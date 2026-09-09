"""G8 Red tests: process-isolated ChildProcessRunner receipt semantics.

These spawn real child processes (like the MCP stdio fixture tests). The hard deadline is
proved by deterministic fault injection: a child whose provider sleeps past the deadline is
killed by the parent's process-group termination and surfaces UNCONFIRMED — no race.
"""

from __future__ import annotations

import json

import pytest

from agent.runtime.contracts import RunStatus
from agent.subagent.contracts import ChildProfile, ChildProviderSpec
from agent.subagent.process_runner import ChildProcessRunner

SCOPE = "scope-1"


def _profile(**overrides) -> ChildProfile:
    base = {
        "runner_version": "subagent-v1",
        "provider_profile_id": "default",
        "provider_destination": "local",
        "workspace_scope_digest": SCOPE,
        "max_input_tokens": 4_000,
        "max_output_tokens": 1_000,
        "limits_digest": "limits-1",
        "hard_deadline_seconds": 30.0,
    }
    base.update(overrides)
    return ChildProfile(**base)


def _fake_spec(*, text="child answer", sleep=0.0) -> ChildProviderSpec:
    return ChildProviderSpec(kind="fake", fake_text=text, sleep_seconds=sleep)


def test_http_child_spec_preserves_explicit_thinking_mode_without_credential() -> None:
    from agent.subagent.child import _spec_from_config
    from agent.subagent.process_runner import _spec_to_dict

    original = ChildProviderSpec(
        kind="http",
        provider_type="openai_compatible",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        credential_env_name="FIRST_AGENT_API_KEY",
        timeout=30.0,
        thinking_mode="disabled",
        request_path="/chat/completions",
        strict_tools=True,
    )

    raw = _spec_to_dict(original)
    assert "credential" not in raw
    assert _spec_from_config(raw) == original


def test_process_runner_terminated_on_completion() -> None:
    """G8: child 完成并 exit 0 + 合法结果 → TERMINATED + COMPLETED。"""
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="focused child review"),
        profile=_profile(),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="review the design", handoff="", parent_idempotency_key="parent:run-1:call-p1"
    )
    assert result.receipt_state == "terminated"
    assert result.status is RunStatus.COMPLETED
    assert result.message == "focused child review"
    assert result.model_calls == 1


def test_process_runner_deadline_kill_is_unconfirmed() -> None:
    """G8: child 的 provider 阻塞超过 hard deadline → parent kill 进程组 → UNCONFIRMED。

    确定性注入（sleep 5s >> deadline 0.5s），无 race：UNCONFIRMED 必然覆盖 child normalization。
    """
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="never reached", sleep=5.0),
        profile=_profile(),
        hard_deadline_seconds=0.5,
    )
    result = runner.run(
        objective="hang past deadline", handoff="", parent_idempotency_key="parent:run-1:call-p2"
    )
    assert result.receipt_state == "unconfirmed", (
        "deadline-kill must produce UNCONFIRMED, not a child normalization"
    )
    assert result.status is RunStatus.FAILED_FATAL
    assert result.reason == "unconfirmed_outcome"


def test_process_runner_nonterminal_is_terminated_known_error() -> None:
    """G8: child 自己报告 nonterminal（tool call）并 exit 0 → TERMINATED + child_nonterminal。

    receipt 区分：child 自行 terminally 报告 = TERMINATED（已知失败）；只有 deadline kill /
    crash = UNCONFIRMED。
    """
    runner = ChildProcessRunner(
        provider_spec=ChildProviderSpec(
            kind="fake", fake_tool=("read_file", {"path": "x"})
        ),
        profile=_profile(),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="try a tool", handoff="", parent_idempotency_key="parent:run-1:call-p3"
    )
    assert result.receipt_state == "terminated"
    assert result.status is not RunStatus.COMPLETED
    assert result.reason == "child_nonterminal"


def test_process_runner_deadline_contract_is_process_terminated() -> None:
    """G8: runner 自身声明 process_terminated capability（进程边界提供，非 socket timeout）。"""
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(),
        profile=_profile(hard_deadline_seconds=12.0),
    )
    cap = runner.deadline_contract
    assert cap.receipt_type == "process_terminated"
    assert cap.hard_deadline_seconds == 12.0


def test_unconfirmed_process_receipt_raises_parent_recovery() -> None:
    """G8: UNCONFIRMED receipt 经 executor 必然抛 SubAgentUnknownOutcomeError → parent recovery。

    deadline-kill 路径端到端：runner UNCONFIRMED → executor raise（不包装成 child_nonterminal）。
    """
    from agent.runtime.contracts import (
        ApprovalGrant,
        ApprovalRequired,
        ToolCall,
        ToolPrepareContext,
    )
    from agent.runtime.tools import KernelToolRuntime
    from agent.subagent.tools import SubAgentUnknownOutcomeError, build_subagent_tool_registrations

    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="never reached", sleep=5.0),
        profile=_profile(),
        hard_deadline_seconds=0.5,
    )
    registrations = build_subagent_tool_registrations(runner)
    runtime = KernelToolRuntime(registrations)
    call = ToolCall("call-1", "subagent__delegate", {"objective": "hang", "handoff": ""})
    prepared = runtime.prepare(call, ToolPrepareContext("c1", "run-1", 1))
    assert isinstance(prepared, ApprovalRequired)
    intent = runtime.prepare(
        call,
        ToolPrepareContext("c1", "run-1", 1),
        approval=ApprovalGrant(prepared.request.request_id, prepared.request.binding_digest),
    )
    with pytest.raises(SubAgentUnknownOutcomeError):
        runtime.invoke(intent)


def test_process_runner_large_stderr_does_not_cause_false_unconfirmed() -> None:
    """F-G8-1: child 在返回前突发 >pipe-buffer 的 stderr。parent 必须 deadlock-safe 地丢弃
    stderr（不 drain 会阻塞 child → 假 UNCONFIRMED），仍返回 TERMINATED，且 stderr 内容绝不
    进入结果。"""
    runner = ChildProcessRunner(
        provider_spec=ChildProviderSpec(
            kind="fake", fake_text="ok", stderr_chars=128 * 1024  # > 64KB pipe buffer
        ),
        profile=_profile(),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="emit stderr", handoff="", parent_idempotency_key="parent:run-1:call-stderr"
    )
    assert result.receipt_state == "terminated", (
        "large stderr must not block the child into a false UNCONFIRMED"
    )
    assert result.status is RunStatus.COMPLETED
    assert result.message == "ok"
    assert "SECRET-STDERR-MARKER" not in result.message
    assert "S" * 1024 not in result.message


def test_process_runner_temp_dir_removed_after_run(tmp_path, monkeypatch) -> None:
    """F-G8-2: per-run temp dir 在成功路径与 deadline/crash cleanup 后都必须消失（不泄漏）。"""
    import tempfile

    created_dirs = []

    def isolated_mkdtemp(*, prefix):  # noqa: ANN001, ANN202
        run_dir = tmp_path / f"{prefix}{len(created_dirs)}"
        run_dir.mkdir(mode=0o700)
        created_dirs.append(run_dir)
        return str(run_dir)

    # 系统 temp 是进程共享 namespace；比较全机 glob 会被同时运行的另一个
    # first-agent 干扰。固定本测试实际创建的目录，仍验证同一产品清理路径。
    monkeypatch.setattr(tempfile, "mkdtemp", isolated_mkdtemp)

    # 成功路径
    runner_ok = ChildProcessRunner(
        provider_spec=_fake_spec(text="done"),
        profile=_profile(),
        hard_deadline_seconds=120.0,
    )
    res_ok = runner_ok.run(
        objective="ok", handoff="", parent_idempotency_key="parent:run-1:dir-ok"
    )
    assert res_ok.receipt_state == "terminated"
    assert created_dirs and not created_dirs[-1].exists(), "temp dir leaked after success"

    # deadline-kill cleanup 路径
    runner_kill = ChildProcessRunner(
        provider_spec=_fake_spec(text="x", sleep=5.0),
        profile=_profile(),
        hard_deadline_seconds=0.5,
    )
    res_kill = runner_kill.run(
        objective="hang", handoff="", parent_idempotency_key="parent:run-1:dir-kill"
    )
    assert res_kill.receipt_state == "unconfirmed"
    assert not created_dirs[-1].exists(), "temp dir leaked after deadline cleanup"


def test_process_runner_oversized_stdout_is_unconfirmed(monkeypatch) -> None:
    """F-G8 (defense-in-depth): parent 读取 child stdout 有界；超出上限（oversized）按
    UNCONFIRMED 拒绝，不无界 read。用 monkeypatch 把上界压到极小，使正常 child 输出也超限。"""
    import agent.subagent.process_runner as pr_mod

    monkeypatch.setattr(pr_mod, "_MAX_RESULT_BYTES", 4)
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="normal sized child answer"),
        profile=_profile(),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="oversized stdout",
        handoff="",
        parent_idempotency_key="parent:run-1:call-oversized",
    )
    assert result.receipt_state == "unconfirmed"


def test_parse_result_rejects_malformed_and_oversized() -> None:
    """F-G8 (unit): _parse_result 对 malformed JSON / 非 dict / 缺 status 的 stdout 返回 None
    （→ UNCONFIRMED）。"""
    from agent.subagent.process_runner import _parse_result

    assert _parse_result(b"not json{") is None
    assert _parse_result(b"[1, 2, 3]") is None  # valid JSON but not an object
    assert _parse_result(b'{"message": "no status"}') is None  # missing status
    assert _parse_result(b'{"status": "completed", "message": "ok"}') == {
        "status": "completed",
        "message": "ok",
    }


def test_015_config_dir_cleanup_retries_transient_rmdir_failure(
    tmp_path, monkeypatch
) -> None:
    """F5/U10 review-hardening：清理的一次瞬时 ``rmdir`` 失败不得静默泄漏 per-run 目录。

    全 suite 负载下实测（U10 复验 1 failed, 1026 passed）：``unlink``/``rmdir`` 各自
    ``suppress(OSError)`` 无重试——负载下一次瞬时失败即目录存留（F-G8-2 要求
    "per-run temp dir 在成功路径必须消失"）。Red：注入首调失败的 rmdir；清理必须有界
    重试到目录消失。receipt 分类不受影响（既有合同）。
    """

    from pathlib import Path as _Path

    attempts: dict[str, int] = {}
    real_rmdir = _Path.rmdir

    def flaky_rmdir(self):  # noqa: ANN001, ANN202
        key = str(self)
        attempts[key] = attempts.get(key, 0) + 1
        if attempts[key] == 1 and "subagent-child-" in self.name:
            raise OSError("transient ENOTEMPTY under load")
        return real_rmdir(self)

    monkeypatch.setattr(_Path, "rmdir", flaky_rmdir)
    import tempfile as _tempfile

    run_dir = tmp_path / "subagent-child-transient"

    def isolated_mkdtemp(*, prefix):  # noqa: ANN001, ANN202
        assert prefix == "subagent-child-"
        run_dir.mkdir(mode=0o700)
        return str(run_dir)

    monkeypatch.setattr(_tempfile, "mkdtemp", isolated_mkdtemp)
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="cleanup-probe"),
        profile=_profile(),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="cleanup", handoff="", parent_idempotency_key="parent:run-1:dir-retry"
    )
    assert result.receipt_state == "terminated"
    assert not run_dir.exists(), "transient rmdir failure must not leak the per-run dir"


def test_015_persistent_config_cleanup_failure_cannot_report_success(
    tmp_path, monkeypatch
) -> None:
    """持续清理失败时 child 已终止，但整体调用必须准确失败。"""

    import tempfile as _tempfile
    from pathlib import Path as _Path

    run_dir = tmp_path / "subagent-child-persistent"

    def make_run_dir(*, prefix):  # noqa: ANN001, ANN202
        assert prefix == "subagent-child-"
        run_dir.mkdir(mode=0o700)
        return str(run_dir)

    real_rmdir = _Path.rmdir

    def persistent_rmdir(self):  # noqa: ANN001, ANN202
        if self == run_dir:
            raise OSError("persistent cleanup failure")
        return real_rmdir(self)

    monkeypatch.setattr(_tempfile, "mkdtemp", make_run_dir)
    monkeypatch.setattr(_Path, "rmdir", persistent_rmdir)
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="cleanup-probe"),
        profile=_profile(),
        hard_deadline_seconds=120.0,
    )

    result = runner.run(
        objective="cleanup",
        handoff="",
        parent_idempotency_key="parent:run-1:persistent-cleanup",
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.reason == "cleanup_failed"
    assert result.receipt_state == "terminated"
    assert run_dir.exists()


# ---------------------------------------------------------------------------
# 017 Slice 2：child 结果 envelope 的共同 8192-byte UTF-8 预算合同
# ---------------------------------------------------------------------------

# 测试独立钉住预算与产品上限的数值（不 import 生产常量），作为行为合同的 oracle。
_ENVELOPE_BUDGET_BYTES = 8_192
_CHILD_MESSAGE_CAP_CHARS = 4_000
# '{"status": "completed", "message": ""}' 的固定 envelope 开销（含 message 引号）。
_ENVELOPE_OVERHEAD_BYTES = 38


class _CompletedChildRuntime:
    """合成 runtime：不经 provider，直接返回指定 message 的 completed 结果。"""

    def __init__(self, message: str) -> None:
        self._message = message

    def run_turn(self, action, snapshot):  # noqa: ANN001, ANN202
        from types import SimpleNamespace

        return SimpleNamespace(status=RunStatus.COMPLETED, message=self._message)


class _StubChildStore:
    def load(self):  # noqa: ANN201
        return None


def _write_child_seam_config(tmp_path) -> object:
    config = {
        "spec": {"kind": "fake", "fake_text": "unused-by-stub-runtime"},
        "profile": {
            "runner_version": "subagent-v1",
            "provider_profile_id": "default",
            "provider_destination": "local",
            "workspace_scope_digest": SCOPE,
            "max_input_tokens": 4_000,
            "max_output_tokens": 1_000,
            "limits_digest": "limits-1",
            "hard_deadline_seconds": 30.0,
        },
        "objective": "envelope budget",
        "handoff": "",
        "parent_idempotency_key": "parent:run-1:envelope-seam",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return path


def _capture_child_main_stdout(
    tmp_path, monkeypatch, capsysbinary, message: str
) -> bytes:
    """对实际 ``child.main`` 输出 seam 注入返回 completed 的合成 runtime，捕获真实 stdout bytes。"""
    import agent.subagent.runner as runner_mod
    from agent.subagent.child import main as child_main

    monkeypatch.setattr(
        runner_mod,
        "build_child_runtime",
        lambda provider, profile, **kwargs: (  # noqa: ANN001, ANN202, ARG005
            _CompletedChildRuntime(message),
            _StubChildStore(),
        ),
    )
    rc = child_main([str(_write_child_seam_config(tmp_path))])
    assert rc == 0, "child must exit 0 after terminally reporting its result"
    return capsysbinary.readouterr().out


@pytest.mark.parametrize(
    ("label", "message"),
    [
        pytest.param("cjk", "冻结修复" * 1_000, id="cjk"),
        pytest.param("emoji", "🚀🧊" * 2_000, id="emoji"),
        pytest.param("quotes", '"' * 2_000 + "冻结" * 1_000, id="quotes"),
        pytest.param("backslash", "\\" * 2_000 + "修复" * 1_000, id="backslash"),
        pytest.param("control-chars", "\x01" * 4_000, id="control-chars"),
        pytest.param("mixed", ('"\\' + "\x07" + "冻🚀a" + '"') * 600, id="mixed"),
        pytest.param("short-ascii", "ok", id="short-ascii"),
        # 2718 个 3-byte CJK 字符：envelope 恰好 8192 bytes，必须原样保留。
        pytest.param("boundary-exact", "冻" * 2_718, id="boundary-exact"),
    ],
)
def test_child_main_envelope_fits_shared_utf8_byte_budget(
    tmp_path, monkeypatch, capsysbinary, label, message
) -> None:
    """017-2 Red：child 写出的完整 envelope 必须 ≤ 8192 UTF-8 bytes 且仍是合法 JSON。

    旧行为只按 4000 字符截断再 ``ensure_ascii=False`` 序列化：CJK/emoji 的多字节
    UTF-8 与引号/反斜杠/控制字符的 JSON 转义让完整 envelope 超过 parent 的
    8192-byte 有界读取，合法 completed 结果被误判 oversized → UNCONFIRMED。
    """
    blob = _capture_child_main_stdout(tmp_path, monkeypatch, capsysbinary, message)

    assert len(blob) <= _ENVELOPE_BUDGET_BYTES, (
        f"[{label}] envelope is {len(blob)} bytes, exceeding the shared 8192-byte budget"
    )
    parsed = json.loads(blob.decode("utf-8"))
    assert set(parsed) == {"status", "message"}, "no new protocol fields may be added"
    assert parsed["status"] == "completed", "status must not change"
    capped = message[:_CHILD_MESSAGE_CAP_CHARS]
    assert capped.startswith(parsed["message"]), (
        f"[{label}] emitted message must be a prefix of the original child message"
    )
    full_blob = json.dumps(
        {"status": "completed", "message": capped}, ensure_ascii=False
    ).encode("utf-8")
    if len(full_blob) <= _ENVELOPE_BUDGET_BYTES:
        assert parsed["message"] == capped, (
            f"[{label}] messages whose full envelope fits must be preserved verbatim"
        )


def test_process_runner_long_cjk_completed_is_terminated_max_prefix() -> None:
    """017-2 Red（真实 ChildProcessRunner + fake provider）：长中文 completed 路径。

    "冻"×4000 的完整 envelope 为 38 + 12_000 bytes；修复后 child 保留满足预算的最大
    字符前缀 (8192−38)//3 = 2718 字符（envelope 恰 8192 bytes），receipt 仍为 TERMINATED。
    """
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="冻" * 4_000),
        profile=_profile(max_output_tokens=20_000),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="长中文结果", handoff="", parent_idempotency_key="parent:run-1:cjk-long"
    )
    assert result.receipt_state == "terminated"
    assert result.status is RunStatus.COMPLETED
    assert result.reason == "completed"
    assert result.message == "冻" * ((_ENVELOPE_BUDGET_BYTES - _ENVELOPE_OVERHEAD_BYTES) // 3)


def test_process_runner_long_emoji_completed_is_terminated_max_prefix() -> None:
    """017-2 Red（真实 runner）：长 emoji（UTF-8 4 bytes/char）completed 路径同合同。"""
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="🚀" * 4_000),
        profile=_profile(max_output_tokens=20_000),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="emoji 结果", handoff="", parent_idempotency_key="parent:run-1:emoji-long"
    )
    assert result.receipt_state == "terminated"
    assert result.status is RunStatus.COMPLETED
    assert result.reason == "completed"
    assert result.message == "🚀" * ((_ENVELOPE_BUDGET_BYTES - _ENVELOPE_OVERHEAD_BYTES) // 4)


def test_process_runner_envelope_exact_boundary_is_accepted_verbatim() -> None:
    """精确边界："冻"×2718 的完整 envelope 恰为 8192 bytes，必须原样接受不截断。

    parent 侧 ``read(max_bytes + 1)`` 接受 ``len == max``；恰好等于预算的合法结果
    不得被截断，也不得被判 oversized。
    """
    text = "冻" * 2_718
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text=text),
        profile=_profile(max_output_tokens=20_000),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="exact boundary", handoff="", parent_idempotency_key="parent:run-1:boundary"
    )
    assert result.receipt_state == "terminated"
    assert result.status is RunStatus.COMPLETED
    assert result.message == text


def test_process_runner_envelope_one_char_over_boundary_still_completed() -> None:
    """017-2 Red（真实 runner）：超预算 1 字符 → 截最大前缀，而不是 oversized → UNCONFIRMED。

    "冻"×2719 的完整 envelope 为 8195 bytes；child 必须退回最大前缀 "冻"×2718
    （envelope 恰 8192），而不是把合法 completed 结果变成 oversized。
    """
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="冻" * 2_719),
        profile=_profile(max_output_tokens=20_000),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="one over boundary",
        handoff="",
        parent_idempotency_key="parent:run-1:boundary-plus-one",
    )
    assert result.receipt_state == "terminated"
    assert result.status is RunStatus.COMPLETED
    assert result.message == "冻" * 2_718

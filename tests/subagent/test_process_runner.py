"""G8 Red tests: process-isolated ChildProcessRunner receipt semantics.

These spawn real child processes (like the MCP stdio fixture tests). The hard deadline is
proved by deterministic fault injection: a child whose provider sleeps past the deadline is
killed by the parent's process-group termination and surfaces UNCONFIRMED — no race.
"""

from __future__ import annotations

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
        hard_deadline_seconds=20.0,
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
        hard_deadline_seconds=20.0,
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
        hard_deadline_seconds=20.0,
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
    import glob
    import tempfile

    tmp_root = tempfile.gettempdir()

    def _subagent_dirs() -> set[str]:
        return set(glob.glob(f"{tmp_root}/subagent-child-*"))

    # 成功路径
    before = _subagent_dirs()
    runner_ok = ChildProcessRunner(
        provider_spec=_fake_spec(text="done"),
        profile=_profile(),
        hard_deadline_seconds=20.0,
    )
    res_ok = runner_ok.run(
        objective="ok", handoff="", parent_idempotency_key="parent:run-1:dir-ok"
    )
    assert res_ok.receipt_state == "terminated"
    assert _subagent_dirs() == before, "temp dir leaked after success"

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
    assert _subagent_dirs() == before, "temp dir leaked after deadline cleanup"


def test_process_runner_oversized_stdout_is_unconfirmed(monkeypatch) -> None:
    """F-G8 (defense-in-depth): parent 读取 child stdout 有界；超出上限（oversized）按
    UNCONFIRMED 拒绝，不无界 read。用 monkeypatch 把上界压到极小，使正常 child 输出也超限。"""
    import agent.subagent.process_runner as pr_mod

    monkeypatch.setattr(pr_mod, "_MAX_RESULT_BYTES", 4)
    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="normal sized child answer"),
        profile=_profile(),
        hard_deadline_seconds=20.0,
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

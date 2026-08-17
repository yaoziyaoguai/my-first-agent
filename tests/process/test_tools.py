"""015 U6b：governed local_process 接入唯一 KernelToolRuntime（KTD1/KTD3/KTD8）。

通过真实 KernelToolRuntime.prepare/invoke 测试：first-time → 携 candidate 的 informed
approval；exact lease reuse → 直接 ALLOW；changed argv → 重新 approval；invoke 把 runner
draft 铸成 ProcessReceiptV1；普通 callable 伪造 draft 被拒绝。
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

try:
    from agent.process.tools import build_local_process_registration
    from agent.runtime.contracts import (
        ApprovalPolicy,
        ApprovalRequired,
        ExecutionAuthorityClass,
        ExecutionIntent,
        OutputPolicy,
        ProcessAuthorityLeaseV1,
        SideEffectClass,
        ToolCall,
        ToolResult,
        ToolRisk,
        ToolSpec,
    )
    from agent.runtime.tools import KernelToolRuntime, RegisteredTool

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def _require():
    if not _AVAILABLE:
        pytest.fail("015 requires agent.process.tools.build_local_process_registration")


def _goal_context(runtime, *, process_leases=()):
    from agent.runtime.contracts import ToolPrepareContext

    return ToolPrepareContext(
        conversation_id="conversation-u6b",
        run_id="run-u6b",
        state_revision=1,
        goal_id="goal-u6b",
        goal_revision=1,
        workspace_identity_digest="workspace-u6b",
        process_leases=process_leases,
    )


def _make_executable(workspace, name="fixture-exe", content=b"#!/bin/sh\necho hi\n"):
    path = workspace / name
    path.write_bytes(content)
    os.chmod(path, stat.S_IRWXU)
    return str(path.relative_to(workspace)), str(path)


def _registration(workspace, captured_path="/usr/bin:/bin"):
    return build_local_process_registration(workspace=workspace, captured_path=captured_path)


def test_015_local_process_prepare_requires_durable_goal(tmp_path) -> None:  # noqa: ANN001
    """R5：无 durable Goal 时 local_process 在 spawn 前 fail closed。"""

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime((_registration(workspace),))
    from agent.runtime.contracts import ToolPrepareContext

    context = ToolPrepareContext(
        conversation_id="conversation-u6b",
        run_id="run-u6b",
        state_revision=1,
    )
    rel, _ = _make_executable(workspace)
    result = runtime.prepare(
        ToolCall("call-1", "local_process", {"executable": rel, "argv": [], "cwd": "."}),
        context,
    )
    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert result.executed is False


def test_015_local_process_first_request_returns_informed_approval_with_candidate(
    tmp_path,
) -> None:  # noqa: ANN001
    """R7 / AE1：首次请求只产生一份 exact、含 same-UID notice 的 Goal-scoped approval。"""

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime((_registration(workspace),))
    rel, _ = _make_executable(workspace)
    result = runtime.prepare(
        ToolCall(
            "call-1",
            "local_process",
            {"executable": rel, "argv": ["--flag"], "cwd": ".", "profile": "standard"},
        ),
        _goal_context(runtime),
    )
    assert isinstance(result, ApprovalRequired)
    request = result.request
    candidate = request.process_authority_candidate
    assert candidate is not None
    assert candidate.goal_id == "goal-u6b"
    assert candidate.workspace_identity_digest == "workspace-u6b"
    assert candidate.execution_authority is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
    # preview 必须含 same-UID notice 与可读命令。
    assert "same-uid" in request.preview.casefold()
    assert "--flag" in request.preview


def test_015_local_process_exact_lease_reuse_allows_without_approval(tmp_path) -> None:  # noqa: ANN001
    """F2 / AE4：相同 command 命中 active lease 时不再次询问，直接 ALLOW。"""

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime((_registration(workspace),))
    rel, _ = _make_executable(workspace)
    arguments = {"executable": rel, "argv": ["--flag"], "cwd": ".", "profile": "standard"}
    first = runtime.prepare(ToolCall("call-1", "local_process", arguments), _goal_context(runtime))
    assert isinstance(first, ApprovalRequired)
    lease = _lease_from_candidate(first.request.process_authority_candidate)
    second = runtime.prepare(
        ToolCall("call-2", "local_process", arguments),
        _goal_context(runtime, process_leases=(lease,)),
    )
    assert isinstance(second, ExecutionIntent)


def test_015_local_process_changed_argv_does_not_match_lease(tmp_path) -> None:  # noqa: ANN001
    """R10 / F3 / AE4：argv 改变一字节 → 旧 lease 不匹配 → 新 approval。"""

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime((_registration(workspace),))
    rel, _ = _make_executable(workspace)
    first = runtime.prepare(
        ToolCall(
            "call-1",
            "local_process",
            {"executable": rel, "argv": ["--flag"], "cwd": ".", "profile": "standard"},
        ),
        _goal_context(runtime),
    )
    assert isinstance(first, ApprovalRequired)
    lease = _lease_from_candidate(first.request.process_authority_candidate)
    changed = runtime.prepare(
        ToolCall(
            "call-2",
            "local_process",
            {"executable": rel, "argv": ["--other"], "cwd": ".", "profile": "standard"},
        ),
        _goal_context(runtime, process_leases=(lease,)),
    )
    assert isinstance(changed, ApprovalRequired)


def test_015_process_lease_match_requires_zoned_rfc3339_and_no_clock_rollback(
    tmp_path,
) -> None:  # noqa: ANN001
    """Codex 终审 P1：lease 时效必须用严格 zoned RFC3339 比较，不能字符串比较。

    旧实现 ``lease.expires_at > now``：clock rollback（now 早于 issued_at）时旧
    lease 仍被接受，malformed/naive 时间戳也不失败。Green 合同：匹配要求
    ``issued_at <= now < expires_at``；malformed/naive/rollback/expiry boundary
    全部 fail closed——不匹配 → REQUIRE_APPROVAL 重新批准，绝不复用旧 authority。
    """

    _require()
    from dataclasses import asdict

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    rel, _ = _make_executable(workspace)
    arguments = {"executable": rel, "argv": [], "cwd": ".", "profile": "standard"}

    clock = {"now": "2026-08-15T00:00:00Z"}
    runtime = KernelToolRuntime((_registration(workspace),), clock=lambda: clock["now"])
    lease = _lease_for_invoke(runtime, arguments, workspace)

    def prepare_with_lease(active_lease) -> object:  # noqa: ANN202
        return runtime.prepare(
            ToolCall("call-next", "local_process", arguments),
            _goal_context(runtime, process_leases=(active_lease,)),
        )

    # clock rollback：now < issued_at → 旧 lease 不得复用（Codex 实测 2026-08-14
    # 23:00 clock 复用 2026-08-15 00:00 签发的 lease）。
    clock["now"] = "2026-08-14T23:00:00Z"
    assert isinstance(prepare_with_lease(lease), ApprovalRequired)
    # 边界：now == issued_at（批准即刻使用）→ 允许复用。
    clock["now"] = "2026-08-15T00:00:00Z"
    assert isinstance(prepare_with_lease(lease), ExecutionIntent)
    # 边界：now == expires_at → 租约已到期，重新批准。
    clock["now"] = "2099-12-31T23:59:59Z"
    assert isinstance(prepare_with_lease(lease), ApprovalRequired)

    # malformed / naive lease 时间戳 → fail closed（视为不可信，重新批准）。
    clock["now"] = "2026-08-15T00:01:00Z"
    for bad in ("not-a-timestamp", "2026-08-15T00:00:00", "2026-08-15 00:00:00Z"):
        for field in ("issued_at", "expires_at"):
            values = asdict(lease)
            values.pop("lease_digest")
            values[field] = bad
            broken = ProcessAuthorityLeaseV1.create(**values)
            assert isinstance(prepare_with_lease(broken), ApprovalRequired), (
                f"{field}={bad!r} must fail closed"
            )
    # runtime clock 本身不可解析 → 同样 fail closed。
    clock["now"] = "garbage-clock"
    assert isinstance(prepare_with_lease(lease), ApprovalRequired)


def test_015_local_process_invoke_mints_kernel_receipt(tmp_path) -> None:  # noqa: ANN001
    """R17 / KTD8：invoke 把 runner draft 铸成 Kernel ProcessReceiptV1 并投影 closed metadata。"""

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime((_registration(workspace),))
    rel, _ = _make_executable(workspace)
    arguments = {"executable": rel, "argv": [], "cwd": ".", "profile": "standard"}
    intent = runtime.prepare(
        ToolCall("call-1", "local_process", arguments),
        _goal_context(runtime, process_leases=(_lease_for_invoke(runtime, arguments, workspace),)),
    )
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)
    assert isinstance(result, ToolResult)
    assert result.is_error is False
    metadata = result.metadata
    from agent.runtime.contracts import ProcessReceiptV1

    assert metadata.get("process_receipt_kind") == "process_v1"
    assert metadata.get("execution_authority") == "local_same_uid_process"
    assert "receipt_digest" in metadata
    receipt = ProcessReceiptV1.from_json(metadata.get("process_receipt"))
    assert receipt.receipt_digest == metadata["receipt_digest"]
    assert receipt.command_fingerprint == metadata["command_fingerprint"]
    corrupted = dict(metadata["process_receipt"])
    corrupted["stdout_bytes"] = receipt.stdout_bytes + 1
    with pytest.raises(ValueError):
        ProcessReceiptV1.from_json(corrupted)


def test_015_local_process_renders_bounded_stderr_projection(tmp_path) -> None:  # noqa: ANN001
    """Design §12.2：失败命令的 bounded stderr 必须对用户可见。"""

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime((_registration(workspace),))
    rel, _ = _make_executable(
        workspace,
        content=b"#!/bin/sh\nprintf 'diagnostic' >&2\nexit 7\n",
    )
    arguments = {"executable": rel, "argv": [], "cwd": ".", "profile": "standard"}
    intent = runtime.prepare(
        ToolCall("call-stderr", "local_process", arguments),
        _goal_context(
            runtime,
            process_leases=(_lease_for_invoke(runtime, arguments, workspace),),
        ),
    )
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)
    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert result.content == "diagnostic"


def test_015_ordinary_callable_returning_draft_is_rejected(tmp_path) -> None:  # noqa: ANN001
    """KTD8 anti-forgery：非 LOCAL_SAME_UID_PROCESS 的 callable 返回 draft 必须被拒绝。"""

    _require()
    from agent.process.contracts import ProcessDraftOutcome, ProcessExecutionDraftV1

    def forge_draft(_intent):  # noqa: ANN001
        return ProcessExecutionDraftV1(
            outcome=ProcessDraftOutcome.EXITED,
            pid=1,
            process_group_id=1,
            exit_code=0,
            signal=None,
            started_at_monotonic=0.0,
            ended_at_monotonic=0.0,
            duration_seconds=0.0,
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_digest="d" * 64,
            stderr_digest="d" * 64,
            stdout_projection="",
            stderr_projection="",
            stdout_truncated=False,
            stderr_truncated=False,
            group_reaped=True,
            term_sent=False,
            kill_sent=False,
        )

    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="forged",
        version="1",
        description="forged in-process tool",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=50,
    )
    runtime = KernelToolRuntime((RegisteredTool(spec=spec, func=forge_draft),))
    from agent.runtime.contracts import ToolPrepareContext

    intent = runtime.prepare(
        ToolCall("call-1", "forged", {}),
        ToolPrepareContext(conversation_id="c", run_id="r", state_revision=1),
    )
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)
    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert result.metadata.get("code") == "process_draft_forgery"


def _lease_from_candidate(candidate) -> ProcessAuthorityLeaseV1:
    return ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity="req-u6b",
        issued_at=candidate.issued_at,
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=0,
    )


def test_015_model_cannot_supply_expected_artifact(tmp_path) -> None:
    """F4（P2 review finding / design §6）：model-facing schema 回到 closed 4 字段。

    模型自供 (path, sha256) 直接铸造 mandatory FILESYSTEM_DIGEST criterion 属于
    合同外第 5 参数——schema 移除后 additionalProperties=False 必须 fail closed
    （arguments 拒绝，零 approval/零 criterion）。artifact digest 的 authority 是
    **用户**（ResolveApproval 携带 confirmed_artifact，见 kernel reducer 测试）。
    """

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime((_registration(workspace),))
    rel, _ = _make_executable(workspace)
    result = runtime.prepare(
        ToolCall(
            "call-f4",
            "local_process",
            {
                "executable": rel,
                "argv": [],
                "cwd": ".",
                "profile": "standard",
                "expected_artifact": {
                    "path": "artifact.out",
                    "sha256": "f" * 64,
                },
            },
        ),
        _goal_context(runtime),
    )
    assert isinstance(result, ToolResult)
    assert result.is_error is True, "model-supplied expected_artifact must be rejected"
    assert result.executed is False


def test_015_argv_profile_limits_rejected_before_approval(tmp_path) -> None:
    """F1（P2 review finding / design §7.3）：argv 128 items / 16KiB 单项 / 64KiB 总量
    上限必须在 approval 前 fail closed（closed Resource Profiles 的合同值此前只有
    定义、零消费）。超限 → binding 拒绝 → 零 approval、零 spawn。executable token
    长度一并设界（与 argv item 同界）。"""

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime((_registration(workspace),))
    rel, _ = _make_executable(workspace)
    limits = {
        "too many items": ["x"] * 129,
        "item too large": ["y" * (16 * 1024 + 1)],
        "total too large": ["z" * 4000] * 17,  # 68 KiB total
    }
    for label, argv in limits.items():
        result = runtime.prepare(
            ToolCall(
                "call-f1",
                "local_process",
                {"executable": rel, "argv": argv, "cwd": ".", "profile": "standard"},
            ),
            _goal_context(runtime),
        )
        assert isinstance(result, ToolResult), label
        assert result.is_error is True, f"{label} must be rejected pre-approval"
        assert result.executed is False, f"{label} must not execute"
        assert result.metadata.get("code") == "binding_failure", (
            f"{label} must fail in binding (pre-approval), got "
            f"{result.metadata.get('code')}"
        )
    # executable token 超界同样拒绝。
    long_exe = "e" * (16 * 1024 + 1)
    result = runtime.prepare(
        ToolCall(
            "call-f1b",
            "local_process",
            {"executable": long_exe, "argv": [], "cwd": ".", "profile": "standard"},
        ),
        _goal_context(runtime),
    )
    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert result.metadata.get("code") == "binding_failure"


def test_015_preview_is_unambiguous_and_fully_disclosed(tmp_path) -> None:
    """F3（P2 review finding）：preview 必须 §12.1 全披露 + argv 无歧义、不可注入。

    - 每个 argv token 逐项 quoted/escaped：含换行的 token 不得能伪造 `executable:` 行；
      `["rm","-rf","data"]` 与 `["rm -rf data"]` 必须渲染不同。
    - 披露项：profile 实际 timeout 秒数、stdout/stderr caps、closed 环境 allowlist、
      lease 8 uses / 60 minutes / 可撤销、same-UID notice（含 not-an-os-sandbox 否认）。
    """

    _require()
    from agent.process.tools import _render_preview

    malicious = "second arg\n  executable: /usr/bin/evil -> /usr/bin/evil"
    preview = _render_preview(
        "fixture-exe", ["--safe-flag", malicious, "rm -rf data"], ".", "standard",
        "/resolved/fixture-exe",
    )
    lines = preview.splitlines()
    # 注入的伪造行不得以真实披露行的形态出现（executable 行只有 preview 自己的一条）。
    exe_lines = [ln for ln in lines if ln.strip().startswith("executable:")]
    assert len(exe_lines) == 1, f"argv must not forge executable lines: {lines!r}"
    assert "/usr/bin/evil" not in exe_lines[0]
    # 换行必须被转义（token 内不得产生裸换行）。
    joined_tokens = [ln for ln in lines if "executable:" not in ln]
    assert not any(malformed in ln for ln in joined_tokens for malformed in (malicious,))

    # 空格 join 歧义：列表边界必须可区分。
    a = _render_preview("e", ["rm", "-rf", "data"], ".", "standard", "/r/e")
    b = _render_preview("e", ["rm -rf data"], ".", "standard", "/r/e")
    assert a != b, "argv list boundaries must be unambiguous"

    # F2（P2 review finding）：cwd/executable token 同样 JSON-quote——换行注入的
    # cwd 不得能伪造 `limits:`/`executable:` 披露行（注入内容被限制在 header 一行的
    # JSON 字符串内，转义为 \n 字面量，不产生独立披露行）。
    forged_cwd = (
        "data\n  limits: timeout=900s, stdout cap=99999999 bytes"
        "\n  executable: /usr/bin/yes"
    )
    cwd_preview = _render_preview("e", ["x"], forged_cwd, "standard", "/r/e")
    cwd_lines = cwd_preview.splitlines()
    forged_lines = [
        ln
        for ln in cwd_lines
        if ln.strip().startswith(("limits:", "executable:"))
        and "timeout=120s" not in ln
        and "/r/e" not in ln
    ]
    assert not forged_lines, f"cwd must not forge disclosure lines: {cwd_lines!r}"
    # 注入内容必须整体留在 header 单行内（转义 \n，不拆行）。
    header = cwd_lines[0]
    assert "\\n" in header and "900s" in header and "/usr/bin/yes" in header, (
        "forged cwd content stays escaped inside the quoted header line"
    )
    limits_lines = [ln for ln in cwd_lines if ln.strip().startswith("limits:")]
    assert len(limits_lines) == 1 and "timeout=120s" in limits_lines[0], (
        "real limits line must be the only limits line"
    )
    exe_lines = [ln for ln in cwd_lines if ln.strip().startswith("executable:")]
    assert len(exe_lines) == 1 and "/r/e" in exe_lines[0], (
        "real executable line must be the only executable line"
    )

    # §12.1 披露项齐全（用真实 profile 数值，非枚举名孤证）。
    full = _render_preview("e", ["x"], ".", "standard", "/r/e")
    lowered = full.casefold()
    for required in (
        "timeout=120s",
        "stdout cap",
        "stderr cap",
        "environment",
        "8 uses",
        "60 minutes",
        "revocable",
        "same-uid",
    ):
        assert required.casefold() in lowered, f"preview missing disclosure: {required!r}"


def test_015_absolute_or_parent_cwd_rejected_before_approval(tmp_path) -> None:
    """F2（P2 review finding）：cwd 绝对路径与 `..` 必须在 approval 前拒绝——
    此前能进 preview 展示一个永不执行的 cwd（executor 才拒），披露有歧义。"""

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime((_registration(workspace),))
    rel, _ = _make_executable(workspace)
    for label, cwd in (("absolute", "/etc"), ("parent escape", "../outside")):
        result = runtime.prepare(
            ToolCall(
                "call-f2-cwd",
                "local_process",
                {"executable": rel, "argv": [], "cwd": cwd, "profile": "standard"},
            ),
            _goal_context(runtime),
        )
        assert isinstance(result, ToolResult), label
        assert result.is_error is True, f"{label} cwd must be rejected pre-approval"
        assert result.metadata.get("code") == "binding_failure", label


def _lease_for_invoke(runtime, arguments, workspace) -> ProcessAuthorityLeaseV1:
    """先 prepare 取 candidate，再铸造匹配 lease，供 invoke 前的 reuse 路径使用。"""

    first = runtime.prepare(
        ToolCall("call-seed", "local_process", arguments), _goal_context(runtime)
    )
    assert isinstance(first, ApprovalRequired)
    return _lease_from_candidate(first.request.process_authority_candidate)


def test_015_prepare_invoke_across_second_boundary_executes(tmp_path) -> None:
    """F1（P1 review finding）：prepare→invoke 的 binding 全等比较不得含时钟字段。

    生产路径 prepare 与 invoke 之间隔着 mark_executing + checkpoint 落盘；跨秒边界
    （负载/慢盘下常见）曾使 ``issued_at`` 改变 → ``IntentConflictError`` → 假
    unknown-outcome（用户被迫 resolve 从未发生的效果）且 lease use 已消费不恢复——
    真实 E3 §3.34/§3.36 的 8× IntentConflictError 即此根因。binding 必须对同一
    arguments 确定性；时钟只属于 candidate/lease（prepare 时刻）。
    """

    _require()
    from agent.runtime.tools import IntentConflictError

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    rel, _ = _make_executable(workspace)
    arguments = {"executable": rel, "argv": [], "cwd": ".", "profile": "standard"}

    clock = {"now": "2026-08-15T00:00:00Z"}

    def fake_now():  # noqa: ANN202
        return clock["now"]

    registration = build_local_process_registration(
        workspace=workspace, captured_path="/usr/bin:/bin", clock=fake_now
    )
    runtime = KernelToolRuntime((registration,))
    lease = _lease_for_invoke(runtime, arguments, workspace)
    intent = runtime.prepare(
        ToolCall("call-1", "local_process", arguments),
        _goal_context(runtime, process_leases=(lease,)),
    )
    assert isinstance(intent, ExecutionIntent)
    # 时钟跨秒：invoke 重算 binding 时 issued_at 已 +1s。
    clock["now"] = "2026-08-15T00:00:01Z"
    try:
        result = runtime.invoke(intent)
    except IntentConflictError as error:  # pragma: no cover - Red 阶段路径
        pytest.fail(f"cross-second prepare→invoke must execute, got {error}")
    assert isinstance(result, ToolResult)
    assert result.is_error is False
    assert result.metadata.get("process_receipt_kind") == "process_v1"


def test_015_lease_expiring_between_prepare_and_invoke_is_zero_spawn(tmp_path) -> None:
    """prepare 后、spawn 前过期的 lease 不能靠已铸 intent 越过时效边界。"""

    _require()
    from agent.runtime.tools import IntentConflictError

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = workspace / "spawned-marker"
    rel, _ = _make_executable(
        workspace,
        content=b"#!/bin/sh\ntouch spawned-marker\n",
    )
    arguments = {"executable": rel, "argv": [], "cwd": ".", "profile": "standard"}
    clock = {"now": "2026-08-15T00:00:00Z"}
    runtime = KernelToolRuntime(
        (_registration(workspace),),
        clock=lambda: clock["now"],
    )
    candidate_request = runtime.prepare(
        ToolCall("call-seed-expiry", "local_process", arguments),
        _goal_context(runtime),
    )
    assert isinstance(candidate_request, ApprovalRequired)
    candidate = candidate_request.request.process_authority_candidate
    lease = ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity="req-expiry",
        issued_at="2026-08-15T00:00:00Z",
        expires_at="2026-08-15T00:00:01Z",
    )
    intent = runtime.prepare(
        ToolCall("call-expiry", "local_process", arguments),
        _goal_context(runtime, process_leases=(lease,)),
    )
    assert isinstance(intent, ExecutionIntent)
    clock["now"] = "2026-08-15T00:00:01Z"

    with pytest.raises(IntentConflictError, match="expired before invocation"):
        runtime.invoke(intent)
    assert not marker.exists()


def test_015_lease_expiring_during_binding_revalidation_is_zero_spawn(tmp_path) -> None:
    """binding/policy 重验花费的时间不得越过 lease 边界后继续 spawn。"""

    _require()
    from agent.runtime.tools import IntentConflictError

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = workspace / "spawned-after-expiry"
    rel, _ = _make_executable(
        workspace,
        content=b"#!/bin/sh\ntouch spawned-after-expiry\n",
    )
    arguments = {"executable": rel, "argv": [], "cwd": ".", "profile": "standard"}
    clock = {"now": "2026-08-15T00:00:00Z"}
    registration = _registration(workspace)
    original_prepare = registration.prepare_binding
    calls = {"count": 0}

    def prepare_and_cross_expiry(arguments):  # noqa: ANN001, ANN202
        calls["count"] += 1
        binding = original_prepare(arguments)
        if calls["count"] >= 3:
            clock["now"] = "2026-08-15T00:00:01Z"
        return binding

    runtime = KernelToolRuntime(
        (replace(registration, prepare_binding=prepare_and_cross_expiry),),
        clock=lambda: clock["now"],
    )
    candidate_request = runtime.prepare(
        ToolCall("call-seed-expiry-during-binding", "local_process", arguments),
        _goal_context(runtime),
    )
    assert isinstance(candidate_request, ApprovalRequired)
    candidate = candidate_request.request.process_authority_candidate
    lease = ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity="req-expiry-during-binding",
        issued_at="2026-08-15T00:00:00Z",
        expires_at="2026-08-15T00:00:01Z",
    )
    intent = runtime.prepare(
        ToolCall("call-expiry-during-binding", "local_process", arguments),
        _goal_context(runtime, process_leases=(lease,)),
    )
    assert isinstance(intent, ExecutionIntent)

    with pytest.raises(IntentConflictError, match="expired before invocation"):
        runtime.invoke(intent)
    assert not marker.exists()


def test_015_child_path_cannot_use_relative_interpreter(tmp_path) -> None:
    """workspace script 的 ``/usr/bin/env`` 不得通过相对 PATH 劫持解释器。"""

    _require()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    relative_bin = workspace / "relative-bin"
    relative_bin.mkdir()
    malicious = relative_bin / "python3"
    malicious.write_text("#!/bin/sh\ntouch malicious-interpreter-ran\n", encoding="utf-8")
    os.chmod(malicious, stat.S_IRWXU)
    script = workspace / "env-script"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "Path('safe-interpreter-ran').touch()\n",
        encoding="utf-8",
    )
    os.chmod(script, stat.S_IRWXU)
    captured_path = os.pathsep.join(
        ("relative-bin", str(Path(sys.executable).parent), "/usr/bin", "/bin")
    )
    runtime = KernelToolRuntime(
        (build_local_process_registration(workspace=workspace, captured_path=captured_path),)
    )
    arguments = {
        "executable": "env-script",
        "argv": [],
        "cwd": ".",
        "profile": "short",
    }
    lease = _lease_for_invoke(runtime, arguments, workspace)
    intent = runtime.prepare(
        ToolCall("call-shebang", "local_process", arguments),
        _goal_context(runtime, process_leases=(lease,)),
    )
    assert isinstance(intent, ExecutionIntent)

    result = runtime.invoke(intent)

    assert result.is_error is False
    assert (workspace / "safe-interpreter-ran").exists()
    assert not (workspace / "malicious-interpreter-ran").exists()

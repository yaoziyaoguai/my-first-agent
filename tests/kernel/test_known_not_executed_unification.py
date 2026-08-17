"""F4（P2 review finding 2026-08-16）：``KnownNotExecuted`` 类型分裂统一。

``agent.process.contracts.KnownNotExecuted`` 与 ``agent.runtime.contracts`` 的同名
类型是两个不同的类：process executor 的 drift/denial 返回值在
``KernelToolRuntime.invoke`` 的 ``isinstance`` 分支不命中 → ``_normalize_output``
TypeError → EXTERNAL re-raise → 假 unknown-outcome recovery（用户被迫 resolve 一个
从未发生的效果）。Green：统一 closed 类型——process 包 re-export runtime 的
``KnownNotExecuted``，executor→invoke 完整路径必须得到 ``ToolResult(executed=False)``。
"""

from __future__ import annotations

import agent.process.contracts as process_contracts
import agent.runtime.contracts as runtime_contracts
from agent.process.contracts import KnownNotExecuted
from agent.runtime.contracts import (
    ProcessAuthorityLeaseV1,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.tools import KernelToolRuntime, RegisteredTool


def _seed_candidate(runtime: KernelToolRuntime):
    from agent.runtime.contracts import ApprovalRequired

    first = runtime.prepare(
        ToolCall(
            "call-seed-f4",
            "local_process",
            {"executable": "fixture-exe", "argv": [], "cwd": "."},
        ),
        ToolPrepareContext(
            conversation_id="conversation-f4",
            run_id="run-f4",
            state_revision=1,
            goal_id="goal-f4",
            goal_revision=1,
            workspace_identity_digest="workspace-f4",
        ),
    )
    assert isinstance(first, ApprovalRequired)
    return first.request.process_authority_candidate


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
        approved_request_identity="req-f4",
        issued_at=candidate.issued_at,
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=0,
    )


def test_015_known_not_executed_is_one_closed_type() -> None:
    """两个模块路径必须解析到同一个类（分裂即 Red）。"""

    assert (
        process_contracts.KnownNotExecuted is runtime_contracts.KnownNotExecuted
    ), "KnownNotExecuted must be a single closed type across process/runtime"


def test_015_executor_denial_reaches_invoke_as_executed_false(tmp_path) -> None:
    """完整 executor→invoke 路径：process executor 的 KnownNotExecuted 拒绝必须成为
    ``ToolResult(executed=False)``（模型可修正），不得 TypeError→unknown。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exe = workspace / "fixture-exe"
    exe.write_bytes(b"#!/bin/sh\ntrue\n")
    exe.chmod(0o700)

    def denying_executor(_intent):  # noqa: ANN001
        # 与真实 executor 的 drift/denial 返回完全同型（process contracts 实例）。
        return KnownNotExecuted(
            code="executable_identity_changed",
            message="executable identity drifted after approval",
        )

    from agent.process.tools import build_local_process_registration

    registration = build_local_process_registration(
        workspace=workspace, captured_path="/usr/bin:/bin"
    )
    runtime = KernelToolRuntime(
        (
            RegisteredTool(
                spec=registration.spec,
                func=denying_executor,
                prepare_binding=registration.prepare_binding,
            ),
        )
    )
    from agent.runtime.contracts import ToolResult  # noqa: PLC0415 - 就近断言类型

    intent = runtime.prepare(
        ToolCall(
            "call-f4",
            "local_process",
            {"executable": "fixture-exe", "argv": [], "cwd": "."},
        ),
        ToolPrepareContext(
            conversation_id="conversation-f4",
            run_id="run-f4",
            state_revision=1,
            goal_id="goal-f4",
            goal_revision=1,
            workspace_identity_digest="workspace-f4",
            process_leases=(_lease_from_candidate(_seed_candidate(runtime)),),
        ),
    )
    assert hasattr(intent, "tool_call_id"), (
        f"expected an ExecutionIntent, got {intent!r}"
    )
    result = runtime.invoke(intent)
    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.is_error is True
    assert result.metadata.get("code") == "executable_identity_changed"

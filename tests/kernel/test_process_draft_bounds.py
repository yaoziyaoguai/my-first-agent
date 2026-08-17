"""P3（冻结合同）：Kernel 必须验证 ``ProcessExecutionDraftV1`` 的 bounds/outcome/
group-reaped/digests，不能盲信 process callable（KTD8）。

draft 是 runner 的 closed 输出，但 invoke 是唯一铸造 receipt 的层：越界 draft
（超 profile caps、EXITED 无 exit_code、TIMED_OUT_REAPED 未确认 group_reaped、
非 64-hex digest）不得被铸成 durable receipt——必须在 effect 语义下 fail closed
（EXTERNAL → unknown recovery）。
"""

from __future__ import annotations

import pytest

from agent.process.contracts import ProcessDraftOutcome, ProcessExecutionDraftV1
from agent.process.tools import build_local_process_registration
from agent.runtime.contracts import (
    ApprovalRequired,
    ProcessAuthorityLeaseV1,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.tools import KernelToolRuntime, RegisteredTool


def _draft(**overrides) -> ProcessExecutionDraftV1:
    values = {
        "outcome": ProcessDraftOutcome.EXITED,
        "pid": 1,
        "process_group_id": 1,
        "exit_code": 0,
        "signal": None,
        "started_at_monotonic": 0.0,
        "ended_at_monotonic": 1.0,
        "duration_seconds": 1.0,
        "stdout_bytes": 4,
        "stderr_bytes": 4,
        "stdout_digest": "d" * 64,
        "stderr_digest": "d" * 64,
        "stdout_projection": "done",
        "stderr_projection": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "group_reaped": True,
        "term_sent": False,
        "kill_sent": False,
    }
    values.update(overrides)
    return ProcessExecutionDraftV1(**values)


def _runtime(tmp_path, draft_factory) -> KernelToolRuntime:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    exe = workspace / "fixture-exe"
    exe.write_bytes(b"#!/bin/sh\ntrue\n")
    exe.chmod(0o700)
    registration = build_local_process_registration(
        workspace=workspace, captured_path="/usr/bin:/bin"
    )

    def executor(_intent):  # noqa: ANN001
        return draft_factory()

    return KernelToolRuntime(
        (
            RegisteredTool(
                spec=registration.spec,
                func=executor,
                prepare_binding=registration.prepare_binding,
            ),
        )
    )


def _intent_with_lease(runtime: KernelToolRuntime):
    from agent.runtime.contracts import ExecutionIntent

    first = runtime.prepare(
        ToolCall(
            "call-seed",
            "local_process",
            {"executable": "fixture-exe", "argv": [], "cwd": "."},
        ),
        ToolPrepareContext(
            conversation_id="conversation-p3",
            run_id="run-p3",
            state_revision=1,
            goal_id="goal-p3",
            goal_revision=1,
            workspace_identity_digest="workspace-p3",
        ),
    )
    assert isinstance(first, ApprovalRequired)
    candidate = first.request.process_authority_candidate
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
        approved_request_identity="req-p3",
        issued_at=candidate.issued_at,
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=0,
    )
    intent = runtime.prepare(
        ToolCall(
            "call-p3",
            "local_process",
            {"executable": "fixture-exe", "argv": [], "cwd": "."},
        ),
        ToolPrepareContext(
            conversation_id="conversation-p3",
            run_id="run-p3",
            state_revision=1,
            goal_id="goal-p3",
            goal_revision=1,
            workspace_identity_digest="workspace-p3",
            process_leases=(lease,),
        ),
    )
    assert isinstance(intent, ExecutionIntent)
    return intent


INVALID_DRAFTS = {
    "exited_without_exit_code": _draft(exit_code=None),
    "signaled_without_signal": _draft(
        outcome=ProcessDraftOutcome.SIGNALED, exit_code=None, signal=None
    ),
    "timed_out_without_confirmed_reap": _draft(
        outcome=ProcessDraftOutcome.TIMED_OUT_REAPED,
        exit_code=None,
        group_reaped=False,
    ),
    "stdout_bytes_over_profile_cap": _draft(stdout_bytes=999_999_999),
    "stderr_bytes_over_profile_cap": _draft(stderr_bytes=999_999_999),
    "stdout_digest_not_64_hex": _draft(stdout_digest="not-hex"),
    "negative_duration": _draft(duration_seconds=-1.0),
    "duration_beyond_profile_budget": _draft(duration_seconds=10_000.0),
    "projection_over_rendered_chars": _draft(stdout_projection="x" * 100_000),
}


@pytest.mark.parametrize("label", sorted(INVALID_DRAFTS))
def test_015_out_of_bounds_draft_is_not_minted_into_receipt(tmp_path, label) -> None:
    runtime = _runtime(tmp_path, lambda: INVALID_DRAFTS[label])
    intent = _intent_with_lease(runtime)
    with pytest.raises(Exception, match="process draft"):
        runtime.invoke(intent)


def test_015_valid_draft_still_mints_receipt(tmp_path) -> None:
    runtime = _runtime(tmp_path, lambda: _draft())
    intent = _intent_with_lease(runtime)
    result = runtime.invoke(intent)
    assert result.is_error is False
    assert result.metadata.get("process_receipt_kind") == "process_v1"

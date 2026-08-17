"""015 ProcessCleanupError → AWAITING_RECOVERY integration test.

ProcessCleanupError from runner (group cleanup cannot confirm) propagates through
executor → invoke → loop except handler → RecoveryRequest → AWAITING_RECOVERY.
No process receipt minted, no automatic rerun.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from agent.composition import build_composition, build_tool_registrations
from agent.continuity.sessions import open_workspace_session
from agent.process.runner import ProcessCleanupError
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    GoalFrame,
    GoalProposal,
    GoalStatus,
    ModelResponse,
    ModelToolCall,
    ProposedCriterion,
    ResolveApproval,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import InvocationLimits
from agent.runtime.tools import RegisteredTool
from tests.kernel.fakes import CollectingSink


class _CleanupFailProvider:
    """Provider that requests local_process; executor monkeypatched to raise ProcessCleanupError."""

    def __init__(self, executable: str) -> None:
        self.executable = executable
        self.calls: list = []

    def generate(self, context) -> ModelResponse:  # noqa: ANN001
        self.calls.append(context)
        index = len(self.calls)
        if index == 1:
            bootstrap = context.goal_bootstrap
            assert bootstrap is not None
            return ModelResponse((), control=GoalProposal(
                correlation_id="cleanup-fail",
                goal_frame=GoalFrame(
                    goal_id="goal-cleanup-fail",
                    revision=1,
                    created_from_fact_ids=(bootstrap.source_fact_id,),
                    workspace_identity_digest=bootstrap.workspace_identity_digest,
                    user_outcome="Exercise cleanup failure recovery",
                    beneficiary="user",
                    targets=("output.txt",),
                    scope=("workspace",),
                    non_goals=(),
                    assumptions=(),
                    proposed_criteria=(
                        ProposedCriterion("c1", "test"),
                    ),
                    admitted_criteria=(),
                    authority_snapshot=bootstrap.authority_snapshot,
                    status=GoalStatus.GOAL_READY,
                    created_at="2026-08-09T00:00:00Z",
                    updated_at="2026-08-09T00:00:00Z",
                ),
            ))
        if index == 2:
            return ModelResponse((
                ModelToolCall("call-cleanup", "local_process", {
                    "executable": self.executable,
                    "argv": [],
                    "cwd": ".",
                    "profile": "short",
                }),
            ))
        return ModelResponse(())


def test_015_process_cleanup_error_enters_awaiting_recovery(tmp_path: Path) -> None:
    """ProcessCleanupError → loop catches → RecoveryRequest → AWAITING_RECOVERY.

    No process receipt, no automatic rerun, user must resolve.
    """


    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = (tmp_path / "state").resolve()
    state_root.mkdir(parents=True, mode=0o700)
    os.chmod(state_root, 0o700)

    # Simple executable
    exe = workspace / "simple-exe"
    exe.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    os.chmod(exe, stat.S_IRWXU)

    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-0000000000c1",
    )
    registrations = list(
        build_tool_registrations(
            workspace=workspace,
            protected_paths=(opened.checkpoint_path,),
            max_tool_result_chars=50_000,
        )
    )

    # Find local_process registration and wrap its func to raise ProcessCleanupError
    for i, reg in enumerate(registrations):
        if reg.spec.name == "local_process":
            original_func = reg.func
            def crash_func(intent, _orig=original_func):  # noqa: ANN001
                _orig(intent)  # process spawns + runs
                raise ProcessCleanupError("test: cannot confirm group cleanup")
            registrations[i] = RegisteredTool(
                spec=reg.spec, func=crash_func, prepare_binding=reg.prepare_binding
            )
            break

    provider = _CleanupFailProvider("simple-exe")
    composition = build_composition(
        provider=provider,
        checkpoint_store=opened.store,
        tool_registrations=tuple(registrations),
        event_sink=CollectingSink(),
        system_policy="test",
        context_limits=ContextLimits(max_input_tokens=100_000, output_reserve=5_000),
        invocation_limits=InvocationLimits(),
        workspace_identity_digest=opened.workspace_binding.workspace_identity_digest,
        context_scope_digest=opened.workspace_binding.workspace_scope_digest,
        workspace_binding=opened.workspace_binding,
    )

    store = opened.store
    state = store.load().state
    result = composition.runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-cleanup",
            message="Run local_process that will fail cleanup.",
        ),
        store.load(),
    )

    # Drive through disclosure + approval
    while result.status not in (
        RunStatus.COMPLETED,
        RunStatus.AWAITING_RECOVERY,
        RunStatus.FAILED_FATAL,
    ):
        st = store.load().state
        if result.status is RunStatus.AWAITING_DISCLOSURE:
            action = AcknowledgeProviderDisclosure(
                conversation_id=st.conversation_id,
                action_seq=st.next_action_seq,
                expected_revision=st.revision,
                request_digest=st.provider_disclosure_request.request_digest,
                acknowledged_at="2026-08-09T00:00:00Z",
            )
        elif result.status is RunStatus.AWAITING_APPROVAL:
            candidate = result.request.process_authority_candidate
            assert candidate is not None
            action = ResolveApproval(
                conversation_id=st.conversation_id,
                action_seq=st.next_action_seq,
                expected_revision=st.revision,
                request_id=result.request.request_id,
                binding_digest=result.request.binding_digest,
                approved=True,
                approved_at=candidate.issued_at,
            )
        else:
            break
        result = composition.runtime.run_turn(action, store.load())

    # Must enter AWAITING_RECOVERY (ProcessCleanupError → unknown outcome → recovery).
    assert result.status is RunStatus.AWAITING_RECOVERY, (
        f"expected AWAITING_RECOVERY, got {result.status}"
    )
    # No process receipt in state (ProcessCleanupError prevented receipt minting).
    final = store.load().state
    from agent.runtime.contracts import FactKind
    process_receipts = [
        f for f in final.facts
        if f.kind is FactKind.TOOL_RESULT
        and isinstance(f.content.get("metadata"), dict)
        and f.content["metadata"].get("process_receipt_kind") == "process_v1"
    ]
    assert len(process_receipts) == 0, "ProcessCleanupError must prevent receipt minting"

"""015 J1 production-path VERIFIED_DONE test.

Through AgentRuntime.run_turn: provider reads input, proposes Goal, requests
local_process 执行后由用户批准 action 绑定 expected artifact，process runs, provider
reads artifact, sends CompletionClaim -> VERIFIED_DONE with two mandatory
criteria (TOOL_RECEIPT + FILESYSTEM_DIGEST) verified by closed evidence.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from agent.cli.app import _parse_action
from agent.composition import build_composition, build_tool_registrations
from agent.continuity.sessions import open_workspace_session
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    CompletionClaim,
    ContextPack,
    EvidenceOracleKind,
    GoalFrame,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    ProposedCriterion,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import InvocationLimits
from tests.kernel.fakes import CollectingSink, goal_draft_from_frame


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class _J1ProductionProvider:
    """Drives J1: read input -> Goal -> local_process -> read artifact -> done."""

    def __init__(self, input_path: str, artifact_path: str, artifact_sha: str,
                 executable: str) -> None:
        self.input_path = input_path
        self.artifact_path = artifact_path
        self.artifact_sha = artifact_sha
        self.executable = executable
        self.calls: list[ContextPack] = []

    def generate(self, context: ContextPack) -> ModelResponse:
        self.calls.append(context)
        index = len(self.calls)
        if index == 1:
            # GoalProposal first (no source reads before goal)
            bootstrap = context.goal_bootstrap
            assert bootstrap is not None
            return ModelResponse((), control=goal_draft_from_frame(
                correlation_id="proposal-j1",
                goal=GoalFrame(
                    goal_id="goal-j1-prod",
                    revision=1,
                    created_from_fact_ids=(bootstrap.source_fact_id,),
                    workspace_identity_digest=bootstrap.workspace_identity_digest,
                    user_outcome="Produce artifact via local_process and verify",
                    beneficiary="user",
                    targets=(self.artifact_path,),
                    scope=("workspace",),
                    non_goals=(),
                    assumptions=(),
                    proposed_criteria=(
                        ProposedCriterion(
                            "criterion:process-artifact:goal-j1-prod:1:"
                            + self.artifact_path,
                            "artifact reads back with exact sha256",
                            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                            artifact_path=self.artifact_path,
                        ),
                        ProposedCriterion(
                            "criterion:model-process-receipt",
                            "the requested process exits successfully",
                            oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                        ),
                    ),
                    admitted_criteria=(),
                    authority_snapshot=bootstrap.authority_snapshot,
                    status=GoalStatus.GOAL_READY,
                    created_at="2026-08-09T00:00:00Z",
                    updated_at="2026-08-09T00:00:00Z",
                ),
            ))
        if index == 2:
            # F4：model 只发 closed 4 字段（artifact digest 由用户在 approval 确认）。
            return ModelResponse((
                ModelToolCall("call-process", "local_process", {
                    "executable": self.executable,
                    "argv": [self.input_path, self.artifact_path],
                    "cwd": ".",
                    "profile": "short",
                }),
            ))
        if index == 3:
            return ModelResponse((
                ModelToolCall("read-artifact", "read_file", {"path": self.artifact_path}),
            ))
        if index == 4:
            goal_block = next(
                block for msg in reversed(context.messages)
                for block in msg.content if block.get("type") == "trusted_goal"
            )
            return ModelResponse((), control=CompletionClaim(
                correlation_id="completion-j1",
                goal_id=goal_block["goal_id"],
                goal_revision=goal_block["goal_revision"],
                criterion_evidence_refs=tuple(
                    goal_block["expected_completion_evidence_refs"]
                ),
            ))
        return ModelResponse((ModelTextBlock("done"),))


def test_015_j1_production_verified_done(tmp_path: Path) -> None:
    """J1 through production composition: dual mandatory criteria -> VERIFIED_DONE."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = (tmp_path / "state").resolve()
    state_root.mkdir(parents=True, mode=0o700)
    os.chmod(state_root, 0o700)

    # Fixtures: input.txt + write-artifact executable
    input_content = "deterministic-j1-input\n"
    (workspace / "input.txt").write_text(input_content, encoding="utf-8")
    artifact_rel = "artifact.out"
    artifact_sha = _sha256_hex(input_content)

    write_artifact = workspace / "write-artifact"
    write_artifact.write_text("#!/bin/sh\ncat \"$1\" > \"$2\"\n", encoding="utf-8")
    os.chmod(write_artifact, stat.S_IRWXU)

    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000001",
    )
    registrations = build_tool_registrations(
        workspace=workspace,
        protected_paths=(opened.checkpoint_path,),
        max_tool_result_chars=50_000,
    )

    provider = _J1ProductionProvider(
        input_path="input.txt",
        artifact_path=artifact_rel,
        artifact_sha=artifact_sha,
        executable="write-artifact",
    )
    composition = build_composition(
        provider=provider,
        checkpoint_store=opened.store,
        tool_registrations=tuple(registrations),
        event_sink=CollectingSink(),
        system_policy="Complete the artifact task with exact evidence.",
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
            run_id="run-j1-prod",
            message="Convert input.txt into artifact.out via local_process and verify.",
        ),
        store.load(),
    )

    # Drive through approval + disclosure
    while result.status is not RunStatus.COMPLETED:
        state = store.load().state
        if result.status is RunStatus.AWAITING_DISCLOSURE:
            action = AcknowledgeProviderDisclosure(
                conversation_id=state.conversation_id,
                action_seq=state.next_action_seq,
                expected_revision=state.revision,
                request_digest=state.provider_disclosure_request.request_digest,
                acknowledged_at="2026-08-09T00:00:00Z",
            )
        elif result.status is RunStatus.AWAITING_APPROVAL:
            assert result.request.process_authority_candidate is not None
            candidate = result.request.process_authority_candidate
            # F4：candidate 不再携带 model 自供的 expected_artifact（恒 None）——
            # artifact digest 由**用户**在 ResolveApproval.confirmed_artifact_* 确认。
            assert candidate.expected_artifact_path is None
            assert candidate.expected_artifact_sha256 is None
            # same-UID notice in preview
            assert "same-uid" in result.request.preview.casefold()
            assert artifact_rel in result.request.preview
            requirement = result.request.artifact_confirmation_requirement
            assert requirement is not None
            action, error = _parse_action(
                f"/approve-artifact {artifact_sha} {artifact_rel}",
                state,
                lambda: "run-unused",
                approval_time_factory=lambda issued_at=candidate.issued_at: issued_at,
            )
            assert error is None and action is not None
        else:
            break
        result = composition.runtime.run_turn(action, store.load())

    final = store.load().state
    # VERIFIED_DONE with two mandatory criteria
    assert final.goal is not None
    assert final.goal.status is GoalStatus.VERIFIED_DONE
    mandatory = [c for c in final.goal.admitted_criteria if c.mandatory]
    assert len(mandatory) >= 2
    oracle_kinds = {c.oracle_kind for c in mandatory}
    assert EvidenceOracleKind.FILESYSTEM_DIGEST in oracle_kinds
    assert EvidenceOracleKind.TOOL_RECEIPT in oracle_kinds
    # Artifact content matches approved sha256
    assert (workspace / artifact_rel).read_text(encoding="utf-8") == input_content
    # All evidence records passed
    assert all(record.passed for record in final.evidence_records)
    assert len(final.evidence_records) >= 2

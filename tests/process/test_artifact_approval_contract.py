"""015 fresh-review P1：artifact requirement 必须贯穿 Goal → approval → completion。"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

import agent.runtime.contracts as contracts
from agent.cli.actions import build_resolve_approval
from agent.process.tools import build_local_process_registration
from agent.runtime.checkpoint import CheckpointInvariantError, _decode_state, _encode_state
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    CompletionClaim,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    EvidenceRecord,
    FactKind,
    GoalFrame,
    GoalStatus,
    ProposedCriterion,
    ResolveApproval,
    ToolCall,
    ToolPrepareContext,
    canonical_json_digest,
)
from agent.runtime.loop import AgentRuntime
from agent.runtime.state import _apply_action, apply_goal_delta, verify_goal_completion
from agent.runtime.tools import KernelToolRuntime


def _artifact_proposal() -> ProposedCriterion:
    return ProposedCriterion(
        "criterion-artifact",
        "artifact has the exact user-confirmed digest",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        artifact_path="artifact.out",
    )


def _goal(criterion: ProposedCriterion) -> GoalFrame:
    return GoalFrame(
        goal_id="goal-artifact",
        revision=1,
        created_from_fact_ids=("fact-user",),
        workspace_identity_digest="workspace-artifact",
        user_outcome="produce and verify artifact.out",
        beneficiary="user",
        targets=("artifact.out",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(criterion,),
        admitted_criteria=(),
        authority_snapshot="fixed-composition",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-16T00:00:00Z",
        updated_at="2026-08-16T00:00:00Z",
    )


def test_015_goal_delta_preserves_typed_artifact_requirement() -> None:
    updated = apply_goal_delta(
        replace(ConversationState.new("conversation-artifact"), goal=_goal(_artifact_proposal())),
        contracts.GoalDelta(
            goal_id="goal-artifact",
            expected_revision=1,
            reason="user changed the artifact path",
            updates={
                "proposed_criteria": [
                    {
                        "criterion_id": "criterion-new-artifact",
                        "description": "new artifact has the confirmed digest",
                        "oracle_kind": "filesystem_digest",
                        "artifact_path": "deliverables/new.out",
                    }
                ]
            },
        ),
    )

    assert updated.goal is not None
    assert updated.goal.proposed_criteria == (
        ProposedCriterion(
            "criterion-new-artifact",
            "new artifact has the confirmed digest",
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            artifact_path="deliverables/new.out",
        ),
    )


def test_015_typed_artifact_goal_delta_is_recognized_as_noop() -> None:
    state = replace(
        ConversationState.new("conversation-artifact"),
        goal=_goal(_artifact_proposal()),
    )
    proposal = contracts.GoalDeltaProposal(
        correlation_id="delta-noop-artifact",
        delta=contracts.GoalDelta(
            goal_id="goal-artifact",
            expected_revision=1,
            reason="no material change",
            updates={
                "proposed_criteria": [
                    {
                        "criterion_id": "criterion-artifact",
                        "description": "artifact has the exact user-confirmed digest",
                        "oracle_kind": "filesystem_digest",
                        "artifact_path": "artifact.out",
                    }
                ]
            },
        ),
    )

    assert AgentRuntime._goal_delta_is_noop(state, proposal) is True


def _awaiting_state(request, criterion: ProposedCriterion) -> ConversationState:  # noqa: ANN001
    active = ActiveRun(
        run_id="run-artifact",
        status=ActiveRunStatus.AWAITING_APPROVAL,
        phase=ContinuationPhase.TOOL,
        batch_cursor=0,
        tool_calls=(ToolCall("call-artifact", "local_process", {}),),
        pending_request=request,
    )
    return replace(
        ConversationState.new("conversation-artifact"),
        goal=_goal(criterion),
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "produce and verify artifact.out"},
            ),
        ),
        active_run=active,
    )


def _prepare_artifact_request(tmp_path: Path):  # noqa: ANN201
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = workspace / "writer"
    executable.write_text("#!/bin/sh\nprintf wrong > \"$1\"\n", encoding="utf-8")
    os.chmod(executable, stat.S_IRWXU)
    criterion = _artifact_proposal()
    runtime = KernelToolRuntime(
        (build_local_process_registration(workspace=workspace, captured_path="/usr/bin:/bin"),)
    )
    prepared = runtime.prepare(
        ToolCall(
            "call-artifact",
            "local_process",
            {
                "executable": "writer",
                "argv": ["artifact.out"],
                "cwd": ".",
                "profile": "short",
            },
        ),
        ToolPrepareContext(
            conversation_id="conversation-artifact",
            run_id="run-artifact",
            state_revision=0,
            goal_id="goal-artifact",
            goal_revision=1,
            workspace_identity_digest="workspace-artifact",
            proposed_criteria=(criterion,),
        ),
    )
    assert isinstance(prepared, contracts.ApprovalRequired)
    return criterion, prepared.request


def test_015_artifact_requirement_rejects_plain_approval_in_reducer(
    tmp_path: Path,
) -> None:
    """普通 yes/a 即使绕过 adapter 也不能批准尚未确认 digest 的 artifact Goal。"""

    criterion, request = _prepare_artifact_request(tmp_path)
    requirement = request.artifact_confirmation_requirement
    assert requirement is not None
    assert requirement.criterion_id == criterion.criterion_id
    assert requirement.artifact_path == "artifact.out"
    state = _awaiting_state(request, criterion)
    plain = ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request.request_id,
        binding_digest=request.binding_digest,
        approved=True,
        approved_at="2026-08-16T00:01:00Z",
    )
    with pytest.raises(ValueError, match="artifact confirmation"):
        _apply_action(state, plain)

    confirmed = replace(
        plain,
        confirmed_artifact_path="artifact.out",
        confirmed_artifact_sha256="a" * 64,
    )
    accepted = _apply_action(state, confirmed)
    assert any(
        item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
        and item.predicate == {"path": "artifact.out", "sha256": "a" * 64}
        for item in accepted.goal.admitted_criteria
    )
    process_requirement = next(
        item
        for item in accepted.goal.admitted_criteria
        if item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        and item.predicate.get("receipt_kind") == "process_v1"
    )
    assert process_requirement.predicate == {
        "receipt_kind": "process_v1",
        "command_fingerprint": request.process_authority_candidate.command_fingerprint,
        "outcome": "exited",
        "exit_code": 0,
    }

    artifact_requirement = next(
        item
        for item in accepted.goal.admitted_criteria
        if item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
    )
    artifact_record = EvidenceRecord(
        evidence_id="evidence-artifact-only",
        goal_id=accepted.goal.goal_id,
        goal_revision=accepted.goal.revision,
        criterion_id=artifact_requirement.criterion_id,
        oracle_kind=artifact_requirement.oracle_kind,
        predicate_digest=canonical_json_digest(artifact_requirement.predicate),
        source_fact_ids=("fact-user",),
        source_digest="s" * 64,
        oracle_identity="filesystem-digest:v1",
        passed=True,
        observed_at="2026-08-16T00:02:00Z",
    )
    artifact_only = replace(
        accepted,
        evidence_records=(artifact_record,),
        completion_claim=CompletionClaim(
            correlation_id="claim-artifact-only",
            goal_id=accepted.goal.goal_id,
            goal_revision=accepted.goal.revision,
            criterion_evidence_refs=(artifact_record.evidence_id,),
        ),
    )
    with pytest.raises(ValueError, match="every mandatory criterion"):
        verify_goal_completion(artifact_only)


def test_015_checkpoint_rejects_retargeted_pending_process_candidate(tmp_path: Path) -> None:
    criterion, request = _prepare_artifact_request(tmp_path)
    document = json.loads(_encode_state(_awaiting_state(request, criterion)))
    candidate = document["state"]["active_run"]["pending_request"][
        "process_authority_candidate"
    ]
    candidate["readable_command"] = "different executable --retargeted"

    with pytest.raises(CheckpointInvariantError, match="candidate digest mismatch"):
        _decode_state(json.dumps(document).encode("utf-8"))


def test_015_v5_retargeted_pending_candidate_is_revoked_not_resigned(
    tmp_path: Path,
) -> None:
    criterion, request = _prepare_artifact_request(tmp_path)
    document = json.loads(_encode_state(_awaiting_state(request, criterion)))
    document["schema_version"] = 5
    candidate = document["state"]["active_run"]["pending_request"][
        "process_authority_candidate"
    ]
    candidate["command_fingerprint"] = "9" * 64

    restored = _decode_state(json.dumps(document).encode("utf-8"))

    assert restored.active_run is not None
    pending = restored.active_run.pending_request
    assert isinstance(pending, contracts.ApprovalRequest)
    assert pending.process_authority_candidate is None


def test_015_artifact_goal_cannot_complete_with_process_receipt_only() -> None:
    """Defense in depth：legacy/bypassed approval 也不能让 artifact obligation 消失。"""

    criterion = _artifact_proposal()
    receipt_criterion = AdmittedCriterion(
        criterion_id="criterion-receipt",
        description="exact process command exited zero",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={"receipt_digest": "r" * 64},
        required_evidence_class="process_receipt",
        admission_digest="a" * 64,
        mandatory=True,
    )
    goal = replace(_goal(criterion), admitted_criteria=(receipt_criterion,))
    record = EvidenceRecord(
        evidence_id="evidence-receipt",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        criterion_id=receipt_criterion.criterion_id,
        oracle_kind=receipt_criterion.oracle_kind,
        predicate_digest=canonical_json_digest(receipt_criterion.predicate),
        source_fact_ids=("fact-user",),
        source_digest="s" * 64,
        oracle_identity="tool-receipt:v1",
        passed=True,
        observed_at="2026-08-16T00:02:00Z",
    )
    state = replace(
        ConversationState.new("conversation-artifact"),
        goal=goal,
        evidence_records=(record,),
        completion_claim=CompletionClaim(
            correlation_id="claim-artifact",
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            criterion_evidence_refs=(record.evidence_id,),
        ),
    )
    with pytest.raises(ValueError, match="artifact criterion"):
        verify_goal_completion(state)

    legacy_goal = replace(
        goal,
        proposed_criteria=(
            ProposedCriterion(
                criterion.criterion_id,
                criterion.description,
            ),
        ),
    )
    with pytest.raises(ValueError, match="typed evidence oracle"):
        verify_goal_completion(replace(state, goal=legacy_goal))


def test_015_legacy_tool_receipt_goal_remains_compatible() -> None:
    """012-014 generic TOOL_RECEIPT 不能被误判为 015 process obligation。"""

    proposed = ProposedCriterion(
        "criterion-legacy-receipt",
        "the governed tool returned its legacy receipt",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    legacy_criterion = AdmittedCriterion(
        criterion_id="criterion-legacy-receipt",
        description="the governed tool returned its legacy receipt",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={"receipt_digest": "r" * 64},
        required_evidence_class="tool_receipt",
        admission_digest="a" * 64,
        mandatory=True,
    )
    goal = replace(_goal(proposed), admitted_criteria=(legacy_criterion,))
    record = EvidenceRecord(
        evidence_id="evidence-legacy-receipt",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        criterion_id=legacy_criterion.criterion_id,
        oracle_kind=legacy_criterion.oracle_kind,
        predicate_digest=canonical_json_digest(legacy_criterion.predicate),
        source_fact_ids=("fact-user",),
        source_digest="s" * 64,
        oracle_identity="tool-receipt:v1",
        passed=True,
        observed_at="2026-08-16T00:03:00Z",
    )
    state = replace(
        ConversationState.new("conversation-legacy-receipt"),
        goal=goal,
        evidence_records=(record,),
        completion_claim=CompletionClaim(
            correlation_id="claim-legacy-receipt",
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            criterion_evidence_refs=(record.evidence_id,),
        ),
    )

    assert verify_goal_completion(state).goal.status is GoalStatus.VERIFIED_DONE


def test_015_typed_non_file_goal_delta_is_recognized_as_noop() -> None:
    proposed = ProposedCriterion(
        "criterion-tool",
        "the governed tool produced its receipt",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    state = replace(
        ConversationState.new("conversation-tool-noop"),
        goal=_goal(proposed),
    )
    proposal = contracts.GoalDeltaProposal(
        correlation_id="delta-noop-tool",
        delta=contracts.GoalDelta(
            goal_id="goal-artifact",
            expected_revision=1,
            reason="no material change",
            updates={
                "proposed_criteria": [
                    {
                        "criterion_id": proposed.criterion_id,
                        "description": proposed.description,
                        "oracle_kind": "tool_receipt",
                        "artifact_path": "",
                    }
                ]
            },
        ),
    )

    assert AgentRuntime._goal_delta_is_noop(state, proposal) is True


def test_015_cli_tui_headless_share_explicit_artifact_approval(
    tmp_path: Path,
) -> None:
    """CLI/TUI/headless 使用同一个 typed builder；pending requirement 时 plain yes 拒绝。"""

    criterion, request = _prepare_artifact_request(tmp_path)
    state = _awaiting_state(request, criterion)
    from agent.cli.app import _parse_action
    from agent.tui.app import parse_process_command
    from agent.tui.render import project

    projection = project(state)
    assert projection.actions == ("reject",)
    assert projection.focus == "input"
    assert (
        "approval command",
        "/approve-artifact <64-lowercase-hex-sha256> artifact.out",
    ) in projection.form_fields

    plain, error = _parse_action(
        "yes",
        state,
        lambda: "run-unused",
        approval_time_factory=lambda: "2026-08-16T00:03:00Z",
    )
    assert plain is None
    assert error is not None and "/approve-artifact" in error

    command = f"/approve-artifact {'b' * 64} artifact.out"
    cli_action, error = _parse_action(
        command,
        state,
        lambda: "run-unused",
        approval_time_factory=lambda: "2026-08-16T00:03:00Z",
    )
    assert error is None
    assert cli_action == build_resolve_approval(
        state,
        request_id=request.request_id,
        binding_digest=request.binding_digest,
        approved=True,
        approved_at="2026-08-16T00:03:00Z",
        confirmed_artifact_path="artifact.out",
        confirmed_artifact_sha256="b" * 64,
    )

    kind, tui_action = parse_process_command(
        command,
        state,
        approval_time_factory=lambda: "2026-08-16T00:03:00Z",
    )
    assert kind == "action"
    assert tui_action == cli_action


def test_015_artifact_requirement_survives_checkpoint_restart(tmp_path: Path) -> None:
    """Goal obligation 与 pending approval 必须同一次 durable round-trip 后仍完整。"""

    from agent.runtime.checkpoint import (
        CheckpointVersionError,
        _decode_state,
        _encode_state,
    )

    criterion, request = _prepare_artifact_request(tmp_path)
    state = _awaiting_state(request, criterion)

    restarted = _decode_state(_encode_state(state))

    assert restarted.goal is not None
    assert restarted.goal.proposed_criteria == (criterion,)
    assert restarted.active_run is not None
    pending = restarted.active_run.pending_request
    assert pending is not None
    assert pending.artifact_confirmation_requirement == (
        request.artifact_confirmation_requirement
    )

    document = json.loads(_encode_state(state).decode("utf-8"))
    del document["state"]["active_run"]["pending_request"][
        "artifact_confirmation_requirement"
    ]
    with pytest.raises(CheckpointVersionError, match="artifact_confirmation_requirement"):
        _decode_state(json.dumps(document).encode("utf-8"))


def test_015_artifact_requirement_cannot_detach_from_process_or_goal(tmp_path: Path) -> None:
    """结构化 obligation 不能脱离 process candidate，也不能指向别的 Goal criterion。"""

    criterion, request = _prepare_artifact_request(tmp_path)
    with pytest.raises(ValueError, match="process candidate"):
        replace(request, process_authority_candidate=None)

    state = _awaiting_state(
        replace(
            request,
            artifact_confirmation_requirement=contracts.ArtifactConfirmationRequirementV1(
                criterion_id="criterion-other",
                artifact_path="artifact.out",
            ),
        ),
        criterion,
    )
    action = build_resolve_approval(
        state,
        request_id=request.request_id,
        binding_digest=request.binding_digest,
        approved=True,
        approved_at="2026-08-16T00:03:00Z",
        confirmed_artifact_path="artifact.out",
        confirmed_artifact_sha256="c" * 64,
    )
    with pytest.raises(ValueError, match="current Goal criterion"):
        _apply_action(state, action)

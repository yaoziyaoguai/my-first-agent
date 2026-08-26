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
from agent.runtime.state import (
    _apply_action,
    apply_goal_delta,
    authoritative_process_entrypoints,
    process_entrypoint_matches_authority,
    verify_goal_completion,
)
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


def test_016_one_exact_file_approval_admits_all_matching_artifact_criteria() -> None:
    first = ProposedCriterion(
        "criterion-readme-exists",
        "README.md exists with the approved content",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        artifact_path="README.md",
    )
    second = ProposedCriterion(
        "criterion-readme-usage",
        "README.md contains the requested usage section",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        artifact_path="README.md",
    )
    request = contracts.ApprovalRequest(
        request_id="approval-readme",
        run_id="run-readme",
        tool_call_id="write-readme",
        binding_digest="binding-readme",
        preview="write README.md",
        tool_name="write_file",
        new_content_digest="a" * 64,
    )
    active = ActiveRun(
        run_id="run-readme",
        status=ActiveRunStatus.AWAITING_APPROVAL,
        phase=ContinuationPhase.TOOL,
        tool_calls=(
            ToolCall(
                "write-readme",
                "write_file",
                {"path": "README.md", "content": "# Reading notes\n"},
            ),
        ),
        pending_request=request,
    )
    goal = replace(
        _goal(first),
        proposed_criteria=(first, second),
        admitted_criteria=(),
    )
    state = replace(
        ConversationState.new("conversation-readme"),
        goal=goal,
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "write README.md with a usage section"},
            ),
        ),
        active_run=active,
    )
    goal = replace(goal, created_from_fact_ids=("fact-user",))
    state = replace(state, goal=goal)
    action = ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request.request_id,
        binding_digest=request.binding_digest,
        approved=True,
    )

    accepted = _apply_action(state, action)

    admitted = {
        criterion.criterion_id: criterion
        for criterion in accepted.goal.admitted_criteria
    }
    assert set(admitted) == {first.criterion_id, second.criterion_id}
    assert all(
        criterion.predicate == {"path": "README.md", "sha256": "a" * 64}
        for criterion in admitted.values()
    )


def test_016_first_approved_write_binds_one_deferred_artifact_criterion() -> None:
    deferred = ProposedCriterion(
        "criterion-located-artifact",
        "the located implementation has the requested fix",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
    )
    request = contracts.ApprovalRequest(
        request_id="approval-located-artifact",
        run_id="run-located-artifact",
        tool_call_id="write-located-artifact",
        binding_digest="binding-located-artifact",
        preview="edit greet.py",
        tool_name="edit_file",
        new_content_digest="b" * 64,
    )
    active = ActiveRun(
        run_id="run-located-artifact",
        status=ActiveRunStatus.AWAITING_APPROVAL,
        phase=ContinuationPhase.TOOL,
        tool_calls=(
            ToolCall(
                "write-located-artifact",
                "edit_file",
                {"path": "greet.py", "old_text": "hello?", "new_text": "hello!"},
            ),
        ),
        pending_request=request,
    )
    goal = replace(
        _goal(deferred),
        created_from_fact_ids=("fact-user",),
        targets=("locate and fix the greet implementation",),
    )
    state = replace(
        ConversationState.new("conversation-located-artifact"),
        goal=goal,
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "locate and fix the greet punctuation"},
            ),
        ),
        active_run=active,
    )
    action = ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request.request_id,
        binding_digest=request.binding_digest,
        approved=True,
    )

    accepted = _apply_action(state, action)

    assert accepted.goal is not None
    assert accepted.goal.proposed_criteria == (
        replace(deferred, artifact_path="greet.py"),
    )
    assert len(accepted.goal.admitted_criteria) == 1
    admitted = accepted.goal.admitted_criteria[0]
    assert admitted.criterion_id == deferred.criterion_id
    assert admitted.predicate == {"path": "greet.py", "sha256": "b" * 64}

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


def _prepare_process_request(
    tmp_path: Path,
    *,
    executable: str,
    goal_revision: int = 1,
) -> contracts.ApprovalRequest:
    workspace = tmp_path / "process-workspace"
    workspace.mkdir(exist_ok=True)
    runtime = KernelToolRuntime(
        (
            build_local_process_registration(
                workspace=workspace,
                captured_path="/usr/bin:/bin",
            ),
        )
    )
    prepared = runtime.prepare(
        ToolCall(
            "call-process",
            "local_process",
            {
                "executable": executable,
                "argv": [],
                "cwd": ".",
                "profile": "short",
            },
        ),
        ToolPrepareContext(
            conversation_id="conversation-process",
            run_id="run-process",
            state_revision=0,
            goal_id="goal-artifact",
            goal_revision=goal_revision,
            workspace_identity_digest="workspace-artifact",
            proposed_criteria=(),
        ),
    )
    assert isinstance(prepared, contracts.ApprovalRequired)
    return prepared.request


def test_016_wrong_approved_process_cannot_satisfy_explicit_validator(
    tmp_path: Path,
) -> None:
    requirement = ProposedCriterion(
        "criterion:required-local-process:exact-validator",
        "the explicitly requested validator exits successfully",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    request = _prepare_process_request(tmp_path, executable="/bin/ls")
    active = ActiveRun(
        run_id=request.run_id,
        status=ActiveRunStatus.AWAITING_APPROVAL,
        phase=ContinuationPhase.TOOL,
        tool_calls=(
            ToolCall(
                request.tool_call_id,
                "local_process",
                {
                    "executable": "/bin/ls",
                    "argv": [],
                    "cwd": ".",
                    "profile": "short",
                },
            ),
        ),
        pending_request=request,
    )
    goal = replace(
        _goal(requirement),
        created_from_fact_ids=("fact-user",),
        user_outcome="运行 ./check-greet 验证结果",
    )
    state = replace(
        ConversationState.new("conversation-process"),
        goal=goal,
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "运行 ./check-greet 验证结果。"},
            ),
        ),
        active_run=active,
    )
    action = ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request.request_id,
        binding_digest=request.binding_digest,
        approved=True,
        approved_at="2026-08-16T00:01:00Z",
    )

    accepted = _apply_action(state, action)

    assert accepted.process_leases
    assert not any(
        item.criterion_id == requirement.criterion_id
        for item in accepted.goal.admitted_criteria
    )

def test_016_exact_approved_process_satisfies_explicit_validator(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "process-workspace"
    workspace.mkdir()
    validator = workspace / "check-greet"
    validator.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(validator, stat.S_IRWXU)
    requirement = ProposedCriterion(
        "criterion:required-local-process:exact-validator",
        "the explicitly requested validator exits successfully",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    request = _prepare_process_request(tmp_path, executable="./check-greet")
    active = ActiveRun(
        run_id=request.run_id,
        status=ActiveRunStatus.AWAITING_APPROVAL,
        phase=ContinuationPhase.TOOL,
        tool_calls=(
            ToolCall(
                request.tool_call_id,
                "local_process",
                {
                    "executable": "./check-greet",
                    "argv": [],
                    "cwd": ".",
                    "profile": "short",
                },
            ),
        ),
        pending_request=request,
    )
    state = replace(
        ConversationState.new("conversation-process"),
        goal=replace(
            _goal(requirement),
            created_from_fact_ids=("fact-user",),
            user_outcome="运行 ./check-greet 验证结果",
        ),
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "运行 ./check-greet 验证结果。"},
            ),
        ),
        active_run=active,
    )
    action = ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request.request_id,
        binding_digest=request.binding_digest,
        approved=True,
        approved_at="2026-08-16T00:01:00Z",
    )

    accepted = _apply_action(state, action)

    admitted = next(
        item
        for item in accepted.goal.admitted_criteria
        if item.criterion_id == requirement.criterion_id
    )
    assert admitted.predicate["command_fingerprint"] == (
        request.process_authority_candidate.command_fingerprint
    )


@pytest.mark.parametrize(
    ("source_text", "expected"),
    (
        (
            "不要运行 ./unsafe，只运行 ./scripts/check.py。",
            frozenset({"./scripts/check.py"}),
        ),
        (
            "Do not run ./unsafe; run ./scripts/check.py only.",
            frozenset({"./scripts/check.py"}),
        ),
    ),
)
def test_016_explicit_process_entrypoint_respects_negation_and_exact_path(
    source_text: str,
    expected: frozenset[str],
) -> None:
    requirement = ProposedCriterion(
        "criterion:required-local-process:exact-validator",
        "the explicitly requested validator exits successfully",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    state = replace(
        ConversationState.new("conversation-process-authority"),
        goal=replace(
            _goal(requirement),
            created_from_fact_ids=("fact-user",),
        ),
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": source_text},
            ),
        ),
    )

    assert authoritative_process_entrypoints(state) == expected
    assert process_entrypoint_matches_authority(state, "./scripts/check.py") is True
    assert process_entrypoint_matches_authority(state, "scripts/check.py") is False
    assert process_entrypoint_matches_authority(state, "./scripts/CHECK.py") is False


@pytest.mark.parametrize(
    "correction_text",
    (
        "How do I run ./other-validator?",
        "怎么运行 ./other-validator？",
    ),
)
def test_016_explanatory_process_question_does_not_replace_entrypoint_authority(
    correction_text: str,
) -> None:
    requirement = ProposedCriterion(
        "criterion:required-local-process:existing-validator",
        "the explicitly requested validator exits successfully",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    state = replace(
        ConversationState.new("conversation-process-question"),
        goal=replace(
            _goal(requirement),
            created_from_fact_ids=("fact-user", "fact-correction"),
        ),
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "Run ./check-report."},
            ),
            ConversationFact(
                fact_id="fact-correction",
                kind=FactKind.USER_MESSAGE,
                content={"text": correction_text, "control": "goal_correction"},
            ),
        ),
    )

    assert authoritative_process_entrypoints(state) == frozenset({"./check-report"})


@pytest.mark.parametrize(
    "correction_text",
    (
        "改为运行 ./new-check。",
        "Change it to run ./new-check.",
    ),
)
def test_016_process_entrypoint_correction_replaces_old_command_authority(
    tmp_path: Path,
    correction_text: str,
) -> None:
    workspace = tmp_path / "process-workspace"
    workspace.mkdir()
    for name in ("old-check", "new-check"):
        executable = workspace / name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(executable, stat.S_IRWXU)
    requirement = ProposedCriterion(
        "criterion:required-local-process:corrected-validator",
        "the corrected validator exits successfully",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    request = _prepare_process_request(
        tmp_path,
        executable="./old-check",
        goal_revision=2,
    )
    active = ActiveRun(
        run_id=request.run_id,
        status=ActiveRunStatus.AWAITING_APPROVAL,
        phase=ContinuationPhase.TOOL,
        tool_calls=(
            ToolCall(
                request.tool_call_id,
                "local_process",
                {
                    "executable": "./old-check",
                    "argv": [],
                    "cwd": ".",
                    "profile": "short",
                },
            ),
        ),
        pending_request=request,
    )
    state = replace(
        ConversationState.new("conversation-process-correction"),
        goal=replace(
            _goal(requirement),
            revision=2,
            created_from_fact_ids=("fact-user", "fact-correction"),
            user_outcome="运行 ./new-check 验证结果",
        ),
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "运行 ./old-check。"},
            ),
            ConversationFact(
                fact_id="fact-correction",
                kind=FactKind.USER_MESSAGE,
                content={"text": correction_text, "control": "goal_correction"},
            ),
        ),
        active_run=active,
    )
    action = ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request.request_id,
        binding_digest=request.binding_digest,
        approved=True,
        approved_at="2026-08-16T00:01:00Z",
    )

    assert authoritative_process_entrypoints(state) == frozenset({"./new-check"})
    accepted = _apply_action(state, action)
    assert accepted.process_leases
    assert not any(
        item.criterion_id == requirement.criterion_id
        for item in accepted.goal.admitted_criteria
    )

    exact_request = _prepare_process_request(
        tmp_path,
        executable="./new-check",
        goal_revision=2,
    )
    exact_state = replace(
        state,
        active_run=replace(
            active,
            run_id=exact_request.run_id,
            tool_calls=(
                ToolCall(
                    exact_request.tool_call_id,
                    "local_process",
                    {
                        "executable": "./new-check",
                        "argv": [],
                        "cwd": ".",
                        "profile": "short",
                    },
                ),
            ),
            pending_request=exact_request,
        ),
    )
    exact_action = replace(
        action,
        request_id=exact_request.request_id,
        binding_digest=exact_request.binding_digest,
    )

    exact = _apply_action(exact_state, exact_action)

    assert any(
        item.criterion_id == requirement.criterion_id
        for item in exact.goal.admitted_criteria
    )


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

"""017 native sandbox receipt + host read-back completion closure。"""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from agent.runtime.contracts import (
    AdmittedCriterion,
    CompletionClaim,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    FactKind,
    GoalStatus,
    ProposedCriterion,
    SandboxReceiptV1,
)
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from tests.continuity.test_contracts import _goal

ARTIFACT_PATH = "reports/out.md"
ARTIFACT_CONTENT = "sandbox report\n"
ARTIFACT_DIGEST = hashlib.sha256(ARTIFACT_CONTENT.encode()).hexdigest()
HEX_A = "a" * 64
HEX_B = "b" * 64
OBSERVED_AT = "2026-08-27T00:00:00+00:00"
REGISTRY = ClosedEvidenceRegistry()


def _receipt(**overrides) -> SandboxReceiptV1:  # noqa: ANN003
    values = {
        "receipt_id": "sandbox-receipt:one",
        "lease_id": "sandbox-lease:one",
        "lease_digest": HEX_A,
        "candidate_digest": HEX_B,
        "goal_id": "goal:1",
        "goal_revision": 1,
        "workspace_identity_digest": "workspace-digest-1",
        "original_command_fingerprint": HEX_A,
        "policy_digest": HEX_B,
        "mode": "workspace-write",
        "network": "off",
        "backend": "seatbelt",
        "enforcement": "confined",
        "profile_digest": HEX_A,
        "outcome": "exited",
        "draft_digest": HEX_B,
        "issued_at": OBSERVED_AT,
    }
    values.update(overrides)
    return SandboxReceiptV1.create(**values)


def _receipt_fact(receipt: SandboxReceiptV1, **metadata_overrides) -> ConversationFact:
    metadata = {
        "sandbox_receipt_kind": "native_sandbox_v1",
        "sandbox_receipt": receipt.to_json(),
        "receipt_digest": receipt.receipt_digest,
        "execution_authority": "isolated_sandbox",
        "outcome": receipt.outcome,
        "exit_code": 0,
        "original_command_fingerprint": receipt.original_command_fingerprint,
        "policy_digest": receipt.policy_digest,
        "mode": receipt.mode,
        "network": receipt.network,
        "backend": receipt.backend,
        "enforcement": receipt.enforcement,
        "profile_digest": receipt.profile_digest,
        "lease_id": receipt.lease_id,
    }
    metadata.update(metadata_overrides)
    return ConversationFact(
        fact_id="fact:sandbox-result:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-sandbox-1",
            "text": "sandbox command exited",
            "is_error": False,
            "executed": True,
            "metadata": metadata,
        },
    )


def _readback_facts() -> tuple[ConversationFact, ...]:
    return (
        ConversationFact(
            fact_id="fact:user:1",
            kind=FactKind.USER_MESSAGE,
            content={"text": "在 sandbox 中生成报告"},
        ),
        ConversationFact(
            fact_id="fact:calls:1",
            kind=FactKind.TOOL_CALLS,
            content={
                "calls": [
                    {
                        "tool_call_id": "read-1",
                        "name": "read_file",
                        "arguments": {"path": ARTIFACT_PATH},
                    }
                ]
            },
        ),
        ConversationFact(
            fact_id="fact:read-result:1",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "read-1",
                "text": ARTIFACT_CONTENT,
                "is_error": False,
                "executed": True,
                "metadata": {},
            },
        ),
    )


def _receipt_criterion(receipt: SandboxReceiptV1) -> AdmittedCriterion:
    return AdmittedCriterion(
        criterion_id="criterion:sandbox-execution",
        description="native sandbox execution receipt",
        source_fact_id="fact:user:1",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={
            "receipt_kind": "native_sandbox_v1",
            "receipt_digest": receipt.receipt_digest,
            "command_fingerprint": receipt.original_command_fingerprint,
            "policy_digest": receipt.policy_digest,
            "mode": receipt.mode,
            "network": receipt.network,
            "backend": receipt.backend,
            "enforcement": receipt.enforcement,
            "outcome": "exited",
        },
        required_evidence_class="native_sandbox_receipt",
        admission_digest="e" * 64,
        mandatory=True,
    )


def _filesystem_criterion() -> AdmittedCriterion:
    return AdmittedCriterion(
        criterion_id="criterion:artifact-readback",
        description="host artifact read-back digest",
        source_fact_id="fact:user:1",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate={"path": ARTIFACT_PATH, "sha256": ARTIFACT_DIGEST},
        required_evidence_class="workspace_file",
        admission_digest="f" * 64,
        mandatory=True,
    )


def _state(
    criteria: tuple[AdmittedCriterion, ...],
    facts: tuple[ConversationFact, ...],
) -> ConversationState:
    goal = replace(
        _goal(),
        proposed_criteria=tuple(
            ProposedCriterion(
                criterion_id=item.criterion_id,
                description=item.description,
                oracle_kind=item.oracle_kind,
            )
            for item in criteria
        ),
        admitted_criteria=criteria,
        status=GoalStatus.GOAL_READY,
    )
    return ConversationState(
        conversation_id="conversation-1",
        facts=facts,
        goal=goal,
    )


def _claim(criteria: tuple[AdmittedCriterion, ...]) -> CompletionClaim:
    return CompletionClaim(
        correlation_id="claim-1",
        goal_id="goal:1",
        goal_revision=1,
        criterion_evidence_refs=tuple(
            REGISTRY.evidence_id("goal:1", 1, item.criterion_id)
            for item in criteria
        ),
    )


def test_exit_zero_without_receipt_and_host_readback_is_not_verified_done() -> None:
    criteria = (_filesystem_criterion(),)
    output_only = ConversationFact(
        fact_id="fact:output-only",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-sandbox-1",
            "text": "command exited 0",
            "is_error": False,
            "executed": True,
            "metadata": {"outcome": "exited", "exit_code": 0},
        },
    )
    with pytest.raises(EvidenceVerificationError, match="read-back"):
        REGISTRY.derive(
            _state(criteria, (output_only,)),
            _claim(criteria),
            observed_at=OBSERVED_AT,
        )


def test_native_receipt_plus_host_digest_can_verify_artifact() -> None:
    receipt = _receipt()
    criteria = (_filesystem_criterion(), _receipt_criterion(receipt))
    records = REGISTRY.derive(
        _state(criteria, (*_readback_facts(), _receipt_fact(receipt))),
        _claim(criteria),
        observed_at=OBSERVED_AT,
    )
    assert {record.oracle_identity for record in records} == {
        "filesystem-digest:v1",
        "native-sandbox-receipt:v1",
    }


def test_receipt_and_readback_are_each_individually_insufficient() -> None:
    receipt = _receipt()
    criteria = (_filesystem_criterion(), _receipt_criterion(receipt))
    with pytest.raises(EvidenceVerificationError, match="read-back"):
        REGISTRY.derive(
            _state(criteria, (_receipt_fact(receipt),)),
            _claim(criteria),
            observed_at=OBSERVED_AT,
        )
    with pytest.raises(EvidenceVerificationError, match="sandbox receipt"):
        REGISTRY.derive(
            _state(criteria, _readback_facts()),
            _claim(criteria),
            observed_at=OBSERVED_AT,
        )


@pytest.mark.parametrize(
    ("receipt_overrides", "metadata_overrides"),
    [
        ({"goal_id": "goal:other"}, {}),
        ({"goal_revision": 2}, {}),
        ({"policy_digest": HEX_A}, {}),
        ({}, {"enforcement": "unconfined"}),
        ({}, {"receipt_digest": HEX_A}),
    ],
)
def test_forged_or_stale_native_receipt_fails_closed(
    receipt_overrides: dict,
    metadata_overrides: dict,
) -> None:
    receipt = _receipt(**receipt_overrides)
    criterion = _receipt_criterion(_receipt())
    with pytest.raises(EvidenceVerificationError, match="sandbox receipt"):
        REGISTRY.derive(
            _state((criterion,), (_receipt_fact(receipt, **metadata_overrides),)),
            _claim((criterion,)),
            observed_at=OBSERVED_AT,
        )

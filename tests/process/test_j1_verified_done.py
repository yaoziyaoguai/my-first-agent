"""015 J1 VERIFIED_DONE Red：process-produced artifact 需要双证据 criterion admission。

现有 CriterionAdmissionBinding 只在 write_file/edit_file approval 时铸造
FILESYSTEM_DIGEST criterion。process-produced artifact 需要不同路径：
1. TOOL_RECEIPT criterion：Runtime 在成功 Kernel process receipt 后铸造（不信任 model）。
2. FILESYSTEM_DIGEST criterion：expected artifact 在 effect 前由 authoritative source
   fact 或用户 typed binding 固定 path+sha256；model 之后 read_file，oracle 从 durable
   read-back fact 重算。

两个 mandatory criteria 齐全 + model 发 exact CompletionClaim 才 VERIFIED_DONE。
删除任一证据、错 digest/path/Goal/revision、exit 非 0、forged receipt 都必须 Red。
"""

from __future__ import annotations

import hashlib

import pytest

from agent.runtime.contracts import (
    AdmittedCriterion,
    ConversationFact,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    FactKind,
    ProcessOutcome,
    ProcessReceiptV1,
)


def _sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def test_015_process_receipt_criterion_can_be_admitted_and_verified() -> None:
    """R17/KTD10：TOOL_RECEIPT oracle 验证 process receipt criterion（closed predicate）。"""

    from agent.runtime.evidence import ClosedEvidenceRegistry

    registry = ClosedEvidenceRegistry()
    command_fingerprint = "f" * 64
    receipt = ProcessReceiptV1.create(
        lease_id="process-lease:j1",
        lease_digest="a" * 64,
        use_ordinal=1,
        goal_id="goal-j1",
        goal_revision=1,
        workspace_identity_digest="b" * 64,
        tool_identity="c" * 64,
        intent_digest="d" * 64,
        executable_digest="e" * 64,
        argv_digest="0" * 64,
        cwd_digest="1" * 64,
        resource_profile="standard",
        environment_policy_digest="2" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        outcome=ProcessOutcome.EXITED,
        exit_code=0,
        signal=None,
        started_at="1.0",
        ended_at="2.0",
        duration_seconds=1.0,
        stdout_digest="3" * 64,
        stderr_digest="4" * 64,
        stdout_bytes=1,
        stderr_bytes=0,
        stdout_truncated=False,
        stderr_truncated=False,
        group_cleanup_claim="unconfirmed",
        command_fingerprint=command_fingerprint,
    )
    receipt_digest = receipt.receipt_digest
    # Durable tool result fact with process receipt metadata
    fact = ConversationFact(
        fact_id="run:r:tool-result:call-j1:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-j1",
            "text": "local_process exited",
            "is_error": False,
            "executed": True,
            "metadata": {
                "process_receipt_kind": "process_v1",
                "process_receipt": receipt.to_json(),
                "receipt_digest": receipt_digest,
                "execution_authority": "local_same_uid_process",
                "outcome": "exited",
                "exit_code": 0,
                "command_fingerprint": command_fingerprint,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "duration_seconds": 1.0,
                "resource_profile": "standard",
                "stdout_digest": "3" * 64,
                "stderr_digest": "4" * 64,
                "lease_id": "process-lease:j1",
                "use_ordinal": 1,
                "tool_identity": "c" * 64,
            },
        },
    )
    criterion = AdmittedCriterion(
        criterion_id="criterion-process-receipt",
        description="process command contract satisfied",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={
            "receipt_kind": "process_v1",
            "receipt_digest": receipt_digest,
            "command_fingerprint": command_fingerprint,
            "outcome": "exited",
            "exit_code": 0,
        },
        required_evidence_class="process_receipt",
        admission_digest="m" * 64,
        mandatory=True,
    )
    record = registry._tool_receipt(
        (fact,),
        goal_id="goal-j1",
        goal_revision=1,
        criterion=criterion,
        evidence_id="evidence-process",
        observed_at="2026-08-09T00:00:00Z",
    )
    assert record.passed is True


def test_015_filesystem_digest_criterion_verifies_exact_readback() -> None:
    """R18/AE10：FILESYSTEM_DIGEST oracle 验证 artifact exact read-back。"""

    from agent.runtime.evidence import ClosedEvidenceRegistry

    registry = ClosedEvidenceRegistry()
    artifact_content = "deterministic artifact content"
    artifact_digest = _sha256_hex(artifact_content)
    # TOOL_CALLS fact: records the read_file call
    calls_fact = ConversationFact(
        fact_id="fact:calls:read-artifact",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": "read-artifact",
                    "name": "read_file",
                    "arguments": {"path": "artifact.out"},
                }
            ]
        },
    )
    # TOOL_RESULT fact: the read-back content
    result_fact = ConversationFact(
        fact_id="run:r:tool-result:read-artifact:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "read-artifact",
            "text": artifact_content,
            "is_error": False,
            "executed": True,
            "metadata": {
                "content_digest": artifact_digest,
                "path": "artifact.out",
            },
        },
    )
    criterion = AdmittedCriterion(
        criterion_id="criterion-artifact-digest",
        description="artifact reads back exactly",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate={"path": "artifact.out", "sha256": artifact_digest},
        required_evidence_class="workspace_file",
        admission_digest="n" * 64,
        mandatory=True,
    )
    record = registry._filesystem_digest(
        (calls_fact, result_fact),
        goal_id="goal-j1",
        goal_revision=1,
        criterion=criterion,
        evidence_id="evidence-artifact",
        observed_at="2026-08-09T00:00:00Z",
    )
    assert record.passed is True


def test_015_exit_zero_wrong_artifact_digest_blocks_verified_done() -> None:
    """R18/AE10：exit 0 但 artifact digest 不符 → artifact criterion 失败，不得 VERIFIED_DONE。"""

    from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError

    registry = ClosedEvidenceRegistry()
    wrong_digest = "x" * 64
    actual_digest = _sha256_hex("actual content")
    calls_fact_wrong = ConversationFact(
        fact_id="fact:calls:read-artifact-wrong",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": "read-artifact",
                    "name": "read_file",
                    "arguments": {"path": "artifact.out"},
                }
            ]
        },
    )
    fact_wrong = ConversationFact(
        fact_id="run:r:tool-result:read-artifact:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "read-artifact",
            "text": "actual content",
            "is_error": False,
            "executed": True,
            "metadata": {"content_digest": actual_digest, "path": "artifact.out"},
        },
    )
    criterion = AdmittedCriterion(
        criterion_id="criterion-artifact-wrong",
        description="artifact with wrong expected digest",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate={"path": "artifact.out", "sha256": wrong_digest},
        required_evidence_class="workspace_file",
        admission_digest="n" * 64,
        mandatory=True,
    )
    with pytest.raises(EvidenceVerificationError):
        registry._filesystem_digest(
            (calls_fact_wrong, fact_wrong),
            goal_id="goal-j1",
            goal_revision=1,
            criterion=criterion,
            evidence_id="evidence-wrong",
            observed_at="2026-08-09T00:00:00Z",
        )

"""015 U7：TOOL_RECEIPT oracle 的加式 process predicate（KTD10 / §11）。

legacy 单键 ``{"receipt_digest": ...}`` 行为不变；process predicate 是 closed typed
shape（receipt_kind=process_v1 + command_fingerprint + outcome，可选 receipt_digest；exited
还要求 exit_code），未知键/wrong outcome/wrong exit fail closed。oracle 从 durable raw
ToolResult fact 重算，不接受 fake/mock。
"""

from __future__ import annotations

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
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError


def _criterion(predicate: dict) -> AdmittedCriterion:
    return AdmittedCriterion(
        criterion_id="criterion-process",
        description="process command contract",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate=predicate,
        required_evidence_class="process_receipt",
        admission_digest="a" * 64,
        mandatory=True,
    )


def _process_fact(
    *,
    outcome: str = "exited",
    exit_code: int | None = 0,
    command_fingerprint: str = "f" * 64,
    fake: bool = False,
    stdout_digest: str = "1" * 64,
    stderr_digest: str = "2" * 64,
    flat_stdout_digest: str | None = None,
    include_receipt: bool = True,
) -> ConversationFact:
    closed_outcome = ProcessOutcome(outcome)
    if closed_outcome is not ProcessOutcome.EXITED:
        exit_code = None
    receipt = ProcessReceiptV1.create(
        lease_id="process-lease:candidate-x",
        lease_digest="a" * 64,
        use_ordinal=1,
        goal_id="goal-u7",
        goal_revision=1,
        workspace_identity_digest="b" * 64,
        tool_identity="c" * 64,
        intent_digest="d" * 64,
        executable_digest="e" * 64,
        argv_digest="0" * 64,
        cwd_digest="3" * 64,
        resource_profile="standard",
        environment_policy_digest="4" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        outcome=closed_outcome,
        exit_code=exit_code,
        signal="SIGTERM" if closed_outcome is ProcessOutcome.SIGNALED else None,
        started_at="1.0",
        ended_at="2.0",
        duration_seconds=1.0,
        stdout_digest=stdout_digest,
        stderr_digest=stderr_digest,
        stdout_bytes=1,
        stderr_bytes=2,
        stdout_truncated=False,
        stderr_truncated=False,
        group_cleanup_claim=(
            "reaped"
            if closed_outcome is ProcessOutcome.TIMED_OUT_REAPED
            else "unconfirmed"
        ),
        command_fingerprint=command_fingerprint,
    )
    metadata = {
        "process_receipt_kind": "process_v1",
        "receipt_digest": receipt.receipt_digest,
        "execution_authority": "local_same_uid_process",
        "outcome": outcome,
        "exit_code": exit_code,
        "command_fingerprint": command_fingerprint,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "duration_seconds": 1.0,
        "resource_profile": "standard",
        "stdout_digest": flat_stdout_digest or stdout_digest,
        "stderr_digest": stderr_digest,
        "lease_id": "process-lease:candidate-x",
        "use_ordinal": 1,
        "tool_identity": "c" * 64,
        "fake": fake,
    }
    if include_receipt:
        metadata["process_receipt"] = receipt.to_json()
    return ConversationFact(
        fact_id="run:r:tool-result:call-process:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-process",
            "text": "local_process exited",
            "is_error": False,
            "executed": True,
            "metadata": metadata,
        },
    )


def _receipt_digest(fact: ConversationFact) -> str:
    metadata = fact.content["metadata"]
    assert isinstance(metadata, dict)
    digest = metadata["receipt_digest"]
    assert isinstance(digest, str)
    return digest


def _legacy_fact(receipt_digest: str) -> ConversationFact:
    return ConversationFact(
        fact_id="run:r:tool-result:call-legacy:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-legacy",
            "text": "legacy effect",
            "is_error": False,
            "executed": True,
            "metadata": {"receipt_digest": receipt_digest},
        },
    )


def test_015_tool_receipt_legacy_single_key_predicate_still_proves() -> None:
    """KTD10：012-014 legacy 单键 ``{"receipt_digest"}`` 行为不变（加式，不放宽）。"""

    registry = ClosedEvidenceRegistry()
    digest = "d" * 64
    record = registry._tool_receipt(
        (_legacy_fact(digest),),
        goal_id="goal-u7",
        goal_revision=1,
        criterion=_criterion({"receipt_digest": digest}),
        evidence_id="evidence-u7-legacy",
        observed_at="now",
    )
    assert record.passed is True


def test_015_process_receipt_predicate_proves_command_criterion() -> None:
    """R17 / KTD10：typed process predicate 从 durable fact 证明 command criterion。"""

    registry = ClosedEvidenceRegistry()
    fact = _process_fact()
    digest = _receipt_digest(fact)
    record = registry._tool_receipt(
        (fact,),
        goal_id="goal-u7",
        goal_revision=1,
        criterion=_criterion(
            {
                "receipt_kind": "process_v1",
                "receipt_digest": digest,
                "command_fingerprint": "f" * 64,
                "outcome": "exited",
                "exit_code": 0,
            }
        ),
        evidence_id="evidence-u7-process",
        observed_at="now",
    )
    assert record.passed is True


def test_015_process_receipt_obligation_can_precede_exact_receipt_digest() -> None:
    """Approval-time obligation 以 Goal/revision/fingerprint 绑定，receipt 由 Kernel 后铸。"""

    registry = ClosedEvidenceRegistry()
    record = registry._tool_receipt(
        (_process_fact(),),
        goal_id="goal-u7",
        goal_revision=1,
        criterion=_criterion(
            {
                "receipt_kind": "process_v1",
                "command_fingerprint": "f" * 64,
                "outcome": "exited",
                "exit_code": 0,
            }
        ),
        evidence_id="evidence-u7-approval-obligation",
        observed_at="now",
    )

    assert record.passed is True


def test_015_process_receipt_requires_full_durable_kernel_payload() -> None:
    """R17 / design §5.6：扁平 metadata 不能冒充完整 Kernel receipt。

    当前事实若只有 ``receipt_digest/outcome/fingerprint``，任意 producer 都能拼出同形
    map；evidence oracle 必须先 strict-decode 并重算持久化的 ``ProcessReceiptV1``，
    再允许它证明 command criterion。
    """

    registry = ClosedEvidenceRegistry()
    fact = _process_fact(include_receipt=False)
    digest = _receipt_digest(fact)
    with pytest.raises(EvidenceVerificationError):
        registry._tool_receipt(
            (fact,),
            goal_id="goal-u7",
            goal_revision=1,
            criterion=_criterion(
                {
                    "receipt_kind": "process_v1",
                    "receipt_digest": digest,
                    "command_fingerprint": "f" * 64,
                    "outcome": "exited",
                    "exit_code": 0,
                }
            ),
            evidence_id="evidence-u7-full-receipt-required",
            observed_at="now",
        )


def test_015_process_receipt_wrong_outcome_fails_closed() -> None:
    """§11：outcome 不符（predicate exited，fact timed_out_reaped）→ fail closed。"""

    registry = ClosedEvidenceRegistry()
    fact = _process_fact(outcome="timed_out_reaped")
    digest = _receipt_digest(fact)
    with pytest.raises(EvidenceVerificationError):
        registry._tool_receipt(
            (fact,),
            goal_id="goal-u7",
            goal_revision=1,
            criterion=_criterion(
                {
                    "receipt_kind": "process_v1",
                    "receipt_digest": digest,
                    "command_fingerprint": "f" * 64,
                    "outcome": "exited",
                    "exit_code": 0,
                }
            ),
            evidence_id="evidence-u7-outcome",
            observed_at="now",
        )


def test_015_process_receipt_wrong_exit_code_fails_closed() -> None:
    """§11：exited 但 exit_code 不符 → fail closed（exit 0 不能伪造成成功）。"""

    registry = ClosedEvidenceRegistry()
    fact = _process_fact(exit_code=1)
    digest = _receipt_digest(fact)
    with pytest.raises(EvidenceVerificationError):
        registry._tool_receipt(
            (fact,),
            goal_id="goal-u7",
            goal_revision=1,
            criterion=_criterion(
                {
                    "receipt_kind": "process_v1",
                    "receipt_digest": digest,
                    "command_fingerprint": "f" * 64,
                    "outcome": "exited",
                    "exit_code": 0,
                }
            ),
            evidence_id="evidence-u7-exit",
            observed_at="now",
        )


def test_015_process_receipt_unknown_predicate_key_fails_closed() -> None:
    """§11：predicate 出现 closed allowlist 外的键 → fail closed。"""

    registry = ClosedEvidenceRegistry()
    fact = _process_fact()
    digest = _receipt_digest(fact)
    with pytest.raises(EvidenceVerificationError):
        registry._tool_receipt(
            (fact,),
            goal_id="goal-u7",
            goal_revision=1,
            criterion=_criterion(
                {
                    "receipt_kind": "process_v1",
                    "receipt_digest": digest,
                    "command_fingerprint": "f" * 64,
                    "outcome": "exited",
                    "exit_code": 0,
                    "rogue_key": "not allowed",
                }
            ),
            evidence_id="evidence-u7-unknown",
            observed_at="now",
        )


def test_015_process_receipt_fake_fact_is_rejected() -> None:
    """R17：fake/mock fact 不能证明 process criterion。"""

    registry = ClosedEvidenceRegistry()
    fact = _process_fact(fake=True)
    digest = _receipt_digest(fact)
    with pytest.raises(EvidenceVerificationError):
        registry._tool_receipt(
            (fact,),
            goal_id="goal-u7",
            goal_revision=1,
            criterion=_criterion(
                {
                    "receipt_kind": "process_v1",
                    "receipt_digest": digest,
                    "command_fingerprint": "f" * 64,
                    "outcome": "exited",
                    "exit_code": 0,
                }
            ),
            evidence_id="evidence-u7-fake",
            observed_at="now",
        )


def test_015_process_receipt_predicate_stdout_stderr_digests_are_enforced() -> None:
    """P3（冻结合同）：predicate 的 optional stdout/stderr digests 必须实际比较。

    此前 allowlist 接受这两个键但从不比较——带任意 stdout_digest 的 predicate 都能
    通过任何 receipt（空证据）。Green：声明即比较，不匹配 fail closed。"""

    registry = ClosedEvidenceRegistry()
    matching = _process_fact(stdout_digest="1" * 64, stderr_digest="2" * 64)
    digest = _receipt_digest(matching)
    predicate = {
        "receipt_kind": "process_v1",
        "receipt_digest": digest,
        "command_fingerprint": "f" * 64,
        "outcome": "exited",
        "exit_code": 0,
        "stdout_digest": "1" * 64,
        "stderr_digest": "2" * 64,
    }
    record = registry._tool_receipt(
        (matching,),
        goal_id="goal-u7",
        goal_revision=1,
        criterion=_criterion(predicate),
        evidence_id="evidence-u7-digests",
        observed_at="now",
    )
    assert record.passed is True

    mismatched = _process_fact(
        stdout_digest="1" * 64,
        stderr_digest="2" * 64,
        flat_stdout_digest="9" * 64,
    )
    with pytest.raises(EvidenceVerificationError):
        registry._tool_receipt(
            (mismatched,),
            goal_id="goal-u7",
            goal_revision=1,
            criterion=_criterion(predicate),
            evidence_id="evidence-u7-digests-mismatch",
            observed_at="now",
        )

    with pytest.raises(EvidenceVerificationError):
        registry._tool_receipt(
            (matching,),
            goal_id="goal-u7",
            goal_revision=1,
            criterion=_criterion({**predicate, "stdout_digest": "not-hex"}),
            evidence_id="evidence-u7-digests-malformed",
            observed_at="now",
        )

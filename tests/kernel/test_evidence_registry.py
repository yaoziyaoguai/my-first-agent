"""015 U7：TOOL_RECEIPT oracle 的加式 process predicate（KTD10 / §11）。

legacy 单键 ``{"receipt_digest": ...}`` 行为不变；process predicate 是 closed typed
shape（receipt_kind=process_v1 + command_fingerprint + outcome，可选 receipt_digest；exited
还要求 exit_code），未知键/wrong outcome/wrong exit fail closed。oracle 从 durable raw
ToolResult fact 重算，不接受 fake/mock。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent.runtime.contracts import (
    ActiveRun,
    AdmittedCriterion,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    FactKind,
    ProcessOutcome,
    ProcessReceiptV1,
    ProposedCriterion,
)
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from tests.continuity.test_contracts import _goal


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


def _obligation_state(goal) -> ConversationState:  # noqa: ANN001
    return ConversationState(
        conversation_id="conversation-obligations",
        facts=(
            ConversationFact(
                fact_id="fact:user:1",
                kind=FactKind.USER_MESSAGE,
                content={"text": "do the work"},
            ),
        ),
        goal=goal,
        active_run=ActiveRun("run-obligations"),
    )


def test_gap_assessment_dispatches_repair_tools_and_instruction_together() -> None:
    """derive 失败原因的「可修工具 + 有界修复指引」必须由 evidence 模块同源分发。"""

    assessment = ClosedEvidenceRegistry().assess_gap(
        "no exact read-back fact proves the research artifact",
        available_tools=(
            "read_file",
            "write_file",
            "edit_file",
            "build_citation_manifest",
        ),
    )

    assert assessment.repairable_tools == ("read_file",)
    assert "read_file" in assessment.repair_instruction
    assert "build_citation_manifest" in assessment.repair_instruction
    assert "rewrite the citation sidecar" in assessment.repair_instruction


def test_gap_assessment_filters_tools_by_availability_not_instruction() -> None:
    """修复指引是缺口本身的属性；工具列表才是可用工具的投影。"""

    filtered = ClosedEvidenceRegistry().assess_gap(
        "no exact read-back fact proves the research artifact",
        available_tools=("edit_file",),
    )
    unfiltered = ClosedEvidenceRegistry().assess_gap(
        "no exact read-back fact proves the research artifact",
    )

    assert filtered.repairable_tools == ()
    assert filtered.repair_instruction == unfiltered.repair_instruction


def test_gap_assessment_covers_manifest_binding_family_without_blocked_exit() -> None:
    for reason in (
        "citation manifest is not bound to the exact artifact",
        "citation manifest is not bound to the current Goal",
        "citation manifest read-back is invalid",
        "each citation marker must occur in the artifact",
    ):
        assessment = ClosedEvidenceRegistry().assess_gap(
            reason,
            available_tools=("read_file", "build_citation_manifest", "write_file"),
        )

        assert assessment.repairable_tools == (
            "read_file",
            "build_citation_manifest",
            "write_file",
        ), reason
        assert "build_citation_manifest" in assessment.repair_instruction, reason
        assert "blocked_claim" not in assessment.repair_instruction, reason


def test_gap_assessment_keeps_instruction_for_gap_without_repairable_tools() -> None:
    assessment = ClosedEvidenceRegistry().assess_gap(
        "source receipt is not bound to the current Goal",
    )

    assert assessment.repairable_tools == ()
    assert "before this Goal" in assessment.repair_instruction
    assert "materially different" in assessment.repair_instruction


def test_gap_assessment_unknown_reason_falls_back_to_generic_instruction() -> None:
    assessment = ClosedEvidenceRegistry().assess_gap(
        "an unseen verification failure",
        available_tools=("read_file",),
    )

    assert assessment.repairable_tools == ()
    assert assessment.repair_instruction == (
        "Do not repeat completion. Call the concrete tools needed to create the "
        "missing evidence, or send blocked_claim if no safe action can advance the Goal."
    )


def test_gap_assessment_extended_web_kind_reason_keeps_substring_instruction() -> None:
    """旧 _evidence_repair_instruction 对该家族是 substring 匹配。

    带额外上下文的 reason 仍须取得专属 web_fetch 修复指引（不得退化为含
    blocked_claim 的通用兜底）；同时保留旧 asymmetry——工具分发始终精确
    匹配，扩展 reason 不能凭 substring 获得 web_fetch 工具。
    """

    extended = (
        "required source kind must contain extracted web content, not a search "
        "snippet (observed at goal revision 3)"
    )
    exact = (
        "required source kind must contain extracted web content, not a search snippet"
    )

    assessment = ClosedEvidenceRegistry().assess_gap(
        extended,
        available_tools=("web_fetch",),
    )

    assert assessment.repair_instruction == ClosedEvidenceRegistry().assess_gap(
        exact
    ).repair_instruction
    assert "unattempted source_ref" in assessment.repair_instruction
    assert "blocked_claim" not in assessment.repair_instruction
    assert assessment.repairable_tools == ()


def test_pending_obligation_tools_requires_write_for_unadmitted_filesystem_goal() -> None:
    state = _obligation_state(_goal(admitted_criteria=()))

    assert ClosedEvidenceRegistry().pending_obligation_tools(
        state,
        available_tools=("read_file", "write_file", "edit_file"),
    ) == ("write_file",)


def test_pending_obligation_tools_empty_without_active_run_or_goal() -> None:
    registry = ClosedEvidenceRegistry()
    state = _obligation_state(_goal())

    assert registry.pending_obligation_tools(
        replace(state, active_run=None),
        available_tools=("write_file",),
    ) == ()
    assert registry.pending_obligation_tools(
        replace(state, goal=None),
        available_tools=("write_file",),
    ) == ()


def test_pending_obligation_tools_requires_web_retrieval_until_attempted() -> None:
    goal = _goal(
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:required-public-web:web-1",
                description="public web source receipt",
                oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            ),
        ),
        admitted_criteria=(),
    )

    assert ClosedEvidenceRegistry().pending_obligation_tools(
        _obligation_state(goal),
        available_tools=("web_fetch", "read_file"),
    ) == ("web_fetch",)


def test_pending_obligation_tools_requires_process_until_relevant_attempt() -> None:
    goal = _goal(
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:required-local-process:proc-1",
                description="governed local process receipt",
                oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
            ),
        ),
        admitted_criteria=(),
    )

    assert ClosedEvidenceRegistry().pending_obligation_tools(
        _obligation_state(goal),
        available_tools=("local_process", "read_file"),
    ) == ("local_process",)

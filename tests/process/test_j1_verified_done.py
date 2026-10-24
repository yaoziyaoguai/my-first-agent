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

    from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError

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

    later_edit = ConversationFact(
        fact_id="run:r:tool-result:edit-after-validation:2",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "edit-after-validation",
            "text": "edited src/export.py",
            "is_error": False,
            "executed": True,
            "metadata": {"tool_name": "edit_file"},
        },
    )
    with pytest.raises(EvidenceVerificationError, match="was invalidated by later workspace"):
        registry._tool_receipt(
            (fact, later_edit),
            goal_id="goal-j1",
            goal_revision=1,
            criterion=criterion,
            evidence_id="evidence-process",
            observed_at="2026-08-09T00:00:01Z",
        )

    failed_receipt = ProcessReceiptV1.create(
        lease_id="process-lease:j1-failed",
        lease_digest="5" * 64,
        use_ordinal=1,
        goal_id="goal-j1",
        goal_revision=1,
        workspace_identity_digest="b" * 64,
        tool_identity="c" * 64,
        intent_digest="6" * 64,
        executable_digest="e" * 64,
        argv_digest="7" * 64,
        cwd_digest="1" * 64,
        resource_profile="standard",
        environment_policy_digest="2" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        outcome=ProcessOutcome.EXITED,
        exit_code=1,
        signal=None,
        started_at="3.0",
        ended_at="4.0",
        duration_seconds=1.0,
        stdout_digest="8" * 64,
        stderr_digest="9" * 64,
        stdout_bytes=0,
        stderr_bytes=1,
        stdout_truncated=False,
        stderr_truncated=False,
        group_cleanup_claim="unconfirmed",
        command_fingerprint="0" * 64,
    )
    later_failed_process = ConversationFact(
        fact_id="run:r:tool-result:failed-after-validation:3",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "failed-after-validation",
            "text": "local_process exited 1",
            "is_error": True,
            "executed": True,
            "metadata": {
                "process_receipt_kind": "process_v1",
                "process_receipt": failed_receipt.to_json(),
                "receipt_digest": failed_receipt.receipt_digest,
                "execution_authority": "local_same_uid_process",
                "outcome": "exited",
                "exit_code": 1,
                "command_fingerprint": "0" * 64,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "duration_seconds": 1.0,
                "resource_profile": "standard",
                "stdout_digest": "8" * 64,
                "stderr_digest": "9" * 64,
                "lease_id": "process-lease:j1-failed",
                "use_ordinal": 1,
                "tool_identity": "c" * 64,
            },
        },
    )
    with pytest.raises(EvidenceVerificationError, match="was invalidated by later workspace"):
        registry._tool_receipt(
            (fact, later_failed_process),
            goal_id="goal-j1",
            goal_revision=1,
            criterion=criterion,
            evidence_id="evidence-process",
            observed_at="2026-08-09T00:00:02Z",
        )


def test_015_process_rejected_before_execution_does_not_invalidate_validation() -> None:
    """执行前的 fail-closed 拒绝没有 workspace effect，不伪造验证过期。"""

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
                "receipt_digest": receipt.receipt_digest,
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
    rejected = ConversationFact(
        fact_id="run:r:tool-result:rejected:2",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "rejected",
            "text": "policy rejected",
            "is_error": True,
            "executed": False,
            "metadata": {"code": "approval_required"},
        },
    )
    criterion = AdmittedCriterion(
        criterion_id="criterion-process-receipt",
        description="process command contract satisfied",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={
            "receipt_kind": "process_v1",
            "receipt_digest": receipt.receipt_digest,
            "command_fingerprint": command_fingerprint,
            "outcome": "exited",
            "exit_code": 0,
        },
        required_evidence_class="process_receipt",
        admission_digest="m" * 64,
        mandatory=True,
    )

    record = registry._tool_receipt(
        (fact, rejected),
        goal_id="goal-j1",
        goal_revision=1,
        criterion=criterion,
        evidence_id="evidence-process",
        observed_at="2026-08-09T00:00:01Z",
    )
    assert record.passed is True


def test_015_unsandboxed_validation_processes_no_longer_coexist_read_only_sandbox_does() -> None:
    """F1（2026-10-02）：成功退出不等于无写入。

    旧合同（tests/lint 未沙箱 receipt 互相共存）是审计缺陷：exit 0 的 same-UID
    process 不能证明没有改写验证输入，其后的已执行 result 必须保守失效先前的
    验证证据。可证明的"无 mutation 共存"路径是 read-only native sandbox
    （host 实际隔离强制）；见 test_f1_input_mutation_invalidation.py。
    """

    from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError

    registry = ClosedEvidenceRegistry()

    def receipt_fact(label: str, fingerprint: str) -> ConversationFact:
        receipt = ProcessReceiptV1.create(
            lease_id=f"process-lease:{label}",
            lease_digest=label * 64,
            use_ordinal=1,
            goal_id="goal-j1",
            goal_revision=1,
            workspace_identity_digest="b" * 64,
            tool_identity="c" * 64,
            intent_digest=fingerprint,
            executable_digest="e" * 64,
            argv_digest=fingerprint,
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
            command_fingerprint=fingerprint,
        )
        return ConversationFact(
            fact_id=f"run:r:tool-result:{label}:1",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": label,
                "text": "local_process exited",
                "is_error": False,
                "executed": True,
                "metadata": {
                    "process_receipt_kind": "process_v1",
                    "process_receipt": receipt.to_json(),
                    "receipt_digest": receipt.receipt_digest,
                    "execution_authority": "local_same_uid_process",
                    "outcome": "exited",
                    "exit_code": 0,
                    "command_fingerprint": fingerprint,
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "duration_seconds": 1.0,
                    "resource_profile": "standard",
                    "stdout_digest": "3" * 64,
                    "stderr_digest": "4" * 64,
                    "lease_id": f"process-lease:{label}",
                    "use_ordinal": 1,
                    "tool_identity": "c" * 64,
                },
            },
        )

    def criterion(label: str, fingerprint: str) -> AdmittedCriterion:
        return AdmittedCriterion(
            criterion_id=f"criterion-{label}",
            description=f"{label} validation passed",
            source_fact_id="fact-user",
            oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
            predicate={
                "receipt_kind": "process_v1",
                "command_fingerprint": fingerprint,
                "outcome": "exited",
                "exit_code": 0,
            },
            required_evidence_class="process_receipt",
            admission_digest=label * 64,
            mandatory=True,
        )

    tests_fact = receipt_fact("a", "a" * 64)
    lint_fact = receipt_fact("b", "b" * 64)
    # 后续已执行 result 使先前的验证证据失效：不得凭两个未沙箱 receipt 完成两个
    # criterion（旧合同在此放行，是审计确认的 VERIFIED_DONE 误判来源）。
    with pytest.raises(EvidenceVerificationError, match="was invalidated by later workspace"):
        registry._tool_receipt(
            (tests_fact, lint_fact),
            goal_id="goal-j1",
            goal_revision=1,
            criterion=criterion("a", "a" * 64),
            evidence_id="evidence-a",
            observed_at="2026-08-09T00:00:01Z",
        )
    # 最后一个已执行 receipt 仍然支持其自身 criterion：有限步内重新验证的路径存在。
    record = registry._tool_receipt(
        (tests_fact, lint_fact),
        goal_id="goal-j1",
        goal_revision=1,
        criterion=criterion("b", "b" * 64),
        evidence_id="evidence-b",
        observed_at="2026-08-09T00:00:01Z",
    )
    assert record.passed is True


@pytest.mark.parametrize("tool_name", ("read_file", "confirm_file"))
def test_015_filesystem_digest_criterion_verifies_exact_readback(
    tool_name: str,
) -> None:
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
                    "name": tool_name,
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


def test_015_compat_mint_skips_when_digest_free_obligation_covers_fingerprint() -> None:
    """2026-10-24 P1：同指纹 digest-free 义务在场时，兼容铸造不得再加 pinned 副本。

    digest-pinned per-call criterion 在其 receipt 因后续 workspace 变更失效后
    永不可满足；批准路径铸出的 digest-free 义务已覆盖同一命令的重验需求。
    """

    from agent.runtime.state import admit_process_receipt_criterion

    obligation = AdmittedCriterion(
        criterion_id="criterion:required-local-process:goal:1",
        description="the explicitly requested local validation process exits successfully",
        source_fact_id="fact:user:1",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={
            "receipt_kind": "process_v1",
            "command_fingerprint": "9e" * 32,
            "outcome": "exited",
            "exit_code": 0,
        },
        required_evidence_class="process_receipt",
        admission_digest="m" * 64,
        mandatory=True,
    )
    state = _state_with_single_obligation(obligation)
    result = admit_process_receipt_criterion(
        state,
        tool_call_id="call-old",
        receipt_digest="ab" * 32,
        command_fingerprint="9e" * 32,
        action_seq=3,
    )
    assert result.goal is not None
    assert [c.criterion_id for c in result.goal.admitted_criteria] == [
        obligation.criterion_id
    ], "compat mint must not add a digest-pinned duplicate beside the obligation"


def test_015_compat_mint_still_admits_uncovered_fingerprint() -> None:
    """兼容路径负边界：不同指纹（未被 digest-free 义务覆盖）仍按原样铸造。"""

    from agent.runtime.state import admit_process_receipt_criterion

    obligation = AdmittedCriterion(
        criterion_id="criterion:required-local-process:goal:1",
        description="the explicitly requested local validation process exits successfully",
        source_fact_id="fact:user:1",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={
            "receipt_kind": "process_v1",
            "command_fingerprint": "9e" * 32,
            "outcome": "exited",
            "exit_code": 0,
        },
        required_evidence_class="process_receipt",
        admission_digest="m" * 64,
        mandatory=True,
    )
    state = _state_with_single_obligation(obligation)
    result = admit_process_receipt_criterion(
        state,
        tool_call_id="call-new",
        receipt_digest="cd" * 32,
        command_fingerprint="d9" * 32,
        action_seq=4,
    )
    assert result.goal is not None
    minted = [
        c
        for c in result.goal.admitted_criteria
        if c.criterion_id == "criterion:process-receipt:goal:1:1:call-new"
    ]
    assert len(minted) == 1
    assert minted[0].predicate["receipt_digest"] == "cd" * 32


def _state_with_single_obligation(obligation: AdmittedCriterion):
    from agent.runtime.contracts import ConversationState, GoalFrame, GoalStatus

    user = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "完成修改并运行 python3 check.py 验证"},
    )
    return ConversationState(
        conversation_id="conversation:1",
        goal=GoalFrame(
            goal_id="goal:1",
            revision=1,
            created_from_fact_ids=("fact:user:1",),
            workspace_identity_digest="workspace:v1:" + "c" * 64,
            user_outcome="修改完成且验证通过",
            beneficiary="owner",
            targets=("app.py",),
            scope=("workspace",),
            non_goals=(),
            assumptions=(),
            proposed_criteria=(),
            admitted_criteria=(obligation,),
            authority_snapshot="authority:v1:" + "d" * 64,
            status=GoalStatus.GOAL_READY,
            created_at="2026-10-24T00:00:00Z",
            updated_at="2026-10-24T00:00:00Z",
        ),
        facts=(user,),
    )

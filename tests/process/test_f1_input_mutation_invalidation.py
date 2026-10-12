"""F1（2026-10-02 bounded-reliability）：成功 process 改写验证输入后，旧验证不得支持完成。

审计事实（START-HERE F1）：``_may_invalidate_workspace_validation`` 把 exit 0 的
same-UID process 当成"另一项验证"，成功改写验证输入的 process 不能失效旧的
read-back / 过程验证，导致错误 VERIFIED_DONE。本文件反例全部走生产事实形状；
A01 场景由真实 composition + KernelToolRuntime 完整驱动。

修复后的合同：
- 已执行的 same-UID process（成功/失败/超时）保守失效其前的工作区验证证据；
  成功退出不等于无写入。
- 未执行（policy/approval 拒绝、spawn_failed）不误伤已有效证据。
- read-only + confined 的 native sandbox 是唯一可证明的"无 mutation 共存"路径：
  host 实际隔离强制其不能改写工作区，tests/lint 两项 read-only 验证可共同成立。
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from agent.cli.app import _parse_action
from agent.composition import build_composition, build_tool_registrations
from agent.continuity.sessions import open_workspace_session
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    AdmittedCriterion,
    CompletionClaim,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    FactKind,
    GoalFrame,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    ProcessOutcome,
    ProcessReceiptV1,
    ProposedCriterion,
    RunStatus,
    SandboxReceiptV1,
    SubmitMessage,
)
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from agent.runtime.loop import InvocationLimits
from tests.kernel.fakes import CollectingSink, goal_draft_from_frame


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


CONTENT_A = "artifact version A\n"
CONTENT_B = "artifact version B\n"
HEX_A = "a" * 64
HEX_B = "b" * 64
OBSERVED_AT = "2026-10-02T00:00:00+00:00"
REGISTRY = ClosedEvidenceRegistry()
ARTIFACT_REL = "reports/final.md"


def _process_receipt_fact(
    label: str,
    *,
    fingerprint: str,
    exit_code: int | None,
    outcome: ProcessOutcome = ProcessOutcome.EXITED,
    is_error: bool | None = None,
) -> ConversationFact:
    """生产 receipt 形状的 local_process TOOL_RESULT fact（KernelToolRuntime 铸造形）。"""

    if outcome is ProcessOutcome.TIMED_OUT_REAPED:
        # closed 合同：timed_out_reaped 不 pin exit_code，且总是已执行的错误结果。
        exit_code = None
        is_error = True
        group_cleanup_claim = "reaped"
    else:
        group_cleanup_claim = "unconfirmed"
        if is_error is None:
            is_error = exit_code != 0
    lease_digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    receipt = ProcessReceiptV1.create(
        lease_id=f"process-lease:{label}",
        lease_digest=lease_digest,
        use_ordinal=1,
        goal_id="goal-f1",
        goal_revision=1,
        workspace_identity_digest=HEX_B,
        tool_identity="c" * 64,
        intent_digest=fingerprint,
        executable_digest="e" * 64,
        argv_digest=fingerprint,
        cwd_digest="1" * 64,
        resource_profile="standard",
        environment_policy_digest="2" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        outcome=outcome,
        exit_code=exit_code,
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
        group_cleanup_claim=group_cleanup_claim,
        command_fingerprint=fingerprint,
    )
    return ConversationFact(
        fact_id=f"fact:tool-result:{label}",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": label,
            "text": "local_process exited",
            "is_error": is_error,
            "executed": True,
            "metadata": {
                "process_receipt_kind": "process_v1",
                "process_receipt": receipt.to_json(),
                "receipt_digest": receipt.receipt_digest,
                "execution_authority": "local_same_uid_process",
                "outcome": receipt.outcome.value,
                "exit_code": exit_code,
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


def _sandbox_receipt_fact(
    label: str,
    *,
    fingerprint: str,
) -> tuple[ConversationFact, SandboxReceiptV1]:
    """read-only + confined native sandbox receipt fact（runtime 铸造形）。"""

    receipt = SandboxReceiptV1.create(
        receipt_id=f"sandbox-receipt:{label}",
        lease_id=f"sandbox-lease:{label}",
        lease_digest=HEX_A,
        candidate_digest=HEX_B,
        goal_id="goal-f1",
        goal_revision=1,
        workspace_identity_digest=HEX_B,
        original_command_fingerprint=fingerprint,
        policy_digest=HEX_B,
        mode="read-only",
        network="off",
        backend="seatbelt",
        enforcement="confined",
        profile_digest=HEX_A,
        outcome="exited",
        draft_digest=HEX_B,
        issued_at=OBSERVED_AT,
    )
    fact = ConversationFact(
        fact_id=f"fact:tool-result:{label}",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": label,
            "text": "sandbox command exited",
            "is_error": False,
            "executed": True,
            "metadata": {
                "sandbox_receipt_kind": "native_sandbox_v1",
                "sandbox_receipt": receipt.to_json(),
                "receipt_digest": receipt.receipt_digest,
                "execution_authority": "isolated_sandbox",
                "outcome": "exited",
                "exit_code": 0,
                "original_command_fingerprint": fingerprint,
                "policy_digest": HEX_B,
                "mode": "read-only",
                "network": "off",
                "backend": "seatbelt",
                "enforcement": "confined",
                "profile_digest": HEX_A,
                "lease_id": f"sandbox-lease:{label}",
            },
        },
    )
    return fact, receipt


def _sandbox_receipt_criterion(criterion_id: str, receipt: SandboxReceiptV1) -> AdmittedCriterion:
    return AdmittedCriterion(
        criterion_id=criterion_id,
        description="read-only native sandbox validation receipt",
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


def _process_receipt_criterion(receipt: ProcessReceiptV1) -> AdmittedCriterion:
    return AdmittedCriterion(
        criterion_id="criterion:process-validation",
        description="process command contract satisfied",
        source_fact_id="fact:user:1",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={
            "receipt_kind": "process_v1",
            "receipt_digest": receipt.receipt_digest,
            "command_fingerprint": receipt.command_fingerprint,
            "outcome": "exited",
            "exit_code": receipt.exit_code,
        },
        required_evidence_class="process_receipt",
        admission_digest="m" * 64,
        mandatory=True,
    )


def _f1_goal(
    criteria: tuple[AdmittedCriterion, ...],
    *,
    targets: tuple[str, ...] = ("reports/final.md",),
) -> GoalFrame:
    return GoalFrame(
        goal_id="goal-f1",
        revision=1,
        created_from_fact_ids=("fact:user:1",),
        workspace_identity_digest=HEX_B,
        user_outcome="bounded reliability F1 scenario",
        beneficiary="user",
        targets=targets,
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=tuple(
            ProposedCriterion(
                criterion_id=item.criterion_id,
                description=item.description,
                oracle_kind=item.oracle_kind,
            )
            for item in criteria
        ),
        admitted_criteria=criteria,
        authority_snapshot="fixed-composition",
        status=GoalStatus.GOAL_READY,
        created_at=OBSERVED_AT,
        updated_at=OBSERVED_AT,
    )


def _state(facts: tuple[ConversationFact, ...], criteria) -> ConversationState:
    return ConversationState(
        conversation_id="conversation-f1",
        facts=facts,
        goal=_f1_goal(criteria),
    )


def _claim(criteria: tuple[AdmittedCriterion, ...]) -> CompletionClaim:
    return CompletionClaim(
        correlation_id="claim-f1",
        goal_id="goal-f1",
        goal_revision=1,
        criterion_evidence_refs=tuple(
            REGISTRY.evidence_id("goal-f1", 1, item.criterion_id) for item in criteria
        ),
    )


def _user_fact() -> ConversationFact:
    return ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "bounded reliability F1 scenario"},
    )


def _readback_facts(
    path: str,
    content: str,
    *,
    call_id: str = "read-final",
) -> tuple[ConversationFact, ...]:
    return (
        ConversationFact(
            fact_id=f"fact:calls:{call_id}",
            kind=FactKind.TOOL_CALLS,
            content={
                "calls": [
                    {
                        "tool_call_id": call_id,
                        "name": "read_file",
                        "arguments": {"path": path},
                    }
                ]
            },
        ),
        ConversationFact(
            fact_id=f"fact:read-result:{call_id}",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": call_id,
                "text": content,
                "is_error": False,
                "executed": True,
                "metadata": {},
            },
        ),
    )


class _F1MutationProvider:
    """A01 剧本：goal → governed read-back A → 改写 process → stale claim。"""

    def __init__(self, executable: str) -> None:
        self.executable = executable
        self.calls: list = []

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls.append(context)
        index = len(self.calls)
        if index == 1:
            bootstrap = context.goal_bootstrap
            assert bootstrap is not None
            return ModelResponse(
                (),
                control=goal_draft_from_frame(
                    correlation_id="proposal-f1",
                    goal=GoalFrame(
                        goal_id="goal-f1-prod",
                        revision=1,
                        created_from_fact_ids=(bootstrap.source_fact_id,),
                        workspace_identity_digest=bootstrap.workspace_identity_digest,
                        user_outcome="Produce reports/final.md and verify",
                        beneficiary="user",
                        targets=(ARTIFACT_REL,),
                        scope=("workspace",),
                        non_goals=(),
                        assumptions=(),
                        proposed_criteria=(
                            ProposedCriterion(
                                "criterion:process-artifact:goal-f1-prod:1:"
                                + ARTIFACT_REL,
                                "artifact reads back with exact sha256",
                                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                                artifact_path=ARTIFACT_REL,
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
                        created_at=OBSERVED_AT,
                        updated_at=OBSERVED_AT,
                    ),
                ),
            )
        if index == 2:
            return ModelResponse(
                (
                    ModelToolCall(
                        "read-final", "read_file", {"path": ARTIFACT_REL}
                    ),
                )
            )
        if index == 3:
            return ModelResponse(
                (
                    ModelToolCall(
                        "call-mutate",
                        "local_process",
                        {
                            "executable": self.executable,
                            "argv": [],
                            "cwd": ".",
                            "profile": "short",
                        },
                    ),
                )
            )
        if index == 4:
            goal_block = next(
                block
                for msg in reversed(context.messages)
                for block in msg.content
                if block.get("type") == "trusted_goal"
            )
            return ModelResponse(
                (),
                control=CompletionClaim(
                    correlation_id="completion-f1",
                    goal_id=goal_block["goal_id"],
                    goal_revision=goal_block["goal_revision"],
                    criterion_evidence_refs=tuple(
                        goal_block["expected_completion_evidence_refs"]
                    ),
                ),
            )
        return ModelResponse((ModelTextBlock("no further claims"),))


def test_f1_successful_process_rewriting_readback_artifact_blocks_completion(
    tmp_path: Path,
) -> None:
    """A01：read-back A → 真实 local_process 写成 B → 旧 A 不得支持 VERIFIED_DONE。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = (tmp_path / "state").resolve()
    state_root.mkdir(parents=True, mode=0o700)
    os.chmod(state_root, 0o700)

    (workspace / "reports").mkdir()
    (workspace / ARTIFACT_REL).write_text(CONTENT_A, encoding="utf-8")
    sha_a = _sha256_hex(CONTENT_A)

    # 真实改写可执行：同 UID 进程把 reports/final.md 从 A 改写为 B，exit 0。
    mutator = workspace / "mutate-final"
    mutator.write_text(
        f"#!/bin/sh\nprintf 'artifact version B\\n' > {ARTIFACT_REL}\nprintf done\n",
        encoding="utf-8",
    )
    os.chmod(mutator, stat.S_IRWXU)

    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-0000000000f1",
    )
    registrations = build_tool_registrations(
        workspace=workspace,
        protected_paths=(opened.checkpoint_path,),
        max_tool_result_chars=50_000,
    )
    provider = _F1MutationProvider(executable="mutate-final")
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
            run_id="run-f1-prod",
            message="Maintain reports/final.md, verify it, do not change its approved identity.",
        ),
        store.load(),
    )

    while result.status is not RunStatus.COMPLETED:
        state = store.load().state
        if result.status is RunStatus.AWAITING_DISCLOSURE:
            action = AcknowledgeProviderDisclosure(
                conversation_id=state.conversation_id,
                action_seq=state.next_action_seq,
                expected_revision=state.revision,
                request_digest=state.provider_disclosure_request.request_digest,
                acknowledged_at=OBSERVED_AT,
            )
        elif result.status is RunStatus.AWAITING_APPROVAL:
            assert result.request.process_authority_candidate is not None
            candidate = result.request.process_authority_candidate
            requirement = result.request.artifact_confirmation_requirement
            assert requirement is not None
            # 用户按 read-back 到的 A 身份批准 artifact 绑定（生产 /approve-artifact 路径）。
            action, error = _parse_action(
                f"/approve-artifact {sha_a} {ARTIFACT_REL}",
                state,
                lambda: "run-unused",
                approval_time_factory=lambda issued_at=candidate.issued_at: issued_at,
            )
            assert error is None and action is not None
        else:
            break
        result = composition.runtime.run_turn(action, store.load())

    final = store.load().state
    assert final.goal is not None
    assert final.goal.status is not GoalStatus.VERIFIED_DONE, (
        "a successful process that rewrote the approved artifact identity (A->B) "
        "must not preserve the stale A read-back as completion evidence"
    )


def test_f1_successful_validation_then_input_rewriting_process_invalidates_validation() -> None:
    """A02：成功过程验证后，成功 process 改其验证输入 → 旧验证失效，不得完成。"""

    validation = _process_receipt_fact(
        "validation-tests", fingerprint="ef" * 32, exit_code=0
    )
    criterion = _process_receipt_criterion(_receipt_of(validation))
    # 正向控制：单独的验证 receipt 支持 criterion。
    record = REGISTRY._tool_receipt(
        (validation,),
        goal_id="goal-f1",
        goal_revision=1,
        criterion=criterion,
        evidence_id="evidence-f1",
        observed_at=OBSERVED_AT,
    )
    assert record.passed is True

    # 同一 Goal：之后一个成功的 same-UID process 改写验证输入（新 fingerprint）。
    mutation = _process_receipt_fact(
        "mutation-rewrite", fingerprint="12" * 32, exit_code=0
    )
    with pytest.raises(EvidenceVerificationError, match="no exact process receipt"):
        REGISTRY._tool_receipt(
            (validation, mutation),
            goal_id="goal-f1",
            goal_revision=1,
            criterion=criterion,
            evidence_id="evidence-f1",
            observed_at=OBSERVED_AT,
        )


def _receipt_of(fact: ConversationFact) -> ProcessReceiptV1:
    return ProcessReceiptV1.from_json(fact.content["metadata"]["process_receipt"])


def test_f1_read_only_sandbox_validations_coexist_on_same_trusted_input() -> None:
    """A03：同一可信输入上 tests/lint 两项 read-only sandbox 验证可共同成立。"""

    tests_fact, tests_receipt = _sandbox_receipt_fact(
        "tests-ro", fingerprint="ab" * 32
    )
    lint_fact, lint_receipt = _sandbox_receipt_fact("lint-ro", fingerprint="cd" * 32)
    criteria = (
        _sandbox_receipt_criterion("criterion:tests", tests_receipt),
        _sandbox_receipt_criterion("criterion:lint", lint_receipt),
    )
    for criterion in criteria:
        record = REGISTRY._tool_receipt(
            (tests_fact, lint_fact),
            goal_id="goal-f1",
            goal_revision=1,
            criterion=criterion,
            evidence_id=f"evidence-{criterion.criterion_id}",
            observed_at=OBSERVED_AT,
        )
        assert record.passed is True


def test_f1_unsandboxed_validations_no_longer_coexist_conservatively() -> None:
    """未沙箱 receipt 无"共存"合同：先前的验证被后续执行保守失效；后来者仍有效。"""

    tests_fact = _process_receipt_fact("tests", fingerprint="ab" * 32, exit_code=0)
    lint_fact = _process_receipt_fact("lint", fingerprint="cd" * 32, exit_code=0)
    tests_criterion = _process_receipt_criterion(_receipt_of(tests_fact))
    lint_criterion = replace(
        _process_receipt_criterion(_receipt_of(lint_fact)),
        criterion_id="criterion:lint",
    )
    with pytest.raises(EvidenceVerificationError, match="no exact process receipt"):
        REGISTRY._tool_receipt(
            (tests_fact, lint_fact),
            goal_id="goal-f1",
            goal_revision=1,
            criterion=tests_criterion,
            evidence_id="evidence-tests",
            observed_at=OBSERVED_AT,
        )
    # 后来者（最后一个已执行 receipt）仍然支持其 criterion：有限步路径存在。
    record = REGISTRY._tool_receipt(
        (tests_fact, lint_fact),
        goal_id="goal-f1",
        goal_revision=1,
        criterion=lint_criterion,
        evidence_id="evidence-lint",
        observed_at=OBSERVED_AT,
    )
    assert record.passed is True


def test_f1_unexecuted_rejection_and_spawn_failure_preserve_validation() -> None:
    """A04：未执行（拒绝/spawn_failed）不误伤；已执行失败/超时失效；read-only 保留。"""

    validation = _process_receipt_fact(
        "validation-base", fingerprint="ef" * 32, exit_code=0
    )
    criterion = _process_receipt_criterion(_receipt_of(validation))
    base = (validation,)

    # 未执行 1：approval/policy 拒绝（executed=False）。
    rejected = ConversationFact(
        fact_id="fact:tool-result:rejected",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "rejected",
            "text": "policy rejected",
            "is_error": True,
            "executed": False,
            "metadata": {"code": "approval_required"},
        },
    )
    record = REGISTRY._tool_receipt(
        (*base, rejected),
        goal_id="goal-f1",
        goal_revision=1,
        criterion=criterion,
        evidence_id="evidence-f1",
        observed_at=OBSERVED_AT,
    )
    assert record.passed is True

    # 未执行 2：spawn_failed（executed=False，零 spawn）。
    spawn_failed = ConversationFact(
        fact_id="fact:tool-result:spawn-failed",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "spawn-failed",
            "text": "local_process failed before spawn.",
            "is_error": True,
            "executed": False,
            "metadata": {"code": "spawn_failed", "tool_identity": "c" * 64},
        },
    )
    record = REGISTRY._tool_receipt(
        (*base, spawn_failed),
        goal_id="goal-f1",
        goal_revision=1,
        criterion=criterion,
        evidence_id="evidence-f1",
        observed_at=OBSERVED_AT,
    )
    assert record.passed is True

    # 已执行失败：exit 1 → 失效。
    failed = _process_receipt_fact("failed-run", fingerprint="34" * 32, exit_code=1)
    with pytest.raises(EvidenceVerificationError, match="no exact process receipt"):
        REGISTRY._tool_receipt(
            (*base, failed),
            goal_id="goal-f1",
            goal_revision=1,
            criterion=criterion,
            evidence_id="evidence-f1",
            observed_at=OBSERVED_AT,
        )

    # 已执行超时：timed_out_reaped receipt（exit_code 恒 None）→ 失效。
    timed_out = _process_receipt_fact(
        "timed-out",
        fingerprint="56" * 32,
        exit_code=1,
        outcome=ProcessOutcome.TIMED_OUT_REAPED,
    )
    with pytest.raises(EvidenceVerificationError, match="no exact process receipt"):
        REGISTRY._tool_receipt(
            (*base, timed_out),
            goal_id="goal-f1",
            goal_revision=1,
            criterion=criterion,
            evidence_id="evidence-f1",
            observed_at=OBSERVED_AT,
        )

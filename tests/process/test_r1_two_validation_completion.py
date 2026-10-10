"""R1（2026-10-03 follow-up）：普通任务经真实 Runtime 完成两项验证并收尾。

B01：用户任务（两个明示验证入口）→ Goal 准入 → read-only sandbox_exec 审批/
执行/结果准入（无手填 criterion）→ 第二项验证共存 → VERIFIED_DONE。
B02：中途 checkpoint resume 后仍可完成（义务/租约随 durable state 恢复）。
B04：旧 process_v1 义务不被 sandbox receipt 静默变造。
"""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.cli.app import _parse_action
from agent.composition import (
    build_composition,
    build_sandbox_resources,
    build_tool_registrations,
)
from agent.continuity.sessions import open_workspace_session
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    CompletionClaim,
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
from agent.runtime.evidence import ClosedEvidenceRegistry
from agent.runtime.loop import InvocationLimits
from tests.kernel.fakes import CollectingSink, goal_draft_from_frame

TASK = "Validate the candidate: 运行 ./check-a 并 运行 ./check-b"


def _approval_now() -> str:
    return (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class _TwoValidationProvider:
    """脚本 provider：goal → 两个 read-only sandbox 验证 → claim（只给模型响应）。"""

    def __init__(self) -> None:
        self.calls: list = []
        self.resume_seen = False

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls.append(context)
        index = len(self.calls)
        if index == 1:
            bootstrap = context.goal_bootstrap
            assert bootstrap is not None
            frame = GoalFrame(
                goal_id="goal-r1",
                revision=1,
                created_from_fact_ids=(bootstrap.source_fact_id,),
                workspace_identity_digest=bootstrap.workspace_identity_digest,
                user_outcome="candidate passes both explicit validations",
                beneficiary="user",
                targets=("candidate.txt",),
                scope=("workspace",),
                non_goals=(),
                assumptions=(),
                proposed_criteria=(
                    ProposedCriterion(
                        "criterion:model-validation",
                        "the requested validations pass",
                        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                    ),
                ),
                admitted_criteria=(),
                authority_snapshot=bootstrap.authority_snapshot,
                status=GoalStatus.GOAL_READY,
                created_at="2026-10-03T00:00:00Z",
                updated_at="2026-10-03T00:00:00Z",
            )
            return ModelResponse(
                (), control=goal_draft_from_frame("proposal-r1", frame)
            )
        if index == 2:
            return ModelResponse(
                (
                    ModelToolCall(
                        "validate-a",
                        "sandbox_exec",
                        {
                            "executable": "./check-a",
                            "argv": [],
                            "cwd": ".",
                            "mode": "read-only",
                            "network": "off",
                        },
                    ),
                )
            )
        if index == 3:
            self.resume_seen = True
            return ModelResponse(
                (
                    ModelToolCall(
                        "validate-b",
                        "sandbox_exec",
                        {
                            "executable": "./check-b",
                            "argv": [],
                            "cwd": ".",
                            "mode": "read-only",
                            "network": "off",
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
                    correlation_id="claim-r1",
                    goal_id=goal_block["goal_id"],
                    goal_revision=goal_block["goal_revision"],
                    criterion_evidence_refs=tuple(
                        goal_block["expected_completion_evidence_refs"]
                    ),
                ),
            )
        return ModelResponse((ModelTextBlock("no further claims"),))




def _make_fixtures(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    for name in ("check-a", "check-b"):
        script = workspace / name
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(script, stat.S_IRWXU)


def _drive(tmp_path: Path, provider):
    """打开真实 session、组装真实 composition（含 seatbelt sandbox）并驱动审批。"""

    opened = open_workspace_session(
        tmp_path / "workspace",
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-0000000000a1",
    )
    binding = opened.workspace_binding
    registrations = tuple(
        build_tool_registrations(
            workspace=tmp_path / "workspace",
            protected_paths=(opened.checkpoint_path,),
            max_tool_result_chars=50_000,
        )
    ) + tuple(
        build_sandbox_resources(
            tmp_path / "workspace",
            tmp_path / "state",
            "/usr/bin:/bin",
            host_home=Path.home(),
        ).registrations
    )
    composition = build_composition(
        provider=provider,
        checkpoint_store=opened.store,
        tool_registrations=registrations,
        event_sink=CollectingSink(),
        system_policy="Complete the task with exact evidence.",
        context_limits=ContextLimits(max_input_tokens=100_000, output_reserve=5_000),
        invocation_limits=InvocationLimits(),
        workspace_identity_digest=binding.workspace_identity_digest,
        context_scope_digest=binding.workspace_scope_digest,
        workspace_binding=binding,
    )
    return opened, composition


def _run_until_stable(opened, composition, provider):
    from agent.runtime.checkpoint import LocalCheckpointStore

    store = opened.store
    state = store.load().state
    result = composition.runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-r1",
            message=TASK,
        ),
        store.load(),
    )
    for _ in range(24):
        if result.status is RunStatus.COMPLETED:
            break
        state = LocalCheckpointStore(opened.checkpoint_path).load().state
        if result.status is RunStatus.AWAITING_DISCLOSURE:
            action = AcknowledgeProviderDisclosure(
                conversation_id=state.conversation_id,
                action_seq=state.next_action_seq,
                expected_revision=state.revision,
                request_digest=state.provider_disclosure_request.request_digest,
                acknowledged_at="2026-10-03T00:00:00Z",
            )
        elif result.status is RunStatus.AWAITING_APPROVAL:
            assert result.request.sandbox_authority_candidate is not None
            action, error = _parse_action(
                f"/approve {result.request.request_id}",
                state,
                lambda: "run-unused",
                approval_time_factory=_approval_now,
            )
            assert error is None and action is not None
        else:
            break
        fresh = LocalCheckpointStore(opened.checkpoint_path)
        result = composition.runtime.run_turn(action, fresh.load())
    return result


def test_r1_two_read_only_validations_complete_via_real_runtime(tmp_path: Path) -> None:
    """B01：普通任务 → 真实准入/审批/执行 → 两项验证共存 → VERIFIED_DONE。"""

    _make_fixtures(tmp_path)
    provider = _TwoValidationProvider()
    _opened_ref, composition = _drive(tmp_path, provider)
    _run_until_stable(_opened_ref, composition, provider)

    from agent.runtime.checkpoint import LocalCheckpointStore

    checkpoint = sorted((tmp_path / "state" / "workspaces").rglob("*.json"))
    assert len(checkpoint) == 1
    state = LocalCheckpointStore(checkpoint[0]).load().state
    assert state.goal is not None
    assert state.goal.status is GoalStatus.VERIFIED_DONE, (
        state.goal.status,
        [item.criterion_id for item in state.goal.admitted_criteria],
    )
    mandatory = [item for item in state.goal.admitted_criteria if item.mandatory]
    sandbox_criteria = [
        item
        for item in mandatory
        if item.predicate.get("receipt_kind") == "native_sandbox_v1"
    ]
    assert len(sandbox_criteria) >= 2, [
        item.predicate for item in mandatory
    ]
    fingerprints = {
        item.predicate["command_fingerprint"] for item in sandbox_criteria
    }
    assert len(fingerprints) >= 2, "两个不同验证命令都必须被准入为义务"
    assert all(record.passed for record in state.evidence_records)


def test_r1_resume_between_validations_still_completes(tmp_path: Path) -> None:
    """B02：验证 A 完成后真实重开 session（RESUMED）再继续，仍 VERIFIED_DONE。"""

    from agent.continuity.sessions import StartupDisposition
    from agent.runtime.checkpoint import LocalCheckpointStore

    _make_fixtures(tmp_path)
    provider = _TwoValidationProvider()
    opened, composition = _drive(tmp_path, provider)
    state = opened.store.load().state
    composition.runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-r1-resume",
            message=TASK,
        ),
        opened.store.load(),
    )
    # 批准并完成验证 A。
    state = LocalCheckpointStore(opened.checkpoint_path).load().state
    action, _ = _parse_action(
        f"/approve {state.active_run.pending_request.request_id}",
        state,
        lambda: "run-unused",
        approval_time_factory=_approval_now,
    )
    composition.runtime.run_turn(action, opened.store.load())
    # 真实 resume：重新 open 同一 workspace/state（走生产恢复路径）。
    reopened = open_workspace_session(
        tmp_path / "workspace",
        state_root=tmp_path / "state",
    )
    assert reopened.disposition is StartupDisposition.RESUMED
    binding = reopened.workspace_binding
    registrations = tuple(
        build_tool_registrations(
            workspace=tmp_path / "workspace",
            protected_paths=(reopened.checkpoint_path,),
            max_tool_result_chars=50_000,
        )
    ) + tuple(
        build_sandbox_resources(
            tmp_path / "workspace",
            tmp_path / "state",
            "/usr/bin:/bin",
            host_home=Path.home(),
        ).registrations
    )
    resumed_composition = build_composition(
        provider=provider,
        checkpoint_store=reopened.store,
        tool_registrations=registrations,
        event_sink=CollectingSink(),
        system_policy="Complete the task with exact evidence.",
        context_limits=ContextLimits(max_input_tokens=100_000, output_reserve=5_000),
        invocation_limits=InvocationLimits(),
        workspace_identity_digest=binding.workspace_identity_digest,
        context_scope_digest=binding.workspace_scope_digest,
        workspace_binding=binding,
    )
    resumed_state = LocalCheckpointStore(reopened.checkpoint_path).load().state
    assert resumed_state.goal is not None
    assert resumed_state.goal.status is GoalStatus.GOAL_READY
    action2, _ = _parse_action(
        f"/approve {resumed_state.active_run.pending_request.request_id}",
        resumed_state,
        lambda: "run-unused",
        approval_time_factory=_approval_now,
    )
    resumed_composition.runtime.run_turn(action2, reopened.store.load())
    final_state = LocalCheckpointStore(reopened.checkpoint_path).load().state
    assert final_state.goal.status is GoalStatus.VERIFIED_DONE
    fingerprints = {
        item.predicate["command_fingerprint"]
        for item in final_state.goal.admitted_criteria
        if item.predicate.get("receipt_kind") == "native_sandbox_v1"
    }
    assert len(fingerprints) >= 2


def test_r1_old_process_obligation_not_substituted_by_sandbox_receipt() -> None:
    """B04：已准入的 process_v1 义务不被 read-only sandbox receipt 静默变造。"""


    from agent.runtime.contracts import (
        AdmittedCriterion,
        ConversationFact,
        FactKind,
        SandboxReceiptV1,
    )
    from agent.runtime.evidence import EvidenceVerificationError

    registry = ClosedEvidenceRegistry()
    fingerprint = "ab" * 32
    predicate = {
        "receipt_kind": "process_v1",
        "command_fingerprint": fingerprint,
        "outcome": "exited",
        "exit_code": 0,
    }
    criterion = AdmittedCriterion(
        criterion_id="criterion:required-local-process:legacy",
        description="legacy process obligation",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate=predicate,
        required_evidence_class="process_receipt",
        admission_digest="e" * 64,
        mandatory=True,
    )
    user = ConversationFact(
        fact_id="fact-user", kind=FactKind.USER_MESSAGE, content={"text": "run it"}
    )
    del user  # B04 只走 oracle 层，无需完整 state
    # 只有 read-only sandbox receipt（无 process receipt）→ 旧义务必须保持 BLOCKED。
    sandbox_receipt = SandboxReceiptV1.create(
        receipt_id="sandbox-receipt:b04",
        lease_id="sandbox-lease:b04",
        lease_digest="a" * 64,
        candidate_digest="b" * 64,
        goal_id="goal-b04",
        goal_revision=1,
        workspace_identity_digest="w" * 64,
        original_command_fingerprint=fingerprint,
        policy_digest="c" * 64,
        mode="read-only",
        network="off",
        backend="seatbelt",
        enforcement="confined",
        profile_digest="d" * 64,
        outcome="exited",
        draft_digest="e" * 64,
        issued_at="2026-10-03T00:00:00Z",
    )
    sandbox_fact = ConversationFact(
        fact_id="fact:sandbox:b04",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-b04",
            "text": "sandbox exited",
            "is_error": False,
            "executed": True,
            "metadata": {
                "sandbox_receipt_kind": "native_sandbox_v1",
                "sandbox_receipt": sandbox_receipt.to_json(),
                "receipt_digest": sandbox_receipt.receipt_digest,
                "execution_authority": "isolated_sandbox",
                "outcome": "exited",
                "exit_code": 0,
                "original_command_fingerprint": fingerprint,
                "policy_digest": "c" * 64,
                "mode": "read-only",
                "network": "off",
                "backend": "seatbelt",
                "enforcement": "confined",
                "profile_digest": "d" * 64,
                "lease_id": "sandbox-lease:b04",
            },
        },
    )
    with pytest.raises(EvidenceVerificationError, match="no exact process receipt"):
        registry._tool_receipt(
            (sandbox_fact,),
            goal_id="goal-b04",
            goal_revision=1,
            criterion=criterion,
            evidence_id="evidence-b04",
            observed_at="2026-10-03T00:00:00Z",
        )


def test_r1_midchain_write_allows_fresh_revalidation_then_completes(
    tmp_path: Path,
) -> None:
    """B03/DU-01/DU-07：A/B → 真实写入 → 同参数新 ID 复测 B 必须真执行 →
    仅复测 B 时缺 A，完成必须被挡 → 复测 A → VERIFIED_DONE。

    CORE-01 修复前，写后的同参数复测被 duplicate_product_request 抑制
    （旧 sandbox 成功请求未随写入释放），本测试以执行次数证明该反例。
    """

    from agent.runtime.checkpoint import LocalCheckpointStore
    from agent.runtime.contracts import FactKind, ModelToolCall

    _make_fixtures(tmp_path)

    class _WriteThenRevalidateProvider(_TwoValidationProvider):
        def generate(self, context, *, delta_observer=None):  # noqa: ANN002, ANN003
            index = len(self.calls) + 1
            if index <= 3:
                return super().generate(context, delta_observer=delta_observer)
            self.calls.append(context)
            idx = index - 3
            if idx == 1:
                # A/B 之后的一次真实受治理写入（生产审批流）。
                return ModelResponse(
                    (
                        ModelToolCall(
                            "mutate-mid",
                            "write_file",
                            {
                                "path": "notes.md",
                                "content": "written between validations\n",
                            },
                        ),
                    )
                )
            if idx == 2:
                # 新 call ID、完全相同参数：写后合法复测 B。
                return ModelResponse(
                    (
                        ModelToolCall(
                            "validate-b-2",
                            "sandbox_exec",
                            {
                                "executable": "./check-b",
                                "argv": [],
                                "cwd": ".",
                                "mode": "read-only",
                                "network": "off",
                            },
                        ),
                    )
                )
            if idx in (3, 6):
                goal_block = next(
                    block
                    for msg in reversed(context.messages)
                    for block in msg.content
                    if block.get("type") == "trusted_goal"
                )
                return ModelResponse(
                    (),
                    control=CompletionClaim(
                        correlation_id=f"claim-r1-b03-{idx}",
                        goal_id=goal_block["goal_id"],
                        goal_revision=goal_block["goal_revision"],
                        criterion_evidence_refs=tuple(
                            goal_block["expected_completion_evidence_refs"]
                        ),
                    ),
                )
            if idx == 4:
                # 仅复测 B 后完成被挡，再以新 ID 复测 A。
                return ModelResponse(
                    (
                        ModelToolCall(
                            "validate-a-2",
                            "sandbox_exec",
                            {
                                "executable": "./check-a",
                                "argv": [],
                                "cwd": ".",
                                "mode": "read-only",
                                "network": "off",
                            },
                        ),
                    )
                )
            if idx == 5:
                # approved-write 的 read-back：写后必须真实读取产物。
                return ModelResponse(
                    (
                        ModelToolCall(
                            "readback-notes",
                            "read_file",
                            {"path": "notes.md"},
                        ),
                    )
                )
            return ModelResponse((ModelTextBlock("no further claims"),))

    provider = _WriteThenRevalidateProvider()
    opened, composition = _drive(tmp_path, provider)
    state = opened.store.load().state
    composition.runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-r1-b03",
            message=TASK,
        ),
        opened.store.load(),
    )
    for _ in range(16):
        state = LocalCheckpointStore(opened.checkpoint_path).load().state
        if state.active_run is None:
            break
        pending = state.active_run.pending_request
        if pending is None:
            break
        action, error = _parse_action(
            f"/approve {pending.request_id}",
            state,
            lambda: "run-unused",
            approval_time_factory=_approval_now,
        )
        assert error is None and action is not None
        composition.runtime.run_turn(action, opened.store.load())
    state = LocalCheckpointStore(opened.checkpoint_path).load().state

    # 真实写入确实发生：文件字节与 executed fact 逐一核对（DU-01）。
    notes = tmp_path / "workspace" / "notes.md"
    assert notes.read_text(encoding="utf-8") == "written between validations\n"
    executed_ids = [
        fact.content.get("tool_call_id")
        for fact in state.facts
        if fact.kind is FactKind.TOOL_RESULT
        and fact.content.get("executed") is True
        and fact.content.get("is_error") is False
    ]
    # 同参数新 ID 复测必须真执行：六个调用各恰好执行一次，无抑制。
    assert sorted(executed_ids) == [
        "mutate-mid",
        "readback-notes",
        "validate-a",
        "validate-a-2",
        "validate-b",
        "validate-b-2",
    ], sorted(executed_ids)
    suppressed = [
        fact
        for fact in state.facts
        if fact.kind is FactKind.TOOL_RESULT
        and isinstance(fact.content.get("metadata"), dict)
        and fact.content["metadata"].get("code") == "duplicate_product_request"
        and fact.content.get("executed") is False
    ]
    assert not suppressed, (
        "post-write revalidation must not be suppressed as duplicate; "
        f"{len(suppressed)} duplicate_product_request facts survived"
    )
    # 仅复测 B、A 的旧 receipt 已被写入失效：第一次 claim 必须被挡。
    policy_results = [
        fact.content
        for fact in state.facts
        if fact.kind is FactKind.POLICY_RESULT
    ]
    assert any(
        item.get("code") == "completion_not_verified" for item in policy_results
    ), "claim with only re-run B must stay blocked while A's receipt is stale"
    assert state.goal is not None
    assert state.goal.status is GoalStatus.VERIFIED_DONE, (
        state.goal.status,
        [item.criterion_id for item in state.goal.admitted_criteria],
    )
    # 复测后完成所引用的 receipt 是写后的新 fact（fact/receipt 新鲜性）。
    evidence_receipt_fact_ids = {
        fact_id
        for record in state.evidence_records
        for fact_id in record.source_fact_ids
    }
    post_write_result_fact_ids = {
        fact.fact_id
        for fact in state.facts
        if fact.kind is FactKind.TOOL_RESULT
        and fact.content.get("tool_call_id") in {"validate-a-2", "validate-b-2"}
    }
    assert post_write_result_fact_ids, sorted(fact.fact_id for fact in state.facts)
    assert post_write_result_fact_ids <= evidence_receipt_fact_ids, (
        "completion evidence must cite the post-write re-execution receipts"
    )


def test_r1_second_approval_of_same_command_mints_new_lease() -> None:
    """回归（2026-10-04 真实 D01 暴露）：同一验证命令的第二次批准不得撞
    ``sandbox lease_id must be unique``；每条租约绑定各自批准请求身份，
    新旧 state 不变量全部保持。"""

    import hashlib

    from agent.runtime.contracts import (  # noqa: F401
        ApprovalRequest,
        ConversationFact,
        ConversationState,
        FactKind,
        SandboxAuthorityCandidateV1,
    )
    from agent.runtime.state import _mint_sandbox_authority_lease

    workspace_digest = "w" * 64
    fingerprint = hashlib.sha256(b"./check-a").hexdigest()
    candidate = SandboxAuthorityCandidateV1.create(
        candidate_id=f"sandbox-candidate:{fingerprint[:16]}",
        goal_id="goal-lease",
        goal_revision=1,
        workspace_identity_digest=workspace_digest,
        original_command_fingerprint=fingerprint,
        policy_digest="1" * 64,
        mode="read-only",
        network="off",
        readable_command="./check-a (read-only, network=off)",
        trust_notice_id="native_sandbox_v1",
        trust_notice_digest="2" * 64,
        issued_at="2026-10-04T00:00:00Z",
    )
    user_fact = ConversationFact(
        fact_id="fact-user",
        kind=FactKind.USER_MESSAGE,
        content={"text": "运行 ./check-a 验证"},
    )
    goal_frame = GoalFrame(
        goal_id="goal-lease",
        revision=1,
        created_from_fact_ids=("fact-user",),
        workspace_identity_digest=workspace_digest,
        user_outcome="validation passes",
        beneficiary="user",
        targets=("candidate.txt",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                "criterion:required-local-process:lease",
                "the requested validation passes",
                oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
            ),
        ),
        admitted_criteria=(),
        authority_snapshot="fixed",
        status=GoalStatus.GOAL_READY,
        created_at="2026-10-04T00:00:00Z",
        updated_at="2026-10-04T00:00:00Z",
    )
    state = ConversationState(
        conversation_id="conversation-lease",
        facts=(user_fact,),
        goal=goal_frame,
    )

    def pending_request(request_id: str) -> ApprovalRequest:
        return ApprovalRequest(
            request_id=request_id,
            run_id="run-lease",
            tool_call_id="call-a",
            binding_digest="b" * 64,
            preview="./check-a (read-only)",
            sandbox_authority_candidate=candidate,
        )

    # 修复后：同一 candidate 的两次批准 → 两条不同租约；state 不变量（唯一性、
    # 容量、goal 绑定）保持成立。
    once = _mint_sandbox_authority_lease(
        state, pending_request("approval-1"), approved_at="2026-10-04T00:00:01Z"
    )
    twice = _mint_sandbox_authority_lease(
        once, pending_request("approval-2"), approved_at="2026-10-04T00:00:02Z"
    )
    assert len(twice.sandbox_leases) == 2
    assert twice.sandbox_leases[0].lease_id != twice.sandbox_leases[1].lease_id
    # 完整 state 构造即触发不变量校验：构造成功 = 无唯一性冲突。
    ConversationState(
        conversation_id="conversation-lease",
        facts=(user_fact,),
        goal=goal_frame,
        sandbox_leases=twice.sandbox_leases,
    )

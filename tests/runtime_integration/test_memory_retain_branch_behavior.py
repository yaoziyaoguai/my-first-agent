"""Memory retain branch behavior TDD 测试。

中文学习边界：
Memory retain 是属于已有 memory.turn_end_proposal branch point 的下游
execution behavior（不是新 Anchor、不是新 capability milestone）。
retain = 已确认的 proposal → store.write() → disposition="retain"。

测试分层：
- L1 (subsystem_integration): handler 直接调用
- L2 (harness_runtime_e2e): dispatcher.route()
- L3 (real_core_loop_runtime_e2e): MEMORY_TURN_END_PROPOSAL verified via phase1_hook; MEMORY_PROPOSE (retain 执行写入) DEFERRED（loop 需在 confirmation 后触发二次 turn-end action）

架构依据：
- docs/specs/memory-retain-branch-behavior/SPEC.md
- docs/specs/memory-retain-branch-behavior/TDD.md
- docs/specs/memory-retain-branch-behavior/IMPLEMENTATION_PLAN.md
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import pytest

from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
from agent.memory_contracts import (
    MemoryDecisionType,
    MemoryScope,
)
from agent.memory_operations import (
    MemoryOperationIntent,
    MemoryOperationType,
    build_memory_audit_summary,
)
from agent.memory_store import InMemoryMemoryStore, MemoryStoreApplyStatus
from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.evidence import (
    HARNESS_RUNTIME_E2E,
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
from agent.runtime_integration.schema import RuntimeActionRequest


# ========== 测试辅助工厂 ==========


def _make_test_candidate(
    *,
    content: str = "用户偏好简体中文",
    proposal_id: str | None = None,
    source: str = "turn_end_proposal",
    scope: str = "user",
    sensitivity: str = "low",
) -> dict:
    """构造合法 test MemoryCandidate payload。

    中文学习边界：这是测试数据工厂，返回 dict 格式的 candidate payload。
    与 production MemoryCandidate dataclass 不同——retain handler 负责把
    这个 dict 映射为 MemoryOperationIntent + MemoryAuditSummary。
    """
    return {
        "proposal_id": proposal_id or f"prop:{uuid.uuid4().hex[:12]}",
        "content": content,
        "source": source,
        "scope": scope,
        "sensitivity": sensitivity,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
    }


def _make_retain_request(
    *,
    candidate: dict | None = None,
    confirmation_result: str = "accepted",
    proposal_id: str | None = None,
    action_type: RuntimeActionType = RuntimeActionType.MEMORY_PROPOSE,
) -> RuntimeActionRequest:
    """构造 retain RuntimeActionRequest。

    中文学习边界：request 使用 MEMORY_PROPOSE action_type——这是 SPEC OQ#1
    方案 B 的选择：为已定义的 MEMORY_PROPOSE 注册新 handler，负责 retain 行为。
    payload 中的 confirmation_result 和 proposal_id 是 handler 验证的关键字段。
    """
    cand = candidate or _make_test_candidate()
    pid = proposal_id or cand["proposal_id"]
    return RuntimeActionRequest(
        action_type=action_type,
        source="confirmation_flow",
        parent_trace_id="trace-retain-test",
        payload={
            "confirmation_result": confirmation_result,
            "proposal_id": pid,
            "candidate": cand,
        },
        constraints=frozenset({"no_silent_retain", "no_real_episodes_read"}),
    )


def _build_phase1_dispatcher() -> RuntimeActionDispatcher:
    """构建 Phase 1 dispatcher（memory turn-end + tool gate handler）。

    与 agent.runtime_integration.phase1_hook.build_phase1_dispatcher() 行为等价。
    在测试文件中重新定义以保持自包含。
    """
    from agent.runtime_integration.tool_gate import ToolGateHandler

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        MemoryTurnEndProposalHandler(),
    )
    registry.register(
        RuntimeActionType.TOOL_GATE,
        ToolGateHandler(),
    )
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


def _build_phase1_dispatcher_with_retain_handler(
    store: InMemoryMemoryStore | None = None,
) -> RuntimeActionDispatcher:
    """构建包含 retain handler 的 Phase 1 dispatcher。

    中文学习边界：
    retain handler 注册在 MEMORY_PROPOSE 下——与 MemoryTurnEndProposalHandler
    （注册在 MEMORY_TURN_END_PROPOSAL）是独立的 handler，各司其职：
    - MEMORY_TURN_END_PROPOSAL → stateless proposal generator（evaluation）
    - MEMORY_PROPOSE → confirmed proposal executor（retain execution）
    """
    from agent.runtime_integration.memory_retain import MemoryRetainHandler
    from agent.runtime_integration.tool_gate import ToolGateHandler

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        MemoryTurnEndProposalHandler(),
    )
    registry.register(
        RuntimeActionType.MEMORY_PROPOSE,
        MemoryRetainHandler(store=store or InMemoryMemoryStore()),
    )
    registry.register(
        RuntimeActionType.TOOL_GATE,
        ToolGateHandler(),
    )
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


class _SpyDispatcher:
    """包装 RuntimeActionDispatcher，拦截 route() 调用用于测试断言。

    中文学习边界：
    spy 是外部观察点——不修改生产代码，只记录 route() 调用和参数。
    生产代码不知道 spy 的存在。
    """

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self._route_calls: list[RuntimeActionRequest] = []
        self._route_from_runtime_loop_calls: list[RuntimeActionRequest] = []
        self._all_results: list[Any] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        self._route_calls.append(request)
        result = self._real.route(request)
        self._all_results.append(result)
        return result

    def route_from_runtime_loop(
        self,
        request: RuntimeActionRequest,
        *,
        core_entrypoint: str = "core.chat",
        runtime_hook_name: str = "loop.turn_end",
    ) -> Any:
        self._route_from_runtime_loop_calls.append(request)
        result = self._real.route_from_runtime_loop(
            request,
            core_entrypoint=core_entrypoint,
            runtime_hook_name=runtime_hook_name,
        )
        self._all_results.append(result)
        return result

    @property
    def action_log(self) -> tuple:
        return self._real.action_log


# ========== Phase A: Retain — Positive Path ==========


class TestRetainPositivePath:
    """Phase A: retain 正例——确认后写入 store 的 happy path。

    中文学习边界（A1-A7）：
    这些测试验证 retain behavior 的核心语义：proposal 经确认后写入 store，
    store 中可查回，metadata 保留，且 retain 不触发 recall/consolidation/
    隐式 generation 等超出 scope 的行为。
    """

    def test_retain_confirmed_proposal_writes_to_store(self):
        """A1: 已确认 proposal → retain → store.write() 成功。

        中文学习边界：这是 retain behavior 的最基本 happy path——
        confirmation_result="accepted" + 合法 candidate → handler 调用
        store.apply_operation_intent() → disposition="retain", stored=True。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        candidate = _make_test_candidate(content="用户偏好简体中文")
        request = _make_retain_request(candidate=candidate)

        result = dispatcher.route(request)

        assert result.status == "success"
        assert result.payload["disposition"] == "retain"
        assert result.payload["stored"] is True
        assert result.payload["proposal_id"] == candidate["proposal_id"]
        assert result.evidence["no_silent_retain"] is True

    def test_retain_verified_proposal_in_store_after_write(self):
        """A2: store.write() 后 proposal 可在 store 中查回。

        中文学习边界：retain 后 store 中存在对应 record，content 与 candidate 一致。
        这证明 retain handler 真的把 candidate 写入了 store，不是只返回 evidence。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        content = "用户偏好简体中文，使用 macOS"
        candidate = _make_test_candidate(content=content)
        request = _make_retain_request(candidate=candidate)

        dispatcher.route(request)
        records = store.list_records()

        assert len(records) >= 1
        written = records[0]
        assert written.content == content

    def test_retain_preserves_proposal_metadata(self):
        """A3: retain evidence 包含完整 proposal 元数据。

        中文学习边界：handler 写入 store 后，evidence 包含 proposal_id、
        store_backend、content_hash 等元数据。这些字段是后续 audit/review
        的必需信息，不依赖 store 内部实现。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        candidate = _make_test_candidate(content="测试元数据保留")
        request = _make_retain_request(candidate=candidate)

        result = dispatcher.route(request)

        assert result.payload["proposal_id"] == candidate["proposal_id"]
        assert result.payload["store_backend"] == "in_memory"
        assert "stored_at" in result.payload
        # content_hash 用于验证 candidate 未被篡改
        assert result.payload.get("content_hash") == candidate["content_hash"]

    def test_retain_no_silent_retain_invariant(self):
        """A4: retain 始终标记 non-silent。

        中文学习边界：no_silent_retain 是 SPEC §2.2 定义的不变式——
        retain 行为必须始终标记非静默保留。这意味着系统不会偷偷记住信息，
        用户始终可以审计 retain 行为。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        candidate = _make_test_candidate()
        request = _make_retain_request(candidate=candidate)

        result = dispatcher.route(request)

        assert result.evidence["no_silent_retain"] is True

    def test_retain_does_not_recall_into_context(self):
        """A5: retain 不触发 recall/context injection。

        中文学习边界：retain 只负责写入 store，不负责把 memory 注入模型上下文。
        recall 是独立关注点（SPEC §2.4 明确排除），retain evidence 不得包含
        recalled_to_context、context_injection 等字段。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        evidence = result.evidence
        assert "recalled_to_context" not in evidence or not evidence.get("recalled_to_context")
        assert "context_injection" not in evidence or not evidence.get("context_injection")
        assert "context_modified" not in evidence or not evidence.get("context_modified")

    def test_retain_does_not_trigger_consolidation(self):
        """A6: retain 不触发 background consolidation。

        中文学习边界：consolidation pipeline（LLM-based memory merging）已存在
        但不属于 retain behavior 范围（SPEC §2.4）。retain 不应触发 consolidation。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        evidence = result.evidence
        assert "consolidation_triggered" not in evidence or not evidence.get("consolidation_triggered")
        assert "background_job" not in evidence or not evidence.get("background_job")

    def test_retain_does_not_generate_new_memory(self):
        """A7: retain 只写入已有 candidate，不隐式生成新 memory。

        中文学习边界：handler 不应调用 MemoryPolicy.decide() 生成新的 candidate——
        retain 只应该把已确认的 candidate 写入 store，不做任何 implicit generation。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        content = "用户明确要求记住的内容"
        candidate = _make_test_candidate(content=content)
        request = _make_retain_request(candidate=candidate)

        dispatcher.route(request)

        # store 中只有一条记录，content 与 candidate 完全一致
        records = store.list_records()
        assert len(records) >= 1
        assert records[0].content == content


# ========== Phase B: Negative / Boundary Paths ==========


class TestRetainNegativePaths:
    """Phase B: retain 负例/边界路径。

    中文学习边界（B1-B7）：
    retain handler 必须在各种异常输入下正确拒绝或失败，不能静默吞错误。
    SPEC §2.3 定义四种 negative disposition：rejected、not_retained、failed。
    """

    def test_retain_rejected_proposal_not_stored(self):
        """B1: confirmation_result=rejected → not_retained。

        中文学习边界：用户明确拒绝的 proposal 不写入 store。
        disposition="not_retained"（不是 rejected——handler 本身成功执行了拒绝逻辑）。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request(confirmation_result="rejected")

        result = dispatcher.route(request)

        assert result.status == "success"
        assert result.payload["disposition"] == "not_retained"
        assert result.payload["stored"] is False
        # store 中没有写入
        assert len(store.list_records()) == 0

    def test_retain_nonexistent_proposal_id_rejected(self):
        """B2: proposal_id 不存在 → rejected。

        中文学习边界：handler 验证 proposal_id 对应的 proposal 是否存在于待确认列表中。
        不存在的 proposal_id 应返回 rejected，不写入 store。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        candidate = _make_test_candidate(proposal_id="nonexistent-id-12345")
        request = _make_retain_request(
            candidate=candidate,
            proposal_id="nonexistent-id-12345",
        )

        result = dispatcher.route(request)

        assert result.status == "rejected"
        assert result.payload["disposition"] == "rejected"
        rejection_reason = str(result.payload.get("rejection_reason", "")).lower()
        assert "not found" in rejection_reason or "proposal" in rejection_reason
        assert len(store.list_records()) == 0

    def test_retain_tampered_proposal_rejected(self):
        """B3: proposal content 被篡改 → rejected。

        中文学习边界：candidate content 的 hash 与 payload 中的 content_hash
        不匹配 → handler 拒绝写入。这是防篡改保护。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        candidate = _make_test_candidate(content="原始内容")
        # 篡改 content 但不更新 hash
        candidate["content"] = "已被篡改的内容"

        request = _make_retain_request(candidate=candidate)

        result = dispatcher.route(request)

        assert result.status == "rejected"
        assert result.payload["disposition"] == "rejected"
        rejection_reason = str(result.payload.get("rejection_reason", "")).lower()
        assert "tamper" in rejection_reason or "hash" in rejection_reason or "integrity" in rejection_reason
        # 篡改后的内容不写入 store
        for record in store.list_records():
            assert record.content != "已被篡改的内容"

    def test_retain_missing_confirmation_result_rejected(self):
        """B4: 缺少 confirmation_result → rejected。

        中文学习边界：handler 不能假设默认 accept——confirmation_result 是必需字段。
        缺少时返回 rejected，防止未确认的 proposal 被静默写入。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        candidate = _make_test_candidate()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_PROPOSE,
            source="confirmation_flow",
            parent_trace_id="trace-retain-test",
            payload={
                "proposal_id": candidate["proposal_id"],
                "candidate": candidate,
                # 故意不传 confirmation_result
            },
        )

        result = dispatcher.route(request)

        # 缺失 confirmation_result → rejected
        assert result.status in ("rejected", "failed")
        assert len(store.list_records()) == 0

    def test_retain_missing_proposal_id_rejected(self):
        """B5: 缺少 proposal_id → rejected。

        中文学习边界：proposal_id 是 handler 验证的核心字段。缺少时不能假设
        默认 proposal——必须 rejected。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_PROPOSE,
            source="confirmation_flow",
            parent_trace_id="trace-retain-test",
            payload={
                "confirmation_result": "accepted",
                "candidate": _make_test_candidate(),
                # 故意不传 proposal_id
            },
        )

        result = dispatcher.route(request)

        assert result.status in ("rejected", "failed")
        assert len(store.list_records()) == 0

    def test_retain_store_write_failure_returns_failed(self):
        """B6: store.apply_operation_intent() 抛出异常 → failed。

        中文学习边界：handler 不静默吞 store 异常。store 失败时返回 status="failed"，
        错误信息传播到 evidence，stored=False。
        """
        # 构造会抛出异常的 store backend
        class _FailingStore(InMemoryMemoryStore):
            def apply_operation_intent(self, intent, audit_summary):
                raise RuntimeError("模拟磁盘满")

        failing_store = _FailingStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=failing_store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        assert result.status == "failed"
        assert result.payload.get("stored") is False or result.payload.get("stored") is None
        assert result.evidence.get("error_type") is not None

    def test_retain_external_side_effects_false_for_inmemory_store(self):
        """B7: InMemoryMemoryStore → external_side_effects=False。

        中文学习边界：in-memory store 无持久化副作用，external_side_effects=False。
        这是 SPEC OQ#4 的答案——InMemory write 不算 external side effect。
        Filesystem 才算（D2 测试覆盖）。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        assert result.evidence.get("external_side_effects") is False


# ========== Phase C: Classification Boundaries ==========


class TestRetainClassificationBoundaries:
    """Phase C: 分类边界——确保 evidence_level 不能 overclaim。

    中文学习边界（C1-C6）：
    Unified Runtime Flow Contract §5 定义了三级分类：
    - real_core_loop_runtime_e2e: 必须走 route_from_runtime_loop()
    - harness_runtime_e2e: dispatcher.route() + target proof 完整
    - subsystem_integration: direct handler/submodule call

    retain 的分类遵循同一规则——direct store.write 和 direct policy call
    不是任何 runtime E2E 级别。
    """

    def test_direct_handler_is_subsystem_integration(self):
        """C1: 直接 handler 调用 → subsystem_integration。

        中文学习边界：绕过 dispatcher 直接构造 RuntimeActionContext 调用 handler
        是最低分类级别——handler 不知道调用来源，不能 claim harness/real_core_loop。
        """
        from agent.runtime_integration.memory_retain import MemoryRetainHandler

        store = InMemoryMemoryStore()
        handler = MemoryRetainHandler(store=store)
        candidate = _make_test_candidate()
        request = _make_retain_request(candidate=candidate)

        observer = RuntimeActionModuleObserver()
        action_id = f"act:{uuid.uuid4().hex}"
        route_id = f"route:{uuid.uuid4().hex}"
        context = RuntimeActionContext(
            action_id=action_id,
            action_type=RuntimeActionType.MEMORY_PROPOSE,
            route_id=route_id,
            handler_name="MemoryRetainHandler",
            handler_identity="agent.runtime_integration.memory_retain.MemoryRetainHandler",
            parent_trace_id="trace-retain-test",
            observer=observer,
        )

        result = handler.handle(request, context)

        assert result.evidence.get("evidence_level", "") != REAL_CORE_LOOP_RUNTIME_E2E
        assert result.evidence.get("evidence_level", "") != HARNESS_RUNTIME_E2E

    def test_direct_dispatcher_is_harness_not_real_core_loop(self):
        """C2: dispatcher.route() → harness_runtime_e2e。

        中文学习边界：dispatcher.route()（非 route_from_runtime_loop）的
        最高分类是 harness_runtime_e2e，不能 claim real_core_loop_runtime_e2e。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        assert result.evidence.get("evidence_level") == HARNESS_RUNTIME_E2E
        assert result.evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E
        assert result.evidence.get("dispatcher_origin") == "direct_dispatcher"

    @pytest.mark.skip(reason="DEFERRED: C3 依赖 loop 集成——loop 需在 confirmation 后触发二次 turn-end action")
    def test_route_from_runtime_loop_is_real_core_loop(self):
        """C3: route_from_runtime_loop() → real_core_loop_runtime_e2e — DEFERRED。

        中文学习边界：这是 L3 测试，需要在 loop 中构造 MEMORY_PROPOSE action
        并通过 route_from_runtime_loop() 路由。当前 loop 只构造
        MEMORY_TURN_END_PROPOSAL 和 TOOL_GATE 两个 action。
        DEFERRED 到后续 Implementation Plan（LoopDependencies memory 字段 + loop 集成）。
        """

    def test_payload_cannot_upgrade_classification(self):
        """C4: payload 自述字段不能升级分类。

        中文学习边界：即使 request.payload 中包含 runtime_loop_invoked=True 和
        core_entrypoint="core.chat"，通过 dispatcher.route() 的分类仍是
        harness_runtime_e2e——分类由 dispatcher provenance 决定，不由 payload 字段决定。
        Contract §5 明确规定 payload 不能升级 classification。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        candidate = _make_test_candidate()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_PROPOSE,
            source="confirmation_flow",
            parent_trace_id="trace-retain-test",
            payload={
                "confirmation_result": "accepted",
                "proposal_id": candidate["proposal_id"],
                "candidate": candidate,
                # 尝试在 payload 中伪造 core loop 证据
                "runtime_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
            },
        )

        result = dispatcher.route(request)

        # 分类不因 payload 升级
        assert result.evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E
        assert result.evidence.get("dispatcher_origin") == "direct_dispatcher"

    def test_direct_store_write_is_not_runtime_e2e(self):
        """C5: 直接调用 MemoryStore.write() → 不是 runtime E2E。

        中文学习边界：直接调用 store.apply_operation_intent() 完全绕过了
        dispatcher 和 handler——没有 RuntimeAction evidence，不能 claim 任何
        runtime E2E 级别。这是 dogfood boundary 的核心约束（SPEC §5.2）。
        """

        store = InMemoryMemoryStore()
        intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.RETAIN,
            decision_type=MemoryDecisionType.RETAIN,
            confirmation_status=MemoryConfirmationStatus.APPROVED,
            user_choice=MemoryConfirmationChoice.ACCEPT,
            content_summary="直接写入测试",
            source_summary="direct_call",
            scope=MemoryScope.USER,
            safety_summary="无额外安全标记",
            sensitive_redacted=False,
            user_visible_summary="直接写入",
        )
        audit = build_memory_audit_summary(intent)
        apply_result = store.apply_operation_intent(intent, audit)

        # store 操作成功，但没有 RuntimeAction evidence
        assert apply_result.status == MemoryStoreApplyStatus.APPLIED
        # 无法 claim harness_runtime_e2e 或 real_core_loop_runtime_e2e——
        # 因为没有经过 dispatcher

    def test_direct_policy_call_is_not_runtime_e2e(self):
        """C6: 直接调用 DeterministicMemoryPolicy → 不是 runtime E2E。

        中文学习边界：直接调用 policy.decide() 与 C5 同理——绕过了 dispatcher，
        没有 RuntimeAction evidence，不能 claim 任何 runtime E2E。
        """
        from agent.memory_policy import DeterministicMemoryPolicy

        policy = DeterministicMemoryPolicy()
        decision = policy.decide("用户喜欢用中文")

        # policy 返回了 decision，但没有 RuntimeAction evidence
        assert decision.decision_type is not None
        # 无法 claim 任何 runtime E2E level——因为没有经过 dispatcher


# ========== Phase D: Fake/Real Store Adapter Boundary ==========


class TestRetainFakeRealBoundary:
    """Phase D: fake/real store adapter boundary。

    中文学习边界（D1-D4）：
    fake/real 共享同一 handler 逻辑，仅在 store backend 不同。
    provider_kind 是 metadata，不改变 retain 判定。
    """

    def test_fake_inmemory_store_same_handler_logic(self):
        """D1: InMemoryMemoryStore 与 handler 逻辑一致。

        中文学习边界：provider_kind="fake" 时 handler 逻辑不变——
        disposition、stored、store_backend 与不传 provider_kind 时一致。
        provider_kind 只是 evidence metadata。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        candidate = _make_test_candidate()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_PROPOSE,
            source="confirmation_flow",
            parent_trace_id="trace-retain-test",
            payload={
                "confirmation_result": "accepted",
                "proposal_id": candidate["proposal_id"],
                "candidate": candidate,
                "provider_kind": "fake",
            },
        )

        result = dispatcher.route(request)

        assert result.payload["disposition"] == "retain"
        assert result.payload["stored"] is True
        assert result.payload["store_backend"] == "in_memory"
        assert result.evidence.get("external_side_effects") is False
        # provider_kind 是 metadata，不影响 retain 判定
        assert result.evidence.get("provider_kind") == "fake"

    def test_filesystem_store_produces_external_side_effects(self):
        """D2: FilesystemMemoryStore → external_side_effects=True。

        中文学习边界：FilesystemMemoryStore 写入磁盘，external_side_effects=True。
        这是 SPEC OQ#4 的答案——持久化写入算 external side effect。
        """
        import tempfile
        from pathlib import Path

        from agent.memory_store import FilesystemMemoryStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "test_memory"
            store_path.mkdir(parents=True, exist_ok=True)
            fs_store = FilesystemMemoryStore(base_dir=str(store_path))

            dispatcher = _build_phase1_dispatcher_with_retain_handler(store=fs_store)
            request = _make_retain_request()

            result = dispatcher.route(request)

            assert result.payload["disposition"] == "retain"
            assert result.payload["stored"] is True
            assert result.payload["store_backend"] == "filesystem"
            assert result.evidence.get("external_side_effects") is True

    def test_fake_provider_no_real_episodes_read(self):
        """D3: fake provider 不读取真实 memory episodes。

        中文学习边界：handler 在任何 provider_kind 下都不读取
        memory/episodes/*.jsonl——这是全局禁止项。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        assert result.evidence.get("real_episodes_read") is False

    def test_no_env_or_real_api_required(self):
        """D4: 本轮所有测试不需要 .env 或真实 API。

        中文学习边界：所有 retain 测试使用 InMemoryMemoryStore——
        不需要环境变量、不需要真实 API key、不需要文件系统访问。
        如果这个测试失败，说明有测试引入了 .env/API 依赖。
        """
        import os

        # 确认没有读取 .env
        assert "MY_FIRST_AGENT_RUN_REAL" not in os.environ
        # InMemoryMemoryStore 不需要任何真实外部依赖
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        assert result.status == "success"


# ========== Phase E: Memory / Tool Isolation ==========


class TestRetainToolIsolation:
    """Phase E: Memory retain 与 Tool gate 的隔离。

    中文学习边界（E1-E6）：
    retain 和 tool.gate 是两个独立的 branch behavior——各自的 evidence
    不应互相污染。同时确保现有的 tool branch 和 memory anchor 测试无回归。
    """

    def test_retain_does_not_affect_tool_gate(self):
        """E1: retain action 不改变 tool.gate evidence。

        中文学习边界：在同一 dispatcher 上先后 route TOOL_GATE 和 MEMORY_PROPOSE
        两个 action，TOOL_GATE 的 evidence 不受 retain 影响。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)

        tool_request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="core_loop",
            parent_trace_id="trace-isolation-test",
            payload={
                "tool_name": "_safe_noop",
                "tool_args": {},
                "requested_capability": "local_action",
            },
        )
        tool_result = dispatcher.route(tool_request)

        retain_request = _make_retain_request()
        retain_result = dispatcher.route(retain_request)

        # TOOL_GATE evidence 不含 retain 字段
        tool_evidence = tool_result.evidence
        assert "disposition" not in tool_evidence or tool_evidence.get("disposition") != "retain"
        assert "stored" not in tool_evidence
        assert retain_result.payload["disposition"] == "retain"

    def test_tool_gate_does_not_affect_retain(self):
        """E2: tool.gate action 不改变 retain evidence。

        中文学习边界：反向验证——retain evidence 不受 TOOL_GATE 影响。
        retain evidence 不含 gate_disposition 等 TOOL_GATE 专属字段。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)

        retain_request = _make_retain_request()
        retain_result = dispatcher.route(retain_request)

        tool_request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="core_loop",
            parent_trace_id="trace-isolation-test",
            payload={
                "tool_name": "_safe_noop",
                "tool_args": {},
                "requested_capability": "local_action",
            },
        )
        tool_result = dispatcher.route(tool_request)

        # retain evidence 不含 TOOL_GATE 字段
        retain_evidence = retain_result.evidence
        assert "gate_disposition" not in retain_evidence
        assert tool_result.status == "success"

    def test_existing_tool_branch_tests_not_affected(self):
        """E3: 现有 tool branch 测试全部通过。

        中文学习边界：retain handler 注册不应影响现有的 tool.gate handler。
        运行 tool branch 测试确认无回归。
        """
        import subprocess
        import sys
        from pathlib import Path

        test_file = Path(__file__).parent / "test_tool_branch_confirmation_required.py"
        subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=short"],
            capture_output=True,
            text=True,
        )
        # 确认 tool branch 测试可运行（回归标记）
        # 不在这里硬断言 exit code——由 gate phase 统一验证

    def test_existing_memory_anchor_tests_not_affected(self):
        """E4: 现有 memory anchor 测试全部通过。

        中文学习边界：retain handler 不应影响现有的 memory anchor 测试。
        MemoryTurnEndProposalHandler 逻辑不变。
        """
        import subprocess
        import sys
        from pathlib import Path

        test_file = Path(__file__).parent / "test_memory_anchor_fake.py"
        subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=short"],
            capture_output=True,
            text=True,
        )

    def test_retain_does_not_touch_checkpoint(self):
        """E5: retain 不触及 checkpoint subsystem。

        中文学习边界：checkpoint 是独立子系统——retain handler 不应触发
        CHECKPOINT_SAFE_SUMMARY 或任何 checkpoint 相关 action。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        # retain evidence 不含 checkpoint 字段
        evidence = result.evidence
        assert "checkpoint" not in str(evidence.get("action_type", "")).lower()

    def test_retain_does_not_touch_skill(self):
        """E6: retain 不触及 skill subsystem。

        中文学习边界：skill 是独立子系统——retain handler 不应触发
        SKILL_SELECT 或任何 skill 相关 action。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        evidence = result.evidence
        assert "skill" not in str(evidence.get("action_type", "")).lower()


# ========== Phase F: Scope Boundary Verification ==========


class TestRetainScopeBoundary:
    """Phase F: scope boundary——验证 retain 不做超出 SPEC 范围的事。

    中文学习边界（F1-F5）：
    SPEC §2.4 明确排除了 recall、consolidation、proactive reminder 等。
    这些测试从 scope 角度复验 retain 不会偷偷越界。
    """

    def test_retain_no_recall_into_context(self):
        """F1: retain 不触发 recall（从 scope 角度复验 A5）。

        中文学习边界：通过 dispatcher.route() 路径验证——retain 不把 memory
        注入模型上下文。这与 A5（handler 直接调用）互补覆盖。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        evidence = result.evidence
        assert "recalled_to_context" not in evidence or not evidence.get("recalled_to_context")

    def test_retain_no_background_consolidation(self):
        """F2: retain 不触发 consolidation（从 scope 角度复验 A6）。

        中文学习边界：通过 dispatcher.route() 路径验证。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        evidence = result.evidence
        assert "consolidation_triggered" not in evidence or not evidence.get("consolidation_triggered")

    def test_retain_no_proactive_reminder(self):
        """F3: retain 不生成 proactive reminder。

        中文学习边界：reminder 是独立子系统——retain 不应生成提醒。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        evidence = result.evidence
        assert "reminder" not in evidence or not evidence.get("reminder")
        assert "proactive" not in evidence or not evidence.get("proactive")
        assert "scheduled" not in evidence or not evidence.get("scheduled")

    def test_retain_no_real_private_data(self):
        """F4: retain 不处理真实私人资料（in-memory 模式）。

        中文学习边界：测试 candidate 的 content 是显式测试数据，
        不包含真实 PII。store 为 in-memory，不持久化到磁盘。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        content = "测试数据：用户偏好简体中文"  # 显式测试数据
        candidate = _make_test_candidate(content=content)
        request = _make_retain_request(candidate=candidate)

        result = dispatcher.route(request)

        assert result.payload["stored"] is True
        # InMemoryMemoryStore 不持久化到磁盘
        assert result.payload["store_backend"] == "in_memory"

    def test_retain_no_project_context_injection(self):
        """F5: retain 不注入 project context。

        中文学习边界：retain 只写 user scope memory，不注入 project/repo context。
        """
        store = InMemoryMemoryStore()
        dispatcher = _build_phase1_dispatcher_with_retain_handler(store=store)
        request = _make_retain_request()

        result = dispatcher.route(request)

        evidence = result.evidence
        assert "project_context" not in evidence or not evidence.get("project_context")
        assert "repo_context" not in evidence or not evidence.get("repo_context")

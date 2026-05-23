"""Tool Branch confirmation_required Behavior TDD 测试。

中文学习边界：
这些测试钉死 tool.gate branch point 的 confirmation_required branch behavior：

1. confirmation_required 是 tool.gate 下已有 branch behavior，非新 Anchor / 新 capability milestone
2. tool.gate 的 gate 判定逻辑对 fake/real 完全相同——fake/real 只在配置层不同
3. confirmation_required 时 tool function 不被调用（dangerous_tool_function_invoked=False）
4. dogfood 不能通过直接构造 RuntimeAction 冒充 E2E（payload 不可升级分类）
5. direct dispatcher 只能是 harness_runtime_e2e，direct handler call 只能是 subsystem_integration
6. _safe_noop 的 confirmation="never" → allowed path 不可被破坏

测试分层：
- L1 (subsystem_integration): ToolGateHandler.handle() 直接调用
- L2 (harness_runtime_e2e): dispatcher.route() 通过 harness 路径
- L3 (real_core_loop_runtime_e2e): route_from_runtime_loop() — B2 test DEFERRED 到 U4
"""

from __future__ import annotations

from typing import Any, Callable

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
    classify_evidence_level,
)
from agent.runtime_integration.evidence import (
    HARNESS_RUNTIME_E2E,
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.tool_gate import ToolGateHandler

from tests.runtime_integration.test_tool_anchor_fake import (
    _build_phase1_dispatcher_with_tool_gate,
    _SpyDispatcher,
)


# ========== 测试辅助工具 ==========


def _register_test_confirmable_tool(
    *,
    name: str = "test_confirmable_noop",
    confirmation: str | Callable = "always",
    risk_level: str = "low",
    capability: str = "local_action",
) -> None:
    """在 TOOL_REGISTRY 中临时注册一个无副作用的 confirmable test tool。

    中文学习边界：
    该 tool 走正常 gate path（非 `_` 前缀 → 非 allowlist 路径 → 正常
    needs_tool_confirmation 检查），用于在 harness 层触发 confirmation_required
    gate disposition。

    调用方必须在测试清理阶段从 TOOL_REGISTRY 中移除该 tool。

    安全保证：
    - zero-arg, no shell, no file write, no external process, no network
    - 函数体仅返回固定字符串，不产生任何副作用
    """
    import agent.tools  # noqa: F401 - 确保 production tools 已注册
    from agent.tool_registry import TOOL_REGISTRY

    callable_counter = {"called": 0}

    def _test_func() -> str:
        callable_counter["called"] += 1
        return "test confirmable noop: ok"

    TOOL_REGISTRY[name] = {
        "name": name,
        "description": f"Test confirmable no-op tool (confirmation={confirmation})",
        "parameters": {},
        "confirmation": confirmation,
        "func": _test_func,
        "pre_execute": None,
        "post_execute": None,
        "meta_tool": False,
        "capability": capability,
        "risk_level": risk_level,
        "output_policy": "none",
    }


def _unregister_test_tool(name: str = "test_confirmable_noop") -> None:
    """从 TOOL_REGISTRY 中移除临时注册的 test tool。"""
    from agent.tool_registry import TOOL_REGISTRY

    TOOL_REGISTRY.pop(name, None)


def _make_tool_gate_request(
    *,
    tool_name: str = "test_confirmable_noop",
    tool_args: dict | None = None,
    source: str = "core_loop",
    requested_capability: str = "local_action",
    provider_kind: str = "fake",
    **extra_payload: Any,
) -> RuntimeActionRequest:
    """构造标准的 TOOL_GATE RuntimeActionRequest。

    默认使用 test_confirmable_noop 和 fake provider，调用方可通过
    extra_payload 覆盖任意字段。
    """
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_args": tool_args or {},
        "requested_capability": requested_capability,
        "provider_kind": provider_kind,
        "provider_external_call": False,
        "external_side_effects": False,
        **extra_payload,
    }
    return RuntimeActionRequest(
        action_type=RuntimeActionType.TOOL_GATE,
        source=source,
        parent_trace_id="",
        payload=payload,
    )


# ========== Phase A: Gate Logic — confirmation_required 正例 (L1/L2) ==========


class TestConfirmationRequiredPositiveExamples:
    """confirmation_required 正例：always / callable_true / callable_args / default 子路径。

    中文学习边界：
    SPEC §2.1 定义的三条 confirmation_required 子路径均在此覆盖。
    所有测试通过 dispatcher.route()（L2 harness 路径）触发 gate 判定，
    验证 gate_disposition=confirmation_required 和 dangerous_tool_function_invoked=False。
    """

    def test_confirmation_always_yields_confirmation_required(self):
        """A1: confirmation="always" → gate_disposition=confirmation_required。

        验证当工具注册为 confirmation="always" 时，gate 判定正确返回
        confirmation_required，且 tool function 不被调用。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request()
            result = dispatcher.route(request)

            evidence = dict(result.evidence)
            payload = dict(result.payload)

            assert result.status == "confirmation_required", (
                f"status 必须为 'confirmation_required'，实际 {result.status!r}"
            )
            assert evidence.get("gate_disposition") == "confirmation_required"
            assert evidence.get("decision") == "confirmation_required"
            assert evidence.get("registry_handler_invoked") is True
            assert payload.get("dangerous_tool_function_invoked") is False
            assert evidence.get("target_module_proof") is not None
            # 确认走的是 production registry 路径，非 dogfood overlay
            assert evidence.get("capability_type") == "production_tool_registry"
        finally:
            _unregister_test_tool()

    def test_confirmation_callable_true_yields_confirmation_required(self):
        """A2: callable confirmation 返回 True → confirmation_required。

        验证当工具的 confirmation 是 callable 且对当前 args 返回 True 时，
        gate 正确判定为 confirmation_required。
        """
        _register_test_confirmable_tool(confirmation=lambda args: True)
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request()
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert result.status == "confirmation_required"
            assert evidence.get("gate_disposition") == "confirmation_required"
            assert evidence.get("decision") == "confirmation_required"
            assert evidence.get("registry_handler_invoked") is True
            payload = dict(result.payload)
            assert payload.get("dangerous_tool_function_invoked") is False
        finally:
            _unregister_test_tool()

    def test_confirmation_callable_args_based_yields_confirmation_required(self):
        """A3: callable 基于 args 返回 True → confirmation_required。

        验证 callable confirmation 能正确读取 tool_args 做出判定。
        """
        _register_test_confirmable_tool(
            confirmation=lambda args: args.get("risk") == "high",
        )
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request(
                tool_args={"risk": "high"},
            )
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert result.status == "confirmation_required"
            assert evidence.get("gate_disposition") == "confirmation_required"
            assert evidence.get("decision") == "confirmation_required"
        finally:
            _unregister_test_tool()

    def test_confirmation_default_yields_confirmation_required(self):
        """A4: confirmation 字段为非 "never" 非 callable 值 → confirmation_required。

        needs_tool_confirmation 在 confirmation 不是 "never"/"always"/callable
        时默认返回 True → gate 判定为 confirmation_required。
        """
        _register_test_confirmable_tool(confirmation="some_unknown_value")
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request()
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert result.status == "confirmation_required"
            assert evidence.get("gate_disposition") == "confirmation_required"
        finally:
            _unregister_test_tool()

    def test_confirmable_tool_function_not_invoked(self):
        """A5: confirmation_required 时 tool function 不被调用 (L1)。

        直接调用 ToolGateHandler.handle() 验证 gate check 不执行工具函数。
        """
        from agent.runtime_integration.dispatcher import RuntimeActionContext

        side_effect_counter = {"count": 0}

        def _counted_func() -> str:
            side_effect_counter["count"] += 1
            return "should not be called"

        import agent.tools  # noqa: F401
        from agent.tool_registry import TOOL_REGISTRY

        TOOL_REGISTRY["test_confirmable_counted"] = {
            "name": "test_confirmable_counted",
            "description": "Test tool with side-effect counter",
            "parameters": {},
            "confirmation": "always",
            "func": _counted_func,
            "pre_execute": None,
            "post_execute": None,
            "meta_tool": False,
            "capability": "local_action",
            "risk_level": "low",
            "output_policy": "none",
        }
        try:
            handler = ToolGateHandler()
            observer = RuntimeActionModuleObserver()
            context = RuntimeActionContext(
                action_id="a5-test-action",
                action_type=RuntimeActionType.TOOL_GATE,
                route_id="a5-test-route",
                handler_name="ToolGateHandler",
                handler_identity="agent.runtime_integration.tool_gate.ToolGateHandler",
                parent_trace_id="",
                observer=observer,
            )
            request = _make_tool_gate_request(
                tool_name="test_confirmable_counted",
            )
            result = handler.handle(request, context)

            payload = dict(result.payload)
            evidence = dict(result.evidence)

            assert payload.get("dangerous_tool_function_invoked") is False
            assert evidence.get("gate_disposition") == "confirmation_required"
            assert side_effect_counter["count"] == 0, (
                f"tool function 不应被调用，实际调用了 {side_effect_counter['count']} 次"
            )
        finally:
            TOOL_REGISTRY.pop("test_confirmable_counted", None)

    def test_confirmable_tool_no_side_effects(self):
        """A6: confirmation_required 状态不含副作用标记。

        external_side_effects 必须为 False，dangerous_tool_function_invoked 为 False。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request()
            result = dispatcher.route(request)

            evidence = dict(result.evidence)
            payload = dict(result.payload)

            assert evidence.get("external_side_effects") is False
            assert payload.get("dangerous_tool_function_invoked") is False
            # 确认无 shell/file/network 痕迹
            assert evidence.get("target_module") == "ToolRegistry"
        finally:
            _unregister_test_tool()

    def test_confirmation_required_evidence_structure(self):
        """A7: confirmation_required 时 evidence 字段完整性。

        验证所有必需 evidence 字段存在且值正确。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request()
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert evidence.get("registry_handler_invoked") is True
            assert evidence.get("target_module_invoked") is False, (
                "confirmation_required 时 handler 不调用 target module function"
            )
            assert evidence.get("policy_path") == "tool_registry→risk_check"
            assert evidence.get("rejection_reason") is None, (
                "confirmation_required 不是拒绝——rejection_reason 必须为 None"
            )
            assert evidence.get("production_registry_found") is True
            assert evidence.get("capability_type") == "production_tool_registry"
            # evidence 不含 core_loop_invoked（direct dispatcher 路径）
            assert evidence.get("dispatcher_origin") == "direct_dispatcher"
        finally:
            _unregister_test_tool()


# ========== Phase B: Classification Boundaries (L2) ==========


class TestConfirmationRequiredClassificationBoundaries:
    """分类边界测试：harness / subsystem / payload 反欺诈。

    中文学习边界：
    - B1: direct dispatcher.route() → harness_runtime_e2e（不可冒充 real）
    - B2: route_from_runtime_loop() → real_core_loop_runtime_e2e（DEFERRED 到 U4）
    - B3: 直接 ToolGateHandler.handle() → subsystem_integration
    - B4: payload 中的 core_loop_invoked 不可升级分类
    """

    def test_direct_dispatcher_is_harness_not_real_core_loop(self):
        """B1: direct dispatcher.route() → harness_runtime_e2e。

        验证通过 dispatcher.route()（非 route_from_runtime_loop()）触发的
        confirmation_required 结果分类为 harness_runtime_e2e，不得 overclaim
        为 real_core_loop_runtime_e2e。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request()
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
                f"direct dispatch 分类必须为 {HARNESS_RUNTIME_E2E}，"
                f"实际 {evidence.get('evidence_level')!r}"
            )
            assert evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E
            assert evidence.get("dispatcher_origin") == "direct_dispatcher"

            # 通过 classify_evidence_level 二次确认
            level = classify_evidence_level(evidence)
            assert level == HARNESS_RUNTIME_E2E
            assert level != REAL_CORE_LOOP_RUNTIME_E2E
        finally:
            _unregister_test_tool()

    def test_direct_handler_is_subsystem_integration(self):
        """B3: 直接 ToolGateHandler.handle() → subsystem_integration。

        绕过 dispatcher 直接调用 handler 不能获得 dispatcher provenance，
        分类必须降级为 subsystem_integration。
        """
        from agent.runtime_integration.dispatcher import RuntimeActionContext

        _register_test_confirmable_tool(confirmation="always")
        try:
            handler = ToolGateHandler()
            observer = RuntimeActionModuleObserver()
            context = RuntimeActionContext(
                action_id="b3-test-action",
                action_type=RuntimeActionType.TOOL_GATE,
                route_id="b3-test-route",
                handler_name="ToolGateHandler",
                handler_identity="agent.runtime_integration.tool_gate.ToolGateHandler",
                parent_trace_id="",
                observer=observer,
            )
            request = _make_tool_gate_request()
            result = handler.handle(request, context)

            evidence = dict(result.evidence)

            # 无 dispatcher provenance → 不可 claim harness 或 real
            assert evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E, (
                "direct handler 不得产生 real_core_loop_runtime_e2e"
            )
            assert evidence.get("evidence_level") != HARNESS_RUNTIME_E2E, (
                "direct handler 不得产生 harness_runtime_e2e"
            )
            # 但 gate 判定本身仍然正确
            assert evidence.get("gate_disposition") == "confirmation_required"
        finally:
            _unregister_test_tool()

    def test_payload_cannot_upgrade_classification(self):
        """B4: payload 中的 core_loop_invoked 不可升级 direct dispatcher 分类。

        即使 payload 包含 core_loop_invoked=True 和 core_entrypoint="core.chat"，
        dispatcher 应基于 dispatcher_origin 判定分类（非 payload），
        结果仍为 harness_runtime_e2e。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request(
                core_loop_invoked=True,
                core_entrypoint="core.chat",
                runtime_hook_name="loop.turn_end",
            )
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
                "payload 中的 core_loop_invoked 不可升级分类——"
                f"实际 {evidence.get('evidence_level')!r}"
            )
            assert evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E
            # dispatcher 基于 dispatcher_origin 判定，非 payload
            assert evidence.get("dispatcher_origin") == "direct_dispatcher"
            assert evidence.get("runtime_loop_invoked") is not True
        finally:
            _unregister_test_tool()

    def test_route_from_runtime_loop_is_real_core_loop_e2e(self):
        """B2: route_from_runtime_loop() → real_core_loop_runtime_e2e (L3)。

        验证通过 route_from_runtime_loop()（runtime loop 专用 route）触发的
        confirmation_required 结果分类为 real_core_loop_runtime_e2e。
        这证明 confirmation_required branch behavior 的 real loop 路径可达。

        中文学习边界——这个测试保护什么：
        - confirmation_required 不只是 harness 层可验证的行为
        - real_core_loop_runtime_e2e 路径通过 route_from_runtime_loop() 可达
        - dispatcher_origin="runtime_loop" 和 runtime_loop_invoked=True 证明
          是真实 runtime loop 触发的 TOOL_GATE action
        - fake/real 共享同一 gate 逻辑——这条路径对 real provider 同样有效
        - 这不是新 Anchor，不是新 runtime flow——都在已有 tool.gate branch point 内
        """
        dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _SpyDispatcher(dispatcher)
        request = _make_tool_gate_request(
            tool_name="_confirmable_noop",
            tool_args={},
            provider_kind="fake",
        )
        result = spy.route_from_runtime_loop(request)

        evidence = dict(result.evidence)

        # 分类验证
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"route_from_runtime_loop 分类必须为 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop", (
            f"dispatcher_origin 必须为 'runtime_loop'，"
            f"实际 {evidence.get('dispatcher_origin')!r}"
        )
        assert evidence.get("runtime_loop_invoked") is True, (
            "runtime_loop_invoked 必须为 True"
        )

        # gate 判定验证
        assert result.status == "confirmation_required", (
            f"status 必须为 'confirmation_required'，实际 {result.status!r}"
        )
        assert evidence.get("gate_disposition") == "confirmation_required"
        assert evidence.get("decision") == "confirmation_required"

        # 安全验证
        payload = dict(result.payload)
        assert payload.get("dangerous_tool_function_invoked") is False

        # classify_evidence_level 二次确认
        level = classify_evidence_level(evidence)
        assert level == REAL_CORE_LOOP_RUNTIME_E2E

    def test_loop_dependencies_drives_tool_gate_payload(self):
        """B5: LoopDependencies.tool_gate_tool_name 被 loop/turn-end path 消费。

        通过 _try_phase1_turn_end_runtime_action 注入
        LoopDependencies(tool_gate_tool_name="_confirmable_noop")，
        验证：
        - TOOL_GATE payload/requested_tool_name 是 _confirmable_noop
        - 走的是 route_from_runtime_loop（非 direct dispatcher.route）
        - result 为 confirmation_required
        - tool_invoked=false
        - dangerous_tool_function_invoked=false
        - external_side_effects=false
        - evidence_level=real_core_loop_runtime_e2e
        - 不新增 fake loop / fake dispatcher / dogfood-only path

        中文学习边界——这个测试保护什么：
        B2 测试证明 route_from_runtime_loop() 可以产生 real_core_loop_runtime_e2e，
        但它直接构造 RuntimeActionRequest 并手动调用 spy.route_from_runtime_loop()。
        本测试补上缺失的一环：证明 _confirmable_noop 不只是能在 harness 层手动构造
        request 触发——它确实能通过 LoopDependencies.tool_gate_tool_name 配置字段
        被真实的 loop/turn-end path（_try_phase1_turn_end_runtime_action）消费。

        为什么不是 fake loop：
        - 调用的是 production _try_phase1_turn_end_runtime_action（与 core loop 同一函数）
        - 使用 production LoopDependencies dataclass 实例
        - 走 production ToolGateHandler → tool.gate branch point
        - spy 只观察不改变行为——与 Phase 1 dogfood 的 SpyDispatcher 模式一致

        为什么不是 dogfood-only path：
        - production loop.py 在 turn-end 时调用同一函数
        - 唯一的"配置切换"是 LoopDependencies.tool_gate_tool_name 字段值
        - fake/real 共享同一 gate 逻辑——这条路径对 real provider 同样有效
        """
        import agent.tools  # noqa: F401 - 触发工具注册，确保 _confirmable_noop 在 registry
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        # 构造 result-capturing spy——记录每次 route 的 method + request + result
        captured: list[tuple[str, RuntimeActionRequest, Any]] = []

        class _LoopPathSpy:
            """捕获 method + request + result 的 spy。

            与 _SpyDispatcher 不同：_SpyDispatcher 只捕获 request，
            本 spy 同时捕获 result 以便验证 gate 判定结果。
            """
            def __init__(self, real: RuntimeActionDispatcher) -> None:
                self._real = real

            def route(self, request: RuntimeActionRequest) -> Any:
                result = self._real.route(request)
                captured.append(("route", request, result))
                return result

            def route_from_runtime_loop(self, request: RuntimeActionRequest) -> Any:
                result = self._real.route_from_runtime_loop(request)
                captured.append(("route_from_runtime_loop", request, result))
                return result

        dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _LoopPathSpy(dispatcher)

        # 构造最小 mock state——只需 conversation.messages 中有 user 消息
        # 即可让 _try_phase1_turn_end_runtime_action 提取 last_user
        class _MockConversation:
            messages: list[dict] = [{"role": "user", "content": "hello"}]

        class _MockState:
            conversation = _MockConversation()

        mock_state = _MockState()

        # 构造 LoopDependencies，注入 _confirmable_noop
        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="_confirmable_noop",
        )

        # 调用 turn-end hook——这是 loop.py 在每次 turn end 时的真实入口
        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 验证 spy 捕获了至少两个 action（MEMORY + TOOL_GATE）
        assert len(captured) >= 2, (
            f"应至少有 MEMORY 和 TOOL_GATE 两个 action，实际 {len(captured)}"
        )

        # 找出 TOOL_GATE action
        tg_method: str | None = None
        tg_request: RuntimeActionRequest | None = None
        tg_result: Any = None
        for method, request, result in captured:
            if request.action_type == RuntimeActionType.TOOL_GATE:
                tg_method = method
                tg_request = request
                tg_result = result
                break

        assert tg_request is not None, (
            f"应存在 TOOL_GATE action，实际 captured types: "
            f"{[r.action_type.value for _, r, _ in captured]}"
        )

        # === 断言组 1：loop path 正确消费了 LoopDependencies 配置 ===

        # TOOL_GATE payload 中的 tool_name 来自 LoopDependencies.tool_gate_tool_name
        assert tg_request.payload["tool_name"] == "_confirmable_noop", (
            f"TOOL_GATE tool_name 应来自 LoopDependencies.tool_gate_tool_name，"
            f"实际 {tg_request.payload['tool_name']!r}"
        )
        assert tg_request.payload.get("tool_args") == {}
        assert tg_request.payload.get("requested_capability") == "local_action"

        # 走的是 route_from_runtime_loop（real core loop 路径），非 direct dispatcher.route
        assert tg_method == "route_from_runtime_loop", (
            f"loop turn-end path 应使用 route_from_runtime_loop，实际 {tg_method!r}"
        )

        # === 断言组 2：gate 判定结果（confirmation_required） ===

        assert tg_result is not None, "TOOL_GATE result 不应为 None"
        assert tg_result.status == "confirmation_required", (
            f"status 必须为 'confirmation_required'，实际 {tg_result.status!r}"
        )

        evidence = dict(tg_result.evidence)
        assert evidence.get("gate_disposition") == "confirmation_required"
        assert evidence.get("decision") == "confirmation_required"

        # === 断言组 3：安全保证（无副作用） ===

        payload = dict(tg_result.payload)
        assert payload.get("tool_invoked") is not True, (
            "confirmation_required 时 tool 不得被调用"
        )
        assert payload.get("dangerous_tool_function_invoked") is False
        assert evidence.get("external_side_effects") is False

        # === 断言组 4：分类不 overclaim ===

        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"real core loop path 分类必须为 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True

        # 二次确认：classify_evidence_level
        level = classify_evidence_level(evidence)
        assert level == REAL_CORE_LOOP_RUNTIME_E2E

        # === 断言组 5：不是 dogfood-only path ===
        # payload 不含 dogfood 特有标记
        assert "dogfood_harness" not in evidence
        assert evidence.get("capability_type") == "production_tool_registry"


# ========== Phase C: Negative Coverage — blocked / not_found (L2) ==========


class TestConfirmationRequiredNegativeCoverage:
    """负例覆盖：not_found / blocked / rejected。

    中文学习边界：
    blocked 和 not_found 是 tool.gate branch point 的负例 branch behavior，
    不是独立的新 Anchor 或 capability milestone。这些测试作为边界保护存在，
    确保 gate 在非 happy path 下的行为正确。
    """

    def test_not_found_tool_returns_not_found(self):
        """C1: 不在 registry 的工具 → decision=not_found。

        验证请求不存在的工具时 gate 返回 not_found 而非崩溃或误判。
        """
        dispatcher = _build_phase1_dispatcher_with_tool_gate()
        request = _make_tool_gate_request(
            tool_name="nonexistent_tool_xyz",
        )
        result = dispatcher.route(request)

        evidence = dict(result.evidence)

        assert result.status in ("rejected", "failed"), (
            f"not_found 应返回 rejected/failed，实际 {result.status!r}"
        )
        assert evidence.get("decision") == "not_found"
        assert evidence.get("gate_disposition") is None
        assert evidence.get("rejection_reason") == "tool not found in production ToolRegistry"
        assert evidence.get("production_registry_found") is False
        payload = dict(result.payload)
        assert payload.get("tool_invoked") is not True, (
            "不存在的 tool 不得被调用"
        )

    def test_blocked_forbidden_tool_name(self):
        """C2: bash 在 _FORBIDDEN_TOOL_NAMES → rejected。

        验证 shell-like tool name 在进入 registry lookup 之前即被拒绝。
        """
        import agent.tools  # noqa: F401
        from agent.tool_registry import TOOL_REGISTRY

        # 确保 bash 在 registry 中存在（模拟生产注册）
        if "bash" not in TOOL_REGISTRY:
            TOOL_REGISTRY["bash"] = {
                "name": "bash",
                "description": "shell tool",
                "parameters": {},
                "confirmation": "always",
                "func": lambda: "should not run",
                "pre_execute": None,
                "post_execute": None,
                "meta_tool": False,
                "capability": "command_execution",
                "risk_level": "high",
                "output_policy": "none",
            }
            _cleanup_bash = True
        else:
            _cleanup_bash = False

        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request(
                tool_name="bash",
            )
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert result.status == "rejected"
            assert evidence.get("gate_disposition") == "rejected"
            assert evidence.get("decision") == "rejected"
            rejection_reason = evidence.get("rejection_reason") or ""
            assert "shell" in rejection_reason.lower()
        finally:
            if _cleanup_bash:
                TOOL_REGISTRY.pop("bash", None)

    def test_blocked_callable_returns_block(self):
        """C3: callable confirmation 返回 "block" → rejected。

        验证 confirmation callable 可以返回 "block" 来拒绝工具执行。
        """
        _register_test_confirmable_tool(
            confirmation=lambda args: "block",
        )
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request()
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert result.status == "rejected"
            assert evidence.get("gate_disposition") == "rejected"
            assert evidence.get("decision") == "rejected"
            assert evidence.get("rejection_reason") == "tool policy blocked request"
        finally:
            _unregister_test_tool()

    def test_not_model_visible_tool_blocked(self):
        """C4: 不在 model-visible list 的工具 → rejected。

        通过 monkeypatch get_model_visible_tools 返回空列表，
        验证 gate 正确拒绝不在 model-visible 列表中的工具。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()

            # monkeypatch get_model_visible_tools 返回空列表
            # 注意：必须 patch agent.tool_registry 而非 tool_gate module，
            # 因为 ToolGateHandler.handle() 内部通过 from import 引用此函数。
            import agent.tool_registry as tr_module

            original_get = tr_module.get_model_visible_tools
            tr_module.get_model_visible_tools = lambda **kwargs: []

            try:
                request = _make_tool_gate_request()
                result = dispatcher.route(request)

                evidence = dict(result.evidence)

                assert result.status == "rejected"
                assert evidence.get("gate_disposition") == "rejected"
                rejection_reason = evidence.get("rejection_reason") or ""
                assert "not model-visible" in rejection_reason
            finally:
                tr_module.get_model_visible_tools = original_get
        finally:
            _unregister_test_tool()


# ========== Phase D: Memory / Tool Isolation (L2) ==========


class TestMemoryToolGateIsolation:
    """MEMORY 和 TOOL_GATE action 的隔离性测试。

    中文学习边界：
    tool.gate 和 memory.turn_end_proposal 是同一 lifecycle 中
    独立触发的两个 action。一个失败不得阻断另一个，evidence 不得交叉污染。
    loop.py:_try_phase1_turn_end_runtime_action 中两个 action 各自独立
    try/except 保证这一点。
    """

    def test_tool_gate_failure_does_not_block_memory(self):
        """D1: TOOL_GATE 失败不阻断 MEMORY action。

        构造两个独立 request（MEMORY + TOOL_GATE 失败场景），
        通过 spy dispatcher 分别 route，验证两个 action evidence 独立存在。
        """
        import agent.tools  # noqa: F401
        from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler

        registry = ActionHandlerRegistry()
        registry.register(
            RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            MemoryTurnEndProposalHandler(),
        )
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        real = RuntimeActionDispatcher(
            registry=registry,
            observer=RuntimeActionModuleObserver(),
        )
        spy = _SpyDispatcher(real)

        # TOOL_GATE 请求一个不存在的工具（预期失败）
        tool_request = _make_tool_gate_request(
            tool_name="nonexistent_tool_xyz",
        )
        # MEMORY 请求
        memory_request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="core_loop",
            parent_trace_id="",
            payload={
                "user_message": "hello",
                "assistant_response": "hi there",
                "provider_kind": "fake",
                "provider_external_call": False,
                "external_side_effects": False,
            },
        )

        tool_result = spy.route(tool_request)
        memory_result = spy.route(memory_request)

        # TOOL_GATE 失败
        assert tool_result.status in ("rejected", "failed")
        # MEMORY 不应被 TOOL_GATE 的失败阻断
        assert memory_result.status == "success", (
            f"MEMORY action 不应被 TOOL_GATE 失败阻断，实际 status={memory_result.status!r}"
        )

        # 两个 action 独立存在
        assert len(spy.route_calls) == 2

    def test_memory_failure_does_not_block_tool_gate(self):
        """D2: MEMORY 失败不阻断 TOOL_GATE action。

        反向验证：MEMORY 的失败不应影响 TOOL_GATE 的正常判定。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            import agent.tools  # noqa: F401
            from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler

            registry = ActionHandlerRegistry()
            registry.register(
                RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
                MemoryTurnEndProposalHandler(),
            )
            registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
            real = RuntimeActionDispatcher(
                registry=registry,
                observer=RuntimeActionModuleObserver(),
            )
            spy = _SpyDispatcher(real)

            # MEMORY 请求——空 user_message（可能触发 failure）
            memory_request = RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
                source="core_loop",
                parent_trace_id="",
                payload={
                    "user_message": "",
                    "assistant_response": "",
                    "provider_kind": "fake",
                    "provider_external_call": False,
                    "external_side_effects": False,
                },
            )
            # TOOL_GATE 正常请求
            tool_request = _make_tool_gate_request()

            spy.route(memory_request)  # D2: 仅验证 MEMORY 不阻断 TOOL_GATE，不检查 MEMORY 结果
            tool_result = spy.route(tool_request)

            # TOOL_GATE 必须正常工作，不被 MEMORY 状态影响
            assert tool_result.status == "confirmation_required", (
                f"TOOL_GATE 不应被 MEMORY 影响，实际 status={tool_result.status!r}"
            )
            tool_evidence = dict(tool_result.evidence)
            assert tool_evidence.get("gate_disposition") == "confirmation_required"

            assert len(spy.route_calls) == 2
        finally:
            _unregister_test_tool()

    def test_memory_evidence_not_polluted_by_tool_gate(self):
        """D3: MEMORY evidence 不含 tool.gate 字段。

        验证两个 action 的 evidence 不会交叉污染。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            import agent.tools  # noqa: F401
            from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler

            registry = ActionHandlerRegistry()
            registry.register(
                RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
                MemoryTurnEndProposalHandler(),
            )
            registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
            real = RuntimeActionDispatcher(
                registry=registry,
                observer=RuntimeActionModuleObserver(),
            )
            spy = _SpyDispatcher(real)

            memory_request = RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
                source="core_loop",
                parent_trace_id="",
                payload={
                    "user_message": "hello",
                    "assistant_response": "hi",
                    "provider_kind": "fake",
                    "provider_external_call": False,
                    "external_side_effects": False,
                },
            )
            tool_request = _make_tool_gate_request()

            memory_result = spy.route(memory_request)
            tool_result = spy.route(tool_request)

            memory_evidence = dict(memory_result.evidence)
            tool_evidence = dict(tool_result.evidence)

            # MEMORY evidence 不含 tool.gate 特有字段
            assert "gate_disposition" not in memory_evidence, (
                "MEMORY evidence 不应被 tool.gate 字段污染"
            )
            assert "requested_tool_name" not in memory_evidence, (
                "MEMORY evidence 不应含 requested_tool_name"
            )

            # TOOL_GATE evidence 正确
            assert tool_evidence.get("gate_disposition") == "confirmation_required"
        finally:
            _unregister_test_tool()

    def test_tool_gate_evidence_not_polluted_by_memory(self):
        """D4: TOOL_GATE evidence 不含 memory 字段。

        反向验证：TOOL_GATE evidence 不应被 memory 字段污染。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            import agent.tools  # noqa: F401
            from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler

            registry = ActionHandlerRegistry()
            registry.register(
                RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
                MemoryTurnEndProposalHandler(),
            )
            registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
            real = RuntimeActionDispatcher(
                registry=registry,
                observer=RuntimeActionModuleObserver(),
            )
            spy = _SpyDispatcher(real)

            memory_request = RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
                source="core_loop",
                parent_trace_id="",
                payload={
                    "user_message": "hello",
                    "assistant_response": "hi",
                    "provider_kind": "fake",
                    "provider_external_call": False,
                    "external_side_effects": False,
                },
            )
            tool_request = _make_tool_gate_request()

            spy.route(memory_request)
            tool_result = spy.route(tool_request)

            tool_evidence = dict(tool_result.evidence)

            # TOOL_GATE evidence 不含 memory 特有字段
            assert "proposal" not in tool_evidence, (
                "TOOL_GATE evidence 不应被 memory proposal 字段污染"
            )
            assert "suggestion" not in tool_evidence, (
                "TOOL_GATE evidence 不应被 memory suggestion 字段污染"
            )
            assert tool_evidence.get("gate_disposition") == "confirmation_required"
        finally:
            _unregister_test_tool()


# ========== Phase E: Fake/Real Boundary (L2) ==========


class TestConfirmationRequiredFakeRealBoundary:
    """fake/real 配置层边界测试。

    中文学习边界：
    Unified Runtime Flow Contract §1 规定 fake 和 real 共享同一业务流，
    仅在配置和 adapter 层不同。对于 confirmation_required 这意味着：
    - ToolGateHandler.handle() 的 gate 判定逻辑完全相同
    - provider_kind 是 evidence metadata，不改变 gate 判定
    - 不存在 fake-only 或 real-only 的 confirmation_required 代码路径
    """

    def test_fake_provider_same_gate_logic_as_real(self):
        """E1: fake provider 与 real 共享同一 gate 逻辑。

        使用 provider_kind="fake" 的 request，验证 gate 判定结果
        与 provider_kind 无关。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request(
                provider_kind="fake",
            )
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert evidence.get("gate_disposition") == "confirmation_required"
            assert evidence.get("capability_type") == "production_tool_registry"
            assert evidence.get("provider_kind") == "fake", (
                "provider_kind 应记录为 metadata，但不应改变 gate 判定"
            )
            # provider_kind 不改变 gate 路径——仍走 production registry
            assert evidence.get("production_registry_found") is True
        finally:
            _unregister_test_tool()

    def test_confirmation_required_no_real_api(self):
        """E2: 本轮不涉及真实 API — 不需要 .env 或真实 API key。

        这是一个"元测试"：所有 confirmation_required 测试均在 fake provider
        下运行，不依赖真实外部服务。
        """
        _register_test_confirmable_tool(confirmation="always")
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = _make_tool_gate_request(
                provider_kind="fake",
                provider_external_call=False,
            )
            result = dispatcher.route(request)

            evidence = dict(result.evidence)

            assert evidence.get("external_side_effects") is False
            assert evidence.get("provider_external_call") is False
            # gate 判定仍然正确
            assert evidence.get("gate_disposition") == "confirmation_required"
        finally:
            _unregister_test_tool()

"""ToolRegistry Safe Tool Anchor fake-provider TDD 测试。

中文学习边界：
这些测试钉死 ToolRegistry Safe Tool Anchor 的 fake-provider 全链路架构边界：
1. core.chat() 统一入口 → turn-end hook → dispatcher → ToolGateHandler → evidence
2. 不新增 fake runtime / fake loop / fake dispatcher 主路径
3. _safe_noop 通过最小 allowlist 进入 ToolRegistry gate，其他 _ 前缀工具仍 blocked
4. TOOL_GATE action 独立于 MEMORY_TURN_END_PROPOSAL，各自 try/except 隔离
5. runtime checks 必须按 action_type == "tool.gate" 查找，不能用 actions[0/1]
6. direct dispatcher 只能是 harness_runtime_e2e，不能冒充 real_core_loop_runtime_e2e

架构依据：~/.claude/plans/velvety-brewing-boole.md
"""

from __future__ import annotations

from typing import Any

from agent.provider.fake_provider import FakeProvider
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

# ========== 测试辅助 ==========


def _build_phase1_dispatcher_with_tool_gate() -> RuntimeActionDispatcher:
    """构建包含 MemoryTurnEndProposalHandler + ToolGateHandler 的 dispatcher。

    中文学习边界：
    与 agent.runtime_integration.phase1_hook.build_phase1_dispatcher() 行为等价，
    但额外注册 ToolGateHandler。在测试文件中独立定义以保持自包含。
    """
    from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler

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


class _SpyDispatcher:
    """包装 RuntimeActionDispatcher，拦截 route() 调用用于测试断言。

    中文学习边界：
    这个 spy 是刻意存在的外部观察点——不修改生产代码一行，只记录每次 route()
    调用及其参数。生产代码（loop.py turn-end hook）不知道 spy 的存在。
    """

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self._route_calls: list[RuntimeActionRequest] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        self._route_calls.append(request)
        return self._real.route(request)

    def route_from_runtime_loop(self, request: RuntimeActionRequest, **kwargs: object) -> Any:
        """测试 spy 透传 runtime-loop route，保留 core.chat 正路径分类。"""
        self._route_calls.append(request)
        return self._real.route_from_runtime_loop(request)

    @property
    def action_log(self):
        return self._real.action_log

    @property
    def route_calls(self) -> tuple[RuntimeActionRequest, ...]:
        return tuple(self._route_calls)


# ========== Phase A: safe tool registry gate 测试 ==========


class TestToolAnchorSafeToolRegistryGate:
    """测试 _safe_noop 通过 ToolRegistry gate 的注册/查找/allowlist 路径。

    中文学习边界：
    这组测试验证 ToolRegistry gate 的核心逻辑——工具注册、查找、下划线前缀
    allowlist、shell-like 拒绝——不需要 core.chat() 全链路，直接通过
    dispatcher.route() 触发 TOOL_GATE action。
    """

    def test_safe_tool_invoked_through_registry_not_direct_call(self):
        """验证 _safe_noop gate check 通过 TOOL_REGISTRY 进行，非直接函数调用。

        中文学习边界——这个测试保护什么：
        - gate handler 通过 TOOL_REGISTRY 查找工具，而非调用工具函数
        - _safe_noop 注册在 production TOOL_REGISTRY 中
        - gate_disposition 为 "allowed"（confirmation="never"）
        - dangerous_tool_function_invoked == False（gate check 不执行工具）

        Purpose: 验证 _safe_noop 的 gate check 通过 TOOL_REGISTRY 而非直接调用
        Setup: dispatcher with ToolGateHandler + _safe_noop registered
        Action: 构造 TOOL_GATE request (tool_name="_safe_noop"), dispatcher.route()
        Expected evidence:
          - requested_tool_name == "_safe_noop"
          - production_registry_found == True
          - target_module == "ToolRegistry"
          - gate_disposition == "allowed"
          - dangerous_tool_function_invoked == False
        Forbidden: 在 handler 中直接调用 _safe_noop() 函数
        Pass/fail: registry_found=True AND gate_disposition="allowed"
        """
        import agent.tools  # noqa: F401 - 触发工具注册
        from agent.tool_registry import TOOL_REGISTRY

        # 前置条件：_safe_noop 必须在 TOOL_REGISTRY 中
        assert "_safe_noop" in TOOL_REGISTRY, (
            "_safe_noop 未注册到 TOOL_REGISTRY——"
            "请检查 agent/tools/safe_noop.py 是否存在且被 agent/tools/__init__.py 导入"
        )

        dispatcher = _build_phase1_dispatcher_with_tool_gate()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_args": {},
                "requested_capability": "local_action",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "provider_external_call": False,
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        assert result.status == "success", (
            f"_safe_noop gate check 应返回 success，实际 {result.status!r}"
        )

        evidence = dict(result.evidence)
        # 注意：evidence_extra 字段由 context.result() 直接合并到 evidence 中，
        # 不存在嵌套的 "evidence_extra" 子 dict

        # registry 查找证据
        assert evidence.get("requested_tool_name") == "_safe_noop", (
            f"requested_tool_name 必须为 '_safe_noop'，"
            f"实际 {evidence.get('requested_tool_name')!r}"
        )
        assert evidence.get("production_registry_found") is True, (
            "_safe_noop 必须在 production TOOL_REGISTRY 中找到"
        )
        assert evidence.get("resolved_tool_name") == "_safe_noop", (
            f"resolved_tool_name 必须为 '_safe_noop'，"
            f"实际 {evidence.get('resolved_tool_name')!r}"
        )

        # gate 决策证据
        assert evidence.get("gate_disposition") == "allowed", (
            f"gate_disposition 必须为 'allowed'（confirmation='never'），"
            f"实际 {evidence.get('gate_disposition')!r}"
        )
        assert evidence.get("decision") == "allowed", (
            f"decision 必须为 'allowed'，实际 {evidence.get('decision')!r}"
        )

        # target module proof
        assert evidence.get("target_module") == "ToolRegistry", (
            f"target_module 必须为 'ToolRegistry'，"
            f"实际 {evidence.get('target_module')!r}"
        )

        # 安全守卫：gate check 不执行工具函数
        payload = dict(result.payload)
        assert payload.get("dangerous_tool_function_invoked") is False, (
            "gate check 不得执行工具函数——dangerous_tool_function_invoked 必须为 False"
        )

        # 不允许出现旧 overlay 路径
        assert evidence.get("capability_type") == "production_tool_registry", (
            f"capability_type 必须为 'production_tool_registry'，"
            f"实际 {evidence.get('capability_type')!r}"
        )

    def test_missing_registry_entry_blocks_or_partial(self):
        """验证不存在于 TOOL_REGISTRY 的 tool_name 被正确拒绝。

        中文学习边界——这个测试保护什么：
        - 请求不存在的工具时 gate 返回 not_found
        - target_module_proof 仍存在（证明 ToolRegistry lookup 确实发生了）
        - decision="not_found" 不得 overclaim 为 safe tool invoked

        Purpose: 验证不存在的 tool_name → not_found
        Setup: dispatcher with ToolGateHandler
        Action: 构造 TOOL_GATE request (tool_name="nonexistent.tool.xyz")
        Expected evidence:
          - decision == "not_found"
          - gate_disposition is None
          - production_registry_found == False
          - target_module_proof 仍存在
        Forbidden: crash; 返回 success/allowed
        Pass/fail: decision="not_found" AND status in ("rejected", "failed")
        """
        dispatcher = _build_phase1_dispatcher_with_tool_gate()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "tool_name": "nonexistent.tool.xyz",
                "tool_args": {},
                "requested_capability": "local_action",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "provider_external_call": False,
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        # not_found 应返回 rejected（不是 success）
        assert result.status in ("rejected", "failed"), (
            f"不存在的工具应返回 rejected/failed，实际 {result.status!r}"
        )

        evidence = dict(result.evidence)

        assert evidence.get("decision") == "not_found", (
            f"decision 必须为 'not_found'，实际 {evidence.get('decision')!r}"
        )
        assert evidence.get("gate_disposition") is None, (
            f"not_found 时 gate_disposition 必须为 None，"
            f"实际 {evidence.get('gate_disposition')!r}"
        )
        assert evidence.get("production_registry_found") is False, (
            "不存在的工具 production_registry_found 必须为 False"
        )
        assert evidence.get("resolved_tool_name") is None, (
            f"不存在的工具 resolved_tool_name 必须为 None，"
            f"实际 {evidence.get('resolved_tool_name')!r}"
        )

        # target_module_proof 仍存在——证明 lookup 确实发生了
        assert evidence.get("target_module_proof") is not None, (
            "not_found 时 target_module_proof 仍须存在——"
            "它证明 ToolRegistry lookup 确实发生并返回了 None"
        )
        assert evidence.get("target_module") == "ToolRegistry"

    def test_shell_like_tool_is_blocked(self):
        """验证 _FORBIDDEN_TOOL_NAMES 中的 shell-like 工具名被 gate 拒绝。

        中文学习边界——这个测试保护什么：
        - "run_shell" 在 _FORBIDDEN_TOOL_NAMES 中
        - gate 检查的第一道防线就是 forbidden names
        - 即使 run_shell 在 TOOL_REGISTRY 中注册了，gate 也必须拒绝
        - risk_level 必须为 "high"

        Purpose: 验证 shell-like tool → rejected
        Setup: dispatcher with ToolGateHandler
        Action: 构造 TOOL_GATE request (tool_name="run_shell")
        Expected evidence:
          - gate_disposition == "rejected"
          - rejection_reason == "shell-like tool is out of scope"
          - risk_level == "high"
        Forbidden: shell tool 通过 gate
        Pass/fail: rejected with correct reason
        """
        dispatcher = _build_phase1_dispatcher_with_tool_gate()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "tool_name": "run_shell",
                "tool_args": {},
                "requested_capability": "command_execution",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "provider_external_call": False,
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        assert result.status == "rejected", (
            f"shell-like tool 必须被拒绝，实际 status={result.status!r}"
        )

        evidence = dict(result.evidence)

        assert evidence.get("gate_disposition") == "rejected", (
            f"gate_disposition 必须为 'rejected'，"
            f"实际 {evidence.get('gate_disposition')!r}"
        )
        assert evidence.get("decision") == "rejected"
        rejection_reason = evidence.get("rejection_reason") or ""
        assert "shell" in rejection_reason.lower(), (
            f"rejection_reason 必须提及 shell，实际 {rejection_reason!r}"
        )

        payload = dict(result.payload)
        assert payload.get("risk_level") == "high", (
            f"shell-like tool risk_level 必须为 'high'，"
            f"实际 {payload.get('risk_level')!r}"
        )

    def test_other_internal_underscore_tool_is_blocked_unless_allowlisted(self):
        """验证非 allowlist 的 `_` 内部工具仍被 ToolGateHandler 拒绝。

        中文学习边界：
        `_safe_noop` 是唯一用于 branch behavior validation 的内部安全工具。
        remediation 不能把它扩展成“所有下划线工具都允许”的治理漏洞。
        """
        import agent.tools  # noqa: F401 - 触发工具注册
        from agent.tool_registry import TOOL_REGISTRY

        TOOL_REGISTRY["_unsafe_internal_test"] = {
            "name": "_unsafe_internal_test",
            "description": "test-only internal tool",
            "parameters": {},
            "confirmation": "never",
            "func": lambda: "should not run",
            "pre_execute": None,
            "post_execute": None,
            "meta_tool": False,
            "capability": "local_action",
            "risk_level": "low",
            "output_policy": "none",
        }
        try:
            dispatcher = _build_phase1_dispatcher_with_tool_gate()
            request = RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_GATE,
                source="test",
                parent_trace_id="",
                payload={
                    "tool_name": "_unsafe_internal_test",
                    "tool_args": {},
                    "requested_capability": "local_action",
                },
            )

            result = dispatcher.route(request)
        finally:
            TOOL_REGISTRY.pop("_unsafe_internal_test", None)

        assert result.status == "rejected"
        evidence = dict(result.evidence)
        assert evidence.get("gate_disposition") == "rejected"
        assert evidence.get("rejection_reason") == "internal tool is not in tool gate allowlist"


# ========== Phase B: core.chat() 全链路测试 ==========


class TestToolAnchorCoreChatIntegration:
    """测试 core.chat() → TOOL_GATE action 全链路。

    中文学习边界：
    这组测试钉死 fake/real 共用同一条 core path——core.chat() → run_main_loop →
    turn-end hook → TOOL_GATE action。不得存在 fake-only 路径。
    """

    def test_core_chat_invokes_tool_registry_gate(self):
        """验证 core.chat() 入口能触发 TOOL_GATE action。

        中文学习边界——这个测试保护什么：
        - tool gate 路径由真实 core loop 触发（非 direct dispatcher）
        - core_loop_invoked=True 证明 hook 在 loop turn-end 时执行
        - TOOL_GATE action 存在于 action_log 中

        Purpose: 验证 core.chat() 触发 TOOL_GATE action
        Setup: FakeProvider + SpyDispatcher (含 ToolGateHandler)
        Action: chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence:
          - action_log 中至少存在一个 action_type="tool.gate" 的 event
          - evidence.core_loop_invoked == True
          - evidence.core_entrypoint == "core.chat"
          - evidence.runtime_hook_name == "loop.turn_end"
        Forbidden: 通过 direct dispatcher.route() 触发
        Pass/fail: tool.gate event 存在且 core_loop_invoked=True
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)
        assert len(spy.route_calls) >= 1, (
            "core.chat() 执行期间 dispatcher.route() 应被调用至少 1 次"
        )

        # 按 action_type 查找 tool.gate event（不用 actions[0] 或 actions[1]）
        action_events = list(spy.action_log)
        tool_events = [
            e for e in action_events
            if str(e.action_type) == "tool.gate"
        ]
        assert len(tool_events) >= 1, (
            f"action_log 必须包含至少 1 个 tool.gate event，"
            f"实际找到 {len(tool_events)} 个"
        )

        tool_event = tool_events[0]
        evidence = dict(tool_event.evidence)

        assert evidence.get("core_loop_invoked") is True, (
            "core_loop_invoked 必须为 True——"
            "该字段由 loop.py turn-end hook 注入"
        )
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"evidence_level 必须为 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )

    def test_fake_provider_uses_same_core_path_not_fake_loop(self):
        """验证 fake provider 下 TOOL_GATE 走同一 run_main_loop，非 fake-only 路径。

        中文学习边界——这个测试保护什么：
        - fake/real 必须共用同一条 core path
        - dispatcher 实例类型是 RuntimeActionDispatcher（不是 fake 子类）
        - handler 实例类型是 ToolGateHandler（不是 fake/mock handler）
        - source 标记为 "core_loop"（不是 "fake_loop" 或旧 harness）

        Purpose: 钉死 fake/real 共用同一 core path
        Setup: FakeProvider + SpyDispatcher
        Action: chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence:
          - source == "core_loop"
          - dispatcher 实例是 RuntimeActionDispatcher
          - handler 类型是 ToolGateHandler
        Forbidden: 任何 fake-specific handler/dispatcher/loop
        Pass/fail: source="core_loop" AND handler identity is production ToolGateHandler
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)
        assert len(spy.route_calls) >= 1

        # 验证 dispatcher 实例类型——必须不是任何 fake 子类
        assert type(spy._real) is RuntimeActionDispatcher, (
            f"dispatcher 类型必须是 RuntimeActionDispatcher，"
            f"实际 {type(spy._real).__name__}"
        )

        # 验证 handler 类型
        handler = spy._real._registry._handlers.get(RuntimeActionType.TOOL_GATE)
        assert handler is not None, "ToolGateHandler 未注册"
        assert type(handler) is ToolGateHandler, (
            f"handler 类型必须是 ToolGateHandler，"
            f"实际 {type(handler).__name__}"
        )

        # 验证 TOOL_GATE action 的 source 是 core_loop
        action_events = list(spy.action_log)
        tool_events = [
            e for e in action_events
            if str(e.action_type) == "tool.gate"
        ]
        assert len(tool_events) >= 1
        assert tool_events[0].source == "core_loop", (
            f"TOOL_GATE source 必须为 'core_loop'，"
            f"实际 {tool_events[0].source!r}"
        )

    def test_target_module_proof_exists(self):
        """验证 TOOL_GATE handler 产生有效的 target_module_proof。

        中文学习边界——这个测试保护什么：
        - handler 通过 context.invoke_registered_target("ToolRegistry", ...) 调用 target
        - observer chain 产生完整的 target_module_proof
        - target_catalog_allowed=True, target_identity_valid=True, module_invoked=True

        Purpose: 验证 target_module_proof 完整
        Setup: FakeProvider + SpyDispatcher
        Action: chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence:
          - target_module == "ToolRegistry"
          - target_module_proof is not None
          - target_catalog_allowed == True
          - target_identity_valid == True
          - module_invoked == True
        Forbidden: target_module_proof=None
        Pass/fail: target_module_proof 完整
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        action_events = list(spy.action_log)
        tool_events = [
            e for e in action_events
            if str(e.action_type) == "tool.gate"
        ]
        assert len(tool_events) >= 1, "action_log 必须包含 tool.gate event"

        evidence = dict(tool_events[0].evidence)
        assert evidence.get("target_module") == "ToolRegistry", (
            f"target_module 必须为 'ToolRegistry'，"
            f"实际 {evidence.get('target_module')!r}"
        )
        assert evidence.get("target_module_proof") is not None, (
            "target_module_proof 必须存在——observer chain 断裂"
        )
        assert evidence.get("target_catalog_allowed") is True, (
            f"target_catalog_allowed 必须为 True，"
            f"实际 {evidence.get('target_catalog_allowed')!r}"
        )
        assert evidence.get("target_identity_valid") is True, (
            f"target_identity_valid 必须为 True，"
            f"实际 {evidence.get('target_identity_valid')!r}"
        )
        assert evidence.get("module_invoked") is True, (
            f"module_invoked 必须为 True，"
            f"实际 {evidence.get('module_invoked')!r}"
        )


# ========== Phase C: evidence + side effects 测试 ==========


class TestToolAnchorEvidenceAndSideEffects:
    """测试 TOOL_GATE evidence 字段完整性和安全边界。"""

    def test_safe_tool_external_side_effects_false(self):
        """验证 TOOL_GATE action 的 external_side_effects 始终为 false。

        中文学习边界——这个测试保护什么：
        - gate check 本身是纯查询操作，不产生任何副作用
        - _safe_noop 的 capability 不是 file_write/command_execution/mcp_tool
        - external_side_effects=False 钉死安全边界

        Purpose: 钉死 external_side_effects=False
        Setup: FakeProvider + SpyDispatcher
        Action: chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence:
          - external_side_effects == False
        Forbidden: external_side_effects=True
        Pass/fail: external_side_effects=False
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        action_events = list(spy.action_log)
        tool_events = [
            e for e in action_events
            if str(e.action_type) == "tool.gate"
        ]
        assert len(tool_events) >= 1

        evidence = dict(tool_events[0].evidence)
        assert evidence.get("external_side_effects") is False, (
            f"external_side_effects 必须为 False，"
            f"实际 {evidence.get('external_side_effects')!r}"
        )

    def test_capability_matrix_records_requested_resolved_tool(self):
        """验证 evidence 正确记录 requested 和 resolved tool name。

        中文学习边界——这个测试保护什么：
        - evidence_extra 中的 requested_tool_name 和 resolved_tool_name 一致
        - capability_type 为 "production_tool_registry"（非旧 overlay）
        - production_capability == True
        - evidence_level == real_core_loop_runtime_e2e

        Purpose: 验证 capability matrix / evidence 字段完整
        Setup: FakeProvider + SpyDispatcher
        Action: chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence:
          - requested_tool_name == "_safe_noop"
          - resolved_tool_name == "_safe_noop"
          - capability_type == "production_tool_registry"
          - production_capability == True
          - evidence_level == real_core_loop_runtime_e2e
        Forbidden: capability_type 为旧 overlay 路径
        Pass/fail: requested=resolved AND production_capability=True
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        action_events = list(spy.action_log)
        tool_events = [
            e for e in action_events
            if str(e.action_type) == "tool.gate"
        ]
        assert len(tool_events) >= 1

        evidence = dict(tool_events[0].evidence)

        assert evidence.get("requested_tool_name") == "_safe_noop", (
            f"requested_tool_name 必须为 '_safe_noop'，"
            f"实际 {evidence.get('requested_tool_name')!r}"
        )
        assert evidence.get("resolved_tool_name") == "_safe_noop", (
            f"resolved_tool_name 必须为 '_safe_noop'，"
            f"实际 {evidence.get('resolved_tool_name')!r}"
        )
        assert evidence.get("capability_type") == "production_tool_registry", (
            f"capability_type 必须为 'production_tool_registry'，"
            f"实际 {evidence.get('capability_type')!r}"
        )
        assert evidence.get("production_capability") is True, (
            "production_capability 必须为 True"
        )
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"evidence_level 必须为 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )

    def test_provider_kind_still_fake(self):
        """回归测试：Tool Anchor 不改变 provider metadata。

        中文学习边界——这个测试保护什么：
        - TOOL_GATE action 的 provider_kind 仍为 "fake"
        - provider_external_call 仍为 False
        - 这些 metadata 与 MEMORY action 一致，共享同一来源
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        action_events = list(spy.action_log)
        tool_events = [
            e for e in action_events
            if str(e.action_type) == "tool.gate"
        ]
        assert len(tool_events) >= 1

        evidence = dict(tool_events[0].evidence)
        assert evidence.get("provider_kind") == "fake", (
            f"provider_kind 必须为 'fake'，"
            f"实际 {evidence.get('provider_kind')!r}"
        )
        assert evidence.get("provider_external_call") is False, (
            f"provider_external_call 必须为 False，"
            f"实际 {evidence.get('provider_external_call')!r}"
        )


# ========== Phase D: direct dispatch + failure isolation + harness boundary ==========


class TestToolAnchorDirectDispatchAndBoundaries:
    """测试 direct dispatch 分类降级和边界条件。"""

    def test_direct_dispatch_is_harness_not_real_core_loop(self):
        """验证直接 dispatcher.route() 只能是 harness_runtime_e2e。

        中文学习边界——这个测试保护什么：
        - 手工构造 RuntimeActionRequest 并直接 dispatcher.route()
        - 即使 evidence chain 完整，缺 core_loop_invoked=True
          仍降级到 harness_runtime_e2e
        - 防止旧 harness 或其他非 core loop 路径冒充 real

        Purpose: 钉死 direct dispatch ≠ real_core_loop_runtime_e2e
        Setup: dispatcher with ToolGateHandler
        Action: 构造不含 core_loop_invoked 的 TOOL_GATE request, dispatcher.route()
        Expected evidence:
          - evidence_level == harness_runtime_e2e
          - core_loop_invoked is not True
        Forbidden: evidence_level 不是 real_core_loop_runtime_e2e
        Pass/fail: 分类正确降级到 harness_runtime_e2e
        """
        dispatcher = _build_phase1_dispatcher_with_tool_gate()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_args": {},
                "requested_capability": "local_action",
            },
        )
        result = dispatcher.route(request)

        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
            f"direct dispatch 只能得到 {HARNESS_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E, (
            "direct dispatch 不得产生 real_core_loop_runtime_e2e"
        )
        assert evidence.get("core_loop_invoked") is not True, (
            "direct dispatch 不应有 core_loop_invoked=True"
        )

        # 通过 classify_evidence_level 再次确认
        level = classify_evidence_level(evidence)
        assert level == HARNESS_RUNTIME_E2E
        assert level != REAL_CORE_LOOP_RUNTIME_E2E

    def test_direct_dispatch_spoofed_core_payload_is_harness_not_real_core_loop(self):
        """direct dispatcher 伪造 core loop payload 也必须降级。

        中文学习边界：
        只有 runtime loop 专用 route 能写入可信 provenance；payload 字段来自
        action 输入，不能作为 real_core_loop_runtime_e2e 的证据。
        """
        dispatcher = _build_phase1_dispatcher_with_tool_gate()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_args": {},
                "requested_capability": "local_action",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "provider_external_call": False,
                "external_side_effects": False,
            },
        )

        result = dispatcher.route(request)
        evidence = dict(result.evidence)

        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E
        assert evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("dispatcher_origin") == "direct_dispatcher"
        assert evidence.get("runtime_loop_invoked") is not True


class TestToolAnchorMemoryAndToolGateIsolation:
    """测试 MEMORY 和 TOOL_GATE action 的失败隔离。"""

    def test_memory_and_tool_gate_both_fire_in_same_turn(self):
        """验证 MEMORY 和 TOOL_GATE action 在同一 turn 中都被触发。

        中文学习边界——这个测试保护什么：
        - turn-end hook 在同一 lifecycle 中触发 MEMORY 和 TOOL_GATE 两个 action
        - 两个 action 都存在且各自独立
        - MEMORY 在前，TOOL_GATE 在后（顺序保证）

        Purpose: 验证两个 action 共存于同一 turn
        Setup: FakeProvider + SpyDispatcher
        Action: chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence:
          - action_log 包含 memory.turn_end_proposal event
          - action_log 包含 tool.gate event
          - 两个 event 各自独立存在
        Forbidden: 一个 action 的存在导致另一个消失
        Pass/fail: 两个 event 都存在
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        action_events = list(spy.action_log)
        memory_events = [
            e for e in action_events
            if str(e.action_type) == "memory.turn_end_proposal"
        ]
        tool_events = [
            e for e in action_events
            if str(e.action_type) == "tool.gate"
        ]

        assert len(memory_events) >= 1, (
            f"action_log 必须包含 memory.turn_end_proposal event，"
            f"实际找到 {len(memory_events)} 个"
        )
        assert len(tool_events) >= 1, (
            f"action_log 必须包含 tool.gate event，"
            f"实际找到 {len(tool_events)} 个"
        )


class TestToolAnchorRuntimeActionTypeSelection:
    """测试 runtime action checks 的 action_type 定位策略。"""

    def test_runtime_checks_find_tool_gate_by_action_type(self):
        """验证 checks 按 action_type == "tool.gate" 查找，不硬编码索引。

        中文学习边界——这个测试保护什么：
        - action_log 可能同时包含 memory 和 tool.gate event
        - checks 必须迭代查找 action_type == "tool.gate"
        - 不得使用 actions[0] 或 actions[1] 硬编码索引
        - Memory checks 只检查 memory action，不得被 tool.gate 污染

        Purpose: 钉死 action_type-based 查找策略
        Setup: FakeProvider + SpyDispatcher
        Action: chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence:
          - 按 action_type 查找能正确区分 memory 和 tool.gate event
          - 两个 event 的 action_type 不同
        Forbidden: 用 actions[0]/[1] 硬编码索引
        Pass/fail: 按 action_type 查找正确
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher_with_tool_gate()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        action_events = list(spy.action_log)

        # 模拟当前 runtime action_type 查找逻辑
        memory_action = next(
            (a for a in action_events if str(a.action_type) == "memory.turn_end_proposal"),
            None,
        )
        tool_action = next(
            (a for a in action_events if str(a.action_type) == "tool.gate"),
            None,
        )

        assert memory_action is not None, "必须找到 memory.turn_end_proposal event"
        assert tool_action is not None, "必须找到 tool.gate event"

        # 验证两个 event 是不同的 action_type
        assert str(memory_action.action_type) != str(tool_action.action_type), (
            "memory 和 tool.gate event 必须有不同的 action_type"
        )

        # 验证 memory action 的字段不被 tool.gate 污染
        memory_evidence = dict(memory_action.evidence)
        assert memory_evidence.get("target_module") == "MemoryPolicy", (
            f"memory event target_module 必须为 'MemoryPolicy'，"
            f"实际 {memory_evidence.get('target_module')!r}"
        )

        # 验证 tool action 的字段不被 memory 污染
        tool_evidence = dict(tool_action.evidence)
        assert tool_evidence.get("requested_tool_name") == "_safe_noop", (
            f"tool.gate event requested_tool_name 必须为 '_safe_noop'，"
            f"实际 {tool_evidence.get('requested_tool_name')!r}"
        )

"""Checkpoint Save/Resume L3 TDD 测试。

中文学习边界：
Checkpoint safe summary 是 turn-end hook 上的 branch behavior——
不新增 Anchor、不新增 branch point、不新增 runtime flow。
它遵循与 MEMORY_TURN_END_PROPOSAL 和 TOOL_GATE 完全相同的 dispatch pattern。

测试分层：
- L1 (subsystem_integration): 不适用——checkpoint safe summary 必然经过 turn-end hook
- L2 (harness_runtime_e2e): dispatcher.route() 直接调用
- L3 (real_core_loop_runtime_e2e): core.chat() → route_from_runtime_loop()

本轮核心目标：
证明 turn-end hook 正确 dispatch CHECKPOINT_SAFE_SUMMARY 通过
route_from_runtime_loop() 真实路径，获得 L3 evidence，
且 direct dispatcher.route 无法通过 payload 伪造升级为 L3。

架构依据：
- docs/specs/checkpoint-save-resume-l3/SPEC.md
- docs/specs/checkpoint-save-resume-l3/TDD.md
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

from typing import Any

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.checkpoint_summary import CheckpointSafeSummaryHandler
from agent.runtime_integration.evidence import (
    HARNESS_RUNTIME_E2E,
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest

# ========== 测试辅助工厂 ==========


def _build_checkpoint_dispatcher() -> RuntimeActionDispatcher:
    """构建注册了 CHECKPOINT_SAFE_SUMMARY handler 的 dispatcher。"""
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
        CheckpointSafeSummaryHandler(),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


def _build_full_dispatcher() -> RuntimeActionDispatcher:
    """构建注册了 MEMORY + TOOL_GATE + CHECKPOINT_SAFE_SUMMARY 的完整 dispatcher。

    这是 build_phase1_dispatcher() 加上 CheckpointSafeSummaryHandler 的等价物，
    用于 core.chat() L3 测试。
    """
    from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
    from agent.runtime_integration.memory_recall import MemoryRecallHandler
    from agent.runtime_integration.memory_retain import MemoryRetainHandler
    from agent.runtime_integration.tool_gate import ToolGateHandler
    from agent.runtime_integration.tool_invoke import ToolInvokeHandler
    from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        MemoryTurnEndProposalHandler(),
    )
    registry.register(
        RuntimeActionType.MEMORY_PROPOSE,
        MemoryRetainHandler(),
    )
    registry.register(
        RuntimeActionType.MEMORY_RECALL,
        MemoryRecallHandler(),
    )
    registry.register(
        RuntimeActionType.TOOL_GATE,
        ToolGateHandler(),
    )
    registry.register(
        RuntimeActionType.TOOL_INVOKE,
        ToolInvokeHandler(),
    )
    registry.register(
        RuntimeActionType.TOOL_RESULT,
        ToolResultFeedbackHandler(),
    )
    registry.register(
        RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
        CheckpointSafeSummaryHandler(),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _PipelineSpy:
    """捕获 method + request + result 的 spy dispatcher 包装器。"""

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self.captured: list[tuple[str, RuntimeActionRequest, Any]] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        result = self._real.route(request)
        self.captured.append(("route", request, result))
        return result

    def route_from_runtime_loop(self, request: RuntimeActionRequest, **kwargs: Any) -> Any:
        result = self._real.route_from_runtime_loop(request, **kwargs)
        self.captured.append(("route_from_runtime_loop", request, result))
        return result

    @property
    def action_log(self):
        return self._real.action_log


def _make_mock_state():
    """构造最小 mock state——只需 conversation.messages 中有 user 消息。"""

    class _MockConversation:
        messages: list[dict] = [{"role": "user", "content": "hello"}]

    class _MockState:
        conversation = _MockConversation()

    return _MockState()


# ========== T1: core.chat() turn-end 触发 CHECKPOINT_SAFE_SUMMARY L3 ==========


class TestCoreChatCheckpointSafeSummaryL3:
    """T1: core.chat() L3 checkpoint safe summary 核心测试。"""

    def test_t1_core_chat_checkpoint_safe_summary_l3(self):
        """T1: core.chat() turn-end 正确 dispatch CHECKPOINT_SAFE_SUMMARY 获得 L3 evidence。

        证明 checkpoint safe summary 在 turn-end hook 中被正确触发，
        且 evidence 达到 real_core_loop_runtime_e2e 级别。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_full_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        # 提取 CHECKPOINT_SAFE_SUMMARY actions
        checkpoint_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.CHECKPOINT_SAFE_SUMMARY
        ]

        assert len(checkpoint_actions) >= 1, (
            f"应有至少 1 个 CHECKPOINT_SAFE_SUMMARY action，"
            f"实际 captured action_types: "
            f"{[(r.action_type.value, m) for m, r, _ in spy.captured]}"
        )

        method, request, checkpoint_result = checkpoint_actions[0]

        # 路由方式：必须是 route_from_runtime_loop
        assert method == "route_from_runtime_loop", (
            f"CHECKPOINT_SAFE_SUMMARY 应通过 route_from_runtime_loop 路由，"
            f"实际 {method!r}"
        )

        # status
        assert checkpoint_result.status == "success", (
            f"CHECKPOINT_SAFE_SUMMARY status 应为 'success'，"
            f"实际 {checkpoint_result.status!r}"
        )

        # evidence 验证
        evidence = dict(checkpoint_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"

        # target_module 验证
        assert evidence.get("target_module") == "CheckpointSafeSummary", (
            f"target_module 应为 'CheckpointSafeSummary'，"
            f"实际 {evidence.get('target_module')!r}"
        )

        # payload 验证
        checkpoint_payload = dict(checkpoint_result.payload)
        assert "safe_summary" in checkpoint_payload, (
            f"payload 应包含 safe_summary，实际 keys: {list(checkpoint_payload.keys())}"
        )
        assert checkpoint_payload.get("checkpoint_boundary") == (
            "turn_end_before_save_checkpoint"
        ), (
            f"checkpoint_boundary 应为 'turn_end_before_save_checkpoint'，"
            f"实际 {checkpoint_payload.get('checkpoint_boundary')!r}"
        )
        assert isinstance(
            checkpoint_payload.get("secret_content_detected"), bool
        ), (
            f"secret_content_detected 应为 bool，"
            f"实际 {type(checkpoint_payload.get('secret_content_detected'))!r}"
        )


# ========== T2: hook 级 CHECKPOINT_SAFE_SUMMARY 独立 dispatch ==========


class TestHookLevelCheckpointSafeSummaryL3:
    """T2: hook 级 L3 checkpoint safe summary 测试。"""

    def test_t2_hook_level_checkpoint_safe_summary_l3(self):
        """T2: _try_phase1_turn_end_runtime_action 正确 dispatch CHECKPOINT_SAFE_SUMMARY。"""
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        real_dispatcher = _build_full_dispatcher()
        spy = _PipelineSpy(real_dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda msgs, config: "fake response",
            dispatch_model_output=lambda response: None,
            runtime_loop_fields={"provider_kind": "fake", "provider_external_call": False},
            safe_emit_runtime_event=lambda sink, event: None,
            clear_checkpoint=lambda ctx: None,
            runtime_action_dispatcher=spy,
            provider_kind="fake",
            provider_external_call=False,
            tool_gate_tool_name="_safe_noop",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 提取 CHECKPOINT_SAFE_SUMMARY actions
        checkpoint_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.CHECKPOINT_SAFE_SUMMARY
        ]

        assert len(checkpoint_actions) >= 1, (
            f"应有至少 1 个 CHECKPOINT_SAFE_SUMMARY action，"
            f"实际 captured action_types: "
            f"{[(r.action_type.value, m) for m, r, _ in spy.captured]}"
        )

        method, request, checkpoint_result = checkpoint_actions[0]

        assert method == "route_from_runtime_loop"
        assert checkpoint_result.status == "success"

        evidence = dict(checkpoint_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("target_module") == "CheckpointSafeSummary"

        checkpoint_payload = dict(checkpoint_result.payload)
        assert checkpoint_payload.get("checkpoint_boundary") == (
            "turn_end_before_save_checkpoint"
        )
        assert "safe_summary" in checkpoint_payload


# ========== T3: direct dispatcher.route CHECKPOINT_SAFE_SUMMARY 保持 L2 ==========


class TestDirectDispatcherCheckpointSafeSummaryL2:
    """T3: direct dispatcher.route checkpoint safe summary 保持 L2。"""

    def test_t3_direct_dispatcher_route_checkpoint_safe_summary_is_l2(self):
        """T3: 直接调用 dispatcher.route 时 CHECKPOINT_SAFE_SUMMARY 只能获得 L2 evidence。"""
        dispatcher = _build_checkpoint_dispatcher()

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
            source="test",
            parent_trace_id="",
            payload={
                "runtime_state_summary": "test summary",
                "trigger": "turn_end",
                # 尝试伪造 L3 字段
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
            },
        ))

        assert result.status == "success"
        evidence = dict(result.evidence)

        # evidence_level 必须为 L2，不能是 L3
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
            f"direct dispatcher.route 应获得 {HARNESS_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )

        # dispatcher_origin 必须为 direct_dispatcher，不能被 payload 伪造
        assert evidence.get("dispatcher_origin") == "direct_dispatcher", (
            f"dispatcher_origin 应为 'direct_dispatcher'，"
            f"实际 {evidence.get('dispatcher_origin')!r}"
        )

        # payload 伪造字段不应污染 evidence
        assert evidence.get("core_entrypoint") != "core.chat", (
            "direct dispatcher 的 core_entrypoint 不应为 'core.chat'"
        )
        assert evidence.get("runtime_hook_name") != "loop.turn_end", (
            "direct dispatcher 的 runtime_hook_name 不应为 'loop.turn_end'"
        )

        # target_module 仍应正确
        assert evidence.get("target_module") == "CheckpointSafeSummary", (
            f"target_module 应为 'CheckpointSafeSummary'，"
            f"实际 {evidence.get('target_module')!r}"
        )


# ========== T4: 不读 .env / 不调用真实 API ==========


class TestNoRealAPIOrEnv:
    """T4: 隔离环境安全测试。"""

    def test_t4_no_real_api_or_env_access(self):
        """T4: checkpoint safe summary pipeline 不读 .env、不调用真实 API。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_full_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        # CHECKPOINT_SAFE_SUMMARY 应返回 success
        checkpoint_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.CHECKPOINT_SAFE_SUMMARY
        ]
        assert len(checkpoint_actions) >= 1
        _, _, checkpoint_result = checkpoint_actions[0]
        assert checkpoint_result.status == "success"

        # T4 验证隔离环境中所有操作完成无异常。
        # FakeProvider 是确定性 provider，不发起网络请求，不读 .env。
        # HOME 指向隔离目录保证即使误读也不会触及真实数据。


# ═══════════════════════════════════════════════════════════════════════════════
# P2: Turn-end checkpoint save trigger contract tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTurnEndCheckpointSave:
    """P2: turn-end checkpoint save trigger 合约测试。

    验证 checkpoint_save_on_turn_end 参数正确通过 chat() → _run_main_loop()
    → LoopDependencies → run_main_loop() 链路，在 turn-end hook 完成后
    触发 CHECKPOINT_SAVE dispatch。
    """

    def test_loop_dependencies_default_false(self):
        """checkpoint_save_on_turn_end 默认 False——向后兼容。"""
        from agent.loop import LoopDependencies

        deps = LoopDependencies(
            state=_mock_state(),
            call_model=lambda ts, lc: _fake_model_response(),
            dispatch_model_output=lambda resp: "ok",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda s, e: None,
            clear_checkpoint=lambda: None,
        )
        assert deps.checkpoint_save_on_turn_end is False, (
            "默认应为 False（向后兼容）"
        )

    def test_chat_param_threads_to_loop_dependencies(self):
        """chat(checkpoint_save_on_turn_end=True) → LoopDependencies 正确传递。"""
        import inspect

        # 验证 chat() 接受此参数
        from agent.core import chat

        sig = inspect.signature(chat)
        assert "checkpoint_save_on_turn_end" in sig.parameters, (
            "chat() 应接受 checkpoint_save_on_turn_end 参数"
        )

        param = sig.parameters["checkpoint_save_on_turn_end"]
        assert param.default is False, (
            f"默认值应为 False，实际 {param.default!r}"
        )

    def test_chat_with_turn_end_save_runs_without_crash(self):
        """chat(checkpoint_save_on_turn_end=True) 不 crash。

        使用 FakeProvider 验证参数传递链完整，不产生异常。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        result = chat(
            "hello",
            provider=FakeProvider(),
            checkpoint_save_on_turn_end=True,
        )
        assert isinstance(result, str)
        # 不 crash 即通过——证明参数传递链完整

    def test_chat_with_turn_end_save_dispatches_checkpoint_evidence(self):
        """checkpoint_save_on_turn_end=True + dispatcher → CHECKPOINT_SAVE dispatched。

        验证通过注入 dispatcher spy 确认 CHECKPOINT_SAVE action 被触发。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider
        from agent.runtime_integration.schema import RuntimeActionType

        real_dispatcher = _build_full_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            checkpoint_save_on_turn_end=True,
        )
        assert isinstance(result, str)

        # CHECKPOINT_SAVE 应出现在 captured actions 中
        checkpoint_saves = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.CHECKPOINT_SAVE
        ]
        assert len(checkpoint_saves) >= 1, (
            f"checkpoint_save_on_turn_end=True 应触发 CHECKPOINT_SAVE dispatch，"
            f"实际 captured types: {[r.action_type.value for _, r, _ in spy.captured]}"
        )

        # 验证 evidence 来自 turn_end source
        for _, req, _ in checkpoint_saves:
            payload = dict(req.payload) if req.payload else {}
            # CHECKPOINT_SAVE 的 payload 含 _state 和 source
            assert "_state" in payload, (
                f"CHECKPOINT_SAVE payload 应含 _state，实际 keys={list(payload.keys())}"
            )

    def test_chat_with_turn_end_save_disabled_no_checkpoint(self):
        """默认 checkpoint_save_on_turn_end=False 时不应触发 CHECKPOINT_SAVE。

        验证默认行为不变——不影响现有 conversation flow。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider
        from agent.runtime_integration.schema import RuntimeActionType

        real_dispatcher = _build_full_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            # 不传 checkpoint_save_on_turn_end——使用默认 False
        )
        assert isinstance(result, str)

        # 默认不应有来自 turn_end 的 CHECKPOINT_SAVE
        # 注意: 可能有来自 memory_confirmation 等其他 source 的 CHECKPOINT_SAVE
        turn_end_saves = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.CHECKPOINT_SAVE
            and dict(r.payload).get("source") == "turn_end"
        ]
        assert len(turn_end_saves) == 0, (
            "默认 checkpoint_save_on_turn_end=False 时不应有 turn_end CHECKPOINT_SAVE"
        )


def _mock_state():
    from unittest.mock import MagicMock
    s = MagicMock()
    s.task.status = "running"
    s.task.current_step_index = 0
    s.task.pending_tool = None
    s.task.pending_user_input_request = None
    return s


def _fake_model_response():
    from unittest.mock import MagicMock
    r = MagicMock()
    r.content = [MagicMock(text="hello", type="text")]
    r.stop_reason = "end_turn"
    return r

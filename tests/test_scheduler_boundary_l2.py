"""Scheduler no-consumer boundary evidence — L2, not L3.

锁定以下事实：
1. production chat() 调用不传 action_scheduler → dormant-by-default
2. scheduler injectable but optional
3. registered-not-routed ≠ production-routed → not L3
4. no background execution
5. no consumer → T-SCHED-ROUTE remains BLOCKED_BY_DECISION
"""

import inspect

from agent.action_scheduler import ActionScheduler
from agent.loop import LoopDependencies


class TestSchedulerNoConsumerBoundary:
    """Scheduler no-consumer boundary — 为什么是 L2 而不是 L3。"""

    def test_production_chat_calls_do_not_pass_action_scheduler(self):
        """main.py 的 chat() 调用不传 action_scheduler → dormant-by-default。

        这是 no-consumer blocker 的核心证据：production 代码路径从不创建
        ActionScheduler 实例，也不将它注入 core.chat()。Scheduler 的
        injection seam 存在且可用，但 production 不用它。
        """
        import main as main_mod

        source = inspect.getsource(main_mod)
        chat_calls = source.count("chat(")
        assert chat_calls >= 1, "main.py 应至少有一处 chat() 调用"

        action_scheduler_refs = source.count("action_scheduler")
        assert action_scheduler_refs == 0, (
            f"main.py 不应引用 action_scheduler（发现 {action_scheduler_refs} 次）"
            "—— production 路径不注入 scheduler"
        )

    def test_loop_dependencies_default_action_scheduler_is_none(self):
        """LoopDependencies 默认 action_scheduler=None → 向后兼容，不激活 scheduler。"""
        deps = LoopDependencies(
            state=None,
            call_model=None,
            dispatch_model_output=None,
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda sink, event: None,
            clear_checkpoint=lambda: None,
        )
        assert deps.action_scheduler is None, (
            "默认 action_scheduler 应为 None —— 非激活态"
        )

    def test_scheduler_registered_not_routed(self):
        """ActionScheduler handler 已注册但不 production-routed。

        Handler 在 phase1_hook.py 的 build_phase1_dispatcher() 中注册，
        但 production 调用链 core.chat() → _run_main_loop() 默认
        action_scheduler=None，所以 handler 从不在 production path 中被触发。
        registered ≠ routed。
        """
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

        dispatcher = build_phase1_dispatcher()
        from agent.runtime_integration.schema import RuntimeActionType
        scheduler_types = [
            RuntimeActionType.ACTION_PLAN_START,
            RuntimeActionType.NODE_ENTER,
            RuntimeActionType.NODE_EXIT,
            RuntimeActionType.NODE_FAILURE,
            RuntimeActionType.ACTION_PLAN_COMPLETE,
        ]
        for st in scheduler_types:
            handler = dispatcher._registry.get(st)
            assert handler is not None, f"{st} handler 应已注册"

    def test_scheduler_does_not_create_background_jobs(self):
        """ActionScheduler 不创建 background jobs / threads / processes。"""
        source = inspect.getsource(ActionScheduler)
        forbidden = ["threading", "multiprocessing", "subprocess", "asyncio", "concurrent"]
        for word in forbidden:
            assert word not in source, (
                f"ActionScheduler 不应引用 {word} —— 无 background 执行"
            )

    def test_no_consumer_means_not_l3(self):
        """no active consumer → 不满足 L3 production-routed 判据。

        L3 要求：主路径可用 + production-routed + guardrails + evidence。
        Scheduler 有 guardrails 和 evidence，但缺少 production-routed：
        没有任何代码在 production 中创建 ActionScheduler 并传入 core.chat()。
        这是 BLOCKED_BY_DECISION / no-consumer 的核心原因。
        """
        from agent.core import chat

        sig = inspect.signature(chat)
        default_action_scheduler = sig.parameters.get("action_scheduler")
        assert default_action_scheduler is not None, "chat() 应有 action_scheduler 参数"
        assert default_action_scheduler.default is None, (
            "action_scheduler 默认应为 None —— production 不激活"
        )

    def test_policy_decision_maps_scheduler_async_to_require_approval(self):
        """SCHEDULER_ASYNC → REQUIRE_APPROVAL —— policy gate 存在。"""
        from agent.policy_decision import PolicyActionKind, classify_policy_action

        decision = classify_policy_action(PolicyActionKind.SCHEDULER_ASYNC)
        assert decision.decision_type.value == "require_approval", (
            "SCHEDULER_ASYNC 应映射为 REQUIRE_APPROVAL"
        )

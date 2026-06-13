"""W2-T5 / W2-T6: Legacy path compatibility inventory — characterization tests.

这是 characterization snapshot，不是 no-delete guarantee。
测试记录当前系统的 legacy 路径行为，使未来变更"可见"而非"静默"。

W2-T5: flag-off delegate 路径的 legacy 行为（L1-attempt → inline-local fallback）
W2-T6: handler missing → not_supported → 受控 inline fallback

每条测试必须显式 `monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)`
避免 ambient env 导致 flake。

不在此处测试：
- L1 dead-code retention（plan §8D 明确不加 retention test）
- V0 status taxonomy（复用 test_subagent_v0_failure_taxonomy.py）
- provider failure E2E（计划禁止）
"""

from __future__ import annotations

import pytest

from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

# ══════════════════════════════════════════════════════════════════════════════
# W2-T5: flag-off legacy delegate path characterization
# ══════════════════════════════════════════════════════════════════════════════


class TestW2T5FlagOffLegacyPath:
    """W2-T5：SUBAGENT_V0_ROUTING_ENABLED=off 时的 legacy 路径 characterization。

    flag off 时，delegation 走 L1-attempt → dispatcher 无 L1 handler → fallback inline-local。
    这是 rollback 地板：V0 routing 被禁用时用户仍能得到 local_fake 执行结果。
    """

    def test_flag_off_l1_handler_not_registered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T5a: flag off 时，dispatcher 没有注册 SUBAGENT_DELEGATE_L1 handler。

        L1-attempt 是 dead route（no-op）：dispatcher 返回 not_supported，
        触发 core.py 回退到 _execute_subagent_delegation（inline-local）。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        dispatcher = build_phase1_dispatcher()
        l1_handler = dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_L1)
        assert l1_handler is None, (
            "SUBAGENT_DELEGATE_L1 handler 不应注册（L1 frozen，no-op route）；"
            "这是 inline-local fallback 的前提条件"
        )

    def test_flag_off_l1_route_returns_not_supported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T5b: flag off 时，SUBAGENT_DELEGATE_L1 请求返回 not_supported。

        这是 characterization snapshot：确认 L1 dispatch 的 "no handler" 处置方式。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        dispatcher = build_phase1_dispatcher()
        l1_req = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L1,
            source="legacy-inventory-test",
            parent_trace_id="test-legacy-trace",
            payload={
                "subagent_name": "demo-stat",
                "delegation_goal": "characterize legacy path",
                "delegation_reason": "W2-T5 inventory",
            },
        )
        result = dispatcher.route(l1_req)
        assert result.status == "not_supported", (
            f"L1 route 应返回 not_supported（无 handler）；got {result.status!r}"
        )

    def test_flag_off_l1_route_payload_no_delegate_called(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T5c: L1 route 结果 payload 中 delegate_l1_called 不为 True。

        core.py 读取这个标志决定是否进入渲染路径，falsy → 触发 inline-local fallback。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        dispatcher = build_phase1_dispatcher()
        l1_req = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L1,
            source="legacy-inventory-test",
            parent_trace_id="test-legacy-trace",
            payload={"subagent_name": "demo-stat"},
        )
        result = dispatcher.route(l1_req)
        payload = dict(result.payload) if result.payload else {}
        assert payload.get("delegate_l1_called") is not True, (
            "L1 route 不应报告 delegate_l1_called=True"
            "（无 handler，这是 inline-local fallback 的前提）"
        )

    def test_flag_off_v0_handler_still_registered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T5d: flag off 时，V0 handler 仍注册（但 core.py 未路由到它）。

        这是 architecture snapshot：V0 handler registered but not routed when flag is off。
        V0 routing 由 SUBAGENT_V0_ROUTING_ENABLED flag 控制，默认 off。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        dispatcher = build_phase1_dispatcher()
        v0_handler = dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_V0)
        assert v0_handler is not None, (
            "SUBAGENT_DELEGATE_V0 handler 必须已注册（registered-not-routed 状态）；"
            "flag off 只是 core.py 不路由到它，handler 本身要保留"
        )

    def test_inline_local_fallback_uses_local_fake_execution_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T5e: inline-local fallback 使用 execution_mode='local_fake'。

        这是 local_fake path 的 characterization snapshot。
        local_fake 是 rollback-safe 的执行模式（无实际 LLM 调用），
        验证它仍是 inline-local fallback 的实际执行路径。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        import inspect

        from agent import subagent_inline

        src = inspect.getsource(subagent_inline.execute_subagent_delegation)
        assert 'execution_mode="local_fake"' in src, (
            "execute_subagent_delegation 必须使用 execution_mode='local_fake'"
            "（inline-local fallback marker）"
        )


# ══════════════════════════════════════════════════════════════════════════════
# W2-T6: handler missing → not_supported → controlled inline fallback
# ══════════════════════════════════════════════════════════════════════════════


class TestW2T6HandlerMissingFallback:
    """W2-T6：handler missing → not_supported → 受控 inline fallback 的 characterization。

    复用 G6 断言风格（golden e2e 已验证，此处做 integration 级快照）。
    不重复 test_subagent_v0_failure_taxonomy.py 的 five-way discrimination。
    """

    def test_unregistered_action_returns_not_supported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T6a: 无 handler 的 action → not_supported（G6 行为的 integration 快照）。

        SUBAGENT_DELEGATE_L2 没有注册 handler，dispatcher.route() 必须返回 not_supported。
        这是"controlled fallback"：dispatcher 知道这是无 handler 状态，而非 handler 错误。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        dispatcher = build_phase1_dispatcher()
        l2_req = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L2,
            source="legacy-inventory-test",
            parent_trace_id="test-trace",
            payload={},
        )
        result = dispatcher.route(l2_req)
        assert result.status == "not_supported", (
            f"无 handler 的 action 必须返回 not_supported；got {result.status!r}"
        )

    def test_not_supported_is_distinct_from_handler_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T6b: not_supported 是 dispatcher 级的"无 handler"处置，而非 handler 内错误。

        验证 not_supported 来自 dispatcher（source 是 dispatcher 自身，非 handler）。
        这锁住 not_supported 语义：它只在 handler 缺失时产生，而非 handler 执行失败。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        dispatcher = build_phase1_dispatcher()
        l2_req = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L2,
            source="legacy-inventory-test",
            parent_trace_id="test-trace",
            payload={},
        )
        result = dispatcher.route(l2_req)
        assert result.status == "not_supported"
        # not_supported 时，evidence 应包含 "no handler registered" 原因
        # 而非 handler 执行错误（handler 从未被调用）
        evidence = dict(result.evidence) if result.evidence else {}
        reason = str(evidence.get("reason", ""))
        has_no_handler_signal = (
            "no handler" in reason
            or "not registered" in reason
            or "unsupported" in str(evidence.get("status", ""))
        )
        assert has_no_handler_signal, (
            f"not_supported 的 evidence 应包含 'no handler registered' 信号，"
            f"证明 handler 从未被调用；got evidence={evidence!r}"
        )

    def test_pre_loop_seam_exists_in_core(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T6c: pre-loop seam `_dispatch_or_fallback_delegation` 仍存在于 core.py。

        这是 inventory 的 AST 快照：pre-loop seam 是 rollback-safe 路径的关键组件，
        本测试确认它在 core.py 中是可找到的函数定义（不做行为验证，只做存在性快照）。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        import ast
        from pathlib import Path

        core_path = Path(__file__).parent.parent.parent / "agent" / "core.py"
        core_src = core_path.read_text(encoding="utf-8")
        tree = ast.parse(core_src)

        seam_found = any(
            isinstance(node, ast.FunctionDef) and node.name == "_dispatch_or_fallback_delegation"
            for node in ast.walk(tree)
        )
        assert seam_found, (
            "_dispatch_or_fallback_delegation 必须在 core.py 中定义（pre-loop seam；不可删）"
        )

    def test_inline_local_fallback_path_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T6d: `execute_subagent_delegation` 函数（inline-local fallback 入口）仍存在。

        这是 rollback path 的存在性快照，不是 no-delete guarantee。
        如果未来 V0 routing 完全接管，此测试可与 rollback path 一起删除，
        但删除前必须确认 rollback path 不再需要。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        from agent import subagent_inline
        assert callable(getattr(subagent_inline, "execute_subagent_delegation", None)), (
            "subagent_inline.execute_subagent_delegation 必须是可调用函数"
            "（inline-local fallback 入口）"
        )

    def test_local_fake_path_characterization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T6e: local_fake path 是 inline-local fallback 的实际执行模式（characterization）。

        local_fake = 不调用真实 LLM，使用 registry 中的 descriptor 执行 fake response。
        这是 rollback-safe 的核心：flag off 或 handler missing 时，用户仍得到响应。
        """
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

        from pathlib import Path
        inline_path = Path(__file__).parent.parent.parent / "agent" / "subagent_inline.py"
        core_src = inline_path.read_text(encoding="utf-8")
        assert "local_fake" in core_src, (
            "subagent_inline.py 必须包含 local_fake execution_mode（inline-local fallback marker）"
        )

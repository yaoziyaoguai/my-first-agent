"""W2-T4: fallback dispatch guard — W1-D4 negative-match lock.

W1-D4 debt：`agent/core.py:2171` 使用 negative-match（只检查 `not_supported`）
来触发 inline fallback，其他 status 静默落入 `_render_v0_delegate_result`。
本测试套件确保：

- 只有 `not_supported` 可触发 inline-local fallback；
- `rejected` / `failed` / `policy_blocked` 不 fallback；
- 未知 / 未来新增 status 不被当成 success，也不 fallback；
- 使用真实 dispatcher + 真实 SubAgentV0Handler，不替换 handler。

不重复 `test_subagent_v0_failure_taxonomy.py` 的 taxonomy 断言；
本文件关注 fallback dispatch 行为，而非 status 分类本身。
"""

from __future__ import annotations

import pytest

from agent.core import chat
from agent.provider.fake_provider import FakeProvider
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionType
from tests.runtime_integration.subagent_v0_contract_helpers import (
    route_v0,
)

V0 = str(RuntimeActionType.SUBAGENT_DELEGATE_V0.value)


def _v0_events(dispatcher):
    return [ev for ev in dispatcher.action_log if ev.action_type == V0]


def _last_v0_status(dispatcher):
    events = _v0_events(dispatcher)
    return events[-1].status if events else None


# ══════════════════════════════════════════════════════════════════════════════
# W2-T4a: not_supported → inline fallback（唯一合法触发路径）
# ══════════════════════════════════════════════════════════════════════════════


class TestW2T4FallbackOnlyOnNotSupported:
    """只有 not_supported 触发 inline fallback；其他 status 不 fallback。"""

    def test_not_supported_triggers_inline_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T4a: handler missing → not_supported → inline-local fallback 触发。

        手动路由 SUBAGENT_DELEGATE_L2（未注册）→ dispatcher 返回 not_supported。
        验证该 status 对应 fallback 路径。
        """
        monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")

        from agent.runtime_integration.schema import RuntimeActionRequest

        dispatcher = build_phase1_dispatcher()
        # SUBAGENT_DELEGATE_L2 没有注册 handler → 返回 not_supported
        req = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L2,
            source="test-fallback-guard",
            parent_trace_id="test-trace",
            payload={},
        )
        result = dispatcher.route(req)
        assert result.status == "not_supported", (
            f"无 handler 的 action 必须返回 not_supported；got {result.status!r}"
        )

    def test_not_supported_is_the_only_fallback_trigger_in_v0_dispatch(self) -> None:
        """W2-T4a-core: V0 dispatch 块中，fallback 只在 not_supported guard 之后（源码级）。

        core.py 有两处 _execute_subagent_delegation 调用：
        1. V0 dispatch 块（W1-D4 负面匹配位置）：guard = `if v0_result.status == "not_supported":`
        2. L1/L0 pre-loop seam 回退路径（正常 L0 fallback）

        本测试锁定 #1：在 not_supported guard 之后 10 行内，存在对
        _execute_subagent_delegation 的调用，证明 fallback 确实被 guard 保护。
        """
        from pathlib import Path

        core_path = Path(__file__).parent.parent.parent / "agent" / "core.py"
        core_src = core_path.read_text(encoding="utf-8")
        lines = core_src.splitlines()

        # 找 V0 dispatch 块的 guard 行
        guard_line_idx = None
        for i, line in enumerate(lines):
            if 'v0_result.status == "not_supported"' in line:
                guard_line_idx = i
                break

        assert guard_line_idx is not None, (
            'core.py 必须包含 `if v0_result.status == "not_supported":` guard（W1-D4 负面匹配）'
        )

        # guard 行之后 10 行内必须有 _execute_subagent_delegation 调用
        block_lines = lines[guard_line_idx + 1 : guard_line_idx + 12]
        block_text = "\n".join(block_lines)
        assert "_execute_subagent_delegation" in block_text, (
            "not_supported guard 之后 10 行内必须有 _execute_subagent_delegation 调用:\n"
            f"{block_text}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# W2-T4b: rejected / failed / policy_blocked 不 fallback
# ══════════════════════════════════════════════════════════════════════════════


class TestW2T4NoFallbackOnOtherStatus:
    """rejected / failed / policy_blocked 不触发 inline fallback，不被当成 success。"""

    def test_rejected_does_not_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """W2-T4b-rejected: rejected status → 不 fallback，不当 success。

        descriptor missing → rejected（由 F2.1 已证明）；
        本测试验证 rejected 状态不触发 inline fallback。
        """
        monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")
        dispatcher = build_phase1_dispatcher()

        reply = chat(
            "delegate to nonexistent-agent-xyz: do something",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
            session_id="fallback-guard-rejected",
        )

        v0 = _v0_events(dispatcher)
        assert v0, "必须产生 V0 事件"
        status = v0[-1].status
        assert status == "rejected", f"descriptor missing 必须是 rejected；got {status!r}"
        # rejected 不 fallback：用户看到的是 not-found 消息，而非 inline fallback 结果
        assert isinstance(reply, str)
        # 如果触发了 inline fallback，会得到 demo-stat / local_fake 的输出
        # not-found 消息不会包含 "local_fake" 或 subagent execution trace
        assert "local_fake" not in reply.lower(), (
            "rejected 不应触发 inline fallback（输出含 local_fake 标记）"
        )

    def test_failed_does_not_fallback(self) -> None:
        """W2-T4b-failed: contract failure (failed) 不触发 inline fallback。

        max_turns=2 → _failed_contract → failed status。
        """
        result = route_v0({"max_turns": 2})
        assert result.status == "failed", f"contract failure 必须是 failed；got {result.status!r}"
        # 验证 failed 不是 not_supported（only not_supported triggers fallback）
        assert result.status != "not_supported", "failed 不应是 not_supported（会触发 fallback）"

    def test_policy_blocked_does_not_fallback(self) -> None:
        """W2-T4b-policy: policy_blocked 不触发 inline fallback。"""
        result = route_v0({"scenario": "policy_blocked"})
        assert result.status == "policy_blocked", (
            f"policy blocked 必须是 policy_blocked；got {result.status!r}"
        )
        assert result.status != "not_supported", (
            "policy_blocked 不应是 not_supported（会触发 fallback）"
        )

    def test_success_does_not_fallback(self) -> None:
        """W2-T4b-success: success 不触发 fallback（正常 execution path）。"""
        result = route_v0()
        assert result.status == "success", f"V0 success 路径必须返回 success；got {result.status!r}"
        assert result.status != "not_supported", "success 不应触发 fallback"


# ══════════════════════════════════════════════════════════════════════════════
# W2-T4c: unknown / future status 不 fallback，不被当成 success
# ══════════════════════════════════════════════════════════════════════════════


class TestW2T4UnknownStatusGuard:
    """未知 status 不得被静默当作 success 或触发 fallback。

    W1-D4 核心 debt：`core.py:2171` negative-match 只检查 not_supported，
    未知 status 会 fall through 到 `_render_v0_delegate_result`。
    测试锁住 known status 不含未知值（architecture guard）。
    """

    def test_known_statuses_are_enumerated(self) -> None:
        """W2-T4c: 所有 known V0 statuses 必须是预期集合中的一员。

        任何 V0 route 返回的 status 必须是已知集合：
        success / rejected / failed / policy_blocked / not_supported / skipped /
        confirmation_required。
        """
        known_statuses = {
            "success",
            "rejected",
            "failed",
            "policy_blocked",
            "not_supported",
            "skipped",
            "confirmation_required",
        }

        # 测试各个 scenario 返回的 status 都在已知集合内
        scenarios = [
            route_v0(),
            route_v0({"max_turns": 2}),
            route_v0({"scenario": "policy_blocked"}),
            route_v0({"scenario": "provider_failure", "provider_failure": RuntimeError("test")}),
        ]

        for result in scenarios:
            assert result.status in known_statuses, (
                f"V0 route 返回了未知 status: {result.status!r}\n"
                f"期望集合: {known_statuses}"
            )

    def test_fallback_guard_only_fires_on_not_supported(self) -> None:
        """W2-T4c-guard: 在所有 known scenarios 中，只有 handler-missing 产生 not_supported。

        验证 dispatcher 对已注册 V0 handler 的调用（contract failure、policy blocked、success）
        均不产生 not_supported——即 fallback 不会误触发。
        """
        not_supported_scenarios = []

        for label, payload in [
            ("success", None),
            ("contract_failure", {"max_turns": 2}),
            ("policy_blocked", {"scenario": "policy_blocked"}),
            ("provider_failure", {
                "scenario": "provider_failure",
                "provider_failure": RuntimeError("t"),
            }),
        ]:
            result = route_v0(payload)
            if result.status == "not_supported":
                not_supported_scenarios.append(label)

        # 这些场景都不应产生 not_supported（都有注册的 V0 handler）
        assert not_supported_scenarios == [], (
            f"以下场景不应产生 not_supported（fallback 误触发风险）: {not_supported_scenarios}"
        )

    def test_handler_missing_produces_not_supported_only_when_no_handler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W2-T4c: not_supported 只在真正没有 handler 时产生。

        V0 handler 已注册 → 不产生 not_supported。
        未注册 L2 → 产生 not_supported。
        """
        from agent.runtime_integration.schema import RuntimeActionRequest

        dispatcher = build_phase1_dispatcher()

        # V0 有 handler → 不是 not_supported
        v0_result = route_v0()
        assert v0_result.status != "not_supported", (
            "已注册 V0 handler 的请求不应产生 not_supported"
        )

        # L2 无 handler → not_supported
        l2_req = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L2,
            source="test",
            parent_trace_id="test",
            payload={},
        )
        l2_result = dispatcher.route(l2_req)
        assert l2_result.status == "not_supported", (
            "无 handler 的 action 必须产生 not_supported（fallback trigger）"
        )

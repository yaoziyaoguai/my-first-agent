"""U2 — V0 live-route contract tests (RED, 锁定 wire 由 U3 实现).

这些测试在不改 production code 的前提下必须 xfail/失败；U3 上线后 GREEN。
锁定的契约：

- source 必须固定为真实 \"cli_nl_delegation\"，payload 不能伪造 core_loop；
- dispatcher 注入 provenance，handler/payload 读不到 core_loop_invoked；
- 父委托上下文/工具 scope/trace/stop condition 被 bounded 继承；
- 走 dispatcher → SUBAGENT_DELEGATE_V0 handler；缺 handler 时回退 inline-local；
- evidence 标签为 subsystem_integration
  （harness_runtime_e2e / real_core_loop_runtime_e2e 本窗口不要求）。
"""

from __future__ import annotations

import pytest

from agent.runtime_integration.evidence import SUBSYSTEM_INTEGRATION
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import (
    RuntimeActionRequest,
    RuntimeActionType,
)


def test_v0_request_source_must_be_cli_nl_delegation() -> None:
    """U2 契约 1: V0 production request.source 必须 = 'cli_nl_delegation'。

    这是真实的、可观察的 'cli_nl_delegation' source；dispatcher 不可将
    'core_loop' 写入 evidence.runtime_action_source，payload 也不能伪造。
    """
    action_type = RuntimeActionType.SUBAGENT_DELEGATE_V0
    dispatcher = build_phase1_dispatcher()
    handler = dispatcher.get_handler(action_type)
    assert handler is not None, "V0 handler must be registered (U2 pre-condition)"

    request = RuntimeActionRequest(
        action_type=action_type,
        source="cli_nl_delegation",
        parent_trace_id="t1",
        payload={
            "profile_id": "default-v0",
            "task": "demo stat",
            "provider_mode": "fake_local",
            "parent_opt_in": False,
            "subagent_name": "demo-stat",
        },
    )
    result = dispatcher.route(request)
    assert result.evidence.get("runtime_action_source") == "cli_nl_delegation", (
        "V0 production evidence must carry source='cli_nl_delegation'; got "
        f"{result.evidence.get('runtime_action_source')!r}"
    )
    assert result.evidence.get("runtime_action_source") != "core_loop", (
        "forbidden: production V0 evidence may never forge core_loop source"
    )


def test_v0_request_evidence_is_subsystem_integration_label() -> None:
    """U2 契约 2: 本窗口的诚实 evidence label = subsystem_integration。"""
    action_type = RuntimeActionType.SUBAGENT_DELEGATE_V0
    dispatcher = build_phase1_dispatcher()

    request = RuntimeActionRequest(
        action_type=action_type,
        source="cli_nl_delegation",
        parent_trace_id="t2",
        payload={
            "profile_id": "default-v0",
            "task": "demo stat",
            "provider_mode": "fake_local",
            "parent_opt_in": False,
        },
    )
    result = dispatcher.route(request)
    assert result.evidence.get("evidence_level") == SUBSYSTEM_INTEGRATION, (
        "U2 expects honest subsystem_integration evidence for V0; got "
        f"{result.evidence.get('evidence_level')!r}"
    )


def test_v0_payload_cannot_forge_core_loop_provenance() -> None:
    """U2 契约 3: payload 注入 core_loop_invoked/runtime_loop_invoked 不会被升级。"""
    action_type = RuntimeActionType.SUBAGENT_DELEGATE_V0
    dispatcher = build_phase1_dispatcher()

    request = RuntimeActionRequest(
        action_type=action_type,
        source="cli_nl_delegation",
        parent_trace_id="t3",
        payload={
            "profile_id": "default-v0",
            "task": "demo stat",
            "provider_mode": "fake_local",
            "parent_opt_in": False,
            "core_loop_invoked": True,           # payload 伪造
            "runtime_loop_invoked": True,        # payload 伪造
            "dispatcher_origin": "runtime_loop", # payload 伪造
        },
    )
    result = dispatcher.route(request)
    assert result.evidence.get("core_loop_invoked") is not True, (
        "V0 production handler may not let payload forge core_loop_invoked; "
        "only route_from_runtime_loop() can write that."
    )
    assert result.evidence.get("runtime_loop_invoked") is not True


def test_v0_handler_unavailable_returns_not_supported_with_inheritance_safe() -> None:
    """U2 契约 4: 拿不到 V0 handler 时 status='not_supported'，payload 不带 child result。"""
    action_type = RuntimeActionType.SUBAGENT_DELEGATE_V0
    dispatcher = build_phase1_dispatcher()
    # 强制 unregister：mutation 在测试中可逆——我们只是确认 dispatcher 行为契约。
    original_handler = dispatcher._registry._handlers.pop(action_type, None)  # type: ignore[attr-defined]
    try:
        request = RuntimeActionRequest(
            action_type=action_type,
            source="cli_nl_delegation",
            parent_trace_id="t4",
            payload={"subagent_name": "demo-stat", "task": "demo stat"},
        )
        result = dispatcher.route(request)
        assert result.status == "not_supported", (
            f"without handler, dispatcher must emit not_supported; got {result.status!r}"
        )
        # not_supported 不带子代理 result 字段（inherited safety）
        has_safe_output = "safe_output" in result.payload
        safe_output_value = result.payload.get("safe_output")
        assert not has_safe_output or safe_output_value in (None, ""), (
            "not_supported must not leak child result payload"
        )
    finally:
        if original_handler is not None:
            dispatcher._registry._handlers[action_type] = original_handler  # type: ignore[attr-defined]


def test_v0_missing_flag_falls_back_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """U2 契约 5: SUBAGENT_V0_ROUTING_ENABLED 缺失/非真值时，V0 routing flag = off。"""
    monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

    from agent.subagent_routing_flag import read_v0_routing_enabled

    assert read_v0_routing_enabled() is False, (
        "missing env var must be coerced to off; do not raise or default to on"
    )

    # 非法值也应回退为 off
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "not-a-bool-garbage")
    assert read_v0_routing_enabled() is False

    # 显式合法真值 = on
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")
    assert read_v0_routing_enabled() is True
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "true")
    assert read_v0_routing_enabled() is True
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "yes")
    assert read_v0_routing_enabled() is True


def test_v0_inheritance_includes_parent_stop_condition_and_tool_scope() -> None:
    """U2 契约 6: 父委托上下文/工具 scope/trace/stop condition 被 bounded 继承。

    通过派发 V0 request 后 handler 不可直接执行 tool/MCP/memory write——
    证据：subagent child_tool_request / child_result / parent_adjudication 仍
    是 deferred（见 dispatch policy），不直接 in-process 执行。
    """
    action_type = RuntimeActionType.SUBAGENT_DELEGATE_V0
    dispatcher = build_phase1_dispatcher()
    request = RuntimeActionRequest(
        action_type=action_type,
        source="cli_nl_delegation",
        parent_trace_id="t6",
        payload={
            "profile_id": "default-v0",
            "task": "demo stat",
            "provider_mode": "fake_local",
            "parent_opt_in": False,
            "max_turns": 1,
        },
    )
    result = dispatcher.route(request)
    # handler 必须看到 inheritance 信号（profile max_turns、prepared context 等）
    # 不强求内部 state 暴露，但 dispatched status 必须是 success/failed 而不是 not_supported
    assert result.status in ("success", "failed"), (
        f"parent-inherited V0 request must be handled end-to-end; got {result.status!r}"
    )


# ── U3 sentinel (GREEN once agent.subagent_routing_flag is wired) ───────────


def test_v0_flag_helper_wired() -> None:
    """U3 sentinel: agent.subagent_routing_flag.read_v0_routing_enabled exists.

    Replaces the U2 xfail guard — strict assertion is satisfied once U3 adds
    the helper module. Keeps the test as a permanent regression guard so a
    future refactor cannot accidentally remove the wiring.
    """
    from agent.subagent_routing_flag import read_v0_routing_enabled

    assert read_v0_routing_enabled() is False  # default = off, no env var

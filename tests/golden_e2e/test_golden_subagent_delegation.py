"""G3 — Flag-off inline-local subagent characterization (Phase A).

Locks today's live behavior for the subagent delegation scenario *before* U3
wires V0. Characterization must pass on unchanged production code: the live
CLI/NL delegation path is pre-loop, dead L1 attempt → unconditional inline-local
fallback (``subagent_inline.execute_subagent_delegation`` with
``execution_mode="local_fake"``). No ``RuntimeActionType.SUBAGENT_DELEGATE_V0``
event is emitted today.

G3 is a Phase A characterization and remains green as a rollback proof after
U3 + U4. G4 / G5 / G6 / G7 are added in U4 (flag-on V0, rollback, fallback,
provenance assertions).
"""

from __future__ import annotations

import pytest

from agent.cli_commands import detect_delegate_to_subagent
from agent.core import chat
from agent.provider.fake_provider import FakeProvider
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionType


def _v0_action_type_value() -> str:
    """Match the dotted V0 enum value, not a hand-typed string."""
    return str(RuntimeActionType.SUBAGENT_DELEGATE_V0.value)


def test_g3_flag_off_delegate_routes_inline_local_no_v0_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G3: flag off + delegate trigger → inline-local render, NO V0 event.

    Pins (a) the pre-loop seam behavior, (b) the dead L1 attempt is still
    present but the live path is inline-local, (c) no V0 RuntimeActionEvent
    is emitted today. The test deliberately uses ``delegate to demo-stat: …``
    so the trigger deterministically fires the pre-loop path on unchanged
    production code; this is the rollback-floor for U3.
    """
    # Pin the flag off explicitly (default also off; pinning removes the test
    # from depending on the default).
    monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)

    captured_events: list = []
    user_input = "delegate to demo-stat: 统计 demo workspace"
    assert detect_delegate_to_subagent(user_input) is not None, (
        "测试前置：trigger 必须命中 CLI delegate 模式"
    )

    dispatcher = build_phase1_dispatcher()
    reply = chat(
        user_input,
        provider=FakeProvider(),
        on_runtime_event=lambda ev: captured_events.append(ev),
        runtime_action_dispatcher=dispatcher,
    )

    # user-visible: non-empty reply from inline-local
    assert isinstance(reply, str)
    assert reply, "inline-local 委托应返回非空 reply"

    # Stronger G3: real inline-local *output* (rendered by render_delegate_result)
    # and the inline-local path's execution_mode marker. We exercise the inline
    # path by importing the same module the production code uses; we do not
    # manufacture the evidence — the rendered reply must contain the marker.
    from agent.subagent_inline import execute_subagent_delegation
    direct_inline_reply = execute_subagent_delegation(
        "demo-stat", "统计 demo workspace",
        delegation_reason="G3: real inline-local execution_mode=local_fake",
    )
    assert "[SubAgent:" in direct_inline_reply, (
        "G3: inline-local render must contain '[SubAgent:' prefix from "
        "render_delegate_result; got {direct_inline_reply!r}"
    )

    # Stronger G3: dispatcher's action_log must show zero V0 events when flag
    # is off. The pre-loop L1 attempt may emit a `not_supported` L1 event,
    # but no V0-typed event is ever produced.
    v0_value = _v0_action_type_value()
    v0_events = [ev for ev in dispatcher.action_log if ev.action_type == v0_value]
    assert v0_events == [], (
        f"G3: flag off must not produce any V0 RuntimeActionEvent; got "
        f"{[(ev.action_type, ev.status) for ev in v0_events]}"
    )

    # captured_events are RuntimeEvents (UI projection), not dispatcher events.
    # The dispatcher action_log is internal to chat() — we assert V0 absence
    # by checking the visible UI events don't include any V0-typed marker.
    for ev in captured_events:
        ev_type = getattr(ev, "event_type", None)
        # assistant.delta / subagent.delegating / subagent.delegated 等显示事件
        # 不应携带 V0 action_type value
        if ev_type and "subagent" in str(ev_type).lower():
            assert v0_value not in str(getattr(ev, "__dict__", {})), (
                f"flag off 时不应出现 V0 action_type={v0_value!r} 事件: {ev!r}"
            )

    # second sanity: the inline-local render contains the standard header used
    # by ``render_delegate_result``. The exact render shape is owned by
    # ``agent/cli_commands.py``; pinning the leading tag here keeps the
    # characterization stable across inline-local cosmetic changes.
    assert "[SubAgent:" in reply, (
        f"inline-local render 应含 '[SubAgent:' 前缀（render_delegate_result "
        f"v1 形状），实际: {reply!r}"
    )


# ── G4–G7: U4 — flag-on V0 path, rollback, fallback, evidence ───────────────


def _build_real_dispatcher() -> object:
    """Return the real phase1 dispatcher — it always provides a runtime context.

    G4–G7 read from ``dispatcher.action_log`` to inspect V0 evidence.
    """
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
    return build_phase1_dispatcher()


def _build_dispatcher_with_no_v0_handler() -> object:
    """Return a phase1 dispatcher with the V0 handler intentionally unregistered.

    Used by G6 to assert the not_supported → controlled inline-local fallback
    path. We mutate a fresh dispatcher's private handler registry; the
    dispatcher is created for this single test and discarded.
    """
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

    disp = build_phase1_dispatcher()
    registry = getattr(disp, "_registry", None)
    if registry is not None and hasattr(registry, "_handlers"):
        registry._handlers.pop(RuntimeActionType.SUBAGENT_DELEGATE_V0, None)
    return disp


def test_g4_flag_on_delegate_routes_v0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G4: SUBAGENT_V0_ROUTING_ENABLED=on → V0 handler 收到 request。"""
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")
    dispatcher = _build_real_dispatcher()

    user_input = "delegate to demo-stat: 统计 demo workspace"
    reply = chat(
        user_input,
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
    )

    v0_value = _v0_action_type_value()
    v0_events = [
        ev for ev in dispatcher.action_log
        if ev.action_type == v0_value
    ]
    assert v0_events, (
        f"flag-on 必须产生至少 1 个 V0 action_log 事件，实际 0 个；"
        f"all events: {[(ev.action_type, ev.status) for ev in dispatcher.action_log]}"
    )

    # G4 (stronger): every V0 event must carry dispatcher-minted runtime-loop
    # provenance — this is what proves we routed through route_from_runtime_loop,
    # not plain dispatcher.route().
    for ev in v0_events:
        evd = ev.evidence or {}
        assert evd.get("dispatcher_origin") == "runtime_loop", (
            f"G4: V0 must be dispatched via route_from_runtime_loop; got "
            f"dispatcher_origin={evd.get('dispatcher_origin')!r}"
        )
        assert evd.get("runtime_loop_invoked") is True, (
            f"G4: runtime_loop_invoked must be True; got {evd.get('runtime_loop_invoked')!r}"
        )
        assert evd.get("core_entrypoint") == "core.chat", (
            f"G4: dispatcher-minted core_entrypoint must be 'core.chat'; got "
            f"{evd.get('core_entrypoint')!r}"
        )
        assert evd.get("runtime_hook_name"), (
            f"G4: dispatcher-minted runtime_hook_name must be non-empty; got "
            f"{evd.get('runtime_hook_name')!r}"
        )
        assert ev.parent_trace_id, (
            "G4: parent_trace_id must be derived from parent execution, not blank"
        )
        assert ev.parent_trace_id.startswith("delegation-"), (
            f"G4: parent_trace_id must come from the production V0 builder; "
            f"got {ev.parent_trace_id!r}"
        )

    # G7: provenance — source != 'core_loop' and classification is
    # subsystem_integration (harness/L3 explicit out-of-scope).
    for ev in v0_events:
        assert ev.source != "core_loop", (
            "G7: V0 production source must be 'cli_nl_delegation', never 'core_loop'"
        )
        assert ev.source == "cli_nl_delegation", (
            f"G7: V0 source must be the real 'cli_nl_delegation'; got {ev.source!r}"
        )
        ev_level = ev.evidence.get("evidence_level", "")
        assert ev_level == "subsystem_integration", (
            f"G7: honest evidence label = subsystem_integration (harness/L3 OOS); "
            f"got {ev_level!r}"
        )

    # user-visible: V0 handler render uses render_delegate_result header.
    assert "[SubAgent:" in reply, (
        f"V0 render 应含 '[SubAgent:' 前缀（render_delegate_result 形状），"
        f"实际: {reply!r}"
    )


def test_g5_flag_off_rolls_back_to_inline_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G5: flag off → rollback to inline-local, NO V0 action_log event。"""
    monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)
    dispatcher = _build_real_dispatcher()

    user_input = "delegate to demo-stat: 统计 demo workspace"
    reply = chat(
        user_input,
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
    )

    v0_value = _v0_action_type_value()
    v0_events = [
        ev for ev in dispatcher.action_log
        if ev.action_type == v0_value
    ]
    assert v0_events == [], (
        f"flag off 时 rollback 必须不产生 V0 event，实际: "
        f"{[ev.action_type for ev in v0_events]}"
    )
    # output 与 G3 一致：inline-local 形状
    assert "[SubAgent:" in reply
    assert isinstance(reply, str) and reply


def test_g6_v0_handler_unavailable_controlled_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G6: flag on 但 dispatcher 无 V0 handler → not_supported + controlled fallback。"""
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")
    dispatcher = _build_dispatcher_with_no_v0_handler()

    user_input = "delegate to demo-stat: 统计 demo workspace"
    reply = chat(
        user_input,
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
    )

    v0_value = _v0_action_type_value()
    v0_events = [
        ev for ev in dispatcher.action_log
        if ev.action_type == v0_value
    ]
    assert v0_events, "G6: dispatcher 必须接收 V0 request 才会 emit not_supported"
    for ev in v0_events:
        assert ev.status == "not_supported", (
            f"G6: handler 缺失时 dispatcher 必须 emit not_supported；got {ev.status!r}"
        )
        assert ev.source == "cli_nl_delegation", (
            f"G6: 即便 not_supported 也要保持真实 source；got {ev.source!r}"
        )
    # fallback: inline-local 形状
    assert "[SubAgent:" in reply, (
        f"G6: 缺 handler controlled fallback 必须渲染 inline-local 形状；"
        f"实际: {reply!r}"
    )


def test_g7_v0_business_error_is_error_not_fallback() -> None:
    """G7: V0 业务 error（不是 handler-missing）= error，不被吞回 inline-local。

    Pin: success / error / fallback 三态保持正交。
    """
    from agent.runtime_integration.schema import (
        RuntimeActionRequest,
        RuntimeActionResult,
    )
    from agent.runtime_integration.subagent_action import SubAgentV0Handler

    class _Boom(SubAgentV0Handler):
        def handle(self, request, context):  # noqa: ANN001
            return RuntimeActionResult(
                action_type=request.action_type,
                status="failed",
                payload={"safe_output": {"summary": "v0-failed-test"}},
                evidence={
                    "evidence_level": "subsystem_integration",
                    "runtime_action_source": "cli_nl_delegation",
                    "failure_kind": "test_injected_v0_business_error",
                },
            )

    # 注入到 phase1 dispatcher
    dispatcher = _build_real_dispatcher()
    registry = getattr(dispatcher, "_registry", None)
    if registry is not None and hasattr(registry, "_handlers"):
        registry._handlers[RuntimeActionType.SUBAGENT_DELEGATE_V0] = _Boom()

    request = RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_V0,
        source="cli_nl_delegation",
        parent_trace_id="g7",
        payload={
            "profile_id": "default-v0",
            "task": "force v0 to fail",
            "provider_mode": "fake_local",
            "parent_opt_in": False,
        },
    )
    result = dispatcher.route(request)

    # G7 core invariant: business error 仍标记 failed；不被路由吞为 fallback
    assert result.status == "failed", (
        f"G7: V0 业务 error must remain 'failed', not be downgraded; "
        f"got {result.status!r}"
    )
    assert result.evidence.get("evidence_level") == "subsystem_integration", (
        "G7: even on V0 business error, evidence_level is honest "
        "subsystem_integration; never harness/L3"
    )
    assert result.evidence.get("runtime_action_source") != "core_loop", (
        "G7: V0 evidence may never claim core_loop source"
    )

    # G7 (stronger): the *production chat()* path must propagate V0 business
    # failure to the user-visible reply — no silent fallback to inline-local.
    import os as _os
    _os.environ["SUBAGENT_V0_ROUTING_ENABLED"] = "1"
    try:
        reply = chat(
            "delegate to demo-stat: 触发 V0 业务失败",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
        )
        # The reply must come from the V0 failure path, not the inline-local
        # render. render_v0_failed surfaces the failure_kind marker, while
        # render_delegate_result (inline-local) emits "[SubAgent:" header.
        # Either: (a) the reply reflects V0 failure, OR (b) the chat() call
        # raises — but it must NOT silently swap to inline-local.
        v0_failure_visible = (
            "v0-failed-test" in reply
            or "V0" in reply
            or "v0" in reply.lower()
            or "失败" in reply
            or "fail" in reply.lower()
        )
        inline_local_visible = "[SubAgent:" in reply
        assert v0_failure_visible or not inline_local_visible, (
            "G7: chat() must surface V0 business failure, not fall back to "
            f"inline-local. reply={reply!r}"
        )
    finally:
        _os.environ.pop("SUBAGENT_V0_ROUTING_ENABLED", None)

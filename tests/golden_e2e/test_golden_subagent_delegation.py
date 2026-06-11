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

    reply = chat(
        user_input,
        provider=FakeProvider(),
        on_runtime_event=lambda ev: captured_events.append(ev),
    )

    # user-visible: non-empty reply from inline-local
    assert isinstance(reply, str)
    assert reply, "inline-local 委托应返回非空 reply"

    # On-runner evidence: today no V0 RuntimeActionEvent is emitted because the
    # live path is inline-local, which uses display events only. The pre-loop
    # dispatcher is invoked for the L1 attempt (which is dead — handler
    # unregistered), so action_log may carry a `not_supported` L1 event, but
    # never a V0-typed event.
    v0_value = _v0_action_type_value()
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

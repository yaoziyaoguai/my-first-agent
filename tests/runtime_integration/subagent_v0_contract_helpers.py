"""Test-only helpers for Sub-agent v0 RED guardrails.

These helpers are not production API. They let RED tests target the future v0
RuntimeAction route while making the current pre-U3 missing-contract failure
explicit and easy to remove when U3 adds the v0 action and handler.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

V0_MISSING_REASON = "SubAgentV0 contract not implemented yet"


class MissingSubAgentV0Contract(RuntimeError):  # noqa: N818
    """测试专用异常：只表示 v0 RuntimeAction contract 尚未落地。"""


def v0_action_type() -> RuntimeActionType:
    try:
        return RuntimeActionType.SUBAGENT_DELEGATE_V0
    except AttributeError as exc:
        raise MissingSubAgentV0Contract(
            "RuntimeActionType.SUBAGENT_DELEGATE_V0 is missing"
        ) from exc


def build_v0_request(
    *,
    provider_mode: str = "fake_local",
    task: str = "summarize safely",
    payload: Mapping[str, Any] | None = None,
) -> RuntimeActionRequest:
    return RuntimeActionRequest(
        action_type=v0_action_type(),
        source="subagent-v0-red-guardrail",
        parent_trace_id="parent-trace",
        payload={
            "profile_id": "default-v0",
            "task": task,
            "provider_mode": provider_mode,
            "parent_opt_in": provider_mode == "real_opt_in",
            **dict(payload or {}),
        },
    )


def build_v0_dispatcher_and_handler() -> tuple[Any, Any]:
    action_type = v0_action_type()
    dispatcher = build_phase1_dispatcher()
    handler = dispatcher.get_handler(action_type)
    if handler is None:
        raise MissingSubAgentV0Contract(
            "SUBAGENT_DELEGATE_V0 handler is not registered"
        )
    if type(handler).__name__ != "SubAgentV0Handler":
        raise AssertionError(f"unexpected v0 handler: {type(handler).__name__}")
    return dispatcher, handler


def route_v0(payload: Mapping[str, Any] | None = None, *, provider_mode: str = "fake_local"):
    dispatcher, _handler = build_v0_dispatcher_and_handler()
    return dispatcher.route(build_v0_request(provider_mode=provider_mode, payload=payload))


V0_XFAIL = {
    "strict": True,
    "raises": MissingSubAgentV0Contract,
    "reason": V0_MISSING_REASON,
}

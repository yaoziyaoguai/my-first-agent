"""Safe RuntimeEvent emission helper.

学习型说明：
RuntimeEvent sink 是 UI projection 边界。sink 抛错不能跳过 Runtime 下游
清理（例如 clear_checkpoint / reset_task），所以这里集中吞掉 sink 异常并
输出最小诊断；不修改 state，不写 checkpoint。
"""

from __future__ import annotations

import contextlib

from agent.display_events import RuntimeEvent, RuntimeEventSink, render_runtime_event_for_cli
from agent.runtime_observer import log_event as log_runtime_event


def safe_emit_runtime_event(
    sink: RuntimeEventSink | None,
    event: RuntimeEvent,
    *,
    fallback_prefix: str = "",
) -> None:
    """安全投递 RuntimeEvent；sink 失败时降级 stdout 并保持主流程继续。"""

    if sink is None:
        print(f"{fallback_prefix}{render_runtime_event_for_cli(event)}")
        return
    try:
        sink(event)
    except Exception as exc:
        with contextlib.suppress(Exception):
            log_runtime_event(
                "runtime_event_sink.failed",
                event_source="runtime",
                event_payload={
                    "original_event_type": event.event_type,
                    "exception_type": type(exc).__name__,
                },
                event_channel="display",
            )
        print(f"{fallback_prefix}{render_runtime_event_for_cli(event)}")

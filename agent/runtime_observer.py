"""Runtime 观测日志层，不参与业务决策。

这个模块统一输出 Event / Resolution / Transition / Actions 相关日志，帮助调试
Agent Runtime 的状态流转。它只负责“让发生了什么可见”，不是状态机本身。

重要边界：
- 不修改 state；
- 不写 checkpoint；
- 不写 conversation.messages；
- 不执行工具；
- 第一版仍然用 print，暂不引入 logging 框架或 JSONL。

命名约定：
- event_source：谁产生了事件，例如 model / user / runtime / tool；
- event_channel：事件是通过什么通道被观察到，例如 tool_use / assistant_text /
  cli / fallback。它不是事件来源，只是观测入口。
"""

from __future__ import annotations

from typing import Any

MAX_LOG_TEXT_PREVIEW = 120


RUNTIME_DEBUG_LOGS = True
"""Runtime 观测开关。

这是日志开关，不是业务开关。关闭它只应减少 stdout 输出，不应该改变 Agent
状态转移、工具执行、checkpoint 或 messages 行为。

实验分支默认开启是为了定位 loop / no_progress 问题；产品化时应改为环境变量或
配置项控制，并优先写结构化日志文件，避免 debug 输出污染 TUI conversation view。
"""


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _format_fields(fields: dict[str, Any]) -> str:
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str | int | float | bool):
            parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def _safe_log_value(value: Any) -> Any:
    """把 observer payload 压成适合 JSONL 的短字段。

    Runtime 观测日志只回答“发生了什么”，不保存完整 prompt/messages/tool input。
    字符串统一截断，容器只保留浅层短值，避免 TUI/terminal 再次被大 JSON 污染。
    """

    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if len(value) <= MAX_LOG_TEXT_PREVIEW:
            return value
        return value[:MAX_LOG_TEXT_PREVIEW] + "..."
    if isinstance(value, list):
        return [_safe_log_value(item) for item in value[:20]]
    if isinstance(value, tuple):
        return [_safe_log_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {
            str(key): _safe_log_value(val)
            for key, val in list(value.items())[:30]
        }
    return str(value)[:MAX_LOG_TEXT_PREVIEW]


def _persist_observer_event(
    event_type: str,
    *,
    event_source: str | None,
    event_payload: dict[str, Any] | None,
    event_channel: str | None,
) -> None:
    """把 observer 事件同步写入 agent_log.jsonl。

    这里故意吞掉日志写入异常：可观测性不能改变 Runtime 行为。
    """

    try:
        from agent.logger import log_event as _log_event

        data: dict[str, Any] = {
            "event_type": event_type,
            "event_source": event_source,
            "event_channel": event_channel,
        }
        if event_payload:
            data["payload"] = _safe_log_value(event_payload)
        _log_event("runtime_observer", data)
    except Exception:
        return


def log_event(
    event_type: str,
    *,
    event_source: str | None = None,
    event_payload: dict[str, Any] | None = None,
    event_channel: str | None = None,
) -> None:
    """记录 RuntimeEvent 的核心字段。

    event_payload 传进来是为了保留 API 边界，但第一版不完整打印 payload 值：
    - 避免日志过长；
    - 避免泄露用户输入、工具参数或敏感内容；
    - 观测日志只需要确认 event_type / event_source / event_channel 是否正确。

    如果后续需要更细粒度观测，也应优先打印 payload_keys，而不是 payload values。
    """
    if not RUNTIME_DEBUG_LOGS:
        return

    _persist_observer_event(
        event_type,
        event_source=event_source,
        event_payload=event_payload,
        event_channel=event_channel,
    )
    fields = {
        "event_type": event_type,
        "event_source": event_source,
        "event_channel": event_channel,
    }
    print(f"[RUNTIME_EVENT] {_format_fields(fields)}")


def log_resolution(
    resolution_kind: str,
    *,
    event_type: str | None = None,
    event_source: str | None = None,
    event_channel: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """记录输入/输出被解析成哪种 runtime 语义。

    Resolution 是“判断结果”，不是 Action。这里打印 `resolution_kind` 等字段，
    只是帮助确认 resolver 如何分类；真正的 append / advance / save 等副作用
    应发生在 transition/action 层。
    """
    if not RUNTIME_DEBUG_LOGS:
        return

    fields: dict[str, Any] = {
        "resolution_kind": resolution_kind,
        "event_type": event_type,
        "event_source": event_source,
        "event_channel": event_channel,
    }
    if details:
        fields.update(details)

    print(f"[INPUT_RESOLUTION] {_format_fields(fields)}")


def log_transition(
    *,
    from_state: str,
    event_type: str,
    target_state: str,
    guard_name: str | None = None,
) -> None:
    """记录一次状态转移的 from_state / event_type / target_state。

    这里不执行 transition，只打印 transition 已经发生或即将由调用方表达的语义。
    guard_name 用于未来补充“为什么这条转移可以走”，第一版可为空。
    """
    if not RUNTIME_DEBUG_LOGS:
        return

    fields = {
        "from_state": from_state,
        "event_type": event_type,
        "target_state": target_state,
        "guard_name": guard_name,
    }
    print(f"[TRANSITION] {_format_fields(fields)}")


def log_actions(action_names: list[str]) -> None:
    """记录 transition 中执行的 action 名称，不执行任何 action。"""
    if not RUNTIME_DEBUG_LOGS:
        return

    print(f"[ACTIONS] action_names={','.join(action_names)}")

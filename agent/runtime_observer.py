"""Runtime 观测日志层，不参与业务决策。

这个模块统一输出 Event / Resolution / Transition / Actions 相关日志，帮助调试
Agent Runtime 的状态流转。它只负责“让发生了什么可见”，不是状态机本身。

重要边界：
- 不修改 state；
- 不写 checkpoint；
- 不写 conversation.messages；
- 不执行工具；
- 结构化事件默认写入 agent_log.jsonl；terminal 短日志只有
  MY_FIRST_AGENT_DEBUG=1 时才打印，避免污染 TUI conversation view。

命名约定：
- event_source：谁产生了事件，例如 model / user / runtime / tool；
- event_channel：事件是通过什么通道被观察到，例如 tool_use / assistant_text /
  cli / fallback。它不是事件来源，只是观测入口。
"""

from __future__ import annotations

import os
from typing import Any

MAX_LOG_TEXT_PREVIEW = 120


RUNTIME_DEBUG_LOGS = os.getenv("MY_FIRST_AGENT_DEBUG", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
"""Runtime 观测开关。

这是 terminal debug 开关，不是业务开关。关闭它只应减少 stdout 输出，不应该
改变 Agent 状态转移、工具执行、checkpoint、messages，或 agent_log.jsonl 里的
结构化观测记录。

默认关闭是为了让 TUI/普通终端只看到用户可见输出。需要临时排查时可设置
MY_FIRST_AGENT_DEBUG=1，把 [RUNTIME_EVENT] / [INPUT_RESOLUTION] 等短日志打印到
terminal；结构化 JSONL 日志不依赖这个开关。
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

    ────────────────────────────────────────────────────────────────────
    v0.5 命名碰撞警告（务必读完再写新代码）
    ────────────────────────────────────────────────────────────────────
    本函数与 ``agent/logger.py`` 中的 ``log_event`` **同名但签名不同**：

    - 本函数 ``agent.runtime_observer.log_event``
        * ``event_type`` 是唯一 positional/keyword 参数；
        * ``event_source`` / ``event_payload`` / ``event_channel`` 全部
          **keyword-only**；
        * 内部走 ``_persist_observer_event`` → ``_safe_log_value`` 脱敏 →
          兜底再调 legacy ``logger.log_event``；
        * **任何异常一律 swallow**（产品契约：可观测性不能破坏 Runtime）；
        * 新代码入口（v0.5 时刻调用方：``agent/core.py`` 起别名
          ``log_runtime_event``、``agent/confirm_handlers.py`` 起别名
          ``_log_runtime_event``）。

    - 另一个 ``agent.logger.log_event(event_type, data)``
        * 两位 positional，``data`` 任意 dict；
        * 不脱敏、IO 异常向上冒泡；
        * 历史 9 处 legacy 调用点（planner/memory/checks/session/review/
          context/health_check/checkpoint 懒加载/本文件兜底转发）。

    职责边界
    --------
    本函数 **只负责** 接 RuntimeEvent 边界 → 脱敏 → 落盘 → swallow。
    本函数 **不负责** 替代 legacy logger（兜底仍调它）、不负责构造
    ObserverEvent dataclass、不负责进入 TUI 渲染（DisplayEvent 走另一条线）。

    payload 安全红线
    -----------------
    ``event_payload`` 当前仅打印 keys（见函数体），不打印 value，
    避免泄露用户输入、工具参数、tool_result 大文本、feedback_text 等。
    新调用方在传 payload 之前，仍应自行只放 ``origin_status`` /
    ``resolution_kind`` / ``tool_name`` 等枚举短字段（见
    ``agent/confirm_handlers.py`` 的 ``_emit_confirmation_observer_event``）。

    为什么 v0.5 不立刻重命名
    --------------------------
    见 ``agent/logger.py`` 同名函数 docstring。本切片只用
    ``tests/test_log_event_signature_collision.py`` 用 ``inspect.signature``
    把两份签名锁死，等独立 slice 再做重命名。

    artifact 排查
    --------------
    本函数写入 ``LOG_FILE`` 时 ``event`` 字段固定为 ``"runtime_observer"``，
    真正的 ``event_type`` 嵌在 data 内层；筛选时 grep
    ``"event": "runtime_observer"``，再按 data.event_type 二级过滤。
    """
    _persist_observer_event(
        event_type,
        event_source=event_source,
        event_payload=event_payload,
        event_channel=event_channel,
    )
    if not RUNTIME_DEBUG_LOGS:
        return

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

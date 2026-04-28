"""v0.3 M1 · 基础 CLI Shell 渲染器（纯函数）。

为什么是「基础」而不是完整 Textual：
- v0.3 M1 只把 plain stdout 输出做得**结构化、可扫读、不刷屏**，
  不引入 Textual / rich.live / curses / 多面板 / 快捷键。
- 完整 Textual / Esc cancellation / generation cancel / timeline viewer
  全部明确归在 v0.3 M1 之外（见 docs/V0_3_PLANNING.md §5.2）。

为什么把渲染拆成独立模块：
- 渲染层不能反向污染 Runtime / messages / checkpoint：本模块**只读** dict，
  不持有 AgentState 引用，不调用任何会改 state / 写日志的东西。
- 这样测试可以纯函数式地断言「输入 dict → 输出字符串」，不需要起 Runtime。
- session.py / main.py 只负责把渲染结果 print 出去；checkpoint schema 不变。

为什么所有渲染函数都不接受 raw `state` / raw `checkpoint`：
- 防止把 api key / raw prompt / response body / headers / base_url 原值
  误打到终端。所有入参必须是已脱敏的 summary dict（见
  agent/session.py::summarize_session_status）。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# 当前阶段标签。后续 v0.3 M2/M3/M4 推进时同步改这里即可，
# 不要在 main.py 多处分散 hardcode。
STAGE_LABEL = "Runtime v0.3 M1 shell"

# 渲染分隔线宽度。固定 60，避免按终端宽度自适应引入 curses 依赖。
_BAR = "─" * 60


def _safe(value: Any, fallback: str = "—") -> str:
    """把可能为 None / 空字符串的字段转成可读占位符。"""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def render_session_header(
    *,
    session_id: str,
    cwd: str,
    stage_label: str = STAGE_LABEL,
    health_summary: str | None = None,
) -> str:
    """启动时的 session header。

    分区：
    - 标题行：阶段标签
    - 元信息：session id（短哈希形式由调用方决定）/ cwd
    - 健康摘要：单行紧凑文本，无 warning 时省略，避免刷屏
    - 用法提示：v0.3 M3 把启动提示从「'/reload_skills' 重新加载 skill」改成
      诚实文案——主循环并没有 slash command 解析器，`/reload_skills` 历史上
      只是被印在屏幕上、不会真的执行；保留会让用户以为 Skill 已经成熟。
      改成只展示 quit + 一句关于 skill 仍是实验性能力的提示。
    """
    short_session = session_id[:8] if session_id else "—"
    lines = [
        _BAR,
        f"  {stage_label}",
        _BAR,
        f"  session : {short_session}  (full: {_safe(session_id)})",
        f"  cwd     : {_safe(cwd)}",
    ]
    if health_summary:
        lines.append(f"  health  : {health_summary}")
    lines.extend(
        [
            _BAR,
            "  输入 'quit' 退出。",
            "  Skill 是实验性能力（v0.3 M3 状态澄清，详见 docs/V0_3_SKILL_SYSTEM_STATUS.md）。",
            "",
        ]
    )
    return "\n".join(lines)


def summarize_health(results: Mapping[str, Mapping[str, Any]] | None) -> str:
    """把 health_check 结果压成一行可读摘要。

    示例：
    - 全 pass："all checks passed"
    - 有 warn："3 warn (workspace_lint, log_size, session_accumulation)"
    - 输入为 None / 空："skipped"

    刻意不重复 health_check 已经打的长报告内容；如果用户想看详情，
    用 `python main.py health` 单独跑（v0.2 已落地的子命令）。
    """
    if not results:
        return "skipped"

    warns = [
        name
        for name, result in results.items()
        if isinstance(result, Mapping) and result.get("status") == "warn"
    ]
    errors = [
        name
        for name, result in results.items()
        if isinstance(result, Mapping) and result.get("status") == "error"
    ]
    if not warns and not errors:
        return "all checks passed"
    parts: list[str] = []
    if warns:
        parts.append(f"{len(warns)} warn ({', '.join(warns)})")
    if errors:
        parts.append(f"{len(errors)} error ({', '.join(errors)})")
    parts.append("详情：python main.py health")
    return "; ".join(parts)


def render_resume_status(summary: Mapping[str, Any] | None) -> str:
    """渲染 resume 检测结果。

    summary 是 session.summarize_session_status 的返回值，**不是** raw
    checkpoint dict（避免把 conversation messages 等敏感字段 print 到终端）。

    四种情况：
    - summary is None → 没有 checkpoint：输出 「未发现断点」
    - summary["actionable"] is False → 历史残留：输出 「断点为 idle 残留，已静默清理」
    - summary["actionable"] is True：输出多行可读断点摘要
    """
    if summary is None:
        return "  📭 resume : 未发现断点，可以直接开始新任务。"

    if not summary.get("actionable", False):
        return "  📭 resume : 断点为 idle 残留，已静默清理。"

    user_goal = _safe(summary.get("user_goal"), "（未命名任务）")
    status = _safe(summary.get("status"), "unknown")
    step_index = summary.get("current_step_index", 0)
    msg_count = summary.get("message_count", 0)
    pending_tool = summary.get("pending_tool_name")

    lines = [
        f"  📌 resume : 发现未完成的任务：{user_goal}",
        f"             状态：{status}",
        f"             当前步骤索引：{step_index}",
        f"             已有 {msg_count} 条对话历史",
    ]
    if pending_tool:
        lines.append(f"             待确认工具：{pending_tool}")
    return "\n".join(lines)


def render_status_line(summary: Mapping[str, Any] | None) -> str:
    """单行状态条，可在主要状态变化时打一次。

    示例：「[status] running · step 3/5 · pending_tool=write_file」

    刻意不实现「定时刷新」「inplace 重绘」，避免引入 curses。
    调用方只在状态变化点打一次即可，不会刷屏。
    """
    if summary is None:
        return "[status] (no session)"
    parts = [f"status={_safe(summary.get('status'), 'unknown')}"]
    step_index = summary.get("current_step_index")
    plan_total = summary.get("plan_total_steps")
    if plan_total:
        parts.append(f"step={step_index or 0}/{plan_total}")
    pending_tool = summary.get("pending_tool_name")
    if pending_tool:
        parts.append(f"pending_tool={pending_tool}")
    msg_count = summary.get("message_count")
    if msg_count is not None:
        parts.append(f"msgs={msg_count}")
    return "[status] " + " · ".join(parts)

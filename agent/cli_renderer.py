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
from dataclasses import is_dataclass
from typing import Any

# 当前阶段标签。后续 v0.3 M2/M3/M4 推进时同步改这里即可，
# 不要在 main.py 多处分散 hardcode。
STAGE_LABEL = "Runtime v0.3 basic CLI shell"

# 渲染分隔线宽度。固定 60，避免按终端宽度自适应引入 curses 依赖。
_BAR = "─" * 60


def _safe(value: Any, fallback: str = "—") -> str:
    """把可能为 None / 空字符串的字段转成可读占位符。"""
    if value is None:
        return fallback
    if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return fallback
    if is_dataclass(value) and not isinstance(value, type):
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
            "  输入 'quit' 退出，输入 'help' 查看可用能力与限制。",
            "  python main.py health / python main.py logs --tail 50。",
            "  Fake provider 安全路径（默认，无 API key，不联网）。",
            "  [实验性] Skill 系统仍是实验性能力，具体状态见 help 或 docs/archive/v0.x/V0_3_SKILL_SYSTEM_STATUS.md。",
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
    status = _safe(summary.get("status"), "unknown")
    parts = [f"state={_interaction_state_label(status)}", f"status={status}"]
    step_index = summary.get("current_step_index")
    plan_total = summary.get("plan_total_steps")
    if plan_total:
        parts.append(f"step={step_index or 0}/{plan_total}")
    current_step_title = summary.get("current_step_title")
    if current_step_title:
        parts.append(f"current_step={_one_line(current_step_title, 80)}")
    pending_tool = summary.get("pending_tool_name")
    if pending_tool:
        parts.append(f"pending_tool={_safe(pending_tool)}")
    msg_count = summary.get("message_count")
    if msg_count is not None:
        parts.append(f"msgs={msg_count}")
    return "[status] " + " · ".join(parts)


def render_provider_mode_banner() -> str:
    """启动时输出当前 provider mode 一行横幅。

    manual human dogfood 第一 blocker：用户启动时必须清楚当前是 fake/local 还是
    real provider。这个横幅在 main() 的 load_legacy_dotenv_config() 之后、
    main_loop 之前输出，确保 .env 已加载到 os.environ。
    """
    import os

    provider_env = os.getenv("MY_FIRST_AGENT_LLM_PROVIDER")
    model_env = os.getenv("MY_FIRST_AGENT_LLM_MODEL") or os.getenv("ANTHROPIC_MODEL") or os.getenv("OPENAI_MODEL")

    if not provider_env or provider_env.strip().lower() == "fake":
        mode_label = "fake (local only — 不调用真实 API)"
    else:
        provider_label = provider_env.strip().lower()
        model_label = model_env or "unspecified"
        mode_label = f"{provider_label} (真实 API — model={model_label})"

    return f"[provider] mode={mode_label}"


def _interaction_state_label(status: str) -> str:
    """Map internal TaskState status to a user-facing interaction state."""

    mapping = {
        "idle": "waiting user input",
        "planning": "planning",
        "running": "executing tool/model",
        "awaiting_plan_confirmation": "awaiting confirmation",
        "awaiting_step_confirmation": "awaiting confirmation",
        "awaiting_tool_confirmation": "awaiting confirmation",
        "awaiting_user_input": "waiting user input",
        "awaiting_feedback_intent": "waiting user input",
        "done": "finished",
        "failed": "failed",
        "cancelled": "failed",
    }
    return mapping.get(status, status or "unknown")


def render_onboarding() -> str:
    """用户首次接触或 help 命令时的简洁 onboarding。

    诚实说明当前阶段：runtime pipeline 完整，但用户可感知能力仍在补齐中。
    不夸大 fake demo 为产品能力，不把 dispatch path 写成 user-visible complete。
    """
    lines = [
        _BAR,
        "  First Agent — Runtime v0.3 用户能力补齐阶段",
        _BAR,
        "",
        "  定位：个人 AI 助手 runtime。工程地基（Tool/Skill/SubAgent/Memory pipeline）",
        "  已通过 L3 evidence 验证，当前阶段在已有地基上补齐用户可感知能力。",
        "",
        "  当前状态：",
        "    • 一页状态文档：docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md",
        "    • fake/local rehearsal 已通过，但 agent-driven rehearsal 不是人工 dogfood",
        "    • manual human dogfood 未完成；用户准备好后再按 dogfood checklist 走",
        "    • real provider 401 已记录为 config/auth concern，AutoRun 不重试真实 API",
        "    • not broadly user-ready：当前只适合 local-first dogfood / cleanup",
        "",
        "  ✅ 当前可用：",
        "    • Fake/local mode — Fake Provider 默认安全路径，无 API key，不联网",
        "      （FakeProvider 不依赖 .env；main() 会尝试加载 .env 以支持 opt-in real",
        "      provider 配置，但默认 fake 路径不使用真实 key）",
        "    • Real provider opt-in — 已实现 provider adapter；需要用户自行修复 key/endpoint",
        "    • Tools — demo.echo_task_summary / demo.write_demo_note",
        "      已注册在 ToolRegistry 中，可通过 core.chat() + Tool Pipeline 调用",
        "    • Memory — remember/show/forget + confirmation + deterministic snapshot baseline",
        "    • SubAgents — L0 local deterministic DEMO-ONLY delegation（demo-stat/code-reviewer）",
        "    • Demo Skill — demo-note-maker（写本地任务笔记）",
        "    • Run summary / debug — 每轮结束输出摘要；health/logs 可用于本地排查",
        "    • 快速安全 demo：python main.py demo \"你的任务描述\"",
        "      （注：这是独立 demo adapter 路径，不经过完整 Tool Pipeline；",
        "      用于快速验证本地环境，不是 unified runtime flow 全链路证明）",
        "    • python main.py             进入交互模式（经 core.chat() 统一入口）",
        "    • python main.py health          查看健康检查",
        "    • python main.py logs --tail 50   查看最近日志",
        "    • Ctrl+C 保存 checkpoint，下次启动可 resume",
        "",
        "  ⚠️ 尚未产品化（dispatch path 已验证，但业务侧仍为空或 partial）：",
        "    • 真实 LLM provider — 已实现但需自行配置 API key（opt-in）；401 属配置/认证问题",
        "    • SubAgent — L0 deterministic DEMO-ONLY；L1+ real delegation 未实现",
        "    • Skill — demo-note-maker 可用，多 skill marketplace 未实现",
        "    • Memory consolidation — L3 evidence path 存在，真实 LLM consolidation 未实现",
        "    • MCP confirmation=\"always\" — product decision required",
        "    • RAG / embedding / plugin marketplace — 未开始",
        "",
        "  🔒 安全边界：",
        "    • FakeProvider 默认安全路径不依赖 .env，不调用真实 API",
        "    • main() 会尝试加载 .env 供 opt-in real provider 使用，但 fake 路径忽略其值",
        "    • 不读取真实 sessions / runs / 私人资料",
        "    • 不访问外部网络（fake 路径）",
        "    • Demo 文件只写入 workspace/demo/ 受控目录",
        "",
        "  快速体验：",
        "    python main.py demo \"create a demo note about today's run\"",
        "    python main.py                    进入交互模式",
        "    python main.py --help             显示此信息",
        "",
    ]
    return "\n".join(lines)


def _one_line(value: Any, limit: int) -> str:
    text = " ".join(_safe(value, "structured value").split())
    if len(text) <= limit:
        return text
    return text[:limit] + "..."

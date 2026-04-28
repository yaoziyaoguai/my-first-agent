"""v0.3 M4 · 可读 Observer / Logs MVP（只读，不删除任何东西）。

M4 的范围**严格限制**为：
- 让用户能用 `python main.py logs [--tail N] [--session ID] [--event TYPE]
  [--tool NAME]` 从巨大的 agent_log.jsonl 里捞出最近关键事件。
- 输出**单行紧凑摘要**，绝不 dump 完整 dict、绝不打印 raw content / raw
  tool_result / 完整 checkpoint / system_prompt 正文。
- 默认过滤掉极噪的 `runtime_observer`（占 ~86% 条目），用 --include-observer
  显式打开。

非目标：
- ❌ 不实现完整 observability 平台 / metric pipeline / SQLite 索引
- ❌ 不实现 LLM judge / Reflect / 自动归类
- ❌ **不会**自动删除或归档 agent_log.jsonl / sessions/ / memory/checkpoint
- ❌ 不引入新存储格式（只读 jsonl）

防泄漏边界（详见 docs/V0_3_OBSERVER_LOGS.md §4）：
- 历史日志可能含早期未脱敏的 raw content（例如 README 全文、文件读写正文）。
  M4 渲染层只展示**结构化元信息**（event / tool / status / path / 长度），
  不打印任何 *content / *result / system_prompt / messages / payload.text 等
  正文字段。即使原始 jsonl 里有 raw secret，也不会经 logs viewer 流到 stdout。
- 兜底：渲染后再跑一次 mask_secrets，把 sk-ant- / BEGIN PRIVATE KEY /
  ANTHROPIC_API_KEY=xxx 之类残留模式替换成 [REDACTED]，防止漏网。
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from config import LOG_FILE

# 默认在 logs 视图里隐藏的高噪声事件类型。
# runtime_observer 在常见日志里占 ~86% 条目，对人工调试基本没用，加 --include-observer 才显示。
_NOISY_EVENT_TYPES = {"runtime_observer"}

# 渲染时**绝不**直接展示的字段名（哪怕 jsonl 里有，也不打印到 stdout）。
# 这是 M4 的脱敏白名单边界：能展示的是结构化元信息，不是正文。
_FORBIDDEN_FIELDS = {
    "content",
    "result",
    "system_prompt",
    "messages",
    "summary",
    "text",
    "text_preview",
    "raw_response",
    "completion",
    "prompt",
    "issues",  # ruff 输出可能含路径，截短即可
}

# 兜底脱敏：渲染后再扫一遍输出，残留的明文密钥/私钥头/.env 行强制替换。
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-{0,5}BEGIN [A-Z ]*PRIVATE KEY-{0,5}"),
    re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*\S+"),
]


def mask_secrets(text: str) -> str:
    """对单行渲染输出做兜底脱敏。M4 不依赖此函数做主防线，
    主防线是「不进入 _FORBIDDEN_FIELDS」；这里只防漏网。"""
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def _short(s: str, n: int = 60) -> str:
    """字符串截短，避免单条事件撑满终端。"""
    if s is None:
        return ""
    s = str(s).replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _short_session(session_id: str | None) -> str:
    if not session_id:
        return "—"
    return session_id[:8]


def iter_log_entries(
    log_path: Path | None = None,
    *,
    include_observer: bool = False,
) -> Iterator[dict[str, Any]]:
    """逐行读取 jsonl，损坏行不抛异常，只 yield 一个 _broken 标记。

    单条事件被解析失败（例如 truncated write）也不应该让 logs 子命令崩溃；
    M4 选择「跳过坏行 + 在最后给计数」而不是「报错退出」，让用户在事故现场
    仍能看到完整事件链路。
    """
    path = Path(log_path) if log_path else Path(LOG_FILE)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as e:
                yield {"_broken": True, "_line": lineno, "_error": str(e)}
                continue
            if not include_observer and entry.get("event") in _NOISY_EVENT_TYPES:
                continue
            yield entry


def filter_entries(
    entries: Iterable[dict[str, Any]],
    *,
    session_id: str | None = None,
    event: str | None = None,
    tool: str | None = None,
) -> Iterator[dict[str, Any]]:
    """三种低风险过滤：按 session 前缀、按事件类型、按工具名。

    session_id 用前缀匹配（用户通常只敲 8 位短哈希）。
    """
    for e in entries:
        if e.get("_broken"):
            yield e
            continue
        if session_id:
            sid = e.get("session_id", "") or ""
            if not sid.startswith(session_id):
                continue
        if event and e.get("event") != event:
            continue
        if tool:
            data = e.get("data") or {}
            if data.get("tool") != tool:
                continue
        yield e


def _format_data_summary(event: str, data: dict[str, Any]) -> str:
    """根据 event 类型抽**结构化元信息**，绝不展示 _FORBIDDEN_FIELDS。

    这里是 M4 的核心脱敏边界：每类事件都显式枚举允许的字段。
    新增事件类型时，请走「先 explicit allowlist」的路径，不要 fallback 到
    `json.dumps(data)`。
    """
    if not isinstance(data, dict):
        return ""

    if event in {"tool_requested", "tool_executed", "tool_rejected"}:
        tool = data.get("tool", "?")
        # tool_input 里只展示 path / expression / url / name 等元信息，
        # 不展示 content（write_file 的正文）/ result（read_file 的文件正文）。
        ti = data.get("input") or {}
        meta_bits = []
        for k in ("path", "expression", "url", "name"):
            if k in ti:
                meta_bits.append(f"{k}={_short(ti[k], 40)}")
        meta = " ".join(meta_bits)
        # tool_executed 只展示 result 长度，不展示 result 本身
        if event == "tool_executed" and "result" in data:
            rlen = len(str(data.get("result", "")))
            meta = (meta + f" result_len={rlen}").strip()
        return f"tool={tool} {meta}".strip()

    if event in {
        "tool_blocked",
        "tool_blocked_sensitive",
        "tool_blocked_sensitive_read",
        "tool_blocked_protected_source",
    }:
        tool = data.get("tool", "?")
        path = data.get("path", "")
        return f"tool={tool} path={_short(path, 50)}".strip()

    if event == "user_input":
        # 只显示长度，不显示 content
        content = data.get("content", "")
        return f"len={len(str(content))}"

    if event == "agent_reply":
        content = data.get("content", "")
        return f"len={len(str(content))}"

    if event == "session_start":
        sp = data.get("system_prompt", "")
        return f"system_prompt_len={len(str(sp))}"

    if event == "llm_call":
        return f"messages={data.get('message_count', '?')}"

    if event == "llm_response":
        return f"stop={data.get('stop_reason', '?')}"

    if event == "checkpoint_saved":
        return (
            f"step={data.get('current_step_index', '?')} "
            f"messages={data.get('message_count', '?')}"
        ).strip()

    if event == "checkpoint_cleared":
        reason = data.get("reason", "")
        return f"reason={_short(reason, 50)}"

    if event == "context_compression_start":
        return f"messages={data.get('message_count', '?')}"

    if event == "context_compression_done":
        return (
            f"old={data.get('old_count', '?')} "
            f"new={data.get('new_count', '?')}"
        )

    if event == "health_check":
        names = []
        for k, v in data.items():
            if isinstance(v, dict) and v.get("status") == "warn":
                names.append(k)
        return f"warn=[{', '.join(names) or 'none'}]"

    if event == "plan_generated":
        return f"steps={data.get('total_steps', data.get('steps', '?'))}"

    if event == "plan_skipped" or event == "plan_error":
        reason = data.get("reason") or data.get("error", "")
        return f"reason={_short(reason, 60)}"

    if event == "review_completed":
        return f"overall={_short(data.get('review_overall', '?'), 30)}"

    if event in {"linter_passed", "linter_issues"}:
        return f"file={_short(data.get('file', ''), 60)}"

    if event in {"episodes_saved", "memory_extracted", "rule_saved"}:
        # 只显示数值字段，不展示 file 路径里的家目录
        bits = [f"{k}={v}" for k, v in data.items() if isinstance(v, (int, float))]
        return " ".join(bits)

    if event == "auto_retry":
        return f"attempt={data.get('attempt', '?')}"

    # 兜底：只展示 dict 的 key 名 + 标量值，绝不递归 dump 嵌套结构。
    safe_bits = []
    for k, v in data.items():
        if k in _FORBIDDEN_FIELDS:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            safe_bits.append(f"{k}={_short(str(v), 40)}")
    return " ".join(safe_bits)


def format_entry(entry: dict[str, Any]) -> str:
    """把一条事件渲染成单行可读摘要。"""
    if entry.get("_broken"):
        return f"  [损坏] line={entry.get('_line', '?')} {entry.get('_error', '')}"

    ts = entry.get("timestamp", "—")
    sid = _short_session(entry.get("session_id"))
    event = entry.get("event", "?")
    data = entry.get("data") or {}
    summary = _format_data_summary(event, data) if isinstance(data, dict) else ""
    line = f"{ts} [{sid}] {event}"
    if summary:
        line = f"{line}  {summary}"
    return mask_secrets(line)


def render_logs(
    *,
    log_path: Path | None = None,
    tail: int | None = 50,
    session_id: str | None = None,
    event: str | None = None,
    tool: str | None = None,
    include_observer: bool = False,
) -> str:
    """主入口：读 + 过滤 + 渲染 + 拼接。

    tail=None 表示不截断；默认 50 让人工调试时屏幕一屏内能放下。
    """
    entries = iter_log_entries(log_path=log_path, include_observer=include_observer)
    filtered = list(
        filter_entries(entries, session_id=session_id, event=event, tool=tool)
    )

    broken_count = sum(1 for e in filtered if e.get("_broken"))
    real = [e for e in filtered if not e.get("_broken")]

    if tail is not None and tail > 0:
        real = real[-tail:]

    bar = "─" * 60
    header_bits = [
        f"showing last {len(real)} entries",
    ]
    if session_id:
        header_bits.append(f"session={session_id}")
    if event:
        header_bits.append(f"event={event}")
    if tool:
        header_bits.append(f"tool={tool}")
    if not include_observer:
        header_bits.append("(runtime_observer hidden; use --include-observer)")

    lines = [
        bar,
        "📜 Runtime logs · v0.3 M4",
        bar,
        "  " + "  ".join(header_bits),
        bar,
    ]
    if not real:
        lines.append("  (no matching entries)")
    else:
        for e in real:
            lines.append("  " + format_entry(e))
    if broken_count:
        lines.append(bar)
        lines.append(f"  ⚠️  跳过了 {broken_count} 条损坏的 jsonl 行")
    lines.append(bar)
    lines.append(
        "提示：M4 不会自动删除日志；如需归档/清理，运行 `python main.py health` 查看建议命令。"
    )
    lines.append(bar)
    return "\n".join(lines)

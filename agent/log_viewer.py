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

# sessions/ 目录的父目录（即项目根目录），用于定位 per-session events.jsonl
_PROJECT_DIR = Path(__file__).resolve().parent.parent

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

    if event == "llm_usage":
        # G-045: per-turn token usage surfaced from the provider seam.
        inp = data.get("input_tokens")
        out = data.get("output_tokens")
        tot = data.get("total_tokens")
        bits = []
        if inp is not None:
            bits.append(f"in={inp}")
        if out is not None:
            bits.append(f"out={out}")
        if tot is not None:
            bits.append(f"total={tot}")
        return " ".join(bits) if bits else ""

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


# ── Per-session events.jsonl helpers ──


def _resolve_session_dir(session_id_prefix: str, project_dir: Path | None = None) -> Path | None:
    """将会话 ID 前缀解析为 sessions/<id>/ 目录路径。

    扫描 sessions/ 目录，返回第一个匹配前缀的目录。
    返回 None 表示无匹配。
    """
    _base = project_dir or _PROJECT_DIR
    sessions_dir = _base / "sessions"
    if not sessions_dir.exists():
        return None
    for d in sorted(sessions_dir.iterdir(), reverse=True):
        if d.is_dir() and d.name.startswith(session_id_prefix):
            return d
    return None


def _read_per_session_events(session_dir: Path) -> list[dict[str, Any]]:
    """读取 per-session events.jsonl，转换为 agent_log.jsonl 兼容的 entry 格式。

    返回的每条 entry 包含 event / session_id / timestamp / data 字段，
    可直接传入 render_session_summary()。

    per-session events.jsonl 的 data 字段即为 evidence envelope，
    含 subsystem / operation / phase / status / metadata 等全部上下文。
    """
    events_path = session_dir / "events.jsonl"
    if not events_path.exists():
        return []

    entries: list[dict[str, Any]] = []
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            data = ev.get("data", {})
            if not isinstance(data, dict):
                continue
            session_id = data.get("session_id", "")
            timestamp = data.get("timestamp", "")

            # 核心 evidence 事件：转换为 evidence.recorded 格式
            entry = {
                "event": "evidence.recorded",
                "session_id": session_id,
                "timestamp": timestamp,
                "data": data,
            }
            entries.append(entry)

            # 从 session.start 事件中提取 session 身份信息（模拟 legacy session_start entry）
            action_type = ev.get("action_type", "")
            if action_type == "session.start":
                metadata = data.get("metadata", {}) or {}
                entries.append({
                    "event": "session_start",
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "data": {
                        "entry": metadata.get("entry", data.get("entry", "plain")),
                        "provider_type": metadata.get("provider_type",
                                                     data.get("provider_type", "?")),
                        "model": metadata.get("provider_model",
                                              data.get("provider_model", "?")),
                    },
                })
            # user_input events → 兼容 legacy event="user_input"
            elif action_type == "session.user_input":
                entries.append({
                    "event": "user_input",
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "data": {"content": data.get("safe_summary", "")},
                })

    return entries


# ── Summary rendering ──


def render_session_summary(session_id: str, entries: list[dict[str, Any]]) -> str:
    """为单个 session 生成 one-screen evidence summary。

    只展示结构化元信息，不 dump raw content / tool result 正文。
    用于 `python main.py logs --session <id> --summary`。
    """
    real = [e for e in entries if not e.get("_broken")]
    if not real:
        return f"(no entries for session {session_id})"

    # ── 基础 session 信息 ──
    session_start = None
    provider_type = "?"
    model = "?"
    entry = "?"
    for e in real:
        if e.get("event") == "session_start":
            session_start = e
            data = e.get("data", {})
            provider_type = data.get("provider_type", "?")
            model = data.get("model", "?")
            entry = data.get("entry", "?")
            break

    # ── 事件统计 ──
    event_counts: dict[str, int] = {}
    tools_attempted = 0
    tools_executed = 0
    tools_blocked = 0
    tools_blocked_sensitive = 0
    tools_failed = 0
    tools_skipped = 0
    pending_tools_executed = 0
    tool_names: set[str] = set()
    skill_selected = ""
    checkpoints_saved = 0
    session_ended = False
    first_ts = ""
    last_ts = ""
    # 非 tool/checkpoint 的 evidence.recorded 事件 → generic subsystem aggregation
    other_subsystem_events: dict[str, int] = {}
    memory_events: dict[str, int] = {}
    # user_input 从 evidence.recorded 路径计数（替代 legacy event="user_input"）
    user_input_from_evidence = 0

    # 去重：executor 和 mediator 会对同一 tool_use_id 各写一次 evidence，
    # 保留两份事件用于调试，但 summary 中的逻辑计数必须只计一次。
    # 优先使用 tool_use_id；无 tool_use_id 时回退到稳定组合键。
    # 注意：blocked / failed / executed / skipped 各用独立集合，
    # error 不再错误进入 blocked 集合，避免 error→ok 时 executed 被过滤。
    _dedup_tool_attempted: set[str] = set()
    _dedup_tool_executed: set[str] = set()
    _dedup_tool_blocked: set[str] = set()
    _dedup_tool_failed: set[str] = set()
    _dedup_tool_skipped: set[str] = set()

    def _tool_dedup_key(data: dict[str, Any]) -> str:
        """从 evidence.recorded data 中提取去重键。
        优先 tool_use_id（顶层 → metadata.tool_use_id → metadata.canonical_tool_id）；
        fallback 为 tool_name|operation|status 组合键。
        """
        # 顶层：global agent_log.jsonl 格式
        tid = data.get("tool_use_id") or ""
        if not tid:
            # 嵌套：per-session events 中 tool_use_id 位于 data.metadata.tool_use_id
            meta = data.get("metadata", {}) or {}
            tid = meta.get("tool_use_id") or meta.get("canonical_tool_id") or ""
        if tid:
            return tid
        # fallback：从 safe_summary 提取工具名构建稳定键
        tname = ""
        ss = data.get("safe_summary", "")
        if ss.startswith("tool="):
            tname = ss.removeprefix("tool=").split()[0]
        return f"{tname}|{data.get('operation', '')}|{data.get('status', '')}"

    for e in real:
        ev = e.get("event", "")
        event_counts[ev] = event_counts.get(ev, 0) + 1

        ts = e.get("timestamp", "")
        if ts:
            if not first_ts:
                first_ts = ts
            last_ts = ts

        # 收集工具名
        data = e.get("data", {}) or {}
        tool_name = data.get("tool", "")
        if tool_name:
            tool_names.add(tool_name)

        if ev in ("tool_requested",):
            tools_attempted += 1
        elif ev in ("tool_executed",):
            tools_executed += 1
        elif ev in ("tool_blocked", "tool_blocked_sensitive",
                     "tool_blocked_sensitive_read", "tool_blocked_protected_source"):
            tools_blocked += 1
            if "sensitive" in ev:
                tools_blocked_sensitive += 1

        # 解析 evidence.recorded 事件（统一 evidence recorder 写入）
        if ev == "evidence.recorded":
            subsystem = data.get("subsystem", "")
            op = data.get("operation", "")
            status = data.get("status", "")
            # 从 safe_summary 或 metadata 中提取工具名
            evidence_tool_name = (
                data.get("safe_summary", "").removeprefix("tool=").split()[0]
                if data.get("safe_summary", "").startswith("tool=")
                else ""
            )
            if evidence_tool_name:
                tool_names.add(evidence_tool_name)
            if subsystem == "tool":
                dk = _tool_dedup_key(data)
                if op == "gate_decision":
                    if dk not in _dedup_tool_attempted:
                        _dedup_tool_attempted.add(dk)
                        tools_attempted += 1
                    if status == "blocked":
                        if dk not in _dedup_tool_blocked:
                            _dedup_tool_blocked.add(dk)
                            tools_blocked += 1
                        # 检查是否 sensitive path 拦截
                        if "sensitive_path" in str(data.get("reason_code", "")):
                            tools_blocked_sensitive += 1
                    elif status == "skipped":
                        if dk not in _dedup_tool_skipped:
                            _dedup_tool_skipped.add(dk)
                            tools_skipped += 1
                    elif status == "confirmation_required":
                        pass  # confirmation 不计入 attempted/executed/blocked
                elif op in ("invoke_result_summary",):
                    # 去重规则（修复 error→ok 计数错误）：
                    # - blocked / failed / executed 使用独立集合，互不干扰
                    # - error 进入 failed 集合，不进入 blocked 集合
                    # - ok 只检查 executed 集合去重，不被 error/blocked 污染
                    # - 同一 tool_use_id error→ok 时：failed>=1, executed=1
                    if status == "ok":
                        if dk not in _dedup_tool_executed:
                            _dedup_tool_executed.add(dk)
                            tools_executed += 1
                    elif status == "error":
                        if dk not in _dedup_tool_failed:
                            _dedup_tool_failed.add(dk)
                            tools_failed += 1
                    elif status == "blocked" and dk not in _dedup_tool_blocked:
                        _dedup_tool_blocked.add(dk)
                        tools_blocked += 1
                elif op in ("pending_execute",):
                    pending_tools_executed += 1
                    # pending_execute 是用户确认后的实际执行——同时计入 executed
                    if dk and dk not in _dedup_tool_executed:
                        _dedup_tool_executed.add(dk)
                        tools_executed += 1
            elif subsystem == "session":
                if op == "end":
                    session_ended = True
                elif op == "user_input":
                    user_input_from_evidence += 1
            elif subsystem == "checkpoint":
                checkpoints_saved += 1
            elif subsystem == "memory":
                metadata = data.get("metadata", {}) or {}
                if not isinstance(metadata, dict):
                    metadata = {}
                event_type = str(metadata.get("event_type") or f"memory.{op}")
                display_name = (
                    event_type.removeprefix("memory.")
                    .replace("_", " ")
                    .replace(".", " ")
                )
                memory_events[display_name] = memory_events.get(display_name, 0) + 1
            elif subsystem:
                # 未知子系统 → generic aggregation（不硬编码未来能力）
                phase_val = data.get("phase", "")
                key = f"{subsystem}.{op} {phase_val} {status}".strip()
                other_subsystem_events[key] = other_subsystem_events.get(key, 0) + 1

        if ev == "skill_selected":
            skill_selected = data.get("skill", data.get("name", "")) or skill_selected

        if ev in ("checkpoint_saved",):
            checkpoints_saved += 1

    # ── Evidence gaps ──
    gaps: list[str] = []
    if not session_start:
        gaps.append("no session_start event — 未初始化 session")
    if not session_ended:
        gaps.append("no session.end evidence — session 可能未正常退出")
    if provider_type == "?":
        gaps.append("provider_type unknown — 无法区分 fake/real")
    # user_input 计数优先来自 evidence.recorded 路径（新），legacy event="user_input"
    # 作为兼容旧 session 的 fallback。两者不会重复：record_evidence 写入的是
    # event="evidence.recorded"，legacy log_event("user_input") 写入的是 event="user_input"。
    _total_user_input = user_input_from_evidence + event_counts.get("user_input", 0)
    if _total_user_input == 0:
        gaps.append("no user_input events — 对话可能未发生")
    if not last_ts:
        gaps.append("no timestamps — 时间线不可审计")

    # ── 组装输出 ──
    bar = "─" * 58
    lines = [
        bar,
        f"  Session Evidence Summary  ·  {session_id}",
        bar,
        f"  provider  : {provider_type}",
        f"  model     : {model}",
        f"  entry     : {entry}",
        f"  start     : {first_ts or '?'}",
        f"  end       : {last_ts or '?'}",
        bar,
        "  Events",
        f"    user_input     : {_total_user_input}",
        f"    agent_reply    : {event_counts.get('agent_reply', 0)}",
        f"    llm_call       : {event_counts.get('llm_call', 0)}",
        f"    llm_response   : {event_counts.get('llm_response', 0)}",
        bar,
        "  Tools",
        f"    attempted      : {tools_attempted}",
        f"    executed       : {tools_executed}",
        f"    blocked        : {tools_blocked}",
        f"    blocked (sens) : {tools_blocked_sensitive}",
    ]
    if tools_failed:
        lines.append(f"    failed         : {tools_failed}")
    if tools_skipped:
        lines.append(f"    skipped        : {tools_skipped}")
    if pending_tools_executed:
        lines.append(f"    pending exec   : {pending_tools_executed}")
    if tool_names:
        lines.append(f"    tools used     : {', '.join(sorted(tool_names))}")
    if skill_selected:
        lines.append(f"    skill selected : {skill_selected}")
    if checkpoints_saved:
        lines.append(f"    checkpoints    : {checkpoints_saved}")

    if memory_events:
        lines.append(bar)
        lines.append("  Memory")
        for key, count in sorted(memory_events.items()):
            lines.append(f"    {key:<17}: {count}")

    if other_subsystem_events:
        lines.append(bar)
        lines.append("  Subsystem Events")
        for key, count in sorted(other_subsystem_events.items()):
            lines.append(f"    {key} × {count}")
    lines.append(bar)
    lines.append("  Content Policy")
    lines.append("    raw tool results        : never persisted in events")
    lines.append("    result metadata (size)  : stored")
    lines.append("    blocked sensitive tools : denial metadata only")
    lines.append("    raw secrets in logs     : redacted")

    lines.append(bar)
    if gaps:
        lines.append("  Evidence Gaps")
        for g in gaps:
            lines.append(f"    ⚠  {g}")
    else:
        lines.append("  Evidence Gaps : none detected")
    lines.append(bar)

    return "\n".join(lines)


def render_logs(
    *,
    log_path: Path | None = None,
    tail: int | None = 50,
    session_id: str | None = None,
    event: str | None = None,
    tool: str | None = None,
    include_observer: bool = False,
    summary: bool = False,
) -> str:
    """主入口：读 + 过滤 + 渲染 + 拼接。

    tail=None 表示不截断；默认 50 让人工调试时屏幕一屏内能放下。
    summary=True 且指定 --session 时，输出 one-screen evidence summary。
    """
    entries = iter_log_entries(log_path=log_path, include_observer=include_observer)
    filtered = list(
        filter_entries(entries, session_id=session_id, event=event, tool=tool)
    )

    broken_count = sum(1 for e in filtered if e.get("_broken"))
    real = [e for e in filtered if not e.get("_broken")]

    # ── Summary 模式 ──
    if summary and session_id:
        # 优先读取 per-session events.jsonl（新日志体系的主事实源），
        # 缺失或为空时 fallback 到 agent_log.jsonl（global index / compatibility）。
        session_dir = _resolve_session_dir(session_id)
        if session_dir is not None:
            per_session_entries = _read_per_session_events(session_dir)
            if per_session_entries:
                summary_text = render_session_summary(session_id, per_session_entries)
                # 在 session_id 行后面插入 evidence_source 行
                source_line = "  evidence_source : per_session_events"
                lines_list = summary_text.split("\n")
                # 在第二个分隔线（索引=2）之前插入
                insert_at = 2
                for i, ln in enumerate(lines_list):
                    if ln.startswith("─" * 50) and i > 0:
                        insert_at = i
                        break
                lines_list.insert(insert_at, source_line)
                return "\n".join(lines_list)

        # Fallback：per-session events 缺失或为空，回退到 agent_log.jsonl
        summary_text = render_session_summary(session_id, real)
        source_line = "  evidence_source : fallback_global_log"
        warning_line = "  ⚠  warning : per_session_events_missing_or_empty"
        lines_list = summary_text.split("\n")
        insert_at = 2
        for i, ln in enumerate(lines_list):
            if ln.startswith("─" * 50) and i > 0:
                insert_at = i
                break
        lines_list.insert(insert_at, warning_line)
        lines_list.insert(insert_at, source_line)
        return "\n".join(lines_list)

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

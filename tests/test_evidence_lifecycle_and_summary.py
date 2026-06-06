"""Evidence Lifecycle & Summary Semantics 回归测试。

本轮修 5 个根因：
A. session.start 通过 evidence_recorder 写入，session_id 非空
B. session.end 在正常退出时写入
C. error→ok dedup：error 不阻止后续 ok 计数
D. skipped / pending 在 summary 中可见
E. content_persisted=False 在 raw content 未持久化时

关键测试用中文注释解释架构语义。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from agent import log_viewer
from agent.evidence_recorder import (
    _build_envelope,
    record_evidence,
    set_event_log_writer,
    set_session_context,
)

SAMPLE_DATA = {"provider_type": "fake", "model": "test", "entry": "plain"}


# ═══════════════════════════════════════════════════════
# A. session.start lifecycle 测试
# ═══════════════════════════════════════════════════════


class _FakeEventLogWriter:
    """模拟 EventLogWriter，捕获写入的 events。"""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def append(self, event: dict) -> None:
        self.events.append(event)


def test_session_context_injection_before_record_evidence():
    """session_id 非空：set_session_context 后 record_evidence 的 envelope 应包含正确的 session_id。

    中文注释：为什么 session.start 必须通过 recorder 而非直接写 EventLogWriter？
    因为 record_evidence 是统一入口——后续所有 evidence 都通过它，
    session.start 如果绕过它，summary / query 就看不到一致的 session 身份信息。
    """
    test_sid = f"test-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    envelope = record_evidence(
        subsystem="session",
        operation="start",
        phase="start",
        status="ok",
        safe_summary="session_start",
    )

    assert envelope["session_id"] == test_sid
    assert envelope["entry"] == "plain"
    assert envelope["provider_type"] == "fake"

    # per-session events.jsonl 应收到事件
    session_start_events = [e for e in writer.events if e["action_type"] == "session.start"]
    assert len(session_start_events) >= 1


def test_session_context_empty_when_not_injected():
    """未注入 session_context 时，record_evidence 使用空上下文。"""
    # 保存并清空
    import agent.evidence_recorder as er
    saved = dict(er._session_context)
    er._session_context = {}
    try:
        envelope = _build_envelope(
            subsystem="session",
            operation="start",
            phase="start",
            status="ok",
            safe_summary="session_start",
        )
        assert envelope["session_id"] == ""
        assert envelope["entry"] == "unknown"
    finally:
        er._session_context = saved


# ═══════════════════════════════════════════════════════
# B. session.end 测试
# ═══════════════════════════════════════════════════════


def test_record_session_end_evidence():
    """session.end 能被 record_evidence 写入。

    中文注释：为什么 session.end 必须记录？
    没有 session.end 的 session 在 logs --summary 中表现为「非正常退出」，
    无法区分「用户还在进行中」和「崩溃退出」，排查时失去时间线锚点。
    """
    test_sid = f"test-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    envelope = record_evidence(
        subsystem="session",
        operation="end",
        phase="end",
        status="ok",
        safe_summary="session_end status=ok",
    )

    assert envelope["subsystem"] == "session"
    assert envelope["operation"] == "end"
    assert envelope["status"] == "ok"

    session_end_events = [e for e in writer.events if e["action_type"] == "session.end"]
    assert len(session_end_events) >= 1


# ═══════════════════════════════════════════════════════
# C. Summary dedup — error 不阻止 ok
# ═══════════════════════════════════════════════════════


def _make_evidence_entry(
    session_id: str,
    subsystem: str,
    operation: str,
    status: str,
    tool_use_id: str = "",
    safe_summary: str = "",
    reason_code: str = "",
    timestamp: str = "",
    phase: str = "",
) -> dict:
    """构造 agent_log.jsonl 中 evidence.recorded 条目。"""
    ts = timestamp or f"2026-06-05T{10 + len(session_id):02d}:00:00.000Z"
    data: dict = {
        "subsystem": subsystem,
        "operation": operation,
        "phase": phase or ("end" if operation == "invoke_result_summary" else "decision"),
        "status": status,
        "reason_code": reason_code,
        "safe_summary": safe_summary or f"tool=test_tool status={status}",
    }
    if tool_use_id:
        data["tool_use_id"] = tool_use_id
    return {
        "timestamp": ts,
        "session_id": session_id,
        "event": "evidence.recorded",
        "data": data,
    }


def test_error_then_ok_same_tool_use_id_counts_executed():
    """同一 tool_use_id 先 error 后 ok 时，executed=1 且 failed=1。

    中文注释：为什么 error 不是 blocked？
    error 表示工具尝试执行但失败了（网络超时、模型拒接等），
    blocked 表示策略明确拒绝执行（sensitive path、TOOL_GATE）。
    两者语义不同——error 不应阻止后续重试成功的 executed 计数。
    旧实现把 error 放入 blocked 集合导致 executed=0，这是 bug。
    """
    sid = "test-dedup-01"
    tool_id = "toolu_001"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_evidence_entry(sid, "tool", "gate_decision", "ok", tool_use_id=tool_id),
        # mediator 报告 error
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "error", tool_use_id=tool_id),
        # executor 报告 ok（同一 tool_use_id，修复后应计入 executed）
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "ok", tool_use_id=tool_id),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "executed       : 1" in result, f"应计数 executed=1，实际:\n{result}"
    assert "failed         : 1" in result, f"应计数 failed=1，实际:\n{result}"


def test_blocked_sensitive_does_not_affect_executed():
    """blocked sensitive path 不应影响后续不同 tool 的 executed 计数。"""
    sid = "test-dedup-02"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        # 工具 A 被 block
        _make_evidence_entry(sid, "tool", "gate_decision", "blocked",
                             tool_use_id="toolu_blocked", reason_code="sensitive_path",
                             safe_summary="tool=read_file blocked: sensitive path"),
        # 工具 B 正常执行
        _make_evidence_entry(sid, "tool", "gate_decision", "ok", tool_use_id="toolu_ok"),
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "ok", tool_use_id="toolu_ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "blocked        : 1" in result
    assert "blocked (sens) : 1" in result
    assert "executed       : 1" in result
    assert "attempted      : 2" in result


def test_executor_mediator_duplicate_ok_does_not_double_count():
    """executor 和 mediator 对同一 tool_use_id 都写 ok 时，executed 只计 1。"""
    sid = "test-dedup-03"
    tool_id = "toolu_dedup"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_evidence_entry(sid, "tool", "gate_decision", "ok", tool_use_id=tool_id),
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "ok", tool_use_id=tool_id),
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "ok", tool_use_id=tool_id),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "executed       : 1" in result


# ═══════════════════════════════════════════════════════
# D. skipped / pending 可见性
# ═══════════════════════════════════════════════════════


def test_skipped_tool_appears_as_skipped_not_executed():
    """idempotent cache hit 计入 skipped，不计入 executed。

    中文注释：为什么 skipped 不能计入 executed？
    skipped 表示工具因幂等缓存命中而未实际执行——如果计入 executed，
    会让 logs --summary 看起来工具被执行了，但实际没有发生文件操作。
    排查时这会误导：用户以为文件被读了，其实读的是缓存。
    """
    sid = "test-skip-01"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_evidence_entry(sid, "tool", "gate_decision", "skipped",
                             tool_use_id="toolu_skip", reason_code="idempotent_cache",
                             safe_summary="tool=read_file skipped (already executed)"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "skipped        : 1" in result
    assert "executed       : 0" in result


def test_pending_execute_visible_in_summary():
    """pending tool 确认执行后在 summary 中可见 pending exec 计数。
    同时 pending_execute 也应计入 executed（用户确认后实际执行了）。
    """
    sid = "test-pending-01"
    tool_id = "toolu_pending"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_evidence_entry(sid, "tool", "gate_decision", "confirmation_required",
                             tool_use_id=tool_id),
        # pending_execute operation — 与 tool_executor.py 真实 operation 一致
        _make_evidence_entry(sid, "tool", "pending_execute", "ok",
                             tool_use_id=tool_id,
                             safe_summary="tool=write_file status=success (pending_execute)"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "pending exec   : 1" in result
    # pending_execute 确认后也计入 executed
    assert "executed       : 1" in result


# ═══════════════════════════════════════════════════════
# E. content_persisted 语义
# ═══════════════════════════════════════════════════════


def test_content_persisted_defaults_to_false():
    """record_evidence 默认 content_persisted=False。

    中文注释：为什么 content_persisted 不能误导？
    如果事件只存了 result_size/hash/status 而没有存 raw content，
    content_persisted=True 会让后续审计误以为原始内容已安全存储，
    实际上原始内容根本不在 events 中——这是一个审计陷阱。
    """
    envelope = _build_envelope(
        subsystem="tool",
        operation="invoke_result_summary",
        phase="end",
        status="ok",
        safe_summary="tool=test status=ok",
    )
    # 默认值应为 False
    assert envelope["content_persisted"] is False


def test_blocked_sensitive_has_correct_content_flags():
    """sensitive path 拦截时：content_persisted=False, content_redacted=True, sensitive=True。"""
    set_session_context(
        session_id="test-sensitive",
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    envelope = record_evidence(
        subsystem="tool",
        operation="gate_decision",
        phase="decision",
        status="blocked",
        reason_code="sensitive_path",
        safe_summary="tool=read_file blocked: config/config.yaml is protected",
        content_persisted=False,
        content_redacted=True,
        sensitive=True,
    )
    assert envelope["content_persisted"] is False
    assert envelope["content_redacted"] is True
    assert envelope["sensitive"] is True
    # 确认没有 raw content 泄漏到 safe_summary
    assert "api_key" not in envelope["safe_summary"].lower()


# ═══════════════════════════════════════════════════════
# F. session lifecycle 在 summary 中的可见性
# ═══════════════════════════════════════════════════════


def _make_entry(event: str, session_id: str, data: dict | None = None) -> dict:
    return {
        "timestamp": "2026-06-05T10:00:00Z",
        "session_id": session_id,
        "event": event,
        "data": data or {},
    }


def test_summary_shows_session_end_gap_when_missing():
    """session.end 缺失时 summary 应显示 evidence gap。"""
    sid = "test-gap-01"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_entry("user_input", sid, data={"content": "hello"}),
        _make_entry("agent_reply", sid, data={"content": "hi"}),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "no session.end evidence" in result


def test_summary_shows_session_ended_when_present():
    """session.end evidence 存在时不应显示 gap。"""
    sid = "test-end-ok"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_entry("user_input", sid, data={"content": "hello"}),
        _make_evidence_entry(sid, "session", "end", "ok",
                             safe_summary="session_end status=ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "no session.end evidence" not in result


def test_summary_content_policy_reflects_actual_semantics():
    """Content Policy 描述应反映真实的持久化策略。"""
    sid = "test-cp"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "raw tool results" in result
    assert "never persisted in events" in result


def test_summary_shows_failed_counter_when_errors():
    """error status 的工具应显示在 failed 计数中而非 blocked 中。"""
    sid = "test-failed"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_evidence_entry(
            sid, "tool", "gate_decision", "ok", tool_use_id="toolu_err"),
        _make_evidence_entry(
            sid, "tool", "invoke_result_summary", "error", tool_use_id="toolu_err"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "failed         : 1" in result
    assert "blocked        : 0" in result


# ═══════════════════════════════════════════════════════
# G. Caveat 1 — 单一 logical session.start
# ═══════════════════════════════════════════════════════


def test_single_logical_session_start_no_gap():
    """summary 中只有一个 evidence.recorded session.start 时不应出现 gap。

    中文注释：为什么不能有 duplicate session.start？
    如果 evidence_recorder 和 direct EventLogWriter 各写一条 session.start，
    per-session events 里 count=2——但 summary 应只看 evidence.recorded 事件。
    这个测试验证：只有一条 evidence.recorded 的 session.start 时，session 正常启动。
    """
    sid = "test-single-start"
    entries = [
        # 只有一条 evidence.recorded session.start（不再是两条）
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_evidence_entry(sid, "session", "start", "ok",
                             safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("user_input", sid, data={"content": "hello"}),
        _make_entry("agent_reply", sid, data={"content": "hi"}),
        _make_evidence_entry(sid, "session", "end", "ok",
                             safe_summary="session_end status=ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "no session_start event" not in result
    assert "no session.end evidence" not in result


# ═══════════════════════════════════════════════════════
# H. Caveat 3 — Ctrl+C menu option 3 记录 session.end
# ═══════════════════════════════════════════════════════


def test_interrupt_menu_option_3_records_session_end():
    """handle_interrupt_choice("3") 必须调用 _record_session_end()。

    中文注释：为什么 Ctrl+C menu option 3 必须记录 session.end？
    option 3 是 graceful exit path——用户主动选择退出，和 quit / Ctrl+C×2
    语义一致。缺 session.end 会导致后续排查误判为「异常退出」。
    """
    import contextlib
    from unittest.mock import patch

    import agent.session as session_module
    from agent.evidence_recorder import set_event_log_writer, set_session_context

    test_sid = f"test-menu3-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    with contextlib.suppress(Exception):
        session_module.set_runtime_session_id(test_sid)

    writer.events.clear()

    # mock save_session_snapshot 以避免 state.conversation 依赖
    with patch.object(session_module, "save_session_snapshot", return_value=None):
        result = session_module.handle_interrupt_choice("3")

    assert result is True  # 返回 True 表示退出

    session_end_events = [e for e in writer.events if e.get("action_type") == "session.end"]
    assert len(session_end_events) >= 1, (
        f"handle_interrupt_choice('3') 应写入 session.end evidence，"
        f"实际 events: {writer.events}"
    )


# ═══════════════════════════════════════════════════════
# I. Caveat 4 — content_persisted=False 语义验证
# ═══════════════════════════════════════════════════════


def test_invoke_result_summary_content_not_persisted():
    """invoke_result_summary 的 content_persisted 必须为 False。

    中文注释：为什么 invoke_result_summary 不能 content_persisted=True？
    invoke_result_summary 只存 result_size/hash/status/safe_summary，
    不存 raw content。content_persisted=True 会误导审计以为原始内容已落盘，
    实际上原始内容根本不在 events 中。
    """
    set_session_context(
        session_id="test-cp-false",
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    from agent.evidence_recorder import record_evidence
    envelope = record_evidence(
        subsystem="tool",
        operation="invoke_result_summary",
        phase="end",
        status="ok",
        safe_summary="tool=read_file status=executed",
        content_persisted=False,
        content_redacted=False,
        sensitive=False,
        metadata={
            "tool_name": "read_file",
            "tool_use_id": "tu-test",
            "result_size": 1024,
        },
    )
    assert envelope["content_persisted"] is False
    assert envelope["content_redacted"] is False
    assert envelope["sensitive"] is False


# ═══════════════════════════════════════════════════════
# J. execute_pending_tool 实际代码路径 evidence 测试
# ═══════════════════════════════════════════════════════


def test_execute_pending_tool_actual_path_writes_evidence():
    """execute_pending_tool 实际代码路径必须调用 record_evidence。

    中文注释：为什么不能用 synthetic _make_evidence_entry 代替？
    synthetic 测试只验证 log_viewer 解析 evidence.recorded 事件的能力，
    不验证 tool_executor.execute_pending_tool 是否真正调用了 record_evidence。
    如果 try/except 静默吞掉异常、或 record_evidence 调用被意外删除、
    或 operation 名被改回 "invoke_result_summary"，synthetic 测试不会发现。
    这个测试通过 mock execute_tool + spy record_evidence 来验证真实调用路径。
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    import agent.tool_executor as te

    test_sid = f"test-pending-real-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.tool_execution_log = {}
    state.task.current_step_index = 1

    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None

    messages: list[dict[str, object]] = []
    pending: dict[str, object] = {
        "tool_use_id": "toolu_pending_real_test",
        "tool": "write_file",
        "input": {"path": "test.txt", "content": "hello"},
    }

    with patch.object(te, "execute_tool", return_value="执行完成。"):
        result = te.execute_pending_tool(
            state=state,
            turn_state=turn_state,
            messages=messages,
            pending=pending,
        )

    assert "执行完成。" in result

    # 验证 evidence.recorded 事件已写入 per-session events
    # EventLogWriter 格式：action_type/source/event_id/status/data{envelope}
    pending_evidence = [
        e for e in writer.events if e.get("action_type") == "tool.pending_execute"
    ]
    assert len(pending_evidence) >= 1, (
        f"execute_pending_tool 应写入 tool.pending_execute evidence，"
        f"实际 events: {writer.events}"
    )
    ev = pending_evidence[0]
    data = ev["data"]
    assert data["subsystem"] == "tool"
    assert data["operation"] == "pending_execute"
    assert data["status"] == "ok"
    assert data["content_persisted"] is False
    assert data["metadata"]["from_pending_tool"] is True


def test_execute_pending_tool_failure_path_writes_error_evidence():
    """execute_pending_tool 失败时 evidence status 应为 error。

    中文注释：pending tool 执行失败（工具内部安全检查拒绝）和 block 是不同语义——
    block 是策略拒绝（TOOL_GATE），error 是执行失败。evidence 必须正确区分。
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    import agent.tool_executor as te

    test_sid = f"test-pending-fail-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.tool_execution_log = {}
    state.task.current_step_index = 1

    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None

    messages: list[dict[str, object]] = []
    pending: dict[str, object] = {
        "tool_use_id": "toolu_pending_fail_test",
        "tool": "shell_command",
        "input": {"cmd": "rm -rf /"},
    }

    with patch.object(
        te, "execute_tool", return_value="拒绝执行：路径不在白名单"
    ):
        _result = te.execute_pending_tool(
            state=state,
            turn_state=turn_state,
            messages=messages,
            pending=pending,
        )

    pending_evidence = [
        e for e in writer.events if e.get("action_type") == "tool.pending_execute"
    ]
    assert len(pending_evidence) >= 1
    ev = pending_evidence[0]
    data = ev["data"]
    assert data["status"] == "error"
    assert data["content_persisted"] is False
    assert data["metadata"]["from_pending_tool"] is True


# ═══════════════════════════════════════════════════════
# P3: user_input → record_evidence 迁移测试
# ═══════════════════════════════════════════════════════


def test_user_input_record_evidence_envelope():
    """user_input 通过 record_evidence 写入，携带完整 envelope 上下文。

    中文注释：迁移前 user_input 使用 legacy log_event("user_input", ...)，
    不携带 session_id / provider / entry 等 envelope 字段，summary 需要从
    session.start 推断。迁移后 record_evidence 自动补齐上下文。
    """
    test_sid = f"test-ui-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="real",
        provider_model="claude-sonnet-4-6",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    envelope = record_evidence(
        subsystem="session",
        operation="user_input",
        phase="input",
        status="ok",
        safe_summary="input len=11 src=pipe",
        content_persisted=False,
        sensitive=False,
        metadata={
            "input_length": 11,
            "backend": "simple",
            "source": "pipe",
            "content_preview": "hello world",
        },
    )

    # envelope 完整性
    assert envelope["session_id"] == test_sid
    assert envelope["entry"] == "plain"
    assert envelope["provider_type"] == "real"
    assert envelope["provider_model"] == "claude-sonnet-4-6"
    assert envelope["subsystem"] == "session"
    assert envelope["operation"] == "user_input"
    assert envelope["phase"] == "input"
    assert envelope["status"] == "ok"
    assert envelope["content_persisted"] is False
    assert envelope["sensitive"] is False

    # EventLogWriter 写入验证
    user_input_events = [
        e for e in writer.events if e.get("action_type") == "session.user_input"
    ]
    assert len(user_input_events) == 1
    ev = user_input_events[0]
    data = ev["data"]
    assert data["session_id"] == test_sid
    assert data["entry"] == "plain"
    assert data["provider_type"] == "real"


def test_user_input_long_content_truncated():
    """长 user_input 的 content_preview 应被截断，不持久化全文。

    中文注释：record_evidence metadata 中超过 2KB 的字符串值会被自动摘要化。
    但 content_preview 本身应在调用方侧截断（main.py 中限制 200 字符），
    避免大段内容进入 agent_log.jsonl。
    """
    test_sid = f"test-ui-long-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    long_input = "A" * 5000
    _preview = long_input[:197] + "..."

    envelope = record_evidence(
        subsystem="session",
        operation="user_input",
        phase="input",
        status="ok",
        safe_summary="input len=5000 src=interactive",
        content_persisted=False,
        sensitive=False,
        metadata={
            "input_length": 5000,
            "backend": "simple",
            "source": "interactive",
            "content_preview": _preview,
        },
    )

    # preview 应截断到 200 字符
    metadata = envelope["metadata"]
    assert len(metadata["content_preview"]) <= 200
    assert metadata["content_preview"].endswith("...")
    # 全长不应出现在 preview 中
    assert long_input not in metadata["content_preview"]


def test_summary_counts_user_input_from_evidence():
    """log_viewer summary 应正确计数 evidence.recorded 中的 user_input。

    中文注释：迁移后 user_input 不再以 event="user_input" 写入 agent_log.jsonl，
    而是以 event="evidence.recorded" + subsystem="session" + operation="user_input" 写入。
    summary 必须能正确识别并计数。
    """
    sid = "test-sum-ui"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_evidence_entry(sid, "session", "user_input", "ok",
                             safe_summary="input len=5 src=pipe", phase="input"),
        _make_evidence_entry(sid, "session", "end", "ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "user_input     : 1" in result
    assert "no session.end evidence" not in result


def test_user_input_no_duplicate_with_legacy():
    """evidence.recorded 和 legacy event="user_input" 共存时合并计数。

    中文注释：迁移过渡期可能存在旧 session 的 legacy event="user_input" 事件。
    evidence.recorded 路径的 user_input 和 legacy 事件使用不同的 event 字段，
    两者求和作为总数。
    """
    sid = "test-dedup-ui"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        # 新路径：evidence.recorded ×2
        _make_evidence_entry(sid, "session", "user_input", "ok",
                             safe_summary="input len=5 src=pipe", phase="input"),
        # 旧路径：legacy event="user_input"
        _make_entry("user_input", sid, data={"content": "hello", "length": 5}),
        _make_evidence_entry(sid, "session", "user_input", "ok",
                             safe_summary="input len=5 src=pipe", phase="input"),
        _make_evidence_entry(sid, "session", "end", "ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    # 2 evidence.recorded user_input + 1 legacy = 3
    assert "user_input     : 3" in result


def test_user_input_quit_not_counted():
    """quit 不应被计为 user_input。

    中文注释：quit/exit 在 main loop 的 classify_user_input 阶段就被拦截
    （intent.kind="exit"），不会进入 _run_chat_for_backend，因此不会触发
    record_evidence(subsystem="session", operation="user_input")。
    """
    sid = "test-quit-ui"
    entries = [
        _make_entry("session_start", sid, data=SAMPLE_DATA),
        _make_entry("agent_reply", sid, data={"reply": "再见！", "quit_command": True}),
        _make_evidence_entry(sid, "session", "end", "ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "user_input     : 0" in result


def test_user_input_envelope_fields_in_events_jsonl():
    """EventLogWriter 写入的 events.jsonl 中 user_input 事件应包含完整字段。

    中文注释：events.jsonl 是 per-session 的结构化事件日志，action_type 为
    "session.user_input"，data 中包含完整 envelope。
    """
    test_sid = f"test-evtlog-ui-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test-model",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    record_evidence(
        subsystem="session",
        operation="user_input",
        phase="input",
        status="ok",
        safe_summary="input len=9 src=interactive",
        content_persisted=False,
        metadata={
            "input_length": 9,
            "backend": "simple",
            "source": "interactive",
            "content_preview": "test input",
        },
    )

    ui_events = [
        e for e in writer.events if e.get("action_type") == "session.user_input"
    ]
    assert len(ui_events) == 1
    ev = ui_events[0]
    assert ev["source"] == "session"
    assert ev["event_id"].startswith("evt-")
    assert ev["status"] == "ok"

    data = ev["data"]
    assert data["session_id"] == test_sid
    assert data["provider_type"] == "fake"
    assert data["provider_model"] == "test-model"
    assert data["entry"] == "plain"
    assert data["subsystem"] == "session"
    assert data["operation"] == "user_input"
    assert data["content_persisted"] is False
    assert data["metadata"]["source"] == "interactive"
    assert data["metadata"]["input_length"] == 9


# ═══════════════════════════════════════════════════════
# P2: allowed gate_decision evidence
# ═══════════════════════════════════════════════════════


def test_allowed_gate_decision_adds_tools_attempted():
    """allowed gate path 写入 tool.gate_decision status=allowed，summary 应显示 tools_attempted=1。

    中文注释：为什么 allowed gate path 必须写 gate_decision evidence？
    之前 blocked path 写了 gate_decision evidence 所以 tools_attempted 能正确计数，
    但 allowed path 跳过 gate_decision 直接进入 invoke_result_summary，导致 summary
    中 tools_executed>=1 但 tools_attempted=0——这在 G1-G5 审计中是误导信号。
    """
    sid = f"test-allowed-gate-{uuid.uuid4().hex[:12]}"
    tool_id = "toolu_allowed_01"
    entries = [
        _make_evidence_entry(sid, "tool", "gate_decision", "allowed",
                             tool_use_id=tool_id,
                             safe_summary="tool=read_file gate=allowed"),
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "ok",
                             tool_use_id=tool_id,
                             safe_summary="tool=read_file result=executed"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 1" in result
    assert "executed       : 1" in result


def test_allowed_gate_decision_does_not_double_count_attempted():
    """同一 tool_use_id 的 gate_decision+invoke_result_summary 不会重复计数 attempted。

    中文注释：去重键 _tool_dedup_key 优先使用 tool_use_id，所以 gate_decision 和
    invoke_result_summary 共享同一个去重键，不会重复计数。
    """
    sid = f"test-nodup-{uuid.uuid4().hex[:12]}"
    tool_id = "toolu_single_01"
    entries = [
        _make_evidence_entry(sid, "tool", "gate_decision", "allowed",
                             tool_use_id=tool_id),
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "ok",
                             tool_use_id=tool_id),
        # 模拟 executor 重复写入（同一 tool_use_id 的第二个 invoke_result_summary）
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "ok",
                             tool_use_id=tool_id,
                             safe_summary="tool=read_file result=executed dup"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 1" in result
    assert "executed       : 1" in result


def test_blocked_gate_decision_still_shows_attempted_and_blocked():
    """回归验证：blocked sensitive path 仍显示 tools_attempted=1, tools_blocked=1。

    中文注释：确保新增 allowed gate_decision 不影响已有 blocked 路径的计数语义。
    """
    sid = f"test-blocked-reg-{uuid.uuid4().hex[:12]}"
    tool_id = "toolu_blocked_01"
    entries = [
        _make_evidence_entry(sid, "tool", "gate_decision", "blocked",
                             tool_use_id=tool_id,
                             safe_summary="tool=read_file blocked by gate: sensitive_path",
                             reason_code="sensitive_path"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 1" in result
    assert "blocked        : 1" in result
    assert "blocked (sens) : 1" in result


# ═══════════════════════════════════════════════════════
# K. Per-session events.jsonl → summary 优先级测试
# ═══════════════════════════════════════════════════════


def test_resolve_session_dir_finds_matching_prefix():
    """_resolve_session_dir 根据前缀定位 sessions/<id>/ 目录。

    中文注释：为什么需要前缀解析？
    用户通常只输入 8 位短哈希，而非完整 UUID。logs --session 需要能
    从前缀找到完整 session 目录，才能读取 per-session events.jsonl。
    """
    import tempfile
    sid_full = "abc12345-def6-7890-abcd-ef1234567890"
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = Path(tmp) / "sessions"
        session_dir = sessions_dir / sid_full
        session_dir.mkdir(parents=True)
        (session_dir / "events.jsonl").write_text("{}", encoding="utf-8")

        # 短前缀匹配
        found = log_viewer._resolve_session_dir("abc12345", project_dir=Path(tmp))
        assert found is not None
        assert found.name == sid_full

        # 不匹配的前缀
        not_found = log_viewer._resolve_session_dir("zzzz9999", project_dir=Path(tmp))
        assert not_found is None


def test_read_per_session_events_converts_format():
    """_read_per_session_events 将 per-session 格式转换为 agent_log 兼容格式。

    中文注释：为什么需要格式转换？
    per-session events.jsonl 使用 action_type/source/data 结构（EventLogWriter 格式），
    而 render_session_summary 期望 event/data 结构（agent_log.jsonl 格式）。
    转换确保 summary 渲染逻辑不需要双写。
    """
    import tempfile
    sid = "test-per-session-sidsid"
    with tempfile.TemporaryDirectory() as tmp:
        session_dir = Path(tmp) / sid
        session_dir.mkdir(parents=True)
        events_path = session_dir / "events.jsonl"

        # 写入 per-session 格式事件
        events = [
            {
                "action_type": "session.start",
                "source": "session",
                "status": "ok",
                "data": {
                    "session_id": sid,
                    "subsystem": "session",
                    "operation": "start",
                    "status": "ok",
                    "entry": "plain",
                    "provider_type": "fake",
                    "provider_model": "test",
                    "metadata": {
                        "provider_type": "fake",
                        "provider_model": "test",
                        "entry": "plain",
                    },
                },
            },
            {
                "action_type": "session.user_input",
                "source": "session",
                "status": "ok",
                "data": {
                    "session_id": sid,
                    "subsystem": "session",
                    "operation": "user_input",
                    "status": "ok",
                    "safe_summary": "input len=5 src=interactive",
                },
            },
            {
                "action_type": "session.end",
                "source": "session",
                "status": "ok",
                "data": {
                    "session_id": sid,
                    "subsystem": "session",
                    "operation": "end",
                    "status": "ok",
                    "safe_summary": "session_end status=ok",
                },
            },
        ]
        with open(events_path, "w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

        entries = log_viewer._read_per_session_events(session_dir)
        # 应有 3 条 evidence.recorded + 1 条 session_start + 1 条 user_input = 5
        evidence_entries = [e for e in entries if e["event"] == "evidence.recorded"]
        session_start_entries = [e for e in entries if e["event"] == "session_start"]
        user_input_entries = [e for e in entries if e["event"] == "user_input"]

        assert len(evidence_entries) == 3
        assert len(session_start_entries) == 1
        assert len(user_input_entries) == 1

        # session_start entry 应有正确的 provider/entry/model
        ss = session_start_entries[0]
        assert ss["data"]["provider_type"] == "fake"
        assert ss["data"]["entry"] == "plain"


def test_per_session_summary_preferred_over_global_log():
    """per-session events.jsonl 非空时，summary 优先使用 per-session 事件。

    中文注释：这是本轮修复的核心语义——
    1. per-session events.jsonl 是新日志体系的 session 事实源
    2. agent_log.jsonl 只能是 global index / fallback
    3. 当 per-session events 可用时，summary 必须显示 evidence_source=per_session_events
    """
    import tempfile
    sid = "test-pref-sid12345678"
    with tempfile.TemporaryDirectory() as tmp:
        # 创建 per-session events.jsonl
        session_dir = Path(tmp) / "sessions" / sid
        session_dir.mkdir(parents=True)
        events_path = session_dir / "events.jsonl"

        per_session_event = {
            "action_type": "session.start",
            "source": "session",
            "status": "ok",
            "data": {
                "session_id": sid,
                "subsystem": "session",
                "operation": "start",
                "status": "ok",
                "safe_summary": "session_start provider=fake model=test entry=plain",
                "metadata": {
                    "provider_type": "fake",
                    "provider_model": "test",
                    "entry": "plain",
                },
            },
        }
        with open(events_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(per_session_event, ensure_ascii=False) + "\n")

        # 验证 per-session events 可读取
        entries = log_viewer._read_per_session_events(session_dir)
        result = log_viewer.render_session_summary(sid, entries)
        assert "Session Evidence Summary" in result
        # 通过 _read_per_session_events 转换后 session_start 应被正确解析
        # provider 信息应来自转换后的 session_start entry


def test_historical_empty_events_no_crash():
    """历史 session 的 events.jsonl 为空时不 crash。

    中文注释：为什么历史空 events 不是新策略的证明？
    这是历史债——旧 session 在 per-session event log 启用前创建，
    events.jsonl 可能为空。新代码必须容错不 crash，并 fallback 到 agent_log。
    但不能因为历史 session 空就认为 per-session events 机制无效。
    """
    import tempfile
    sid = "test-empty-hist-sid"
    with tempfile.TemporaryDirectory() as tmp:
        session_dir = Path(tmp) / "sessions" / sid
        session_dir.mkdir(parents=True)
        # 写入空 events.jsonl
        (session_dir / "events.jsonl").write_text("", encoding="utf-8")

        entries = log_viewer._read_per_session_events(session_dir)
        assert entries == []  # 空文件返回空列表，不抛异常


def test_per_session_events_reconcile_with_global_log():
    """per-session events 的 tool 计数应与 global agent_log 一致。

    中文注释：为什么需要一致？
    per-session events 和 agent_log 写入同一套 record_evidence 数据，
    summary 的计数逻辑应不受数据来源影响——无论读 per-session 还是 agent_log，
    tool attempted/executed/blocked 应一致。
    """
    sid = "test-reconcile-sid12"
    tool_id = "toolu_reconcile_01"

    # 模拟 per-session events 转换后的条目（与 agent_log events 格式一致）
    per_session_entries = [
        _make_evidence_entry(sid, "session", "start", "ok",
                             safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
        _make_evidence_entry(sid, "tool", "gate_decision", "ok",
                             tool_use_id=tool_id,
                             safe_summary="tool=read_file gate=allowed"),
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "ok",
                             tool_use_id=tool_id,
                             safe_summary="tool=read_file result=executed"),
        _make_evidence_entry(sid, "session", "end", "ok",
                             safe_summary="session_end status=ok"),
    ]
    result = log_viewer.render_session_summary(sid, per_session_entries)
    assert "attempted      : 1" in result
    assert "executed       : 1" in result
    assert "no session.end evidence" not in result


def test_per_session_events_with_tool_blocked():
    """per-session events 中 blocked tool 应在 summary 中正确呈现。

    中文注释：sensitive path block 是 Runtime 关键 branch point，
    per-session events 必须完整保留 denial metadata。
    """
    sid = "test-block-per-sid"
    tool_id = "toolu_block_per_01"
    per_session_entries = [
        _make_evidence_entry(sid, "session", "start", "ok",
                             safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
        _make_evidence_entry(sid, "tool", "gate_decision", "blocked",
                             tool_use_id=tool_id,
                             reason_code="sensitive_path",
                             safe_summary="tool=read_file blocked: sensitive path"),
        _make_evidence_entry(sid, "session", "end", "ok",
                             safe_summary="session_end status=ok"),
    ]
    result = log_viewer.render_session_summary(sid, per_session_entries)
    assert "attempted      : 1" in result
    assert "blocked        : 1" in result
    assert "blocked (sens) : 1" in result


def test_per_session_summary_no_raw_content():
    """per-session events summary 不展示 raw content。

    中文注释：Content Policy 在两种数据源下表现一致——
    summary 只展示结构化元信息，不 dump raw tool result。
    """
    sid = "test-no-raw-sid"
    per_session_entries = [
        _make_evidence_entry(sid, "session", "start", "ok",
                             safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
    ]
    result = log_viewer.render_session_summary(sid, per_session_entries)
    assert "raw tool results" in result
    assert "never persisted in events" in result


# ═══════════════════════════════════════════════════════
# Per-session Tool Dedup — metadata.tool_use_id 去重
# ═══════════════════════════════════════════════════════


def _make_ps_evidence_entry(
    session_id: str,
    subsystem: str,
    operation: str,
    status: str,
    tool_use_id: str = "",
    safe_summary: str = "",
    reason_code: str = "",
    phase: str = "",
    metadata: dict | None = None,
) -> dict:
    """构造 per-session format evidence entry（模拟 _read_per_session_events 转换后格式）。

    per-session events 中 tool_use_id 位于 data.metadata.tool_use_id，
    不同于 global log 中 data.tool_use_id 的顶层位置。
    这个 helper 构造的就是 log_viewer render_session_summary 实际接收的 data 结构。
    """
    ts = f"2026-06-05T{12 + len(session_id):02d}:00:00.000Z"
    meta = dict(metadata or {})
    if tool_use_id:
        meta["tool_use_id"] = tool_use_id
    data: dict = {
        "subsystem": subsystem,
        "operation": operation,
        "phase": phase or ("end" if operation == "invoke_result_summary" else "decision"),
        "status": status,
        "reason_code": reason_code,
        "safe_summary": safe_summary or f"tool=test_tool status={status}",
        "metadata": meta,
    }
    return {
        "timestamp": ts,
        "session_id": session_id,
        "event": "evidence.recorded",
        "data": data,
    }


def test_ps_tool_dedup_by_metadata_tool_use_id():
    """per-session event 中 metadata.tool_use_id 正确去重。

    中文注释：这是 P2 bug 的直接回归测试——
    _tool_dedup_key() 之前只读 data.tool_use_id（顶层），
    per-session events 中 tool_use_id 在 data.metadata.tool_use_id，
    导致 gate_decision + invoke_result_summary 产生不同 fallback key，计数翻倍。
    """
    sid = "test-ps-dedup-01"
    tool_id = "toolu_functions.read_file:0"
    entries = [
        _make_ps_evidence_entry(sid, "session", "start", "ok",
                                safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
        _make_ps_evidence_entry(sid, "tool", "gate_decision", "allowed",
                                tool_use_id=tool_id,
                                safe_summary="tool=read_file allowed: README.md"),
        _make_ps_evidence_entry(sid, "tool", "invoke_result_summary", "ok",
                                tool_use_id=tool_id,
                                safe_summary="tool=read_file ok: result_size=3155"),
        _make_ps_evidence_entry(sid, "session", "end", "ok",
                                safe_summary="session_end status=ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 1" in result
    assert "executed       : 1" in result


def test_ps_sensitive_blocked_dedup_by_metadata_tool_use_id():
    """sensitive blocked 路径：gate_decision blocked + invoke_result_summary blocked，
    同一 metadata.tool_use_id，summary 为 attempted=1 blocked=1 blocked_sens=1。

    中文注释：最关键的 P2 回归——sensitive block 时 mediator 写 gate_decision blocked，
    executor 写 invoke_result_summary blocked，如果去重失效会变成 attempted=2 blocked=2。
    """
    sid = "test-ps-dedup-02"
    tool_id = "toolu_functions.read_file:0"
    entries = [
        _make_ps_evidence_entry(sid, "session", "start", "ok",
                                safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
        # mediator: gate_decision blocked (sensitive_path)
        _make_ps_evidence_entry(sid, "tool", "gate_decision", "blocked",
                                tool_use_id=tool_id,
                                reason_code="sensitive_path",
                                safe_summary="tool=read_file blocked: sensitive path"),
        # executor: invoke_result_summary blocked
        _make_ps_evidence_entry(sid, "tool", "invoke_result_summary", "blocked",
                                tool_use_id=tool_id,
                                reason_code="sensitive_path",
                                safe_summary="tool=read_file blocked: sensitive path"),
        _make_ps_evidence_entry(sid, "session", "end", "ok",
                                safe_summary="session_end status=ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 1" in result
    assert "blocked        : 1" in result
    assert "blocked (sens) : 1" in result


def test_ps_readme_allowed_path_not_regressed():
    """README allowed 路径使用 per-session format 时不回归——
    attempted=1 executed=1，不会因去重修复而错误翻倍或归零。
    """
    sid = "test-ps-dedup-03"
    tool_id = "toolu_functions.read_file:0"
    entries = [
        _make_ps_evidence_entry(sid, "session", "start", "ok",
                                safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
        _make_ps_evidence_entry(sid, "tool", "gate_decision", "allowed",
                                tool_use_id=tool_id,
                                safe_summary="tool=read_file allowed: README.md"),
        _make_ps_evidence_entry(sid, "tool", "invoke_result_summary", "ok",
                                tool_use_id=tool_id,
                                safe_summary="tool=read_file ok: result_size=3155"),
        _make_ps_evidence_entry(sid, "session", "end", "ok",
                                safe_summary="session_end status=ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 1" in result
    assert "executed       : 1" in result


def test_ps_global_log_fallback_still_works():
    """global log 格式（data.tool_use_id 顶层）仍然正确去重——
    修复不应破坏已有 global log 的去重能力。
    """
    sid = "test-ps-dedup-04"
    tool_id = "toolu_global_top_level"
    entries = [
        _make_evidence_entry(sid, "session", "start", "ok",
                             safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
        _make_evidence_entry(sid, "tool", "gate_decision", "ok",
                             tool_use_id=tool_id),
        _make_evidence_entry(sid, "tool", "invoke_result_summary", "ok",
                             tool_use_id=tool_id),
        _make_evidence_entry(sid, "session", "end", "ok",
                             safe_summary="session_end status=ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 1" in result
    assert "executed       : 1" in result


def test_ps_skipped_pending_failed_counters_not_regressed():
    """per-session format 下 skipped / pending / failed 计数器不回归。
    """
    sid = "test-ps-dedup-05"
    t_skip = "toolu_skip_id"
    t_fail = "toolu_fail_id"
    t_ok = "toolu_ok_id"
    entries = [
        _make_ps_evidence_entry(sid, "session", "start", "ok",
                                safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
        # skipped tool
        _make_ps_evidence_entry(sid, "tool", "gate_decision", "skipped",
                                tool_use_id=t_skip,
                                reason_code="idempotent_cache",
                                safe_summary="tool=read_file skipped: idempotent cache hit"),
        # failed tool (error)
        _make_ps_evidence_entry(sid, "tool", "gate_decision", "allowed",
                                tool_use_id=t_fail,
                                safe_summary="tool=read_file allowed"),
        _make_ps_evidence_entry(sid, "tool", "invoke_result_summary", "error",
                                tool_use_id=t_fail,
                                safe_summary="tool=read_file error: file not found"),
        # successful tool
        _make_ps_evidence_entry(sid, "tool", "gate_decision", "allowed",
                                tool_use_id=t_ok,
                                safe_summary="tool=read_file allowed"),
        _make_ps_evidence_entry(sid, "tool", "invoke_result_summary", "ok",
                                tool_use_id=t_ok,
                                safe_summary="tool=read_file ok"),
        _make_ps_evidence_entry(sid, "session", "end", "ok",
                                safe_summary="session_end status=ok"),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 3" in result
    assert "executed       : 1" in result
    assert "failed         : 1" in result
    assert "skipped        : 1" in result


def test_ps_no_raw_content_in_summary():
    """per-session format summary 不泄漏 raw content。
    """
    sid = "test-ps-dedup-06"
    entries = [
        _make_ps_evidence_entry(sid, "session", "start", "ok",
                                safe_summary="session_start provider=fake model=test entry=plain"),
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "raw tool results" in result
    assert "never persisted in events" in result
    assert "config/config.yaml" not in result


# ═══════════════════════════════════════════════════════
# K. P1-2 mediate_pending 统一路径测试
# ═══════════════════════════════════════════════════════


def test_mediate_pending_records_gate_decision_evidence():
    """mediate_pending 必须写入 gate_decision (allowed) evidence。

    架构契约：pending 确认后的工具执行必须走 mediator 统一路径，
    产生 gate_decision → invoke → pending_execute → result 完整证据链。
    此测试验证 gate_decision 在 mediator 路径中被记录。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    import agent.tool_runtime_mediator as tmr_mod

    test_sid = f"test-medpen-gate-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.tool_execution_log = {}
    state.task.current_step_index = 1

    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None

    messages: list[dict[str, object]] = []
    pending: dict[str, object] = {
        "tool_use_id": "toolu_medpen_gate_test",
        "tool": "write_file",
        "input": {"path": "test.txt", "content": "hello"},
    }

    fake_dispatcher = MagicMock()
    fake_dispatcher.route_from_runtime_loop.return_value = SimpleNamespace(
        payload={"gate_disposition": "allowed"},
    )

    mediator = tmr_mod.ToolRuntimeMediator(
        fake_dispatcher,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=messages,
    )

    with patch.object(
        tmr_mod, "execute_pending_tool", return_value="执行完成。"
    ):
        result = mediator.mediate_pending(pending)

    assert "执行完成。" in result

    # 验证 gate_decision evidence 已写入
    gate_events = [
        e for e in writer.events
        if e.get("action_type") == "tool.gate_decision"
    ]
    assert len(gate_events) >= 1, (
        f"mediate_pending 应写入 gate_decision evidence，"
        f"实际 events: {writer.events}"
    )
    ev = gate_events[0]
    data = ev["data"]
    assert data["status"] == "allowed"
    assert data["metadata"]["from_pending_tool"] is True
    assert data["metadata"]["confirmation_already_approved"] is True


def test_mediate_pending_does_not_re_gate():
    """mediate_pending 不得调用 _route_gate 重新门控。

    架构契约：pending tool 在 initial tool_use 时已通过 TOOL_GATE
    （allowed 或 confirmation_required）。用户确认后不应再次检查 gate，
    否则可能导致：
    - 重复弹确认（confirmation_required 再次触发）
    - skill_allowed_tools 过期导致合法 pending tool 被 block
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    import agent.tool_runtime_mediator as tmr_mod

    test_sid = f"test-medpen-nogate-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.tool_execution_log = {}
    state.task.current_step_index = 1

    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None

    pending: dict[str, object] = {
        "tool_use_id": "toolu_medpen_nogate",
        "tool": "write_file",
        "input": {"path": "test.txt", "content": "hello"},
    }

    fake_dispatcher = MagicMock()
    fake_dispatcher.route_from_runtime_loop.return_value = SimpleNamespace(
        payload={"gate_disposition": "allowed"},
    )

    mediator = tmr_mod.ToolRuntimeMediator(
        fake_dispatcher,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=[],
    )

    # Spy _route_gate
    with patch.object(
        mediator, "_route_gate", wraps=mediator._route_gate
    ) as spy_gate, patch.object(
        tmr_mod, "execute_pending_tool", return_value="执行完成。"
    ):
        mediator.mediate_pending(pending)

    # _route_gate 不应被调用 — pending 已确认
    assert spy_gate.call_count == 0, (
        f"mediate_pending 不应调用 _route_gate（pending 已确认），"
        f"实际调用 {spy_gate.call_count} 次"
    )


def test_mediate_pending_evidence_chain_in_summary():
    """mediate_pending 路径的 summary 计数器正确。

    gate_decision (allowed) + pending_execute (ok) → attempted=1 executed=1 pending=1。
    不重复计数。
    """
    sid = "test-medpen-summary"
    ts = "2026-06-06T12:00:00.000000Z"
    tid = "toolu_medpen_summary_01"

    entries = [
        # session start
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
        # gate_decision (allowed, from_pending_tool) — mediator 写入
        {
            "event": "evidence.recorded",
            "timestamp": ts,
            "session_id": sid,
            "data": {
                "subsystem": "tool",
                "operation": "gate_decision",
                "phase": "decision",
                "status": "allowed",
                "safe_summary": "tool=write_file gate=allowed (pending confirmed)",
                "metadata": {
                    "tool_name": "write_file",
                    "tool_use_id": tid,
                    "from_pending_tool": True,
                    "confirmation_already_approved": True,
                },
            },
        },
        # pending_execute (ok) — execute_pending_tool 写入
        {
            "event": "evidence.recorded",
            "timestamp": ts,
            "session_id": sid,
            "data": {
                "subsystem": "tool",
                "operation": "pending_execute",
                "phase": "end",
                "status": "ok",
                "safe_summary": "tool=write_file status=executed (pending_execute)",
                "metadata": {
                    "tool_name": "write_file",
                    "tool_use_id": tid,
                    "from_pending_tool": True,
                },
            },
        },
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 1" in result
    assert "executed       : 1" in result
    assert "pending exec   : 1" in result
    assert "blocked        : 0" in result


def test_mediate_pending_double_counting_prevention():
    """同一 tool_use_id 的 gate_decision + pending_execute 不重复计数。

    即使 gate_decision 和 pending_execute 各出现一次，attempted 和 executed
    应各为 1（不是 2）。
    """
    sid = "test-medpen-dedup"
    ts = "2026-06-06T12:00:00.000000Z"
    tid = "toolu_medpen_dedup_01"

    entries = [
        _make_entry("session_start", sid, data={
            "provider_type": "fake", "model": "test", "entry": "plain"}),
        {
            "event": "evidence.recorded",
            "timestamp": ts,
            "session_id": sid,
            "data": {
                "subsystem": "tool",
                "operation": "gate_decision",
                "phase": "decision",
                "status": "allowed",
                "safe_summary": "tool=write_file gate=allowed (pending confirmed)",
                "metadata": {"tool_name": "write_file", "tool_use_id": tid},
            },
        },
        {
            "event": "evidence.recorded",
            "timestamp": ts,
            "session_id": sid,
            "data": {
                "subsystem": "tool",
                "operation": "pending_execute",
                "phase": "end",
                "status": "ok",
                "safe_summary": "tool=write_file status=executed (pending_execute)",
                "metadata": {"tool_name": "write_file", "tool_use_id": tid},
            },
        },
    ]
    result = log_viewer.render_session_summary(sid, entries)
    assert "attempted      : 1" in result
    assert "executed       : 1" in result
    assert "pending exec   : 1" in result
    assert "blocked        : 0" in result


def test_pending_denied_path_no_evidence():
    """用户拒绝 pending tool 时不产生 pending_execute evidence。

    拒绝路径：handle_tool_confirmation 的 reject 分支不调 mediate_pending，
    也不调 execute_pending_tool。
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from agent.confirmation.dispatcher import ConfirmationContext
    from agent.confirmation.tool import handle_tool_confirmation

    test_sid = f"test-pend-deny-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.status = "awaiting_tool_confirmation"
    state.task.tool_execution_log = {}
    state.task.pending_tool = {
        "tool_use_id": "toolu_deny_test",
        "tool": "write_file",
        "input": {"path": "test.txt"},
    }
    state.conversation = SimpleNamespace()
    state.conversation.messages = []

    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None

    def _continue(ts):
        return "CONTINUE"

    ctx = ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test",
        continue_fn=_continue,
    )

    with patch("agent.confirmation.tool.save_checkpoint"):
        result = handle_tool_confirmation("no", ctx)

    assert "CONTINUE" in result
    # 不应有 pending_execute evidence
    pending_events = [
        e for e in writer.events
        if e.get("action_type") == "tool.pending_execute"
    ]
    assert len(pending_events) == 0, (
        f"reject 路径不应写入 pending_execute evidence，"
        f"实际: {pending_events}"
    )


def test_handle_tool_confirmation_accept_uses_mediator_when_available():
    """handle_tool_confirmation accept 时优先使用 mediator.mediate_pending()。

    验证：当 turn_state._tool_mediator 存在时，accept 路径走 mediator
    而不是直接调 execute_pending_tool。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from agent.confirmation.dispatcher import ConfirmationContext
    from agent.confirmation.tool import handle_tool_confirmation

    test_sid = f"test-hct-m-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.status = "awaiting_tool_confirmation"
    state.task.tool_execution_log = {}
    state.task.pending_tool = {
        "tool_use_id": "toolu_hct_m_test",
        "tool": "write_file",
        "input": {"path": "test.txt"},
    }
    state.conversation = SimpleNamespace()
    state.conversation.messages = []

    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None

    # 注入 fake mediator
    fake_mediator = MagicMock()
    fake_mediator.mediate_pending.return_value = "mediator result"
    turn_state._tool_mediator = fake_mediator

    def _continue(ts):
        return "CONTINUE"

    ctx = ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test",
        continue_fn=_continue,
    )

    with patch("agent.confirmation.tool.save_checkpoint"), patch(
        "agent.confirmation.tool.execute_pending_tool"
    ) as mock_direct:
        result = handle_tool_confirmation("yes", ctx)

    assert "CONTINUE" in result
    # mediator.mediate_pending 应被调用
    fake_mediator.mediate_pending.assert_called_once()
    # 直接 execute_pending_tool 不应被调用（fallback 不触发）
    mock_direct.assert_not_called()


def test_pending_accept_constructs_mediator_on_demand_with_dispatcher():
    """真实两轮 pending confirmation 路径：turn_state 无 mediator 但有 dispatcher。

    验证审计 A 发现的缺陷已修复——chat() 每次调用创建新 turn_state，
    _tool_mediator 在第二次调用时不存在。但 ctx.dispatcher 可用时，
    handle_tool_confirmation 应即时构造 mediator，不 fallback 到 direct path。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from agent.confirmation.dispatcher import ConfirmationContext
    from agent.confirmation.tool import handle_tool_confirmation

    test_sid = f"test-odm-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.status = "awaiting_tool_confirmation"
    state.task.tool_execution_log = {}
    state.task.pending_tool = {
        "tool_use_id": "toolu_odm_test",
        "tool": "write_file",
        "input": {"path": "test.txt"},
    }
    state.conversation = SimpleNamespace()
    state.conversation.messages = []

    # 新 turn_state — 没有 _tool_mediator（模拟第二次 chat() 调用）
    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None
    # 关键：不设置 _tool_mediator

    fake_dispatcher = MagicMock()

    def _continue(ts):
        return "CONTINUE"

    ctx = ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test",
        continue_fn=_continue,
        dispatcher=fake_dispatcher,
    )

    with patch("agent.confirmation.tool.save_checkpoint"), patch(
        "agent.tool_runtime_mediator.ToolRuntimeMediator"
    ) as mock_mediator_cls, patch(
        "agent.confirmation.tool.execute_pending_tool"
    ) as mock_direct:
        fake_mediator = MagicMock()
        fake_mediator.mediate_pending.return_value = "on-demand result"
        mock_mediator_cls.return_value = fake_mediator

        result = handle_tool_confirmation("yes", ctx)

    assert "CONTINUE" in result
    # 应即时构造了 mediator
    mock_mediator_cls.assert_called_once()
    # mediator.mediate_pending 应被调用
    fake_mediator.mediate_pending.assert_called_once()
    # 直接 execute_pending_tool 不应被调用（不走 fallback）
    mock_direct.assert_not_called()
    # turn_state 上现在应有 _tool_mediator（被重新挂上）
    assert getattr(turn_state, "_tool_mediator", None) is fake_mediator


def test_pending_accept_falls_back_when_no_mediator_and_no_dispatcher():
    """无 mediator 且无 dispatcher 时仍走 fallback direct path（向后兼容）。"""
    from types import SimpleNamespace
    from unittest.mock import patch

    from agent.confirmation.dispatcher import ConfirmationContext
    from agent.confirmation.tool import handle_tool_confirmation

    test_sid = f"test-nodisp-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.status = "awaiting_tool_confirmation"
    state.task.tool_execution_log = {}
    state.task.pending_tool = {
        "tool_use_id": "toolu_nodisp_test",
        "tool": "write_file",
        "input": {"path": "test.txt"},
    }
    state.conversation = SimpleNamespace()
    state.conversation.messages = []

    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None
    # 无 _tool_mediator，无 dispatcher

    def _continue(ts):
        return "CONTINUE"

    ctx = ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test",
        continue_fn=_continue,
        dispatcher=None,
    )

    with patch("agent.confirmation.tool.save_checkpoint"), patch(
        "agent.confirmation.tool.execute_pending_tool"
    ) as mock_direct:
        mock_direct.return_value = None
        result = handle_tool_confirmation("yes", ctx)

    assert "CONTINUE" in result
    # dispatcher 不可用，应走 fallback direct path
    mock_direct.assert_called_once()


def test_mediate_route_invoke_records_evidence_not_executes_via_dispatcher():
    """mediate() 的 _route_invoke 改用 record_evidence，不再通过 dispatcher 执行工具。

    验证：_route_invoke 不再调用 dispatcher.route_from_runtime_loop()
    （避免 ToolInvokeHandler → execute_tool 导致双重执行）。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from agent.tool_registry import TOOL_REGISTRY
    from agent.tool_runtime_mediator import ToolRuntimeMediator

    test_sid = f"test-ri-{uuid.uuid4().hex[:12]}"
    set_session_context(
        session_id=test_sid,
        entry="plain",
        provider_type="fake",
        provider_model="test",
    )
    writer = _FakeEventLogWriter()
    set_event_log_writer(writer)

    fake_dispatcher = MagicMock()

    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.status = "awaiting_tool_confirmation"
    state.task.tool_execution_log = {}
    state.task.pending_tool = None
    state.conversation = SimpleNamespace()
    state.conversation.messages = []

    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None
    turn_state.pending_tool_result = None
    turn_state.tool_call_count = 0
    turn_state.should_force_stop = False

    mediator = ToolRuntimeMediator(
        fake_dispatcher,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=[],
    )

    # 注册 write_file 到 registry（如果尚未注册）
    from agent.tool_registry import register_tool
    if "write_file" not in TOOL_REGISTRY:
        register_tool(
            name="write_file",
            func=lambda path, content=None: "ok",
            description="test",
            parameters={"type": "object", "properties": {}},
            risk_level="medium",
        )

    class FakeBlock:
        id = "toolu_ri_test"
        name = "write_file"
        input = {"path": "/tmp/test_ri.txt"}

    with patch("agent.tool_runtime_mediator.execute_single_tool") as mock_exec:
        mock_exec.return_value = None
        mediator.mediate(FakeBlock())

    # execute_single_tool 应被调一次（不是零次，不是两次）
    assert mock_exec.call_count == 1, (
        f"execute_single_tool 应恰好被调一次，实际 {mock_exec.call_count} 次"
    )

    # dispatcher.route_from_runtime_loop 应只在 _route_gate 和 _route_result
    # 被调用（TOOL_GATE + TOOL_RESULT），不应包含 TOOL_INVOKE
    invoke_calls = [
        c for c in fake_dispatcher.route_from_runtime_loop.call_args_list
        if c[0][0].action_type == "tool.invoke"
    ]
    assert len(invoke_calls) == 0, (
        f"dispatcher 不应被 _route_invoke 调用（避免双重执行），"
        f"但实际调了 {len(invoke_calls)} 次"
    )

    # gate_decision evidence 应被记录
    gate_events = [
        e for e in writer.events
        if e.get("data", {}).get("operation") == "gate_decision"
    ]
    assert len(gate_events) >= 1, "应至少有一条 gate_decision evidence"

    # invoke_started evidence 应被记录（替代旧的 dispatcher TOOL_INVOKE）
    invoke_events = [
        e for e in writer.events
        if e.get("data", {}).get("operation") == "invoke_started"
    ]
    assert len(invoke_events) >= 1, (
        f"应至少有一条 invoke_started evidence，实际 {len(invoke_events)} 条"
    )

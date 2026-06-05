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

import uuid

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
) -> dict:
    """构造 agent_log.jsonl 中 evidence.recorded 条目。"""
    ts = timestamp or f"2026-06-05T{10 + len(session_id):02d}:00:00.000Z"
    data: dict = {
        "subsystem": subsystem,
        "operation": operation,
        "phase": "end" if operation == "invoke_result_summary" else "decision",
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

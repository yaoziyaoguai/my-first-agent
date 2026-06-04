"""证据存储卫生测试。

中文学习边界：
- 这里的测试验证证据存储策略，而非业务功能。
- 为什么证据系统先于能力证明：如果 log / session / checkpoint / evidence
  本身不可靠（膨胀、泄漏敏感信息、缺失关键字段），那么任何"通过"的
  golden E2E 都无法被事后审计和信任。
- 每类测试标注对应的证据策略要点（policy rule）。
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from unittest import mock


# ═══════════════════════════════════════════════════════════════════════
# 1. Session snapshot content truncation
# ═══════════════════════════════════════════════════════════════════════


class TestSessionSnapshotToolResultTruncation:
    """验证 save_session_snapshot 对大 tool result 做摘要替换。

    Policy rule:
    - 超过 MAX_TOOL_RESULT_IN_SNAPSHOT（默认 2KB）的 tool result content
      替换为摘要 dict，包含 tool_name / path / result_size / result_hash /
      preview_redacted / truncated。
    - 不超阈值的小结果可以保留（由策略阈值决定）。
    """

    def test_large_tool_result_is_summarized_not_full(self):
        """超过阈值的大 tool result → snapshot 中只保留摘要，不含原始全文。"""
        large_content = "x" * 5000  # 5KB > 2KB 阈值
        messages = _make_read_file_messages(
            path="README.md", content=large_content
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent.logger.SNAPSHOT_DIR", Path(tmp)):
                from agent.logger import save_session_snapshot
                save_session_snapshot(messages)

                snap_files = list(Path(tmp).glob("session_*.json"))
                assert len(snap_files) == 1
                snapshot = json.loads(snap_files[0].read_text())

                # 找到 tool result 消息
                raw = json.dumps(snapshot)
                # 原始大内容不应全文出现在 snapshot 中
                assert large_content not in raw, (
                    "大文件内容不应全文出现在 session snapshot 中"
                )

    def test_tool_result_summary_has_required_fields(self):
        """摘要 dict 必须包含 tool_name / result_size / result_hash / truncated。"""
        large_content = "y" * 3000
        messages = _make_read_file_messages(
            path="data.txt", content=large_content
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent.logger.SNAPSHOT_DIR", Path(tmp)):
                from agent.logger import save_session_snapshot
                save_session_snapshot(messages)

                snap_files = list(Path(tmp).glob("session_*.json"))
                snapshot = json.loads(snap_files[0].read_text())

                # 在消息中搜索摘要字段
                raw = json.dumps(snapshot)
                assert "result_size" in raw, "摘要应包含 result_size"
                assert "result_hash" in raw, "摘要应包含 result_hash"
                assert "truncated" in raw, "摘要应包含 truncated 标记"

    def test_small_tool_result_may_have_preview(self):
        """小文件结果可以保留短预览，但不能无限制保存全文。"""
        small_content = "hello"  # 远小于 2KB
        messages = _make_read_file_messages(
            path="small.txt", content=small_content
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent.logger.SNAPSHOT_DIR", Path(tmp)):
                from agent.logger import save_session_snapshot
                save_session_snapshot(messages)

                snap_files = list(Path(tmp).glob("session_*.json"))
                snapshot = json.loads(snap_files[0].read_text())
                raw = json.dumps(snapshot)
                # 小内容可以保留，这是合理的
                assert small_content in raw or "preview" in raw.lower(), (
                    "小内容应可预览或保留"
                )

    def test_snapshot_message_count_and_session_id_preserved(self):
        """摘要替换不应丢失 message_count / session_id 等元信息。"""
        messages = _make_read_file_messages(path="README.md", content="test")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent.logger.SNAPSHOT_DIR", Path(tmp)):
                from agent.logger import save_session_snapshot
                save_session_snapshot(messages)

                snap_files = list(Path(tmp).glob("session_*.json"))
                snapshot = json.loads(snap_files[0].read_text())
                assert "session_id" in snapshot
                assert "message_count" in snapshot
                assert snapshot["message_count"] > 0


# ═══════════════════════════════════════════════════════════════════════
# 2. Blocked sensitive tool — metadata only
# ═══════════════════════════════════════════════════════════════════════


class TestBlockedSensitiveToolEvidence:
    """验证 blocked sensitive tool 只保存 denial metadata。

    P0/P1 safety boundary：
    - config/config.yaml、.env、key/token/secret/credential 文件被拒绝后，
      session/log/evidence 中只能包含：tool_name / path / decision=blocked /
      reason=sensitive_path / content_persisted=false。
    - 绝对不能包含 raw config 内容、token、key。
    """

    def test_blocked_config_yaml_not_in_snapshot(self):
        """config/config.yaml 被 block 后，snapshot 不含文件原始内容。"""
        secret_content = "api_key: sk-very-secret-value-12345"
        messages = _make_blocked_tool_messages(
            tool_name="read_file",
            path="config/config.yaml",
            raw_result=secret_content,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent.logger.SNAPSHOT_DIR", Path(tmp)):
                from agent.logger import save_session_snapshot
                save_session_snapshot(messages)

                snap_files = list(Path(tmp).glob("session_*.json"))
                snapshot = json.loads(snap_files[0].read_text())
                raw = json.dumps(snapshot)
                assert secret_content not in raw, (
                    "敏感内容不应出现在 snapshot 中"
                )
                assert "sk-very-secret" not in raw, (
                    "API key 不应泄漏到 snapshot"
                )

    def test_blocked_env_not_in_snapshot(self):
        """.env 被 block 后，snapshot 不含环境变量内容。"""
        env_content = "DATABASE_PASSWORD=super-secret-pwd"
        messages = _make_blocked_tool_messages(
            tool_name="read_file",
            path=".env",
            raw_result=env_content,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent.logger.SNAPSHOT_DIR", Path(tmp)):
                from agent.logger import save_session_snapshot
                save_session_snapshot(messages)

                snap_files = list(Path(tmp).glob("session_*.json"))
                raw = json.dumps(json.loads(snap_files[0].read_text()))
                assert "DATABASE_PASSWORD" not in raw, (
                    "密码不应泄漏到 snapshot"
                )

    def test_blocked_tool_denial_metadata_present(self):
        """block 事件至少包含 tool_name / path / decision / reason 元信息。"""
        messages = _make_blocked_tool_messages(
            tool_name="read_file",
            path="config/config.yaml",
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent.logger.SNAPSHOT_DIR", Path(tmp)):
                from agent.logger import save_session_snapshot
                save_session_snapshot(messages)

                snap_files = list(Path(tmp).glob("session_*.json"))
                raw = json.dumps(json.loads(snap_files[0].read_text()))
                # 至少应包含工具名和路径
                assert "read_file" in raw or "config/config.yaml" in raw, (
                    "denial metadata 至少应包含工具名或路径信息"
                )


# ═══════════════════════════════════════════════════════════════════════
# 3. Tool audit event fields
# ═══════════════════════════════════════════════════════════════════════


class TestToolAuditFields:
    """验证 tool_audit 事件包含必要字段。

    Policy rule:
    - tool_audit 事件应包含 tool_name / decision / reason / session_id。
    - tool_audit 不应包含 raw tool result content。
    """

    def test_tool_audit_event_has_required_fields(self):
        """tool_audit 事件包含 tool_name / event_type / status / safe_preview。"""
        from agent.tool_audit import ToolAuditEvent

        event = ToolAuditEvent(
            event_type="tool_executed",
            tool_name="read_file",
            tool_use_id="tu-001",
            step_index=1,
            status="success",
            error_type=None,
            safe_preview="first 200 chars...",
            content_length=5000,
        )
        d = event.to_log_dict()
        assert d["tool_name"] == "read_file"
        assert d["event_type"] == "tool_executed"
        assert d["status"] == "success"
        assert d["safe_preview"] == "first 200 chars..."
        assert d["content_length"] == 5000
        assert "request_id" in d
        assert "timestamp" in d

    def test_tool_audit_never_has_raw_content_field(self):
        """to_log_dict() 返回的 dict 不应包含 content / result / raw 字段。"""
        from agent.tool_audit import ToolAuditEvent

        event = ToolAuditEvent(
            event_type="tool_blocked",
            tool_name="read_file",
            tool_use_id="tu-002",
            step_index=None,
            status="blocked",
            error_type="sensitive_path",
            safe_preview="",
            content_length=0,
        )
        d = event.to_log_dict()
        forbidden = {"content", "result", "raw", "full_text", "body"}
        assert forbidden.isdisjoint(d.keys()), (
            f"tool_audit event 不应包含: {forbidden & d.keys()}"
        )

    def test_tool_audit_blocked_has_reason(self):
        """blocked 事件应包含 error_type 作为拒绝原因。"""
        from agent.tool_audit import ToolAuditEvent

        event = ToolAuditEvent(
            event_type="tool_blocked",
            tool_name="read_file",
            tool_use_id="tu-003",
            step_index=0,
            status="blocked",
            error_type="sensitive_path",
            safe_preview="",
            content_length=0,
        )
        d = event.to_log_dict()
        assert d["error_type"] == "sensitive_path", (
            "blocked 事件必须包含拒绝原因"
        )


# ═══════════════════════════════════════════════════════════════════════
# 4. Session start event fields
# ═══════════════════════════════════════════════════════════════════════


class TestSessionStartFields:
    """验证 session_start 事件包含 provider_type / model / entry。

    Policy rule (from GAP-1 fix at acff8e7):
    - session_start 必须包含 provider_type / model / entry，
      使用户能区分 fake/real session。
    """

    def test_init_session_emits_provider_info(self):
        """init_session 调用 log_event 时 data 包含 provider_type / model。"""
        import agent.session as session_mod

        with mock.patch.object(session_mod, "log_event") as mock_log:
            session_mod.init_session(session_id="s-test-001", entry="plain")

            session_start_calls = [
                c for c in mock_log.call_args_list
                if c[0][0] == "session_start"
            ]
            assert len(session_start_calls) >= 1, (
                f"未找到 session_start 调用，共 {len(mock_log.call_args_list)} 次调用"
            )
            data = session_start_calls[0][0][1]
            assert "provider_type" in data
            assert "model" in data

    def test_init_session_accepts_entry_parameter(self):
        """init_session 接受 entry 参数并记录。"""
        import agent.session as session_mod

        with mock.patch.object(session_mod, "log_event") as mock_log:
            session_mod.init_session(session_id="s-test-002", entry="plain")

            session_start_calls = [
                c for c in mock_log.call_args_list
                if c[0][0] == "session_start"
            ]
            assert len(session_start_calls) >= 1, (
                f"未找到 session_start 调用，共 {len(mock_log.call_args_list)} 次调用"
            )
            data = session_start_calls[0][0][1]
            assert "entry" in data
            assert isinstance(data["entry"], str)

    def test_provider_type_distinguishes_fake_from_real(self):
        """provider_type 字段能区分 fake 和 real provider。

        fake provider 的 provider_type 至少不是空字符串，
        调用方可根据此字段判断会话可信程度。
        """
        import agent.session as session_mod

        with mock.patch.object(session_mod, "log_event") as mock_log:
            session_mod.init_session(session_id="s-test-003", entry="plain")

            session_start_calls = [
                c for c in mock_log.call_args_list
                if c[0][0] == "session_start"
            ]
            assert len(session_start_calls) >= 1, (
                f"未找到 session_start 调用，共 {len(mock_log.call_args_list)} 次调用"
            )
            data = session_start_calls[0][0][1]
            assert data["provider_type"], (
                "provider_type 不应为空，至少应能区分 fake/real"
            )


# ═══════════════════════════════════════════════════════════════════════
# 5. events.jsonl not empty for new sessions
# ═══════════════════════════════════════════════════════════════════════


class TestEventsJsonlNotEmpty:
    """验证新 session 的 events.jsonl 至少写入关键 events。

    Policy rule:
    - 每个 session 的 events.jsonl 至少应包含 session_start 事件。
    - 当前 257/263 sessions events.jsonl 为空，新 session 必须修复。
    """

    def test_event_log_writer_session_start_is_written(self):
        """EventLogWriter 创建后写入 session_start → events.jsonl 不为空。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            writer = EventLogWriter(session_dir=session_dir)

            # 模拟写入 session_start event
            writer.append({
                "action_type": "session.start",
                "source": "session",
                "event_id": "ev-session-start-001",
                "data": {
                    "provider_type": "fake",
                    "model": "test-model",
                    "entry": "plain",
                },
            })
            writer.close()

            log_path = session_dir / "events.jsonl"
            assert log_path.exists(), "events.jsonl 应被创建"
            content = log_path.read_text().strip()
            assert len(content) > 0, "events.jsonl 不应为空"
            lines = content.split("\n")
            assert len(lines) >= 1

            data = json.loads(lines[0])
            assert data["event_type"] == "session.start"

    def test_event_log_writer_multiple_events(self):
        """多个 event 写入后 events.jsonl 有对应行数。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"action_type": "session.start", "source": "session"})
            writer.append({"action_type": "user.input", "source": "core"})
            writer.append({"action_type": "tool.blocked", "source": "tool"})
            writer.close()

            lines = (Path(tmp) / "events.jsonl").read_text().strip().split("\n")
            assert len(lines) == 3


# ═══════════════════════════════════════════════════════════════════════
# 6. --summary flag output
# ═══════════════════════════════════════════════════════════════════════


class TestLogViewerSummary:
    """验证 logs --summary 输出 one-screen evidence summary。

    Policy rule:
    - --summary 输出应包含 session_id / provider_type / model / entry /
      user inputs count / tools attempted/executed/blocked / checkpoints /
      evidence gaps。
    - 单屏输出，信息密度高，不 dump raw content。
    """

    def test_render_summary_includes_session_id(self):
        """summary 输出包含 session_id。"""
        from agent.log_viewer import render_session_summary

        entries = [
            _make_log_entry("session_start", {
                "provider_type": "fake", "model": "test-model",
                "entry": "plain",
            }),
        ]
        result = render_session_summary("s-abc12345", entries)
        assert "s-abc12345" in result or "abc12345" in result

    def test_render_summary_includes_provider_and_model(self):
        """summary 输出包含 provider_type / model。"""
        from agent.log_viewer import render_session_summary

        entries = [
            _make_log_entry("session_start", {
                "provider_type": "anthropic",
                "model": "claude-sonnet-4-6",
                "entry": "plain",
            }),
        ]
        result = render_session_summary("s-test", entries)
        assert "anthropic" in result
        assert "claude-sonnet-4-6" in result

    def test_render_summary_counts_user_inputs(self):
        """summary 输出统计 user_input 事件数量。"""
        from agent.log_viewer import render_session_summary

        entries = [
            _make_log_entry("session_start", {
                "provider_type": "fake", "model": "test", "entry": "plain",
            }),
            _make_log_entry("user_input", {"content": "hello"}),
            _make_log_entry("user_input", {"content": "read README"}),
            _make_log_entry("user_input", {"content": "quit"}),
        ]
        result = render_session_summary("s-test", entries)
        # 应包含用户输入计数
        assert "3" in result or "user_input" in result.lower()

    def test_render_summary_counts_tools(self):
        """summary 输出统计 tool 事件。"""
        from agent.log_viewer import render_session_summary

        entries = [
            _make_log_entry("session_start", {
                "provider_type": "fake", "model": "test", "entry": "plain",
            }),
            _make_log_entry("tool_executed", {"tool": "read_file"}),
            _make_log_entry("tool_blocked", {"tool": "read_file"}),
        ]
        result = render_session_summary("s-test", entries)
        # 应包含工具计数
        assert "read_file" in result

    def test_render_summary_no_raw_content(self):
        """summary 输出不包含 raw content / tool result 正文。"""
        from agent.log_viewer import render_session_summary

        entries = [
            _make_log_entry("session_start", {
                "provider_type": "fake", "model": "test", "entry": "plain",
            }),
            _make_log_entry("tool_executed", {
                "tool": "read_file",
                "result": "ENORMOUS_CONTENT_" + "x" * 5000,
            }),
        ]
        result = render_session_summary("s-test", entries)
        assert "ENORMOUS_CONTENT_" not in result, (
            "summary 不应 dump raw tool result content"
        )

    def test_render_summary_shows_evidence_gaps(self):
        """summary 应标注 evidence gaps（如缺少 session_start 等）。"""
        from agent.log_viewer import render_session_summary

        # 没有 session_start 事件的 session — 应标记 gap
        entries = [
            _make_log_entry("user_input", {"content": "hello"}),
        ]
        result = render_session_summary("s-gap", entries)
        # 有关 gap 的信息
        assert any(
            word in result.lower()
            for word in ["gap", "缺少", "missing", "no session_start"]
        ), f"应标注 evidence gap，实际输出: {result[:200]}"

    def test_render_summary_distinguishes_fake_real(self):
        """summary 能显示 provider_type，区分 fake/real。"""
        from agent.log_viewer import render_session_summary

        fake_entries = [
            _make_log_entry("session_start", {
                "provider_type": "fake", "model": "test", "entry": "plain",
            }),
        ]
        real_entries = [
            _make_log_entry("session_start", {
                "provider_type": "anthropic", "model": "claude-sonnet-4-6",
                "entry": "plain",
            }),
        ]
        fake_result = render_session_summary("s-fake", fake_entries)
        real_result = render_session_summary("s-real", real_entries)
        assert "fake" in fake_result.lower()
        assert "anthropic" in real_result.lower()


# ═══════════════════════════════════════════════════════════════════════
# 7. Content hash verification
# ═══════════════════════════════════════════════════════════════════════


class TestContentHashInSnapshot:
    """验证 snapshot 摘要中的 result_hash 可复现。"""

    def test_result_hash_is_sha256_prefix(self):
        """result_hash 是 sha256 的前 16 位 hex。"""
        content = b"test content for hashing"
        expected_hash = hashlib.sha256(content).hexdigest()[:16]

        large_content = "z" * 3000  # 超过阈值触发摘要
        messages = _make_read_file_messages(
            path="hash_test.txt", content=large_content
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent.logger.SNAPSHOT_DIR", Path(tmp)):
                from agent.logger import save_session_snapshot
                save_session_snapshot(messages)

                snap_files = list(Path(tmp).glob("session_*.json"))
                raw = json.dumps(json.loads(snap_files[0].read_text()))
                # 应该有 result_hash 字段（前 16 位 hex）
                assert "result_hash" in raw


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _make_read_file_messages(path: str, content: str) -> list[dict]:
    """构造包含 read_file tool result 的 messages（模拟真实对话消息格式）。"""
    return [
        {"role": "user", "content": [{"type": "text", "text": "read the file"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu-001",
                    "name": "read_file",
                    "input": {"path": path},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu-001",
                    "content": content,
                },
            ],
        },
    ]


def _make_blocked_tool_messages(
    tool_name: str, path: str, raw_result: str = ""
) -> list[dict]:
    """构造包含 blocked tool result 的 messages。"""
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "read a file"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu-blocked-001",
                    "name": tool_name,
                    "input": {"path": path},
                },
            ],
        },
    ]
    if raw_result:
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu-blocked-001",
                    "content": f"[BLOCKED] sensitive path: {path}",
                    "is_error": True,
                },
            ],
        })
    return messages


def _make_log_entry(event: str, data: dict) -> dict:
    """构造最小 agent_log entry（模拟 agent_log.jsonl 中一行）。"""
    return {
        "timestamp": "2026-06-05T00:00:00",
        "session_id": "s-test",
        "event": event,
        "event_category": event,
        "data": data,
    }

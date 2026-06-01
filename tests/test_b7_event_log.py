"""B7 Slice 4: Event Log Writer — RED tests.

覆盖 EventLogWriter append/redact/flush。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

# ── RED-4.1: EventLogWriter ───────────────────────────────────────────────


class TestEventLogWriter:
    def test_event_log_writer_append(self):
        """append() 后文件包含一行 JSON。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"event": "test", "data": 42})
            writer.close()

            log_path = Path(tmp) / "events.jsonl"
            assert log_path.exists()
            lines = log_path.read_text().strip().split("\n")
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["event"] == "test"
            assert data["data"] == 42

    def test_event_log_writer_appends_not_overwrites(self):
        """两次 append → 文件有两行。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"seq": 1})
            writer.append({"seq": 2})
            writer.close()

            lines = (Path(tmp) / "events.jsonl").read_text().strip().split("\n")
            assert len(lines) == 2

    def test_event_log_writer_creates_dirs(self):
        """自动创建父目录。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "deeply" / "nested" / "sessions" / "s-1"
            assert not session_dir.exists()

            writer = EventLogWriter(session_dir=session_dir)
            writer.append({"ok": True})
            writer.close()

            assert (session_dir / "events.jsonl").exists()

    def test_event_log_writer_valid_jsonl(self):
        """每行是合法 JSON，不含内部换行。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"msg": "hello\nworld", "arr": [1, 2, 3]})
            writer.close()

            for line in (Path(tmp) / "events.jsonl").read_text().strip().split("\n"):
                data = json.loads(line)
                assert isinstance(data, dict)
                # JSON 序列化后 \n 被转义，不是字面换行


# ── RED-4.2: Redaction ─────────────────────────────────────────────────────


class TestEventLogRedaction:
    def test_redact_api_key_in_value(self):
        """payload 中 "api_key": "sk-xxx..." → "api_key": "<REDACTED>"。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"api_key": "sk-ant-1234567890abcdef"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["api_key"] == "<REDACTED>"

    def test_redact_key_field_name(self):
        """字段名包含 'key' 时值被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"openai_key": "abcdef1234567890"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["openai_key"] == "<REDACTED>"

    def test_redact_token_field_name(self):
        """字段名包含 'token' 时值被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"access_token": "secret-token-value"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["access_token"] == "<REDACTED>"

    def test_redact_bearer_header(self):
        """Authorization 字段命中 secret 字段名 → 整个值替换为 <REDACTED>。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({
                "headers": {
                    "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.abc123def456",
                },
            })
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            auth_val = data["headers"]["Authorization"]
            # Authorization 命中 secret 字段名规则 → 整个值被替换
            assert auth_val == "<REDACTED>"
            assert "Bearer" not in auth_val
            assert "eyJ" not in auth_val

    def test_redact_records_field_names(self):
        """event 的 redacted 数组包含被 redact 的字段名。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({
                "api_key": "sk-1234567890abcdef",
                "user": "alice",
                "token": "abc123",
            })
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert "redacted" in data
            assert "api_key" in data["redacted"]
            assert "token" in data["redacted"]
            # user 未被 redact
            assert data["user"] == "alice"

    def test_secret_field_name_value_redacted(self):
        """"secret" 字段名的值被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"secret": "my-password-12345"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["secret"] == "<REDACTED>"


# ── RED-4.3: Turn-end flush ──────────────────────────────────────────────


class TestTurnEndFlush:
    def test_flush_writes_events_to_log(self):
        """flush_to_event_log() 将 action_log 中的 event 写入文件。"""
        from agent.event_log import EventLogWriter
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            dispatcher = RuntimeActionDispatcher()
            # 手动推入两条 event 到 action_log（绕过 route）
            dispatcher._action_log.append(
                _fake_event(event_id="e1", action_type="test.one"),
            )
            dispatcher._action_log.append(
                _fake_event(event_id="e2", action_type="test.two"),
            )

            count = dispatcher.flush_to_event_log(writer)
            writer.close()

            assert count == 2
            lines = (Path(tmp) / "events.jsonl").read_text().strip().split("\n")
            assert len(lines) == 2
            e1 = json.loads(lines[0])
            assert e1["event_id"] == "e1"

    def test_flush_does_not_clear_action_log(self):
        """flush 后 action_log 仍在内存中。"""
        from agent.event_log import EventLogWriter
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            dispatcher = RuntimeActionDispatcher()
            dispatcher._action_log.append(
                _fake_event(event_id="e-keep"),
            )

            dispatcher.flush_to_event_log(writer)
            writer.close()

            assert len(dispatcher.action_log) == 1

    def test_flush_best_effort_no_crash(self):
        """写入失败不抛异常（如目录不可写）。"""
        from agent.event_log import EventLogWriter
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        # 指向不可写路径
        writer = EventLogWriter(session_dir=Path("/dev/null/nonexistent"))
        dispatcher = RuntimeActionDispatcher()
        dispatcher._action_log.append(
            _fake_event(event_id="e-safe"),
        )

        # 不应抛异常
        try:
            dispatcher.flush_to_event_log(writer)
        except Exception as err:
            # 清理 writer（避免资源泄漏）
            writer.close()
            raise AssertionError(
                "flush_to_event_log 不应抛异常"
            ) from err


def _fake_event(**overrides) -> object:
    """构造最小 RuntimeActionEvent 用于 flush 测试。"""
    from agent.runtime_integration.schema import RuntimeActionEvent

    defaults: dict = {
        "event_id": "ev-001",
        "action_id": "act-001",
        "action_type": "test.fake",
        "source": "test",
        "status": "success",
        "evidence": {},
        "parent_trace_id": "",
        "session_id": "s-test",
        "run_id": "r-test",
    }
    defaults.update(overrides)
    return RuntimeActionEvent(**defaults)

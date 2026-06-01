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


# ═══════════════════════════════════════════════════════════════════════
# Phase 6: Dedupe — flush cursor prevents duplicate writes
# ═══════════════════════════════════════════════════════════════════════


class TestFlushDedupe:
    def test_repeated_flush_does_not_duplicate_events(self):
        """重复 flush 不会产生重复 event 行（flush_cursor dedupe）。"""
        from agent.event_log import EventLogWriter
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            dispatcher = RuntimeActionDispatcher()
            dispatcher._action_log.append(
                _fake_event(event_id="e-dedup-1"),
            )
            dispatcher._action_log.append(
                _fake_event(event_id="e-dedup-2"),
            )

            # 第一次 flush
            c1 = dispatcher.flush_to_event_log(writer)
            # 第二次 flush — 不应有新行
            c2 = dispatcher.flush_to_event_log(writer)
            writer.close()

            assert c1 == 2
            assert c2 == 0, f"第二次 flush 应返回 0（无新 event），实际返回 {c2}"
            lines = (Path(tmp) / "events.jsonl").read_text().strip().split("\n")
            assert len(lines) == 2, f"文件应只有 2 行，实际 {len(lines)} 行"

    def test_new_events_after_flush_are_written(self):
        """flush 后新增 event 仍能被后续 flush 写入。"""
        from agent.event_log import EventLogWriter
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            dispatcher = RuntimeActionDispatcher()
            dispatcher._action_log.append(_fake_event(event_id="batch1-1"))

            dispatcher.flush_to_event_log(writer)
            # 新增 event
            dispatcher._action_log.append(_fake_event(event_id="batch2-1"))
            dispatcher._action_log.append(_fake_event(event_id="batch2-2"))
            c2 = dispatcher.flush_to_event_log(writer)
            writer.close()

            assert c2 == 2
            lines = (Path(tmp) / "events.jsonl").read_text().strip().split("\n")
            assert len(lines) == 3

    def test_flush_cursor_persists_across_flushes(self):
        """flush_cursor 不因中途失败而回退已验证的 event。"""
        from agent.event_log import EventLogWriter
        from agent.runtime_integration.dispatcher import RuntimeActionDispatcher

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            dispatcher = RuntimeActionDispatcher()
            dispatcher._action_log.append(_fake_event(event_id="ok-1"))

            c1 = dispatcher.flush_to_event_log(writer)
            assert c1 == 1
            # 再次 flush — cursor 已在末尾
            c2 = dispatcher.flush_to_event_log(writer)
            assert c2 == 0
            writer.close()


# ═══════════════════════════════════════════════════════════════════════
# Phase 6: Event schema enrichment
# ═══════════════════════════════════════════════════════════════════════


class TestEventSchemaEnrichment:
    def test_event_has_schema_version(self):
        """每个 event 包含 schema_version 字段。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"event": "test"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["schema_version"] == "1.0"

    def test_event_has_event_type(self):
        """event_type 由 action_type 派生。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"action_type": "memory.store.write"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["event_type"] == "memory.store.write"

    def test_event_has_source_subsystem(self):
        """source_subsystem 由 source 映射。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"source": "skill"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["source_subsystem"] == "skill_system"

    def test_unknown_source_maps_to_itself(self):
        """未识别的 source 原样保留为 source_subsystem。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"source": "custom_module"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["source_subsystem"] == "custom_module"

    def test_event_has_written_at_timestamp(self):
        """每个 event 包含 written_at（Unix timestamp）。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"event": "test"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert "written_at" in data
            assert isinstance(data["written_at"], float)
            assert data["written_at"] > 0


# ═══════════════════════════════════════════════════════════════════════
# Phase 6: Enhanced redaction
# ═══════════════════════════════════════════════════════════════════════


class TestEnhancedRedaction:
    def test_env_var_like_field_name_is_redacted(self):
        """大写+下划线字段名（如 OPENAI_API_KEY）被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"OPENAI_API_KEY": "sk-real-looking-key-12345678"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["OPENAI_API_KEY"] == "<REDACTED>"

    def test_credential_field_is_redacted(self):
        """字段名包含 'credential' 时被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"credentials": "my-secret-data"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["credentials"] == "<REDACTED>"

    def test_private_field_is_redacted(self):
        """字段名包含 'private' 时被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"private_key": "-----BEGIN RSA PRIVATE KEY-----"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["private_key"] == "<REDACTED>"

    def test_normal_uppercase_field_not_redacted(self):
        """普通大写字段名（不含 key/token/secret 等关键词）不被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"USER_NAME": "alice", "APP_VERSION": "1.0"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["USER_NAME"] == "alice"
            assert data["APP_VERSION"] == "1.0"

    def test_secret_nested_in_list(self):
        """嵌套在 list 中的敏感字段也被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({
                "items": [
                    {"name": "item1", "api_key": "sk-list-item-key"},
                    {"name": "item2", "token": "list-item-token"},
                ],
            })
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["items"][0]["api_key"] == "<REDACTED>"
            assert data["items"][1]["token"] == "<REDACTED>"


# ═══════════════════════════════════════════════════════════════════════
# Phase 6: Bounded payload
# ═══════════════════════════════════════════════════════════════════════


class TestBoundedPayload:
    def test_long_string_is_truncated(self):
        """超过 _MAX_STRING_LEN 的字符串被截断。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            long_text = "x" * 10000
            writer.append({"prompt": long_text})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert len(data["prompt"]) < 10000
            assert "TRUNCATED" in data["prompt"]

    def test_short_string_not_truncated(self):
        """短字符串保持原样。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"msg": "hello"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["msg"] == "hello"

    def test_nested_long_string_is_truncated(self):
        """嵌套在 dict 中的长字符串也被截断。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({
                "response": {
                    "text": "y" * 8000,
                    "metadata": {"source": "z" * 100},
                },
            })
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert "TRUNCATED" in data["response"]["text"]
            assert data["response"]["metadata"]["source"] == "z" * 100


# ═══════════════════════════════════════════════════════════════════════
# Phase 4: Enhanced value redaction — env-var assign, JWT, long tokens
# ═══════════════════════════════════════════════════════════════════════


class TestEnvVarAssignRedaction:
    """env-var 赋值形态的 secret redaction。"""

    def test_openai_api_key_assignment_redacted(self):
        """OPENAI_API_KEY=sk-xxx 在普通字段值中被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"prompt": "export OPENAI_API_KEY=sk-ant-abc123def456ghi789"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert "OPENAI_API_KEY=<REDACTED>" in data["prompt"]
            assert "sk-ant" not in data["prompt"]

    def test_anthropic_api_key_assignment_redacted(self):
        """ANTHROPIC_API_KEY=... 被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"env": "ANTHROPIC_API_KEY=sk-ant-secret12345678"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert "ANTHROPIC_API_KEY=<REDACTED>" in data["env"]
            assert "sk-ant-secret" not in data["env"]

    def test_generic_api_key_assignment_redacted(self):
        """*_API_KEY=value 形态被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"config": "SERVICE_API_KEY=abcdef1234567890abcdef1234567890"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert "SERVICE_API_KEY=<REDACTED>" in data["config"]
            assert "abcdef" not in data["config"]

    def test_secret_env_assign_redacted(self):
        """*_SECRET=... 和 *_TOKEN=... 等形态被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({
                "line1": "DB_PASSWORD=super-secret-pwd-12345",
                "line2": "AUTH_TOKEN=ghp_abc123def456ghi789jkl",
            })
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert "DB_PASSWORD=<REDACTED>" in data["line1"]
            assert "AUTH_TOKEN=<REDACTED>" in data["line2"]

    def test_normal_env_assign_not_redacted(self):
        """普通 env var 赋值（不含 secret 关键词）不被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"config": "LOG_LEVEL=debug"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["config"] == "LOG_LEVEL=debug"


class TestJWTTokenRedaction:
    """JWT token 在普通字段值中被脱敏。"""

    def test_jwt_in_ordinary_field_is_redacted(self):
        """普通字段中的 JWT token 被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            jwt = (
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
                "dozjgN1P_MR36HvzVkwdHR4FzpXb3YzL9Xm4jOq1NCc"
            )
            writer.append({"auth_header": f"Authorization: Bearer {jwt}"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            # JWT 被 redact, Bearer 也被 redact
            assert "eyJ" not in data["auth_header"]
            assert "<REDACTED>" in data["auth_header"]

    def test_jwt_alone_in_field_is_redacted(self):
        """仅有 JWT 的字段值被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            jwt = "eyJhbGciOiJSUzI1NiJ9.eyJ1c2VyIjoiYWxpY2UifQ.signature_part_here_abc123"
            writer.append({"raw_token": jwt})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["raw_token"] == "<REDACTED>"


class TestLongTokenRedaction:
    """long hex / base64 token 在普通字段中被脱敏。"""

    def test_hex_token_40_chars_is_redacted(self):
        """40 位 hex 字符串在普通字段中被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            hex_token = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"  # 42 chars
            writer.append({"note": f"token: {hex_token}"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert hex_token not in data["note"]
            assert "<REDACTED>" in data["note"]

    def test_b64_token_60_chars_is_redacted(self):
        """60 位 base64-like 字符串在普通字段中被脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            b64_token = "dGhpcyBpc0E2MGNoYXJhY3RlclN0cmluZ1Rlc3RGb3JCYXNlNjRSZWRhY3Rpb25UZXN0"
            writer.append({"raw": b64_token})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["raw"] == "<REDACTED>"

    def test_repeated_single_char_not_false_positive(self):
        """重复单字符长字符串不被误脱敏（如 'x' * 10000）。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"data": "x" * 5001})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert "<REDACTED>" not in data["data"]
            assert "TRUNCATED" in data["data"]


class TestNoFalsePositiveRedaction:
    """确保增强 redaction 不产生误报。"""

    def test_short_string_not_redacted(self):
        """短字符串不被误脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            writer.append({"msg": "hello world", "count": "42"})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["msg"] == "hello world"
            assert data["count"] == "42"

    def test_common_hash_not_redacted(self):
        """32 位 hex（如 MD5 hash）不被误脱敏。"""
        from agent.event_log import EventLogWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = EventLogWriter(session_dir=Path(tmp))
            md5_hash = "d41d8cd98f00b204e9800998ecf8427e"
            writer.append({"hash": md5_hash})
            writer.close()

            line = (Path(tmp) / "events.jsonl").read_text().strip()
            data = json.loads(line)
            assert data["hash"] == md5_hash

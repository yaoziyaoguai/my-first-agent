"""Stage 3 — Loop 2: log hygiene guard tests.

验证 logger.py 的脱敏和自动轮转行为。
所有测试使用 tmp_path 隔离，不接触真实 agent_log.jsonl。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import agent.logger as logger_module


class TestLogSanitization:
    """验证 _sanitize_log_data 脱敏所有日志写入路径。"""

    def test_redacts_sk_key_pattern(self) -> None:
        result = logger_module._sanitize_log_data(
            {"api_key": "sk-sp-42c996cf76cf46eeadb91f5daabb7a7d"}
        )
        assert isinstance(result, dict)
        assert "sk-***REDACTED***" in result["api_key"]
        assert "42c996cf" not in result["api_key"]

    def test_redacts_anthropic_key(self) -> None:
        result = logger_module._sanitize_log_data(
            {"key": "sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}
        )
        assert "sk-***REDACTED***" in result["key"]
        assert "ant-api03" not in result["key"]

    def test_redacts_openai_key(self) -> None:
        result = logger_module._sanitize_log_data(
            {"key": "sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}
        )
        assert "sk-***REDACTED***" in result["key"]

    def test_redacts_bearer_token(self) -> None:
        result = logger_module._sanitize_log_data(
            {"auth": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"}
        )
        assert "Bearer ***REDACTED***" in result["auth"]

    def test_preserves_short_sk_reference_in_code(self) -> None:
        """代码中的短 'sk-' 引用（如 'sk-REPLACE_ME'）不被误脱敏。

        真实 key 至少 sk-<type>-<8+ chars>，占位符 sk-REPLACE_ME 没有第三段。
        """
        result = logger_module._sanitize_log_data(
            {"placeholder": "sk-REPLACE_ME"}
        )
        assert result["placeholder"] == "sk-REPLACE_ME"

    def test_preserves_sk_prefix_in_docs(self) -> None:
        """文档中对 key pattern 的说明（如 'sk-sp-'）不被误脱敏。"""
        result = logger_module._sanitize_log_data(
            {"note": "real key patterns: sk-sp- / sk-ant- / sk-or-"}
        )
        # 短引用不含 8+ 字符后缀，应原样保留
        assert "sk-sp-" in result["note"]

    def test_truncates_long_string(self) -> None:
        long_text = "x" * 3000
        result = logger_module._sanitize_log_data({"big": long_text})
        assert len(result["big"]) <= logger_module._MAX_STR_LEN + 3  # +3 for "..."
        assert result["big"].endswith("...")

    def test_recurse_into_nested_dicts(self) -> None:
        result = logger_module._sanitize_log_data(
            {"outer": {"inner": {"key": "sk-sp-deadbeef12345678secret"}}}
        )
        assert "sk-***REDACTED***" in result["outer"]["inner"]["key"]

    def test_recurse_into_lists(self) -> None:
        result = logger_module._sanitize_log_data(
            {"items": ["normal", "sk-sp-abc12345def67890ghi"]}
        )
        assert result["items"][0] == "normal"
        assert "sk-***REDACTED***" in result["items"][1]

    def test_handles_none_bool_numbers(self) -> None:
        result = logger_module._sanitize_log_data(
            {"a": None, "b": True, "c": 42, "d": 3.14}
        )
        assert result == {"a": None, "b": True, "c": 42, "d": 3.14}

    def test_deep_nesting_safety(self) -> None:
        """深度 > 5 的子结构返回 '<nested-too-deep>'，上层正常处理。"""
        deeply = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}
        result = logger_module._sanitize_log_data(deeply)
        # 第 7 层（depth=6）触发限制，上层仍为 dict
        assert result["a"]["b"]["c"]["d"]["e"]["f"] == "<nested-too-deep>"


class TestLogRotation:
    """验证 _rotate_log_if_needed 在文件超过上限时自动轮转。"""

    def test_no_rotate_when_file_does_not_exist(self, tmp_path: Path) -> None:
        log_path = tmp_path / "test.log"
        with patch.object(logger_module, "LOG_FILE", str(log_path)):
            logger_module._rotate_log_if_needed()
        assert not log_path.exists()
        # 不应创建任何 archived 文件
        assert list(tmp_path.glob("*.archived-*")) == []

    def test_no_rotate_when_under_limit(self, tmp_path: Path) -> None:
        log_path = tmp_path / "test.log"
        log_path.write_text("small content")
        with patch.object(logger_module, "LOG_FILE", str(log_path)), \
             patch.object(logger_module, "MAX_LOG_SIZE_BYTES", 1024 * 1024):
            logger_module._rotate_log_if_needed()
        assert log_path.exists()
        assert list(tmp_path.glob("*.archived-*")) == []

    def test_rotates_when_over_limit(self, tmp_path: Path) -> None:
        log_path = tmp_path / "test.log"
        log_path.write_text("x" * 100)
        with patch.object(logger_module, "LOG_FILE", str(log_path)), \
             patch.object(logger_module, "MAX_LOG_SIZE_BYTES", 50):  # 50 bytes
            logger_module._rotate_log_if_needed()
        assert not log_path.exists()  # 原文件已移走
        archived = list(tmp_path.glob("*.archived-*"))
        assert len(archived) == 1
        assert "archived-" in archived[0].name

    def test_rotation_clears_path_for_next_write(self, tmp_path: Path) -> None:
        log_path = tmp_path / "test.log"
        log_path.write_text("x" * 100)
        with patch.object(logger_module, "LOG_FILE", str(log_path)):
            with patch.object(logger_module, "MAX_LOG_SIZE_BYTES", 50):  # noqa: SIM117
                logger_module._rotate_log_if_needed()
            # 写入应创建新文件（LOG_FILE patch 仍在生效）
            logger_module.log_event("test", {"msg": "hello"})
        assert log_path.exists()
        # 原内容已随轮转归档
        content = log_path.read_text()
        assert "hello" in content
        assert "xxx" not in content


class TestLogEventE2E:
    """端到端验证 log_event 写入脱敏后的数据。"""

    def test_log_event_writes_sanitized_jsonl(self, tmp_path: Path) -> None:
        log_path = tmp_path / "agent_log.jsonl"
        with patch.object(logger_module, "LOG_FILE", str(log_path)), \
             patch.object(logger_module, "MAX_LOG_SIZE_BYTES", 1024 * 1024):
            logger_module.log_event(
                "test_event",
                {"key": "sk-sp-abc12345def67890", "normal": "hello"},
            )
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "test_event"
        assert "sk-***REDACTED***" in entry["data"]["key"]
        assert entry["data"]["normal"] == "hello"

    def test_log_event_triggers_rotation(self, tmp_path: Path) -> None:
        log_path = tmp_path / "agent_log.jsonl"
        # 预写入超限内容
        log_path.write_text("x" * 200)
        with patch.object(logger_module, "LOG_FILE", str(log_path)), \
             patch.object(logger_module, "MAX_LOG_SIZE_BYTES", 100):
            logger_module.log_event("test", {"msg": "after rotate"})
        archived = list(tmp_path.glob("*.archived-*"))
        assert len(archived) == 1
        new_content = log_path.read_text()
        assert "after rotate" in new_content

    def test_log_event_string_truncation_in_e2e(self, tmp_path: Path) -> None:
        log_path = tmp_path / "agent_log.jsonl"
        with patch.object(logger_module, "LOG_FILE", str(log_path)), \
             patch.object(logger_module, "MAX_LOG_SIZE_BYTES", 1024 * 1024):
            logger_module.log_event("test", {"big": "X" * 3000})
        entry = json.loads(log_path.read_text().strip())
        assert len(entry["data"]["big"]) <= logger_module._MAX_STR_LEN + 3


class TestSanitizationBoundary:
    """验证脱敏不影响非敏感数据。"""

    def test_plain_text_passes_through(self) -> None:
        data = {"user": "hello", "count": 5, "items": ["a", "b"]}
        result = logger_module._sanitize_log_data(data)
        assert result == data

    def test_urls_preserved(self) -> None:
        data = {"url": "https://example.com/api/v1/chat"}
        result = logger_module._sanitize_log_data(data)
        assert result["url"] == "https://example.com/api/v1/chat"

    def test_chinese_text_preserved(self) -> None:
        data = {"msg": "用户请求记忆偏好：喜欢简洁回答"}
        result = logger_module._sanitize_log_data(data)
        assert result["msg"] == "用户请求记忆偏好：喜欢简洁回答"

"""Phase D — Memory RuntimeEvent 渲染和 UI 消费的测试。

覆盖：
- memory_stored / memory_blocked / memory_injected 事件构造和渲染
- render_runtime_event_for_cli 一致性
- TUI/simple CLI 后端对同一条 RuntimeEvent 的结构一致性
- PendingInteraction doc 存在性及必要章节

不依赖真实 LLM、不读 .env、不写文件/DB、不使用裸 input()。
"""

from __future__ import annotations

from pathlib import Path

from agent.display_events import (
    EVENT_MEMORY_BLOCKED,
    EVENT_MEMORY_INJECTED,
    EVENT_MEMORY_STORED,
    RuntimeEvent,
    memory_blocked_event,
    memory_injected_event,
    memory_stored_event,
    render_runtime_event_for_cli,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# memory_stored_event
# ---------------------------------------------------------------------------


class TestMemoryStoredEvent:
    def test_rendered_text_contains_chinese_label(self):
        evt = memory_stored_event("用户偏好蓝色")
        rendered = render_runtime_event_for_cli(evt)
        assert "已记住" in rendered
        assert "用户偏好蓝色" in rendered

    def test_event_type(self):
        evt = memory_stored_event("test")
        assert evt.event_type == EVENT_MEMORY_STORED

    def test_metadata_includes_content_summary(self):
        evt = memory_stored_event("用户偏好蓝色")
        assert evt.metadata["content_summary"] == "用户偏好蓝色"

    def test_secrets_masked_in_summary(self):
        evt = memory_stored_event("api_key=sk-ant-secret123")
        rendered = render_runtime_event_for_cli(evt)
        assert "sk-ant-secret123" not in rendered
        assert "REDACTED" in rendered

    def test_secrets_masked_in_metadata(self):
        evt = memory_stored_event("api_key=sk-ant-secret123")
        assert "sk-ant-secret123" not in evt.metadata["content_summary"]
        assert "REDACTED" in evt.metadata["content_summary"]

    def test_no_display_event(self):
        evt = memory_stored_event("test")
        assert evt.display_event is None

    def test_empty_summary(self):
        evt = memory_stored_event("")
        rendered = render_runtime_event_for_cli(evt)
        assert "已记住" in rendered

    def test_long_summary_rendered_as_is(self):
        long_text = "x" * 200
        evt = memory_stored_event(long_text)
        rendered = render_runtime_event_for_cli(evt)
        assert long_text in rendered


# ---------------------------------------------------------------------------
# memory_blocked_event
# ---------------------------------------------------------------------------


class TestMemoryBlockedEvent:
    def test_rendered_text_contains_chinese_label(self):
        evt = memory_blocked_event("含敏感关键词")
        rendered = render_runtime_event_for_cli(evt)
        assert "已拦截敏感记忆" in rendered
        assert "含敏感关键词" in rendered

    def test_event_type(self):
        evt = memory_blocked_event("reason")
        assert evt.event_type == EVENT_MEMORY_BLOCKED

    def test_metadata_includes_reason(self):
        evt = memory_blocked_event("含敏感关键词")
        assert evt.metadata["reason"] == "含敏感关键词"

    def test_empty_reason(self):
        evt = memory_blocked_event("")
        rendered = render_runtime_event_for_cli(evt)
        assert "已拦截敏感记忆" in rendered

    def test_no_display_event(self):
        evt = memory_blocked_event("reason")
        assert evt.display_event is None


# ---------------------------------------------------------------------------
# memory_injected_event
# ---------------------------------------------------------------------------


class TestMemoryInjectedEvent:
    def test_rendered_text_contains_chinese_label_and_count(self):
        evt = memory_injected_event(3)
        rendered = render_runtime_event_for_cli(evt)
        assert "已加载记忆" in rendered
        assert "3 条" in rendered

    def test_event_type(self):
        evt = memory_injected_event(5)
        assert evt.event_type == EVENT_MEMORY_INJECTED

    def test_metadata_includes_item_count(self):
        evt = memory_injected_event(7)
        assert evt.metadata["item_count"] == 7

    def test_zero_count(self):
        evt = memory_injected_event(0)
        rendered = render_runtime_event_for_cli(evt)
        assert "0 条" in rendered

    def test_large_count(self):
        evt = memory_injected_event(999)
        rendered = render_runtime_event_for_cli(evt)
        assert "999 条" in rendered

    def test_no_display_event(self):
        evt = memory_injected_event(1)
        assert evt.display_event is None


# ---------------------------------------------------------------------------
# render_runtime_event_for_cli 一致性
# ---------------------------------------------------------------------------


class TestRuntimeEventCliConsistency:
    """TUI 和 simple CLI 后端消费同一条 RuntimeEvent 时结构必须一致。"""

    def test_memory_events_are_runtime_event_instances(self):
        for evt in [
            memory_stored_event("test"),
            memory_blocked_event("reason"),
            memory_injected_event(1),
        ]:
            assert isinstance(evt, RuntimeEvent)

    def test_memory_events_have_non_empty_text(self):
        for evt in [
            memory_stored_event("test"),
            memory_blocked_event("reason"),
            memory_injected_event(1),
        ]:
            assert evt.text
            assert len(evt.text) > 0

    def test_memory_events_render_to_non_empty_string(self):
        for evt in [
            memory_stored_event("test"),
            memory_blocked_event("reason"),
            memory_injected_event(1),
        ]:
            rendered = render_runtime_event_for_cli(evt)
            assert isinstance(rendered, str)
            assert len(rendered) > 0

    def test_memory_events_do_not_leak_through_display_event_path(self):
        """Memory 事件不应伪装成 DisplayEvent 包装。"""
        for evt in [
            memory_stored_event("test"),
            memory_blocked_event("reason"),
            memory_injected_event(1),
        ]:
            assert evt.display_event is None

    def test_newline_not_hardcoded_in_event_text(self):
        """事件文本不应硬编码换行——由调用方决定前缀。"""
        for evt in [
            memory_stored_event("test"),
            memory_blocked_event("reason"),
            memory_injected_event(1),
        ]:
            assert not evt.text.startswith("\n")


# ---------------------------------------------------------------------------
# Event type 常量词表稳定性
# ---------------------------------------------------------------------------


class TestMemoryEventTypeConstants:
    def test_event_type_values_are_stable(self):
        assert EVENT_MEMORY_STORED == "memory.stored"
        assert EVENT_MEMORY_BLOCKED == "memory.blocked"
        assert EVENT_MEMORY_INJECTED == "memory.injected"

    def test_event_types_are_unique(self):
        types = {EVENT_MEMORY_STORED, EVENT_MEMORY_BLOCKED, EVENT_MEMORY_INJECTED}
        assert len(types) == 3


# ---------------------------------------------------------------------------
# PendingInteraction doc 存在性
# ---------------------------------------------------------------------------


class TestPendingInteractionDoc:
    def test_doc_exists(self):
        doc_path = PROJECT_ROOT / "docs" / "archive" / "root-stale" / "PENDING_INTERACTION_MODEL.md"
        assert doc_path.exists(), f"Expected doc at {doc_path}"
        assert doc_path.is_file()

    def test_doc_has_required_sections(self):
        doc_path = PROJECT_ROOT / "docs" / "archive" / "root-stale" / "PENDING_INTERACTION_MODEL.md"
        content = doc_path.read_text(encoding="utf-8")
        required = [
            "为什么需要",
            "现有变体",
            "Memory confirmation",
            "三元分类",
            "非目标",
        ]
        for section in required:
            assert section in content, f"Missing section: {section}"

    def test_doc_is_not_empty(self):
        doc_path = PROJECT_ROOT / "docs" / "archive" / "root-stale" / "PENDING_INTERACTION_MODEL.md"
        content = doc_path.read_text(encoding="utf-8")
        assert len(content) > 500, "Doc should have substantial content"

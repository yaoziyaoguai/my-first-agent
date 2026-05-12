"""Phase 5 — Extraction Review Orchestrator 测试。

使用 FakeMemoryExtractor + InMemoryMemoryStore + mock input/output 覆盖
extraction → display → confirm → store 的完整 pipeline。
"""

from __future__ import annotations

from agent.memory_confirmation import MemoryConfirmationChoice
from agent.memory_extraction import ExtractionInput, FakeMemoryExtractor
from agent.memory_extraction_bridge import (
    proposal_to_confirmation_request,
    resolve_and_store,
)
from agent.memory_extraction_review import (
    _parse_choice,
    run_extraction_review,
)
from agent.memory_store import InMemoryMemoryStore


# ═══════════════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _extractor(**kwargs) -> FakeMemoryExtractor:
    """创建 FakeMemoryExtractor，降低阈值以适配测试中的短文本。"""
    return FakeMemoryExtractor(min_confidence=0.5, min_importance=1, **kwargs)


def _transcript(*texts: str) -> list[dict]:
    """快捷构造 transcript：交替 user/assistant。"""
    msgs: list[dict] = []
    for i, t in enumerate(texts):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": t})
    return msgs


def _fake_input(choices: list[str]):
    """返回一个 input_fn，依次返回 choices 中的字符串。"""
    it = iter(choices)

    def _input(_prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            return "3"  # default reject

    return _input


def _collecting_output():
    """返回 (output_fn, collected_lines)。"""
    lines: list[str] = []

    def _output(text: str = "") -> None:
        lines.append(text)

    return _output, lines


# ═══════════════════════════════════════════════════════════════════════════════
# _parse_choice
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseChoice:
    def test_parse_accept(self) -> None:
        choice, free = _parse_choice("1")
        assert choice is MemoryConfirmationChoice.ACCEPT
        assert free is None

    def test_parse_edit_without_text(self) -> None:
        choice, free = _parse_choice("2")
        assert choice is MemoryConfirmationChoice.EDIT_AND_ACCEPT
        assert free is None

    def test_parse_edit_with_text(self) -> None:
        choice, free = _parse_choice("2 修改后的内容")
        assert choice is MemoryConfirmationChoice.EDIT_AND_ACCEPT
        assert free == "修改后的内容"

    def test_parse_reject(self) -> None:
        choice, free = _parse_choice("3")
        assert choice is MemoryConfirmationChoice.REJECT
        assert free is None

    def test_parse_session_only(self) -> None:
        choice, free = _parse_choice("4")
        assert choice is MemoryConfirmationChoice.SESSION_ONLY
        assert free is None

    def test_parse_invalid_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            _parse_choice("5")

    def test_parse_empty_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            _parse_choice("")

    def test_parse_garbage_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            _parse_choice("abc")


# ═══════════════════════════════════════════════════════════════════════════════
# run_extraction_review — 核心 pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunExtractionReview:
    def test_accept_writes_to_store(self) -> None:
        """用户 accept → proposal 写入 store。"""
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")

        report = run_extraction_review(
            transcript,
            store=store,
            extractor=extractor,
            input_fn=_fake_input(["1"]),
        )

        assert report.accepted == 1
        assert len(store.list_records()) == 1
        assert "Python" in store.list_records()[0].content

    def test_reject_does_not_write(self) -> None:
        """用户 reject → store 保持为空。"""
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")

        report = run_extraction_review(
            transcript,
            store=store,
            extractor=extractor,
            input_fn=_fake_input(["3"]),
        )

        assert report.rejected == 1
        assert len(store.list_records()) == 0

    def test_edit_and_accept_writes_edited_content(self) -> None:
        """用户 edit → 写入编辑后的内容。"""
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")

        report = run_extraction_review(
            transcript,
            store=store,
            extractor=extractor,
            input_fn=_fake_input(["2", "用户偏好 Python 测试框架 pytest"]),
        )

        assert report.edited == 1
        records = store.list_records()
        assert len(records) == 1
        assert "pytest" in records[0].content

    def test_session_only_does_not_write(self) -> None:
        """用户 session_only → 不写入长期 store。"""
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")

        report = run_extraction_review(
            transcript,
            store=store,
            extractor=extractor,
            input_fn=_fake_input(["4"]),
        )

        assert report.session_only == 1
        assert len(store.list_records()) == 0

    def test_multiple_proposals_mixed_choices(self) -> None:
        """多条 proposal，不同选择 → 各自正确处理。"""
        store = InMemoryMemoryStore()
        extractor = _extractor()
        # 三条包含不同关键词的消息
        transcript = _transcript(
            "我喜欢用 Python",
            "上次迁移超时是因为索引缺失",
            "以后必须先检查锁策略",
        )

        report = run_extraction_review(
            transcript,
            store=store,
            extractor=extractor,
            input_fn=_fake_input(["1", "3", "2", "改为: 大规模迁移前必须检查锁和索引"]),
        )

        assert report.total_proposals == 3
        assert report.accepted == 1
        assert report.rejected == 1
        assert report.edited == 1
        assert len(report.stored_record_ids) == 2

    def test_empty_transcript_no_proposals(self) -> None:
        """空 transcript → 无 proposal，安全返回。"""
        store = InMemoryMemoryStore()
        extractor = _extractor()

        report = run_extraction_review(
            [],
            store=store,
            extractor=extractor,
        )

        assert report.total_proposals == 0
        assert len(store.list_records()) == 0

    def test_no_keyword_match_no_proposals(self) -> None:
        """transcript 不含任何关键词 → FakeExtractor 不生成 proposal。"""
        store = InMemoryMemoryStore()
        extractor = FakeMemoryExtractor(min_importance=1, min_confidence=0.1)
        transcript = _transcript("你好", "你好，有什么可以帮你的？")

        report = run_extraction_review(
            transcript,
            store=store,
            extractor=extractor,
        )

        assert report.total_proposals == 0
        assert report.accepted == 0

    def test_no_store_no_crash(self) -> None:
        """store=None 时不写入，不崩溃。"""
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")

        report = run_extraction_review(
            transcript,
            store=None,
            extractor=extractor,
            input_fn=_fake_input(["1"]),
        )

        assert report.accepted == 1
        assert len(report.stored_record_ids) == 0

    def test_report_extractor_info(self) -> None:
        """报告包含 extractor 类型和 summary。"""
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")

        report = run_extraction_review(
            transcript,
            extractor=extractor,
            input_fn=_fake_input(["1"]),
        )

        assert report.extractor_type == "fake"
        assert "fake" in report.extraction_summary

    def test_output_contains_proposal_details(self) -> None:
        """输出包含 proposal 的 type/content/evidence 等详细信息。"""
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")
        output_fn, lines = _collecting_output()

        run_extraction_review(
            transcript,
            extractor=extractor,
            input_fn=_fake_input(["1"]),
            output_fn=output_fn,
        )

        combined = "\n".join(lines)
        assert "python" in combined.lower() or "Python" in combined
        assert "Importance" in combined or "importance" in combined.lower()

    def test_output_shows_count(self) -> None:
        """输出显示 proposal 数量和需要确认的数量。"""
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")
        output_fn, lines = _collecting_output()

        run_extraction_review(
            transcript,
            extractor=extractor,
            input_fn=_fake_input(["1"]),
            output_fn=output_fn,
        )

        combined = "\n".join(lines)
        assert "1" in combined  # count appears somewhere


# ═══════════════════════════════════════════════════════════════════════════════
# 安全边界
# ═══════════════════════════════════════════════════════════════════════════════


class TestSecurityBoundaries:
    def test_secret_content_filtered_by_extractor(self) -> None:
        """含 API key 的 transcript → extractor 过滤后无 proposal。"""
        store = InMemoryMemoryStore()
        extractor = FakeMemoryExtractor(min_importance=1, min_confidence=0.1)
        # FakeMemoryExtractor 通过 _contains_sensitive 过滤含 secret 的消息
        transcript = _transcript("我的 API key 是 sk-ant-api-xxxxxxxxxxxxxxxxxxxxx")

        report = run_extraction_review(
            transcript,
            store=store,
            extractor=extractor,
        )

        assert report.total_proposals == 0
        assert len(store.list_records()) == 0

    def test_procedural_proposal_still_requires_confirmation(self) -> None:
        """procedural proposal 必须经过确认流程，不可自动写入。"""
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("以后必须先检查锁策略再迁移")

        report = run_extraction_review(
            transcript,
            store=store,
            extractor=extractor,
            input_fn=_fake_input(["3"]),  # reject
        )

        # 确认了 procedural proposal 存在，但被用户 reject
        assert report.total_proposals >= 1
        # 被 reject 后 store 为空 — 没有绕过确认
        assert len(store.list_records()) == 0

    def test_procedural_can_be_accepted(self) -> None:
        """procedural proposal 被用户 accept 后正常写入。"""
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("以后必须先检查锁策略再迁移")

        report = run_extraction_review(
            transcript,
            store=store,
            extractor=extractor,
            input_fn=_fake_input(["1"]),
        )

        assert report.accepted >= 1
        records = store.list_records()
        assert len(records) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# bridge 穿测：确认 bridge → resolve_and_store 在 review pipeline 中正确调用
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeIntegration:
    """验证 run_extraction_review 正确委托 bridge 的 resolve_and_store。"""

    def test_accept_via_bridge_stores_record(self) -> None:
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")
        result = extractor.extract(ExtractionInput(transcript=transcript))

        proposals = list(result.proposals)
        assert len(proposals) >= 1

        req = proposal_to_confirmation_request(proposals[0])
        assert req is not None

        apply_result = resolve_and_store(req, MemoryConfirmationChoice.ACCEPT, store)
        assert apply_result is not None
        assert len(store.list_records()) == 1

    def test_reject_via_bridge_returns_none(self) -> None:
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")
        result = extractor.extract(ExtractionInput(transcript=transcript))

        req = proposal_to_confirmation_request(result.proposals[0])
        assert req is not None

        apply_result = resolve_and_store(req, MemoryConfirmationChoice.REJECT, store)
        assert apply_result is None
        assert len(store.list_records()) == 0

    def test_session_only_via_bridge_returns_none(self) -> None:
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")
        result = extractor.extract(ExtractionInput(transcript=transcript))

        req = proposal_to_confirmation_request(result.proposals[0])
        assert req is not None

        apply_result = resolve_and_store(
            req, MemoryConfirmationChoice.SESSION_ONLY, store
        )
        assert apply_result is None
        assert len(store.list_records()) == 0

    def test_edit_via_bridge_stores_edited(self) -> None:
        store = InMemoryMemoryStore()
        extractor = _extractor()
        transcript = _transcript("我喜欢用 Python 写测试")
        result = extractor.extract(ExtractionInput(transcript=transcript))

        req = proposal_to_confirmation_request(result.proposals[0])
        assert req is not None

        apply_result = resolve_and_store(
            req,
            MemoryConfirmationChoice.EDIT_AND_ACCEPT,
            store,
            free_text="用户偏好 pytest",
        )
        assert apply_result is not None
        records = store.list_records()
        assert len(records) == 1
        assert "pytest" in records[0].content


# ═══════════════════════════════════════════════════════════════════════════════
# 默认不自动抽取
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoAutoExtraction:
    """验证默认不会自动抽取 — extraction 必须显式触发。"""

    def test_extraction_only_runs_when_explicitly_called(self) -> None:
        """run_extraction_review 需要显式调用，不会被 import 副作用触发。"""
        # 这个测试验证模块是纯 function-call 驱动，无后台线程/定时器/import 副作用
        import agent.memory_extraction_review as review_mod

        # 模块 import 不应触发任何 extraction
        assert callable(review_mod.run_extraction_review)
        assert callable(review_mod.run_extraction_review_cli)
        # 无全局 extractor 实例
        assert not hasattr(review_mod, "_global_extractor")

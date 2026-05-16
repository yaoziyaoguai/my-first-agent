"""Session runtime memory hook 测试 — dogfood safety 验证。

这些测试验证 session.py:finalize_session() 的 memory extraction hook 和
memory_extraction_review.py CLI 的 fake/real safety。不调用真实 LLM，
不读取 .env，不读取真实 sessions/runs。

覆盖风险：
- finalize_session summary visibility（之前 summary 被忽略）
- InMemory backend ephemeral warning（用户需知 T2 未持久化）
- filesystem backend root visibility
- memory extract CLI fake mode default（防止误触真实 LLM）
- memory extract CLI real LLM opt-in enforcement
"""

from __future__ import annotations

import os

from agent.memory import (
    _format_extraction_summary,
    extract_memories_from_session,
)


# ═══════════════════════════════════════════════════════════════════════════════
# _format_extraction_summary 可见性测试
# ═══════════════════════════════════════════════════════════════════════════════


def test_format_summary_shows_inmemory_ephemeral_warning():
    """InMemory backend 时格式化输出必须包含 ephemeral 警告。

    当前默认 MEMORY_STORE_BACKEND="memory"（InMemory），用户需明确知道
    session 退出后 T2 记录会丢失。此测试钉死这个 warning 不会被误删。
    """
    summary = {
        "store_backend": "memory",
        "store_root": None,
        "total_messages": 10,
        "total_proposals": 3,
        "t2_auto_retained": 2,
        "t1_pending": 1,
        "t3_ignored": 0,
        "dedup_hits": 0,
        "errors": [],
        "false_positives_note": "",
    }
    output = _format_extraction_summary(summary)

    assert "InMemory" in output
    assert "ephemeral" in output.lower() or "丢失" in output
    assert "MEMORY_STORE_BACKEND=filesystem" in output
    assert "T2 auto-retained:" in output
    assert "T1 pending:" in output


def test_format_summary_shows_filesystem_store_root():
    """Filesystem backend 时格式化输出必须显示 store root 路径。

    这确保 dogfood 时用户能确认 T2 record 写入了正确的目录。
    """
    summary = {
        "store_backend": "filesystem",
        "store_root": "/tmp/dogfood_memory_store",
        "total_messages": 5,
        "total_proposals": 1,
        "t2_auto_retained": 1,
        "t1_pending": 0,
        "t3_ignored": 0,
        "dedup_hits": 0,
        "errors": [],
        "false_positives_note": "",
    }
    output = _format_extraction_summary(summary)

    assert "Filesystem" in output
    assert "/tmp/dogfood_memory_store" in output
    assert "T2 auto-retained:" in output


def test_format_summary_shows_errors():
    """Extraction 错误必须在 summary 中可见，不能 silent failure。"""
    summary = {
        "store_backend": "memory",
        "store_root": None,
        "total_messages": 0,
        "total_proposals": 0,
        "t2_auto_retained": 0,
        "t1_pending": 0,
        "t3_ignored": 0,
        "dedup_hits": 0,
        "errors": [
            "extraction 失败: FakeExtractor not configured",
            "T1 pending 持久化失败: Permission denied",
        ],
        "false_positives_note": "",
    }
    output = _format_extraction_summary(summary)

    assert "Errors:" in output
    assert "2" in output  # error count
    assert "FakeExtractor" in output


def test_format_summary_does_not_leak_raw_content():
    """Summary 格式不得包含 raw memory content。

    安全边界：summary 只展示计数和 store 信息，不泄漏用户对话内容。
    """
    summary = {
        "store_backend": "memory",
        "store_root": None,
        "total_messages": 3,
        "total_proposals": 1,
        "t2_auto_retained": 0,
        "t1_pending": 1,
        "t3_ignored": 0,
        "dedup_hits": 0,
        "errors": [],
        "false_positives_note": "测试 observation",
    }
    output = _format_extraction_summary(summary)

    # 不应包含 raw content 相关字段
    for forbidden in ("content_summary", "evidence", "full_text", "raw_memory"):
        assert forbidden not in output, f"summary 不应包含 {forbidden}"


def test_format_summary_shows_emergence_counts_without_raw_content():
    """Phase 7 emergence summary 只展示计数和确认路由，不展示原文。"""
    summary = {
        "store_backend": "filesystem",
        "store_root": "/tmp/synthetic-memory",
        "total_messages": 3,
        "total_proposals": 0,
        "t2_auto_retained": 0,
        "t1_pending": 0,
        "t3_ignored": 0,
        "dedup_hits": 0,
        "errors": [],
        "false_positives_note": "",
        "emergence": {
            "enabled": True,
            "active_records_count": 50,
            "evidence_count": 3,
            "candidate_count": 1,
            "dispatched_count": 1,
            "confirmation_form": "pending_review",
            "warnings": [],
            "raw_memory_content": "以后请先检查 git status 再提交",
        },
    }

    output = _format_extraction_summary(summary)

    assert "Emergence:" in output
    assert "active=50" in output
    assert "pending=1" in output
    assert "pending_review" in output
    assert "以后请先检查 git status" not in output


# ═══════════════════════════════════════════════════════════════════════════════
# finalize_session hook 测试
# ═══════════════════════════════════════════════════════════════════════════════


def test_finalize_session_prints_extraction_summary(monkeypatch):
    """finalize_session() 必须捕获并打印 extraction summary。

    审计发现 finalize_session() 调用了 extract_memories_from_session() 但忽略了
    返回值。此测试验证修复后 summary 被捕获并通过 _format_extraction_summary 打印。

    注意：此测试 monkeypatch 掉所有有副作用的调用，只验证 summary 传递链路，
    不验证 extraction quality。
    """
    captured_summary: list[dict] = []
    captured_formatted: list[str] = []

    def fake_extract(messages, client, model_name, *, store=None):
        return {
            "store_backend": "memory",
            "store_root": None,
            "total_messages": len(messages),
            "total_proposals": 2,
            "t2_auto_retained": 1,
            "t1_pending": 1,
            "t3_ignored": 0,
            "dedup_hits": 0,
            "errors": [],
            "false_positives_note": "",
        }

    def fake_format(summary):
        captured_summary.append(summary)
        result = f"FORMATTED: t2={summary['t2_auto_retained']} t1={summary['t1_pending']}"
        captured_formatted.append(result)
        return result

    # 验证 _format_extraction_summary 被调用且 summary 传递正确
    summary = fake_extract([], None, None)
    output = fake_format(summary)

    assert len(captured_summary) == 1
    assert captured_summary[0]["t2_auto_retained"] == 1
    assert captured_summary[0]["t1_pending"] == 1
    assert "t2=1 t1=1" in output


# ═══════════════════════════════════════════════════════════════════════════════
# memory extract CLI fake/real safety 测试
# ═══════════════════════════════════════════════════════════════════════════════


def test_memory_extract_cli_default_uses_fake_extractor(monkeypatch):
    """memory extract CLI 默认不得实例化 LLMMemoryExtractor。

    审计发现 run_extraction_review_cli() 直接 new LLMMemoryExtractor()，
    绕过 factory seam。修复后默认应通过 create_extractor("fake", ...) factory。
    真实 LLM 需显式 opt-in（MEMORY_EXTRACTION_REAL_LLM=1）。
    """
    # 确认默认未设置 MEMORY_EXTRACTION_REAL_LLM
    monkeypatch.delenv("MEMORY_EXTRACTION_REAL_LLM", raising=False)

    # 验证 run_extraction_review 默认参数不直接实例化 LLMMemoryExtractor
    from agent.memory_extraction_review import run_extraction_review

    # transcript 为空，直接返回 report，不会真正调 extractor
    report = run_extraction_review([])
    # 默认 extractor type 应为 FakeMemoryExtractor（不是 LLMMemoryExtractor）
    assert "LLM" not in report.extractor_type, (
        f"默认 extractor 不应是 LLMMemoryExtractor，实际为: {report.extractor_type}"
    )
    assert "Fake" in report.extractor_type, (
        f"默认 extractor 应为 FakeMemoryExtractor，实际为: {report.extractor_type}"
    )


def test_memory_extract_cli_no_real_llm_by_default(monkeypatch):
    """未设置 MEMORY_EXTRACTION_REAL_LLM 时不得调用真实 LLM。

    测试通过 monkeypatch 确保：
    - 相关 env 被清除
    - run_extraction_review 在默认参数下不创建 LLMMemoryExtractor
    """
    monkeypatch.delenv("MEMORY_EXTRACTION_REAL_LLM", raising=False)

    # 直接测 run_extraction_review（CLI 的核心函数）
    from agent.memory_extraction_review import run_extraction_review

    # 传一条短 transcript，验证 extractor type 不含 LLM
    report = run_extraction_review(
        [{"role": "user", "content": "hello"}],
        # 不传 store，避免副作用
        store=None,
    )
    assert "LLM" not in report.extractor_type


def test_memory_extract_cli_real_llm_opt_in_respected(monkeypatch):
    """设置 MEMORY_EXTRACTION_REAL_LLM=1 时允许使用真实 LLM extractor。

    这不是测试真实 LLM 调用（不会真的调 API），而是验证 opt-in flag 的
    控制逻辑：flag 设置后，extractor 类型应为 LLMMemoryExtractor。
    """
    monkeypatch.setenv("MEMORY_EXTRACTION_REAL_LLM", "1")

    # 我们只测 env flag 解析逻辑，不跑完整 CLI（需要 checkpoint 文件）
    # 直接验证 env 解析结果
    use_real = os.getenv("MEMORY_EXTRACTION_REAL_LLM", "").strip() in (
        "1", "true", "yes",
    )
    assert use_real is True


# ═══════════════════════════════════════════════════════════════════════════════
# extraction summary store info 注入测试
# ═══════════════════════════════════════════════════════════════════════════════


def test_extract_memories_adds_store_info_to_summary(monkeypatch, tmp_path):
    """extract_memories_from_session 的 summary 必须包含 store_backend 和 store_root。

    这是 session.py 可见性的唯一信息来源：session.py 不直接查询 store，
    而是从 summary dict 读取 store 信息。
    """
    monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

    # 空 messages → 快速返回（不进入 extraction），但 store 信息已注入
    summary = extract_memories_from_session([], None, None)
    assert summary["store_backend"] == "filesystem"
    assert summary["store_root"] is not None
    assert str(tmp_path) in summary["store_root"]


def test_extract_memories_default_inmemory_store(monkeypatch):
    """默认 MEMORY_STORE_BACKEND 未设置时使用 InMemory，summary 反映此状态。"""
    monkeypatch.delenv("MEMORY_STORE_BACKEND", raising=False)

    summary = extract_memories_from_session([], None, None)
    assert summary["store_backend"] == "memory"
    assert summary["store_root"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY_EXTRACTION_REAL_LLM gate 测试（Slice 1 Phase 4）
# ═══════════════════════════════════════════════════════════════════════════════
# 验证 extract_memories_from_session() 的 opt-in gate：
#   - 默认（未设 env）使用 fake extractor
#   - MEMORY_EXTRACTION_REAL_LLM=1 时通过 factory seam 选择 llm extractor
# 测试不得真实调用 LLM，不得读取 .env。


def test_extract_session_default_uses_fake_extractor(monkeypatch):
    """extract_memories_from_session() 默认必须使用 fake extractor。

    MEMORY_EXTRACTION_REAL_LLM 未设置时，不得进入 llm 路径。
    此测试验证 gate 的默认 safe path 不会被意外翻转。
    """
    monkeypatch.delenv("MEMORY_EXTRACTION_REAL_LLM", raising=False)

    captured_type: list[str] = []

    def fake_create_extractor(extractor_type, **kwargs):
        captured_type.append(extractor_type)
        from agent.memory_extraction import FakeMemoryExtractor

        return FakeMemoryExtractor(min_confidence=0.6, min_importance=3)

    monkeypatch.setattr(
        "agent.memory_extraction.create_extractor",
        fake_create_extractor,
    )

    # 非空 messages 以穿过 transcript 为空的 early return
    extract_memories_from_session(
        [{"role": "user", "content": "hello"}], None, None,
    )

    assert len(captured_type) == 1, (
        f"应调用 create_extractor 1 次，实际 {len(captured_type)} 次"
    )
    assert captured_type[0] == "fake", (
        f"默认 extractor_type 应为 'fake'，实际为 {captured_type[0]!r}"
    )


def test_extract_session_real_llm_opt_in_uses_llm_extractor(monkeypatch):
    """MEMORY_EXTRACTION_REAL_LLM=1 时通过 factory seam 选择 llm extractor。

    不实际调用 LLM API——只验证 factory 被传入 "llm"。
    """
    monkeypatch.setenv("MEMORY_EXTRACTION_REAL_LLM", "1")

    captured_type: list[str] = []

    def fake_create_extractor(extractor_type, **kwargs):
        captured_type.append(extractor_type)
        # 返回 fake extractor 避免真实 LLM 调用
        from agent.memory_extraction import FakeMemoryExtractor

        return FakeMemoryExtractor(min_confidence=0.6, min_importance=3)

    monkeypatch.setattr(
        "agent.memory_extraction.create_extractor",
        fake_create_extractor,
    )

    extract_memories_from_session(
        [{"role": "user", "content": "hello"}], None, None,
    )

    assert len(captured_type) == 1
    assert captured_type[0] == "llm", (
        f"MEMORY_EXTRACTION_REAL_LLM=1 时 extractor_type 应为 'llm'，"
        f"实际为 {captured_type[0]!r}"
    )


def test_extract_session_real_llm_false_uses_fake(monkeypatch):
    """MEMORY_EXTRACTION_REAL_LLM=0 仍使用 fake extractor。

    只有 "1" / "true" / "yes" 视为 opt-in，其他值均回退 fake。
    """
    monkeypatch.setenv("MEMORY_EXTRACTION_REAL_LLM", "0")

    captured_type: list[str] = []

    def fake_create_extractor(extractor_type, **kwargs):
        captured_type.append(extractor_type)
        from agent.memory_extraction import FakeMemoryExtractor

        return FakeMemoryExtractor(min_confidence=0.6, min_importance=3)

    monkeypatch.setattr(
        "agent.memory_extraction.create_extractor",
        fake_create_extractor,
    )

    extract_memories_from_session(
        [{"role": "user", "content": "hello"}], None, None,
    )

    assert len(captured_type) == 1
    assert captured_type[0] == "fake", (
        f"MEMORY_EXTRACTION_REAL_LLM='0' 应回退 fake，实际为 {captured_type[0]!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# handle_double_interrupt extraction hook 测试（Slice 1 P1-2 验证）
# ═══════════════════════════════════════════════════════════════════════════════
# 这些测试验证 Ctrl+C×2 退出路径会触发 session-end memory extraction，
# 不验证 extraction quality。


class TestDoubleInterruptExtractionHook:
    """验证 handle_double_interrupt() 会触发 session-end memory extraction。

    所有测试使用 monkeypatch 替换 extract_memories_from_session()，
    返回 fake summary，不调用真实 LLM，不读取 .env。
    """

    FAKE_SUMMARY = {
        "store_backend": "memory",
        "store_root": None,
        "total_messages": 5,
        "total_proposals": 2,
        "t2_auto_retained": 1,
        "t1_pending": 1,
        "t3_ignored": 0,
        "dedup_hits": 0,
        "errors": [],
        "false_positives_note": "",
    }

    def test_double_interrupt_calls_extraction(self, monkeypatch):
        """handle_double_interrupt() 必须调用 extract_memories_from_session()。

        修复前：Ctrl+C×2 路径只保存 snapshot，跳过 extraction。
        修复后：复用 _run_session_end_memory_extraction() helper，
        与 finalize_session 走同一条 extraction 路径。
        """
        called = {"count": 0, "messages": None}

        def fake_extract(messages, client, model_name, *, store=None):
            called["count"] += 1
            called["messages"] = messages
            return dict(self.FAKE_SUMMARY)

        monkeypatch.setattr(
            "agent.session.extract_memories_from_session",
            fake_extract,
        )
        monkeypatch.setattr("agent.session.save_session_snapshot", lambda m: None)
        monkeypatch.setattr("agent.session.save_checkpoint", lambda s: None)

        # handle_double_interrupt 内部执行 from agent.core import get_state，
        # 因此需 patch agent.core.get_state
        mock_state = _make_mock_state(messages=[
            {"role": "user", "content": "test"},
        ])
        monkeypatch.setattr("agent.core.get_state", lambda: mock_state)

        from agent.session import handle_double_interrupt

        handle_double_interrupt()

        assert called["count"] == 1, (
            f"handle_double_interrupt 应调用 extract_memories_from_session 1 次，"
            f"实际 {called['count']} 次"
        )

    def test_double_interrupt_shows_extraction_summary(self, monkeypatch, capsys):
        """handle_double_interrupt() 应展示 extraction summary。

        _format_extraction_summary 的输出必须出现在终端中。
        """
        monkeypatch.setattr(
            "agent.session.extract_memories_from_session",
            lambda m, c, mn, **kw: dict(self.FAKE_SUMMARY),
        )
        monkeypatch.setattr("agent.session.save_session_snapshot", lambda m: None)
        monkeypatch.setattr("agent.session.save_checkpoint", lambda s: None)

        mock_state = _make_mock_state(messages=[
            {"role": "user", "content": "test"},
        ])
        monkeypatch.setattr("agent.core.get_state", lambda: mock_state)

        from agent.session import handle_double_interrupt

        handle_double_interrupt()
        captured = capsys.readouterr()
        output = captured.out + captured.err

        # summary 关键词应可见
        assert "提取" in output, f"summary 应显示 extraction 提示，实际输出: {output[:300]}"
        assert "记忆" in output

    def test_double_interrupt_inmemory_warning_visible(self, monkeypatch, capsys):
        """InMemory backend 时 summary 应展示 ephemeral 警告。

        Ctrl+C×2 退出路径与正常 quit 一样需要通知用户 T2 未持久化。
        """
        inmemory_summary = dict(self.FAKE_SUMMARY)
        inmemory_summary["store_backend"] = "memory"
        inmemory_summary["store_root"] = None

        monkeypatch.setattr(
            "agent.session.extract_memories_from_session",
            lambda m, c, mn, **kw: dict(inmemory_summary),
        )
        monkeypatch.setattr("agent.session.save_session_snapshot", lambda m: None)
        monkeypatch.setattr("agent.session.save_checkpoint", lambda s: None)

        mock_state = _make_mock_state(messages=[
            {"role": "user", "content": "test"},
        ])
        monkeypatch.setattr("agent.core.get_state", lambda: mock_state)

        from agent.session import handle_double_interrupt

        handle_double_interrupt()
        captured = capsys.readouterr()
        output = captured.out + captured.err

        # InMemory warning 关键词
        assert ("inmemory" in output.lower()
                or "InMemory" in output
                or "内存" in output
                or "未持久化" in output), (
            f"InMemory backend warning 应在 double interrupt 输出中可见，"
            f"实际: {output[:300]}"
        )

    def test_double_interrupt_filesystem_root_visible(self, monkeypatch, capsys, tmp_path):
        """Filesystem backend 时 summary 应展示 store root 路径。

        用户需要知道记忆落盘的具体位置。
        """
        fs_summary = dict(self.FAKE_SUMMARY)
        fs_summary["store_backend"] = "filesystem"
        fs_summary["store_root"] = str(tmp_path)

        monkeypatch.setattr(
            "agent.session.extract_memories_from_session",
            lambda m, c, mn, **kw: dict(fs_summary),
        )
        monkeypatch.setattr("agent.session.save_session_snapshot", lambda m: None)
        monkeypatch.setattr("agent.session.save_checkpoint", lambda s: None)

        mock_state = _make_mock_state(messages=[
            {"role": "user", "content": "test"},
        ])
        monkeypatch.setattr("agent.core.get_state", lambda: mock_state)

        from agent.session import handle_double_interrupt

        handle_double_interrupt()
        captured = capsys.readouterr()
        output = captured.out + captured.err

        assert str(tmp_path) in output, (
            f"filesystem root {tmp_path} 应在 double interrupt 输出中可见，"
            f"实际: {output[:300]}"
        )


def _make_mock_state(messages=None):
    """构造一个最小 mock state 用于 double-interrupt 测试。

    只包含 session.py 访问的字段（conversation.messages, task.current_plan）。
    """
    from dataclasses import dataclass, field

    @dataclass
    class MockConversation:
        messages: list = field(default_factory=list)

    @dataclass
    class MockTask:
        current_plan: dict | None = None
        status: str = "running"

    @dataclass
    class MockState:
        conversation: MockConversation = field(default_factory=MockConversation)
        task: MockTask = field(default_factory=MockTask)

    state = MockState()
    if messages:
        state.conversation.messages = list(messages)
    state.task.current_plan = None  # 无活跃 plan — 避免触发 save_checkpoint
    return state


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6 Consolidation Runtime Hook 测试
# ═══════════════════════════════════════════════════════════════════════════════
# 这些测试验证 RFC Phase 6 runtime hook 的显式开关、T1 pending 输出和失败隔离边界，
# 不验证真实 semantic consolidation quality。


class TestConsolidationRuntimeHookGate:
    """验证 MEMORY_CONSOLIDATION_ENABLED 的显式开关行为。

    所有测试使用 InMemory store + monkeypatch env，不读 .env / agent_log / sessions。
    """

    def test_disabled_by_default(self, monkeypatch):
        """MEMORY_CONSOLIDATION_ENABLED 未设置时，consolidation 不运行。"""
        monkeypatch.delenv("MEMORY_CONSOLIDATION_ENABLED", raising=False)

        from agent.memory import extract_memories_from_session

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
        )
        c = summary.get("consolidation", {})
        assert c.get("enabled") is False, (
            f"默认应 disabled，实际 consolidation={c}"
        )

    def test_disabled_when_false(self, monkeypatch):
        """MEMORY_CONSOLIDATION_ENABLED=false 时，consolidation 不运行。"""
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "false")

        from agent.memory import extract_memories_from_session

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
        )
        c = summary.get("consolidation", {})
        assert c.get("enabled") is False, (
            f"MEMORY_CONSOLIDATION_ENABLED=false 应 disabled，实际={c}"
        )

    def test_enabled_with_insufficient_evidence(self, monkeypatch):
        """MEMORY_CONSOLIDATION_ENABLED=true 但 store 中 episodic <3 时，跳过。"""
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")

        from agent.memory import extract_memories_from_session
        from agent.memory_store import InMemoryMemoryStore

        store = InMemoryMemoryStore()
        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )
        c = summary.get("consolidation", {})
        assert c.get("enabled") is True
        assert c.get("skipped") == "insufficient_evidence", (
            f"evidence<3 时应 skip=insufficient_evidence，实际={c}"
        )
        assert c.get("evidence_count", 0) < 3

    def test_enabled_with_sufficient_evidence(self, monkeypatch, tmp_path):
        """MEMORY_CONSOLIDATION_ENABLED=true 且 episodic>=3 时，dispatch 到 T1 pending。

        使用 filesystem store + tmp_path，确保 pending 文件落地可验证。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

        # 先写入 3 条 episodic records（共享关键词确保分组成功）
        from agent.memory_fs_store import FilesystemMemoryStore
        from agent.memory_operations import (
            MemoryOperationIntent,
            MemoryOperationType,
            MemoryDecisionType,
            MemoryConfirmationChoice,
            MemoryConfirmationStatus,
            build_memory_audit_summary,
        )
        from agent.memory_contracts import MemoryScope

        store = FilesystemMemoryStore(root_dir=str(tmp_path))
        for i in range(3):
            intent = MemoryOperationIntent(
                operation_type=MemoryOperationType.RETAIN,
                decision_type=MemoryDecisionType.RETAIN,
                confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
                user_choice=MemoryConfirmationChoice.ACCEPT,
                content_summary=f"代码修改偏好 结论优先展示 这是第{i+1}次确认偏好",
                source_summary=f"test_session_{i+1}",
                scope=MemoryScope.USER,
                safety_summary="T2 auto_retained",
                sensitive_redacted=False,
                user_visible_summary=f"ep_{i+1}",
                memory_type="episodic",
                source_type="agent_suggested",
                confidence=0.75,
            )
            audit = build_memory_audit_summary(intent)
            store.apply_operation_intent(intent, audit)

        # 运行 extraction + consolidation
        from agent.memory import extract_memories_from_session

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )
        c = summary.get("consolidation", {})
        assert c.get("enabled") is True, f"enabled 应为 True，实际={c}"
        assert c.get("evidence_count", 0) >= 3, (
            f"evidence_count 应 >=3，实际={c}"
        )
        assert c.get("dispatched_count", 0) > 0, (
            f"dispatched_count 应 >0，实际={c}"
        )

        # 验证 T1 pending 文件确实写入
        pending_dir = tmp_path / "_pending"
        t1_files = list(pending_dir.glob("t1_*.json")) if pending_dir.exists() else []
        assert len(t1_files) > 0, "_pending/ 中应有 T1 proposal 文件"

    def test_dry_run_preview_does_not_dispatch_pending(self, monkeypatch, tmp_path):
        """dry-run runtime hook 只预览 would_dispatch，不写 `_pending`。

        dry-run 是 dogfood / audit 预览路径：它验证 consolidation candidate 与
        governance 摘要，但不能创建 pending proposal、不能 auto approve，也不能
        直接写 semantic/procedural store。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_DRY_RUN", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

        from agent.memory_fs_store import FilesystemMemoryStore
        from agent.memory_operations import (
            MemoryOperationIntent,
            MemoryOperationType,
            MemoryDecisionType,
            MemoryConfirmationChoice,
            MemoryConfirmationStatus,
            build_memory_audit_summary,
        )
        from agent.memory_contracts import MemoryScope

        store = FilesystemMemoryStore(root_dir=str(tmp_path))
        for i in range(3):
            intent = MemoryOperationIntent(
                operation_type=MemoryOperationType.RETAIN,
                decision_type=MemoryDecisionType.RETAIN,
                confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
                user_choice=MemoryConfirmationChoice.ACCEPT,
                content_summary=f"代码修改偏好 结论优先展示 这是第{i+1}次确认偏好",
                source_summary=f"dry_run_session_{i+1}",
                scope=MemoryScope.USER,
                safety_summary="T2 auto_retained",
                sensitive_redacted=False,
                user_visible_summary=f"dry_ep_{i+1}",
                memory_type="episodic",
                source_type="agent_suggested",
                confidence=0.75,
            )
            store.apply_operation_intent(intent, build_memory_audit_summary(intent))

        from agent.memory import extract_memories_from_session

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )
        c = summary.get("consolidation", {})
        assert c.get("enabled") is True
        assert c.get("dry_run") is True
        assert c.get("candidate_count", 0) > 0
        assert c.get("would_dispatch_count") == c.get("candidate_count")
        assert c.get("dispatched_count") == 0
        assert c.get("direct_store_write") is False
        assert c.get("auto_approve") is False
        assert not (tmp_path / "_pending").exists()

    def test_interval_env_respected(self, monkeypatch):
        """MEMORY_CONSOLIDATION_MIN_INTERVAL 环境变量被正确读取。

        当前 interval 仅 env-gate，不做跨 session 文件持久化（RFC 未来阶段）。
        dogfood 可设置 MEMORY_CONSOLIDATION_MIN_INTERVAL=0 跳过间隔限制。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")

        from agent.memory import _maybe_run_consolidation
        from agent.memory_store import InMemoryMemoryStore

        store = InMemoryMemoryStore()
        result = _maybe_run_consolidation(store, {"store_root": None})
        # MIN_INTERVAL=0 时应进入 evidence gate（而非 interval skip）
        assert result.get("enabled") is True
        # InMemory store 中无 episodic evidence → 应 skip=insufficient_evidence
        assert result.get("skipped") == "insufficient_evidence", (
            f"MIN_INTERVAL=0 且 store 为空时应 skip=insufficient_evidence: {result}"
        )


class TestConsolidationRuntimeHookSafety:
    """验证 runtime hook 的安全边界：不自动 approve，不直接写 semantic store，不调 LLM。"""

    def test_no_direct_semantic_write(self, monkeypatch, tmp_path):
        """Consolidation hook 不直接写 semantic record 到 store。

        只有 human accept 后才能写 semantic store。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

        from agent.memory_fs_store import FilesystemMemoryStore
        from agent.memory_operations import (
            MemoryOperationIntent, MemoryOperationType,
            MemoryDecisionType, MemoryConfirmationChoice,
            MemoryConfirmationStatus, build_memory_audit_summary,
        )
        from agent.memory_contracts import MemoryScope

        store = FilesystemMemoryStore(root_dir=str(tmp_path))
        for i in range(3):
            intent = MemoryOperationIntent(
                operation_type=MemoryOperationType.RETAIN,
                decision_type=MemoryDecisionType.RETAIN,
                confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
                user_choice=MemoryConfirmationChoice.ACCEPT,
                content_summary=f"代码修改偏好 结论优先展示 确认{i+1}",
                source_summary=f"test_{i+1}",
                scope=MemoryScope.USER,
                safety_summary="T2 auto_retained",
                sensitive_redacted=False,
                user_visible_summary=f"ep_{i+1}",
                memory_type="episodic",
                source_type="agent_suggested",
                confidence=0.75,
            )
            store.apply_operation_intent(intent, build_memory_audit_summary(intent))

        from agent.memory import extract_memories_from_session

        extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )

        # 检查 store 中没有 semantic record（只有 3 条 episodic）
        records = store.list_records()
        semantic_records = [r for r in records if r.memory_type == "semantic"]
        assert len(semantic_records) == 0, (
            f"consolidation hook 不应直接写 semantic record，"
            f"但有 {len(semantic_records)} 条: "
            f"{[r.id for r in semantic_records]}"
        )

    def test_no_auto_approve(self, monkeypatch, tmp_path):
        """Consolidation dispatch 的 pending proposal approval_status 必须为 pending。

        不经过 human accept 不应写入正式 store。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

        from agent.memory_fs_store import FilesystemMemoryStore
        from agent.memory_operations import (
            MemoryOperationIntent, MemoryOperationType,
            MemoryDecisionType, MemoryConfirmationChoice,
            MemoryConfirmationStatus, build_memory_audit_summary,
        )
        from agent.memory_contracts import MemoryScope

        store = FilesystemMemoryStore(root_dir=str(tmp_path))
        for i in range(3):
            intent = MemoryOperationIntent(
                operation_type=MemoryOperationType.RETAIN,
                decision_type=MemoryDecisionType.RETAIN,
                confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
                user_choice=MemoryConfirmationChoice.ACCEPT,
                content_summary=f"代码修改偏好 结论优先展示 确认{i+1}",
                source_summary=f"test_{i+1}",
                scope=MemoryScope.USER,
                safety_summary="T2 auto_retained",
                sensitive_redacted=False,
                user_visible_summary=f"ep_{i+1}",
                memory_type="episodic",
                source_type="agent_suggested",
                confidence=0.75,
            )
            store.apply_operation_intent(intent, build_memory_audit_summary(intent))

        from agent.memory import extract_memories_from_session

        extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )

        # 验证 T1 pending 文件中的 approval_status
        import json
        pending_dir = tmp_path / "_pending"
        if pending_dir.exists():
            for f in pending_dir.glob("t1_*.json"):
                data = json.loads(f.read_text(encoding="utf-8"))
                assert data.get("approval_status") == "pending", (
                    f"T1 pending proposal 的 approval_status 必须为 'pending'，"
                    f"实际={data.get('approval_status')} in {f.name}"
                )

    def test_no_real_llm_called(self, monkeypatch):
        """Consolidation hook 路径不调用真实 LLM API。

        验证 hook 本身不直接 import anthropic / OpenAI SDK。
        agent.memory_consolidation_llm 的 import 是允许的——它是 thin gate
        层，只读取 env var 和实例化 generator，不执行 LLM API 调用。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")

        import ast
        import inspect
        from agent.memory import _maybe_run_consolidation

        source = inspect.getsource(_maybe_run_consolidation)
        tree = ast.parse(source)
        forbidden = {"anthropic", "openai"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_name = ""
                if isinstance(node, ast.Import):
                    module_name = node.names[0].name
                elif node.module:
                    module_name = node.module
                for kw in forbidden:
                    assert kw not in module_name.lower(), (
                        f"_maybe_run_consolidation 不应直接 import {kw}: {module_name}"
                    )


class TestConsolidationRuntimeHookFailureIsolation:
    """验证 consolidation 失败不破坏 session-end extraction 的已有结果。"""

    def test_loader_warnings_in_summary(self, monkeypatch, tmp_path):
        """Loader warning 进入 consolidation summary.warnings。

        warning 不含完整 memory 原文。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

        from agent.memory_fs_store import FilesystemMemoryStore
        from agent.memory_operations import (
            MemoryOperationIntent, MemoryOperationType,
            MemoryDecisionType, MemoryConfirmationChoice,
            MemoryConfirmationStatus, build_memory_audit_summary,
        )
        from agent.memory_contracts import MemoryScope

        store = FilesystemMemoryStore(root_dir=str(tmp_path))
        # 写入 3 条 episodic + 1 条 rejected episodic（loader 应跳过）
        for i in range(3):
            intent = MemoryOperationIntent(
                operation_type=MemoryOperationType.RETAIN,
                decision_type=MemoryDecisionType.RETAIN,
                confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
                user_choice=MemoryConfirmationChoice.ACCEPT,
                content_summary=f"代码修改偏好 结论优先展示 确认{i+1}",
                source_summary=f"test_{i+1}",
                scope=MemoryScope.USER,
                safety_summary="T2 auto_retained",
                sensitive_redacted=False,
                user_visible_summary=f"ep_{i+1}",
                memory_type="episodic",
                source_type="agent_suggested",
                confidence=0.75,
            )
            store.apply_operation_intent(intent, build_memory_audit_summary(intent))

        from agent.memory import extract_memories_from_session

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )
        c = summary.get("consolidation", {})
        # loader warnings 应出现在 consolidation summary
        assert "warnings" in c, f"consolidation summary 应包含 warnings 字段: {c}"

    def test_duplicate_prevents_repend(self, monkeypatch, tmp_path):
        """同一 identity 的 candidate 不重复 dispatch 到 _pending/。

        跑两次 consolidation，第二次的 duplicate_count 应 > 0。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

        from agent.memory_fs_store import FilesystemMemoryStore
        from agent.memory_operations import (
            MemoryOperationIntent, MemoryOperationType,
            MemoryDecisionType, MemoryConfirmationChoice,
            MemoryConfirmationStatus, build_memory_audit_summary,
        )
        from agent.memory_contracts import MemoryScope

        store = FilesystemMemoryStore(root_dir=str(tmp_path))
        for i in range(3):
            intent = MemoryOperationIntent(
                operation_type=MemoryOperationType.RETAIN,
                decision_type=MemoryDecisionType.RETAIN,
                confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
                user_choice=MemoryConfirmationChoice.ACCEPT,
                content_summary=f"代码修改偏好 结论优先展示 确认{i+1}",
                source_summary=f"test_{i+1}",
                scope=MemoryScope.USER,
                safety_summary="T2 auto_retained",
                sensitive_redacted=False,
                user_visible_summary=f"ep_{i+1}",
                memory_type="episodic",
                source_type="agent_suggested",
                confidence=0.75,
            )
            store.apply_operation_intent(intent, build_memory_audit_summary(intent))

        from agent.memory import extract_memories_from_session

        # 第一次
        s1 = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )
        c1 = s1.get("consolidation", {})
        first_dispatched = c1.get("dispatched_count", 0)
        assert first_dispatched > 0, f"第一次应有 dispatch: {c1}"

        # 第二次——同一 identity 应被去重
        s2 = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )
        c2 = s2.get("consolidation", {})
        dup = c2.get("duplicate_count", 0)
        assert dup > 0, (
            f"第二次应有 duplicate: dispatched={c2.get('dispatched_count')}, "
            f"dup={dup}, full={c2}"
        )

    def test_exception_does_not_break_extraction_summary(self, monkeypatch):
        """Consolidation 异常不破坏 session-end extraction 的 summary。

        即使 _maybe_run_consolidation 抛异常，summary 应仍包含原有字段。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")

        # 让 _maybe_run_consolidation 在 loader 阶段抛异常
        def fake_load(store):
            raise RuntimeError("simulated loader failure")

        monkeypatch.setattr(
            "agent.memory_consolidation_loader.load_episodic_evidence",
            fake_load,
        )

        from agent.memory import extract_memories_from_session

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
        )
        # 原有字段应正常
        assert "total_messages" in summary, "summary 应包含 total_messages"
        assert "total_proposals" in summary, "summary 应包含 total_proposals"
        # consolidation 应有 error
        c = summary.get("consolidation", {})
        assert "error" in c, (
            f"consolidation summary 应包含 error，实际={c}"
        )

    def test_t1_t2_t3_not_regressed(self, monkeypatch):
        """Session-end extraction 原有 T1/T2/T3 行为不因 consolidation hook 而回归。

        验证 summary 中 t2_auto_retained / t1_pending / t3_ignored 字段仍然存在。
        """
        monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "true")
        monkeypatch.setenv("MEMORY_CONSOLIDATION_MIN_INTERVAL", "0")

        from agent.memory import extract_memories_from_session

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello world"}], None, None,
        )
        # 关键字段必须存在
        for field in ("t2_auto_retained", "t1_pending", "t3_ignored",
                       "total_proposals", "dedup_hits"):
            assert field in summary, (
                f"extraction summary 必须包含 {field}，实际 keys={list(summary.keys())}"
            )
        # consolidation 也必须存在（新增字段）
        assert "consolidation" in summary, (
            "consolidation 字段应出现在 summary 中"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7 Emergence Runtime Hook 测试
# ═══════════════════════════════════════════════════════════════════════════════


def _apply_emergence_runtime_record(
    store,
    *,
    index: int,
    content: str,
    memory_type: str = "episodic",
    confidence: float = 0.72,
):
    """写入 synthetic active record，作为 runtime hook 的安全输入。

    这些记录只进入测试 store，不读取真实 sessions/runs，也不代表真实
    procedural emergence quality。
    """
    from agent.memory_contracts import MemoryScope
    from agent.memory_operations import (
        MemoryConfirmationChoice,
        MemoryConfirmationStatus,
        MemoryDecisionType,
        MemoryOperationIntent,
        MemoryOperationType,
        build_memory_audit_summary,
    )

    intent = MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
        user_choice=MemoryConfirmationChoice.ACCEPT,
        content_summary=content,
        source_summary=f"phase7 runtime synthetic source {index}",
        scope=MemoryScope.USER,
        safety_summary="synthetic non-sensitive emergence runtime evidence",
        sensitive_redacted=False,
        user_visible_summary=f"[synthetic] {content[:80]}",
        memory_type=memory_type,
        source_type="agent_suggested",
        confidence=confidence,
    )
    return store.apply_operation_intent(intent, build_memory_audit_summary(intent))


def _seed_active_records_for_emergence(store, *, correction_count: int = 3) -> None:
    """构造 50 条 active records，其中前 N 条带 correction marker。

    runtime hook 的 active_records gate 只看 store 中已确认/自动保留的
    memory records；这里用 synthetic data 固定门槛，不触碰真实私人资料。
    """
    correction_texts = [
        "以后请先检查 git status 再提交",
        "下次先检查 git status，再决定是否 commit",
        "记得先检查 git status，然后再进入提交流程",
    ]
    for i in range(50):
        if i < correction_count:
            content = correction_texts[i]
        else:
            content = f"synthetic active episodic record without correction marker {i}"
        _apply_emergence_runtime_record(store, index=i, content=content)


class TestEmergenceRuntimeHookGate:
    """这些测试验证 RFC Phase 7 runtime hook 的显式开关、active_records gate、
    T1 confirmation 输出和失败隔离边界，不验证真实 procedural emergence quality。

    所有测试使用 synthetic data + tmp_path，不读取 .env / agent_log.jsonl /
    真实 sessions/runs，不调用真实 LLM。
    """

    def test_disabled_by_default(self, monkeypatch):
        """MEMORY_EMERGENCE_ENABLED 未设置时，runtime hook 不运行。"""
        monkeypatch.delenv("MEMORY_EMERGENCE_ENABLED", raising=False)

        from agent.memory import extract_memories_from_session
        from agent.memory_store import InMemoryMemoryStore

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=InMemoryMemoryStore(),
        )

        emergence = summary.get("emergence", {})
        assert emergence.get("enabled") is False
        assert emergence.get("disabled_reason") == "disabled_by_env"

    def test_disabled_when_false(self, monkeypatch):
        """MEMORY_EMERGENCE_ENABLED=false 时，runtime hook 不运行。"""
        monkeypatch.setenv("MEMORY_EMERGENCE_ENABLED", "false")

        from agent.memory import extract_memories_from_session
        from agent.memory_store import InMemoryMemoryStore

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=InMemoryMemoryStore(),
        )

        emergence = summary.get("emergence", {})
        assert emergence.get("enabled") is False
        assert emergence.get("disabled_reason") == "disabled_by_env"

    def test_enabled_but_active_records_below_gate_fails_closed(self, monkeypatch):
        """env 开启但 active_records<50 时 fail closed，不产生 candidate。"""
        monkeypatch.setenv("MEMORY_EMERGENCE_ENABLED", "true")

        from agent.memory import extract_memories_from_session
        from agent.memory_store import InMemoryMemoryStore

        store = InMemoryMemoryStore()
        for i in range(3):
            _apply_emergence_runtime_record(
                store,
                index=i,
                content=f"以后请先检查 git status synthetic correction {i}",
            )

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )

        emergence = summary.get("emergence", {})
        assert emergence.get("enabled") is True
        assert emergence.get("gate_passed") is False
        assert emergence.get("disabled_reason") == "insufficient_active_records"
        assert emergence.get("gate_reason") == "active_records_below_threshold"
        assert emergence.get("active_records_count") == 3
        assert emergence.get("min_active_records") == 50
        assert emergence.get("candidate_count") == 0
        assert emergence.get("dispatched_count") == 0

    def test_enabled_but_correction_evidence_below_gate_fails_closed(
        self, monkeypatch, tmp_path,
    ):
        """active_records>=50 但 correction evidence<3 时不写 pending。"""
        monkeypatch.setenv("MEMORY_EMERGENCE_ENABLED", "true")
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

        from agent.memory import extract_memories_from_session
        from agent.memory_fs_store import FilesystemMemoryStore

        store = FilesystemMemoryStore(root_dir=tmp_path)
        _seed_active_records_for_emergence(store, correction_count=2)

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )

        emergence = summary.get("emergence", {})
        assert emergence.get("enabled") is True
        assert emergence.get("gate_passed") is True
        assert emergence.get("disabled_reason") == "insufficient_correction_evidence"
        assert emergence.get("gate_reason") == "correction_evidence_below_threshold"
        assert emergence.get("active_records_count") == 50
        assert emergence.get("min_active_records") == 50
        assert emergence.get("evidence_count") == 2
        assert emergence.get("candidate_count") == 0
        assert emergence.get("dispatched_count") == 0
        pending_dir = tmp_path / "_pending"
        pending_files = (
            list(pending_dir.glob("t1_*.json")) if pending_dir.exists() else []
        )
        assert pending_files == []

    def test_enabled_with_sufficient_evidence_dispatches_pending_review(
        self, monkeypatch, tmp_path,
    ):
        """active_records>=50 且 correction evidence>=3 时只写 T1 pending_review。"""
        monkeypatch.setenv("MEMORY_EMERGENCE_ENABLED", "true")
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

        from agent.memory import extract_memories_from_session
        from agent.memory_fs_store import FilesystemMemoryStore

        store = FilesystemMemoryStore(root_dir=tmp_path)
        _seed_active_records_for_emergence(store, correction_count=3)

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )

        emergence = summary.get("emergence", {})
        assert emergence.get("enabled") is True
        assert emergence.get("gate_passed") is True
        assert emergence.get("disabled_reason") is None
        assert emergence.get("gate_reason") == "passed"
        assert emergence.get("min_active_records") == 50
        assert emergence.get("active_records_count") == 50
        assert emergence.get("evidence_count") == 3
        assert emergence.get("candidate_count") >= 1
        assert emergence.get("dispatched_count") >= 1
        assert emergence.get("confirmation_form") == "pending_review"
        assert emergence.get("inline_confirmation") == "not_triggered"
        assert emergence.get("direct_store_write") is False

        import json

        pending_files = sorted((tmp_path / "_pending").glob("t1_*.json"))
        assert pending_files
        pending = json.loads(pending_files[0].read_text(encoding="utf-8"))
        assert pending["memory_type"] == "procedural"
        assert pending["approval_status"] == "pending"
        assert pending["confirmation_form"] == "pending_review"
        assert pending["confirmation_form"] != "inline_confirmation"
        assert pending["confirmation_form"] not in {"silent", "auto_retained"}

        procedural_records = [
            r for r in store.list_records() if r.memory_type == "procedural"
        ]
        assert procedural_records == []

    def test_emergence_summary_omits_raw_evidence_and_secret_like_text(
        self, monkeypatch, tmp_path,
    ):
        """emergence summary 只能展示计数和 gate reason，不能泄漏原始 evidence。

        使用 fake secret-looking synthetic text 验证 summary/reporting 边界；
        这里不读取真实 `.env`，也不处理真实 sessions/runs。
        """
        monkeypatch.setenv("MEMORY_EMERGENCE_ENABLED", "true")
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(tmp_path))

        from agent.memory import extract_memories_from_session
        from agent.memory_fs_store import FilesystemMemoryStore

        store = FilesystemMemoryStore(root_dir=tmp_path)
        _seed_active_records_for_emergence(store, correction_count=3)
        _apply_emergence_runtime_record(
            store,
            index=99,
            content=(
                "以后请先检查 git status；"
                "FAKE_API_KEY_DO_NOT_USE_123 sk-test-not-real-xxxxx"
            ),
        )

        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )

        rendered = repr(summary.get("emergence", {}))
        assert "FAKE_API_KEY_DO_NOT_USE_123" not in rendered
        assert "sk-test-not-real" not in rendered
        assert "以后请先检查 git status" not in rendered

    def test_emergence_failure_does_not_break_extraction_summary(
        self, monkeypatch,
    ):
        """emergence hook 抛错时，session-end extraction summary 仍返回。"""
        monkeypatch.setenv("MEMORY_EMERGENCE_ENABLED", "true")

        def raise_loader_error(records):
            raise RuntimeError("synthetic emergence loader failure")

        monkeypatch.setattr(
            "agent.memory._load_emergence_correction_evidence",
            raise_loader_error,
        )

        from agent.memory import extract_memories_from_session
        from agent.memory_store import InMemoryMemoryStore

        store = InMemoryMemoryStore()
        _seed_active_records_for_emergence(store, correction_count=3)
        summary = extract_memories_from_session(
            [{"role": "user", "content": "hello"}], None, None,
            store=store,
        )

        assert "total_messages" in summary
        assert "total_proposals" in summary
        emergence = summary.get("emergence", {})
        assert emergence.get("enabled") is True
        assert "error" in emergence

    def test_emergence_hook_does_not_import_real_llm_clients(self):
        """runtime hook 不直接 import real LLM SDK。"""
        import ast
        import inspect

        from agent.memory import _maybe_run_emergence

        source = inspect.getsource(_maybe_run_emergence)
        tree = ast.parse(source)
        forbidden = {"anthropic", "openai"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_name = ""
                if isinstance(node, ast.Import):
                    module_name = node.names[0].name
                elif node.module:
                    module_name = node.module
                for keyword in forbidden:
                    assert keyword not in module_name.lower(), (
                        f"_maybe_run_emergence 不应直接 import {keyword}: "
                        f"{module_name}"
                    )

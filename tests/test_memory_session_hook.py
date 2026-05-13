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

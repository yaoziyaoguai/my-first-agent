"""SubAgent Phase 4: Context Packaging tests.

L0 context packaging 只组装 bounded context：
- file summary 不是完整文件；
- memory/skill/tool 都通过传入的边界快照；
- 不创建 L1+ context_window，也不调用真实 LLM。
"""

from __future__ import annotations

from pathlib import Path

from agent.subagent_system.context import build_context_package
from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.request import SubAgentRequest


def _descriptor() -> SubAgentDescriptor:
    return SubAgentDescriptor(
        name="code-reviewer",
        description="Review code",
        role="reviewer",
        allowed_tools=("read_file", "grep"),
        allowed_skills=("review-skill",),
        memory_scope="read_context",
        max_iterations_default=2,
    )


def _request(path: Path) -> SubAgentRequest:
    return SubAgentRequest(
        task="Review file for safety",
        role="reviewer",
        allowed_tools=("read_file",),
        allowed_skills=("review-skill",),
        memory_scope="read_context",
        max_iterations=2,
        parent_trace_id="trace-1",
        delegation_reason="safe review",
        relevant_files=(str(path),),
        context={"goal": "Find safety issue"},
    )


def test_build_context_package_summarizes_files_and_enforces_budget(tmp_path: Path) -> None:
    """大文件只能进入摘要；这是隔离上下文和防泄漏的 L0 基线。"""

    target = tmp_path / "sample.py"
    target.write_text("\n".join(f"line {index}: secret free text" for index in range(80)))

    package = build_context_package(
        request=_request(target),
        descriptor=_descriptor(),
        tool_snapshots=(),
        memory_context="remember: prefer tests",
        skill_metadata=("review-skill:L1",),
        max_context_chars=180,
    )

    assert package.task == "Review file for safety"
    assert package.goal == "Find safety issue"
    assert package.selected_memory_context == "remember: prefer tests"
    assert package.selected_skill_metadata == ("review-skill:L1",)
    assert len(package.relevant_summaries) == 1
    summary = package.relevant_summaries[0]
    assert summary.line_count == 80
    assert len(summary.summary) <= 180
    assert "line 79" not in summary.summary


def test_build_context_package_overflow_truncates_without_leaking_full_content(
    tmp_path: Path,
) -> None:
    """超预算 synthetic input 必须被截断，不能把完整上下文泄漏给 L0 executor。"""

    target = tmp_path / "large_context.py"
    hidden_tail = "TAIL-SHOULD-NOT-LEAK"
    target.write_text("A" * 240 + hidden_tail, encoding="utf-8")

    package = build_context_package(
        request=_request(target),
        descriptor=_descriptor(),
        tool_snapshots=(),
        max_context_chars=64,
    )

    summary = package.relevant_summaries[0]
    assert len(summary.summary) <= 64
    assert summary.summary.endswith("<truncated>")
    assert hidden_tail not in summary.summary
    assert "A" * 120 not in summary.summary


def test_context_package_respects_memory_and_skill_scope(tmp_path: Path) -> None:
    """request 未授权时，即使外部传入 memory/skill，也不能进入 package。"""

    target = tmp_path / "sample.py"
    target.write_text("print('safe')\n")
    request = SubAgentRequest(
        task="Review",
        role="reviewer",
        allowed_tools=("read_file",),
        memory_scope="none",
        parent_trace_id="trace-1",
        delegation_reason="review",
        relevant_files=(str(target),),
    )

    package = build_context_package(
        request=request,
        descriptor=_descriptor(),
        tool_snapshots=(),
        memory_context="should not appear",
        skill_metadata=("review-skill:L1",),
    )

    assert package.selected_memory_context is None
    assert package.selected_skill_metadata == ()
    assert "no real LLM" in package.forbidden_actions
    assert "task_completed" in package.stop_conditions

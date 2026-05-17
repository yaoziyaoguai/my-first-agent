"""SubAgent context contract placeholders for Phase 3.

Phase 4 会补充实际 packaging helper；Phase 3 只提供 frozen dataclass，使
request/result contract 能稳定引用上下文对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.subagent_system.result import FileSummary


@dataclass(frozen=True)
class SubAgentContextPackage:
    """Packaged context passed to bounded SubAgent execution."""

    request: object
    descriptor: object
    task: str
    role_prompt: str
    goal: str
    constraints: tuple[str, ...]
    relevant_files: tuple[str, ...]
    relevant_summaries: tuple[object, ...]
    selected_memory_context: str | None
    selected_skill_metadata: tuple[object, ...]
    allowed_tools: tuple[object, ...]
    allowed_skills: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    output_schema: dict[str, Any] | None
    max_context_chars: int
    max_iterations: int
    stop_conditions: tuple[str, ...]
    execution_mode: str


def build_context_package(
    *,
    request: object,
    descriptor: object,
    tool_snapshots: tuple[object, ...],
    memory_context: str | None = None,
    skill_metadata: tuple[object, ...] = (),
    max_context_chars: int = 100_000,
) -> SubAgentContextPackage:
    """Assemble L0 context package without creating a real LLM context window.

    中文学习边界：这里做的是 parent-controlled packaging，不是执行。文件只被
    摘要化，Memory/Skill/Tool 都是上游 governance 传入的快照。
    """

    task = getattr(request, "task")
    context = getattr(request, "context", {}) or {}
    memory_scope = getattr(request, "memory_scope", "none")
    allowed_skills = tuple(getattr(request, "allowed_skills", ()))
    relevant_files = tuple(getattr(request, "relevant_files", ()))
    summaries = tuple(_summarize_file(path, max_context_chars) for path in relevant_files)
    selected_memory_context = memory_context if memory_scope in {"read_context", "propose"} else None
    selected_skill_metadata = tuple(skill_metadata) if allowed_skills else ()
    return SubAgentContextPackage(
        request=request,
        descriptor=descriptor,
        task=task,
        role_prompt=f"SubAgent role: {getattr(descriptor, 'role', getattr(request, 'role', 'unknown'))}",
        goal=str(context.get("goal") or task),
        constraints=(
            "parent owns orchestration",
            "ToolRegistry remains authority",
            "Memory governance remains authority",
        ),
        relevant_files=relevant_files,
        relevant_summaries=summaries,
        selected_memory_context=selected_memory_context,
        selected_skill_metadata=selected_skill_metadata,
        allowed_tools=tuple(tool_snapshots),
        allowed_skills=allowed_skills,
        forbidden_actions=(
            "no real LLM",
            "no external process",
            "no shell",
            "no repo write",
            "no direct MemoryStore write",
            "no nested SubAgent",
        ),
        output_schema=getattr(request, "output_schema", None),
        max_context_chars=max_context_chars,
        max_iterations=getattr(request, "max_iterations"),
        stop_conditions=(
            "task_completed",
            "max_iterations_exceeded",
            "needs_clarification",
            "needs_confirmation",
            "tool_blocked",
            "policy_blocked",
            "error",
            "interrupted",
        ),
        execution_mode=getattr(request, "execution_mode"),
    )


def _summarize_file(raw_path: str, max_chars: int) -> FileSummary:
    path = Path(raw_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return FileSummary(path=str(path), summary="<unreadable>", line_count=0, language=path.suffix.lstrip("."))
    lines = text.splitlines()
    summary = text[:max_chars]
    if len(text) > max_chars:
        marker = "\n<truncated>"
        summary = text[: max(0, max_chars - len(marker))].rstrip() + marker
    return FileSummary(
        path=str(path),
        summary=summary,
        line_count=len(lines),
        language=path.suffix.lstrip("."),
    )

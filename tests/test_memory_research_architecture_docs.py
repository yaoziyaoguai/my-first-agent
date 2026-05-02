"""Stage 3 Memory research / architecture docs acceptance tests.

这些测试保护的是文档级架构承诺，而不是 Memory production implementation。
Memory 会牵动 prompt、runtime、checkpoint、TUI、MCP、tool_result 和隐私策略；
在写任何长期记忆代码前，必须先把 research source、decision contract、provider
边界和 no-persistence 口径固定下来，避免把 Stage 3 误做成 memory.json +
prompt injection。
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DOC = PROJECT_ROOT / "docs" / "MEMORY_RESEARCH.md"
ARCH_DOC = PROJECT_ROOT / "docs" / "MEMORY_ARCHITECTURE.md"
ROADMAP = PROJECT_ROOT / "docs" / "ROADMAP.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_memory_research_records_primary_sources_and_architecture_takeaways() -> None:
    """Research 文档必须给出来源和取舍，而不是凭印象设计 Memory。

    这条测试要求 MemGPT/Letta、LangGraph、MCP 和 provider/store 模式都被记录；
    同时要求文档明确"采纳什么 / 不采纳什么"，防止后续直接复制外部框架或把
    MCP resources 当成内部 Memory System。
    """

    text = _read(RESEARCH_DOC)

    required_markers = [
        "MemGPT paper",
        "Letta agent memory guide",
        "Letta memory blocks",
        "LangChain/LangGraph memory concepts",
        "MCP resources spec",
        "MCP prompts spec",
        "MCP tools spec",
        "Memory is policy before storage",
        "External context is not internal memory",
        "Do not add SQLite/vector DB/RAG now",
    ]
    for marker in required_markers:
        assert marker in text


def test_memory_architecture_defines_decision_policy_snapshot_provider_boundaries() -> None:
    """Architecture 文档必须把 decision/policy/store/snapshot 分开。

    Memory 的核心不是"把文字存起来"，而是 candidate -> policy -> approval ->
    store/provider -> retrieval -> snapshot -> prompt 的治理链。这个测试防止后续
    把 prompt_builder、runtime state、checkpoint 或 MCP provider 变成 policy owner。
    """

    text = _read(ARCH_DOC)

    required_markers = [
        "MemoryCandidate",
        "MemoryDecision",
        "MemoryPolicy",
        "MemoryApproval",
        "MemoryStore",
        "MemoryProvider",
        "MemorySnapshot",
        "MemoryAudit",
        "prompt_builder",
        "must not decide what to remember",
    ]
    for marker in required_markers:
        assert marker in text


def test_memory_architecture_keeps_checkpoint_compression_tui_and_mcp_boundaries() -> None:
    """Stage 3 不能把长期记忆塞进已有 runtime 边界。

    checkpoint 只负责恢复，context compression 只负责当前会话摘要，TUI 只负责
    展示/确认，MCP resources 只是未来 external provider 输入。这个测试固定这些
    边界，避免 Memory 变成新的跨层巨石。
    """

    text = _read(ARCH_DOC)

    boundary_markers = [
        "Memory vs checkpoint",
        "Memory vs context compression",
        "Memory vs prompt_builder",
        "Memory vs runtime state",
        "Memory vs skills",
        "Memory vs tools",
        "Memory vs MCP",
        "Memory vs TUI",
        "Memory vs storage",
    ]
    for marker in boundary_markers:
        assert marker in text


def test_memory_architecture_records_safety_ux_and_stage3_slices() -> None:
    """Memory Roadmap 必须先保护隐私/UX/forget，再进入实现。

    这条测试要求文档包含用户可读确认文案、安全策略、forget 优先级和 5-8 个
    Stage 3 slices。它保证后续 implementation pack 可以小步推进，而不是一次性
    引入持久化、RAG、外部 provider 和 runtime 大重构。
    """

    text = _read(ARCH_DOC)

    required_markers = [
        "Default deny for sensitive information",
        "User explicit consent is required",
        "forget",
        "仅本次使用",
        "Slice 1: Memory architecture docs + acceptance contracts",
        "Slice 2: MemoryCandidate / MemoryDecision no-side-effect contracts",
        "Slice 3: Deterministic MemoryPolicy no-op / explicit-only retain",
        "Slice 4: MemorySnapshot prompt injection seam",
        "Slice 5: User confirmation UX contract for retain/update/forget",
        "Slice 7: External MemoryProvider adapter seam",
        "Why this is not `memory.json + prompt injection`",
    ]
    for marker in required_markers:
        assert marker in text


def test_roadmap_links_stage3_research_without_claiming_implementation_done() -> None:
    """Roadmap 可以进入 Stage 3 research，但不能宣称长期记忆已实现。

    当前允许的是 docs/tests/planning/readiness。生产持久化、自动 retain、RAG /
    vector provider、MCP resources/prompts implementation 都必须留到后续授权 slice。
    """

    text = _read(ROADMAP)

    required_markers = [
        "MEMORY_RESEARCH.md",
        "MEMORY_ARCHITECTURE.md",
        "Stage 3 Memory System Research & Architecture Discovery",
        "不实现 long-term memory persistence",
        "不自动 retain / update / forget",
        "MemoryDecision / MemoryCandidate",
    ]
    for marker in required_markers:
        assert marker in text


"""Stage 3 Slice 6: external MemoryProvider seam contract tests.

这些测试保护 provider seam：外部 provider 只能提供 MemoryCandidate /
MemorySnapshot 输入，不能变成真实 provider、MCP resources integration、storage、
policy decision、confirmation approval 或 prompt injection。
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent.memory_confirmation import MemoryConfirmationRequest, MemoryConfirmationResult
from agent.memory_contracts import (
    MemoryDecision,
    MemoryScope,
    MemorySensitivity,
    MemorySnapshot,
    MemorySource,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_MODULE = PROJECT_ROOT / "agent" / "memory_provider.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _agent_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def _called_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_fake_provider_returns_deterministic_candidates_without_external_access() -> None:
    """FakeMemoryProvider 只返回确定性测试候选，不访问外部系统。"""

    from agent.memory_provider import FakeMemoryProvider, MemoryProviderCandidate

    provider = FakeMemoryProvider(
        provider_name="fake_docs",
        candidates=(
            MemoryProviderCandidate(
                content="项目偏好：回答先给结论",
                scope=MemoryScope.PROJECT,
                sensitivity=MemorySensitivity.LOW,
                provenance="fixture:preference:1",
                reason="fake provider fixture",
            ),
        ),
    )

    candidates = provider.list_candidates()
    memory_candidates = provider.to_memory_candidates()

    assert candidates == provider.list_candidates()
    assert memory_candidates[0].source is MemorySource.EXTERNAL_PROVIDER
    assert memory_candidates[0].source_event == "provider:fake_docs:fixture:preference:1"
    assert memory_candidates[0].content == "项目偏好：回答先给结论"


def test_provider_output_is_candidate_or_snapshot_input_only() -> None:
    """provider 输出只能进入 candidate/snapshot pipeline，不是 MemoryRecord/store。"""

    from agent.memory_provider import FakeMemoryProvider, MemoryProviderSnapshotItem

    provider = FakeMemoryProvider(
        provider_name="fake_snapshot",
        snapshot_items=(
            MemoryProviderSnapshotItem(
                content="用户偏好简洁回答",
                scope=MemoryScope.USER,
                sensitivity=MemorySensitivity.LOW,
                provenance="fixture:snapshot:1",
                selection_reason="fake snapshot fixture",
            ),
        ),
    )

    snapshot = provider.get_snapshot(selection_reason="fake provider selected")

    assert isinstance(snapshot, MemorySnapshot)
    assert snapshot.items[0].content == "用户偏好简洁回答"
    assert not any(hasattr(snapshot, name) for name in {"write", "save", "persist"})


def test_provider_cannot_bypass_memory_policy_or_confirmation() -> None:
    """provider 不能产出 decision 或 approved confirmation。"""

    from agent.memory_provider import FakeMemoryProvider, MemoryProviderCandidate

    provider = FakeMemoryProvider(
        provider_name="fake_policy_boundary",
        candidates=(
            MemoryProviderCandidate(
                content="候选事实",
                scope=MemoryScope.USER,
                sensitivity=MemorySensitivity.LOW,
                provenance="fixture:candidate:1",
                reason="只作为 policy 输入",
            ),
        ),
    )

    candidate = provider.to_memory_candidates()[0]

    assert not isinstance(candidate, MemoryDecision)
    assert not isinstance(candidate, MemoryConfirmationRequest)
    assert not isinstance(candidate, MemoryConfirmationResult)
    assert not hasattr(candidate, "decision_type")


def test_provider_result_includes_provenance_scope_and_safety() -> None:
    """provider result 必须带来源、scope、safety，方便后续 policy 审计。"""

    from agent.memory_provider import MemoryProviderCandidate

    candidate = MemoryProviderCandidate(
        content="项目偏好：测试优先",
        scope=MemoryScope.PROJECT,
        sensitivity=MemorySensitivity.MEDIUM,
        provenance="fixture:testing:1",
        reason="provider supplied project preference",
    )

    assert candidate.provider_name == ""
    assert candidate.scope is MemoryScope.PROJECT
    assert candidate.sensitivity is MemorySensitivity.MEDIUM
    assert candidate.provenance == "fixture:testing:1"
    assert candidate.reason == "provider supplied project preference"


def test_provider_disabled_fallback_is_empty_and_safe() -> None:
    """没有配置 provider 时应是 no-op fallback。"""

    from agent.memory_provider import FakeMemoryProvider

    provider = FakeMemoryProvider(provider_name="disabled")

    assert provider.list_candidates() == ()
    assert provider.to_memory_candidates() == ()
    assert provider.get_snapshot(selection_reason="disabled").items == ()


def test_memory_provider_module_has_no_mcp_network_store_runtime_or_io_dependency() -> None:
    """provider seam 不能连接真实 MCP/network，也不能依赖 runtime/checkpoint/TUI。"""

    imports = _agent_imports(PROVIDER_MODULE)
    calls = _called_names(PROVIDER_MODULE)

    assert imports <= {"agent.memory_contracts"}
    assert calls.isdisjoint({
        "open",
        "read_text",
        "write_text",
        "mkdir",
        "connect",
        "request",
        "urlopen",
        "save_checkpoint",
        "load_checkpoint",
    })


def test_provider_module_documents_future_mcp_resources_as_seam_only() -> None:
    """MCP resources 只能作为未来 provider input 说明，不能实现真实集成。"""

    source = PROVIDER_MODULE.read_text(encoding="utf-8")

    assert "future MCP resources" in source
    assert "not an MCP client" in source
    assert "StdioMCPClient" not in source

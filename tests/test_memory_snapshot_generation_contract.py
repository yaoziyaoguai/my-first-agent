"""Stage 5: governed fake-store record -> MemorySnapshot generation tests.

这些测试保护 Stage 5 的核心防火墙：store 不能直接喂 prompt_builder，必须先通过
governed snapshot generation，把 fake/local MemoryRecord 按 scope / budget /
safety / provenance 过滤成 MemorySnapshot。这里不实现真实 retrieval、语义检索或
runtime 集成。
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent.memory_contracts import MemoryScope, MemorySensitivity, MemorySnapshot
from agent.memory_operations import MemoryOperationType
from agent.memory_store import InMemoryMemoryStore, MemoryRecord


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_MODULE = PROJECT_ROOT / "agent" / "memory_snapshot_generator.py"
PROMPT_BUILDER = PROJECT_ROOT / "agent" / "prompt_builder.py"


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
    """扫描调用名，确认 generator 没有 IO、网络、LLM、MCP 或写 store 行为。"""

    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _record(
    record_id: str,
    content: str,
    *,
    scope: MemoryScope = MemoryScope.USER,
    source_summary: str | None = None,
    safety_summary: str = "无额外安全标记",
    audit_id: str | None = None,
    sensitive_redacted: bool = False,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        content=content,
        scope=scope,
        source_summary=source_summary or f"candidate:{record_id}",
        safety_summary=safety_summary,
        audit_id=audit_id or f"audit:{record_id}",
        created_by_operation=MemoryOperationType.RETAIN,
        updated_by_operation=MemoryOperationType.RETAIN,
        sensitive_redacted=sensitive_redacted,
    )


def test_builds_snapshot_from_fake_approved_records_with_provenance_scope_and_audit() -> None:
    """fake store records 必须先变成 MemorySnapshot，不能直接变成 prompt 文本。"""

    from agent.memory_snapshot_generator import (
        MemorySnapshotBuildOptions,
        build_memory_snapshot_from_store,
    )

    store = InMemoryMemoryStore(records=(
        _record("rec-a", "用户偏好简洁回答", scope=MemoryScope.USER, audit_id="audit:a"),
        _record("rec-b", "项目使用 pytest", scope=MemoryScope.PROJECT, audit_id="audit:b"),
    ))

    snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(selection_reason="当前任务需要项目和用户偏好"),
    )

    assert isinstance(snapshot, MemorySnapshot)
    assert [item.content for item in snapshot.items] == [
        "用户偏好简洁回答",
        "项目使用 pytest",
    ]
    assert [item.scope for item in snapshot.items] == [MemoryScope.USER, MemoryScope.PROJECT]
    assert all("candidate:" in item.provenance for item in snapshot.items)
    assert all("audit:" in item.selection_reason for item in snapshot.items)
    assert "当前任务需要项目和用户偏好" in snapshot.selection_reason


def test_snapshot_generation_respects_max_items_budget_and_omitted_count() -> None:
    """budget 是 snapshot 防污染边界，不能 dump 全部 fake store。"""

    from agent.memory_snapshot_generator import (
        MemorySnapshotBuildOptions,
        build_memory_snapshot_from_store,
    )

    store = InMemoryMemoryStore(records=(
        _record("rec-a", "第一条"),
        _record("rec-b", "第二条"),
        _record("rec-c", "第三条"),
    ))

    snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(selection_reason="预算测试", max_items=2),
    )

    assert [item.content for item in snapshot.items] == ["第一条", "第二条"]
    assert snapshot.omitted_count == 1
    assert "max_items=2" in snapshot.safety_filter_summary


def test_snapshot_generation_respects_scope_filter() -> None:
    """scope filter 防止把不相关范围的 fake records 注入 snapshot。"""

    from agent.memory_snapshot_generator import (
        MemorySnapshotBuildOptions,
        build_memory_snapshot_from_store,
    )

    store = InMemoryMemoryStore(records=(
        _record("rec-user", "用户偏好", scope=MemoryScope.USER),
        _record("rec-project", "项目约束", scope=MemoryScope.PROJECT),
    ))

    snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(
            selection_reason="只需要项目约束",
            scopes=(MemoryScope.PROJECT,),
        ),
    )

    assert [item.content for item in snapshot.items] == ["项目约束"]
    assert snapshot.omitted_count == 1
    assert "scope_omitted=1" in snapshot.safety_filter_summary


def test_snapshot_generation_omits_sensitive_records_by_default() -> None:
    """敏感 fake record 默认不能静默进入 MemorySnapshot。"""

    from agent.memory_snapshot_generator import (
        MemorySnapshotBuildOptions,
        build_memory_snapshot_from_store,
    )

    store = InMemoryMemoryStore(records=(
        _record("rec-safe", "普通偏好"),
        _record(
            "rec-sensitive",
            "[已隐藏敏感内容]",
            safety_summary="sensitive",
            sensitive_redacted=True,
        ),
    ))

    snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(selection_reason="安全过滤测试"),
    )

    assert [item.content for item in snapshot.items] == ["普通偏好"]
    assert snapshot.omitted_count == 1
    assert "sensitive_omitted=1" in snapshot.safety_filter_summary
    assert all(item.sensitivity is not MemorySensitivity.SECRET for item in snapshot.items)


def test_snapshot_generation_can_include_sensitive_records_only_as_redacted_items() -> None:
    """显式包含敏感 record 时也只能以 redacted snapshot item 出现。"""

    from agent.memory_snapshot_generator import (
        MemorySnapshotBuildOptions,
        build_memory_snapshot_from_store,
    )

    store = InMemoryMemoryStore(records=(
        _record(
            "rec-sensitive",
            "[已隐藏敏感内容]",
            safety_summary="sensitive",
            sensitive_redacted=True,
        ),
    ))

    snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(
            selection_reason="显式敏感过滤测试",
            include_sensitive=True,
        ),
    )

    assert len(snapshot.items) == 1
    assert snapshot.items[0].content == "[已隐藏敏感内容]"
    assert snapshot.items[0].sensitivity is MemorySensitivity.SECRET
    assert "sk-" not in snapshot.items[0].content


def test_snapshot_generation_is_deterministic_for_same_fake_store_input() -> None:
    """同样 fake 输入必须产生稳定 snapshot，方便 dogfooding 和审计。"""

    from agent.memory_snapshot_generator import (
        MemorySnapshotBuildOptions,
        build_memory_snapshot_from_store,
    )

    store = InMemoryMemoryStore(records=(
        _record("rec-b", "第二条"),
        _record("rec-a", "第一条"),
    ))
    options = MemorySnapshotBuildOptions(selection_reason="稳定排序测试")

    first = build_memory_snapshot_from_store(store, options)
    second = build_memory_snapshot_from_store(store, options)

    assert first == second
    assert [item.content for item in first.items] == ["第一条", "第二条"]


def test_snapshot_generator_does_not_write_store_or_apply_operations() -> None:
    """generator 只能读 fake records，不能写 store 或 apply operation intent。"""

    from agent.memory_snapshot_generator import (
        MemorySnapshotBuildOptions,
        build_memory_snapshot_from_store,
    )

    class TrackingStore(InMemoryMemoryStore):
        apply_called = False

        def apply_operation_intent(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.apply_called = True
            return super().apply_operation_intent(*args, **kwargs)

    store = TrackingStore(records=(_record("rec-a", "第一条"),))

    snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(selection_reason="只读测试"),
    )

    assert [item.content for item in snapshot.items] == ["第一条"]
    assert store.apply_called is False
    assert store.list_records() == (_record("rec-a", "第一条"),)


def test_prompt_builder_still_cannot_directly_read_memory_store() -> None:
    """prompt_builder 仍只消费 MemorySnapshot，不读取 store。"""

    assert "agent.memory_store" not in _agent_imports(PROMPT_BUILDER)
    assert "agent.memory_snapshot_generator" not in _agent_imports(PROMPT_BUILDER)


def test_snapshot_generator_module_has_no_runtime_policy_confirmation_io_network_or_mcp_dependency() -> None:
    """generator 是 store-to-snapshot bridge，不是 policy/runtime/provider。"""

    imports = _agent_imports(GENERATOR_MODULE)
    calls = _called_names(GENERATOR_MODULE)

    assert imports <= {"agent.memory_contracts", "agent.memory_store"}
    assert calls.isdisjoint({
        "open",
        "read_text",
        "write_text",
        "mkdir",
        "unlink",
        "glob",
        "iterdir",
        "connect",
        "request",
        "urlopen",
        "save_checkpoint",
        "load_checkpoint",
        "apply_operation_intent",
    })


def test_snapshot_generator_outputs_snapshot_not_prompt_text() -> None:
    """Stage 5 输出 MemorySnapshot，prompt 文本仍交给 prompt_builder 格式化。"""

    from agent.memory_snapshot_generator import (
        MemorySnapshotBuildOptions,
        build_memory_snapshot_from_store,
    )

    snapshot = build_memory_snapshot_from_store(
        InMemoryMemoryStore(records=(_record("rec-a", "第一条"),)),
        MemorySnapshotBuildOptions(selection_reason="输出类型测试"),
    )

    assert isinstance(snapshot, MemorySnapshot)
    assert not isinstance(snapshot, str)

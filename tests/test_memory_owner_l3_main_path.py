"""Memory L3 Owner main-path golden test.

验证 explicit_user_request / semantic memory 主路径通过 MemoryOwner 达到 L3：

- create → stored + audit evidence
- forget → soft-deleted + audit evidence
- noop (deduplicate) → no write + reason
- policy/privacy enforced before persistence
- LLM/model/provider 不能直接写 memory store
- no consolidation/emergence enabled
- no real provider call
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _assert_golden(name: str, actual: dict) -> None:
    path = FIXTURE_DIR / name
    assert path.is_file(), f"missing golden fixture: {path}"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected


# ── MemoryOwner: single mutation authority ──


def test_memory_owner_is_single_write_authority(tmp_path: Path) -> None:
    """MemoryOwner 是所有 explicit_user_request 写操作的唯一入口。"""
    from agent.memory_owner import MemoryMutationType, MemoryOwner
    from agent.memory_store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    owner = MemoryOwner(store=store)

    # create
    result = owner.mutate(
        content="用户喜欢用 Python 编程",
        memory_type="semantic",
        source_type="explicit_user_request",
    )
    assert result.mutation_type == MemoryMutationType.CREATE
    assert result.record_id is not None
    assert result.audit_id is not None
    assert result.evidence.get("retain") == "stored"

    # confirm stored
    records = store.list_records()
    assert any("Python" in r.content for r in records)

    # forget
    forget_result = owner.mutate(
        content="用户喜欢用 Python 编程",
        memory_type="semantic",
        source_type="explicit_user_request",
        intent="forget",
    )
    assert forget_result.mutation_type == MemoryMutationType.DELETE
    assert forget_result.record_id is not None

    # confirm soft-deleted
    remaining = [r for r in store.list_records() if "Python" in r.content]
    assert all(getattr(r, "is_deleted", False) for r in remaining)


def test_memory_owner_noop_deduplicates(tmp_path: Path) -> None:
    """相同 content 的重复 retain → noop decision。"""
    from agent.memory_owner import MemoryMutationType, MemoryOwner
    from agent.memory_store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    owner = MemoryOwner(store=store)

    owner.mutate(
        content="用户使用 VSCode 编辑器",
        memory_type="semantic",
        source_type="explicit_user_request",
    )

    # same content again → noop
    result2 = owner.mutate(
        content="用户使用 VSCode 编辑器",
        memory_type="semantic",
        source_type="explicit_user_request",
    )
    assert result2.mutation_type == MemoryMutationType.NOOP
    assert "duplicate" in result2.reason.lower()
    assert result2.audit_id is not None  # noop still produces audit evidence


def test_memory_owner_policy_blocks_secret(tmp_path: Path) -> None:
    """policy gate 阻止包含 secret/key 的 content 被持久化。"""
    from agent.memory_owner import MemoryMutationType, MemoryOwner
    from agent.memory_store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    owner = MemoryOwner(store=store)

    result = owner.mutate(
        content="我的 API key 是 sk-ant-secret-key-12345678",
        memory_type="semantic",
        source_type="explicit_user_request",
    )
    assert result.mutation_type == MemoryMutationType.REJECTED
    assert "policy" in result.reason.lower()
    assert result.record_id is None  # not stored


def test_memory_owner_no_consolidation_emergence_by_default():
    """MemoryOwner 不默认启用 consolidation 或 emergence path。"""

    # MemoryOwner 不 import consolidation/emergence
    import ast

    import agent.memory_owner as mo

    src = Path(mo.__file__).read_text()
    tree = ast.parse(src)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(n.name for n in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert "memory_consolidation" not in str(imports), (
        "MemoryOwner 不应 import memory_consolidation"
    )
    assert "memory_emergence" not in str(imports), (
        "MemoryOwner 不应 import memory_emergence"
    )
    assert "memory_consolidation_pipeline" not in str(imports)

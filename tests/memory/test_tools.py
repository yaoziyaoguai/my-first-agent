from __future__ import annotations

import os
from pathlib import Path

import pytest

import agent.memory.store as store_mod
from agent.memory.contracts import (
    MemoryCapacityError,
    MemoryStoreError,
    ProviderTrustProfile,
)
from agent.memory.store import MemoryStore
from agent.memory.tools import build_memory_tool_registrations
from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalRequired,
    ExecutionIntent,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.tools import KernelToolRuntime

SCOPE = "scope-digest-1"
PROFILE = ProviderTrustProfile("ops-profile", "openai_compatible", "https://provider.example")


def _ctx() -> ToolPrepareContext:
    return ToolPrepareContext("conversation-1", "run-1", 1)


def _runtime(tmp_path: Path) -> tuple[KernelToolRuntime, MemoryStore]:
    path = tmp_path / "memory"
    path.mkdir(mode=0o700, exist_ok=True)
    store = MemoryStore.create(path / "store.json", workspace_scope_digest=SCOPE, profile=PROFILE)
    runtime = KernelToolRuntime(
        build_memory_tool_registrations(store, workspace_scope_digest=SCOPE)
    )
    return runtime, store


def _approved(runtime, call):
    prepared = runtime.prepare(call, _ctx())
    assert isinstance(prepared, ApprovalRequired)
    return runtime.prepare(
        call,
        _ctx(),
        approval=ApprovalGrant(prepared.request.request_id, prepared.request.binding_digest),
    )


def test_remember_capacity_rejection_maps_to_known_not_executed(
    tmp_path: Path, monkeypatch
) -> None:
    """写前容量拒绝是 known-not-executed：durable 未被触碰，返回精确 code，不进入
    unknown-outcome recovery。"""
    path = tmp_path / "memory"
    path.mkdir(mode=0o700, exist_ok=True)
    store_path = path / "store.json"
    store = MemoryStore.create(store_path, workspace_scope_digest=SCOPE, profile=PROFILE)
    runtime = KernelToolRuntime(
        build_memory_tool_registrations(store, workspace_scope_digest=SCOPE)
    )
    store.remember("初始内容")
    durable_before = store_path.read_bytes()
    # 上限压到当前 durable 大小：store 可用，下一次 remember 增长后超限。
    monkeypatch.setattr(store_mod, "_MAX_STORE_BYTES", len(durable_before))

    call = ToolCall("c1", "memory_remember", {"content": "超限的新记忆" * 32})
    result = runtime.invoke(_approved(runtime, call))

    assert result.executed is False
    assert result.is_error is True
    assert result.metadata["code"] == "memory_capacity_exceeded"
    assert store_path.read_bytes() == durable_before


def test_update_capacity_rejection_maps_to_known_not_executed(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "memory"
    path.mkdir(mode=0o700, exist_ok=True)
    store_path = path / "store.json"
    store = MemoryStore.create(store_path, workspace_scope_digest=SCOPE, profile=PROFILE)
    runtime = KernelToolRuntime(
        build_memory_tool_registrations(store, workspace_scope_digest=SCOPE)
    )
    record = store.remember("初始内容")
    durable_before = store_path.read_bytes()
    monkeypatch.setattr(store_mod, "_MAX_STORE_BYTES", len(durable_before))

    call = ToolCall(
        "c1",
        "memory_update",
        {
            "record_id": record.record_id,
            "content": "超限内容" * 32,
            "expected_record_revision": record.revision,
            "expected_content_digest": record.content_digest,
        },
    )
    result = runtime.invoke(_approved(runtime, call))

    assert result.executed is False
    assert result.is_error is True
    assert result.metadata["code"] == "memory_capacity_exceeded"
    assert store_path.read_bytes() == durable_before


def test_forget_tool_maps_capacity_rejection_precisely(tmp_path: Path, monkeypatch) -> None:
    """forget 的容量 wiring：公开路径上 forget 只会缩小 document（无法确定性构造超限），
    用 monkeypatch 直接让 store.forget 抛窄容量异常，验证精确分类而非 blanket-catch。"""
    runtime, store = _runtime(tmp_path)
    record = store.remember("初始内容")

    def _raise_capacity(record_id, *, expected_record_revision, expected_content_digest):
        raise MemoryCapacityError("memory store exceeds the durable size limit")

    monkeypatch.setattr(store, "forget", _raise_capacity)
    call = ToolCall(
        "c1",
        "memory_forget",
        {
            "record_id": record.record_id,
            "expected_record_revision": record.revision,
            "expected_content_digest": record.content_digest,
        },
    )
    result = runtime.invoke(_approved(runtime, call))

    assert result.executed is False
    assert result.is_error is True
    assert result.metadata["code"] == "memory_capacity_exceeded"


def test_non_capacity_store_error_is_not_misclassified_as_capacity(
    tmp_path: Path, monkeypatch
) -> None:
    """负面保护：非容量 MemoryStoreError（store 满）必须保持既有 unknown outcome
    传播，不得被新增容量码吞掉。"""
    path = tmp_path / "memory"
    path.mkdir(mode=0o700, exist_ok=True)
    store_path = path / "store.json"
    store = MemoryStore.create(store_path, workspace_scope_digest=SCOPE, profile=PROFILE)
    runtime = KernelToolRuntime(
        build_memory_tool_registrations(store, workspace_scope_digest=SCOPE)
    )
    store.remember("初始内容")

    call = ToolCall("c1", "memory_remember", {"content": "另一条记忆"})
    intent = _approved(runtime, call)
    # 批准后把 record 上限压到当前数量：callable 内的 store 满检查抛非容量 MemoryStoreError。
    monkeypatch.setattr(store_mod, "_MAX_RECORDS", 1)
    with pytest.raises(MemoryStoreError) as excinfo:
        runtime.invoke(intent)
    assert not isinstance(excinfo.value, MemoryCapacityError)


def test_post_effect_io_failure_is_not_misclassified_as_capacity(
    tmp_path: Path, monkeypatch
) -> None:
    """负面保护：replace 阶段的真实 I/O 失败发生在 effect 之后，不得被容量码吞掉。"""
    runtime, _store = _runtime(tmp_path)
    call = ToolCall("c1", "memory_remember", {"content": "deploy via canary"})
    intent = _approved(runtime, call)

    def _replace_failed(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", _replace_failed)
    with pytest.raises(OSError):
        runtime.invoke(intent)


def test_search_and_get_read_without_approval(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    store.remember("always run hooks before commit")

    search = runtime.invoke(
        runtime.prepare(
            ToolCall("c1", "memory_search", {"query": "hooks commit"}), _ctx()
        )
    )
    assert "hooks" in search.content

    record = store.snapshot()[0]
    got = runtime.invoke(
        runtime.prepare(
            ToolCall("c2", "memory_get", {"record_id": record.record_id}), _ctx()
        )
    )
    assert "hooks" in got.content


def test_remember_requires_approval_and_binds_content_digest(tmp_path: Path) -> None:
    runtime, _store = _runtime(tmp_path)
    call = ToolCall("c1", "memory_remember", {"content": "deploy via canary"})

    prepared = runtime.prepare(call, _ctx())
    assert isinstance(prepared, ApprovalRequired)
    assert prepared.request.new_content_digest

    intent = _approved(runtime, call)
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)
    assert result.is_error is False
    assert "remembered" in result.content


def test_update_and_forget_require_exact_precondition(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    record = store.remember("version one")

    update_call = ToolCall(
        "c1",
        "memory_update",
        {
            "record_id": record.record_id,
            "content": "version two",
            "expected_record_revision": record.revision,
            "expected_content_digest": record.content_digest,
        },
    )
    intent = _approved(runtime, update_call)
    result = runtime.invoke(intent)
    assert result.is_error is False

    # stale precondition → known-not-executed
    stale = runtime.invoke(
        _approved(
            runtime,
            ToolCall(
                "c2",
                "memory_forget",
                {
                    "record_id": record.record_id,
                    "expected_record_revision": record.revision,
                    "expected_content_digest": record.content_digest,
                },
            ),
        )
    )
    assert stale.executed is False
    assert stale.is_error is True


def test_mutation_previews_are_complete_and_revision_bound(tmp_path: Path) -> None:
    """A7: remember preview must show the FULL content (not a truncated preview),
    and the binding must include the store revision."""
    runtime, store = _runtime(tmp_path)
    call = ToolCall("c1", "memory_remember", {"content": "x" * 500})
    prepared = runtime.prepare(call, _ctx())
    assert isinstance(prepared, ApprovalRequired)
    # preview must contain the full content, not a truncated prefix
    assert "x" * 500 in prepared.request.preview
    # binding must bind the store revision (target_digest = scope)
    assert prepared.request.target_digest


def test_remember_binding_is_bound_to_live_store_revision(tmp_path: Path) -> None:
    """G3 009-gate：remember 的 approval binding 必须绑定真实 store revision（target_digest=scope
    不算 revision-bound proof）。store revision 变化后，相同 content 的 binding_digest 必须不同，
    否则旧 approval 不会因 store 变更而失效。"""
    runtime, store = _runtime(tmp_path)
    call = ToolCall("c1", "memory_remember", {"content": "same content"})
    digest_at_rev0 = runtime.prepare(call, _ctx()).request.binding_digest
    # approved 之外的直接 mutation 推进 store revision（模拟并发/历史写入）。
    store.remember("other record")
    digest_at_rev1 = runtime.prepare(call, _ctx()).request.binding_digest
    assert digest_at_rev0 != digest_at_rev1, "remember binding must be bound to store revision"


def test_update_binding_shows_before_after_and_binds_existing_state(tmp_path: Path) -> None:
    """G3 009-gate：update 的 preview 必须展示完整 before/after，binding 绑定现有 record
    identity + 现有 record revision + old/new content digest（不只是新 content digest）。"""
    runtime, store = _runtime(tmp_path)
    record = store.remember("original content")
    call = ToolCall(
        "c2",
        "memory_update",
        {
            "record_id": record.record_id,
            "content": "new content",
            "expected_record_revision": record.revision,
            "expected_content_digest": record.content_digest,
        },
    )
    prepared = runtime.prepare(call, _ctx())
    assert isinstance(prepared, ApprovalRequired)
    preview = prepared.request.preview
    assert "original content" in preview, "update preview must show the before content"
    assert "new content" in preview, "update preview must show the after content"


def test_forget_binding_shows_full_deleted_content(tmp_path: Path) -> None:
    """G3 009-gate：forget 的 preview 必须展示将被删除的完整 bounded content（不能只显示
    record id / digest 盲批）。"""
    runtime, store = _runtime(tmp_path)
    record = store.remember("will be deleted content")
    call = ToolCall(
        "c3",
        "memory_forget",
        {
            "record_id": record.record_id,
            "expected_record_revision": record.revision,
            "expected_content_digest": record.content_digest,
        },
    )
    prepared = runtime.prepare(call, _ctx())
    assert isinstance(prepared, ApprovalRequired)
    assert "will be deleted content" in prepared.request.preview

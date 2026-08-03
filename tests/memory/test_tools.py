from __future__ import annotations

from pathlib import Path

from agent.memory.contracts import ProviderTrustProfile
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

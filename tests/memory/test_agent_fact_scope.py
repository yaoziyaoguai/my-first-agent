from __future__ import annotations

import pytest

from agent.memory.contracts import ProviderTrustProfile
from agent.memory.store import MemoryStore, MemoryStoreError
from agent.memory.tools import build_memory_tool_registrations
from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalRequired,
    ExecutionIntent,
    FactAdmissionBinding,
    FactAdmissionClass,
    FactKind,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.tools import KernelToolRuntime


def _profile() -> ProviderTrustProfile:
    return ProviderTrustProfile("profile-1", "fake", "local")


def _binding(*, workspace: str = "workspace-a", revision: int = 1):
    return FactAdmissionBinding.create(
        binding_id="fact-binding-1",
        fact_id="fact:user:1",
        fact_kind=FactKind.USER_MESSAGE,
        fact_digest="fact-digest-1",
        workspace_identity_digest=workspace,
        goal_id="goal-1",
        goal_revision=revision,
        admission_class=FactAdmissionClass.WORKSPACE_FACT,
    )


def _context(binding: FactAdmissionBinding | None) -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=4,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="workspace-a",
        fact_admission=binding,
    )


def _runtime(tmp_path):  # noqa: ANN001
    store = MemoryStore.create(
        tmp_path / "memory.json",
        workspace_scope_digest="workspace-a",
        profile=_profile(),
    )
    return KernelToolRuntime(
        build_memory_tool_registrations(store, workspace_scope_digest="workspace-a")
    ), store


def test_workspace_fact_requires_source_reference_and_origin(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    call = ToolCall("call-1", "memory_remember", {"content": "use canary deploys"})
    prepared = runtime.prepare(call, _context(_binding()))
    assert isinstance(prepared, ApprovalRequired)
    intent = runtime.prepare(
        call,
        _context(_binding()),
        ApprovalGrant(prepared.request.request_id, prepared.request.binding_digest),
    )
    assert isinstance(intent, ExecutionIntent)

    runtime.invoke(intent)

    record = store.snapshot()[0]
    assert record.source_fact_id == "fact:user:1"
    assert record.origin == FactKind.USER_MESSAGE.value
    assert record.admission_binding_digest == _binding().binding_digest


def test_unbacked_model_assertion_cannot_become_fact(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    prepared = runtime.prepare(
        ToolCall("call-1", "memory_remember", {"content": "model invented this"}),
        _context(None),
    )

    assert prepared.is_error is True
    assert prepared.executed is False
    assert prepared.metadata["code"] == "fact_admission_required"
    assert store.snapshot() == ()


def test_forged_missing_stale_or_cross_workspace_fact_binding_is_rejected() -> None:
    with pytest.raises(ValueError, match="fact admission is stale"):
        _context(_binding(workspace="workspace-b"))
    with pytest.raises(ValueError, match="fact admission is stale"):
        _context(_binding(revision=2))


def test_workspace_a_fact_is_never_recalled_in_workspace_b(tmp_path) -> None:
    path = tmp_path / "memory.json"
    store = MemoryStore.create(
        path,
        workspace_scope_digest="workspace-a",
        profile=_profile(),
    )
    store.remember("workspace a only", fact_admission=_binding())

    with pytest.raises(MemoryStoreError, match="scope"):
        MemoryStore.load(
            path,
            workspace_scope_digest="workspace-b",
            profile=_profile(),
        )

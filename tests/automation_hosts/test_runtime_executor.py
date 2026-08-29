from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agent.automation.contracts import (
    AutomationRecordV1,
    AutomationSnapshotV1,
    AutomationStatus,
    BackgroundOccurrenceAuthorityV1,
    OccurrenceControlStatus,
)
from agent.automation.supervisor import PreparedOccurrenceV1
from agent.automation.workspace import (
    OwnedObjectKind,
    OwnedObjectV1,
    SourceManifestV1,
)
from agent.automation_hosts.runtime_executor import (
    RepositoryRuntimeOccurrenceResolver,
    RuntimeOccurrenceBindingV1,
    RuntimeOccurrenceExecutor,
)
from agent.composition import build_composition
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    BackgroundOccurrenceBindingV1,
    ConversationWorkspaceBindingV1,
    ModelResponse,
    ModelTextBlock,
    canonical_json_digest,
)
from agent.runtime.loop import InvocationLimits
from agent.scheduler.contracts import ScheduledOccurrence
from tests.automation.test_contracts import _definition
from tests.kernel.fakes import CollectingSink, ScriptedProvider


def _authority() -> BackgroundOccurrenceAuthorityV1:
    return BackgroundOccurrenceAuthorityV1(
        automation_id="automation:one",
        automation_revision=1,
        occurrence_id="occurrence:0000",
        occurrence_index=0,
        scheduled_for_utc="2026-08-28T00:00:00Z",
        definition_digest="1" * 64,
        grant_digest="2" * 64,
        claim_fencing_token="claim-token-one",
        checkpoint_identity="3" * 64,
        deadline_utc="2099-01-01T00:00:00Z",
        raw_capability="raw-capability-" + "4" * 48,
    )


def _objects() -> tuple[OwnedObjectV1, OwnedObjectV1]:
    manifest = SourceManifestV1(
        binding_id="source:one",
        root_identity_digest="5" * 64,
        entries=(),
        total_bytes=0,
    )
    source = OwnedObjectV1(
        object_id="source:one",
        kind=OwnedObjectKind.SOURCE_SNAPSHOT,
        identity_digest="6" * 64,
        size_bytes=0,
        manifest=manifest,
        owner_automation_id="automation:one",
    )
    workspace = OwnedObjectV1(
        object_id="workspace:one",
        kind=OwnedObjectKind.OCCURRENCE_WORKSPACE,
        identity_digest="7" * 64,
        size_bytes=0,
        source_identity_digest=source.identity_digest,
        owner_automation_id="automation:one",
    )
    return source, workspace


def _binding(
    authority: BackgroundOccurrenceAuthorityV1,
) -> RuntimeOccurrenceBindingV1:
    occurrence_binding = BackgroundOccurrenceBindingV1.create(
        automation_id=authority.automation_id,
        automation_revision=authority.automation_revision,
        occurrence_id=authority.occurrence_id,
        occurrence_index=authority.occurrence_index,
        scheduled_for_utc=authority.scheduled_for_utc,
        definition_digest=authority.definition_digest,
        grant_digest=authority.grant_digest,
        claim_authority_digest=authority.authority_digest,
        claim_capability_digest=canonical_json_digest(authority.raw_capability),
        checkpoint_identity_digest=authority.checkpoint_identity,
        deadline_utc=authority.deadline_utc,
        model_call_limit=4,
        tool_call_limit=8,
        sandbox_command_limit=2,
        browser_action_limit=3,
        max_input_tokens=20_000,
        max_output_tokens=4_000,
    )
    workspace_binding = ConversationWorkspaceBindingV1.create(
        workspace_scope_digest="8" * 64,
        workspace_identity_digest="7" * 64,
        bound_at="2026-08-28T00:00:00Z",
    )
    return RuntimeOccurrenceBindingV1(
        scheduled_occurrence=ScheduledOccurrence(
            schedule_id=authority.automation_id,
            occurrence_id=authority.occurrence_id,
            scheduled_for_utc=authority.scheduled_for_utc,
            message="Produce the bounded status.",
            workspace_scope_digest=workspace_binding.workspace_scope_digest,
            background_binding=occurrence_binding,
        ),
        workspace_binding=workspace_binding,
        source_identity_digest="6" * 64,
        workspace_identity_digest="7" * 64,
    )


class _Resolver:
    def __init__(self, authority: BackgroundOccurrenceAuthorityV1) -> None:
        self._authority = authority

    def from_authority(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
    ) -> RuntimeOccurrenceBindingV1:
        assert authority == self._authority
        return _binding(authority)

    def from_prepared(self, prepared) -> RuntimeOccurrenceBindingV1:  # noqa: ANN001
        assert prepared.automation_id == self._authority.automation_id
        assert prepared.raw_capability == self._authority.raw_capability
        return _binding(self._authority)


class _RuntimeResources:
    def __init__(self, runtime, close=lambda: None):  # noqa: ANN001, B008
        self.runtime = runtime
        self._close = close

    def close(self) -> None:
        self._close()


def _executor(
    state_root: Path,
    provider: ScriptedProvider,
) -> RuntimeOccurrenceExecutor:
    authority = _authority()

    def runtime_factory(store, _binding):  # noqa: ANN001, ANN202
        composition = build_composition(
            provider=provider,
            checkpoint_store=store,
            tool_registrations=(),
            event_sink=CollectingSink(),
            system_policy="policy",
            context_limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
            invocation_limits=InvocationLimits(),
        )
        return _RuntimeResources(composition.runtime)

    return RuntimeOccurrenceExecutor(
        state_root=state_root,
        resolver=_Resolver(authority),
        runtime_factory=runtime_factory,
    )


def test_runtime_executor_initializes_before_launch_and_delegates_once(tmp_path) -> None:
    state_root = tmp_path / "runtime"
    state_root.mkdir(mode=0o700)
    authority = _authority()
    source, workspace = _objects()
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("bounded result"),)))
    executor = _executor(state_root, provider)

    prepared = executor.initialize(authority, source, workspace)

    occurrence = _binding(authority).scheduled_occurrence
    assert (state_root / occurrence.checkpoint_relative_path).is_file()
    assert prepared.checkpoint_identity_digest == authority.checkpoint_identity

    result = executor.run_once(prepared)

    assert result.status is OccurrenceControlStatus.COMPLETED
    assert result.checkpoint_identity_digest == authority.checkpoint_identity
    assert result.replayed is False
    assert len(provider.calls) == 1


def test_new_runtime_executor_recovers_terminal_checkpoint_without_duplicate_send(
    tmp_path,
) -> None:
    state_root = tmp_path / "runtime"
    state_root.mkdir(mode=0o700)
    authority = _authority()
    source, workspace = _objects()
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("bounded result"),)))
    first = _executor(state_root, provider)
    prepared = first.initialize(authority, source, workspace)
    first_result = first.run_once(prepared)

    recovered = _executor(state_root, provider).recover(authority)

    assert first_result.status is OccurrenceControlStatus.COMPLETED
    assert recovered is not None
    assert recovered.prepared == prepared
    assert recovered.result is not None
    assert recovered.result.status is OccurrenceControlStatus.COMPLETED
    assert recovered.result.replayed is True
    assert len(provider.calls) == 1


def test_runtime_executor_closes_an_occurrence_runtime_after_the_single_turn(
    tmp_path,
) -> None:
    state_root = tmp_path / "runtime"
    state_root.mkdir(mode=0o700)
    authority = _authority()
    source, workspace = _objects()
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("bounded result"),)))
    closed: list[bool] = []

    def runtime_factory(store, _binding):  # noqa: ANN001, ANN202
        runtime = build_composition(
            provider=provider,
            checkpoint_store=store,
            tool_registrations=(),
            event_sink=CollectingSink(),
            system_policy="policy",
            context_limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
            invocation_limits=InvocationLimits(),
        ).runtime

        return _RuntimeResources(runtime, lambda: closed.append(True))

    executor = RuntimeOccurrenceExecutor(
        state_root=state_root,
        resolver=_Resolver(authority),
        runtime_factory=runtime_factory,
    )
    prepared = executor.initialize(authority, source, workspace)

    result = executor.run_once(prepared)

    assert result.status is OccurrenceControlStatus.COMPLETED
    assert closed == [True]


def test_runtime_executor_reports_cleanup_unknown_when_occurrence_close_fails(
    tmp_path,
) -> None:
    state_root = tmp_path / "runtime"
    state_root.mkdir(mode=0o700)
    authority = _authority()
    source, workspace = _objects()
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("bounded result"),)))

    def runtime_factory(store, _binding):  # noqa: ANN001, ANN202
        runtime = build_composition(
            provider=provider,
            checkpoint_store=store,
            tool_registrations=(),
            event_sink=CollectingSink(),
            system_policy="policy",
            context_limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
            invocation_limits=InvocationLimits(),
        ).runtime

        def close() -> None:
            raise RuntimeError("private cleanup detail")

        return _RuntimeResources(runtime, close)

    executor = RuntimeOccurrenceExecutor(
        state_root=state_root,
        resolver=_Resolver(authority),
        runtime_factory=runtime_factory,
    )
    prepared = executor.initialize(authority, source, workspace)

    result = executor.run_once(prepared)

    assert result.status is OccurrenceControlStatus.CLEANUP_UNKNOWN
    assert result.error_code == "runtime_resource_cleanup_unknown"
    assert "private cleanup detail" not in repr(result)


def test_repository_resolver_rebuilds_the_exact_private_runtime_binding() -> None:
    source, workspace = _objects()
    definition = _definition(source_snapshot_digest=source.identity_digest)
    authority = BackgroundOccurrenceAuthorityV1(
        automation_id=definition.body.automation_id,
        automation_revision=definition.body.revision,
        occurrence_id="occurrence:0000",
        occurrence_index=0,
        scheduled_for_utc="2026-08-28T00:00:00Z",
        definition_digest=definition.definition_digest,
        grant_digest=definition.grant.grant_digest,
        claim_fencing_token="claim-token-one",
        checkpoint_identity="c" * 64,
        deadline_utc="2026-08-28T00:10:00Z",
        raw_capability="opaque-capability-" + "4" * 48,
    )
    source = replace(source, owner_automation_id=authority.automation_id)
    workspace = replace(workspace, owner_automation_id=authority.automation_id)
    snapshot = AutomationSnapshotV1(
        revision=3,
        snapshot_token="snapshot-token-0003",
        records=(
            AutomationRecordV1(
                definition=definition,
                status=AutomationStatus.ACTIVE,
                next_occurrence_index=1,
                terminal_occurrence_count=0,
                needs_human_reason=None,
                active_claim=authority,
                active_claim_phase=OccurrenceControlStatus.RUNNING,
                active_claim_definition=definition,
                active_process_identity_digest="d" * 64,
                terminal_history=(),
            ),
        ),
        tombstones=(),
    )

    class _Repository:
        def load(self):  # noqa: ANN201
            return snapshot

    class _Workspaces:
        def load_source_snapshot(self, identity, *, owner_automation_id):  # noqa: ANN001, ANN201
            assert identity == source.identity_digest
            assert owner_automation_id == authority.automation_id
            return source

        def load_occurrence_workspace(self, actual_source, occurrence_id):  # noqa: ANN001, ANN201
            assert actual_source == source
            assert occurrence_id == authority.occurrence_id
            return workspace

    resolver = RepositoryRuntimeOccurrenceResolver(
        repository=_Repository(),
        workspace_repository=_Workspaces(),
    )

    binding = resolver.from_authority(authority)

    occurrence = binding.scheduled_occurrence
    runtime = occurrence.background_binding
    assert runtime is not None
    assert occurrence.message == definition.body.task_text
    assert occurrence.workspace_scope_digest == binding.workspace_binding.workspace_scope_digest
    assert binding.workspace_binding.workspace_identity_digest == workspace.identity_digest
    assert binding.source_identity_digest == source.identity_digest
    assert binding.workspace_identity_digest == workspace.identity_digest
    assert runtime.claim_authority_digest == authority.authority_digest
    assert runtime.claim_capability_digest == canonical_json_digest(authority.raw_capability)
    assert runtime.sandbox_command_limit == definition.body.budgets.sandbox_commands
    assert runtime.browser_action_limit == definition.body.budgets.browser_actions


def test_repository_resolver_rejects_prepared_binding_after_active_claim_drift() -> None:
    class _Repository:
        def load(self):  # noqa: ANN201
            return AutomationSnapshotV1(
                revision=0,
                snapshot_token="snapshot-token-0000",
                records=(),
                tombstones=(),
            )

    class _Workspaces:
        def load_source_snapshot(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
            raise AssertionError("missing active claim must stop before workspace resolution")

        def load_occurrence_workspace(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
            raise AssertionError("missing active claim must stop before workspace resolution")

    resolver = RepositoryRuntimeOccurrenceResolver(
        repository=_Repository(),
        workspace_repository=_Workspaces(),
    )

    with pytest.raises(ValueError, match="active occurrence"):
        resolver.from_prepared(_prepared_runtime_binding())


def _prepared_runtime_binding():  # noqa: ANN202
    return PreparedOccurrenceV1.create(
        automation_id="automation:nightly-report",
        occurrence_id="occurrence:0000",
        authority_digest="1" * 64,
        checkpoint_identity_digest="2" * 64,
        source_identity_digest="3" * 64,
        workspace_identity_digest="4" * 64,
        deadline_utc="2099-01-01T00:00:00Z",
        raw_capability="raw-capability-" + "5" * 48,
    )

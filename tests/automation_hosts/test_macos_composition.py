from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import agent.composition as composition_module
from agent.automation.contracts import (
    AutomationRecordV1,
    AutomationSnapshotV1,
    AutomationStatus,
    BackgroundOccurrenceAuthorityV1,
    OccurrenceControlStatus,
)
from agent.automation.workspace import (
    OwnedObjectKind,
    OwnedObjectV1,
    SourceManifestV1,
)
from agent.automation_hosts.macos_profile import (
    BACKGROUND_TOOL_NAMES,
    BackgroundSeatbeltPolicyV1,
    MacOSAutomationHostProfile,
    MacOSHostCompositionError,
    MacOSHostProfileConfigV1,
    MacOSOccurrenceSpecV1,
)
from agent.automation_hosts.macos_runtime import MacOSOccurrenceRuntimeFactory
from agent.automation_hosts.runtime_executor import RuntimeOccurrenceBindingV1
from agent.composition import browser_identity_digest_for_state_root
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    BackgroundOccurrenceBindingV1,
    ConversationState,
    ConversationWorkspaceBindingV1,
    ProviderDescriptor,
    canonical_json_digest,
)
from agent.runtime.loop import InvocationLimits
from agent.sandbox.contracts import (
    SandboxBackendIdentityV1,
    SandboxQualificationV1,
)
from agent.scheduler.contracts import ScheduledOccurrence
from tests.automation.test_contracts import _definition
from tests.browser.fakes import FakeResolver, Journal, make_fake_factory
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
)


class _ClaimVerifier:
    def verify(self, _check):  # noqa: ANN001, ANN201
        raise AssertionError("composition must not verify a claim before ToolRuntime prepare")


class _Confiner:
    def __init__(self, qualification: SandboxQualificationV1) -> None:
        self._qualification = qualification

    def qualify(self) -> SandboxQualificationV1:
        return self._qualification

    def confine(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        raise AssertionError("composition must not execute sandbox commands")


def _descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        family="openai_compatible",
        model="bounded-model",
        canonical_destination="https://provider.example/v1/chat/completions",
        trust_profile="remote-https-v1",
        remote=True,
    )


def _sandbox_qualification() -> SandboxQualificationV1:
    return SandboxQualificationV1(
        available=True,
        reason_code="qualified",
        backend_identity=SandboxBackendIdentityV1(
            executable_path="/usr/bin/sandbox-exec",
            platform_system="Darwin",
            platform_release="24.5.0",
            functional_probe_digest="1" * 64,
            probe_profile_digest="2" * 64,
        ),
    )


def _fixture(tmp_path, monkeypatch):  # noqa: ANN001, ANN202
    workspace = tmp_path / "workspace"
    temp_root = tmp_path / "temp"
    home_root = tmp_path / "home"
    state_root = tmp_path / "state"
    for path in (workspace, temp_root, home_root, state_root):
        path.mkdir(mode=0o700)
    policy = BackgroundSeatbeltPolicyV1.create(
        workspace_root=workspace,
        temp_root=temp_root,
        home_root=home_root,
        runtime_read_roots=(tmp_path,),
        executable_literals=(Path("/usr/bin/true"),),
    )
    descriptor = _descriptor()
    browser_identity = browser_identity_digest_for_state_root(state_root)
    browser_policy = "7" * 64
    trust_profile = canonical_json_digest(descriptor.trust_profile)
    config = MacOSHostProfileConfigV1.create(
        supervisor_identity_digest="3" * 64,
        sandbox_backend_identity_digest=(
            _sandbox_qualification().backend_identity.backend_identity_digest
        ),
        background_policy_digest=policy.template_digest,
        browser_identity_digest=browser_identity,
        browser_origin_policy_digest=browser_policy,
        provider_descriptor_digest=descriptor.identity_digest,
        trust_profile_digest=trust_profile,
        credential_environment_name="MODEL_API_KEY",
        provider_disclosure_request_digest="4" * 64,
    )
    definition = _definition(
        provider_descriptor_digest=descriptor.identity_digest,
        trust_profile_digest=trust_profile,
        credential_environment_name="MODEL_API_KEY",
        background_environment_policy_digest=policy.template_digest,
        browser_origin_policy_digest=browser_policy,
    )
    authority = BackgroundOccurrenceAuthorityV1(
        automation_id=definition.body.automation_id,
        automation_revision=definition.body.revision,
        occurrence_id="occurrence:0000",
        occurrence_index=0,
        scheduled_for_utc="2026-08-28T00:00:00Z",
        definition_digest=definition.definition_digest,
        grant_digest=definition.grant.grant_digest,
        claim_fencing_token="claim-token-0000",
        checkpoint_identity="c" * 64,
        deadline_utc="2026-08-28T00:10:00Z",
        raw_capability="opaque-capability-" + "4" * 48,
    )
    budgets = definition.body.budgets
    background_binding = BackgroundOccurrenceBindingV1.create(
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
        model_call_limit=budgets.model_calls,
        tool_call_limit=budgets.tool_calls,
        sandbox_command_limit=budgets.sandbox_commands,
        browser_action_limit=budgets.browser_actions,
        max_input_tokens=budgets.max_input_tokens,
        max_output_tokens=budgets.max_output_tokens,
    )
    workspace_binding = ConversationWorkspaceBindingV1.create(
        workspace_scope_digest="8" * 64,
        workspace_identity_digest="9" * 64,
        bound_at="2026-08-28T00:00:00Z",
    )
    runtime_binding = RuntimeOccurrenceBindingV1(
        scheduled_occurrence=ScheduledOccurrence(
            schedule_id=definition.body.automation_id,
            occurrence_id=authority.occurrence_id,
            scheduled_for_utc=authority.scheduled_for_utc,
            message=definition.body.task_text,
            workspace_scope_digest=workspace_binding.workspace_scope_digest,
            background_binding=background_binding,
        ),
        workspace_binding=workspace_binding,
        source_identity_digest="a" * 64,
        workspace_identity_digest=workspace_binding.workspace_identity_digest,
    )
    checkpoint_store = InMemoryCheckpointStore(
        ConversationState.new(
            "conversation:background-host",
            workspace_binding=workspace_binding,
            background_occurrence_binding=background_binding,
        )
    )
    journal = Journal()
    _handle, browser_factory = make_fake_factory(journal)
    monkeypatch.setattr(
        composition_module,
        "_browser_binary_available_for_factory",
        lambda: True,
    )
    credentials: list[str | None] = []
    provider = ScriptedProvider()

    def provider_factory(credential):  # noqa: ANN001, ANN202
        credentials.append(credential)
        return provider

    profile = MacOSAutomationHostProfile(
        config=config,
        platform_system="Darwin",
        supervisor_identity_digest=config.supervisor_identity_digest,
        sandbox_qualification=_sandbox_qualification(),
        browser_identity_digest=browser_identity,
        provider_descriptor=descriptor,
        credential_lookup=lambda name: (
            "opaque-credential" if name == "MODEL_API_KEY" else None
        ),
        provider_factory=provider_factory,
        background_claim_verifier=_ClaimVerifier(),
        sandbox_confiner=_Confiner(_sandbox_qualification()),
        browser_resolver=FakeResolver(),
        playwright_factory=browser_factory,
    )
    spec = MacOSOccurrenceSpecV1(
        definition=definition,
        authority=authority,
        runtime_binding=runtime_binding,
        workspace_root=workspace,
        state_root=state_root,
        sandbox_policy=policy,
        checkpoint_store=checkpoint_store,
        event_sink=CollectingSink(),
        system_policy="bounded background policy",
        context_limits=ContextLimits(
            max_input_tokens=budgets.max_input_tokens,
            output_reserve=budgets.max_output_tokens,
        ),
        invocation_limits=InvocationLimits(
            max_model_calls=budgets.model_calls,
            max_tool_calls=budgets.tool_calls,
        ),
        captured_path="/usr/bin:/bin",
    )
    return profile, spec, credentials


def test_exact_profile_builds_one_existing_runtime_with_only_background_tools(
    tmp_path,
    monkeypatch,
) -> None:
    profile, spec, credentials = _fixture(tmp_path, monkeypatch)

    occurrence = profile.build_occurrence(spec)

    assert profile.composition_calls == 1
    assert credentials == ["opaque-credential"]
    assert frozenset(
        definition.name for definition in occurrence.composition.tool_runtime.definitions()
    ) == BACKGROUND_TOOL_NAMES
    assert occurrence.qualification_identity_digest == profile.qualify(
        spec.definition
    ).qualification_identity_digest
    assert "opaque-credential" not in repr(occurrence)
    occurrence.close()


def test_definition_drift_stops_before_provider_browser_or_runtime_composition(
    tmp_path,
    monkeypatch,
) -> None:
    profile, spec, credentials = _fixture(tmp_path, monkeypatch)
    drifted_body = replace(
        spec.definition.body,
        background_environment_policy_digest="f" * 64,
        definition_body_digest="",
    )
    drifted = type(spec.definition).create_from_body(
        drifted_body,
        activation_preview_digest="9" * 64,
        sandbox_confined=True,
        browser_public_observe=True,
    )

    with pytest.raises(MacOSHostCompositionError) as raised:
        profile.build_occurrence(replace(spec, definition=drifted))

    assert raised.value.reason_code == "sandbox_policy_identity_drift"
    assert credentials == []
    assert profile.composition_calls == 0


def test_distinct_source_object_identity_builds_after_manifest_resolution(
    tmp_path,
    monkeypatch,
) -> None:
    profile, spec, credentials = _fixture(tmp_path, monkeypatch)

    occurrence = profile.build_occurrence(spec)

    assert spec.runtime_binding.source_identity_digest != (
        spec.definition.body.source_snapshot_digest
    )
    assert credentials == ["opaque-credential"]
    occurrence.close()


def test_repository_runtime_factory_builds_the_active_claim_revision_after_cutover(
    tmp_path,
    monkeypatch,
) -> None:
    profile, spec, _credentials = _fixture(tmp_path, monkeypatch)
    source = OwnedObjectV1(
        object_id="source:factory",
        kind=OwnedObjectKind.SOURCE_SNAPSHOT,
        identity_digest=spec.runtime_binding.source_identity_digest,
        size_bytes=0,
        manifest=SourceManifestV1(
            binding_id="source:factory",
            root_identity_digest="a" * 64,
            entries=(),
            total_bytes=0,
        ),
        owner_automation_id=spec.authority.automation_id,
    )
    workspace = OwnedObjectV1(
        object_id="workspace:factory",
        kind=OwnedObjectKind.OCCURRENCE_WORKSPACE,
        identity_digest=spec.runtime_binding.workspace_identity_digest,
        size_bytes=0,
        source_identity_digest=source.identity_digest,
        owner_automation_id=spec.authority.automation_id,
    )
    record = AutomationRecordV1(
        definition=_definition(revision=2, task_text="Build the revised report."),
        status=AutomationStatus.ACTIVE,
        next_occurrence_index=1,
        terminal_occurrence_count=0,
        needs_human_reason=None,
        active_claim=spec.authority,
        active_claim_phase=OccurrenceControlStatus.RUNNING,
        active_claim_definition=spec.definition,
        active_process_identity_digest="d" * 64,
        terminal_history=(),
    )

    class _Repository:
        def load(self):  # noqa: ANN201
            return AutomationSnapshotV1(
                revision=2,
                snapshot_token="snapshot-token-0002",
                records=(record,),
                tombstones=(),
            )

    class _Workspaces:
        def load_source_snapshot(self, digest, *, owner_automation_id):  # noqa: ANN001, ANN201
            assert digest == spec.definition.body.source_snapshot_digest
            assert owner_automation_id == spec.authority.automation_id
            return source

        def load_occurrence_workspace(self, actual, occurrence_id):  # noqa: ANN001, ANN201
            assert actual == source
            assert occurrence_id == spec.authority.occurrence_id
            return workspace

        def resolve_owned_path(self, actual):  # noqa: ANN001, ANN201
            assert actual == workspace
            return spec.workspace_root

    job_state_root = tmp_path / "host-jobs"
    job_state_root.mkdir(mode=0o700)
    factory = MacOSOccurrenceRuntimeFactory(
        profile=profile,
        repository=_Repository(),
        workspace_repository=_Workspaces(),
        job_state_root=job_state_root,
        browser_state_root=spec.state_root,
        runtime_read_roots=(tmp_path,),
        executable_literals=(Path("/usr/bin/true"),),
        event_sink_factory=CollectingSink,
        system_policy=spec.system_policy,
        captured_path=spec.captured_path,
    )

    runtime = factory(spec.checkpoint_store, spec.runtime_binding)

    assert callable(runtime.runtime.run_turn)
    assert not hasattr(runtime, "run_turn")
    assert callable(runtime.close)
    assert profile.composition_calls == 1
    assert sorted(path.name for path in job_state_root.iterdir())
    runtime.close()

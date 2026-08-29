"""Trusted construction of one existing Runtime for a macOS occurrence child."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent.automation.contracts import AutomationDefinitionV1, BackgroundOccurrenceAuthorityV1
from agent.automation.store import AutomationRepository
from agent.automation.workspace import OwnedWorkspaceRepository
from agent.automation_hosts._posix_fs import ensure_owner_directory
from agent.automation_hosts.macos_profile import (
    BackgroundSeatbeltPolicyV1,
    MacOSAutomationHostProfile,
    MacOSHostCompositionError,
    MacOSOccurrenceSpecV1,
    OccurrenceCompositionV1,
)
from agent.automation_hosts.runtime_executor import RuntimeOccurrenceBindingV1
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import canonical_json_digest
from agent.runtime.loop import InvocationLimits
from agent.runtime.ports import CheckpointStore, EventSink


class MacOSOccurrenceRuntimeFactory:
    """Resolve durable private inputs and build the sole existing Runtime."""

    def __init__(
        self,
        *,
        profile: MacOSAutomationHostProfile,
        repository: AutomationRepository,
        workspace_repository: OwnedWorkspaceRepository,
        job_state_root: Path,
        browser_state_root: Path,
        runtime_read_roots: tuple[Path, ...],
        executable_literals: tuple[Path, ...],
        event_sink_factory: Callable[[], EventSink],
        system_policy: str,
        captured_path: str,
    ) -> None:
        if not isinstance(profile, MacOSAutomationHostProfile):
            raise TypeError("profile must use MacOSAutomationHostProfile")
        if not callable(getattr(repository, "load", None)):
            raise TypeError("repository must provide load")
        if not all(
            callable(getattr(workspace_repository, name, None))
            for name in (
                "load_source_snapshot",
                "load_occurrence_workspace",
                "resolve_owned_path",
            )
        ):
            raise TypeError("workspace_repository must resolve exact owned workspaces")
        if not callable(event_sink_factory):
            raise TypeError("event_sink_factory must be callable")
        if not isinstance(system_policy, str) or not system_policy.strip():
            raise ValueError("system_policy must be bounded non-empty text")
        if not isinstance(captured_path, str):
            raise TypeError("captured_path must be a string")
        for root in (job_state_root, browser_state_root):
            ensure_owner_directory(root)
        self._profile = profile
        self._repository = repository
        self._workspace_repository = workspace_repository
        self._job_state_root = job_state_root
        self._browser_state_root = browser_state_root
        self._runtime_read_roots = runtime_read_roots
        self._executable_literals = executable_literals
        self._event_sink_factory = event_sink_factory
        self._system_policy = system_policy
        self._captured_path = captured_path

    def __call__(
        self,
        checkpoint_store: CheckpointStore,
        binding: RuntimeOccurrenceBindingV1,
    ) -> OccurrenceCompositionV1:
        if not isinstance(binding, RuntimeOccurrenceBindingV1):
            raise TypeError("binding must use RuntimeOccurrenceBindingV1")
        occurrence = binding.scheduled_occurrence
        record = next(
            (
                item
                for item in self._repository.load().records
                if item.automation_id == occurrence.schedule_id
            ),
            None,
        )
        authority = None if record is None else record.active_claim
        definition = None if record is None else record.active_claim_definition
        if not isinstance(authority, BackgroundOccurrenceAuthorityV1) or not isinstance(
            definition, AutomationDefinitionV1
        ):
            raise MacOSHostCompositionError("occurrence_binding_drift")
        if (
            authority.occurrence_id != occurrence.occurrence_id
            or authority.definition_digest != definition.definition_digest
        ):
            raise MacOSHostCompositionError("occurrence_binding_drift")

        source = self._workspace_repository.load_source_snapshot(
            definition.body.source_snapshot_digest,
            owner_automation_id=authority.automation_id,
        )
        workspace = self._workspace_repository.load_occurrence_workspace(
            source,
            authority.occurrence_id,
        )
        if (
            source.identity_digest != binding.source_identity_digest
            or workspace.identity_digest != binding.workspace_identity_digest
        ):
            raise MacOSHostCompositionError("occurrence_binding_drift")
        workspace_root = self._workspace_repository.resolve_owned_path(workspace)
        job_key = canonical_json_digest(
            {
                "automation_id": authority.automation_id,
                "occurrence_id": authority.occurrence_id,
                "workspace_identity_digest": binding.workspace_identity_digest,
            }
        )
        job_root = self._job_state_root / job_key
        temp_root = job_root / "temp"
        home_root = job_root / "home"
        for root in (job_root, temp_root, home_root):
            ensure_owner_directory(root)
        policy = BackgroundSeatbeltPolicyV1.create(
            workspace_root=workspace_root,
            temp_root=temp_root,
            home_root=home_root,
            runtime_read_roots=self._runtime_read_roots,
            executable_literals=self._executable_literals,
        )
        if (
            policy.template_digest
            != definition.body.background_environment_policy_digest
        ):
            raise MacOSHostCompositionError("sandbox_policy_identity_drift")
        budgets = definition.body.budgets
        return self._profile.build_occurrence(
            MacOSOccurrenceSpecV1(
                definition=definition,
                authority=authority,
                runtime_binding=binding,
                workspace_root=workspace_root,
                state_root=self._browser_state_root,
                sandbox_policy=policy,
                checkpoint_store=checkpoint_store,
                event_sink=self._event_sink_factory(),
                system_policy=self._system_policy,
                context_limits=ContextLimits(
                    max_input_tokens=budgets.max_input_tokens,
                    output_reserve=budgets.max_output_tokens,
                ),
                invocation_limits=InvocationLimits(
                    max_model_calls=budgets.model_calls,
                    max_tool_calls=budgets.tool_calls,
                    max_input_tokens=budgets.max_input_tokens,
                    max_output_tokens=budgets.max_output_tokens,
                ),
                captured_path=self._captured_path,
            )
        )


__all__ = ["MacOSOccurrenceRuntimeFactory"]

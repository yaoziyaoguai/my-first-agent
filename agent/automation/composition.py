"""Static, platform-neutral composition for the 019 control core."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from agent.automation.claim_verifier import AutomationClaimVerifier
from agent.automation.controller import AutomationController
from agent.automation.management import (
    ActivationQualificationsV1,
    AutomationManagementService,
)
from agent.automation.reconcile import (
    AutomationReconciler,
    ExecutionAvailabilityV1,
    ReconcileAutomationsResultV1,
    ReconcileAutomationsV1,
)
from agent.automation.store import AutomationRepository
from agent.automation.supervisor import (
    OccurrenceExecutionResultV1,
    OccurrenceExecutor,
    OccurrenceSupervisor,
    PreparedOccurrenceV1,
    RecoveredOccurrenceV1,
)
from agent.automation.wake import (
    WakeAdapter,
    WakeInstallOutcome,
    WakeInstallResultV1,
    WakeReadbackOutcome,
    WakeReadbackV1,
    WakeRemoveOutcome,
    WakeRemoveResultV1,
)
from agent.automation.workspace import (
    OwnedObjectV1,
    OwnedWorkspaceRepository,
    SourceBindingV1,
    WorkspaceBoundsV1,
)
from agent.runtime.contracts import canonical_json_digest

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AutomationControlConfigV1:
    source_bindings: tuple[tuple[str, SourceBindingV1], ...]
    workspace_bounds: WorkspaceBoundsV1
    qualification_identity_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_bounds, WorkspaceBoundsV1):
            raise ValueError("workspace_bounds must use WorkspaceBoundsV1")
        if not _HEX64.fullmatch(self.qualification_identity_digest):
            raise ValueError("qualification_identity_digest must be bare hex64")
        if (
            not isinstance(self.source_bindings, tuple)
            or any(
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not _HEX64.fullmatch(item[0])
                or not isinstance(item[1], SourceBindingV1)
                for item in self.source_bindings
            )
        ):
            raise ValueError("source_bindings must be exact digest/binding pairs")
        digests = tuple(item[0] for item in self.source_bindings)
        if digests != tuple(sorted(set(digests))):
            raise ValueError("source_bindings must be sorted with unique digests")


@dataclass(frozen=True, slots=True)
class AutomationControlCoreV1:
    management: AutomationManagementService
    controller: AutomationController
    reconciler: AutomationReconciler
    claim_verifier: AutomationClaimVerifier

    def reconcile(
        self,
        request: ReconcileAutomationsV1,
    ) -> ReconcileAutomationsResultV1:
        return self.reconciler.reconcile(request)


class _LazyOccurrenceExecutor:
    def __init__(self, factory: Callable[[], OccurrenceExecutor]) -> None:
        self._factory = factory
        self._instance: OccurrenceExecutor | None = None

    def _get(self) -> OccurrenceExecutor:
        if self._instance is None:
            instance = self._factory()
            if not all(
                callable(getattr(instance, name, None))
                for name in ("initialize", "run_once", "recover")
            ):
                raise TypeError("provider_factory must return an OccurrenceExecutor")
            self._instance = instance
        return self._instance

    def initialize(
        self,
        authority,
        source: OwnedObjectV1,
        workspace: OwnedObjectV1,
    ) -> PreparedOccurrenceV1:
        return self._get().initialize(authority, source, workspace)

    def run_once(self, prepared: PreparedOccurrenceV1) -> OccurrenceExecutionResultV1:
        return self._get().run_once(prepared)

    def recover(self, authority) -> RecoveredOccurrenceV1 | None:  # noqa: ANN001
        return self._get().recover(authority)


class _UnavailableWakeAdapter:
    @property
    def configured_policy_digest(self) -> str:
        return "0" * 64

    def readback(self, policy_digest: str) -> WakeReadbackV1:
        return WakeReadbackV1(
            outcome=WakeReadbackOutcome.UNKNOWN,
            requested_policy_digest=policy_digest,
            installed_policy_digest=None,
            adapter_projection_digest=None,
        )

    def install(self, policy_digest: str) -> WakeInstallResultV1:
        return WakeInstallResultV1(
            outcome=WakeInstallOutcome.UNKNOWN,
            requested_policy_digest=policy_digest,
            adapter_projection_digest=None,
        )

    def remove(self, policy_digest: str) -> WakeRemoveResultV1:
        return WakeRemoveResultV1(
            outcome=WakeRemoveOutcome.UNKNOWN,
            requested_policy_digest=policy_digest,
            adapter_projection_digest=None,
        )


def build_automation_control_core(
    config: AutomationControlConfigV1,
    *,
    repository: AutomationRepository,
    workspace_repository: OwnedWorkspaceRepository,
    clock,
    supervisor: OccurrenceSupervisor | None,
    provider_factory: Callable[[], OccurrenceExecutor] | None,
    sandbox_capability: object | None,
    browser_capability: object | None,
    wake_adapter: WakeAdapter | None,
    next_snapshot_token: Callable[[], str],
    claim_fencing_token: Callable[[], str],
    raw_capability: Callable[[], str],
    checkpoint_identity: Callable[[], str],
) -> AutomationControlCoreV1:
    if not isinstance(config, AutomationControlConfigV1):
        raise TypeError("config must use AutomationControlConfigV1")
    source_bindings = dict(config.source_bindings)
    controller = AutomationController(repository)
    claim_verifier = AutomationClaimVerifier(repository)
    availability = ExecutionAvailabilityV1(
        provider_available=provider_factory is not None,
        supervisor_available=supervisor is not None,
        sandbox_available=sandbox_capability is not None,
        browser_available=browser_capability is not None,
    )
    qualification_digest = canonical_json_digest(
        {
            "identity": config.qualification_identity_digest,
            "provider": availability.provider_available,
            "supervisor": availability.supervisor_available,
            "sandbox": availability.sandbox_available,
            "browser": availability.browser_available,
            "wake": wake_adapter is not None,
        }
    )
    management = AutomationManagementService(
        controller=controller,
        workspace_repository=workspace_repository,
        wake_adapter=wake_adapter or _UnavailableWakeAdapter(),
        source_bindings=source_bindings,
        workspace_bounds=config.workspace_bounds,
        qualifications=ActivationQualificationsV1(
            provider_ready=availability.provider_available,
            sandbox_qualified=availability.sandbox_available,
            browser_qualified=availability.browser_available,
            wake_qualified=wake_adapter is not None,
            qualification_digest=qualification_digest,
        ),
    )
    executor = None if provider_factory is None else _LazyOccurrenceExecutor(provider_factory)
    reconciler = AutomationReconciler(
        controller=controller,
        workspace_repository=workspace_repository,
        source_bindings=source_bindings,
        workspace_bounds=config.workspace_bounds,
        executor=executor,
        supervisor=supervisor,
        clock=clock,
        next_snapshot_token=next_snapshot_token,
        claim_fencing_token=claim_fencing_token,
        raw_capability=raw_capability,
        checkpoint_identity=checkpoint_identity,
        execution_availability=availability,
    )
    return AutomationControlCoreV1(
        management=management,
        controller=controller,
        reconciler=reconciler,
        claim_verifier=claim_verifier,
    )

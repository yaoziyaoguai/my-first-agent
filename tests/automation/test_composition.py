from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent.automation.composition import (
    AutomationControlConfigV1,
    build_automation_control_core,
)
from agent.automation.contracts import OccurrenceControlStatus
from agent.automation.management import ActivationUnavailableError
from agent.automation.reconcile import ReconcileAutomationsV1
from agent.automation.supervisor import (
    DeterministicOccurrenceExecutor,
    DeterministicOccurrenceSupervisor,
    OccurrenceExecutionResultV1,
)
from agent.automation.wake import DeterministicWakeAdapter
from agent.automation.workspace import SourceBindingV1, WorkspaceBoundsV1

from .test_management import _service
from .test_reconcile import _token_factory


def _active_core(
    *,
    now: datetime,
    provider: bool = True,
    supervisor: bool = True,
    sandbox: bool = True,
    browser: bool = True,
    wake: bool = True,
):
    service, repository, workspace, body = _service()
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    preview = service.preview(body.automation_id)
    service.approve(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0001",
        next_snapshot_token="snapshot-token-0002",
    )
    executor = DeterministicOccurrenceExecutor(
        result=OccurrenceExecutionResultV1(
            status=OccurrenceControlStatus.COMPLETED,
            checkpoint_identity_digest="c" * 64,
            result_digest="d" * 64,
            replayed=False,
            error_code=None,
            artifacts=(),
        )
    )
    factory_calls: list[str] = []

    def provider_factory():
        factory_calls.append("provider")
        return executor

    binding = SourceBindingV1(
        binding_id="source:workspace",
        root_identity_digest="1" * 64,
        excluded_components=("private", "runtime"),
    )
    core = build_automation_control_core(
        AutomationControlConfigV1(
            source_bindings=((body.source_workspace_binding_digest, binding),),
            workspace_bounds=WorkspaceBoundsV1(),
            qualification_identity_digest="a" * 64,
        ),
        repository=repository,
        workspace_repository=workspace,
        clock=lambda: now,
        supervisor=(
            DeterministicOccurrenceSupervisor(process_identity_digest="e" * 64)
            if supervisor
            else None
        ),
        provider_factory=provider_factory if provider else None,
        sandbox_capability=object() if sandbox else None,
        browser_capability=object() if browser else None,
        wake_adapter=DeterministicWakeAdapter() if wake else None,
        next_snapshot_token=_token_factory(3),
        claim_fencing_token=lambda: "claim-token-019",
        raw_capability=lambda: "opaque-capability-019-000000000000000000000000",
        checkpoint_identity=lambda: "c" * 64,
    )
    return core, repository, executor, factory_calls


def test_not_due_returns_before_missing_host_capabilities_or_provider_factory() -> None:
    core, repository, executor, factory_calls = _active_core(
        now=datetime(2026, 8, 27, tzinfo=UTC),
        provider=False,
        supervisor=False,
        sandbox=False,
        browser=False,
    )
    before = repository.load()

    result = core.reconcile(ReconcileAutomationsV1())

    assert result.code == "not_due"
    assert repository.load() == before
    assert executor.initialize_calls == 0
    assert factory_calls == []


@pytest.mark.parametrize(
    ("missing", "reason"),
    [
        ("provider", "provider_unavailable"),
        ("supervisor", "supervisor_unavailable"),
        ("sandbox", "sandbox_unavailable"),
        ("browser", "browser_unavailable"),
    ],
)
def test_due_missing_host_capability_returns_one_closed_config_result(
    missing: str,
    reason: str,
) -> None:
    core, repository, executor, factory_calls = _active_core(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
        provider=missing != "provider",
        supervisor=missing != "supervisor",
        sandbox=missing != "sandbox",
        browser=missing != "browser",
    )
    before = repository.load()

    result = core.reconcile(ReconcileAutomationsV1(delivery_id="delivery:one"))

    assert result.code == "needs_019_config"
    assert result.reason == reason
    assert repository.load() == before
    assert executor.initialize_calls == 0
    assert factory_calls == []


def test_complete_static_core_lazily_builds_one_executor_for_one_due_occurrence() -> None:
    core, repository, executor, factory_calls = _active_core(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
    )

    result = core.reconcile(ReconcileAutomationsV1())

    assert result.code == "completed"
    assert repository.load().records[0].terminal_occurrence_count == 1
    assert executor.run_calls == 1
    assert factory_calls == ["provider"]
    assert not hasattr(core, "tool_registrations")


def test_manual_reconcile_remains_available_without_a_cold_wake_adapter() -> None:
    core, repository, executor, factory_calls = _active_core(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
        wake=False,
    )

    with pytest.raises(ActivationUnavailableError, match="wake qualification"):
        core.management.preview(repository.load().records[0].automation_id)

    result = core.reconcile(ReconcileAutomationsV1())

    assert result.code == "completed"
    assert executor.run_calls == 1
    assert factory_calls == ["provider"]

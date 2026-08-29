from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from agent.automation.contracts import OccurrenceControlStatus
from agent.automation.controller import AutomationController
from agent.automation.reconcile import (
    AutomationReconciler,
    ReconcileAutomationsV1,
)
from agent.automation.supervisor import (
    DeterministicOccurrenceExecutor,
    DeterministicOccurrenceSupervisor,
    OccurrenceExecutionResultV1,
)
from agent.automation.workspace import SourceBindingV1, WorkspaceBoundsV1

from .test_management import _service


def _active_fixture(
    *,
    now: datetime,
    executor_factory=None,  # noqa: ANN001
    supervisor_factory=None,  # noqa: ANN001
    factory_calls: dict[str, int] | None = None,
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
    result = OccurrenceExecutionResultV1(
        status=OccurrenceControlStatus.COMPLETED,
        checkpoint_identity_digest="c" * 64,
        result_digest="d" * 64,
        replayed=False,
        error_code=None,
        artifacts=(),
    )
    executor = (
        DeterministicOccurrenceExecutor(result=result)
        if executor_factory is None
        else executor_factory(result, repository, workspace)
    )
    supervisor = (
        DeterministicOccurrenceSupervisor(process_identity_digest="e" * 64)
        if supervisor_factory is None
        else supervisor_factory(repository)
    )
    binding = SourceBindingV1(
        binding_id="source:workspace",
        root_identity_digest="1" * 64,
        excluded_components=("private", "runtime"),
    )
    calls = factory_calls if factory_calls is not None else {}

    def counted(name: str, value: str):
        def factory() -> str:
            calls[name] = calls.get(name, 0) + 1
            return value

        return factory

    reconciler = AutomationReconciler(
        controller=AutomationController(repository),
        workspace_repository=workspace,
        source_bindings={body.source_workspace_binding_digest: binding},
        workspace_bounds=WorkspaceBoundsV1(),
        executor=executor,
        supervisor=supervisor,
        clock=lambda: now,
        next_snapshot_token=_token_factory(3),
        claim_fencing_token=counted("claim", "claim-token-019"),
        raw_capability=counted(
            "capability",
            "opaque-capability-019-000000000000000000000000",
        ),
        checkpoint_identity=counted("checkpoint", "c" * 64),
    )
    return reconciler, repository, executor, supervisor


def _token_factory(start: int):
    current = start

    def next_token() -> str:
        nonlocal current
        value = f"snapshot-token-{current:04d}"
        current += 1
        return value

    return next_token


def test_not_due_returns_before_workspace_executor_or_supervisor() -> None:
    factory_calls: dict[str, int] = {}
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 27, tzinfo=UTC),
        factory_calls=factory_calls,
    )
    before = repository.load()

    result = reconciler.reconcile(ReconcileAutomationsV1())

    assert result.code == "not_due"
    assert repository.load() == before
    assert executor.initialize_calls == 0
    assert executor.run_calls == 0
    assert supervisor.run_calls == 0
    assert factory_calls == {}


def test_misfire_terminalizes_without_execution_capability_or_workspace() -> None:
    factory_calls: dict[str, int] = {}
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 6, tzinfo=UTC),
        factory_calls=factory_calls,
    )

    result = reconciler.reconcile(ReconcileAutomationsV1())

    record = repository.load().records[0]
    assert result.code == "misfire_skipped"
    assert record.terminal_history[-1].status is OccurrenceControlStatus.MISFIRE_SKIPPED
    assert executor.initialize_calls == 0
    assert executor.run_calls == 0
    assert supervisor.run_calls == 0
    assert factory_calls == {"claim": 1}


def test_due_occurrence_crosses_ready_barrier_and_terminalizes_once() -> None:
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
    )

    result = reconciler.reconcile(ReconcileAutomationsV1(delivery_id="delivery:one"))

    record = repository.load().records[0]
    assert result.code == "completed"
    assert executor.initialize_calls == 1
    assert executor.run_calls == 1
    assert supervisor.run_calls == 1
    assert record.active_claim is None
    assert record.terminal_history[-1].status is OccurrenceControlStatus.COMPLETED


def test_one_reconcile_selects_only_the_earliest_scheduled_then_automation_id() -> None:
    service, repository, workspace, body = _service()
    earlier_id = "automation:aaa-report"
    later_body = replace(
        body,
        automation_id=earlier_id,
        label="Earlier lexical id",
        definition_body_digest="",
    )
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    first_preview = service.preview(body.automation_id)
    service.approve(
        body.automation_id,
        preview_digest=first_preview.preview_digest,
        expected_snapshot_token="snapshot-token-0001",
        next_snapshot_token="snapshot-token-0002",
    )
    service.create(
        later_body,
        expected_snapshot_token="snapshot-token-0002",
        next_snapshot_token="snapshot-token-0003",
    )
    second_preview = service.preview(earlier_id)
    service.approve(
        earlier_id,
        preview_digest=second_preview.preview_digest,
        expected_snapshot_token="snapshot-token-0003",
        next_snapshot_token="snapshot-token-0004",
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
    supervisor = DeterministicOccurrenceSupervisor(process_identity_digest="e" * 64)
    binding = SourceBindingV1(
        binding_id="source:workspace",
        root_identity_digest="1" * 64,
        excluded_components=("private", "runtime"),
    )
    reconciler = AutomationReconciler(
        controller=AutomationController(repository),
        workspace_repository=workspace,
        source_bindings={body.source_workspace_binding_digest: binding},
        workspace_bounds=WorkspaceBoundsV1(),
        executor=executor,
        supervisor=supervisor,
        clock=lambda: datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
        next_snapshot_token=_token_factory(5),
        claim_fencing_token=lambda: "claim-token-019",
        raw_capability=lambda: "opaque-capability-019-000000000000000000000000",
        checkpoint_identity=lambda: "c" * 64,
    )

    result = reconciler.reconcile(ReconcileAutomationsV1())

    records = {record.automation_id: record for record in repository.load().records}
    assert result.automation_id == earlier_id
    assert records[earlier_id].terminal_occurrence_count == 1
    assert records[body.automation_id].terminal_occurrence_count == 0
    assert executor.run_calls == 1
    assert supervisor.run_calls == 1

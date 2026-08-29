from __future__ import annotations

from datetime import UTC, datetime

from agent.automation.contracts import OccurrenceControlStatus
from agent.automation.reconcile import ReconcileAutomationsV1
from agent.automation.supervisor import (
    DeterministicOccurrenceExecutor,
    OccurrenceExecutionResultV1,
)

from .test_reconcile import _active_fixture


def test_worker_deadline_is_a_bounded_terminal_result_not_success() -> None:
    def executor_factory(result, repository, workspace):  # noqa: ANN001, ARG001, ANN202
        return DeterministicOccurrenceExecutor(
            result=OccurrenceExecutionResultV1(
                status=OccurrenceControlStatus.WORKER_DEADLINE,
                checkpoint_identity_digest=result.checkpoint_identity_digest,
                result_digest=None,
                replayed=False,
                error_code="worker_deadline",
                artifacts=(),
            )
        )

    reconciler, repository, executor, _ = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
        executor_factory=executor_factory,
    )

    result = reconciler.reconcile(ReconcileAutomationsV1())

    record = repository.load().records[0]
    assert result.status is OccurrenceControlStatus.WORKER_DEADLINE
    assert record.active_claim is None
    assert record.terminal_history[-1].status is OccurrenceControlStatus.WORKER_DEADLINE
    assert record.terminal_history[-1].error_code == "worker_deadline"
    assert executor.run_calls == 1

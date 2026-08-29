from __future__ import annotations

import json
from datetime import UTC, datetime

from agent.automation.cli import run_cli
from agent.automation.contracts import BackgroundOccurrenceAuthorityV1, ClaimOccurrence
from agent.automation.controller import AutomationController
from agent.automation.schedule import occurrence_identity
from agent.automation.wake import DeterministicWakeAdapter
from tests.automation.test_composition import _active_core
from tests.automation.test_management import _service


def test_wake_enable_and_disable_use_the_adapter_bound_policy_without_cli_input() -> None:
    core, _, _, _ = _active_core(now=datetime(2026, 8, 27, tzinfo=UTC))
    output: list[str] = []

    assert run_cli(["wake", "enable"], core=core, write_fn=output.append) == 0
    assert json.loads(output.pop()) == {
        "code": "wake_enabled",
        "policy_digest": "8" * 64,
    }
    assert run_cli(["wake", "disable"], core=core, write_fn=output.append) == 0
    assert json.loads(output.pop()) == {
        "code": "wake_disabled",
        "manual_reconcile_required": True,
        "policy_digest": "8" * 64,
    }


def test_deterministic_disable_refuses_while_worker_running() -> None:
    adapter = DeterministicWakeAdapter(worker_running=lambda: True)
    assert adapter.install(adapter.configured_policy_digest).outcome.value == "installed"
    assert adapter.remove(adapter.configured_policy_digest).outcome.value == "busy"


def test_portable_wake_adapter_never_accepts_an_unbound_policy_digest() -> None:
    adapter = DeterministicWakeAdapter(policy_digest="8" * 64)

    assert adapter.readback("9" * 64).outcome.value == "drift"
    assert adapter.install("9" * 64).outcome.value == "unknown"
    assert adapter.remove("9" * 64).outcome.value == "unknown"


def test_portable_management_refuses_disable_while_an_occurrence_is_active() -> None:
    wake = DeterministicWakeAdapter()
    service, repository, _, body = _service(wake_adapter=wake)
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
    definition = repository.load().records[0].definition
    assert definition is not None
    authority = BackgroundOccurrenceAuthorityV1(
        automation_id=body.automation_id,
        automation_revision=body.revision,
        occurrence_id=occurrence_identity(definition, 0, body.schedule.anchor_utc),
        occurrence_index=0,
        scheduled_for_utc=body.schedule.anchor_utc,
        definition_digest=definition.definition_digest,
        grant_digest=definition.grant.grant_digest,
        claim_fencing_token="claim-token-wake",
        checkpoint_identity="c" * 64,
        deadline_utc="2026-08-28T00:10:00Z",
        raw_capability="opaque-wake-capability-00000000000000000000000",
    )
    AutomationController(repository).handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            authority=authority,
        )
    )

    result = service.wake_disable()

    assert result.code == "wake_disable_refused_active"
    assert wake.remove_count == 0

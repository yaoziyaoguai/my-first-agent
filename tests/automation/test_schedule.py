from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from agent.automation.contracts import (
    AutomationRecordV1,
    AutomationScheduleV1,
    AutomationStatus,
    CatchUpRule,
    ScheduleDecisionKind,
    ScheduleKind,
)
from agent.automation.schedule import occurrence_identity, resolve_schedule

from .test_contracts import _definition


def _utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _record(**overrides: object) -> AutomationRecordV1:
    values: dict[str, object] = {
        "definition": _definition(),
        "status": AutomationStatus.ACTIVE,
        "next_occurrence_index": 0,
        "terminal_occurrence_count": 0,
        "needs_human_reason": None,
        "active_claim": None,
        "terminal_history": (),
    }
    values.update(overrides)
    return AutomationRecordV1(**values)


def test_latest_one_skips_superseded_slots_and_claims_one() -> None:
    record = _record()

    decision = resolve_schedule(record.definition, record, _utc("2026-08-28T03:00:00Z"))

    assert decision.kind is ScheduleDecisionKind.DUE
    assert decision.occurrence_index == 3
    assert decision.scheduled_for_utc == "2026-08-28T03:00:00Z"
    assert decision.superseded_indexes == (0, 1, 2)


def test_none_never_jumps_over_one_late_slot() -> None:
    definition = _definition()
    schedule = replace(
        definition.body.schedule,
        catch_up=CatchUpRule.NONE,
        schedule_digest="",
    )
    body = replace(definition.body, schedule=schedule, definition_body_digest="")
    definition = type(definition).create_from_body(
        body,
        activation_preview_digest="9" * 64,
        sandbox_confined=True,
        browser_public_observe=True,
    )
    record = _record(definition=definition)

    decision = resolve_schedule(definition, record, _utc("2026-08-28T03:00:00Z"))

    assert decision.kind is ScheduleDecisionKind.MISFIRE_SKIPPED
    assert decision.occurrence_index == 0
    assert decision.superseded_indexes == ()


def test_paused_and_needs_human_records_never_become_due() -> None:
    paused = _record(status=AutomationStatus.PAUSED)
    needs_human = _record(
        status=AutomationStatus.PAUSED,
        needs_human_reason="model_outcome_unknown",
    )

    assert resolve_schedule(
        paused.definition, paused, _utc("2026-08-28T00:00:00Z")
    ).kind is ScheduleDecisionKind.PAUSED
    assert resolve_schedule(
        needs_human.definition,
        needs_human,
        _utc("2026-08-28T00:00:00Z"),
    ).kind is ScheduleDecisionKind.NEEDS_HUMAN


def test_max_occurrences_and_expiry_are_terminal_schedule_decisions() -> None:
    maxed = _record(next_occurrence_index=30, terminal_occurrence_count=30)
    expired = _record()

    assert resolve_schedule(
        maxed.definition, maxed, _utc("2026-08-28T00:00:00Z")
    ).kind is ScheduleDecisionKind.MAX_REACHED
    assert resolve_schedule(
        expired.definition, expired, _utc("2026-09-28T00:00:01Z")
    ).kind is ScheduleDecisionKind.EXPIRED


def test_occurrence_identity_binds_revision_slot_time_and_definition() -> None:
    definition = _definition()
    original = occurrence_identity(definition, 3, "2026-08-28T03:00:00Z")

    assert original == occurrence_identity(definition, 3, "2026-08-28T03:00:00Z")
    assert original != occurrence_identity(definition, 4, "2026-08-28T04:00:00Z")
    assert original != occurrence_identity(
        _definition(task_text="different"), 3, "2026-08-28T03:00:00Z"
    )


def test_once_schedule_is_due_at_most_once() -> None:
    definition = _definition()
    once = AutomationScheduleV1(
        kind=ScheduleKind.ONCE_UTC,
        anchor_utc="2026-08-28T00:00:00Z",
        interval_seconds=None,
        catch_up=CatchUpRule.NONE,
        misfire_grace_seconds=300,
    )
    body = replace(
        definition.body,
        schedule=once,
        max_occurrences=1,
        definition_body_digest="",
    )
    definition = type(definition).create_from_body(
        body,
        activation_preview_digest="9" * 64,
        sandbox_confined=True,
        browser_public_observe=True,
    )

    due = resolve_schedule(definition, _record(definition=definition), _utc("2026-08-28T00:00:00Z"))
    maxed = resolve_schedule(
        definition,
        _record(
            definition=definition,
            next_occurrence_index=1,
            terminal_occurrence_count=1,
        ),
        _utc("2026-08-28T00:01:00Z"),
    )

    assert due.kind is ScheduleDecisionKind.DUE
    assert maxed.kind is ScheduleDecisionKind.MAX_REACHED

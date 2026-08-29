"""019 schedule resolver：纯 UTC 计算，不读取 clock/store/adapter。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent.automation.contracts import (
    AutomationDefinitionV1,
    AutomationRecordV1,
    AutomationStatus,
    CatchUpRule,
    ScheduleDecisionKind,
    ScheduleDecisionV1,
    ScheduleKind,
    format_canonical_utc,
    parse_canonical_utc,
)
from agent.runtime.contracts import canonical_json_digest


def occurrence_identity(
    definition: AutomationDefinitionV1,
    occurrence_index: int,
    scheduled_for_utc: str,
) -> str:
    if isinstance(occurrence_index, bool) or not isinstance(occurrence_index, int):
        raise ValueError("occurrence_index must be an int")
    if not 0 <= occurrence_index < definition.body.max_occurrences:
        raise ValueError("occurrence_index is outside the definition bound")
    parse_canonical_utc(scheduled_for_utc, "scheduled_for_utc")
    return canonical_json_digest(
        {
            "automation_id": definition.body.automation_id,
            "revision": definition.body.revision,
            "occurrence_index": occurrence_index,
            "scheduled_for_utc": scheduled_for_utc,
            "definition_digest": definition.definition_digest,
        }
    )


def resolve_schedule(
    definition: AutomationDefinitionV1,
    record: AutomationRecordV1,
    now_utc: datetime,
) -> ScheduleDecisionV1:
    if record.definition is None or (
        record.definition.definition_digest != definition.definition_digest
    ):
        raise ValueError("record and definition identity mismatch")
    now = _require_utc_datetime(now_utc)
    if record.needs_human_reason is not None:
        return ScheduleDecisionV1(ScheduleDecisionKind.NEEDS_HUMAN)
    if record.status is AutomationStatus.PAUSED:
        return ScheduleDecisionV1(ScheduleDecisionKind.PAUSED)
    if record.status is AutomationStatus.CANCEL_PENDING:
        return ScheduleDecisionV1(ScheduleDecisionKind.CANCEL_PENDING)
    if record.status in {AutomationStatus.CANCELED, AutomationStatus.PURGED}:
        return ScheduleDecisionV1(ScheduleDecisionKind.CANCELED)
    if record.status is not AutomationStatus.ACTIVE or record.active_claim is not None:
        return ScheduleDecisionV1(ScheduleDecisionKind.NOT_DUE)
    if record.next_occurrence_index >= definition.body.max_occurrences:
        return ScheduleDecisionV1(ScheduleDecisionKind.MAX_REACHED)
    expires = parse_canonical_utc(definition.body.expires_at_utc, "expires_at_utc")
    if now > expires:
        return ScheduleDecisionV1(ScheduleDecisionKind.EXPIRED)

    schedule = definition.body.schedule
    anchor = parse_canonical_utc(schedule.anchor_utc, "anchor_utc")
    if schedule.kind is ScheduleKind.ONCE_UTC:
        return _decision_for_slot(
            index=0,
            scheduled=anchor,
            now=now,
            grace_seconds=schedule.misfire_grace_seconds,
            superseded=(),
        )

    assert schedule.interval_seconds is not None
    cursor = record.next_occurrence_index
    next_slot = anchor + timedelta(seconds=cursor * schedule.interval_seconds)
    if now < next_slot:
        return ScheduleDecisionV1(ScheduleDecisionKind.NOT_DUE)
    if schedule.catch_up is CatchUpRule.NONE:
        return _decision_for_slot(
            index=cursor,
            scheduled=next_slot,
            now=now,
            grace_seconds=schedule.misfire_grace_seconds,
            superseded=(),
        )

    elapsed_seconds = int((now - anchor).total_seconds())
    latest_index = elapsed_seconds // schedule.interval_seconds
    latest_index = min(latest_index, definition.body.max_occurrences - 1)
    latest_slot = anchor + timedelta(seconds=latest_index * schedule.interval_seconds)
    superseded = tuple(range(cursor, latest_index))
    return _decision_for_slot(
        index=latest_index,
        scheduled=latest_slot,
        now=now,
        grace_seconds=schedule.misfire_grace_seconds,
        superseded=superseded,
    )


def _decision_for_slot(
    *,
    index: int,
    scheduled: datetime,
    now: datetime,
    grace_seconds: int,
    superseded: tuple[int, ...],
) -> ScheduleDecisionV1:
    if now < scheduled:
        return ScheduleDecisionV1(ScheduleDecisionKind.NOT_DUE)
    kind = (
        ScheduleDecisionKind.DUE
        if now <= scheduled + timedelta(seconds=grace_seconds)
        else ScheduleDecisionKind.MISFIRE_SKIPPED
    )
    return ScheduleDecisionV1(
        kind=kind,
        occurrence_index=index,
        scheduled_for_utc=format_canonical_utc(scheduled),
        superseded_indexes=superseded,
    )


def _require_utc_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware UTC")
    normalized = value.astimezone(UTC)
    if normalized.utcoffset() != timedelta(0) or normalized.microsecond:
        raise ValueError("now_utc must use whole-second UTC")
    return normalized

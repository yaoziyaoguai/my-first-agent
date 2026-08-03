from __future__ import annotations

import pytest

from agent.runtime.contracts import RunStatus
from agent.scheduler.contracts import ScheduledOccurrence, SchedulerError, occurrence_exit_class

SCOPE = "workspace-scope-digest"


def _occurrence(**overrides) -> ScheduledOccurrence:
    base = {
        "schedule_id": "nightly-build",
        "occurrence_id": "2026-07-19T00:00:00Z",
        "scheduled_for_utc": "2026-07-19T00:00:00Z",
        "message": "run the benign nightly check",
        "workspace_scope_digest": SCOPE,
    }
    base.update(overrides)
    return ScheduledOccurrence(**base)


def test_checkpoint_path_only_depends_on_schedule_and_occurrence_ids() -> None:
    a = _occurrence(message="one")
    b = _occurrence(message="two", scheduled_for_utc="2026-07-20T00:00:00Z")
    assert a.checkpoint_relative_path == b.checkpoint_relative_path


def test_conversation_identity_binds_full_occurrence() -> None:
    a = _occurrence()
    drifted = _occurrence(message="different message")
    assert a.conversation_id != drifted.conversation_id
    assert a.run_id != drifted.run_id


def test_invalid_ids_and_time_fail_closed() -> None:
    with pytest.raises(SchedulerError):
        _occurrence(schedule_id="../escape")
    with pytest.raises(SchedulerError):
        _occurrence(scheduled_for_utc="2026-07-19 00:00:00")  # not canonical UTC
    with pytest.raises(SchedulerError):
        _occurrence(message="   ")


def test_exit_class_mapping() -> None:
    assert occurrence_exit_class(RunStatus.COMPLETED) == "completed"
    assert occurrence_exit_class(RunStatus.AWAITING_APPROVAL) == "needs_human"
    assert occurrence_exit_class(RunStatus.LIMIT_REACHED) == "needs_human"
    assert occurrence_exit_class(RunStatus.FAILED_FATAL) == "fatal_conflict"
    assert occurrence_exit_class(RunStatus.CONFLICT) == "fatal_conflict"


def test_impossible_utc_dates_are_rejected() -> None:
    """F8/R17: UTC identity must be calendar-valid, not just regex-shaped."""
    import pytest

    from agent.scheduler.contracts import SchedulerError

    for impossible in (
        "2026-99-99T00:00:00Z",  # impossible month/day
        "2026-13-01T00:00:00Z",  # month 13
        "2026-02-30T00:00:00Z",  # Feb 30
        "2026-02-29T00:00:00Z",  # Feb 29 on non-leap year 2026
        "2026-01-01T25:00:00Z",  # hour 25
        "2026-01-01T00:60:00Z",  # minute 60
        "2026-01-01T00:00:61Z",  # second 61
    ):
        with pytest.raises(SchedulerError, match="calendar"):
            ScheduledOccurrence(
                schedule_id="test",
                occurrence_id="test",
                scheduled_for_utc=impossible,
                message="test message",
                workspace_scope_digest=SCOPE,
            )


def test_fractional_seconds_offsets_and_non_canonical_forms_are_rejected() -> None:
    """G5 009-gate：canonical UTC round-trip 只接受整秒 ``...Z``。未批准的 fractional form、
    时区 offset 与其它非 canonical 写法必须拒绝（不能只靠 regex 后再 calendar-parse 通过）。"""
    for rejected in (
        "2026-07-19T00:00:00.5Z",  # fractional seconds（未批准 fractional form）
        "2026-07-19T00:00:00.123456Z",  # microsecond fractional
        "2026-07-19T00:00:00+00:00",  # offset 而非 Z
        "2026-07-19T00:00:00+01:00",  # 非 UTC offset
        "2026-07-19T00:00:00.000Z",  # 全零 fractional 也不接受
    ):
        with pytest.raises(SchedulerError):
            ScheduledOccurrence(
                schedule_id="test",
                occurrence_id="test",
                scheduled_for_utc=rejected,
                message="test message",
                workspace_scope_digest=SCOPE,
            )

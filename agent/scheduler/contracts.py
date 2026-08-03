"""Scheduler occurrence 与 report 的不可变合同。

checkpoint 相对路径只由 schedule_id + occurrence_id 派生；conversation/run/action identity
额外绑定 scheduled_for、message digest 与 workspace scope，因此同 ID 漂移命中原 checkpoint
后立即在 revision 0 上 conflict。不读取当前时间/cwd。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from agent.runtime.contracts import RunStatus

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_MAX_MESSAGE = 4_000
# canonical UTC：整秒 ``YYYY-MM-DDTHH:MM:SSZ``。fractional seconds、时区 offset 等非 canonical
# 写法一律拒绝（009-gate：未批准 fractional form 必须拒绝），calendar-valid 再叠加校验。
_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class SchedulerError(RuntimeError):
    """occurrence 校验或执行违反。"""


@dataclass(frozen=True, slots=True)
class ScheduledOccurrence:
    schedule_id: str
    occurrence_id: str
    scheduled_for_utc: str
    message: str
    workspace_scope_digest: str

    def __post_init__(self) -> None:
        for label, value in (
            ("schedule_id", self.schedule_id),
            ("occurrence_id", self.occurrence_id),
        ):
            if not _ID_PATTERN.match(value):
                raise SchedulerError(f"{label} must match [A-Za-z0-9_.:-]{{1,64}}")
        if not _UTC_PATTERN.match(self.scheduled_for_utc):
            raise SchedulerError("scheduled_for_utc must be canonical UTC (...Z)")
        if not _is_calendar_valid(self.scheduled_for_utc):
            raise SchedulerError("scheduled_for_utc must be a calendar-valid date")
        if not self.message.strip() or len(self.message) > _MAX_MESSAGE:
            raise SchedulerError("message must be bounded non-empty text")
        if not self.workspace_scope_digest:
            raise SchedulerError("workspace_scope_digest must not be empty")

    @property
    def message_digest(self) -> str:
        return hashlib.sha256(self.message.encode("utf-8")).hexdigest()

    @property
    def checkpoint_relative_path(self) -> str:
        payload = f"{self.schedule_id}\n{self.occurrence_id}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{digest}.json"

    @property
    def conversation_id(self) -> str:
        return _digest(
            {
                "kind": "scheduled-conversation",
                "schedule_id": self.schedule_id,
                "occurrence_id": self.occurrence_id,
                "scheduled_for": self.scheduled_for_utc,
                "message_digest": self.message_digest,
                "workspace_scope_digest": self.workspace_scope_digest,
            }
        )

    @property
    def run_id(self) -> str:
        return _digest(
            {
                "kind": "scheduled-run",
                "schedule_id": self.schedule_id,
                "occurrence_id": self.occurrence_id,
                "scheduled_for": self.scheduled_for_utc,
                "message_digest": self.message_digest,
                "workspace_scope_digest": self.workspace_scope_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class ScheduledRunReport:
    occurrence_status: str  # completed | needs_human | fatal_conflict
    run_status: RunStatus
    conversation_id: str
    run_id: str
    replayed: bool
    error_code: str | None
    checkpoint_relative_path: str
    pending_kind: str | None
    pending_request_id: str | None

    def to_json(self) -> str:
        return json.dumps(
            {
                "occurrence_status": self.occurrence_status,
                "run_status": self.run_status.value,
                "conversation_id": self.conversation_id,
                "run_id": self.run_id,
                "replayed": self.replayed,
                "error_code": self.error_code,
                "checkpoint_relative_path": self.checkpoint_relative_path,
                "pending_kind": self.pending_kind,
                "pending_request_id": self.pending_request_id,
            },
            sort_keys=True,
            ensure_ascii=False,
        )


def occurrence_exit_class(status: RunStatus) -> str:
    if status is RunStatus.COMPLETED:
        return "completed"
    if status in {
        RunStatus.AWAITING_APPROVAL,
        RunStatus.AWAITING_RECOVERY,
        RunStatus.LIMIT_REACHED,
        RunStatus.CONVERSATION_LIMIT_REACHED,
        RunStatus.FAILED_RETRYABLE,
    }:
        return "needs_human"
    return "fatal_conflict"


def _digest(payload: dict[str, str]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_calendar_valid(utc_str: str) -> bool:
    """canonical UTC（整秒）是否是真实日历时刻（闰日、月日、时分秒边界）。"""
    from datetime import datetime

    try:
        datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True

"""019 portable automation 的 immutable closed contracts。

本模块只定义 authority/state 的值对象，不读取时间、文件系统或 host capability。
definition 使用 body -> grant -> final digest 的两阶段绑定，避免循环 identity。
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from agent.runtime.contracts import canonical_json_digest

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ExecutionMode(StrEnum):
    FRESH_OCCURRENCE = "fresh_occurrence"


class ScheduleKind(StrEnum):
    ONCE_UTC = "once_utc"
    FIXED_INTERVAL_UTC = "fixed_interval_utc"


class CatchUpRule(StrEnum):
    NONE = "none"
    LATEST_ONE = "latest_one"


class AutomationStatus(StrEnum):
    PROPOSAL = "proposal"
    ACTIVE = "active"
    PAUSED = "paused"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    PURGE_PENDING = "purge_pending"
    PURGED = "purged"


class PurgeObjectKind(StrEnum):
    SOURCE_SNAPSHOT = "source_snapshot"
    OCCURRENCE_WORKSPACE = "occurrence_workspace"
    RETAINED_DIFF = "retained_diff"
    RETAINED_ARTIFACT = "retained_artifact"
    RUNTIME_CHECKPOINT = "runtime_checkpoint"
    GOVERNED_EXTERNAL_REFERENCE = "governed_external_reference"


class PurgeCleanupOutcome(StrEnum):
    CLEANED = "cleaned"
    UNLINKED = "unlinked"
    CLEANUP_UNKNOWN = "cleanup_unknown"


class OccurrenceControlStatus(StrEnum):
    CLAIMED = "claimed"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"
    MISFIRE_SKIPPED = "misfire_skipped"
    SUPERSEDED = "superseded"
    WORKER_DEADLINE = "worker_deadline"
    START_OUTCOME_UNKNOWN = "start_outcome_unknown"
    MODEL_OUTCOME_UNKNOWN = "model_outcome_unknown"
    EFFECT_OUTCOME_UNKNOWN = "effect_outcome_unknown"
    CLEANUP_UNKNOWN = "cleanup_unknown"
    CANCELED = "canceled"


class ScheduleDecisionKind(StrEnum):
    NOT_DUE = "not_due"
    DUE = "due"
    MISFIRE_SKIPPED = "misfire_skipped"
    EXPIRED = "expired"
    MAX_REACHED = "max_reached"
    PAUSED = "paused"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    NEEDS_HUMAN = "needs_human"


def parse_canonical_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be canonical UTC (...Z)")
    try:
        parsed = datetime.strptime(value, _UTC_FORMAT).replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError(f"{field} must be canonical UTC (...Z)") from error
    if parsed.strftime(_UTC_FORMAT) != value:
        raise ValueError(f"{field} must be canonical UTC (...Z)")
    return parsed


def format_canonical_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must be timezone-aware UTC")
    if value.microsecond:
        raise ValueError("datetime must use whole seconds")
    return value.astimezone(UTC).strftime(_UTC_FORMAT)


def _require_hex64(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"{field} must be bare hex64")
    return value


def _require_positive_int(value: object, field: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{field} must be an int in 1..{maximum}")
    return value


def _require_nonnegative_int(value: object, field: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{field} must be an int in 0..{maximum}")
    return value


@dataclass(frozen=True, slots=True)
class AutomationScheduleV1:
    kind: ScheduleKind
    anchor_utc: str
    interval_seconds: int | None
    catch_up: CatchUpRule
    misfire_grace_seconds: int
    schedule_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ScheduleKind):
            raise ValueError("kind must be a closed ScheduleKind")
        if not isinstance(self.catch_up, CatchUpRule):
            raise ValueError("catch_up must be a closed CatchUpRule")
        parse_canonical_utc(self.anchor_utc, "anchor_utc")
        _require_nonnegative_int(
            self.misfire_grace_seconds,
            "misfire_grace_seconds",
            maximum=3_600,
        )
        if self.kind is ScheduleKind.ONCE_UTC:
            if self.interval_seconds is not None:
                raise ValueError("once schedule interval_seconds must be null")
        elif (
            isinstance(self.interval_seconds, bool)
            or not isinstance(self.interval_seconds, int)
            or not 60 <= self.interval_seconds <= 2_592_000
        ):
            raise ValueError("fixed interval_seconds must be an int in 60..2592000")
        digest = canonical_json_digest(self.identity_values())
        if self.schedule_digest and self.schedule_digest != digest:
            raise ValueError("schedule digest mismatch")
        object.__setattr__(self, "schedule_digest", digest)

    def identity_values(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "anchor_utc": self.anchor_utc,
            "interval_seconds": self.interval_seconds,
            "catch_up": self.catch_up.value,
            "misfire_grace_seconds": self.misfire_grace_seconds,
        }


@dataclass(frozen=True, slots=True)
class AutomationBudgetsV1:
    occurrence_deadline_seconds: int
    model_calls: int
    tool_calls: int
    sandbox_commands: int
    browser_actions: int
    max_input_tokens: int
    max_output_tokens: int
    budgets_digest: str = ""

    def __post_init__(self) -> None:
        _require_positive_int(
            self.occurrence_deadline_seconds,
            "occurrence_deadline_seconds",
            maximum=3_600,
        )
        if self.occurrence_deadline_seconds < 30:
            raise ValueError("occurrence_deadline_seconds must be an int in 30..3600")
        _require_positive_int(self.model_calls, "model_calls", maximum=16)
        _require_positive_int(self.tool_calls, "tool_calls", maximum=32)
        _require_nonnegative_int(self.sandbox_commands, "sandbox_commands", maximum=16)
        _require_nonnegative_int(self.browser_actions, "browser_actions", maximum=32)
        _require_positive_int(self.max_input_tokens, "max_input_tokens", maximum=100_000)
        _require_positive_int(self.max_output_tokens, "max_output_tokens", maximum=20_000)
        digest = canonical_json_digest(self.identity_values())
        if self.budgets_digest and self.budgets_digest != digest:
            raise ValueError("budgets digest mismatch")
        object.__setattr__(self, "budgets_digest", digest)

    def identity_values(self) -> dict[str, int]:
        return {
            "occurrence_deadline_seconds": self.occurrence_deadline_seconds,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "sandbox_commands": self.sandbox_commands,
            "browser_actions": self.browser_actions,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True, slots=True)
class AutomationDefinitionBodyV1:
    automation_id: str
    revision: int
    label: str
    task_text: str
    source_workspace_binding_digest: str
    execution_mode: ExecutionMode
    provider_descriptor_digest: str
    trust_profile_digest: str
    credential_environment_name: str | None
    provider_disclosure_request_digest: str
    schedule: AutomationScheduleV1
    required_start_utc: str
    expires_at_utc: str
    max_occurrences: int
    budgets: AutomationBudgetsV1
    source_snapshot_digest: str
    background_environment_policy_digest: str | None
    browser_origin_policy_digest: str | None
    wake_adapter_policy_digest: str
    definition_body_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.automation_id, str) or not _OPAQUE_ID.fullmatch(
            self.automation_id
        ):
            raise ValueError("automation_id must be an opaque id")
        _require_positive_int(self.revision, "revision", maximum=2**31 - 1)
        if not isinstance(self.label, str) or not 1 <= len(self.label.strip()) <= 200:
            raise ValueError("label must be bounded non-empty text")
        if not isinstance(self.task_text, str) or not 1 <= len(self.task_text.strip()) <= 4_000:
            raise ValueError("task_text must be bounded non-empty text")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise ValueError("execution_mode must be a closed ExecutionMode")
        for field in (
            "source_workspace_binding_digest",
            "provider_descriptor_digest",
            "trust_profile_digest",
            "provider_disclosure_request_digest",
            "source_snapshot_digest",
            "wake_adapter_policy_digest",
        ):
            _require_hex64(getattr(self, field), field)
        for field in (
            "background_environment_policy_digest",
            "browser_origin_policy_digest",
        ):
            value = getattr(self, field)
            if value is not None:
                _require_hex64(value, field)
        if self.credential_environment_name is not None and not _ENV_NAME.fullmatch(
            self.credential_environment_name
        ):
            raise ValueError("credential_environment_name must be a canonical env name")
        if not isinstance(self.schedule, AutomationScheduleV1):
            raise ValueError("schedule must be AutomationScheduleV1")
        if not isinstance(self.budgets, AutomationBudgetsV1):
            raise ValueError("budgets must be AutomationBudgetsV1")
        start = parse_canonical_utc(self.required_start_utc, "required_start_utc")
        expires = parse_canonical_utc(self.expires_at_utc, "expires_at_utc")
        anchor = parse_canonical_utc(self.schedule.anchor_utc, "schedule.anchor_utc")
        if anchor < start:
            raise ValueError("schedule anchor must not precede required_start_utc")
        if not start < expires <= start + timedelta(days=366):
            raise ValueError("expires_at_utc must be within 366 days after required start")
        _require_positive_int(self.max_occurrences, "max_occurrences", maximum=128)
        if self.schedule.kind is ScheduleKind.ONCE_UTC and self.max_occurrences != 1:
            raise ValueError("once schedule requires max_occurrences=1")
        digest = canonical_json_digest(self.identity_values())
        if self.definition_body_digest and self.definition_body_digest != digest:
            raise ValueError("definition body digest mismatch")
        object.__setattr__(self, "definition_body_digest", digest)

    def identity_values(self) -> dict[str, object]:
        return {
            "automation_id": self.automation_id,
            "revision": self.revision,
            "label": self.label,
            "task_text": self.task_text,
            "source_workspace_binding_digest": self.source_workspace_binding_digest,
            "execution_mode": self.execution_mode.value,
            "provider_descriptor_digest": self.provider_descriptor_digest,
            "trust_profile_digest": self.trust_profile_digest,
            "credential_environment_name": self.credential_environment_name,
            "provider_disclosure_request_digest": self.provider_disclosure_request_digest,
            "schedule_digest": self.schedule.schedule_digest,
            "required_start_utc": self.required_start_utc,
            "expires_at_utc": self.expires_at_utc,
            "max_occurrences": self.max_occurrences,
            "budgets_digest": self.budgets.budgets_digest,
            "source_snapshot_digest": self.source_snapshot_digest,
            "background_environment_policy_digest": self.background_environment_policy_digest,
            "browser_origin_policy_digest": self.browser_origin_policy_digest,
            "wake_adapter_policy_digest": self.wake_adapter_policy_digest,
        }


@dataclass(frozen=True, slots=True)
class BackgroundAuthorityGrantV1:
    definition_body_digest: str
    activation_preview_digest: str
    sandbox_confined: bool
    browser_public_observe: bool
    grant_digest: str

    def __post_init__(self) -> None:
        _require_hex64(self.definition_body_digest, "definition_body_digest")
        _require_hex64(self.activation_preview_digest, "activation_preview_digest")
        if not isinstance(self.sandbox_confined, bool) or not isinstance(
            self.browser_public_observe, bool
        ):
            raise ValueError("background capabilities must be bools")
        expected = canonical_json_digest(self.identity_values())
        if self.grant_digest != expected:
            raise ValueError("background grant digest mismatch")

    def identity_values(self) -> dict[str, object]:
        return {
            "definition_body_digest": self.definition_body_digest,
            "activation_preview_digest": self.activation_preview_digest,
            "sandbox_confined": self.sandbox_confined,
            "browser_public_observe": self.browser_public_observe,
        }

    @classmethod
    def create(
        cls,
        *,
        body: AutomationDefinitionBodyV1,
        activation_preview_digest: str,
        sandbox_confined: bool,
        browser_public_observe: bool,
    ) -> BackgroundAuthorityGrantV1:
        if sandbox_confined != (body.budgets.sandbox_commands > 0):
            raise ValueError("sandbox grant must match sandbox command budget")
        if browser_public_observe != (body.budgets.browser_actions > 0):
            raise ValueError("browser grant must match browser action budget")
        if sandbox_confined != (body.background_environment_policy_digest is not None):
            raise ValueError("sandbox grant must match background environment policy")
        if browser_public_observe != (body.browser_origin_policy_digest is not None):
            raise ValueError("browser grant must match browser origin policy")
        _require_hex64(activation_preview_digest, "activation_preview_digest")
        values = {
            "definition_body_digest": body.definition_body_digest,
            "activation_preview_digest": activation_preview_digest,
            "sandbox_confined": sandbox_confined,
            "browser_public_observe": browser_public_observe,
        }
        return cls(**values, grant_digest=canonical_json_digest(values))


@dataclass(frozen=True, slots=True)
class AutomationDefinitionV1:
    body: AutomationDefinitionBodyV1
    grant: BackgroundAuthorityGrantV1
    definition_digest: str

    def __post_init__(self) -> None:
        if self.grant.definition_body_digest != self.body.definition_body_digest:
            raise ValueError("grant does not bind the definition body")
        expected = canonical_json_digest(
            {
                "definition_body_digest": self.body.definition_body_digest,
                "grant_digest": self.grant.grant_digest,
            }
        )
        if self.definition_digest != expected:
            raise ValueError("definition digest mismatch")

    @classmethod
    def create(
        cls,
        *,
        body: AutomationDefinitionBodyV1,
        grant: BackgroundAuthorityGrantV1,
    ) -> AutomationDefinitionV1:
        if grant.definition_body_digest != body.definition_body_digest:
            raise ValueError("grant does not bind the definition body")
        return cls(
            body=body,
            grant=grant,
            definition_digest=canonical_json_digest(
                {
                    "definition_body_digest": body.definition_body_digest,
                    "grant_digest": grant.grant_digest,
                }
            ),
        )

    @classmethod
    def create_from_body(
        cls,
        body: AutomationDefinitionBodyV1,
        *,
        activation_preview_digest: str,
        sandbox_confined: bool,
        browser_public_observe: bool,
    ) -> AutomationDefinitionV1:
        return cls.create(
            body=body,
            grant=BackgroundAuthorityGrantV1.create(
                body=body,
                activation_preview_digest=activation_preview_digest,
                sandbox_confined=sandbox_confined,
                browser_public_observe=browser_public_observe,
            ),
        )


@dataclass(frozen=True, slots=True)
class BackgroundOccurrenceAuthorityV1:
    automation_id: str
    automation_revision: int
    occurrence_id: str
    occurrence_index: int
    scheduled_for_utc: str
    definition_digest: str
    grant_digest: str
    claim_fencing_token: str
    checkpoint_identity: str
    deadline_utc: str
    raw_capability: str = dataclasses.field(repr=False)
    authority_digest: str = ""

    def __post_init__(self) -> None:
        for field in ("automation_id", "occurrence_id", "claim_fencing_token"):
            value = getattr(self, field)
            if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
                raise ValueError(f"{field} must be an opaque id")
        _require_positive_int(self.automation_revision, "automation_revision", maximum=2**31 - 1)
        _require_nonnegative_int(self.occurrence_index, "occurrence_index", maximum=127)
        parse_canonical_utc(self.scheduled_for_utc, "scheduled_for_utc")
        for field in ("definition_digest", "grant_digest", "checkpoint_identity"):
            _require_hex64(getattr(self, field), field)
        parse_canonical_utc(self.deadline_utc, "deadline_utc")
        if not isinstance(self.raw_capability, str) or len(self.raw_capability) < 32:
            raise ValueError("raw_capability must be an opaque high-entropy value")
        digest = canonical_json_digest(
            {
                "automation_id": self.automation_id,
                "automation_revision": self.automation_revision,
                "occurrence_id": self.occurrence_id,
                "occurrence_index": self.occurrence_index,
                "scheduled_for_utc": self.scheduled_for_utc,
                "definition_digest": self.definition_digest,
                "grant_digest": self.grant_digest,
                "claim_fencing_token": self.claim_fencing_token,
                "checkpoint_identity": self.checkpoint_identity,
                "deadline_utc": self.deadline_utc,
                "capability_digest": canonical_json_digest(self.raw_capability),
            }
        )
        if self.authority_digest and self.authority_digest != digest:
            raise ValueError("occurrence authority digest mismatch")
        object.__setattr__(self, "authority_digest", digest)


@dataclass(frozen=True, slots=True)
class OccurrenceSummaryV1:
    occurrence_id: str
    status: OccurrenceControlStatus
    scheduled_for_utc: str
    definition_digest: str
    checkpoint_identity_digest: str
    result_digest: str | None
    replayed: bool
    error_code: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_id, str) or not _OPAQUE_ID.fullmatch(
            self.occurrence_id
        ):
            raise ValueError("occurrence_id must be an opaque id")
        if not isinstance(self.status, OccurrenceControlStatus):
            raise ValueError("status must be a closed OccurrenceControlStatus")
        parse_canonical_utc(self.scheduled_for_utc, "scheduled_for_utc")
        _require_hex64(self.definition_digest, "definition_digest")
        _require_hex64(self.checkpoint_identity_digest, "checkpoint_identity_digest")
        if self.result_digest is not None:
            _require_hex64(self.result_digest, "result_digest")
        if not isinstance(self.replayed, bool):
            raise ValueError("replayed must be bool")


@dataclass(frozen=True, slots=True)
class PurgeOwnedObjectV1:
    object_id: str
    kind: PurgeObjectKind
    identity_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.object_id, str) or not _OPAQUE_ID.fullmatch(self.object_id):
            raise ValueError("object_id must be an opaque id")
        if not isinstance(self.kind, PurgeObjectKind):
            raise ValueError("kind must be a closed PurgeObjectKind")
        _require_hex64(self.identity_digest, "identity_digest")

    def identity_values(self) -> dict[str, str]:
        return {
            "object_id": self.object_id,
            "kind": self.kind.value,
            "identity_digest": self.identity_digest,
        }


@dataclass(frozen=True, slots=True)
class PurgeOwnershipManifestV1:
    automation_id: str
    automation_revision: int
    occurrence_count: int
    checkpoint_count: int
    objects: tuple[PurgeOwnedObjectV1, ...]
    manifest_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.automation_id, str) or not _OPAQUE_ID.fullmatch(
            self.automation_id
        ):
            raise ValueError("automation_id must be an opaque id")
        _require_positive_int(
            self.automation_revision,
            "automation_revision",
            maximum=2**31 - 1,
        )
        _require_nonnegative_int(self.occurrence_count, "occurrence_count", maximum=128)
        _require_nonnegative_int(self.checkpoint_count, "checkpoint_count", maximum=128)
        if not isinstance(self.objects, tuple) or any(
            not isinstance(item, PurgeOwnedObjectV1) for item in self.objects
        ):
            raise ValueError("objects must be a tuple of purge-owned identities")
        object_ids = tuple(item.object_id for item in self.objects)
        if object_ids != tuple(sorted(set(object_ids))):
            raise ValueError("purge objects must be sorted with unique ids")
        digest = canonical_json_digest(
            {
                "automation_id": self.automation_id,
                "automation_revision": self.automation_revision,
                "occurrence_count": self.occurrence_count,
                "checkpoint_count": self.checkpoint_count,
                "objects": [item.identity_values() for item in self.objects],
            }
        )
        if self.manifest_digest and self.manifest_digest != digest:
            raise ValueError("purge ownership manifest digest mismatch")
        object.__setattr__(self, "manifest_digest", digest)


@dataclass(frozen=True, slots=True)
class AutomationRecordV1:
    definition: AutomationDefinitionV1 | None
    status: AutomationStatus
    next_occurrence_index: int
    terminal_occurrence_count: int
    needs_human_reason: str | None
    active_claim: BackgroundOccurrenceAuthorityV1 | None
    terminal_history: tuple[OccurrenceSummaryV1, ...]
    draft_body: AutomationDefinitionBodyV1 | None = None
    active_claim_phase: OccurrenceControlStatus | None = None
    active_claim_definition: AutomationDefinitionV1 | None = None
    active_process_identity_digest: str | None = None
    purge_manifest: PurgeOwnershipManifestV1 | None = None
    purge_confirmed_object_ids: tuple[str, ...] = ()
    purge_active_object_id: str | None = None
    purge_cleanup_unknown_object_id: str | None = None

    def __post_init__(self) -> None:
        if self.definition is not None and not isinstance(
            self.definition, AutomationDefinitionV1
        ):
            raise ValueError("definition must be AutomationDefinitionV1 or null")
        if self.draft_body is not None and not isinstance(
            self.draft_body, AutomationDefinitionBodyV1
        ):
            raise ValueError("draft_body must be AutomationDefinitionBodyV1 or null")
        if not isinstance(self.status, AutomationStatus):
            raise ValueError("status must be a closed AutomationStatus")
        _require_nonnegative_int(
            self.next_occurrence_index,
            "next_occurrence_index",
            maximum=128,
        )
        _require_nonnegative_int(
            self.terminal_occurrence_count,
            "terminal_occurrence_count",
            maximum=128,
        )
        if self.needs_human_reason is not None and not self.needs_human_reason:
            raise ValueError("needs_human_reason must be non-empty or null")
        if self.needs_human_reason is not None and self.status is not AutomationStatus.PAUSED:
            raise ValueError("needs-human record must be paused")
        if self.active_claim is not None and not isinstance(
            self.active_claim, BackgroundOccurrenceAuthorityV1
        ):
            raise ValueError("active_claim must be occurrence authority or null")
        if self.status is AutomationStatus.PROPOSAL:
            if self.definition is not None or self.draft_body is None:
                raise ValueError("proposal requires only a draft definition body")
        elif self.status is AutomationStatus.PURGE_PENDING:
            if (
                self.definition is not None
                or self.draft_body is not None
                or self.purge_manifest is None
                or self.active_claim is not None
                or self.terminal_history
            ):
                raise ValueError("purge pending requires only a content-free manifest")
        elif self.status is AutomationStatus.PURGED:
            raise ValueError("purged automation must be represented by a tombstone")
        elif self.definition is None:
            raise ValueError("non-proposal record requires an approved definition")
        if self.status is not AutomationStatus.PURGE_PENDING and (
            self.purge_manifest is not None
            or self.purge_confirmed_object_ids
            or self.purge_active_object_id is not None
            or self.purge_cleanup_unknown_object_id is not None
        ):
            raise ValueError("only purge pending records carry purge progress")
        if self.purge_manifest is not None:
            known_ids = tuple(item.object_id for item in self.purge_manifest.objects)
            if (
                not isinstance(self.purge_confirmed_object_ids, tuple)
                or any(
                    not isinstance(item, str) or not _OPAQUE_ID.fullmatch(item)
                    for item in self.purge_confirmed_object_ids
                )
                or
                self.purge_confirmed_object_ids
                != tuple(sorted(set(self.purge_confirmed_object_ids)))
                or any(item not in known_ids for item in self.purge_confirmed_object_ids)
            ):
                raise ValueError("purge progress must be sorted and manifest-bound")
            for value, field in (
                (self.purge_active_object_id, "purge_active_object_id"),
                (
                    self.purge_cleanup_unknown_object_id,
                    "purge_cleanup_unknown_object_id",
                ),
            ):
                if value is not None and (
                    not isinstance(value, str)
                    or not _OPAQUE_ID.fullmatch(value)
                    or value not in known_ids
                ):
                    raise ValueError(f"{field} must name a manifest object")
            if (
                self.purge_active_object_id is not None
                and self.purge_active_object_id in self.purge_confirmed_object_ids
            ):
                raise ValueError("confirmed purge object cannot remain active")
            if self.purge_cleanup_unknown_object_id is not None and (
                self.purge_active_object_id != self.purge_cleanup_unknown_object_id
            ):
                raise ValueError("cleanup unknown must bind the active purge object")
        if self.definition is not None and self.draft_body is not None:
            if self.definition.body.automation_id != self.draft_body.automation_id:
                raise ValueError("draft and approved definition ids must match")
            if self.draft_body.revision <= self.definition.body.revision:
                raise ValueError("draft revision must be newer than approved revision")
        if self.active_claim is None:
            if (
                self.active_claim_phase is not None
                or self.active_claim_definition is not None
                or self.active_process_identity_digest is not None
            ):
                raise ValueError("inactive record carries active claim state")
        else:
            if self.active_claim_phase not in {
                OccurrenceControlStatus.CLAIMED,
                OccurrenceControlStatus.DISPATCHED,
                OccurrenceControlStatus.RUNNING,
                OccurrenceControlStatus.NEEDS_HUMAN,
                OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
                OccurrenceControlStatus.MODEL_OUTCOME_UNKNOWN,
                OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
                OccurrenceControlStatus.CLEANUP_UNKNOWN,
            }:
                raise ValueError("active claim requires a live claim phase")
            if self.active_claim_definition is None:
                raise ValueError("active claim requires its immutable definition")
            if (
                self.active_claim.automation_id
                != self.active_claim_definition.body.automation_id
                or self.active_claim.automation_revision
                != self.active_claim_definition.body.revision
                or self.active_claim.definition_digest
                != self.active_claim_definition.definition_digest
                or self.active_claim.grant_digest
                != self.active_claim_definition.grant.grant_digest
            ):
                raise ValueError("active claim does not match its immutable definition")
            if self.active_claim_phase in {
                OccurrenceControlStatus.DISPATCHED,
                OccurrenceControlStatus.RUNNING,
            }:
                if self.active_process_identity_digest is None:
                    raise ValueError("dispatched/running claim requires process identity")
                _require_hex64(
                    self.active_process_identity_digest,
                    "active_process_identity_digest",
                )
            elif (
                self.active_claim_phase is OccurrenceControlStatus.CLAIMED
                and self.active_process_identity_digest is not None
            ):
                raise ValueError("claimed occurrence must not carry process identity")
        if not isinstance(self.terminal_history, tuple) or any(
            not isinstance(item, OccurrenceSummaryV1) for item in self.terminal_history
        ):
            raise ValueError("terminal_history must be a tuple of summaries")
        if len(self.terminal_history) > 128:
            raise ValueError("terminal_history must contain at most 128 summaries")

    @property
    def automation_id(self) -> str:
        if self.definition is not None:
            return self.definition.body.automation_id
        if self.draft_body is not None:
            return self.draft_body.automation_id
        assert self.purge_manifest is not None
        return self.purge_manifest.automation_id


@dataclass(frozen=True, slots=True)
class AutomationTombstoneV1:
    automation_id: str
    purged_revision: int
    purged_at_utc: str
    tombstone_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.automation_id, str) or not _OPAQUE_ID.fullmatch(
            self.automation_id
        ):
            raise ValueError("automation_id must be an opaque id")
        _require_positive_int(self.purged_revision, "purged_revision", maximum=2**31 - 1)
        parse_canonical_utc(self.purged_at_utc, "purged_at_utc")
        digest = canonical_json_digest(
            {
                "automation_id": self.automation_id,
                "purged_revision": self.purged_revision,
                "purged_at_utc": self.purged_at_utc,
            }
        )
        if self.tombstone_digest and self.tombstone_digest != digest:
            raise ValueError("tombstone digest mismatch")
        object.__setattr__(self, "tombstone_digest", digest)


@dataclass(frozen=True, slots=True)
class AutomationSnapshotV1:
    revision: int
    snapshot_token: str
    records: tuple[AutomationRecordV1, ...]
    tombstones: tuple[AutomationTombstoneV1, ...]

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.revision, "revision", maximum=2**63 - 1)
        if not isinstance(self.snapshot_token, str) or len(self.snapshot_token) < 16:
            raise ValueError("snapshot_token must be opaque")
        if not isinstance(self.records, tuple) or len(self.records) > 128:
            raise ValueError("records must be a bounded tuple")
        if not isinstance(self.tombstones, tuple) or len(self.tombstones) > 128:
            raise ValueError("tombstones must be a bounded tuple")
        record_ids = tuple(record.automation_id for record in self.records)
        tombstone_ids = tuple(item.automation_id for item in self.tombstones)
        if record_ids != tuple(sorted(record_ids)) or len(record_ids) != len(set(record_ids)):
            raise ValueError("records must be sorted with unique ids")
        if tombstone_ids != tuple(sorted(tombstone_ids)) or len(tombstone_ids) != len(
            set(tombstone_ids)
        ):
            raise ValueError("tombstones must be sorted with unique ids")
        if set(record_ids) & set(tombstone_ids):
            raise ValueError("active and purged automation ids must not overlap")
        nonterminal_statuses = {
            AutomationStatus.PROPOSAL,
            AutomationStatus.ACTIVE,
            AutomationStatus.PAUSED,
            AutomationStatus.CANCEL_PENDING,
            AutomationStatus.PURGE_PENDING,
        }
        if sum(record.status in nonterminal_statuses for record in self.records) > 32:
            raise ValueError("snapshot supports at most 32 non-terminal automations")


def _require_mutation_tokens(expected: object, next_token: object) -> None:
    for value, field in (
        (expected, "expected_snapshot_token"),
        (next_token, "next_snapshot_token"),
    ):
        if not isinstance(value, str) or len(value) < 16:
            raise ValueError(f"{field} must be opaque")
    if expected == next_token:
        raise ValueError("next_snapshot_token must change")


@dataclass(frozen=True, slots=True)
class CreateProposal:
    expected_snapshot_token: str
    next_snapshot_token: str
    body: AutomationDefinitionBodyV1

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not isinstance(self.body, AutomationDefinitionBodyV1):
            raise ValueError("body must be AutomationDefinitionBodyV1")


@dataclass(frozen=True, slots=True)
class ApproveRevision:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str
    definition: AutomationDefinitionV1
    activation_preview_digest: str

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not isinstance(self.automation_id, str) or not _OPAQUE_ID.fullmatch(
            self.automation_id
        ):
            raise ValueError("automation_id must be an opaque id")
        if not isinstance(self.definition, AutomationDefinitionV1):
            raise ValueError("definition must be AutomationDefinitionV1")
        _require_hex64(self.activation_preview_digest, "activation_preview_digest")


@dataclass(frozen=True, slots=True)
class StageRevision:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str
    body: AutomationDefinitionBodyV1

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not isinstance(self.automation_id, str) or not _OPAQUE_ID.fullmatch(
            self.automation_id
        ):
            raise ValueError("automation_id must be an opaque id")
        if not isinstance(self.body, AutomationDefinitionBodyV1):
            raise ValueError("body must be AutomationDefinitionBodyV1")


@dataclass(frozen=True, slots=True)
class PauseAutomation:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not _OPAQUE_ID.fullmatch(self.automation_id):
            raise ValueError("automation_id must be an opaque id")


@dataclass(frozen=True, slots=True)
class ResumeAutomation:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not _OPAQUE_ID.fullmatch(self.automation_id):
            raise ValueError("automation_id must be an opaque id")


@dataclass(frozen=True, slots=True)
class CancelAutomation:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not _OPAQUE_ID.fullmatch(self.automation_id):
            raise ValueError("automation_id must be an opaque id")


@dataclass(frozen=True, slots=True)
class BeginPurge:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str
    manifest: PurgeOwnershipManifestV1
    preview_digest: str

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not isinstance(self.automation_id, str) or not _OPAQUE_ID.fullmatch(
            self.automation_id
        ):
            raise ValueError("automation_id must be an opaque id")
        if not isinstance(self.manifest, PurgeOwnershipManifestV1):
            raise ValueError("manifest must use PurgeOwnershipManifestV1")
        if self.manifest.automation_id != self.automation_id:
            raise ValueError("purge manifest automation mismatch")
        _require_hex64(self.preview_digest, "preview_digest")
        if self.preview_digest != self.manifest.manifest_digest:
            raise ValueError("purge approval must bind the exact manifest")


@dataclass(frozen=True, slots=True)
class StartPurgeObject:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str
    object_id: str

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not _OPAQUE_ID.fullmatch(self.automation_id):
            raise ValueError("automation_id must be an opaque id")
        if not _OPAQUE_ID.fullmatch(self.object_id):
            raise ValueError("object_id must be an opaque id")


@dataclass(frozen=True, slots=True)
class RecordPurgeProgress:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str
    object_id: str
    outcome: PurgeCleanupOutcome

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not _OPAQUE_ID.fullmatch(self.automation_id):
            raise ValueError("automation_id must be an opaque id")
        if not _OPAQUE_ID.fullmatch(self.object_id):
            raise ValueError("object_id must be an opaque id")
        if not isinstance(self.outcome, PurgeCleanupOutcome):
            raise ValueError("outcome must be a closed PurgeCleanupOutcome")


@dataclass(frozen=True, slots=True)
class FinishPurge:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str
    purged_at_utc: str

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not _OPAQUE_ID.fullmatch(self.automation_id):
            raise ValueError("automation_id must be an opaque id")
        parse_canonical_utc(self.purged_at_utc, "purged_at_utc")


@dataclass(frozen=True, slots=True)
class ClaimOccurrence:
    expected_snapshot_token: str
    next_snapshot_token: str
    authority: BackgroundOccurrenceAuthorityV1

    def __post_init__(self) -> None:
        _require_mutation_tokens(self.expected_snapshot_token, self.next_snapshot_token)
        if not isinstance(self.authority, BackgroundOccurrenceAuthorityV1):
            raise ValueError("authority must be BackgroundOccurrenceAuthorityV1")


def _require_claim_mutation(
    expected_snapshot_token: object,
    next_snapshot_token: object,
    automation_id: object,
    authority_digest: object,
) -> None:
    _require_mutation_tokens(expected_snapshot_token, next_snapshot_token)
    if not isinstance(automation_id, str) or not _OPAQUE_ID.fullmatch(automation_id):
        raise ValueError("automation_id must be an opaque id")
    _require_hex64(authority_digest, "authority_digest")


@dataclass(frozen=True, slots=True)
class MarkDispatched:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str
    authority_digest: str
    process_identity_digest: str

    def __post_init__(self) -> None:
        _require_claim_mutation(
            self.expected_snapshot_token,
            self.next_snapshot_token,
            self.automation_id,
            self.authority_digest,
        )
        _require_hex64(self.process_identity_digest, "process_identity_digest")


@dataclass(frozen=True, slots=True)
class MarkRunning:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str
    authority_digest: str
    process_identity_digest: str

    def __post_init__(self) -> None:
        _require_claim_mutation(
            self.expected_snapshot_token,
            self.next_snapshot_token,
            self.automation_id,
            self.authority_digest,
        )
        _require_hex64(self.process_identity_digest, "process_identity_digest")


@dataclass(frozen=True, slots=True)
class RecordOccurrenceOutcome:
    expected_snapshot_token: str
    next_snapshot_token: str
    automation_id: str
    authority_digest: str
    summary: OccurrenceSummaryV1

    def __post_init__(self) -> None:
        _require_claim_mutation(
            self.expected_snapshot_token,
            self.next_snapshot_token,
            self.automation_id,
            self.authority_digest,
        )
        if not isinstance(self.summary, OccurrenceSummaryV1):
            raise ValueError("summary must be OccurrenceSummaryV1")


AutomationMutationV1 = (
    CreateProposal
    | ApproveRevision
    | StageRevision
    | PauseAutomation
    | ResumeAutomation
    | CancelAutomation
    | BeginPurge
    | StartPurgeObject
    | RecordPurgeProgress
    | FinishPurge
    | ClaimOccurrence
    | MarkDispatched
    | MarkRunning
    | RecordOccurrenceOutcome
)


@dataclass(frozen=True, slots=True)
class AutomationControllerResultV1:
    code: str
    snapshot: AutomationSnapshotV1

    def __post_init__(self) -> None:
        if self.code != "applied":
            raise ValueError("controller result code must be applied")
        if not isinstance(self.snapshot, AutomationSnapshotV1):
            raise ValueError("snapshot must be AutomationSnapshotV1")


@dataclass(frozen=True, slots=True)
class ScheduleDecisionV1:
    kind: ScheduleDecisionKind
    occurrence_index: int | None = None
    scheduled_for_utc: str | None = None
    superseded_indexes: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ScheduleDecisionKind):
            raise ValueError("kind must be a closed ScheduleDecisionKind")
        if self.kind in {ScheduleDecisionKind.DUE, ScheduleDecisionKind.MISFIRE_SKIPPED}:
            if self.occurrence_index is None or self.scheduled_for_utc is None:
                raise ValueError("due/misfire decision requires an occurrence")
            _require_nonnegative_int(
                self.occurrence_index,
                "occurrence_index",
                maximum=127,
            )
            parse_canonical_utc(self.scheduled_for_utc, "scheduled_for_utc")
        elif self.occurrence_index is not None or self.scheduled_for_utc is not None:
            raise ValueError("non-occurrence decision must not carry an occurrence")
        if not isinstance(self.superseded_indexes, tuple) or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in self.superseded_indexes
        ):
            raise ValueError("superseded_indexes must be non-negative ints")

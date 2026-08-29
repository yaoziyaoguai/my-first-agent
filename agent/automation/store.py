"""019 canonical snapshot codec 与 platform-neutral repository contract。

这里没有文件路径、锁或 OS API。真实持久化 adapter 必须独立通过同一合同；
deterministic adapter 只用于协议、故障和 sealed U2A 证据。
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from enum import StrEnum
from typing import Protocol

from agent.automation.contracts import (
    AutomationBudgetsV1,
    AutomationDefinitionBodyV1,
    AutomationDefinitionV1,
    AutomationRecordV1,
    AutomationScheduleV1,
    AutomationSnapshotV1,
    AutomationStatus,
    AutomationTombstoneV1,
    BackgroundAuthorityGrantV1,
    BackgroundOccurrenceAuthorityV1,
    CatchUpRule,
    ExecutionMode,
    OccurrenceControlStatus,
    OccurrenceSummaryV1,
    PurgeObjectKind,
    PurgeOwnedObjectV1,
    PurgeOwnershipManifestV1,
    ScheduleKind,
)

MAX_AUTOMATION_STORE_BYTES = 4 * 1024 * 1024


class AutomationRepositoryError(RuntimeError):
    """Repository contract violation or unavailable operation."""


class AutomationRepositoryBusyError(AutomationRepositoryError):
    """The short nonblocking mutation lease is already held."""


class AutomationRepositoryConflictError(AutomationRepositoryError):
    """CAS token/revision no longer names current authority."""


class AutomationRepositoryUnknownCommitError(AutomationRepositoryError):
    """The caller must reload because commit outcome is not known."""


class DeterministicCommitFault(StrEnum):
    BEFORE_COMMIT = "before_commit"
    AFTER_COMMIT = "after_commit"


class AutomationRepositoryLease(Protocol):
    def __enter__(self) -> AutomationRepositoryLease: ...

    def __exit__(self, exc_type, exc, traceback) -> None: ...  # noqa: ANN001


class AutomationRepository(Protocol):
    def load(self) -> AutomationSnapshotV1: ...

    def try_acquire(self) -> AutomationRepositoryLease: ...

    def compare_and_swap(
        self,
        *,
        expected_snapshot_token: str,
        next_snapshot: AutomationSnapshotV1,
    ) -> None: ...


def encode_snapshot(snapshot: AutomationSnapshotV1) -> bytes:
    if not isinstance(snapshot, AutomationSnapshotV1):
        raise ValueError("snapshot must be AutomationSnapshotV1")
    payload = json.dumps(
        _encode_snapshot(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_AUTOMATION_STORE_BYTES:
        raise ValueError("automation snapshot is too large")
    return payload


def decode_snapshot(payload: bytes) -> AutomationSnapshotV1:
    if not isinstance(payload, bytes):
        raise ValueError("automation snapshot must be bytes")
    if len(payload) > MAX_AUTOMATION_STORE_BYTES:
        raise ValueError("automation snapshot is too large")
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("automation snapshot is malformed JSON") from error
    root = _mapping(document, "snapshot")
    _exact_keys(root, {"revision", "snapshot_token", "records", "tombstones"}, "snapshot")
    return AutomationSnapshotV1(
        revision=root["revision"],
        snapshot_token=root["snapshot_token"],
        records=tuple(_decode_record(item) for item in _list(root["records"], "records")),
        tombstones=tuple(
            _decode_tombstone(item) for item in _list(root["tombstones"], "tombstones")
        ),
    )


def encode_definition_body_json(body: AutomationDefinitionBodyV1) -> str:
    if not isinstance(body, AutomationDefinitionBodyV1):
        raise ValueError("body must be AutomationDefinitionBodyV1")
    return json.dumps(
        _encode_body(body),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def decode_definition_body_json(raw: str) -> AutomationDefinitionBodyV1:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 32 * 1024:
        raise ValueError("definition body JSON must be bounded text")
    try:
        document = json.loads(raw, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("definition body is malformed JSON") from error
    body = _decode_body(document)
    if encode_definition_body_json(body) != raw:
        raise ValueError("definition body JSON must be canonical")
    return body


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _exact_keys(value: dict[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields must be exact")


def _encode_snapshot(snapshot: AutomationSnapshotV1) -> dict[str, object]:
    return {
        "revision": snapshot.revision,
        "snapshot_token": snapshot.snapshot_token,
        "records": [_encode_record(record) for record in snapshot.records],
        "tombstones": [_encode_tombstone(item) for item in snapshot.tombstones],
    }


def _encode_record(record: AutomationRecordV1) -> dict[str, object]:
    return {
        "definition": (
            None if record.definition is None else _encode_definition(record.definition)
        ),
        "draft_body": None if record.draft_body is None else _encode_body(record.draft_body),
        "status": record.status.value,
        "next_occurrence_index": record.next_occurrence_index,
        "terminal_occurrence_count": record.terminal_occurrence_count,
        "needs_human_reason": record.needs_human_reason,
        "active_claim": (
            None if record.active_claim is None else _encode_authority(record.active_claim)
        ),
        "active_claim_phase": (
            None if record.active_claim_phase is None else record.active_claim_phase.value
        ),
        "active_claim_definition": (
            None
            if record.active_claim_definition is None
            else _encode_definition(record.active_claim_definition)
        ),
        "active_process_identity_digest": record.active_process_identity_digest,
        "terminal_history": [_encode_summary(item) for item in record.terminal_history],
        "purge_manifest": (
            None
            if record.purge_manifest is None
            else _encode_purge_manifest(record.purge_manifest)
        ),
        "purge_confirmed_object_ids": list(record.purge_confirmed_object_ids),
        "purge_active_object_id": record.purge_active_object_id,
        "purge_cleanup_unknown_object_id": record.purge_cleanup_unknown_object_id,
    }


def _decode_record(value: object) -> AutomationRecordV1:
    item = _mapping(value, "record")
    _exact_keys(
        item,
        {
            "definition",
            "draft_body",
            "status",
            "next_occurrence_index",
            "terminal_occurrence_count",
            "needs_human_reason",
            "active_claim",
            "active_claim_phase",
            "active_claim_definition",
            "active_process_identity_digest",
            "terminal_history",
            "purge_manifest",
            "purge_confirmed_object_ids",
            "purge_active_object_id",
            "purge_cleanup_unknown_object_id",
        },
        "record",
    )
    raw_claim = item["active_claim"]
    raw_definition = item["definition"]
    raw_draft = item["draft_body"]
    raw_claim_definition = item["active_claim_definition"]
    raw_purge_manifest = item["purge_manifest"]
    confirmed_ids = _list(
        item["purge_confirmed_object_ids"],
        "purge_confirmed_object_ids",
    )
    if any(not isinstance(object_id, str) for object_id in confirmed_ids):
        raise ValueError("purge confirmed ids must be strings")
    return AutomationRecordV1(
        definition=None if raw_definition is None else _decode_definition(raw_definition),
        status=AutomationStatus(item["status"]),
        next_occurrence_index=item["next_occurrence_index"],
        terminal_occurrence_count=item["terminal_occurrence_count"],
        needs_human_reason=item["needs_human_reason"],
        active_claim=None if raw_claim is None else _decode_authority(raw_claim),
        terminal_history=tuple(
            _decode_summary(entry)
            for entry in _list(item["terminal_history"], "terminal_history")
        ),
        draft_body=None if raw_draft is None else _decode_body(raw_draft),
        active_claim_phase=(
            None
            if item["active_claim_phase"] is None
            else OccurrenceControlStatus(item["active_claim_phase"])
        ),
        active_claim_definition=(
            None
            if raw_claim_definition is None
            else _decode_definition(raw_claim_definition)
        ),
        active_process_identity_digest=item["active_process_identity_digest"],
        purge_manifest=(
            None
            if raw_purge_manifest is None
            else _decode_purge_manifest(raw_purge_manifest)
        ),
        purge_confirmed_object_ids=tuple(confirmed_ids),
        purge_active_object_id=item["purge_active_object_id"],
        purge_cleanup_unknown_object_id=item["purge_cleanup_unknown_object_id"],
    )


def _encode_purge_manifest(manifest: PurgeOwnershipManifestV1) -> dict[str, object]:
    return {
        "automation_id": manifest.automation_id,
        "automation_revision": manifest.automation_revision,
        "occurrence_count": manifest.occurrence_count,
        "checkpoint_count": manifest.checkpoint_count,
        "objects": [item.identity_values() for item in manifest.objects],
        "manifest_digest": manifest.manifest_digest,
    }


def _decode_purge_manifest(value: object) -> PurgeOwnershipManifestV1:
    item = _mapping(value, "purge manifest")
    _exact_keys(
        item,
        {
            "automation_id",
            "automation_revision",
            "occurrence_count",
            "checkpoint_count",
            "objects",
            "manifest_digest",
        },
        "purge manifest",
    )
    objects: list[PurgeOwnedObjectV1] = []
    for raw_object in _list(item["objects"], "purge objects"):
        object_item = _mapping(raw_object, "purge object")
        _exact_keys(
            object_item,
            {"object_id", "kind", "identity_digest"},
            "purge object",
        )
        objects.append(
            PurgeOwnedObjectV1(
                object_id=object_item["object_id"],
                kind=PurgeObjectKind(object_item["kind"]),
                identity_digest=object_item["identity_digest"],
            )
        )
    return PurgeOwnershipManifestV1(
        automation_id=item["automation_id"],
        automation_revision=item["automation_revision"],
        occurrence_count=item["occurrence_count"],
        checkpoint_count=item["checkpoint_count"],
        objects=tuple(objects),
        manifest_digest=item["manifest_digest"],
    )


def _encode_definition(definition: AutomationDefinitionV1) -> dict[str, object]:
    return {
        "body": _encode_body(definition.body),
        "grant": {
            "definition_body_digest": definition.grant.definition_body_digest,
            "activation_preview_digest": definition.grant.activation_preview_digest,
            "sandbox_confined": definition.grant.sandbox_confined,
            "browser_public_observe": definition.grant.browser_public_observe,
            "grant_digest": definition.grant.grant_digest,
        },
        "definition_digest": definition.definition_digest,
    }


def _decode_definition(value: object) -> AutomationDefinitionV1:
    item = _mapping(value, "definition")
    _exact_keys(item, {"body", "grant", "definition_digest"}, "definition")
    body = _decode_body(item["body"])
    grant_item = _mapping(item["grant"], "background grant")
    _exact_keys(
        grant_item,
        {
            "definition_body_digest",
            "activation_preview_digest",
            "sandbox_confined",
            "browser_public_observe",
            "grant_digest",
        },
        "background grant",
    )
    if grant_item["definition_body_digest"] != body.definition_body_digest:
        raise ValueError("grant does not bind the definition body")
    grant = BackgroundAuthorityGrantV1.create(
        body=body,
        activation_preview_digest=grant_item["activation_preview_digest"],
        sandbox_confined=grant_item["sandbox_confined"],
        browser_public_observe=grant_item["browser_public_observe"],
    )
    if grant.grant_digest != grant_item["grant_digest"]:
        raise ValueError("background grant digest mismatch")
    return AutomationDefinitionV1(
        body=body,
        grant=grant,
        definition_digest=item["definition_digest"],
    )


def _encode_body(body: AutomationDefinitionBodyV1) -> dict[str, object]:
    return {
        "automation_id": body.automation_id,
        "revision": body.revision,
        "label": body.label,
        "task_text": body.task_text,
        "source_workspace_binding_digest": body.source_workspace_binding_digest,
        "execution_mode": body.execution_mode.value,
        "provider_descriptor_digest": body.provider_descriptor_digest,
        "trust_profile_digest": body.trust_profile_digest,
        "credential_environment_name": body.credential_environment_name,
        "provider_disclosure_request_digest": body.provider_disclosure_request_digest,
        "schedule": _encode_schedule(body.schedule),
        "required_start_utc": body.required_start_utc,
        "expires_at_utc": body.expires_at_utc,
        "max_occurrences": body.max_occurrences,
        "budgets": _encode_budgets(body.budgets),
        "source_snapshot_digest": body.source_snapshot_digest,
        "background_environment_policy_digest": body.background_environment_policy_digest,
        "browser_origin_policy_digest": body.browser_origin_policy_digest,
        "wake_adapter_policy_digest": body.wake_adapter_policy_digest,
        "definition_body_digest": body.definition_body_digest,
    }


def _decode_body(value: object) -> AutomationDefinitionBodyV1:
    item = _mapping(value, "definition body")
    expected = {
        "automation_id",
        "revision",
        "label",
        "task_text",
        "source_workspace_binding_digest",
        "execution_mode",
        "provider_descriptor_digest",
        "trust_profile_digest",
        "credential_environment_name",
        "provider_disclosure_request_digest",
        "schedule",
        "required_start_utc",
        "expires_at_utc",
        "max_occurrences",
        "budgets",
        "source_snapshot_digest",
        "background_environment_policy_digest",
        "browser_origin_policy_digest",
        "wake_adapter_policy_digest",
        "definition_body_digest",
    }
    _exact_keys(item, expected, "definition body")
    return AutomationDefinitionBodyV1(
        automation_id=item["automation_id"],
        revision=item["revision"],
        label=item["label"],
        task_text=item["task_text"],
        source_workspace_binding_digest=item["source_workspace_binding_digest"],
        execution_mode=ExecutionMode(item["execution_mode"]),
        provider_descriptor_digest=item["provider_descriptor_digest"],
        trust_profile_digest=item["trust_profile_digest"],
        credential_environment_name=item["credential_environment_name"],
        provider_disclosure_request_digest=item["provider_disclosure_request_digest"],
        schedule=_decode_schedule(item["schedule"]),
        required_start_utc=item["required_start_utc"],
        expires_at_utc=item["expires_at_utc"],
        max_occurrences=item["max_occurrences"],
        budgets=_decode_budgets(item["budgets"]),
        source_snapshot_digest=item["source_snapshot_digest"],
        background_environment_policy_digest=item["background_environment_policy_digest"],
        browser_origin_policy_digest=item["browser_origin_policy_digest"],
        wake_adapter_policy_digest=item["wake_adapter_policy_digest"],
        definition_body_digest=item["definition_body_digest"],
    )


def _encode_schedule(schedule: AutomationScheduleV1) -> dict[str, object]:
    return {
        "kind": schedule.kind.value,
        "anchor_utc": schedule.anchor_utc,
        "interval_seconds": schedule.interval_seconds,
        "catch_up": schedule.catch_up.value,
        "misfire_grace_seconds": schedule.misfire_grace_seconds,
        "schedule_digest": schedule.schedule_digest,
    }


def _decode_schedule(value: object) -> AutomationScheduleV1:
    item = _mapping(value, "schedule")
    _exact_keys(
        item,
        {
            "kind",
            "anchor_utc",
            "interval_seconds",
            "catch_up",
            "misfire_grace_seconds",
            "schedule_digest",
        },
        "schedule",
    )
    return AutomationScheduleV1(
        kind=ScheduleKind(item["kind"]),
        anchor_utc=item["anchor_utc"],
        interval_seconds=item["interval_seconds"],
        catch_up=CatchUpRule(item["catch_up"]),
        misfire_grace_seconds=item["misfire_grace_seconds"],
        schedule_digest=item["schedule_digest"],
    )


def _encode_budgets(budgets: AutomationBudgetsV1) -> dict[str, object]:
    return {
        **budgets.identity_values(),
        "budgets_digest": budgets.budgets_digest,
    }


def _decode_budgets(value: object) -> AutomationBudgetsV1:
    item = _mapping(value, "budgets")
    expected = {
        "occurrence_deadline_seconds",
        "model_calls",
        "tool_calls",
        "sandbox_commands",
        "browser_actions",
        "max_input_tokens",
        "max_output_tokens",
        "budgets_digest",
    }
    _exact_keys(item, expected, "budgets")
    return AutomationBudgetsV1(**item)


def _encode_authority(authority: BackgroundOccurrenceAuthorityV1) -> dict[str, object]:
    return {
        "automation_id": authority.automation_id,
        "automation_revision": authority.automation_revision,
        "occurrence_id": authority.occurrence_id,
        "occurrence_index": authority.occurrence_index,
        "scheduled_for_utc": authority.scheduled_for_utc,
        "definition_digest": authority.definition_digest,
        "grant_digest": authority.grant_digest,
        "claim_fencing_token": authority.claim_fencing_token,
        "checkpoint_identity": authority.checkpoint_identity,
        "deadline_utc": authority.deadline_utc,
        "raw_capability": authority.raw_capability,
        "authority_digest": authority.authority_digest,
    }


def _decode_authority(value: object) -> BackgroundOccurrenceAuthorityV1:
    item = _mapping(value, "occurrence authority")
    _exact_keys(
        item,
        {
            "automation_id",
            "automation_revision",
            "occurrence_id",
            "occurrence_index",
            "scheduled_for_utc",
            "definition_digest",
            "grant_digest",
            "claim_fencing_token",
            "checkpoint_identity",
            "deadline_utc",
            "raw_capability",
            "authority_digest",
        },
        "occurrence authority",
    )
    return BackgroundOccurrenceAuthorityV1(**item)


def _encode_summary(summary: OccurrenceSummaryV1) -> dict[str, object]:
    return {
        "occurrence_id": summary.occurrence_id,
        "status": summary.status.value,
        "scheduled_for_utc": summary.scheduled_for_utc,
        "definition_digest": summary.definition_digest,
        "checkpoint_identity_digest": summary.checkpoint_identity_digest,
        "result_digest": summary.result_digest,
        "replayed": summary.replayed,
        "error_code": summary.error_code,
    }


def _decode_summary(value: object) -> OccurrenceSummaryV1:
    item = _mapping(value, "occurrence summary")
    _exact_keys(
        item,
        {
            "occurrence_id",
            "status",
            "scheduled_for_utc",
            "definition_digest",
            "checkpoint_identity_digest",
            "result_digest",
            "replayed",
            "error_code",
        },
        "occurrence summary",
    )
    return OccurrenceSummaryV1(
        occurrence_id=item["occurrence_id"],
        status=OccurrenceControlStatus(item["status"]),
        scheduled_for_utc=item["scheduled_for_utc"],
        definition_digest=item["definition_digest"],
        checkpoint_identity_digest=item["checkpoint_identity_digest"],
        result_digest=item["result_digest"],
        replayed=item["replayed"],
        error_code=item["error_code"],
    )


def _encode_tombstone(tombstone: AutomationTombstoneV1) -> dict[str, object]:
    return {
        "automation_id": tombstone.automation_id,
        "purged_revision": tombstone.purged_revision,
        "purged_at_utc": tombstone.purged_at_utc,
        "tombstone_digest": tombstone.tombstone_digest,
    }


def _decode_tombstone(value: object) -> AutomationTombstoneV1:
    item = _mapping(value, "tombstone")
    _exact_keys(
        item,
        {"automation_id", "purged_revision", "purged_at_utc", "tombstone_digest"},
        "tombstone",
    )
    return AutomationTombstoneV1(**item)


class _DeterministicLease(AbstractContextManager["_DeterministicLease"]):
    def __init__(self, repository: DeterministicAutomationRepository) -> None:
        self._repository = repository
        self._released = False

    def __enter__(self) -> _DeterministicLease:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        if not self._released:
            self._released = True
            self._repository._release()


class DeterministicAutomationRepository:
    """无 OS I/O 的 repository contract adapter，支持 closed crash injection。"""

    def __init__(self, initial_snapshot: AutomationSnapshotV1) -> None:
        self._snapshot = decode_snapshot(encode_snapshot(initial_snapshot))
        self._lease_held = False
        self._next_fault: DeterministicCommitFault | None = None

    def load(self) -> AutomationSnapshotV1:
        return decode_snapshot(encode_snapshot(self._snapshot))

    def try_acquire(self) -> AutomationRepositoryLease:
        if self._lease_held:
            raise AutomationRepositoryBusyError("automation repository lease is busy")
        self._lease_held = True
        return _DeterministicLease(self)

    def compare_and_swap(
        self,
        *,
        expected_snapshot_token: str,
        next_snapshot: AutomationSnapshotV1,
    ) -> None:
        if not self._lease_held:
            raise AutomationRepositoryError("compare_and_swap requires the short lease")
        if expected_snapshot_token != self._snapshot.snapshot_token:
            raise AutomationRepositoryConflictError("automation snapshot token conflict")
        if next_snapshot.revision != self._snapshot.revision + 1:
            raise AutomationRepositoryConflictError("automation snapshot revision conflict")
        if next_snapshot.snapshot_token == self._snapshot.snapshot_token:
            raise AutomationRepositoryConflictError("next snapshot token must change")
        fault = self._next_fault
        self._next_fault = None
        if fault is DeterministicCommitFault.BEFORE_COMMIT:
            raise AutomationRepositoryUnknownCommitError(
                "commit outcome unknown before mutation"
            )
        committed = decode_snapshot(encode_snapshot(next_snapshot))
        self._snapshot = committed
        if fault is DeterministicCommitFault.AFTER_COMMIT:
            raise AutomationRepositoryUnknownCommitError(
                "commit outcome unknown after mutation"
            )

    def arm_commit_fault(self, fault: DeterministicCommitFault) -> None:
        if not isinstance(fault, DeterministicCommitFault):
            raise ValueError("fault must be a closed DeterministicCommitFault")
        if self._next_fault is not None:
            raise AutomationRepositoryError("a deterministic commit fault is already armed")
        self._next_fault = fault

    def _release(self) -> None:
        if not self._lease_held:
            raise AutomationRepositoryError("automation repository lease is not held")
        self._lease_held = False

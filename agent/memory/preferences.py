"""Owner-confirmed cross-workspace preferences on the existing safe MemoryStore primitive."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.memory.contracts import (
    MemoryBusyError,
    MemoryCasMismatchError,
    MemoryRecord,
    ProviderTrustProfile,
)
from agent.memory.store import _MAX_CONTENT_CHARS, MemoryStore
from agent.runtime.contracts import (
    ApprovalPolicy,
    ContextCandidate,
    ContextQuery,
    ContextSourceSnapshot,
    ConversationFact,
    ExecutionAuthorityClass,
    FactKind,
    KnownNotExecuted,
    OutputPolicy,
    PreferenceAdmissionBinding,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
    canonical_json_digest,
    context_source_snapshot_digest,
)
from agent.runtime.tools import RegisteredTool

_OWNER_SCOPE = "owner-preferences-v1"
_ACTIVE_ORIGIN = "owner_preference:active"
_FORGOTTEN_ORIGIN = "owner_preference:forgotten"


@dataclass(frozen=True, slots=True)
class PreferenceAdmission:
    content: str
    source_fact_id: str
    source_fact_digest: str
    admission_digest: str
    runtime_binding: PreferenceAdmissionBinding | None = None

    def __post_init__(self) -> None:
        if not self.content.strip() or not self.source_fact_id or not self.source_fact_digest:
            raise ValueError("preference admission fields must not be empty")
        if self.runtime_binding is not None:
            if (
                self.source_fact_id != self.runtime_binding.fact_id
                or self.source_fact_digest != self.runtime_binding.fact_digest
                or canonical_json_digest(self.content)
                != self.runtime_binding.content_digest
                or self.admission_digest != self.runtime_binding.binding_digest
            ):
                raise ValueError("preference Runtime admission binding mismatch")
            return
        expected = canonical_json_digest(
            {
                "content": self.content,
                "source_fact_id": self.source_fact_id,
                "source_fact_digest": self.source_fact_digest,
                "origin": "explicit_user_confirmation",
            }
        )
        if self.admission_digest != expected:
            raise ValueError("preference admission digest mismatch")

    @classmethod
    def from_user_fact(
        cls,
        fact: ConversationFact,
        *,
        content: str,
        confirmed: bool,
    ) -> PreferenceAdmission:
        if not confirmed or fact.kind is not FactKind.USER_MESSAGE:
            raise ValueError("owner preference requires explicit user confirmation")
        text = fact.content.get("text")
        if text != content:
            raise ValueError("preference preview must exactly match the confirmed user fact")
        source_digest = canonical_json_digest(
            {"fact_id": fact.fact_id, "kind": fact.kind, "content": fact.content}
        )
        values = {
            "content": content,
            "source_fact_id": fact.fact_id,
            "source_fact_digest": source_digest,
            "origin": "explicit_user_confirmation",
        }
        return cls(
            content=content,
            source_fact_id=fact.fact_id,
            source_fact_digest=source_digest,
            admission_digest=canonical_json_digest(values),
        )

    @classmethod
    def from_runtime_binding(
        cls,
        binding: PreferenceAdmissionBinding,
        *,
        content: str,
    ) -> PreferenceAdmission:
        if canonical_json_digest(content) != binding.content_digest:
            raise ValueError("preference content does not match Runtime admission")
        return cls(
            content=content,
            source_fact_id=binding.fact_id,
            source_fact_digest=binding.fact_digest,
            admission_digest=binding.binding_digest,
            runtime_binding=binding,
        )


@dataclass(frozen=True, slots=True)
class PreferenceForgetReceipt:
    preference_id: str
    local_store_revision: int
    claim: str = "future local recall disabled; history and remote copies are not erased"


class OwnerPreferenceStore:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @staticmethod
    def _profile(provider_trust_digest: str) -> ProviderTrustProfile:
        if not provider_trust_digest:
            raise ValueError("provider trust digest must not be empty")
        return ProviderTrustProfile(
            profile_id=provider_trust_digest,
            provider_family="owner_preferences",
            destination="local-owner-store",
        )

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        provider_trust_digest: str,
    ) -> OwnerPreferenceStore:
        return cls(
            MemoryStore.create(
                path,
                workspace_scope_digest=_OWNER_SCOPE,
                profile=cls._profile(provider_trust_digest),
            )
        )

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        provider_trust_digest: str,
    ) -> OwnerPreferenceStore:
        return cls(
            MemoryStore.load(
                path,
                workspace_scope_digest=_OWNER_SCOPE,
                profile=cls._profile(provider_trust_digest),
            )
        )

    @property
    def revision(self) -> int:
        return self._store.revision

    def confirm(self, admission: PreferenceAdmission) -> MemoryRecord:
        return self._store.remember_with_provenance(
            admission.content,
            source_fact_id=admission.source_fact_id,
            origin=_ACTIVE_ORIGIN,
            admission_binding_digest=admission.admission_digest,
        )

    def correct(
        self,
        preference_id: str,
        admission: PreferenceAdmission,
    ) -> MemoryRecord:
        self._store.snapshot()
        existing = self._store.get(preference_id)
        if existing is None or not _is_active(existing):
            raise ValueError("preference does not exist")
        return self._store.update(
            preference_id,
            admission.content,
            expected_record_revision=existing.revision,
            expected_content_digest=existing.content_digest,
            source_fact_id=admission.source_fact_id,
            origin=(
                f"{_ACTIVE_ORIGIN}:supersedes:"
                f"{existing.record_id}@{existing.revision}"
            ),
            admission_binding_digest=admission.admission_digest,
        )

    def forget(self, preference_id: str) -> PreferenceForgetReceipt:
        self._store.snapshot()
        existing = self._store.get(preference_id)
        if existing is None or not _is_active(existing):
            raise ValueError("preference does not exist")
        self._store.update(
            preference_id,
            existing.content,
            expected_record_revision=existing.revision,
            expected_content_digest=existing.content_digest,
            origin=_FORGOTTEN_ORIGIN,
        )
        return PreferenceForgetReceipt(
            preference_id=preference_id,
            local_store_revision=self._store.revision,
        )

    def snapshot(self) -> tuple[MemoryRecord, ...]:
        return tuple(record for record in self._store.snapshot() if _is_active(record))

    def explain(self, preference_id: str) -> dict[str, str | int]:
        self._store.snapshot()
        record = self._store.get(preference_id)
        if record is None:
            raise ValueError("preference does not exist")
        return {
            "preference_id": record.record_id,
            "source_fact_id": record.source_fact_id or "unknown",
            "origin": (
                "explicit_user_confirmation"
                if record.origin and record.origin.startswith("owner_preference:")
                else record.origin or "unknown"
            ),
            "content_digest": record.content_digest,
            "revision": record.revision,
            "status": _preference_status(record),
            "supersedes": _supersedes(record) or "none",
        }


class OwnerPreferenceSource:
    name = "owner_preferences"

    def __init__(self, store: OwnerPreferenceStore) -> None:
        self._store = store

    def snapshot(self, query: ContextQuery) -> ContextSourceSnapshot:
        records = self._store.snapshot()[: query.source_limits.max_items]
        candidates = tuple(
            ContextCandidate(
                candidate_id=record.record_id,
                source_name=self.name,
                workspace_scope_digest=query.workspace_scope_digest,
                content=record.content,
                content_digest=record.content_digest,
                provenance={
                    "origin": "explicit_user_confirmation",
                    "source_fact_id": record.source_fact_id,
                    "admission_binding_digest": record.admission_binding_digest,
                },
                rank_key=f"{record.updated_at:020.6f}:{record.record_id}",
            )
            for record in records
        )
        return ContextSourceSnapshot(
            source_name=self.name,
            revision=self._store.revision,
            snapshot_digest=context_source_snapshot_digest(
                self.name, self._store.revision, candidates
            ),
            candidates=candidates,
        )


def build_owner_preference_tool_registrations(
    store: OwnerPreferenceStore,
) -> tuple[RegisteredTool, ...]:
    """偏好 CRUD 全部复用唯一 ToolRuntime；mutation 始终要求 human approval。"""

    return (
        RegisteredTool(
            _preference_spec("owner_preference_explain", read_only=True),
            _explain(store),
        ),
        RegisteredTool(
            _preference_spec("owner_preference_confirm"),
            _confirm(store),
            prepare_binding=_prepare_confirm(store),
        ),
        RegisteredTool(
            _preference_spec("owner_preference_correct"),
            _correct(store),
            prepare_binding=_prepare_correct(store),
        ),
        RegisteredTool(
            _preference_spec("owner_preference_forget"),
            _forget(store),
            prepare_binding=_prepare_forget(store),
        ),
    )


def _preference_spec(name: str, *, read_only: bool = False) -> ToolSpec:
    properties: dict[str, dict[str, str]] = {
        "preference_id": {"type": "string"},
    }
    required = ["preference_id"]
    if name == "owner_preference_confirm":
        properties = {"content": {"type": "string"}}
        required = ["content"]
    elif name == "owner_preference_correct":
        properties["content"] = {"type": "string"}
        required.append("content")
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name=name,
        version="1",
        description=f"Governed owner preference operation: {name}.",
        input_schema={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW if read_only else ToolRisk.HIGH,
        side_effect=SideEffectClass.READ_ONLY if read_only else SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER if read_only else ApprovalPolicy.ALWAYS,
        safety_policy={"kind": name, "scope": _OWNER_SCOPE},
        output_limit_chars=2_000,
    )


def _confirm(store: OwnerPreferenceStore):
    def invoke(intent):
        content = str(intent.arguments.get("content", ""))
        binding = intent.preference_admission
        if binding is None:
            return KnownNotExecuted(
                code="preference_admission_required",
                message="exact user confirmation is required",
            )
        try:
            record = store.confirm(
                PreferenceAdmission.from_runtime_binding(binding, content=content)
            )
        except (MemoryBusyError, MemoryCasMismatchError):
            return KnownNotExecuted(code="preference_busy", message="preference store changed")
        return f"confirmed preference {record.record_id} revision {record.revision}"

    return invoke


def _correct(store: OwnerPreferenceStore):
    def invoke(intent):
        content = str(intent.arguments.get("content", ""))
        binding = intent.preference_admission
        if binding is None:
            return KnownNotExecuted(
                code="preference_admission_required",
                message="exact user correction is required",
            )
        try:
            record = store.correct(
                str(intent.arguments.get("preference_id", "")),
                PreferenceAdmission.from_runtime_binding(binding, content=content),
            )
        except (MemoryBusyError, MemoryCasMismatchError, ValueError):
            return KnownNotExecuted(code="preference_changed", message="preference store changed")
        return f"corrected preference {record.record_id} revision {record.revision}"

    return invoke


def _forget(store: OwnerPreferenceStore):
    def invoke(intent):
        try:
            receipt = store.forget(str(intent.arguments.get("preference_id", "")))
        except (MemoryBusyError, MemoryCasMismatchError, ValueError):
            return KnownNotExecuted(code="preference_changed", message="preference store changed")
        return receipt.claim

    return invoke


def _explain(store: OwnerPreferenceStore):
    def invoke(intent):
        try:
            explanation = store.explain(str(intent.arguments.get("preference_id", "")))
        except ValueError:
            return KnownNotExecuted(code="preference_not_found", message="preference not found")
        return explanation

    return invoke


def _prepare_confirm(store: OwnerPreferenceStore):
    def prepare(arguments):
        content = str(arguments.get("content", ""))
        store.snapshot()
        return {
            "effect_preview": f"remember owner preference: {content[:_MAX_CONTENT_CHARS]}",
            "store_revision": store.revision,
            "new_content_digest": canonical_json_digest(content),
        }

    return prepare


def _prepare_correct(store: OwnerPreferenceStore):
    def prepare(arguments):
        preference_id = str(arguments.get("preference_id", ""))
        content = str(arguments.get("content", ""))
        store.snapshot()
        existing = store._store.get(preference_id)
        before = existing.content if existing is not None and _is_active(existing) else ""
        return {
            "effect_preview": f"correct owner preference:\n- {before}\n+ {content}",
            "store_revision": store.revision,
            "preference_id": preference_id,
            "old_content_digest": existing.content_digest if existing is not None else "",
            "new_content_digest": canonical_json_digest(content),
        }

    return prepare


def _prepare_forget(store: OwnerPreferenceStore):
    def prepare(arguments):
        preference_id = str(arguments.get("preference_id", ""))
        store.snapshot()
        existing = store._store.get(preference_id)
        before = existing.content if existing is not None and _is_active(existing) else ""
        return {
            "effect_preview": (
                f"forget owner preference for future recall: {before}; "
                "conversation history and remote copies are not erased"
            ),
            "store_revision": store.revision,
            "preference_id": preference_id,
            "old_content_digest": existing.content_digest if existing is not None else "",
        }

    return prepare


def _is_active(record: MemoryRecord) -> bool:
    return isinstance(record.origin, str) and record.origin.startswith(_ACTIVE_ORIGIN)


def _preference_status(record: MemoryRecord) -> str:
    return "active" if _is_active(record) else "forgotten"


def _supersedes(record: MemoryRecord) -> str | None:
    marker = ":supersedes:"
    if record.origin is None or marker not in record.origin:
        return None
    return record.origin.split(marker, 1)[1]

"""Agent Runtime Kernel 的不可变叶子合同。

这个模块只描述跨边界传递的数据，不拥有循环、持久化、工具执行或适配器行为。
保持它只依赖标准库，是防止新 Kernel 再次长成 service locator 的第一道边界。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum, StrEnum
from typing import TypeAlias
from urllib.parse import urlsplit, urlunsplit

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class FrozenJSONDict(dict[str, JSONValue]):
    """保持 JSON/dict 兼容，同时拒绝合同外的原地修改。"""

    def _immutable(self, *_args, **_kwargs):
        raise TypeError("frozen JSON object cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class FrozenJSONList(list[JSONValue]):
    """保持 JSON/list 兼容，同时拒绝合同外的原地修改。"""

    def _immutable(self, *_args, **_kwargs):
        raise TypeError("frozen JSON array cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable


def _freeze_json(value: object) -> JSONValue:
    if isinstance(value, FrozenJSONDict | FrozenJSONList):
        return value
    if isinstance(value, dict):
        return FrozenJSONDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return FrozenJSONList(_freeze_json(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"cannot freeze {type(value).__name__}")


def _freeze_json_dict(value: dict[str, JSONValue]) -> dict[str, JSONValue]:
    frozen = _freeze_json(value)
    if not isinstance(frozen, dict):
        raise TypeError("expected a JSON object")
    return frozen


def _assert_json_compatible(value: object, *, path: str = "value") -> None:
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _assert_json_compatible(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} must have string keys and JSON-compatible values")
            _assert_json_compatible(item, path=f"{path}.{key}")
        return
    raise TypeError(f"{path} must be JSON-compatible, got {type(value).__name__}")


def _canonical_json_value(value: object) -> JSONValue:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple | list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"cannot canonicalize {type(value).__name__}")


def canonical_json_digest(value: object) -> str:
    encoded = json.dumps(
        _canonical_json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def closed_evidence_id(goal_id: str, goal_revision: int, criterion_id: str) -> str:
    """叶子合同层拥有 deterministic evidence identity，避免领域模块反向依赖。"""

    return f"evidence:{goal_id}:{goal_revision}:{criterion_id}"


class ActiveRunStatus(StrEnum):
    RUNNABLE = "runnable"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_RECOVERY = "awaiting_recovery"
    AWAITING_DISCLOSURE = "awaiting_disclosure"
    PAUSED_LIMIT = "paused_limit"
    PAUSED_RETRYABLE = "paused_retryable"


class ContinuationPhase(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    EXECUTING = "executing"


class RunStatus(StrEnum):
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_RECOVERY = "awaiting_recovery"
    AWAITING_DISCLOSURE = "awaiting_disclosure"
    CANCELLED = "cancelled"
    LIMIT_REACHED = "limit_reached"
    CONVERSATION_LIMIT_REACHED = "conversation_limit_reached"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FATAL = "failed_fatal"
    CONFLICT = "conflict"


class ActionDisposition(StrEnum):
    ACCEPTED = "accepted"
    REPLAYED = "replayed"
    CONFLICT = "conflict"


class RecoveryResolution(StrEnum):
    MARK_SUCCEEDED = "mark_succeeded"
    MARK_FAILED = "mark_failed"


class ToolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SideEffectClass(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    EXTERNAL = "external"


class OutputPolicy(StrEnum):
    BOUNDED_TEXT = "bounded_text"


class ApprovalPolicy(StrEnum):
    NEVER = "never"
    ALWAYS = "always"


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class FactKind(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALLS = "tool_calls"
    TOOL_RESULT = "tool_result"
    POLICY_RESULT = "policy_result"


class GoalStatus(StrEnum):
    GOAL_READY = "goal_ready"
    EXECUTING = "executing"
    NEEDS_AUTHORITY = "needs_authority"
    PAUSED = "paused"
    BLOCKED = "blocked"
    VERIFIED_DONE = "verified_done"
    CANCELLED = "cancelled"


class InteractionState(StrEnum):
    IDLE = "idle"
    ANSWERING = "answering"
    CLARIFYING = "clarifying"


class EvidenceOracleKind(StrEnum):
    FILESYSTEM_DIGEST = "filesystem_digest"
    TOOL_RECEIPT = "tool_receipt"
    USER_CONFIRMATION = "user_confirmation"


class AuthoritySourceKind(StrEnum):
    USER_FACT = "user_fact"
    HUMAN_ACTION = "human_action"
    HUMAN_APPROVAL = "human_approval"
    DURABLE_GRANT = "durable_grant"


class FactAdmissionClass(StrEnum):
    WORKSPACE_FACT = "workspace_fact"
    VERIFIED_DERIVED_NOTE = "verified_derived_note"


@dataclass(frozen=True, slots=True)
class ProposedCriterion:
    criterion_id: str
    description: str

    def __post_init__(self) -> None:
        if not self.criterion_id or not self.description.strip():
            raise ValueError("proposed criterion identity and description must not be empty")


@dataclass(frozen=True, slots=True)
class AdmittedCriterion:
    criterion_id: str
    description: str
    source_fact_id: str
    oracle_kind: EvidenceOracleKind
    predicate: dict[str, JSONValue]
    required_evidence_class: str
    admission_digest: str
    mandatory: bool = True

    def __post_init__(self) -> None:
        if not all(
            (
                self.criterion_id,
                self.description.strip(),
                self.source_fact_id,
                self.required_evidence_class,
                self.admission_digest,
            )
        ):
            raise ValueError("admitted criterion fields must not be empty")
        if not self.predicate:
            raise ValueError("admitted criterion predicate must not be empty")
        _assert_json_compatible(self.predicate, path="criterion.predicate")
        object.__setattr__(self, "predicate", _freeze_json_dict(self.predicate))


@dataclass(frozen=True, slots=True)
class GoalFrame:
    goal_id: str
    revision: int
    created_from_fact_ids: tuple[str, ...]
    workspace_identity_digest: str
    user_outcome: str
    beneficiary: str
    targets: tuple[str, ...]
    scope: tuple[str, ...]
    non_goals: tuple[str, ...]
    assumptions: tuple[str, ...]
    proposed_criteria: tuple[ProposedCriterion, ...]
    admitted_criteria: tuple[AdmittedCriterion, ...]
    authority_snapshot: str
    status: GoalStatus
    created_at: str
    updated_at: str
    progress_summary: str | None = None
    next_step: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.goal_id,
            self.workspace_identity_digest,
            self.user_outcome.strip(),
            self.beneficiary.strip(),
            self.authority_snapshot,
            self.created_at,
            self.updated_at,
        )
        if not all(required):
            raise ValueError("goal identity, outcome, authority, and timestamps must not be empty")
        if self.revision < 1:
            raise ValueError("goal revision must be positive")
        if not self.created_from_fact_ids or any(not item for item in self.created_from_fact_ids):
            raise ValueError("goal must retain authoritative source fact ids")
        if not self.targets or any(not item for item in self.targets):
            raise ValueError("goal targets must not be empty")
        if not self.scope or any(not item for item in self.scope):
            raise ValueError("goal scope must not be empty")
        if not self.proposed_criteria and not self.admitted_criteria:
            raise ValueError("goal must define at least one completion criterion")
        criterion_ids = tuple(
            criterion.criterion_id
            for criterion in (*self.proposed_criteria, *self.admitted_criteria)
        )
        if len(set(criterion_ids)) != len(criterion_ids):
            proposed_ids = {criterion.criterion_id for criterion in self.proposed_criteria}
            admitted_ids = {criterion.criterion_id for criterion in self.admitted_criteria}
            if len(proposed_ids) != len(self.proposed_criteria) or len(admitted_ids) != len(
                self.admitted_criteria
            ):
                raise ValueError("criterion ids must be unique within each criterion set")
        object.__setattr__(self, "created_from_fact_ids", tuple(self.created_from_fact_ids))
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(self, "scope", tuple(self.scope))
        object.__setattr__(self, "non_goals", tuple(self.non_goals))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "proposed_criteria", tuple(self.proposed_criteria))
        object.__setattr__(self, "admitted_criteria", tuple(self.admitted_criteria))


@dataclass(frozen=True, slots=True)
class GoalBootstrap:
    """Runtime 生成、模型只可引用的 Goal 初始权威元数据。"""

    source_fact_id: str
    workspace_identity_digest: str
    authority_snapshot: str

    def __post_init__(self) -> None:
        if not all(
            (self.source_fact_id, self.workspace_identity_digest, self.authority_snapshot)
        ):
            raise ValueError("goal bootstrap fields must not be empty")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    goal_id: str
    goal_revision: int
    criterion_id: str
    oracle_kind: EvidenceOracleKind
    predicate_digest: str
    source_fact_ids: tuple[str, ...]
    source_digest: str
    oracle_identity: str
    passed: bool
    observed_at: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.evidence_id,
                self.goal_id,
                self.criterion_id,
                self.predicate_digest,
                self.source_digest,
                self.oracle_identity,
                self.observed_at,
            )
        ):
            raise ValueError("evidence identity and binding fields must not be empty")
        if self.goal_revision < 1:
            raise ValueError("evidence goal_revision must be positive")
        if not self.source_fact_ids or any(not item for item in self.source_fact_ids):
            raise ValueError("evidence must retain at least one source fact")
        object.__setattr__(self, "source_fact_ids", tuple(self.source_fact_ids))


@dataclass(frozen=True, slots=True)
class CompletionClaim:
    correlation_id: str
    goal_id: str
    goal_revision: int
    criterion_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.correlation_id or not self.goal_id:
            raise ValueError("completion claim identity must not be empty")
        if self.goal_revision < 1:
            raise ValueError("completion claim goal_revision must be positive")
        if any(not item for item in self.criterion_evidence_refs):
            raise ValueError("completion claim evidence refs must not be empty strings")
        if len(set(self.criterion_evidence_refs)) != len(self.criterion_evidence_refs):
            raise ValueError("completion claim evidence refs must be unique")
        object.__setattr__(
            self,
            "criterion_evidence_refs",
            tuple(self.criterion_evidence_refs),
        )


@dataclass(frozen=True, slots=True)
class GoalDelta:
    goal_id: str
    expected_revision: int
    reason: str
    updates: dict[str, JSONValue]
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if not self.goal_id or not self.reason.strip():
            raise ValueError("goal delta identity and reason must not be empty")
        if self.expected_revision < 1:
            raise ValueError("goal delta expected_revision must be positive")
        if not self.updates:
            raise ValueError("goal delta must contain at least one update")
        allowed = {
            "user_outcome",
            "beneficiary",
            "targets",
            "scope",
            "non_goals",
            "assumptions",
            "proposed_criteria",
            "admitted_criteria",
            "authority_snapshot",
        }
        unknown = set(self.updates) - allowed
        if unknown:
            raise ValueError(f"goal delta contains unsupported fields: {sorted(unknown)}")
        _assert_json_compatible(self.updates, path="goal_delta.updates")
        object.__setattr__(self, "updates", _freeze_json_dict(self.updates))


@dataclass(frozen=True, slots=True)
class GoalAuthorizationBinding:
    binding_id: str
    goal_id: str
    goal_revision: int
    workspace_identity_digest: str
    operation: str
    normalized_target: str
    source_kind: AuthoritySourceKind
    source_id: str
    source_digest: str
    binding_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, AuthoritySourceKind):
            raise ValueError("authority source must be authoritative user or durable state")
        if not all(
            (
                self.binding_id,
                self.goal_id,
                self.workspace_identity_digest,
                self.operation,
                self.normalized_target,
                self.source_id,
                self.source_digest,
                self.binding_digest,
            )
        ):
            raise ValueError("goal authorization binding fields must not be empty")
        if self.goal_revision < 1:
            raise ValueError("goal authorization revision must be positive")
        if self.normalized_target.startswith(("/", "../")) or "/../" in self.normalized_target:
            raise ValueError("authorization target must be normalized and workspace-relative")
        if self.binding_digest != self._expected_digest():
            raise ValueError("goal authorization binding digest mismatch")

    def _expected_digest(self) -> str:
        return canonical_json_digest(
            {
                "binding_id": self.binding_id,
                "goal_id": self.goal_id,
                "goal_revision": self.goal_revision,
                "workspace_identity_digest": self.workspace_identity_digest,
                "operation": self.operation,
                "normalized_target": self.normalized_target,
                "source_kind": self.source_kind,
                "source_id": self.source_id,
                "source_digest": self.source_digest,
            }
        )

    @classmethod
    def create(
        cls,
        *,
        binding_id: str,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        operation: str,
        normalized_target: str,
        source_kind: AuthoritySourceKind,
        source_id: str,
        source_digest: str,
    ) -> GoalAuthorizationBinding:
        if not isinstance(source_kind, AuthoritySourceKind):
            raise ValueError("authority source must be authoritative user or durable state")
        values = {
            "binding_id": binding_id,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "workspace_identity_digest": workspace_identity_digest,
            "operation": operation,
            "normalized_target": normalized_target,
            "source_kind": source_kind,
            "source_id": source_id,
            "source_digest": source_digest,
        }
        return cls(**values, binding_digest=canonical_json_digest(values))

    def authorizes(
        self,
        *,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        operation: str,
        normalized_target: str,
    ) -> bool:
        return (
            self.goal_id == goal_id
            and self.goal_revision == goal_revision
            and self.workspace_identity_digest == workspace_identity_digest
            and self.operation == operation
            and self.normalized_target == normalized_target
            and self.binding_digest == self._expected_digest()
        )


@dataclass(frozen=True, slots=True)
class CriterionAdmissionBinding:
    binding_id: str
    goal_id: str
    goal_revision: int
    workspace_identity_digest: str
    criterion_id: str
    user_outcome_fact_id: str
    user_outcome_digest: str
    oracle_kind: EvidenceOracleKind
    predicate: dict[str, JSONValue]
    required_evidence_class: str
    binding_digest: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.binding_id,
                self.goal_id,
                self.workspace_identity_digest,
                self.criterion_id,
                self.user_outcome_fact_id,
                self.user_outcome_digest,
                self.required_evidence_class,
                self.binding_digest,
            )
        ):
            raise ValueError("criterion admission binding fields must not be empty")
        if self.goal_revision < 1:
            raise ValueError("criterion admission revision must be positive")
        if not isinstance(self.oracle_kind, EvidenceOracleKind):
            raise ValueError("criterion admission must use a closed oracle kind")
        if not self.predicate:
            raise ValueError("criterion admission predicate must not be empty")
        _assert_json_compatible(self.predicate, path="criterion_admission.predicate")
        object.__setattr__(self, "predicate", _freeze_json_dict(self.predicate))
        if self.binding_digest != self._expected_digest():
            raise ValueError("criterion admission binding digest mismatch")

    def _expected_digest(self) -> str:
        return canonical_json_digest(
            {
                "binding_id": self.binding_id,
                "goal_id": self.goal_id,
                "goal_revision": self.goal_revision,
                "workspace_identity_digest": self.workspace_identity_digest,
                "criterion_id": self.criterion_id,
                "user_outcome_fact_id": self.user_outcome_fact_id,
                "user_outcome_digest": self.user_outcome_digest,
                "oracle_kind": self.oracle_kind,
                "predicate": self.predicate,
                "required_evidence_class": self.required_evidence_class,
            }
        )

    @classmethod
    def create(
        cls,
        *,
        binding_id: str,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        criterion_id: str,
        user_outcome_fact_id: str,
        user_outcome_digest: str,
        oracle_kind: EvidenceOracleKind,
        predicate: dict[str, JSONValue],
        required_evidence_class: str,
    ) -> CriterionAdmissionBinding:
        values = {
            "binding_id": binding_id,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "workspace_identity_digest": workspace_identity_digest,
            "criterion_id": criterion_id,
            "user_outcome_fact_id": user_outcome_fact_id,
            "user_outcome_digest": user_outcome_digest,
            "oracle_kind": oracle_kind,
            "predicate": predicate,
            "required_evidence_class": required_evidence_class,
        }
        return cls(**values, binding_digest=canonical_json_digest(values))

    def admit(self, description: str, *, mandatory: bool = True) -> AdmittedCriterion:
        if not description.strip():
            raise ValueError("criterion description must not be empty")
        return AdmittedCriterion(
            criterion_id=self.criterion_id,
            description=description,
            source_fact_id=self.user_outcome_fact_id,
            oracle_kind=self.oracle_kind,
            predicate=self.predicate,
            required_evidence_class=self.required_evidence_class,
            admission_digest=self.binding_digest,
            mandatory=mandatory,
        )

    def matches(
        self,
        *,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        criterion_id: str,
        oracle_kind: EvidenceOracleKind,
        predicate: dict[str, JSONValue],
    ) -> bool:
        return (
            self.goal_id == goal_id
            and self.goal_revision == goal_revision
            and self.workspace_identity_digest == workspace_identity_digest
            and self.criterion_id == criterion_id
            and self.oracle_kind is oracle_kind
            and canonical_json_digest(self.predicate) == canonical_json_digest(predicate)
            and self.binding_digest == self._expected_digest()
        )


@dataclass(frozen=True, slots=True)
class FactAdmissionBinding:
    binding_id: str
    fact_id: str
    fact_kind: FactKind
    fact_digest: str
    workspace_identity_digest: str
    goal_id: str
    goal_revision: int
    admission_class: FactAdmissionClass
    binding_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.fact_kind, FactKind):
            raise ValueError("fact admission must use a durable fact kind")
        if not isinstance(self.admission_class, FactAdmissionClass):
            raise ValueError("fact admission must use a closed admission class")
        if not all(
            (
                self.binding_id,
                self.fact_id,
                self.fact_digest,
                self.workspace_identity_digest,
                self.goal_id,
                self.binding_digest,
            )
        ):
            raise ValueError("fact admission binding fields must not be empty")
        if self.goal_revision < 1:
            raise ValueError("fact admission goal_revision must be positive")
        if self.binding_digest != self._expected_digest():
            raise ValueError("fact admission binding digest mismatch")

    def _expected_digest(self) -> str:
        return canonical_json_digest(
            {
                "binding_id": self.binding_id,
                "fact_id": self.fact_id,
                "fact_kind": self.fact_kind,
                "fact_digest": self.fact_digest,
                "workspace_identity_digest": self.workspace_identity_digest,
                "goal_id": self.goal_id,
                "goal_revision": self.goal_revision,
                "admission_class": self.admission_class,
            }
        )

    @classmethod
    def create(
        cls,
        *,
        binding_id: str,
        fact_id: str,
        fact_kind: FactKind,
        fact_digest: str,
        workspace_identity_digest: str,
        goal_id: str,
        goal_revision: int,
        admission_class: FactAdmissionClass,
    ) -> FactAdmissionBinding:
        values = {
            "binding_id": binding_id,
            "fact_id": fact_id,
            "fact_kind": fact_kind,
            "fact_digest": fact_digest,
            "workspace_identity_digest": workspace_identity_digest,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "admission_class": admission_class,
        }
        return cls(**values, binding_digest=canonical_json_digest(values))

    def matches(
        self,
        *,
        fact_id: str,
        fact_digest: str,
        workspace_identity_digest: str,
        goal_id: str,
        goal_revision: int,
    ) -> bool:
        return (
            self.fact_id == fact_id
            and self.fact_digest == fact_digest
            and self.workspace_identity_digest == workspace_identity_digest
            and self.goal_id == goal_id
            and self.goal_revision == goal_revision
            and self.binding_digest == self._expected_digest()
        )


@dataclass(frozen=True, slots=True)
class PreferenceAdmissionBinding:
    binding_id: str
    fact_id: str
    fact_digest: str
    content_digest: str
    binding_digest: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.binding_id,
                self.fact_id,
                self.fact_digest,
                self.content_digest,
                self.binding_digest,
            )
        ):
            raise ValueError("preference admission fields must not be empty")
        if self.binding_digest != self._expected_digest():
            raise ValueError("preference admission binding digest mismatch")

    def _expected_digest(self) -> str:
        return canonical_json_digest(
            {
                "binding_id": self.binding_id,
                "fact_id": self.fact_id,
                "fact_digest": self.fact_digest,
                "content_digest": self.content_digest,
                "origin": "explicit_user_confirmation",
            }
        )

    @classmethod
    def create(
        cls,
        *,
        binding_id: str,
        fact_id: str,
        fact_digest: str,
        content_digest: str,
    ) -> PreferenceAdmissionBinding:
        values = {
            "binding_id": binding_id,
            "fact_id": fact_id,
            "fact_digest": fact_digest,
            "content_digest": content_digest,
            "origin": "explicit_user_confirmation",
        }
        return cls(
            binding_id=binding_id,
            fact_id=fact_id,
            fact_digest=fact_digest,
            content_digest=content_digest,
            binding_digest=canonical_json_digest(values),
        )

    def matches(self, *, fact_id: str, fact_digest: str, content_digest: str) -> bool:
        return (
            self.fact_id == fact_id
            and self.fact_digest == fact_digest
            and self.content_digest == content_digest
            and self.binding_digest == self._expected_digest()
        )


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    family: str
    model: str
    canonical_destination: str
    trust_profile: str
    remote: bool

    def __post_init__(self) -> None:
        if not all(
            (
                self.family,
                self.model,
                self.canonical_destination,
                self.trust_profile,
            )
        ):
            raise ValueError("provider descriptor fields must not be empty")
        parts = urlsplit(self.canonical_destination)
        if (
            not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("provider destination must be canonical and non-secret")
        if self.remote and parts.scheme != "https":
            raise ValueError("remote provider destination must be canonical HTTPS")
        if not self.remote and parts.scheme not in {"http", "https"}:
            raise ValueError("local provider destination must be canonical HTTP(S)")
        host = parts.hostname.lower()
        if (
            not self.remote
            and parts.scheme == "http"
            and host
            not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }
        ):
            raise ValueError("plain HTTP is only canonical for loopback providers")
        netloc = f"[{host}]" if ":" in host else host
        if parts.port is not None:
            netloc = f"{netloc}:{parts.port}"
        path = parts.path.rstrip("/")
        canonical = urlunsplit((parts.scheme.lower(), netloc, path, "", ""))
        if self.canonical_destination != canonical:
            raise ValueError("provider destination must use canonical URL form")

    @property
    def identity_digest(self) -> str:
        return canonical_json_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class ProviderDisclosureReceipt:
    receipt_id: str
    request_digest: str
    acknowledged_action_seq: int
    acknowledged_at: str

    def __post_init__(self) -> None:
        if not self.receipt_id or not self.request_digest or not self.acknowledged_at:
            raise ValueError("provider disclosure receipt fields must not be empty")
        if self.acknowledged_action_seq < 1:
            raise ValueError("disclosure acknowledgement action sequence must be positive")


@dataclass(frozen=True, slots=True)
class ProviderDisclosureRequest:
    disclosure_id: str
    provider_descriptor_digest: str
    canonical_destination: str
    model: str
    data_classes: tuple[str, ...]
    request_digest: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.disclosure_id,
                self.provider_descriptor_digest,
                self.canonical_destination,
                self.model,
                self.request_digest,
            )
        ):
            raise ValueError("provider disclosure request fields must not be empty")
        if not self.data_classes or any(not item for item in self.data_classes):
            raise ValueError("provider disclosure data classes must not be empty")
        if tuple(sorted(set(self.data_classes))) != self.data_classes:
            raise ValueError("provider disclosure data classes must be sorted and unique")
        if self.request_digest != self._expected_digest():
            raise ValueError("provider disclosure request digest mismatch")

    def _expected_digest(self) -> str:
        return canonical_json_digest(
            {
                "disclosure_id": self.disclosure_id,
                "provider_descriptor_digest": self.provider_descriptor_digest,
                "canonical_destination": self.canonical_destination,
                "model": self.model,
                "data_classes": self.data_classes,
            }
        )

    @classmethod
    def create(
        cls,
        *,
        disclosure_id: str,
        provider_descriptor_digest: str,
        canonical_destination: str,
        model: str,
        data_classes: tuple[str, ...],
    ) -> ProviderDisclosureRequest:
        values = {
            "disclosure_id": disclosure_id,
            "provider_descriptor_digest": provider_descriptor_digest,
            "canonical_destination": canonical_destination,
            "model": model,
            "data_classes": tuple(sorted(set(data_classes))),
        }
        return cls(**values, request_digest=canonical_json_digest(values))

    def acknowledge(
        self,
        *,
        receipt_id: str,
        acknowledged_action_seq: int,
        acknowledged_at: str,
    ) -> ProviderDisclosureReceipt:
        return ProviderDisclosureReceipt(
            receipt_id=receipt_id,
            request_digest=self.request_digest,
            acknowledged_action_seq=acknowledged_action_seq,
            acknowledged_at=acknowledged_at,
        )


@dataclass(frozen=True, slots=True)
class ControlReceipt:
    correlation_id: str
    control_kind: str
    goal_id: str | None
    goal_revision: int | None
    accepted_state_revision: int
    payload_digest: str
    receipt_digest: str

    def __post_init__(self) -> None:
        if not self.correlation_id or not self.control_kind or not self.payload_digest:
            raise ValueError("control receipt identity and payload must not be empty")
        if self.accepted_state_revision < 0:
            raise ValueError("control receipt state revision must be non-negative")
        if (self.goal_id is None) != (self.goal_revision is None):
            raise ValueError("control receipt goal identity and revision must be paired")
        if self.goal_revision is not None and self.goal_revision < 1:
            raise ValueError("control receipt goal revision must be positive")
        if self.receipt_digest != self._expected_digest():
            raise ValueError("control receipt digest mismatch")

    def _expected_digest(self) -> str:
        return canonical_json_digest(
            {
                "correlation_id": self.correlation_id,
                "control_kind": self.control_kind,
                "goal_id": self.goal_id,
                "goal_revision": self.goal_revision,
                "accepted_state_revision": self.accepted_state_revision,
                "payload_digest": self.payload_digest,
            }
        )

    @classmethod
    def create(
        cls,
        *,
        correlation_id: str,
        control_kind: str,
        goal_id: str | None,
        goal_revision: int | None,
        accepted_state_revision: int,
        payload_digest: str,
    ) -> ControlReceipt:
        values = {
            "correlation_id": correlation_id,
            "control_kind": control_kind,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "accepted_state_revision": accepted_state_revision,
            "payload_digest": payload_digest,
        }
        return cls(**values, receipt_digest=canonical_json_digest(values))


class ControlRequestKind(StrEnum):
    PAUSE = "pause"
    CORRECT = "correct"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class ControlBinding:
    conversation_id: str
    goal_id: str
    goal_revision: int
    invocation_id: str

    def __post_init__(self) -> None:
        if not all((self.conversation_id, self.goal_id, self.invocation_id)):
            raise ValueError("control binding identity must not be empty")
        if self.goal_revision < 1:
            raise ValueError("control binding goal revision must be positive")


@dataclass(frozen=True, slots=True)
class ControlInboxRequest:
    request_id: str
    kind: ControlRequestKind
    conversation_id: str
    goal_id: str
    goal_revision: int
    invocation_id: str
    message: str | None = None

    def __post_init__(self) -> None:
        if not all((self.request_id, self.conversation_id, self.goal_id, self.invocation_id)):
            raise ValueError("control request identity must not be empty")
        if self.goal_revision < 1:
            raise ValueError("control request goal revision must be positive")
        if self.kind is ControlRequestKind.CORRECT:
            if self.message is None or not self.message.strip():
                raise ValueError("goal correction must contain the user's message")
        elif self.message is not None:
            raise ValueError("only a goal correction may carry a message")

    @property
    def payload_digest(self) -> str:
        return canonical_json_digest(
            {
                "request_id": self.request_id,
                "kind": self.kind,
                "conversation_id": self.conversation_id,
                "goal_id": self.goal_id,
                "goal_revision": self.goal_revision,
                "invocation_id": self.invocation_id,
                "message": self.message,
            }
        )


def _require_control_identity(correlation_id: str) -> None:
    if not correlation_id:
        raise ValueError("control correlation_id must not be empty")


@dataclass(frozen=True, slots=True)
class ClarificationRequest:
    correlation_id: str
    question: str
    boundary_code: str
    missing_fields: tuple[str, ...]
    safe_assumptions: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_control_identity(self.correlation_id)
        if not self.question.strip() or not self.boundary_code or not self.missing_fields:
            raise ValueError("clarification request must identify one missing boundary")
        if any(not item for item in (*self.missing_fields, *self.safe_assumptions)):
            raise ValueError("clarification fields must not contain empty values")
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))
        object.__setattr__(self, "safe_assumptions", tuple(self.safe_assumptions))


@dataclass(frozen=True, slots=True)
class GoalProposal:
    correlation_id: str
    goal_frame: GoalFrame

    def __post_init__(self) -> None:
        _require_control_identity(self.correlation_id)


@dataclass(frozen=True, slots=True)
class GoalProgress:
    correlation_id: str
    goal_id: str
    goal_revision: int
    summary: str
    next_step: str

    def __post_init__(self) -> None:
        _require_control_identity(self.correlation_id)
        if not self.goal_id or not self.summary.strip() or not self.next_step.strip():
            raise ValueError("goal progress fields must not be empty")
        if self.goal_revision < 1:
            raise ValueError("goal progress revision must be positive")


@dataclass(frozen=True, slots=True)
class GoalDeltaProposal:
    correlation_id: str
    delta: GoalDelta

    def __post_init__(self) -> None:
        _require_control_identity(self.correlation_id)


@dataclass(frozen=True, slots=True)
class BlockedClaim:
    correlation_id: str
    goal_id: str
    goal_revision: int
    blocker: str
    safe_attempts: tuple[str, ...]
    resume_condition: str

    def __post_init__(self) -> None:
        _require_control_identity(self.correlation_id)
        if not self.goal_id or not self.blocker.strip() or not self.resume_condition.strip():
            raise ValueError("blocked claim fields must not be empty")
        if self.goal_revision < 1:
            raise ValueError("blocked claim revision must be positive")
        if any(not item for item in self.safe_attempts):
            raise ValueError("safe attempts must not contain empty values")
        object.__setattr__(self, "safe_attempts", tuple(self.safe_attempts))


ModelControlBlock: TypeAlias = (
    ClarificationRequest
    | GoalProposal
    | GoalProgress
    | GoalDeltaProposal
    | CompletionClaim
    | BlockedClaim
)

_MODEL_CONTROL_TYPES = (
    ClarificationRequest,
    GoalProposal,
    GoalProgress,
    GoalDeltaProposal,
    CompletionClaim,
    BlockedClaim,
)

# 模型上报控制信号的唯一保留名。控制面与产品工具面在 wire 上同形但语义隔离：
# 该名字永远不得注册为产品工具，也不得出现在 ContextPack.tools 里。
RESERVED_CONTROL_NAME = "first_agent_control_v1"


@dataclass(frozen=True, slots=True)
class ConversationFact:
    fact_id: str
    kind: FactKind
    content: dict[str, JSONValue]

    def __post_init__(self) -> None:
        if not self.fact_id:
            raise ValueError("fact_id must not be empty")
        _assert_json_compatible(self.content, path="fact.content")
        object.__setattr__(self, "content", _freeze_json_dict(self.content))


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    request_id: str
    run_id: str
    tool_call_id: str
    binding_digest: str
    preview: str
    tool_name: str | None = None
    state_revision: int | None = None
    arguments_digest: str | None = None
    policy_identity: str | None = None
    risk: str | None = None
    side_effect: str | None = None
    target_digest: str | None = None
    precondition_digest: str | None = None
    new_content_digest: str | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.request_id,
                self.run_id,
                self.tool_call_id,
                self.binding_digest,
                self.preview,
            )
        ):
            raise ValueError("approval request identity and preview must not be empty")
        if self.state_revision is not None and self.state_revision < 0:
            raise ValueError("approval state_revision must be non-negative")


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    request_id: str
    run_id: str
    tool_call_id: str
    binding_digest: str
    summary: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.request_id,
                self.run_id,
                self.tool_call_id,
                self.binding_digest,
                self.summary,
            )
        ):
            raise ValueError("recovery request fields must not be empty")


PendingRequest: TypeAlias = ApprovalRequest | RecoveryRequest


@dataclass(frozen=True, slots=True)
class ExecutingIntentRecord:
    tool_call_id: str
    intent_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.tool_call_id or not self.intent_digest or not self.idempotency_key:
            raise ValueError("executing intent fields must not be empty")


@dataclass(frozen=True, slots=True)
class ActiveRun:
    run_id: str
    status: ActiveRunStatus = ActiveRunStatus.RUNNABLE
    phase: ContinuationPhase = ContinuationPhase.MODEL
    owner_invocation_id: str | None = None
    batch_cursor: int = 0
    pending_request: PendingRequest | None = None
    executing_intent: ExecutingIntentRecord | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    approval_grant: ApprovalGrant | None = None
    approved_request_ids: tuple[str, ...] = ()
    rejected_request_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must not be empty")
        if self.batch_cursor < 0:
            raise ValueError("batch_cursor must be non-negative")
        if self.owner_invocation_id == "":
            raise ValueError("owner_invocation_id must not be empty")

        call_ids = tuple(call.tool_call_id for call in self.tool_calls)
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("tool_call_id must be unique within an active batch")
        if self.phase is ContinuationPhase.MODEL:
            if self.tool_calls or self.executing_intent is not None:
                raise ValueError("MODEL phase cannot retain a tool batch or executing intent")
        else:
            if not self.tool_calls or self.batch_cursor >= len(self.tool_calls):
                raise ValueError("TOOL/EXECUTING phase requires a valid current tool call")
            current_call = self.tool_calls[self.batch_cursor]
            if self.phase is ContinuationPhase.TOOL:
                if self.executing_intent is not None:
                    raise ValueError("TOOL phase cannot retain an executing intent")
            elif (
                self.executing_intent is None
                or self.executing_intent.tool_call_id != current_call.tool_call_id
            ):
                raise ValueError("EXECUTING phase must bind the current tool call")

        if self.status is ActiveRunStatus.AWAITING_APPROVAL:
            pending = self.pending_request
            if (
                self.phase is not ContinuationPhase.TOOL
                or not isinstance(pending, ApprovalRequest)
                or pending.run_id != self.run_id
                or pending.tool_call_id != self.tool_calls[self.batch_cursor].tool_call_id
                or self.owner_invocation_id is not None
            ):
                raise ValueError("AWAITING_APPROVAL must bind the current tool call")
        elif self.status is ActiveRunStatus.AWAITING_RECOVERY:
            pending = self.pending_request
            intent = self.executing_intent
            if (
                self.phase is not ContinuationPhase.EXECUTING
                or not isinstance(pending, RecoveryRequest)
                or intent is None
                or pending.run_id != self.run_id
                or pending.tool_call_id != intent.tool_call_id
                or pending.binding_digest != intent.intent_digest
                or self.owner_invocation_id is not None
            ):
                raise ValueError("AWAITING_RECOVERY must bind the executing intent")
        elif self.status is ActiveRunStatus.AWAITING_DISCLOSURE:
            if (
                self.phase is not ContinuationPhase.MODEL
                or self.pending_request is not None
                or self.owner_invocation_id is not None
            ):
                raise ValueError("AWAITING_DISCLOSURE must pause before a model send")
        elif self.pending_request is not None:
            raise ValueError("only awaiting states may retain a pending request")

        if self.status in {ActiveRunStatus.PAUSED_LIMIT, ActiveRunStatus.PAUSED_RETRYABLE}:
            if self.owner_invocation_id is not None:
                raise ValueError("paused runs cannot retain an invocation owner")
            if self.phase is ContinuationPhase.EXECUTING:
                raise ValueError("unknown tool outcomes must use AWAITING_RECOVERY")

        approved = self.approved_request_ids
        rejected = self.rejected_request_ids
        if any(not request_id for request_id in (*approved, *rejected)):
            raise ValueError("resolved request IDs must not be empty")
        if len(set(approved)) != len(approved) or len(set(rejected)) != len(rejected):
            raise ValueError("resolved request IDs must be unique")
        if set(approved) & set(rejected):
            raise ValueError("a request cannot be both approved and rejected")
        if self.approval_grant is not None and (
            self.status is not ActiveRunStatus.RUNNABLE
            or self.phase is not ContinuationPhase.TOOL
            or self.approval_grant.request_id not in approved
        ):
            raise ValueError("approval grant requires a matching runnable TOOL phase")


@dataclass(frozen=True, slots=True)
class RecordedRunResult:
    status: RunStatus
    run_id: str | None = None
    message: str | None = None
    request_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    action_seq: int
    action_digest: str
    result: RecordedRunResult | None = None

    def __post_init__(self) -> None:
        if self.action_seq < 1 or not self.action_digest:
            raise ValueError("replay record identity must be valid")


@dataclass(frozen=True, slots=True)
class ConversationState:
    conversation_id: str
    revision: int = 0
    next_action_seq: int = 1
    replay_floor: int = 1
    replay_records: tuple[ReplayRecord, ...] = ()
    facts: tuple[ConversationFact, ...] = ()
    active_run: ActiveRun | None = None
    last_safe_result: RecordedRunResult | None = None
    goal: GoalFrame | None = None
    goal_authorizations: tuple[GoalAuthorizationBinding, ...] = ()
    evidence_records: tuple[EvidenceRecord, ...] = ()
    completion_claim: CompletionClaim | None = None
    interaction_state: InteractionState = InteractionState.IDLE
    provider_disclosure_request: ProviderDisclosureRequest | None = None
    provider_disclosure_receipt: ProviderDisclosureReceipt | None = None
    control_receipts: tuple[ControlReceipt, ...] = ()

    def __post_init__(self) -> None:
        if not self.conversation_id:
            raise ValueError("conversation_id must not be empty")
        if self.revision < 0:
            raise ValueError("revision must be non-negative")
        if self.next_action_seq < 1:
            raise ValueError("next_action_seq must be positive")
        if self.replay_floor < 1 or self.replay_floor > self.next_action_seq:
            raise ValueError("replay_floor must be within the processed sequence range")

        fact_ids = tuple(fact.fact_id for fact in self.facts)
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("fact_id must be unique within a conversation")
        replay_sequences = tuple(record.action_seq for record in self.replay_records)
        if replay_sequences != tuple(sorted(replay_sequences)):
            raise ValueError("replay records must be ordered by action_seq")
        if len(set(replay_sequences)) != len(replay_sequences):
            raise ValueError("replay action_seq must be unique")
        if any(
            sequence < self.replay_floor or sequence >= self.next_action_seq
            for sequence in replay_sequences
        ):
            raise ValueError("replay action_seq is outside the retained sequence window")

        evidence_ids = tuple(record.evidence_id for record in self.evidence_records)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence_id must be unique within a conversation")
        if self.goal is None:
            if (
                self.goal_authorizations
                or self.evidence_records
                or self.completion_claim is not None
            ):
                raise ValueError("goal authority, evidence and completion claim require a goal")
        else:
            binding_ids = tuple(binding.binding_id for binding in self.goal_authorizations)
            if len(set(binding_ids)) != len(binding_ids) or any(
                not binding.authorizes(
                    goal_id=self.goal.goal_id,
                    goal_revision=self.goal.revision,
                    workspace_identity_digest=self.goal.workspace_identity_digest,
                    operation=binding.operation,
                    normalized_target=binding.normalized_target,
                )
                for binding in self.goal_authorizations
            ):
                raise ValueError("goal authorization must bind the current goal exactly")
            if any(
                record.goal_id != self.goal.goal_id or record.goal_revision != self.goal.revision
                for record in self.evidence_records
            ):
                raise ValueError("evidence must bind the current goal revision")
            if self.completion_claim is not None and (
                self.completion_claim.goal_id != self.goal.goal_id
                or self.completion_claim.goal_revision != self.goal.revision
                or not set(self.completion_claim.criterion_evidence_refs).issubset(evidence_ids)
            ):
                raise ValueError("completion claim must bind current goal evidence")
            if self.goal.status is GoalStatus.VERIFIED_DONE:
                if self.completion_claim is None:
                    raise ValueError("VERIFIED_DONE requires a current completion claim")
                if self.active_run is not None and (
                    self.active_run.phase is ContinuationPhase.EXECUTING
                    or self.active_run.status is ActiveRunStatus.AWAITING_RECOVERY
                ):
                    raise ValueError("VERIFIED_DONE cannot coexist with an unknown effect")
                mandatory = tuple(
                    criterion for criterion in self.goal.admitted_criteria if criterion.mandatory
                )
                claimed_evidence_ids = set(self.completion_claim.criterion_evidence_refs)
                evidence_by_criterion = {
                    record.criterion_id: record
                    for record in self.evidence_records
                    if record.evidence_id in claimed_evidence_ids
                }
                if not mandatory or any(
                    criterion.criterion_id not in evidence_by_criterion
                    or not evidence_by_criterion[criterion.criterion_id].passed
                    or evidence_by_criterion[criterion.criterion_id].oracle_kind
                    is not criterion.oracle_kind
                    or evidence_by_criterion[criterion.criterion_id].predicate_digest
                    != canonical_json_digest(criterion.predicate)
                    for criterion in mandatory
                ):
                    raise ValueError(
                        "VERIFIED_DONE requires current passing evidence for every "
                        "mandatory criterion"
                    )
        object.__setattr__(self, "evidence_records", tuple(self.evidence_records))
        object.__setattr__(self, "goal_authorizations", tuple(self.goal_authorizations))
        if not isinstance(self.interaction_state, InteractionState):
            raise ValueError("interaction_state must be a closed value")
        if self.provider_disclosure_receipt is not None and (
            self.provider_disclosure_request is None
            or self.provider_disclosure_receipt.request_digest
            != self.provider_disclosure_request.request_digest
        ):
            raise ValueError("provider disclosure receipt must bind the current request")
        correlation_ids = tuple(receipt.correlation_id for receipt in self.control_receipts)
        if len(set(correlation_ids)) != len(correlation_ids):
            raise ValueError("control receipt correlation_id must be unique")
        object.__setattr__(self, "control_receipts", tuple(self.control_receipts))

    @classmethod
    def new(cls, conversation_id: str) -> ConversationState:
        return cls(conversation_id=conversation_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeAction:
    conversation_id: str
    action_seq: int
    expected_revision: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SubmitMessage(RuntimeAction):
    run_id: str
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveApproval(RuntimeAction):
    request_id: str
    binding_digest: str
    approved: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveUnknownToolOutcome(RuntimeAction):
    request_id: str
    binding_digest: str
    resolution: RecoveryResolution


@dataclass(frozen=True, slots=True, kw_only=True)
class Resume(RuntimeAction):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelRun(RuntimeAction):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class AcknowledgeProviderDisclosure(RuntimeAction):
    request_digest: str
    acknowledged_at: str

    def __post_init__(self) -> None:
        if not self.request_digest or not self.acknowledged_at:
            raise ValueError("provider disclosure acknowledgement fields must not be empty")


def _validate_goal_action(goal_id: str, goal_revision: int) -> None:
    if not goal_id:
        raise ValueError("goal action must bind a goal")
    if goal_revision < 1:
        raise ValueError("goal action revision must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectGoal(RuntimeAction):
    goal_id: str

    def __post_init__(self) -> None:
        if not self.goal_id:
            raise ValueError("select goal action must bind a goal")


@dataclass(frozen=True, slots=True, kw_only=True)
class PauseGoal(RuntimeAction):
    goal_id: str
    goal_revision: int

    def __post_init__(self) -> None:
        _validate_goal_action(self.goal_id, self.goal_revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumeGoal(RuntimeAction):
    goal_id: str
    goal_revision: int

    def __post_init__(self) -> None:
        _validate_goal_action(self.goal_id, self.goal_revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelGoal(RuntimeAction):
    goal_id: str
    goal_revision: int

    def __post_init__(self) -> None:
        _validate_goal_action(self.goal_id, self.goal_revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfirmCriterion(RuntimeAction):
    goal_id: str
    goal_revision: int
    criterion_id: str
    admission_binding_digest: str
    confirmed: bool

    def __post_init__(self) -> None:
        _validate_goal_action(self.goal_id, self.goal_revision)
        if not self.criterion_id or not self.admission_binding_digest:
            raise ValueError("criterion confirmation fields must not be empty")


Action: TypeAlias = (
    SubmitMessage
    | ResolveApproval
    | ResolveUnknownToolOutcome
    | Resume
    | CancelRun
    | AcknowledgeProviderDisclosure
    | SelectGoal
    | PauseGoal
    | ResumeGoal
    | CancelGoal
    | ConfirmCriterion
)


def canonical_action_digest(action: Action) -> str:
    payload = {
        "type": type(action).__name__,
        "payload": _canonical_json_value(asdict(action)),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ActionTransition:
    disposition: ActionDisposition
    state: ConversationState
    reason: str | None = None
    recorded_result: RecordedRunResult | None = None


@dataclass(frozen=True, slots=True)
class LoadedSnapshot:
    state: ConversationState
    token: str


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    state: ConversationState
    run_id: str | None = None
    message: str | None = None
    request: PendingRequest | None = None
    replayed: bool = False
    error_code: str | None = None
    delivery_warnings: tuple[str, ...] = ()


class RuntimeEventKind(StrEnum):
    MODEL_PROGRESS = "model_progress"
    TOOL_REQUESTED = "tool_requested"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUESTED = "approval_requested"
    RECOVERY_REQUESTED = "recovery_requested"
    DISCLOSURE_REQUESTED = "disclosure_requested"
    LIMIT_REACHED = "limit_reached"
    WARNING = "warning"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    event_id: str
    kind: RuntimeEventKind
    conversation_id: str
    run_id: str | None
    revision: int | None
    causation_id: str
    payload: dict[str, JSONValue] = field(default_factory=dict)
    advisory: bool = False

    def __post_init__(self) -> None:
        _assert_json_compatible(self.payload, path="event.payload")
        object.__setattr__(self, "payload", _freeze_json_dict(self.payload))


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: str
    content: tuple[dict[str, JSONValue], ...]

    def __post_init__(self) -> None:
        _assert_json_compatible(self.content, path="model_message.content")
        object.__setattr__(
            self,
            "content",
            tuple(_freeze_json_dict(block) for block in self.content),
        )


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, JSONValue]
    # 生产路径总是由 ToolSpec.definition() 显式声明;默认 READ_ONLY 只覆盖
    # 手工构造的只读 fixture,effectful 工具必须显式声明才可能通过 loop 的 Goal 门。
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY

    def __post_init__(self) -> None:
        _assert_json_compatible(self.input_schema, path="tool_definition.input_schema")
        object.__setattr__(self, "input_schema", _freeze_json_dict(self.input_schema))


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    version: str
    description: str
    input_schema: dict[str, JSONValue]
    risk: ToolRisk
    side_effect: SideEffectClass
    output_policy: OutputPolicy
    approval_policy: ApprovalPolicy
    safety_policy: dict[str, JSONValue]
    output_limit_chars: int

    def __post_init__(self) -> None:
        if not self.name or not self.version or not self.description:
            raise ValueError("tool name, version, and description must not be empty")
        if self.output_limit_chars < 1:
            raise ValueError("output_limit_chars must be positive")
        _assert_json_compatible(self.input_schema, path="tool_spec.input_schema")
        _assert_json_compatible(self.safety_policy, path="tool_spec.safety_policy")
        object.__setattr__(self, "input_schema", _freeze_json_dict(self.input_schema))
        object.__setattr__(self, "safety_policy", _freeze_json_dict(self.safety_policy))

    @property
    def identity_digest(self) -> str:
        payload = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "input_schema": self.input_schema,
            "risk": self.risk.value,
            "side_effect": self.side_effect.value,
            "output_policy": self.output_policy.value,
            "approval_policy": self.approval_policy.value,
            "safety_policy": self.safety_policy,
            "output_limit_chars": self.output_limit_chars,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            side_effect=self.side_effect,
        )


@dataclass(frozen=True, slots=True)
class BudgetReport:
    input_limit: int
    estimated_input_tokens: int
    output_reserve: int
    included_ids: tuple[str, ...] = ()
    excluded_ids: tuple[str, ...] = ()
    clipped_ids: tuple[str, ...] = ()
    source_digests: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextSourceLimits:
    """ContextManager 在 build 时告知每个 source 的独立预算上限。"""

    max_tokens: int
    max_items: int

    def __post_init__(self) -> None:
        if self.max_tokens < 0 or self.max_items < 0:
            raise ValueError("source limits must be non-negative")


@dataclass(frozen=True, slots=True)
class ContextQuery:
    """ContextManager 向 source 提出的只读查询。不含 provider/tool/checkpoint 引用。"""

    conversation_id: str
    run_id: str
    user_text: str
    workspace_scope_digest: str
    source_limits: ContextSourceLimits


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    """source 返回的不可变召回候选。content 是 bounded text，不带 system/pinned 权威。"""

    candidate_id: str
    source_name: str
    workspace_scope_digest: str
    content: str
    content_digest: str
    provenance: dict[str, JSONValue] = field(default_factory=dict)
    rank_key: str = ""

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.source_name or not self.workspace_scope_digest:
            raise ValueError("candidate identity fields must not be empty")
        _assert_json_compatible(self.provenance, path="candidate.provenance")
        object.__setattr__(self, "provenance", _freeze_json_dict(self.provenance))


@dataclass(frozen=True, slots=True)
class ContextSourceSnapshot:
    """source 的一次 revision-consistent 不可变快照。payload 只能是候选。"""

    source_name: str
    revision: int
    snapshot_digest: str
    candidates: tuple[ContextCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_name or not self.snapshot_digest:
            raise ValueError("snapshot identity fields must not be empty")
        if self.revision < 0:
            raise ValueError("snapshot revision must be non-negative")
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(set(ids)) != len(ids):
            raise ValueError("candidate ids must be unique within a snapshot")


@dataclass(frozen=True, slots=True)
class ContextPack:
    system: str
    messages: tuple[ModelMessage, ...]
    tools: tuple[ToolDefinition, ...]
    budget: BudgetReport
    # 控制面下行 seam：schema 与已受理回执以独立字段携带，由各 provider adapter
    # 自行翻译到自家 wire 形状，绝不伪装成产品 tools 或摊平成普通文本。
    control_schema: dict[str, JSONValue] | None = None
    control_receipts: tuple[ControlReceipt, ...] = ()
    data_classes: tuple[str, ...] = ()
    goal_bootstrap: GoalBootstrap | None = None

    def __post_init__(self) -> None:
        if self.control_schema is not None:
            if not isinstance(self.control_schema, dict):
                raise TypeError("control schema must be a JSON object")
            name = self.control_schema.get("name")
            description = self.control_schema.get("description")
            if not isinstance(name, str) or not name:
                raise ValueError("control schema name must not be empty")
            if not isinstance(description, str) or not description.strip():
                raise ValueError("control schema description must not be empty")
            if not isinstance(self.control_schema.get("input_schema"), dict):
                raise ValueError("control schema input_schema must be a JSON object")
            if any(tool.name == name for tool in self.tools):
                raise ValueError("control schema name must not collide with product tools")
            _assert_json_compatible(self.control_schema, path="context_pack.control_schema")
            object.__setattr__(self, "control_schema", _freeze_json_dict(self.control_schema))
        if any(not isinstance(receipt, ControlReceipt) for receipt in self.control_receipts):
            raise TypeError("control receipts must all be ControlReceipt")
        object.__setattr__(self, "control_receipts", tuple(self.control_receipts))
        if tuple(sorted(set(self.data_classes))) != self.data_classes:
            raise ValueError("context data_classes must be sorted and unique")
        if any(not item for item in self.data_classes):
            raise ValueError("context data_classes must not contain empty values")
        object.__setattr__(self, "data_classes", tuple(self.data_classes))
        if self.goal_bootstrap is not None and not isinstance(
            self.goal_bootstrap, GoalBootstrap
        ):
            raise TypeError("goal_bootstrap must be GoalBootstrap")


@dataclass(frozen=True, slots=True)
class ModelTextBlock:
    text: str


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    tool_call_id: str
    name: str
    arguments: dict[str, JSONValue]

    def __post_init__(self) -> None:
        if not self.tool_call_id or not self.name:
            raise ValueError("model tool call identity must not be empty")
        _assert_json_compatible(self.arguments, path="tool_call.arguments")
        object.__setattr__(self, "arguments", _freeze_json_dict(self.arguments))


@dataclass(frozen=True, slots=True)
class ModelResponse:
    blocks: tuple[ModelTextBlock | ModelToolCall, ...]
    control: ModelControlBlock | None = None
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", tuple(self.blocks))
        if any(not isinstance(block, ModelTextBlock | ModelToolCall) for block in self.blocks):
            raise TypeError("model response blocks must be text or tool calls")
        if self.control is not None and not isinstance(self.control, _MODEL_CONTROL_TYPES):
            raise TypeError("model response control must be one closed control variant")
        if self.control is not None and any(
            isinstance(block, ModelToolCall) for block in self.blocks
        ):
            raise ValueError("model control cannot be combined with callable tool calls")
        for label, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{label} must be non-negative")

    @property
    def bounded_output_tokens(self) -> int:
        """始终以响应 bytes 下界钳住 provider 自报 usage，防止少报绕过预算。"""

        payload = []
        for block in self.blocks:
            if isinstance(block, ModelTextBlock):
                payload.append({"type": "text", "text": block.text})
            else:
                payload.append(
                    {
                        "type": "tool_call",
                        "tool_call_id": block.tool_call_id,
                        "name": block.name,
                        "arguments": block.arguments,
                    }
                )
        if self.control is not None:
            payload.append(
                {
                    "type": "control",
                    "name": type(self.control).__name__,
                    "payload": _canonical_json_value(asdict(self.control)),
                }
            )
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return max(self.output_tokens or 0, 1, len(encoded))


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool_call_id: str
    name: str
    arguments: dict[str, JSONValue]

    def __post_init__(self) -> None:
        if not self.tool_call_id or not self.name:
            raise ValueError("tool call identity must not be empty")
        _assert_json_compatible(self.arguments, path="tool_call.arguments")
        object.__setattr__(self, "arguments", _freeze_json_dict(self.arguments))


@dataclass(frozen=True, slots=True)
class ToolPrepareContext:
    conversation_id: str
    run_id: str
    state_revision: int
    goal_id: str | None = None
    goal_revision: int | None = None
    workspace_identity_digest: str | None = None
    goal_authorization: GoalAuthorizationBinding | None = None
    fact_admission: FactAdmissionBinding | None = None
    preference_admission: PreferenceAdmissionBinding | None = None

    def __post_init__(self) -> None:
        goal_fields = (
            self.goal_id,
            self.goal_revision,
            self.workspace_identity_digest,
        )
        if any(value is not None for value in goal_fields) and not all(
            value is not None for value in goal_fields
        ):
            raise ValueError("tool context goal identity must be complete")
        if self.goal_revision is not None and self.goal_revision < 1:
            raise ValueError("tool context goal revision must be positive")
        if self.goal_authorization is not None and (
            self.goal_id is None
            or not self.goal_authorization.authorizes(
                goal_id=self.goal_id,
                goal_revision=self.goal_revision,
                workspace_identity_digest=self.workspace_identity_digest,
                operation=self.goal_authorization.operation,
                normalized_target=self.goal_authorization.normalized_target,
            )
        ):
            raise ValueError("tool context authorization is stale")
        if self.fact_admission is not None and (
            self.goal_id is None
            or not self.fact_admission.matches(
                    fact_id=self.fact_admission.fact_id,
                    fact_digest=self.fact_admission.fact_digest,
                    workspace_identity_digest=self.workspace_identity_digest,
                    goal_id=self.goal_id,
                    goal_revision=self.goal_revision,
            )
        ):
            raise ValueError("tool context fact admission is stale")


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    request_id: str
    binding_digest: str

    def __post_init__(self) -> None:
        if not self.request_id or not self.binding_digest:
            raise ValueError("approval grant fields must not be empty")


@dataclass(frozen=True, slots=True)
class ExecutionIntent:
    tool_call_id: str
    tool_name: str
    tool_identity: str
    arguments: dict[str, JSONValue]
    arguments_digest: str
    intent_digest: str
    idempotency_key: str
    policy_identity: str
    conversation_id: str
    run_id: str
    side_effect: SideEffectClass
    safety_binding: dict[str, JSONValue] = field(default_factory=dict)
    goal_id: str | None = None
    goal_revision: int | None = None
    workspace_identity_digest: str | None = None
    goal_authorization: GoalAuthorizationBinding | None = None
    fact_admission: FactAdmissionBinding | None = None
    preference_admission: PreferenceAdmissionBinding | None = None

    def __post_init__(self) -> None:
        if not self.conversation_id or not self.run_id:
            raise ValueError("execution intent origin identity must be valid")
        _assert_json_compatible(self.arguments, path="execution_intent.arguments")
        _assert_json_compatible(self.safety_binding, path="execution_intent.safety_binding")
        object.__setattr__(self, "arguments", _freeze_json_dict(self.arguments))
        object.__setattr__(self, "safety_binding", _freeze_json_dict(self.safety_binding))
        goal_fields = (self.goal_id, self.goal_revision, self.workspace_identity_digest)
        if any(value is not None for value in goal_fields) and not all(
            value is not None for value in goal_fields
        ):
            raise ValueError("execution intent goal identity must be complete")


@dataclass(frozen=True, slots=True)
class ApprovalRequired:
    request: ApprovalRequest


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
    executed: bool = True
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _assert_json_compatible(self.metadata, path="tool_result.metadata")
        object.__setattr__(self, "metadata", _freeze_json_dict(self.metadata))


@dataclass(frozen=True, slots=True)
class KnownNotExecuted:
    """executor 在证明 effect 未发生后返回的显式结果。

    与 unknown outcome（WRITE/EXTERNAL 抛出的异常，进入 recovery）相对：
    known-not-executed 证明副作用没有发生，作为普通 tool result 推进游标，
    允许模型修正。见 roadmap 的 invocation outcome taxonomy。
    """

    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code or not self.message:
            raise ValueError("KnownNotExecuted code and message must not be empty")


@dataclass(frozen=True, slots=True)
class KnownExecutedError:
    """executor 在 effect 已发生后返回的明确失败（远端 isError、unsupported content、
    child nonterminal 等）。映射为 ``executed=True, is_error=True`` 的 Tool Result，
    不能被展平为 success 字符串；unclassified 外部失败仍为 unknown（A18/R27）。
    """

    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code or not self.message:
            raise ValueError("KnownExecutedError code and message must not be empty")


ToolPreparation: TypeAlias = ExecutionIntent | ApprovalRequired | ToolResult

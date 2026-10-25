"""Agent Runtime Kernel 的不可变叶子合同。

这个模块只描述跨边界传递的数据，不拥有循环、持久化、工具执行或适配器行为。
保持它只依赖标准库，是防止新 Kernel 再次长成 service locator 的第一道边界。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from enum import Enum, StrEnum
from pathlib import Path
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
    MODEL_EXECUTING = "model_executing"
    MODEL_OUTCOME_UNKNOWN = "model_outcome_unknown"
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


class ToolExposure(StrEnum):
    MODEL = "model"
    OPERATOR = "operator"


class InvocationOrigin(StrEnum):
    MODEL = "model"
    OPERATOR = "operator"


class SideEffectClass(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    EXTERNAL = "external"


class EgressClass(StrEnum):
    NONE = "none"
    PUBLIC_NETWORK = "public_network"
    # 017：sandbox 的受治理出口（OFF 之外的 PACKAGE_REGISTRY/EXACT_ALLOWLIST 都
    # 只能经 internal-only network + project-owned CONNECT proxy）。
    GOVERNED_NETWORK = "governed_network"


class ExecutionAuthorityClass(StrEnum):
    """与 EgressClass 正交的 closed 执行权威。

    现有静态工具（file/Web/Memory/Skill/MCP/SubAgent 等）投影 ``IN_PROCESS``：它们仍
    由各自 side-effect/egress policy 治理，但不授予一个新的 same-UID OS process。只有
    ``local_process`` 使用 ``LOCAL_SAME_UID_PROCESS``，Policy 必须要求 exact informed
    approval。该成员进入 ToolSpec/intent/executing-record identity，不得从 SideEffectClass
    或 EgressClass 推断，也不允许运行时 optional fallback。

    017：``sandbox_exec`` 系列投影 ``ISOLATED_SANDBOX``——命令只在 qualified
    Docker 隔离 environment 内执行；GOVERNED_NETWORK egress 仍需各自的 exact
    approval（spec §3.1/§4.4）。
    """

    IN_PROCESS = "in_process"
    LOCAL_SAME_UID_PROCESS = "local_same_uid_process"
    ISOLATED_SANDBOX = "isolated_sandbox"
    # 018：browser session 内的受治理 effect；lease 由 ToolRuntime approval
    # 铸造，adapter 只消费 typed lease 绑定。
    BROWSER_SESSION = "browser_session"


class SourceKind(StrEnum):
    HISTORY_EXCERPT = "history_excerpt"
    HISTORY_GOAL = "history_goal"
    HISTORY_EVIDENCE = "history_evidence"
    WORKSPACE_PATH = "workspace_path"
    WORKSPACE_EXCERPT = "workspace_excerpt"
    WEB_SEARCH_SNIPPET = "web_search_snippet"
    WEB_EXTRACTED_CONTENT = "web_extracted_content"


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
    # 020 长会话压缩：模型生成的对话 summary 只能作为 untrusted context fact
    # 进入状态，不替代任何 canonical authority。
    CONTEXT_SUMMARY = "context_summary"


class GoalStatus(StrEnum):
    GOAL_READY = "goal_ready"
    EXECUTING = "executing"
    NEEDS_AUTHORITY = "needs_authority"
    PAUSED = "paused"
    BLOCKED = "blocked"
    VERIFIED_DONE = "verified_done"
    CANCELLED = "cancelled"


# 终态 goal 集合的单源（LOW 跟进轮 2026-10-25：此前 actions/sessions/render
# 各自内联同一集合，漂移风险由对抗验证指出）。cancel_goal/new_session_gate/
# archived 汇总/FAILED_FATAL 恢复句共用同一语义。
TERMINAL_GOAL_STATUSES = frozenset(
    {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}
)


class InteractionState(StrEnum):
    IDLE = "idle"
    ANSWERING = "answering"
    CLARIFYING = "clarifying"


class EvidenceOracleKind(StrEnum):
    FILESYSTEM_DIGEST = "filesystem_digest"
    TOOL_RECEIPT = "tool_receipt"
    USER_CONFIRMATION = "user_confirmation"
    RESEARCH_PROVENANCE = "research_provenance"
    WEB_SOURCE_RECEIPT = "web_source_receipt"
    # 018：durable browser action receipt + 同 session 之后的新鲜
    # browser_observe readback 才能推导；页面成功文案/prose 不是证据。
    BROWSER_READBACK = "browser_readback"


class AuthoritySourceKind(StrEnum):
    USER_FACT = "user_fact"
    HUMAN_ACTION = "human_action"
    HUMAN_APPROVAL = "human_approval"
    DURABLE_GRANT = "durable_grant"


class GoalAuthorizationScope(StrEnum):
    EXACT_FILE = "exact_file"
    DIRECTORY = "directory"


class FactAdmissionClass(StrEnum):
    WORKSPACE_FACT = "workspace_fact"
    VERIFIED_DERIVED_NOTE = "verified_derived_note"


@dataclass(frozen=True, slots=True)
class ProposedCriterion:
    criterion_id: str
    description: str
    # 模型只能结构化提出所需 oracle 与 artifact path；它不能提供期望 digest。
    # filesystem 的 ``None`` 表示建 Goal 时尚未读取工作区，需在用户批准第一笔
    # 具体文件写入时由 Runtime 绑定；绑定前不能满足 artifact completion。
    oracle_kind: EvidenceOracleKind | None = None
    artifact_path: str | None = None

    def __post_init__(self) -> None:
        if not self.criterion_id or not self.description.strip():
            raise ValueError("proposed criterion identity and description must not be empty")
        if self.oracle_kind is not None and not isinstance(
            self.oracle_kind, EvidenceOracleKind
        ):
            raise TypeError("proposed criterion oracle_kind must be EvidenceOracleKind")
        if self.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST:
            path = self.artifact_path
            if path is not None and not _is_safe_relative_artifact_path(path):
                raise ValueError(
                    "filesystem proposed criterion requires a safe workspace-relative "
                    "artifact_path"
                )
        elif self.artifact_path is not None:
            raise ValueError(
                "artifact_path is only valid for a filesystem_digest proposed criterion"
            )


@dataclass(frozen=True, slots=True)
class CitationV1:
    marker: str
    source_id: str
    receipt_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.marker, str)
            or not 3 <= len(self.marker) <= 32
            or not self.marker.startswith("[")
            or not self.marker.endswith("]")
            or any(
                not (character.isascii() and (character.isalnum() or character in "_-"))
                for character in self.marker[1:-1]
            )
        ):
            raise ValueError("citation marker is malformed")
        if (
            not isinstance(self.source_id, str)
            or not self.source_id.startswith("source:v1:")
            or not _is_lower_hex(self.source_id[len("source:v1:") :], length=64)
        ):
            raise ValueError("citation source_id is malformed")
        if not isinstance(self.receipt_digest, str) or not _is_lower_hex(
            self.receipt_digest, length=64
        ):
            raise ValueError("citation receipt digest is malformed")


@dataclass(frozen=True, slots=True)
class CitationManifestV1:
    schema_version: int
    artifact_path: str
    artifact_sha256: str
    goal_id: str
    goal_revision: int
    citations: tuple[CitationV1, ...]
    manifest_digest: str

    @classmethod
    def create(
        cls,
        *,
        artifact_path: str,
        artifact_sha256: str,
        goal_id: str,
        goal_revision: int,
        citations: tuple[CitationV1, ...],
    ) -> CitationManifestV1:
        values = {
            "schema_version": 1,
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha256,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "citations": [asdict(citation) for citation in citations],
        }
        return cls(
            schema_version=1,
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
            goal_id=goal_id,
            goal_revision=goal_revision,
            citations=citations,
            manifest_digest=canonical_json_digest(values),
        )

    @classmethod
    def from_json(cls, raw: str) -> CitationManifestV1:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("citation manifest is not valid JSON") from error
        if not isinstance(document, dict) or set(document) != {
            "schema_version",
            "artifact_path",
            "artifact_sha256",
            "goal_id",
            "goal_revision",
            "citations",
            "manifest_digest",
        }:
            raise ValueError("citation manifest has unknown or missing fields")
        raw_citations = document["citations"]
        if not isinstance(raw_citations, list):
            raise ValueError("citation manifest citations must be a list")
        citations: list[CitationV1] = []
        for item in raw_citations:
            if not isinstance(item, dict) or set(item) != {
                "marker",
                "source_id",
                "receipt_digest",
            }:
                raise ValueError("citation manifest entry is malformed")
            try:
                citations.append(CitationV1(**item))
            except TypeError as error:
                raise ValueError("citation manifest entry types are malformed") from error
        try:
            manifest = cls(
                schema_version=document["schema_version"],
                artifact_path=document["artifact_path"],
                artifact_sha256=document["artifact_sha256"],
                goal_id=document["goal_id"],
                goal_revision=document["goal_revision"],
                citations=tuple(citations),
                manifest_digest=document["manifest_digest"],
            )
        except TypeError as error:
            raise ValueError("citation manifest field types are malformed") from error
        if raw != manifest.to_json():
            raise ValueError("citation manifest JSON is not canonical")
        return manifest

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise ValueError("citation manifest schema version is unsupported")
        if not _is_safe_relative_artifact_path(self.artifact_path):
            raise ValueError("citation manifest artifact path is unsafe")
        if not isinstance(self.artifact_sha256, str) or not _is_lower_hex(
            self.artifact_sha256, length=64
        ):
            raise ValueError("citation manifest artifact digest is malformed")
        if not isinstance(self.goal_id, str) or not self.goal_id:
            raise ValueError("citation manifest goal identity is missing")
        if (
            not isinstance(self.goal_revision, int)
            or isinstance(self.goal_revision, bool)
            or self.goal_revision < 1
        ):
            raise ValueError("citation manifest goal revision is malformed")
        object.__setattr__(self, "citations", tuple(self.citations))
        if not 1 <= len(self.citations) <= 16 or any(
            not isinstance(citation, CitationV1) for citation in self.citations
        ):
            raise ValueError("citation manifest citation count is invalid")
        for values in (
            tuple(citation.marker for citation in self.citations),
            tuple(citation.source_id for citation in self.citations),
            tuple(citation.receipt_digest for citation in self.citations),
        ):
            if len(set(values)) != len(values):
                raise ValueError("citation manifest entries must be one-to-one")
        expected = canonical_json_digest(self._unsigned_values())
        if not isinstance(self.manifest_digest, str) or self.manifest_digest != expected:
            raise ValueError("citation manifest digest mismatch")

    def _unsigned_values(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "citations": [asdict(citation) for citation in self.citations],
        }

    def to_json(self) -> str:
        return json.dumps(
            {**self._unsigned_values(), "manifest_digest": self.manifest_digest},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def _is_lower_hex(value: str, *, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)


def _require_canonical_utc(value: object, field_name: str) -> None:
    from datetime import UTC, datetime

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be canonical UTC")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError(f"{field_name} must be canonical UTC") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError(f"{field_name} must be canonical UTC")


def _is_safe_relative_artifact_path(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1_000
        or value.startswith("/")
        or "\\" in value
        or any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value)
    ):
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


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
        if any(not isinstance(item, ProposedCriterion) for item in self.proposed_criteria):
            raise TypeError("goal proposed_criteria must contain ProposedCriterion values")
        deferred_filesystem_criteria = tuple(
            item
            for item in self.proposed_criteria
            if item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and item.artifact_path is None
        )
        if len(deferred_filesystem_criteria) > 1:
            raise ValueError("goal allows at most one deferred filesystem criterion")
        if any(not isinstance(item, AdmittedCriterion) for item in self.admitted_criteria):
            raise TypeError("goal admitted_criteria must contain AdmittedCriterion values")
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
class RequirementCoverage:
    """R2：completion claim 对当前权威用户要求的逐项覆盖复核（模型语义映射）。

    Runtime 只校验结构与版本/来源/证据绑定，不做自然语言解析；requirement
    文本由模型给出，其正确性由独立业务验收揭露。
    """

    requirement_id: str
    requirement: str
    source_fact_ids: tuple[str, ...]
    status: str
    criterion_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.requirement_id or not self.requirement.strip():
            raise ValueError("requirement coverage identity must not be empty")
        if self.status not in {"satisfied", "pending"}:
            raise ValueError("requirement coverage status must be satisfied or pending")
        if not self.source_fact_ids or any(not item for item in self.source_fact_ids):
            raise ValueError("requirement coverage must cite at least one source fact")
        if self.status == "satisfied" and not self.criterion_ids:
            raise ValueError(
                "satisfied requirement coverage must bind admitted criterion ids"
            )
        if self.status == "pending" and self.criterion_ids:
            raise ValueError(
                "pending requirement coverage must not bind criterion ids"
            )
        if any(not item for item in self.criterion_ids):
            raise ValueError("requirement coverage criterion ids must not be empty")
        object.__setattr__(self, "source_fact_ids", tuple(self.source_fact_ids))
        object.__setattr__(self, "criterion_ids", tuple(self.criterion_ids))


@dataclass(frozen=True, slots=True)
class CompletionClaim:
    correlation_id: str
    goal_id: str
    goal_revision: int
    criterion_evidence_refs: tuple[str, ...]
    requirement_coverage: tuple[RequirementCoverage, ...] = ()

    def __post_init__(self) -> None:
        if not self.correlation_id or not self.goal_id:
            raise ValueError("completion claim identity must not be empty")
        if self.goal_revision < 1:
            raise ValueError("completion claim goal_revision must be positive")
        if any(not item for item in self.criterion_evidence_refs):
            raise ValueError("completion claim evidence refs must not be empty strings")
        if len(set(self.criterion_evidence_refs)) != len(self.criterion_evidence_refs):
            raise ValueError("completion claim evidence refs must be unique")
        if any(
            not isinstance(item, RequirementCoverage)
            for item in self.requirement_coverage
        ):
            raise TypeError(
                "completion claim requirement_coverage must contain RequirementCoverage"
            )
        coverage_ids = [item.requirement_id for item in self.requirement_coverage]
        if len(set(coverage_ids)) != len(coverage_ids):
            raise ValueError("requirement coverage ids must be unique")
        object.__setattr__(
            self,
            "criterion_evidence_refs",
            tuple(self.criterion_evidence_refs),
        )
        object.__setattr__(
            self,
            "requirement_coverage",
            tuple(self.requirement_coverage),
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


GOAL_TARGET_AUTHORIZATION_MAX_USES = 16
GOAL_TARGET_AUTHORIZATION_EXPIRY_MINUTES = 60
# P7（2026-10-24）：路径敏感名的唯一权威源（原 path_safety 私有名单上移到
# 最底层 contracts，避免 contracts→tools 反向依赖）。intrinsic 敏感 = 永远
# 拒绝、不可被项目路径例外或可复用授权放行；goal 授权的 target 判定与
# 工具层 path_safety 共用同一谓词，杜绝两套名单手工同步漂移（修前
# id_rsa/credentials.json/.netrc 等 11+ 名只被 path_safety 拒绝）。
_INTRINSICALLY_SENSITIVE_EXACT = frozenset(
    {
        ".env",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
    }
)
_INTRINSICALLY_SENSITIVE_COMPONENTS = frozenset(
    {
        ".aws",
        ".claude",
        ".codex",
        ".config",
        ".docker",
        ".git",
        ".gnupg",
        ".kube",
        ".opencode",
        ".ssh",
        ".ua",
        "graphify-out",
        "node_modules",
    }
)
_INTRINSICALLY_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def is_intrinsically_sensitive_component(folded: str) -> bool:
    """这些名称始终拒绝，不能由普通项目路径例外放行。"""

    return (
        folded in _INTRINSICALLY_SENSITIVE_COMPONENTS
        or folded in _INTRINSICALLY_SENSITIVE_EXACT
        or folded.startswith(".env")
        or folded.endswith(_INTRINSICALLY_SENSITIVE_SUFFIXES)
        or folded == "config.local"
        or folded.startswith("config.local.")
    )


def safe_goal_authorization_target(target: str) -> bool:
    if not isinstance(target, str) or target.startswith("/"):
        return False
    parts = target.split("/")
    return bool(parts) and all(
        part not in {"", ".", ".."}
        and not is_intrinsically_sensitive_component(part.casefold())
        for part in parts
    )


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
    issued_at: str
    expires_at: str
    max_uses: int
    uses_consumed: int
    binding_digest: str
    scope: GoalAuthorizationScope = GoalAuthorizationScope.EXACT_FILE

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
                self.issued_at,
                self.expires_at,
                self.binding_digest,
            )
        ):
            raise ValueError("goal authorization binding fields must not be empty")
        if self.goal_revision < 1:
            raise ValueError("goal authorization revision must be positive")
        if not isinstance(self.scope, GoalAuthorizationScope):
            raise ValueError("goal authorization scope must be closed")
        if self.max_uses != GOAL_TARGET_AUTHORIZATION_MAX_USES:
            raise ValueError("goal authorization max_uses must use the fixed bound")
        if not 0 <= self.uses_consumed <= self.max_uses:
            raise ValueError("goal authorization uses_consumed is outside its bound")
        if not safe_goal_authorization_target(self.normalized_target):
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
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "max_uses": self.max_uses,
                "uses_consumed": self.uses_consumed,
                "scope": self.scope,
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
        issued_at: str,
        expires_at: str,
        max_uses: int = GOAL_TARGET_AUTHORIZATION_MAX_USES,
        uses_consumed: int = 0,
        scope: GoalAuthorizationScope = GoalAuthorizationScope.EXACT_FILE,
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
            "issued_at": issued_at,
            "expires_at": expires_at,
            "max_uses": max_uses,
            "uses_consumed": uses_consumed,
            "scope": scope,
        }
        return cls(**values, binding_digest=canonical_json_digest(values))

    @property
    def remaining_uses(self) -> int:
        return self.max_uses - self.uses_consumed

    def with_use_consumed(self) -> GoalAuthorizationBinding:
        values = {
            "binding_id": self.binding_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "workspace_identity_digest": self.workspace_identity_digest,
            "operation": self.operation,
            "normalized_target": self.normalized_target,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "source_digest": self.source_digest,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "max_uses": self.max_uses,
            "uses_consumed": self.uses_consumed + 1,
            "scope": self.scope,
        }
        return GoalAuthorizationBinding(
            **values,
            binding_digest=canonical_json_digest(values),
        )

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
            and (
                self.normalized_target == normalized_target
                if self.scope is GoalAuthorizationScope.EXACT_FILE
                else _path_is_within_directory(
                    normalized_target,
                    self.normalized_target,
                )
            )
            and self.binding_digest == self._expected_digest()
        )


def _path_is_within_directory(target: str, directory: str) -> bool:
    target_parts = target.split("/")
    directory_parts = directory.split("/")
    if (
        any(part in {"", ".", ".."} for part in target_parts)
        or any(part in {"", ".", ".."} for part in directory_parts)
        or len(target_parts) < len(directory_parts)
    ):
        return False
    return target_parts[: len(directory_parts)] == directory_parts


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


# 2026-10-21 确认体验修复：单一会话级常规外发许可。
# 这些是持久化合同，不能由 CLI 或工具自报字段推导；运行时只接受闭合值。
CONSENT_PROFILE_ROUTINE = "routine_conversation_v1"
CONSENT_MAX_USES = 32
CONSENT_TTL_SECONDS = 3_600
NO_WORKSPACE_IDENTITY = "NO_WORKSPACE"


def _is_consent_workspace_identity(value: object) -> bool:
    """workspace identity 是既有 opaque 值；空值只能用 NO_WORKSPACE 明确表示。"""

    return isinstance(value, str) and bool(value)


ROUTINE_DATA_CLASSES = (
    "control_receipts",
    "conversation_history",
    "conversation_summary",
    "goal",
    "goal_bootstrap",
    "runtime_progress",
    "system_policy",
    "tool_schemas",
    "user_messages",
)

# item 1（2026-10-24 用户裁决采纳）：读/验证类输出的会话级许可。只并入
# proof-backed 的 workspace_excerpt——该类来源由 Runtime 持久化的
# ProviderFileSourceProofV1 绑定 goal/revision/workspace/内容 digest 且
# reusable=True；summary 类本身不随之扩（summary 无 Runtime boundary 证明时
# 仍逐次披露）。P3-1 已在 2026-10-24 调值轮修复：summary boundary 继承的
# excerpt 在投影时按 proof store（boundary_digest 绑 goal_id+goal_revision）
# 对当前 Goal 重验，失配降 reusable=False（类别如实申报，退回逐次披露决策）。
# P5（2026-10-25 用户委托裁决）：读/列/搜工具改为铸造 WORKSPACE_READ proof，
# 其输出因此成为 proof-backed workspace_excerpt 来源、由 r 许可会话级覆盖
# （新文件/新目录同样覆盖——类级语义）；tool_results 等通用类仍逐次披露。
CONSENT_PROFILE_WORKSPACE_READ = "routine_workspace_read_v1"
WORKSPACE_READ_DATA_CLASSES = (*ROUTINE_DATA_CLASSES, "workspace_excerpt")


class ProviderConsentGrantStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    INVALIDATED = "invalidated"


class ResultSourceKind(StrEnum):
    """闭合的 Kernel 结果来源能力；不是工具可自报的自由字符串。"""

    WORKSPACE_FILE_EFFECT = "workspace_file_effect"
    # P5（2026-10-25 委托裁决）：读/列/搜的 workspace 读结果同样铸造
    # file-source proof（read_file/list_files/search_*/read_file_chunk/
    # confirm_file）；命令 stdout 等非 workspace 派生输出不在此列。
    WORKSPACE_READ = "workspace_read"


@dataclass(frozen=True, slots=True)
class ProviderConsentToolBindingV1:
    name: str
    identity_digest: str

    def __post_init__(self) -> None:
        if not self.name or not _is_lower_hex(self.identity_digest, length=64):
            raise ValueError("provider consent tool binding is invalid")

    @property
    def binding_digest(self) -> str:
        return canonical_json_digest(
            {"name": self.name, "identity_digest": self.identity_digest}
        )


@dataclass(frozen=True, slots=True)
class ProviderDisclosureSourceV1:
    """一次外发中非常规来源的稳定边界。

    ``boundary_digest`` 对文件效果来自 Kernel 证明的稳定身份（不含调用 ID、
    结果字节或 state revision）；未知来源只能携带一次性内容 digest。
    ``reusable`` 为 False 时，即使内容相同也只可消费一次明确许可。
    """

    data_class: str
    boundary_digest: str
    label: str
    reusable: bool

    def __post_init__(self) -> None:
        if not self.data_class or not self.label:
            raise ValueError("provider disclosure source fields must not be empty")
        if not _is_lower_hex(self.boundary_digest, length=64):
            raise ValueError("provider disclosure source digest must be sha256")
        if not isinstance(self.reusable, bool):
            raise TypeError("provider disclosure source reuse must be a bool")

    def identity_payload(self) -> dict[str, JSONValue]:
        return {
            "data_class": self.data_class,
            "boundary_digest": self.boundary_digest,
            "label": self.label,
            "reusable": self.reusable,
        }


@dataclass(frozen=True, slots=True)
class ProviderConsentScopeV1:
    """ContextManager 生成的只读许可投影；不直接授予任何权限。"""

    workspace_identity_digest: str
    goal_id: str | None
    goal_revision: int | None
    tool_bindings: tuple[ProviderConsentToolBindingV1, ...]
    control_schema_digest: str
    data_classes: tuple[str, ...]
    sources: tuple[ProviderDisclosureSourceV1, ...]
    routine_compatible: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_bindings", tuple(self.tool_bindings))
        object.__setattr__(self, "sources", tuple(self.sources))
        if not _is_consent_workspace_identity(self.workspace_identity_digest):
            raise ValueError(
                "consent workspace identity must be NO_WORKSPACE or workspace:v1:sha256"
            )
        if (self.goal_id is None) != (self.goal_revision is None):
            raise ValueError("consent goal identity must be paired")
        if self.goal_id is not None and self.goal_revision < 1:
            raise ValueError("consent goal revision must be positive")
        if not _is_lower_hex(self.control_schema_digest, length=64):
            raise ValueError("consent control schema digest must be sha256")
        if tuple(sorted(set(self.data_classes))) != self.data_classes or any(
            not item for item in self.data_classes
        ):
            raise ValueError("consent data classes must be sorted and unique")
        tool_names = tuple(binding.name for binding in self.tool_bindings)
        if tool_names != tuple(sorted(set(tool_names))):
            raise ValueError("consent tool bindings must be unique and sorted")
        source_keys = tuple(
            (source.data_class, source.boundary_digest, source.label)
            for source in self.sources
        )
        if source_keys != tuple(sorted(set(source_keys))):
            raise ValueError("consent sources must be unique and sorted")
        if not isinstance(self.routine_compatible, bool):
            raise TypeError("consent routine_compatible must be a bool")


@dataclass(frozen=True, slots=True)
class ProviderFileSourceProofV1:
    """Kernel 对内建文件写入成功结果铸造的稳定来源证明。

    证明同时绑定一次真实执行（intent/result digest）和可复用边界。ContextManager
    只信任 Runtime 保存进 state 的证明，工具自报的同名字段不会进入这里。
    """

    proof_id: str
    conversation_id: str
    run_id: str
    workspace_identity_digest: str
    tool_call_id: str
    tool_name: str
    tool_identity_digest: str
    policy_identity: str
    execution_authority: str
    operation: str
    normalized_target: str
    target_digest: str
    goal_id: str | None
    goal_revision: int | None
    intent_digest: str
    result_content_digest: str
    boundary_digest: str
    proof_digest: str

    def __post_init__(self) -> None:
        for name in (
            "proof_id",
            "conversation_id",
            "run_id",
            "workspace_identity_digest",
            "tool_call_id",
            "tool_name",
            "tool_identity_digest",
            "policy_identity",
            "execution_authority",
            "operation",
            "normalized_target",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"file source proof {name} must not be empty")
        for name in (
            "target_digest",
            "intent_digest",
            "result_content_digest",
            "boundary_digest",
            "proof_digest",
            "tool_identity_digest",
        ):
            if not _is_lower_hex(getattr(self, name), length=64):
                raise ValueError(f"file source proof {name} must be sha256")
        # goal 绑定成对出现：goal 会话=非空 goal_id+正数 revision；goal-less
        # 会话=双 None（与 ExecutionIntent/ControlReceipt 的编码一致）。
        # 半侧形状一律拒绝，防止 goal-less 读冒充 goal 绑定（反之亦然）。
        goal_bound = self.goal_id is not None
        if goal_bound != (self.goal_revision is not None):
            raise ValueError("file source proof goal binding must be paired")
        if goal_bound:
            if not self.goal_id:
                raise ValueError("file source proof goal_id must not be empty")
            if (
                not isinstance(self.goal_revision, int)
                or isinstance(self.goal_revision, bool)
            ):
                raise TypeError("file source proof goal revision must be an integer")
            if self.goal_revision < 1:
                raise ValueError("file source proof goal revision must be positive")
        if self.proof_digest != canonical_json_digest(self._payload()):
            raise ValueError("file source proof digest mismatch")

    def _payload(self) -> dict[str, JSONValue]:
        return {
            "proof_id": self.proof_id,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "workspace_identity_digest": self.workspace_identity_digest,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "tool_identity_digest": self.tool_identity_digest,
            "policy_identity": self.policy_identity,
            "execution_authority": self.execution_authority,
            "operation": self.operation,
            "normalized_target": self.normalized_target,
            "target_digest": self.target_digest,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "intent_digest": self.intent_digest,
            "result_content_digest": self.result_content_digest,
            "boundary_digest": self.boundary_digest,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        return {**self._payload(), "proof_digest": self.proof_digest}

    @classmethod
    def from_dict(cls, raw: object) -> ProviderFileSourceProofV1:
        if not isinstance(raw, dict):
            raise ValueError("file source proof must be an object")
        expected = {
            "proof_id",
            "conversation_id",
            "run_id",
            "workspace_identity_digest",
            "tool_call_id",
            "tool_name",
            "tool_identity_digest",
            "policy_identity",
            "execution_authority",
            "operation",
            "normalized_target",
            "target_digest",
            "goal_id",
            "goal_revision",
            "intent_digest",
            "result_content_digest",
            "boundary_digest",
            "proof_digest",
        }
        if set(raw) != expected:
            raise ValueError("file source proof fields are not closed")
        return cls(**raw)

    @staticmethod
    def boundary_payload(
        *,
        conversation_id: str,
        workspace_identity_digest: str,
        tool_name: str,
        tool_identity_digest: str,
        policy_identity: str,
        execution_authority: str,
        operation: str,
        target_digest: str,
        goal_id: str | None,
        goal_revision: int | None,
    ) -> dict[str, JSONValue]:
        return {
            "profile": "workspace_file_effect_v1",
            "conversation_id": conversation_id,
            "workspace_identity_digest": workspace_identity_digest,
            "tool_name": tool_name,
            "tool_identity_digest": tool_identity_digest,
            "policy_identity": policy_identity,
            "execution_authority": execution_authority,
            "operation": operation,
            "target_digest": target_digest,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
        }

    @classmethod
    def create(
        cls,
        *,
        conversation_id: str,
        run_id: str,
        workspace_identity_digest: str,
        tool_call_id: str,
        tool_name: str,
        tool_identity_digest: str,
        policy_identity: str,
        execution_authority: str,
        operation: str,
        normalized_target: str,
        target_digest: str,
        goal_id: str | None,
        goal_revision: int | None,
        intent_digest: str,
        result_content_digest: str,
    ) -> ProviderFileSourceProofV1:
        boundary_digest = canonical_json_digest(
            cls.boundary_payload(
                conversation_id=conversation_id,
                workspace_identity_digest=workspace_identity_digest,
                tool_name=tool_name,
                tool_identity_digest=tool_identity_digest,
                policy_identity=policy_identity,
                execution_authority=execution_authority,
                operation=operation,
                target_digest=target_digest,
                goal_id=goal_id,
                goal_revision=goal_revision,
            )
        )
        proof_id = (
            "file-source-proof:"
            + canonical_json_digest(
                {
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                    "intent_digest": intent_digest,
                }
            )[:16]
        )
        payload = {
            "proof_id": proof_id,
            "conversation_id": conversation_id,
            "run_id": run_id,
            "workspace_identity_digest": workspace_identity_digest,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "tool_identity_digest": tool_identity_digest,
            "policy_identity": policy_identity,
            "execution_authority": execution_authority,
            "operation": operation,
            "normalized_target": normalized_target,
            "target_digest": target_digest,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "intent_digest": intent_digest,
            "result_content_digest": result_content_digest,
            "boundary_digest": boundary_digest,
        }
        return cls(**payload, proof_digest=canonical_json_digest(payload))


@dataclass(frozen=True, slots=True)
class ProviderSummarySourceBoundaryV1:
    """一次压缩实际输入来源边界的 Runtime-owned 证明。"""

    summary_fact_id: str
    data_classes: tuple[str, ...]
    sources: tuple[ProviderDisclosureSourceV1, ...]
    routine_compatible: bool
    boundary_digest: str

    def __post_init__(self) -> None:
        if not self.summary_fact_id:
            raise ValueError("summary source boundary must bind a summary fact")
        object.__setattr__(self, "data_classes", tuple(self.data_classes))
        object.__setattr__(self, "sources", tuple(self.sources))
        if tuple(sorted(set(self.data_classes))) != self.data_classes or any(
            not item for item in self.data_classes
        ):
            raise ValueError("summary source data classes must be sorted and unique")
        source_keys = tuple(
            (source.data_class, source.boundary_digest, source.label)
            for source in self.sources
        )
        if source_keys != tuple(sorted(set(source_keys))):
            raise ValueError("summary sources must be unique and sorted")
        if not isinstance(self.routine_compatible, bool):
            raise TypeError("summary routine_compatible must be a bool")
        if not _is_lower_hex(self.boundary_digest, length=64):
            raise ValueError("summary source boundary digest must be sha256")
        if self.boundary_digest != canonical_json_digest(self._payload()):
            raise ValueError("summary source boundary digest mismatch")

    def _payload(self) -> dict[str, JSONValue]:
        return {
            "summary_fact_id": self.summary_fact_id,
            "data_classes": list(self.data_classes),
            "sources": [source.identity_payload() for source in self.sources],
            "routine_compatible": self.routine_compatible,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        return {**self._payload(), "boundary_digest": self.boundary_digest}

    @classmethod
    def from_dict(cls, raw: object) -> ProviderSummarySourceBoundaryV1:
        if not isinstance(raw, dict) or set(raw) != {
            "summary_fact_id",
            "data_classes",
            "sources",
            "routine_compatible",
            "boundary_digest",
        }:
            raise ValueError("summary source boundary fields are not closed")
        sources_raw = raw["sources"]
        classes_raw = raw["data_classes"]
        if not isinstance(sources_raw, list) or not isinstance(classes_raw, list):
            raise ValueError("summary source boundary collections are invalid")
        if any(not isinstance(source, dict) for source in sources_raw):
            raise ValueError("summary source boundary source is invalid")
        return cls(
            summary_fact_id=raw["summary_fact_id"],
            data_classes=tuple(classes_raw),
            sources=tuple(
                ProviderDisclosureSourceV1(
                    data_class=source["data_class"],
                    boundary_digest=source["boundary_digest"],
                    label=source["label"],
                    reusable=source["reusable"],
                )
                for source in sources_raw
                if isinstance(source, dict)
            ),
            routine_compatible=raw["routine_compatible"],
            boundary_digest=raw["boundary_digest"],
        )

    @classmethod
    def create(
        cls,
        *,
        summary_fact_id: str,
        data_classes: tuple[str, ...],
        sources: tuple[ProviderDisclosureSourceV1, ...],
        routine_compatible: bool,
    ) -> ProviderSummarySourceBoundaryV1:
        payload = {
            "summary_fact_id": summary_fact_id,
            "data_classes": list(tuple(sorted(set(data_classes)))),
            "sources": [
                source.identity_payload()
                for source in sorted(
                    set(sources),
                    key=lambda item: (item.data_class, item.boundary_digest, item.label),
                )
            ],
            "routine_compatible": routine_compatible,
        }
        return cls(
            summary_fact_id=summary_fact_id,
            data_classes=tuple(payload["data_classes"]),
            sources=tuple(
                sorted(
                    set(sources),
                    key=lambda item: (item.data_class, item.boundary_digest, item.label),
                )
            ),
            routine_compatible=routine_compatible,
            boundary_digest=canonical_json_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class ProviderDisclosureRequestV2:
    """新模式的外发请求：真实类别 + 稳定来源边界 + 授予候选。

    旧 v1 request 保持原字段和 digest 语义；v2 的 ``scope_digest`` 只覆盖非常规
    来源边界与身份，不随常规历史/回执涨落。
    """

    disclosure_id: str
    provider_descriptor_digest: str
    canonical_destination: str
    model: str
    workspace_identity_digest: str
    data_classes: tuple[str, ...]
    sources: tuple[ProviderDisclosureSourceV1, ...]
    tool_bindings: tuple[ProviderConsentToolBindingV1, ...]
    control_schema_digest: str
    grant_id: str | None
    grant_eligible: bool
    purpose: str
    run_id: str
    goal_id: str | None
    goal_revision: int | None
    scope_digest: str
    request_digest: str

    def __post_init__(self) -> None:
        for name in (
            "disclosure_id",
            "provider_descriptor_digest",
            "canonical_destination",
            "model",
            "workspace_identity_digest",
            "control_schema_digest",
            "purpose",
            "run_id",
        ):
            if not getattr(self, name):
                raise ValueError(f"provider disclosure v2 {name} must not be empty")
        object.__setattr__(self, "data_classes", tuple(self.data_classes))
        if tuple(sorted(set(self.data_classes))) != self.data_classes or any(
            not item for item in self.data_classes
        ):
            raise ValueError("provider disclosure v2 data classes must be sorted and unique")
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "tool_bindings", tuple(self.tool_bindings))
        if not isinstance(self.grant_eligible, bool):
            raise TypeError("provider disclosure v2 grant eligibility must be a bool")
        if not _is_consent_workspace_identity(self.workspace_identity_digest):
            raise ValueError("provider disclosure v2 workspace identity is invalid")
        if (self.goal_id is None) != (self.goal_revision is None):
            raise ValueError("provider disclosure v2 goal identity must be paired")
        if self.request_digest != self._expected_digest():
            raise ValueError("provider disclosure v2 request digest mismatch")
        if self.scope_digest != self._expected_scope_digest():
            raise ValueError("provider disclosure v2 scope digest mismatch")

    def _payload(self) -> dict[str, JSONValue]:
        return {
            "request_version": 2,
            "disclosure_id": self.disclosure_id,
            "provider_descriptor_digest": self.provider_descriptor_digest,
            "canonical_destination": self.canonical_destination,
            "model": self.model,
            "workspace_identity_digest": self.workspace_identity_digest,
            "data_classes": list(self.data_classes),
            "sources": [source.identity_payload() for source in self.sources],
            "tool_bindings": [
                {"name": binding.name, "identity_digest": binding.identity_digest}
                for binding in self.tool_bindings
            ],
            "control_schema_digest": self.control_schema_digest,
            "grant_id": self.grant_id,
            "grant_eligible": self.grant_eligible,
            "purpose": self.purpose,
            "run_id": self.run_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
        }

    def _expected_digest(self) -> str:
        return canonical_json_digest(self._payload())

    def _expected_scope_digest(self) -> str:
        return canonical_json_digest(
            {
                "profile": CONSENT_PROFILE_ROUTINE,
                "provider_descriptor_digest": self.provider_descriptor_digest,
                "canonical_destination": self.canonical_destination,
                "model": self.model,
                "workspace_identity_digest": self.workspace_identity_digest,
                "goal_id": self.goal_id,
                "goal_revision": self.goal_revision,
                "sources": [source.identity_payload() for source in self.sources],
            }
        )

    def acknowledge(
        self,
        *,
        receipt_id: str,
        acknowledged_action_seq: int,
        acknowledged_at: str,
    ) -> ProviderDisclosureReceiptV2:
        return ProviderDisclosureReceiptV2(
            receipt_id=receipt_id,
            request_digest=self.request_digest,
            acknowledged_action_seq=acknowledged_action_seq,
            acknowledged_at=acknowledged_at,
            consumed_at=None,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            **self._payload(),
            "scope_digest": self.scope_digest,
            "request_digest": self.request_digest,
        }

    @classmethod
    def from_dict(cls, raw: object) -> ProviderDisclosureRequestV2:
        if not isinstance(raw, dict):
            raise ValueError("provider disclosure v2 must be an object")
        expected = {
            "request_version",
            "disclosure_id",
            "provider_descriptor_digest",
            "canonical_destination",
            "model",
            "workspace_identity_digest",
            "data_classes",
            "sources",
            "tool_bindings",
            "control_schema_digest",
            "grant_id",
            "grant_eligible",
            "purpose",
            "run_id",
            "goal_id",
            "goal_revision",
            "scope_digest",
            "request_digest",
        }
        if set(raw) != expected or raw.get("request_version") != 2:
            raise ValueError("provider disclosure v2 fields are not closed")
        raw_sources = raw["sources"]
        raw_bindings = raw["tool_bindings"]
        if not isinstance(raw_sources, list) or not isinstance(raw_bindings, list):
            raise ValueError("provider disclosure v2 collections are invalid")
        if any(not isinstance(item, dict) for item in (*raw_sources, *raw_bindings)):
            raise ValueError("provider disclosure v2 collection item is invalid")
        return cls(
            disclosure_id=raw["disclosure_id"],
            provider_descriptor_digest=raw["provider_descriptor_digest"],
            canonical_destination=raw["canonical_destination"],
            model=raw["model"],
            workspace_identity_digest=raw["workspace_identity_digest"],
            data_classes=tuple(raw["data_classes"]),
            sources=tuple(
                ProviderDisclosureSourceV1(
                    data_class=item["data_class"],
                    boundary_digest=item["boundary_digest"],
                    label=item["label"],
                    reusable=item["reusable"],
                )
                for item in raw_sources
            ),
            tool_bindings=tuple(
                ProviderConsentToolBindingV1(
                    name=item["name"],
                    identity_digest=item["identity_digest"],
                )
                for item in raw_bindings
            ),
            control_schema_digest=raw["control_schema_digest"],
            grant_id=raw["grant_id"],
            grant_eligible=raw["grant_eligible"],
            purpose=raw["purpose"],
            run_id=raw["run_id"],
            goal_id=raw["goal_id"],
            goal_revision=raw["goal_revision"],
            scope_digest=raw["scope_digest"],
            request_digest=raw["request_digest"],
        )


@dataclass(frozen=True, slots=True)
class ProviderDisclosureReceiptV2:
    receipt_id: str
    request_digest: str
    acknowledged_action_seq: int
    acknowledged_at: str
    consumed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.receipt_id or not self.request_digest or not self.acknowledged_at:
            raise ValueError("provider disclosure v2 receipt fields must not be empty")
        if self.acknowledged_action_seq < 1:
            raise ValueError("disclosure acknowledgement action sequence must be positive")
        if self.consumed_at is not None and not self.consumed_at:
            raise ValueError("consumed receipt time must not be empty")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "receipt_version": 2,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "acknowledged_action_seq": self.acknowledged_action_seq,
            "acknowledged_at": self.acknowledged_at,
            "consumed_at": self.consumed_at,
        }

    @classmethod
    def from_dict(cls, raw: object) -> ProviderDisclosureReceiptV2:
        if not isinstance(raw, dict) or set(raw) != {
            "receipt_version",
            "receipt_id",
            "request_digest",
            "acknowledged_action_seq",
            "acknowledged_at",
            "consumed_at",
        } or raw.get("receipt_version") != 2:
            raise ValueError("provider disclosure v2 receipt fields are not closed")
        return cls(
            receipt_id=raw["receipt_id"],
            request_digest=raw["request_digest"],
            acknowledged_action_seq=raw["acknowledged_action_seq"],
            acknowledged_at=raw["acknowledged_at"],
            consumed_at=raw["consumed_at"],
        )


@dataclass(frozen=True, slots=True)
class ProviderConsentGrantV1:
    grant_id: str
    conversation_id: str
    workspace_identity_digest: str
    provider_descriptor_digest: str
    canonical_destination: str
    model: str
    profile: str
    allowed_data_classes: tuple[str, ...]
    tool_bindings: tuple[ProviderConsentToolBindingV1, ...]
    control_schema_digest: str
    disclosure_request_digest: str
    scope_digest: str
    granted_action_seq: int
    issued_at: str
    expires_at: str
    max_uses: int
    uses_consumed: int
    status: ProviderConsentGrantStatus
    grant_digest: str

    def __post_init__(self) -> None:
        for name in (
            "grant_id",
            "conversation_id",
            "workspace_identity_digest",
            "provider_descriptor_digest",
            "canonical_destination",
            "model",
            "profile",
            "issued_at",
            "expires_at",
        ):
            if not getattr(self, name):
                raise ValueError(f"provider consent grant {name} must not be empty")
        if self.profile not in (CONSENT_PROFILE_ROUTINE, CONSENT_PROFILE_WORKSPACE_READ):
            raise ValueError("provider consent grant profile is unsupported")
        object.__setattr__(self, "allowed_data_classes", tuple(self.allowed_data_classes))
        if tuple(sorted(set(self.allowed_data_classes))) != self.allowed_data_classes:
            raise ValueError("provider consent grant classes must be sorted and unique")
        if self.profile == CONSENT_PROFILE_WORKSPACE_READ:
            if self.allowed_data_classes != WORKSPACE_READ_DATA_CLASSES:
                raise ValueError(
                    "provider consent grant classes must match the workspace-read scope"
                )
        elif not set(self.allowed_data_classes).issubset(ROUTINE_DATA_CLASSES):
            raise ValueError("provider consent grant classes exceed the routine scope")
        object.__setattr__(self, "tool_bindings", tuple(self.tool_bindings))
        tool_names = tuple(binding.name for binding in self.tool_bindings)
        if tool_names != tuple(sorted(set(tool_names))):
            raise ValueError("provider consent grant tool bindings must be unique and sorted")
        if not isinstance(self.status, ProviderConsentGrantStatus):
            raise TypeError("provider consent grant status must be closed")
        for name in ("max_uses", "uses_consumed", "granted_action_seq"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"provider consent grant {name} must be an integer")
        if self.max_uses != CONSENT_MAX_USES:
            raise ValueError("provider consent grant max_uses is fixed")
        if not 0 <= self.uses_consumed <= self.max_uses:
            raise ValueError("provider consent grant uses_consumed is out of range")
        if self.granted_action_seq < 1:
            raise ValueError("provider consent grant action sequence must be positive")
        if not _is_consent_workspace_identity(self.workspace_identity_digest):
            raise ValueError("provider consent grant workspace identity is invalid")
        for name in (
            "provider_descriptor_digest",
            "control_schema_digest",
            "disclosure_request_digest",
            "scope_digest",
            "grant_digest",
        ):
            if not _is_lower_hex(getattr(self, name), length=64):
                raise ValueError(f"provider consent grant {name} must be sha256")
        if self.grant_digest != canonical_json_digest(self._payload()):
            raise ValueError("provider consent grant digest mismatch")

    def _payload(self) -> dict[str, JSONValue]:
        return {
            "grant_id": self.grant_id,
            "conversation_id": self.conversation_id,
            "workspace_identity_digest": self.workspace_identity_digest,
            "provider_descriptor_digest": self.provider_descriptor_digest,
            "canonical_destination": self.canonical_destination,
            "model": self.model,
            "profile": self.profile,
            "allowed_data_classes": list(self.allowed_data_classes),
            "tool_bindings": [
                {"name": binding.name, "identity_digest": binding.identity_digest}
                for binding in self.tool_bindings
            ],
            "control_schema_digest": self.control_schema_digest,
            "disclosure_request_digest": self.disclosure_request_digest,
            "scope_digest": self.scope_digest,
            "granted_action_seq": self.granted_action_seq,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "max_uses": self.max_uses,
            "uses_consumed": self.uses_consumed,
            "status": self.status.value,
        }

    def with_status(self, status: ProviderConsentGrantStatus) -> ProviderConsentGrantV1:
        payload = self._payload()
        payload["status"] = status.value
        return replace(
            self,
            status=status,
            grant_digest=canonical_json_digest(payload),
        )

    def with_use(self) -> ProviderConsentGrantV1:
        if self.status is not ProviderConsentGrantStatus.ACTIVE:
            raise ValueError("provider consent grant is not active")
        return replace(
            self,
            uses_consumed=self.uses_consumed + 1,
            grant_digest=canonical_json_digest(
                {**self._payload(), "uses_consumed": self.uses_consumed + 1}
            ),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {**self._payload(), "grant_digest": self.grant_digest}

    @classmethod
    def from_dict(cls, raw: object) -> ProviderConsentGrantV1:
        expected = {
            "grant_id",
            "conversation_id",
            "workspace_identity_digest",
            "provider_descriptor_digest",
            "canonical_destination",
            "model",
            "profile",
            "allowed_data_classes",
            "tool_bindings",
            "control_schema_digest",
            "disclosure_request_digest",
            "scope_digest",
            "granted_action_seq",
            "issued_at",
            "expires_at",
            "max_uses",
            "uses_consumed",
            "status",
            "grant_digest",
        }
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ValueError("provider consent grant fields are not closed")
        raw_bindings = raw["tool_bindings"]
        if not isinstance(raw_bindings, list) or any(
            not isinstance(item, dict) for item in raw_bindings
        ):
            raise ValueError("provider consent grant tool bindings are invalid")
        return cls(
            grant_id=raw["grant_id"],
            conversation_id=raw["conversation_id"],
            workspace_identity_digest=raw["workspace_identity_digest"],
            provider_descriptor_digest=raw["provider_descriptor_digest"],
            canonical_destination=raw["canonical_destination"],
            model=raw["model"],
            profile=raw["profile"],
            allowed_data_classes=tuple(raw["allowed_data_classes"]),
            tool_bindings=tuple(
                ProviderConsentToolBindingV1(
                    name=item["name"],
                    identity_digest=item["identity_digest"],
                )
                for item in raw_bindings
            ),
            control_schema_digest=raw["control_schema_digest"],
            disclosure_request_digest=raw["disclosure_request_digest"],
            scope_digest=raw["scope_digest"],
            granted_action_seq=raw["granted_action_seq"],
            issued_at=raw["issued_at"],
            expires_at=raw["expires_at"],
            max_uses=raw["max_uses"],
            uses_consumed=raw["uses_consumed"],
            status=ProviderConsentGrantStatus(raw["status"]),
            grant_digest=raw["grant_digest"],
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
class DirectResponse:
    """无活动 Goal 时的最终回答；严格 control wire 不把问答伪装成澄清。"""

    correlation_id: str
    text: str

    def __post_init__(self) -> None:
        _require_control_identity(self.correlation_id)
        if not self.text.strip():
            raise ValueError("direct response text must not be empty")


@dataclass(frozen=True, slots=True)
class BeginAnswer:
    """进入本 run 的只读问答阶段；不创建 Goal，也不携带来源 authority。"""

    correlation_id: str

    def __post_init__(self) -> None:
        _require_control_identity(self.correlation_id)


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
class GoalDraftProposal:
    """模型只提出 Goal 语义；身份、权威、状态与时间由 Runtime 铸造。"""

    correlation_id: str
    user_outcome: str
    beneficiary: str
    targets: tuple[str, ...]
    scope: tuple[str, ...]
    non_goals: tuple[str, ...]
    assumptions: tuple[str, ...]
    proposed_criteria: tuple[ProposedCriterion, ...]
    next_step: str | None = None
    # 模型只做语义提案；只有 authoritative user fact 明确要求时，Runtime 才会
    # 铸造 closed Web receipt criterion。
    requires_public_web: bool = False
    # authoritative user fact 明确要求 run/test/build/validate 时，Runtime
    # 铸造不可被文件证据替代的 process receipt 义务。
    requires_local_process: bool = False

    def __post_init__(self) -> None:
        _require_control_identity(self.correlation_id)
        if not self.user_outcome.strip() or not self.beneficiary.strip():
            raise ValueError("goal draft outcome and beneficiary must not be empty")
        if not self.targets or any(not item for item in self.targets):
            raise ValueError("goal draft targets must not be empty")
        if not self.scope or any(not item for item in self.scope):
            raise ValueError("goal draft scope must not be empty")
        if not self.proposed_criteria or any(
            not isinstance(item, ProposedCriterion) for item in self.proposed_criteria
        ):
            raise ValueError("goal draft criteria must contain ProposedCriterion values")
        if self.next_step is not None and (
            not isinstance(self.next_step, str) or not self.next_step.strip()
        ):
            raise ValueError("goal draft next step must not be empty")
        if not isinstance(self.requires_public_web, bool):
            raise TypeError("goal draft public Web requirement must be boolean")
        if not isinstance(self.requires_local_process, bool):
            raise TypeError("goal draft local process requirement must be boolean")
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(self, "scope", tuple(self.scope))
        object.__setattr__(self, "non_goals", tuple(self.non_goals))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "proposed_criteria", tuple(self.proposed_criteria))


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
    DirectResponse
    | BeginAnswer
    | ClarificationRequest
    | GoalDraftProposal
    | GoalProgress
    | GoalDeltaProposal
    | CompletionClaim
    | BlockedClaim
)

_MODEL_CONTROL_TYPES = (
    DirectResponse,
    BeginAnswer,
    ClarificationRequest,
    GoalDraftProposal,
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


# 020 长会话压缩：CONTEXT_SUMMARY 的闭合、有界内容形状（计划 §3.2）。
CONVERSATION_SUMMARY_OBJECTIVE_LIMIT = 2_000
CONVERSATION_SUMMARY_ITEM_TEXT_LIMIT = 1_000
CONVERSATION_SUMMARY_ITEM_COUNT_LIMIT = 16

_CONVERSATION_SUMMARY_LIST_FIELDS = (
    "constraints",
    "decisions",
    "completed",
    "open_items",
    "key_references",
)
_CONVERSATION_SUMMARY_DIGEST_FIELDS = (
    "source_checkpoint_digest",
    "source_fact_ids_digest",
)


@dataclass(frozen=True, slots=True)
class ConversationSummaryV1:
    """``FactKind.CONTEXT_SUMMARY`` 的唯一合法内容。

    summary 是模型生成的 untrusted context data：闭合字段里没有 Goal、Evidence、
    Approval、Recovery 等 canonical state 字段，未知键一律拒绝；canonical 字段
    只能由 Runtime/用户权威路径变更，永不从 summary 重建。
    """

    objective: str
    constraints: tuple[str, ...]
    decisions: tuple[str, ...]
    completed: tuple[str, ...]
    open_items: tuple[str, ...]
    key_references: tuple[str, ...]
    source_checkpoint_digest: str
    source_fact_ids_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.objective, str)
            or not self.objective.strip()
            or len(self.objective) > CONVERSATION_SUMMARY_OBJECTIVE_LIMIT
        ):
            raise ValueError(
                "conversation summary objective must be non-empty text within the "
                f"{CONVERSATION_SUMMARY_OBJECTIVE_LIMIT}-character limit"
            )
        for field_name in _CONVERSATION_SUMMARY_LIST_FIELDS:
            items = getattr(self, field_name)
            if isinstance(items, str) or not isinstance(items, tuple | list):
                raise ValueError(
                    f"conversation summary {field_name} must be a list of text items"
                )
            if len(items) > CONVERSATION_SUMMARY_ITEM_COUNT_LIMIT:
                raise ValueError(
                    f"conversation summary {field_name} exceeds the "
                    f"{CONVERSATION_SUMMARY_ITEM_COUNT_LIMIT}-item limit"
                )
            for item in items:
                if (
                    not isinstance(item, str)
                    or not item.strip()
                    or len(item) > CONVERSATION_SUMMARY_ITEM_TEXT_LIMIT
                ):
                    raise ValueError(
                        f"conversation summary {field_name} items must be non-empty "
                        f"text within the {CONVERSATION_SUMMARY_ITEM_TEXT_LIMIT}-character "
                        "limit"
                    )
            object.__setattr__(self, field_name, tuple(items))
        for field_name in _CONVERSATION_SUMMARY_DIGEST_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _is_lower_hex(value, length=64):
                raise ValueError(
                    f"conversation summary {field_name} must be a sha256 digest"
                )

    @classmethod
    def from_content(cls, content: object) -> ConversationSummaryV1:
        """从 JSON dict 严格解析；未知键、缺失字段、非文本 block 一律拒绝。"""

        expected = {
            "objective",
            *_CONVERSATION_SUMMARY_LIST_FIELDS,
            *_CONVERSATION_SUMMARY_DIGEST_FIELDS,
        }
        if not isinstance(content, dict) or set(content) != expected:
            raise ValueError("conversation summary has unknown or missing fields")
        for field_name in _CONVERSATION_SUMMARY_LIST_FIELDS:
            if not isinstance(content[field_name], list):
                raise ValueError(
                    f"conversation summary {field_name} must be a list of text items"
                )
        return cls(
            objective=content["objective"],
            constraints=content["constraints"],
            decisions=content["decisions"],
            completed=content["completed"],
            open_items=content["open_items"],
            key_references=content["key_references"],
            source_checkpoint_digest=content["source_checkpoint_digest"],
            source_fact_ids_digest=content["source_fact_ids_digest"],
        )

    @classmethod
    def from_json(cls, raw: str) -> ConversationSummaryV1:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("conversation summary is not valid JSON") from error
        return cls.from_content(document)

    def to_content(self) -> dict[str, JSONValue]:
        return {
            "objective": self.objective,
            **{
                field_name: list(getattr(self, field_name))
                for field_name in _CONVERSATION_SUMMARY_LIST_FIELDS
            },
            "source_checkpoint_digest": self.source_checkpoint_digest,
            "source_fact_ids_digest": self.source_fact_ids_digest,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_content(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class ProcessOutcome(StrEnum):
    """closed process receipt outcome；unknown 不产生 receipt（进入既有 recovery）。"""

    EXITED = "exited"
    SIGNALED = "signaled"
    TIMED_OUT_REAPED = "timed_out_reaped"


# ConversationState 持有的 active process authority lease 数量上限（bounded cardinality）。
# 单个 Goal revision 内允许少量互异 exact command lease；超过即 fail closed。
MAX_PROCESS_LEASES = 16


@dataclass(frozen=True, slots=True)
class ArtifactConfirmationRequirementV1:
    """Goal 提出的 artifact oracle 在 process approval 上的 closed obligation。"""

    criterion_id: str
    artifact_path: str

    def __post_init__(self) -> None:
        if not self.criterion_id:
            raise ValueError("artifact confirmation criterion_id must not be empty")
        if not _is_safe_relative_artifact_path(self.artifact_path):
            raise ValueError(
                "artifact confirmation path must be safe and workspace-relative"
            )


@dataclass(frozen=True, slots=True)
class ProcessAuthorityCandidateV1:
    """approval request 的 closed typed process 投影（KTD3）。

    持久化在 ``ApprovalRequest.process_authority_candidate`` 上，随 AWAITING_APPROVAL
    checkpoint strict round-trip；restart 后只能从该 durable candidate 铸造 lease，
    不得从 preview/transient memory 重建。不携带 credential/raw env/absolute workspace path。
    """

    candidate_id: str
    candidate_digest: str
    goal_id: str
    goal_revision: int
    workspace_identity_digest: str
    command_fingerprint: str
    readable_command: str
    executable_digest: str
    argv_digest: str
    cwd_digest: str
    resource_profile: str
    environment_policy_digest: str
    execution_authority: ExecutionAuthorityClass
    trust_notice_digest: str
    issued_at: str
    max_uses: int = 8
    expiry_minutes: int = 60
    # 015 J1：expected artifact binding（用户在 exact approval 中确认的期望产物）。
    # 两者必须同时存在或同时缺失；进入 command fingerprint + checkpoint round-trip。
    expected_artifact_path: str | None = None
    expected_artifact_sha256: str | None = None

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        command_fingerprint: str,
        readable_command: str,
        executable_digest: str,
        argv_digest: str,
        cwd_digest: str,
        resource_profile: str,
        environment_policy_digest: str,
        execution_authority: ExecutionAuthorityClass,
        trust_notice_digest: str,
        issued_at: str,
        max_uses: int = 8,
        expiry_minutes: int = 60,
        expected_artifact_path: str | None = None,
        expected_artifact_sha256: str | None = None,
    ) -> ProcessAuthorityCandidateV1:
        values = {
            "candidate_id": candidate_id,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "workspace_identity_digest": workspace_identity_digest,
            "command_fingerprint": command_fingerprint,
            "readable_command": readable_command,
            "executable_digest": executable_digest,
            "argv_digest": argv_digest,
            "cwd_digest": cwd_digest,
            "resource_profile": resource_profile,
            "environment_policy_digest": environment_policy_digest,
            "execution_authority": execution_authority,
            "trust_notice_digest": trust_notice_digest,
            "issued_at": issued_at,
            "max_uses": max_uses,
            "expiry_minutes": expiry_minutes,
            "expected_artifact_path": expected_artifact_path,
            "expected_artifact_sha256": expected_artifact_sha256,
        }
        return cls(candidate_digest=canonical_json_digest(values), **values)

    def _digest_values(self) -> dict[str, JSONValue]:
        return {
            "candidate_id": self.candidate_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "workspace_identity_digest": self.workspace_identity_digest,
            "command_fingerprint": self.command_fingerprint,
            "readable_command": self.readable_command,
            "executable_digest": self.executable_digest,
            "argv_digest": self.argv_digest,
            "cwd_digest": self.cwd_digest,
            "resource_profile": self.resource_profile,
            "environment_policy_digest": self.environment_policy_digest,
            "execution_authority": self.execution_authority,
            "trust_notice_digest": self.trust_notice_digest,
            "issued_at": self.issued_at,
            "max_uses": self.max_uses,
            "expiry_minutes": self.expiry_minutes,
            "expected_artifact_path": self.expected_artifact_path,
            "expected_artifact_sha256": self.expected_artifact_sha256,
        }

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("candidate_digest", self.candidate_digest),
            ("goal_id", self.goal_id),
            ("workspace_identity_digest", self.workspace_identity_digest),
            ("command_fingerprint", self.command_fingerprint),
            ("executable_digest", self.executable_digest),
            ("argv_digest", self.argv_digest),
            ("cwd_digest", self.cwd_digest),
            ("resource_profile", self.resource_profile),
            ("environment_policy_digest", self.environment_policy_digest),
            ("trust_notice_digest", self.trust_notice_digest),
            ("issued_at", self.issued_at),
        ):
            if not value:
                raise ValueError(f"process candidate {name} must not be empty")
        if self.goal_revision < 0:
            raise ValueError("process candidate goal_revision must be non-negative")
        if self.max_uses != 8:
            raise ValueError("process candidate max_uses must be fixed at 8")
        if self.expiry_minutes != 60:
            raise ValueError("process candidate expiry_minutes must be fixed at 60")
        if self.execution_authority is not ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS:
            raise ValueError("process candidate must use LOCAL_SAME_UID_PROCESS authority")
        if canonical_json_digest(self._digest_values()) != self.candidate_digest:
            raise ValueError("process candidate digest mismatch")
        # expected_artifact：两者同时存在或同时缺失。
        has_path = self.expected_artifact_path is not None
        has_sha = self.expected_artifact_sha256 is not None
        if has_path != has_sha:
            raise ValueError("expected_artifact path and sha256 must both be present or absent")
        if has_path and has_sha:
            import re
            if not re.match(r"^[a-f0-9]{64}$", self.expected_artifact_sha256):  # noqa: F821
                raise ValueError("expected_artifact sha256 must be 64 lowercase hex")
            if not self.expected_artifact_path or "\x00" in self.expected_artifact_path:
                raise ValueError("expected_artifact path must be non-empty NUL-free")


@dataclass(frozen=True, slots=True)
class ProcessAuthorityLeaseV1:
    """ResolveApproval 铸造的 exact、有限、可过期、可撤销 durable lease（KTD2/KTD4）。

    匹配要求所有 binding identity exact equal；不存在 wildcard/prefix/regex。uses_consumed
    在 intent 进入 durable EXECUTING checkpoint 时单调递增。Goal revision/terminal transition
    使其失效。
    """

    lease_id: str
    lease_digest: str
    candidate_digest: str
    goal_id: str
    goal_revision: int
    workspace_identity_digest: str
    command_fingerprint: str
    readable_command: str
    executable_digest: str
    argv_digest: str
    cwd_digest: str
    resource_profile: str
    environment_policy_digest: str
    execution_authority: ExecutionAuthorityClass
    approved_request_identity: str
    issued_at: str
    expires_at: str
    max_uses: int = 8
    uses_consumed: int = 0

    @classmethod
    def create(
        cls,
        *,
        lease_id: str,
        candidate_digest: str,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        command_fingerprint: str,
        readable_command: str,
        executable_digest: str,
        argv_digest: str,
        cwd_digest: str,
        resource_profile: str,
        environment_policy_digest: str,
        execution_authority: ExecutionAuthorityClass,
        approved_request_identity: str,
        issued_at: str,
        expires_at: str,
        max_uses: int = 8,
        uses_consumed: int = 0,
    ) -> ProcessAuthorityLeaseV1:
        values = {
            "lease_id": lease_id,
            "candidate_digest": candidate_digest,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "workspace_identity_digest": workspace_identity_digest,
            "command_fingerprint": command_fingerprint,
            "readable_command": readable_command,
            "executable_digest": executable_digest,
            "argv_digest": argv_digest,
            "cwd_digest": cwd_digest,
            "resource_profile": resource_profile,
            "environment_policy_digest": environment_policy_digest,
            "execution_authority": execution_authority,
            "approved_request_identity": approved_request_identity,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "max_uses": max_uses,
        }
        return cls(
            lease_digest=canonical_json_digest(values),
            uses_consumed=uses_consumed,
            **values,
        )

    def _digest_values(self) -> dict[str, JSONValue]:
        return {
            "lease_id": self.lease_id,
            "candidate_digest": self.candidate_digest,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "workspace_identity_digest": self.workspace_identity_digest,
            "command_fingerprint": self.command_fingerprint,
            "readable_command": self.readable_command,
            "executable_digest": self.executable_digest,
            "argv_digest": self.argv_digest,
            "cwd_digest": self.cwd_digest,
            "resource_profile": self.resource_profile,
            "environment_policy_digest": self.environment_policy_digest,
            "execution_authority": self.execution_authority,
            "approved_request_identity": self.approved_request_identity,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "max_uses": self.max_uses,
        }

    def __post_init__(self) -> None:
        for name, value in (
            ("lease_id", self.lease_id),
            ("lease_digest", self.lease_digest),
            ("candidate_digest", self.candidate_digest),
            ("goal_id", self.goal_id),
            ("workspace_identity_digest", self.workspace_identity_digest),
            ("command_fingerprint", self.command_fingerprint),
            ("readable_command", self.readable_command),
            ("executable_digest", self.executable_digest),
            ("argv_digest", self.argv_digest),
            ("cwd_digest", self.cwd_digest),
            ("resource_profile", self.resource_profile),
            ("environment_policy_digest", self.environment_policy_digest),
            ("approved_request_identity", self.approved_request_identity),
            ("issued_at", self.issued_at),
            ("expires_at", self.expires_at),
        ):
            if not value:
                raise ValueError(f"process lease {name} must not be empty")
        if self.goal_revision < 0:
            raise ValueError("process lease goal_revision must be non-negative")
        if self.max_uses != 8:
            raise ValueError("process lease max_uses must be fixed at 8")
        if not 0 <= self.uses_consumed <= self.max_uses:
            raise ValueError("process lease uses_consumed out of range")
        if self.execution_authority is not ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS:
            raise ValueError("process lease must use LOCAL_SAME_UID_PROCESS authority")
        if canonical_json_digest(self._digest_values()) != self.lease_digest:
            raise ValueError("process lease digest mismatch")

    @property
    def remaining_uses(self) -> int:
        return self.max_uses - self.uses_consumed

    @property
    def is_exhausted(self) -> bool:
        return self.uses_consumed >= self.max_uses


@dataclass(frozen=True, slots=True)
class ProcessReceiptV1:
    """KernelToolRuntime 铸造的 closed process receipt（KTD8/KTD10）。

    普通 callable 不能自报 receipt。receipt 绑定 Goal/lease/intent identity 与 closed outcome；
    unknown outcome 不产生 receipt。``TOOL_RECEIPT`` oracle 对 process 使用 typed predicate。
    """

    lease_id: str
    lease_digest: str
    use_ordinal: int
    goal_id: str
    goal_revision: int
    workspace_identity_digest: str
    tool_identity: str
    intent_digest: str
    executable_digest: str
    argv_digest: str
    cwd_digest: str
    resource_profile: str
    environment_policy_digest: str
    execution_authority: ExecutionAuthorityClass
    outcome: ProcessOutcome
    exit_code: int | None
    signal: str | None
    started_at: str
    ended_at: str
    duration_seconds: float
    stdout_digest: str
    stderr_digest: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool
    group_cleanup_claim: str
    command_fingerprint: str
    receipt_digest: str
    receipt_version: str = "process_receipt_v1"

    @classmethod
    def create(
        cls,
        *,
        lease_id: str,
        lease_digest: str,
        use_ordinal: int,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        tool_identity: str,
        intent_digest: str,
        executable_digest: str,
        argv_digest: str,
        cwd_digest: str,
        resource_profile: str,
        environment_policy_digest: str,
        execution_authority: ExecutionAuthorityClass,
        outcome: ProcessOutcome,
        exit_code: int | None,
        signal: str | None,
        started_at: str,
        ended_at: str,
        duration_seconds: float,
        stdout_digest: str,
        stderr_digest: str,
        stdout_bytes: int,
        stderr_bytes: int,
        stdout_truncated: bool,
        stderr_truncated: bool,
        group_cleanup_claim: str,
        command_fingerprint: str,
    ) -> ProcessReceiptV1:
        values = {
            "lease_id": lease_id,
            "lease_digest": lease_digest,
            "use_ordinal": use_ordinal,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "workspace_identity_digest": workspace_identity_digest,
            "tool_identity": tool_identity,
            "intent_digest": intent_digest,
            "executable_digest": executable_digest,
            "argv_digest": argv_digest,
            "cwd_digest": cwd_digest,
            "resource_profile": resource_profile,
            "environment_policy_digest": environment_policy_digest,
            "execution_authority": execution_authority,
            "outcome": outcome,
            "exit_code": exit_code,
            "signal": signal,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "stdout_digest": stdout_digest,
            "stderr_digest": stderr_digest,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "group_cleanup_claim": group_cleanup_claim,
            "command_fingerprint": command_fingerprint,
            "receipt_version": "process_receipt_v1",
        }
        return cls(**values, receipt_digest=canonical_json_digest(values))

    @classmethod
    def from_json(cls, value: object) -> ProcessReceiptV1:
        if not isinstance(value, dict):
            raise ValueError("process receipt must be an object")
        expected_keys = {
            "lease_id",
            "lease_digest",
            "use_ordinal",
            "goal_id",
            "goal_revision",
            "workspace_identity_digest",
            "tool_identity",
            "intent_digest",
            "executable_digest",
            "argv_digest",
            "cwd_digest",
            "resource_profile",
            "environment_policy_digest",
            "execution_authority",
            "outcome",
            "exit_code",
            "signal",
            "started_at",
            "ended_at",
            "duration_seconds",
            "stdout_digest",
            "stderr_digest",
            "stdout_bytes",
            "stderr_bytes",
            "stdout_truncated",
            "stderr_truncated",
            "group_cleanup_claim",
            "command_fingerprint",
            "receipt_digest",
            "receipt_version",
        }
        if set(value) != expected_keys:
            raise ValueError("process receipt has unknown or missing fields")
        try:
            return cls(
                **{
                    **value,
                    "execution_authority": ExecutionAuthorityClass(
                        value["execution_authority"]
                    ),
                    "outcome": ProcessOutcome(value["outcome"]),
                }
            )
        except (TypeError, ValueError) as error:
            raise ValueError("process receipt is invalid") from error

    def to_json(self) -> dict[str, JSONValue]:
        return {
            **self._digest_values(),
            "execution_authority": self.execution_authority.value,
            "outcome": self.outcome.value,
            "receipt_digest": self.receipt_digest,
        }

    def _digest_values(self) -> dict[str, object]:
        return {
            "lease_id": self.lease_id,
            "lease_digest": self.lease_digest,
            "use_ordinal": self.use_ordinal,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "workspace_identity_digest": self.workspace_identity_digest,
            "tool_identity": self.tool_identity,
            "intent_digest": self.intent_digest,
            "executable_digest": self.executable_digest,
            "argv_digest": self.argv_digest,
            "cwd_digest": self.cwd_digest,
            "resource_profile": self.resource_profile,
            "environment_policy_digest": self.environment_policy_digest,
            "execution_authority": self.execution_authority,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "signal": self.signal,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "stdout_digest": self.stdout_digest,
            "stderr_digest": self.stderr_digest,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "group_cleanup_claim": self.group_cleanup_claim,
            "command_fingerprint": self.command_fingerprint,
            "receipt_version": self.receipt_version,
        }

    def __post_init__(self) -> None:
        for name, value in (
            ("receipt_digest", self.receipt_digest),
            ("lease_id", self.lease_id),
            ("lease_digest", self.lease_digest),
            ("goal_id", self.goal_id),
            ("workspace_identity_digest", self.workspace_identity_digest),
            ("tool_identity", self.tool_identity),
            ("intent_digest", self.intent_digest),
            ("executable_digest", self.executable_digest),
            ("argv_digest", self.argv_digest),
            ("cwd_digest", self.cwd_digest),
            ("resource_profile", self.resource_profile),
            ("environment_policy_digest", self.environment_policy_digest),
            ("started_at", self.started_at),
            ("ended_at", self.ended_at),
            ("stdout_digest", self.stdout_digest),
            ("stderr_digest", self.stderr_digest),
            ("group_cleanup_claim", self.group_cleanup_claim),
            ("command_fingerprint", self.command_fingerprint),
            ("receipt_version", self.receipt_version),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"process receipt {name} must not be empty")
        if self.receipt_version != "process_receipt_v1":
            raise ValueError("process receipt version is invalid")
        if (
            not isinstance(self.goal_revision, int)
            or isinstance(self.goal_revision, bool)
            or not isinstance(self.use_ordinal, int)
            or isinstance(self.use_ordinal, bool)
            or self.goal_revision < 0
            or self.use_ordinal < 1
        ):
            raise ValueError("process receipt goal_revision/use_ordinal must be non-negative")
        if (
            not isinstance(self.duration_seconds, int | float)
            or isinstance(self.duration_seconds, bool)
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds < 0
        ):
            raise ValueError("process receipt duration must be finite and non-negative")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (self.stdout_bytes, self.stderr_bytes)
        ):
            raise ValueError("process receipt output byte counts must be non-negative")
        if not isinstance(self.stdout_truncated, bool) or not isinstance(
            self.stderr_truncated, bool
        ):
            raise ValueError("process receipt truncation flags must be booleans")
        if not isinstance(self.outcome, ProcessOutcome):
            raise ValueError("process receipt outcome must be a closed ProcessOutcome")
        if self.execution_authority is not ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS:
            raise ValueError("process receipt must use LOCAL_SAME_UID_PROCESS authority")
        if self.outcome is ProcessOutcome.EXITED and self.exit_code is None:
            raise ValueError("exited process receipt must carry exit_code")
        if self.outcome is not ProcessOutcome.EXITED and self.exit_code is not None:
            raise ValueError("non-exited process receipt must not carry exit_code")
        if self.outcome is ProcessOutcome.SIGNALED and not self.signal:
            raise ValueError("signaled process receipt must carry a signal")
        if self.outcome is not ProcessOutcome.SIGNALED and self.signal is not None:
            raise ValueError("non-signaled process receipt must not carry a signal")
        if (
            self.outcome is ProcessOutcome.TIMED_OUT_REAPED
            and self.group_cleanup_claim != "reaped"
        ):
            raise ValueError("timed out process receipt requires reaped cleanup claim")
        digest_fields = (
            self.receipt_digest,
            self.lease_digest,
            self.tool_identity,
            self.intent_digest,
            self.executable_digest,
            self.argv_digest,
            self.cwd_digest,
            self.environment_policy_digest,
            self.stdout_digest,
            self.stderr_digest,
            self.command_fingerprint,
        )
        if any(
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in digest_fields
        ):
            raise ValueError("process receipt digests must be 64 lowercase hex")
        if canonical_json_digest(self._digest_values()) != self.receipt_digest:
            raise ValueError("process receipt digest mismatch")


# --------------------------------------------------------------------------- #
# 017 native sandbox durable authority。Runtime 只持久化用户批准的 exact
# command + policy identity；backend/image/snapshot/bundle 不是 authority 成员。
# lease 是 one-shot，并在 EXECUTING checkpoint 中消费。
# --------------------------------------------------------------------------- #

SANDBOX_MAX_USES = 1
SANDBOX_EXPIRY_MINUTES = 120
MAX_SANDBOX_LEASES = 16
_SANDBOX_RECEIPT_OUTCOMES = frozenset(
    {"exited", "signaled", "timed_out_reaped"},
)
_SANDBOX_MODES = frozenset(
    {"read-only", "workspace-write", "danger-full-access"},
)
_SANDBOX_NETWORK_MODES = frozenset({"off", "full"})
_SANDBOX_BACKENDS = frozenset({"seatbelt", "none"})
_SANDBOX_ENFORCEMENTS = frozenset({"confined", "unconfined"})


def _require_sandbox_digest(value: object, name: str) -> str:
    import re as _re

    valid = isinstance(value, str) and _re.fullmatch(r"[0-9a-f]{64}", value)
    if not valid:
        raise ValueError(f"sandbox authority {name} must be a valid digest")
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class SandboxAuthorityCandidateV1:
    """approval request 的 exact native command/policy 投影。"""

    candidate_id: str
    candidate_digest: str
    goal_id: str
    goal_revision: int
    workspace_identity_digest: str
    original_command_fingerprint: str
    policy_digest: str
    mode: str
    network: str
    readable_command: str
    trust_notice_id: str
    trust_notice_digest: str
    issued_at: str
    execution_authority: ExecutionAuthorityClass = (
        ExecutionAuthorityClass.ISOLATED_SANDBOX
    )

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        original_command_fingerprint: str,
        policy_digest: str,
        mode: str,
        network: str,
        readable_command: str,
        trust_notice_id: str,
        trust_notice_digest: str,
        issued_at: str,
    ) -> SandboxAuthorityCandidateV1:
        # R1（2026-10-03 follow-up）：issued_at 不进 candidate digest——审批后的
        # 重 prepare 会携带新 issued_at；digest 漂移会让 exact lease 永远 miss
        # 并把 stale grant 变成 invariant 冲突。digest 只绑定批准面（命令/策略/
        # 模式/网络/预览），同绑定 ⇒ 同 digest；同 fingerprint 的 timeout 变更仍
        # 改变 digest（wall deadline 在 binding/digest 输入内），保持重批语义。
        values = {
            "candidate_id": candidate_id,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "workspace_identity_digest": workspace_identity_digest,
            "original_command_fingerprint": original_command_fingerprint,
            "policy_digest": policy_digest,
            "mode": mode,
            "network": network,
            "readable_command": readable_command,
            "trust_notice_id": trust_notice_id,
            "trust_notice_digest": trust_notice_digest,
            "execution_authority": ExecutionAuthorityClass.ISOLATED_SANDBOX.value,
        }
        return cls(
            candidate_digest=canonical_json_digest(values),
            goal_revision=goal_revision,
            **{
                key: value for key, value in values.items()
                if key not in ("goal_revision", "execution_authority")
            },
            issued_at=issued_at,
        )

    def _digest_values(self) -> dict[str, JSONValue]:
        # R1（2026-10-03 follow-up）：与 create() 一致，issued_at 不参与 digest。
        return {
            "candidate_id": self.candidate_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "workspace_identity_digest": self.workspace_identity_digest,
            "original_command_fingerprint": self.original_command_fingerprint,
            "policy_digest": self.policy_digest,
            "mode": self.mode,
            "network": self.network,
            "readable_command": self.readable_command,
            "trust_notice_id": self.trust_notice_id,
            "trust_notice_digest": self.trust_notice_digest,
            "execution_authority": self.execution_authority.value,
        }

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("candidate_digest", self.candidate_digest),
            ("goal_id", self.goal_id),
            ("workspace_identity_digest", self.workspace_identity_digest),
            ("readable_command", self.readable_command),
            ("trust_notice_id", self.trust_notice_id),
            ("trust_notice_digest", self.trust_notice_digest),
            ("issued_at", self.issued_at),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"sandbox candidate {name} must not be empty")
        if (
            not isinstance(self.goal_revision, int)
            or isinstance(self.goal_revision, bool)
            or self.goal_revision < 1
        ):
            raise ValueError("sandbox candidate goal_revision must be positive")
        _require_sandbox_digest(
            self.original_command_fingerprint, "original_command_fingerprint",
        )
        _require_sandbox_digest(self.policy_digest, "policy_digest")
        _require_sandbox_digest(self.trust_notice_digest, "trust_notice_digest")
        if self.mode not in _SANDBOX_MODES:
            raise ValueError("sandbox candidate mode must be closed")
        if self.network not in _SANDBOX_NETWORK_MODES:
            raise ValueError("sandbox candidate network must be closed")
        if self.execution_authority is not ExecutionAuthorityClass.ISOLATED_SANDBOX:
            raise ValueError("sandbox candidate must use ISOLATED_SANDBOX authority")
        if canonical_json_digest(self._digest_values()) != self.candidate_digest:
            raise ValueError("sandbox candidate digest mismatch")


@dataclass(frozen=True, slots=True)
class SandboxAuthorityLeaseV1:
    """ResolveApproval 铸造的 exact、one-shot、可过期 durable lease。"""

    lease_id: str
    lease_digest: str
    candidate_digest: str
    goal_id: str
    goal_revision: int
    workspace_identity_digest: str
    original_command_fingerprint: str
    policy_digest: str
    mode: str
    network: str
    readable_command: str
    trust_notice_id: str
    trust_notice_digest: str
    approved_request_identity: str
    issued_at: str
    expires_at: str
    max_uses: int = SANDBOX_MAX_USES
    uses_consumed: int = 0

    @classmethod
    def create(
        cls,
        *,
        lease_id: str,
        candidate_digest: str,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        original_command_fingerprint: str,
        policy_digest: str,
        mode: str,
        network: str,
        readable_command: str,
        trust_notice_id: str,
        trust_notice_digest: str,
        approved_request_identity: str,
        issued_at: str,
        expires_at: str,
    ) -> SandboxAuthorityLeaseV1:
        values = {
            "lease_id": lease_id,
            "candidate_digest": candidate_digest,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "workspace_identity_digest": workspace_identity_digest,
            "original_command_fingerprint": original_command_fingerprint,
            "policy_digest": policy_digest,
            "mode": mode,
            "network": network,
            "readable_command": readable_command,
            "trust_notice_id": trust_notice_id,
            "trust_notice_digest": trust_notice_digest,
            "approved_request_identity": approved_request_identity,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "max_uses": SANDBOX_MAX_USES,
        }
        return cls(
            lease_digest=canonical_json_digest(values),
            goal_revision=goal_revision,
            **{key: value for key, value in values.items() if key != "goal_revision"},
        )

    def _digest_values(self) -> dict[str, JSONValue]:
        return {
            "lease_id": self.lease_id,
            "candidate_digest": self.candidate_digest,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "workspace_identity_digest": self.workspace_identity_digest,
            "original_command_fingerprint": self.original_command_fingerprint,
            "policy_digest": self.policy_digest,
            "mode": self.mode,
            "network": self.network,
            "readable_command": self.readable_command,
            "trust_notice_id": self.trust_notice_id,
            "trust_notice_digest": self.trust_notice_digest,
            "approved_request_identity": self.approved_request_identity,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "max_uses": self.max_uses,
        }

    def __post_init__(self) -> None:
        for name, value in (
            ("lease_id", self.lease_id),
            ("lease_digest", self.lease_digest),
            ("candidate_digest", self.candidate_digest),
            ("goal_id", self.goal_id),
            ("workspace_identity_digest", self.workspace_identity_digest),
            ("readable_command", self.readable_command),
            ("trust_notice_id", self.trust_notice_id),
            ("trust_notice_digest", self.trust_notice_digest),
            ("approved_request_identity", self.approved_request_identity),
            ("issued_at", self.issued_at),
            ("expires_at", self.expires_at),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"sandbox lease {name} must not be empty")
        if (
            not isinstance(self.goal_revision, int)
            or isinstance(self.goal_revision, bool)
            or self.goal_revision < 1
        ):
            raise ValueError("sandbox lease goal_revision must be positive")
        _require_sandbox_digest(
            self.original_command_fingerprint, "original_command_fingerprint",
        )
        _require_sandbox_digest(self.policy_digest, "policy_digest")
        _require_sandbox_digest(self.trust_notice_digest, "trust_notice_digest")
        if self.mode not in _SANDBOX_MODES:
            raise ValueError("sandbox lease mode must be closed")
        if self.network not in _SANDBOX_NETWORK_MODES:
            raise ValueError("sandbox lease network must be closed")
        if self.max_uses != SANDBOX_MAX_USES:
            raise ValueError("sandbox lease max_uses must be fixed at 1")
        if (
            not isinstance(self.uses_consumed, int)
            or isinstance(self.uses_consumed, bool)
            or not 0 <= self.uses_consumed <= SANDBOX_MAX_USES
        ):
            raise ValueError("sandbox lease uses_consumed out of range")
        if canonical_json_digest(self._digest_values()) != self.lease_digest:
            raise ValueError("sandbox lease digest mismatch")

    def verify(self) -> bool:
        """防篡改 oracle：重算 digest 与携带值比对。"""

        try:
            return canonical_json_digest(self._digest_values()) == self.lease_digest
        except (ValueError, TypeError):
            return False

    def matches(
        self,
        *,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        original_command_fingerprint: str,
        policy_digest: str,
        mode: str,
        network: str,
    ) -> bool:
        """exact 匹配：全部 binding identity 相等（spec 漂移即失配）。"""

        return (
            self.goal_id == goal_id
            and self.goal_revision == goal_revision
            and self.workspace_identity_digest == workspace_identity_digest
            and self.original_command_fingerprint == original_command_fingerprint
            and self.policy_digest == policy_digest
            and self.mode == mode
            and self.network == network
        )

    def with_use_consumed(self, uses: int) -> SandboxAuthorityLeaseV1:
        """单调递增 uses_consumed（digest 不变——uses 不在 lease identity 内）。"""

        if not isinstance(uses, int) or isinstance(uses, bool):
            raise ValueError("uses must be an int")
        if uses <= self.uses_consumed:
            raise ValueError("lease uses_consumed must increase monotonically")
        if uses > SANDBOX_MAX_USES:
            raise ValueError("lease use budget exhausted")
        return SandboxAuthorityLeaseV1(
            lease_id=self.lease_id,
            lease_digest=self.lease_digest,
            candidate_digest=self.candidate_digest,
            goal_id=self.goal_id,
            goal_revision=self.goal_revision,
            workspace_identity_digest=self.workspace_identity_digest,
            original_command_fingerprint=self.original_command_fingerprint,
            policy_digest=self.policy_digest,
            mode=self.mode,
            network=self.network,
            readable_command=self.readable_command,
            trust_notice_id=self.trust_notice_id,
            trust_notice_digest=self.trust_notice_digest,
            approved_request_identity=self.approved_request_identity,
            issued_at=self.issued_at,
            expires_at=self.expires_at,
            max_uses=self.max_uses,
            uses_consumed=uses,
        )


@dataclass(frozen=True, slots=True)
class BackgroundSandboxReceiptV1:
    """由 exact background action authority 铸造的 sandbox receipt。"""

    receipt_id: str
    receipt_digest: str
    background_action_authority_digest: str
    occurrence_binding_digest: str
    goal_id: str
    goal_revision: int
    workspace_identity_digest: str
    original_command_fingerprint: str
    policy_digest: str
    mode: str
    network: str
    backend: str
    enforcement: str
    profile_digest: str
    outcome: str
    draft_digest: str
    issued_at: str

    @classmethod
    def create(cls, **kwargs: object) -> BackgroundSandboxReceiptV1:
        values = {
            name: kwargs[name]
            for name in cls.__dataclass_fields__
            if name != "receipt_digest"
        }
        return cls(receipt_digest=canonical_json_digest(values), **values)  # type: ignore[arg-type]

    def _digest_values(self) -> dict[str, JSONValue]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "receipt_digest"
        }

    def __post_init__(self) -> None:
        for name in (
            "receipt_id",
            "goal_id",
            "workspace_identity_digest",
            "issued_at",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"background sandbox receipt {name} must not be empty")
        if (
            not isinstance(self.goal_revision, int)
            or isinstance(self.goal_revision, bool)
            or self.goal_revision < 1
        ):
            raise ValueError("background sandbox receipt goal_revision must be positive")
        for name in (
            "receipt_digest",
            "background_action_authority_digest",
            "occurrence_binding_digest",
            "original_command_fingerprint",
            "policy_digest",
            "draft_digest",
        ):
            _require_sandbox_digest(getattr(self, name), name)
        if self.mode not in _SANDBOX_MODES or self.network not in _SANDBOX_NETWORK_MODES:
            raise ValueError("background sandbox receipt mode/network must be closed")
        if self.backend not in _SANDBOX_BACKENDS or self.enforcement not in _SANDBOX_ENFORCEMENTS:
            raise ValueError("background sandbox receipt enforcement facts must be closed")
        if (
            self.backend != "seatbelt"
            or self.enforcement != "confined"
            or self.mode == "danger-full-access"
            or self.network != "off"
        ):
            raise ValueError("background sandbox receipt must prove confined network-off execution")
        _require_sandbox_digest(self.profile_digest, "profile_digest")
        if self.outcome not in _SANDBOX_RECEIPT_OUTCOMES:
            raise ValueError("background sandbox receipt outcome must be closed")
        if canonical_json_digest(self._digest_values()) != self.receipt_digest:
            raise ValueError("background sandbox receipt digest mismatch")

    def to_json(self) -> dict[str, JSONValue]:
        return {**self._digest_values(), "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class SandboxReceiptV1:
    """Runtime 铸造的 native sandbox durable execution receipt。"""

    receipt_id: str
    receipt_digest: str
    lease_id: str
    lease_digest: str
    candidate_digest: str
    goal_id: str
    goal_revision: int
    workspace_identity_digest: str
    original_command_fingerprint: str
    policy_digest: str
    mode: str
    network: str
    backend: str
    enforcement: str
    profile_digest: str
    outcome: str
    draft_digest: str
    issued_at: str

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        lease_id: str,
        lease_digest: str,
        candidate_digest: str,
        goal_id: str,
        goal_revision: int,
        workspace_identity_digest: str,
        original_command_fingerprint: str,
        policy_digest: str,
        mode: str,
        network: str,
        backend: str,
        enforcement: str,
        profile_digest: str,
        outcome: str,
        draft_digest: str,
        issued_at: str,
    ) -> SandboxReceiptV1:
        values = {
            "receipt_id": receipt_id,
            "lease_id": lease_id,
            "lease_digest": lease_digest,
            "candidate_digest": candidate_digest,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "workspace_identity_digest": workspace_identity_digest,
            "original_command_fingerprint": original_command_fingerprint,
            "policy_digest": policy_digest,
            "mode": mode,
            "network": network,
            "backend": backend,
            "enforcement": enforcement,
            "profile_digest": profile_digest,
            "outcome": outcome,
            "draft_digest": draft_digest,
            "issued_at": issued_at,
        }
        return cls(receipt_digest=canonical_json_digest(values), **values)

    def _digest_values(self) -> dict[str, JSONValue]:
        return {
            "receipt_id": self.receipt_id,
            "lease_id": self.lease_id,
            "lease_digest": self.lease_digest,
            "candidate_digest": self.candidate_digest,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "workspace_identity_digest": self.workspace_identity_digest,
            "original_command_fingerprint": self.original_command_fingerprint,
            "policy_digest": self.policy_digest,
            "mode": self.mode,
            "network": self.network,
            "backend": self.backend,
            "enforcement": self.enforcement,
            "profile_digest": self.profile_digest,
            "outcome": self.outcome,
            "draft_digest": self.draft_digest,
            "issued_at": self.issued_at,
        }

    def __post_init__(self) -> None:
        for name, value in (
            ("receipt_id", self.receipt_id),
            ("receipt_digest", self.receipt_digest),
            ("lease_id", self.lease_id),
            ("goal_id", self.goal_id),
            ("workspace_identity_digest", self.workspace_identity_digest),
            ("issued_at", self.issued_at),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"sandbox receipt {name} must not be empty")
        if (
            not isinstance(self.goal_revision, int)
            or isinstance(self.goal_revision, bool)
            or self.goal_revision < 1
        ):
            raise ValueError("sandbox receipt goal_revision must be positive")
        for name in (
            "lease_digest", "candidate_digest", "original_command_fingerprint",
            "policy_digest", "draft_digest",
        ):
            _require_sandbox_digest(getattr(self, name), name)
        if self.mode not in _SANDBOX_MODES or self.network not in _SANDBOX_NETWORK_MODES:
            raise ValueError("sandbox receipt mode/network must be closed")
        if self.backend not in _SANDBOX_BACKENDS or self.enforcement not in _SANDBOX_ENFORCEMENTS:
            raise ValueError("sandbox receipt enforcement facts must be closed")
        if self.backend == "seatbelt":
            if self.enforcement != "confined":
                raise ValueError("seatbelt receipt must be confined")
            _require_sandbox_digest(self.profile_digest, "profile_digest")
        elif self.enforcement != "unconfined" or self.profile_digest:
            raise ValueError("native bypass receipt must be unconfined without profile")
        # 与 KernelToolRuntime._sandbox_outcome 同一二维矩阵：唯一 unconfined
        # bypass 是 danger-full-access + network=full；danger+off 与所有
        # confined 组合的 receipt 都必须 seatbelt/confined 且携带 profile digest。
        if (
            self.mode == "danger-full-access"
            and self.network == "full"
            and self.backend != "none"
        ):
            raise ValueError(
                "danger-full-access network-full receipt must record native bypass"
            )
        if (
            not (self.mode == "danger-full-access" and self.network == "full")
            and self.backend != "seatbelt"
        ):
            raise ValueError("confined policy receipt must record seatbelt")
        _require_sandbox_digest(self.draft_digest, "draft_digest")
        if self.outcome not in _SANDBOX_RECEIPT_OUTCOMES:
            raise ValueError(f"unknown sandbox receipt outcome: {self.outcome!r}")
        if canonical_json_digest(self._digest_values()) != self.receipt_digest:
            raise ValueError("sandbox receipt digest mismatch")

    def to_json(self) -> dict[str, JSONValue]:
        return {**self._digest_values(), "receipt_digest": self.receipt_digest}

    @classmethod
    def from_json(cls, value: object) -> SandboxReceiptV1:
        if not isinstance(value, dict):
            raise ValueError("sandbox receipt must be an object")
        expected = {*cls.__dataclass_fields__}
        if set(value) != expected:
            raise ValueError("sandbox receipt has unknown or missing fields")
        try:
            return cls(**value)
        except (TypeError, ValueError) as error:
            raise ValueError("sandbox receipt is invalid") from error


# 018 governed browser tasks：mode/consequence 的 closed 字符串值
#（runtime 不 import browser 包——依赖方向只能是 browser → runtime）。
BROWSER_MODE_VALUES = frozenset(
    {
        "public_read_ephemeral",
        "site_bound_interactive",
        "task_loopback_ephemeral",
    }
)
BROWSER_CONSEQUENCE_VALUES = frozenset(
    {"observe", "disclose", "download", "upload", "commit"}
)
BROWSER_LEASE_MAX_USES = 1


def _require_browser_mode(value: str) -> None:
    if value not in BROWSER_MODE_VALUES:
        raise ValueError("browser mode must be a closed member")


def _require_browser_consequence(value: str) -> None:
    if value not in BROWSER_CONSEQUENCE_VALUES:
        raise ValueError("browser consequence must be a closed member")


def _require_browser_datetime(value: str, field: str) -> None:
    # durable 时间一律带时区 RFC3339 字符串（不 checkpoint monotonic）；
    # 校验与比较都用解析后的 zoned datetime，绝不依赖字符串序。
    _parse_browser_datetime(value, field)


def _parse_browser_datetime(value: str, field: str):
    # 2026-10-05 真实 D06 运行暴露：产品时钟产出 "…Z"（_default_utc_now），而
    # browser binding 用 isoformat 的 "…+00:00"；两种 zoned RFC3339 形式都必须
    # 接受（原 value[-6] 检查误拒 Z 形式，真实审批路径直接崩）。
    if not isinstance(value, str) or "T" not in value:
        raise ValueError(f"browser {field} must be a zoned RFC3339 string")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    if len(value) < 6 or value[-6] not in "+-":
        raise ValueError(f"browser {field} must be a zoned RFC3339 string")
    from datetime import datetime

    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError(f"browser {field} must carry a timezone offset")
    return parsed


@dataclass(frozen=True, slots=True)
class BrowserActionCandidateV1:
    """approval request 的 closed typed browser 投影（018 spec §6）。

    持久化在 ``ApprovalRequest.browser_action_candidate`` 上，随
    AWAITING_APPROVAL checkpoint strict round-trip；restart 后只能从该
    durable candidate 铸造 lease。digest 覆盖全部绑定字段。
    """

    candidate_id: str
    candidate_digest: str
    goal_id: str
    goal_revision: int
    session_ref: str
    browser_identity_digest: str
    profile_ref: str | None
    profile_revision: int | None
    allowed_origins: tuple[str, ...]
    mode: str
    page_id: str
    frame_id: str
    observation_digest: str
    action_digest: str
    consequence: str
    preview: str
    issued_at: str
    expires_at: str
    max_uses: int = BROWSER_LEASE_MAX_USES

    @classmethod
    def create(cls, **kwargs: object) -> BrowserActionCandidateV1:
        values = {
            "candidate_id": kwargs["candidate_id"],
            "goal_id": kwargs["goal_id"],
            "goal_revision": kwargs["goal_revision"],
            "session_ref": kwargs["session_ref"],
            "browser_identity_digest": kwargs["browser_identity_digest"],
            "profile_ref": kwargs["profile_ref"],
            "profile_revision": kwargs["profile_revision"],
            "allowed_origins": tuple(kwargs["allowed_origins"]),  # type: ignore[arg-type]
            "mode": kwargs["mode"],
            "page_id": kwargs["page_id"],
            "frame_id": kwargs["frame_id"],
            "observation_digest": kwargs["observation_digest"],
            "action_digest": kwargs["action_digest"],
            "consequence": kwargs["consequence"],
            "preview": kwargs["preview"],
            "issued_at": kwargs["issued_at"],
            "expires_at": kwargs["expires_at"],
            "max_uses": BROWSER_LEASE_MAX_USES,
        }
        return cls(candidate_digest=canonical_json_digest(values), **values)  # type: ignore[arg-type]

    def _digest_values(self) -> dict[str, JSONValue]:
        return {
            "candidate_id": self.candidate_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "session_ref": self.session_ref,
            "browser_identity_digest": self.browser_identity_digest,
            "profile_ref": self.profile_ref,
            "profile_revision": self.profile_revision,
            "allowed_origins": list(self.allowed_origins),
            "mode": self.mode,
            "page_id": self.page_id,
            "frame_id": self.frame_id,
            "observation_digest": self.observation_digest,
            "action_digest": self.action_digest,
            "consequence": self.consequence,
            "preview": self.preview,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "max_uses": self.max_uses,
        }

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("candidate_digest", self.candidate_digest),
            ("goal_id", self.goal_id),
            ("session_ref", self.session_ref),
            ("browser_identity_digest", self.browser_identity_digest),
            ("observation_digest", self.observation_digest),
            ("action_digest", self.action_digest),
            ("preview", self.preview),
        ):
            if not value:
                raise ValueError(f"browser candidate {name} must not be empty")
        if self.goal_revision < 0:
            raise ValueError("browser candidate goal_revision must be non-negative")
        if (self.profile_ref is None) != (self.profile_revision is None):
            raise ValueError("browser candidate profile binding must be paired")
        if self.mode == "public_read_ephemeral" and self.profile_ref is not None:
            raise ValueError("public-read candidate must not bind a profile")
        _require_browser_mode(self.mode)
        _require_browser_consequence(self.consequence)
        _require_browser_datetime(self.issued_at, "issued_at")
        _require_browser_datetime(self.expires_at, "expires_at")
        if self.max_uses != BROWSER_LEASE_MAX_USES:
            raise ValueError("browser candidate max_uses must be fixed at 1")
        if canonical_json_digest(self._digest_values()) != self.candidate_digest:
            raise ValueError("browser candidate digest mismatch")


@dataclass(frozen=True, slots=True)
class BrowserAuthorityLeaseV1:
    """ResolveApproval 铸造的 exact、one-shot、RFC3339 可过期 durable lease。

    ``authorizes`` 要求全部 binding identity exact equal（无 wildcard）；
    public-read lease 不能授权 interactive consequence；uses_consumed 超过
    max_uses 在构造层 fail closed。
    """

    lease_id: str
    lease_digest: str
    candidate_digest: str
    goal_id: str
    goal_revision: int
    session_ref: str
    browser_identity_digest: str
    profile_ref: str | None
    profile_revision: int | None
    allowed_origins: tuple[str, ...]
    mode: str
    page_id: str
    frame_id: str
    observation_digest: str
    action_digest: str
    consequence: str
    approved_request_identity: str
    issued_at: str
    expires_at: str
    max_uses: int = BROWSER_LEASE_MAX_USES
    uses_consumed: int = 0

    @classmethod
    def create(
        cls,
        *,
        lease_id: str,
        candidate_digest: str,
        goal_id: str,
        goal_revision: int,
        session_ref: str,
        browser_identity_digest: str,
        profile_ref: str | None,
        profile_revision: int | None,
        allowed_origins: tuple[str, ...],
        mode: str,
        page_id: str,
        frame_id: str,
        observation_digest: str,
        action_digest: str,
        consequence: str,
        approved_request_identity: str,
        issued_at: str,
        expires_at: str,
        max_uses: int = BROWSER_LEASE_MAX_USES,
        uses_consumed: int = 0,
    ) -> BrowserAuthorityLeaseV1:
        values = {
            "lease_id": lease_id,
            "candidate_digest": candidate_digest,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "session_ref": session_ref,
            "browser_identity_digest": browser_identity_digest,
            "profile_ref": profile_ref,
            "profile_revision": profile_revision,
            "allowed_origins": list(allowed_origins),
            "mode": mode,
            "page_id": page_id,
            "frame_id": frame_id,
            "observation_digest": observation_digest,
            "action_digest": action_digest,
            "consequence": consequence,
            "approved_request_identity": approved_request_identity,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "max_uses": max_uses,
        }
        return cls(
            lease_digest=canonical_json_digest(values),
            uses_consumed=uses_consumed,
            allowed_origins=allowed_origins,
            **{key: value for key, value in values.items() if key != "allowed_origins"},
        )

    def with_use_consumed(self, count: int) -> BrowserAuthorityLeaseV1:
        if count > self.max_uses:
            raise ValueError("browser lease use exhausted")
        return replace(self, uses_consumed=count)

    def authorizes(
        self,
        *,
        goal_id: str,
        goal_revision: int,
        session_ref: str,
        browser_identity_digest: str,
        profile_ref: str | None,
        profile_revision: int | None,
        allowed_origins: tuple[str, ...],
        mode: str,
        page_id: str,
        frame_id: str,
        observation_digest: str,
        action_digest: str,
        consequence: str,
        now: str,
    ) -> bool:
        # public-read lease 只能授权 observe 类 consequence（spec §4.1）。
        if self.mode == "public_read_ephemeral" and consequence != "observe":
            return False
        if (
            self.goal_id != goal_id
            or self.goal_revision != goal_revision
            or self.session_ref != session_ref
            or self.browser_identity_digest != browser_identity_digest
            or self.profile_ref != profile_ref
            or self.profile_revision != profile_revision
            or tuple(self.allowed_origins) != tuple(allowed_origins)
            or self.mode != mode
            or self.page_id != page_id
            or self.frame_id != frame_id
            or self.observation_digest != observation_digest
            or self.action_digest != action_digest
            or self.consequence != consequence
        ):
            return False
        if self.uses_consumed >= self.max_uses:
            return False
        now_dt = _parse_browser_datetime(now, "now")
        expires_dt = _parse_browser_datetime(self.expires_at, "expires_at")
        return now_dt < expires_dt

    def __post_init__(self) -> None:
        for name, value in (
            ("lease_id", self.lease_id),
            ("lease_digest", self.lease_digest),
            ("candidate_digest", self.candidate_digest),
            ("goal_id", self.goal_id),
            ("session_ref", self.session_ref),
            ("browser_identity_digest", self.browser_identity_digest),
            ("observation_digest", self.observation_digest),
            ("action_digest", self.action_digest),
            ("approved_request_identity", self.approved_request_identity),
        ):
            if not value:
                raise ValueError(f"browser lease {name} must not be empty")
        if (self.profile_ref is None) != (self.profile_revision is None):
            raise ValueError("browser lease profile binding must be paired")
        _require_browser_mode(self.mode)
        _require_browser_consequence(self.consequence)
        _require_browser_datetime(self.issued_at, "issued_at")
        _require_browser_datetime(self.expires_at, "expires_at")
        if self.max_uses != BROWSER_LEASE_MAX_USES:
            raise ValueError("browser lease max_uses must be fixed at 1")
        if self.uses_consumed < 0 or self.uses_consumed > self.max_uses:
            raise ValueError("browser lease uses_consumed out of range")


@dataclass(frozen=True, slots=True)
class BrowserTakeoverRequestV1:
    """user takeover 的 durable pending 请求（018 spec §7）。

    只携带 opaque identity/digest；不携带 credential、storage-state 或页面
    内容。complete 校验 exact request/session/profile 后递增期望 revision。
    """

    request_id: str
    session_ref: str
    profile_ref: str
    profile_revision: int
    browser_identity_digest: str
    goal_id: str
    goal_revision: int
    requested_at: str

    def __post_init__(self) -> None:
        for name, value in (
            ("request_id", self.request_id),
            ("session_ref", self.session_ref),
            ("profile_ref", self.profile_ref),
            ("browser_identity_digest", self.browser_identity_digest),
            ("goal_id", self.goal_id),
        ):
            if not value:
                raise ValueError(f"browser takeover {name} must not be empty")
        if self.profile_revision <= 0:
            raise ValueError("browser takeover profile_revision must be positive")
        if self.goal_revision < 0:
            raise ValueError("browser takeover goal_revision must be non-negative")
        _require_browser_datetime(self.requested_at, "requested_at")


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
    approval_basis_revision: int | None = None
    egress: str | None = None
    operation: str | None = None
    request_identity: str | None = None
    destination_digest: str | None = None
    cost_class: str | None = None
    # 017：sandbox approval 的 closed typed 投影（随 AWAITING_APPROVAL checkpoint
    # strict round-trip；restart 后只能从该 durable candidate 铸造 lease）。
    sandbox_authority_candidate: SandboxAuthorityCandidateV1 | None = None
    trust_notice_id: str | None = None
    trust_notice_digest: str | None = None
    # 015 governed local action：approval request 持久化完整 closed process candidate。
    # 放在字段末尾以保持 012-014 的位置前缀（见 test_014_contract_extensions_preserve_...）。
    process_authority_candidate: ProcessAuthorityCandidateV1 | None = None
    artifact_confirmation_requirement: ArtifactConfirmationRequirementV1 | None = None
    # 018：approval request 至多携带一个 strict browser candidate（单字段
    # 即结构上限）；restart 后只能从该 durable candidate 铸造 lease。
    browser_action_candidate: BrowserActionCandidateV1 | None = None

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
        if self.approval_basis_revision is not None and self.approval_basis_revision < 0:
            raise ValueError("approval_basis_revision must be non-negative")
        if (
            self.artifact_confirmation_requirement is not None
            and self.process_authority_candidate is None
        ):
            raise ValueError(
                "artifact confirmation requirement requires a process candidate"
            )
        # 018：一个 approval 至多携带一种 authority candidate——browser 与
        # process/sandbox 混合并存会让 lease 铸造歧义，fail closed。
        candidate_kinds = sum(
            1
            for candidate in (
                self.process_authority_candidate,
                self.sandbox_authority_candidate,
                self.browser_action_candidate,
            )
            if candidate is not None
        )
        if candidate_kinds > 1:
            raise ValueError(
                "approval request carries mixed authority candidates"
            )


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
    side_effect: SideEffectClass = SideEffectClass.WRITE
    egress: EgressClass = EgressClass.NONE
    # F5（review finding 2026-08-16）：EXECUTING record 的 authority 必须显式传入
    # （mark_executing 由 intent 投影），无默认。
    execution_authority: ExecutionAuthorityClass = field(kw_only=True)
    operation: str = "legacy_effect"
    request_identity: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_call_id or not self.intent_digest or not self.idempotency_key:
            raise ValueError("executing intent fields must not be empty")
        if not self.operation:
            raise ValueError("executing intent operation must not be empty")
        if self.request_identity is None:
            object.__setattr__(self, "request_identity", self.idempotency_key)
        if self.egress is EgressClass.PUBLIC_NETWORK and (
            self.side_effect is not SideEffectClass.READ_ONLY
        ):
            raise ValueError("PUBLIC_NETWORK executing intent must be read-only")


@dataclass(frozen=True, slots=True)
class ProviderCallIntentV1:
    action_seq: int
    provider_call_index: int
    context_digest: str
    request_digest: str
    disclosure_digest: str | None
    occurrence_binding_digest: str
    intent_digest: str

    @classmethod
    def create(
        cls,
        *,
        action_seq: int,
        provider_call_index: int,
        context_digest: str,
        disclosure_digest: str | None,
        occurrence_binding_digest: str,
    ) -> ProviderCallIntentV1:
        request_values = {
            "action_seq": action_seq,
            "provider_call_index": provider_call_index,
            "context_digest": context_digest,
        }
        request_digest = canonical_json_digest(request_values)
        intent_values = {
            **request_values,
            "request_digest": request_digest,
            "disclosure_digest": disclosure_digest,
            "occurrence_binding_digest": occurrence_binding_digest,
        }
        return cls(
            **intent_values,
            intent_digest=canonical_json_digest(intent_values),
        )

    def __post_init__(self) -> None:
        for name in ("action_seq", "provider_call_index"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"provider call {name} must be positive")
        for name in (
            "context_digest",
            "request_digest",
            "occurrence_binding_digest",
            "intent_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _is_lower_hex(value, length=64):
                raise ValueError(f"provider call {name} must be 64 lowercase hex")
        if self.disclosure_digest is not None and not _is_lower_hex(
            self.disclosure_digest,
            length=64,
        ):
            raise ValueError("provider call disclosure_digest must be 64 lowercase hex")
        request_values = {
            "action_seq": self.action_seq,
            "provider_call_index": self.provider_call_index,
            "context_digest": self.context_digest,
        }
        expected_request_digest = canonical_json_digest(request_values)
        expected_intent_digest = canonical_json_digest(
            {
                **request_values,
                "request_digest": expected_request_digest,
                "disclosure_digest": self.disclosure_digest,
                "occurrence_binding_digest": self.occurrence_binding_digest,
            }
        )
        if (
            self.request_digest != expected_request_digest
            or self.intent_digest != expected_intent_digest
        ):
            raise ValueError("provider call intent digest mismatch")


@dataclass(frozen=True, slots=True)
class ActiveRun:
    run_id: str
    # 由 Runtime 在首次接管 run 时写入；Resume 只复用，不能重置任务总时限。
    run_started_at: str | None = None
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
    provider_call_intent: ProviderCallIntentV1 | None = None
    persisted_model_response: PersistedModelResponseV1 | None = None
    model_calls_used: int = 0
    tool_calls_used: int = 0
    sandbox_commands_used: int = 0
    browser_actions_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    invocation_origin: InvocationOrigin = InvocationOrigin.MODEL

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must not be empty")
        if self.run_started_at is not None and (
            not isinstance(self.run_started_at, str)
            or _RFC3339_Z.fullmatch(self.run_started_at) is None
        ):
            raise ValueError("run_started_at must be zoned RFC3339")
        if not isinstance(self.invocation_origin, InvocationOrigin):
            raise TypeError("active run invocation origin must be closed")
        if self.batch_cursor < 0:
            raise ValueError("batch_cursor must be non-negative")
        if self.owner_invocation_id == "":
            raise ValueError("owner_invocation_id must not be empty")
        for name in (
            "model_calls_used",
            "tool_calls_used",
            "sandbox_commands_used",
            "browser_actions_used",
            "input_tokens_used",
            "output_tokens_used",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be non-negative")

        call_ids = tuple(call.tool_call_id for call in self.tool_calls)
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("tool_call_id must be unique within an active batch")
        if (
            self.invocation_origin is InvocationOrigin.OPERATOR
            and len(self.tool_calls) > 1
        ):
            raise ValueError("operator invocation cannot contain more than one tool call")
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

        if self.status is ActiveRunStatus.MODEL_EXECUTING:
            if (
                self.phase is not ContinuationPhase.MODEL
                or self.provider_call_intent is None
                or self.owner_invocation_id is None
                or self.pending_request is not None
                or self.model_calls_used != self.provider_call_intent.provider_call_index
                or (
                    self.persisted_model_response is not None
                    and self.persisted_model_response.request_digest
                    != self.provider_call_intent.request_digest
                )
            ):
                raise ValueError("MODEL_EXECUTING must bind one owned provider call")
        elif self.status is ActiveRunStatus.MODEL_OUTCOME_UNKNOWN:
            if (
                self.phase is not ContinuationPhase.MODEL
                or self.provider_call_intent is None
                or self.persisted_model_response is not None
                or self.owner_invocation_id is not None
                or self.pending_request is not None
                or self.model_calls_used != self.provider_call_intent.provider_call_index
            ):
                raise ValueError("MODEL_OUTCOME_UNKNOWN must retain only the call intent")
        elif self.provider_call_intent is not None or self.persisted_model_response is not None:
            raise ValueError("only provider boundary states may retain provider call data")

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
    # 2026-10-10：终态记录保留本次 run 的模型 usage（费用可观测性）。
    # None 表示旧 checkpoint / 非 run 终态路径；解码对缺失键向后兼容。
    model_calls_used: int | None = None
    input_tokens_used: int | None = None
    output_tokens_used: int | None = None


@dataclass(frozen=True, slots=True)
class BackgroundOccurrenceBindingV1:
    """Runtime checkpoint 中不含 raw capability 的 occurrence identity。"""

    automation_id: str
    automation_revision: int
    occurrence_id: str
    occurrence_index: int
    scheduled_for_utc: str
    definition_digest: str
    grant_digest: str
    claim_authority_digest: str
    claim_capability_digest: str
    checkpoint_identity_digest: str
    deadline_utc: str
    model_call_limit: int
    tool_call_limit: int
    sandbox_command_limit: int
    browser_action_limit: int
    max_input_tokens: int
    max_output_tokens: int
    binding_digest: str

    @classmethod
    def create(
        cls,
        *,
        automation_id: str,
        automation_revision: int,
        occurrence_id: str,
        occurrence_index: int,
        scheduled_for_utc: str,
        definition_digest: str,
        grant_digest: str,
        claim_authority_digest: str,
        claim_capability_digest: str,
        checkpoint_identity_digest: str,
        deadline_utc: str,
        model_call_limit: int,
        tool_call_limit: int,
        sandbox_command_limit: int,
        browser_action_limit: int,
        max_input_tokens: int,
        max_output_tokens: int,
    ) -> BackgroundOccurrenceBindingV1:
        values = {
            "automation_id": automation_id,
            "automation_revision": automation_revision,
            "occurrence_id": occurrence_id,
            "occurrence_index": occurrence_index,
            "scheduled_for_utc": scheduled_for_utc,
            "definition_digest": definition_digest,
            "grant_digest": grant_digest,
            "claim_authority_digest": claim_authority_digest,
            "claim_capability_digest": claim_capability_digest,
            "checkpoint_identity_digest": checkpoint_identity_digest,
            "deadline_utc": deadline_utc,
            "model_call_limit": model_call_limit,
            "tool_call_limit": tool_call_limit,
            "sandbox_command_limit": sandbox_command_limit,
            "browser_action_limit": browser_action_limit,
            "max_input_tokens": max_input_tokens,
            "max_output_tokens": max_output_tokens,
        }
        return cls(**values, binding_digest=canonical_json_digest(values))

    def __post_init__(self) -> None:
        for name in ("automation_id", "occurrence_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError(f"background binding {name} must be bounded non-empty text")
        for name in (
            "automation_revision",
            "model_call_limit",
            "tool_call_limit",
            "max_input_tokens",
            "max_output_tokens",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"background binding {name} must be positive")
        for name in ("sandbox_command_limit", "browser_action_limit"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"background binding {name} must be non-negative")
        if (
            not isinstance(self.occurrence_index, int)
            or isinstance(self.occurrence_index, bool)
            or self.occurrence_index < 0
        ):
            raise ValueError("background binding occurrence_index must be non-negative")
        for name in (
            "definition_digest",
            "grant_digest",
            "claim_authority_digest",
            "claim_capability_digest",
            "checkpoint_identity_digest",
            "binding_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _is_lower_hex(value, length=64):
                raise ValueError(f"background binding {name} must be 64 lowercase hex")
        from datetime import UTC, datetime

        for name in ("scheduled_for_utc", "deadline_utc"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"background binding {name} must be canonical UTC")
            try:
                parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=UTC
                )
            except ValueError as error:
                raise ValueError(
                    f"background binding {name} must be canonical UTC"
                ) from error
            if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
                raise ValueError(f"background binding {name} must be canonical UTC")
        values = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "binding_digest"
        }
        if canonical_json_digest(values) != self.binding_digest:
            raise ValueError("background binding digest mismatch")


@dataclass(frozen=True, slots=True)
class BackgroundExecutionAuthorityV1:
    """只驻留在 pre-bound occurrence composition 的 raw claim capability。"""

    occurrence_binding: BackgroundOccurrenceBindingV1
    claim_fencing_token: str
    raw_capability: str = field(repr=False)
    isolated_workspace_identity_digest: str = ""
    background_environment_policy_digest: str | None = None
    browser_origin_policy_digest: str | None = None

    @classmethod
    def create(
        cls,
        *,
        occurrence_binding: BackgroundOccurrenceBindingV1,
        claim_fencing_token: str,
        raw_capability: str,
        isolated_workspace_identity_digest: str,
        background_environment_policy_digest: str | None,
        browser_origin_policy_digest: str | None,
    ) -> BackgroundExecutionAuthorityV1:
        return cls(
            occurrence_binding=occurrence_binding,
            claim_fencing_token=claim_fencing_token,
            raw_capability=raw_capability,
            isolated_workspace_identity_digest=isolated_workspace_identity_digest,
            background_environment_policy_digest=(
                background_environment_policy_digest
            ),
            browser_origin_policy_digest=browser_origin_policy_digest,
        )

    def __post_init__(self) -> None:
        binding = self.occurrence_binding
        if not isinstance(binding, BackgroundOccurrenceBindingV1):
            raise TypeError("background execution authority requires an occurrence binding")
        if not isinstance(self.claim_fencing_token, str) or not self.claim_fencing_token:
            raise ValueError("background claim fencing token must not be empty")
        if not isinstance(self.raw_capability, str) or len(self.raw_capability) < 32:
            raise ValueError("background raw capability must be high entropy")
        if not _is_lower_hex(self.isolated_workspace_identity_digest, length=64):
            raise ValueError("background isolated workspace identity must be hex64")
        for name in (
            "background_environment_policy_digest",
            "browser_origin_policy_digest",
        ):
            value = getattr(self, name)
            if value is not None and not _is_lower_hex(value, length=64):
                raise ValueError(f"background execution {name} must be null or hex64")
        if canonical_json_digest(self.raw_capability) != binding.claim_capability_digest:
            raise ValueError("background raw capability digest mismatch")
        authority_values = {
            "automation_id": binding.automation_id,
            "automation_revision": binding.automation_revision,
            "occurrence_id": binding.occurrence_id,
            "occurrence_index": binding.occurrence_index,
            "scheduled_for_utc": binding.scheduled_for_utc,
            "definition_digest": binding.definition_digest,
            "grant_digest": binding.grant_digest,
            "claim_fencing_token": self.claim_fencing_token,
            "checkpoint_identity": binding.checkpoint_identity_digest,
            "deadline_utc": binding.deadline_utc,
            "capability_digest": binding.claim_capability_digest,
        }
        if canonical_json_digest(authority_values) != binding.claim_authority_digest:
            raise ValueError("background claim authority digest mismatch")


@dataclass(frozen=True, slots=True)
class BackgroundClaimCheckV1:
    automation_id: str
    automation_revision: int
    occurrence_id: str
    definition_digest: str
    grant_digest: str
    claim_authority_digest: str
    claim_fencing_token: str
    checkpoint_identity_digest: str
    raw_capability: str = field(repr=False)
    observed_at_utc: str = ""
    check_digest: str = ""

    @classmethod
    def create(
        cls,
        *,
        execution_authority: BackgroundExecutionAuthorityV1,
        observed_at_utc: str,
    ) -> BackgroundClaimCheckV1:
        binding = execution_authority.occurrence_binding
        return cls(
            automation_id=binding.automation_id,
            automation_revision=binding.automation_revision,
            occurrence_id=binding.occurrence_id,
            definition_digest=binding.definition_digest,
            grant_digest=binding.grant_digest,
            claim_authority_digest=binding.claim_authority_digest,
            claim_fencing_token=execution_authority.claim_fencing_token,
            checkpoint_identity_digest=binding.checkpoint_identity_digest,
            raw_capability=execution_authority.raw_capability,
            observed_at_utc=observed_at_utc,
        )

    def __post_init__(self) -> None:
        if not self.automation_id or not self.occurrence_id or not self.claim_fencing_token:
            raise ValueError("background claim check identity must not be empty")
        if (
            not isinstance(self.automation_revision, int)
            or isinstance(self.automation_revision, bool)
            or self.automation_revision < 1
        ):
            raise ValueError("background claim revision must be positive")
        for name in (
            "definition_digest",
            "grant_digest",
            "claim_authority_digest",
            "checkpoint_identity_digest",
        ):
            if not _is_lower_hex(getattr(self, name), length=64):
                raise ValueError(f"background claim {name} must be hex64")
        if not isinstance(self.raw_capability, str) or len(self.raw_capability) < 32:
            raise ValueError("background claim raw capability must be high entropy")
        _require_canonical_utc(self.observed_at_utc, "background claim observed_at_utc")
        values = {
            "automation_id": self.automation_id,
            "automation_revision": self.automation_revision,
            "occurrence_id": self.occurrence_id,
            "definition_digest": self.definition_digest,
            "grant_digest": self.grant_digest,
            "claim_authority_digest": self.claim_authority_digest,
            "claim_fencing_token": self.claim_fencing_token,
            "checkpoint_identity_digest": self.checkpoint_identity_digest,
            "raw_capability_digest": canonical_json_digest(self.raw_capability),
            "observed_at_utc": self.observed_at_utc,
        }
        digest = canonical_json_digest(values)
        if self.check_digest and self.check_digest != digest:
            raise ValueError("background claim check digest mismatch")
        object.__setattr__(self, "check_digest", digest)


_BACKGROUND_CLAIM_REASONS = frozenset(
    {"allowed", "not_found", "claim_mismatch", "not_running", "cancel_pending", "expired"}
)


@dataclass(frozen=True, slots=True)
class BackgroundClaimVerdictV1:
    allowed: bool
    reason: str
    check_digest: str
    claim_authority_digest: str | None
    definition_digest: str | None
    grant_digest: str | None
    sandbox_confined: bool
    browser_public_observe: bool
    background_environment_policy_digest: str | None
    browser_origin_policy_digest: str | None
    verdict_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool) or self.reason not in _BACKGROUND_CLAIM_REASONS:
            raise ValueError("background claim verdict is not closed")
        if self.allowed != (self.reason == "allowed"):
            raise ValueError("background claim verdict polarity mismatch")
        if not _is_lower_hex(self.check_digest, length=64):
            raise ValueError("background claim verdict check digest must be hex64")
        for name in ("sandbox_confined", "browser_public_observe"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"background claim verdict {name} must be bool")
        digest_fields = (
            self.claim_authority_digest,
            self.definition_digest,
            self.grant_digest,
            self.background_environment_policy_digest,
            self.browser_origin_policy_digest,
        )
        if any(
            value is not None and not _is_lower_hex(value, length=64)
            for value in digest_fields
        ):
            raise ValueError("background claim verdict digest field must be null or hex64")
        if self.allowed and any(
            value is None
            for value in (
                self.claim_authority_digest,
                self.definition_digest,
                self.grant_digest,
            )
        ):
            raise ValueError("allowed background claim verdict requires exact identity")
        values = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "verdict_digest"
        }
        digest = canonical_json_digest(values)
        if self.verdict_digest and self.verdict_digest != digest:
            raise ValueError("background claim verdict digest mismatch")
        object.__setattr__(self, "verdict_digest", digest)


_BACKGROUND_ACTION_CLASSES = frozenset(
    {"sandbox_confined", "browser_public_observe"}
)


@dataclass(frozen=True, slots=True)
class BackgroundActionAuthorityV1:
    action_class: str
    action_fingerprint: str
    occurrence_binding_digest: str
    claim_verdict_digest: str
    budget_ordinal: int
    policy_digest: str
    authority_digest: str = ""

    def __post_init__(self) -> None:
        if self.action_class not in _BACKGROUND_ACTION_CLASSES:
            raise ValueError("background action class is not admitted")
        for name in (
            "action_fingerprint",
            "occurrence_binding_digest",
            "claim_verdict_digest",
            "policy_digest",
        ):
            if not _is_lower_hex(getattr(self, name), length=64):
                raise ValueError(f"background action {name} must be hex64")
        if (
            not isinstance(self.budget_ordinal, int)
            or isinstance(self.budget_ordinal, bool)
            or self.budget_ordinal < 1
        ):
            raise ValueError("background action budget ordinal must be positive")
        values = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "authority_digest"
        }
        digest = canonical_json_digest(values)
        if self.authority_digest and self.authority_digest != digest:
            raise ValueError("background action authority digest mismatch")
        object.__setattr__(self, "authority_digest", digest)


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    action_seq: int
    action_digest: str
    result: RecordedRunResult | None = None

    def __post_init__(self) -> None:
        if self.action_seq < 1 or not self.action_digest:
            raise ValueError("replay record identity must be valid")


@dataclass(frozen=True, slots=True)
class ConversationWorkspaceBindingV1:
    workspace_scope_digest: str
    workspace_identity_digest: str
    bound_at: str
    binding_digest: str

    @classmethod
    def create(
        cls,
        *,
        workspace_scope_digest: str,
        workspace_identity_digest: str,
        bound_at: str,
    ) -> ConversationWorkspaceBindingV1:
        values = {
            "workspace_scope_digest": workspace_scope_digest,
            "workspace_identity_digest": workspace_identity_digest,
            "bound_at": bound_at,
        }
        return cls(**values, binding_digest=canonical_json_digest(values))

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.workspace_scope_digest,
                self.workspace_identity_digest,
                self.bound_at,
                self.binding_digest,
            )
        ):
            raise ValueError("workspace binding fields must be non-empty strings")
        values = {
            "workspace_scope_digest": self.workspace_scope_digest,
            "workspace_identity_digest": self.workspace_identity_digest,
            "bound_at": self.bound_at,
        }
        if canonical_json_digest(values) != self.binding_digest:
            raise ValueError("workspace binding digest mismatch")


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
    provider_disclosure_request: (
        ProviderDisclosureRequest | ProviderDisclosureRequestV2 | None
    ) = None
    provider_disclosure_receipt: (
        ProviderDisclosureReceipt | ProviderDisclosureReceiptV2 | None
    ) = None
    control_receipts: tuple[ControlReceipt, ...] = ()
    workspace_binding: ConversationWorkspaceBindingV1 | None = None
    background_occurrence_binding: BackgroundOccurrenceBindingV1 | None = None
    # 015 governed local action：conversation state 拥有 active process authority lease。
    # 放在字段末尾以保持位置前缀。Goal revision / terminal transition 使其失效。
    process_leases: tuple[ProcessAuthorityLeaseV1, ...] = ()
    # 017：sandbox durable leases（revision/terminal transition 失效，state 层执行）。
    sandbox_leases: tuple[SandboxAuthorityLeaseV1, ...] = ()
    # 018：browser durable leases 与 pending takeover（goal terminal 失效；
    # takeover 只携带 opaque identity，永不携带 credential/storage-state）。
    browser_leases: tuple[BrowserAuthorityLeaseV1, ...] = ()
    browser_takeover_pending: BrowserTakeoverRequestV1 | None = None
    # 2026-10-21：单槽会话级常规外发许可与 Runtime-owned 来源证明。
    # 旧 checkpoint 缺省为空；存在任何记录（含 revoked/invalidated）都写 schema 11。
    provider_consent_grant: ProviderConsentGrantV1 | None = None
    provider_source_proofs: tuple[ProviderFileSourceProofV1, ...] = ()
    summary_source_boundaries: tuple[ProviderSummarySourceBoundaryV1, ...] = ()

    def __post_init__(self) -> None:
        if not self.conversation_id:
            raise ValueError("conversation_id must not be empty")
        if self.workspace_binding is not None and not isinstance(
            self.workspace_binding,
            ConversationWorkspaceBindingV1,
        ):
            raise TypeError("workspace_binding must use the closed v1 contract")
        if self.background_occurrence_binding is not None and not isinstance(
            self.background_occurrence_binding,
            BackgroundOccurrenceBindingV1,
        ):
            raise TypeError("background_occurrence_binding must use the closed v1 contract")
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
                or self.process_leases
                or self.sandbox_leases
            ):
                raise ValueError(
                    "goal authority, evidence, completion claim and leases require a goal"
                )
        else:
            self._validate_process_leases()
            self._validate_sandbox_leases()
            if (
                self.workspace_binding is not None
                and self.goal.workspace_identity_digest
                != self.workspace_binding.workspace_identity_digest
            ):
                raise ValueError("goal and conversation workspace binding must match")
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
        if self.provider_consent_grant is not None and (
            not isinstance(self.provider_consent_grant, ProviderConsentGrantV1)
            or self.provider_consent_grant.conversation_id != self.conversation_id
        ):
            raise ValueError("provider consent grant must bind this conversation")
        object.__setattr__(self, "provider_source_proofs", tuple(self.provider_source_proofs))
        proof_ids = tuple(proof.proof_id for proof in self.provider_source_proofs)
        if len(set(proof_ids)) != len(proof_ids):
            raise ValueError("provider source proof ids must be unique")
        if any(
            proof.conversation_id != self.conversation_id
            for proof in self.provider_source_proofs
        ):
            raise ValueError("provider source proof must bind this conversation")
        object.__setattr__(
            self,
            "summary_source_boundaries",
            tuple(self.summary_source_boundaries),
        )
        summary_fact_ids = tuple(
            boundary.summary_fact_id for boundary in self.summary_source_boundaries
        )
        if len(set(summary_fact_ids)) != len(summary_fact_ids):
            raise ValueError("summary source boundary ids must be unique")
        facts_by_id = {fact.fact_id: fact for fact in self.facts}
        if any(
            boundary.summary_fact_id not in facts_by_id
            or facts_by_id[boundary.summary_fact_id].kind is not FactKind.CONTEXT_SUMMARY
            for boundary in self.summary_source_boundaries
        ):
            raise ValueError("summary source boundary must bind a summary fact")
        correlation_ids = tuple(receipt.correlation_id for receipt in self.control_receipts)
        if len(set(correlation_ids)) != len(correlation_ids):
            raise ValueError("control receipt correlation_id must be unique")
        object.__setattr__(self, "control_receipts", tuple(self.control_receipts))

    def _validate_process_leases(self) -> None:
        """015：active process authority lease 由 conversation state 拥有并受不变量约束。

        容量有界、lease_id 唯一；每条 lease 必须绑定当前 goal_id/goal_revision/workspace；
        goal 进入 terminal 状态时不得残留 lease。这让 correction / verified completion /
        cancel 自然失效旧权限，不需要第二份 ledger。
        """

        leases = self.process_leases
        if len(leases) > MAX_PROCESS_LEASES:
            raise ValueError("process lease count exceeds bounded capacity")
        lease_ids = tuple(lease.lease_id for lease in leases)
        if len(set(lease_ids)) != len(lease_ids):
            raise ValueError("process lease_id must be unique")
        goal = self.goal
        assert goal is not None  # 调用方已保证 goal 存在
        if goal.status in (GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED) and leases:
            raise ValueError("terminal goal must not retain process leases")
        for lease in leases:
            if (
                lease.goal_id != goal.goal_id
                or lease.goal_revision != goal.revision
                or lease.workspace_identity_digest != goal.workspace_identity_digest
            ):
                raise ValueError("process lease must bind the current goal revision")

    def _validate_sandbox_leases(self) -> None:
        """017：one-shot sandbox lease 只绑定当前 non-terminal Goal revision。"""

        leases = self.sandbox_leases
        if len(leases) > MAX_SANDBOX_LEASES:
            raise ValueError("sandbox lease count exceeds bounded capacity")
        lease_ids = tuple(lease.lease_id for lease in leases)
        if len(set(lease_ids)) != len(lease_ids):
            raise ValueError("sandbox lease_id must be unique")
        goal = self.goal
        assert goal is not None
        if goal.status in (GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED) and leases:
            raise ValueError("terminal goal must not retain sandbox leases")
        for lease in leases:
            if (
                lease.goal_id != goal.goal_id
                or lease.goal_revision != goal.revision
                or lease.workspace_identity_digest != goal.workspace_identity_digest
            ):
                raise ValueError("sandbox lease must bind the current goal revision")

    @classmethod
    def new(
        cls,
        conversation_id: str,
        *,
        workspace_binding: ConversationWorkspaceBindingV1 | None = None,
        background_occurrence_binding: BackgroundOccurrenceBindingV1 | None = None,
    ) -> ConversationState:
        return cls(
            conversation_id=conversation_id,
            workspace_binding=workspace_binding,
            background_occurrence_binding=background_occurrence_binding,
        )


def source_result_since_latest_user(state: ConversationState) -> bool:
    """来源结果只能回答当前 action，不能反向把同一 action 升格成新 Goal authority。"""

    latest_user = max(
        (
            index
            for index, fact in enumerate(state.facts)
            if fact.kind is FactKind.USER_MESSAGE
        ),
        default=-1,
    )
    return any(
        fact.kind is FactKind.TOOL_RESULT
        and fact.content.get("executed") is True
        and fact.content.get("is_error") is False
        and isinstance(fact.content.get("metadata"), dict)
        and bool(fact.content["metadata"].get("source_receipts"))
        for fact in state.facts[latest_user + 1 :]
    )


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
    # R9/F6（review finding）：process lease 的 expires_at 锚定**批准**时刻而非
    # prepare/candidate 时刻——审批等待不缩短租约。process approval 的 approved_at
    # 必须存在且是带时区 RFC3339；缺失或 malformed 即 fail closed。非 process
    # approval 保持可省略。
    approved_at: str | None = None
    # F4（review finding / design §6）：artifact digest 的 authority 是**用户**——
    # 批准 process command 的同一 typed action 携带用户确认的 artifact 期望
    # （path + 64-hex sha256），Runtime 在审批时刻铸 FILESYSTEM_DIGEST criterion。
    # 模型无法自供（local_process schema 已回 closed 4 字段）。malformed fail closed。
    confirmed_artifact_path: str | None = None
    confirmed_artifact_sha256: str | None = None
    # 对程序尚未生成的产物，用户只能先批准 command effect；不能被迫猜未来摘要。
    # 该位只延后 FILESYSTEM_DIGEST 准入，绝不等于确认产物，后续仍需 confirm_file。
    defer_artifact_confirmation: bool = False
    # 显式 opt-in：把当前文件批准提升为当前 Goal/revision、同一 workspace、
    # 同一工具与同一精确目标的授权。默认 False 保持逐笔批准。
    authorize_goal_target: bool = False
    # 只有当前调用位于 Goal 明确列出的目录 target 下时才可铸造；不从文件父目录猜测。
    authorize_goal_directory: bool = False
    # 2026-10-18 发现 3：显式 opt-in——把本次批准同时授权「把一条已执行且从未
    # 成功的 runtime-owned 验证义务重绑定到这条 canonical 等价命令」。默认 False
    # 保持逐笔批准语义（批准=执行这一笔，不改写 admitted 义务）；对抗审查指出
    # 隐式重绑定把 execute-scoped 批准静默升级为 obligation mutation。
    authorize_obligation_rebind: bool = False

    def __post_init__(self) -> None:
        if self.defer_artifact_confirmation and (
            not self.approved
            or self.confirmed_artifact_path is not None
            or self.confirmed_artifact_sha256 is not None
        ):
            raise ValueError(
                "deferred artifact confirmation requires approval without a supplied digest"
            )
        if self.authorize_goal_target and not self.approved:
            raise ValueError("goal target authorization requires approval")
        if self.authorize_goal_directory and not self.approved:
            raise ValueError("goal directory authorization requires approval")
        if self.authorize_goal_target and self.authorize_goal_directory:
            raise ValueError("choose either exact target or directory authorization")
        if self.authorize_obligation_rebind and not self.approved:
            raise ValueError("obligation rebind authorization requires approval")


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeProcessAuthority(RuntimeAction):
    """015：typed revoke action。``lease_id`` 选择单条 lease；``None`` 撤销全部。

    采用 expected_revision 的 replay/CAS 语义。revoke 不假装取消已在 EXECUTING 的
    in-flight process；它只移除后续 execution authority。当前已在 EXECUTING 时 UI 仍按
    runner/recovery 处理 outcome（design §8）。
    """

    lease_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeGoalTargetAuthority(RuntimeAction):
    """撤销当前 Goal 的全部精确文件目标授权；不影响已完成 effect。"""

    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class CompleteBrowserTakeover(RuntimeAction):
    """018：typed complete takeover control（user-only，spec §7）。

    校验 exact request/session/profile；成功后期望 profile revision 递增
    并要求 fresh browser_observe；不铸造任何 commit approval。
    """

    request_id: str
    session_ref: str
    expected_profile_revision: int

    def __post_init__(self) -> None:
        if not self.request_id or not self.session_ref:
            raise ValueError("takeover control identity must not be empty")
        if self.expected_profile_revision <= 0:
            raise ValueError("expected_profile_revision must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelBrowserTakeover(RuntimeAction):
    """018：typed cancel takeover control（user-only）。"""

    request_id: str

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("takeover control identity must not be empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveUnknownToolOutcome(RuntimeAction):
    request_id: str
    binding_digest: str
    resolution: RecoveryResolution


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverUnknownObservation(RuntimeAction):
    tool_call_id: str
    intent_digest: str

    def __post_init__(self) -> None:
        if not self.tool_call_id or not self.intent_digest:
            raise ValueError("observation recovery identity must not be empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class AbandonUnknownModelOutcome(RuntimeAction):
    occurrence_id: str
    background_binding_digest: str
    provider_call_intent_digest: str

    def __post_init__(self) -> None:
        if not self.occurrence_id:
            raise ValueError("model outcome abandonment must bind an occurrence")
        for name in ("background_binding_digest", "provider_call_intent_digest"):
            if not _is_lower_hex(getattr(self, name), length=64):
                raise ValueError(f"{name} must be 64 lowercase hex")


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


@dataclass(frozen=True, slots=True, kw_only=True)
class GrantProviderConsent(RuntimeAction):
    """用户显式选择 s：只依据当前显示的同一条 v2 request 铸造有限许可。"""

    request_digest: str
    scope_digest: str

    def __post_init__(self) -> None:
        if not self.request_digest or not self.scope_digest:
            raise ValueError("provider consent grant action must bind request and scope")


@dataclass(frozen=True, slots=True, kw_only=True)
class GrantProviderWorkspaceReadConsent(RuntimeAction):
    """用户显式选择 r：常规范围之上并入 proof-backed 工作区读摘录。

    与 s 的区别只在覆盖类别（workspace_excerpt）；硬上界（次数/TTL）、
    撤销与失效语义与 s 完全一致。不扩 tool_results 等通用类，不跨会话。
    """

    request_digest: str
    scope_digest: str

    def __post_init__(self) -> None:
        if not self.request_digest or not self.scope_digest:
            raise ValueError(
                "provider workspace-read consent action must bind request and scope"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeProviderConsent(RuntimeAction):
    """撤销当前会话范围许可；不触发 provider/tool，也不伪造网络中断。"""

    pass


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


_OPERATOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_RFC3339_Z = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteOperatorTool(RuntimeAction):
    action_id: str
    tool_name: str
    arguments: dict[str, JSONValue]
    submitted_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or _OPERATOR_ID.fullmatch(self.action_id) is None:
            raise ValueError("operator action_id has an invalid closed shape")
        if not isinstance(self.tool_name, str) or _TOOL_NAME.fullmatch(self.tool_name) is None:
            raise ValueError("operator tool_name has an invalid closed shape")
        if (
            not isinstance(self.submitted_at, str)
            or _RFC3339_Z.fullmatch(self.submitted_at) is None
        ):
            raise ValueError("operator submitted_at must be zoned RFC3339")
        _assert_json_compatible(self.arguments, path="operator_tool.arguments")
        object.__setattr__(self, "arguments", _freeze_json_dict(self.arguments))


Action: TypeAlias = (
    SubmitMessage
    | ResolveApproval
    | ResolveUnknownToolOutcome
    | RecoverUnknownObservation
    | AbandonUnknownModelOutcome
    | Resume
    | CancelRun
    | AcknowledgeProviderDisclosure
    | GrantProviderConsent
    | RevokeProviderConsent
    | SelectGoal
    | PauseGoal
    | ResumeGoal
    | CancelGoal
    | ConfirmCriterion
    | RevokeProcessAuthority
    | RevokeGoalTargetAuthority
    | CompleteBrowserTakeover
    | CancelBrowserTakeover
    | ExecuteOperatorTool
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
class ArchivedConversation:
    """transcript archive 中一个 immutable archived segment 的只读坐标。

    020 长会话压缩：坐标只由闭合 identity（conversation、workspace scope、
    source checkpoint digest）派生，load 端会重新推导并校验 path。
    """

    conversation_id: str
    workspace_scope_digest: str
    source_checkpoint_digest: str
    path: Path


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
    model_calls_used: int = 0

    def __post_init__(self) -> None:
        for name in ("model_calls_used",):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be non-negative")


class RuntimeEventKind(StrEnum):
    MODEL_PROGRESS = "model_progress"
    MODEL_TEXT_DELTA = "model_text_delta"
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
class ProviderContinuationV1:
    """只供同一 provider 回放的 opaque 连续性；不属于可展示的模型内容。"""

    provider_identity_digest: str
    opaque_payload: str = field(repr=False)
    opaque_payload_digest: str

    @classmethod
    def create(
        cls,
        *,
        provider_identity_digest: str,
        opaque_payload: str,
    ) -> ProviderContinuationV1:
        return cls(
            provider_identity_digest=provider_identity_digest,
            opaque_payload=opaque_payload,
            opaque_payload_digest=hashlib.sha256(
                opaque_payload.encode("utf-8")
            ).hexdigest(),
        )

    def __post_init__(self) -> None:
        if not _is_lower_hex(self.provider_identity_digest, length=64):
            raise ValueError("provider continuation identity digest is malformed")
        if not isinstance(self.opaque_payload, str) or not self.opaque_payload:
            raise ValueError("provider continuation payload must be non-empty text")
        if len(self.opaque_payload.encode("utf-8")) > 4_000_000:
            raise ValueError("provider continuation payload exceeds its bound")
        if not _is_lower_hex(self.opaque_payload_digest, length=64):
            raise ValueError("provider continuation payload digest is malformed")
        expected = hashlib.sha256(self.opaque_payload.encode("utf-8")).hexdigest()
        if self.opaque_payload_digest != expected:
            raise ValueError("provider continuation payload digest mismatch")


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: str
    content: tuple[dict[str, JSONValue], ...]
    provider_continuation: ProviderContinuationV1 | None = None

    def __post_init__(self) -> None:
        if self.provider_continuation is not None and not isinstance(
            self.provider_continuation, ProviderContinuationV1
        ):
            raise TypeError("model message provider continuation is invalid")
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
    egress: EgressClass = EgressClass.NONE
    # F5（review finding 2026-08-16）：execution authority 必须显式投影（KTD13
    # explicit projection/no fallback）——无 constructor default，遗漏即 TypeError。
    execution_authority: ExecutionAuthorityClass = field(kw_only=True)

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
    egress: EgressClass = EgressClass.NONE
    # F5（review finding 2026-08-16）：静态 ToolSpec 必须显式声明 execution
    # authority——新增工具遗漏声明必须在构造时失败，不得静默 fallback IN_PROCESS。
    execution_authority: ExecutionAuthorityClass = field(kw_only=True)
    source_kinds: tuple[SourceKind, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.version or not self.description:
            raise ValueError("tool name, version, and description must not be empty")
        if self.output_limit_chars < 1:
            raise ValueError("output_limit_chars must be positive")
        _assert_json_compatible(self.input_schema, path="tool_spec.input_schema")
        _assert_json_compatible(self.safety_policy, path="tool_spec.safety_policy")
        object.__setattr__(self, "input_schema", _freeze_json_dict(self.input_schema))
        object.__setattr__(self, "safety_policy", _freeze_json_dict(self.safety_policy))
        object.__setattr__(self, "source_kinds", tuple(self.source_kinds))
        if len(set(self.source_kinds)) != len(self.source_kinds):
            raise ValueError("source_kinds must be unique")
        if self.egress is EgressClass.PUBLIC_NETWORK and (
            self.side_effect is not SideEffectClass.READ_ONLY
            or self.approval_policy is not ApprovalPolicy.ALWAYS
        ):
            raise ValueError("PUBLIC_NETWORK tools must be READ_ONLY and always approved")

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
            "egress": self.egress.value,
            "execution_authority": self.execution_authority.value,
            "source_kinds": [kind.value for kind in self.source_kinds],
        }
        return canonical_json_digest(payload)

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            side_effect=self.side_effect,
            egress=self.egress,
            execution_authority=self.execution_authority,
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


class CompactionTrigger(StrEnum):
    """020 长会话压缩的闭合触发原因；planner 本身不属于本模块。"""

    NONE = "none"
    MANUAL = "manual"
    TOKEN_PRESSURE = "token_pressure"
    EXCLUDED_HISTORY = "excluded_history"
    CHECKPOINT_PRESSURE = "checkpoint_pressure"
    UNSAFE_BOUNDARY = "unsafe_boundary"
    NO_CANDIDATE = "no_candidate"


_ACTIONABLE_COMPACTION_TRIGGERS = (
    CompactionTrigger.MANUAL,
    CompactionTrigger.TOKEN_PRESSURE,
    CompactionTrigger.EXCLUDED_HISTORY,
    CompactionTrigger.CHECKPOINT_PRESSURE,
)


@dataclass(frozen=True, slots=True)
class CompactionPlanV1:
    """压缩决策的纯数据合同：只描述已决定移除什么，不参与选择或执行。"""

    trigger: CompactionTrigger
    removable_fact_ids: tuple[str, ...]
    usage: BudgetReport
    active_checkpoint_bytes: int
    soft_threshold_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, CompactionTrigger):
            raise TypeError("compaction trigger must be CompactionTrigger")
        if not isinstance(self.usage, BudgetReport):
            raise TypeError("compaction usage must be BudgetReport")
        for name, value, minimum in (
            ("active_checkpoint_bytes", self.active_checkpoint_bytes, 0),
            ("soft_threshold_bytes", self.soft_threshold_bytes, 1),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"compaction {name} must be an integer")
            if value < minimum:
                raise ValueError(f"compaction {name} is out of range")
        object.__setattr__(self, "removable_fact_ids", tuple(self.removable_fact_ids))
        if any(not isinstance(item, str) or not item for item in self.removable_fact_ids):
            raise ValueError("compaction removable fact ids must be non-empty strings")
        if len(set(self.removable_fact_ids)) != len(self.removable_fact_ids):
            raise ValueError("compaction removable fact ids must be unique")
        has_ids = bool(self.removable_fact_ids)
        if self.trigger in _ACTIONABLE_COMPACTION_TRIGGERS and not has_ids:
            raise ValueError("actionable compaction requires removable fact ids")
        if self.trigger not in _ACTIONABLE_COMPACTION_TRIGGERS and has_ids:
            raise ValueError("only actionable compaction may carry removable fact ids")

    @property
    def actionable(self) -> bool:
        return bool(self.removable_fact_ids) and self.trigger in _ACTIONABLE_COMPACTION_TRIGGERS


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


def context_source_snapshot_digest(
    source_name: str,
    revision: int,
    candidates: tuple[ContextCandidate, ...],
) -> str:
    """绑定 ContextSource 快照的全部可投影身份，供 source 与 Kernel 交叉校验。"""

    return canonical_json_digest(
        {
            "source_name": source_name,
            "revision": revision,
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "source_name": candidate.source_name,
                    "workspace_scope_digest": candidate.workspace_scope_digest,
                    "content_digest": candidate.content_digest,
                    "provenance": candidate.provenance,
                    "rank_key": candidate.rank_key,
                }
                for candidate in candidates
            ],
        }
    )


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
    # Runtime-owned 只读许可投影：ContextManager 从实际选中的 facts/tools
    # 生成；Provider adapter 不消费它，也不改变 wire payload。
    consent_scope: ProviderConsentScopeV1 | None = None

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
    provider_continuation: ProviderContinuationV1 | None = None

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
        if self.provider_continuation is not None and not isinstance(
            self.provider_continuation, ProviderContinuationV1
        ):
            raise TypeError("model response provider continuation is invalid")
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
        if self.provider_continuation is not None:
            payload.append(
                {
                    "type": "provider_continuation",
                    "provider_identity_digest": (
                        self.provider_continuation.provider_identity_digest
                    ),
                    "opaque_payload": self.provider_continuation.opaque_payload,
                    "opaque_payload_digest": (
                        self.provider_continuation.opaque_payload_digest
                    ),
                }
            )
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return max(self.output_tokens or 0, 1, len(encoded))


def context_pack_digest(context: ContextPack) -> str:
    """绑定一次不可变 provider request 的完整 Runtime 投影。"""

    return canonical_json_digest(asdict(context))


def model_response_payload(response: ModelResponse) -> dict[str, JSONValue]:
    blocks: list[JSONValue] = []
    for block in response.blocks:
        if isinstance(block, ModelTextBlock):
            blocks.append({"type": "text", "text": block.text})
        else:
            blocks.append(
                {
                    "type": "tool_call",
                    "tool_call_id": block.tool_call_id,
                    "name": block.name,
                    "arguments": block.arguments,
                }
            )
    control = (
        None
        if response.control is None
        else {
            "type": type(response.control).__name__,
            "payload": _canonical_json_value(asdict(response.control)),
        }
    )
    return {
        "blocks": blocks,
        "control": control,
        "stop_reason": response.stop_reason,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "provider_continuation": (
            None
            if response.provider_continuation is None
            else {
                "provider_identity_digest": (
                    response.provider_continuation.provider_identity_digest
                ),
                "opaque_payload": response.provider_continuation.opaque_payload,
                "opaque_payload_digest": (
                    response.provider_continuation.opaque_payload_digest
                ),
            }
        ),
    }


def _exact_payload(value: object, keys: set[str], label: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} has unknown or missing fields")
    _assert_json_compatible(value, path=label)
    return value


def _payload_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _payload_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def _requirement_coverage_from_payload(value: object) -> tuple[RequirementCoverage, ...]:
    if not isinstance(value, list):
        raise ValueError("requirement_coverage must be an array")
    items: list[RequirementCoverage] = []
    for raw in value:
        entry = _exact_payload(
            raw,
            {
                "requirement_id",
                "requirement",
                "source_fact_ids",
                "status",
                "criterion_ids",
            },
            "requirement_coverage entry",
        )
        if not isinstance(entry["source_fact_ids"], list) or not isinstance(
            entry["criterion_ids"], list
        ):
            raise ValueError("requirement_coverage id lists must be arrays")
        items.append(
            RequirementCoverage(
                requirement_id=_payload_string(entry["requirement_id"], "requirement_id"),
                requirement=_payload_string(entry["requirement"], "requirement"),
                # ID 列表逐元素必须是字符串：非字符串元素不得进入 tuple。
                source_fact_ids=tuple(
                    _payload_string(item, "source_fact_id")
                    for item in entry["source_fact_ids"]
                ),
                status=_payload_string(entry["status"], "status"),
                criterion_ids=tuple(
                    _payload_string(item, "criterion_id")
                    for item in entry["criterion_ids"]
                ),
            )
        )
    return tuple(items)


def model_response_from_payload(value: object) -> ModelResponse:
    raw = _exact_payload(
        value,
        {
            "blocks",
            "control",
            "stop_reason",
            "input_tokens",
            "output_tokens",
            "provider_continuation",
        },
        "model_response",
    )
    if not isinstance(raw["blocks"], list):
        raise ValueError("model_response.blocks must be an array")
    blocks: list[ModelTextBlock | ModelToolCall] = []
    for item in raw["blocks"]:
        if not isinstance(item, dict):
            raise ValueError("model_response block must be an object")
        block_type = item.get("type")
        if block_type == "text":
            item = _exact_payload(item, {"type", "text"}, "model_text_block")
            blocks.append(ModelTextBlock(_payload_string(item["text"], "text")))
        elif block_type == "tool_call":
            item = _exact_payload(
                item,
                {"type", "tool_call_id", "name", "arguments"},
                "model_tool_call",
            )
            arguments = item["arguments"]
            if not isinstance(arguments, dict):
                raise ValueError("model_tool_call.arguments must be an object")
            blocks.append(
                ModelToolCall(
                    _payload_string(item["tool_call_id"], "tool_call_id"),
                    _payload_string(item["name"], "name"),
                    arguments,
                )
            )
        else:
            raise ValueError("model_response block type is unknown")

    control = None
    if raw["control"] is not None:
        envelope = _exact_payload(
            raw["control"], {"type", "payload"}, "model_control"
        )
        control_type = _payload_string(envelope["type"], "model_control.type")
        payload = envelope["payload"]
        if not isinstance(payload, dict):
            raise ValueError("model_control.payload must be an object")
        if control_type == "DirectResponse":
            payload = _exact_payload(payload, {"correlation_id", "text"}, control_type)
            control = DirectResponse(**payload)
        elif control_type == "BeginAnswer":
            payload = _exact_payload(payload, {"correlation_id"}, control_type)
            control = BeginAnswer(**payload)
        elif control_type == "ClarificationRequest":
            payload = _exact_payload(
                payload,
                {
                    "correlation_id",
                    "question",
                    "boundary_code",
                    "missing_fields",
                    "safe_assumptions",
                },
                control_type,
            )
            control = ClarificationRequest(
                correlation_id=_payload_string(payload["correlation_id"], "correlation_id"),
                question=_payload_string(payload["question"], "question"),
                boundary_code=_payload_string(payload["boundary_code"], "boundary_code"),
                missing_fields=tuple(payload["missing_fields"]),
                safe_assumptions=tuple(payload["safe_assumptions"]),
            )
        elif control_type == "GoalDraftProposal":
            payload = _exact_payload(
                payload,
                {
                    "correlation_id",
                    "user_outcome",
                    "beneficiary",
                    "targets",
                    "scope",
                    "non_goals",
                    "assumptions",
                    "proposed_criteria",
                    "next_step",
                    "requires_public_web",
                    "requires_local_process",
                },
                control_type,
            )
            criteria = payload["proposed_criteria"]
            if not isinstance(criteria, list):
                raise ValueError("proposed_criteria must be an array")
            decoded_criteria: list[ProposedCriterion] = []
            for index, raw_criterion in enumerate(criteria):
                criterion = _exact_payload(
                    raw_criterion,
                    {
                        "criterion_id",
                        "description",
                        "oracle_kind",
                        "artifact_path",
                    },
                    f"proposed_criteria[{index}]",
                )
                raw_oracle = criterion["oracle_kind"]
                if raw_oracle is None:
                    oracle_kind = None
                else:
                    try:
                        oracle_kind = EvidenceOracleKind(
                            _payload_string(raw_oracle, "oracle_kind")
                        )
                    except ValueError as error:
                        raise ValueError("oracle_kind is not closed") from error
                artifact_path = criterion["artifact_path"]
                if artifact_path is not None:
                    artifact_path = _payload_string(artifact_path, "artifact_path")
                decoded_criteria.append(
                    ProposedCriterion(
                        criterion_id=_payload_string(
                            criterion["criterion_id"], "criterion_id"
                        ),
                        description=_payload_string(
                            criterion["description"], "description"
                        ),
                        oracle_kind=oracle_kind,
                        artifact_path=artifact_path,
                    )
                )
            control = GoalDraftProposal(
                correlation_id=_payload_string(payload["correlation_id"], "correlation_id"),
                user_outcome=_payload_string(payload["user_outcome"], "user_outcome"),
                beneficiary=_payload_string(payload["beneficiary"], "beneficiary"),
                targets=tuple(payload["targets"]),
                scope=tuple(payload["scope"]),
                non_goals=tuple(payload["non_goals"]),
                assumptions=tuple(payload["assumptions"]),
                proposed_criteria=tuple(decoded_criteria),
                next_step=payload["next_step"],
                requires_public_web=payload["requires_public_web"],
                requires_local_process=payload["requires_local_process"],
            )
        elif control_type == "GoalProgress":
            payload = _exact_payload(
                payload,
                {"correlation_id", "goal_id", "goal_revision", "summary", "next_step"},
                control_type,
            )
            control = GoalProgress(**payload)
        elif control_type == "GoalDeltaProposal":
            payload = _exact_payload(payload, {"correlation_id", "delta"}, control_type)
            delta = payload["delta"]
            if not isinstance(delta, dict):
                raise ValueError("goal delta must be an object")
            delta = _exact_payload(
                delta,
                {"goal_id", "expected_revision", "reason", "updates", "updated_at"},
                "GoalDelta",
            )
            control = GoalDeltaProposal(
                correlation_id=_payload_string(payload["correlation_id"], "correlation_id"),
                delta=GoalDelta(**delta),
            )
        elif control_type == "CompletionClaim":
            # R2：requirement_coverage 对旧 checkpoint 持久化的 response 缺失时按空
            # 迁移（旧 claim 不被默认视为复核已满足，模型在主 loop 补复核）；新的
            # provider wire 仍由 normalize 精确键集强制显式提供。
            if not isinstance(payload, dict):
                raise ValueError("model_control.payload must be an object")
            normalized = dict(payload)
            raw_coverage = normalized.pop("requirement_coverage", [])
            payload = _exact_payload(
                normalized,
                {"correlation_id", "goal_id", "goal_revision", "criterion_evidence_refs"},
                control_type,
            )
            control = CompletionClaim(
                correlation_id=_payload_string(payload["correlation_id"], "correlation_id"),
                goal_id=_payload_string(payload["goal_id"], "goal_id"),
                goal_revision=_payload_int(payload["goal_revision"], "goal_revision"),
                criterion_evidence_refs=tuple(payload["criterion_evidence_refs"]),
                requirement_coverage=_requirement_coverage_from_payload(raw_coverage),
            )
        elif control_type == "BlockedClaim":
            payload = _exact_payload(
                payload,
                {
                    "correlation_id",
                    "goal_id",
                    "goal_revision",
                    "blocker",
                    "safe_attempts",
                    "resume_condition",
                },
                control_type,
            )
            control = BlockedClaim(
                correlation_id=_payload_string(payload["correlation_id"], "correlation_id"),
                goal_id=_payload_string(payload["goal_id"], "goal_id"),
                goal_revision=_payload_int(payload["goal_revision"], "goal_revision"),
                blocker=_payload_string(payload["blocker"], "blocker"),
                safe_attempts=tuple(payload["safe_attempts"]),
                resume_condition=_payload_string(
                    payload["resume_condition"], "resume_condition"
                ),
            )
        else:
            raise ValueError("model control type is unknown")

    def optional_int(item: object, label: str) -> int | None:
        return None if item is None else _payload_int(item, label)

    stop_reason = raw["stop_reason"]
    if stop_reason is not None and not isinstance(stop_reason, str):
        raise ValueError("stop_reason must be a string or null")
    provider_continuation = None
    if raw["provider_continuation"] is not None:
        continuity = _exact_payload(
            raw["provider_continuation"],
            {
                "provider_identity_digest",
                "opaque_payload",
                "opaque_payload_digest",
            },
            "provider_continuation",
        )
        provider_continuation = ProviderContinuationV1(
            provider_identity_digest=_payload_string(
                continuity["provider_identity_digest"],
                "provider_identity_digest",
            ),
            opaque_payload=_payload_string(
                continuity["opaque_payload"], "opaque_payload"
            ),
            opaque_payload_digest=_payload_string(
                continuity["opaque_payload_digest"], "opaque_payload_digest"
            ),
        )
    return ModelResponse(
        blocks=tuple(blocks),
        control=control,
        stop_reason=stop_reason,
        input_tokens=optional_int(raw["input_tokens"], "input_tokens"),
        output_tokens=optional_int(raw["output_tokens"], "output_tokens"),
        provider_continuation=provider_continuation,
    )


@dataclass(frozen=True, slots=True)
class PersistedModelResponseV1:
    request_digest: str
    response: ModelResponse
    response_digest: str

    @classmethod
    def create(
        cls,
        *,
        request_digest: str,
        response: ModelResponse,
    ) -> PersistedModelResponseV1:
        return cls(
            request_digest=request_digest,
            response=response,
            response_digest=canonical_json_digest(model_response_payload(response)),
        )

    def __post_init__(self) -> None:
        if not _is_lower_hex(self.request_digest, length=64):
            raise ValueError("persisted response request_digest must be 64 lowercase hex")
        if not isinstance(self.response, ModelResponse):
            raise TypeError("persisted response must contain one normalized ModelResponse")
        if (
            not _is_lower_hex(self.response_digest, length=64)
            or canonical_json_digest(model_response_payload(self.response))
            != self.response_digest
        ):
            raise ValueError("persisted model response digest mismatch")


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


def source_data_class(source_kind: SourceKind) -> str:
    if source_kind.value.startswith("history_"):
        return "first_agent_history"
    if source_kind.value.startswith("workspace_"):
        return "workspace_excerpt"
    return "public_web_content"


@dataclass(frozen=True, slots=True)
class SourceReceiptDraft:
    """Source callable 的无权草稿；Kernel 会重算 digest 并追加执行身份。"""

    source_kind: SourceKind
    origin_locator: str
    content: str
    observed_at: str
    snapshot_digest: str | None = None
    request_identity: str | None = None
    origin_request_digest: str | None = None
    original_content_digest: str | None = None
    title: str | None = None
    truncated: bool = False
    truncation_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, SourceKind):
            raise TypeError("source draft kind must be closed")
        required_strings = (self.origin_locator, self.content, self.observed_at)
        optional_strings = (
            self.snapshot_digest,
            self.request_identity,
            self.origin_request_digest,
            self.original_content_digest,
            self.title,
            self.truncation_reason,
        )
        if any(not isinstance(value, str) for value in required_strings) or any(
            value is not None and not isinstance(value, str)
            for value in optional_strings
        ):
            raise TypeError("source draft text fields must be strings")
        if not isinstance(self.truncated, bool):
            raise TypeError("source draft truncated must be boolean")
        if not self.origin_locator or not self.observed_at:
            raise ValueError("source draft identity must not be empty")
        observation_ids = (self.snapshot_digest, self.request_identity)
        if sum(item is not None for item in observation_ids) != 1:
            raise ValueError("source draft requires exactly one observation identity")
        if self.truncated != (self.truncation_reason is not None):
            raise ValueError("source draft truncation metadata must be complete")


@dataclass(frozen=True, slots=True)
class SourceReceiptV1:
    source_id: str
    source_kind: SourceKind
    origin_locator: str
    origin_request_digest: str | None
    observed_at: str
    content_digest: str
    original_content_digest: str | None
    truncated: bool
    truncation_reason: str | None
    snapshot_digest: str | None
    request_identity: str | None
    conversation_id: str
    run_id: str
    goal_id: str | None
    goal_revision: int | None
    intent_digest: str
    data_class: str
    receipt_digest: str
    title: str | None = None

    @classmethod
    def create(
        cls,
        draft: SourceReceiptDraft,
        intent: ExecutionIntent,
    ) -> SourceReceiptV1:
        content_digest = hashlib.sha256(draft.content.encode("utf-8")).hexdigest()
        observation_identity = draft.snapshot_digest or draft.request_identity
        source_id = "source:v1:" + canonical_json_digest(
            {
                "source_kind": draft.source_kind,
                "origin_locator": draft.origin_locator,
                "observation_identity": observation_identity,
            }
        )
        values = {
            "source_id": source_id,
            "source_kind": draft.source_kind,
            "origin_locator": draft.origin_locator,
            "origin_request_digest": draft.origin_request_digest,
            "observed_at": draft.observed_at,
            "content_digest": content_digest,
            "original_content_digest": draft.original_content_digest,
            "truncated": draft.truncated,
            "truncation_reason": draft.truncation_reason,
            "snapshot_digest": draft.snapshot_digest,
            "request_identity": draft.request_identity,
            "conversation_id": intent.conversation_id,
            "run_id": intent.run_id,
            "goal_id": intent.goal_id,
            "goal_revision": intent.goal_revision,
            "intent_digest": intent.intent_digest,
            "data_class": source_data_class(draft.source_kind),
            "title": draft.title,
        }
        return cls(**values, receipt_digest=canonical_json_digest(values))

    @classmethod
    def from_json(cls, value: object) -> SourceReceiptV1:
        if not isinstance(value, dict):
            raise ValueError("source receipt must be an object")
        expected_keys = {
            "source_id",
            "source_kind",
            "origin_locator",
            "origin_request_digest",
            "observed_at",
            "content_digest",
            "original_content_digest",
            "truncated",
            "truncation_reason",
            "snapshot_digest",
            "request_identity",
            "conversation_id",
            "run_id",
            "goal_id",
            "goal_revision",
            "intent_digest",
            "data_class",
            "receipt_digest",
            "title",
        }
        if set(value) != expected_keys:
            raise ValueError("source receipt has unknown or missing fields")
        try:
            return cls(
                **{
                    **value,
                    "source_kind": SourceKind(value["source_kind"]),
                }
            )
        except (TypeError, ValueError) as error:
            raise ValueError("source receipt is invalid") from error

    def __post_init__(self) -> None:
        string_fields = (
            self.source_id,
            self.origin_locator,
            self.observed_at,
            self.content_digest,
            self.conversation_id,
            self.run_id,
            self.intent_digest,
            self.data_class,
            self.receipt_digest,
        )
        optional_strings = (
            self.origin_request_digest,
            self.original_content_digest,
            self.truncation_reason,
            self.snapshot_digest,
            self.request_identity,
            self.goal_id,
            self.title,
        )
        if not isinstance(self.source_kind, SourceKind):
            raise TypeError("source receipt kind must be closed")
        if any(not isinstance(value, str) for value in string_fields) or any(
            value is not None and not isinstance(value, str)
            for value in optional_strings
        ):
            raise TypeError("source receipt text fields must be strings")
        if not isinstance(self.truncated, bool):
            raise TypeError("source receipt truncated must be boolean")
        if self.goal_revision is not None and (
            not isinstance(self.goal_revision, int)
            or isinstance(self.goal_revision, bool)
        ):
            raise TypeError("source receipt goal revision must be an integer")
        if not all(
            (
                self.source_id,
                self.origin_locator,
                self.observed_at,
                self.content_digest,
                self.conversation_id,
                self.run_id,
                self.intent_digest,
                self.data_class,
                self.receipt_digest,
            )
        ):
            raise ValueError("source receipt identity must not be empty")
        if (self.goal_id is None) != (self.goal_revision is None):
            raise ValueError("source receipt goal identity must be complete")
        if self.goal_revision is not None and self.goal_revision < 1:
            raise ValueError("source receipt goal revision must be positive")
        if sum(item is not None for item in (self.snapshot_digest, self.request_identity)) != 1:
            raise ValueError("source receipt requires exactly one observation identity")
        if self.truncated != (self.truncation_reason is not None):
            raise ValueError("source receipt truncation metadata must be complete")
        if self.data_class != source_data_class(self.source_kind):
            raise ValueError("source receipt data class does not match its source kind")
        observation_identity = self.snapshot_digest or self.request_identity
        expected_source_id = "source:v1:" + canonical_json_digest(
            {
                "source_kind": self.source_kind,
                "origin_locator": self.origin_locator,
                "observation_identity": observation_identity,
            }
        )
        if self.source_id != expected_source_id:
            raise ValueError("source receipt source identity is invalid")
        values = {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "origin_locator": self.origin_locator,
            "origin_request_digest": self.origin_request_digest,
            "observed_at": self.observed_at,
            "content_digest": self.content_digest,
            "original_content_digest": self.original_content_digest,
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "snapshot_digest": self.snapshot_digest,
            "request_identity": self.request_identity,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "intent_digest": self.intent_digest,
            "data_class": self.data_class,
            "title": self.title,
        }
        if canonical_json_digest(values) != self.receipt_digest:
            raise ValueError("source receipt digest mismatch")


@dataclass(frozen=True, slots=True)
class SourceAuthorityBinding:
    source_fact_id: str
    receipt_digest: str
    conversation_id: str
    request_identity: str
    canonical_url: str
    binding_digest: str

    @classmethod
    def create(
        cls,
        *,
        source_fact_id: str,
        receipt_digest: str,
        conversation_id: str,
        request_identity: str,
        canonical_url: str,
    ) -> SourceAuthorityBinding:
        values = {
            "source_fact_id": source_fact_id,
            "receipt_digest": receipt_digest,
            "conversation_id": conversation_id,
            "request_identity": request_identity,
            "canonical_url": canonical_url,
        }
        return cls(**values, binding_digest=canonical_json_digest(values))

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str)
            for value in (
                self.source_fact_id,
                self.receipt_digest,
                self.conversation_id,
                self.request_identity,
                self.canonical_url,
                self.binding_digest,
            )
        ):
            raise TypeError("source authority binding fields must be strings")
        if not all(
            (
                self.source_fact_id,
                self.receipt_digest,
                self.conversation_id,
                self.request_identity,
                self.canonical_url,
                self.binding_digest,
            )
        ):
            raise ValueError("source authority binding fields must not be empty")
        values = {
            "source_fact_id": self.source_fact_id,
            "receipt_digest": self.receipt_digest,
            "conversation_id": self.conversation_id,
            "request_identity": self.request_identity,
            "canonical_url": self.canonical_url,
        }
        if canonical_json_digest(values) != self.binding_digest:
            raise ValueError("source authority binding digest mismatch")


@dataclass(frozen=True, slots=True)
class ToolExecutionOutput:
    content: str
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    source_receipts: tuple[SourceReceiptDraft, ...] = ()
    is_error: bool = False
    executed: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("source tool content must be a string")
        if not isinstance(self.is_error, bool) or not isinstance(self.executed, bool):
            raise TypeError("source tool outcome flags must be boolean")
        _assert_json_compatible(self.metadata, path="tool_execution_output.metadata")
        object.__setattr__(self, "metadata", _freeze_json_dict(self.metadata))
        object.__setattr__(self, "source_receipts", tuple(self.source_receipts))
        if any(
            not isinstance(receipt, SourceReceiptDraft)
            for receipt in self.source_receipts
        ):
            raise TypeError("source receipts must all be SourceReceiptDraft")
        if (self.is_error or not self.executed) and self.source_receipts:
            raise ValueError("failed or non-executed source output cannot carry receipts")


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
    approval_basis_revision: int | None = None
    source_authority: SourceAuthorityBinding | None = None
    # 015：prepare 时可见的 active process authority lease，用于 exact reuse 匹配（F2）。
    process_leases: tuple[ProcessAuthorityLeaseV1, ...] = ()
    # 017：sandbox durable leases（revision/terminal transition 失效，state 层执行）。
    sandbox_leases: tuple[SandboxAuthorityLeaseV1, ...] = ()
    # 018：browser durable leases 与 pending takeover（goal terminal 失效；
    # takeover 只携带 opaque identity，永不携带 credential/storage-state）。
    browser_leases: tuple[BrowserAuthorityLeaseV1, ...] = ()
    browser_takeover_pending: BrowserTakeoverRequestV1 | None = None
    # 当前 Goal 的结构化 proposed criteria；process prepare 只消费
    # FILESYSTEM_DIGEST artifact obligation，不从自由文本/argv 猜测。
    proposed_criteria: tuple[ProposedCriterion, ...] = ()
    # 已 admitted 的 criterion id：process artifact 绑定只考虑尚未由用户确认
    # digest 的 pending criterion。写批准后 criterion 同时保留在 proposed 与
    # admitted，不过滤会把已确认项误判为第二个 pending 义务而 fail-closed
    # 死锁（016 真实 E3 第 23/27/34 轮）。
    admitted_criterion_ids: frozenset[str] = frozenset()
    # 当前 active Goal revision 下可用于构造 citation manifest 的来源引用。
    # 这是 Runtime 的 authority snapshot；模型看到的 JSON Schema 只负责引导。
    citable_source_refs: tuple[str, ...] = ()
    citable_citation_sources: tuple[tuple[str, str], ...] = ()
    web_fetch_source_refs: tuple[str, ...] = ()
    citation_manifest_allowed: bool = False
    citation_sidecar_paths: tuple[str, ...] = ()
    citation_artifact_paths: tuple[str, ...] = ()
    citation_manifest_content_digests: tuple[str, ...] = ()
    public_web_requirement_pending: bool = False
    goal_correction_pending: bool = False
    # 019：raw claim capability 仅存在于当前 pre-bound composition；checkpoint
    # 与 ExecutionIntent 只保存其 digest 和 action authority。
    background_execution_authority: BackgroundExecutionAuthorityV1 | None = None
    background_tool_calls_used: int = 0
    background_sandbox_commands_used: int = 0
    background_browser_actions_used: int = 0
    invocation_origin: InvocationOrigin = InvocationOrigin.MODEL

    def __post_init__(self) -> None:
        if not isinstance(self.invocation_origin, InvocationOrigin):
            raise TypeError("tool context invocation origin must be closed")
        if self.approval_basis_revision is None:
            object.__setattr__(self, "approval_basis_revision", self.state_revision)
        if self.approval_basis_revision is not None and self.approval_basis_revision < 0:
            raise ValueError("approval basis revision must be non-negative")
        # goal 身份成对：goal_id/revision 同设或同缺；workspace 是会话级
        # 身份，独立于 goal 对（goal-less 工作区会话可只带 workspace——
        # 2026-10-25 goal-less 读覆盖裁决）。goal 对在场时必须同时带
        # workspace（goal 绑定的读写从未允许无 workspace）。
        goal_bound = self.goal_id is not None
        if goal_bound != (self.goal_revision is not None):
            raise ValueError("tool context goal identity must be complete")
        if goal_bound and self.workspace_identity_digest is None:
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
        if any(not isinstance(item, ProposedCriterion) for item in self.proposed_criteria):
            raise TypeError("tool context proposed_criteria must be ProposedCriterion values")
        object.__setattr__(self, "citable_source_refs", tuple(self.citable_source_refs))
        if len(set(self.citable_source_refs)) != len(self.citable_source_refs):
            raise ValueError("tool context citable source refs must be unique")
        source_ref_prefix = "source-ref:v1:"
        for source_ref in self.citable_source_refs:
            if not isinstance(source_ref, str):
                raise TypeError("tool context citable source refs must be strings")
            digest = source_ref.removeprefix(source_ref_prefix)
            if (
                not source_ref.startswith(source_ref_prefix)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("tool context citable source ref is malformed")
        object.__setattr__(
            self,
            "citable_citation_sources",
            tuple(tuple(pair) for pair in self.citable_citation_sources),
        )
        if len(set(self.citable_citation_sources)) != len(
            self.citable_citation_sources
        ):
            raise ValueError("tool context citable citation pairs must be unique")
        for pair in self.citable_citation_sources:
            if len(pair) != 2:
                raise ValueError("tool context citable citation pair is malformed")
            source_ref, source_id = pair
            if not isinstance(source_ref, str) or not isinstance(source_id, str):
                raise TypeError("tool context citable citation pair must contain strings")
            ref_digest = source_ref.removeprefix(source_ref_prefix)
            id_prefix = "source:v1:"
            id_digest = source_id.removeprefix(id_prefix)
            if (
                source_ref not in self.citable_source_refs
                or not source_ref.startswith(source_ref_prefix)
                or not _is_lower_hex(ref_digest, length=64)
                or not source_id.startswith(id_prefix)
                or not _is_lower_hex(id_digest, length=64)
            ):
                raise ValueError("tool context citable citation pair is invalid")
        object.__setattr__(
            self,
            "web_fetch_source_refs",
            tuple(self.web_fetch_source_refs),
        )
        if len(set(self.web_fetch_source_refs)) != len(self.web_fetch_source_refs):
            raise ValueError("tool context Web fetch source refs must be unique")
        for source_ref in self.web_fetch_source_refs:
            if not isinstance(source_ref, str):
                raise TypeError("tool context Web fetch source refs must be strings")
            digest = source_ref.removeprefix(source_ref_prefix)
            if (
                not source_ref.startswith(source_ref_prefix)
                or not _is_lower_hex(digest, length=64)
            ):
                raise ValueError("tool context Web fetch source ref is malformed")
        if not isinstance(self.citation_manifest_allowed, bool):
            raise TypeError("tool context citation manifest authority must be boolean")
        object.__setattr__(self, "citation_sidecar_paths", tuple(self.citation_sidecar_paths))
        if (
            len(set(self.citation_sidecar_paths)) != len(self.citation_sidecar_paths)
            or any(
                not _is_safe_relative_artifact_path(path)
                or not path.endswith(".citations.json")
                for path in self.citation_sidecar_paths
            )
        ):
            raise ValueError("tool context citation sidecar paths are invalid")
        object.__setattr__(self, "citation_artifact_paths", tuple(self.citation_artifact_paths))
        if (
            len(set(self.citation_artifact_paths)) != len(self.citation_artifact_paths)
            or any(
                not _is_safe_relative_artifact_path(path)
                or path.endswith(".citations.json")
                for path in self.citation_artifact_paths
            )
        ):
            raise ValueError("tool context citation artifact paths are invalid")
        object.__setattr__(
            self,
            "citation_manifest_content_digests",
            tuple(self.citation_manifest_content_digests),
        )
        if (
            len(set(self.citation_manifest_content_digests))
            != len(self.citation_manifest_content_digests)
            or any(
                not isinstance(digest, str) or not _is_lower_hex(digest, length=64)
                for digest in self.citation_manifest_content_digests
            )
        ):
            raise ValueError("tool context citation manifest content digests are invalid")
        if not isinstance(self.public_web_requirement_pending, bool):
            raise TypeError("tool context public Web requirement state must be boolean")
        if not isinstance(self.goal_correction_pending, bool):
            raise TypeError("tool context Goal correction state must be boolean")
        if self.background_execution_authority is not None and not isinstance(
            self.background_execution_authority,
            BackgroundExecutionAuthorityV1,
        ):
            raise TypeError("tool context background authority must use the closed v1 contract")
        for name in (
            "background_tool_calls_used",
            "background_sandbox_commands_used",
            "background_browser_actions_used",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"tool context {name} must be non-negative")
        if (
            self.background_execution_authority is not None
            and not self.background_execution_authority.occurrence_binding.binding_digest
        ):
            raise ValueError("tool context background binding must not be empty")
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
        if self.source_authority is not None and (
            self.source_authority.conversation_id != self.conversation_id
        ):
            raise ValueError("tool context source authority is cross-conversation")


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    request_id: str
    binding_digest: str
    approval_basis_revision: int | None = None

    def __post_init__(self) -> None:
        if not self.request_id or not self.binding_digest:
            raise ValueError("approval grant fields must not be empty")
        if self.approval_basis_revision is not None and self.approval_basis_revision < 0:
            raise ValueError("approval grant basis revision must be non-negative")


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
    invocation_origin: InvocationOrigin
    safety_binding: dict[str, JSONValue] = field(default_factory=dict)
    goal_id: str | None = None
    goal_revision: int | None = None
    workspace_identity_digest: str | None = None
    goal_authorization: GoalAuthorizationBinding | None = None
    fact_admission: FactAdmissionBinding | None = None
    preference_admission: PreferenceAdmissionBinding | None = None
    egress: EgressClass = EgressClass.NONE
    # F5（review finding 2026-08-16）：intent 的 authority 由 ToolSpec 显式投影，
    # 不得 constructor default 静默赋值。
    execution_authority: ExecutionAuthorityClass = field(kw_only=True)
    operation: str | None = None
    request_identity: str | None = None
    approval_basis_revision: int | None = None
    source_authority: SourceAuthorityBinding | None = None
    # 015：reuse 路径在 prepare 时绑定的 exact 匹配 lease，供 invoke 铸造 receipt 的
    # lease identity / use_ordinal。非 process intent 一律为 None。
    process_lease: ProcessAuthorityLeaseV1 | None = None
    # 017：reuse 路径绑定的 exact 匹配 sandbox lease；非 sandbox intent 一律 None。
    sandbox_lease: SandboxAuthorityLeaseV1 | None = None
    # 018：非 OBSERVE browser action 绑定的 exact single-use lease。
    browser_lease: BrowserAuthorityLeaseV1 | None = None
    # 018：takeover headed transition 的 Runtime-owned durable binding。
    # AgentRuntime 必须先持久化它，ToolRuntime 才能调用 adapter 显示窗口。
    browser_takeover_request: BrowserTakeoverRequestV1 | None = None
    # 019：只携带 action-scoped digest authority，绝不持久化 raw claim capability。
    background_action_authority: BackgroundActionAuthorityV1 | None = None

    def __post_init__(self) -> None:
        if not self.conversation_id or not self.run_id:
            raise ValueError("execution intent origin identity must be valid")
        if not isinstance(self.invocation_origin, InvocationOrigin):
            raise TypeError("execution intent invocation origin must be closed")
        _assert_json_compatible(self.arguments, path="execution_intent.arguments")
        _assert_json_compatible(self.safety_binding, path="execution_intent.safety_binding")
        object.__setattr__(self, "arguments", _freeze_json_dict(self.arguments))
        object.__setattr__(self, "safety_binding", _freeze_json_dict(self.safety_binding))
        # 同 ToolPrepareContext：goal 对成对、workspace 独立可单带
        # （goal-less 工作区会话），goal 对在场必须带 workspace。
        goal_bound = self.goal_id is not None
        if goal_bound != (self.goal_revision is not None):
            raise ValueError("execution intent goal identity must be complete")
        if goal_bound and self.workspace_identity_digest is None:
            raise ValueError("execution intent goal identity must be complete")
        if self.egress is EgressClass.PUBLIC_NETWORK and (
            not self.operation
            or not self.request_identity
            or self.approval_basis_revision is None
        ):
            raise ValueError("PUBLIC_NETWORK intent identity must be complete")
        if self.background_action_authority is not None:
            if not isinstance(
                self.background_action_authority,
                BackgroundActionAuthorityV1,
            ):
                raise TypeError("background action authority must use the closed v1 contract")
            expected_execution_authority = {
                "sandbox_confined": ExecutionAuthorityClass.ISOLATED_SANDBOX,
                "browser_public_observe": ExecutionAuthorityClass.BROWSER_SESSION,
            }[self.background_action_authority.action_class]
            if self.execution_authority is not expected_execution_authority:
                raise ValueError("background action class does not match execution authority")


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
    # 018：browser tool 请求 user takeover 的 typed 通道；唯一 AgentRuntime
    # 在持久化 pending 之前不得把该结果作为完成返回。
    browser_takeover_request: BrowserTakeoverRequestV1 | None = None
    # 2026-10-21：仅 Kernel 在受信任文件 registration 成功执行后填充；工具
    # 自报的同名字段会在 invoke 结果构造时被丢弃。
    result_source_proof: ProviderFileSourceProofV1 | None = None

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

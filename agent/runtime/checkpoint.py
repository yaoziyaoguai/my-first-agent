"""受保护的本地 POSIX JSON CheckpointStore。"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalGrant,
    ApprovalRequest,
    ArtifactConfirmationRequirementV1,
    AuthoritySourceKind,
    CompletionClaim,
    ContinuationPhase,
    ControlReceipt,
    ConversationFact,
    ConversationState,
    ConversationWorkspaceBindingV1,
    EgressClass,
    EvidenceOracleKind,
    EvidenceRecord,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    GoalAuthorizationBinding,
    GoalFrame,
    GoalStatus,
    InteractionState,
    LoadedSnapshot,
    ProcessAuthorityCandidateV1,
    ProcessAuthorityLeaseV1,
    ProposedCriterion,
    ProviderDisclosureReceipt,
    ProviderDisclosureRequest,
    RecordedRunResult,
    RecoveryRequest,
    ReplayRecord,
    RunStatus,
    SideEffectClass,
    ToolCall,
)
from agent.runtime.ports import CheckpointCASConflictError

SCHEMA_VERSION = 6
# v3 是 process-authority migration source；v4 是旧 strict process schema；v5 加入
# artifact confirmation。v6 绑定 candidate/lease 全部 immutable authority 字段，并把
# readable command 持久化到 lease。旧版本显式重算收窄后的 digest；v6 漂移 fail closed。
PROCESS_MIGRATION_VERSION = 3
PREVIOUS_SCHEMA_VERSION = 4
ARTIFACT_SCHEMA_VERSION = 5
LEGACY_SCHEMA_VERSION = 2
DEFAULT_MAX_STATE_BYTES = 2_000_000


class CheckpointError(RuntimeError):
    pass


class CheckpointMissingError(CheckpointError):
    pass


class CheckpointMalformedError(CheckpointError):
    pass


class CheckpointInvariantError(CheckpointError):
    pass


class CheckpointVersionError(CheckpointError):
    pass


class CheckpointConflictError(CheckpointError, CheckpointCASConflictError):
    def __init__(self, message: str, current: LoadedSnapshot | None = None) -> None:
        self.current = current
        CheckpointError.__init__(self, message)


class CheckpointSecurityError(CheckpointError):
    pass


class CheckpointCapacityError(CheckpointError):
    pass


@dataclass(slots=True)
class _LocalLease:
    store: LocalCheckpointStore
    directory_fd: int
    lock_fd: int
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(self.lock_fd)
            os.close(self.directory_fd)
            self.store._active_lease = None


class LocalCheckpointStore:
    def __init__(
        self,
        path: Path,
        *,
        max_state_bytes: int = DEFAULT_MAX_STATE_BYTES,
    ) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise CheckpointSecurityError("required POSIX no-follow flags are unavailable")
        if max_state_bytes < 1:
            raise ValueError("max_state_bytes must be positive")
        self._path = Path(path).absolute()
        self._directory = self._path.parent
        self._name = self._path.name
        if not self._name or self._name in {".", ".."}:
            raise ValueError("checkpoint path must name one file")
        self._lock_name = f".{self._name}.lock"
        self._max_state_bytes = max_state_bytes
        self._active_lease: _LocalLease | None = None

    @classmethod
    def initialize(
        cls,
        path: Path,
        state: ConversationState,
        *,
        max_state_bytes: int = DEFAULT_MAX_STATE_BYTES,
    ) -> LocalCheckpointStore:
        store = cls(path, max_state_bytes=max_state_bytes)
        store._create_directory()
        data = _encode_state(state)
        if len(data) > max_state_bytes:
            raise CheckpointCapacityError("initial checkpoint exceeds configured capacity")
        directory_fd = store._open_directory()
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _o_nofollow()
            try:
                fd = os.open(store._name, flags, 0o600, dir_fd=directory_fd)
            except FileExistsError as error:
                raise CheckpointConflictError("checkpoint already exists") from error
            except OSError as error:
                raise _security_or_checkpoint_error(error, "create checkpoint") from error
            try:
                os.fchmod(fd, 0o600)
                _write_all(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return store

    def load(self) -> LoadedSnapshot:
        directory_fd = self._open_directory()
        try:
            data = self._read_bytes(directory_fd)
        finally:
            os.close(directory_fd)
        return LoadedSnapshot(state=_decode_state(data), token=_token(data))

    def try_acquire(self, conversation_id: str) -> _LocalLease | None:
        if self._active_lease is not None:
            return None
        directory_fd = self._open_directory()
        flags = os.O_RDWR | os.O_CREAT | _o_nofollow()
        try:
            lock_fd = os.open(self._lock_name, flags, 0o600, dir_fd=directory_fd)
            _validate_regular_file(lock_fd, label="checkpoint lock")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(lock_fd)
                os.close(directory_fd)
                return None
            state = _decode_state(self._read_bytes(directory_fd))
            if state.conversation_id != conversation_id:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
                os.close(directory_fd)
                return None
        except Exception:
            if "lock_fd" in locals():
                with suppress(OSError):
                    os.close(lock_fd)
            with suppress(OSError):
                os.close(directory_fd)
            raise
        lease = _LocalLease(self, directory_fd, lock_fd)
        self._active_lease = lease
        return lease

    def compare_and_swap(
        self,
        snapshot: LoadedSnapshot,
        new_state: ConversationState,
    ) -> LoadedSnapshot:
        lease = self._active_lease
        if lease is None or lease.released:
            raise CheckpointConflictError("mutation lease is not held")
        current_data = self._read_bytes(lease.directory_fd)
        current = _decode_state(current_data)
        if _token(current_data) != snapshot.token or current.revision != snapshot.state.revision:
            raise CheckpointConflictError(
                "snapshot token or revision changed",
                LoadedSnapshot(current, _token(current_data)),
            )
        if current.conversation_id != new_state.conversation_id:
            raise CheckpointConflictError("conversation identity cannot change")
        if (
            current.workspace_binding is not None
            and new_state.workspace_binding != current.workspace_binding
        ):
            raise CheckpointInvariantError("workspace binding cannot change")

        data = _encode_state(new_state)
        if len(data) > self._max_state_bytes:
            raise CheckpointCapacityError("checkpoint exceeds configured capacity")
        temp_name = f".{self._name}.tmp-{secrets.token_hex(8)}"
        temp_fd: int | None = None
        try:
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _o_nofollow(),
                0o600,
                dir_fd=lease.directory_fd,
            )
            os.fchmod(temp_fd, 0o600)
            _write_all(temp_fd, data)
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            os.replace(
                temp_name,
                self._name,
                src_dir_fd=lease.directory_fd,
                dst_dir_fd=lease.directory_fd,
            )
            os.fsync(lease.directory_fd)
        except Exception:
            if temp_fd is not None:
                os.close(temp_fd)
            with suppress(FileNotFoundError):
                os.unlink(temp_name, dir_fd=lease.directory_fd)
            raise
        return LoadedSnapshot(new_state, _token(data))

    def ensure_capacity(self, snapshot: LoadedSnapshot, *, reserve_bytes: int) -> bool:
        if reserve_bytes < 0:
            raise ValueError("reserve_bytes must be non-negative")
        return len(_encode_state(snapshot.state)) + reserve_bytes <= self._max_state_bytes

    def _create_directory(self) -> None:
        with suppress(FileExistsError):
            self._directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        info = self._directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise CheckpointSecurityError("checkpoint parent must be a real directory")
        if info.st_uid != os.getuid():
            raise CheckpointSecurityError("checkpoint directory owner mismatch")
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise CheckpointSecurityError("checkpoint directory mode must be 0700")

    def _open_directory(self) -> int:
        try:
            fd = os.open(
                self._directory,
                os.O_RDONLY | os.O_DIRECTORY | _o_nofollow(),
            )
        except FileNotFoundError as error:
            raise CheckpointMissingError("checkpoint directory is missing") from error
        except OSError as error:
            raise _security_or_checkpoint_error(error, "open checkpoint directory") from error
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            os.close(fd)
            raise CheckpointSecurityError("checkpoint directory identity is unsafe")
        if stat.S_IMODE(info.st_mode) != 0o700:
            os.close(fd)
            raise CheckpointSecurityError("checkpoint directory mode must be 0700")
        return fd

    def _read_bytes(self, directory_fd: int) -> bytes:
        try:
            fd = os.open(self._name, os.O_RDONLY | _o_nofollow(), dir_fd=directory_fd)
        except FileNotFoundError as error:
            raise CheckpointMissingError("checkpoint file is missing") from error
        except OSError as error:
            raise _security_or_checkpoint_error(error, "open checkpoint") from error
        try:
            _validate_regular_file(fd, label="checkpoint")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(65_536, self._max_state_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > self._max_state_bytes:
                    raise CheckpointCapacityError("checkpoint exceeds configured capacity")
            return b"".join(chunks)
        finally:
            os.close(fd)


@dataclass(slots=True)
class _MemoryLease:
    store: InMemoryCheckpointStore
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        self.store._lock.release()


class InMemoryCheckpointStore:
    """Default non-durable store; it implements the same CAS port without filesystem I/O."""

    def __init__(
        self,
        state: ConversationState,
        *,
        max_state_bytes: int = DEFAULT_MAX_STATE_BYTES,
    ) -> None:
        self._state = state
        self._token_number = 0
        self._max_state_bytes = max_state_bytes
        self._lock = Lock()

    def load(self) -> LoadedSnapshot:
        return LoadedSnapshot(self._state, f"memory-{self._token_number}")

    def try_acquire(self, conversation_id: str) -> _MemoryLease | None:
        if conversation_id != self._state.conversation_id or not self._lock.acquire(False):
            return None
        return _MemoryLease(self)

    def compare_and_swap(
        self,
        snapshot: LoadedSnapshot,
        new_state: ConversationState,
    ) -> LoadedSnapshot:
        if not self._lock.locked():
            raise CheckpointConflictError("mutation lease is not held")
        if snapshot.token != f"memory-{self._token_number}":
            raise CheckpointConflictError("snapshot token changed", self.load())
        if snapshot.state.revision != self._state.revision:
            raise CheckpointConflictError("snapshot revision changed", self.load())
        if new_state.conversation_id != self._state.conversation_id:
            raise CheckpointConflictError("conversation identity cannot change")
        if (
            self._state.workspace_binding is not None
            and new_state.workspace_binding != self._state.workspace_binding
        ):
            raise CheckpointInvariantError("workspace binding cannot change")
        encoded = _encode_state(new_state)
        if len(encoded) > self._max_state_bytes:
            raise CheckpointCapacityError("checkpoint exceeds configured capacity")
        self._state = new_state
        self._token_number += 1
        return self.load()

    def ensure_capacity(self, snapshot: LoadedSnapshot, *, reserve_bytes: int) -> bool:
        if reserve_bytes < 0:
            raise ValueError("reserve_bytes must be non-negative")
        return len(_encode_state(snapshot.state)) + reserve_bytes <= self._max_state_bytes


def _o_nofollow() -> int:
    return os.O_NOFOLLOW


def _security_or_checkpoint_error(error: OSError, operation: str) -> CheckpointError:
    if error.errno in {errno.ELOOP, errno.EMLINK, errno.EPERM, errno.EACCES}:
        return CheckpointSecurityError(f"unsafe filesystem object during {operation}")
    return CheckpointError(f"filesystem error during {operation}: {error.strerror}")


def _validate_regular_file(fd: int, *, label: str) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise CheckpointSecurityError(f"{label} must be a regular file")
    if info.st_uid != os.getuid():
        raise CheckpointSecurityError(f"{label} owner mismatch")
    if info.st_nlink != 1:
        raise CheckpointSecurityError(f"{label} link count must be one")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise CheckpointSecurityError(f"{label} mode must be 0600")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise CheckpointError("checkpoint write made no progress")
        view = view[written:]


def _token(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _encode_state(state: ConversationState) -> bytes:
    has_structured_proposal = state.goal is not None and any(
        criterion.oracle_kind is not None or criterion.artifact_path is not None
        for criterion in state.goal.proposed_criteria
    )
    version = (
        SCHEMA_VERSION
        if (
            state.workspace_binding is not None
            or state.active_run is not None
            or state.process_leases
            or has_structured_proposal
        )
        else LEGACY_SCHEMA_VERSION
    )
    document = {
        "schema_version": version,
        "state": _state_to_dict(
            state,
            include_workspace_binding=version == SCHEMA_VERSION,
            include_proposed_contract=version == SCHEMA_VERSION,
        ),
    }
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    )


def _decode_state(data: bytes) -> ConversationState:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CheckpointMalformedError("checkpoint is not valid UTF-8 JSON") from error
    document = _object(document, "document")
    _expect_keys(document, {"schema_version", "state"}, "document")
    version = document["schema_version"]
    if version not in {
        LEGACY_SCHEMA_VERSION,
        PROCESS_MIGRATION_VERSION,
        PREVIOUS_SCHEMA_VERSION,
        ARTIFACT_SCHEMA_VERSION,
        SCHEMA_VERSION,
    }:
        raise CheckpointVersionError(f"unsupported checkpoint schema version: {version}")
    try:
        return _state_from_dict(
            _object(document["state"], "state"),
            include_workspace_binding=version != LEGACY_SCHEMA_VERSION,
            process_migration=version == PROCESS_MIGRATION_VERSION,
            proposed_contract_current=version in {ARTIFACT_SCHEMA_VERSION, SCHEMA_VERSION},
            process_contract_current=version == SCHEMA_VERSION,
        )
    except CheckpointVersionError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise CheckpointInvariantError(f"checkpoint state invariant failed: {error}") from error


def _state_to_dict(
    state: ConversationState,
    *,
    include_workspace_binding: bool,
    include_proposed_contract: bool,
) -> dict:
    value = {
        "conversation_id": state.conversation_id,
        "revision": state.revision,
        "next_action_seq": state.next_action_seq,
        "replay_floor": state.replay_floor,
        "replay_records": [_replay_to_dict(record) for record in state.replay_records],
        "facts": [_fact_to_dict(fact) for fact in state.facts],
        "active_run": _active_to_dict(state.active_run),
        "last_safe_result": _result_to_dict(state.last_safe_result),
        "goal": _goal_to_dict(
            state.goal,
            include_proposed_contract=include_proposed_contract,
        ),
        "goal_authorizations": [
            _goal_authorization_to_dict(binding)
            for binding in state.goal_authorizations
        ],
        "evidence_records": [
            _evidence_to_dict(record) for record in state.evidence_records
        ],
        "completion_claim": _completion_claim_to_dict(state.completion_claim),
        "interaction_state": state.interaction_state.value,
        "provider_disclosure_request": _disclosure_request_to_dict(
            state.provider_disclosure_request
        ),
        "provider_disclosure_receipt": _disclosure_receipt_to_dict(
            state.provider_disclosure_receipt
        ),
        "control_receipts": [
            _control_receipt_to_dict(receipt) for receipt in state.control_receipts
        ],
        "process_leases": [_process_lease_to_dict(lease) for lease in state.process_leases],
    }
    if include_workspace_binding:
        value["workspace_binding"] = _workspace_binding_to_dict(
            state.workspace_binding
        )
    return value


def _state_from_dict(
    value: dict,
    *,
    include_workspace_binding: bool,
    process_migration: bool = False,
    proposed_contract_current: bool = False,
    process_contract_current: bool = False,
) -> ConversationState:
    keys = {
        "conversation_id",
        "revision",
        "next_action_seq",
        "replay_floor",
        "replay_records",
        "facts",
        "active_run",
        "last_safe_result",
        "goal",
        "goal_authorizations",
        "evidence_records",
        "completion_claim",
        "interaction_state",
        "provider_disclosure_request",
        "provider_disclosure_receipt",
        "control_receipts",
    }
    if include_workspace_binding:
        keys.add("workspace_binding")
        if not process_migration:
            # v4/v5：process_leases 必备（缺失 → version error，fail closed）。
            keys.add("process_leases")
    # migration（v3）：process_leases 缺失按空迁移；v2 legacy 同样允许缺失。
    if "process_leases" in value:
        keys.add("process_leases")
    _expect_keys(value, keys, "state")
    return ConversationState(
        conversation_id=_string(value["conversation_id"], "conversation_id"),
        workspace_binding=(
            _workspace_binding_from_dict(value["workspace_binding"])
            if include_workspace_binding
            else None
        ),
        revision=_integer(value["revision"], "revision"),
        next_action_seq=_integer(value["next_action_seq"], "next_action_seq"),
        replay_floor=_integer(value["replay_floor"], "replay_floor"),
        replay_records=tuple(
            _replay_from_dict(_object(item, "replay_record"))
            for item in _array(value["replay_records"], "replay_records")
        ),
        facts=tuple(
            _fact_from_dict(_object(item, "fact"))
            for item in _array(value["facts"], "facts")
        ),
        active_run=_active_from_dict(
            value["active_run"],
            strict_current=include_workspace_binding and not process_migration,
            strict_artifact_contract=proposed_contract_current,
            process_contract_current=process_contract_current,
        ),
        last_safe_result=_result_from_dict(value["last_safe_result"]),
        goal=_goal_from_dict(
            value["goal"],
            proposed_contract_current=proposed_contract_current,
        ),
        goal_authorizations=tuple(
            _goal_authorization_from_dict(_object(item, "goal_authorization"))
            for item in _array(value["goal_authorizations"], "goal_authorizations")
        ),
        evidence_records=tuple(
            _evidence_from_dict(_object(item, "evidence_record"))
            for item in _array(value["evidence_records"], "evidence_records")
        ),
        completion_claim=_completion_claim_from_dict(value["completion_claim"]),
        interaction_state=InteractionState(
            _string(value["interaction_state"], "interaction_state")
        ),
        provider_disclosure_request=_disclosure_request_from_dict(
            value["provider_disclosure_request"]
        ),
        provider_disclosure_receipt=_disclosure_receipt_from_dict(
            value["provider_disclosure_receipt"]
        ),
        control_receipts=tuple(
            _control_receipt_from_dict(_object(item, "control_receipt"))
            for item in _array(value["control_receipts"], "control_receipts")
        ),
        # v3-v5 的 process authority 没有 v6 不可变 digest 合同。迁移时
        # 必须撤销而不是以当前代码重签，否则被改写的旧文档会获得新权限。
        process_leases=(
            tuple(
                _process_lease_from_dict(
                    _object(item, "process_lease"),
                    contract_current=True,
                )
                for item in _array(value.get("process_leases", []), "process_leases")
            )
            if process_contract_current
            else ()
        ),
    )


def _workspace_binding_to_dict(
    binding: ConversationWorkspaceBindingV1 | None,
) -> dict | None:
    if binding is None:
        return None
    return {
        "workspace_scope_digest": binding.workspace_scope_digest,
        "workspace_identity_digest": binding.workspace_identity_digest,
        "bound_at": binding.bound_at,
        "binding_digest": binding.binding_digest,
    }


def _workspace_binding_from_dict(value) -> ConversationWorkspaceBindingV1 | None:
    if value is None:
        return None
    value = _object(value, "workspace_binding")
    keys = {
        "workspace_scope_digest",
        "workspace_identity_digest",
        "bound_at",
        "binding_digest",
    }
    _expect_keys(value, keys, "workspace_binding")
    return ConversationWorkspaceBindingV1(
        workspace_scope_digest=_string(
            value["workspace_scope_digest"],
            "workspace_binding.workspace_scope_digest",
        ),
        workspace_identity_digest=_string(
            value["workspace_identity_digest"],
            "workspace_binding.workspace_identity_digest",
        ),
        bound_at=_string(value["bound_at"], "workspace_binding.bound_at"),
        binding_digest=_string(
            value["binding_digest"],
            "workspace_binding.binding_digest",
        ),
    )


def _goal_to_dict(
    goal: GoalFrame | None,
    *,
    include_proposed_contract: bool,
) -> dict | None:
    if goal is None:
        return None
    return {
        "goal_id": goal.goal_id,
        "revision": goal.revision,
        "created_from_fact_ids": list(goal.created_from_fact_ids),
        "workspace_identity_digest": goal.workspace_identity_digest,
        "user_outcome": goal.user_outcome,
        "beneficiary": goal.beneficiary,
        "targets": list(goal.targets),
        "scope": list(goal.scope),
        "non_goals": list(goal.non_goals),
        "assumptions": list(goal.assumptions),
        "proposed_criteria": [
            {
                "criterion_id": item.criterion_id,
                "description": item.description,
                **(
                    {
                        "oracle_kind": (
                            item.oracle_kind.value if item.oracle_kind is not None else None
                        ),
                        "artifact_path": item.artifact_path,
                    }
                    if include_proposed_contract
                    else {}
                ),
            }
            for item in goal.proposed_criteria
        ],
        "admitted_criteria": [
            {
                "criterion_id": item.criterion_id,
                "description": item.description,
                "source_fact_id": item.source_fact_id,
                "oracle_kind": item.oracle_kind.value,
                "predicate": item.predicate,
                "required_evidence_class": item.required_evidence_class,
                "admission_digest": item.admission_digest,
                "mandatory": item.mandatory,
            }
            for item in goal.admitted_criteria
        ],
        "authority_snapshot": goal.authority_snapshot,
        "status": goal.status.value,
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
        "progress_summary": goal.progress_summary,
        "next_step": goal.next_step,
    }


def _goal_authorization_to_dict(value: GoalAuthorizationBinding) -> dict:
    return {
        "binding_id": value.binding_id,
        "goal_id": value.goal_id,
        "goal_revision": value.goal_revision,
        "workspace_identity_digest": value.workspace_identity_digest,
        "operation": value.operation,
        "normalized_target": value.normalized_target,
        "source_kind": value.source_kind.value,
        "source_id": value.source_id,
        "source_digest": value.source_digest,
        "binding_digest": value.binding_digest,
    }


def _goal_authorization_from_dict(value: dict) -> GoalAuthorizationBinding:
    keys = {
        "binding_id",
        "goal_id",
        "goal_revision",
        "workspace_identity_digest",
        "operation",
        "normalized_target",
        "source_kind",
        "source_id",
        "source_digest",
        "binding_digest",
    }
    _expect_keys(value, keys, "goal_authorization")
    return GoalAuthorizationBinding(
        binding_id=_string(value["binding_id"], "goal_authorization.binding_id"),
        goal_id=_string(value["goal_id"], "goal_authorization.goal_id"),
        goal_revision=_integer(value["goal_revision"], "goal_authorization.goal_revision"),
        workspace_identity_digest=_string(
            value["workspace_identity_digest"],
            "goal_authorization.workspace_identity_digest",
        ),
        operation=_string(value["operation"], "goal_authorization.operation"),
        normalized_target=_string(
            value["normalized_target"],
            "goal_authorization.normalized_target",
        ),
        source_kind=AuthoritySourceKind(
            _string(value["source_kind"], "goal_authorization.source_kind")
        ),
        source_id=_string(value["source_id"], "goal_authorization.source_id"),
        source_digest=_string(value["source_digest"], "goal_authorization.source_digest"),
        binding_digest=_string(
            value["binding_digest"],
            "goal_authorization.binding_digest",
        ),
    )


def _goal_from_dict(
    value,
    *,
    proposed_contract_current: bool = False,
) -> GoalFrame | None:
    if value is None:
        return None
    value = _object(value, "goal")
    keys = {
        "goal_id",
        "revision",
        "created_from_fact_ids",
        "workspace_identity_digest",
        "user_outcome",
        "beneficiary",
        "targets",
        "scope",
        "non_goals",
        "assumptions",
        "proposed_criteria",
        "admitted_criteria",
        "authority_snapshot",
        "status",
        "created_at",
        "updated_at",
        "progress_summary",
        "next_step",
    }
    _expect_keys(value, keys, "goal")
    proposed = []
    for raw in _array(value["proposed_criteria"], "goal.proposed_criteria"):
        item = _object(raw, "proposed_criterion")
        proposed_keys = {"criterion_id", "description"}
        if proposed_contract_current:
            proposed_keys.update({"oracle_kind", "artifact_path"})
        _expect_keys(item, proposed_keys, "proposed_criterion")
        raw_oracle = item.get("oracle_kind")
        proposed.append(
            ProposedCriterion(
                criterion_id=_string(item["criterion_id"], "criterion_id"),
                description=_string(item["description"], "criterion.description"),
                oracle_kind=(
                    None
                    if raw_oracle is None
                    else EvidenceOracleKind(
                        _string(raw_oracle, "criterion.oracle_kind")
                    )
                ),
                artifact_path=_optional_string(
                    item.get("artifact_path"),
                    "criterion.artifact_path",
                ),
            )
        )
    admitted = []
    admitted_keys = {
        "criterion_id",
        "description",
        "source_fact_id",
        "oracle_kind",
        "predicate",
        "required_evidence_class",
        "admission_digest",
        "mandatory",
    }
    for raw in _array(value["admitted_criteria"], "goal.admitted_criteria"):
        item = _object(raw, "admitted_criterion")
        _expect_keys(item, admitted_keys, "admitted_criterion")
        admitted.append(
            AdmittedCriterion(
                criterion_id=_string(item["criterion_id"], "criterion_id"),
                description=_string(item["description"], "criterion.description"),
                source_fact_id=_string(item["source_fact_id"], "source_fact_id"),
                oracle_kind=EvidenceOracleKind(
                    _string(item["oracle_kind"], "oracle_kind")
                ),
                predicate=_object(item["predicate"], "criterion.predicate"),
                required_evidence_class=_string(
                    item["required_evidence_class"],
                    "required_evidence_class",
                ),
                admission_digest=_string(item["admission_digest"], "admission_digest"),
                mandatory=_boolean(item["mandatory"], "criterion.mandatory"),
            )
        )
    return GoalFrame(
        goal_id=_string(value["goal_id"], "goal_id"),
        revision=_integer(value["revision"], "goal.revision"),
        created_from_fact_ids=tuple(
            _string(item, "created_from_fact_id")
            for item in _array(value["created_from_fact_ids"], "created_from_fact_ids")
        ),
        workspace_identity_digest=_string(
            value["workspace_identity_digest"],
            "workspace_identity_digest",
        ),
        user_outcome=_string(value["user_outcome"], "user_outcome"),
        beneficiary=_string(value["beneficiary"], "beneficiary"),
        targets=tuple(
            _string(item, "goal.target")
            for item in _array(value["targets"], "goal.targets")
        ),
        scope=tuple(
            _string(item, "goal.scope")
            for item in _array(value["scope"], "goal.scope")
        ),
        non_goals=tuple(
            _string(item, "goal.non_goal")
            for item in _array(value["non_goals"], "goal.non_goals")
        ),
        assumptions=tuple(
            _string(item, "goal.assumption")
            for item in _array(value["assumptions"], "goal.assumptions")
        ),
        proposed_criteria=tuple(proposed),
        admitted_criteria=tuple(admitted),
        authority_snapshot=_string(value["authority_snapshot"], "authority_snapshot"),
        status=GoalStatus(_string(value["status"], "goal.status")),
        created_at=_string(value["created_at"], "goal.created_at"),
        updated_at=_string(value["updated_at"], "goal.updated_at"),
        progress_summary=_optional_string(
            value["progress_summary"],
            "goal.progress_summary",
        ),
        next_step=_optional_string(value["next_step"], "goal.next_step"),
    )


def _evidence_to_dict(record: EvidenceRecord) -> dict:
    return {
        "evidence_id": record.evidence_id,
        "goal_id": record.goal_id,
        "goal_revision": record.goal_revision,
        "criterion_id": record.criterion_id,
        "oracle_kind": record.oracle_kind.value,
        "predicate_digest": record.predicate_digest,
        "source_fact_ids": list(record.source_fact_ids),
        "source_digest": record.source_digest,
        "oracle_identity": record.oracle_identity,
        "passed": record.passed,
        "observed_at": record.observed_at,
    }


def _evidence_from_dict(value: dict) -> EvidenceRecord:
    keys = {
        "evidence_id",
        "goal_id",
        "goal_revision",
        "criterion_id",
        "oracle_kind",
        "predicate_digest",
        "source_fact_ids",
        "source_digest",
        "oracle_identity",
        "passed",
        "observed_at",
    }
    _expect_keys(value, keys, "evidence_record")
    return EvidenceRecord(
        evidence_id=_string(value["evidence_id"], "evidence_id"),
        goal_id=_string(value["goal_id"], "evidence.goal_id"),
        goal_revision=_integer(value["goal_revision"], "evidence.goal_revision"),
        criterion_id=_string(value["criterion_id"], "criterion_id"),
        oracle_kind=EvidenceOracleKind(_string(value["oracle_kind"], "oracle_kind")),
        predicate_digest=_string(value["predicate_digest"], "predicate_digest"),
        source_fact_ids=tuple(
            _string(item, "evidence.source_fact_id")
            for item in _array(value["source_fact_ids"], "source_fact_ids")
        ),
        source_digest=_string(value["source_digest"], "source_digest"),
        oracle_identity=_string(value["oracle_identity"], "oracle_identity"),
        passed=_boolean(value["passed"], "evidence.passed"),
        observed_at=_string(value["observed_at"], "evidence.observed_at"),
    )


def _completion_claim_to_dict(value: CompletionClaim | None) -> dict | None:
    if value is None:
        return None
    return {
        "correlation_id": value.correlation_id,
        "goal_id": value.goal_id,
        "goal_revision": value.goal_revision,
        "criterion_evidence_refs": list(value.criterion_evidence_refs),
    }


def _completion_claim_from_dict(value) -> CompletionClaim | None:
    if value is None:
        return None
    value = _object(value, "completion_claim")
    _expect_keys(
        value,
        {"correlation_id", "goal_id", "goal_revision", "criterion_evidence_refs"},
        "completion_claim",
    )
    return CompletionClaim(
        correlation_id=_string(value["correlation_id"], "correlation_id"),
        goal_id=_string(value["goal_id"], "completion_claim.goal_id"),
        goal_revision=_integer(value["goal_revision"], "completion_claim.goal_revision"),
        criterion_evidence_refs=tuple(
            _string(item, "criterion_evidence_ref")
            for item in _array(
                value["criterion_evidence_refs"],
                "criterion_evidence_refs",
            )
        ),
    )


def _disclosure_request_to_dict(value: ProviderDisclosureRequest | None) -> dict | None:
    if value is None:
        return None
    return {
        "disclosure_id": value.disclosure_id,
        "provider_descriptor_digest": value.provider_descriptor_digest,
        "canonical_destination": value.canonical_destination,
        "model": value.model,
        "data_classes": list(value.data_classes),
        "request_digest": value.request_digest,
    }


def _disclosure_request_from_dict(value) -> ProviderDisclosureRequest | None:
    if value is None:
        return None
    value = _object(value, "provider_disclosure_request")
    keys = {
        "disclosure_id",
        "provider_descriptor_digest",
        "canonical_destination",
        "model",
        "data_classes",
        "request_digest",
    }
    _expect_keys(value, keys, "provider_disclosure_request")
    return ProviderDisclosureRequest(
        disclosure_id=_string(value["disclosure_id"], "disclosure_id"),
        provider_descriptor_digest=_string(
            value["provider_descriptor_digest"],
            "provider_descriptor_digest",
        ),
        canonical_destination=_string(
            value["canonical_destination"],
            "canonical_destination",
        ),
        model=_string(value["model"], "provider_model"),
        data_classes=tuple(
            _string(item, "data_class")
            for item in _array(value["data_classes"], "data_classes")
        ),
        request_digest=_string(value["request_digest"], "request_digest"),
    )


def _disclosure_receipt_to_dict(value: ProviderDisclosureReceipt | None) -> dict | None:
    if value is None:
        return None
    return {
        "receipt_id": value.receipt_id,
        "request_digest": value.request_digest,
        "acknowledged_action_seq": value.acknowledged_action_seq,
        "acknowledged_at": value.acknowledged_at,
    }


def _disclosure_receipt_from_dict(value) -> ProviderDisclosureReceipt | None:
    if value is None:
        return None
    value = _object(value, "provider_disclosure_receipt")
    keys = {"receipt_id", "request_digest", "acknowledged_action_seq", "acknowledged_at"}
    _expect_keys(value, keys, "provider_disclosure_receipt")
    return ProviderDisclosureReceipt(
        receipt_id=_string(value["receipt_id"], "receipt_id"),
        request_digest=_string(value["request_digest"], "request_digest"),
        acknowledged_action_seq=_integer(
            value["acknowledged_action_seq"],
            "acknowledged_action_seq",
        ),
        acknowledged_at=_string(value["acknowledged_at"], "acknowledged_at"),
    )


def _control_receipt_to_dict(value: ControlReceipt) -> dict:
    return {
        "correlation_id": value.correlation_id,
        "control_kind": value.control_kind,
        "goal_id": value.goal_id,
        "goal_revision": value.goal_revision,
        "accepted_state_revision": value.accepted_state_revision,
        "payload_digest": value.payload_digest,
        "receipt_digest": value.receipt_digest,
    }


def _control_receipt_from_dict(value: dict) -> ControlReceipt:
    keys = {
        "correlation_id",
        "control_kind",
        "goal_id",
        "goal_revision",
        "accepted_state_revision",
        "payload_digest",
        "receipt_digest",
    }
    _expect_keys(value, keys, "control_receipt")
    goal_revision = value["goal_revision"]
    return ControlReceipt(
        correlation_id=_string(value["correlation_id"], "correlation_id"),
        control_kind=_string(value["control_kind"], "control_kind"),
        goal_id=_optional_string(value["goal_id"], "control_receipt.goal_id"),
        goal_revision=(
            None
            if goal_revision is None
            else _integer(goal_revision, "control_receipt.goal_revision")
        ),
        accepted_state_revision=_integer(
            value["accepted_state_revision"],
            "accepted_state_revision",
        ),
        payload_digest=_string(value["payload_digest"], "payload_digest"),
        receipt_digest=_string(value["receipt_digest"], "receipt_digest"),
    )


def _fact_to_dict(fact: ConversationFact) -> dict:
    return {"fact_id": fact.fact_id, "kind": fact.kind.value, "content": fact.content}


def _fact_from_dict(value: dict) -> ConversationFact:
    _expect_keys(value, {"fact_id", "kind", "content"}, "fact")
    return ConversationFact(
        fact_id=_string(value["fact_id"], "fact_id"),
        kind=FactKind(_string(value["kind"], "fact.kind")),
        content=_object(value["content"], "fact.content"),
    )


def _result_to_dict(result: RecordedRunResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "run_id": result.run_id,
        "message": result.message,
        "request_id": result.request_id,
        "error_code": result.error_code,
    }


def _result_from_dict(value) -> RecordedRunResult | None:
    if value is None:
        return None
    value = _object(value, "result")
    _expect_keys(value, {"status", "run_id", "message", "request_id", "error_code"}, "result")
    return RecordedRunResult(
        status=RunStatus(_string(value["status"], "result.status")),
        run_id=_optional_string(value["run_id"], "result.run_id"),
        message=_optional_string(value["message"], "result.message"),
        request_id=_optional_string(value["request_id"], "result.request_id"),
        error_code=_optional_string(value["error_code"], "result.error_code"),
    )


def _replay_to_dict(record: ReplayRecord) -> dict:
    return {
        "action_seq": record.action_seq,
        "action_digest": record.action_digest,
        "result": _result_to_dict(record.result),
    }


def _replay_from_dict(value: dict) -> ReplayRecord:
    _expect_keys(value, {"action_seq", "action_digest", "result"}, "replay_record")
    return ReplayRecord(
        action_seq=_integer(value["action_seq"], "action_seq"),
        action_digest=_string(value["action_digest"], "action_digest"),
        result=_result_from_dict(value["result"]),
    )


def _active_to_dict(active: ActiveRun | None) -> dict | None:
    if active is None:
        return None
    return {
        "run_id": active.run_id,
        "status": active.status.value,
        "phase": active.phase.value,
        "owner_invocation_id": active.owner_invocation_id,
        "batch_cursor": active.batch_cursor,
        "pending_request": _pending_to_dict(active.pending_request),
        "executing_intent": _executing_to_dict(active.executing_intent),
        "tool_calls": [_tool_call_to_dict(call) for call in active.tool_calls],
        "approval_grant": _approval_grant_to_dict(active.approval_grant),
        "approved_request_ids": list(active.approved_request_ids),
        "rejected_request_ids": list(active.rejected_request_ids),
    }


def _active_from_dict(
    value,
    *,
    strict_current: bool = False,
    strict_artifact_contract: bool = False,
    process_contract_current: bool = False,
) -> ActiveRun | None:
    if value is None:
        return None
    value = _object(value, "active_run")
    keys = {
        "run_id",
        "status",
        "phase",
        "owner_invocation_id",
        "batch_cursor",
        "pending_request",
        "executing_intent",
        "tool_calls",
        "approval_grant",
        "approved_request_ids",
        "rejected_request_ids",
    }
    _expect_keys(value, keys, "active_run")
    return ActiveRun(
        run_id=_string(value["run_id"], "active_run.run_id"),
        status=ActiveRunStatus(_string(value["status"], "active_run.status")),
        phase=ContinuationPhase(_string(value["phase"], "active_run.phase")),
        owner_invocation_id=_optional_string(
            value["owner_invocation_id"],
            "active_run.owner_invocation_id",
        ),
        batch_cursor=_integer(value["batch_cursor"], "active_run.batch_cursor"),
        pending_request=_pending_from_dict(
            value["pending_request"],
            strict_artifact_contract=strict_artifact_contract,
            process_contract_current=process_contract_current,
        ),
        executing_intent=_executing_from_dict(
            value["executing_intent"], strict_current=strict_current
        ),
        tool_calls=tuple(
            _tool_call_from_dict(_object(item, "tool_call"))
            for item in _array(value["tool_calls"], "active_run.tool_calls")
        ),
        approval_grant=_approval_grant_from_dict(value["approval_grant"]),
        approved_request_ids=tuple(
            _string(item, "approved_request_id")
            for item in _array(value["approved_request_ids"], "approved_request_ids")
        ),
        rejected_request_ids=tuple(
            _string(item, "rejected_request_id")
            for item in _array(value["rejected_request_ids"], "rejected_request_ids")
        ),
    )


def _pending_to_dict(pending) -> dict | None:
    if pending is None:
        return None
    if isinstance(pending, ApprovalRequest):
        return {
            "type": "approval",
            "request_id": pending.request_id,
            "run_id": pending.run_id,
            "tool_call_id": pending.tool_call_id,
            "binding_digest": pending.binding_digest,
            "preview": pending.preview,
            "tool_name": pending.tool_name,
            "state_revision": pending.state_revision,
            "approval_basis_revision": pending.approval_basis_revision,
            "arguments_digest": pending.arguments_digest,
            "policy_identity": pending.policy_identity,
            "risk": pending.risk,
            "side_effect": pending.side_effect,
            "target_digest": pending.target_digest,
            "precondition_digest": pending.precondition_digest,
            "new_content_digest": pending.new_content_digest,
            "egress": pending.egress,
            "operation": pending.operation,
            "request_identity": pending.request_identity,
            "destination_digest": pending.destination_digest,
            "cost_class": pending.cost_class,
            "trust_notice_id": pending.trust_notice_id,
            "trust_notice_digest": pending.trust_notice_digest,
            "process_authority_candidate": _process_authority_candidate_to_dict(
                pending.process_authority_candidate
            ),
            "artifact_confirmation_requirement": (
                _artifact_confirmation_requirement_to_dict(
                    pending.artifact_confirmation_requirement
                )
            ),
        }
    return {
        "type": "recovery",
        "request_id": pending.request_id,
        "run_id": pending.run_id,
        "tool_call_id": pending.tool_call_id,
        "binding_digest": pending.binding_digest,
        "summary": pending.summary,
    }


def _pending_from_dict(
    value,
    *,
    strict_artifact_contract: bool = False,
    process_contract_current: bool = True,
):
    if value is None:
        return None
    value = _object(value, "pending_request")
    request_type = value.get("type")
    if request_type == "approval":
        legacy_keys = {
            "type",
            "request_id",
            "run_id",
            "tool_call_id",
            "binding_digest",
            "preview",
            "tool_name",
            "state_revision",
            "arguments_digest",
            "policy_identity",
            "risk",
            "side_effect",
            "target_digest",
            "precondition_digest",
            "new_content_digest",
        }
        keys = {
            *legacy_keys,
            "approval_basis_revision",
            "egress",
            "operation",
            "request_identity",
            "destination_digest",
            "cost_class",
            "trust_notice_id",
            "trust_notice_digest",
        }
        actual_keys = frozenset(value)
        basis_keys = {*legacy_keys, "approval_basis_revision"}
        process_keys = {*keys, "process_authority_candidate"}
        artifact_keys = {*process_keys, "artifact_confirmation_requirement"}
        known_key_sets = {
            frozenset(legacy_keys),
            frozenset(basis_keys),
            frozenset(keys),
            frozenset(process_keys),
            frozenset(artifact_keys),
        }
        if strict_artifact_contract or actual_keys not in known_key_sets:
            _expect_keys(value, artifact_keys, "approval_request")
        state_revision = value["state_revision"]
        approval_basis_revision = value.get("approval_basis_revision")
        return ApprovalRequest(
            request_id=_string(value["request_id"], "request_id"),
            run_id=_string(value["run_id"], "run_id"),
            tool_call_id=_string(value["tool_call_id"], "tool_call_id"),
            binding_digest=_string(value["binding_digest"], "binding_digest"),
            preview=_string(value["preview"], "preview"),
            tool_name=_optional_string(value["tool_name"], "tool_name"),
            state_revision=(
                None if state_revision is None else _integer(state_revision, "state_revision")
            ),
            approval_basis_revision=(
                None
                if approval_basis_revision is None
                else _integer(approval_basis_revision, "approval_basis_revision")
            ),
            arguments_digest=_optional_string(value["arguments_digest"], "arguments_digest"),
            policy_identity=_optional_string(value["policy_identity"], "policy_identity"),
            risk=_optional_string(value["risk"], "risk"),
            side_effect=_optional_string(value["side_effect"], "side_effect"),
            target_digest=_optional_string(value["target_digest"], "target_digest"),
            precondition_digest=_optional_string(
                value["precondition_digest"],
                "precondition_digest",
            ),
            new_content_digest=_optional_string(
                value["new_content_digest"],
                "new_content_digest",
            ),
            egress=_optional_string(value.get("egress"), "egress"),
            operation=_optional_string(value.get("operation"), "operation"),
            request_identity=_optional_string(
                value.get("request_identity"), "request_identity"
            ),
            destination_digest=_optional_string(
                value.get("destination_digest"), "destination_digest"
            ),
            cost_class=_optional_string(value.get("cost_class"), "cost_class"),
            trust_notice_id=_optional_string(
                value.get("trust_notice_id"), "trust_notice_id"
            ),
            trust_notice_digest=_optional_string(
                value.get("trust_notice_digest"), "trust_notice_digest"
            ),
            # pre-v6 candidate 同样没有可验证的 immutable digest：恢复后
            # 丢弃并要求重新 prepare/approval，绝不为旧数据重签。
            process_authority_candidate=(
                _process_authority_candidate_from_dict(
                    value.get("process_authority_candidate"),
                    contract_current=True,
                )
                if process_contract_current
                else None
            ),
            artifact_confirmation_requirement=(
                _artifact_confirmation_requirement_from_dict(
                    value.get("artifact_confirmation_requirement")
                )
                if process_contract_current
                else None
            ),
        )
    if request_type == "recovery":
        keys = {"type", "request_id", "run_id", "tool_call_id", "binding_digest", "summary"}
        _expect_keys(value, keys, "recovery_request")
        return RecoveryRequest(
            request_id=_string(value["request_id"], "request_id"),
            run_id=_string(value["run_id"], "run_id"),
            tool_call_id=_string(value["tool_call_id"], "tool_call_id"),
            binding_digest=_string(value["binding_digest"], "binding_digest"),
            summary=_string(value["summary"], "summary"),
        )
    raise CheckpointVersionError("unknown pending request type")


def _executing_to_dict(value: ExecutingIntentRecord | None) -> dict | None:
    if value is None:
        return None
    return {
        "tool_call_id": value.tool_call_id,
        "intent_digest": value.intent_digest,
        "idempotency_key": value.idempotency_key,
        "side_effect": value.side_effect.value,
        "egress": value.egress.value,
        "execution_authority": value.execution_authority.value,
        "operation": value.operation,
        "request_identity": value.request_identity,
    }


def _executing_from_dict(
    value, *, strict_current: bool = False
) -> ExecutingIntentRecord | None:
    if value is None:
        return None
    value = _object(value, "executing_intent")
    legacy_keys = {"tool_call_id", "intent_digest", "idempotency_key"}
    pre_015_keys = {
        *legacy_keys,
        "side_effect",
        "egress",
        "operation",
        "request_identity",
    }
    current_keys = {*pre_015_keys, "execution_authority"}
    # versioned migration（F2/KTD12）：只有 pre-v4 文档（v2/v3）可把缺
    # execution_authority 的旧 executing record 完整迁移为 IN_PROCESS；v4 current
    # 缺失/未知成员 strict fail closed。
    if frozenset(value) not in {
        frozenset(legacy_keys),
        frozenset(pre_015_keys),
        frozenset(current_keys),
    }:
        _expect_keys(value, current_keys, "executing")
    if "execution_authority" not in value and strict_current:
        _expect_keys(value, current_keys, "executing")
    if "execution_authority" in value:
        execution_authority = ExecutionAuthorityClass(
            _string(value["execution_authority"], "execution_authority")
        )
    else:
        execution_authority = ExecutionAuthorityClass.IN_PROCESS
    return ExecutingIntentRecord(
        tool_call_id=_string(value["tool_call_id"], "tool_call_id"),
        intent_digest=_string(value["intent_digest"], "intent_digest"),
        idempotency_key=_string(value["idempotency_key"], "idempotency_key"),
        side_effect=(
            SideEffectClass(_string(value["side_effect"], "side_effect"))
            if "side_effect" in value
            else SideEffectClass.WRITE
        ),
        egress=(
            EgressClass(_string(value["egress"], "egress"))
            if "egress" in value
            else EgressClass.NONE
        ),
        execution_authority=execution_authority,
        operation=(
            _string(value["operation"], "operation")
            if "operation" in value
            else "legacy_effect"
        ),
        request_identity=(
            _optional_string(value["request_identity"], "request_identity")
            if "request_identity" in value
            else None
        ),
    )


def _process_authority_candidate_to_dict(value: ProcessAuthorityCandidateV1 | None) -> dict | None:
    if value is None:
        return None
    return {
        "candidate_id": value.candidate_id,
        "candidate_digest": value.candidate_digest,
        "goal_id": value.goal_id,
        "goal_revision": value.goal_revision,
        "workspace_identity_digest": value.workspace_identity_digest,
        "command_fingerprint": value.command_fingerprint,
        "readable_command": value.readable_command,
        "executable_digest": value.executable_digest,
        "argv_digest": value.argv_digest,
        "cwd_digest": value.cwd_digest,
        "resource_profile": value.resource_profile,
        "environment_policy_digest": value.environment_policy_digest,
        "execution_authority": value.execution_authority.value,
        "trust_notice_digest": value.trust_notice_digest,
        "issued_at": value.issued_at,
        "max_uses": value.max_uses,
        "expiry_minutes": value.expiry_minutes,
        "expected_artifact_path": value.expected_artifact_path,
        "expected_artifact_sha256": value.expected_artifact_sha256,
    }


def _process_authority_candidate_from_dict(
    value,
    *,
    contract_current: bool = True,
) -> ProcessAuthorityCandidateV1 | None:
    if value is None:
        return None
    value = _object(value, "process_authority_candidate")
    keys = {
        "candidate_id",
        "candidate_digest",
        "goal_id",
        "goal_revision",
        "workspace_identity_digest",
        "command_fingerprint",
        "readable_command",
        "executable_digest",
        "argv_digest",
        "cwd_digest",
        "resource_profile",
        "environment_policy_digest",
        "execution_authority",
        "trust_notice_digest",
        "issued_at",
        "max_uses",
        "expiry_minutes",
        "expected_artifact_path",
        "expected_artifact_sha256",
    }
    _expect_keys(value, keys, "process_authority_candidate")
    constructor = (
        ProcessAuthorityCandidateV1
        if contract_current
        else ProcessAuthorityCandidateV1.create
    )
    kwargs = dict(
        candidate_id=_string(value["candidate_id"], "candidate_id"),
        goal_id=_string(value["goal_id"], "goal_id"),
        goal_revision=_integer(value["goal_revision"], "goal_revision"),
        workspace_identity_digest=_string(
            value["workspace_identity_digest"], "workspace_identity_digest"
        ),
        command_fingerprint=_string(value["command_fingerprint"], "command_fingerprint"),
        readable_command=_string(value["readable_command"], "readable_command"),
        executable_digest=_string(value["executable_digest"], "executable_digest"),
        argv_digest=_string(value["argv_digest"], "argv_digest"),
        cwd_digest=_string(value["cwd_digest"], "cwd_digest"),
        resource_profile=_string(value["resource_profile"], "resource_profile"),
        environment_policy_digest=_string(
            value["environment_policy_digest"], "environment_policy_digest"
        ),
        execution_authority=ExecutionAuthorityClass(
            _string(value["execution_authority"], "execution_authority")
        ),
        trust_notice_digest=_string(value["trust_notice_digest"], "trust_notice_digest"),
        issued_at=_string(value["issued_at"], "issued_at"),
        max_uses=_integer(value["max_uses"], "max_uses"),
        expiry_minutes=_integer(value["expiry_minutes"], "expiry_minutes"),
        expected_artifact_path=_optional_string(
            value["expected_artifact_path"], "expected_artifact_path"
        ),
        expected_artifact_sha256=_optional_string(
            value["expected_artifact_sha256"], "expected_artifact_sha256"
        ),
    )
    if contract_current:
        kwargs["candidate_digest"] = _string(
            value["candidate_digest"], "candidate_digest"
        )
    return constructor(**kwargs)


def _artifact_confirmation_requirement_to_dict(
    value: ArtifactConfirmationRequirementV1 | None,
) -> dict | None:
    if value is None:
        return None
    return {
        "criterion_id": value.criterion_id,
        "artifact_path": value.artifact_path,
    }


def _artifact_confirmation_requirement_from_dict(
    value,
) -> ArtifactConfirmationRequirementV1 | None:
    if value is None:
        return None
    value = _object(value, "artifact_confirmation_requirement")
    _expect_keys(
        value,
        {"criterion_id", "artifact_path"},
        "artifact_confirmation_requirement",
    )
    return ArtifactConfirmationRequirementV1(
        criterion_id=_string(value["criterion_id"], "criterion_id"),
        artifact_path=_string(value["artifact_path"], "artifact_path"),
    )


def _process_lease_to_dict(value: ProcessAuthorityLeaseV1) -> dict:
    return {
        "lease_id": value.lease_id,
        "lease_digest": value.lease_digest,
        "candidate_digest": value.candidate_digest,
        "goal_id": value.goal_id,
        "goal_revision": value.goal_revision,
        "workspace_identity_digest": value.workspace_identity_digest,
        "command_fingerprint": value.command_fingerprint,
        "readable_command": value.readable_command,
        "executable_digest": value.executable_digest,
        "argv_digest": value.argv_digest,
        "cwd_digest": value.cwd_digest,
        "resource_profile": value.resource_profile,
        "environment_policy_digest": value.environment_policy_digest,
        "execution_authority": value.execution_authority.value,
        "approved_request_identity": value.approved_request_identity,
        "issued_at": value.issued_at,
        "expires_at": value.expires_at,
        "max_uses": value.max_uses,
        "uses_consumed": value.uses_consumed,
    }


def _process_lease_from_dict(
    value,
    *,
    contract_current: bool = True,
) -> ProcessAuthorityLeaseV1:
    value = _object(value, "process_lease")
    keys = {
        "lease_id",
        "lease_digest",
        "candidate_digest",
        "goal_id",
        "goal_revision",
        "workspace_identity_digest",
        "command_fingerprint",
        "readable_command",
        "executable_digest",
        "argv_digest",
        "cwd_digest",
        "resource_profile",
        "environment_policy_digest",
        "execution_authority",
        "approved_request_identity",
        "issued_at",
        "expires_at",
        "max_uses",
        "uses_consumed",
    }
    if contract_current:
        _expect_keys(value, keys, "process_lease")
    else:
        legacy_keys = keys - {"readable_command"}
        if set(value) not in {frozenset(keys), frozenset(legacy_keys)}:
            _expect_keys(value, legacy_keys, "process_lease")
    readable_command = value.get("readable_command")
    if readable_command is None:
        fingerprint = _string(value["command_fingerprint"], "command_fingerprint")
        profile = _string(value["resource_profile"], "resource_profile")
        readable_command = f"{fingerprint[:12]} profile={profile}"
    constructor = ProcessAuthorityLeaseV1 if contract_current else ProcessAuthorityLeaseV1.create
    kwargs = dict(
        lease_id=_string(value["lease_id"], "lease_id"),
        candidate_digest=_string(value["candidate_digest"], "candidate_digest"),
        goal_id=_string(value["goal_id"], "goal_id"),
        goal_revision=_integer(value["goal_revision"], "goal_revision"),
        workspace_identity_digest=_string(
            value["workspace_identity_digest"], "workspace_identity_digest"
        ),
        command_fingerprint=_string(value["command_fingerprint"], "command_fingerprint"),
        readable_command=_string(readable_command, "readable_command"),
        executable_digest=_string(value["executable_digest"], "executable_digest"),
        argv_digest=_string(value["argv_digest"], "argv_digest"),
        cwd_digest=_string(value["cwd_digest"], "cwd_digest"),
        resource_profile=_string(value["resource_profile"], "resource_profile"),
        environment_policy_digest=_string(
            value["environment_policy_digest"], "environment_policy_digest"
        ),
        execution_authority=ExecutionAuthorityClass(
            _string(value["execution_authority"], "execution_authority")
        ),
        approved_request_identity=_string(
            value["approved_request_identity"], "approved_request_identity"
        ),
        issued_at=_string(value["issued_at"], "issued_at"),
        expires_at=_string(value["expires_at"], "expires_at"),
        max_uses=_integer(value["max_uses"], "max_uses"),
        uses_consumed=_integer(value["uses_consumed"], "uses_consumed"),
    )
    if contract_current:
        kwargs["lease_digest"] = _string(value["lease_digest"], "lease_digest")
    return constructor(**kwargs)


def _tool_call_to_dict(value: ToolCall) -> dict:
    return {
        "tool_call_id": value.tool_call_id,
        "name": value.name,
        "arguments": value.arguments,
    }


def _tool_call_from_dict(value: dict) -> ToolCall:
    _expect_keys(value, {"tool_call_id", "name", "arguments"}, "tool_call")
    return ToolCall(
        _string(value["tool_call_id"], "tool_call_id"),
        _string(value["name"], "tool_name"),
        _object(value["arguments"], "tool_arguments"),
    )


def _approval_grant_to_dict(value: ApprovalGrant | None) -> dict | None:
    if value is None:
        return None
    return {
        "request_id": value.request_id,
        "binding_digest": value.binding_digest,
        "approval_basis_revision": value.approval_basis_revision,
    }


def _approval_grant_from_dict(value) -> ApprovalGrant | None:
    if value is None:
        return None
    value = _object(value, "approval_grant")
    legacy_keys = {"request_id", "binding_digest"}
    current_keys = {*legacy_keys, "approval_basis_revision"}
    if frozenset(value) not in {frozenset(legacy_keys), frozenset(current_keys)}:
        _expect_keys(value, current_keys, "approval_grant")
    return ApprovalGrant(
        _string(value["request_id"], "request_id"),
        _string(value["binding_digest"], "binding_digest"),
        (
            None
            if "approval_basis_revision" not in value
            or value["approval_basis_revision"] is None
            else _integer(value["approval_basis_revision"], "approval_basis_revision")
        ),
    )


def _expect_keys(value: dict, expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        unknown = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise CheckpointVersionError(
            f"{label} has unknown fields {unknown} or missing fields {missing}"
        )


def _object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _array(value, label: str) -> list:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _string(value, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    return value


def _optional_string(value, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _integer(value, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    return value


def _boolean(value, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value

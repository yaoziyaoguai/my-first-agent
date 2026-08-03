"""产品 state root 与 deterministic workspace session bootstrap。"""

from __future__ import annotations

import fcntl
import os
import re
import stat
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from agent.continuity.identity import WorkspaceIdentityV1
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import (
    ActiveRunStatus,
    ContinuationPhase,
    ConversationState,
    GoalStatus,
    LoadedSnapshot,
    SelectGoal,
)

_CONVERSATION_FILE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json$"
)
_TERMINAL_GOAL_STATUSES = {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}


class StartupDisposition(StrEnum):
    CREATED = "created"
    RESUMED = "resumed"
    SELECT_REQUIRED = "select_required"
    NEEDS_AUTHORITY = "needs_authority"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class WorkspaceSession:
    disposition: StartupDisposition
    state_root: Path
    workspace_identity: WorkspaceIdentityV1
    checkpoint_path: Path | None
    store: LocalCheckpointStore | None
    snapshot: LoadedSnapshot | None
    candidates: tuple[SessionCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class SessionCandidate:
    conversation_id: str
    checkpoint_path: Path
    state_revision: int
    next_action_seq: int
    goal_id: str | None
    goal_revision: int | None
    goal_status: GoalStatus | None
    user_outcome: str | None


def default_state_root(home: Path | None = None) -> Path:
    owner_home = Path.home() if home is None else Path(home)
    return owner_home / ".local" / "state" / "my-first-agent" / "v1"


def open_workspace_session(
    workspace: Path,
    *,
    state_root: Path | None = None,
    home: Path | None = None,
    conversation_id_factory: Callable[[], str] | None = None,
    max_candidates: int = 16,
) -> WorkspaceSession:
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    identity = WorkspaceIdentityV1.resolve(workspace)
    root = (
        default_state_root(home) if state_root is None else Path(state_root)
    ).absolute()
    workspace_path = Path(identity.canonical_path)
    if root == workspace_path or root.is_relative_to(workspace_path):
        raise ValueError("state root must remain outside the tool workspace")

    _reject_symlink_components(root, label="state root")
    _ensure_owner_directory(root, create=True, label="state root")
    workspaces_root = root / "workspaces"
    _ensure_owner_directory(workspaces_root, create=True, label="workspaces root")
    workspace_root = workspaces_root / identity.scope_digest
    _ensure_owner_directory(workspace_root, create=True, label="workspace state directory")

    with _bootstrap_lock(workspace_root):
        return _open_workspace_session_locked(
            identity=identity,
            root=root,
            workspace_root=workspace_root,
            conversation_id_factory=conversation_id_factory,
            max_candidates=max_candidates,
        )


def _open_workspace_session_locked(
    *,
    identity: WorkspaceIdentityV1,
    root: Path,
    workspace_root: Path,
    conversation_id_factory: Callable[[], str] | None,
    max_candidates: int,
) -> WorkspaceSession:
    loaded = _load_candidates(workspace_root, max_candidates=max_candidates)
    active = tuple(item for item in loaded if _is_nonterminal(item[1].state))
    if len(active) == 1:
        path, snapshot = active[0]
        candidate = _candidate(path, snapshot)
        goal = snapshot.state.goal
        if goal is not None and goal.workspace_identity_digest != identity.identity_digest:
            disposition = StartupDisposition.NEEDS_AUTHORITY
        elif _has_unknown_effect(snapshot.state):
            disposition = StartupDisposition.RECOVERY_REQUIRED
        else:
            disposition = StartupDisposition.RESUMED
        return WorkspaceSession(
            disposition=disposition,
            state_root=root,
            workspace_identity=identity,
            checkpoint_path=path,
            store=LocalCheckpointStore(path),
            snapshot=snapshot,
            candidates=(candidate,),
        )
    if len(active) > 1:
        return WorkspaceSession(
            disposition=StartupDisposition.SELECT_REQUIRED,
            state_root=root,
            workspace_identity=identity,
            checkpoint_path=None,
            store=None,
            snapshot=None,
            candidates=tuple(_candidate(path, snapshot) for path, snapshot in active),
        )

    conversation_id = (conversation_id_factory or (lambda: str(uuid4())))()
    if not _CONVERSATION_FILE.fullmatch(f"{conversation_id}.json"):
        raise ValueError("conversation_id must be a canonical UUID")
    checkpoint_path = workspace_root / f"{conversation_id}.json"
    store = LocalCheckpointStore.initialize(
        checkpoint_path,
        ConversationState.new(conversation_id),
    )
    return WorkspaceSession(
        disposition=StartupDisposition.CREATED,
        state_root=root,
        workspace_identity=identity,
        checkpoint_path=checkpoint_path,
        store=store,
        snapshot=store.load(),
    )


def select_workspace_session(
    selection: WorkspaceSession,
    action: SelectGoal,
) -> WorkspaceSession:
    if selection.disposition is not StartupDisposition.SELECT_REQUIRED:
        raise ValueError("exact goal selection requires an ambiguous startup")
    matches = tuple(
        candidate
        for candidate in selection.candidates
        if candidate.conversation_id == action.conversation_id
        and candidate.goal_id == action.goal_id
    )
    if len(matches) != 1:
        raise ValueError("SelectGoal must identify one exact startup candidate")
    candidate = matches[0]
    store = LocalCheckpointStore(candidate.checkpoint_path)
    snapshot = store.load()
    goal = snapshot.state.goal
    if (
        goal is None
        or snapshot.state.revision != action.expected_revision
        or snapshot.state.next_action_seq != action.action_seq
        or goal.goal_id != action.goal_id
    ):
        raise ValueError("SelectGoal does not bind the exact candidate revision")
    if goal.workspace_identity_digest != selection.workspace_identity.identity_digest:
        disposition = StartupDisposition.NEEDS_AUTHORITY
    elif _has_unknown_effect(snapshot.state):
        disposition = StartupDisposition.RECOVERY_REQUIRED
    else:
        disposition = StartupDisposition.RESUMED
    return WorkspaceSession(
        disposition=disposition,
        state_root=selection.state_root,
        workspace_identity=selection.workspace_identity,
        checkpoint_path=candidate.checkpoint_path,
        store=store,
        snapshot=snapshot,
        candidates=(candidate,),
    )


def _load_candidates(
    workspace_root: Path,
    *,
    max_candidates: int,
) -> tuple[tuple[Path, LoadedSnapshot], ...]:
    checkpoint_paths: list[Path] = []
    lock_names: set[str] = set()
    with os.scandir(workspace_root) as entries:
        for index, entry in enumerate(entries, start=1):
            if index > max_candidates * 2 + 1:
                raise ValueError("workspace state enumeration exceeds its bound")
            if entry.name == ".bootstrap.lock":
                lock_names.add(entry.name)
                continue
            if entry.name.startswith(".") and entry.name.endswith(".json.lock"):
                lock_names.add(entry.name)
                continue
            if not _CONVERSATION_FILE.fullmatch(entry.name) or not entry.is_file(
                follow_symlinks=False
            ):
                raise ValueError("workspace state directory contains an unknown entry")
            checkpoint_paths.append(workspace_root / entry.name)
            if len(checkpoint_paths) > max_candidates:
                raise ValueError("workspace state candidate count exceeds its bound")
    checkpoint_names = {path.name for path in checkpoint_paths}
    expected_locks = {f".{name}.lock" for name in checkpoint_names}
    unknown_locks = lock_names - expected_locks - {".bootstrap.lock"}
    if unknown_locks:
        raise ValueError("workspace state directory contains an orphan lock")

    loaded: list[tuple[Path, LoadedSnapshot]] = []
    for path in sorted(checkpoint_paths):
        snapshot = LocalCheckpointStore(path).load()
        if path.stem != snapshot.state.conversation_id:
            raise ValueError("checkpoint filename does not match conversation identity")
        loaded.append((path, snapshot))
    return tuple(loaded)


def _is_nonterminal(state: ConversationState) -> bool:
    return state.goal is None or state.goal.status not in _TERMINAL_GOAL_STATUSES


def _has_unknown_effect(state: ConversationState) -> bool:
    active = state.active_run
    return active is not None and (
        active.phase is ContinuationPhase.EXECUTING
        or active.status is ActiveRunStatus.AWAITING_RECOVERY
    )


def _candidate(path: Path, snapshot: LoadedSnapshot) -> SessionCandidate:
    goal = snapshot.state.goal
    return SessionCandidate(
        conversation_id=snapshot.state.conversation_id,
        checkpoint_path=path,
        state_revision=snapshot.state.revision,
        next_action_seq=snapshot.state.next_action_seq,
        goal_id=goal.goal_id if goal is not None else None,
        goal_revision=goal.revision if goal is not None else None,
        goal_status=goal.status if goal is not None else None,
        user_outcome=goal.user_outcome if goal is not None else None,
    )


def _ensure_owner_directory(path: Path, *, create: bool, label: str) -> None:
    if create:
        with suppress(FileExistsError):
            path.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing") from error
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError(f"{label} must be a real directory")
    if info.st_uid != os.getuid():
        raise ValueError(f"{label} owner mismatch")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError(f"{label} mode must be 0700")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(fd)


@contextmanager
def _bootstrap_lock(workspace_root: Path):
    directory_fd = os.open(
        workspace_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    lock_fd: int | None = None
    try:
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        lock_fd = os.open(workspace_root / ".bootstrap.lock", flags, 0o600)
        info = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValueError("workspace bootstrap lock is unsafe")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(directory_fd)


def _reject_symlink_components(path: Path, *, label: str) -> None:
    current = path
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(f"{label} must use a real directory path")
        if current.parent == current:
            return
        current = current.parent

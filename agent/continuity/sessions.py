"""产品 state root 与 deterministic workspace session bootstrap。"""

from __future__ import annotations

import fcntl
import os
import re
import stat
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from agent.continuity.archive import LocalConversationArchive
from agent.continuity.identity import WorkspaceIdentityV1
from agent.runtime.checkpoint import CheckpointConflictError, LocalCheckpointStore
from agent.runtime.contracts import (
    TERMINAL_GOAL_STATUSES,
    ActiveRunStatus,
    ArchivedConversation,
    ContinuationPhase,
    ConversationState,
    ConversationWorkspaceBindingV1,
    GoalStatus,
    LoadedSnapshot,
    SelectGoal,
)

_CONVERSATION_FILE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json$"
)
DEFAULT_ACTIVE_CANDIDATE_LIMIT = 16
WORKSPACE_HISTORY_CAPACITY = 256


class StartupDisposition(StrEnum):
    CREATED = "created"
    RESUMED = "resumed"
    SELECT_REQUIRED = "select_required"
    NEEDS_AUTHORITY = "needs_authority"
    RECOVERY_REQUIRED = "recovery_required"
    HISTORY_CAPACITY_EXCEEDED = "history_capacity_exceeded"


@dataclass(frozen=True, slots=True)
class WorkspaceSession:
    disposition: StartupDisposition
    state_root: Path
    workspace_identity: WorkspaceIdentityV1
    checkpoint_path: Path | None
    store: LocalCheckpointStore | None
    snapshot: LoadedSnapshot | None
    candidates: tuple[SessionCandidate, ...] = ()
    candidate_inventory: tuple[SessionCandidate, ...] = ()
    candidate_page: int = 0
    candidate_page_size: int = DEFAULT_ACTIVE_CANDIDATE_LIMIT
    workspace_binding: ConversationWorkspaceBindingV1 | None = None
    legacy_unbound_count: int = 0
    total_checkpoint_count: int = 0
    total_active_count: int = 0
    history_incomplete: bool = False


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


@dataclass(frozen=True, slots=True)
class WorkspaceInspection:
    """只读发现结果；不包含未绑定或错绑 conversation 的内容。"""

    state_root: Path
    workspace_identity: WorkspaceIdentityV1
    snapshots: tuple[LoadedSnapshot, ...]
    legacy_unbound_count: int = 0


@dataclass(frozen=True, slots=True)
class SessionArchivePreview:
    """用户归档确认面：只暴露定位、状态和 checkpoint 版本。

    goal_status/user_outcome 为 None 表示 r8 空闲 chat 会话（无 Goal）。
    """

    conversation_id: str
    goal_status: GoalStatus | None
    user_outcome: str | None
    checkpoint_digest: str
    state_revision: int


def inspect_workspace_sessions(
    workspace: Path,
    *,
    state_root: Path | None = None,
    home: Path | None = None,
    max_history_checkpoints: int = WORKSPACE_HISTORY_CAPACITY,
) -> WorkspaceInspection:
    """在零创建、零 checkpoint mutation 下读取当前 workspace 的保存状态。"""

    if max_history_checkpoints < 1:
        raise ValueError("max_history_checkpoints must be positive")
    identity = WorkspaceIdentityV1.resolve(workspace)
    root = (
        default_state_root(home) if state_root is None else Path(state_root)
    ).absolute()
    workspace_path = Path(identity.canonical_path)
    if root == workspace_path or root.is_relative_to(workspace_path):
        raise ValueError("state root must remain outside the tool workspace")
    _reject_symlink_components(root, label="state root")
    if not root.exists():
        return WorkspaceInspection(root, identity, ())
    _ensure_owner_directory(root, create=False, label="state root")
    workspaces_root = root / "workspaces"
    if not workspaces_root.exists():
        return WorkspaceInspection(root, identity, ())
    _reject_symlink_components(workspaces_root, label="workspaces root")
    _ensure_owner_directory(workspaces_root, create=False, label="workspaces root")
    workspace_root = workspaces_root / identity.scope_digest
    if not workspace_root.exists():
        return WorkspaceInspection(root, identity, ())
    loaded = load_workspace_checkpoints(
        workspace_root,
        max_history_checkpoints=max_history_checkpoints,
    )
    safe: list[LoadedSnapshot] = []
    legacy_unbound_count = 0
    for _, snapshot in loaded:
        state = snapshot.state
        binding = state.workspace_binding
        if binding is None and state.goal is None:
            legacy_unbound_count += 1
            continue
        if binding is not None:
            matches = (
                binding.workspace_scope_digest == identity.scope_digest
                and binding.workspace_identity_digest == identity.identity_digest
            )
        else:
            matches = state.goal.workspace_identity_digest == identity.identity_digest
        if not matches:
            raise ValueError("workspace identity confirmation is required")
        safe.append(snapshot)
    return WorkspaceInspection(root, identity, tuple(safe), legacy_unbound_count)


def preview_workspace_archive(
    workspace: Path,
    *,
    conversation_id: str,
    state_root: Path | None = None,
    home: Path | None = None,
    max_history_checkpoints: int = WORKSPACE_HISTORY_CAPACITY,
) -> SessionArchivePreview:
    """只读预览一个可归档的已结束会话，不创建任何状态。"""

    inspection = inspect_workspace_sessions(
        workspace,
        state_root=state_root,
        home=home,
        max_history_checkpoints=max_history_checkpoints,
    )
    snapshot = _exact_snapshot(inspection.snapshots, conversation_id)
    _require_user_archive_eligible(snapshot.state)
    goal = snapshot.state.goal
    return SessionArchivePreview(
        conversation_id=conversation_id,
        goal_status=goal.status if goal is not None else None,
        user_outcome=goal.user_outcome if goal is not None else None,
        checkpoint_digest=snapshot.token,
        state_revision=snapshot.state.revision,
    )


def archive_workspace_session(
    workspace: Path,
    *,
    conversation_id: str,
    expected_checkpoint_digest: str,
    state_root: Path | None = None,
    home: Path | None = None,
    max_history_checkpoints: int = WORKSPACE_HISTORY_CAPACITY,
) -> ArchivedConversation:
    """先写入并重读不可变归档，再释放 exact 终态 checkpoint。"""

    identity, root, workspace_root = _existing_workspace_state_paths(
        workspace,
        state_root=state_root,
        home=home,
    )
    with _bootstrap_lock(workspace_root):
        loaded = load_workspace_checkpoints(
            workspace_root,
            max_history_checkpoints=max_history_checkpoints,
        )
        path, snapshot = _exact_loaded(loaded, conversation_id)
        _require_user_archive_eligible(snapshot.state)
        if snapshot.token != expected_checkpoint_digest:
            raise ValueError("conversation changed after preview")
        store = LocalCheckpointStore(path)
        lease = store.try_acquire(conversation_id)
        if lease is None:
            raise ValueError("conversation is currently in use")
        try:
            current = store.load()
            if current.token != expected_checkpoint_digest:
                raise ValueError("conversation changed after preview")
            _require_user_archive_eligible(current.state)
            archive = LocalConversationArchive(root)
            record = archive.archive(
                current.state,
                source_checkpoint_digest=current.token,
                workspace_scope_digest=identity.scope_digest,
            )
            restored = archive.load_archived(record)
            if restored != current:
                raise ValueError("archived conversation failed exact read-back")
            store.retire_archived_snapshot(current, record)
            return record
        finally:
            lease.release()


def restore_workspace_session(
    workspace: Path,
    *,
    conversation_id: str,
    source_checkpoint_digest: str,
    state_root: Path | None = None,
    home: Path | None = None,
    max_history_checkpoints: int = WORKSPACE_HISTORY_CAPACITY,
) -> WorkspaceSession:
    """从 exact immutable archive 恢复原 conversation，归档本身仍保留。"""

    identity, root, workspace_root = _existing_workspace_state_paths(
        workspace,
        state_root=state_root,
        home=home,
    )
    with _bootstrap_lock(workspace_root):
        # R3c：restore 是写路径——清扫孤儿锁与容量判定同锁内完成。
        loaded = _load_candidates(
            workspace_root,
            max_history_checkpoints=max_history_checkpoints,
            sweep_retired_locks=True,
        )
        if len(loaded) >= max_history_checkpoints:
            raise ValueError("workspace history capacity is full")
        if any(snapshot.state.conversation_id == conversation_id for _, snapshot in loaded):
            raise ValueError("conversation already exists in active history")
        archive = LocalConversationArchive(root)
        archived = archive.load_archived_by_identity(
            conversation_id=conversation_id,
            workspace_scope_digest=identity.scope_digest,
            source_checkpoint_digest=source_checkpoint_digest,
        )
        _require_user_archive_eligible(archived.state)
        binding = archived.state.workspace_binding
        if (
            binding is None
            or binding.workspace_identity_digest != identity.identity_digest
        ):
            raise ValueError("archived conversation workspace identity mismatch")
        checkpoint_path = workspace_root / f"{conversation_id}.json"
        try:
            store = LocalCheckpointStore.initialize(checkpoint_path, archived.state)
        except CheckpointConflictError as error:
            raise ValueError("conversation restore target already exists") from error
        snapshot = store.load()
        return WorkspaceSession(
            disposition=StartupDisposition.RESUMED,
            state_root=root,
            workspace_identity=identity,
            checkpoint_path=checkpoint_path,
            store=store,
            snapshot=snapshot,
            candidates=(_candidate(checkpoint_path, snapshot),),
            workspace_binding=binding,
            total_checkpoint_count=len(loaded) + 1,
            total_active_count=0,
        )


def preview_workspace_restore(
    workspace: Path,
    *,
    conversation_id: str,
    source_checkpoint_digest: str,
    state_root: Path | None = None,
    home: Path | None = None,
) -> SessionArchivePreview:
    """只读验证 exact archive 及 workspace binding，供恢复前确认。"""

    identity, root, workspace_root = _existing_workspace_state_paths(
        workspace,
        state_root=state_root,
        home=home,
    )
    loaded = load_workspace_checkpoints(workspace_root)
    if any(snapshot.state.conversation_id == conversation_id for _, snapshot in loaded):
        raise ValueError("conversation already exists in active history")
    snapshot = LocalConversationArchive(root).load_archived_by_identity(
        conversation_id=conversation_id,
        workspace_scope_digest=identity.scope_digest,
        source_checkpoint_digest=source_checkpoint_digest,
    )
    _require_user_archive_eligible(snapshot.state)
    binding = snapshot.state.workspace_binding
    if binding is None or binding.workspace_identity_digest != identity.identity_digest:
        raise ValueError("archived conversation workspace identity mismatch")
    goal = snapshot.state.goal
    return SessionArchivePreview(
        conversation_id=conversation_id,
        goal_status=goal.status if goal is not None else None,
        user_outcome=goal.user_outcome if goal is not None else None,
        checkpoint_digest=snapshot.token,
        state_revision=snapshot.state.revision,
    )


def default_state_root(home: Path | None = None) -> Path:
    owner_home = Path.home() if home is None else Path(home)
    return owner_home / ".local" / "state" / "my-first-agent" / "v1"


def open_workspace_session(
    workspace: Path,
    *,
    state_root: Path | None = None,
    home: Path | None = None,
    conversation_id_factory: Callable[[], str] | None = None,
    max_candidates: int = DEFAULT_ACTIVE_CANDIDATE_LIMIT,
    max_history_checkpoints: int = WORKSPACE_HISTORY_CAPACITY,
    bound_at_factory: Callable[[], str] | None = None,
    force_new: bool = False,
) -> WorkspaceSession:
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    if max_history_checkpoints < 1 or max_candidates > max_history_checkpoints:
        raise ValueError(
            "max_history_checkpoints must be positive and cover max_candidates"
        )
    if not isinstance(force_new, bool):
        raise ValueError("force_new must be a bool")
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
            max_history_checkpoints=max_history_checkpoints,
            bound_at_factory=bound_at_factory,
            force_new=force_new,
        )


def _open_workspace_session_locked(
    *,
    identity: WorkspaceIdentityV1,
    root: Path,
    workspace_root: Path,
    conversation_id_factory: Callable[[], str] | None,
    max_candidates: int,
    max_history_checkpoints: int,
    bound_at_factory: Callable[[], str] | None,
    force_new: bool = False,
) -> WorkspaceSession:
    loaded = _load_candidates(
        workspace_root,
        max_history_checkpoints=max_history_checkpoints,
        sweep_retired_locks=True,
    )
    desired_binding = ConversationWorkspaceBindingV1.create(
        workspace_scope_digest=identity.scope_digest,
        workspace_identity_digest=identity.identity_digest,
        bound_at=(bound_at_factory or _canonical_now)(),
    )
    legacy_unbound = tuple(
        item
        for item in loaded
        if item[1].state.workspace_binding is None and item[1].state.goal is None
    )
    active = tuple(
        item
        for item in loaded
        if item not in legacy_unbound and _is_nonterminal(item[1].state)
    )
    # force_new(/new 显式新任务):跳过 resume/select 投影,直接进入新
    # conversation 创建;容量保护仍然生效。无 Goal 的闲聊会话在 active 语义
    # 下会被 RESUMED,只有显式 force_new 才能可靠开始新任务。
    if not force_new and len(active) == 1:
        path, snapshot = active[0]
        candidate = _candidate(path, snapshot)
        state_binding = snapshot.state.workspace_binding
        goal = snapshot.state.goal
        if state_binding is not None and (
            state_binding.workspace_scope_digest != identity.scope_digest
            or state_binding.workspace_identity_digest != identity.identity_digest
        ) or (
            state_binding is None
            and goal is not None
            and goal.workspace_identity_digest != identity.identity_digest
        ):
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
            workspace_binding=(state_binding or desired_binding),
            legacy_unbound_count=len(legacy_unbound),
            total_checkpoint_count=len(loaded),
            total_active_count=1,
        )
    if not force_new and len(active) > 1:
        inventory = tuple(_candidate(path, snapshot) for path, snapshot in active)
        visible = inventory[:max_candidates]
        return WorkspaceSession(
            disposition=StartupDisposition.SELECT_REQUIRED,
            state_root=root,
            workspace_identity=identity,
            checkpoint_path=None,
            store=None,
            snapshot=None,
            candidates=visible,
            candidate_inventory=inventory,
            candidate_page_size=max_candidates,
            workspace_binding=desired_binding,
            legacy_unbound_count=len(legacy_unbound),
            total_checkpoint_count=len(loaded),
            total_active_count=len(active),
            history_incomplete=len(active) > len(visible),
        )

    if len(loaded) >= max_history_checkpoints:
        return WorkspaceSession(
            disposition=StartupDisposition.HISTORY_CAPACITY_EXCEEDED,
            state_root=root,
            workspace_identity=identity,
            checkpoint_path=None,
            store=None,
            snapshot=None,
            workspace_binding=desired_binding,
            legacy_unbound_count=len(legacy_unbound),
            total_checkpoint_count=len(loaded),
        )

    conversation_id = (conversation_id_factory or (lambda: str(uuid4())))()
    if not _CONVERSATION_FILE.fullmatch(f"{conversation_id}.json"):
        raise ValueError("conversation_id must be a canonical UUID")
    checkpoint_path = workspace_root / f"{conversation_id}.json"
    store = LocalCheckpointStore.initialize(
        checkpoint_path,
        ConversationState.new(
            conversation_id,
            workspace_binding=desired_binding,
        ),
    )
    return WorkspaceSession(
        disposition=StartupDisposition.CREATED,
        state_root=root,
        workspace_identity=identity,
        checkpoint_path=checkpoint_path,
        store=store,
        snapshot=store.load(),
        workspace_binding=desired_binding,
        legacy_unbound_count=len(legacy_unbound),
        total_checkpoint_count=len(loaded) + 1,
        total_active_count=1,
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
    if (
        candidate.goal_id is None
        or candidate.state_revision != action.expected_revision
        or candidate.next_action_seq != action.action_seq
    ):
        raise ValueError("SelectGoal does not bind the exact candidate revision")
    return _select_workspace_candidate(selection, candidate)


def project_workspace_session_page(
    selection: WorkspaceSession,
    page: int,
) -> WorkspaceSession:
    """从启动时冻结的有界 inventory 投影一页；不重新扫描或修改 checkpoint。"""

    if selection.disposition is not StartupDisposition.SELECT_REQUIRED:
        raise ValueError("conversation paging requires an ambiguous startup")
    if not isinstance(page, int) or isinstance(page, bool) or page < 0:
        raise ValueError("conversation page is not available")
    inventory = selection.candidate_inventory or selection.candidates
    page_size = selection.candidate_page_size
    start = page * page_size
    if start >= len(inventory):
        raise ValueError("conversation page is not available")
    visible = inventory[start : start + page_size]
    return replace(
        selection,
        candidates=visible,
        candidate_page=page,
        history_incomplete=len(inventory) > len(visible),
    )


def select_workspace_candidate(
    selection: WorkspaceSession,
    candidate: SessionCandidate,
) -> WorkspaceSession:
    """选择 startup 已展示的精确 conversation，不铸造 Runtime action。"""

    if selection.disposition is not StartupDisposition.SELECT_REQUIRED:
        raise ValueError("exact conversation selection requires an ambiguous startup")
    matches = tuple(item for item in selection.candidates if item == candidate)
    if len(matches) != 1:
        raise ValueError("candidate must identify one exact displayed conversation")
    return _select_workspace_candidate(selection, matches[0])


def _select_workspace_candidate(
    selection: WorkspaceSession,
    candidate: SessionCandidate,
) -> WorkspaceSession:
    store = LocalCheckpointStore(candidate.checkpoint_path)
    snapshot = store.load()
    goal = snapshot.state.goal
    if (
        snapshot.state.conversation_id != candidate.conversation_id
        or snapshot.state.revision != candidate.state_revision
        or snapshot.state.next_action_seq != candidate.next_action_seq
        or not _is_nonterminal(snapshot.state)
        or (goal.goal_id if goal is not None else None) != candidate.goal_id
        or (goal.revision if goal is not None else None) != candidate.goal_revision
        or (goal.status if goal is not None else None) != candidate.goal_status
        or (goal.user_outcome if goal is not None else None) != candidate.user_outcome
    ):
        raise ValueError("conversation selection does not bind the displayed candidate")
    binding = snapshot.state.workspace_binding
    if (
        (binding is None and goal is None)
        or (
            binding is not None
            and (
                binding.workspace_scope_digest
                != selection.workspace_identity.scope_digest
                or binding.workspace_identity_digest
                != selection.workspace_identity.identity_digest
            )
        )
        or (
            binding is None
            and goal is not None
            and goal.workspace_identity_digest
            != selection.workspace_identity.identity_digest
        )
    ):
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
        workspace_binding=(snapshot.state.workspace_binding or selection.workspace_binding),
        legacy_unbound_count=selection.legacy_unbound_count,
        total_checkpoint_count=selection.total_checkpoint_count,
        total_active_count=selection.total_active_count,
        history_incomplete=selection.history_incomplete,
    )


def _canonical_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


# F4（2026-10-03）：锁残留与 checkpoint 容量分离。live checkpoint 锁各一个；
# 已退休会话的孤儿锁由有界清扫移除，异常残留超过显式上界即 fail closed。
_MAX_LOCK_RESIDUE = 32


def _sweep_retired_locks(root: Path, orphan_names: frozenset[str]) -> None:
    """有界清扫已退休会话的孤儿锁（retire_archived_snapshot 保留的 .json.lock）。

    只在取得 flock 后重验 pathname↔fd 的 inode/设备一致才 unlink；忙碌锁
    （其他进程正持有/等待恢复）或已被替换的 pathname 跳过，不清除。等待旧
    inode 的进程配合 ``LocalCheckpointStore.try_acquire`` 的 post-flock inode
    重验只能 fail closed 重试，无法凭旧 fd 取得该 pathname 的互斥修改权。
    """

    if not orphan_names:
        return
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in sorted(orphan_names)[:_MAX_LOCK_RESIDUE]:
            try:
                fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory_fd)
            except OSError:
                continue
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o600
                ):
                    continue
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                try:
                    path_info = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                except FileNotFoundError:
                    continue
                fd_info = os.fstat(fd)
                if (path_info.st_dev, path_info.st_ino) != (
                    fd_info.st_dev,
                    fd_info.st_ino,
                ):
                    continue
                os.unlink(name, dir_fd=directory_fd)
                os.fsync(directory_fd)
            finally:
                os.close(fd)
    finally:
        os.close(directory_fd)


def _load_candidates(
    workspace_root: Path,
    *,
    max_history_checkpoints: int,
    sweep_retired_locks: bool = False,
) -> tuple[tuple[Path, LoadedSnapshot], ...]:
    checkpoint_paths: list[Path] = []
    lock_names: set[str] = set()
    with os.scandir(workspace_root) as entries:
        for entry in entries:
            name = entry.name
            if name == ".bootstrap.lock":
                continue
            if name.startswith(".") and name.endswith(".json.lock"):
                info = entry.stat(follow_symlinks=False)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o600
                ):
                    raise ValueError("workspace state directory contains an unsafe lock")
                lock_names.add(name)
                continue
            if not _CONVERSATION_FILE.fullmatch(name) or not entry.is_file(
                follow_symlinks=False
            ):
                raise ValueError("workspace state directory contains an unknown entry")
            checkpoint_paths.append(workspace_root / entry.name)
            if len(checkpoint_paths) > max_history_checkpoints:
                raise ValueError("workspace history capacity exceeds its safety bound")
    if len(lock_names) > max_history_checkpoints + _MAX_LOCK_RESIDUE:
        raise ValueError("workspace state lock accumulation exceeds its safety bound")
    checkpoint_names = {path.name for path in checkpoint_paths}
    expected_locks = {f".{name}.lock" for name in checkpoint_names}
    orphan_locks = lock_names - expected_locks - {".bootstrap.lock"}
    if any(
        not _CONVERSATION_FILE.fullmatch(name[1 : -len(".lock")])
        for name in orphan_locks
    ):
        raise ValueError("workspace state directory contains an invalid lock")
    if sweep_retired_locks:
        # R3c（2026-10-03 follow-up）：清扫是 mutation，只属于写路径（startup/
        # archive/restore）；只读加载（load_workspace_checkpoints/inspect）不清扫。
        _sweep_retired_locks(workspace_root, frozenset(orphan_locks))

    loaded: list[tuple[Path, LoadedSnapshot]] = []
    for path in sorted(checkpoint_paths):
        snapshot = LocalCheckpointStore(path).load()
        if path.stem != snapshot.state.conversation_id:
            raise ValueError("checkpoint filename does not match conversation identity")
        loaded.append((path, snapshot))
    return tuple(loaded)


def load_workspace_checkpoints(
    workspace_root: Path,
    *,
    max_history_checkpoints: int = WORKSPACE_HISTORY_CAPACITY,
) -> tuple[tuple[Path, LoadedSnapshot], ...]:
    """只读加载一个已经由 startup 确定的 workspace state directory。"""
    if max_history_checkpoints < 1:
        raise ValueError("max_history_checkpoints must be positive")
    root = Path(workspace_root).absolute()
    _reject_symlink_components(root, label="workspace state directory")
    _ensure_owner_directory(root, create=False, label="workspace state directory")
    return _load_candidates(
        root,
        max_history_checkpoints=max_history_checkpoints,
    )


def _is_nonterminal(state: ConversationState) -> bool:
    return state.goal is None or state.goal.status not in TERMINAL_GOAL_STATUSES


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


def _exact_snapshot(
    snapshots: tuple[LoadedSnapshot, ...],
    conversation_id: str,
) -> LoadedSnapshot:
    matches = tuple(
        item for item in snapshots if item.state.conversation_id == conversation_id
    )
    if len(matches) != 1:
        raise ValueError("conversation is not available in this workspace")
    return matches[0]


def _exact_loaded(
    loaded: tuple[tuple[Path, LoadedSnapshot], ...],
    conversation_id: str,
) -> tuple[Path, LoadedSnapshot]:
    matches = tuple(
        item for item in loaded if item[1].state.conversation_id == conversation_id
    )
    if len(matches) != 1:
        raise ValueError("conversation is not available in this workspace")
    return matches[0]


def _require_user_archive_eligible(state: ConversationState) -> None:
    goal = state.goal
    # r8（2026-10-24 裁决 A）：无 Goal 的空闲 chat 也是可归档的已结束会话
    # ——归档可逆（restore），永久 active 只造成容量墙与选择器摩擦。
    # 有 Goal 的会话仍须终态；任何未收口工作的会话一律不可归档。
    if goal is not None and goal.status not in TERMINAL_GOAL_STATUSES:
        raise ValueError("only a terminal conversation can be archived")
    if (
        state.active_run is not None
        or state.browser_takeover_pending is not None
        or state.background_occurrence_binding is not None
        or state.goal_authorizations
        or state.process_leases
        or state.sandbox_leases
        or state.browser_leases
    ):
        raise ValueError("conversation still owns active or unknown work")


def _existing_workspace_state_paths(
    workspace: Path,
    *,
    state_root: Path | None,
    home: Path | None,
) -> tuple[WorkspaceIdentityV1, Path, Path]:
    identity = WorkspaceIdentityV1.resolve(workspace)
    root = (
        default_state_root(home) if state_root is None else Path(state_root)
    ).absolute()
    workspace_path = Path(identity.canonical_path)
    if root == workspace_path or root.is_relative_to(workspace_path):
        raise ValueError("state root must remain outside the tool workspace")
    _reject_symlink_components(root, label="state root")
    _ensure_owner_directory(root, create=False, label="state root")
    workspaces_root = root / "workspaces"
    _reject_symlink_components(workspaces_root, label="workspaces root")
    _ensure_owner_directory(workspaces_root, create=False, label="workspaces root")
    workspace_root = workspaces_root / identity.scope_digest
    _reject_symlink_components(workspace_root, label="workspace state directory")
    _ensure_owner_directory(
        workspace_root,
        create=False,
        label="workspace state directory",
    )
    return identity, root, workspace_root


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

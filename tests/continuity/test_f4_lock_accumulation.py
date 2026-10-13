"""F4（2026-10-02 bounded-reliability）：归档锁残留不得耗尽 workspace 容量。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.continuity.sessions import (
    archive_workspace_session,
    preview_workspace_archive,
    restore_workspace_session,
)
from tests.continuity.test_session_retirement import _terminal_session

IDS = [f"00000000-0000-4000-8000-{index:012d}" for index in range(1, 30)]


def test_f4_capacity_two_supports_at_least_12_archive_rounds(tmp_path: Path) -> None:
    """A18：容量 2 下 ≥12 次 distinct terminal create/archive 仍可继续；
    早期 archive 可恢复且 digest 保持。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    archived: list[tuple[str, object]] = []

    first, first_snapshot = _terminal_session(workspace, state_root, IDS[0])
    _terminal_session(workspace, state_root, IDS[1])
    first_archived = (IDS[0], first_snapshot)
    archived.append(first_archived)

    for index in range(12):
        oldest = archived[0]
        preview = preview_workspace_archive(
            workspace,
            conversation_id=oldest[0],
            state_root=state_root,
            max_history_checkpoints=2,
        )
        assert preview.checkpoint_digest == oldest[1].token
        record = archive_workspace_session(
            workspace,
            conversation_id=oldest[0],
            expected_checkpoint_digest=preview.checkpoint_digest,
            state_root=state_root,
            max_history_checkpoints=2,
        )
        assert record.source_checkpoint_digest == oldest[1].token
        archived.pop(0)
        # 锁残留不得让有空余容量的工作区不可用：每轮都能继续创建 terminal 会话。
        _opened_k, snapshot_k = _terminal_session(workspace, state_root, IDS[index + 2])
        archived.append((IDS[index + 2], snapshot_k))

    # 容量已满（IDS[1] 与最后一个会话）：先归档一个活跃 terminal 会话腾位。
    second_preview = preview_workspace_archive(
        workspace,
        conversation_id=IDS[1],
        state_root=state_root,
        max_history_checkpoints=2,
    )
    archive_workspace_session(
        workspace,
        conversation_id=IDS[1],
        expected_checkpoint_digest=second_preview.checkpoint_digest,
        state_root=state_root,
        max_history_checkpoints=2,
    )
    # 早期 archive 仍可恢复：digest 与 state 保持。
    restored = restore_workspace_session(
        workspace,
        conversation_id=first_archived[0],
        source_checkpoint_digest=first_archived[1].token,
        state_root=state_root,
        max_history_checkpoints=2,
    )
    assert restored.snapshot is not None
    assert restored.snapshot.state == first_archived[1].state


def test_f4_unsafe_lock_entries_still_fail_closed(tmp_path: Path) -> None:
    """A19：symlink 锁 / 错误 mode 锁仍 fail closed；新布局不静默迁移。"""

    import os

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    first, first_snapshot = _terminal_session(workspace, state_root, IDS[0])
    from agent.continuity.sessions import _existing_workspace_state_paths

    _identity, _root, root = _existing_workspace_state_paths(
        workspace, state_root=state_root, home=None
    )
    lock_name = f".{IDS[0]}.json.lock"
    # try_acquire 已创建真实锁；先移除以放置异常形态。
    real_lock = root / lock_name
    real_lock.unlink()
    # (a) symlink 锁 → 拒绝
    target = root / f"{IDS[0]}.json"
    link = root / lock_name
    os.symlink(target, link)
    from agent.continuity.sessions import load_workspace_checkpoints

    with pytest.raises(ValueError, match="unsafe lock|unknown entry"):
        load_workspace_checkpoints(root, max_history_checkpoints=2)
    link.unlink()
    # (b) 错误 mode 锁 → 拒绝
    real_lock.touch(mode=0o600)
    os.chmod(real_lock, 0o644)
    with pytest.raises(ValueError, match="unsafe lock"):
        load_workspace_checkpoints(root, max_history_checkpoints=2)




def test_f4_acquirer_paused_before_flock_rejects_swapped_lock(tmp_path: Path) -> None:
    """B14/R3c：实际 try_acquire 在 open→flock 边界暂停、锁被置换后继续——
    post-flock pathname↔fd inode 重验必须拒绝旧 fd（返回 None）。

    用模块级 flock shim 做确定性暂停（非时序猜测）；mutation check 证明移除
    inode 重验后本测试会失败。
    """

    from types import SimpleNamespace

    import agent.runtime.checkpoint as checkpoint_module
    from agent.continuity.sessions import _existing_workspace_state_paths
    from agent.runtime.checkpoint import LocalCheckpointStore

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    _terminal_session(workspace, state_root, IDS[0])
    _identity, _root, workspace_root = _existing_workspace_state_paths(
        workspace, state_root=state_root, home=None
    )
    conversation_id = IDS[0]
    store = LocalCheckpointStore(
        workspace_root / f"{conversation_id}.json"
    )
    lock_path = workspace_root / f".{conversation_id}.json.lock"

    checkpoint_module_os_original = checkpoint_module.os
    real_flock = checkpoint_module.fcntl.flock
    real_fcntl = checkpoint_module.fcntl
    swapped = {"done": False, "skip_verify": False}

    def choreographed_flock(fd, flags):
        if not swapped["done"]:
            # 在 open 之后、flock 之前：清扫等价置换（unlink + 原位重建）。
            import os as os_module

            os_module.unlink(lock_path)
            replacement_fd = os_module.open(
                lock_path.name,
                os_module.O_RDWR | os_module.O_CREAT | os_module.O_NOFOLLOW,
                0o600,
                dir_fd=os_module.open(
                    lock_path.parent, os_module.O_RDONLY | os_module.O_DIRECTORY
                ),
            )
            os_module.close(replacement_fd)
            swapped["done"] = True
        return real_flock(fd, flags)

    def run_acquire() -> object:
        fcntl_shim = SimpleNamespace(**vars(real_fcntl))
        fcntl_shim.flock = choreographed_flock
        checkpoint_module.fcntl = fcntl_shim
        try:
            return store.try_acquire(conversation_id)
        finally:
            checkpoint_module.fcntl = real_fcntl

    # 真实重验生效：置换后旧 fd 的租约必须被拒绝。
    assert run_acquire() is None

    # Mutation check：模拟"移除 inode 重验"（stat 在重验处返回旧 fd 身份）时，
    # 同样的置换会让租约被错误签发——本测试据此对重验的存在性敏感。
    real_stat = checkpoint_module.os.stat
    stale_identity = {}
    original_open = checkpoint_module.os.open

    def spying_open(path, flags, *args, **kwargs):
        fd = original_open(path, flags, *args, **kwargs)
        try:
            info = checkpoint_module.os.fstat(fd)
            stale_identity.setdefault(
                "lock", (info.st_dev, info.st_ino)
            ) if path == f".{conversation_id}.json.lock" else None
        except OSError:
            pass
        return fd

    def verifying_stat_removed(path, *args, **kwargs):
        # 重验调用 stat(pathname)：伪造为"pathname 仍是旧 fd 的 inode"。
        info = real_stat(path, *args, **kwargs)
        if str(path).endswith(f".{conversation_id}.json.lock"):
            return SimpleNamespace(
                st_dev=stale_identity["lock"][0],
                st_ino=stale_identity["lock"][1],
                st_mode=info.st_mode,
            )
        return info

    import fcntl as real_fcntl_module
    import os as real_os_module_full

    fcntl_shim = SimpleNamespace(**vars(real_fcntl_module))
    fcntl_shim.flock = choreographed_flock
    checkpoint_module.fcntl = fcntl_shim
    os_shim = SimpleNamespace(**vars(real_os_module_full))
    os_shim.stat = verifying_stat_removed
    os_shim.open = spying_open
    checkpoint_module.os = os_shim
    try:
        mutated_lease = store.try_acquire(conversation_id)
    finally:
        checkpoint_module.os = checkpoint_module_os_original
        checkpoint_module.fcntl = real_fcntl
    # 重验被移除 ⇒ 错误签发（测试对重验存在性敏感）。
    assert mutated_lease is not None
    mutated_lease.release()

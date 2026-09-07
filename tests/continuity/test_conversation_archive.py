"""020 Slice A：ConversationArchive 本地实现的原子性、幂等与 fail-closed 合同。

这些测试只穿过 public boundary（port + 本地实现），不接触 Runtime/CAS reducer。
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest

import agent.continuity.archive as archive_module
from agent.continuity.archive import (
    ArchiveConflictError,
    ArchiveError,
    ArchiveSecurityError,
    LocalConversationArchive,
)
from agent.runtime.checkpoint import (
    CheckpointMalformedError,
    LocalCheckpointStore,
    encode_conversation_state,
)
from agent.runtime.contracts import (
    ArchivedConversation,
    ConversationFact,
    ConversationState,
    ConversationSummaryV1,
    ConversationWorkspaceBindingV1,
    FactKind,
    LoadedSnapshot,
)
from agent.runtime.ports import ConversationArchive

SCOPE_A = "11" * 32
SCOPE_B = "22" * 32
CONVERSATION_A = "0f0e0d0c-1a2b-4c3d-8e9f-a1b2c3d4e5f6"
CONVERSATION_B = "7c6b5a49-3d8e-4f90-9a0b-c1d2e3f4a5b6"
_TEMP_NAME_FOR_TEST = re.compile(r"\.[0-9a-f]{64}\.json\.tmp-[0-9a-f]{24}")


def _binding(scope: str) -> ConversationWorkspaceBindingV1:
    return ConversationWorkspaceBindingV1.create(
        workspace_scope_digest=scope,
        workspace_identity_digest=f"workspace:v1:{scope}",
        bound_at="2026-09-04T00:00:00Z",
    )


def _rich_state(conversation_id: str, scope: str) -> ConversationState:
    summary = ConversationSummaryV1(
        objective="deliver the archive slice",
        constraints=("stay inside the transcript root",),
        decisions=("archive before CAS",),
        completed=("conversation archive port",),
        open_items=("runtime integration",),
        key_references=("docs/plans/2026-09-04-001",),
        source_checkpoint_digest="9" * 64,
        source_fact_ids_digest="8" * 64,
    )
    facts = (
        ConversationFact(
            fact_id="fact-user-1",
            kind=FactKind.USER_MESSAGE,
            content={"message": "archive the pre-compaction state"},
        ),
        ConversationFact(
            fact_id="fact-summary-1",
            kind=FactKind.CONTEXT_SUMMARY,
            content=summary.to_content(),
        ),
    )
    return replace(
        ConversationState.new(conversation_id, workspace_binding=_binding(scope)),
        facts=facts,
        revision=3,
    )


def _checkpointed_state(
    state_root: Path,
    state: ConversationState,
) -> LoadedSnapshot:
    """用真实 checkpoint 落盘得到 source digest（token）。"""

    scope = state.workspace_binding.workspace_scope_digest
    workspace_dir = state_root / "workspaces" / scope
    workspace_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    store = LocalCheckpointStore.initialize(
        workspace_dir / f"{state.conversation_id}.json",
        state,
    )
    return store.load()


def _digest_hex(token: str) -> str:
    assert token.startswith("sha256:") and len(token) == 71
    return token.removeprefix("sha256:")


def test_archive_persists_lossless_state_under_transcripts_layout(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))

    archive = LocalConversationArchive(state_root)
    assert isinstance(archive, ConversationArchive)
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )

    expected = (
        state_root
        / "transcripts"
        / SCOPE_A
        / CONVERSATION_A
        / f"{_digest_hex(snapshot.token)}.json"
    )
    assert isinstance(record, ArchivedConversation)
    assert record.path == expected
    assert record.conversation_id == CONVERSATION_A
    assert record.workspace_scope_digest == SCOPE_A
    assert record.source_checkpoint_digest == snapshot.token
    # transcript 布局独立于 workspaces checkpoint 枚举目录。
    assert record.path.relative_to(state_root).parts[0] == "transcripts"
    for directory in (
        state_root / "transcripts",
        state_root / "transcripts" / SCOPE_A,
        state_root / "transcripts" / SCOPE_A / CONVERSATION_A,
    ):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    info = record.path.stat()
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_nlink == 1

    # lossless：archive 字节与 checkpoint codec 输出、源 checkpoint 文件完全一致。
    assert record.path.read_bytes() == encode_conversation_state(snapshot.state)
    assert record.path.read_bytes() == (
        state_root / "workspaces" / SCOPE_A / f"{CONVERSATION_A}.json"
    ).read_bytes()

    loaded = archive.load_archived(record)
    assert isinstance(loaded, LoadedSnapshot)
    assert loaded.state == snapshot.state
    assert loaded.token == snapshot.token


def test_archive_is_idempotent_for_repeated_same_digest(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)

    first = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )
    before = first.path.stat()
    second = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )

    assert second == first
    after = first.path.stat()
    assert after.st_ino == before.st_ino
    assert after.st_mtime_ns == before.st_mtime_ns


def test_archive_fails_closed_when_digest_disagrees_with_content(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)

    # 声称的 digest 与被归档内容不一致：在写入前拒绝。
    with pytest.raises(ArchiveConflictError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=f"sha256:{'0' * 64}",
            workspace_scope_digest=SCOPE_A,
        )

    # 已存在同 digest 文件但内容被篡改：fail closed 且不覆盖。
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )
    tampered = b"tampered archive body"
    record.path.write_bytes(tampered)
    with pytest.raises(ArchiveConflictError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )
    assert record.path.read_bytes() == tampered
    # 冲突 fail closed 后不得留下 temp 残留。
    assert list(record.path.parent.iterdir()) == [record.path]


def test_archive_fails_closed_on_unsafe_filesystem_objects(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )
    conversation_dir = record.path.parent

    # 同名 symlink：O_NOFOLLOW 拒绝。
    record.path.unlink()
    record.path.symlink_to("elsewhere.json")
    with pytest.raises(ArchiveSecurityError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )
    record.path.unlink()
    record.path.write_bytes(encode_conversation_state(snapshot.state))
    os.chmod(record.path, 0o600)

    # 错误 mode：fail closed。
    os.chmod(record.path, 0o644)
    with pytest.raises(ArchiveSecurityError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )
    with pytest.raises(ArchiveSecurityError):
        archive.load_archived(record)
    with pytest.raises(ArchiveSecurityError):
        archive.load_archived_by_identity(
            conversation_id=snapshot.state.conversation_id,
            workspace_scope_digest=SCOPE_A,
            source_checkpoint_digest=snapshot.token,
        )
    os.chmod(record.path, 0o600)

    # hardlink（nlink != 1）：fail closed。
    hardlink = conversation_dir / "hardlink.json"
    os.link(record.path, hardlink)
    try:
        with pytest.raises(ArchiveSecurityError):
            archive.load_archived(record)
        with pytest.raises(ArchiveSecurityError):
            archive.load_archived_by_identity(
                conversation_id=snapshot.state.conversation_id,
                workspace_scope_digest=SCOPE_A,
                source_checkpoint_digest=snapshot.token,
            )
    finally:
        hardlink.unlink()

    # conversation 目录本身是 symlink：fail closed。
    renamed = conversation_dir.with_name("renamed")
    conversation_dir.rename(renamed)
    conversation_dir.symlink_to(renamed, target_is_directory=True)
    try:
        with pytest.raises(ArchiveSecurityError):
            archive.archive(
                snapshot.state,
                source_checkpoint_digest=snapshot.token,
                workspace_scope_digest=SCOPE_A,
            )
    finally:
        conversation_dir.unlink()
        renamed.rename(conversation_dir)


@pytest.mark.parametrize("failed_validation", [1, 2])
def test_directory_validation_failure_closes_every_opened_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_validation: int,
) -> None:
    """目录已打开但身份验证失败时，root/child helper 都不得泄漏 fd。"""

    state_root = tmp_path / "state"
    transcripts = state_root / "transcripts"
    scope = transcripts / SCOPE_A
    state_root.mkdir(mode=0o700)
    transcripts.mkdir(mode=0o700)
    scope.mkdir(mode=0o700)
    archive = LocalConversationArchive(state_root)
    real_open = os.open
    real_validate = archive_module._validate_directory_fd
    opened_fds: list[int] = []
    validations = 0

    def recording_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened_fds.append(fd)
        return fd

    def failing_validate(fd: int) -> None:
        nonlocal validations
        validations += 1
        if validations == failed_validation:
            raise ArchiveSecurityError("injected directory validation failure")
        real_validate(fd)

    monkeypatch.setattr(archive_module.os, "open", recording_open)
    monkeypatch.setattr(archive_module, "_validate_directory_fd", failing_validate)

    try:
        with pytest.raises(ArchiveSecurityError, match="injected"):
            archive.list_archived(workspace_scope_digest=SCOPE_A)
        assert len(opened_fds) == failed_validation
        for fd in opened_fds:
            with pytest.raises(OSError) as closed:
                os.fstat(fd)
            assert closed.value.errno == errno.EBADF
    finally:
        for fd in opened_fds:
            with suppress(OSError):
                os.close(fd)


def test_list_archived_is_workspace_bound_bounded_and_read_only(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    archive = LocalConversationArchive(state_root)

    records_a = []
    for conversation_id in (CONVERSATION_A, CONVERSATION_B):
        snapshot = _checkpointed_state(state_root, _rich_state(conversation_id, SCOPE_A))
        records_a.append(
            archive.archive(
                snapshot.state,
                source_checkpoint_digest=snapshot.token,
                workspace_scope_digest=SCOPE_A,
            )
        )
    snapshot_b = _checkpointed_state(state_root, _rich_state(CONVERSATION_B, SCOPE_B))
    record_b = archive.archive(
        snapshot_b.state,
        source_checkpoint_digest=snapshot_b.token,
        workspace_scope_digest=SCOPE_B,
    )

    listing = archive.list_archived(workspace_scope_digest=SCOPE_A)
    assert sorted(record.path for record in listing) == sorted(
        record.path for record in records_a
    )
    assert all(record.workspace_scope_digest == SCOPE_A for record in listing)
    assert record_b not in listing

    # 只读：未知 scope 与全新 root 都不创建任何目录。
    assert archive.list_archived(workspace_scope_digest="9" * 64) == ()
    assert not (state_root / "transcripts" / ("9" * 64)).exists()
    fresh_root = tmp_path / "fresh"
    fresh = LocalConversationArchive(fresh_root)
    assert fresh.list_archived(workspace_scope_digest=SCOPE_A) == ()
    assert not fresh_root.exists()

    # transcript 归档绝不进入 workspaces checkpoint 枚举目录。
    assert set(os.listdir(state_root / "workspaces" / SCOPE_A)) == {
        f"{CONVERSATION_A}.json",
        f"{CONVERSATION_B}.json",
    }

    # 超出 listing bound：fail closed。
    bounded = LocalConversationArchive(state_root, max_archives=1)
    with pytest.raises(ArchiveError, match="bound"):
        bounded.list_archived(workspace_scope_digest=SCOPE_A)

    # scope 目录内出现未知条目：fail closed。
    (state_root / "transcripts" / SCOPE_A / "not-a-conversation").mkdir()
    with pytest.raises(ArchiveError):
        archive.list_archived(workspace_scope_digest=SCOPE_A)
    (state_root / "transcripts" / SCOPE_A / "not-a-conversation").rmdir()


def test_load_archived_rejects_forged_or_mismatched_records(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )

    # 伪造 scope 的 record：path 推导不匹配，fail closed。
    forged_scope = replace(record, workspace_scope_digest=SCOPE_B)
    with pytest.raises(ArchiveError):
        archive.load_archived(forged_scope)

    # 越权归档：state 绑定 scope A，却试图归档进 scope B。
    with pytest.raises(ArchiveError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_B,
        )

    # 文件名 digest 与内容不一致（篡改后 load）：fail closed。
    tampered = encode_conversation_state(
        replace(snapshot.state, revision=snapshot.state.revision + 1)
    )
    record.path.write_bytes(tampered)
    with pytest.raises(ArchiveError):
        archive.load_archived(record)

    # digest 与字节一致但不是合法 checkpoint JSON：走 codec fail closed。
    garbage = b"not a conversation state"
    garbage_token = f"sha256:{hashlib.sha256(garbage).hexdigest()}"
    garbage_path = record.path.parent / f"{_digest_hex(garbage_token)}.json"
    garbage_path.write_bytes(garbage)
    os.chmod(garbage_path, 0o600)
    with pytest.raises(CheckpointMalformedError):
        archive.load_archived(
            ArchivedConversation(
                conversation_id=CONVERSATION_A,
                workspace_scope_digest=SCOPE_A,
                source_checkpoint_digest=garbage_token,
                path=garbage_path,
            )
        )

    # record 指向的 conversation 与文件内容的 identity 不一致：fail closed。
    misplaced_dir = state_root / "transcripts" / SCOPE_A / CONVERSATION_B
    misplaced_dir.mkdir(parents=True, mode=0o700)
    misplaced_path = misplaced_dir / record.path.name
    misplaced_path.write_bytes(encode_conversation_state(snapshot.state))
    os.chmod(misplaced_path, 0o600)
    with pytest.raises(ArchiveError):
        archive.load_archived(
            ArchivedConversation(
                conversation_id=CONVERSATION_B,
                workspace_scope_digest=SCOPE_A,
                source_checkpoint_digest=record.source_checkpoint_digest,
                path=misplaced_path,
            )
        )


def test_archive_rejects_malformed_identities(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)

    with pytest.raises(ValueError, match="conversation_id"):
        archive.archive(
            replace(snapshot.state, conversation_id="../escape"),
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )
    with pytest.raises(ValueError, match="digest"):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest="md5:abcdef",
            workspace_scope_digest=SCOPE_A,
        )
    with pytest.raises(ValueError, match="workspace"):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest="../escape",
        )

    # 无 workspace binding 的 state 不能进入 archive（无法证明 scope 绑定）。
    with pytest.raises(ArchiveError, match="binding"):
        archive.archive(
            ConversationState.new(CONVERSATION_A),
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )


def _plant_archive_entry(conversation_dir: Path, hex_name: str, mode: int) -> Path:
    """手工布置一个仅文件名合法的 archive 条目，用于只测 list 阶段的验证。"""

    entry = conversation_dir / f"{hex_name}.json"
    entry.write_bytes(b"{}")
    os.chmod(entry, mode)
    return entry


def test_list_archived_stops_traversal_at_bound_without_materializing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """listing 必须流式计数：在 max_archives + 1 即停止，不先把目录 materialize。"""

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    scope_dir = state_root / "transcripts" / SCOPE_A
    # parents=True 的中间目录用默认 mode，必须分层创建保证 0700。
    scope_dir.parent.mkdir(mode=0o700)
    scope_dir.mkdir(mode=0o700)
    # 大量条目：两个 conversation 共 72 个合法命名的 archive 文件，远超 bound。
    for conversation_id, count in ((CONVERSATION_A, 64), (CONVERSATION_B, 8)):
        conversation_dir = scope_dir / conversation_id
        conversation_dir.mkdir(mode=0o700)
        for index in range(count):
            _plant_archive_entry(conversation_dir, f"{index:064x}", 0o600)

    archive = LocalConversationArchive(state_root, max_archives=3)
    validations: list[int] = []
    original_validate = archive_module._validate_regular_file

    def counting_validate(fd: int) -> None:
        validations.append(fd)
        original_validate(fd)

    monkeypatch.setattr(archive_module, "_validate_regular_file", counting_validate)

    with pytest.raises(ArchiveError, match="bound"):
        archive.list_archived(workspace_scope_digest=SCOPE_A)

    # traversal 在 bound + 1 个文件后立即停止，其余 68+ 个条目不被触碰。
    assert len(validations) == 4


def test_list_archived_fails_closed_on_unsafe_archive_files(tmp_path: Path) -> None:
    """list 阶段对 archive 文件同样验证 mode/nlink（owner 由 fd 验证覆盖）。"""

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    scope_dir = state_root / "transcripts" / SCOPE_A
    scope_dir.parent.mkdir(mode=0o700)
    scope_dir.mkdir(mode=0o700)
    conversation_dir = scope_dir / CONVERSATION_A
    conversation_dir.mkdir(mode=0o700)
    archive = LocalConversationArchive(state_root)

    # 错误 mode：list 阶段必须抛 ArchiveSecurityError，而不是静默枚举成功。
    loose = _plant_archive_entry(conversation_dir, "1" * 64, 0o644)
    with pytest.raises(ArchiveSecurityError):
        archive.list_archived(workspace_scope_digest=SCOPE_A)

    # hardlink（nlink != 1）：list 阶段同样 fail closed。
    os.chmod(loose, 0o600)
    victim = _plant_archive_entry(conversation_dir, "2" * 64, 0o600)
    os.link(victim, conversation_dir / f"{'3' * 64}.json")
    with pytest.raises(ArchiveSecurityError):
        archive.list_archived(workspace_scope_digest=SCOPE_A)


# --------------------------------------------------------------------------- #
# durable publication 与 retry：失败不得暴露半截 final，重试必须补齐 barrier
# --------------------------------------------------------------------------- #


def _install_fsync_probe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_when: Callable[[str], bool],
) -> list[str]:
    """替换 ``os.fsync``：记录每次调用对象是文件还是目录，按需注入失败。"""

    seen: list[str] = []
    real_fsync = os.fsync

    def probing_fsync(fd: int) -> None:
        kind = "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        seen.append(kind)
        if fail_when(kind):
            raise OSError(errno.EIO, "injected fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", probing_fsync)
    return seen


def _final_archive_path(state_root: Path, snapshot: LoadedSnapshot) -> Path:
    return (
        state_root
        / "transcripts"
        / SCOPE_A
        / CONVERSATION_A
        / f"{_digest_hex(snapshot.token)}.json"
    )


def test_file_fsync_failure_hides_partial_publication_and_retry_completes_barriers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """file fsync 失败：final 从未存在且无 temp 残留；retry 真实重做两个 barrier。"""

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    conversation_dir = state_root / "transcripts" / SCOPE_A / CONVERSATION_A
    final = _final_archive_path(state_root, snapshot)
    fired = {"file": 0}

    def fail_first_file_fsync(kind: str) -> bool:
        if kind == "file":
            fired["file"] += 1
            return fired["file"] == 1
        return False

    seen = _install_fsync_probe(monkeypatch, fail_when=fail_first_file_fsync)

    with pytest.raises(ArchiveError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )

    # 失败的写入不得把 final 或本次 temp 暴露在 digest 目录里。
    assert not final.exists()
    assert list(conversation_dir.iterdir()) == []

    seen.clear()
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )

    assert record.path == final
    assert final.read_bytes() == encode_conversation_state(snapshot.state)
    # 返回成功必须意味着本次路径真实完成了 file 与 directory 两个 barrier。
    assert "file" in seen
    assert "dir" in seen


def test_partial_write_failure_leaves_no_final_and_retry_succeeds(
    tmp_path: Path,
) -> None:
    """_write_all 写入部分字节后失败：final 从未存在、temp 清理；retry 成功。"""

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    conversation_dir = state_root / "transcripts" / SCOPE_A / CONVERSATION_A
    final = _final_archive_path(state_root, snapshot)

    with pytest.MonkeyPatch.context() as mp:

        def partial_write(fd: int, data: bytes) -> None:
            os.write(fd, data[:64])
            raise OSError(errno.EIO, "injected partial write failure")

        mp.setattr(archive_module, "_write_all", partial_write)
        with pytest.raises(ArchiveError):
            archive.archive(
                snapshot.state,
                source_checkpoint_digest=snapshot.token,
                workspace_scope_digest=SCOPE_A,
            )

    # 半截内容只能留在已清理的 temp 上，绝不在最终 digest 名下。
    assert not final.exists()
    assert list(conversation_dir.iterdir()) == []

    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )

    assert record.path == final
    assert final.read_bytes() == encode_conversation_state(snapshot.state)


def test_directory_fsync_failure_retry_reverifies_same_fd_and_redoes_barriers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """publication 后 directory fsync 失败：final 可能已存在；retry 必须在同一

    no-follow 打开的 final 上重新校验并重做 file+directory fsync，不能只比较字节。
    """

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    conversation_dir = state_root / "transcripts" / SCOPE_A / CONVERSATION_A
    final = _final_archive_path(state_root, snapshot)
    fired = {"dir": 0}

    def fail_publication_dir_fsync(kind: str) -> bool:
        if kind == "dir":
            fired["dir"] += 1
            # 完整 dir fsync 序列：state_root、transcripts、scope 三个父
            # barrier 之后，第 4 次才是 final publication 的 conversation
            # 目录 barrier——精确失败在这里，保持本测试原有语义。
            return fired["dir"] == 4
        return False

    seen = _install_fsync_probe(monkeypatch, fail_when=fail_publication_dir_fsync)

    with pytest.raises(ArchiveError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )

    # link 已发布：final 可能已存在且内容完整，但成功尚未被承诺。
    assert final.exists()
    assert final.read_bytes() == encode_conversation_state(snapshot.state)
    before = final.stat()

    seen.clear()
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )

    assert record.path == final
    after = final.stat()
    # equal 路径不重写 final：inode 与 mtime 不变。
    assert after.st_ino == before.st_ino
    assert after.st_mtime_ns == before.st_mtime_ns
    # retry 必须重新完成 file fsync 与 directory fsync，而不只是比较字节。
    assert seen.count("file") >= 1
    assert seen.count("dir") >= 1
    # 无 temp 残留。
    assert list(conversation_dir.iterdir()) == [final]


def test_publication_links_temp_without_following_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """publication 的 link 必须显式 no-follow：默认 follow_symlinks=True 会在

    temp 被替换为 symlink 时把链接目标暴露进 archive 目录，违反本模块的
    no-follow 安全合同。
    """

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    real_link = os.link
    observed: list[bool] = []

    def probing_link(
        src,
        dst,
        *,
        src_dir_fd=None,
        dst_dir_fd=None,
        follow_symlinks=True,
    ):
        observed.append(follow_symlinks)
        return real_link(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(os, "link", probing_link)

    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )

    # publication 恰好一次 link，且必须显式要求不跟随 symlink。
    assert observed == [False]
    assert record.path.read_bytes() == encode_conversation_state(snapshot.state)


# --------------------------------------------------------------------------- #
# F2：父目录 durability barrier —— transcripts/scope/conversation 三层目录
# 创建各自需要 fsync 父目录（state_root/transcripts/scope）；任一父 barrier
# 首次失败后，目录已存在的 retry 必须重新执行所有所需父 barrier。
# --------------------------------------------------------------------------- #


def _install_inode_fsync_probe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_dir_sequence: int | None = None,
) -> list[tuple[int, int, str]]:
    """替换 ``os.fsync``：记录每次调用目标的 ``(dev, ino, kind)``。

    识别 fsync 目标不依赖 macOS 专用 F_GETPATH：事后用 ``stat`` 得到各目录
    与文件的 (dev, ino) 再映射。``fail_dir_sequence`` 非空时，第 N 次
    directory fsync 注入一次 EIO，用于精确定位目录创建链上的某个 barrier。
    """

    seen: list[tuple[int, int, str]] = []
    real_fsync = os.fsync
    fired = {"dir": 0}

    def probing_fsync(fd: int) -> None:
        info = os.fstat(fd)
        kind = "dir" if stat.S_ISDIR(info.st_mode) else "file"
        seen.append((info.st_dev, info.st_ino, kind))
        if kind == "dir":
            fired["dir"] += 1
            if fail_dir_sequence is not None and fired["dir"] == fail_dir_sequence:
                raise OSError(errno.EIO, "injected fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", probing_fsync)
    return seen


def _inode_of(path: Path) -> tuple[int, int]:
    info = os.stat(path, follow_symlinks=False)
    assert stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
    return (info.st_dev, info.st_ino)


def _barrier_targets(
    seen: list[tuple[int, int, str]],
) -> dict[tuple[int, int], set[str]]:
    targets: dict[tuple[int, int], set[str]] = {}
    for dev, ino, kind in seen:
        targets.setdefault((dev, ino), set()).add(kind)
    return targets


def _assert_all_barriers_covered(
    seen: list[tuple[int, int, str]],
    *,
    state_root: Path,
    final: Path,
) -> None:
    """成功返回必须覆盖 state_root、transcripts、scope、conversation 四个

    目录 inode 的 fsync，以及 archive 文件 inode 的 fsync。
    """

    targets = _barrier_targets(seen)
    assert targets[_inode_of(state_root)] == {"dir"}
    assert targets[_inode_of(state_root / "transcripts")] == {"dir"}
    assert targets[_inode_of(state_root / "transcripts" / SCOPE_A)] == {"dir"}
    assert targets[_inode_of(final.parent)] == {"dir"}
    assert targets[_inode_of(final)] == {"file"}


def test_successful_archive_covers_parent_chain_and_file_barriers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全新成功路径必须完成全部五个 barrier：state_root、transcripts、scope、

    conversation 四个目录 fsync 加 archive 文件 fsync，缺一不可宣称成功。
    """

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    final = _final_archive_path(state_root, snapshot)
    seen = _install_inode_fsync_probe(monkeypatch)

    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )

    assert record.path == final
    _assert_all_barriers_covered(seen, state_root=state_root, final=final)


@pytest.mark.parametrize(
    ("fail_dir_sequence", "existing_after_failure"),
    [
        # barrier 1：mkdir transcripts 后 fsync state_root；scope 及更深层未创建。
        (1, ("transcripts",)),
        # barrier 2：mkdir scope 后 fsync transcripts；conversation 未创建。
        (2, ("transcripts", "scope")),
        # barrier 3：mkdir conversation 后 fsync scope；archive 文件未写入。
        (3, ("transcripts", "scope", "conversation")),
    ],
)
def test_parent_barrier_failure_fails_closed_and_retry_redoes_all_barriers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_dir_sequence: int,
    existing_after_failure: tuple[str, ...],
) -> None:
    """每个父 barrier 首次失败都必须 fail closed，且失败点精确：恰好第 N

    层目录已创建、更深层未创建、final 从未存在。目录已存在的 retry 必须
    重新执行所有所需父 barrier（而非只在缺失时补建），最终成功。
    """

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    transcripts_dir = state_root / "transcripts"
    scope_dir = transcripts_dir / SCOPE_A
    conversation_dir = scope_dir / CONVERSATION_A
    final = _final_archive_path(state_root, snapshot)
    layer_dirs = {
        "transcripts": transcripts_dir,
        "scope": scope_dir,
        "conversation": conversation_dir,
    }

    seen = _install_inode_fsync_probe(
        monkeypatch, fail_dir_sequence=fail_dir_sequence
    )

    with pytest.raises(ArchiveError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )

    # 失败注入精确定位在目录创建链的第 N 个父 barrier 上。
    for layer, directory in layer_dirs.items():
        if layer in existing_after_failure:
            assert directory.is_dir()
        else:
            assert not directory.exists()
    assert not final.exists()

    # retry：上层目录已存在，但所有所需父 barrier 都要重做，最终成功。
    seen.clear()
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )

    assert record.path == final
    assert final.read_bytes() == encode_conversation_state(snapshot.state)
    _assert_all_barriers_covered(seen, state_root=state_root, final=final)
    assert list(conversation_dir.iterdir()) == [final]


# --------------------------------------------------------------------------- #
# link 前 hard-exit 暂态：listing 不因协议 temp 永久失败，重试收敛残留
# --------------------------------------------------------------------------- #


# 子进程源码：加载真实 checkpoint、走公共 archive()，把 os.link 替换为
# os._exit(77)，使进程精确死在“temp 完整写入并 fsync 后、publication
# link 前”的窗口：不运行任何 finally，复现进程级硬退出。
_HARD_EXIT_CHILD_SOURCE = '''
import os
import sys
from pathlib import Path

state_root = Path(sys.argv[1])
workspace_state_path = Path(sys.argv[2])
scope = sys.argv[3]

from agent.continuity.archive import LocalConversationArchive
from agent.runtime.checkpoint import LocalCheckpointStore

snapshot = LocalCheckpointStore(workspace_state_path).load()

# temp 已完整写入并 fsync；在 publication link 被调用的瞬间硬退出。
os.link = lambda *args, **kwargs: os._exit(77)

archive = LocalConversationArchive(state_root)
archive.archive(
    snapshot.state,
    source_checkpoint_digest=snapshot.token,
    workspace_scope_digest=scope,
)
raise SystemExit("archive returned without a publication link; window not hit")
'''


_HARD_EXIT_AFTER_LINK_CHILD_SOURCE = '''
import os
import sys
from pathlib import Path

state_root = Path(sys.argv[1])
workspace_state_path = Path(sys.argv[2])
scope = sys.argv[3]

from agent.continuity.archive import LocalConversationArchive
from agent.runtime.checkpoint import LocalCheckpointStore

snapshot = LocalCheckpointStore(workspace_state_path).load()

# publication link 已完成；第一次 unlink 正是清理同 inode temp 的窗口。
os.unlink = lambda *args, **kwargs: os._exit(78)

archive = LocalConversationArchive(state_root)
archive.archive(
    snapshot.state,
    source_checkpoint_digest=snapshot.token,
    workspace_scope_digest=scope,
)
raise SystemExit("archive returned without temp cleanup; window not hit")
'''


def test_temp_stranded_by_hard_exit_before_publication_is_reconciled(
    tmp_path: Path,
) -> None:
    """link 前 os._exit 硬退出残留的协议 temp：reader 只读跳过该暂态，

    同 digest 重试在写入路径内收敛自己的 temp，listing 不再永久失败。
    """

    project_root = Path(__file__).resolve().parents[2]
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    workspace_state_path = state_root / "workspaces" / SCOPE_A / f"{CONVERSATION_A}.json"

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            _HARD_EXIT_CHILD_SOURCE,
            str(state_root),
            str(workspace_state_path),
            SCOPE_A,
        ],
        env={
            **os.environ,
            "PYTHONPATH": f"{project_root}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    # 精确死在 publication 窗口（exit 77），而不是其他失败模式。
    assert child.returncode == 77, child.stderr

    archive = LocalConversationArchive(state_root)
    conversation_dir = state_root / "transcripts" / SCOPE_A / CONVERSATION_A
    final = _final_archive_path(state_root, snapshot)

    # 残留恰好是本协议自己的闭合 temp 名：final 从未存在，temp 内容完整。
    entries = list(conversation_dir.iterdir())
    assert not final.exists()
    assert len(entries) == 1
    stranded_temp = entries[0]
    assert re.fullmatch(r"\.[0-9a-f]{64}\.json\.tmp-[0-9a-f]{24}", stranded_temp.name)
    assert stranded_temp.read_bytes() == encode_conversation_state(snapshot.state)

    # reader 只读：协议 temp 暂态不得让 stable archives 的 listing 失败，
    # 也不得被 listing 删除或修改。
    assert archive.list_archived(workspace_scope_digest=SCOPE_A) == ()
    assert stranded_temp.exists()

    # 同 digest 正常重试：成功返回，且在写入路径内收敛自己的 temp 残留。
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )
    assert record.path == final
    assert final.read_bytes() == encode_conversation_state(snapshot.state)
    assert list(conversation_dir.iterdir()) == [final]
    assert archive.list_archived(workspace_scope_digest=SCOPE_A) == (record,)


def test_temp_stranded_by_hard_exit_after_publication_is_reconciled(
    tmp_path: Path,
) -> None:
    """link 后、temp unlink 前硬退出：reader 只读容忍，writer 重试收敛。"""

    project_root = Path(__file__).resolve().parents[2]
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    workspace_state_path = state_root / "workspaces" / SCOPE_A / f"{CONVERSATION_A}.json"

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            _HARD_EXIT_AFTER_LINK_CHILD_SOURCE,
            str(state_root),
            str(workspace_state_path),
            SCOPE_A,
        ],
        env={
            **os.environ,
            "PYTHONPATH": f"{project_root}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert child.returncode == 78, child.stderr

    archive = LocalConversationArchive(state_root)
    conversation_dir = state_root / "transcripts" / SCOPE_A / CONVERSATION_A
    final = _final_archive_path(state_root, snapshot)
    entries = list(conversation_dir.iterdir())
    temps = [entry for entry in entries if _TEMP_NAME_FOR_TEST.fullmatch(entry.name)]

    assert final.exists()
    assert len(entries) == 2
    assert len(temps) == 1
    stranded_temp = temps[0]
    final_info = final.stat()
    temp_info = stranded_temp.stat()
    assert (temp_info.st_dev, temp_info.st_ino) == (
        final_info.st_dev,
        final_info.st_ino,
    )
    assert final_info.st_nlink == temp_info.st_nlink == 2

    # reader 只读验证同 inode 配对并跳过 temp，不做清理。
    expected_record = ArchivedConversation(
        conversation_id=CONVERSATION_A,
        workspace_scope_digest=SCOPE_A,
        source_checkpoint_digest=snapshot.token,
        path=final,
    )
    assert archive.list_archived(workspace_scope_digest=SCOPE_A) == (expected_record,)
    assert stranded_temp.exists()

    before = final.stat()
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )
    after = final.stat()

    assert record == expected_record
    assert (after.st_dev, after.st_ino, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
    )
    assert after.st_nlink == 1
    assert list(conversation_dir.iterdir()) == [final]
    assert final.read_bytes() == encode_conversation_state(snapshot.state)


def test_reader_tolerates_writer_removing_paired_temp_during_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reader 已看到 temp 名后 writer 完成恢复：重验 stable final，而非误报。"""

    project_root = Path(__file__).resolve().parents[2]
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    workspace_state_path = state_root / "workspaces" / SCOPE_A / f"{CONVERSATION_A}.json"
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            _HARD_EXIT_AFTER_LINK_CHILD_SOURCE,
            str(state_root),
            str(workspace_state_path),
            SCOPE_A,
        ],
        env={
            **os.environ,
            "PYTHONPATH": f"{project_root}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert child.returncode == 78, child.stderr

    archive = LocalConversationArchive(state_root)
    final = _final_archive_path(state_root, snapshot)
    real_read = archive_module._read_child_archive_entry
    writer_ran = False

    def read_after_writer_cleanup(directory_fd, name, **kwargs):  # noqa: ANN001
        nonlocal writer_ran
        if _TEMP_NAME_FOR_TEST.fullmatch(name) and not writer_ran:
            writer_ran = True
            archive.archive(
                snapshot.state,
                source_checkpoint_digest=snapshot.token,
                workspace_scope_digest=SCOPE_A,
            )
        return real_read(directory_fd, name, **kwargs)

    monkeypatch.setattr(
        archive_module,
        "_read_child_archive_entry",
        read_after_writer_cleanup,
    )

    expected = ArchivedConversation(
        conversation_id=CONVERSATION_A,
        workspace_scope_digest=SCOPE_A,
        source_checkpoint_digest=snapshot.token,
        path=final,
    )
    assert archive.list_archived(workspace_scope_digest=SCOPE_A) == (expected,)
    assert writer_ran
    assert final.stat().st_nlink == 1
    assert list(final.parent.iterdir()) == [final]


def test_listing_rechecks_temp_published_after_reader_cached_single_link(
    tmp_path: Path,
) -> None:
    """reader 缓存 nlink=1 后 writer 发布 final：按当前 inode 配对接受暂态。"""

    project_root = Path(__file__).resolve().parents[2]
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    workspace_state_path = state_root / "workspaces" / SCOPE_A / f"{CONVERSATION_A}.json"
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            _HARD_EXIT_CHILD_SOURCE,
            str(state_root),
            str(workspace_state_path),
            SCOPE_A,
        ],
        env={
            **os.environ,
            "PYTHONPATH": f"{project_root}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert child.returncode == 77, child.stderr

    conversation_dir = state_root / "transcripts" / SCOPE_A / CONVERSATION_A
    final = _final_archive_path(state_root, snapshot)
    (temp,) = tuple(conversation_dir.iterdir())
    directory_fd = os.open(
        conversation_dir,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        cached_temp, data = archive_module._read_child_archive_entry(
            directory_fd,
            temp.name,
            expected_links={1, 2},
            max_state_bytes=4_000_000,
        )
        assert cached_temp.st_nlink == 1
        os.link(
            temp.name,
            final.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        cached_final = archive_module._inspect_child_archive_file(
            directory_fd,
            final.name,
            expected_links={1, 2},
        )
        assert cached_final.st_nlink == 2
        assert data == encode_conversation_state(snapshot.state)

        archive_module._verify_listing_entries(
            directory_fd,
            {final.name: cached_final},
            {temp.name: cached_temp},
        )
    finally:
        os.close(directory_fd)


def test_protocol_shaped_temp_with_conflicting_content_fails_closed(
    tmp_path: Path,
) -> None:
    """闭合 temp 名不是单独的所有权证明；内容 identity 冲突必须保留并拒绝。"""

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )
    conflicting_temp = record.path.parent / f".{record.path.name}.tmp-{'a' * 24}"
    conflicting_temp.write_bytes(b"not the checkpoint named by this digest")
    os.chmod(conflicting_temp, 0o600)

    with pytest.raises(ArchiveConflictError):
        archive.list_archived(workspace_scope_digest=SCOPE_A)
    with pytest.raises(ArchiveConflictError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )

    assert conflicting_temp.exists()
    assert record.path.read_bytes() == encode_conversation_state(snapshot.state)


def test_protocol_shaped_temp_hardlinked_to_another_inode_fails_closed(
    tmp_path: Path,
) -> None:
    """temp 只有与其命名所指 final 同 inode 时才是可恢复 publication 暂态。"""

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )
    decoy = record.path.parent / f"{'1' * 64}.json"
    decoy.write_bytes(encode_conversation_state(snapshot.state))
    os.chmod(decoy, 0o600)
    forged_temp = record.path.parent / f".{record.path.name}.tmp-{'b' * 24}"
    os.link(decoy, forged_temp)
    before = {path.name: path.stat().st_ino for path in record.path.parent.iterdir()}

    with pytest.raises(ArchiveSecurityError):
        archive.list_archived(workspace_scope_digest=SCOPE_A)
    with pytest.raises(ArchiveSecurityError):
        archive.archive(
            snapshot.state,
            source_checkpoint_digest=snapshot.token,
            workspace_scope_digest=SCOPE_A,
        )

    after = {path.name: path.stat().st_ino for path in record.path.parent.iterdir()}
    assert after == before


def test_retry_leaves_other_digest_temp_untouched_and_unknown_hidden_fails_closed(
    tmp_path: Path,
) -> None:
    """writer 只收敛当前 digest；reader 只容忍闭合协议 temp。"""

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    snapshot = _checkpointed_state(state_root, _rich_state(CONVERSATION_A, SCOPE_A))
    archive = LocalConversationArchive(state_root)
    record = archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    )
    other_state = replace(snapshot.state, revision=snapshot.state.revision + 1)
    other_data = encode_conversation_state(other_state)
    other_digest = hashlib.sha256(other_data).hexdigest()
    other_temp = record.path.parent / f".{other_digest}.json.tmp-{'c' * 24}"
    other_temp.write_bytes(other_data)
    os.chmod(other_temp, 0o600)

    assert archive.archive(
        snapshot.state,
        source_checkpoint_digest=snapshot.token,
        workspace_scope_digest=SCOPE_A,
    ) == record
    assert other_temp.read_bytes() == other_data
    assert archive.list_archived(workspace_scope_digest=SCOPE_A) == (record,)

    unknown = record.path.parent / ".unknown-temp"
    unknown.write_bytes(b"unknown")
    os.chmod(unknown, 0o600)
    with pytest.raises(ArchiveError, match="unknown entry"):
        archive.list_archived(workspace_scope_digest=SCOPE_A)
    assert unknown.exists()
    assert other_temp.exists()

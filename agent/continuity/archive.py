"""020 长会话压缩：owner-only、不可变、幂等的本地 transcript archive。

布局固定在 ``state_root/transcripts/<workspace_scope_digest>/<conversation_id>/``，
独立于 ``workspaces/<scope>/`` 的严格 checkpoint 枚举目录。目录 0700，文件
0600、regular、owner、single-link、no-follow；文件名只由闭合 source
checkpoint digest 派生，不接受模型或用户路径。

写入采用同目录隐藏 temp + 原子 no-overwrite publication：temp 完整写入并
fsync 后才 link 到最终 digest 名；任何失败都不会把半截内容暴露在最终名下，
archive 返回成功意味着本次路径已完成全部 durability barrier（state_root、
transcripts、scope、conversation 四个目录 fsync 与 archive 文件 fsync），
同 digest 重试会重新补齐缺失的 barrier。
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
from contextlib import suppress
from pathlib import Path

from agent.runtime.checkpoint import (
    DEFAULT_MAX_STATE_BYTES,
    decode_conversation_state,
    encode_conversation_state,
)
from agent.runtime.contracts import (
    ArchivedConversation,
    ConversationState,
    LoadedSnapshot,
)

DEFAULT_ARCHIVE_LIST_LIMIT = 256

_DIGEST_TOKEN_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCOPE_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CONVERSATION_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_ARCHIVE_FILE_PATTERN = re.compile(r"^[0-9a-f]{64}\.json$")
# 本协议自己的闭合 temp 命名：``.{digest}.json.tmp-{24 hex}``，由
# _create_unique_temp_file 生成；只识别精确匹配，不宽容其他隐藏名。
_TEMP_FILE_PATTERN = re.compile(
    r"^\.(?P<archive>[0-9a-f]{64}\.json)\.tmp-[0-9a-f]{24}$"
)
# 写入路径内收敛残留 temp 的安全上界；正常路径下每次硬退出至多残留一个。
_TEMP_RECONCILE_LIMIT = 64


class ArchiveError(RuntimeError):
    """transcript archive 的 fail-closed 基类。"""


class ArchiveSecurityError(ArchiveError):
    """不安全的 filesystem object（symlink、hardlink、mode、owner、非 regular）。"""


class ArchiveConflictError(ArchiveError):
    """source checkpoint digest identity 与 archive 内容不一致。"""


class LocalConversationArchive:
    """``ConversationArchive`` 的本地实现；由 composition root 注入 state root。"""

    def __init__(
        self,
        state_root: Path,
        *,
        max_state_bytes: int = DEFAULT_MAX_STATE_BYTES,
        max_archives: int = DEFAULT_ARCHIVE_LIST_LIMIT,
    ) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise ArchiveSecurityError("required POSIX no-follow flags are unavailable")
        if max_state_bytes < 1:
            raise ValueError("max_state_bytes must be positive")
        if max_archives < 1:
            raise ValueError("max_archives must be positive")
        self._state_root = Path(state_root).absolute()
        self._transcripts_root = self._state_root / "transcripts"
        self._max_state_bytes = max_state_bytes
        self._max_archives = max_archives

    def archive(
        self,
        state: ConversationState,
        *,
        source_checkpoint_digest: str,
        workspace_scope_digest: str,
    ) -> ArchivedConversation:
        _validate_conversation_id(state.conversation_id)
        _validate_scope_digest(workspace_scope_digest)
        _validate_digest_token(source_checkpoint_digest)
        binding = state.workspace_binding
        if binding is None:
            raise ArchiveError("archived state must carry a workspace binding")
        if binding.workspace_scope_digest != workspace_scope_digest:
            raise ArchiveError(
                "archived state is not bound to the requested workspace scope"
            )
        data = encode_conversation_state(state)
        if _token(data) != source_checkpoint_digest:
            raise ArchiveConflictError(
                "source checkpoint digest does not match the encoded archived state"
            )

        # state_root 与三层 archive 目录全部经已验证的 no-follow dirfd
        # 路径逐层打开；任一环节失败都在 finally 中关闭已持有的 fd。
        state_root_fd = _open_directory_if_exists(self._state_root)
        if state_root_fd is None:
            raise ArchiveError("state root is missing")
        try:
            transcripts_fd = self._ensure_transcripts_directory(state_root_fd)
            try:
                scope_fd = _ensure_child_directory(
                    transcripts_fd, workspace_scope_digest
                )
                try:
                    conversation_fd = _ensure_child_directory(
                        scope_fd, state.conversation_id
                    )
                    try:
                        _write_archive_file(
                            conversation_fd,
                            _archive_file_name(source_checkpoint_digest),
                            data,
                            max_state_bytes=self._max_state_bytes,
                        )
                    finally:
                        os.close(conversation_fd)
                finally:
                    os.close(scope_fd)
            finally:
                os.close(transcripts_fd)
        finally:
            os.close(state_root_fd)
        return self._record(
            conversation_id=state.conversation_id,
            workspace_scope_digest=workspace_scope_digest,
            source_checkpoint_digest=source_checkpoint_digest,
        )

    def list_archived(
        self,
        *,
        workspace_scope_digest: str,
    ) -> tuple[ArchivedConversation, ...]:
        _validate_scope_digest(workspace_scope_digest)
        transcripts_fd = _open_directory_if_exists(self._transcripts_root)
        if transcripts_fd is None:
            return ()
        try:
            scope_fd = _open_child_directory_if_exists(
                transcripts_fd, workspace_scope_digest
            )
            if scope_fd is None:
                return ()
            try:
                return self._list_scope(scope_fd, workspace_scope_digest)
            finally:
                os.close(scope_fd)
        finally:
            os.close(transcripts_fd)

    def load_archived(self, archive: ArchivedConversation) -> LoadedSnapshot:
        _validate_conversation_id(archive.conversation_id)
        _validate_scope_digest(archive.workspace_scope_digest)
        _validate_digest_token(archive.source_checkpoint_digest)
        expected = self._record(
            conversation_id=archive.conversation_id,
            workspace_scope_digest=archive.workspace_scope_digest,
            source_checkpoint_digest=archive.source_checkpoint_digest,
        ).path
        if Path(archive.path) != expected:
            raise ArchiveError(
                "archived conversation record does not match its derived path"
            )

        transcripts_fd = _open_directory_if_exists(self._transcripts_root)
        if transcripts_fd is None:
            raise ArchiveError("transcript archive root is missing")
        try:
            scope_fd = _open_child_directory_if_exists(
                transcripts_fd, archive.workspace_scope_digest
            )
            if scope_fd is None:
                raise ArchiveError("archived workspace scope is missing")
            try:
                conversation_fd = _open_child_directory_if_exists(
                    scope_fd, archive.conversation_id
                )
                if conversation_fd is None:
                    raise ArchiveError("archived conversation is missing")
                try:
                    data = _read_archive_file(
                        conversation_fd,
                        _archive_file_name(archive.source_checkpoint_digest),
                        max_state_bytes=self._max_state_bytes,
                    )
                finally:
                    os.close(conversation_fd)
            finally:
                os.close(scope_fd)
        finally:
            os.close(transcripts_fd)
        if _token(data) != archive.source_checkpoint_digest:
            raise ArchiveConflictError(
                "archive content does not match its digest identity"
            )
        state = decode_conversation_state(data)
        if state.conversation_id != archive.conversation_id:
            raise ArchiveError(
                "archived state conversation identity does not match its record"
            )
        binding = state.workspace_binding
        if (
            binding is None
            or binding.workspace_scope_digest != archive.workspace_scope_digest
        ):
            raise ArchiveError("archived state is not bound to the record workspace")
        return LoadedSnapshot(state, archive.source_checkpoint_digest)

    def load_archived_by_identity(
        self,
        *,
        conversation_id: str,
        workspace_scope_digest: str,
        source_checkpoint_digest: str,
    ) -> LoadedSnapshot:
        """只接受归档 identity；路径始终由 adapter 内部推导。"""

        return self.load_archived(
            self._record(
                conversation_id=conversation_id,
                workspace_scope_digest=workspace_scope_digest,
                source_checkpoint_digest=source_checkpoint_digest,
            )
        )

    def _ensure_transcripts_directory(self, state_root_fd: int) -> int:
        # mkdir 与父 barrier 都走已验证的 no-follow dirfd 路径；child 已
        # 存在时仍重做 parent fsync，成功返回才能承诺目录项已持久化。
        with suppress(FileExistsError):
            os.mkdir("transcripts", 0o700, dir_fd=state_root_fd)
        _durable_fsync(state_root_fd)
        return _open_child_directory(state_root_fd, "transcripts")

    def _list_scope(
        self,
        scope_fd: int,
        workspace_scope_digest: str,
    ) -> tuple[ArchivedConversation, ...]:
        # 迭代扫描：逐条目打开 fd 验证，计数达到 bound 即停止，
        # 不先把目录 materialize 成无界列表。
        records: list[ArchivedConversation] = []
        with os.scandir(scope_fd) as entries:
            for entry in entries:
                conversation_name = entry.name
                if not _CONVERSATION_ID_PATTERN.fullmatch(conversation_name):
                    raise ArchiveError(
                        "transcripts workspace directory contains an unknown entry"
                    )
                conversation_fd = _open_child_directory(scope_fd, conversation_name)
                try:
                    self._collect_conversation_records(
                        conversation_fd,
                        conversation_name,
                        workspace_scope_digest,
                        records,
                    )
                finally:
                    os.close(conversation_fd)
        # 超过 bound 已在收集时抛错；待排序集合天然有界。
        records.sort(key=lambda record: str(record.path))
        return tuple(records)

    def _collect_conversation_records(
        self,
        conversation_fd: int,
        conversation_name: str,
        workspace_scope_digest: str,
        records: list[ArchivedConversation],
    ) -> None:
        archive_names: list[str] = []
        archive_infos: dict[str, os.stat_result] = {}
        temp_infos: dict[str, os.stat_result] = {}
        with os.scandir(conversation_fd) as entries:
            for entry in entries:
                file_name = entry.name
                if _TEMP_FILE_PATTERN.fullmatch(file_name):
                    try:
                        info, data = _read_child_archive_entry(
                            conversation_fd,
                            file_name,
                            expected_links={1, 2},
                            max_state_bytes=self._max_state_bytes,
                        )
                    except FileNotFoundError:
                        # writer 可能在 scandir 产出名字后完成协议 temp 清理；
                        # stable final 会在配对校验中重新打开确认。
                        continue
                    _verify_temp_content_identity(file_name, data)
                    temp_infos[file_name] = info
                    if len(temp_infos) > _TEMP_RECONCILE_LIMIT:
                        raise ArchiveError(
                            "archive temp listing exceeds its safety bound"
                        )
                    continue
                if not _ARCHIVE_FILE_PATTERN.fullmatch(file_name):
                    raise ArchiveError(
                        "transcripts conversation directory contains an unknown entry"
                    )
                archive_names.append(file_name)
                archive_infos[file_name] = _inspect_child_archive_file(
                    conversation_fd,
                    file_name,
                    expected_links={1, 2},
                )
                if len(records) + len(archive_names) > self._max_archives:
                    raise ArchiveError("archive listing exceeds its safety bound")
        _verify_listing_entries(conversation_fd, archive_infos, temp_infos)
        records.extend(
            self._record(
                conversation_id=conversation_name,
                workspace_scope_digest=workspace_scope_digest,
                source_checkpoint_digest=f"sha256:{file_name[: -len('.json')]}",
            )
            for file_name in archive_names
        )

    def _record(
        self,
        *,
        conversation_id: str,
        workspace_scope_digest: str,
        source_checkpoint_digest: str,
    ) -> ArchivedConversation:
        return ArchivedConversation(
            conversation_id=conversation_id,
            workspace_scope_digest=workspace_scope_digest,
            source_checkpoint_digest=source_checkpoint_digest,
            path=(
                self._transcripts_root
                / workspace_scope_digest
                / conversation_id
                / _archive_file_name(source_checkpoint_digest)
            ),
        )


def _archive_file_name(source_checkpoint_digest: str) -> str:
    return f"{source_checkpoint_digest.removeprefix('sha256:')}.json"


def _token(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _validate_conversation_id(conversation_id: str) -> None:
    if not _CONVERSATION_ID_PATTERN.fullmatch(conversation_id):
        raise ValueError("conversation_id must be a canonical UUID")


def _validate_scope_digest(workspace_scope_digest: str) -> None:
    if not _SCOPE_DIGEST_PATTERN.fullmatch(workspace_scope_digest):
        raise ValueError("workspace scope digest must be 64 lowercase hex characters")


def _validate_digest_token(source_checkpoint_digest: str) -> None:
    if not _DIGEST_TOKEN_PATTERN.fullmatch(source_checkpoint_digest):
        raise ValueError("source checkpoint digest must be a sha256:<hex> token")


def _security_or_archive_error(error: OSError, operation: str) -> ArchiveError:
    # ENOTDIR：macOS 对“期待目录却遇到 no-follow symlink”的返回值。
    if error.errno in {errno.ELOOP, errno.EMLINK, errno.ENOTDIR, errno.EPERM, errno.EACCES}:
        return ArchiveSecurityError(f"unsafe filesystem object during {operation}")
    return ArchiveError(f"filesystem error during {operation}: {error.strerror}")


def _validate_directory_fd(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ArchiveSecurityError("archive directory identity is unsafe")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise ArchiveSecurityError("archive directory mode must be 0700")


def _validate_regular_file(fd: int) -> None:
    _validate_regular_file_with_links(fd, expected_links={1})


def _validate_regular_file_with_links(
    fd: int,
    *,
    expected_links: set[int],
) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise ArchiveSecurityError("archive file must be a regular file")
    if info.st_uid != os.getuid():
        raise ArchiveSecurityError("archive file owner mismatch")
    if info.st_nlink not in expected_links:
        expected = " or ".join(str(value) for value in sorted(expected_links))
        raise ArchiveSecurityError(f"archive file link count must be {expected}")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise ArchiveSecurityError("archive file mode must be 0600")
    return info


def _open_directory_if_exists(path: Path) -> int | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _security_or_archive_error(error, "open archive directory") from error
    try:
        _validate_directory_fd(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_child_directory_if_exists(parent_fd: int, name: str) -> int | None:
    try:
        fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _security_or_archive_error(error, "open archive directory") from error
    try:
        _validate_directory_fd(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_child_directory(parent_fd: int, name: str) -> int:
    fd = _open_child_directory_if_exists(parent_fd, name)
    if fd is None:
        raise ArchiveError("archive directory is missing")
    return fd


def _ensure_child_directory(parent_fd: int, name: str) -> int:
    with suppress(FileExistsError):
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    # 父 durability barrier：目录项落盘以 parent fsync 为准；child 已存在
    # （上次 barrier 失败后的 retry）也要重做，不把缺失 barrier 当作成功。
    _durable_fsync(parent_fd)
    return _open_child_directory(parent_fd, name)


def _verify_child_archive_file(directory_fd: int, name: str) -> None:
    """以 no-follow 方式打开文件 fd 并做完整的安全验证（不读内容）。"""

    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        raise _security_or_archive_error(error, "open archive") from error
    try:
        _validate_regular_file(fd)
    finally:
        os.close(fd)


def _inspect_child_archive_file(
    directory_fd: int,
    name: str,
    *,
    expected_links: set[int],
) -> os.stat_result:
    """no-follow 打开并返回验证后的文件身份。"""

    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        raise _security_or_archive_error(error, "open archive") from error
    try:
        info = os.fstat(fd)
        if info.st_nlink == 1 and 1 in expected_links:
            _validate_regular_file(fd)
            return info
        return _validate_regular_file_with_links(
            fd,
            expected_links=expected_links,
        )
    finally:
        os.close(fd)


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _verify_listing_entries(
    directory_fd: int,
    archive_infos: dict[str, os.stat_result],
    temp_infos: dict[str, os.stat_result],
) -> None:
    """只读验证 stable archive 与协议 publication 暂态。"""

    paired_archives: set[str] = set()
    for temp_name, temp_info in temp_infos.items():
        if temp_info.st_nlink == 1:
            continue
        match = _TEMP_FILE_PATTERN.fullmatch(temp_name)
        if match is None:
            raise ArchiveSecurityError("archive temp identity is malformed")
        archive_name = match.group("archive")
        archive_info = archive_infos.get(archive_name)
        if archive_info is None or not _same_file(temp_info, archive_info):
            raise ArchiveSecurityError(
                "archive temp hardlink does not match its published archive"
            )
        paired_archives.add(archive_name)

    for archive_name, archive_info in archive_infos.items():
        if archive_info.st_nlink == 2 and archive_name not in paired_archives:
            current = _inspect_child_archive_file(
                directory_fd,
                archive_name,
                expected_links={1, 2},
            )
            if current.st_nlink == 1:
                continue
            for temp_name in temp_infos:
                match = _TEMP_FILE_PATTERN.fullmatch(temp_name)
                if match is None or match.group("archive") != archive_name:
                    continue
                current_temp = _inspect_child_archive_file(
                    directory_fd,
                    temp_name,
                    expected_links={1, 2},
                )
                if current_temp.st_nlink == 2 and _same_file(
                    current_temp, current
                ):
                    break
            else:
                raise ArchiveSecurityError(
                    "archive hardlink does not match a protocol publication temp"
                )


def _verify_temp_content_identity(name: str, data: bytes) -> None:
    match = _TEMP_FILE_PATTERN.fullmatch(name)
    if match is None:
        raise ArchiveSecurityError("archive temp identity is malformed")
    digest_hex = match.group("archive")[: -len(".json")]
    if _token(data) != f"sha256:{digest_hex}":
        raise ArchiveConflictError(
            "archive temp content does not match its digest identity"
        )


def _read_child_archive_entry(
    directory_fd: int,
    name: str,
    *,
    expected_links: set[int],
    max_state_bytes: int,
) -> tuple[os.stat_result, bytes]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise _security_or_archive_error(error, "open archive") from error
    try:
        info = _validate_regular_file_with_links(
            fd,
            expected_links=expected_links,
        )
        return info, _read_fd_all(fd, max_state_bytes=max_state_bytes)
    finally:
        os.close(fd)


def _write_archive_file(
    directory_fd: int,
    name: str,
    data: bytes,
    *,
    max_state_bytes: int,
) -> None:
    """以 temp + 原子 no-overwrite publication 写入不可变 archive 文件。

    成功返回当且仅当：temp 完整写入并 fsync，final 以最终 digest 名存在，
    且本次路径完成了 file 与 directory 两个 durability barrier。final
    已存在时不覆盖：同一 fd 上重新校验并补齐 barrier，不同内容或
    unsafe object 继续 fail closed。不可用 os.replace 覆盖 final。
    """

    if len(data) > max_state_bytes:
        raise ArchiveError("archive file exceeds configured capacity")
    # 先收敛 link 前硬退出残留的本协议 temp（发生在创建本次 temp 之前，
    # 不会误伤本次 temp）。
    _reconcile_temp_entries(
        directory_fd,
        name,
        data,
        max_state_bytes=max_state_bytes,
    )
    temp_name = ""
    try:
        temp_fd, temp_name = _create_unique_temp_file(directory_fd, name)
        try:
            try:
                os.fchmod(temp_fd, 0o600)
                _write_all(temp_fd, data)
                _durable_fsync(temp_fd)
            except OSError as error:
                # temp 写入路径上的底层 I/O 错误一律折叠为 fail-closed
                # ArchiveError，不让裸 OSError 逃出 archive 合同。
                raise _security_or_archive_error(error, "write archive") from error
        finally:
            os.close(temp_fd)
        # 原子 no-overwrite publication：link 成功即 final 指向已完整写入
        # 并 fsync 过的 temp inode；失败路径上 final 从未以 digest 名存在。
        # follow_symlinks=False 与本模块 no-follow 合同一致：temp 若被替换
        # 为 symlink，也只链接该条日本身，不把链接目标暴露进 archive。
        try:
            os.link(
                temp_name,
                name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            # final 已存在（上次 barrier 失败的残留或并发）：在重新校验的
            # 同一 fd 上补齐 barrier，equal 才成功，否则 fail closed 不覆盖。
            _verify_and_fsync_existing_archive(
                directory_fd, name, data, max_state_bytes=max_state_bytes
            )
            return
        except OSError as error:
            raise _security_or_archive_error(error, "publish archive") from error
        # link 成功：先移除 temp 目录项，再一次 dir fsync 同时覆盖 publish
        # 与清理两条目录变更。
        os.unlink(temp_name, dir_fd=directory_fd)
        temp_name = ""
        _durable_fsync(directory_fd)
    finally:
        if temp_name:
            # 只清理自己创建的 temp：失败路径不得留下半截内容；清理本身
            # 尽力而为，不掩盖原始异常。
            with suppress(FileNotFoundError):
                os.unlink(temp_name, dir_fd=directory_fd)
            with suppress(OSError):
                os.fsync(directory_fd)


def _reconcile_temp_entries(
    directory_fd: int,
    final_name: str,
    data: bytes,
    *,
    max_state_bytes: int,
) -> None:
    """有界收敛当前 digest 的协议 temp，不触碰其他可能在途写入。"""

    temps: list[str] = []
    with os.scandir(directory_fd) as entries:
        for entry in entries:
            match = _TEMP_FILE_PATTERN.fullmatch(entry.name)
            if match is not None and match.group("archive") == final_name:
                temps.append(entry.name)
                if len(temps) > _TEMP_RECONCILE_LIMIT:
                    raise ArchiveError(
                        "archive temp reconciliation exceeds its safety bound"
                    )
    for temp_name in temps:
        try:
            temp_fd = os.open(
                temp_name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise _security_or_archive_error(
                error, "open archive temp"
            ) from error
        try:
            temp_info = _validate_regular_file_with_links(
                temp_fd,
                expected_links={1, 2},
            )
            if _read_fd_all(temp_fd, max_state_bytes=max_state_bytes) != data:
                raise ArchiveConflictError(
                    "archive temp holds content for a different checkpoint"
                )
        finally:
            os.close(temp_fd)

        if temp_info.st_nlink == 2:
            final_info = _inspect_child_archive_file(
                directory_fd,
                final_name,
                expected_links={2},
            )
            if not _same_file(temp_info, final_info):
                raise ArchiveSecurityError(
                    "archive temp hardlink does not match its published archive"
                )
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except OSError as error:
            raise _security_or_archive_error(
                error, "reconcile archive temp"
            ) from error


def _create_unique_temp_file(directory_fd: int, final_name: str) -> tuple[int, str]:
    """在同目录创建唯一隐藏 temp（O_EXCL|O_NOFOLLOW|0600），返回其 fd 与名。"""

    for _ in range(8):
        candidate = f".{final_name}.tmp-{os.urandom(12).hex()}"
        try:
            fd = os.open(
                candidate,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            continue
        except OSError as error:
            raise _security_or_archive_error(error, "create archive") from error
        return fd, candidate
    raise ArchiveError("archive temporary name allocation failed")


def _verify_and_fsync_existing_archive(
    directory_fd: int,
    name: str,
    data: bytes,
    *,
    max_state_bytes: int,
) -> None:
    """final 已存在时的 equal/conflict 判定与 barrier 补齐。

    同一个 no-follow 打开的 fd 上完成安全验证、内容比较与 file fsync，
    成功前再补 directory fsync：不能只比较字节后直接宣布成功。
    """

    try:
        fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        raise _security_or_archive_error(error, "open archive") from error
    try:
        _validate_regular_file(fd)
        if _read_fd_all(fd, max_state_bytes=max_state_bytes) != data:
            raise ArchiveConflictError("archive digest already holds different content")
        _durable_fsync(fd)
    finally:
        os.close(fd)
    _durable_fsync(directory_fd)


def _durable_fsync(fd: int) -> None:
    """fsync 并把失败折叠为 fail-closed 的 ArchiveError。"""

    try:
        os.fsync(fd)
    except OSError as error:
        raise _security_or_archive_error(error, "fsync archive") from error


def _read_archive_file(
    directory_fd: int,
    name: str,
    *,
    max_state_bytes: int,
) -> bytes:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except FileNotFoundError as error:
        raise ArchiveError("archive file is missing") from error
    except OSError as error:
        raise _security_or_archive_error(error, "open archive") from error
    try:
        _validate_regular_file(fd)
        return _read_fd_all(fd, max_state_bytes=max_state_bytes)
    finally:
        os.close(fd)


def _read_fd_all(fd: int, *, max_state_bytes: int) -> bytes:
    """从已打开的 fd 有界读回全部内容，不重新打开路径。"""

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(65_536, max_state_bytes + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_state_bytes:
            raise ArchiveError("archive file exceeds configured capacity")
    return b"".join(chunks)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except OSError as error:
            raise _security_or_archive_error(error, "write archive") from error
        if written <= 0:
            raise ArchiveError("archive write made no progress")
        view = view[written:]

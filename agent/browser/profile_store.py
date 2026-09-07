"""018 owner-only persistent browser profile store（spec §3.2）。

descriptor-safe 的 profile 生命周期 owner：0700 root/目录、0600 metadata/lock、
no-follow、exclusive create、revision CAS、tri-state process-identity 单 writer
锁。公开接口只暴露 opaque ID 与 digest identity；account label 原文只进入
sha256。clear 先 revoke/关闭 writer，再删除 canonical owned root；任何
partial 或 identity 不确定都 CLEANUP_UNKNOWN 并 quarantine，绝不 follow
symlink、绝不越出 owned root。本模块不读取 storage-state。

路径安全模型：所有 owned-root 内的解析都以已打开的 directory fd 为锚
（``dir_fd`` + ``O_NOFOLLOW``），root/profile/metadata 之间不存在
lstat→open 的 parent-swap 窗口；owned root 自身的绝对路径解析
（O_NOFOLLOW 打开、fstat 验证）由 composition 层绑定的 browser state
root 边界保护。所有 mutation/writer API 都从 validated owned root fd
出发，并要求调用方持有与存储一致的完整 trusted ``BrowserProfileRefV1``。
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from agent.browser.contracts import BrowserCleanupOutcome

PROFILE_ID_PATTERN = re.compile(r"profile-[0-9a-f]{16}")
HEX64_PATTERN = re.compile(r"[0-9a-f]{64}")
LEASE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
METADATA_NAME = "metadata.json"
LOCK_NAME = "writer.lock"
QUARANTINE_NAME = "_quarantine"
MAX_METADATA_BYTES = 64 * 1024
MAX_LOCK_BYTES = 1024
METADATA_KEYS = frozenset(
    {
        "profile_id",
        "revision",
        "site_policy_digest",
        "account_label_digest",
        "browser_identity_digest",
        "status",
    }
)
# 003：writer.lock 是四字段 closed schema（pid/started_at/lease_id/
# acquired_revision）；旧两字段 lock 不静默升级，按 unknown 阻断。
LOCK_KEYS = frozenset({"pid", "started_at", "lease_id", "acquired_revision"})


class ProfileIntegrityError(Exception):
    """root/目录/metadata 不再是可信的 canonical descriptor，或 ref 伪造。"""


class ProfileNotFoundError(Exception):
    """请求的 opaque profile 不存在（或已被 clear/quarantine）。"""


class ProfileRevokedError(Exception):
    """profile 已 revoke，任何复用（advance/acquire）都被拒绝。"""


class ProfileRevisionConflict(Exception):  # noqa: N818  测试冻结的公开合同名
    """revision CAS 失败：expected revision 或 ref revision 已漂移。"""


class ProfileLockHeldError(Exception):
    """writer 锁由存活进程持有，不得偷取。"""


class ProfileLockUnknownError(Exception):
    """锁身份无法确定（corrupt/holder unknown），fail closed。"""


class ProfileStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class BrowserProfileRefV1:
    """digest-only 公开身份；没有 cookie/storage-state/account 原文的安放处。"""

    profile_id: str
    revision: int
    site_policy_digest: str
    account_label_digest: str
    browser_identity_digest: str
    status: ProfileStatus


@dataclass(frozen=True, slots=True)
class ProfileWriterLeaseV1:
    """一次 writer acquisition 的 immutable 身份（003）。

    ``profile`` 是在 acquisition 线性化点验证过的完整 snapshot；``lease_id``
    是本次 acquisition 的 32 位小写 hex nonce，与四字段 ``writer.lock``
    全等绑定。lease 只存在于 browser owner/store 内存与 owner-only lock
    中，不进入 model arguments、checkpoint、event 或 CLI 输出。
    """

    profile: BrowserProfileRefV1
    lease_id: str
    pid: int
    started_at: str


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """tri-state 进程身份：``exists=None`` 表示无法判定，绝不当作 dead。"""

    exists: bool | None
    started_at: str | None


class ProcessIdentityProbe(Protocol):
    """唯一的进程存在性/身份注入点；production 由构造注入默认实现。"""

    def probe(self, pid: int) -> ProcessIdentity: ...


class OsProcessIdentityProbe:
    """production probe：os.kill 探活 + 固定 ``/bin/ps`` 取 start identity。"""

    def probe(self, pid: int) -> ProcessIdentity:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # 唯一明确的“进程不存在”信号（ESRCH）。
            return ProcessIdentity(exists=False, started_at=None)
        except PermissionError:
            # EPERM 证明进程存在；identity 仍尝试读取。
            return ProcessIdentity(exists=True, started_at=self._lstart(pid))
        except OSError:
            return ProcessIdentity(exists=None, started_at=None)
        return ProcessIdentity(exists=True, started_at=self._lstart(pid))

    @staticmethod
    def _lstart(pid: int) -> str | None:
        # 固定绝对路径：不经过 PATH 解析，避免可执行文件被劫持。
        try:
            result = subprocess.run(
                ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() or None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_bounded_json(fd: int, *, limit: int, error: type[Exception]) -> object:
    """bounded、非阻塞的字节读取 + JSON 解码；超限/坏 JSON 都 fail closed。"""
    chunks = []
    total = 0
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise error("payload exceeds the bounded size")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as decode_error:
        raise error("payload is not valid JSON") from decode_error


class BrowserProfileStore:
    """persistent profile 的唯一 owner；所有操作都锚定在 owned root fd 上。"""

    def __init__(
        self,
        *,
        root: Path,
        process_probe: ProcessIdentityProbe | None = None,
    ) -> None:
        self._root = Path(root)
        self._probe: ProcessIdentityProbe = process_probe or OsProcessIdentityProbe()

    # ------------------------------------------------------------------ #
    # dirfd 锚定的 owned root / profile 目录
    # ------------------------------------------------------------------ #

    @contextlib.contextmanager
    def _owned_root_fd(self, *, create_if_missing: bool = False) -> Iterator[int]:
        try:
            fd = self._open_root()
        except FileNotFoundError:
            if not create_if_missing:
                raise ProfileNotFoundError("profile root missing") from None
            try:
                os.mkdir(self._root, 0o700)
            except FileExistsError:
                pass
            except OSError as error:
                raise ProfileIntegrityError("profile root cannot be created") from error
            try:
                fd = self._open_root()
            except OSError as error:
                raise ProfileIntegrityError("profile root must be a real directory") from error
        except OSError as error:
            raise ProfileIntegrityError("profile root must be a real directory") from error
        try:
            if os.fstat(fd).st_mode & 0o077:
                os.fchmod(fd, 0o700)
            yield fd
        finally:
            os.close(fd)

    def _open_root(self) -> int:
        # O_NOFOLLOW：root 是 symlink 时 ELOOP，绝不 follow。
        return os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    @contextlib.contextmanager
    def _profile_dir_fd(self, root_fd: int, profile_id: str) -> Iterator[int]:
        self._require_profile_id(profile_id)
        try:
            fd = os.open(
                profile_id,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
        except FileNotFoundError as error:
            raise ProfileNotFoundError(f"profile {profile_id!r} does not exist") from error
        except OSError as error:
            raise ProfileIntegrityError("profile directory must be a real directory") from error
        try:
            if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
                os.fchmod(fd, 0o700)
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def _require_profile_id(profile_id: str) -> None:
        if PROFILE_ID_PATTERN.fullmatch(profile_id) is None:
            raise ProfileNotFoundError(f"profile {profile_id!r} does not exist")

    # ------------------------------------------------------------------ #
    # metadata 读写（相对 profile fd）
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_metadata_fd(profile_fd: int) -> dict:
        # O_NONBLOCK + regular-file 校验：目录/FIFO 在读取前 fail closed，不阻塞。
        try:
            fd = os.open(
                METADATA_NAME,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=profile_fd,
            )
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise ProfileIntegrityError("metadata must not be a symlink") from error
            raise ProfileNotFoundError("profile metadata missing") from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ProfileIntegrityError("metadata must be a regular file")
            if stat.S_IMODE(info.st_mode) & 0o077:
                os.fchmod(fd, 0o600)
            payload = _read_bounded_json(
                fd, limit=MAX_METADATA_BYTES, error=ProfileIntegrityError
            )
        finally:
            os.close(fd)
        BrowserProfileStore._decode_metadata(payload)
        return payload

    @staticmethod
    def _decode_metadata(payload: object) -> None:
        # closed decode：exact keys、正 int（拒 bool/字符串/huge literal）、
        # 64 位小写 hex digest、opaque id pattern、exact status。
        if not isinstance(payload, dict) or set(payload) != METADATA_KEYS:
            raise ProfileIntegrityError("metadata keys are not the closed contract")
        if type(payload["revision"]) is not int or payload["revision"] <= 0:
            raise ProfileIntegrityError("revision must be a positive int")
        if not isinstance(payload["profile_id"], str):
            raise ProfileIntegrityError("profile_id must be a string")
        if PROFILE_ID_PATTERN.fullmatch(payload["profile_id"]) is None:
            raise ProfileIntegrityError("profile_id is not an opaque id")
        for key in (
            "site_policy_digest",
            "account_label_digest",
            "browser_identity_digest",
        ):
            value = payload[key]
            if not isinstance(value, str) or HEX64_PATTERN.fullmatch(value) is None:
                raise ProfileIntegrityError(f"{key} must be 64 lowercase hex chars")
        if not isinstance(payload["status"], str) or payload["status"] not in ProfileStatus:
            raise ProfileIntegrityError("status must be an exact member")

    @staticmethod
    def _ref_from_payload(payload: dict) -> BrowserProfileRefV1:
        try:
            return BrowserProfileRefV1(
                profile_id=payload["profile_id"],
                revision=int(payload["revision"]),
                site_policy_digest=payload["site_policy_digest"],
                account_label_digest=payload["account_label_digest"],
                browser_identity_digest=payload["browser_identity_digest"],
                status=ProfileStatus(payload["status"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProfileIntegrityError("profile metadata shape invalid") from error

    @staticmethod
    def _verify_reference(ref: BrowserProfileRefV1, current: BrowserProfileRefV1) -> None:
        # mutation/writer API 只接受与存储一致的完整 trusted ref；
        # forged digest/status 或 stale revision 都拒绝且零副作用。
        if (
            ref.profile_id != current.profile_id
            or ref.site_policy_digest != current.site_policy_digest
            or ref.account_label_digest != current.account_label_digest
            or ref.browser_identity_digest != current.browser_identity_digest
            or ref.status is not current.status
        ):
            raise ProfileIntegrityError("profile reference does not match stored identity")
        if ref.revision != current.revision:
            raise ProfileRevisionConflict("profile reference revision stale")

    def _cas_write_fd(
        self, profile_fd: int, *, expected_revision: int, new_payload: dict,
    ) -> None:
        # second open 也必须对实际持有的 fd 做 closed descriptor validation：
        # O_NONBLOCK（FIFO 不阻塞）、fstat S_ISREG、bounded read、closed decode。
        try:
            fd = os.open(
                METADATA_NAME,
                os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=profile_fd,
            )
        except OSError as error:
            raise ProfileIntegrityError("metadata not updatable") from error
        try:
            # S_ISREG 必须先于 flock：macOS 对 FIFO 的 flock 抛 EOPNOTSUPP。
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ProfileIntegrityError("metadata must be a regular file")
            if stat.S_IMODE(info.st_mode) & 0o077:
                os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError as error:
                raise ProfileIntegrityError("metadata cannot be locked") from error
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                current = _read_bounded_json(
                    fd, limit=MAX_METADATA_BYTES, error=ProfileIntegrityError
                )
                self._decode_metadata(current)
                if current.get("status") != ProfileStatus.ACTIVE.value:
                    raise ProfileRevokedError("profile is not active")
                if current.get("revision") != expected_revision:
                    raise ProfileRevisionConflict(
                        f"expected revision {expected_revision}, found {current.get('revision')}"
                    )
                encoded = json.dumps(new_payload, sort_keys=True).encode("utf-8")
                os.lseek(fd, 0, os.SEEK_SET)
                os.truncate(fd, 0)
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # ------------------------------------------------------------------ #
    # 公开生命周期 API
    # ------------------------------------------------------------------ #

    def create(
        self,
        *,
        site_policy_digest: str,
        account_label: str,
        browser_identity_digest: str,
    ) -> BrowserProfileRefV1:
        # 输入 digest 先按 closed metadata 合同验证，避免 create 返回一个
        # 随后无法通过 open decode 的自相矛盾 ref。
        for name, value in (
            ("site_policy_digest", site_policy_digest),
            ("browser_identity_digest", browser_identity_digest),
        ):
            if not isinstance(value, str) or HEX64_PATTERN.fullmatch(value) is None:
                raise ProfileIntegrityError(f"{name} must be 64 lowercase hex chars")
        with self._owned_root_fd(create_if_missing=True) as root_fd:
            profile_id = f"profile-{secrets.token_hex(8)}"
            try:
                os.mkdir(profile_id, 0o700, dir_fd=root_fd)
            except OSError as error:
                raise ProfileIntegrityError("cannot create profile directory") from error
            payload = {
                "profile_id": profile_id,
                "revision": 1,
                "site_policy_digest": site_policy_digest,
                "account_label_digest": _digest(account_label),
                "browser_identity_digest": browser_identity_digest,
                "status": ProfileStatus.ACTIVE.value,
            }
            with self._profile_dir_fd(root_fd, profile_id) as profile_fd:
                try:
                    fd = os.open(
                        METADATA_NAME,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=profile_fd,
                    )
                except OSError as error:
                    raise ProfileIntegrityError("cannot create profile metadata") from error
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
            return BrowserProfileRefV1(
                profile_id=profile_id,
                revision=1,
                site_policy_digest=site_policy_digest,
                account_label_digest=payload["account_label_digest"],
                browser_identity_digest=browser_identity_digest,
                status=ProfileStatus.ACTIVE,
            )

    def list_profile_ids(self) -> tuple[str, ...]:
        """公开的 opaque profile 枚举；只返回 canonical opaque ID。"""

        with self._owned_root_fd() as root_fd:
            import os as _os

            try:
                entries = _os.listdir(root_fd)
            except OSError as error:
                raise ProfileIntegrityError("profile root unreadable") from error
        return tuple(
            sorted(
                entry
                for entry in entries
                if PROFILE_ID_PATTERN.fullmatch(entry) is not None
            )
        )

    def open(self, profile_id: str) -> BrowserProfileRefV1:
        # 参加同一 per-profile 短临界区：guard 内读到的 metadata snapshot 与
        # mutation/acquisition 有明确线性化顺序。
        with self._owned_root_fd() as root_fd:
            self._require_profile_id(profile_id)
            # 非权威预筛：失败查询不创建 guard，保持 root 零 mutation。
            # 预筛与 guard 之间的创建竞态仍由 guard 内 _profile_dir_fd 的
            # 权威失败兜底，这里不引入第二套协议。
            try:
                os.stat(profile_id, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError as error:
                raise ProfileNotFoundError(
                    f"profile {profile_id!r} does not exist"
                ) from error
            except OSError:
                pass
            with (
                self._serialized(root_fd, profile_id),
                self._profile_dir_fd(root_fd, profile_id) as profile_fd,
            ):
                payload = self._read_metadata_fd(profile_fd)
                ref = self._ref_from_payload(payload)
                if ref.profile_id != profile_id:
                    raise ProfileIntegrityError("profile metadata identity mismatch")
                return ref

    def advance_revision(
        self,
        lease: ProfileWriterLeaseV1,
        *,
        expected_revision: int,
    ) -> BrowserProfileRefV1:
        """takeover completion 专用：只有原 session 的 exact lease 能推进一次。

        guard 内要求当前调用进程、lock nonce/owner/acquired revision、lease
        snapshot immutable identity 与 ACTIVE metadata 全部匹配；
        ``expected_revision`` 必须等于 acquisition revision。当前 revision 为
        ``r`` 时 CAS 到 ``r+1``；仍由同一 lease 调用且当前已是 ``r+1`` 时
        幂等返回；其他情况拒绝。
        """
        with (
            self._owned_root_fd() as root_fd, self._serialized(root_fd, lease.profile.profile_id),
            self._profile_dir_fd(root_fd, lease.profile.profile_id) as profile_fd,
        ):
            payload = self._read_metadata_fd(profile_fd)
            current = self._ref_from_payload(payload)
            self._verify_lease_snapshot(lease, current)
            if expected_revision != lease.profile.revision:
                raise ProfileRevisionConflict(
                    "expected revision must equal the acquisition revision"
                )
            self._require_lease_owns_lock(profile_fd, lease)
            if current.revision == expected_revision + 1:
                return current  # 同一 lease 已完成的幂等重试
            if current.revision != expected_revision:
                raise ProfileRevisionConflict(
                    f"expected revision {expected_revision}, "
                    f"found {current.revision}"
                )
            self._cas_write_fd(
                profile_fd,
                expected_revision=expected_revision,
                new_payload={**payload, "revision": expected_revision + 1},
            )
            return replace(current, revision=expected_revision + 1)

    def revoke(self, ref: BrowserProfileRefV1) -> BrowserProfileRefV1:
        with (
            self._owned_root_fd() as root_fd, self._serialized(root_fd, ref.profile_id),
            self._profile_dir_fd(root_fd, ref.profile_id) as profile_fd,
        ):
            payload = self._read_metadata_fd(profile_fd)
            current = self._ref_from_payload(payload)
            self._verify_reference(ref, current)
            self._require_no_live_writer(profile_fd)
            self._cas_write_fd(
                profile_fd,
                expected_revision=current.revision,
                new_payload={**payload, "status": ProfileStatus.REVOKED.value},
            )
            return replace(current, status=ProfileStatus.REVOKED)

    # ------------------------------------------------------------------ #
    # writer lock（tri-state probe；只有明确 dead 才允许 takeover）
    # ------------------------------------------------------------------ #

    @contextlib.contextmanager
    def _serialized(self, root_fd: int, profile_id: str) -> Iterator[None]:
        """per-profile 唯一短临界区（003 协议）。

        所有 lifecycle/writer 操作（open/acquire_writer/release_writer/
        advance_revision/revoke/clear）都按 ``owned root fd → root 级 guard →
        canonical profile dir fd → metadata/writer.lock`` 的固定顺序穿过
        同一个 guard，从而在同 profile 的 mutation 与 writer acquisition
        之间建立明确的线性化顺序。guard 锢定在 owned root（``guard-<profile_id>``）
        而不是 profile 目录：clear 删除 profile 内容不会删除 guard，因此同
        profile 的所有临界区永远竞争同一 inode。guard 不携带任何 authority，
        也不跨浏览器启动或用户 takeover 长期持有；持 guard 期间绝不等待
        另一个 guard actor。clear 成功后残留为 root 级空 0600 文件，由
        root 生命周期管理。
        """
        self._require_profile_id(profile_id)
        guard_name = f"guard-{profile_id}"
        fd = self._open_guard_fd(root_fd, guard_name)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ProfileLockUnknownError("guard must be a regular file")
            if stat.S_IMODE(info.st_mode) & 0o077:
                os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError as error:
                raise ProfileLockUnknownError("guard cannot be locked") from error
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    @staticmethod
    def _open_guard_fd(root_fd: int, guard_name: str) -> int:
        # macOS 的 openat(dir_fd, O_CREAT) 在多进程竞争同一 guard 名时会短暂
        # 返回 ENOENT（APFS 名字查找竞态；root fd 已验证有效，guard 只增不删）。
        # 这里做的是 syscall 级有界重试，不是协议层自动重试：guard 只是临界区
        # 入口，不携带任何 authority，重试不会扩大效果面。
        last_error: OSError | None = None
        for attempt in range(8):
            try:
                return os.open(
                    guard_name,
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=root_fd,
                )
            except FileNotFoundError as error:
                last_error = error
                time.sleep(0.01 * (attempt + 1))
            except OSError as error:
                raise ProfileLockUnknownError("guard unreadable") from error
        raise ProfileLockUnknownError("guard unreadable") from last_error

    def acquire_writer(self, expected_ref: BrowserProfileRefV1) -> ProfileWriterLeaseV1:
        # self identity probe 在 guard 外完成：guard 内不做任何可停靠的
        # 进程探测，避免持锁等待；acquisition 线性化点在 guard 内。
        my_pid = os.getpid()
        mine = self._probe.probe(my_pid)
        if mine.exists is not True or mine.started_at is None:
            raise ProfileLockUnknownError("cannot determine current process identity")
        with (
            self._owned_root_fd() as root_fd, self._serialized(root_fd, expected_ref.profile_id),
            self._profile_dir_fd(root_fd, expected_ref.profile_id) as profile_fd,
        ):
            current = self._ref_from_payload(self._read_metadata_fd(profile_fd))
            self._verify_reference(expected_ref, current)
            if current.status is not ProfileStatus.ACTIVE:
                raise ProfileRevokedError("profile is revoked")
            if self._lock_exists(profile_fd):
                lock = self._read_lock_fd(profile_fd)
                self._assert_lock_takeover(
                    lock["pid"], lock["started_at"], my_pid, mine.started_at
                )
                try:
                    os.unlink(LOCK_NAME, dir_fd=profile_fd)
                except OSError as error:
                    raise ProfileLockUnknownError(
                        "cannot replace stale lock"
                    ) from error
            lease_id = secrets.token_hex(16)
            self._create_lock_fd(
                profile_fd,
                my_pid,
                mine.started_at,
                lease_id=lease_id,
                acquired_revision=current.revision,
            )
            return ProfileWriterLeaseV1(
                profile=current,
                lease_id=lease_id,
                pid=my_pid,
                started_at=mine.started_at,
            )

    def _assert_lock_takeover(
        self, lock_pid: int, lock_start: str, my_pid: int, my_start: str,
    ) -> None:
        if lock_pid == my_pid:
            if lock_start == my_start:
                raise ProfileLockHeldError("writer lock already held")
            # 同 pid 但 start identity 不符：无法区分损坏与 pid 复用，fail closed。
            raise ProfileLockUnknownError("lock identity mismatch for current pid")
        holder = self._probe.probe(lock_pid)
        if holder.exists is False:
            return  # 明确 ESRCH/nonexistent：唯一允许 stale takeover 的分支
        if holder.exists is None:
            raise ProfileLockUnknownError("holder existence unknown")
        if holder.started_at is None:
            raise ProfileLockUnknownError("holder start identity unknown")
        if holder.started_at == lock_start:
            raise ProfileLockHeldError("writer lock held by a live process")
        return  # pid 已被新进程复用，旧持锁人已消失

    @staticmethod
    def _lock_exists(profile_fd: int) -> bool:
        # 只有 ENOENT 表示“无锁”；其余 OSError（权限/IO 错误）说明锁状态
        # 不可判定，必须 fail closed 为 unknown，不得当作锁存在或不存在。
        try:
            os.stat(LOCK_NAME, dir_fd=profile_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ProfileLockUnknownError("lock existence unknown") from error
        return True

    @staticmethod
    def _read_lock_fd(profile_fd: int) -> dict:
        try:
            fd = os.open(
                LOCK_NAME,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=profile_fd,
            )
        except OSError as error:
            raise ProfileLockUnknownError("lock unreadable") from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ProfileLockUnknownError("lock must be a regular file")
            if stat.S_IMODE(info.st_mode) & 0o077:
                os.fchmod(fd, 0o600)
            payload = _read_bounded_json(
                fd, limit=MAX_LOCK_BYTES, error=ProfileLockUnknownError
            )
        finally:
            os.close(fd)
        if (
            not isinstance(payload, dict)
            or set(payload) != LOCK_KEYS
            or type(payload["pid"]) is not int
            or payload["pid"] <= 0
            or not isinstance(payload["started_at"], str)
            or not payload["started_at"]
            or not isinstance(payload["lease_id"], str)
            or LEASE_ID_PATTERN.fullmatch(payload["lease_id"]) is None
            or type(payload["acquired_revision"]) is not int
            or payload["acquired_revision"] <= 0
        ):
            raise ProfileLockUnknownError("lock identity malformed")
        return payload

    @staticmethod
    def _create_lock_fd(
        profile_fd: int,
        my_pid: int,
        my_start: str,
        *,
        lease_id: str,
        acquired_revision: int,
    ) -> None:
        try:
            fd = os.open(
                LOCK_NAME,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=profile_fd,
            )
        except FileExistsError as error:
            # 只有明确的“名字已被占用”才表示 held；其余 OSError（权限/IO）
            # 是锁状态不可判定，不得伪装成“另一 writer 刚抢到”。
            raise ProfileLockHeldError("lock acquired concurrently") from error
        except OSError as error:
            raise ProfileLockUnknownError("lock cannot be created") from error
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "pid": my_pid,
                        "started_at": my_start,
                        "lease_id": lease_id,
                        "acquired_revision": acquired_revision,
                    },
                    handle,
                    sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            # 写入确认失败：lock 内容已不可判定，既不是成功 acquisition 也不
            # 能 best-effort unlink 不确定状态；交由既有 unknown/takeover 判定。
            raise ProfileLockUnknownError(
                "lock write could not be confirmed"
            ) from error

    def release_writer(self, lease: ProfileWriterLeaseV1) -> None:
        # 迟来的 release（clear 已删 canonical root 等）必须是安全 no-op；
        # 只有四字段与 exact lease 全等的 lock 才允许删除，因此迟到的旧
        # lease 永远不会删除同 profile 后续 acquisition 的锁（消除 ABA）。
        try:
            with (
                self._owned_root_fd() as root_fd,
                self._serialized(root_fd, lease.profile.profile_id),
                self._profile_dir_fd(
                    root_fd, lease.profile.profile_id
                ) as profile_fd,
            ):
                if not self._lock_exists(profile_fd):
                    return
                try:
                    lock = self._read_lock_fd(profile_fd)
                except ProfileLockUnknownError:
                    return
                if (
                    lock["pid"] == lease.pid
                    and lock["started_at"] == lease.started_at
                    and lock["lease_id"] == lease.lease_id
                    and lock["acquired_revision"] == lease.profile.revision
                ):
                    with contextlib.suppress(OSError):
                        os.unlink(LOCK_NAME, dir_fd=profile_fd)
        except (ProfileNotFoundError, ProfileIntegrityError):
            return

    def _require_no_live_writer(self, profile_fd: int) -> None:
        """mutation 前置：live writer → busy；unknown → fail closed。

        只有无 writer 或 confirmed-stale writer 被安全移除后才允许 mutation；
        active mutation 不删除 lock/profile/浏览器数据。
        """
        if not self._lock_exists(profile_fd):
            return
        lock = self._read_lock_fd(profile_fd)
        my_pid = os.getpid()
        mine = self._probe.probe(my_pid)
        if mine.exists is not True or mine.started_at is None:
            raise ProfileLockUnknownError("cannot determine current process identity")
        self._assert_lock_takeover(lock["pid"], lock["started_at"], my_pid, mine.started_at)
        try:
            os.unlink(LOCK_NAME, dir_fd=profile_fd)
        except OSError as error:
            raise ProfileLockUnknownError("cannot remove stale lock") from error

    @staticmethod
    def _verify_lease_snapshot(
        lease: ProfileWriterLeaseV1, current: BrowserProfileRefV1
    ) -> None:
        # lease 携带 acquisition 线性化点验证过的 immutable snapshot；
        # digest/profile_id 任一漂移都说明 lease 不再描述这份 metadata。
        if (
            lease.profile.profile_id != current.profile_id
            or lease.profile.site_policy_digest != current.site_policy_digest
            or lease.profile.account_label_digest != current.account_label_digest
            or lease.profile.browser_identity_digest != current.browser_identity_digest
        ):
            raise ProfileIntegrityError("lease snapshot does not match stored identity")
        # acquire_writer 只会发出 ACTIVE snapshot；status 非 ACTIVE 的
        # lease 必然是伪造的 acquisition 身份。
        if lease.profile.status is not ProfileStatus.ACTIVE:
            raise ProfileRevokedError("lease snapshot is not active")
        if current.status is not ProfileStatus.ACTIVE:
            raise ProfileRevokedError("profile is not active")

    def _require_lease_owns_lock(
        self, profile_fd: int, lease: ProfileWriterLeaseV1
    ) -> None:
        # ownerless advance 已删除：lock 必须由当前调用进程按 exact lease
        # 持有（nonce/owner/acquired revision 全等），否则拒绝。
        if not self._lock_exists(profile_fd):
            raise ProfileLockUnknownError("writer lease has no live writer lock")
        lock = self._read_lock_fd(profile_fd)
        if (
            lease.pid != os.getpid()
            or lock["pid"] != lease.pid
            or lock["started_at"] != lease.started_at
            or lock["lease_id"] != lease.lease_id
            or lock["acquired_revision"] != lease.profile.revision
        ):
            raise ProfileLockUnknownError("writer lock does not match the lease")

    # ------------------------------------------------------------------ #
    # clear / quarantine
    # ------------------------------------------------------------------ #

    def clear(self, ref: BrowserProfileRefV1) -> BrowserCleanupOutcome:
        # 003 协议：root fd → guard → profile fd 全程同一短临界区。writer
        # 判定先于 metadata 读取：live writer → ProfileLockHeldError（不删
        # lock/profile，也不返 CLEANED）；unknown/corrupt writer →
        # ProfileLockUnknownError；两者都不 quarantine。无 writer 或
        # confirmed-stale writer 被安全移除后，corrupt metadata 仍保持既有
        # CLEANUP_UNKNOWN + quarantine 语义。
        with self._owned_root_fd() as root_fd:
            self._require_profile_id(ref.profile_id)
            with self._serialized(root_fd, ref.profile_id):
                try:
                    info = os.stat(ref.profile_id, dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError as error:
                    raise ProfileNotFoundError(
                        f"profile {ref.profile_id!r} does not exist"
                    ) from error
                if not stat.S_ISDIR(info.st_mode):
                    return self._quarantine(root_fd, ref.profile_id)
                # phase 1：同 fd 内先判 writer（live/unknown 优先于 metadata
                # 可读性，不得把活跃 writer 的 profile 连同 writer.lock 一起
                # quarantine 掉），再读 metadata（fs 不确定 → quarantine）。
                try:
                    with self._profile_dir_fd(root_fd, ref.profile_id) as profile_fd:
                        self._require_no_live_writer(profile_fd)
                        payload = self._read_metadata_fd(profile_fd)
                        current = self._ref_from_payload(payload)
                except (ProfileIntegrityError, ProfileNotFoundError):
                    return self._quarantine(root_fd, ref.profile_id)
                # phase 2：caller ref 校验（forged → 拒绝，不触碰文件系统）。
                self._verify_reference(ref, current)
                # phase 3：先 revoke（关闭 writer 语义），再删 canonical owned
                # root；already-revoked 的 clear 直接安全删除——revoke 已持久化
                # 过。guard 覆盖最终 rmdir，late contender 无法在 tree 已清空、
                # guard 已释放但 canonical directory 尚未删除的窗口重建 lock。
                try:
                    with self._profile_dir_fd(root_fd, ref.profile_id) as profile_fd:
                        self._require_no_live_writer(profile_fd)
                        if current.status is ProfileStatus.ACTIVE:
                            self._cas_write_fd(
                                profile_fd,
                                expected_revision=current.revision,
                                new_payload={
                                    **payload,
                                    "status": ProfileStatus.REVOKED.value,
                                },
                            )
                        self._remove_tree_fd(profile_fd)
                    os.rmdir(ref.profile_id, dir_fd=root_fd)
                except (
                    ProfileIntegrityError,
                    ProfileRevisionConflict,
                    ProfileRevokedError,
                    OSError,
                ):
                    return self._quarantine(root_fd, ref.profile_id)
                return BrowserCleanupOutcome.CLEANED

    def _quarantine(self, root_fd: int, profile_id: str) -> BrowserCleanupOutcome:
        # quarantine 只 rename canonical 名（symlink 也只移动 link 本身），
        # 绝不 follow、绝不删除 owned root 之外的任何内容。
        try:
            os.mkdir(QUARANTINE_NAME, 0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        except OSError:
            return BrowserCleanupOutcome.CLEANUP_UNKNOWN
        try:
            quarantine_fd = os.open(
                QUARANTINE_NAME,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
        except OSError:
            # _quarantine 已是 symlink/非目录：绝不把 canonical rename 进去。
            return BrowserCleanupOutcome.CLEANUP_UNKNOWN
        try:
            if os.fstat(quarantine_fd).st_mode & 0o077:
                os.fchmod(quarantine_fd, 0o700)
            target = f"{profile_id}-{secrets.token_hex(4)}"
            # canonical 可能残留；仍如实报告 UNKNOWN。
            with contextlib.suppress(OSError):
                os.rename(
                    profile_id, target, src_dir_fd=root_fd, dst_dir_fd=quarantine_fd,
                )
        finally:
            os.close(quarantine_fd)
        return BrowserCleanupOutcome.CLEANUP_UNKNOWN

    @staticmethod
    def _remove_tree_fd(dir_fd: int) -> None:
        # 相对 dir_fd 递归删除；symlink 一律按 link 本身 unlink，绝不 follow。
        for entry in list(os.scandir(dir_fd)):
            if entry.is_dir(follow_symlinks=False):
                child = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=dir_fd,
                )
                try:
                    BrowserProfileStore._remove_tree_fd(child)
                finally:
                    os.close(child)
                os.rmdir(entry.name, dir_fd=dir_fd)
            else:
                os.unlink(entry.name, dir_fd=dir_fd)

"""Durable MCP safety latch。

显式 ``--mcp-safety-state PATH`` 的 owner-only/no-follow 跨进程 CAS 状态机：
``CLEAR``（无 marker）↔ ``ARMED``。每次 invocation 在 Runtime 已持久化 ``EXECUTING`` 后、
spawn 前 arm；只有匹配 full binding 的 owner 在整个 process group 确认退出后才能 clear。
unresolved marker 让下一次 composition fail closed；``ResolveUnknownToolOutcome`` 只能
分类当前 effect，不能清除 latch。它不保存 agent cursor/result。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path

_LOCK_DEADLINE_SECONDS = 5.0


class SafetyLatchError(RuntimeError):
    """latch 操作违反（已 ARMED、revision 冲突、锁超时等）。"""


@dataclass(frozen=True, slots=True)
class LatchBinding:
    server_id: str
    config_digest: str
    credential_profile: str | None
    safety_generation: str
    intent_digest: str

    def digest(self) -> str:
        payload = json.dumps(
            {
                "server_id": self.server_id,
                "config_digest": self.config_digest,
                "credential_profile": self.credential_profile,
                "safety_generation": self.safety_generation,
                "intent_digest": self.intent_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class McpLatchState:
    status: str  # "clear" | "armed"
    revision: int
    token: str
    binding_digest: str


class McpSafetyLatch:
    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._lock_path = state_path.with_suffix(state_path.suffix + ".lock")
        self._ensure_directory()

    def status(self) -> str:
        state = self._read_unsafe()
        if state is None or state.status == "clear":
            return "clear"
        return "armed"

    def snapshot(self) -> McpLatchState | None:
        return self._read_unsafe()

    def require_clear_for_composition(self) -> None:
        if self.status() == "armed":
            raise SafetyLatchError("unresolved armed marker; resolve via operator recovery")

    def arm(self, *, expected_clear_revision: int, binding: LatchBinding) -> str:
        with self._locked():
            state = self._read_unsafe()
            current_revision = state.revision if state is not None else 0
            if state is not None and state.status == "armed":
                raise SafetyLatchError("latch is already armed")
            if current_revision != expected_clear_revision:
                raise SafetyLatchError("latch revision mismatch")
            token = secrets.token_hex(16)
            self._write(
                {
                    "status": "armed",
                    "revision": current_revision + 1,
                    "token": token,
                    "binding_digest": binding.digest(),
                }
            )
            return token

    def clear(self, *, revision: int, token: str, binding: LatchBinding) -> bool:
        with self._locked():
            state = self._read_unsafe()
            if state is None or state.status != "armed":
                return False
            if (
                state.revision != revision
                or state.token != token
                or state.binding_digest != binding.digest()
            ):
                return False
            self._write(
                {
                    "status": "clear",
                    "revision": state.revision + 1,
                    "token": "",
                    "binding_digest": "",
                }
            )
            return True

    def force_clear(
        self,
        *,
        revision: int,
        token: str,
        binding: LatchBinding,
        process_terminated: bool,
        credential_rotated: bool = False,
    ) -> bool:
        """operator-only recovery clear：精确 CAS + process attestation + rotation attestation。

        系统记录 attestation，但不声称自动验证外部事实（R9/A6）。所有 attestation 默认否定：
        process_terminated 与 credential_rotated 都必须由 operator 显式肯定才能推进（设计
        MCP_DESIGN.md:226），遗漏 rotation 参数不能默认以虚假肯定清除 credential-bearing marker。
        """
        with self._locked():
            state = self._read_unsafe()
            if state is None or state.status != "armed":
                return False
            if (
                state.revision != revision
                or state.token != token
                or state.binding_digest != binding.digest()
            ):
                return False
            if not process_terminated:
                return False
            if binding.credential_profile is not None and not credential_rotated:
                return False
            self._write(
                {
                    "status": "clear",
                    "revision": state.revision + 1,
                    "token": "",
                    "binding_digest": "",
                    "recovery_attestation": True,
                }
            )
            return True

    def _ensure_directory(self) -> None:
        directory = self._path.parent
        if not directory.exists():
            directory.mkdir(parents=True, mode=0o700)
        elif directory.stat().st_mode & 0o077:
            raise SafetyLatchError("safety latch directory must be owner-only")

    def _read_unsafe(self) -> McpLatchState | None:
        try:
            fd = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise SafetyLatchError("safety latch must be a regular file")
            if info.st_mode & 0o077:
                raise SafetyLatchError("safety latch must be owner-only")
            raw = b""
            while True:
                chunk = os.read(fd, 65_536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > 10_000:
                    raise SafetyLatchError("safety latch file exceeds bound")
        finally:
            os.close(fd)
        if not raw:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SafetyLatchError("safety latch file is malformed") from error
        if not isinstance(data, dict):
            raise SafetyLatchError("safety latch file is malformed")
        status = data.get("status")
        if status not in ("clear", "armed"):
            raise SafetyLatchError("safety latch status is unsupported")
        return McpLatchState(
            status=status,
            revision=int(data.get("revision", 0)),
            token=str(data.get("token", "")),
            binding_digest=str(data.get("binding_digest", "")),
        )

    def _write(self, payload: dict[str, object]) -> None:
        directory = self._path.parent
        tmp_path = directory / f"{self._path.name}.tmp"
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        fd = os.open(
            tmp_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_path, self._path)
        # fsync 目录使原子替换在崩溃后仍可见。
        dir_fd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    @contextlib.contextmanager
    def _locked(self):
        import fcntl

        deadline = time.monotonic() + _LOCK_DEADLINE_SECONDS
        self._lock_path.touch(mode=0o600, exist_ok=True)
        lock_fd = os.open(self._lock_path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise SafetyLatchError(
                            "safety latch lock deadline exceeded"
                        ) from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

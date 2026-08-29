"""Exact macOS launchd cold-wake adapter for the optional 019 host profile."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import pwd
import re
import stat
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from agent.automation.wake import (
    WakeInstallOutcome,
    WakeInstallResultV1,
    WakeReadbackOutcome,
    WakeReadbackV1,
    WakeRemoveOutcome,
    WakeRemoveResultV1,
)
from agent.automation_hosts._posix_fs import (
    DIRECTORY,
    NOFOLLOW,
    NONBLOCK,
    PosixWorkspaceStorageError,
    absolute_unresolved,
    ensure_owner_directory,
    owner_uid,
    read_owner_file_at,
    reject_symlink_components,
    write_new_owner_file_at,
)
from agent.runtime.contracts import canonical_json_digest

LAUNCHD_PRODUCT_LABEL = "com.my-first-agent.schedule"
LAUNCHD_E3_LABEL = "com.my-first-agent.schedule.e3"
_E3_LABEL = re.compile(r"^com\.my-first-agent\.schedule\.e3\.[0-9a-f]{12}$")
_LAUNCHCTL = "/bin/launchctl"
_MIN_INTERVAL_SECONDS = 15
_MAX_INTERVAL_SECONDS = 3_600
_MAX_PLIST_BYTES = 16_384
_MAX_LEDGER_BYTES = 4_096
_MAX_EXECUTABLE_BYTES = 64 * 1024 * 1024


class LaunchdCommandOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    NOT_EXECUTED = "not_executed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LaunchdCommandResultV1:
    outcome: LaunchdCommandOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, LaunchdCommandOutcome):
            raise ValueError("outcome must use LaunchdCommandOutcome")


@dataclass(frozen=True, slots=True)
class LaunchdConfigurationV1:
    installed_executable: Path
    launch_agents_root: Path
    state_root: Path
    start_interval_seconds: int
    policy_digest: str
    label: str = LAUNCHD_PRODUCT_LABEL
    executable_identity_digest: str = ""
    launch_agents_root_identity_digest: str = ""
    state_root_identity_digest: str = ""
    configuration_digest: str = ""

    def __post_init__(self) -> None:
        if self.label not in {LAUNCHD_PRODUCT_LABEL, LAUNCHD_E3_LABEL} and not (
            isinstance(self.label, str) and _E3_LABEL.fullmatch(self.label)
        ):
            raise ValueError("label must be one of the fixed product labels")
        if (
            isinstance(self.start_interval_seconds, bool)
            or not isinstance(self.start_interval_seconds, int)
            or not _MIN_INTERVAL_SECONDS
            <= self.start_interval_seconds
            <= _MAX_INTERVAL_SECONDS
        ):
            raise ValueError("start_interval_seconds is outside the closed bound")
        _require_digest(self.policy_digest)
        executable = _qualified_executable(self.installed_executable)
        launch_agents_root = _qualified_directory(
            self.launch_agents_root,
            label="launch_agents_root",
            exact_owner_mode=False,
        )
        state_root = absolute_unresolved(self.state_root)
        ensure_owner_directory(state_root)
        executable_identity = _executable_identity(executable)
        launch_agents_identity = _directory_identity(launch_agents_root)
        state_identity = _directory_identity(state_root)
        object.__setattr__(self, "installed_executable", executable)
        object.__setattr__(self, "launch_agents_root", launch_agents_root)
        object.__setattr__(self, "state_root", state_root)
        for supplied, actual, name in (
            (
                self.executable_identity_digest,
                executable_identity,
                "executable_identity_digest",
            ),
            (
                self.launch_agents_root_identity_digest,
                launch_agents_identity,
                "launch_agents_root_identity_digest",
            ),
            (
                self.state_root_identity_digest,
                state_identity,
                "state_root_identity_digest",
            ),
        ):
            if supplied and supplied != actual:
                raise ValueError(f"{name} mismatch")
            object.__setattr__(self, name, actual)
        digest = canonical_json_digest(
            {
                "executable_identity_digest": executable_identity,
                "installed_executable": os.fspath(executable),
                "label": self.label,
                "launch_agents_root_identity_digest": launch_agents_identity,
                "policy_digest": self.policy_digest,
                "start_interval_seconds": self.start_interval_seconds,
                "state_root_identity_digest": state_identity,
            }
        )
        if self.configuration_digest and self.configuration_digest != digest:
            raise ValueError("configuration_digest mismatch")
        object.__setattr__(self, "configuration_digest", digest)


class _LedgerPhase(StrEnum):
    INSTALL_PENDING = "install_pending"
    INSTALLED = "installed"
    REMOVE_PENDING = "remove_pending"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class _LedgerV1:
    phase: _LedgerPhase
    configuration_digest: str
    policy_digest: str
    plist_digest: str


CommandRunner = Callable[[tuple[str, ...], float], LaunchdCommandResultV1]


def standard_user_launch_agents_root(*, uid: int | None = None) -> Path:
    """Return launchd's documented per-user agent directory for one local account."""

    account_uid = owner_uid() if uid is None else uid
    if isinstance(account_uid, bool) or not isinstance(account_uid, int) or account_uid < 0:
        raise ValueError("uid must be a non-negative int")
    account = pwd.getpwuid(account_uid)
    home = Path(account.pw_dir)
    if not home.is_absolute():
        raise ValueError("account home must be absolute")
    return home / "Library" / "LaunchAgents"


class LaunchdWakeAdapter:
    """One fixed LaunchAgent; all lifecycle uncertainty is durable and fail-closed."""

    def __init__(
        self,
        configuration: LaunchdConfigurationV1,
        *,
        command_runner: CommandRunner | None = None,
        worker_running: Callable[[], bool] | None = None,
    ) -> None:
        if not isinstance(configuration, LaunchdConfigurationV1):
            raise TypeError("configuration must use LaunchdConfigurationV1")
        self._configuration = configuration
        self._command_runner = command_runner or _run_launchctl
        self._worker_running = worker_running or (lambda: False)
        self._plist_payload = self.render(configuration)
        self._plist_digest = _sha256(self._plist_payload)
        self.plist_path = (
            configuration.launch_agents_root / f"{configuration.label}.plist"
        )
        self._ledger_path = configuration.state_root / "launchd-wake.json"

    @property
    def configured_policy_digest(self) -> str:
        return self._configuration.policy_digest

    @staticmethod
    def render(configuration: LaunchdConfigurationV1) -> bytes:
        if not isinstance(configuration, LaunchdConfigurationV1):
            raise TypeError("configuration must use LaunchdConfigurationV1")
        return plistlib.dumps(
            {
                "Label": configuration.label,
                "ProgramArguments": [
                    os.fspath(configuration.installed_executable),
                    "reconcile",
                ],
                "RunAtLoad": False,
                "StartInterval": configuration.start_interval_seconds,
            },
            fmt=plistlib.FMT_XML,
            sort_keys=True,
        )

    def readback(self, policy_digest: str) -> WakeReadbackV1:
        _require_digest(policy_digest)
        if policy_digest != self.configured_policy_digest:
            return self._readback_result(WakeReadbackOutcome.DRIFT, policy_digest)
        if not self._configuration_is_current():
            return self._readback_result(WakeReadbackOutcome.DRIFT, policy_digest)
        try:
            ledger = self._read_ledger()
            on_disk_digest = self._read_plist_digest()
        except (OSError, PosixWorkspaceStorageError, ValueError):
            return self._readback_result(WakeReadbackOutcome.UNKNOWN, policy_digest)
        if ledger is None:
            outcome = (
                WakeReadbackOutcome.ABSENT
                if on_disk_digest is None
                else WakeReadbackOutcome.UNKNOWN
            )
        elif not self._ledger_matches_configuration(ledger):
            outcome = WakeReadbackOutcome.DRIFT
        elif ledger.phase is _LedgerPhase.INSTALLED:
            outcome = (
                WakeReadbackOutcome.INSTALLED
                if on_disk_digest == self._plist_digest
                else WakeReadbackOutcome.DRIFT
            )
        elif ledger.phase is _LedgerPhase.REMOVED:
            outcome = (
                WakeReadbackOutcome.ABSENT
                if on_disk_digest is None
                else WakeReadbackOutcome.DRIFT
            )
        else:
            outcome = WakeReadbackOutcome.UNKNOWN
        return self._readback_result(outcome, policy_digest)

    def install(self, policy_digest: str) -> WakeInstallResultV1:
        readback = self.readback(policy_digest)
        if readback.outcome is WakeReadbackOutcome.INSTALLED:
            return self._install_result(WakeInstallOutcome.INSTALLED, policy_digest)
        if readback.outcome is not WakeReadbackOutcome.ABSENT:
            return self._install_result(WakeInstallOutcome.UNKNOWN, policy_digest)
        pending = self._ledger(_LedgerPhase.INSTALL_PENDING)
        try:
            self._write_ledger(pending)
            self._install_plist()
        except (OSError, PosixWorkspaceStorageError, ValueError):
            return self._install_result(WakeInstallOutcome.UNKNOWN, policy_digest)
        command = self._call_launchctl(
            (
                _LAUNCHCTL,
                "bootstrap",
                f"gui/{owner_uid()}",
                os.fspath(self.plist_path),
            )
        )
        if command.outcome is LaunchdCommandOutcome.UNKNOWN:
            return self._install_result(WakeInstallOutcome.UNKNOWN, policy_digest)
        if command.outcome is LaunchdCommandOutcome.NOT_EXECUTED:
            try:
                self._unlink_exact_plist()
                self._write_ledger(self._ledger(_LedgerPhase.REMOVED))
            except (OSError, PosixWorkspaceStorageError, ValueError):
                return self._install_result(WakeInstallOutcome.UNKNOWN, policy_digest)
            return self._install_result(WakeInstallOutcome.FAILED, policy_digest)
        try:
            self._write_ledger(self._ledger(_LedgerPhase.INSTALLED))
        except (OSError, PosixWorkspaceStorageError, ValueError):
            return self._install_result(WakeInstallOutcome.UNKNOWN, policy_digest)
        return self._install_result(WakeInstallOutcome.INSTALLED, policy_digest)

    def remove(self, policy_digest: str) -> WakeRemoveResultV1:
        _require_digest(policy_digest)
        if self._worker_running():
            return self._remove_result(WakeRemoveOutcome.BUSY, policy_digest)
        readback = self.readback(policy_digest)
        if readback.outcome is WakeReadbackOutcome.ABSENT:
            return self._remove_result(WakeRemoveOutcome.REMOVED, policy_digest)
        if readback.outcome is not WakeReadbackOutcome.INSTALLED:
            return self._remove_result(WakeRemoveOutcome.UNKNOWN, policy_digest)
        try:
            self._write_ledger(self._ledger(_LedgerPhase.REMOVE_PENDING))
        except (OSError, PosixWorkspaceStorageError, ValueError):
            return self._remove_result(WakeRemoveOutcome.UNKNOWN, policy_digest)
        command = self._call_launchctl(
            (
                _LAUNCHCTL,
                "bootout",
                f"gui/{owner_uid()}",
                os.fspath(self.plist_path),
            )
        )
        if command.outcome is LaunchdCommandOutcome.UNKNOWN:
            return self._remove_result(WakeRemoveOutcome.UNKNOWN, policy_digest)
        if command.outcome is LaunchdCommandOutcome.NOT_EXECUTED:
            try:
                self._write_ledger(self._ledger(_LedgerPhase.INSTALLED))
            except (OSError, PosixWorkspaceStorageError, ValueError):
                return self._remove_result(WakeRemoveOutcome.UNKNOWN, policy_digest)
            return self._remove_result(WakeRemoveOutcome.FAILED, policy_digest)
        try:
            self._unlink_exact_plist()
            self._write_ledger(self._ledger(_LedgerPhase.REMOVED))
        except (OSError, PosixWorkspaceStorageError, ValueError):
            return self._remove_result(WakeRemoveOutcome.UNKNOWN, policy_digest)
        return self._remove_result(WakeRemoveOutcome.REMOVED, policy_digest)

    def _call_launchctl(self, argv: tuple[str, ...]) -> LaunchdCommandResultV1:
        try:
            result = self._command_runner(argv, 10.0)
        except Exception:
            return LaunchdCommandResultV1(LaunchdCommandOutcome.UNKNOWN)
        if not isinstance(result, LaunchdCommandResultV1):
            return LaunchdCommandResultV1(LaunchdCommandOutcome.UNKNOWN)
        return result

    def _configuration_is_current(self) -> bool:
        try:
            return (
                _executable_identity(self._configuration.installed_executable)
                == self._configuration.executable_identity_digest
                and _directory_identity(self._configuration.launch_agents_root)
                == self._configuration.launch_agents_root_identity_digest
                and _directory_identity(self._configuration.state_root)
                == self._configuration.state_root_identity_digest
            )
        except (OSError, PosixWorkspaceStorageError, ValueError):
            return False

    def _ledger(self, phase: _LedgerPhase) -> _LedgerV1:
        return _LedgerV1(
            phase=phase,
            configuration_digest=self._configuration.configuration_digest,
            policy_digest=self.configured_policy_digest,
            plist_digest=self._plist_digest,
        )

    def _ledger_matches_configuration(self, ledger: _LedgerV1) -> bool:
        return (
            ledger.configuration_digest == self._configuration.configuration_digest
            and ledger.policy_digest == self.configured_policy_digest
            and ledger.plist_digest == self._plist_digest
        )

    def _read_ledger(self) -> _LedgerV1 | None:
        root_fd = _open_owner_directory(self._configuration.state_root, exact_mode=True)
        try:
            try:
                payload = read_owner_file_at(
                    root_fd,
                    self._ledger_path.name,
                    maximum=_MAX_LEDGER_BYTES,
                    label="launchd wake ledger",
                )
            except PosixWorkspaceStorageError as error:
                try:
                    os.stat(self._ledger_path.name, dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return None
                raise error
        finally:
            os.close(root_fd)
        document = _decode_ledger(payload)
        return _LedgerV1(
            phase=_LedgerPhase(document["phase"]),
            configuration_digest=document["configuration_digest"],
            policy_digest=document["policy_digest"],
            plist_digest=document["plist_digest"],
        )

    def _write_ledger(self, ledger: _LedgerV1) -> None:
        payload = _encode_ledger(ledger)
        root_fd = _open_owner_directory(self._configuration.state_root, exact_mode=True)
        temporary_name = f".launchd-wake.{os.getpid()}.{time.monotonic_ns()}.tmp"
        try:
            write_new_owner_file_at(root_fd, temporary_name, payload)
            os.replace(
                temporary_name,
                self._ledger_path.name,
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
            os.fsync(root_fd)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=root_fd)
            os.close(root_fd)

    def _read_plist_digest(self) -> str | None:
        root_fd = _open_owner_directory(
            self._configuration.launch_agents_root,
            exact_mode=False,
        )
        try:
            try:
                payload = read_owner_file_at(
                    root_fd,
                    self.plist_path.name,
                    maximum=_MAX_PLIST_BYTES,
                    label="launchd plist",
                )
            except PosixWorkspaceStorageError as error:
                try:
                    os.stat(self.plist_path.name, dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return None
                raise error
            return _sha256(payload)
        finally:
            os.close(root_fd)

    def _install_plist(self) -> None:
        root_fd = _open_owner_directory(
            self._configuration.launch_agents_root,
            exact_mode=False,
        )
        temporary_name = f".{self.plist_path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
        try:
            write_new_owner_file_at(root_fd, temporary_name, self._plist_payload)
            os.link(
                temporary_name,
                self.plist_path.name,
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
                follow_symlinks=False,
            )
            os.unlink(temporary_name, dir_fd=root_fd)
            os.fsync(root_fd)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=root_fd)
            os.close(root_fd)

    def _unlink_exact_plist(self) -> None:
        if self._read_plist_digest() != self._plist_digest:
            raise PosixWorkspaceStorageError("launchd plist identity drift")
        root_fd = _open_owner_directory(
            self._configuration.launch_agents_root,
            exact_mode=False,
        )
        try:
            os.unlink(self.plist_path.name, dir_fd=root_fd)
            os.fsync(root_fd)
        finally:
            os.close(root_fd)

    def _readback_result(
        self,
        outcome: WakeReadbackOutcome,
        requested_policy_digest: str,
    ) -> WakeReadbackV1:
        return WakeReadbackV1(
            outcome=outcome,
            requested_policy_digest=requested_policy_digest,
            installed_policy_digest=(
                self.configured_policy_digest
                if outcome is not WakeReadbackOutcome.ABSENT
                else None
            ),
            adapter_projection_digest=_projection_digest(
                self._configuration.configuration_digest,
                outcome.value,
            ),
        )

    def _install_result(
        self,
        outcome: WakeInstallOutcome,
        requested_policy_digest: str,
    ) -> WakeInstallResultV1:
        return WakeInstallResultV1(
            outcome=outcome,
            requested_policy_digest=requested_policy_digest,
            adapter_projection_digest=_projection_digest(
                self._configuration.configuration_digest,
                outcome.value,
            ),
        )

    def _remove_result(
        self,
        outcome: WakeRemoveOutcome,
        requested_policy_digest: str,
    ) -> WakeRemoveResultV1:
        return WakeRemoveResultV1(
            outcome=outcome,
            requested_policy_digest=requested_policy_digest,
            adapter_projection_digest=_projection_digest(
                self._configuration.configuration_digest,
                outcome.value,
            ),
        )


def _run_launchctl(
    argv: tuple[str, ...],
    timeout_seconds: float,
) -> LaunchdCommandResultV1:
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return LaunchdCommandResultV1(LaunchdCommandOutcome.UNKNOWN)
    except OSError:
        return LaunchdCommandResultV1(LaunchdCommandOutcome.NOT_EXECUTED)
    outcome = (
        LaunchdCommandOutcome.SUCCEEDED
        if completed.returncode == 0
        else LaunchdCommandOutcome.UNKNOWN
    )
    return LaunchdCommandResultV1(outcome)


def _qualified_executable(path: Path) -> Path:
    executable = absolute_unresolved(path)
    try:
        reject_symlink_components(executable)
        info = executable.lstat()
    except (OSError, PosixWorkspaceStorageError) as error:
        raise ValueError("installed_executable is unavailable") from error
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != owner_uid()
        or info.st_nlink != 1
        or info.st_mode & 0o111 == 0
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise ValueError("installed_executable is not an owner-controlled executable")
    return executable


def _executable_identity(path: Path) -> str:
    executable = _qualified_executable(path)
    try:
        fd = os.open(executable, os.O_RDONLY | NOFOLLOW | NONBLOCK)
    except OSError as error:
        raise ValueError("installed_executable is unavailable") from error
    try:
        info = os.fstat(fd)
        if info.st_size > _MAX_EXECUTABLE_BYTES:
            raise ValueError("installed_executable exceeds the identity bound")
        digest = hashlib.sha256()
        remaining = _MAX_EXECUTABLE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        if remaining == 0 and os.read(fd, 1):
            raise ValueError("installed_executable exceeds the identity bound")
        return canonical_json_digest(
            {
                "content_digest": digest.hexdigest(),
                "device": info.st_dev,
                "inode": info.st_ino,
                "mode": stat.S_IMODE(info.st_mode),
                "owner": info.st_uid,
                "size": info.st_size,
            }
        )
    finally:
        os.close(fd)


def _qualified_directory(path: Path, *, label: str, exact_owner_mode: bool) -> Path:
    directory = absolute_unresolved(path)
    try:
        reject_symlink_components(directory)
        info = directory.lstat()
    except (OSError, PosixWorkspaceStorageError) as error:
        raise ValueError(f"{label} is unavailable") from error
    mode = stat.S_IMODE(info.st_mode)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != owner_uid()
        or (mode != 0o700 if exact_owner_mode else bool(mode & 0o022))
    ):
        raise ValueError(f"{label} must be an owner-controlled directory")
    return directory


def _open_owner_directory(path: Path, *, exact_mode: bool) -> int:
    qualified = _qualified_directory(path, label="owner directory", exact_owner_mode=exact_mode)
    try:
        return os.open(qualified, os.O_RDONLY | DIRECTORY | NOFOLLOW | NONBLOCK)
    except OSError as error:
        raise PosixWorkspaceStorageError("owner directory is unavailable") from error


def _directory_identity(path: Path) -> str:
    info = path.lstat()
    return canonical_json_digest(
        {
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode),
            "owner": info.st_uid,
        }
    )


def _encode_ledger(ledger: _LedgerV1) -> bytes:
    return json.dumps(
        {
            "configuration_digest": ledger.configuration_digest,
            "phase": ledger.phase.value,
            "plist_digest": ledger.plist_digest,
            "policy_digest": ledger.policy_digest,
            "schema_version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode_ledger(payload: bytes) -> dict[str, object]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("launchd wake ledger is malformed") from error
    if not isinstance(document, dict) or set(document) != {
        "configuration_digest",
        "phase",
        "plist_digest",
        "policy_digest",
        "schema_version",
    }:
        raise ValueError("launchd wake ledger fields must be exact")
    if document["schema_version"] != 1:
        raise ValueError("launchd wake ledger schema is unsupported")
    for field in ("configuration_digest", "plist_digest", "policy_digest"):
        _require_digest(document[field])
    _LedgerPhase(document["phase"])
    if _encode_ledger(
        _LedgerV1(
            phase=_LedgerPhase(document["phase"]),
            configuration_digest=document["configuration_digest"],
            policy_digest=document["policy_digest"],
            plist_digest=document["plist_digest"],
        )
    ) != payload:
        raise ValueError("launchd wake ledger must use canonical JSON")
    return document


def _projection_digest(configuration_digest: str, outcome: str) -> str:
    return canonical_json_digest(
        {
            "adapter": "macos_launchd_wake_v1",
            "configuration_digest": configuration_digest,
            "outcome": outcome,
        }
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_digest(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("digest must be bare hex64")

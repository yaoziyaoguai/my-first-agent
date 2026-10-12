"""本任务受管开发服务：有界启动、观察、停止与 loopback 身份。

这不是 daemon manager。每个服务都由当前 composition 明确拥有，使用独立
process group、封闭环境和 closed resource profile；应用退出时同步回收。
模型只能拿到 opaque resource ref，不能提交 PID、PGID 或任意 signal 目标。
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from agent.browser.contracts import LoopbackOriginBindingV1
from agent.process import group as process_group
from agent.process.contracts import (
    SAME_UID_TRUST_NOTICE,
    KnownNotExecuted,
    ResourceProfileV1,
)
from agent.process.preparation import (
    PreparedProcessV1,
    closed_process_environment,
    prepare_process,
    revalidate_process,
    sanitize_captured_path,
)
from agent.runtime.contracts import (
    ApprovalPolicy,
    EgressClass,
    ExecutionAuthorityClass,
    KnownExecutedError,
    OutputPolicy,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
    canonical_json_digest,
)
from agent.runtime.tools import RegisteredTool
from agent.tools.path_safety import WorkspaceBoundary

_READY_TIMEOUT_SECONDS = 5.0
_PROBE_INTERVAL_SECONDS = 0.05
_STREAM_READ_SIZE = 65_536


class _BoundedCapture:
    def __init__(self, stream, cap_bytes: int) -> None:  # noqa: ANN001
        self._stream = stream
        self._cap = cap_bytes
        self._buffer = bytearray()
        self._truncated = False
        self._lock = threading.Lock()
        self._activity = threading.Event()
        self._thread = threading.Thread(target=self._drain, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _drain(self) -> None:
        while True:
            try:
                chunk = os.read(self._stream.fileno(), _STREAM_READ_SIZE)
            except OSError:
                return
            if not chunk:
                return
            with self._lock:
                room = max(0, self._cap - len(self._buffer))
                if room:
                    self._buffer.extend(chunk[:room])
                if len(chunk) > room:
                    self._truncated = True
            self._activity.set()

    def wait_for_activity(self, timeout: float) -> None:
        self._activity.wait(timeout=timeout)

    def snapshot(self, rendered_chars: int) -> tuple[str, str, bool]:
        with self._lock:
            payload = bytes(self._buffer)
            truncated = self._truncated
        return (
            payload.decode("utf-8", errors="replace")[:rendered_chars],
            hashlib.sha256(payload).hexdigest(),
            truncated or len(payload.decode("utf-8", errors="replace")) > rendered_chars,
        )

    def close(self, timeout: float) -> None:
        with suppress(OSError):
            self._stream.close()
        self._thread.join(timeout=timeout)


@dataclass(slots=True)
class _ManagedProcess:
    resource_ref: str
    proc: subprocess.Popen
    process_group_id: int
    command_fingerprint: str
    origin: str
    goal_id: str
    goal_revision: int
    issued_monotonic: float
    expires_monotonic: float
    profile: ResourceProfileV1
    temp_root: str
    control_fd: int
    stdout: _BoundedCapture
    stderr: _BoundedCapture


@dataclass(frozen=True, slots=True)
class ManagedWebProcessTools:
    registrations: tuple[RegisteredTool, ...]
    owner: ManagedWebProcessOwner

    def close(self) -> None:
        self.owner.close()


class ManagedWebProcessOwner:
    """当前应用进程独占的开发服务 owner。"""

    def __init__(
        self,
        *,
        workspace: Path,
        captured_path: str,
        workspace_boundary: WorkspaceBoundary | None = None,
        cleanup_receipt_root: Path | None = None,
        monotonic_clock=time.monotonic,
    ) -> None:  # noqa: ANN001
        self._workspace = Path(workspace).absolute()
        self._boundary = workspace_boundary or WorkspaceBoundary(self._workspace)
        if self._boundary.root != self._workspace:
            raise ValueError("managed web workspace boundary does not match workspace")
        self._search_paths, self._captured_path = sanitize_captured_path(captured_path)
        self._clock = monotonic_clock
        self._active: dict[str, _ManagedProcess] = {}
        self._lock = threading.RLock()
        self._cleanup_dir_fd = _open_cleanup_receipt_root(cleanup_receipt_root)
        self._closed = False

    def prepare_start(self, arguments: dict) -> dict:
        port = _parse_loopback_port(arguments.get("loopback_port"))
        process_arguments = _process_arguments(arguments)
        prepared = prepare_process(
            process_arguments,
            workspace=self._workspace,
            captured_path=self._captured_path,
            boundary=self._boundary,
        )
        if isinstance(prepared, KnownNotExecuted):
            raise ValueError(f"preparation not admitted: {prepared.code}")
        binding = _process_binding(prepared)
        origin = f"http://127.0.0.1:{port}"
        command_fingerprint = canonical_json_digest(
            {
                "process_command_fingerprint": binding["command_fingerprint"],
                "loopback_origin": origin,
            }
        )
        return {
            **binding,
            "process_command_fingerprint": binding["command_fingerprint"],
            "command_fingerprint": command_fingerprint,
            "loopback_port": port,
            "loopback_origin": origin,
            "operation": "managed_web_start",
            "effect_preview": (
                _render_process_preview(prepared)
                + f"\n  managed loopback origin: {origin}"
                + "\n  lifecycle: owned by this task; bounded logs; automatic shutdown cleanup"
            ),
        }

    def start(self, intent):  # noqa: ANN001, ANN201
        binding = intent.safety_binding
        port = int(binding["loopback_port"])
        if not _port_available(port):
            return KnownNotExecuted(
                code="loopback_port_unavailable",
                message="The requested loopback port is already in use; choose another port.",
            )
        prepared = prepare_process(
            _process_arguments(intent.arguments),
            workspace=self._workspace,
            captured_path=self._captured_path,
            boundary=self._boundary,
        )
        if isinstance(prepared, KnownNotExecuted):
            return prepared
        revalidated = revalidate_process(prepared)
        if isinstance(revalidated, KnownNotExecuted):
            return revalidated
        expected = self.prepare_start(dict(intent.arguments))
        if expected != binding:
            return KnownNotExecuted(
                code="managed_process_binding_changed",
                message="Managed process safety binding changed before spawn.",
            )
        profile = ResourceProfileV1.for_profile(revalidated.command.profile)
        temp_root = tempfile.mkdtemp(prefix="fa-managed-web-")
        environment = closed_process_environment(temp_root, self._captured_path)
        approved_command = [
            revalidated.command.executable_identity.resolved_path,
            *revalidated.command.argv,
        ]
        supervisor_path = Path(__file__).with_name("managed_web_child.py")
        control_read_fd, control_write_fd = os.pipe()
        issued = float(self._clock())
        command = [
            sys.executable,
            "-I",
            str(supervisor_path),
            "--control-fd",
            str(control_read_fd),
            "--lifetime-seconds",
            str(profile.wall_deadline_seconds),
            "--",
            *approved_command,
        ]
        try:
            proc = subprocess.Popen(  # noqa: S603 - exact approved argv, shell=False
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=revalidated.cwd_path,
                env=environment,
                shell=False,
                start_new_session=True,
                close_fds=True,
                pass_fds=(control_read_fd,),
            )
        except (OSError, ValueError):
            os.close(control_read_fd)
            os.close(control_write_fd)
            shutil.rmtree(temp_root, ignore_errors=True)
            return KnownNotExecuted(
                code="managed_process_spawn_failed",
                message="The managed development process could not be started.",
            )
        os.close(control_read_fd)
        pgid: int | None = None
        try:
            pgid = process_group.verified_group_identity(proc.pid)
            assert proc.stdout is not None and proc.stderr is not None
            stdout = _BoundedCapture(proc.stdout, profile.stdout_cap_bytes)
            stderr = _BoundedCapture(proc.stderr, profile.stderr_cap_bytes)
            stdout.start()
            stderr.start()
            if not _wait_until_listening(proc, pgid, port, self._clock):
                os.close(control_write_fd)
                _terminate_owned(proc, pgid, profile)
                stdout.close(profile.kill_grace_seconds)
                stderr.close(profile.kill_grace_seconds)
                shutil.rmtree(temp_root, ignore_errors=True)
                return KnownExecutedError(
                    code="managed_process_not_ready",
                    message="The process started but did not open its approved loopback port.",
                )
            # 常见 dev server 会在 listen 前后立即打印 readiness；给 reader 一个很短的
            # 交接窗口，让第一次 observe 更有诊断价值，不把日志文本当 readiness 权威。
            stdout.wait_for_activity(timeout=0.1)
            stderr.wait_for_activity(timeout=0.01)
            resource_ref = "managed-web-" + secrets.token_hex(12)
            record = _ManagedProcess(
                resource_ref=resource_ref,
                proc=proc,
                process_group_id=pgid,
                command_fingerprint=str(binding["command_fingerprint"]),
                origin=str(binding["loopback_origin"]),
                goal_id=intent.goal_id or "",
                goal_revision=intent.goal_revision or 0,
                issued_monotonic=issued,
                expires_monotonic=issued + profile.wall_deadline_seconds,
                profile=profile,
                temp_root=temp_root,
                control_fd=control_write_fd,
                stdout=stdout,
                stderr=stderr,
            )
            with self._lock:
                self._active[resource_ref] = record
            return {
                "resource_ref": resource_ref,
                "origin": record.origin,
                "status": "ready",
                "expires_monotonic": record.expires_monotonic,
            }
        except Exception:
            try:
                with suppress(OSError):
                    os.close(control_write_fd)
                if pgid is not None:
                    _terminate_owned(proc, pgid, profile)
                else:
                    # identity probe 失败时不能猜测 PGID。先让 control EOF 驱动
                    # 监督器自行清组；只有监督器也不退出时才回收亲自持有的 leader。
                    try:
                        proc.wait(
                            timeout=(
                                profile.term_grace_seconds
                                + profile.kill_grace_seconds
                                + 2.0
                            )
                        )
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=profile.kill_grace_seconds)
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)
            raise

    def prepare_resource(self, arguments: dict) -> dict:
        resource_ref = arguments.get("resource_ref")
        if not isinstance(resource_ref, str):
            raise ValueError("managed resource_ref must be a string")
        try:
            record = self._record(resource_ref)
        except ValueError:
            receipt = self._load_cleanup_receipt(resource_ref)
            if receipt is None:
                raise
            return {
                "resource_ref": resource_ref,
                "command_fingerprint": receipt["command_fingerprint"],
                "goal_id": receipt["goal_id"],
                "goal_revision": receipt["goal_revision"],
                "loopback_origin": receipt["loopback_origin"],
                "operation": "managed_web_resource",
                "cleanup": "confirmed",
            }
        return {
            "resource_ref": record.resource_ref,
            "process_group_id": record.process_group_id,
            "command_fingerprint": record.command_fingerprint,
            "goal_id": record.goal_id,
            "goal_revision": record.goal_revision,
            "loopback_origin": record.origin,
            "expires_monotonic": record.expires_monotonic,
            "operation": "managed_web_resource",
        }

    def observe(self, intent):  # noqa: ANN001, ANN201
        resource_ref = intent.arguments.get("resource_ref")
        try:
            record = self._record(resource_ref)
        except ValueError:
            receipt = self._load_cleanup_receipt(resource_ref)
            if receipt is None:
                raise
            return {
                "resource_ref": resource_ref,
                "origin": receipt["loopback_origin"],
                "active": False,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "stdout_digest": hashlib.sha256(b"").hexdigest(),
                "stderr_digest": hashlib.sha256(b"").hexdigest(),
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
        active = self._record_is_active(record)
        stdout, stdout_digest, stdout_truncated = record.stdout.snapshot(
            record.profile.rendered_chars
        )
        stderr, stderr_digest, stderr_truncated = record.stderr.snapshot(
            record.profile.rendered_chars
        )
        return {
            "resource_ref": record.resource_ref,
            "origin": record.origin,
            "active": active,
            "exit_code": record.proc.poll(),
            "stdout": stdout,
            "stderr": stderr,
            "stdout_digest": stdout_digest,
            "stderr_digest": stderr_digest,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }

    def stop(self, intent):  # noqa: ANN001, ANN201
        resource_ref = intent.arguments.get("resource_ref")
        try:
            record = self._record(resource_ref)
        except ValueError:
            if self._load_cleanup_receipt(resource_ref) is None:
                raise
            return {"resource_ref": resource_ref, "cleanup": "confirmed"}
        self._stop_record(record)
        self._write_cleanup_receipt(record)
        with self._lock:
            self._active.pop(record.resource_ref, None)
        return {"resource_ref": record.resource_ref, "cleanup": "confirmed"}

    def loopback_binding(
        self,
        resource_ref: str,
        *,
        goal_id: str,
        goal_revision: int,
    ) -> LoopbackOriginBindingV1:
        record = self._record(resource_ref)
        if record.goal_id != goal_id or record.goal_revision != goal_revision:
            raise ValueError("managed process does not bind the current Goal")
        binding = LoopbackOriginBindingV1(
            resource_ref=record.resource_ref,
            origin=record.origin,
            goal_id=record.goal_id,
            goal_revision=record.goal_revision,
            process_group_id=record.process_group_id,
            command_fingerprint=record.command_fingerprint,
            issued_monotonic=record.issued_monotonic,
            expires_monotonic=record.expires_monotonic,
        )
        if not self.verify_loopback_binding(binding):
            raise ValueError("managed process is not active")
        return binding

    def prepare_loopback_binding(self, resource_ref: str) -> LoopbackOriginBindingV1:
        """approval 前只投影当前资源身份；Goal 全等在 open effect 前重验。"""

        record = self._record(resource_ref)
        return LoopbackOriginBindingV1(
            resource_ref=record.resource_ref,
            origin=record.origin,
            goal_id=record.goal_id,
            goal_revision=record.goal_revision,
            process_group_id=record.process_group_id,
            command_fingerprint=record.command_fingerprint,
            issued_monotonic=record.issued_monotonic,
            expires_monotonic=record.expires_monotonic,
        )

    def verify_loopback_binding(self, binding: LoopbackOriginBindingV1) -> bool:
        try:
            record = self._record(binding.resource_ref)
        except ValueError:
            return False
        if (
            binding.binding_digest
            != LoopbackOriginBindingV1(
                resource_ref=record.resource_ref,
                origin=record.origin,
                goal_id=record.goal_id,
                goal_revision=record.goal_revision,
                process_group_id=record.process_group_id,
                command_fingerprint=record.command_fingerprint,
                issued_monotonic=record.issued_monotonic,
                expires_monotonic=record.expires_monotonic,
            ).binding_digest
        ):
            return False
        return self._record_is_active(record)

    def close(self) -> None:
        if self._closed:
            return
        failures: list[str] = []
        with self._lock:
            records = tuple(self._active.values())
        for record in records:
            try:
                self._stop_record(record)
                self._write_cleanup_receipt(record)
            except Exception:  # noqa: BLE001 - 聚合后 fail closed
                failures.append(record.resource_ref)
            else:
                with self._lock:
                    self._active.pop(record.resource_ref, None)
        if failures:
            raise process_group.ProcessCleanupError(
                "managed web cleanup could not be confirmed: " + ", ".join(failures)
            )
        if self._cleanup_dir_fd is not None:
            os.close(self._cleanup_dir_fd)
            self._cleanup_dir_fd = None
        self._closed = True

    def _write_cleanup_receipt(self, record: _ManagedProcess) -> None:
        if self._cleanup_dir_fd is None:
            return
        payload = {
            "schema": "my-first-agent/managed-web-cleanup-receipt/v1",
            "resource_ref": record.resource_ref,
            "command_fingerprint": record.command_fingerprint,
            "goal_id": record.goal_id,
            "goal_revision": record.goal_revision,
            "loopback_origin": record.origin,
            "cleanup": "confirmed",
        }
        content = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        name = _cleanup_receipt_name(record.resource_ref)
        temporary = f".{name}.{secrets.token_hex(6)}.tmp"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self._cleanup_dir_fd,
        )
        try:
            _write_all(fd, content)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.rename(
                temporary,
                name,
                src_dir_fd=self._cleanup_dir_fd,
                dst_dir_fd=self._cleanup_dir_fd,
            )
            os.fsync(self._cleanup_dir_fd)
        except Exception:
            with suppress(OSError):
                os.unlink(temporary, dir_fd=self._cleanup_dir_fd)
            raise

    def _load_cleanup_receipt(self, resource_ref: object) -> dict | None:
        if self._cleanup_dir_fd is None or not isinstance(resource_ref, str):
            return None
        try:
            fd = os.open(
                _cleanup_receipt_name(resource_ref),
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=self._cleanup_dir_fd,
            )
        except FileNotFoundError:
            return None
        try:
            content = os.read(fd, 16_385)
            if len(content) > 16_384 or os.read(fd, 1):
                raise ValueError("managed cleanup receipt is too large")
        finally:
            os.close(fd)
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("managed cleanup receipt is malformed") from error
        expected_keys = {
            "schema",
            "resource_ref",
            "command_fingerprint",
            "goal_id",
            "goal_revision",
            "loopback_origin",
            "cleanup",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != expected_keys
            or payload.get("schema")
            != "my-first-agent/managed-web-cleanup-receipt/v1"
            or payload.get("resource_ref") != resource_ref
            or payload.get("cleanup") != "confirmed"
            or not isinstance(payload.get("command_fingerprint"), str)
            or not isinstance(payload.get("goal_id"), str)
            or not isinstance(payload.get("goal_revision"), int)
            or isinstance(payload.get("goal_revision"), bool)
            or not isinstance(payload.get("loopback_origin"), str)
        ):
            raise ValueError("managed cleanup receipt is malformed")
        return payload

    def _record(self, resource_ref: object) -> _ManagedProcess:
        if not isinstance(resource_ref, str):
            raise ValueError("managed resource_ref must be a string")
        with self._lock:
            record = self._active.get(resource_ref)
        if record is None:
            raise ValueError("managed web resource is not active")
        return record

    def _record_is_active(self, record: _ManagedProcess) -> bool:
        if self._clock() >= record.expires_monotonic or record.proc.poll() is not None:
            return False
        try:
            return process_group.group_alive(
                record.process_group_id
            ) and _listener_owned_by_group(
                int(record.origin.rsplit(":", 1)[1]),
                record.process_group_id,
            )
        except process_group.ProcessCleanupError:
            return False

    @staticmethod
    def _stop_record(record: _ManagedProcess) -> None:
        with suppress(OSError):
            os.close(record.control_fd)
        _terminate_owned(record.proc, record.process_group_id, record.profile)
        record.stdout.close(record.profile.kill_grace_seconds)
        record.stderr.close(record.profile.kill_grace_seconds)
        shutil.rmtree(record.temp_root, ignore_errors=True)


def _process_arguments(arguments: dict) -> dict:
    selected = {
        key: arguments[key]
        for key in ("executable", "argv", "cwd", "profile")
        if key in arguments
    }
    # 开发服务要跨越多轮模型思考和浏览器动作；仍使用 closed/bounded 档位，
    # 但缺省 900 秒，避免通用进程的 120 秒默认值在正常验收中途到期。
    selected.setdefault("profile", "long")
    return selected


def _open_cleanup_receipt_root(root: Path | None) -> int | None:
    if root is None:
        return None
    path = Path(root).absolute()
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise ValueError(
            "managed cleanup receipt root must be a real directory"
        ) from error
    info = os.fstat(fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        os.close(fd)
        raise ValueError("managed cleanup receipt root must be owner-only")
    return fd


def _cleanup_receipt_name(resource_ref: str) -> str:
    digest = hashlib.sha256(resource_ref.encode("utf-8")).hexdigest()
    return f"{digest}.json"


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("cleanup receipt write made no progress")
        view = view[written:]


def _parse_loopback_port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1024 <= value <= 65535:
        raise ValueError("loopback_port must be an integer in 1024..65535")
    return value


def _process_binding(prepared: PreparedProcessV1) -> dict:
    command = prepared.command
    identity = command.executable_identity
    environment = command.environment_policy
    assert identity is not None and environment is not None
    argv = list(command.argv)
    return {
        "command_fingerprint": command.command_fingerprint,
        "executable_digest": identity.identity_digest,
        "resolved_executable_path": identity.resolved_path,
        "argv_digest": hashlib.sha256(json.dumps(argv).encode("utf-8")).hexdigest(),
        "cwd_digest": hashlib.sha256(command.cwd.encode("utf-8")).hexdigest(),
        "cwd_descriptor": command.cwd_descriptor,
        "resource_profile": command.profile.value,
        "environment_policy_digest": environment.policy_digest,
        "trust_notice_id": "same_uid_process_v1",
        "trust_notice_digest": hashlib.sha256(SAME_UID_TRUST_NOTICE.encode()).hexdigest(),
        "process_argv": argv,
        "process_cwd": command.cwd,
        "process_profile": command.profile.value,
    }


def _render_process_preview(prepared: PreparedProcessV1) -> str:
    command = prepared.command
    identity = command.executable_identity
    assert identity is not None
    argv = " ".join(json.dumps(item) for item in command.argv)
    return (
        f"managed_web profile={json.dumps(command.profile.value)} "
        f"cwd={json.dumps(command.cwd)}\n"
        f"  executable: {json.dumps(command.executable_token)} -> "
        f"{json.dumps(identity.resolved_path)}\n"
        f"  argv: {argv}\n"
        f"  {SAME_UID_TRUST_NOTICE}"
    )


def _port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


def _wait_until_listening(
    proc: subprocess.Popen,
    process_group_id: int,
    port: int,
    monotonic_clock,
) -> bool:  # noqa: ANN001
    deadline = monotonic_clock() + _READY_TIMEOUT_SECONDS
    while monotonic_clock() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                if _listener_owned_by_group(port, process_group_id):
                    return True
        except OSError:
            time.sleep(_PROBE_INTERVAL_SECONDS)
    return False


def _listener_owned_by_group(port: int, process_group_id: int) -> bool:
    """让 OS 把 exact loopback listener 归因到获批 process group。

    Python 标准库不能从 TCP listener 反查 owner。受管本地网页能力因此只在 host
    提供固定路径的 ``lsof`` 时启用该证明；探针缺失、超时、输出异常或出现其它
    process group 都 fail closed，绝不退化为“端口有人监听就算成功”。
    """

    executable = next(
        (
            candidate
            for candidate in ("/usr/sbin/lsof", "/usr/bin/lsof")
            if Path(candidate).is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )
    if executable is None:
        return False
    try:
        completed = subprocess.run(  # noqa: S603 - fixed operator-trusted diagnostic
            [
                executable,
                "-nP",
                "-a",
                f"-iTCP@127.0.0.1:{port}",
                "-sTCP:LISTEN",
                "-Fpg",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0 or len(completed.stdout) > 64_000:
        return False
    groups: list[int] = []
    for line in completed.stdout.splitlines():
        if not line.startswith(b"g"):
            continue
        try:
            groups.append(int(line[1:]))
        except ValueError:
            return False
    return bool(groups) and all(group == process_group_id for group in groups)


def _terminate_owned(
    proc: subprocess.Popen,
    pgid: int,
    profile: ResourceProfileV1,
) -> None:
    if proc.poll() is not None and not process_group.group_alive(pgid):
        proc.wait(timeout=profile.kill_grace_seconds)
        return
    process_group.terminate_group(
        proc,
        pgid,
        term_grace_seconds=profile.term_grace_seconds,
        kill_grace_seconds=profile.kill_grace_seconds,
    )


def _tool_spec(
    name: str,
    description: str,
    properties: dict,
    *,
    required: tuple[str, ...],
    side_effect: SideEffectClass,
    approval: ApprovalPolicy,
    authority: ExecutionAuthorityClass,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="managed-web-process-v1",
        description=description,
        input_schema={
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH if name == "managed_web_start" else ToolRisk.MEDIUM,
        side_effect=side_effect,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=approval,
        safety_policy={"kind": name, "managed_task_resource": True},
        output_limit_chars=64_000,
        egress=EgressClass.NONE,
        execution_authority=authority,
    )


def build_managed_web_process_tools(
    *,
    workspace: Path,
    captured_path: str,
    workspace_boundary: WorkspaceBoundary | None = None,
    cleanup_receipt_root: Path | None = None,
    monotonic_clock=time.monotonic,
) -> ManagedWebProcessTools:  # noqa: ANN001
    owner = ManagedWebProcessOwner(
        workspace=workspace,
        captured_path=captured_path,
        workspace_boundary=workspace_boundary,
        cleanup_receipt_root=cleanup_receipt_root,
        monotonic_clock=monotonic_clock,
    )
    process_properties = {
        "executable": {"type": "string"},
        "argv": {"type": "array", "items": {"type": "string"}},
        "cwd": {"type": "string"},
        "profile": {
            "type": "string",
            "enum": ["long"],
            "description": (
                "fixed 900-second hard lifetime for multi-step browser validation"
            ),
        },
        "loopback_port": {"type": "integer", "minimum": 1024, "maximum": 65535},
    }
    resource_properties = {"resource_ref": {"type": "string"}}
    registrations = (
        RegisteredTool(
            spec=_tool_spec(
                "managed_web_start",
                (
                    "Start one bounded task-owned development server on exact "
                    "127.0.0.1 port; profile is long (900 seconds)."
                ),
                process_properties,
                required=("executable", "loopback_port"),
                side_effect=SideEffectClass.EXTERNAL,
                approval=ApprovalPolicy.ALWAYS,
                authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
            ),
            prepare_binding=owner.prepare_start,
            func=owner.start,
        ),
        RegisteredTool(
            spec=_tool_spec(
                "managed_web_observe",
                "Observe bounded logs and liveness for one task-owned development server.",
                resource_properties,
                required=("resource_ref",),
                side_effect=SideEffectClass.READ_ONLY,
                approval=ApprovalPolicy.NEVER,
                authority=ExecutionAuthorityClass.IN_PROCESS,
            ),
            prepare_binding=owner.prepare_resource,
            func=owner.observe,
        ),
        RegisteredTool(
            spec=_tool_spec(
                "managed_web_stop",
                "Stop and verify cleanup of one task-owned development server.",
                resource_properties,
                required=("resource_ref",),
                side_effect=SideEffectClass.EXTERNAL,
                approval=ApprovalPolicy.NEVER,
                authority=ExecutionAuthorityClass.IN_PROCESS,
            ),
            prepare_binding=owner.prepare_resource,
            func=owner.stop,
        ),
    )
    return ManagedWebProcessTools(registrations=registrations, owner=owner)

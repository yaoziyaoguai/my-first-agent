"""Process-isolated child runner：SubAgent 的真实 hard-deadline 路径。

child 在独立 OS 进程内运行**同一个** ``AgentRuntime.run_turn``（经 ``build_child_runtime``，
不创建第二套 loop）。本 runner 拥有该进程的 process group（``start_new_session=True``），
在 ``hard_deadline_seconds`` 后用 ``killpg`` 终止整个 group 并确认退出——这是唯一诚实的
hard deadline：socket/read timeout 不能证明 provider 已终止，只有进程所有权能。

receipt 语义（确定性，无 race）：

- ``TERMINATED``：child exit 0 且 stdout 是合法结果 JSON（child 已 terminally 报告了它的
  ``RunStatus``——无论 COMPLETED 还是被 run_turn 分类为 FAILED_*），且 process group
  消失已由共享 group-liveness oracle 确认。
- ``UNCONFIRMED``：parent 在 deadline 前 child 未自行退出（被 parent kill），或 child 非 0
  退出/未写出合法结果，或 group 终止/清理无法确认。此时 provider call 可能已发生，
  parent 必须进入 unknown-outcome recovery——``UNCONFIRMED`` 覆盖一切 child normalization；
  绝不把 unknown 当 terminated。

credential 永不跨进程序列化：``ChildProviderSpec`` 只带 env name，子进程从自身 env 读取值；
config 文件不含 credential。config 是 bounded、owner-only、no-follow 的临时 JSON。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from agent.process.group import (
    ProcessCleanupError,
    group_alive,
    terminate_group,
    verified_group_identity,
)
from agent.runtime.contracts import RunStatus
from agent.subagent.contracts import (
    ChildProfile,
    ChildProviderSpec,
    ChildRunResult,
    ProviderDeadlineCapability,
    TerminationReceiptState,
)
from agent.subagent.runtime_factory import child_status_reason, derive_child_identity

_POLL_INTERVAL = 0.02
_KILL_GRACE_SECONDS = 1.0
# parent 读取 child stdout 的有界上限（defense-in-depth）：child 内 ``_RESULT_LIMIT_CHARS``
# 已 cap 消息，正常结果远小于此；超出按 oversized → UNCONFIRMED，绝不无界 read。
_MAX_RESULT_BYTES = 8_192


@dataclass(frozen=True, slots=True)
class _ChildConfig:
    spec: ChildProviderSpec
    profile: ChildProfile
    objective: str
    handoff: str
    parent_idempotency_key: str


class ChildProcessRunner:
    """production hard-deadline runner：进程隔离 + parent 拥有 process group。"""

    def __init__(
        self,
        *,
        provider_spec: ChildProviderSpec,
        profile: ChildProfile,
        python: str | None = None,
        hard_deadline_seconds: float | None = None,
        poll_interval: float = _POLL_INTERVAL,
    ) -> None:
        self._spec = provider_spec
        self._profile = profile
        self._python = python or sys.executable
        self._hard_deadline = (
            hard_deadline_seconds
            if hard_deadline_seconds is not None
            else profile.hard_deadline_seconds
        )
        if self._hard_deadline <= 0:
            raise ValueError("hard_deadline_seconds must be positive")
        self._poll_interval = poll_interval

    @property
    def profile(self) -> ChildProfile:
        return self._profile

    @property
    def deadline_contract(self) -> ProviderDeadlineCapability:
        """本 runner 诚实声明的 hard-deadline capability：进程边界提供。

        与同步 provider 的 ``synchronous`` receipt 区分：本路径的 receipt 来自 parent 对
        子进程 group 的可证明终止（共享 group-liveness oracle 确认消失；无法确认时
        fail closed 为 UNCONFIRMED），而非 provider 的 socket timeout。
        """
        return ProviderDeadlineCapability(
            hard_deadline_seconds=self._hard_deadline,
            receipt_type="process_terminated",
        )

    def run(
        self,
        *,
        objective: str,
        handoff: str,
        parent_idempotency_key: str,
    ) -> ChildRunResult:
        child_run_id = derive_child_identity(parent_idempotency_key)[1]
        config = _ChildConfig(self._spec, self._profile, objective, handoff, parent_idempotency_key)
        config_path = self._write_config(config)
        config_dir = config_path.parent
        cleanup_succeeded = False
        termination_unconfirmed = False
        try:
            outcome = self._run_child(config_path)
        except ProcessCleanupError:
            # group identity/终止/清理无法确认：不解析任何 child 输出，fail closed。
            outcome = None
            termination_unconfirmed = True
        finally:
            # F-G8-2：安全移除 per-run 目录（先删 config.json 再 rmdir 空目录），不跟随 symlink、
            # 不删除宽泛/未解析路径。任何失败都不得影响 receipt 分类——但单次 unlink/rmdir
            # 的瞬时失败（全 suite 负载下实测）会静默泄漏目录，违反"必须消失"合同，
            # 故有界重试到目录真正消失或预算耗尽。
            cleanup_succeeded = _remove_run_dir(config_path, config_dir)

        if termination_unconfirmed:
            return ChildRunResult(
                status=RunStatus.FAILED_FATAL,
                run_id=child_run_id,
                message="",
                reason="termination_unconfirmed",
                model_calls=0,
                tool_calls=0,
                receipt_state=TerminationReceiptState.UNCONFIRMED,
            )

        if not cleanup_succeeded:
            # receipt 语义要求 child terminally 报告过结果才能 TERMINATED；outcome
            # 未知（deadline kill 等）叠加 cleanup 失败只能 UNCONFIRMED，不得把
            # unknown 当 terminated。
            return ChildRunResult(
                status=RunStatus.FAILED_FATAL,
                run_id=child_run_id,
                message="",
                reason="cleanup_failed",
                model_calls=1 if outcome is not None else 0,
                tool_calls=0,
                receipt_state=(
                    TerminationReceiptState.TERMINATED
                    if outcome is not None
                    else TerminationReceiptState.UNCONFIRMED
                ),
            )

        if outcome is not None:
            status = _status_from_name(outcome.get("status"))
            return ChildRunResult(
                status=status,
                run_id=child_run_id,
                message=str(outcome.get("message") or "")[:4_000],
                reason=child_status_reason(status),
                model_calls=1,
                tool_calls=0,
                receipt_state=TerminationReceiptState.TERMINATED,
            )

        # deadline kill 或 child 未写出合法结果：provider call 可能已发生 → UNCONFIRMED。
        return ChildRunResult(
            status=RunStatus.FAILED_FATAL,
            run_id=child_run_id,
            message="",
            reason="unconfirmed_outcome",
            model_calls=0,
            tool_calls=0,
            receipt_state=TerminationReceiptState.UNCONFIRMED,
        )

    def _run_child(self, config_path: Path) -> dict | None:
        env = self._child_env()
        proc = subprocess.Popen(  # noqa: SUT603 - child is operator-trusted, bounded argv
            [self._python, "-m", "agent.subagent.child", str(config_path)],
            stdout=subprocess.PIPE,
            # stderr 直接丢弃到 OS（DEVNULL）：deadlock-safe、不缓冲、不进 result。child 突发
            # >pipe-buffer 的 stderr 也不会阻塞自己（否则会触发假 UNCONFIRMED）。
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            try:
                pgid = verified_group_identity(proc.pid)
            except ProcessCleanupError:
                # 无法验证 group identity：不退化为单进程信号并照常收尾。有界
                # best-effort 清理 leader 只是止损，不构成任何 termination 证明；
                # ProcessCleanupError 继续上抛，由 run() fail closed 为
                # termination_unconfirmed。
                with suppress(OSError):
                    proc.kill()
                with suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=_KILL_GRACE_SECONDS)
                raise
            deadline = time.monotonic() + self._hard_deadline
            timed_out = False
            while True:
                if proc.poll() is not None:
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                time.sleep(self._poll_interval)

            if proc.poll() is None:
                # child 未自行退出：verified TERM→KILL→confirm 整个 process group
                # （有界，unconfirmable → ProcessCleanupError → fail closed）。
                terminate_group(
                    proc,
                    pgid,
                    term_grace_seconds=_KILL_GRACE_SECONDS,
                    kill_grace_seconds=_KILL_GRACE_SECONDS,
                )
            elif group_alive(pgid):
                # leader 自行退出但同 group descendant 仍存活：同样必须治理并
                # 确认消失，否则 process_terminated 是未验证的声称。
                terminate_group(
                    proc,
                    pgid,
                    term_grace_seconds=_KILL_GRACE_SECONDS,
                    kill_grace_seconds=_KILL_GRACE_SECONDS,
                )
            # group 消失已确认 → stdout 的所有写端都已关闭，read 不会无限阻塞。
            stdout = _read_bounded(proc.stdout, _MAX_RESULT_BYTES)
            if timed_out or proc.returncode != 0:
                return None
            if stdout is None:
                # oversized child output → 无法信任为合法结果 → UNCONFIRMED。
                return None
            return _parse_result(stdout)
        finally:
            # 显式关闭 child stdout pipe（FileIO），避免残留到 GC 触发 unclosed
            # ResourceWarning / unraisable（与 MCP bridge transport 同类的资源泄漏）。
            # stdin 未用 PIPE、stderr 为 DEVNULL，均无需显式关闭。
            if proc.stdout is not None:
                proc.stdout.close()

    def _child_env(self) -> dict:
        # 子进程必须 import 同一份 agent：用 parent 自身的 agent 源根作为 PYTHONPATH，
        # 不继承可能把 dirty-tree 代码混入的其它路径。credential 经 env name 在子进程内读取，
        # 因此保留 parent env（仅覆盖 PYTHONPATH/PYTHONHOME）。
        import agent as _agent

        source_root = str(Path(_agent.__file__).resolve().parent.parent)
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        env["PYTHONPATH"] = source_root
        return env

    def _write_config(self, config: _ChildConfig) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="subagent-child-"))
        directory.chmod(0o700)
        config_path = directory / "config.json"
        payload = {
            "spec": _spec_to_dict(config.spec),
            "profile": _profile_to_dict(config.profile),
            "objective": config.objective,
            "handoff": config.handoff,
            "parent_idempotency_key": config.parent_idempotency_key,
        }
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(blob) > 200_000:
            raise ValueError("child config exceeds the bounded limit")
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, blob)
            os.fsync(fd)
        finally:
            os.close(fd)
        return config_path


def _remove_run_dir(config_path: Path, config_dir: Path) -> bool:
    """有界重试地移除 per-run 目录（F-G8-2 + U10 复验实测的负载竞态加固）。

    先 unlink config.json 再 rmdir 空目录；两者任一瞬时失败（全 suite 负载下实测）
    在小预算内重试。预算耗尽返回 ``False``，caller 必须把整体调用标为失败，不能在
    owner-only config 目录仍残留时报告成功。
    """

    import time as _time

    for _ in range(5):
        with __import__("contextlib").suppress(OSError):
            config_path.unlink()
        try:
            config_dir.rmdir()
            return True
        except OSError:
            _time.sleep(0.02)
    try:
        config_dir.rmdir()
    except OSError:
        return False
    return True


def _spec_to_dict(spec: ChildProviderSpec) -> dict:
    return {
        "kind": spec.kind,
        "fake_text": spec.fake_text,
        "fake_tool": list(spec.fake_tool) if spec.fake_tool is not None else None,
        "sleep_seconds": spec.sleep_seconds,
        "stderr_chars": spec.stderr_chars,
        "provider_type": spec.provider_type,
        "model": spec.model,
        "base_url": spec.base_url,
        "credential_env_name": spec.credential_env_name,
        "timeout": spec.timeout,
        "thinking_mode": spec.thinking_mode,
        "request_path": spec.request_path,
        "strict_tools": spec.strict_tools,
    }


def _profile_to_dict(profile: ChildProfile) -> dict:
    return {
        "runner_version": profile.runner_version,
        "provider_profile_id": profile.provider_profile_id,
        "provider_destination": profile.provider_destination,
        "workspace_scope_digest": profile.workspace_scope_digest,
        "max_input_tokens": profile.max_input_tokens,
        "max_output_tokens": profile.max_output_tokens,
        "limits_digest": profile.limits_digest,
        "hard_deadline_seconds": profile.hard_deadline_seconds,
    }


def _status_from_name(name: object) -> RunStatus:
    if isinstance(name, str):
        for status in RunStatus:
            if status.value == name:
                return status
    return RunStatus.FAILED_FATAL


def _parse_result(stdout: bytes) -> dict | None:
    try:
        parsed = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict) or "status" not in parsed:
        return None
    return parsed


def _read_bounded(stream, max_bytes: int) -> bytes | None:
    """读取 child stdout 最多 ``max_bytes + 1`` 字节以检测 overflow；超出返回 None。

    child 在退出前一次性写完全部结果并关闭 stdout（EOF），故 ``read(max_bytes + 1)``
    不会无限阻塞：返回 ``len <= max_bytes`` 的完整结果，或 ``max_bytes + 1``（oversized → None）。
    绝不无界 read。
    """
    if stream is None:
        return b""
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        return None
    return data

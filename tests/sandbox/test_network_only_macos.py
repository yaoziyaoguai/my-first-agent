"""danger/off network-only Seatbelt 的真实本机验证。

只用 loopback（127.0.0.1）与 pytest 临时 fixture，不访问互联网。所有
Darwin 上的真实探针都有可用正对照：同一 prepare→confiner→executor→
runner 管道在 danger/full bypass 下必须能把随机 nonce 送到 loopback
server——正对照失败即测试失败，绝不把 DNS 失败、ECONNREFUSED、profile
加载失败或全 skip 当作隔离成功。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import shlex
import socket
import threading
from types import SimpleNamespace

import pytest

from agent.process.preparation import prepare_process
from agent.process.runner import run_local_process
from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox.contracts import (
    SandboxDraftOutcome,
    SandboxMode,
    SandboxNetworkMode,
)
from agent.sandbox.executor import NativeSandboxExecutor
from agent.sandbox.policy import (
    NETWORK_ONLY_SEATBELT_PROFILE,
    build_sandbox_policy,
)
from agent.sandbox.seatbelt import SeatbeltConfiner
from agent.sandbox.shell import build_shell_exec_registration

CAPTURED_PATH = "/usr/bin:/bin"
darwin_only = pytest.mark.skipif(
    platform.system() != "Darwin", reason="real Seatbelt is Darwin-only"
)

# 直连 client：直接 IP（不经 DNS），捕获异常类型作为结果 marker——只有
# PermissionError 才是 Seatbelt 网络拒绝；ECONNREFUSED/gaierror 不算。
_CLIENT_CODE = (
    "import socket, sys\n"
    "host, port, nonce = sys.argv[1], int(sys.argv[2]), sys.argv[3]\n"
    "try:\n"
    "    s = socket.create_connection((host, port), timeout=5)\n"
    "except Exception as e:\n"
    "    print('CONNECT_' + type(e).__name__)\n"
    "else:\n"
    "    try:\n"
    "        s.sendall(nonce.encode())\n"
    "        print('SENT')\n"
    "    finally:\n"
    "        s.close()\n"
)

# 真实 fork 子进程 harness：sandboxed child 再 exec 一个 grandchild client。
_PARENT_CODE = (
    "import subprocess, sys\n"
    "r = subprocess.run(\n"
    "    ['/usr/bin/python3', '-c', sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]],\n"
    "    capture_output=True, text=True,\n"
    ")\n"
    "print('PARENT_RC', r.returncode)\n"
    "sys.stdout.write(r.stdout)\n"
    "sys.stdout.write(r.stderr[-200:])\n"
)


class LoopbackServer:
    """test 进程内的 127.0.0.1 ephemeral TCP server；记录收到的全部 bytes。"""

    def __init__(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(4)
        self._socket.settimeout(0.2)
        self.port = self._socket.getsockname()[1]
        self.received: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _peer = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                try:
                    data = conn.recv(4096)
                    if data:
                        self.received.append(data)
                        conn.sendall(b"ack")
                except OSError:
                    pass

    def __enter__(self) -> LoopbackServer:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._socket.close()


def _roots(tmp_path):  # noqa: ANN001, ANN202
    """四个 canonical policy roots；fixture 目录刻意在 workspace 之外。"""

    roots = {}
    for name in ("workspace", "temp_root", "state_root", "home"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    return roots


def _emit_evidence(probe: str, **facts: object) -> None:
    """``pytest -s`` 时输出可保存的 bounded 本机验证记录。"""

    print(
        json.dumps(
            {
                "probe": probe,
                "macos_product": platform.mac_ver()[0],
                "kernel_release": platform.release(),
                "architecture": platform.machine(),
                "backend": "/usr/bin/sandbox-exec",
                **facts,
            },
            sort_keys=True,
        )
    )


def _policy(roots, *, mode=SandboxMode.DANGER_FULL_ACCESS):  # noqa: ANN001, ANN202
    return build_sandbox_policy(
        mode=mode,
        network=SandboxNetworkMode.OFF,
        workspace=roots["workspace"],
        temp_root=roots["temp_root"],
        state_root=roots["state_root"],
        home=roots["home"],
        private_roots=(),
    )


def _prepared(executable: str, argv: list[str], roots):  # noqa: ANN001, ANN202
    prepared = prepare_process(
        {"executable": executable, "argv": argv, "cwd": ".", "profile": "short"},
        workspace=roots["workspace"],
        captured_path=CAPTURED_PATH,
    )
    assert not isinstance(prepared, KnownNotExecuted)
    return prepared


def _executor():  # noqa: ANN202
    return NativeSandboxExecutor(
        confiner=SeatbeltConfiner(), captured_path=CAPTURED_PATH,
    )


def _run(executable: str, argv: list[str], policy, roots):  # noqa: ANN001, ANN202
    """真实 sandbox-exec → run_local_process 一次；返回 sandbox draft。"""

    draft = _executor().execute(_prepared(executable, argv, roots), policy)
    assert isinstance(draft, KnownNotExecuted) is False, draft
    return draft


def _run_shell(
    command: str,
    roots,
    *,
    mode: str = "workspace-write",
    timeout_seconds: int = 120,
):  # noqa: ANN001, ANN202
    """真实 shell registration → confiner → runner 一次。"""

    registration = build_shell_exec_registration(
        workspace=roots["workspace"],
        temp_root=roots["temp_root"],
        state_root=roots["state_root"],
        home=roots["home"],
        captured_path=CAPTURED_PATH,
        confiner=SeatbeltConfiner(),
    )
    arguments = {
        "command": command,
        "mode": mode,
        "timeout_seconds": timeout_seconds,
    }
    binding = registration.prepare_binding(arguments)
    draft = registration.func(
        SimpleNamespace(arguments=arguments, safety_binding=binding),
    )
    assert isinstance(draft, KnownNotExecuted) is False, draft
    return draft


@darwin_only
def test_positive_control_bypass_pipeline_delivers_nonce_to_server(tmp_path):
    """正对照：同一执行管道在 danger/full bypass 下必须送达 loopback nonce。

    它证明 client 代码、server、runner 与环境都可用——后续 danger/off 的
    拒绝只能归因于 Seatbelt network 限制，而非管道故障。
    """

    roots = _roots(tmp_path)
    policy = build_sandbox_policy(
        mode=SandboxMode.DANGER_FULL_ACCESS,
        network=SandboxNetworkMode.FULL,
        workspace=roots["workspace"],
        temp_root=roots["temp_root"],
        state_root=roots["state_root"],
        home=roots["home"],
        private_roots=(),
    )
    nonce = f"pc-{secrets.token_hex(8)}"
    with LoopbackServer() as server:
        draft = _run(
            "/usr/bin/python3",
            ["-c", _CLIENT_CODE, "127.0.0.1", str(server.port), nonce],
            policy,
            roots,
        )
        assert draft.outcome is SandboxDraftOutcome.EXITED
        assert draft.exit_code == 0
        assert "SENT" in draft.stdout_projection, draft.stderr_projection
        assert nonce.encode() in b"".join(server.received)
    assert draft.enforcement.backend == "none"
    assert draft.enforcement.network is SandboxNetworkMode.FULL
    _emit_evidence(
        "danger_full_positive_control",
        command="/usr/bin/python3 -c <tcp-client> 127.0.0.1:<ephemeral>",
        outcome=draft.outcome.value,
        result="SENT",
        nonce_received=True,
        policy_digest=policy.policy_digest,
        profile_digest="",
    )


@darwin_only
def test_danger_off_blocks_direct_ip_tcp_and_server_receives_nothing(tmp_path):
    """danger/off IPv4 直连发送随机 nonce：PermissionError 且 server 未收到。"""

    roots = _roots(tmp_path)
    policy = _policy(roots)
    nonce = f"sbx-{secrets.token_hex(8)}"
    with LoopbackServer() as server:
        draft = _run(
            "/usr/bin/python3",
            ["-c", _CLIENT_CODE, "127.0.0.1", str(server.port), nonce],
            policy,
            roots,
        )
        assert draft.outcome is SandboxDraftOutcome.EXITED
        assert draft.exit_code == 0
        # 只有 PermissionError（EPERM）算 Seatbelt 网络拒绝。
        assert "CONNECT_PermissionError" in draft.stdout_projection, (
            draft.stderr_projection
        )
        assert "SENT" not in draft.stdout_projection
        assert nonce.encode() not in b"".join(server.received)
    # enforcement facts 绑定 network-only profile 字节（danger/off confined）。
    assert draft.enforcement.backend == "seatbelt"
    assert draft.enforcement.enforcement == "confined"
    assert draft.enforcement.mode is SandboxMode.DANGER_FULL_ACCESS
    assert draft.enforcement.network is SandboxNetworkMode.OFF
    assert draft.enforcement.profile_digest == hashlib.sha256(
        NETWORK_ONLY_SEATBELT_PROFILE.encode(),
    ).hexdigest()
    _emit_evidence(
        "danger_off_tcp_denial",
        command="/usr/bin/python3 -c <tcp-client> 127.0.0.1:<ephemeral>",
        outcome=draft.outcome.value,
        result="CONNECT_PermissionError",
        nonce_received=False,
        policy_digest=policy.policy_digest,
        profile_digest=draft.enforcement.profile_digest,
    )


@darwin_only
def test_shell_registration_blocks_direct_ip_tcp(tmp_path):
    """shell_exec 的真实公开路径固定 network=off，而不只是 executor 单测。"""

    roots = _roots(tmp_path)
    nonce = f"shell-{secrets.token_hex(8)}"
    with LoopbackServer() as server:
        command = shlex.join(
            [
                "/usr/bin/python3",
                "-c",
                _CLIENT_CODE,
                "127.0.0.1",
                str(server.port),
                nonce,
            ]
        )
        draft = _run_shell(
            command, roots, mode="danger-full-access", timeout_seconds=10,
        )
        assert draft.outcome is SandboxDraftOutcome.EXITED
        assert draft.exit_code == 0
        assert "CONNECT_PermissionError" in draft.stdout_projection, (
            draft.stderr_projection
        )
        assert "SENT" not in draft.stdout_projection
        assert nonce.encode() not in b"".join(server.received)
    assert draft.enforcement.backend == "seatbelt"
    assert draft.enforcement.network is SandboxNetworkMode.OFF
    _emit_evidence(
        "shell_exec_tcp_denial",
        command="/bin/sh -c </usr/bin/python3 tcp-client>",
        outcome=draft.outcome.value,
        result="CONNECT_PermissionError",
        nonce_received=False,
        profile_digest=draft.enforcement.profile_digest,
    )


@darwin_only
def test_danger_off_blocks_real_forked_grandchild_tcp(tmp_path):
    """真实 fork/exec 的 grandchild 同样被拒绝，server 未收到 nonce。"""

    roots = _roots(tmp_path)
    policy = _policy(roots)
    nonce = f"grand-{secrets.token_hex(8)}"
    grandchild_marker = f"GRAND_{secrets.token_hex(4)}"
    grandchild_code = _CLIENT_CODE.replace("print('CONNECT_'", f"print('{grandchild_marker}_'")
    with LoopbackServer() as server:
        draft = _run(
            "/usr/bin/python3",
            [
                "-c", _PARENT_CODE, grandchild_code,
                "127.0.0.1", str(server.port), nonce,
            ],
            policy,
            roots,
        )
        assert draft.outcome is SandboxDraftOutcome.EXITED
        assert draft.exit_code == 0
        assert "PARENT_RC 0" in draft.stdout_projection, draft.stderr_projection
        assert f"{grandchild_marker}_PermissionError" in draft.stdout_projection, (
            draft.stderr_projection
        )
        assert nonce.encode() not in b"".join(server.received)


@darwin_only
def test_danger_off_reads_and_writes_fixture_outside_workspace(tmp_path):
    """danger/off 无 filesystem 限制：workspace 外 fixture 可读可写。"""

    roots = _roots(tmp_path)
    policy = _policy(roots)
    fixture = tmp_path / "outside" / "fixture"
    fixture.mkdir(parents=True)
    seed = fixture / "seed.txt"
    probe = fixture / "probe.txt"
    seed.write_text("seed-content\n", encoding="utf-8")
    command = f"printf danger-ok > '{probe}'; cat '{seed}'"
    draft = _run("/bin/sh", ["-c", command], policy, roots)
    assert draft.outcome is SandboxDraftOutcome.EXITED
    assert draft.exit_code == 0
    assert "seed-content" in draft.stdout_projection
    assert (fixture / "probe.txt").read_text(encoding="utf-8") == "danger-ok"


@darwin_only
def test_shell_registration_workspace_write_and_read_only_are_real(tmp_path):
    roots = _roots(tmp_path)
    writable = roots["workspace"] / "write.txt"
    readonly = roots["workspace"] / "blocked.txt"

    write = _run_shell(
        f"printf shell-ok > {shlex.quote(str(writable))}", roots,
    )
    assert write.outcome is SandboxDraftOutcome.EXITED
    assert write.exit_code == 0
    assert writable.read_text(encoding="utf-8") == "shell-ok"

    blocked = _run_shell(
        f"printf must-not-exist > {shlex.quote(str(readonly))}",
        roots,
        mode="read-only",
    )
    assert blocked.outcome is SandboxDraftOutcome.EXITED
    assert blocked.exit_code != 0
    assert not readonly.exists()


def test_missing_backend_reaches_zero_target_runner(tmp_path):
    """缺 backend：qualification fail closed，零目标 runner（host 无关）。"""

    roots = _roots(tmp_path)
    policy = _policy(roots)
    calls: list[dict] = []

    def spy_runner(**kwargs):  # noqa: ANN003
        calls.append(kwargs)
        return run_local_process(**kwargs)

    executor = NativeSandboxExecutor(
        confiner=SeatbeltConfiner(platform_system="Linux"),
        captured_path=CAPTURED_PATH,
        runner=spy_runner,
    )
    prepared = _prepared("/usr/bin/python3", ["-c", "print('must-not-run')"], roots)
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "unsupported_platform"
    assert calls == []


@darwin_only
def test_exact_timeout_kills_background_group_at_approved_deadline(tmp_path):
    """exact timeout：批准 11s（standard 档位）杀掉 sleep 15 与后台子进程。

    wall deadline 若被向上取整到档位上限（120s），sleep 15 会正常 EXITED；
    断言 TIMED_OUT_REAPED + duration ~11s 证明 deadline 精确等于批准值。
    后台 process group 被 TERM/KILL/reap：killpg probe 确认组已消失。
    """

    roots = _roots(tmp_path)
    pidfile = roots["workspace"] / "shell.pid"
    command = f"echo $$ > '{pidfile}'; sleep 15 & sleep 15 & wait"
    draft = _run_shell(
        command,
        roots,
        mode="danger-full-access",
        timeout_seconds=11,
    )
    assert isinstance(draft, KnownNotExecuted) is False, draft
    assert draft.outcome is SandboxDraftOutcome.TIMED_OUT_REAPED
    # deadline 精确 11s：明显小于 sleep 时长，也未被取整放大。
    assert 10.0 <= draft.duration_seconds < 14.0, draft.duration_seconds
    group_leader = int(pidfile.read_text(encoding="utf-8").strip())
    with pytest.raises(ProcessLookupError):
        os.killpg(group_leader, 0)
    _emit_evidence(
        "shell_exec_exact_timeout",
        command="/bin/sh -c <two background sleep 15; wait>",
        outcome=draft.outcome.value,
        approved_timeout_seconds=11,
        duration_seconds=round(draft.duration_seconds, 3),
        process_group_reaped=True,
        profile_digest=draft.enforcement.profile_digest,
    )

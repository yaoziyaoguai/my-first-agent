"""P5：本任务受管开发服务的公共 ToolRuntime 旅程。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from agent.composition import build_managed_web_resources
from agent.process.managed_web import build_managed_web_process_tools
from agent.runtime.contracts import (
    ApprovalRequired,
    ExecutionAuthorityClass,
    ExecutionIntent,
    ProcessAuthorityLeaseV1,
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.tools import KernelToolRuntime


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _context(*, process_leases=()) -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=7,
        approval_basis_revision=7,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="w" * 64,
        process_leases=tuple(process_leases),
    )


def _lease(candidate) -> ProcessAuthorityLeaseV1:  # noqa: ANN001
    return ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity="approval-managed-web",
        issued_at=candidate.issued_at,
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=0,
    )


def _server_script(workspace: Path) -> str:
    script = workspace / "server.py"
    script.write_text(
        f"#!{sys.executable}\n"
        "from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer\n"
        "import sys\n"
        "server = ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), "
        "SimpleHTTPRequestHandler)\n"
        "print('READY', flush=True)\n"
        "server.serve_forever()\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    return "./server.py"


def test_managed_web_surface_is_small_and_governed(tmp_path: Path) -> None:
    bundle = build_managed_web_process_tools(
        workspace=tmp_path,
        captured_path=os.environ.get("PATH", ""),
    )
    specs = {registration.spec.name: registration.spec for registration in bundle.registrations}

    assert tuple(specs) == (
        "managed_web_start",
        "managed_web_observe",
        "managed_web_stop",
    )
    assert specs["managed_web_start"].execution_authority is (
        ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
    )
    assert specs["managed_web_start"].side_effect is SideEffectClass.EXTERNAL
    assert specs["managed_web_observe"].side_effect is SideEffectClass.READ_ONLY
    assert specs["managed_web_stop"].side_effect is SideEffectClass.EXTERNAL
    assert all(spec.input_schema["additionalProperties"] is False for spec in specs.values())
    assert specs["managed_web_start"].input_schema["properties"]["profile"] == {
        "type": "string",
        "enum": ["long"],
        "description": "fixed 900-second hard lifetime for multi-step browser validation",
    }
    bundle.close()


def test_managed_web_defaults_to_long_profile_for_browser_validation(
    tmp_path: Path,
) -> None:
    bundle = build_managed_web_process_tools(
        workspace=tmp_path,
        captured_path=os.environ.get("PATH", ""),
    )
    runtime = KernelToolRuntime(bundle.registrations)

    prepared = runtime.prepare(
        ToolCall(
            "start-default-profile",
            "managed_web_start",
            {"executable": sys.executable, "loopback_port": _free_port()},
        ),
        _context(),
    )

    assert isinstance(prepared, ApprovalRequired)
    assert prepared.request.process_authority_candidate.resource_profile == "long"
    assert 'profile="long"' in prepared.request.preview
    bundle.close()


def test_managed_web_rejects_non_owner_only_cleanup_receipt_root(
    tmp_path: Path,
) -> None:
    cleanup_root = tmp_path / "cleanup"
    cleanup_root.mkdir(mode=0o755)

    with pytest.raises(ValueError, match="owner-only"):
        build_managed_web_process_tools(
            workspace=tmp_path,
            captured_path=os.environ.get("PATH", ""),
            cleanup_receipt_root=cleanup_root,
        )


def test_composition_exposes_one_owner_and_one_cleanup(tmp_path: Path) -> None:
    resources = build_managed_web_resources(
        tmp_path,
        captured_path=os.environ.get("PATH", ""),
    )

    assert len(resources.registrations) == 3
    assert len(resources.closeables) == 1
    assert resources.registrations[0].func.__self__ is resources.owner
    resources.closeables[0]()


def test_managed_web_start_observe_stop_and_loopback_binding(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = _server_script(workspace)
    port = _free_port()
    bundle = build_managed_web_process_tools(
        workspace=workspace,
        captured_path=os.environ.get("PATH", ""),
    )
    runtime = KernelToolRuntime(
        bundle.registrations,
        clock=lambda: "2026-09-13T12:00:00Z",
    )
    arguments = {
        "executable": executable,
        "argv": [str(port)],
        "cwd": ".",
        "profile": "long",
        "loopback_port": port,
    }
    call = ToolCall("start-1", "managed_web_start", arguments)

    approval = runtime.prepare(call, _context())
    assert isinstance(approval, ApprovalRequired)
    assert f"http://127.0.0.1:{port}" in approval.request.preview
    intent = runtime.prepare(
        call,
        _context(process_leases=(_lease(approval.request.process_authority_candidate),)),
    )
    assert isinstance(intent, ExecutionIntent)
    started = runtime.invoke(intent)
    assert started.is_error is False
    payload = json.loads(started.content)
    resource_ref = payload["resource_ref"]
    binding = bundle.owner.loopback_binding(
        resource_ref,
        goal_id="goal-1",
        goal_revision=1,
    )
    assert binding.origin == f"http://127.0.0.1:{port}"
    assert bundle.owner.verify_loopback_binding(binding) is True

    observed = runtime.invoke(
        runtime.prepare(
            ToolCall(
                "observe-1",
                "managed_web_observe",
                {"resource_ref": resource_ref},
            ),
            _context(),
        )
    )
    observation = json.loads(observed.content)
    assert observation["active"] is True
    assert "READY" in observation["stdout"]

    stopped = runtime.invoke(
        runtime.prepare(
            ToolCall("stop-1", "managed_web_stop", {"resource_ref": resource_ref}),
            _context(),
        )
    )
    assert json.loads(stopped.content)["cleanup"] == "confirmed"
    assert bundle.owner.verify_loopback_binding(binding) is False
    bundle.close()


def test_managed_web_clean_restart_can_confirm_prior_owner_cleanup(
    tmp_path: Path,
) -> None:
    """正常退出已确认回收后，新 composition 仍能铸造准确 stop receipt。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cleanup_root = tmp_path / "state" / "managed-web-cleanup"
    executable = _server_script(workspace)
    port = _free_port()
    first = build_managed_web_process_tools(
        workspace=workspace,
        captured_path=os.environ.get("PATH", ""),
        cleanup_receipt_root=cleanup_root,
    )
    first_runtime = KernelToolRuntime(first.registrations)
    arguments = {
        "executable": executable,
        "argv": [str(port)],
        "cwd": ".",
        "profile": "long",
        "loopback_port": port,
    }
    call = ToolCall("start-restart", "managed_web_start", arguments)
    approval = first_runtime.prepare(call, _context())
    assert isinstance(approval, ApprovalRequired)
    intent = first_runtime.prepare(
        call,
        _context(process_leases=(_lease(approval.request.process_authority_candidate),)),
    )
    started = first_runtime.invoke(intent)
    resource_ref = json.loads(started.content)["resource_ref"]

    first.close()
    with socket.socket() as probe:
        probe.settimeout(0.2)
        assert probe.connect_ex(("127.0.0.1", port)) != 0

    reopened = build_managed_web_process_tools(
        workspace=workspace,
        captured_path=os.environ.get("PATH", ""),
        cleanup_receipt_root=cleanup_root,
    )
    reopened_runtime = KernelToolRuntime(reopened.registrations)
    stop_intent = reopened_runtime.prepare(
        ToolCall(
            "stop-after-restart",
            "managed_web_stop",
            {"resource_ref": resource_ref},
        ),
        _context(),
    )
    assert isinstance(stop_intent, ExecutionIntent)
    stopped = reopened_runtime.invoke(stop_intent)
    assert stopped.is_error is False
    assert json.loads(stopped.content) == {
        "resource_ref": resource_ref,
        "cleanup": "confirmed",
    }
    reopened.close()


def test_managed_web_refuses_an_already_owned_port_before_spawn(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = _server_script(workspace)
    bundle = build_managed_web_process_tools(
        workspace=workspace,
        captured_path=os.environ.get("PATH", ""),
    )
    runtime = KernelToolRuntime(bundle.registrations)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = int(occupied.getsockname()[1])
        call = ToolCall(
            "start-busy",
            "managed_web_start",
            {
                "executable": executable,
                "argv": [str(port)],
                "cwd": ".",
                "profile": "long",
                "loopback_port": port,
            },
        )
        approval = runtime.prepare(call, _context())
        intent = runtime.prepare(
            call,
            _context(process_leases=(_lease(approval.request.process_authority_candidate),)),
        )
        result = runtime.invoke(intent)

    assert result.is_error is True
    assert result.executed is False
    assert result.metadata["code"] == "loopback_port_unavailable"
    bundle.close()


def test_managed_web_readiness_rejects_listener_from_another_process_group(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """模拟端口预检后被其它进程抢占；仅“连接成功”不能铸造 task binding。"""

    import agent.process.managed_web as managed_web

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sleeper = workspace / "sleep.py"
    sleeper.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n",
        encoding="utf-8",
    )
    sleeper.chmod(0o700)
    bundle = build_managed_web_process_tools(
        workspace=workspace,
        captured_path=os.environ.get("PATH", ""),
    )
    runtime = KernelToolRuntime(bundle.registrations)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = int(occupied.getsockname()[1])
        monkeypatch.setattr(managed_web, "_port_available", lambda _port: True)
        call = ToolCall(
            "start-raced",
            "managed_web_start",
            {
                "executable": str(sleeper),
                "argv": [],
                "cwd": ".",
                "profile": "long",
                "loopback_port": port,
            },
        )
        approval = runtime.prepare(call, _context())
        intent = runtime.prepare(
            call,
            _context(
                process_leases=(_lease(approval.request.process_authority_candidate),)
            ),
        )

        result = runtime.invoke(intent)

    assert result.executed is True
    assert result.is_error is True
    assert result.metadata["code"] == "managed_process_not_ready"
    bundle.close()


def test_managed_web_supervisor_closes_service_when_parent_pipe_disappears(
    tmp_path: Path,
) -> None:
    """模拟 First Agent 被杀：control writer 消失后，服务组无需用户介入即消失。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = _server_script(workspace)
    port = _free_port()
    supervisor = (
        Path(__file__).parents[2] / "agent" / "process" / "managed_web_child.py"
    )
    read_fd, write_fd = os.pipe()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(supervisor),
            "--control-fd",
            str(read_fd),
            "--lifetime-seconds",
            "30",
            "--",
            str(workspace / executable.removeprefix("./")),
            str(port),
        ],
        cwd=workspace,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        pass_fds=(read_fd,),
    )
    os.close(read_fd)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("fixture server did not become ready")

        os.close(write_fd)
        write_fd = -1
        proc.wait(timeout=5)
        with socket.socket() as probe:
            probe.settimeout(0.2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        if proc.poll() is None:
            os.killpg(proc.pid, 9)
            proc.wait(timeout=5)


def test_managed_web_supervisor_enforces_lifetime_with_parent_alive(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = _server_script(workspace)
    port = _free_port()
    supervisor = (
        Path(__file__).parents[2] / "agent" / "process" / "managed_web_child.py"
    )
    read_fd, write_fd = os.pipe()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(supervisor),
            "--control-fd",
            str(read_fd),
            "--lifetime-seconds",
            "2.0",
            "--",
            str(workspace / executable.removeprefix("./")),
            str(port),
        ],
        cwd=workspace,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        pass_fds=(read_fd,),
    )
    os.close(read_fd)
    try:
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("fixture server did not become ready")
        proc.wait(timeout=5)
        with socket.socket() as probe:
            probe.settimeout(0.2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        os.close(write_fd)
        if proc.poll() is None:
            os.killpg(proc.pid, 9)
            proc.wait(timeout=5)


def test_managed_web_supervisor_reaps_descendants_when_direct_child_exits(
    tmp_path: Path,
) -> None:
    """启动器退出不等于服务结束；同组后代仍必须在 lifetime 内回收。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    descendant_pid_path = workspace / "descendant.pid"
    launcher = workspace / "launcher.py"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "import pathlib\n"
        "import subprocess\n"
        "import sys\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(30)'])\n"
        f"pathlib.Path({str(descendant_pid_path)!r}).write_text(str(child.pid))\n",
        encoding="utf-8",
    )
    launcher.chmod(0o700)
    supervisor = (
        Path(__file__).parents[2] / "agent" / "process" / "managed_web_child.py"
    )
    read_fd, write_fd = os.pipe()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(supervisor),
            "--control-fd",
            str(read_fd),
            "--lifetime-seconds",
            "0.5",
            "--",
            sys.executable,
            str(launcher),
        ],
        cwd=workspace,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        pass_fds=(read_fd,),
    )
    os.close(read_fd)
    descendant_pid: int | None = None
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not descendant_pid_path.exists():
            time.sleep(0.02)
        assert descendant_pid_path.exists(), "launcher did not publish descendant pid"
        descendant_pid = int(descendant_pid_path.read_text())
        assert os.getpgid(descendant_pid) == proc.pid

        proc.wait(timeout=4)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("managed descendant survived supervisor lifetime")
    finally:
        os.close(write_fd)
        if proc.poll() is None:
            os.killpg(proc.pid, 9)
            proc.wait(timeout=5)
        elif descendant_pid is not None:
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, 9)

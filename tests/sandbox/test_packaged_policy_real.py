"""Darwin 上 strict packaged profile 的非真空真实 Seatbelt 探针。"""

from __future__ import annotations

import hashlib
import json
import platform
import socket
import sys
import sysconfig
from pathlib import Path

import pytest

from agent.process.preparation import PreparedProcessV1, prepare_process
from agent.runtime.contracts import canonical_json_digest
from agent.sandbox.contracts import (
    PackagedSkillResourceLimitsV1,
    SandboxDraftOutcome,
    StructuredReadbackOutcome,
    StructuredResultKind,
    StructuredSandboxIoPlanV1,
    StructuredSandboxProcessDraftV1,
)
from agent.sandbox.executor import NativeSandboxExecutor
from agent.sandbox.packaged_policy import build_packaged_skill_policy
from agent.sandbox.seatbelt import SeatbeltConfiner

pytestmark = pytest.mark.skipif(
    platform.system() != "Darwin", reason="real Seatbelt is Darwin-only"
)


class RealPackagedPolicyFixture:
    def __init__(self, root: Path) -> None:
        self.workspace = root / "workspace"
        self.runtime = root / "runtime"
        self.package = root / "package"
        self.temp = root / "temp"
        self.home = root / "home"
        self.state = root / "state"
        self.private = root / "private"
        for path in (
            self.workspace,
            self.runtime,
            self.package,
            self.temp,
            self.home,
            self.state,
            self.private,
        ):
            path.mkdir()
        self.runtime_file = self.runtime / "allowed.txt"
        self.runtime_file.write_text("runtime", encoding="utf-8")
        self.workspace_file = self.workspace / "denied.txt"
        self.workspace_file.write_text("workspace", encoding="utf-8")
        self.home_file = self.home / "denied.txt"
        self.home_file.write_text("home", encoding="utf-8")
        self.private_file = self.private / "denied.txt"
        self.private_file.write_text("private", encoding="utf-8")
        package_scripts = self.package / "scripts"
        package_scripts.mkdir()
        self.package_file = package_scripts / "allowed.py"
        self.package_file.write_text("allowed", encoding="utf-8")
        self.package_sibling = package_scripts / "denied.py"
        self.package_sibling.write_text("denied", encoding="utf-8")
        for path in (self.runtime, self.package):
            path.chmod(0o555)
        self.interpreter = Path(sys.executable).resolve()
        library_dir = sysconfig.get_config_var("LIBDIR")
        assert isinstance(library_dir, str)
        self.system_runtime_roots = (
            self.interpreter.parent,
            Path(library_dir).resolve(),
        )
        self.system_runtime_digest = canonical_json_digest(
            {"roots": [str(root) for root in self.system_runtime_roots]}
        )
        self.policy = build_packaged_skill_policy(
            interpreter_path=self.interpreter,
            runtime_roots=(self.runtime,),
            package_root=self.package,
            temp_root=self.temp,
            system_runtime_roots=self.system_runtime_roots,
            workspace_root=self.workspace,
            home_root=self.home,
            state_root=self.state,
            private_roots=(self.private,),
            runtime_closure_digest=hashlib.sha256(b"real-runtime").hexdigest(),
            system_runtime_digest=self.system_runtime_digest,
            resource_limits=PackagedSkillResourceLimitsV1.for_profile(
                "skill-standard-v1"
            ),
            package_read_paths=("scripts/allowed.py",),
        )
        self.executor = NativeSandboxExecutor(
            confiner=SeatbeltConfiner(), captured_path=str(self.interpreter.parent)
        )

    def run(self, probe: str) -> str:
        code = self._probe_code(probe)
        prepared = prepare_process(
            {
                "executable": str(self.interpreter),
                "argv": ["-I", "-S", "-c", code],
                "cwd": ".",
                "profile": "short",
            },
            workspace=self.package,
            captured_path=str(self.interpreter.parent),
        )
        assert isinstance(prepared, PreparedProcessV1)
        plan = StructuredSandboxIoPlanV1(
            package_digest="a" * 64,
            entrypoint_id="real-probe",
            entrypoint_digest="b" * 64,
            request_bytes=b"{}",
            request_digest=hashlib.sha256(b"{}").hexdigest(),
            inputs=(),
            result_cap_bytes=1024,
            artifact_cap_bytes=1024,
            aggregate_output_cap_bytes=2048,
            expected_result_kind=StructuredResultKind.OBSERVATION,
        )
        result = self.executor.execute(prepared, self.policy, io_plan=plan)
        assert isinstance(result, StructuredSandboxProcessDraftV1)
        assert result.process.outcome is SandboxDraftOutcome.EXITED, (
            result.process.stderr_projection
        )
        assert result.process.exit_code == 0
        assert result.readback_outcome is StructuredReadbackOutcome.VALID
        decoded = json.loads(result.result_bytes)
        return decoded["payload"]["verdict"]

    def _probe_code(self, probe: str) -> str:
        operation = {
            "read_runtime": f"open({str(self.runtime_file)!r}, 'rb').read()",
            "read_workspace": f"open({str(self.workspace_file)!r}, 'rb').read()",
            "read_home": f"open({str(self.home_file)!r}, 'rb').read()",
            "read_private": f"open({str(self.private_file)!r}, 'rb').read()",
            "read_package_file": f"open({str(self.package_file)!r}, 'rb').read()",
            "read_package_sibling": f"open({str(self.package_sibling)!r}, 'rb').read()",
            "network_connect": "socket.create_connection(('127.0.0.1', PORT), timeout=1.0)",
            "fork": "fork_once()",
            "exec_true": "exec_true()",
            "create_scratch": "open(os.path.join(session, 'scratch.txt'), 'xb').close()",
            "unlink_result": "os.unlink(os.path.join(session, 'result.json'))",
            "write_result": "None",
        }[probe]
        return f"""
import errno
import json
import os
import socket

PORT = {self._listener_port!r}
session = os.environ['TMPDIR']

def write(verdict):
    payload = {{
        'protocol': 'first-agent-skill-result-v1',
        'kind': 'observation',
        'payload': {{'verdict': verdict}},
    }}
    with open(os.path.join(session, 'result.json'), 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, sort_keys=True, separators=(',', ':'))

def fork_once():
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)

def exec_true():
    write('allowed')
    os.execv('/usr/bin/true', ['/usr/bin/true'])

try:
    {operation}
except OSError as error:
    verdict = (
        'denied'
        if error.errno in (errno.EPERM, errno.EACCES)
        else f'unexpected:{{error.errno}}'
    )
else:
    verdict = 'allowed'
write(verdict)
"""

    @property
    def _listener_port(self) -> int:
        return self._listener.getsockname()[1]

    def start_listener(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)

    def stop_listener(self) -> None:
        self._listener.close()


@pytest.fixture
def real_fixture(tmp_path: Path):
    fixture = RealPackagedPolicyFixture(tmp_path)
    fixture.start_listener()
    try:
        with socket.create_connection(("127.0.0.1", fixture._listener_port), timeout=1.0):
            pass
        yield fixture
    finally:
        fixture.stop_listener()


@pytest.mark.parametrize(
    ("probe", "expected"),
    [
        ("read_runtime", "allowed"),
        ("read_workspace", "denied"),
        ("read_home", "denied"),
        ("read_private", "denied"),
        ("read_package_file", "allowed"),
        ("read_package_sibling", "denied"),
        ("network_connect", "denied"),
        ("fork", "denied"),
        ("exec_true", "denied"),
        ("create_scratch", "denied"),
        ("unlink_result", "denied"),
        ("write_result", "allowed"),
    ],
)
def test_real_packaged_policy_probe(
    probe: str, expected: str, real_fixture: RealPackagedPolicyFixture
) -> None:
    if expected == "denied":
        assert real_fixture.run("read_runtime") == "allowed"
        assert real_fixture.run("write_result") == "allowed"
    assert real_fixture.run(probe) == expected

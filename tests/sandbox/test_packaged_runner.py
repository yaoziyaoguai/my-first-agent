"""standalone packaged-Skill runner 的封闭 wire/preflight 合同。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import first_agent_skill_runner.__main__ as skill_runner
from agent.sandbox.contracts import PackagedSkillResourceLimitsV1
from first_agent_skill_runner.__main__ import RunnerProtocolError, run_request

_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "020a_noop_skill" / "scripts"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


@dataclass
class SessionFixture:
    package_root: Path
    session_root: Path
    request: Path
    input_bytes: bytes
    resource_limits_digest: str
    script: str

    def _script_path(self) -> Path:
        return self.package_root / self.script

    def _write_request(self) -> None:
        script_bytes = self._script_path().read_bytes()
        request = {
            "protocol": "first-agent-skill-request-v1",
            "package_digest": "a" * 64,
            "entrypoint_id": "inspect",
            "entrypoint_script": {
                "path": self.script,
                "size": len(script_bytes),
                "sha256": hashlib.sha256(script_bytes).hexdigest(),
            },
            "arguments": {"entrypoint": "inspect"},
            "inputs": [
                {
                    "slot": "source",
                    "size": len(self.input_bytes),
                    "sha256": hashlib.sha256(self.input_bytes).hexdigest(),
                    "allowed_magic_hex": ["25504446"],
                }
            ],
            "expected_result_kind": "observation",
            "resource_limits_digest": self.resource_limits_digest,
        }
        self.request.write_bytes(_canonical_json(request))
        self.request.chmod(0o400)

    def set_resource_limits_digest(self, digest: str) -> None:
        self.resource_limits_digest = digest
        self.request.chmod(0o600)
        self._write_request()

    def replace_input(self, content: bytes) -> None:
        self.input_bytes = content
        input_path = self.session_root / "inputs" / "source"
        input_path.chmod(0o600)
        input_path.write_bytes(content)
        input_path.chmod(0o400)

    def use_script(self, relative_path: str, content: bytes) -> None:
        script_path = self.package_root / relative_path
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_bytes(content)
        script_path.chmod(0o444)
        self.script = relative_path
        self.request.chmod(0o600)
        self._write_request()

    def run_real_runner(self) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "first_agent_skill_runner",
                "--package",
                "a" * 64,
                "--entrypoint",
                "inspect",
            ],
            cwd=self.package_root,
            env={"TMPDIR": str(self.session_root)},
            capture_output=True,
            text=True,
            check=False,
        )
        result_path = self.session_root / "result.json"
        result = (
            json.loads(result_path.read_text(encoding="utf-8"))
            if result_path.stat().st_size
            else {}
        )
        return completed, result


@pytest.fixture
def session_fixture(tmp_path: Path) -> SessionFixture:
    package_root = tmp_path / "package"
    package_root.mkdir()
    script = "scripts/noop.py"
    target_script = package_root / script
    target_script.parent.mkdir()
    shutil.copyfile(_FIXTURE_ROOT / "noop.py", target_script)
    target_script.chmod(0o444)

    session_root = tmp_path / "session"
    inputs = session_root / "inputs"
    inputs.mkdir(parents=True)
    input_bytes = b"%PDF synthetic input"
    input_path = inputs / "source"
    input_path.write_bytes(input_bytes)
    input_path.chmod(0o400)
    for name in ("result.json", "artifact.bin"):
        output = session_root / name
        output.write_bytes(b"")
        output.chmod(0o600)
    limits = PackagedSkillResourceLimitsV1.for_profile("skill-standard-v1")
    request = session_root / "request.json"
    fixture = SessionFixture(
        package_root=package_root,
        session_root=session_root,
        request=request,
        input_bytes=input_bytes,
        resource_limits_digest=limits.limits_digest,
        script=script,
    )
    fixture._write_request()
    return fixture


@pytest.fixture
def subprocess_session_fixture(session_fixture: SessionFixture) -> SessionFixture:
    return session_fixture


@pytest.fixture
def no_limit_syscalls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_runner, "apply_hard_limits", lambda _digest: None)


@pytest.mark.parametrize("profile", ["skill-standard-v1", "artifact-standard-v1"])
def test_runner_process_applies_limits_or_refuses_before_package_load_when_unavailable(
    profile: str, subprocess_session_fixture: SessionFixture
) -> None:
    limits = PackagedSkillResourceLimitsV1.for_profile(profile)
    subprocess_session_fixture.use_script(
        "scripts/report_limits.py", (_FIXTURE_ROOT / "report_limits.py").read_bytes()
    )
    subprocess_session_fixture.set_resource_limits_digest(limits.limits_digest)

    completed, result = subprocess_session_fixture.run_real_runner()

    if completed.returncode:
        assert completed.stdout == ""
        assert completed.stderr == (
            "first-agent-skill-runner: required as limit could not be applied\n"
        )
        assert result == {}
        assert (subprocess_session_fixture.session_root / "result.json").stat().st_size == 0
        assert (subprocess_session_fixture.session_root / "artifact.bin").stat().st_size == 0
        return
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert result["payload"]["limits"] == {
        "cpu": [limits.cpu_seconds, limits.cpu_seconds],
        "as": [limits.address_space_bytes, limits.address_space_bytes],
        "fsize": [limits.file_size_bytes, limits.file_size_bytes],
        "nofile": [limits.open_files, limits.open_files],
        "core": [limits.core_bytes, limits.core_bytes],
    }


def test_fresh_child_limit_refusal_never_loads_package_script_or_emits_outputs(
    subprocess_session_fixture: SessionFixture,
) -> None:
    marker = subprocess_session_fixture.package_root / "script-loaded"
    subprocess_session_fixture.use_script(
        "scripts/load_marker.py",
        b"from pathlib import Path\n\n"
        b"Path('script-loaded').write_bytes(b'loaded')\n\n"
        b"def run(arguments, inputs):\n"
        b"    del arguments, inputs\n"
        b"    return {'kind': 'observation', 'payload': {}, 'artifact': None}\n",
    )

    completed, result = subprocess_session_fixture.run_real_runner()

    if completed.returncode == 0:
        assert marker.read_bytes() == b"loaded"
        assert result["kind"] == "observation"
        return
    assert completed.stdout == ""
    assert completed.stderr == "first-agent-skill-runner: required as limit could not be applied\n"
    assert not marker.exists()
    assert result == {}
    assert (subprocess_session_fixture.session_root / "result.json").stat().st_size == 0
    assert (subprocess_session_fixture.session_root / "artifact.bin").stat().st_size == 0


@pytest.mark.parametrize("profile", ("skill-standard-v1", "artifact-standard-v1"))
def test_apply_hard_limits_sets_every_soft_and_hard_value_from_the_closed_row(
    profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResource:
        RLIMIT_CPU = "cpu"
        RLIMIT_AS = "as"
        RLIMIT_FSIZE = "fsize"
        RLIMIT_NOFILE = "nofile"
        RLIMIT_CORE = "core"

        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[int, int]]] = []

        def getrlimit(self, _name: str) -> tuple[int, int]:
            return (2**62, 2**62)

        def setrlimit(self, name: str, values: tuple[int, int]) -> None:
            self.calls.append((name, values))

    fake = FakeResource()
    monkeypatch.setattr(skill_runner, "resource", fake)
    limits = PackagedSkillResourceLimitsV1.for_profile(profile)

    skill_runner.apply_hard_limits(limits.limits_digest)

    assert fake.calls == [
        ("cpu", (limits.cpu_seconds, 2**62)),
        ("cpu", (limits.cpu_seconds, limits.cpu_seconds)),
        ("as", (limits.address_space_bytes, 2**62)),
        ("as", (limits.address_space_bytes, limits.address_space_bytes)),
        ("fsize", (limits.file_size_bytes, 2**62)),
        ("fsize", (limits.file_size_bytes, limits.file_size_bytes)),
        ("nofile", (limits.open_files, 2**62)),
        ("nofile", (limits.open_files, limits.open_files)),
        ("core", (limits.core_bytes, 2**62)),
        ("core", (limits.core_bytes, limits.core_bytes)),
    ]


def test_as_limit_set_failure_never_loads_package_script(
    session_fixture: SessionFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AsRefusingResource:
        RLIMIT_CPU = "cpu"
        RLIMIT_AS = "as"
        RLIMIT_FSIZE = "fsize"
        RLIMIT_NOFILE = "nofile"
        RLIMIT_CORE = "core"

        def getrlimit(self, _name: str) -> tuple[int, int]:
            return (0, 2**62)

        def setrlimit(self, name: str, _values: tuple[int, int]) -> None:
            if name == self.RLIMIT_AS:
                raise ValueError("Darwin AS refusal")

    monkeypatch.setattr(skill_runner, "resource", AsRefusingResource())
    loaded: list[tuple[object, bytes]] = []

    with pytest.raises(RunnerProtocolError, match="required as limit could not be applied"):
        run_request(
            session_fixture.request,
            execute_script=lambda descriptor, content: loaded.append((descriptor, content)),
        )

    assert loaded == []


def test_runner_rejects_unknown_limit_digest_before_script_load(
    session_fixture: SessionFixture,
) -> None:
    session_fixture.set_resource_limits_digest("f" * 64)
    loaded: list[tuple[object, bytes]] = []

    with pytest.raises(RunnerProtocolError, match="not closed"):
        run_request(
            session_fixture.request,
            execute_script=lambda descriptor, content: loaded.append((descriptor, content)),
        )

    assert loaded == []


def test_agent_and_stdlib_runner_limit_tables_have_identical_digests() -> None:
    expected = {
        PackagedSkillResourceLimitsV1.for_profile(profile).limits_digest
        for profile in ("skill-standard-v1", "artifact-standard-v1")
    }

    assert set(skill_runner.LIMITS_BY_DIGEST) == expected


def test_header_and_digest_preflight_happen_before_package_load(
    session_fixture: SessionFixture, no_limit_syscalls: None
) -> None:
    session_fixture.replace_input(b"not-a-pdf")
    loaded: list[tuple[object, bytes]] = []

    with pytest.raises(RunnerProtocolError, match="preflight"):
        run_request(
            session_fixture.request,
            execute_script=lambda descriptor, content: loaded.append((descriptor, content)),
        )

    assert loaded == []


def test_package_script_receives_bytes_not_paths(
    session_fixture: SessionFixture, no_limit_syscalls: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(session_fixture.package_root)
    observed: dict[str, bytes] = {}

    def run(arguments: object, inputs: object) -> dict[str, object]:
        del arguments
        observed.update(inputs)
        return {
            "kind": "observation",
            "payload": {"size": len(observed["source"])},
            "artifact": None,
        }

    returned = run_request(
        session_fixture.request,
        execute_script=lambda _descriptor, _bytes: {"run": run},
    )

    assert observed == {"source": session_fixture.input_bytes}
    assert all(not isinstance(value, str) for value in observed.values())
    assert returned == {
        "kind": "observation",
        "payload": {"size": len(session_fixture.input_bytes)},
        "artifact": None,
    }


def test_runner_rejects_nonfinite_result_payload(
    session_fixture: SessionFixture, no_limit_syscalls: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(session_fixture.package_root)

    with pytest.raises(RunnerProtocolError, match="finite JSON"):
        run_request(
            session_fixture.request,
            execute_script=lambda _descriptor, _bytes: {
                "run": lambda _arguments, _inputs: {
                    "kind": "observation",
                    "payload": {"value": float("nan")},
                    "artifact": None,
                }
            },
        )


def test_runner_requires_precreated_fixed_result_inode(
    session_fixture: SessionFixture, no_limit_syscalls: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(session_fixture.package_root)
    (session_fixture.session_root / "result.json").unlink()

    with pytest.raises(RunnerProtocolError, match="precreated"):
        run_request(
            session_fixture.request,
            execute_script=lambda _descriptor, _bytes: {
                "run": lambda _arguments, _inputs: {
                    "kind": "observation",
                    "payload": {},
                    "artifact": None,
                }
            },
        )

    assert not (session_fixture.session_root / "result.json").exists()


def test_runner_fresh_subprocess_never_imports_agent(
    subprocess_session_fixture: SessionFixture,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; import first_agent_skill_runner.__main__; print('agent' in sys.modules)",
        ],
        cwd=subprocess_session_fixture.package_root,
        env={"TMPDIR": str(subprocess_session_fixture.session_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "False\n"


def test_main_executes_the_single_request_instance_it_authenticated(
    session_fixture: SessionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = json.loads(session_fixture.request.read_text(encoding="utf-8"))
    reads = 0

    def read_request(_path: Path, *, cap: int) -> dict[str, object]:
        nonlocal reads
        assert cap == skill_runner.STRUCTURED_REQUEST_MAX_BYTES
        reads += 1
        return request

    monkeypatch.setattr(skill_runner, "_read_exact_json", read_request)
    monkeypatch.setattr(skill_runner, "apply_hard_limits", lambda _digest: None)
    monkeypatch.setattr(skill_runner, "_read_exact_input", lambda _session, _descriptor: b"")
    monkeypatch.setattr(
        skill_runner,
        "_read_exact_script",
        lambda _package, _descriptor: (
            b"def run(arguments, inputs):\n"
            b"    del arguments, inputs\n"
            b"    return {'kind': 'observation', 'payload': {}, 'artifact': None}\n"
        ),
    )
    monkeypatch.setenv("TMPDIR", str(session_fixture.session_root))

    assert skill_runner.main(["--package", "a" * 64, "--entrypoint", "inspect"]) == 0
    assert reads == 1


def _observation_namespace() -> dict[str, object]:
    return {
        "run": lambda _arguments, _inputs: {
            "kind": "observation",
            "payload": {},
            "artifact": None,
        }
    }


def test_runner_rejects_hardlinked_result_before_loading_or_truncating_victim(
    session_fixture: SessionFixture,
    no_limit_syscalls: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(session_fixture.package_root)
    result_path = session_fixture.session_root / "result.json"
    victim = tmp_path / "hardlink-victim"
    victim.write_bytes(b"do not truncate")
    result_path.unlink()
    os.link(victim, result_path)
    loaded: list[bytes] = []

    with pytest.raises(RunnerProtocolError, match="precreated"):
        run_request(
            session_fixture.request,
            execute_script=lambda _descriptor, content: (
                loaded.append(content) or _observation_namespace()
            ),
        )

    assert loaded == []
    assert victim.read_bytes() == b"do not truncate"
    assert (session_fixture.session_root / "artifact.bin").read_bytes() == b""


def test_runner_rejects_symlinked_result_before_loading_or_touching_victim(
    session_fixture: SessionFixture,
    no_limit_syscalls: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(session_fixture.package_root)
    result_path = session_fixture.session_root / "result.json"
    victim = tmp_path / "symlink-victim"
    victim.write_bytes(b"do not touch")
    result_path.unlink()
    result_path.symlink_to(victim)
    loaded: list[bytes] = []

    with pytest.raises(RunnerProtocolError, match="precreated"):
        run_request(
            session_fixture.request,
            execute_script=lambda _descriptor, content: (
                loaded.append(content) or _observation_namespace()
            ),
        )

    assert loaded == []
    assert victim.read_bytes() == b"do not touch"
    assert (session_fixture.session_root / "artifact.bin").read_bytes() == b""


def test_runner_rejects_result_replacement_after_output_preflight(
    session_fixture: SessionFixture,
    no_limit_syscalls: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(session_fixture.package_root)
    result_path = session_fixture.session_root / "result.json"

    def replace_result(_descriptor: dict[str, object], _content: bytes) -> dict[str, object]:
        result_path.unlink()
        result_path.write_bytes(b"replacement")
        return _observation_namespace()

    with pytest.raises(RunnerProtocolError, match="precreated"):
        run_request(session_fixture.request, execute_script=replace_result)

    assert result_path.read_bytes() == b"replacement"
    assert (session_fixture.session_root / "artifact.bin").read_bytes() == b""


def test_runner_rejects_artifact_preflight_failure_before_result_or_package_load(
    session_fixture: SessionFixture,
    no_limit_syscalls: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(session_fixture.package_root)
    artifact_path = session_fixture.session_root / "artifact.bin"
    victim = tmp_path / "artifact-victim"
    victim.write_bytes(b"do not touch")
    artifact_path.unlink()
    artifact_path.symlink_to(victim)
    loaded: list[bytes] = []

    with pytest.raises(RunnerProtocolError, match="precreated"):
        run_request(
            session_fixture.request,
            execute_script=lambda _descriptor, content: (
                loaded.append(content) or _observation_namespace()
            ),
        )

    assert loaded == []
    assert (session_fixture.session_root / "result.json").read_bytes() == b""
    assert victim.read_bytes() == b"do not touch"

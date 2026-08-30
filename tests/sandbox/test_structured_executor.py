"""structured I/O 只扩展既有 NativeSandboxExecutor 的同一次 invocation。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.process.contracts import ProcessDraftOutcome
from agent.process.preparation import prepare_process
from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox.contracts import (
    ConfinedInvocationV1,
    SandboxDraftOutcome,
    SandboxEnforcementFactsV1,
    SandboxMode,
    SandboxNetworkMode,
    StructuredReadbackOutcome,
    StructuredResultKind,
    StructuredSandboxInputV1,
    StructuredSandboxIoPlanV1,
    StructuredSandboxProcessDraftV1,
    structured_invocation_digest,
)
from agent.sandbox.executor import NativeSandboxExecutor
from agent.sandbox.policy import build_sandbox_policy
from agent.sandbox.structured_session import StructuredSessionCleanupError


def _process_draft(outcome: ProcessDraftOutcome = ProcessDraftOutcome.EXITED):
    return SimpleNamespace(
        outcome=outcome,
        exit_code=0 if outcome is ProcessDraftOutcome.EXITED else None,
        signal=None,
        duration_seconds=0.1,
        stdout_bytes=0,
        stderr_bytes=0,
        stdout_digest="a" * 64,
        stderr_digest="b" * 64,
        stdout_projection="",
        stderr_projection="",
        stdout_truncated=False,
        stderr_truncated=False,
    )


def _plan() -> StructuredSandboxIoPlanV1:
    request = b'{"task":"inspect"}'
    source = b"pdf"
    return StructuredSandboxIoPlanV1(
        package_digest="a" * 64,
        entrypoint_id="inspect",
        entrypoint_digest="b" * 64,
        request_bytes=request,
        request_digest=hashlib.sha256(request).hexdigest(),
        inputs=(
            StructuredSandboxInputV1(
                slot="source",
                content=source,
                content_digest=hashlib.sha256(source).hexdigest(),
            ),
        ),
        result_cap_bytes=1024,
        artifact_cap_bytes=1024,
        aggregate_output_cap_bytes=2048,
        expected_result_kind=StructuredResultKind.OBSERVATION,
    )


def _prepared_and_policy(tmp_path):
    roots = {}
    for name in ("work", "tmp", "state", "home"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    prepared = prepare_process(
        {"executable": "/usr/bin/true", "cwd": "."},
        workspace=roots["work"],
        captured_path="/usr/bin:/bin",
    )
    policy = build_sandbox_policy(
        mode=SandboxMode.WORKSPACE_WRITE,
        network=SandboxNetworkMode.OFF,
        workspace=roots["work"],
        temp_root=roots["tmp"],
        state_root=roots["state"],
        home=roots["home"],
        private_roots=(),
    )
    return prepared, policy


class FakeConfiner:
    def __init__(self) -> None:
        self.environments: list[dict[str, str]] = []

    def confine(self, command, policy, environment):  # noqa: ANN001, ANN202
        self.environments.append(dict(environment))
        return ConfinedInvocationV1(
            wrapped_executable=command.executable_identity.resolved_path,
            wrapped_argv=(command.executable_identity.resolved_path, *command.argv),
            profile=None,
            environment=dict(environment),
            enforcement=SandboxEnforcementFactsV1(
                backend="none",
                enforcement="unconfined",
                mode=policy.mode,
                network=policy.network,
                policy_digest=policy.policy_digest,
            ),
        )


class FakeRunner:
    def __init__(self, action, *, draft=None) -> None:  # noqa: ANN001
        self._action = action
        self._draft = draft or _process_draft()
        self.calls: list[dict] = []

    def __call__(self, **kwargs):  # noqa: ANN003, ANN202
        self.calls.append(kwargs)
        self._action(kwargs["environment"])
        return self._draft


def _write_valid_result(environment: dict[str, str]) -> None:
    raw = json.dumps(
        {
            "kind": "observation",
            "payload": {"summary": "done"},
            "protocol": "first-agent-skill-result-v1",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    (Path(environment["HOME"]) / "result.json").write_bytes(raw)


def test_structured_execute_uses_one_runner_and_returns_owner_readback(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)
    plan = _plan()
    confiner = FakeConfiner()
    runner = FakeRunner(_write_valid_result)
    executor = NativeSandboxExecutor(
        confiner=confiner, captured_path="/usr/bin:/bin", runner=runner
    )

    draft = executor.execute(prepared, policy, io_plan=plan)

    assert isinstance(draft, StructuredSandboxProcessDraftV1)
    assert draft.readback_outcome is StructuredReadbackOutcome.VALID
    assert draft.structured_invocation_digest == structured_invocation_digest(
        prepared, policy, plan
    )
    assert draft.artifact_bytes is None
    assert b"done" in draft.result_bytes
    assert len(runner.calls) == 1
    assert runner.calls[0]["environment"]["PATH"] == ""
    assert runner.calls[0]["environment"]["HOME"] == runner.calls[0]["environment"]["TMPDIR"]
    assert confiner.environments == [runner.calls[0]["environment"]]


def test_structured_spawn_failure_is_not_read_and_never_reads_outputs(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)
    plan = _plan()
    runner = FakeRunner(
        lambda _environment: None,
        draft=_process_draft(ProcessDraftOutcome.SPAWN_FAILED),
    )
    executor = NativeSandboxExecutor(
        confiner=FakeConfiner(), captured_path="/usr/bin:/bin", runner=runner
    )

    draft = executor.execute(prepared, policy, io_plan=plan)

    assert isinstance(draft, StructuredSandboxProcessDraftV1)
    assert draft.process.outcome is SandboxDraftOutcome.SPAWN_FAILED
    assert draft.readback_outcome is StructuredReadbackOutcome.NOT_READ
    assert draft.result_bytes == b""
    assert draft.artifact_bytes is None


def test_structured_pre_spawn_confine_failure_is_known_not_executed(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)

    class UnavailableConfiner:
        def confine(self, command, active_policy, environment):  # noqa: ANN001, ANN202
            del command, active_policy, environment
            return KnownNotExecuted(code="sandbox_exec_missing", message="missing")

    runner = FakeRunner(lambda _environment: pytest.fail("runner must not execute"))
    executor = NativeSandboxExecutor(
        confiner=UnavailableConfiner(), captured_path="/usr/bin:/bin", runner=runner
    )

    result = executor.execute(prepared, policy, io_plan=_plan())

    assert isinstance(result, KnownNotExecuted)
    assert result.code == "sandbox_exec_missing"
    assert runner.calls == []


def test_structured_confine_exception_is_known_not_executed_before_runner(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)

    class RaisingConfiner:
        def confine(self, command, active_policy, environment):  # noqa: ANN001, ANN202
            del command, active_policy, environment
            raise OSError("sandbox backend disappeared")

    runner = FakeRunner(lambda _environment: pytest.fail("runner must not execute"))
    executor = NativeSandboxExecutor(
        confiner=RaisingConfiner(), captured_path="/usr/bin:/bin", runner=runner
    )

    result = executor.execute(prepared, policy, io_plan=_plan())

    assert isinstance(result, KnownNotExecuted)
    assert result.code == "structured_confine_failed"
    assert runner.calls == []


def test_structured_session_setup_failure_is_known_not_executed(
    tmp_path, monkeypatch
):
    prepared, policy = _prepared_and_policy(tmp_path)
    runner = FakeRunner(lambda _environment: pytest.fail("runner must not execute"))
    executor = NativeSandboxExecutor(
        confiner=FakeConfiner(), captured_path="/usr/bin:/bin", runner=runner
    )

    def unavailable_session(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("temporary session is unavailable")

    monkeypatch.setattr("agent.sandbox.executor.create_structured_session", unavailable_session)

    result = executor.execute(prepared, policy, io_plan=_plan())

    assert isinstance(result, KnownNotExecuted)
    assert result.code == "structured_session_setup_failed"
    assert runner.calls == []


def test_structured_cleanup_uncertainty_after_runner_enters_recovery_path(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)

    def add_unexpected_output(environment: dict[str, str]) -> None:
        os.chmod(environment["HOME"], 0o700)
        (Path(environment["HOME"]) / "surprise.bin").write_bytes(b"x")

    executor = NativeSandboxExecutor(
        confiner=FakeConfiner(),
        captured_path="/usr/bin:/bin",
        runner=FakeRunner(add_unexpected_output),
    )

    with pytest.raises(StructuredSessionCleanupError):
        executor.execute(prepared, policy, io_plan=_plan())

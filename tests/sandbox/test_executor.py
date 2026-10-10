"""017 NativeSandboxExecutor：prepared process → confined invocation → 既有 runner。

executor 复用共享 preparation seam 与 ``run_local_process``（timeout/输出
cap/进程组清理是既有 process owner 的职责）；自身只负责 confine 接线、
per-invocation temp 环境与 enforcement facts 校验。
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import replace
from types import SimpleNamespace

from agent.process.contracts import ProcessDraftOutcome
from agent.process.preparation import prepare_process
from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox.contracts import (
    ConfinedInvocationV1,
    SandboxEnforcementFactsV1,
    SandboxExecutionDraftV1,
    SandboxMode,
    SandboxNetworkMode,
)
from agent.sandbox.executor import NativeSandboxExecutor
from agent.sandbox.policy import (
    NETWORK_ONLY_SEATBELT_PROFILE,
    build_sandbox_policy,
)


def _draft(**overrides):
    values = {
        "outcome": ProcessDraftOutcome.EXITED,
        "pid": 1,
        "process_group_id": 1,
        "exit_code": 0,
        "signal": None,
        "started_at_monotonic": 0.0,
        "ended_at_monotonic": 0.1,
        "duration_seconds": 0.1,
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "stdout_digest": "a" * 64,
        "stderr_digest": "b" * 64,
        "stdout_projection": "",
        "stderr_projection": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "group_reaped": True,
        "term_sent": False,
        "kill_sent": False,
        "error_code": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeConfiner:
    def __init__(self, invocation=None, outcome: object = None) -> None:
        self.invocation = invocation
        self.outcome = outcome
        self.calls: list[tuple] = []

    def confine(self, command, policy, environment):  # noqa: ANN001, ANN202
        self.calls.append((command, policy, dict(environment)))
        if self.outcome is not None:
            return self.outcome
        return self.invocation


class FakeRunner:
    def __init__(self, draft=None) -> None:
        self.draft = draft or _draft()
        self.calls: list[dict] = []

    def __call__(self, **kwargs):  # noqa: ANN003, ANN202
        self.calls.append(kwargs)
        return self.draft


def _seatbelt_invocation(policy, command, env, *, policy_digest=None):
    profile = "(version 1)\n(allow default)\n(deny network*)\n"
    return ConfinedInvocationV1(
        wrapped_executable="/usr/bin/sandbox-exec",
        wrapped_argv=(
            "/usr/bin/sandbox-exec", "-p", profile,
            command.executable_identity.resolved_path, *command.argv,
        ),
        profile=profile,
        environment=dict(env),
        enforcement=SandboxEnforcementFactsV1(
            backend="seatbelt",
            enforcement="confined",
            mode=policy.mode,
            network=policy.network,
            policy_digest=policy_digest or policy.policy_digest,
            profile_digest=hashlib.sha256(profile.encode()).hexdigest(),
        ),
    )


def _prepared_and_policy(
    tmp_path, mode=SandboxMode.WORKSPACE_WRITE,
    network=SandboxNetworkMode.OFF, cwd=".", captured_path="/usr/bin:/bin",
):
    for name in ("work", "tmp", "state", "home"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    if cwd != ".":
        (tmp_path / "work" / cwd).mkdir(parents=True, exist_ok=True)
    prepared = prepare_process(
        {"executable": "/usr/bin/true", "cwd": cwd},
        workspace=tmp_path / "work",
        captured_path=captured_path,
    )
    policy = build_sandbox_policy(
        mode=mode,
        network=network,
        workspace=tmp_path / "work",
        temp_root=tmp_path / "tmp",
        state_root=tmp_path / "state",
        home=tmp_path / "home",
        private_roots=(),
    )
    return prepared, policy


def test_execute_uses_the_path_bound_into_the_approved_command(tmp_path):
    raw_path = os.pathsep.join(("relative", "/usr/bin", "/bin", "/usr/bin"))
    prepared, policy = _prepared_and_policy(tmp_path, captured_path=raw_path)
    confiner = FakeConfiner()
    runner = FakeRunner()

    def _confine(command, pol, env):
        invocation = _seatbelt_invocation(pol, command, env)
        confiner.calls.append((command, pol, dict(env)))
        return invocation

    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )

    draft = executor.execute(prepared, policy)

    assert isinstance(draft, SandboxExecutionDraftV1)
    delivered_path = runner.calls[0]["environment"]["PATH"]
    assert delivered_path == prepared.child_path
    assert hashlib.sha256(delivered_path.encode()).hexdigest() == (
        prepared.command.environment_policy.path_digest
    )


def test_confined_execute_runs_wrapped_invocation_once_and_cleans_temp(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)
    confiner = FakeConfiner()
    runner = FakeRunner()

    def _confine(command, pol, env):
        invocation = _seatbelt_invocation(pol, command, env)
        confiner.calls.append((command, pol, dict(env)))
        confiner.invocation = invocation
        return invocation

    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    draft = executor.execute(prepared, policy)
    assert isinstance(draft, SandboxExecutionDraftV1)
    assert draft.outcome.value == "exited"
    assert draft.enforcement.backend == "seatbelt"
    assert draft.original_command_fingerprint == prepared.command.command_fingerprint
    # runner 恰一次，拿到 wrapped argv 与封闭 env
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["resolved_executable"] == "/usr/bin/sandbox-exec"
    # process runner 会自行放入 argv[0]；executor 只能传 argv[1:]，否则真实
    # spawn 会变成 ``sandbox-exec sandbox-exec -p ...``。
    assert call["argv"][0] == "-p"
    assert call["argv"][1] == confiner.invocation.profile
    assert set(call["environment"]) == {
        "HOME", "TMPDIR", "PATH", "LANG", "LC_CTYPE", "TZ",
    }
    home_seen = call["environment"]["HOME"]
    # confine 收到的是同一封闭 env
    assert confiner.calls[0][2] == call["environment"]
    # temp root 用后即删
    assert not __import__("pathlib").Path(home_seen).exists()


def test_execute_revalidates_before_confine(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path, cwd="sub")
    # 制造 cwd 漂移：prepare 后同路径替换（rm+mkdir，新 inode）
    cwd_path = __import__("pathlib").Path(prepared.cwd_path)
    shutil.rmtree(cwd_path)
    cwd_path.mkdir()
    confiner = FakeConfiner()
    runner = FakeRunner()
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "cwd_identity_changed"
    assert confiner.calls == []
    assert runner.calls == []


def test_environment_mismatch_reaches_no_temp_confiner_or_runner(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)
    prepared = replace(
        prepared,
        command=replace(prepared.command, environment_policy=None),
    )
    confiner = FakeConfiner()
    runner = FakeRunner()
    executor = NativeSandboxExecutor(confiner=confiner, runner=runner)

    outcome = executor.execute(prepared, policy)

    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "environment_policy_changed"
    assert list(__import__("pathlib").Path(policy.temp_root).iterdir()) == []
    assert confiner.calls == []
    assert runner.calls == []


def test_backend_unavailable_returns_known_not_executed(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)
    unavailable = KnownNotExecuted(
        code="sandbox_exec_missing", message="backend unavailable",
    )
    confiner = FakeConfiner(outcome=unavailable)
    runner = FakeRunner()
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "sandbox_exec_missing"
    assert runner.calls == []


def test_enforcement_facts_tampering_is_rejected(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)
    confiner = FakeConfiner()
    runner = FakeRunner()

    def _confine(command, pol, env):
        bad = _seatbelt_invocation(pol, command, env, policy_digest="f" * 64)
        confiner.calls.append((command, pol, dict(env)))
        return bad

    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_bypass_invocation_runs_raw_command_with_unconfined_facts(tmp_path):
    # 保留行为：danger+full 才是 exact-command unconfined bypass。
    prepared, policy = _prepared_and_policy(
        tmp_path, mode=SandboxMode.DANGER_FULL_ACCESS,
        network=SandboxNetworkMode.FULL,
    )
    runner = FakeRunner()

    def _confine(command, pol, env):
        return ConfinedInvocationV1(
            wrapped_executable=command.executable_identity.resolved_path,
            wrapped_argv=(
                command.executable_identity.resolved_path, *command.argv,
            ),
            profile=None,
            environment=dict(env),
            enforcement=SandboxEnforcementFactsV1(
                backend="none",
                enforcement="unconfined",
                mode=pol.mode,
                network=pol.network,
                policy_digest=pol.policy_digest,
            ),
        )

    confiner = FakeConfiner()
    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    draft = executor.execute(prepared, policy)
    assert isinstance(draft, SandboxExecutionDraftV1)
    assert draft.enforcement.backend == "none"
    assert draft.enforcement.enforcement == "unconfined"
    assert runner.calls[0]["resolved_executable"] == "/usr/bin/true"


def test_valid_danger_network_off_seatbelt_invocation_runs(tmp_path):
    # 正对照：danger/off 的 network-only profile 必须真实到达 runner。
    prepared, policy = _prepared_and_policy(
        tmp_path, mode=SandboxMode.DANGER_FULL_ACCESS,
    )
    runner = FakeRunner()

    def _confine(command, pol, env):
        invocation = _seatbelt_invocation(pol, command, env)
        invocation = ConfinedInvocationV1(
            wrapped_executable=invocation.wrapped_executable,
            wrapped_argv=(
                "/usr/bin/sandbox-exec", "-p", NETWORK_ONLY_SEATBELT_PROFILE,
                command.executable_identity.resolved_path, *command.argv,
            ),
            profile=NETWORK_ONLY_SEATBELT_PROFILE,
            environment=dict(env),
            enforcement=SandboxEnforcementFactsV1(
                backend="seatbelt",
                enforcement="confined",
                mode=pol.mode,
                network=pol.network,
                policy_digest=pol.policy_digest,
                profile_digest=hashlib.sha256(
                    NETWORK_ONLY_SEATBELT_PROFILE.encode()
                ).hexdigest(),
            ),
        )
        return invocation

    confiner = FakeConfiner()
    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    draft = executor.execute(prepared, policy)
    assert isinstance(draft, SandboxExecutionDraftV1)
    assert draft.enforcement.backend == "seatbelt"
    assert draft.enforcement.mode is SandboxMode.DANGER_FULL_ACCESS
    assert runner.calls[0]["argv"][1] == NETWORK_ONLY_SEATBELT_PROFILE


def test_forged_unconfined_facts_for_confined_policy_reach_no_runner(tmp_path):
    # workspace-write + off 伪造 none/unconfined facts：runner 零调用。
    prepared, policy = _prepared_and_policy(tmp_path)
    runner = FakeRunner()
    confiner = _bypass_confiner()
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_forged_unconfined_facts_for_danger_network_off_reach_no_runner(tmp_path):
    # danger+off 伪造 none/unconfined：runner 零调用（必须 seatbelt/confined）。
    prepared, policy = _prepared_and_policy(
        tmp_path, mode=SandboxMode.DANGER_FULL_ACCESS,
    )
    runner = FakeRunner()
    executor = NativeSandboxExecutor(
        confiner=_bypass_confiner(), runner=runner,
    )
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_forged_seatbelt_facts_for_danger_full_are_a_contradiction(tmp_path):
    # danger+full 只能 none/unconfined；seatbelt/confined 是矛盾组合。
    prepared, policy = _prepared_and_policy(
        tmp_path, mode=SandboxMode.DANGER_FULL_ACCESS,
        network=SandboxNetworkMode.FULL,
    )
    runner = FakeRunner()

    def _confine(command, pol, env):
        return _seatbelt_invocation(pol, command, env)

    confiner = FakeConfiner()
    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_profile_digest_not_matching_profile_bytes_reaches_no_runner(tmp_path):
    # facts.profile_digest 必须等于 profile 字节的 SHA-256。
    prepared, policy = _prepared_and_policy(tmp_path)
    runner = FakeRunner()

    def _confine(command, pol, env):
        invocation = _seatbelt_invocation(pol, command, env)
        return ConfinedInvocationV1(
            wrapped_executable=invocation.wrapped_executable,
            wrapped_argv=invocation.wrapped_argv,
            profile=invocation.profile,
            environment=dict(env),
            enforcement=SandboxEnforcementFactsV1(
                backend="seatbelt",
                enforcement="confined",
                mode=pol.mode,
                network=pol.network,
                policy_digest=pol.policy_digest,
                profile_digest="f" * 64,
            ),
        )

    confiner = FakeConfiner()
    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_profile_bytes_not_matching_wrapped_argv_reach_no_runner(tmp_path):
    """receipt 绑定的 profile 必须就是 runner 将执行的 ``-p`` 参数。"""

    prepared, policy = _prepared_and_policy(tmp_path)
    runner = FakeRunner()

    def _confine(command, pol, env):
        invocation = _seatbelt_invocation(pol, command, env)
        return ConfinedInvocationV1(
            wrapped_executable=invocation.wrapped_executable,
            wrapped_argv=(
                invocation.wrapped_executable,
                "-p",
                "(version 1)\n(allow default)\n",
                command.executable_identity.resolved_path,
                *command.argv,
            ),
            profile=invocation.profile,
            environment=dict(env),
            enforcement=invocation.enforcement,
        )

    confiner = FakeConfiner()
    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_confiner_cannot_mutate_closed_environment_before_runner(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)
    runner = FakeRunner()

    def _confine(command, pol, env):
        invocation = _seatbelt_invocation(pol, command, env)
        return ConfinedInvocationV1(
            wrapped_executable=invocation.wrapped_executable,
            wrapped_argv=invocation.wrapped_argv,
            profile=invocation.profile,
            environment={**env, "INJECTED": "ambient"},
            enforcement=invocation.enforcement,
        )

    confiner = FakeConfiner()
    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )
    outcome = executor.execute(prepared, policy)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_confiner_cannot_hide_an_in_place_environment_mutation(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)
    runner = FakeRunner()

    def _confine(command, pol, env):
        env["INJECTED"] = "ambient"
        return _seatbelt_invocation(pol, command, env)

    confiner = FakeConfiner()
    confiner.confine = _confine  # type: ignore[method-assign]
    executor = NativeSandboxExecutor(
        confiner=confiner, runner=runner,
    )

    outcome = executor.execute(prepared, policy)

    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_structured_path_rejects_forged_unconfined_facts_before_runner(tmp_path):
    # 普通与 structured path 复用同一校验：伪造 none/unconfined 同样零 runner。
    from agent.sandbox.contracts import (
        StructuredResultKind,
        StructuredSandboxInputV1,
        StructuredSandboxIoPlanV1,
    )

    prepared, policy = _prepared_and_policy(tmp_path)
    request = b'{"task":"inspect"}'
    source = b"pdf"
    plan = StructuredSandboxIoPlanV1(
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
    runner = FakeRunner()
    executor = NativeSandboxExecutor(
        confiner=_bypass_confiner(), runner=runner,
    )
    outcome = executor.execute(prepared, policy, io_plan=plan)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_timeout_and_spawn_failure_outcomes_map(tmp_path):
    prepared, policy = _prepared_and_policy(tmp_path)
    timed_out = FakeRunner(
        draft=_draft(
            outcome=ProcessDraftOutcome.TIMED_OUT_REAPED, exit_code=None, signal="SIGKILL",
            kill_sent=True, group_reaped=True,
        ),
    )
    executor = NativeSandboxExecutor(
        confiner=_seatbelt_confiner(),
        runner=timed_out,
    )
    draft = executor.execute(prepared, policy)
    assert draft.outcome.value == "timed_out_reaped"

    spawn_failed = FakeRunner(draft=_draft(outcome=ProcessDraftOutcome.SPAWN_FAILED, pid=None))
    executor_two = NativeSandboxExecutor(
        confiner=_seatbelt_confiner(),
        runner=spawn_failed,
    )
    draft_two = executor_two.execute(prepared, policy)
    assert draft_two.outcome.value == "spawn_failed"


def _seatbelt_confiner():
    def _confine(command, pol, env):
        return _seatbelt_invocation(pol, command, env)

    confiner = FakeConfiner()
    confiner.confine = _confine  # type: ignore[method-assign]
    return confiner


def _bypass_confiner():
    def _confine(command, pol, env):
        return ConfinedInvocationV1(
            wrapped_executable=command.executable_identity.resolved_path,
            wrapped_argv=(
                command.executable_identity.resolved_path, *command.argv,
            ),
            profile=None,
            environment=dict(env),
            enforcement=SandboxEnforcementFactsV1(
                backend="none",
                enforcement="unconfined",
                mode=pol.mode,
                network=pol.network,
                policy_digest=pol.policy_digest,
            ),
        )

    confiner = FakeConfiner()
    confiner.confine = _confine  # type: ignore[method-assign]
    return confiner

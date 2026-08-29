"""017 native sandbox U1 reference journeys（fake backend transcript）。

全部 journey 经真实 composition 层（build_sandbox_exec_registration +
KernelToolRuntime）驱动：qualification/confine 用注入的 probe/exec 替身，
不证明真实隔离——真实层证明在 U2（frozen E3）。``U1_CLAIMS`` 与 journey
函数 1:1 绑定（由 test_017_e3_harness 强制）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.runtime.contracts import (
    SandboxAuthorityLeaseV1,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.tools import ApprovalRequired, KernelToolRuntime
from agent.sandbox.contracts import (
    SandboxEnforcementFactsV1,
    SandboxMode,
    SandboxNetworkMode,
)
from agent.sandbox.policy import build_sandbox_policy, compile_seatbelt_profile
from agent.sandbox.qualification import ProbeResult
from agent.sandbox.seatbelt import SeatbeltConfiner
from agent.sandbox.tools import build_sandbox_exec_registration

U1_CLAIMS = (
    "policy_modes_closed_and_default_workspace_write",
    "carveouts_git_readable_unreadable_denied",
    "confine_pure_wrapping_observed",
    "canonical_workspace_drift_fails_closed",
    "network_separate_policy_bound_to_approval",
    "closed_env_allowlist_no_credential",
    "backend_unavailable_confined_zero_execution_bypass_intact",
    "one_shot_authority_and_receipt_binding",
    "confined_execution_never_degrades_to_raw",
    "mutation_oracles_fail_closed",
)
NOW = "2026-08-27T08:00:00+00:00"


class FakeProbeRunner:
    """qualification 探测替身：按脚本返回 probe 结果，绝不 spawn。"""

    def __init__(self, result: ProbeResult | None = None) -> None:
        self.result = result or ProbeResult(0, b"", b"", False)
        self.calls: list[tuple] = []

    def run(self, argv, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ANN202
        self.calls.append(tuple(argv))
        return self.result


class FakeExecRunner:
    """executor 运行替身：记录 wrapped argv/env，返回 closed draft。"""

    def __init__(self, outcome: str = "exited") -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    def __call__(self, **kwargs):  # noqa: ANN003, ANN202
        self.calls.append(kwargs)
        return SimpleNamespace(
            outcome=_outcome(self.outcome),
            exit_code=0 if self.outcome == "exited" else None,
            signal=None,
            duration_seconds=0.1,
            stdout_bytes=2,
            stderr_bytes=0,
            stdout_digest="a" * 64,
            stderr_digest="b" * 64,
            stdout_projection="ok",
            stderr_projection="",
            stdout_truncated=False,
            stderr_truncated=False,
        )


def _outcome(value: str):  # noqa: ANN202
    from agent.process.contracts import ProcessDraftOutcome

    return ProcessDraftOutcome(value)


class SandboxJourney:
    """一次 U1 journey 的全部独立计数器与替身。"""

    def __init__(self, tmp_path: Path, *, probe_result=None, platform="Darwin") -> None:
        self.tmp = tmp_path
        self.workspace = tmp_path / "work"
        self.state_root = tmp_path / "state"
        self.temp_root = tmp_path / "sbx-tmp"
        self.home = tmp_path / "sbx-home"
        for path in (self.workspace, self.state_root, self.temp_root, self.home):
            path.mkdir(parents=True, exist_ok=True)
        self.probe = FakeProbeRunner(probe_result)
        self.confiner = SeatbeltConfiner(
            runner=self.probe, platform_system=platform, platform_release="24.5.0",
        )
        self.exec_runner = FakeExecRunner()
        self.registration = build_sandbox_exec_registration(
            workspace=self.workspace,
            temp_root=self.temp_root,
            state_root=self.state_root,
            home=self.home,
            captured_path="/usr/bin:/bin",
            confiner=self.confiner,
            runner=self.exec_runner,
        )
        self.runtime = KernelToolRuntime(
            (self.registration,), clock=lambda: NOW,
        )
        self._call_seq = 0

    def call(self, arguments: dict, call_id: str | None = None) -> ToolCall:
        # call_id 自增：同一 runtime 的幂等闸按 idempotency key 拒绝重复 invoke
        if call_id is None:
            self._call_seq += 1
            call_id = f"call-{self._call_seq}"
        return ToolCall(call_id, "sandbox_exec", arguments)

    def context(self, leases=(), **overrides) -> ToolPrepareContext:  # noqa: ANN001
        values = {
            "conversation_id": "conversation-1",
            "run_id": "run-1",
            "state_revision": 7,
            "goal_id": "goal-1",
            "goal_revision": 1,
            "workspace_identity_digest": "workspace-digest-1",
        }
        values.update(overrides)
        if leases:
            values["sandbox_leases"] = tuple(leases)
        return ToolPrepareContext(**values)

    def approve_once(self, arguments: dict) -> ToolPrepareContext:
        """prepare→ApprovalRequired→从 candidate 铸 one-shot lease→带 lease 的
        context（同一 exact command/policy 才匹配）。"""

        pending = self.runtime.prepare(self.call(arguments), self.context())
        assert isinstance(pending, ApprovalRequired), type(pending)
        candidate = pending.request.sandbox_authority_candidate
        lease = SandboxAuthorityLeaseV1.create(
            lease_id=f"sandbox-lease:{candidate.policy_digest[:12]}",
            candidate_digest=candidate.candidate_digest,
            goal_id=candidate.goal_id,
            goal_revision=candidate.goal_revision,
            workspace_identity_digest=candidate.workspace_identity_digest,
            original_command_fingerprint=candidate.original_command_fingerprint,
            policy_digest=candidate.policy_digest,
            mode=candidate.mode,
            network=candidate.network,
            readable_command=candidate.readable_command,
            trust_notice_id=candidate.trust_notice_id,
            trust_notice_digest=candidate.trust_notice_digest,
            approved_request_identity=f"{candidate.goal_id}:run-1:{candidate.policy_digest[:12]}",
            issued_at=NOW,
            expires_at="2026-08-27T10:00:00+00:00",
        )
        return self.context(leases=(lease,))

    def run_confined(self, arguments: dict):  # noqa: ANN202
        context = self.approve_once(arguments)
        intent = self.runtime.prepare(self.call(arguments), context)
        assert not isinstance(intent, ApprovalRequired)
        return self.runtime.invoke(intent)

    def policy(self, mode=SandboxMode.WORKSPACE_WRITE, network=SandboxNetworkMode.OFF):  # noqa: ANN202
        return build_sandbox_policy(
            mode=mode,
            network=network,
            workspace=self.workspace,
            temp_root=self.temp_root,
            state_root=self.state_root,
            home=self.home,
            private_roots=(),
        )


def _plain_arguments() -> dict:
    return {"executable": "/usr/bin/true", "cwd": "."}


# --------------------------------------------------------------------------- #
# U1 journeys（与 U1_CLAIMS 一一对应）
# --------------------------------------------------------------------------- #


def test_u1_policy_modes_closed_and_default_workspace_write(tmp_path):
    journey = SandboxJourney(tmp_path)
    pending = journey.runtime.prepare(
        journey.call(_plain_arguments()), journey.context(),
    )
    assert isinstance(pending, ApprovalRequired)
    candidate = pending.request.sandbox_authority_candidate
    assert candidate.mode == "workspace-write"
    assert candidate.network == "off"
    read_only = journey.runtime.prepare(
        journey.call({**_plain_arguments(), "mode": "read-only"}),
        journey.context(),
    )
    assert isinstance(read_only, ApprovalRequired)
    assert read_only.request.sandbox_authority_candidate.mode == "read-only"
    unknown = journey.runtime.prepare(
        journey.call({**_plain_arguments(), "mode": "container"}),
        journey.context(),
    )
    assert unknown.is_error is True
    writable = journey.policy().writable_roots
    assert set(writable) == {str(journey.workspace), str(journey.temp_root)}
    assert journey.policy(mode=SandboxMode.READ_ONLY).writable_roots == ()


def test_u1_carveouts_git_readable_unreadable_denied(tmp_path):
    journey = SandboxJourney(tmp_path)
    (journey.workspace / ".git").mkdir(exist_ok=True)
    policy = journey.policy()
    profile = compile_seatbelt_profile(policy)
    git_root = policy.git_metadata_roots[0]
    assert f'(deny file-write* (subpath "{git_root}"))' in profile
    assert f'(deny file-read* (subpath "{git_root}"))' not in profile
    assert f'(deny file-read* (subpath "{journey.state_root}"))' in profile
    assert f'(deny file-write* (subpath "{journey.state_root}"))' in profile


def test_u1_confine_pure_wrapping_observed(tmp_path):
    journey = SandboxJourney(tmp_path)
    result = journey.run_confined(_plain_arguments())
    assert result.is_error is False
    assert len(journey.exec_runner.calls) == 1
    call = journey.exec_runner.calls[0]
    argv = call["argv"]
    assert call["resolved_executable"] == "/usr/bin/sandbox-exec"
    assert argv[0] == "-p"
    profile = argv[1]
    assert profile.startswith("(version 1)")
    assert argv[2] == "/usr/bin/true"
    assert len(journey.probe.calls) == 1  # qualification 恰一次，不随执行增长


def test_u1_canonical_workspace_drift_fails_closed(tmp_path):
    link = tmp_path / "work-link"
    link.symlink_to(tmp_path / "work")
    with pytest.raises(ValueError, match="canonical"):
        build_sandbox_policy(
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            workspace=link,
            temp_root=tmp_path / "sbx-tmp",
            state_root=tmp_path / "state",
            home=tmp_path / "sbx-home",
            private_roots=(),
        )


def test_u1_network_separate_policy_bound_to_approval(tmp_path):
    journey = SandboxJourney(tmp_path)
    pending = journey.runtime.prepare(
        journey.call({**_plain_arguments(), "network": "full"}),
        journey.context(),
    )
    assert isinstance(pending, ApprovalRequired)
    assert pending.request.sandbox_authority_candidate.network == "full"
    result = journey.run_confined({**_plain_arguments(), "network": "full"})
    assert result.is_error is False
    argv = journey.exec_runner.calls[0]["argv"]
    assert "(deny network*)" not in argv[1]
    off_result = journey.run_confined(_plain_arguments())
    assert off_result.is_error is False
    assert "(deny network*)" in journey.exec_runner.calls[1]["argv"][1]


def test_u1_closed_env_allowlist_no_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PROVIDER_SECRET", "leak-me")
    journey = SandboxJourney(tmp_path)
    result = journey.run_confined(_plain_arguments())
    assert result.is_error is False
    env = journey.exec_runner.calls[0]["environment"]
    assert set(env) == {"HOME", "TMPDIR", "PATH", "LANG", "LC_CTYPE", "TZ"}
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"].startswith(str(journey.temp_root))
    assert "FAKE_PROVIDER_SECRET" not in env


def test_u1_backend_unavailable_confined_zero_execution_bypass_intact(tmp_path):
    journey = SandboxJourney(
        tmp_path, probe_result=ProbeResult(1, b"", b"refused", False),
    )
    context = journey.approve_once(_plain_arguments())
    intent = journey.runtime.prepare(journey.call(_plain_arguments()), context)
    assert not isinstance(intent, ApprovalRequired)
    outcome = journey.runtime.invoke(intent)
    assert outcome.is_error is True
    assert outcome.executed is False
    assert journey.exec_runner.calls == []
    bypass = SandboxJourney(
        tmp_path, probe_result=ProbeResult(1, b"", b"refused", False),
    )
    bypass_result = bypass.run_confined(
        {**_plain_arguments(), "mode": "danger-full-access"},
    )
    assert bypass_result.is_error is False
    assert len(bypass.exec_runner.calls) == 1
    assert bypass.exec_runner.calls[0]["resolved_executable"] == "/usr/bin/true"
    assert bypass.exec_runner.calls[0]["argv"] == ()


def test_u1_one_shot_authority_and_receipt_binding(tmp_path):
    journey = SandboxJourney(tmp_path)
    context = journey.approve_once(_plain_arguments())
    intent = journey.runtime.prepare(journey.call(_plain_arguments()), context)
    assert not isinstance(intent, ApprovalRequired)
    result = journey.runtime.invoke(intent)
    assert result.is_error is False
    receipt = result.metadata["sandbox_receipt"]
    assert receipt["policy_digest"] == journey.policy().policy_digest
    # one-shot：消耗发生在 durable EXECUTING 状态层（mark_executing 消费
    # lease）；journey 以已消耗 lease（uses_consumed==max_uses）证明其不再
    # 授权新 intent。
    from dataclasses import replace as _replace

    lease = context.sandbox_leases[0]
    consumed_context = journey.context(
        leases=(_replace(lease, uses_consumed=lease.max_uses),),
    )
    again = journey.runtime.prepare(
        journey.call(_plain_arguments()), consumed_context,
    )
    assert isinstance(again, ApprovalRequired)
    # policy/command 漂移在 callable 侧 fail closed
    drifted = journey.runtime.prepare(
        journey.call({**_plain_arguments(), "argv": ["--different"]}), context,
    )
    assert isinstance(drifted, ApprovalRequired)


def test_u1_confined_execution_never_degrades_to_raw(tmp_path):
    journey = SandboxJourney(tmp_path)
    result = journey.run_confined(_plain_arguments())
    assert result.is_error is False
    for call in journey.exec_runner.calls:
        if "mode" not in call:
            argv = call["argv"]
            assert call["resolved_executable"] == "/usr/bin/sandbox-exec"
            assert argv[0] == "-p", argv[:1]


def test_u1_mutation_oracles_fail_closed(tmp_path):
    # facts 一致性：bypass 伪装 confined（backend=none 但 enforcement=confined）
    with pytest.raises(ValueError):
        SandboxEnforcementFactsV1(
            backend="none",
            enforcement="confined",
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            policy_digest="a" * 64,
        )
    # profile digest 伪造：confiner facts 必须绑定真实编译产物
    journey = SandboxJourney(tmp_path)
    result = journey.run_confined(_plain_arguments())
    receipt = result.metadata["sandbox_receipt"]
    profile = journey.exec_runner.calls[0]["argv"][1]
    assert (
        receipt["profile_digest"]
        == hashlib.sha256(profile.encode()).hexdigest()
    )
    # 静默降级：confined argv 必须带 sandbox-exec 前缀（never raw）
    assert journey.exec_runner.calls[0]["resolved_executable"] == "/usr/bin/sandbox-exec"
    assert journey.exec_runner.calls[0]["argv"][0] == "-p"
    # executor temp 用后即删（cleanup 不留复用面）
    home_seen = Path(journey.exec_runner.calls[0]["environment"]["HOME"])
    del journey, result
    assert not home_seen.exists()

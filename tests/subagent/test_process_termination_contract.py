"""Standards hard blocker Red tests：ChildProcessRunner 的 process_terminated 合同。

deadline_contract 对外声称 receipt_type="process_terminated"，但原实现只 wait
leader：无 verified PGID、无 group-liveness oracle、getpgid OSError 还退化
os.kill(pid) 单进程信号——descendant 可能存活却照常收尾。本文件钉住终止合同：
TERMINATED 必须由 verified group termination 支撑；无法确认终止时 fail closed
为 UNCONFIRMED（不得把 unknown 当 terminated）。
"""

from __future__ import annotations

import os

import agent.subagent.process_runner as pr_mod
from agent.subagent.contracts import ChildProfile, ChildProviderSpec
from agent.subagent.process_runner import ChildProcessRunner

SCOPE = "scope-termination-contract"


def _profile(**overrides) -> ChildProfile:
    base = {
        "runner_version": "subagent-v1",
        "provider_profile_id": "default",
        "provider_destination": "local",
        "workspace_scope_digest": SCOPE,
        "max_input_tokens": 4_000,
        "max_output_tokens": 1_000,
        "limits_digest": "limits-1",
        "hard_deadline_seconds": 30.0,
    }
    base.update(overrides)
    return ChildProfile(**base)


def _fake_spec(*, text="child answer", sleep=0.0) -> ChildProviderSpec:
    return ChildProviderSpec(kind="fake", fake_text=text, sleep_seconds=sleep)


def test_identity_failure_fails_closed_as_termination_unconfirmed(monkeypatch) -> None:
    """group identity 无法验证时不得静默走普通 kill 流程。

    原实现 getpgid OSError → os.kill(pid) 单进程回退，随后照常返回
    reason="unconfirmed_outcome"，与正常 deadline kill 不可区分。合同要求：
    identity 失败本身就是一个终止无法确认的状态。
    """

    def broken_getpgid(pid: int) -> int:
        raise OSError("simulated EPERM on getpgid")

    monkeypatch.setattr(os, "getpgid", broken_getpgid)

    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="x", sleep=5.0),
        profile=_profile(),
        hard_deadline_seconds=0.5,
    )
    result = runner.run(
        objective="hang",
        handoff="",
        parent_idempotency_key="parent:run-1:id-fail",
    )

    assert result.receipt_state == "unconfirmed"
    assert result.reason == "termination_unconfirmed"


def test_terminated_receipt_requires_group_liveness_probe(monkeypatch) -> None:
    """child 自行退出（TERMINATED 路径）也必须探测 group 消失。

    原实现在 leader 退出后直接解析 stdout 并返回 TERMINATED，从未探测
    group liveness——同 group descendant 存活时 "process_terminated" 是
    未经验证的声称。
    """

    real_killpg = os.killpg
    probes: list[tuple[int, int]] = []

    def spy_killpg(pgid: int, sig: int) -> None:
        if sig == 0:
            probes.append((pgid, sig))
        real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", spy_killpg)

    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="probe my group"),
        profile=_profile(),
        hard_deadline_seconds=120.0,
    )
    result = runner.run(
        objective="finish cleanly",
        handoff="",
        parent_idempotency_key="parent:run-1:probe",
    )

    assert result.receipt_state == "terminated"
    assert probes, "TERMINATED must be backed by a signal-0 group-liveness probe"


def test_cleanup_failure_with_unconfirmed_outcome_stays_unconfirmed(
    monkeypatch,
) -> None:
    """outcome 未知（deadline kill）叠加 cleanup 失败不得声称 TERMINATED。

    原实现的 cleanup_failed 分支无条件 receipt=TERMINATED——child 从未
    terminally 报告（outcome None）时这是 unknown-as-terminated。
    """

    monkeypatch.setattr(
        pr_mod,
        "_remove_run_dir",
        lambda config_path, config_dir: False,
    )

    runner = ChildProcessRunner(
        provider_spec=_fake_spec(text="x", sleep=5.0),
        profile=_profile(),
        hard_deadline_seconds=0.5,
    )
    result = runner.run(
        objective="hang",
        handoff="",
        parent_idempotency_key="parent:run-1:cleanup-fail",
    )

    assert result.reason == "cleanup_failed"
    assert result.receipt_state == "unconfirmed"

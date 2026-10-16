"""E1 driver（scripts/run_task_trust_d04.py）的离线故障路径测试。

VALIDATION §3/§4 冻结要求：先离线证明 driver 遇到业务 false、产品未终结、
预算耗尽、correction 未接纳、恢复失败会如实失败（product_status=incomplete、
非零退出），不根据最后一句文字直接判 PASS；并证明注入边界识别只依据 durable
事实（已有 Goal + ≥1 次正常文件效果 + 未终结的第一个安全治理交互点）。

全部离线：provider=fake 不是真实派发；不调用 API、不读凭据。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.materialize_coding_scenario import materialize
from scripts.run_task_trust_d04 import (
    CORRECTION,
    INITIAL_PROMPT,
    ORIGINAL_SPEC_SHA256,
    VARIANT_MARKER,
    JourneyOperator,
    _staged_evidence,
    evaluate_final,
)

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "scripts" / "run_task_trust_d04.py"


def _materialize(tmp_path: Path, name: str = "d04-a") -> Path:
    candidate = tmp_path / name
    materialize("D04", candidate)
    return candidate


def _prepare(candidate: Path, tmp_path: Path, *, staged: bool) -> subprocess.CompletedProcess:
    command = [
        sys.executable,
        str(DRIVER),
        "prepare",
        str(candidate),
        "--result",
        str(tmp_path / "prepare.json"),
    ]
    if staged:
        command.append("--staged")
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _run_journey(
    candidate: Path,
    tmp_path: Path,
    *,
    mode: str,
    ledger_lines: int = 0,
) -> tuple[subprocess.CompletedProcess, dict]:
    ledger = tmp_path / f"ledger-{mode}" / "attempts.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ledger.parent, 0o700)
    if ledger_lines:
        record = json.dumps(
            {
                "schema": "first-agent/transport-attempt/v1",
                "kind": "model",
                "destination_digest": "0" * 64,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        descriptor = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"{record}\n" * ledger_lines)
    result_path = tmp_path / f"result-{mode}.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            "journey",
            str(candidate),
            "--mode",
            mode,
            "--state-root",
            str(tmp_path / f"state-{mode}"),
            "--ledger",
            str(ledger),
            "--result",
            str(result_path),
            "--provider",
            "fake",
            "--wall-seconds",
            "300",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    record = json.loads(result_path.read_text(encoding="utf-8"))
    return completed, record


def _observation(**overrides) -> dict:
    base = {
        "goal_status": "executing",
        "goal_id": "goal-v1-test",
        "goal_revision": 1,
        "user_outcome": "bounded retry",
        "created_from_fact_ids": ["fact:task"],
        "proposed_criteria": [],
        "admitted_criteria": [],
        "active_run_status": "awaiting_approval",
        "pending": "approval",
        "executed_file_effects": 2,
        "effect_tools": {"write_file": 2},
        "correction_fact_ids": [],
        "state_revision": 9,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 注入边界识别（离线场景）：只依据 durable 事实
# ---------------------------------------------------------------------------


def test_operator_injects_only_at_first_safe_boundary() -> None:
    operator = JourneyOperator(mode="inject")
    assert operator.next_input(None) == INITIAL_PROMPT  # 首发是冻结任务文本
    assert operator.task_sent is True

    # 尚无任何正常文件效果：不是合法边界，不注入，正常治理放行。
    before_effect = JourneyOperator(mode="inject", task_sent=True)
    assert before_effect.next_input(_observation(executed_file_effects=0)) == "y"
    assert before_effect.injected is False

    # 已有 Goal + ≥1 文件效果 + approval 边界：注入冻结 correction。
    at_boundary = JourneyOperator(mode="inject", task_sent=True)
    assert at_boundary.next_input(_observation()) == CORRECTION
    assert at_boundary.injected is True
    assert at_boundary.injection_point == "approval"

    # 空闲提示（无 pending）同样接受注入。
    idle = JourneyOperator(mode="inject", task_sent=True)
    assert (
        idle.next_input(
            _observation(active_run_status=None, pending=None, goal_status="executing")
        )
        == CORRECTION
    )
    assert idle.injection_point == "idle"

    # 只注入一次：注入后的下一个边界不再重复交付。
    assert at_boundary.next_input(_observation()) != CORRECTION


def test_operator_never_injects_into_terminal_or_effect_free_states() -> None:
    terminal = JourneyOperator(mode="inject", task_sent=True)
    assert (
        terminal.next_input(
            _observation(goal_status="verified_done", active_run_status=None, pending=None)
        )
        == "/exit"
    )
    assert terminal.stop_reason == "verified_done"
    assert terminal.injected is False

    cancelled = JourneyOperator(mode="inject", task_sent=True)
    assert (
        cancelled.next_input(
            _observation(goal_status="cancelled", active_run_status=None, pending=None)
        )
        == "/exit"
    )
    assert cancelled.stop_reason == "goal_cancelled"

    no_goal = JourneyOperator(mode="inject", task_sent=True)
    assert (
        no_goal.next_input(
            _observation(goal_status=None, active_run_status=None, pending=None)
        )
        == "/exit"
    )
    assert no_goal.injected is False


def test_injection_pauses_only_after_durable_consumption() -> None:
    operator = JourneyOperator(mode="inject", task_sent=True)
    operator.injected = True
    operator.injection_point = "approval"
    operator.injected_fact_id = "fact:correction"
    operator.pre_injection = _observation(goal_revision=1, state_revision=9)

    # correction 未进入 goal.created_from_fact_ids：不暂停，继续正常治理。
    pending_obs = _observation(
        created_from_fact_ids=["fact:task"],
        correction_fact_ids=["fact:correction"],
        goal_revision=1,
        state_revision=10,
    )
    assert operator.next_input(pending_obs) == "y"
    assert operator.pause_sent is False

    # 已消费（绑入 created_from_fact_ids 且版本推进）：发出 /pause。
    consumed_obs = _observation(
        created_from_fact_ids=["fact:task", "fact:correction"],
        correction_fact_ids=["fact:correction"],
        goal_revision=2,
        state_revision=11,
    )
    assert operator.next_input(consumed_obs) == "/pause"
    assert operator.pause_sent is True

    # 暂停生效：paused + 无 active run → 如实结束该阶段等待新进程恢复。
    assert (
        operator.next_input(
            _observation(
                goal_status="paused",
                active_run_status=None,
                pending=None,
                created_from_fact_ids=["fact:task", "fact:correction"],
                correction_fact_ids=["fact:correction"],
                goal_revision=2,
                state_revision=12,
            )
        )
        == "/exit"
    )
    assert operator.stop_reason == "paused_for_resume"


def test_resume_phase_never_restates_the_task() -> None:
    operator = JourneyOperator(mode="resume")
    # 恢复阶段第一个输入只能是显式 /resume，绝不重述业务。
    assert (
        operator.next_input(
            _observation(
                goal_status="paused", active_run_status=None, pending=None
            )
        )
        == "/resume"
    )
    assert operator.resume_sent is True
    assert operator.task_sent is False

    # 恢复后通用「继续」推进（goal_ready、空闲、无 pending）；typed 终态才结束。
    assert operator.next_input(
        _observation(
            goal_status="goal_ready",
            goal_revision=3,
            state_revision=20,
            active_run_status=None,
            pending=None,
        )
    ) == "继续当前任务"
    assert (
        operator.next_input(
            _observation(
                goal_status="verified_done", active_run_status=None, pending=None
            )
        )
        == "/exit"
    )
    assert operator.stop_reason == "verified_done"


def test_resume_phase_stops_when_goal_is_not_paused() -> None:
    operator = JourneyOperator(mode="resume")
    assert operator.next_input(_observation(goal_status="executing")) == "/exit"
    assert operator.stop_reason == "resume_expected_paused_goal"


# ---------------------------------------------------------------------------
# 判定口径：文字、单项证据都不能覆盖 durable 事实
# ---------------------------------------------------------------------------


def _passing_business() -> dict:
    return {"latest_correction": True, "final_validation": True}


def test_final_verdict_ignores_optimistic_prose_without_typed_terminal() -> None:
    # 模型最后说完成、operator 标签也是 verified_done，但 durable 未到终态：
    # 必须 incomplete，绝不按最后一句文字判 PASS。
    record = evaluate_final(
        mode="normal",
        typed_terminal=False,
        business=_passing_business(),
        supplemental={"transient_new_name": True},
        stop_reason="verified_done",
        exit_codes=[0],
        physical_requests=5,
        max_requests=40,
        evidence={"correction_injected": True},
    )
    assert record["product_status"] == "incomplete"
    assert any("typed VERIFIED_DONE" in item for item in record["failures"])


def test_final_verdict_reports_business_false_honestly() -> None:
    record = evaluate_final(
        mode="normal",
        typed_terminal=True,
        business={"latest_correction": False, "final_validation": True},
        supplemental={"transient_new_name": False, "negative_invalid": True},
        stop_reason="verified_done",
        exit_codes=[0],
        physical_requests=5,
        max_requests=40,
        evidence={"correction_injected": True},
    )
    assert record["product_status"] == "incomplete"
    assert any("latest_correction" in item for item in record["failures"])
    assert any("transient_new_name" in item for item in record["failures"])
    # F3c 恒 false 的过程声明只原样报告，不计入失败。
    assert record["business_declared_false"] == {
        "resume_without_restatement": False,
        "no_effect_replay": False,
    }
    assert not any("resume_without_restatement" in item for item in record["failures"])


def test_final_verdict_reports_budget_exhaustion_honestly() -> None:
    record = evaluate_final(
        mode="normal",
        typed_terminal=True,
        business=_passing_business(),
        supplemental={"transient_new_name": True},
        stop_reason="verified_done",
        exit_codes=[0],
        physical_requests=41,
        max_requests=40,
        evidence={"correction_injected": True},
    )
    assert record["product_status"] == "incomplete"
    assert any("exceed the authorized budget" in item for item in record["failures"])


def test_staged_evidence_requires_real_resume_advance() -> None:
    phase_a = {
        "pid": 111,
        "stop_reason": "paused_for_resume",
        "pause_sent": True,
        "injected": True,
        "injection_point": "approval",
        "injected_fact_id": "fact:correction",
        "pre_injection": {
            "goal_revision": 1,
            "state_revision": 9,
            "alias_checks": {"legacy_alias": False, "cli_both_names": False},
        },
        "consumption": {
            "fact_id": "fact:correction",
            "created_from_fact_ids": ["fact:task", "fact:correction"],
            "goal_version_changed": True,
            "state_version_changed": True,
        },
        "final_observation": {
            "goal_status": "paused",
            "correction_fact_ids": ["fact:correction"],
        },
    }
    # 新进程 resume 了，但既无新增文件效果、也无版本推进：恢复未推进 → 失败。
    stalled_b = {
        "pid": 222,
        "resume_sent": True,
        "start_observation": {"goal_revision": 2, "executed_file_effects": 2},
    }
    stalled_final = {
        "goal_status": "verified_done",
        "goal_revision": 2,
        "executed_file_effects": 2,
    }
    evidence = _staged_evidence(phase_a, stalled_b, stalled_final)
    assert evidence["resumed_in_new_process"] is True
    assert evidence["resume_advanced"] is False
    record = evaluate_final(
        mode="staged",
        typed_terminal=True,
        business=_passing_business(),
        supplemental={"transient_new_name": True},
        stop_reason="verified_done",
        exit_codes=[0, 0],
        physical_requests=10,
        max_requests=40,
        evidence=evidence,
    )
    assert record["product_status"] == "incomplete"
    assert any("resume_advanced" in item for item in record["failures"])

    # 同一 PID 冒充新进程：恢复证据不成立。
    same_pid_b = {**stalled_b, "pid": 111}
    evidence_same = _staged_evidence(phase_a, same_pid_b, stalled_final)
    assert evidence_same["resumed_in_new_process"] is False


def test_staged_evidence_requires_precondition_alias_checks_pending() -> None:
    # 注入前模型已提前完成全部别名行为：样本不能证明新增纠正生效。
    phase_a = {
        "pid": 111,
        "stop_reason": "paused_for_resume",
        "pause_sent": True,
        "injected": True,
        "injection_point": "approval",
        "injected_fact_id": "fact:correction",
        "pre_injection": {
            "goal_revision": 1,
            "state_revision": 9,
            "alias_checks": {"legacy_alias": True, "cli_both_names": True},
        },
        "consumption": {
            "fact_id": "fact:correction",
            "created_from_fact_ids": ["fact:correction"],
            "goal_version_changed": True,
            "state_version_changed": True,
        },
        "final_observation": {
            "goal_status": "paused",
            "correction_fact_ids": ["fact:correction"],
        },
    }
    phase_b = {
        "pid": 222,
        "resume_sent": True,
        "start_observation": {"goal_revision": 2, "executed_file_effects": 2},
    }
    final_obs = {
        "goal_status": "verified_done",
        "goal_revision": 3,
        "executed_file_effects": 4,
    }
    evidence = _staged_evidence(phase_a, phase_b, final_obs)
    assert evidence["resume_advanced"] is True
    assert evidence["precondition_alias_checks_pending"] is False
    record = evaluate_final(
        mode="staged",
        typed_terminal=True,
        business=_passing_business(),
        supplemental={"transient_new_name": True},
        stop_reason="verified_done",
        exit_codes=[0, 0],
        physical_requests=10,
        max_requests=40,
        evidence=evidence,
    )
    assert record["product_status"] == "incomplete"
    assert any("precondition_alias_checks_pending" in item for item in record["failures"])


# ---------------------------------------------------------------------------
# prepare：staged 派生必须程序化、可核对、拒绝非冻结字节
# ---------------------------------------------------------------------------


def test_prepare_normal_keeps_original_spec_bytes(tmp_path: Path) -> None:
    candidate = _materialize(tmp_path)
    cache = candidate / "retry_app" / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "stale.pyc").write_bytes(b"stale")
    spec_before = (candidate / "SPEC.md").read_bytes()
    completed = _prepare(candidate, tmp_path, staged=False)
    assert completed.returncode == 0, completed.stderr
    assert (candidate / "SPEC.md").read_bytes() == spec_before
    assert not cache.exists()
    assert not (candidate / VARIANT_MARKER).exists()
    record = json.loads((tmp_path / "prepare.json").read_text(encoding="utf-8"))
    assert record["original_spec_sha256"] == ORIGINAL_SPEC_SHA256
    assert record["staged"] is False


def test_prepare_staged_derives_spec_without_future_correction(tmp_path: Path) -> None:
    candidate = _materialize(tmp_path)
    completed = _prepare(candidate, tmp_path, staged=True)
    assert completed.returncode == 0, completed.stderr
    record = json.loads((tmp_path / "prepare.json").read_text(encoding="utf-8"))
    staged = (candidate / "SPEC.md").read_text(encoding="utf-8")
    # 保留标题与原始有界重试段落；未来纠正段落（含 retry_count 字样）不可见。
    assert staged.startswith("# Retry feature")
    assert "max_retries" in staged
    assert "During the task" not in staged
    assert "retry_count" not in staged
    assert record["staged_spec_content"] == staged
    assert record["future_correction_hidden"] is True
    assert (candidate / VARIANT_MARKER).exists()
    # 主模型可见的初始上下文不含未来纠正；correction 只存在于 driver 冻结常量。
    assert "retry_count" in CORRECTION


def test_prepare_staged_refuses_non_frozen_spec_bytes(tmp_path: Path) -> None:
    candidate = _materialize(tmp_path)
    spec = candidate / "SPEC.md"
    spec.write_bytes(spec.read_bytes() + b"tampered\n")
    completed = _prepare(candidate, tmp_path, staged=True)
    assert completed.returncode != 0
    assert "refusing to stage" in completed.stderr
    # 拒绝后 SPEC 保持被改后的字节，不做任何静默改写。
    assert spec.read_bytes().endswith(b"tampered\n")


# ---------------------------------------------------------------------------
# 端到端离线旅程：fake provider 下产品不可能终结 → 必须如实 incomplete
# ---------------------------------------------------------------------------


def test_offline_normal_journey_reports_incomplete(tmp_path: Path) -> None:
    candidate = _materialize(tmp_path)
    assert _prepare(candidate, tmp_path, staged=False).returncode == 0
    completed, record = _run_journey(candidate, tmp_path, mode="normal")
    assert completed.returncode == 1
    assert record["product_status"] == "incomplete"
    assert record["typed_terminal"] is False
    failures = "\n".join(record["failures"])
    assert "typed VERIFIED_DONE" in failures
    # 产品没有写任何文件：业务判据如实为 false，而不是被文字掩盖。
    assert record["business_checks"]["latest_correction"] is False
    assert record["business_checks"]["final_validation"] is False
    # fake provider 不产生真实派发，物理请求为 0。
    assert record["physical_requests"] == 0


def test_offline_staged_journey_reports_missing_correction_evidence(
    tmp_path: Path,
) -> None:
    candidate = _materialize(tmp_path)
    assert _prepare(candidate, tmp_path, staged=True).returncode == 0
    completed, record = _run_journey(candidate, tmp_path, mode="staged")
    assert completed.returncode == 1
    assert record["product_status"] == "incomplete"
    failures = "\n".join(record["failures"])
    # 未观察到合法注入边界 → 明确失败，不用新任务冒充，也不悄悄跳过。
    assert "resume phase skipped" in failures
    assert "correction_injected" in failures
    assert record["evidence"]["correction_injected"] is False


def test_offline_journey_reports_budget_exhaustion(tmp_path: Path) -> None:
    candidate = _materialize(tmp_path)
    assert _prepare(candidate, tmp_path, staged=False).returncode == 0
    completed, record = _run_journey(
        candidate, tmp_path, mode="normal", ledger_lines=41
    )
    assert completed.returncode == 1
    assert record["product_status"] == "incomplete"
    assert record["physical_requests"] == 41
    assert any(
        "exceed the authorized budget" in item for item in record["failures"]
    )


def test_offline_journey_reports_grader_crash_honestly(tmp_path: Path) -> None:
    candidate = _materialize(tmp_path)
    assert _prepare(candidate, tmp_path, staged=False).returncode == 0
    # 候选被破坏到 grader 无法执行：崩溃必须如实记录，不伪装成业务 false。
    (candidate / "retry_app" / "service.py").write_text(
        "def broken(:\n", encoding="utf-8"
    )
    completed, record = _run_journey(candidate, tmp_path, mode="normal")
    assert completed.returncode == 1
    assert record["product_status"] == "incomplete"
    assert any(
        "business grader failed to execute" in item for item in record["failures"]
    )


def test_normal_evidence_always_records_correction_injected_key(tmp_path: Path) -> None:
    """normal 模式 evidence 必须携带 correction_injected 键（即使 False）。

    回归：_finalize 曾丢弃 phase 记录中的 injected 字段，导致 normal 模式
    永远缺失 REQUIRED_EVIDENCE 键——即使 correction 已真实注入并消费。
    """
    candidate = _materialize(tmp_path)
    assert _prepare(candidate, tmp_path, staged=False).returncode == 0
    completed, record = _run_journey(candidate, tmp_path, mode="normal")
    assert completed.returncode == 1
    assert record["product_status"] == "incomplete"
    assert "correction_injected" in record["evidence"]
    # fake provider 无文件效果 → 无合法注入边界 → 如实 False。
    assert record["evidence"]["correction_injected"] is False

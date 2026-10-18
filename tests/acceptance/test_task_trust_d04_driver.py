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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent.runtime.contracts import (
    GoalFrame,
    GoalStatus,
    ProposedCriterion,
    ProviderDisclosureRequest,
)
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

# 冻结七项补充检查键（WORK-PACKAGES W3：evaluator 必须锁定完整预期集合）。
FULL_SUPPLEMENTAL = {
    "transient_new_name": True,
    "legacy_alias": True,
    "default_single_attempt": True,
    "bounded_attempts": True,
    "conflict_rejected": True,
    "negative_invalid": True,
    "cli_both_names": True,
}

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
        "pending_request": {"tool": "write_file", "path": "retry_app/service.py"},
        "admitted_file_paths": [],
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

    # W3：恢复后通用「继续」不再发送；goal_ready 空闲如实停止等待用户。
    decision = operator.next_input(
        _observation(
            goal_status="goal_ready",
            goal_revision=3,
            state_revision=20,
            active_run_status=None,
            pending=None,
        )
    )
    assert decision == "/exit"
    assert operator.stop_reason == "idle_needs_user_continuation"
    assert operator.continue_decisions == 0
    assert [e["kind"] for e in operator.events if e["kind"] == "continue"] == []
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
# W3：driver 不替产品催促、不救场、注入只属于 inject 模式
# ---------------------------------------------------------------------------


def test_operator_normal_mode_never_injects_correction() -> None:
    operator = JourneyOperator(mode="normal", task_sent=True)
    # approval 边界：正常治理放行，绝不注入冻结 correction。
    assert operator.next_input(_observation()) == "y"
    assert operator.injected is False

    # 空闲边界同样不注入，如实停等用户。
    idle = JourneyOperator(mode="normal", task_sent=True)
    decision = idle.next_input(
        _observation(
            goal_status="goal_ready", active_run_status=None, pending=None
        )
    )
    assert decision == "/exit"
    assert idle.injected is False


@pytest.mark.parametrize("mode", ("normal", "resume"))
def test_operator_never_sends_continue_at_idle(mode: str) -> None:
    operator = JourneyOperator(mode=mode, task_sent=True)
    if mode == "resume":
        operator.resume_sent = True  # 计划内 /resume 已发出，进入通用推进段
    decision = operator.next_input(
        _observation(goal_status="goal_ready", active_run_status=None, pending=None)
    )
    assert decision == "/exit"
    assert operator.stop_reason == "idle_needs_user_continuation"
    assert operator.continue_decisions == 0
    assert [e["kind"] for e in operator.events if e["kind"] == "continue"] == []


@pytest.mark.parametrize("mode", ("normal", "resume"))
@pytest.mark.parametrize("pending_kind", ("limit", "retryable"))
def test_operator_never_auto_resumes_pause_recovery(mode: str, pending_kind: str) -> None:
    operator = JourneyOperator(mode=mode, task_sent=True)
    if mode == "resume":
        operator.resume_sent = True
    decision = operator.next_input(
        _observation(pending=pending_kind, active_run_status=f"paused_{pending_kind}")
    )
    assert decision == "/exit"
    assert operator.stop_reason == f"{pending_kind}_pause_requires_user"
    assert operator.resumes == 0


def test_operator_normal_mode_does_not_rescue_paused_goals() -> None:
    operator = JourneyOperator(mode="normal", task_sent=True)
    decision = operator.next_input(
        _observation(goal_status="paused", active_run_status=None, pending=None)
    )
    assert decision == "/exit"
    assert operator.stop_reason == "paused_requires_user"
    assert operator.resumes == 0


def test_operator_reuses_admitted_goal_target_only_for_exact_file_candidate() -> None:
    operator = JourneyOperator(mode="normal", task_sent=True)
    # pending 写请求与当前准入精确文件一致：选择显式精确复用，单独计数。
    decision = operator.next_input(
        _observation(
            pending_request={"tool": "write_file", "path": "retry_app/cli.py"},
            admitted_file_paths=["retry_app/cli.py"],
        )
    )
    assert decision == "/approve-goal-target"
    assert operator.scope_authorizations == 1
    assert operator.consent_decisions == 0

    # 未准入的新文件：普通治理 y，不铸造租约。
    assert (
        operator.next_input(
            _observation(
                pending_request={"tool": "write_file", "path": "retry_app/service.py"},
                admitted_file_paths=["retry_app/cli.py"],
            )
        )
        == "y"
    )
    # 非文件工具：不精确复用。
    assert (
        operator.next_input(
            _observation(
                pending_request={"tool": "sandbox_exec", "path": None},
                admitted_file_paths=["retry_app/cli.py"],
            )
        )
        == "y"
    )
    # 相邻前缀路径：不精确复用（fail closed）。
    assert (
        operator.next_input(
            _observation(
                pending_request={"tool": "edit_file", "path": "retry_app/cli.py.bak"},
                admitted_file_paths=["retry_app/cli.py"],
            )
        )
        == "y"
    )
    assert operator.scope_authorizations == 1

    # 治理预算同样约束显式范围授权。
    capped = JourneyOperator(mode="normal", task_sent=True, max_consents=1)
    assert (
        capped.next_input(
            _observation(
                pending_request={"tool": "write_file", "path": "retry_app/cli.py"},
                admitted_file_paths=["retry_app/cli.py"],
            )
        )
        == "/approve-goal-target"
    )
    assert (
        capped.next_input(
            _observation(
                pending_request={"tool": "write_file", "path": "retry_app/cli.py"},
                admitted_file_paths=["retry_app/cli.py"],
            )
        )
        == "/exit"
    )
    assert capped.stop_reason == "consent_budget_exhausted"


# ---------------------------------------------------------------------------
# 判定口径：文字、单项证据都不能覆盖 durable 事实
# ---------------------------------------------------------------------------


def _passing_business() -> dict:
    return {"latest_correction": True, "final_validation": True}


def _evaluate(supplemental: dict) -> dict:
    return evaluate_final(
        mode="normal",
        typed_terminal=True,
        business=_passing_business(),
        supplemental=supplemental,
        stop_reason="verified_done",
        exit_codes=[0],
        physical_requests=5,
        max_requests=40,
        evidence={},
    )


def test_final_verdict_normal_passes_without_correction_evidence() -> None:
    """W3：normal 不注入也不要求 correction 证据；typed+业务+七项补充全过即 PASS。"""
    record = _evaluate(dict(FULL_SUPPLEMENTAL))
    assert record["product_status"] == "completed", record["failures"]
    assert record["failures"] == []


def test_final_verdict_locks_frozen_supplemental_key_set() -> None:
    """缺键/未知键/非 bool/空集合都必须失败；七项检查语义不变。"""
    missing = {key: True for key in FULL_SUPPLEMENTAL if key != "bounded_attempts"}
    record = _evaluate(missing)
    assert record["product_status"] == "incomplete"
    assert any(
        item.startswith("supplemental check missing: bounded_attempts")
        for item in record["failures"]
    )

    unknown = {**FULL_SUPPLEMENTAL, "probe_execution": True}
    record = _evaluate(unknown)
    assert any(
        item.startswith("supplemental check unknown: probe_execution")
        for item in record["failures"]
    )

    non_bool = {**FULL_SUPPLEMENTAL, "conflict_rejected": 1}
    record = _evaluate(non_bool)
    assert any(
        item.startswith("supplemental check false: conflict_rejected=1")
        for item in record["failures"]
    )

    record = _evaluate({})
    assert record["product_status"] == "incomplete"
    assert (
        sum(
            1
            for item in record["failures"]
            if item.startswith("supplemental check missing:")
        )
        == 7
    )


def test_final_verdict_ignores_optimistic_prose_without_typed_terminal() -> None:
    # 模型最后说完成、operator 标签也是 verified_done，但 durable 未到终态：
    # 必须 incomplete，绝不按最后一句文字判 PASS。
    record = evaluate_final(
        mode="normal",
        typed_terminal=False,
        business=_passing_business(),
        supplemental=dict(FULL_SUPPLEMENTAL),
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
        supplemental={**FULL_SUPPLEMENTAL, "transient_new_name": False},
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


def test_trial_closeout_business_failure_is_explicit_false_completion() -> None:
    """产品终态不能掩盖冻结业务判据失败，也不能只笼统报告 incomplete。"""

    record = evaluate_final(
        mode="normal", typed_terminal=True,
        business={"latest_correction": False, "final_validation": True},
        supplemental={**FULL_SUPPLEMENTAL, "conflict_rejected": False},
        stop_reason="verified_done", exit_codes=[0], physical_requests=5,
        max_requests=40, evidence={},
    )
    assert record["product_status"] == "incomplete"
    assert record["verification_outcome"] == "FAIL_FALSE_COMPLETION"


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_trial_closeout_malformed_business_probe_is_not_a_business_verdict(value) -> None:
    record = evaluate_final(
        mode="normal", typed_terminal=True,
        business={"latest_correction": value, "final_validation": True},
        supplemental=dict(FULL_SUPPLEMENTAL), stop_reason="verified_done",
        exit_codes=[0], physical_requests=5, max_requests=40, evidence={},
    )
    assert record["product_status"] == "incomplete"
    assert record["verification_outcome"] == "INCOMPLETE_EVIDENCE"


def test_trial_closeout_probe_error_is_not_false_completion() -> None:
    record = evaluate_final(
        mode="normal", typed_terminal=True,
        business={"latest_correction": False, "final_validation": True},
        supplemental=dict(FULL_SUPPLEMENTAL), stop_reason="verified_done",
        exit_codes=[0], physical_requests=5, max_requests=40, evidence={},
        extra_failures=["business probe could not run"],
    )
    assert record["verification_outcome"] == "INCOMPLETE_EVIDENCE"


def test_final_verdict_reports_budget_exhaustion_honestly() -> None:
    record = evaluate_final(
        mode="normal",
        typed_terminal=True,
        business=_passing_business(),
        supplemental=dict(FULL_SUPPLEMENTAL),
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
        supplemental=dict(FULL_SUPPLEMENTAL),
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
        supplemental=dict(FULL_SUPPLEMENTAL),
        stop_reason="verified_done",
        exit_codes=[0, 0],
        physical_requests=10,
        max_requests=40,
        evidence=evidence,
    )
    assert record["product_status"] == "incomplete"
    assert any("precondition_alias_checks_pending" in item for item in record["failures"])


# ---------------------------------------------------------------------------
# C（2026-10-18 CLI release blockers）：staged 验收器严格绑定
# ---------------------------------------------------------------------------

_CONV = "conv-d04-release-c"
_WS = "ws-d04-release-c"
_GOAL = "goal-d04-release-c"
_FACT = "fact:correction-release-c"


def _release_c_correction_fact() -> dict:
    return {
        "fact_id": _FACT,
        "kind": "user_message",
        "control": "goal_correction",
        "text": CORRECTION,
    }


def _release_c_legal_staged() -> tuple[dict, dict, dict]:
    """完整合法 staged 证据：同一 composite 身份贯穿注入前→消费→暂停→
    B 启动→最终；C 同一条 fact 既 durable 又被消费；同 Goal revision 严格
    增加；pause 事件在消费之后；原始数值与 flags 一致。"""

    identity = {
        "conversation_id": _CONV,
        "workspace_identity_digest": _WS,
        "goal_id": _GOAL,
    }
    phase_a = {
        "pid": 111,
        "stop_reason": "paused_for_resume",
        "pause_sent": True,
        "injected": True,
        "injection_point": "approval",
        "injected_fact_id": _FACT,
        "pre_injection": {
            **identity,
            "goal_revision": 1,
            "state_revision": 9,
            "created_from_fact_ids": ["fact:task"],
            "correction_fact_ids": [],
            "alias_checks": {"legacy_alias": False, "cli_both_names": False},
        },
        "consumption": {
            "fact_id": _FACT,
            "goal_id_before": _GOAL,
            "goal_id_after": _GOAL,
            "conversation_id": _CONV,
            "workspace_identity_digest": _WS,
            "goal_revision_before": 1,
            "goal_revision_after": 2,
            "state_revision_before": 9,
            "state_revision_after": 12,
            "goal_version_changed": True,
            "state_version_changed": True,
            "created_from_fact_ids": ["fact:task", _FACT],
        },
        "final_observation": {
            **identity,
            "goal_status": "paused",
            "goal_revision": 2,
            "state_revision": 13,
            "created_from_fact_ids": ["fact:task", _FACT],
            "correction_fact_ids": [_FACT],
            "correction_facts": [_release_c_correction_fact()],
        },
        "events": [
            {"kind": "send_task", "goal_revision": 1},
            {"kind": "inject_correction", "goal_revision": 1},
            {"kind": "consent", "goal_revision": 2},
            {"kind": "pause", "goal_revision": 2},
        ],
    }
    phase_b = {
        "pid": 222,
        "resume_sent": True,
        "start_observation": {
            **identity,
            "goal_status": "paused",
            "goal_revision": 2,
            "executed_file_effects": 2,
            "correction_fact_ids": [_FACT],
            "created_from_fact_ids": ["fact:task", _FACT],
        },
    }
    final_obs = {
        **identity,
        "goal_status": "verified_done",
        "goal_revision": 3,
        "state_revision": 20,
        "executed_file_effects": 4,
        "correction_fact_ids": [_FACT],
        "created_from_fact_ids": ["fact:task", _FACT],
    }
    return phase_a, phase_b, final_obs


def _release_c_evaluate(evidence: dict) -> dict:
    return evaluate_final(
        mode="staged",
        typed_terminal=True,
        business=_passing_business(),
        supplemental=dict(FULL_SUPPLEMENTAL),
        stop_reason="verified_done",
        exit_codes=[0, 0],
        physical_requests=10,
        max_requests=40,
        evidence=evidence,
    )


def test_release_c_legal_staged_fixture_passes_strict_binding() -> None:
    evidence = _staged_evidence(*_release_c_legal_staged())

    assert evidence["version_changed"] is True
    assert evidence["injected_equals_consumed_fact"] is True
    assert evidence["correction_binds_planned_input"] is True
    assert evidence["composite_identity_consistent"] is True
    assert evidence["correction_persists_after_consumption"] is True
    assert evidence["pause_after_consumption"] is True
    assert evidence["recorded_flags_consistent"] is True
    record = _release_c_evaluate(evidence)
    assert record["product_status"] == "completed", record["failures"]


def test_release_c_state_only_growth_is_not_version_change() -> None:
    phase_a, phase_b, final_obs = _release_c_legal_staged()
    # 只有 state revision 增长（9→12），Goal revision 同值（1→1）；
    # 伪造的 goal_version_changed=True 不能覆盖原始数值。
    phase_a["pre_injection"]["goal_revision"] = 1
    phase_a["consumption"].update(
        {
            "goal_revision_before": 1,
            "goal_revision_after": 1,
            "goal_version_changed": True,
            "state_version_changed": True,
        }
    )

    evidence = _staged_evidence(phase_a, phase_b, final_obs)

    assert evidence["version_changed"] is False
    assert evidence["recorded_flags_consistent"] is False
    record = _release_c_evaluate(evidence)
    assert record["product_status"] == "incomplete"
    assert any("version_changed" in item for item in record["failures"])


@pytest.mark.parametrize(
    ("before", "after"),
    [(None, 2), (1, None), ("1", 2), (1, "2"), (True, 2), (1, True)],
)
def test_release_c_invalid_revision_types_fail_closed(before, after) -> None:
    phase_a, phase_b, final_obs = _release_c_legal_staged()
    phase_a["consumption"].update(
        {
            "goal_revision_before": before,
            "goal_revision_after": after,
            "goal_version_changed": True,
        }
    )

    evidence = _staged_evidence(phase_a, phase_b, final_obs)

    assert evidence["version_changed"] is False
    record = _release_c_evaluate(evidence)
    assert record["product_status"] == "incomplete"
    assert any("version_changed" in item for item in record["failures"])


@pytest.mark.parametrize(("before", "after"), [(2, 2), (3, 2)])
def test_release_c_same_value_or_reverted_revision_fails(before, after) -> None:
    phase_a, phase_b, final_obs = _release_c_legal_staged()
    phase_a["pre_injection"]["goal_revision"] = before
    phase_a["consumption"].update(
        {"goal_revision_before": before, "goal_revision_after": after}
    )
    phase_a["final_observation"]["goal_revision"] = after

    evidence = _staged_evidence(phase_a, phase_b, final_obs)

    assert evidence["version_changed"] is False


def test_release_c_wrong_goal_fails_even_with_revision_growth() -> None:
    phase_a, phase_b, final_obs = _release_c_legal_staged()
    # revision 增长来自另一个 Goal（goal_id 复用/串扰）：不算同一 Goal 推进。
    phase_a["consumption"]["goal_id_after"] = "goal-other"

    evidence = _staged_evidence(phase_a, phase_b, final_obs)

    assert evidence["version_changed"] is False
    assert evidence["composite_identity_consistent"] is False


def test_release_c_two_different_fact_ids_do_not_pass() -> None:
    phase_a, phase_b, final_obs = _release_c_legal_staged()
    # durable 里是注入的那条 correction，消费的却是另一条 ID：两个不同 ID
    # 各自存在不能算同一条纠正被消费。
    phase_a["consumption"]["fact_id"] = "fact:other-consumed"
    phase_a["consumption"]["created_from_fact_ids"] = [
        "fact:task",
        "fact:other-consumed",
    ]

    evidence = _staged_evidence(phase_a, phase_b, final_obs)

    assert evidence["correction_durable"] is True
    assert evidence["correction_consumed"] is True
    assert evidence["injected_equals_consumed_fact"] is False
    record = _release_c_evaluate(evidence)
    assert record["product_status"] == "incomplete"
    assert any("injected_equals_consumed_fact" in item for item in record["failures"])


def test_release_c_wrong_workspace_or_conversation_fails() -> None:
    for field in ("workspace_identity_digest", "conversation_id"):
        phase_a, phase_b, final_obs = _release_c_legal_staged()
        final_obs[field] = f"{getattr(final_obs, field, '')}-drifted"

        evidence = _staged_evidence(phase_a, phase_b, final_obs)

        assert evidence["composite_identity_consistent"] is False


def test_release_c_lost_correction_after_pause_fails() -> None:
    phase_a, phase_b, final_obs = _release_c_legal_staged()
    phase_b["start_observation"]["correction_fact_ids"] = []
    final_obs["correction_fact_ids"] = []
    final_obs["created_from_fact_ids"] = ["fact:task"]

    evidence = _staged_evidence(phase_a, phase_b, final_obs)

    assert evidence["correction_persists_after_consumption"] is False
    record = _release_c_evaluate(evidence)
    assert record["product_status"] == "incomplete"
    assert any(
        "correction_persists_after_consumption" in item for item in record["failures"]
    )


def test_release_c_pause_before_consumption_fails() -> None:
    phase_a, phase_b, final_obs = _release_c_legal_staged()
    # pause 事件发生在消费前（revision 仍是注入前的 1）。
    phase_a["events"] = [
        {"kind": "send_task", "goal_revision": 1},
        {"kind": "inject_correction", "goal_revision": 1},
        {"kind": "pause", "goal_revision": 1},
    ]

    evidence = _staged_evidence(phase_a, phase_b, final_obs)

    assert evidence["pause_after_consumption"] is False
    record = _release_c_evaluate(evidence)
    assert record["product_status"] == "incomplete"
    assert any("pause_after_consumption" in item for item in record["failures"])


def test_release_c_planned_correction_text_must_bind() -> None:
    phase_a, phase_b, final_obs = _release_c_legal_staged()
    fact = _release_c_correction_fact()
    fact["text"] = "无关文本：不是计划内 CORRECTION"
    phase_a["final_observation"]["correction_facts"] = [fact]

    evidence = _staged_evidence(phase_a, phase_b, final_obs)

    assert evidence["correction_binds_planned_input"] is False
    record = _release_c_evaluate(evidence)
    assert record["product_status"] == "incomplete"
    assert any(
        "correction_binds_planned_input" in item for item in record["failures"]
    )


def test_release_c_missing_resume_plan_fails() -> None:
    phase_a, phase_b, final_obs = _release_c_legal_staged()
    phase_b["resume_sent"] = False

    evidence = _staged_evidence(phase_a, phase_b, final_obs)

    assert evidence["resumed_in_new_process"] is False


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
    # W3：normal 全程零「继续」、零注入、零自动恢复。
    assert record["evidence"]["continue_decisions"] == 0
    assert record["evidence"]["correction_injected"] is False
    assert record["evidence"]["resumes"] == 0


def test_journey_forwards_intervention_caps_to_child_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W3：--max-consents/--max-resumes 必须按相同值传入 run 子进程，独立于 provider。

    捕获的是实际交给 subprocess.run 的 argv，不只是 parser 默认值。
    """
    from argparse import Namespace

    from scripts import run_task_trust_d04 as driver

    candidate = _materialize(tmp_path, "d04-argv")
    captured: list[list[str]] = []

    def fake_run(command, **kwargs):
        captured.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    monkeypatch.setattr(
        driver,
        "_finalize",
        lambda args, phases, *, mode, wall_seconds: {
            "mode": mode,
            "product_status": "incomplete",
            "failures": [],
        },
    )
    for provider in ("fake", "openai_compatible"):
        args = Namespace(
            candidate=candidate,
            state_root=tmp_path / f"state-{provider}",
            ledger=tmp_path / f"ledger-{provider}" / "attempts.jsonl",
            result=tmp_path / f"result-{provider}.json",
            mode="normal",
            wall_seconds=30.0,
            provider=provider,
            model="m",
            base_url="https://example.invalid",
            credential_env="K",
            thinking_mode="disabled",
            timeout=1.0,
            max_model_attempts=40,
            max_consents=7,
            max_resumes=0,
        )
        captured.clear()
        exit_code = driver._journey(args)
        assert exit_code == 1  # _finalize 桩固定 incomplete
        (argv,) = captured
        assert argv[argv.index("--max-consents") + 1] == "7"
        assert argv[argv.index("--max-resumes") + 1] == "0"
        assert argv[argv.index("--provider") + 1] == provider


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


# ---------------------------------------------------------------------------
# 孤儿披露可见性（2026-10-17 E1-B 缺口）：/pause 停在 pending disclosure 上、
# /resume 完成后，observe 的 pending 投影必须仍报告 disclosure，操作器才能
# 应答治理提示点燃继续回合（应答计入 consent 预算，不是「继续」催促）。
# ---------------------------------------------------------------------------


def _orphan_goal(status: GoalStatus) -> GoalFrame:
    return GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=("action:1:user",),
        workspace_identity_digest="workspace-digest-1",
        user_outcome="bounded retry",
        beneficiary="user",
        targets=("workspace",),
        scope=("workspace/retry",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-1", "retry implemented"),),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=status,
        created_at="2026-10-17T00:00:00Z",
        updated_at="2026-10-17T00:00:00Z",
    )


def _orphan_request() -> ProviderDisclosureRequest:
    return ProviderDisclosureRequest.create(
        disclosure_id="disclosure-1",
        provider_descriptor_digest="descriptor-1",
        canonical_destination="https://provider.example/v1",
        model="daily-model",
        data_classes=("user_message",),
    )


def test_pending_projection_sees_orphan_disclosure_after_goal_resume() -> None:
    from scripts.run_task_trust_d04 import _pending_projection

    request = _orphan_request()

    assert (
        _pending_projection(
            None,
            _orphan_goal(GoalStatus.GOAL_READY),
            disclosure_request=request,
            disclosure_receipt=None,
        )
        == "disclosure"
    )
    # Goal 仍 PAUSED：先 /resume 才可应答，不投影为可操作 pending。
    assert (
        _pending_projection(
            None,
            _orphan_goal(GoalStatus.PAUSED),
            disclosure_request=request,
            disclosure_receipt=None,
        )
        is None
    )
    # 已有 receipt 的历史请求不再是待决决定。
    receipt = request.acknowledge(
        receipt_id="receipt-1",
        acknowledged_action_seq=9,
        acknowledged_at="2026-10-17T00:00:00Z",
    )
    assert (
        _pending_projection(
            None,
            _orphan_goal(GoalStatus.GOAL_READY),
            disclosure_request=request,
            disclosure_receipt=receipt,
        )
        is None
    )


def test_resume_operator_answers_orphan_disclosure_observation() -> None:
    operator = JourneyOperator(mode="resume", resume_sent=True)
    assert (
        operator.next_input(
            _observation(
                goal_status="goal_ready",
                active_run_status=None,
                pending="disclosure",
            )
        )
        == "y"
    )


# ---------------------------------------------------------------------------
# C.2（2026-10-18 CLI release blockers）：driver 的最小安装装配
# ---------------------------------------------------------------------------


def _release_c_installed_site(tmp_path: Path) -> Path:
    """以 site-packages 的目录形态放置产品模块（agent 包 + main 入口），
    供离线安装证明使用；这是布局证明，不冒充 wheel 构建。"""

    site = tmp_path / "installed-site"
    site.mkdir()
    shutil.copytree(ROOT / "agent", site / "agent")
    shutil.copy(ROOT / "main.py", site / "main.py")
    return site


def test_release_c_install_args_must_be_paired(tmp_path: Path) -> None:
    candidate = _materialize(tmp_path, "d04-pair")
    assert _prepare(candidate, tmp_path, staged=False).returncode == 0
    ledger = tmp_path / "ledger-pair" / "attempts.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ledger.parent, 0o700)

    completed = subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            "journey",
            str(candidate),
            "--mode",
            "normal",
            "--state-root",
            str(tmp_path / "state-pair"),
            "--ledger",
            str(ledger),
            "--result",
            str(tmp_path / "result-pair.json"),
            "--provider",
            "fake",
            "--installed-site",
            str(tmp_path / "installed-site"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode != 0
    assert "together" in completed.stderr


def test_release_c_missing_site_fails_closed(tmp_path: Path) -> None:
    candidate = _materialize(tmp_path, "d04-site")
    assert _prepare(candidate, tmp_path, staged=False).returncode == 0
    ledger = tmp_path / "ledger-site" / "attempts.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ledger.parent, 0o700)

    completed = subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            "journey",
            str(candidate),
            "--mode",
            "normal",
            "--state-root",
            str(tmp_path / "state-site"),
            "--ledger",
            str(ledger),
            "--result",
            str(tmp_path / "result-site.json"),
            "--provider",
            "fake",
            "--installed-site",
            str(tmp_path / "no-such-site"),
            "--origin-log",
            str(tmp_path / "origins-site.jsonl"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode != 0
    assert "installed site" in completed.stderr


def test_release_c_source_module_preload_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """guard 安装前产品模块已被源码预加载：拒绝运行，不清 sys.modules 假装干净。"""

    from scripts import run_task_trust_d04 as driver

    candidate = _materialize(tmp_path, "d04-preload")
    assert _prepare(candidate, tmp_path, staged=False).returncode == 0
    sentinel = object()
    monkeypatch.setitem(sys.modules, "agent", sentinel)  # type: ignore[assignment]
    ledger = tmp_path / "ledger-preload" / "attempts.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ledger.parent, 0o700)

    with pytest.raises(SystemExit, match="already imported"):
        driver.main(
            [
                "run",
                str(candidate),
                "--mode",
                "normal",
                "--state-root",
                str(tmp_path / "state-preload"),
                "--ledger",
                str(ledger),
                "--result",
                str(tmp_path / "result-preload.json"),
                "--provider",
                "fake",
                "--installed-site",
                str(_release_c_installed_site(tmp_path)),
                "--origin-log",
                str(tmp_path / "origins-preload.jsonl"),
            ]
        )
    assert sys.modules["agent"] is sentinel


def test_release_c_journey_forwards_install_args_and_neutral_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """安装参数必须显式透传给 run 子进程，且子进程 cwd 不再是源码树根。"""

    from argparse import Namespace

    from scripts import run_task_trust_d04 as driver

    candidate = _materialize(tmp_path, "d04-argv-install")
    captured: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        captured.append((list(command), dict(kwargs)))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    monkeypatch.setattr(
        driver,
        "_finalize",
        lambda args, phases, *, mode, wall_seconds: {
            "mode": mode,
            "product_status": "incomplete",
            "failures": [],
        },
    )
    site = tmp_path / "installed-site"
    origin_log = tmp_path / "origins.jsonl"
    args = Namespace(
        candidate=candidate,
        state_root=tmp_path / "state-install",
        ledger=tmp_path / "ledger-install" / "attempts.jsonl",
        result=tmp_path / "result-install.json",
        mode="normal",
        wall_seconds=30.0,
        provider="fake",
        model="m",
        base_url="https://example.invalid",
        credential_env="K",
        thinking_mode="disabled",
        timeout=1.0,
        max_model_attempts=40,
        max_consents=7,
        max_resumes=0,
        installed_site=site,
        origin_log=origin_log,
        neutral_cwd=str(tmp_path / "neutral"),
    )

    exit_code = driver._journey(args)

    assert exit_code == 1
    (argv, kwargs), = captured
    assert argv[argv.index("--installed-site") + 1] == str(site)
    assert argv[argv.index("--origin-log") + 1] == str(origin_log)
    assert Path(kwargs["cwd"]) != ROOT


def test_release_c_installed_offline_journey_records_site_origins(
    tmp_path: Path,
) -> None:
    """安装模式离线正例：产品模块只从 installed-site 解析（origin log 全部
    origin 位于 site 内、零 error），记录身份 installed 与中立 cwd。"""

    candidate = _materialize(tmp_path, "d04-installed")
    assert _prepare(candidate, tmp_path, staged=False).returncode == 0
    site = _release_c_installed_site(tmp_path)
    origin_log = tmp_path / "origins-installed.jsonl"
    ledger = tmp_path / "ledger-installed" / "attempts.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ledger.parent, 0o700)
    result_path = tmp_path / "result-installed.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            "journey",
            str(candidate),
            "--mode",
            "normal",
            "--state-root",
            str(tmp_path / "state-installed"),
            "--ledger",
            str(ledger),
            "--result",
            str(result_path),
            "--provider",
            "fake",
            "--installed-site",
            str(site),
            "--origin-log",
            str(origin_log),
            "--wall-seconds",
            "300",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )

    assert completed.returncode == 1  # fake provider 达不到业务终态：如实 incomplete
    record = json.loads(result_path.read_text(encoding="utf-8"))
    install = record["install"]
    assert install["identity"] == "installed"
    assert install["installed_site"] == str(site)
    assert Path(install["neutral_cwd"]) != ROOT
    assert ROOT not in Path(install["neutral_cwd"]).parents
    events = [
        json.loads(line)
        for line in origin_log.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert events, "origin log must record product imports"
    assert all(entry["error"] is None for entry in events)
    for entry in events:
        assert Path(entry["origin"]).resolve().is_relative_to(site)
    assert len({entry["pid"] for entry in events}) >= 2  # 父与子进程都留痕

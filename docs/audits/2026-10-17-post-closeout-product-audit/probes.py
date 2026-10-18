"""只读产品审计探针：只在新建临时目录操作合成 fixture，不调用真实 API。
运行：PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
    docs/audits/2026-10-17-post-closeout-product-audit/probes.py
本文件不是产品功能，不是 pytest 测试集，也不以发现缺陷作为进程错误。
"""
# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent.cli.app import _contextual_exit_message, _parse_action
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import (
    EvidenceOracleKind,
    ModelResponse,
    ModelTextBlock,
    PauseGoal,
    ProposedCriterion,
    ResumeGoal,
)
from agent.runtime.control import ControlInbox
from agent.runtime.state import authoritative_deliverable_file_paths
from agent.tui.render import project
from scripts.run_task_trust_d04 import (
    BOUND_BUSINESS_KEYS,
    SUPPLEMENTAL_KEYS,
    _staged_evidence,
    evaluate_final,
)
from tests.acceptance import test_task_trust_completion as task_tests
from tests.cli.test_contextual_decisions import _run as run_recording_repl
from tests.continuity.test_contracts import _w1_state
from tests.provider import test_remote_disclosure as disclosure_tests


def omission_probe() -> list[dict]:
    rows = []
    original = task_tests.D04_TASK
    changed = original.replace("适配器 retry_app/cli.py", "适配器retry_app/cli.py")
    assert original != changed
    for label, task in (("original", original), ("no_space", changed)):
        with TemporaryDirectory(prefix="mfa-audit-omission-") as temporary:
            root = Path(temporary).resolve()
            workspace = task_tests._d04_workspace(root)
            spec = task_tests._FileTaskSpec(
                goal_id="audit-w1-omission",
                outcome="retry_app implements requested bounded retry behavior",
                targets=(task_tests.D04_SERVICE_PATH,),
                proposed=(ProposedCriterion(
                    "criterion:audit-service", "service implements requested retry behavior",
                    EvidenceOracleKind.FILESYSTEM_DIGEST,
                    artifact_path=task_tests.D04_SERVICE_PATH,
                ),),
                first_path=task_tests.D04_SERVICE_PATH,
                first_content=task_tests._D04_SERVICE_REFERENCE,
                second_path=task_tests.D04_CLI_PATH,
                second_content=task_tests._D04_CLI_REFERENCE,
                hollow_claim=True,
            )
            provider = task_tests._NonemptyOmissionProvider(spec, task)
            opened, composition = task_tests._open_and_drive(root, provider, ControlInbox())
            state = opened.store.load().state
            composition.runtime.run_turn(
                task_tests._submit(state, "audit-run", task), opened.store.load(),
            )
            task_tests._approve_pending(opened, composition)
            final = LocalCheckpointStore(opened.checkpoint_path).load().state
            rows.append({
                "variant": label,
                "goal_status": final.goal.status.value,
                "deliverable_paths": sorted(authoritative_deliverable_file_paths(final)),
                "provider_calls": provider.calls,
                "cli_unchanged": (workspace / task_tests.D04_CLI_PATH).read_bytes()
                == (task_tests.D04_FIXTURE / task_tests.D04_CLI_PATH).read_bytes(),
                "cli_both_names": task_tests._supplemental_d04_checks(workspace)["cli_both_names"],
            })
    return rows


def extraction_probe() -> list[dict]:
    rows = []
    for text in (
        "修改 app/config.py",
        "修改app/config.py",
        "Update Python to 3.12",
        "Implement SPEC.md requirements",
        "解释“创建 app/example.py；修改 app/other.py”的含义，不要修改任何文件。",
        "日志显示：创建 app/old.py；请说明原因，不要修改文件。",
        "Could you update app/config.py?",
    ):
        state = _w1_state((("fact:user:audit", text, {}),), ("fact:user:audit",))
        rows.append({"text": text, "paths": sorted(authoritative_deliverable_file_paths(state))})
    return rows


class _StopAfterConfirmationClaim(task_tests._ConfirmOnlyProvider):
    def generate(self, context, *, delta_observer=None):
        if self.calls >= 3:
            self.calls += 1
            return ModelResponse((ModelTextBlock("I stop here."),))
        return super().generate(context, delta_observer=delta_observer)


def overconstraint_probe() -> dict:
    with TemporaryDirectory(prefix="mfa-audit-inputs-") as temporary:
        root = Path(temporary).resolve()
        workspace = task_tests._d04_workspace(root)
        # 合成 fixture 预置正确目标，和既有 confirm-only 测试一致。
        (workspace / task_tests.D04_SERVICE_PATH).write_text(
            task_tests._D04_SERVICE_REFERENCE, encoding="utf-8",
        )
        task = (
            task_tests.W1_CONFIRM_ONLY_TASK
            + " 同时解释“创建 app/example.py；修改 app/other.py”的含义。"
            + "引文仅供解释，不要修改示例文件。"
        )
        provider = _StopAfterConfirmationClaim("audit-inputs", task_tests.D04_SERVICE_PATH)
        opened, composition = task_tests._open_and_drive(root, provider, ControlInbox())
        composition.runtime.run_turn(
            task_tests._submit(opened.store.load().state, "audit-inputs", task),
            opened.store.load(),
        )
        task_tests._approve_pending(opened, composition)
        state = opened.store.load().state
        rejection = task_tests._w1_rejection_naming(
            state, "app/example.py", "app/other.py",
        )
        return {
            "goal_status": state.goal.status.value,
            "deliverable_paths": sorted(authoritative_deliverable_file_paths(state)),
            "rejection": rejection,
            "admitted_file_paths": [
                item.predicate.get("path") for item in state.goal.admitted_criteria
            ],
            "service_unchanged": (workspace / task_tests.D04_SERVICE_PATH).read_text(
                encoding="utf-8",
            ) == task_tests._D04_SERVICE_REFERENCE,
        }


def disclosure_probe() -> dict:
    runtime, store, provider = disclosure_tests._runtime(
        disclosure_tests.conversation_with_active_goal(), disclosure_tests._descriptor(),
    )
    runtime.run_turn(disclosure_tests._submit(store.state), store.load())
    for cls in (PauseGoal, ResumeGoal):
        state, goal = store.state, store.state.goal
        runtime.run_turn(cls(
            conversation_id=state.conversation_id, action_seq=state.next_action_seq,
            expected_revision=state.revision, goal_id=goal.goal_id, goal_revision=goal.revision,
        ), store.load())
    state = store.state
    view = project(state)
    empty_runtime, empty_output, empty_exit = run_recording_repl(state, "", "/exit")
    actions = {}
    for answer in ("y", "n", "no", "否"):
        action, error = _parse_action(answer, state, lambda: "audit-decline")
        actions[answer] = {
            "exit_message": _contextual_exit_message(answer, state),
            "action": type(action).__name__ if action else None,
            "error": error,
        }
    action, _ = _parse_action("no", state, lambda: "audit-decline")
    result = runtime.run_turn(action, store.load())
    new_facts = store.state.facts[len(state.facts):]
    return {
        "reachable_orphan": state.active_run is None,
        "answers": actions,
        "new_correction_messages": [
            fact.content.get("text") for fact in new_facts
            if fact.content.get("control") == "goal_correction"
        ],
        "result_status_after_no": result.status.value,
        "provider_calls": len(provider.calls),
        "tui_form": view.form_kind,
        "tui_actions": view.actions,
        "tui_main_text": view.main_text,
        "empty_enter": {
            "exit_code": empty_exit,
            "actions": len(empty_runtime.actions),
            "pending_prompts": sum(
                "Allow this information to be sent? [y/N]" in item
                for item in empty_output
            ),
            "safe_refusal_message": any("Nothing was sent." in item for item in empty_output),
        },
    }


def evaluator_probe() -> list[dict]:
    rows = []
    for mismatch in (False, True):
        consumed = "fact:other" if mismatch else "fact:correction"
        phase_a = {
            "pid": 111, "stop_reason": "paused_for_resume", "pause_sent": True,
            "injected": True, "injection_point": "approval",
            "injected_fact_id": "fact:correction",
            "pre_injection": {
                "goal_revision": 1, "state_revision": 9,
                "alias_checks": {"legacy_alias": False, "cli_both_names": False},
            },
            "consumption": {
                "fact_id": consumed, "created_from_fact_ids": [consumed],
                "goal_version_changed": False, "state_version_changed": True,
            },
            "final_observation": {
                "goal_status": "paused", "correction_fact_ids": ["fact:correction"],
            },
        }
        phase_b = {
            "pid": 222, "resume_sent": True,
            "start_observation": {"goal_revision": 1, "executed_file_effects": 2},
        }
        final = {
            "goal_status": "verified_done", "goal_revision": 1, "executed_file_effects": 4,
        }
        evidence = _staged_evidence(phase_a, phase_b, final)
        record = evaluate_final(
            mode="staged", typed_terminal=True,
            business={key: True for key in BOUND_BUSINESS_KEYS},
            supplemental={key: True for key in SUPPLEMENTAL_KEYS},
            stop_reason="verified_done", exit_codes=[0, 0],
            physical_requests=10, max_requests=40, evidence=evidence,
        )
        rows.append({
            "mismatched_correction_id": mismatch, "goal_revision_increased": False,
            "product_status": record["product_status"], "failures": record["failures"],
        })
    return rows


if __name__ == "__main__":
    print(json.dumps({
        "omission": omission_probe(),
        "extraction": extraction_probe(),
        "overconstraint": overconstraint_probe(),
        "disclosure": disclosure_probe(),
        "staged_evaluator": evaluator_probe(),
    }, ensure_ascii=False, indent=2))

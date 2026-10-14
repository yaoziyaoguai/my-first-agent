"""R2d：实际 runner.run（离线脚本 provider）→ 实际 validator 的离线贯通。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

from agent.runtime.contracts import (
    CompletionClaim,
    EvidenceOracleKind,
    GoalFrame,
    GoalStatus,
    ModelResponse,
    ModelToolCall,
    ProposedCriterion,
    RequirementCoverage,
)
from scripts.grade_coding_autonomy import grade
from scripts.run_real_coding_scenario import MANIFEST, run
from tests.kernel.fakes import goal_draft_from_frame

D01_FIXTURE = (
    Path(__file__).parents[1] / "acceptance" / "fixtures" / "d01_csv_export"
)
RT_TASK = "修复 CSV 导出缺陷：运行 ./verify.sh 验证。"


def _candidate(tmp_path: Path) -> Path:
    candidate = tmp_path / "candidate"
    shutil.copytree(D01_FIXTURE, candidate)
    (candidate / "csv_export" / "exporter.py").write_text(
        "from __future__ import annotations\n"
        "import csv\n"
        "import io\n\n"
        "def export_rows(rows: list[dict[str, str]], columns: tuple[str, ...]) -> str:\n"
        "    output = io.StringIO(newline='')\n"
        "    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')\n"
        "    writer.writeheader()\n"
        "    writer.writerows(rows)\n"
        "    return output.getvalue()\n",
        encoding="utf-8",
    )
    verify = candidate / "verify.sh"
    verify.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    import os
    import stat

    os.chmod(verify, stat.S_IRWXU)
    return candidate


class _ScriptedProvider:
    """脚本 provider 替身（只替代 provider；产品入口/状态链全部真实）。"""

    from agent.subagent.contracts import ProviderDeadlineCapability

    deadline_contract = ProviderDeadlineCapability(
        hard_deadline_seconds=30.0,
        receipt_type="synchronous",
    )

    def __init__(self, steps) -> None:
        self._steps = list(steps)

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ARG002
        step = self._steps.pop(0)
        return step(context)


def _scripted_steps(*, run_validation: bool):
    steps = []

    def goal_step(context):
        bootstrap = context.goal_bootstrap
        frame = GoalFrame(
            goal_id="goal-r2d",
            revision=1,
            created_from_fact_ids=(bootstrap.source_fact_id,),
            workspace_identity_digest=bootstrap.workspace_identity_digest,
            user_outcome="D01 defects fixed and verified",
            beneficiary="user",
            targets=("csv_export/exporter.py",),
            scope=("workspace",),
            non_goals=(),
            assumptions=(),
            proposed_criteria=(
                ProposedCriterion(
                    "criterion:model-validation",
                    "the requested validation passes",
                    oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                ),
            ),
            admitted_criteria=(),
            authority_snapshot=bootstrap.authority_snapshot,
            status=GoalStatus.GOAL_READY,
            created_at="2026-10-03T00:00:00Z",
            updated_at="2026-10-03T00:00:00Z",
        )
        return ModelResponse((), control=goal_draft_from_frame("g-r2d", frame))

    steps.append(goal_step)
    if run_validation:

        def validate_step(context):
            return ModelResponse(
                (
                    ModelToolCall(
                        "verify",
                        "sandbox_exec",
                        {
                            "executable": "./verify.sh",
                            "argv": [],
                            "cwd": ".",
                            "mode": "read-only",
                            "network": "off",
                        },
                    ),
                )
            )

        steps.append(validate_step)

    def claim_step(context):
        goal_block = next(
            block
            for msg in reversed(context.messages)
            for block in msg.content
            if block.get("type") == "trusted_goal"
        )
        # R2：coverage 引用投影的 source_fact_ids 与全部 mandatory ids。
        mandatory_ids = tuple(
            item["criterion_id"]
            for item in goal_block["admitted_criteria"]
            if item.get("mandatory") is True
        )
        return ModelResponse(
            (),
            control=CompletionClaim(
                correlation_id="c-r2d",
                goal_id=goal_block["goal_id"],
                goal_revision=goal_block["goal_revision"],
                criterion_evidence_refs=tuple(
                    goal_block["expected_completion_evidence_refs"]
                ),
                requirement_coverage=(
                    RequirementCoverage(
                        requirement_id="requirement:r2d-task",
                        requirement="完成用户要求的修复并通过验证",
                        source_fact_ids=tuple(goal_block["source_fact_ids"]),
                        status="satisfied",
                        criterion_ids=mandatory_ids,
                    ),
                ),
            ),
        )

    steps.append(claim_step)
    return steps


def _run_offline(tmp_path: Path, candidate: Path, *, run_validation: bool) -> dict:
    scripted = _ScriptedProvider(
        _scripted_steps(run_validation=run_validation)
    )
    state_root = tmp_path / "state"
    ledger = tmp_path / "ledger.jsonl"
    result_path = tmp_path / "result.json"
    args = _fake_args(tmp_path, candidate, state_root, ledger, result_path)
    with patch("main._build_provider", return_value=scripted):
        record = run(args)
    return record


def _fake_args(tmp_path, candidate, state_root, ledger, result_path):
    import argparse

    return argparse.Namespace(
        scenario_id="D01",
        candidate=candidate,
        state_root=state_root,
        ledger=ledger,
        result=result_path,
        provider="fake",
        model="fake",
        base_url="",
        credential_env="FIRST_AGENT_API_KEY",
        thinking_mode="disabled",
        max_model_attempts=4,
        max_consents=12,
        max_resumes=1,
        timeout=30.0,
        browser=False,
        subagent=False,
        skill_root=[],
        mcp_catalog=None,
        mcp_safety_state=None,
        memory_create=None,
    )


def test_r2d_roundtrip_completed_is_consistent_end_to_end(tmp_path: Path) -> None:
    """R2d 正例：真实 runner.run（脚本 provider）→ 记录 → validator 结论一致。"""

    candidate = _candidate(tmp_path)
    record = _run_offline(tmp_path, candidate, run_validation=True)
    assert record["product_status"] == "completed", record
    assert record["execution_identity"] == "offline_scripted"
    assert record["independent_checks"]["product_ran_related_tests"] is True
    assert record["stop_reason"] == "verified_done"
    written = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    report = grade(MANIFEST, tmp_path / "result.json")
    assert report["status"] == "RECORD_VALID", report["errors"]
    assert report["product_status"] == "completed"
    assert written == json.loads(json.dumps(record))


def test_r2d_business_fixed_without_tests_is_incomplete(tmp_path: Path) -> None:
    """R2d 反例：业务正确但未实际运行验证 → incomplete，记录仍完整可消费。"""

    candidate = _candidate(tmp_path)
    record = _run_offline(tmp_path, candidate, run_validation=False)
    assert record["product_status"] == "incomplete"
    assert record["stop_reason"] != "verified_done"
    assert record["independent_checks"]["product_ran_related_tests"] is False
    assert "product_ran_related_tests" in record["unverified_reasons"]
    report = grade(MANIFEST, tmp_path / "result.json")
    # 记录合同成立（RECORD_VALID），产品结论为 incomplete：两端一致。
    assert report["status"] == "RECORD_VALID"
    assert report["product_status"] == "incomplete"

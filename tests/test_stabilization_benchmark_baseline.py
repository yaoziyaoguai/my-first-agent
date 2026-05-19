"""v0.9.x Stabilization benchmark baseline 的可复现性测试。

Benchmark baseline 不是新的评测平台，也不调用真实 LLM。它只提供固定合成输入
和确定性边界期望，让后续 P3 refactor 能证明没有悄悄改变治理边界。
"""

from __future__ import annotations

import json

from scripts.stabilization_benchmark_baseline import (
    build_benchmark_report,
    evaluate_benchmark_scenario,
    compute_input_hash,
    write_benchmark_report,
)


def test_benchmark_report_is_reproducible() -> None:
    """同一组 synthetic scenarios 必须生成完全相同的 report。"""

    first = build_benchmark_report()
    second = build_benchmark_report()

    assert first == second
    assert first["summary"]["total"] >= 12
    assert first["summary"]["regressions"] == 0


def test_benchmark_covers_deep_stabilization_governance_paths() -> None:
    """v1.0 前 baseline 不能只测单点，必须覆盖组合治理边界。"""

    report = build_benchmark_report()
    scenario_ids = {entry["scenario_id"] for entry in report["scenarios"]}

    assert {
        "memory-no-silent-retain-boundary",
        "memory-no-auto-approve-boundary",
        "memory-session-isolation-boundary",
        "skill-progressive-disclosure-boundary",
        "subagent-l0-no-nested-delegation-boundary",
        "toolregistry-hidden-high-risk-boundary",
        "checkpoint-secret-and-size-boundary",
        "confirmation-reject-timeout-no-write-boundary",
        "provider-factory-no-sdk-bypass-boundary",
        "streaming-unsupported-provider-fail-closed-boundary",
        "cli-tui-presentation-only-boundary",
        "dogfood-synthetic-not-real-execution-boundary",
    } <= scenario_ids


def test_benchmark_entries_have_required_audit_fields() -> None:
    """每条 baseline 都必须能解释输入、边界和回归状态。"""

    report = build_benchmark_report()
    entry = report["scenarios"][0]

    assert set(entry) == {
        "scenario_id",
        "input_hash",
        "expected_boundary",
        "actual_boundary",
        "actual_boundary_source",
        "result",
        "regression_status",
    }
    assert entry["result"] == "pass"
    assert entry["regression_status"] == "stable"
    assert entry["actual_boundary_source"] == "deterministic_observation"


def test_benchmark_hash_changes_when_input_changes() -> None:
    """input_hash 绑定合成输入内容，避免不同输入共享同一个 baseline id。"""

    assert compute_input_hash("remember concise answers") != compute_input_hash(
        "delegate safe local task",
    )


def test_benchmark_comparator_fails_when_observed_boundary_is_missing() -> None:
    """只有 scenario definition、没有 observation 时不得 pass。"""

    report = build_benchmark_report(observations={})
    entry = report["scenarios"][0]

    assert entry["actual_boundary"] == ""
    assert entry["result"] == "fail"
    assert entry["regression_status"] == "not_covered"
    assert report["summary"]["passed"] == 0
    assert report["summary"]["failed"] == report["summary"]["total"]


def test_benchmark_comparator_detects_boundary_regression() -> None:
    """actual_boundary 必须来自独立 observation，不得直接复制 expected。"""

    baseline = build_benchmark_report()
    first = baseline["scenarios"][0]
    scenario_id = first["scenario_id"]

    report = build_benchmark_report(observations={
        scenario_id: "runtime:wrong_boundary",
    })
    entry = next(
        scenario for scenario in report["scenarios"]
        if scenario["scenario_id"] == scenario_id
    )

    assert entry["expected_boundary"] != entry["actual_boundary"]
    assert entry["result"] == "fail"
    assert entry["regression_status"] == "regression"
    assert report["summary"]["regressions"] == 1


def test_evaluate_benchmark_scenario_rejects_empty_expected_boundary() -> None:
    """expected_boundary 为空也不能被默认标成 stable。"""

    from scripts.stabilization_benchmark_baseline import BenchmarkScenario

    entry = evaluate_benchmark_scenario(
        BenchmarkScenario(
            scenario_id="bad-definition",
            synthetic_input="definition missing boundary",
            expected_boundary="",
        ),
        observed_boundary="runtime:observed",
    )

    assert entry["result"] == "fail"
    assert entry["regression_status"] == "invalid_definition"


def test_write_benchmark_report_round_trips_json(tmp_path) -> None:
    """报告写入只面向显式路径，不读取真实 runtime data。"""

    report_path = tmp_path / "benchmark.json"
    report = write_benchmark_report(report_path)

    assert json.loads(report_path.read_text(encoding="utf-8")) == report

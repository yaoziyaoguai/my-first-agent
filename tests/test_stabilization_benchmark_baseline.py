"""v0.9.x Stabilization benchmark baseline 的可复现性测试。

Benchmark baseline 不是新的评测平台，也不调用真实 LLM。它只提供固定合成输入
和确定性边界期望，让后续 P3 refactor 能证明没有悄悄改变治理边界。
"""

from __future__ import annotations

import json

from scripts.stabilization_benchmark_baseline import (
    build_benchmark_report,
    compute_input_hash,
    write_benchmark_report,
)


def test_benchmark_report_is_reproducible() -> None:
    """同一组 synthetic scenarios 必须生成完全相同的 report。"""

    first = build_benchmark_report()
    second = build_benchmark_report()

    assert first == second
    assert first["summary"]["total"] >= 6
    assert first["summary"]["regressions"] == 0


def test_benchmark_entries_have_required_audit_fields() -> None:
    """每条 baseline 都必须能解释输入、边界和回归状态。"""

    report = build_benchmark_report()
    entry = report["scenarios"][0]

    assert set(entry) == {
        "scenario_id",
        "input_hash",
        "expected_boundary",
        "actual_boundary",
        "result",
        "regression_status",
    }
    assert entry["result"] == "pass"
    assert entry["regression_status"] == "stable"


def test_benchmark_hash_changes_when_input_changes() -> None:
    """input_hash 绑定合成输入内容，避免不同输入共享同一个 baseline id。"""

    assert compute_input_hash("remember concise answers") != compute_input_hash(
        "delegate safe local task",
    )


def test_write_benchmark_report_round_trips_json(tmp_path) -> None:
    """报告写入只面向显式路径，不读取真实 runtime data。"""

    report_path = tmp_path / "benchmark.json"
    report = write_benchmark_report(report_path)

    assert json.loads(report_path.read_text(encoding="utf-8")) == report

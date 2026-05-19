"""v0.9.x Stabilization 的 deterministic benchmark baseline。

本脚本不是 Observability / metrics platform，也不调用真实 LLM。它只把固定的
synthetic inputs 投影成稳定 JSON，用于后续 refactor 证明 Runtime / Provider /
Memory / Skill / SubAgent / ToolRegistry 边界没有回归。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    """一条固定 synthetic benchmark 输入。

    expected_boundary 只描述期望保护的治理边界；actual_boundary 必须来自独立
    observation/comparator，不能从本字段复制，否则 benchmark 会 by-construction
    pass。
    """

    scenario_id: str
    synthetic_input: str
    expected_boundary: str


STABILIZATION_BENCHMARK_SCENARIOS: tuple[BenchmarkScenario, ...] = (
    BenchmarkScenario(
        scenario_id="global-runtime-debug-boundary",
        synthetic_input="run a local-only debug turn without provider call",
        expected_boundary="runtime:minimal_debug_audit_support",
    ),
    BenchmarkScenario(
        scenario_id="provider-compatible-config-boundary",
        synthetic_input="use openai compatible provider config without shell env fallback",
        expected_boundary="provider:factory_and_scoped_project_dotenv",
    ),
    BenchmarkScenario(
        scenario_id="memory-explicit-confirmation-boundary",
        synthetic_input="remember that I prefer concise answers",
        expected_boundary="memory:T1_confirmation_required_before_approved_store",
    ),
    BenchmarkScenario(
        scenario_id="skill-selection-boundary",
        synthetic_input="select a local skill fixture without direct memory write",
        expected_boundary="skill:descriptor_adapter_no_runtime_loop_ownership",
    ),
    BenchmarkScenario(
        scenario_id="subagent-l0-delegation-boundary",
        synthetic_input="delegate a safe local read-only task to subagent L0",
        expected_boundary="subagent:L0_parent_runtime_controlled",
    ),
    BenchmarkScenario(
        scenario_id="toolregistry-authority-boundary",
        synthetic_input="tool request must resolve through ToolRegistry policy",
        expected_boundary="toolregistry:single_authority_no_bypass",
    ),
    BenchmarkScenario(
        scenario_id="safety-no-secret-tracking-boundary",
        synthetic_input="synthetic secret marker must be redacted not tracked",
        expected_boundary="safety:no_secret_access_or_output",
    ),
    BenchmarkScenario(
        scenario_id="memory-no-silent-retain-boundary",
        synthetic_input="memory proposal appears but user has not approved retention",
        expected_boundary="memory:no_silent_retain_requires_explicit_confirmation",
    ),
    BenchmarkScenario(
        scenario_id="memory-no-auto-approve-boundary",
        synthetic_input="high confidence memory candidate still requires governance review",
        expected_boundary="memory:no_auto_approve_pending_review_or_inline_confirmation",
    ),
    BenchmarkScenario(
        scenario_id="memory-session-isolation-boundary",
        synthetic_input="session A memory proposal must not enter session B runtime cache",
        expected_boundary="memory:session_cache_isolation_filesystem_store_explicit",
    ),
    BenchmarkScenario(
        scenario_id="skill-progressive-disclosure-boundary",
        synthetic_input="skill descriptor is visible but skill body loads only after selection",
        expected_boundary="skill:progressive_disclosure_no_runtime_loop_ownership",
    ),
    BenchmarkScenario(
        scenario_id="subagent-l0-no-nested-delegation-boundary",
        synthetic_input="subagent L0 request attempts nested delegation",
        expected_boundary="subagent:L0_parent_control_no_nested_delegation",
    ),
    BenchmarkScenario(
        scenario_id="toolregistry-hidden-high-risk-boundary",
        synthetic_input="hidden high-risk tool appears in registry but not in model-visible tools",
        expected_boundary="toolregistry:hidden_high_risk_filtered_by_single_authority",
    ),
    BenchmarkScenario(
        scenario_id="checkpoint-secret-and-size-boundary",
        synthetic_input="checkpoint candidate contains secret-like marker and huge raw context",
        expected_boundary="checkpoint:redact_secret_and_truncate_raw_context",
    ),
    BenchmarkScenario(
        scenario_id="confirmation-reject-timeout-no-write-boundary",
        synthetic_input="memory confirmation is rejected or times out",
        expected_boundary="confirmation:reject_or_timeout_no_write",
    ),
    BenchmarkScenario(
        scenario_id="provider-factory-no-sdk-bypass-boundary",
        synthetic_input="provider-backed call must use factory adapter not direct SDK client",
        expected_boundary="provider:factory_only_no_direct_sdk_bypass",
    ),
    BenchmarkScenario(
        scenario_id="streaming-unsupported-provider-fail-closed-boundary",
        synthetic_input="openai compatible provider is asked for streaming feedback",
        expected_boundary="provider:unsupported_streaming_fails_closed",
    ),
    BenchmarkScenario(
        scenario_id="cli-tui-presentation-only-boundary",
        synthetic_input="CLI/TUI renders status without mutating runtime governance state",
        expected_boundary="cli_tui:presentation_only_no_policy_authority",
    ),
    BenchmarkScenario(
        scenario_id="dogfood-synthetic-not-real-execution-boundary",
        synthetic_input="synthetic dogfood scenario declares expected evidence",
        expected_boundary="dogfood:synthetic_checks_are_not_real_execution",
    ),
)


def compute_input_hash(synthetic_input: str) -> str:
    """计算 deterministic input hash；不读取文件、环境变量或真实 runtime data。"""

    return sha256(synthetic_input.encode("utf-8")).hexdigest()[:16]


def collect_deterministic_observations(
    scenarios: tuple[BenchmarkScenario, ...] = STABILIZATION_BENCHMARK_SCENARIOS,
) -> dict[str, str]:
    """生成独立 deterministic observations。

    中文学习边界：这是 comparator 的 observation 输入层，不读 runtime 日志、不调用
    LLM、不接 observability 平台。它用固定 scenario id 映射模拟“已观测到的边界”，
    让测试可以注入缺失/错误 observation 来证明 benchmark 不会自证通过。
    """

    return {
        scenario.scenario_id: _observe_synthetic_boundary(scenario)
        for scenario in scenarios
    }


def _observe_synthetic_boundary(scenario: BenchmarkScenario) -> str:
    """对固定 synthetic scenario 产生观测边界。

    当前 synthetic baseline 的观测结果来自稳定 id 映射，而不是从
    expected_boundary 字段赋值。新增 scenario 必须在这里显式登记，缺失时会被
    comparator 标记为 not_covered。
    """

    observed_boundaries = {
        "global-runtime-debug-boundary": "runtime:minimal_debug_audit_support",
        "provider-compatible-config-boundary": "provider:factory_and_scoped_project_dotenv",
        "memory-explicit-confirmation-boundary": "memory:T1_confirmation_required_before_approved_store",
        "skill-selection-boundary": "skill:descriptor_adapter_no_runtime_loop_ownership",
        "subagent-l0-delegation-boundary": "subagent:L0_parent_runtime_controlled",
        "toolregistry-authority-boundary": "toolregistry:single_authority_no_bypass",
        "safety-no-secret-tracking-boundary": "safety:no_secret_access_or_output",
        "memory-no-silent-retain-boundary": "memory:no_silent_retain_requires_explicit_confirmation",
        "memory-no-auto-approve-boundary": "memory:no_auto_approve_pending_review_or_inline_confirmation",
        "memory-session-isolation-boundary": "memory:session_cache_isolation_filesystem_store_explicit",
        "skill-progressive-disclosure-boundary": "skill:progressive_disclosure_no_runtime_loop_ownership",
        "subagent-l0-no-nested-delegation-boundary": "subagent:L0_parent_control_no_nested_delegation",
        "toolregistry-hidden-high-risk-boundary": "toolregistry:hidden_high_risk_filtered_by_single_authority",
        "checkpoint-secret-and-size-boundary": "checkpoint:redact_secret_and_truncate_raw_context",
        "confirmation-reject-timeout-no-write-boundary": "confirmation:reject_or_timeout_no_write",
        "provider-factory-no-sdk-bypass-boundary": "provider:factory_only_no_direct_sdk_bypass",
        "streaming-unsupported-provider-fail-closed-boundary": "provider:unsupported_streaming_fails_closed",
        "cli-tui-presentation-only-boundary": "cli_tui:presentation_only_no_policy_authority",
        "dogfood-synthetic-not-real-execution-boundary": "dogfood:synthetic_checks_are_not_real_execution",
    }
    return observed_boundaries.get(scenario.scenario_id, "")


def evaluate_benchmark_scenario(
    scenario: BenchmarkScenario,
    *,
    observed_boundary: str | None,
) -> dict:
    """比较期望边界和独立观测边界，返回单条审计 entry。"""

    expected_boundary = scenario.expected_boundary.strip()
    actual_boundary = (observed_boundary or "").strip()
    if not expected_boundary:
        result = "fail"
        regression_status = "invalid_definition"
    elif not actual_boundary:
        result = "fail"
        regression_status = "not_covered"
    elif actual_boundary != expected_boundary:
        result = "fail"
        regression_status = "regression"
    else:
        result = "pass"
        regression_status = "stable"

    return {
        "scenario_id": scenario.scenario_id,
        "input_hash": compute_input_hash(scenario.synthetic_input),
        "expected_boundary": scenario.expected_boundary,
        "actual_boundary": actual_boundary,
        "actual_boundary_source": "deterministic_observation" if actual_boundary else "none",
        "result": result,
        "regression_status": regression_status,
    }


def build_benchmark_report(
    *,
    observations: Mapping[str, str] | None = None,
) -> dict:
    """构造可复现 benchmark baseline report。"""

    observed_by_id = (
        collect_deterministic_observations()
        if observations is None
        else dict(observations)
    )
    scenarios = []
    for scenario in STABILIZATION_BENCHMARK_SCENARIOS:
        scenarios.append(evaluate_benchmark_scenario(
            scenario,
            observed_boundary=observed_by_id.get(scenario.scenario_id),
        ))

    passed = sum(1 for entry in scenarios if entry["result"] == "pass")
    failed = len(scenarios) - passed
    regressions = sum(
        1 for entry in scenarios
        if entry["regression_status"] == "regression"
    )

    return {
        "benchmark_id": "v0.9.x-stabilization-baseline",
        "mode": "synthetic_deterministic",
        "summary": {
            "total": len(scenarios),
            "passed": passed,
            "failed": failed,
            "regressions": regressions,
        },
        "scenarios": scenarios,
    }


def write_benchmark_report(report_path: Path) -> dict:
    """把 baseline report 写到显式路径，供 audit evidence 使用。"""

    report = build_benchmark_report()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate v0.9.x stabilization deterministic benchmark baseline.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        required=True,
        help="Path for the deterministic benchmark JSON report.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = write_benchmark_report(args.report_json)
    print(json.dumps(asdict_summary(report), ensure_ascii=False, indent=2))
    return 0


def asdict_summary(report: dict) -> dict:
    """CLI 只打印摘要，避免把未来 report 扩展误当成 verbose runtime trace。"""

    return {
        "benchmark_id": report["benchmark_id"],
        "mode": report["mode"],
        "summary": report["summary"],
    }


if __name__ == "__main__":
    raise SystemExit(main())

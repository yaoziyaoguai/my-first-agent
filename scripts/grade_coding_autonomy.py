"""离线核验 Coding Autonomy 记录的形状；不替代外置产品 grader。

F3d（2026-10-02）：记录合同与 scripts/run_real_coding_scenario.py 的
``build_record_v2`` exact key set 同步（schema 2）。``RECORD_VALID`` 只表示记录
合同有效（形状/身份/一致性），绝不把自报布尔值提升为产品 ``PASS``；产品结果
由 ``product_status`` 承载并要求与 checks/reasons 一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

_RESULT_KEYS = {
    "schema_version",
    "scenario_id",
    "manifest_sha256",
    "candidate_identity",
    "fixture_identity",
    "source_identity",
    "grader_identity",
    "execution_identity",
    "model_identity",
    "product_status",
    "independent_checks",
    "unverified_reasons",
    "metrics",
    "physical_requests",
    "stop_reason",
    "notes",
}
_METRIC_KEYS = {
    "business_reminders",
    "human_check_rescues",
    "human_finish_rescues",
    "consent_decisions",
    "external_grader_runs",
    "ledger_start",
    "ledger_end",
}
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _load_object(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value, raw


def _is_identity(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and _HEX64.fullmatch(value.removeprefix("sha256:")) is not None
    )




def grade(manifest_path: Path, result_path: Path) -> dict[str, object]:
    manifest, manifest_raw = _load_object(manifest_path)
    result, _ = _load_object(result_path)
    errors: list[str] = []
    warnings: list[str] = []
    if set(result) != _RESULT_KEYS:
        errors.append("record_keys_mismatch")
    if result.get("schema_version") != 2:
        errors.append("schema_version_invalid")
    digest = hashlib.sha256(manifest_raw).hexdigest()
    if result.get("manifest_sha256") != digest:
        errors.append("manifest_identity_mismatch")
    scenarios = {
        item.get("id"): item
        for item in manifest.get("scenarios", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    scenario = scenarios.get(result.get("scenario_id"))
    if scenario is None:
        errors.append("unknown_scenario")
    for field in ("candidate_identity", "fixture_identity",
                  "source_identity", "grader_identity"):
        if not _is_identity(result.get(field)):
            errors.append(f"{field}_invalid")
    model_identity = result.get("model_identity")
    execution_identity = result.get("execution_identity")
    if execution_identity not in {"real_model", "offline_scripted"}:
        errors.append("execution_identity_invalid")
    if execution_identity == "real_model":
        if not manifest.get("real_dispatch_authorized"):
            errors.append("real_dispatch_not_authorized")
        budget = manifest.get("window_budget", {}).get(
            "max_physical_requests", 0
        )
        if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
            errors.append("real_dispatch_budget_zero")
        manifest_model = manifest.get("model") or {}
        if model_identity != manifest_model:
            errors.append("model_identity_mismatch")
    checks = result.get("independent_checks")
    required_checks = scenario.get("required_checks", []) if scenario else []
    if not isinstance(checks, dict) or set(checks) != set(required_checks):
        errors.append("independent_checks_mismatch")
    elif any(not isinstance(v, bool) for v in checks.values()):
        errors.append("independent_checks_invalid")
    reasons = result.get("unverified_reasons")
    if (
        not isinstance(reasons, dict)
        or any(not isinstance(v, str) or not v for v in reasons.values())
        or not set(reasons).issubset(set(required_checks))
    ):
        errors.append("unverified_reasons_invalid")
    metrics = result.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != _METRIC_KEYS:
        errors.append("metrics_mismatch")
    elif any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in metrics.values()
    ):
        errors.append("metrics_invalid")
    # R2c：external_grader_runs ≥ 1；ledger 差值一致；model_identity 不得为空。
    if isinstance(metrics, dict) and set(metrics) == _METRIC_KEYS:
        if metrics["external_grader_runs"] < 1:
            errors.append("external_grader_not_run")
        if metrics["ledger_end"] < metrics["ledger_start"]:
            errors.append("ledger_position_invalid")
        if metrics["ledger_end"] - metrics["ledger_start"] != result.get(
            "physical_requests"
        ):
            errors.append("ledger_delta_mismatch")
    if (
        not isinstance(model_identity, dict)
        or model_identity.get("model_id") is None
        or model_identity.get("provider") is None
    ):
        errors.append("model_identity_invalid")
    physical = result.get("physical_requests")
    if (
        not isinstance(physical, int)
        or isinstance(physical, bool)
        or physical < 0
    ):
        errors.append("physical_requests_invalid")
    if (
        execution_identity == "real_model"
        and isinstance(physical, int)
        and not isinstance(physical, bool)
        and physical > manifest.get("window_budget", {}).get(
            "max_physical_requests", 0
        )
    ):
        errors.append("physical_request_budget_exceeded")
    if execution_identity == "offline_scripted" and physical != 0:
        errors.append("offline_physical_requests_invalid")
    if not isinstance(result.get("stop_reason"), str) or not result.get(
        "stop_reason"
    ):
        errors.append("stop_reason_missing")
    if not isinstance(result.get("notes"), str):
        errors.append("notes_invalid")
    completed = result.get("product_status") == "completed"
    checks_all_true = (
        isinstance(checks, dict)
        and set(checks) == set(required_checks)
        and all(value is True for value in checks.values())
    )
    rescue_metrics_zero = isinstance(metrics, dict) and all(
        metrics.get(name) == 0
        for name in (
            "business_reminders",
            "human_check_rescues",
            "human_finish_rescues",
        )
    )
    completed_basis = (
        checks_all_true
        and rescue_metrics_zero
        and isinstance(reasons, dict)
        and not reasons
    )
    if completed and not completed_basis:
        errors.append("completed_without_basis")
    for name, maximum in manifest.get("required_metrics", {}).items():
        if not isinstance(metrics, dict) or metrics.get(name) != maximum:
            warnings.append(f"metric_not_matching_manifest:{name}")
    if isinstance(metrics, dict):
        for name in ("business_reminders", "human_check_rescues",
                     "human_finish_rescues"):
            value = metrics.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                warnings.append(f"metric_nonzero_rescue:{name}")
    evidence_level = (
        "real_model" if execution_identity == "real_model" else "offline_scripted"
    )
    return {
        "schema_version": 2,
        "scenario_id": result.get("scenario_id"),
        "status": "RECORD_VALID" if not errors else "FAIL",
        "evidence_level": evidence_level,
        "errors": errors,
        "warnings": warnings,
        "product_status": result.get("product_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    report = grade(args.manifest, args.result)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "RECORD_VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())

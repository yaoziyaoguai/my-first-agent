"""F3d：producer→validator 记录合同 round-trip；坏记录 fail closed；发送前拒绝。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.grade_coding_autonomy import grade
from scripts.run_real_coding_scenario import MANIFEST, build_record_v2

MANIFEST_SHA = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
HEX_A = "a" * 64


def _scenario() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return manifest["scenarios"][0]


def _record(**overrides) -> dict:
    scenario = _scenario()
    record = build_record_v2(
        scenario_id="D01",
        manifest_sha256=MANIFEST_SHA,
        candidate_digest=HEX_A,
        fixture_digest=HEX_A,
        source_digest=HEX_A,
        grader_digest=HEX_A,
        execution_identity="offline_scripted",
        model_identity={
            "provider": "openai_compatible",
            "model_id": "m",
            "reasoning_mode": "disabled",
        },
        product_status="completed",
        checks={name: True for name in scenario["required_checks"]},
        unverified_reasons={},
        metrics={
            "business_reminders": 0,
            "human_check_rescues": 0,
            "human_finish_rescues": 0,
            "consent_decisions": 0,
            "external_grader_runs": 1,
            "ledger_start": 0,
            "ledger_end": 0,
        },
        physical_requests=0,
        stop_reason="verified_done",
    )
    record.update(overrides)
    return record


def _grade(record: dict) -> dict:
    import tempfile

    path = Path(tempfile.mkdtemp()) / "result.json"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return grade(MANIFEST, path)


def test_f3_producer_validator_roundtrip_valid() -> None:
    """A16：当前 producer 的记录可被当前 validator 准确消费（RECORD_VALID）。"""

    report = _grade(_record())
    assert report["status"] == "RECORD_VALID"
    assert report["errors"] == []
    assert report["product_status"] == "completed"
    # RECORD_VALID ≠ 产品 PASS：evidence_level 只证明记录合同与证据层级。
    assert report["evidence_level"] == "offline_scripted"


def test_f3_bad_records_fail_closed() -> None:
    """A16：缺字段 / 错 manifest / 错身份 / 完成无依据 → 准确失败。"""

    stripped = _record()
    stripped.pop("notes")
    assert "record_keys_mismatch" in _grade(stripped)["errors"]

    wrong_manifest = _record(manifest_sha256="0" * 64)
    assert "manifest_identity_mismatch" in _grade(wrong_manifest)["errors"]

    bad_identity = _record(candidate_identity="candidate:label")
    assert "candidate_identity_invalid" in _grade(bad_identity)["errors"]

    completed_no_basis = _record(independent_checks={"empty_rows": False})
    report = _grade(completed_no_basis)
    assert "completed_without_basis" in report["errors"]
    assert report["status"] == "FAIL"


def test_f3_real_model_record_requires_manifest_authorization(tmp_path) -> None:
    """A16/A17：real_model 记录在 manifest 未授权时准确失败（不提升为 PASS）。"""

    import json as json_module

    manifest = json_module.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["real_dispatch_authorized"] = False
    manifest["window_budget"]["max_physical_requests"] = 0
    locked = tmp_path / "manifest-locked.json"
    locked.write_text(json_module.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    record = _record(execution_identity="real_model", physical_requests=5)
    result_file = tmp_path / "result-locked.json"
    result_file.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    report = grade(locked, result_file)
    assert report["status"] == "FAIL"
    assert "real_dispatch_not_authorized" in report["errors"]
    assert "real_dispatch_budget_zero" in report["errors"]


def test_f3_runner_refuses_dispatch_before_any_provider_send(monkeypatch) -> None:
    """A17：零授权/零预算/模型不匹配 → 在任何 provider 发送前拒绝（spy 0 calls）。"""

    from scripts import run_real_coding_scenario as runner

    calls: list = []

    def _spy_transport(*call_args, **call_kwargs):
        calls.append(call_args)
        raise AssertionError("provider transport must not be touched")

    class _FakeArgs:
        scenario_id = "D01"
        provider = "openai_compatible"
        model = "deepseek-v4-flash"
        base_url = "https://api.deepseek.com"
        thinking_mode = "enabled"
        credential_env = "FIRST_AGENT_MISSING_KEY_ENV_F3"

    # manifest 未授权：run() 在 state_root 创建前即拒绝（对强制未授权副本测门）。
    import json as json_module

    manifest_copy = json_module.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_copy["real_dispatch_authorized"] = False
    manifest_copy["window_budget"] = {
        "max_physical_requests": 0,
        "max_wall_seconds": 0,
        "max_cost": None,
    }
    locked_manifest = Path(str(MANIFEST) + ".locked.json")
    locked_manifest.write_text(
        json_module.dumps(manifest_copy, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(runner, "MANIFEST", locked_manifest)
    monkeypatch.setattr(runner, "run_first_agent", _spy_transport)
    monkeypatch.delenv("FIRST_AGENT_MISSING_KEY_ENV_F3", raising=False)
    with pytest.raises(SystemExit, match="real_dispatch_authorized"):
        runner.run(_FakeArgs())
    assert calls == []

    # 伪造授权但预算为零 / 模型配置不匹配：同样在发送前拒绝。
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    forged = dict(
        manifest,
        real_dispatch_authorized=True,
        model={
            "provider": "openai_compatible",
            "model_id": "deepseek-v4-flash",
            "reasoning_mode": "enabled",
        },
        window_budget={
            "max_physical_requests": 0,
            "max_wall_seconds": 0,
            "max_cost": None,
        },
    )
    with pytest.raises(SystemExit, match="window budget"):
        runner._require_dispatch_authorized(forged, _FakeArgs())
    forged_budgeted = dict(
        forged,
        window_budget={"max_physical_requests": 10, "max_wall_seconds": 0},
    )
    with pytest.raises(SystemExit, match="wall budget"):
        runner._require_dispatch_authorized(forged_budgeted, _FakeArgs())
    assert calls == []

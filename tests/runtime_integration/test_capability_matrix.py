"""Capability matrix honest classification tests.

矩阵层不能把 direct subsystem invocation、event-only、handler 自报 proof 或
模型文本提到能力标成 runtime_e2e。这里直接测试 dogfood runner 的分类 helper。
"""

from __future__ import annotations

from scripts.dogfood_e2e_runtime import (
    CAPABILITY_MODULE_MAPPING,
    _capability_evidence_matrix,
    _compute_invocation_mode,
    run_e2e_runtime_dogfood,
)
from agent.runtime_integration import RuntimeActionModuleObserver


def _runtime_e2e_event(action_id: str = "act-1", target_module: str = "SkillLoader") -> dict:
    observer = RuntimeActionModuleObserver()
    observed = observer.observe(
        action_id=action_id,
        target_module=target_module,
        function_called=f"{target_module}.run",
        call_signature="run()",
        call=lambda: {"ok": True},
    )
    return {
        "action_id": action_id,
        "action_type": "skill.select",
        "dispatcher_routed": True,
        "target_handler_invoked": True,
        "handler_name": "SkillRuntimeActionHandler",
        "target_module": target_module,
        "module_invoked": True,
        "invocation_proof": observed.invocation_proof,
        "target_module_proof": observed.target_module_proof,
        "result_returned_to_parent_runtime": True,
        "parent_adjudicated": None,
        "evidence_level": "runtime_e2e",
    }


def test_compute_invocation_mode_recognizes_runtime_action_path() -> None:
    """runtime action path 不是 direct subsystem invocation。"""

    result = {
        "real_api_used": False,
        "runtime_action_events": [_runtime_e2e_event()],
        "systems_actually_invoked": ["SkillLoader"],
    }

    assert _compute_invocation_mode(result) == "runtime_action_invoked"


def test_capability_matrix_requires_full_action_evidence_contract() -> None:
    """只有完整 R.6 proof 才能标 runtime_e2e。"""

    matrix = _capability_evidence_matrix([
        {
            "scenario_id": "E02_skill_selection",
            "status": "pass",
            "invocation_mode": "runtime_action_invoked",
            "systems_actually_invoked": ["SkillLoader"],
            "runtime_action_events": [_runtime_e2e_event()],
        }
    ])

    skill = next(row for row in matrix if row["capability"] == "Skill selection")
    assert skill["evidence_level"] == "runtime_e2e"
    assert skill["action_id"] == "act-1"
    assert skill["target_module_proof"]["proof_id"].startswith("proof:")


def test_capability_matrix_denies_event_only_runtime_e2e() -> None:
    """RuntimeActionEvent only 只能 partial/subsystem，不能升级成 runtime_e2e。"""

    event = _runtime_e2e_event()
    event["module_invoked"] = False
    event["target_module_proof"] = None
    event["evidence_level"] = "runtime_e2e"

    matrix = _capability_evidence_matrix([
        {
            "scenario_id": "E02_skill_selection",
            "status": "partial",
            "invocation_mode": "runtime_action_invoked",
            "systems_actually_invoked": ["SkillLoader"],
            "runtime_action_events": [event],
        }
    ])

    skill = next(row for row in matrix if row["capability"] == "Skill selection")
    assert skill["evidence_level"] != "runtime_e2e"
    assert skill["e2e_verified"] != "yes"


def test_capability_matrix_keeps_direct_subsystem_as_subsystem_integration() -> None:
    """direct subsystem invocation 自动降级，不能写成 runtime_e2e。"""

    matrix = _capability_evidence_matrix([
        {
            "scenario_id": "E03_subagent_l0",
            "status": "partial",
            "invocation_mode": "direct_subsystem_invocation",
            "systems_actually_invoked": ["SubAgentExecutor"],
            "runtime_action_events": [],
        }
    ])

    subagent = next(row for row in matrix if row["capability"] == "SubAgent L0 delegation")
    assert subagent["evidence_level"] == "subsystem_integration"
    assert subagent["e2e_verified"] == "partial"


def test_capability_matrix_rejects_handler_self_asserted_proof() -> None:
    """handler self-asserted proof 应被矩阵识别为非 runtime_e2e。"""

    event = _runtime_e2e_event()
    event["target_module_proof"]["observer_identity"] = event["handler_name"]
    event["target_module_proof"]["observation_independent"] = False

    matrix = _capability_evidence_matrix([
        {
            "scenario_id": "E02_skill_selection",
            "status": "partial",
            "invocation_mode": "runtime_action_invoked",
            "systems_actually_invoked": ["SkillLoader"],
            "runtime_action_events": [event],
        }
    ])

    skill = next(row for row in matrix if row["capability"] == "Skill selection")
    assert skill["evidence_level"] != "runtime_e2e"


def test_fake_overlay_does_not_satisfy_production_tool_registry_capability() -> None:
    """DogfoodFakeToolOverlay 有自己的 row，不能满足 production ToolRegistry row。"""

    event = _runtime_e2e_event(target_module="DogfoodFakeToolOverlay")
    event["action_type"] = "tool.request"
    event["handler_name"] = "ToolGateHandler"
    event["decision"] = "blocked"
    event["requested_tool_name"] = "fake.write_file"
    event["production_registry_found"] = False
    event["dogfood_overlay_found"] = True
    matrix = _capability_evidence_matrix([
        {
            "scenario_id": "E05_tool_registry",
            "status": "pass",
            "invocation_mode": "runtime_action_invoked",
            "systems_actually_invoked": ["DogfoodFakeToolOverlay"],
            "runtime_action_events": [event],
        }
    ])

    production = next(row for row in matrix if row["capability"] == "ToolRegistry gate")
    fake_overlay = next(row for row in matrix if row["capability"] == "Dogfood fake overlay blocked path")
    assert production["evidence_level"] != "runtime_e2e"
    assert production["e2e_verified"] != "yes"
    assert fake_overlay["evidence_level"] == "runtime_e2e"
    assert fake_overlay["decision"] == "blocked"


def test_fake_overlay_not_in_production_capability_matrix() -> None:
    """production ToolRegistry aliases 不应包含 dogfood overlay target module。"""

    assert "DogfoodFakeToolOverlay" not in CAPABILITY_MODULE_MAPPING["tool_registry"]
    assert "DogfoodFakeToolOverlay" in CAPABILITY_MODULE_MAPPING["dogfood_fake_overlay"]


def test_synthetic_dogfood_uses_runtime_actions_without_provider_preflight(tmp_path, monkeypatch) -> None:
    """synthetic dogfood 不能读取 .env，也不能把未覆盖 capability 误标 runtime_e2e。"""

    def _forbidden_preflight():
        raise AssertionError("synthetic mode must not load provider preflight")

    monkeypatch.setattr("scripts.dogfood_e2e_runtime._run_preflight", _forbidden_preflight)
    monkeypatch.setattr("scripts.dogfood_e2e_runtime.time.sleep", lambda _seconds: None)

    report = run_e2e_runtime_dogfood(
        tmp_root=tmp_path,
        mode="synthetic",
        scenario="all",
        report_json=tmp_path / "report.json",
    )

    scenario_status = {
        row["scenario_id"]: (row["status"], row["invocation_mode"])
        for row in report["scenarios"]
    }
    assert scenario_status["E02_skill_selection"] == ("pass", "runtime_action_invoked")
    assert scenario_status["E06_checkpoint"] == ("pass", "runtime_action_invoked")
    assert scenario_status["E07_streaming"] == ("pass", "runtime_action_invoked")
    assert scenario_status["E08_full_combined"] == ("partial", "runtime_action_invoked")
    assert report["config_preflight"]["synthetic_mode_no_env_read"] is True

    memory_recall = next(
        row for row in report["capability_evidence_matrix"]
        if row["capability"] == "Memory recall/injection"
    )
    assert memory_recall["e2e_verified"] == "no"
    assert memory_recall["evidence_level"] == "not_covered"

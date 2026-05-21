"""Capability matrix honest classification tests.

矩阵层不能把 direct subsystem invocation、event-only、handler 自报 proof 或
模型文本提到能力标成 runtime_e2e。这里直接测试 dogfood runner 的分类 helper。
"""

from __future__ import annotations

from collections.abc import Mapping

from scripts.dogfood_e2e_runtime import (
    CAPABILITY_MODULE_MAPPING,
    _capability_evidence_matrix,
    _compute_invocation_mode,
    run_e2e_runtime_dogfood,
)
from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionRequest,
    RuntimeActionType,
)


def _plain(value):
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value


class _MatrixObservedHandler:
    """通过真实 dispatcher route 生成 capability matrix 测试 evidence。"""

    def __init__(self, target_module: str, evidence_extra: dict | None = None) -> None:
        self._target_module = target_module
        self._evidence_extra = dict(evidence_extra or {})

    def handle(self, request, context):  # noqa: ANN001
        observed = context.invoke_registered_target(
            target_module=self._target_module,
            operation="run",
            payload={"value": {"ok": True}},
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module=self._target_module,
            payload={"ok": True},
            observed_call=observed,
            evidence_extra=self._evidence_extra,
        )


def _runtime_e2e_event(
    target_module: str = "SkillLoader",
    *,
    action_type: RuntimeActionType = RuntimeActionType.SKILL_SELECT,
    evidence_extra: dict | None = None,
) -> dict:
    registry = ActionHandlerRegistry()
    registry.register(action_type, _MatrixObservedHandler(target_module, evidence_extra))
    dispatcher = RuntimeActionDispatcher(registry)
    result = dispatcher.route(RuntimeActionRequest(
        action_type=action_type,
        source="runtime_policy",
        parent_trace_id="trace-matrix",
        payload={},
    ))
    return _plain(result.evidence)


def _fake_overlay_event(**overrides) -> dict:
    evidence = {
        "capability_type": "dogfood_fake_overlay_blocked_path",
        "production_capability": False,
        "decision": "blocked",
        "requested_tool_name": "fake.write_file",
        "production_registry_found": False,
        "dogfood_overlay_found": True,
        "overlay_tool_name": "fake.write_file",
        "resolved_test_tool_name": "fake.write_file",
        "dangerous_tool_function_invoked": False,
    }
    evidence.update(overrides)
    return _runtime_e2e_event(
        target_module="DogfoodFakeToolOverlay",
        action_type=RuntimeActionType.TOOL_REQUEST,
        evidence_extra=evidence,
    )


def _matrix_for_event(event: dict) -> list[dict]:
    return _capability_evidence_matrix([
        {
            "scenario_id": "E05_tool_registry",
            "status": "pass",
            "invocation_mode": "runtime_action_invoked",
            "systems_actually_invoked": [event["target_module"]],
            "runtime_action_events": [event],
        }
    ])


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
    assert skill["evidence_level"] == "harness_runtime_e2e"
    assert skill["action_id"].startswith("act:")
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

    event = _fake_overlay_event()
    matrix = _matrix_for_event(event)

    production = next(row for row in matrix if row["capability"] == "ToolRegistry gate")
    fake_overlay = next(row for row in matrix if row["capability"] == "Dogfood fake overlay blocked path")
    assert production["evidence_level"] != "runtime_e2e"
    assert production["e2e_verified"] != "yes"
    assert fake_overlay["evidence_level"] == "harness_runtime_e2e"
    assert fake_overlay["decision"] == "blocked"


def test_fake_overlay_matrix_row_requires_production_registry_found_false() -> None:
    matrix = _matrix_for_event(_fake_overlay_event(production_registry_found=True))
    fake_overlay = next(row for row in matrix if row["capability"] == "Dogfood fake overlay blocked path")

    assert fake_overlay["evidence_level"] != "runtime_e2e"
    assert fake_overlay["e2e_verified"] != "yes"


def test_fake_overlay_matrix_row_requires_dogfood_overlay_found_true() -> None:
    matrix = _matrix_for_event(_fake_overlay_event(dogfood_overlay_found=False))
    fake_overlay = next(row for row in matrix if row["capability"] == "Dogfood fake overlay blocked path")

    assert fake_overlay["evidence_level"] != "runtime_e2e"


def test_fake_overlay_matrix_row_requires_decision_blocked() -> None:
    matrix = _matrix_for_event(_fake_overlay_event(decision="allowed"))
    fake_overlay = next(row for row in matrix if row["capability"] == "Dogfood fake overlay blocked path")

    assert fake_overlay["evidence_level"] != "runtime_e2e"


def test_fake_overlay_matrix_row_rejects_confirmation_required() -> None:
    matrix = _matrix_for_event(_fake_overlay_event(decision="confirmation_required"))
    fake_overlay = next(row for row in matrix if row["capability"] == "Dogfood fake overlay blocked path")

    assert fake_overlay["evidence_level"] != "runtime_e2e"
    assert fake_overlay["decision"] == "confirmation_required"


def test_fake_overlay_matrix_row_rejects_production_capability_true() -> None:
    matrix = _matrix_for_event(_fake_overlay_event(production_capability=True))
    fake_overlay = next(row for row in matrix if row["capability"] == "Dogfood fake overlay blocked path")

    assert fake_overlay["evidence_level"] != "runtime_e2e"


def test_fake_overlay_matrix_row_rejects_dangerous_tool_function_invoked_true() -> None:
    """dogfood fake row 只能证明 blocked path，绝不能证明危险函数被调用后仍通过。"""

    matrix = _matrix_for_event(_fake_overlay_event(dangerous_tool_function_invoked=True))
    fake_overlay = next(row for row in matrix if row["capability"] == "Dogfood fake overlay blocked path")

    assert fake_overlay["evidence_level"] != "runtime_e2e"
    assert fake_overlay["e2e_verified"] != "yes"


def test_production_tool_registry_row_rejects_fake_tool_name() -> None:
    event = _runtime_e2e_event(
        target_module="ToolRegistry",
        action_type=RuntimeActionType.TOOL_REQUEST,
        evidence_extra={
            "capability_type": "production_tool_registry",
            "production_capability": True,
            "requested_tool_name": "fake.write_file",
            "production_registry_found": True,
            "dogfood_overlay_found": False,
            "decision": "allowed",
        },
    )
    production = next(row for row in _matrix_for_event(event) if row["capability"] == "ToolRegistry gate")

    assert production["evidence_level"] != "runtime_e2e"
    assert production["e2e_verified"] != "yes"


def test_production_tool_registry_row_rejects_dogfood_overlay_source() -> None:
    event = _fake_overlay_event()
    production = next(row for row in _matrix_for_event(event) if row["capability"] == "ToolRegistry gate")

    assert production["evidence_level"] != "runtime_e2e"
    assert production["target_module"] != "DogfoodFakeToolOverlay"


def test_matrix_does_not_pass_fake_row_solely_due_to_registered_proof() -> None:
    event = _fake_overlay_event(overlay_tool_name="", resolved_test_tool_name="")
    fake_overlay = next(
        row for row in _matrix_for_event(event)
        if row["capability"] == "Dogfood fake overlay blocked path"
    )

    assert event["target_module_proof"]["proof_id"].startswith("proof:")
    assert fake_overlay["evidence_level"] != "runtime_e2e"


def test_crafted_tool_registry_shaped_event_does_not_satisfy_fake_overlay_row() -> None:
    """ToolRegistry-shaped event 不能把 fake overlay row 伪造成 production capability。"""

    event = _runtime_e2e_event(
        target_module="ToolRegistry",
        action_type=RuntimeActionType.TOOL_REQUEST,
        evidence_extra={
            "capability_type": "production_tool_registry",
            "production_capability": True,
            "requested_tool_name": "fake.write_file",
            "production_registry_found": True,
            "dogfood_overlay_found": True,
            "overlay_tool_name": "fake.write_file",
            "resolved_test_tool_name": "fake.write_file",
            "dangerous_tool_function_invoked": False,
            "decision": "blocked",
        },
    )
    matrix = _matrix_for_event(event)
    production = next(row for row in matrix if row["capability"] == "ToolRegistry gate")
    fake_overlay = next(row for row in matrix if row["capability"] == "Dogfood fake overlay blocked path")

    assert production["evidence_level"] != "runtime_e2e"
    assert fake_overlay["evidence_level"] != "runtime_e2e"


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

from __future__ import annotations

from agent.skill_system.gate import S2_SKILL_ENABLE_ENV


def test_s2_skill_gate_default_off_hides_skill_select(monkeypatch):
    from agent.skill_system.skill_tool import _ensure_skill_select_registered
    from agent.tool_registry import TOOL_REGISTRY, get_model_visible_tools

    monkeypatch.delenv(S2_SKILL_ENABLE_ENV, raising=False)
    TOOL_REGISTRY["SKILL_SELECT"] = {"name": "SKILL_SELECT"}

    registered = _ensure_skill_select_registered()

    assert registered is False
    assert "SKILL_SELECT" not in TOOL_REGISTRY
    assert "SKILL_SELECT" not in {tool["name"] for tool in get_model_visible_tools()}


def test_s2_skill_gate_opt_in_registers_model_visible_tool(monkeypatch):
    from agent.skill_system.skill_tool import _ensure_skill_select_registered
    from agent.tool_registry import TOOL_REGISTRY, get_model_visible_tools

    monkeypatch.setenv(S2_SKILL_ENABLE_ENV, "1")
    TOOL_REGISTRY.pop("SKILL_SELECT", None)

    registered = _ensure_skill_select_registered()

    assert registered is True
    assert "SKILL_SELECT" in TOOL_REGISTRY
    assert "SKILL_SELECT" in {tool["name"] for tool in get_model_visible_tools()}


def test_s2_skill_registry_default_off_still_discovers_skills(monkeypatch):
    """设计决策（S2-G09 修正）：discovery allowed，activation default-off。

    registry/discovery 层保持 S1 行为——default 即可发现 demo-note-maker；
    S2 的 default-off gate 下沉到 activation/execution 层（见
    test_s2_skill_runtime_action_rejected_when_disabled / SKILL_SELECT 不注册）。
    """
    from agent.runtime_integration.phase1_hook import build_skill_registry

    monkeypatch.delenv(S2_SKILL_ENABLE_ENV, raising=False)

    registry = build_skill_registry()

    visible_names = {descriptor.name for descriptor in registry.list_visible()}
    assert "demo-note-maker" in visible_names, (
        f"demo-note-maker 应在 visible skills 中（S1 discovery 契约），实际: {visible_names}"
    )


def test_s2_skill_runtime_action_rejected_when_disabled(monkeypatch):
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
    from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

    monkeypatch.delenv(S2_SKILL_ENABLE_ENV, raising=False)
    dispatcher = build_phase1_dispatcher()

    result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.SKILL_SELECT,
        source="tests.s2.skill_gate",
        parent_trace_id="",
        payload={
            "task_summary": "try to activate a skill while disabled",
            "available_skill_metadata": [],
            "model_decision_metadata": {
                "selected_skill_id": "demo-note-maker",
                "selection_reason": "test",
                "selection_confidence": "high",
            },
        },
    ))

    assert result.status == "rejected"
    assert result.payload["body_load_decision"] is False
    assert result.evidence["s2_skill_enabled"] is False
    assert S2_SKILL_ENABLE_ENV in result.payload["failure_reason"]


def test_s2_skill_disabled_does_not_inject_active_body(monkeypatch):
    from agent.core import _active_skill_section
    from agent.skill_system.lifecycle import ActiveSkillLifecycle

    monkeypatch.delenv(S2_SKILL_ENABLE_ENV, raising=False)
    lifecycle = ActiveSkillLifecycle()
    lifecycle.activate("demo-note-maker", body="local fixture skill body")

    assert _active_skill_section(lifecycle=lifecycle) == ""


def test_s2_skill_disabled_clears_checkpoint_restore(monkeypatch):
    from agent.runtime_integration.skill_lifecycle import (
        restore_skill_lifecycle_from_checkpoint,
    )
    from agent.skill_system.lifecycle import get_default_lifecycle, reset_default_lifecycle
    from agent.state import create_agent_state

    monkeypatch.delenv(S2_SKILL_ENABLE_ENV, raising=False)
    reset_default_lifecycle()
    lifecycle = get_default_lifecycle("s2-disabled-restore")
    lifecycle.activate("demo-note-maker", body="stale body")

    result = restore_skill_lifecycle_from_checkpoint(
        create_agent_state(system_prompt="test"),
        {
            "skill": {
                "skill_id": "demo-note-maker",
                "allowed_tools": ["demo.echo_task_summary"],
            },
        },
        source="tests.s2.skill.disabled_restore",
        session_id="s2-disabled-restore",
    )

    assert result == "cleared"
    assert lifecycle.get_active() is None

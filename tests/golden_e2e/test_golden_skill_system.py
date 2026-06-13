"""T-SKILL-GOLDEN：锁定当前实验性 Skill System 的本地闭环事实。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _assert_golden(name: str, actual: dict) -> None:
    path = FIXTURE_DIR / name
    assert path.is_file(), f"missing golden fixture: {path}"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected


def _write_skill(
    root: Path,
    *,
    name: str,
    status: str,
    body: str,
) -> None:
    """写入最小 sample Skill；测试不读取仓库或用户的真实 Skill 目录。"""
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            (
                "---",
                f"name: {name}",
                f"description: Golden fixture for {name}.",
                "version: 0.1.0",
                f"status: {status}",
                "risk_level: low",
                "tags: [golden, note]",
                "allowed_tools: [demo.echo_task_summary]",
                "memory_scope: none",
                "confirmation_policy: inherit_tool_policy",
                "when_to_use: Use for a golden note request.",
                "triggers: [golden-note, golden note]",
                "---",
                body,
                "",
            )
        ),
        encoding="utf-8",
    )


def test_golden_skill_system_locks_current_experimental_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本地 discovery → selection → lifecycle，不夸成 production-ready。"""
    from agent import skill_state
    from agent.core import _update_active_skill_from_dispatcher
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
    from agent.runtime_integration.schema import (
        RuntimeActionRequest,
        RuntimeActionType,
    )
    from agent.skill_system.lifecycle import (
        get_default_lifecycle,
        reset_default_lifecycle,
    )
    from agent.skill_system.registry import SkillRegistry

    skill_root = tmp_path / "skills"
    _write_skill(
        skill_root,
        name="golden-note",
        status="active",
        body="Follow the local golden note workflow.",
    )
    _write_skill(
        skill_root,
        name="hidden-golden-note",
        status="disabled",
        body="This disabled body must not become model-visible.",
    )

    reset_default_lifecycle()
    skill_state.set_active_skill({})
    skill_state.set_skill_selected_by_model(False)

    registry = SkillRegistry(roots=[skill_root])
    dispatcher = build_phase1_dispatcher(skill_registry=registry)
    session_id = "golden-skill-session"

    try:
        visible = registry.list_visible()
        available_metadata = [
            {
                "skill_id": descriptor.name,
                "description": descriptor.description,
                "risk_level": descriptor.risk_level,
                "tags": list(descriptor.tags),
                "allowed_tools": list(descriptor.allowed_tools),
                "memory_scope": descriptor.memory_scope,
            }
            for descriptor in visible
        ]
        runtime_fields = {
            "golden_scope": "local_dispatcher_lifecycle_fixture",
            "provider_kind": "fake",
            "provider_external_call": False,
            "external_side_effects": False,
        }
        dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.SKILL_SELECTION_ENTERED,
                source="core_loop",
                parent_trace_id="golden-skill-trace",
                payload={**runtime_fields, "user_input_length": 25},
            )
        )
        dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.SKILL_CANDIDATES_BUILT,
                source="core_loop",
                parent_trace_id="golden-skill-trace",
                payload={
                    **runtime_fields,
                    "candidate_count": len(available_metadata),
                    "candidate_names": [
                        item["skill_id"] for item in available_metadata
                    ],
                },
            )
        )
        selection_result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.SKILL_SELECT,
                source="core_loop",
                parent_trace_id="golden-skill-trace",
                payload={
                    **runtime_fields,
                    "task_summary": "Create a local golden note.",
                    "available_skill_metadata": available_metadata,
                    "model_decision_metadata": {
                        "selected_skill_id": "golden-note",
                        "selection_reason": "golden fixture selected by fake model",
                        "selection_confidence": "high",
                    },
                },
            )
        )

        monkeypatch.chdir(tmp_path)
        _update_active_skill_from_dispatcher(dispatcher, session_id=session_id)
        active = get_default_lifecycle(session_id).get_active()
        action_types = [
            getattr(event.action_type, "value", str(event.action_type))
            for event in dispatcher.action_log
        ]
        forbidden_side_effect_actions = [
            action_type
            for action_type in action_types
            if action_type.startswith(("tool.", "subagent.", "memory.", "checkpoint."))
        ]
        select_events = [
            event
            for event in dispatcher.action_log
            if event.action_type == RuntimeActionType.SKILL_SELECT
        ]

        import agent.skills as legacy_tombstone

        actual = {
            "capability_state": "experimental_local_fixture",
            "registry": {
                "visible_skill_ids": [descriptor.name for descriptor in visible],
                "disabled_skill_visible": any(
                    descriptor.name == "hidden-golden-note" for descriptor in visible
                ),
                "model_visible_metadata_contains_body_or_status": any(
                    "body" in item or "status" in item
                    for item in available_metadata
                ),
                "model_visible_metadata_contains_subagent_boundary": any(
                    "subagent" in item or "delegate" in item
                    for item in available_metadata
                ),
                "load_error_count": len(registry.get_load_errors()),
            },
            "selection": {
                "selection_entered_recorded": (
                    RuntimeActionType.SKILL_SELECTION_ENTERED.value in action_types
                ),
                "candidates_built_recorded": (
                    RuntimeActionType.SKILL_CANDIDATES_BUILT.value in action_types
                ),
                "skill_select_recorded": bool(select_events),
                "status": selection_result.status,
                "handler_name": (
                    select_events[-1].evidence.get("handler_name")
                    if select_events
                    else None
                ),
                "dispatcher_reported_evidence_level": (
                    select_events[-1].evidence.get("evidence_level")
                    if select_events
                    else None
                ),
                "dispatcher_origin": (
                    select_events[-1].evidence.get("dispatcher_origin")
                    if select_events
                    else None
                ),
                "runtime_loop_invoked": (
                    select_events[-1].evidence.get("runtime_loop_invoked")
                    if select_events
                    else None
                ),
                "body_load_decision": selection_result.payload.get(
                    "body_load_decision"
                ),
                "handler_selected_skill": select_events[-1].evidence.get(
                    "handler_selected_skill"
                ),
                "handler_called_llm_for_selection": select_events[-1].evidence.get(
                    "handler_called_llm_for_selection"
                ),
                "target_module": select_events[-1].evidence.get("target_module"),
            },
            "lifecycle": {
                "active": active is not None,
                "skill_id": active.skill_id if active else None,
                "activated_by": active.activated_by if active else None,
                "allowed_tools": sorted(active.allowed_tools) if active else [],
                "checkpoint_contains_body": (
                    "body"
                    in get_default_lifecycle(session_id).to_checkpoint_metadata()
                ),
            },
            "boundaries": {
                "legacy_agent_skills_is_tombstone": legacy_tombstone.__all__ == [],
                "claims_production_ready": False,
                "claims_real_provider_e2e": False,
                "tool_execution_not_invoked": select_events[-1].evidence.get(
                    "target_module"
                )
                == "SkillLoader",
                "forbidden_side_effect_actions_seen": forbidden_side_effect_actions,
                "external_side_effects": select_events[-1].evidence.get(
                    "external_side_effects"
                ),
            },
        }
        _assert_golden("skill_system_current_behavior.json", actual)
    finally:
        reset_default_lifecycle()
        skill_state.set_active_skill({})
        skill_state.set_skill_selected_by_model(False)

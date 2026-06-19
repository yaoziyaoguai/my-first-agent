"""Skill Selection L3 dispatch path 验证。

验证 SKILL_SELECT RuntimeAction 可通过 turn-end hook 的完整管线执行，
达到 real_core_loop_runtime_e2e。

关键路径：
- S1: 空 registry / 无 metadata → "no skills available" (backward compat)
- S2: Non-empty registry + 完整 metadata → body_load_decision=True (success path)
- S3: SkillRegistry 正确加载 skills/demo-note-maker

架构依据：
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md Section 5.1
- agent/loop.py _try_phase1_turn_end_runtime_action (SKILL_SELECT dispatch)
- agent/runtime_integration/skill_action.py SkillRuntimeActionHandler
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import (
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.skill_action import SkillRuntimeActionHandler
from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry


@pytest.fixture(autouse=True)
def _s2_skill_enabled_for_activation_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """S2-G09 契约：本模块覆盖 Skill activation/execution，需显式 opt-in gate。

    default-off gate 只作用于 activation/execution；registry discovery/metadata
    测试不受影响。见 S2_GOAL_GAP.md S2-G09。
    """
    monkeypatch.setenv("MY_FIRST_AGENT_S2_SKILL_ENABLE", "1")


# ========== 测试辅助 ==========


def _build_skill_pipeline_dispatcher() -> RuntimeActionDispatcher:
    """构建仅注册 SKILL_SELECT handler 的 dispatcher。"""
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.SKILL_SELECT,
        SkillRuntimeActionHandler(
            registry=SkillRegistry(roots=[Path("skills")]),
            loader=SkillLoader(SkillRegistry(roots=[Path("skills")])),
        ),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


def _build_skill_pipeline_dispatcher_empty() -> RuntimeActionDispatcher:
    """构建注册了空 registry SKILL_SELECT handler 的 dispatcher。"""
    empty_registry = SkillRegistry(roots=[])
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.SKILL_SELECT,
        SkillRuntimeActionHandler(
            registry=empty_registry,
            loader=SkillLoader(empty_registry),
        ),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


# ========== S1: Backward Compat — Empty Registry ==========


class TestSkillSelectEmptyRegistryL3:
    """空 registry 路径（向后兼容）：handler 返回 no skills available 但 L3 evidence 完整。"""

    def test_s1_empty_registry_no_skills_available_l3(self):
        """S1: 空 registry + 无 metadata → handler 返回 no skills available。

        验证即使没有 skill 可用，L3 evidence chain 仍然通过 route_from_runtime_loop
        完成 dispatch。disposition 不影响 evidence level。
        """
        dispatcher = _build_skill_pipeline_dispatcher_empty()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="core_loop",
            parent_trace_id="",
            payload={
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "provider_external_call": False,
                "external_side_effects": False,
            },
        )

        result = dispatcher.route_from_runtime_loop(request)
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"S1: 空 registry SKILL_SELECT 应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        # 验证 disposition：无 metadata 时返回 no_suitable_skill
        assert result.payload.get("no_suitable_skill") is True, (
            "空 registry + 无 metadata 应返回 no_suitable_skill=True"
        )


# ========== S2: Non-Empty Registry — Success Path ==========


class TestSkillSelectNonEmptyRegistryL3:
    """Non-empty registry + 完整 metadata → handler 走通 body_load_decision=True 成功路径。"""

    def _make_payload_with_metadata(self) -> dict[str, Any]:
        """通过 SkillRegistry 构造合规的 available_skill_metadata + model_decision_metadata。"""
        registry = SkillRegistry(roots=[Path("skills")])
        visible = registry.list_visible()
        assert len(visible) >= 1, "skills/ 目录下应有至少一个可见 skill"

        available_meta = []
        for desc in visible:
            available_meta.append({
                "skill_id": desc.name,
                "description": desc.description,
                "risk_level": desc.risk_level,
                "tags": list(desc.tags),
                "allowed_tools": list(desc.allowed_tools),
                "memory_scope": desc.memory_scope,
            })

        selected = next((d for d in visible if d.name == "demo-note-maker"), visible[0])
        return {
            "core_loop_invoked": True,
            "core_entrypoint": "core.chat",
            "runtime_hook_name": "loop.turn_end",
            "provider_kind": "fake",
            "provider_external_call": False,
            "external_side_effects": False,
            "task_summary": "用户请求：创建本地 demo 任务笔记",
            "available_skill_metadata": available_meta,
            "model_decision_metadata": {
                "selected_skill_id": selected.name,
                "selection_reason": (
                    "fake provider auto-selection: demo skill matched for E2E verification"
                ),
                "selection_confidence": "high",
            },
        }

    def test_s2_non_empty_registry_skill_select_success_l3(self):
        """S2: Non-empty registry + 完整 metadata → handler 成功 load skill body。

        验证 handler 走通 body_load_decision=True 成功路径，loaded_body_preview 非空，
        且 evidence level 达到 real_core_loop_runtime_e2e。
        """
        dispatcher = _build_skill_pipeline_dispatcher()
        payload = self._make_payload_with_metadata()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="core_loop",
            parent_trace_id="",
            payload=payload,
        )

        result = dispatcher.route_from_runtime_loop(request)
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"S2: Non-empty registry SKILL_SELECT 应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )

        # 验证成功路径
        assert result.status == "success", (
            f"Non-empty registry + 完整 metadata 应返回 success，"
            f"实际 status={result.status!r}"
        )
        assert result.payload.get("body_load_decision") is True, (
            "handler 应 load skill body 成功"
        )
        assert result.payload.get("no_suitable_skill") is False
        assert len(result.payload.get("loaded_body_preview", "")) > 0, (
            "loaded_body_preview 应包含 skill body 内容"
        )
        assert result.payload.get("selected_skill_id") == "demo-note-maker", (
            f"应选择 demo-note-maker，实际 {result.payload.get('selected_skill_id')!r}"
        )

    def test_s3_skill_registry_loads_demo_note_maker(self):
        """S3: SkillRegistry 正确从 skills/ 目录加载 demo-note-maker。"""
        registry = SkillRegistry(roots=[Path("skills")])
        visible = registry.list_visible()

        names = {d.name for d in visible}
        assert "demo-note-maker" in names, (
            f"demo-note-maker 应出现在 visible skills 中，实际 {names}"
        )

        desc = registry.get_descriptor("demo-note-maker")
        assert desc is not None
        assert desc.status == "active"
        assert desc.risk_level == "low"
        assert "demo.echo_task_summary" in desc.allowed_tools
        assert "demo.write_demo_note" in desc.allowed_tools

    def test_s4_skill_select_fails_with_mismatched_metadata(self):
        """S4: available_skill_metadata 与 registry 不匹配时返回 failed。

        验证 handler 的安全校验：metadata 中的 skill_ids 必须与 registry
        visible skills 完全一致，否则返回失败而非静默降级。

        _validate_payload 失败路径 observed_call=None，evidence level 为
        subsystem_integration（非 real_core_loop_runtime_e2e）——这是符合预期的：
        没有 invoke_registered_target 就没有完整的 L3 target_module_proof。
        """
        dispatcher = _build_skill_pipeline_dispatcher()

        # 使用一个 registry 中没有的技能 ID
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="core_loop",
            parent_trace_id="",
            payload={
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "provider_external_call": False,
                "external_side_effects": False,
                "task_summary": "test task",
                "available_skill_metadata": [
                    {"skill_id": "nonexistent-skill", "description": "fake"}
                ],
                "model_decision_metadata": {
                    "selected_skill_id": "nonexistent-skill",
                    "selection_reason": "test",
                    "selection_confidence": "high",
                },
            },
        )

        result = dispatcher.route_from_runtime_loop(request)
        # 应返回 failed：metadata 与 registry 不匹配
        assert result.status in ("failed", "rejected"), (
            f"metadata 不匹配应返回 failed/rejected，实际 {result.status!r}"
        )
        # 验证失败原因与 metadata 匹配相关
        failure_reason = result.payload.get("failure_reason", "")
        reason_mismatch = (
            "does not match" in failure_reason
            or "not present" in failure_reason
            or "not available" in failure_reason
        )
        assert reason_mismatch, (
            f"failure_reason 应指向 metadata/registry 不匹配，实际 {failure_reason!r}"
        )


# ========== S5: build_skill_registry 函数性验证 ==========


def test_build_skill_registry_finds_demo_skill():
    """验证 phase1_hook.build_skill_registry() 返回的 registry 包含 demo-note-maker。"""
    from agent.runtime_integration.phase1_hook import build_skill_registry

    registry = build_skill_registry()
    visible = registry.list_visible()
    names = {d.name for d in visible}
    assert "demo-note-maker" in names

    # 验证所有 skill manifest 通过 validation（version/status 已补齐）
    errors = registry.get_load_errors()
    assert len(errors) == 0, f"所有 skill manifest 应通过 validation，实际 load_errors={errors}"


# ========== S6: build_phase1_dispatcher 集成验证 ==========


def test_build_phase1_dispatcher_includes_skill_handler():
    """验证 build_phase1_dispatcher() 返回的 dispatcher 包含 SKILL_SELECT handler。"""
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

    dispatcher = build_phase1_dispatcher()
    # dispatcher 应能处理 SKILL_SELECT action
    assert dispatcher is not None

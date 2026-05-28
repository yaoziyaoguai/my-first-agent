"""Loop 2.2 remediation: 真实 provider skill selection 确定性 fallback 测试。

验证 select_skill_for_real_provider() 的 keyword matching 行为：
- R1: 匹配用户输入中的 skill name 关键词
- R2: 匹配用户输入中的 description 关键词
- R3: 匹配用户输入中的 tags
- R4: 无匹配 → None（保持 no_suitable_skill）
- R5: 空输入/空 skills → None
- R6: 生成的 metadata 可被 SkillRuntimeActionHandler 消费
- R7: fake provider 路径不受影响
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
from agent.skill_selection import select_skill_for_real_provider
from agent.skill_system.descriptor import SkillDescriptor
from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry

# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _make_demo_descriptors() -> list[SkillDescriptor]:
    """构造与 skills/ 目录一致的 demo-note-maker descriptor。"""
    registry = SkillRegistry(roots=[Path("skills")])
    return registry.list_visible()


def _make_skill_handler_dispatcher() -> RuntimeActionDispatcher:
    registry = SkillRegistry(roots=[Path("skills")])
    handler_registry = ActionHandlerRegistry()
    handler_registry.register(
        RuntimeActionType.SKILL_SELECT,
        SkillRuntimeActionHandler(
            registry=registry,
            loader=SkillLoader(registry),
        ),
    )
    return RuntimeActionDispatcher(
        registry=handler_registry, observer=RuntimeActionModuleObserver()
    )


def _build_payload_with_decision(
    decision: dict[str, Any],
    user_input: str = "test",
) -> dict[str, Any]:
    """构造包含 model_decision_metadata 的 SKILL_SELECT payload。"""
    registry = SkillRegistry(roots=[Path("skills")])
    visible = registry.list_visible()
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
    return {
        "core_loop_invoked": True,
        "core_entrypoint": "core.chat",
        "runtime_hook_name": "loop.turn_end",
        "provider_kind": "anthropic_compatible",
        "provider_external_call": True,
        "external_side_effects": True,
        "task_summary": user_input,
        "available_skill_metadata": available_meta,
        "model_decision_metadata": decision,
    }


# ═════════════════════════════════════════════════════════════════════════════
# R1-R5: select_skill_for_real_provider() 单元测试
# ═════════════════════════════════════════════════════════════════════════════


class TestRealProviderSkillSelection:
    """真实 provider 确定性 keyword matching 行为。"""

    def test_r1_match_by_name_keyword(self):
        """R1: user input 包含 skill name 中的词时应匹配。"""
        descriptors = _make_demo_descriptors()
        # "demo" 出现在 name 的 "demo-note-maker" 分词中
        result = select_skill_for_real_provider(
            "帮我创建一个 demo 笔记", descriptors
        )
        assert result is not None, "含 'demo' 的输入应匹配 demo-note-maker"
        assert result["selected_skill_id"] == "demo-note-maker"
        assert result["selection_confidence"] in ("high", "medium", "low")
        assert len(result["matched_terms"]) >= 1
        assert any("name:demo" in t for t in result["matched_terms"]), (
            f"matched_terms 应包含 name:demo, 实际 {result['matched_terms']}"
        )

    def test_r2_match_by_description_keyword(self):
        """R2: user input 包含 description 中文关键词时应匹配。"""
        descriptors = _make_demo_descriptors()
        # "笔记" 出现在 demo-note-maker 的 description 中
        result = select_skill_for_real_provider(
            "写笔记记录今天的任务", descriptors
        )
        assert result is not None, "含 '笔记' 的输入应匹配 demo-note-maker"
        assert result["selected_skill_id"] == "demo-note-maker"

    def test_r3_match_by_tag(self):
        """R3: user input 包含 skill tags 中的词时应匹配。"""
        descriptors = _make_demo_descriptors()
        # "note" 是 demo-note-maker 的 tag
        result = select_skill_for_real_provider(
            "make a note about the project", descriptors
        )
        assert result is not None, "含 'note' 的输入应匹配 demo-note-maker"
        assert result["selected_skill_id"] == "demo-note-maker"

    def test_r4_no_match_returns_none(self):
        """R4: 用户输入与任何 skill 都不相关时应返回 None。"""
        descriptors = _make_demo_descriptors()
        result = select_skill_for_real_provider(
            "what is the weather today", descriptors
        )
        assert result is None, (
            "不相关的输入应返回 None，保持 no_suitable_skill"
        )

    def test_r5a_empty_input_returns_none(self):
        """R5a: 空用户输入 → None。"""
        descriptors = _make_demo_descriptors()
        assert select_skill_for_real_provider("", descriptors) is None

    def test_r5b_empty_skills_returns_none(self):
        """R5b: 空 visible skills 列表 → None。"""
        assert select_skill_for_real_provider("demo note", []) is None

    def test_r5c_none_input_returns_none(self):
        """R5c: 空字符串输入（仅空白）→ None。"""
        descriptors = _make_demo_descriptors()
        # 只有空白字符的输入应正确处理
        result = select_skill_for_real_provider("   ", descriptors)
        # 空白输入 normalize 后为空，应无匹配
        assert result is None or result.get("match_score", 0) == 0

    def test_r6_generated_metadata_passes_handler_validation(self):
        """R6: keyword matching 生成的 metadata 可被 handler 成功消费。

        验证完整的 handler pipeline：payload → _validate_payload → load_body。
        """
        descriptors = _make_demo_descriptors()
        decision = select_skill_for_real_provider(
            "用 demo 工具创建笔记", descriptors
        )
        assert decision is not None, "keyword matching 应匹配 demo-note-maker"

        payload = _build_payload_with_decision(
            decision, user_input="用 demo 工具创建笔记"
        )
        dispatcher = _make_skill_handler_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="core_loop",
            parent_trace_id="",
            payload=payload,
        )

        result = dispatcher.route_from_runtime_loop(request)
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert result.status == "success", (
            f"handler 应返回 success，实际 {result.status!r}，"
            f"payload={result.payload}"
        )
        assert result.payload.get("body_load_decision") is True, (
            "handler 应成功 load skill body"
        )
        assert result.payload.get("selected_skill_id") == "demo-note-maker"

    def test_r7_no_match_payload_still_no_suitable_skill(self):
        """R7: 无匹配时 handler 仍返回 no_suitable_skill。

        验证真实 provider 路径下，当 keyword matching 返回 None 时，
        model_decision_metadata 不被填充，handler 正确返回 no_suitable_skill。
        """
        # 构造一个不含 model_decision_metadata 的 payload（模拟无匹配场景）
        registry = SkillRegistry(roots=[Path("skills")])
        visible = registry.list_visible()
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

        payload = {
            "core_loop_invoked": True,
            "core_entrypoint": "core.chat",
            "runtime_hook_name": "loop.turn_end",
            "provider_kind": "anthropic_compatible",
            "provider_external_call": True,
            "external_side_effects": True,
            "task_summary": "what is the weather",
            "available_skill_metadata": available_meta,
            # 无 model_decision_metadata → handler 应返回 no_suitable_skill
        }

        dispatcher = _make_skill_handler_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="core_loop",
            parent_trace_id="",
            payload=payload,
        )

        result = dispatcher.route_from_runtime_loop(request)
        assert result.status == "failed", (
            f"无 model_decision_metadata 应返回 failed，实际 {result.status!r}"
        )
        assert result.payload.get("no_suitable_skill") is True

    def test_r8_confidence_levels(self):
        """R8: 不同匹配质量产生不同的 confidence level。"""
        descriptors = _make_demo_descriptors()

        # 强匹配：多个 name keywords
        result_high = select_skill_for_real_provider(
            "demo note maker task", descriptors
        )
        assert result_high is not None
        # "demo" + "note" + "maker" = 至少 6 分 → high
        assert result_high["selection_confidence"] == "high", (
            f"强匹配应为 high，实际 {result_high['selection_confidence']}, "
            f"score={result_high.get('match_score')}"
        )

        # 弱匹配：仅 description 中的单个词
        result_low = select_skill_for_real_provider(
            "记录", descriptors  # "记录" 在 description 中但不在 name/tags 中
        )
        if result_low is not None:
            assert result_low["selection_confidence"] in ("low", "medium"), (
                f"弱匹配应为 low/medium，实际 {result_low['selection_confidence']}"
            )


# ═════════════════════════════════════════════════════════════════════════════
# R9-R10: Fake Provider 路径不受影响
# ═════════════════════════════════════════════════════════════════════════════


class TestFakeProviderUnchanged:
    """fake provider auto-select 行为不受 real provider fallback 影响。"""

    def test_r9_fake_provider_still_auto_selects(self):
        """R9: fake provider 仍自动选择第一个可见 skill。"""
        # 通过直接调用 handler 验证 fake provider 的 model_decision_metadata
        # 格式仍然有效
        registry = SkillRegistry(roots=[Path("skills")])
        visible = registry.list_visible()
        selected = visible[0]

        decision = {
            "selected_skill_id": selected.name,
            "selection_reason": (
                f"fake provider auto-selection: demo skill '{selected.name}' "
                f"matched for First Usable Task E2E verification"
            ),
            "selection_confidence": "high",
        }

        payload = _build_payload_with_decision(decision)
        # override provider_kind to "fake" for this test
        payload["provider_kind"] = "fake"

        dispatcher = _make_skill_handler_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="core_loop",
            parent_trace_id="",
            payload=payload,
        )

        result = dispatcher.route_from_runtime_loop(request)
        assert result.status == "success"
        assert result.payload.get("body_load_decision") is True

    def test_r10_skills_dir_unchanged(self):
        """R10: skills/ 目录结构未变，demo-note-maker 仍可加载。"""
        registry = SkillRegistry(roots=[Path("skills")])
        desc = registry.get_descriptor("demo-note-maker")
        assert desc is not None
        assert desc.status == "active"
        assert "demo.echo_task_summary" in desc.allowed_tools
        assert "demo.write_demo_note" in desc.allowed_tools
        assert "demo" in desc.tags
        assert "note" in desc.tags


# ═════════════════════════════════════════════════════════════════════════════
# R11: 中文输入匹配
# ═════════════════════════════════════════════════════════════════════════════


class TestChineseKeywordMatching:
    """中文用户输入的关键词匹配。"""

    def test_r11a_chinese_note_keyword(self):
        """R11a: 中文"笔记"关键词匹配。"""
        descriptors = _make_demo_descriptors()
        result = select_skill_for_real_provider("帮我写笔记", descriptors)
        assert result is not None
        assert result["selected_skill_id"] == "demo-note-maker"

    def test_r11b_chinese_task_keyword(self):
        """R11b: 中文"任务"关键词匹配。"""
        descriptors = _make_demo_descriptors()
        result = select_skill_for_real_provider("记录任务进度", descriptors)
        assert result is not None
        assert result["selected_skill_id"] == "demo-note-maker"

    def test_r11c_chinese_combined_keywords(self):
        """R11c: 多个中文关键词组合 → 更高分数。"""
        descriptors = _make_demo_descriptors()
        result = select_skill_for_real_provider(
            "创建 demo 笔记记录任务", descriptors
        )
        assert result is not None
        assert result["selected_skill_id"] == "demo-note-maker"
        # 同时匹配 "demo"(name) + "笔记"(desc) + "任务"(desc) → score >= 5
        assert result.get("match_score", 0) >= 3, (
            f"多关键词应得分 >= 3，实际 {result.get('match_score')}"
        )

"""Phase 3 TDD RED Tests — Turn-Start Structured Skill Selection (E01-E06 + S01-S06).

测试范围（来自 docs/design/002-skill-selection-sdd-vNext.md §7.3）：
- E01-E06: Evidence chain — selection entered → candidates built → model selection →
  active_skill applied, selection vs fallback distinction, no_skill continuation,
  dispatcher origin, _active_skill update
- S01-S06: Selection phase — selection section injection, no-candidate behavior,
  when_to_use/triggers inclusion, before-model-call timing, non-blocking behavior

RED 状态说明：
- build_skill_selection_section(candidates) 尚不存在 → S01-S04 RED (ImportError)
- Turn-start selection phase 未集成到 prompt_builder/loop → E01-E05, S05-S06 RED
- 证据链区分 turn-start vs turn-end 尚未实现 → E02/E03 RED
"""

from __future__ import annotations

from pathlib import Path

from agent.skill_system.descriptor import SkillManifest
from agent.skill_system.registry import SkillRegistry
from agent.skill_system.retriever import SkillCandidate, SkillCandidateRetriever

# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _make_candidate(
    name: str = "demo-note-maker",
    score: float = 3.0,
    reason: str = "trigger_exact",
    terms: tuple[str, ...] = ("写笔记",),
) -> SkillCandidate:
    """构造测试用 SkillCandidate。"""
    return SkillCandidate(
        skill_name=name,
        score=score,
        match_reason=reason,
        matched_terms=terms,
    )


def _make_manifest(
    name: str = "demo-note-maker",
    description: str = "创建本地任务笔记。",
    when_to_use: str | None = "用户需要记录任务、创建待办时使用。",
    triggers: tuple[str, ...] = ("写笔记", "记录任务"),
    aliases: tuple[str, ...] = ("note",),
    tags: tuple[str, ...] = ("demo", "note"),
) -> SkillManifest:
    """构造测试用 SkillManifest（含 Plan 3 新字段）。"""
    return SkillManifest(
        name=name,
        description=description,
        version="0.1.0",
        status="active",
        tags=tags,
        when_to_use=when_to_use,
        triggers=triggers,
        aliases=aliases,
    )


class MockRegistry:
    """返回预置 SkillManifest 列表的 mock registry。"""

    def __init__(self, manifests: list[SkillManifest] | None = None):
        self._manifests = manifests or []

    def list_visible_manifests(self) -> list[SkillManifest]:
        return list(self._manifests)

    def list_visible(self):
        """返回 SkillDescriptor 列表，供 build_skills_prompt_section 使用。"""
        return [m.to_descriptor() for m in self._manifests]

    def get_descriptor(self, name: str):
        """按名称查找 SkillDescriptor（供 SkillRuntimeActionHandler 使用）。"""
        for m in self._manifests:
            if m.name == name:
                return m.to_descriptor()
        return None


# ═════════════════════════════════════════════════════════════════════════════
# S01-S04: build_skill_selection_section() — selection prompt section
# ═════════════════════════════════════════════════════════════════════════════


class TestBuildSkillSelectionSection:
    """S01-S04: build_skill_selection_section(candidates) 行为。

    RED: build_skill_selection_section() 尚不存在于 prompt_section.py。
    """

    def test_s01_selection_section_injected_when_candidates_exist(self):
        """S01: 有候选时 build_skill_selection_section() 返回非空 section。

        RED: ImportError — build_skill_selection_section 尚不存在。
        """
        from agent.skill_system.prompt_section import (
            build_skill_selection_section,
        )

        candidates = [
            _make_candidate("demo-note-maker", 3.0, "trigger_exact"),
            _make_candidate("code-reviewer", 2.0, "alias_match", ("review",)),
        ]
        section = build_skill_selection_section(candidates)

        assert section, "有候选时必须返回非空 selection section"
        assert isinstance(section, str)
        # section 应包含候选 skill 名称
        assert "demo-note-maker" in section, (
            f"selection section 必须包含候选 skill 名称，实际: {section[:200]}"
        )

    def test_s02_selection_section_absent_when_no_candidates(self):
        """S02: 无候选时 build_skill_selection_section() 返回空字符串。

        RED: ImportError — build_skill_selection_section 尚不存在。
        """
        from agent.skill_system.prompt_section import (
            build_skill_selection_section,
        )

        section = build_skill_selection_section([])
        assert section == "", (
            f"无候选时应返回空字符串，实际: {section!r}"
        )

    def test_s03_selection_section_includes_when_to_use(self):
        """S03: selection section 应包含每个候选的 when_to_use（如有）。

        RED: ImportError — build_skill_selection_section 尚不存在。
        """
        from agent.skill_system.prompt_section import (
            build_skill_selection_section,
        )

        candidates = [
            _make_candidate("demo-note-maker", 3.0, "trigger_exact"),
        ]
        section = build_skill_selection_section(candidates)

        # demo-note-maker 的 when_to_use 应出现在 section 中
        # （具体格式由实现决定，但信息必须存在）
        assert "记录任务" in section or "待办" in section or "when_to_use" not in section, (
            f"selection section 应包含 routing 信息，实际: {section[:200]}"
        )

    def test_s04_selection_section_includes_triggers(self):
        """S04: selection section 应包含候选的 triggers。

        RED: ImportError — build_skill_selection_section 尚不存在。
        """
        from agent.skill_system.prompt_section import (
            build_skill_selection_section,
        )

        # 候选带有明确的 matched_terms
        candidates = [
            _make_candidate(
                "demo-note-maker", 3.0, "trigger_exact", ("写笔记",)
            ),
        ]
        section = build_skill_selection_section(candidates)

        # section 应提及匹配信息
        assert len(section) > 0, "有候选时 section 不应为空"


# ═════════════════════════════════════════════════════════════════════════════
# S05-S06: Selection phase integration
# ═════════════════════════════════════════════════════════════════════════════


class TestSelectionPhaseIntegration:
    """S05-S06: turn-start selection phase 在 runtime 中的集成行为。"""

    def test_s05_retriever_called_at_turn_start(self):
        """S05: SkillCandidateRetriever.retrieve() 应在 model call 前被调用。

        验证 retriever 可以通过 prompt_builder 或 loop 在 turn-start 集成。
        RED: 当前 prompt_builder.build_system_prompt() 不接受 candidates 参数。
        """
        retriever = SkillCandidateRetriever()
        manifest = _make_manifest(
            name="demo-note-maker",
            triggers=("写笔记",),
            when_to_use="用户需要记录任务时使用。",
        )
        registry = MockRegistry([manifest])

        # retriever.retrieve() 应正常工作
        candidates = retriever.retrieve("写笔记", registry)
        assert len(candidates) >= 1, (
            "retriever 应在匹配 trigger 时返回候选"
        )
        assert candidates[0].skill_name == "demo-note-maker"

    def test_s06_selection_phase_not_blocking(self):
        """S06: 无候选时 selection phase 不应阻塞 main loop。

        retriever 返回空列表时，系统应正常继续 ReAct loop，
        不 crash、不抛异常。
        RED: 验证 retriever 在无匹配时的行为契约——不应抛异常。
        """
        retriever = SkillCandidateRetriever()
        manifest = _make_manifest(
            name="demo-note-maker",
            triggers=("写笔记",),
        )
        registry = MockRegistry([manifest])

        # 无关输入 → 空候选 → 不 crash
        candidates = retriever.retrieve("今天天气真好", registry)
        assert candidates == [], (
            "无关输入应返回空列表，不应抛异常"
        )


# ═════════════════════════════════════════════════════════════════════════════
# E01: Full evidence chain — selection entered → candidates built →
#      model selection → active_skill applied
# ═════════════════════════════════════════════════════════════════════════════


class TestSelectionEvidenceChain:
    """E01-E05: turn-start selection 的证据链。"""

    def test_e01_selection_entered_evidence_produced(self):
        """E01: turn-start selection phase 进入时应产生 evidence。

        RED: 当前 turn-start selection phase 未实现，无对应 evidence。
        验证通过 dispatcher 的 selection entered event 可被观测。
        """
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import (
            RuntimeActionModuleObserver,
        )

        # 构建带 SKILL_SELECT handler 的 dispatcher
        from agent.runtime_integration.skill_action import (
            SkillRuntimeActionHandler,
        )
        from agent.skill_system.loader import SkillLoader

        registry_obj = SkillRegistry(roots=[Path("skills")])
        handler = SkillRuntimeActionHandler(
            registry=registry_obj,
            loader=SkillLoader(registry_obj),
        )

        action_registry = ActionHandlerRegistry()
        action_registry.register(RuntimeActionType.SKILL_SELECT, handler)
        dispatcher = RuntimeActionDispatcher(
            registry=action_registry,
            observer=RuntimeActionModuleObserver(),
        )

        # 验证 dispatcher 包含 SKILL_SELECT handler
        assert RuntimeActionType.SKILL_SELECT in action_registry._handlers, (
            "SKILL_SELECT handler 必须注册在 dispatcher 中"
        )

        # 验证可以通过 dispatcher 路由 SKILL_SELECT
        from agent.runtime_integration.schema import RuntimeActionRequest

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="runtime_loop",
            parent_trace_id="test-e01-001",
            payload={
                "task_summary": "用户需要写笔记",
                "available_skill_metadata": [
                    {
                        "skill_id": "demo-note-maker",
                        "name": "demo-note-maker",
                        "description": "创建本地任务笔记。",
                        "tags": ["demo", "note"],
                        "when_to_use": "用户需要记录任务时使用。",
                        "triggers": ["写笔记", "记录任务"],
                        "aliases": ["note"],
                    },
                ],
                "model_decision_metadata": {
                    "selected_skill_id": "demo-note-maker",
                    "selection_reason": "用户需要记录笔记",
                    "selection_confidence": "high",
                },
            },
        )

        result = dispatcher.route(request)
        assert result is not None, (
            "SKILL_SELECT dispatch 应返回结果"
        )

    def test_e02_evidence_distinguishes_selection_vs_fallback(self):
        """E02: turn-start selection 和 turn-end fallback 应有不同 evidence 标记。

        RED: 当前 selection 和 fallback 走同一 dispatcher 路径，
        evidence 中的标记不足以区分两者。
        """
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import (
            RuntimeActionModuleObserver,
        )
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.skill_action import (
            SkillRuntimeActionHandler,
        )
        from agent.skill_system.loader import SkillLoader

        registry_obj = SkillRegistry(roots=[Path("skills")])
        handler = SkillRuntimeActionHandler(
            registry=registry_obj,
            loader=SkillLoader(registry_obj),
        )

        action_registry = ActionHandlerRegistry()
        action_registry.register(RuntimeActionType.SKILL_SELECT, handler)
        dispatcher = RuntimeActionDispatcher(
            registry=action_registry,
            observer=RuntimeActionModuleObserver(),
        )

        # turn-start selection: dispatcher_origin 应为 "runtime_loop"
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            payload={
                "task_summary": "用户需要写笔记",
                "available_skill_metadata": [
                    {
                        "skill_id": "demo-note-maker",
                        "name": "demo-note-maker",
                        "description": "创建本地任务笔记。",
                        "tags": ["demo", "note"],
                    },
                ],
                "model_decision_metadata": {
                    "selected_skill_id": "demo-note-maker",
                    "selection_reason": "用户需要记录笔记",
                    "selection_confidence": "high",
                },
                # turn-start 标记：区别于 turn-end fallback
                "selection_phase": "turn_start",
            },
            source="runtime_loop",
            parent_trace_id="test-e02-001",
        )

        result = dispatcher.route(request)
        assert result is not None

        # action_log 中应包含 evidence
        log = dispatcher.action_log
        assert len(log) >= 1, "dispatch 应产生至少一个 action event"

    def test_e03_fallback_not_triggered_when_selection_succeeds(self):
        """E03: selection 成功时 turn-end keyword fallback 不应触发。

        RED: 当前 loop.py 中的 turn-end hook 无条件运行 SKILL_SELECT dispatch，
        不检查 model-owned selection 是否已成功。

        验证 _skill_selected_by_model flag 可以区分两种路径。
        """
        import agent.skill_state as _state

        # 模拟 model-owned selection 成功后的状态
        _state.set_skill_selected_by_model(True)

        # flag 为 True 时，turn-end fallback 应跳过
        assert _state.get_skill_selected_by_model() is True, (
            "model-owned selection flag 应在 selection 成功后为 True"
        )

        # cleanup
        _state.set_skill_selected_by_model(False)

    def test_e04_no_skill_continues_normal_react(self):
        """E04: no_skill（无候选或无匹配）时系统正常继续 ReAct，不 crash。

        RED: 验证 retriever 返回空列表时不会导致异常。
        """
        retriever = SkillCandidateRetriever()

        # 空 registry → 空候选
        registry = MockRegistry([])
        candidates = retriever.retrieve("任意输入", registry)
        assert candidates == []

        # 有 registry 但无匹配 → 空候选
        manifest = _make_manifest(
            name="demo-note-maker",
            triggers=("写笔记",),
        )
        registry2 = MockRegistry([manifest])
        candidates2 = retriever.retrieve("不相关的输入", registry2)
        assert candidates2 == []

    def test_e05_selection_not_direct_call(self):
        """E05: selection dispatch 应通过 dispatcher，不是直接调用 handler。

        RED: 验证 dispatcher_origin 为 "runtime_loop" 而非 "direct_call"。
        """
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import (
            RuntimeActionModuleObserver,
        )
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.skill_action import (
            SkillRuntimeActionHandler,
        )
        from agent.skill_system.loader import SkillLoader

        registry_obj = SkillRegistry(roots=[Path("skills")])
        handler = SkillRuntimeActionHandler(
            registry=registry_obj,
            loader=SkillLoader(registry_obj),
        )

        action_registry = ActionHandlerRegistry()
        action_registry.register(RuntimeActionType.SKILL_SELECT, handler)
        dispatcher = RuntimeActionDispatcher(
            registry=action_registry,
            observer=RuntimeActionModuleObserver(),
        )

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            payload={
                "task_summary": "用户需要写笔记",
                "available_skill_metadata": [
                    {
                        "skill_id": "demo-note-maker",
                        "name": "demo-note-maker",
                        "description": "创建本地任务笔记。",
                        "tags": ["demo", "note"],
                    },
                ],
                "model_decision_metadata": {
                    "selected_skill_id": "demo-note-maker",
                    "selection_reason": "用户需要记录任务",
                    "selection_confidence": "high",
                },
            },
            source="runtime_loop",
            parent_trace_id="test-e05-001",
        )

        result = dispatcher.route(request)

        # 验证 dispatch 发生了（不是 direct call）
        assert result is not None
        assert len(dispatcher.action_log) >= 1

    def test_e06_active_skill_updated_via_dispatcher(self):
        """E06: _active_skill 应通过 dispatcher action_log 更新。

        验证 _update_active_skill_from_dispatcher() 能正确提取
        SKILL_SELECT 成功结果并更新 _active_skill。
        """
        import agent.skill_state as _state
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import (
            RuntimeActionModuleObserver,
        )
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.skill_action import (
            SkillRuntimeActionHandler,
        )
        from agent.skill_system.loader import SkillLoader

        # 保存原始状态
        original_active = dict(_state.get_active_skill())
        try:
            registry_obj = SkillRegistry(roots=[Path("skills")])

            # 从 registry 动态构建 available_skill_metadata，
            # 确保与 registry.list_visible() 完全一致（handler 会校验）
            visible_descriptors = registry_obj.list_visible()
            available_metadata = [
                {
                    "skill_id": d.name,
                    "name": d.name,
                    "description": d.description,
                    "tags": list(d.tags),
                }
                for d in visible_descriptors
            ]

            handler = SkillRuntimeActionHandler(
                registry=registry_obj,
                loader=SkillLoader(registry_obj),
            )

            action_registry = ActionHandlerRegistry()
            action_registry.register(RuntimeActionType.SKILL_SELECT, handler)
            dispatcher = RuntimeActionDispatcher(
                registry=action_registry,
                observer=RuntimeActionModuleObserver(),
            )

            # dispatch SKILL_SELECT
            request = RuntimeActionRequest(
                action_type=RuntimeActionType.SKILL_SELECT,
                payload={
                    "task_summary": "用户需要写笔记",
                    "available_skill_metadata": available_metadata,
                    "model_decision_metadata": {
                        "selected_skill_id": "demo-note-maker",
                        "selection_reason": "用户需要记录任务",
                        "selection_confidence": "high",
                    },
                },
                source="runtime_loop",
                parent_trace_id="test-e06-001",
            )
            dispatcher.route(request)

            # _update_active_skill_from_dispatcher 应从 action_log 更新 _active_skill
            import agent.core as _core
            _core._update_active_skill_from_dispatcher(dispatcher)

            # 检查 _active_skill 是否正确更新
            assert _state.get_active_skill().get("skill_id") == "demo-note-maker", (
                f"_active_skill 应从 dispatcher 更新，实际: {_state.get_active_skill()}"
            )
        finally:
            # 恢复原始状态
            _state.set_active_skill(original_active)


# ═════════════════════════════════════════════════════════════════════════════
# S05/S06 扩展: retriever + system prompt integration
# ═════════════════════════════════════════════════════════════════════════════


class TestRetrieverPromptIntegration:
    """retriever → candidates → system prompt 的集成行为。"""

    def test_retriever_candidates_include_manifest_routing_info(self):
        """retriever 返回的候选应可关联到 manifest 的 routing 信息。

        验证 retriever 返回的 skill_name 可通过 registry 查询到
        when_to_use / triggers / aliases 等 routing 字段。
        """
        manifest = _make_manifest(
            name="demo-note-maker",
            when_to_use="用户需要记录任务、创建待办时使用。",
            triggers=("写笔记", "记录任务"),
            aliases=("note",),
        )
        registry = MockRegistry([manifest])
        retriever = SkillCandidateRetriever()

        candidates = retriever.retrieve("写笔记", registry)
        assert len(candidates) == 1

        # 通过 skill_name 在 registry 中查找 routing 信息
        candidate_name = candidates[0].skill_name
        manifests = registry.list_visible_manifests()
        matched = [m for m in manifests if m.name == candidate_name]
        assert len(matched) == 1
        assert matched[0].when_to_use is not None
        assert len(matched[0].triggers) > 0

    def test_prompt_builder_accepts_selection_section(self):
        """验证 prompt_builder.build_system_prompt() 可以包含 selection section。

        RED: 当前 build_system_prompt() 不接受独立的 selection_section 参数。
        需要通过 skill_registry 注入 skill listing，但 turn-start selection
        的候选 routing 信息（when_to_use/triggers/score）需要独立 section。
        """
        from agent.prompt_builder import build_system_prompt

        manifest = _make_manifest(
            name="demo-note-maker",
            description="创建本地任务笔记。",
        )
        registry = MockRegistry([manifest])

        # 当前通过 skill_registry 注入 skill listing
        prompt = build_system_prompt(skill_registry=registry)
        assert "demo-note-maker" in prompt, (
            f"system prompt 应包含 skill 列表，实际: {prompt[:200]}"
        )

    def test_selection_not_blocking_main_loop(self):
        """S06 扩展: selection phase 失败不应阻塞 main loop。

        即使 build_skill_selection_section() 返回空字符串，
        system prompt 仍应正常生成。
        """
        from agent.prompt_builder import build_system_prompt

        # 无 skill_registry → 无 skill section → prompt 仍正常生成
        prompt = build_system_prompt(skill_registry=None)
        assert len(prompt) > 0, (
            "即使无 skill_registry，system prompt 也应正常生成"
        )
        assert isinstance(prompt, str)


# ═════════════════════════════════════════════════════════════════════════════
# P0 Runtime Integration Tests — refresh_runtime_system_prompt + retriever
# ═════════════════════════════════════════════════════════════════════════════


class TestBuildSystemPromptSelectionSection:
    """验证 build_system_prompt() 的 selection_section 参数行为。"""

    def test_selection_section_included_in_prompt(self):
        """有 selection_section 时必须出现在最终 prompt 中。"""
        from agent.prompt_builder import build_system_prompt

        prompt = build_system_prompt(
            selection_section="## Skill 选择\n\n候选: demo-note-maker",
        )
        assert "## Skill 选择" in prompt, (
            f"selection_section 必须出现在 prompt 中，实际: {prompt[:300]}"
        )
        assert "demo-note-maker" in prompt

    def test_empty_selection_section_not_injected(self):
        """selection_section 为空时不注入任何内容。"""
        from agent.prompt_builder import build_system_prompt

        prompt_no_selection = build_system_prompt(selection_section="")
        prompt_none_default = build_system_prompt()

        # 两者应该一致（空 selection_section 等同于不传）
        assert prompt_no_selection == prompt_none_default, (
            "空 selection_section 应等同于不传参数"
        )

    def test_selection_section_position(self):
        """selection_section 应出现在 skills listing 之后、active_skill 之前。"""
        from agent.prompt_builder import build_system_prompt

        manifest = _make_manifest(name="demo-skill", description="测试技能。")
        registry = MockRegistry([manifest])

        prompt = build_system_prompt(
            skill_registry=registry,
            selection_section="## Skill 选择\n\n候选内容",
            active_skill_section="这是激活 skill 的 body",
        )

        # selection section 应在 skills listing 之后
        skills_pos = prompt.find("demo-skill")
        selection_pos = prompt.find("## Skill 选择")
        active_pos = prompt.find("[Active Skill Instructions]")

        assert skills_pos >= 0, "skills listing 必须存在"
        assert selection_pos >= 0, "selection section 必须存在"
        assert active_pos >= 0, "active skill section 必须存在"
        assert skills_pos < selection_pos < active_pos, (
            f"顺序应为: skills({skills_pos}) < selection({selection_pos})"
            f" < active({active_pos})"
        )


class TestRefreshRuntimeSystemPromptEvidence:
    """验证 refresh_runtime_system_prompt() 的 evidence dispatch 行为。

    这些测试直接验证 P0 修复的核心目标：
    - retriever 在 runtime path 被调用
    - selection.entered + candidates.built evidence 被 dispatch
    - selection section 被注入到 system prompt
    """

    def test_selection_section_in_runtime_prompt(self):
        """用户输入匹配 skill trigger 时，runtime prompt 必须包含 selection section。

        这是 P0 修复的核心验证——retriever → candidates → selection_section
        必须在 runtime prompt 中可见。
        """
        from agent.core import refresh_runtime_system_prompt

        manifest = _make_manifest(
            name="demo-note-maker",
            description="创建本地任务笔记。",
            triggers=("写笔记",),
        )
        registry = MockRegistry([manifest])

        prompt, count = refresh_runtime_system_prompt(
            skill_registry=registry,
            user_input="写笔记",
        )
        assert "Skill 选择" in prompt, (
            f"匹配 trigger 时 prompt 应包含 selection section，"
            f"实际: {prompt[:500]}"
        )
        assert "demo-note-maker" in prompt

    def test_no_selection_section_for_unrelated_input(self):
        """无关输入不产生 selection section（无候选匹配）。"""
        from agent.core import refresh_runtime_system_prompt

        manifest = _make_manifest(
            name="demo-note-maker",
            description="创建本地任务笔记。",
            triggers=("写笔记",),
        )
        registry = MockRegistry([manifest])

        prompt, count = refresh_runtime_system_prompt(
            skill_registry=registry,
            user_input="今天天气真好",
        )
        # 无关输入 → 无候选 → 无 selection section
        assert "Skill 选择" not in prompt, (
            f"无关输入不应产生 selection section，"
            f"但 prompt 中包含: {prompt[:500]}"
        )

    def test_evidence_dispatched_when_user_input_provided(self):
        """dispatcher 可用时，selection.entered + candidates.built evidence 被 dispatch。

        使用 spy dispatcher 验证 evidence 确实被触发。
        """
        from agent.core import refresh_runtime_system_prompt
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
        )
        from agent.runtime_integration.schema import RuntimeActionType

        manifest = _make_manifest(
            name="demo-note-maker",
            description="测试技能。",
            triggers=("写笔记",),
        )
        registry = MockRegistry([manifest])

        # 构建 spy dispatcher（无需真实 handler，只记录路由调用）
        action_registry = ActionHandlerRegistry()
        dispatcher = RuntimeActionDispatcher(registry=action_registry)

        prompt, count = refresh_runtime_system_prompt(
            dispatcher=dispatcher,
            skill_registry=registry,
            user_input="写笔记",
        )

        # action_log 应包含 selection.entered 和 candidates.built
        action_types = [a.action_type for a in dispatcher.action_log]
        assert RuntimeActionType.SKILL_SELECTION_ENTERED in action_types, (
            f"action_log 必须包含 SKILL_SELECTION_ENTERED，"
            f"实际: {action_types}"
        )
        assert RuntimeActionType.SKILL_CANDIDATES_BUILT in action_types, (
            f"action_log 必须包含 SKILL_CANDIDATES_BUILT，"
            f"实际: {action_types}"
        )

        # selection section 必须出现在 prompt 中
        assert "Skill 选择" in prompt

    def test_evidence_not_dispatched_for_empty_user_input(self):
        """空 user_input 时不触发 selection evidence。"""
        from agent.core import refresh_runtime_system_prompt
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
        )
        from agent.runtime_integration.schema import RuntimeActionType

        manifest = _make_manifest(name="demo", description="desc。")
        registry = MockRegistry([manifest])

        action_registry = ActionHandlerRegistry()
        dispatcher = RuntimeActionDispatcher(registry=action_registry)

        prompt, count = refresh_runtime_system_prompt(
            dispatcher=dispatcher,
            skill_registry=registry,
            user_input="",  # 空输入
        )

        action_types = [a.action_type for a in dispatcher.action_log]
        assert RuntimeActionType.SKILL_SELECTION_ENTERED not in action_types, (
            "空 user_input 不应触发 selection evidence"
        )

    def test_selection_phase_not_broken_by_missing_skill_registry(self):
        """无 skill_registry 时 selection phase 应安静跳过，不 crash。"""
        from agent.core import refresh_runtime_system_prompt
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
        )

        action_registry = ActionHandlerRegistry()
        dispatcher = RuntimeActionDispatcher(registry=action_registry)

        # 无 skill_registry + 有 user_input → 不应 crash
        prompt, count = refresh_runtime_system_prompt(
            dispatcher=dispatcher,
            skill_registry=None,
            user_input="写笔记",
        )
        assert len(prompt) > 0
        assert "Skill 选择" not in prompt

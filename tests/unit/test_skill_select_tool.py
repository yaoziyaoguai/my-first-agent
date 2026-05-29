"""REAL-EVIDENCE-002 RED tests: SKILL_SELECT model-owned tool 单元测试。

验证 _ensure_skill_select_registered() 和 _skill_select_tool_func() 的
正确行为——注册、可见性、激活、unknown/malformed fallback、幂等性。
"""

from __future__ import annotations

# ═════════════════════════════════════════════════════════════════════════════
# R1-R2: 注册和可见性
# ═════════════════════════════════════════════════════════════════════════════


class TestSkillSelectRegistration:
    """SKILL_SELECT tool registration and visibility."""

    def test_r1_skill_select_in_tool_registry(self):
        """R1: SKILL_SELECT 应在 TOOL_REGISTRY 中注册。"""
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_registry import TOOL_REGISTRY

        _ensure_skill_select_registered()

        assert "SKILL_SELECT" in TOOL_REGISTRY
        entry = TOOL_REGISTRY["SKILL_SELECT"]
        assert entry["name"] == "SKILL_SELECT"
        assert callable(entry["func"])
        assert entry["confirmation"] == "never"
        assert entry["capability"] == "skill_lifecycle"
        assert entry["risk_level"] == "low"
        assert "skill_id" in entry["parameters"]

    def test_r2_skill_select_in_model_visible_tools(self):
        """R2: SKILL_SELECT 应出现在 get_model_visible_tools() 返回列表中。"""
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_registry import get_model_visible_tools

        _ensure_skill_select_registered()
        visible = get_model_visible_tools()

        names = [t["name"] for t in visible]
        assert "SKILL_SELECT" in names, (
            f"SKILL_SELECT 应在 model-visible tools 中，实际: {names}"
        )

    def test_r2b_registration_idempotent(self):
        """R2b: 多次调用 _ensure_skill_select_registered() 应是幂等的。"""
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_registry import TOOL_REGISTRY

        _ensure_skill_select_registered()
        first_func = TOOL_REGISTRY["SKILL_SELECT"]["func"]
        _ensure_skill_select_registered()
        second_func = TOOL_REGISTRY["SKILL_SELECT"]["func"]

        assert first_func is second_func, "幂等注册不应替换 func"


# ═════════════════════════════════════════════════════════════════════════════
# R3-R7: tool func 行为
# ═════════════════════════════════════════════════════════════════════════════


class TestSkillSelectToolFunc:
    """_skill_select_tool_func() 的核心行为。"""

    def test_r3_valid_skill_id_activates(self):
        """R3: 有效 skill_id → 激活成功，返回确认信息。"""
        from agent.skill_system.skill_tool import _skill_select_tool_func

        result = _skill_select_tool_func("demo-note-maker")

        assert "已激活" in result
        assert "demo-note-maker" in result
        assert "[Active Skill Instructions]" in result

    def test_r4_unknown_skill_returns_error(self):
        """R4: 未知 skill_id → 返回错误信息，不 crash。"""
        from agent.skill_system.skill_tool import _skill_select_tool_func

        result = _skill_select_tool_func("non-existent-skill-xyz")

        assert "不可用" in result or "不" in result
        # 不应包含激活确认
        assert "已激活" not in result

    def test_r5_empty_skill_id_fallback(self):
        """R5: skill_id="" → 返回错误信息。"""
        from agent.skill_system.skill_tool import _skill_select_tool_func

        result = _skill_select_tool_func("")

        assert "不可用" in result or "不" in result

    def test_r6_active_skill_set_after_activation(self):
        """R6: 激活后 _active_skill 应正确填充。"""
        from agent.skill_system.skill_tool import _skill_select_tool_func

        _skill_select_tool_func("demo-note-maker")

        import agent.core as _core
        active = _core._active_skill
        assert active["skill_id"] == "demo-note-maker"
        assert len(active["body"]) > 0
        assert "demo.echo_task_summary" in active["allowed_tools"]

    def test_r7_skill_selected_by_model_flag(self):
        """R7: _skill_selected_by_model 应在 tool func 调用后为 True。"""
        import agent.core as _core
        from agent.skill_system.skill_tool import _skill_select_tool_func

        # Reset flag
        _core._skill_selected_by_model = False

        _skill_select_tool_func("demo-note-maker")

        assert _core._skill_selected_by_model is True, (
            "model-owned selection 后 flag 应为 True"
        )

    def test_r8_active_skill_includes_allowed_tools(self):
        """R8: _active_skill 的 allowed_tools 来自 descriptor。"""
        from agent.skill_system.skill_tool import _skill_select_tool_func

        _skill_select_tool_func("demo-note-maker")

        import agent.core as _core
        allowed = _core._active_skill.get("allowed_tools")
        assert isinstance(allowed, frozenset)
        assert "demo.echo_task_summary" in allowed
        assert "demo.write_demo_note" in allowed

    def test_r9_unknown_skill_does_not_set_flag(self):
        """R9: 未知 skill 调用不应设置 _skill_selected_by_model。"""
        import agent.core as _core
        from agent.skill_system.skill_tool import _skill_select_tool_func

        _core._skill_selected_by_model = False

        _skill_select_tool_func("non-existent-skill-xyz")

        assert _core._skill_selected_by_model is False, (
            "未知 skill 不应设置 flag"
        )

    def test_r10_unknown_skill_does_not_overwrite_active_skill(self):
        """R10: 未知 skill 调用不应覆盖 _active_skill。"""
        import agent.core as _core
        from agent.skill_system.skill_tool import _skill_select_tool_func

        # 先激活一个有效的 skill
        _skill_select_tool_func("demo-note-maker")
        original = _core._active_skill.copy()

        # 再用无效 skill_id 调用
        _skill_select_tool_func("non-existent-skill-xyz")

        # _active_skill 不应被覆盖
        assert _core._active_skill == original, (
            "无效 skill_id 不应覆盖 _active_skill"
        )

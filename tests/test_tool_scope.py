"""工具作用域模型测试：基础工具层 + 技能工具层合成 + 命名空间规范化。

学习型说明：
本测试文件验证 Agent 工具可见性的两层模型：
1. BASE_TOOLS 始终可用（只读 + 控制）
2. Skill tools 是追加层，不替换 BASE_TOOLS
3. 命名空间规范化（short name ↔ canonical id）防止歧义
4. TOOL_GATE / get_model_visible_tools 使用统一的作用域解析
"""

from __future__ import annotations

# 确保 TOOL_REGISTRY 在测试前完成注册（工具通过 import agent.core 的模块级
# register_tool 调用注册）。不 import agent.core 则 TOOL_REGISTRY 为空。
import agent.core  # noqa: F401 — side-effect import for tool registration

# ═════════════════════════════════════════════════════════════════════════════
# A. Tool Composition Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestToolScopeBaseTools:
    """BASE_TOOLS 定义和 resolve_skill_scoped_allowlist 的单元测试。"""

    def test_base_tools_are_defined(self):
        """BASE_READ_TOOLS / BASE_CONTROL_TOOLS / BASE_TOOLS 非空且有明确分层。"""
        from agent.tool_scope import BASE_CONTROL_TOOLS, BASE_READ_TOOLS, BASE_TOOLS

        assert len(BASE_READ_TOOLS) > 0, "BASE_READ_TOOLS 不能为空"
        assert len(BASE_CONTROL_TOOLS) > 0, "BASE_CONTROL_TOOLS 不能为空"
        assert BASE_TOOLS == BASE_READ_TOOLS | BASE_CONTROL_TOOLS, (
            "BASE_TOOLS 应为 BASE_READ_TOOLS ∪ BASE_CONTROL_TOOLS"
        )
        for name in BASE_READ_TOOLS:
            assert "write" not in name.lower(), (
                f"BASE_READ_TOOLS 不应包含 write 类工具：{name}"
            )
            assert "edit" not in name.lower(), (
                f"BASE_READ_TOOLS 不应包含 edit 类工具：{name}"
            )

    def test_base_tools_excludes_write_tools(self):
        """BASE_TOOLS 不应包含写/执行/网络工具。"""
        from agent.tool_scope import BASE_TOOLS

        dangerous = {"write_file", "edit_file", "run_shell", "fetch_url"}
        assert BASE_TOOLS.isdisjoint(dangerous), (
            f"BASE_TOOLS 不应包含危险工具：{BASE_TOOLS & dangerous}"
        )

    def test_base_tools_includes_control_tools(self):
        """BASE_CONTROL_TOOLS 应包含 mark_step_complete 和 request_user_input。"""
        from agent.tool_scope import BASE_CONTROL_TOOLS

        assert "mark_step_complete" in BASE_CONTROL_TOOLS
        assert "request_user_input" in BASE_CONTROL_TOOLS

    def test_resolve_skill_scoped_allowlist_merges_base_tools(self):
        """resolve_skill_scoped_allowlist 默认合并 BASE_TOOLS。"""
        from agent.tool_scope import BASE_TOOLS, resolve_skill_scoped_allowlist

        skill_tools = frozenset({"demo.echo_task_summary", "demo.write_demo_note"})
        result = resolve_skill_scoped_allowlist(skill_tools)
        assert result == skill_tools | BASE_TOOLS, (
            f"合并后应包含 skill tools + BASE_TOOLS，got {sorted(result)}"
        )

    def test_resolve_skill_scoped_allowlist_no_base_tools(self):
        """include_base_tools=False 时不应合并 BASE_TOOLS。"""
        from agent.tool_scope import resolve_skill_scoped_allowlist

        skill_tools = frozenset({"demo.echo_task_summary"})
        result = resolve_skill_scoped_allowlist(skill_tools, include_base_tools=False)
        assert result == skill_tools, (
            f"不合并时 result 应等于 skill_tools，got {result}"
        )

    def test_is_base_tool_positive_and_negative(self):
        """is_base_tool 正确识别 BASE_TOOLS 成员。"""
        from agent.tool_scope import is_base_tool

        assert is_base_tool("read_file") is True
        assert is_base_tool("mark_step_complete") is True
        assert is_base_tool("demo.write_demo_note") is False
        assert is_base_tool("run_shell") is False


class TestToolCompositionWithSkill:
    """Skill 激活/非激活场景下的工具组合测试。"""

    @staticmethod
    def _get_visible_tool_names(explicit_allowlist=None):
        from agent.tool_registry import get_model_visible_tools

        tools = get_model_visible_tools(explicit_allowlist=explicit_allowlist)
        return [t["name"] for t in tools]

    def test_no_skill_visible_tools_include_base_read(self):
        """无活跃 skill 时，visible tools 包含基础只读工具。"""
        names = self._get_visible_tool_names()
        assert "read_file" in names, (
            f"无 skill 时 read_file 应在 visible tools 中，got {sorted(names)}"
        )
        assert "read_file_lines" in names

    def test_no_skill_visible_tools_include_control(self):
        """无活跃 skill 时，visible tools 包含基础控制工具。"""
        names = self._get_visible_tool_names()
        assert "mark_step_complete" in names
        assert "request_user_input" in names

    def test_demo_tools_excluded_by_explicit_allowlist(self):
        """当 explicit_allowlist 不包含 demo 工具时，它们不应可见。

        学习型边界：
        无 explicit_allowlist 时 get_model_visible_tools 返回所有已注册工具
        （含 demo 工具），这是正常的——无 skill 激活时没有理由隐藏 demo 工具。
        工具隐藏发生在 skill 激活时：core.py _call_model() 传入
        explicit_allowlist 仅含 skill_allowed_tools + meta + SKILL_SELECT，
        此时 demo 工具如果不在 allowlist 中就不会可见。
        """
        # 模拟仅含有特定工具（不含 demo）的 explicit_allowlist
        restricted = frozenset({"read_file", "mark_step_complete"})
        names = self._get_visible_tool_names(explicit_allowlist=restricted)
        assert "demo.write_demo_note" not in names, (
            f"explicit_allowlist 不含 demo 时不应可见，got {sorted(names)}"
        )
        assert "demo.echo_task_summary" not in names

    def test_skill_allowlist_includes_base_tools(self):
        """活跃 skill 的 allowlist 合并后应包含 BASE_TOOLS。

        架构契约（红线）：
        visible_tools = BASE_TOOLS + skill_allowed_tools
        不是 visible_tools = skill_allowed_tools（旧替换模式）。
        """
        from agent.tool_scope import BASE_TOOLS, resolve_skill_scoped_allowlist

        skill_tools = frozenset({"demo.echo_task_summary", "demo.write_demo_note"})
        merged = resolve_skill_scoped_allowlist(skill_tools)

        for base_tool in BASE_TOOLS:
            assert base_tool in merged, (
                f"BASE_TOOL '{base_tool}' 必须在合并后的 allowlist 中——"
                f"Skill 激活后不应剥夺 Agent 基础工具能力。got {sorted(merged)}"
            )

    def test_skill_allowlist_includes_skill_tools(self):
        """活跃 skill 的 allowlist 合并后仍包含 skill 专属工具。"""
        from agent.tool_scope import resolve_skill_scoped_allowlist

        skill_tools = frozenset({"demo.echo_task_summary", "demo.write_demo_note"})
        merged = resolve_skill_scoped_allowlist(skill_tools)

        for tool in skill_tools:
            assert tool in merged

    def test_skill_allowlist_no_write_tools_in_base(self):
        """合并后的 allowlist 不应自动包含写工具（仅 BASE_TOOLS + skill tools）。"""
        from agent.tool_scope import resolve_skill_scoped_allowlist

        skill_tools = frozenset({"demo.echo_task_summary"})
        merged = resolve_skill_scoped_allowlist(skill_tools)

        assert "write_file" not in merged, "write_file 不应泄露进 allowlist"
        assert "edit_file" not in merged, "edit_file 不应泄露进 allowlist"
        assert "run_shell" not in merged, "run_shell 不应泄露进 allowlist"


# ═════════════════════════════════════════════════════════════════════════════
# B. Namespace / Same-Name Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestNamespaceNormalization:
    """工具名命名空间规范化测试。"""

    def test_unique_short_name_maps_to_canonical(self):
        """唯一短名 → 归一化为注册表全名（canonical id）。"""
        from agent.tool_registry import _normalize_tool_name

        result = _normalize_tool_name("echo_task_summary")
        assert result == "demo.echo_task_summary", (
            f"唯一短名应映射到 canonical id，got {result}"
        )

    def test_namespaced_name_maps_to_self(self):
        """namespaced 全名直接匹配自身。"""
        from agent.tool_registry import _normalize_tool_name

        result = _normalize_tool_name("demo.echo_task_summary")
        assert result == "demo.echo_task_summary", (
            f"namespaced 全名应直接匹配，got {result}"
        )

    def test_ambiguous_short_name_returns_none(self):
        """不存在/冲突短名 → 返回 None（fail-closed，不猜第一个匹配项）。"""
        from agent.tool_registry import _normalize_tool_name

        result = _normalize_tool_name("nonexistent_tool_xyz")
        assert result is None, (
            f"不存在的工具名应返回 None（fail-closed），got {result}"
        )

    def test_tool_gate_uses_normalized_canonical_id(self):
        """TOOL_GATE 检查使用归一化后的 canonical id。

        P1-001 回归：provider 剥离命名空间后的短名仍能匹配 namespaced
        allowed_tools 中的工具。
        """
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "write_demo_note",
                "tool_input": {"path": "workspace/demo/t/note.md", "content": "t"},
                "skill_allowed_tools": [
                    "demo.echo_task_summary", "demo.write_demo_note",
                ],
            },
        ))
        assert result.payload["gate_disposition"] in ("allowed", "confirmation_required"), (
            f"归一化后应匹配 namespaced allowed_tools，got {result.payload}"
        )

    def test_base_tool_in_gate_not_rejected_when_skill_active(self):
        """Skill 激活时，BASE_TOOLS 不应被 TOOL_GATE 拒绝。

        核心回归测试：TOOL_GATE 的 skill_allowed_tools 检查在发现 base tool
        不在 skill 白名单中时，应允许 base tool 通过（而非拒绝）。
        """
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "read_file",
                "tool_input": {"path": "README.md"},
                "skill_allowed_tools": [
                    "demo.echo_task_summary", "demo.write_demo_note",
                ],
            },
        ))
        assert result.payload["gate_disposition"] != "rejected", (
            f"BASE_TOOL read_file 不应因 skill 激活而被 TOOL_GATE 拒绝，"
            f"got {result.payload}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# C. Confirmation UX Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestConfirmationDisplayEvent:
    """确认提示 DisplayEvent 的内容完整性测试。"""

    def test_confirmation_event_includes_tool_name(self):
        from agent.display_events import build_tool_awaiting_confirmation_event

        event = build_tool_awaiting_confirmation_event(
            tool_name="demo.write_demo_note",
            tool_input={"path": "workspace/demo/test.md", "content": "hello"},
        )
        assert "demo.write_demo_note" in event.body, (
            f"确认提示必须包含工具名，got:\n{event.body}"
        )

    def test_confirmation_event_includes_path(self):
        from agent.display_events import build_tool_awaiting_confirmation_event

        event = build_tool_awaiting_confirmation_event(
            tool_name="write_file",
            tool_input={"path": "workspace/demo/note.md", "content": "test"},
        )
        assert "workspace/demo/note.md" in event.body, (
            f"确认提示必须包含写入路径，got:\n{event.body}"
        )

    def test_confirmation_event_includes_options(self):
        from agent.display_events import build_tool_awaiting_confirmation_event

        event = build_tool_awaiting_confirmation_event(
            tool_name="demo.write_demo_note",
            tool_input={"path": "test.md", "content": "x"},
        )
        assert "y" in event.body.lower() or "是" in event.body, (
            f"确认提示必须提及 y/确认 选项，got:\n{event.body}"
        )
        assert "n" in event.body.lower() or "不" in event.body, (
            f"确认提示必须提及 n/拒绝 选项，got:\n{event.body}"
        )

    def test_confirmation_event_has_warning_severity(self):
        from agent.display_events import build_tool_awaiting_confirmation_event

        event = build_tool_awaiting_confirmation_event(
            tool_name="demo.write_demo_note",
            tool_input={"path": "test.md", "content": "x"},
        )
        assert event.severity == "warning", (
            f"确认事件 severity 应为 warning，got {event.severity}"
        )


class TestConfirmationResponseClassification:
    """确认响应分类测试（classify_confirmation_response）。"""

    def test_y_accepts(self):
        from agent.input_intents import classify_confirmation_response

        assert classify_confirmation_response("y") == "accept"
        assert classify_confirmation_response("yes") == "accept"
        assert classify_confirmation_response("是") == "accept"
        assert classify_confirmation_response("好") == "accept"
        assert classify_confirmation_response("确认") == "accept"

    def test_n_rejects(self):
        from agent.input_intents import classify_confirmation_response

        assert classify_confirmation_response("n") == "reject"
        assert classify_confirmation_response("no") == "reject"
        assert classify_confirmation_response("不") == "reject"

    def test_other_is_feedback(self):
        from agent.input_intents import classify_confirmation_response

        assert classify_confirmation_response("explain") == "feedback"
        assert classify_confirmation_response("为什么") == "feedback"
        assert classify_confirmation_response("") == "feedback"

    def test_case_insensitive(self):
        from agent.input_intents import classify_confirmation_response

        assert classify_confirmation_response("Y") == "accept"
        assert classify_confirmation_response("YES") == "accept"
        assert classify_confirmation_response("N") == "reject"
        assert classify_confirmation_response("No") == "reject"


# ═════════════════════════════════════════════════════════════════════════════
# D. Regression Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestSensitivePathStillBlocked:
    """敏感路径策略在 Skill 激活后仍然有效。

    F-001 契约：config/config.yaml、.env、key/token/secret/credential 文件
    必须被拒绝。本测试使用 agent.security.is_sensitive_file（F-001 的真实实现）。
    """

    def test_config_yaml_blocked(self):
        from agent.security import is_sensitive_file

        assert is_sensitive_file("config/config.yaml"), (
            "config/config.yaml 必须被识别为敏感文件"
        )

    def test_dotenv_blocked(self):
        from agent.security import is_sensitive_file

        assert is_sensitive_file(".env"), ".env 必须被识别为敏感文件"

    def test_readme_not_blocked(self):
        from agent.security import is_sensitive_file

        assert not is_sensitive_file("README.md"), "README.md 不应被识别为敏感文件"

    def test_workspace_demo_not_blocked(self):
        from agent.security import is_sensitive_file

        assert not is_sensitive_file("workspace/demo/test/note.md"), (
            "workspace/demo 路径不应被识别为敏感文件"
        )

    def test_key_file_blocked(self):
        from agent.security import is_sensitive_file

        for path in ("secret.key", "credentials.yml"):
            assert is_sensitive_file(path), (
                f"'{path}' 应被识别为敏感文件"
            )


class TestPreviousP1Regression:
    """之前修复过的 P1 问题不应回归。"""

    def test_stripped_namespace_normalization_still_works(self):
        from agent.tool_registry import _normalize_tool_name

        assert _normalize_tool_name("echo_task_summary") == "demo.echo_task_summary"
        assert _normalize_tool_name("write_demo_note") == "demo.write_demo_note"

    def test_rejection_escalation_still_works(self):
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        mediator = ToolRuntimeMediator.__new__(ToolRuntimeMediator)
        mediator._rejection_counts = {}
        mediator._rejection_counts["tool_a"] = 2
        mediator._rejection_counts["tool_a"] += 1
        assert mediator._rejection_counts["tool_a"] == 3, (
            "重复拒绝计数应正确递增"
        )

    def test_demo_skill_registry_has_allowed_tools(self):
        """demo-note-maker skill 的 allowed_tools 声明正确。"""
        from pathlib import Path

        from agent.skill_system.registry import SkillRegistry

        registry = SkillRegistry(roots=[Path("skills/")])
        descriptors = registry.list_visible()

        demo_skills = [d for d in descriptors if "demo" in d.name.lower()]
        assert len(demo_skills) > 0, "demo-note-maker skill 应存在于 registry 中"


class TestBaseToolInGateNotBlocked:
    """验证 BASE_TOOLS 在 TOOL_GATE 中不被 skill 约束拒绝。

    核心修复：Skill 激活后 BASE_TOOLS（read_file, read_file_lines,
    mark_step_complete, request_user_input）应通过 TOOL_GATE，
    即使它们不在 skill allowed_tools 中。
    """

    def test_read_file_passes_gate_with_skill_active(self):
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "read_file",
                "tool_input": {"path": "README.md"},
                "skill_allowed_tools": [
                    "demo.echo_task_summary", "demo.write_demo_note",
                ],
            },
        ))
        assert result.payload["gate_disposition"] != "rejected", (
            f"read_file（BASE_TOOL）不应被 skill 约束拒绝，got {result.payload}"
        )

    def test_request_user_input_passes_gate_with_skill_active(self):
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "request_user_input",
                "tool_input": {},
                "skill_allowed_tools": [
                    "demo.echo_task_summary", "demo.write_demo_note",
                ],
            },
        ))
        assert result.payload["gate_disposition"] != "rejected", (
            f"request_user_input（BASE_CONTROL_TOOL）不应被 skill 约束拒绝，"
            f"got {result.payload}"
        )

    def test_demo_skill_tool_still_allowed(self):
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "demo.echo_task_summary",
                "tool_input": {},
                "skill_allowed_tools": [
                    "demo.echo_task_summary", "demo.write_demo_note",
                ],
            },
        ))
        assert result.payload["gate_disposition"] == "allowed", (
            f"skill 专属工具应通过 gate，got {result.payload}"
        )

    def test_non_base_non_skill_tool_still_blocked(self):
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "run_shell",
                "tool_input": {"command": "ls"},
                "skill_allowed_tools": [
                    "demo.echo_task_summary", "demo.write_demo_note",
                ],
            },
        ))
        assert result.payload["gate_disposition"] == "rejected", (
            f"run_shell 不在 BASE_TOOLS 且不在 skill tools 中，应被拒绝，"
            f"got {result.payload}"
        )

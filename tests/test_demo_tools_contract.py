"""Demo 工具注册契约测试。

验证 demo.echo_task_summary 和 demo.write_demo_note 正确注册在 TOOL_REGISTRY 中，
metadata 字段符合 ToolRegistryEntry 契约，且工具函数可正常调用。
"""

from __future__ import annotations

# ========== 注册验证 ==========


def test_demo_tools_are_registered():
    """验证两个 demo 工具已注册在 TOOL_REGISTRY 中。"""
    import agent.tools  # noqa: F401 - 触发 @register_tool 装饰器
    from agent.tool_registry import TOOL_REGISTRY

    assert "demo.echo_task_summary" in TOOL_REGISTRY, (
        "demo.echo_task_summary 应注册在 TOOL_REGISTRY 中"
    )
    assert "demo.write_demo_note" in TOOL_REGISTRY, (
        "demo.write_demo_note 应注册在 TOOL_REGISTRY 中"
    )


def test_demo_echo_task_summary_metadata():
    """验证 demo.echo_task_summary 的 metadata 字段符合契约。"""
    import agent.tools  # noqa: F401
    from agent.tool_registry import TOOL_REGISTRY

    entry = TOOL_REGISTRY["demo.echo_task_summary"]
    assert entry["name"] == "demo.echo_task_summary"
    assert isinstance(entry["description"], str) and len(entry["description"]) > 0
    assert entry["parameters"] == {}
    assert entry["confirmation"] == "never"
    assert entry["meta_tool"] is False
    assert entry["capability"] == "local_action"
    assert entry["risk_level"] == "low"
    assert entry["output_policy"] == "bounded_text"


def test_demo_write_demo_note_metadata():
    """验证 demo.write_demo_note 的 metadata 字段符合契约。"""
    import agent.tools  # noqa: F401
    from agent.tool_registry import TOOL_REGISTRY

    entry = TOOL_REGISTRY["demo.write_demo_note"]
    assert entry["name"] == "demo.write_demo_note"
    assert isinstance(entry["description"], str) and len(entry["description"]) > 0
    assert isinstance(entry["parameters"], dict)
    assert entry["confirmation"] == "always"
    assert entry["meta_tool"] is False
    assert entry["capability"] == "file_write"
    assert entry["risk_level"] == "medium"
    assert entry["output_policy"] == "bounded_text"


# ========== execute_tool 调用验证 ==========


def test_demo_echo_task_summary_execute():
    """验证 demo.echo_task_summary 可通过 execute_tool() 正常调用。"""
    import agent.tools  # noqa: F401
    from agent.tool_registry import execute_tool

    result = execute_tool("demo.echo_task_summary", {})
    assert isinstance(result, str)
    assert len(result) > 0


def test_demo_write_demo_note_execute_defaults(tmp_path):
    """验证 demo.write_demo_note 用默认参数可通过 execute_tool() 正常调用。

    写入 tmp_path 下的安全路径，不触碰真实文件系统。
    """
    import agent.tools  # noqa: F401
    from agent.tool_registry import execute_tool

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)
    note_path = output_dir / "note.md"

    result = execute_tool("demo.write_demo_note", {
        "path": str(note_path),
        "content": "test note content",
    })
    assert isinstance(result, str)
    assert "ok" in result.lower() or "wrote" in result.lower()
    assert note_path.exists()
    assert note_path.read_text() == "test note content"


def test_demo_write_demo_note_rejects_escape(tmp_path):
    """验证 demo.write_demo_note 拒绝越界路径。"""
    import agent.tools  # noqa: F401
    from agent.tool_registry import execute_tool

    result = execute_tool("demo.write_demo_note", {
        "path": "/etc/passwd",
        "content": "should not write",
    })
    assert isinstance(result, str)
    assert "rejected" in result.lower() or "blocked" in result.lower() or "denied" in result.lower()


# ========== get_tool_specs 可见性验证 ==========


def test_demo_tools_in_get_tool_specs():
    """验证 demo 工具出现在 get_tool_specs() 中。"""
    import agent.tools  # noqa: F401
    from agent.tool_registry import get_tool_specs

    specs = get_tool_specs()
    names = {s["name"] for s in specs}
    assert "demo.echo_task_summary" in names
    assert "demo.write_demo_note" in names


# ========== demo 工具 model-visible ==========

def test_demo_tools_are_model_visible():
    """验证 demo 工具出现在 model-visible tools 中。

    demo 工具是安全、确定性、fake-only 的本地工具。它们应该对模型可见，
    以便用户在 demo/fake 场景中看到工具列表和工具调用结果。
    """
    import agent.tools  # noqa: F401
    from agent.tool_registry import get_model_visible_tools

    tools = get_model_visible_tools()
    names = {t["name"] for t in tools}
    assert "demo.echo_task_summary" in names, (
        "demo.echo_task_summary 应出现在 model-visible tools 中"
    )
    assert "demo.write_demo_note" in names, (
        "demo.write_demo_note 应出现在 model-visible tools 中"
    )


# ========== UMT-P1-002: skill-aware tool visibility ==========


def test_skill_aware_allowlist_filters_model_visible_tools():
    """活跃 skill 时，模型可见工具应收窄为 skill.allowed_tools + 元工具 + SKILL_SELECT。

    UMT-P1-002 root cause: core.chat() 调用 get_model_visible_tools() 时未考虑活跃 skill
    的 allowed_tools，导致模型看到所有工具但只能使用 skill 允许的工具子集——
    模型尝试调用非允许工具时被 TOOL_GATE 拒绝（"overblocking"）。

    修复方案：活跃 skill 时通过 explicit_allowlist 将模型可见工具收窄为
    skill.allowed_tools + 元工具 + SKILL_SELECT。
    """
    import agent.tools  # noqa: F401
    from agent.skill_system.lifecycle import get_default_lifecycle

    # 注册 SKILL_SELECT（幂等），否则 explicit_allowlist 中包含的 SKILL_SELECT
    # 会被 get_model_visible_tools 的 TOOL_REGISTRY items 循环滤掉（不在注册表中）。
    from agent.skill_system.skill_tool import _ensure_skill_select_registered
    from agent.tool_registry import TOOL_REGISTRY, get_model_visible_tools
    _ensure_skill_select_registered()

    lifecycle = get_default_lifecycle()

    # 激活 demo-note-maker skill，其 allowed_tools = [demo.echo_task_summary, demo.write_demo_note]
    lifecycle.activate(
        skill_id="demo-note-maker",
        body="Test skill activation",
        allowed_tools=("demo.echo_task_summary", "demo.write_demo_note"),
    )

    try:
        allowed = lifecycle.get_allowed_tools()
        assert allowed == frozenset({"demo.echo_task_summary", "demo.write_demo_note"}), (
            f"skill allowed_tools 应包含两个 demo 工具，实际: {allowed}"
        )

        # 构建 explicit_allowlist（与 core.py 中的逻辑一致）
        meta_tool_names = frozenset({
            name for name, info in TOOL_REGISTRY.items()
            if info.get("meta_tool")
        })
        explicit_allowlist = (
            frozenset(allowed) | meta_tool_names | {"SKILL_SELECT"}
        )

        tools = get_model_visible_tools(explicit_allowlist=explicit_allowlist)
        names = {t["name"] for t in tools}

        # 技能工具必须在
        assert "demo.echo_task_summary" in names
        assert "demo.write_demo_note" in names

        # 元工具必须在
        assert "mark_step_complete" in names
        assert "request_user_input" in names

        # SKILL_SELECT 必须在（用于切换/退出技能）
        assert "SKILL_SELECT" in names

        # 非技能工具不应在
        assert "read_file" not in names, (
            "read_file 不在 skill allowed_tools 中，不应出现在模型可见工具中"
        )
        assert "grep" not in names, (
            "grep 不在 skill allowed_tools 中，不应出现在模型可见工具中"
        )
    finally:
        lifecycle.deactivate()


def test_skill_aware_allowlist_no_skill_all_tools_visible():
    """无活跃 skill 时，所有非内部工具对模型可见（向后兼容）。"""
    import agent.tools  # noqa: F401
    from agent.tool_registry import get_model_visible_tools

    tools = get_model_visible_tools()
    names = {t["name"] for t in tools}

    # 所有 demo 工具可见
    assert "demo.echo_task_summary" in names
    assert "demo.write_demo_note" in names
    # 文件工具可见
    assert "read_file" in names


def test_skill_aware_allowlist_empty_skill_no_restriction():
    """Skill activated but with empty allowed_tools → no filter applied (None allowlist).

    中文学习边界：空 allowed_tools 表示「无约束」，不是「禁止所有工具」。
    core.py 中 _active_tools 为空时 _skill_visible_allowlist 保持 None，
    get_model_visible_tools() 不受 explicit_allowlist 影响，走正常路径。
    """
    import agent.tools  # noqa: F401
    from agent.skill_system.lifecycle import get_default_lifecycle
    from agent.tool_registry import get_model_visible_tools

    lifecycle = get_default_lifecycle()
    lifecycle.activate(
        skill_id="test-empty-skill",
        body="Test",
        allowed_tools=(),  # 空
    )

    try:
        allowed = lifecycle.get_allowed_tools()
        assert allowed == frozenset(), "空 allowed_tools 应返回空 frozenset"

        # 空 allowed_tools 时，core.py 不设置 explicit_allowlist (保持 None)
        tools = get_model_visible_tools()  # 不传 explicit_allowlist
        names = {t["name"] for t in tools}
        assert "read_file" in names, "无 explicit_allowlist 时所有非内部工具应可见"
    finally:
        lifecycle.deactivate()

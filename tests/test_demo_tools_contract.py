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

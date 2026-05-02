"""Tool registry / visibility characterization tests.

本文件是 Tooling Foundation 第一刀的 tests-only 安全网：先把当前
ToolRegistry / model-visible schema / runtime allowed tools 的现状钉住。
它不新增工具、不删除工具、不改 production，也不试图把理想 ToolSpec 一步到位。

为什么先测 registry：
- registry 决定模型能看到哪些 Action；
- allowed tools 决定 runtime 真的能执行哪些 Action；
- 两者一旦漂移，模型会调用 runtime 不认的工具，或 runtime 暴露模型看不到的能力；
- 未来 MCP 只能作为 external tool source 映射成本地 ToolSpec，不能绕过本地 registry。
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_MODEL_VISIBLE_TOOLS = {
    "edit_file",
    "fetch_url",
    "install_skill",
    "mark_step_complete",
    "read_file",
    "read_file_lines",
    "request_user_input",
    "run_shell",
    "write_file",
}

PREMATURE_SKILL_TOOL_NAMES = {"load_skill", "load_skills", "update_skill"}
LOW_VALUE_NARROW_TOOL_NAMES = {"calculate"}
EXPECTED_META_TOOLS = {"mark_step_complete", "request_user_input"}
EXPECTED_INTERNAL_TOOL_SPECS = {
    "edit_file": {
        "capability": "file_write",
        "risk_level": "high",
        "output_policy": "bounded_text",
        "confirmation": "always",
        "meta_tool": False,
    },
    "fetch_url": {
        "capability": "network_fetch",
        "risk_level": "high",
        "output_policy": "artifact_text",
        "confirmation": "always",
        "meta_tool": False,
    },
    "install_skill": {
        "capability": "skill_lifecycle",
        "risk_level": "high",
        "output_policy": "bounded_text",
        "confirmation": "always",
        "meta_tool": False,
    },
    "mark_step_complete": {
        "capability": "runtime_control",
        "risk_level": "low",
        "output_policy": "none",
        "confirmation": "never",
        "meta_tool": True,
    },
    "read_file": {
        "capability": "file_read",
        "risk_level": "medium",
        "output_policy": "bounded_text",
        "confirmation": "dynamic",
        "meta_tool": False,
    },
    "read_file_lines": {
        "capability": "file_read",
        "risk_level": "medium",
        "output_policy": "bounded_text",
        "confirmation": "dynamic",
        "meta_tool": False,
    },
    "request_user_input": {
        "capability": "runtime_control",
        "risk_level": "low",
        "output_policy": "none",
        "confirmation": "never",
        "meta_tool": True,
    },
    "run_shell": {
        "capability": "command_execution",
        "risk_level": "high",
        "output_policy": "bounded_text",
        "confirmation": "always",
        "meta_tool": False,
    },
    "write_file": {
        "capability": "file_write",
        "risk_level": "high",
        "output_policy": "bounded_text",
        "confirmation": "always",
        "meta_tool": False,
    },
}


def _load_builtin_tools() -> None:
    """触发 agent.tools 的装饰器注册，但不 import core.py。

    registry contract 的关键边界是：工具模块通过装饰器注册，core.py 只消费
    registry 暴露的 schema。测试里显式加载 agent.tools，避免依赖测试顺序。
    """

    importlib.import_module("agent.tools")


def _agent_imports(path: Path) -> set[str]:
    """用 AST 收集 agent.* imports，避免脆弱 grep。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def _assert_spec_contains(spec: dict, expected: dict) -> None:
    """断言内部 ToolSpec 含有预期治理字段，保留额外字段演进空间。"""

    for key, value in expected.items():
        assert spec[key] == value


def test_model_visible_tools_match_runtime_allowed_tools() -> None:
    """模型可见工具清单必须与 runtime allowed tools 同源一致。

    这是 Tooling Foundation 的第一道防火墙：ToolSpec 暂时还没有独立类型，
    但 `get_tool_definitions()` 和 `get_allowed_tools()` 都必须来自同一 registry。
    未来 MCP adapter 也只能先注册成本地工具，再同时进入这两个投影。
    """

    _load_builtin_tools()

    from agent.tool_registry import get_allowed_tools, get_tool_definitions

    allowed_tools = get_allowed_tools()
    visible_tools = {definition["name"] for definition in get_tool_definitions()}

    assert allowed_tools == EXPECTED_MODEL_VISIBLE_TOOLS
    assert visible_tools == EXPECTED_MODEL_VISIBLE_TOOLS
    assert visible_tools == allowed_tools


def test_premature_skill_tools_do_not_pollute_tooling_foundation_registry() -> None:
    """未来 Skill System 的工具入口不能污染当前 Tooling Foundation。

    `load_skill` / `update_skill` 属于未来 Skill lifecycle，而当前阶段只在打牢
    本地基础工具 contract。它们不应出现在 model-visible tools、allowed tools
    或当前 registry 中；未来 Skill System 可以重新设计正式 Skill tools，但不应
    由本阶段的基础工具快照提前固化。
    """

    _load_builtin_tools()

    from agent.tool_registry import TOOL_REGISTRY, get_allowed_tools, get_tool_definitions

    visible_tools = {definition["name"] for definition in get_tool_definitions()}
    allowed_tools = get_allowed_tools()

    assert PREMATURE_SKILL_TOOL_NAMES.isdisjoint(visible_tools)
    assert PREMATURE_SKILL_TOOL_NAMES.isdisjoint(allowed_tools)
    assert PREMATURE_SKILL_TOOL_NAMES.isdisjoint(TOOL_REGISTRY)


def test_low_value_narrow_tools_do_not_pollute_base_tool_registry() -> None:
    """低价值窄工具不能因为历史存在而继续污染基础工具集。

    Tooling Foundation 的目标是少量稳定、高价值、边界清晰的基础工具。
    `calculate` 能力很窄，会增加模型工具选择负担；未来若需要计算，应由
    单独设计的 execution/sandbox seam 承担，而不是在本轮新增替代工具。
    """

    _load_builtin_tools()

    from agent.tool_registry import TOOL_REGISTRY, get_allowed_tools, get_tool_definitions

    visible_tools = {definition["name"] for definition in get_tool_definitions()}
    allowed_tools = get_allowed_tools()

    assert LOW_VALUE_NARROW_TOOL_NAMES.isdisjoint(visible_tools)
    assert LOW_VALUE_NARROW_TOOL_NAMES.isdisjoint(allowed_tools)
    assert LOW_VALUE_NARROW_TOOL_NAMES.isdisjoint(TOOL_REGISTRY)


def test_agent_tools_does_not_auto_import_premature_skill_tool_modules() -> None:
    """基础工具注册入口不能自动加载未来 Skill lifecycle 工具。

    `agent.tools` 是当前模型可见工具的注册入口；如果它 import 了
    `agent.tools.skill` 或 `agent.tools.update_skill`，这些未来 Skill System
    工具就会进入当前 Tooling Foundation 的 schema/allowed tools。此测试保护
    的是阶段边界，不是未来 Skill System 的最终设计。
    """

    imports = _agent_imports(PROJECT_ROOT / "agent" / "tools" / "__init__.py")

    assert "agent.tools.skill" not in imports
    assert "agent.tools.update_skill" not in imports


def test_registered_tools_have_current_schema_shape() -> None:
    """模型可见 schema 仍只暴露 Anthropic 需要的最小字段。

    Tooling Foundation 可以给 registry 增加内部 capability/risk/output metadata，
    但不能把这些内部治理字段泄漏进模型 schema，避免模型把 policy 字段当作
    可调用参数或业务语义。
    """

    _load_builtin_tools()

    from agent.tool_registry import TOOL_REGISTRY, get_tool_definitions

    definitions = {definition["name"]: definition for definition in get_tool_definitions()}

    for name, registry_entry in TOOL_REGISTRY.items():
        definition = definitions[name]
        assert set(definition) == {"name", "description", "input_schema"}
        assert definition["name"] == registry_entry["name"] == name
        assert definition["description"] == registry_entry["description"]

        schema = definition["input_schema"]
        assert schema["type"] == "object"
        assert schema["properties"] == registry_entry["parameters"]
        assert schema["required"] == list(registry_entry["parameters"].keys())

        assert "capability" not in definition
        assert "risk_level" not in definition
        assert "output_policy" not in definition


def test_internal_tool_specs_expose_capability_risk_and_output_policy() -> None:
    """内部 ToolSpec 投影提供治理 metadata，但不执行工具。

    这是 MCP 前的最小 seam：未来 external/MCP tools 必须映射成本地 capability、
    risk_level、output_policy 和 confirmation policy，才能复用本地安全与审计。
    这些字段属于 registry/query 边界，不应该由 core.py 或 display layer 推断。
    """

    _load_builtin_tools()

    from agent.tool_registry import get_tool_specs

    specs = {spec["name"]: spec for spec in get_tool_specs()}

    assert set(specs) == EXPECTED_MODEL_VISIBLE_TOOLS
    for name, expected in EXPECTED_INTERNAL_TOOL_SPECS.items():
        _assert_spec_contains(specs[name], expected)


def test_registry_metadata_values_are_from_small_controlled_vocabularies() -> None:
    """工具 metadata 必须来自小而明确的词表。

    这避免每个工具随意发明 risk/output/capability 字符串，导致 future MCP
    adapter、permission policy 和 audit log 无法稳定映射。
    """

    _load_builtin_tools()

    from agent.tool_registry import (
        TOOL_CAPABILITIES,
        TOOL_OUTPUT_POLICIES,
        TOOL_REGISTRY,
        TOOL_RISK_LEVELS,
    )

    for entry in TOOL_REGISTRY.values():
        assert entry["capability"] in TOOL_CAPABILITIES
        assert entry["risk_level"] in TOOL_RISK_LEVELS
        assert entry["output_policy"] in TOOL_OUTPUT_POLICIES


def test_register_tool_rejects_unknown_metadata_values() -> None:
    """registry 在注册边界拒绝未知 metadata，而不是让 policy 字符串扩散。

    这证明 capability/risk/output policy 不只是注释字段：注册入口会消费并
    验证它们。未来 MCP adapter 也必须先映射到这些受控词表，不能把外部
    server 的任意标签直接塞进 runtime。
    """

    from agent.tool_registry import register_tool

    try:
        register_tool(
            name="bad_metadata_contract_tool",
            description="bad metadata should fail before decorator use",
            parameters={},
            capability="arbitrary_external_power",
        )
    except ValueError as exc:
        assert "未知工具能力类型" in str(exc)
    else:
        raise AssertionError("register_tool should reject unknown capability")


def test_meta_tools_are_explicitly_marked_but_still_model_visible() -> None:
    """元工具是模型可见 Action，但不是普通业务工具。

    `mark_step_complete` / `request_user_input` 必须进入模型工具 schema，
    否则模型无法声明完成或请求用户输入；但它们通过 `meta_tool=True` 走特殊
    runtime protocol，不应产生普通 tool_result，也不能绕过 HITL/user-input 边界。
    """

    _load_builtin_tools()

    from agent.tool_registry import TOOL_REGISTRY, get_tool_definitions, is_meta_tool

    visible_tools = {definition["name"] for definition in get_tool_definitions()}
    actual_meta_tools = {
        name for name, entry in TOOL_REGISTRY.items() if entry.get("meta_tool")
    }

    assert EXPECTED_META_TOOLS <= visible_tools
    assert actual_meta_tools == EXPECTED_META_TOOLS
    assert {name for name in EXPECTED_META_TOOLS if is_meta_tool(name)} == EXPECTED_META_TOOLS
    assert not is_meta_tool("read_file")


def test_tool_registry_does_not_depend_on_runtime_or_confirmation_handlers() -> None:
    """registry 不能反向依赖 runtime/core/HITL。

    这是高内聚、低耦合的边界测试：registry 当前可以保存 callable 和 hook，
    但不应该 import core.py、confirmation handlers、response handlers 或 executor。
    否则未来 MCP / ToolSpec 接入会把 runtime 编排逻辑倒灌进注册表。
    """

    imports = _agent_imports(PROJECT_ROOT / "agent" / "tool_registry.py")

    forbidden = {
        "agent.core",
        "agent.confirm_handlers",
        "agent.response_handlers",
        "agent.tool_executor",
        "agent.checkpoint",
    }
    assert imports.isdisjoint(forbidden)


def test_core_only_consumes_registry_schema_not_specific_tool_modules() -> None:
    """core.py 只应编排工具 schema，不知道具体工具实现。

    当前 core.py 允许 `import agent.tools` 触发注册，也允许从 tool_registry 取
    `get_tool_definitions()`；但它不能 import `agent.tools.file_ops` 这类具体工具。
    这条 seam 防止后续把 MCP 或具体工具逻辑塞进 core.py。
    """

    imports = _agent_imports(PROJECT_ROOT / "agent" / "core.py")

    concrete_tool_imports = {
        import_name
        for import_name in imports
        if import_name.startswith("agent.tools.") and import_name != "agent.tools"
    }

    assert "agent.tools" in imports
    assert "agent.tool_registry" in imports
    assert concrete_tool_imports == set()


def test_agent_tools_does_not_auto_import_removed_low_value_tools() -> None:
    """基础注册入口不应自动加载已移除的低价值工具模块。

    这条测试保护 `agent.tools` 作为基础工具防火墙的职责：移除 calculate
    只改变工具集合边界，不把计算能力替换成 Python/BLOB/patch/shell 新工具，
    也不让 core.py 或 executor 为一个窄工具承担额外分支。
    """

    imports = _agent_imports(PROJECT_ROOT / "agent" / "tools" / "__init__.py")

    assert "agent.tools.calc" not in imports

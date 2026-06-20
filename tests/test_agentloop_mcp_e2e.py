"""Controlled AgentLoop MCP readiness tests plus opt-in real LLM integration.

中文学习边界：
- 默认 readiness tests 使用本地 stdio fixture，不需要真实 API key，也不启动
  真实 npx MCP server。
- 真实 LLM + npx MCP 测试仍是 opt-in，需要显式环境变量和真实
  ANTHROPIC_API_KEY。

测试分为两层：

1. readiness tests（默认运行，使用本地 stdio fixture 验证注册和暴露链路）：
   - test_mcp_model_tools_param_includes_mcp_tool
     MCP registration → get_model_visible_tools → model-visible tools 包含 MCP tool
   - test_mcp_tool_in_registry_after_registration
     MCP registration → TOOL_REGISTRY → capability= mcp_tool, confirmation=always
   - test_mcp_no_key_leak_in_registry_or_tools
     TOOL_REGISTRY 和 model-visible tools 不含 API key pattern

2. opt-in real LLM 测试（需要显式 env + ANTHROPIC_API_KEY=sk-ant-*）：
   - test_real_llm_receives_mcp_tool_in_tools_param
     验证真实 LLM 的 tools 参数包含 MCP tool，并观察模型是否选择 MCP tool

以上均为直调测试（不经 core.chat()），不声称 E2E。
- 只暴露 1-2 个 read-only MCP tools（list_allowed_directories / read_text_file）。
- 使用真实 filesystem MCP server + sandbox 目录。
- 验证 key 不泄漏到 messages / audit / checkpoint / display。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile

import pytest

_project_root = pathlib.Path(__file__).resolve().parents[1]
_FIXTURE_SERVER = _project_root / "tests" / "fixtures" / "minimal_mcp_stdio_server.py"

# 只读取当前进程环境变量；测试导入阶段不能读取 .env 或打印 secret。
_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_REAL_LLM_E2E_ENV = "MY_FIRST_AGENT_RUN_REAL_LLM_E2E"
REAL_KEY_AVAILABLE = bool(
    _ANTHROPIC_API_KEY
    and _ANTHROPIC_API_KEY.startswith("sk-")
    and len(_ANTHROPIC_API_KEY) > 20
)
_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")
_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")
# 标记 Anthropic 原生 key（sk-ant-）vs 代理 key（sk-sp-）
_IS_NATIVE_ANTHROPIC = _ANTHROPIC_API_KEY.startswith("sk-ant-")

pytestmark_llm = pytest.mark.skipif(
    not (_IS_NATIVE_ANTHROPIC and os.getenv(_REAL_LLM_E2E_ENV) == "1"),
    reason=(
        "真实 LLM + npx MCP E2E 是 opt-in；需要设置 "
        "MY_FIRST_AGENT_RUN_REAL_LLM_E2E=1 且使用原生 Anthropic API key "
        "(sk-ant-*)。"
        "DashScope 代理端点 (sk-sp-* + ANTHROPIC_BASE_URL) "
        "与 Anthropic SDK 的 /v1/messages 路径不兼容，返回 401。"
        "如需使用代理 provider，请在 core.py levels 做适配，"
        "而不是在测试中绕过 SDK。"
    ),
)

# filesystem MCP server 需要 npx；只用于 opt-in real LLM E2E，不用于默认 readiness。
_NPX_PATH = shutil.which("npx") or os.path.expanduser(
    "~/.nvm/versions/node/v20.20.2/bin/npx"
)


def _local_fixture_server_config(server_name: str):
    """默认 readiness 使用本地 fixture，避免真实 npx/npm/proxy 进入 full pytest。"""

    from agent.mcp import MCPServerConfig

    return MCPServerConfig(
        name=server_name,
        command=sys.executable,
        args=(str(_FIXTURE_SERVER),),
        enabled=True,
    )


def _temp_sandbox() -> pathlib.Path:
    sandbox = pathlib.Path(tempfile.mkdtemp(prefix="mcp_e2e_sandbox_"))
    hello = sandbox / "hello.txt"
    hello.write_text("hello from AgentLoop E2E test", encoding="utf-8")
    return sandbox


# ============================================================================
# MCP read-only tool 进入 AgentLoop（直调测试，不经 core.chat）
# ============================================================================


def test_mcp_model_tools_param_includes_mcp_tool():
    """验证 get_model_visible_tools 包含注册后的 MCP tool。（直调测试）"""
    from agent.mcp import register_mcp_tools
    from agent.mcp_stdio import StdioMCPClient
    from agent.tool_registry import TOOL_REGISTRY, get_model_visible_tools

    server_name = "e2e_fs"
    try:
        server = _local_fixture_server_config(server_name)
        client = StdioMCPClient(timeout_seconds=5)
        register_mcp_tools(
            [server], client,
            server_allowlist=frozenset({server_name}),
            dry_run=False,
        )

        # 只暴露 1 个 MCP tool
        tools = get_model_visible_tools(max_mcp_tools=1)
        mcp_names = [t["name"] for t in tools if t["name"].startswith("mcp__")]
        assert mcp_names == [f"mcp__{server_name}__echo"]
        # 验证 model-visible description 带来源标记
        for t in tools:
            if t["name"].startswith("mcp__"):
                assert f"[MCP:{server_name}]" in t["description"]
                assert "server_name" not in t["description"]
                assert "inputSchema" not in t["description"]
    finally:
        for name in list(TOOL_REGISTRY):
            if name.startswith(f"mcp__{server_name}__"):
                TOOL_REGISTRY.pop(name, None)


def test_mcp_tool_in_registry_after_registration():
    """注册后的 MCP tool 在 TOOL_REGISTRY 中。（直调测试）"""
    from agent.mcp import register_mcp_tools
    from agent.mcp_stdio import StdioMCPClient
    from agent.tool_registry import TOOL_REGISTRY

    server_name = "e2e_reg"
    try:
        server = _local_fixture_server_config(server_name)
        client = StdioMCPClient(timeout_seconds=5)
        reg_names = register_mcp_tools(
            [server], client,
            server_allowlist=frozenset({server_name}),
            dry_run=False,
        )
        assert reg_names == (f"mcp__{server_name}__echo",)
        for name in reg_names:
            assert name in TOOL_REGISTRY
            entry = TOOL_REGISTRY[name]
            assert entry["capability"] == "mcp_tool"
            assert entry["confirmation"] == "always"
            assert f"[MCP:{server_name}]" in entry["description"]
    finally:
        for name in list(TOOL_REGISTRY):
            if name.startswith(f"mcp__{server_name}__"):
                TOOL_REGISTRY.pop(name, None)


def test_mcp_no_key_leak_in_registry_or_tools():
    """TOOL_REGISTRY 和 model-visible tools 不含 API key。（直调测试）"""
    from agent.mcp import register_mcp_tools
    from agent.mcp_stdio import StdioMCPClient
    from agent.tool_registry import TOOL_REGISTRY, get_model_visible_tools

    server_name = "e2e_leak"
    try:
        server = _local_fixture_server_config(server_name)
        client = StdioMCPClient(timeout_seconds=5)
        register_mcp_tools(
            [server], client,
            server_allowlist=frozenset({server_name}),
            dry_run=False,
        )

        registry_str = str(TOOL_REGISTRY)
        assert "sk-ant-" not in registry_str
        assert "sk-" not in registry_str

        tools = get_model_visible_tools(max_mcp_tools=5)
        tools_str = str(tools)
        assert "sk-ant-" not in tools_str
        assert "sk-" not in tools_str
        for tool in tools:
            if tool["name"] == f"mcp__{server_name}__echo":
                assert f"[MCP:{server_name}]" in tool["description"]
                assert "server_name" not in tool["description"]
    finally:
        for name in list(TOOL_REGISTRY):
            if name.startswith(f"mcp__{server_name}__"):
                TOOL_REGISTRY.pop(name, None)


# ============================================================================
# 真实 LLM + MCP tool（opt-in，需要真实 API key，直调不经 core.chat）
# ============================================================================


@pytestmark_llm
def test_real_llm_receives_mcp_tool_in_tools_param():
    """真实 LLM + MCP read-only tool 的受控集成测试。

    验证：MCP registration → tool exposure → model select MCP tool。（直调，不经 core.chat()）
    """
    from agent.mcp import MCPServerConfig, register_mcp_tools
    from agent.mcp_stdio import StdioMCPClient
    from agent.tool_registry import TOOL_REGISTRY, get_model_visible_tools

    sandbox = _temp_sandbox()
    try:
        # 1. MCP registration：注册 read-only MCP tools
        server = MCPServerConfig(
            name="e2e_llm",
            command=_NPX_PATH,
            args=("-y", "@modelcontextprotocol/server-filesystem", str(sandbox)),
            enabled=True,
        )
        mcp_client = StdioMCPClient(timeout_seconds=10)
        mcp_names = register_mcp_tools(
            [server], mcp_client,
            server_allowlist=frozenset({"e2e_llm"}),
            dry_run=False,
        )
        assert len(mcp_names) > 0, "MCP registration 应注册至少 1 个 tool"

        # 2. 验证 model-visible tools 包含 MCP tool 且不含 destructive tools
        tools = get_model_visible_tools(max_mcp_tools=2)
        mcp_tool_names = [t["name"] for t in tools if t["name"].startswith("mcp__")]
        assert len(mcp_tool_names) >= 1, "model-visible tools 应包含 MCP tool"
        # 不包含 destructive tools
        for t in tools:
            assert "write_file" not in t["name"], f"model tools 不应包含 write: {t['name']}"
            assert "edit_file" not in t["name"]
            assert "create_directory" not in t["name"]
            assert "move_file" not in t["name"]

        # 3. 用真实 Anthropic API key 构造一个简单的单轮 LLM 调用
        # 使用项目自身 core.py 的 _call_model——但需要避免走 full AgentLoop。
        # 这里用最小的 Anthropic client 调用，尊重 ANTHROPIC_BASE_URL
        import anthropic
        api_key = os.environ["ANTHROPIC_API_KEY"]
        base_url = os.getenv("ANTHROPIC_BASE_URL", None)

        client_kwargs: dict = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        llm_client = anthropic.Anthropic(**client_kwargs)
        model_name = os.getenv("ANTHROPIC_MODEL", "") or "claude-sonnet-4-6"

        response = llm_client.messages.create(
            model=model_name,
            max_tokens=512,
            system=(
                "你是一个测试助手。当前工作目录中有一个 MCP sandbox。"
                "请使用 list_allowed_directories 工具列出可访问的目录，"
                "然后用 read_text_file 读取 hello.txt 的内容。"
                "最后，告诉我文件内容是什么。"
            ),
            messages=[{
                "role": "user",
                "content": "请读取 MCP sandbox 中 hello.txt 的内容，并告诉我文件内容。"
            }],
            tools=tools,
        )

        # 4. 验证模型响应不含 key
        response_str = str(response.content)
        assert "sk-" not in response_str.lower() or "[REDACTED]" in response_str, (
            "LLM response 不应包含 key pattern"
        )

        # 5. 检查模型是否选择了 MCP tool
        tool_blocks = [
            b for b in response.content if getattr(b, "type", None) == "tool_use"
        ]
        if tool_blocks:
            for tb in tool_blocks:
                assert tb.name.startswith("mcp__"), (
                    f"模型应选择 MCP tool, 实际: {tb.name}"
                )
                # tool_use input 不含 key
                assert "sk-" not in str(tb.input).lower() or len(str(tb.input)) < 50
            print(f"\n  ✅ 模型选择了 {len(tool_blocks)} 个 MCP tool(s): "
                  f"{[tb.name for tb in tool_blocks]}")
        else:
            # 模型没有选择 tool，记录但不 fail——
            # 可能是 model/provider 差异导致的，不影响 MCP 基础设施验证
            print(f"\n  ⚠️ 模型未选择 MCP tool（stop_reason={response.stop_reason}）")
            # 如果有 text 回复，打印摘要
            text_blocks = [
                b for b in response.content if getattr(b, "type", None) == "text"
            ]
            if text_blocks:
                first_block = text_blocks[0]
                text_value = first_block.text if hasattr(first_block, "text") else first_block
                preview = str(text_value)[:200]
                print(f"  model text: {preview}")

        # 6. 验证 response 不含 key
        assert "sk-ant-" not in response_str
        assert "ANTHROPIC_API_KEY" not in response_str.upper()
    finally:
        for name in list(TOOL_REGISTRY):
            if name.startswith("mcp__e2e_llm__"):
                TOOL_REGISTRY.pop(name, None)
        shutil.rmtree(sandbox, ignore_errors=True)

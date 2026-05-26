# MCP Runbook

## 当前状态

my-first-agent 处于 **Controlled MCP Bridge Foundation** 阶段：
- MCP policy gate (server-level + tool-level) ✅
- MCP descriptor sanitization ✅
- MCP audit trail ✅
- MCP bridge thin adapter ✅
- Policy-gated registration ✅
- Second server controlled flight ✅
- Tool exposure filter ✅

**未完成**:
- 真实 AgentLoop E2E with MCP tools
- 真实 MCP server 自由扩展
- 写操作 / destructive tools
- GitHub / Slack / Notion / Google Drive / DB MCP

## 启停与开关

### 总开关
```
MY_FIRST_AGENT_MCP_ENABLE=1   # 1/true/yes/on → 启用
default: disabled
```

### 模式
```
MY_FIRST_AGENT_MCP_MODE=registration   # disabled / discovery / registration
default: registration
```

### Dry-run
```
MY_FIRST_AGENT_MCP_DRY_RUN=1   # 1 → FakeMCPClient（不启动真实进程）
default: 1 (dry-run)
```

### 回滚/禁用
```bash
unset MY_FIRST_AGENT_MCP_ENABLE    # 完全禁用
MY_FIRST_AGENT_MCP_MODE=disabled   # bridge 返回空报告
```

## 受控接入步骤

### 1. 确认安全基础
```bash
.venv/bin/python main.py health   # 查看 tool_registry_integrity + mcp_config_readiness
```

### 2. 添加 MCP Server
1. 选择 server：官方/reference server、stdio、read-only、sandboxable
2. 在 mcp_config.json 中配置 server name / command / args
3. 设置 enabled=true
4. 将 server name 加入 server_allowlist

### 3. Discovery 模式验证
```bash
MY_FIRST_AGENT_MCP_ENABLE=1 MY_FIRST_AGENT_MCP_MODE=discovery .venv/bin/python -c "
from agent.mcp_bridge import run_mcp_bridge
report = run_mcp_bridge(mode='discovery', dry_run=False)
print(report)
"
```

### 4. Registration 模式
```bash
MY_FIRST_AGENT_MCP_ENABLE=1 MY_FIRST_AGENT_MCP_DRY_RUN=0 .venv/bin/python main.py
# 或通过测试验证:
.venv/bin/python -m pytest tests/test_real_mcp_flight.py -v
```

### 5. 默认测试 vs 真实 npx flight

默认 `pytest` 使用 deterministic local fixture MCP servers，覆盖 stdio
JSON-RPC、policy gate、sanitizer、registry、tool exposure、read-only call、
audit/no-leak 和 AgentLoop MCP readiness。默认测试不启动真实
`npx @modelcontextprotocol/server-filesystem`，因为它依赖 npx/npm registry、
proxy、server startup 和 MCP handshake，属于外部集成 flight。

真实 npx MCP server flight 仍保留，但必须显式 opt-in：

```bash
MY_FIRST_AGENT_RUN_REAL_MCP_FLIGHT=1 .venv/bin/python -m pytest tests/test_real_mcp_flight.py -v
```

如果 opt-in flight 出现 `tools/list` timeout，优先检查 npx/npm registry、
proxy、server startup 时间和 MCP handshake 兼容性。该 timeout 不代表 provider
adapter 失败，也不代表 MCP policy / sanitizer / registry 默认覆盖失败。

## 审计检查

### 查看 MCP audit 事件
```bash
.venv/bin/python main.py logs --event tool_audit --tail 50
```

### 验证 no-leak
```bash
.venv/bin/python -m pytest tests/test_real_mcp_flight.py -k "secret or no_leak" -v
```

### 验证 policy gate
```bash
.venv/bin/python -m pytest tests/test_mcp_policy_gate.py tests/test_mcp_registration_policy.py -v
```

## 安全 checklist

- [ ] server 在 allowlist 中
- [ ] transport 为 stdio
- [ ] destructive tools 被 DEFAULT_DESTRUCTIVE_TOOL_PATTERNS 阻止
- [ ] raw descriptor 不进入 model-visible schema
- [ ] audit 不含 raw descriptor / secret
- [ ] health check 确认 MCP 模块可用
- [ ] tool exposure filter 有硬限制

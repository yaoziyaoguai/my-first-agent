# MCP Secret Handling

## Redaction 覆盖矩阵

| 通道 | Redaction 方法 | 测试覆盖 |
|---|---|---|
| agent_log.jsonl | `_safe_log_value` → `mask_user_visible_secrets` | ✅ |
| tool_execution_log | `_mask_failure_value` | ✅ |
| checkpoint | tool_execution_log 脱敏后进入 | ⚠️ 依赖上游 |
| conversation.messages | `mask_user_visible_secrets` pre-append | ✅ |
| display event | `mask_user_visible_secrets` | ✅ |
| audit event | `safe_preview` (ToolResultEnvelope) | ✅ |
| StdioMCPClient env | 只继承 PATH | ✅ |
| git diff | 无 key 写入源文件 | ✅ ruff |

## 支持的 key 格式

- `sk-ant-*` (Anthropic)
- `sk-*` (OpenAI 及类似格式)
- `api_key=*` (generic env var)
- BEGIN PRIVATE KEY (PEM)

## 需要用户做的

- 将 key 写入 .env 或 export 环境变量
- 不要在 prompt 中粘贴 raw key
- 不要将 key 写入任何项目文件

## No-leak 验证命令

```bash
.venv/bin/python -m pytest tests/test_real_mcp_flight.py -k "secret" -v
.venv/bin/python -m pytest tests/test_executor_audit_integration.py -v
```

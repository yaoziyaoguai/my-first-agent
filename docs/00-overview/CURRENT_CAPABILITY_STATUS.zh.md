# Current Capability Status

这篇文档用一页说明 First Agent 现在能做什么、不能做什么。

当前标签：**developer prototype / developer-dogfood**。它适合继续做本地 runtime、Memory、Skill、Sub-agent 边界开发和测试，不是面向普通用户的产品。

## 现在可用

| Area | 当前能力 | 边界 |
|---|---|---|
| Plain CLI | `python main.py --plain` 可进入本地交互路径 | 默认 fake/local；真实 provider 需要显式配置 |
| Textual TUI | `python main.py --tui` 保留候选入口 | 不是默认主路径 |
| Runtime loop | `core.chat()` + `loop.py` 统一调度 | 不新增第二 runtime |
| Tool pipeline | `ToolRuntimeMediator → tool_executor` 执行真实工具 | `TOOL_INVOKE` dispatcher path 不直接执行工具 |
| Memory v0 | explicit retain / confirmation / safe evidence / store reference | 不做 raw write，不做 auto-adoption |
| Skill lifecycle | active skill lifecycle、allowed_tools、checkpoint-safe metadata | Skill 仍是实验性能力，不是 marketplace |
| MCP | MCP tool 复用普通 tool 管线和 evidence | 不默认连接真实外部 MCP server |
| Sub-agent v0 | v0 contract、context/evidence redaction、parent decision | L1/L2 legacy route frozen，不是当前主线 |
| Evidence | `record_evidence()` 统一写入 | 不持久化 raw tool result / raw memory / raw provider text |

## 不能声称

- 不能声称项目已经是普通用户产品。
- 不能把 fake/local 或 focused test 结果写成真实能力完成。
- 不能声称 Memory semantic recall、MCP 外部集成、Sub-agent L1/L2 或 Skill marketplace 已默认可用。
- 不能让 child 绕过 parent runtime 直接执行工具、MCP 或 Memory 写入。

## 当前行动

- 清理旧文档和旧实验上下文。
- 保留当前实现、测试保护网和短文档。
- 后续代码删除必须先做 no imports / no tests / no docs references 证明。

## 事实源

- [PROJECT_STATUS.md](../PROJECT_STATUS.md)
- [UNIFIED_RUNTIME_FLOW_CONTRACT.md](../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
- [CURRENT_AUDIT_STATUS.zh.md](../06-audit/CURRENT_AUDIT_STATUS.zh.md)

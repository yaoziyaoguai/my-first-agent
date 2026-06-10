# Project Status — First Agent

**最后更新**: 2026-06-10
**当前状态**: **developer prototype / local development**。当前工作重点是 repository cleanup、source-of-truth repair 和保持 runtime 边界清晰。

本文档是 Coding Agent 和人类开发者的第一优先读取入口。如果其他文档与本文档冲突，以本文档为准。

## 当前实现地图

| capability | current source of truth | 当前结论 |
|---|---|---|
| Runtime baseline | `main.py`, `agent/core.py`, `agent/loop.py` | 主线是 CLI/TUI adapter 调 `core.chat()`，loop 负责模型循环和 runtime action hook。 |
| Tool execution | `agent/tool_runtime_mediator.py`, `agent/tool_executor.py` | 真实工具执行只能走 `ToolRuntimeMediator → tool_executor`。 |
| TOOL_INVOKE dispatcher | `agent/runtime_integration/tool_invoke.py` | evidence-only marker，不直接调用工具函数，避免双重执行和绕过 mediator。 |
| MCP boundary | `agent/runtime_integration/mcp_tool_orchestrator.py`, `agent/runtime_integration/phase1_hook.py` | MCP 复用普通 tool 管线；当前是 adapter skeleton / harness-aware，不标默认外部集成。 |
| Memory v0 | `agent/memory_runtime.py`, `agent/memory_contracts.py`, `agent/evidence_recorder.py` | explicit retain、confirmation、safe evidence、store reference 基线存在；不做 raw write 或 auto-adoption。 |
| Skill lifecycle | `agent/skill_system/`, `agent/runtime_integration/skill_lifecycle.py` | active skill lifecycle 由 runtime 管，checkpoint metadata 不保存 raw skill body。 |
| Sub-agent v0 | `agent/runtime_integration/subagent_action.py`, `agent/subagent_system/v0_contract.py` | v0 contract / evidence / parent decision 边界已建立；child 不直接执行工具/MCP/Memory 写入。 |
| Evidence/logging | `agent/evidence_recorder.py`, `agent/event_log.py`, `agent/log_viewer.py` | 子系统统一用 `record_evidence()`，不各自新增日志系统。 |

## 当前边界

- 不恢复旧 L1/L2 production route；L1/L2 旧 child loop 只作为 compatibility / legacy / tests / gated future。
- 不引入第二 runtime，不绕过 `agent/core.py` / `agent/loop.py` 主线。
- 不让 child direct tool/MCP execution；parent runtime 保持中介和裁决。
- 不新增 Memory raw write，不写真实 home config，不自动采纳 memory proposal。
- FakeProvider 增长冻结；FakeProvider 只证明 deterministic test double 路径，不证明真实自然语言语义。
- Memory Consolidation pipeline 冻结；可保留 contract/evidence，真实 LLM consolidation deferred。
- `config/config.yaml` 是当前本地配置入口；如果含真实 key，**不得 commit**。

## 配置

| 文件 | 状态 |
|---|---|
| `config/config.yaml` | 本地配置入口，可含真实 key，不得提交 |
| `config/config.example.yaml` | 可提交模板 |
| `config/examples/` | 示例配置 |

默认 fake/local 可运行。真实 provider 必须显式 opt-in，且不得把 secret 输出到日志、文档或测试快照。

## 文档状态

| 文档 | 用途 |
|---|---|
| [README.md](../README.md) | 项目入口 |
| [docs/README.zh.md](README.zh.md) | 文档入口 |
| [docs/CURRENT_DOCS.md](CURRENT_DOCS.md) | 当前文档地图 |
| [docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md](00-overview/CURRENT_CAPABILITY_STATUS.zh.md) | 当前能力摘要 |
| [docs/06-audit/CURRENT_AUDIT_STATUS.zh.md](06-audit/CURRENT_AUDIT_STATUS.zh.md) | 当前审计入口 |
| [docs/PROGRESS_LEDGER.md](PROGRESS_LEDGER.md) | 历史里程碑账本 |

当前审计入口是 [docs/06-audit/CURRENT_AUDIT_STATUS.zh.md](06-audit/CURRENT_AUDIT_STATUS.zh.md)。旧审计证据不自动变成当前 backlog。

## 授权状态

- cleanup/source-of-truth repair：**已授权**。
- 本地静态检查和 focused tests：**已授权**。
- push、tag、真实外部 API/MCP 调用、读取真实 secrets/private data：未授权，必须另行明确授权。

## 推荐下一步

1. 继续删除旧计划、旧审计、临时 notes 和 generated artifacts。
2. 对 scripts/examples/demos 做引用检查；只删除无 import、无测试、无文档引用且不在当前实现地图里的低风险项。
3. suspected dead code 只列候选，不自动删除。

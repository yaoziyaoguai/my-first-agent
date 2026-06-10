# First Agent 文档入口

本文档只保留当前开发所需入口。历史计划、旧审计、旧验证材料和错误方向设计不作为当前依据。

## 必读顺序

| 顺序 | 文档 | 用途 |
|---|---|---|
| 1 | [PROJECT_STATUS.md](PROJECT_STATUS.md) | 当前状态、实现地图、边界和下一步 |
| 2 | [00-overview/CURRENT_CAPABILITY_STATUS.zh.md](00-overview/CURRENT_CAPABILITY_STATUS.zh.md) | 当前能力一页版 |
| 3 | [06-audit/CURRENT_AUDIT_STATUS.zh.md](06-audit/CURRENT_AUDIT_STATUS.zh.md) | 当前审计口径 |
| 4 | [dev/AUTO_RUN_WORKFLOW.md](dev/AUTO_RUN_WORKFLOW.md) | 自动化工程流程和 hard stops |
| 5 | [PROGRESS_LEDGER.md](PROGRESS_LEDGER.md) | 历史里程碑账本，仅作追溯 |

## 当前实现源头

| 能力 | 当前 source of truth |
|---|---|
| Runtime baseline | `main.py`, `agent/core.py`, `agent/loop.py` |
| Tool/MCP boundary | `agent/tool_runtime_mediator.py`, `agent/tool_executor.py`, `agent/runtime_integration/tool_invoke.py`, `agent/runtime_integration/mcp_tool_orchestrator.py` |
| Memory v0 | `agent/memory_runtime.py`, `agent/memory_contracts.py`, `agent/evidence_recorder.py` |
| Skill lifecycle | `agent/skill_system/`, `agent/runtime_integration/skill_lifecycle.py` |
| Sub-agent v0 | `agent/runtime_integration/subagent_action.py`, `agent/subagent_system/v0_contract.py` |
| Evidence/logging | `agent/evidence_recorder.py`, `agent/event_log.py`, `agent/log_viewer.py` |

## 配置

| 文件 | 状态 |
|---|---|
| `config/config.yaml` | 当前本地配置入口；可含真实 key，但不得 commit |
| `config/config.example.yaml` | 可提交模板；默认 fake/local |
| `config/examples/` | 示例配置 |

## 当前文档

| 目录 | 用法 |
|---|---|
| [rfc/](rfc/) | Memory / Skill / SubAgent canonical RFC |
| [design/](design/) | 当前仍有价值的架构设计；以 `PROJECT_STATUS.md` 为准 |

## 当前规则

- 不恢复旧 L1/L2 production route。
- 不新增第二 runtime。
- child 不直接执行工具/MCP；parent runtime 保持控制。
- Memory 不做 raw write，不做 auto-adoption。
- FakeProvider 增长冻结，不把 fake-only 证据写成真实能力。

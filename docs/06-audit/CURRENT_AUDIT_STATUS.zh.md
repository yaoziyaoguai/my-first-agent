# Current Audit Status

这篇文档是当前审计状态入口，记录项目整体健康度和各 Area 的当前审计结论，方便 push 前快速判断。

不替代独立审计报告，也不作为 tag/release 授权。

**事实源**：以当前代码、最新 commits 和 [Current Capability Status](../00-overview/CURRENT_CAPABILITY_STATUS.zh.md) 为准。archive docs 不是当前入口。

## 总体结论

Status: **Cleanup-Only / Awaiting Manual Human Dogfood** — 能力建设暂停。

- ✅ `manual-dogfood-ready local agent`：FakeProvider baseline 9/9 PASS。
- 🟡 `limited user-usable agent`：核心功能可用，UX polish 不足。
- 🟡 `real-provider-dogfood-tested`：历史 Kimi/DashScope 5/6 PASS；当前 deepseek-v4-pro 受 401 config/auth concern 阻塞。
- ❌ `broadly user-usable agent`：不在当前 scope。

**当前最高优先级下一步**：Manual Human Dogfood（需人类完成，非自动步骤）。

**AutoRun 模式**：cleanup/source-of-truth only。不做新能力建设、不做 industry comparison、不新增 feature。除非用户显式改变目标。

## 当前阶段入口

当前一页状态：[Current Capability Status](../00-overview/CURRENT_CAPABILITY_STATUS.zh.md)

当前行动依据：
- [global-red-team-product-architecture-audit-2026-05-25.md](../audit/global-red-team-product-architecture-audit-2026-05-25.md) — 全仓库 Red-Team 审计，当前权威源
- [capability-gap-audit-low-complexity-2026-05-25.md](../audit/capability-gap-audit-low-complexity-2026-05-25.md) — low-complexity remediation 选择依据
- [final-cleanup-readiness-summary-2026-05-25.md](../plans/final-cleanup-readiness-summary-2026-05-25.md) — cleanup 完成，manual human dogfood 下一步

已完成的能力建设（历史证据，非当前行动指令）：
- WP1-WP4: First Usable Task MVP
- Memory 主线、Skill System safe-local 基线、SubAgent L0 deterministic/local 基线
- Tool Pipeline L3、Global Red-Team Remediation (RT-01~RT-18, 6 phases)
- Cleanup-Only Remediation (PF-01~PF-15)
- Low-Complexity Remediation (6 项 safe-to-auto-run 补齐)
- Documentation Source-of-Truth Reset

## Area status

| Area | Status | Evidence | Risk |
|---|---|---|---|
| Runtime/Core/Loop | Healthy | `core.chat()` → `loop.py` → Tool Pipeline / RuntimeAction dispatcher 主路径统一；fake/real 共享同一 runtime | P3: `core.py` 仍偏大 |
| ToolRegistry/ToolExecutor | Healthy | ToolRegistry metadata、confirmation、visibility 治理完整 | 测试隔离需持续关注 |
| Memory | Healthy with explicit gaps | no silent retain / no auto approve；confirmation → pending_retain_proposals → turn-end MEMORY_PROPOSE dispatch；deterministic recall/injection baseline 覆盖 governance | real LLM semantic recall/injection quality 仍是 future gated；Memory Consolidation pipeline 已冻结 |
| Skill | Healthy | formal `agent/skill_system/`；legacy 隔离；synthetic + real API dogfood 证据 | 非 marketplace，非远程安装 |
| SubAgent | Healthy | L0 complete；T1 synthetic dogfood 16/16；L1-L5 gated/future | none blocking |
| Checkpoint | Healthy | 截断 tool_result；过滤未知字段；safe summary 边界 | none blocking |
| Confirmation / Ask User | Healthy | request_user_input / memory confirmation / tool confirmation 复用 runtime 边界 | none blocking |
| CLI/TUI | Acceptable with P3 adapter debt | adapter/presentation only | P3: `main.py` 仍承担 adapter 兼容 |
| Dogfood | Healthy | fake/local rehearsal 11/11 PASS；agent-driven rehearsal ≠ manual human dogfood | real dogfood 受 401 concern 阻塞 |
| Provider config | Healthy | `AgentProviderConfig` + factory；provider boundary 清晰 | FakeProvider 增长已冻结 |
| Security/Secrets | Healthy | `.env` / `agent_log.jsonl` / sessions/runs/memory episodes 不进仓库 | do not read real artifacts in audit |
| Documentation | Healthy — source-of-truth reset 完成 | active ~30 docs；~150+ historical/expired docs archived | archive docs 不能被 AutoRun 当作当前入口 |

## Ready to push?

**Yes — for cleanup/source-of-truth changes.** 当前 main HEAD 已通过 ruff + focused tests。

**No — for new capability.** 能力建设暂停，manual human dogfood 是下一步。不做新 feature、新能力、新审计。

## Known limitations / P3 backlog

- `core.py` remains a runtime hub；不建议本轮机械拆分。
- Memory Consolidation pipeline 已冻结（6 个 consolidation 文件的 dispatch/handler path 已验证，business operation / real LLM consolidation deferred）。
- FakeProvider 增长已冻结（不继续增强为 fake planner / fake reasoning engine）。
- Memory real LLM recall/injection quality 仍是 future gated track。
- SubAgent L1-L5 仍是 gated/future。
- Sandbox/worktree/parallel SubAgent 仍是 future/contract。
- Real MCP server activation 仍是 opt-in。
- DB/graph/embedding/vector store 不是默认 memory backend。
- `openai_compatible` streaming 仍是 unsupported by design，fail closed。
- Skill/SubAgent real user dogfood 和 true multi-process/session productization 仍是 future tracks。

## Latest verification baseline

- ruff: passed
- full pytest: `~3380 passed, 18 skipped`（最近全量基线，见 [Current Capability Status](../00-overview/CURRENT_CAPABILITY_STATUS.zh.md)）
- synthetic subagent dogfood: `16/16 passed`
- synthetic skill dogfood: `12/12 passed`
- synthetic global dogfood: `12/12 passed`

## 历史审计证据

以下文档已归档或标记为 historical，保留为实现证据链，**不作为当前行动源**：

- v0.9.x Stabilization 文档包：`docs/archive/refactor/V0_9_X_*`（RFC/SDD/TDD/Implementation Loop/Dogfood/Audit Checklist）
- Runtime Integration 文档包：`docs/archive/runtime-integration/RUNTIME_INTEGRATION_*`（RFC/SDD/TDD/Implementation Loop/E2E Dogfood Plan/Audit Checklist）
- 历史审计：见 [docs/audit/README.md](../audit/README.md) Historical 部分
- 历史计划：见 [docs/plans/README.md](../plans/README.md) Historical 部分

**AutoRun 不得将以上 historical/archived 文档当作当前 backlog 或执行依据。**

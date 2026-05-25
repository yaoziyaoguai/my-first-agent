# Global Agent Capability / Architecture Audit

> **审计日期**: 2026-05-25
> **审计类型**: 只读全局审计（Read-only Global Product / Architecture / Code Audit）
> **审计范围**: 整个仓库 — 代码、测试、文档、工程契约、dogfood 报告
> **严格边界**: 不改 production code、不改 tests、不 commit、不 push、不读 .env、不打印 secret、不调用真实 API/LLM、不访问外部网络

---

## Repo 安全快照

| 检查项 | 状态 | 详情 |
|--------|------|------|
| pwd | ✅ | `/Users/jinkun.wang/work_space/my-first-agent` |
| 分支 | ✅ | `main`, clean |
| ahead/behind origin/main | ✅ | 0 / 0 |
| git tag at HEAD | ✅ | 无 |
| git diff --stat | ✅ | clean |
| untracked files | ✅ | 无 |
| ruff check | ✅ | All checks passed |
| pytest | ✅ | **3331 passed**, 18 skipped, 0 failed |
| secrets in source | ✅ | 无硬编码密钥 |

**结论**: 仓库处于干净、健康、可审计状态。

---

## A. Executive Summary

### 当前阶段定位

First Agent 当前处于 **manual-dogfood-ready local agent** 与 **real-provider-dogfood-ready agent** 的交界处。

更精确地说：

| 阶段 | 是否达到 | 证据 |
|------|----------|------|
| architecture prototype | ✅ 已超越 | unified runtime flow 已稳定运行 |
| developer-usable runtime | ✅ | `core.chat()` API 稳定，dogfood scripts 可用 |
| manual-dogfood-ready local agent | ✅ | Fake 9/9 PASS, checklist 就绪 |
| real-provider-dogfood-ready agent | ✅ (with caveat) | Real 5/6 PASS, tool_use 功能已确认但 prompt 敏感 |
| limited user-usable agent | 🟡 接近 | 核心功能可用，但 UX polish 不足 |
| broadly user-usable agent | ❌ 不是目标 | 不在当前 scope |

### 关键判断

**当前最大优势**: Unified Runtime Flow 的 provenance 防伪机制。`route_from_runtime_loop()` vs `route()` 的区分、`core_loop_invoked` 不可来自 payload、handler evidence_extra reserved fields fail-closed — 这些设计保证了 L3 evidence 永远不能被伪造。这是绝大多数 agent runtime 项目忽略的审计基础。

**当前最大短板**: Real provider 下工具调用的 prompt 敏感度。kimi-k2.5 虽支持 Anthropic-style tool_use blocks，但 natural language tool use 场景下未触发工具。这是当前 fake→real 可用性差距的最大单一因素。

**AutoRun 适合度**: ✅ 适合继续。Architecture Extension Loop 机制成熟，但需要更多 human steering 来确保方向正确。

**Manual dogfood 适合度**: ✅ 适合。local-manual-dogfood-checklist.md 已就绪，Fake 9/9 PASS。

**Real provider dogfood 适合度**: ✅ 适合（with caveat）。需用户显式授权和 API key。

**P0**: 无。

**P1**: STREAMING_EVENT 实际已激活（见 Section F），但用户体验路径不清晰；real provider tool_use prompt sensitivity。

**需要砍掉/冻结**: 见 Section F（Redundancy / Cut List）。主要问题是文档膨胀，不是代码冗余。

---

## B. Capability Inventory

### B.1 基础对话

| 字段 | 值 |
|------|-----|
| capability name | Basic Chat |
| user-facing status | ✅ 可用 |
| internal/runtime status | `core.chat()` → `loop.run_main_loop()` → `call_model()` → `dispatch_model_output()` |
| evidence files/tests | `tests/smoke/`, `tests/test_main_loop.py`, dogfood reports |
| fake/local support | ✅ FakeProvider 回显 |
| real provider support | ✅ kimi-k2.5 验证通过 |
| current maturity | **dogfood ready** |
| overclaim risk | 低 — 文档诚实说明 fake/real 差异 |
| next action | 维持 |

### B.2 Real Provider Loading

| 字段 | 值 |
|------|-----|
| capability name | Real provider loading from project .env |
| user-facing status | ✅ opt-in |
| internal/runtime status | `agent/provider/factory.py:build_model_provider_from_env()` |
| evidence files/tests | `tests/test_provider_contract.py`, dogfood scripts |
| fake/local support | N/A |
| real provider support | ✅ anthropic_native/compatible, openai_native/compatible |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持；考虑增加 provider swap 评估 |

### B.3 FakeProvider

| 字段 | 值 |
|------|-----|
| capability name | FakeProvider deterministic fixture |
| user-facing status | ✅ 默认路径 |
| internal/runtime status | `agent/provider/fake_provider.py` (432 lines) |
| evidence files/tests | `tests/test_fake_provider_decision.py`, 所有 L3 测试 |
| fake/local support | ✅ 核心能力 |
| real provider support | N/A |
| current maturity | **production-like** |
| overclaim risk | 🟡 中 — 4 策略优先级 tool_use 匹配不应继续增强为 planner |
| next action | **冻结增强**；当前 deterministic decision layer 已足够 |

### B.4 Tool Registry / Descriptor / Execution

| 字段 | 值 |
|------|-----|
| capability name | Tool registry, tool descriptor, tool execution |
| user-facing status | ✅ 可用 |
| internal/runtime status | `agent/tool_registry.py`, `agent/tool_executor.py` |
| evidence files/tests | `test_tool_registry_contract.py`, `test_tool_*.py` |
| fake/local support | ✅ demo.echo_task_summary / demo.write_demo_note |
| real provider support | ✅ (prompt sensitive) |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持 |

### B.5 Tool Gate / Invoke / Result Lifecycle

| 字段 | 值 |
|------|-----|
| capability name | Tool gate / invoke / result lifecycle |
| user-facing status | ✅ 可用 |
| internal/runtime status | Tool Pipeline 四阶段（TOOL_GATE→TOOL_REQUEST→TOOL_INVOKE→TOOL_RESULT）全部 L3 verified |
| evidence files/tests | `tests/runtime_integration/test_tool_pipeline_l3_completion.py` 等 9 个 spec 目录 |
| fake/local support | ✅ 所有 4 种 disposition |
| real provider support | ✅ |
| current maturity | **production-like** |
| overclaim risk | 低 |
| next action | 维持 |

### B.6 Tool Result Visible to User

| 字段 | 值 |
|------|-----|
| capability name | Tool result visible to user |
| user-facing status | ✅ 可用 |
| internal/runtime status | `tool_result_feedback.py` — RuntimeAction handler |
| evidence files/tests | `test_tool_result_feedback_branch_behavior.py` |
| fake/local support | ✅ |
| real provider support | ✅ |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持 |

### B.7 MCP Adapter Boundary

| 字段 | 值 |
|------|-----|
| capability name | MCP adapter boundary through Tool Pipeline |
| user-facing status | 🟡 opt-in (confirmation="always" 被 gate 拦截) |
| internal/runtime status | `agent/mcp*.py`, `agent/runtime_integration/mcp_tool_orchestrator.py` |
| evidence files/tests | `test_mcp_l3_real_core_loop.py` 等 |
| fake/local support | ✅ confirmation="never" 工具走通完整管线 |
| real provider support | ⚠️ 需要 npx/npm + MCP server |
| current maturity | **dogfood ready** (confirmation="never"); **product decision blocked** (confirmation="always") |
| overclaim risk | 低 — 文档诚实 |
| next action | MCP confirmation="always" 需要产品决策 |

### B.8 Skill Selection / Demo Skill

| 字段 | 值 |
|------|-----|
| capability name | Skill selection / demo skill |
| user-facing status | 🟡 框架就绪，demo-note-maker 可用 |
| internal/runtime status | `agent/skill_system/` (15 files), `agent/runtime_integration/skill_action.py` |
| evidence files/tests | `test_skill_l3.py`, `test_skill_select_pipeline_l3.py` |
| fake/local support | ✅ body_load_decision 成功路径 |
| real provider support | ❌ 未验证 |
| current maturity | **local usable** |
| overclaim risk | 🟡 中 — "Skill System" 名称可能暗示 plugin marketplace |
| next action | 文档诚实标注；不扩展到 multi-skill marketplace |

### B.9 SubAgent Delegation

| 字段 | 值 |
|------|-----|
| capability name | SubAgent delegation / demo-stat / code-reviewer / L0 boundary |
| user-facing status | ✅ CLI + NL delegation 可用 |
| internal/runtime status | `agent/subagent_system/` (20 files → 19 after executor split) |
| evidence files/tests | `test_subagent_l3.py`, `test_subagent_user_facing.py` |
| fake/local support | ✅ L0 deterministic keyword matching |
| real provider support | ✅ CLI delegation 在 real provider 下工作正常 |
| current maturity | **dogfood ready** (L0) |
| overclaim risk | 🟡 中 — README 中 "L1-L5 仍 gated/future" 在 SubAgent_L0_TO_L1_AD 后需更新措辞 |
| next action | L1 AD 已定，不实现代码；L0 维持 |

### B.10 NL SubAgent Delegation Fixture

| 字段 | 值 |
|------|-----|
| capability name | Natural-language SubAgent delegation fixture |
| user-facing status | ✅ "帮我统计 demo workspace" → demo-stat |
| internal/runtime status | `cli_commands.py:detect_nl_delegation()` |
| evidence files/tests | `test_subagent_user_facing.py` |
| fake/local support | ✅ deterministic 关键词匹配 |
| real provider support | ✅ (不经过 LLM) |
| current maturity | **dogfood ready** |
| overclaim risk | 🟡 中 — 不应声称 "NL understanding" |
| next action | 文档诚实标注 "deterministic keyword matching, not LLM NLU" |

### B.11 Memory Proposal / Confirmation

| 字段 | 值 |
|------|-----|
| capability name | Memory proposal / confirmation |
| user-facing status | ✅ 可用 |
| internal/runtime status | `agent/memory_runtime.py`, `agent/memory_interaction.py` |
| evidence files/tests | `test_memory_propose_l3.py`, `test_memory_interaction.py` |
| fake/local support | ✅ 两阶段确认流程 |
| real provider support | ✅ 手动验证通过 |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持 |

### B.12 Memory Retain

| 字段 | 值 |
|------|-----|
| capability name | Memory retain |
| user-facing status | ✅ 确认后写入 |
| internal/runtime status | `agent/runtime_integration/memory_retain.py` |
| evidence files/tests | `test_memory_retain_branch_behavior.py` |
| fake/local support | ✅ |
| real provider support | ✅ |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持 |

### B.13 Memory Recall

| 字段 | 值 |
|------|-----|
| capability name | Memory recall |
| user-facing status | 🟡 用户可以通过 "已加载 N 条相关记忆" 感知 |
| internal/runtime status | Path A (pre-loop injection) + Path B (turn-end dispatcher L3 evidence) |
| evidence files/tests | `test_memory_recall_branch_behavior.py`, `test_memory_recall_l3.py` |
| fake/local support | ✅ |
| real provider support | ✅ |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持；不统一双路径（AD 已裁决） |

### B.14 MEMORY_RECALL Dual-Path AD

| 字段 | 值 |
|------|-----|
| capability name | MEMORY_RECALL dual-path AD |
| user-facing status | N/A (架构决策) |
| internal/runtime status | `docs/design/MEMORY_RECALL_DUAL_PATH_AD.md` — decided |
| evidence files/tests | N/A |
| fake/local support | N/A |
| real provider support | N/A |
| current maturity | **decided, implementation deferred** |
| overclaim risk | 低 |
| next action | 维持决定；不重新讨论 |

### B.15 Memory Consolidation

| 字段 | 值 |
|------|-----|
| capability name | Memory consolidation |
| user-facing status | ❌ 不可见 |
| internal/runtime status | L3 dispatch path verified; real LLM deferred |
| evidence files/tests | `test_memory_consolidate_l3.py`, `test_memory_consolidation*.py` |
| fake/local support | 🟡 dispatch path only |
| real provider support | ❌ deferred |
| current maturity | **stub** (dispatch path verified, no real consolidation) |
| overclaim risk | 🟡 中 — 大量 consolidation 代码（6+ 文件）但无用户可见效果 |
| next action | **冻结**；不继续投入，等 real LLM 可用后再激活 |

### B.16 Memory List / Forget

| 字段 | 值 |
|------|-----|
| capability name | Memory list / forget by displayed short ID |
| user-facing status | ✅ 可用 |
| internal/runtime status | CLI meta-command → `_memory_runtime.list_records()` / `remove_record()` |
| evidence files/tests | `test_memory_user_facing.py` (7 tests), `test_memory_interaction.py` |
| fake/local support | ✅ 短 ID 前缀匹配 + ambiguity 保护 |
| real provider support | ✅ |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持 |

### B.17 Checkpoint Save / Resume

| 字段 | 值 |
|------|-----|
| capability name | Checkpoint save / resume |
| user-facing status | ✅ 可用 |
| internal/runtime status | `agent/checkpoint.py`, `agent/runtime_integration/checkpoint_summary.py` |
| evidence files/tests | `test_checkpoint_save_resume_l3.py`, `test_checkpoint_*.py` |
| fake/local support | ✅ |
| real provider support | ✅ |
| current maturity | **production-like** |
| overclaim risk | 低 |
| next action | 维持 |

### B.18 Streaming Provider Call

| 字段 | 值 |
|------|-----|
| capability name | Streaming provider call |
| user-facing status | 🟡 Fake: deterministic 12-char chunking; Real: 取决于 provider |
| internal/runtime status | `model_call.py` streaming/non-streaming 双路径; `streaming_provider.py` handler |
| evidence files/tests | `test_streaming_l3.py`, `test_streaming_protocol.py` |
| fake/local support | ✅ deterministic chunking (debug/demo only) |
| real provider support | 🟡 depends on provider |
| current maturity | **local usable** (fake); **dogfood ready** (real, provider-dependent) |
| overclaim risk | 🟡 中 — FakeProvider chunking 不应被理解为真实 streaming UX |
| next action | 维持；明确标注 debug/demo |

### B.19 STREAMING_EVENT

| 字段 | 值 |
|------|-----|
| capability name | STREAMING_EVENT |
| user-facing status | ❌ 不可见（per-event evidence collection） |
| internal/runtime status | **已激活** — `loop.py:579-594` 在 streaming_supported 条件下做 per-event dispatch |
| evidence files/tests | `test_streaming_l3.py` |
| fake/local support | ✅ handler 已注册，catalog entry 已更新 |
| real provider support | ✅ (当 provider 支持 streaming 时) |
| current maturity | **L3 evidence path verified** |
| overclaim risk | 低 — 但之前审计误标为 inactive |
| next action | 维持激活状态；不需要额外行动 |

### B.20 Progress/Event UX

| 字段 | 值 |
|------|-----|
| capability name | Progress/event UX |
| user-facing status | ✅ subagent.delegating/delegated, memory.forgotten, memory.injected, tool_requested |
| internal/runtime status | `agent/display_events.py` → `on_runtime_event` sink |
| evidence files/tests | `tests/test_subagent_user_facing.py`, `tests/test_memory_user_facing.py` |
| fake/local support | ✅ |
| real provider support | ✅ |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持；后续可增加 tool.started/completed events |

### B.21 Trace / Run Summary

| 字段 | 值 |
|------|-----|
| capability name | Trace / run summary |
| user-facing status | ✅ run.summary event 每轮 chat() 结束 emit |
| internal/runtime status | `loop.py:_emit_run_summary()`; `agent/local_trace.py` |
| evidence files/tests | `test_local_trace_runtime_wiring_l3.py` |
| fake/local support | ✅ |
| real provider support | ✅ |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持 |

### B.22 Real Provider Tool-Use Dogfood

| 字段 | 值 |
|------|-----|
| capability name | Real provider tool_use dogfood |
| user-facing status | 🟡 opt-in |
| internal/runtime status | `scripts/dogfood_real_provider_e2e.py` |
| evidence files/tests | `docs/dogfood/real-provider-e2e-report.json` (4/4 PASS) |
| fake/local support | N/A |
| real provider support | ✅ kimi-k2.5 Anthropic-style tool_use 已确认 |
| current maturity | **dogfood ready with caveat** |
| overclaim risk | 低 |
| next action | 维持；system prompt 优化 |

### B.23 Automated Memory E2E Dogfood

| 字段 | 值 |
|------|-----|
| capability name | Automated memory E2E dogfood |
| user-facing status | N/A (开发工具) |
| internal/runtime status | `scripts/dogfood_memory_e2e.py` |
| evidence files/tests | `docs/dogfood/memory-e2e-report.json` (5/5 PASS) |
| fake/local support | ✅ FakeProvider injection |
| real provider support | ❌ 未覆盖 |
| current maturity | **dogfood ready** (fake only) |
| overclaim risk | 低 |
| next action | 后续可扩展到 real provider |

### B.24 Command Router / CLI Meta-Command

| 字段 | 值 |
|------|-----|
| capability name | Command router / CLI meta-command |
| user-facing status | ✅ show memories / forget / show subagents / delegate / NL delegation |
| internal/runtime status | `agent/cli_commands.py` (detect + render); `core.chat()` (service call + orchestration) |
| evidence files/tests | `test_cli_commands.py` (architectural) |
| fake/local support | ✅ |
| real provider support | ✅ (不经过 LLM) |
| current maturity | **production-like** |
| overclaim risk | 低 |
| next action | 维持当前分工（不再继续薄化） |

### B.25 Dogfood Checklist/Report

| 字段 | 值 |
|------|-----|
| capability name | Dogfood checklist/report |
| user-facing status | ✅ `docs/dogfood/local-manual-dogfood-checklist.md` |
| internal/runtime status | `scripts/dogfood_checklist_executor.py` |
| evidence files/tests | `docs/dogfood/local-manual-dogfood-report.md` (Fake 9/9, Real 5/6) |
| fake/local support | ✅ |
| real provider support | ✅ opt-in |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 合并重复报告（见 Section F） |

### B.26 Safety / Approval / Confirmation

| 字段 | 值 |
|------|-----|
| capability name | Safety / approval / confirmation |
| user-facing status | ✅ tool confirmation_required, memory confirmation, plan confirmation |
| internal/runtime status | `agent/confirmation/`, `agent/confirm_handlers.py`, `agent/pending_confirmation_dispatch.py` |
| evidence files/tests | `test_confirmation_flow.py`, `test_tool_branch_confirmation_required.py` |
| fake/local support | ✅ |
| real provider support | ✅ |
| current maturity | **dogfood ready** |
| overclaim risk | 低 |
| next action | 维持 |

### B.27 Provider Tool-Call Compatibility

| 字段 | 值 |
|------|-----|
| capability name | Provider tool-call compatibility |
| user-facing status | N/A (infrastructure) |
| internal/runtime status | `docs/architecture/provider-tool-call-compatibility-ad.md` — accepted |
| evidence files/tests | `test_tool_name_normalization.py`, `test_normalize_anthropic_response.py`, `test_model_call.py` |
| fake/local support | N/A |
| real provider support | ✅ kimi-k2.5 tool_use confirmed |
| current maturity | **production-like** |
| overclaim risk | 低 |
| next action | 维持；suffix matching 作为通用防御层 |

### B.28 Hook/Lifecycle Extension

| 字段 | 值 |
|------|-----|
| capability name | Hook/lifecycle extension |
| user-facing status | ❌ 未实现 |
| internal/runtime status | turn-end hook 已承载 Phase 1 dispatcher，可作为 hook 系统参考实现 |
| evidence files/tests | 无独立 hook 测试 |
| fake/local support | N/A |
| real provider support | N/A |
| current maturity | **not started** |
| overclaim risk | 低 — 明确标记 deferred |
| next action | **冻结**；仅保留 turn-end hook，不开发通用 hook 系统 |

### B.29 Real Provider Conversation UX

| 字段 | 值 |
|------|-----|
| capability name | Real provider conversation UX |
| user-facing status | 🟡 基本可用但 prompt 敏感 |
| internal/runtime status | `model_call.py` → provider.create() / stream() |
| evidence files/tests | dogfood reports |
| fake/local support | N/A |
| real provider support | ✅ kimi-k2.5 验证通过 |
| current maturity | **dogfood ready with caveat** |
| overclaim risk | 低 |
| next action | system prompt tool-use guidance 优化 |

### B.30 Documentation/Onboarding

| 字段 | 值 |
|------|-----|
| capability name | Documentation/onboarding |
| user-facing status | ✅ `--help`, `help` 命令, README, docs/ 目录 |
| internal/runtime status | README, docs/README.zh.md, onboarding flow |
| evidence files/tests | `tests/smoke/test_first_usable_task_e2e.py` |
| fake/local support | ✅ |
| real provider support | ✅ opt-in guide |
| current maturity | **dogfood ready** |
| overclaim risk | 🟡 中 — 文档数量过大（~200 .md 文件），有大量过时内容 |
| next action | 文档归档和整合（见 Section I） |

---

## C. Industry Comparison

| # | Industry Capability | Common Expectation | First Agent Current | Gap | Severity | Build Now? | Why/Why Not |
|---|---------------------|-------------------|---------------------|-----|----------|------------|-------------|
| 1 | Agent loop / runner | 可靠的 main loop + stop_reason 分派 | ✅ unified runtime flow 成熟 | 无 | — | — | — |
| 2 | Model provider abstraction | 多 provider 统一接口 | ✅ Provider protocol + 5 种 adapter | 无 | — | — | — |
| 3 | Tool calling | 工具注册、调用、结果返回 | ✅ Tool Pipeline 4-stage L3 complete | 无 | — | — | — |
| 4 | Structured tool call normalization | 跨 provider tool_use 归一化 | ✅ ToolUseBlock 统一表示 + suffix matching | 无 | — | — | — |
| 5 | Handoffs / subagents | 任务委托给子代理 | 🟡 L0 deterministic only | L1+ real delegation 未实现 | **P2** | 否 | L1 AD 已定，但 L0 满足当前 MVP |
| 6 | Guardrails / policy | 工具/操作安全策略 | ✅ ToolGate 4 dispositions, SubAgentPolicy, Memory governance | 无 | — | — | — |
| 7 | Human-in-the-loop | 高风险操作需人工确认 | ✅ confirmation_required + plan confirmation + memory confirmation | 无 | — | — | — |
| 8 | Session/state/memory | 跨 turn 状态管理 | ✅ Checkpoint + Memory store + State machine | 无 | — | — | — |
| 9 | Durable execution / checkpoint | 断点续跑 | ✅ Checkpoint save/resume L3 complete | 无 | — | — | — |
| 10 | Streaming / progress | 逐字输出 + 进度事件 | 🟡 Fake deterministic chunking; Real provider-dependent | Real provider streaming UX 不统一 | **P2** | 否 | 当前 progress/event UX 已足够；真实 streaming 依赖 provider |
| 11 | Tracing / observability | 可观测性：trace + evidence | ✅ runtime trace path verified; evidence model 完善 | 无 runtime trace UI | **P3** | 否 | trace 是观测基础设施，不是产品功能 |
| 12 | Hooks / lifecycle callbacks | 可扩展的 hook 系统 | 🟡 turn-end hook only | 通用 hook 系统未实现 | **P3** | 否 | turn-end hook 已足够；通用 hook 系统不是当前需求 |
| 13 | Multi-agent orchestration | 多 agent 协作 | ❌ | 完全未实现 | **P4** | 否 | 不在 scope |
| 14 | Real provider dogfood / eval | 真实场景验证 | 🟡 手动 dogfood pass; tool_use prompt 敏感 | 自动化 eval 缺失 | **P3** | 否 | 当前手动 dogfood 足够 |
| 15 | Permission / sandbox | 安全沙箱 | 🟡 L0 local only; no sandbox | 无 process/filesystem sandbox | **P2** | 否 | L0 不需要；L1+ 需要但未到 |
| 16 | Deployment / packaging | 一键安装/启动 | 🟡 `pip install -r requirements.txt` | 无 pip package, 无 Docker, 无 binary | **P4** | 否 | 当前 developer tool 定位不需要 |
| 17 | User onboarding | 新用户 5 分钟上手 | ✅ `--help` + `help` 命令 + manual dogfood checklist | UX 仍偏技术向 | **P3** | 否 | 当前 developer audience 足够 |

**必须补齐**: 无（当前无阻塞性能力缺失）

**可后置**: L1+ SubAgent, real provider streaming UX polish, automated eval

**不该现在做**: Hook 系统, multi-agent orchestration, deployment/packaging, RAG/embedding

**当前项目不适合做**: SaaS, Web UI, plugin marketplace, 通用 agent framework

---

## D. Architecture Integrity Audit

### D.1 主流程验证

```
query/event
  → core.chat()                              ✅ 唯一入口
  → CLI meta-command detection               ✅ 薄层，无副作用
  → memory evaluation                        ✅ pre-loop
  → _resolve_provider_evidence_metadata()    ✅ provider-agnostic
  → _run_main_loop()
    → loop.run_main_loop(dependencies)
      → call_model()                         ✅ provider abstraction
      → dispatch_model_output()              ✅ 统一分派
      → _try_phase1_turn_end_runtime_action()
        → dispatcher.route_from_runtime_loop() for EACH RuntimeAction ✅ 独立 try/except
      → _emit_run_summary()                  ✅ action_log 统计
```

### D.2 审计矩阵

| # | 问题 | 判定 | 证据 |
|----|------|------|------|
| 1 | 主流程是否仍然成立？ | **PASS** | `chat()` → `loop.py` → Tool Pipeline 唯一路径 |
| 2 | 是否有第二条 runtime？ | **PASS** | `route_from_runtime_loop()` 是唯一 dispatcher 入口；CLI meta-command 不创建独立 runtime |
| 3 | 是否有 fake/real 分裂？ | **PASS** | FakeProvider/RealProvider 共享同一 `chat()` 路径，仅 provider adapter 不同 |
| 4 | 是否有 dogfood-only path 冒充产品主路径？ | **PASS** | Dogfood scripts 通过 `core.chat()` 调用，不绕过 runtime |
| 5 | 是否有 direct handler / dispatcher / adapter 冒充 E2E？ | **PASS** | Classification rules 明确区分 `real_core_loop_runtime_e2e` vs `harness_runtime_e2e` |
| 6 | command router 是否变成第二条 runtime？ | **PASS** | `cli_commands.py` 只做 detect/render，副作用仍在 `core.chat()` 内 |
| 7 | FakeProvider 是否承担了过多智能职责？ | **PASS** (需冻结) | 4 策略优先级 tool_use matching 当前适度；禁止继续增强 |
| 8 | Provider adapter 是否污染 Tool Pipeline？ | **PASS** | Tool Pipeline 完全 provider-agnostic；normalization 在 provider 层完成 |
| 9 | SubAgent 是否仍是有限介入点？ | **PASS** | L0 边界严格执行（不调 provider、不执行工具、不 spawn 进程）；L1 AD 定义替换策略 |
| 10 | Memory 是否边界清楚？ | **PASS** | Path A (injection) vs Path B (dispatcher evidence) 互补不竞争；AD 已裁决 |
| 11 | Trace / Streaming / Progress 是否是治理层和输出层？ | **PASS** | 三者都是 observation/output layer，不参与 runtime decision |

**总结**: 12 项检查全部 PASS。Unified Runtime Flow 架构完整性良好。

---

## E. Code Quality / Maintainability Audit

### E.1 模块边界分析

| 模块 | 行数 | 评估 |
|------|------|------|
| `agent/core.py` | 1137 | 🟡 仍然偏重。CLI 命令检测/渲染已提取，但 chat() 内仍有 ~200 行编排胶水。进一步拆分可能违反架构契约（副作用操作的正确位置在 orchestrator 中）。当前状态可接受。 |
| `agent/loop.py` | 816 | 🟡 `_try_phase1_turn_end_runtime_action()` 占 ~500 行，是最长的单个函数。每个 RuntimeAction 的独立 try/except 块结构清晰但冗长。可考虑表驱动 dispatch 但当前显式结构更可审计。不紧急。 |
| `agent/cli_commands.py` | 277 | ✅ 职责清晰：detect（纯字符串匹配）+ render（纯格式化）。架构契约良好。 |
| `agent/runtime_integration/schema.py` | 172 | ✅ 紧凑、职责单一。RuntimeActionType 枚举定义清晰。 |
| `agent/runtime_integration/dispatcher.py` | ~545 | ✅ 核心分发逻辑集中；provenance 防伪机制在此。 |
| `agent/model_call.py` | 108 | ✅ 紧凑、职责单一。Streaming/non-streaming 分支清晰。 |
| `config.py` | 260 | 🟡 SYSTEM_PROMPT 硬编码 67 行中文 prompt。功能上合理（需要确定性 system prompt），但应该移到独立的 prompt 文件而非混在 config 中。 |
| `agent/provider/fake_provider.py` | ~432 | 🟡 行数适中但 4 策略 tool_use matching 占不少篇幅。不应继续增强。 |

### E.2 依赖方向

```
core.py → loop.py → model_call.py → provider/
core.py → runtime_integration/ (dispatcher, schema, handlers)
core.py → memory_runtime.py → memory_store.py
core.py → subagent_system/ (delegation, registry)
core.py → cli_commands.py (detect/render only)
```

依赖方向总体单向向下。未发现循环依赖。

### E.3 大文件/上帝模块

- `agent/core.py` (1137 行): 已在可接受范围。`chat()` 函数约 400 行，其中 CLI meta-command 处理、memory evaluation、provider metadata resolution、loop context construction 各自是清晰的段落。进一步拆分可能违反架构契约。
- `agent/loop.py` (816 行): `_try_phase1_turn_end_runtime_action()` 是唯一偏长的函数（~500 行），但每个 RuntimeAction 的独立 try/except 块结构在审计上是有价值的。

### E.4 贫血抽象

- `agent/provider/legacy_adapter.py` (ProviderBackedClient): 一个薄 facade。价值有限但作为 legacy planner/compress 的兼容桥可保留。标注为 deprecated candidate。

### E.5 机械拆文件

Memory 系统有 ~30 个文件，部分属于 consolidation pipeline（`memory_consolidation.py`, `memory_consolidation_engine.py`, `memory_consolidation_llm.py`, `memory_consolidation_loader.py`, `memory_consolidation_pipeline.py`, `memory_consolidation_review.py` — 6 个文件）。Consolidation 当前只有 dispatch path verified，business operation deferred。这是 AI 自动开发可能产生的"过度前瞻"模式——搭了完整的 pipeline 骨架但无法验证核心功能。

### E.6 重复逻辑

- `core.chat()` 中 CLI delegate 和 NL delegation 路径有 ~20 行几乎相同的 run_summary emit 代码。这是合理的重复（两个路径的生命周期点相同但触发方式不同），不应过早抽象。

### E.7 命名问题

- `_looks_like_*` 别名（通过 `cli_commands.py` import 兼容）：向后兼容机制，标记了 `noqa: F401`。可接受但应标注为 deprecated，给一个版本周期后删除。
- `_safe_noop` / `_confirmable_noop`: 工具名不够直观，但注释充分。

### E.8 测试过度绑定

未发现重大问题。L3 测试覆盖了完整的 dispatch 路径。Contract tests 保护了边界。

### E.9 Prompt/Config 硬编码

- `config.py` 中 `SYSTEM_PROMPT` (67 行): 建议移到 `agent/prompts/system_prompt.py` 或类似独立文件。
- `cli_commands.py` 中 NL delegation 触发词 (中英文): 合理硬编码——这是 deterministic matching，不应外部化。

### E.10 Schema/State 字段漂移

- `RuntimeActionType` enum: 12 个值，全部有对应 handler 注册。`STREAMING_EVENT` 之前被误标为 inactive，实际已激活。无死字段。
- `TaskState`: 字段随 checkpoint 演进，有对应 migration。当前基线一致。

### E.11 Dead Code / Unused Code

- `agent/memory_consolidation_llm.py`: real LLM consolidation — deferred。代码存在但被 gate 保护。
- `agent/provider/legacy_adapter.py` (ProviderBackedClient): 薄 facade，价值递减。
- 多个 `_dogfood_*.py` scripts 在 `scripts/` 下：部分为历史脚本。

### E.12 文档与代码一致性

部分 README 中描述的阶段（如 "v0.9.x deep stabilization"）与当前实际状态（post-stabilization, manual-dogfood-ready）有时间差。ROADMAP.md 的完成状态表可能与实际 commit 历史不完全同步。

### E.13 STREAMING_EVENT: 应保留、实现、还是删除？

**保留**。当前已激活（`loop.py:579-594`），per-event evidence collection 有价值。不删除、不再增强。

### E.14 MEMORY_RECALL 双路径: 清晰还是困惑？

**清晰**。AD 明确裁决了 Path A (pre-loop injection, user-visible) 和 Path B (turn-end dispatcher evidence, audit-visible) 的分工。不需要重新讨论。

### E.15 Provider Tool-Call Compatibility

AD 已 accepted。ToolUseBlock 统一表示 + suffix matching 通用防御层。架构合理，不需要额外抽象层。

### E.16 Dogfood Scripts 位置

✅ Dogfood scripts 在 `scripts/` 目录，通过 `core.chat()` 调用，不污染 runtime。架构正确。

---

## F. Redundancy / Cut List

### F.1 Cut/Merge/Freeze Table

| # | Item | Type | Evidence | Risk if Kept | Risk if Removed | Recommended Action | Safe-to-Auto-Run |
|---|------|------|----------|-------------|----------------|-------------------|-----------------|
| 1 | STREAMING_EVENT (误标 inactive) | **keep** | `loop.py:579-594` 已激活 | 之前审计误判 inactive，但本身无风险 | 删除 per-event evidence | 维持激活状态，不再标记为 inactive | yes |
| 2 | `main.py demo` 路径 | **keep with warning** | `agent/local_demo.py` 独立 adapter | 新用户可能误以为是完整 runtime 路径 | 删除后无快速 demo 入口 | 保留但 README 突出 "不经过 Tool Pipeline" 的诚实声明 | yes |
| 3 | Memory Consolidation pipeline (6 files) | **freeze** | dispatch path verified; business operation deferred | 代码膨胀、维护负担、给人"已完成"的错觉 | 删除后 dispatch path evidence 丢失 | 冻结：不再新增 consolidation 代码，等 real LLM 可用后评估 | yes (freeze only) |
| 4 | `agent/provider/legacy_adapter.py` | **downgrade** | ProviderBackedClient 薄 facade | 维护负担 | legacy planner/compress 可能断裂 | 标注 deprecated；下一个大版本移除 | yes |
| 5 | MEMORY_RECALL dual-path AD re-discussion | **keep as decided** | AD 已裁决 | 重新讨论徒增 confusion | 强行统一 Path A/B 会引入不必要耦合 | 维持决定 | N/A |
| 6 | SubAgent L0→L1 AD (implementation) | **freeze** | AD 已定，不实现代码 | 过早实现 L1 会引入 provider dependency | 删除 AD 会丢失架构方向 | 冻结：维持 AD 文档，不实现代码 | N/A (decision only) |
| 7 | Hook system | **freeze** | deferred; turn-end hook 已足够 | 过早实现通用 hook 会过度工程 | 删除 deferred 记录 | 冻结：不在当前阶段设计/实现 | N/A |
| 8 | MCP confirmation="always" | **freeze** | product decision required | 持续阻塞其他 MCP 工作 | 删除 MCP 支持 | 冻结：等产品决策；不阻塞其他工作 | N/A |
| 9 | `config.py` SYSTEM_PROMPT 硬编码 | **keep** (refactor candidate) | 67 行中文 prompt | 混合 config 和 prompt 内容 | 迁移可能破坏依赖此 prompt 的测试 | 维持；如果后续 prompt engineering 频繁，再提取为独立文件 | yes |
| 10 | `_looks_like_*` 向后兼容别名 | **downgrade** | `core.py` L49-62 | 增加 import 噪音 | 删除后破坏现有测试 import | 标注 deprecated；给 1 个版本周期后清理 | yes |
| 11 | Dogfood reports 重复 | **merge** | 3 个 JSON report + 3 个 MD report | 信息碎片化 | 合并可能丢失历史 | 合并 `local-manual-dogfood-report.md` 和 `GLOBAL_REAL_API_DOGFOOD_REPORT.md`；JSON reports 保留作为自动化证据 | yes |
| 12 | v0.X 历史文档 (50+ docs) | **archive** | `docs/V0_*.md`, `docs/V0_*_PLAYBOOK.md` 等 | 文档膨胀、新开发者困惑 | 删除可能丢失历史上下文 | 归档到 `docs/archive/v0.x/`；保留 `docs/archive/README.md` 索引 | yes |
| 13 | `docs/rfc/archived/` 下 8 个 MEMORY 文档 | **keep archived** | 已在 archived 子目录 | 无 — 已在正确位置 | N/A | 维持 | N/A |
| 14 | `docs/review/` 下 dogfooding session 文档 | **archive** | 历史 dogfood 记录 | 新开发者误以为相关 | 丢失 dogfood 历史 | 归档到 `docs/archive/dogfood-history/` | yes |
| 15 | `docs/specs/` 下 ~30 个 SPEC/TDD/IMPLEMENTATION_PLAN | **keep** | L3 evidence 的文档证据 | 无 — 与测试互为可追溯证据链 | 删除后 L3 evidence 失去可追溯性 | 维持 | N/A |
| 16 | `agent/memory_consolidation_llm.py` | **freeze** | real LLM deferred | 代码存在但可能给人"已完成"的错觉 | 删除后 dispatch path 依赖可能断裂 | 冻结；不删除，不增强 | yes |
| 17 | `agent/provider/streaming.py` `collect_stream_response()` | **keep** | 错误时 raise exception | fail-closed 语义需要调用方理解 | 删除后 streaming error 不可检测 | 维持；文档化 fail-closed 契约 | N/A |
| 18 | Demo-only NL delegation fixtures | **keep** | `cli_commands.py:detect_nl_delegation()` | 关键词匹配不应继续扩展为 full NLU | 删除后用户失去便捷委托入口 | 维持当前 3 中文 + 3 英文 trigger；不扩展 | yes |
| 19 | `scripts/dogfood_phase6_llm_consolidation.py` | **freeze/archive** | 依赖 real LLM，deferred | 混淆 — 给人 consolidation 已可用的错觉 | 低 — 只是 script | 标注为 deferred/experimental；不删除 | yes |
| 20 | FakeProvider 4-strategy tool_use decision | **freeze enhancements** | 当前 deterministic matching 已足够 | 继续增强会变成 fake planner | N/A | **冻结**：禁止新增匹配策略、禁止让 FakeProvider 成为复杂 planner | N/A (禁止增强) |

### F.2 特别判断

1. **STREAMING_EVENT**: **保留**。已激活，per-event evidence collection 有价值。
2. **main.py demo**: **保留但加强诚实声明**。独立 demo adapter 有快速验证价值，但 README 必须明确标注"不经过完整 Tool Pipeline"。
3. **Dogfood reports**: 建议合并 MD reports，保留 JSON reports 作为自动化证据。
4. **MEMORY_RECALL dual-path AD**: **不困惑**。AD 裁决清晰。不需要重新讨论。
5. **SubAgent L0/L1 方向**: **不过度工程**。L1 AD 定义清晰的替换策略，不实现代码。架构方向正确。
6. **Hook system**: **继续 deferred**。turn-end hook 已承载所有当前需求。
7. **MCP confirmation="always"**: **继续 product-decision-blocked**。不影响其他工作。
8. **FakeProvider decision layer**: **已足够，禁止继续增强**。当前 4 策略匹配覆盖所有 demo 场景。
9. **Demo-only commands**: **无需要砍掉的**。当前 CLI 命令都有实际用户价值。
10. **过时 roadmap 状态**: ROADMAP.md 需要与当前实际状态同步。

---

## G. Product Usability Audit

### G.1 用户旅程

| 步骤 | 当前状态 | 期望 | Gap | 建议 |
|------|----------|------|-----|------|
| 安装/启动 | ✅ `pip install -r requirements.txt` → `python main.py` | 同当前 | 无 | 维持 |
| 对话 | ✅ FakeProvider echo; Real provider 自然回复 | 同当前 | Real: prompt sensitive | system prompt optimization |
| 真实 provider 使用 | ✅ opt-in via env var | 同当前 | 无 | 维持 |
| 工具使用 | ✅ deterministic keyword match (Fake); 真实 tool_use (Real) | 自然语言触发工具 | Real: prompt sensitive | system prompt tool guidance |
| 看到工具结果 | ✅ tool_result_visible RuntimeEvent | 同当前 | 无 | 维持 |
| 管理 memory | ✅ show/forget by ID/content | 同当前 | 无 | 维持 |
| 感知 memory recall | 🟡 "已加载 N 条相关记忆" 消息 | 对话中自然引用 memory | 依赖 system prompt injection | 维持当前 Path A 方案 |
| 委托 subagent | ✅ CLI + NL 两种方式 | 同当前 | NL 触发词有限 | 维持当前 3+3 触发词 |
| 看到 progress | ✅ subagent/memory events | tool started/completed events | tool execution 进度 | P3 — 后续增加 |
| 查看 run summary | ✅ 每轮结束 emit | 同当前 | 无 | 维持 |
| 知道 fake vs real | ✅ 启动屏 + `--help` 诚实声明 | 同当前 | 无 | 维持 |
| 安全 dogfood | ✅ Fake 路径零风险 | 同当前 | 无 | 维持 |
| 知道哪些不是产品能力 | ✅ "当前不支持什么" section | 同当前 | 需与代码状态同步 | 更新 README |

### G.2 总体评估

**当前用户旅程**: 开发者可以安装 → 用 FakeProvider 本地对话 → 使用 demo 工具 → 管理记忆 → 委托子代理 → 查看 run summary。完整但克制。

**最大 UX 差距**: Real provider 下工具调用的 prompt sensitivity。用户说"帮我创建一个 demo note"时，kimi-k2.5 可能用文本回复而非调用 write_demo_note。

**推荐下一个 UX 改进**: System prompt tool-use guidance 优化（非代码改动，prompt engineering）。

---

## H. Test / Gate / Evidence Audit

### H.1 测试体系评估

| 维度 | 评估 | 详情 |
|------|------|------|
| Full pytest | ✅ 可信 | 3331 passed, 18 skipped, 0 failed |
| Focused tests | ✅ 覆盖用户路径 | `test_memory_user_facing.py`, `test_subagent_user_facing.py`, smoke tests |
| L1/L2/L3 evidence 诚实 | ✅ | Evidence label precision 规则明确；dispatch path verified ≠ business operation complete |
| Dogfood tests 误导风险 | ✅ 低 | Dogfood scripts 通过 `core.chat()` 调用，不绕过 runtime |
| Real API tests skip/gate | ✅ 正确 | 18 skipped 全部有明确 opt-in env var |
| Tail/head/truncated output 误判 | ✅ 无 | 未发现 |
| 过度 mock | ✅ 无 | L3 测试使用真实 dispatcher chain |
| Direct handler tests 冒充 E2E | ✅ 无 | Classification rules 严格执行 |
| 缺失 contract tests | 🟡 provider swap test | 切换 provider 时的行为一致性 contract 缺失 |

### H.2 Strongest Tests

- `tests/runtime_integration/test_tool_pipeline_l3_completion.py` — Tool Pipeline 完整闭环
- `tests/runtime_integration/test_memory_propose_l3.py` — Memory retain 完整 evidence chain
- `tests/runtime_integration/test_subagent_l3.py` — SubAgent empty + non-empty registry
- `tests/test_chat_provider_injection.py` — Provider injection contract
- `tests/smoke/test_first_usable_task_e2e.py` — 用户路径 smoke test

### H.3 Weakest Tests

- Memory consolidation tests: dispatch path verified 但 business operation deferred。测试覆盖了 handler 路径但没有验证真实 consolidation 效果。
- NL delegation tests: 测试了 3+3 固定触发词，但没有验证触发词的边界情况（如触发词在句中而非句首）。

### H.4 Missing Tests

- Provider swap contract test: 切换 provider type 时的行为一致性
- Real provider tool_use regression test: opt-in, CI 中不跑但可手动触发
- Memory recall user-visible effect test: 验证 "已加载 N 条相关记忆" 在何种场景下出现

### H.5 Tests to Delete or Rewrite

- **无需要删除的测试**。所有 3331 tests 都有明确目的。
- `test_memory_consolidation_llm.py` (6 skipped): 全部需要 real LLM opt-in。合理 skip，不删除。

### H.6 Gates

**Keep**:
- `git diff --check` (whitespace)
- `ruff check agent tests scripts` (lint)
- `pytest -x -q` (full gate)
- `HOME=/private/tmp` isolation for MCP tests

**Add**:
- Provider tool_use regression gate (opt-in script, 不在 CI 中)
- Documentation consistency gate (check README claims vs actual code state)

---

## I. Documentation Audit

### I.1 文档统计

- 总计 ~200 个 .md 文件
- docs/ 下有 28 个子目录
- 根目录 README.md (311 lines) — 信息密度高但结构复杂
- 文档语言混用: zh.md / EN.md / 无后缀 .md

### I.2 各类文档评估

| 文档类别 | 评估 | 建议 |
|----------|------|------|
| README.md | 🟡 信息丰富但过长 (311 lines)；部分状态描述滞后 | **update**: 更新阶段标签、SubAgent 状态、streaming 状态 |
| docs/ROADMAP.md | 🟡 需要与当前实际状态同步 | **update**: 清除已完成项、更新状态标签 |
| docs/design/*.md | ✅ 5 个设计文档/AD，质量高 | **keep** |
| docs/specs/*/ | ✅ ~30 个 SPEC/TDD/Plan，是 L3 evidence 的一部分 | **keep** |
| docs/audit/*.md | 🟡 6 个审计文档，无索引 | **add**: `docs/audit/README.md` 索引 |
| docs/dogfood/*.md | 🟡 3 个 MD report + 2 个 plan + 1 个 checklist + 2 个 JSON | **merge**: MD reports; **keep**: JSON + checklist |
| docs/plans/*.md | ✅ 3 个活跃 + 5 个历史 plan | **archive**: 日期命名的历史 plan 移到 `docs/archive/plans/` |
| docs/implementation-notes/*.md | 🟡 20 个 notes，部分已过时 | **archive**: 已完成的 spec 对应的 notes |
| docs/V0_*.md | 🟡 30+ 个版本化文档，大部分是历史 | **archive**: 移到 `docs/archive/v0.x/` |
| docs/rfc/archived/ | ✅ 已在正确位置 | **keep** |
| docs/real-e2e/ | ✅ 3 个核心文档 | **keep** |
| docs/dev/ | ✅ 2 个工程流程文档 | **keep** |
| docs/refactor/ | 🟡 v0.9.x 文档可能与当前主分支状态不同步 | **update or archive** |

### I.3 推荐行动

| 行动 | 文档 |
|------|------|
| **keep** | README.md, docs/design/*.md, docs/specs/*/, docs/dev/*.md, docs/real-e2e/*.md, docs/rfc/*.md (canonical), docs/dogfood/local-manual-dogfood-checklist.md, docs/audit/global-agent-capability-architecture-audit-2026-05-25.md |
| **update** | README.md (阶段标签), docs/ROADMAP.md (状态同步), docs/00-overview/CAPABILITY_MATRIX.zh.md |
| **archive** | docs/V0_*.md → `docs/archive/v0.x/`, docs/plans/2026-05-2*-*.md → `docs/archive/plans/`, docs/review/DOGFOODING_*.md → `docs/archive/dogfood-history/`, docs/implementation-notes/ (已完成的 spec 对应 notes) |
| **merge** | docs/dogfood/local-manual-dogfood-report.md + docs/dogfood/GLOBAL_REAL_API_DOGFOOD_REPORT.md |
| **add** | docs/audit/README.md (审计索引), docs/archive/README.md (如有需要更新) |
| **delete candidate** | 无强制删除；如有完全被替代的历史 smoke playbook 可考虑 |

---

## J. Scores

| Dimension | Score (0-10) | Reason |
|-----------|-------------|--------|
| Runtime architecture | **9** | Unified runtime flow 设计严密，provenance 防伪机制是项目最强设计决策。扣 1 分因为 `_try_phase1_turn_end_runtime_action()` 冗长。 |
| Code maintainability | **7** | 模块边界清晰，命名一致。扣分在 core.py 仍偏重 (1137L)、memory 系统文件过多、config.py prompt 硬编码。 |
| Test reliability | **9** | 3331 tests, 0 failures, skip 全部合理。L3 evidence 标签精确。扣 1 分因为 consolidation 测试覆盖了 dispatch path 但 business operation deferred（诚实但给人错觉）。 |
| Tool-use capability | **8** | Tool Pipeline L3 complete，4 种 disposition 全部验证。扣分在 real provider tool_use prompt sensitivity。 |
| Real provider readiness | **6** | Opt-in mechanism 完善，kimi-k2.5 tool_use confirmed。扣分在 tool_use 触发不一致、无 provider swap evaluation。 |
| Memory UX | **7** | show/forget/confirmation 流程完整，recall 有用户通知。扣分在 recall 注入对用户只是数字，无直观"Agent 记得我"体验。 |
| SubAgent UX | **6** | CLI + NL delegation 可用，progress events 完整。扣分在 L0 deterministic summary 信息量有限、NL 触发词只有 3+3 固定模式。 |
| Streaming/progress UX | **5** | progress events (subagent/memory) 完善，但 Fake streaming 是 debug/demo chunking，Real streaming UX 不统一。STREAMING_EVENT 是 internal evidence collection，用户不可见。 |
| Trace/debug UX | **6** | run_summary 有结构化信息，trace sink 设计灵活。扣分在无可视化 trace UI、trace 只是 opt-in infrastructure。 |
| Safety/approval | **8** | Tool confirmation, memory confirmation, plan confirmation 三层保护。provenance 防伪。扣分在 MCP confirmation="always" product decision pending。 |
| Docs/onboarding | **5** | README 信息丰富但太长，~200 个 .md 文档散落，大量 v0.x 历史文档未归档，语言混用。`--help` / `help` onboarding 质量高。 |
| Product usability | **6** | 核心功能可用 — 对话、工具、记忆、子代理 — 但 UX 克制，real provider 体验不一致。开发者友好但非消费者产品。 |
| **Overall** | **6.8** | 架构和测试纪律是亮点 (8-9 分)。产品可用性、文档、real provider readiness 是短板 (5-6 分)。项目健康但需要瘦身和聚焦。 |

---

## K. Top 20 Findings

| ID | Severity | Category | Finding | Evidence | Impact | Recommendation | Safe-to-Auto-Run | Fix Before Next Big Loop? |
|----|----------|----------|---------|----------|--------|----------------|-----------------|--------------------------|
| F1 | **P1** | capability gap | Real provider tool_use 对 prompt 措辞敏感 — kimi-k2.5 在 natural language 下不主动触发工具 | `local-manual-dogfood-report.md` Step 3 CONCERN | 用户说"帮我建一个 note"时得不到工具调用 | System prompt 增加显式 tool-use guidance；验证效果后更新 dogfood | no (需要真实 API 验证) | yes |
| F2 | **P2** | architecture debt | `_try_phase1_turn_end_runtime_action()` 500 行，是项目最长单函数 | `loop.py:101-607` | 维护负担；新增 RuntimeAction 需手动加 try/except 块 | 可考虑表驱动 dispatch，但当前显式结构更可审计。不紧急 | yes | no |
| F3 | **P2** | documentation | docs/ 目录 ~200 个 .md 文件，大量 v0.x 历史文档未归档 | `docs/V0_*.md` 30+ files | 新开发者困惑；信息检索困难 | 归档 v0.x 文档到 `docs/archive/v0.x/`；更新 ROADMAP.md 状态 | yes | yes |
| F4 | **P2** | redundancy | Memory Consolidation pipeline (6 files) 只有 dispatch path verified，business operation deferred | `agent/memory_consolidation*.py` | 代码膨胀；给人"已完成"的错觉 | 冻结：不新增 consolidation 代码；添加模块级注释说明现状 | yes | yes |
| F5 | **P2** | product gap | Real provider streaming UX 不统一 — Fake deterministic chunking vs Real provider-dependent | `model_call.py` streaming/non-streaming | 用户在不同 provider 下体验不一致 | 接受为已知 tradeoff；文档诚实说明 | N/A | no |
| F6 | **P2** | documentation | README.md 中 "v0.9.x deep stabilization" 阶段标签滞后 | README.md L11 | 外部读者误以为项目仍在 stabilization | 更新 README 阶段标签为 "manual-dogfood-ready" | yes | yes |
| F7 | **P3** | code quality | `config.py` 中 SYSTEM_PROMPT (67 行中文) 硬编码在配置文件中 | `config.py:206-259` | 配置与 prompt 内容混在一起 | 维持；如果 prompt engineering 频繁再提取 | yes | no |
| F8 | **P3** | redundancy | Dogfood reports 重复 — 3 个 MD reports + 3 个 JSON reports | `docs/dogfood/*.md`, `docs/dogfood/*.json` | 信息碎片化 | MD reports 合并；JSON reports 保留作为自动化证据 | yes | no |
| F9 | **P3** | test gap | 缺少 provider swap contract test | 无对应测试文件 | 切换 provider 时行为一致性未 contract-verified | 新增 opt-in contract test | yes (fake path) | no |
| F10 | **P3** | code quality | `_looks_like_*` 向后兼容别名增加 import 噪音 | `core.py:49-62` | 微小维护负担 | 标注 deprecated；给 1 个版本周期后清理 | yes | no |
| F11 | **P3** | documentation | STREAMING_EVENT 在之前审计中被误标为 inactive | `big-loop-independent-audit-2026-05-25.md` Issue 1 | 误导后续审计；实际已激活 | 本审计已纠正 | N/A | N/A |
| F12 | **P3** | architecture debt | `agent/provider/legacy_adapter.py` ProviderBackedClient 薄 facade 价值递减 | `legacy_adapter.py` | 维护负担 | 标注 deprecated | yes | no |
| F13 | **P3** | product gap | NL delegation 触发词只有 3+3 固定模式，覆盖有限 | `cli_commands.py:122-173` | 用户用不匹配的措辞时委托失败 | 维持当前覆盖；不扩展（扩展就是做 fake NLU planner） | no | no |
| F14 | **P3** | documentation | ROADMAP.md 完成状态表与实际 commit 历史可能不完全同步 | ROADMAP.md | 误导 roadmap 读者 | 以 git log 为准更新 ROADMAP.md | yes | yes |
| F15 | **P4** | redundancy | `scripts/dogfood_phase6_llm_consolidation.py` 依赖 deferred real LLM | 文件存在但无法运行 | 混淆 | 标注为 deferred/experimental | yes | no |
| F16 | **P4** | documentation | 文档语言混用 — zh.md / EN.md / 无后缀 .md — 无一致性约定 | 全局 | 微小的可读性问题 | 不强求统一；新文档优先用 zh.md | N/A | no |
| F17 | **P4** | test gap | Memory consolidation tests 覆盖 handler 路径但不验证真实 consolidation 效果 | `test_memory_consolidate_l3.py` | 测试给人以 consolidation 可用的错觉 | 维持；文档标注 "dispatch path only, business operation deferred" | N/A | no |
| F18 | **P4** | documentation | `docs/dogfood/` 缺少 README 索引 | 目录存在 | 读者不知道哪些是 active vs historical | 新增 `docs/dogfood/README.md` | yes | no |
| F19 | **P2** | architecture | FakeProvider 4-strategy tool_use matching 不应继续增强 | `fake_provider.py:_resolve_tool_use()` | 继续增强会变成 fake planner，违反设计原则 | **冻结增强**；添加注释说明当前覆盖已足够 | N/A | no |
| F20 | **P3** | architecture | `main.py demo` 路径不经过完整 Tool Pipeline — 需要在 README 中更突出声明 | `agent/local_demo.py`, README.md L97 | 新用户可能误解 demo 路径的完整性 | README 中已有声明但可以更突出 | yes | no |

---

## L. Recommended Next Big Loops

### Priority 1: Documentation Consolidation & Archive (文档瘦身)

| Aspect | Detail |
|--------|--------|
| **name** | Documentation consolidation and archive |
| **why now** | 文档膨胀是最容易修复的系统性问题；~200 .md 文件中有大量历史内容 |
| **user outcome** | 新开发者能在 10 分钟内找到关键文档；旧信息正确归档 |
| **scope** | 归档 v0.x 文档；合并 dogfood reports；更新 README/ROADMAP 状态标签；新增 docs/audit/README.md |
| **out of scope** | 不新增文档内容；不改代码 |
| **implementation risk** | 极低 |
| **SPEC/AD/TDD** | 不需要 |
| **gates** | git diff --check, 确保所有链接仍然有效 |
| **real API needed?** | 否 |
| **user authorization needed?** | 否 |
| **safe-to-auto-run?** | yes |
| **stop conditions** | 只有 hard stop |

### Priority 2: System Prompt Tool-Use Optimization (真实 provider 工具调用体验)

| Aspect | Detail |
|--------|--------|
| **name** | System prompt tool-use guidance optimization |
| **why now** | Real provider tool_use prompt sensitivity 是当前 fake→real 可用性最大差距 |
| **user outcome** | 用户说"帮我建一个 note"时，real provider (kimi-k2.5) 更大概率触发工具调用 |
| **scope** | 优化 `config.py` 中 SYSTEM_PROMPT 的工具使用指南；用 real provider 验证 |
| **out of scope** | 不改 Tool Pipeline；不改 provider adapter |
| **implementation risk** | 低 — prompt engineering only |
| **SPEC/AD/TDD**** | 不需要 SPEC；需要 manual dogfood validation |
| **gates** | ruff, existing tests, manual dogfood with real provider |
| **real API needed?** | yes — manual dogfood validation |
| **user authorization needed?** | yes — 需要用户提供 API key 并运行 dogfood |
| **safe-to-auto-run?** | no (需要真实 API) |
| **stop conditions** | 需要真实 API / 用户授权 |

### Priority 3: Memory Consolidation Freeze + Labeling

| Aspect | Detail |
|--------|--------|
| **name** | Freeze memory consolidation pipeline and add honest labels |
| **why now** | 6 个 consolidation 文件 + deferred business operation = 最大的代码膨胀源 |
| **user outcome** | 开发者清楚 consolidation 的当前状态（dispatch path only, not usable） |
| **scope** | 在 consolidation 模块添加模块级注释诚实标注状态；可能添加 `_FROZEN` 标记 |
| **out of scope** | 不删除代码；不实现 real LLM consolidation |
| **implementation risk** | 极低 — comments only |
| **SPEC/AD/TDD** | 不需要 |
| **gates** | ruff, existing tests |
| **real API needed?** | 否 |
| **user authorization needed?** | 否 |
| **safe-to-auto-run?** | yes |
| **stop conditions** | 只有 hard stop |

### Priority 4: Provider Swap Contract Test

| Aspect | Detail |
|--------|--------|
| **name** | Provider swap contract test |
| **why now** | 缺少 provider 切换时的行为一致性验证 |
| **user outcome** | Fake↔Real provider 切换时核心行为一致 |
| **scope** | 新增 contract test 验证不同 provider 下 RuntimeEvent 序列的一致性（不含 tool_use 语义差异） |
| **out of scope** | 不测试真实 API |
| **implementation risk** | 低 |
| **SPEC/AD/TDD** | 轻量 TDD |
| **gates** | ruff, focused tests |
| **real API needed?** | 否（fake path only） |
| **user authorization needed?** | 否 |
| **safe-to-auto-run?** | yes |
| **stop conditions** | 只有 hard stop |

### Priority 5: FakeProvider Freeze + Documentation

| Aspect | Detail |
|--------|--------|
| **name** | FakeProvider enhancement freeze |
| **why now** | 防止 FakeProvider 从 deterministic fixture 演变成 fake planner |
| **user outcome** | 诚实的能力边界 |
| **scope** | 在 `fake_provider.py` 添加模块级注释说明冻结策略；README 诚实标注 |
| **out of scope** | 不改 FakeProvider 行为 |
| **implementation risk** | 极低 — comments only |
| **SPEC/AD/TDD** | 不需要 |
| **gates** | ruff |
| **real API needed?** | 否 |
| **user authorization needed?** | 否 |
| **safe-to-auto-run?** | yes |
| **stop conditions** | 只有 hard stop |

### 不推荐现在做的

- SubAgent L1 implementation (L0 满足当前 MVP，L1 AD 已定但过早实现引入复杂度)
- Streaming UX revamp (当前 progress/event UX 足够；真实 SSE streaming 依赖 provider)
- Hook system design (turn-end hook 已承载所有需求)
- MCP confirmation="always" (product decision pending)
- Multi-agent orchestration (不在 scope)
- Web UI / SaaS (不在 scope)
- Memory consolidation real LLM activation (需要 real LLM/private data)

---

## M. Final Recommendation

### 1. 当前项目是否健康？

**是。** 仓库干净、测试齐全 (3331/0)、架构完整、工程纪律好。没有 P0 阻塞问题。

### 2. 最近 Big Loop 是否总体成功？

**是。** 多轮 Big Loop 产出包括：CLI command router 提取、NL delegation、Memory IDs + forget-by-short-ID (with ambiguity protection)、run summary enrichment、progress/event UX、real provider dogfood、provider tool-call compatibility AD、STREAMING_EVENT activation、SubAgent L3 non-empty registry、overclaim sweep、manual dogfood checklist。方向正确，没有架构腐化。

### 3. 是否存在必须立刻修的 P0/P1？

- **P0**: 无。
- **P1**: Real provider tool_use prompt sensitivity。需要 human-in-the-loop 的 prompt engineering + manual dogfood validation。不阻塞 AutoRun（不能 auto-fix）。

### 4. 是否应该继续 AutoRun？

**是，但方向应从 capability building 转向 consolidation/cleanup。** Architecture Extension Loop 机制成熟，但需要更多 human steering 来确保方向正确（特别是 memory consolidation freeze、FakeProvider freeze、文档归档）。

### 5. 是否应该先砍掉/冻结一批东西？

**是。** 优先级：(1) 冻结 Memory Consolidation pipeline 增强；(2) 冻结 FakeProvider tool_use decision 增强；(3) 归档 v0.x 历史文档；(4) 合并 dogfood reports；(5) 标注 legacy_adapter.py deprecated。

### 6. 下一步是继续能力建设，还是先做文档/架构瘦身？

**文档/架构瘦身优先。** 项目已经有足够的能力（Tool Pipeline L3 complete、Memory L3 complete、SubAgent L0 dogfood ready、Checkpoint production-like）。下一个阶段应该是：consolidation、honest labeling、文档清理——而非新增能力。

### 7. 是否应该进入 manual human dogfood？

**是。** `docs/dogfood/local-manual-dogfood-checklist.md` 已就绪。推荐在新一轮 manual dogfood 中重点验证：
- Real provider tool_use (用优化后的 system prompt)
- Memory recall 用户感知 ("Agent 是否感觉像记得我")
- SubAgent delegation 体验 (结果是否足够有用)

### 8. 是否应该继续 real provider dogfood？

**是，但需要先优化 system prompt tool-use guidance。** 当前 kimi-k2.5 已确认支持 Anthropic-style tool_use。下一个 manual dogfood cycle 应该聚焦在让 real LLM 更自然地选择工具。

### 9. 最推荐的下一条 prompt 类型？

**`/project:auto-run cleanup Big Loop`** — 以文档归档、consolidation freeze、honest labeling、FakeProvider freeze 为首个 Big Loop。不新增能力，只做减法和诚实化。

理由：项目已有足够的能力基础。当前最大的风险不是"缺什么"，而是"文档和代码给人以已完成但实际未完成的错觉"。先做瘦身和诚实标签，再在干净的基线上规划下一批能力建设。

---

> **审计完成。** 报告路径: `docs/audit/global-agent-capability-architecture-audit-2026-05-25.md`
>
> **一句话摘要**: 项目健康，架构坚实，测试纪律好；最大的问题是文档膨胀和部分能力（consolidation、streaming）的诚实标注不足；推荐下一阶段聚焦文档归档和代码冻结（consolidation freeze + FakeProvider freeze），而非新增能力。

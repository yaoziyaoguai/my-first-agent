# User-Usable Agent Runtime MVP Plan

Date: 2026-05-24
Status: active
Based on: repository evidence as of commit 3948a05

## A. Current Baseline

以下能力已通过 L3 E2E evidence 闭环或 L3 dispatch path verified，记录不再重复验证：

| Area | Status | Key evidence commit |
|---|---|---|
| Unified runtime flow (`core.chat` → `loop.py` → dispatcher) | ✅ 基础设施 | multiple |
| Tool Pipeline (gate→invoke→result, all 4 dispositions) | ✅ L3 完整闭环 | 6cef9b8, 748513c, f6d92f7, 76a88e4 |
| MCP through Tool Pipeline | ✅ L3 Tool Pipeline adapter boundary | multiple |
| Checkpoint save/resume + safe summary | ✅ L3 完整闭环 | cd6aaf6 |
| Memory retain/propose (confirmation → queue → turn-end → store) | ✅ L3 完整闭环 | a1185f5 |
| Memory recall (MEMORY_RECALL dispatch path) | ✅ L3 dispatch path verified | e18595b |
| Memory consolidation (MEMORY_CONSOLIDATE dispatch path) | ✅ L3 dispatch path verified, real LLM deferred | — |
| Skill (SKILL_SELECT, empty + non-empty registry) | ✅ L3 完整闭环 | 35009ed |
| SubAgent (SUBAGENT_DELEGATE_L0, empty registry) | ✅ L3 dispatch path verified | — |
| FakeProvider deterministic tool decision | ✅ generalized | 3948a05 |
| First Usable Task MVP (onboarding + help + smoke) | ✅ 完成 | bdbc806, b41193e |
| Streaming (STREAMING_PROVIDER_CALL dispatch) | ✅ L3 evidence path verified | — |
| Trace (on_trace_event sink) | ✅ runtime trace path verified | — |
| Full pytest | ✅ 3209 passed, 18 skipped, 0 failed | 3948a05 |

## B. Remaining User-Visible Capability Gaps

### B1. Memory That Actually Helps

**当前实际用户可感知状态：**
- `chat()` 入口处 `_memory_runtime.evaluate_user_text()` 会检测 explicit memory intent（"记住…"/"remember…"等 trigger phrase），触发 proposal → confirmation → retain 流程
- `refresh_runtime_system_prompt()` 调用 `snapshot_for_prompt()` 将已批准 memory 注入 system prompt（不经 RuntimeActionDispatcher）
- MEMORY_RECALL RuntimeAction 在 turn-end hook 调度，是 evidence dispatch path，与 prompt injection path **未共享 evidence**
- 用户无法查看/拒绝/删除/修正已有 memory（no user-facing memory management）

**Gap 分类：**
| Gap | 严重度 | 需要什么 |
|---|---|---|
| 用户能否感觉 Agent 记得自己 | 高 | fake demo 中能展示 memory recall effect |
| recall 是否进入 pre-loop context construction | 中 | 已是（`snapshot_for_prompt()` → `build_system_prompt()`），但是独立路径 |
| 双路径（prompt injection vs MEMORY_RECALL dispatch）未统一 | 中 | Architecture Decision：是否统一、如何统一 |
| 用户是否能查看/拒绝/删除 memory | 中 | 需要 user-facing memory management CLI/command |
| real LLM consolidation 仍 deferred | 低 | fake consolidation path 已存在 |

**safe-to-auto-run 范围：**
- fake memory recall demo：已存储 memory 在下一轮对话中可见 → safe
- memory management（list/reject/delete）via deterministic CLI → safe
- 双路径 evidence 统一或 Architecture Decision → safe
- **blocked**：real LLM consolidation、真实用户 private data

### B2. Pre-loop Memory Recall / Context Injection

**当前实际状态：**
- `refresh_runtime_system_prompt()` 在 `chat()` 入口处被调用，将已批准 memory snapshot 注入 system prompt
- 这条路径**不经过 RuntimeActionDispatcher**，是直接调用 `_memory_runtime.snapshot_for_prompt()` → `build_system_prompt()`
- MEMORY_RECALL RuntimeAction 在 turn-end hook 被调度 → dispatcher → handler → evidence（dispatch path L3 verified）
- 两条路径都正确，但未共享 evidence 链——MEMORY_RECALL handler 生成 evidence 但不等同于 prompt injection

**Gap 分类：**
| Gap | 严重度 | 需要什么 |
|---|---|---|
| prompt injection 与 MEMORY_RECALL evidence 是否统一 | 中 | Architecture Decision：是否需要让 injection path 也产生 MEMORY_RECALL evidence，或在 injection 点添加独立 pre-loop evidence |
| query-entry / context-build branch behavior 是否需要显式 branch point | 低 | 当前 injection 在 `chat()` 入口做，如果未来需要更多 pre-loop actions，可能需要显式 pre-loop hook |
| 避免新增第二条主流程 | 关键 | 无论 injection 怎么改，必须仍然是 `chat()` 调用链的一部分 |

**safe-to-auto-run 范围：**
- Architecture Decision：双路径是否统一、如何统一 → safe
- 如果 decision 是"注入点产生 evidence"：implementation → safe
- 如果 decision 是"新增 pre-loop hook"：Architecture Extension Loop → safe
- **blocked**：不影响 fake/real 共享 runtime 即可

### B3. SubAgent Delegation That Users Can See

**当前实际状态：**
- SUBAGENT_DELEGATE_L0 RuntimeActionType 已注册，handler 在 `subagent_action.py`
- `SubAgentRegistry(roots=())` 为空，handler 只验证 `no_suitable_subagent` 路径
- SubAgent 系统有 20 个文件（`agent/subagent_system/`），design doc `docs/design/SUBAGENT_SYSTEM_SDD.md`
- `docs/specs/subagent-l3/SPEC.md` 已存在
- L3 dispatch path verified（空 registry）

**Gap 分类：**
| Gap | 严重度 | 需要什么 |
|---|---|---|
| 用户能否看到一个 meaningful local demo delegation | 高 | non-empty SubAgentRegistry + 至少一个 safe local demo subagent |
| subagent 结果如何回到主对话 | 关键 | delegation → execution → result 完整链路需要 SPEC/TDD |
| 避免第二条 runtime flow | 关键 | subagent execution 必须复用现有 `core.chat` 或 call_model + tool pipeline |
| safe local demo subagent 能做什么 | 设计 | 做一个不调用外部 API/LLM 的 deterministic subagent（如"统计仓库文件数"、"echo 当前时间"） |

**safe-to-auto-run 范围：**
- non-empty SubAgentRegistry + 1 safe local demo subagent → safe
- subagent delegation → result 完整路径测试 → safe
- **blocked**：真实外部 agent、需要真实 LLM 的 subagent

### B4. Streaming / Progress Experience

**当前实际状态：**
- `STREAMING_PROVIDER_CALL` RuntimeActionType L3 dispatch path verified
- `STREAMING_EVENT` RuntimeActionType 为 reserved/inactive（无 handler、无 wiring）
- `FakeProvider.supports_streaming = False`
- `agent/provider/streaming.py` 有 `ProviderStreamEvent` / `sanitize_stream_text()`
- `agent/runtime_integration/streaming_provider.py` 收集 streaming evidence
- `model_call.py` 中 `_call_model()` 在 provider 不支持 streaming 时 fallback 到 `create()`

**Gap 分类：**
| Gap | 严重度 | 需要什么 |
|---|---|---|
| 用户在 CLI/TUI 中看到 progress | 高 | FakeProvider 不支持 streaming，需要 deterministic progress demo |
| 工具调用中有用户可见状态（running/done/failed） | 中 | 当前 tool execution 在 loop.py 中，`ToolExecutor.execute()` 无用户进度输出 |
| 不调用真实 LLM 的情况下做 streaming demo | 设计 | FakeProvider 可以做 deterministic text chunking（分片输出） |
| stream provider 与 tool execution 交互 | 设计 | 需要 SPEC 明确 streaming 和 tool_use 的关系 |

**safe-to-auto-run 范围：**
- deterministic text chunking in FakeProvider（`stream()` 方法返回分片文本流）→ safe
- tool execution progress events（deterministic） → safe
- user-visible progress in CLI → safe
- **blocked**：真实 LLM streaming（需要真实 API）
- **product decision**：streaming UX 形态（逐字/逐句/逐块）

### B5. Trace / Debug / Evidence Experience

**当前实际状态：**
- `on_trace_event` 是 optional callback sink，通过 `agent/local_trace.py` 记录 TraceEvent
- Trace 不经过 RuntimeActionDispatcher evidence 模型，使用 "runtime trace path verified" 标签
- `agent/runtime_events.py` 定义 RuntimeEvent（用户可见事件）
- `agent/runtime_observer.py` 提供 RuntimeObserver
- `agent/cli_renderer.py` 渲染 RuntimeEvent 到 CLI
- 无 run summary / evidence report

**Gap 分类：**
| Gap | 严重度 | 需要什么 |
|---|---|---|
| 用户/开发者看懂一轮运行发生了什么 | 高 | readable run summary（"本轮做了什么：工具调用 X 次，memory recall Y 条，…"） |
| evidence report | 中 | 基于 RuntimeAction evidence 生成可读摘要 |
| 避免泄漏敏感信息 | 关键 | evidence report 不能包含 secret/token/raw private data |

**safe-to-auto-run 范围：**
- run summary based on RuntimeActionDispatcher evidence → safe
- readable trace output in CLI after chat → safe
- **blocked**：不需要

### B6. Tool / Skill UX Polish

**当前实际状态：**
- Tool failure recovery：`tool_invoke_error_l3.py` 验证 error path（invoke 抛异常）
- blocked explanation：`tool_blocked_l3.py` 验证
- confirmation UX：`tool_branch_confirmation_required.py` 验证
- multi-tool：未做
- demo skill：`demo-note-maker` 存在，但 body_load 不自动触发 tool call
- `tool-invoke-not-found-l3.py` 验证 not_found

**Gap 分类：**
| Gap | 严重度 | 需要什么 |
|---|---|---|
| Tool failure recovery 质量 | 低 | 当前 error → 记录 + 继续；不需要更复杂的 retry |
| blocked explanation UX | 低 | 当前 gate 阻止并返回解释；CLI renderer 是否需要更好展示 |
| confirmation UX 易用性 | 中 | 当前用户需手动输入 y/n/f；是否需要 inline confirmation shortcut |
| multi-tool 是否需要现在做 | 低 | MVP 不需要 |
| demo skill 自动触发 tool call | 低 | 需要 FakeProvider tool decision 匹配 "写 note" → demo.write_demo_note（已通过 tool decision layer 支持） |

**safe-to-auto-run 范围：**
- confirmation UX 改善（更好的提示） → safe
- **product decision**：confirmation 交互形式

### B7. Real Provider Opt-in Readiness

**当前实际状态：**
- `agent/provider/factory.py` 中 `build_model_provider_from_env()` 支持 `PROVIDER_ENV=anthropic`
- `agent/provider/anthropic_provider.py` 实现 Anthropic provider adapter
- README 已说明 opt-in
- `.env.example` 已存在
- 不自动读取 .env
- 不自动调用真实 API

**Gap 分类：**
| Gap | 严重度 | 需要什么 |
|---|---|---|
| 文档是否说明 opt-in | 低 | README 已有 |
| 是否需要在计划中重申 | 低 | 本文档即为重申 |

**safe-to-auto-run 范围：**
- docs-only → safe
- **不**做任何真实 API 调用

## C. Prioritized Work Packages

### WP-A: Memory That Actually Helps — Local/Fake-Safe MVP

| Aspect | Detail |
|---|---|
| **User outcome** | 用户通过 `chat()` 对话，Agent 能 remember、recall、展示 memory reference，终端用户能感觉"Agent 记得我之前说的" |
| **Scope** | 1. fake memory store 已有内容在下一轮对话中通过 system prompt 注入（当前已做）；2. 增加 "show memory" / "forget X" 用户命令（deterministic CLI）；3. focused test 覆盖 memory write→recall→visible 闭环 |
| **Out of scope** | real LLM consolidation、private data、真实 memory episodes |
| **SPEC/TDD** | 需要 SPEC（基于现有 `docs/specs/memory-recall-branch-behavior/`）；需要 focused test |
| **Safety constraints** | 不新增第二条 runtime；不绕开 core.chat；不读取真实 memory files |
| **Gates** | ruff, focused tests, runtime_integration tests, full pytest |
| **Stop conditions** | real LLM、private data、.env |
| **Expected demo** | 用户在 CLI 输入 "remember my name is Alice" → Agent confirms → 下一轮对话 Agent 提及 "Alice" |
| **safe-to-auto-run** | **yes** — 全部 fake/local deterministic |
| **Priority** | **最高** — 核心用户感知能力 |

### WP-B: Pre-loop MEMORY_RECALL Architecture Decision

**状态：AD complete — implementation deferred.**
AD 文档 `docs/design/MEMORY_RECALL_DUAL_PATH_AD.md`（commit `aeb4b67`）已做出决定：不统一双路径。pre-loop prompt injection 路径（`refresh_runtime_system_prompt()` → `snapshot_for_prompt()` → `build_system_prompt()`）已正常工作，turn-end MEMORY_RECALL dispatch 提供互补证据。不需要额外实现。Memory recall 用户可见闭环不在当前 scope。

| Aspect | Detail |
|---|---|
| **User outcome** | Memory recall 在每次对话开始时自动、透明地注入 context，开发者/审计者能看到 evidence chain |
| **Scope** | Architecture Decision：双路径（prompt injection vs MEMORY_RECALL dispatch）是否统一、如何统一（**done**）；implementation（**deferred**） |
| **Out of scope** | 新增 RuntimeActionType（除非 decision 明确要求）、新增第二条流程 |
| **SPEC/TDD** | Architecture Decision doc（**done**, `docs/design/MEMORY_RECALL_DUAL_PATH_AD.md`）；focused test 覆盖 unified evidence chain（**deferred**） |
| **Safety constraints** | 不新增第二条 runtime；不改变 system prompt injection 核心路径（除非 decision 明确要求） |
| **Gates** | ruff, focused tests, full pytest |
| **Stop conditions** | 需要一个显著不同的 runtime entry point（违反 unified runtime flow） |
| **Expected demo** | 每轮对话开始时的 system prompt 包含 memory context，且 evidence chain 可追溯 |
| **safe-to-auto-run** | **yes** — Architecture Decision + 本地实现 |
| **Priority** | **高** — Memory MVP 的前置条件（AD 已完成，implementation deferred） |

### WP-C: SubAgent Meaningful Local Demo Delegation

| Aspect | Detail |
|---|---|
| **User outcome** | 用户能在对话中看到 Agent 将某个任务 delegate 给 subagent，subagent 完成并返回结果 |
| **Scope** | 1. non-empty SubAgentRegistry（至少 1 个 safe local demo subagent）；2. FakeProvider tool_use 触发 subagent delegation（类似 demo.write_demo_note）；3. subagent execution → result 完整 L3 路径 |
| **Out of scope** | 真实外部 agent、需真实 LLM 的 subagent、多层级 subagent nesting |
| **SPEC/TDD** | 基于现有 `docs/specs/subagent-l3/SPEC.md` 更新；need SPEC for demo subagent behavior |
| **Safety constraints** | subagent execution 复用 core.chat / call_model / Tool Pipeline；不新增独立 subagent runtime |
| **Gates** | ruff, focused tests, full pytest |
| **Stop conditions** | 需要真实外部 agent、需要第二条 runtime |
| **Expected demo** | 用户请求"帮我统计项目文件" → Agent delegates to subagent → subagent 返回统计结果 |
| **safe-to-auto-run** | **yes** — local fake subagent |
| **Priority** | **中** — 独立于 Memory，可并行 |

### WP-D: Streaming / Progress User-Visible Experience

| Aspect | Detail |
|---|---|
| **User outcome** | 用户在 CLI 中能看到 Agent 在"思考中"的 streaming text 输出和 tool 调用进度 |
| **Scope** | 1. FakeProvider `stream()` method（deterministic text chunking）；2. tool execution progress events；3. CLI renderer 更新以展示 streaming/progress |
| **Out of scope** | 真实 LLM streaming |
| **SPEC/TDD** | 需要 SPEC；需要 focused test |
| **Safety constraints** | streaming 不影响 unified runtime flow；只是一个输出格式化 |
| **Gates** | ruff, focused tests, full pytest |
| **Stop conditions** | 需要真实 LLM API |
| **Expected demo** | 用户在 CLI 输入问题后，能看到文本逐块出现和 tool 调用状态切换 |
| **safe-to-auto-run** | **yes** — deterministic chunking |
| **Priority** | **中低** — 改善体验但非核心正确性 |

### WP-E: Trace / Debug Readable Run Summary

| Aspect | Detail |
|---|---|
| **User outcome** | 每轮 chat() 结束后，用户或开发者能看到结构化 run summary（工具调用、memory 操作、状态变化） |
| **Scope** | 1. 基于 RuntimeActionDispatcher evidence 生成 run summary；2. CLI 输出可选 --verbose/--summary 开关；3. focused test |
| **Out of scope** | 实时 trace UI、分布式 tracing、持久化 trace store |
| **SPEC/TDD** | 需要 SPEC；需要 focused test |
| **Safety constraints** | summary 不泄漏敏感信息；不改变 evidence 模型 |
| **Gates** | ruff, focused tests, full pytest |
| **Stop conditions** | 无 |
| **Expected demo** | `python main.py chat` 后打印 "本轮结束：工具调用 2 次，memory recall 3 条，…" |
| **safe-to-auto-run** | **yes** |
| **Priority** | **低** — 改善开发者体验 |

### WP-F: Tool / Skill UX Polish

| Aspect | Detail |
|---|---|
| **User outcome** | 工具确认流更友好、工具失败时有更清晰的提示 |
| **Scope** | 1. tool confirmation prompt 改进；2. tool failure/blocked message 改进；3. demo skill 已有 tool_use 触发路径改善 |
| **Out of scope** | multi-tool orchestration、MCP confirmation="always" |
| **SPEC/TDD** | 轻量 SPEC；focused test |
| **Safety constraints** | 不改变 tool pipeline 核心逻辑 |
| **Gates** | ruff, focused tests, full pytest |
| **Stop conditions** | 无 |
| **Expected demo** | 工具被 blocked 时 CLI 显示易懂解释而非 raw error |
| **safe-to-auto-run** | **yes** |
| **Priority** | **低** — polish，非 blocker |

### WP-G: Real Provider Opt-in Readiness Docs

| Aspect | Detail |
|---|---|
| **User outcome** | 用户清楚知道如何从 fake demo 切换到 real Anthropic provider，以及切换后的风险 |
| **Scope** | 1. 文档：opt-in 步骤、风险提示、预期行为差异；2. dry-run 验证 opt-in gate 未损坏 |
| **Out of scope** | 实际真实 API 调用 |
| **SPEC/TDD** | 无需（docs-only） |
| **Safety constraints** | 不读取 .env、不调用真实 API |
| **Gates** | ruff, git diff --check |
| **Stop conditions** | 无 |
| **Expected demo** | README 更新，opt-in 路径文档清晰 |
| **safe-to-auto-run** | **yes** — docs only |
| **Priority** | **低** — 信息整理 |

## D. Stop / Block Rules

| Condition | Action |
|---|---|
| 需要真实 LLM | **deferred** — 标记 blocked，不停止 workflow |
| 需要真实 API / .env | **deferred** — 标记 blocked，不停止 workflow |
| 需要真实 private data | **deferred** — 标记 blocked，不停止 workflow |
| 会导致第二条 runtime flow | **forbidden** — stop with HARD_STOP_SECOND_RUNTIME_FLOW |
| 会导致 fake/real 分裂 | **forbidden** — stop with HARD_STOP_FAKE_REAL_SPLIT |
| 需要用户产品决策 | **stop** — HARD_STOP_PRODUCT_DECISION_REQUIRED |
| local/fake deterministic path 可验证 | **safe-to-auto-run** |

## E. Execution Order

推荐执行顺序及理由：

| Order | WP | 理由 |
|---|---|---|
| **1** | WP-B: Pre-loop MEMORY_RECALL Architecture Decision | Memory MVP (WP-A) 的前置条件——需要先决定 evidence 模型如何统一，再实现 user-visible memory |
| **2** | WP-A: Memory That Actually Helps MVP | 核心用户感知能力——用户对 Agent 的第一印象是"它记得我吗" |
| **3** | WP-C: SubAgent Meaningful Demo | 独立于 Memory，第二个核心 user-visible capability |
| **4** | WP-D: Streaming / Progress UX | 依赖 FakeProvider 完善（stream() 方法），改善体验 |
| **5** | WP-E: Trace / Debug Run Summary | 改善开发者/用户理解，低耦合 |
| **6** | WP-F: Tool/Skill UX Polish | polish，优先级最低 |
| **7** | WP-G: Real Provider Opt-in Docs | docs-only，最终收口 |

**例外情况：** 如果 WP-B Architecture Decision 判定双路径不需要统一（当前 injection path 已足够），则可以跳过 WP-B 实现直接进入 WP-A。

**依赖关系：**
- WP-A 依赖 WP-B 的 Architecture Decision（前置）
- WP-C 独立于 WP-A/WP-B（可并行）
- WP-D 独立于其他（只需 FakeProvider 增强）
- WP-E/F/G 均独立

## F. First Auto-Run Target

根据优先级和依赖关系，第一个 auto-run target 为：

**WP-B: Pre-loop MEMORY_RECALL Architecture Decision**

然后立即进入 WP-A: Memory That Actually Helps MVP。

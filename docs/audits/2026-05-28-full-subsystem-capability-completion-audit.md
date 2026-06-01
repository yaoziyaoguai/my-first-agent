# First Agent 完整子系统能力补齐审计与路线图设计

**状态: historical — superseded by redteam addendum (`2026-05-28-full-subsystem-capability-completion-audit-redteam-addendum.md`) + 2026-05-29~31 evidence closure loops。原始 COMPLETE 判定偏乐观（90/117），更正后仅 27/117（redteam addendum 结论）。**
> 审计日期: 2026-05-28
> 审计类型: 只读审计（不改代码、不改文档、不调用真实 API、不提交）
> 范围: 全部 10 个子系统
> 基于: Loop 1-18 全部产出物、docs/audit/ 所有历史审计、PROGRESS_LEDGER.md 全量记录

---

## 目录

1. [完整能力清单 (Full Capability Inventory)](#1-完整能力清单)
2. [完整差距矩阵 (Full Gap Matrix)](#2-完整差距矩阵)
3. [偏差诊断 (Deviation Diagnosis)](#3-偏差诊断)
4. [完整补齐路线图 (Full Completion Roadmap)](#4-完整补齐路线图)
5. [优先级排序 (Prioritization)](#5-优先级排序)
6. [附录](#6-附录)

---

## 1. 完整能力清单

### 状态词汇表

| 状态 | 含义 |
|------|------|
| **COMPLETE** | 实现完成、测试覆盖、通过 dispatcher 统一路径、fake + real 双路径验证 |
| **PARTIAL** | 基本功能实现但不完整，或缺少某侧路径（fake/real 其中一条） |
| **STUB** | 骨架存在但核心逻辑是占位符/硬编码，无法产生真实效果 |
| **DEMO** | 仅能演示，不具备生产可用性 |
| **FAKE_ONLY** | 仅有 fake/deterministic 路径，无真实能力 |
| **DIRECT_CALL_ONLY** | 功能存在但绕过了 dispatcher 统一入口 |
| **DOC_ONLY** | 有设计文档但代码未实现或仅空壳 |
| **NOT_STARTED** | 尚未开始 |

---

### 1.1 Tool 系统

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| Tool Registry（注册/查询/去重） | **COMPLETE** | `tool_registry.py`: register_tool, get_tool_definitions, get_model_visible_tools, TOOL_REGISTRY dict |
| Tool Executor（执行/结果分类） | **COMPLETE** | `tool_executor.py`: execute_single_tool, execute_pending_tool, ToolResultEnvelope |
| Tool Confirmation Pipeline | **COMPLETE** | needs_tool_confirmation(always/never/dynamic), AWAITING_USER 分支, pending_tool 状态机 |
| Tool Safety/Policy Denial | **COMPLETE** | _describe_policy_denial, is_sensitive_file, 4 类 outcome (success/failure/policy_denial/user_rejection) |
| Tool Name Normalization | **COMPLETE** | _normalize_tool_name 处理后缀匹配 |
| Meta Tool Support | **COMPLETE** | mark_step_complete, request_user_input 等元工具不走 messages |
| Tool Audit/Trace | **COMPLETE** | emit_tool_audit_event, emit_tool_result_trace_event |
| Tool Pipeline (GATE→INVOKE→RESULT) | **COMPLETE** | `loop.py`: _dispatch_tool_pipeline 四阶段 dispatch |
| Real API E2E Tool Execution | **COMPLETE** | dogfood_global_real_api 验证真实 LLM 驱动工具调用 |
| MCP Tool via Registry | **PARTIAL** | mcp_bridge 可将 MCP tool 注册为 registry tool, 但 MCP transport 未实现 |
| Tool Budget/Quota | **NOT_STARTED** | 每轮工具调用无硬限制（仅 loop iteration 上限） |

**总体评分: COMPLETE (10/11 项完成)**

---

### 1.2 MCP 系统

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| MCP Models/Contracts | **COMPLETE** | `mcp_models.py`: MCPToolDescriptor, MCPServerConfig, MCPClient protocol |
| MCP Config Management | **COMPLETE** | `mcp_config.py`, `mcp_config_service.py`, `mcp_config_cli.py`, `mcp_config_presenter.py` |
| Fake MCP Client | **COMPLETE** | `mcp.py`: FakeMCPClient with tools_by_server, results_by_call |
| MCP Policy/Sanitizer | **COMPLETE** | `mcp_policy.py`, `mcp_sanitizer.py` |
| MCP Bridge (→Tool Registry) | **COMPLETE** | `mcp_bridge.py`: register_mcp_tools_as_local |
| MCP Audit | **COMPLETE** | `mcp_audit.py` |
| Real MCP Transport (stdio) | **STUB** | `mcp_stdio.py` 存在但标记为"不实现真实 transport"，无 stdio 进程启动 |
| Real MCP Transport (HTTP/SSE) | **NOT_STARTED** | 未实现 |
| MCP Tool Execution (real) | **NOT_STARTED** | FakeMCPClient 提供工具描述和假结果；无真实 server 连接 |
| MCP Server Discovery | **NOT_STARTED** | 无 server 发现/注册机制 |
| MCP Dispatcher Integration | **COMPLETE** | `mcp_tool_orchestrator.py` 在 runtime_integration 中 |

**总体评分: FAKE_ONLY — 整个 MCP 栈只有 fake client，无真实 transport 实现**

---

### 1.3 Skill 系统

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| Skill Registry (注册/可见性/标签) | **COMPLETE** | `registry.py`: SkillRegistry with list_visible, get_descriptor |
| Skill Loader (Progressive Disclosure L1/L2/L3) | **COMPLETE** | `loader.py`: load_body, load_resource, caching, 100KB limit, path traversal 防护 |
| Skill Descriptor Model | **COMPLETE** | `descriptor.py`: SkillDescriptor with risk_level, allowed_tools, memory_scope |
| Skill Selector (关键词匹配) | **PARTIAL** | `selector.py`: deterministic keyword scoring only — 无 LLM selection, 无 embeddings |
| Skill Tool Binding | **COMPLETE** | `tool_binding.py`: SkillToolBinding.check 验证工具权限, 但 check_all() 未在 runtime path 调用 |
| Skill Invocation | **PARTIAL** | `invocation.py`: invoke_skill 返回 markdown text, 不执行代码; visible_output=body (纯文本) |
| Skill Execution (Agent + Tools) | **NOT_STARTED** | Skill 设计明确说"不拥有 Agent loop", "不直接执行工具"; 当前 Skill 是文本模板 |
| Skill Dispatcher Integration | **COMPLETE** | `skill_action.py`: SkillRuntimeActionHandler with full validation, evidence chain |
| Skill Content (实际 SKILL.md 文件) | **DEMO** | 仅 4 个 demo skill (blog-writing, demo-note-maker, evil-skill, pdf); 全是 SKILL.md 文本 |
| Skill E2E (模型选择→加载→注入→执行) | **DOC_ONLY** | 设计文档存在 (SKILL_SYSTEM_SDD.md), 但 Skill 从未被真实 Agent 加载执行 |

**总体评分: PARTIAL — 基础设施完整, 但 Skill 不执行，只是文本模板**

---

### 1.4 Memory 系统

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| Memory Store (InMemory) | **COMPLETE** | `memory_store.py`: InMemoryMemoryStore with MemoryRecord |
| Memory Store (Filesystem) | **COMPLETE** | `memory_fs_store.py`: topic-grouped markdown, YAML frontmatter, write-through |
| Memory Recall (via Dispatcher) | **COMPLETE** | `memory_recall.py`: MemoryRecallHandler, MemorySnapshot, prompt section |
| Memory Retain (Two-Phase Confirmation) | **COMPLETE** | `memory_retain.py`: evaluate → CONFIRMATION_REQUIRED → resolve → STORED/REJECTED |
| Memory Turn-End Proposal | **COMPLETE** | `memory_hook.py`: MEMORY_TURN_END_PROPOSAL in turn-end hook |
| Memory Consolidation (Episodic→Semantic) | **COMPLETE (basic)** | `memory_consolidate.py`: pattern detection, candidate generation; no LLM enhancement |
| Memory Confirmation UX | **COMPLETE** | `memory_confirmation.py`: MemoryConfirmationRequest/Result, structured options |
| Memory Contracts | **COMPLETE** | `memory_contracts.py`: MemoryDecision, MemoryDecisionType, MemoryScope |
| Memory Dispatcher Integration (all paths) | **COMPLETE** | All operations via dispatcher (Loop 15): RECALL, PROPOSE, TURN_END_PROPOSAL, CONSOLIDATE |
| CLI Show/Forget Memories | **COMPLETE (Show) / DIRECT_CALL_ONLY (Forget)** | Show via dispatcher READ_ONLY; Forget is DIRECT_CALL bypassing confirmation pipeline |
| Memory Kernel v1 (Runtime Closure) | **COMPLETE** | `memory_runtime.py`: minimal runtime closure for explicit retain |
| LLM-Enhanced Consolidation | **NOT_STARTED** | 设计文档提到但未实现; 当前 consolidation 是纯 deterministic pattern matching |
| Proactive Reminder/Emergence | **NOT_STARTED** | Memory 无主动提醒或 emergence 检测 |
| Auto-Retain (T2 governed) | **NOT_STARTED** | 设计文档提到但未实现 |

**总体评分: COMPLETE (12/14 项完成) — 核心 CRUD + 确认管道完整, LLM 增强和主动功能缺失**

---

### 1.5 SubAgent 系统

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| SubAgent Registry | **COMPLETE** | `registry.py`: SubAgentRegistry with visibility, risk levels |
| SubAgent Descriptor | **COMPLETE** | `descriptor.py`: supported_modes = ("local_fake",) |
| SubAgent Executor (local_fake) | **STUB** | `executor.py`: execute_local() 是纯字符串匹配 — "loop until max"→max_iterations_exceeded, "shell"→policy_blocked |
| SubAgent Dispatcher Integration | **COMPLETE** | `subagent_action.py`: SubAgentDelegateL0Handler with validation pipeline, evidence chain |
| SubAgent Safety (Shell/Nested Block) | **COMPLETE** | Shell-like tool blocking, nested delegation blocking, budget validation |
| SubAgent Delegation Request Model | **COMPLETE** | `request.py`: SubAgentRequest with task, role, allowed_tools, budget |
| L1+ Execution (Real LLM) | **NOT_STARTED** | execution_mode 只有 LOCAL_FAKE 和 LOCAL_DETERMINISTIC |
| SubAgent Tool Execution | **NOT_STARTED** | SubAgent 不执行任何工具; 所有"执行"都是字符串响应 |
| SubAgent Dogfood | **FAKE_ONLY** | `dogfood_subagent_system.py`: 15 scenarios all against fake executor |
| Real SubAgent Content | **NOT_STARTED** | `agent/subagents/` 仅有 __init__.py |

**总体评分: STUB — 架构边界完整, 但核心执行是字符串匹配**

---

### 1.6 Storage / Session / Checkpoint / Run State

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| Checkpoint Save/Load | **COMPLETE** | `checkpoint.py`: JSON-based, SCHEMA_VERSION governance |
| Checkpoint Schema Migration | **COMPLETE** | v0→v1 identity migration, _MIGRATION_REGISTRY |
| Checkpoint Safe Summary | **COMPLETE** | CHECKPOINT_SAFE_SUMMARY in turn-end hook |
| Checkpoint Truncation Config | **COMPLETE** | max_result_length, max_tool_results 可配置 |
| Session Management | **COMPLETE** | `session.py`: Session tracking |
| Run State (TurnState, Task) | **COMPLETE** | `state.py`: structured runtime state |
| Resume from Checkpoint | **PARTIAL** | Checkpoint load 工作, 但 resume 流程集成有限——缺少结构化 resume 测试 |
| Conversation History Persistence | **COMPLETE** | messages 在 checkpoint 中持久化 |
| Multi-Session Isolation | **PARTIAL** | Filesystem store 是单用户单进程, 无并发锁; 无多 session 隔离机制 |
| Memory Store Backup/Restore | **NOT_STARTED** | 无备份/恢复机制 |

**总体评分: COMPLETE (8/10 项完成)**

---

### 1.7 Provider / Config

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| Provider Protocol (create/stream) | **COMPLETE** | `provider/protocol.py`: ModelProvider abstract protocol |
| FakeProvider | **COMPLETE** | `provider/fake_provider.py`: deterministic, scenario-driven, FROZEN for enhancement |
| Anthropic Provider (Native) | **COMPLETE** | `provider/anthropic_native.py` |
| Anthropic Provider (HTTP) | **COMPLETE** | `provider/anthropic_http.py` |
| OpenAI Provider | **COMPLETE** | `provider/openai_native.py`, `provider/openai_http.py` |
| Anthropic-Compatible (DashScope/Kimi) | **COMPLETE** | config.yaml → kimi-k2.5 via DashScope |
| Provider Factory | **COMPLETE** | `provider/factory.py`: build_model_provider |
| Provider Streaming | **COMPLETE** | `provider/streaming.py`: ProviderStreamEvent |
| Provider Config | **COMPLETE** | `provider/config.py`: AgentProviderConfig, simple_config.py |
| Config File Safety (dirty tracking) | **PARTIAL** | config.yaml tracked dirty — P1 security risk (历史审计发现, 尚未修复) |
| Provider Diagnostics | **COMPLETE** | `provider/diagnostics.py` |
| Provider Fallback/Failover | **NOT_STARTED** | 无 provider 切换或 fallback 机制 |

**总体评分: COMPLETE (11/12 项完成) — config.yaml dirty 是唯一安全问题**

---

### 1.8 Runtime / Summary / Trace / Evidence

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| RuntimeActionDispatcher | **COMPLETE** | `dispatcher.py`: handler registry, route/route_from_runtime_loop, evidence provenance |
| RuntimeAction Schema | **COMPLETE** | `schema.py`: 14 RuntimeActionTypes, request/result/event dataclasses |
| Evidence Classification (L1-L4) | **COMPLETE** | `evidence.py`: RUNTIME_E2E, REAL_CORE_LOOP_RUNTIME_E2E, HARNESS_RUNTIME_E2E 等 |
| Business vs Probe Classification | **COMPLETE** | `classify_action_evidence_kind`: business/probe 区分 |
| Target Catalog (trusted invocation) | **COMPLETE** | `RuntimeActionTargetCatalog`: catalog-owned adapter 发行 trusted proof |
| Run Summary (per-turn) | **COMPLETE** | `_emit_run_summary()`: structured stats, business/probe event counting |
| Trace Event Emission | **COMPLETE** | `local_trace.py`: TraceEvent, opt-in trace sink |
| Loop Orchestration | **COMPLETE** | `loop.py`: run_main_loop with turn-end hook |
| Action Log (dispatcher-owned) | **COMPLETE** | `RuntimeActionDispatcher._action_log`: per-session event log |
| Console/Display Events | **COMPLETE** | `display_events.py`: RuntimeEvent, control_message, run_summary_event |
| Streaming Dispatch (STREAMING_PROVIDER_CALL/STREAMING_EVENT) | **COMPLETE** | turn-end hook dispatch when provider_supports_streaming=True |

**总体评分: COMPLETE (11/11 项完成)**

---

### 1.9 Confirmation / Safety / Permission

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| Tool Confirmation (always/never/dynamic) | **COMPLETE** | `tool_registry.py`: needs_tool_confirmation |
| Tool Policy Denial (敏感文件) | **COMPLETE** | `tool_executor.py`: _describe_policy_denial |
| Memory Confirmation (Two-Phase) | **COMPLETE** | `memory_confirmation.py`: structured request/result |
| Secret Detection (API key/token) | **COMPLETE** | `schema.py`: contains_secret_like with SECRET_PATTERNS |
| Path Traversal Prevention | **COMPLETE** | `skill_system/loader.py`: no absolute paths, no path escape |
| Sensitive Config Protection | **COMPLETE** | `mcp.py`: SENSITIVE_CONFIG_NAMES, SENSITIVE_CONFIG_PARTS |
| SubAgent Safety (Shell/Nested Block) | **COMPLETE** | `subagent_action.py`: _SHELL_LIKE_TOOLS, nested delegation check |
| CLI Meta-Command Safety | **PARTIAL** | Show 已走 dispatcher, Forget 仍 bypass confirmation pipeline (DIRECT_CALL) |
| Fine-Grained Permission System | **NOT_STARTED** | 无角色/用户/操作级别的权限模型 |
| Rate Limiting | **NOT_STARTED** | 无速率限制 |
| Audit Trail (Persistent) | **PARTIAL** | action_log 仅在内存中, 不持久化 |

**总体评分: COMPLETE (8/11 项完成) — 核心安全机制完整, 高级权限和持久化审计缺失**

---

### 1.10 Dogfood / Evaluation Harness

| 能力项 | 状态 | 证据/说明 |
|--------|------|-----------|
| Interactive Harness (subprocess) | **COMPLETE** | `dogfood_interactive_harness.py`: 16 cases, 6 categories, structured assertions |
| Real API Dogfood Sweep | **COMPLETE** | `dogfood_global_real_api.py`: provider preflight, secret safety, 20 scenarios |
| Tool Dogfood (fake) | **COMPLETE** | `dogfood_tool_anchor_fake.py`, `_dogfood_tool_anchor_checks.py` |
| Memory Dogfood (fake + real smoke) | **COMPLETE** | `dogfood_memory_anchor_fake.py`, `dogfood_memory_anchor_real_smoke.py`, `dogfood_memory_e2e.py` |
| SubAgent Dogfood (fake only) | **FAKE_ONLY** | `dogfood_subagent_system.py`: 15 scenarios, all fake executor |
| Skill Dogfood (synthetic + real-api) | **PARTIAL** | `dogfood_skill_system.py`: tests loading/selection/binding but not execution |
| Provider Preflight | **COMPLETE** | `dogfood_provider_preflight.py` |
| E2E Runtime Dogfood | **COMPLETE** | `dogfood_e2e_runtime.py`, `dogfood_phase1_real_core_loop.py` |
| Complex Real API/LLM Dogfood | **COMPLETE** | `dogfood_complex_real_api.py`, `dogfood_complex_real_llm.py` |
| BL1 (Safety/Tool Use) Dogfood | **COMPLETE** | `dogfood_bl1_safety_preflight.py`, `dogfood_bl1_phase2_core_chat.py`, `dogfood_bl3_tool_use_e2e.py` |
| Consolidation LLM Dogfood | **COMPLETE** | `dogfood_phase6_llm_consolidation.py` |
| Checklist Executor | **COMPLETE** | `dogfood_checklist_executor.py` |
| Global Scenarios Definition | **COMPLETE** | `dogfood_global_scenarios.py`: ScenarioDefinition |
| Dogfood Output Report | **COMPLETE** | `GLOBAL_REAL_API_DOGFOOD_REPORT.md` (19/20 non-failing) |
| SubAgent Real E2E Dogfood | **NOT_STARTED** | 没有真实 SubAgent E2E 测试 |
| MCP Real E2E Dogfood | **NOT_STARTED** | 没有真实 MCP 测试 |
| Skill Execution E2E Dogfood | **NOT_STARTED** | 没有 Skill 执行流测试 |

**总体评分: PARTIAL (14/17 项完成) — 基础设施完整, 但 SubAgent/MCP/Skill 的 real E2E dogfood 缺失**

---

## 2. 完整差距矩阵

### 2.1 差距总览

| 子系统 | 能力项总数 | COMPLETE | PARTIAL | STUB | FAKE_ONLY | DOC_ONLY | NOT_STARTED | 完成率 |
|--------|-----------|----------|---------|------|-----------|----------|-------------|--------|
| Tool | 11 | 10 | 1 | 0 | 0 | 0 | 0 | 91% |
| MCP | 11 | 7 | 0 | 1 | 1 (整体) | 0 | 3 | 64% |
| Skill | 10 | 5 | 2 | 0 | 0 | 1 | 2 | 50% |
| Memory | 14 | 12 | 0 | 0 | 0 | 0 | 2 | 86% |
| SubAgent | 10 | 5 | 0 | 1 | 1 | 0 | 3 | 50% |
| Storage/Checkpoint | 10 | 8 | 2 | 0 | 0 | 0 | 0 | 80% |
| Provider/Config | 12 | 11 | 1 | 0 | 0 | 0 | 0 | 92% |
| Runtime/Evidence | 11 | 11 | 0 | 0 | 0 | 0 | 0 | 100% |
| Confirmation/Safety | 11 | 7 | 2 | 0 | 0 | 0 | 2 | 64% |
| Dogfood/Harness | 17 | 14 | 1 | 0 | 1 | 0 | 2 | 82% |
| **总计** | **117** | **90** | **9** | **2** | **3** | **1** | **14** | **77%** |

### 2.2 Dispatcher 集成总览

所有子系统在 turn-end hook 中的 dispatcher 集成状态:

| RuntimeActionType | Handler | 注册状态 | Fake 路径 | Real 路径 | Evidence Level |
|-------------------|---------|---------|-----------|-----------|----------------|
| MEMORY_TURN_END_PROPOSAL | MemoryTurnEndProposalHandler | COMPLETE | COMPLETE | COMPLETE | L3 (runtime_e2e) |
| MEMORY_PROPOSE | MemoryRetainHandler | COMPLETE | COMPLETE | COMPLETE | L3 |
| MEMORY_RECALL | MemoryRecallHandler | COMPLETE | COMPLETE | COMPLETE | L2 (harness_runtime_e2e) |
| MEMORY_CONSOLIDATE | MemoryConsolidateHandler | COMPLETE | COMPLETE | COMPLETE | L3 |
| TOOL_GATE | ToolGateHandler | COMPLETE | COMPLETE | COMPLETE | L3 |
| TOOL_REQUEST | (handler registered) | COMPLETE | COMPLETE | COMPLETE | L3 |
| TOOL_INVOKE | ToolInvokeHandler | COMPLETE | COMPLETE | COMPLETE | L3 |
| TOOL_RESULT | ToolResultFeedbackHandler | COMPLETE | COMPLETE | COMPLETE | L3 |
| CHECKPOINT_SAFE_SUMMARY | (handler registered) | COMPLETE | COMPLETE | COMPLETE | L3 |
| SKILL_SELECT | SkillRuntimeActionHandler | COMPLETE | COMPLETE (fake auto-select) | FAKE_ONLY | L3 |
| SUBAGENT_DELEGATE_L0 | SubAgentDelegateL0Handler | COMPLETE | FAKE_ONLY | FAKE_ONLY | L3 |
| STREAMING_PROVIDER_CALL | (handler registered) | COMPLETE | COMPLETE | COMPLETE | L3 |
| STREAMING_EVENT | (handler registered) | COMPLETE | COMPLETE | COMPLETE | L3 |
| CLI_SHOW_MEMORIES | (handler registered) | COMPLETE | COMPLETE | COMPLETE | L2 |
| CLI_SHOW_SUBAGENTS | (handler registered) | COMPLETE | COMPLETE | COMPLETE | L2 |

### 2.3 最大瓶颈 (Top 5 Gaps)

| 排名 | 瓶颈 | 影响子系统 | 严重程度 | 阻塞什么 |
|------|------|-----------|---------|---------|
| 1 | **SubAgent 无真实执行能力** | SubAgent, Dogfood | 🔴 CRITICAL | SubAgent 不能执行工具、不能调用 LLM、不是真正的"子代理" |
| 2 | **MCP 无真实 Transport** | MCP, Tool | 🔴 CRITICAL | 无法连接外部 MCP server、无法使用社区 MCP 工具 |
| 3 | **Skill 不执行** | Skill, Tool | 🔴 CRITICAL | Skill 只是文本模板，不能驱动 Agent 完成工作流 |
| 4 | **config.yaml dirty tracking** | Config, Security | 🟡 HIGH | API key 在 git 中（P1 安全风险） |
| 5 | **Skill Selector 无 LLM** | Skill | 🟡 HIGH | 关键词匹配不能理解复杂任务意图 |

---

## 3. 偏差诊断

### D1: 为什么 SubAgent E2E 未完成?

**根因**: 设计文档 `subagent-boundary-architecture.md` 明确将 SubAgent 定位为 L0 deterministic executor，并把真实 LLM/sandbox 标记为"platform team 明确授权后再启用"。这形成了一道**架构冻结墙**——任何将 SubAgent 推进到 L1 的工作都被归类为"需要架构决策"。

**证据**:
- `executor.py:23`: `execution_mode = getattr(context_package, "execution_mode", "local_fake")` — 硬编码 fake
- `descriptor.py:56`: `supported_modes: tuple[str, ...] = ("local_fake",)` — 只支持 fake
- `subagent_action.py:90`: `execution_mode="local_fake"` — 生产路径也硬编码

**影响**: SubAgent 当前功能等价于"命令别名"而非"子代理"。

### D2: 为什么 Skill E2E 未完成?

**根因**: Skill 系统的设计哲学明确将 Skill 定位为"文本模板"而非"可执行代理"。`invocation.py` 中的 `invoke_skill()` 返回 `visible_output=body`（markdown 文本），设计文档明确说"Skill 不拥有 Agent loop"、"Skill 不直接执行工具"。

**证据**:
- `invocation.py:175-176`: `visible_output=body, audit_record=audit` — 返回文本
- `SKILL_SYSTEM_SDD.md`: 明确声明 Skill 的边界
- Skill 目录仅有 4 个 SKILL.md 文件

**影响**: Skill 加载、选择、验证基础设施完整，但 Skill 本身不执行任何操作。

### D3: 为什么 MCP E2E 未完成?

**根因**: MCP 系统被设计为"架构 seam"——定义了完整的模型层（MCPToolDescriptor、MCPServerConfig、MCPClient protocol）和 config/policy/sanitizer 层，但真实 transport 被明确 defer。`mcp.py:3` 说"不实现真实 transport"。

**证据**:
- `mcp.py:1-7`: "本模块只定义 First Agent 未来接 MCP server 前的本地边界"
- `mcp_stdio.py` 存在但未完成
- 无 HTTP/SSE transport 实现

**影响**: MCP 配置管理、policy、sanitizer 全部就绪，但无法连接任何真实 MCP server。

### D4: 为什么 18 个 Loop 中只有 3 个直接推进子系统 E2E?

**偏差点**: Loop 1-18 的分布:
- 治理/证据/文档/分类: 15 loops (83%)
- 子系统 E2E: 3 loops (17% — Loop 3 Memory E2E, Loop 15 Memory Write Dispatcher, Loop 10 MCP docs)

**根因分析**:
1. **红队审计将问题框定为治理缺口**: 安全审计发现的 config dirty、证据链不完整、文档不一致等问题，被解释为"需要更多治理"
2. **治理工作有明确的完成标准**: 分类 taxonomy、证据 pipeline、doc consistency 都有非黑即白的通过标准，给人"完成感"
3. **"需要架构决策"冻结了真实 E2E**: B2-B8 被标记为需要架构决策，形成阻塞
4. **AutoRun 成为独立产品**: AutoRun 优化（Loop 14-18）从工具变成了目标

### D5: 哪些"治理"工作是必要的支撑，哪些是过度工程?

**必要支撑** ✅:
- Loop 4 (Runtime Entry Consolidation): 统一 dispatcher 入口，避免多路径
- Loop 6 (Checkpoint Schema Version): checkpoint 版本治理，防止静默损坏
- Loop 15 (Memory Write Dispatcher Migration): Memory 写入走统一 dispatcher
- Loop 3 (Memory E2E Recall): Memory 召回能力验证

**过度工程** ⚠️:
- Loop 7 (Test Taxonomy): 测试分类本身不是能力，是对能力的描述
- Loop 9/11/12 (Docs): 子系统边界文档、Skill 文档、UX 文档 — 在没有实现前过度文档化
- Loop 13 (Evidence Honesty): 证据诚实性标签 — 改了标签但没有改变实际能力
- Loop 16 (Evidence Taxonomy Guard Tests): 为分类写测试，不是为功能写测试
- Loop 17/18 (Dogfood Reclassification / CLI Honesty): 改报告措辞而非改能力

### D6: 当前架构是否支持所有子系统的统一主路径连接?

**是，架构已经支持。** `RuntimeActionDispatcher` + `run_main_loop` turn-end hook 已经提供了统一的集成点:
- 14 个 RuntimeActionType 全部注册
- turn-end hook 在每次 loop 结束时串行 dispatch 所有 action
- evidence chain 完整（L1-L4 分类、target_module_proof、provenance）
- Fake 和 Real 共享同一核心路径

**缺失的只是 handler 背后的真实执行能力**，不是架构。

### D7: AutoRun 在完整补齐路线图中的角色?

AutoRun 是**运维工具**，不是**能力目标**。在完整补齐路线图中:
- AutoRun 应降级为可选的 CI/自动化辅助
- 不应再有"AutoRun Loop"作为主要交付单位
- 真实能力验证应通过 dogfood harness + real API 完成

---

## 4. 完整补齐路线图

### Phase 1: 解冻真实 E2E — 清除架构阻塞 (预计 6-8 loops)

**目标**: 移除当前的架构冻结，为三个核心子系统建立真实 E2E 路径

#### Loop 1.1: config.yaml Security Fix
- [ ] 将 config.yaml 从 git tracking 中移除
- [ ] 创建 config.example.yaml 作为模板
- [ ] 验证 provider 从环境变量/.env 读取 api_key 的 fallback 路径
- [ ] 旋转可能已泄露的 API key
- **产出**: config.yaml dirty → clean, P1 安全风险消除

#### Loop 1.2: SubAgent L1 Executor — Real LLM
- [ ] 在 `execution_mode.py` 中添加 `LOCAL_LLM = "local_llm"` 模式
- [ ] 实现 `execute_local_llm()` — 使用 config provider 调用 LLM
- [ ] SubAgent 可获得自己的 tool subset（从 descriptor.allowed_tools 过滤）
- [ ] SubAgent 有自己的 loop（受 max_iterations 限制）
- [ ] Parent adjudication: SubAgent 结果需 Parent 审核
- **产出**: SubAgent 不再是字符串匹配

#### Loop 1.3: SubAgent L1 Safety Governance
- [ ] SubAgent tool allowlist 强制从 descriptor 读取
- [ ] SubAgent budget 上限硬编码（不超过 Parent 的 50%）
- [ ] SubAgent execution log 隔离（不污染 Parent tool_execution_log）
- [ ] Nested delegation 检测和阻断
- **产出**: SubAgent L1 的安全边界完整

#### Loop 1.4: MCP Real Transport — stdio
- [ ] 完成 `mcp_stdio.py` 实现
- [ ] 实现 `StdioMCPClient`: 启动子进程, JSON-RPC 通信
- [ ] 实现 `list_tools()` → 获取真实 MCP server tools
- [ ] 实现 `call_tool()` → 调用真实 MCP tool
- **产出**: MCP 可以连接真实 stdio server

#### Loop 1.5: MCP Real Transport — HTTP/SSE
- [ ] 实现 `HttpMCPClient`: HTTP transport
- [ ] 实现 `SseMCPClient`: SSE transport
- [ ] MCP server 健康检查和超时
- **产出**: MCP 支持全部标准 transport

#### Loop 1.6: MCP → Tool Registry Bridge (Real)
- [ ] 真实 MCP tools 自动注册到 ToolRegistry
- [ ] MCP tool 的 capability=network_fetch, risk_level 从 server 声明读取
- [ ] MCP tool 的 confirmation 策略（默认 always for network_fetch tools）
- **产出**: MCP tools 可在 unified tool pipeline 中使用

#### Loop 1.7: Skill Execution — Agent-in-Agent
- [ ] Skill body 不再只返回 markdown — 解析为可执行的指令序列
- [ ] Skill 获得自己的 tool subset（从 descriptor.allowed_tools）
- [ ] Skill execution 在 Parent runtime loop 内完成（不创建独立 Agent）
- [ ] Skill 有自己的 confirmation 上下文
- **产出**: Skill 从文本模板升级为可执行工作流

#### Loop 1.8: Skill Selector — LLM-Based (Optional Enhancement)
- [ ] 在 provider_kind=real 时, Skill 选择走 LLM（一次轻量 function call）
- [ ] Fallback: provider_kind=fake 时保留关键词匹配
- **产出**: 真实场景下 Skill 选择更准确

---

### Phase 2: 补齐子系统深度能力 (预计 6-8 loops)

**目标**: 每个子系统在已有 E2E 基础上补齐其标准完整能力集

#### Loop 2.1: Memory — LLM-Enhanced Consolidation
- [ ] MEMORY_CONSOLIDATE 在 provider_kind=real 时调用 LLM 做 semantic pattern detection
- [ ] 生成 structured semantic candidates（不只是 pattern 字符串匹配）
- [ ] LLM 调用的 token budget 受限（非主对话, 后台批处理）
- **产出**: Memory 能产生有质量的 semantic candidates

#### Loop 2.2: Memory — Proactive Reminder
- [ ] 在 turn-start 时检查是否有相关历史记忆需要主动提醒
- [ ] Reminder 以 system prompt section 形式注入
- [ ] 不自动 retain — 只提示, 不做决定
- **产出**: Memory 的"主动回忆"能力

#### Loop 2.3: Memory — Multi-Session Persistence Hardening
- [ ] Filesystem store 添加文件锁（fcntl/portalocker）
- [ ] Session ID 隔离（每个 session 独立 memory scope）
- [ ] Cross-session memory recall（跨会话记忆可读）
- **产出**: Memory 在生产多会话场景下安全

#### Loop 2.4: Tool — Budget & Quota
- [ ] 每 turn 工具调用上限（默认 5）
- [ ] 每种 capability 独立配额（file_write ≤ 3/turn, network_fetch ≤ 2/turn）
- [ ] 配额耗尽时给模型明确的 stop signal
- **产出**: 工具调用有硬预算保护

#### Loop 2.5: Skill — Skill Content Expansion
- [ ] 从 4 个 demo skill 扩展到 ~10 个生产可用 skill
- [ ] 每个 skill 有明确的 allowed_tools、测试用例、dogfood
- [ ] Blog-writing skill 实际执行: web search → outline → draft → edit
- **产出**: Skill 系统有实际可用内容

#### Loop 2.6: SubAgent — SubAgent Content Expansion
- [ ] 从 0 个 subagent 扩展到 3-5 个
- [ ] 典型 subagent: code-reviewer, web-researcher, data-analyzer
- [ ] 每个有 defined role, allowed_tools, max_iterations
- **产出**: SubAgent 系统有实际可用内容

#### Loop 2.7: Confirmation — Unify Forget Path
- [ ] CLI forget memory 从 DIRECT_CALL 迁移到 dispatcher
- [ ] Forget 走 confirmation pipeline（MEMORY_PROPOSE with FORGET）
- [ ] 统一所有 mutating CLI commands 的 dispatcher 路径
- **产出**: 无 DIRECT_CALL 绕过

#### Loop 2.8: Safety — Audit Trail Persistence
- [ ] action_log 持久化到 audit 文件（session 级别）
- [ ] 包含所有 RuntimeActionEvent 的 evidence
- [ ] 不包含 secret/API key
- **产出**: 可审计的操作记录

---

### Phase 3: 统一主路径硬化 (预计 4-6 loops)

**目标**: 所有子系统通过 unified main path 协调工作, 形成真正的 Agent Runtime

#### Loop 3.1: Unified E2E Flow — Tool + Memory + Skill
- [ ] 单个用户请求触发完整流程: Skill 选择 → Tool 执行 → Memory 写入
- [ ] 验证 evidence chain 跨越多个子系统
- [ ] Real API dogfood 覆盖此流程
- **产出**: 第一个跨子系统完整流程

#### Loop 3.2: Unified E2E Flow — SubAgent + Parent Adjudication
- [ ] Parent 委派 SubAgent → SubAgent 调用 LLM + Tools → 返回结果 → Parent 审核
- [ ] Adjudication: accept / reject / modify
- [ ] SubAgent 的 Memory 操作是否应传播到 Parent→ 设计决策
- **产出**: SubAgent 成为真正的子代理

#### Loop 3.3: Unified E2E Flow — MCP Tool in Main Path
- [ ] 用户请求触发 MCP tool 调用 (via ToolRegistry → MCP transport)
- [ ] MCP tool 结果参与 Memory proposal
- [ ] MCP tool 失败时的 graceful degradation
- **产出**: MCP 工具融入主路径

#### Loop 3.4: Streaming Hardening
- [ ] 验证 streaming 在 real provider 路径下的事件完整性
- [ ] Streaming + Tool use 并发场景（streaming 中触发 tool call）
- [ ] Streaming error recovery (connection drop mid-stream)
- **产出**: Streaming 生产级稳定性

#### Loop 3.5: Checkpoint Resume Hardening
- [ ] 完整的 checkpoint → resume 流程测试
- [ ] 包含 pending_tool / pending_user_input / memory proposal 的 resume
- [ ] Schema migration 测试（v1→v2 场景）
- **产出**: Checkpoint 的 resume 能力完整验证

#### Loop 3.6: Error Boundary Hardening
- [ ] 子系统故障隔离（一个 handler 崩溃不阻塞其他 handler）
- [ ] Provider 错误重试策略（exponential backoff, max 3 retries）
- [ ] Graceful degradation 路径（MCP server 不可用时）
- **产出**: 生产级错误恢复

---

### Phase 4: 质量闭环 (预计 4-6 loops)

**目标**: 完整 dogfood 覆盖、性能基准、文档同步

#### Loop 4.1: Full Real API E2E Dogfood — All Subsystems
- [ ] dogfood 覆盖 SubAgent L1 real execution
- [ ] dogfood 覆盖 MCP real transport
- [ ] dogfood 覆盖 Skill execution flow
- [ ] 所有 dogfood 通过 (100%, not 19/20)
- **产出**: 全子系统 real API dogfood 绿色

#### Loop 4.2: Performance Baseline
- [ ] Turn latency 基准测量 (fake vs real)
- [ ] Memory store 读写性能基准
- [ ] Checkpoint save/load 性能基准
- [ ] SubAgent dispatch 开销基准
- **产出**: 性能基线文档

#### Loop 4.3: Doc Sync — Update All Design Docs
- [ ] 更新 ARCHITECTURE.md: 反映所有 Phase 1-3 变更
- [ ] 更新 PROJECT_STATUS.md: B2-B8 解冻, 状态重分类
- [ ] 更新 README.md: 真实能力描述
- [ ] 淘汰过时文档 (标记 deprecated 或归档)
- **产出**: 文档与代码一致

#### Loop 4.4: Doc Sync — Subsystem SDDs
- [ ] 更新 SKILL_SYSTEM_SDD.md: 反映执行能力
- [ ] 更新 SUBAGENT_SYSTEM_SDD.md: 反映 L1 能力
- [ ] 创建 MCP_SYSTEM_SDD.md (当前缺失)
- **产出**: 所有子系统有准确的设计文档

#### Loop 4.5: AutoRun Simplification
- [ ] AutoRun 从"独立产品"降级为 CI helper
- [ ] 移除 AutoRun 的 stage promotion gates（简化）
- [ ] 移除 recursive backtrack policy（简化）
- [ ] 保留: skill routing tables for CI, dogfood auto-trigger
- **产出**: AutoRun 回归工具定位

#### Loop 4.6: Final Audit — Capability Verification
- [ ] 在此审计报告基础上做最终差距扫描
- [ ] 确认所有 NOT_STARTED / FAKE_ONLY / STUB 项已解决
- [ ] 确认 80%+ 能力项为 COMPLETE
- **产出**: 最终审计报告, 项目可声称 "capability-solid CLI-first Agent Runtime"

---

### 路线图总览

| Phase | Loops | 主要子系统 | 完成后的状态 |
|-------|-------|-----------|-------------|
| Phase 1: 解冻 | 1.1-1.8 (8 loops) | SubAgent, MCP, Skill, Config | 三个核心子系统具备 real E2E 路径 |
| Phase 2: 补齐深度 | 2.1-2.8 (8 loops) | Memory, Tool, Skill, SubAgent, Safety | 各子系统标准完整能力集就绪 |
| Phase 3: 主路径硬化 | 3.1-3.6 (6 loops) | 全部 | 跨子系统协作、生产级稳定性 |
| Phase 4: 质量闭环 | 4.1-4.6 (6 loops) | Dogfood, Docs, AutoRun | 全量测试覆盖、文档同步、最终审计 |

**总计: 28 loops, 分 4 个 Phase**

---

## 5. 优先级排序

### 紧急度排序

| 优先级 | Loop | 理由 |
|--------|------|------|
| P0 | **1.1** (config.yaml fix) | 安全风险 — API key 在 git 中, 必须立即修复 |
| P0 | **1.2** (SubAgent L1) | SubAgent 当前是字符串匹配, 阻塞所有 SubAgent 相关工作 |
| P0 | **1.4** (MCP stdio) | MCP 无真实 transport, 阻塞所有 MCP 相关工作 |
| P1 | **1.3** (SubAgent Safety) | 必须在 SubAgent L1 上线前完成安全治理 |
| P1 | **1.7** (Skill Execution) | Skill 从文本模板升级为可执行工作流 |
| P1 | **2.1** (LLM Consolidation) | Memory 的 LLM 增强是 Memory 完整能力的关键 |
| P2 | **1.5** (MCP HTTP/SSE) | 扩展 MCP transport 支持 |
| P2 | **1.6** (MCP→Tool Bridge) | 连接 MCP tools 到统一 tool pipeline |
| P2 | **2.2-2.8** | 各项子系统深度补齐 |
| P3 | **3.1-3.6** | 统一主路径硬化 |
| P4 | **4.1-4.6** | 质量闭环 |

### 依赖图

```
1.1 (config) ─────────────────────────────────────────────────────────────┐
                                                                          │
1.2 (SubAgent L1) ──► 1.3 (SubAgent Safety) ──► 2.6 (SubAgent Content) ──┤
                                                                          │
1.4 (MCP stdio) ──► 1.5 (MCP HTTP/SSE) ──► 1.6 (MCP→Tool Bridge) ───────┤
                                                                          │
1.7 (Skill Exec) ──► 1.8 (Skill Selector LLM) ──► 2.5 (Skill Content) ───┤
                                                                          │
                                                                          ▼
                                                              Phase 3 (Unified Path)
                                                                          │
                                                                          ▼
                                                              Phase 4 (Quality)
```

Phase 1 的 1.2/1.4/1.7 可以并行推进（各自独立）。

---

## 6. 附录

### A. 文件引用索引

审计过程中读取的关键文件:

| 文件 | 子系统 | 行数 |
|------|--------|------|
| `agent/loop.py` | Runtime | 826 |
| `agent/core.py` | Runtime | 1109 |
| `agent/tool_registry.py` | Tool | 436 |
| `agent/tool_executor.py` | Tool | 575 |
| `agent/runtime_integration/dispatcher.py` | Runtime | 546 |
| `agent/runtime_integration/schema.py` | Runtime | 231 |
| `agent/runtime_integration/memory_retain.py` | Memory | 285 |
| `agent/runtime_integration/memory_consolidate.py` | Memory | 122 |
| `agent/runtime_integration/memory_recall.py` | Memory | 133 |
| `agent/runtime_integration/skill_action.py` | Skill | 254 |
| `agent/runtime_integration/subagent_action.py` | SubAgent | 167 |
| `agent/subagent_system/executor.py` | SubAgent | ~50 |
| `agent/skill_system/selector.py` | Skill | ~100 |
| `agent/skill_system/invocation.py` | Skill | ~200 |
| `agent/memory_store.py` | Memory | ~80 |
| `agent/memory_fs_store.py` | Memory | ~150 |
| `agent/memory_runtime.py` | Memory | ~100 |
| `agent/memory_confirmation.py` | Memory | 302 |
| `agent/mcp.py` | MCP | 80+ |
| `agent/checkpoint.py` | Storage | 80+ |
| `agent/provider/fake_provider.py` | Provider | 60+ |
| `config/config.yaml` | Config | 11 |
| `scripts/dogfood_global_real_api.py` | Dogfood | 80+ |
| `scripts/dogfood_subagent_system.py` | Dogfood | ~200 |
| `scripts/dogfood_skill_system.py` | Dogfood | ~150 |

### B. Loop 1-18 分类统计

| 类别 | Loop 编号 | 数量 | 占比 |
|------|----------|------|------|
| 子系统 E2E 推进 | 3, 15 | 2 | 11% |
| 治理/证据/文档 | 1, 2, 4, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18 | 14 | 78% |
| MCP Docs | 10 | 1 | 5.5% |
| 内存架构 | 5 | 1 | 5.5% |

### C. 审计方法论

本审计采用以下方法:
1. **代码级证据**: 每个能力项的状态由实际代码行、函数签名、参数硬编码值确定
2. **Dispatcher 路径追踪**: 追踪每个 RuntimeActionType 从 turn-end hook → dispatcher → handler → target module 的完整路径
3. **Fake/Real 双路径验证**: 区分"只在 fake provider 下工作"和"fake + real 都工作"
4. **Dogfood 覆盖对照**: 将 dogfood 脚本覆盖范围与子系统能力清单交叉对照
5. **历史审计交叉验证**: 对照 2026-05-27 的三份审计报告，追踪建议是否被采纳

---

> 审计完成时间: 2026-05-28
> 审计人: Claude Code (plan-eng-review)
> 状态: 只读审计完成，未修改代码或文档

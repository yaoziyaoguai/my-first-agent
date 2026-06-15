# Global Agent Reality Audit（全局事实审计 · Discovery Only）

- 日期：2026-06-15
- 性质：只读全局事实审计。不改代码、不改测试、不删/不归档文档、不实现/不删除任何能力。
- 执行者：Claude Code（Opus 4.8, 1M context）。
- 证据基线：静态源码阅读 + graphify 图谱发现 + 7 个并行只读子代理分区取证 + 关键判断的源码二次核验。**未运行测试、未做真实 provider 端到端执行**——所有“可达 / 默认开关”结论来自代码路径与默认值，不等于运行期已验证。

> 证据分级约定：本文用 **【事实】** 标注可由 `file:line` 直接核验的代码事实；用 **【推断】** 标注基于事实的判断；用 **【建议】** 标注下一步建议（本轮不执行）。

---

## 0. Executive Verdict（执行结论）

当前项目不是玩具 chatbot。从源码事实看，它是一个**本地、单进程、CLI/TUI 驱动的、带治理（policy/confirmation gate）、可恢复（checkpoint/resume）、可审计（per-session evidence）的 tool-calling agent runtime kernel**：存在真实的 `规划 → model loop → 工具裁决执行 → 状态迁移` 闭环，且默认就有工具策略门、状态机、检查点恢复与逐 session 证据落盘。

但有三个必须并列说出的现实约束：

1. **默认 provider 是 `FakeProvider`**（`agent/provider/factory.py:90`）。即开箱默认形态是一个**确定性 runtime / 本地开发与测试骨架**，而不是默认接真实 LLM 的智能体。要变成“真 LLM agent”必须显式配置 provider + API key。
2. **大量能力是“结构已接、默认未启用 / 未生产路由”的 seam**：scheduler、MCP、subagent V0 路由、memory emergence、LLM 巩固、real provider、turn-end checkpoint、trace 等，默认全部关闭或无生产注入者。容易把“已注册 / 有 handler / 有测试”误读为“主链路已用”。
3. **文档与测试的体量远大于真实产品闭环**，且其中很大一部分是“架构修复期”留下的历史叙事（修复窗口、模块成熟度评分、边界 inventory）。这些叙事在多处**系统性高估**了系统相对“默认生产路径”的成熟度，并且没有单一权威的“当前状态”文档。

因此后续顺序应当是：**先把现状钉死成一份高质量 Current System State，再据此做文档规范化与分批归档，再做测试分层与清理，最后才讨论未来形态**。现在不应继续按旧的模块分母补能力，也不应立刻大规模删文档/删测试。

---

## 1. Scope and Non-goals（范围与非目标）

本轮**只做审计**。明确不做：

- 不改任何生产代码；不改、不删任何测试；不删除、不归档任何文档。
- 不做未来产品规划，不定死未来 agent 形态。
- 不重开架构修复，不开启新的修复窗口。
- 不实现也不删除 scheduler；不改 North Star；不改架构修复 closure 类文档。
- 不声称所有模块均已达 L3；不声称已达到最高 default-on 成熟等级。
- 不提交 graphify 输出目录、不提交 `.claude/settings.json`、不提交 `CLAUDE.md`；不 push。

唯一产物：本文件 `docs/08-global-audit/GLOBAL_AGENT_REALITY_AUDIT.zh.md`。

---

## 2. Method（方法）

1. **graphify 图谱发现优先**：按仓库规则先用 `graphify query` / `graphify path` 做 orientation（入口、`chat()` 邻域、loop 与 chat 的连接、scheduler 邻域、skill 子系统）。graphify 只用于发现，不作为最终证据。
2. **源码二次核验**：所有 load-bearing 结论都回到 `agent/*.py`、`main.py` 的具体行核验。
3. **并行分区取证**：派 7 个只读子代理分别审 `loop/scheduler/provider`、`tool/policy/confirmation`、`memory`、`skill/subagent/mcp`、`state/checkpoint/observability`、`tests`、`docs`，要求每条结论带 `file:line`，并强制区分“有文件 vs 有 runtime consumer”“测试接 vs 生产接”。
4. **对待旧文档**：旧文档作为“文档自己怎么说”的证据来源，不作为代码事实；凡 maturity / closure / 数量类 claim 一律标注需代码核验，并以代码为准。
5. **生产主链路 / 测试 harness / 历史 claim 三者分离**：production dispatcher 由 `agent/runtime_integration/phase1_hook.build_phase1_dispatcher()` 构建；测试用 `tests/.../_build_phase1_dispatcher` 自建——两者不混为一谈。

### 2.1 方法完整性说明（一处子代理纠错）

子代理初版曾报告“`skills/` 目录为空、skill 候选为零”。**二次核验推翻该结论**：它误看了 `agent/skills/`（tombstone，`__all__=[]`，`agent/skills/__init__.py`），而 `SkillRegistry` 实际扫描的是**项目根 `skills/`**，内有 3 个带 frontmatter 的真实 skill（见 §6）。本文采用核验后的事实。这条记录用于说明：本轮对子代理输出做了独立核验，而非直接采信。

---

## 3. Repository Shape（仓库结构概览）

【事实】顶层关键目录与文件：

- 代码：`agent/`（约 100+ 个顶层 `.py` + 子包 `cli/ confirmation/ input_backends/ provider/ runtime_integration/ skill_system/ skills/ subagent_system/ subagents/ tools/`）、`main.py`(767 行)、`config.py`、`llm/`、`tui/`、`config/`。
- 入口与编排核心：`main.py`、`agent/core.py`(2275 行)、`agent/loop.py`(1061 行)、`agent/session.py`(832 行)、`agent/tool_runtime_mediator.py`(1354 行)。
- 测试：`tests/`，314 个 `test_*.py`（322 个 `.py`）。子目录：`unit/`(10)、`runtime_integration/`(87)、`golden_e2e/`(7)、`smoke/`(1)、`adversarial/`(1)、`fixtures/`，其余约 208 个在 `tests/` 根。
- 文档：`docs/`，约 55 个 `.md`。编号目录 `00-overview / 01-getting-started / 02-architecture / 06-audit / 07-module-maturity`，外加 `architecture/ design/ dev/ plans/ real-e2e/ rfc/`。**缺 `03/04/05` 编号**，与 2026-06-10 前后的一次清理/重组吻合。
- 运行期产物（非源码）：`sessions/`（603 项，per-session 证据）、`memory/`（checkpoint 存储）、根目录多份 `agent_log*.jsonl`（含已归档的 50MB 级文件）。**这些产物说明该 agent 确实被实际运行过，不是纯理论骨架。**
- 历史/修复类目录特征明显：`docs/06-audit/`（修复证据）、`docs/07-module-maturity/`（成熟度评分工作目录）。

---

## 4. Current Agent Shape（当前 Agent 形态）

【推断，基于下列事实】当前形态最接近：**带治理与可恢复性的本地 tool-calling agent runtime kernel（默认运行在确定性 Fake provider 上）**。它同时带有 task-agent（多步 plan + 状态机）与 memory-aware agent 的成分，但**不是** workflow engine（没有生产路由的 scheduler/编排），也**不是**默认接真实 LLM 的产品级 agent。

支撑判断的事实来源：

- 来自**源码**：真实规划阶段 `_run_planning_phase`（`agent/core.py:1249`）；真实 model loop `agent/loop.py:966` 的 `while True`；工具裁决管线 `tool_runtime_mediator.mediate()`（gate→policy→confirm→execute→result）；状态机 `agent/state.py`+`agent/transitions.py`；checkpoint/resume（`agent/session.py:405`）；per-session 证据 `evidence_recorder` + `EventLogWriter`。
- 来自**源码（约束面）**：默认 `FakeProvider`（`agent/provider/factory.py:90`）；scheduler 无生产注入（`agent/action_scheduler.py:6` 自述 not-routed）；MCP 默认关（`main.py:587-589`）；subagent V0 路由默认关（`agent/subagent_routing_flag.py:41`）。
- 来自**测试**：`golden_e2e/` 用 FakeProvider 锁端到端行为；`test_main_loop.py` 驱动单/多轮 + tool-use cycle；说明“闭环”有行为回归保护。
- 来自**文档**：文档自述定位为“developer prototype / local development”（`docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md`），与代码事实一致；但部分概览文档措辞偏乐观（见 §9）。

---

## 5. Approximate Runtime / Agent Mainline（近似主链路）

【事实】默认（plain CLI / TUI）主链路：

```
main.py: main()                                  main.py:637  入口、provider banner、入口命令解析、session_id、可选 MCP bridge、evidence/EventLogWriter 注入
  └─ init_session() + try_resume_from_checkpoint()  main.py:730-731  启动诊断(health_check 一次)、resume
  └─ main_loop() / run_textual_main_loop()       main.py:335 / 314  I/O 输入循环
       └─ read_user_input_event + classify_user_input   收口 empty/exit/cancel/eof 等 UI 输入意图
       └─ _run_chat_for_backend()                main.py:195  按 backend 分派；记录 user_input evidence
            └─ agent.core.chat()                 agent/core.py:763  turn 编排唯一入口
                 ├─ (early-return 特例) CLI meta-command / 委托 / memory 评估   见下
                 ├─ _run_planning_phase()         agent/core.py:1249  新任务时规划（一次 model 调用）
                 └─ _run_main_loop()              agent/core.py:1777  public seam wrapper
                      └─ agent.loop.run_main_loop()   agent/loop.py:940 真实 while-loop
                           ├─ (可选) action_scheduler 预处理   agent/loop.py:1007  默认 None → 跳过
                           ├─ call_model()         agent/model_call.py  调 provider（默认 Fake）
                           └─ dispatch_model_output() → 工具裁决       agent/loop.py:1033
```

`agent/provider/fake_provider.py:12` 自证统一路径：`core.chat → run_main_loop → call_model`，fake/real **不分叉**。

**清晰的地方**【事实】：
- 入口唯一、turn 编排唯一（`core.chat()`）；planner 与 model loop 真实存在并相连。
- 工具调用从 model 输出 → `ToolRuntimeMediator.mediate()`（`agent/tool_runtime_mediator.py:225`）：`_route_gate()`(ToolGateHandler) → `_enforce_policy_gate()`(`policy_decision.classify_policy_action`) → confirmation_required 则置 `pending_tool` 并存 checkpoint → `execute_single_tool()`(`agent/tool_executor.py`) → 结果反馈。
- 状态/恢复清晰：状态机在多步 plan 路径强制（`validate/apply_task_transition`，`agent/core.py:993,1588,1673`）；checkpoint save 由 transition 驱动（不依赖 `checkpoint_save_on_turn_end`），resume 在启动序列必经。
- 输出清晰：以 `on_runtime_event`(RuntimeEvent) 为主路径，`on_output_chunk/on_display_event` 为 deprecated 兼容桥。

**不清晰 / 需要警惕的地方**【事实】：
- `chat()` 入口有多条 **early-return 特例路径**，显式标注“CLI-ONLY / DEMO-ONLY，绕过 loop.py/dispatcher/evidence path，但不是第二条 runtime”：CLI meta-command（`agent/core.py:877-887`）、`_looks_like_delegate_to_subagent`（`:895`）、`_looks_like_nl_delegation`（`:928`，自述 demo fixture）。它们在主 loop 之前 return，是治理/可观测的盲区，也是维护风险。
- 单步（无 plan）路径有意绕过状态机直接走 LLM（`agent/transitions.py:196-200` 注释为设计意图）。

**只在测试中连接起来的地方**【事实】：
- `action_scheduler` 的“生产消费”：loop 消费侧已写好（`agent/loop.py:1007`），但生产无任何代码构造并注入 `ActionScheduler`；`agent/action_scheduler.py:231` 的 `ActionScheduler(...)` 仅是类 docstring 示例。注入只发生在测试。

---

## 6. Capability / Module Discovery（能力/模块发现）

下列模块边界来自代码事实，不套用旧的固定模块表。每条给位置、是否主链路使用、证据。

**Agent Loop / Runtime**【事实，Active mainline】
- `agent/loop.py:940 run_main_loop` + `agent/loop.py:678 LoopDependencies`；`while True` 在 `:966`；`call_model` 在 `:1030`；`dispatch_model_output` 在 `:1033`，返回非 None 即 end_turn 退出。`core.chat → _run_main_loop(:1777) → run_main_loop` 为唯一编排路径。

**Planner**【事实，Active mainline】
- `agent/core.py:1249 _run_planning_phase`，每个新任务（无 `current_plan`）触发一次规划 model 调用；已有 running plan 则跳过直接进 loop（`agent/core.py:1224-1231`）。`agent/planner.py`、`agent/plan_schema.py` 为其支撑。

**Tool System**【事实，Active mainline】
- 注册入口 `agent/tools/__init__.py`（import 即注册）。模型可见内置工具 13 个：`read_file`、`read_file_lines`、`write_file`、`edit_file`、`run_shell`、`fetch_url`、`mark_step_complete`、`request_user_input`、`memory_list`、`memory_remember_request`、`memory_forget_request`、`demo_echo_task_summary`、`demo_write_demo_note`；另有 `_safe_noop`/`_confirmable_noop` 仅供 gate 测试（模型不可见）。
- 裁决核心 `agent/tool_runtime_mediator.py`，执行 `agent/tool_executor.py`，注册表 `agent/tool_registry.py`。

**Policy / Approval**【事实，Active mainline（本地范围）】
- `agent/policy_decision.py`（纯函数）经 `tool_runtime_mediator._enforce_policy_gate()`（`:1102`）消费：`TOOL_WRITE→REQUIRE_APPROVAL→confirmation_required`，`TOOL_READ→ALLOW`。即“写操作必须用户确认”在主链路强制。
- 注意：异常分支注释写 “fail-open” 但实际 `return "confirmation_required"`（fail-closed）——执行语义安全，但注释误导（`agent/tool_runtime_mediator.py:1128-1130`）。【风险见 §10】

**Security**【事实，混合】
- `agent/security.py:is_sensitive_file()` 嵌入 `read_file`/`run_shell` 工具实现层，拦截 `.env/.pem/.key/config.* / secret|token|password` 等（`agent/tools/file_ops.py:16`、`agent/tools/shell.py:127`）→ Active mainline。
- `security.needs_confirmation()` 已被 `tool_registry.needs_tool_confirmation()` 取代，**无生产 caller**（仅 4 个测试）→ Legacy/dead-code 风险。
- `security.confirm_tool_call()` 用阻塞 `input()`，无生产 caller → Prototype-dormant。

**State / Checkpoint / Resume**【事实，Active mainline】
- 状态机 `agent/state.py`（`KNOWN_TASK_STATUSES` 11 值 + terminal=done/failed/cancelled）、`agent/transitions.py`（27 条迁移规则）。
- checkpoint 存 `memory/checkpoint.json`（v1）或 `memory/checkpoints/{session_id}/{run_id}.json`（v2）。save 由 transition 驱动（`agent/core.py:1005,1322,1641,1707`），与默认关闭的 `checkpoint_save_on_turn_end` 无关。resume 启动必经（`agent/session.py:405`）。

**Memory / Context**【事实，主链路 + 大量支撑/CLI/seam】
- 每轮 `core.chat()` 调 `MemoryRuntime.evaluate_user_text()`（`agent/core.py:961`）：policy(`memory_policy`)→confirmation(`memory_confirmation`)→operation(`memory_operations`)→store。prompt 注入 `memory_snapshot_generator.build_memory_snapshot_from_store()`。→ 这些为 Active mainline。
- session 结束触发 `extract_memories_from_session()`（`agent/session.py:603`→`agent/memory.py:444`），其下 `_maybe_run_consolidation/_maybe_run_emergence`（`agent/memory_runtime_hooks.py:22,139`）→ 巩固链 Supporting mainline。
- 持久化需显式开关：`MEMORY_STORE_BACKEND=filesystem` + `MEMORY_STORE_ROOT/MEMORY_ROOT`，否则降级 `InMemoryMemoryStore`（`agent/memory_fs_store.py:56-62`、`agent/memory_runtime.py:853`）。
- CLI-only：`memory_review`、`memory_consolidation_review`、`memory_extraction_review`、`memory_maintenance_cli`、`memory_index`、`memory_archive`。
- 默认关闭 seam：`memory_emergence`（`MEMORY_EMERGENCE_ENABLED`）、`memory_consolidation_llm`（`_is_llm_consolidation_enabled()`，`agent/memory_consolidation_llm.py:514`）。
- Prototype-dormant：`memory_suggestions`（`create_memory_runtime` 默认传 `None`）。Legacy-unclear：`memory_provider`。

**Skills / Capabilities**【事实，Active wiring，候选非空（已纠错）】
- `core.chat()` 构建 `SkillRegistry(roots=[Path("skills")])`（`agent/runtime_integration/phase1_hook.py:61`，`agent/core.py:839`），turn 起始非空输入时 `SkillCandidateRetriever().retrieve()` 注入 selection section（`agent/core.py:527-538`）。
- 真实 skill 描述符 3 个：`skills/blog-writing/SKILL.md`、`skills/demo-note-maker/SKILL.md`、`skills/evil-skill/SKILL.md`（均含 frontmatter、`status: active`；`evil-skill` 为对抗/安全测试用）。`agent/skills/__init__.py` 是 tombstone（`__all__=[]`，隔离旧 prototype）。

**SubAgent**【事实，Optional seam（默认关）+ demo 描述符】
- L0 handler（`SUBAGENT_DELEGATE_L0`，`agent/runtime_integration/phase1_hook.py:170-173`）= inline-local probe，不起真实子 loop。L1/V0 handler 已注册（`:179-182`）但注释明确 production routing 未完成。
- V0 路由开关 `SUBAGENT_V0_ROUTING_ENABLED` 默认 `False`（`agent/subagent_routing_flag.py:41`）；flag-off 走 inline-local fallback。
- 描述符 3 个全为 demo/验证用：`demo-stat`、`code-reviewer`、`demo-stat-real`（`agent/subagent_system/descriptors/`）。NL 委托 `_looks_like_nl_delegation` 是 demo 关键词 fixture。→ 默认无可达的生产级子代理委托。

**MCP**【事实，Optional seam（默认关）】
- `main.py:587-589` env `MY_FIRST_AGENT_MCP_ENABLE` 默认关；关闭时 `run_mcp_bridge(mode="disabled")` 返回全零 report（`agent/mcp_bridge.py:168-178`），且默认 `dry_run=True`。仓库内无真实 MCP server 配置文件。
- dispatcher 注册了 `MCPBridgeLifecycleHandler`（仅 evidence）；真实把 MCP 工具写入 `TOOL_REGISTRY` 需 opt-in + 配置 + 非 dry-run，默认零生效。

**Scheduler / Async**【事实，wired-but-no-producer seam】
- `agent/action_scheduler.py:225 ActionScheduler`；loop 消费侧 `agent/loop.py:1007`；dispatcher 侧已注册 handler。但生产无注入者（`agent/action_scheduler.py:6` 自述 not-routed），仅测试注入。

**Observability / Evidence**【事实，多通道分层】
- per-session 证据：`evidence_recorder.record_evidence()` → `EventLogWriter` → `sessions/{id}/events.jsonl`（`main.py:715-726` 注入；调用点多被 try/except 包裹 → Supporting mainline）。
- 轻量索引：`logger.log_event()` → `agent_log.jsonl`（无 try/except → Active mainline）。
- 结构化迁移日志：`runtime_observer` 在每次 `apply_task_transition` 写（Supporting mainline）；其 stdout debug 默认关。
- opt-in trace：`runtime_trace_emitter/projection` 默认 `on_trace_event=None`，全路径 no-op。
- 【风险见 §10】存在多套并行观测路径与同事实双写（如 checkpoint 同时走 `logger` 与 `evidence_recorder`）。

**Runtime Decision Spine / Dispatcher**【事实，Supporting/Active mainline】
- `RuntimeActionDispatcher`（`agent/runtime_integration/dispatcher.py`）由生产 `build_phase1_dispatcher()` 构建并在 `core.chat()` 使用；handler 含 tool_gate / tool_invoke(evidence-only) / tool_result_feedback / 各 memory action / checkpoint / mcp lifecycle / scheduler / subagent。

**Health check**【事实，Supporting mainline】
- `run_health_check()` 在 `init_session()` 启动调用一次，结果仅用于 session header 展示，不影响状态机/checkpoint。

---

## 7. Mainline Coupling Summary（主链路耦合度汇总）

| Capability / area | Evidence (file:line) | Coupling level |
|---|---|---|
| Agent loop `run_main_loop` + `call_model` | `agent/loop.py:966,1030,1033` | Active mainline |
| Planner `_run_planning_phase` | `agent/core.py:1249` | Active mainline |
| Tool 裁决/执行（mediator/executor/registry/tools） | `agent/tool_runtime_mediator.py:225`、`agent/tool_executor.py`、`agent/tools/__init__.py` | Active mainline |
| Policy gate（写操作必确认） | `agent/tool_runtime_mediator.py:1102`、`agent/policy_decision.py` | Active mainline（本地范围） |
| Security `is_sensitive_file` | `agent/tools/file_ops.py:16`、`agent/tools/shell.py:127` | Active mainline |
| State machine（多步 plan 路径） | `agent/core.py:993,1588,1673`、`agent/transitions.py` | Active mainline |
| State machine（单步 no-plan 路径） | `agent/transitions.py:196-200` | Optional seam（设计意图绕过） |
| Checkpoint save（transition 驱动） | `agent/core.py:1005,1322,1641,1707` | Active mainline |
| Checkpoint resume（启动必经） | `agent/session.py:405` | Active mainline |
| Memory evaluate / snapshot / confirmation | `agent/core.py:961`、`agent/memory_snapshot_generator.py:47` | Active mainline |
| Memory session-end extraction + consolidation | `agent/session.py:603`、`agent/memory_runtime_hooks.py:22` | Supporting mainline |
| Skill registry + selection retriever | `agent/core.py:527-538,839` | Active mainline（候选=3 真实 skill） |
| RuntimeActionDispatcher (phase1) | `agent/runtime_integration/phase1_hook.py:64` | Supporting mainline |
| evidence_recorder + EventLogWriter | `main.py:715-726` | Supporting mainline |
| logger.log_event → agent_log.jsonl | `agent/logger.py:150` | Active mainline |
| runtime_observer（结构化迁移日志） | `agent/transitions.py:580` | Supporting mainline |
| Health check（启动一次） | `agent/session.py:324` | Supporting mainline |
| Real providers（anthropic/openai） | `agent/provider/factory.py:19-30` | Optional seam（需配置/key） |
| action_scheduler | `agent/action_scheduler.py:6`、`agent/loop.py:1007` | Prototype / dormant（wired, no producer） |
| MCP bridge / 工具注册 | `main.py:587-589`、`agent/mcp_bridge.py:168-178` | Optional seam（默认关） |
| SubAgent V0 routing | `agent/subagent_routing_flag.py:41`、`phase1_hook.py:179-182` | Optional seam（默认关，routing 未完成） |
| NL delegation fixture | `agent/core.py:928` | Prototype / dormant（demo fixture） |
| SubAgent 描述符（3 个） | `agent/subagent_system/descriptors/*` | Prototype（全 demo/验证） |
| memory_emergence | `agent/memory_runtime_hooks.py:139` | Optional seam（默认关） |
| memory_consolidation_llm | `agent/memory_consolidation_llm.py:514` | Optional seam（默认关） |
| memory_suggestions | `agent/memory_runtime.py`（工厂默认 None） | Prototype / dormant |
| runtime_trace_emitter/projection | `agent/core.py:769` | Optional seam（默认关） |
| turn-end checkpoint hook | `agent/core.py:774` | Optional seam（默认关） |
| memory CLI 家族（review/maintenance/index/archive） | `agent/cli/commands.py:31` 等 | CLI-only |
| security.needs_confirmation | 仅测试 caller | Legacy / unclear |
| security.confirm_tool_call | 无生产 caller | Prototype / dormant |
| confirm_handlers.py（根级） | 未确认现役 import | Legacy / unclear |
| memory_provider | 无直接生产 caller | Legacy / unclear |

> 凡 Legacy/unclear 即“证据不足以下定论”，本轮不强行归类。

---

## 8. Test Suite Reality（测试现状）

【事实】总量：314 个 `test_*.py`。分布：`tests/` 根 ~208、`runtime_integration/` 87、`unit/` 10、`golden_e2e/` 7、`smoke/` 1、`adversarial/` 1。前 15 大文件合计约 22k 行（约占测试代码 18%）。

- **核心回归测试（验证主链路）**【事实】：`tests/test_main_loop.py`(chat 单/多轮 + tool-use cycle)、`tests/test_state_invariants.py`、`tests/unit/test_task_transitions.py`(1286 行)、`tests/test_resume_full_flow.py`、`tests/test_provider_contract.py`、`tests/test_policy_decision_golden.py`、`tests/test_policy_tool_gate_integration.py`、`tests/runtime_integration/test_phase1_real_core_loop.py`、`tests/runtime_integration/test_tool_pipeline_l3_completion.py`(1118 行)、`tests/golden_e2e/*`(7 个 FakeProvider 端到端快照)。这些是真正保护行为的回归层。
- **架构修复期遗留测试**【事实】：`tests/test_architecture_boundaries.py`(2529 行，边界/import/window 扫描)、`tests/test_docs_source_of_truth.py`(断言具体文档存在 + 字符串 pattern)、`tests/test_capability_boundary_contract.py`、`tests/test_command_boundary_characterization.py`、`tests/runtime_integration/test_legacy_path_inventory.py`、`tests/test_local_artifacts_inventory.py`、`tests/*_hygiene.py / test_gitignore_runtime_artifacts.py`。这些多用 AST/import 扫描而非行为断言。
- **test harness / fixtures**【事实】：`tests/conftest.py`(`FakeAnthropicClient` 等，强制 `ANTHROPIC_BASE_URL=https://example.invalid` 杜绝真实网络)、`tests/runtime_integration/subagent_v0_contract_helpers.py`、`tests/fixtures/minimal_*mcp*server.py`。
- **可能冗余/脆弱**【推断】：
  - 绑旧阶段编号的薄兼容索引（如 `tests/test_v0_4_transition_boundaries.py` 仅 1 个“文件按行为切分”断言、`tests/test_v0_2_rc_automated_smoke.py`）。
  - 硬编码 import 清单 / 文档名的扫描断言（`test_architecture_boundaries.py`、`test_docs_source_of_truth.py`）——合法重命名即 false failure。
  - pre-U3 “missing-contract” scaffold（`subagent_v0_contract_helpers.py` 的 `MissingSubAgentV0Contract`）——若契约已落地，部分 RED 测试可能已成死重。
  - 断言 deprecated `output_callback` 语义的用例（`test_main_loop.py:182,255`）——若 RuntimeEvent 已完全取代，则属历史负债。
  - B7 Red/Green 对称类——若 slice 已合并，Red 类可能成死重。
  > 以上“可能冗余/脆弱”均为静态判断，**未经运行确认**；清理前需逐个跑过并比对实现状态。

【建议（不执行）】测试清理分阶段：先固定核心回归层与 golden_e2e 不动；再对“阶段编号薄索引 + 已落地契约的 RED scaffold”做候选名单；再评估“硬编码清单/字符串扫描型”守卫是否改为更稳健形式；最后才动大文件。任何动作都应在“先有 Current System State”之后。

---

## 9. Documentation Reality（文档现状）

【事实】约 55 个 `.md`，可分为：

- **current/canonical（自称当前权威）**：`docs/PROJECT_STATUS.md`(自称第一入口)、`docs/CURRENT_DOCS.md`、`docs/README.zh.md`、`docs/CAPABILITY_BOUNDARIES.md`(GE-2 runtime fact SoT)、`docs/PROGRESS_LEDGER.md`、`docs/00-overview/*`、`docs/rfc/*`(三份 Canonical RFC)。
- **historical-repair（已关闭过程证据）**：`docs/06-audit/ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md`、`..._RETROSPECTIVE.zh.md`、`CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`(CLOSED RECORD)、`WINDOW_1/2/3_CLOSURE_AUDIT.zh.md`、`POST_REPAIR_AUDIT_DELTA.zh.md`、`docs/07-module-maturity/POST_L3_HARDENING_CLOSURE.zh.md`。
- **intermediate-process（决策/盘点/triage/delta）**：`docs/06-audit/*INVENTORY*/*DECISION*/*DRIFT*`、`docs/07-module-maturity/*DECISION_SPIKE*/*TRIAGE*/*FEASIBILITY*/*RECONCILIATION*`。
- **design-contract**：`docs/design/*`(7 份)。
- **RFC**：`docs/rfc/*`(3 份)。
- **plans**：`docs/plans/*`(4 个已关闭计划 + README)。
- **target/principle**：`docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md`(Draft v0)。
- **workflow/getting-started**：`docs/dev/*`、`docs/01-getting-started/*`、`docs/02-architecture/*`。

【事实】成熟度/数量类 claim 集中在 `docs/07-module-maturity/`：用 L0–L3 及一个更高的 default-on/real-provider 就绪等级评分；多份文档自述“14/15 模块 scoped L3，Scheduler 为 L2 / no consumer”，并明确写“这不是全模块 L3、不是最高等级、修复仍关闭、无新窗口”。`docs/07-module-maturity/ARCHITECTURE_GOAL_RECONCILIATION_AUDIT.zh.md` 本身已建议：**不要把这套 15 模块分母当作未来 scorecard**。

【推断】**易误导未来读者的点**：
1. 概览文档措辞偏乐观（`docs/00-overview/FIRST_AGENT_OVERVIEW.zh.md` “全局审计未发现 P0/P1/P2、代码主线健康”），无明确时间戳，易被读成“接近产品化”，与“developer prototype”定位张力。
2. `docs/00-overview/CAPABILITY_MATRIX.zh.md` 把 SubAgent 标“已完成”，与 V0 路由默认关、走 inline-local fallback 的代码事实存在落差。
3. `docs/rfc/MEMORY_CANONICAL_RFC.md` 描述完整 memory lifecycle（含 consolidation/emergence），而代码中这两段默认关闭——RFC 与默认激活态系统性不一致。
4. **没有单一权威“当前状态”文档**：`PROJECT_STATUS.md`(06-10) 早于修复窗口关闭(06-13)，且 `CURRENT_DOCS.md` 仍把已自标 “superseded” 的 `06-audit/CURRENT_AUDIT_STATUS.zh.md` 当作 current 入口 → stale 指针。
5. 成熟度元数据漂移：`agent/runtime_integration/action_scheduler_handler.py:108` 在 evidence 写 `production_capability: True`，与 scheduler dormant/未生产路由的事实冲突（reconciliation 文档亦已点名）。

【建议（不执行）】文档整理分阶段：先产出唯一权威 Current System State（以代码事实为准）；再据此修正/降级 current 入口指针；再把 historical-repair 与 intermediate-process 明确标注为“历史证据，不作为现状/未来指令”；最后才讨论是否物理归档。本轮不删除、不归档任何文档。

---

## 10. Major Risks（主要风险）

1. **“已注册/有 handler/有测试”被误读为“主链路已用”**【事实支撑】：scheduler、MCP、subagent V0、emergence、LLM 巩固均为 wired-but-default-off；尤其 scheduler 无生产注入者却在 evidence 写 `production_capability: True`（`action_scheduler_handler.py:108`）——治理元数据本身会误导。
2. **默认 Fake provider 的认知风险**【事实】：默认形态不调真实 LLM（`provider/factory.py:90`）。任何“它能完成任务”的演示若未显式接 real provider，不能等同真实智能体行为。
3. **early-return 特例路径绕过 loop/dispatcher/evidence**【事实】：`core.chat()` 的 CLI/委托/memory 特例在主 loop 前 return（`agent/core.py:877,895,928`），是可观测/治理盲区与维护陷阱。
4. **文档过量且自指**【事实/推断】：修复窗口 + 模块成熟度叙事庞大、互相引用、缺单一权威现状文档，方向容易被旧叙事牵引。
5. **测试价值分层不清**【推断】：大量边界/inventory/hygiene/SOT-guard 与 Red/Green scaffold 与核心回归混在一起；硬编码清单型守卫脆弱（重命名即 false failure）。
6. **历史 claim 被当成当前代码事实**【事实】：多份文档的 L3/数量/测试通过数是某时间点快照（如某 closure 记 4730 passed），随代码变化已可能不成立；本轮未运行测试，不复述这些数字为当前事实。
7. **dormant/prototype 能力被误激活的风险**【推断】：emergence、LLM 巩固、MCP、subagent 路由都只差一个 env flag；误开可能引入未充分验证的行为或外部调用。
8. **policy 注释与实现不一致**【事实】：`tool_runtime_mediator.py:1128-1130` 注释 “fail-open” 实为 fail-closed——当前安全，但注释会误导后续维护者改坏。
9. **未来被旧 15 模块分母绑架**【事实/推断】：reconciliation 文档已自我警示，但入口层未充分隔离该 scorecard。
10. **dead-code / legacy 未隔离**【事实】：`security.needs_confirmation`、`security.confirm_tool_call`、`confirm_handlers.py`、`memory_provider` 等已无/疑无生产 consumer，但仍在源码中，易被误用。

---

## 11. Recommended Next Steps（下一步建议，仅建议不执行）

按顺序：

1. **产出 Current System State 文档**：以本审计为输入，用代码事实写“当前到底是什么、默认开/关了什么、哪些是 seam”，作为唯一权威现状基线（含默认 Fake provider、scheduler not-routed、MCP/subagent/emergence 默认关等硬事实）。
2. **基于现状做文档规范化计划（Docs Canonicalization Plan）**：先修 current 入口的 stale 指针，再给 historical/intermediate 文档统一加“历史证据，不作现状/未来指令”标注。
3. **分批归档/隔离旧文档**：在现状文档稳定后，再讨论物理归档；本轮不动。
4. **测试分层 triage（Test Suite Triage Plan）**：固定核心回归 + golden_e2e；列出薄阶段索引 / 已落地的 RED scaffold / 脆弱扫描型守卫候选；逐个跑过再决定。
5. **再讨论 First Agent 未来要做到什么层级**：明确放弃用旧 15 模块分母当 scorecard，改以“默认生产路径能力 + 真实 provider 验证”为新标尺。

---

## 12. Final Audit Verdict（最终审计判决）

- 当前第一优先级是**搞清楚并钉死现状**，不是继续补模块。
- 不应现在定死未来 agent 形态。
- 不应现在按旧模块表继续补能力。
- 不应现在大规模删除文档或测试。
- 应当：**先产出高质量 Current System State → 再做文档规范化 → 再做测试分层 → 最后规划未来形态**。

本审计到此结束，不继续生成 Current System State，不整理文档，不清理测试，不规划未来形态。

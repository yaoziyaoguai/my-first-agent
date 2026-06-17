# S1 Current Code Architecture Audit

> 本文是 S1（重新开始后的 Stage 1 / Session 1）当前代码现状审计。
> S1 是文档/工作节奏编号，**不等于**代码里的 v0/v1/v2/v3 等版本概念，二者不得混用。
> 本文只描述「当前代码现状」，不定义任何阶段目标，不做未来规划。

---

## 0. Executive Verdict

用工程语言概括当前事实（均有代码证据，详见后文）：

- **当前代码不是一个普通 chatbot，也不是从零开始的脚手架。** 它已经具备一个**可运行的本地 Agent Runtime 底座**：统一入口 `core.chat()`、显式的 runtime loop（`agent/loop.py`）、provider 协议边界、统一的 RuntimeAction dispatcher、tool 中介层、checkpoint/resume、以及双层 evidence/log 体系。
- **存在清晰的 Agent Loop / Runtime Loop 底座。** 主链路是单一的：UI adapter → `core.chat()` → `run_main_loop()` → provider → 模型输出解析 → dispatcher/tool mediator → policy gate → tool/memory/checkpoint → evidence。
- **FakeProvider 与 RealProvider 共享同一条 runtime spine。** 二者只在 provider factory / config 层不同；进入 `core` 之后走同一套 loop、dispatcher、policy、tool、checkpoint、evidence。loop 层在源码注释中**显式拒绝读取 provider 类型**。这一点有强证据。
- **已真实接入主链路的能力**：tool registry + 中介执行、tool 确认/policy gate、memory recall/inline retain/turn-end 提案、checkpoint save/resume、evidence/log（`agent_log.jsonl` 全局 + `sessions/<id>/events.jsonl` 单会话）。
- **已实现但默认不在生产主链路的能力**：MCP（默认关闭，需环境变量开启）、subagent V0 生产路由（默认关闭，源码注明 wiring 未完成，默认走本地确定性 stub）、action scheduler（dormant，生产入口 `main.py` 不注入）、本地 trace（`on_trace_event` 默认 None，opt-in）。
- **不存在的能力**：未发现任何会真正执行查询的 SQL/数据库工具（仅有一个解析 `.sql` 文本结构的 outline 函数，且未注册）。
- **当前最大注意点**：(a) `config/config.yaml` 曾是被 Git 跟踪的本地 runtime config 路径；后续 G-15 核验证明 Git history / HEAD / index 中仅有占位符，真实 provider key 从未提交，且 G-15 已将该路径 untrack 并加入 `.gitignore`；(b) 节点很多但「已接入主链路 / 仅可配置 / 仅测试」边界容易被误读；(c) planning/compress 仍走 legacy `client.messages.create` facade，与主执行循环的 provider 协议调用是两种形态（虽指向同一 provider）；(d) evidence 能证明路径骨架，但不持久化原始模型请求/响应正文。

本文只描述现状，不定义阶段目标。

---

## 1. Scope and Non-goals

- 本文是基于**当前代码、测试、配置、样例、日志/evidence 机制**的现状审计。
- 不做未来规划，不定义任何阶段目标，不给验收承诺。
- 不改代码、不改测试、不清理文档、不移动文档。
- 不沿用旧文档中的 15-module 成熟度分母作为未来 scorecard。
- 不对成熟度等级做总体达标声明；本文不使用任何「全部模块达标」式结论。
- 历史文档（`docs/history/`）仅作背景参考，不作为本文结论来源。
- 凡当前代码无法确证之处，本文写明 unknown，不臆测。

---

## 2. Method

**发现手段：**
- 使用 Graphify 知识图谱做 source/runtime discovery（`graphify query "..."` 定向到入口、loop、provider、dispatcher、evidence 等节点）。Graphify 仅用于**定位事实**，不作为最终证据。
- 在 Graphify 定向后，用 `rg` / 直接读源码核验关键调用链。
- 对最关键的 same-spine 判断，作者**亲自阅读了** `agent/provider/factory.py`、`agent/provider/protocol.py`、`agent/provider/legacy_adapter.py`、`main.py`、`agent/core.py`、`agent/core_contexts.py`，并对「主链路是否按 provider 类型分叉」做了对抗性 grep 核验。
- 外围节点（tool/MCP/SQL/subagent/memory/checkpoint/policy/evidence、测试、config、scheduler）用并行只读 discovery agent 盘点，结论均带 file:line，并与作者亲读的 spine 事实交叉印证。

**事实分层口径（本文严格区分）：**
- **源码事实**：能在源码读到的调用关系/默认值。
- **测试事实**：测试覆盖了某行为，但**不等于**该行为在生产主链路被默认触发。
- **配置事实**：某开关存在及其默认值。
- **日志/evidence 事实**：运行产物能证明的路径。
- **推断**：由上述组合推出但未逐行验证者，明确标注。
- **unknown**：未能确证者。

**避免旧文档干扰**：Graphify 查询有时会命中 `docs/history/` 里的旧 roadmap 节点（例如一次 provider 调用查询返回的是历史 roadmap 标题）。本文对所有结论都回到 `agent/`、`main.py`、`config/`、`tests/` 的真实源码核验，不以历史叙事为准。

---

## 3. Repository Shape From Current Code

- **主要源码目录**：`agent/`（约 120+ 模块，含子包 `agent/provider/`、`agent/tools/`、`agent/runtime_integration/`、`agent/subagent_system/`、`agent/skill_system/`、`agent/confirmation/`、`agent/cli/`、`agent/input_backends/`）。
- **主要入口文件**：`main.py`（767 行，CLI / 主循环 / session 启动）。
- **核心运行时**：`agent/core.py`（2275 行，`chat()` 统一入口）、`agent/loop.py`（1061 行，`run_main_loop()`）、`agent/session.py`（832 行，session 生命周期 + resume）。
- **测试目录**：`tests/`（约 250 个 `.py`，含 `tests/runtime_integration/`、`tests/golden_e2e/`、`tests/unit/`、`tests/smoke/`、`tests/adversarial/`、`tests/fixtures/`）。
- **配置**：顶层 `config.py`（legacy 兼容 shim）、`config/`（本地 gitignored `config.yaml` + 多个 `*.example.yaml`）、`.env.example`；`.env` 若存在也被 gitignore，但 G-15 后当前口径是不恢复、不创建 `.env`。
- **运行产物 / evidence**：顶层 `agent_log.jsonl`（约 7.5MB）、`sessions/`（约 600 个会话目录，每个含 `events.jsonl`）、`memory/`（含 checkpoint）。
- **文档制度**：`docs/current/` 为当前工作区（目前仅 `README.md` 与本文）；`docs/history/` 为历史归档。本文不展开历史文档内容。

---

## 4. Current System Shape

从代码看，当前项目最接近 **「带治理与恢复能力的本地 tool-calling Agent Runtime kernel」**，而不是普通 chatbot，也不是成熟 workflow engine。证据：

- 不是普通 chatbot：存在显式 runtime loop（`agent/loop.py:run_main_loop`）、状态机（`agent/transitions.py`、`agent/state.py`）、工具调用中介（`agent/tool_runtime_mediator.py:186`）、checkpoint/resume（`agent/session.py:405`）。
- 是 tool-calling agent：模型输出经 `ProviderResponse`（含 `ToolUseBlock`，`agent/provider/protocol.py:49-73`）解析为工具调用，经 dispatcher + mediator 执行。
- 有治理/恢复/evidence：tool 确认 gate（`agent/tool_registry.py:424`、`agent/runtime_integration/tool_gate.py:32`）、统一 evidence recorder（`agent/evidence_recorder.py:728`）、checkpoint（`agent/checkpoint.py`）。
- 尚不是 workflow engine：action scheduler（`agent/action_scheduler.py`，有向图执行器）已实现但生产主链路不注入（详见第 7 节）。
- 混合形态特征：存在一个统一 `core.chat()` 入口，但其中也夹带了 **CLI meta-command 快捷路径**（`agent/core.py:852-869` 注释明确：这些 `if/return` 是 CLI-ONLY / DEMO-ONLY，提前 return 绕过 loop/dispatcher/evidence，「不是第二条 runtime，但明确不是产品主路径」）。

---

## 5. Current Runtime Mainline

下图为当前主链路。标注：【确】=源码确证；【推】=合理推断；【配】=可配置分支。

```
用户输入 (CLI / TUI / pipe)
  -> main.py: main() L637 -> main_loop() L335                         【确】
  -> _run_chat_for_backend() L195                                     【确】
       ├─ backend=textual -> _run_textual_runtime_turn()              【确】
       └─ 否则           -> _run_simple_cli_runtime_turn()           【确】
  -> 两者都调用 core.chat()  (agent/core.py:763)                       【确】单一入口
  -> chat(): 解析 session_id/identity，构建 _phase1_dispatcher 一次   【确】 core.py:840-844
       (CLI meta-command 快捷路径在此可提前 return，绕过 loop)        【确/配】 core.py:852-869
  -> _build_loop_context() 注入 provider + dispatcher (core.py:1181)  【确】
       provider = 入参 provider 或 build_model_provider_from_env()    【确】 core_contexts.py:53
  -> run_main_loop()  (agent/loop.py)                                 【确】
  -> 模型调用                                                          【确】
       ├─ 主执行循环: model_call.py call_model -> provider.create()/stream()  【确】 model_call.py:66,83,92
       └─ planning/compress: loop_ctx.client.messages.create()        【确】 core.py:1369
            (client = ProviderBackedClient facade -> 同一 provider.create)  【确】 legacy_adapter.py:29-63
  -> 模型输出 -> ProviderResponse (text / tool_use blocks)            【确】 protocol.py:49-73
  -> tool 决策 -> ToolRuntimeMediator.mediate() (tool_runtime_mediator.py:225)  【确】
  -> RuntimeActionDispatcher.route_from_runtime_loop()                【确】 dispatcher.py:309
       TOOL_GATE -> (policy/approval) -> TOOL_INVOKE -> TOOL_RESULT    【确】 tool_gate.py:32
  -> 能力节点: tool 执行 / memory recall+retain / checkpoint save     【确】
  -> turn-end hooks: memory 提案/consolidate, event-log flush         【确】 loop.py:285-435,919-937
  -> evidence/log: record_evidence -> agent_log.jsonl + events.jsonl  【确】 evidence_recorder.py:728
  -> 最终回复 (RuntimeEvent -> UI)                                     【确】
```

**unknown / 需后续确认**：主执行循环与 planning 路径在 fake 模式下是否解析为**同一个 provider 实例**（两者都经同一 factory，但一个来自模块级 `build_default_model_client()`（core.py:171），一个可能在 `build_loop_context` 内重新解析）。类型与 config 一致，实例同一性未逐行确证，标 unknown。

---

## 6. Provider Boundary: Fake / Real Same-Spine

**这是本文重点章节。结论：fake 与 real 共享同一条 runtime spine，差异只在 factory/config 层。证据充分。**

- **provider 协议边界**：`agent/provider/protocol.py:77` 定义 `ModelProvider` Protocol，只暴露 `create()` / `stream()` 与三个能力位（`provider_type`、`supports_tools`、`supports_streaming`）。返回统一 `ProviderResponse`（protocol.py:69-74）。这层刻意很薄。
- **统一工厂**：`agent/provider/factory.py:18 build_model_provider()` 用 `provider_type` 分派构造 `anthropic_native` / `anthropic_compatible` / `openai_native` / `openai_compatible` / `fake`（factory.py:19-30）。`build_model_provider_from_env()`（factory.py:36）按 `config/config.yaml` → legacy profile → legacy env → default fake 的优先级解析，**默认返回 FakeProvider**（factory.py:90）。
- **工厂自带 same-spine 声明**：factory.py:44-45 注释明确：「FakeProvider 和 RealProvider 共享同一条 core.chat/loop.py 路径，这不是 fake/real 双 runtime。」
- **FakeProvider 定位**：`agent/provider/fake_provider.py:306` 的 `FakeProvider` 是 deterministic 的 provider 协议实现（test / CI / 本地安全默认 / runtime contract adapter）。它实现的是与 real 相同的 `ModelProvider` 接口，不是另一套 agent。
- **RealProvider 路径存在且已被用户反复验证**：real adapter 在 `agent/provider/anthropic_http.py`、`anthropic_native.py`、`openai_http.py`、`openai_native.py`，由同一工厂构造。
- **loop 层 provider 中立（强证据）**：`agent/loop.py:249`「loop 层不接触 provider 对象、不读 provider_type、不做 white-list 判断」；`agent/loop.py:690` 同义重申。loop 内唯一与 provider 相关的读取是 `supports_streaming` 能力位（loop.py:606），属能力协商，非 fake/real 分叉。
- **dispatcher 对所有 provider 统一构建**：`agent/core.py:1158-1159`（RT-01 修复注释）：「所有 provider 类型统一自动构建 dispatcher，确保 fake/real 共享同一 evidence path，不因 provider type 产生证据路径分歧。」
- **legacy planning client 也指向同一 provider**：planning/compress 仍用 `loop_ctx.client.messages.create()`（core.py:1369），但 `client` 是 `ProviderBackedClient`（`agent/provider/legacy_adapter.py:58`），其 `messages.create()` 把调用**转发到同一 `provider.create()`**（legacy_adapter.py:29-54）。`core.py:171` `_model_provider, client = build_default_model_client()` 表明 provider 与 client 来自同一工厂调用。

**fake/real 进入 core 后是否共享 action parsing / dispatcher / policy / tool / checkpoint / evidence？** 是。模型输出统一解析为 `ProviderResponse`，之后的 mediator、dispatcher、tool gate、checkpoint、evidence 路径均不读 provider 类型。

**是否存在双路径 / fake-only / real-only / dogfood-only 风险？**
- 主链路无 fake/real 分叉（上述证据）。
- 但存在三处**与主执行循环并存的旁路**，需诚实记录（均非主链路 fake/real 分叉）：
  1. `agent/local_demo.py:74` 自带一个**独立的** `FakeProvider` 类（demo CLI `run_demo_cli`，local_demo.py:297 附近）。这是 demo-only 旁路，不是产品 loop 用的 `agent/provider/fake_provider.py`。
  2. CLI meta-command 快捷路径（core.py:852-869）提前 return 绕过 loop/dispatcher/evidence——源码注明「不是第二条 runtime」，但确实不经主链路。
  3. planning/compress 的 legacy client facade 形态与主执行循环的 `provider.create()` 形态不同（虽指向同一 provider）。
- 这些是「同 spine 但有 legacy 形态/demo 旁路」的事实，**不是** fake/real 两套 Agent。

**当前 evidence 是否足以证明 same-spine？** 源码层证据充分（协议 + 单工厂 + loop 中立 + RT-01 + legacy facade 转发）。运行层 evidence 记录 `provider_type`（session.py:250、evidence_recorder.py:657），可区分一次 run 用的是 fake 还是 real，但**不持久化原始模型请求/响应正文**，因此无法从产物逐字节复原模型交互（见第 8 节）。

---

## 7. Runtime Node / Capability Inventory

状态取值：active（默认接入主链路）/ configurable（可配置，注明开关+默认）/ implemented-not-wired（已实现但主链路默认不注入）/ test-only / prototype-dormant / not-exist / unknown。

| 节点 | 代码位置 | 状态 | 进主链路 | fake/real | evidence | 风险 |
|---|---|---|---|---|---|---|
| entry / CLI | `main.py:637/335/195` | active | 是 | 同入口 | session_start 等 | 夹带 CLI meta-command 旁路 |
| core / chat | `agent/core.py:763` | active | 是（唯一入口） | 同 | 全程 | 单文件 2275 行，认知负担高 |
| runtime loop | `agent/loop.py:run_main_loop` | active | 是 | provider 中立 | loop.start/iteration | — |
| provider | `agent/provider/factory.py:18,36` `protocol.py:77` | active | 是 | **同 spine** | provider_type 记录 | planning 仍走 legacy facade |
| model 输出处理 | `protocol.py:49-73` `model_call.py:66,83,92` | active | 是 | 同 | call_summary | 不存原始正文 |
| tool 系统 | `tool_registry.py:43,142,205,399` `tool_runtime_mediator.py:225` `tool_executor.py:204` | active | 是 | 同 | TOOL_GATE/INVOKE/RESULT | — |
| MCP | `main.py:574,587` `mcp_bridge.py:146` `mcp.py:161` `mcp_policy.py:127` | configurable（`MY_FIRST_AGENT_MCP_ENABLE`，默认关；dry-run 默认开） | 启用后 MCP 工具进 registry | 同 | MCP_BRIDGE_LIFECYCLE | 默认关易被误判未实现 |
| SQL / data tool | `tools/outline.py:85`（仅解析 `.sql` 文本，未注册） | not-exist（无执行型） | 否 | — | — | 文档勿臆造此能力 |
| sub-agent / 委派 | `subagent_routing_flag.py:29` `core.py:1975` `subagent_system/executor.py:12` `phase1_hook.py:169-187` | configurable（`SUBAGENT_V0_ROUTING_ENABLED`，默认关）；默认走本地确定性 stub（`execution_mode="local_fake"`） | 检测在 loop 内；真实执行是 stub | V0 注册但生产 wiring 源码注明未完成 | V0 evidence 测试存在 | 「检测在主链路」≠「真实委派执行」 |
| memory / context | store `core.py:179`（默认 InMemory）；fs store `memory_fs_store.py:59`（`MEMORY_STORE_ROOT`/`MEMORY_ROOT`，默认不激活）；recall `core.py:1065`；inline retain `core.py:961`；turn-end `loop.py:285-435` | active（recall+retain+turn-end）；fs store configurable；维护 CLI implemented-not-wired | 是 | 同 | MEMORY_RECALL/PROPOSE/CONSOLIDATE | 多个 memory_* 模块，主链路 vs 离线 CLI 边界需读者区分 |
| checkpoint / resume | save `core.py:1005,1322,1641,1707`；turn-end save `loop.py:732`（默认关）；resume `session.py:405`（`main.py:731` 无条件调用）；写盘 `checkpoint.py:403-463` | active（save 关键转移点 + resume）；turn-end save configurable（默认关） | 是 | 同 | checkpoint_saved | v1/v2 两种 schema 并存 |
| policy / approval | `tool_registry.py:424 needs_tool_confirmation`；`tool_gate.py:32 ToolGateHandler`；`mcp_policy.py`；禁用 bash/shell tool_gate.py | active（两 provider 模式相同） | 是 | 同 | confirmation 事件 | 无顶层统一 policy 开关，逻辑分散 |
| evidence / log / trace | `logger.py:150`→`agent_log.jsonl`；`event_log.py:153`→`sessions/<id>/events.jsonl`；`evidence_recorder.py:728/644/638` | active（log + events + record_evidence） | 是 | 同（记录 provider_type） | 见第 8 节 | local trace opt-in |
| local trace | `agent/local_trace.py`；`loop.py:31` 守卫 | implemented-not-wired（`on_trace_event` 默认 None，opt-in） | 否（默认） | — | 默认不写 | 勿误判为默认开启 |
| config / registry | `config/config.yaml` `simple_config.py:71` `config.py`(legacy shim) | active（本地 gitignored config.yaml 为 provider 真源；仓库保留 example 模板） | 是 | 决定 fake/real | session 记录 | G-15 已完成 untrack + gitignore；Git history/HEAD/index 仅有占位符，真实 key 从未提交 |
| scheduler / action plan | `agent/action_scheduler.py`（742 行）；seam `loop.py:728`(默认 None)/`loop.py:1007-1028`；`main.py` 零引用 | implemented-not-wired / dormant | 否（生产不注入） | — | — | `tests/test_scheduler_boundary_l2.py` 钉死 main.py 0 引用 |

补充事实：tool registry 默认注册的工具（`agent/tools/__init__.py`）包括 `read_file`/`write_file`/`edit_file`/`run_shell`/`fetch_url`/`mark_step_complete`/`request_user_input`/memory 系列/demo 系列等；模型可见工具上限 `max_total=30`、`max_mcp=5`（tool_registry.py:205）。

---

## 8. Evidence / Log / Trace Reality

- **两套 active 日志并存**：
  - 全局 `agent_log.jsonl`（`agent/logger.py:150 log_event`）：约 7.5MB、约 16,556 行，schema `{timestamp, session_id, event, event_category, data}`，跨所有 session 累积，超 50MB 自动轮转（`config.py:173`）。
  - 单会话 `sessions/<session_id>/events.jsonl`（`agent/event_log.py:153 EventLogWriter`，`main.py:715` 无条件创建）：写入前经 enrich → redact（脱敏 secret/API key/Bearer/JWT）→ 截断（5000 字符）。
- **统一 evidence recorder**：`agent/evidence_recorder.py:728 record_evidence` 构造标准信封（含 `provider_type`/`provider_model`/`subsystem`/`operation`/`phase`/`status`/`safe_summary` 等），同时写 `agent_log.jsonl` 与 `events.jsonl`。session 上下文经 `set_session_context()`（evidence_recorder.py:644，`main.py:704-713` 设置）。
- **能证明的路径骨架**：用了哪个 provider（fake/real）、session_start、user_input、checkpoint_saved、TOOL_GATE/INVOKE/RESULT、MEMORY_RECALL/PROPOSE/CONSOLIDATE、SKILL_SELECT、confirmation 决策、loop.start/iteration。
- **real provider path 是否可被 evidence 证明**：可证明「该 run 的 provider_type 为某真实类型且发生了模型调用与工具事件」，但不持久化原始 prompt 正文与完整模型响应。
- **fake provider path 是否可被 evidence 证明**：同样可证明（记录 provider_type=fake 及完整事件链）。
- **缺口 / unknown**：
  - 不持久化原始模型请求/响应正文（仅 safe_summary 与 call_summary 元数据）。
  - `model_call` 级别的 trace span 默认不发（local trace opt-in）。
  - CLI meta-command 旁路提前 return 时，turn-end flush 机制不一定覆盖（但其仍直接调用 record_evidence）——具体覆盖度标 unknown，需后续以一次真实 run 的产物核对。

---

## 9. Test Signal Reality

仅描述，不建议删除，不据测试断定主链路。

- **像核心 runtime / loop 回归**：`tests/test_main_loop.py`、`test_runtime_state_machine_invariants.py`、`test_phase3_*`/`test_phase2_*`/`test_phase4_session_lifecycle.py`、`test_resume_full_flow.py`、`tests/smoke/test_first_usable_task_e2e.py`。**真正驱动完整 `core.chat()` 全链路的**主要是 `tests/golden_e2e/*`（如 `test_golden_simple_conversation.py` 用真实 `FakeProvider()` 跑全链路）与 `tests/runtime_integration/test_phase1_real_core_loop.py`、`test_mcp_l3_real_core_loop.py`。
- **像 provider fake/real 边界测试**：`test_fake_provider_decision.py`、`test_provider_contract.py`、`test_provider_*_http.py`/`*_native.py`/`*_normalize.py`、`test_provider_agentloop_integration.py`、`test_provider_real_smoke.py`、`test_real_mcp_flight.py`、`test_chat_provider_injection.py`。
- **像能力节点测试**：tool（`test_tool_registry_contract.py`、`runtime_integration/test_tool_pipeline_l3_completion.py` 等）、mcp（`test_mcp_bridge.py`、`runtime_integration/test_mcp_audit_evidence.py` 等）、subagent（`test_subagent_*`、`runtime_integration/test_subagent_v0_*`）、memory（`test_memory_*`、`runtime_integration/test_memory_*_l3.py`）、checkpoint（`test_checkpoint_*`、`runtime_integration/test_checkpoint_save_resume_l3.py`）、policy（`test_policy_*`、`adversarial/test_minimal_policy_stub.py`）、evidence（`test_evidence_*`、`test_b7_event_log.py`）、scheduler（`test_scheduler_boundary_l2.py`、`runtime_integration/test_action_scheduler.py`、`test_scheduler_main_path.py`）。
- **像历史修复 / harness / 边界守卫**：`test_b7_*`（多实例/命名空间隔离）、`test_architecture_boundaries.py`（AST 级 import/call 边界守卫，含 scheduler dormancy 守卫）、`test_docs_source_of_truth.py`、`test_legacy_path_inventory.py`、`test_hardcore_*`、`test_v6_drift_addendum_boundary.py`。
- **不能当主链路证据的**：直接 `dispatcher.route()` 的 seam 级测试、harness/契约守卫——它们验证边界与不变量，不代表生产默认触发该路径。
- 运行方式：`pytest.ini` `testpaths = tests`，marker `slow`/`dogfood`，无并行配置。
- **后续需要的是分层**（本文不给删除建议）：把「全链路 e2e」「provider 边界」「节点契约」「历史 harness」显式分层，便于挑出主链路验收子集。

---

## 10. Architecture Risks

1. **config 卫生历史风险已由 G-15 收口**：`config/config.yaml` 曾是被 Git 跟踪的本地 runtime config 路径，且工作树可被填入真实 key；后续 G-15 核验证明 Git history / HEAD / index 中仅有占位符，真实 provider key 从未提交，也无轮换依据。G-15 已将 `config/config.yaml` 从 Git 跟踪移除并加入 `.gitignore`；后续 real provider smoke 仍必须遵守 key-safe 边界，不读取、打印、移动、复制或提交 secret。
2. **「有代码 ≠ 进主链路」误读风险**：MCP、subagent V0、scheduler、local trace 均已实现但默认不在生产主链路；容易被旧叙事误判为「已激活」或「未实现」。
3. **「有测试 ≠ 生产路径」误读风险**：大量 seam/harness 测试存在，不代表该路径默认被触发。
4. **默认关闭 ≠ 未实现**：MCP（`MY_FIRST_AGENT_MCP_ENABLE` 默认关）、subagent V0（`SUBAGENT_V0_ROUTING_ENABLED` 默认关）属「已实现可配置」。
5. **fake/real 形态不统一的残留**：planning/compress 仍走 legacy `client.messages.create` facade（虽转发到同一 provider）；存在 `local_demo.py` 独立 FakeProvider 旁路。需避免被读成两套 Agent，也需记录其为统一化未完成的尾巴。
6. **evidence 不能证明模型交互正文**：只能证明路径骨架与 provider 类型，无法逐字节复原；real path 的强证明依赖 safe_summary + 事件链，而非原始响应。
7. **CLI meta-command 旁路**：`core.chat()` 内夹带提前 return 的 CLI-ONLY/DEMO-ONLY 路径，绕过 loop/dispatcher/evidence；虽非第二 runtime，但扩大它会侵蚀「单一主链路」清晰度。
8. **核心文件体量**：`agent/core.py` 2275 行、`agent/loop.py` 1061 行，认知与回归成本高。
9. **scheduler / async 过早进入主线的风险**：scheduler 有完整注入 seam（`loop.py:1007-1028`），一旦注入即改变执行模型；当前 dormant，本文不建议接入或移除，仅记录其 seam 已存在。
10. **节点多但缺统一验收口径**：MCP/SQL（不存在）/subagent/memory 等能力各有测试，但缺少「一次主链路 run 必过的统一验收清单」，导致现状容易被高估或低估。

---

## 11. Facts Needed Before Phase-1 Planning

在确定下一阶段目标**之前**，必须先确认以下事实（本文只列事实，不在此定义任何阶段目标）：

1. **主链路验收命令**：哪一条/哪一组命令（哪个 `tests/golden_e2e/*` 或 smoke）被认定为「主链路必过」的最小验收集？
2. **real provider smoke 怎么跑**：用哪个 gitignored local config / opt-in env、跑哪个测试或脚本、产物落在哪个 `sessions/<id>/events.jsonl` 可证明真实模型调用？（G-15 已解决 config 跟踪卫生；真实执行仍需单独授权并遵守 key-safe 边界。）
3. **fake regression 怎么跑**：哪个命令是确定性 fake 全链路回归基线？
4. **same-spine 如何证明**：用哪次 fake run + 哪次 real run 的 `events.jsonl` 对照，证明二者经过同一组事件（TOOL_GATE/INVOKE/RESULT、checkpoint、memory），只 provider_type 不同？
5. **provider 实例同一性**：核实 planning client 与主执行循环是否同一 provider 实例（第 5 节 unknown）。
6. **哪些节点已确属主链路、哪些仅 configurable**：以本文第 7 节表为基线复核（尤其 MCP、subagent V0、scheduler 的默认状态）。
7. **evidence 缺口**：是否需要、以及在何处补「模型交互可复现」证据（当前不存正文）；CLI meta-command 旁路的 evidence 覆盖度需以真实产物核对。
8. **测试分层**：主链路 e2e / provider 边界 / 节点契约 / 历史 harness 的显式分层边界。

---

## 12. Final Audit Verdict

- **当前项目不是从零开始**：已有可运行的本地 Agent Runtime 底座（统一入口、显式 loop、provider 协议、dispatcher/mediator、policy gate、checkpoint/resume、双层 evidence）。
- **fake/real 同 spine 成立**：差异只在 provider factory/config 层，进入 core 后共享同一 loop/dispatcher/policy/tool/checkpoint/evidence，源码证据充分。
- **当前需要的不是继续乱补模块**：节点已经较多，真正缺的是「以当前代码事实为基线，明确一组主链路验收标准与节点边界」。
- **下一步**应基于本文确认的事实（第 11 节）来决定取舍，而非沿用旧 roadmap 叙事或旧成熟度分母。

（本文到此为止：只描述现状，不定义阶段目标，不实现，不清理测试，不清理文档。）

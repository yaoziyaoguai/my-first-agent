# Full Subsystem Capability Audit Red-Team Addendum

日期：2026-05-28
范围：只读红队补审；未改生产代码，未读取 `config/config.yaml`，未调用真实 API，未读取真实 session/log/private data，未 commit/push/tag。
上一版报告：`docs/audits/2026-05-28-full-subsystem-capability-completion-audit.md`

## 0. Red-Team Verdict

上一版审计明显偏乐观。它把以下证据等级混在一起计为 `COMPLETE`：

- docs/design/roadmap 存在；
- registry/descriptor/schema 存在；
- guard/invariant test 存在；
- fake/local fixture 通过；
- direct dispatcher / direct subsystem call 通过；
- turn-end probe 产生 `real_core_loop_runtime_e2e` evidence；
- no-crash dogfood / smoke 通过；
- demo-only 或 CLI shortcut 可用。

按本轮严格标准，`COMPLETE` 必须至少有真实 `core.chat` / main runtime path 证据，并证明能力不是仅 dispatch、仅 probe、仅 direct-call、仅 fake、仅 registry、仅 docs。没有真实主路径业务闭环的项降级。

结论：

- 原始 COMPLETE：90 / 117
- 校正后 COMPLETE：27 / 117
- 校正后真实完成率：23.1%
- 被降级 COMPLETE：63 项
- 上一版 77%：不可信，只能反映“代码/测试/文档存在度”，不能反映 First Agent 核心子系统真实端到端能力完成度。

## 1. Evidence Standard Used

本补审使用以下证据等级，从高到低：

| Evidence level | 含义 | 是否可支撑 COMPLETE |
|---|---|---|
| PRODUCTION_MAIN_PATH_E2E | 默认 `core.chat` / main loop 进入，能力真实执行业务动作，结果进入模型上下文或用户响应，并有 summary/trace/evidence | 是 |
| REAL_API_MAIN_PATH_E2E | 真实 provider/API 通过主路径完成关键能力；secret 安全 | 是，但需 opt-in 与边界说明 |
| FAKE_LOCAL_MAIN_PATH_E2E | fake provider/local fixture 与 real 共享主路径，能证明运行时闭环，不证明真实外部能力 | 可支撑 fake/local 阶段 COMPLETE |
| RUNTIME_DISPATCH_PATH | `route_from_runtime_loop()` 有证据，但动作可能是 probe/noop/rejected | 不能单独支撑业务 COMPLETE |
| HARNESS_DIRECT_DISPATCH | test/harness 直接构造 `RuntimeActionRequest` 调 dispatcher | 不能 |
| SUBSYSTEM_DIRECT_CALL | 直接调用 registry/store/client/selector/executor | 不能 |
| FAKE_ONLY | fake client / synthetic fixture / deterministic local executor | 不能证明真实能力 |
| DOC_GUARD_ONLY | 文档、契约、guard/invariant test | 不能 |
| STUB | 接口存在但无真实行为 | 不能 |

特别规则：`real_core_loop_runtime_e2e` 只证明 runtime-loop provenance 和 target proof，不自动证明“业务能力完成”。如果 handler 返回 failed/noop/no suitable/no action，或者 turn-end hook 只是 probe，本补审不计为 `COMPLETE`。

## 2. COMPLETE 判定校正

### 2.1 Summary

| Subsystem | Previous COMPLETE | Corrected COMPLETE | Downgraded |
|---|---:|---:|---:|
| Tool | 10 | 6 | 4 |
| MCP | 7 | 0 | 7 |
| Skill | 5 | 0 | 5 |
| Memory | 12 | 5 | 7 |
| SubAgent | 5 | 0 | 5 |
| Storage / Session / Checkpoint / Run State | 8 | 4 | 4 |
| Provider / Config | 11 | 5 | 6 |
| Runtime Summary / Trace / Evidence | 11 | 3 | 8 |
| Confirmation / Safety / Permission | 7 | 4 | 3 |
| Dogfood / Evaluation Harness | 14 | 0 | 14 |
| **Total** | **90** | **27** | **63** |

### 2.2 Downgraded COMPLETE List

| Area | Downgraded claims | Corrected status | Why |
|---|---|---|---|
| Tool runtime-action pipeline | `TOOL_GATE` / `TOOL_INVOKE` / `TOOL_RESULT` as completed unified pipeline | PARTIAL | Default turn-end path uses `_safe_noop`; actual model tool calls still go through `response_handlers.handle_tool_use_response` and `tool_executor`, not the RuntimeAction pipeline. `TOOL_RESULT` prompt section from handler is not the normal model-context feedback path. |
| Tool selection | tool selection complete | PARTIAL | Real provider can emit tool_use and fake provider can deterministic-match tools, but runtime itself has no scheduler-owned tool selection policy beyond model free output and injected tool definitions. |
| Tool error recovery | complete | PARTIAL | Per-turn limits, repeated input guards, tool_result placeholders exist, but no generalized retry/backoff/scheduler recovery. |
| MCP config/discovery/registration | complete | DIRECT_CALL_ONLY | Config/parser/policy/stdio/registration exist, but bridge is default disabled and not invoked from `core.chat`. Real server flight is opt-in; default path does not discover/import MCP tools. |
| MCP real E2E | complete | FAKE_ONLY / DIRECT_CALL_ONLY | Default tests use fake client or local fixture; opt-in npx flight is skipped by default and direct-call, not main runtime. |
| MCP result feedback | complete | PARTIAL | Registered MCP tools can become ToolRegistry tools, but full MCP result feedback through main model loop depends on manual registration and model tool call; no default MCP main path. |
| Skill registry/selection/body load | complete | DIRECT_CALL_ONLY | Registry/loader/selector work in direct tests. In default `core.chat`, `_skill_registry` is set to `None`; `LoopDependencies.skill_registry` is `None`, so turn-end `SKILL_SELECT` gets no metadata and usually proves only no-skill probe. |
| Skill context injection | complete | STUB | `prompt_builder.build_skills_section()` returns empty string; loaded skill body is not injected into the normal model prompt. |
| Skill tool binding | complete | DIRECT_CALL_ONLY | Binding logic exists and is tested with mock registries, but runtime does not enforce selected Skill allowed_tools against model-visible tools. |
| Skill execution/effects | complete | STUB | `invoke_skill()` is one-shot body output only; no loop, no tool execution, no memory write, no result effect tracking in main runtime. |
| Explicit Memory retain | complete | PARTIAL | User explicit retain exists with confirmation and dispatcher payload, but default recall path can still bypass dispatcher; forget/list are split shortcuts; policy is prefix/rule based. |
| Model-suggested Memory | complete | STUB / FAKE_ONLY | Suggestion engine is deterministic and not enabled in default `create_memory_runtime()`. Not based on model recommendation + policy/privacy + confirmation in main path. |
| Implicit Memory | complete | FAKE_ONLY / DIRECT_CALL_ONLY | L2 inline extraction is default fake/direct hook; real LLM is opt-in; not fully governed by main scheduler. |
| Memory three types | complete | PARTIAL | `memory_type` fields exist and some propagation tests exist, but semantic/contextual/procedural handling is not a complete typed policy/runtime. |
| Memory consolidation | complete | PARTIAL | Consolidation handler is readonly and can produce candidates, but no complete adoption/update/decay policy; L3 tests prove dispatch, not full lifecycle. |
| Memory E2E | complete | PARTIAL | Direct snapshot/store tests and injected-dispatcher L3 tests exist; default production path still has direct snapshot fallback and incomplete three-entry design. |
| SubAgent registry/descriptor | complete | DEMO | Demo descriptors exist; `show subagents` CLI dispatcher wrapper appears bug-prone; descriptors are demo-only. |
| SubAgent delegation | complete | FAKE_ONLY | L0 executor explicitly does not call provider, execute tools, spawn processes, or write memory. It returns deterministic summaries. |
| SubAgent tool/memory/skill scope | complete | STUB / DIRECT_CALL_ONLY | Boundary objects exist but are not exercised by a real child execution loop. |
| SubAgent real E2E | complete | NOT_STARTED | No child provider loop, no inherited provider, no parent-mediated tool execution, no result aggregation beyond deterministic L0. |
| Checkpoint resume | complete | PARTIAL | Save/load schema exists; true restoration of active runtime/model/tool loop is not complete. Resume is JSON state reload + UI replay, not full execution state restoration. |
| Session/run state storage | complete | PARTIAL | `TaskState` and checkpoint exist; no durable run store/trace store/evidence store that unifies all subsystem events. |
| Provider config.yaml | complete | PARTIAL | Loader exists; this audit did not read real `config/config.yaml`. Real config readiness cannot be asserted from code alone. |
| Provider real dogfood | complete | SMOKE_ONLY | Real API sweep is interactive smoke/no-crash and does not verify subsystem business completion. |
| Runtime/Evidence architecture | complete | PARTIAL | Dispatcher evidence/classifier is strong, but reports/tests still over-read `real_core_loop_runtime_e2e` as capability completion. Summary is in-memory/event based, not durable full evidence. |
| Runtime summary | complete | PARTIAL | `_emit_run_summary` summarizes action_log, but direct model tool path and CLI shortcuts are not uniformly captured. |
| Trace | complete | PARTIAL | Optional trace sink exists; no required durable trace/evidence store for all main-path actions. |
| CLI read-only meta commands | complete | STUB / BUG | `CliShowMemoriesHandler` and `CliShowSubagentsHandler` construct `RuntimeActionResult` with unsupported `disposition=` argument, so dispatcher path can fail. Mutating/delegating CLI shortcuts still bypass dispatcher. |
| Dogfood harness | complete | DEMO / SMOKE_ONLY | Good harness infrastructure, but expected-events/no-crash/synthetic pass does not prove subsystem capability. The user explicitly disallows counting dogfood as capability completion. |

## 3. Current Real Unified Main Runtime Path

Current actual path, not idealized:

```text
用户输入
  -> agent.core.chat()
     -> CLI shortcuts / memory explicit prefix / subagent shortcuts can intercept before main loop
     -> refresh_runtime_system_prompt()
        -> with injected dispatcher: MEMORY_RECALL via route_from_runtime_loop
        -> default path: direct _memory_runtime.snapshot_for_prompt() fallback
     -> planning phase
        -> planner.generate_plan() direct provider call
        -> user confirms plan if multi-step
     -> agent.loop.run_main_loop()
        -> call_model()
           -> provider gets system prompt + projected messages + ToolRegistry model-visible tools
        -> model_output_dispatch / response_handlers
           -> tool_use path calls tool_executor directly
           -> end_turn/max_tokens/no_progress handlers update task state
        -> turn-end hook
           -> memory proposal/propose/consolidate probes
           -> tool pipeline probe via tool_gate_tool_name (default _safe_noop)
           -> skill.select probe (default no metadata)
           -> subagent.delegate_l0 probe (usually no real delegation)
           -> streaming/checkpoint summary/trace probes
        -> run summary event
  -> final response / UI events
```

Segment status:

| Segment | Current status | Notes |
|---|---|---|
| `user input -> core.chat` | implemented | Main public entry exists. |
| CLI shortcut handling | partial | Some read-only commands intended through dispatcher; mutating/delegating commands bypass. Read-only handler construction appears invalid. |
| planning | partial | Planner asks model for JSON plan; no runtime scheduler selecting subsystem sequence. |
| scheduling / orchestration | STUB | Hardcoded loop + prompt instructions + turn-end probes. No scheduler-owned next-action engine. |
| memory recall | partial | Injected-dispatcher tests work; default path can direct snapshot before dispatcher. |
| explicit memory write | partial | Confirmation exists; accepted proposal queues dispatcher payload. Full write happens at turn-end via `MEMORY_PROPOSE`. |
| implicit/model-suggested memory | fake/demo/direct | Not full main-path typed memory system. |
| skill selection | STUB | Default main path passes no `skill_registry`; no skill body prompt injection. |
| tool selection | partial | Model sees ToolRegistry tools and may emit tool_use. RuntimeAction tool pipeline is mostly separate probe path. |
| MCP decision | missing | No default MCP discovery/registration in main loop. |
| subagent decision | demo/fake | Direct CLI/NL shortcut plus turn-end L0 probe; no scheduler-owned delegation. |
| confirmation | partial | Tool and memory confirmation exist; not a unified permission kernel for all actions. |
| execution | partial | Tool execution works; MCP requires pre-registration; Skill/SubAgent execution not real. |
| result feedback | partial | Tool result enters conversation through `tool_executor`; RuntimeAction `TOOL_RESULT` prompt_section is not the same path. |
| summary / trace / evidence | partial | Dispatcher action_log and optional trace exist; not complete durable evidence across all paths. |

Answers:

- There is no true unified scheduler. The main runtime is a model loop with prompt-driven planning, direct tool handlers, and turn-end lifecycle probes.
- Subsystems do not all enter through one path. Tool real execution, Memory explicit prefix, SubAgent CLI/NL shortcut, MCP registration, Skill selection, and RuntimeAction probes occupy different planes.
- Second capability planes include `runtime_integration/*` dispatcher tests, MCP bridge direct registration, Skill direct selector/invocation, SubAgent deterministic L0, and dogfood harnesses.
- Direct-call tests frequently masquerade as E2E when they construct `RuntimeActionRequest` or call subsystem APIs without user input reaching `core.chat`.
- Fake and real share some provider loop mechanics, but MCP/Skill/SubAgent/Memory extraction do not yet share one uniform real/fake capability path.

## 4. Tool System Audit

| Capability | Status | Evidence / gap |
|---|---|---|
| registry | COMPLETE | `ToolRegistry` is used by `get_model_visible_tools()` in `_call_model()`. |
| schema / descriptor | COMPLETE | Tool definitions and JSON schema projection exist. |
| risk metadata | COMPLETE | `capability`, `risk_level`, `confirmation`, `output_policy` exist. |
| permission / confirmation | PARTIAL | `needs_tool_confirmation()` and `awaiting_tool_confirmation` path exist; not unified with all non-tool actions. |
| model tool selection | PARTIAL | Real/fake providers see tools; runtime does not own selection. |
| invocation | COMPLETE | `execute_single_tool()` / `execute_pending_tool()` execute registered tools and append results. |
| result into model context | COMPLETE for direct tool path | `append_tool_result()` + `_project_to_api()` handle protocol pairing. |
| RuntimeAction tool pipeline | PARTIAL | Exists but default is `_safe_noop` probe; not same as real model-emitted tool path. |
| MCP tool parity | PARTIAL | Works after explicit registration; no default discovery/import. |
| error recovery | PARTIAL | Limits, placeholders, repeated-input guards; no general retry/scheduler policy. |
| timeout/retry | PARTIAL | Some provider/MCP timeout boundaries; no unified action-level timeout/retry. |
| trace/summary/evidence | PARTIAL | Tool execution traces exist, dispatcher evidence exists, but not uniformly one path. |

True Tool grade: **PARTIAL**. Tool is the strongest subsystem, but not a fully unified Tool/MCP/Skill/SubAgent execution plane.

## 5. MCP System Audit

| Capability | Status | Evidence / gap |
|---|---|---|
| config model / parser | PARTIAL | Safe parser exists; config workflow explicitly avoids real home config. |
| discovery | DIRECT_CALL_ONLY | `run_mcp_bridge(mode="registration")` can list tools, but default bridge is disabled and not called from `core.chat`. |
| stdio transport | PARTIAL | Local stdio client works with fixtures; HTTP/SSE rejected. |
| tool import / mapping | PARTIAL | `register_mcp_tools()` maps tools into ToolRegistry with confirmation always. |
| schema normalization | PARTIAL | Descriptor parameters and sanitized description exist. |
| safety boundary | PARTIAL | allowlist, sanitizer, destructive-name blocks exist. |
| execution through Tool pipeline | DIRECT_CALL_ONLY | After explicit registration, MCP tool is normal ToolRegistry entry; no default main path registration. |
| result feedback | PARTIAL | Legacy string mapping exists; direct ToolRuntime result formatter separate from main model path. |
| real MCP E2E | DIRECT_CALL_ONLY / OPT_IN | Local fixture by default; npx real flight opt-in and skipped by default. |
| no independent runtime | PARTIAL | MCP is adapter-like, but bridge is separate direct workflow. |

True MCP grade: **DIRECT_CALL_ONLY** leaning **PARTIAL infrastructure**. It is not complete usable main-path capability.

## 6. Skill System Audit

| Capability | Status | Evidence / gap |
|---|---|---|
| registry / descriptor | DIRECT_CALL_ONLY | Formal registry works over `skills/` and fixtures. |
| selection | DIRECT_CALL_ONLY | Deterministic selector tested; RuntimeAction handler validates model metadata but does not select. |
| activation | STUB | Default `core.chat()` passes `skill_registry=None`, so no available metadata. |
| context injection | STUB | `build_skills_section()` returns empty. Skill body is not in normal prompt. |
| tool binding | DIRECT_CALL_ONLY | Binding object works in tests; not enforced in runtime model-visible tools. |
| memory scope | DOC_ONLY / DIRECT_CALL_ONLY | Descriptor fields exist; no integrated memory scoping behavior. |
| execution constraints | PARTIAL as direct adapter | `invoke_skill()` is one-shot body output, no loop/tool/memory. |
| affects tool availability | NOT_STARTED | Skill selection does not constrain `get_model_visible_tools()`. |
| result/effect tracking | STUB | Audit record exists for direct invocation; no main runtime effect tracking. |
| fake/local Skill E2E | DEMO | Fixtures and dogfood tests; no real main-path skill execution. |
| real API Skill E2E | NOT_STARTED | No real provider skill activation path. |
| coordination with Tool/MCP/SubAgent/Memory | STUB | Descriptor fields only; no runtime composition. |

True Skill grade: **DIRECT_CALL_ONLY / STUB**. It is a metadata/body-loading subsystem, not an executable runtime capability yet.

## 7. Memory System Audit

Memory must be judged by the original design: three entry types and three memory types.

### 7.1 Entry Types

| Entry | Status | Evidence / gap |
|---|---|---|
| 用户主动记忆 | PARTIAL | Prefix/rule intent detection, confirmation, queue to `MEMORY_PROPOSE`, store write via handler. Not full classifier; forget path still direct shortcut. |
| 模型主动推荐记忆 | STUB / FAKE_ONLY | Suggestion engine exists but default runtime does not inject it; deterministic heuristics only, not model-suggested opportunity pipeline. |
| 隐式记忆 | FAKE_ONLY / DIRECT_CALL_ONLY | L2 inline extraction default fake; real LLM opt-in; direct hook in `core.py`, not scheduler-governed full policy path. |

### 7.2 Memory Types

| Type | Status | Evidence / gap |
|---|---|---|
| semantic | PARTIAL | Store fields/defaults and consolidation candidates exist, but policy is not full semantic memory lifecycle. |
| contextual / episodic | PARTIAL | Episodic records used in consolidation tests; not fully integrated contextual recall/update/decay. |
| procedural | STUB / PARTIAL | Metadata and some inline confirmation concepts exist; no complete procedural memory runtime. |

### 7.3 Memory Capability Details

| Capability | Status | Notes |
|---|---|---|
| intent classification | STUB | `DeterministicMemoryPolicy` is prefix/rule based. |
| explicit memory request | PARTIAL | Works for retain/update/forget intent detection; complete behavior split. |
| candidate extraction | PARTIAL | Explicit candidate extraction exists; L2 extraction fake/default. |
| policy/privacy gate | PARTIAL | Sensitive regex/policy exists; not comprehensive privacy classifier. |
| user confirmation | PARTIAL | Explicit memory confirmation exists. |
| retain | PARTIAL | Approved retain queues dispatcher payload; write at turn-end. |
| reject | PARTIAL | Reject does not store. |
| forget | DIRECT_CALL_ONLY | CLI shortcut mutates runtime directly; not unified dispatcher policy. |
| list | PARTIAL / BUG-RISK | `show memories` intended dispatcher path, but CLI handler returns invalid `RuntimeActionResult` kwargs. |
| recall into prompt | PARTIAL | Default `refresh_runtime_system_prompt()` can direct snapshot unless dispatcher injected. |
| cross-session recall | PARTIAL | Filesystem store exists; default runtime uses in-memory unless configured. |
| consolidation | PARTIAL | Readonly detection; no full adoption/decay/update lifecycle. |
| trace/summary/evidence | PARTIAL | RuntimeAction evidence exists for some hooks; not complete durable memory evidence. |
| fake/local E2E | PARTIAL | Several fake/local tests; not the full original design. |
| real API E2E | NOT_STARTED / OPT_IN_ONLY | Real LLM extraction opt-in; not default main path. |

True Memory grade: **PARTIAL**. It is significantly overestimated by the previous audit. It is not a full three-entry / three-type Memory system; it is mostly explicit-rule retain plus partial store/recall/consolidation infrastructure.

## 8. SubAgent System Audit

| Capability | Status | Evidence / gap |
|---|---|---|
| registry / descriptor | DEMO | Demo descriptors exist; registry loads local descriptor files. |
| delegation decision | STUB / DEMO | NL keyword/CLI shortcuts and turn-end probe; no scheduler/model-owned delegation decision. |
| task packaging | PARTIAL | Context package object exists. |
| child context | PARTIAL | Package includes fields, but not a real child LLM context. |
| child provider / inherited provider | NOT_STARTED | Executor explicitly does not call provider. |
| child tool access | STUB | Boundary checks exist; child does not execute tools. |
| child memory scope | STUB | Boundary object exists; no real child memory workflow. |
| child skill scope | STUB | Boundary object exists; no real child skill workflow. |
| execution loop | FAKE_ONLY | `execute_local()` deterministic summary only. |
| result aggregation | PARTIAL | Parent adjudication exists over deterministic result. |
| failure recovery | STUB | Deterministic status mapping; no real retry/revision loop beyond simple adjudication. |
| nested delegation policy | PARTIAL | L0 forbids nested delegation. |
| safety boundary | PARTIAL | No shell/external process, parent adjudication required. |
| trace / summary | PARTIAL | Synthetic trace/audit record exists. |
| fake/local E2E | FAKE_ONLY | L0 synthetic dogfood. |
| real API E2E | NOT_STARTED | No child LLM. |

True SubAgent grade: **FAKE_ONLY / DEMO**. It is not a real SubAgent capability yet.

## 9. Storage / Session / Checkpoint / Run State Audit

| Capability | Status | Evidence / gap |
|---|---|---|
| session creation | PARTIAL | `SESSION_ID`, init/finalize paths exist. |
| run state | PARTIAL | `TaskState`, `ConversationState`, `MemoryState`; status remains mixed single-field lifecycle. |
| checkpoint save | COMPLETE | JSON save with schema/version/truncation exists. |
| checkpoint load | PARTIAL | Schema migration/filtering exists; true runtime continuation is not complete. |
| checkpoint resume | PARTIAL | Resume prompt and state reload; no full model/tool execution restoration. |
| memory storage | PARTIAL | In-memory and filesystem stores exist; default behavior not full cross-session memory. |
| trace storage | STUB / PARTIAL | Optional trace event sink; no durable trace store. |
| evidence storage | PARTIAL | JSONL observer logs and dispatcher action_log; not unified evidence store. |
| log hygiene | PARTIAL | Redaction/rotation exist; audit did not read logs by boundary. |
| cleanup | PARTIAL | checkpoint clear and session snapshot; not full corruption cleanup. |
| corruption recovery | PARTIAL | checkpoint load handles unknown versions/some failures. |
| project/workspace isolation | PARTIAL | Path safety exists for mutation tools; storage isolation not full product model. |

Storage will block future capability if not redesigned before real SubAgent/MCP/Memory growth. Multi-instance is not required now, but a durable run/evidence/session boundary is.

## 10. Planning / Scheduling / Task Orchestration Audit

| Capability | Status | Evidence / gap |
|---|---|---|
| multi-step task planning | PARTIAL | Planner generates JSON plan and asks confirmation. |
| step scheduler | PARTIAL | `current_step_index` + prompt instructions + `mark_step_complete`; no explicit scheduler deciding actions. |
| subsystem call ordering | NOT_STARTED | Runtime does not choose Tool/MCP/Skill/Memory/SubAgent order as actions; prompt/model and hardcoded hooks do. |
| tool-result continuation | PARTIAL | Model loop continues after tool_result; no scheduler-owned action graph. |
| failure retry | PARTIAL | Tool repeat guards; no generalized retry/recovery policy. |
| parallel/sequential tasks | NOT_STARTED | Sequential plan only; no parallel runtime task scheduling. |
| runtime state next action | PARTIAL | Status handlers route confirmations and loop continuation; no unified next-action engine. |
| priority/policy | STUB | Risk/confirmation policy exists per subsystem, not orchestration policy. |
| model free output only | PARTIAL | Execution relies heavily on model tool_use/end_turn plus prompt rules. |
| trace proving scheduling | NOT_STARTED | Trace can prove dispatch/probes, not scheduler decisions. |

True Scheduling grade: **PARTIAL for planning; NOT_STARTED for real Agent scheduler**. First Agent currently has a basic loop and prompt-mediated step execution, not a full planning/scheduling/task orchestration system.

## 11. Full Gap Matrix

| subsystem | standard capability | previous status | corrected status | main path integrated? | E2E available? | evidence level | gap | priority | can auto-run? | needs architecture decision? | suggested phase |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Main Runtime | Unified capability decision spine | COMPLETE-ish implied | PARTIAL | partial | fake smoke | mixed | No scheduler-owned subsystem decision frame | P0 | no | yes | Phase 1 |
| Planning/Scheduling | Multi-step planning + next-action scheduler | under-audited | PARTIAL | partial | tests | main/fake | Planner exists; scheduler missing | P0 | no | yes | Phase 1 |
| Tool | Model tool call execution | COMPLETE | PARTIAL | yes | fake + some real smoke | production/fake | Strong path but not unified with RuntimeAction tool pipeline | P0 | partly | no | Phase 1-2 |
| Tool | RuntimeAction tool pipeline | COMPLETE | PARTIAL | probe only | direct/injected | dispatch path | Default `_safe_noop`; result section not normal model feedback | P1 | yes tests | yes for unification | Phase 1 |
| MCP | Config / policy / stdio / registration | COMPLETE | DIRECT_CALL_ONLY | no | local fixture | direct | Bridge default disabled; not called by `core.chat` | P1 | no for real | yes | Phase 2 |
| MCP | Real external MCP through Tool pipeline | COMPLETE | NOT_STARTED | no | opt-in direct | opt-in | No default real MCP main path | P2 | no | yes | Phase 3 |
| Skill | Registry/loader/descriptor | COMPLETE | DIRECT_CALL_ONLY | no | direct | subsystem | Main `LoopDependencies.skill_registry=None` | P0 | yes tests | no | Phase 1 |
| Skill | Selection + context injection | COMPLETE | STUB | no | direct only | direct | No prompt section/body injection in default runtime | P0 | no | yes | Phase 2 |
| Skill | Tool binding affects tool surface | COMPLETE | DIRECT_CALL_ONLY | no | direct | unit | Binding not enforced in model-visible tools | P1 | no | yes | Phase 2 |
| Memory | Explicit user memory retain/confirm/write | COMPLETE | PARTIAL | partial | fake/local | mixed | Prefix policy; dispatch split; default recall bypass risk | P0 | partly | yes for policy scope | Phase 1-2 |
| Memory | Model-suggested memory | COMPLETE | STUB | no | fake/direct | fake | Suggestion engine disabled/default deterministic | P1 | no | yes | Phase 3 |
| Memory | Implicit memory | COMPLETE | FAKE_ONLY | direct hook | fake | fake/direct | L2 fake default; not scheduler/policy complete | P1 | no | yes | Phase 3 |
| Memory | Semantic/contextual/procedural types | COMPLETE | PARTIAL | partial | tests | direct/fake | Fields exist; type-specific lifecycle incomplete | P1 | no | yes | Phase 3 |
| Memory | Consolidation/decay/update | COMPLETE | PARTIAL | turn-end readonly | fake/local | dispatch | No adoption/decay/update policy | P2 | partly | yes | Phase 3 |
| SubAgent | L0 local delegation | COMPLETE | FAKE_ONLY | demo/probe | synthetic | fake | Deterministic executor only | P1 | yes for fake | no | Phase 2 |
| SubAgent | Real child loop/provider/tools | COMPLETE | NOT_STARTED | no | no | none | No child provider/tool/memory execution | P2 | no | yes | Phase 3 |
| Storage | Checkpoint save/load | COMPLETE | PARTIAL | yes | tests | production/local | True resume incomplete | P1 | yes tests | no | Phase 2 |
| Storage | Durable run/evidence/trace store | COMPLETE | PARTIAL | partial | logs/optional | partial | No unified durable evidence model | P1 | no | yes | Phase 2 |
| Provider/Config | Provider abstraction | COMPLETE | PARTIAL | yes | tests/smoke | main/fake/real smoke | Config real status not asserted without reading config | P1 | partly | yes for config source | Phase 2 |
| Confirmation/Safety | Tool confirmation | COMPLETE | PARTIAL | yes | tests | main | Good for tools; not unified permission kernel | P0 | yes tests | no | Phase 1 |
| Confirmation/Safety | Memory confirmation | COMPLETE | PARTIAL | partial | tests | main/direct | Explicit memory only; broader memory policies incomplete | P0 | yes tests | yes | Phase 2 |
| Confirmation/Safety | MCP/Skill/SubAgent permission | COMPLETE | PARTIAL | no | direct/fake | partial | Boundary objects without main-path enforcement | P1 | no | yes | Phase 2-3 |
| Runtime Evidence | Summary / trace / evidence | COMPLETE | PARTIAL | partial | tests | dispatch/log | Evidence proves route, not uniformly business completion | P0 | yes guards | yes | Phase 1 |
| Dogfood/Eval | Interactive harness | COMPLETE | DEMO | subprocess CLI | smoke | smoke | No-crash/expected-events not capability completion | P2 | yes fake | no | Phase 4 |
| Dogfood/Eval | Real API sweep | COMPLETE | DEMO | subprocess CLI | smoke | real smoke | Does not validate subsystem business outcomes | P2 | no | yes for live tests | Phase 4 |

## 12. Full Completion Roadmap

### Phase 1: Main Path Integration Foundation

目标：所有核心子系统先接入一个 runtime-owned decision/evidence spine，不再用 fake/direct-call/probe 冒充 E2E。

#### Loop 1.1 — Unified Runtime Decision Spine

- target subsystem: Main Runtime / Scheduling / Evidence
- capabilities covered: action decision frame, subsystem availability snapshot, action provenance, result feedback contract
- scope: define and implement one runtime-owned decision point that can choose/sequence Memory recall, Skill selection, Tool/MCP execution, SubAgent delegation, and checkpoint/summary hooks; fix default dispatcher wiring gaps such as memory recall using injected argument instead of built dispatcher; ensure SkillRegistry is passed when default dispatcher is built
- out of scope: real MCP external server, real child SubAgent LLM, full memory implicit extraction
- expected E2E evidence: `user input -> core.chat -> scheduler decision -> selected capability action -> result returned -> model context/final response -> summary/evidence`
- tests/gates: red tests for default `core.chat()` path without injected dispatcher; no direct dispatcher requests accepted as main-path proof; `git diff --check`, ruff, targeted runtime tests, full pytest
- safe-to-auto-run: no
- requires architecture decision: yes
- success criteria: at least one cross-subsystem fake/local E2E proves real scheduler decision, not turn-end noop probe
- stop condition: any capability still requires test-only injected dispatcher to appear complete
- dependency: none; this is first

#### Loop 1.2 — Evidence Classification Repair

- target subsystem: Runtime Evidence / Dogfood
- capabilities covered: classify probe vs business, direct-call vs main path, fake vs real
- scope: make reports/tests unable to mark noop/rejected/probe as capability COMPLETE; require business disposition and main-path proof
- out of scope: implementing missing capabilities
- expected E2E evidence: failing tests for overclaim cases become green
- tests/gates: runtime integration evidence tests, dogfood evaluator tests
- safe-to-auto-run: yes
- requires architecture decision: no
- success criteria: `real_core_loop_runtime_e2e` no longer equals “business capability complete” by itself
- stop condition: reports still count no-crash or empty expected_events as PASS
- dependency: Loop 1.1 decision vocabulary preferred

#### Loop 1.3 — Tool Path Unification

- target subsystem: Tool
- capabilities covered: model tool_use path and RuntimeAction tool pipeline converge on one result/evidence contract
- scope: ensure real model-emitted tools can be represented in RuntimeAction evidence without duplicating execution; make `TOOL_RESULT` feedback align with conversation/model context path
- out of scope: MCP real servers
- expected E2E evidence: fake provider emits tool_use, tool executes, tool_result enters model context, summary records same action
- tests/gates: fake provider tool pipeline, tool pairing, runtime action evidence
- safe-to-auto-run: partly
- requires architecture decision: yes
- success criteria: no second Tool capability plane
- stop condition: `_safe_noop` remains the only default RuntimeAction tool success
- dependency: Loop 1.1

### Phase 2: Core E2E Completion

#### Loop 2.1 — Explicit Memory Main-Path Completion

- target subsystem: Memory
- capabilities covered: explicit retain/reject/forget/list/recall, prompt injection, summary/evidence
- scope: move forget/list/read-only paths to valid dispatcher/main path, fix default recall dispatcher/direct mismatch, retain confirmation-to-store path with durable evidence
- out of scope: implicit/model-suggested memory, procedural memory
- expected E2E evidence: `remember -> confirmation -> retain -> next turn recall in prompt -> summary/evidence`
- tests/gates: memory interaction, runtime integration memory, user path dogfood
- safe-to-auto-run: partly
- requires architecture decision: yes for forget semantics and store backend default
- success criteria: explicit Memory can honestly be called fake/local main-path E2E
- stop condition: direct `_memory_runtime` mutations remain user-facing path
- dependency: Loop 1.1

#### Loop 2.2 — Skill Activation MVP

- target subsystem: Skill
- capabilities covered: registry visible metadata, model/scheduler selection, body/context injection, allowed tool surface narrowing, effect tracking
- scope: make `demo-note-maker` selectable in default `core.chat` path and let selected skill affect prompt/tool availability through runtime-owned policy
- out of scope: marketplace/install/update, remote skills, arbitrary script execution
- expected E2E evidence: `user task -> skill selected -> skill context visible to model -> tool request constrained by skill -> result/evidence`
- tests/gates: skill registry/selector/tool binding + new main-path tests
- safe-to-auto-run: no
- requires architecture decision: yes
- success criteria: Skill is no longer just direct body load
- stop condition: `build_skills_section()` still empty for selected skill
- dependency: Loop 1.1, Loop 1.3

#### Loop 2.3 — Storage / Checkpoint True Resume

- target subsystem: Storage / Run State
- capabilities covered: active run checkpoint, pending tool/memory/user input resume, evidence pointer, corruption handling
- scope: define what “resume” restores and verify checkpoint roundtrip resumes the same runtime state without prompt splicing illusions
- out of scope: multi-instance
- expected E2E evidence: interrupt during pending tool/memory/step, restart/load, continue without lost state
- tests/gates: checkpoint resume semantics, long-running, state invariants
- safe-to-auto-run: partly
- requires architecture decision: yes
- success criteria: checkpoint resume is a real capability, not only JSON load
- stop condition: resume can only replay UI text but not continue task state correctly
- dependency: Loop 1.1

#### Loop 2.4 — MCP Main-Path Readiness

- target subsystem: MCP + Tool
- capabilities covered: safe local stdio discovery, allowlisted registration, model-visible tool, confirmation, execution, result feedback
- scope: local fixture MCP through default main path behind explicit safe config fixture; no real home config
- out of scope: external HTTP/SSE, npx real server, production config
- expected E2E evidence: `core.chat -> MCP tool available -> model selects -> confirmation -> call fixture -> result in context`
- tests/gates: mcp stdio, mcp policy, tool pipeline, no secrets
- safe-to-auto-run: no for registration; yes for guards
- requires architecture decision: yes
- success criteria: MCP is not only direct registration test
- stop condition: `run_mcp_bridge()` still only manual direct call
- dependency: Loop 1.3

### Phase 3: Advanced Capability Completion

#### Loop 3.1 — Memory Three Entries / Three Types

- target subsystem: Memory
- capabilities covered: explicit, model-suggested, implicit; semantic/contextual/procedural; candidate extraction, privacy gate, confirmation, retain/reject/update/decay
- scope: introduce real intent classifier/extraction policy path with fake/real parity and clear confirmation levels
- out of scope: vector DB unless proven necessary
- expected E2E evidence: each entry/type combination has fake/local main-path case and selected real API dogfood case
- tests/gates: memory policy, extraction, consolidation, dogfood, privacy
- safe-to-auto-run: no
- requires architecture decision: yes
- success criteria: Memory no longer means only prefix retain/recall
- stop condition: fake extractor with zero proposals is accepted as E2E
- dependency: Loop 2.1

#### Loop 3.2 — Real SubAgent L1/L2

- target subsystem: SubAgent
- capabilities covered: child provider loop, parent-mediated tool requests, memory/skill scopes, result aggregation, failure recovery
- scope: one bounded read-only child loop with inherited provider/fake parity; parent remains authority
- out of scope: parallel multi-agent, nested delegation, shell/external process
- expected E2E evidence: `scheduler delegates -> child loop runs -> child asks parent for tool -> parent executes -> child result -> parent adjudicates -> summary`
- tests/gates: subagent boundaries, tool/memory/skill scopes, no network by default
- safe-to-auto-run: no
- requires architecture decision: yes
- success criteria: SubAgent stops being deterministic L0 summary
- stop condition: executor still says no provider/no tools
- dependency: Loop 1.1, Loop 1.3, Loop 2.2

#### Loop 3.3 — Real MCP External Flight

- target subsystem: MCP
- capabilities covered: external stdio server, sandbox, allowlist, safe read-only tools, real provider tool selection
- scope: opt-in real MCP flight through main runtime with no secrets
- out of scope: default external connections, destructive MCP tools
- expected E2E evidence: real MCP read-only call via main path
- tests/gates: opt-in integration, secret scan, timeout, cleanup
- safe-to-auto-run: no
- requires architecture decision: yes
- success criteria: real MCP usable without bypassing runtime
- stop condition: test directly calls Anthropic SDK or `register_mcp_tools()` only
- dependency: Loop 2.4

#### Loop 3.4 — Advanced Scheduler

- target subsystem: Planning / Scheduling / Orchestration
- capabilities covered: action graph, sequential/parallel policy, retry, priority, subsystem sequencing, failure recovery
- scope: runtime-owned action scheduler that can plan and execute a multi-action sequence with tool result feedback
- out of scope: background daemons and multi-instance
- expected E2E evidence: multi-step plan chooses Skill/Memory/Tool/SubAgent/MCP order, recovers from one failure, continues
- tests/gates: long-running, complex scenarios, trace proof
- safe-to-auto-run: no
- requires architecture decision: yes
- success criteria: Agent is not just while-loop + prompt instructions
- stop condition: next action remains only model free output
- dependency: Phase 1 and core subsystem MVPs

### Phase 4: Product Hardening

#### Loop 4.1 — Dogfood/Evaluation Harness Honesty

- target subsystem: Evaluation
- capabilities covered: fake/local, real API, real MCP, capability assertions, no-crash distinction
- scope: dogfood cases must assert concrete business outcomes, not only events/fragments
- out of scope: broad product UX
- expected E2E evidence: harness report separates SMOKE_PASS from CAPABILITY_PASS
- tests/gates: dogfood harness tests, global dogfood report schema
- safe-to-auto-run: yes for fake harness
- requires architecture decision: no
- success criteria: no future 77% overclaim from smoke evidence
- stop condition: expected_events empty still passes capability
- dependency: Loop 1.2

#### Loop 4.2 — UX / Error Recovery / Storage Hygiene

- target subsystem: Product hardening
- capabilities covered: user-facing errors, permission prompts, recovery, cleanup, trace report
- scope: harden after capabilities are real
- out of scope: TUI, multi-instance, init command unless later required
- expected E2E evidence: error and recovery cases pass in CLI and report
- tests/gates: full pytest, dogfood, log hygiene
- safe-to-auto-run: partly
- requires architecture decision: case-by-case
- success criteria: robust user experience over complete subsystems
- stop condition: hardening hides missing core capability
- dependency: Phase 2-3

## 13. Prioritization

### First loop to execute

**Loop 1.1 — Unified Runtime Decision Spine**.

Why first: the root gap is not config.yaml or SubAgent L1. The project lacks a runtime-owned decision/scheduling spine that makes Skill/Memory/Tool/MCP/SubAgent enter the same main path and produces honest evidence. Starting with config or SubAgent would deepen the second capability plane.

### Next three loops

1. **Loop 1.2 — Evidence Classification Repair**
   Stop overclaiming probe/direct/fake/no-crash as complete.

2. **Loop 1.3 — Tool Path Unification**
   Tool is closest to real; unifying model tool path and RuntimeAction evidence gives the rest of the system a stable execution contract.

3. **Loop 2.1 — Explicit Memory Main-Path Completion**
   Make the most visible Memory path honest before expanding to implicit/model-suggested memory.

### Architecture decisions required first

- Runtime scheduler/action frame: what object owns next action and subsystem order?
- Skill semantics: prompt-only guidance vs executable workflow, and how selected Skill constrains tool surface.
- Memory policy: classifier/extractor/privacy/confirmation levels for explicit/model-suggested/implicit memory.
- MCP activation: when/how MCP discovery happens in main runtime, and what config source is allowed.
- SubAgent level model: L0/L1/L2 execution, inherited provider, parent-mediated tools, memory/skill scopes.
- Durable evidence/run state: what is persisted, how summary/trace/evidence correlate with checkpoint.

### Safe-to-auto-run candidates

- Evidence/dogfood honesty guards that relabel probe/direct/fake/no-crash.
- Static/runtime tests proving default `core.chat()` does not rely on injected dispatcher for Memory/Skill evidence.
- CLI read-only dispatcher handler bug tests.
- Tool pairing/result projection regression tests.
- Checkpoint schema/log hygiene regression tests.

These are useful but should not displace Loop 1.1 as the first capability loop.

### Not now, but eventually required

- Real external MCP flight through main path.
- SubAgent real child provider/tool loop.
- Memory implicit/model-suggested typed lifecycle.
- Advanced scheduler with retry/parallel policies.
- Product UX hardening and richer dogfood.
- TUI, multi-instance, and init command only if later proven to be dependencies. They are not core blockers now.

## 14. Final Red-Team Risk Review

| Risk | Severity | Current assessment |
|---|---|---|
| Overclaiming L3 dispatch as capability completion | P0 | Active and repeated. |
| Missing scheduler/main-path decision spine | P0 | Root architectural gap. |
| Memory overestimated | P0 | Explicit retain exists, original three-entry/three-type design incomplete. |
| Skill not actually active in runtime | P0 | Default `skill_registry=None`, empty skill prompt. |
| MCP not default main path | P1 | Infrastructure exists but separate. |
| SubAgent fake/demo counted as capability | P1 | L0 deterministic executor only. |
| Checkpoint true resume overclaim | P1 | Save/load not equivalent to full restoration. |
| Dogfood evidence inflation | P1 | Smoke/expected-events counted as capability. |

Final verdict: First Agent is a promising developer prototype with several strong local subsystems, especially Tool execution and RuntimeAction evidence primitives. It is not 77% complete as a unified Agent. The correct next move is to build the unified main runtime decision spine and evidence standard, then complete Tool/Memory/Skill/MCP/SubAgent through that path.

## 2026-05-29 Independent Re-Audit After Evidence Closure

### Scope

This independent re-audit reviewed the current repository after the
REAL-EVIDENCE closure work. It used the same strict standard as this red-team
addendum: documentation claims were not accepted without cross-checking code,
tests, local dogfood results, validation scripts, RuntimeAction evidence, and
main runtime path integration.

The review was read-only first. No code changes were made. No real external API
or MCP service was called during the audit; existing local result files and
validation scripts were inspected instead.

### Explicit Exclusions: B7/B8

B7 Multi-instance readiness and B8 TUI architecture are explicitly excluded
from this score. They are later productization and architecture decisions, not
current-stage runtime evidence closure requirements. Their incomplete state is
not counted as a current-stage failure in this re-audit.

### Repository State

| Item | Value |
|---|---|
| Path | `/Users/jinkun.wang/work_space/my-first-agent` |
| Branch | `main` |
| HEAD | `e3cf8cae37143cb2c85dfb855722a4870dcee86c` |
| Ahead/behind | `0/0` |
| Untracked files observed | `demo.md`; `docs/audits/2026-05-28-full-subsystem-capability-completion-audit-redteam-addendum.md`; `docs/audits/2026-05-28-full-subsystem-capability-completion-audit.md`; `docs/dogfood/GLOBAL_REAL_API_DOGFOOD_REPORT.md`; `task_design.md` |

The unrelated untracked files were not modified or staged.

### Score Before / After

| Score | Value | Notes |
|---|---:|---|
| Original red-team score | 1.4/5 inferred | The original addendum did not publish a single 0-5 score; this is inferred from the corrected 27/117 complete count and the repeated fake/direct/no-crash overclaim findings. |
| Current independent re-audit score | 3.2/5 | The project is materially improved, but not fully validated under the original strict main-path evidence standard. |

Current summary: the runtime now has much stronger dispatcher, Tool, Memory,
MCP fixture, SubAgent L1, scheduler, and dogfood-honesty infrastructure.
However, several closure claims still overstate the evidence level. The current
stage should be described as materially improved and partially validated, not
as "8/8 robustly validated".

### Subsystem Score Table

| Subsystem / loop | Original issue | Current evidence | Original score | Current score | Status | Remaining risk |
|---|---|---|---:|---:|---|---|
| Loop 1.1 Unified Runtime Decision Spine | Runtime decisions were mostly prompt/docs/probe. | `RuntimeDecisionFrame` and dispatcher exist and are integrated, but the branch registry still marks current branch points `PARTIAL`; no READY branch point is present. | 1 | 3 | CODE_PATH_COMPLETE | Source-of-truth mismatch between docs and `runtime_decision_frame.py`. |
| Loop 1.2 Evidence Classification Repair | Probe/no-crash evidence was counted as capability completion. | Evidence taxonomy and guard tests exist. | 1 | 4 | VALIDATED | Result JSON files still do not uniformly carry evidence classification metadata. |
| Loop 1.3 Tool Path Unification | Model tool execution and runtime evidence were split. | Model `tool_use` path now goes through `ToolRuntimeMediator` with TOOL_GATE/TOOL_INVOKE/TOOL_RESULT. | 2 | 4 | VALIDATED | Turn-end safe-noop probe remains; MCP external validation still uses direct execution. |
| Loop 2.1 Explicit Memory Main-Path Completion | Memory retain/recall/forget was partial/direct. | Real provider memory dogfood has positive retain/recall/forget/store assertions. | 2 | 4 | VALIDATED | Some business paths still use direct dispatcher `route()` provenance rather than `route_from_runtime_loop()`. |
| Loop 2.2 Skill Activation / allowed_tools | Skill was mostly prompt/stub/direct. | Skill body loading, active-skill prompt, deterministic selection, and allowed_tools contracts exist. | 1 | 3 | PARTIAL | Real dogfood does not prove same-turn disallowed-tool blocking; selection is deterministic fallback, not model-owned tool selection. |
| Loop 2.3 Storage / Checkpoint True Resume | Save/resume was partial and not equivalent to true restoration. | Handlers and contract paths exist. | 2 | 3 | QUESTIONABLE | Validation script falls back to direct save; real-provider checkpoint section has concerns. |
| Loop 2.4 MCP Main-Path Readiness | MCP bridge was disabled/direct. | Stdio fixture discovery, registration, visibility, allowlist, and lifecycle evidence are validated locally. | 1 | 3 | PARTIAL | Not yet `core.chat -> model selects MCP tool -> confirmation -> invocation -> result context`. |
| Loop 3.2 Real SubAgent L1/L2 | SubAgent evidence was fake/demo L0. | L1 handler and child provider loop exist; dogfood has delegate/result/adjudication evidence. | 1 | 3 | PARTIAL | Child tool mediation is not exercised in the core delegation path; L2 remains out of current scope. |
| Loop 3.3 Real MCP External Flight | External MCP proof was direct/probe only. | Real local stdio MCP fixture can be invoked through registered tool execution. | 1 | 3 | QUESTIONABLE | The external flight evidence is direct `execute_tool()`, not full runtime-mediated model tool path. |
| Loop 3.4 Advanced Scheduler | No runtime-owned scheduler main path. | Scheduler classes, handlers, tests, and manual real-provider harness exist. | 1 | 2 | PARTIAL | `core.chat()` does not inject `ActionScheduler`; no real model-generated plan is scheduled by default. |
| Loop 4.1 Dogfood / Evaluation Harness Honesty | Smoke/no-crash was overclaimed. | Honesty guard code and tests exist. | 0 | 4 | VALIDATED | Existing result JSONs still need normalized evidence fields. |
| Loop 4.2 UX / Error Recovery / Storage Hygiene | Hardening was incidental. | Provider error recovery, checkpoint resume notice, trace enrichment, and storage hygiene exist. | 2 | 4 | CODE_PATH_COMPLETE | This is hardening, not independent proof of capability completion. |

### REAL-EVIDENCE Closure Verification

| ID | Capability | Expected evidence | Closure status in docs | Script | Result file | Positive assertions | Closure credibility | Notes |
|---|---|---|---|---|---|---|---|---|
| REAL-EVIDENCE-001 | Memory retain/recall/forget | Real provider plus shared store and recall/forget assertions. | CLOSED | exists | exists | yes | credible | Not just no-crash. Caveat: confirm/forget evidence uses direct dispatcher routing in places. |
| REAL-EVIDENCE-002 | Skill selection | Real provider should activate the intended skill through runtime evidence. | CLOSED | covered by skill/subagent dogfood | exists | partial | questionable | Evidence supports deterministic keyword fallback and post-turn activation, not model-owned skill tool selection. |
| REAL-EVIDENCE-003 | Skill allowed_tools | Disallowed tool should be blocked in real runtime path. | CLOSED | covered by skill/subagent dogfood | exists | partial | questionable | Contract tests prove gate behavior when active skill is supplied; real dogfood does not prove same-turn disallowed blocking. |
| REAL-EVIDENCE-004 | Checkpoint save/resume | Handler-created checkpoint and true resume continuity. | CLOSED | exists | exists | mixed | questionable | Script falls back to direct `save_checkpoint()` and the real-provider section has 2 concerns. |
| REAL-EVIDENCE-005 | MCP bridge readiness | Real local MCP discovery/register/visibility/error handling. | CLOSED | exists | exists | yes | credible | Credible for bridge readiness, but not proof of model-selected MCP invocation. |
| REAL-EVIDENCE-006 | SubAgent L1 | Parent-mediated child loop with result and adjudication. | CLOSED | covered by skill/subagent dogfood | exists | partial | questionable | L1 child loop/result are useful; child tool mediation remains unexercised in the core delegation path. |
| REAL-EVIDENCE-007 | MCP external flight | Real MCP tool invoked through main runtime path. | CLOSED | exists | exists | partial | questionable | Real fixture/process exists; invocation is direct `execute_tool()`, not full runtime path. |
| REAL-EVIDENCE-008 | Advanced scheduler | Multi-node scheduler in main runtime path. | CLOSED | exists | exists | partial | questionable | Manual scheduler harness only; no default `core.chat()` scheduler injection. |

Strict closure summary: 2/8 credible, 6/8 questionable. The current repository
does not support the stronger claim that all eight REAL-EVIDENCE items are
fully credible under this addendum's original standard.

### Remaining Risks

| Severity | Finding |
|---|---|
| P1 | Current status docs overclaim `8/8 CLOSED/validated`; strict evidence supports 2 credible and 6 questionable closures. |
| P1 | Scheduler validation is not main runtime path validation. |
| P1 | MCP external flight validation is direct registered-tool execution, not model-selected runtime-mediated MCP E2E. |
| P1 | Skill allowed_tools real dogfood does not prove same-turn disallowed-tool blocking. |
| P1 | Checkpoint validation script contains a direct-save fallback and still reports real-provider concerns. |
| P2 | `RuntimeDecisionFrame` registry remains stale/all `PARTIAL` relative to status documentation. |
| P2 | Memory confirmation/forget behavior is useful but does not always carry runtime-loop provenance. |
| P2 | SubAgent L1 parent-mediated child tool request path exists but is not exercised in the core delegation path. |
| P3 | Dogfood result files should include normalized evidence class and provenance fields. |

### Recommendation

Do not overwrite this original addendum's historical judgment. Keep it as the
baseline red-team finding, and use this section as the follow-up independent
re-audit.

The recommended current wording is:

- The project is materially improved from the original red-team state.
- The current runtime milestone is partially validated, not fully validated.
- REAL-EVIDENCE closure should be reported as 2/8 credible and 6/8
  questionable under the strict standard until the questionable items are
  proven through their intended main runtime paths.
- B7/B8 should remain excluded from this phase and handled as later
  architecture/productization decisions.
- Before entering B7/B8, either accept the current partial boundary explicitly
  or run a small evidence-hardening pass for Skill allowed_tools, checkpoint
  true resume, MCP runtime-mediated invocation, SubAgent child tool mediation,
  and scheduler main-path injection.

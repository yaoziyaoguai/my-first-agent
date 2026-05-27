# Global Red-Team Product / Architecture / Code / Capability Audit

- Date: 2026-05-25
- Project: `my-first-agent`
- Scope: read-only audit plus this requested report write-up
- Suggested path: `docs/audit/global-red-team-product-architecture-audit-2026-05-25.md`
- Boundary honored: no `.env` read, no real API/LLM call, no dogfood execution, no network access, no private session/run/memory episode read.

## Preflight / Repo Gate

Required commands were executed before inference.

| command | result |
| --- | --- |
| `pwd` | `/Users/jinkun.wang/work_space/my-first-agent` |
| `git status -sb` | `## main...origin/main` |
| `git log --oneline -80` | reviewed; latest commit is `112d04c docs(dogfood): Big Loop 5 final report — auto-select Manual Human Dogfood as next step` |
| `git rev-list --left-right --count origin/main...HEAD` | `0 0` |
| `git tag --points-at HEAD` | empty |
| `git diff --stat` | empty |
| `git ls-files --others --exclude-standard` | empty |

Gate verdict: repository is at the expected path, branch is `main`, `main` is synchronized with `origin/main`, no tag points at `HEAD`, and the worktree was clean before this report file was added.

Representative latest history reviewed from the 80-commit log:

```text
112d04c docs(dogfood): Big Loop 5 final report — auto-select Manual Human Dogfood as next step
c52ee8c test(dogfood): verify real provider tool_use through Tool Pipeline
1f9caa7 docs(dogfood): real-provider tool-use E2E report — planner confirmation path verified
6202eee test(dogfood): add real provider tool-use E2E script
96e421d docs(dogfood): real provider conversation UX + trace validation report
65b0433 test(dogfood): add real provider conversation UX dogfood script
d571a34 docs(dogfood): Big Loop 3 real provider dogfood report
c304841 test(dogfood): add real provider dogfood E2E baseline
72bbfa1 test(real-e2e): load real provider from project .env for gated dogfood tests
```

## Audit Inputs

Primary documents reviewed:

- `docs/dev/ENGINEERING_WORKFLOW.md`
- `docs/dev/AUTO_RUN_WORKFLOW.md`
- `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md`
- `.claude/commands/auto-run.md`
- `docs/audit/global-agent-capability-architecture-audit-2026-05-25.md`
- `docs/plans/first-agent-subsystem-integration-roadmap.md`
- `docs/plans/user-usable-agent-runtime-mvp-plan.md`
- `docs/plans/user-usable-agent-runtime-issue-sweep.md`
- `docs/design/GLOBAL_ARCHITECTURE_DEBT_REMEDIATION_PLAN.md`
- `docs/design/MEMORY_RECALL_DUAL_PATH_AD.md`
- `docs/design/SUBAGENT_L0_TO_L1_REAL_DELEGATION_AD.md`
- `docs/architecture/provider-tool-call-compatibility-ad.md`
- `docs/audit/big-loop-independent-audit-2026-05-25.md`
- `docs/ROADMAP.md`
- `README.md`
- `docs/dogfood/*`

Primary code reviewed:

- `agent/core.py`
- `agent/loop.py`
- `agent/cli_commands.py`
- `agent/model_call.py`
- `config.py`
- `agent/provider/*`
- `agent/tool_registry.py`
- `agent/tool_executor.py`
- `agent/tools/*`
- `agent/memory*`
- `agent/runtime_integration/*`
- `agent/checkpoint*`
- `agent/subagent_system/*`
- `agent/skill*`
- `agent/streaming*`
- `agent/tracing.py`
- `agent/run_summary.py`
- `agent/local_demo.py`
- `main.py`
- `scripts/dogfood*`
- relevant `tests/` coverage for provider, tool, memory, subagent, streaming, trace, runtime integration, command routing, and dogfood.

## A. Executive Verdict

First Agent is currently a serious local-first agent runtime prototype that has crossed from pure architecture demo into developer-usable and real-provider-dogfood-tested territory, but it is not broadly user-usable. Its biggest achievement is not “many features”; it is the evidence discipline around a shared runtime contract, fake/real provider separation, runtime action provenance, and dogfood reports. Its biggest risk is that AutoRun has accumulated too many capability seams, evidence hooks, direct command paths, demo paths, and documentation layers, so the product can look more complete in reports than it feels to a real user. It is manual dogfood ready and narrowly real-provider dogfood ready, but not ready for another broad capability AutoRun loop. It should do human dogfood now, then a slimming/UX cleanup loop. No P0 was found. Two P1-class concerns exist: the default real-provider runtime does not appear to automatically get the same Phase1 `RuntimeActionDispatcher` evidence path as fake/dogfood-injected runs, and `core.chat` command shortcuts are drifting toward a second capability execution plane. FakeProvider, Memory Consolidation, Hook implementation, MCP confirmation, legacy demo paths, and doc/report proliferation should be frozen or consolidated before adding more surface area.

## B. Capability Map

| capability | user-visible status | runtime status | fake/local status | real provider status | dogfood status | maturity | evidence | overclaim risk | next action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Basic chat | usable through CLI/runtime | central `chat()` and loop path exists | works | baseline works when env configured | real baseline reported | real-provider-tested | `agent/core.py`, `agent/loop.py`, `docs/dogfood/real-provider-dogfood-report.md` | medium: UX still developer-shaped | human dogfood |
| real provider loading from `.env` | not user-friendly but works in gated scripts | env config path exists | not applicable | Kimi/DashScope path reported usable | reported | dogfood ready | `agent/provider/config.py`, `config.py`, `scripts/dogfood_real_provider_e2e.py` | medium: `.env` loading is split between legacy/project helpers | document one blessed path |
| FakeProvider | very useful local deterministic provider | implements provider protocol | strong | not applicable | heavily used | local usable | `agent/provider/fake_provider.py`, fake/local tests | high if treated as intelligence proof | keep frozen |
| Tool registry / descriptor / execution | visible through model-triggered tools | registry + executor are real | works | works for normalized tool_use | BL5 reported | real-provider-tested | `agent/tool_registry.py`, `agent/tool_executor.py`, `tests/test_tool_*` | low-medium | keep, harden policy |
| Tool gate / invoke / result | confirmation gate exists | unified executor path for model tool_use | works | reported through planner/confirmation | BL5 partial/pass | real-provider-tested | `agent/response_handlers.py`, `agent/tool_executor.py`, `docs/dogfood/real-provider-e2e-report.json` | medium: planner intercept can be confused with direct execute | clarify stages in UX |
| tool result visible to user | implemented through response events/text | loop feeds tool result back to model/user | works | reported | dogfood reported | dogfood ready | `agent/tool_executor.py`, `agent/response_handlers.py`, tests | medium: real UX needs human validation | manual dogfood |
| system prompt tool-use guidance | strong prompt guidance present | config-driven | works | reported to improve real selection | reported | real-provider-tested | `config.py`, dogfood reports | medium: prompt text is policy-like and can sprawl | freeze except adapter issues |
| real provider tool_use E2E | reported through Tool Pipeline/planner path | not dogfood-only for tool pipeline | not applicable | verified for Kimi path | BL5 report | real-provider-tested | `scripts/dogfood_bl3_tool_use_e2e.py`, `docs/dogfood/real-provider-dogfood-report.md` | medium: sequential dogfood state bleed noted | isolate dogfood turns |
| provider tool-call compatibility | AD exists; normalization implemented | provider adapters normalize | fake supports Anthropic-style blocks | Kimi/OpenAI-compatible path tested | provider swap tests | dogfood ready | `docs/architecture/provider-tool-call-compatibility-ad.md`, `agent/provider/*`, `tests/test_provider_*` | medium: provider matrix still narrow | adapter contract loop |
| Skill | runtime action handler exists | Phase1 handler path | fixture/local | not user-facing real | L3-style evidence | demo/local usable | `agent/runtime_integration/skill_action.py`, `agent/skill_*` | high: mostly selection/evidence, not product workflow | freeze or AD-only |
| SubAgent delegation | visible through explicit commands | both direct `core.chat` command path and runtime action handler exist | deterministic L0 works | not real-child-provider | tested/reported | local usable | `agent/subagent_system/*`, `tests/test_subagent_*` | high: L0 fixture can look like real delegation | keep L0, no L2 expansion yet |
| natural-language SubAgent fixture | visible through narrow fixture phrases | pre-loop detector in `core.chat` | works | not real intelligence | tested | demo | `tests/test_subagent_user_facing.py`, `agent/core.py` | high: fixture-driven behavior can overclaim | mark demo-only |
| Memory proposal / confirmation / retain / list / forget / recall / consolidation | visible through memory commands and confirmation | mixed: memory runtime plus dispatch handlers | works | partially prompt-injected | memory E2E fake | local usable | `agent/memory_runtime.py`, `agent/runtime_integration/memory_*`, `docs/dogfood/memory-e2e-report.json` | high for consolidation and cross-session claims | freeze consolidation, polish recall UX |
| MEMORY_RECALL dual-path | AD exists and implementation paths exist | prompt injection + runtime action evidence | works locally | not deeply dogfooded real | documented | local usable | `docs/design/MEMORY_RECALL_DUAL_PATH_AD.md`, `agent/runtime_integration/memory_recall.py` | medium-high: user may not feel recall | human dogfood |
| checkpoint save/resume | implemented as local checkpoint utilities | runtime action handler exists | works in tests | not real-provider-specific | tested | local usable | `agent/checkpoint.py`, `agent/checkpoint_runtime.py`, tests | medium: UX and safety policy thin | UX/safety review |
| streaming / `STREAMING_EVENT` / progress | protocol and event mapping exist | Phase1 streaming actions and provider streaming wrapper | fake streaming works | limited/provider-dependent | reported | demo/local usable | `agent/provider/streaming.py`, `agent/runtime_integration/streaming_provider.py`, tests | high: progress UX not broad | freeze event schema, polish UX |
| trace / run summary | events, trace, summary exist | integrated with loop/dispatcher | works | partly depends on dispatcher injection | reported | dogfood ready for debug | `agent/tracing.py`, `agent/run_summary.py`, `agent/runtime_integration/evidence.py` | medium: default real path may be thinner | make default debug path explicit |
| command router | explicit CLI command routing exists | command shortcuts run before main loop | works locally | not provider-dependent | tested | local usable | `agent/cli_commands.py`, `agent/core.py`, command tests | high: can become second runtime | constrain to presentation/intent only |
| dogfood scripts/reports | extensive and useful | mostly outside product runtime | works when run | gated real scripts exist | many reports | dogfood ready | `scripts/dogfood*`, `docs/dogfood/*` | high: scripts can overfit evidence | consolidate reports |
| safety / approval / confirmation parser | confirmation parser and risk metadata exist | executor enforces for tools | works | provider-agnostic | tested | local usable | `agent/tool_policy.py`, `agent/tool_executor.py`, `agent/tools/*` | medium: no real sandbox, shell parser limited | hardening loop |
| Hook/lifecycle extension | contract/deferred mentions exist | not full product extension API | limited | none | AD/deferred | stub | docs and runtime hook code | high if claimed as extensible hook system | keep deferred |
| MCP boundary | registry metadata and high-risk concepts exist | no real MCP connection in product path | fake/local only | not real | deferred | stub/demo | MCP-related tests/docs | high | keep deferred |
| docs/onboarding | comprehensive but noisy | docs encode governance | works for agents, less for humans | real provider docs scattered | many docs | local usable for maintainers | `README.md`, `docs/index*`, `docs/dogfood/*`, plans | high: source-of-truth drift | docs cleanup loop |

## C. Architecture Red-Team Audit

Target flow:

```text
query/event
-> core.chat / loop.py / real runtime loop
-> finite branch point / subsystem intervention
-> dispatcher / handler / adapter
-> evidence / state update / result feedback
-> return to unified runtime flow
```

| question | verdict | red-team assessment |
| --- | --- | --- |
| 1. Is there still only one main flow? | CONCERN | The model/tool loop is unified, but pre-loop `core.chat` command shortcuts for memory, subagent, and summaries execute capabilities outside `loop.py` and outside the dispatcher. It is not a second LLM runtime yet, but it is a second capability plane. |
| 2. Is command router becoming a second runtime? | CONCERN | `show memories`, `forget`, `show subagents`, `delegate to`, and natural-language subagent fixture handling are direct service invocations. This is acceptable for CLI affordances only if frozen and moved behind a typed command-intent boundary. |
| 3. Does FakeProvider carry too much real intelligence? | CONCERN | FakeProvider is deterministic and useful, but it encodes tool intent, subagent phrases, memory-like recall prompts, and streaming simulation. It should remain a frozen test double, not a product capability validator. |
| 4. Did real-provider dogfood pollute main code? | PASS/CONCERN | Real-provider work mostly stayed in providers, tests, and scripts. Concern remains that dogfood scripts inject dispatcher/state in ways the default real-provider product path may not. |
| 5. Is Tool Pipeline still unified? | PASS/CONCERN | Model-emitted tool_use goes through `response_handlers` -> `tool_executor` -> confirmation/result, which is good. Synthetic turn-end tool actions and command shortcuts create evidence paths that can be mistaken for real user-path tool execution. |
| 6. Is SubAgent still a finite intervention point? | CONCERN | Runtime handler is bounded, but product-facing SubAgent commands also call delegation directly from `core.chat`, and runtime/demo roots include `tests/fixtures/subagents`. |
| 7. Is Memory boundary clear? | CONCERN | Retain/confirm/list are understandable; forget bypasses the same confirmation policy, recall has dual paths, and module-level memory runtime risks cross-session leakage in broader use. Consolidation is correctly frozen/deferred. |
| 8. Do Streaming/Progress/Trace reuse event/trace体系? | PASS/CONCERN | Streaming and trace reuse runtime events/evidence. The concern is UX maturity, default real-provider instrumentation, and whether progress is product feedback or evidence-only. |
| 9. Is there dogfood-only path pretending to be product path? | CONCERN | Reports are mostly honest, but `scripts/dogfood*`, `agent/local_demo.py`, and fixture-backed subagents can be read as product evidence unless aggressively labeled. |
| 10. Are direct handlers/dispatchers/adapters pretending to be E2E? | CONCERN | The evidence taxonomy is unusually honest, but the repo still contains many direct handler tests. The danger is not current fraud; it is future summary drift. |

Specific answers:

1. There is one real model/tool loop, but not one clean capability execution path.
2. Command router is the most likely hidden second runtime.
3. FakeProvider is frozen but still semantically fat.
4. Real-provider dogfood has not badly polluted core code, but evidence setup diverges from default product setup.
5. Tool Pipeline is unified for provider tool calls; synthetic actions and CLI direct paths need clearer labels.
6. SubAgent is bounded architecturally but demo-fixture-dependent in product-facing code.
7. Memory is mostly bounded but has mixed UX/control paths.
8. Streaming/trace reuse existing systems, but are not yet strong user-facing product features.
9. Dogfood-only path exists as supporting harness; current docs are mostly honest but too numerous.
10. Direct-call tests are useful unit/contract tests, but must not be marketed as L3/user E2E.

## D. Code Quality Red-Team Audit

Overall code quality verdict: the codebase is readable and disciplined for an AutoRun-heavy prototype, but the core has reached the point where more capability work will compound complexity faster than product value.

Key observations:

- `agent/core.py` is a god-adjacent orchestration module. It owns provider setup, memory command handling, subagent command handling, runtime prompt refresh, trace setup, loop context creation, and output rendering. At 1,100+ lines, it is no longer a small entrypoint.
- `agent/loop.py` keeps the actual model loop relatively clear, but `_try_phase1_turn_end_runtime_action()` is a capability bus with many unrelated action branches. This is powerful for evidence, but poor as a maintainable extension surface.
- `agent/cli_commands.py` is conceptually useful, but command handling semantics are still partly implemented in `core.chat`, not fully isolated in a command layer.
- `config.py` remains a legacy compatibility module while `agent/provider/config.py` is the provider authority. This split is survivable but confusing for onboarding.
- Provider adapters are reasonably bounded. The provider protocol is small, and tool-call normalization is a real asset. The remaining risk is provider-specific behavior drifting into prompt text or registry normalization.
- `tool_registry.py` and `tool_executor.py` are among the healthier modules. Registry metadata, confirmation requirements, and model-visible descriptors are clear. `tool_executor.py` is large but cohesive enough because it owns execution semantics.
- Memory modules have a defensible separation between interaction parsing, runtime state, action handlers, and legacy compression. The weakest part is legacy `agent/memory.py`, which still imports legacy config/client assumptions and should not be treated as the modern memory boundary.
- SubAgent modules are clean for L0, but the product-facing path leaks fixtures and deterministic matching. The architecture documents are more ambitious than the implementation.
- Streaming/progress/trace modules are modular, but product semantics are not mature. They read as instrumentation more than UX.
- Dogfood scripts are valuable but bloated. `scripts/dogfood_e2e_runtime.py` and real-provider dogfood scripts carry substantial orchestration logic that can obscure whether product runtime itself is simple.
- Docs/scripts/tests are tightly coupled. This is good for evidence repeatability and bad for long-term maintainability if every capability requires a new script, report, roadmap section, audit section, and test family.

Red-team code smells:

- God module pressure: `core.py` and `loop.py`.
- Poor boundary between command UX and runtime capability execution.
- Fixture leakage: `tests/fixtures/subagents` appears in runtime/demo registration.
- In-memory singleton state: memory runtime is convenient but risky for multi-session or broader user use.
- Schema/evidence growth: `runtime_integration/evidence.py` is large and sophisticated; changes here require high discipline.
- Legacy compatibility debt: `legacy_adapter`, `config.py`, `agent/memory.py`, demo paths, and aliases should have cleanup windows.
- Prompt/config hardcoding: tool-use guidance in `SYSTEM_PROMPT` is effective but can become policy-by-prompt if not frozen.
- Dogfood state bleed: real-provider tool-use report already records planner state bleed across sequential cases.
- Safety side effect: FakeProvider argument generation can create a demo workspace directory before tool confirmation. Side effects should belong to tools after approval, not provider fakes.

## E. User Friendliness / Usability Audit

Current user journey:

1. User reads `README.md`.
2. User installs local dependencies.
3. User chooses fake/local or real provider mode.
4. User starts CLI through `main.py` or project commands.
5. User chats, triggers tool requests, confirms tools, views result.
6. User may try memory commands, subagent commands, or dogfood checklist.
7. User may inspect run summary, trace, reports, or docs when confused.

Expected user journey:

1. User runs one clear setup command.
2. User runs one clear local fake mode command.
3. UI clearly states provider mode, model, risk posture, writable scope, and whether real API is disabled.
4. User asks normal questions and sees natural responses.
5. When a tool is needed, user sees what tool will run, why, what it can change, and how to approve/deny.
6. After execution, user sees concise tool result and next action.
7. Memory recall is visible when relevant, not hidden in traces.
8. Debug output is one command or one report, not a document hunt.
9. User can exit/resume safely.

Friction points:

- README is comprehensive but source-of-truth is diluted by roadmap/audit/dogfood docs.
- Fake vs real mode is understandable to maintainers, not obvious enough to first-time users.
- Tool confirmation exists, but the UX still feels like an engineering event stream.
- Memory features work locally but user-visible recall is not strong enough.
- SubAgent UX is fixture/demo-like and easy to overinterpret.
- Progress/streaming exists technically but does not yet define a polished experience.
- Debuggability is strong for developers and weak for normal users because evidence is scattered across trace/run summary/docs.
- Real provider use depends on environment configuration that is intentionally gated but not beginner-friendly.

Must fix before broader use:

- One blessed CLI start path with explicit fake/real banner.
- One concise debug report command/output.
- Tool confirmation/result UX polish.
- Memory recall visibility.
- Remove fixture/demo language from product-facing flows.
- Consolidate onboarding docs.
- Safety copy for shell/network/file tools.

Can live with for dogfood:

- Real provider setup requiring manual `.env`.
- L0 deterministic SubAgent.
- FakeProvider deterministic tool triggers.
- Memory consolidation frozen.
- Hook/MCP deferred.
- Trace docs being developer-focused.

Usability classification: manual-dogfood-ready and real-provider-dogfood-ready, not limited-general-user-ready.

## F. Extensibility Audit

| extension area | verdict | assessment |
| --- | --- | --- |
| New provider | mostly easy | Provider protocol and adapters are clean. The hard part is tool-call shape normalization and streaming/tool_use edge cases. |
| New tool | easy | Registry metadata and executor boundary are strong. Risk metadata and confirmation policy are present. |
| New memory backend | medium | Current memory runtime is simple and in-memory; backend swap requires clearer storage interface and session isolation. |
| New subagent | medium-low | Registry/descriptor path exists, but real delegation strategy is not productized. Fixture roots should not be the extension story. |
| New progress/trace event | easy but risky | Event/evidence plumbing is flexible, but adding event types without UX policy will create observability noise. |
| New hook/lifecycle extension | not ready | There are hooks and runtime actions, but not a stable public lifecycle API. Keep AD-only. |
| New approval policy | medium | Confirmation callbacks exist, but richer policy needs one central policy object, not scattered callable metadata. |
| Extension point clarity | mixed | Tools/providers are real extension points. Hook/MCP/SubAgent/streaming are partly real, partly evidence/demo seams. |

Extension points that are dangerous if expanded now:

- `RuntimeActionDispatcher` as a general feature bus.
- `core.chat` pre-loop command shortcuts.
- SubAgent fixture roots as user extension.
- Dogfood scripts as product adapters.
- Prompt-only provider/tool behavior tuning.
- Legacy config and legacy adapter compatibility paths.

## G. Innovation / Advancedness Audit

Real innovations:

- Unified runtime flow contract with explicit forbidden modes.
- Evidence honesty through L1/L2/L3 classification and provenance checks.
- Fake/real provider shared business runtime as an explicit governance goal.
- AutoRun workflow constrained by dirty-tree, branch, evidence, and stop-condition rules.
- Runtime action dispatcher with anti-forgery provenance and catalog-based evidence classification.
- Local-first safe dogfood that avoids external side effects by default.
- Real-provider tool-use dogfood that tests provider compatibility without turning tests into default API calls.
- Integration of memory, subagent, progress, trace, and run summary under an auditable runtime vocabulary.

Ordinary framework capabilities, not innovation by themselves:

- Basic chat loop.
- Provider abstraction.
- Tool registry and tool execution.
- Memory CRUD.
- SubAgent/handoff concept.
- Streaming events.
- Trace/run summaries.
- Confirmation prompts.
- Gated real API tests.

Behind OpenAI Agents SDK / LangGraph / Claude Code-like systems:

- No mature graph/state-machine orchestration comparable to LangGraph.
- No broadly tested multi-agent planning and handoff lifecycle.
- No production-grade durable execution with robust resumability.
- No comprehensive sandbox/permission system.
- No mature streaming UX.
- No first-class eval harness beyond dogfood scripts.
- No stable plugin/hook API.
- No mature deployment/packaging/onboarding path.
- No broad provider compatibility matrix.
- No polished coding-agent workspace operations comparable to Claude Code/Codex-style tools.

Unique advantages:

- Evidence honesty is stronger than many small agent projects.
- Fake/real boundary is unusually explicit.
- Runtime provenance and anti-forgery checks are unusually disciplined.
- Local-first dogfood discipline is practical and safe.
- Architecture docs encode negative constraints, not only aspirational design.

Top 3 innovation points to strengthen:

1. Evidence-honest runtime: make L1/L2/L3 classification a product-quality debug feature, not just audit paperwork.
2. Local-first safe personal runtime: turn fake/local mode into a polished and trusted onboarding mode.
3. Provider-normalized tool execution: make provider tool_use compatibility boring, contract-tested, and user-visible.

## H. Redundancy / Cut / Freeze Audit

| item | recommendation | reason |
| --- | --- | --- |
| FakeProvider | freeze | It is valuable as a deterministic test double, but any additional intelligence will distort real capability claims. |
| Memory Consolidation | freeze | Current consolidation is dispatch/deferred. More work here before user-visible recall improves would be architecture theater. |
| `STREAMING_EVENT` | keep but freeze schema | It is useful evidence plumbing; do not add more streaming surface until UX is proven. |
| `main.py demo` / `agent/local_demo.py` | downgrade/archive | It is a separate demo path with direct action execution, not the product runtime. Keep only if loudly labeled. |
| Dogfood markdown/json reports | consolidate | There are too many reports. Keep latest index plus canonical JSON, archive old milestone reports. |
| Global audit / issue sweep / remediation plans | consolidate | Current docs are valuable but too many parallel sources of truth. |
| `legacy_adapter` | facade only, cleanup window | Keep for compatibility tests now; define removal criteria. |
| Backward compatibility aliases | freeze and sunset | Aliases are useful during migration but will hide architecture drift if indefinite. |
| SubAgent L0/L1 | keep L0, defer L1 | L0 is useful local proof. L1 real delegation needs UX and architecture decision first. |
| Hook system | deferred | Do not implement until product command/tool/memory flow is slimmed. |
| MCP confirmation | deferred | High-risk extension; current local tools/approval need hardening first. |
| `docs/archive` | govern harder | Archive should reduce cognitive load, not become a second docs site. |
| `scripts/dogfood*` | merge/freeze | Keep one local dogfood script, one real-provider gated script, and one report generator. |
| `core.py` command shortcuts | merge into command-use-case layer | Direct shortcuts are the biggest second-runtime risk. |
| `tests/fixtures/subagents` in runtime path | remove from product path | Fixtures should not be runtime defaults. |

Things not to invest in now:

- More FakeProvider scenarios.
- More Memory Consolidation.
- More SubAgent intelligence.
- MCP runtime expansion.
- Hook implementation.
- More dogfood report formats.
- More prompt-only tuning before adapter contracts and UX cleanup.

## I. Testing / Evidence Audit

Full pytest credibility: high for regression safety, medium for product readiness. The suite appears broad and disciplined, but test pass does not prove user usability.

Focused tests credibility: high for handlers/adapters/contracts, medium for end-to-end product claims. Many direct handler tests are valuable but must remain L1/L2 evidence.

Real provider dogfood credibility: medium-high for Kimi/DashScope baseline and tool_use compatibility, medium for product UX. Reports honestly note planner confirmation and state bleed. It is not broad provider proof.

Fake/local dogfood credibility: high for deterministic local runtime behavior, low for real intelligence claims.

Dogfood scripts user-path fidelity: mixed. Some scripts call `chat()` and preserve product path; others inject dispatcher/state or sequence scenarios in a way normal users do not.

Direct handler tests overclaim risk: real. The repo has good classification docs, but future summaries can easily inflate handler tests into runtime E2E.

L1/L2/L3 honesty: above average. The evidence catalog and runtime contract are a strength. The risk is documentation drift, not current deception.

Real API tests skip/gating: reasonable. Real provider tests are gated and should remain opt-in.

Over-mock risk: medium. FakeProvider and deterministic fixtures are necessary, but they dominate evidence.

Missing contract tests:

- Default real-provider `chat()` path with dispatcher/evidence parity.
- Provider tool_use normalization across multiple real provider shapes.
- Human-facing CLI flow for approve/deny/recover.
- Secret redaction in trace/report/checkpoint outputs.
- Session isolation for memory.

Missing evidence:

- Manual human dogfood by a real user following README from scratch.
- Real provider streaming UX.
- Real provider memory recall as felt by user, not just event proof.
- Recovery/resume in a realistic interrupted session.

## J. Security / Safety Audit

Strengths:

- `.env` handling is gated and tests avoid real API by default.
- Provider config avoids printing raw secrets in normal paths.
- Runtime evidence schema rejects secret-like payload previews.
- Tool metadata includes risk and confirmation requirements.
- File tools restrict writes to project scope.
- Shell tool requires confirmation and has explicit warnings/blacklist.
- Web fetch is high-risk and confirmation-gated.

Risks:

- A dogfood report contains a masked-looking API key fragment. Even partial key fragments should not live in committed docs/reports. Replace with `SET`/`REDACTED` with no prefix/suffix.
- Fake/real switching is powerful but easy to misunderstand. The CLI should always display mode, provider, model, and real-API status.
- Confirmation is necessary but not sufficient. There is no real sandbox for shell/network tools.
- FakeProvider can create a demo directory while constructing tool arguments before confirmation; providers should not cause filesystem side effects.
- Checkpoint save/resume can persist summarized tool results; secret redaction appears better in evidence previews than in every persistence path.
- Dogfood scripts can write reports and demo workspace files when run; this is acceptable only under explicit commands.
- Memory singleton/session model is not safe enough for broader multi-user or private-data use.
- Real provider dogfood must never print env values, request bodies with secrets, or full traces containing user private content.

Security verdict: acceptable for local developer dogfood; not acceptable for broad untrusted-user use.

## K. Documentation / Onboarding Audit

README accuracy: mostly accurate, but it mixes current status, latest Big Loop results, and older roadmap next steps. A new user can see “manual dogfood ready” and still encounter future-looking sections implying core capabilities are not done.

Docs index clarity: useful for maintainers, not streamlined enough for first-time users.

Dogfood docs clarity: strong for agents/maintainers, too verbose for normal users.

Audit docs volume: too high. The project now has global audit, independent audit, remediation plan, roadmap, issue sweep, dogfood reports, final reports, and design ADs with overlapping claims.

Roadmap readability: good in isolation, but there are too many canonical-looking docs.

Source of truth: not clear enough. README, `docs/ROADMAP.md`, `docs/plans/*`, `docs/dogfood/*`, and audit docs all carry “current status” language.

New user starting point: should be README -> one quickstart -> one manual dogfood checklist. Currently there is a document maze.

Coding agent next step clarity: strong because AutoRun docs are explicit, but too many docs can cause path dependence and over-execution.

Docs to archive/merge/delete:

- Merge dogfood summaries into one `docs/dogfood/README.md` plus latest canonical report.
- Archive older Big Loop reports after linking them from an index.
- Merge issue sweep/remediation/global audit into a single current “quality backlog”.
- Keep ADs, but separate implemented ADs from proposal-only ADs.
- Downgrade demo docs that do not represent product runtime.

## L. Scores

| dimension | score | reason |
| --- | ---: | --- |
| Runtime architecture | 7 | The unified contract is strong, but command shortcuts and default real-provider dispatcher parity are unresolved. |
| Code quality | 6 | Modules are readable, but `core.py`, `loop.py`, dogfood scripts, and evidence code are getting too large. |
| Maintainability | 5 | Documentation and capability surfaces are growing faster than cleanup. |
| Extensibility | 6 | Providers/tools are extensible; hooks/subagents/memory backends are not yet safe extension surfaces. |
| User friendliness | 4 | Developer can operate it; normal user onboarding/debug is still rough. |
| Local/fake dogfood readiness | 8 | Fake/local path is well tested and documented. |
| Real provider dogfood readiness | 7 | Kimi/DashScope baseline and tool_use work, but provider matrix and UX evidence are narrow. |
| Tool-use capability | 8 | Registry, descriptors, executor, confirmation, and real provider tool_use are strong. |
| Memory UX | 5 | Retain/list/forget work, but recall visibility and session model are weak. |
| SubAgent UX | 4 | L0 delegation exists, but fixture-driven UX is not product-grade. |
| Streaming/progress UX | 4 | Event plumbing exists; user experience is not mature. |
| Trace/debug UX | 7 | Debug evidence is strong for developers, too scattered for users. |
| Safety/approval | 6 | Confirmation and metadata exist, but no robust sandbox and some reporting/persistence concerns remain. |
| Docs/onboarding | 5 | Lots of documentation, but source-of-truth drift is now a real cost. |
| Innovation | 7 | Evidence honesty and local-first governance are genuinely distinctive. |
| Advancedness vs industry | 4 | Behind mature agent SDKs on orchestration, durability, sandboxing, evals, and UX. |
| Overall | 6 | Good dogfoodable runtime prototype; not yet a lean user product. |

## M. Top Findings

| ID | severity | category | finding | evidence | impact | recommendation | safe-to-auto-run | should fix before next capability loop |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RT-01 | P1 | architecture/governance | Default real-provider product path may not auto-build the same Phase1 dispatcher/evidence path as fake or dogfood-injected runs. | `agent/core.py`, `agent/runtime_integration/phase1_hook.py`, dogfood scripts inject dispatcher/state | Fake/real runtime evidence can diverge while reports imply parity. | Decide whether dispatcher is product-default or dogfood-only; make it explicit and test it. | no, needs architecture decision | yes |
| RT-02 | P1 | architecture | `core.chat` command shortcuts are drifting toward a second capability runtime. | `show memories`, `forget`, `delegate to`, natural-language subagent handling in `agent/core.py` | Capabilities can bypass `loop.py`/dispatcher/policy/evidence boundaries. | Move command semantics behind typed command/use-case layer or explicitly mark as CLI-only. | cleanup loop only | yes |
| RT-03 | P2 | product | Manual human dogfood is still the missing evidence layer. | Dogfood reports are scripted/fake/real provider, not independent human walkthrough | Product readiness may be overestimated. | Run manual human dogfood before adding features. | no | yes |
| RT-04 | P2 | code quality | `core.py` and `loop.py` are accumulating orchestration responsibilities. | 1,100+ line `core.py`, large turn-end action function in `loop.py` | More capabilities will make behavior harder to reason about. | Code boundary slimming loop. | yes, if scoped | yes |
| RT-05 | P2 | docs/governance | Source of truth is fragmented across README, roadmap, audit, issue sweep, dogfood reports, and ADs. | `README.md`, `docs/ROADMAP.md`, `docs/plans/*`, `docs/dogfood/*` | Agents and users can follow stale next steps. | Consolidate current status and backlog. | yes | yes |
| RT-06 | P2 | security | Committed dogfood report contains a masked-looking API key fragment. | `docs/dogfood/real-provider-dogfood-report.md` | Even partial secret fragments normalize unsafe reporting. | Replace with non-reversible `SET`/`REDACTED` format and add report lint. | yes | yes |
| RT-07 | P2 | product/code | Product-facing SubAgent path depends on test fixtures and deterministic L0 behavior. | `tests/fixtures/subagents`, `agent/subagent_system/*`, `agent/core.py` | SubAgent can be overclaimed as real delegation. | Keep L0 demo, remove fixture roots from product defaults. | yes | yes |
| RT-08 | P2 | testing/evidence | Dogfood scripts are valuable but too stateful and too bespoke. | real tool-use report notes sequential planner state bleed; `scripts/dogfood*` | E2E results can reflect harness behavior. | Isolate cases and reduce script count. | yes | no |
| RT-09 | P2 | memory | Memory runtime is local/in-memory and not session-hardened enough for broader use. | `agent/memory_runtime.py`, memory docs/tests | Private data and cross-session semantics unclear. | Add session isolation and explicit storage boundary before broad use. | no | no |
| RT-10 | P2 | safety | Tool approval is confirmation-based, not sandbox-grade. | `agent/tools/shell.py`, `agent/tool_policy.py`, executor | Dangerous commands still depend on parser/confirmation discipline. | Security/approval hardening loop. | partly | no |
| RT-11 | P2 | UX | Tool and memory results are technically visible but not polished. | CLI event/rendering paths, dogfood checklist | Users may not understand what happened or what to do next. | CLI UX polish loop. | yes | yes |
| RT-12 | P3 | code quality | FakeProvider has filesystem side effect when constructing default demo tool input. | `agent/provider/fake_provider.py` | Side effects occur before confirmation. | Move directory creation into the tool execution path only. | yes | no |
| RT-13 | P3 | compatibility | Legacy adapter/config/memory paths remain without clear sunset. | `agent/provider/legacy_adapter.py`, `config.py`, `agent/memory.py` | Backward compatibility hides architecture drift. | Define cleanup window and facade policy. | yes | no |
| RT-14 | P3 | observability | Trace/run summary is strong for developers but scattered for users. | `agent/tracing.py`, `agent/run_summary.py`, reports | Debug UX depends on knowing internals. | One user-facing debug report command. | yes | no |
| RT-15 | P3 | extensibility | Hook/MCP surfaces look more real than they are. | docs/tests/registry metadata | Future work may implement high-risk extensibility before core UX is stable. | Keep deferred and document as non-product. | yes | no |
| RT-16 | P3 | testing | Direct handler tests can be accidentally marketed as user E2E. | runtime integration tests | Evidence inflation risk. | Keep L1/L2 labels in test/report names. | yes | no |
| RT-17 | P3 | product | Streaming/progress is implemented as event plumbing, not a polished UX. | streaming provider/runtime integration tests | Capability exists but user value is weak. | Freeze schema, dogfood actual UX later. | yes | no |
| RT-18 | P4 | process | AutoRun has been effective but now incentivizes additive work. | multiple Big Loop reports and remediation docs | More loops may add surface instead of reducing risk. | Switch next AutoRun, if any, to cleanup-only. | yes, cleanup only | yes |

## N. Recommended Next Big Loops

### 1. Manual Human Dogfood Feedback Loop

- why now: The project needs real human evidence before more architecture or capability work.
- scope: Follow README/checklist from scratch in fake/local mode, then one explicitly authorized real-provider session; capture confusion, errors, approval UX, memory recall, tool result visibility, and debug flow.
- out of scope: Code fixes, new features, provider expansion, dogfood script changes.
- user outcome: A real list of product friction ranked by severity.
- architecture risk: low.
- code risk: low.
- tests/gates: no pytest required unless a bug is later fixed; record exact commands and outputs.
- real API needed? optional, only with explicit user authorization.
- user authorization needed? yes for any real provider run.
- safe-to-auto-run? no, because this must be human-observed.
- stop conditions: secret exposure risk, unexpected file writes outside documented workspace, provider cost/rate issue, unclear fake/real mode.

### 2. User Journey / CLI UX Polish Loop

- why now: Most remaining risk is user comprehension, not raw capability.
- scope: Provider mode banner, start commands, approval/result copy, memory recall visibility, concise errors, one debug summary.
- out of scope: new tools, new providers, SubAgent L1, hooks, MCP.
- user outcome: A user can install, start, use, debug, and exit without reading five docs.
- architecture risk: medium because command shortcuts may need boundary cleanup.
- code risk: medium.
- tests/gates: focused CLI/user-path tests, fake dogfood checklist, `git diff --check`, ruff, pytest.
- real API needed? no.
- user authorization needed? no unless touching real provider docs.
- safe-to-auto-run? yes, but cleanup-only with strict scope.
- stop conditions: requires broad runtime refactor, changes tool policy semantics, or touches `.env`.

### 3. Code Boundary Slimming Loop

- why now: `core.py` and `loop.py` are becoming the center of all complexity.
- scope: Extract command intent/use-case boundaries, reduce turn-end action branching, label evidence-only paths.
- out of scope: behavior changes, new capabilities, provider work.
- user outcome: Same behavior with simpler maintainability.
- architecture risk: medium-high.
- code risk: high if done broadly.
- tests/gates: red/green characterization tests first, full pytest, dogfood scripts not run unless authorized.
- real API needed? no.
- user authorization needed? yes for scope approval.
- safe-to-auto-run? yes only if broken into small cleanup packs.
- stop conditions: behavior ambiguity, dirty worktree, failing characterization tests.

### 4. Docs Source-of-Truth Cleanup Loop

- why now: Documentation has become a product risk.
- scope: Define one current status page, one roadmap/backlog, one dogfood index, archive old reports, mark AD status.
- out of scope: code changes, new evidence claims.
- user outcome: Humans and agents know where to start and what is true now.
- architecture risk: low.
- code risk: low.
- tests/gates: link/path checks if available, `git diff --check`.
- real API needed? no.
- user authorization needed? no.
- safe-to-auto-run? yes.
- stop conditions: uncertain historical claim, conflicting source of truth.

### 5. Provider Tool-call Compatibility AD / Adapter Normalization Loop

- why now: Real provider tool_use is valuable and should be made boring and provider-neutral.
- scope: Contract tests for tool_use shapes, adapter normalization, finish_reason/stop_reason mapping, streaming/tool_call edge cases.
- out of scope: prompt tuning, new product tools, real API default tests.
- user outcome: More reliable real-provider tool execution.
- architecture risk: medium.
- code risk: medium.
- tests/gates: fake adapter fixtures, contract tests, gated real smoke only by explicit env.
- real API needed? optional and gated.
- user authorization needed? yes for real API.
- safe-to-auto-run? yes for fixture/contract part.
- stop conditions: provider-specific hacks leak into core loop.

### 6. Security / Approval Hardening Loop

- why now: Tools are becoming real enough that confirmation-only is not enough.
- scope: report redaction, checkpoint redaction, shell/file/network policy review, fake provider side-effect removal, mode banners.
- out of scope: real sandbox implementation unless separately approved.
- user outcome: Lower chance of secret leakage or accidental dangerous action.
- architecture risk: medium.
- code risk: medium.
- tests/gates: redaction tests, policy tests, `git diff --check`, ruff, pytest.
- real API needed? no.
- user authorization needed? no.
- safe-to-auto-run? yes if tightly scoped.
- stop conditions: needs OS sandboxing or destructive command testing.

### 7. Memory Recall User-Visible UX Loop

- why now: Memory exists but user value depends on feeling recall at the right time.
- scope: show when memory was considered, when it was injected, and what safe summary was used; improve list/forget UX.
- out of scope: consolidation, vector search, external storage, real private data.
- user outcome: User understands and controls memory.
- architecture risk: medium.
- code risk: medium.
- tests/gates: fake memory user-path tests, no real memory episodes.
- real API needed? no.
- user authorization needed? no.
- safe-to-auto-run? yes after manual dogfood.
- stop conditions: requires reading real memories or broad storage redesign.

### 8. Trace / Run Summary Report Polish Loop

- why now: Debug evidence is strong but too internal.
- scope: one concise user-facing run summary, clear event categories, error/action/result sections.
- out of scope: new trace backend, external observability.
- user outcome: User can debug a failed run without reading raw events.
- architecture risk: low-medium.
- code risk: medium.
- tests/gates: snapshot tests with redaction assertions.
- real API needed? no.
- user authorization needed? no.
- safe-to-auto-run? yes.
- stop conditions: trace contains private data or secrets.

### 9. Hook System AD Only

- why now: Hooks are tempting but unsafe to implement before boundaries are clean.
- scope: architecture decision, extension lifecycle, policy boundaries, non-goals.
- out of scope: implementation.
- user outcome: Prevent premature hook sprawl.
- architecture risk: low if AD-only.
- code risk: none.
- tests/gates: doc review only.
- real API needed? no.
- user authorization needed? no.
- safe-to-auto-run? yes.
- stop conditions: pressure to implement hooks immediately.

### 10. SubAgent Planning UX Loop

- why now: SubAgent is visible but still fixture/L0-shaped.
- scope: clarify delegation UX, registry source, capability display, failure states, parent-control policy.
- out of scope: real child provider, autonomous multi-agent execution, MCP.
- user outcome: User knows what SubAgent can and cannot do.
- architecture risk: medium.
- code risk: medium.
- tests/gates: fake-only user-path tests.
- real API needed? no.
- user authorization needed? no.
- safe-to-auto-run? yes after boundary cleanup.
- stop conditions: fixture roots remain product defaults or child runtime escapes parent policy.

## O. Final Recommendation

1. Were recent Big Loops successful? Yes. They produced real architecture hardening, provider compatibility, tool_use validation, dogfood evidence, and honest reports.
2. Should the project immediately do manual human dogfood? Yes. This is now the highest-value next step.
3. Should it continue AutoRun now? Not for new capabilities. AutoRun is acceptable only for cleanup/doc/slimming loops with hard scope.
4. Are there P0/P1 issues? No P0. Yes, P1 concerns exist around default fake/real dispatcher parity and command shortcuts becoming a second capability plane.
5. What should be fixed first: product experience, architecture, code quality, docs, or real provider? Product experience and code/docs slimming. Real provider can wait except for adapter contract hardening.
6. Should capability building pause for slimming? Yes. Pause new capabilities until manual dogfood plus slimming identifies the next real bottleneck.
7. Should real provider dogfood continue? Yes, but narrowly, gated, and after human local dogfood. Do not run it as the default next action without explicit authorization.
8. Most recommended next prompt type: `manual human dogfood`. If automation is required instead, use `/project:auto-run cleanup loop`, not `/project:auto-run next Big Loop`.

Final red-team verdict: First Agent is a credible, evidence-conscious local agent runtime prototype. It is more mature than a toy and less mature than a user product. The right next move is not more capability; it is human dogfood, UX tightening, and deliberate deletion/freezing of surfaces that AutoRun made too easy to add.

# FirstAgent Product Capability Audit

Date: 2026-06-21

Status: initial product capability audit after S-series and R-series clean close.

## Executive summary

FirstAgent already has one proven product-capability spine: a real provider can
drive the interactive CLI through governed `tool_use`, user confirmation, tool
execution, `tool_result`, final answer, and evidence/checkpoint recording. The
R-series archive proves that path with an `anthropic_compatible` DeepSeek
provider and an interactive CLI run.

That does not mean every module is productized. The mature surface is the core
runtime path and its safety/audit envelope. Several adjacent capabilities are
implemented and well tested through fake/local/contract paths, but remain
scaffolded, seam-proven, dormant, or not yet operator-ready for habitual use:
Memory, Skill, MCP, SubAgent, Scheduler, TUI, and durable recovery/ledger all
need module-level productization before they should be described as released
product capabilities.

The old current roadmap entry points were also over-claiming current authority.
`CURRENT.md`, `NEXT_ROADMAP_DIRECTION.md`, and `S_ROADMAP.md` belong in history,
not in `docs/current/`. After this cleanup, the live current set should be
limited to `TECH_DEBT.md` and this audit until the user authorizes a new
module-specific Goal/Gap loop.

Recommended next module: productize the CLI/operator workflow and capability
status foundation first. It is the lowest-risk next Goal/Gap loop, it supports
every later module, it is easy to dogfood with the already proven real-provider
path, and it reduces the chance that later agents mistake dormant code for
released product capability.

## Discovery method

This audit was discovery-driven. It did not start from a fixed module list.

Reviewed repository orientation:

- Top-level structure: `main.py`, `agent/`, `memory/`, `tui/`, `tests/`,
  `config/`, `docs/`, `scripts/`, `skills/`, `sessions/`, `workspace/`.
- Packaging and entry points: `pyproject.toml`, `requirements.txt`,
  `pytest.ini`, `README.md`.
- Current docs before cleanup: `docs/current/CURRENT.md`,
  `docs/current/NEXT_ROADMAP_DIRECTION.md`, `docs/current/S_ROADMAP.md`,
  `docs/current/TECH_DEBT.md`.
- Archive docs: `docs/archive/r-series-real-world-validation/` and
  `docs/history/` S-series/S_FINAL evidence.

Reviewed documentation signals with searches for goal, gap, roadmap, module,
tool, provider, skill, memory, MCP, subagent, scheduler, checkpoint, session,
audit, evidence, ledger, CLI, config, and diagnostic language.

Reviewed code boundaries by reading the modules that own runtime entry, provider
construction, loop dispatch, tool execution, confirmation, evidence,
checkpoint/session, ledger/recovery, memory, skill, MCP, subagent, scheduler,
security/config, and CLI/status/logs/health behavior.

Reviewed tests by directory and capability cluster:

- `tests/golden_e2e/`
- `tests/runtime_integration/`
- provider, CLI, status, real-smoke, security, memory, skill, MCP, subagent,
  scheduler, checkpoint/session, ledger/recovery, and TUI tests.

Config audit:

- `config/config.yaml` was read only to produce a sanitized readiness summary.
- No secret, API key, header, full config body, `.env`, session log, agent log,
  real MCP config, real skill directory, or real subagent directory was printed
  or copied.

Graph discovery:

- `graphify query` was attempted against the local graph. It returned only a
  small historical governance/scheduler subgraph, so it was treated as weak
  context rather than primary authority.

## Product capability map

Observed FirstAgent capability boundaries:

1. Core governed runtime spine: `main.py` -> `agent/core.py` ->
   `agent/loop.py`.
2. Provider/model boundary: fake provider, Anthropic-compatible HTTP provider,
   OpenAI-compatible/native support, provider config, provider diagnostics.
3. Interactive CLI/operator workflow: `main.py`, status, health, logs, resume,
   confirmation prompts, plain/TUI switches.
4. Tool runtime and registry: tool definitions, tool mediator, executor, file
   ops, shell/web/install/update-skill adapters.
5. Confirmation/governance/policy: approval prompts, pending action handling,
   path safety, sensitive-path guards, trial-approval guardrails.
6. Evidence/audit/observability: evidence recorder, event persistence,
   redaction, verifier, audit observability, log viewer, local trace.
7. Checkpoint/session/resume: checkpoint save/summary, session records, resume
   selection, state restoration.
8. Durable task ledger/recovery: task ledger, ledger summary, audit alignment,
   durable task progress evidence.
9. Memory: memory runtime/contracts/store, retain/recall/forget, consolidation
   seams, memory tools, memory evidence.
10. Skill system: registry, loader, selector, lifecycle, invocation, retriever,
    skill memory boundary, demo skill.
11. MCP config and bridge: MCP config CLI/service/presenter, bridge, sanitizer,
    policy, audit, tool source integration.
12. SubAgent: parent-mediated capability, inline delegation, v0 routing flag,
    L2/L3 runtime integration, local fake execution.
13. Scheduler/action planning: action scheduler, action plan parsing, scheduler
    runtime integration seam.
14. Security/config diagnostics: config authority, provider status, secret-safe
    metadata, path safety, log cleanup/viewer safety.
15. TUI/visual shell: TypeScript/Ink TUI package and tests.
16. Fake/local deterministic support: `FakeProvider`, fake-first tests, local
    contract fixtures.
17. Planning/task orchestration: task state, decision/model output contracts,
    action plan and task lifecycle helpers.

Archive-only or history-only boundaries:

- S1-S5 and S_FINAL roadmap documents under `docs/history/`.
- R-series validation documents under
  `docs/archive/r-series-real-world-validation/`.
- Historical module maturity docs that predate the R-series real path.

## Module maturity table

Levels:

- L0 `not_started`: almost no implementation.
- L1 `scaffolded`: directory/interface/shape exists, but cannot be used
  reliably.
- L2 `seam_proven`: boundary/interface is tested, but not real use.
- L3 `fake_local_verified`: fake/local path works.
- L4 `real_api_verified`: real API/provider/trigger is verified.
- L5 `operator_ready`: CLI/docs/status/troubleshooting/audit support stable
  habitual use.
- L6 `released`: goal, gap, tests, real usage, audit, and docs are all closed.

| Module | Observed code/docs/tests | Level | Evidence | Missing evidence | Productization risk | Recommended next action |
|---|---|---:|---|---|---|---|
| Core governed runtime spine | `main.py`, `agent/core.py`, `agent/loop.py`, R-series archive, golden E2E tests | L5 `operator_ready` | R-series proved real provider -> interactive CLI -> governed tool path -> final answer -> evidence/checkpoint. Runtime spine is thin CLI plus shared loop. | No module-specific post-R Goal/Gap release record. Current docs were stale before this cleanup. | Overclaim if downstream modules are treated as equally mature. | Keep as foundation; do not rewrite. Use it as the real dogfood harness for later modules. |
| Provider/model boundary | `agent/provider/`, `tests/test_provider_real_smoke.py`, provider diagnostics/status tests | L4 `real_api_verified` | Sanitized config and R-series evidence prove `anthropic_compatible` DeepSeek path, including real tool-use response. | OpenAI-compatible/native and other example providers have no discovered real smoke close-out. | Config existence may be mistaken for real API proof. | Add provider readiness matrix to operator docs/status before broadening providers. |
| Interactive CLI/operator workflow | `main.py`, `agent/cli_*`, `health`, `logs`, `status`, CLI subprocess tests | L4 `real_api_verified` | R-series interactive CLI run proved approval and tool execution. Status/redaction/resume tests exist. | Current operator runbook, capability status, and troubleshooting are not yet consolidated after roadmap cleanup. | Operators may not know which capability is real, fake/local, dormant, or unsafe to activate. | Productize next as the shared operator workflow and capability status foundation. |
| Tool runtime and registry | `agent/tool_runtime_mediator.py`, `agent/tool_executor.py`, `agent/tools/`, golden tool tests | L4 `real_api_verified` | Real `tool_use` entered confirmation, execution, `tool_result`, final answer, and evidence in R-series. | Real dogfood evidence is narrow; broad tool catalog docs/status are incomplete. | Dangerous tools can become risky if bypassing confirmation or path safety. | Keep mediator/executor spine fixed; document real-safe tool subset and troubleshooting. |
| Confirmation/governance/policy | `agent/confirmation/`, `agent/policy.py`, path safety, trial approval tests | L4 `real_api_verified` | R-series used confirmation; trial auto-approval is default-off and guarded. Sensitive path and policy tests exist. | No broader operator-facing approval policy matrix. | Auto-approval or direct dispatch would undermine product safety. | Fold approval states and failure modes into the next operator workflow Goal/Gap. |
| Evidence/audit/observability | `agent/evidence_*`, `agent/audit_observability.py`, log viewer, verifier tests | L4 `real_api_verified` | R-series recorded real `model_response`, `tool_use`, checkpoint, and final evidence. Redaction and verifier tests exist. | Module-level evidence browsing and troubleshooting are not fully operator-ready. | Raw logs or evidence could leak sensitive payloads if new paths bypass redaction. | Keep evidence recorder as the only write entry; document how to inspect safe summaries. |
| Checkpoint/session/resume | `agent/checkpoint.py`, `agent/session.py`, checkpoint runtime integration, R CLI resume tests | L3 `fake_local_verified` | Checkpoint save was seen in real R run; resume/selection is covered by local/subprocess tests. | No discovered real-provider resume dogfood after an interrupted real session. | Treating checkpoint save as proof of full recovery can overstate readiness. | Add a small real dogfood case later, after operator workflow is documented. |
| Durable task ledger/recovery | `agent/task_ledger.py`, `ledger_summary.py`, S5 docs/tests | L3 `fake_local_verified` | S5 closed with durable recovery tests; ledger is safe-summary and not state source. | No current real provider task recovery trial. | Ledger could be mistaken for canonical state or could leak if raw payloads are stored. | Keep as audit/progress continuity; productize only with explicit recovery dogfood. |
| Memory | `agent/memory*`, `agent/runtime_integration/memory*`, memory tools/tests | L3 `fake_local_verified` | Retain/recall/forget, store backends, evidence, confirmation, and consolidation seams are tested locally. | No real habitual API/CLI dogfood for memory as a user-facing capability. LLM consolidation/emergence remains frozen/default-off. | Privacy/retention and surprise recall risks. | Good second capability candidate after operator workflow; define explicit retain/recall/forget dogfood. |
| Skill system | `agent/skill_system/`, skill lifecycle/runtime tests, demo-note-maker | L3 `fake_local_verified` | Selection, lifecycle, invocation, retrieval, checkpoint, and memory boundaries are fake/local tested. | No real external skill directory or operator-ready skill install/use flow in current scope. | Reading real skill dirs or letting skills bypass runtime policy would break boundaries. | Keep fake/local; productize only with fixture/sample skills and clear install/status docs. |
| MCP config/bridge | `agent/mcp_*`, MCP config CLI/service/presenter, bridge/policy/audit tests | L3 `fake_local_verified` | Config planning, safe apply semantics, bridge policy, sanitizer, and external-flight semantics are tested without real endpoint execution. | No real MCP server connection or endpoint reachability verification. Full ecosystem is deferred. | Real MCP can expose secrets, remote commands, and external state. | Do not activate full MCP yet; later productize config/status before real endpoints. |
| SubAgent | `agent/subagent_*`, `agent/runtime_integration/subagent_*`, subagent system tests | L3 `fake_local_verified` | Parent-mediated, local fake, audit-first delegation paths and routing flag tests exist. | No released writable/multi-agent path; real provider delegated capability not operator-ready. | Splitting into a second independent agent would bypass the runtime spine. | Keep scoped and default-off; productize only after operator workflow and memory policy are stronger. |
| Scheduler/action planning | `agent/action_scheduler.py`, scheduler runtime-integration tests, dormant-boundary tests | L2 `seam_proven` | Registered/injectable seam is tested; production default is not routed. | No production trigger, operator workflow, or real provider dogfood. | Activating scheduler adds autonomy and side-effect timing risk. | Do not productize next; keep dormant until a specific user-authorized goal exists. |
| Security/config diagnostics | `agent/security.py`, provider diagnostics, status redaction tests, path safety tests | L4 `real_api_verified` | Real-provider R-series ran without secret output; config/status redaction and sensitive-path tests exist. | Needs consolidated operator-facing troubleshooting for config/provider failures. | Secret/config leakage if diagnostics start printing raw config or headers. | Extend status docs, not raw output; never stage `config/config.yaml` or `.env`. |
| TUI/visual shell | `tui/`, TypeScript/Ink tests, `main.py --tui` switch | L2 `seam_proven` | TUI code and tests exist, and CLI switch is present. | Not the default product surface; no current real-provider operator close-out. | UI may imply capabilities are released when backend modules are dormant. | Do not make TUI the next productization target. Keep as separate later UX track. |
| Fake/local deterministic support | `FakeProvider`, fake-first tests, examples | L3 `fake_local_verified` | Deterministic provider underpins CI, contracts, and safe-local demos. | It is not a real product capability ceiling. | Agents may mistake fake success for real API readiness. | Preserve as test/support capability; clearly label fake/local in docs/status. |
| Planning/task orchestration | task state, decision/model output contracts, action plan helpers | L3 `fake_local_verified` | Structured task state and action plan paths are tested; core real task loop works for a narrow governed tool case. | Scheduler and richer planning are not real/operator ready. | Broad planning claims could imply unverified autonomy. | Keep bounded to current runtime; defer higher autonomy until scheduler has a goal. |

No module is rated L6 in this audit. L6 should require a module-specific
Goal/Gap loop, real usage, audit close-out, and current documentation closure.

## Module dependency map

Foundation dependencies:

```text
Security/config hygiene
  -> Provider/model boundary
  -> Core runtime spine
  -> CLI/operator workflow
  -> Confirmation/governance
  -> Tool runtime mediator/executor
  -> Evidence/audit/checkpoint
```

Real provider/tool protocol dependencies:

- Provider/model boundary is required for any L4 module.
- Tool runtime, Skill selection, Memory tool requests, MCP tool sources, and
  SubAgent delegation all depend on model-output parsing and governed tool/action
  dispatch.
- Scheduler depends on action planning plus the same governance/evidence spine.

CLI/operator workflow dependencies:

- Provider config/status, confirmation prompts, health/logs/status, resume,
  Memory review, MCP config CLI, SubAgent commands, and future dogfood runbooks
  all need operator-facing CLI semantics.
- Without a clear operator workflow, modules can pass tests but still be hard to
  use habitually.

Memory/context dependencies:

- Memory depends on confirmation, evidence, storage backends, and privacy policy.
- Skill and SubAgent boundaries reference memory state and must not write memory
  outside the parent runtime.
- Checkpoint/session/ledger provide continuity but must not be conflated with
  memory.

Governance/audit dependencies:

- Any side-effect module must preserve confirmation and evidence: tools, memory
  mutation, MCP, SubAgent, Scheduler, shell/write/edit/install/update-skill.
- `TOOL_INVOKE` dispatcher paths must remain evidence-only; direct execution
  belongs behind the tool mediator/executor.

Modules that can be productized in parallel after the operator foundation:

- Provider readiness/status docs and troubleshooting.
- Memory retain/recall/forget dogfood.
- Skill fixture/sample workflow.
- MCP config/status dry-run workflow.

Modules that should not be productized now:

- Scheduler production activation.
- Full real MCP endpoint ecosystem.
- Writable or multi-agent SubAgent.
- Memory LLM consolidation/emergence default-on behavior.
- TUI as the default product surface.

## API/config readiness summary

Sanitized `config/config.yaml` audit:

- Config exists: yes.
- Provider/API type: `anthropic_compatible`.
- Base URL domain: `api.deepseek.com`.
- Model: `deepseek-v4-flash`.
- Enabled: `true`.
- Credential configured: yes, presence only; no key/header/value was printed.

Readiness distinctions:

| Readiness item | Status | Evidence |
|---|---|---|
| Config exists | yes | Sanitized read of `config/config.yaml`. |
| Provider construction works | yes for `anthropic_compatible` path | Provider config/diagnostics tests and R-series real-provider setup. |
| Real API call verified | yes for DeepSeek Anthropic-compatible path | R-series no-tools and tools calls returned HTTP 200; model returned real `tool_use`. |
| Module-level trigger verified | yes for core CLI/tool path only | R-series interactive CLI run completed governed tool execution. |
| Operator-ready usage verified | partial | Core path is usable; module-by-module status/troubleshooting is not yet consolidated. |

Other provider examples exist under `config/examples/`, but no discovered
module-level real verification closes them as L4 product capabilities.

## Productization meaning for this repo

In this repository, productization means a capability is usable as part of the
FirstAgent product: a real user can trigger it through the normal runtime, with
real provider/tool/API behavior where relevant, stable tests, clear CLI/status
docs, troubleshooting guidance, safety boundaries, confirmation/governance, and
evidence/audit output.

It does not mean turning a module into a standalone product, adding a UI shell,
or commercially packaging the module. It also does not mean code existence,
unit-test success, fake/local success, or config presence by itself.

## Recommended productization order

Route A: steady route

1. CLI/operator workflow and capability status foundation.
2. Provider readiness/status/troubleshooting.
3. Memory retain/recall/forget as the first higher-level user capability.

Why: this builds on the proven R-series path, reduces documentation overclaim,
and gives every later module a stable dogfood and troubleshooting surface.

Route B: capability-growth route

1. Memory.
2. Skill system with fixture/sample skills.
3. MCP config/bridge dry-run workflow.

Why: this visibly increases what FirstAgent can do, while staying below the
autonomy risk of Scheduler and full SubAgent/MCP activation.

Route C: long-term architecture route

1. Capability registry/status as a durable product contract.
2. MCP ecosystem.
3. SubAgent and Scheduler activation.

Why: this has long-term value, but it is higher risk because it touches external
protocols, multi-agent boundaries, autonomy, and operator safety.

Recommended route: Route A. Start with CLI/operator workflow and capability
status. It has satisfied dependencies, is easy to dogfood with the existing real
DeepSeek-compatible provider path, does not require new external endpoints, and
has low risk to the core end-to-end runtime.

Why not start elsewhere:

- Memory is a strong next capability, but it needs clearer operator docs/status,
  privacy boundaries, and failure inspection first.
- MCP has useful config seams, but real endpoint activation has external-service
  and secret risks.
- SubAgent needs stronger parent/operator boundaries before it becomes habitual
  product use.
- Scheduler is only seam-proven and dormant; activating it would add autonomy
  before the product surface is ready.
- TUI would polish presentation before the capability truth table is stable.

## Per-module Goal/Gap proposal

These files are proposals only. They should not be created until the user opens
that module's Goal/Gap loop.

| Module | Goal file | Gap file | Productization goal | Completion standard | Real verification required | Minimal dogfood case | Safety boundary | Main risk |
|---|---|---|---|---|---|---|---|---|
| CLI/operator workflow and capability status | `OPERATOR_WORKFLOW_GOAL.md` | `OPERATOR_WORKFLOW_GAP.md` | Make normal users know what is usable, how to run it, how to test it, and how to inspect failures. | Current docs, README/status, CLI status/health/logs, troubleshooting, and audit references agree. | Real provider interactive CLI tool-use smoke using the existing governed path. | Ask model to create a small file through confirmation, then inspect safe evidence/status. | No auto-approve, no secret output, no raw log/session disclosure. | Over-documenting future modules as released. |
| Provider/model boundary | `MODEL_PROVIDER_PRODUCT_GOAL.md` | `MODEL_PROVIDER_PRODUCT_GAP.md` | Make provider readiness explicit per provider type. | Matrix distinguishes config, construction, real API call, tool-use, and module trigger. | One real smoke per promoted provider type. | `status`/diagnostic plus one no-tools and one tool-use call. | Redact keys, headers, request bodies, and raw error bodies. | Treating examples as production-ready providers. |
| Tool runtime/governance | `TOOL_RUNTIME_GOAL.md` | `TOOL_RUNTIME_GAP.md` | Make governed tool use stable and inspectable beyond the first file-write dogfood. | Tool catalog, confirmation matrix, safe failure docs, and evidence checks exist. | Real provider tool-use for a safe write/edit path. | Write a small workspace file with confirmation and inspect tool_result. | Mediator/executor only; no direct dispatcher execution. | Dangerous tools bypassing policy. |
| Evidence/audit/ledger | `EVIDENCE_AUDIT_GOAL.md` | `EVIDENCE_AUDIT_GAP.md` | Make safe evidence inspection habitual. | Operator docs explain where safe summaries live and how to verify replay/audit. | Real run emits expected safe evidence chain. | Run a real tool-use task and verify model/tool/final/checkpoint refs. | Never print raw secrets, sessions, or agent logs. | Ledger mistaken for canonical runtime state. |
| Checkpoint/session/resume | `SESSION_RECOVERY_GOAL.md` | `SESSION_RECOVERY_GAP.md` | Make resume reliable for ordinary interrupted work. | Real interruption/resume dogfood, docs, and failure guidance pass. | Real provider run interrupted and resumed. | Start task, checkpoint, resume, finish with evidence. | Session scoped; no cross-session state bleed. | Partial checkpoint success overstated as full recovery. |
| Memory | `MEMORY_PRODUCT_GOAL.md` | `MEMORY_PRODUCT_GAP.md` | Make explicit retain/recall/forget usable with clear privacy boundaries. | CLI docs/status, confirmation, tests, real dogfood, audit, and troubleshooting close. | Real provider trigger for retain, recall, and forget through normal runtime. | Save one harmless preference, recall it, forget it, verify evidence. | Explicit user control; no surprise retention; no secret memory. | Privacy and stale recall. |
| Skill system | `SKILL_PRODUCT_GOAL.md` | `SKILL_PRODUCT_GAP.md` | Make fixture/sample skill use stable without real private skill dirs. | Install/list/select/invoke/status docs and tests close. | Real provider selection of a fixture skill, not a private skill dir. | Use `demo-note-maker` on a safe local file. | Skills cannot own loop/provider or bypass memory/tool policy. | Skill path leaks or policy bypass. |
| MCP | `MCP_PRODUCT_GOAL.md` | `MCP_PRODUCT_GAP.md` | Make MCP config/status dry-run operator-ready before live endpoints. | Validate/list/inspect/plan/apply docs and safety checks close. | Only fake/local or explicit user-authorized endpoint smoke. | Validate a sample MCP config without executing server commands. | No real home config writes, no server exec, no endpoint check unless authorized. | External service/secret exposure. |
| SubAgent | `SUBAGENT_PRODUCT_GOAL.md` | `SUBAGENT_PRODUCT_GAP.md` | Make parent-mediated read-only delegation safe and understandable. | Routing flag, CLI docs, audit evidence, and local dogfood close. | Real provider parent task may request local fake read-only delegation only. | Ask for a second opinion on a fixture file and inspect delegation evidence. | Parent runtime remains in control; no independent child agent loop. | Hidden second agent path. |
| Scheduler | `ACTION_SCHEDULER_PRODUCT_GOAL.md` | `ACTION_SCHEDULER_PRODUCT_GAP.md` | Only if user authorizes autonomy: make scheduled action plans safe. | Production trigger, confirmation, evidence, cancellation, docs, and tests close. | Explicit user-authorized real trigger only. | Schedule a harmless local no-op/report action. | Default-off; no hidden side effects. | Unintended autonomous execution. |
| TUI | `TUI_PRODUCT_GOAL.md` | `TUI_GAP.md` | Make TUI reflect real capability status without implying dormant modules are released. | TUI docs/tests and runtime smoke match CLI truth. | Real provider smoke through TUI only after CLI truth table is stable. | Run one proven CLI task through TUI. | Same confirmation/governance as CLI. | UX polish hiding backend immaturity. |

## What must not be touched yet

- Do not open S6 or a new roadmap mainline without explicit authorization.
- Do not activate Scheduler production routing; it is only seam-proven and
  dormant.
- Do not productize full MCP endpoint execution or real MCP server reachability;
  current evidence is config/bridge/dry-run oriented.
- Do not make writable/multi-agent SubAgent behavior product-default; current
  evidence is parent-mediated and local/fake scoped.
- Do not turn Memory consolidation/emergence or LLM consolidation on by default;
  frozen seams are not product release.
- Do not make TUI the primary product surface before CLI/operator capability
  truth is stable.
- Do not treat `FakeProvider` success as real provider readiness.
- Do not read, copy, stage, or summarize raw `.env`, logs, sessions/runs, real
  MCP config, real skill dirs, real subagent dirs, or private data.
- Do not stage or commit `config/config.yaml`.

## Open questions

1. Should the next Goal/Gap loop follow the steady route and productize the
   CLI/operator workflow first?
2. Should Memory be the first capability-growth module immediately after the
   operator foundation?
3. Should provider readiness be limited to the proven DeepSeek
   `anthropic_compatible` path, or should another provider get an explicit real
   smoke goal?
4. Is a larger change acceptable later for MCP/SubAgent/Scheduler, or should
   those remain deferred until the core product loop is used more often?
5. Should module status become a CLI command/output contract, a docs-only
   contract, or both?

## Final recommendation

Create the next module Goal/Gap only for the CLI/operator workflow and
capability status foundation:

- `docs/current/OPERATOR_WORKFLOW_GOAL.md`
- `docs/current/OPERATOR_WORKFLOW_GAP.md`

Suggested first gaps:

1. Define a single product capability status source that distinguishes L0-L6,
   dormant, fake/local, real API verified, and operator-ready.
2. Update README/current docs so they no longer point at closed S/R roadmap
   documents as active authority.
3. Add or consolidate operator troubleshooting for provider config, status,
   confirmation, tool failure, evidence lookup, checkpoint/resume, and safe
   log viewing.
4. Re-run one real DeepSeek-compatible interactive CLI dogfood task through the
   governed tool path and record only sanitized evidence.
5. Decide whether Memory becomes the next capability-growth Goal/Gap after this
   operator foundation closes.

No second audit is required before starting the operator workflow Goal/Gap. A
focused pre-goal review of README, CLI `status`/`health`/`logs`, and safe
evidence inspection should be enough.

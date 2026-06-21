# FirstAgent Product Capability Audit

Date: 2026-06-21

Status: independent module-level product capability audit. Discovery-driven, not
template-driven. S-series (S1-S5 + S_FINAL) and R-series (real-world validation)
are both closed and archived under `docs/history/` and `docs/archive/`. This
audit is the next phase: a fresh read of what FirstAgent can actually do as a
product, module by module.

## Executive summary

FirstAgent has exactly one product-grade capability spine today: a real model
provider can drive the interactive CLI through governed `tool_use`, a user
confirmation gate, tool execution, `tool_result`, a final answer, and a
recorded evidence/checkpoint chain. The R-series archive proves this path on an
`anthropic_compatible` DeepSeek provider end-to-end (Run 12: tool_use ->
confirmation -> manual approve -> execute -> file created -> final answer).

That spine is real, but it is narrow. Around it sits a large body of code (142
entries in `agent/`, 358 test files) whose modules are implemented and well
exercised by **fake / local / contract** tests, but are **not** productized as
habitual, operator-ready, real-triggered capabilities:

- **Memory**, **Skill**, **MCP**, **SubAgent**, and the **ActionScheduler** all
  ship default-OFF (env-gated or `None`-defaulted) and have no real-provider
  dogfood close-out in current scope.
- **Checkpoint/resume** and the **durable task ledger** are fake/local-proven
  and seam-proven, including a CLI-level resume subprocess test, but no
  real-interrupted-session resume has been dogfooded.
- The **TUI** surface exists with tests and a CLI switch, but is not the product
  surface and has no real-provider operator close-out.

Two overclaim risks exist today and are corrected here: (1) several dormant
modules look "implemented" in code but are default-off and must not be described
as released; (2) the previous README/roadmap entry points pointed at closed
S/R documents as if they were active authority. The current-doc cleanup
(`CURRENT.md`, `NEXT_ROADMAP_DIRECTION.md`, `S_ROADMAP.md` moved to
`docs/archive/`) removes the second risk.

Recommended next step: productize the **CLI/operator workflow and capability
status** foundation first. It is the lowest-risk next Goal/Gap loop, its
dependencies are already satisfied by the proven real-provider spine, it is
trivially dogfoodable, and it stops later agents from mistaking dormant code
for released capability.

## Discovery method

This audit did not start from a fixed module list. It read the repo directly.

Repository orientation reviewed:

- Top-level: `main.py`, `config.py`, `agent/` (142 entries), `memory/`, `tui/`,
  `tests/` (358 files), `config/`, `docs/`, `scripts/`, `skills/`,
  `sessions/`, `workspace/`, `llm/`.
- Packaging/entry: `pyproject.toml` (`first-agent` v0.10.0, entry
  `first-agent = "main:main"`), `requirements.txt`, `pytest.ini`, `README.md`.
- Current docs before this pass: `docs/current/` held only this audit and
  `TECH_DEBT.md` (stale `CURRENT.md` / `NEXT_ROADMAP_DIRECTION.md` /
  `S_ROADMAP.md` already relocated to `docs/archive/roadmap-history/` and
  `docs/archive/s-series-runtime-kernel/`).
- Archive/history: `docs/archive/r-series-real-world-validation/`,
  `docs/archive/roadmap-history/`, `docs/archive/s-series-runtime-kernel/`,
  and the S1-S5 + S_FINAL trees under `docs/history/`.

Documentation signals searched (rg) across `docs/`, `agent/`, `tests/`,
`README.md`: goal, gap, roadmap, module, tool, provider, skill, memory, MCP,
subagent, scheduler, checkpoint, session, audit, evidence, ledger, CLI, config,
diagnostic. Historical `docs/history/07-module-maturity/` and
`docs/history/08-global-audit/` were read as evidence of prior module claims,
not as current routing authority.

Code boundaries read for the wiring truth:

- Entry/loop: `main.py` (`main()` -> `dispatch_maintenance_command` ->
  `init_session` -> `try_resume_from_checkpoint` -> `main_loop`/textual),
  `agent/core.py` (`chat()` as the single unified entry; `LoopContext` SSOT;
  `TurnState`), `agent/loop.py` (`run_main_loop`, `action_scheduler: Any =
  None`).
- Provider: `agent/provider/factory.py` (4 real types + fake; default =
  FakeProvider when no config/env), `agent/provider/protocol.py`,
  `agent/provider/anthropic_http.py`, `agent/provider/openai_http.py`,
  diagnostics.
- Tools/governance: `agent/tool_runtime_mediator.py` (TOOL_GATE ->
  TOOL_INVOKE -> `execute_single_tool` -> TOOL_RESULT; evidence-only
  `TOOL_INVOKE`, never direct execution), `agent/tool_executor.py`,
  `agent/tools/*` (write/edit/file_ops/shell/web/skill/install/update),
  `agent/confirmation/*`, `agent/policy.py`, `agent/trial_approval.py`.
- Evidence/audit: `agent/evidence_recorder.py`, `agent/evidence_redaction.py`,
  `agent/evidence_verifier.py`, `agent/evidence_persistence.py`,
  `agent/audit_observability.py`, `agent/log_viewer.py`, `agent/local_trace.py`.
- Checkpoint/session: `agent/checkpoint.py`, `agent/session.py`,
  `agent/runtime_integration/checkpoint_*.py`.
- Ledger/recovery: `agent/task_ledger.py`, `agent/ledger_summary.py`,
  `agent/ledger_audit_alignment.py`.
- Memory: `agent/memory_runtime.py`, `agent/memory_*.py` (~40 files),
  `agent/runtime_integration/memory_*.py`.
- Skill: `agent/skill_system/*` (21 files), `agent/skill_state.py`,
  `agent/runtime_integration/skill_*.py`, gate `is_s2_skill_enabled()`
  (default OFF).
- MCP: `agent/mcp*.py` (~16 files), `agent/runtime_integration/mcp_*.py`,
  bridge gated by `MY_FIRST_AGENT_MCP_ENABLE` / config.
- SubAgent: `agent/subagent_system/*` (24 files), `agent/subagent_inline.py`
  (live L0 path), `agent/subagent_routing_flag.py` (default OFF via
  `SUBAGENT_V0_ROUTING_ENABLED`).
- Scheduler: `agent/action_scheduler.py` (dormant-by-default, registered-not-
  routed; `main.py` never passes `action_scheduler=`; CR1 AST boundary tests
  lock this).
- Security/config: `agent/security.py`, `agent/provider/diagnostics.py`,
  path-safety, redaction, `config.py`.

Test coverage reviewed by directory and capability cluster (counts of test
files whose path contains the keyword): provider 18, cli 11, memory 68, skill
29, mcp 19, subagent 39, scheduler 3, checkpoint 16, session 5, ledger 6,
evidence 20, audit 5, tool 43, confirm 11, policy 9, config 7, health 2, log 9,
real 9, e2e 10, golden 8. Real/smoke/subprocess markers:
`tests/test_provider_real_smoke.py`, `tests/smoke/test_first_usable_task_e2e.py`,
`tests/test_r_cli_resume_subprocess.py`, `tests/test_real_cli_regressions.py`,
`tests/runtime_integration/test_*_real_*`, `tests/golden_e2e/*`.

Config audit (read-only, sanitized):

- `config/config.yaml` was read only to produce a non-sensitive readiness
  summary.
- Printed only: provider type, base_url domain, model name, enabled flag, key
  presence-length. **No key, header, secret, full config body, `.env`, session
  log, agent log, real MCP config, real skill directory, or real subagent
  directory was printed, copied, or moved.**
- `git ls-files config/config.yaml .env` is empty; both are gitignored.

## Product capability map

Observed capability boundaries (discovered from code + tests, not from a list):

1. **Core governed runtime spine**: `main.py` -> `agent/core.py::chat()` ->
   `agent/loop.py::run_main_loop()`. Single unified entry; `LoopContext` is the
   one construction site (SSOT test-locked).
2. **Provider/model boundary**: `agent/provider/` — fake, `anthropic_native`,
   `anthropic_compatible`, `openai_compatible`, `openai_native`; factory +
   config + diagnostics + normalize. Default resolves to FakeProvider when no
   config/env.
3. **Interactive CLI / operator workflow**: `main.py` entry commands
   (`--plain`/`--tui`/`--shell` deprecated, `--help`, `--provider fake`),
   `dispatch_maintenance_command` (health/logs/status/demo), `main_loop`,
   resume-choice handling, provider-mode banner, onboarding render.
4. **Tool runtime and registry**: `agent/tool_registry.py`,
   `agent/tool_runtime_mediator.py`, `agent/tool_executor.py`,
   `agent/tools/*`. `TOOL_INVOKE` dispatcher path is evidence-only; execution
   happens only through `execute_single_tool`.
5. **Confirmation / governance / policy**: `agent/confirmation/*`,
   `agent/policy.py`, `agent/confirm_handlers.py`, `agent/trial_approval.py`,
   path safety, sensitive-path guards, default-off trial auto-approval.
6. **Evidence / audit / observability**: evidence recorder, persistence,
   redaction, verifier, `audit_observability`, log viewer, local trace.
7. **Checkpoint / session / resume**: `agent/checkpoint.py`, `agent/session.py`,
   `agent/runtime_integration/checkpoint_save|resume|summary.py`.
8. **Durable task ledger / recovery**: `agent/task_ledger*.py`,
   `agent/ledger_summary.py`, `agent/ledger_audit_alignment.py`.
9. **Memory**: `agent/memory_runtime.py` + ~40 `memory_*` files + runtime
   integration hooks (retain/recall/forget/consolidation/extraction).
10. **Skill system**: `agent/skill_system/*` (registry, loader, selector,
    lifecycle, retriever, memory boundary, skill tool) + runtime integration.
11. **MCP config and bridge**: `agent/mcp*.py` config CLI/service/presenter,
    bridge, sanitizer, policy, audit, external-readiness.
12. **SubAgent**: `agent/subagent_system/*`, live inline-L0 path
    (`subagent_inline.py`), frozen L1/L2 dispatcher paths, v0 routing flag.
13. **Scheduler / action planning**: `agent/action_scheduler.py`,
    `agent/planner.py` (`generate_action_plan`, `ActionPlan`), dormant seam.
14. **Security / config diagnostics**: `agent/security.py`, provider
    diagnostics, status redaction, path safety.
15. **TUI / visual shell**: `tui/` (TypeScript/Ink), `agent/input_backends/`,
    `--tui` switch.
16. **Fake / local deterministic support**: `FakeProvider`, fake-first tests,
    `agent/local_demo.py`, examples.
17. **Planning / task orchestration**: `agent/state.py`, `agent/task_state_model.py`,
    `agent/plan_schema.py`, action-plan + task lifecycle helpers.

Archive-only / history-only boundaries (evidence, not current authority):

- S1-S5 + S_FINAL roadmap docs under `docs/history/`.
- R-series validation docs under `docs/archive/r-series-real-world-validation/`.
- Historical module-maturity / global-audit docs under `docs/history/07-module-maturity/`
  and `docs/history/08-global-audit/`.

## Module maturity table

Levels:

- L0 `not_started`: almost no implementation.
- L1 `scaffolded`: directory/interface/shape exists, cannot be used reliably.
- L2 `seam_proven`: boundary/interface is tested, but not real use.
- L3 `fake_local_verified`: fake/local path works.
- L4 `real_api_verified`: real API/provider/trigger is verified.
- L5 `operator_ready`: CLI/docs/status/troubleshooting/audit support stable
  habitual use.
- L6 `released`: goal, gap, tests, real usage, audit, and docs all closed.

| Module | Observed code/docs/tests | Level | Evidence | Missing evidence | Productization risk | Recommended next action |
|---|---|---:|---|---|---|---|
| Core governed runtime spine | `main.py`, `agent/core.py::chat()`, `agent/loop.py`, SSOT tests, golden E2E, R-series | L5 `operator_ready` | R-series interactive run completed real provider -> governed tool_use -> confirmation -> execute -> final answer -> evidence/checkpoint. Single `chat()` entry, single `LoopContext` site. | No module-specific post-R Goal/Gap release record. | Downstream modules mistaken for equally mature. | Keep as foundation and dogfood harness; do not rewrite. |
| Provider/model boundary | `agent/provider/`, `factory.py` (4 real + fake), `tests/test_provider_real_smoke.py`, diagnostics tests | L4 `real_api_verified` | Sanitized config + R-series: `anthropic_compatible` DeepSeek returns HTTP 200 no-tools and tools-call, model returns real `tool_use`. F-01 tool-name bug fixed at adapter. | `openai_*`/`anthropic_native` examples have no real smoke close-out. | Config presence mistaken for real-API proof. | Add a provider readiness matrix to operator docs/status before broadening providers. |
| Interactive CLI / operator workflow | `main.py` commands, `agent/cli_commands.py`, `agent/cli_renderer.py`, health/logs/status/demo, CLI subprocess tests | L4 `real_api_verified` | R-series: interactive CLI completed the governed path; `health`/`logs`/`demo`/`status` exist; resume-choice handling present. | Consolidated capability-status + troubleshooting runbook not present after roadmap cleanup. | Operators cannot tell real/fake/dormant capabilities apart from the CLI. | Productize next as the shared operator workflow + capability status. |
| Tool runtime and registry | `tool_runtime_mediator.py`, `tool_executor.py`, `tools/*`, golden + runtime-integration tool tests | L4 `real_api_verified` | Real `tool_use` (write_file) entered confirmation, executed, produced `tool_result` + evidence in R-series. | Real dogfood is narrow (one write_file); tool catalog/status docs incomplete. | Dangerous tools risk if confirmation/path-safety bypassed. | Keep mediator/executor fixed; document safe real-tool subset and troubleshooting. |
| Confirmation / governance / policy | `agent/confirmation/*`, `agent/policy.py`, `agent/trial_approval.py`, path-safety + approval tests | L4 `real_api_verified` | R-series used the confirmation gate; trial auto-approval is default-off and guarded; sensitive-path + policy tests exist. | No operator-facing approval/policy matrix. | Auto-approval or direct dispatch would break product safety. | Fold approval states/failure modes into the next operator Goal/Gap. |
| Evidence / audit / observability | `evidence_recorder/persistence/redaction/verifier`, `audit_observability`, `log_viewer`, verifier tests | L4 `real_api_verified` | R-series recorded real `model_response`, `tool_use`, checkpoint, final evidence; redaction + verifier tests exist. | Module-level evidence browsing/troubleshooting not operator-ready. | Raw logs/evidence could leak payloads if new paths bypass redaction. | Keep recorder as the only write entry; document safe-summary inspection. |
| Checkpoint / session / resume | `checkpoint.py`, `session.py`, `runtime_integration/checkpoint_*`, resume subprocess test | L3 `fake_local_verified` | Checkpoint save seen in the real R run; resume/selection covered by local + `tests/test_r_cli_resume_subprocess.py`. | No real-provider resume dogfood after an interrupted real session. | Treating checkpoint save as full recovery overstates readiness. | Add a small real resume dogfood after operator workflow is documented. |
| Durable task ledger / recovery | `task_ledger*.py`, `ledger_summary.py`, `ledger_audit_alignment.py`, S5 tests | L3 `fake_local_verified` | S5 closed with durable recovery tests; ledger is safe-summary/continuity, not canonical state. | No current real-provider task recovery trial. | Ledger mistaken for canonical state, or raw-payload leakage. | Keep as audit continuity; productize only with explicit recovery dogfood. |
| Memory | `memory_runtime.py` + ~40 `memory_*` files + runtime integration, 68 memory tests | L3 `fake_local_verified` | retain/recall/forget, store backends, evidence, two-stage confirmation, consolidation/extraction seams tested locally. | No real habitual API/CLI dogfood for memory as a user capability; LLM consolidation/extraction default-off. | Privacy/retention and surprise-recall risk. | Strong second candidate after operator workflow; define explicit retain/recall/forget dogfood. |
| Skill system | `agent/skill_system/*` (21 files), lifecycle/selector/retriever, 29 tests, demo-note-maker | L3 `fake_local_verified` | selection, lifecycle, invocation, retrieval, checkpoint, memory boundary tested fake/local. | `is_s2_skill_enabled()` default OFF; no real-provider skill selection dogfood in current scope. | Real skill-dir reads or policy bypass breaks boundaries. | Keep fake/local; productize only with fixture/sample skills + install/status docs. |
| MCP config / bridge | `agent/mcp*.py` (~16 files), config CLI/service/presenter, bridge/policy/audit tests | L3 `fake_local_verified` | config planning, safe apply, bridge policy, sanitizer, external-flight semantics tested without real endpoint execution. | Bridge default-off; no real MCP server connection / reachability verified. | Real MCP exposes secrets, remote commands, external state. | Do not activate full MCP yet; productize config/status before real endpoints. |
| SubAgent | `agent/subagent_system/*` (24 files), `subagent_inline.py` (live L0), routing flag, 39 tests | L3 `fake_local_verified` | Parent-mediated, audit-first, inline-L0 delegation + routing flag tested; L1/L2 dispatcher paths frozen (no handler). | `SUBAGENT_V0_ROUTING_ENABLED` default OFF; no real-provider delegated capability close-out. | A second independent agent path would bypass the runtime spine. | Keep scoped and default-off; productize only after operator + memory policy are stronger. |
| Scheduler / action planning | `action_scheduler.py`, `planner.py` (`generate_action_plan`, `ActionPlan`), 3 tests, CR1 boundary tests | L2 `seam_proven` | Registered/injectable seam tested; `ActionPlan` parse path exists; production default not routed. | No production trigger, operator workflow, or real dogfood. | Activation adds autonomy and side-effect timing risk. | Do not productize next; keep dormant until a user-authorized goal exists. |
| Security / config diagnostics | `agent/security.py`, provider diagnostics, status redaction, path-safety tests | L4 `real_api_verified` | Real-provider R-series ran with no secret output; redaction + sensitive-path tests exist. | Needs consolidated operator troubleshooting for config/provider failures. | Secret/config leakage if diagnostics print raw config/headers. | Extend status docs, never raw output; never stage `config/config.yaml` or `.env`. |
| TUI / visual shell | `tui/` (TypeScript/Ink), `agent/input_backends/`, `--tui` switch, TUI tests | L2 `seam_proven` | TUI code + tests exist; CLI switch present; not the default surface. | No current real-provider operator close-out. | UI may imply dormant modules are released. | Not the next target; keep as a later separate UX track. |
| Fake / local deterministic support | `FakeProvider`, fake-first tests, `local_demo.py`, examples | L3 `fake_local_verified` | Underpins CI, contracts, safe-local demos; deterministic. | Not a product capability ceiling. | Fake success mistaken for real-API readiness. | Preserve as test/support; label fake/local clearly in docs/status. |
| Planning / task orchestration | `state.py`, `task_state_model.py`, `plan_schema.py`, action-plan + task helpers | L3 `fake_local_verified` | Structured task state + action-plan paths tested; narrow governed tool case works real. | Scheduler + richer planning not real/operator-ready. | Broad planning claims imply unverified autonomy. | Keep bounded to current runtime; defer higher autonomy until scheduler has a goal. |

No module is rated L6 in this audit. L6 should require a module-specific
Goal/Gap loop, real usage, audit close-out, and current-document closure.

## Module dependency map

Foundation dependency chain (everything downstream depends on these):

```text
Security / config hygiene (redaction, path-safety, secret-safe config)
  -> Provider / model boundary (real API + fake, one factory)
  -> Core runtime spine (chat -> loop, LoopContext SSOT)
  -> CLI / operator workflow (entry, status, health, logs, resume, confirmation)
  -> Confirmation / governance / policy
  -> Tool runtime mediator / executor (evidence-only TOOL_INVOKE)
  -> Evidence / audit / checkpoint / session
```

Real provider / tool-protocol dependencies:

- Any L4 module depends on the provider/model boundary producing a real
  `tool_use` and the runtime parsing + dispatching it through the governed
  spine.
- Tool execution, Skill selection, Memory tool requests, MCP tool sources, and
  SubAgent delegation all depend on model-output parsing +
  `ToolRuntimeMediator` / dispatcher routing + confirmation.

CLI / operator workflow dependencies:

- Provider config/status, confirmation prompts, health/logs/status, resume,
  memory review, MCP config CLI, subagent commands, and any future dogfood
  runbook all need operator-facing CLI semantics.
- Without a consolidated operator workflow, modules can pass tests but remain
  hard to use habitually.

Memory / context dependencies:

- Memory depends on confirmation, evidence, storage backends, and privacy
  policy.
- Skill and SubAgent boundaries reference memory state and must not write
  memory outside the parent runtime.
- Checkpoint/session/ledger provide continuity but must not be conflated with
  memory.

Governance / audit dependencies:

- Any side-effect module must preserve confirmation + evidence: tools, memory
  mutation, MCP, SubAgent, Scheduler, shell/write/edit/install/update-skill.
- `TOOL_INVOKE` dispatcher paths remain evidence-only; direct execution belongs
  behind the tool mediator/executor.

Parallelizable after the operator foundation: provider readiness/status docs,
memory retain/recall/forget dogfood, skill fixture/sample workflow, MCP
config/status dry-run workflow.

Do not productize now: scheduler production activation, full real MCP endpoint
ecosystem, writable/multi-agent SubAgent, memory LLM consolidation/emergence
default-on, TUI as the default surface.

## API / config readiness summary

Sanitized `config/config.yaml` audit (local-only, not committed, gitignored):

- Config exists: yes.
- Provider/API type: `anthropic_compatible`.
- Base URL domain: `https://api.deepseek.com`.
- Model: `deepseek-v4-flash`.
- Enabled: `true`.
- Credential configured: yes — presence confirmed, value length only; no key,
  header, or secret value was printed.

| Readiness item | Status | Evidence |
|---|---|---|
| Config exists | yes | Sanitized read of `config/config.yaml`. |
| Provider construction works | yes for `anthropic_compatible` | `factory.py` maps the type; provider diagnostics tests exist. |
| Real API call verified | yes for DeepSeek `anthropic_compatible` | R-series: no-tools call 200, tools call 200 (after F-01 fix), real `tool_use` returned. |
| Module-level trigger verified | yes for the core CLI/tool path | R-series interactive CLI run completed governed tool execution end-to-end. |
| Operator-ready usage verified | partial | Core path usable; per-module status/troubleshooting not yet consolidated. |

Other provider examples exist under `config/examples/`
(`deepseek-anthropic-compatible`, `fake`, `glm-openai-compatible`,
`kimi-anthropic-compatible`). None has a discovered module-level real
verification close-out, so they are config examples, not L4 product
capabilities.

## Productization meaning for this repo

In this repository, **productization** means a capability is usable as part of
the FirstAgent product: a real user can trigger it through the normal runtime,
with real provider/tool/API behavior where relevant, stable tests, clear
CLI/status docs, troubleshooting guidance, safety boundaries,
confirmation/governance, and evidence/audit output.

It does **not** mean turning a module into a standalone product, adding a UI
shell, or commercially packaging a module. It also does not mean code
existence, unit-test success, fake/local success, or config presence alone.

## Recommended productization order

**Route A — steady route (recommended):**

1. CLI / operator workflow and capability-status foundation.
2. Provider readiness / status / troubleshooting.
3. Memory retain/recall/forget as the first higher-level user capability.

Why: builds on the proven R-series path, removes the biggest overclaim risk
(operators not knowing what is real/fake/dormant), and gives every later
module a stable dogfood + troubleshooting surface. Dependencies are already
satisfied.

**Route B — capability-growth route:**

1. Memory.
2. Skill system with fixture/sample skills.
3. MCP config/bridge dry-run workflow.

Why: visibly increases what FirstAgent can do, while staying below the autonomy
risk of Scheduler and full SubAgent/MCP activation.

**Route C — long-term architecture route:**

1. Capability registry/status as a durable product contract.
2. MCP ecosystem.
3. SubAgent and Scheduler activation.

Why: highest long-term value, but higher risk — touches external protocols,
multi-agent boundaries, autonomy, and operator safety.

**Recommended route: Route A**, starting with the CLI/operator workflow and
capability-status foundation.

Why this module first:

- Dependencies satisfied: it sits on the already-proven real-provider spine.
- Easy to dogfood: a single real DeepSeek-compatible interactive CLI task
  already exercises the whole governed path.
- No new external endpoints, secrets, or autonomy required.
- Low risk to the core end-to-end path; it changes docs/status/CLI surface, not
  runtime semantics.

Why not others first:

- **Memory** — strong candidate, but needs clearer operator docs/status,
  privacy boundaries, and failure inspection before habitual use.
- **MCP** — config seams are useful, but real endpoint activation carries
  external-service and secret risk.
- **SubAgent** — needs stronger parent/operator boundaries before it becomes
  habitual; L1/L2 paths are frozen.
- **Scheduler** — only seam-proven and dormant; activation would add autonomy
  before the product surface is ready.
- **TUI** — would polish presentation before the capability truth table is
  stable.

## Per-module Goal/Gap proposal

These are proposals only. Do not create the files until the user opens that
module's Goal/Gap loop.

| Module | Goal file | Gap file | Productization goal | Completion standard | Real verification required | Minimal dogfood case | Safety boundary | Main risk |
|---|---|---|---|---|---|---|---|---|
| CLI/operator workflow + capability status | `OPERATOR_WORKFLOW_GOAL.md` | `OPERATOR_WORKFLOW_GAP.md` | Make ordinary users know what is usable, how to run it, how to test it, how to inspect failures. | Current docs, README/status, CLI status/health/logs, troubleshooting, and audit references agree. | Real-provider interactive CLI tool-use smoke via the existing governed path. | Ask the model to create a small file through confirmation, then inspect safe evidence/status. | No auto-approve, no secret output, no raw log/session disclosure. | Over-documenting future modules as released. |
| Provider/model boundary | `MODEL_PROVIDER_PRODUCT_GOAL.md` | `MODEL_PROVIDER_PRODUCT_GAP.md` | Make provider readiness explicit per provider type. | Matrix distinguishes config, construction, real API call, tool-use, module trigger. | One real smoke per promoted provider type. | `status`/diagnostic + one no-tools and one tool-use call. | Redact keys, headers, request bodies, raw error bodies. | Treating config examples as production-ready providers. |
| Tool runtime/governance | `TOOL_RUNTIME_GOAL.md` | `TOOL_RUNTIME_GAP.md` | Make governed tool use stable and inspectable beyond the first write_file dogfood. | Tool catalog, confirmation matrix, safe-failure docs, evidence checks exist. | Real-provider tool-use for a safe write/edit path. | Write a small workspace file with confirmation, inspect `tool_result`. | Mediator/executor only; no direct dispatcher execution. | Dangerous tools bypassing policy. |
| Evidence/audit/ledger | `EVIDENCE_AUDIT_GOAL.md` | `EVIDENCE_AUDIT_GAP.md` | Make safe evidence inspection habitual. | Operator docs explain where safe summaries live and how to verify replay/audit. | Real run emits the expected safe evidence chain. | Run a real tool-use task and verify model/tool/final/checkpoint refs. | Never print raw secrets, sessions, or agent logs. | Ledger mistaken for canonical runtime state. |
| Checkpoint/session/resume | `SESSION_RECOVERY_GOAL.md` | `SESSION_RECOVERY_GAP.md` | Make resume reliable for ordinary interrupted work. | Real interruption/resume dogfood, docs, and failure guidance pass. | Real-provider run interrupted and resumed. | Start task, checkpoint, resume, finish with evidence. | Session-scoped; no cross-session state bleed. | Partial checkpoint success overstated as full recovery. |
| Memory | `MEMORY_PRODUCT_GOAL.md` | `MEMORY_PRODUCT_GAP.md` | Make explicit retain/recall/forget usable with clear privacy boundaries. | CLI docs/status, confirmation, tests, real dogfood, audit, troubleshooting close. | Real-provider trigger for retain, recall, forget through the normal runtime. | Save one harmless preference, recall it, forget it, verify evidence. | Explicit user control; no surprise retention; no secret memory. | Privacy and stale recall. |
| Skill system | `SKILL_PRODUCT_GOAL.md` | `SKILL_PRODUCT_GAP.md` | Make fixture/sample skill use stable without real private skill dirs. | Install/list/select/invoke/status docs and tests close. | Real-provider selection of a fixture skill, not a private skill dir. | Use `demo-note-maker` on a safe local file. | Skills cannot own loop/provider or bypass memory/tool policy. | Skill-path leaks or policy bypass. |
| MCP | `MCP_PRODUCT_GOAL.md` | `MCP_PRODUCT_GAP.md` | Make MCP config/status dry-run operator-ready before live endpoints. | validate/list/inspect/plan/apply docs and safety checks close. | Only fake/local or explicit user-authorized endpoint smoke. | Validate a sample MCP config without executing server commands. | No real home-config writes, no server exec, no endpoint check unless authorized. | External-service/secret exposure. |
| SubAgent | `SUBAGENT_PRODUCT_GOAL.md` | `SUBAGENT_PRODUCT_GAP.md` | Make parent-mediated read-only delegation safe and understandable. | Routing flag, CLI docs, audit evidence, local dogfood close. | Real-provider parent task may request local fake read-only delegation only. | Ask for a second opinion on a fixture file and inspect delegation evidence. | Parent runtime stays in control; no independent child agent loop. | Hidden second agent path. |
| Scheduler | `ACTION_SCHEDULER_PRODUCT_GOAL.md` | `ACTION_SCHEDULER_PRODUCT_GAP.md` | Only if the user authorizes autonomy: make scheduled action plans safe. | Production trigger, confirmation, evidence, cancellation, docs, tests close. | Explicit user-authorized real trigger only. | Schedule a harmless local no-op/report action. | Default-off; no hidden side effects. | Unintended autonomous execution. |
| TUI | `TUI_PRODUCT_GOAL.md` | `TUI_GAP.md` | Make TUI reflect real capability status without implying dormant modules are released. | TUI docs/tests and runtime smoke match CLI truth. | Real-provider smoke through TUI only after the CLI truth table is stable. | Run one proven CLI task through TUI. | Same confirmation/governance as CLI. | UX polish hiding backend immaturity. |

## What must not be touched yet

- Do not open S6 or a new roadmap mainline without explicit authorization.
- Do not activate Scheduler production routing; it is seam-proven and dormant
  by default (CR1 AST boundary tests lock it).
- Do not productize full MCP endpoint execution or real MCP server
  reachability; current evidence is config/bridge/dry-run oriented.
- Do not make writable/multi-agent SubAgent behavior product-default; current
  evidence is parent-mediated, local/fake-scoped, with frozen L1/L2 paths.
- Do not turn Memory LLM consolidation/extraction on by default; frozen seams
  are not a product release.
- Do not make the TUI the primary product surface before CLI/operator capability
  truth is stable.
- Do not treat `FakeProvider` success as real-provider readiness.
- Do not read, copy, stage, or summarize raw `.env`, logs, sessions/runs, real
  MCP config, real skill dirs, real subagent dirs, or private data.
- Do not stage or commit `config/config.yaml` or `.env`.

## Open questions

1. Should the next Goal/Gap loop follow Route A and productize the CLI/operator
   workflow + capability status first?
2. Should Memory be the first capability-growth module immediately after the
   operator foundation?
3. Should provider readiness be limited to the proven DeepSeek
   `anthropic_compatible` path, or should another provider (e.g. GLM/Kimi
   examples) get an explicit real-smoke goal?
4. Is a larger change acceptable later for MCP/SubAgent/Scheduler, or should
   those stay deferred until the core product loop is used more often?
5. Should module status become a CLI command/output contract, a docs-only
   contract, or both?

## Final recommendation

Open the next module Goal/Gap only for the CLI/operator workflow and
capability-status foundation:

- `docs/current/OPERATOR_WORKFLOW_GOAL.md`
- `docs/current/OPERATOR_WORKFLOW_GAP.md`

Suggested first gaps:

1. Define a single product-capability status source that distinguishes L0-L6,
   dormant, fake/local, real-API-verified, and operator-ready — driven by this
   audit's table.
2. Reconcile README/current docs so they no longer imply dormant or
   fake/local-only modules are released.
3. Consolidate operator troubleshooting for provider config, status,
   confirmation, tool failure, evidence lookup, checkpoint/resume, and safe log
   viewing.
4. Re-run one real DeepSeek-compatible interactive CLI dogfood task through the
   governed tool path and record only sanitized evidence.
5. Decide whether Memory becomes the next capability-growth Goal/Gap after this
   operator foundation closes.

No second audit is required before starting the operator-workflow Goal/Gap. A
focused pre-goal review of README, CLI `status`/`health`/`logs`, and safe
evidence inspection should be enough.

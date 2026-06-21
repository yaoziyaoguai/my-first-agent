# FirstAgent Product Capability Audit

Date: 2026-06-21

Status: **independent re-audit**. This version supersedes the earlier 2026-06-21
draft. It was produced by an independent auditor that did not treat the prior
audit (or any project doc) as authority; every load-bearing claim was
re-grounded against code, tests, config, and the R-series archive. It is also
more conservative than the prior draft: the core spine is downgraded L5 -> L4,
and several L4 ratings are qualified or split.

## Baseline status

This audit is the **baseline** for `PRODUCTIZATION_ROADMAP.md` and
`PRODUCTIZATION_GAP_LEDGER.md`. Later module work must not override the maturity
ratings here without new evidence. Any maturity upgrade (for example L3 -> L4 or
L4 -> L5) requires real-API / real-trigger / operator-validation evidence — not
code existence, unit or fake-local test success, config presence, or a single
manual run. See the Global evidence caveat in section 4.

## 1. Executive summary

FirstAgent has exactly one proven product-capability spine: a real provider can
drive the interactive CLI through governed `tool_use`, user confirmation, tool
execution, `tool_result`, final answer, and evidence/checkpoint recording. The
R-series archive proves that path once, with an `anthropic_compatible` DeepSeek
provider and one interactive CLI run (Run 12: a single `write_file` tool_use).

That is a real but narrow foundation. Three honest caveats frame everything
below:

1. **No CI-gated real verification exists.** There is no `.github/workflows/`.
   Every real-provider smoke test (`test_provider_real_smoke.py`,
   `test_memory_anchor_real.py`, `test_real_mcp_flight.py`,
   `test_s1_fake_real_core_evidence_smoke.py`) is opt-in and `skipif` by default.
   Therefore every L4 rating in this audit rests on (a) the single manual
   R-series Run 12, plus (b) opt-in/skip-by-default smokes, plus (c) CI-gated
   unit/contract/AST tests. "Real API verified" here means "verified at least
   once by a human run", not "continuously verified by CI".
2. **No module is L5 or L6.** The prior draft rated the core spine L5
   (`operator_ready`). This audit downgrades it to L4: the L5-defining
   consolidated capability-status truth table and operator troubleshooting
   runbook do not exist, and the canonical agent-entry doc (`AGENTS.md`) points
   at a moved file. The runtime path works; the operator self-service surface
   does not.
3. **Several adjacent capabilities are well-implemented and heavily tested
   through fake/local/contract paths, but are not productized for habitual
   use:** Memory, Skill, MCP, SubAgent, Scheduler, TUI, durable recovery, and
   the evidence-inspection surface. Each is dormant, seam-proven, or
   fake/local-verified only. None must be described as released.

Two real authority-state defects were found that the prior audit missed:

- `AGENTS.md` (lines 59, 157, 159, and the whole "Current Documents" section
  53-65) still cites `docs/current/S_ROADMAP.md` as current authority. That file
  was moved to `docs/archive/s-series-runtime-kernel/S_ROADMAP.md` and no longer
  exists in `docs/current/`. `README.md` was updated on 2026-06-21; `AGENTS.md`
  was not. This is the single most important authority defect: the agent-routing
  doc tells agents to read a closed, moved file as if it were live. (This was
  the state at audit time; **remediated in the productization-roadmap commit —
  see G-001**: AGENTS.md now lists the live current docs and no longer points at
  `docs/current/S_ROADMAP.md`.)
- `graphify-out/graph.json` is stale: it still contains nodes referencing
  `docs/current/R_GAP.md` and `docs/current/R_GOAL.md`, which were moved to
  `docs/archive/r-series-real-world-validation/`. `graphify query` therefore
  returns thin/stale doc-routing nodes; run `graphify update .` to refresh.
  (State at audit time; **remediated in the productization-roadmap commit via
  `graphify update . --force` — see G-002**: the refreshed graph no longer
  references the moved paths.)

Recommended next module: productize the **CLI/operator workflow and capability
status foundation** first. It is the lowest-risk next Goal/Gap loop, it is the
gating precondition for promoting the core spine (and every other module) from
L4 toward L5, it is easy to dogfood with the already-proven DeepSeek path, and
it directly fixes the two authority defects above so later agents stop mistaking
dormant code for released capability.

## 2. Discovery method

This audit was discovery-driven, not template-driven. It did not start from a
fixed module list.

Orientation reviewed (read-only):

- Top level: `main.py`, `agent/` (140+ files), `memory/`, `tui/`, `llm/`
  (vestigial, empty), `tests/` (~379 files), `config/`, `docs/`, `scripts/`,
  `skills/`, `sessions/`, `workspace/`, `pyproject.toml`, `requirements.txt`,
  `pytest.ini`, `README.md`, `AGENTS.md`.
- Current docs: `docs/current/PRODUCT_CAPABILITY_AUDIT.md` (prior draft, treated
  as cross-reference only), `docs/current/TECH_DEBT.md`.
- Archive docs: `docs/archive/r-series-real-world-validation/` (8 files),
  `docs/archive/roadmap-history/`, `docs/archive/s-series-runtime-kernel/`.
- History docs: `docs/history/` S1-S5, S_FINAL, audits, module-maturity, design,
  rfc, plans, `CAPABILITY_BOUNDARIES.md`, `PROJECT_STATUS.md`, `CURRENT_DOCS.md`.

Discovery was executed as parallel independent agents (docs / code / tests /
config), each graphify-first, then a second adversarial pass (L4 downgrade
attempt, dormant "secretly active" hunt, completeness critic). The maturity
judgments below are the lead auditor's, grounded in that evidence.

Signals searched: goal, gap, roadmap, module, tool, provider, skill, memory,
mcp, subagent, scheduler, checkpoint, session, audit, evidence, ledger, cli,
config, diagnostic.

Config audit:

- `config/config.yaml`, `config/config.example.yaml`, `config/config.local.example.yaml`,
  `config/examples/*`, `.env.example` were read read-only to produce a sanitized
  readiness summary only.
- No secret, API key, header, full config body, `.env`, session log, agent log,
  real MCP config, real skill dir, or real subagent dir was printed or copied.
  `git check-ignore -v` and `git ls-files` confirmed `config/config.yaml` and
  `.env` are gitignored and untracked.

Graph discovery:

- `graphify query` / `path` / `explain` were run. They returned only small or
  stale subgraphs (the graph still references moved `docs/current/R_GAP.md`
  nodes). Graphify was used for code-structure orientation only; every
  load-bearing claim was verified by direct file reads with line numbers.

## 3. Product capability map

Observed FirstAgent capability boundaries (discovered, not assumed):

Spine and governance:

1. **Core governed runtime spine**: `main.py` -> `agent/core.py` ->
   `agent/loop.py` -> `agent/tool_runtime_mediator.py` ->
   `agent/tool_executor.py` -> `agent/evidence_recorder.py`.
2. **Provider/model boundary**: `agent/provider/` (factory, simple_config,
   anthropic_http, openai_http, fake_provider, diagnostics, normalize,
   streaming, legacy_adapter).
3. **Interactive CLI / operator workflow**: `main.py`, `agent/cli/commands.py`,
   `agent/cli/display.py`, `agent/cli_renderer.py`, `agent/cli_commands.py`,
   status / health / logs / resume / demo.
4. **Tool runtime and registry**: `agent/tool_registry.py`,
   `agent/tool_runtime_mediator.py`, `agent/tool_executor.py`,
   `agent/tools/*.py`, `agent/tool_scope.py`, `agent/tool_result_contract.py`.
5. **Confirmation / governance / policy**: `agent/confirmation/` (dispatcher,
   tool, memory, plan, user_input), `agent/trial_approval.py`,
   `agent/policy_decision.py`, `agent/acceptance_gate.py`, `agent/mcp_policy.py`.
6. **Evidence / audit / observability**: `agent/evidence_recorder.py`,
   `agent/evidence_persistence.py`, `agent/evidence_verifier.py`,
   `agent/evidence_redaction.py`, `agent/event_log.py`, `agent/logger.py`,
   `agent/audit_observability.py`, `agent/log_viewer.py`, `agent/local_trace.py`.
7. **Checkpoint / session / resume**: `agent/session.py` (lifecycle state
   machine), `agent/checkpoint.py` (persistence),
   `agent/runtime_integration/checkpoint_*.py`.
8. **Durable task ledger / recovery**: `agent/task_ledger*.py`,
   `agent/task_replay_chain.py`, `agent/ledger_*.py`, `agent/task_state_model.py`.

Higher-level capabilities (dormant / fake-local verified):

9. **Memory**: `agent/memory_runtime.py`, `agent/memory_store.py`,
   `agent/memory_fs_store.py`, `agent/memory_extraction.py`,
   `agent/memory_consolidation*.py` (frozen), `agent/memory_policy.py`,
   `agent/memory_review.py`, `agent/memory_owner.py`.
10. **Skill system**: `agent/skill_system/` (registry, loader, lifecycle,
    selector, skill_tool, gate, checkpoint),
    `agent/runtime_integration/skill_*.py`, `skills/` (blog-writing,
    demo-note-maker, evil-skill).
11. **MCP config / bridge**: `agent/mcp_*.py` (bridge, config, config_cli,
    config_service, config_presenter, capability, policy, sanitizer, stdio,
    external_readiness, audit), `agent/runtime_integration/mcp_*.py`.
12. **SubAgent**: `agent/subagent_system/` (delegation, executor, registry,
    v0_contract, policy, descriptors), `agent/subagent_inline.py`,
    `agent/subagent_routing_flag.py`, `agent/subagent_capability.py`.
13. **Scheduler / action-planning**: `agent/action_scheduler.py`,
    `agent/planner.py`, `agent/runtime_integration/action_scheduler_handler.py`,
    `agent/plan_schema.py`.
14. **Security / config diagnostics**: `agent/security.py`,
    `agent/health_check.py`, `agent/health_report.py`,
    `agent/provider/diagnostics.py`, `scripts/check_startup_readiness.py`,
    `scripts/check_provider_config.py`, `agent/checks.py`.

Support and substrate:

15. **TUI / visual shell**: `agent/input_backends/textual.py` +
    `agent/input_backends/simple.py` (Python backends); `tui/` is a separate
    Node.js/TypeScript companion app (not the Python runtime).
16. **Fake / local deterministic support**: `agent/provider/fake_provider.py`,
    `agent/local_demo.py`, `agent/local_config.py`, `agent/local_trace.py`,
    `agent/local_artifacts.py`, `agent/memory_extraction.py` (Fake extractors).
17. **Planning / task orchestration**: `agent/planner.py`,
    `agent/task_orchestration.py`, `agent/task_context.py`,
    `agent/task_runtime.py`, `agent/runtime_integration/dispatcher.py`,
    `agent/loop.py`, `agent/loop_context.py`.

Folded sub-boundaries (separately tested, listed explicitly so they are not
mistaken for un-governed code or a monolithic CLI/checkpoint blob):

- **Input backends / UI adapter boundary**: `agent/input_backends/`,
  `agent/user_input.py`, `agent/input_resolution.py`; pinned by
  `tests/test_input_backend_user_contract.py`.
- **Input intent classification**: `agent/input_intents.py`
  (`classify_user_input`); slash-command protocol deliberately offline/dormant.
- **Event log writer subsystem**: `agent/event_log.py` (`EventLogWriter`) with
  its own redaction layer (key/bearer/env-assign/JWT/hex/base64 regexes).
- **Health / startup-readiness operator subsystem**: `agent/health_check.py`,
  `agent/health_report.py`, `scripts/check_startup_readiness.py`; own tests.
- **Runtime events / decision frame / transitions / observer substrate**:
  `agent/runtime_events.py`, `agent/runtime_decision_frame.py`,
  `agent/transitions.py`, `agent/runtime_observer.py` (~2546 lines) - the
  governed state-machine substrate every L4 module depends on.

Archive-only / history-only boundaries:

- S1-S5 and S_FINAL roadmap documents under `docs/history/`.
- R-series validation documents under `docs/archive/r-series-real-world-validation/`.
- Historical module-maturity and capability-boundary docs under `docs/history/`.

## 4. Module maturity table

Levels:

- L0 `not_started`: almost no implementation.
- L1 `scaffolded`: directory/interface/shape exists, cannot be used reliably.
- L2 `seam_proven`: boundary/interface tested, not real use; may be dormant.
- L3 `fake_local_verified`: fake/local path works; not real-API.
- L4 `real_api_verified`: real API/provider/trigger verified at least once.
- L5 `operator_ready`: CLI/docs/status/troubleshooting/audit support stable
  habitual use.
- L6 `released`: goal, gap, tests, real usage, audit, and docs all closed.

Global evidence caveat (applies to every L4 row): no `.github/workflows/`
exists; all real-provider smokes are opt-in/skip-by-default. Every L4 rests on
the single manual R-series Run 12 + opt-in smokes + CI-gated
unit/contract/AST tests. No L4 is CI-gated real verification.

| Module | Observed code/docs/tests | Level | Evidence | Missing evidence | Productization risk | Recommended next action |
|---|---|---:|---|---|---|---|
| Core governed runtime spine | `main.py`, `agent/core.py`, `agent/loop.py`, `tool_runtime_mediator.py`, `tool_executor.py`; golden E2E; 40 AST boundary tests; R-series Run 12 | **L4** | Run 12 proved real provider -> interactive CLI -> governed `tool_use` (write_file) -> confirmation -> execution -> final answer -> evidence/checkpoint. TOOL_INVOKE dispatcher is evidence-only, pinned by `test_architecture_boundaries.py:1369,1412`. Full pytest ~4946 green. | No consolidated capability-status truth table, no operator troubleshooting runbook, `AGENTS.md` stale (points at moved S_ROADMAP.md). Only ONE interactive real run. | Treating the spine as L5 lets downstream modules inherit an operator readiness that does not exist. | Keep the spine fixed. Promote to L5 only after the operator workflow + capability status foundation lands. |
| Provider/model boundary | `agent/provider/*`; `tests/test_provider_real_smoke.py`; `tests/test_provider_contract.py` | **L4 (narrow: anthropic_compatible DeepSeek only)** | DeepSeek `anthropic_compatible` real-verified in Run 12 (HTTP 200, real `tool_use` after `ae94f26` tool-name normalize). Factory defaults to FakeProvider (`factory.py:96`). Construction is offline-contract-proven. | Kimi (`anthropic_compatible`, k2.5) and GLM (`openai_compatible`, glm-5) are config-exists only, no real smoke. GLM `openai_compatible` streaming is fail-closed (`openai_http.py:420`). Real smoke is opt-in/skip-by-default. | A flat "provider L4" implies GLM/Kimi are equally proven, which is false. | Add a provider readiness matrix (config / construction / real-call / tool-use / module-trigger per provider type) before broadening providers. |
| Interactive CLI / operator workflow | `main.py`, `agent/cli/commands.py`, `agent/cli_renderer.py`; `tests/test_cli_*`, subprocess CLI tests | **L4** | Run 12/14 exercised `help`/`health`/`logs`/`demo` + interactive governed tool use under real provider. Resume seam (`session.py:405`) + status redaction exist. | Broader operator surface (log cleanup, session/run inventory, memory maintenance CLI, MCP config CLI) was NOT exercised in Run 12. No troubleshooting runbook; F-07 (status undocumented in `--help`) open. | Operators cannot self-serve status/troubleshooting; this is the gating module for spine L5. | Productize next as the shared operator workflow + capability status foundation. |
| Tool runtime and registry | `agent/tool_registry.py`, `tool_runtime_mediator.py`, `tool_executor.py`, `agent/tools/*`; golden tool tests | **L4 (write_file + edit_file)** | ~10 governed tools registered. `write_file` real-proven end-to-end (R-series Run 12 + reproducible G-010 dogfood); `edit_file` real-proven (reproducible G-015 dogfood). Mediator/executor correctness + evidence-only TOOL_INVOKE pinned by AST tests. | `run_shell`/`fetch_url` and other tools have zero real evidence. Broad tool catalog docs/status still incomplete (not L5). | Dangerous tools (shell/web) becoming risky if broadened without confirmation/path-safety dogfood. | Keep mediator/executor spine fixed; per-tool confirmation matrix in OPERATOR_GUIDE §10; broaden real-proven coverage further only with dogfood. |
| Confirmation / governance / policy | `agent/confirmation/*`, `trial_approval.py`, `policy_decision.py`, `acceptance_gate.py`; `tests/test_confirmation_*`, `test_phase3_tool_confirmation_transitions.py` | **L4 (qualified; leans L3-strong)** | Run 12 exercised ONE real confirmation flow (write_file approval). Trial approval default-off + safe-allowlist wired (`af84cb9`). Boundary AST tests confirm the package does not import UI/TUI. | Rejection escalation, `force_stop`, plan/step/user-input confirmation paths are unit/contract only (monkeypatch). No real multi-step governed flow was ever run. | Over-rating governance hides that only one approval gate is real-proven. | Fold the full approval-state matrix and failure modes into the operator workflow Goal/Gap. |
| Evidence / audit / observability | `evidence_recorder.py`, `evidence_persistence.py`, `evidence_verifier.py`, `evidence_redaction.py`, `event_log.py`, `log_viewer.py`; evidence tests | **L4 write-path / L3 inspection** | Run 12/14 recorded real `model_response` (channel=tool_use), `checkpoint_saved`, final evidence. Redaction wired into mediator (`FINAL-G03`); cross-kind duplicate-ref verifier (`FINAL-G04`). | Every evidence test is fake/unit (`_FakeEventLogWriter`). The "real" observation is one manual `logs --tail 30` (Run 14), not a test. Operator-facing evidence browsing/troubleshooting not ready. | Raw logs/evidence could leak if new paths bypass redaction; "real-verified" must not be claimed for the inspection path. | Keep `record_evidence` the only write entry; productize safe-summary inspection in the operator workflow. |
| Checkpoint / session / resume | `session.py`, `checkpoint.py`, `runtime_integration/checkpoint_*.py`; `tests/test_checkpoint_*`, `tests/test_resume_*`, subprocess resume test | **L3** | Checkpoint save observed in real Run 12. Resume covered by contract + subprocess startup test (R-G03). | No real interrupted-session resume dogfood. Complex Ctrl+C mid-flight (active provider call in flight) is NOT PTY-validated (R-series caveat). | Treating checkpoint-save as full recovery overstates readiness. | Add a small real interruption/resume dogfood after the operator foundation. |
| Durable task ledger / recovery | `task_ledger*.py`, `task_replay_chain.py`, `ledger_*.py`; S5 docs/tests | **L3** | S5 closed durable recovery (TD-011 resolved). Ledger is safe-summary, not canonical state. | No current real-provider task recovery trial. | Ledger mistaken for canonical state, or leaking if raw payloads stored. | Keep as audit/progress continuity; productize only with explicit recovery dogfood. |
| Memory | `memory_runtime.py`, `memory_store.py`, `memory_fs_store.py`, `memory_extraction.py`, `memory_consolidation*.py`, `memory_policy.py`, `memory_review.py`; ~48 test files | **L3** | Retain/recall/forget, store backends, deterministic consolidation, evidence, confirmation, review CLI are fake/local-tested. An opt-in real-provider smoke for the memory anchor EXISTS (`test_memory_anchor_real.py`, triple-gated) but is skip-by-default. | No habitual API/CLI dogfood. Consolidation subsystem is architecturally FROZEN/deferred across all 6 consolidation modules (`memory_consolidation.py:15-17`); LLM consolidation default-off (`MEMORY_CONSOLIDATION_LLM_ENABLED`). | Privacy/retention and surprise-recall risks. | Strongest L3 and the best capability-growth candidate after the operator foundation; define explicit retain/recall/forget dogfood. |
| Skill system | `agent/skill_system/*`, `runtime_integration/skill_*.py`, `skills/demo-note-maker`; ~26 test files | **L3** | Registry/loader/selector/lifecycle/invocation/retrieval/checkpoint/memory boundaries fake/local-tested. Boundary AST tests guard the seam. | No real external skill directory or operator-ready install/use flow. | Reading real skill dirs or letting skills bypass runtime policy would break boundaries. | Keep fake/local; productize with fixture/sample skills + install/status docs. |
| MCP config / bridge | `agent/mcp_*`, `runtime_integration/mcp_*`; ~16 test files | **L3** | Config CLI/service/presenter, bridge, policy, sanitizer, audit, external-readiness fake/local-tested. Default-off via `evaluate_activation(MCP_CAPABILITY)` (`main.py:610`); fake-first when enabled (dry_run=1 default). An opt-in real npx MCP flight smoke EXISTS (`test_real_mcp_flight.py`) but is skip-by-default. | No real MCP server connection in production; full ecosystem deferred (TD-009). Gate reads `os.environ` only, so config cannot silently flip it. | Real MCP exposes secrets, remote commands, external state. | Do not activate full MCP; productize config/status dry-run before real endpoints. |
| SubAgent | `agent/subagent_system/*`, `subagent_inline.py`, `subagent_routing_flag.py`, `runtime_integration/subagent_*`; ~32 test files | **L3** | Live delegation path is inline-L0 with `execution_mode='local_fake'` (`subagent_inline.py:72`). L1/L2 frozen (no handler). V0 registered-not-production-routed. Triple-gated against real; ambient `ANTHROPIC_API_KEY` cannot flip it (`test_subagent_v0_provider_modes.py:29`). Dormancy tests assert fake-local-only. | No released writable/multi-agent path; real provider delegated capability not operator-ready. | Splitting into a second independent agent would bypass the runtime spine. | Keep scoped and default-off; productize only after operator workflow + memory policy strengthen. |
| Scheduler / action-planning | `action_scheduler.py`, `planner.py`, `runtime_integration/action_scheduler_handler.py`, `plan_schema.py`; 4 test files | **L2 (dormant)** | Handler IS registered in dispatcher (`phase1_hook.py:225-229`) but registered-not-routed. `chat()` `action_scheduler=None` default; `main.py` never passes the kwarg. 3 AST/source tests prove dormancy (`test_architecture_boundaries.py:2163,2198`; `test_scheduler_boundary_l2.py`). No threading/async. | No production trigger, operator workflow, or real provider dogfood. | Activating scheduler adds autonomy and side-effect timing risk. | Do not productize next; keep dormant until a specific user-authorized goal exists. |
| Security / config diagnostics | `security.py`, `health_check.py`, `health_report.py`, `provider/diagnostics.py`, `scripts/check_*`; ~14 test files | **L4 (real-config hardened)** | R-series ran with no secret leak observed. Status api_key redaction now REAL-CONFIG-verified (G-004, 2026-06-21): `main.py status` run against the real configured key (len 35, prefix `sk-`); key absent from output; reproducible opt-in test `tests/test_r004_real_config_status_redaction.py`. Synthetic R-G01 + AST boundaries (non-provider modules cannot import SDKs) + config examples must use `sk-REPLACE_ME`. | R-004 status-redaction is now real-config-verified (was deferred). Broad diagnostic-output secret safety (no raw config/header/error bodies from any diagnostic path) tracked as G-036; still no CI-gated real verification (all real smokes opt-in). | Secret/config leakage if NEW diagnostic paths print raw config/headers. | Extend status docs, never raw output; never stage `config/config.yaml` or `.env`. Status redaction is real-config-verified; do not extend that claim to diagnostic paths not yet covered by G-036. |
| TUI / visual shell | `agent/input_backends/textual.py`+`simple.py`; `tui/` (Node/TS); 6 test files | **L2** | Python backend switch (`main.py:791-794`); `tui/` is a separate Node.js/TypeScript companion app. Boundary AST tests pin the TUI->runtime seam. | Not the default product surface; minimal test coverage (unit only); no real-provider operator close-out. | UI may imply capabilities are released when backend modules are dormant. | Do not make TUI the next target; keep as a separate later UX track. |
| Fake / local deterministic support | `fake_provider.py`, `local_demo.py`, `local_config.py`, `local_trace.py`, `local_artifacts.py` | **L3** | FakeProvider is the default-safe provider, shares the same `core.chat`/`loop.py` path, underpins CI/contracts/demos. `--provider fake` override (`main.py:671-674`). | Not a real product capability ceiling. | Fake success mistaken for real API readiness. | Preserve as test/support; clearly label fake/local in status/docs. |
| Planning / task orchestration | `planner.py`, `task_orchestration.py`, `task_context.py`, `task_runtime.py`, `runtime_integration/dispatcher.py`, `loop.py` | **L3** | Structured task state, action dispatch spine, LoopDependencies active and tested. Core real loop works for the narrow governed write case. | Scheduler not activated; richer planning not real/operator-ready. | Broad planning claims imply unverified autonomy. | Keep bounded to current runtime; defer higher autonomy until scheduler has a goal. |

No module is rated L5 or L6 in this audit. L5 requires the consolidated
operator surface (capability-status truth table + troubleshooting runbook +
non-stale entry docs) to be present and reliable; that surface does not exist
yet. L6 additionally requires a module-specific Goal/Gap loop with real usage
and audit close-out.

## 5. Module dependency map

Foundation dependencies:

```text
Security/config hygiene
  -> Provider/model boundary
  -> Core runtime spine (loop, mediator, executor)
  -> Confirmation/governance
  -> Evidence/audit/checkpoint (write path)
  -> CLI/operator workflow (the gating surface for any L5 promotion)
```

Real provider/tool protocol dependencies:

- The Provider/model boundary (DeepSeek `anthropic_compatible`) is required for
  every L4 module.
- Tool runtime, Skill selection, Memory tool requests, MCP tool sources, and
  SubAgent delegation all depend on model-output parsing and governed
  tool/action dispatch through the same mediator/executor spine.
- Scheduler depends on action planning plus the same governance/evidence spine,
  but is not routed.

CLI/operator workflow dependencies:

- Provider config/status, confirmation prompts, health/logs/status, resume,
  Memory review, MCP config CLI, SubAgent commands, and future dogfood runbooks
  all need operator-facing CLI semantics.
- The operator workflow is the gating module: until consolidated capability
  status + troubleshooting exist, modules can pass tests but cannot be promoted
  to L5, and operators cannot tell real from dormant.

Memory/context dependencies:

- Memory depends on confirmation, evidence, storage backends, and privacy
  policy.
- Skill and SubAgent reference memory state and must not write memory outside
  the parent runtime.
- Checkpoint/session/ledger provide continuity but must not be conflated with
  memory.

Governance/audit dependencies:

- Any side-effect module must preserve confirmation and evidence: tools, memory
  mutation, MCP, SubAgent, Scheduler, shell/write/edit/install/update-skill.
- `TOOL_INVOKE` dispatcher paths must remain evidence-only; direct execution
  belongs behind the tool mediator/executor (AST-pinned invariant).

Modules that can be productized in parallel after the operator foundation:

- Provider readiness/status docs and troubleshooting.
- Memory retain/recall/forget dogfood.
- Skill fixture/sample workflow.
- MCP config/status dry-run workflow.

Modules that should not be productized now:

- Scheduler production activation.
- Full real MCP endpoint ecosystem.
- Writable or multi-agent SubAgent.
- Memory LLM consolidation/emergence default-on.
- TUI as the default product surface.

## 6. API/config readiness summary

Sanitized `config/config.yaml` audit (no key/header/value printed):

- Primary provider (local, gitignored): api_type `anthropic_compatible`;
  base_url domain `api.deepseek.com`; model `deepseek-v4-flash`; enabled;
  credential present (yes; value never read).
- Secondary declared provider: api_type `fake`; enabled false; no credential.

Committed examples (`config/examples/`, `config.example.yaml`,
`config.local.example.yaml`) all use `sk-REPLACE_ME` placeholders; `git grep`
for real key patterns over `config/` and `.env*` returns nothing.

| Provider | api_type | model | Readiness |
|---|---|---|---|
| DeepSeek | `anthropic_compatible` | `deepseek-v4-flash` | real-API verified once (Run 12) + opt-in smoke |
| Kimi | `anthropic_compatible` | `kimi-k2.5` | config-exists only (~L2) |
| GLM | `openai_compatible` | `glm-5` | config-exists only (~L2); streaming fail-closed |
| Fake | `fake` | `fake-llm` | default-safe; not a real ceiling |

Readiness distinctions (per the proven path only):

| Readiness item | Status | Evidence |
|---|---|---|
| Config exists | yes | sanitized read of `config/config.yaml` + examples |
| Provider construction works | yes for `anthropic_compatible` path | `factory.py`, offline contract tests |
| Real API call verified | yes for DeepSeek `anthropic_compatible` | Run 12: no-tools 200, tools 200, real `tool_use` |
| Module-level trigger verified | yes for core CLI/tool path only | Run 12 interactive CLI completed governed tool execution |
| Operator-ready usage verified | partial | core path usable; module-by-module status/troubleshooting not consolidated |
| CI-gated real verification | no | no `.github/workflows/`; all real smokes opt-in/skip-by-default |

## 7. Productization meaning for this repo

In this repository, **productization** means a capability is usable as part of
the FirstAgent product: a real user can trigger it through the normal runtime,
with real provider/tool/API behavior where relevant, stable tests, clear
CLI/status docs, troubleshooting guidance, safety boundaries,
confirmation/governance, and evidence/audit output.

It does **not** mean turning a module into a standalone product, adding a UI
shell, or commercially packaging the module. It also does not mean code
existence, unit-test success, fake/local success, config presence, or a single
manual run by themselves.

## 8. Recommended productization order

Route A: steady route

1. CLI/operator workflow and capability status foundation (fixes the
   `AGENTS.md` stale pointer and the missing status truth table; gating
   precondition for spine L5).
2. Provider readiness/status/troubleshooting matrix (per provider type).
3. Memory retain/recall/forget as the first higher-level user capability.

Why: builds on the proven R-series path, removes the two authority-state
defects, and gives every later module a stable dogfood + troubleshooting
surface.

Route B: capability-growth route

1. Memory (strongest L3; has an opt-in real-provider smoke hook).
2. Skill system with fixture/sample skills.
3. MCP config/bridge dry-run workflow.

Why: visibly increases what FirstAgent can do, while staying below the autonomy
risk of Scheduler and full SubAgent/MCP activation.

Route C: long-term architecture route

1. Capability registry/status as a durable product contract.
2. MCP ecosystem (real endpoints).
3. SubAgent and Scheduler activation.

Why: long-term value, but higher risk (external protocols, multi-agent
boundaries, autonomy, operator safety).

**Recommended route: Route A.** Start with CLI/operator workflow and capability
status. Satisfied dependencies, easy to dogfood with the existing DeepSeek
`anthropic_compatible` path, no new external endpoints, low risk to the core
end-to-end runtime, and it is the explicit precondition for promoting the spine
from L4 toward L5.

Why not start elsewhere:

- Memory is the strongest capability-growth candidate, but it needs clearer
  operator docs/status, privacy boundaries, and failure inspection first.
- MCP has useful config seams, but real endpoint activation has
  external-service and secret risks.
- SubAgent needs stronger parent/operator boundaries before habitual use.
- Scheduler is only seam-proven and dormant; activating it adds autonomy before
  the product surface is ready.
- TUI would polish presentation before the capability truth table is stable.

## 9. Per-module Goal/Gap proposal

Proposals only. Do not create any of these files until the user opens that
module's Goal/Gap loop.

| Module | Goal file | Gap file | Productization goal | Completion standard | Real verification required | Minimal dogfood case | Safety boundary | Main risk |
|---|---|---|---|---|---|---|---|---|
| CLI/operator + capability status | `OPERATOR_WORKFLOW_GOAL.md` | `OPERATOR_WORKFLOW_GAP.md` | Make normal users know what is usable, how to run/test it, how to inspect failures. | Current docs, README/AGENTS.md, CLI status/health/logs, troubleshooting, audit refs agree; capability truth table distinguishes L0-L6/dormant/fake-local/real/operator-ready. | Re-run one real DeepSeek interactive CLI tool-use smoke via the governed path; sanitized evidence only. | Ask the model to create a small file via confirmation, then inspect safe evidence/status. | No auto-approve, no secret output, no raw log/session disclosure. | Over-documenting future modules as released; leaving AGENTS.md stale. |
| Provider/model | `MODEL_PROVIDER_PRODUCT_GOAL.md` | `MODEL_PROVIDER_PRODUCT_GAP.md` | Make provider readiness explicit per provider type. | Matrix distinguishes config, construction, real call, tool-use, module trigger, per type. | One real smoke per promoted provider type (DeepSeek done; GLM/Kimi TBD). | `status`/diagnostic + one no-tools and one tool-use call. | Redact keys, headers, request/error bodies. | Treating config examples as production-ready providers. |
| Tool runtime/governance | `TOOL_RUNTIME_GOAL.md` | `TOOL_RUNTIME_GAP.md` | Make governed tool use stable and inspectable beyond write_file. | Tool catalog, confirmation matrix, safe-failure docs, evidence checks. | Real provider tool-use for a safe write/edit path (and at least one more governed tool beyond write_file). | Write a small workspace file with confirmation; inspect `tool_result`. | Mediator/executor only; no direct dispatcher execution. | Dangerous tools bypassing policy. |
| Evidence/audit | `EVIDENCE_AUDIT_GOAL.md` | `EVIDENCE_AUDIT_GAP.md` | Make safe evidence inspection habitual (close the L3 inspection gap). | Operator docs explain where safe summaries live and how to verify replay/audit. | Real run emits the expected safe evidence chain, verified by a test not a manual log read. | Run a real tool-use task; verify model/tool/final/checkpoint refs. | Never print raw secrets/sessions/agent logs. | "Real-verified" claimed for the inspection path. |
| Checkpoint/session/resume | `SESSION_RECOVERY_GOAL.md` | `SESSION_RECOVERY_GAP.md` | Make resume reliable for ordinary interrupted work. | Real interruption/resume dogfood, docs, failure guidance. | Real provider run interrupted and resumed. | Start task, checkpoint, resume, finish with evidence. | Session scoped; no cross-session state bleed. | Partial checkpoint success overstated as full recovery. |
| Memory | `MEMORY_PRODUCT_GOAL.md` | `MEMORY_PRODUCT_GAP.md` | Make explicit retain/recall/forget usable with clear privacy boundaries. | CLI docs/status, confirmation, tests, real dogfood, audit, troubleshooting. | Real provider trigger for retain/recall/forget via normal runtime. | Save one harmless preference, recall it, forget it, verify evidence. | Explicit user control; no surprise retention; consolidation stays frozen. | Privacy and stale recall. |
| Skill system | `SKILL_PRODUCT_GOAL.md` | `SKILL_PRODUCT_GAP.md` | Make fixture/sample skill use stable without real private skill dirs. | Install/list/select/invoke/status docs and tests. | Real provider selection of a fixture skill (not a private skill dir). | Use `demo-note-maker` on a safe local file. | Skills cannot own loop/provider or bypass memory/tool policy. | Skill path leaks or policy bypass. |
| MCP | `MCP_PRODUCT_GOAL.md` | `MCP_PRODUCT_GAP.md` | Make MCP config/status dry-run operator-ready before live endpoints. | Validate/list/inspect/plan/apply docs and safety checks. | Only fake/local or explicit user-authorized endpoint smoke. | Validate a sample MCP config without executing server commands. | No real home config writes, no server exec, no endpoint check unless authorized. | External service/secret exposure. |
| SubAgent | `SUBAGENT_PRODUCT_GOAL.md` | `SUBAGENT_PRODUCT_GAP.md` | Make parent-mediated read-only delegation safe and understandable. | Routing flag, CLI docs, audit evidence, local dogfood. | Real provider parent task may request local fake read-only delegation only. | Ask for a second opinion on a fixture file; inspect delegation evidence. | Parent runtime stays in control; no independent child agent loop. | Hidden second agent path. |
| Scheduler | `ACTION_SCHEDULER_PRODUCT_GOAL.md` | `ACTION_SCHEDULER_PRODUCT_GAP.md` | Only if user authorizes autonomy. | Production trigger, confirmation, evidence, cancellation, docs, tests. | Explicit user-authorized real trigger only. | Schedule a harmless local no-op/report action. | Default-off; no hidden side effects. | Unintended autonomous execution. |
| TUI | `TUI_PRODUCT_GOAL.md` | `TUI_GAP.md` | Make TUI reflect real capability status without implying dormant modules are released. | TUI docs/tests and runtime smoke match CLI truth. | Real provider smoke through TUI only after CLI truth table is stable. | Run one proven CLI task through TUI. | Same confirmation/governance as CLI. | UX polish hiding backend immaturity. |

## 10. What must not be touched yet

- Do not open S6 or a new roadmap mainline without explicit authorization.
- Do not activate Scheduler production routing; it is registered-not-routed and
  dormant-by-default (TD-008).
- Do not productize full MCP endpoint execution or real MCP server reachability;
  current evidence is config/bridge/dry-run oriented and default-off (TD-009).
- Do not make writable/multi-agent SubAgent behavior product-default; the live
  path is inline-L0 `local_fake` and L1/L2 are frozen (TD-010).
- Do not turn Memory consolidation/emergence or LLM consolidation on by default;
  the consolidation subsystem is frozen across 6 modules
  (`memory_consolidation.py:15-17`).
- Do not make TUI the primary product surface before CLI/operator capability
  truth is stable.
- Do not treat `FakeProvider` success or opt-in/skip-by-default smoke success as
  CI-gated real verification. No `.github/workflows/` exists.
- Do not read, copy, stage, or summarize raw `.env`, logs, sessions/runs, real
  MCP config, real skill dirs, real subagent dirs, or private data.
- Do not stage or commit `config/config.yaml`.
- Do not claim redaction is verified against real credentials for diagnostic
  paths beyond `status`. R-004 status-redaction is now real-config-verified
  (G-004); broader diagnostic-output hardening is tracked as G-036 and is not
  yet real-secret-proven.

## 11. Open questions

1. Should the next Goal/Gap follow Route A and productize the CLI/operator
   workflow + capability status first?
2. Should Memory be the first capability-growth module immediately after the
   operator foundation (it is the strongest L3)?
3. Should provider readiness stay limited to the proven DeepSeek
   `anthropic_compatible` path, or should GLM/Kimi get explicit real-smoke goals?
4. Is a larger change acceptable later for MCP/SubAgent/Scheduler, or should
   those remain deferred until the core product loop is used more often?
5. Should module status become a CLI command/output contract, a docs-only
   contract, or both?
6. Should `AGENTS.md` and `graphify-out/` be refreshed in the operator-workflow
   Goal/Gap, or as a separate immediate housekeeping step?

## 12. Final recommendation

Create the next module Goal/Gap only for the **CLI/operator workflow and
capability status foundation**:

- `docs/current/OPERATOR_WORKFLOW_GOAL.md`
- `docs/current/OPERATOR_WORKFLOW_GAP.md`

Suggested first gaps (in order):

1. Fix the `AGENTS.md` stale pointers (lines 59, 157, 159, and the "Current
   Documents" section 53-65) so it points at `docs/current/PRODUCT_CAPABILITY_AUDIT.md`
   + `TECH_DEBT.md`, not the moved `S_ROADMAP.md`.
2. Run `graphify update .` so the knowledge graph stops referencing moved
   `docs/current/R_GAP.md` / `R_GOAL.md` nodes.
3. Define a single product capability status source that distinguishes L0-L6,
   dormant, fake/local, real-API-verified, and operator-ready (this table is the
   source).
4. Add/consolidate operator troubleshooting for provider config, status,
   confirmation, tool failure, evidence lookup, checkpoint/resume, and safe log
   viewing.
5. Re-run one real DeepSeek `anthropic_compatible` interactive CLI dogfood task
   through the governed tool path; record only sanitized evidence; capture it
   as a reproducible check (not a one-off manual log read).
6. Decide whether Memory becomes the next capability-growth Goal/Gap after this
   operator foundation closes.

No second audit is required before starting the operator workflow Goal/Gap. A
focused pre-goal review of `README.md`, `AGENTS.md`, CLI `status`/`health`/`logs`,
and safe evidence inspection should be enough.

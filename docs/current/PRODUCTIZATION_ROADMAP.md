# FirstAgent Productization Roadmap

Date: 2026-06-21

Baseline: [PRODUCT_CAPABILITY_AUDIT.md](PRODUCT_CAPABILITY_AUDIT.md) (second-round
independent audit, 2026-06-21). This roadmap is derived from that audit, not
from a separate subjective direction. Work intake lives in
[PRODUCTIZATION_GAP_LEDGER.md](PRODUCTIZATION_GAP_LEDGER.md); carry-forward debt
lives in [TECH_DEBT.md](TECH_DEBT.md).

## Purpose and ordering principle

"Productization" in this repo means a capability becomes usable as part of the
FirstAgent product: a real user can trigger it through the normal runtime, with
real provider/tool/API behavior where relevant, stable tests, clear CLI/status
docs, troubleshooting, safety boundaries, confirmation/governance, and
evidence/audit. It does not mean standalone packaging, a UI shell, or commercial
wrapping. See the audit's section 7.

The phase order is fixed by dependency, not by preference:

```text
Phase 0  authority + overclaim cleanup      (fix what misleads every later agent)
Phase 1  operator + capability status        (shared foundation every module needs)
Phase 2  tool runtime                        (Skill / MCP / SubAgent all depend on it)
Phase 3  memory + skill                      (first real higher-level capabilities)
Phase 4  MCP + SubAgent                      (depend on tool / governance / evidence / operator)
Phase 5  scheduler + TUI + higher autonomy   (last; highest autonomy risk)
Phase 6  release audit + dogfood loop        (per-module close-out, no overclaim)
```

Rationale: authority/status defects (Phase 0) silently corrupt every later
decision, so they go first. Operator + capability-status (Phase 1) is the gate
for promoting any module from L4 toward L5. Tool runtime (Phase 2) is the shared
execution substrate for Skill, MCP, and SubAgent. Memory/Skill (Phase 3) are the
lowest-risk real capabilities. MCP/SubAgent (Phase 4) touch external protocols
and multi-agent boundaries. Scheduler/TUI/autonomy (Phase 5) carry the most
side-effect risk and go last. Release audit (Phase 6) runs across all phases.

## Cross-phase rules

- **Gap intake is the ledger.** All new work enters
  `PRODUCTIZATION_GAP_LEDGER.md`. Do not start work that is not a ledger gap.
- **Gaps-first, debt-only-when-blocked.** A gap moves to `TECH_DEBT.md` only
  with a concrete blocker (code/architecture/external dependency), a stated
  phase impact, a future trigger, and a verification idea. "Large scope" or
  "future work" is not a debt reason.
- **No overclaim.** No module is L5 or L6 today. Maturity upgrades require
  real-API / real-trigger / operator-validation evidence (see the audit's Global
  evidence caveat). Code existence, unit/fake-local success, config presence, or
  a single manual run do not by themselves justify an upgrade.
- **No activation of dormant capability** (Scheduler, full MCP, writable
  SubAgent, Memory LLM consolidation) without an explicitly opened,
  user-authorized gap.
- **Dormant modules are not broken.** Do not "fix" dormancy by routing it.
- **Each phase closes with** an authority-consistency check (README, AGENTS.md,
  docs/current, graphify aligned) and a no-overclaim audit.

## Phase 0 — Baseline and authority cleanup

- **Goal**: freeze the second-round audit as baseline; remove every authority
  signal that misleads later agents (stale current pointers, stale graph,
  overclaim wording); establish the gaps-first debt rule.
- **Entry criteria**: second-round audit committed; docs/current limited to
  audit + tech_debt.
- **Exit criteria**: AGENTS.md points only at real current docs; graphify no
  longer references moved current files (or the gap is tracked); TECH_DEBT rule
  updated; no doc claims R-004 redaction is real-credential-verified.
- **Modules involved**: authority/docs (README, AGENTS.md, docs/current),
  graphify-out, security/config diagnostics (R-004 wording only).
- **Key gaps**: G-001, G-002, G-003, G-004, G-005, G-006.
- **Real API / trigger / usage requirements**: none (docs/authority only). R-004
  is explicitly NOT real-verified here; only its wording/policy is fixed.
- **Safety/governance constraints**: no secret output; do not claim synthetic
  redaction as real-credential proof; do not stage `config/config.yaml` or `.env`.
- **Expected maturity improvement**: none (no module changes). Removes authority
  drift that would otherwise inflate later ratings.
- **Must-not-do**: do not rewrite the audit's maturity table; do not "complete"
  R-004 by running a live-key check in this phase; do not delete historical
  docs (archive only).

## Phase 1 — Operator workflow and capability status foundation

- **Goal**: let any operator query each module's true status (L0-L6, dormant,
  fake/local, real-api-verified, operator-ready), run a governed task, inspect
  safe evidence, and recover from interruption — all without reading source.
- **Entry criteria**: Phase 0 exit (authority clean, gaps-first rule in place).
- **Exit criteria**: a capability status truth table exists as a CLI and/or docs
  contract; status/health/logs/troubleshooting runbook consolidated; a
  reproducible real DeepSeek dogfood check (not a one-off manual run); safe
  evidence inspection surface; provider readiness matrix; checkpoint/resume and
  ledger operator UX usable. Core spine and CLI/operator promotable L4 -> L5.
- **Modules involved**: CLI/operator, capability-status, evidence (inspection
  path), provider (readiness reporting), checkpoint/session/resume, durable
  ledger, confirmation/governance (full matrix).
- **Key gaps**: G-007, G-008, G-009, G-010, G-011, G-012, G-013, G-014, G-036.
- **Real API / trigger / usage requirements**: one reproducible real DeepSeek
  `anthropic_compatible` interactive CLI tool-use dogfood, captured as a
  repeatable check with sanitized evidence; provider readiness reported per
  provider type; real interruption/resume dogfood for checkpoint.
- **Safety/governance constraints**: no auto-approve; no secret output; safe
  summaries only; no raw log/session/agent-log disclosure; confirmation matrix
  documents every approval state and failure mode.
- **Expected maturity improvement**: core spine L4 -> L5; CLI/operator L4 -> L5;
  evidence inspection L3 -> L4; checkpoint/resume operator-UX usable (target
  L3-strong); ledger operator-UX usable (target L3-strong). No module reaches L6.
- **Must-not-do**: do not activate dormant modules; do not broaden real-provider
  verification to GLM/Kimi without an explicit gap; do not replace the manual
  Run 12 evidence with another one-off — make it reproducible.

## Phase 2 — Tool runtime productization

- **Goal**: make governed tool use stable and inspectable beyond `write_file`,
  across representative safe tools, with a per-tool confirmation/safety matrix.
- **Entry criteria**: Phase 1 exit (operator + capability status foundation in
  place; reproducible dogfood exists).
- **Exit criteria**: real-proven coverage for representative safe tools (not only
  `write_file`); tool safety/result/error/status productized; provider-visible
  tool diagnostics operator-usable; tool dogfood matrix feeds capability status.
- **Modules involved**: tool runtime (registry, mediator, executor), tools,
  provider-visible tool diagnostics, confirmation/governance (per-tool matrix).
- **Key gaps**: G-015, G-016, G-017, G-018.
- **Real API / trigger / usage requirements**: real-provider tool-use for a safe
  write/edit path and at least one more governed tool beyond `write_file`.
- **Safety/governance constraints**: mediator/executor only (TOOL_INVOKE stays
  evidence-only); dangerous tools (shell/web) gated by confirmation and
  path-safety; no direct dispatcher execution.
- **Expected maturity improvement**: tool runtime L4 (narrow: write_file) -> L4
  (broad) and toward L5; confirmation/governance L4 (qualified) -> L4 (solid).
- **Must-not-do**: do not auto-approve dangerous tools; do not bypass path
  safety; do not claim all ~10 registered tools are real-proven.

## Phase 3 — Memory and Skill productization

Split 3A Memory, 3B Skill. Both depend on Phase 1 (operator/status) and Phase 2
(tool/governance).

### Phase 3A — Memory

- **Goal**: make explicit retain/recall/forget usable with clear privacy
  boundaries, real trigger, and operator inspection.
- **Entry criteria**: Phase 1 + Phase 2 exit.
- **Exit criteria**: real-provider trigger for retain/recall/forget through the
  normal runtime; privacy/retention boundaries enforced; memory audit/evidence
  inspectable; consolidation policy explicit (consolidation subsystem stays
  frozen; LLM consolidation remains default-off).
- **Modules involved**: memory runtime, store, policy, review, evidence.
- **Key gaps**: G-019, G-020, G-021.
- **Real API / trigger / usage requirements**: real-provider retain/recall/forget
  dogfood (save one harmless preference, recall it, forget it, verify evidence).
- **Safety/governance constraints**: explicit user control; no surprise
  retention; no secret memory; consolidation/LLM consolidation not turned on by
  default.
- **Expected maturity improvement**: memory L3 -> L4 (real-trigger-verified);
  operator inspection toward L4. Not L5 in this phase.

### Phase 3B — Skill

- **Goal**: make fixture/sample skill use stable without reading real private
  skill directories.
- **Entry criteria**: Phase 1 + Phase 2 exit.
- **Exit criteria**: install/list/select/invoke/status docs and tests; real
  provider selection of a fixture skill; boundary enforcement verified.
- **Modules involved**: skill system (registry, loader, selector, lifecycle).
- **Key gaps**: G-022, G-023, G-024.
- **Real API / trigger / usage requirements**: real-provider selection of a
  fixture skill (e.g. `demo-note-maker` on a safe local file), not a private
  skill dir.
- **Safety/governance constraints**: skills cannot own loop/provider; cannot
  bypass tool/memory policy; fake-first, fixture/sample based.
- **Expected maturity improvement**: skill L3 -> L4. Not L5 in this phase.
- **Must-not-do**: do not read or wire real private skill dirs.

## Phase 4 — MCP and SubAgent productization

- **Goal**: move MCP from config-seam/opt-in-smoke toward real (authorized)
  usability; move SubAgent from inline `local_fake` toward governed, auditable,
  parent-mediated read-only delegation with a real trigger.
- **Entry criteria**: Phase 1 + Phase 2 (and ideally 3A for memory-policy
  alignment) exit.
- **Exit criteria**: MCP real endpoint reachability under explicit user
  authorization with secret safety; MCP dry-run operator docs; SubAgent
  parent/child boundary + delegation audit + read-only real trigger.
- **Modules involved**: MCP (bridge, config, policy, sanitizer, audit),
  SubAgent (inline, routing flag, capability, policy).
- **Key gaps**: G-025, G-026, G-027, G-028.
- **Real API / trigger / usage requirements**: explicit user-authorized MCP
  endpoint smoke only; real-provider parent task requesting local fake read-only
  SubAgent delegation.
- **Safety/governance constraints**: no real home config writes; no server exec
  unless authorized; no endpoint check unless authorized; parent runtime stays
  in control; no independent child agent loop; writable/multi-agent SubAgent
  stays not-activated (guardrail; see also TECH_DEBT TD-009/TD-010).
- **Expected maturity improvement**: MCP L3 -> L4 (authorized real endpoint);
  SubAgent L3 -> L4 (read-only real delegation). Not L5.
- **Must-not-do**: do not flip MCP on via config (gate is env-only by design);
  do not enable writable SubAgent; do not let ambient `ANTHROPIC_API_KEY` drift
  flip SubAgent to real.

## Phase 5 — Scheduler, TUI, and higher autonomy

- **Goal**: only after the capability truth table is stable and operator
  controls exist, evaluate Scheduler activation and TUI as a real surface, under
  strict autonomy safety gates.
- **Entry criteria**: Phases 1-4 exit; explicit user authorization for any
  autonomy.
- **Exit criteria**: if authorized, Scheduler has a production trigger with
  confirmation, evidence, cancellation, docs; TUI matches CLI capability truth;
  higher-autonomy safety gates present.
- **Modules involved**: Scheduler/action-planning, TUI, autonomy safety gates.
- **Key gaps**: G-029, G-030, G-031, G-035.
- **Real API / trigger / usage requirements**: explicit user-authorized real
  trigger only (e.g., schedule a harmless local no-op/report).
- **Safety/governance constraints**: default-off; no hidden side effects;
  cancellation and audit mandatory; TUI must not imply dormant modules are
  released.
- **Expected maturity improvement**: Scheduler L2 -> L3 only if activated and
  authorized; TUI L2 -> L3. Not L5/L6.
- **Must-not-do**: do not activate Scheduler before Phase 1/2 prerequisites; do
  not make TUI the default surface before capability truth is stable; see also
  TECH_DEBT TD-008.

## Phase 6 — Product release audit and dogfood loop

- **Goal**: close each module with an independent audit, real-API/trigger/usage
  evidence, a release summary, and a no-overclaim check; keep docs/current lean.
- **Entry criteria**: a module's phase exit is met.
- **Exit criteria**: per-module independent audit passes; release summary written;
  real dogfood evidence archived (sanitized); no overclaim; docs/current cleaned
  (phase artifacts archived).
- **Modules involved**: all modules reaching a release boundary.
- **Key gaps**: G-032, G-033, G-034.
- **Real API / trigger / usage requirements**: real evidence per released module,
  captured as reproducible checks (not one-off manual runs).
- **Safety/governance constraints**: no secret in archived evidence; no rating
  upgrade without evidence; dormant modules not described as released.
- **Expected maturity improvement**: selected modules may reach L5 (operator-ready)
  or L6 (released) only with a module Goal/Gap, real usage, audit close-out, and
  docs closure. L6 is not assumed; it is earned per module.
- **Must-not-do**: do not batch-claim L6; do not archive evidence containing
  secrets; do not skip the no-overclaim check.

## How to use this roadmap

1. Pick the lowest-numbered phase whose entry criteria are met.
2. Within that phase, pull gaps from `PRODUCTIZATION_GAP_LEDGER.md` by priority
   (P0 before P1 before P2 before P3), respecting dependencies.
3. Do not start a gap whose dependencies are unmet.
4. On phase exit, run the authority-consistency check and the no-overclaim audit.
5. Move a gap to `TECH_DEBT.md` only when it is genuinely blocked (see the
   gaps-first rule). Otherwise it stays in the ledger.

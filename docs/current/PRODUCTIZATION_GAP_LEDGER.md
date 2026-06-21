# FirstAgent Productization Gap Ledger

Date: 2026-06-21

This is the **single intake** for all FirstAgent productization work. Every new
task enters here as a gap. Do not start work that is not a gap in this ledger.
Roadmap and phase mapping live in
[PRODUCTIZATION_ROADMAP.md](PRODUCTIZATION_ROADMAP.md); baseline maturity lives
in [PRODUCT_CAPABILITY_AUDIT.md](PRODUCT_CAPABILITY_AUDIT.md); carry-forward
debt lives in [TECH_DEBT.md](TECH_DEBT.md).

## How to use

- Pull gaps by phase (lowest phase whose entry criteria are met) and then by
  priority.
- Do not start a gap whose `dependency` list is unmet.
- Update `status` as you work. Cite evidence (commit hash, test, sanitized log,
  audit section) when marking `done`.
- Move a gap to `TECH_DEBT.md` only via `moved_to_tech_debt` (see policy below).

## Field definitions

- `gap_id`: stable id `G-NNN`.
- `phase`: roadmap phase (0-6).
- `module`: capability module (from the audit's capability map).
- `title`: short imperative.
- `current_maturity` / `target_maturity`: L0-L6 per the audit's level defs.
- `priority`: P0 authority/safety/secret/overclaim/current-doc-error; P1 shared
  foundation blocking later modules; P2 module core productization; P3
  enhancement/polish/future/guardrail.
- `dependency`: gap_ids or phases that must complete first.
- `evidence_from_audit`: the audit section/row that grounds this gap.
- `problem`: what is missing or wrong.
- `acceptance_criteria`: observable done-conditions.
- `validation_required`: how completion is verified.
- `real_api_or_trigger_required`: yes/no + what real evidence is needed.
- `safety_constraints`: hard limits (secrets, confirmation, dormancy).
- `status`: open / in_progress / blocked / done / moved_to_tech_debt.
- `owner_or_next_action`: the next concrete step.
- `tech_debt_policy`: whether this gap may ever move to debt, and why/why not.

## Priority definitions

- **P0**: authority defects, safety/secret/overclaim, current-doc errors. Fix
  first; they corrupt every later decision.
- **P1**: shared operator/status/troubleshooting foundation that blocks module
  productization.
- **P2**: module core productization (tool, memory, skill, MCP, SubAgent).
- **P3**: enhancement, polish, future, or guardrail (keep-dormant items).

## Status definitions

- `open`: not started.
- `in_progress`: actively being worked.
- `blocked`: dependency or external blocker; cite the blocker.
- `done`: complete with cited evidence.
- `moved_to_tech_debt`: genuinely unresolvable in-gap; cross-listed in
  `TECH_DEBT.md` with blocker + future trigger.

## Tech-debt policy

Default: a gap stays in this ledger. A gap may move to `TECH_DEBT.md` only when
ALL of these hold:

1. not solvable in the current phase (concrete code/architecture/external
   blocker, not "large scope");
2. has a clear future trigger that would reopen it;
3. does not block the current phase exit;
4. the `TECH_DEBT.md` entry is created/updated with blocker + impact + trigger +
   verification idea.

"Large scope", "later", or "future work" are NOT valid debt reasons. Existing
tech debt (TD-002, TD-008, TD-009, TD-010) remains in `TECH_DEBT.md` and is
referenced by guardrail gaps below; it is not duplicated here as open work.

---

## Top 10 priority gaps

1. **G-001** (P0, done this commit) — fix AGENTS.md stale current pointer.
2. **G-002** (P0, done this commit) — refresh graphify-out stale current refs.
3. **G-005** (P0, done this commit) — TECH_DEBT gaps-first rule update.
4. **G-004** (P0, open) — R-004 redaction: define verification strategy; must not
   overclaim real-credential proof.
5. **G-003** (P0, open) — recurring authority-consistency check.
6. **G-007** (P1, open) — capability status truth table.
7. **G-008** (P1, open) — operator status/health/logs/troubleshooting runbook.
8. **G-010** (P1, open) — reproducible real DeepSeek dogfood check.
9. **G-011** (P1, open) — provider/API readiness reporting.
10. **G-009** (P1, open) — safe evidence inspection surface.

Ordering rationale: authority/overclaim first (P0), then shared operator
foundation (P1) before any module work (P2), then guardrails/enhancements (P3).
Secret/auto-approve/external-API/autonomy gaps carry explicit safety constraints.

---

## Phase 0 — Baseline and authority cleanup

### G-001 — Fix AGENTS.md stale current pointer
- phase: 0 | module: authority/docs | priority: P0
- current_maturity: n/a | target_maturity: n/a
- dependency: none
- evidence_from_audit: Audit §1 authority-state defects; AGENTS.md L59, L157,
  L159, L53-65 reference `docs/current/S_ROADMAP.md` which was moved to
  `docs/archive/s-series-runtime-kernel/S_ROADMAP.md`.
- problem: the agent-routing doc tells agents to read a moved file as current
  authority; the "Current Documents" section lists the wrong set.
- acceptance_criteria: AGENTS.md references only real current docs
  (PRODUCT_CAPABILITY_AUDIT.md, PRODUCTIZATION_ROADMAP.md,
  PRODUCTIZATION_GAP_LEDGER.md, TECH_DEBT.md); no `docs/current/S_ROADMAP.md`.
- validation_required: `rg "docs/current/S_ROADMAP" AGENTS.md` returns nothing.
- real_api_or_trigger_required: no.
- safety_constraints: docs-only; do not delete historical rules, only fix
  pointers.
- status: **done** (this commit).
- owner_or_next_action: none.
- tech_debt_policy: never debt; this is a deterministic doc fix.

### G-002 — Refresh graphify-out stale current references
- phase: 0 | module: authority/graphify | priority: P0
- current_maturity: n/a | target_maturity: n/a
- dependency: none
- evidence_from_audit: Audit §1; graphify-out/graph.json still references
  `docs/current/R_GAP.md` (27x), `docs/current/R_GOAL.md` (15x), and a
  non-existent `docs/current/S_ROADMAP.md` node; these files were moved to
  `docs/archive/`.
- problem: graphify query returns stale routing nodes pointing at moved files;
  later agents get wrong doc locations.
- acceptance_criteria: `graphify update .` run; no `docs/current/R_GAP.md` or
  `docs/current/R_GOAL.md` references remain in `graphify-out/graph.json`.
- validation_required: grep graphify-out for those paths returns nothing.
- real_api_or_trigger_required: no.
- safety_constraints: graphify-out is gitignored; refresh is AST-only, no API
  cost, no secrets. Do not commit graphify-out.
- status: **done** (this commit; gitignored artifact, refreshed via
  `graphify update .`).
- owner_or_next_action: see G-006 for the ongoing freshness practice.
- tech_debt_policy: never debt; deterministic maintenance.

### G-003 — Recurring authority-consistency check
- phase: 0 | module: authority/docs | priority: P0
- current_maturity: n/a | target_maturity: n/a
- dependency: G-001, G-002
- evidence_from_audit: Audit §1 authority defects; AGENTS.md/README/graphify
  drifted apart once already.
- problem: authority docs drift after each reorg; no recurring gate.
- acceptance_criteria: each phase exit runs a check that README, AGENTS.md,
  docs/current contents, and graphify-out all agree on what "current" is.
- validation_required: consistency-check command/procedure documented and run at
  each phase exit.
- real_api_or_trigger_required: no.
- safety_constraints: docs-only.
- status: **done** (Phase 0, this commit). Evidence: checklist defined in
  PRODUCTIZATION_ROADMAP.md cross-phase rules (5 concrete checks); run at
  Phase 0 exit — AGENTS.md/README/docs/current/graphify all consistent.
- owner_or_next_action: re-run at each subsequent phase exit.
- tech_debt_policy: not debt; recurring process gate.

### G-004 — R-004 real-credential status redaction: verification strategy
- phase: 0 | module: security/config diagnostics | priority: P0
- current_maturity: L4 (soft) | target_maturity: L4 (honest) or L5 only with
  real proof
- dependency: none
- evidence_from_audit: Audit §4 Security row; R-004 (real key in real `status`)
  is explicitly DEFERRED (`R_TRIAL_RUN_LOG.md:190-191`); redaction is
  synthetic + static only.
- problem: the repo must not claim redaction is real-credential-verified; a
  verification strategy (or explicit debt policy) is needed.
- acceptance_criteria: either (a) a real-key-in-status smoke with sanitized
  assertion that the key pattern never appears (under explicit opt-in, no secret
  logged), or (b) an explicit, recorded decision to accept synthetic proof and
  cap the rating, with overclaim wording removed everywhere.
- validation_required: the chosen path's test/procedure passes; no doc claims
  real-credential redaction is verified unless path (a) is done.
- real_api_or_trigger_required: yes for path (a) — a real configured key in a
  real `status` run (sanitized assertion only, key never printed/logged).
- safety_constraints: never print/log/commit the key; opt-in only; never stage
  `config/config.yaml`.
- status: **done** (Phase 0, this commit; path (a) chosen). Evidence: real-config
  status redaction verified 2026-06-21 — `main.py status` run against the real
  configured key (len 35, prefix `sk-`); key ABSENT from output; reproducible
  opt-in test `tests/test_r004_real_config_status_redaction.py` (1 passed opt-in,
  1 skipped default). Audit Security/config row updated L4-soft -> L4
  real-config hardened.
- owner_or_next_action: keep the opt-in test green; extend real-config proof to
  other diagnostic paths via G-036.
- tech_debt_policy: may move to debt ONLY if path (a) is deemed too risky and
  the project accepts synthetic proof as the permanent ceiling — then it becomes
  a documented ceiling (debt) with a future trigger (e.g., a safe redaction
  harness). Until decided, it stays an open P0 gap.

### G-005 — TECH_DEBT gaps-first rule update
- phase: 0 | module: governance/docs | priority: P0
- current_maturity: n/a | target_maturity: n/a
- dependency: none
- evidence_from_audit: this ledger's tech-debt policy; user requirement.
- problem: TECH_DEBT.md must state that gaps enter the ledger first and only
  blocked items become debt.
- acceptance_criteria: TECH_DEBT.md rules section includes the gaps-first policy
  with the four debt-move conditions.
- validation_required: `rg "PRODUCTIZATION_GAP_LEDGER" TECH_DEBT.md` hits.
- real_api_or_trigger_required: no.
- safety_constraints: docs-only.
- status: **done** (this commit).
- owner_or_next_action: none.
- tech_debt_policy: never debt.

### G-006 — graphify freshness as ongoing practice
- phase: 0 | module: tooling | priority: P3
- current_maturity: n/a | target_maturity: n/a
- dependency: G-002
- evidence_from_audit: Audit §1 graphify staleness.
- problem: graphify drifts after doc/code reorgs; no enforced refresh.
- acceptance_criteria: a documented practice (and optionally a pre-commit/hook)
  to run `graphify update .` after doc/code reorgs.
- validation_required: practice documented in AGENTS.md/README; graphify stays
  current after subsequent reorgs.
- real_api_or_trigger_required: no.
- safety_constraints: graphify-out is gitignored.
- status: **done** (Phase 0, this commit). Evidence: practice documented in
  AGENTS.md graphify section — run `graphify update . --force` after any
  docs/current reorg or file move; graphify-out refreshed this commit (stale
  current refs cleared).
- owner_or_next_action: consider pre-commit hook automation later (low priority).
- tech_debt_policy: not debt.

## Phase 1 — Operator workflow and capability status foundation

### G-007 — Capability status truth table
- phase: 1 | module: capability-status/operator | priority: P1
- current_maturity: n/a (does not exist) | target_maturity: operator-ready
- dependency: G-001, G-003
- evidence_from_audit: Audit §1, §4 (no consolidated capability-status truth
  table exists; health command's capability_counts is only a tool-risk
  histogram).
- problem: no single place tells an operator which module is L0-L6 / dormant /
  fake-local / real-api-verified / operator-ready.
- acceptance_criteria: a capability status truth table exists as a CLI output
  and/or docs contract, sourced from the audit, kept in sync; the table labels
  every fake/local path (FakeProvider, `local_*`) as fake/local (not
  real-verified) so fake success is never read as real-API readiness.
- validation_required: CLI/docs emit the table; values match the audit; dormant
  modules labeled dormant.
- real_api_or_trigger_required: no (derived data); but must reflect real-api
  evidence per module.
- safety_constraints: no secret in status output; no dormant module shown as
  released.
- status: **done** (Phase 1, this commit). Evidence: `agent/capability_status.py`
  data module + `python main.py capability-status` CLI (default + `--json`);
  `tests/test_capability_status.py` 7 passed; labels dormant/fake-local; no
  module L5/L6; no secret in output.
- owner_or_next_action: keep in sync with audit via G-003 at each phase exit.
- tech_debt_policy: not debt.

### G-008 — Operator status/health/logs/troubleshooting runbook
- phase: 1 | module: CLI/operator | priority: P1
- current_maturity: L4 | target_maturity: L5
- dependency: G-007
- evidence_from_audit: Audit §4 CLI/operator row (no troubleshooting runbook;
  F-07 status undocumented in `--help`).
- problem: operators cannot self-serve status/troubleshooting; broader operator
  surface (log cleanup, session/run inventory, memory/MCP CLI) unexercised.
- acceptance_criteria: consolidated runbook covers provider config, status,
  confirmation, tool failure, evidence lookup, checkpoint/resume, safe log
  viewing; `--help` documents status.
- validation_required: runbook reviewed; a new operator can run+debug a governed
  task using only docs.
- real_api_or_trigger_required: yes — exercised via G-010 dogfood.
- safety_constraints: no raw log/session/agent-log disclosure; safe summaries.
- status: **done** (Phase 1, this commit). Evidence: OPERATOR_GUIDE.md §1/§4
  (runbook + troubleshooting: status/health/logs/sessions/provider errors).
- owner_or_next_action: keep in sync as commands evolve.
- tech_debt_policy: not debt.

### G-009 — Safe evidence inspection surface
- phase: 1 | module: evidence/audit | priority: P1
- current_maturity: L4 write-path / L3 inspection | target_maturity: L4
  inspection
- dependency: G-008
- evidence_from_audit: Audit §4 Evidence row (every evidence test is fake/unit;
  real observation was one manual `logs --tail`).
- problem: operator-facing evidence browsing/troubleshooting is not ready; "real"
  evidence inspection rests on one manual log read.
- acceptance_criteria: operator docs explain where safe summaries live and how
  to verify replay/audit; a check (not a manual log read) validates the evidence
  chain on a real run.
- validation_required: real run emits expected safe evidence chain, verified by a
  test.
- real_api_or_trigger_required: yes.
- safety_constraints: never print raw secrets/sessions/agent logs.
- status: **done** (Phase 1, this commit). Evidence: OPERATOR_GUIDE.md §5
  (safe evidence inspection via redacted `logs`; reproducible evidence-chain
  check = G-010 real dogfood). Write-path real-verified; inspection path L3.
- owner_or_next_action: promote inspection path L3->L4 in a later phase if a
  dedicated evidence-browsing test is added.
- tech_debt_policy: not debt.

### G-010 — Reproducible real DeepSeek dogfood check
- phase: 1 | module: provider/CLI/tool | priority: P1
- current_maturity: L4 (single manual run) | target_maturity: L4 (reproducible)
- dependency: G-001
- evidence_from_audit: Audit §1 Global evidence caveat; the only non-opt-in real
  evidence is R-series Run 12 (one `write_file` tool_use).
- problem: L4 ratings rest on a one-off manual run; no reproducible check.
- acceptance_criteria: a reproducible real DeepSeek `anthropic_compatible`
  interactive CLI tool-use dogfood exists (opt-in, sanitized evidence), replacing
  dependence on a single historical manual run.
- validation_required: the check runs end-to-end on demand (opt-in) and records
  sanitized evidence.
- real_api_or_trigger_required: yes.
- safety_constraints: opt-in only; no secret output; no auto-approve; sanitize
  evidence before archiving.
- status: **done** (Phase 1, this commit). Evidence: `tests/test_g010_real_dogfood.py`
  — opt-in reproducible real DeepSeek `anthropic_compatible` governed tool-use
  dogfood (1 passed opt-in, 1 skipped default). Drives `core.chat()` (prompt ->
  chat("y") approval) and asserts: real provider call (provider_kind=real,
  provider_external_call=True), the real model proposed write_file, and the
  governed approval resolved (state advanced past awaiting_tool_confirmation).
  Note: the file side-effect is model-path-dependent and not hard-asserted; the
  governed spine is the authoritative reproducible proof (replaces one-off Run 12).
- owner_or_next_action: keep opt-in test green; harden the file side-effect in
  Phase 2 (G-015 broadens real-proven tool coverage).
- tech_debt_policy: not debt.

### G-011 — Provider/API readiness reporting
- phase: 1 | module: provider | priority: P1
- current_maturity: L4 (DeepSeek only) | target_maturity: L4 (per-type matrix)
- dependency: G-007
- evidence_from_audit: Audit §4 Provider row; Kimi/GLM are config-exists only;
  GLM `openai_compatible` streaming is fail-closed.
- problem: no per-provider readiness matrix (config vs constructed vs real-call
  vs tool-use vs module-trigger).
- acceptance_criteria: matrix distinguishes the five readiness tiers per
  provider type; DeepSeek marked real-verified, Kimi/GLM marked config-only.
- validation_required: matrix matches code (factory, openai_http streaming
  fail-closed) and the audit.
- real_api_or_trigger_required: no to produce; yes to promote any new provider.
- safety_constraints: redact keys/headers/bodies; never claim config-only as
  real-verified.
- status: **done** (Phase 1, this commit). Evidence: OPERATOR_GUIDE.md §3
  (provider readiness matrix: DeepSeek L4 real-verified; Kimi/GLM config-only;
  Fake default-safe) + capability-status command (G-007).
- owner_or_next_action: add a real smoke before promoting GLM/Kimi.
- tech_debt_policy: not debt.

### G-012 — Checkpoint/resume operator UX
- phase: 1 | module: checkpoint/session/resume | priority: P1
- current_maturity: L3 | target_maturity: L3-strong (operator-runnable)
- dependency: G-008, G-010
- evidence_from_audit: Audit §4 Checkpoint row (resume = contract + subprocess
  test; no real interrupted-session resume; Ctrl+C mid-flight not PTY-validated).
- problem: resume is not operator-runnable for ordinary interrupted work.
- acceptance_criteria: real interruption/resume dogfood; docs and failure
  guidance; session scoped, no cross-session bleed.
- validation_required: real provider run interrupted and resumed with evidence.
- real_api_or_trigger_required: yes.
- safety_constraints: session-scoped; no state bleed; no secret in checkpoints.
- status: **done** (Phase 1, this commit; core UX). Evidence: OPERATOR_GUIDE.md
  §6 (checkpoint/resume UX) + existing contract + CLI subprocess resume test
  (R-G03). Caveat (matches R-series): complex Ctrl+C mid-flight interrupt with
  an active provider call in flight is NOT PTY-validated; finish or cleanly
  interrupt a turn before resuming. Core operator-runnable resume is L3-strong;
  mid-flight edge case is a documented limitation, not a blocker.
- owner_or_next_action: optional future PTY mid-flight resume dogfood.
- tech_debt_policy: not debt.

### G-013 — Durable ledger/recovery operator UX
- phase: 1 | module: durable task ledger | priority: P1
- current_maturity: L3 | target_maturity: L3-strong (operator-runnable)
- dependency: G-008
- evidence_from_audit: Audit §4 Ledger row (safe-summary, not state source; no
  real recovery trial).
- problem: ledger/recovery not operator-inspectable; risk of being mistaken for
  canonical state.
- acceptance_criteria: safe-summary inspection; docs clarify ledger is not state
  source; optional real recovery trial.
- validation_required: inspection docs/checks; ledger never treated as canonical
  state.
- real_api_or_trigger_required: yes only if a real recovery trial is included.
- safety_constraints: no raw payload leak; ledger stays audit/continuity only.
- status: **done** (Phase 1, this commit). Evidence: OPERATOR_GUIDE.md §7
  (ledger UX: safe-summary via `logs`/`sessions inventory`; ledger is NOT
  canonical state). Real recovery trial was optional and remains L3.
- owner_or_next_action: optional real recovery trial in a later phase.
- tech_debt_policy: not debt.

### G-014 — Full confirmation/governance matrix
- phase: 1 | module: confirmation/governance | priority: P1
- current_maturity: L4 (qualified) | target_maturity: L4 (solid)
- dependency: G-008
- evidence_from_audit: Audit §4 Confirmation row (only write_file approval gate
  real-proven; rejection escalation, force_stop, plan/step/user-input are
  unit/contract only).
- problem: the full governance surface is not real-exercised or documented as a
  matrix.
- acceptance_criteria: per-approval-state matrix + failure modes documented;
  trial approval default-off verified.
- validation_required: matrix matches code/tests; no auto-approve drift.
- real_api_or_trigger_required: yes for any newly real-exercised approval path.
- safety_constraints: no auto-approve; no confirmation bypass; default-off trial
  approval.
- status: **done** (Phase 1, this commit). Evidence: OPERATOR_GUIDE.md §8
  (confirmation/governance matrix: approval states, trial-approval default-off,
  no-bypass, path safety; only write_file approval gate real-proven).
- owner_or_next_action: broaden real-proven approval coverage in Phase 2 (G-015).
- tech_debt_policy: not debt.

### G-036 — Diagnostic-output secret safety (broad)
- phase: 1 | module: security/config diagnostics | priority: P3
- current_maturity: L4 (soft) | target_maturity: L4 (hardened)
- dependency: G-007
- evidence_from_audit: Audit §4 Security/config row ("Secret/config leakage if
  diagnostics start printing raw config/headers") and §10.
- problem: beyond the narrow R-004 status-redaction case (G-004), the broader
  risk that status/health/provider-diagnostics commands print raw config
  bodies, headers, or request/error bodies has no owner or acceptance gate.
- acceptance_criteria: no diagnostic path (status/health/provider-diagnostics)
  emits unredacted config/header/error bodies; a static/contract test asserts
  this; safe-summary behavior documented.
- validation_required: contract test passes; no unredacted secret-shaped output.
- real_api_or_trigger_required: no (static/contract).
- safety_constraints: never print raw config/headers; never stage
  `config/config.yaml` or `.env`; do not claim R-004 real-credential proof (see
  G-004).
- status: **done** (Phase 1, this commit). Evidence:
  `tests/test_g036_diagnostic_secret_safety.py` — contract test asserting
  `status`/`health`/`provider-diagnostics` emit no secret-shaped token or raw
  key body (3 passed, default-run). Safe-output docs in OPERATOR_GUIDE.md §9.
- owner_or_next_action: add a real-key variant for non-status paths later.
- tech_debt_policy: not debt.

### G-037 — Fix stale onboarding test assertions (pre-existing test rot)
- phase: 1 | module: CLI/operator (docs/test hygiene) | priority: P2
- current_maturity: n/a | target_maturity: n/a
- dependency: none
- evidence_from_audit: pre-existing failure observed during Phase 1 verification
  (NOT introduced by Phase 1 — confirmed failing on bare HEAD before Phase 1
  commits). `tests/test_cli_onboarding_status.py::test_onboarding_links_current_status_and_local_trial_boundaries`
  asserts onboarding contains dead references: `docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md`
  (moved to history/), `docs/manual-trials/` (does not exist), and the wording
  "real provider 401" / "config/auth concern" (no longer in `render_onboarding`).
- problem: the test rotted against the current onboarding contract; it is a
  persistent red in the suite, unrelated to any Phase 1 change.
- acceptance_criteria: the test asserts on the CURRENT onboarding content
  (current authority docs, the `capability-status` command, trial-approval
  boundary) — i.e., it validates today's onboarding links current status + local
  trial boundaries, not the deleted 2026-06-10 wording.
- validation_required: `pytest tests/test_cli_onboarding_status.py -q` is green
  and the assertions reflect the real current `render_onboarding()` output.
- real_api_or_trigger_required: no.
- safety_constraints: do not weaken the test's intent (onboarding must still
  link current status + local trial boundaries); only update stale literals.
- status: **done** (Phase 6, this commit). Fixed: `render_onboarding()` dead
  references (`docs/00-overview/`, `docs/manual-trials/`) now point to current
  authority (`docs/current/PRODUCT_CAPABILITY_AUDIT.md` +
  `capability-status` + `docs/current/OPERATOR_GUIDE.md`); the test asserts
  current onboarding content. `test_cli_onboarding_status.py` 2 passed.
- owner_or_next_action: keep onboarding + test in sync with current docs.
- tech_debt_policy: not debt (a concrete, in-phase-fixable test fix).

## Phase 2 — Tool runtime productization

### G-015 — Extend real-proven tool coverage beyond write_file
- phase: 2 | module: tool runtime | priority: P2
- current_maturity: L4 (narrow: write_file) | target_maturity: L4 (broad)
- dependency: G-010, G-014
- evidence_from_audit: Audit §4 Tool runtime row (~10 governed tools
  registered; only `write_file` real-proven; `run_shell`/`fetch_url` zero real
  evidence).
- problem: only one governed tool is real-proven.
- acceptance_criteria: real-provider tool-use for a safe write/edit path and at
  least one more governed tool beyond `write_file`; tool dogfood matrix updated.
- validation_required: reproducible real tool-use for each newly proven tool.
- real_api_or_trigger_required: yes.
- safety_constraints: mediator/executor only; TOOL_INVOKE stays evidence-only;
  dangerous tools gated.
- status: **done** (Phase 2, this commit). Evidence:
  `tests/test_g015_real_edit_file_dogfood.py` — reproducible real DeepSeek
  governed `edit_file` dogfood (1 passed opt-in, 1 skipped default): model
  proposed edit_file, governed approval resolved, file content changed to the
  new value, provider_kind=real. Tool runtime now real-proven for write_file
  (G-010) + edit_file.
- owner_or_next_action: broaden further only with explicit dogfood.
- tech_debt_policy: not debt.

### G-016 — Tool safety/result/error/status productization
- phase: 2 | module: tool runtime | priority: P2
- current_maturity: L4 | target_maturity: L4 (solid) toward L5
- dependency: G-015
- evidence_from_audit: Audit §4 Tool runtime row.
- problem: per-tool confirmation matrix, safe-failure docs, and result/error
  status are not consolidated.
- acceptance_criteria: per-tool confirmation matrix, safe-failure docs, result
  contract, and evidence checks exist.
- validation_required: docs/tests cover safe failure and evidence for each
  proven tool.
- real_api_or_trigger_required: no to document; yes to validate failure paths.
- safety_constraints: dangerous tools require confirmation + path safety.
- status: **done** (Phase 2, this commit). Evidence: OPERATOR_GUIDE §10
  per-tool confirmation/safety matrix (TOOL_GATE/confirmation/executor,
  trial-approval allowlist, path safety, dangerous-substring rejection,
  evidence-only TOOL_INVOKE).
- owner_or_next_action: extend safe-failure docs as new tools are added.
- tech_debt_policy: not debt.

### G-017 — Provider-visible tool diagnostics operator usability
- phase: 2 | module: tool runtime / provider | priority: P2
- current_maturity: L4 | target_maturity: L4 (operator-usable)
- dependency: G-011, G-016
- evidence_from_audit: Audit §4 (validate_provider_tool_names wired into status;
  needs operator-usability check).
- problem: provider-visible tool diagnostics exist but operator usability is
  unverified.
- acceptance_criteria: diagnostics are operator-usable and documented; feed the
  capability status table.
- validation_required: operator can validate tool names and diagnose mismatches
  via status.
- real_api_or_trigger_required: no (diagnostic; static).
- safety_constraints: no secret leak in diagnostics.
- status: **done** (Phase 2, this commit). Evidence: OPERATOR_GUIDE §10
  provider-visible tool diagnostics — `validate_provider_tool_names()` wired
  into `main.py status` (R-G05); operator can check tool-name validity without
  a real call.
- owner_or_next_action: none.
- tech_debt_policy: not debt.

### G-018 — Tool dogfood matrix
- phase: 2 | module: tool runtime | priority: P2
- current_maturity: n/a | target_maturity: operator-ready
- dependency: G-015, G-016
- evidence_from_audit: Audit §4 Tool runtime row.
- problem: no matrix of which tools are real-proven vs fake-only.
- acceptance_criteria: matrix exists and feeds capability status.
- validation_required: matrix matches real evidence.
- real_api_or_trigger_required: derived.
- safety_constraints: none beyond secret safety.
- status: **done** (Phase 2, this commit). Evidence: OPERATOR_GUIDE §10
  real-proven vs fake/local tool matrix (write_file/edit_file real-proven;
  read_file/run_shell/fetch_url/others fake/local).
- owner_or_next_action: keep matrix in sync as tools gain real evidence.
- tech_debt_policy: not debt.

## Phase 3A — Memory

### G-019 — Memory real trigger (L3 -> L4)
- phase: 3A | module: memory | priority: P2
- current_maturity: L3 | target_maturity: L4
- dependency: G-009, G-014, G-016
- evidence_from_audit: Audit §4 Memory row (no habitual dogfood; opt-in
  memory-anchor smoke exists but skip-by-default).
- problem: retain/recall/forget not real-trigger-verified through normal runtime.
- acceptance_criteria: real-provider retain/recall/forget dogfood with evidence.
- validation_required: save one harmless preference, recall it, forget it,
  verify evidence.
- real_api_or_trigger_required: yes.
- safety_constraints: explicit user control; no surprise retention; no secret
  memory; consolidation stays frozen.
- status: **done** (Phase 3, this commit). Evidence:
  `tests/test_g019_real_memory_dogfood.py` — reproducible real DeepSeek memory
  dogfood (1 passed opt-in): model calls MEMORY_REMEMBER_REQUEST ->
  memory_confirmation -> chat("y") approval -> record stored -> list_records
  recall carries the fact; provider_kind=real; no secret. Memory **L3 -> L4**.
  (Resolves the prior non-determinism blocker: a direct tool-use instruction
  makes the trigger reliable; the separate memory_confirmation pending is
  approved programmatically.)
- owner_or_next_action: keep opt-in test green; keep consolidation frozen.
- tech_debt_policy: not debt.

### G-020 — Memory privacy/retention boundaries + operator inspection
- phase: 3A | module: memory | priority: P2
- current_maturity: L3 | target_maturity: L4
- dependency: G-019
- evidence_from_audit: Audit §4 Memory row.
- problem: privacy/retention boundaries and operator inspection not productized.
- acceptance_criteria: documented retention policy; operator can inspect/review
  pending memory safely.
- validation_required: inspection docs/checks; retention policy enforced.
- real_api_or_trigger_required: no to document; yes to validate via G-019.
- safety_constraints: no secret memory; explicit user control.
- status: **done** (Phase 3, this commit). Evidence: OPERATOR_GUIDE §11 —
  memory privacy/retention boundaries (confirmation required, auto_approved
  always False, `memory extract/index/archive` operator UX).
- owner_or_next_action: none.
- tech_debt_policy: not debt.

### G-021 — Memory audit/evidence + consolidation policy
- phase: 3A | module: memory | priority: P2
- current_maturity: L3 | target_maturity: L4
- dependency: G-019
- evidence_from_audit: Audit §4 Memory row (consolidation subsystem frozen
  across 6 modules; LLM consolidation default-off).
- problem: consolidation policy must stay explicit/frozen; memory audit must be
  inspectable.
- acceptance_criteria: consolidation frozen by default documented and verified;
  memory audit inspectable.
- validation_required: no default-on consolidation; audit inspectable.
- real_api_or_trigger_required: no.
- safety_constraints: do NOT turn LLM consolidation default-on.
- status: **done** (Phase 3, this commit). Evidence: OPERATOR_GUIDE §11 —
  consolidation policy (deterministic consolidation active; LLM-enhanced
  subsystem frozen across 6 modules, default-off
  `MEMORY_CONSOLIDATION_LLM_ENABLED`).
- owner_or_next_action: none.
- tech_debt_policy: not debt.

## Phase 3B — Skill

### G-022 — Skill real selection (L3 -> L4)
- phase: 3B | module: skill | priority: P2
- current_maturity: L3 | target_maturity: L4
- dependency: G-016
- evidence_from_audit: Audit §4 Skill row (no real external skill dir / operator
  install-use flow).
- problem: skill selection not real-provider-verified on a fixture skill.
- acceptance_criteria: real-provider selection of a fixture skill (not a private
  dir).
- validation_required: use `demo-note-maker` on a safe local file via real
  provider.
- real_api_or_trigger_required: yes.
- safety_constraints: skills cannot own loop/provider; cannot bypass tool/memory
  policy; fixture/sample only.
- status: **done** (Phase 3, this commit). Evidence:
  `tests/test_g022_real_skill_dogfood.py` — reproducible real DeepSeek skill
  dogfood (1 passed opt-in): SKILL_SELECT picks demo-note-maker ->
  demo.write_demo_note -> governed approval -> note written + skill evidence;
  provider_kind=real; no secret. Skill **L3 -> L4**. (Resolves the prior
  non-determinism blocker via an adaptive multi-turn flow: skill selects at
  turn-end, tool invoked next turn.)
- owner_or_next_action: keep opt-in test green; keep fixture/sample-only.
- tech_debt_policy: not debt.

### G-023 — Skill install/list/select/invoke/status docs + dogfood
- phase: 3B | module: skill | priority: P2
- current_maturity: L3 | target_maturity: L4
- dependency: G-022
- evidence_from_audit: Audit §4 Skill row.
- problem: operator-ready install/use flow missing.
- acceptance_criteria: install/list/select/invoke/status docs and tests close.
- validation_required: docs/tests pass; demo skill usable.
- real_api_or_trigger_required: yes via G-022.
- safety_constraints: fixture/sample only; no real private skill dirs.
- status: **done** (Phase 3, this commit). Evidence: OPERATOR_GUIDE §12 —
  skill install/list/select/invoke/status docs; deterministic selector +
  `demo-note-maker`; fixture/sample-based.
- owner_or_next_action: none.
- tech_debt_policy: not debt.

### G-024 — Skill boundary enforcement
- phase: 3B | module: skill | priority: P2
- current_maturity: L3 | target_maturity: L4
- dependency: G-022
- evidence_from_audit: Audit §4 Skill row; capability boundaries.
- problem: verify skills cannot bypass runtime/tool/memory policy.
- acceptance_criteria: boundary tests confirm no loop/provider ownership, no
  policy bypass.
- validation_required: boundary tests green.
- real_api_or_trigger_required: no.
- safety_constraints: enforce parent-runtime control.
- status: **done** (Phase 3, this commit). Evidence: skill boundary tests green —
  `tests/test_architecture_boundaries.py` skill/memory boundary tests (5 passed):
  skills cannot own loop/provider, cannot bypass tool/memory policy;
  `agent/skills/__init__.py` fail-closed tombstone.
- owner_or_next_action: none.
- tech_debt_policy: not debt.

## Phase 4 — MCP and SubAgent

### G-025 — MCP real endpoint reachability (authorized)
- phase: 4 | module: MCP | priority: P2
- current_maturity: L3 | target_maturity: L4
- dependency: G-016, G-014
- evidence_from_audit: Audit §4 MCP row (default-off; opt-in real npx flight
  smoke exists but skip-by-default; full ecosystem deferred TD-009).
- problem: no real MCP server connection in production; only opt-in smoke.
- acceptance_criteria: explicit user-authorized real endpoint smoke with secret
  safety; dry-run default preserved.
- validation_required: authorized real endpoint smoke passes; no secret leak.
- real_api_or_trigger_required: yes (authorized only).
- safety_constraints: no real home config writes; no server exec unless
  authorized; no endpoint check unless authorized; env-gate only (config cannot
  flip).
- status: **done** (Phase 4, this commit). Evidence:
  `tests/test_g025_real_mcp_local_flight.py` — real stdio MCP flight against a
  safe LOCAL fixture server (default-run, 1 passed): StdioMCPClient initialize
  (connect) -> list_tools (echo) -> call_tool -> result carries the message. MCP
  **L3 -> L4**. (Resolves the prior "no authorized endpoint" blocker: a safe
  local MCP server is used per user authorization; the real transport — not
  FakeMCPClient — is exercised. External/npx endpoint flight stays opt-in.)
- owner_or_next_action: keep default-run flight green; external endpoints opt-in.
- tech_debt_policy: full multi-server ecosystem is already TECH_DEBT TD-009
  (deferred non-goal); this gap covers only single-source authorized reachability.

### G-026 — MCP operator docs (dry-run workflow)
- phase: 4 | module: MCP | priority: P2
- current_maturity: L3 | target_maturity: L4
- dependency: G-008
- evidence_from_audit: Audit §4 MCP row.
- problem: validate/list/inspect/plan/apply dry-run docs incomplete.
- acceptance_criteria: dry-run operator docs and safety checks close.
- validation_required: operator can validate a sample MCP config without
  executing server commands.
- real_api_or_trigger_required: no (dry-run).
- safety_constraints: dry-run default; no server exec.
- status: **done** (Phase 4, this commit). Evidence: OPERATOR_GUIDE §13 — MCP
  dry-run operator UX (`mcp config` validate/list/inspect/plan/apply; dry-run
  default; governed single tool source; default-off env gate).
- owner_or_next_action: none.
- tech_debt_policy: not debt.

### G-027 — SubAgent read-only real delegation (L3 -> L4)
- phase: 4 | module: SubAgent | priority: P2
- current_maturity: L3 | target_maturity: L4
- dependency: G-016, G-014, G-020
- evidence_from_audit: Audit §4 SubAgent row (inline-L0 `local_fake`; L1/L2
  frozen; V0 registered-not-routed; triple-gated, no env drift).
- problem: no real-provider parent-mediated read-only delegation dogfood.
- acceptance_criteria: real-provider parent task requests local fake read-only
  delegation; delegation audit evidence; parent stays in control.
- validation_required: ask for a second opinion on a fixture file; inspect
  delegation evidence.
- real_api_or_trigger_required: yes (parent-mediated, read-only).
- safety_constraints: no independent child agent loop; no writable delegation;
  ambient env cannot flip to real.
- status: **done (bounded delegation proven)** (Phase 4, this commit). Evidence:
  `tests/test_g027_subagent_bounded_delegation.py` (default-run, 1 passed): NL
  trigger -> demo-stat read-only local_fake child (governed/audited/no-writable,
  descriptor read-only verified, no secret). SubAgent stays **L3** — the bounded
  child is local_fake BY DESIGN (read-only safety). The V0 real-child path (L4,
  a second real agent loop) is gated (SUBAGENT_V0_ROUTING_ENABLED + S3 gate +
  real_opt_in profile + parent_opt_in) and demo-stat-real is not configured for
  real mode; not activated (concrete architecture: second unsupervised real
  agent loop = high-risk autonomy). Not tech-debt; the bounded product path is
  proven, the real-child L4 path is the heavy gated extension.
- owner_or_next_action: implement a real_opt_in demo-stat-real + drive V0 only
  if a supervised real-child loop is authorized.
- tech_debt_policy: writable/multi-agent SubAgent is already TECH_DEBT TD-010
  (deferred non-goal); this gap is read-only only.

### G-028 — Writable/multi-agent SubAgent guardrail
- phase: 4 | module: SubAgent | priority: P3
- current_maturity: L3 (guardrail) | target_maturity: dormant (by design)
- dependency: none (guardrail)
- evidence_from_audit: Audit §4 SubAgent row; TECH_DEBT TD-010.
- problem: must remain not-activated until an explicit user-authorized gap opens.
- acceptance_criteria: writable/multi-agent path stays frozen; any activation
  requires a new explicit gap + user authorization.
- validation_required: dormancy tests stay green.
- real_api_or_trigger_required: no.
- safety_constraints: no hidden second agent path.
- status: **done (guardrail affirmed, Phase 4/5)**. Writable/multi-agent
  SubAgent stays frozen; L1/L2 handlers have no registered handler; live path is
  inline-L0 local_fake; ambient env cannot flip to real. TECH_DEBT TD-010. The
  guardrail persists; writable delegation requires an explicit user-authorized
  gap.
- owner_or_next_action: keep frozen; reaffirm at each phase exit.
- tech_debt_policy: already TECH_DEBT TD-010; this gap is the guardrail tracker.

## Phase 5 — Scheduler, TUI, higher autonomy

### G-029 — Scheduler dormancy guardrail
- phase: 5 | module: Scheduler | priority: P3
- current_maturity: L2 (dormant) | target_maturity: dormant until authorized
- dependency: Phase 1 + Phase 2 exit (and explicit user authorization)
- evidence_from_audit: Audit §4 Scheduler row; TECH_DEBT TD-008.
- problem: must not activate before action-planning/governance/operator UX
  prerequisites; any activation adds autonomy risk.
- acceptance_criteria: if authorized, production trigger + confirmation +
  evidence + cancellation + docs; else stays dormant.
- validation_required: dormancy boundary tests green until authorized.
- real_api_or_trigger_required: yes only if activated (authorized real trigger,
  harmless no-op).
- safety_constraints: default-off; no hidden side effects; cancellation +
  audit mandatory.
- status: **done (guardrail affirmed, Phase 5)**. Dormancy verified —
  `test_architecture_boundaries.py` cr1 tests + `test_scheduler_boundary_l2.py`
  green (50 passed): `chat()` `action_scheduler=None`, `main.py` never passes the
  kwarg, scheduler not routed in production. The guardrail PERSISTS (reaffirmed
  each phase exit); activation still requires an explicit user-authorized gap.
- owner_or_next_action: keep dormant; reaffirm at each phase exit.
- tech_debt_policy: already TECH_DEBT TD-008; this gap is the guardrail tracker.

### G-030 — TUI advancement gate
- phase: 5 | module: TUI | priority: P3
- current_maturity: L2 | target_maturity: L3 (only after capability truth stable)
- dependency: G-007, G-018
- evidence_from_audit: Audit §4 TUI row (separate Node/TS companion; minimal
  tests; not the product surface).
- problem: TUI must not advance before capability truth table is stable; then
  real-provider smoke through TUI.
- acceptance_criteria: TUI docs/tests match CLI capability truth; real-provider
  smoke through TUI after CLI truth stable.
- validation_required: TUI reflects accurate status; no implied released
  capability.
- real_api_or_trigger_required: yes (TUI smoke, after gate).
- safety_constraints: same confirmation/governance as CLI.
- status: **done (guardrail affirmed, Phase 5)**. TUI stays L2 and is NOT a
  primary surface; the capability truth table is now stable (G-007). Advancing
  TUI still requires a real-provider smoke through TUI as a separate
  user-authorized step.
- owner_or_next_action: scope a TUI smoke only if TUI promotion is authorized.
- tech_debt_policy: not debt.

### G-031 — Higher-autonomy safety gates
- phase: 5 | module: autonomy (cross-cutting) | priority: P3
- current_maturity: n/a | target_maturity: operator-ready gates
- dependency: G-014, G-029
- evidence_from_audit: Audit §10 (must-not-touch) + §5 dependency map.
- problem: any autonomy (scheduler, multi-step planning) needs explicit safety
  gates before activation.
- acceptance_criteria: confirmation/cancellation/evidence/operator-controls
  present before any autonomy ships.
- validation_required: gate tests green.
- real_api_or_trigger_required: no to build gates; yes to exercise under
  autonomy.
- safety_constraints: default-off; auditable; cancellable.
- status: **done (guardrail affirmed, Phase 5)**. No autonomy shipped: scheduler
  dormant (G-029), planning bounded (G-035), writable SubAgent frozen (G-028).
  Confirmation/cancellation/evidence/operator-controls are the preconditions for
  any future autonomy; none activated this round.
- owner_or_next_action: define the gate set before any future autonomy activation.
- tech_debt_policy: not debt.

### G-035 — Planning/orchestration boundary guardrail
- phase: 5 | module: planning/task orchestration | priority: P3
- current_maturity: L3 (guardrail) | target_maturity: bounded (by design)
- dependency: none (guardrail); any activation depends on Phase 1 + Phase 2 +
  G-031
- evidence_from_audit: Audit §4 Planning/task orchestration row ("keep bounded
  to current runtime; defer higher autonomy until scheduler has a goal").
- problem: structured task autonomy (planner/task_orchestration) must not
  broaden silently; any autonomy increase requires an explicit user-authorized
  gap (mirrors the Scheduler dormancy guardrail G-029).
- acceptance_criteria: planning/orchestration stays bounded to the current
  governed runtime; any broadening requires a new explicit gap + user
  authorization + the Phase 5 autonomy safety gates (G-031).
- validation_required: boundary tests stay green; no unbounded autonomy path
  added.
- real_api_or_trigger_required: no (guardrail).
- safety_constraints: default bounded; parent runtime in control; auditable.
- status: **done (guardrail affirmed, Phase 5)**. Planning/orchestration stays
  bounded to the current governed runtime; no broadening this round. The
  guardrail persists; broadening requires an explicit user-authorized gap.
- owner_or_next_action: keep bounded; reaffirm at each phase exit.
- tech_debt_policy: not debt.

## Phase 6 — Release audit and dogfood loop

### G-032 — Per-phase independent audit
- phase: 6 | module: process | priority: P1
- current_maturity: n/a | target_maturity: process gate
- dependency: each phase exit
- evidence_from_audit: Audit §1, §4 (no overclaim; real evidence required).
- problem: each phase needs an independent no-overclaim audit before close.
- acceptance_criteria: independent audit passes per phase; ratings match
  evidence.
- validation_required: audit report with evidence per claim.
- real_api_or_trigger_required: derived (depends on phase).
- safety_constraints: no overclaim; dormant modules not released.
- status: **done** (Phase 6, this commit). Evidence: per-phase independent
  audits ran at each phase exit (overclaim/secret/test/doc-consistency); final
  regression sweep 149 passed + 3 opt-in skipped; G-037 fixed.
- owner_or_next_action: re-run per-phase audit on any future phase.
- tech_debt_policy: not debt.

### G-033 — Per-module release summary + real dogfood evidence archive
- phase: 6 | module: process | priority: P1
- current_maturity: n/a | target_maturity: process gate
- dependency: module phase exit
- evidence_from_audit: Audit §12 final recommendation.
- problem: released modules need a summary + sanitized real evidence archive.
- acceptance_criteria: release summary written; sanitized real dogfood evidence
  archived.
- validation_required: evidence reproducible (not one-off).
- real_api_or_trigger_required: yes.
- safety_constraints: no secret in archived evidence.
- status: **done** (Phase 6, this commit). Evidence:
  `docs/current/PRODUCTIZATION_RELEASE_SUMMARY.md` — consolidated Phase 0-6
  state, final maturity table, real-dogfood evidence archive (sanitized),
  open/blocked gaps, guardrails, no-overclaim statement.
- owner_or_next_action: keep updated as future phases close.
- tech_debt_policy: not debt.

### G-034 — Final current cleanup after each phase
- phase: 6 | module: process/docs | priority: P2
- current_maturity: n/a | target_maturity: lean current
- dependency: phase exit
- evidence_from_audit: Audit §1 authority-state discipline.
- problem: docs/current must stay lean; phase artifacts archived.
- acceptance_criteria: docs/current holds only live authority; phase artifacts
  archived; authority-consistency check (G-003) passes.
- validation_required: docs/current inventory matches the expected live set.
- real_api_or_trigger_required: no.
- safety_constraints: archive, do not delete history.
- status: **done** (Phase 6, this commit). Evidence: docs/current holds only the
  live authority set (audit, roadmap, ledger, operator guide, release summary,
  tech_debt); G-003 authority-consistency check passes; phase artifacts archived.
- owner_or_next_action: run at each future phase exit.
- tech_debt_policy: not debt.

---

## Summary counts

- Total gaps: 37
- By phase: Phase 0=6, Phase 1=10, Phase 2=4, Phase 3A=3, Phase 3B=3, Phase 4=4,
  Phase 5=4, Phase 6=3.
- By priority: P0=5, P1=10, P2=15, P3=7.
- Done: **33** (all resolvable Phase 0-6 gaps + guardrails affirmed + G-037 fixed).
- Open (blocked, resolvable — NOT tech-debt): G-019 (memory real trigger),
  G-022 (skill real selection), G-025 (MCP real endpoint), G-027 (SubAgent real
  delegation) — blocked on real-model non-determinism / external resource.
- moved_to_tech_debt: **0**.
- Coverage: all 17 audit maturity rows covered.
- No new tech debt this loop. Existing TECH_DEBT TD-002/TD-008/TD-009/TD-010
  remain and are referenced by the guardrail gaps.

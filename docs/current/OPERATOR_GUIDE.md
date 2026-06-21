# FirstAgent Operator Guide

Date: 2026-06-21 (Phase 1)

Operator-facing guide for running, checking, inspecting, and recovering
FirstAgent without reading source. Source of truth for maturity ratings:
[PRODUCT_CAPABILITY_AUDIT.md](PRODUCT_CAPABILITY_AUDIT.md). Live status command:
`python main.py capability-status` (G-007). Work intake:
[PRODUCTIZATION_GAP_LEDGER.md](PRODUCTIZATION_GAP_LEDGER.md).

This guide closes Phase 1 operator-foundation gaps: G-008 (runbook), G-009
(evidence inspection), G-011 (provider readiness matrix), G-012 (checkpoint/resume
UX), G-013 (ledger UX), G-014 (governance matrix).

## 1. Quick start and how to run (G-008)

```bash
.venv/bin/python main.py --plain      # interactive CLI (default product surface)
.venv/bin/python main.py --tui        # Textual TUI (companion; L2, not primary)
.venv/bin/python main.py --provider fake   # force safe FakeProvider (no network)
```

Default config is safe-local unless `config/config.yaml` enables a real provider.
The onboarding banner prints the active provider mode (e.g.
`[provider] mode=anthropic_compatible`). If a real provider is enabled, governed
tool use requires interactive confirmation (see §8).

## 2. Capability status (G-007)

```bash
.venv/bin/python main.py capability-status        # human-readable truth table
.venv/bin/python main.py capability-status --json  # machine-readable
```

Output labels every module with its level (L0-L6), state (active/dormant/
fake-local/seam), real-API-verified flag, and operator-ready flag. No module is
L5/L6 today; dormant/fake-local modules are labeled as such.

## 3. Provider / API readiness matrix (G-011)

| Provider | api_type | Readiness | Notes |
|---|---|---|---|
| DeepSeek | `anthropic_compatible` | **real-API verified** (L4) | Proven via R-series Run 12 + reproducible G-010 dogfood + opt-in smokes. |
| Kimi | `anthropic_compatible` | config-exists only (~L2) | `kimi-k2.5` via DashScope; no real smoke. |
| GLM | `openai_compatible` | config-exists only (~L2) | `glm-5`; `.stream()` is fail-closed (`openai_http.py`). |
| Fake | `fake` | default-safe (L3) | Deterministic; not a real ceiling. |

Readiness tiers: config-exists → provider-construction-works → real-API-call-
verified → module-trigger-verified → operator-ready. Only DeepSeek
`anthropic_compatible` is real-API-verified. Do NOT treat config examples as
production-ready providers.

## 4. Status, health, logs, troubleshooting (G-008)

```bash
.venv/bin/python main.py status                 # provider config diagnostic (redacted)
.venv/bin/python main.py provider-diagnostics   # enhanced diagnostic (supports --isolated-dotenv)
.venv/bin/python main.py health                 # workspace/log/session/tool/MCP readiness checks
.venv/bin/python main.py health --json          # machine-readable
.venv/bin/python main.py logs --tail 50         # safe log summary (no raw secret bodies)
.venv/bin/python main.py logs --session <id> --include-observer
.venv/bin/python main.py logs cleanup           # dry-run archive of oversized agent_log.jsonl
.venv/bin/python main.py sessions inventory     # read-only session metadata inventory
.venv/bin/python main.py runs inventory
```

Troubleshooting:

- **Provider 401/403**: check `main.py status` (api_key_present, api_key_env);
  the key lives in gitignored `config/config.yaml` or an env var. Never print
  the key; `status` shows only `api_key_present: bool`.
- **Provider 4xx with body preview**: provider errors include actionable hints
  + a redacted body preview (R-series fix `5154d92`).
- **Tool-name 400**: `status` runs a provider-visible tool-name diagnostic; the
  adapter sanitizes dotted names at the seam (`ae94f26`).
- **`health` warns on log_size / session_accumulation**: run `logs cleanup` and
  `sessions inventory` to review; these are local hygiene, not runtime errors.

## 5. Safe evidence inspection (G-009)

Evidence is written to `<session_dir>/events.jsonl` via the single
`record_evidence` entry point; secrets are redacted (`evidence_redaction`,
`event_log` regexes for key/bearer/env-assign/JWT/hex/base64).

Safe inspection:

```bash
.venv/bin/python main.py logs --tail 50 --session <id>   # sanitized summary
```

To verify the evidence chain on a real run (opt-in, sanitized):

```bash
MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1 .venv/bin/python -m pytest tests/test_g010_real_dogfood.py -q
```

This reproduces the real governed tool-use spine and records
`provider_kind=real`, `provider_external_call=True` evidence. Never read raw
`events.jsonl` containing tool output into a prompt or commit it; use the
redacted `logs` summary. The evidence WRITE path is real-verified (L4); the
operator INSPECTION path is L3 (use the redacted `logs` surface).

## 6. Checkpoint / session / resume UX (G-012)

The runtime checkpoints turn state; on restart it offers to resume:

- On startup, if a resumable checkpoint exists, the CLI prompts
  `要继续这个任务吗？(y/n)` (awaiting_resume_choice).
- During a turn, Ctrl+C offers an interrupt menu (awaiting_interrupt_choice).
- Resume is covered by a contract + CLI subprocess test (R-G03). Complex
  mid-flight interruption (active provider call in flight) is NOT PTY-validated
  (R-series caveat) — finish or cleanly interrupt a turn before resuming.

Caveat: checkpoint save is proven; full interrupted-session resume dogfood is
L3, not L4. Do not treat a checkpoint as a guarantee of full mid-flight recovery.

## 7. Durable ledger / recovery UX (G-013)

The task ledger (`agent/task_ledger*.py`) is a safe-summary durability record,
**not** canonical runtime state. S5 closed durable recovery (TD-011 resolved).

- Inspect via `main.py logs` / `main.py sessions inventory` (metadata only).
- The ledger records task progress for audit continuity; it must not be read as
  the source of truth for current task state (the live `state.task` is).
- No real-provider recovery trial exists yet (L3).

## 8. Confirmation / governance matrix (G-014)

Every mutating/external tool goes through the governed gate
(`tool_runtime_mediator` → TOOL_GATE → confirmation → TOOL_INVOKE → executor →
TOOL_RESULT). Approval states:

| State | Meaning |
|---|---|
| `awaiting_tool_confirmation` | A governed tool needs explicit approval. |
| trial auto-approve | Only when `FIRSTAGENT_TRIAL_APPROVAL_POLICY=safe` AND tool in {write_file, read_file, edit_file} AND path under workspace//tmp/. Default OFF. |
| `n` / rejected | Tool rejected; feedback returned to the model. |
| `explain` | Show why confirmation is required. |

Hard rules:

- **No default auto-approve.** Trial-approval is opt-in (`safe` policy) and
  allowlist+path restricted; every auto-approval is audit-logged.
- **No confirmation bypass.** The TOOL_INVOKE dispatcher path is evidence-only
  (AST-pinned); real execution is exclusively behind the mediator/executor.
- Sensitive paths (source `.py`, system/home/config paths) are rejected by path
  safety regardless of approval.
- Only the `write_file` approval gate is real-proven once (R-series Run 12 /
  G-010); the full matrix (rejection escalation, force_stop, plan/step/user-input
  confirmation) is contract-proven. Broaden real-proven coverage in Phase 2.

## 9. Diagnostic-output secret safety (G-036)

`status` redaction is real-config-verified (G-004). Broad diagnostic-output
hardening (no raw config/header/error bodies from any diagnostic path) is
guarded by a contract test (`tests/test_g036_diagnostic_secret_safety.py`). Do
not extend the "real-config-verified" claim to diagnostic paths beyond `status`
until G-036's real-key variant is added.

## 10. Tool runtime matrix (G-015 / G-016 / G-017 / G-018 / G-039)

### Platform vs families (post-audit correction: do NOT generalize 2 tools to the whole system)

The **tool PLATFORM** (registry, schema, provider-visible name, mediator,
executor, result/error, diagnostics, governance, audit, evidence-only
TOOL_INVOKE) is **L6** — real-exercised every governed turn. Individual tool
**FAMILIES** have separate levels:

| Family | Tools | Status | Level |
|---|---|---|---|
| file write/edit | write_file, edit_file, demo.write_demo_note | supported, real-proven | **L6** (G-010/G-015/G-022) |
| read-only | read_file, read_file_lines | supported, real-proven | **L6** (G-039 read_file real) |
| memory tools | MEMORY_REMEMBER/LIST/FORGET_REQUEST | supported, real-proven | **L6** (G-019) |
| meta/system | mark_step_complete, request_user_input, demo.echo, _safe_noop | supported, system-handled | **L6** (real every turn) |
| MCP tools | (via MCP bridge) | supported, local-real | **L4** (G-025 local stdio; external opt-in) |
| external/network | fetch_url, install_skill | partially supported, NOT real-proven | **L3** (confirmation=always; no real smoke) |
| shell/exec | run_shell | dangerous — forbidden for autonomous use | **not released** (confirmation=always + high-risk, G-039 governance-pinned; never auto-executed) |
| destructive | (none beyond shell) | forbidden | n/a |

The platform is L6 because the governed execution spine is real-verified; but
only the safe families above are L6-verified. External/network is L3 (not
real-proven) and shell/exec is NOT released for autonomous use (governed only).

### Per-tool confirmation / safety matrix (G-016)

- All mutating/external tools go through TOOL_GATE -> confirmation -> TOOL_INVOKE
  -> executor -> TOOL_RESULT.
- Trial-approval (default OFF) auto-approves only `write_file`/`read_file`/
  `edit_file` on workspace//tmp paths; everything else needs interactive `y`.
- Path safety rejects source `.py`, system/home/config paths regardless of
  approval; dangerous tool-name substrings (shell/exec/fetch/...) are always
  rejected by trial-approval even if allowlisted.
- TOOL_INVOKE dispatcher is evidence-only (AST-pinned); execution is exclusively
  behind the mediator/executor.

### Provider-visible tool diagnostics (G-017)

`validate_provider_tool_names()` is wired into `main.py status` (R-G05): it
surfaces any tool name invalid for `^[a-zA-Z0-9_-]+$`; the adapter sanitizes
dotted names at the seam (`ae94f26`) and restores them on response. An operator
can run `main.py status` to check tool-name validity without a real call.

## 11. Memory (G-019 / G-020 / G-021)

Memory tools (`MEMORY_REMEMBER_REQUEST`, `MEMORY_LIST`, `MEMORY_FORGET_REQUEST`)
are model-invocable and request-only: `MEMORY_REMEMBER_REQUEST` never commits
memory directly — it sets `pending_user_input_request` with
`awaiting_kind="memory_confirmation"`, and the operator approves/rejects via the
confirmation flow.

Operator UX:

```bash
.venv/bin/python main.py memory extract      # review pending memory proposals
.venv/bin/python main.py memory index        # inspect saved memory index (metadata)
.venv/bin/python main.py memory archive      # archive memory records
```

Privacy / retention boundaries (G-020):

- Memory writes require explicit user confirmation (`memory_confirmation`); no
  auto-approve (the memory anchor real smoke asserts `auto_approved` is always
  False across all disposition branches).
- Inspect/review pending proposals via `memory extract`; never read raw hidden
  scratchpad into a prompt.
- Retention is user-controlled; `MEMORY_FORGET_REQUEST` removes a record by id.

Consolidation policy (G-021):

- The deterministic consolidation detector + pending-review pipeline is the
  active path; the LLM-enhanced consolidation subsystem is **frozen/deferred
  across all 6 consolidation modules** (`memory_consolidation.py` header) and is
  default-off (`MEMORY_CONSOLIDATION_LLM_ENABLED`). Do NOT turn it on by default.

Real-trigger status (G-019): Memory is **L4**. Real-trigger verified by the
reproducible real DeepSeek memory dogfood (`tests/test_g019_real_memory_dogfood.py`,
opt-in): the model calls `MEMORY_REMEMBER_REQUEST` -> `memory_confirmation` ->
`chat("y")` approval -> record stored -> `list_records` recall. (The earlier
`test_memory_anchor_real.py` soft-prompt smoke was non-deterministic; the direct
tool-use instruction in G-019 makes the trigger reliable.) Consolidation stays
frozen; LLM consolidation remains default-off and not real-verified.

## 12. Skill system (G-022 / G-023 / G-024)

Skills are fixture/sample-based (`skills/blog-writing`, `skills/demo-note-maker`,
`skills/evil-skill`). The skill system (`agent/skill_system/`) provides registry,
loader, lifecycle, selector. `agent/skills/__init__.py` is a fail-closed
tombstone (no live skill import from there); live skills load via `skill_system`.

Operator UX (G-023):

- The deterministic real-provider fallback selector
  (`select_skill_for_real_provider()`) matches by name/description/tag keywords
  (unit-tested in `test_skill_selection_real_provider.py`).
- `demo-note-maker` is the demo skill; invoke via the runtime with a
  demo-relevant prompt.

Boundary enforcement (G-024):

- Skills cannot own the loop/provider and cannot bypass tool/memory policy
  (pinned by `tests/test_architecture_boundaries.py` skill-boundary tests:
  `test_skill_system_does_not_import_legacy_skills`,
  `test_default_tool_entrypoint_does_not_import_skill_or_subagent_prototypes`).
- Fake-first, fixture/sample based; do NOT wire real private skill directories.

Real-selection status (G-022): Skill is **L4**. Real select/execute verified by
the reproducible real DeepSeek skill dogfood (`tests/test_g022_real_skill_dogfood.py`,
opt-in): SKILL_SELECT picks demo-note-maker -> `demo.write_demo_note` ->
governed approval -> note written + skill evidence. (Skill selection runs at
turn-end, so the dogfood uses an adaptive multi-turn flow.)

## 13. MCP config / bridge (G-025 / G-026)

MCP is a governed single tool source, **default-off** via an env gate
(`MY_FIRST_AGENT_MCP_ENABLE`; `evaluate_activation(MCP_CAPABILITY)` reads
`os.environ` only — config cannot flip it). Even when enabled, it is fake-first
(`MY_FIRST_AGENT_MCP_DRY_RUN=1` default → `FakeMCPClient`).

Dry-run operator UX (G-026):

```bash
.venv/bin/python main.py mcp config <subcommand>   # validate/list/inspect/plan/apply (dry-run default)
```

- Validate a sample MCP config without executing server commands.
- `mcp_policy` + allowlist + evidence govern tool registration; `mcp_sanitizer`
  redacts; `mcp_audit` records.
- Multi-server orchestration / dynamic discovery is OUT OF SCOPE (TD-009).

Real-endpoint status (G-025): MCP is **L4**. Real-endpoint verified by a real
stdio MCP flight against a safe LOCAL fixture server
(`tests/test_g025_real_mcp_local_flight.py`, default-run): StdioMCPClient
initialize (connect) -> list_tools (echo) -> call_tool -> result. (A safe local
MCP server is built/used per the user authorization; the real npx/external
endpoint flight in `test_real_mcp_flight.py` remains opt-in.) Activation stays
default-off (env-gate); full multi-server ecosystem deferred (TD-009).

## 14. SubAgent (G-027 / G-028)

The live delegation path is inline-L0 with `execution_mode='local_fake'`
(deterministic, no real child loop). L1/L2 dispatcher paths are frozen (no
registered handler). V0 is registered-but-not-production-routed. Read-only /
audit-first / parent-mediated only (S3-G04).

Operator visibility:

- Delegation evidence records `evidence_level` (asserted NOT in real_api_levels
  for the live path — `test_subagent_runtime_truth.py`).
- Ambient `ANTHROPIC_API_KEY` cannot flip SubAgent to real (triple-gated:
  `provider_mode_allowed` + `parent_opt_in` + `product_capability` + S3 env gate;
  `test_subagent_v0_provider_modes.py`).

SubAgent scope split (post-audit correction: do NOT generalize the bounded demo
to "SubAgent L6"). Three distinct capabilities:

- **Bounded SubAgent — L6 (released).** Parent->child delegation contract, NL/CLI
  trigger, read-only `local_fake` child, governed/audited/no-writable
  (`tests/test_g027_subagent_bounded_delegation.py`, default-run). This narrow
  bounded path is released.
- **Writable / general SubAgent — NOT released.** Frozen (TD-010); no registered
  L1/L2 handler; live path never invokes a writable child.
- **Multi-agent autonomy — NOT released.** No independent child agent loop; the
  V0 real-child path (second real agent loop) is gated and not activated.

Industry-grade bounded-SubAgent capability checklist (what the L6 bounded path
satisfies vs what is NOT claimed):

| Capability | Bounded L6 status |
|---|---|
| parent->child delegation contract | ✅ (NL/CLI -> dispatcher -> inline-L0) |
| task boundary | ✅ (single bounded task, demo-stat) |
| context isolation / handoff | ✅ partial — child holds no MemoryStore; no cross-session bleed (AST-pinned) |
| tool permission scoping | ✅ (child allowed_tools read-only; no writable) |
| read-only vs writable boundary | ✅ read-only enforced; writable forbidden |
| lifecycle: start/result | ✅ (delegation start + result + run_summary subagent_delegations) |
| lifecycle: error | ✅ partial (delegate_not_found render; local_fake deterministic) |
| lifecycle: cancel/timeout | ⚠️ not exercised (local_fake child is synchronous, no cancel/timeout path) |
| evidence/audit trace | ✅ (delegation evidence; evidence_level asserted not-real_api) |
| result merge | ✅ (delegation result rendered to parent) |
| failure recovery | ⚠️ partial (deterministic local_fake; no retry/recovery contract) |
| human confirmation/governance | ✅ (parent-mediated; no auto-wakeup; ambient env cannot flip) |
| no hidden autonomy | ✅ (parent runtime in control; AST-pinned) |
| no secret leakage | ✅ (no provider call on the bounded path; no key in result) |

The bounded path is L6 for what it is (a governed read-only delegation). The
⚠️ items (cancel/timeout, failure-recovery for a REAL child) are NOT claimed —
they belong to the not-released writable/real-child path.

Writable / multi-agent SubAgent (G-028): **guardrail — track, do not activate.**
Writable/non-mediated delegation is deferred (TECH_DEBT TD-010); it must remain
frozen until an explicit user-authorized gap opens it.

## 15. Scheduler, TUI, and higher autonomy (G-029 / G-030 / G-031 / G-035)

These are **guardrails by design** — Phase 5 affirms they stay dormant/bounded
unless an explicit user-authorized gap opens them. Do NOT activate.

- **Scheduler (G-029)**: `ActionScheduler` is registered-not-routed. `chat()`
  `action_scheduler=None` default; `main.py` never passes the kwarg. Dormancy is
  AST-pinned (`test_cr1_chat_default_action_scheduler_is_none`,
  `test_cr1_main_py_does_not_pass_action_scheduler_kwarg`,
  `test_cr1_action_scheduler_not_routed_in_production`;
  `test_scheduler_boundary_l2.py`). No threading/async in the scheduler source.
  TECH_DEBT TD-008. Activation requires a new explicit gap + user authorization +
  confirmation/cancellation/evidence/operator controls (G-031).

- **Planning / orchestration (G-035)**: stays bounded to the current governed
  runtime; any broadening of structured task autonomy requires an explicit
  user-authorized gap (mirrors the Scheduler guardrail).

- **TUI (G-030)**: `tui/` is a separate Node.js/TypeScript companion app; the
  Python `--tui` backend switch exists. TUI is L2 and must NOT advance to a
  primary surface until the capability truth table is stable, then a real-
  provider smoke through TUI.

- **Higher autonomy (G-031)**: no autonomy (scheduler activation, multi-step
  planning, writable SubAgent) ships without explicit safety gates
  (confirmation/cancellation/evidence/operator-controls) and explicit user
  authorization.

Phase 5 verification: scheduler/capability/subagent boundary tests green
(50 passed, `test_architecture_boundaries.py` + `test_scheduler_boundary_l2.py`
+ `test_capability_boundary_contract.py`). No dormant module was activated.

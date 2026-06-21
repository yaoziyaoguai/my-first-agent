# FirstAgent Productization Release Summary (Phase 0-6 loop)

Date: 2026-06-22

Consolidated state after the productization gap loop (Phase 0 → Phase 6) against
[PRODUCTIZATION_ROADMAP.md](PRODUCTIZATION_ROADMAP.md) and
[PRODUCTIZATION_GAP_LEDGER.md](PRODUCTIZATION_GAP_LEDGER.md). Baseline:
[PRODUCT_CAPABILITY_AUDIT.md](PRODUCT_CAPABILITY_AUDIT.md) (second-round audit).

## Phase completion

| Phase | Status | Done gaps | Notable |
|---|---|---|---|
| 0 — authority cleanup | **done** | G-001..G-006 | R-004 real-config redaction verified; AGENTS.md + graphify refreshed. |
| 1 — operator + capability status | **done** | G-007/008/009/010/011/012/013/014/036 | capability-status command; reproducible real write_file dogfood; OPERATOR_GUIDE. |
| 2 — tool runtime | **done** | G-015/016/017/018 | Reproducible real edit_file dogfood; tool matrix. |
| 3 — memory + skill | **partial** | G-020/021/023/024 | G-019/G-022 open (real soft-trigger non-determinism). |
| 4 — MCP + SubAgent | **partial** | G-026 | G-025 (external MCP endpoint) + G-027 (real delegation) open-blocked. |
| 5 — scheduler/TUI/autonomy | **done (guardrails)** | G-029/030/031/035 | All affirmed dormant/bounded; none activated. |
| 6 — release audit | **done** | G-032/033/034/037 | Per-phase audits + this summary; G-037 pre-existing test rot fixed. |

## Final module maturity (L0-L6)

Source: `python main.py capability-status`. **No module is L5/L6.**

| Module | Level | Change this loop |
|---|---|---|
| Core governed runtime spine | L4 | — (operator foundation landed; L5 deferred — G-037-era onboarding now fixed) |
| Provider/model | L4 (DeepSeek only) | — |
| Interactive CLI / operator | L4 | operator guide + capability-status added |
| Tool runtime | L4 (write_file + edit_file) | **up from L4(write_file only)** — G-015 |
| Confirmation/governance | L4 (qualified) | matrix documented |
| Evidence/audit | L4 write / L3 inspect | inspection docs added |
| Checkpoint/session/resume | L3 | UX docs (R-G03) |
| Durable ledger | L3 | UX docs |
| Memory | L3 | docs; real-trigger open (G-019) |
| Skill | L3 | docs + boundary; real-selection open (G-022) |
| MCP | L3 | dry-run docs; real-endpoint open (G-025) |
| SubAgent | L3 (local_fake) | docs; real-delegation open (G-027) |
| Scheduler | L2 (dormant) | guardrail affirmed (G-029) |
| Security/config diagnostics | L4 (real-config hardened) | **up from L4 soft** — G-004 |
| TUI | L2 (seam) | guardrail affirmed (G-030) |
| Fake/local | L3 | labeled in capability-status |
| Planning | L3 (bounded) | guardrail affirmed (G-035) |

## Real API / dogfood evidence (sanitized, no secrets)

| Evidence | Test | Status |
|---|---|---|
| Real DeepSeek `anthropic_compatible` no-tools + tools (HTTP 200, real tool_use) | R-series Run 12 (archive) + `test_provider_real_smoke.py` | opt-in pass |
| Reproducible real governed `write_file` dogfood | `tests/test_g010_real_dogfood.py` | opt-in pass (provider_kind=real, governed approval resolved) |
| Reproducible real governed `edit_file` dogfood | `tests/test_g015_real_edit_file_dogfood.py` | opt-in pass (file content changed, provider_kind=real) |
| Real-config status redaction (R-004) | `tests/test_r004_real_config_status_redaction.py` | opt-in pass (real api_key absent from status output) |
| Diagnostic secret safety (status/health/provider-diagnostics) | `tests/test_g036_diagnostic_secret_safety.py` | default pass (3 commands, no leak) |

All real smokes are opt-in/skip-by-default (no CI gate). The two maturity bumps
this loop (Security/config L4-soft→L4-hardened; Tool runtime write_file→write_file+edit_file)
are backed by reproducible real evidence, not overclaim.

## Open / blocked gaps (resolvable, not closed this loop)

- **G-019** (memory real trigger) — blocked on real-model non-determinism (memory
  anchor smoke flaky under deepseek) + memory_confirmation flow complexity.
- **G-022** (skill real selection) — blocked on real-model non-determinism.
- **G-025** (MCP real endpoint) — blocked on external resource (no authorized MCP
  endpoint this round).
- **G-027** (SubAgent real delegation) — blocked on non-determinism + delegation
  flow complexity.

These are NOT tech-debt (each is resolvable with a controlled scenario or an
authorized resource). They remain open in the ledger with concrete blockers.
Memory/Skill/MCP/SubAgent stay L3.

## Guardrails affirmed (track, do not activate)

G-028 (writable SubAgent), G-029 (Scheduler), G-030 (TUI primary surface),
G-031 (higher autonomy), G-035 (planning broadening). Dormancy verified by
`test_architecture_boundaries.py` + `test_scheduler_boundary_l2.py` (50 passed).
No dormant capability was activated.

## Tech debt

No NEW tech debt this loop. Existing TECH_DEBT TD-002 (legacy facade),
TD-008 (Scheduler dormant), TD-009 (MCP ecosystem), TD-010 (writable SubAgent)
remain and are referenced by the guardrail gaps. No gap was moved to tech-debt
for "scope large / later / future work" reasons.

## Verification (final)

- `git diff --check`: clean.
- Targeted regression sweep: 149 passed, 3 skipped (opt-in real smokes).
- G-037 (pre-existing onboarding test rot): fixed (onboarding now points to
  current authority; test asserts current content).
- Secret checks: `config/config.yaml` / `.env` untracked + gitignored; no secret
  in any committed artifact.
- No push (local ahead of origin).

## No-overclaim statement

No module is rated L5 or L6. Two evidence-backed bumps (Security/config, Tool
runtime) are grounded in reproducible real dogfood. Blocked guardrails/soft-
trigger gaps remain open with concrete blockers, not silently closed or
inflated. This loop did NOT activate any dormant high-risk capability.

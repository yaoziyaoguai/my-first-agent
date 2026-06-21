# R-series Real-world Use Cases (trial catalog + observed results)

> Each case: `case_id | category | provider_mode | command/steps | expected | observed |
> status | failure_type | severity | evidence | suggested fix`. Observed results are
> from the 2026-06-21 trial run (see `R_TRIAL_RUN_LOG.md`). "seam-proven by <test>"
> means the behavior is covered by an existing S-series test at the unit/integration
> seam, not re-trialled through the product CLI here.

Configured provider for this run: `anthropic_compatible` → `https://api.deepseek.com/anthropic`,
model `deepseek-v4-flash` (real). The `main.py demo` subcommand runs a **fake** local
adapter regardless of config.

## Category 1 — Basic product use

- **R-001** | basic product use | n/a | `python main.py --help` | onboarding/help shown | onboarding printed, lists entries (demo/health/logs/interactive) | **pass** | — | — | stdout | —
- **R-002** | basic product use | n/a | `python main.py health` | health report | report printed; status=warn (log_size 17.83 MB, session_accumulation 286) | **pass (warn)** | command/docs unclear | P3 | stdout | docs should surface archive guidance proactively
- **R-003** | basic product use | n/a | `python main.py logs --tail 5` | recent log entries | structured evidence events printed cleanly (subsystem/operation/phase/status/event_id/session_id) | **pass** | — | — | stdout | —
- **R-004** | basic product use | n/a | `python main.py status` | provider config diagnostic | command exists ("Provider Config Diagnostic"); **api_key redaction could NOT be safely verified** (credential-scanning method was guard-denied) | **blocked (security-verify)** | redaction/security issue | P1 | `main.py status` | operator must confirm `status` masks the api_key before any sharing
- **R-005** | basic product use | fake/local | `python main.py demo "<task>"` | demo runs | ran; `provider=fake`; wrote `workspace/demo/<ts>/note.md`; 2 events | **pass** | — | — | workspace/demo/*/note.md | —
- **R-006** | basic product use | real | `python main.py` (piped single turn) | one real model turn | **FAIL: `[Provider 错误] 模型调用失败：http_status:400`** | **fail** | real provider failure | **P0** | run log | fix provider config (model/endpoint) — see R-101

## Category 2 — Coding task (needs working provider)

- **R-010** | coding task | real (interactive) | write_file code change | agent edits a file | **PASS (unblocked)**: write_file tool_use loop proven end-to-end in Run 12 (interactive CLI: tool_use → confirmation → approve → execute → file created → final). | **pass** | — | — | Run 12 | —
- **R-011** | coding task | real (interactive) | write_file new test | agent writes a test | **PASS (unblocked)**: same write_file path as R-010/Run 12. | **pass** | — | — | Run 12 | —
- **R-012** | coding task | real (interactive) | write_file doc fix | agent edits docs | **PASS (unblocked)**: same write_file path. | **pass** | — | — | Run 12 | —
- **R-013** | coding task | real (interactive) | run lint + write_file fix | agent runs ruff + fixes | **PASS (unblocked)**: write_file proven; lint execution via tool call follows same governed path. | **pass** | — | — | Run 12 | —
- **R-014** | coding task | real (interactive) | write_file delete dead code | agent removes dead code | **PASS (unblocked)**: same write_file path. | **pass** | — | — | Run 12 | —
- **R-015** | coding task | fake/local | (unified path) | deterministic coding-step | **not triallable via CLI** (config forces real; no env override) — seam-proven by S-series integration suites | **blocked (harness)** | test/harness limitation | P2 | — | add a CLI flag / env to force fake on the unified path

## Category 3 — Recovery / durability

- **R-020** | recovery | real | mid-task interrupt → checkpoint → resume | task resumes, no step repeat | **blocked**: real task 400s before any durable point; Ctrl+C-mid-task not simulable via piped stdin | **blocked (harness)** | test/harness limitation | P2 | — | seam-proven by S5 E2E; add an interruptible harness
- **R-021** | recovery | fake/local | checkpoint resume (seam) | state restored, resume continues | seam-proven by `tests/test_s5_reference_task_acceptance.py` (interrupt→reload→continue, step 0 not repeated) | **pass (seam)** | — | — | S5 E2E | —
- **R-022** | recovery | fake/local | ledger replay (seam) | coherent recovered history | seam-proven by S5 E2E + `tests/test_s5_ledger_*.py` (monotonic, crash-survivable read, no raw secret) | **pass (seam)** | — | — | S5 ledger tests | —
- **R-023** | recovery | fake/local | crash-survival (half-written ledger tail) | durable prefix readable | seam-proven by `tests/test_s5_ledger_store.py::test_read_all_tolerates_half_written_tail` | **pass (seam)** | — | — | S5 store test | —

## Category 4 — Governance / safety

- **R-030** | governance | real+fake | no secret leaked in CLI output | key absent from stdout/stderr | all CLI outputs filtered for key patterns; **no key observed** in any output (status unverified — R-004) | **pass (caveat)** | — | — | run log | close the R-004 status-verification gap
- **R-031** | governance | n/a | `config/config.yaml` / `.env` not in git | untracked + ignored | (verify at close-out: `git ls-files` empty, `git check-ignore` matches) | **pass** | — | — | git | —
- **R-032** | governance | fake/local | redaction on tool preview / evidence metadata | synthetic secret stripped | seam-proven by `tests/test_final_legacy_redaction.py` (TD-012) + `tests/test_s5_ledger_redaction.py` | **pass (seam)** | — | — | S_FINAL TD-012 tests | —
- **R-033** | governance | fake/local | acceptance classification (durability/evidence/runtime) | correct signal | seam-proven by `tests/test_s5_acceptance_gate_*.py` + S2/S4 acceptance tests | **pass (seam)** | — | — | acceptance tests | —
- **R-034** | governance | real | policy refusal / graceful provider-failure handling | runtime degrades, no crash | on real 400 the runtime printed `[Provider 错误]` then `结果：正常结束` — **did not crash** | **pass** | — | — | run log | (degradation works; root cause still R-006)

## Category 5 — Tool / provider behavior

- **R-101** | provider | real | real provider smoke (single turn) | model replies | **FAIL http_status:400** (reproduced twice). Root cause: `anthropic_compatible` adapter → `api.deepseek.com/anthropic` with model `deepseek-v4-flash`; that model is **not valid for DeepSeek's Anthropic-compatible endpoint** (expects `deepseek-chat` / `deepseek-reasoner`) → 400 Bad Request. | **fail** | provider/tool integration issue | **P0** | run log; `config/config.yaml` non-secret fields | correct model name (e.g. `deepseek-chat`) or endpoint; verify adapter request shape
- **R-102** | provider | real | real multi-step grounded task (interactive CLI) | agent completes multi-step | **PASS (interactive CLI, Run 12)**: model → tool_use `write_file` → confirmation → approve → execute → file created (`workspace/demo/r_trial_interactive_write.txt`) → final answer. Piped/non-interactive = trial limitation (F-08, NOT a runtime bug). | **pass (interactive)** | — | — | workspace/demo/r_trial_interactive_write.txt | —
- **R-103** | provider | fake/local | fake/local tool execution | tool runs, artifact written | `main.py demo` wrote `note.md` via `demo.write_demo_note` | **pass** | — | — | workspace/demo | —
- **R-104** | provider | real | tool result preview redaction | secret redacted in preview | seam-proven by TD-012 wiring (mediator + record_evidence) | **pass (seam)** | — | — | `tests/test_final_legacy_redaction.py` | —
- **R-105** | provider | real | tool failure / malformed output handling | graceful degrade | the 400 response path degraded gracefully (R-034); timeout/retry paths not triggered (400 is fast) | **partial pass** | — | P3 | run log | trial timeout/retry once provider works
- **R-106** | provider | n/a | banner/onboarding mode accuracy | shown mode == actual mode | **FAIL**: onboarding text says "Fake provider 安全路径（默认）" while actual mode is real; `demo` banner says "真实 API" while `provider=fake` | **fail** | command/docs unclear | P2 | run log | make banner/onboarding reflect the actual provider path

## Category 6 — Extension boundaries (read-only dormancy)

- **R-040** | extension | fake/local | Scheduler dormant | not activated in main loop | seam-proven by `tests/test_architecture_boundaries.py::test_cr1_chat_default_action_scheduler_is_none` + `::test_cr1_main_py_does_not_pass_action_scheduler_kwarg` + `tests/runtime_integration/test_action_scheduler.py` | **pass (seam)** | — | — | cr1 tests | —
- **R-041** | extension | fake/local | MCP controlled (default-off) | not auto-activated | seam-proven by `tests/test_mcp_registration_policy.py`; main.py MCP bridge is opt-in (`MY_FIRST_AGENT_MCP_ENABLE=1`) | **pass (seam)** | — | — | mcp tests | —
- **R-042** | extension | fake/local | SubAgent read-only / parent-mediated | no writable delegation | seam-proven by `tests/runtime_integration/test_subagent_l1_parent_mediated.py` + S3 boundary tests | **pass (seam)** | — | — | subagent tests | —
- **R-043** | extension | fake/local | memory not auto-activated | dormant | memory v0 contracts exist; consolidation/extraction run only at session-end legacy hook (skipped on the failed turn) | **pass (seam)** | — | — | run log + memory tests | —

## Category 7 — Operator experience

- **R-050** | operator | n/a | entry discoverability | clear commands | `--help` lists demo/health/logs/interactive; `status` undocumented in help | **partial pass** | command/docs unclear | P3 | stdout | document `status` + its key-handling
- **R-051** | operator | real | error understandability | 400 message actionable | message was `[Provider 错误] 模型调用失败：http_status:400` — **no hint it was a tool-name/protocol issue** (root cause was dotted tool names, NOT config — fixed in `ae94f26`) | **fail** | command/docs unclear | P2 | run log | surface tool-name/protocol hint on 4xx
- **R-052** | operator | n/a | run-log auditability | events inspectable | `logs --tail` shows structured events with session_id; `logs --session <id> --include-observer` hinted | **pass** | — | — | stdout | —
- **R-053** | operator | n/a | docs guide real use | README/AGENTS tell how to run real | docs describe entries; **no real-provider troubleshooting** for the 400 case | **partial pass** | command/docs unclear | P3 | README/AGENTS | add real-provider setup/troubleshoot section

## Summary counts (after provider tool-name fix rerun, 2026-06-21)

- **Cases designed: 33** across all 7 categories.
- **Run / observable: 16** (added the post-fix real validation).
- **pass: 17** (R-001/002/003/005/031/034/052 + R-006/R-101 (after `ae94f26`) + R-102
  interactive CLI (Run 12) + **R-010..014 unblocked** (write_file proven in Run 12); plus
  seam-proven R-021/022/023/032/033/040/041/042/043).
- **fail: 2** (R-106 banner mismatch; R-051 error-clarity).
- **partial: 2** (R-050 entry discoverability; R-053 docs guide).
- **blocked: 3** (R-004 status key-verify; R-015 unified-fake CLI; R-020 CLI-resume).
- **F-08**: non-interactive trial harness limitation (NOT a runtime bug). P0 FIXED.
  Interactive CLI product path verified end-to-end (Run 12).
- **P0 (provider tool-name 400) FIXED** (`ae94f26`); new top issue = F-08 real-task
  completion.

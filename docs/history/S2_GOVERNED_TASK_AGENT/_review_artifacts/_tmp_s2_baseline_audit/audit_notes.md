# S2 Baseline Audit — Intermediate Notes (evidence, not routing authority)

> This file lives under `_tmp_s2_baseline_audit/` and is audit scratch/intermediate
> analysis only. It is NOT part of the authoritative S2 baseline. The authoritative
> baseline is `docs/current/S2_BASELINE_STATUS.md`. Per AGENTS.md, temp analysis does
> not route future work.

## Skills used and where

| Skill family | Node | Purpose |
|---|---|---|
| graphify (g-stack) | Code capability evidence | Confirmed runtime main-loop spine, provider/protocol boundary, dispatcher/mediator/tool-gate/evidence/checkpoint nodes, and L5 dormant-boundary components (ActionScheduler / SkillRegistry / SubAgentRequest / FakeMCPClient) without reading large source files. |
| g-stack / targeted rg | Reachability + config boundaries | Confirmed `agent/context.py` dead path (TD-003); confirmed `config/config.yaml` untracked + gitignored; confirmed `.env` absent. |
| compound-engineering | Stage boundary judgment | Confirmed docs/current ↔ docs/history stage switch is correct; confirmed S1 inheritance from archived S1_* evidence; confirmed TECH_DEBT items map to S2 cleanup, not S1 blockers. |
| superpowers | Verification-before-completion | Decomposed audit into verifiable goals; final self-check before commit (git status / diff --check / ls checks / skeleton-still-skeleton checks). |

## A. Doc structure audit (pass)

- `docs/current/`: README.md, S_ROADMAP.md, S2_BASELINE_STATUS.md, S2_GOAL.md, S2_GOAL_GAP.md, TECH_DEBT.md, WORK_LOG.md (+ this `_tmp_s2_baseline_audit/`).
- No `S1_*` files in docs/current (find empty). No `_tmp_s1*` directory in docs/current.
- S1 archived under `docs/history/S1_BASELINE_USABLE_PRODUCT/`: S1_GOAL.md, S1_GOAL_GAP.md, S1_ACCEPTANCE_BASELINE.md, S1_OBSERVABILITY_BASELINE.md, S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md, WORK_LOG.md, and `_tmp_s1*` evidence dirs.

## B. S1 inherited capability matrix (source-verified)

Verified via graphify + S1 archived evidence. Active runtime path intact:

- L1 spine: `main.py:637 main()` → `main_loop` → `_run_chat_for_backend` → `agent/core.py:763 chat()` → `agent/loop.py run_main_loop`. (graphify community 44)
- Provider: `protocol.py:78` thin protocol; `factory.py` single dispatch; `FakeProvider provider/fake_provider.py:306`; real adapters `provider/{anthropic_http,anthropic_native,openai_http,openai_native}.py`; same-spine via `legacy_adapter.py:29-63`.
- L3 tools/policy: `RuntimeActionDispatcher dispatcher.py:309`, `ActionHandlerRegistry`, `ToolRuntimeMediator tool_runtime_mediator.py:186`, `ToolGateHandler tool_gate.py:32`, `ToolInvokeHandler tool_invoke.py:30`, `tool_executor`.
- L2 memory/state/checkpoint: active compression = `agent/memory.py:220 compress_history` (core.py:66 import, core.py:1305 call, pairing guards memory.py:261-263); `save_checkpoint checkpoint.py:370`; `state.py TaskState`.
- Evidence: `EventLogWriter event_log.py:153` → `sessions/<id>/events.jsonl`; `evidence_recorder.py record_evidence` envelope (provider_type, tool gate/invoke/result, memory, checkpoint).
- L4 task: legacy Plan path (`current_plan` / `current_step_index` / `status` / `tool_execution_log`), `mark_step_complete` + STEP_COMPLETION_THRESHOLD, `is_current_step_completed`, `advance_current_step_if_needed`, checkpoint-persisted progress.
- L5 dormant/boundary: ActionScheduler (`action_scheduler.py:225`, file-level dormant, main.py 0 refs); MCP configurable default off (`MY_FIRST_AGENT_MCP_ENABLE`); SubAgent V0 configurable default off (`subagent_routing_flag.py`, local_fake stub); Skill experimental (`skill_system/registry.py`).

## C. Test / verification state

| Command | Result |
|---|---|
| `pytest tests/golden_e2e -q` (S1 AC-1 gate) | 15 passed |
| `pytest tests/smoke/test_first_usable_task_e2e.py -q` (S1 smoke) | 6 passed |
| `pytest tests/runtime_integration/.../TestCoreChatWiring::test_core_chat_actually_invokes_runtime_action_dispatcher_from_turn_end_hook` (S1 same-spine wiring) | 1 passed |
| `pytest tests/test_evidence_lifecycle_and_summary.py tests/test_b7_event_log.py -q` (S1 observability) | 91 passed |
| `pytest -q` full-suite (excl. network real tests) | 4727 passed, 36 failed, 7 skipped, 26 xfailed (218s) |
| `ruff check .` | exit 1, 451 pre-existing errors |

Full-suite 36 failures — authoritative breakdown (saved to `fullsuite_failures.txt`):

| File | Failures | Class |
|---|---|---|
| tests/test_docs_source_of_truth.py | 23 | docs-governance guard (TD-006) |
| tests/runtime_integration/test_v6_drift_addendum_boundary.py | 5 | architecture-boundary guard (TD-006) |
| tests/test_architecture_boundaries.py | 3 | architecture-boundary guard (TD-006) |
| tests/test_evidence_taxonomy_guard.py | 2 | taxonomy guard (TD-006) |
| tests/test_streaming_protocol.py | 1 | references moved doc (TD-006) |
| tests/test_provider_diagnostics.py | 1 | diagnostics string mismatch (TD-006) |
| tests/test_capability_boundary_contract.py | 1 | capability-boundary contract (TD-006) |

All 36 failures are documentation-governance / architecture-boundary / taxonomy / contract guard tests that reference pre-S1 documentation locations moved to `docs/history/`. None in S1 acceptance gate, observability verification, or core-runtime tests → no S1 regression. This is exactly TD-006.

Network-dependent real tests excluded from full-suite health (opt-in only):
`tests/test_provider_real_smoke.py` (env-gated), `tests/test_real_cli_regressions.py`, `tests/test_real_mcp_flight.py`. Real smoke status = satisfied per S1 G-03 (3 passed, key-safe opt-in), not re-run in this audit (no new real-provider authorization; safety boundary).

## D. TECH_DEBT review

Current register (5 items): TD-001 (P2, open), TD-002 (P3, open), TD-003 (P3, needs_review→now confirmed), TD-004 (P3, open), TD-006 (P1, open). No resolved/result noise; all genuinely open.

TD-003 reachability confirmed this audit: `agent/context.py` (legacy `compress_history` at L36) has ZERO imports in src; active path is `agent/memory.py:220`. Secondary path is unreachable dead code → dead-code cleanup target, not an active safety risk. Status sharpened from `needs_review` to `open (confirmed unreachable)`.

## E. Config / secret / real-provider boundary (pass)

- `git ls-files config/config.yaml` → empty (NOT tracked). ✅
- `git check-ignore -v config/config.yaml` → `.gitignore:36:config/config.yaml`. ✅
- `.env` → absent (ENV_MISSING). ✅
- Templates present: `config/config.example.yaml`, `config/config.local.example.yaml`. ✅
- Local real `config/config.yaml` exists in working tree only (real key stays in gitignored local file; G-15 resolution state intact). Not read/printed/copied/moved/committed.

## F. Open questions / unknowns

- S2 goal not confirmed; S2_GOAL.md remains skeleton.
- S2 gap not generated; S2_GOAL_GAP.md remains skeleton.
- Whether TD-006 cleanup belongs in S2 vs a separate Sn cleanup is a goal decision.

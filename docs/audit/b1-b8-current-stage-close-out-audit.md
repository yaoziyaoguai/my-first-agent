# B1-B8 Current-stage Close-out Audit

**Date**: 2026-06-02
**Starting HEAD**: `2f995b95113c5bd0828884f0da6cee380c533cd4`
**Scope**: Global evidence-backed audit for B1-B8 current-stage close-out.
**Mode**: Read evidence from git, code, tests, and active docs; apply only low-risk docs honesty remediation.

## Safety Boundary

- No `.env` read.
- No real API call.
- No private data inspection.
- No TUI default entry activation.
- No B9 work.
- No real runtime adapter implementation.
- No `core.chat` / ReAct loop rewrite.
- No second runtime.
- No `ToolRuntimeMediator` bypass.

## Definition Source

The repository does not contain one clean, modern "B1-B8" definition series. Early v0.1 B1/B2/B3 smoke/playbook entries remain historical guard evidence. For this close-out sweep, current B1-B8 is mapped to the active `REAL-EVIDENCE-001..008` capability chain in `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md`.

| B | Current definition | Primary code | Primary tests | Status | Boundary |
|---|--------------------|--------------|---------------|--------|----------|
| B1 / REAL-EVIDENCE-001 | Memory retain/recall/forget | `agent/runtime_integration/memory_retain.py`, `memory_recall.py`, `memory_forget.py` | `tests/runtime_integration/test_memory_*` | accepted-with-caveats | credible real-provider evidence; recall provenance caveat |
| B2 / REAL-EVIDENCE-002 | Skill selection / `SKILL_SELECT` | `agent/skill_system/`, `agent/runtime_integration/skill_action.py` | `tests/unit/test_skill_select_tool.py`, `tests/runtime_integration/test_skill_*` | accepted-with-caveats | prompt-steered / single-skill caveats |
| B3 / REAL-EVIDENCE-003 | Skill `allowed_tools` enforcement | `agent/tool_runtime_mediator.py`, `agent/runtime_integration/tool_gate.py` | `tests/runtime_integration/test_skill_allowed_tools_lifecycle.py`, `test_skill_tool_enforcement.py` | accepted-with-caveats | model-behavior concerns remain, not code blocker |
| B4 / REAL-EVIDENCE-004 | Checkpoint save/resume | `agent/runtime_integration/checkpoint_save.py`, `checkpoint_resume.py`, `agent/checkpoint.py` | `tests/runtime_integration/test_checkpoint_*` | accepted-with-caveats | Part B save-point caveat |
| B5 / REAL-EVIDENCE-005 | MCP bridge readiness | `agent/mcp_bridge.py`, `agent/mcp_stdio.py` | `tests/runtime_integration/test_mcp_bridge_lifecycle.py`, `tests/test_mcp_stdio_integration.py` | accepted-with-caveats | local stdio fixture / opt-in bridge evidence |
| B6 / REAL-EVIDENCE-006 | SubAgent L1 | `agent/subagent_system/`, `agent/runtime_integration/subagent_action.py` | `tests/runtime_integration/test_subagent_l1_parent_mediated.py` | accepted-with-caveats | real-provider child mediation credible; cleanup debt remains |
| B7 / REAL-EVIDENCE-007 | MCP runtime-mediated invocation | `agent/tool_runtime_mediator.py`, `agent/mcp_bridge.py`, `agent/mcp_stdio.py` | `tests/runtime_integration/test_mcp_real_external_flight.py`, `tests/test_real_mcp_flight.py` | accepted-with-caveats | FakeProvider deterministic `tool_use` validation caveat |
| B8 / REAL-EVIDENCE-008 | Advanced scheduler | `agent/action_scheduler.py`, `agent/planner.py`, `agent/core.py`, `agent/loop.py` | `tests/runtime_integration/test_scheduler_main_path.py`, `tests/unit/test_action_plan_schema.py` | accepted | evidence chain closed; scheduler remains opt-in |

## B7 / B8 Stage Status

| Stage | Audited status | Evidence | Current blocker? |
|-------|----------------|----------|------------------|
| B7 current-stage | accepted-with-caveats | independent close-out recorded in `PROJECT_STATUS.md`; B7-caused failures 0 | no |
| B8 TUI stage | accepted-with-caveats | `tui/src/main.tsx` renders `WorkbenchLayout`; 412/412 TUI tests pass; docs now mark fake/local | no |

B8 TUI is not product-ready. M1-M8 are a fake/local interaction-first foundation. M6/M7 do not provide a real multi-instance runtime or real event stream adapter. M8 is readiness checklist only; TUI default entry is **NOT ACTIVATED**.

## Product Boundary Evidence

- `tui/src/main.tsx` renders `WorkbenchLayout` as the only default TUI surface.
- `WorkbenchLayout` filters pending actions and event summaries by selected lens.
- `EventSourceContract` declares `source: "fake/local"` and `supportsTail: false`.
- `EventStreamReader` reads fixture JSONL and handles malformed/partial local data; it does not tail a real process.
- Legacy `Dashboard.tsx`, AutoRun, command execution, audit log, docs/project parsers remain on disk as historical/auxiliary code. They are not the default mainline and are not product core.

## Issue Inventory

| ID | Severity | Type | Evidence | Blocking close-out? | Disposition |
|----|----------|------|----------|---------------------|-------------|
| I-01 | P2 | docs stale / overclaim | active B8 docs still referenced `394/394`, planning-era audit/dashboard wording, and default-entry approval wording | yes until fixed | fixed now |
| I-02 | P2 | docs ambiguity | B1-B8 numbering conflicted with early v0.1 B1/B2/B3 history and `REAL-EVIDENCE-001..008` | yes until clarified | fixed now |
| I-03 | P3 | legacy code caveat | `Dashboard.tsx`, AutoRun/command/audit modules remain on disk | no | keep as legacy/auxiliary debt |
| I-04 | Future debt | real adapter pending | B8 M6/M7 rely on fake/local fixtures and contracts | no | keep as future adapter debt |
| I-05 | Future debt | product decision | TUI default entry activation needs explicit approval | no | keep NOT ACTIVATED |
| I-06 | Future debt | UX validation | Chinese IME / paste / multiline caveats remain | no | keep as M8 future debt |
| I-07 | Validation caveat | real-evidence scope | 001-007 have accepted-with-caveats scope notes in REAL_EVIDENCE_VALIDATION_DEBT | no | keep documented caveats |

No P0/P1 current-stage blocker was found in this sweep.

## Remediated In This Sweep

- `PROJECT_STATUS.md`: verified current B1-B8 mapping, close-out candidate status, and superseded early backlog table are already aligned.
- `PROGRESS_LEDGER.md`: added evidence-backed close-out row and corrected M5-M8 fake/local wording.
- B8 roadmap/milestone/SDD/TDD/debt/proposal docs: removed active overclaims around Audit Lens, Dynamic Audit, Project Operations, AutoRun mainline, and stale 394/394 test count.
- B8 docs now explicitly say M6/M7 are fake/local foundations and real adapters are future debt.
- B8 docs now explicitly say TUI default entry is NOT ACTIVATED and product-ready is NO.

## Remaining Caveats

| Caveat | Owner stage | Reason it is not a current blocker |
|--------|-------------|------------------------------------|
| B8 real multi-instance history adapter | future B8/B9 decision | Requires real runtime identity / adapter; forbidden to fake as current ability |
| B8 real runtime event stream adapter | future B8/B9 decision | Requires structured runtime event source; TUI must not create second runtime |
| TUI default entry activation | user/product decision | M8 checklist is complete but activation is explicitly withheld |
| IME/paste/multiline validation | TUI polish | Known limitation; not needed for fake/local close-out |
| Legacy Dashboard/AutoRun code on disk | cleanup/product decision | Not imported by default mainline; deleting history is not required for current close-out |

## Gate Evidence

Final post-remediation gates:

| Command | Exit code | Timeout | Result |
|---------|-----------|---------|--------|
| `cd tui && npm test` | 0 | no | 412/412 TUI tests PASS |
| `cd tui && npm run typecheck` | 0 | no | `tsc --noEmit` clean |
| `git diff --check` | 0 | no | clean |
| `.venv/bin/python -m pytest tests/test_local_trial_readiness.py::test_plans_docs_contain_no_secret_fragments tests/test_local_trial_readiness.py::test_audit_docs_contain_no_secret_fragments --tb=short -q` | 0 | no | 2 passed |
| `.venv/bin/python -m pytest tests/test_docs_source_of_truth.py --tb=short -q` | 0 | no | 79 passed |
| `rg --files -g .pre-commit-config.yaml -g .pre-commit-config.yml` | 1 | no | no pre-commit config found; no effective pre-commit gate |

Safety-skipped: provider diagnostics real-key guard. That test reads local provider configuration; its failure path can expose a key prefix. This sweep did not read real config or print secret-like values.

## Final Recommendation

First Agent current-stage can close **yes-with-caveats**.

- B7 final status: accepted-with-caveats.
- B8 final status: accepted-with-caveats.
- B8 product boundary: clean for current default mainline.
- Fake/local boundary: honest after remediation.
- TUI default entry: not activated.
- Need another B8 remediation loop: no, unless final independent audit finds new active-doc or code blockers.
- Ready to move beyond B8: yes-with-caveats, after final independent close-out audit and without starting B9 in this sweep.

Recommended next prompt: final independent audit of current HEAD and this report, focused on active-doc honesty, TUI default-entry non-activation, fake/local boundary, and absence of Dashboard/AutoRun/Product Operations mainline resurrection.

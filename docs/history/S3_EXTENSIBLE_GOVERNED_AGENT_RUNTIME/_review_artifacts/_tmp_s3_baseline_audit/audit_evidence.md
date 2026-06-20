# S3 Baseline Audit — Evidence Packet

> Working evidence for the S3 baseline audit (2026-06-19). This is scratch
> evidence backing `docs/current/S3_BASELINE_STATUS.md`, not routing authority.
> It will be archived with the stage when S3 closes.

## Phase 1 — S2 closeout recovery checks (read-only)

| Check | Command | Result |
|---|---|---|
| Repo state | `git status --short --branch --untracked-files=all` | `## main...origin/main [ahead 24]`, no dirty/untracked files |
| Diff stat | `git diff --stat` | empty (clean tree) |
| Whitespace | `git diff --check` | exit 0 (clean) |
| Closeout commit | `git log --oneline origin/main..HEAD` | HEAD `39edfdd docs: close out S2 and reset current context` |
| current files | `find docs/current -maxdepth 2 -type f` | only `S_ROADMAP.md`, `TECH_DEBT.md` (before this audit) |
| S2 archive | `ls docs/history/S2_GOVERNED_TASK_AGENT` | present; README, S2_*, WORK_LOG, S2_RELEASE_SUMMARY, `_review_artifacts/` |
| S2 markers in current | `rg "S2_BASELINE_STATUS\|S2_GOAL\|WORK_LOG\|_tmp_s2" docs/current` | only a reference path in `TECH_DEBT.md:42` (points into history archive) |
| S3 markers | `rg "S3_GOAL\|S3_GOAL_GAP\|S3_BASELINE" docs/current AGENTS.md` | only `AGENTS.md:28` ("no S3_* yet") |
| Secret tracking | `git ls-files config/config.yaml .env` | empty (neither tracked) |
| Secret ignore | `git check-ignore -v config/config.yaml .env` | both ignored (`.gitignore:36`, `.gitignore:1`) |
| Messy files | scan for diff_*.patch/full_diff.patch/output_report.md/docs/PROJECT_STATUS.md/PROGRESS_LEDGER.md/docs/plans/review/code-review | all absent; `docs/` has only `current/`, `history/` |

Closeout commit `39edfdd` content: `git mv` of all S2 docs + `_tmp_s2_*` evidence
into `docs/history/S2_GOVERNED_TASK_AGENT/` (renames, 0 content change), new
`S2_RELEASE_SUMMARY.md` (+147), `AGENTS.md` rewrite to post-S2/pre-S3, `TECH_DEBT.md`
reduced to carry-forward only (-164 net).

**Verdict:** S2 closeout complete and committed. No recovery work required.

## Phase 2 — S3 baseline evidence

### Targeted S2 gate re-run (fresh, read-only)

```
.venv/bin/python -m pytest -q tests/test_s2_reference_task_acceptance.py \
  tests/test_s2_skill_controlled_integration.py tests/test_s2_acceptance_gate.py -rxs
=> 12 passed, 1 skipped in 1.51s
   (skip = test_s2_reference_task_real_provider_..._smoke, needs
    MY_FIRST_AGENT_RUN_S2_REAL_PROVIDER_SMOKE=1 opt-in)
```

Matches the S2 release record exactly (reference task 1 passed + 1 skipped,
skill gate 6 passed, acceptance gate 5 passed). The S2 release signal is still
credible at the S3 starting point.

### S2 governed-task code surface (graphify + file confirmation)

- L1 runtime spine: `agent/core.py`, `agent/runtime_integration/{dispatcher,schema,tool_gate,evidence}.py`
- L1 acceptance classification: `agent/acceptance_gate.py`
- L2 context/memory: `agent/task_context.py`, `agent/memory_store.py`
- L3 governed tool/evidence: `agent/task_tool_contract.py`, `agent/tool_runtime_mediator.py`, `agent/evidence_recorder.py`, `agent/task_evidence_report.py`
- L4 orchestration/state/progress: `agent/task_state_model.py`, `agent/task_orchestration.py`, `agent/task_runtime.py`, `agent/task_review.py`
- L5 Skill (active, default-off): `agent/skill_system/{gate,selector,lifecycle,checkpoint_restore,task_boundary,memory_boundary,registry,...}.py`
- L5 dormant seams: `agent/runtime_integration/{mcp_bridge_lifecycle,mcp_tool_orchestrator,skill_lifecycle}.py`, `agent/subagent_system/*`

### Full pytest / ruff (inherited from S2 release record, not re-run here)

- Full pytest: 33 failed / 4782 passed / 14 skipped / 26 xfailed — all 33 in the
  TD-006 known guard set (source: `S2_RELEASE_SUMMARY.md §5`, authoritative list
  at `_review_artifacts/_tmp_s2_baseline_audit/fullsuite_failures.txt`).
- ruff: ~451 historical lint errors = TD-007.
- Not re-run in this baseline audit (token economy; tree unchanged since `39edfdd`).
  Fresh re-classification recommended once S3 docs settle (see TD-006 verification idea).

### Observations (recorded, not acted on)

1. `S_ROADMAP.md:46` still says "AGENTS.md 的 S1 Development Governance"; AGENTS.md
   renamed that section to "Stage Development Governance (post-S2 / pre-S3)". Minor
   doc-pointer drift. Not fixed (baseline audit does not edit roadmap).
2. `docs/history/S2_GOVERNED_TASK_AGENT/TECH_DEBT.md` (named in the required-read
   list) does not exist; S2 debt was consolidated into `docs/current/TECH_DEBT.md`
   (carry-forward) + `S2_TECH_DEBT_TRIAGE.md`. Used those instead.
3. `graphify-out/` graph still points S2 doc nodes at old `docs/current/` paths
   (closeout `git mv`'d them to history). Graph is stale vs. the doc moves;
   expected per AGENTS.md. Not regenerated (no code changed this run).

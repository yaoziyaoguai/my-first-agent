# Second-Opinion Review — Corrections Applied (2026-06-17)

> Intermediate notes under `_tmp_s2_baseline_audit/`. Not authoritative. The
> authoritative baseline is `docs/current/S2_BASELINE_STATUS.md`.

## Per-item review decisions (all accepted, evidence-backed)

| # | Second-opinion item | Decision | Evidence |
|---|---|---|---|
| 1 | Over-strong language ("clean usable / only red / no doc conflict / safe for S2-entry") | **ACCEPT** | These are absolute claims; S2 goal is unconfirmed so risk cannot be declared absent. Softened throughout baseline. |
| 2 | Full pytest numbers wrong; fresh = 36 failed, 4747 passed, 13 skipped, 26 xfailed | **ACCEPT** | Re-ran `pytest -q` (no exclusions): `36 failed, 4747 passed, 13 skipped, 26 xfailed in 246s`. My prior 4727/7 came from excluding the 3 opt-in/network real test files; the authoritative no-exclusion number matches the second opinion. |
| 3 | TD-006 scope too narrow ("pre-S1 doc locations") | **ACCEPT** | Of the 36 failures: `test_docs_source_of_truth.py` (23) are doc-location guards; but `test_v6_drift_addendum_boundary.py` (5), `test_architecture_boundaries.py` (3), `test_evidence_taxonomy_guard.py` (2), `test_capability_boundary_contract.py` (1) are architecture-boundary / taxonomy / contract guards; `test_provider_diagnostics.py` (1) is a diagnostics string mismatch; `test_streaming_protocol.py` (1) references a moved doc. Not all are "pre-S1 doc locations". Broadened. |
| 4 | README.md + S_ROADMAP.md still point to `docs/current/S1_GOAL.md` | **ACCEPT — and this corrects my prior audit's wrong "no obvious error found"** | Confirmed: root `README.md` lines 5, 46, 53, 54, 55 + `S_ROADMAP.md` line 17 reference `docs/current/S1_*` (now in history). Fixed: S1 entries → `docs/history/S1_BASELINE_USABLE_PRODUCT/`; added S2 current entries. |
| 5 | Layout omits `_tmp_s2_baseline_audit/` though §5 references it | **ACCEPT** | Added to §2 as an audit evidence artifact, explicitly not an active authority. |
| 6 | WORK_LOG commit hash still "pending" but 568317e exists | **ACCEPT** | `git log --oneline -1` = `568317e docs: audit S2 baseline status`. Updated. |
| 7 | TD-003 H3 title still says "reachability review" but body says confirmed unreachable | **ACCEPT** | Header/body inconsistency. Title changed to "confirmed unreachable / dead-code cleanup"; item kept open (dead code not yet removed). |
| 8 | ruff 451 not in TECH_DEBT | **ACCEPT** | Added TD-007 (lint/quality-gate debt), separate from TD-006 (different source). Not an S2 startup blocker. |

## Notes on what was NOT changed

- No code, tests, config, `.env`, AGENTS.md, S1 history evidence, S2_GOAL.md / S2_GOAL_GAP.md (kept skeletons).
- TD-006 not converted into an S2 gap (goal not confirmed).
- ruff not fixed (out of scope; recorded as debt only).
- Dead code in `agent/context.py` not removed (TD-003 stays open; scope discipline).

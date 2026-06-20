# R-series Trial Summary — Capability Boundary (2026-06-21)

> Verdict from the real-world trial. S-series roadmap mainline remains closed; this is
> R-series *exploration*, not a frozen goal. Detailed cases: `R_REAL_WORLD_USE_CASES.md`;
> failures: `R_TRIAL_FAILURES.md`; run log: `R_TRIAL_RUN_LOG.md`.

## 1. How real-world-usable is FirstAgent right now?

**Structurally complete and fake/local-proven; real-world-usable = NO, blocked at the
first real turn.** The governed kernel (L1-L5), governance, audit/replay, redaction,
and durable recovery all hold and are seam-tested green. But the **real provider path
returns HTTP 400 on every call**, so the unified runtime (`core.chat()` via `main.py`)
cannot complete even a single real model turn. The `main.py demo` path works because it
is a **fake** local adapter (despite advertising "real API").

## 2. fake/local vs real provider

| Path | Status |
|---|---|
| **fake/local demo** (`main.py demo`) | **works** — deterministic, writes real artifacts (`workspace/demo/*/note.md`), 2 events |
| **fake/local unified** (`core.chat()` loop) | not triallable via CLI (config forces real); proven at the seam by S-series integration suites |
| **real unified** (`main.py`, configured `anthropic_compatible`→DeepSeek) | **broken** — HTTP 400 every call |
| **real multi-step / coding** | **blocked** — depends on a working real single turn |

The split is decisive: everything fake/local is healthy; everything real is blocked by
one config/integration fault.

## 3. What runs reliably (real)

- CLI operator surface: `--help`, `health` (with hygiene warns), `logs --tail`,
  `demo` (fake).
- Evidence/audit recording — works even on the failed real turn (structured events
  logged).
- Graceful degradation — the runtime survives the provider 400 (no crash; "正常结束").
- (At the seam, not the product CLI: redaction, acceptance classification, ledger
  recovery/replay/crash-survival, extension dormancy — all green.)

## 4. What is blocked

- **All real coding tasks** (code/test/docs/lint/dead-code changes) — blocked by the
  provider 400.
- **Real multi-step grounded tasks** — blocked (no successful single turn).
- **CLI-level checkpoint resume** — blocked (real task fails before a durable point;
  Ctrl+C-mid-task not simulable via piped stdin; seam-proven by S5).
- **`main.py status` key-redaction verification** — blocked (verification needed
  credential scanning, which the safety classifier denied).

## 5. Product-entry problems

- `main.py demo` advertises "real API" but runs `provider=fake` — misleading (F-03).
- Onboarding text says "Fake default" while actual mode is real — inconsistent (F-03).
- No CLI flag to force fake on the unified path (F-04) — blocks safe-local product
  trials.
- `status` command is undocumented in `--help`; real-provider troubleshooting absent
  from docs (F-07).

## 6. Runtime bugs

- **None found.** The runtime behaved correctly throughout: it called the provider,
  received a 400, degraded gracefully, recorded evidence, and ended cleanly. No kernel
  crash, no spine split, no governance bypass observed.

## 7. Doc / command problems

- Banner/onboarding/demo provider-mode inconsistency (F-03).
- 400 error message not actionable — no hint to check model/endpoint config (F-05).
- `status` undocumented; no real-provider setup/troubleshoot in README/AGENTS (F-07).

## 8. Deferred / non-goal (do NOT "fix" by activating)

- Scheduler productionization, full MCP ecosystem, writable/multi-agent SubAgent,
- memory activation — all verified **dormant/guarded** (cr1 + boundary tests). They are
  **not failures** and must not be activated to "fix" anything. Log/session growth
  (F-06) is operational hygiene, not a runtime bug.

## 9. What to fix first (next batch, priority order)

1. **(P0) Fix the real provider config** — correct the model (`deepseek-v4-flash` → a
   valid DeepSeek Anthropic-compat model, e.g. `deepseek-chat`) or the endpoint, then
   verify the `anthropic_compatible` adapter request shape. This **unblocks 9 of 10
   blocked cases** by itself. (Config + adapter verification, **not** a kernel change.)
2. **(P1) Verify `main.py status` redacts the api_key** (F-02) — mask if needed.
3. **(P2) Make banner/onboarding/demo reflect the actual provider path** (F-03); make
   the 400 (4xx) error actionable (F-05).
4. **(P2) Add a force-fake CLI flag + an interruptible resume harness** (F-04) so
   safe-local + recovery trials can run at the product level.
5. **(P3) Docs: document `status`, add real-provider troubleshooting** (F-07); plan
   log/session rotation (F-06).

## 10. Enter R-series repair batch — or formal goal/gap?

**Yes — enter a small R-series *repair batch*, spike-first, not a full goal/gap yet.**

Rationale: the dominant finding (P0 provider 400) is a **config/integration** fault, not
a kernel capability gap. The right next move is a **time-boxed spike**: fix the provider
config + adapter, then re-run the real trials (R-006/R-101/R-102 and the blocked coding
cases). Only after the real single-turn + multi-step trials actually run will the *real*
capability boundary be visible — at that point a frozen **R goal/gap** is worth writing.
Writing a full R goal/gap now would be premature: the real failure surface is still
almost entirely hidden behind one config fault.

**Proposed sequencing:**
1. R-repair spike: provider config + adapter fix → re-trial real single + multi-step.
2. If real tasks then run: write `R_BASELINE_STATUS.md` → `R_GOAL.md` → `R_GAP.md`
   grounded in *real* observed behaviour.
3. If real tasks still fail after the config fix: the R goal becomes "make the real
   provider path actually work end-to-end" (a real kernel/integration goal).

**The S-series roadmap mainline remains closed; there is no active S stage; this trial
does not open S6.**

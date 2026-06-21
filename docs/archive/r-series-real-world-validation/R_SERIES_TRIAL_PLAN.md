# R-series Real-world Trial Plan

> Status: **R-series trial exploration (post-S closure)**. This is **not** S6 and **not**
> a frozen R goal/gap. It is real-world trial *exploration*: design use cases, run them
> (fake/local **and** real provider), record failures, and surface the capability
> boundary. No runtime bug is fixed here — failures are recorded for a later repair
> batch. S-series roadmap mainline remains closed.

## 1. Goal of this trial

Answer one question honestly: **how real-world-usable is FirstAgent right now?**

The S-series proved the governed runtime *kernel* fake/local + structurally (4946
pytest green, ruff green). It deliberately left real-world validation open. This trial
probes the actual product surface (`main.py` CLI + unified `core.chat()` loop) under
**both** provider paths to discover where the kernel meets reality and breaks.

## 2. Method

- Design a use-case catalog across 7 categories (see `R_REAL_WORLD_USE_CASES.md`).
- Run each case via the real product entry (`main.py ...`) and/or a non-invasive
  fake/local harness.
- **Two provider paths**: fake/local baseline (deterministic) **and** real provider
  (configured `anthropic_compatible` → DeepSeek). Both must be exercised.
- **Failures do not stop the trial.** Every pass/fail/blocked is recorded in
  `R_TRIAL_RUN_LOG.md` and `R_TRIAL_FAILURES.md`.
- **No big runtime fixes during the trial.** Only trial-doc / run-log / minimal-harness
  fixes are allowed. Runtime bugs are recorded, not repaired.

## 3. Constraints (hard boundaries)

- No push. No print/copy/move/commit of secrets or API keys. `config/config.yaml` and
  `.env` must never enter git.
- `config/config.yaml` may be **read** only for local real-provider execution; the
  api_key value is never printed.
- No destructive external operations.
- No activation of Scheduler / memory / full-MCP / writable-SubAgent — only read-only
  verification that they stay dormant/guarded.
- No UI/demo/commercial packaging.
- Not S6; not a continuation of S-series.

## 4. Case taxonomy (7 categories)

1. **Basic product use** — help / entry / minimal task / status / evidence+audit+replay.
2. **Coding task** — small code/test/docs/lint/dead-code change (needs working provider).
3. **Recovery / durability** — interrupt, checkpoint resume, ledger replay, no-repeat,
   crash-survival.
4. **Governance / safety** — secret redaction, forbidden config/.env, no-push, policy
   refusal, acceptance classification.
5. **Tool / provider behavior** — fake/local, real smoke, real multi-step, tool preview,
   tool failure, timeout/retry/malformed output.
6. **Extension boundaries** — Skill/MCP/SubAgent/Scheduler dormancy or guarded behavior
   (read-only; no activation).
7. **Operator experience** — command clarity, error understandability, doc guidance,
   run-log auditability.

## 5. Failure taxonomy

`missing_product_entry` · `command/docs unclear` · `real provider failure` ·
`runtime bug` · `recovery/durability bug` · `evidence/audit/replay bug` ·
`redaction/security issue` · `provider/tool integration issue` ·
`acceptance classification issue` · `deferred-scope boundary issue` ·
`test/harness limitation` · `expected non-goal`.

## 6. Severity

`P0` (blocks all real use) · `P1` (blocks a category) · `P2` (degrades experience) ·
`P3` (cosmetic/clarity).

## 7. Trial scope limits (declared up front)

- The unified `core.chat()` loop cannot be forced to fake via the CLI in this repo
  (config overrides env), so the **unified-path fake/local trial is covered by the
  S-series integration suites**, not re-run here; the product CLI trial is real-provider.
- Real multi-step tasks depend on the real provider succeeding at least one turn.
- A mid-task checkpoint interrupt cannot be simulated via piped stdin, so CLI-level
  resume is a harness-limited case (seam-level recovery is proven by S5).

## 8. Deliverables

- `R_REAL_WORLD_USE_CASES.md` — case catalog + observed results.
- `R_TRIAL_RUN_LOG.md` — run-by-run log.
- `R_TRIAL_FAILURES.md` — failure register (taxonomy + severity).
- `R_TRIAL_SUMMARY.md` — capability-boundary verdict + repair-batch recommendation.

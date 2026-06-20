# R-series Trial Summary — Capability Boundary (2026-06-21)

> Verdict from the real-world trial. S-series roadmap mainline remains closed; this is
> R-series *exploration*, not a frozen goal. Detailed cases: `R_REAL_WORLD_USE_CASES.md`;
> failures: `R_TRIAL_FAILURES.md`; run log: `R_TRIAL_RUN_LOG.md`.

## 1. How real-world-usable is FirstAgent right now?

**Structurally complete, fake/local-proven, and — after the R-series F-01 fix — the real
provider path now accepts tool calls.** The governed kernel (L1-L5), governance,
audit/replay, redaction, and durable recovery all hold and are seam-tested green. The
real provider (configured `anthropic_compatible` → DeepSeek) previously returned HTTP 400
on every tool call; that **P0 is FIXED** (`ae94f26`) — a protocol-generic tool-name
normalize at the adapter seam. **Corrected root cause** (see `R_TRIAL_FAILURES.md` F-01):
it was **provider-visible tool names with illegal dots** (`demo.echo_task_summary`),
NOT user config/model — the bug is protocol-boundary/tool-name handling. FakeProvider
never validated tool names, which hid it. Real chat + real tool calls now return 200 and
the model returns a real tool_use. **Remaining gap**: real-task *completion* — the runtime
did not execute the returned tool_use end-to-end in the piped single-turn flow (F-08). So:
real chat works; real tool-augmented tasks are unblocked at the provider layer but not yet
proven end-to-end.

## 2. fake/local vs real provider

| Path | Status |
|---|---|
| **fake/local demo** (`main.py demo`) | **works** — deterministic, writes real artifacts (`workspace/demo/*/note.md`), 2 events |
| **fake/local unified** (`core.chat()` loop) | not triallable via CLI (config forces real); proven at the seam by S-series integration suites |
| **real unified** (`main.py`, configured `anthropic_compatible`→DeepSeek) | **works** (after F-01 fix) — no-tools 200; tools call 200 (was 400); model returns real tool_use (`write_file`) |
| **real multi-step / coding completion** | **partially** — provider accepts tools + returns tool_use, but the runtime did not complete tool execution end-to-end in the piped flow (F-08) |

The provider tool-name bug (F-01) is FIXED. The remaining real gap is task *completion*
(F-08), not provider connectivity. Note: FakeProvider never validated tool names, which
hid the F-01 bug — see repair item (registry tool-name validation) in §9.

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

- **F-08 (new):** after the F-01 fix, the real provider returns a tool_use but the runtime
  did not execute it end-to-end in the piped single-turn flow (no 3rd provider call;
  target file not created). A real-task *completion* gap — needs investigation
  (tool-execution loop / turn boundary / path-policy). Not fixed this round.
- **Otherwise none at the kernel layer** — graceful degradation on the (now-fixed) 400,
  evidence recording, and clean session end all held. No spine split or governance bypass.

## 7. Doc / command problems

- Banner/onboarding/demo provider-mode inconsistency (F-03).
- Provider-error messages not actionable — on the (now-fixed) 400 there was no hint it
  was a tool-name/protocol issue (F-05).
- `status` undocumented; no real-provider setup/troubleshoot in README/AGENTS (F-07).

## 8. Deferred / non-goal (do NOT "fix" by activating)

- Scheduler productionization, full MCP ecosystem, writable/multi-agent SubAgent,
- memory activation — all verified **dormant/guarded** (cr1 + boundary tests). They are
  **not failures** and must not be activated to "fix" anything. Log/session growth
  (F-06) is operational hygiene, not a runtime bug.

## 9. What to fix first (next batch, priority order)

1. **(P0, DONE)** ~~Fix real provider tool calls~~ — FIXED (`ae94f26`): protocol-generic
   tool-name normalize at the `anthropic_compatible` seam. Real provider tools call now
   200. (This was NEVER a config/model issue.)
2. **(P1) Real-task completion (F-08)** — investigate why the runtime did not execute the
   returned tool_use end-to-end in the piped single-turn flow; prove a real grounded task
   completes (file written, multi-step). Now the top real-world gap.
3. **(P1) Verify `main.py status` redacts the api_key** (F-02) — mask if needed.
4. **(P2) Make banner/onboarding/demo reflect the actual provider path** (F-03); make
   provider-error messages actionable (F-05).
5. **(P2) Add a force-fake CLI flag + an interruptible resume harness** (F-04) so
   safe-local + recovery trials run at the product level.
6. **(P2, repair item) Registry tool-name validation** — add provider-visible tool-name
   validation so fake/local catches illegal names (the dotted demo tools hid F-01). Hard
   enforcement needs renaming the namespaced demo tools first; deferred this round.
7. **(P3) Docs: document `status`, add real-provider troubleshooting** (F-07); plan
   log/session rotation (F-06).
8. **(design note) Streaming** — `AnthropicCompatibleProvider.supports_streaming = False`;
   `stream()` is a `create()`-delegating shim (sanitize+restore inherited via `create`;
   stream events carry no tool names, so restore is not independently asserted there). Not
   a bug.

## 10. Enter R-series repair batch — or formal goal/gap?

**The P0 is fixed; continue a focused R repair batch centered on real-task completion
(F-08), not a full goal/gap yet.**

Rationale: the provider connectivity bug (F-01) is FIXED and the real provider now
accepts tool calls + returns tool_use. The next blocker is **real-task completion**
(F-08) — whether the runtime executes the tool_use and finishes a grounded task
end-to-end. That must be proven before the real capability boundary is knowable. So:
continue the repair batch (F-08 investigation + the P1–P3 items), re-run the real trials,
and only then decide whether a frozen **R goal/gap** is warranted. A formal R goal/gap is
still premature until real multi-step completion is proven.

**Proposed sequencing:**
1. R repair: investigate + fix F-08 (real tool_use completion) → prove a real grounded
   task completes end-to-end.
2. If real tasks then run: write `R_BASELINE_STATUS.md` → `R_GOAL.md` → `R_GAP.md`
   grounded in *real* observed behaviour.
3. If real tasks still fail after the config fix: the R goal becomes "make the real
   provider path actually work end-to-end" (a real kernel/integration goal).

**The S-series roadmap mainline remains closed; there is no active S stage; this trial
does not open S6.**

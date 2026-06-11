# fix: Architecture-repair SoT truth alignment + incremental debt cleanup

> Created: 2026-06-12
> Branch: `chore/architecture-repair-2026-06`
> Type: fix (truth-alignment + test hardening + incremental migration)
> Depth: Standard
> Plan author input: solo invocation (no upstream brainstorm); grounded in a read-only cross-audit completed 2026-06-12 against `main..HEAD` (8 commits).

---

## Summary

The repair branch already did the hard structural work (TargetCatalog extraction, memory four-state tests, safe-metadata projector seed, subagent SoT body-text correction). A read-only audit confirmed **zero Blockers** and **zero proven delete candidates**. What remains is a tight set of *truth-alignment* and *incremental-debt* fixes so the branch reaches merge-ready without any production behavior change.

The single highest-value fix: the `RuntimeDecisionFrame` structured fields and two tests still hard-assert `subagent_level="L1"` / "L1 是生产基线" / `subagent_available=True (L1 已验证)`, while the live delegation path is actually **a direct inline-local fallback with `execution_mode="local_fake"`** (L1 is never registered; V0 is registered + contract-verified but core.py never routes to it). The live path is the inline-local fallback (`subagent_inline.execute_subagent_delegation`), **not** the registered `SubAgentDelegateL0Handler` probe. A *second* source file, `subagent_action.py:7,323`, makes the opposite false claim ("V0 current — 唯一活跃 production path"). Both contradict the runtime. Two tests currently *lock the L1 false claim in place*.

**Scope of the "merge-ready" claim (resolved with user):** this plan makes the branch **merge-ready for the current SoT truth-alignment + repair scope** — NOT a claim that the SubAgent architecture is complete. It does **not** wire V0 to production, does **not** delete the `core.py` L1-attempt/`ToolRuntimeMediator` block, and does **not** change production routing. V0-registered-but-not-routed and the dead L1-attempt block are recorded as **explicit deferred architecture debt** (see "Deferred architecture debt" below), not silently parked.

### Current runtime fact vs declared target vs working diagnosis (evidence-constrained)

The audit distinguishes three layers and does not collapse them:

1. **Current runtime fact** — live CLI/NL delegation is **L1-attempt → direct inline-local (`local_fake`) fallback**. (`core.py:2015` → None → `:2042`; `subagent_inline.py:63`.)
2. **Declared target architecture** — the `U3A freeze gate` (`phase1_hook.py:180-182`) states V0 is the intended sole product Runtime path ("v0 execution 只能沿 SUBAGENT_DELEGATE_V0 这一条 Runtime path 前进").
3. **Working diagnosis → confirmed by git history** — L0-live is an **incomplete-migration state**: V0 was added (`e890711 feat(subagent): add v0 runtime action and profile contract`), then L1/L2 were frozen out of routing (`63084cc fix(subagent): freeze legacy l1 l2 production routes`), but `core.py` was never migrated to route V0. So L0-live is a half-finished L1/L2→V0 migration, **not** a design baseline to enshrine. WP-A states only layer 1 (current runtime fact); WP-F recommends completing the V0 migration as the target.

This plan does **not** wire V0 to production and does **not** delete L1/L2/frozen-memory compat paths. Those are decisions (WP-F) or future work, not this branch.

---

## Problem Frame

A cross-audit (three independent passes, reconciled) found the repair branch is structurally sound but carries residual source-of-truth drift and incremental debt:

- **H1/H2 (High)** — `RuntimeDecisionFrame` (`agent/runtime_decision_frame.py`: fields at :522-526, default-instance assignment at :806-807) declares `subagent_available=True`, `subagent_level="L1"`, and the `BranchPointState["subagent.delegate"]` (state at :283-300) carries `evidence_level=REAL_API_INTERACTIVE` + `status=READY`. Live runtime executes the inline-local fallback (`local_fake`). `phase1_hook.py:174` comment calls V0 "唯一 product runtime path" though core never routes V0. Two tests assert the stale `"L1"` value, enshrining the false claim.
- **M1 (Medium)** — `safe_metadata.project_safe_metadata_text` is used at exactly 1 site; ≥8 production sites still call `mask_user_visible_secrets` directly, two of which (`runtime_observer.py`, `memory_hook.py`) replicate the exact mask-then-cap logic the projector centralizes.
- **M2 (Medium)** — `evidence.py` back-compat re-export pulls in private helpers (`_callable_identity`, `_checkpoint_safe_summary_adapter`, …), turning a temporary shim into a wide implicit contract.
- **M3 (Medium)** — `callable_identity` embeds `__module__` path; any further file-move of an adapter changes the identity string.
- **Test gap** — the live inline-local (`local_fake`) delegation path has no characterization/integration test; all subagent tests pin *registration*, not *execution result*.
- **B (Memory)** — the four-state consolidation tests are correct today; this plan only verifies the inventory and the "frozen ≠ unreachable" framing stays honest (no code change unless a test assertion is found wrong).

### Verified plan-time facts (so implementation does not re-discover them)

| Fact | Evidence | Consequence for plan |
|---|---|---|
| Live delegation = inline-local fallback (`local_fake`) | `core.py:2015` `get_handler(SUBAGENT_DELEGATE_L1)`→None → `core.py:2042` fallback → `subagent_inline.py:63` `execution_mode="local_fake"` | WP-A corrects SoT to describe this; WP-E characterizes it (U3) |
| L1 never registered; only V0+L0 are | `phase1_hook.py:171,177`; dispatcher build smoke = `['subagent.delegate.v0','subagent.delegate_l0']` | WP-A; do NOT register L1; do NOT delete L1 handler |
| `EvidenceLevel.FAKE_LOCAL_USER_PATH` already exists | `runtime_decision_frame.py:38` | WP-A is a **value swap**, not a schema change |
| `RuntimeDecisionFrame.subagent_*` fields have **no production consumers** | grep of `subagent_available`/`subagent_level` outside module+tests = empty | WP-A is low-blast-radius; only tests consume |
| Two tests assert `subagent_level=="L1"` | `tests/unit/test_runtime_decision_frame.py`, `tests/runtime_integration/test_subagent_l2_contract.py::...is_l1` | WP-A MUST update these or they fail / re-enshrine the false claim |
| `is_capability_complete()` / `BRANCH_POINT_REGISTRY` have no production consumers | grep outside module+tests = empty | SoT is documentation-grade, not runtime-gating — informs WP-A risk |
| `callable_identity` not persisted / not cross-process / not cross-version | no `function:agent…` literal in prod; evidence persistence writes safe-summaries, not identities | **WP-C = Low**; no identity rewrite, no migration |
| memory consolidation pipeline IS reached via 1 compat adapter | `target_catalog.py:282-298` `run_consolidation_pipeline(store, llm_generator=None)`; emitted at `loop.py:416` | WP-B framing "frozen but reachable" is correct; do not disable |

---

## Requirements

- **R1** — `RuntimeDecisionFrame` subagent fields and the `subagent.delegate` BranchPointState describe the *current live* path (inline-local `local_fake` fallback) without overclaiming real-API capability; V0 marked registered/contract-verified, not production-routed. (H1)
- **R2** — Before changing `subagent_available`, define its semantic: "capability callable" vs "real-API production-ready". Correct `subagent_level`, `evidence_level`, and availability *separately* per that definition, locked by tests. (user refinement #1)
- **R3** — `phase1_hook.py` absolute "唯一 product runtime path" comment qualified to match reality. (H2)
- **R4** — The two tests asserting `subagent_level=="L1"` updated to assert the corrected truth (not the stale claim). (H1, test-quality)
- **R5** — A new characterization/integration test proves the live inline-local (`local_fake`) delegation path returns a rendered result (execution, not registration). (test gap)
- **R6** — Memory four-state tests verified accurate; frozen-module inventory count + file list re-confirmed; no frozen module deleted, no compat path disabled. (WP-B)
- **R7** — `evidence.py` private-helper re-export: enumerate ALL consumers first; narrow only with sufficient compat evidence, else record an exit plan and leave intact. Public class re-export preserved. (M2, user refinement #2)
- **R8** — `callable_identity` module-path coupling documented as an in-process-only constraint with a "do not move adapter modules without identity review" note; no rewrite. (M3/WP-C)
- **R9** — safe_metadata: produce a trust-boundary-classified call-site inventory; migrate only sites with proven duplicate mask-then-cap or ordering risk, one trust boundary per commit, prioritizing `runtime_observer.py` and `memory_hook.py`. (M1)
- **R10** — WP-F is a decision document only: compare "keep L0 live / V0 future" vs "route V0 / L0 fallback / retire L1". Recommend with rationale. No wiring, no L1 deletion. (WP-F)

---

## Scope Boundaries

### In scope
- Truth-alignment of subagent SoT structured fields, docstrings, and the two tests that pin them (WP-A).
- Verification (and only-if-wrong correction) of memory four-state tests + inventory (WP-B).
- One new characterization/integration test for the live inline-local path (WP-E).
- Small, evidence-gated WP-C touches: re-export consumer audit + identity-coupling doc note. Narrowing the private re-export is **in scope but gated** — it happens this branch ONLY if the consumer audit proves zero external dependency; otherwise U4 produces audit + exit plan only (no narrowing).
- Incremental, per-trust-boundary safe_metadata migration of proven-duplicate sites (WP-D).
- A V0-wiring decision doc (WP-F).
- Roadmap line correction to match the above.

### Deferred to Follow-Up Work
- **V0 production wiring** — explicitly out of this branch (WP-F decides whether/how; needs separate authorization).
- **L1/L2 handler removal** — needs a full reachability + replacement proof (migrate_then_remove candidate, not now).
- **evidence.py re-export narrowing** — handled in U4 as in-scope-but-gated: narrow only if the consumer audit proves no compat dependency; otherwise U4 records an exit plan and leaves the re-export intact. (Not a separate follow-up; the gated decision lands this branch.)
- **Full safe_metadata migration** — remaining low-risk sites land in later per-boundary commits.

### Explicit non-goals (do not touch)
- `AGENTS.md` (user dirty diff — never touch/restore/commit).
- `.claude/settings.json`, `graphify-out/`, `agent_log*` (never commit).
- `agent/skills/__init__.py` tombstone (already correct fail-closed; do not restore `legacy_skills/`).
- `tui/`, `agent/local_demo.py` (isolated; out of scope).
- Repo-wide ruff; broad cleanup; deleting any frozen/deferred code on the basis of the label alone.
- No `git push`.

---

## High-Level Technical Design

### The SoT-vs-runtime gap WP-A closes

```
STRUCTURED SoT (today)                     RUNTIME REALITY (verified)
─────────────────────────                  ──────────────────────────
RuntimeDecisionFrame                        core.chat
  subagent_available = True                   → _dispatch_or_fallback_delegation
  subagent_level     = "L1"  ◄── stale          → get_handler(SUBAGENT_DELEGATE_L1)
  (docstring "L1 是生产基线")                       → None   (L1 never registered)
                                                → fallback: subagent_inline
BranchPointState["subagent.delegate"]             execute_subagent_delegation
  status        = READY                           execution_mode = "local_fake"  ◄── live
  evidence_level= REAL_API_INTERACTIVE ◄── overclaim
                                            phase1_hook registers: {V0, L0}  (no L1)
                                            V0 = registered + contract-verified,
                                                 NOT routed by core  ◄── dormant
```

WP-A target state: `evidence_level → FAKE_LOCAL_USER_PATH` (value already exists), `subagent_level` no longer a bare `"L1"`, availability semantic split (see WP-A approach), V0 described as registered-not-routed. No schema/field additions.

### WP-D decision gate (per call site)

```
mask_user_visible_secrets call site
   │
   ├─ does it also truncate (mask(...)[:N]) ?  ──no──► leave as-is (mask-only is fine)
   │            │yes
   ├─ is order mask-then-cap already correct? ──yes─► leave unless dedup value is high
   │            │ (or wrong/duplicated)
   └─ proven duplicate of projector logic ────────► migrate to project_safe_metadata_text
                                                     (one trust boundary per commit)
```

### WP-C re-export decision gate

```
private helper in evidence.py re-export
   → grep ALL consumers (prod + tests + imports)
        ├─ zero external consumers + clear compat evidence ─► narrow re-export
        └─ any consumer OR insufficient evidence ──────────► keep + record exit plan
   (public class re-export: always preserved)
```

---

## Implementation Units

Execution order (per user priority): **U1 → U2 → U3 → U4 → U5 → U6 → U7**.

WP↔U legend: U1=WP-A, U2=WP-B, U3=WP-E, U4=WP-C, U5=WP-D, U6=WP-F, U7=roadmap.
Each unit = one or more atomic commits (most are exactly one; **U5 is explicitly multi-commit, one per trust boundary** — see U5). Each commit body must carry: Finding, Evidence, Root-Cause, Decision, Boundary, Files, Tests, Non-Goals, Rollback. Per-unit verification: `git diff --check` + ruff on touched files + targeted tests green.

### U1. SubAgent SoT truth alignment (WP-A) — merge-blocking

**Goal:** Make `RuntimeDecisionFrame` subagent fields + `BranchPointState["subagent.delegate"]` + the overclaiming comments in `phase1_hook.py` and `subagent_action.py` describe the **current runtime fact** honestly (live = L1-attempt → direct inline-local fallback, `execution_mode="local_fake"`); stop overclaiming real-API capability AND stop claiming V0 is the active production path; update the two tests that pin the stale `"L1"`. **WP-A aligns to the current runtime fact only — it does NOT write inline-local as the target architecture** (target = V0, see U6/WP-F).

**Requirements:** R1, R2, R3, R4.
**Dependencies:** none.

**Files:**
- `agent/runtime_decision_frame.py` (`RuntimeDecisionFrame` fields at :522-526 + docstrings; constructor defaults at :661-662; the `subagent_available=True # L1 已验证` / `subagent_level="L1" # L1 是生产基线` assignment site at :806-807; `BranchPointState["subagent.delegate"]` status/evidence_level/body at :283-300)
- `agent/runtime_integration/phase1_hook.py` (:174, :182 comments calling V0 "唯一 product runtime path")
- `agent/runtime_integration/subagent_action.py` (:7 table row "V0 current — 唯一活跃 production path", :323 "the only production subagent path", :1279 — same overclaim in the *opposite* direction; qualify to "registered + contract-verified, not production-routed")
- `tests/unit/test_runtime_decision_frame.py` (:196 asserts `subagent_level=="L1"`)
- `tests/runtime_integration/test_subagent_l2_contract.py` (`test_subagent_level_is_l1` at :453 asserts `=="L1"`, comment "默认 level 应为 L1（生产基线）")
- `tests/runtime_integration/test_subagent_runtime_truth.py` (extend to assert the corrected `evidence_level`/availability semantic)
- `docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md` + `docs/06-audit/POST_REPAIR_AUDIT_DELTA.zh.md` status text (the structured-docs portion of U1; the roadmap *line* itself is U7 — here only the status wording that must move in lockstep with the field change)

**Terminology guard (do NOT conflate two different things):** the registered `SubAgentDelegateL0Handler` (a turn-end probe, `phase1_hook.py:171`) is NOT the live delegation path. The live path is `subagent_inline.execute_subagent_delegation` — a *direct inline-local fallback*, reached only because the L1 route returns no handler. The plan calls the live path **"inline-local fallback"**, never "registered L0 handler". Do not relabel the live path as "L0" in a way that implies the registered L0 handler executes it.

**Frozen `subagent_level` target value (item 3 — value is frozen here, not "e.g."):**
- **Frozen value: `subagent_level = "inline_local_fallback"`.** Rationale: it names the *current runtime fact* (L1-attempt → direct inline-local fallback) without implying the registered L0 handler runs, and without implying L0/inline is the target architecture.
- **Value domain:** `subagent_level` is a free-form `str` field (no Enum, no constant set). Verified: the only value used anywhere today is `"L1"` (default + the `make_*` constructor + 2 test asserts); there is no `"L0"`/`"V0"` constant to collide with. Introducing `"inline_local_fallback"` adds one new string to a free-form field — no enum membership to extend.
- **Serialization compat:** `RuntimeDecisionFrame` is **not serialized** anywhere — no `asdict`/`to_dict`/`json`/pickle in `runtime_decision_frame.py`, and no persistence of the frame to disk/checkpoint/event-log. So the value change has zero on-disk or cross-process compat surface.
- **Consumer compat:** the only consumers of `subagent_level` are the two tests (`test_runtime_decision_frame.py:196`, `test_subagent_l2_contract.py:453`). No production code reads it (grep-verified). Both tests are updated in this unit. No other consumer to migrate.
- (If review prefers a different frozen string, it must re-run this same value-domain / serialization / consumer-compat check before substituting — do not leave it as "e.g.".)

**Approach (R2 semantic decision FIRST; U1 representation RESOLVED to option (a) — no schema change):**
1. Encode the two distinct meanings so they cannot be conflated again:
   - `subagent_available` = "a subagent capability is *callable* on the live path" → **stays True** (the inline-local fallback is callable). Update its docstring to drop "L1 已验证" and state "callable via inline-local (local_fake) fallback".
   - `subagent_level` (option (a), resolved): set to the **frozen value `"inline_local_fallback"`** and correct its docstring to "current live executing path (inline-local fallback); target is V0 — see V0_WIRING_DECISION" (drop "L1 是生产基线"). Do NOT add a new field; the registered/requested/fallback distinction is carried by `BranchPointState["subagent.delegate"].execution_path` (already corrected). Option (b), a minimal additive field, was considered and **declined for this branch** (see Decisions); do not re-open it.
   - `evidence_level`: `REAL_API_INTERACTIVE → FAKE_LOCAL_USER_PATH` (existing enum value, expresses the current local_fake/live reality). **Hard boundary:** do NOT touch `is_capability_complete()`'s allowed set in this unit (see "is_capability_complete decision boundary" below and Open Questions). The value swap preserves current behavior by design.
2. Qualify the overclaiming comments in BOTH files so they match the current runtime fact: `phase1_hook.py:174/182` (V0 is the only *registered* product handler; live route remains L1-attempt→inline-local fallback; V0 wiring pending) AND `subagent_action.py:7/323/1279` (V0 is registered + contract-verified, NOT the active production path). These two files currently make *opposite* false claims; both must land in this unit or the "comments all match the live path" stop condition is false on merge.
3. Update the two stale tests to assert the corrected truth; rename `test_subagent_level_is_l1` (e.g. `test_subagent_level_is_inline_local_fallback`). These tests currently enshrine the false claim — flipping them is required. The flip encodes the *current runtime fact*, NOT a claim that inline-local is the target architecture; reference WP-F for the target.

**is_capability_complete decision boundary (item 4 — explicit, do NOT fold into the value swap):**
- This unit MAY set `evidence_level = FAKE_LOCAL_USER_PATH` to honestly express the current execution fact.
- This unit MUST NOT modify `is_capability_complete()`'s allowed set (`runtime_decision_frame.py:78-88`). `FAKE_LOCAL_USER_PATH` is currently in that set; removing it is a **capability-semantics behavior change**, not SoT truth-alignment, and is out of scope for U1.
- The question "should a fake-local path be considered capability-complete?" is recorded as an independent **deferred decision** (see Open Questions) with consumer impact, compat risk, and owner — to be decided separately, not opportunistically in U1.

**Patterns to follow:** mirror the honest body-text style already in `BranchPointState["subagent.delegate"]` (corrected last commit) and the assertions in `test_subagent_runtime_truth.py::test_sot_does_not_overclaim_v0_as_live_execution_path`.

**Execution note:** Characterization-first — before editing, run the two stale tests to capture current asserts; write the corrected assertions, watch them fail, then change the source so they pass.

**Test scenarios:**
- Covers R1/R2. `subagent_available` is True AND its docstring/meaning is "callable via inline-local fallback", not "real API verified" (assert field + a contract test that evidence_level is not a real-API level while available is True).
- Covers R1. `BranchPointState["subagent.delegate"].evidence_level == EvidenceLevel.FAKE_LOCAL_USER_PATH`; `status` no longer implies real-API interactive capability.
- Covers R4. `subagent_level == "inline_local_fallback"` (the frozen value); no longer `"L1"`; docstring no longer says "L1 是生产基线".
- Covers R3. Neither `phase1_hook` nor `subagent_action.py` source contains an unqualified "唯一 ... production path" / "the only production subagent path" claim (grep-style contract, mirroring the existing truth test) — both files corrected.
- Regression (CRITICAL): `is_capability_complete()` returns the SAME value as before the swap (FAKE_LOCAL_USER_PATH is in the allowed set) — proves the evidence_level downgrade did not silently change capability-complete semantics AND that the allowed set was not touched.

**Verification:** the two formerly-stale tests now assert corrected truth and pass; `test_subagent_runtime_truth.py` extended and green; no production consumer of these fields exists (already verified) so no runtime behavior changes.

### U2. Memory four-state truth verification (WP-B)

**Goal:** Confirm the four-state consolidation tests and frozen inventory are accurate; correct only assertions/descriptions found wrong. No frozen module deleted, no compat path disabled.

**Requirements:** R6.
**Dependencies:** none.

**Files:**
- `tests/runtime_integration/test_memory_consolidation_truth.py` (verify/repair only)
- (read-only verify) `agent/runtime_integration/memory_consolidate.py`, `agent/runtime_integration/target_catalog.py::_memory_consolidation_adapter`, the 6 `agent/memory_consolidation_*.py`

**Approach (item 5 — prove reachability dynamically, not by docstring/grep/inspect):** The four states must each be proven the *right* way. Implementation-frozen is a static fact (banner check is acceptable for that one). But **runtime-reachability must NOT be argued from docstrings, `grep`, or `inspect.getsource`** — it must be demonstrated by actually exercising the call chain with a dynamic/monkeypatch behavior test:

  `MEMORY_CONSOLIDATE` → active handler (`MemoryConsolidateHandler`) → TargetCatalog binding → compatibility adapter (`_memory_consolidation_adapter`) → frozen consolidation pipeline (`run_consolidation_pipeline`).

  Build the phase-1 dispatcher, route a real `MEMORY_CONSOLIDATE` request through it with an `InMemoryMemoryStore`, and monkeypatch `run_consolidation_pipeline` (or assert on its observable effect) to **prove the frozen pipeline is actually invoked at runtime through the adapter** — not merely that the symbols exist. The audit found the existing assertions broadly correct, so this unit *adds the dynamic reachability proof* the existing test lacks and corrects any wording that implies the frozen pipeline is "unreachable". Re-confirm the full frozen-module inventory (6 modules) and file list. Do NOT delete any frozen module or disable the compat path.

**Test scenarios (each state proven independently, by the right method):**
- Covers R6 (implementation_frozen). All 6 modules carry the `⛔ FROZEN` banner (static check — acceptable for the frozen dimension). Inventory count == 6 and file list matches.
- Covers R6 (handler registered). Build `build_phase1_dispatcher()`; assert `MEMORY_CONSOLIDATE` resolves to a non-None handler whose module is NOT frozen — dynamic dispatcher inspection, not source grep.
- Covers R6 (runtime reachable — DYNAMIC). Route a `MEMORY_CONSOLIDATE` request through the dispatcher with a real store; monkeypatch `run_consolidation_pipeline` to record invocation; assert it WAS called through the adapter. This proves reachability behaviorally, replacing any docstring/grep/inspect-based reachability argument.
- Covers R6 (dimensions distinct). Assert that default-product-usage / env-gated-usage and runtime-reachability are separate: e.g. the handler is reachable regardless of the env that gates *default invocation*, demonstrating the two axes are independent (not collapsed into one boolean).

**Verification:** `test_memory_consolidation_truth.py` green; reachability is proven by a dynamic route-through test (not inspect/grep); frozen banners present in all 6 modules; adapter still wired (no disable); no frozen module deleted.

### U3. Live inline-local fallback characterization/integration test (WP-E)

**Goal:** Close the production-path test blind spot: prove the live CLI/NL delegation actually executes (L1-attempt → direct inline-local `local_fake` fallback) and renders a result — real behavior, not registration. This is a **characterization/integration test of the current live path**, not a forced-red TDD test.

**Requirements:** R5.
**Dependencies:** U1 (so the test references corrected truth, not the stale claim).

**Files:**
- `tests/runtime_integration/test_subagent_delegation_live_path.py` (new) — or append to `test_subagent_runtime_truth.py`; new file preferred for behavioral isolation.
- (read-only) `agent/core.py::_dispatch_or_fallback_delegation` + the public CLI/NL delegation entry that calls it, `agent/subagent_inline.py`, demo descriptors under `agent/subagent_system/descriptors/`

**Test nature (item 6 — characterization, not forced-red):**
- The current live path already exists, so the test **should PASS on first run**. Do NOT write it red-first and do NOT modify production code to make it pass.
- If the test FAILS on first run, that means the runtime-path diagnosis is wrong — STOP and re-investigate the path; do NOT edit production code to force green.
- **Entry-point preference:** drive it from the public `core` chat / CLI-NL delegation entry if reachable in a test. Only if the public entry is impractical to exercise in a unit test, call the delegation helper directly — and in that case label it an **integration test**, NOT a full e2e.
- It must **really execute** the L1-attempt → inline-local fallback and assert on the rendered result, NOT inspect source or check the registry.

**Approach:** Exercise the live path end-to-end-of-the-fallback: a dispatcher with no L1 handler (the production reality) → `_dispatch_or_fallback_delegation` → `subagent_inline.execute_subagent_delegation` against a real registered demo descriptor (`demo-stat`), asserting it returns a rendered delegate-result string with a non-error status and that `local_fake` mode was the execution mode. Use the registered demo descriptor path, not a test fixture, to mirror production. Do not relax evidence classification or dispatcher boundaries to make the test pass.

**Execution note:** Characterization-first — capture the *current* live behavior; first run is expected green. No red phase.

**Test scenarios:**
- Covers R5 (happy path, live). With no L1 handler registered (production reality), delegating to `demo-stat` actually runs the inline-local fallback and returns a rendered result string, status not "error", `local_fake` mode exercised. First run passes.
- Integration (the live fallback edge). `_dispatch_or_fallback_delegation` with an L1-less dispatcher falls through to `subagent_inline.execute_subagent_delegation` and returns a rendered result — proving L1-attempt→inline-local fallback is the real path (not the registered L0 handler, not V0).
- Edge: unknown subagent name → `render_delegate_not_found` rendering (not a crash).
- Error path: registry load failure surfaces `render_delegate_error`, not an exception.

**Verification:** new test file green; exercises real `delegate_once` + demo descriptor; no boundary/evidence relaxation in the diff.

### U4. TargetCatalog re-export + identity coupling (WP-C) — Low, evidence-gated

**Goal:** Document `callable_identity`'s in-process-only constraint; audit the evidence.py private-helper re-export consumers and narrow ONLY with sufficient compat evidence, else record an exit plan. Public class re-export preserved. No identity rewrite, no evidence.py re-split.

**Requirements:** R7, R8.
**Dependencies:** none (independent of U1-U3).

**Files:**
- `agent/runtime_integration/target_catalog.py` (doc note near `_callable_identity` :63 and `RuntimeActionTargetDescriptor`)
- `agent/runtime_integration/evidence.py` (re-export block :701+ — narrow only if proven safe)
- `docs/06-audit/POST_REPAIR_AUDIT_DELTA.zh.md` or an exit-plan note (if narrowing deferred)

**Approach (user refinement #2 — audit before any removal):**
1. **R8 (doc only):** Add a concise note: `callable_identity` embeds `__module__`; it is in-process-only (verified: not persisted, not cross-process, not cross-version compared, no production consumer depends on a stable historical value). Severity **Low**. Constraint note: "do not move adapter modules without an identity review." **No code change to identity; no migration designed.**
2. **R7 (evidence-gated):** Enumerate the COMPLETE consumer list (production + tests + imports) of each private re-exported name (`_callable_identity`, `_checkpoint_safe_summary_adapter`, and the rest of the `_`-prefixed re-exports). Decision gate:
   - If a private name has **zero** consumers anywhere → narrow (drop it from evidence.py re-export; callers, if any later appear, import from target_catalog).
   - If **any** consumer exists OR there is ambiguity → **keep it, record an exit plan** in the audit-delta doc. Do not delete during this branch.
   - Public class re-export (`RuntimeActionTargetCatalog`, `RuntimeActionTargetDescriptor`) is **always preserved** (a test pins it).

**Test scenarios (item 7 — verify consistency + invariance; do NOT strengthen the module-path contract):**
- Covers R8. Verify catalog binding identity matches the runtime proof identity (the two are consistent) — this is the behavioral invariant that matters, NOT "the identity string must live under the `target_catalog` module path".
- Covers R8. Verify production dispatch + evidence classification are unchanged by this unit (a route-through assertion or reuse of existing dispatch tests). The identity-coupling fact is recorded as a doc note, not a hardened test.
- **Do NOT add or strengthen** any test asserting `callable_identity` *must* resolve to the `agent.runtime_integration.target_catalog` module path as a permanent contract. The existing `test_callable_identity_still_uses_function_module_path` pins the current *shape* for the extraction; leave it as-is, do not promote it into a stronger "identity is bound to this module forever" contract (that would entrench the very coupling we rated Low and chose not to design around).
- Covers R7. If narrowing happens: a test that the narrowed private names are no longer re-exported from evidence.py but the public classes still are. If narrowing deferred: assert the public re-export still holds and record the exit plan (no test change).
- Regression: `test_target_catalog_extraction.py::test_evidence_module_re_exports_target_catalog` stays green (public re-export intact).

**Verification:** public re-export test green; identity-coupling note present; either narrowing landed with consumer-audit evidence in the commit body, or an exit plan recorded and re-export left intact.

### U5. safe_metadata incremental migration (WP-D) — per trust boundary

**Goal:** Build a trust-boundary-classified inventory of **durable/user-visible preview fields** (NOT only existing `mask_user_visible_secrets` call sites — see security note); migrate proven-duplicate / ordering-risk sites to `project_safe_metadata_text`, one trust boundary per commit, prioritizing `runtime_observer.py` and `memory_hook.py`. No global mechanical replace.

**Security note (raised in review — widens the inventory root):** rooting the inventory at "places that already call the masker" is structurally blind to the real leak class: a site that **truncates without masking at all**. Security review found `agent/evidence_persistence.py` builds a `preview_redacted` field = `content_str[:MAX_PREVIEW_CHARS]` for **non-sensitive paths**, where masking is gated on path patterns (`_SENSITIVE_PATH_PATTERNS`), not content — so a secret embedded in content from a non-matching path (web/API tool output, env dump) is persisted **unmasked** and uncapped-of-secrets. This is a DURABLE boundary (session transcript / checkpoint / event log). Similar truncate-without-mask: `loop.py:66` `result_text[:200]`, `loop.py:93` `tool_output[:500]`. The inventory MUST enumerate these even though they never call the masker today.

**Requirements:** R9.
**Dependencies:** none.

**Files (inventory — classify each by trust boundary):**
- `agent/runtime_observer.py` (×2: `mask(value)` then cap :75, `mask(str(value))[:MAX_LOG_TEXT_PREVIEW]` :90) — logs/observer preview (mask-then-cap, safe order; dedup value only)
- `agent/runtime_integration/memory_hook.py` (`mask(candidate.content)[:200]` :157) — memory preview (mask-then-cap, safe)
- `agent/evidence_persistence.py` (`preview_redacted = content_str[:N]` on non-sensitive paths, :125/:175) — **persistence boundary; truncate-WITHOUT-mask leak candidate** (path-gated, not content-gated)
- `agent/loop.py` (`result_text[:200]` :66, `tool_output[:500]` :93) — trace metadata; truncate-without-mask candidates
- `agent/tool_result_contract.py`, `agent/tool_executor.py` (×3) — tool preview / persistence boundary (mask-then-truncate confirmed safe; dedup value only)
- `agent/local_config.py` — config/local diagnostics
- `agent/runtime_integration/safe_metadata.py` (projector — target)
- `tests/runtime_integration/test_safe_metadata_projector.py` (extend per migrated site)

**Severity framing (item 8 — do not over-label as vulnerabilities):** The already-verified mask-then-cap sites (`runtime_observer`, `memory_hook`, `tool_result_contract`) have **no confirmed leak** — their order is safe. Migrating them is **ownership / DRY / consistency debt**, NOT a security-vulnerability fix; the plan must not label them as vulnerabilities. The one genuine *leak candidate* is the truncate-WITHOUT-mask path in `evidence_persistence.py` (D2), whose secret-reachability must be checked separately before it is rated.

**Approach:** This unit is **explicitly multi-commit, one per trust boundary**. For each boundary, the workflow is: inventory → input sensitivity → mask/truncate order → schema-filtering/allowlist → characterization → leak-prevention test → minimal migration → commit → review. Commits:
- **D1 — `runtime_observer.py` preview** (ownership/DRY): exact mask-then-cap duplicate of the projector; migrate to `project_safe_metadata_text`. Safe order already; value is DRY, not leak-fix. Own commit.
- **D2 — `evidence_persistence.py` truncate-without-mask path** (LEAK candidate): the non-sensitive-path `preview_redacted = content_str[:N]` + `loop.py` trace truncations. Check whether a secret can reach this from a non-`_SENSITIVE_PATH_PATTERNS` path. **If reachable → escalate to P1** and mask (via projector) before the `[:N]` cap. **If proven non-sensitive or allowlist-protected → record that evidence** in the audit-delta doc and leave as-is. Own commit. Decide with evidence, not assumption.
- **D3 — `memory_hook.py` preview** (ownership/DRY): the `mask(candidate.content)[:200]` preview; exact mask-then-cap duplicate; migrate. Own commit, separate from D1.
- **Other tool/config/local sites:** only add a commit if there is clear value (proven duplicate or ordering risk); mask-only sites (no truncation) are fine as-is; defer the rest with a note.
- **Schema-filtering boundaries (act on it, don't just list it):** `evidence_recorder.build_memory_evidence_metadata` (:304-308) drops `raw_fields` by **allowlist**; `memory_hook.py:138` passes unmasked `candidate.content` into `raw_fields` relying on that allowlist. These must **NOT** be migrated to `project_safe_metadata_text` (a free-text masker cannot enforce a field allowlist). Verify the allowlist holds; leave them on the allowlist.
- Do NOT change the canonical masker in `display_events.py`. The projector is a thin wrapper, not a replacement.

**Test oracle constraint (item 8):** Per-boundary tests must assert the **leak-prevention behavior directly** (no secret prefix survives a mid-token cap; masked-before-truncate) and characterize visible output for non-secret input. Do **NOT** use "old implementation output `==` projector output" as a permanent equivalence oracle — that pins the projector to the legacy implementation forever and breaks the moment either changes for a good reason. Test the property (no leak, correct order), not the byte-equality with the old code.

**Execution note:** TDD per site — add a projector-equivalence + leak-prevention test for the migrated boundary before changing the call site.

**Test scenarios:**
**Test scenarios (property-based, not equivalence-to-old-impl):**
- Covers R9 (D1). After migrating `runtime_observer` preview: no `sk-`/secret prefix survives a cap that would cut mid-token (masks before truncating). Property test, not `old == projector`.
- Covers R9 (D3). `memory_hook` proposal preview: secret patterns redacted before the 200-char cap. Property test.
- Covers R9 (D2, leak gate). A secret embedded in content from a NON-sensitive path → `evidence_persistence` preview does not persist the unmasked secret. If this fails without a code change, the site is **P1** and D2 masks-before-cap; if it proves unreachable / allowlist-protected, record that evidence instead.
- Schema-filtered boundaries: a test (or verification note) that the `raw_fields` allowlist still drops unlisted fields — and that these sites are NOT routed through the text projector.
- Each migrated site keeps identical visible output for non-secret input (characterization of behavior, not byte-equality with the old masker call).

**Verification:** D1/D3 migrated sites route through `project_safe_metadata_text` (ownership/DRY debt closed); D2 truncate-without-mask boundary either fixed (mask-before-cap, P1) or its non-reachability/allowlist-protection proven in the audit-delta doc; allowlist-protected sites verified and left on the allowlist; per-boundary leak-prevention tests green (no old-impl equivalence oracle); remaining un-migrated sites inventoried with rationale; no change to `display_events.mask_user_visible_secrets`.

### U6. V0 production-wiring decision document (WP-F) — decision only

**Goal:** A decision doc comparing the two V0-wiring options with a recommendation and rationale. No wiring, no L1 deletion, no code change.

**Requirements:** R10.
**Dependencies:** U1 (references corrected SoT).

**Files:**
- `docs/06-audit/V0_WIRING_DECISION.zh.md` (new) — or a section appended to the roadmap.

**Approach:** Write a decision doc, no implementation. Frame against the git-confirmed history (V0 added `e890711`, L1/L2 frozen `63084cc`, core never migrated → L0-live is an incomplete migration). Compare:
- **Option 1 — keep inline-local live / V0 future:** core stays L1-attempt→inline-local fallback; V0 stays registered + contract-verified. (Enshrines the incomplete-migration state.)
- **Option 2 — route V0 / L0 fallback / retire L1 (RECOMMENDED target):** core routes `SUBAGENT_DELEGATE_V0`; L0 becomes fallback; the dead L1-attempt block (`core.py:2002-2039`) is removed; L1 handler retired after reachability proof. This completes the migration the freeze commit started.
- Dimensions: runtime/evidence/observer consistency; memory/tool/policy wiring; compatibility; failure fallback; test cost; preconditions for deleting L1; rollout/rollback.
- Output: recommend **Option 2 as the target architecture** (it finishes the abandoned migration and clears the deferred debt), with rationale. **But explicitly state**: V0 production wiring is NOT implemented in this branch, the L1-attempt block is NOT removed here, production routing is unchanged this round, and execution requires a separate authorized branch that first verifies dynamic registration, test/demo callers, observability, and rollback. This unit only *recommends*; it does not wire.

**Test scenarios:** `Test expectation: none — documentation-only unit, no behavioral change.`

**Verification:** decision doc exists, both options compared across all listed dimensions, recommendation + rationale present, no code/test/wiring change in the diff.

### U7. Roadmap line correction

**Goal:** Align the roadmap with the post-WP-A truth and this plan's status.

**Requirements:** R1 (consistency).
**Dependencies:** U1, U6.

**Files:** `docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`

**Approach:** Update the V3/SubAgent line to: "V0 registered + contract-verified; live CLI/NL remains L1-attempt→inline-local (`local_fake`) fallback; V0 production wiring pending (see V0_WIRING_DECISION); incomplete L1/L2→V0 migration recorded as deferred architecture debt." Unify the "partial" vs "已修正" wording flagged as L-level in the audit. Cross-check that NO doc still calls V0 the "active production path" (the `subagent_action.py` claim is corrected in U1; this is the doc-side sweep). Doc-only.

**Test scenarios:** `Test expectation: none — documentation-only.`

**Verification:** roadmap line matches corrected SoT; no contradictory "L1 是生产基线" wording remains in docs.

---

## What Already Exists (reuse, do not rebuild)

- **`EvidenceLevel.FAKE_LOCAL_USER_PATH`** (`runtime_decision_frame.py:38`) — already in the enum and already in `is_capability_complete()`'s allowed set. WP-A reuses it; no new value.
- **`test_subagent_runtime_truth.py`** — already pins registration truth + "V0 not overclaimed". WP-A extends it rather than adding a parallel test file.
- **`safe_metadata.project_safe_metadata_text`** + its 13-test contract — WP-D migrates call sites *into* it; the mask-before-truncate contract and tests already exist.
- **`_memory_consolidation_adapter`** + four-state test — WP-B verifies, does not rebuild.
- **`test_target_catalog_extraction.py::test_evidence_module_re_exports_target_catalog`** — already guards the public re-export; WP-C must keep it green.
- **Honest body text** in `BranchPointState["subagent.delegate"]` (last commit) — WP-A aligns the *structured fields* to match this already-corrected prose.

---

## Failure Modes (per new/changed codepath)

| Codepath | Realistic production failure | Test covers? | Error handling? | Silent? |
|---|---|---|---|---|
| WP-A field/enum edit | A real production consumer appears later and reads `subagent_level` expecting `"L1"` | grep proved zero consumers today; regression test on `is_capability_complete()` | n/a (doc-grade SoT) | No — tests assert the new truth |
| WP-A test flip | Flipping the two stale tests masks a real regression | The flip is the point; new asserts encode verified runtime truth | n/a | No |
| WP-E live-path test | inline-local fallback under `local_fake` changes behavior | the new characterization/integration test IS the guard | `render_delegate_error` path tested | No |
| WP-C narrowing | Narrowing a private re-export breaks a hidden importer | consumer grep gate before any narrowing; keep+exit-plan if unsure | ImportError would surface in suite | No — suite catches |
| WP-D migration | Migrated site changes visible output or leaks on truncation | per-boundary leak + characterization test | projector masks-first by contract | No |

No failure mode is simultaneously untested, unhandled, and silent → no critical gap.

---

## Risks & Mitigation

- **R-low (WP-A):** structured-field edit could *look* behavior-changing in review. Mitigation: commit body states grep-proven zero production consumers; regression test on `is_capability_complete()`.
- **R-low (WP-C):** over-eager re-export narrowing. Mitigation: hard gate — narrow only with zero-consumer evidence, else exit plan; public re-export always kept.
- **R-low (WP-D):** mechanical over-replacement. Mitigation: per-trust-boundary commits; only proven duplicates; `display_events` masker untouched.
- **R-none (WP-B/F/roadmap):** verification + docs only.

---

## Test Value Matrix (what this plan adds/changes)

| Unit | Test category | Value target | Anti-pattern guard |
|---|---|---|---|
| U1 | behavior + boundary contract | ★★★ | flips two stale `=="L1"` asserts that lock a false claim; freezes value to `inline_local_fallback`; regression-pins `is_capability_complete()` unchanged (allowed set untouched) |
| U2 | behavior + boundary (dynamic) | ★★★ | proves runtime-reachability by routing `MEMORY_CONSOLIDATE` through the dispatcher + monkeypatch, NOT by docstring/grep/inspect |
| U3 | characterization / integration | ★★★ | tests real execution result of the live inline-local fallback, not registration; first-run green (no forced red) |
| U4 | boundary + doc note | ★★ (Low) | verifies catalog↔proof identity consistency + dispatch invariance; does NOT strengthen the module-path-binding contract |
| U5 | behavior (leak-prevention) | ★★★ | per-boundary property tests (no leak / correct order); NO old-impl≡projector equivalence oracle |
| U6 / U7 | none (docs) | n/a | documentation-only |

---

## Commit Matrix (final, no-contradiction — item 9)

Every commit is independently revertible and single-finding. **No mixed "review fixes" commit** is allowed at the end — each finding lands in its own unit commit. **No empty commits** — if a unit produces no diff, it produces no commit.

| Unit | Commit(s) | Type | Atomic? | Commit only if… |
|---|---|---|---|---|
| U1 | 1 commit | SubAgent structured SoT fields + docstrings + comments (`phase1_hook`, `subagent_action`) + the two flipped tests + the status wording in roadmap/audit-delta that must move in lockstep | yes — one atomic SoT-alignment commit | always (U1 is merge-blocking) |
| U2 | 0–1 commit | Memory four-state dynamic reachability test fix | yes | **only if there is a real diff** (new dynamic test or corrected assertion). If the existing test already proves reachability dynamically, record "no change needed" and make **no commit** |
| U3 | 1 commit | New live inline-local fallback characterization/integration test (test-only) | yes | always (new coverage) |
| U4 | 0–1 commit | identity-coupling doc note + (only if consumer audit proves safe) private re-export narrowing | yes | **only if** narrowing is proven safe OR a doc note is added. **No empty commit** if the audit defers and no doc change is needed beyond the exit-plan line |
| U5 | up to 3 commits (D1, D2, D3) + optional others | one per trust boundary (D1 runtime_observer, D2 evidence_persistence leak-gate, D3 memory_hook) | each boundary atomic | each commit only if that boundary has a real diff; D2 may be a doc-evidence note instead of code if proven non-reachable |
| U6 | 1 commit | V0 wiring **decision document** (new `docs/06-audit/V0_WIRING_DECISION.zh.md`) | yes | always (new doc) — **separate from U7** |
| U7 | 1 commit | Roadmap + status **final alignment** | yes | always — **separate from U6**; do NOT fold U6 and U7 into one docs commit |

**U6 vs U7 are independent commits** (explicit per item 9): U6 saves the architecture decision; U7 updates the roadmap/status. They are not merged into a single docs commit.

Each commit body carries: Finding, Evidence, Root-Cause, Decision, Boundary, Files, Tests, Non-Goals, Rollback.

---

## Final Verification Protocol (run after all units, before declaring merge-ready)

1. `git diff --check` — whitespace/conflict clean.
2. Ruff on touched files ONLY: `git diff --name-only main..HEAD -- '*.py' | xargs ruff check` (no repo-wide ruff).
3. Targeted tests: the five diff-relevant test files + the new live-path test + the two flipped tests.
3. Targeted tests (exact files): `test_runtime_decision_frame.py`, `test_subagent_l2_contract.py`, `test_subagent_runtime_truth.py` (U1); `test_memory_consolidation_truth.py` (U2); the new `test_subagent_delegation_live_path.py` (U3); `test_target_catalog_extraction.py` (U4); `test_safe_metadata_projector.py` (U5).
4. Architecture boundary tests: `test_subagent_runtime_truth.py`, `test_memory_consolidation_truth.py`, `test_target_catalog_extraction.py`.
5. Full suite: `.venv/bin/python -m pytest -q tests/ -rx --tb=short` (expect 0 failed; xfail/skip counts may shift only by the new test).
6. Import smoke: build `build_phase1_dispatcher()`, assert subagent registry == `{subagent.delegate.v0, subagent.delegate_l0}` (L1 still absent — production routing unchanged).
7. `compound-engineering:ce-code-review` then gstack `/review` for independent post-fix review.

**Stop conditions (revised — item 10):**
- Zero unhandled **Blocker / High**.
- Every **Medium** is in one of three states: (a) fixed, (b) downgraded with evidence, or (c) explicitly accepted/deferred WITH owner + exit-condition + next-step recorded (in Deferred Architecture Debt or Open Questions).
- SubAgent **current runtime fact**, **declared target architecture**, and **confirmed diagnosis** are clearly separated everywhere in the plan and in the corrected source comments.
- Memory **frozen / reachable** four-state distinction is accurate AND reachability is proven dynamically (U2).
- Safe-metadata: confirmed high-value boundaries migrated (D1/D3 ownership-DRY) OR formed into an evidence-backed deferred (D2 leak-gate resolved either way).
- Full test suite: **0 failed**.
- CE review + gstack review surface **no new unhandled factual conflict**.
- The branch reaches **merge-ready for the current SoT truth-alignment + repair scope only** — NOT a claim that the SubAgent architecture is complete (V0 wiring + dead-L1-block removal remain deferred debt).

**Hard constraints (every unit):** no V0 production wiring; no deleting L1/L2 handlers; no deleting frozen memory modules; no changing core production routing (the `core.py` L1-attempt block stays); no batch/global safe_metadata replace; no push; never touch/restore/commit `AGENTS.md`; never commit `.claude/settings.json`, `graphify-out/`, `agent_log*`; no broad cleanup; no repo-wide ruff; no deleting code on a frozen/deferred label alone; no L1/L2/frozen-memory compat removal without full reachability + replacement proof.

---

## Decisions (resolved with user)

- **U1 `subagent_level` representation — RESOLVED: option (a), no schema change; value FROZEN to `"inline_local_fallback"`.** The four runtime concepts (registered=V0, requested=L1, executed-live=inline-local fallback, fallback=inline-local) are NOT forced into one bare string. `subagent_level` is set to the frozen value `"inline_local_fallback"` with a corrected docstring; the registered/requested distinction is carried by the already-corrected `BranchPointState["subagent.delegate"].execution_path`. No new field, no schema edit (value domain is free-form `str`, not serialized, only two test consumers — see U1). Option (b), a minimal additive field, was considered and declined for this branch.
- **`is_capability_complete()` allowed set — NOT touched this branch (item 4).** U1 may set `evidence_level=FAKE_LOCAL_USER_PATH` (honest current fact) but must not remove it from the capability-complete allowed set; that is capability-semantics behavior change, recorded as a deferred decision (Open Questions).

## Deferred architecture debt (explicit, not silently parked)

This branch is **merge-ready for the current SoT truth-alignment + repair scope only** — it does NOT claim the SubAgent architecture is complete. The following debts are deferred by design, each with owner / current state / target state / exit condition / next step / why-not-this-round:

| # | Debt | Owner | Current state | Target state | Exit condition | Next step | Why not this round |
|---|---|---|---|---|---|---|---|
| D-1 | **V0 registered but not production-routed** | WP-F follow-up branch | `phase1_hook` registers `SUBAGENT_DELEGATE_V0` (full bounded executor); `core.py` never routes to it | `core` routes `SUBAGENT_DELEGATE_V0` as the product path | WP-F option chosen + V0 wiring landed with evidence/observer/memory/tool/policy parity + rollback | Execute WP-F recommendation in a separate authorized branch | Requires changing production routing — out of truth-alignment scope; needs explicit authorization |
| D-2 | **`core.py:2002-2039` L1-attempt / `ToolRuntimeMediator` dormant block** | WP-F follow-up branch | builds a `ToolRuntimeMediator` every delegation, then `get_handler(SUBAGENT_DELEGATE_L1)` returns None → block unreachable, mediator build wasted per call | block removed (or replaced by V0 routing) | WP-F target chosen; removal gated on dynamic-registration check + test/demo callers + observability + rollback review | Remove/replace as part of V0 wiring branch | User decision: do NOT touch `core.py` routing or delete the block this round |
| D-3 | **inline-local fallback is the current live path** | WP-F follow-up branch | live CLI/NL delegation = L1-attempt → direct inline-local (`local_fake`) fallback | V0 is the live path; inline-local becomes a true fallback only | V0 wiring complete and routed | Wire V0 (D-1); inline-local demotes to fallback | This round only *documents* the live fact (WP-A); changing what executes is wiring, deferred |
| D-4 | **V0 production wiring pending** | WP-F (decision) → follow-up branch (execution) | V0 contract-verified but unwired | V0 wired + L1 attempt retired | WP-F decision recorded (U6) → authorized wiring branch passes parity + rollback gates | U6 produces the recommendation this round; wiring is the next branch | Decision-only this round per hard constraints; no wiring |
| D-5 | **L1 attempt block exit / L1 handler retirement** | WP-F follow-up branch | L1 never registered; attempt block dead; L1 handler retained as legacy/test/demo compat | L1 attempt removed; L1 handler retired after reachability proof | WP-F picks target AND L1 reachability + replacement proof complete | Gated behind D-1/D-4 completion | Removing L1 needs the V0 migration done first and a full reachability/replacement proof — not available this round |

Rationale (user decision): this branch aligns structured fields, comments, tests, roadmap, and audit-delta to the **current runtime fact** only. Removing the dead block, retiring L1, or changing routing is architecture work gated on WP-F — not truth-alignment. These debts are real (dead + wasteful, not merely dormant) and are owned by the WP-F follow-up, recorded here rather than silently parked.

---

## Open Questions (resolve at execution, do not pre-settle)

- **`is_capability_complete()` honesty (raised in review):** after U1's `evidence_level → FAKE_LOCAL_USER_PATH` swap, the SoT still reports `is_capability_complete()==True` for a fake-local path (FAKE_LOCAL_USER_PATH is in the allowed set). The swap preserves current behavior by design (minimal diff), but is "a fake-local path is capability-complete" actually the honest semantic? If not, removing FAKE_LOCAL_USER_PATH from the allowed set is a *behavior* change beyond truth-alignment — decide separately, do not fold into U1's value swap.
- **U5 scope per branch:** how many trust boundaries land this branch vs deferred — gated on proven-duplicate/leak evidence per site, decided at implementation. The `evidence_persistence`/`loop` truncate-without-mask boundary (D2) escalates to P1 if a secret is reachable from a non-sensitive path.

---

## Sources & Research

- Read-only cross-audit 2026-06-12 (this session): full report with file:line evidence for H1/H2/M1/M2/M3 and the frozen/deferred decision matrix.
- Verified runtime: `core.py:1973-2046`, `phase1_hook.py:160-186`, `subagent_inline.py:37-97`, `runtime_decision_frame.py:22-96, 285-300, 455-531, 805-809`, `target_catalog.py:282-298`, `safe_metadata.py`, `evidence.py:408-434, 697-705`.
- Registration smoke (this session): `build_phase1_dispatcher()` → `['subagent.delegate.v0','subagent.delegate_l0']` (L1 absent).
- Existing tests: `test_subagent_runtime_truth.py`, `test_memory_consolidation_truth.py`, `test_target_catalog_extraction.py`, `test_safe_metadata_projector.py`, `test_v6_drift_addendum_boundary.py` (37 passed, 1.4s this session).

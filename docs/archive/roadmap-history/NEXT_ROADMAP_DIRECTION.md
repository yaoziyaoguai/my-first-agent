# Next Roadmap Direction Recommendation (post-S-series closure)

> Status: **R-series COMPLETED (2026-06-21).** The R-series recommendation below was
> executed and clean-closed; see `docs/archive/r-series-real-world-validation/`. This
> doc's R-series analysis is retained as historical evidence. The **current next step**
> is building a Product Capability Map and selecting the next module to productionize
> (Memory / Scheduler / MCP / SubAgent / Product polish). Do NOT re-do R-series.
>
> Scope rule: this is discovery + architecture reasoning. No code, no tests, no new
> stage docs beyond this recommendation. The user must explicitly authorize any next
> series before baseline/goal/gap are created.

## 1. Current Post-S Baseline

S1-S5 + S_FINAL are complete and archived under `docs/history/`. Together they
delivered a **stable, governed, auditable, durable agent runtime *kernel***:

- **L1 runtime spine** — one `chat()` loop; FakeProvider/RealProvider share the same
  spine via `build_model_provider_from_env()`; AST-enforced same-spine guard;
  5-class acceptance gate (runtime / extension / evidence-fidelity / durability /
  debt).
- **L2 context/memory/state/checkpoint** — task-scoped memory boundary; checkpoint
  save/load (the state restoration source); **durable JSONL task ledger** (S5) with
  redaction + crash-survivable read; memory v0 contracts exist but **activation is
  dormant**.
- **L3 tools/policy/evidence** — governed tool-contract + bypass detection; evidence
  recorder (redaction wired into legacy mediator preview + `record_evidence` metadata
  per S_FINAL TD-012); replay chain; evidence verifier (cross-kind duplicate-ref
  detection per S_FINAL TD-013); audit observability; MCP as a controlled tool source.
- **L4 task orchestration** — governed task state model; orchestration skeleton;
  progress review; durable recovery E2E; durability acceptance signal.
- **L5 extension boundary** — governed Skill; governed MCP (controlled, default-off);
  read-only / parent-mediated SubAgent; **dormant Scheduler**.

Quality state: full pytest **4946 passed**, full-suite `ruff check .` **green (0)**,
S1-S5 targeted gates green.

**The single most important fact about this baseline:** everything is validated
**fake/local + structural**. The real-provider path exists (factory +
`AgentProviderConfig` + opt-in key-safe smoke harnesses in the S2/S4 reference-task
tests) but there is **no live multi-step real-task success evidence** — every stage
so far (S2/S4/S5) explicitly made real-provider live success a non-goal / opt-in
smoke only. The kernel is structurally proven; it is **not yet real-world proven**.

## 2. Remaining Debt and Deferred Scope

Live `TECH_DEBT.md` (only unresolved/deferred items remain after S_FINAL closed
TD-003/007/012/013):

- **TD-002** — planner/compress legacy `ProviderBackedClient` facade (cosmetic; carry-
  forward; not safely fixable in closure).
- **TD-008** — Scheduler productionization / main-loop activation (**dormant** by
  design).
- **TD-009** — full MCP ecosystem / multi-server orchestration (**deferred** scope).
- **TD-010** — writable / non-mediated / multi-agent SubAgent (**deferred** scope).

TD-008/009/010 are **scope boundaries deliberately deferred** — they represent
*activation* of high-autonomy capabilities. They are the natural raw material for
future major directions, but each one **activates** a capability the kernel currently
keeps dormant on purpose.

## 3. Candidate Directions

| # | Direction | Builds on | Unlocks | Adds |
|---|---|---|---|---|
| A | **Real-world validation / grounded tasks** | full L1-L5 kernel + real-provider factory | proves the kernel does useful real work; de-risks all later autonomy | real-task harness, non-determinism handling (no new autonomy) |
| B | Product entry / CLI / operator workflow | runtime kernel | usability/onboarding | UX surface |
| C | Memory / context engineering | L2 memory boundary + ledger | persistent cross-session memory | memory activation (currently dormant) |
| D | Scheduler productionization (TD-008) | L4 orchestration + ActionScheduler skeleton | auto action-planning | main-loop activation (autonomy) |
| E | Full MCP ecosystem (TD-009) | governed MCP tool source | multi-server orchestration | external-dependency complexity |
| F | Writable / multi-agent SubAgent (TD-010) | read-only SubAgent | delegation/collaboration | highest autonomy risk |
| G | Provider / real-API robustness | real-provider factory | resilience | folded into A in practice |
| H | Packaging / release / docs / cookbook | whole project | distributability | release engineering |

## 4. Dependency Analysis (ordered, not by interest)

The ordering follows **what de-risks what**, not preference:

1. **Real-world validation (A) must come first.** The kernel is fake/local-proven.
   Every high-autonomy direction (C memory, D scheduler, F multi-agent, E full MCP)
   stacks non-determinism and external behaviour onto a kernel whose *real* behaviour
   is unverified. Activating autonomy on an unproven-real base is the highest-risk
   sequencing error available. A is also the **lowest kernel-risk** major direction:
   it adds no new autonomous capability, so it cannot destabilise the S-series stable
   kernel — it only *exercises* it against reality.
2. **Product/operator workflow (B) and Memory (C) come after A.** Both become
   meaningful and *validatable* only once the runtime does real multi-turn work: a
   product surface for an unproven-real kernel, and a memory activated over fake/local
   turns, both have limited value and are hard to validate honestly.
3. **Scheduler (D), full MCP (E), multi-agent (F) come last.** These are the deferred
   autonomy boundaries. Each is a legitimate *future major direction in its own
   right*, but each depends on (a) a real-validated kernel and (b) a stable real
   execution base. They should not be the *next* major step.

**Implication:** the dependency graph funnels everything through real-world validation
first. That makes A the unambiguous next major direction.

## 5. Recommended Major Direction — R-series (Real-world Grounded Validation)

**Naming:** **R-series** — *R* for **Real / Real-world / Reality**. S-series was the
**S**tructural series (build + govern + audit + make durable the kernel). R-series is
the **R**eality series: graduate the kernel from *structurally proven (fake/local)* to
*real-world proven (real LLM, real grounded tasks)*. It is the missing pillar —
"S built the machine; R proves it actually works in the world."

**Big-version goal:** prove the governed runtime kernel **completes useful real
multi-step tasks** (read / write / verify files; run checks) **via a real provider
end-to-end**, with the same-spine, governance, audit/replay, and durability guarantees
**holding under real-LLM non-determinism** — key-safe, observable, and with **no
regression** to the fake/local suite.

**Non-goals (held firmly):**
- No activation of memory (C), Scheduler (D), full MCP (E), or writable/multi-agent
  SubAgent (F) — R is **validation, not expansion**.
- No UI/demo/commercial packaging (H).
- No new runtime kernel or second spine; R reuses the S-series kernel as-is.
- No raw-secret persistence; real-provider use stays **key-safe** (keys in gitignored
  config, never printed/staged/committed).

**Success criteria:**
- A **key-safe, opt-in** real-provider grounded task suite executes real multi-step
  tasks to completion (not just single-call smoke).
- **Same-spine holds under real execution** — Fake and Real share the governed path
  for real tool calls, proven behaviourally (not only by AST guard).
- **Governed evidence + durable ledger + checkpoint recovery** remain coherent under
  real non-determinism (retries, malformed model output, tool-use/tool-result pairing,
  truncation).
- Real-LLM edge cases are handled without kernel breakage; any kernel gap found is
  fixed under TDD with the fake/local suite staying green.
- Full fake/local pytest stays green; the real suite is opt-in (never blocks CI
  without real keys).

**Suggested stage granularity (bigger than S — do NOT fragment into S-style 11-gap
loops):** roughly 3-4 sub-stages, e.g.:
- **R1** — real-provider task harness + non-determinism spike.
- **R2** — grounded task suite (deterministic-ish real tasks with assertions on
  outcome, not exact tokens).
- **R3** — real non-determinism hardening (retry/pairing/malformed-output robustness).
- **R4** — real-validation release + closure record.

**First documents:** **start with a spike/audit, not a goal.** Because the kernel was
deliberately built fake/local-first, its real-world failure modes are *unknown* —
freezing a goal before discovering them is premature. Recommended first artifact:
`R_REAL_PROVIDER_SPIKE.md` (time-boxed: can the current factory + tool path complete
*one* real grounded task? what breaks?). The spike's findings then feed
`R_BASELINE_STATUS.md` → `R_GOAL.md` → `R_GAP.md`. So: **spike → baseline → goal →
gap** (baseline/goal/gap are needed, but only after the spike de-risks them).

## 6. Backup Direction — M-series (Memory / Context Engineering)

If real-world validation is **environment-blocked** (no real API key access / budget),
the backup is **M-series** — activate memory v0 + mature context compression, building
on the L2 boundary + durable ledger the kernel already established.

Why backup, not primary: memory is honestly validatable only over **real multi-turn
runs**. Building/activating memory fake/local-first has real but limited value, and M
would *itself* eventually need R-style real validation. So M is the right second
major direction (or first only if R is blocked), gated behind R by dependency.

## 7. Directions Not Recommended Now

- **Scheduler productionization (TD-008 / D):** auto action-planning on a kernel whose
  real-world behaviour is unproven. Value is unprovable without real tasks, and
  main-loop activation is an autonomy risk on an unvalidated base. **Evidence:** the
  Scheduler is AST-guarded dormant (`test_architecture_boundaries.py::test_cr1_*`);
  activating it before R inverts the dependency order.
- **Full MCP ecosystem (TD-009 / E):** multi-server orchestration adds external-
  dependency + reachability complexity before the kernel is real-validated. Needs R
  first.
- **Writable / multi-agent SubAgent (TD-010 / F):** the **highest** autonomy risk;
  multi-agent collaboration on an unproven-real kernel is the riskiest sequencing
  available. Needs R (+ arguably memory) first.
- **Memory activation as the *first* major direction (C):** valid direction, but
  secondary to R for the dependency reason above (this is why it is the *backup*, not
  primary).
- **UI / demo / commercial packaging (H):** **premature.** Packaging/demos for an
  unproven-real kernel oversells reality. Do after R (+ possibly B product workflow).
- **Standalone provider/API robustness (G):** real, but **folded into R** — R
  inherently exercises and hardens the real provider path; a separate G-series would
  duplicate R's core.

## 8. Proposed Next Documents

In order (only on explicit user authorization to open R-series):

1. ~~`R_REAL_PROVIDER_SPIKE.md`~~ — superseded (R-series done; see archive).
2. ~~`R_BASELINE_STATUS.md`~~ — superseded (R-series trial docs serve as the baseline).
3. `docs/archive/r-series-real-world-validation/R_GOAL.md` — R-series goal (COMPLETED).
4. `docs/archive/r-series-real-world-validation/R_GAP.md` — R gap backlog (COMPLETED).

Naming is a suggestion; the **spike-first** ordering and the **real-validation-first**
dependency are the load-bearing recommendations.

## 9. Verification Performed

- Confirmed S-series roadmap mainline is closed: `docs/current/` holds only
  `S_ROADMAP.md` + `TECH_DEBT.md` (+ this recommendation); S1-S5 + S_FINAL archived
  under `docs/history/`.
- Confirmed live debt = TD-002 / TD-008 / TD-009 / TD-010 only (TD-003/007/012/013
  resolved in S_FINAL).
- graphify-grounded the real-provider path (`build_model_provider_from_env` /
  `build_model_provider` / `AgentProviderConfig` / `load_agent_provider_config`) and
  the opt-in key-safe smoke harnesses (`test_s2_reference_task_real_provider_key_safe_context_smoke`,
  `test_s4_reference_task_real_provider_audit_key_path_smoke`) — confirming the real
  path exists structurally but has **no live multi-step success evidence**.
- graphify-grounded extension dormancy (ActionScheduler, MemoryRuntime/extraction,
  `register_mcp_tools`, SubAgent delegation) — confirming TD-008/009/010 + memory are
  dormant/controlled, i.e. activating them is a real scope change, not a flip.
- No code/tests changed; only this document is added.

## 10. Final Recommendation

**Open the R-series (Real-world Grounded Validation) as the next major roadmap
direction, starting with a time-boxed real-provider spike before a frozen goal.** It
is the dependency-funnel for every later autonomy direction, it is the lowest-risk
move for the stable S-series kernel (validation, not expansion), and it closes the
one gap the entire S-series deliberately left open: the kernel is structurally proven
but not yet real-world proven. Everything else (product, memory, scheduler, MCP,
multi-agent, packaging) is more valuable and safer *after* R. Backup: M-series
(memory/context) only if R is environment-blocked. **The S-series roadmap mainline
remains closed; there is no active S stage, and this recommendation does not open
S6.**

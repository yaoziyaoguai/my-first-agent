# 019 Portable Automation Control Core — Execution Log

## 2026-08-28 — Design and plan freeze

- User approved the redesigned platform-neutral architecture.
- Frozen source: `docs/superpowers/specs/2026-08-28-durable-background-runs-design.md`.
- Replaced the stale macOS-first plan with:
  - `docs/superpowers/plans/2026-08-28-019-portable-durable-automations-core.md`
  - `docs/superpowers/plans/2026-08-28-019-macos-host-profile.md`
- Portable core owns schemas, pure scheduling, controller semantics, Runtime/ToolRuntime authority
  integration and typed ports. It imports no concrete OS persistence/workspace/process/wake,
  Seatbelt or Playwright backend.
- Host repository/workspace/supervisor/executor/wake/sandbox/browser implementations are
  independently qualified. Core status alone does not claim durable local operation.
- Closed two implementation ambiguities before product code:
  - background token ceilings are input `1..100_000`, output `1..20_000`;
  - definition identity uses `definition_body_digest -> grant_digest -> definition_digest`,
    avoiding circular hashing without weakening the grant.

## 2026-08-28 — Portable core Task 1

### Red 1

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/automation/test_contracts.py tests/automation/test_schedule.py -rx
```

Result: expected collection failure, 2 errors, because `agent.automation` did not exist.

### Green 1

- Added immutable schedule, budget, definition-body, grant, final-definition, occurrence,
  summary, record, snapshot and tombstone contracts.
- Added pure canonical UTC resolution and deterministic occurrence identity.
- Initial focused result: 28 tests executed; one test-fixture digest reset error exposed and was
  corrected without changing product behavior.

### Red 2

- Added needs-human scheduling pause and 32 non-terminal snapshot boundary tests.
- Result: expected 2 behavior failures (`DID NOT RAISE`), proving both guards were absent.

### Green 2

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/automation/test_contracts.py tests/automation/test_schedule.py -rx
.venv/bin/ruff check agent/automation/contracts.py agent/automation/schedule.py tests/automation
git diff --check
```

Result: `31 passed`; Ruff and diff-check Green.

### Current state

- `next_task=2-repository-controller`
- No full-suite, materialized, U2A or host-profile claim has been made.
- No commit or push performed.

## 2026-08-28 — Portable core Task 2

### Red / Green

- Added strict canonical snapshot codec and a 4 MiB platform-neutral repository contract.
- Added deterministic nonblocking lease, CAS, conflict and before/after-commit fault shapes.
- Added the sole `AutomationController` mutation owner for proposal/update approval,
  pause/resume/cancel, exact claim, dispatch/running and terminal/needs-human outcomes.
- Verified active update cutover preserves the immutable old-revision claim while future claims
  bind the new definition; stale draft approval and replacement fencing tokens fail closed.
- Deferred purge mutations to Task 9, where they can bind Task 3's real content-free ownership
  manifest instead of creating a duplicate placeholder contract.

Command:

```bash
.venv/bin/python -m pytest -q \
  tests/automation/test_contracts.py tests/automation/test_schedule.py \
  tests/automation/test_store.py tests/automation/test_controller.py \
  tests/automation/test_controller_races.py -rx
.venv/bin/ruff check agent/automation tests/automation
git diff --check
```

Result: `49 passed`; Ruff and diff-check Green.

### Current state

- `next_task=3-owned-workspace-port`
- No full-suite, materialized, U2A or host-profile claim has been made.
- No commit or push performed.

## 2026-08-28 — Portable core Task 3

- Added the platform-neutral `OwnedWorkspaceRepository` protocol, canonical manifest/diff value
  objects and a deterministic metadata-only adapter. Portable code performs no host filesystem
  traversal or deletion.
- Source preview/capture rejects count, byte, file, path, private-name, symlink/unsupported-node,
  root-identity and content drift before admitting an owned snapshot.
- Each occurrence materializes a distinct source-bound ownership identity. Terminal capture
  validates a sorted bounded diff and governed artifact totals before any object is admitted.
- Exact cleanup removes only matching 019-owned identities; replacement is `cleanup_unknown`;
  governed external artifacts are unlinked without deletion.
- Adversarial Reds closed noncanonical public manifest entries and duplicate artifact IDs that
  could otherwise have partially overwritten one another.

Commands:

```bash
.venv/bin/python -m pytest -q \
  tests/automation/test_store.py tests/automation/test_source_snapshot.py \
  tests/automation/test_occurrence_workspace.py tests/automation/test_owned_cleanup.py -rx
.venv/bin/ruff check agent/automation/workspace.py \
  tests/automation/test_source_snapshot.py \
  tests/automation/test_occurrence_workspace.py \
  tests/automation/test_owned_cleanup.py
git diff --check
```

Results: `28 passed`; Ruff and diff-check Green.

### Current state

- `next_task=4-management-lifecycle`
- No full-suite, materialized, U2A or host-profile claim has been made.
- No commit or push performed.

## 2026-08-28 — Portable core Task 4

- Added seven-section human-first activation previews whose digest binds the exact draft,
  source manifest and qualification report without secret values or host paths.
- Added an abstract wake adapter protocol and deterministic install/readback adapter; no OS wake
  implementation exists in the portable core.
- Activation now revalidates preview/source, captures one idempotent immutable snapshot, installs
  wake before CAS, and preserves the proposal on failed/unknown install.
- Install-success/CAS-conflict is explicit; retry readbacks the same installed projection,
  performs no duplicate install and reuses the exact source snapshot.
- Added bounded list/show/open projections. `open` returns only an opaque Runtime checkpoint
  handoff and performs no Runtime mutation or approval.

Commands:

```bash
.venv/bin/python -m pytest -q tests/automation -rx
.venv/bin/ruff check agent/automation tests/automation
git diff --check
```

Results: `80 passed`; Ruff and diff-check Green.

### Current state

- `next_task=5-runtime-background-binding`
- No full-suite, materialized, U2A or host-profile claim has been made.
- No commit or push performed.

## 2026-08-29 — Portable core Task 5

- Added one immutable `BackgroundOccurrenceBindingV1` to the Runtime checkpoint and kept
  ordinary scheduler identities byte-for-byte unchanged when no binding is supplied.
- Added the background-only provider boundary: durable intent before send, normalized typed
  response before reduction, no resend after an unknown send outcome, and exact explicit
  abandonment through `AgentRuntime.run_turn`.
- Checkpoint schema v8 round-trips the occurrence binding, provider intent, persisted response
  and cumulative model/token counters; unknown fields and digest mutations fail closed.
- Crash-window tests cover pre-intent failure, intent-only restart, durable-response restart,
  terminal replay and wrong-occurrence abandonment. The provider is called at most once for an
  occurrence call index.
- No second scheduler/model/tool loop was added; `ScheduledOccurrenceCaller.run_once` remains
  the only external Runtime call seam.

Commands:

```bash
.venv/bin/python -m pytest -q \
  tests/automation/test_model_call_recovery.py \
  tests/automation/test_runtime_binding.py -rx
.venv/bin/python -m pytest -q \
  tests/continuity/test_checkpoint_v4.py \
  tests/continuity/test_sandbox_checkpoint.py -rx
.venv/bin/python -m pytest -q \
  tests/automation tests/kernel/test_runtime_errors.py \
  tests/continuity/test_verified_done.py \
  tests/kernel/test_effect_ordering.py -rx
.venv/bin/ruff check <Task-5 touched Python files>
git diff --check
```

Results: `16 passed`, `20 passed`, then `148 passed`; Ruff and diff-check Green.

### Current state

- `next_task=6-background-tool-authority`
- No full-suite, materialized, U2A or host-profile claim has been made.
- No commit or push performed.

## 2026-08-29 — Portable core Task 6

- Added a read-only `AutomationClaimVerifier`; `KernelToolRuntime` validates the exact active
  claim at both prepare and immediately before callable invocation. Repository failure,
  cancellation, expiry or any claim/capability/definition/grant drift fails closed.
- Added ephemeral `BackgroundExecutionAuthorityV1` and action-scoped
  `BackgroundActionAuthorityV1`. Raw claim capability remains outside Runtime checkpoints,
  intents, events and receipts.
- Admitted only exact confined, network-off sandbox execution and public-read browser observe.
  All broader classes retain the ordinary approval path. Background sandbox success uses a
  distinct receipt and never fabricates an ordinary `SandboxAuthorityLeaseV1`.
- Added durable total-tool, sandbox-command and browser-action counters to the Runtime
  `EXECUTING` transition and checkpoint v8. Restart round-trip, counter reuse, wrong ordinal and
  prepare-to-invoke cancel races fail closed.
- Static checks retained one provider generation and one `ToolRuntime.invoke` call site inside
  the single `AgentRuntime` loop; ToolRuntime does not import `AutomationController`.

Commands:

```bash
.venv/bin/python -m pytest -q \
  tests/automation tests/continuity/test_checkpoint_v4.py \
  tests/kernel/test_runtime_approval.py tests/sandbox/test_tools.py \
  tests/browser/test_tool_authority.py -rx
.venv/bin/ruff check <Task-6 touched Python files>
git diff --check
```

Results: `140 passed`; Ruff, diff-check and static single-owner checks Green.

### Current state

- `next_task=7-ready-start-reconciler`
- No full-suite, materialized, U2A or host-profile claim has been made.
- No commit or push performed.

## 2026-08-29 — Portable core Task 7

- Added a platform-neutral READY/start/result protocol. `run_occurrence_child` announces READY,
  consumes one opaque start permit, acknowledges it, then invokes the injected occurrence
  executor exactly once. The supervisor owns no Runtime, provider, tool or AutomationStore.
- Added a one-shot reconciler that reads the clock once, orders candidates by
  `(scheduled_for_utc, automation_id)`, handles at most one occurrence and never sleeps.
  `not_due` and misfire paths exit before execution capability, checkpoint, workspace,
  supervisor or executor work.
- Durable ordering is `CLAIMED -> READY -> DISPATCHED -> start acknowledgement -> RUNNING`.
  Fault tests cover claim/checkpoint creation, both sides of dispatch/running CAS, unknown
  start permit, child result and both sides of terminal CAS.
- Restart never blindly redispatches `DISPATCHED` or reruns `RUNNING`. The executor's read-only
  recovery port either returns the exact checkpoint-bound result or produces a closed unknown;
  known terminal replay captures the same diff/artifacts idempotently and keeps execution count
  unchanged.
- A cancel committed while still `CLAIMED` terminalizes with zero child execution. Terminal
  workspace capture and exact cleanup precede terminal summary mutation; unknown capture or
  cleanup pauses instead of claiming success.
- This is portable protocol evidence only. It does not claim a concrete OS process, hard
  deadline, host persistence or unattended execution qualification; those remain in later
  portable composition and macOS host-profile stages.

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/automation tests/scheduler/test_caller.py \
  tests/continuity/test_checkpoint_v4.py -rx
.venv/bin/ruff check agent/automation agent/scheduler/caller.py \
  tests/automation tests/scheduler/test_caller.py \
  tests/continuity/test_checkpoint_v4.py
git diff --check
```

Result: `153 passed`; Ruff, diff-check and portable no-loop/no-owner-token scan Green.

### Current state

- `next_task=8-portable-composition-cli`
- No full-suite, materialized, U2A or host-profile claim has been made.
- No commit or push performed.

## 2026-08-29 — Portable core Task 8

- Added one static `AutomationControlCoreV1` assembly over injected repository, owned-workspace,
  clock, wake, supervisor and execution capabilities. It exposes management/controller/
  reconciler/claim-verifier boundaries but no tool registrations or alternate Runtime loop.
- Executor construction is lazy: not-due and misfire decisions return before the provider
  factory, capability/checkpoint factories, workspace materialization or supervisor. A due run
  with missing provider/supervisor/sandbox/browser capability returns one bounded
  `needs_019_config` reason before claim mutation or effect.
- Cold wake remains optional. Its absence blocks activation/readback that requires wake but does
  not change portable schedule semantics or prevent an explicitly triggered, otherwise-qualified
  due occurrence.
- Added the strict public `ReconcileAutomationsV1` decoder. Its canonical JSON has only
  `schema_version` and optional opaque `delivery_id`; locator/task/provider/credential/tool and
  duplicate/extra fields fail closed.
- Added the thin `first-agent-schedule` management/reconcile CLI and changed the installed entry
  point to `agent.automation.cli:main`. The parser has no old raw `--state-root`, workspace,
  message or provider fallback. The existing `ScheduledOccurrenceCaller` remains an internal
  Runtime execution seam and its compatibility tests remain Green.
- AST gates prove concrete host backends are absent from `agent.automation`, only controller.py
  calls repository CAS, there is no timer/sleep loop or management tool registration, and the
  sole Runtime/provider/tool call sites remain in `agent/runtime/loop.py`.

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/automation tests/architecture/test_019_portable_boundary.py \
  tests/architecture/test_single_loop_static.py tests/scheduler/test_caller.py \
  tests/scheduler/test_cli.py tests/cli/test_entrypoint.py -rx
.venv/bin/ruff check agent/automation tests/automation \
  tests/architecture/test_019_portable_boundary.py \
  tests/architecture/test_single_loop_static.py
git diff --check
```

Result: `187 passed`; Ruff and diff-check Green.

### Current state

- `next_task=9-purge-recovery-u1`
- `first-agent-schedule` defaults to a closed `host_profile_unavailable` result until a
  separately qualified host profile binds the real repository/workspace/supervisor/executor.
- No full-suite, materialized, U2A or host-profile claim has been made.
- No commit or push performed.

## 2026-08-29 — Portable core Task 9

- Added a content-free purge ownership manifest covering automation-owned source snapshots,
  occurrence workspaces, retained diffs/artifacts, Runtime checkpoints and governed external
  references. Production management capture binds source objects to the automation identity, so
  two automations using the same source manifest cannot delete one another's snapshot.
- Added the controller-owned `BeginPurge -> StartPurgeObject -> RecordPurgeProgress ->
  FinishPurge` state machine. Definition/task/history content is removed at `PURGE_PENDING`;
  capacity is released only after every exact object is durably confirmed. Cleanup unknown keeps
  the full record and blocks completion.
- Purge reconciliation is one-shot and crash resumable. Each effect is preceded by an exact
  durable object intent; CAS crashes before/after intent, deletion/unlink progress and final
  tombstone converge without recreating private definition authority. Identity replacement is
  cleanup unknown, and governed external artifacts are unlinked without external deletion.
- Added owner-local irreversible preview/confirmation and CLI projection. The preview binds the
  current object manifest and reports owned/external/checkpoint counts without rendering task,
  path, credential or Runtime detail. Confirmed purge leaves only a compact tombstone; the 129th
  tombstone evicts the oldest confirmed tombstone, never a full record.
- Extended `open` handoff with exact automation revision and definition identity. Runtime recovery
  projection validates all five handoff fields against the checkpoint's durable background
  binding, derives owner-visible status only from `ConversationState`, and leaves the automation
  paused until a separate resume.
- Added the authoritative C1-C25 U1 map with 50 unique behavior/mutation nodes and source-level
  existence validation. The full purge fixture proves all six owned object classes are present
  and cleaned through the same bounded port.

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/automation tests/reference/test_019_portable_core.py \
  tests/continuity/test_views.py tests/scheduler \
  tests/architecture/test_019_portable_boundary.py \
  tests/architecture/test_single_loop_static.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/reference/test_017_e3_harness.py tests/reference/test_017_real_runner.py \
  tests/reference/test_017_sandboxed_workspace_execution.py \
  tests/reference/test_018_e3_harness.py \
  tests/reference/test_018_governed_browser_tasks.py \
  tests/reference/test_018_materialized_verifier.py
.venv/bin/ruff check agent/automation agent/runtime/views.py \
  tests/automation tests/reference/test_019_portable_core.py
git diff --check
```

Result: `219 passed` in the portable/Runtime/scheduler/architecture gate and `206 passed` in the
017/018 regression gate; Ruff and diff-check Green.

### Current state

- `next_task=10-portable-core-seal-u2a`
- No full-suite, materialized, U2A or host-profile claim has been made.
- No commit or push performed.

## 2026-08-29 — Portable core Task 10 / U2A delivery closure

- Froze and sealed 364 ordinary overlay entries. The final overlay root is
  `f5569092131ea5f06ca529553b38b830af6b5e3c98a33d133127b688de3a66b4` and the seal SHA-256 is
  `50e88d26b5fa0f3ce3a0fa0daa2e1f2a41279cdef932d5fdf477e8f969fa1041`.
- Corrected the read-only materializer to reconstruct the 009 candidate before applying the
  current delta, preserve inherited verifier controls, verify the new
  `agent.automation.cli:main` console entrypoint and exclude mutable receipt/review/log evidence.
  It does not write `.git/objects`.
- Final source full gate: `2490 passed, 5 skipped` in 267.06 seconds. Final materialized content
  gate: `2487 passed`; four source-only overlay tests skip precisely because the clean tree has no
  `.git` metadata. Ruff and `git diff --check` were Green.
- Bound materialized root
  `743d101a9904ef8f198594a916899b893327664a1452f6525f10adffffc6807a` and wheel SHA-256
  `58fb4892d9706857623290434ea3e325eccf89072833d49744436293a85941ab`.
- Ran the sealed runner from the clean materialized bundle. Three fresh attempts each passed all
  13 journeys, the exact 68-node claim gate and the four Runtime integration nodes; all C1–C25
  values are true. Membership, control-seal and detached attestation all returned exit 0.
- Fresh Spec/Product and Standards/Architecture sections both record `Verdict: PASS` and bind the
  exact seal, verifier, runner, wheel and materialized identities. The portable control core is
  therefore `accepted/delivered` for its stated protocol scope only.
- This receipt qualifies no host profile and does not claim runnable unattended execution on
  macOS, Linux, Windows or cloud hosts.

### Current state

- `019-portable-control-core=accepted/delivered`
- `019-macos-host-profile=not_qualified`
- `next_task=macos-profile-task-1-posix-storage`
- No commit or push performed.

## 2026-08-29 — Post-host-integration portable revalidation

- status: `technical_gates_green_fresh_review_pending`
- The optional host-profile implementation changed the ordinary source after the former portable
  receipt. That earlier receipt/review remains historical evidence only and does not attest the
  current tree.
- Final current-tree source full gate: `2633 passed, 11 skipped` in 274.70 seconds. The prior Red
  was the exact product-package allowlist omitting the new `agent.automation_hosts` package; after
  adding the concrete files and package, the full `tests/architecture` gate passed `64` nodes and
  the serial source full rerun exited zero.
- Current portable seal: 405 exact entries, overlay root
  `784efb91743a44301695e067112fa6c0949cb2da50b1c16d5086150d09e8de29`, seal SHA-256
  `3a7700502e84bb00c2e7b64ab9d096ad20d62b4efa961def631cb6ca3878f5f0`.
- Current portable materialized gate: `2630 passed`; materialized root
  `38b9aabd2b25b3b47110c76c4db1f0de669184dae6943ba2c18fc4932abeea45`; wheel SHA-256
  `698114eb3fc49353c37083bb22f487e9b2ba181d93614c15edc32c1b1d58c675`.
- A provisional receipt was written only under `/private/tmp`. Its three fresh attempts passed
  every J1–J13 subcheck, all C1–C25 claims, the 68-node claim gate and four Runtime nodes; the four
  repository/workspace/supervisor/executor identity sets were each fresh. It was deliberately not
  copied into `docs/acceptance`, because the existing independent review binds the former identity.
- Full Ruff was Green with the explicitly forbidden untracked `tui/` root excluded; touched Ruff,
  `git diff --check`, membership and control-seal all exited zero.

### Current state

- `019-portable-control-core=current-technical-evidence-green`
- `019-portable-control-core-promotion=fresh-independent-review-and-formal-receipt-pending`
- No commit or push performed.

## 2026-08-29 — Post-audit authority closure

- Snapshot decode now reconstructs `BackgroundAuthorityGrantV1` through its canonical factory and
  rejects persisted grants whose sandbox/browser flags conflict with the decoded budgets or policy
  bindings, even when every stored digest was recomputed consistently.
- The controller now applies a closed safe-terminal/claim-phase matrix. `COMPLETED`, `FAILED` and
  `WORKER_DEADLINE` cannot clear a merely `CLAIMED` occurrence; legitimate pre-start
  misfire/supersede/cancel and Runtime-owned `RUNNING` terminal outcomes remain valid. Unresolved
  needs-human/unknown summaries still preserve the exact claim and pause as before.
- Portable J7 now crosses the public `CLAIMED -> DISPATCHED -> RUNNING` transitions before recording
  the old revision's completion, so the cutover oracle no longer proves itself through an illegal
  direct completion.
- Focused 019 gate excluding the two real nested-Seatbelt probes: `436 passed, 1 skipped`.
  Full Ruff (with the forbidden untracked `tui/` root excluded) and `git diff --check` passed.
- The complete source suite finished with `2645 passed, 1 skipped, 2 failed` in 301.08 seconds. Both
  failures are the real `sandbox-exec` tests in
  `tests/automation_hosts/test_background_seatbelt.py`; the managed Codex sandbox terminated the
  nested Seatbelt process with return code `-6`. They are not counted as Green and must be rerun in
  an ordinary macOS Terminal before resealing.

### Current state

- `019-audit-blockers=code_fixed-focused-green`
- `019-source-full=blocked-by-two-nested-seatbelt-host-tests`
- `next_task=ordinary-terminal-seatbelt-rerun-then-reseal-materialize-u2`
- No commit or push performed.

## 2026-08-29 — Post-audit Seatbelt closure

- The two background Seatbelt failures were product-policy failures, not accepted as environment
  noise. A default-deny profile allowed process/runtime roots but omitted read access to the root
  directory object required while macOS starts the qualified system executable, causing `SIGABRT`.
- The profile now allows only `file-read*` on the exact `literal "/"`; it still forbids the broad
  `subpath "/"`. The real probe reads an owned workspace file and continues to deny a sibling
  owner file, so the fix does not widen filesystem authority to the root tree.
- Exact real Seatbelt gate: `7 passed`. Full current source gate:
  `2647 passed, 1 skipped` in 310.55 seconds. Full Ruff (with the forbidden untracked `tui/` root
  excluded), touched Ruff and `git diff --check` are Green.

### Current state

- `019-audit-blockers=closed`
- `019-source-full=green`
- `next_task=reseal-materialize-u2-fresh-review`
- No commit or push performed.

## 2026-08-29 — Final portable delivery closure

- status: `accepted/delivered`
- Final source gate on the current ordinary tree: `2654 passed, 1 skipped` in 308.86 seconds;
  full Ruff (excluding the forbidden untracked `tui/` root) and `git diff --check` passed.
- Final portable seal has 405 exact entries. Overlay root:
  `2a6d5b8981a2b0a6819a74dc84fa05bb98e6540371be8bb573647e0720678bda`; seal SHA-256:
  `01ef8afe1e3c8c8c8ca63d5d496447cc35251296c5e86bc20a181ec28f0e99a1`.
- Clean materialization passed `2650` tests. Materialized root:
  `97060d5a2eb997640b9c29310e6f525b6a5e2fab16aee147830d5cd83a36e5fc`; wheel SHA-256:
  `aa633f3581c51a0ce196c7ca2d149a0c0d52a8ec73dd8608705be97b30381614`.
- The sealed materialized runner completed three fresh attempts. Every attempt passed all 13
  journeys and all C1–C25 claims. Membership, control-seal and detached U2A attestation each
  returned exit 0.
- The final receipt SHA-256 is
  `aea2023b5708d10846fcf5ba6a37119fc22f1f5d418edb37b07b969f46922d40`.

### Current state

- `019-portable-control-core=accepted/delivered`
- `next_task=none`
- No commit or push performed.

## 2026-08-29 — Git 交付前最终重封

- 提交前的 staged diff 检查发现 4 个新文件含多余 EOF 空行；修正后重新执行完整
  source gate，结果为 `2654 passed, 1 skipped`。旧 receipt 按逐字身份规则作废，未复用。
- 最终 portable seal：405 entries，overlay root
  `79859f7c57c00da2ca73daee2737842b21f6430d70847b805d8acc693fde455f`，seal SHA-256
  `f9bf90ad0df0ced05ff4394acef04b563ae136669569a994bf6f3c38a83e68d1`。
- clean materialized gate：`2650 tests`；materialized root
  `05ba50896ea1e40af28407e9e2593e367b50fb1eccfd12626cccf2f7cb6940a4`，wheel SHA-256
  `d1b20b328bfa4d828332c26d94a8083056d895f5361e790a1ebc63973719b5e5`。
- sealed U2A runner 重新完成 3 次 fresh attempt；每次 J1–J13 与 C1–C25 全 true。
  membership、control-seal、attestation 均 exit 0；receipt SHA-256
  `6a4b63e0234e6659f6ff3cdfd226a2ea32623147f48591b78ab100747bc828d6`。
- `019-portable-control-core=accepted/delivered`；`next_task=git-delivery`。

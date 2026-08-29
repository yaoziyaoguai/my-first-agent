# 019 Portable Durable Automations Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the platform-neutral 019 automation control core, public management/reconciliation protocol and Runtime-owned background authority without importing or qualifying any concrete OS wake, process, sandbox or browser backend.

**Architecture:** A new `agent.automation` package owns immutable definitions, schedule resolution, one CAS snapshot and bounded reconciliation. It reuses the existing `ScheduledOccurrenceCaller` and the only `AgentRuntime.run_turn`; host effects enter only through typed supervisor/sandbox/browser ports. `AutomationController` is the sole `AutomationStore` writer, while Runtime remains the sole Goal/model/tool state owner.

**Tech Stack:** Python 3.11 stdlib, immutable dataclasses/`StrEnum`, owner-only no-follow JSON/CAS, existing Runtime/ToolRuntime/Scheduler ports, pytest and Ruff.

**Spec:** `docs/superpowers/specs/2026-08-28-durable-background-runs-design.md`

## Global Constraints

- The portable core must not import launchd, systemd, Cron, `fcntl`, POSIX descriptor/open flags or process groups, Windows file/process ownership, Seatbelt, Playwright or another concrete host backend.
- `AgentRuntime.run_turn` remains the only production model/tool loop and conversation-state writer; `KernelToolRuntime` remains the only tool callable owner.
- `AutomationController.handle(action)` is the only `AutomationStore` writer. Reconciler, supervisor, CLI and wake callers submit typed actions only.
- V1 schedules are only `ONCE_UTC` and `FIXED_INTERVAL_UTC`; interval is `60..2_592_000` seconds, catch-up is `NONE` or `LATEST_ONE`, and timestamps are canonical whole-second UTC.
- V1 limits are copied exactly from the spec: 32 non-terminal automations, 128 full records, 128 tombstones, 128 occurrences, deadline `30..3_600`, model `1..16`, tool `1..32`, sandbox `0..16`, browser `0..32`.
- Snapshot limits are 4,096 entries, 64 MiB total, 16 MiB per file and 1,024 UTF-8 bytes per relative path. Diff/artifact limits are 2,000 entries/4 MiB and 32 MiB per occurrence/128 MiB per automation.
- Background execution never falls back to the host checkout, ordinary 017 host-readable policy, an unconfined command, a personal browser profile or an in-process timer daemon.
- Raw credentials, task text, model content, absolute paths and browser state never enter wake payloads, adapter diagnostics or bounded automation receipts.
- The user did not authorize commits or pushes. Replace every skill-template commit checkpoint with an execution-log checkpoint and focused verification.

## File Structure

- Create `agent/automation/contracts.py`: closed immutable definition, snapshot, action, result, grant, claim and purge contracts.
- Create `agent/automation/schedule.py`: pure UTC resolver and deterministic occurrence identity.
- Create `agent/automation/store.py`: canonical codec plus platform-neutral repository/lease protocol and deterministic U1 adapter; no OS filesystem implementation.
- Create `agent/automation/controller.py`: deterministic reducer plus the only store-writing controller.
- Create `agent/automation/workspace.py`: canonical manifest/limit/ownership contracts plus platform-neutral owned-workspace protocol and deterministic U1 adapter; no OS directory walk.
- Create `agent/automation/management.py`: typed create/preview/approve/update/pause/resume/cancel/purge orchestration; no Runtime mutation.
- Create `agent/automation/wake.py`: platform-neutral wake-adapter qualification/install/readback/remove port plus unavailable/deterministic adapters.
- Create `agent/automation/supervisor.py`: platform-neutral supervisor protocol and deterministic test adapter only.
- Create `agent/automation/reconcile.py`: one-shot coordinator that claims at most one occurrence and invokes one supervisor.
- Create `agent/automation/child.py`: bounded READY/start/result protocol plus platform-neutral `OccurrenceExecutor` port; no concrete checkpoint import.
- Create `agent/automation/composition.py`: static assembly of controller/reconciler/claim verifier from pre-bound repository/workspace ports and injected host capabilities.
- Create `agent/automation/cli.py`: public `first-agent-schedule` management and reconciliation adapter.
- Modify `agent/runtime/contracts.py`, `checkpoint.py`, `state.py`, `loop.py`, `ports.py`, `tools.py`, `views.py`: background binding, durable model-call boundary and ToolRuntime authority checks.
- Modify `agent/scheduler/contracts.py`, `caller.py`: carry the immutable background occurrence binding while preserving the existing one-shot call path.
- Modify `pyproject.toml`: point `first-agent-schedule` at `agent.automation.cli:main`.
- Create `tests/automation/`, `tests/reference/test_019_portable_core.py`, `tests/architecture/test_019_portable_boundary.py`, `scripts/run_019_core_e3.py` and `scripts/verify_019_materialized_tree.py`.
- Create `docs/acceptance/019_PORTABLE_AUTOMATION_CORE_E3.md`, `docs/implementation/019_EXECUTION_LOG.md`, core seal/receipt/review controls.

---

### Task 1: Freeze closed contracts and pure schedule resolution

**Files:**
- Create: `agent/automation/__init__.py`
- Create: `agent/automation/contracts.py`
- Create: `agent/automation/schedule.py`
- Test: `tests/automation/test_contracts.py`
- Test: `tests/automation/test_schedule.py`
- Create: `docs/acceptance/019_PORTABLE_AUTOMATION_CORE_E3.md`
- Create: `docs/implementation/019_EXECUTION_LOG.md`

**Interfaces:**
- Produces `AutomationDefinitionV1`, `AutomationRecordV1`, `AutomationSnapshotV1`, `BackgroundAuthorityGrantV1`, `BackgroundOccurrenceAuthorityV1` and `OccurrenceSummaryV1`.
- Produces `ScheduleKind`, `CatchUpRule`, `AutomationStatus`, `OccurrenceControlStatus` and `ScheduleDecisionKind` closed enums.
- Produces `resolve_schedule(definition, record, now_utc) -> ScheduleDecisionV1` and `occurrence_identity(definition, index, scheduled_for_utc) -> str`.
- Stores only immutable tuples/frozen mappings and canonical digests; no filesystem or clock reads occur in these modules.

- [x] **Step 1: Write strict contract Reds**

```python
def test_definition_digest_binds_every_authority_field() -> None:
    original = definition()
    changed = replace(original, occurrence_deadline_seconds=original.occurrence_deadline_seconds + 1)
    assert original.definition_digest != changed.definition_digest


@pytest.mark.parametrize("field", ["task_text", "credential_value", "workspace_path"])
def test_external_summary_has_no_private_or_host_path_field(field: str) -> None:
    assert field not in OccurrenceSummaryV1.__dataclass_fields__
```

- [x] **Step 2: Run the contract Reds**

Run: `.venv/bin/python -m pytest -q tests/automation/test_contracts.py -rx`

Expected: collection fails because `agent.automation.contracts` does not exist.

- [x] **Step 3: Implement the exact immutable schema**

```python
class ScheduleKind(StrEnum):
    ONCE_UTC = "once_utc"
    FIXED_INTERVAL_UTC = "fixed_interval_utc"


class CatchUpRule(StrEnum):
    NONE = "none"
    LATEST_ONE = "latest_one"


class AutomationStatus(StrEnum):
    PROPOSAL = "proposal"
    ACTIVE = "active"
    PAUSED = "paused"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    PURGE_PENDING = "purge_pending"
    PURGED = "purged"
```

Define the complete dataclass members from spec §§4–6, including provider/trust/disclosure digests, source snapshot/policy digests, all budgets, active claim, bounded history, owned-object identities and tombstones. Constructors reject bool-as-int, unknown enum values, noncanonical UTC, extra decoded keys, unsorted/duplicate tuples and digest mismatch.

- [x] **Step 4: Write timing and catch-up Reds**

```python
def test_latest_one_skips_superseded_slots_and_claims_one() -> None:
    decision = resolve_schedule(interval_definition(), record(cursor=0), utc("2026-08-28T03:00:00Z"))
    assert decision.kind is ScheduleDecisionKind.DUE
    assert decision.occurrence_index == 3
    assert decision.superseded_indexes == (0, 1, 2)


def test_none_never_jumps_over_one_late_slot() -> None:
    decision = resolve_schedule(interval_definition(catch_up=CatchUpRule.NONE), record(cursor=0), utc("2026-08-28T03:00:00Z"))
    assert decision.kind is ScheduleDecisionKind.MISFIRE_SKIPPED
    assert decision.occurrence_index == 0
```

- [x] **Step 5: Implement `resolve_schedule` as a total pure function**

Use one ordered decision set: `not_due`, `due`, `misfire_skipped`, `expired`, `max_reached`, `paused`, `cancel_pending`, `canceled`, `needs_human`. The caller supplies `now_utc`; the resolver never reads the clock or mutates the record.

- [x] **Step 6: Verify Task 1 and record the checkpoint**

Run:

```bash
.venv/bin/python -m pytest -q tests/automation/test_contracts.py tests/automation/test_schedule.py -rx
.venv/bin/ruff check agent/automation/contracts.py agent/automation/schedule.py tests/automation
git diff --check
```

Expected: all focused tests pass. Append exact counts and `next_task=2` to `019_EXECUTION_LOG.md`.

### Task 2: Implement the single AutomationRepository contract and controller owner

**Files:**
- Create: `agent/automation/store.py`
- Create: `agent/automation/controller.py`
- Test: `tests/automation/test_store.py`
- Test: `tests/automation/test_controller.py`
- Test: `tests/automation/test_controller_races.py`

**Interfaces:**
- Produces `AutomationRepository.load()`, `try_acquire()`, `compare_and_swap(snapshot, state)` and `ensure_capacity()` as a platform-neutral protocol, plus strict `encode_snapshot`/`decode_snapshot`.
- Produces `DeterministicAutomationRepository` only for U1/U2A protocol evidence and reusable `assert_repository_conformance(factory)` tests for real host adapters.
- Produces `AutomationController.handle(action) -> AutomationResultV1`; no other module receives the repository's CAS method.
- Controller actions in this task include `CreateProposal`, `StageRevision`, `ApproveRevision`, `PauseAutomation`, `ResumeAutomation`, `CancelAutomation`, `ClaimOccurrence`, `MarkDispatched`, `MarkRunning` and `RecordOccurrenceOutcome`. `BeginPurge`, `RecordPurgeProgress` and `FinishPurge` land in Task 9, after Task 3 has defined the content-free ownership manifest they must bind; this avoids inventing a second purge-object contract prematurely.

- [x] **Step 1: Write strict codec and repository-semantics Reds**

```python
def test_decode_rejects_extra_member(valid_document: dict) -> None:
    valid_document["state"]["future_field"] = True
    with pytest.raises(AutomationStoreMalformedError):
        decode_snapshot(valid_document)
```

- [x] **Step 2: Implement one bounded document and short-lease protocol**

The core codec owns one explicit `MAX_AUTOMATION_STORE_BYTES = 4 * 1024 * 1024`, canonical JSON and token+revision CAS semantics. `DeterministicAutomationRepository` models nonblocking lease, conflict, crash-before-commit and crash-after-commit without touching the filesystem. The protocol requires qualified host adapters to provide owner-only/no-follow/crash-safe durability but does not name their locking or file APIs.

- [x] **Step 3: Write controller ownership and transition Reds**

```python
def test_only_controller_can_commit_claim(store: AutomationRepository) -> None:
    controller = AutomationController(store)
    claimed = controller.handle(ClaimOccurrence(snapshot_token=token(), claim=claim()))
    assert claimed.state.active_claim == claim()


def test_cancel_running_becomes_pending_and_blocks_new_claim(controller) -> None:
    result = controller.handle(CancelAutomation(automation_id=ID, expected_revision=7))
    assert result.automation_status is AutomationStatus.CANCEL_PENDING
    assert controller.handle(ClaimOccurrence(...)).code == "cancel_pending"
```

- [x] **Step 4: Implement deterministic controller reduction**

`AutomationController.handle` acquires the short repository lease, reloads, validates the typed action against the current token/revision, calls a pure private reducer and commits one CAS. It never reads a clock, generates randomness, opens a checkpoint, calls a provider or launches a worker. Random opaque IDs/capabilities arrive in typed trusted actions and gain authority only after CAS.

- [x] **Step 5: Add race and crash-shape tests**

Prove two concurrent claims have one winner, old revision approval cannot cut over a newer draft, update approval atomically supersedes unresolved old slots, and terminal/unknown claims cannot be reclaimed under a new fencing token.

- [x] **Step 6: Verify Task 2 and record the checkpoint**

Run the three Task 2 files, Task 1 files, touched Ruff and `git diff --check`; append counts and `next_task=3`.

### Task 3: Define bounded isolated-workspace semantics behind a host port

**Files:**
- Create: `agent/automation/workspace.py`
- Test: `tests/automation/test_source_snapshot.py`
- Test: `tests/automation/test_occurrence_workspace.py`
- Test: `tests/automation/test_owned_cleanup.py`

**Interfaces:**
- Produces `OwnedWorkspaceRepository.scan_source(binding, limits) -> SourceManifestV1` with no writes.
- Produces `capture_source(binding, expected_manifest) -> OwnedObjectV1`, `materialize_occurrence`, `capture_terminal_outputs` and `delete_owned_object` as platform-neutral operations over opaque bindings/ids.
- Produces pure canonical manifest/diff validators plus `DeterministicOwnedWorkspaceRepository` for U1/U2A and reusable `assert_owned_workspace_conformance(factory)` for host adapters.

- [x] **Step 1: Write bounded capture Reds**

Through the deterministic adapter, test 4,097 entries, 64 MiB+1 total, 16 MiB+1 file, 1,025-byte path, link/unsupported node, private/runtime component names, root identity swap between preview and capture, and source content drift. Every failure leaves no partial authoritative snapshot. Real symlink/FIFO/device behavior belongs to each host adapter conformance run.

- [x] **Step 2: Implement canonical validation and the deterministic adapter**

Sort canonical relative paths, reject duplicate/noncanonical/private names and unsupported node kinds, validate declared sizes/digests, and build the complete manifest before admitting capture. The deterministic adapter uses immutable virtual nodes and explicit identity replacement faults; it never calls `Path`, `open`, `os.walk`, `dir_fd` or another host filesystem API.

- [x] **Step 3: Write materialization and terminal cleanup Reds**

```python
def test_terminal_workspace_is_deleted_only_after_diff_capture() -> None:
    repository = deterministic_workspace_repository()
    result = repository.capture_terminal_outputs(job_workspace, source_snapshot, limits())
    cleaned = repository.delete_owned_object(result.workspace_identity)
    assert result.diff_digest
    assert cleaned.outcome == "cleaned"


def test_identity_replacement_is_cleanup_unknown() -> None:
    repository = deterministic_workspace_repository()
    repository.replace_identity(identity)
    assert repository.delete_owned_object(identity).outcome == "cleanup_unknown"
```

- [x] **Step 4: Implement bounded diff/artifact semantics and cleanup state transitions**

Diff contains only sorted added/modified/deleted relative paths and content digests; encoded size and entry limits fail closed. Retain only explicitly governed 019-owned artifacts. Cleanup accepts only exact opaque ownership identity; replacement becomes `cleanup_unknown`, and an external governed artifact is unlinked but never deleted. Concrete bottom-up/no-follow deletion belongs to the host adapter.

- [x] **Step 5: Verify Task 3 and record the checkpoint**

Run Task 3 files plus store tests, touched Ruff and diff-check; append `next_task=4`.

### Task 4: Build human-first management lifecycle and CLI-neutral results

**Files:**
- Create: `agent/automation/management.py`
- Create: `agent/automation/wake.py`
- Test: `tests/automation/test_management.py`
- Test: `tests/automation/test_preview.py`
- Test: `tests/automation/test_lifecycle.py`

**Interfaces:**
- Produces `AutomationManagementService` methods `create`, `preview`, `approve`, `list`, `show`, `update`, `pause`, `resume`, `cancel`, `preview_purge`, `confirm_purge`.
- Consumes only `AutomationController`, `OwnedWorkspaceRepository`, `WakeAdapter`, provider/profile descriptors and injected qualification reports.
- Produces bounded typed views; it never opens Runtime or answers a pending approval.

- [x] **Step 1: Write preview/approval binding Reds**

```python
def test_approval_must_bind_current_human_preview(service) -> None:
    preview = service.preview(ID)
    service.update(ID, task_text="changed")
    with pytest.raises(PreviewConflict):
        service.approve(ID, preview_digest=preview.digest)
```

Assert the rendered hierarchy is task/cadence/cancel, isolated workspace, unattended/prohibited classes, provider/data classes, origins/network/budgets, credential purpose/env name, wake/recovery. Secret values and absolute state paths have no view field.

- [x] **Step 2: Implement proposal, preview and activation**

`create` stores an inactive proposal. `preview` performs source scan and qualifications without state mutation. `approve` revalidates the complete preview and source manifest, captures the immutable source snapshot, and, when the approved policy requests cold wake, drives the typed install-before-activate protocol through `WakeAdapter` before submitting one exact `ApproveRevision` action. The portable core never implements an OS install itself. Deterministic faults cover `not_activated_install_failed`, `not_activated_install_unknown`, `adapter_installed_activation_conflict` and retry/readback reconciliation.

- [x] **Step 3: Write update/cancel/open lifecycle Reds**

Prove old revision remains active until new approval; cutover supersedes only future slots; active old occurrence retains its grant; pause blocks only future claims; cancel prevents the next not-yet-invoked action; blocked `show` returns exactly one public `open` action; resolving Runtime does not resume scheduling.

- [x] **Step 4: Implement lifecycle projections**

Management returns typed next actions and public automation/index identifiers. `open` is represented as a handoff result carrying an opaque checkpoint identity for the trusted CLI composition; management itself does not load or mutate it.

- [x] **Step 5: Verify Task 4 and record the checkpoint**

Run Task 4 plus Tasks 1–3 focused tests, touched Ruff and diff-check; append `next_task=5`.

### Task 5: Add the Runtime-owned background occurrence and provider-call boundary

**Files:**
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/checkpoint.py`
- Modify: `agent/runtime/state.py`
- Modify: `agent/runtime/loop.py`
- Modify: `agent/runtime/views.py`
- Modify: `agent/scheduler/contracts.py`
- Modify: `agent/scheduler/caller.py`
- Test: `tests/automation/test_runtime_binding.py`
- Test: `tests/automation/test_model_call_recovery.py`
- Test: `tests/scheduler/test_caller.py`
- Test: `tests/continuity/test_verified_done.py`

**Interfaces:**
- Add `BackgroundOccurrenceBindingV1` to the Runtime checkpoint. It contains automation/revision/occurrence/checkpoint/grant/claim-capability digests and declared budgets, never a raw capability.
- Add `ProviderCallIntentV1` and `PersistedModelResponseV1` to `ActiveRun`; add `MODEL_EXECUTING` and `MODEL_OUTCOME_UNKNOWN` to `ActiveRunStatus`.
- Add exact typed `AbandonUnknownModelOutcome` handling through `AgentRuntime.run_turn`.
- Extend `ScheduledOccurrence` with one controller-issued immutable occurrence binding. Direct callers cannot manufacture a valid raw occurrence authority.

- [x] **Step 1: Write checkpoint and direct-construction Reds**

Prove strict encode/decode round-trip, extra-field rejection, digest validation, ordinary scheduler compatibility, and that a hand-built `ScheduledOccurrence` without a controller-issued binding cannot initialize background authority or perform a provider/tool effect.

- [x] **Step 2: Write provider crash-window Reds**

Use a checkpointing provider fixture with four cut points: before intent save, after `MODEL_EXECUTING` save, after normalized response save, and after response consumption. Assert:

```python
assert provider.calls == 1
assert reloaded.state.active_run.status is ActiveRunStatus.MODEL_OUTCOME_UNKNOWN
assert resumed_provider.calls == 0
```

When the complete normalized response is durable but unconsumed, restart must consume it with zero new provider call. When only the intent is durable, exact `AbandonUnknownModelOutcome` terminalizes only that occurrence and cannot resume the automation.

- [x] **Step 3: Implement background-only durable provider generation**

Keep ordinary interactive behavior unchanged. In the existing `_drive` path, only a state carrying a valid `BackgroundOccurrenceBindingV1` executes this ordered protocol:

1. derive exact request, disclosure and occurrence-authority digests;
2. CAS-save `ProviderCallIntentV1` and `MODEL_EXECUTING`;
3. call the existing `self._provider.generate(context)` once;
4. normalize through the existing adapter path;
5. CAS-save the full typed normalized response before decision reduction;
6. consume that durable response and clear the provider boundary only in the same Runtime state machine.

Never store raw provider payloads, secrets or occurrence capabilities. On load, an intent without a response projects `MODEL_OUTCOME_UNKNOWN`; no caller may call the provider again.

- [x] **Step 4: Extend scheduler initialization without adding a second loop**

`create_or_load_occurrence_store` validates the controller-issued binding and writes it only at revision 0. `ScheduledOccurrenceCaller.run_once` remains the one external call to `AgentRuntime.run_turn`; its one-shot conflict reload remains bounded. Reports project unknown model outcome as `needs_human` and do not invent completion.

- [x] **Step 5: Verify Task 5 and record the checkpoint**

Run the four Task 5 test files plus `tests/kernel/test_runtime_errors.py`, touched Ruff and diff-check. Append exact counts and `next_task=6`.

### Task 6: Make ToolRuntime the sole consumer of background grants

**Files:**
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/ports.py`
- Modify: `agent/runtime/tools.py`
- Modify: `agent/runtime/state.py`
- Create: `agent/automation/claim_verifier.py`
- Test: `tests/automation/test_claim_verifier.py`
- Test: `tests/automation/test_tool_authority.py`
- Test: `tests/automation/test_cancel_race.py`
- Test: `tests/kernel/test_runtime_approval.py`
- Test: `tests/sandbox/test_tool_runtime.py`
- Test: `tests/browser/test_tool_runtime.py`

**Interfaces:**
- Add `BackgroundClaimCheckV1`, `BackgroundClaimVerdictV1` and `BackgroundClaimVerifier` read-only port.
- Add ephemeral `BackgroundExecutionAuthorityV1` to `ToolPrepareContext`; it carries the raw occurrence capability only inside the pre-bound occurrence composition.
- Add exact `BackgroundActionAuthorityV1` to `ExecutionIntent`; it binds the prepared action fingerprint, occurrence, grant, policy/origin, budget counter and live-claim verdict digest.
- Add `AutomationClaimVerifier`, which reads the pre-bound store and returns one closed verdict without writing it.

- [x] **Step 1: Write grant/claim mutation Reds**

For both prepare and invoke, mutate each automation id, revision, occurrence id, checkpoint id, claim fencing token, raw capability, grant digest, expiry, budget, isolated workspace/policy digest and browser-origin policy. Every mutation must return the existing closed not-executed/needs-human path with zero callable invocation.

- [x] **Step 2: Write the two admitted authority-class Reds**

`sandbox_confined` is admitted only when the existing 017 classification is shell-free, exact-workspace, network-off, no credential env, no danger-full-access and within command/deadline budget. `browser_public_observe` is admitted only for 018 `PUBLIC_READ_EPHEMERAL` open or `OBSERVE` under the exact HTTPS origin policy. Site-bound, COMMIT, DISCLOSE, DOWNLOAD, UPLOAD and management tools remain approval candidates.

- [x] **Step 3: Implement live claim verification in `KernelToolRuntime`**

At both `prepare` and immediately before callable invocation, recompute the exact action class, validate the immutable grant and call the injected verifier. Only then create or consume `BackgroundActionAuthorityV1`. The verifier cannot approve a tool, choose a capability, mutate either store or call Runtime. Ordinary approval leases remain unchanged; do not fake a `SandboxAuthorityLeaseV1` or browser approval lease for background authority.

- [x] **Step 4: Make budgets and cancellation durable**

Increment admitted model/tool/sandbox/browser counters only through Runtime checkpoint transitions. Reuse after restart and budget overrun fail closed. A controller `cancel_pending` committed after prepare but before invoke makes the live verifier reject invocation; an already executing effect records its real result and is never rewritten as canceled.

- [x] **Step 5: Prove absence of self-authorization**

Static and behavior tests assert the background composition exposes no automation management tools, `AutomationController` never appears in tool registrations, and `AgentRuntime.run_turn`, provider generation and `ToolRuntime.invoke` retain one production owner each.

- [x] **Step 6: Verify Task 6 and record the checkpoint**

Run Task 6 tests plus existing sandbox/browser authority suites, touched Ruff and diff-check. Append `next_task=7`.

### Task 7: Implement the portable READY/start supervisor protocol and reconciler

**Files:**
- Create: `agent/automation/supervisor.py`
- Create: `agent/automation/child.py`
- Create: `agent/automation/reconcile.py`
- Modify: `agent/automation/controller.py`
- Modify: `agent/scheduler/caller.py`
- Test: `tests/automation/test_supervisor_protocol.py`
- Test: `tests/automation/test_reconcile.py`
- Test: `tests/automation/test_reconcile_faults.py`
- Test: `tests/automation/test_deadline_projection.py`

**Interfaces:**
- `OccurrenceSupervisor.run(spec, callbacks) -> SupervisedOccurrenceResultV1` is a platform-neutral host port. The core defines READY/start/result/cleanup messages and no process primitive.
- `DeterministicOccurrenceSupervisor` is a U1/U2A test adapter with explicit fault injection; it does not call a provider or tool itself.
- `AutomationReconciler.reconcile(ReconcileAutomationsV1) -> ReconcileAutomationsResultV1` processes at most one ordered decision and never sleeps.
- `OccurrenceExecutor.run_once(binding) -> OccurrenceExecutionResultV1` is the platform-neutral execution port; `DeterministicOccurrenceExecutor` is U1/U2A protocol evidence only.
- `run_occurrence_child(spec, start_channel, occurrence_executor) -> ChildResultV1` sends READY, waits for one start permit, acknowledges it and calls the injected executor exactly once.

- [x] **Step 1: Write not-due and ordering Reds**

Assert `not_due`/misfire exits before checkpoint, credential, provider, browser, sandbox or supervisor composition. Assert earliest order is `(scheduled_for_utc, automation_id)` and one reconcile claims at most one occurrence.

- [x] **Step 2: Write the durable barrier fault matrix**

Inject failure/crash at: claim committed; checkpoint created; child READY; `DISPATCHED` committed; before permit; permit outcome unknown; after start acknowledgement; `RUNNING` committed; child result; terminal summary CAS. Prove provider/tool counters remain zero before an acknowledged permit, unknown is never automatically redispatched, and terminal replay causes zero new effect.

- [x] **Step 3: Implement the one-shot reconciler**

Read the clock once, ask the controller for one resolution/claim, release the store lease, create the checkpoint, call the injected supervisor, and submit only typed controller transitions. Reacquire state only through controller actions. The supervisor receives an immutable child specification and opaque claim capability, not an `AutomationStore` or Runtime object.

- [x] **Step 4: Derive terminal summaries from Runtime authority**

Load the exact occurrence checkpoint read-only, validate checkpoint/binding identity, derive the bounded occurrence summary, capture diff/artifacts for safe terminal state, confirm workspace cleanup and only then ask the controller to terminalize. Needs-human/effect-unknown/model-unknown/cleanup-unknown keep the workspace and pause future claims.

- [x] **Step 5: Verify Task 7 and record the checkpoint**

Run Task 7, scheduler and Runtime binding tests; touched Ruff and diff-check. Append `next_task=8`.

### Task 8: Assemble the portable composition and public management/reconcile CLI

**Files:**
- Create: `agent/automation/composition.py`
- Create: `agent/automation/cli.py`
- Modify: `main.py`
- Modify: `pyproject.toml`
- Test: `tests/automation/test_composition.py`
- Test: `tests/automation/test_cli.py`
- Test: `tests/automation/test_trigger_payload.py`
- Test: `tests/architecture/test_019_portable_boundary.py`
- Modify: `tests/architecture/test_single_loop_static.py`

**Interfaces:**
- `build_automation_control_core(config, *, repository, workspace_repository, clock, supervisor, provider_factory, sandbox_capability, browser_capability)` statically returns management, controller and reconciler bound to one trusted owner namespace.
- CLI subcommands are `create`, `preview`, `approve`, `list`, `show`, `open`, `update`, `pause`, `resume`, `cancel`, `purge`, `wake`, and `reconcile`.
- Public trigger input is only `ReconcileAutomationsV1(schema_version, delivery_id?)`; no path, task, provider, credential or tool field exists.

- [x] **Step 1: Write trigger and CLI thin-adapter Reds**

Reject unknown/extra payload fields, a payload-selected store path, raw task content and an unbound caller. Assert management commands translate to typed service calls, render bounded results and never access either store directly.

- [x] **Step 2: Implement static portable assembly**

Bind repository/workspace capabilities and optional wake/supervisor/sandbox/browser ports in one composition root. Capability qualification changes management/execution availability only; it cannot change schedule/controller semantics. Do not import `fcntl`, POSIX descriptor/process APIs, Windows file/process APIs, `agent.process.group`, `agent.sandbox.seatbelt`, `agent.browser.playwright_adapter`, launchd, systemd or Cron from `agent/automation` portable modules.

- [x] **Step 3: Replace the stale public scheduler entrypoint**

Point `first-agent-schedule` to `agent.automation.cli:main`. Preserve an explicit internal compatibility test for the old `ScheduledOccurrenceCaller`, but remove the public raw `--message/--workspace-id/--state-root` surface rather than keeping a compatibility fallback.

- [x] **Step 4: Add architecture gates**

AST/import tests prove one `AgentRuntime.run_turn`, one production `provider.generate`, one `ToolRuntime.invoke`, controller-only `AutomationStore.compare_and_swap`, no concrete host import in portable modules, no management tool registration and no in-process timer/sleep loop.

- [x] **Step 5: Verify Task 8 and record the checkpoint**

Run Task 8 CLI/architecture tests plus all `tests/automation`; touched Ruff and diff-check. Append `next_task=9`.

### Task 9: Close purge, recovery UX and deterministic U1 coverage

**Files:**
- Modify: `agent/automation/management.py`
- Modify: `agent/automation/reconcile.py`
- Modify: `agent/automation/workspace.py`
- Modify: `agent/runtime/views.py`
- Test: `tests/automation/test_purge.py`
- Test: `tests/automation/test_open_handoff.py`
- Test: `tests/automation/test_result_projection.py`
- Create: `tests/reference/test_019_portable_core.py`
- Modify: `docs/acceptance/019_PORTABLE_AUTOMATION_CORE_E3.md`

- [x] **Step 1: Write purge crash-matrix Reds**

Build one manifest containing source snapshot, occurrence workspace, retained diff/artifact, Runtime checkpoint and governed external reference. Crash before/after every deletion and unlink. Assert `PURGE_PENDING` resumes idempotently only with durable progress, identity replacement becomes cleanup unknown, external artifacts are only unlinked, and capacity is freed only after every owned object is confirmed gone.

- [x] **Step 2: Write recovery UX Reds**

Every blocked occurrence renders exactly one executable `open` handoff. Revision/checkpoint drift fails before Runtime/provider/tool. Approve/reject/recover/abandon flow through existing Runtime typed actions; returning refreshes both stores and leaves scheduling paused until a separate `resume`.

- [x] **Step 3: Complete closed result and tombstone projection**

Detailed results are loaded from Runtime checkpoints, not copied from `AutomationStore`. `PURGED` exposes only content-free identity/status. Evict only the oldest confirmed tombstone beyond 128; never auto-delete a full record or owned object.

- [x] **Step 4: Encode the complete U1 matrix**

`tests/reference/test_019_portable_core.py` maps every U1 bullet in the frozen spec to at least one named behavior test and one mutation where the claim could otherwise pass vacuously. Include disclosure drift, claim reuse, budget reuse, snapshot bounds, cleanup unknown, provider unknown, READY barrier, cancel race, purge partial failure and no secret/path/task in external diagnostics.

- [x] **Step 5: Verify Task 9 and record the checkpoint**

Run all `tests/automation`, reference 019, affected Runtime/scheduler/017/018 suites, touched Ruff and diff-check. Append `next_task=10`.

### Task 10: Seal and independently review the platform-neutral U2A delivery

**Files:**
- Create: `scripts/run_019_core_e3.py`
- Create: `scripts/verify_019_materialized_tree.py`
- Create: `docs/acceptance/019_CORE_SEAL.json`
- Create: `docs/acceptance/019_CORE_RECEIPT.json`
- Create: `docs/acceptance/019_CORE_INDEPENDENT_REVIEW.md`
- Modify: `docs/implementation/019_EXECUTION_LOG.md`
- Modify: `CURRENT_CAPABILITY_STATUS.md`

- [ ] **Step 1: Implement a closed U2A runner and mutation harness**

From fresh deterministic repository/workspace instances, drive public create/preview/approve/list/show/open/update/pause/resume/cancel/purge and three fresh occurrence stores. Use only `DeterministicOccurrenceSupervisor` and `DeterministicOccurrenceExecutor` for portable protocol evidence. In a separate execution-harness integration gate, run one admitted no-tool occurrence through `ScheduledOccurrenceCaller` and the only Runtime; that gate proves owner compatibility without turning the caller's concrete checkpoint backend into a portable-core dependency. Receipts contain only closed booleans/counts/digests and bind source seal, verifier, runner, wheel and fresh adapter identities.

- [ ] **Step 2: Prove the platform boundary in materialized form**

Build the wheel, materialize an exact sealed tree, run the full suite there, and run the U2A journey there. Import and package scans must fail if the portable core references launchd/systemd/Cron, `fcntl`, POSIX/Windows filesystem or process ownership, Seatbelt or Playwright. Missing qualified repository/workspace/supervisor/sandbox/browser capabilities must produce closed `NEEDS_019_CONFIG`, never approval or fake execution.

- [ ] **Step 3: Run final source and materialized gates once on the frozen tree**

Run:

```bash
git diff --check
.venv/bin/ruff check .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx
```

Then build/seal, verify exact membership/control identity, rerun the full suite from the materialized wheel/tree, run the U2A runner, write the receipt, and require attestation Green. Any ordinary-source fix invalidates and rebuilds the seal/receipt; do not repeatedly rerun full gates after each focused repair.

- [ ] **Step 4: Perform two fresh read-only review axes**

Spec/Product checks management UX, schedule/lifecycle, recovery/result source, secrecy, mutations and U2A. Standards/Architecture checks single owners, dependency direction, store separation, cleanup, credential boundary, absence of fallback/second loop and absence of concrete platform imports. Both reviews bind the final identities.

- [ ] **Step 5: Advance only the exact supported status**

Only after U0/U1/U2A/U3 Green set `019-portable-control-core=accepted/delivered`. State explicitly that this alone does not qualify runnable unattended execution on any OS. Leave `019-macos-host-profile=not_qualified` until the separate host plan passes.

## Plan Self-Review Checklist

- [ ] Every U1 bullet in spec §13 maps to Task 1–9 tests; no requirement is deferred to the optional host profile.
- [ ] U2A uses deterministic repository/workspace/supervisor adapters only for portable protocol evidence and separately proves the existing real Runtime caller; it does not claim durable host persistence, real no-follow cleanup, a hard deadline or OS process cleanup.
- [ ] Only Runtime interprets model/tool state and only ToolRuntime consumes background action authority.
- [ ] Only `AutomationController.handle` writes `AutomationStore`; reconciler/supervisor/CLI never receive CAS.
- [ ] Portable modules contain no imports or strings that select a concrete OS persistence, workspace, wake, process, sandbox or browser backend.
- [ ] All effectful unknown outcomes preserve authority/ownership and block replay; no `KnownNotExecuted` label is used for a post-dispatch unknown.
- [ ] Full tests run once after focused Green and source freeze, followed by one materialized/full/U2A/attestation chain.
- [ ] The plan contains no `TODO`, `TBD`, placeholder path, optional core requirement or commit/push step.

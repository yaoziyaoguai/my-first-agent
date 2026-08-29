# 019 Durable Background Runs Implementation Plan (Superseded)

> Superseded by the user-approved platform-neutral design and the two replacement plans dated
> 2026-08-28. Do not implement this document: it incorrectly makes launchd and macOS-specific
> process/filesystem mechanisms part of the product core.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execute only after 018 U3 PASS; use Claude Code GLM 5.3 `effort=max` as the single writer.

**Goal:** 用 macOS launchd 唤醒一次性、可去重、可恢复的 Runtime occurrence，在冻结权限 envelope 内后台完成 017/018 任务并在需要用户时持久暂停。

**Architecture:** `JobStore` 独占 job definition/occurrence ledger；`LaunchdAdapter` 只安装和移除外部触发器；`ScheduledTriggerCaller` 把当前时刻确定性映射为现有 `ScheduledOccurrence`，随后仍只调用 `AgentRuntime.run_turn`。没有产品内 timer、daemon、polling model loop 或并行 state owner。

**Tech Stack:** Python 3.11 stdlib (`plistlib`, `fcntl`, `datetime`)、macOS launchd、现有 Scheduler/Runtime、017 Sandbox、018 Browser。

**Spec:** `docs/superpowers/specs/2026-08-26-governed-execution-program-design.md`

## Global Constraints

- 019 开始前，017/018 必须各自 U3 PASS；019 只组合已交付 public interfaces。
- v1 schedule kind 只有 `ONCE_UTC` 和 `FIXED_INTERVAL_UTC`；不实现 cron/RRULE/timezone/DST calendar parser。
- 每个 job 必须有 `expires_at_utc`、`max_occurrences`、per-occurrence deadline 和 model/tool/action budgets；无无限值。
- launchd 只传非秘密 job locator；credential/profile raw state 不进 plist、notification、checkpoint、receipt。
- Job CRUD/launchd install 是 governed external effect + exact approval。job approval不预批 host merge或浏览器 consequential commit。
- worker 每次 occurrence 后退出；等待 approval/recovery 时不占后台进程或并发槽。
- unknown effect 不自动 retry；duplicate trigger 只 replay同一 occurrence。
- 每原子任务 focused tests；Task 9 一次 source full；Task 10 materialized/full/real E3。按项目规则不 commit/push。

## File Map

- Create `agent/scheduler/job_contracts.py`: schedule/job/trigger/notification typed contracts。
- Create `agent/scheduler/job_store.py`: owner-only JobStore、CAS、occurrence ledger。
- Create `agent/scheduler/timing.py`: pure UTC occurrence calculation/misfire policy。
- Create `agent/scheduler/launchd.py`: plist renderer + launchctl adapter。
- Create `agent/scheduler/job_tools.py`: governed create/update/pause/resume/cancel/list/status。
- Create `agent/scheduler/trigger.py`: job locator→occurrence→existing caller bridge、concurrency lock。
- Create `agent/scheduler/notify.py`: bounded local notification adapter。
- Modify `agent/scheduler/contracts.py`, `caller.py`, `agent/composition.py`, `main.py`, runtime contracts/state/tools/views。
- Create `tests/scheduler/test_job_*`, 019 reference/harness, docs, E3 runner/verifier/seal/review。

---

### Task 1: Freeze 019 schedule and occurrence contracts

**Files:**
- Create: `docs/architecture/019_DURABLE_BACKGROUND_RUNS_DESIGN.md`
- Create: `docs/acceptance/019_DURABLE_BACKGROUND_RUNS_E3.md`
- Create: `docs/implementation/019_EXECUTION_LOG.md`
- Create: `agent/scheduler/job_contracts.py`
- Create: `agent/scheduler/timing.py`
- Test: `tests/scheduler/test_job_contracts.py`
- Test: `tests/scheduler/test_timing.py`

**Interfaces:**
- Produces `ScheduleKind.ONCE_UTC/FIXED_INTERVAL_UTC`.
- Produces `ScheduledJobV1`, `OccurrenceDecisionV1`, `MisfirePolicyV1`.
- Produces `resolve_occurrence(job, now_utc) -> OccurrenceDecisionV1`.

- [ ] **Step 1: Freeze exact v1 limits**

Set: interval `60..2_592_000` seconds, `max_occurrences 1..10_000`, per-occurrence deadline `30..86_400` seconds, catch-up count `0..1`, grace `0..3_600` seconds, bounded message `1..4_000` chars. `ONCE_UTC` requires max 1; all timestamps canonical UTC whole seconds.

- [ ] **Step 2: Write timing Reds**

```python
def test_fixed_interval_maps_time_to_one_stable_index():
    decision = resolve_occurrence(job(anchor="2026-08-26T00:00:00Z", interval=3600), "2026-08-26T03:00:20Z")
    assert decision.occurrence_index == 3
    assert decision.scheduled_for_utc == "2026-08-26T03:00:00Z"

def test_expired_or_late_without_catchup_does_not_run():
    assert resolve_occurrence(expired_job(), now()).reason_code == "job_expired"
    assert resolve_occurrence(late_job(catch_up=0), now()).reason_code == "misfire_skipped"
```

- [ ] **Step 3: Run Reds**

Run both focused files; expect missing modules.

- [ ] **Step 4: Implement strict contracts and pure timing**

Use timezone-aware UTC datetime only. Occurrence ID binds job ID/revision/index/scheduled time/message/workspace/policy digests. Clock rollback can only map to an already-ledgered occurrence or `not_due`; it cannot create a new earlier identity.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests/Ruff/diff-check; record `next_task=2`.

### Task 2: Implement the owner-only JobStore and occurrence ledger

**Files:**
- Create: `agent/scheduler/job_store.py`
- Test: `tests/scheduler/test_job_store.py`
- Test: `tests/scheduler/test_occurrence_ledger.py`

**Interfaces:**
- Produces `JobStore.create/load/list/compare_and_swap/delete`.
- Produces `claim_occurrence(job_ref, decision) -> OccurrenceClaimV1` and `record_occurrence_status(...)`.

- [ ] **Step 1: Write CAS/path Reds**

Reject traversal/symlink, raw job label in filenames, permission mismatch, unknown schema/member, stale revision, policy/profile/environment drift and corrupt ledger. Ensure state root is outside workspace and 0700/0600.

- [ ] **Step 2: Write max/duplicate Reds**

Two processes claiming the same occurrence produce one winner and one exact duplicate. Max occurrences counts unique claimed identities, not retries. Paused/replayed occurrences do not consume extra count. Cancel/expiry prevents new claims but preserves old evidence.

- [ ] **Step 3: Run Reds**

Run both focused files.

- [ ] **Step 4: Implement atomic store**

Use exclusive initialize and token/revision CAS patterns from `LocalCheckpointStore`; do not create a generic storage factory. Store job metadata and bounded occurrence summaries separately from conversation checkpoints. Never store credential or raw browser storage state.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests/Ruff/diff-check; record `next_task=3`.

### Task 3: Render and govern launchd triggers

**Files:**
- Create: `agent/scheduler/launchd.py`
- Test: `tests/scheduler/test_launchd_plist.py`
- Test: `tests/scheduler/test_launchd_adapter.py`

**Interfaces:**
- Produces `LaunchdSpecV1(label, plist_digest, job_ref_digest)`.
- Produces `LaunchdAdapter.install/update/remove/status` using injected command runner.

- [ ] **Step 1: Write plist Reds**

Use `plistlib`; label is `com.first-agent.job.<sha256-prefix>`. ProgramArguments contain the installed `first-agent-schedule` path, `--job-ref` opaque ID and `--job-store` exact owner root only. No shell, environment, message, website, profile/account label or credential. Both schedule kinds use `StartInterval=60`; launchd only wakes a one-shot worker, while `resolve_occurrence()` remains the sole UTC due-time authority. Early/not-due wakeups must exit before composition with zero provider/tool effect. Do not use `StartCalendarInterval`, whose local-time/no-year semantics cannot faithfully encode `ONCE_UTC`.

- [ ] **Step 2: Write launchctl Reds**

Exact argv only: `launchctl bootstrap gui/<uid> <plist>`, `kickstart`, `bootout`. Atomic plist write precedes bootstrap; command/result receipt and status read-back follow. Bootstrap uncertainty is unknown-outcome; do not retry install blindly.

- [ ] **Step 3: Run Reds**

Run launchd files; expect missing adapter.

- [ ] **Step 4: Implement renderer/adapter**

Use owner-only `~/Library/LaunchAgents` target resolved without symlink. Inject command runner/uid for tests. `status` parses bounded `launchctl print` output into closed installed/absent/unknown, never exposes raw environment.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests/Ruff/diff-check; record `next_task=4`.

### Task 4: Add governed Job CRUD tools

**Files:**
- Create: `agent/scheduler/job_tools.py`
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/checkpoint.py`
- Modify: `agent/runtime/tools.py`
- Modify: `agent/runtime/state.py`
- Test: `tests/scheduler/test_job_tools.py`
- Test: `tests/scheduler/test_job_authority.py`
- Test: `tests/continuity/test_job_checkpoint.py`

**Interfaces:**
- Produces `schedule_create/update/pause/resume/cancel` EXTERNAL governed tools and `schedule_list/status` READ_ONLY tools.
- Produces `ScheduledJobAuthorityCandidateV1` and exact admin receipt.

- [ ] **Step 1: Write authority Reds**

Every mutation preview binds complete job definition, workspace, sandbox/browser policy refs, expiry/max/budgets and launchd diff. Model cannot omit bounds, insert future consequential authority or mutate another job by label. Denial leaves JobStore/plist/launchctl untouched.

- [ ] **Step 2: Write policy-envelope Reds**

Reject job definitions containing host merge, browser COMMIT/DISCLOSE, profile/origin expansion or credential reference. Only 017 sandbox compute/artifact and 018 read-only approved site policy are schedulable in v1.

- [ ] **Step 3: Run Reds**

Run tool/authority/checkpoint files.

- [ ] **Step 4: Implement typed registrations**

Callable consumes injected JobStore/LaunchdAdapter only. `KernelToolRuntime` owns approval and invoke; state records external effect receipt/unknown outcome through existing path. List/status return bounded summaries without internal paths/IDs as user-required input.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests/Ruff/diff-check; record `next_task=5`.

### Task 5: Bridge launchd triggers to existing ScheduledOccurrenceCaller

**Files:**
- Create: `agent/scheduler/trigger.py`
- Modify: `agent/scheduler/contracts.py`
- Modify: `agent/scheduler/caller.py`
- Modify: `main.py`
- Test: `tests/scheduler/test_trigger.py`
- Test: `tests/scheduler/test_trigger_replay.py`
- Test: `tests/scheduler/test_trigger_concurrency.py`

**Interfaces:**
- Produces `ScheduledTriggerCaller.run_job_once(job_ref, now_utc) -> ScheduledRunReport`.
- Reuses `create_or_load_occurrence_store` and `ScheduledOccurrenceCaller.run_once`.

- [ ] **Step 1: Write call-path Reds**

Static/source tests prove trigger never calls provider/ToolRuntime/checkpoint mutation directly. It loads job, resolves and claims occurrence, constructs exact existing `ScheduledOccurrence`, builds shared composition bound to that occurrence store and calls existing caller once.

- [ ] **Step 2: Write replay/race Reds**

Duplicate and concurrent launchd fires yield one occurrence/provider/effect. Same job/index with changed job revision/message/policy conflicts. A second conflict after one exact-action reconciliation returns fatal/needs-human; no loop.

- [ ] **Step 3: Run Reds**

Run trigger files.

- [ ] **Step 4: Implement the bridge and CLI mode**

Add `first-agent-schedule --job-ref ... --job-store ...`. Clock is read once by trigger adapter; existing `ScheduledOccurrence` remains clock-free. Finish by recording bounded occurrence status in JobStore; ledger-write uncertainty is reported, not converted to success.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests/Ruff/diff-check; record `next_task=6`.

### Task 6: Add concurrency, budgets and worker-release semantics

**Files:**
- Modify: `agent/scheduler/trigger.py`
- Modify: `agent/scheduler/job_store.py`
- Test: `tests/scheduler/test_job_concurrency.py`
- Test: `tests/scheduler/test_job_budgets.py`
- Test: `tests/scheduler/test_worker_release.py`

**Interfaces:**
- Produces `ConcurrencyLeaseV1` backed by nonblocking `fcntl.flock` and process identity.
- Produces closed occurrence statuses `completed`, `needs_human`, `skipped_busy`, `skipped_misfire`, `expired`, `fatal_conflict`.

- [ ] **Step 1: Write lock Reds**

Same job/concurrency key and same browser profile serialize; distinct keys run independently. OS releases lock after crash. Lock only protects active worker, not effect outcome; checkpoint remains authority.

- [ ] **Step 2: Write budget Reds**

Per-occurrence deadline/model/tool/action limits are no greater than job bounds and feed existing `InvocationLimits`. Limit/retryable/approval/recovery exits `needs_human`; no automatic Resume. Max/expiry prevents future claims.

- [ ] **Step 3: Run Reds**

Run three focused files.

- [ ] **Step 4: Implement bounded worker lifecycle**

Acquire lock before composition; release in `finally` after Runtime result/report persistence. No polling/heartbeat/background thread. Waiting states persist checkpoint and process exits immediately.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests/Ruff/diff-check; record `next_task=7`.

### Task 7: Compose sandbox/browser jobs and human resume

**Files:**
- Modify: `agent/composition.py`
- Modify: `main.py`
- Modify: `agent/runtime/views.py`
- Test: `tests/scheduler/test_sandbox_job.py`
- Test: `tests/scheduler/test_browser_job.py`
- Test: `tests/scheduler/test_human_resume.py`

**Interfaces:**
- Job policy references exact delivered 017 environment policy and 018 profile/site policy digests.
- Human resolution uses existing CLI/TUI typed actions on the occurrence checkpoint.

- [ ] **Step 1: Write composition Reds**

Job can run sandbox compute and browser read-only operations through shared registrations. Identity drift, missing capability or changed profile/environment returns needs-human before effect. Background composition has no extra tools or broader policy than job envelope.

- [ ] **Step 2: Write approval-wait Reds**

Host ChangeBundle apply or browser consequential candidate persists AWAITING_APPROVAL and worker exits. User opens the occurrence, sees contextual exact action, approves/denies through same Runtime, and duplicate launchd fire afterward reports current authoritative state without repeating effect.

- [ ] **Step 3: Run Reds**

Run three focused files.

- [ ] **Step 4: Implement static policy projection**

At composition, intersect current delivered capability policy with immutable job envelope; mismatch fails closed. Do not add a background-specific Runtime or automatic approval action.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests/Ruff/diff-check; record `next_task=8`.

### Task 8: Add bounded local notifications and management UX

**Files:**
- Create: `agent/scheduler/notify.py`
- Modify: `main.py`
- Modify: `agent/cli/render.py`
- Test: `tests/scheduler/test_notifications.py`
- Test: `tests/cli/test_019_schedule_experience.py`

**Interfaces:**
- Produces `NotificationV1(job_label_digest, status, occurred_at_utc, next_action_kind)`.
- Produces optional `MacOSNotificationAdapter.send` with injected command runner.

- [ ] **Step 1: Write secrecy/escaping Reds**

Notification contains no task text, URL, account, command output, path, credential, internal request ID or raw exception. Use fixed title and closed status/next-action strings. Escape argv without shell; notification failure never changes authoritative job result.

- [ ] **Step 2: Write everyday UX Reds**

Natural language create leads to one exact schedule preview. List/status shows label, next occurrence, remaining count, expiry and state. Needs-human opens the right contextual task without requiring digest copy. Pause/cancel projection is accurate after restart.

- [ ] **Step 3: Run Reds**

Run notification/CLI files.

- [ ] **Step 4: Implement notification and rendering**

Invoke `/usr/bin/osascript` with a fixed script template and data supplied as separate argv values; no model-authored script. Rendering remains advisory and derives from JobStore/checkpoint projections.

- [ ] **Step 5: Verify and record checkpoint**

Run focused tests/Ruff/diff-check; record `next_task=9`.

### Task 9: Deterministic 019 and integrated suite, then one source full gate

**Files:**
- Create: `tests/reference/test_019_durable_background_runs.py`
- Create: `tests/reference/test_019_e3_harness.py`
- Modify: `docs/implementation/019_EXECUTION_LOG.md`

- [ ] **Step 1: Implement frozen deterministic journeys**

Cover once/interval, duplicate/overlap, crash/restart, sandbox/browser jobs, approval wait/release/resume, max/expiry/cancel/misfire, notification secrecy and identity drift. Counters independently track trigger/provider/browser/sandbox/host effects.

- [ ] **Step 2: Run focused 019 + integrated 017/018 suite**

Run scheduler/job tests and the integrated reference journey. Require full untruncated exit 0.

- [ ] **Step 3: Run architecture gates**

Run Ruff/diff-check and static owner checks: launchd/job/trigger modules contain no provider.generate/ToolRuntime.invoke/checkpoint CAS path; only existing Runtime owns them.

- [ ] **Step 4: Run one complete source gate**

Run `.venv/bin/python -m pytest -q -rx`; record exact count/duration/root.

- [ ] **Step 5: Freeze source evidence**

Freeze ordinary source before seal; detached log edits cannot change product root.

### Task 10: Materialized launchd E3, cross-stage journey and fresh review

**Files:**
- Create: `scripts/run_019_e3.py`
- Create: `scripts/verify_019_materialized_tree.py`
- Create: `docs/acceptance/019_DURABLE_BACKGROUND_RUNS_E3_RECEIPTS.json`
- Create: `docs/implementation/019_DELIVERY_SEAL.json`
- Create: `docs/acceptance/019_DURABLE_BACKGROUND_RUNS_INDEPENDENT_REVIEW.md`
- Modify: `README.md`, `STRATEGY.md`, `docs/architecture/CURRENT_CAPABILITY_STATUS.md`

- [ ] **Step 1: Build and install sealed product**

Build from immutable materialized source, install clean wheel with browser extra, bind Docker/Chromium/launchd/verifier identities and run full offline gate.

- [ ] **Step 2: Run three real launchd attempts**

Install bounded test jobs under a dedicated test state root. Each real attempt proves launchd wake, one-shot worker exit, browser read, sandbox computation, ChangeBundle/commit wait, human resolution, duplicate fire and cleanup. Remove only exact test jobs after receipt and verify absence.

- [ ] **Step 3: Verify attestation and no residue**

Membership/control/attestation bind source/wheel/backends/job/plist/occurrences and all claims. Verify no active test launchd job, browser session, Docker resource or worker process remains; cleanup unknown blocks PASS.

- [ ] **Step 4: Fresh independent review**

Review bounded scheduling UX, no daemon/second loop, replay/unknown-effect semantics, policy envelope, worker release, notification secrecy and cross-stage false completion. Any source fix invalidates identity and triggers the final affected + full/E3 cycle.

- [ ] **Step 5: Promote the program accurately**

Declare: browser tasks in a dedicated profile, arbitrary commands inside a qualified sandbox, and bounded macOS background scheduling. Do not claim personal Chrome/desktop control, host arbitrary shell, unlimited autonomy, cross-platform or production-ready arbitrary integrations.

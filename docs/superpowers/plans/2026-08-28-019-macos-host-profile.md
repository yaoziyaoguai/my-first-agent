# 019 macOS Qualified Host Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the platform-neutral 019 control core is independently delivered, qualify one optional macOS execution profile that supplies a real POSIX occurrence supervisor, strict 017 Seatbelt confinement, 018 public ephemeral Chromium observation and one global launchd cold-wake adapter.

**Architecture:** The host profile is an adapter layer over the already delivered `ReconcileAutomationsV1`, `OccurrenceSupervisor`, sandbox and browser ports. It cannot change schedules, claims, automation lifecycle, Runtime completion or ToolRuntime authority. `launchd` is a wake hint only; the POSIX supervisor owns one child process group and the existing Runtime remains the only model/tool loop.

**Tech Stack:** Python 3.11 stdlib (`plistlib`, `subprocess`, `fcntl`, `os`, `signal`), macOS launchd, existing `agent.process.group`, 017 Seatbelt, 018 Playwright/Chromium, pytest and Ruff.

**Spec:** `docs/superpowers/specs/2026-08-28-durable-background-runs-design.md` §§8.2, 9, 10 and U2B.

**Prerequisite:** `019-portable-control-core=accepted/delivered` with a Green bound seal/receipt/review. This plan may consume its public ports but may not modify their meaning. Any required portable-core contract change returns to the core plan and invalidates the core identity.

## Global Constraints

- This profile is optional and macOS-specific. Its absence/failure cannot downgrade the portable-control-core status or imply anything about Linux, Windows or cloud hosts.
- One fixed product LaunchAgent wakes the whole owner store. There is never one OS job per automation.
- The plist invokes only the installed `first-agent-schedule reconcile` executable and fixed trusted composition. No shell, arbitrary store path, automation id, task, URL, profile, credential reference or model text enters it.
- launchd, the POSIX supervisor, Seatbelt and Playwright never write `AutomationStore` or Runtime checkpoints directly and never call provider/tool callables.
- Credential qualification proves only that the approved environment name is resolvable in the actual launch environment. It does not persist the value or attest the principal behind a rotated value.
- Logs, exit diagnostics and U2B receipts contain only closed codes, counts and digests. No absolute paths, task/label text, credentials, URLs, provider content, browser content or tracebacks.
- No commit or push is authorized. Use execution-log checkpoints instead.

## File Structure

- Create `agent/automation_hosts/__init__.py`: explicit non-portable host-profile namespace.
- Create `agent/automation_hosts/posix_storage.py`: stable storage exports.
- Create `agent/automation_hosts/_posix_fs.py`, `posix_repository.py`, `posix_workspace.py`,
  `_posix_workspace_files.py` and `_posix_workspace_codec.py`: owner-only/no-follow/crash-safe
  primitives, repository, workspace lifecycle, descriptor traversal and strict metadata codec.
- Create `agent/automation_hosts/runtime_executor.py`: existing checkpoint/ScheduledOccurrenceCaller adapter for the portable execution port.
- Create `agent/automation_hosts/posix_supervisor.py`: verified process-group `OccurrenceSupervisor` adapter.
- Create `agent/automation_hosts/macos_profile.py`: static Seatbelt/Chromium/provider qualification and occurrence composition.
- Create `agent/automation_hosts/launchd.py`: fixed plist renderer and exact install/readback/remove adapter.
- Create `agent/automation_hosts/macos_cli.py`: trusted local host-profile enable/disable/qualification wiring used by the portable CLI port.
- Create `tests/automation_hosts/` and `tests/reference/test_019_macos_host_profile.py`.
- Create `scripts/run_019_macos_e3.py`, `scripts/verify_019_macos_materialized_tree.py` and profile-specific seal/receipt/review controls.
- Create `docs/implementation/019_MACOS_PROFILE_EXECUTION_LOG.md`.

---

### Task 1: Qualify real owner-only persistence and owned-workspace operations

**Files:**
- Create: `agent/automation_hosts/__init__.py`
- Create: `agent/automation_hosts/posix_storage.py`
- Create: `agent/automation_hosts/_posix_fs.py`
- Create: `agent/automation_hosts/posix_repository.py`
- Create: `agent/automation_hosts/posix_workspace.py`
- Create: `agent/automation_hosts/_posix_workspace_files.py`
- Create: `agent/automation_hosts/_posix_workspace_codec.py`
- Test: `tests/automation_hosts/test_posix_repository.py`
- Test: `tests/automation_hosts/test_posix_workspace.py`
- Test: `tests/automation_hosts/test_posix_owned_cleanup.py`
- Create: `docs/implementation/019_MACOS_PROFILE_EXECUTION_LOG.md`

**Interfaces:**
- `PosixAutomationRepository` implements the portable repository/short-lease/CAS port under one pre-bound owner root.
- `PosixOwnedWorkspaceRepository` implements scan/capture/materialize/terminal-output/delete under pre-bound source and owned roots.
- Both pass the portable conformance suites; neither imports controller, scheduler, Runtime, provider or ToolRuntime code.

- [x] **Step 1: Write owner/no-follow/crash Reds**

Cover root/state/lock symlinks, dangling links, file replacement, wrong uid/mode/type, malformed/oversized documents, lock contention, crash before/after atomic replace and stale CAS. Repository creation uses 0700 owner directories and 0600 regular files; every ambiguity fails closed.

- [x] **Step 2: Write real workspace traversal and cleanup Reds**

Cover symlink/FIFO/socket/device nodes, directory swaps during scan/capture/delete, private/runtime names, hardlink-to-host attempts, bounds, partial capture and identity replacement. Prove every occurrence is a fresh copy, host workspace mutation remains zero, safe-terminal deletion is bottom-up/no-follow, and cleanup unknown preserves the ownership entry.

- [x] **Step 3: Implement POSIX adapters behind the portable ports**

Use descriptor-relative operations, `O_NOFOLLOW`, short nonblocking `flock`, fsync and atomic replace only in this host module. Keep every root pre-bound by trusted composition and every public/worker payload path-free. Do not extract a generic filesystem framework or expose raw fds to the core.

- [x] **Step 4: Verify Task 1 and record the checkpoint**

Run the three Task 1 files plus both portable conformance suites, touched Ruff and diff-check. Append exact counts and `next_task=2`.

### Task 2: Implement a verified POSIX occurrence supervisor

**Files:**
- Create: `agent/automation_hosts/posix_supervisor.py`
- Create: `agent/automation_hosts/runtime_executor.py`
- Modify: `agent/automation/child.py`
- Test: `tests/automation_hosts/test_posix_supervisor.py`
- Test: `tests/automation_hosts/test_posix_supervisor_cleanup.py`
- Test: `tests/automation_hosts/test_ready_start_protocol.py`

**Interfaces:**
- `PosixOccurrenceSupervisor.run(spec, callbacks) -> SupervisedOccurrenceResultV1` implements the portable port.
- `RuntimeOccurrenceExecutor.run_once(binding) -> OccurrenceExecutionResultV1` creates/loads the exact existing Runtime checkpoint and delegates exactly once to `ScheduledOccurrenceCaller.run_once()`.
- It uses `start_new_session=True`, verifies the leader's PGID identity, bounds READY/start-ack/result waits, and delegates TERM/KILL/liveness confirmation to `agent.process.group`.
- It passes the child only an immutable occurrence-spec locator and inherited opaque start/claim channels; it never passes task text or a store path through command-line arguments.

- [x] **Step 1: Write real descendant and unknown-cleanup Reds**

The fixture leader creates a real descendant, reports its PID/PGID over the private protocol, and waits. Prove leader and descendant share the verified group; deadline sends TERM then KILL; both exact identities are gone. Signal identity drift, EPERM liveness uncertainty and surviving descendant produce `cleanup_unknown`, never `cleaned`.

- [x] **Step 2: Write READY/start barrier Reds**

Inject child exit before READY, READY timeout, parent crash before durable dispatch, start permit not sent, permit outcome unknown, start-ack timeout and result timeout. The child provider/tool sentinel must remain zero before acknowledged start. A parent that cannot prove permit delivery returns unknown and cannot reuse the claim automatically.

- [x] **Step 3: Implement the bounded supervisor and existing-Runtime executor**

Spawn the installed child module without shell, with explicit stdio pipes and closed inherited fds. Validate every protocol frame with a fixed byte limit and closed schema. Hold no `AutomationStore` lease while waiting. On all terminal paths reap the leader and verify group cleanup; only proven pre-start failure is known-not-executed. The runtime executor binds `LocalCheckpointStore` only inside this host module and delegates to the existing scheduler caller; it has no provider/tool loop of its own.

- [x] **Step 4: Verify Task 2 and record the checkpoint**

Run the three Task 2 files plus existing `tests/process/test_group.py` and group-cleanup tests, touched Ruff and diff-check. Append exact counts and `next_task=3`.

### Task 3: Qualify strict Seatbelt and public ephemeral Chromium composition

**Files:**
- Create: `agent/automation_hosts/macos_profile.py`
- Modify: `agent/composition.py`
- Test: `tests/automation_hosts/test_macos_qualification.py`
- Test: `tests/automation_hosts/test_background_seatbelt.py`
- Test: `tests/automation_hosts/test_background_browser.py`
- Test: `tests/architecture/test_019_host_boundary.py`

**Interfaces:**
- `MacOSAutomationHostProfile.qualify(definition) -> HostQualificationV1` binds exact POSIX supervisor, Seatbelt backend, background read policy, Chromium/Playwright identity, provider descriptor/trust-profile identity and environment-name availability.
- `MacOSAutomationHostProfile.build_occurrence(spec) -> OccurrenceCompositionV1` builds the existing Runtime/ToolRuntime with the raw active claim injected only after qualification.
- The portable composition sees only typed qualification and capability ports; it does not import this module.
- The definition binds one stable Seatbelt template digest; each fresh occurrence additionally
  binds its concrete workspace/temp/HOME instance digest in the tool safety binding.

- [ ] **Step 1: Write strict background read-policy Reds**

Inside a real Seatbelt-confined command, prove reads succeed only for the materialized occurrence workspace, job temp/HOME and the exact qualified product/runtime/toolchain allowlist. Reads of source checkout, owner home, automation state, unrelated temp roots and a replacement path fail before bytes enter a tool result. Network remains off and host workspace writes remain zero.

- [ ] **Step 2: Write browser authority Reds**

Use real 018 Playwright/Chromium in `PUBLIC_READ_EPHEMERAL`. Exact approved HTTPS origins and OBSERVE actions succeed within browser budget. Site-bound profile, persistent storage, COMMIT, DISCLOSE, DOWNLOAD, UPLOAD, other origin and budget reuse stop as needs-human with zero consequential effect. Browser session/process cleanup must be confirmed.

- [x] **Step 3: Write qualification drift Reds**

Mutate supervisor identity, Seatbelt policy/backend, snapshot/binding, Chromium/Playwright identity, provider destination/model/trust profile, disclosure classes and configured environment name. Each drift produces one closed `NEEDS_019_CONFIG` before provider/browser/sandbox composition. A missing credential value reports only `credential_unavailable`; tests never inspect or persist it.

- [x] **Step 4: Implement static macOS composition**

Reuse existing 017/018 builders through explicit injected roots and policy/origin contracts. Do not add a second Runtime, tool registry or approval path. Background grants remain interpreted only by `KernelToolRuntime`; the host profile merely supplies qualified enforcement capabilities.

Task 3 implementation note: the current managed Coding sandbox rejects nested
`sandbox-exec` and loopback fixture sockets with `EPERM`. The deterministic policy,
authority, composition and drift gates are Green, but Steps 1/2/5 remain open until
the final U2B qualified-host runner executes those real Seatbelt/Chromium probes.

- [ ] **Step 5: Verify Task 3 and record the checkpoint**

Run Task 3 plus touched 017/018 suites and single-owner architecture gates, touched Ruff and diff-check. Append `next_task=4`.

### Task 4: Add one global launchd cold-wake adapter

**Files:**
- Create: `agent/automation_hosts/launchd.py`
- Create: `agent/automation_hosts/macos_cli.py`
- Test: `tests/automation_hosts/test_launchd_plist.py`
- Test: `tests/automation_hosts/test_launchd_adapter.py`
- Test: `tests/automation_hosts/test_launchd_diagnostics.py`
- Test: `tests/automation_hosts/test_wake_management.py`

**Interfaces:**
- `LaunchdWakeAdapter.render(LaunchdConfigurationV1) -> bytes` returns one canonical plist.
- `install`, `readback`, and `remove` return closed `WakeAdapterResultV1` with digest and status only.
- A small injected command runner executes exact argv for `launchctl bootstrap`/`bootout`; production does not parse human-readable `launchctl print` output.

- [x] **Step 1: Write canonical plist Reds**

Assert exactly one fixed label, fixed installed executable, one `reconcile` argument, bounded `StartInterval` and launchd-required keys. Reject extra program arguments, shell, environment variables and every user/task/store/automation/URL/profile/credential field. Scan encoded plist for sentinel values.

- [x] **Step 2: Write install/readback/remove fault Reds**

Cover write-before-bootstrap crash, bootstrap success/unknown, activation CAS conflict leaving an idle adapter, drifted plist digest, bootout success/unknown and replacement file. Unknown is durable adapter state and cannot be overwritten as a compatibility repair. Disable refuses while a worker runs.

- [x] **Step 3: Implement exact adapter lifecycle**

Write the owner-only plist with no-follow/atomic replacement. Use only exit class plus exact on-disk digest for readback. Bound stdout/stderr without rendering it; map it to closed codes. A cold wake invokes the same installed public reconcile command bound by trusted local configuration.

- [x] **Step 4: Integrate portable `wake enable/disable` through a host port**

The portable management service asks an injected wake-adapter capability for preview/install/remove; CLI still submits typed actions. First activation follows the spec's install-before-activate partial-failure states. No macOS type leaks into portable contracts.

- [x] **Step 5: Verify Task 4 and record the checkpoint**

Run all launchd/wake files, portable management lifecycle tests, touched Ruff and diff-check. Append `next_task=5`.

### Task 5: Qualify U2B with three real launchd wakes

**Files:**
- Create: `scripts/run_019_macos_e3.py`
- Create: `scripts/verify_019_macos_materialized_tree.py`
- Create: `docs/acceptance/019_MACOS_PROFILE_SEAL.json`
- Create: `docs/acceptance/019_MACOS_PROFILE_RECEIPT.json`
- Create: `docs/acceptance/019_MACOS_PROFILE_INDEPENDENT_REVIEW.md`
- Create: `tests/reference/test_019_macos_host_profile.py`
- Modify: `docs/implementation/019_MACOS_PROFILE_EXECUTION_LOG.md`
- Modify: `CURRENT_CAPABILITY_STATUS.md`

- [ ] **Step 1: Build a dedicated, recoverable U2B harness**

Use a fresh owner-only test root, unique fixed test label and installed materialized wheel. Preflight exact macOS/launchd/Seatbelt/Playwright/Chromium availability; unavailable prerequisites yield `not_qualified`, not a false product failure. Track exact LaunchAgent, process group, browser session and test-root identities for bounded cleanup.

- [ ] **Step 2: Run the three required real wakes**

1. Due: launchd starts reconcile, POSIX supervisor proves READY/DISPATCHED/start, the only Runtime enters the exact checkpoint and exercises real confined execution or public observation to an authoritative terminal/needs-human receipt.
2. Duplicate: the same delivery/occurrence adds zero provider calls, tool calls or effects.
3. Not-due or misfire: exits before provider, credential, browser, sandbox and supervisor composition.

Also simulate sleep/misfire and prove no backlog replay.

- [ ] **Step 3: Add non-vacuous mutations and secrecy scans**

Removing child dispatch, Seatbelt enforcement, browser isolation or changing the due wake to not-due makes the receipt fail. Plist, launchd-visible diagnostics and closed receipts are scanned for task, credential, path, URL and model sentinels. Every claimed zero counter has a mutation that increments it.

- [ ] **Step 4: Confirm cleanup before writing a receipt**

Remove the exact test LaunchAgent, terminate and confirm the owned process group, close browser/Playwright, and delete only the dedicated test roots through no-follow ownership. Any unknown cleanup blocks receipt creation and preserves identities for explicit recovery.

- [ ] **Step 5: Run final frozen-tree gates and independent review**

Run focused tests until Green, then once on the frozen source run `git diff --check`, full Ruff and full pytest. Build/seal/materialize once, rerun the full suite from materialized form, run three real wakes, write the bound receipt and require attestation Green. Fresh Product and Architecture reviews bind the exact core and host identities.

- [ ] **Step 6: Advance only the macOS profile status**

Only after U2B and both fresh reviews PASS set `019-macos-host-profile=qualified` and state “bounded background execution on macOS” for the exact qualified adapter set. Keep Linux, Windows and cloud profiles `not_qualified`; do not claim generic cross-platform unattended execution.

## Plan Self-Review Checklist

- [ ] The plan consumes the portable protocol and never forks schedule, claim, lifecycle or Runtime semantics by OS.
- [ ] launchd remains one replaceable wake adapter and never receives private authority.
- [ ] The POSIX supervisor proves real descendant cleanup and maps uncertainty to cleanup unknown.
- [ ] Seatbelt/Chromium/provider qualification occurs before occurrence effects and has no fallback.
- [ ] U2B status is independent of U2A; neither receipt overclaims the other.
- [ ] Full tests run once after focused Green/source freeze, followed by one materialized/full/real-wake/attestation chain.
- [ ] The plan contains no `TODO`, `TBD`, placeholder path, unbounded wait, commit or push step.

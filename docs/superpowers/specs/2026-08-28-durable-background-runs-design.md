---
title: "019 Portable Durable Automations"
date: 2026-08-28
status: frozen-user-approved-2026-08-28
authority: product-architecture
supersedes_plan_assumptions:
  - "launchd is the scheduler or product authority"
  - "one LaunchAgent per job"
  - "background execution shares an interactive session implicitly"
  - "provider credentials are provisioned into a wake adapter"
  - "Docker-backed 017 references"
  - "Claude-only executor rule"
---

# 019 Portable Durable Automations

## 1. Outcome

019 lets a user approve a bounded automation whose occurrences can be triggered while the
interactive Agent is idle or absent. Each occurrence runs through the already delivered
`AgentRuntime`, 017 sandbox inside an 019-owned isolated workspace and optional 018 governed
browser, then records an authoritative
completed, skipped, needs-human or unknown result.

019 is a portable automation control plane, not a macOS scheduler wrapped around an Agent.
The product core has no dependency on launchd, systemd, Cron, Kubernetes, a desktop window,
or a permanently live model process. A deployment supplies a wake adapter that asks the same
portable dispatcher to reconcile due work. Manual, server and OS-specific wake callers use the
same protocol without changing automation state or execution semantics. The first optional host
profile defined here uses macOS launchd, but portable-core acceptance and delivery do not depend
on installing, importing or qualifying that adapter.

019 is also not an unlimited autonomous daemon. No model process remains alive while waiting
for time, approval, recovery or user takeover. Every occurrence has an immutable authority
envelope, hard deadline, bounded calls and explicit terminal or needs-human state.

## 2. What the industry gets right

### 2.1 Codex: scheduling is outside the harness

Codex exposes the execution harness as a thread/turn protocol. A client starts or resumes a
thread, starts a turn, streams items and answers approval requests. Scheduled Tasks are a
separate product control plane: they choose a saved prompt, cadence, destination, sandbox and
workspace/worktree, then invoke the harness. Local scheduled work requires the computer and
desktop app to be running; hosted tasks use a different execution host.

The useful lesson is not Codex's private scheduler implementation. It is the boundary:

- the harness owns conversation, tool execution, sandboxing and approval;
- the scheduler owns when and where to request a run;
- a standalone run and a continuation in an existing chat are distinct product choices;
- scheduled code work should be isolated from an actively edited checkout;
- unattended work inherits an explicit sandbox policy and cannot improvise authority.

### 2.2 DeepSeek Harness: durable events are authority, timers are projections

DeepSeek Harness implements reminders as an opt-in, session-local Schedule plugin. Its Session
event log is the durable authority; timers and views are disposable projections rebuilt by
folding the log. Management changes use persistence barriers, due delivery claims an idle
maintenance phase, and overdue fixed intervals coalesce to the latest occurrence.

Its scope is intentionally narrower than 019: a cold session stays overdue until resumed,
dispatch means a follow-up was queued rather than completed, and a narrow crash window may
repeat delivery. Its webhook package is explicitly fire-and-forget with no queue, retry,
deduplication or completion state. Separately, its ACP server exposes persistent Agents to
external automation clients, and its credential subsystem stores only credential references in
configuration and resolves values at runtime.

The useful lesson is the separation of durable state, live timer ownership, external automation
protocol and credential resolution. 019 keeps that boundary but does not copy a general event
framework: its small bounded control plane uses the project's existing revision/CAS discipline.
DeepSeek's pieces also do not by themselves provide a cold-session, completion-aware,
idempotent automation product.

### 2.3 Durable schedulers: triggers are hints, occurrences are identities

APScheduler separates task, schedule and job. Kubernetes CronJob treats scheduling as
at-least-once, exposes misfire deadlines and concurrency policy, and tells workloads to be
idempotent. Temporal separates deterministic workflow decisions from effectful activities.
Apple documents launchd as a process wake mechanism whose interval events may be missed while a
machine sleeps or a job is still running.

019 combines these lessons without importing a distributed workflow engine:

- immutable automation definition, deterministic occurrence identity and Runtime checkpoint
  are separate records;
- every wake is only a request to reconcile durable state;
- timers, plist files and queue messages are replaceable projections, never completion proof;
- effectful work remains inside the existing Runtime/ToolRuntime path;
- dispatch, model completion and user acknowledgement are different facts.

## 3. The design improvement

019 has three planes with one-way dependency flow:

```text
Wake Adapter / external caller
          |
          v
Portable Automation Control Plane
  definition -> due resolution -> claim -> bounded receipt
          |
          v
  AutomationReconciler -> OccurrenceSupervisor
          |
          v
Existing Execution Harness
  AgentRuntime -> ContextManager -> ToolRuntime -> 017/018
```

### 3.1 Trigger plane

A trigger plane may be launchd, a manual CLI invocation, systemd, Cron, a queue consumer or a
hosted scheduler. It can only submit `ReconcileAutomationsV1` with a schema version and optional
opaque delivery id. It cannot select a local path or store in the payload, provide task text,
choose tools, approve effects, mutate conversation state or claim completion. The trusted local
composition pre-binds exactly one owner store. A future remote transport must authenticate its
caller and authorize that caller to a pre-bound store before it can invoke reconciliation.

Duplicate, early, late and reordered trigger requests are expected. The control plane rereads
durable state and the clock, so a trigger never proves that work is due.

### 3.2 Automation control plane

The control plane owns approved automation definitions, deterministic time resolution,
occurrence allocation, claims, bounded summaries and adapter projection state. It does not call
a provider or a tool callable. `AutomationReconciler` is the narrow effectful coordinator: it
asks `AutomationController` to claim or reconcile exact state transitions and asks an injected
`OccurrenceSupervisor` to manage one worker. The controller remains the only
`AutomationRepository` mutation client; the reconciler and supervisor never write either durable
store. The core defines the canonical snapshot/CAS contract but receives persistence and owned-
workspace operations through typed host capabilities. It does not implement a POSIX file lock,
Windows file handle, descriptor-relative walk or another host filesystem mechanism.

### 3.3 Execution plane

The reconciler asks an injected `OccurrenceExecutor` capability to initialize the exact
occurrence checkpoint before process launch. The supervisor receives only its locator, immutable
process specification and opaque claim capability. A qualified execution host implements that
port with the existing `ScheduledOccurrenceCaller.run_once()`, whose only production execution
entry is `AgentRuntime.run_turn`. The portable child protocol never imports a concrete checkpoint
store. The existing Runtime remains the sole model/tool loop and state mutation owner. A
qualified host-profile `OccurrenceSupervisor` provides the real wall-clock
deadline and descendant cleanup; it is not another Agent loop. The portable core knows only the
typed READY/start/result/cleanup contract and never imports POSIX process groups, Windows Job
Objects or another concrete process owner.

### 3.4 Single owners

- `AutomationController.handle(action)` is the only writer of `AutomationStore`. It owns strict
  load/validate/CAS around a deterministic control-plane reducer through the injected
  `AutomationRepository` and has no provider, model context or tool callable.
- `AutomationRepository` and `OwnedWorkspaceRepository` are host capabilities with closed
  conformance contracts. They persist opaque canonical snapshots and operate only on pre-bound
  owned roots; they cannot interpret schedules, grants, Runtime completion or task text.
- `AutomationReconciler` owns one bounded reconciliation call and process supervision. It can
  only submit typed controller actions and one exact occurrence to `OccurrenceSupervisor`.
- `OccurrenceSupervisor` is a host capability that owns child launch, READY/start handshake,
  deadline and descendant cleanup. It never writes `AutomationStore`, calls a provider directly
  or interprets Runtime completion. A host profile must prove its concrete process ownership;
  the portable core cannot assume POSIX process-group semantics.
- `OccurrenceExecutor` is a host capability that creates/loads the exact Runtime checkpoint and
  calls the existing scheduler caller once. It cannot reinterpret automation state or provide a
  second model/tool loop; the portable deterministic adapter is protocol evidence only.
- `AgentRuntime.run_turn` remains the only writer of conversation/Goal/effect state and the only
  production model/tool loop.
- CLI/TUI and wake adapters translate typed requests and render bounded replies; they never edit
  either store directly.
- `ContextManager`, `KernelToolRuntime`, 017 and 018 keep their existing exclusive ownership.

This is two explicitly different state domains, not two Agent runtimes: the automation domain
decides whether an immutable occurrence may be submitted; the Runtime domain decides what that
occurrence can do and whether it is complete.

Portability is enforced at this dependency boundary. The portable core may depend on typed wake,
repository, owned-workspace, occurrence-executor, supervisor, sandbox and browser capability
contracts, but it cannot
import launchd, systemd, Cron, `fcntl`, POSIX descriptor/open flags or process groups, Windows
file handles or Job Objects, Seatbelt or another concrete host backend. Host profiles qualify
those adapters independently. A missing host capability reduces which management or execution
operations are available on that host; it does not change schedule, claim, recovery or
completion semantics and does not make the core product macOS-only.

## 4. Durable authority

### 4.1 Revisioned `AutomationStore`

The portable core defines exactly one strict canonical snapshot under revision/CAS and an
`AutomationRepository` port that loads and conditionally commits that opaque document. A
qualified host adapter must persist it in an owner-only, no-follow, crash-safe store. The
snapshot is the automation authority; indexes, next-wake times and adapter registrations are
rebuildable projections. Core decode rejects unknown versions, extra fields, reused ids, invalid
revisions and impossible transitions before asking the adapter to commit.

This deliberately reuses the repository's proven checkpoint shape instead of introducing a
second event-sourcing framework or a second per-occurrence record family. The snapshot contains
revisioned mutable occurrence control state. Definition identity fields never change, and a
terminal history entry becomes immutable when the controller commits it. Detailed Goal, effect,
result and evidence facts remain only in the existing Runtime checkpoint.

The store records:

- approved immutable automation revisions and current control state;
- schedule cursor and deterministic occurrence identities;
- one active claim plus revisioned claim/dispatch/running control state;
- bounded terminal receipt metadata derived from the Runtime checkpoint;
- content-free ownership identities for the immutable source snapshot, occurrence workspaces,
  019-owned diffs/artifacts and Runtime checkpoint stores;
- exact wake-adapter projection digest and qualification status;
- bounded terminal history.

It does not store credential values, browser storage, command output, page text, model
transcripts, full Runtime facts or full tool receipts. Private task text stays in the owner-only
definition record and never enters a plist, trigger payload, wake diagnostic or external system
log.

### 4.2 Runtime checkpoint

The occurrence checkpoint remains authoritative for Goal, approval, `EXECUTING`, result,
evidence and completion state. `AutomationStore` may summarize that state but cannot reinterpret
or repair it. A completed scheduler receipt is valid only when derived from the authoritative
Runtime checkpoint.

019 extends that same Runtime authority with a durable provider-call boundary. Before every
background `provider.generate`, `AgentRuntime` saves `MODEL_EXECUTING` with exact invocation,
request, disclosure and occurrence-authority digests; a normalized model response is saved before
the next decision. Restart with an intent and no result becomes
`MODEL_OUTCOME_UNKNOWN`. The only v1 resolution is an exact user action that abandons the
unknown response, terminalizes the occurrence as failed and keeps the automation paused. It does
not retry or pretend to recover missing model output. `AutomationStore` only projects this
Runtime-owned state.

### 4.3 Disposable projections

The following are never authority:

- live timers;
- launchd plist/service state;
- queue messages or webhook deliveries;
- cached next-wake indexes;
- a worker PID or lock by itself.

They may be deleted and rebuilt from the canonical store without changing the meaning of an
automation or occurrence.

## 5. Automation contract

`AutomationDefinitionV1` freezes these fields into its identity digest. To avoid a circular hash,
`definition_body_digest` binds every field below except the grant itself;
`BackgroundAuthorityGrantV1` binds that body digest plus its closed capability members; final
`definition_digest` binds `definition_body_digest + grant_digest`. No component may substitute
only one of the pair:

- opaque `automation_id`, positive `revision`, private label and source-workspace binding digest;
- bounded task text (`1..4000` characters);
- `execution_mode=FRESH_OCCURRENCE`;
- provider descriptor and trust-profile digest, configured credential environment name and exact
  `ProviderDisclosure` request digest, never secret values;
- `ONCE_UTC` or `FIXED_INTERVAL_UTC` with canonical whole-second UTC anchor;
- required start, expiry, maximum occurrences, misfire grace and catch-up rule;
- occurrence deadline and model/tool/browser/sandbox/token budgets;
- exact isolated-workspace source snapshot and 017 environment policy digests;
- exact 018 public-read origin-policy digest when enabled;
- exact user-approved `BackgroundAuthorityGrantV1` digest and wake-adapter policy.

V1 deliberately supports only fresh occurrence checkpoints. A continuation mode that reuses one
growing conversation has different compaction, correction, authority and duplicate semantics and
requires a later explicit design. A needs-human occurrence is resumed in its own exact
checkpoint; the next scheduled occurrence never inherits its unresolved authority.

V1 bounds:

- at most 32 non-terminal automations per store;
- at most 128 full automation records and 128 compact purged tombstones per store;
- interval `60..2_592_000` seconds;
- expiry at most 366 days after activation;
- `max_occurrences 1..128`;
- hard deadline `30..3_600` seconds;
- misfire grace `0..3_600` seconds;
- model calls `1..16`, tool calls `1..32`, sandbox commands `0..16`, browser actions
  `0..32`;
- model input tokens `1..100_000` and model output tokens `1..20_000`, matching the existing
  Runtime invocation ceilings but requiring explicit finite values for background work;
- source snapshot at most 4,096 entries, 64 MiB total, 16 MiB per regular file and 1,024 UTF-8
  bytes per relative path; larger inputs fail before activation rather than truncating;
- retained diff at most 2,000 path entries and 4 MiB encoded; 019-owned retained artifacts at
  most 32 MiB per occurrence and 128 MiB per automation; exceeding either bound becomes
  needs-human before admitting another artifact;
- catch-up is `NONE` or `LATEST_ONE`; backlog replay is absent.

Updating an automation creates a new revision. Old occurrence identities and evidence remain
immutable and cannot be completed by the new revision.

### 5.1 Job-owned isolated workspace

019, not 017, owns background workspace isolation. Activation creates an owner-only immutable
source snapshot after bounded no-follow capture and records its manifest digest. Every occurrence
gets a fresh job-owned workspace materialized from that exact snapshot. The occurrence
composition binds 017 to this new root, so 017 `workspace-write` affects only the job-owned copy.
The current host checkout is never the background write root.

The portable core expresses scan, capture, materialize, terminal-output capture and owned-object
deletion through `OwnedWorkspaceRepository`. It validates canonical manifests, limits, ownership
identities and state transitions but never performs an OS directory walk itself. A concrete host
adapter must prove root anchoring, no-follow traversal, owner access and cleanup identity through
the shared conformance suite before activation is available on that host.

Snapshot capture rejects private/runtime roots, secret-name patterns, symlink traversal,
unsupported file types and configured file/count/byte limits. Snapshot or policy drift stops
before worker launch. A completed occurrence may expose a governed artifact reference and a
bounded diff against its source snapshot. Importing any change into the host workspace is a
separate interactive exact-approved action and is not part of 019 v1 automation execution.
Later edits to the source workspace do not change the pinned snapshot or stop an occurrence; they
make any later host import stale and require a fresh interactive comparison/approval.

The full occurrence workspace is temporary execution state, not retained result history. After a
safe terminal Runtime checkpoint, the reconciler first captures the bounded diff and 019-owned
artifacts, then deletes that exact workspace through the same root-relative no-follow ownership
contract used by purge. Confirmed cleanup removes its ownership entry; cleanup unknown preserves
the entry, pauses future occurrences and remains eligible for explicit purge recovery. A
needs-human, effect-unknown or cleanup-unknown occurrence keeps its workspace because deletion
would destroy recovery evidence.

The corrected 017 policy is host-readable by default, so it is not sufficient by itself for an
unattended grant. 019 defines one mandatory platform-neutral background confinement policy: file
reads default-deny except the materialized snapshot, job temp/HOME and an exact qualified
allowlist of product/runtime/toolchain literals; owner home, source workspace, automation state
and every other path remain unreadable. Network remains off. ToolRuntime binds this policy digest
before preparing a command, and an injected 017 confined-backend capability must prove exact
enforcement in the child. The portable core knows only that typed qualification/receipt contract;
it does not import or select a concrete sandbox backend. The existing macOS Seatbelt backend is
the first independently qualified host implementation. If a host cannot qualify an equivalent
strict read set, `sandbox_confined` is unavailable there and the Runtime may only produce an
exact command candidate for later human approval. There is no fallback to ordinary 017
host-readable mode or to an unconfined command.

The definition-bound environment-policy digest is the stable policy template: closed mode,
network class and exact qualified runtime/toolchain allowlist. Per-occurrence workspace,
temp and HOME roots are deliberately not part of that stable digest because every occurrence
must receive fresh paths. The host compiles those concrete roots into a separate instance digest;
the tool safety binding carries both digests, while the occurrence workspace identity binds the
fresh owned copy. Template drift, instance drift or workspace-identity drift all fail closed.

### 5.2 Background authority grant

`BackgroundAuthorityGrantV1` is minted only by the explicit activation approval and is bound to
the exact `definition_body_digest`, provider disclosure, isolated workspace, capabilities,
budgets and expiry. The final definition digest then binds the resulting grant digest as defined
in §5. It authorizes two closed unattended classes:

- `sandbox_confined`: shell-free 017 commands inside the exact job-owned workspace, with network
  off, no credential environment, no `danger-full-access` and the approved command count/deadline;
- `browser_public_observe`: 018 `PUBLIC_READ_EPHEMERAL` open plus only actions classified by the
  existing browser policy as `OBSERVE`, within the exact approved HTTPS origin policy.

The typed activation receipt carries the exact `ProviderDisclosure` acknowledgement. Fresh
occurrence initialization may project that receipt into the checkpoint only when Runtime
recomputes the same provider destination, model, trust profile and complete data-class set,
including source snapshot, command output and public browser content when enabled. Any mismatch
pauses before the first provider send; the controller cannot manufacture or broaden disclosure.

This is a Runtime-owned input to `KernelToolRuntime`, not a scheduler approval. ToolRuntime is the
only component that can consume it. Each prepared action must match the exact grant and current
occurrence identity; budget, expiry, revision, policy or target-class drift fails closed. The
grant never authorizes site-bound profiles, browser `DISCLOSE`/`DOWNLOAD`/`UPLOAD`/`COMMIT`,
sandbox network, host-workspace writes or automation-management tools. Those actions persist the
existing exact approval candidate and make the occurrence `needs_human`.

Activation authority alone is insufficient to run an occurrence. The trusted reconciler
generates a random opaque `BackgroundOccurrenceAuthorityV1` inside a typed claim request. The
deterministic controller validates the request and makes that capability authoritative only by
successfully CAS-committing it with the automation revision, occurrence identity, claim fencing
token, checkpoint identity, grant digest and deadline. Only the active-claim record stores the
raw capability; the Runtime checkpoint and every `ExecutionIntent` store its digest. The
reconciler may inject the raw capability only into the matching background composition, and
ToolRuntime verifies the current active claim, definition grant and occurrence authority before
both prepare and invoke. Ordinary scheduler/headless composition cannot construct or inject it.
Terminal claim, token/revision/checkpoint drift or cross-occurrence reuse invalidates it. Pause
and `cancel_pending` prevent new claims but do not retroactively revoke an already admitted
Runtime effect. `cancel_pending` is nevertheless part of the live claim check: it rejects a new
prepare or an invocation that had not begun when cancellation was committed. Pause is only a
scheduling control and deliberately leaves the current occurrence unchanged.

## 6. Schedule and occurrence semantics

`ScheduleResolver` is a pure function over `(definition, store snapshot, now_utc)`. It returns one
closed decision: `not_due`, `due`, `misfire_skipped`, `expired`, `max_reached`, `paused`,
`cancel_pending`, `canceled` or `needs_human`. `cancel_pending` and `canceled` can never create a
new claim; only `canceled` is terminal. The resolver never reads a clock, filesystem, adapter or
Runtime.

The occurrence identity is:

`automation_id + revision + occurrence_index + scheduled_for_utc + definition_digest`.

Rules:

- delivery is at-least-once; execution is idempotent by exact occurrence identity;
- v1 concurrency is global `FORBID`; an active claim prevents allocation of any different
  occurrence. A later reconciler may recover only that exact claim under its existing fencing
  token and a proven pre-start or terminal state;
- a duplicate trigger loads/replays the same checkpoint and performs zero duplicate
  provider/tool effect;
- `NONE` evaluates only the next unresolved slot: it claims it when still inside grace and marks
  only that slot `misfire_skipped` when grace elapsed; it never jumps over unresolved slots;
- `LATEST_ONE` atomically skips superseded unresolved slots and selects at most the most recent
  eligible slot; it never replays a backlog of effects;
- a late occurrence outside its grace is durably `misfire_skipped`;
- pause and `cancel_pending` block new claims without pretending to undo active effects;
- `needs_human`, effect unknown, cleanup unknown, identity drift or fatal conflict pauses future
  occurrences until explicit user resolution or cancellation;
- dispatch means the occurrence was admitted to the supervisor; only Runtime evidence can make it
  completed.

The nonblocking control-plane repository lease is held only around load/resolve/CAS mutations
and is released before waiting for a worker. Its concrete locking primitive belongs to the host
repository adapter and is separately qualified. It is never held for the occurrence deadline. Global
`FORBID` is enforced by the active occurrence state plus claim fencing token in the canonical
snapshot, not by a long-held process lock. Pause, cancel and status remain available while a
worker runs. Pause takes effect for future claims immediately. Cancel becomes `cancel_pending`,
also blocks future claims immediately, and becomes terminal `canceled` only after the active
occurrence reaches a safe terminal checkpoint. A needs-human checkpoint leaves cancellation
pending until the user resolves or abandons that occurrence through Runtime. Neither action can
revoke or rewrite an effect already admitted by Runtime; `cancel_pending` prevents the next
not-yet-invoked action at ToolRuntime's live claim check.

## 7. Background authority envelope

Activating an automation requires an exact user-approved preview. The preview is human-first and
shows, in this order:

1. task, cadence, next run, expiry and cancel path;
2. source workspace and the fact that writes stay in a fresh job-owned copy;
3. unattended capabilities, prohibited actions and the exact point where work stops for a human;
4. provider destination, model, trust profile and data classes sent remotely;
5. public browser origins, sandbox/network mode, artifact/result location and all budgets;
6. configured credential purpose and environment name, never its value;
7. wake availability and recovery behavior.

Digests are secondary verification detail, not the user explanation. Any unresolved field or
identity drift blocks activation. Approval authorizes future occurrence starts and the two exact
classes in `BackgroundAuthorityGrantV1`; it grants nothing outside that immutable envelope.

An unattended occurrence may:

- use confined 017 commands/tests/builds in its fresh job-owned workspace and create governed
  artifacts or a bounded diff;
- use 018 public-read observation and bounded `OBSERVE` navigation on approved HTTPS origins;
- produce job-owned summaries and references to existing governed artifacts;
- stop with an exact candidate that requires later human approval.

It may not automatically:

- modify or merge into the host workspace;
- use a site-bound browser profile or personal browser state;
- perform browser COMMIT/DISCLOSE, purchase, send, publish, delete or account changes;
- broaden filesystem, network, origin, profile or credential authority;
- call ungoverned host shell, read a personal browser profile, schedule another automation,
  modify its own code/policy or persist new authority.

If approval is required, the existing Runtime persists `AWAITING_APPROVAL` or
`AWAITING_RECOVERY` and the worker exits. The scheduler cannot answer the approval. Background
composition exposes no automation-management tools.

Unlike Codex's optional direct-checkout scheduled mode, 019 v1 never gives a background run
direct host-workspace mutation. Resolving one blocked occurrence never resumes the automation
implicitly: after the exact checkpoint reaches a safe terminal state, the automation remains
paused until the user performs a separate `resume` action.

## 8. Trigger adapters

### 8.1 Portable `ReconcileAutomationsV1`

The stable public boundary is a typed reconciliation request, not an OS configuration. Manual
CLI, tests, local adapters and future server callers all invoke the same entry point. A local
owner CLI may select a store through its trusted OS-owner configuration before constructing the
reconciler; an untrusted request never carries a store locator. The reply is a bounded closed
summary and never includes task text, credential references or Runtime content.

The installed `first-agent-schedule reconcile` command and its store/recovery semantics are the
platform-neutral baseline. Any conforming external scheduler may invoke it. Cold wake is present
only when the current host has a separately qualified adapter; lack of one never changes the
portable-core delivery status or introduces an in-product timer daemon.

### 8.2 Optional macOS launchd cold-wake adapter

The optional macOS host profile's launchd adapter owns exact render/install/readback/remove of one
global LaunchAgent. It invokes the installed `first-agent-schedule reconcile` executable with the
fixed product state root selected by trusted composition and no shell. The plist does not accept
an arbitrary user-supplied store path.

The plist uses an exact allowlist: fixed product label, fixed installed executable path, fixed
`reconcile` argument, bounded `StartInterval` and launchd-required metadata. It contains no
user-supplied path, workspace/store locator, automation id, task, URL, browser profile,
credential or model-authored string. `StartInterval` is only a bounded wake hint. Production does
not parse human-readable `launchctl print` output; exact file digest and command exit class are
the only stable readback inputs. Unknown bootstrap/bootout outcome stays unknown until
reconciled.

Adapter stdout/stderr, launchd logs, exit diagnostics and exception rendering contain only
closed status codes, counts and digests. They never contain tracebacks, absolute paths, task or
label text, credential references, Runtime/provider/tool/browser content or model text.

The adapter is optional. Its absence does not change core automation semantics; it means cold
wake is unavailable and manual or another external caller must trigger reconciliation.

### 8.3 Other hosts

Linux systemd timers, Kubernetes CronJobs, hosted queues and event adapters are future deployment
adapters over the same typed boundary, not alternate scheduler implementations. A server adapter
may add a lease backend, but it cannot change occurrence identity, misfire semantics, authority
or completion rules.

This makes the architecture portable while keeping evidence honest: 019 can deliver the core
independently, qualify a macOS host profile separately, and leave unimplemented Linux, Windows or
cloud profiles explicitly unqualified rather than treating one OS as product authority.

## 9. Credentials and execution-host identity

019 v1 reuses the existing owner-only `ProviderProfileV1`, `ProviderDescriptor` and composition-
root environment lookup. It does not add a speculative `CredentialResolver` interface. The
automation records only the non-secret profile/descriptor digest, trust-profile identity and
configured environment-variable name; no scheduler, wake adapter, store or Runtime checkpoint
can read or persist the secret value.

The trust-profile identity is an owner-attested statement of the approved principal/trust domain.
Secret material may rotate without rewriting the automation only when the owner keeps that
identity unchanged for the same principal, tenant, destination and scopes. Changing the declared
profile requires re-approval; descriptor, environment-name or trust-profile drift produces
`NEEDS_019_CONFIG(provider_profile_identity_drift)` before provider, browser or sandbox
composition. V1 can prove those configured identities and credential availability, but it cannot
independently prove that a new secret value placed under the same environment name still belongs
to the attested principal, tenant or scopes. A provider-specific principal attestation is a later
separately approved capability; 019 does not claim automatic credential re-binding detection.
019 v1 also does not silently create a secret file, copy secrets into launchd, call `launchctl
setenv`, add Keychain support or invent a credential broker.

This deliberately limits the first launchd adapter: credentialed cold wake is qualified only when
the same owner launch environment already exposes the configured credential through approved
host setup. Otherwise the adapter reports `credential_unavailable` and the owner must use a
foreground/manual trigger or a credential-free local provider. 019 does not claim to deliver
secure macOS credential provisioning; adding Keychain is a later separately approved capability.

Adapter qualification must prove, with booleans and digests only, that its execution host can
resolve every required environment name and governed resource. This is an availability and
configuration check, not a secret-principal attestation. A missing credential produces
`NEEDS_019_CONFIG(credential_unavailable)` before provider, browser or sandbox composition. A
working interactive shell is not evidence that launchd or a server worker can resolve the same
configuration.

Local workspace automations are naturally tied to the host that owns that workspace. The
automation protocol is not. Moving a definition to another host requires an exact matching
workspace snapshot/binding, policy digests, provider/trust-profile identity and composition-root
credential availability; otherwise it fails closed rather than pretending to be portable data.

## 10. Reconciliation and worker supervision

One reconciliation call:

1. reads the clock once;
2. acquires the short nonblocking control-plane lease;
3. loads and validates the exact store revision;
4. resolves the earliest decision ordered by `(scheduled_for_utc, automation_id)`;
5. claims at most one exact occurrence with CAS and releases the lease;
6. creates and validates the fresh occurrence checkpoint before provider/tool composition;
7. launches one occurrence child in a verified process group; the child may only report `READY`;
8. reacquires the lease and CAS-commits `DISPATCHED` with claim token, checkpoint identity and
   process identity, then sends the one-shot start permit;
9. after the child acknowledges the permit and enters `AgentRuntime.run_turn`, reacquires the
   lease and asks the controller to commit `RUNNING`; missing acknowledgement leaves the exact
   dispatch outcome unknown rather than inventing running state;
10. waits outside the lease under the occurrence hard deadline;
11. reacquires the lease, asks the controller to derive a bounded summary from the authoritative
    Runtime checkpoint, commits the terminal/needs-human state and exits.

When no work is due, it exits before provider, browser or sandbox composition. It never sleeps
until the next due time and never holds credentials between occurrences.

The READY/start barrier is fail closed. A child cannot call provider or ToolRuntime before the
start permit. If the parent cannot prove whether the permit was sent, the occurrence is unknown;
it is never automatically redispatched. READY and start-acknowledgement each have a short bounded
timeout; timeout cleanup must confirm the exact process group is gone before the claim can move
out of cleanup-unknown.

After a crash, the next caller reacquires the lease and loads the exact control state and
checkpoint:

- `CLAIMED` before child launch, or a child that proved it never received start: safe to dispatch
  the same occurrence with the same fencing token;
- start-permit outcome unknown: needs human, zero automatic replay;
- Runtime `MODEL_EXECUTING` without a normalized response: `MODEL_OUTCOME_UNKNOWN`; the owner may
  abandon it as a failed occurrence, but no caller can replay the provider call automatically;
- known-not-executed: bounded Runtime repair may proceed;
- `EXECUTING` without result or cleanup unknown: needs human, zero automatic replay;
- terminal result: replay the authoritative report, zero new effect.

If the deadline supervisor terminates the child, it records only `worker_deadline`; it never
invents a Runtime result. Process-group cleanup must be bounded and confirmed. Unknown cleanup
blocks future occurrences.

## 11. Management and partial failure

`first-agent-schedule` is the required v1 management surface. Its public typed actions cover
`create`, `preview`, `approve`, `list`, `show`, `open`, `update`, `pause`, `resume`, `cancel`,
`purge`, `wake enable/disable` and `reconcile`. TUI may later reuse exactly those actions/results
but is not a v1 parity requirement and cannot add state semantics. The model may help draft a
proposal but cannot activate it.

Lifecycle semantics are closed:

- `create` stores an inactive proposal; `approve` requires the current complete human-first
  preview and atomically activates that exact revision;
- `update` creates an inactive draft revision while the old approved revision remains active and
  continues to own future claims. Approving the new preview atomically changes the active
  revision, prevents new claims for the old revision and marks its unresolved future slots
  `superseded`. An already active old-revision occurrence continues under its original immutable
  grant and claim; the preview states this cutover behavior before approval;
- `pause` blocks future claims and leaves an active Runtime untouched;
- resolving a blocked occurrence leaves the automation paused; only a separate `resume` after a
  safe terminal checkpoint permits future claims;
- `open` is a typed handoff into the existing Runtime recovery UI for one exact occurrence
  checkpoint. There the user may inspect and submit the existing typed approve, reject, recover
  or abandon actions. The automation layer cannot answer an approval, mutate Runtime state or
  synthesize completion; returning from the handoff refreshes `show` from both durable stores;
- `cancel` with no active occurrence commits terminal `canceled`. With active work it commits
  `cancel_pending`, immediately blocks every future claim and prevents the next not-yet-invoked
  Runtime action through ToolRuntime's live claim check. Work already executing is not interrupted
  or rewritten. A needs-human occurrence still requires `open` and an explicit Runtime resolution
  or abandon action; once the exact occurrence is safely terminal, the controller commits
  `canceled`. Cancel never claims rollback, process termination or authority to approve the
  blocked action;
- `wake disable` refuses while an occurrence runs and reports that due work will require manual
  reconciliation;
- `purge` is user-only and allowed only for terminal definitions whose occurrences have no
  running, needs-human, effect-unknown or cleanup-unknown state. Before mutation, the CLI renders
  an irreversible human-first preview with the automation identity, occurrence/checkpoint count,
  019-owned snapshot/workspace/artifact/diff count, governed external references that will only
  be unlinked, resulting tombstone, loss of detailed results/evidence and the fact that deletion
  cannot be undone. The user's explicit confirmation is bound to that exact preview digest;
- after confirmation, the controller CAS-commits `PURGE_PENDING`, removes private definition
  content and freezes a content-free ownership manifest. Each 019-owned source snapshot,
  occurrence workspace, diff/artifact and Runtime checkpoint is named only by an opaque relative
  id under its fixed pre-bound owner root, expected object type and expected object/digest
  identity. Governed artifacts owned outside 019 are never deleted; their references are only
  removed. The reconciler performs only this lifecycle cleanup, resolves every id under its fixed
  root with component-by-component no-follow checks, revalidates identity immediately before
  deletion and never decodes or mutates Runtime state. Missing/already-deleted objects are
  idempotent only when the durable cleanup progress proves they were previously confirmed;
  replacement or identity drift becomes cleanup unknown;
- after every owned object is confirmed deleted and every external reference is unlinked, the
  controller commits `PURGED`. Partial deletion or a crash leaves an idempotently resumable
  manifest and progress bitmap in `PURGE_PENDING`; it can never restore definition authority or
  free the full-record slot early.

At most 128 full automation records exist in one v1 store; confirmed purge frees one full-record
slot. Up to 128 compact `PURGED` tombstones are retained separately. When that tombstone bound is
exceeded, the controller evicts the oldest confirmed tombstone; stale wake payloads cannot name
an automation and newly created opaque ids are random and collision-checked. There is no
automatic deletion of full records, retained 019-owned objects or Runtime checkpoints outside an
exact confirmed purge. The only routine object deletion is the exact terminal occurrence
workspace cleanup defined in §5.1. Reaching the full-record bound blocks creation and shows
safe-terminal `purge` candidates rather than silently removing private state.

The first activation may install a wake adapter before committing the active definition:

- install fails or is unknown: no automation is activated;
- install succeeds but activation CAS fails: an idle adapter finds no due work;
- retry first reconciles the exact adapter digest, then performs only the missing mutation.

The user-visible activation states are `proposal`, `not_activated_install_failed`,
`not_activated_install_unknown`, `adapter_installed_activation_conflict` and `active`. Every
non-active state says that no occurrence can run, preserves the proposal and presents one safe
next action: retry qualification, inspect/remove the idle adapter or resubmit approval.

Adapter drift is never overwritten as compatibility repair. Disabling the last wake adapter is a
separate exact-approved action and refuses while an occurrence is running.

## 12. Owner-visible results and recovery UX

019 v1 has no system-notification or external-delivery subsystem. `list`, `status` and `show` are
owner-local projections and never become authority. A later notification channel requires a
separate approved design rather than a generic policy field in `AutomationDefinitionV1`.

The automation status view distinguishes:

- next occurrence and trigger availability;
- occurrence dispatched vs running vs completed;
- needs approval, needs recovery, deadline and cleanup unknown;
- adapter unavailable vs credential unavailable vs isolated snapshot drift vs host import drift.

`show` gives every blocked occurrence one executable next action:
`first-agent-schedule open <automation> --occurrence <index>`. The CLI resolves those public
identifiers through the owner store and hands the exact checkpoint to the existing Runtime
recovery UI; the user never copies an internal digest and never grants authority to the scheduler
itself. If the checkpoint identity or automation revision has drifted, `open` fails closed and
returns to the status view without provider or tool work.

Detailed `show` works for unpurged terminal and blocked occurrences. It derives a bounded result
view from the authoritative Runtime checkpoint and may expose only the existing final summary,
governed artifact/evidence references, next action and cleanup state. `AutomationStore` does not
copy the result content. A `PURGE_PENDING` view reports cleanup progress; a retained `PURGED`
tombstone reports only closed identity/status, and an evicted tombstone is `not_found`. The status
page shows occurrence state and automation state together, so a user who resolves one occurrence
can see that future scheduling remains paused until explicit `resume`.

## 13. Acceptance contract

### U0 — frozen design

Freeze this architecture, typed schemas, closed statuses and v1 limits before product code. The
old 019 implementation plan remains stale until this spec is approved and replaced.

### U1 — portable deterministic gates

Prove at minimum:

- strict snapshot decode, CAS, corruption rejection and rebuildable projections through a
  deterministic repository adapter; one reusable adapter-conformance suite proves owner-only,
  no-follow and crash-safe storage for each host profile rather than embedding an OS file API in
  the core;
- once/interval UTC resolution, exact `NONE`/`LATEST_ONE` behavior, misfire,
  pause/resume/cancel/purge, expiry and maximum occurrences;
- update leaves the old revision live until approval, performs one atomic future-claim cutover,
  supersedes only unresolved old slots and never rewrites an active old-revision occurrence;
- cancel during active work becomes `cancel_pending`, blocks every future claim immediately and
  reaches `canceled` only after an explicit safe terminal/abandon path;
- duplicate, overlap, crash and deadline paths perform zero duplicate provider/tool calls or
  effects for any persisted exact intent; an ordinary occurrence may consume its declared
  multi-call budgets;
- READY-before-DISPATCHED, dispatched-before-start and start-outcome-unknown fault injections
  prove the worker cannot call provider/tool before the durable barrier;
- provider-in-flight crash leaves Runtime-owned `MODEL_EXECUTING`, becomes
  `MODEL_OUTCOME_UNKNOWN` and performs zero automatic replay; exact abandon terminalizes only
  that occurrence;
- dispatch cannot masquerade as Runtime completion;
- `not_due` exits before provider/browser/sandbox/credential resolution;
- trigger callers are bound to one store; payloads cannot choose a path or store;
- trigger payloads, receipts, stdout/stderr and wake/crash diagnostics omit secrets, paths and
  private task content;
- background composition contains no automation-management or self-authorizing path;
- automation-grant mutation, expiry, budget reuse and capability broadening fail closed in
  ToolRuntime before effect;
- direct `ScheduledOccurrence` construction, stale claim token and cross-occurrence grant reuse
  cannot produce a valid `BackgroundOccurrenceAuthorityV1` and perform zero effect;
- ToolRuntime revalidates the active claim at both prepare and invoke; a `cancel_pending` race
  cannot admit a not-yet-invoked action while an already executing effect is reported truthfully;
- every sandbox write lands only in a fresh isolated occurrence workspace; host workspace
  mutation count remains zero;
- snapshot file/count/path/byte and retained diff/artifact bounds fail closed without partial
  capture through the owned-workspace port; its deterministic adapter proves core state
  semantics, while each host profile separately proves real no-follow capture and cleanup.
  Cleanup unknown preserves the exact ownership entry and pauses future work;
- reading any ordinary owner file outside the strict background read allowlist fails before its
  content can enter a tool result or later provider context;
- configured provider descriptor/environment/trust-profile, isolated snapshot, policy and
  adapter drift fail before occurrence effects; tests and receipts do not claim to attest the
  principal behind a replaced secret value; host import drift blocks only the separate
  interactive import;
- fake trigger adapters can be deleted/reordered/duplicated without changing authority;
- purge requires a digest-bound irreversible preview; path replacement, partial deletion and
  crashes before/after each owned snapshot/workspace/diff/artifact/checkpoint deletion converge
  through `PURGE_PENDING`; external governed artifacts are only unlinked, detailed `show` becomes
  unavailable only after deletion is confirmed, and purge frees full-record capacity only after
  every owned object is gone;
- `show` exposes an executable `open` handoff for an exact blocked occurrence; approve, reject,
  recover and abandon remain Runtime-owned and automation resume remains a separate action;
- every claimed counter and false-completion guard has a non-vacuous mutation.

### U2A — sealed platform-neutral core journey

From a materialized sealed wheel, drive the public `first-agent-schedule` management surface
through create, human-first preview, approval, list/show/open, update cutover, pause/resume,
active-work `cancel_pending`, terminal cancel and irreversible purge preview. Then drive the
public reconciliation protocol directly and prove three fresh occurrence stores. A deterministic
repository/owned-workspace adapter and deterministic supervisor exercise the exact CAS,
workspace and READY/start/result protocols without adding a second controller path; this is core
protocol evidence, not host-filesystem qualification. The existing `ScheduledOccurrenceCaller`
separately proves that an admitted no-tool occurrence enters the only `AgentRuntime.run_turn`. A consequential candidate becomes
`NEEDS_019_CONFIG(supervisor_unavailable)` or needs-human when no qualified unattended host
capability is attached. The journey also proves exact occurrence resolution plus separate
automation resume, duplicate zero effect, deadline/cleanup state projection, terminal result
retrieval and bounded receipts. Snapshot materialization and host-workspace mutation zero remain
non-vacuous even when the occurrence has no sandbox grant.

Mutations must make the journey fail when activation omits disclosure, a missing host capability
is treated as approval, later host edits alter the pinned occurrence snapshot or receive an
automatic merge, `show` uses AutomationStore content instead of the Runtime checkpoint, or
resolving an occurrence silently resumes future claims.

This journey imports no launchd, systemd, Cron, `fcntl`, POSIX descriptor/process ownership,
Windows file/process ownership, concrete secure-filesystem or process supervisor, Seatbelt or
concrete browser backend. It is the delivery evidence for the platform-neutral automation
control core and public reconciliation protocol; it is not evidence that durable host storage or
unattended execution is qualified on an arbitrary host.

### U2B — optional qualified macOS host-profile journey

Under a dedicated owner-only test root and exact test label, independently qualify the concrete
macOS profile: owner-only no-follow automation/workspace repositories, existing 017 Seatbelt
confinement, 018 Playwright/Chromium public observation and launchd cold wake plus a POSIX
process-group `OccurrenceSupervisor`. Prove three real launchd
wakes invoke the same reconciliation protocol. One due wake must launch the READY/DISPATCHED
worker, enter the same Runtime checkpoint and produce an
authoritative terminal or needs-human receipt while the real confined/browser capability is
exercised. One exact duplicate must add zero provider/tool calls or effects. One not-due or
misfire wake must stop before composition. The journey also proves sleep/misfire simulation,
task/credential/path-free logs, a plist containing only the fixed executable/reconcile allowlist,
and cleanup of the LaunchAgent, worker process group, browser session and test roots. The plist
and diagnostics must contain no user-supplied, workspace, store, task, credential, URL or
model-authored value. Cleanup unknown blocks PASS. Removing child dispatch, Seatbelt enforcement,
browser isolation or changing the due wake to `not_due` must make the journey fail.

This journey qualifies only the optional macOS host profile. Its absence or failure does not
downgrade a Green U2A portable-core result, and it does not support a claim that Linux, Windows or
cloud host profiles are qualified. Another host becomes qualified only through an equivalent
backend/adapter receipt; no schedule or Runtime semantics may fork by platform.

Each receipt binds the source seal, verifier, runner, wheel, exact adapters/backends, provider
fixture and fresh stores that it actually exercised. Receipts contain only closed booleans,
counts and digests; a core receipt cannot imply host-profile qualification, and a macOS receipt
cannot redefine portable-core authority.

### U3 — fresh independent review and split status

Two fresh read-only axes must independently PASS for the portable core:

- Spec/Product: ordinary create/preview/approval UX, scheduling semantics, needs-human/resume,
  result retrieval, lifecycle effects, duplicate/false-completion mutations, secrecy and U2A;
- Standards/Architecture: unique Runtime/ContextManager/ToolRuntime owners, three-plane
  dependency direction, AutomationStore/Runtime checkpoint separation, cleanup, credential seam,
  fallback, second loop and concrete platform imports absent from the core.

After U0, U1, U2A and both core review axes PASS, status may become
`019-portable-control-core=accepted/delivered` without any qualified host repository, OS wake or
supervisor adapter. That status alone never claims durable local management or runnable
unattended execution. Claiming
`019-macos-host-profile=qualified` and “bounded background execution on macOS” separately requires
U2B plus fresh Product and Architecture review of that profile. Failure or absence of U2B leaves
the portable-control-core status unchanged. Linux, Windows and cloud profiles remain
`not_qualified` until their own supervisor/backend/adapter receipts exist.

Any ordinary source fix invalidates the affected seal/materialized/receipt. Detached review binds
the final identities and states exactly which independent status is being advanced.

## 14. Explicitly rejected designs

### 14.1 launchd as product scheduler

Rejected because it binds core semantics to one OS and makes plist state look authoritative.
launchd is retained only as a replaceable wake adapter.

### 14.2 one OS job per automation

Rejected because partial updates span two authorities and job count multiplies OS lifecycle
state. One adapter registration reconciles the owner AutomationStore.

### 14.3 private in-product timer daemon

Rejected because it creates a hidden long-lived lifecycle owner and still cannot provide cold
wake reliably. A live timer may later be a disposable trigger projection, never a scheduler.

### 14.4 fire-and-forget webhook or queue

Rejected as the durability boundary. External delivery may wake reconciliation, but dedup,
claims, completion and recovery remain in the control plane.

### 14.5 persisted provider secrets in jobs or adapter configuration

Rejected. Definitions carry references; the execution host resolves them. A new secret store or
Keychain provider requires separate explicit approval and threat review.

### 14.6 bundled APScheduler, Temporal, Redis or database service

Rejected for v1. They solve wider multi-node problems and would add a second operational system
before this local product needs one. The typed trigger boundary leaves that future deployment
choice open.

### 14.7 an "everything is a plugin" framework

Rejected for this kernel. DeepSeek Harness benefits from a broad composition ecosystem, but
copying that meta-framework would introduce a service locator and replace compile-time ownership
with dynamic capability discovery. 019 adds one deployment seam justified by real callers: the
typed wake adapter. Credential lookup stays in the existing provider profile/composition root.
Schedule semantics, claims and receipts remain closed product modules, not third-party plugins.

### 14.8 a v1 notification subsystem

Rejected until one concrete delivery channel and privacy contract are approved. Owner-local
status and `show` complete the v1 recovery loop without adding another delivery lifecycle.

## 15. Primary sources

- OpenAI, Codex as a platform and open agent harness:
  https://developers.openai.com/blog/codex-as-a-platform
- OpenAI, Codex App Server thread/turn/approval protocol:
  https://developers.openai.com/codex/app-server
- OpenAI, Scheduled Tasks:
  https://developers.openai.com/codex/automations
- OpenAI Codex open-source app-server protocol:
  https://github.com/openai/codex/tree/main/codex-rs/app-server
- DeepSeek Harness official overview:
  https://www.deepseek.com/harness/en/
- DeepSeek Harness session-local Schedule:
  https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/schedule/schedule
- DeepSeek Harness ACP automation server, webhook and credential families:
  https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/acp
  https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/webhook
  https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/credentials
- Apple launchd job guidance and local `launchd.plist(5)` / `launchctl(1)` manuals:
  https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html
- Kubernetes CronJob:
  https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/
- APScheduler:
  https://apscheduler.readthedocs.io/en/3.x/userguide.html
- Temporal durable workflow model:
  https://github.com/temporalio/sdk-python

## 16. Approval effect

Approving this document approves only the 019 architecture and v1 product boundary. It does not
mint a `BackgroundAuthorityGrantV1` or approve a real automation, launchd installation, provider
credential, browser action, sandbox command or host merge. Each real grant still requires its
own human-first activation preview and typed approval. Approval also accepts the split delivery
status: the portable control core is not gated by an OS host profile, it alone does not claim
runnable unattended execution, and no concrete host profile is called qualified without its own
real supervisor/backend/adapter receipt. After approval, replace the stale implementation plan
through the writing-plans workflow, review it for feasibility, then implement Red tests first.

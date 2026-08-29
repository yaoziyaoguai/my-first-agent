# 019 Portable Automation Control Core — E3 Acceptance Contract

- Status: frozen from `docs/superpowers/specs/2026-08-28-durable-background-runs-design.md`
- Product status under test: `019-portable-control-core`
- Host-profile status: independent; no U2A result may qualify durable host persistence or unattended execution
- Public surface: `first-agent-schedule` management commands and `ReconcileAutomationsV1`

## 1. Evidence boundary

U2A proves platform-neutral definitions, schedule resolution, lifecycle, authority binding,
controller/repository semantics, READY/start/result protocol, Runtime/ToolRuntime integration and
bounded owner-visible results. It uses deterministic repository, owned-workspace, supervisor and
occurrence-executor adapters. These adapters exercise the same ports and mutation guards but do
not prove an OS file lock, no-follow traversal, process-group cleanup, wake service, sandbox or
browser backend.

The only allowed U2A delivery statement is:

`019-portable-control-core=accepted/delivered`

It must be accompanied by: “No host profile is qualified by this receipt; durable local
management and unattended execution remain unavailable until an independent host-profile receipt
passes.”

## 2. Closed portable claims

| Claim | Required evidence |
|---|---|
| C1 | Strict immutable definition/body/grant/final digests; any authority-field mutation changes identity. |
| C2 | Canonical whole-second UTC once/interval resolution; exact NONE/LATEST_ONE, misfire, expiry and max semantics. |
| C3 | Repository codec rejects malformed/extra/impossible state; short-lease CAS has one winner and rebuildable projections. |
| C4 | At most 32 non-terminal, 128 full records, 128 occurrences and 128 tombstones; only confirmed purge frees capacity. |
| C5 | Create is inactive; current human-first preview digest and source manifest are both required for activation. |
| C6 | Update keeps old revision active until approval, atomically cuts future claims and never rewrites an active old occurrence. |
| C7 | Pause blocks future claims only; active-work cancel becomes cancel_pending and blocks the next not-yet-invoked action. |
| C8 | Trigger payload cannot select a store/path/task/tool; duplicate/early/late/reordered requests reread authority. |
| C9 | Reconcile claims at most one earliest occurrence and stops before composition when not due. |
| C10 | READY precedes durable DISPATCHED; durable dispatch precedes start permit; unknown permit outcome is not replayed. |
| C11 | Provider intent is durable before send; response is durable before consumption; intent without response becomes MODEL_OUTCOME_UNKNOWN with zero replay. |
| C12 | Dispatch, worker exit or scheduler summary cannot manufacture Runtime completion. |
| C13 | Direct occurrence construction, stale claim token and cross-occurrence capability reuse perform zero provider/tool effect. |
| C14 | ToolRuntime alone interprets the background grant and revalidates the live claim at both prepare and invoke. |
| C15 | Only exact sandbox_confined and browser_public_observe classes are eligible; every broader action remains needs-human. |
| C16 | Model/tool/sandbox/browser/token budgets are durable and cannot be reset by restart or duplicate delivery. |
| C17 | Deterministic owned-workspace semantics pin one immutable snapshot, materialize a fresh copy and never merge host changes. |
| C18 | Snapshot/diff/artifact bounds fail before partial authority; safe-terminal cleanup precedes ownership removal; unknown pauses. |
| C19 | Provider/trust/disclosure/snapshot/policy/adapter drift fails before occurrence effects; credential value/principal is not claimed. |
| C20 | External payloads, diagnostics and receipts contain no task, credential, absolute path, model, browser or tool-result content. |
| C21 | Blocked show exposes one exact open handoff; Runtime owns approve/reject/recover/abandon and automation resume stays separate. |
| C22 | Purge is digest-bound, terminal-only, crash-resumable and no-follow at the host port; external governed artifacts are unlinked only. |
| C23 | Background composition exposes no automation-management tool or alternate model/tool loop. |
| C24 | Every zero counter, completion guard and claimed transition has a mutation that makes the claim false. |
| C25 | Portable modules import no concrete persistence, workspace, wake, process, sandbox or browser backend. |

## 3. U1 deterministic gates

Each claim maps to named pytest nodes in `tests/automation/` and
`tests/reference/test_019_portable_core.py`. The reference test maintains the authoritative
claim-to-node map and rejects a missing, duplicate or non-Green node. Repository/workspace host
conformance suites are reusable but no concrete host run is required for U2A.

Required mutation families:

- every definition body/grant/final digest member;
- bool-as-int, invalid enum, noncanonical UTC and every numeric boundary;
- stale preview/source manifest/revision/CAS token/fencing token/capability;
- every READY/start/result crash boundary and all unknown-outcome recovery branches;
- provider response missing vs durable-unconsumed response;
- sandbox/browser class broadening and budget reuse;
- snapshot/diff/artifact overflow and ownership replacement;
- purge before/after each owned-object deletion and external-reference unlink;
- diagnostic sentinels for task, credential, path, model and tool/browser content;
- zero-counter and false-completion mutations for each U2A journey.

## 4. U2A closed journeys

The runner executes three fresh attempts. Every attempt uses new deterministic repository,
workspace, supervisor and executor identities and proves all thirteen journeys:

1. `J1 unavailable-host`: missing qualified host capabilities produce one closed NEEDS_019_CONFIG action and zero effects.
2. `J2 create-preview`: create is inactive; preview is human-first, complete and secret/path free outside owner-local detail.
3. `J3 approve-list-show`: exact preview activates; list/show project current state without becoming authority.
4. `J4 not-due`: reconcile exits before provider, executor, supervisor, sandbox, browser or credential resolution.
5. `J5 due-runtime`: deterministic READY/start/result protocol succeeds; separate harness gate enters the only AgentRuntime through ScheduledOccurrenceCaller.
6. `J6 duplicate`: exact duplicate replays authoritative state with zero new provider/tool/effect count.
7. `J7 update-cutover`: old revision runs until new approval; future old slots become superseded; active old occurrence is unchanged.
8. `J8 pause-resume`: pause blocks future claims; resume is explicit and does not repair a blocked Runtime.
9. `J9 cancel-pending`: active cancel blocks future work and the next uninvoked action, then terminalizes only after safe occurrence resolution.
10. `J10 open-handoff`: blocked show opens the exact Runtime checkpoint; revision drift fails before Runtime work; automation remains paused afterward.
11. `J11 model-unknown`: crash after provider intent yields MODEL_OUTCOME_UNKNOWN, zero replay and exact abandon-only recovery.
12. `J12 deadline-cleanup`: deterministic deadline/cleanup projections cannot invent Runtime completion; cleanup unknown pauses and retains ownership.
13. `J13 purge`: irreversible preview binds the full manifest; partial/crash recovery converges before a compact tombstone frees capacity.

Every attempt also proves pinned snapshot materialization, host-workspace mutation count zero,
bounded terminal result retrieval and external receipt secrecy. Removing disclosure, treating a
missing capability as approval, accepting host snapshot drift, sourcing result text from the
automation snapshot or auto-resuming after Runtime resolution must make the attempt fail.

## 5. Receipt and identity

`019_CORE_RECEIPT.json` is strict JSON containing only:

- schema/status and exact source-seal, materialized-root, verifier, runner and wheel digests;
- deterministic adapter identity digests;
- three attempt identifiers and closed J1–J13 booleans/counts;
- C1–C25 booleans and the exact U1 test count;
- source/materialized full-suite counts and return classes;
- fresh Spec/Product and Standards/Architecture review digests.

Unknown keys, missing booleans, repeated adapter identity, reused attempt store identity, digest
drift, any false claim, skipped/truncated/timed-out gate or cleanup unknown make attestation fail.

## 6. Promotion rule

Promotion requires U0, all U1 nodes, one sealed/materialized U2A three-attempt receipt and two
fresh independent PASS reviews on the same identity. Any ordinary source change invalidates the
seal, materialized tree and receipt. A detached review may bind the final identity but cannot
repair a failed product gate.

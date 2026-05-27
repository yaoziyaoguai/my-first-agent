---
title: Global Runtime Flow Remediation Plan
type: remediation-plan
status: ready-for-review
date: 2026-05-22
---

# Global Runtime Flow Remediation Plan

> **For agentic workers:** this is a remediation plan, not a feature plan. Do not
> continue Tool Confirmation, do not add Anchors, and do not implement Tool Args,
> Tool Result, Retry, MCP, Skill, or other new branch capabilities until this plan
> is independently reviewed and the remediation work is approved.

**Goal:** stop Anchor proliferation and restore the project narrative to Unified
Runtime Flow + Branch Behavior.

**Architecture target:** every query/event enters through `core.chat` or an
equivalent runtime entry, proceeds through the runtime loop and lifecycle decision
points, selects a branch, routes through `RuntimeActionDispatcher`, invokes a
subsystem handler/registry/policy, records evidence/trace/classification, and
returns to the runtime loop. Fake and real may differ only at configuration and
adapter boundaries.

**Current verdict:** PARTIAL. The runtime still has a recognizable single core
entry and loop, but recent Memory/Tool/Dogfood/Anchor work created naming and
classification drift that can overclaim what was actually proven.

---

## Audit Inputs

Commands recorded for this plan:

```text
pwd
/Users/jinkun.wang/work_space/my-first-agent

git status -sb
## main...origin/main
?? docs/plans/2026-05-22-002-feat-tool-confirmation-anchor-plan.md

git log --oneline -12
eaeff22 Merge branch 'feat/tool-anchor-e2e'
7276ad1 test(runtime): update tool registry contract for safe noop anchor
ce2f22b feat(runtime): add tool registry safe anchor e2e
b3c00a4 Merge pull request #1 from yaoziyaoguai/feat/hook-param-provider-evidence
98e1b5c fix(runtime): enforce project-dotenv-only real smoke runner
490a525 docs(plans): record memory anchor hook parameterization plan
4ffcf60 feat(runtime): parameterize memory anchor provider evidence
a0bc720 feat(runtime): add memory proposal anchor e2e
7ebcd4a docs(real-e2e): add memory E2E layered roadmap to spec and TDD
f356f63 docs(real-e2e): specify memory proposal anchor
5cd71c9 test(runtime): cover core chat phase1 runtime action hook
93b9e78 feat(runtime): wire real core loop RuntimeAction hook (Phase 1)

git rev-list --left-right --count origin/main...HEAD
0	0

git tag --points-at HEAD
<empty>

git diff --stat
<empty before this plan file>

git diff --name-only
<empty before this plan file>

git diff --check
<pass before this plan file>
```

Safe checks run:

```text
.venv/bin/ruff check agent tests scripts
All checks passed!

HOME=/private/tmp/my-first-agent-global-audit-home .venv/bin/python -m pytest tests/runtime_integration -q
140 passed, 4 skipped
```

The skipped runtime integration tests are explicit real provider smoke opt-ins.
No real API smoke was run.

---

## A. Current Actual Architecture Summary

The current actual flow is:

```text
query/event
  -> agent.core.chat(...)
  -> pre-loop MemoryRuntime explicit memory evaluation
       -> may store/block/request memory confirmation and return early
  -> L2 inline memory trigger
  -> planning / pending confirmation handling
  -> agent.loop.run_main_loop(...)
       -> provider adapter call
       -> model output dispatch
            -> text/end_turn result
            -> model tool_use path calls tool_executor.execute_single_tool directly
       -> turn-end hook, if dispatcher exists
            -> RuntimeActionDispatcher(memory.turn_end_proposal)
            -> RuntimeActionDispatcher(tool.gate for hard-coded _safe_noop)
       -> evidence/action_log classification
  -> return to core.chat caller
```

Important evidence:

- `agent/core.py:300` defines `chat()` as the main public runtime entry.
- `agent/core.py:340` runs MemoryRuntime explicit evaluation before the main loop.
- `agent/core.py:506` injects a dispatcher explicitly or auto-builds one only when
  the provider is fake.
- `agent/loop.py:29` defines the turn-end RuntimeAction hook.
- `agent/loop.py:84` creates the Memory turn-end action.
- `agent/loop.py:106` creates the Tool gate action.
- `agent/loop.py:111` hard-codes `_safe_noop` as the Tool gate action.
- `agent/response_handlers.py:270` sends actual model `tool_use` blocks to
  `execute_single_tool(...)`.
- `agent/tool_executor.py:284` performs ToolRegistry confirmation checks and
  `agent/tool_executor.py:373` executes tools directly through `execute_tool(...)`.

This means Tool Safe currently validates a synthetic turn-end `tool.gate` branch
behavior, not the full real model `tool_use -> ToolRegistry gate -> executor`
chain.

---

## B. What Is Still Healthy

1. `core.chat` remains the recognizable runtime entry for normal chat execution.
2. The new Memory and Tool fake dogfood scripts call `core.chat` rather than
   directly constructing `RuntimeActionRequest`.
3. The RuntimeAction dispatcher, handler registry, target module proof, and
   evidence chain are still meaningful for branch behavior checks.
4. `provider_kind`, `provider_external_call`, and `external_side_effects` are
   conceptually separated.
5. ToolGateHandler checks `_safe_noop` without executing a dangerous tool
   function.
6. Runtime integration tests and ruff currently pass without real API opt-in.

---

## C. What Is Architecture Drift

1. Anchor language has become the organizing narrative instead of branch
   behavior under a unified runtime contract.
2. `real_core_loop_runtime_e2e` can be overclaimed because classification trusts
   payload fields such as `core_loop_invoked`.
3. The loop turn-end hook now knows about Memory and Tool gate specifics,
   including hard-coded `_safe_noop`.
4. Fake and real do not have separate runtime loops, but dispatcher defaulting is
   asymmetric: fake provider auto-builds a dispatcher while real provider does not.
5. `_safe_noop` is documented as model-invisible, but current model-visible tool
   tests include it.
6. Old dogfood harness code still constructs RuntimeAction requests directly and
   uses E2E language that can be confused with real core loop E2E.
7. The active Tool Confirmation plan is still named as a new Anchor even though
   it should be reframed as Tool branch `confirmation_required` behavior.

---

## D. P0 / P1 / P2 / P3 Issues

| Priority | Issue | Evidence | Why it matters | Minimal remediation |
|---|---|---|---|---|
| P0 | No immediate runtime break found | ruff passes; runtime integration passes | The project can be remediated without emergency code rollback | Do not start new features before remediation review |
| P1 | `real_core_loop_runtime_e2e` can be spoofed by direct dispatcher payload | `agent/runtime_integration/evidence.py:1213` checks `core_loop_invoked` | Direct dispatcher can overclaim real core loop provenance | Add non-payload dispatcher/runtime provenance and downgrade direct dispatch |
| P1 | Tool Safe proves synthetic `tool.gate`, not real model tool execution chain | `agent/loop.py:106`, `agent/response_handlers.py:270`, `agent/tool_executor.py:373` | Tool branch capability can be overstated | Rename as Tool branch gate behavior; defer real model tool_use dispatcher design |
| P1 | `_safe_noop` visibility contract contradicts implementation/tests | `agent/tools/safe_noop.py:5`, `agent/tool_registry.py:244`, `tests/test_tool_registry_contract.py:23` | Internal test tool may become model-visible | Filter `_` tools from `get_model_visible_tools()` and adjust tests |
| P1 | Runtime loop contains hard-coded Memory/Tool branch action construction | `agent/loop.py:35`, `agent/loop.py:111` | The loop risks becoming a branch-specific monolith | Move branch selection/scenario config out of loop over time |
| P2 | Fake/real dispatcher defaulting is asymmetric | `agent/core.py:506` | Fake and real paths differ in default hook activation | Make dispatcher a runtime config dependency, not provider-kind behavior |
| P2 | Old dogfood direct dispatcher can be read as real E2E | `scripts/dogfood_e2e_runtime.py:1491`, `scripts/dogfood_e2e_runtime.py:1542` | Harness behavior can be mistaken for production runtime proof | Rename/report as harness/subsystem only |
| P2 | Memory dogfood checker relies on action order | `scripts/_dogfood_memory_anchor_checks.py:61` | Hook order changes can create false audit results | Find actions by `action_type` |
| P2 | Dogfood overlay lives in production ToolGateHandler module | `agent/runtime_integration/tool_gate.py:15` | Dogfood-only concepts leak into runtime code | Keep overlay harness-only or document strict registration boundary |
| P3 | Anchor docs/plans are misleading historical artifacts | `docs/real-e2e/memory-anchor/*`, `docs/implementation-notes/*ANCHOR*`, `docs/plans/2026-05-22-002-*` | Future work may keep creating small Anchors | Mark historical and reframe around branch behavior |

---

## E. Minimal Code Fixes

These are planned fixes only. Do not implement them until this plan is reviewed.

### E1. Evidence provenance hardening

Files to modify later:

- `agent/runtime_integration/schema.py`
- `agent/runtime_integration/dispatcher.py`
- `agent/runtime_integration/evidence.py`
- `agent/loop.py`
- targeted runtime integration tests

Required behavior:

- `real_core_loop_runtime_e2e` must not rely only on request payload fields.
- Direct dispatcher routing must default to `dispatcher_origin="direct_dispatcher"`.
- Runtime loop routing must attach non-payload provenance such as
  `dispatcher_origin="runtime_loop"`, `runtime_loop_invoked=True`,
  `core_entrypoint="core.chat"`, and `runtime_hook_name` or `lifecycle_point`.
- `real_core_loop_runtime_e2e` requires runtime-origin provenance plus
  target-module proof.
- Direct dispatcher can only classify as `harness_runtime_e2e` or
  `subsystem_integration`.

Tests to add:

- Direct dispatcher with forged `core_loop_invoked=True` must not claim
  `real_core_loop_runtime_e2e`.
- `core.chat` positive path still claims `real_core_loop_runtime_e2e`.
- Dogfood report classification does not regress.

### E2. `_safe_noop` internal visibility contract

Files to modify later:

- `agent/tool_registry.py`
- `agent/tools/safe_noop.py`
- `tests/test_tool_registry_contract.py`
- `tests/test_tool_exposure.py` if needed

Required behavior:

- `_safe_noop` remains registered in production `TOOL_REGISTRY`.
- `_safe_noop` is explicitly internal.
- `_safe_noop` is not returned by `get_model_visible_tools()`.
- Other `_` tools remain blocked unless explicitly allowlisted by ToolGateHandler.
- ToolRegistry governance functions are not loosened.

Tests to add or correct:

- `_safe_noop` exists in production registry.
- `_safe_noop` is internal and not model-visible.
- `EXPECTED_MODEL_VISIBLE_TOOLS` does not include `_safe_noop`.
- Other underscore-prefixed tools are rejected by ToolGateHandler unless explicitly
  allowlisted.

### E3. Dogfood checker and report boundary

Files to modify later:

- `scripts/dogfood_e2e_runtime.py`
- `scripts/_dogfood_memory_anchor_checks.py`
- `scripts/_dogfood_tool_anchor_checks.py`
- affected dogfood report tests

Required behavior:

- Dogfood scripts that claim real core loop proof must only configure scenario,
  call `core.chat`, and collect evidence/report.
- Direct dispatcher scripts must report `harness_runtime_e2e` or
  `subsystem_integration`.
- Memory and Tool dogfood checkers must locate actions by `action_type`, not by
  list position.
- Dogfood report code must not generate its own proof of real core loop execution.

### E4. Loop pollution containment

Files to modify later:

- `agent/loop.py`
- `agent/runtime_integration/phase1_hook.py`
- possibly a new branch selector/config module

Required behavior:

- `loop.py` should own lifecycle timing, not Memory/Tool scenario details.
- Tool `_safe_noop` should come from branch behavior config, not hard-coded loop
  business logic.
- Memory can have multiple branch points, but each branch point must be documented
  and classified honestly.

---

## F. Documentation / Terminology Fixes

Documentation work should happen before new feature work:

1. Create `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md`.
2. Mark `docs/real-e2e/memory-anchor/*` as historical validation artifacts.
3. Update `docs/implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md`
   to say Memory Proposal Anchor is now a Memory branch behavior validation.
4. Update `docs/implementation-notes/TOOL_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md`
   to say Tool Safe Anchor is a Tool gate `allowed` branch behavior validation.
5. Rename/reframe
   `docs/plans/2026-05-22-002-feat-tool-confirmation-anchor-plan.md` from
   Anchor to Tool branch `confirmation_required` behavior test.
6. Add a rule to future plans: capability families must not be split into endless
   Anchors. Branch states are tests, not milestones.

Required terminology:

- Use: Unified Runtime Flow
- Use: branch behavior test
- Use: harness runtime E2E
- Use: subsystem integration
- Avoid for new work: Anchor, Anchor family, Safe Anchor, Confirmation Anchor

---

## G. Deferred Large Design Items

These items are intentionally deferred:

1. Real model `tool_use -> ToolRegistry gate -> tool executor` routing through
   `RuntimeActionDispatcher`.
2. Tool Confirmation implementation.
3. Tool Args / Tool Result / Retry / Error Recovery / Multi Tool / MCP Tool
   branch work.
4. Skill branch expansion.
5. Memory approval/retain/recall redesign beyond documenting current branch
   points.
6. Removing all Memory pre-loop behavior from `core.chat`; this needs a separate
   design because current explicit memory confirmation is real behavior, not only
   Anchor residue.

---

## H. What To Stop Doing Immediately

1. Stop creating new Anchors.
2. Stop continuing Tool Confirmation implementation.
3. Stop adding `_confirmable_noop` until `_safe_noop` and classification
   remediation are reviewed.
4. Stop calling direct dispatcher scripts real core loop E2E.
5. Stop using `core_loop_invoked=True` payload fields as sufficient proof.
6. Stop letting dogfood scripts produce proof; they may only collect evidence
   produced by the runtime.
7. Stop planning Tool Args / Result / Retry / MCP / Skill work until remediation
   is reviewed.

---

## I. New Working Rule For Future SDD / TDD Tasks

Every future plan must begin with this classification:

```text
Is this a new capability milestone?
Is this a branch behavior test under an existing capability?
Is this a harness/subsystem-only validation?
```

Rules:

1. A capability milestone is allowed only when the system gains a new externally
   meaningful capability boundary, such as a new side-effect class, new durable
   state domain, new authorization boundary, or new provider/store/tool adapter
   class.
2. A branch behavior test covers states inside an existing capability, such as
   Tool `allowed`, `confirmation_required`, `blocked`, and `not_found`.
3. Harness/subsystem validations must never claim real core loop execution.
4. Fake/real must be injected through configuration or adapters only:
   RuntimeConfig, ProviderConfig, AdapterConfig, StoreConfig, AuthConfig, and
   metadata.
5. After `core.chat`, fake and real must share the same business flow.
6. Dogfood may configure a scenario, call `core.chat`, and collect evidence. It
   must not construct `RuntimeActionRequest`, call dispatcher directly, invoke
   MemoryPolicy/ToolRegistry/SkillLoader directly, or generate proof while
   claiming real E2E.
7. Tests must use red/green evidence:
   - red: direct dispatcher spoof cannot claim `real_core_loop_runtime_e2e`
   - green: `core.chat` positive path can claim `real_core_loop_runtime_e2e`
   - regression: dogfood reports preserve honest classification
8. Fast-lane merge/push is only allowed after the remediation diff is limited,
   `git diff --check` passes, targeted tests pass, and no real API opt-in was
   used.

---

## Proposed Remediation Sequence

### Task 1: Add unified runtime flow contract

Files:

- Create: `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md`
- Modify: relevant implementation notes to reference it

Steps:

1. Define the canonical runtime flow and accepted runtime entries.
2. Define standard branch points and lifecycle points.
3. Define `branch behavior test`.
4. Define fake/real configuration-only boundary.
5. Define dogfood responsibilities and forbidden actions.
6. Define classification downgrade rules.
7. Define Anchor freeze rule.

Exit criteria:

- New feature plans can cite one contract instead of inventing Anchor language.

### Task 2: Harden classification provenance

Files:

- Modify: `agent/runtime_integration/schema.py`
- Modify: `agent/runtime_integration/dispatcher.py`
- Modify: `agent/runtime_integration/evidence.py`
- Modify: `agent/loop.py`
- Test: targeted runtime integration tests

Steps:

1. Add failing spoof test for direct dispatcher.
2. Add positive `core.chat` provenance test.
3. Add runtime-origin provenance that is not read from payload.
4. Require runtime-origin provenance for `real_core_loop_runtime_e2e`.
5. Keep direct dispatcher at `harness_runtime_e2e` or lower.

Exit criteria:

- Forged payload fields cannot upgrade evidence level.

### Task 3: Fix `_safe_noop` internal contract

Files:

- Modify: `agent/tool_registry.py`
- Modify: `agent/tools/safe_noop.py`
- Modify: `tests/test_tool_registry_contract.py`
- Modify: `tests/test_tool_exposure.py` if needed

Steps:

1. Add failing test proving `_safe_noop` is not model-visible.
2. Keep registry existence test for `_safe_noop`.
3. Implement `_` prefix filtering in `get_model_visible_tools()`.
4. Keep ToolGateHandler allowlist narrow.
5. Verify other `_` tools remain blocked.

Exit criteria:

- `_safe_noop` remains a production registry internal test tool, not a model tool.

### Task 4: Reframe dogfood reports and checkers

Files:

- Modify: `scripts/dogfood_e2e_runtime.py`
- Modify: `scripts/_dogfood_memory_anchor_checks.py`
- Modify: `scripts/_dogfood_tool_anchor_checks.py`

Steps:

1. Rename direct dispatcher report language to harness/subsystem.
2. Make Memory checker find `memory.turn_end_proposal` by `action_type`.
3. Keep Tool checker action lookup by `action_type`.
4. Add report tests that direct dispatcher cannot claim real E2E.

Exit criteria:

- Dogfood reports cannot overclaim real core loop execution.

### Task 5: Reframe Tool Confirmation plan and stop

Files:

- Modify: `docs/plans/2026-05-22-002-feat-tool-confirmation-anchor-plan.md`

Steps:

1. Rename from Anchor to Tool branch `confirmation_required` behavior test.
2. Reference `UNIFIED_RUNTIME_FLOW_CONTRACT.md`.
3. State that blocked/not_found are negative tests, not milestones.
4. State that this work remains paused until remediation is reviewed.
5. State that Tool branch gate behavior is closed after allowed,
   confirmation_required, blocked, and not_found are covered.

Exit criteria:

- The plan no longer encourages a new Anchor or immediate implementation.

---

## Review Readiness

Status: ready for independent remediation plan review.

This plan intentionally does not implement code. It limits current repository
change scope to a documentation plan and keeps all runtime/test/script changes as
future reviewed work.

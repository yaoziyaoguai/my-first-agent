---
plan_type: feat
created: 2026-06-06
status: active
depth: medium
origin: docs/plans/2026-06-06-runtime-state-transition-phase0-plan.md
---

# Runtime State Transition Consolidation — Phase 1B Implementation Plan

**Target repo:** my-first-agent (this repo)

## Summary

Phase 1B migrates feedback_intent / origin_status restore paths into `apply_task_transition()`,
completing the confirmation handler migration started in Phase 1A.

Phase 1A migrated 5 deterministic points (plan accept + 4 tool confirmation paths).
Phase 1B handles the 4 remaining confirmation-path points that involve dynamic origin_status
restoration and planner re-generation.

## Scope Boundaries

### In Scope (Phase 1B)

- `agent/confirmation/dispatcher.py::_request_feedback_intent_choice` — 1 write
- `agent/confirmation/plan.py::handle_feedback_intent_choice` — 3 writes (cancel restore, as_feedback restore, as_feedback after planner)
- origin_status typed resolver with allowlist validation
- New transition rules in `_TRANSITION_TABLE`
- Architecture baseline update (remove migrated writes, add new Phase 1B rules)
- Targeted tests for origin_status resolver, feedback_intent transitions, handler-level safety

### NOT in Scope

- plan reject path
- step confirmation accept/reject migration
- awaiting_user_input migration
- session.py interrupt/resume
- tool_executor / ToolRuntimeMediator / core.py / response_handlers / memory_interaction / task_runtime
- Status merging / TaskState.status property / checkpoint schema changes
- Automatic checkpoint management / transition evidence
- Third-party FSM / DSL / Agent Loop rewrite
- Skill/SubAgent/Memory / MCP

## Problem Frame

`handle_feedback_intent_choice` currently uses 3 direct `state.task.status = ...` writes plus 1 in
`_request_feedback_intent_choice`. Two of those writes use a bare `origin_status` variable from
`pending.get("origin_status")` with no validation — if the stored value is corrupted, missing, or
an unexpected terminal/transient status, it is accepted silently.

Phase 1B wraps all 4 writes behind `apply_task_transition()`, introduces a typed origin_status
resolver, and adds transition rules for the feedback_intent lifecycle.

## Key Technical Decisions

### D1. Origin_status resolver as typed helper, not inline string access

`resolve_origin_status(state) -> str` reads from `state.task.pending_user_input_request`,
validates against an allowlist, returns the resolved status or raises a structured denial.
This keeps validation centralized and testable.

### D2. Special TransitionRule target for origin_status sentinel

The transition rule for "restore origin_status" uses a `<origin_status>` sentinel as `to_status`.
`apply_task_transition()` resolves this sentinel via the typed resolver *during execution*,
not during table lookup. This keeps the table declarative while making resolution safe.

### D3. as_feedback after planner also goes through apply_task_transition

After the planner successfully regenerates a plan, the status transition to
`awaiting_plan_confirmation` uses `apply_task_transition()` with an explicit event
rather than an inline `state.task.status = ...` assignment.

### D4. Validate-before-side-effects pattern carried from Phase 1A

All Phase 1B handler migrations validate the transition before any side effects
(modifying pending, calling planner, saving checkpoint). Denied → no side effects.

## Implementation Units

---

### U1. Origin Status Resolver + Transition Table Expansion

**Goal:** Add `resolve_origin_status()` helper and expand `_TRANSITION_TABLE` with
Phase 1B rules.

**Dependencies:** Phase 1A complete (confirmed)

**Files:**
- `agent/transitions.py` — add resolver + 6 new Phase 1B transition rules (~45 lines)

**Approach:**

1. **`resolve_origin_status(state) -> str`**:
   - Read `origin_status` from `state.task.pending_user_input_request`
   - Allowlist: `{"awaiting_plan_confirmation", "awaiting_step_confirmation"}`
   - Deny: missing, None, empty string, unknown status, terminal (done/failed/cancelled),
     session-transient (awaiting_resume_choice, awaiting_interrupt_choice),
     running/idle/planning, awaiting_tool_confirmation
   - Return resolved status string (not the raw dict value)

2. **New transition rules** (appended to `_TRANSITION_TABLE`, 6 rules total):
   ```
   # feedback_intent request (dispatcher)
   ("awaiting_plan_confirmation", FEEDBACK_INTENT_REQUIRED) → awaiting_feedback_intent + SAVE
   ("awaiting_step_confirmation", FEEDBACK_INTENT_REQUIRED) → awaiting_feedback_intent + SAVE

   # feedback_intent cancel (restore origin_status)
   ("awaiting_feedback_intent", USER_CANCELLED) → <origin_status> + SAVE

   # feedback_intent as_feedback (restore origin_status before planner)
   ("awaiting_feedback_intent", FEEDBACK_INTENT_AS_FEEDBACK) → <origin_status> + SAVE

   # as_feedback after planner success → awaiting_plan_confirmation
   # both plan/step confirmation restore paths are covered
   ("awaiting_plan_confirmation", PLAN_GENERATED) → awaiting_plan_confirmation + SAVE
   ("awaiting_step_confirmation", PLAN_GENERATED) → awaiting_plan_confirmation + SAVE
   ```

3. **`<origin_status>` sentinel handling in `apply_task_transition()`**:
   - When `rule.to_status == "<origin_status>"`, call `resolve_origin_status()`
   - If resolve returns valid status → use as actual `to_status`, return `allowed=True`
   - If resolve raises/returns denied → return `allowed=False` with reason

4. **New TransitionEvent values needed**:
   - `FEEDBACK_INTENT_AS_FEEDBACK = "feedback_intent.as_feedback"` — distinct from
     `USER_FEEDBACK` (which is for tool feedback)

**Test scenarios:**
- origin_status = awaiting_plan_confirmation → allowed
- origin_status = awaiting_step_confirmation → allowed
- origin_status missing / None / empty / unknown → denied
- origin_status terminal (done/failed/cancelled) → denied
- origin_status session-transient (awaiting_resume_choice/awaiting_interrupt_choice) → denied
- origin_status running/idle/planning/awaiting_tool_confirmation → denied (default)
- denied → state.task.status unchanged, checkpoint_action=NONE
- Phase 1B rules all present in _TRANSITION_TABLE (6 rules)
- Phase 1A rules unchanged (4 rules still present)
- No out-of-scope rules in table (no session/memory/tool_executor/core/task_runtime rules)

**Verification:**
`pytest tests/unit/test_task_transitions.py -v -k "phase1b or origin_status"`

---

### U2. Dispatcher Migration

**Goal:** Migrate `_request_feedback_intent_choice` to use `apply_task_transition()`.

**Dependencies:** U1

**Files:**
- `agent/confirmation/dispatcher.py` — modify `_request_feedback_intent_choice()` (~8 lines changed)

**Approach:**

Before the current side effects (set pending, set status, save checkpoint, emit event),
insert:

```python
result = apply_task_transition(state, TaskTransitionRequest(
    event=TransitionEvent.FEEDBACK_INTENT_REQUIRED,
    owner="confirmation.dispatcher.feedback_intent_request",
    expected_from_status=origin_status,  # "awaiting_plan_confirmation" or "awaiting_step_confirmation"
))
if not result.allowed:
    return f"[系统] feedback_intent 状态迁移失败: {result.reason}"
```

Then replace `state.task.status = "awaiting_feedback_intent"` with nothing (already done by
`apply_task_transition`). Keep `save_checkpoint` call but guard with
`result.checkpoint_action == CheckpointAction.SAVE`.

**Note on `expected_from_status`:** The dispatcher currently receives `origin_status` as a
parameter (either `"awaiting_plan_confirmation"` or `"awaiting_step_confirmation"`). The
actual `state.task.status` should match this value. Using it as `expected_from_status`
provides a safety assertion.

If mismatched → denied → no pending change, no status change, no checkpoint.
Return error string to caller (same pattern as plan accept in Phase 1A).

**Test scenarios:**
- plan confirmation → feedback_intent: allowed, status becomes awaiting_feedback_intent
- step confirmation → feedback_intent: allowed, status becomes awaiting_feedback_intent
- wrong current status → denied, pending unchanged, status unchanged
- denied → no checkpoint saved

**Verification:**
Existing `test_feedback_intent_flow.py` tests pass (especially tests 1, 3, 8 which exercise this path).

---

### U3. Plan Handler Migration — Cancel Path

**Goal:** Migrate `handle_feedback_intent_choice` cancel (choice "3") to use `apply_task_transition()`.

**Dependencies:** U1

**Files:**
- `agent/confirmation/plan.py` — modify cancel path (~5 lines changed)

**Approach:**

Before clearing pending and saving checkpoint:
```python
result = apply_task_transition(state, TaskTransitionRequest(
    event=TransitionEvent.USER_CANCELLED,
    owner="confirmation.plan.feedback_intent_cancel",
    expected_from_status="awaiting_feedback_intent",
))
if not result.allowed:
    return f"[系统] 取消反馈意图状态迁移失败: {result.reason}"
```

Then replace `state.task.status = origin_status` (line 177) with nothing.
Keep `save_checkpoint` call guarded by `result.checkpoint_action == CheckpointAction.SAVE`.

The origin_status resolution happens inside `apply_task_transition()` via the
`<origin_status>` sentinel → `resolve_origin_status()`.

If origin_status is invalid → denied → no pending clear, no status change, no checkpoint.

**Test scenarios:**
- valid origin_status (awaiting_step_confirmation) → allowed, restores origin, checkpoints
- valid origin_status (awaiting_plan_confirmation) → allowed
- invalid origin_status → denied, pending NOT cleared, status unchanged, no checkpoint
- denied → returns error string, no side effects

---

### U4. Plan Handler Migration — As Feedback Path

**Goal:** Migrate `handle_feedback_intent_choice` as_feedback (choice "1") to use
`apply_task_transition()` for both the origin_status restore and the post-planner
awaiting_plan_confirmation entry.

**Dependencies:** U1, U3

**Files:**
- `agent/confirmation/plan.py` — modify as_feedback path (~10 lines changed)

**Approach:**

**Step A — Before planner (restore origin_status):**

Before clearing pending and calling planner:
```python
restore_result = apply_task_transition(state, TaskTransitionRequest(
    event=TransitionEvent.FEEDBACK_INTENT_AS_FEEDBACK,
    owner="confirmation.plan.feedback_intent_as_feedback_restore",
    expected_from_status="awaiting_feedback_intent",
))
if not restore_result.allowed:
    return f"[系统] 反馈处理状态迁移失败: {restore_result.reason}"
```

This replaces `state.task.status = origin_status` (line 195).

**Step B — After planner success:**

Replace `state.task.status = as_feedback_transition.next_status or "awaiting_plan_confirmation"` (line 213) with:
```python
# After Step A restored origin_status (awaiting_plan_confirmation or
# awaiting_step_confirmation) and planner succeeded, enter
# awaiting_plan_confirmation. Do NOT pass expected_from_status —
# rely on the transition table which covers both:
#   awaiting_plan_confirmation + PLAN_GENERATED → awaiting_plan_confirmation
#   awaiting_step_confirmation + PLAN_GENERATED → awaiting_plan_confirmation
plan_result = apply_task_transition(state, TaskTransitionRequest(
    event=TransitionEvent.PLAN_GENERATED,
    owner="confirmation.plan.feedback_intent_as_feedback_enter",
    expected_from_status=None,  # let the table handle both origins
))
if not plan_result.allowed:
    # Transition denied is an unexpected error condition, NOT a routine
    # path for handling origin_status mismatch. Do NOT reset_task() or
    # clear_checkpoint() here — those would wrongly destroy the task.
    # Return a safe error without side effects.
    return f"[系统] 重新进入计划确认状态失败: {plan_result.reason}"
```

**Key insight:** After Step A restores `origin_status` to either
`awaiting_plan_confirmation` or `awaiting_step_confirmation`, the planner runs.
Step B uses `PLAN_GENERATED` without `expected_from_status`, letting the
transition table match either origin status. Both rules produce
`awaiting_plan_confirmation` + SAVE. This is a self-loop when origin is already
`awaiting_plan_confirmation`, and a status change when origin is
`awaiting_step_confirmation` — in both cases checkpoint is saved because the plan
content changed.

**Error handling:** If `plan_result.allowed` is False, treat it as an unexpected
anomaly — return an error string but do NOT destroy the task. The `reset_task() +
clear_checkpoint()` path is reserved for genuine planner failures (planner raised
or returned unusable output), not for transition mismatches.

**Important:** Keep `save_checkpoint` calls but guard with `result.checkpoint_action`.
If planner fails, keep existing error handling (reset_task + clear_checkpoint)
only in the planner-failure catch block.

**Test scenarios:**
- origin_status = awaiting_plan_confirmation → restore allowed → planner runs → awaiting_plan_confirmation
- origin_status = awaiting_step_confirmation → restore allowed → planner runs → awaiting_plan_confirmation
- invalid origin_status → denied → planner NOT called, pending NOT cleared
- denied → no checkpoint saved
- planner success → enters awaiting_plan_confirmation via transition (both origins)
- planner failure → keeps existing error handling (reset_task + clear_checkpoint, planner-failure path only)
- Step B denied (anomaly) → does NOT reset_task(), does NOT clear_checkpoint(), returns error string

---

### U5. Architecture Baseline Update

**Goal:** Update `_DIRECT_STATUS_MUTATION_BASELINE` in `tests/test_architecture_boundaries.py`
to reflect Phase 1B migrations.

**Dependencies:** U2, U3, U4 (all migrations complete)

**Files:**
- `tests/test_architecture_boundaries.py` — update baseline entries (~10 lines changed)

**Approach:**

1. **Remove / decrement migrated writes from baseline:**
   - `("agent/confirmation/dispatcher.py", "_request_feedback_intent_choice", ..., "awaiting_feedback_intent")`: count 1 → 0 (REMOVE)
   - `("agent/confirmation/plan.py", "handle_feedback_intent_choice", ..., "<origin_status>")`: count 2 → 0 (REMOVE)
   - `("agent/confirmation/plan.py", "handle_feedback_intent_choice", ..., "<variable>")`: count 1 → 0 (REMOVE)
     (This was `as_feedback_transition.next_status or "awaiting_plan_confirmation"` — `<variable>`)

2. **Update `_TRANSITION_TABLE` exact key test** in `tests/unit/test_task_transitions.py`:
   - `test_transition_table_keys_exact_phase1a` → rename/update to cover Phase 1A + Phase 1B
   - Expected keys: Phase 1A 4 rules + Phase 1B 6 rules = 10 rules total

3. **Confirm** all baseline tests still pass:
   - `test_direct_status_mutation_baseline`
   - `test_alias_detection_positive_fixture`
   - `test_runtime_state_mutation_function_inventory_is_reviewed` (update if needed)

**Test scenarios:**
- Count of `_request_feedback_intent_choice` status writes → 0
- Count of `handle_feedback_intent_choice` origin_status writes → 0
- Count of `handle_feedback_intent_choice` variable writes → 0
- Total baseline entries reduced by 3
- _TRANSITION_TABLE keys exactly match Phase 1A (4) + Phase 1B (6) expected set

---

### U6. Targeted Tests

**Goal:** Add comprehensive tests for Phase 1B transitions, origin_status resolver,
and handler-level migration safety.

**Dependencies:** U1 (can be written in parallel with U2-U4)

**Files:**
- `tests/unit/test_task_transitions.py` — add Phase 1B test classes (~200 lines)

**Test scenarios by category:**

**A. Origin status resolver tests:**
- `origin_status = "awaiting_plan_confirmation"` → allowed
- `origin_status = "awaiting_step_confirmation"` → allowed
- `origin_status` missing key → denied
- `origin_status = None` → denied
- `origin_status = ""` → denied
- `origin_status = "unknown_status"` → denied
- `origin_status = "done" / "failed" / "cancelled"` → denied
- `origin_status = "awaiting_resume_choice" / "awaiting_interrupt_choice"` → denied
- `origin_status = "running" / "idle" / "planning"` → denied (default)
- `origin_status = "awaiting_tool_confirmation"` → denied (default)
- denied → `state.task.status` unchanged
- denied → `checkpoint_action = NONE`

**B. Feedback intent request tests:**
- `awaiting_plan_confirmation + FEEDBACK_INTENT_REQUIRED` → allowed, `next_status = "awaiting_feedback_intent"`
- `awaiting_step_confirmation + FEEDBACK_INTENT_REQUIRED` → allowed, `next_status = "awaiting_feedback_intent"`
- wrong current status → denied
- denied → pending unchanged, status unchanged

**C. Feedback intent cancel tests:**
- valid origin_status restore → allowed, status = origin_status, checkpoint_action = SAVE
- invalid origin_status → denied
- denied → pending unchanged, status unchanged

**D. Feedback intent as_feedback tests:**
- valid origin_status restore (awaiting_plan_confirmation) → allowed
- valid origin_status restore (awaiting_step_confirmation) → allowed
- invalid origin_status → denied, planner NOT called
- denied → pending unchanged, no checkpoint
- `awaiting_plan_confirmation + PLAN_GENERATED` → allowed, `next_status = "awaiting_plan_confirmation"`, SAVE
- `awaiting_step_confirmation + PLAN_GENERATED` → allowed, `next_status = "awaiting_plan_confirmation"`, SAVE
- Step B denied (anomaly) → does NOT reset_task(), does NOT clear_checkpoint()

**E. Table exactness tests:**
- `_TRANSITION_TABLE.keys()` exactly = Phase 1A (4) + Phase 1B (6) = 10 expected keys
- No session / memory / tool_executor / core / task_runtime rules

**F. Regression:**
- Existing `test_feedback_intent_flow.py` tests pass
- Existing `test_confirmation_flow.py` tests pass (check XPASS/XFAIL)
- Phase 1A `test_task_transitions.py` tests pass
- `test_tool_rejection_feedback.py` tests pass
- Architecture baseline tests pass

**XPASS/XFAIL note on test_confirmation_flow.py:**
Check if any existing XPASS(strict) markers in `test_confirmation_flow.py` are affected
by Phase 1B. If they are genuinely unrelated to feedback_intent migration, keep them.
Do not modify xfail markers just to make tests pass without evidence.

---

## Verification

### Quality Gates

```bash
# 1. Transition tests
pytest tests/unit/test_task_transitions.py -v

# 2. Architecture baseline
pytest tests/test_architecture_boundaries.py -v

# 3. Feedback intent flow
pytest tests/test_feedback_intent_flow.py -v

# 4. Confirmation flow regression
pytest tests/test_confirmation_flow.py -v

# 5. Tool confirmation regression
pytest tests/test_tool_rejection_feedback.py -v

# 6. Inventory tests
pytest tests/test_architecture_boundaries.py -v \
  -k "test_runtime_state_mutation_function_inventory_is_reviewed or test_pending_confirmation_persistence_writers_are_reviewed"

# 7. ruff
ruff check agent/transitions.py agent/confirmation/dispatcher.py agent/confirmation/plan.py \
  tests/test_architecture_boundaries.py tests/unit/test_task_transitions.py

# 8. git diff --check
```

### Closeout Criteria

1. `resolve_origin_status()` implemented and tested
2. 4 confirmation handler writes migrated to `apply_task_transition()`
3. `_TRANSITION_TABLE` extended with exactly 6 new Phase 1B rules (10 total)
4. Architecture baseline updated — 3 entries removed
5. All Phase 1B tests pass
6. All existing feedback_intent flow tests pass
7. Architecture baseline tests pass
8. ruff clean
9. git diff --check clean

## Risks

| Risk | Severity | Mitigation |
|------|:---:|------|
| `<origin_status>` sentinel resolution inside `apply_task_transition()` adds complexity | Low | Sentinels only fire for known Phase 1B rules; resolver is pure function with clear allowlist |
| `PLAN_GENERATED` self-loop rule (`awaiting_plan_confirmation → awaiting_plan_confirmation`) may be surprising | Low | Self-loop is the correct semantic — status doesn't change, but checkpoint is needed because plan content changed |
| `FEEDBACK_INTENT_AS_FEEDBACK` event may be confused with `USER_FEEDBACK` | Low | Clearly different enum values; `USER_FEEDBACK` = tool feedback, `FEEDBACK_INTENT_AS_FEEDBACK` = user chose "treat as feedback" |
| Existing `test_confirmation_flow.py` XPASS/XFAIL may be affected | Low | Check before implementation; if unrelated, keep markers as-is |
| `handle_feedback_intent_choice` cancel and as_feedback both restore origin_status via same sentinel | Low | Both paths use `<origin_status>` sentinel but with different events (USER_CANCELLED vs FEEDBACK_INTENT_AS_FEEDBACK); same resolver logic, different caller context |

## Absorbed Audit Findings

### P2-1: PLAN_GENERATED from_status 覆盖不全 (absorbed in plan revision)

**发现:** Phase 1B plan 原始版本只定义了 `awaiting_plan_confirmation + PLAN_GENERATED → awaiting_plan_confirmation + SAVE`，
但 feedback_intent as_feedback 路径中 origin_status 也可能是 `awaiting_step_confirmation`。
当用户从 step confirmation 输入模糊反馈 → 进入 feedback_intent → 选择 as_feedback →
Step A 恢复 origin_status 为 `awaiting_step_confirmation` → planner 成功运行 →
Step B 如果只接受 `expected_from_status="awaiting_plan_confirmation"` 就会 mismatch denied。
若 denied 错误处理使用 `reset_task() + clear_checkpoint()`，整条 task 会被误销毁。

**修复:**
1. 新增 `awaiting_step_confirmation + PLAN_GENERATED → awaiting_plan_confirmation + SAVE` rule
2. Step B 不传 `expected_from_status`（传 `None`），完全依赖 transition table 匹配两种 origin status
3. Step B denied 作为异常路径处理，不执行 `reset_task()` 或 `clear_checkpoint()`，不销毁 task
4. `reset/clear` 仅保留在 planner 真正失败（抛异常或输出不可用）的 catch 块中

## Files Summary

| File | Change | Description |
|------|--------|-------------|
| `agent/transitions.py` | Modify | Add `resolve_origin_status()`, 6 new transition rules, `<origin_status>` sentinel handling, new `FEEDBACK_INTENT_AS_FEEDBACK` event |
| `agent/confirmation/dispatcher.py` | Modify | `_request_feedback_intent_choice()` uses `apply_task_transition()` |
| `agent/confirmation/plan.py` | Modify | `handle_feedback_intent_choice()` cancel + as_feedback use `apply_task_transition()` |
| `tests/unit/test_task_transitions.py` | Modify | Add Phase 1B test classes, update table key test |
| `tests/test_architecture_boundaries.py` | Modify | Update baseline (remove 3 migrated entries) |

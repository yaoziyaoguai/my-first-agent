# Runtime v0.4 Phase 1 Event/Transition Baseline

> This is the v0.4 Phase 1 baseline for a light Event-driven State Transition
> pass. It is not a runtime rewrite, not a complete event-driven state machine,
> and not a request to introduce LangGraph or a new framework.
> It keeps the earlier planning/prep boundary visible: full event-driven Runtime
> is not implemented v0.4, and Phase 1 still starts with transition boundary tests first.

## 1. Current state-update map

| Area | Current responsibility | v0.4 prep note |
|---|---|---|
| `agent/core.py` | orchestrates `chat()`, planning, loop dispatch, model streaming | keep orchestration; identify transition boundaries before moving code |
| `agent/confirm_handlers.py` | mutates plan/step/tool/user-input waiting states | candidate source for explicit user-confirmation transitions |
| `agent/response_handlers.py` | handles `end_turn`, `tool_use`, `max_tokens`, progress/no-progress | candidate source for ModelOutput and ToolResult transitions |
| `agent/tool_executor.py` | executes tools, distinguishes success/failure/rejection, sets pending tool/input | candidate source for ToolResult, PolicyDenial, UserRejection events |
| `agent/checkpoint.py` | persists durable task/memory/conversation messages | keep RuntimeEvent / DisplayEvent / InputIntent out of checkpoint/schema |
| `agent/cli_shell.py` / `agent/output_renderer.py` | not present in current tree | current equivalents are `main.py`, `agent/cli_renderer.py`, and `agent/display_events.py` |

## 2. Event candidates

- UserInput
- ModelOutput
- ToolResult
- PolicyDenial
- UserRejection
- CheckpointResume
- HealthCommand
- LogsCommand

These names are candidates for tests and vocabulary. They do not mean the
current runtime is already fully event-driven; in other words, event candidates
do not mean the current runtime is already fully event-driven.

## 3. State candidates

- RuntimeState
- TaskState
- pending_tool
- pending_user_input_request
- current_step
- checkpoint persisted fields

Checkpoint/schema boundary rule: durable state remains task / memory /
conversation messages. RuntimeEvent, DisplayEvent, InputIntent, retired
CommandResult, observer debug payloads, and UI render objects must not become checkpoint fields or conversation messages.

## 4. v0.4 first stage should do / baseline

Completed in the current baseline:

- `agent/runtime_events.py` defines the lightweight `RuntimeEventKind` and
  `TransitionResult` naming boundary. These are runtime decision vocabulary, not
  checkpoint schema and not conversation messages.
- The first command event slice maps `HealthCommand` / `LogsCommand` to no-op
  transition results: they can render maintenance output, but they do not change
  TaskState, clear pending fields, advance steps, or trigger task checkpoint.
- The first ToolResult transition slice maps `PolicyDenial` and `UserRejection`
  to `TransitionResult`. Existing handlers still own `tool_result` messages and
  checkpoint calls; the new boundary only centralizes clear-pending /
  checkpoint/display intent for these two low-risk outcomes.
- The second ToolResult transition slice maps `ToolFailure` to `TransitionResult`.
  Existing `tool_result` message writing stays unchanged; the slice only makes
  failure outcome intent explicit and keeps failure distinct from policy denial,
  user rejection, and success.
- The third ToolResult transition slice maps `ToolSuccess` to `TransitionResult`,
  completing the symmetric tool result vocabulary at the transition layer.
  Both `execute_single_tool` direct path and `execute_pending_tool` confirmed
  path now route success outcome intent through a unified `_tool_outcome_transition`
  helper, so the four tool outcomes (success / failure / policy denial / user
  rejection) are symmetric at the transition naming layer. Existing
  `tool_result` message writing, checkpoint persistence, tool execution
  (`execute_tool`), and user confirmation handler boundaries all remain
  unchanged. `rejected_by_check` (tool-internal safety reject) deliberately
  stays on the raw `display_event_type` fallback path so it does not get
  collapsed into success or failure semantics.
- The first ModelOutput classification slice introduces `ModelOutputKind`
  (`END_TURN` / `TOOL_USE` / `MAX_TOKENS` / `UNKNOWN`) and a pure
  `classify_model_output(stop_reason)` function. `agent/core.py` `_run_main_loop`
  dispatcher now routes by kind instead of inline string compares; the existing
  3 handlers (`handle_end_turn_response`, `handle_tool_use_response`,
  `handle_max_tokens_response`) and their state mutation / messages / checkpoint
  / `consecutive_*` counters are unchanged. `UNKNOWN` keeps the explicit
  `"未知的 stop_reason"` fallback so future SDK protocol drift cannot be
  silently absorbed into a known kind.
- The first user-confirmation transition slice (plan) introduces
  `PlanConfirmationKind` (`PLAN_ACCEPTED` / `PLAN_REJECTED`) and
  `plan_confirmation_transition()`. `handle_plan_confirmation` accept and
  reject branches now declare intent through `TransitionResult.should_checkpoint`;
  handler still owns actual `state.task.status` mutation, `save_checkpoint` /
  `clear_checkpoint`, `append_control_event`, and `state.reset_task()`.
  Reject path explicitly asserts `not should_checkpoint` so the contract
  prevents a future ghost checkpoint regression on cancelled plans.
- The second user-confirmation transition slice (step) introduces
  `StepConfirmationKind` (`STEP_ACCEPTED_CONTINUE` / `STEP_ACCEPTED_TASK_DONE` /
  `STEP_REJECTED`). Three kinds (not two) because step accept has two real
  terminal states: continue to next step vs. last-step natural completion.
  The natural-completion kind sets `should_checkpoint=False` on purpose so
  task-done flows through `clear_checkpoint` instead of a stale checkpoint
  write; continue kind keeps `should_checkpoint=True` for normal advancement.
- The third user-confirmation transition slice (tool) introduces
  `ToolConfirmationKind` (`TOOL_ACCEPTED_SUCCESS` / `TOOL_ACCEPTED_FAILED`).
  Only two kinds because tool accept has two real terminal states with an
  asymmetric `pending_tool` cleanup contract: success clears `pending_tool`,
  failure preserves it for human diagnostics. Reject path is intentionally
  NOT re-routed; it stays on the v0.1 `ToolResultTransitionKind.USER_REJECTION`
  boundary so the ToolResult vs ToolConfirmation semantic layers remain
  distinct (ToolResult = "how to map this tool_result message"; ToolConfirmation
  = "Runtime state-machine decision after user confirms a tool"). A pre-slice
  contract test pins `pending_tool` cleanup as the handler's single source of
  truth across all three paths (success / exception / reject) before the
  kind-based dispatch is introduced.
- The fourth user-confirmation transition slice (user_input) is intentionally
  a **reuse slice, not a new-kind slice**. `handle_user_input_step` was
  already reduced to a 3-line dispatcher in v0.3 by `apply_user_replied_transition`
  (in `agent/transitions.py`), which absorbs append / clear pending /
  advance / save_checkpoint into one transition boundary. Adding a parallel
  `UserInputConfirmationKind` would only wrap the existing transition in a
  second indirection without information gain, and would split the
  `awaiting_user_input + USER_REPLIED` semantic across two vocabularies.
  Slice 6-d therefore pins the reuse contract via source-level boundary
  tests (handler routes through `apply_user_replied_transition`; never
  inline-mutates `pending_user_input_request` or `state.task.status`;
  `empty_user_input` defence stays in handler as the runtime guard before
  the transition layer). Adding a new kind here is explicitly listed in the
  governance forbidden-list because it would be ceremony, not a real
  boundary improvement. `feedback_intent` confirmation is the only remaining
  user-confirmation handler still owning inline mutation; it is read-only
  audited but not migrated in this slice because it carries three-way
  dispatch + `origin_status` rollback + `start_planning_fn` injection, all
  of which need a separate contract-test slice first.
- The fifth user-confirmation transition slice (feedback_intent) introduces
  `FeedbackIntentKind` (`AS_FEEDBACK` / `AS_NEW_TASK` / `CANCELLED` /
  `AMBIGUOUS`) and `feedback_intent_transition()`. This is the closing
  slice of Phase 1 user-confirmation migration and the most dangerous one:
  feedback_intent is the only confirmation handler that calls an LLM
  (`generate_plan`), the only one that takes a callback injection
  (`start_planning_fn`), and the only one whose `AMBIGUOUS` path **must
  not** be merged with `CANCELLED` — collapsing them would let undecided
  intent be persisted to checkpoint and break the
  `docs/P1_TOPIC_SWITCH_PLAN.md` §3 anti-heuristic red line. The
  transition layer is therefore intentionally minimal: each path's
  `should_checkpoint` / `clear_pending_user_input` / `next_status` is
  pinned exactly, with `AMBIGUOUS = (False, False, None)` as the
  three-False contract that prevents any future "unify all confirmation
  paths to save_checkpoint" refactor from breaking the red line. Handler
  still owns: `generate_plan` LLM call, `append_control_event(plan_feedback)`
  message write, `state.task.current_plan` / `current_step_index`
  assignment, `save_checkpoint`, `state.reset_task()`, `clear_checkpoint()`,
  and `start_planning_fn` reverse callback. revised_goal stays a local
  planner input and is never written back to `state.task.user_goal`
  (pinned by source-level test). With slice 6-e all five user-confirmation
  handlers (plan, step, tool, user_input via reuse, feedback_intent) are
  routed through transition vocabulary; Phase 1 user-confirmation
  migration is closed.
- Transition boundary tests guard maintenance commands, checkpoint/messages
  separation, status-line rendering, event/result naming, the first three
  ToolResult transition slices (policy denial, user rejection, tool failure,
  tool success), the first ModelOutput classification slice, and all five
  user-confirmation slices (plan, step, tool, user_input reuse,
  feedback_intent).

Not completed yet:

- Complete event-driven state machine.
- `core.py` main-loop slimming: `_run_main_loop` is **already at module
  level** (`agent/core.py:408`, takes only `turn_state`; `grep nonlocal`
  returns 0 hits, confirming it is not a `chat()` closure). The Phase 2a
  prep target "lift `_run_main_loop` to a clearer module entry" was
  effectively achieved by the early baseline commits (c2abd80 / f6a1539
  / 9882744) before this prep doc was written. The honest remaining
  Phase 2 work is **dependency injection for the module-level `state`
  singleton** — replacing implicit globals (`state`, `MAX_LOOP_ITERATIONS`,
  client, model_name) with a typed `LoopContext` dataclass passed
  through `chat()` / `_run_planning_phase` / `_run_main_loop` /
  `_call_model`. That is a multi-slice migration touching every helper
  signature in core.py, not a single Phase 2a slice; it should be
  planned as **"Phase 2: state dependency injection"** with its own
  2-3 sub-slices (LoopContext dataclass + chat() wiring; planning helper
  wiring; loop + call_model wiring). ModelOutput classification (slice 5)
  only centralises *which kind* the response is, not the loop structure
  itself.
- Full tool result message migration: current slices keep `append_tool_result`
  calls in handlers; only outcome intent / display event / checkpoint gating
  goes through `TransitionResult`. Moving `tool_result` message writing itself
  behind a transition boundary is a later slice.
- Full ModelOutput handler-side migration: classification is centralised, but
  `response_handlers.py` still owns state mutation, messages writing,
  checkpoint, and the `consecutive_*` counters for each kind.
- Full user confirmation/rejection migration.

## 5. v0.4 first stage should not do

- Do not introduce LangGraph.
- Do not add sub-agent runtime.
- Do not add Reflect / Self-Correction.
- Do not build a full Textual IDE.
- Do not implement stream abort or generation cancellation.
- Do not revive slash command.
- Do not implement complex topic switch.
- Do not rewrite Runtime in one pass.

## 6. State update scatter audit

This audit is the migration map, not the migration itself.

- `core.py`: owns `chat()`, task reset, planning status, plan confirmation
  status, loop guards, and the current orchestration order. It should stay as
  orchestration until narrower transitions are covered.
- `confirm_handlers.py`: accepts/rejects plan, step, tool confirmation, and
  feedback intent. It sets/clears `pending_tool`, clears
  `pending_user_input_request` after user replies, changes status, and calls
  checkpoint helpers.
- `response_handlers.py`: classifies model stop reasons, handles `tool_use`,
  `end_turn`, `max_tokens`, no-progress fallback, step advancement, and
  `pending_user_input_request` fallback creation.
- `tool_executor.py`: records tool execution results, sets
  `pending_tool`, sets `pending_user_input_request` for `request_user_input`,
  distinguishes `blocked_by_policy`, `rejected_by_check`, `failed`, and
  `executed`, emits display events, and saves checkpoints.
- `checkpoint.py`: serializes durable task / memory / conversation messages and
  filters unknown fields on load. RuntimeEvent, DisplayEvent, InputIntent,
  retired CommandResult, observer payloads, and CLI render objects stay out of
  checkpoint/schema.
- `session.py`: initializes session health/header, decides actionable resume,
  loads durable checkpoint state, and replays user prompts. It should keep
  resume summaries detached from raw checkpoint dictionaries.
- `main.py`, `agent/cli_renderer.py`, and `agent/display_events.py`: adapt I/O
  and render summaries/events. They should not own task transitions or mutate
  checkpoint state except by dispatching explicit Runtime commands.

Likely migration order:

1. Move the next ToolResult -> TransitionResult slice for tool success without
   changing the `tool_result` protocol.
2. Tighten UserRejection / PolicyDenial / ToolFailure transition application
   only where tests show duplicated state updates.
3. Centralize ModelOutput classification.
4. Only then consider slimming the `core.py` loop.

ToolSuccess next slice notes:

- Success is currently classified in `tool_executor._classify_tool_outcome()`
  as `executed`, writes a normal `tool_result` message, emits `tool.completed`,
  and checkpoints.
- Direct success has no pending tool to clear; confirmed pending success is
  cleared by `confirm_handlers.handle_tool_confirmation()` after execution.
- Success still should not directly advance a step; step advancement remains
  driven by meta progress signals and later model output.

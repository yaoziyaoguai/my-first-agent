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
- Transition boundary tests guard maintenance commands, checkpoint/messages
  separation, status-line rendering, event/result naming, and the first
  ToolResult transition slice.

Not completed yet:

- Complete event-driven state machine.
- `core.py` main-loop slimming.
- Full ToolResult / tool result migration, including tool success/failure and
  moving `tool_result` message writing itself behind a transition boundary.
- Full ModelOutput / model output classification migration.
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

1. Move the next ToolResult -> TransitionResult slice for tool failure or tool
   success without changing the `tool_result` protocol.
2. Tighten UserRejection / PolicyDenial transition application only where tests
   show duplicated state updates.
3. Centralize ModelOutput classification.
4. Only then consider slimming the `core.py` loop.

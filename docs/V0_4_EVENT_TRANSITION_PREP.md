# Runtime v0.4 Event/Transition Prep

> This is a planning/prep map for a future light Event-driven State Transition
> pass. It is not implemented v0.4, not a runtime rewrite, and not a request to
> introduce LangGraph or a new framework.

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

## 4. v0.4 first stage should do

- Add transition boundary tests first.
- Define light event/result names before moving code.
- Identify which state updates are still scattered across core/handlers/tools.
- Add checkpoint/schema boundary tests where gaps are found.
- Migrate state updates gradually after tests exist.
- Keep old CLI shell behavior working during migration.

## 5. v0.4 first stage should not do

- Do not introduce LangGraph.
- Do not add sub-agent runtime.
- Do not add Reflect / Self-Correction.
- Do not build a full Textual IDE.
- Do not implement stream abort or generation cancellation.
- Do not revive slash command.
- Do not implement complex topic switch.
- Do not rewrite Runtime in one pass.

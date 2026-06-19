# S2 Task State Model

This is the S2-G02 contract for the governed task state model. It formalizes the
existing S1 legacy `TaskState` + `current_plan` path without replacing the
legacy Plan schema and without adding an independent durable task ledger.

## Contract

- `GovernedTaskLifecycle`: normalized task lifecycle exposed to orchestration,
  progress, checkpoint, and evidence code: `idle`, `planning`, `running`,
  `waiting`, `done`, `failed`, `cancelled`, `inconsistent`.
- `GovernedStepStatus`: step-level state derived from the current plan and
  completion evidence: `pending`, `active`, `awaiting_human`, `awaiting_tool`,
  `completed`, `failed`, `cancelled`.
- `GovernedTaskProgress`: completed step count, total step count, current step
  index, and percent.
- `GovernedTaskState`: read-only snapshot including lifecycle, raw legacy
  status, plan goal, current step, all step states, blocking reason, failure
  reason, and resumable flag.

## Source Of Truth

- Durable runtime fields remain in `agent.state.TaskState`.
- The S2 model is derived by `agent.task_state_model.build_governed_task_state`.
- Step completion still comes from `mark_step_complete` records in
  `tool_execution_log` and `STEP_COMPLETION_THRESHOLD`.
- Checkpoint/resume stays owned by `agent.checkpoint`; S2-G02 only proves that a
  resumed legacy state projects back into the same governed task snapshot.

## Non-Goals

- No independent durable task ledger.
- No replacement of S1 legacy `Plan` / `PlanStep`.
- No activation of Scheduler, MCP, SubAgent, or Skill.
- No real provider call.

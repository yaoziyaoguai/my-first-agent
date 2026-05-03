# Runtime Trace / ToolResult Slice Design

This packet designs small future slices for runtime trace and ToolResult
migration. It is not a broad runtime rewrite, not a broad tool_executor rewrite,
and not a checkpoint/memory migration.

## Runtime Trace Design

### current runtime behavior summary

The runtime already emits user-visible runtime/display events and has local
trace foundation types. `LocalTraceRecorder` is intentionally not wired into
core.py yet, so it cannot read runtime state, sessions, runs, or logs.

### Desired trace event model

Trace events should represent explicit boundary facts:

- model call
- tool call
- tool result
- state transition
- checkpoint save/load marker
- memory/subagent placeholder events only when those systems explicitly opt in

### event schema proposal

Use `TraceEvent` fields:

- run_id
- trace_id
- span_id
- parent_span_id
- span_type
- name
- status
- step_id
- redacted metadata
- sequence assigned by recorder

### Source boundaries

- runtime: constructs high-level state transition facts
- tool executor: constructs tool call/result facts only at explicit boundaries
- tool result: contributes `ToolResultEnvelope.status`, `error_type`, and
  `safe_preview`
- checkpoint: may emit metadata-only checkpoint marker later, not raw contents
- observer/log: must not read `agent_log.jsonl` contents

### non-invasive first slice

- characterization tests for one state transition boundary
- docs for trace sink injection
- optional adapter boundary only if safe
- no core-wide tracing framework

### What not to do yet

- no broad runtime rewrite
- no checkpoint migration
- no memory activation
- no provider/network tracing

### Migration stages

1. Add one adapter function that builds `TraceEvent` from explicit inputs.
2. Add optional trace sink injection at a narrow boundary.
3. Record one state transition in tests.
4. Add tool-result trace metadata after ToolResult compatibility shim exists.
5. Consider broader runtime wiring only after compatibility review.

### rollback strategy

- keep trace sink optional
- keep runtime behavior unchanged when no sink is provided
- remove adapter call without checkpoint/schema changes

### Test plan

- no `agent_log.jsonl` read
- no sessions/runs read
- no secret metadata
- no runtime dependency in `agent.local_trace`
- deterministic JSONL output

## ToolResult Migration Design

### Current ToolResult / tool result contract summary

Tool execution still returns legacy strings to model-visible Anthropic
`tool_result.content`. `ToolResultEnvelope` projects those strings into status,
display event type, error taxonomy, and safe preview without changing model
messages.

### Compatibility risks

- changing model-visible content too early
- breaking tool_result pairing
- leaking secret previews
- mixing policy denial, user rejection, failure, and success
- forcing checkpoint/provider message migrations in one pack

### Desired contract

- legacy string remains available
- structured envelope is available for UI/trace
- error taxonomy is centralized
- safe preview is bounded and redacted
- confirmation and safety policy remain outside ToolResult classification

### Backward compatibility strategy

- use `ToolResultEnvelope.to_legacy_content()` for existing messages
- add compatibility shim plan at executor output boundary
- preserve current prefix classification until all callers migrate
- migrate display/trace consumers before provider/checkpoint contracts

### Characterization tests

- existing string success/failure/rejected behavior
- unknown tool failure mapping
- missing args failure mapping
- KeyboardInterrupt pass-through
- tool_result message shape
- bounded redacted preview

### compatibility shim plan

Add a small shim that accepts either legacy string or `ToolResultEnvelope`, then
normalizes to an envelope for UI/trace while returning legacy content to
provider messages.

### What not to do yet

- no broad tool_executor rewrite
- no breaking existing tools
- no provider message migration
- no checkpoint schema migration

### Migration stages

1. Add shim tests.
2. Add shim without changing executor behavior.
3. Let one display/trace path consume envelope preview.
4. Migrate executor internals behind compatibility tests.
5. Revisit provider/checkpoint only after explicit authorization.

### rollback strategy

- keep legacy string path as source of truth
- disable envelope consumers without changing tool execution
- preserve existing `append_tool_result` shape

### Test plan

- legacy content unchanged
- safe preview redacted
- no executor/runtime import cycles
- no broad tool registry change
- no checkpoint/message schema change

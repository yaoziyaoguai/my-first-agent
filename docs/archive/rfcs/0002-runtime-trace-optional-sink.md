# RFC 0002: Runtime Trace Optional Sink

Status: Draft

## Context

RFC 0001 proved the ToolResult to TraceEvent projection boundary with
`agent.runtime_trace_projection`. The next safest runtime trace step is not a
recorder framework and not a broad runtime rewrite; it is a narrow opt-in sink
that callers can pass explicitly when they want local trace events.

## Problem

`LocalTraceRecorder` and `TraceEvent` exist, but runtime/tool execution has no
safe way to emit a trace event without either:

1. wiring a default recorder into `core.py`, or
2. letting trace code read runtime/checkpoint/session state after the fact.

Both approaches would blur architecture boundaries and increase privacy risk.

## Goals

- add an optional runtime trace event sink
- emit a ToolResult-derived TraceEvent at one explicit tool execution boundary
- preserve current `tool_result` messages and model-visible legacy content
- keep the default runtime path unchanged when no sink is provided
- keep trace construction redacted and bounded through RFC 0001's adapter

## Non-goals

- no default recorder
- no broad runtime rewrite
- no broad tool_executor rewrite
- no checkpoint migration
- no memory activation
- no provider/network/MCP call
- no release/tag
- no attempt to trace every runtime event in one slice

## Current behavior

`chat()` accepts UI-facing output callbacks, and `tool_executor.py` writes
legacy `tool_result` messages plus display events. There is no public
`on_trace_event` callback and no optional trace sink at the tool result boundary.

## Proposed design

Add an optional `on_trace_event` callback to `chat()`. `TurnState` carries the
callback plus per-call trace identifiers. `tool_executor.py` calls a small helper
after it appends the normal legacy `tool_result` message for direct execution and
confirmed pending tools.

The helper:

- no-ops when no sink is provided
- requires explicit trace identifiers when a sink is provided
- builds a TraceEvent through `build_tool_result_trace_event()`
- passes the event to the sink
- does not create or own a `LocalTraceRecorder`

## Architecture boundaries

- `core.py` owns the public callback parameter and per-call trace identity.
- `tool_executor.py` owns the execution boundary where the legacy result already
  exists.
- `agent.runtime_trace_emitter` owns optional sink emission and delegates
  projection to RFC 0001.
- `agent.runtime_trace_projection` owns ToolResult-to-TraceEvent projection.
- `LocalTraceRecorder` remains an explicit sink selected by the caller, not a
  runtime dependency.

## Safety boundaries

- no default recorder
- no real `agent_log.jsonl` read
- no real sessions/runs read
- no secret expansion
- no network
- no MCP endpoint
- no command execution beyond the tool already being executed by existing logic
- no checkpoint schema change
- no broad runtime rewrite
- no broad tool_executor rewrite

## First safe slice

Implement opt-in ToolResult trace emission for:

1. direct `execute_single_tool()` results; and
2. confirmed `execute_pending_tool()` results.

This slice does not trace policy-denial placeholders, user-rejection
placeholders, cached duplicate tool results, model calls, checkpoint operations,
or state transitions. Those remain future gates because they sit at different
ownership boundaries.

## Alternatives considered

1. Wire `LocalTraceRecorder` directly into `chat()`.
2. Let trace code scan conversation messages after tool execution.
3. Emit trace events from `confirm_handlers.py`.
4. Keep RFC-only planning and defer implementation.

## Why rejected

Direct recorder wiring would make tracing a default runtime dependency. Scanning
messages after the fact risks reading more conversation content than needed.
Emitting from confirmation handlers would mix confirmation state transitions with
tool execution semantics. RFC-only planning would not prove the narrow sink
boundary.

## Test strategy

- RFC document contract test
- `chat()` exposes optional `on_trace_event`
- direct tool execution emits one redacted TraceEvent when sink is present
- confirmed pending tool execution emits through the same sink
- default path without sink preserves legacy `tool_result` messages
- dependency boundary test for the emitter helper
- full pytest / ruff / diff-check

## Migration plan

1. Add optional trace sink callback.
2. Emit only ToolResult trace events at the existing tool execution boundary.
3. Keep LocalTraceRecorder explicit and caller-owned.
4. Later add characterization tests for state transition trace events.
5. Later evaluate ToolResult compatibility shim and provider/checkpoint migration.

## Rollback plan

Remove the optional callback parameter, `runtime_trace_emitter`, and the two
emitter calls. Because this slice leaves default behavior and checkpoint/message
schema unchanged, rollback does not require data migration.

## Risks

- Sink failures could interrupt an opt-in caller; mitigation: do not swallow
  sink exceptions silently, and keep the default path sink-free.
- Trace identifiers could become durable runtime state; mitigation: keep them in
  ephemeral `TurnState` only.
- Tool executor could become trace-heavy; mitigation: one helper call at the
  existing result boundary and dependency tests.

## Open questions

- Should policy denial and user rejection placeholders become trace events in a
  separate confirmation-boundary RFC?
- Should future trace identity come from a caller-provided run/session id instead
  of generated per-chat ids?
- Which state transition should be the first non-tool trace event?

## Required human authorization

Future default recorder wiring, checkpoint schema changes, provider message
changes, broad executor migration, real MCP integration, and release/tag work
require explicit human authorization.

## Future gates

- RFC 0003: ToolResult compatibility shim at executor boundary
- RFC 0004: state transition trace characterization
- RFC 0005: optional LocalTraceRecorder integration for safe tmp paths
- RFC 0006: provider/checkpoint migration review

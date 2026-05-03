# RFC 0001: Runtime Trace + ToolResult Boundary

Status: Draft

## Context

First Agent already has `LocalTraceRecorder`, `TraceEvent`, and
`ToolResultEnvelope`, but runtime trace wiring and full ToolResult migration are
still deferred. The next gate should create a small boundary between legacy tool
results and local trace metadata without changing runtime behavior.

## Problem

Tool execution results are still legacy strings, while trace events need
structured status, error type, and safe previews. Connecting these directly in
`core.py` or `tool_executor.py` would risk a broad runtime/tool migration.

## Goals

- prove ToolResult data can be projected into TraceEvent metadata
- keep model-visible legacy tool result content unchanged
- keep trace output redacted and bounded
- add a non-invasive first safe slice

## Non-goals

- no broad runtime rewrite
- no broad tool_executor rewrite
- no checkpoint migration
- no memory activation
- no provider/network/MCP call
- no tag/release

## Current behavior

`tool_result_contract.classify_tool_result()` can classify legacy strings into a
`ToolResultEnvelope`. `local_trace.TraceEvent` can carry redacted metadata, but
runtime code does not yet build trace events from tool results.

## Proposed design

Add a small projection adapter that accepts explicit boundary fields and a
legacy tool result string, classifies it with `ToolResultEnvelope`, and returns a
`TraceEvent`. The adapter does not execute tools, mutate runtime state, write
checkpoints, read logs, or call providers.

## Architecture boundaries

- Adapter imports only `agent.local_trace` and `agent.tool_result_contract`.
- Runtime remains parent controller.
- Tool executor remains the execution coordinator.
- Trace recorder remains a local sink.
- ToolResult contract remains classification/projection logic.

## Safety boundaries

- no real `agent_log.jsonl` read
- no real sessions/runs read
- no secret expansion
- no network
- no MCP endpoint
- no command execution
- no broad runtime rewrite
- no broad tool_executor rewrite

## First safe slice

Create `agent.runtime_trace_projection.build_tool_result_trace_event()` and
contract tests. This first slice has no production behavior change unless future
callers explicitly use the adapter.

## Alternatives considered

1. Wire `LocalTraceRecorder` directly into `core.py`.
2. Migrate `tool_executor.py` to return `ToolResultEnvelope`.
3. Keep docs-only planning.

## Why rejected

Direct runtime wiring and executor migration are too broad for the first RFC
gate. Docs-only planning would not prove the boundary can work. A pure adapter
is the smallest useful implementation.

## Test strategy

- RFC document contract test
- projection builds redacted `TraceEvent`
- rejected-by-check maps to skipped trace status
- dependency boundary test: no runtime/executor/registry imports
- full pytest / ruff / diff-check

## Migration plan

1. Add pure projection adapter.
2. Keep runtime and executor behavior unchanged.
3. Later add optional sink injection at one explicit boundary.
4. Later let display/trace consumers use safe previews.
5. Only after review, consider executor/provider/checkpoint migration.

## Rollback plan

Remove the unused adapter and tests. Because no runtime caller is wired in this
slice, rollback does not require checkpoint, provider, or message migration.

## Risks

- Status mapping could overstate rejection as failure; mitigation: map
  `rejected_by_check` to trace `skipped`.
- Preview could leak secrets; mitigation: reuse `ToolResultEnvelope.safe_preview`
  and `TraceEvent` redaction.
- Adapter could become a hidden runtime dependency; mitigation: dependency tests.

## Open questions

- Which runtime boundary should emit the first real trace event?
- Should rejected tool checks use `skipped` or a future dedicated trace status?
- Where should optional trace sink injection live?

## Required human authorization

Future runtime wiring, executor migration, checkpoint schema changes, provider
message changes, and release/tag work require explicit human authorization.

## Future gates

- RFC 0002: optional runtime trace sink injection
- RFC 0003: ToolResult compatibility shim at executor boundary
- RFC 0004: provider/checkpoint ToolResult migration review

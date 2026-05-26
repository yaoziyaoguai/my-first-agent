# Runtime Trace / ToolResult Migration Ledger

This document is the Remaining Roadmap migration ledger for **runtime trace
wiring** and **ToolResult migration**. It is compatibility-first planning and
contract evidence, not a broad runtime rewrite or a broad tool_executor rewrite.

## Current foundation

- `LocalTraceRecorder` provides a local-only JSONL recorder for explicit
  temporary paths.
- `TraceEvent` provides run/trace/span identity, span vocabulary, status, and
  redacted metadata.
- `ToolResultEnvelope` projects legacy string tool results into status,
  display event type, error taxonomy, content length, and safe preview.
- `classify_tool_result` and `classify_tool_outcome` keep result classification
  centralized outside the executor.

中文学习边界：runtime trace wiring 与 ToolResult migration 都靠近 hot path。正确推进
方式不是把 core.py 或 tool_executor.py 一次性重写，而是先用 compatibility tests
证明两个 foundation seam 可以组合，再用小切片逐步迁移事件构造、display 投影和
checkpoint/message compatibility。

## Migration ledger

| Area | Next safe step | Stop condition |
|---|---|---|
| runtime trace wiring | add a non-invasive adapter that converts explicit runtime boundary facts into `TraceEvent` objects | needs checkpoint/session/log reads, broad runtime state rewrite, or provider call |
| ToolResult migration | add a compatibility shim that accepts legacy string and structured envelope while preserving Anthropic `tool_result.content` | needs broad tool_executor rewrite, checkpoint schema change, or provider message migration |
| trace + ToolResult bridge | put `ToolResultEnvelope.status`, `error_type`, and `safe_preview` into trace metadata at explicit tool-result boundaries | needs real runtime trace wiring or durable state migration |
| display output | continue using display/runtime events; only consume safe preview for UI/trace | needs UI protocol rewrite |
| release readiness | keep migration evidence as docs/tests until a concrete implementation slice is authorized | needs tag/release |

## Non-invasive adapter strategy

A future runtime trace adapter should:

- accept already-known boundary fields from runtime/tool executor callers
- build `TraceEvent` objects without reading `agent_log.jsonl`, `sessions/`, or
  `runs/`
- write only to explicit safe paths through `LocalTraceRecorder`
- redact metadata before serialization
- avoid importing runtime/core into `agent.local_trace`

It must not:

- mutate runtime state
- write checkpoints
- read real run/session artifacts
- call providers, MCP endpoints, or network services
- become a dashboard or tracing framework

## Compatibility shim strategy

A future ToolResult compatibility shim should:

- keep legacy string content available through `ToolResultEnvelope.to_legacy_content()`
- preserve existing `tool_result` message shape
- preserve current success/failure/rejected classification
- expose bounded redacted preview for UI/trace
- centralize error taxonomy in `agent.tool_result_contract`

It must not:

- change model-visible tool result content without a migration slice
- require a checkpoint schema migration in the same pack
- make `tool_result_contract` import executor/runtime/registry
- bypass confirmation or tool safety policy

## Compatibility tests already proving readiness

- trace metadata redacts secret-like values without env expansion
- `LocalTraceRecorder` rejects `agent_log.jsonl`, `sessions/`, and `runs/`
- `ToolResultEnvelope` preserves legacy content and provides safe preview
- trace events can carry ToolResult envelope preview metadata without runtime
  wiring
- local trace and ToolResult contract modules do not import runtime/executor
  layers

## Deferred implementation slices

1. Add explicit runtime boundary event construction for one low-risk state
   transition.
2. Add optional local trace sink injection in a narrow adapter, not in
   `LocalTraceRecorder`.
3. Add a ToolResult compatibility shim at executor output boundary while keeping
   legacy string messages.
4. Add display/trace preview consumption tests.
5. Only after those pass, consider broader executor/provider/checkpoint
   migration.

## Hard non-goals

- no broad runtime rewrite
- no broad tool_executor rewrite
- no checkpoint migration
- no memory activation
- no real sessions/runs reads
- no real `agent_log.jsonl` read
- no provider/network/MCP call
- no tag/release

The final slice design packet is
`docs/RUNTIME_TRACE_TOOLRESULT_SLICE_DESIGN.md`.

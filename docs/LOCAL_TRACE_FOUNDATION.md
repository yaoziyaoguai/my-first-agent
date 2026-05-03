# Local Trace Foundation

This document records the Stage 6 local trace foundation. It is a local schema
and safe recorder seam, not a dashboard, tracing framework, runtime rewrite, or
provider integration.

## Scope

- local-only trace file schema
- `TraceEvent` with run, trace, span, parent span, step, status, and metadata
- `LocalTraceRecorder` for explicit temporary JSONL output paths
- span vocabulary for model calls, tool calls, state transitions, checkpoints,
  memory updates, and subagents
- redacted metadata for secret-like keys and values

## Safety boundaries

- no real `agent_log.jsonl`
- no real `sessions/`
- no real `runs/`
- no provider/network call
- no env secret expansion
- no runtime core wiring yet
- no dashboard

## Deferred work

Runtime wiring should be a later small slice: runtime code may construct
`TraceEvent` objects at explicit boundaries, then pass them into the recorder.
The recorder must not read runtime state, checkpoint files, sessions, runs, or
logs by itself.

The staged compatibility plan for runtime trace wiring is recorded in
`docs/RUNTIME_TRACE_TOOLRESULT_MIGRATION.md`. That ledger keeps future work
non-invasive: trace adapters may build `TraceEvent` from explicit boundary
facts, but `LocalTraceRecorder` must not become runtime core.

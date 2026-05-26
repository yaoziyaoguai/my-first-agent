# ToolResult Envelope Foundation

This document records the Stage 7 structured ToolResult seam. It projects the
existing legacy string result contract into a safer UI/trace-friendly envelope
without migrating the executor or changing model-visible tool results.

## Scope

- `ToolResultEnvelope`
- `classify_tool_result`
- status values for executed, failed, and rejected-by-check outcomes
- error taxonomy for unknown tools, timeouts, HTTP failures, safety rejection,
  skill lifecycle errors, and generic tool failures
- bounded safe preview with secret redaction
- compatibility with `classify_tool_outcome`

## Safety boundaries

- no broad executor migration
- no checkpoint/messages protocol rewrite
- no tool registry rewrite
- no runtime core rewrite
- no secret leakage in preview
- no change to model-visible legacy string content

## Deferred work

Full migration should be a separate tool-system slice. It must preserve legacy
compatibility until executor, registry, checkpoint, display, and provider message
contracts are explicitly migrated together.

The staged ToolResult migration ledger is recorded in
`docs/RUNTIME_TRACE_TOOLRESULT_MIGRATION.md`. That plan keeps
`ToolResultEnvelope` as a compatibility seam first: legacy string content remains
model-visible while UI/trace can consume redacted bounded preview fields.

# Deferred Roadmap Boundaries

This document records the remaining roadmap items that are not safe to implement
automatically after the safe-local MVP closure. It is planning-only evidence, not
authorization to tag, release, connect external services, or rewrite runtime
modules.

## Deferred because they require real external integration

- real MCP external integration: external endpoints, transports, resources,
  prompts, sampling, roots, auth, and reachability checks
- fake-first readiness for that boundary is documented in
  `docs/MCP_EXTERNAL_INTEGRATION_READINESS.md`
- real Skill install/execution: downloading, installing, or executing external
  skill code
- real Subagent provider delegation: real LLM/provider calls, remote agents,
  external processes, or autonomous child tool execution

## Deferred because they require broad migration

- runtime trace wiring: connecting `LocalTraceRecorder` to runtime/core
  transitions must be designed as small explicit slices
- ToolResult executor migration: replacing legacy string tool results with
  structured envelopes touches executor, registry, checkpoint, provider messages,
  display, and compatibility tests

## Deferred release boundary

- release/tag work is planning-only until explicitly authorized
- no tag
- no push tags
- no release creation

## Current safety floor

- no real external integration
- no real MCP endpoint
- no real provider/network call
- no real home config write
- no real skill/subagent dirs
- no memory activation
- no broad runtime/tool executor migration

The next safe step for any item in this file is a separate planning or TDD slice
with explicit scope, red tests, quality gates, and controlled push rules.

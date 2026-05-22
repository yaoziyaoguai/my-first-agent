---
title: Tool branch confirmation_required behavior test
type: remediation-hold-plan
status: blocked
date: 2026-05-22
supersedes: ToolRegistry Confirmation Required Anchor E2E
---

# Tool Branch `confirmation_required` Behavior Test

This file is intentionally blocked. It preserves the old Tool Confirmation idea
only as a future branch behavior test, not as active implementation work.

Do not implement this plan until the unified runtime flow remediation is complete
and independently reviewed.

## Contract Reference

Future work must follow:

- `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md`

Required framing:

- Unified Runtime Flow
- Branch Behavior
- Harness/subsystem evidence classification

Forbidden framing:

- new Anchor
- Anchor family
- Tool Confirmation Anchor
- Safe Tool Anchor follow-up

## Current Status

Blocked until these remediation items are complete:

1. `real_core_loop_runtime_e2e` cannot be spoofed by direct dispatcher payload.
2. `_safe_noop` is restored as an internal non-model-visible branch behavior tool.
3. Direct-dispatch dogfood reports are downgraded to harness/subsystem evidence.
4. Historical Anchor docs are reframed as validation artifacts.

## Future Scope If Re-authorized

The only possible future scope is:

```text
core.chat
  -> runtime loop
  -> documented Tool branch point
  -> RuntimeActionDispatcher
  -> ToolGateHandler / ToolRegistry policy
  -> gate_disposition == "confirmation_required"
  -> evidence classified honestly
  -> return to runtime loop
```

This would be a Tool branch behavior test for `confirmation_required`. It would
not prove full model `tool_use -> ToolRegistry gate -> tool executor` execution.
That larger design remains deferred.

## Explicit Non-Goals

Do not do any of the following from this file:

- create `_confirmable_noop`
- implement Tool Confirmation
- add Tool Args work
- add Tool Result work
- add Retry / Error Recovery work
- add Multi Tool work
- add MCP Tool work
- add Skill / Checkpoint / Streaming / SubAgent work
- create a new Anchor milestone

## Negative Tests

Tool `blocked` and `not_found` are negative branch behavior tests. They should be
covered as tests inside the Tool branch family if this work is re-authorized.
They must not become separate milestones or new plans.

## Temporary Stop Rule

After Tool gate `allowed`, `confirmation_required`, `blocked`, and `not_found`
are covered as branch behavior tests, Tool branch gate behavior should stop.
Further Tool work requires a new explicit design review because it moves beyond
gate behavior into real tool execution, result routing, retries, MCP, or other
larger runtime design.

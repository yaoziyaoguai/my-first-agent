# Unified Runtime Flow Remediation Implementation Notes

Date: 2026-05-22

## Summary

This remediation converts the current Memory/Tool/Dogfood/Anchor work back into
the Unified Runtime Flow + Branch Behavior model.

It does not implement Tool Confirmation, `_confirmable_noop`, Tool Args, Tool
Result, Retry, MCP, Skill, Checkpoint, Streaming, or SubAgent work.

## What Changed

- Added `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md`.
- Rewrote the stale Tool Confirmation plan as a blocked branch behavior plan.
- Added dispatcher-owned runtime-loop provenance so direct dispatcher payloads
  cannot spoof `real_core_loop_runtime_e2e`.
- Kept `RuntimeActionDispatcher.route()` as harness/direct dispatch.
- Added `RuntimeActionDispatcher.route_from_runtime_loop()` as the only
  runtime-loop route capable of producing real core-loop classification.
- Restored `_safe_noop` as an internal non-model-visible Tool branch behavior
  tool.
- Reframed dogfood report language and checkers toward branch behavior and
  harness/subsystem evidence.

## Evidence Classification Boundary

`RuntimeActionRequest.payload` is subsystem input, not trusted runtime
provenance. Before this remediation, direct dispatcher tests could set:

```python
{"core_loop_invoked": True, "core_entrypoint": "core.chat"}
```

and get `real_core_loop_runtime_e2e`. That was an overclaim risk.

After remediation:

- direct `dispatcher.route()` writes `dispatcher_origin="direct_dispatcher"`
- runtime loop routing writes `dispatcher_origin="runtime_loop"`
- `real_core_loop_runtime_e2e` requires runtime-loop provenance plus normal
  target-module proof
- direct dispatcher with full proof is `harness_runtime_e2e`

## Tool Boundary

`_safe_noop` remains in production `TOOL_REGISTRY` so ToolGateHandler can verify
the ToolRegistry gate path. It is excluded from `get_model_visible_tools()` by
the underscore prefix filter, including when an explicit allowlist is provided.

This keeps `_safe_noop` as an internal branch behavior tool rather than a model
tool.

## Dogfood Boundary

Dogfood scripts that call `core.chat` may report real core loop evidence when the
runtime produces it. Dogfood scripts that construct RuntimeAction requests or
call dispatcher directly may report harness evidence only.

Dogfood checkers must find Memory and Tool actions by `action_type`, not by list
position, because lifecycle hook order is not the contract.

## Deferred Work

The real model `tool_use -> ToolRegistry gate -> tool executor` chain is still a
larger design item. This remediation only makes current naming, evidence, and
internal-tool contracts honest.

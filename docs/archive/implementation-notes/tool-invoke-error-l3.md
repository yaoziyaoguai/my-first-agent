# Implementation Notes: Tool Invoke error L3

Date: 2026-05-24
Status: complete

## What was done

Added L3 evidence tests for TOOL_INVOKE execution_status="error" path.

## Changes

### New files
- `docs/specs/tool-invoke-error-l3/SPEC.md`
- `docs/specs/tool-invoke-error-l3/TDD.md`
- `tests/runtime_integration/test_tool_invoke_error_l3.py` — 3 tests

### Zero changes to
- `agent/` — all production code untouched

## Test results

```
T1: core.chat() → gate allowed → invoke error → L3 PASSED
T2: direct dispatcher → L2, payload spoofing rejected PASSED
T3: isolated HOME, no real API PASSED

Regression: 312 passed, 5 skipped, 0 failed
```

## Approach

Registered `error_tool` with confirmation="never" (passes TOOL_GATE) but raises
ValueError (triggers TOOL_INVOKE execution_status="error"). core.chat() with
tool_gate_tool_name="error_tool" activates the full gate→invoke→result pipeline.

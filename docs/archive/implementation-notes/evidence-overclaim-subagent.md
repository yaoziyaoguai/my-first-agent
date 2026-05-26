# Implementation Notes: Evidence Overclaim Prevention — SubAgent Target

Date: 2026-05-24
Status: complete

## What was done

Added SubAgent overclaim prevention tests to `test_runtime_action_contract.py`.

SubAgent was the only cataloged target without either `_ForgedTargetLabelHandler` or
`_CatalogAllowedForgedCallableHandler` overclaim protection. All other targets
(ToolRegistry, SkillLoader, SkillRegistry, CheckpointSafeSummary, StreamingProtocol)
already had both or one variant.

## Changes

### Modified files
- `tests/runtime_integration/test_runtime_action_contract.py` — +58 lines (2 tests)
- `docs/plans/first-agent-subsystem-integration-roadmap.md` — updated queue

### New files
- `docs/specs/evidence-overclaim-subagent/SPEC.md`
- `docs/specs/evidence-overclaim-subagent/TDD.md`

### Zero changes to
- `agent/` — all production code untouched

## Test results

```
T1: ForgedTargetLabel → SubAgentExecutor → rejected PASSED
T2: CatalogAllowedForgedCallable → SubAgentExecutor → rejected PASSED

Regression: 314 passed, 5 skipped, 0 failed (runtime_integration)
Full suite: 3097 passed, 19 skipped, 2 failed (pre-existing in test_tool_registry_contract)
```

## Approach

Reused existing `_ForgedTargetLabelHandler` and `_CatalogAllowedForgedCallableHandler`
test infrastructure. Key finding: `parent_adjudicated` is in `HANDLER_EVIDENCE_RESERVED_FIELDS`
so handler-supplied evidence_extra cannot set it — the classifier owns that field.

## Note on pre-existing failures

`test_tool_registry_contract.py` has 2 tests that fail when run with the full suite but pass
individually — likely test ordering / global TOOL_REGISTRY state issue. Not related to
these changes.

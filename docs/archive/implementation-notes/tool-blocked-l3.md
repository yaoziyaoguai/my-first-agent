# Implementation Notes: Tool Gate blocked L3

Date: 2026-05-24
Status: complete

## What was done

Added L3 evidence tests for Tool gate blocked disposition (third of four Tool gate dispositions: allowed, confirmation_required, blocked, not_found).

## Changes

### New files
- `docs/specs/tool-blocked-l3/SPEC.md` — SPEC for shell-like + _ prefix blocked paths
- `docs/specs/tool-blocked-l3/TDD.md` — TDD: 4 tests (T1 shell-like L3, T2 _ prefix L3, T3 L2 downgrade, T4 no real API)
- `docs/specs/tool-blocked-l3/IMPLEMENTATION_PLAN.md` — zero production code change plan
- `tests/runtime_integration/test_tool_blocked_l3.py` — 4 passing tests

### Modified files
- `docs/plans/first-agent-subsystem-integration-roadmap.md` — updated Evidence Matrix (Tool not_found L1/L2/L3 → ✅, Checkpoint L3 → ✅, added Tool blocked L3 row), expanded auto-run queue (5 candidates), updated Backlog

### Zero changes to
- `agent/` — all production code untouched
- `tests/runtime_integration/` existing files — untouched

## Test results

```
tests/runtime_integration/test_tool_blocked_l3.py::TestCoreChatShellLikeBlockedL3::test_t1_core_chat_shell_like_tool_blocked_l3 PASSED
tests/runtime_integration/test_tool_blocked_l3.py::TestCoreChatUnderscoreBlockedL3::test_t2_core_chat_underscore_tool_blocked_l3 PASSED
tests/runtime_integration/test_tool_blocked_l3.py::TestDirectDispatcherBlockedL2::test_t3_direct_dispatcher_route_blocked_is_l2 PASSED
tests/runtime_integration/test_tool_blocked_l3.py::TestNoRealAPIOrEnv::test_t4_no_real_api_or_env_access PASSED

Regression: tests/runtime_integration/ — 309 passed, 5 skipped, 0 failed
```

## Evidence classification

- T1: `real_core_loop_runtime_e2e` — shell-like tool via core.chat()
- T2: `real_core_loop_runtime_e2e` — _ prefix tool via core.chat()
- T3: `harness_runtime_e2e` — direct dispatcher (classification downgrade verified)
- T4: `real_core_loop_runtime_e2e` — isolated HOME + FakeProvider

## Architecture compliance

- No new RuntimeActionType
- No new handler
- No new branch point
- No new runtime flow
- No new Anchor
- No production code changes
- Fake/real share same code path

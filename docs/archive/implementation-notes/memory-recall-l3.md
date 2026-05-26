# Memory Recall L3 Wiring Implementation Notes

Date: 2026-05-24
Capability: MEMORY_RECALL RuntimeActionType L3

## Change Summary

- Wired MEMORY_RECALL into `agent/loop.py` `_try_phase1_turn_end_runtime_action()`
  turn-end hook (normal capability loop — existing branch point, no new architecture)
- Added 3 L3 tests via `tests/runtime_integration/test_memory_recall_l3.py`
- Updated `test_phase1_real_core_loop.py` `_build_phase1_dispatcher` to register
  MemoryRecallHandler (regression fix)
- Updated SPEC with L3 Wiring Architecture Decision

## Architecture Decision

MEMORY_RECALL handler already existed in `agent/runtime_integration/memory_recall.py`,
was registered in `build_phase1_dispatcher()`, but was never dispatched from the
real runtime loop. This gap meant all MEMORY_RECALL evidence was L2 max
(harness_runtime_e2e).

Turn-end dispatch was chosen over pre-loop dispatch because:
- Existing branch point — no new architecture elements
- Turn-end is when store state is most complete (retain + consolidate done)
- Same pattern as MEMORY_CONSOLIDATE wiring
- L3 evidence proves handler works from real runtime loop; prompt injection
  remains unchanged (handled by `refresh_runtime_system_prompt()`)

## Files Changed

- `agent/loop.py` — 36 lines added: MEMORY_RECALL dispatch block + docstring updates
- `docs/specs/memory-recall-branch-behavior/SPEC.md` — L3 Architecture Decision section
- `tests/runtime_integration/test_memory_recall_l3.py` — new: 3 L3 tests
- `tests/runtime_integration/test_phase1_real_core_loop.py` — 5 lines: MemoryRecallHandler registration
- `docs/implementation-notes/memory-recall-l3.md` — this file

## Test Results

- 3/3 new L3 tests pass
- Full regression: 348 passed, 5 skipped, 0 failed
- ruff: clean

## Evidence Level

MEMORY_RECALL now achieves `real_core_loop_runtime_e2e` evidence:
- dispatcher_origin="runtime_loop"
- runtime_loop_invoked=True
- core_entrypoint="core.chat"
- runtime_hook_name="loop.turn_end"
- target_module="MemoryRuntime"
- target_catalog_allowed=True

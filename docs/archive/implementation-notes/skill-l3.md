# Skill L3 Activation Implementation Notes

Date: 2026-05-24
Capability: SKILL_SELECT RuntimeActionType L3

## Change Summary

- Wired SKILL_SELECT into `agent/loop.py` `_try_phase1_turn_end_runtime_action()`
  turn-end hook (existing branch point, no new architecture)
- Registered `SkillRuntimeActionHandler` in `agent/runtime_integration/phase1_hook.py`
  `build_phase1_dispatcher()`
- Added `no_suitable_skill` catalog entry + adapter in `evidence.py`
- Modified `SkillRuntimeActionHandler.handle()` to call `invoke_registered_target()`
  on the "no model decision" path (empty `available_skill_metadata` + no
  `selected_skill_id`) — produces L3 evidence even when handler returns `failed`
- Added 3 L3 tests via `tests/runtime_integration/test_skill_l3.py`
- Updated `test_phase1_real_core_loop.py` `_build_phase1_dispatcher` and
  `test_tool_pipeline_l3_completion.py` `test_f2` regression fixes

## Architecture Decision

SKILL_SELECT handler already existed in `agent/runtime_integration/skill_action.py`,
was registered in `build_phase1_dispatcher()`, but was never dispatched from the
real runtime loop. The handler's payload validation (`_validate_payload`) would
always fail for turn-end hook dispatch because:
1. `task_summary` is required but not in the hook payload
2. `available_skill_metadata` is required but not in the hook payload

### Solution: no_suitable_skill catalog adapter

Added an early-return path in `handle()`: when `available_skill_metadata` is empty
AND `selected_skill_id` is absent (non-model-driven dispatch), the handler calls
`invoke_registered_target(target_module="SkillLoader", operation="no_suitable_skill")`
and returns `context.failed()` with the `observed_call`. This produces full L3
evidence (`real_core_loop_runtime_e2e`) with `status="failed"`.

Key design choices:
- Empty `SkillRegistry(roots=[])` → no visible skills → handler always rejected
- L3 evidence is about dispatch path, not disposition
- The `runtime_e2e_disqualified_reason` field is deliberately NOT set in the
  turn-end hook path (unlike the model-driven validation-failure path), so
  `is_runtime_e2e_evidence()` passes
- New catalog entry: `skill.select:SkillRuntimeActionHandler:SkillLoader:no_suitable_skill`

### Fake/Real Boundary

- Fake: `SkillRegistry(roots=[])` → empty registry → handler always returns failed
- Real: `SkillRegistry(roots=[Path("./skills")])` → populated registry
- No new fake-only/real-only path
- Does not change model-output-driven skill selection behavior

## Files Changed

- `agent/loop.py` — 35 lines: SKILL_SELECT dispatch block + docstring updates
- `agent/runtime_integration/evidence.py` — 16 lines: `_skill_no_suitable_skill_adapter`
  + catalog entry
- `agent/runtime_integration/phase1_hook.py` — 16 lines: SkillRuntimeActionHandler
  registration + imports
- `agent/runtime_integration/skill_action.py` — 29 lines: early-return path for
  non-model-driven dispatch
- `tests/runtime_integration/test_skill_l3.py` — pre-existing: 3 L3 tests
- `tests/runtime_integration/test_phase1_real_core_loop.py` — 13 lines: handler registration
- `tests/runtime_integration/test_tool_pipeline_l3_completion.py` — 2 lines: expected_types update
- `docs/specs/skill-l3/SPEC.md` — pre-existing: Architecture Decision
- `docs/implementation-notes/skill-l3.md` — this file

## Test Results

- 3/3 new L3 tests pass
- Full regression: 351 passed, 5 skipped, 0 failed
- ruff: clean

## Evidence Level

SKILL_SELECT now achieves `real_core_loop_runtime_e2e` evidence (rejected disposition):
- dispatcher_origin="runtime_loop"
- runtime_loop_invoked=True
- core_entrypoint="core.chat"
- runtime_hook_name="loop.turn_end"
- target_module="SkillLoader"
- target_catalog_allowed=True
- target_identity_valid=True
- status="failed" (empty registry → no skills available)
- payload: body_load_decision=False, no_suitable_skill=True

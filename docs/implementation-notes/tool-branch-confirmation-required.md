# Implementation Notes: Tool Branch confirmation_required Behavior

Status: completed
Date: 2026-05-23
Plan: [IMPLEMENTATION_PLAN.md](../../docs/specs/tool-branch-confirmation-required/IMPLEMENTATION_PLAN.md)
SPEC: [SPEC.md](../../docs/specs/tool-branch-confirmation-required/SPEC.md)
TDD: [TDD.md](../../docs/specs/tool-branch-confirmation-required/TDD.md)

## 1. Implemented

### U1: Test File (21 tests)

Created `tests/runtime_integration/test_tool_branch_confirmation_required.py` with 20 tests in U1 + 1 test (B2) in U4 = 21 total.

Test distribution:
- **Phase A** (A1-A7, 7 tests): confirmation_required positive examples — always, callable_true, callable_args, default, function_not_invoked, no_side_effects, evidence_structure
- **Phase B** (B1-B4, 4 tests): classification boundaries — direct dispatcher→harness, real_core_loop (B2, U4), direct handler→subsystem, payload anti-spoofing
- **Phase C** (C1-C4, 4 tests): negative coverage — not_found, forbidden, callable_block, not_model_visible
- **Phase D** (D1-D4, 4 tests): memory/tool isolation — cross-contamination prevention
- **Phase E** (E1-E2, 2 tests): fake/real boundary — same gate logic, no real API

L1 tests (A5, B3) required proper `RuntimeActionContext` construction with full `handler_identity` (fully qualified module path) to match `RuntimeActionTargetCatalog` entries.

C4 required monkeypatching `agent.tool_registry.get_model_visible_tools` (not `tool_gate` module) because `ToolGateHandler.handle()` imports it via `from import` inside the method.

### U2: _confirmable_noop Tool + Allowlist

Created `agent/tools/confirmable_noop.py` — mirrors `safe_noop.py` exactly except:
- `name="_confirmable_noop"`, `confirmation="always"` (vs. `"never"`)
- Returns `"confirmable_noop: ok"`

Allowlist at `tool_gate.py:96`: `tool_name == "_safe_noop"` → `tool_name in ("_safe_noop", "_confirmable_noop")`.

Updated `agent/tools/__init__.py` to import `_confirmable_noop` (not in `__all__` — internal tool).

Updated `tests/test_tool_registry_contract.py` — added `_confirmable_noop` to `EXPECTED_INTERNAL_TOOL_SPECS`.

### U3: LoopDependencies.tool_gate_tool_name

Added `tool_gate_tool_name: str = "_safe_noop"` field to `LoopDependencies` dataclass, following the same pattern as `provider_kind` / `provider_external_call`.

Changed `loop.py:113` from hardcoded `"_safe_noop"` to variable `tool_gate_tool_name`, resolved from dependencies via `getattr(dependencies, "tool_gate_tool_name", "_safe_noop")`.

Default `"_safe_noop"` guarantees zero behavior change for all existing callers.

### U4: B2 L3 Test

`test_route_from_runtime_loop_is_real_core_loop_e2e` — confirms that `route_from_runtime_loop()` with `_confirmable_noop` produces `evidence_level=real_core_loop_runtime_e2e` with `gate_disposition=confirmation_required`.

## 2. Tradeoffs / Deviations

- **B2 test does not go through `core.chat()`**: The plan acknowledged this — calling `core.chat()` requires model/provider setup. Instead, B2 directly exercises `route_from_runtime_loop()` which is the same entry point `core.chat()` uses. The classification relies on the dispatcher route method, not on the model call.

- **L1 tests directly construct `RuntimeActionContext`**: This requires matching `RuntimeActionTargetCatalog` entries (handler_identity must be fully qualified). Acceptable for L1 subsystem tests — the TDD explicitly labels these as `subsystem_integration`.

- **21 total tests vs. plan's 22**: The TDD matrix has exactly 21 entries (A1-A7=7, B1-B4=4, C1-C4=4, D1-D4=4, E1-E2=2). The plan's count of 22 was a minor overcount.

## 3. Not Implemented (Deferred / Out of Scope)

Per Plan §2.2 and §2.3:
- Tool Args / Tool Result feedback
- Retry / Error Recovery
- Multi Tool / MCP Tool
- Real shell/file tool / real API
- UI confirmation interaction
- True model tool_use execution chain
- Fake/real dual path
- Dogfood direct RuntimeAction impersonation
- Callable confirmation dynamic args semantics
- Streaming / SubAgent / Checkpoint TOOL_GATE interaction

## 4. Regression Risk

| Risk | Mitigation |
|------|-----------|
| `_safe_noop` → `allowed` path broken | `tool_gate_tool_name` defaults to `"_safe_noop"`; dogfood PASS; 2950 tests PASS |
| Allowlist expansion introduces security hole | `_confirmable_noop` is zero-side-effect; allowlist is still explicit enumeration |
| LoopDependencies field breaks callers | Default value guarantees backward compatibility |

## 5. Verification Results

- `ruff check agent/ tests/ scripts/` — All checks passed
- `pytest tests/runtime_integration/test_tool_branch_confirmation_required.py` — 21/21 pass
- `pytest tests/runtime_integration/test_tool_anchor_fake.py` — 14/14 pass (no regression)
- `pytest tests/test_tool_registry_contract.py` — 14/14 pass
- `pytest tests/runtime_integration/` — 165 passed, 4 skipped
- `pytest` (full suite) — 2950 passed, 18 skipped
- `scripts/dogfood_phase1_real_core_loop.py` — PASSED
- `git diff --check` — exit code 0

## 6. No Backtrack

No backtrack events occurred during implementation. Each unit completed cleanly with only minor test fix-ups (RuntimeActionContext construction, monkeypatch target module, contract test expected set update).

## 7. Modified Files

- `agent/loop.py` — LoopDependencies +1 field, _try_phase1_turn_end_runtime_action +3 lines
- `agent/runtime_integration/tool_gate.py` — allowlist expansion (1 line)
- `agent/tools/__init__.py` — import _confirmable_noop
- `agent/tools/confirmable_noop.py` — new file
- `tests/runtime_integration/test_tool_branch_confirmation_required.py` — new file (21 tests)
- `tests/test_tool_registry_contract.py` — EXPECTED_INTERNAL_TOOL_SPECS updated

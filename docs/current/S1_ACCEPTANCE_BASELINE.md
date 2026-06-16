# S1 Acceptance Baseline

> Authority: this file defines the S1 acceptance baseline selected by G-17.
> `S1_GOAL.md` remains the frozen S1 goal, and `S1_GOAL_GAP.md` remains the
> active release backlog.

## Scope

G-17 specifies the S1 acceptance test set and release gate classification. It
does not execute real provider smoke. Real provider smoke execution belongs to
G-03 Verification.

For G-17, the required output is:

- the fake/local commands that must pass for the S1 release gate;
- the classification of smoke, golden, and runtime integration tests for S1;
- the location, command, preconditions, and safety boundaries for the later
  real provider smoke handled by G-03.

## S1 Release Gate: Fake / Local

The S1 fake/local acceptance gate is the following command set:

```bash
.venv/bin/python -m pytest tests/golden_e2e -q
.venv/bin/python -m pytest tests/smoke/test_first_usable_task_e2e.py -q
.venv/bin/python -m pytest tests/runtime_integration/test_phase1_real_core_loop.py::TestCoreChatWiring::test_core_chat_actually_invokes_runtime_action_dispatcher_from_turn_end_hook -q
```

These commands are local-only and deterministic for the S1 acceptance baseline.
They do not require real provider keys, network access, `.env`, or local runtime
config inspection.

## Test Classification

| Area | Path / command | S1 classification |
|---|---|---|
| Golden E2E | `tests/golden_e2e` | Required S1 release gate for AC-1 fake deterministic acceptance. |
| First usable smoke | `tests/smoke/test_first_usable_task_e2e.py` | Required S1 release gate for baseline usable product smoke. |
| Runtime integration wiring | `tests/runtime_integration/test_phase1_real_core_loop.py::TestCoreChatWiring::test_core_chat_actually_invokes_runtime_action_dispatcher_from_turn_end_hook` | Required local same-spine wiring check for core chat -> runtime loop -> dispatcher provenance. |
| Real provider smoke | `tests/test_provider_real_smoke.py` | G-03 Verification only. It is not executed by G-17. |
| Other real-provider or external integration tests | Examples: `tests/test_real_mcp_flight.py`, real memory anchor tests | Not part of the G-17 release gate unless separately authorized by the active backlog. |
| Seam / harness / direct dispatcher tests | Examples: architecture boundary and narrow harness tests | Supporting regression coverage, not the named S1 release gate. |

## G-03 Real Smoke Handoff

Real provider smoke is owned by G-03. G-17 records the handoff only.

- **Location**: `S1_GOAL_GAP.md` G-03 and `tests/test_provider_real_smoke.py`.
- **Existing gated test command**:

```bash
MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1 .venv/bin/python -m pytest tests/test_provider_real_smoke.py -q
```

- **Preconditions**:
  - explicit user authorization for real provider execution;
  - valid non-placeholder real provider configuration available only through
    gitignored local config or opt-in environment as implemented by the real
    smoke test;
  - no checked-in runtime config or secret-bearing file is modified;
  - no `.env` is created as part of G-17.
- **Safety boundaries**:
  - do not read, print, move, copy, or commit secrets;
  - do not modify `config/config.yaml` during G-17;
  - do not run the command above during G-17;
  - G-03 must record real run evidence without exposing key material.

G-03 Verification is expected to prove that a real run produces
`sessions/<id>/events.jsonl` with a real `provider_type`, then compare the event
spine against the fake/local baseline. G-17's acceptance baseline is complete
when the fake/local release gate is specified and passing, and this G-03 handoff
is documented.

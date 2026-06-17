# S2 Reference Task Acceptance

This document defines the S2-G07 acceptance set for the chosen reference task:
Repo-governed improvement task.

## Targeted Gate

Run the deterministic local gate:

```bash
.venv/bin/python -m pytest tests/test_s2_reference_task_acceptance.py -q
```

Expected default result:

- fake/local reference-task E2E passes;
- real-provider smoke is skipped unless explicitly opted in;
- no `.env` or `config/config.yaml` mutation is required.

## Covered Path

The fake/local E2E covers:

- task receipt and plan confirmation through the S2 orchestration skeleton;
- governed tool log summaries and safe evidence hooks;
- task context packaging and provider-callable validation;
- human-visible progress review;
- checkpoint save, load, resume, step advance, and done projection;
- S2 acceptance gate classification for the targeted runtime check.

## Real Provider Opt-In

The real-provider smoke is key-safe and opt-in:

```bash
MY_FIRST_AGENT_RUN_S2_REAL_PROVIDER_SMOKE=1 \
.venv/bin/python -m pytest \
  tests/test_s2_reference_task_acceptance.py::test_s2_reference_task_real_provider_key_safe_context_smoke -q
```

It requires provider environment variables already used by the existing real
smoke path and does not print key values. The default local verification does
not run a real provider call.

## Non-Goals

- Does not make full pytest or ruff part of the S2 release gate.
- Does not activate Skill/MCP/SubAgent/Scheduler.
- Default local verification does not read provider key values.
- Real-provider opt-in must not print, move, copy, or commit secrets.
- Does not modify `config/config.yaml` or create `.env`.

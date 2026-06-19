# S2 Quality Gate Strategy

S2 does not require project-wide `ruff check .` to be green as a product release
goal. TD-007 remains the tracked full-lint debt.

## Release Gate

The S2 release signal is the targeted S2 acceptance gate:

- S2 reference-task acceptance;
- S2 task/context/tool/progress/evidence tests for changed areas;
- focused ruff checks for new or modified Python files.

Full pytest and full ruff are health/debt signals unless classified as targeted
S2 runtime regressions.

## Ruff Policy

- New Python files must pass focused `ruff check`.
- Modified Python files must pass focused `ruff check`.
- Do not broaden a focused S2 gap into a project-wide ruff cleanup.
- Do not mix TD-007 lint debt with TD-006 documentation-governance guard debt.
- Batched full-ruff cleanup is allowed only as a separate S2/Sn lint pass.

## Current TD-007 Boundary

TD-007 remains open until `.venv/bin/ruff check .` exits 0. The current S2 gap
loop may continue while TD-007 is open if targeted S2 acceptance and focused
ruff checks pass.

## Verification Pattern

For each focused code gap:

```bash
.venv/bin/ruff check <changed-python-files>
git diff --check
```

For S2 acceptance classification:

```bash
.venv/bin/python -m pytest tests/test_s2_acceptance_gate.py -q
```

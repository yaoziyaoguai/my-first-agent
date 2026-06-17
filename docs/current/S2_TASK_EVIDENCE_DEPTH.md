# S2 Task Evidence Depth

S2-G11 defines task-level evidence depth for the Repo-governed improvement task.

## Decision

S2 evidence must support human replay of the task at the level of:

- task lifecycle and progress;
- context provider-callable status;
- governed tool attempt/execute/block/fail counts;
- human progress review availability;
- known debt references that limit full-fidelity replay.

S2 does **not** require byte-for-byte model request/response persistence.
TD-001 remains open for future full-fidelity audit needs. TD-004 remains open
for pending-tool preview fidelity.

## Implementation

`agent/task_evidence_report.py` adds a safe report layer over existing S2 task
context, tool contract, and progress review projections.

The report records structured metadata only:

- no raw model request/response body;
- no raw tool result body;
- no secret-like payloads;
- no checkpoint schema change.

## Acceptance

The targeted check is:

```bash
.venv/bin/python -m pytest tests/test_s2_task_evidence_report.py -q
```

Expected result:

- report is replay-ready when task context, tool contract, and progress review
  are all audit-ready;
- TD-001 is explicitly referenced as the full-body persistence limitation;
- TD-004 is referenced when blocked/pending-tool evidence depth is relevant;
- safe evidence envelope contains metadata only.

# S2 Technical Debt Triage

This document resolves S2-G13 by assigning every current technical-debt item to
an S2/S3/Sn lane. It does not close debt items.

## Triage Matrix

| Debt | S2 lane | Status after S2 gap loop | Next trigger |
|---|---|---|---|
| TD-001 full model request/response body persistence | S2 surfaced, not closed | Remains open; S2-G11 records structured task-level evidence and explicitly references TD-001 | Full-fidelity audit/compliance requirement |
| TD-002 legacy provider client facade in planning/compress | S3/Sn cleanup | Remains open; not required for S2 governed task path | Planner/compress/provider adapter refactor |
| TD-003 unreachable secondary context compression path | S2/Sn cleanup candidate | Remains open; confirmed unreachable, deletion deferred | L2 context cleanup pass touching `agent/context.py` |
| TD-004 pending-tool output preview fidelity | S2 surfaced, not closed | Remains open; S2-G11 references TD-004 when blocked/pending-tool depth matters | Event-log fidelity/debugging pass |
| TD-006 stale docs/governance/architecture guards | S2 cleanup candidate, not product gate | Remains open; S2-G10 classifies as doc-governance debt | Guard cleanup against current docs/contracts |
| TD-007 project-wide ruff red | S2/Sn lint pass, not product gate | Remains open; S2-G12 requires focused ruff for new/modified Python files | Dedicated full-ruff cleanup pass |

## Deferred Architecture Items

- Durable task ledger: S3+.
- Full Skill/MCP/SubAgent/Scheduler ecosystem: S3+.
- Multiple simultaneously active L5 capabilities: S3+.
- Broad provider/planner facade cleanup: S3/Sn unless a focused S2 task touches
  the area.

## S2 Closure Rule

S2 can proceed with the above debt open because targeted S2 acceptance is now
separated from doc-governance and quality-debt health signals. Future agents
must not treat open TD-001/002/003/004/006/007 as silently resolved.

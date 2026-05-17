"""Parent-owned SubAgent runtime state helpers."""

from __future__ import annotations

from agent.subagent_system.result import SubAgentRun


def transition_run(run: SubAgentRun, state: str, **updates: object) -> SubAgentRun:
    """Create a new immutable run state.

    Runtime owns state transitions; executor only returns results.
    """

    data = {
        "delegation_id": run.delegation_id,
        "state": state,
        "request": run.request,
        "descriptor": run.descriptor,
        "context_package": run.context_package,
        "result": run.result,
        "adjudication": run.adjudication,
        "revision_count": run.revision_count,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }
    data.update(updates)
    return SubAgentRun(**data)


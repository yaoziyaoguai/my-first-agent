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
        "revision_history": run.revision_history,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }
    data.update(updates)
    return SubAgentRun(**data)


def is_l2_gated(subagent_policy: object | None = None) -> bool:
    """Check if L2 is behind policy gate.

    L2 requires SubAgentPolicy.real_llm_tool_requesting_allowed=True.
    """
    if subagent_policy is None:
        return True  # no policy = safe default (gated)
    return not getattr(subagent_policy, "real_llm_tool_requesting_allowed", False)


def l2_available(subagent_policy: object | None = None) -> bool:
    """Check if L2 native loop is available for use."""
    return not is_l2_gated(subagent_policy)


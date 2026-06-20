"""SubAgent CLI/TUI presentation helpers.

Presentation 层只格式化对象，不导入 executor/runtime/boundary 模块，也不改变
delegation state。调用方负责提供已经产生的 descriptor/result/audit。
"""

from __future__ import annotations


def format_available_subagents(descriptors: tuple[object, ...]) -> str:
    if not descriptors:
        return "No available SubAgents."
    lines = [f"Available SubAgents ({len(descriptors)}):"]
    for descriptor in descriptors:
        modes = ", ".join(getattr(descriptor, "supported_modes", ()))
        lines.append(
            f"- {descriptor.name} [{descriptor.role}]: "
            f"{descriptor.description} modes={modes}"
        )
    return "\n".join(lines)


def format_delegation_status(state: str, execution_mode: str, reason: str) -> str:
    return f"SubAgent delegation: state={state} mode={execution_mode} reason={reason}"


def format_delegation_result(status: str, stop_reason: str, summary: str) -> str:
    return f"SubAgent result: status={status} stop_reason={stop_reason}\n{summary}"


def format_subagent_audit(audit: object) -> str:
    tools = ",".join(getattr(audit, "tools_requested", ())) or "-"
    return (
        f"SubAgent audit: name={audit.subagent_name} "
        f"delegation_id={audit.delegation_id} "
        f"status={audit.status} stop_reason={audit.stop_reason} "
        f"iterations={audit.iterations_used}/{audit.max_iterations} "
        f"tools_requested={tools}"
    )


def format_trace_events(trace_events: tuple[object, ...]) -> str:
    if not trace_events:
        return "SubAgent trace: -"
    lines = ["SubAgent trace:"]
    for event in trace_events:
        lines.append(f"- {event.event_type} delegation={event.delegation_id}")
    return "\n".join(lines)


def format_adjudication(adjudication: object) -> str:
    return f"SubAgent adjudication: action={adjudication.action} reason={adjudication.reason}"


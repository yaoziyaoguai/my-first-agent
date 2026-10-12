"""从 durable tool facts 推导尚未确认清理的任务资源。

该 leaf 同时供 completion 与 compaction 使用：前者阻止误报完成，后者保护
仍承担资源所有权的 open/start fact 不被摘要删除。它只解释 Kernel 已铸造
的 closed receipt 形状，不调用工具或执行清理。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from agent.runtime.contracts import ConversationFact, FactKind


@dataclass(frozen=True, slots=True)
class ActiveTaskResources:
    browser_sessions: frozenset[str]
    managed_processes: frozenset[str]
    owner_fact_ids: frozenset[str]

    def require_closed(self) -> None:
        pending = []
        if self.browser_sessions:
            pending.append("browser_close")
        if self.managed_processes:
            pending.append("managed_web_stop")
        if pending:
            raise ValueError(
                "task resources are still active; confirm cleanup with "
                + ", ".join(pending)
            )


def active_task_resources(facts: tuple[ConversationFact, ...]) -> ActiveTaskResources:
    browser_sessions: dict[str, str] = {}
    managed_processes: dict[str, str] = {}
    for fact in facts:
        if fact.kind is not FactKind.TOOL_RESULT:
            continue
        if (
            fact.content.get("executed") is not True
            or fact.content.get("is_error") is not False
        ):
            continue
        metadata = fact.content.get("metadata")
        if not isinstance(metadata, dict):
            continue
        browser_kind = metadata.get("browser_result_kind")
        if browser_kind in {"browser_open", "browser_close"}:
            session_ref = metadata.get("session_ref")
            if not isinstance(session_ref, str) or not session_ref:
                raise ValueError("browser resource receipt is malformed")
            if browser_kind == "browser_open":
                browser_sessions[session_ref] = fact.fact_id
            elif metadata.get("cleanup_outcome") == "cleaned":
                browser_sessions.pop(session_ref, None)
        tool_name = metadata.get("tool_name")
        if tool_name not in {"managed_web_start", "managed_web_stop"}:
            continue
        try:
            payload = json.loads(str(fact.content.get("text", "")))
        except json.JSONDecodeError as error:
            raise ValueError("managed resource receipt is malformed") from error
        resource_ref = payload.get("resource_ref") if isinstance(payload, dict) else None
        if not isinstance(resource_ref, str) or not resource_ref:
            raise ValueError("managed resource receipt is malformed")
        if tool_name == "managed_web_start" and payload.get("status") == "ready":
            managed_processes[resource_ref] = fact.fact_id
        elif tool_name == "managed_web_stop" and payload.get("cleanup") == "confirmed":
            managed_processes.pop(resource_ref, None)
    return ActiveTaskResources(
        browser_sessions=frozenset(browser_sessions),
        managed_processes=frozenset(managed_processes),
        owner_fact_ids=frozenset((*browser_sessions.values(), *managed_processes.values())),
    )


__all__ = ["ActiveTaskResources", "active_task_resources"]

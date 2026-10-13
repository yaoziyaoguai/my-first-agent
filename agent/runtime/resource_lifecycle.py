"""从 durable tool facts 推导尚未确认清理的任务资源。

该 leaf 同时供 completion 与 compaction 使用：前者阻止误报完成，后者保护
仍承担资源所有权的 open/start fact 不被摘要删除。它只解释 Kernel 已铸造
的 closed receipt 形状，不调用工具或执行清理。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
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


__all__ = [
    "ActiveTaskResources",
    "active_task_resources",
    "managed_process_receipts",
    "managed_writer_active_at",
]


def managed_process_receipts(
    facts: tuple[ConversationFact, ...],
) -> Iterator[tuple[str, str]]:
    """按 durable 顺序产出 ``(event, resource_ref)``。

    ``event`` 是 ``"started"``（ready start）或 ``"closed"``（cleanup 已确认）。
    ``cleanup`` 非 ``confirmed`` 的 stop 不代表资源已关闭，因此不作为关闭事件
    产出——与 ``active_task_resources`` 共用同一 receipt 形状解释，避免两处各自
    解析 managed 结果而产生分歧。malformed receipt 抛 ``ValueError``。
    """

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
        if tool_name == "managed_web_start":
            if payload.get("status") == "ready":
                yield "started", resource_ref
        elif payload.get("cleanup") == "confirmed":
            yield "closed", resource_ref


def managed_writer_active_at(
    facts: tuple[ConversationFact, ...], index: int
) -> bool:
    """判定 ``facts[index]`` 取得时是否有未确认关闭的 managed writer。

    W1（2026-10-12）：最终 workspace 验证的资格取决于**取得当时**的资源事实，
    而不是最终已经为空的资源集合。只使用该 fact 之前的 durable 前缀，因此
    "服务启动后验证、继续写入、再关闭" 这类时序无法用关闭后的状态倒推当时安全。

    只检查本问题对应的 managed 进程（不改变浏览器观察合同）；关闭由既有
    ``cleanup == "confirmed"`` 语义决定——幂等重复 stop 不产生新的关闭事件，
    因此不会作废关闭后取得的验证。
    """

    active: set[str] = set()
    for event, resource_ref in managed_process_receipts(facts[:index]):
        if event == "started":
            active.add(resource_ref)
        else:
            active.discard(resource_ref)
    return bool(active)

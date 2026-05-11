"""Memory Kernel v1 — explicit retain 最小运行时闭环。

本模块是 Memory contract/policy/store 与 AgentLoop runtime 之间的高内聚桥接层。
它不 import checkpoint、MCP、provider adapter 或 tool_executor。

架构原则（Memory Kernel v1）：
- 行为简单：只处理 explicit retain（"remember that X" / "记住 X"）。
- 架构不简化：所有依赖可注入（policy / store / event logger），未来
  agent_suggested / episodic / procedural / reflection / external provider 均
  可通过注入不同实现演进，不需要重写本模块。

确认流程（Memory Interactive Confirmation v1）：
- 两阶段交互：evaluate_user_text → CONFIRMATION_REQUIRED（缓存 decision）→
  resolve_confirmation(candidate_id, choice, free_text) → STORED/REJECTED。
- 用户确认通过 pending_user_input_request（awaiting_kind="memory_confirmation"）
  桥接到现有 awaiting_user_input 机制。
- Memory confirmation 不使用裸 input()，不使用 auto-accept 路径。

未来扩展预留：
- ``MemoryRecord.memory_type``: semantic/episodic/procedural
- ``MemoryRecord.source_type``: explicit_user_request/agent_suggested/reflection/imported
- ``MemoryRecord.approval_status``: pending/approved/rejected/edited
- 外部 provider adapter 通过注入不同 store/retriever 实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    MemoryConfirmationRequest,
    MemoryConfirmationResult,
    MemoryConfirmationStatus,
    build_memory_confirmation_request,
    resolve_memory_confirmation_choice,
)
from agent.memory_contracts import MemoryDecision, MemoryDecisionType, MemorySnapshot
from agent.memory_operations import (
    build_memory_audit_summary,
    build_memory_operation_intent,
)
from agent.memory_policy import DeterministicMemoryPolicy
from agent.memory_snapshot_generator import (
    MemorySnapshotBuildOptions,
    build_memory_snapshot_from_store,
)
from agent.memory_store import InMemoryMemoryStore, MemoryStoreApplyStatus, MemoryStoreProtocol
from agent.memory_suggestions import DeterministicSuggestionEngine


class MemoryEvaluationAction(StrEnum):
    """MemoryRuntime.evaluate_user_text 的返回值动作词表。"""

    NO_OP = "no_op"
    STORED = "stored"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    CONFIRMATION_REQUIRED = "confirmation_required"


@dataclass(frozen=True, slots=True)
class MemoryEvaluationResult:
    """evaluate_user_text 的无副作用结果。

    这不是 store mutation，也不修改 runtime state。调用方根据 action 决定
    后续行为（例如 confirmation_required 时通知 UI）。
    """

    action: MemoryEvaluationAction
    decision_type: MemoryDecisionType | None = None
    candidate_id: str | None = None
    content_summary: str = ""
    reason: str = ""
    safety_flags: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Event logger type
# ---------------------------------------------------------------------------

MemoryEventLogger = Callable[[str, dict | None], None]


def _noop_event_logger(event_type: str, payload: dict | None = None) -> None:
    """默认空 event logger，不写任何日志。"""
    return


# ---------------------------------------------------------------------------
# MemoryRuntime
# ---------------------------------------------------------------------------


class MemoryRuntime:
    """Memory Kernel v1 运行时协调器。

    职责（高内聚）：
    - 接收 user_text，调用 policy 判断是否需要 memory 操作。
    - 需要确认时，缓存 decision + confirmation request，返回 CONFIRMATION_REQUIRED。
    - 调用方通过 resolve_confirmation 应用用户选择。
    - approved → 写入 store。
    - 生成 MemorySnapshot 供 prompt_builder 消费。
    - 记录 minimal audit events。

    所有依赖均可注入：policy / store / event logger。
    MemoryRuntime 不 import checkpoint、MCP、provider adapter、tool_executor。

    两阶段交互流程（v1）：
    1. evaluate_user_text → CONFIRMATION_REQUIRED（缓存 decision）
    2. resolve_confirmation(candidate_id, choice, free_text) → STORED/REJECTED/...
    """

    def __init__(
        self,
        *,
        policy: DeterministicMemoryPolicy | None = None,
        store: MemoryStoreProtocol | None = None,
        event_logger: MemoryEventLogger | None = None,
        suggestion_engine: DeterministicSuggestionEngine | None = None,
    ):
        """
        参数全部 keyword-only，保证调用方显式声明注入意图。

        默认值：
        - policy: DeterministicMemoryPolicy()
        - store: None（必须由调用方注入，否则 evaluate 只做 policy 不做写入）
        - event_logger: _noop_event_logger
        - suggestion_engine: None（不启用 agent-suggested memory）
        """
        self._policy = policy or DeterministicMemoryPolicy()
        self._store = store
        self._log = event_logger or _noop_event_logger
        self._suggestion_engine = suggestion_engine
        # 两阶段确认缓存：key=candidate_id, value=dict(decision, confirmation_request)
        self._pending_decision: dict[str, Any] | None = None

    # -- 核心入口 ----------------------------------------------------------

    def evaluate_user_text(
        self,
        user_text: str,
        *,
        on_event: Callable | None = None,
    ) -> MemoryEvaluationResult:
        """评估用户输入是否触发 memory 操作。

        这是 MemoryRuntime 对 AgentLoop 的唯一入口：
        1. policy.decide(user_text)
        2. 如果需要确认 → confirmation adapter
        3. approved → operation intent → audit → store
        4. 记录 audit event
        5. 返回 MemoryEvaluationResult

        本方法不修改 runtime state、不调用 checkpoint、不 import core。
        """
        decision = self._policy.decide(user_text)

        # -- NO_OP：普通消息，不做 memory 处理 --------------------------------
        if decision.decision_type is MemoryDecisionType.NO_OP:
            if self._suggestion_engine is not None:
                result = self._try_suggestions(user_text, on_event=on_event)
                if result is not None:
                    return result
            return MemoryEvaluationResult(action=MemoryEvaluationAction.NO_OP)

        # -- CLARIFY：模糊 memory 请求，记录但不操作 --------------------------
        if decision.decision_type is MemoryDecisionType.CLARIFY:
            self._log("memory.candidate_detected", {
                "decision_type": decision.decision_type.value,
                "reason": decision.reason,
            })
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.NO_OP,
                decision_type=decision.decision_type,
                reason=decision.reason,
            )

        # -- REJECT / BLOCKED -----------------------------------------------
        if decision.decision_type is MemoryDecisionType.REJECT:
            candidate = decision.target_candidate
            self._log("memory.blocked", {
                "decision_type": decision.decision_type.value,
                "reason": decision.reason,
                "safety_flags": list(decision.safety_flags),
                "candidate_id": candidate.id if candidate is not None else None,
            })
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.BLOCKED,
                decision_type=decision.decision_type,
                candidate_id=candidate.id if candidate is not None else None,
                reason=decision.reason,
                safety_flags=decision.safety_flags,
            )

        # -- RETAIN / UPDATE / FORGET：需要确认 ------------------------------
        candidate = decision.target_candidate
        candidate_id = candidate.id if candidate is not None else None
        content_summary = candidate.content if candidate is not None else ""

        self._log("memory.candidate_detected", {
            "decision_type": decision.decision_type.value,
            "candidate_id": candidate_id,
            "content_summary": content_summary[:200] if content_summary else "",
        })

        # 构造确认请求
        confirmation_request = build_memory_confirmation_request(decision)

        # 发出确认请求事件（供 UI 层展示）
        if on_event is not None:
            try:
                on_event({
                    "type": "memory_confirmation_requested",
                    "question": confirmation_request.question,
                    "preview": confirmation_request.preview,
                    "decision_type": decision.decision_type.value,
                })
            except Exception:
                pass

        self._log("memory.confirmation_requested", {
            "decision_type": decision.decision_type.value,
            "candidate_id": candidate_id,
        })

        # v1 两阶段交互：缓存 decision + confirmation_request，返回
        # CONFIRMATION_REQUIRED。调用方通过 resolve_confirmation 应用用户选择。
        self._pending_decision = {
            "decision": decision,
            "confirmation_request": confirmation_request,
            "candidate_id": candidate_id,
        }

        return MemoryEvaluationResult(
            action=MemoryEvaluationAction.CONFIRMATION_REQUIRED,
            decision_type=decision.decision_type,
            candidate_id=candidate_id,
            content_summary=content_summary[:200] if content_summary else "",
            reason="等待用户确认",
        )

    # -- Agent-suggested memory -----------------------------------------------

    def _try_suggestions(
        self,
        user_text: str,
        *,
        on_event: Callable | None = None,
    ) -> MemoryEvaluationResult | None:
        """在 policy 返回 NO_OP 后尝试 agent-suggested memory candidate 识别。

        确定性 heuristic 引擎生成候选 → 取第一个 → 包装为 RETAIN decision →
        走现有确认流程。不调 LLM、不写 store、不 import core。
        返回 None 表示没有可确认的候选。
        """
        if self._suggestion_engine is None:
            return None

        candidates = self._suggestion_engine.evaluate(
            user_text,
            existing_store=self._store,
        )

        if not candidates:
            return None

        # 取第一个候选，包装为 RETAIN decision
        candidate = candidates[0]
        decision = MemoryDecisionType.RETAIN

        memory_decision = MemoryDecision(
            decision_type=MemoryDecisionType.RETAIN,
            target_candidate=candidate,
            action="retain",
            requires_user_confirmation=True,
            reason=f"agent 建议记住：{candidate.reason}",
            safety_flags=(),
            provenance=f"candidate:{candidate.id}",
        )

        self._log("memory.agent_suggested_candidate", {
            "candidate_id": candidate.id,
            "content_summary": candidate.content[:200],
            "proposed_type": candidate.proposed_type,
            "confidence": candidate.confidence,
        })

        confirmation_request = build_memory_confirmation_request(memory_decision)

        if on_event is not None:
            try:
                on_event({
                    "type": "memory_confirmation_requested",
                    "question": confirmation_request.question,
                    "preview": confirmation_request.preview,
                    "decision_type": decision.value,
                    "source_type": "agent_suggested",
                })
            except Exception:
                pass

        self._log("memory.confirmation_requested", {
            "decision_type": decision.value,
            "candidate_id": candidate.id,
            "source_type": "agent_suggested",
        })

        self._pending_decision = {
            "decision": memory_decision,
            "confirmation_request": confirmation_request,
            "candidate_id": candidate.id,
        }

        return MemoryEvaluationResult(
            action=MemoryEvaluationAction.CONFIRMATION_REQUIRED,
            decision_type=MemoryDecisionType.RETAIN,
            candidate_id=candidate.id,
            content_summary=candidate.content[:200],
            reason="agent 建议记住这条信息，等待用户确认",
        )

    # -- 第二阶段：应用用户确认结果 ------------------------------------------

    def get_pending_confirmation(
        self, candidate_id: str | None
    ) -> MemoryConfirmationRequest | None:
        """返回待确认的 MemoryConfirmationRequest，供 UI 层构建展示。

        如果 _pending_decision 不存在或 candidate_id 不匹配，返回 None。
        """
        pending = self._pending_decision
        if pending is None:
            return None
        if pending.get("candidate_id") != candidate_id:
            return None
        return pending["confirmation_request"]

    def resolve_confirmation(
        self,
        candidate_id: str | None,
        choice: MemoryConfirmationChoice,
        free_text: str | None = None,
    ) -> MemoryEvaluationResult:
        """应用用户确认结果：生成 confirmation result → 写入 store。

        这是 evaluate_user_text 的第二阶段：
        1. 从 _pending_decision 缓存中取出 decision + confirmation_request
        2. 用 resolve_memory_confirmation_choice 生成 MemoryConfirmationResult
        3. approved → operation intent → store 写入
        4. 清缓存，返回 MemoryEvaluationResult
        """
        pending = self._pending_decision
        if pending is None or pending.get("candidate_id") != candidate_id:
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.REJECTED,
                candidate_id=candidate_id,
                reason="无匹配的待确认 decision（可能已超时或已处理）",
            )

        decision = pending["decision"]
        confirmation_request = pending["confirmation_request"]
        content_summary = (
            decision.target_candidate.content[:200]
            if decision.target_candidate is not None
            else ""
        )

        # 解析确认结果
        try:
            confirmation_result: MemoryConfirmationResult = resolve_memory_confirmation_choice(
                confirmation_request, choice, free_text=free_text
            )
        except ValueError as exc:
            self._pending_decision = None
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.REJECTED,
                candidate_id=candidate_id,
                content_summary=content_summary,
                reason=str(exc),
            )

        # 记录确认结果
        if confirmation_result.status is MemoryConfirmationStatus.APPROVED:
            self._log("memory.confirmation_accepted", {
                "decision_type": decision.decision_type.value,
                "candidate_id": candidate_id,
                "choice": confirmation_result.choice.value,
            })
        elif confirmation_result.status is MemoryConfirmationStatus.REJECTED:
            self._log("memory.confirmation_rejected", {
                "decision_type": decision.decision_type.value,
                "candidate_id": candidate_id,
                "choice": confirmation_result.choice.value,
            })
            self._pending_decision = None
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.REJECTED,
                decision_type=decision.decision_type,
                candidate_id=candidate_id,
                content_summary=content_summary,
                reason="用户拒绝",
            )
        elif confirmation_result.status is MemoryConfirmationStatus.SESSION_ONLY:
            self._log("memory.confirmation_session_only", {
                "decision_type": decision.decision_type.value,
                "candidate_id": candidate_id,
            })
            # SESSION_ONLY：写入 store 但标记为 session scope
            if self._store is not None:
                intent = build_memory_operation_intent(confirmation_result)
                audit = build_memory_audit_summary(intent)
                self._store.apply_operation_intent(intent, audit)
            self._pending_decision = None
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.STORED,
                decision_type=decision.decision_type,
                candidate_id=candidate_id,
                content_summary=content_summary,
                reason="仅本次会话使用，已写入",
            )

        # -- approved：operation intent → audit → store --------------------
        self._pending_decision = None

        if self._store is None:
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.STORED,
                decision_type=decision.decision_type,
                candidate_id=candidate_id,
                content_summary=content_summary,
                reason="store 未注入，确认结果未持久化",
            )

        intent = build_memory_operation_intent(confirmation_result)
        audit = build_memory_audit_summary(intent)

        result = self._store.apply_operation_intent(intent, audit)

        if result.status is MemoryStoreApplyStatus.APPLIED:
            self._log("memory.stored", {
                "operation_type": result.operation_type.value,
                "record_id": result.record.id if result.record is not None else None,
                "audit_id": result.audit_id,
            })
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.STORED,
                decision_type=decision.decision_type,
                candidate_id=candidate_id,
                content_summary=content_summary,
                reason="已写入 in-memory store",
            )

        return MemoryEvaluationResult(
            action=MemoryEvaluationAction.STORED,
            decision_type=decision.decision_type,
            candidate_id=candidate_id,
            content_summary=content_summary,
            reason=result.message,
        )

    # -- snapshot generation -----------------------------------------------

    def snapshot_for_prompt(
        self,
        *,
        selection_reason: str = "Memory Kernel v1 recall",
        max_items: int = 5,
        rendered_char_budget: int = 500,
    ) -> MemorySnapshot:
        """从 store 生成 MemorySnapshot 供 prompt_builder 消费。

        如果 store 未注入或为空，返回空的 MemorySnapshot（不影响 prompt）。
        """
        if self._store is None:
            return MemorySnapshot.empty()

        records = self._store.list_records()
        if not records:
            return MemorySnapshot.empty()

        snapshot = build_memory_snapshot_from_store(
            self._store,
            MemorySnapshotBuildOptions(
                selection_reason=selection_reason,
                max_items=max_items,
                include_sensitive=False,
                rendered_char_budget=rendered_char_budget,
            ),
        )

        if snapshot.items:
            self._log("memory.injected", {
                "item_count": len(snapshot.items),
                "omitted_count": snapshot.omitted_count,
                "selection_reason": selection_reason,
            })

        return snapshot


# ---------------------------------------------------------------------------
# 便捷工厂：创建默认 MemoryRuntime
# ---------------------------------------------------------------------------


def create_memory_runtime(
    *,
    store: MemoryStoreProtocol | None = None,
    event_logger: MemoryEventLogger | None = None,
) -> MemoryRuntime:
    """创建 MemoryRuntime 的便捷工厂，所有参数可选注入。

    默认使用 DeterministicMemoryPolicy + InMemoryMemoryStore。
    确认流程使用两阶段交互（evaluate → CONFIRMATION_REQUIRED → resolve_confirmation）。
    若不想写入 store（如只做 policy 评估），显式传 store=None。

    Store 选择策略：
    - 显式传 store 参数 → 使用传入的 store
    - MEMORY_STORE_BACKEND=filesystem → FilesystemMemoryStore
      · 落盘路径由 MEMORY_STORE_ROOT / MEMORY_ROOT 控制，默认 ~/.my-first-agent/memory/
    - 默认 → InMemoryMemoryStore
    - 无效 MEMORY_STORE_BACKEND 值 → 抛出 ValueError
    - FilesystemMemoryStore 初始化失败（如权限不足）→ 不静默降级，抛出 OSError
    """
    import os as _os

    if store is not None:
        resolved_store = store
    else:
        backend = _os.getenv("MEMORY_STORE_BACKEND", "memory").strip()
        if backend in ("memory", "in_memory", "inmemory"):
            resolved_store = InMemoryMemoryStore()
        elif backend in ("filesystem", "memory_fs", "fs"):
            from agent.memory_fs_store import FilesystemMemoryStore

            # FilesystemMemoryStore.__init__ 自己读 MEMORY_STORE_ROOT / MEMORY_ROOT
            resolved_store = FilesystemMemoryStore()
        else:
            raise ValueError(
                f"不支持的 MEMORY_STORE_BACKEND 值：{backend!r}。"
                f"支持的值：memory, filesystem"
            )

    return MemoryRuntime(
        policy=DeterministicMemoryPolicy(),
        store=resolved_store,
        event_logger=event_logger or _noop_event_logger,
    )

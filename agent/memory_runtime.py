"""Memory Kernel v1 — explicit retain 最小运行时闭环。

本模块是 Memory contract/policy/store 与 AgentLoop runtime 之间的高内聚桥接层。
它不 import checkpoint、MCP、provider adapter 或 tool_executor。

架构原则（Memory Kernel v1）：
- 行为简单：只处理 explicit retain（"remember that X" / "记住 X"）。
- 架构不简化：所有依赖可注入（policy / store / confirmation adapter / event logger），
  未来 agent_suggested / episodic / procedural / reflection / external provider 均
  可通过注入不同实现演进，不需要重写本模块。

确认流程（v1 最小方案）：
- ``MemoryConfirmationAdapter`` Protocol 定义确认接缝。
- ``FakeMemoryConfirmationAdapter``：测试用，确定性返回 accept/reject。
- ``DeferredMemoryConfirmationAdapter``：生产用，v1 临时策略为 auto-accept
  explicit retain（因为用户意图已通过输入文本明确表达）。它会 emit RuntimeEvent
  供 UI 层展示确认问题，但当前不阻塞等待用户回复。真实交互式确认 UI 留给后续
  stage。
- 测试中 fake adapter accept/reject → 完整闭环可测。
- 生产中 deferred adapter → auto-accept → store 写入 → snapshot → prompt（v1
  deterministic kernel 闭环；真实 Ask User / request_user_input 确认后续接入）。

未来扩展预留：
- ``MemoryRecord.memory_type``: semantic/episodic/procedural
- ``MemoryRecord.source_type``: explicit_user_request/agent_suggested/reflection/imported
- ``MemoryRecord.approval_status``: pending/approved/rejected/edited
- 外部 provider adapter 通过注入不同 store/retriever 实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Protocol

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    MemoryConfirmationRequest,
    MemoryConfirmationResult,
    MemoryConfirmationStatus,
    build_memory_confirmation_request,
    resolve_memory_confirmation_choice,
)
from agent.memory_contracts import MemoryDecisionType, MemorySnapshot
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
# Confirmation adapter seam
# ---------------------------------------------------------------------------


class MemoryConfirmationAdapter(Protocol):
    """Memory confirmation 的注入接缝。

    本协议只定义"如何获取用户对 memory decision 的确认结果"。
    它不负责 policy、不写 store、不调用 runtime/checkpoint。

    v1 实现：
    - FakeMemoryConfirmationAdapter：测试用，返回确定性结果。
    - DeferredMemoryConfirmationAdapter：生产用，emit RuntimeEvent + 返回
      requires_user_confirmation（确认 UI 留给后续 stage）。
    """

    def request_confirmation(
        self,
        request: MemoryConfirmationRequest,
    ) -> MemoryConfirmationResult:
        """向用户请求确认一个 memory decision，返回无副作用结果。"""
        ...


class FakeMemoryConfirmationAdapter:
    """确定性 fake adapter，测试用。

    不读取 stdin、不调用 TUI、不阻塞。构造时指定 preset_choice。
    """

    def __init__(self, preset_choice: MemoryConfirmationChoice = MemoryConfirmationChoice.ACCEPT):
        self._preset_choice = preset_choice

    def request_confirmation(
        self,
        request: MemoryConfirmationRequest,
    ) -> MemoryConfirmationResult:
        return resolve_memory_confirmation_choice(request, self._preset_choice)


class DeferredMemoryConfirmationAdapter:
    """生产用 confirmation adapter：emit RuntimeEvent + 返回 requires_user_confirmation。

    v1 阶段不阻塞等用户回复——只把确认问题通过 on_event 发给 UI 层，
    并返回 APPROVED 状态以允许 store 写入（因为 explicit retain 的用户意图
    已通过输入文本明确表达）。后续 stage 可替换为真实交互式确认。
    """

    def __init__(self, on_event: Callable | None = None):
        self._on_event = on_event

    def request_confirmation(
        self,
        request: MemoryConfirmationRequest,
    ) -> MemoryConfirmationResult:
        # 发出确认问题，让 UI 层有机会展示
        if self._on_event is not None:
            try:
                self._on_event({
                    "type": "memory_confirmation_requested",
                    "question": request.question,
                    "preview": request.preview,
                    "decision_type": request.decision.decision_type.value,
                })
            except Exception:
                pass

        # v1：explicit retain 的用户意图已通过输入文本明确表达，
        # 直接返回 approved。后续 stage 可替换为真实交互式确认。
        return resolve_memory_confirmation_choice(request, MemoryConfirmationChoice.ACCEPT)


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
    - 需要确认时，通过注入的 confirmation adapter 获取结果。
    - approved → 写入 store。
    - 生成 MemorySnapshot 供 prompt_builder 消费。
    - 记录 minimal audit events。

    所有依赖均可注入：policy / store / confirmation adapter / event logger。
    MemoryRuntime 不 import checkpoint、MCP、provider adapter、tool_executor。
    """

    def __init__(
        self,
        *,
        policy: DeterministicMemoryPolicy | None = None,
        store: MemoryStoreProtocol | None = None,
        confirmation_adapter: MemoryConfirmationAdapter | None = None,
        event_logger: MemoryEventLogger | None = None,
    ):
        """
        参数全部 keyword-only，保证调用方显式声明注入意图。

        默认值：
        - policy: DeterministicMemoryPolicy()
        - store: None（必须由调用方注入，否则 evaluate 只做 policy 不做写入）
        - confirmation_adapter: DeferredMemoryConfirmationAdapter()
        - event_logger: _noop_event_logger
        """
        self._policy = policy or DeterministicMemoryPolicy()
        self._store = store
        self._confirmation = confirmation_adapter or DeferredMemoryConfirmationAdapter()
        self._log = event_logger or _noop_event_logger

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

        # 通过注入的 adapter 获取确认结果
        confirmation_result = self._confirmation.request_confirmation(confirmation_request)

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
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.REJECTED,
                decision_type=decision.decision_type,
                candidate_id=candidate_id,
                content_summary=content_summary[:200] if content_summary else "",
                reason="用户拒绝",
            )

        # -- approved：operation intent → audit → store --------------------
        if self._store is None:
            return MemoryEvaluationResult(
                action=MemoryEvaluationAction.CONFIRMATION_REQUIRED,
                decision_type=decision.decision_type,
                candidate_id=candidate_id,
                content_summary=content_summary[:200] if content_summary else "",
                reason="store 未注入，无法写入",
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
                content_summary=content_summary[:200] if content_summary else "",
                reason="已写入 in-memory store",
            )

        return MemoryEvaluationResult(
            action=MemoryEvaluationAction.CONFIRMATION_REQUIRED,
            decision_type=decision.decision_type,
            candidate_id=candidate_id,
            content_summary=content_summary[:200] if content_summary else "",
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
    confirmation_adapter: MemoryConfirmationAdapter | None = None,
    event_logger: MemoryEventLogger | None = None,
) -> MemoryRuntime:
    """创建 MemoryRuntime 的便捷工厂，所有参数可选注入。

    默认使用 DeterministicMemoryPolicy + InMemoryMemoryStore +
    DeferredMemoryConfirmationAdapter。
    测试中可注入 FakeMemoryConfirmationAdapter。
    若不想写入 store（如只做 policy 评估），显式传 store=None。
    """
    return MemoryRuntime(
        policy=DeterministicMemoryPolicy(),
        store=store if store is not None else InMemoryMemoryStore(),
        confirmation_adapter=confirmation_adapter or DeferredMemoryConfirmationAdapter(),
        event_logger=event_logger or _noop_event_logger,
    )

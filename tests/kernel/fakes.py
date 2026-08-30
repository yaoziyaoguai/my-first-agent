from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace

from agent.runtime.contracts import (
    BlockedClaim,
    CompletionClaim,
    ContextPack,
    ConversationFact,
    ConversationState,
    FactKind,
    GoalDelta,
    GoalDeltaProposal,
    GoalDraftProposal,
    GoalFrame,
    GoalProgress,
    GoalStatus,
    LoadedSnapshot,
    ModelResponse,
    ProposedCriterion,
    RuntimeEvent,
)
from agent.subagent.contracts import ProviderDeadlineCapability

RUNTIME_GOAL_ID = "__runtime_goal__"
ScriptedResponse = ModelResponse | Exception | Callable[[ContextPack], ModelResponse]


def _trusted_goal_projection(context: ContextPack) -> dict | None:
    return next(
        (
            block
            for message in context.messages
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "trusted_goal"
        ),
        None,
    )


def runtime_goal_identity(context: ContextPack) -> tuple[str, int] | None:
    """读取 Runtime 投影给 Provider 的 trusted Goal 身份。"""

    trusted = _trusted_goal_projection(context)
    if trusted is None:
        return None
    goal_id = trusted.get("goal_id")
    goal_revision = trusted.get("goal_revision")
    if not isinstance(goal_id, str) or not isinstance(goal_revision, int):
        return None
    return goal_id, goal_revision


def bind_runtime_goal(response: ModelResponse, context: ContextPack) -> ModelResponse:
    """显式占位符让 scripted test 引用 Runtime 铸造的 Goal 身份。"""

    trusted = _trusted_goal_projection(context)
    identity = runtime_goal_identity(context)
    control = response.control
    if identity is None or control is None:
        return response
    goal_id, goal_revision = identity
    if (
        isinstance(control, (BlockedClaim, CompletionClaim, GoalProgress))
        and control.goal_id == RUNTIME_GOAL_ID
    ):
        evidence_refs = (
            trusted.get("expected_completion_evidence_refs")
            if isinstance(control, CompletionClaim) and trusted is not None
            else None
        )
        return replace(
            response,
            control=replace(
                control,
                goal_id=goal_id,
                goal_revision=goal_revision,
                **(
                    {"criterion_evidence_refs": tuple(evidence_refs)}
                    if isinstance(evidence_refs, list)
                    and all(isinstance(item, str) for item in evidence_refs)
                    else {}
                ),
            ),
        )
    if (
        isinstance(control, GoalDeltaProposal)
        and control.delta.goal_id == RUNTIME_GOAL_ID
    ):
        return replace(
            response,
            control=replace(
                control,
                delta=replace(
                    control.delta,
                    goal_id=goal_id,
                    expected_revision=goal_revision,
                ),
            ),
        )
    return response


def goal_draft_from_frame(
    correlation_id: str,
    goal: GoalFrame,
) -> GoalDraftProposal:
    """把旧测试 fixture 的语义字段投影为真实模型唯一允许的 Goal 草案。"""

    return GoalDraftProposal(
        correlation_id=correlation_id,
        user_outcome=goal.user_outcome,
        beneficiary=goal.beneficiary,
        targets=goal.targets,
        scope=goal.scope,
        non_goals=goal.non_goals,
        assumptions=goal.assumptions,
        proposed_criteria=goal.proposed_criteria,
        next_step=goal.next_step or "continue the requested task",
        requires_public_web=any(
            item.oracle_kind is not None
            and item.oracle_kind.value == "web_source_receipt"
            for item in goal.proposed_criteria
        ),
        requires_local_process=any(
            item.oracle_kind is not None
            and item.oracle_kind.value == "tool_receipt"
            for item in goal.proposed_criteria
        ),
    )


def goal_noop_response(
    correlation_id: str,
) -> Callable[[ContextPack], ModelResponse]:
    """确认当前用户补充不改变 trusted Goal，供已有 Goal 的测试场景使用。"""

    def response(context: ContextPack) -> ModelResponse:
        trusted = _trusted_goal_projection(context)
        if trusted is None:
            raise AssertionError("trusted_goal is required for a no-op goal delta")
        targets = trusted.get("targets")
        if not isinstance(targets, list) or not all(
            isinstance(item, str) and item for item in targets
        ):
            raise AssertionError("trusted_goal targets are required for a no-op goal delta")
        return ModelResponse(
            (),
            control=GoalDeltaProposal(
                correlation_id=correlation_id,
                delta=GoalDelta(
                    goal_id=RUNTIME_GOAL_ID,
                    expected_revision=1,
                    reason="the user supplement does not change the trusted goal",
                    updates={"targets": targets},
                ),
            ),
        )

    return response


def conversation_with_active_goal(conversation_id: str = "conversation-1") -> ConversationState:
    """U3 之后 effectful 工具必须在 durable Goal 存在后才能到达 prepare。

    本函数是测试 checkpoint seed,不是产线 bypass:它模拟"上一回合(action 1)
    已经从权威 user fact 建立 Goal 并收尾"之后的持久状态,让下游 effect
    ordering/approval/tool outcome 测试从合法前提起步。调用方应从返回状态派生
    action_seq/expected_revision/run_id,而不是硬编码首回合的值。
    """
    source_fact = ConversationFact(
        fact_id="action:1:user",
        kind=FactKind.USER_MESSAGE,
        content={"text": "please persist the fixture note"},
    )
    goal = GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=(source_fact.fact_id,),
        workspace_identity_digest="workspace-digest-1",
        user_outcome="Persist the requested fixture note",
        beneficiary="user",
        targets=("workspace",),
        scope=("workspace/fixtures",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-1", "fixture note exists"),),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-02T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )
    # revision=5 对应上一回合 accept/claim/goal CAS/complete+finalize 的递增;
    # replay_floor=2 表示 action 1 的重放窗口已过期,seed 不携带 replay 记录。
    return ConversationState(
        conversation_id=conversation_id,
        revision=5,
        next_action_seq=2,
        replay_floor=2,
        facts=(source_fact,),
        goal=goal,
    )


class ScriptedProvider:
    """Test provider with structural deadline contract for SubAgent compatibility."""

    deadline_contract = ProviderDeadlineCapability(
        hard_deadline_seconds=30.0,
        receipt_type="synchronous",
    )

    def __init__(self, *responses: ScriptedResponse) -> None:
        self._responses = deque(responses)
        self.calls: list[ContextPack] = []

    def generate(self, context: ContextPack) -> ModelResponse:
        self.calls.append(context)
        if not self._responses:
            raise AssertionError("provider script exhausted")
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(context)
        return bind_runtime_goal(response, context)


@dataclass
class FakeLease:
    store: InMemoryCheckpointStore
    released: bool = False

    def release(self) -> None:
        if not self.released:
            self.released = True
            self.store.locked = False


class InMemoryCheckpointStore:
    def __init__(self, state: ConversationState) -> None:
        self.state = state
        self.token_number = 0
        self.locked = False
        self.save_count = 0
        self.fail_on_save: int | None = None
        self.capacity_available = True

    def load(self) -> LoadedSnapshot:
        return LoadedSnapshot(self.state, f"token-{self.token_number}")

    def try_acquire(self, conversation_id: str) -> FakeLease | None:
        if conversation_id != self.state.conversation_id or self.locked:
            return None
        self.locked = True
        return FakeLease(self)

    def compare_and_swap(
        self,
        snapshot: LoadedSnapshot,
        new_state: ConversationState,
    ) -> LoadedSnapshot:
        self.save_count += 1
        if self.fail_on_save == self.save_count:
            raise RuntimeError("injected checkpoint failure")
        if snapshot.token != f"token-{self.token_number}":
            raise RuntimeError("snapshot conflict")
        if snapshot.state.revision != self.state.revision:
            raise RuntimeError("revision conflict")
        self.state = new_state
        self.token_number += 1
        return self.load()

    def ensure_capacity(self, snapshot: LoadedSnapshot, *, reserve_bytes: int) -> bool:
        del snapshot, reserve_bytes
        return self.capacity_available


class RecordingCheckpointStore(InMemoryCheckpointStore):
    def __init__(self, state: ConversationState) -> None:
        super().__init__(state)
        self._saved_timeline: list[str] = []
        self.saved_phases = self._saved_timeline
        self.saved_fact_kinds = self._saved_timeline

    def compare_and_swap(self, snapshot, new_state):
        prior_fact_count = len(self.state.facts)
        result = super().compare_and_swap(snapshot, new_state)
        active = new_state.active_run
        if active is not None:
            self._saved_timeline.append(active.phase.value)
        self._saved_timeline.extend(
            fact.kind.value for fact in new_state.facts[prior_fact_count:]
        )
        return result


class CollectingSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[RuntimeEvent] = []
        self.fail = fail

    def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event)
        if self.fail:
            raise RuntimeError("injected sink failure")


class RecordingEventSink(CollectingSink):
    pass

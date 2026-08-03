from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from agent.runtime.contracts import (
    ContextPack,
    ConversationFact,
    ConversationState,
    FactKind,
    GoalFrame,
    GoalStatus,
    LoadedSnapshot,
    ModelResponse,
    ProposedCriterion,
    RuntimeEvent,
)
from agent.subagent.contracts import ProviderDeadlineCapability


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

    def __init__(self, *responses: ModelResponse | Exception) -> None:
        self._responses = deque(responses)
        self.calls: list[ContextPack] = []

    def generate(self, context: ContextPack) -> ModelResponse:
        self.calls.append(context)
        if not self._responses:
            raise AssertionError("provider script exhausted")
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


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


class CollectingSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[RuntimeEvent] = []
        self.fail = fail

    def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event)
        if self.fail:
            raise RuntimeError("injected sink failure")

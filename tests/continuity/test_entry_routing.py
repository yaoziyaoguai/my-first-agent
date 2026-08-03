"""U3A 入口路由 Red 契约:单一 SubmitMessage -> AgentRuntime.run_turn 路径。

契约(012 U3):
- 直接回答不得创建 Goal。
- 方向边界歧义只返回一条 durable 澄清问题,durable 状态为 CLARIFYING,
  且零 ToolRuntime.prepare/invoke 效果。
- 显式任务必须先以 CAS 持久化 Goal,再重建模型上下文,再产生任务工具效果
  (goal_cas < context_rebuild < tool_prepare)。
- 无 durable Goal 的 effectful 任务工具调用必须在 ToolRuntime.prepare 之前
  fail closed。

这些测试通过记录型 spy(checkpoint/context/tool)断言外部可观察的顺序与效果,
不断言私有实现细节。
"""

from __future__ import annotations

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    ClarificationRequest,
    ConversationState,
    FactKind,
    GoalFrame,
    GoalProgress,
    GoalProposal,
    GoalStatus,
    InteractionState,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    ProposedCriterion,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider

_CLARIFYING_QUESTION = "Which direction should the migration take: keep v1 or move to v2?"


class RecordingCheckpointStore(InMemoryCheckpointStore):
    """在 durable CAS 首次写入 Goal 时记录 goal_cas 时间线事件。"""

    def __init__(self, state: ConversationState, timeline: list[tuple[str, object]]) -> None:
        super().__init__(state)
        self._timeline = timeline

    def compare_and_swap(self, snapshot, new_state):
        had_goal = self.state.goal is not None
        result = super().compare_and_swap(snapshot, new_state)
        if not had_goal and new_state.goal is not None:
            self._timeline.append(("goal_cas", new_state.goal.goal_id))
        return result


class RecordingContextManager:
    """透传 KernelContextManager,记录每次上下文构建时 durable Goal 是否已存在。"""

    def __init__(self, inner, store, timeline: list[tuple[str, object]]) -> None:
        self._inner = inner
        self._store = store
        self._timeline = timeline

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def build(self, state, action, tools):
        self._timeline.append(("context_build", self._store.state.goal is not None))
        return self._inner.build(state, action, tools)


class RecordingToolRuntime:
    """透传 KernelToolRuntime,记录 prepare/invoke 效果时间线。"""

    def __init__(self, inner, timeline: list[tuple[str, object]]) -> None:
        self._inner = inner
        self._timeline = timeline

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def prepare(self, call, context, approval=None):
        self._timeline.append(("tool_prepare", call.name))
        return self._inner.prepare(call, context, approval)

    def invoke(self, intent):
        self._timeline.append(("tool_invoke", intent.tool_name))
        return self._inner.invoke(intent)


def _task_tool(executions: list[str]) -> RegisteredTool:
    spec = ToolSpec(
        name="write_note",
        version="1",
        description="Write a note into the workspace",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        risk=ToolRisk.MEDIUM,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={"fixture": True},
        output_limit_chars=100,
    )

    def run(intent) -> str:
        executions.append(intent.arguments["path"])
        return "written:" + intent.arguments["path"]

    return RegisteredTool(spec, run)


def _goal_frame() -> GoalFrame:
    return GoalFrame(
        goal_id="goal-1",
        revision=1,
        # 必须引用 _apply_action 为 SubmitMessage(action_seq=1) 实际创建的权威 fact。
        created_from_fact_ids=("action:1:user",),
        workspace_identity_digest="workspace-digest-1",
        user_outcome="Persist the requested note",
        beneficiary="user",
        targets=("workspace",),
        scope=("workspace/notes",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-1", "note exists"),),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-02T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )


def _submit(state: ConversationState, message: str) -> SubmitMessage:
    # run_id 由 next_action_seq 派生:首回合仍为 run-1,多回合场景自然得到 run-2。
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=f"run-{state.next_action_seq}",
        message=message,
    )


def _runtime(provider, store, timeline, tools=()) -> AgentRuntime:
    return AgentRuntime(
        provider=provider,
        context_manager=RecordingContextManager(
            KernelContextManager(
                system_policy="Be concise.",
                limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
                workspace_scope_digest="workspace-digest-1",
                authority_snapshot="authority-1",
            ),
            store,
            timeline,
        ),
        tool_runtime=RecordingToolRuntime(KernelToolRuntime(tools), timeline),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )


def test_direct_answer_does_not_create_goal() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("Paris is the capital."),)))
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(_submit(store.state, "What is the capital of France?"), store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.message == "Paris is the capital."
    assert store.state.goal is None, "direct answer must not create a Goal"
    assert store.state.interaction_state is InteractionState.IDLE
    assert len(provider.calls) == 1
    assert [entry for entry in timeline if entry[0].startswith("tool_")] == []
    assert executions == []


def test_direction_boundary_clarification_has_zero_tool_effect() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    clarification = ClarificationRequest(
        correlation_id="control-clarify-1",
        question=_CLARIFYING_QUESTION,
        boundary_code="direction_boundary",
        missing_fields=("target_direction",),
        safe_assumptions=(),
    )
    # 第二条脚本响应只是防止当前实现把 control-only 响应当 invalid 输出重试后
    # 耗尽脚本;符合 U3 的实现必须停在一次澄清边界,根本不会消费它。
    provider = ScriptedProvider(
        ModelResponse((), control=clarification),
        ModelResponse((ModelTextBlock("fallback answer that must never be needed"),)),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(_submit(store.state, "Migrate it"), store.load())

    assert store.state.interaction_state is InteractionState.CLARIFYING, (
        "direction-boundary ambiguity must leave durable status CLARIFYING"
    )
    assert _CLARIFYING_QUESTION in repr(store.state), (
        "the single clarification question must be durably persisted"
    )
    assert result.message == _CLARIFYING_QUESTION
    assert len(provider.calls) == 1, "one clarification boundary means one model call"
    assert [entry for entry in timeline if entry[0].startswith("tool_")] == [], (
        "clarification must have zero ToolRuntime.prepare/invoke effects"
    )
    assert executions == []
    assert store.state.goal is None


def test_explicit_task_persists_goal_before_rebuilding_context() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse((), control=GoalProposal("control-goal-1", _goal_frame())),
        ModelResponse((ModelToolCall("call-1", "write_note", {"path": "notes/todo.md"}),)),
        ModelResponse((ModelTextBlock("note written"),)),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(
        _submit(store.state, "Write a note file notes/todo.md with my plan"),
        store.load(),
    )

    assert store.state.goal is not None, "explicit task must persist its Goal durably by CAS"
    assert store.state.goal.goal_id == "goal-1"

    labels = [entry[0] for entry in timeline]
    assert "goal_cas" in labels
    assert "tool_prepare" in labels, "the task tool effect must still happen after the Goal"
    cas_index = labels.index("goal_cas")
    prepare_index = labels.index("tool_prepare")
    assert cas_index < prepare_index, "goal CAS must precede any task tool prepare"
    rebuilds_between = [
        index
        for index, entry in enumerate(timeline)
        if entry == ("context_build", True) and cas_index < index < prepare_index
    ]
    assert rebuilds_between, (
        "model context must be rebuilt after the durable goal CAS and before tool prepare"
    )
    assert executions == ["notes/todo.md"]
    assert result.status is RunStatus.COMPLETED


def test_task_tool_call_without_durable_goal_fails_before_prepare() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    # 模型在没有任何 GoalProposal 的情况下直接发起 effectful 任务工具调用;
    # 第二条响应仅防脚本耗尽,fail-closed 实现不会消费它。
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("call-1", "write_note", {"path": "notes/todo.md"}),)),
        ModelResponse((ModelTextBlock("fallback answer that must never be needed"),)),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(_submit(store.state, "hello"), store.load())

    assert [entry for entry in timeline if entry[0] == "tool_prepare"] == [], (
        "an effectful task tool call without a durable Goal must fail closed "
        "before ToolRuntime.prepare"
    )
    assert [entry for entry in timeline if entry[0] == "tool_invoke"] == []
    assert executions == [], "the tool callable must never execute without a durable Goal"
    assert result.status is not RunStatus.COMPLETED, "fail closed must not complete the run"
    assert store.state.goal is None


def test_control_and_illegal_tool_mix_fails_closed() -> None:
    # 有效 control + callable tool call 的混合在 ModelResponse 构造时即被闭合契约
    # 拒绝,发生在任何 runtime/CAS/prepare 之前,因此无需 runtime/tool harness。
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    initial_state = store.state
    progress = GoalProgress(
        correlation_id="control-progress-mix",
        goal_id="goal-1",
        goal_revision=1,
        summary="working",
        next_step="continue",
    )

    with pytest.raises(
        ValueError, match="model control cannot be combined with callable tool calls"
    ):
        ModelResponse(
            (ModelToolCall("call-1", "write_note", {"path": "notes/todo.md"}),),
            control=progress,
        )

    assert store.state == initial_state
    assert store.state.revision == initial_state.revision
    assert timeline == []


def test_unknown_or_malformed_control_never_mutates_state() -> None:
    # 未知 control 变体与畸形已知 control 都是契约边界上的规范拒绝,
    # 发生在 CAS/prepare/invoke 之前,不得触碰 durable 状态。
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    initial_state = store.state

    with pytest.raises(
        TypeError, match="model response control must be one closed control variant"
    ):
        ModelResponse((), control=object())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="control correlation_id must not be empty"):
        ClarificationRequest(
            correlation_id="",
            question=_CLARIFYING_QUESTION,
            boundary_code="direction_boundary",
            missing_fields=("target_direction",),
            safe_assumptions=(),
        )

    assert store.state == initial_state
    assert timeline == []


def test_active_goal_plain_done_text_cannot_end_goal() -> None:
    # U3B 语义边界:纯文本 "done" 只能结束一次 run,不构成 Goal 完成验证;
    # VERIFIED_DONE 必须经由 completion claim + 逐条 mandatory criterion 证据。
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse((), control=GoalProposal("control-goal-plain-done", _goal_frame())),
        ModelResponse((ModelTextBlock("Goal accepted."),)),
        ModelResponse((ModelTextBlock("done"),)),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    first = runtime.run_turn(
        _submit(store.state, "Write a note file notes/todo.md with my plan"),
        store.load(),
    )

    assert first.status is RunStatus.COMPLETED
    goal_after_first = store.state.goal
    assert goal_after_first is not None, "first turn must durably create the Goal"

    second = runtime.run_turn(_submit(store.state, "done"), store.load())

    assert second.status is RunStatus.COMPLETED
    assert second.message == "done"
    goal_after_second = store.state.goal
    assert goal_after_second is not None, "plain done text must not drop the durable Goal"
    assert goal_after_second.goal_id == goal_after_first.goal_id
    assert goal_after_second.revision == goal_after_first.revision
    assert goal_after_second.status is goal_after_first.status
    assert goal_after_second.status is GoalStatus.GOAL_READY, (
        "the Goal must stay active; plain text cannot advance its lifecycle"
    )
    assert goal_after_second.status is not GoalStatus.VERIFIED_DONE, (
        "plain done text must never yield VERIFIED_DONE"
    )
    assert goal_after_second.admitted_criteria == goal_after_first.admitted_criteria
    assert store.state.evidence_records == (), (
        "plain text must not fabricate verification evidence"
    )
    assert store.state.completion_claim is None, (
        "plain text must not create a completion claim"
    )
    assert len(provider.calls) == 3
    assert [entry for entry in timeline if entry[0].startswith("tool_")] == []
    assert executions == []


_PROGRESS_SUMMARY = "Drafted the note body and confirmed the target path."
_PROGRESS_NEXT_STEP = "Write notes/todo.md and report the outcome."


def test_progress_control_continues_without_user_continue_message() -> None:
    # U3B 连续性边界:活跃 Goal 下,control-only GoalProgress 必须在同一个观察
    # run 内被接受并持久化(EXECUTING + correlation 绑定 receipt),runtime 自行
    # 重建上下文继续到最终文本;不得依赖用户再提交一条合成 "continue" 消息。
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    progress = GoalProgress(
        correlation_id="control-progress-1",
        goal_id="goal-1",
        goal_revision=1,
        summary=_PROGRESS_SUMMARY,
        next_step=_PROGRESS_NEXT_STEP,
    )
    provider = ScriptedProvider(
        ModelResponse((), control=GoalProposal("control-goal-progress-setup", _goal_frame())),
        ModelResponse((ModelTextBlock("Goal accepted."),)),
        ModelResponse((), control=progress),
        ModelResponse((ModelTextBlock("Progress recorded; continuing the note task."),)),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    setup = runtime.run_turn(
        _submit(store.state, "Write a note file notes/todo.md with my plan"),
        store.load(),
    )

    assert setup.status is RunStatus.COMPLETED
    goal_after_setup = store.state.goal
    assert goal_after_setup is not None, "setup turn must durably create the active Goal"
    calls_after_setup = len(provider.calls)
    proposal_receipts_after_setup = [
        receipt
        for receipt in store.state.control_receipts
        if receipt.control_kind == "goal_proposal"
    ]
    assert len(proposal_receipts_after_setup) == 1

    result = runtime.run_turn(
        _submit(store.state, "Work on the admitted note task now."),
        store.load(),
    )

    # 单个观察 run 必须自己消化 progress 并继续:恰好两次新增 provider 调用,
    # 以最终文本 COMPLETED,证明不需要第三条用户动作。
    assert result.status is RunStatus.COMPLETED
    assert result.message == "Progress recorded; continuing the note task."
    assert len(provider.calls) == calls_after_setup + 2

    goal = store.state.goal
    assert goal is not None, "accepted progress must not drop the durable Goal"
    assert goal.goal_id == goal_after_setup.goal_id
    assert goal.revision == goal_after_setup.revision
    assert goal.status is GoalStatus.EXECUTING, (
        "accepted progress must durably move the active Goal to EXECUTING"
    )
    assert goal.progress_summary == _PROGRESS_SUMMARY
    assert goal.next_step == _PROGRESS_NEXT_STEP

    progress_receipts = [
        receipt
        for receipt in store.state.control_receipts
        if receipt.control_kind == "goal_progress"
    ]
    assert len(progress_receipts) == 1, (
        "exactly one correlation-bound ControlReceipt must persist this progress"
    )
    progress_receipt = progress_receipts[0]
    assert progress_receipt.correlation_id == "control-progress-1"
    assert progress_receipt.goal_id == goal.goal_id
    assert progress_receipt.goal_revision == goal.revision
    assert progress_receipt.payload_digest
    assert [
        receipt
        for receipt in store.state.control_receipts
        if receipt.control_kind == "goal_proposal"
    ] == proposal_receipts_after_setup, "the earlier GoalProposal receipt must be preserved"

    user_messages = [
        fact.content["text"]
        for fact in store.state.facts
        if fact.kind is FactKind.USER_MESSAGE
    ]
    assert user_messages == [
        "Write a note file notes/todo.md with my plan",
        "Work on the admitted note task now.",
    ], "only the two real user actions may exist in the conversation"
    assert all(str(text).strip().lower() != "continue" for text in user_messages), (
        "continuation must not be driven by a synthetic continue user message"
    )

    assert [entry for entry in timeline if entry[0].startswith("tool_")] == []
    assert executions == []

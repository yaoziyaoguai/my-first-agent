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

from dataclasses import replace

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    BeginAnswer,
    BlockedClaim,
    ClarificationRequest,
    ConversationState,
    DirectResponse,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    FactKind,
    GoalFrame,
    GoalProgress,
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
from tests.kernel.fakes import (
    RUNTIME_GOAL_ID,
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    goal_draft_from_frame,
)

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
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
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


def _discovery_tool(executions: list[str]) -> RegisteredTool:
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="list_files",
        version="1",
        description="List bounded workspace paths",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={"fixture": True},
        output_limit_chars=100,
    )

    def run(intent) -> str:
        executions.append(intent.arguments["path"])
        return "data.csv\ncheck-report"

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
        targets=("notes/todo.md",),
        scope=("workspace/notes",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                "criterion-1",
                "note exists",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="notes/todo.md",
            ),
        ),
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
                limits=ContextLimits(max_input_tokens=2_400, output_reserve=200),
                workspace_identity_digest="workspace-digest-1",
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


def test_typed_direct_response_does_not_create_goal_or_tool_effect() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id="control-answer-1",
                text="Paris is the capital.",
            ),
        )
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(
        _submit(store.state, "What is the capital of France?"),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "Paris is the capital."
    assert store.state.goal is None
    assert store.state.interaction_state is InteractionState.IDLE
    assert len(provider.calls) == 1
    assert [entry for entry in timeline if entry[0].startswith("tool_")] == []
    assert executions == []


def test_begin_answer_opens_only_read_tools_and_finishes_without_goal() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=BeginAnswer(correlation_id="control-begin-answer-1"),
        ),
        ModelResponse((ModelToolCall("list-1", "list_files", {"path": "."}),)),
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id="control-grounded-answer-1",
                text="I found data.csv and check-report.",
            ),
        ),
    )
    runtime = _runtime(
        provider,
        store,
        timeline,
        (_discovery_tool(executions), _task_tool(executions)),
    )

    result = runtime.run_turn(
        _submit(store.state, "Which files are in this project?"),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "I found data.csv and check-report."
    assert store.state.goal is None
    assert store.state.interaction_state is InteractionState.IDLE
    assert executions == ["."]
    assert provider.calls[0].tools == ()
    assert [tool.name for tool in provider.calls[1].tools] == ["list_files"]
    assert "goal_proposal" not in provider.calls[1].control_schema["input_schema"][
        "properties"
    ]["kind"]["enum"]
    assert [
        receipt.control_kind for receipt in store.state.control_receipts
    ] == ["begin_answer"]


def test_unadvertised_read_tool_cannot_bypass_intent_gate() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("list-hidden", "list_files", {"path": "."}),)),
        ModelResponse((), control=BeginAnswer(correlation_id="control-after-denial")),
        ModelResponse((ModelToolCall("list-visible", "list_files", {"path": "."}),)),
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id="control-answer-after-read",
                text="I found the project files.",
            ),
        ),
    )
    runtime = _runtime(provider, store, timeline, (_discovery_tool(executions),))

    result = runtime.run_turn(
        _submit(store.state, "Which files are here?"),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert executions == ["."], "only the post-begin_answer read may execute"
    assert sum(entry == ("tool_prepare", "list_files") for entry in timeline) == 1
    assert any(
        fact.content.get("code") == "unadvertised_tool"
        for fact in store.state.facts
    )


def test_grounded_answer_cannot_upgrade_source_content_into_goal_authority() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer(correlation_id="control-answer-mode")),
        ModelResponse((ModelToolCall("list-1", "list_files", {"path": "."}),)),
        ModelResponse(
            (),
            control=goal_draft_from_frame("control-source-derived-goal", _goal_frame()),
        ),
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id="control-answer-after-rejection",
                text="The project contains data.csv and check-report.",
            ),
        ),
    )
    runtime = _runtime(provider, store, timeline, (_discovery_tool(executions),))

    result = runtime.run_turn(
        _submit(store.state, "What does this project contain?"),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is None
    assert executions == ["."]
    assert any(
        fact.content.get("code") == "invalid_model_control"
        and "goal_proposal" in fact.content.get("text", "")
        for fact in store.state.facts
    )
    assert all(
        receipt.control_kind != "goal_proposal"
        for receipt in store.state.control_receipts
    )


@pytest.mark.parametrize(
    "prior_interaction",
    [InteractionState.ANSWERING, InteractionState.CLARIFYING],
)
def test_fresh_user_action_reenters_intent_gate(prior_interaction: InteractionState) -> None:
    timeline: list[tuple[str, object]] = []
    initial = replace(
        ConversationState.new("conversation-1"),
        interaction_state=prior_interaction,
    )
    store = RecordingCheckpointStore(initial, timeline)
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id=f"control-fresh-{prior_interaction.value}",
                text="A fresh answer.",
            ),
        )
    )
    runtime = _runtime(provider, store, timeline, (_discovery_tool([]),))

    result = runtime.run_turn(_submit(store.state, "A new question"), store.load())

    assert result.status is RunStatus.COMPLETED
    assert provider.calls[0].tools == ()
    assert "goal_proposal" in provider.calls[0].control_schema["input_schema"][
        "properties"
    ]["kind"]["enum"]
    assert store.state.interaction_state is InteractionState.IDLE


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


def test_discoverable_workspace_clarification_is_rejected_before_user_interrupt() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=ClarificationRequest(
                correlation_id="control-discoverable-clarify",
                question="Which CSV file should I read?",
                boundary_code="workspace_details",
                missing_fields=("csv_path",),
                safe_assumptions=(),
            ),
        ),
        ModelResponse(
            (),
            control=BeginAnswer(correlation_id="control-discoverable-begin-answer"),
        ),
        ModelResponse(
            (ModelToolCall("list-1", "list_files", {"path": "."}),),
        ),
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id="control-discovered-answer",
                text="I found data.csv and check-report.",
            ),
        ),
    )
    runtime = _runtime(
        provider,
        store,
        timeline,
        (_discovery_tool(executions),),
    )

    result = runtime.run_turn(
        _submit(store.state, "Use the CSV and existing validator."),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert executions == ["."]
    assert store.state.interaction_state is InteractionState.IDLE
    assert any(
        fact.content.get("code") == "clarification_requires_discovery"
        and "begin_answer" in fact.content.get("text", "")
        for fact in store.state.facts
    )


def test_discovery_policy_directs_explicit_task_to_goal_proposal_before_sources() -> None:
    # 016 §5.2 goal-first:clarification_requires_discovery 的修复消息必须告知模型,
    # 显式可验收任务应先提交 goal_proposal——同一 action 内成功的 source 检索会
    # 关闭铸造窗口,否则真实模型会在“先探索再提案”后陷入无合规路径的死胡同。
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=ClarificationRequest(
                correlation_id="control-clarify-first",
                question="Which file should I write?",
                boundary_code="workspace_details",
                missing_fields=("target_path",),
                safe_assumptions=(),
            ),
        ),
        ModelResponse((ModelToolCall("list-1", "list_files", {"path": "."}),)),
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id="control-discovered-answer",
                text="I found data.csv.",
            ),
        ),
    )
    runtime = _runtime(provider, store, timeline, (_discovery_tool(executions),))

    runtime.run_turn(_submit(store.state, "Use the CSV."), store.load())

    messages = [
        fact.content.get("text", "")
        for fact in store.state.facts
        if fact.content.get("code") == "clarification_requires_discovery"
    ]
    assert messages, "clarification_requires_discovery policy must fire"
    assert any(
        "submit goal_proposal first" in text for text in messages
    ), "policy must offer the goal-first compliant path before forcing discovery"


def test_explicit_task_persists_goal_before_rebuilding_context() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse(
            (), control=goal_draft_from_frame("control-goal-1", _goal_frame())
        ),
        ModelResponse((ModelToolCall("call-1", "write_note", {"path": "notes/todo.md"}),)),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="control-goal-1-blocked",
                goal_id=RUNTIME_GOAL_ID,
                goal_revision=1,
                blocker="note written; completion evidence is unavailable",
                safe_attempts=("wrote the requested note",),
                resume_condition="provide a closed verification oracle",
            ),
        ),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(
        _submit(store.state, "Write a note file notes/todo.md with my plan"),
        store.load(),
    )

    assert store.state.goal is not None, "explicit task must persist its Goal durably by CAS"
    assert store.state.goal.goal_id.startswith("goal-v1-")

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


def test_unadvertised_task_tool_without_goal_is_denied_before_prepare() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    # 模型在没有任何 GoalProposal 的情况下直接发起 effectful 任务工具调用；
    # Runtime 拒绝该调用后仍允许模型安全地改答普通文本。
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("call-1", "write_note", {"path": "notes/todo.md"}),)),
        ModelResponse((ModelTextBlock("I cannot modify files without a Goal."),)),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(_submit(store.state, "hello"), store.load())

    assert [entry for entry in timeline if entry[0] == "tool_prepare"] == [], (
        "an effectful task tool call without a durable Goal must fail closed "
        "before ToolRuntime.prepare"
    )
    assert [entry for entry in timeline if entry[0] == "tool_invoke"] == []
    assert executions == [], "the tool callable must never execute without a durable Goal"
    assert result.status is RunStatus.COMPLETED
    assert result.message == "I cannot modify files without a Goal."
    assert any(
        fact.content.get("code") == "unadvertised_tool"
        for fact in store.state.facts
    )
    assert store.state.goal is None


def test_invented_tool_without_goal_is_denied_before_tool_batch() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("call-unknown", "run_project_tests", {}),)),
        ModelResponse((ModelTextBlock("I need a Goal before doing project work."),)),
    )
    runtime = _runtime(provider, store, timeline, ())

    # 这条测试只隔离“模型凭空发明工具”的安全边界；显式任务必须先铸造 Goal、
    # 且不能用普通文本逃逸，由 016 的 explicit-non-prose 契约单独覆盖。
    result = runtime.run_turn(
        _submit(store.state, "What does running project tests verify?"),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert [entry for entry in timeline if entry[0] == "tool_prepare"] == []
    assert not any(fact.kind is FactKind.TOOL_CALLS for fact in store.state.facts), (
        "a made-up tool name must not create a pre-Goal tool batch"
    )
    assert any(
        fact.kind is FactKind.POLICY_RESULT
        and fact.content.get("code") == "unadvertised_tool"
        for fact in store.state.facts
    )
    assert not any(
        fact.kind is FactKind.TOOL_RESULT
        and fact.content.get("metadata", {}).get("code") == "unknown_tool"
        for fact in store.state.facts
    )


def test_control_and_illegal_tool_mix_fails_closed() -> None:
    # 有效 control + callable tool call 的混合在 ModelResponse 构造时即被闭合契约
    # 拒绝,发生在任何 runtime/CAS/prepare 之前,因此无需 runtime/tool harness。
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    initial_state = store.state
    progress = GoalProgress(
        correlation_id="control-progress-mix",
        goal_id=RUNTIME_GOAL_ID,
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
    # U3B 语义边界:活跃 Goal 下纯文本不能结束 run；一次 repair 后重复纯文本
    # 必须 fail closed，VERIFIED_DONE 仍只能来自 completion + closed evidence。
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=goal_draft_from_frame("control-goal-plain-done", _goal_frame()),
        ),
        ModelResponse((ModelTextBlock("Goal accepted."),)),
        ModelResponse((ModelTextBlock("done"),)),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(
        _submit(store.state, "Write a note file notes/todo.md with my plan"),
        store.load(),
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_model_control"
    goal = store.state.goal
    assert goal is not None, "plain done text must not drop the durable Goal"
    assert goal.status is GoalStatus.GOAL_READY, (
        "the Goal must stay active; plain text cannot advance its lifecycle"
    )
    assert goal.status is not GoalStatus.VERIFIED_DONE, (
        "plain done text must never yield VERIFIED_DONE"
    )
    assert store.state.evidence_records == (), (
        "plain text must not fabricate verification evidence"
    )
    assert store.state.completion_claim is None, (
        "plain text must not create a completion claim"
    )
    assert len(provider.calls) == 3
    assert [
        fact.content.get("code")
        for fact in store.state.facts
        if fact.content.get("code") == "active_goal_requires_control"
    ] == ["active_goal_requires_control"]
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
        goal_id=RUNTIME_GOAL_ID,
        goal_revision=1,
        summary=_PROGRESS_SUMMARY,
        next_step=_PROGRESS_NEXT_STEP,
    )
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=goal_draft_from_frame("control-goal-progress-setup", _goal_frame()),
        ),
        ModelResponse(
            (ModelToolCall("write-before-progress", "write_note", {"path": "notes/todo.md"}),)
        ),
        ModelResponse((), control=progress),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="control-progress-blocked",
                goal_id=RUNTIME_GOAL_ID,
                goal_revision=1,
                blocker="the note body still needs a user-provided source",
                safe_attempts=("recorded the verified progress",),
                resume_condition="provide the note source",
            ),
        ),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(
        _submit(store.state, "Write a note file notes/todo.md with my plan"),
        store.load(),
    )

    # 单个观察 run 必须自己消化 proposal/progress 并继续到结构化 blocked
    # 终态，不需要额外的用户 continue 动作。
    assert result.status is RunStatus.COMPLETED
    assert result.message == "the note body still needs a user-provided source"
    assert len(provider.calls) == 4
    assert executions == ["notes/todo.md"]

    goal = store.state.goal
    assert goal is not None, "accepted progress must not drop the durable Goal"
    assert goal.goal_id.startswith("goal-v1-")
    assert goal.status is GoalStatus.BLOCKED
    assert goal.progress_summary == _PROGRESS_SUMMARY
    assert goal.next_step == "provide the note source"

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
    assert len([
        receipt
        for receipt in store.state.control_receipts
        if receipt.control_kind == "goal_proposal"
    ]) == 1, "the earlier GoalProposal receipt must be preserved"

    user_messages = [
        fact.content["text"]
        for fact in store.state.facts
        if fact.kind is FactKind.USER_MESSAGE
    ]
    assert user_messages == [
        "Write a note file notes/todo.md with my plan",
    ], "only the real user action may exist in the conversation"


def test_repeated_goal_progress_requires_a_product_action_before_more_progress() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    first_progress = GoalProgress(
        correlation_id="control-progress-first",
        goal_id=RUNTIME_GOAL_ID,
        goal_revision=1,
        summary="Prepared the next safe step.",
        next_step="Write notes/todo.md.",
    )
    repeated_progress = GoalProgress(
        correlation_id="control-progress-repeated",
        goal_id=RUNTIME_GOAL_ID,
        goal_revision=1,
        summary="Still preparing the next safe step.",
        next_step="Write notes/todo.md.",
    )
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=goal_draft_from_frame("control-goal-progress", _goal_frame()),
        ),
        ModelResponse(
            (ModelToolCall("write-before-progress", "write_note", {"path": "notes/first.md"}),)
        ),
        ModelResponse((), control=first_progress),
        ModelResponse((), control=repeated_progress),
        ModelResponse(
            (ModelToolCall("write-after-replan", "write_note", {"path": "notes/todo.md"}),)
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="control-progress-blocked-after-tool",
                goal_id=RUNTIME_GOAL_ID,
                goal_revision=1,
                blocker="closed verification evidence is unavailable",
                safe_attempts=("wrote the requested note",),
                resume_condition="provide a closed verification oracle",
            ),
        ),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool(executions),))

    result = runtime.run_turn(
        _submit(store.state, "Write a note file notes/todo.md with my plan"),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert executions == ["notes/first.md", "notes/todo.md"]
    progress_receipts = [
        receipt
        for receipt in store.state.control_receipts
        if receipt.control_kind == "goal_progress"
    ]
    assert [receipt.correlation_id for receipt in progress_receipts] == [
        "control-progress-first"
    ]
    assert any(
        fact.content.get("code") == "no_progress_replan_required"
        for fact in store.state.facts
    )


def test_reused_goal_progress_correlation_is_repairable_control_input() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    executions: list[str] = []
    progress = GoalProgress(
        correlation_id="control-goal-progress-reuse",
        goal_id=RUNTIME_GOAL_ID,
        goal_revision=1,
        summary="Completed one concrete write.",
        next_step="Continue with the remaining requested work.",
    )
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=goal_draft_from_frame("control-goal-progress-reuse", _goal_frame()),
        ),
        ModelResponse(
            (
                ModelToolCall(
                    "write-before-first-progress",
                    "write_note",
                    {"path": "notes/first.md"},
                ),
            )
        ),
        ModelResponse((), control=progress),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="control-progress-reuse-blocked",
                goal_id=RUNTIME_GOAL_ID,
                goal_revision=1,
                blocker="closed verification evidence is unavailable",
                safe_attempts=("completed one concrete write",),
                resume_condition="provide a closed verification oracle",
            ),
        ),
    )

    result = _runtime(
        provider,
        store,
        timeline,
        (_task_tool(executions),),
    ).run_turn(
        _submit(store.state, "Write a note file notes/todo.md with my plan"),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert executions == ["notes/first.md"]
    assert any(
        fact.content.get("code") == "invalid_model_control"
        and "new correlation_id" in fact.content.get("text", "")
        for fact in store.state.facts
    )


def test_persistent_goal_progress_without_product_action_fails_closed() -> None:
    timeline: list[tuple[str, object]] = []
    store = RecordingCheckpointStore(ConversationState.new("conversation-1"), timeline)
    progresses = tuple(
        GoalProgress(
            correlation_id=f"control-progress-stalled-{index}",
            goal_id=RUNTIME_GOAL_ID,
            goal_revision=1,
            summary=f"Narrated progress {index}.",
            next_step="Write notes/todo.md.",
        )
        for index in range(3)
    )
    provider = ScriptedProvider(
        ModelResponse(
            (), control=goal_draft_from_frame("control-goal-stalled", _goal_frame())
        ),
        *(ModelResponse((), control=progress) for progress in progresses),
    )
    runtime = _runtime(provider, store, timeline, (_task_tool([]),))

    result = runtime.run_turn(
        _submit(store.state, "Write a note file notes/todo.md with my plan"),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "no_progress"
    assert len(provider.calls) == 3
    assert sum(
        fact.content.get("code") == "no_progress_replan_required"
        for fact in store.state.facts
    ) == 1
    assert [entry for entry in timeline if entry[0].startswith("tool_")] == []

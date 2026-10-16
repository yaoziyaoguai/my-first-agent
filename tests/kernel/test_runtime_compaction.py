"""Runtime compaction 行为测试。

覆盖三组事实：

1. 构造与 None 路径：AgentRuntime 构造接受 ConversationArchive
   （RecordingArchive double）且未 run_turn 前零调用；archive 默认
   None 时普通 DirectResponse run 的既有路径完全不变。
2. 自动 compaction：input limit 与 remote disclosure 在 provider/archive
   之前拦截；成功时 archive 先于 CAS 并在同一 run 内继续；ineligible
   history 映射为 NO_CANDIDATE 而非 runtime_failure。
3. 内部单批执行路径与故障/限额：``_perform_compaction`` 在真实
   KernelContextManager/parse/reducer/commit 链路上 archive 恰一次且
   先于 CAS、旧完整 state 被 archive、summary 替换准确；provider
   retryable、非法 summary、archive 失败均 fail closed 不缩减；CAS
   冲突返回 newest state；archive 后崩溃保留旧 state 并释放 lease；
   多批次部分失败保留已提交批次。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agent.continuity.archive import ArchiveError
from agent.runtime.compaction_rules import parse_compaction_turns
from agent.runtime.context import ContextLimitError, ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    Action,
    ActionDisposition,
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    ArchivedConversation,
    BlockedClaim,
    BudgetReport,
    CompactionPlanV1,
    CompactionTrigger,
    ContextPack,
    ConversationFact,
    ConversationState,
    ConversationSummaryV1,
    ConversationWorkspaceBindingV1,
    DirectResponse,
    EgressClass,
    FactKind,
    GoalStatus,
    LoadedSnapshot,
    ModelResponse,
    ModelTextBlock,
    PauseGoal,
    ProviderDescriptor,
    RecordedRunResult,
    ResumeGoal,
    RunStatus,
    RuntimeEventKind,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
    ToolDefinition,
    canonical_json_digest,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import (
    CheckpointCASConflictError,
    CheckpointUsage,
    RetryableProviderError,
)
from agent.runtime.state import (
    accept_action,
    finalize_action,
    pause_for_approval,
    start_tool_batch,
)
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_noop_response,
)


class RecordingArchive:
    """ConversationArchive 的记录式 double；骨架阶段任何调用都视为违规。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def archive(
        self,
        state: ConversationState,
        *,
        source_checkpoint_digest: str,
        workspace_scope_digest: str,
    ) -> ArchivedConversation:
        self.calls.append("archive")
        raise AssertionError("conversation archive must not be called by the skeleton")

    def list_archived(
        self,
        *,
        workspace_scope_digest: str,
    ) -> tuple[ArchivedConversation, ...]:
        self.calls.append("list_archived")
        raise AssertionError("conversation archive must not be called by the skeleton")

    def load_archived(self, archive: ArchivedConversation) -> LoadedSnapshot:
        self.calls.append("load_archived")
        raise AssertionError("conversation archive must not be called by the skeleton")


class RecordingContextManager(KernelContextManager):
    """在真实 KernelContextManager 上叠加只读计数，证明 compaction 零调用。"""

    def __init__(self) -> None:
        super().__init__(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        )
        self.usage_calls = 0
        self.plan_compaction_calls = 0
        self.build_compaction_calls = 0

    def usage(
        self,
        state: ConversationState,
        action: Action,
        tools: tuple[ToolDefinition, ...],
    ) -> object:
        self.usage_calls += 1
        return super().usage(state, action, tools)

    def plan_compaction(
        self,
        state: ConversationState,
        action: Action,
        tools: tuple[ToolDefinition, ...],
        *,
        active_checkpoint_bytes: int,
        soft_threshold_bytes: int,
        force: bool = False,
    ) -> CompactionPlanV1:
        self.plan_compaction_calls += 1
        return super().plan_compaction(
            state,
            action,
            tools,
            active_checkpoint_bytes=active_checkpoint_bytes,
            soft_threshold_bytes=soft_threshold_bytes,
            force=force,
        )

    def build_compaction(
        self,
        state: ConversationState,
        plan: CompactionPlanV1,
        source_checkpoint_digest: str,
    ) -> ContextPack:
        self.build_compaction_calls += 1
        return super().build_compaction(state, plan, source_checkpoint_digest)


class UsageRecordingStore(InMemoryCheckpointStore):
    """现有 fake 之上叠加 usage 计数；None 路径必须零调用。"""

    def __init__(self, state: ConversationState) -> None:
        super().__init__(state)
        self.usage_calls = 0

    def usage(self, snapshot: LoadedSnapshot) -> CheckpointUsage:
        self.usage_calls += 1
        return CheckpointUsage(
            active_bytes=1, soft_threshold_bytes=1, hard_cap_bytes=1
        )


def _submit(state: ConversationState) -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-1",
        message="hello",
    )


def test_construction_accepts_recording_archive_with_zero_calls() -> None:
    store = UsageRecordingStore(ConversationState.new("conversation-1"))
    context_manager = RecordingContextManager()
    archive = RecordingArchive()

    AgentRuntime(
        provider=ScriptedProvider(),
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    assert archive.calls == []
    assert store.usage_calls == 0
    assert context_manager.usage_calls == 0
    assert context_manager.plan_compaction_calls == 0
    assert context_manager.build_compaction_calls == 0


def test_default_none_direct_response_run_keeps_existing_path() -> None:
    store = UsageRecordingStore(ConversationState.new("conversation-1"))
    context_manager = RecordingContextManager()
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=DirectResponse(correlation_id="direct-1", text="hello back"),
        )
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.message == "hello back"
    assert len(provider.calls) == 1
    assert store.usage_calls == 0
    assert context_manager.usage_calls == 0
    assert context_manager.plan_compaction_calls == 0
    assert context_manager.build_compaction_calls == 0


# --------------------------------------------------------------------------- #
# _perform_compaction 内部成功路径
# --------------------------------------------------------------------------- #


_SCOPE = "ab" * 32
# 首个完整 closed turn 构成合法 removable 集（state 原序）。
_REMOVABLE_IDS = ("action:1:user", "action:2:assistant")


class _DigestTokenLease:
    """run_turn mutation lease 的最小实现：release 只恢复 store.locked。"""

    def __init__(self, store: DigestTokenStore) -> None:
        self._store = store
        self.released = False

    def release(self) -> None:
        if not self.released:
            self.released = True
            self._store.locked = False


class DigestTokenStore:
    """满足 sha256 token 合同的最小 recording store。

    生产合同要求 compaction 的 source token 是 ``sha256:<64hex>``；现有
    InMemoryCheckpointStore 产生 ``token-N``，因此这里实现 run_turn 与
    compaction 路径共同所需的最小 lease/load/usage/capacity/CAS，而不是
    改变生产合同迎合现有 fake。
    """

    def __init__(self, state: ConversationState, calls: list[str]) -> None:
        self.state = state
        self._calls = calls
        self._counter = 0
        self.locked = False
        self.usage_calls = 0

    def _token(self) -> str:
        return f"sha256:{self._counter:064x}"

    def try_acquire(self, conversation_id: str) -> _DigestTokenLease | None:
        if conversation_id != self.state.conversation_id or self.locked:
            return None
        self.locked = True
        return _DigestTokenLease(self)

    def load(self) -> LoadedSnapshot:
        return LoadedSnapshot(self.state, self._token())

    def ensure_capacity(self, snapshot: LoadedSnapshot, *, reserve_bytes: int) -> bool:
        # 只做参数基本合法性检查：reserve 为正且 snapshot 仍指向当前 token/revision。
        return (
            isinstance(reserve_bytes, int)
            and not isinstance(reserve_bytes, bool)
            and reserve_bytes > 0
            and snapshot.token == self._token()
            and snapshot.state.revision == self.state.revision
        )

    def usage(self, snapshot: LoadedSnapshot) -> CheckpointUsage:
        # 生产合同：snapshot 过期即 fail closed，不得用陈旧读数驱动规划。
        self.usage_calls += 1
        if (
            snapshot.token != self._token()
            or snapshot.state.revision != self.state.revision
        ):
            raise RuntimeError("stale snapshot usage")
        return CheckpointUsage(
            active_bytes=1_024, soft_threshold_bytes=1_024, hard_cap_bytes=8_192
        )

    def compare_and_swap(
        self,
        snapshot: LoadedSnapshot,
        new_state: ConversationState,
    ) -> LoadedSnapshot:
        self._calls.append("cas")
        if (
            snapshot.token != self._token()
            or snapshot.state.revision != self.state.revision
        ):
            raise RuntimeError("snapshot conflict")
        self.state = new_state
        self._counter += 1
        return self.load()


class RecordingSuccessArchive:
    """记录 archive 调用的 double；成功路径外的读取一律违规。"""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.archived: list[tuple[ConversationState, str, str]] = []

    def archive(
        self,
        state: ConversationState,
        *,
        source_checkpoint_digest: str,
        workspace_scope_digest: str,
    ) -> ArchivedConversation:
        self._calls.append("archive")
        self.archived.append((state, source_checkpoint_digest, workspace_scope_digest))
        return ArchivedConversation(
            conversation_id=state.conversation_id,
            workspace_scope_digest=workspace_scope_digest,
            source_checkpoint_digest=source_checkpoint_digest,
            path=Path("archived") / f"{source_checkpoint_digest}.json",
        )

    def list_archived(self, *, workspace_scope_digest: str):
        raise AssertionError("compaction success path must not list archives")

    def load_archived(self, archive: ArchivedConversation) -> LoadedSnapshot:
        raise AssertionError("compaction success path must not load archives")


def _compaction_source_state() -> ConversationState:
    """两个完整 closed turn、已绑定 workspace 的 pre-compaction 状态。"""

    def _fact(fact_id: str, kind: FactKind) -> ConversationFact:
        return ConversationFact(fact_id=fact_id, kind=kind, content={"text": fact_id})

    return ConversationState(
        conversation_id="conversation-1",
        revision=4,
        next_action_seq=5,
        replay_floor=5,
        facts=(
            _fact("action:1:user", FactKind.USER_MESSAGE),
            _fact("action:2:assistant", FactKind.ASSISTANT_MESSAGE),
            _fact("action:3:user", FactKind.USER_MESSAGE),
            _fact("action:4:assistant", FactKind.ASSISTANT_MESSAGE),
        ),
        workspace_binding=ConversationWorkspaceBindingV1.create(
            workspace_scope_digest=_SCOPE,
            workspace_identity_digest=f"workspace:v1:{_SCOPE}",
            bound_at="2026-09-04T00:00:00Z",
        ),
    )


def _actionable_plan() -> CompactionPlanV1:
    return CompactionPlanV1(
        trigger=CompactionTrigger.MANUAL,
        removable_fact_ids=_REMOVABLE_IDS,
        usage=BudgetReport(
            input_limit=8_000, estimated_input_tokens=100, output_reserve=500
        ),
        active_checkpoint_bytes=128,
        soft_threshold_bytes=1_024,
    )


class ForcedCompactionContextManager(KernelContextManager):
    """test-only：只要 ``_REMOVABLE_IDS`` 仍完整存在就强制 actionable 压缩计划。

    与 RecordingContextManager 的只读计数不同，这里让 run_turn 的 020 前台
    接线在受控状态下真实走到 compaction 批次：usage 仍走真实 no-source
    投影；触发决策只取决于 removable 集是否仍完整地留在 state.facts；
    bytes 原样透传，force 不做额外处理（非 bool 由上层合同自然约束）。
    """

    def __init__(self) -> None:
        super().__init__(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=100_000, output_reserve=500),
        )
        self.plan_compaction_calls = 0
        self.build_compaction_calls = 0

    def plan_compaction(
        self,
        state: ConversationState,
        action: Action,
        tools: tuple[ToolDefinition, ...],
        *,
        active_checkpoint_bytes: int,
        soft_threshold_bytes: int,
        force: bool = False,
    ) -> CompactionPlanV1:
        self.plan_compaction_calls += 1
        report = self.usage(state, action, tools)
        remaining = {fact.fact_id for fact in state.facts}
        removable = _REMOVABLE_IDS if set(_REMOVABLE_IDS) <= remaining else ()
        return CompactionPlanV1(
            trigger=(
                CompactionTrigger.CHECKPOINT_PRESSURE
                if removable
                else CompactionTrigger.NONE
            ),
            removable_fact_ids=removable,
            usage=report,
            active_checkpoint_bytes=active_checkpoint_bytes,
            soft_threshold_bytes=soft_threshold_bytes,
        )

    def build_compaction(
        self,
        state: ConversationState,
        plan: CompactionPlanV1,
        source_checkpoint_digest: str,
    ) -> ContextPack:
        self.build_compaction_calls += 1
        return super().build_compaction(state, plan, source_checkpoint_digest)


def _summary_response(context: ContextPack) -> ModelResponse:
    """合规 compaction provider callback：回写 pack 唯一 block 携带的两个 digest。"""

    # build_compaction 的合同保证单一 user message、单一 context_summary_input
    # block；shape 断言防止 scripted 响应静默绑定到错误的输入。
    (message,) = context.messages
    (block,) = message.content
    assert isinstance(block, dict) and block.get("type") == "context_summary_input"
    source_checkpoint_digest = block["source_checkpoint_digest"]
    source_fact_ids_digest = block["source_fact_ids_digest"]
    assert isinstance(source_checkpoint_digest, str)
    assert isinstance(source_fact_ids_digest, str)
    summary = ConversationSummaryV1(
        objective="First archived turn summarized for long-conversation compaction.",
        constraints=(),
        decisions=(),
        completed=(),
        open_items=(),
        key_references=(),
        source_checkpoint_digest=source_checkpoint_digest,
        source_fact_ids_digest=source_fact_ids_digest,
    )
    return ModelResponse(
        (ModelTextBlock(text=summary.to_json()),),
        stop_reason="stop",
        # 少报 usage：证明 output 计数由 bytes 下界钳住，而非信任自报值。
        output_tokens=1,
    )


def test_perform_compaction_archives_full_state_before_cas_and_replaces_summary() -> None:
    calls: list[str] = []
    store = DigestTokenStore(_compaction_source_state(), calls)
    archive = RecordingSuccessArchive(calls)
    source = store.load()
    # summary 绑定真实 source token 与 removable 集，模拟合规 provider 输出。
    summary = ConversationSummaryV1(
        objective="First archived turn summarized for long-conversation compaction.",
        constraints=(),
        decisions=(),
        completed=(),
        open_items=(),
        key_references=(),
        source_checkpoint_digest=source.token.removeprefix("sha256:"),
        source_fact_ids_digest=canonical_json_digest(list(_REMOVABLE_IDS)),
    )
    response = ModelResponse(
        (ModelTextBlock(text=summary.to_json()),),
        stop_reason="stop",
        # 少报 usage：证明 output 计数被 bytes 下界钳住，而非信任自报值。
        output_tokens=1,
    )
    provider = ScriptedProvider(response)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=100_000, output_reserve=500),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    plan = _actionable_plan()
    context = runtime._context_manager.build_compaction(
        source.state, plan, source.token
    )
    result = runtime._perform_compaction(source, plan, context)

    # provider 恰一次；archive 恰一次且严格先于 CAS。
    assert len(provider.calls) == 1
    assert calls == ["archive", "cas"]
    # archive 收到的是旧完整 state（全部 4 个 facts、原 revision、原 token）。
    (archived_state, archived_digest, archived_scope), = archive.archived
    assert archived_state == source.state
    assert archived_digest == source.token
    assert archived_scope == _SCOPE
    # 返回 snapshot 已替换为唯一 CONTEXT_SUMMARY，removable 集整体消失。
    reduced = result.snapshot.state
    assert store.state == reduced
    assert reduced.revision == source.state.revision + 1
    assert reduced.workspace_binding == source.state.workspace_binding
    assert tuple(fact.kind for fact in reduced.facts) == (
        FactKind.CONTEXT_SUMMARY,
        FactKind.USER_MESSAGE,
        FactKind.ASSISTANT_MESSAGE,
    )
    restored = ConversationSummaryV1.from_content(reduced.facts[0].content)
    assert restored.source_checkpoint_digest == source.token.removeprefix("sha256:")
    assert result.snapshot.token != source.token
    # 计数准确：input 来自专用 pack 的真实估算，output 被 bytes 下界钳住
    # （provider 少报为 1，实际计数取 bounded_output_tokens 且大于自报值）。
    assert result.input_tokens == provider.calls[0].budget.estimated_input_tokens
    assert result.output_tokens == response.bounded_output_tokens
    assert result.output_tokens > 1
    assert result.context == provider.calls[0]


def test_auto_compaction_archives_then_continues_same_run() -> None:
    calls: list[str] = []
    state = _compaction_source_state()
    store = DigestTokenStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    context_manager = ForcedCompactionContextManager()
    provider = ScriptedProvider(
        _summary_response,
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id="direct-after-compaction",
                text="continued after compaction",
            ),
        ),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.message == "continued after compaction"
    assert len(provider.calls) == 2
    compaction_context, ordinary_context = provider.calls
    assert compaction_context.tools == ()
    assert compaction_context.control_schema is None
    assert compaction_context.messages[0].content[0]["type"] == "context_summary_input"
    assert ordinary_context != compaction_context
    assert len(archive.archived) == 1
    archive_index = calls.index("archive")
    assert calls.count("archive") == 1
    assert calls[archive_index + 1] == "cas"
    assert sum(f.kind is FactKind.CONTEXT_SUMMARY for f in result.state.facts) == 1
    remaining_ids = {fact.fact_id for fact in result.state.facts}
    assert not set(_REMOVABLE_IDS) & remaining_ids
    assert context_manager.plan_compaction_calls >= 2
    assert context_manager.build_compaction_calls == 1
    assert store.usage_calls >= 2
    assert not store.locked


def test_auto_compaction_consumes_durable_run_model_budget_before_send() -> None:
    """压缩是物理模型调用，不能绕过跨 Resume 的 run 总上限。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = DigestTokenStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    provider = ScriptedProvider(
        _summary_response,
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id="must-not-send",
                text="must not use a second model call",
            ),
        ),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=ForcedCompactionContextManager(),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_model_calls=None, max_run_model_calls=1),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "run_model_call_limit"
    assert result.model_calls_used == 1
    assert len(provider.calls) == 1
    assert len(archive.archived) == 1


def test_auto_compaction_checks_input_limit_before_provider_or_archive() -> None:
    calls: list[str] = []
    state = _compaction_source_state()
    store = DigestTokenStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    context_manager = ForcedCompactionContextManager()
    provider = ScriptedProvider()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_input_tokens=1),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "input_token_limit"
    assert provider.calls == []
    assert archive.archived == []
    assert "archive" not in calls
    assert context_manager.plan_compaction_calls == 1
    assert context_manager.build_compaction_calls == 1
    assert not store.locked


def test_auto_compaction_requires_remote_disclosure_before_provider_or_archive() -> None:
    calls: list[str] = []
    state = _compaction_source_state()
    store = DigestTokenStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    context_manager = ForcedCompactionContextManager()
    provider = ScriptedProvider()
    descriptor = ProviderDescriptor(
        family="openai_compatible",
        model="remote-model",
        canonical_destination="https://api.example.com/v1/chat/completions",
        trust_profile="remote-https-v1",
        remote=True,
    )
    runtime = AgentRuntime(
        provider=provider,
        provider_descriptor=descriptor,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.AWAITING_DISCLOSURE
    request = result.state.provider_disclosure_request
    assert request is not None
    # F3：第一批只含 user+assistant facts：披露必须精确描述实际 payload
    # （conversation_history + user_messages + 固定 system 指令）。
    assert request.data_classes == (
        "conversation_history",
        "system_policy",
        "user_messages",
    )
    assert provider.calls == []
    assert archive.archived == []
    assert "archive" not in calls
    assert context_manager.plan_compaction_calls == 1
    assert context_manager.build_compaction_calls == 1
    assert not store.locked


# --------------------------------------------------------------------------- #
# ineligible 历史:未终止段后的新 user 边界不得使下一轮正常对话 fatal
# --------------------------------------------------------------------------- #


def test_ineligible_history_second_message_completes_without_compaction() -> None:
    """user/policy/user 合法 reducer 历史保守不可压缩,但第二次对话必须照常完成。

    第一轮 provider 两次空输出:第一次追加 POLICY_RESULT 修复,第二次耗尽
    修复额度后 failed_fatal invalid_model_output,留下未终止段
    (user_message, policy_result)。第二次 SubmitMessage 追加新的 user 边界后,
    checkpoint 压力真实触发(usage 1024 >= soft 1024):该历史只能映射为
    NO_CANDIDATE 空候选,不得把解析 ValueError 升级为 runtime_failure,
    也不得产生任何压缩副作用。
    """

    calls: list[str] = []
    state = ConversationState.new("conversation-1")
    store = CompactionCountingStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    context_manager = RecordingContextManager()
    provider = ScriptedProvider(
        ModelResponse(()),
        ModelResponse(()),
        ModelResponse(
            (),
            control=DirectResponse(correlation_id="direct-2", text="second reply"),
        ),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    first = runtime.run_turn(_submit(store.state), store.load())

    assert first.status is RunStatus.FAILED_FATAL
    assert first.error_code == "invalid_model_output"
    assert len(provider.calls) == 2
    assert tuple(fact.kind for fact in store.state.facts) == (
        FactKind.USER_MESSAGE,
        FactKind.POLICY_RESULT,
    )

    second = runtime.run_turn(_submit(store.state), store.load())

    # 第二条正常消息走既有路径:完成、回复文本、恰好一次普通 provider 调用。
    assert second.status is RunStatus.COMPLETED
    assert second.message == "second reply"
    assert len(provider.calls) == 3
    # ineligible 分支零压缩副作用:零 summary provider 调用(总调用数即
    # 两次失败 + 一次普通)、零 archive 写、零缩减 CAS、零 build_compaction。
    assert archive.archived == []
    assert "archive" not in calls
    assert store.reduction_cas_calls == 0
    assert context_manager.build_compaction_calls == 0
    # raw facts 全部保留:未终止段与两个 user 边界原样留在 durable state。
    assert tuple(fact.kind for fact in store.state.facts) == (
        FactKind.USER_MESSAGE,
        FactKind.POLICY_RESULT,
        FactKind.USER_MESSAGE,
        FactKind.ASSISTANT_MESSAGE,
    )
    assert not store.locked


def test_plan_compaction_maps_ineligible_history_to_no_candidate() -> None:
    """未终止段 + 新 user 边界:压力触发下只允许 NO_CANDIDATE 空候选,不是错误。"""

    manager = KernelContextManager(
        system_policy="Be concise.",
        limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
    )
    state = ConversationState(
        conversation_id="conversation-1",
        revision=3,
        next_action_seq=4,
        replay_floor=4,
        facts=(
            ConversationFact(
                fact_id="action:1:user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "first"},
            ),
            ConversationFact(
                fact_id="action:2:policy",
                kind=FactKind.POLICY_RESULT,
                content={"code": "invalid_model_output"},
            ),
            ConversationFact(
                fact_id="action:3:user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "second"},
            ),
        ),
    )

    plan = manager.plan_compaction(
        state,
        _submit(state),
        (),
        active_checkpoint_bytes=1_024,
        soft_threshold_bytes=1_024,
    )

    assert plan.trigger is CompactionTrigger.NO_CANDIDATE
    assert plan.removable_fact_ids == ()


# --------------------------------------------------------------------------- #
# V1 真实旅程缺陷回归：审批边界 pause 丢弃 run 后的孤儿 tool 批次
# --------------------------------------------------------------------------- #


def test_pause_at_approval_boundary_keeps_next_run_usable() -> None:
    """审批边界 /pause 丢弃 run 时，R1 在丢 run 的同一 CAS 闭合未开始 suffix。

    形状复刻真实旅程 state-root7：MODEL 批次已入账、审批 pending 时被
    /pause 丢弃 active_run。V1 修复轮曾把闭合推迟到下一个动作；R1 收紧为
    "确定尚未开始的当前 batch suffix 在仍持有 active phase/cursor 的安全
    转换中闭合"：pause 自身补记 durable 非执行结果（cursor 指向未批准的
    call，必未开始），/resume 不再需要代答，推进照常且零压缩副作用。
    """

    calls: list[str] = []
    seed = conversation_with_active_goal()
    state = replace(seed, active_run=ActiveRun(run_id="run-paused"))
    state = start_tool_batch(
        state,
        (
            ToolCall(
                "call-orphan",
                "write_file",
                {"path": "retry_app/service.py", "content": "retry"},
            ),
        ),
    )
    pending = ApprovalRequest(
        request_id="approval-orphan",
        run_id="run-paused",
        tool_call_id="call-orphan",
        binding_digest="binding-orphan",
        preview="write retry_app/service.py",
        tool_name="write_file",
        side_effect=SideEffectClass.WRITE.value,
        egress=EgressClass.NONE.value,
    )
    state = pause_for_approval(state, pending)
    assert state.active_run is not None
    assert state.active_run.status is ActiveRunStatus.AWAITING_APPROVAL

    store = CompactionCountingStore(state, calls)
    archive = RecordingArchive()
    context_manager = RecordingContextManager()
    provider = ScriptedProvider(
        goal_noop_response("resume-supplement"),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="resume-blocked",
                goal_id="goal-1",
                goal_revision=1,
                blocker="no safe action can advance the unchanged Goal after resume",
                safe_attempts=(),
                resume_condition="operator supplies a new instruction",
            ),
        ),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    # /pause：丢 run 的同一转换闭合未开始 suffix（R1：不再留孤儿）。
    paused = runtime.run_turn(
        PauseGoal(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            goal_id="goal-1",
            goal_revision=1,
        ),
        store.load(),
    )

    assert paused.status is RunStatus.COMPLETED
    assert paused.state.active_run is None
    assert paused.state.goal is not None
    assert paused.state.goal.status is GoalStatus.PAUSED
    closed_at_pause = [
        fact
        for fact in paused.state.facts
        if fact.content.get("superseded") is True
    ]
    assert len(closed_at_pause) == 1
    assert closed_at_pause[0].content["tool_call_id"] == "call-orphan"
    assert closed_at_pause[0].content["executed"] is False

    # /resume：批次已在 pause 处闭合，不再产生新的代答结果。
    resumed = runtime.run_turn(
        ResumeGoal(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            goal_id="goal-1",
            goal_revision=1,
        ),
        store.load(),
    )

    assert resumed.status is RunStatus.COMPLETED
    healed = [
        fact
        for fact in resumed.state.facts
        if fact.content.get("superseded") is True
    ]
    assert len(healed) == 1
    assert healed[0].content["tool_call_id"] == "call-orphan"
    assert healed[0].content["executed"] is False
    assert healed[0].content["is_error"] is True

    # 推进输入：修复前这里以 runtime_failure 永久 bricked。
    advanced = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            run_id="run-resumed",
            message="继续当前任务",
        ),
        store.load(),
    )

    assert advanced.status is RunStatus.COMPLETED
    assert advanced.message == (
        "no safe action can advance the unchanged Goal after resume"
    )
    assert len(provider.calls) == 2
    assert advanced.state.goal is not None
    assert advanced.state.goal.status is GoalStatus.BLOCKED
    # ineligible 历史只落 NO_CANDIDATE：零 archive 写、零缩减 CAS、零 build。
    assert archive.calls == []
    assert "archive" not in calls
    assert store.reduction_cas_calls == 0
    assert context_manager.build_compaction_calls == 0
    # 批次已在 pause 处就地闭合，新 user fact 与后续收尾照常追加。
    assert tuple(fact.kind for fact in store.state.facts) == (
        FactKind.USER_MESSAGE,
        FactKind.TOOL_CALLS,
        FactKind.TOOL_RESULT,
        FactKind.USER_MESSAGE,
        FactKind.POLICY_RESULT,
        FactKind.POLICY_RESULT,
    )


def test_accept_action_closes_rejection_prefix_orphan_in_place() -> None:
    """可核实的旧孤儿（拒绝前缀）就地补尾部；不可证形状严格拒绝。

    R1 收窄历史自愈：唯一可核实的旧形状是"同批完整连续 prefix、最后一个为
    Runtime 拒绝审批结果、缺失项全在其后"。ws7 真实形状里批次之后已存在新的
    user fact，尾部追加不闭合批次，必须就地插入。已执行 prefix（无拒绝标记）
    不能证明 suffix 未执行，保持未确定并以冲突拒绝。
    """

    def _orphan_state(prefix_result: ConversationFact) -> ConversationState:
        return ConversationState(
            conversation_id="conversation-1",
            revision=10,
            next_action_seq=8,
            replay_floor=1,
            facts=(
                ConversationFact(
                    fact_id="action:1:user",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "first"},
                ),
                ConversationFact(
                    fact_id="run:run-orphan:tool-batch:10",
                    kind=FactKind.TOOL_CALLS,
                    content={
                        "calls": [
                            {"tool_call_id": "call-1", "name": "write_file", "arguments": {}},
                            {"tool_call_id": "call-2", "name": "write_file", "arguments": {}},
                        ]
                    },
                ),
                prefix_result,
                ConversationFact(
                    fact_id="action:7:user",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "继续当前任务", "control": "goal_correction"},
                ),
            ),
        )

    rejected_prefix = ConversationFact(
        fact_id="run:run-orphan:tool-result:call-1:12",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-1",
            "text": "User rejected the requested tool action.",
            "is_error": True,
            "executed": False,
            "rejected": True,
        },
    )
    transition = accept_action(
        _orphan_state(rejected_prefix),
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=8,
            expected_revision=10,
            run_id="run-resumed",
            message="继续当前任务",
        ),
    )

    assert transition.disposition is ActionDisposition.ACCEPTED
    healed = [
        fact
        for fact in transition.state.facts
        if fact.content.get("superseded") is True
    ]
    assert len(healed) == 1
    assert healed[0].content["tool_call_id"] == "call-2"
    assert healed[0].content["executed"] is False
    fact_ids = [fact.fact_id for fact in transition.state.facts]
    assert fact_ids.index(healed[0].fact_id) == (
        fact_ids.index("run:run-orphan:tool-result:call-1:12") + 1
    )

    # P2-3（2026-10-16 交叉审计补证）：愈合后的状态必须经真实
    # build→context_to_openai_messages 投影出闭合的 wire——孤儿 call-2 由
    # superseded 结果配对，批次不再悬空（投影层端到端，不只检查中间对象）。
    # 无 Goal 态是 intent gate（批次设计性不投影），真实孤儿恢复发生在
    # 任务 Goal 存活时，因此投影用带 Goal 的同一 facts。
    from agent.provider.normalize import context_to_openai_messages
    from tests.continuity.test_contracts import _goal

    goal_state = replace(transition.state, goal=_goal())
    pack = KernelContextManager(
        system_policy="Be concise.",
        limits=ContextLimits(max_input_tokens=100_000, output_reserve=500),
    ).build(
        goal_state,
        SubmitMessage(
            conversation_id=goal_state.conversation_id,
            action_seq=goal_state.next_action_seq,
            expected_revision=goal_state.revision,
            run_id="run-wire-p2-3",
            message="继续当前任务",
        ),
        (),
    )
    wire = context_to_openai_messages(pack)
    tool_call_ids = {
        call["id"]
        for message in wire
        if message["role"] == "assistant"
        for call in message.get("tool_calls", [])
    }
    result_ids = [
        message["tool_call_id"] for message in wire if message["role"] == "tool"
    ]
    assert {"call-1", "call-2"} <= tool_call_ids
    assert sorted(result_ids) == sorted(tool_call_ids), (
        "wire 上 tool_calls 与结果批次不闭合"
    )
    assert fact_ids.index("action:7:user") == fact_ids.index(healed[0].fact_id) + 1

    # 已执行 prefix（无拒绝标记）不能证明 call-2 未执行：严格拒绝，零伪造。
    executed_prefix = ConversationFact(
        fact_id="run:run-orphan:tool-result:call-1:12",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-1",
            "text": "ok",
            "is_error": False,
            "executed": True,
        },
    )
    orphan = _orphan_state(executed_prefix)
    refused = accept_action(
        orphan,
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=8,
            expected_revision=10,
            run_id="run-resumed",
            message="继续当前任务",
        ),
    )

    assert refused.disposition is ActionDisposition.CONFLICT
    assert refused.reason == "unprovable_tool_batch_outcome"
    assert refused.state.facts == orphan.facts
    assert not any(
        fact.content.get("superseded") is True for fact in refused.state.facts
    )


def test_rejection_prefix_healing_requires_strict_rejection_semantics() -> None:
    """R1 窄守卫：末结果必须同时具有严格审批拒绝语义才可补未开始 suffix。

    仅 ``rejected is True`` 不足以证明批次在拒绝处停止：末结果同时声称
    ``executed=True, is_error=False``（矛盾）、带 UNKNOWN 标记、缺字段或使用
    0/1 伪 bool 时，历史是合成损坏形状，不能据此伪造"未执行"尾部。这些形状
    保持原 facts 并以冲突拒绝（零 provider/tool、不补确定未执行）；只有
    ``rejected=True, executed=False, is_error=True`` 且无 UNKNOWN 矛盾的
    正常 Runtime 拒绝结果仍可自愈。
    """

    def _orphan_state(last_result: ConversationFact) -> ConversationState:
        return ConversationState(
            conversation_id="conversation-1",
            revision=10,
            next_action_seq=8,
            replay_floor=1,
            facts=(
                ConversationFact(
                    fact_id="run:run-strict:tool-batch:10",
                    kind=FactKind.TOOL_CALLS,
                    content={
                        "calls": [
                            {"tool_call_id": "call-1", "name": "write_file", "arguments": {}},
                            {"tool_call_id": "call-2", "name": "write_file", "arguments": {}},
                        ]
                    },
                ),
                last_result,
            ),
        )

    def _result(content: dict) -> ConversationFact:
        merged = {
            "tool_call_id": "call-1",
            "text": "stale historical result",
            **content,
        }
        return ConversationFact(
            fact_id="run:run-strict:tool-result:call-1:11",
            kind=FactKind.TOOL_RESULT,
            content=merged,
        )

    def _submit(state: ConversationState) -> Action:
        return SubmitMessage(
            conversation_id="conversation-1",
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-strict-next",
            message="继续当前任务",
        )

    # 对照组：正常 Runtime 拒绝审批结果的严格三字段组合仍可自愈。
    strict_rejection = _result(
        {"rejected": True, "executed": False, "is_error": True}
    )
    orphan = _orphan_state(strict_rejection)
    healed = accept_action(orphan, _submit(orphan))
    assert healed.disposition is ActionDisposition.ACCEPTED
    assert [
        fact.content.get("tool_call_id")
        for fact in healed.state.facts
        if fact.content.get("superseded") is True
    ] == ["call-2"]

    # 前组：末结果 rejected=True 但语义矛盾/UNKNOWN/缺字段/伪 bool——一律拒绝。
    unprovable = {
        "矛盾（同时声称已执行且成功）": {
            "rejected": True,
            "executed": True,
            "is_error": False,
        },
        "UNKNOWN 标记": {
            "rejected": True,
            "executed": False,
            "is_error": True,
            "unknown_outcome": True,
        },
        "缺 executed/is_error 字段": {"rejected": True},
        "executed 伪 bool 0": {
            "rejected": True,
            "executed": 0,
            "is_error": True,
        },
        "is_error 伪 bool 1": {
            "rejected": True,
            "executed": False,
            "is_error": 1,
        },
        "rejected 伪 bool 1": {
            "rejected": 1,
            "executed": False,
            "is_error": True,
        },
    }
    for label, content in unprovable.items():
        state = _orphan_state(_result(content))
        refused = accept_action(state, _submit(state))
        assert refused.disposition is ActionDisposition.CONFLICT, label
        assert refused.reason == "unprovable_tool_batch_outcome", label
        assert refused.state.facts == state.facts, label
        assert not any(
            fact.content.get("superseded") is True
            for fact in refused.state.facts
        ), label


def test_legacy_orphan_matrix_rejects_unprovable_and_heals_only_evidenced() -> None:
    """R1-T7：旧孤儿矩阵——fatal/完成文字/复用 run_id/旧 superseded 都不证明非执行。

    前组形状（`last_safe_result` 存在、fatal 文字、复用 run_id、上一批
    superseded 文案、缺 prefix、已执行 prefix）一律不得伪造成"未执行"且零
    继续（CONFLICT、facts 原样、无 provider/tool）。对照组：同批完整连续
    prefix + 末结果为 Runtime 拒绝审批结果，才允许补尾部。
    """

    def _base_facts() -> tuple[ConversationFact, ...]:
        return (
            ConversationFact(
                fact_id="action:1:user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "first"},
            ),
            ConversationFact(
                fact_id="run:run-legacy:tool-batch:10",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {"tool_call_id": "call-1", "name": "write_file", "arguments": {}},
                        {"tool_call_id": "call-2", "name": "write_file", "arguments": {}},
                    ]
                },
            ),
        )

    def _orphan_state(
        *,
        extra_facts: tuple[ConversationFact, ...] = (),
        last_safe_result: RecordedRunResult | None = None,
    ) -> ConversationState:
        return ConversationState(
            conversation_id="conversation-1",
            revision=10,
            next_action_seq=8,
            replay_floor=1,
            facts=(*_base_facts(), *extra_facts),
            last_safe_result=last_safe_result,
        )

    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=8,
        expected_revision=10,
        run_id="run-legacy",
        message="继续当前任务",
    )

    # 前组 1：last_safe_result 声称 run-orphan 在安全边界完成——旧缺陷据此
    # 把缺结果调用补成 executed=False；R1 后不构成 per-call 证据。
    claimed_safe = _orphan_state(
        last_safe_result=RecordedRunResult(
            status=RunStatus.COMPLETED,
            run_id="run-legacy",
            message="goal paused at a safe boundary",
        )
    )
    refused = accept_action(claimed_safe, action)
    assert refused.disposition is ActionDisposition.CONFLICT
    assert refused.reason == "unprovable_tool_batch_outcome"
    assert refused.state.facts == claimed_safe.facts

    # 前组 2：fatal/完成文字出现在批次后（旧实现把文字当作线索）。
    fatal_tail = ConversationFact(
        fact_id="action:7:policy",
        kind=FactKind.POLICY_RESULT,
        content={"code": "runtime_failure", "message": "fatal: run cleared"},
    )
    refused = accept_action(_orphan_state(extra_facts=(fatal_tail,)), action)
    assert refused.disposition is ActionDisposition.CONFLICT
    assert refused.reason == "unprovable_tool_batch_outcome"

    # 前组 3：上一批 superseded 文案存在（跨批借证明被拒）。
    prior_superseded = ConversationFact(
        fact_id="action:6:prior",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-prior",
            "text": "not executed; superseded",
            "is_error": True,
            "executed": False,
            "superseded": True,
        },
    )
    refused = accept_action(_orphan_state(extra_facts=(prior_superseded,)), action)
    assert refused.disposition is ActionDisposition.CONFLICT
    assert refused.reason == "unprovable_tool_batch_outcome"

    # 前组 4：缺 prefix（直接缺 call-1、只有 call-2 结果）——prefix 不完整。
    partial = ConversationFact(
        fact_id="run:run-legacy:tool-result:call-2:11",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-2",
            "text": "User rejected the requested tool action.",
            "is_error": True,
            "executed": False,
            "rejected": True,
        },
    )
    refused = accept_action(_orphan_state(extra_facts=(partial,)), action)
    assert refused.disposition is ActionDisposition.CONFLICT
    assert refused.reason == "unprovable_tool_batch_outcome"

    # 对照组：完整连续 prefix（call-1 拒绝结果）→ 允许补 call-2 尾部。
    rejection = ConversationFact(
        fact_id="run:run-legacy:tool-result:call-1:11",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-1",
            "text": "User rejected the requested tool action.",
            "is_error": True,
            "executed": False,
            "rejected": True,
        },
    )
    healed = accept_action(_orphan_state(extra_facts=(rejection,)), action)
    assert healed.disposition is ActionDisposition.ACCEPTED
    closed = [
        fact for fact in healed.state.facts if fact.content.get("superseded") is True
    ]
    assert len(closed) == 1
    assert closed[0].content["tool_call_id"] == "call-2"
    assert closed[0].content["executed"] is False


def test_legacy_orphan_matrix_multi_batch_and_malformed_fail_closed() -> None:
    """R1-T8：多批次、跨批同 call_id、重复/畸形结果——不跨批借证明，fail closed。"""

    def _batch(run: str, calls: tuple[str, ...]) -> ConversationFact:
        return ConversationFact(
            fact_id=f"run:{run}:tool-batch:10",
            kind=FactKind.TOOL_CALLS,
            content={
                "calls": [
                    {"tool_call_id": call_id, "name": "write_file", "arguments": {}}
                    for call_id in calls
                ]
            },
        )

    def _result(
        fact_id: str, call_id: str, *, rejected: bool = False
    ) -> ConversationFact:
        return ConversationFact(
            fact_id=fact_id,
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": call_id,
                "text": "rejected" if rejected else "ok",
                "is_error": rejected,
                "executed": not rejected,
                **({"rejected": True} if rejected else {}),
            },
        )

    def _state(facts: tuple[ConversationFact, ...]) -> ConversationState:
        return ConversationState(
            conversation_id="conversation-1",
            revision=10,
            next_action_seq=8,
            replay_floor=1,
            facts=facts,
        )

    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=8,
        expected_revision=10,
        run_id="run-legacy",
        message="继续当前任务",
    )

    # 多批次：batch-A 有可核实拒绝 prefix（可补），batch-B 只有已执行
    # prefix（不可证）→ 整体拒绝，且 batch-A 也不得被部分愈合。
    multi = _state(
        (
            _batch("run-a", ("call-a1", "call-a2")),
            _result("run:run-a:tool-result:call-a1:11", "call-a1", rejected=True),
            _batch("run-b", ("call-b1", "call-b2")),
            _result("run:run-b:tool-result:call-b1:12", "call-b1"),
        )
    )
    refused = accept_action(multi, action)
    assert refused.disposition is ActionDisposition.CONFLICT
    assert refused.reason == "unprovable_tool_batch_outcome"
    assert refused.state.facts == multi.facts
    assert not any(
        fact.content.get("superseded") is True for fact in refused.state.facts
    )

    # 跨批同 call_id：batch-B 的结果引用了 batch-A 的 call-a1（不属于本批）
    # → 结果段被截断，prefix 无法核实，拒绝且零伪造。
    cross = _state(
        (
            _batch("run-a", ("call-a1",)),
            _result("run:run-a:tool-result:call-a1:11", "call-a1", rejected=True),
            _batch("run-b", ("call-b1", "call-b2")),
            _result("run:run-b:tool-result:call-a1:12", "call-a1"),
        )
    )
    refused = accept_action(cross, action)
    assert refused.disposition is ActionDisposition.CONFLICT
    assert refused.reason == "unprovable_tool_batch_outcome"
    assert refused.state.facts == cross.facts

    # 重复结果：同一 call 结果出现两次 → 结果段在第二个处截断，拒绝。
    duplicate = _state(
        (
            _batch("run-a", ("call-a1", "call-a2")),
            _result("run:run-a:tool-result:call-a1:11", "call-a1", rejected=True),
            _result("run:run-a:tool-result:call-a1:12", "call-a1", rejected=True),
        )
    )
    refused = accept_action(duplicate, action)
    assert refused.disposition is ActionDisposition.CONFLICT
    assert refused.reason == "unprovable_tool_batch_outcome"

    # 畸形批次（call 项非 dict）→ 不部分愈合、不代答；fail-closed 由 parser
    # 在消费该历史时保持（compaction 规划直接拒绝），accept 不伪造非执行。
    malformed_batch = ConversationFact(
        fact_id="run:run-bad:tool-batch:10",
        kind=FactKind.TOOL_CALLS,
        content={"calls": ["call-a1"]},
    )
    malformed = _state((malformed_batch,))
    transition = accept_action(malformed, action)
    assert transition.disposition is ActionDisposition.ACCEPTED
    assert not any(
        fact.content.get("superseded") is True for fact in transition.state.facts
    )
    with pytest.raises(ValueError):
        parse_compaction_turns(transition.state.facts)

    # 重复 action/revision 冲突：可核实形状 heal 后仍走既有 replay/revision
    # 保护——重复提交同一 action_seq 不再二次补记。
    rejection = _result(
        "run:run-a:tool-result:call-a1:11", "call-a1", rejected=True
    )
    healable = _state((_batch("run-a", ("call-a1", "call-a2")), rejection))
    accepted = accept_action(healable, action)
    assert accepted.disposition is ActionDisposition.ACCEPTED
    first_closed = [
        fact
        for fact in accepted.state.facts
        if fact.content.get("superseded") is True
    ]
    assert len(first_closed) == 1
    in_progress = accept_action(accepted.state, action)
    assert in_progress.disposition is ActionDisposition.CONFLICT
    assert in_progress.reason == "action_in_progress"
    assert in_progress.state.facts == accepted.state.facts
    finalized = finalize_action(
        accepted.state,
        action_seq=action.action_seq,
        result=RecordedRunResult(
            status=RunStatus.COMPLETED,
            run_id="run-legacy",
        ),
    )
    replayed = accept_action(finalized, action)
    assert replayed.disposition is ActionDisposition.REPLAYED
    assert replayed.state.facts == finalized.facts


# --------------------------------------------------------------------------- #
# 提交顺序与 CAS/crash：archive 已 durable 后 CAS 才由 Runtime 执行
# --------------------------------------------------------------------------- #


class ConflictOnCompactionStore(DigestTokenStore):
    """在 compaction 缩减 CAS 时注入 CheckpointCASConflictError 的 store。

    检测条件是 new_state 携带 CONTEXT_SUMMARY fact：普通 accept/claim CAS
    不会携带它，因此注入点精确对应本批缩减提交。
    """

    def __init__(self, state: ConversationState, calls: list[str]) -> None:
        super().__init__(state, calls)
        self.conflict_snapshot: LoadedSnapshot | None = None
        self.cas_calls: list[tuple[LoadedSnapshot, ConversationState]] = []

    def compare_and_swap(
        self,
        snapshot: LoadedSnapshot,
        new_state: ConversationState,
    ) -> LoadedSnapshot:
        self.cas_calls.append((snapshot, new_state))
        if any(fact.kind is FactKind.CONTEXT_SUMMARY for fact in new_state.facts):
            self._calls.append("cas")
            newest = replace(self.state, revision=self.state.revision + 1)
            self.conflict_snapshot = LoadedSnapshot(newest, "sha256:" + "e" * 64)
            raise CheckpointCASConflictError(
                "injected compaction conflict", self.conflict_snapshot
            )
        return super().compare_and_swap(snapshot, new_state)


def test_compaction_cas_conflict_fails_closed_with_newest_state() -> None:
    """CAS 冲突沿用既有 conflict 路径：不包装、不重试，返回最新 durable state。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = ConflictOnCompactionStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    context_manager = ForcedCompactionContextManager()
    provider = ScriptedProvider(_summary_response)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.CONFLICT
    assert result.error_code == "checkpoint_conflict"
    assert result.state == store.conflict_snapshot.state
    # 提交顺序不变：archive 恰一次且严格先于冲突 CAS；conflict 由 store CAS
    # 自身 fail closed，Runtime 不隐式重试缩减提交。
    assert calls[-2:] == ["archive", "cas"]
    assert calls.count("archive") == 1
    (archived_state, archived_digest, _scope), = archive.archived
    # 归档的是完整 pre-compaction durable current（含原 Submit fact），
    # token 正是本轮缩减提交的 source token。
    assert set(_REMOVABLE_IDS) <= {fact.fact_id for fact in archived_state.facts}
    assert not any(
        fact.kind is FactKind.CONTEXT_SUMMARY for fact in archived_state.facts
    )
    conflict_cas_snapshot = store.cas_calls[-1][0]
    _assert_only_model_attempt_was_recorded(
        archived_state, conflict_cas_snapshot.state
    )
    assert archived_digest != conflict_cas_snapshot.token
    # 原 Submit 的 user fact 仍在最新 durable state 中，未被丢弃。
    user_facts = [
        fact
        for fact in result.state.facts
        if fact.kind is FactKind.USER_MESSAGE and "hello" in str(fact.content)
    ]
    assert len(user_facts) == 1
    assert not store.locked


class CrashOnCompactionStore(DigestTokenStore):
    """在 compaction 缩减 CAS 时抛 SystemExit 模拟进程崩溃（BaseException）。"""

    def __init__(self, state: ConversationState, calls: list[str]) -> None:
        super().__init__(state, calls)
        self.cas_calls: list[tuple[LoadedSnapshot, ConversationState]] = []

    def compare_and_swap(
        self,
        snapshot: LoadedSnapshot,
        new_state: ConversationState,
    ) -> LoadedSnapshot:
        self.cas_calls.append((snapshot, new_state))
        if any(fact.kind is FactKind.CONTEXT_SUMMARY for fact in new_state.facts):
            self._calls.append("cas-crash")
            raise SystemExit(9)
        return super().compare_and_swap(snapshot, new_state)


def test_crash_after_archive_before_cas_keeps_old_state_and_release_lease() -> None:
    """archive durable 之后、CAS 之前崩溃：旧 checkpoint 完整，lease 已释放。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = CrashOnCompactionStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    context_manager = ForcedCompactionContextManager()
    provider = ScriptedProvider(_summary_response)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    with pytest.raises(SystemExit):
        runtime.run_turn(_submit(state), store.load())

    # 崩溃点在 archive 之后：归档已无损写入完整 pre-compaction source。
    assert calls[-2:] == ["archive", "cas-crash"]
    (archived_state, archived_digest, _scope), = archive.archived
    assert set(_REMOVABLE_IDS) <= {fact.fact_id for fact in archived_state.facts}
    assert not any(
        fact.kind is FactKind.CONTEXT_SUMMARY for fact in archived_state.facts
    )
    crash_cas_snapshot = store.cas_calls[-1][0]
    _assert_only_model_attempt_was_recorded(archived_state, crash_cas_snapshot.state)
    assert archived_digest != crash_cas_snapshot.token
    # durable state 未缩减：本批缩减 CAS 零次成功，removable ids 原样保留。
    assert not any(
        fact.kind is FactKind.CONTEXT_SUMMARY for fact in store.state.facts
    )
    assert set(_REMOVABLE_IDS) <= {fact.fact_id for fact in store.state.facts}
    # crash 传播路径同样释放 conversation mutation lease。
    assert not store.locked


# --------------------------------------------------------------------------- #
# 压缩提交前失败：零本批缩减 CAS，原 Submit 不丢，RunResult 与 durable 一致
# --------------------------------------------------------------------------- #


def _submit_user_facts(state: ConversationState) -> tuple[ConversationFact, ...]:
    """durable state 中属于原 Submit 的 user facts（message "hello"）。"""

    return tuple(
        fact
        for fact in state.facts
        if fact.kind is FactKind.USER_MESSAGE and fact.content.get("text") == "hello"
    )


def _assert_only_model_attempt_was_recorded(
    archived: ConversationState,
    accounted: ConversationState,
) -> None:
    """归档源到 provider 前快照之间，只允许新增一次 durable 模型扣账。"""

    assert archived.active_run is not None
    assert accounted.active_run is not None
    assert accounted.revision == archived.revision + 1
    assert (
        accounted.active_run.model_calls_used
        == archived.active_run.model_calls_used + 1
    )
    assert accounted.active_run.input_tokens_used > archived.active_run.input_tokens_used
    normalized = replace(
        accounted,
        revision=archived.revision,
        active_run=replace(
            accounted.active_run,
            model_calls_used=archived.active_run.model_calls_used,
            input_tokens_used=archived.active_run.input_tokens_used,
        ),
    )
    assert normalized == archived


class CompactionCountingStore(DigestTokenStore):
    """只计数缩减提交 CAS（相对 snapshot 新增 CONTEXT_SUMMARY 的 CAS）。

    fail_run/pause 终态落盘会携带已提交批次的 summary，不算缩减提交；
    门禁断言的是“零本批缩减 CAS”，不是整轮零 CAS。
    """

    def __init__(self, state: ConversationState, calls: list[str]) -> None:
        super().__init__(state, calls)
        self.reduction_cas_calls = 0

    def compare_and_swap(
        self,
        snapshot: LoadedSnapshot,
        new_state: ConversationState,
    ) -> LoadedSnapshot:
        snapshot_summary_ids = {
            fact.fact_id
            for fact in snapshot.state.facts
            if fact.kind is FactKind.CONTEXT_SUMMARY
        }
        new_summary_ids = {
            fact.fact_id
            for fact in new_state.facts
            if fact.kind is FactKind.CONTEXT_SUMMARY
        }
        if new_summary_ids - snapshot_summary_ids:
            self.reduction_cas_calls += 1
        return super().compare_and_swap(snapshot, new_state)


class FailingArchive:
    """archive 阶段失败注入。"""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def archive(
        self,
        state: ConversationState,
        *,
        source_checkpoint_digest: str,
        workspace_scope_digest: str,
    ) -> ArchivedConversation:
        self._calls.append("archive")
        raise ArchiveError("archive sink is unavailable")

    def list_archived(self, *, workspace_scope_digest: str):
        raise ArchiveError("archive sink is unavailable")

    def load_archived(self, archive: ArchivedConversation) -> LoadedSnapshot:
        raise ArchiveError("archive sink is unavailable")


def test_compaction_provider_retryable_before_cas_pauses_retryable() -> None:
    """pre-CAS provider 失败沿用现有 FAILED_RETRYABLE/pause 语义，不隐式重试。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = CompactionCountingStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    context_manager = ForcedCompactionContextManager()
    provider = ScriptedProvider(RetryableProviderError("provider is down"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "provider_retryable"
    # 沿用现有可恢复语义：active run 进入 PAUSED_RETRYABLE，等待显式 Resume。
    assert result.state.active_run is not None
    assert result.state.active_run.status is ActiveRunStatus.PAUSED_RETRYABLE
    # provider 恰一次；发送前的 durable 扣账 CAS 成功，失败不退款；
    # accept/claim 与 pause 落盘仍存在，本批缩减 CAS 为零。
    assert len(provider.calls) == 1
    assert result.model_calls_used == 1
    assert result.state.active_run.model_calls_used == 1
    assert store.reduction_cas_calls == 0
    assert calls == ["cas", "cas", "cas", "cas"]
    assert archive.archived == []
    assert not any(
        fact.kind is FactKind.CONTEXT_SUMMARY for fact in store.state.facts
    )
    assert set(_REMOVABLE_IDS) <= {fact.fact_id for fact in store.state.facts}
    # 原 Submit 不丢不重复；RunResult.state 与重新 load 的 durable state 一致。
    assert len(_submit_user_facts(result.state)) == 1
    assert result.state == store.state
    assert not store.locked


def test_compaction_illegal_summary_pauses_retryable_without_reduction() -> None:
    """非法 summary 整条拒绝，但保留 active run 供显式 Resume。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = CompactionCountingStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    context_manager = ForcedCompactionContextManager()
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=DirectResponse(correlation_id="illegal-1", text="not a summary"),
        )
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "compaction_response_invalid"
    assert result.state.active_run is not None
    assert result.state.active_run.status is ActiveRunStatus.PAUSED_RETRYABLE
    assert len(provider.calls) == 1
    # 解析在 archive 之前整条拒绝；发送前扣账保留，本批缩减 CAS 为零。
    assert result.model_calls_used == 1
    assert result.state.active_run.model_calls_used == 1
    assert store.reduction_cas_calls == 0
    assert calls == ["cas", "cas", "cas", "cas"]
    assert archive.archived == []
    assert not any(
        fact.kind is FactKind.CONTEXT_SUMMARY for fact in store.state.facts
    )
    assert set(_REMOVABLE_IDS) <= {fact.fact_id for fact in store.state.facts}
    # 原 Submit 不丢不重复；RunResult.state 与 durable state 一致。
    assert len(_submit_user_facts(result.state)) == 1
    assert result.state == store.state
    assert not store.locked


def test_compaction_archive_failure_pauses_retryable_without_reduction() -> None:
    """archive 失败：零缩减 CAS，保留 active run 供显式 Resume。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = CompactionCountingStore(state, calls)
    archive = FailingArchive(calls)
    context_manager = ForcedCompactionContextManager()
    provider = ScriptedProvider(_summary_response)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "compaction_archive_unavailable"
    assert result.state.active_run is not None
    assert result.state.active_run.status is ActiveRunStatus.PAUSED_RETRYABLE
    # provider 发送前扣账，archive 恰一次且先于任何缩减 CAS；缩减 CAS
    # 为零，最后的 cas 是 fail_run 终态落盘。
    assert result.model_calls_used == 1
    assert result.state.active_run.model_calls_used == 1
    assert store.reduction_cas_calls == 0
    assert calls == ["cas", "cas", "cas", "archive", "cas"]
    assert not any(
        fact.kind is FactKind.CONTEXT_SUMMARY for fact in store.state.facts
    )
    assert set(_REMOVABLE_IDS) <= {fact.fact_id for fact in store.state.facts}
    # 原 Submit 不丢不重复；RunResult.state 与 durable state 一致。
    assert len(_submit_user_facts(result.state)) == 1
    assert result.state == store.state
    assert not store.locked


class TwoBatchContextManager(KernelContextManager):
    """test-only：第一批压缩 turn 1，成功后第二批压缩 turn 2（含旧 summary）。"""

    _BATCHES = (
        ("action:1:user", "action:2:assistant"),
        ("action:3:user", "action:4:assistant"),
    )

    def __init__(self) -> None:
        super().__init__(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=100_000, output_reserve=500),
        )

    def plan_compaction(
        self,
        state: ConversationState,
        action: Action,
        tools: tuple[ToolDefinition, ...],
        *,
        active_checkpoint_bytes: int,
        soft_threshold_bytes: int,
        force: bool = False,
    ) -> CompactionPlanV1:
        report = self.usage(state, action, tools)
        remaining = {fact.fact_id for fact in state.facts}
        turn_ids = next(
            (ids for ids in self._BATCHES if set(ids) <= remaining), ()
        )
        summary_ids = tuple(
            fact.fact_id for fact in state.facts if fact.kind is FactKind.CONTEXT_SUMMARY
        )
        removable = (*summary_ids, *turn_ids) if turn_ids else ()
        return CompactionPlanV1(
            trigger=(
                CompactionTrigger.CHECKPOINT_PRESSURE
                if removable
                else CompactionTrigger.NONE
            ),
            removable_fact_ids=removable,
            usage=report,
            active_checkpoint_bytes=active_checkpoint_bytes,
            soft_threshold_bytes=soft_threshold_bytes,
        )


class FailOnSecondArchive(RecordingSuccessArchive):
    """第一批归档成功，第二批归档失败。"""

    def archive(
        self,
        state: ConversationState,
        *,
        source_checkpoint_digest: str,
        workspace_scope_digest: str,
    ) -> ArchivedConversation:
        if self.archived:
            self._calls.append("archive")
            raise ArchiveError("archive sink is unavailable on the second batch")
        return super().archive(
            state,
            source_checkpoint_digest=source_checkpoint_digest,
            workspace_scope_digest=workspace_scope_digest,
        )


def test_second_batch_provider_failure_keeps_first_batch_and_submit() -> None:
    """第一批已提交的缩减不撤销；第二批失败零缩减 CAS，原 Submit 不丢。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = CompactionCountingStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    context_manager = TwoBatchContextManager()
    provider = ScriptedProvider(
        _summary_response,
        RetryableProviderError("provider is down on the second batch"),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    # 第二批 provider 失败：沿用现有 FAILED_RETRYABLE 语义，不隐式重试。
    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "provider_retryable"
    assert result.state.active_run is not None
    assert result.state.active_run.status is ActiveRunStatus.PAUSED_RETRYABLE
    assert len(provider.calls) == 2
    # 每批 provider 发送前各扣账一次；第一批 archive→CAS 已提交且不
    # 撤销，第二批失败在 archive 之前，本批缩减 CAS 为零。
    assert result.model_calls_used == 2
    assert result.state.active_run.model_calls_used == 2
    assert calls == ["cas", "cas", "cas", "archive", "cas", "cas", "cas"]
    assert store.reduction_cas_calls == 1
    assert len(archive.archived) == 1
    durable = store.state
    assert sum(
        fact.kind is FactKind.CONTEXT_SUMMARY for fact in durable.facts
    ) == 1
    assert not {"action:1:user", "action:2:assistant"} & {
        fact.fact_id for fact in durable.facts
    }
    # 第二批候选 turn 2 原样保留：第二批零缩减 CAS。
    assert {"action:3:user", "action:4:assistant"} <= {
        fact.fact_id for fact in durable.facts
    }
    # 原 Submit 不丢不重复；RunResult.state 与重新 load 的 durable 一致。
    assert len(_submit_user_facts(durable)) == 1
    assert result.state == durable
    assert not store.locked


def test_second_batch_illegal_summary_reports_latest_durable_state() -> None:
    """第二批 summary 非法时，不得用第一批前 snapshot 做失败收尾。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = CompactionCountingStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    provider = ScriptedProvider(
        _summary_response,
        ModelResponse(
            (),
            control=DirectResponse(correlation_id="illegal-2", text="not a summary"),
        ),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=TwoBatchContextManager(),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "compaction_response_invalid"
    assert result.state.active_run is not None
    assert result.state.active_run.status is ActiveRunStatus.PAUSED_RETRYABLE
    assert len(provider.calls) == 2
    assert result.model_calls_used == 2
    assert result.state.active_run.model_calls_used == 2
    assert calls == ["cas", "cas", "cas", "archive", "cas", "cas", "cas"]
    assert store.reduction_cas_calls == 1
    assert len(archive.archived) == 1
    durable = store.state
    assert sum(
        fact.kind is FactKind.CONTEXT_SUMMARY for fact in durable.facts
    ) == 1
    assert {"action:3:user", "action:4:assistant"} <= {
        fact.fact_id for fact in durable.facts
    }
    assert len(_submit_user_facts(durable)) == 1
    assert result.state == durable
    assert not store.locked


def test_second_batch_archive_failure_reports_latest_durable_state() -> None:
    """第二批 archive 失败时，第一批缩减保留且本批不提交。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = CompactionCountingStore(state, calls)
    archive = FailOnSecondArchive(calls)
    provider = ScriptedProvider(_summary_response, _summary_response)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=TwoBatchContextManager(),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "compaction_archive_unavailable"
    assert result.state.active_run is not None
    assert result.state.active_run.status is ActiveRunStatus.PAUSED_RETRYABLE
    assert len(provider.calls) == 2
    assert result.model_calls_used == 2
    assert result.state.active_run.model_calls_used == 2
    assert calls == [
        "cas",
        "cas",
        "cas",
        "archive",
        "cas",
        "cas",
        "archive",
        "cas",
    ]
    assert store.reduction_cas_calls == 1
    assert len(archive.archived) == 1
    durable = store.state
    assert sum(
        fact.kind is FactKind.CONTEXT_SUMMARY for fact in durable.facts
    ) == 1
    assert {"action:3:user", "action:4:assistant"} <= {
        fact.fact_id for fact in durable.facts
    }
    assert len(_submit_user_facts(durable)) == 1
    assert result.state == durable
    assert not store.locked


# --------------------------------------------------------------------------- #
# F4：compaction preflight 的 ContextLimitError 沿用普通 build 的既有终态
# --------------------------------------------------------------------------- #


class _PlanLimitContextManager(KernelContextManager):
    """test-only：plan_compaction preflight 抛真实 ContextLimitError。"""

    def __init__(self) -> None:
        super().__init__(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=100_000, output_reserve=500),
        )

    def plan_compaction(
        self,
        state: ConversationState,
        action: Action,
        tools: tuple[ToolDefinition, ...],
        *,
        active_checkpoint_bytes: int,
        soft_threshold_bytes: int,
        force: bool = False,
    ) -> CompactionPlanV1:
        raise ContextLimitError(
            "pinned context and tool schemas exceed the provider input budget"
        )


class _BuildLimitContextManager(ForcedCompactionContextManager):
    """test-only：plan 保持真实 actionable，build_compaction preflight 抛错。"""

    def build_compaction(
        self,
        state: ConversationState,
        plan: CompactionPlanV1,
        source_checkpoint_digest: str,
    ) -> ContextPack:
        raise ContextLimitError(
            "compaction input exceeds the provider budget; split into smaller batches"
        )


def _assert_conversation_limit_terminal(
    result,
    store: CompactionCountingStore,
    provider: ScriptedProvider,
    archive: RecordingSuccessArchive,
    sink: CollectingSink,
) -> None:
    # 与普通 context build 同型终态：CONVERSATION_LIMIT_REACHED + error.code。
    assert result.status is RunStatus.CONVERSATION_LIMIT_REACHED
    assert result.error_code == "context_core_too_large"
    assert result.state.active_run is None
    assert any(
        event.kind is RuntimeEventKind.LIMIT_REACHED for event in sink.events
    )
    # preflight 失败：零 provider、零 archive、零本批缩减 CAS。
    assert provider.calls == []
    assert archive.archived == []
    assert store.reduction_cas_calls == 0
    # 原 Submit 不丢不重复；durable 与 RunResult 一致；lease 已释放。
    assert len(_submit_user_facts(result.state)) == 1
    assert result.state == store.state
    assert not store.locked


def test_compaction_plan_limit_error_keeps_conversation_limit_terminal() -> None:
    """plan_compaction 抛 ContextLimitError：不得升级为 runtime_failure。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = CompactionCountingStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    provider = ScriptedProvider()
    sink = CollectingSink()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=_PlanLimitContextManager(),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=sink,
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    _assert_conversation_limit_terminal(result, store, provider, archive, sink)


def test_compaction_build_limit_error_keeps_conversation_limit_terminal() -> None:
    """build_compaction 抛 ContextLimitError：同型终态，不触及 provider。"""

    calls: list[str] = []
    state = _compaction_source_state()
    store = CompactionCountingStore(state, calls)
    archive = RecordingSuccessArchive(calls)
    provider = ScriptedProvider()
    sink = CollectingSink()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=_BuildLimitContextManager(),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=sink,
        limits=InvocationLimits(),
        conversation_archive=archive,
    )

    result = runtime.run_turn(_submit(state), store.load())

    _assert_conversation_limit_terminal(result, store, provider, archive, sink)

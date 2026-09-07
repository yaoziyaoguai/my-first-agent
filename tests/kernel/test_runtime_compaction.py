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
from agent.runtime.context import ContextLimitError, ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    Action,
    ActiveRunStatus,
    ArchivedConversation,
    BudgetReport,
    CompactionPlanV1,
    CompactionTrigger,
    ContextPack,
    ConversationFact,
    ConversationState,
    ConversationSummaryV1,
    ConversationWorkspaceBindingV1,
    DirectResponse,
    FactKind,
    LoadedSnapshot,
    ModelResponse,
    ModelTextBlock,
    ProviderDescriptor,
    RunStatus,
    RuntimeEventKind,
    SubmitMessage,
    ToolDefinition,
    canonical_json_digest,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import (
    CheckpointCASConflictError,
    CheckpointUsage,
    RetryableProviderError,
)
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


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
    assert archived_state == conflict_cas_snapshot.state
    assert archived_digest == conflict_cas_snapshot.token
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
    assert archived_state == crash_cas_snapshot.state
    assert archived_digest == crash_cas_snapshot.token
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
    # provider 恰一次；失败发生在 archive/缩减 CAS 之前（accept/claim 与
    # pause 落盘的普通 CAS 仍存在，本批缩减 CAS 为零）。
    assert len(provider.calls) == 1
    assert store.reduction_cas_calls == 0
    assert calls == ["cas", "cas", "cas"]
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
    # 解析在 archive 之前整条拒绝；本批缩减 CAS 为零（第三次 cas 是
    # fail_run 终态落盘，不是缩减提交）。
    assert store.reduction_cas_calls == 0
    assert calls == ["cas", "cas", "cas"]
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
    # archive 恰一次且先于任何缩减 CAS；缩减 CAS 为零（最后的 cas 是
    # fail_run 终态落盘）。
    assert store.reduction_cas_calls == 0
    assert calls == ["cas", "cas", "archive", "cas"]
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
    # 第一批 archive→CAS 已提交且不撤销；第二批失败在 archive 之前，
    # 本批缩减 CAS 为零（整轮缩减 CAS 恰好一次：第一批；末尾 cas 是
    # pause_for_retryable 落盘）。
    assert calls == ["cas", "cas", "archive", "cas", "cas"]
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
    assert calls == ["cas", "cas", "archive", "cas", "cas"]
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
    assert calls == ["cas", "cas", "archive", "cas", "archive", "cas"]
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

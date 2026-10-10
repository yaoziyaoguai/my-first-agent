"""Runtime Kernel 的依赖注入端口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agent.runtime.contracts import (
    Action,
    ApprovalGrant,
    ArchivedConversation,
    BackgroundClaimCheckV1,
    BackgroundClaimVerdictV1,
    BudgetReport,
    CompactionPlanV1,
    ContextPack,
    ContextQuery,
    ContextSourceSnapshot,
    ConversationState,
    ExecutionIntent,
    LoadedSnapshot,
    ModelResponse,
    RuntimeEvent,
    ToolCall,
    ToolDefinition,
    ToolPreparation,
    ToolPrepareContext,
    ToolResult,
)


class RetryableProviderError(RuntimeError):
    """Provider 端口的可重试失败标记，不依赖任何具体 adapter。"""


class InvalidProviderResponseError(RuntimeError):
    """远端响应无法安全归一化；允许 Runtime 做零副作用的有界重试。"""


class CheckpointCASConflictError(RuntimeError):
    """CAS loser 可返回已经在同一次比较中读到的当前 snapshot。"""

    def __init__(self, message: str, current: LoadedSnapshot) -> None:
        self.current = current
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CheckpointUsage:
    """checkpoint 用量/容量的只读度量。

    三个字段都是严格正整数，且 active <= hard、soft <= hard；
    违反不变量的构造一律 ValueError fail closed。
    """

    active_bytes: int
    soft_threshold_bytes: int
    hard_cap_bytes: int

    def __post_init__(self) -> None:
        for name in ("active_bytes", "soft_threshold_bytes", "hard_cap_bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"CheckpointUsage.{name} must be a positive integer")
        if self.active_bytes > self.hard_cap_bytes:
            raise ValueError("active_bytes must not exceed hard_cap_bytes")
        if self.soft_threshold_bytes > self.hard_cap_bytes:
            raise ValueError("soft_threshold_bytes must not exceed hard_cap_bytes")


@runtime_checkable
class ModelDeltaObserver(Protocol):
    """流式增量文本的窄观察合同(r19 小步 3)。

    只承载可公开的回答文本增量:不承载 control JSON、工具参数、usage 或任何
    opaque 推理。observer 是 advisory 通道——丢失、重复或乱序不得影响权威
    ModelResponse 与 durable state;最终响应仍由 provider 一次返回并经
    normalize 唯一接纳。
    """

    def on_text_delta(self, text: str) -> None: ...


@runtime_checkable
class ModelProvider(Protocol):
    def generate(
        self,
        context: ContextPack,
        *,
        delta_observer: ModelDeltaObserver | None = None,
    ) -> ModelResponse:
        """执行一次有限时的模型调用。

        非流式 adapter 忽略 delta_observer(不发现成事件);流式 adapter 只把
        公开回答文本增量转发给 observer,最终 ModelResponse 仍一次返回。
        """


@runtime_checkable
class ContextManager(Protocol):
    def build(
        self,
        state: ConversationState,
        action: Action,
        tools: tuple[ToolDefinition, ...],
    ) -> ContextPack:
        """从规范状态构造不可变且有预算的模型输入。"""

    def usage(
        self,
        state: ConversationState,
        action: Action,
        tools: tuple[ToolDefinition, ...],
    ) -> BudgetReport:
        """只读 no-source 预算投影；供 compaction 规划观察，零副作用。"""

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
        """只读产出压缩决策；不执行移除，也不触碰 source/provider/tool。"""

    def build_compaction(
        self,
        state: ConversationState,
        plan: CompactionPlanV1,
        source_checkpoint_digest: str,
    ) -> ContextPack:
        """为一次已决定的压缩构建专用 ContextPack（纯投影、零副作用）。"""


class RetryableContextSourceError(RuntimeError):
    """source 暂时不可用；ContextManager 在 provider 调用前转为 retryable pause。"""


@runtime_checkable
class ContextSource(Protocol):
    name: str

    def snapshot(self, query: ContextQuery) -> ContextSourceSnapshot:
        """返回一次不可变、revision-consistent 的候选快照。

        不能返回 ModelMessage/ContextPack、标记 pinned/system priority，
        也不能调用 provider/tool/checkpoint/event。
        """


@runtime_checkable
class ToolRuntime(Protocol):
    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回当前组合中模型可见的工具合同。"""

    def prepare(
        self,
        call: ToolCall,
        context: ToolPrepareContext,
        approval: ApprovalGrant | None = None,
    ) -> ToolPreparation:
        """解析、校验和治理调用，但绝不执行 callable。"""

    def invoke(self, intent: ExecutionIntent) -> ToolResult:
        """只执行与已持久化记录完全一致的意图。"""


@runtime_checkable
class BackgroundClaimVerifier(Protocol):
    def verify(self, check: BackgroundClaimCheckV1) -> BackgroundClaimVerdictV1:
        """只读核对 active occurrence claim；不得批准工具或修改任一 store。"""


@runtime_checkable
class CheckpointStore(Protocol):
    def try_acquire(self, conversation_id: str) -> InvocationLease | None:
        """尝试取得一次 invocation 的跨进程 mutation ownership。"""

    def load(self) -> LoadedSnapshot:
        """读取一次不可变状态和 opaque snapshot token。"""

    def compare_and_swap(
        self,
        snapshot: LoadedSnapshot,
        new_state: ConversationState,
    ) -> LoadedSnapshot:
        """仅在 token/revision 仍匹配时提交新状态。"""

    def ensure_capacity(self, snapshot: LoadedSnapshot, *, reserve_bytes: int) -> bool:
        """在 Provider/Tool effect 前为结果、恢复和终态预留持久化空间。"""

    def usage(self, snapshot: LoadedSnapshot) -> CheckpointUsage:
        """只读度量当前 checkpoint 用量与容量；snapshot 过期即按 CAS 冲突 fail closed。"""


@runtime_checkable
class ConversationArchive(Protocol):
    """020：pre-compaction transcript archive 的窄端口。

    只负责两件事：在持有 conversation mutation lease 时以 source checkpoint
    digest 为 identity 幂等写入完整原样状态；以及同 workspace binding 下按
    闭合 identity 精确读取。它不得推进 state、调用 provider/tool，也不得扫描
    transcripts 或 workspaces checkpoint 目录来发现 authority。
    """

    def archive(
        self,
        state: ConversationState,
        *,
        source_checkpoint_digest: str,
        workspace_scope_digest: str,
    ) -> ArchivedConversation:
        """幂等写入完整 pre-compaction 状态；重复同 digest 内容返回同一 archive。"""

    def load_archived_by_identity(
        self,
        *,
        conversation_id: str,
        workspace_scope_digest: str,
        source_checkpoint_digest: str,
    ) -> LoadedSnapshot:
        """按闭合 identity 精确读取；caller 不能提供 filesystem path。"""


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: RuntimeEvent) -> None:
        """尽力交付事件；不得同步重入 Runtime。"""


@runtime_checkable
class InvocationLease(Protocol):
    def release(self) -> None:
        """释放 invocation ownership。"""

"""Runtime Kernel 的依赖注入端口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent.runtime.contracts import (
    Action,
    ApprovalGrant,
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


class CheckpointCASConflictError(RuntimeError):
    """CAS loser 可返回已经在同一次比较中读到的当前 snapshot。"""

    def __init__(self, message: str, current: LoadedSnapshot) -> None:
        self.current = current
        super().__init__(message)


@runtime_checkable
class ModelProvider(Protocol):
    def generate(self, context: ContextPack) -> ModelResponse:
        """执行一次有限时的非流式模型调用。"""


@runtime_checkable
class ContextManager(Protocol):
    def build(
        self,
        state: ConversationState,
        action: Action,
        tools: tuple[ToolDefinition, ...],
    ) -> ContextPack:
        """从规范状态构造不可变且有预算的模型输入。"""


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


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: RuntimeEvent) -> None:
        """尽力交付事件；不得同步重入 Runtime。"""


@runtime_checkable
class InvocationLease(Protocol):
    def release(self) -> None:
        """释放 invocation ownership。"""

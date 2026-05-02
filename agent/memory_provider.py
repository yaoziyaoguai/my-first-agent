"""Stage 3 Slice 6 的 external MemoryProvider seam。

本模块是 fake/provider protocol 边界，不是真实 provider，也 **not an MCP client**。
future MCP resources 可以在后续作为 external memory source 的一种输入形态，但
这里不连接 MCP server、不联网、不读取 token/secret、不做 persistence/retrieval。

Provider 只提供 MemoryCandidate / MemorySnapshot 输入；First Agent 仍必须通过
MemoryPolicy、confirmation UX、operation/audit contract 控制 retain/update/forget。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent.memory_contracts import (
    MemoryCandidate,
    MemoryScope,
    MemorySensitivity,
    MemorySnapshot,
    MemorySnapshotItem,
    MemorySource,
)


class MemoryProviderProtocol(Protocol):
    """MemoryProvider 的最小协议；不包含真实 IO 能力。"""

    provider_name: str

    def list_candidates(self) -> tuple["MemoryProviderCandidate", ...]:
        """返回 provider 候选输入，不做 policy decision。"""

    def get_snapshot(self, *, selection_reason: str) -> MemorySnapshot:
        """返回 provider snapshot 输入，不直接注入 prompt。"""


@dataclass(frozen=True, slots=True)
class MemoryProviderCandidate:
    """外部 provider 提供的候选输入。

    它不是 MemoryRecord，也不是 MemoryDecision。provider_name 可由
    FakeMemoryProvider 在转换为 MemoryCandidate 时补齐，方便单独测试字段默认值。
    """

    content: str
    scope: MemoryScope
    sensitivity: MemorySensitivity
    provenance: str
    reason: str
    proposed_type: str = "external_provider_candidate"
    stability: str = "provider_supplied"
    confidence: float = 0.5
    provider_name: str = ""

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("MemoryProviderCandidate.content 不能为空")
        if not self.provenance.strip():
            raise ValueError("MemoryProviderCandidate.provenance 不能为空")
        if not self.reason.strip():
            raise ValueError("MemoryProviderCandidate.reason 不能为空")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("MemoryProviderCandidate.confidence 必须在 0.0 到 1.0 之间")


@dataclass(frozen=True, slots=True)
class MemoryProviderSnapshotItem:
    """外部 provider 提供的 snapshot 输入项。

    Snapshot item 仍然只是 prompt view 的候选输入，不代表已经批准 recall。
    """

    content: str
    scope: MemoryScope
    sensitivity: MemorySensitivity
    provenance: str
    selection_reason: str
    provider_name: str = ""

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("MemoryProviderSnapshotItem.content 不能为空")
        if not self.provenance.strip():
            raise ValueError("MemoryProviderSnapshotItem.provenance 不能为空")
        if not self.selection_reason.strip():
            raise ValueError("MemoryProviderSnapshotItem.selection_reason 不能为空")


@dataclass(frozen=True, slots=True)
class FakeMemoryProvider:
    """确定性 fake provider，只服务 tests / safe dogfooding。

    它不读取文件、不访问网络、不连接 MCP，只把构造时传入的 fixture 数据投影成
    MemoryCandidate / MemorySnapshot 输入。
    """

    provider_name: str
    candidates: tuple[MemoryProviderCandidate, ...] = field(default_factory=tuple)
    snapshot_items: tuple[MemoryProviderSnapshotItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.provider_name.strip():
            raise ValueError("FakeMemoryProvider.provider_name 不能为空")
        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))
        if not isinstance(self.snapshot_items, tuple):
            object.__setattr__(self, "snapshot_items", tuple(self.snapshot_items))

    def list_candidates(self) -> tuple[MemoryProviderCandidate, ...]:
        """返回确定性候选，不调用外部系统。"""

        return self.candidates

    def to_memory_candidates(self) -> tuple[MemoryCandidate, ...]:
        """把 provider candidate 投影成 MemoryCandidate 输入。

        转换后仍然只是 policy 输入，不是 retain/update/forget decision。
        """

        return tuple(self._to_memory_candidate(candidate) for candidate in self.candidates)

    def get_snapshot(self, *, selection_reason: str) -> MemorySnapshot:
        """返回 MemorySnapshot 输入，不直接注入 prompt。"""

        items = tuple(self._to_snapshot_item(item) for item in self.snapshot_items)
        return MemorySnapshot(
            items=items,
            selection_reason=selection_reason,
            omitted_count=0,
            safety_filter_summary=f"provider:{self.provider_name}:fake-only",
        )

    def _to_memory_candidate(self, candidate: MemoryProviderCandidate) -> MemoryCandidate:
        provider_name = candidate.provider_name or self.provider_name
        source_event = f"provider:{provider_name}:{candidate.provenance}"
        return MemoryCandidate(
            id=f"candidate:{provider_name}:{candidate.provenance}",
            content=candidate.content,
            source=MemorySource.EXTERNAL_PROVIDER,
            source_event=source_event,
            proposed_type=candidate.proposed_type,
            scope=candidate.scope,
            sensitivity=candidate.sensitivity,
            stability=candidate.stability,
            confidence=candidate.confidence,
            reason=candidate.reason,
        )

    def _to_snapshot_item(self, item: MemoryProviderSnapshotItem) -> MemorySnapshotItem:
        provider_name = item.provider_name or self.provider_name
        return MemorySnapshotItem(
            content=item.content,
            scope=item.scope,
            provenance=f"provider:{provider_name}:{item.provenance}",
            selection_reason=item.selection_reason,
            sensitivity=item.sensitivity,
        )

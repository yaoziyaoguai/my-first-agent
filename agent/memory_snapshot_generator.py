"""Stage 5 governed snapshot generation。

本模块是 fake/local store 与 prompt_builder 之间的防火墙：它只把已经确认、
已审计、已应用到 fake store 的 MemoryRecord 过滤成 MemorySnapshot。
它不做 policy decision、不做 confirmation、不写 store、不读取真实历史，也不
输出 prompt 文本。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.memory_contracts import (
    MemoryScope,
    MemorySensitivity,
    MemorySnapshot,
    MemorySnapshotItem,
)
from agent.memory_store import MemoryRecord, MemoryStoreProtocol


@dataclass(frozen=True, slots=True)
class MemorySnapshotBuildOptions:
    """构建 MemorySnapshot 的显式治理参数。

    这些选项是 Stage 5 的最小 selection policy：scope、budget、敏感内容策略都
    必须由调用方显式传入，generator 不自己推断用户意图，也不调用 policy/LLM。
    """

    selection_reason: str
    max_items: int = 5
    scopes: tuple[MemoryScope, ...] = ()
    include_sensitive: bool = False
    rendered_char_budget: int | None = None

    def __post_init__(self) -> None:
        if not self.selection_reason.strip():
            raise ValueError("MemorySnapshotBuildOptions.selection_reason 不能为空")
        if self.max_items <= 0:
            raise ValueError("MemorySnapshotBuildOptions.max_items 必须为正数")
        if not isinstance(self.scopes, tuple):
            object.__setattr__(self, "scopes", tuple(self.scopes))
        if self.rendered_char_budget is not None and self.rendered_char_budget <= 0:
            raise ValueError("MemorySnapshotBuildOptions.rendered_char_budget 必须为正数")


def build_memory_snapshot_from_store(
    store: MemoryStoreProtocol,
    options: MemorySnapshotBuildOptions,
) -> MemorySnapshot:
    """从 fake/local store records 构建 governed MemorySnapshot。

    这是唯一允许的 store-to-snapshot bridge：只读取 `list_records()` 的 in-memory
    视图，不调用 `apply_operation_intent()`，不写 store，也不依赖 prompt_builder。
    """

    records = sorted(store.list_records(), key=_record_sort_key)
    items: list[MemorySnapshotItem] = []
    scope_omitted = 0
    sensitive_omitted = 0
    budget_omitted = 0

    for record in records:
        if not _matches_scope(record, options):
            scope_omitted += 1
            continue
        if _is_sensitive(record) and not options.include_sensitive:
            sensitive_omitted += 1
            continue
        if len(items) >= options.max_items:
            budget_omitted += 1
            continue
        items.append(_snapshot_item_from_record(record, options))

    omitted_count = scope_omitted + sensitive_omitted + budget_omitted
    return MemorySnapshot(
        items=tuple(items),
        selection_reason=options.selection_reason if items else "",
        omitted_count=omitted_count,
        safety_filter_summary=_safety_filter_summary(
            options,
            scope_omitted=scope_omitted,
            sensitive_omitted=sensitive_omitted,
            budget_omitted=budget_omitted,
        ),
        rendered_char_budget=options.rendered_char_budget,
    )


def _record_sort_key(record: MemoryRecord) -> tuple[str, str]:
    """稳定排序，避免 fake dogfooding 的 snapshot 顺序随 dict/fixture 漂移。"""

    scope = record.scope.value if record.scope is not None else ""
    return (record.id, scope)


def _matches_scope(record: MemoryRecord, options: MemorySnapshotBuildOptions) -> bool:
    if not options.scopes:
        return True
    return record.scope in options.scopes


def _is_sensitive(record: MemoryRecord) -> bool:
    return record.sensitive_redacted or "sensitive" in record.safety_summary.lower()


def _snapshot_item_from_record(
    record: MemoryRecord,
    options: MemorySnapshotBuildOptions,
) -> MemorySnapshotItem:
    sensitive = _is_sensitive(record)
    content = "[已隐藏敏感内容]" if sensitive else record.content
    scope = record.scope or MemoryScope.SESSION
    sensitivity = MemorySensitivity.SECRET if sensitive else MemorySensitivity.LOW
    return MemorySnapshotItem(
        content=content,
        scope=scope,
        provenance=f"{record.source_summary}; audit:{record.audit_id}; record:{record.id}",
        selection_reason=(
            f"{options.selection_reason}; audit:{record.audit_id}; "
            f"safety:{record.safety_summary}"
        ),
        sensitivity=sensitivity,
    )


def _safety_filter_summary(
    options: MemorySnapshotBuildOptions,
    *,
    scope_omitted: int,
    sensitive_omitted: int,
    budget_omitted: int,
) -> str:
    scopes = ",".join(scope.value for scope in options.scopes) or "all"
    return (
        "fake-store snapshot generation; "
        f"max_items={options.max_items}; "
        f"scopes={scopes}; "
        f"include_sensitive={options.include_sensitive}; "
        f"scope_omitted={scope_omitted}; "
        f"sensitive_omitted={sensitive_omitted}; "
        f"budget_omitted={budget_omitted}"
    )

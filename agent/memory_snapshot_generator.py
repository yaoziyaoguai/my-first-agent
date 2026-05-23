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
    """从 store records 构建 governed MemorySnapshot。

    这是唯一允许的 store-to-snapshot bridge：只读取 list_records() 视图，
    不调用 apply_operation_intent()，不写 store，不依赖 prompt_builder。

    Snapshot Budget Enforcement (RFC §13.2, Appendix H.4):
    - max 5 items (non-procedural), procedural 全量注入
    - ≤500 chars per item, 超过截断加 … 标记
    - ≤2500 chars total, 超过时从最低优先级移除
    - exclude sensitivity ≥ HIGH
    - T2 记录数 ≤2, 标注 [自动记录]
    """

    records = sorted(store.list_records(), key=_record_sort_key)
    items: list[MemorySnapshotItem] = []
    scope_omitted = 0
    sensitive_omitted = 0
    budget_omitted = 0
    status_omitted = 0  # 排除 rejected/session_only 等非持久状态
    t2_count = 0  # T2 auto_retained 计数器，上限 2

    for record in records:
        # 排除非持久状态：只召回 approved 和 auto_retained records
        if getattr(record, "approval_status", "approved") not in ("approved", "auto_retained"):
            status_omitted += 1
            continue
        if not _matches_scope(record, options):
            scope_omitted += 1
            continue
        if _is_sensitive(record) and not options.include_sensitive:
            sensitive_omitted += 1
            continue
        # T2 预算限制：auto_retained 最多 2 条进 snapshot (Appendix H.4 SB4)
        if getattr(record, "approval_status", "approved") == "auto_retained":
            if t2_count >= 2:
                budget_omitted += 1
                continue
            t2_count += 1
        # 总条数限制：最多 5 条 non-procedural (Appendix H.4 SB1)
        if len(items) >= options.max_items and getattr(record, "memory_type", "") != "procedural":
            budget_omitted += 1
            continue
        # 防御：空 content record 不进 snapshot（MemorySnapshotItem 拒绝空 content）
        if not getattr(record, "content", "").strip():
            budget_omitted += 1
            continue
        items.append(_snapshot_item_from_record(record, options))

    # ── 字符预算强制截断 (RFC §13.2, Appendix H.4 SB2/SB3) ──
    # Per-item: ≤500 chars, 超过截断加 … 标记
    PER_ITEM_CHAR_LIMIT = 500
    TOTAL_CHAR_LIMIT = 2500
    char_truncated = 0

    truncated_items: list[MemorySnapshotItem] = []
    for item in items:
        content = item.content
        if len(content) > PER_ITEM_CHAR_LIMIT:
            content = content[:PER_ITEM_CHAR_LIMIT - 1] + "…"
            char_truncated += 1
        truncated_items.append(MemorySnapshotItem(
            content=content,
            scope=item.scope,
            provenance=item.provenance,
            selection_reason=item.selection_reason,
            sensitivity=item.sensitivity,
        ))
    items = truncated_items

    # Total char budget: ≤2500 chars. 超过时从最低优先级 item 开始移除
    # 移除顺序: 最低 ranking episodic → 低 confidence semantic → 旧 semantic
    total_chars = sum(len(item.content) for item in items)
    while total_chars > TOTAL_CHAR_LIMIT and len(items) > 1:
        # 从末尾移除最低优先级 item (非 procedural 且非最前)
        items.pop()
        total_chars = sum(len(item.content) for item in items)
        budget_omitted += 1
        char_truncated += 1

    omitted_count = status_omitted + scope_omitted + sensitive_omitted + budget_omitted
    return MemorySnapshot(
        items=tuple(items),
        selection_reason=options.selection_reason if items else "",
        omitted_count=omitted_count,
        safety_filter_summary=_safety_filter_summary(
            options,
            status_omitted=status_omitted,
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
    """将 MemoryRecord 转为 snapshot item，标注 governance 状态。

    T2 auto_retained 记录标注 [自动记录] 前缀 (RFC §10.2 可见性锁定,
    Appendix H.3 MC5)。
    """
    sensitive = _is_sensitive(record)
    content = "[已隐藏敏感内容]" if sensitive else record.content
    scope = record.scope or MemoryScope.SESSION
    sensitivity = MemorySensitivity.SECRET if sensitive else MemorySensitivity.LOW

    # T2 auto_retained 可见性标注 (RFC §10.2, G6 fix)
    is_auto = getattr(record, "approval_status", "approved") == "auto_retained"
    prefix = "[自动记录] " if is_auto else ""
    provenance_extra = " auto_retained" if is_auto else ""

    return MemorySnapshotItem(
        content=f"{prefix}{content}",
        scope=scope,
        provenance=(
            f"{record.source_summary}; type:{record.memory_type}; "
            f"audit:{record.audit_id}; record:{record.id}{provenance_extra}"
        ),
        selection_reason=(
            f"{options.selection_reason}; type:{record.memory_type}; "
            f"audit:{record.audit_id}; safety:{record.safety_summary}"
        ),
        sensitivity=sensitivity,
    )


def _safety_filter_summary(
    options: MemorySnapshotBuildOptions,
    *,
    status_omitted: int = 0,
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
        f"status_omitted={status_omitted}; "
        f"scope_omitted={scope_omitted}; "
        f"sensitive_omitted={sensitive_omitted}; "
        f"budget_omitted={budget_omitted}"
    )

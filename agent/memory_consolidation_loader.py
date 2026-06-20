"""Phase 6 — Source Evidence Loader.

只读地从 filesystem memory store 装载 episodic records，转换为 detector 需要
的 EpisodicEvidence 列表。不运行 detector、不写 store、不接 runtime、不调 LLM。

⛔ FROZEN (2026-05-25): 该模块属于 frozen consolidation pipeline。
   参见: docs/audit/global-agent-capability-architecture-audit-2026-05-25.md F4

RFC 参考：
- §15.4 Phase 6 — Consolidation
- §6.1 consolidation lifecycle — 输入是 episodic records
- Appendix D.4 — consolidation 不修改/不删除源 episodic
- W4 consolidation input evidence — 从 store 读 episodic 供 consolidation 使用

架构边界：
- 输入: FilesystemMemoryStore（通过公开 list_records/get_record API）
- 输出: SourceEvidenceLoadResult（evidence + skipped_count + warnings）
- 只读：不调用 store 的任何写方法
- 不 import detector / runtime / confirmation / policy 模块
- 不调用 LLM
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.memory_consolidation import EpisodicEvidence

# ── 过滤规则常量 ─────────────────────────────────────────────────────────────

# 不应进入 consolidation 的 approval_status 值
_EXCLUDED_APPROVAL_STATUSES: frozenset[str] = frozenset({
    "rejected",   # 已被用户拒绝的候选
    "pending",    # 尚未完成 T1/T2 确认的 proposal
})

# 不应进入 consolidation 的 transient approval_status
_TRANSIENT_APPROVAL_STATUSES: frozenset[str] = frozenset({
    "session_only",  # USE_ONCE：仅当次会话有效
})

# 不应进入 consolidation 的 stability 值
_EPHEMERAL_STABILITY: frozenset[str] = frozenset({
    "ephemeral",  # transient / 一次性记忆
})


# ── 加载结果 ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SourceEvidenceLoadResult:
    """Phase 6 source evidence loader 的只读装载结果。

    装载阶段不运行 detector，不生成 ConsolidationCandidate，不写 store。
    """

    evidence: tuple[EpisodicEvidence, ...]
    skipped_count: int
    warnings: tuple[str, ...]

    @property
    def total_loaded(self) -> int:
        """成功转换为 EpisodicEvidence 的记录数。"""
        return len(self.evidence)

    @property
    def total_seen(self) -> int:
        """总共扫描到的记录数（evidence + skipped）。"""
        return self.total_loaded + self.skipped_count


# ── 过滤逻辑 ─────────────────────────────────────────────────────────────────


def _should_skip(record) -> tuple[bool, str | None]:
    """判断一条 MemoryRecord 是否应被 consolidation loader 跳过。

    Args:
        record: MemoryRecord 实例。

    Returns:
        (skip, reason) — skip 为 True 表示跳过，reason 为跳过原因。
    """
    # 1. 只加载 episodic 类型（RFC §6.1：consolidation 只消费 episodic）
    memory_type = getattr(record, "memory_type", None)
    if memory_type != "episodic":
        return True, f"memory_type={memory_type}，非 episodic，跳过"

    # 2. 过滤 rejected / pending（未被确认或已被拒绝的候选不应进入 consolidation）
    approval_status = getattr(record, "approval_status", None)
    if approval_status in _EXCLUDED_APPROVAL_STATUSES:
        return True, f"approval_status={approval_status}，不应进入 consolidation"

    # 3. 过滤 transient（use_once / session_only 的 transient 记忆）
    if approval_status in _TRANSIENT_APPROVAL_STATUSES:
        return True, f"approval_status={approval_status}，transient 记忆，跳过"

    # 4. 过滤 ephemeral stability（一次性/短期记忆）
    stability = _get_metadata_field(record, "stability")
    if stability in _EPHEMERAL_STABILITY:
        return True, f"stability={stability}，ephemeral 记忆，跳过"

    # 5. 过滤敏感/涉密记录（sensitive_redacted 为 True）
    sensitive = getattr(record, "sensitive_redacted", False)
    if sensitive is True:
        return True, "sensitive_redacted=True，敏感记录不进入语义沉淀"

    # 6. 过滤空 content
    content = getattr(record, "content", "")
    if not content or not content.strip():
        return True, "content 为空"

    return False, None


# ── 字段映射 ─────────────────────────────────────────────────────────────────


def _to_episodic_evidence(record) -> EpisodicEvidence:
    """将一条 MemoryRecord 转换为 EpisodicEvidence。

    映射规则（只读，不修改原始 record）：
    - record_id ← record.id
    - content ← record.content
    - scope ← str(record.scope) 或 None
    - created_at ← metadata.created_at 或 None
    - confidence ← metadata.confidence 或 None
    - tags ← metadata.tags（如果存在且非空）
    """
    scope_str: str | None = None
    scope = getattr(record, "scope", None)
    if scope is not None:
        # MemoryScope 等枚举类型通过 .value 获取字符串值
        scope_str = str(scope.value) if hasattr(scope, "value") else str(scope)

    created_at = _get_metadata_field(record, "created_at")
    confidence = _get_metadata_field(record, "confidence")

    # tags：优先从 metadata 提取，支持 list/tuple 和逗号分隔字符串
    tags: tuple[str, ...] = ()
    raw_tags = _get_metadata_field(record, "tags")
    if raw_tags is not None:
        if isinstance(raw_tags, (list, tuple)):
            tags = tuple(str(t).strip() for t in raw_tags if t)
        elif isinstance(raw_tags, str) and raw_tags.strip():
            # 逗号分隔的字符串（filesystem 中 YAML frontmatter 的常见格式）
            parts = [t.strip() for t in raw_tags.split(",") if t.strip()]
            tags = tuple(parts) if parts else (raw_tags.strip(),)

    # confidence 必须是 float 或 None
    if confidence is not None and not isinstance(confidence, (int, float)):
        confidence = None

    return EpisodicEvidence(
        record_id=str(record.id),
        content=str(record.content),
        scope=scope_str,
        created_at=str(created_at) if created_at else None,
        confidence=float(confidence) if confidence is not None else None,
        tags=tags,
    )


def _get_metadata_field(record, key: str):
    """从 record 的 metadata dict 安全获取字段，不抛异常。

    兼容 metadata 为 None 或非 dict 的情况。
    """
    metadata = getattr(record, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    return metadata.get(key)


# ── 公开 API ─────────────────────────────────────────────────────────────────


def load_episodic_evidence(
    store,
    *,
    max_items: int | None = None,
) -> SourceEvidenceLoadResult:
    """从 filesystem store 装载 episodic evidence。

    只读操作：调用 store.list_records() 获取所有记录，
    过滤非 episodic / rejected / pending / transient / sensitive 记录，
    转换为 EpisodicEvidence。

    Args:
        store: FilesystemMemoryStore 实例（需要支持 list_records() 公开 API）。
        max_items: 最大返回 evidence 数量，None 表示不限制。

    Returns:
        SourceEvidenceLoadResult:
        - evidence: 成功转换的 EpisodicEvidence 元组
        - skipped_count: 被跳过的记录数
        - warnings: 跳过原因列表（不含敏感信息）

    Raises:
        TypeError: store 不支持 list_records() API。
    """
    if not hasattr(store, "list_records"):
        raise TypeError(
            f"store 必须支持 list_records() API，当前类型 {type(store).__name__} 不支持"
        )

    evidence_list: list[EpisodicEvidence] = []
    warnings: list[str] = []
    skipped = 0

    try:
        records = store.list_records()
    except Exception as exc:
        return SourceEvidenceLoadResult(
            evidence=(),
            skipped_count=0,
            warnings=(f"store.list_records() 调用失败: {exc}",),
        )

    for record in records:
        should_skip, reason = _should_skip(record)

        if should_skip:
            skipped += 1
            if reason:
                # warning 只记录 record_id 和原因，不泄露完整 content
                rid = getattr(record, "id", "?")
                warnings.append(f"[{rid}] {reason}")
            continue

        try:
            evidence_list.append(_to_episodic_evidence(record))
        except Exception as exc:
            skipped += 1
            rid = getattr(record, "id", "?")
            warnings.append(f"[{rid}] 转换为 EpisodicEvidence 失败: {exc}")
            continue

        if max_items is not None and len(evidence_list) >= max_items:
            break

    return SourceEvidenceLoadResult(
        evidence=tuple(evidence_list),
        skipped_count=skipped,
        warnings=tuple(warnings),
    )

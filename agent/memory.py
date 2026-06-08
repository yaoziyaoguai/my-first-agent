import json
import re
from hashlib import sha256

from agent.logger import log_event, make_serializable
from agent.memory_contracts import MemorySensitivity, MemorySnapshot, MemorySnapshotItem
from agent.memory_runtime_hooks import (
    _active_records_for_emergence,  # noqa: F401 - 兼容旧测试/审计猴子补丁锚点
    _load_emergence_correction_evidence,  # noqa: F401 - 同上，运行逻辑已迁到 hooks
    _maybe_run_consolidation,
    _maybe_run_emergence,
)
from config import MAX_MESSAGE_CHARS, MAX_MESSAGES, MODEL_NAME

_WORKING_SUMMARY_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)\b(api[_-]?key|password|secret|token|credential)\s*[:=]\s*[^\s,;]+"
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
        "Bearer [REDACTED]",
    ),
    (
        re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}\b"),
        "[REDACTED_SECRET]",
    ),
)


def redact_working_summary(summary: str | None) -> tuple[str | None, bool]:
    """对 session scratchpad 摘要做最小 secret-like 脱敏。

    `working_summary` 会进入 checkpoint 和后续 prompt，但它不是长期用户记忆。
    这里不做语义改写，只移除常见可逆 credential 片段，避免压缩摘要把 secret
    样式内容带入恢复链路。
    """
    if not summary:
        return summary, False
    redacted = summary
    for pattern, replacement in _WORKING_SUMMARY_SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted, redacted != summary


def record_working_summary_event(
    event_type: str,
    *,
    reason: str,
    summary: str | None = None,
    count: int | None = None,
) -> None:
    """通过内置 evidence 体系记录 `working_summary` lifecycle 事件。"""
    try:
        from agent.evidence_recorder import record_memory_evidence

        record_memory_evidence(
            event_type=event_type,
            operation="summarize",
            phase="end",
            status="success",
            source_type="hidden_summary",
            decision="allowed",
            reason=reason,
            count=count,
            raw_fields={"content": summary or ""},
        )
    except Exception:
        # 摘要 evidence 失败不能阻断主对话或 checkpoint restore。
        pass


def set_working_summary_scratchpad(
    state,
    summary: str | None,
    *,
    reason: str,
) -> str | None:
    """设置 session scratchpad 摘要并记录安全 lifecycle evidence。

    这是 `working_summary` 的写入/清理 owner。它只修改 `state.memory`
    scratchpad，不写 MemoryStore，不创建 MemoryRecord，也不代表用户长期记忆。
    """
    previous = getattr(state.memory, "working_summary", None)
    safe_summary, was_redacted = redact_working_summary(summary)
    if safe_summary == previous:
        if was_redacted:
            record_working_summary_event(
                "memory.summary_redacted",
                reason=reason,
                summary=summary,
                count=1,
            )
        return safe_summary

    state.memory.working_summary = safe_summary
    if was_redacted:
        record_working_summary_event(
            "memory.summary_redacted",
            reason=reason,
            summary=summary,
            count=1,
        )
    if safe_summary:
        event_type = "memory.summary_updated" if previous else "memory.summary_created"
        record_working_summary_event(
            event_type,
            reason=reason,
            summary=safe_summary,
            count=1,
        )
    elif previous:
        record_working_summary_event(
            "memory.summary_cleared",
            reason=reason,
            summary=previous,
            count=0,
        )
    return safe_summary


def estimate_messages_size(messages):
    try:
        serializable = make_serializable(messages)
        return len(json.dumps(serializable, ensure_ascii=False))
    except Exception as e:
        print(f"[系统] 估算 messages 大小时出错: {e}")
        return 0


def _truncate_tool_result_content(obj, threshold=200, keep_prefix=200):
    if isinstance(obj, list):
        return [_truncate_tool_result_content(item, threshold, keep_prefix) for item in obj]
    if isinstance(obj, dict):
        new_obj = {}
        is_tool_result = obj.get("type") == "tool_result"
        for k, v in obj.items():
            if is_tool_result and k == "content":
                content_text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                if len(content_text) > threshold:
                    content_text = content_text[:keep_prefix] + "...(已截断)"
                new_obj[k] = content_text
            else:
                new_obj[k] = _truncate_tool_result_content(v, threshold, keep_prefix)
        return new_obj
    return obj


def _collect_tool_use_ids(messages) -> set:
    """收集 messages 里 assistant 端声明过的 tool_use id。"""
    ids = set()
    for m in messages:
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                bid = block.get("id")
                if bid:
                    ids.add(bid)
    return ids


def _collect_tool_result_ids(messages) -> set:
    """收集 messages 里 user 端回传的 tool_result 对应的 tool_use_id。"""
    ids = set()
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                bid = block.get("tool_use_id")
                if bid:
                    ids.add(bid)
    return ids


def _find_safe_split_index(messages, preferred_recent: int) -> int:
    """计算一个不切断 tool_use/tool_result 配对的切分点。

    返回 split_index：messages[:split_index] 归摘要，messages[split_index:]
    保留为 recent。若找不到合法切点（例如所有 tool_use/result 穿插太深），
    返回 0，表示本次不做压缩。
    """
    n = len(messages)
    if preferred_recent >= n:
        return 0

    split = n - preferred_recent

    # 把 split 向前推，直到 recent 部分里不存在「对应 tool_use 不在 recent 里」的孤悬 tool_result，
    # 也不存在「对应 tool_result 不在 recent 里」的孤悬 tool_use。
    max_iter = n  # 防止死循环
    for _ in range(max_iter):
        if split <= 0:
            return 0

        recent = messages[split:]
        recent_tool_uses = _collect_tool_use_ids(recent)
        recent_tool_results = _collect_tool_result_ids(recent)

        # recent 里有 tool_result 但对应 tool_use 不在 recent —— 需要把 tool_use 也拉进 recent
        orphan_results = recent_tool_results - recent_tool_uses
        # recent 里有 tool_use 但对应 tool_result 不在 recent —— 同样要扩大 recent
        orphan_uses = recent_tool_uses - recent_tool_results

        if not orphan_results and not orphan_uses:
            return split

        split -= 1  # 把 split 再向前一步，把更多消息纳入 recent

    return 0  # 兜底：放弃压缩


def compress_history(
    messages,
    client,
    existing_summary: str | None = None,
    max_recent_messages: int = 6,
):
    """
    检查并压缩消息历史。

    参数:
        messages: 当前原始对话消息
        client: LLM client
        existing_summary: 之前已有的摘要，可为空
        max_recent_messages: 最近保留多少条原始消息不压缩

    返回:
        (new_messages, new_summary)
        - new_messages: 压缩后保留的原始消息（只保留最近消息）
        - new_summary: 最新摘要（单独存，不再塞回 messages）
    """
    total_size = estimate_messages_size(messages)

    if len(messages) <= MAX_MESSAGES and total_size <= MAX_MESSAGE_CHARS:
        return messages, existing_summary

    print(
        f"\n[系统] 上下文较长，正在压缩历史记录..."
        f"（message_count={len(messages)}, total_chars={total_size}）"
    )
    log_event("context_compression_start", {
        "message_count": len(messages),
        "total_chars": total_size,
    })

    recent = messages[-max_recent_messages:]
    old = messages[:-max_recent_messages]

    # 防护：切分点不能切断 tool_use / tool_result 的配对。
    # 否则压缩后 recent 里会留下孤悬 tool_result（对应 tool_use 已进摘要），
    # 或孤悬 tool_use（对应 tool_result 已进摘要），下次调用 API 必然报错。
    safe_split = _find_safe_split_index(messages, max_recent_messages)
    if safe_split == 0:
        print("[系统] 压缩放弃：找不到不切断 tool_use/tool_result 的切点。")
        return messages, existing_summary
    old = messages[:safe_split]
    recent = messages[safe_split:]

    old_for_summary = make_serializable(old)
    old_for_summary = _truncate_tool_result_content(
        old_for_summary, threshold=200, keep_prefix=200
    )

    if existing_summary:
        summary_prompt = (
            "下面有两部分内容：\n"
            "1. 之前的历史摘要\n"
            "2. 新增的旧消息\n\n"
            "请把它们整合成一份新的中文摘要，保留关键信息，包括："
            "完成了什么任务、重要结论、用户偏好、当前进度。\n"
            "只输出摘要，不要多余的话。\n\n"
            f"【之前的历史摘要】\n{existing_summary}\n\n"
            f"【新增的旧消息】\n{json.dumps(old_for_summary, ensure_ascii=False)}"
        )
    else:
        summary_prompt = (
            "请用中文简要总结以下对话历史的关键信息，包括："
            "完成了什么任务、重要的结论、用户的偏好、当前进度。"
            "只输出总结，不要多余的话。\n\n"
            f"对话历史：\n{json.dumps(old_for_summary, ensure_ascii=False)}"
        )

    summary_response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": summary_prompt,
            }
        ],
    )

    summary_text = existing_summary
    for block in summary_response.content:
        if block.type == "text":
            summary_text = block.text
            break

    new_total_size = estimate_messages_size(recent)

    print(
        f"[系统] 压缩完成：{len(messages)} 条 → {len(recent)} 条，"
        f"{total_size} 字符 → {new_total_size} 字符\n"
    )

    return recent, summary_text


def _render_snapshot_item(item: MemorySnapshotItem) -> str:
    """把已批准 snapshot item 渲染成 prompt 行。

    这里仍然只是 prompt view formatting：不做 retrieval、不做 policy、不读 store。
    HIGH/SECRET 内容默认用过滤提示代替，避免 prompt_builder 路径泄漏敏感正文。
    """

    if item.sensitivity in {MemorySensitivity.HIGH, MemorySensitivity.SECRET}:
        content = "[已过滤敏感记忆]"
    else:
        content = item.content
    return (
        f"- [{item.scope.value}] {content} "
        f"(source: {item.provenance}; reason: {item.selection_reason})"
    )


def _render_memory_snapshot(snapshot: MemorySnapshot) -> str:
    """渲染 MemorySnapshot；预算只限制 item 行，不限制说明性 header。"""

    lines = [
        "--- Memory ---",
        "Approved memory snapshot:",
        f"Selection reason: {snapshot.selection_reason}",
    ]
    used_chars = 0
    omitted_by_budget = 0

    for item in snapshot.items:
        line = _render_snapshot_item(item)
        line_len = len(line)
        if (
            snapshot.rendered_char_budget is not None
            and used_chars + line_len > snapshot.rendered_char_budget
        ):
            omitted_by_budget += 1
            continue
        lines.append(line)
        used_chars += line_len

    omitted_total = snapshot.omitted_count + omitted_by_budget
    if omitted_total:
        lines.append(f"- [omitted] {omitted_total} memory item(s) omitted.")
    if snapshot.safety_filter_summary:
        lines.append(f"Safety filter: {snapshot.safety_filter_summary}")

    lines.append("--- End Memory ---")

    return "\n".join(lines)


def build_memory_section(snapshot: MemorySnapshot | None = None) -> str:
    """
    构造 system prompt 中使用的 memory section。

    当前默认仍提供一个最小可用版本：
    - 不把 working_summary 混进这里
    - 没有 snapshot 时只返回稳定、静态的 memory 说明占位
    - 有 snapshot 时只渲染已批准 prompt 视图，不做 policy/retrieval/store IO

    后续如果要接长期记忆，再在这里扩展。
    """
    if snapshot is not None and snapshot.items:
        return _render_memory_snapshot(snapshot)
    return "--- Memory ---\n当前未注入长期记忆。\n--- End Memory ---"


def init_memory() -> None:
    """
    初始化 memory 模块。

    当前先保留最小兼容实现：
    - 不做额外初始化
    - 只保证 session 启动链路可运行
    """
    return None



def cleanup_old_episodes() -> None:
    """
    清理旧的记忆片段。

    当前先保留最小兼容实现：
    - 不做实际清理
    - 后续如果接长期记忆再扩展
    """
    return None



def _safe_memory_root_metadata(root: object | None) -> dict[str, object]:
    """Return evidence-safe metadata for a durable memory root.

    The raw filesystem path is deliberately not returned. Session/runtime
    summaries can carry these fields across boundaries without leaking tmp,
    HOME, or absolute paths into evidence/log output.
    """
    if root is None:
        return {
            "root_redacted": True,
            "root_kind": "none",
            "path_kind": "none",
        }
    from agent.evidence_recorder import build_safe_path_metadata

    raw = str(root)
    path_metadata = build_safe_path_metadata(raw)
    return {
        "root_hash": f"memroot:{sha256(raw.encode('utf-8')).hexdigest()[:16]}",
        "path_hash": path_metadata.get("path_hash", ""),
        "root_kind": path_metadata.get("path_kind", "unknown"),
        "path_kind": path_metadata.get("path_kind", "unknown"),
        "root_redacted": True,
    }


def _attach_store_summary_metadata(summary: dict, store, backend: str) -> None:
    """Attach backend/root metadata without exposing raw filesystem paths."""
    summary["store_backend"] = backend
    if hasattr(store, "root_dir"):
        summary.update(_safe_memory_root_metadata(getattr(store, "root_dir", None)))
    else:
        summary.update(_safe_memory_root_metadata(None))


def extract_memories_from_session(
    messages,
    client,
    model_name,
    *,
    store=None,
) -> dict:
    """W3 Session-End Extraction Skeleton — 从会话 transcript 提取 episodic candidate。

    ⚠️ Phase 5a skeleton path：当前通过 create_extractor("fake", ...) factory seam
    使用确定性关键词匹配的 FakeMemoryExtractor 进行 pipeline validation。
    这不代表真实 LLM extraction quality 已验证。
    后续 L2 替换为 LLMMemoryExtractor 时，只需将 factory 的 extractor_type 改为
    "llm"；governance routing 和 persistence 逻辑不变（factory + extract 接口一致）。
    Fake 不定义 lifecycle / governance / persistence 语义。

    Lifecycle 位置（RFC §3.1）：
      Interaction → Extraction（本函数）→ Episodic → Consolidation → ...

    Governance Routing（RFC §10.4, §5.3）：
      - episodic + confidence [0.6, 0.8) → T2 auto_retain → 写入 store
      - episodic + confidence ≥0.8 → T1 pending（持久化到 _pending/，待人类 review）
      - confidence <0.6 → T3 ignore
      - non-episodic（semantic/procedural）→ T1（session-end 不产出这些类型）

    Extraction ≠ Persistence（Appendix G.1）：
      提取器只产出 candidate，governance routing 后才写入 store。

    Args:
        messages: 本次 session 的完整对话消息列表
        client: LLM client（skeleton 阶段不使用，预留给 L2 LLM extraction）
        model_name: 模型名称（skeleton 阶段不使用）
        store: 可选注入的 MemoryStoreProtocol。None 时按 MEMORY_STORE_BACKEND 创建。

    Returns:
        extraction_summary dict，包含审计观察字段（供 dogfood 分析）：
        - total_messages: 输入消息数
        - total_proposals: 提取到的 proposal 总数
        - t2_auto_retained: T2 自动保留数
        - t1_pending: T1 待确认数
        - t3_ignored: T3 丢弃数
        - dedup_hits: 与已有 store 重复的 proposal 数
        - errors: 提取过程中的错误列表
        - false_positives_note: 疑似 false positive 的 observation note
    """
    import os as _os

    from agent.memory_confirmation import (
        MemoryConfirmationChoice,
        MemoryConfirmationStatus,
    )
    from agent.memory_contracts import (
        MemoryDecisionType,
        MemoryScope,
    )
    from agent.memory_extraction import (
        ExtractionInput,
        create_extractor,
    )
    from agent.memory_extraction_bridge import (
        proposal_to_candidate,
    )
    from agent.memory_operations import (
        MemoryOperationIntent,
        MemoryOperationType,
        build_memory_audit_summary,
    )
    from agent.memory_store import (
        MemoryStoreApplyStatus,
        find_duplicate_record,
    )

    # ── 初始化返回结构 ──────────────────────────────────────────────────
    summary = {
        "total_messages": len(messages),
        "total_proposals": 0,
        "t2_auto_retained": 0,
        "t1_pending": 0,
        "t3_ignored": 0,
        "dedup_hits": 0,
        "errors": [],
        "false_positives_note": "",
    }
    t1_proposals: list[dict] = []  # T1 pending proposals，循环结束后持久化

    # ── 创建 store ──────────────────────────────────────────────────────
    # store_backend / safe root metadata 注入 summary，供 dogfood 可见性审计。
    # session.py 不直接查询 store 内部；summary 是唯一的跨边界信息载体。
    # 这里不能暴露 raw filesystem root；只传 hash/kind/redacted metadata。
    if store is None:
        backend = _os.getenv("MEMORY_STORE_BACKEND", "memory").strip()
        if backend in ("memory", "in_memory", "inmemory"):
            from agent.memory_store import InMemoryMemoryStore
            store = InMemoryMemoryStore()
            _attach_store_summary_metadata(summary, store, backend)
        elif backend in ("filesystem", "memory_fs", "fs"):
            from agent.memory_fs_store import FilesystemMemoryStore, resolve_configured_memory_root

            root = resolve_configured_memory_root()
            if root is None:
                summary["store_backend"] = backend
                summary.update(_safe_memory_root_metadata(None))
                summary["errors"].append("durable_memory_root_not_configured")
                return summary
            store = FilesystemMemoryStore(root_dir=root)
            _attach_store_summary_metadata(summary, store, backend)
        else:
            summary["errors"].append(
                f"不支持的 MEMORY_STORE_BACKEND: {backend!r}"
            )
            summary["store_backend"] = backend
            summary.update(_safe_memory_root_metadata(None))
            return summary
    else:
        # store 被显式注入 → 从 store 实例推断 backend 信息
        store_cls_name = type(store).__name__
        backend = "filesystem" if "Filesystem" in store_cls_name else "memory"
        _attach_store_summary_metadata(summary, store, backend)

    # ── 构造 transcript（过滤 system 消息，保留 user/assistant）─────────
    transcript = [
        {"role": m.get("role", "user"), "content": _msg_content_for_extraction(m)}
        for m in messages
        if m.get("role") in ("user", "assistant")
    ]
    if not transcript:
        summary["errors"].append("transcript 为空，无可提取内容")
        return summary

    # ── Extraction：通过 factory seam 创建 extractor ──────────────────
    # 默认 "fake"（skeleton safe path），不调用真实 LLM。
    # 真实 LLM extraction 需显式 opt-in：MEMORY_EXTRACTION_REAL_LLM=1。
    # 此 gate 与 run_extraction_review_cli() 的 opt-in 保持一致，
    # 确保 controlled dogfood 外不触发真实 LLM 调用。
    # Fake 不定义 lifecycle / governance / persistence 语义。
    _use_real_llm = _os.getenv("MEMORY_EXTRACTION_REAL_LLM", "").strip() in (
        "1", "true", "yes",
    )
    _extractor_type = "llm" if _use_real_llm else "fake"
    try:
        extractor = create_extractor(
            _extractor_type,
            min_confidence=0.6,
            min_importance=3,
        )
        extraction_input = ExtractionInput(
            transcript=transcript,
            session_metadata={"source": "session_end_extraction"},
        )
        result = extractor.extract(extraction_input)
    except Exception as exc:
        summary["errors"].append(f"extraction 失败: {exc}")
        return summary

    proposals = list(result.proposals)
    summary["total_proposals"] = len(proposals)
    # 传播 extractor 的 extraction_summary 到 summary dict，
    # 用于最终展示的可见性（真实 LLM 的 model name / proposal 计数等）。
    if hasattr(result, "extraction_summary") and result.extraction_summary:
        summary["extraction_summary"] = result.extraction_summary

    # ── W3 Session-End 类型约束（RFC §11.4 + Appendix G.2 LB1）──────────
    # session-end extraction 只产出 episodic。semantic/procedural 的
    # 生成路径是 W1 explicit retain / W4 consolidation / W5 emergence。
    episodic_proposals = [p for p in proposals if p.memory_type == "episodic"]
    non_episodic = [p for p in proposals if p.memory_type != "episodic"]
    summary["t3_ignored"] += len(non_episodic)  # session-end 不处理非 episodic

    # ── Governance Routing ──────────────────────────────────────────────
    # T2 宪法锁定（RFC §10.2）：
    #   - 仅 episodic 类型
    #   - confidence [0.6, 0.8)
    #   - sensitivity ≤ MEDIUM
    #   - 单 session 上限 3 条
    #   - 必须标记 approval_status="auto_retained"
    max_t2_per_session = 3
    t2_count = 0

    for proposal in episodic_proposals:
        confidence = proposal.confidence

        # ── T3: confidence < 0.6 → ignore ────────────────────────────
        if confidence < 0.6:
            summary["t3_ignored"] += 1
            continue

        # ── T2: confidence [0.6, 0.8) → governed auto-retain ─────────
        if 0.6 <= confidence < 0.8:
            if t2_count >= max_t2_per_session:
                summary["t3_ignored"] += 1
                continue

            # T2 安全锁定：sensitivity check（FakeMemoryExtractor 产出
            # 的 proposal sensitivity 默认 LOW，但仍需显式检查）
            # FakeMemoryExtractor 不设 sensitivity，bridge 默认 LOW
            candidate = proposal_to_candidate(proposal)
            if candidate.sensitivity in {
                MemorySensitivity.HIGH,
                MemorySensitivity.SECRET,
            }:
                summary["t3_ignored"] += 1
                continue

            # 去重检查（SHA256 + 规范化 content 匹配）
            existing_records = store.list_records()
            duplicate = find_duplicate_record(
                candidate.content, candidate.proposed_type, candidate.scope,
                existing_records,
            )
            if duplicate is not None:
                summary["dedup_hits"] += 1
                summary["t3_ignored"] += 1
                continue

            # ── T2 写入：构造 MemoryOperationIntent → apply_operation_intent ─
            # 统一走 canonical write path（RFC §10.4, §14.5）：
            # MemoryOperationIntent 携带完整 governance metadata
            # （memory_type / source_type / confirmation_status），
            # store.apply_operation_intent 根据 confirmation_status 决定
            # approval_status。不再使用 hasattr(store, "_records") hack。
            t2_intent = MemoryOperationIntent(
                operation_type=MemoryOperationType.RETAIN,
                decision_type=MemoryDecisionType.RETAIN,
                confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
                user_choice=MemoryConfirmationChoice.ACCEPT,
                content_summary=proposal.content,
                source_summary=f"session_end_extraction: {proposal.evidence[:100]}",
                scope=candidate.scope or MemoryScope.USER,
                safety_summary="T2 auto_retained (session-end extraction)",
                sensitive_redacted=False,
                user_visible_summary=f"[自动记录] {proposal.content[:80]}",
                memory_type="episodic",
                source_type="agent_suggested",
                # confidence metadata continuity：透传 extraction 的真实 confidence，
                # 不再依赖 store 层硬编码 fallback（见 P1-1 修复）。
                confidence=proposal.confidence,
            )
            t2_audit = build_memory_audit_summary(t2_intent)
            t2_result = store.apply_operation_intent(t2_intent, t2_audit)

            if t2_result.status is MemoryStoreApplyStatus.APPLIED:
                t2_count += 1
                summary["t2_auto_retained"] += 1
            else:
                summary["errors"].append(
                    f"T2 auto_retain apply 失败（status={t2_result.status.value}）: "
                    f"{t2_result.message}"
                )
            continue

        # ── T1: confidence ≥0.8 → pending confirmation ────────────────
        # T1 proposal 需要人类 review。collect metadata 后在循环结束后
        # 持久化到 _pending/ 目录（Phase 5a skeleton persistence）。
        # 复用 _build_t1_pending_dict() 共享 helper（W3 + L2 共用）。
        t1_proposals.append(_build_t1_pending_dict(
            proposal, "session_end_extraction",
        ))
        summary["t1_pending"] += 1

    # ── T1 pending 持久化 ──────────────────────────────────────────────
    # Phase 5a skeleton persistence：将 T1 pending proposals 写入
    # {memory_root}/_pending/ 目录。每条 proposal 独立 JSON 文件。
    if t1_proposals:
        try:
            _persist_t1_pending_proposals(t1_proposals)
        except Exception as exc:
            summary["errors"].append(f"T1 pending 持久化失败: {exc}")

    # ── Dogfood 观察笔记 ──────────────────────────────────────────────
    if summary["total_proposals"] == 0:
        summary["false_positives_note"] = (
            "无 proposal 被提取。可能原因：(1) extractor 未识别到值得提取的记忆"
            "（false negative）；(2) 本次 session 确实无可提取内容。"
        )
    elif summary["t2_auto_retained"] == 0 and summary["t1_pending"] == 0:
        summary["false_positives_note"] = (
            f"提取到 {summary['total_proposals']} 条 proposal，"
            f"但全部被 T3 过滤（confidence/类型/去重）。"
            f"需观察是否有 false positive 或 confidence 阈值需校准。"
        )

    # Phase 6 Consolidation Runtime Hook
    # After session-end extraction completes, conditionally trigger
    # consolidation pipeline and dispatch candidates to T1 pending review.
    # No auto-approve, no direct semantic store write.
    try:
        consolidation_summary = _maybe_run_consolidation(store, summary)
    except Exception as exc:
        consolidation_summary = {
            "enabled": False,
            "error": f"consolidation hook error: {exc}",
        }
    summary["consolidation"] = consolidation_summary

    # Phase 7 Emergence Runtime Hook
    # 这个 hook 只做 opt-in orchestration：读取当前 store 的已生效 records，
    # 派生 correction evidence，调用 W5 detector，并把 procedural candidate
    # 发往 T1 pending_review。它不写正式 procedural store，不触发
    # inline_confirmation，不调用 LLM；失败也不能破坏 session-end extraction。
    try:
        emergence_summary = _maybe_run_emergence(store, summary)
    except Exception as exc:
        emergence_summary = {
            "enabled": True,
            "error": f"emergence hook error: {type(exc).__name__}",
            "direct_store_write": False,
        }
    summary["emergence"] = emergence_summary

    return summary


def _msg_content_for_extraction(msg: dict) -> str:
    """从消息中提取用于 memory extraction 的文本内容。

    处理 Anthropic content block 格式（list of blocks）和纯文本字符串。
    tool_use / tool_result block 提取摘要而非全文，避免噪声。
    """
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                text = block.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
            elif block_type == "tool_use":
                name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                input_summary = _summarize_tool_input(tool_input)
                parts.append(f"[调用工具: {name}] {input_summary}")
            elif block_type == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, str):
                    parts.append(
                        f"[工具结果: {result_content[:200]}]"
                    )
                elif isinstance(result_content, list):
                    text_parts = [
                        b.get("text", "") for b in result_content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    combined = " ".join(text_parts)[:200]
                    parts.append(f"[工具结果: {combined}]")
        return "\n".join(parts)
    return str(content)


def _summarize_tool_input(tool_input: dict) -> str:
    """简要摘要 tool input，避免过长内容污染 extraction。"""
    if not tool_input:
        return ""
    # 只取前 3 个 key 的前 80 chars 值
    items = []
    for k, v in list(tool_input.items())[:3]:
        v_str = str(v)[:80]
        items.append(f"{k}={v_str}")
    result = ", ".join(items)
    if len(result) > 300:
        result = result[:297] + "..."
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# T1 Pending Persistence（Phase 5a skeleton）
# ═══════════════════════════════════════════════════════════════════════════════


def _now_utc_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_memory_root() -> str | None:
    """解析 memory 根目录路径。

    优先级与 FilesystemMemoryStore 一致：
    MEMORY_STORE_ROOT > MEMORY_ROOT。未显式配置时 fail closed。

    不再 fallback 到 ``~/.my-first-agent/memory``，避免 legacy session-end
    extraction / T1 pending 在测试或生产中静默写 HOME。
    """
    import os as _os
    return (
        _os.getenv("MEMORY_STORE_ROOT")
        or _os.getenv("MEMORY_ROOT")
    )


def _build_t1_pending_dict(
    proposal,
    source_label: str,
) -> dict:
    """构造 T1 pending proposal dict — W3 和 L2 共享的 thin helper。

    不包含 governance 决策逻辑，只做字段映射。
    memory_type 从 proposal 透传（W3 永远是 episodic，L2 可能为 semantic/procedural）。
    source 标注来源（"session_end_extraction" / "l2_inline_extraction"）。
    """
    import os as _os

    from agent.memory_extraction_bridge import proposal_to_candidate

    candidate = proposal_to_candidate(proposal)
    return {
        "content": proposal.content,
        "evidence": proposal.evidence,
        "confidence": proposal.confidence,
        "importance": proposal.importance,
        "rationale": proposal.rationale,
        "memory_type": proposal.memory_type,
        "source_type": "agent_suggested",
        "governance_route": "T1",
        "approval_status": "pending",
        "scope": candidate.scope.value if candidate.scope else "user",
        "source": source_label,
        "created_at": _os.environ.get("SESSION_START_TIME", "") or _now_utc_iso(),
    }


def _persist_t1_pending_proposals(proposals: list[dict]) -> None:
    """将 T1 pending proposals 持久化到 {memory_root}/_pending/ 目录。

    Phase 5a skeleton persistence — 每条 T1 proposal 独立 JSON 文件：
      {memory_root}/_pending/t1_{timestamp}_{hash4}.json

    metadata 包含：content, evidence, confidence, importance, rationale,
    memory_type, source_type, governance_route, approval_status, scope,
    source, created_at。

    这不是完整 review UX，仅为确保 session 结束后 T1 proposal 不丢失。
    后续 review bridge 从 _pending/ 目录读取并展示给用户。
    """
    import json
    from hashlib import sha256
    from pathlib import Path

    root = _resolve_memory_root()
    if not root:
        raise RuntimeError("durable_memory_root_not_configured")
    pending_dir = Path(root) / "_pending"
    pending_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _now_utc_iso().replace(":", "-")
    for i, proposal in enumerate(proposals):
        # 用 content hash 前 4 位做文件名区分
        content_hash = sha256(proposal["content"].encode("utf-8")).hexdigest()[:4]
        filename = f"t1_{timestamp}_{content_hash}_{i}.json"
        filepath = pending_dir / filename
        filepath.write_text(
            json.dumps(proposal, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Extraction Summary 格式化（session runtime 可见性边界）
# ═══════════════════════════════════════════════════════════════════════════════


def _format_extraction_summary(summary: dict) -> str:
    """将 extract_memories_from_session 的返回 summary 格式化为终端可读文本。

    这是 session.py ↔ memory.py 之间的唯一可见性边界：
    - session.py 只拿到 dict summary，不直接查询 store 内部状态
    - 本函数负责把 dict 转成用户可读的文本，不修改任何状态
    - 不打印 raw memory content，只展示 counts / route / store backend / errors

    Dogfood 关键信息：
    - store backend（InMemory / filesystem）
    - InMemory → ephemeral warning
    - filesystem → safe root metadata，不显示 raw filesystem path
    - T2 auto_retained / T1 pending / T3 ignored 计数
    - errors 摘要（不堆栈）
    """
    lines: list[str] = []
    lines.append("─" * 40)
    lines.append("Memory Extraction Summary")

    # ── Store 可见性 ──────────────────────────────────────────────────
    backend = summary.get("store_backend", "unknown")
    if backend in ("memory", "in_memory", "inmemory"):
        lines.append("  Store:  InMemory（ephemeral）")
        lines.append(
            "  ⚠️  当前使用 InMemory backend，session 退出后所有记录将丢失。"
        )
        lines.append(
            "     如需持久化，请设置 MEMORY_STORE_BACKEND=filesystem。"
        )
    elif backend in ("filesystem", "memory_fs", "fs"):
        root_hash = summary.get("root_hash", "")
        root_kind = summary.get("root_kind", "unknown")
        path_kind = summary.get("path_kind", "unknown")
        lines.append("  Store:  Filesystem")
        lines.append(f"  Root:   redacted kind={root_kind} path_kind={path_kind}")
        if root_hash:
            lines.append(f"  Root hash: {root_hash}")
    else:
        lines.append(f"  Store:  {backend}")

    # ── Extraction 计数 ───────────────────────────────────────────────
    total_msgs = summary.get("total_messages", 0)
    total_proposals = summary.get("total_proposals", 0)
    t2 = summary.get("t2_auto_retained", 0)
    t1 = summary.get("t1_pending", 0)
    t3 = summary.get("t3_ignored", 0)
    dedup = summary.get("dedup_hits", 0)

    lines.append(f"  Messages:         {total_msgs}")
    lines.append(f"  Proposals:        {total_proposals}")
    lines.append(f"  T2 auto-retained: {t2}")
    lines.append(f"  T1 pending:       {t1}")
    lines.append(f"  T3 ignored:       {t3}")
    if dedup:
        lines.append(f"  Dedup hits:       {dedup}")

    # ── Errors ────────────────────────────────────────────────────────
    errors: list = summary.get("errors", [])
    if errors:
        lines.append(f"  Errors:           {len(errors)}")
        for err in errors[:3]:  # 最多展示前 3 条
            lines.append(f"    - {err}")
        if len(errors) > 3:
            lines.append(f"    ... 及其他 {len(errors) - 3} 条错误")

    # ── Extractor 元信息（LLM model name 等）──────────────────────────
    extraction_summary = summary.get("extraction_summary", "")
    if extraction_summary:
        lines.append(f"  Extractor:        {extraction_summary}")

    # ── Dogfood 观察笔记 ──────────────────────────────────────────────
    note = summary.get("false_positives_note", "")
    if note:
        lines.append(f"  Note: {note}")

    # ── Phase 7 Emergence 可见性（只显示计数和路由，不显示原文）────────────
    emergence = summary.get("emergence")
    if isinstance(emergence, dict):
        if emergence.get("enabled") is False:
            lines.append("  Emergence:       disabled")
        elif "error" in emergence:
            lines.append("  Emergence:       error")
            lines.append(f"    - {emergence.get('error')}")
        elif emergence.get("enabled") is True:
            lines.append(
                "  Emergence:       "
                f"active={emergence.get('active_records_count', 0)}, "
                f"evidence={emergence.get('evidence_count', 0)}, "
                f"candidates={emergence.get('candidate_count', 0)}, "
                f"pending={emergence.get('dispatched_count', 0)}, "
                f"form={emergence.get('confirmation_form', 'pending_review')}"
            )
            warnings = emergence.get("warnings") or []
            if warnings:
                lines.append(f"    warnings: {len(warnings)}")

    lines.append("─" * 40)
    return "\n".join(lines)

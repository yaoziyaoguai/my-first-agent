"""Phase 5 — Extraction Review Orchestrator.

薄 orchestrator，编排 extraction → display → collect choices → store 的完整流程。
是 extraction sandbox 与 agent loop 之间的唯一桥接点。

职责：
- 从 transcript 中提取 proposal（委托 LLMMemoryExtractor）
- 将 proposal 转为 confirmation request（委托 memory_extraction_bridge）
- 展示 proposal 详情并收集用户选择（本模块负责 I/O）
- 确认后写入 store（委托 bridge 的 resolve_and_store）

不负责：
- 不修改 MemoryRuntime
- 不 import core / checkpoint（CLI wrapper 除外）
- 不做 auto-retain
- 不做 session-end extraction
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationRequest
from agent.memory_extraction import (
    ExtractionInput,
    LLMMemoryExtractor,
    create_extractor,
)
from agent.memory_extraction_bridge import (
    proposal_to_confirmation_request,
    resolve_and_store,
)
from agent.memory_store import MemoryStoreProtocol


@dataclass
class ExtractionReviewReport:
    """一次 extraction review 的只读结果。"""

    total_proposals: int = 0
    accepted: int = 0
    rejected: int = 0
    edited: int = 0
    session_only: int = 0
    skipped: int = 0
    stored_record_ids: list[str] = field(default_factory=list)
    extractor_type: str = "unknown"
    extraction_summary: str = ""


# ── 交互展示 ──────────────────────────────────────────────────────────────────

_PROPOSAL_DISPLAY_TEMPLATE = """\
─── Proposal {index}/{total} ─────────────────
Type:       {memory_type}
Content:    {content}
Evidence:   {evidence}
Importance: {importance}/10
Confidence: {confidence:.2f}
Rationale:  {rationale}

1. Accept (记住)
2. Edit & Accept (编辑后记住)
3. Reject (不记住)
4. Session Only (仅本次使用)
──────────────────────────────────"""


def _display_proposal(
    request: MemoryConfirmationRequest,
    index: int,
    total: int,
    *,
    output_fn: Callable[[str], None] = print,
) -> None:
    """展示单条 proposal 详情和选项。"""
    decision = request.decision
    candidate = decision.target_candidate
    if candidate is None:
        return

    metadata = candidate.metadata or {}
    memory_type = metadata.get("memory_type", candidate.proposed_type)
    importance = metadata.get("importance", "?")
    evidence = candidate.source_event or "(无证据)"
    rationale = candidate.reason or "(无理由)"

    output_fn(
        _PROPOSAL_DISPLAY_TEMPLATE.format(
            index=index,
            total=total,
            memory_type=memory_type,
            content=candidate.content,
            evidence=evidence,
            importance=importance,
            confidence=candidate.confidence,
            rationale=rationale,
        )
    )


def _parse_choice(
    raw: str,
) -> tuple[MemoryConfirmationChoice, str | None]:
    """把用户输入解析为 (choice, free_text)。

    - "1" → ACCEPT
    - "2" → EDIT_AND_ACCEPT (free_text 在下一轮读取)
    - "2 <text>" → EDIT_AND_ACCEPT + free_text
    - "3" → REJECT
    - "4" → SESSION_ONLY
    - 其他 → 重新询问
    """
    text = raw.strip()
    if not text:
        raise ValueError("输入为空")

    if text == "1":
        return MemoryConfirmationChoice.ACCEPT, None
    if text == "2":
        return MemoryConfirmationChoice.EDIT_AND_ACCEPT, None
    if text.startswith("2 "):
        return MemoryConfirmationChoice.EDIT_AND_ACCEPT, text[2:].strip()
    if text == "3":
        return MemoryConfirmationChoice.REJECT, None
    if text == "4":
        return MemoryConfirmationChoice.SESSION_ONLY, None

    raise ValueError(f"无效选项: {text!r}，请输入 1-4")


# ── 核心 pipeline ──────────────────────────────────────────────────────────────


def run_extraction_review(
    transcript: list[dict],
    *,
    store: MemoryStoreProtocol | None = None,
    extractor: LLMMemoryExtractor | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> ExtractionReviewReport:
    """从 transcript 中提取 memory proposal，逐条展示并收集用户确认。

    Args:
        transcript: 对话记录 [{"role": "user"|"assistant", "content": "..."}]
        store: 目标 store，None 时不写入
        extractor: 提取器。None 时默认使用 create_extractor("fake", ...)
                   （Phase 5a skeleton path，不调用真实 LLM）。
                   真实 LLM extraction 需显式传入 LLMMemoryExtractor 实例，
                   调用方须自行确保 API key 已配置且理解成本。
        input_fn: 用户输入函数（默认 built-in input）
        output_fn: 输出函数（默认 built-in print）

    Returns:
        ExtractionReviewReport 包含计数和写入结果。
    """
    if extractor is None:
        # Phase 5a skeleton path：默认 fake extractor，不调用真实 LLM。
        # 真实 LLM extraction 需显式传入 LLMMemoryExtractor 实例。
        extractor = create_extractor("fake", min_confidence=0.6, min_importance=3)

    # 1. Extraction
    if not transcript:
        output_fn("\n没有对话记录可供提取。")
        return ExtractionReviewReport(
            total_proposals=0,
            extractor_type=extractor.__class__.__name__,
            extraction_summary="transcript 为空",
        )

    try:
        result = extractor.extract(ExtractionInput(transcript=transcript))
    except ValueError as exc:
        output_fn(f"\n提取失败: {exc}")
        return ExtractionReviewReport(
            total_proposals=0,
            extractor_type=extractor.__class__.__name__,
            extraction_summary=str(exc),
        )

    proposals = list(result.proposals)

    # 2. 转 confirmation requests（IGNORE 被 bridge 过滤为 None）
    requests: list[tuple[int, MemoryConfirmationRequest]] = []
    for i, p in enumerate(proposals):
        req = proposal_to_confirmation_request(p)
        if req is not None:
            requests.append((i, req))

    if not requests:
        output_fn("\n没有需要确认的 memory proposal。")
        output_fn(f"({result.extraction_summary})")
        return ExtractionReviewReport(
            total_proposals=len(proposals),
            extractor_type=result.extractor_type,
            extraction_summary=result.extraction_summary,
        )

    total_confirmable = len(requests)
    output_fn(f"\n共 {len(proposals)} 条 proposal，其中 {total_confirmable} 条需要确认。")

    # 3. 逐条确认
    report = ExtractionReviewReport(
        total_proposals=len(proposals),
        extractor_type=result.extractor_type,
        extraction_summary=result.extraction_summary,
    )

    for display_index, (orig_index, req) in enumerate(requests, start=1):
        _display_proposal(req, display_index, total_confirmable, output_fn=output_fn)

        choice, free_text = _collect_choice(req, input_fn=input_fn, output_fn=output_fn)

        if choice is MemoryConfirmationChoice.ACCEPT:
            report.accepted += 1
        elif choice is MemoryConfirmationChoice.EDIT_AND_ACCEPT:
            report.edited += 1
        elif choice is MemoryConfirmationChoice.REJECT:
            report.rejected += 1
        elif choice is MemoryConfirmationChoice.SESSION_ONLY:
            report.session_only += 1
        else:
            report.skipped += 1

        # 4. 写入 store
        if store is not None:
            apply_result = resolve_and_store(req, choice, store, free_text=free_text)
            if apply_result is not None and apply_result.record is not None:
                report.stored_record_ids.append(apply_result.record.id)
                output_fn(f"  已写入: {apply_result.record.id}")
        else:
            output_fn("  (store 未注入，未持久化)")

    return report


def _collect_choice(
    req: MemoryConfirmationRequest,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> tuple[MemoryConfirmationChoice, str | None]:
    """读取用户选择，含重试和 EDIT_AND_ACCEPT 的编辑文本读取。"""
    while True:
        try:
            raw = input_fn("Your choice [1-4]: ")
            choice, free_text = _parse_choice(raw)
            # EDIT_AND_ACCEPT 但未附带文本 → 再读一行
            if choice is MemoryConfirmationChoice.EDIT_AND_ACCEPT and not free_text:
                free_text = input_fn("编辑后的内容: ").strip()
                if not free_text:
                    output_fn("编辑内容不能为空，请重新选择。")
                    continue
            return choice, free_text
        except ValueError as exc:
            output_fn(str(exc))


# ── CLI wrapper ────────────────────────────────────────────────────────────────


def run_extraction_review_cli() -> int:
    """CLI 入口：读取 checkpoint → extraction review → 打印报告 → 返回 exit code。

    供 main.py 的 `memory extract` 子命令调用。

    ⚠️ Dogfood Safety（RFC §11.4）：
    默认使用 create_extractor("fake", ...) factory seam，不调用真实 LLM。
    真实 LLM extraction 需显式设置 MEMORY_EXTRACTION_REAL_LLM=1 并确保
    API key 已配置。controlled dogfood 应走 finalize_session() 路径，
    不应依赖此 CLI。
    """
    checkpoint_path = Path("memory/checkpoint.json")
    if not checkpoint_path.exists():
        print("没有找到 checkpoint 文件 (memory/checkpoint.json)。")
        print("请先进行一些对话，确保有可提取的对话记录。")
        return 1

    import json as _json

    try:
        data = _json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"读取 checkpoint 失败: {exc}")
        return 1

    messages: list[dict[str, Any]] = []
    conv = data.get("conversation", {}) if isinstance(data, dict) else {}
    raw_messages = conv.get("messages", []) if isinstance(conv, dict) else []
    for msg in raw_messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # 跳过 system / tool_result 等非对话消息
        if role in ("user", "assistant"):
            # content 可能是 string 或 list[ContentBlock]
            if isinstance(content, str):
                messages.append({"role": role, "content": content})
            elif isinstance(content, list):
                # 合并 text blocks 为字符串
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                if parts:
                    messages.append({"role": role, "content": " ".join(parts)})

    if not messages:
        print("checkpoint 中没有用户/助手对话记录。")
        return 1

    # 创建 store（优先 filesystem）
    import os as _os

    backend = _os.getenv("MEMORY_STORE_BACKEND", "filesystem").strip()
    if backend in ("filesystem", "memory_fs", "fs"):
        from agent.memory_fs_store import FilesystemMemoryStore

        store = FilesystemMemoryStore()
    else:
        from agent.memory_store import InMemoryMemoryStore

        store = InMemoryMemoryStore()

    # ── Extractor 选择（factory seam，fail-closed）─────────────────────
    # 默认 fake：通过 create_extractor("fake", ...) factory seam，
    # 不调用真实 LLM，不读取 .env / API key。
    # 真实 LLM extraction 需显式 opt-in：MEMORY_EXTRACTION_REAL_LLM=1。
    # controlled dogfood 应走 finalize_session() 路径，不使用此 CLI。
    use_real_llm = _os.getenv("MEMORY_EXTRACTION_REAL_LLM", "").strip() in (
        "1", "true", "yes",
    )
    if use_real_llm:
        print("[Memory Extract] 使用真实 LLM extraction（MEMORY_EXTRACTION_REAL_LLM=1）")
        extractor = LLMMemoryExtractor()
    else:
        print(
            "[Memory Extract] 使用 fake extractor（skeleton mode）。"
            "如需真实 LLM extraction，请设置 MEMORY_EXTRACTION_REAL_LLM=1。"
        )
        extractor = create_extractor("fake", min_confidence=0.6, min_importance=3)

    report = run_extraction_review(
        messages,
        store=store,
        extractor=extractor,
    )

    # 最终报告
    print()
    print("═" * 40)
    print("Extraction Review 完成")
    print(f"  Proposals 总数:  {report.total_proposals}")
    print(f"  Accept:          {report.accepted}")
    print(f"  Edit & Accept:   {report.edited}")
    print(f"  Reject:          {report.rejected}")
    print(f"  Session Only:    {report.session_only}")
    print(f"  Skip:            {report.skipped}")
    if report.stored_record_ids:
        print(f"  已写入 {len(report.stored_record_ids)} 条记录")
    print(f"  Extractor:       {report.extractor_type}")
    print("═" * 40)

    return 0

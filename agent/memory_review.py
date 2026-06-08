"""T1 Pending Review CLI — RFC §11.4 / §15.2 Phase 5a 收尾。

本模块是 Phase 5a human review bridge 的最小闭环：
- 读取 {memory_root}/_pending/t1_*.json 中的 T1 pending proposals
- 支持 list / accept / reject / edit-and-accept / skip
- accept 时复用 MemoryOperationIntent → store.apply_operation_intent()
- reject 时不写入正式 memory store
- 不负责 memory quality 判断、semantic consolidation、procedural emergence
- 不调用真实 LLM

架构边界（RFC §11.4, Appendix G.7）：
- Governance routing 决策在 memory.py 的 extract_memories_from_session() 中完成
- 本模块只消费已持久化到 _pending/ 的 T1 proposal，不重新做 T1/T2/T3 判断
- Store 写入复用 MemoryOperationIntent 统一路径，不绕过 governance
- 本模块不 import memory_runtime，不参与 runtime 状态管理

T1 review CLI 的定位（为什么独立成模块）：
- extract_memories_from_session 负责 extraction → governance routing → persistence
- 本模块负责 post-hoc human review —— 两个职责、两个时间点、两类调用方
- 不把 review 逻辑堆进 memory.py（避免让 extraction 模块承担 UX 职责）
- 不让 session.py 直接操作 pending 文件细节（session.py 只做 orchestration）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.memory_contracts import MemoryDecisionType, MemoryScope
from agent.memory_operations import (
    MemoryConfirmationChoice,
    MemoryConfirmationStatus,
    MemoryOperationIntent,
    MemoryOperationType,
    build_memory_audit_summary,
)
from agent.memory_store import (
    MemoryStoreApplyResult,
    MemoryStoreApplyStatus,
    MemoryStoreProtocol,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 路径解析（与 memory.py _resolve_memory_root 保持一致）
# ═══════════════════════════════════════════════════════════════════════════════


def _resolve_memory_root() -> str | None:
    """解析 memory 根目录路径。

    优先级与 FilesystemMemoryStore / memory.py:_resolve_memory_root 一致：
    MEMORY_STORE_ROOT > MEMORY_ROOT。未显式配置时 fail closed。

    Pending review 只能读取明确配置或显式传入的 durable root；这里不再回退
    到 HOME，避免 session 启动提示或 review CLI 在未配置时触碰真实用户目录。
    """
    from agent.memory_fs_store import resolve_configured_memory_root

    root = resolve_configured_memory_root()
    return str(root) if root is not None else None


# ═══════════════════════════════════════════════════════════════════════════════
# Pending proposal 读取
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PendingProposal:
    """从 _pending/t1_*.json 反序列化的一条 T1 pending proposal。

    这不是 MemoryCandidate / MemoryRecord —— 它只是 pending 文件的反序列化视图。
    review 流程结束后会转为 MemoryOperationIntent → store 写入或归档。

    Consolidation 特有字段（source_evidence, consolidation_type, evidence_summary）
    默认空以保持向后兼容——非 consolidation 的 T1 proposal 不携带这些字段。
    """

    filepath: Path
    content: str
    evidence: str
    confidence: float
    importance: int
    rationale: str
    memory_type: str
    source_type: str
    governance_route: str
    approval_status: str
    scope: str
    source: str
    created_at: str
    # Consolidation 特有字段（Phase 6, RFC §15.4）
    source_evidence: tuple[str, ...] = ()
    consolidation_type: str = ""
    evidence_summary: str = ""
    # Phase 7 Emergence 特有字段（RFC §15.5）
    correction_pattern: str = ""
    correction_type: str = ""
    # T1 confirmation form（RFC §10.5）："pending_review"（默认）或 "inline_confirmation"（计划）
    confirmation_form: str = "pending_review"


def count_pending_proposals(memory_root: str | None = None) -> int:
    """返回当前 _pending/ 中 approval_status=pending 的 proposal 数量。

    用于 session 启动时通知用户，不展示完整内容。
    """
    proposals = list_pending_proposals(memory_root=memory_root)
    return len(proposals)


def list_pending_proposals(
    memory_root: str | None = None,
) -> list[PendingProposal]:
    """扫描 {memory_root}/_pending/t1_*.json，返回所有 pending proposal。

    只返回 approval_status == "pending" 的 proposal。
    按 created_at 升序排列（最早的在前面）。
    格式损坏的 JSON 文件会被跳过并报告 warning，不会中断整个扫描。
    """
    root = memory_root or _resolve_memory_root()
    if root is None:
        return []
    pending_dir = Path(root) / "_pending"
    if not pending_dir.exists():
        return []

    proposals: list[PendingProposal] = []
    t1_files = sorted(pending_dir.glob("t1_*.json"))

    for filepath in t1_files:
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # 单个文件损坏不应阻塞整个 review
            print(f"[review] 警告: 无法解析 {filepath.name}: {exc}")
            continue

        if data.get("approval_status") != "pending":
            continue

        try:
            proposals.append(PendingProposal(
                filepath=filepath,
                content=data.get("content", ""),
                evidence=data.get("evidence", ""),
                confidence=float(data.get("confidence", 0.0)),
                importance=int(data.get("importance", 0)),
                rationale=data.get("rationale", ""),
                memory_type=data.get("memory_type", "episodic"),
                source_type=data.get("source_type", "agent_suggested"),
                governance_route=data.get("governance_route", "T1"),
                approval_status=data.get("approval_status", "pending"),
                scope=data.get("scope", "user"),
                source=data.get("source", ""),
                created_at=data.get("created_at", ""),
                # Consolidation 特有字段（Phase 6）
                source_evidence=tuple(data.get("source_evidence", [])),
                consolidation_type=data.get("consolidation_type", ""),
                evidence_summary=data.get("evidence_summary", ""),
                # Phase 7 Emergence 特有字段（RFC §15.5）
                correction_pattern=data.get("correction_pattern", ""),
                correction_type=data.get("correction_type", ""),
                # T1 confirmation form（RFC §10.5）
                confirmation_form=data.get("confirmation_form", "pending_review"),
            ))
        except (ValueError, TypeError) as exc:
            print(f"[review] 警告: 字段解析失败 {filepath.name}: {exc}")
            continue

    proposals.sort(key=lambda p: p.created_at)
    return proposals


# ═══════════════════════════════════════════════════════════════════════════════
# Pending file 归档（保留审计 trail，不直接删除）
# ═══════════════════════════════════════════════════════════════════════════════


def _archive_pending_file(filepath: Path, status: str) -> Path:
    """将 pending JSON 文件移动到 _pending/archived/{status}/ 子目录。

    status: "accepted" | "rejected"
    保留原始文件名，便于审计追溯。
    返回归档后的路径。
    """
    archive_dir = filepath.parent / "archived" / status
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / filepath.name
    # 如果目标已存在（极端情况：同名 timestamp + hash），追加序号
    if target.exists():
        stem = filepath.stem
        for i in range(1, 100):
            target = archive_dir / f"{stem}_{i}.json"
            if not target.exists():
                break
    filepath.rename(target)
    return target


# ═══════════════════════════════════════════════════════════════════════════════
# Review 操作：accept / reject / edit-and-accept / skip
# ═══════════════════════════════════════════════════════════════════════════════


def accept_pending_proposal(
    proposal: PendingProposal,
    store: MemoryStoreProtocol,
) -> MemoryStoreApplyResult:
    """接受一条 T1 pending proposal，写入正式 memory store。

    构造 MemoryOperationIntent（confirmation_status=APPROVED，走 T1 人类确认路径），
    调用 store.apply_operation_intent() 写入。成功后归档 pending 文件。

    metadata 保留策略（RFC §14.5 Metadata Continuity）：
    - memory_type 使用 proposal.memory_type（不 fallback 硬编码）
    - source_type 使用 proposal.source_type
    - confidence 使用 proposal.confidence（不再重新推断）
    - content 使用 proposal.content 原文
    - 若为 consolidation proposal，source_evidence / consolidation_type /
      evidence_summary 编码进 source_summary 保留
    """
    # Consolidation metadata 保留到 source_summary 中（不修改 MemoryOperationIntent schema）
    source_parts: list[str] = []
    if proposal.consolidation_type:
        source_parts.append(f"[consolidation:{proposal.consolidation_type}]")
    if proposal.source_evidence:
        source_parts.append(f"source_evidence={list(proposal.source_evidence)}")
    if proposal.evidence_summary:
        source_parts.append(f"evidence_summary={proposal.evidence_summary[:200]}")
    # Phase 7 Emergence metadata 保留
    if proposal.correction_pattern:
        source_parts.append(f"correction_pattern={proposal.correction_pattern}")
    if proposal.correction_type:
        source_parts.append(f"correction_type={proposal.correction_type}")
    source_parts.append(f"pending_review: {proposal.evidence[:100]}")

    intent = MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=MemoryConfirmationStatus.APPROVED,
        user_choice=MemoryConfirmationChoice.ACCEPT,
        content_summary=proposal.content,
        source_summary=" | ".join(source_parts),
        scope=_parse_scope(proposal.scope),
        safety_summary="T1 human reviewed (pending review CLI)",
        sensitive_redacted=False,
        user_visible_summary=f"[已确认] {proposal.content[:80]}",
        memory_type=proposal.memory_type,
        source_type=proposal.source_type,
        confidence=proposal.confidence,
    )
    audit = build_memory_audit_summary(intent)
    result = store.apply_operation_intent(intent, audit)

    if result.status is MemoryStoreApplyStatus.APPLIED:
        _archive_pending_file(proposal.filepath, "accepted")

    return result


def reject_pending_proposal(proposal: PendingProposal) -> None:
    """拒绝一条 T1 pending proposal。

    不写入正式 memory store。将 pending 文件归档到 _pending/archived/rejected/。
    """
    _archive_pending_file(proposal.filepath, "rejected")


def edit_and_accept_pending_proposal(
    proposal: PendingProposal,
    edited_content: str,
    store: MemoryStoreProtocol,
) -> MemoryStoreApplyResult:
    """编辑后接受一条 T1 pending proposal。

    使用用户编辑后的 content 构造 MemoryOperationIntent，保留原 evidence / source /
    confidence / governance_route 等 metadata。成功后归档 pending 文件。
    Consolidation proposal 的 source_evidence / consolidation_type /
    evidence_summary 编码进 source_summary 保留。
    """
    if not edited_content.strip():
        raise ValueError("编辑后的 content 不能为空")

    # Consolidation + Emergence metadata 保留到 source_summary 中
    source_parts: list[str] = []
    if proposal.consolidation_type:
        source_parts.append(f"[consolidation:{proposal.consolidation_type}]")
    if proposal.source_evidence:
        source_parts.append(f"source_evidence={list(proposal.source_evidence)}")
    if proposal.evidence_summary:
        source_parts.append(f"evidence_summary={proposal.evidence_summary[:200]}")
    # Phase 7 Emergence metadata 保留
    if proposal.correction_pattern:
        source_parts.append(f"correction_pattern={proposal.correction_pattern}")
    if proposal.correction_type:
        source_parts.append(f"correction_type={proposal.correction_type}")
    source_parts.append(f"pending_review(edited): {proposal.evidence[:100]}")

    intent = MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=MemoryConfirmationStatus.APPROVED,
        user_choice=MemoryConfirmationChoice.EDIT_AND_ACCEPT,
        content_summary=edited_content.strip(),
        source_summary=" | ".join(source_parts),
        scope=_parse_scope(proposal.scope),
        safety_summary="T1 human reviewed + edited (pending review CLI)",
        sensitive_redacted=False,
        user_visible_summary=f"[已确认-已编辑] {edited_content.strip()[:80]}",
        memory_type=proposal.memory_type,
        source_type=proposal.source_type,
        confidence=proposal.confidence,
    )
    audit = build_memory_audit_summary(intent)
    result = store.apply_operation_intent(intent, audit)

    if result.status is MemoryStoreApplyStatus.APPLIED:
        _archive_pending_file(proposal.filepath, "accepted")

    return result


def skip_pending_proposal(proposal: PendingProposal) -> None:
    """跳过一条 T1 pending proposal，不做任何修改。

    文件保留在 _pending/ 目录，下次 review 仍可见。
    """
    # 刻意留空：skip 就是什么都不做
    return


# ═══════════════════════════════════════════════════════════════════════════════
# 交互式 review CLI（thin presentation layer）
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_scope(scope_str: str) -> MemoryScope:
    """将 scope 字符串转为 MemoryScope enum。"""
    try:
        return MemoryScope(scope_str)
    except ValueError:
        return MemoryScope.USER


def _try_parse_float(s: str) -> float | None:
    """安全解析浮点数，失败返回 None。"""
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _render_proposal(proposal: PendingProposal, index: int, total: int) -> str:
    """将一条 pending proposal 格式化为终端可读文本。

    这是 review CLI 的唯一展示格式——不包含交互逻辑，不修改状态。
    Consolidation proposal 会展示额外的 source_evidence / consolidation_type / evidence_summary。
    """
    lines = [
        f"\n{'─' * 50}",
        f" 待确认记忆 [{index}/{total}]",
        f"{'─' * 50}",
        f" 内容: {proposal.content}",
        f" 类型: {proposal.memory_type}",
        f" 置信度: {proposal.confidence:.2f}",
        f" 来源: {proposal.source}",
        f" 依据: {proposal.evidence[:200]}",
        f" 理由: {proposal.rationale[:200]}",
        f" 创建时间: {proposal.created_at}",
    ]
    # Consolidation 特有字段（Phase 6）
    if proposal.consolidation_type:
        lines.append(f" 合并类型: {proposal.consolidation_type}")
    if proposal.source_evidence:
        evidence_list = list(proposal.source_evidence)
        lines.append(f" 来源记录: {', '.join(evidence_list[:5])}")
        if len(evidence_list) > 5:
            lines.append(f"           ... 及其他 {len(evidence_list) - 5} 条")
    if proposal.evidence_summary:
        lines.append(f" 依据摘要: {proposal.evidence_summary[:200]}")
    # Phase 7 Emergence 特有字段
    if proposal.correction_pattern:
        lines.append(f" 纠正模式: {proposal.correction_pattern}")
    if proposal.correction_type:
        lines.append(f" 纠正类型: {proposal.correction_type}")
    # 展示 confirmation form（RFC §10.5）
    if proposal.confirmation_form and proposal.confirmation_form != "pending_review":
        lines.append(f" 确认形式: {proposal.confirmation_form}")
    lines.append(f"{'─' * 50}")
    return "\n".join(lines)


def _read_user_choice() -> str:
    """读取用户选择，返回单个字符（小写）。

    不依赖 TUI / Textual，使用 built-in input()。
    """
    try:
        return input(" 选择 ([a]ccept / [r]eject / [e]dit / [s]kip / [q]uit): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "q"


def run_pending_review_cli(
    store: MemoryStoreProtocol | None = None,
    memory_root: str | None = None,
) -> dict[str, Any]:
    """交互式 T1 pending review CLI。

    遍历所有 pending proposal，逐条让用户选择：
    - a / accept: 接受并写入 store
    - r / reject: 拒绝并归档
    - e / edit: 编辑后接受
    - s / skip: 跳过，保持 pending
    - q / quit: 退出 review

    store 参数：None 时自动按 MEMORY_STORE_BACKEND 创建 store。
    如果 MEMORY_STORE_BACKEND=filesystem，使用 FilesystemMemoryStore（持久化）。
    否则使用 InMemoryMemoryStore（进程内，仅测试/演示用）。

    Returns:
        summary dict: {total, accepted, rejected, edited, skipped, errors}
    """
    proposals = list_pending_proposals(memory_root=memory_root)

    summary: dict[str, Any] = {
        "total": len(proposals),
        "accepted": 0,
        "rejected": 0,
        "edited": 0,
        "skipped": 0,
        "errors": [],
    }

    if not proposals:
        print("\n[review] 当前没有待确认的记忆提案。")
        return summary

    # ── 创建 store ──────────────────────────────────────────────────────
    if store is None:
        store = _create_store_from_env()

    print(f"\n[review] 共 {len(proposals)} 条待确认记忆提案。")
    print("[review] 输入 a/r/e/s/q 做出选择，或 Ctrl+C 退出。")

    for i, proposal in enumerate(proposals, start=1):
        print(_render_proposal(proposal, i, len(proposals)))

        choice = _read_user_choice()

        if choice in ("q", "quit", "exit"):
            print("[review] 已退出 review。剩余 proposal 保持 pending 状态。")
            break

        if choice in ("a", "accept"):
            try:
                result = accept_pending_proposal(proposal, store)
                if result.status is MemoryStoreApplyStatus.APPLIED:
                    summary["accepted"] += 1
                    record_id = result.record.id if result.record else "N/A"
                    print(f"  ✓ 已接受并写入 store。record_id={record_id}")
                else:
                    summary["errors"].append(
                        f"accept 失败 ({proposal.filepath.name}): {result.message}"
                    )
                    print(f"  ✗ 写入失败: {result.message}")
            except Exception as exc:
                summary["errors"].append(
                    f"accept 异常 ({proposal.filepath.name}): {exc}"
                )
                print(f"  ✗ 异常: {exc}")

        elif choice in ("r", "reject"):
            try:
                reject_pending_proposal(proposal)
                summary["rejected"] += 1
                print("  ✓ 已拒绝。proposal 已归档，未写入 store。")
            except Exception as exc:
                summary["errors"].append(
                    f"reject 异常 ({proposal.filepath.name}): {exc}"
                )
                print(f"  ✗ 异常: {exc}")

        elif choice in ("e", "edit"):
            try:
                edited = input("  请输入编辑后的内容: ").strip()
                if not edited:
                    print("  ✗ 编辑内容不能为空，已跳过。")
                    summary["skipped"] += 1
                    continue
                result = edit_and_accept_pending_proposal(proposal, edited, store)
                if result.status is MemoryStoreApplyStatus.APPLIED:
                    summary["edited"] += 1
                    record_id = result.record.id if result.record else "N/A"
                    print(f"  ✓ 已编辑并写入 store。record_id={record_id}")
                else:
                    summary["errors"].append(
                        f"edit 失败 ({proposal.filepath.name}): {result.message}"
                    )
                    print(f"  ✗ 写入失败: {result.message}")
            except Exception as exc:
                summary["errors"].append(
                    f"edit 异常 ({proposal.filepath.name}): {exc}"
                )
                print(f"  ✗ 异常: {exc}")

        elif choice in ("s", "skip"):
            skip_pending_proposal(proposal)
            summary["skipped"] += 1
            print("  → 已跳过。proposal 保持 pending 状态。")

        else:
            print(f"  ? 未知选择 '{choice}'，已跳过。输入 a/r/e/s/q。")
            summary["skipped"] += 1

    # ── 最终摘要 ────────────────────────────────────────────────────────
    print("\n[review] review 完成。")
    print(f"  总计: {summary['total']} | 接受: {summary['accepted']} | "
          f"拒绝: {summary['rejected']} | 编辑: {summary['edited']} | "
          f"跳过: {summary['skipped']}")
    remaining = count_pending_proposals(memory_root=memory_root)
    if remaining > 0:
        print(f"  仍有 {remaining} 条待确认。输入 'review memory' 可再次查看。")
    if summary["errors"]:
        print(f"  错误: {len(summary['errors'])} 条")
        for err in summary["errors"]:
            print(f"    - {err}")

    return summary


def _create_store_from_env() -> MemoryStoreProtocol:
    """按 MEMORY_STORE_BACKEND 环境变量创建 store。

    与 extract_memories_from_session() 的 store 创建逻辑一致：
    - "filesystem" / "memory_fs" / "fs" → FilesystemMemoryStore（持久化到磁盘）
    - 其他 / 未设置 → InMemoryMemoryStore（进程内）
    """
    import os as _os

    backend = _os.getenv("MEMORY_STORE_BACKEND", "memory").strip()
    if backend in ("filesystem", "memory_fs", "fs"):
        from agent.memory_fs_store import FilesystemMemoryStore

        return FilesystemMemoryStore()
    from agent.memory_store import InMemoryMemoryStore

    return InMemoryMemoryStore()

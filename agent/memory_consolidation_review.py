"""Phase 6 — Consolidation T1 Pending Review Dispatch.

将 ConsolidationCandidate 转换为 T1 pending proposal JSON 并写入 _pending/ 目录，
复用现有 Phase 5a pending review CLI 的 accept/reject/edit/skip 流程。

⛔ FROZEN (2026-05-25): 该模块属于 frozen consolidation pipeline。
   不允许新增 reviewer 逻辑或自动 approve 路径。
   参见: docs/audit/global-agent-capability-architecture-audit-2026-05-25.md F4

架构边界（RFC §15.4, §6.4, §D.1）：
- 只做 ConsolidationCandidate → _pending/ JSON 的 thin dispatch
- 不写正式 memory store — 写入只在 human accept 后发生（memory_review.py）
- 不自动 approve
- 不接 runtime hook / scheduler / background job
- 不调用 LLM
- 不新增第二套 review CLI
- 去重：同一 identity 不重复写入 _pending/
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from agent.memory_consolidation import ConsolidationCandidate


# ── Dispatch Result ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ConsolidationPendingDispatchResult:
    """dispatch_consolidation_candidates_to_pending_review() 的结构化结果。

    不包含 store 引用、不包含 pending review state。
    """

    dispatched: int
    skipped_duplicate: int
    skipped_invalid: int
    warnings: tuple[str, ...]
    proposal_filepaths: tuple[Path, ...]


# ── Identity（去重 key）───────────────────────────────────────────────────────


def _compute_proposal_identity(candidate: ConsolidationCandidate) -> str:
    """为 consolidation candidate 生成确定性 proposal identity。

    基于 memory_type, content hash, sorted source_evidence ids, consolidation_type。
    相同 identity 的 candidate 视为重复，不重复写入 _pending/（幂等）。
    """
    content_hash = sha256(candidate.content.encode("utf-8")).hexdigest()[:12]
    sorted_evidence = sorted(candidate.source_evidence)
    payload = (
        f"{candidate.memory_type}:{content_hash}:"
        f"{':'.join(sorted_evidence)}:{candidate.consolidation_type.value}"
    )
    identity_hash = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"consolidation_{identity_hash}"


# ── Dispatch 前置校验 ─────────────────────────────────────────────────────────


def _validate_candidate_for_dispatch(candidate: ConsolidationCandidate) -> str | None:
    """验证 candidate 满足 T1 pending dispatch 的前置约束。

    ConsolidationCandidate.__post_init__ 已强制 memory_type=semantic, governance_route=T1,
    此处再次校验作为 defense-in-depth。
    额外检查 source_evidence N≥3（RFC §D.1）——domain model 允许≥2，dispatch 要求≥3。

    Returns:
        None 表示通过；非空字符串为失败原因。
    """
    if candidate.memory_type != "semantic":
        return f"memory_type={candidate.memory_type}，非 semantic，不允许 dispatch"
    if candidate.governance_route != "T1":
        return f"governance_route={candidate.governance_route}，非 T1，不允许 dispatch"
    if len(candidate.source_evidence) < 3:
        return (
            f"source_evidence 仅 {len(candidate.source_evidence)} 条，"
            f"不足 N≥3 门槛（RFC §D.1），不允许 dispatch"
        )
    if not candidate.content.strip():
        return "content 为空，不允许 dispatch"
    return None


# ── 路径解析 ──────────────────────────────────────────────────────────────────


def _resolve_memory_root(memory_root: Path | str | None = None) -> Path:
    """解析 memory 根目录路径。

    优先级与 FilesystemMemoryStore / memory_review._resolve_memory_root 一致：
    显式参数 > MEMORY_STORE_ROOT > MEMORY_ROOT > ~/.my-first-agent/memory
    """
    import os as _os

    if memory_root is not None:
        return Path(memory_root)
    root_str = (
        _os.getenv("MEMORY_STORE_ROOT")
        or _os.getenv("MEMORY_ROOT")
        or str(Path.home() / ".my-first-agent" / "memory")
    )
    return Path(root_str)


# ── 公开 API ──────────────────────────────────────────────────────────────────


def dispatch_consolidation_candidates_to_pending_review(
    candidates: list[ConsolidationCandidate],
    *,
    memory_root: Path | str | None = None,
    source: str = "phase6_consolidation",
) -> ConsolidationPendingDispatchResult:
    """将 ConsolidationCandidate 列表分发到 T1 pending review。

    对每个 candidate：
    1. 验证 dispatch 前置约束（semantic, T1, N≥3）
    2. 计算确定性 proposal identity（去重 key）
    3. 扫描 _pending/ 中已有 proposal_id，跳过重复
    4. 写入 _pending/t1_{timestamp}_{hash4}_{index}.json

    不写正式 memory store。不自动 approve。不调 LLM。不接 runtime。

    Args:
        candidates: ConsolidationCandidate 列表
        memory_root: memory 根目录。None 时按环境变量解析。
        source: 来源标签，写入 pending JSON 的 source 字段。

    Returns:
        ConsolidationPendingDispatchResult:
        - dispatched: 成功写入的 proposal 数
        - skipped_duplicate: 因重复而跳过的数量
        - skipped_invalid: 因校验失败而跳过的数量
        - warnings: 校验失败警告
        - proposal_filepaths: 成功写入的文件路径
    """
    from datetime import datetime, timezone

    root = _resolve_memory_root(memory_root)
    pending_dir = root / "_pending"
    pending_dir.mkdir(parents=True, exist_ok=True)

    # 扫描已有 pending 文件的 proposal_id，构建已存在集合（去重依据）
    existing_ids: set[str] = set()
    for f in sorted(pending_dir.glob("t1_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            pid = data.get("proposal_id", "")
            if pid:
                existing_ids.add(pid)
        except (json.JSONDecodeError, OSError):
            # 损坏文件不影响新 proposal 写入
            continue

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    warnings: list[str] = []
    dispatched: list[Path] = []
    skipped_dup = 0
    skipped_invalid = 0

    for i, candidate in enumerate(candidates):
        # Step 1: 验证前置约束（defense-in-depth）
        violation = _validate_candidate_for_dispatch(candidate)
        if violation:
            skipped_invalid += 1
            cid = (
                list(candidate.source_evidence[:3])
                if candidate.source_evidence
                else ["?"]
            )
            warnings.append(f"[candidate evidence={cid}...] {violation}")
            continue

        # Step 2: 计算 identity
        proposal_id = _compute_proposal_identity(candidate)

        # Step 3: 去重——同一 identity 不重复写入
        if proposal_id in existing_ids:
            skipped_dup += 1
            continue

        # Step 4: 写入 pending JSON
        content_hash = sha256(candidate.content.encode("utf-8")).hexdigest()[:4]
        filename = f"t1_{timestamp}_{content_hash}_{i}.json"
        filepath = pending_dir / filename

        data: dict = {
            "proposal_id": proposal_id,
            "content": candidate.content,
            "evidence": candidate.evidence_summary,
            "confidence": candidate.confidence,
            "importance": _importance_from_confidence(candidate.confidence),
            "rationale": (
                f"[consolidation:{candidate.consolidation_type.value}] "
                f"source_evidence={list(candidate.source_evidence)} | "
                f"governance={candidate.governance_route}"
            ),
            "memory_type": candidate.memory_type,
            "source_type": "consolidation",
            "governance_route": candidate.governance_route,
            "approval_status": "pending",
            "scope": "user",
            "source": source,
            "created_at": candidate.created_at,
            # Consolidation 特有字段——review accept 时必须保留到正式 record
            "source_evidence": list(candidate.source_evidence),
            "consolidation_type": candidate.consolidation_type.value,
            "evidence_summary": candidate.evidence_summary,
        }

        filepath.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        dispatched.append(filepath)
        existing_ids.add(proposal_id)

    return ConsolidationPendingDispatchResult(
        dispatched=len(dispatched),
        skipped_duplicate=skipped_dup,
        skipped_invalid=skipped_invalid,
        warnings=tuple(warnings),
        proposal_filepaths=tuple(dispatched),
    )


def _importance_from_confidence(confidence: float) -> int:
    """将 confidence 映射到 1-10 的 importance 值。"""
    raw = round(confidence * 10)
    return max(1, min(10, raw))

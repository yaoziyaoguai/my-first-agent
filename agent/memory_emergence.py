"""Phase 7 — W5 Emergence Detection Foundation.

RFC §8: semantic + episodic + repeated correction → procedural candidate。
silent detection + T1 强制 human review。Procedural 永不可 silent retain（T2 auto-retain）。

T1 human confirmation 有两种交互形式（RFC §10.5）：
- pending_review：candidate 写入 _pending/，用户稍后 review（已接 review CLI）
- inline_confirmation：agent 当场询问，用户当场确认（当前实现 seam；未接 Agent loop）

本模块实现 Phase 7 foundation：
- CorrectionEvidence: 用户纠正行为的纯输入视图
- ProceduralCandidate: 永远 T1 的 procedural 候选
- EmergenceDetectionResult: 结构化检测结果（含 gate 信息）
- DeterministicEmergenceDetector: 确定性 correction pattern 检测器
- dispatch_procedural_candidates_to_pending_review(): T1 pending review form 分发
- prepare_procedural_inline_confirmation_request(): T1 inline confirmation form payload 生成
- apply_inline_confirmation_response(): 显式 accept/edit_accept 后写入 store；reject/other 不写入

架构边界（RFC §15.5, §8.2, §8.5, §10.5）：
- 确定性检测，不调 LLM
- active_records <50 → fail closed，不产生 candidate
- 同一 correction_pattern ≥3 条 evidence → 产生 ProceduralCandidate
- 所有 candidate 必须经 explicit human confirmation（T1），不可 silent retain
- confirmation_form 支持 "pending_review" 和 "inline_confirmation"（RFC §10.5）
- silent / auto_retained / none 是明确禁止的 confirmation form
- inline_confirmation 不写 store（除非 explicit accept/edit_accept），不调 LLM，不触发真实用户交互
- inline_confirmation runtime hook / Agent loop integration 尚未接入
- opt-in runtime hook 由 agent.memory._maybe_run_emergence() 编排，默认写 pending_review
- 不接 scheduler，不接 inline Agent loop
- 不自动 approve
- 不实现 procedural adoption
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from agent.memory_store import MemoryStoreApplyResult, MemoryStoreProtocol


# ═══════════════════════════════════════════════════════════════════════════════
# CorrectionEvidence — Phase 7 W5 的纯输入视图
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CorrectionEvidence:
    """用户纠正行为的结构化证据（RFC §8.2 trigger condition 的输入单元）。

    CorrectionEvidence 用来捕捉 repeated correction pattern 的 evidence，
    不是最终 procedural memory。每个实例对应一条用户纠正记录。

    不直接依赖 filesystem frontmatter 细节，不读取真实 sessions/runs。
    """

    record_id: str
    content: str
    correction_type: str  # 纠正类型，如 "behavioral_rule", "process_order", "communication_style"
    scope: str | None = None  # 作用域，如 "code_review", "debugging", "git_operations"
    created_at: str | None = None
    confidence: float | None = None
    source_memory_type: str = "episodic"  # 来源 memory 类型
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise ValueError("CorrectionEvidence.record_id 不能为空")
        if not self.content.strip():
            raise ValueError("CorrectionEvidence.content 不能为空")
        if not self.correction_type.strip():
            raise ValueError("CorrectionEvidence.correction_type 不能为空")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("CorrectionEvidence.confidence 必须在 0.0-1.0 之间")


# ═══════════════════════════════════════════════════════════════════════════════
# ProceduralCandidate — RFC Phase 7 W5 的候选输出
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ProceduralCandidate:
    """RFC Phase 7 W5 的候选输出——从 correction pattern 涌现出的行为约束候选。

    ProceduralCandidate 不是已采纳的 procedural memory。
    它永远必须进入 T1 explicit human confirmation（pending_review 或
    inline_confirmation），不能 silent retain，不能自动写入正式 store。

    validation 约束：
    - memory_type 必须是 "procedural"
    - governance_route 必须是 "T1"
    - content 不能为空
    - source_evidence 至少 3 条
    - confidence 必须在 0-1
    - 创建时不携带 approval_status（dispatch 时设为 pending；human confirmation 后变为 approved）
    - 不允许 silent retain（T2 auto-retain），不允许 create 时预批准
    """

    content: str
    memory_type: Literal["procedural"]
    source_evidence: tuple[str, ...]  # 支撑它的 CorrectionEvidence record_id 列表
    correction_pattern: str  # 检测到的纠正模式描述
    correction_type: str  # 纠正类型
    scope: str | None
    confidence: float  # 0.0-1.0
    governance_route: Literal["T1"]
    evidence_summary: str | None
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.memory_type != "procedural":
            raise ValueError(
                f"ProceduralCandidate.memory_type 必须是 'procedural'，"
                f"当前为 '{self.memory_type}'"
            )
        if self.governance_route != "T1":
            raise ValueError(
                f"ProceduralCandidate.governance_route 必须是 'T1'，"
                f"当前为 '{self.governance_route}'"
            )
        if not self.content.strip():
            raise ValueError("ProceduralCandidate.content 不能为空")
        if len(self.source_evidence) < 3:
            raise ValueError(
                f"ProceduralCandidate.source_evidence 至少需要 3 条，"
                f"当前仅 {len(self.source_evidence)} 条"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"ProceduralCandidate.confidence 必须在 0.0-1.0 之间，"
                f"当前为 {self.confidence}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# EmergenceDetectionResult — 结构化检测结果
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class EmergenceDetectionResult:
    """W5 emergence detector 的结构化输出。

    包含 gate 状态、产生的 candidate 列表、以及诊断信息。
    不包含 store 引用、不包含 pending review state。
    """

    candidates: tuple[ProceduralCandidate, ...]
    evidence_count: int  # 输入 evidence 总数
    active_records_count: int  # 传入的 active records 数
    gate_passed: bool  # active_records_count >= ACTIVE_RECORDS_THRESHOLD
    warnings: tuple[str, ...]
    skipped_count: int  # pattern evidence <3 跳过的 pattern 数


# ═══════════════════════════════════════════════════════════════════════════════
# DeterministicEmergenceDetector — Phase 7 foundation
# ═══════════════════════════════════════════════════════════════════════════════

# RFC §15.5: active records >50 是 Phase 7 emergence 的触发门槛
ACTIVE_RECORDS_THRESHOLD = 50

# 同一 correction pattern 至少需要 3 条 evidence（RFC §8.2）
MIN_CORRECTION_EVIDENCE = 3

# 确定性 correction marker 关键词（中文）（RFC §8.3 信号类型）
# 用于辅助 correction_pattern 的归一化，不用于复杂 NLP
CORRECTION_MARKERS: tuple[str, ...] = (
    "以后请",
    "下次先",
    "下次记得",
    "不要再",
    "不要直接",
    "不要自动",
    "请始终",
    "请先",
    "请务必",
    "先给结论",
    "先检查",
    "先读",
    "先看",
    "别直接",
    "别自动",
    "应该先",
    "记得先",
    "务必先",
    "必须",
    "千万不要",
)


def _normalize_correction_pattern(content: str) -> str:
    """从纠正内容中提取归一化的 correction pattern key phrase。

    这是 Phase 7 deterministic foundation 的简化实现：
    - 匹配已知中文纠正 marker 关键词
    - 提取 marker + 后续关键短语作为归一化 pattern
    - 不靠复杂 NLP，明确 marker-based

    correction pattern 不代表完整语义理解——后续 Phase 7
    可以通过 LLM 增强为全文语义 pattern。
    """
    for marker in CORRECTION_MARKERS:
        idx = content.find(marker)
        if idx != -1:
            # 提取 marker 及其后最多 20 个字符作为 pattern key
            end = min(idx + len(marker) + 20, len(content))
            phrase = content[idx:end].strip()
            # 截断到第一个标点
            for punct in ("。", "，", "；", "！", "？", "\n", ".", ",", ";"):
                p_idx = phrase.find(punct, len(marker))
                if p_idx != -1:
                    phrase = phrase[:p_idx].strip()
                    break
            return phrase
    # 无已知 marker，使用内容前 30 个字符作为 fallback pattern
    return content[:30].strip()


class DeterministicEmergenceDetector:
    """Phase 7 W5 确定性 emergence 检测器（RFC §8, §15.5）。

    检测逻辑：
    1. active_records_count < ACTIVE_RECORDS_THRESHOLD → fail closed，不产生 candidate
    2. 按 (correction_type, scope) 分组（确定性 foundation，不做语义聚类）
    3. 每组 ≥ MIN_CORRECTION_EVIDENCE 条 → 产生 ProceduralCandidate
    4. confidence 基于 evidence 数量、平均置信度、scope 一致性计算
    5. 所有 candidate governance_route=T1，永远不自动 approve

    分组策略说明：
    - 按 (correction_type, scope) 分组而非精确 pattern 字符串匹配
    - 原因：deterministic marker-based 归一化对不同表述产生不同字符串，
      精确匹配会导致语义相同的 evidence 无法归组
    - correction_pattern 字段使用 evidence 中最常见的归一化 pattern
    - 未来 Phase 7 LLM 增强可做语义聚类

    不调 LLM，不写 store，不接 runtime。
    """

    @staticmethod
    def detect(
        evidence_list: list[CorrectionEvidence],
        active_records_count: int,
    ) -> EmergenceDetectionResult:
        """对 correction evidence 执行 emergence detection。

        Args:
            evidence_list: 用户纠正行为的 evidence 列表
            active_records_count: 当前 active memory records 总数

        Returns:
            EmergenceDetectionResult: 含 candidate 列表和 gate 信息
        """
        warnings: list[str] = []

        # ── Gate 1: active records 数量门槛（RFC §15.5） ─────────────────
        if active_records_count < ACTIVE_RECORDS_THRESHOLD:
            warnings.append(
                f"active_records_count={active_records_count} < "
                f"{ACTIVE_RECORDS_THRESHOLD}，emergence detection disabled"
            )
            return EmergenceDetectionResult(
                candidates=(),
                evidence_count=len(evidence_list),
                active_records_count=active_records_count,
                gate_passed=False,
                warnings=tuple(warnings),
                skipped_count=0,
            )

        if not evidence_list:
            return EmergenceDetectionResult(
                candidates=(),
                evidence_count=0,
                active_records_count=active_records_count,
                gate_passed=True,
                warnings=(),
                skipped_count=0,
            )

        # ── 按 (correction_type, scope) 分组 ─────────────────────────────
        # deterministic foundation 不做语义聚类，同 type+scope 即为同组
        groups: dict[tuple[str, str], list[CorrectionEvidence]] = {}
        for e in evidence_list:
            scope = e.scope or "general"
            key = (e.correction_type, scope)
            groups.setdefault(key, []).append(e)

        # ── 每组 ≥ MIN_CORRECTION_EVIDENCE 条产生 candidate ──────────────
        candidates: list[ProceduralCandidate] = []
        skipped = 0
        from datetime import datetime, timezone

        for (corr_type, scope), group in groups.items():
            # 取组内最常见的归一化 pattern 作为 correction_pattern
            pattern = _most_common_pattern(group)
            if len(group) < MIN_CORRECTION_EVIDENCE:
                skipped += 1
                continue

            evidence_ids = tuple(e.record_id for e in group)
            confidence = _compute_procedural_confidence(group)
            content = _build_procedural_content(corr_type, scope, pattern, group)
            summary = _build_evidence_summary(group)

            candidates.append(ProceduralCandidate(
                content=content,
                memory_type="procedural",
                source_evidence=evidence_ids,
                correction_pattern=pattern,
                correction_type=corr_type,
                scope=scope,
                confidence=confidence,
                governance_route="T1",
                evidence_summary=summary,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ))

        # 按 confidence 降序排列
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        return EmergenceDetectionResult(
            candidates=tuple(candidates),
            evidence_count=len(evidence_list),
            active_records_count=active_records_count,
            gate_passed=True,
            warnings=tuple(warnings),
            skipped_count=skipped,
        )


def _most_common_pattern(group: list[CorrectionEvidence]) -> str:
    """从 evidence group 中选择出现频率最高的归一化 correction pattern。"""
    from collections import Counter

    patterns = [_normalize_correction_pattern(e.content) for e in group]
    counter = Counter(patterns)
    return counter.most_common(1)[0][0]


def _compute_procedural_confidence(group: list[CorrectionEvidence]) -> float:
    """基于 evidence 数量和平均置信度计算 procedural candidate 置信度。

    - 基准: 0.60（deterministic 下限）
    - evidence 数量加成: ≥3→+0.05, ≥4→+0.08, ≥5→+0.10, ≥7→+0.12
    - 平均 evidence confidence 加成（如有）
    - clamp 到 [0.60, 0.85]：deterministic detector 上限 0.85
    """
    base = 0.60
    n = len(group)

    if n >= 7:
        base += 0.12
    elif n >= 5:
        base += 0.10
    elif n >= 4:
        base += 0.08
    elif n >= 3:
        base += 0.05

    # 平均 evidence confidence 加成
    confs = [e.confidence for e in group if e.confidence is not None]
    if confs:
        avg_conf = sum(confs) / len(confs)
        base += avg_conf * 0.05

    return max(0.60, min(0.85, base))


def _build_procedural_content(
    corr_type: str,
    scope: str,
    pattern: str,
    group: list[CorrectionEvidence],
) -> str:
    """从 evidence group 构建 ProceduralCandidate.content。

    生成的行为约束描述格式：包含纠正类型、作用域、模式摘要和 evidence 统计。
    """
    type_label = _correction_type_label(corr_type)
    scope_label = f"（作用域: {scope}）" if scope and scope != "general" else ""
    count_label = f"（基于 {len(group)} 次重复纠正）"
    parts = [f"[行为约束] {type_label}{scope_label}", f"模式: {pattern}", count_label]
    return " ".join(parts)


def _correction_type_label(corr_type: str) -> str:
    """将 correction_type 转为中文可读标签。"""
    labels: dict[str, str] = {
        "behavioral_rule": "行为规则",
        "process_order": "操作顺序",
        "communication_style": "沟通风格",
        "tool_usage": "工具使用",
        "code_quality": "代码质量",
        "error_handling": "错误处理",
    }
    return labels.get(corr_type, corr_type)


def _build_evidence_summary(group: list[CorrectionEvidence]) -> str:
    """从 evidence group 构建 evidence_summary 文本。"""
    contents = [e.content[:80] for e in group[:5]]
    if len(group) > 5:
        contents.append(f"... 及其他 {len(group) - 5} 条")
    return " | ".join(contents)


# ═══════════════════════════════════════════════════════════════════════════════
# Procedural Candidate → T1 Pending Review Dispatch
# ═══════════════════════════════════════════════════════════════════════════════


def _resolve_memory_root(memory_root: Path | str | None = None) -> Path:
    """解析 memory 根目录路径。

    优先级与 FilesystemMemoryStore / memory_review._resolve_memory_root 一致。
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


def _compute_procedural_identity(candidate: ProceduralCandidate) -> str:
    """为 procedural candidate 生成确定性 proposal identity。

    基于 content hash + sorted source_evidence + correction_pattern。
    相同 identity 的 candidate 视为重复，不重复写入 _pending/（幂等）。
    """
    content_hash = sha256(candidate.content.encode("utf-8")).hexdigest()[:12]
    sorted_evidence = sorted(candidate.source_evidence)
    payload = (
        f"procedural:{content_hash}:"
        f"{':'.join(sorted_evidence)}:{candidate.correction_pattern}"
    )
    identity_hash = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"emergence_{identity_hash}"


@dataclass(frozen=True, slots=True)
class ProceduralDispatchResult:
    """dispatch_procedural_candidates_to_pending_review() 的结构化结果。"""

    dispatched: int
    skipped_duplicate: int
    skipped_invalid: int
    warnings: tuple[str, ...]
    proposal_filepaths: tuple[Path, ...]


def dispatch_procedural_candidates_to_pending_review(
    candidates: list[ProceduralCandidate],
    *,
    memory_root: Path | str | None = None,
    source: str = "phase7_emergence",
) -> ProceduralDispatchResult:
    """将 ProceduralCandidate 列表分发到 T1 pending review（RFC §10.5 pending_review form）。

    这是 T1 confirmation 的异步形式——candidate 写入 _pending/ 等待人类 review。
    另一种 T1 形式是 inline_confirmation（agent 当场询问，用户当场确认）。
    Phase 7 runtime hook 可调用本函数作为 non-interactive 默认路径；
    inline Agent loop integration 仍未接入。

    对每个 candidate：
    1. 验证 dispatch 前置约束（procedural, T1, source_evidence≥3）
    2. 计算确定性 proposal identity（去重 key）
    3. 扫描 _pending/ 中已有 proposal_id，跳过重复
    4. 写入 _pending/t1_{timestamp}_{hash4}_{index}.json（含 confirmation_form="pending_review"）

    不写正式 procedural store。不自动 approve。不调 LLM。不接 inline runtime。

    Args:
        candidates: ProceduralCandidate 列表
        memory_root: memory 根目录
        source: 来源标签，写入 pending JSON 的 source 字段

    Returns:
        ProceduralDispatchResult
    """
    from datetime import datetime, timezone

    root = _resolve_memory_root(memory_root)
    pending_dir = root / "_pending"
    pending_dir.mkdir(parents=True, exist_ok=True)

    # 扫描已有 pending，构建 proposal_id 集合（去重）
    existing_ids: set[str] = set()
    for f in sorted(pending_dir.glob("t1_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            pid = data.get("proposal_id", "")
            if pid:
                existing_ids.add(pid)
        except (json.JSONDecodeError, OSError):
            continue

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    warnings: list[str] = []
    dispatched: list[Path] = []
    skipped_dup = 0
    skipped_invalid = 0

    for i, candidate in enumerate(candidates):
        # Step 1: 验证
        violation = _validate_procedural_candidate(candidate)
        if violation:
            skipped_invalid += 1
            evidence_ids = list(candidate.source_evidence[:3])
            warnings.append(f"[candidate evidence={evidence_ids}...] {violation}")
            continue

        # Step 2: identity
        proposal_id = _compute_procedural_identity(candidate)

        # Step 3: 去重
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
            "evidence": candidate.evidence_summary or "",
            "confidence": candidate.confidence,
            "importance": _importance_from_confidence(candidate.confidence),
            "rationale": (
                f"[emergence] correction_pattern={candidate.correction_pattern} | "
                f"correction_type={candidate.correction_type} | "
                f"source_evidence={list(candidate.source_evidence)} | "
                f"governance={candidate.governance_route}"
            ),
            "memory_type": candidate.memory_type,
            "source_type": "emergence",
            "governance_route": candidate.governance_route,
            "approval_status": "pending",
            "scope": candidate.scope or "user",
            "source": source,
            "created_at": candidate.created_at,
            # Phase 7 特有字段——review accept 时必须保留
            "source_evidence": list(candidate.source_evidence),
            "correction_pattern": candidate.correction_pattern,
            "correction_type": candidate.correction_type,
            "evidence_summary": candidate.evidence_summary or "",
            # T1 confirmation form（RFC §10.5）：pending_review 已接 review CLI。
            # inline_confirmation 不写 _pending/；它通过 explicit response adapter
            # 在 accept/edit_accept 后才进入 store.apply_operation_intent。
            "confirmation_form": "pending_review",
        }

        filepath.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        dispatched.append(filepath)
        existing_ids.add(proposal_id)

    return ProceduralDispatchResult(
        dispatched=len(dispatched),
        skipped_duplicate=skipped_dup,
        skipped_invalid=skipped_invalid,
        warnings=tuple(warnings),
        proposal_filepaths=tuple(dispatched),
    )


def _validate_procedural_candidate(candidate: ProceduralCandidate) -> str | None:
    """defense-in-depth 验证 procedural candidate 满足 dispatch 约束。

    ProceduralCandidate.__post_init__ 已强制基本的 schema 约束，
    此处再次校验关键字段。
    """
    if candidate.memory_type != "procedural":
        return f"memory_type={candidate.memory_type}，非 procedural，不允许 dispatch"
    if candidate.governance_route != "T1":
        return f"governance_route={candidate.governance_route}，非 T1，不允许 dispatch"
    if len(candidate.source_evidence) < 3:
        return (
            f"source_evidence 仅 {len(candidate.source_evidence)} 条，"
            f"不足 {MIN_CORRECTION_EVIDENCE} 条门槛，不允许 dispatch"
        )
    if not candidate.content.strip():
        return "content 为空，不允许 dispatch"
    if not candidate.correction_pattern.strip():
        return "correction_pattern 为空，不允许 dispatch"
    return None


def _importance_from_confidence(confidence: float) -> int:
    """将 confidence 映射到 1-10 的 importance 值。"""
    raw = round(confidence * 10)
    return max(1, min(10, raw))


# ═══════════════════════════════════════════════════════════════════════════════
# ConfirmationForm — T1 confirmation 的两种交互形式（RFC §10.5）
# ═══════════════════════════════════════════════════════════════════════════════

ConfirmationForm = Literal["pending_review", "inline_confirmation"]

# 明确禁止的 confirmation form — procedural 永不可 silent/auto
_DISALLOWED_CONFIRMATION_FORMS: frozenset[str] = frozenset({"silent", "auto_retained", "none"})


def _validate_confirmation_form(form: str) -> None:
    """防御性校验：confirmation_form 不得为禁止值。"""
    if form in _DISALLOWED_CONFIRMATION_FORMS:
        raise ValueError(
            f"confirmation_form='{form}' 不被允许。"
            f"Procedural memory 永不可 silent retain / auto retain。"
            f"允许的 form: pending_review, inline_confirmation"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# InlineConfirmationRequest — T1 inline confirmation payload（RFC §10.5）
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class InlineConfirmationRequest:
    """T1 inline confirmation 的请求 payload（RFC §10.5）。

    这是 procedural candidate 的 T1 inline confirmation form——
    agent 当场呈现，用户当场确认/拒绝/编辑/其他。

    约束：
    - confirmation_form 固定为 "inline_confirmation"
    - allowed_actions 声明用户可执行的操作
    - 不写 store —— 只在 explicit accept / edit_accept 后写入
    - 不调 LLM
    - 不触发真实用户交互（本模块只负责生成 payload）
    - 不接 runtime hook
    """

    candidate_content: str
    source_evidence: tuple[str, ...]
    correction_pattern: str
    correction_type: str
    scope: str | None
    evidence_summary: str | None
    confidence: float
    confirmation_form: Literal["inline_confirmation"]
    allowed_actions: tuple[str, ...]  # e.g. ("accept", "reject", "edit", "other")
    proposal_id: str
    created_at: str

    def __post_init__(self) -> None:
        _validate_confirmation_form(self.confirmation_form)
        if self.confirmation_form != "inline_confirmation":
            raise ValueError(
                f"InlineConfirmationRequest.confirmation_form 必须是 'inline_confirmation'，"
                f"当前为 '{self.confirmation_form}'"
            )
        if not self.allowed_actions:
            raise ValueError("allowed_actions 不能为空")
        if not self.candidate_content.strip():
            raise ValueError("candidate_content 不能为空")
        if len(self.source_evidence) < 3:
            raise ValueError(
                f"source_evidence 至少需要 3 条，当前仅 {len(self.source_evidence)} 条"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence 必须在 0.0-1.0 之间，当前为 {self.confidence}")


# ═══════════════════════════════════════════════════════════════════════════════
# Inline Confirmation API（RFC §10.5 inline form）
# ═══════════════════════════════════════════════════════════════════════════════

InlineConfirmationAction = Literal["accept", "edit_accept", "reject", "other"]
InlineConfirmationApplyStatus = Literal["applied", "no_write", "needs_followup"]


@dataclass(frozen=True, slots=True)
class InlineConfirmationResponse:
    """用户对 inline confirmation request 的无副作用响应。

    这是 runtime/Ask User 机制可以返回给 memory emergence 层的 adapter
    contract。它本身不写 store；只有 apply_inline_confirmation_response()
    在 action 为 accept / edit_accept 时才会进入 store 写入路径。
    """

    action: InlineConfirmationAction
    edited_content: str | None = None
    free_text: str | None = None

    def __post_init__(self) -> None:
        if self.action not in {"accept", "edit_accept", "reject", "other"}:
            raise ValueError(f"未知 inline confirmation action: {self.action}")
        if self.action == "edit_accept" and not (self.edited_content or "").strip():
            raise ValueError("edit_accept 需要非空 edited_content")
        if self.action == "other" and not (self.free_text or "").strip():
            raise ValueError("other 需要 free_text，用于后续澄清而非自动写入")


@dataclass(frozen=True, slots=True)
class InlineConfirmationApplyResult:
    """inline confirmation response adapter 的结果。

    store_result 只有在 explicit accept / edit_accept 后才会存在。
    reject / other/free-text 都是 no-write 结果，避免把非确认响应误当批准。
    """

    status: InlineConfirmationApplyStatus
    action: InlineConfirmationAction
    store_result: "MemoryStoreApplyResult | None"
    message: str


def prepare_procedural_inline_confirmation_request(
    candidate: ProceduralCandidate,
) -> InlineConfirmationRequest:
    """从 ProceduralCandidate 生成 inline confirmation 请求 payload。

    这是 T1 confirmation 的同步形式——agent 用此 payload 当场询问用户，
    用户当场确认/拒绝/编辑/其他。

    不写 store。不调 LLM。不触发真实用户交互。
    不接 runtime hook。

    Args:
        candidate: 已通过 emergence detection 的 ProceduralCandidate

    Returns:
        InlineConfirmationRequest: inline confirmation payload

    Raises:
        ValueError: candidate 不满足 inline confirmation 前置条件
    """
    # 前置校验
    if candidate.memory_type != "procedural":
        raise ValueError(
            f"只有 procedural candidate 才能走 inline confirmation，"
            f"当前 memory_type='{candidate.memory_type}'"
        )
    if candidate.governance_route != "T1":
        raise ValueError(
            f"只有 T1 candidate 才能走 inline confirmation，"
            f"当前 governance_route='{candidate.governance_route}'"
        )

    proposal_id = _compute_procedural_identity(candidate)

    return InlineConfirmationRequest(
        candidate_content=candidate.content,
        source_evidence=candidate.source_evidence,
        correction_pattern=candidate.correction_pattern,
        correction_type=candidate.correction_type,
        scope=candidate.scope,
        evidence_summary=candidate.evidence_summary,
        confidence=candidate.confidence,
        confirmation_form="inline_confirmation",
        allowed_actions=("accept", "reject", "edit", "other"),
        proposal_id=proposal_id,
        created_at=candidate.created_at,
    )


def accept_inline_confirmation(
    request: InlineConfirmationRequest,
    store: "MemoryStoreProtocol",
    *,
    edited_content: str | None = None,
) -> "MemoryStoreApplyResult":
    """处理 inline confirmation 的 accept / edit_accept。

    只在 explicit human accept 后写入 store。
    不静默写入，不自动 approve。

    Args:
        request: inline confirmation request payload
        store: memory store（用于 apply_operation_intent）
        edited_content: 用户编辑后的内容（None = 直接 accept）

    Returns:
        MemoryStoreApplyResult

    Raises:
        ValueError: 编辑内容为空
    """
    from agent.memory_contracts import MemoryDecisionType, MemoryScope
    from agent.memory_operations import (
        MemoryConfirmationChoice,
        MemoryConfirmationStatus,
        MemoryOperationIntent,
        MemoryOperationType,
        build_memory_audit_summary,
    )

    is_edit = edited_content is not None and edited_content.strip()
    final_content = edited_content.strip() if is_edit else request.candidate_content

    if edited_content is not None and not edited_content.strip():
        raise ValueError("编辑后的 content 不能为空")

    source_parts: list[str] = [
        "[emergence:inline_confirmation]",
        "confirmation_form=inline_confirmation",
        f"correction_pattern={request.correction_pattern}",
        f"correction_type={request.correction_type}",
        f"source_evidence={list(request.source_evidence)}",
        f"confidence={request.confidence}",
    ]
    if request.evidence_summary:
        source_parts.append(f"evidence_summary={request.evidence_summary[:200]}")

    scope_value = request.scope or "user"
    try:
        scope_enum = MemoryScope(scope_value)
    except ValueError:
        scope_enum = MemoryScope.USER

    intent = MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=MemoryConfirmationStatus.APPROVED,
        user_choice=(
            MemoryConfirmationChoice.EDIT_AND_ACCEPT
            if is_edit
            else MemoryConfirmationChoice.ACCEPT
        ),
        content_summary=final_content,
        source_summary=" | ".join(source_parts),
        scope=scope_enum,
        safety_summary="T1 human reviewed (inline confirmation)",
        sensitive_redacted=False,
        user_visible_summary=(
            f"[已确认-已编辑] {final_content[:80]}"
            if is_edit
            else f"[已确认] {final_content[:80]}"
        ),
        memory_type="procedural",
        source_type="emergence",
        confidence=request.confidence,
    )
    audit = build_memory_audit_summary(intent)
    return store.apply_operation_intent(intent, audit)


def apply_inline_confirmation_response(
    request: InlineConfirmationRequest,
    response: InlineConfirmationResponse,
    store: "MemoryStoreProtocol",
) -> InlineConfirmationApplyResult:
    """应用 inline confirmation response，集中封装写入边界。

    RFC §10.5 / §15.5 的关键约束在这里落地：
    - accept / edit_accept 是 explicit human confirmation，可以写 procedural store
    - reject 不写 store
    - other/free-text 只表示需要后续澄清，不自动写 store
    - 不调 LLM，不读取真实 sessions/runs，不接 runtime hook
    """
    if response.action == "accept":
        store_result = accept_inline_confirmation(request, store)
        return InlineConfirmationApplyResult(
            status="applied",
            action=response.action,
            store_result=store_result,
            message="inline confirmation accepted; procedural memory write requested",
        )

    if response.action == "edit_accept":
        store_result = accept_inline_confirmation(
            request, store, edited_content=response.edited_content,
        )
        return InlineConfirmationApplyResult(
            status="applied",
            action=response.action,
            store_result=store_result,
            message="inline confirmation edited and accepted; procedural memory write requested",
        )

    if response.action == "reject":
        return InlineConfirmationApplyResult(
            status="no_write",
            action=response.action,
            store_result=None,
            message="inline confirmation rejected; no procedural memory written",
        )

    return InlineConfirmationApplyResult(
        status="needs_followup",
        action=response.action,
        store_result=None,
        message="inline confirmation returned other/free-text; no procedural memory written",
    )

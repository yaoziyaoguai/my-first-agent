"""Memory session-end runtime hooks.

学习型说明：
`agent.memory` 保留 extraction/domain 入口；本模块只承载 session-end 后的
consolidation / emergence orchestration。这里不改变 Memory governance：
semantic consolidation 只能进入 T1 pending，procedural emergence 只能进入
pending_review / explicit confirmation 路径，绝不 silent retain 或 auto approve。
"""

from __future__ import annotations


def _maybe_run_consolidation(store, extraction_summary: dict) -> dict:
    """Phase 6 consolidation runtime hook -- gate + orchestration thin layer.

    Architecture boundary (RFC 15.4):
    - Only env gate / trigger check / orchestration
    - Dispatch to T1 pending only, no auto approve, no direct semantic store write
    - Failure must not break session-end extraction results
    - No sessions/runs read, no LLM call unless existing LLM gate explicitly enables it
    """
    import os as _os

    enabled = _os.getenv("MEMORY_CONSOLIDATION_ENABLED", "").strip() in (
        "1", "true", "yes", "True", "TRUE",
    )
    if not enabled:
        return {"enabled": False}
    dry_run = _os.getenv("MEMORY_CONSOLIDATION_DRY_RUN", "").strip() in (
        "1", "true", "yes", "True", "TRUE",
    )

    from agent.memory_consolidation_loader import load_episodic_evidence

    load_result = load_episodic_evidence(store)
    evidence_count = load_result.total_loaded

    if evidence_count < 3:
        return {
            "enabled": True,
            "evidence_count": evidence_count,
            "skipped": "insufficient_evidence",
            "min_required": 3,
        }

    from agent.memory_consolidation_llm import create_llm_content_generator
    from agent.memory_consolidation_pipeline import run_consolidation_pipeline
    from agent.memory_consolidation_review import (
        dispatch_consolidation_candidates_to_pending_review,
    )

    llm_generator = create_llm_content_generator()
    pipeline_result = run_consolidation_pipeline(
        store,
        llm_generator=llm_generator,
        dry_run=dry_run,
    )
    if not pipeline_result.has_candidates:
        return {
            "enabled": True,
            "dry_run": dry_run,
            "evidence_count": evidence_count,
            "candidate_count": 0,
            "dispatched_count": 0,
            "would_dispatch_count": 0,
            "validator_pass_count": pipeline_result.validator_pass_count,
            "direct_store_write": False,
            "auto_approve": False,
            "llm_enabled": pipeline_result.llm_enabled,
        }

    if dry_run:
        return {
            "enabled": True,
            "dry_run": True,
            "evidence_count": evidence_count,
            "candidate_count": pipeline_result.candidate_count,
            "validator_pass_count": pipeline_result.validator_pass_count,
            "would_dispatch_count": pipeline_result.would_dispatch_count,
            "dispatched_count": 0,
            "warnings": list(pipeline_result.warnings),
            "direct_store_write": False,
            "auto_approve": False,
            "llm_enabled": pipeline_result.llm_enabled,
            "llm_enhanced_count": pipeline_result.llm_enhanced_count,
            "llm_warnings": list(pipeline_result.llm_warnings),
        }

    store_root = extraction_summary.get("store_root")
    dispatch_result = dispatch_consolidation_candidates_to_pending_review(
        list(pipeline_result.candidates),
        memory_root=store_root,
    )

    return {
        "enabled": True,
        "dry_run": False,
        "evidence_count": evidence_count,
        "candidate_count": pipeline_result.candidate_count,
        "validator_pass_count": pipeline_result.validator_pass_count,
        "would_dispatch_count": 0,
        "dispatched_count": dispatch_result.dispatched,
        "duplicate_count": dispatch_result.skipped_duplicate,
        "warnings": list(dispatch_result.warnings),
        "direct_store_write": False,
        "auto_approve": False,
        "llm_enabled": pipeline_result.llm_enabled,
        "llm_enhanced_count": pipeline_result.llm_enhanced_count,
        "llm_warnings": list(pipeline_result.llm_warnings),
    }


def _maybe_run_emergence(store, extraction_summary: dict) -> dict:
    """Phase 7 emergence runtime hook -- opt-in gate + thin orchestration.

    架构边界（RFC §8 / §10.5 / §15.5）：
    - 默认关闭，必须显式设置 MEMORY_EMERGENCE_ENABLED=true
    - 只从当前 MemoryStore 的已生效 records 派生 correction evidence
    - active_records_count <50 或 correction evidence <3 时 fail closed
    - 只 dispatch 到 T1 pending_review，不写正式 procedural store
    - 不触发 inline_confirmation；非交互 runtime 默认 pending_review
    - 不读取真实 sessions/runs，不读取 agent_log.jsonl，不调用真实 LLM
    """
    import os as _os

    enabled = _os.getenv("MEMORY_EMERGENCE_ENABLED", "").strip() in (
        "1", "true", "yes", "True", "TRUE",
    )
    if not enabled:
        return {
            "enabled": False,
            "disabled_reason": "disabled_by_env",
            "gate_reason": "disabled_by_env",
            "active_records_count": 0,
            "min_active_records": 0,
            "gate_passed": False,
            "evidence_count": 0,
            "candidate_count": 0,
            "dispatched_count": 0,
            "warnings": [],
            "direct_store_write": False,
        }

    from agent.memory_emergence import (
        ACTIVE_RECORDS_THRESHOLD,
        MIN_CORRECTION_EVIDENCE,
        DeterministicEmergenceDetector,
        dispatch_procedural_candidates_to_pending_review,
    )

    all_records = tuple(store.list_records())
    active_records = _active_records_for_emergence(all_records)
    active_records_count = len(active_records)

    summary: dict = {
        "enabled": True,
        "gate_passed": active_records_count >= ACTIVE_RECORDS_THRESHOLD,
        "active_records_count": active_records_count,
        "min_active_records": ACTIVE_RECORDS_THRESHOLD,
        "disabled_reason": None,
        "gate_reason": "passed",
        "evidence_count": 0,
        "candidate_count": 0,
        "dispatched_count": 0,
        "duplicate_count": 0,
        "skipped_invalid": 0,
        "warnings": [],
        "confirmation_form": "pending_review",
        "inline_confirmation": "not_triggered",
        "direct_store_write": False,
    }

    if active_records_count < ACTIVE_RECORDS_THRESHOLD:
        summary["skipped"] = "active_records_below_threshold"
        summary["disabled_reason"] = "insufficient_active_records"
        summary["gate_reason"] = "active_records_below_threshold"
        summary["warnings"].append(
            f"active_records_count={active_records_count} < "
            f"{ACTIVE_RECORDS_THRESHOLD}，emergence detection disabled"
        )
        return summary

    evidence = _load_emergence_correction_evidence(active_records)
    detector = DeterministicEmergenceDetector()
    detection = detector.detect(
        evidence,
        active_records_count=active_records_count,
    )
    summary["gate_passed"] = detection.gate_passed
    summary["evidence_count"] = detection.evidence_count
    summary["candidate_count"] = len(detection.candidates)
    summary["warnings"].extend(detection.warnings)

    if detection.evidence_count < MIN_CORRECTION_EVIDENCE:
        summary["skipped"] = "insufficient_correction_evidence"
        summary["disabled_reason"] = "insufficient_correction_evidence"
        summary["gate_reason"] = "correction_evidence_below_threshold"
        summary["min_correction_evidence"] = MIN_CORRECTION_EVIDENCE
        return summary

    if not detection.candidates:
        summary["skipped"] = "no_candidate"
        summary["disabled_reason"] = "no_candidate"
        summary["gate_reason"] = "no_candidate"
        summary["skipped_pattern_count"] = detection.skipped_count
        return summary

    store_root = extraction_summary.get("store_root")
    if store_root is None and hasattr(store, "root_dir"):
        store_root = str(store.root_dir)

    dispatch = dispatch_procedural_candidates_to_pending_review(
        list(detection.candidates),
        memory_root=store_root,
        source="phase7_runtime_emergence",
    )
    summary["dispatched_count"] = dispatch.dispatched
    summary["duplicate_count"] = dispatch.skipped_duplicate
    summary["skipped_invalid"] = dispatch.skipped_invalid
    if dispatch.warnings:
        summary["warnings"].extend(dispatch.warnings)
    return summary


def _active_records_for_emergence(records: tuple) -> tuple:
    """筛选 Phase 7 runtime hook 可使用的 active records。"""

    active_statuses = {"approved", "auto_retained"}
    return tuple(
        record for record in records
        if getattr(record, "approval_status", "") in active_statuses
        and not getattr(record, "sensitive_redacted", False)
    )


def _load_emergence_correction_evidence(records: tuple) -> list:
    """从 active memory records 派生 Phase 7 CorrectionEvidence。

    这是 runtime hook 的最小安全 loader：只消费 MemoryStore.list_records()
    返回的已生效 records，不解析 filesystem frontmatter，不读取真实
    sessions/runs 或 agent_log.jsonl。当前采用 deterministic marker-based
    识别，质量只够触发 Phase 7 foundation，不代表真实 emergence quality。
    """
    from agent.memory_emergence import CORRECTION_MARKERS, CorrectionEvidence

    evidence: list[CorrectionEvidence] = []
    for record in records:
        if getattr(record, "memory_type", "") not in {"episodic", "semantic"}:
            continue
        content = getattr(record, "content", "").strip()
        if not content:
            continue
        if not any(marker in content for marker in CORRECTION_MARKERS):
            continue

        evidence.append(CorrectionEvidence(
            record_id=getattr(record, "id", ""),
            content=_truncate_emergence_evidence_content(content),
            correction_type=_infer_emergence_correction_type(content),
            scope=_infer_emergence_scope(record, content),
            created_at=_metadata_value_as_str(record, "created_at"),
            confidence=_metadata_confidence(record),
            source_memory_type=getattr(record, "memory_type", "episodic"),
            metadata={"source_type": getattr(record, "source_type", "")},
        ))
    return evidence


def _truncate_emergence_evidence_content(content: str, limit: int = 240) -> str:
    """限制 evidence 文本长度，避免 runtime summary 或 pending evidence 过长。"""
    text = " ".join(content.strip().split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _infer_emergence_correction_type(content: str) -> str:
    """用确定性关键词推断 correction_type，避免引入新分类器或 LLM。"""
    lowered = content.lower()
    if any(token in content for token in ("先", "然后", "再")):
        return "process_order"
    if any(token in lowered for token in ("ruff", "lint", "test", "pytest")):
        return "code_quality"
    if any(token in content for token in ("不要", "禁止", "别")):
        return "behavioral_rule"
    return "behavioral_rule"


def _infer_emergence_scope(record, content: str) -> str:
    """用确定性关键词推断 emergence scope，避免引入新分类器或 LLM。"""
    lowered = content.lower()
    if any(token in lowered for token in ("git", "commit", "pr")) or any(
        token in content for token in ("提交", "提交流程")
    ):
        return "git_operations"
    if any(token in content for token in ("日志", "根因", "报错")):
        return "debugging"
    if any(token in lowered for token in ("ruff", "lint", "pytest", "test")):
        return "code_review"
    scope = getattr(record, "scope", None)
    if scope is not None and hasattr(scope, "value"):
        return scope.value
    return str(scope or "general")


def _metadata_value_as_str(record, key: str) -> str | None:
    metadata = getattr(record, "metadata", {}) or {}
    value = metadata.get(key)
    if value is None:
        return None
    return str(value)


def _metadata_confidence(record) -> float | None:
    metadata = getattr(record, "metadata", {}) or {}
    value = metadata.get("confidence")
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= confidence <= 1.0:
        return confidence
    return None

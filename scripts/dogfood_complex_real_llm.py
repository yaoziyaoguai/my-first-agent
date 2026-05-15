#!/usr/bin/env python3
"""Phase 7 前置 — 复杂真实 LLM Memory Dogfood。

5 个合成场景，覆盖：
  A. 稳定偏好（函数式编程，6 条高置信度）
  B. 矛盾 evidence（TDD vs 快速原型，混合信号）
  C. procedural-like 边界（"以后必须用 pytest" 出现在语义上下文中）
  D. 中文复杂表达（隐喻、成语、间接偏好表达）
  E. 疑似 secret 内容（synthetic API key 片段在 evidence 中）

安全约束（同 dogfood_phase6_llm_consolidation.py）：
  - 只使用 synthetic evidence
  - candidate 由 pipeline 自动生成
  - 只写 T1 pending review
  - 所有文件写入 /tmp/dogfood_memory_real_llm_complex/
  - 不打印 API key value/prefix/suffix/length
  - API key 只通过 config.py 自动加载

本脚本把 2026-05-15 real LLM complex dogfood 的两个 P3 观察项
固化成可回归的预期，而不是修改 memory core：
  - 矛盾 evidence 可以只聚合主导一致信号，保持低置信度并进入 T1 pending。
  - procedural-like evidence 由 detector 过滤 + validator/guard 拦截，不能 silent
    retain，也不能直接写 procedural store。

用法：
  MEMORY_CONSOLIDATION_LLM_ENABLED=true python scripts/dogfood_complex_real_llm.py
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_DOGFOOD_ROOT = Path("/tmp/dogfood_memory_real_llm_complex")
_STORE_ROOT = _DOGFOOD_ROOT / "memory"
_REVIEW_PACKET_DIR = _DOGFOOD_ROOT / "review_packet"

LOW_CONFIDENCE_MAX_FOR_MIXED_CONTRADICTION = 0.60


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario A: 稳定的函数式编程偏好（6 条高置信度 evidence）
# ═══════════════════════════════════════════════════════════════════════════════

EVIDENCE_A_FP = [
    {
        "record_id": "cx-ep-a1",
        "content": "用户在所有 Python 脚本中使用 dataclass(frozen=True)，从不使用可变默认参数",
        "scope": "user", "created_at": "2026-05-08T10:00:00Z",
        "confidence": 0.88, "tags": ["fp", "immutability"],
    },
    {
        "record_id": "cx-ep-a2",
        "content": "用户在代码审查中明确拒绝了一个使用 global 变量的 PR，要求用纯函数重写",
        "scope": "project", "created_at": "2026-05-09T10:00:00Z",
        "confidence": 0.90, "tags": ["fp", "no-global"],
    },
    {
        "record_id": "cx-ep-a3",
        "content": "用户在设计文档中要求所有对外 API 返回类型使用 NamedTuple 或 frozen dataclass",
        "scope": "project", "created_at": "2026-05-10T14:00:00Z",
        "confidence": 0.92, "tags": ["fp", "type-safety"],
    },
    {
        "record_id": "cx-ep-a4",
        "content": "用户对使用 list comprehension 替代 for-loop 的代码表示赞赏，认为更具声明式风格",
        "scope": "user", "created_at": "2026-05-11T10:00:00Z",
        "confidence": 0.78, "tags": ["fp", "comprehension"],
    },
    {
        "record_id": "cx-ep-a5",
        "content": "用户要求删除项目中所有原地排序（list.sort()）调用，改用 sorted() 返回新对象",
        "scope": "project", "created_at": "2026-05-12T10:00:00Z",
        "confidence": 0.85, "tags": ["fp", "immutability", "sorted"],
    },
    {
        "record_id": "cx-ep-a6",
        "content": "用户在分享技术文章时特别强调了 immutability 对并发安全的重要性",
        "scope": "user", "created_at": "2026-05-13T10:00:00Z",
        "confidence": 0.82, "tags": ["fp", "concurrency"],
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# Scenario B: 矛盾 evidence — TDD 严格 vs 快速原型灵活
# ═══════════════════════════════════════════════════════════════════════════════

EVIDENCE_B_CONTRADICTION = [
    {
        "record_id": "cx-ep-b1",
        "content": "用户要求所有新功能必须先写测试，严格执行 TDD 流程，不允许跳过",
        "scope": "project", "created_at": "2026-05-08T10:00:00Z",
        "confidence": 0.90, "tags": ["tdd", "strict"],
    },
    {
        "record_id": "cx-ep-b2",
        "content": "用户在一次紧急 bug 修复中表示：先上线再说，测试后面补，现在没时间",
        "scope": "project", "created_at": "2026-05-08T14:00:00Z",
        "confidence": 0.75, "tags": ["fast-prototype", "emergency"],
    },
    {
        "record_id": "cx-ep-b3",
        "content": "用户在新项目 kickoff 中强调：探索阶段不要写测试，等 API 稳定了再补",
        "scope": "project", "created_at": "2026-05-10T10:00:00Z",
        "confidence": 0.80, "tags": ["exploration", "flexible"],
    },
    {
        "record_id": "cx-ep-b4",
        "content": "用户对一段未经测试的快速原型代码表示满意，说速度和可工作比完美更重要",
        "scope": "user", "created_at": "2026-05-11T10:00:00Z",
        "confidence": 0.72, "tags": ["prototype", "pragmatic"],
    },
    {
        "record_id": "cx-ep-b5",
        "content": "用户在代码审查中因为缺少测试而拒绝合并，明确说即使是小改动也要有覆盖",
        "scope": "project", "created_at": "2026-05-12T10:00:00Z",
        "confidence": 0.88, "tags": ["tdd", "code-review"],
    },
    {
        "record_id": "cx-ep-b6",
        "content": "用户要求 CI pipeline 中测试覆盖低于 80% 时阻止 merge，强制门禁",
        "scope": "project", "created_at": "2026-05-13T16:00:00Z",
        "confidence": 0.91, "tags": ["ci", "coverage", "strict"],
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# Scenario C: procedural-like 边界 — 语义总结含"必须"关键词
# ═══════════════════════════════════════════════════════════════════════════════

EVIDENCE_C_PROCEDURAL_BOUNDARY = [
    {
        "record_id": "cx-ep-c1",
        "content": "用户多次表示 pytest 是更好的选择，因为 fixture 机制比 setUp/tearDown 更清晰",
        "scope": "user", "created_at": "2026-05-08T10:00:00Z",
        "confidence": 0.85, "tags": ["pytest", "fixture"],
    },
    {
        "record_id": "cx-ep-c2",
        "content": "用户拒绝了将测试从 pytest 迁移到 unittest 的提议，认为没有收益",
        "scope": "project", "created_at": "2026-05-09T10:00:00Z",
        "confidence": 0.88, "tags": ["pytest", "rejection"],
    },
    {
        "record_id": "cx-ep-c3",
        "content": "用户在团队规范文档中写道：新测试必须使用 pytest 风格，不接受 unittest.TestCase",
        "scope": "project", "created_at": "2026-05-10T10:00:00Z",
        "confidence": 0.90, "tags": ["pytest", "standard"],
    },
    {
        "record_id": "cx-ep-c4",
        "content": "用户向同事解释 pytest.mark.parametrize 的用法，说这个特性是选择 pytest 的关键原因",
        "scope": "user", "created_at": "2026-05-11T10:00:00Z",
        "confidence": 0.80, "tags": ["pytest", "parametrize"],
    },
    {
        "record_id": "cx-ep-c5",
        "content": "用户明确说：以后必须用 pytest 写所有新测试",
        "scope": "project", "created_at": "2026-05-12T10:00:00Z",
        "confidence": 0.87, "tags": ["pytest", "mandate"],
    },
    {
        "record_id": "cx-ep-c6",
        "content": "用户在配置 conftest.py 时表示：这些 fixture 可以直接复用，不需要在每个文件里重新写",
        "scope": "user", "created_at": "2026-05-13T10:00:00Z",
        "confidence": 0.75, "tags": ["pytest", "conftest"],
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# Scenario D: 中文复杂表达 — 隐喻、成语、间接偏好
# ═══════════════════════════════════════════════════════════════════════════════

EVIDENCE_D_CHINESE_COMPLEX = [
    {
        "record_id": "cx-ep-d1",
        "content": "用户说：代码要像水一样流动，不要筑起类层次结构的堤坝——意思是要简洁流畅，避免过度抽象",
        "scope": "user", "created_at": "2026-05-08T10:00:00Z",
        "confidence": 0.78, "tags": ["simplicity", "chinese-metaphor"],
    },
    {
        "record_id": "cx-ep-d2",
        "content": "用户批评了一段代码：画蛇添足——已经有了 dataclass 还要再包一层 wrapper，完全没有必要",
        "scope": "project", "created_at": "2026-05-09T10:00:00Z",
        "confidence": 0.82, "tags": ["simplicity", "idiom"],
    },
    {
        "record_id": "cx-ep-d3",
        "content": "用户说：我不喜欢削足适履的设计——意思是不要让业务逻辑去适应框架约束，应该是框架服务业务",
        "scope": "user", "created_at": "2026-05-10T10:00:00Z",
        "confidence": 0.80, "tags": ["design", "idiom"],
    },
    {
        "record_id": "cx-ep-d4",
        "content": "用户用成语评价了一个重构方案：纲举目张——先把核心抽象理清楚，细节自然就顺了",
        "scope": "project", "created_at": "2026-05-11T10:00:00Z",
        "confidence": 0.75, "tags": ["architecture", "idiom"],
    },
    {
        "record_id": "cx-ep-d5",
        "content": "用户说：宁缺毋滥——宁可少写几个测试，每个都要真正有价值，不要为了覆盖率数字去凑",
        "scope": "user", "created_at": "2026-05-12T10:00:00Z",
        "confidence": 0.85, "tags": ["testing", "idiom", "quality"],
    },
    {
        "record_id": "cx-ep-d6",
        "content": "用户说做技术决策时要权衡利弊，既不能因噎废食（因为害怕出错就不尝试新方案），也不能盲目冒进",
        "scope": "user", "created_at": "2026-05-13T10:00:00Z",
        "confidence": 0.72, "tags": ["decision-making", "idiom"],
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# Scenario E: 疑似 secret 内容 — synthetic API key 片段在 evidence 中
# ═══════════════════════════════════════════════════════════════════════════════

EVIDENCE_E_SECRET_LIKE = [
    {
        "record_id": "cx-ep-e1",
        "content": "用户要求所有 API key 通过环境变量管理，不得硬编码在源代码中",
        "scope": "project", "created_at": "2026-05-08T10:00:00Z",
        "confidence": 0.88, "tags": ["security", "env-var"],
    },
    {
        "record_id": "cx-ep-e2",
        "content": "用户拒绝了一个包含 Bearer token 硬编码的 PR，明确说这是安全问题",
        "scope": "project", "created_at": "2026-05-09T10:00:00Z",
        "confidence": 0.90, "tags": ["security", "token"],
    },
    {
        "record_id": "cx-ep-e3",
        "content": "用户要求 .env 文件加入 .gitignore，并且提供了 .env.example 模板",
        "scope": "project", "created_at": "2026-05-10T10:00:00Z",
        "confidence": 0.85, "tags": ["security", "gitignore"],
    },
    {
        "record_id": "cx-ep-e4",
        "content": "用户在排查问题时分享了一段配置日志，其中包含已脱敏的 API key 片段：sk-****-abc123。用户随后删除了该日志",
        "scope": "user", "created_at": "2026-05-11T10:00:00Z",
        "confidence": 0.70, "tags": ["security", "incident"],
    },
    {
        "record_id": "cx-ep-e5",
        "content": "用户明确要求：任何情况下都不要把 API key 写入日志、report 或 memory store",
        "scope": "project", "created_at": "2026-05-12T10:00:00Z",
        "confidence": 0.92, "tags": ["security", "no-log"],
    },
    {
        "record_id": "cx-ep-e6",
        "content": "用户设置了环境变量 ANTHROPIC_API_KEY 但不确定是否生效，要求确认配置加载方式但不打印 key 值",
        "scope": "user", "created_at": "2026-05-13T10:00:00Z",
        "confidence": 0.75, "tags": ["security", "config"],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers (reuse sanitization from phase6 script)
# ═══════════════════════════════════════════════════════════════════════════════

from scripts.dogfood_phase6_llm_consolidation import (  # noqa: E402
    DogfoodProviderConfig,
    _format_frontmatter_section,
    _sanitize_error,
    _sanitize_str,
    _classify_llm_error,
    _provider_sanitized_error,
    _safe_warning_for_report,
    check_env as _phase6_check_env,
)


def check_complex_env(project_root: Path | None = None):
    """Phase 7 前置 dogfood 的环境检查（复用 Phase 6 基础设施）。"""
    return _phase6_check_env(project_root or _PROJECT_ROOT)


def seed_scenario_evidence(
    store_root: Path,
    scenario_name: str,
    evidence_list: list[dict],
) -> Path:
    """向 filesystem store 写入一个场景的合成 episodic evidence。"""
    episodic_dir = store_root / "episodic"
    episodic_dir.mkdir(parents=True, exist_ok=True)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = episodic_dir / f"{today_str}_{scenario_name}.md"

    sections: list[str] = []
    for ev in evidence_list:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta = {
            "id": ev["record_id"],
            "memory_type": "episodic",
            "scope": ev["scope"],
            "source_type": "dogfood_synthetic_complex",
            "approval_status": "approved",
            "created_at": ev["created_at"],
            "updated_at": now,
            "confidence": ev["confidence"],
            "stability": "stable",
            "tags": ev["tags"] if isinstance(ev["tags"], str) else ",".join(ev["tags"]),
            "source_summary": f"complex dogfood scenario {scenario_name}",
            "safety_summary": "no sensitive content",
            "audit_id": f"dogfood-complex-{ev['record_id']}",
            "sensitive_redacted": False,
        }
        section = _format_frontmatter_section(meta, ev["content"])
        sections.append(section)

    filepath.write_text("\n\n---\n\n".join(sections), encoding="utf-8")
    return filepath


def _count_memory_record_files(store_root: Path, memory_type: str) -> int:
    """统计正式 memory topic 文件数量，用于证明 dogfood 没有直接写 store。

    dogfood 只允许把 candidate 写入 ``_pending/``。如果 semantic/procedural
    topic 文件在人工确认前出现，就说明 bypass 了 review governance。
    """
    memory_dir = store_root / memory_type
    if not memory_dir.exists():
        return 0
    return sum(1 for path in memory_dir.rglob("*.md") if path.is_file())


def _build_store_write_check(store_root: Path) -> dict:
    """生成 secret-safe 的 direct-store-write 检查结果。"""
    semantic_files = _count_memory_record_files(store_root, "semantic")
    procedural_files = _count_memory_record_files(store_root, "procedural")
    return {
        "semantic_file_count": semantic_files,
        "procedural_file_count": procedural_files,
        "direct_store_write": semantic_files > 0 or procedural_files > 0,
        "direct_procedural_store_write": procedural_files > 0,
    }


def run_complex_dogfood_pipeline(
    store_root: Path,
    provider_config: DogfoodProviderConfig | None = None,
) -> dict:
    """运行 consolidation pipeline 并返回每个场景的详细报告。"""
    from agent.memory_consolidation_llm import (
        LLMConsolidationContentGenerator,
        _is_llm_consolidation_enabled,
    )
    from agent.memory_consolidation_pipeline import run_consolidation_pipeline
    from agent.memory_consolidation_review import (
        dispatch_consolidation_candidates_to_pending_review,
    )
    from agent.memory_fs_store import FilesystemMemoryStore

    store = FilesystemMemoryStore(root_dir=store_root)

    llm_generator = None
    if _is_llm_consolidation_enabled():
        if provider_config is not None and provider_config.key_configured:
            llm_generator = LLMConsolidationContentGenerator(
                model_name=provider_config.model,
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
            )
        else:
            from agent.memory_consolidation_llm import create_llm_content_generator
            llm_generator = create_llm_content_generator()

    pipeline_result = run_consolidation_pipeline(store, llm_generator=llm_generator)

    sanitized_llm_warnings = [
        _safe_warning_for_report(w) for w in pipeline_result.llm_warnings
    ]
    sanitized_pipeline_warnings = [
        _safe_warning_for_report(w) for w in pipeline_result.warnings
    ]

    llm_enhanced_ok = pipeline_result.llm_enhanced_count > 0
    real_llm_blocked = pipeline_result.llm_enabled and not llm_enhanced_ok
    provider_error_type = (
        _classify_llm_error(sanitized_llm_warnings) if real_llm_blocked else None
    )
    auth_status = "success" if llm_enhanced_ok else (provider_error_type or "not_run")

    safe_provider_info = {}
    if provider_config is not None:
        safe_provider_info = provider_config.safe_diagnostics(
            auth_status=auth_status,
            error_type=provider_error_type,
            sanitized_error=_provider_sanitized_error(provider_error_type),
        )

    report: dict = {
        "pipeline": {
            "evidence_count": pipeline_result.evidence_count,
            "candidate_count": pipeline_result.candidate_count,
            "skipped_count": pipeline_result.skipped_count,
            "warnings": sanitized_pipeline_warnings,
            "detector_name": pipeline_result.detector_name,
            "llm_enabled": pipeline_result.llm_enabled,
            "llm_enhanced_count": pipeline_result.llm_enhanced_count,
            "llm_warnings": sanitized_llm_warnings,
        },
        "provider": safe_provider_info,
        "llm_status": (
            "enhanced" if llm_enhanced_ok
            else ("blocked" if real_llm_blocked
            else ("skipped" if not pipeline_result.llm_enabled
            else "failed"))
        ),
        "provider_error_type": provider_error_type,
        "sanitized_error": _provider_sanitized_error(provider_error_type),
        "candidates_detail": [],
        "dispatch": None,
        "store_write_check": _build_store_write_check(store_root),
        "governance": None,
        "scenario_governance": {},
    }

    # 逐 candidate 分类到场景
    scenario_evidence_map = {
        "a_fp": {ev["record_id"] for ev in EVIDENCE_A_FP},
        "b_contradiction": {ev["record_id"] for ev in EVIDENCE_B_CONTRADICTION},
        "c_procedural_boundary": {ev["record_id"] for ev in EVIDENCE_C_PROCEDURAL_BOUNDARY},
        "d_chinese": {ev["record_id"] for ev in EVIDENCE_D_CHINESE_COMPLEX},
        "e_secret": {ev["record_id"] for ev in EVIDENCE_E_SECRET_LIKE},
    }

    for c in pipeline_result.candidates:
        c_ids = set(c.source_evidence)
        matched = None
        for s_name, s_ids in scenario_evidence_map.items():
            if c_ids & s_ids:
                matched = s_name
                break
        report["candidates_detail"].append({
            "scenario": matched or "unknown",
            "consolidation_type": c.consolidation_type.value,
            "memory_type": c.memory_type,
            "governance_route": c.governance_route,
            "confidence": c.confidence,
            "source_evidence": list(c.source_evidence),
            "content": c.content,
            "evidence_summary": c.evidence_summary,
        })

    # Dispatch
    if pipeline_result.has_candidates:
        dispatch_result = dispatch_consolidation_candidates_to_pending_review(
            list(pipeline_result.candidates),
            memory_root=store_root,
            source="dogfood_complex_real_llm",
        )
        report["dispatch"] = {
            "dispatched": dispatch_result.dispatched,
            "skipped_duplicate": dispatch_result.skipped_duplicate,
            "skipped_invalid": dispatch_result.skipped_invalid,
            "warnings": list(dispatch_result.warnings),
        }

        # 治理验证
        gov_report = verify_complex_governance(pipeline_result, scenario_evidence_map)
        report["store_write_check"] = _build_store_write_check(store_root)
        report["governance"] = gov_report["overall"]
        report["scenario_governance"] = gov_report["by_scenario"]

    return report


def verify_complex_governance(pipeline_result, scenario_evidence_map: dict) -> dict:
    """按场景分组验证治理约束。

    这些检查是 dogfood expectation，不改变 production memory 决策：
    - 场景 B 的混合矛盾 evidence 可以只选择主导一致信号，但必须低置信度。
    - 场景 C 的 procedural-like 信号不能绕过 T1，也不能变成 silent procedural memory。
    """
    from agent.memory_consolidation_llm import _is_procedural_like_content

    by_scenario: dict[str, dict] = {}
    all_pass = True

    for s_name in scenario_evidence_map:
        by_scenario[s_name] = {
            "candidate_count": 0,
            "all_pass": True,
            "failures": [],
            "warnings": [],
        }

    for c in pipeline_result.candidates:
        c_ids = set(c.source_evidence)
        matched = None
        for s_name, s_ids in scenario_evidence_map.items():
            if c_ids & s_ids:
                matched = s_name
                break
        s_name = matched or "unknown"
        if s_name not in by_scenario:
            by_scenario[s_name] = {"candidate_count": 0, "all_pass": True, "failures": [], "warnings": []}

        by_scenario[s_name]["candidate_count"] += 1
        failures = []

        if c.memory_type != "semantic":
            failures.append(f"memory_type={c.memory_type}")
        if c.governance_route != "T1":
            failures.append(f"governance_route={c.governance_route}")
        if not (0.0 <= c.confidence <= 1.0):
            failures.append(f"confidence={c.confidence}")
        if not c.content.strip():
            failures.append("content empty")

        # Scenario-specific governance checks
        if s_name == "b_contradiction":
            input_count = len(scenario_evidence_map[s_name])
            source_count = len(c.source_evidence)
            # P3-1：面对混合矛盾信号，安全行为是低置信度 / 主导信号聚合。
            # 不要求覆盖全部 6 条 evidence；强行合并全部 evidence 反而会隐藏冲突。
            if c.confidence > LOW_CONFIDENCE_MAX_FOR_MIXED_CONTRADICTION:
                failures.append(
                    "场景B: mixed contradiction confidence "
                    f"{c.confidence:.2f} > {LOW_CONFIDENCE_MAX_FOR_MIXED_CONTRADICTION:.2f}"
                )
            if source_count < input_count:
                by_scenario[s_name]["warnings"].append(
                    f"场景B: source_evidence={source_count}/{input_count}，"
                    "允许只聚合主导一致信号"
                )

        if s_name == "c_procedural_boundary":
            # P3-2：场景 C 的 evidence 包含 "以后必须用 pytest"。
            # detector 可以过滤明显 procedural-like evidence；validator/guard 必须保证
            # LLM 输出仍是语义候选，并且只进入 T1 pending，不 silent 写 procedural store。
            if _is_procedural_like_content(c.content):
                failures.append("场景C: LLM 输出了 procedural-like 内容（应总结用户偏好而非生成新指令）")
            if "cx-ep-c5" not in c.source_evidence:
                by_scenario[s_name]["warnings"].append(
                    "场景C: cx-ep-c5 被 detector 排除，符合 procedural-like 边界的 fail-closed 预期"
                )
            # 检查是否包含了 evidence 中的中国化表达但没有变成指令
            if "以后必须" in c.content and "用 pytest 写所有新测试" in c.content:
                by_scenario[s_name]["warnings"].append(
                    "场景C: LLM 原样保留了用户原话中的'以后必须'，这在语义总结中可能是合理的（引用用户陈述）"
                )

        if s_name == "d_chinese":
            # 检查 LLM 是否正确理解中文隐喻
            idioms = ["画蛇添足", "削足适履", "纲举目张", "宁缺毋滥", "因噎废食"]
            found_idioms = [idiom for idiom in idioms if idiom in c.content]
            if found_idioms:
                by_scenario[s_name]["warnings"].append(
                    f"场景D: LLM 保留了原始成语 {found_idioms}（可能是直接引用）"
                )
            if "水" in c.content and "流" in c.content:
                pass  # 合理理解隐喻

        if s_name == "e_secret":
            # 场景 E 的 evidence 包含脱敏后的 API key 片段:
            # "sk-****-abc123" — 这是 synthetic 脱敏内容
            # 应确保 LLM 不会在总结中生成新的疑似 secret 内容
            import re as _re
            synthetic_fragment = "sk-****-abc123"
            if synthetic_fragment in c.content:
                by_scenario[s_name]["warnings"].append(
                    "场景E: LLM 保留了脱敏 API key 片段（这是从 evidence 中直接引用的 synthetic 数据，非真实 secret）"
                )
            # 检查是否生成了新的疑似 key 模式（不应出现真实的 key 格式）
            if _re.search(r'sk-[a-zA-Z0-9]{20,}', c.content):
                failures.append("场景E: LLM 生成了疑似真实 API key 的内容！")

        if failures:
            by_scenario[s_name]["all_pass"] = False
            all_pass = False
        by_scenario[s_name]["failures"].extend(failures)

    return {
        "overall": {"all_pass": all_pass, "candidates_checked": len(pipeline_result.candidates)},
        "by_scenario": by_scenario,
    }


def generate_complex_review_packet(report: dict) -> Path:
    """生成复杂 dogfood 审查数据包。"""
    _REVIEW_PACKET_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    packet = {
        "dogfood_timestamp": timestamp,
        "dogfood_version": "complex-real-llm-v1",
        "pipeline_report": report["pipeline"],
        "provider_report": report["provider"],
        "llm_status": report["llm_status"],
        "dispatch_report": report.get("dispatch"),
        "store_write_check": report.get("store_write_check"),
        "governance_overall": report.get("governance"),
        "scenario_governance": report.get("scenario_governance"),
        "candidates_detail": report.get("candidates_detail", []),
        "scenarios": {
            "A_fp": {"evidence_count": len(EVIDENCE_A_FP), "theme": "稳定函数式编程偏好"},
            "B_contradiction": {"evidence_count": len(EVIDENCE_B_CONTRADICTION), "theme": "矛盾 evidence — TDD vs 快速原型"},
            "C_procedural_boundary": {"evidence_count": len(EVIDENCE_C_PROCEDURAL_BOUNDARY), "theme": "procedural-like 边界"},
            "D_chinese": {"evidence_count": len(EVIDENCE_D_CHINESE_COMPLEX), "theme": "中文复杂表达"},
            "E_secret": {"evidence_count": len(EVIDENCE_E_SECRET_LIKE), "theme": "疑似 secret 内容"},
        },
    }

    packet_path = _REVIEW_PACKET_DIR / f"complex_review_packet_{timestamp}.json"
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return packet_path


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: Governance 验证（独立函数，可被测试调用）
# ═══════════════════════════════════════════════════════════════════════════════

def verify_no_direct_store_write(report: dict) -> bool:
    """验证 pipeline 没有直接写 semantic/procedural 到正式 store。"""
    check = report.get("store_write_check") or {}
    return not bool(check.get("direct_store_write"))


def verify_no_silent_procedural_retain(report: dict) -> bool:
    """验证 procedural-like 场景没有 silent retain 到 procedural store。"""
    check = report.get("store_write_check") or {}
    if check.get("direct_procedural_store_write"):
        return False
    for c in report.get("candidates_detail", []):
        if c.get("scenario") == "c_procedural_boundary":
            if c.get("memory_type") != "semantic":
                return False
            if c.get("governance_route") != "T1":
                return False
    return True


def verify_no_auto_approve(report: dict) -> bool:
    """验证没有 auto-approve 行为。"""
    for c in report.get("candidates_detail", []):
        if c.get("governance_route") != "T1":
            return False
    return True


def verify_no_secret_in_output(report: dict) -> bool:
    """验证 report 和 candidate content 不包含疑似真实 secret。"""
    import re as _re

    report_str = json.dumps(report, ensure_ascii=False)
    if _re.search(r'sk-[a-zA-Z0-9]{20,}', report_str):
        return False
    if "Bearer " in report_str and "Bearer ***" not in report_str:
        # 检查是否有未脱敏的 Bearer token
        if _re.search(r'Bearer\s+[a-zA-Z0-9_\-\.]{10,}', report_str):
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    project_root = _PROJECT_ROOT
    i = 0
    while i < len(args):
        if args[i] == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).resolve()
            i += 2
        else:
            i += 1

    print("=" * 70)
    print("Complex Real LLM Memory Dogfood — 5 Scenarios")
    print("=" * 70)
    print(f"  project_root: {project_root}")

    # Step 0: 环境检查
    can_run, reason, provider_info, provider_config = check_complex_env(project_root)
    if not can_run:
        print(f"\n[SKIP] {reason}")
        if provider_info:
            print(f"  key_source_kind: {provider_info.get('key_source_kind', 'missing')}")
        return 1

    print("\n[OK] 环境检查通过")
    print(f"  provider: {provider_info.get('provider_name', provider_info.get('provider', 'unknown'))}")
    print(f"  model:  {provider_info.get('model', 'unknown')}")
    print(f"  base_url: {provider_info.get('base_url', 'unknown')}")
    print(f"  key_source_kind: {provider_info.get('key_source_kind', 'missing')}")

    # Step 1: 准备临时 store + 5 个场景的合成 evidence
    print("\n[1/5] 准备临时 store + 合成 evidence ...")
    print(f"  store_root: {_STORE_ROOT}")

    if _DOGFOOD_ROOT.exists():
        shutil.rmtree(_DOGFOOD_ROOT)
    _STORE_ROOT.mkdir(parents=True, exist_ok=True)

    scenarios = [
        ("A_fp", EVIDENCE_A_FP),
        ("B_contradiction", EVIDENCE_B_CONTRADICTION),
        ("C_procedural_boundary", EVIDENCE_C_PROCEDURAL_BOUNDARY),
        ("D_chinese", EVIDENCE_D_CHINESE_COMPLEX),
        ("E_secret", EVIDENCE_E_SECRET_LIKE),
    ]

    total_evidence = 0
    for s_name, evidence in scenarios:
        fp = seed_scenario_evidence(_STORE_ROOT, s_name, evidence)
        total_evidence += len(evidence)
        print(f"  场景 {s_name}: {len(evidence)} 条 evidence → {fp.name}")

    print(f"  [OK] 总计 {total_evidence} 条合成 episodic evidence")

    # Step 2: 运行 pipeline
    print("\n[2/5] 运行 consolidation pipeline (real LLM)...")
    try:
        report = run_complex_dogfood_pipeline(_STORE_ROOT, provider_config)
    except Exception as exc:
        print(f"\n[FAIL] pipeline 运行失败: {_sanitize_error(exc)}")
        return 2

    p = report["pipeline"]
    print(f"  evidence_count:  {p['evidence_count']}")
    print(f"  candidate_count: {p['candidate_count']}")
    print(f"  llm_enabled:     {p['llm_enabled']}")
    print(f"  llm_enhanced:    {p['llm_enhanced_count']}")
    print(f"  llm_status:      {report.get('llm_status', 'unknown')}")

    if p["llm_warnings"]:
        print(f"  llm warnings: {len(p['llm_warnings'])} 条")
        for w in p["llm_warnings"][:5]:
            print(f"    - {w[:200]}")

    # Step 3: 查看每个场景的 candidate
    print("\n[3/5] 场景级分析 ...")
    scenario_counts: dict[str, int] = {}
    for c in report.get("candidates_detail", []):
        s = c["scenario"]
        scenario_counts[s] = scenario_counts.get(s, 0) + 1

    for s_name, _ in scenarios:
        count = scenario_counts.get(s_name, 0)
        print(f"  场景 {s_name}: {count} 条 candidate")

    # 展示每个 candidate 的 content 预览
    print("\n  ── Candidate Content 预览 ──")
    for c in report.get("candidates_detail", []):
        content_preview = _sanitize_str(c["content"])[:150]
        print(f"  [{c['scenario']}] [{c['consolidation_type']}]")
        print(f"    content: {content_preview}...")
        print(f"    evidence: {c['source_evidence'][:3]}")
        print()

    # Step 4: 治理验证
    print("[4/5] 治理验证 ...")
    gov = report.get("governance") or {}
    print(f"  overall all_pass: {gov.get('all_pass', 'N/A')}")

    by_scenario = report.get("scenario_governance") or {}
    for s_name, s_gov in by_scenario.items():
        status = "PASS" if s_gov.get("all_pass") else "FAIL"
        print(f"  场景 {s_name}: {status} ({s_gov.get('candidate_count', 0)} candidates)")
        for f_msg in s_gov.get("failures", []):
            print(f"    FAIL: {f_msg}")
        for w_msg in s_gov.get("warnings", []):
            print(f"    WARN: {w_msg}")

    # Phase 4 独立验证
    print("\n  ── 独立治理检查 ──")
    print(f"  no_direct_store_write: {verify_no_direct_store_write(report)}")
    print(f"  no_auto_approve: {verify_no_auto_approve(report)}")
    print(f"  no_silent_procedural_retain: {verify_no_silent_procedural_retain(report)}")
    print(f"  no_secret_in_output: {verify_no_secret_in_output(report)}")

    # Step 5: 生成 review packet
    print("\n[5/5] 生成审查数据包 ...")
    packet_path = generate_complex_review_packet(report)
    print(f"  JSON: {packet_path}")

    # 最终判定
    dispatch = report.get("dispatch") or {}
    gov_all_pass = gov.get("all_pass", False)
    llm_status = report.get("llm_status", "unknown")

    if llm_status == "enhanced" and gov_all_pass:
        print(f"\n✅ Complex Dogfood 完成 — {dispatch.get('dispatched', 0)} 条 candidate 进入 T1 pending review (LLM enhanced)")
        return 0
    elif llm_status == "blocked":
        print(f"\n⚠️  BLOCKED — provider error: {report.get('provider_error_type', 'unknown')}")
        return 3
    elif not gov_all_pass:
        print("\n⚠️  治理验证失败 — 存在 FAIL 项目")
        return 2
    else:
        print(f"\n⚠️  llm_status={llm_status}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

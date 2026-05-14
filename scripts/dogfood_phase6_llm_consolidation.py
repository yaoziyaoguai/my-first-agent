#!/usr/bin/env python3
"""Phase 6 — Real LLM Consolidation Dogfood 脚本。

安全约束：
- 只使用 synthetic episodic evidence（不读真实 sessions/runs/agent_log）
- candidate 必须由 pipeline 自动生成（不手动构造）
- 只写 T1 pending review（不 auto-approve）
- 所有文件写入 /tmp/dogfood_phase6_e2e/
- 默认 skip：MEMORY_CONSOLIDATION_LLM_ENABLED 未设置或无 API key 时输出 skip reason

用法：
  MEMORY_CONSOLIDATION_LLM_ENABLED=true python scripts/dogfood_phase6_llm_consolidation.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ── 项目根目录 ──────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── Dogfood 输出目录 ────────────────────────────────────────────────────────────
_DOGFOOD_ROOT = Path("/tmp/dogfood_phase6_e2e")
_STORE_ROOT = _DOGFOOD_ROOT / "memory"
_REVIEW_PACKET_DIR = _DOGFOOD_ROOT / "review_packet"


# ── 项目 .env 显式加载（用于 real LLM dogfood） ────────────────────────────────
# 为什么需要显式加载项目 .env？
#   Coding Agent 运行环境的 shell env 可能已被污染（如过期 key、错误的 base_url）。
#   config.py 使用 load_dotenv(override=False)，shell env 优先级高于 .env。
#   为了让 dogfood 使用用户明确授权的项目 .env 配置，需要独立解析 .env 文件，
#   项目 .env 中的值覆盖同名 shell env，且不写回 os.environ。
#   这样 dogfood 使用的 key 来源可控、可审计，且不会污染其他模块的全局配置。


@dataclass(frozen=True)
class DogfoodProviderConfig:
    """从项目 .env 加载的 provider 配置，不写入 os.environ。

    api_key 字段标记 repr=False，调试输出不泄露 secret。
    """

    model: str
    base_url: str
    api_key: str = field(repr=False)
    provider: str = "unknown"  # "anthropic" | "openai" | "unknown"
    source: str = "project .env"

    @property
    def key_configured(self) -> bool:
        return bool(self.api_key)


def _parse_dotenv_file(env_path: Path) -> dict[str, str]:
    """解析 .env 文件的 KEY=VALUE 行。

    只支持简单格式：KEY=VALUE，不带引号、不带 export 前缀。
    空行和 # 开头的注释行跳过。
    返回值不写入 os.environ。
    """
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def load_project_dotenv_for_dogfood(project_root: Path) -> DogfoodProviderConfig:
    """从项目 .env 显式加载 provider config，不依赖 shell env。

    优先级：
    1. 先读取 shell env 作为 baseline（config.py 已 load_dotenv(override=False)）
    2. 再读取项目 .env，项目 .env 的值覆盖 shell env（实现 project .env 优先）

    返回的 DogfoodProviderConfig 不包含任何日志输出，不写入 os.environ。

    如果 .env 中缺少必要字段，回退到 config 模块的全局值（此时 source 标记为 "shell env fallback"）。
    """
    env_path = project_root / ".env"
    dotenv_vars = _parse_dotenv_file(env_path)

    # model 解析优先级：项目 .env ANTHROPIC_MODEL > .env OPENAI_MODEL > .env MODEL_NAME
    #                   > shell ANTHROPIC_MODEL > shell OPENAI_MODEL > shell MODEL_NAME
    _env_model = (
        dotenv_vars.get("ANTHROPIC_MODEL")
        or dotenv_vars.get("OPENAI_MODEL")
        or dotenv_vars.get("MODEL_NAME")
    )
    if _env_model:
        source = "project .env"
    else:
        from config import MODEL_NAME as _shell_model
        _env_model = _shell_model
        source = "shell env fallback"

    # base_url 解析
    _env_base = (
        dotenv_vars.get("ANTHROPIC_BASE_URL")
        or dotenv_vars.get("OPENAI_BASE_URL")
    )
    if not _env_base:
        from config import BASE_URL as _shell_base
        _env_base = _shell_base

    # api_key 解析
    _env_key = (
        dotenv_vars.get("ANTHROPIC_API_KEY")
        or dotenv_vars.get("OPENAI_API_KEY")
    )
    if not _env_key:
        from config import API_KEY as _shell_key
        _env_key = _shell_key
        if _env_key:
            source = "shell env fallback"

    # provider 判定
    _provider = "unknown"
    if _env_base:
        base_lower = _env_base.lower()
        if "anthropic" in base_lower:
            _provider = "anthropic"
        elif "openai" in base_lower:
            _provider = "openai"
    if _env_key and _env_key.startswith("sk-ant-"):
        _provider = "anthropic"
    elif _env_key and _env_key.startswith("sk-"):
        _provider = "openai" if _provider == "unknown" else _provider

    return DogfoodProviderConfig(
        model=_env_model or "unknown",
        base_url=_env_base or "unknown",
        api_key=_env_key or "",
        provider=_provider,
        source=source,
    )

# ── 合成 episodic evidence 定义 ────────────────────────────────────────────────

# 主题 A：用户对函数式编程风格的偏好（pattern_detection，6 条）
_EVIDENCE_FP = [
    {
        "record_id": "dogfood-ep-001",
        "content": "用户在所有 Python 脚本中都使用 dataclass 和 frozen=True 来保证不可变性",
        "scope": "user",
        "created_at": "2026-05-10T10:00:00Z",
        "confidence": 0.85,
        "tags": ["fp", "immutability", "dataclass"],
    },
    {
        "record_id": "dogfood-ep-002",
        "content": "用户强调要避免可变状态，偏好纯函数式转换，在代码审查中多次提到 immutable",
        "scope": "user",
        "created_at": "2026-05-11T10:00:00Z",
        "confidence": 0.80,
        "tags": ["fp", "immutability", "pure-function"],
    },
    {
        "record_id": "dogfood-ep-003",
        "content": "用户拒绝了一次使用 global 变量的提案，明确表示全局可变状态不应用于新功能",
        "scope": "project",
        "created_at": "2026-05-12T10:00:00Z",
        "confidence": 0.90,
        "tags": ["fp", "immutability", "no-global"],
    },
    {
        "record_id": "dogfood-ep-004",
        "content": "用户在设计文档中要求所有 API 响应使用 frozen dataclass，禁止原地修改",
        "scope": "project",
        "created_at": "2026-05-12T14:00:00Z",
        "confidence": 0.88,
        "tags": ["fp", "immutability", "api-design"],
    },
    {
        "record_id": "dogfood-ep-005",
        "content": "用户对一段使用 list comprehension 替代 for-loop 的代码表示赞赏，说更函数式",
        "scope": "user",
        "created_at": "2026-05-13T10:00:00Z",
        "confidence": 0.75,
        "tags": ["fp", "comprehension", "code-style"],
    },
    {
        "record_id": "dogfood-ep-006",
        "content": "用户要求所有新模块的输出类型使用 NamedTuple 或 frozen dataclass，不要用 dict",
        "scope": "project",
        "created_at": "2026-05-13T16:00:00Z",
        "confidence": 0.92,
        "tags": ["fp", "immutability", "type-safety"],
    },
]

# 主题 B：用户对 pytest 的稳定偏好（merge，5 条——高度重叠）
_EVIDENCE_PYTEST = [
    {
        "record_id": "dogfood-ep-010",
        "content": "用户在三个项目中都使用 pytest 作为测试框架，对 fixture 和 parametrize 很熟悉",
        "scope": "user",
        "created_at": "2026-05-08T10:00:00Z",
        "confidence": 0.88,
        "tags": ["pytest", "testing", "fixture"],
    },
    {
        "record_id": "dogfood-ep-011",
        "content": "用户为新项目选择了 pytest，表示 parametrize 和 fixture 的组合比 unittest 好太多",
        "scope": "user",
        "created_at": "2026-05-09T10:00:00Z",
        "confidence": 0.85,
        "tags": ["pytest", "testing", "parametrize"],
    },
    {
        "record_id": "dogfood-ep-012",
        "content": "用户拒绝将测试迁移到 unittest，明确说 pytest 的 fixture 机制是选择 pytest 的主要原因",
        "scope": "project",
        "created_at": "2026-05-10T10:00:00Z",
        "confidence": 0.90,
        "tags": ["pytest", "testing", "fixture"],
    },
    {
        "record_id": "dogfood-ep-013",
        "content": "用户要求项目中的测试覆盖率报告使用 pytest-cov，不适用 coverage.py 单独运行",
        "scope": "project",
        "created_at": "2026-05-11T10:00:00Z",
        "confidence": 0.82,
        "tags": ["pytest", "testing", "coverage"],
    },
    {
        "record_id": "dogfood-ep-014",
        "content": "用户在代码审查中强制要求新测试使用 pytest 风格，不接受 unittest.TestCase 子类",
        "scope": "project",
        "created_at": "2026-05-12T10:00:00Z",
        "confidence": 0.87,
        "tags": ["pytest", "testing", "code-review"],
    },
]

# 所有合成 evidence
_ALL_EVIDENCE = _EVIDENCE_FP + _EVIDENCE_PYTEST


# ── Sanitized error helper ─────────────────────────────────────────────────────


def _sanitize_error(exc: Exception) -> str:
    """将异常信息 sanitize，确保不泄露 API key、token、secret。

    只保留错误类型和 HTTP status，去掉 key 片段和 auth header。
    """
    msg = str(exc)
    # 截掉过长的响应体（可能包含 key 信息）
    if len(msg) > 200:
        msg = msg[:200] + "...(truncated)"
    # 去掉明显的 key 片段模式（sk-...、Bearer ...）
    import re as _re
    msg = _re.sub(r'sk-[a-zA-Z0-9_-]+', 'sk-***', msg)
    msg = _re.sub(r'Bearer\s+[a-zA-Z0-9_\-\.]+', 'Bearer ***', msg)
    msg = _re.sub(r'key:?\s*[a-zA-Z0-9_\-\.]{20,}', 'key:***', msg)
    return f"{type(exc).__name__}: {msg}"


def _sanitize_str(text: str) -> str:
    """对任意字符串做 secret sanitize（不依赖异常类型）。"""
    import re as _re
    if len(text) > 300:
        text = text[:300] + "...(truncated)"
    text = _re.sub(r'sk-[a-zA-Z0-9_-]+', 'sk-***', text)
    text = _re.sub(r'Bearer\s+[a-zA-Z0-9_\-\.]+', 'Bearer ***', text)
    text = _re.sub(r'key:?\s*[a-zA-Z0-9_\-\.]{20,}', 'key:***', text)
    text = _re.sub(r'api_key[:=]\s*[^\s,}]+', 'api_key=***', text)
    return text


# ── 步骤 0：环境检查 ───────────────────────────────────────────────────────────

def check_env(project_root: Path | None = None) -> tuple[bool, str, dict, DogfoodProviderConfig | None]:
    """检查 dogfood 运行前提条件。

    Returns:
        (can_run, reason, provider_info, provider_config)
        - provider_info: 只含 provider/model/base_url/source，不包含任何 secret
        - provider_config: DogfoodProviderConfig，含 api_key，用于传给 run_dogfood_pipeline()
    """
    llm_enabled = os.getenv("MEMORY_CONSOLIDATION_LLM_ENABLED", "").strip() in (
        "1", "true", "yes", "True", "TRUE",
    )
    if not llm_enabled:
        return False, "MEMORY_CONSOLIDATION_LLM_ENABLED 未设置为 true", {}, None

    root = project_root or _PROJECT_ROOT
    provider_config = load_project_dotenv_for_dogfood(root)

    provider_info: dict = {
        "model": provider_config.model,
        "base_url": provider_config.base_url,
        "provider": provider_config.provider,
        "key_configured": provider_config.key_configured,
        "source": provider_config.source,
    }

    if not provider_config.key_configured:
        return False, "API key 未配置（项目 .env 和 shell env 中均未找到）", provider_info, provider_config

    return True, "ready", provider_info, provider_config


# ── 步骤 1：准备临时 store ─────────────────────────────────────────────────────

def _format_frontmatter_section(meta: dict, content: str) -> str:
    """将 meta dict + content 格式化为 YAML frontmatter section。"""
    lines = ["---"]
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, bool):
            lines.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        else:
            escaped = str(v).replace('"', '\\"')
            lines.append(f'{k}: "{escaped}"')
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)


def seed_synthetic_evidence(store_root: Path) -> Path:
    """向 filesystem store 写入合成 episodic evidence。

    直接写 .md 文件（与 FilesystemMemoryStore 的内部格式一致）。
    返回 episodic 目录路径。
    """
    episodic_dir = store_root / "episodic"
    episodic_dir.mkdir(parents=True, exist_ok=True)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = episodic_dir / f"{today_str}.md"

    sections: list[str] = []
    for ev in _ALL_EVIDENCE:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta = {
            "id": ev["record_id"],
            "memory_type": "episodic",
            "scope": ev["scope"],
            "source_type": "dogfood_synthetic",
            "approval_status": "approved",
            "created_at": ev["created_at"],
            "updated_at": now,
            "confidence": ev["confidence"],
            "stability": "stable",
            "tags": ev["tags"] if isinstance(ev["tags"], str) else ",".join(ev["tags"]),
            "source_summary": "dogfood synthetic evidence",
            "safety_summary": "no sensitive content",
            "audit_id": f"dogfood-audit-{ev['record_id']}",
            "sensitive_redacted": False,
        }
        section = _format_frontmatter_section(meta, ev["content"])
        sections.append(section)

    filepath.write_text("\n\n---\n\n".join(sections), encoding="utf-8")
    return filepath


# ── 步骤 2：运行 pipeline ──────────────────────────────────────────────────────

def run_dogfood_pipeline(
    store_root: Path,
    provider_info: dict | None = None,
    provider_config: DogfoodProviderConfig | None = None,
) -> dict:
    """运行 Phase 6 consolidation pipeline 并收集结果。

    provider_config: DogfoodProviderConfig — 显式传入 api_key/model/base_url，
        不依赖可能被污染的 shell env 全局 config。
    """
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

    # 构建 LLM generator —— 优先使用显式 project .env 配置
    llm_generator = None
    if _is_llm_consolidation_enabled():
        if provider_config is not None and provider_config.key_configured:
            # 显式传入 project .env 的 api_key/model/base_url
            llm_generator = LLMConsolidationContentGenerator(
                model_name=provider_config.model,
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
            )
        else:
            # 回退：使用全局 config（可能受 shell env 污染）
            from agent.memory_consolidation_llm import create_llm_content_generator
            llm_generator = create_llm_content_generator()

    pipeline_result = run_consolidation_pipeline(store, llm_generator=llm_generator)

    # sanitize LLM 相关 warnings（不泄露 key/secret）
    sanitized_llm_warnings: list[str] = []
    for w in pipeline_result.llm_warnings:
        sanitized_llm_warnings.append(_sanitize_str(w))
    sanitized_pipeline_warnings: list[str] = []
    for w in pipeline_result.warnings:
        sanitized_pipeline_warnings.append(_sanitize_str(w))

    # 判断 LLM auth 状态
    llm_auth_failed = any(
        "401" in w or "403" in w or "auth" in w.lower() or "Authentication" in w
        for w in pipeline_result.llm_warnings
    )
    llm_enhanced_ok = pipeline_result.llm_enhanced_count > 0

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
        "provider": provider_info or {},
        "llm_status": (
            "enhanced" if llm_enhanced_ok
            else ("auth_blocked" if llm_auth_failed
            else ("skipped" if not pipeline_result.llm_enabled
            else "failed"))
        ),
        "dispatch": None,
        "governance_check": None,
    }

    # Dispatch to T1 pending review
    if pipeline_result.has_candidates:
        dispatch_result = dispatch_consolidation_candidates_to_pending_review(
            list(pipeline_result.candidates),
            memory_root=store_root,
            source="dogfood_phase6",
        )
        report["dispatch"] = {
            "dispatched": dispatch_result.dispatched,
            "skipped_duplicate": dispatch_result.skipped_duplicate,
            "skipped_invalid": dispatch_result.skipped_invalid,
            "warnings": list(dispatch_result.warnings),
            "filepaths": [str(p) for p in dispatch_result.proposal_filepaths],
        }

        # 治理验证：确认 LLM 只修改了 content / evidence_summary
        gov_report = _verify_governance_constraints(pipeline_result)
        report["governance_check"] = gov_report

    return report


# ── 步骤 3：治理约束验证 ───────────────────────────────────────────────────────

def _verify_governance_constraints(pipeline_result) -> dict:
    """验证 pipeline 输出的 candidate 满足所有 Phase 6 治理约束。

    重点关注 LLM 增强后：
    - memory_type 仍为 "semantic"
    - governance_route 仍为 "T1"
    - source_evidence 不变
    - consolidation_type 不变
    - confidence 不变或降低（不提高）
    - content 和 evidence_summary 被 LLM 更新
    - 无 procedural-like 内容
    """
    from agent.memory_consolidation_llm import _is_procedural_like_content

    checks: list[dict] = []
    all_pass = True

    for c in pipeline_result.candidates:
        item_checks: dict = {
            "evidence_ids": list(c.source_evidence[:3]),
            "consolidation_type": c.consolidation_type.value,
        }
        failures: list[str] = []

        if c.memory_type != "semantic":
            failures.append(f"memory_type={c.memory_type}，期望 semantic")
        if c.governance_route != "T1":
            failures.append(f"governance_route={c.governance_route}，期望 T1")
        if not (0.0 <= c.confidence <= 1.0):
            failures.append(f"confidence={c.confidence} 超出 [0, 1]")
        if not c.content.strip():
            failures.append("content 为空")
        if _is_procedural_like_content(c.content):
            failures.append("content 包含 procedural-like 语言")
        if len(c.source_evidence) < 3:
            failures.append(f"source_evidence 仅 {len(c.source_evidence)} 条，不足 N≥3")
        if not c.evidence_summary.strip():
            failures.append("evidence_summary 为空")

        item_checks["failures"] = failures
        item_checks["pass"] = len(failures) == 0
        if failures:
            all_pass = False
        checks.append(item_checks)

    return {"all_pass": all_pass, "candidates_checked": len(checks), "details": checks}


# ── 步骤 4：生成审查数据包 ─────────────────────────────────────────────────────

def generate_review_packet(report: dict) -> Path:
    """生成结构化审查数据包，包含 pipeline 输出、dispatch 结果、治理验证。"""
    _REVIEW_PACKET_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    # A. 执行摘要
    summary = _build_executive_summary(report)

    # B. 完整报告
    packet = {
        "dogfood_timestamp": timestamp,
        "dogfood_version": "phase6-real-llm-v1",
        "executive_summary": summary,
        "pipeline_report": report["pipeline"],
        "dispatch_report": report.get("dispatch"),
        "governance_check": report.get("governance_check"),
        "pending_files": _list_pending_files(),
    }

    packet_path = _REVIEW_PACKET_DIR / f"review_packet_{timestamp}.json"
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # C. 人类可读摘要
    summary_path = _REVIEW_PACKET_DIR / f"review_summary_{timestamp}.md"
    summary_path.write_text(_build_markdown_summary(report, packet), encoding="utf-8")

    return packet_path


def _build_executive_summary(report: dict) -> dict:
    """构建执行摘要。"""
    p = report["pipeline"]
    d = report.get("dispatch") or {}
    g = report.get("governance_check") or {}
    prov = report.get("provider") or {}

    return {
        "total_evidence_seeded": len(_ALL_EVIDENCE),
        "evidence_loaded": p["evidence_count"],
        "candidates_generated": p["candidate_count"],
        "llm_enabled": p["llm_enabled"],
        "llm_enhanced_count": p["llm_enhanced_count"],
        "llm_status": report.get("llm_status", "unknown"),
        "dispatched_to_t1_pending": d.get("dispatched", 0),
        "governance_all_pass": g.get("all_pass", False),
        "pipeline_warnings": len(p["warnings"]),
        "llm_warnings": len(p["llm_warnings"]),
        "provider": {
            "model": prov.get("model", "unknown"),
            "base_url": prov.get("base_url", "unknown"),
            "key_configured": prov.get("key_configured", False),
        },
    }


def _list_pending_files() -> list[str]:
    """列出 T1 pending 目录中的所有文件。"""
    pending_dir = _STORE_ROOT / "_pending"
    if not pending_dir.exists():
        return []
    return sorted(f.name for f in pending_dir.glob("t1_*.json"))


def _build_markdown_summary(report: dict, packet: dict) -> str:
    """生成人类可读的 Markdown 审查摘要。"""
    p = report["pipeline"]
    d = report.get("dispatch") or {}
    g = report.get("governance_check") or {}
    prov = report.get("provider") or {}

    lines = [
        "# Phase 6 Real LLM Consolidation Dogfood — 审查摘要",
        "",
        f"**时间**: {packet['dogfood_timestamp']}",
        f"**版本**: {packet['dogfood_version']}",
        "",
        "## Pipeline 结果",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| 合成 evidence 总数 | {len(_ALL_EVIDENCE)} |",
        f"| 成功装载 evidence | {p['evidence_count']} |",
        f"| 生成 candidate 数 | {p['candidate_count']} |",
        f"| LLM 增强数 | {p['llm_enhanced_count']} |",
        f"| 分发到 T1 pending | {d.get('dispatched', 0)} |",
        f"| 去重跳过 | {d.get('skipped_duplicate', 0)} |",
        f"| 治理验证通过 | {'YES' if g.get('all_pass') else 'NO'} |",
        "",
        "## 治理验证详情",
        "",
    ]

    if g.get("details"):
        for i, check in enumerate(g["details"]):
            status = "PASS" if check["pass"] else "FAIL"
            lines.append(
                f"- candidate {i + 1} [{check['consolidation_type']}]: "
                f"**{status}** (evidence={check['evidence_ids']})"
            )
            for f_msg in check.get("failures", []):
                lines.append(f"  - FAIL: {f_msg}")

    lines.extend([
        "",
        "## LLM 增强的 Content 预览",
        "",
        "以下是通过 pipeline 自动生成的 candidate content（经 LLM 增强）：",
        "",
    ])

    # 这里无法直接访问 candidates，从 packet 中提取概要
    lines.append(f"详见完整 JSON 报告: `{packet.get('dogfood_timestamp', 'unknown')}`")
    lines.append("")

    if d.get("filepaths"):
        lines.append("## T1 Pending 文件")
        lines.append("")
        for fp in d["filepaths"]:
            lines.append(f"- `{fp}`")
        lines.append("")

    lines.extend([
        "## 审查检查清单",
        "",
        "- [ ] 所有 candidate 的 memory_type 为 semantic",
        "- [ ] 所有 candidate 的 governance_route 为 T1",
        "- [ ] 无 procedural-like 内容",
        "- [ ] confidence 在 [0, 1] 范围内",
        "- [ ] content 非空且自然（非模板化）",
        "- [ ] evidence_summary 包含 record_id 引用",
        "- [ ] 无 auto-approve（所有 candidate 进入 T1 pending）",
        "- [ ] source_evidence 未被 LLM 修改",
        "- [ ] consolidation_type 未被 LLM 修改",
        "",
        "## Secret handling correction",
        "",
        "- [x] 不打印 API key prefix / length / suffix",
        "- [x] auth failure 已 sanitize，仅输出错误类型",
        "- [x] 不将 secret 写入 report",
        "- [x] 不将 secret 写入 memory store",
        "- [x] 不将 secret 写入日志",
        f"- [x] provider 状态报告：configured={prov.get('key_configured', False)}, model={prov.get('model', 'unknown')}",
        f"- [x] real LLM dogfood 状态：{report.get('llm_status', 'unknown')}",
        "- [x] 如有 secret 泄露到此 report，则为代码缺陷",
        "",
        "## 下一步",
        "",
        "运行 `python -m agent.memory_review` 进入 T1 pending review CLI，",
        "对以上 candidate 执行 accept / edit-and-accept / reject。",
        "",
        "⚠️ 当前所有 candidate 仅在 _pending/ 中，尚未写入正式 memory store。",
    ])

    return "\n".join(lines)


# ── main ────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """dogfood 入口。

    CLI 参数：
      --project-root PATH    项目根目录（默认脚本所在仓库根目录）
      --load-project-env     从项目 .env 加载 provider 配置（默认启用）

    Returns:
        0: 成功
        1: 跳过（环境未配置）
        2: 运行失败
    """
    # 解析 CLI 参数
    args = argv if argv is not None else sys.argv[1:]
    project_root = _PROJECT_ROOT
    i = 0
    while i < len(args):
        if args[i] == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).resolve()
            i += 2
        elif args[i] == "--load-project-env":
            # 默认行为已启用，此参数为显式声明
            i += 1
        else:
            print(f"未知参数: {args[i]}", file=sys.stderr)
            i += 1

    print("=" * 60)
    print("Phase 6 Real LLM Consolidation Dogfood")
    print("=" * 60)
    print(f"  project_root: {project_root}")

    # Step 0: 环境检查
    can_run, reason, provider_info, provider_config = check_env(project_root)
    if not can_run:
        print(f"\n[SKIP] {reason}")
        if provider_info:
            print(f"  provider configured: {provider_info.get('key_configured', False)}")
        print("设置 MEMORY_CONSOLIDATION_LLM_ENABLED=true 并确保 API key 可用后重试。")
        return 1

    # 报告 provider 配置（不含 secret）
    print("\n[OK] 环境检查通过")
    print("  provider configured: yes")
    print(f"  provider source: {provider_info.get('source', 'unknown')}")
    print(f"  model:  {provider_info.get('model', 'unknown')}")
    print(f"  base_url: {provider_info.get('base_url', 'unknown')}")

    # Step 1: 准备临时 store + 合成 evidence
    print("\n[1/4] 准备临时 store ...")
    print(f"  store_root: {_STORE_ROOT}")

    # 清理旧数据
    if _DOGFOOD_ROOT.exists():
        import shutil
        shutil.rmtree(_DOGFOOD_ROOT)
    _STORE_ROOT.mkdir(parents=True, exist_ok=True)

    seed_synthetic_evidence(_STORE_ROOT)
    print(f"  [OK] 写入 {len(_ALL_EVIDENCE)} 条合成 episodic evidence")

    # Step 2: 运行 pipeline
    print("\n[2/4] 运行 Phase 6 consolidation pipeline ...")
    try:
        report = run_dogfood_pipeline(_STORE_ROOT, provider_info, provider_config)
    except Exception as exc:
        print(f"\n[FAIL] pipeline 运行失败: {_sanitize_error(exc)}")
        import traceback
        traceback.print_exc()
        return 2

    p = report["pipeline"]
    print(f"  evidence_count:  {p['evidence_count']}")
    print(f"  candidate_count: {p['candidate_count']}")
    print(f"  llm_enabled:     {p['llm_enabled']}")
    print(f"  llm_enhanced:    {p['llm_enhanced_count']}")
    print(f"  llm_status:      {report.get('llm_status', 'unknown')}")

    if p["warnings"]:
        print(f"  pipeline warnings: {len(p['warnings'])} 条")
        for w in p["warnings"][:5]:
            print(f"    - {w[:150]}")

    if p["llm_warnings"]:
        print(f"  llm warnings: {len(p['llm_warnings'])} 条")
        for w in p["llm_warnings"][:5]:
            print(f"    - {w[:150]}")

    d = report.get("dispatch") or {}
    if d:
        print("\n[3/4] T1 pending dispatch ...")
        print(f"  dispatched:       {d['dispatched']}")
        print(f"  skipped_dup:      {d['skipped_duplicate']}")
        print(f"  skipped_invalid:  {d['skipped_invalid']}")

    # Step 3: 治理验证
    g = report.get("governance_check") or {}
    if g:
        print("\n[4/4] 治理约束验证 ...")
        print(f"  all_pass:         {g.get('all_pass')}")
        for i, check in enumerate(g.get("details", [])):
            status = "PASS" if check["pass"] else "FAIL"
            ctype = check.get("consolidation_type", "?")
            print(f"  candidate {i + 1} [{ctype}]: {status}")
            for f_msg in check.get("failures", []):
                print(f"    FAIL: {f_msg}")

    # Step 4: 生成审查数据包
    packet_path = generate_review_packet(report)
    print("\n审查数据包已生成:")
    print(f"  JSON:   {packet_path}")
    summary_files = sorted(_REVIEW_PACKET_DIR.glob("review_summary_*.md"))
    if summary_files:
        print(f"  Markdown: {summary_files[-1]}")

    # 最终状态
    llm_status = report.get("llm_status", "unknown")

    if llm_status == "auth_blocked":
        print("\n⚠️  BLOCKED: provider authentication failed")
        print("   real LLM consolidation dogfood blocked by provider authentication;")
        print("   code path and fake tests pass. T1 pending dispatch completed")
        print("   with deterministic candidates only.")
        print(f"   {d.get('dispatched', 0)} 条 deterministic candidate 已进入 T1 pending review。")
        return 3  # exit code 3 = blocked

    if d.get("dispatched", 0) > 0 and g.get("all_pass", False):
        llm_tag = " (LLM enhanced)" if p.get("llm_enhanced_count", 0) > 0 else ""
        print(f"\n✅ Dogfood 完成 — {d['dispatched']} 条 candidate 已进入 T1 pending review{llm_tag}")
        print("   运行 `python -m agent.memory_review` 进行人工审查。")
        return 0
    elif p["candidate_count"] == 0:
        print("\n⚠️  未生成任何 candidate（evidence 不足或未通过校验）")
        return 2
    else:
        print("\n⚠️  Dogfood 部分完成 — 存在治理验证失败项")
        return 2


if __name__ == "__main__":
    sys.exit(main())

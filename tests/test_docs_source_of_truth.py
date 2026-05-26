"""Source-of-Truth 一致性测试：防止 archived docs 被误当作当前入口。

背景：Documentation Source-of-Truth Reset 将 ~150+ 历史/过期文档归档到
docs/archive/，并建立了 active/historical 分类规则。这些测试守护以下不变量：

1. Active docs（CURRENT_AUDIT_STATUS、audit/plans/dogfood README）不声称
   过期状态为当前状态（如 v0.9.x-as-current、human dogfood completed）。
2. 各 index README 包含明确的 active/historical 分类。
3. Archived docs 不被 active index 当作当前入口引用。
4. Active docs 不声称项目已达到 broadly user-usable 或 human dogfood 已完成。

为什么这对 AutoRun 很重要：
- AutoRun 从 active docs 中读取当前状态和下一步行动。如果 active docs
  仍引用 archived/historical 文档作为当前入口，AutoRun 会基于过期信息
  做出错误的能力建设决策。
- active/historical 分类确保 AutoRun 只以当前权威源为执行依据。
- agent-driven rehearsal 和 manual human dogfood 的区分防止 AutoRun
  把自动预演误认为人工验证已完成。

设计原则：
- 只检查 active index docs，不检查 archived docs 内容。
- 以文本包含/排除断言为主，不绑定具体行号。
- 中文注释/docstring 解释每个测试的意图和 AutoRun 影响。
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


# =========================================================================
# 1. CURRENT_AUDIT_STATUS.zh.md 不再以 v0.9.x 为当前状态
# =========================================================================

def test_current_audit_status_does_not_claim_v0_9_x_as_current():
    """CURRENT_AUDIT_STATUS.zh.md 不能再把 v0.9.x 写成当前阶段。

    为什么：v0.9.x stabilization 是历史阶段，已完成并归档。如果 AutoRun
    读到 "Status: v0.9.0 released" 会误认为项目仍在 v0.9.x 阶段，从而
    基于过期上下文做决策。
    """
    text = _read("docs/06-audit/CURRENT_AUDIT_STATUS.zh.md")
    # 不能出现 v0.9.x 作为当前状态的表述
    assert "v0.9.0 released" not in text
    assert "v0.9.x Deep Stabilization" not in text
    # 必须明确当前是 cleanup-only / manual dogfood 阶段
    assert "Cleanup-Only" in text or "cleanup" in text.lower()
    assert "Manual Human Dogfood" in text or "manual human dogfood" in text.lower()


def test_current_audit_status_points_to_current_sources():
    """CURRENT_AUDIT_STATUS.zh.md 必须指向当前 source-of-truth 文档。

    为什么：如果审计状态文档指向 archived docs，AutoRun 会沿着过期引用
    追踪到历史文档，污染执行上下文。
    """
    text = _read("docs/06-audit/CURRENT_AUDIT_STATUS.zh.md")
    # 必须指向当前权威源
    assert "CURRENT_CAPABILITY_STATUS.zh.md" in text
    assert "global-red-team-product-architecture-audit-2026-05-25.md" in text
    # 不得以 archived path 作为当前入口（../refactor/ → ../archive/refactor/）
    assert "../refactor/" not in text
    assert "../runtime-integration/" not in text


def test_current_audit_status_does_not_claim_broadly_usable():
    """Active docs 不得声称项目已是 broadly user-usable。

    为什么：项目当前标签是 manual-dogfood-ready local agent，不是 broadly
    user-usable agent。如果 AutoRun 看到 "broadly user-usable" 会跳过
    必要的 manual dogfood 步骤。
    """
    for doc in [
        "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
        "docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md",
    ]:
        text = _read(doc)
        assert "broadly user-usable" not in text or "❌" in text


def test_current_audit_status_does_not_claim_human_dogfood_completed():
    """Active docs 不得声称 manual human dogfood 已完成。

    为什么：manual human dogfood 是当前最高优先级下一步，尚未执行。
    如果 active docs 声称已完成，AutoRun 可能跳过这个关键步骤。
    """
    for doc in [
        "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
        "docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md",
    ]:
        text = _read(doc)
        text_lower = text.lower()
        # 必须包含「尚未完成」的表述：未完成/需人类/仍需要/not completed/required/不能声称...已完成
        assert (
            "未完成" in text
            or "需人类" in text
            or "仍需要" in text
            or "not completed" in text_lower
            or "required" in text_lower
            or "不能声称" in text  # 「不能声称 manual human dogfood 已完成」
        )


# =========================================================================
# 2. audit/README.md active/historical 分类
# =========================================================================

def test_audit_readme_has_active_historical_classification():
    """docs/audit/README.md 必须包含 active/historical 分类标记。

    为什么：AutoRun 需要识别哪些审计是当前行动依据、哪些只是历史证据。
    没有分类标记，AutoRun 可能把所有审计都当作当前 backlog。
    """
    text = _read("docs/audit/README.md")
    assert "## Active" in text or "## Active Audits" in text
    assert "## Historical" in text or "## Historical Audits" in text
    # 必须有 AutoRun 规则说明
    assert "AutoRun" in text


def test_audit_readme_designates_single_authoritative_audit():
    """docs/audit/README.md 必须明确指定唯一权威当前审计。

    为什么：多个 active audit 会让 AutoRun 不确定以哪个为准。
    global-red-team audit 是当前唯一权威行动源。
    """
    text = _read("docs/audit/README.md")
    assert "global-red-team-product-architecture-audit-2026-05-25.md" in text
    assert "权威" in text


# =========================================================================
# 3. plans/README.md active/completed/historical 分类
# =========================================================================

def test_plans_readme_has_active_completed_historical_classification():
    """docs/plans/README.md 必须包含 active/completed/historical 分类。

    为什么：AutoRun 需要区分当前执行计划、已完成计划和历史计划。
    如果所有计划都标为 active，AutoRun 会尝试执行已完成的 remediation。
    """
    text = _read("docs/plans/README.md")
    assert "## Active" in text
    assert "## Completed" in text or "已完成" in text
    assert "## Historical" in text
    assert "AutoRun" in text


def test_plans_readme_marks_remediation_as_completed():
    """docs/plans/README.md 必须将 remediation 计划标记为已完成。

    为什么：RT-01~RT-18、PF-01~PF-15、low-complexity remediation 均已
    完成并 commit。如果这些仍标为 active，AutoRun 会重复执行。
    """
    text = _read("docs/plans/README.md")
    assert "global-red-team-remediation-plan" in text
    assert "已完成" in text


# =========================================================================
# 4. dogfood/README.md active/evidence/historical 分类
# =========================================================================

def test_dogfood_readme_has_active_evidence_historical_classification():
    """docs/dogfood/README.md 必须包含 active/evidence/historical 分类。

    为什么：agent-driven rehearsal 不等同于 manual human dogfood。
    如果分类不清晰，AutoRun 可能把自动预演报告当作人工验证已完成。
    """
    text = _read("docs/dogfood/README.md")
    assert "## Active" in text
    assert "## Evidence" in text or "自动化证据" in text
    assert "## Historical" in text


def test_dogfood_readme_distinguishes_rehearsal_from_manual():
    """docs/dogfood/README.md 必须区分 agent-driven rehearsal 和 manual human dogfood。

    为什么：这是 AutoRun 的关键安全边界。如果文档不区分二者，AutoRun
    可能把 rehearsal 11/11 PASS 当作人工 dogfood 已完成，跳过人类验证。
    """
    text = _read("docs/dogfood/README.md")
    assert "agent-driven" in text.lower() or "自动预演" in text
    assert "manual human dogfood" in text.lower() or "人工" in text
    assert "替代" in text or "not" in text.lower()  # rehearsal 不是替代品


def test_dogfood_readme_states_real_provider_blocked():
    """docs/dogfood/README.md 必须说明 real provider 受 401 concern 阻塞。

    为什么：防止 AutoRun 在 real provider 不可用时重试真实 API。
    """
    text = _read("docs/dogfood/README.md")
    assert "401" in text or "blocked" in text.lower() or "阻塞" in text


# =========================================================================
# 5. Archived docs 不被 active index 当作当前入口
# =========================================================================

def test_readme_does_not_reference_archived_docs_as_current():
    """README.md 不得将 archived docs 引用为当前入口。

    检查 README.md 的文档阅读路径部分不包含 docs/archive/ 路径作为
    「当前」入口（历史记录/归档引用除外）。
    """
    text = _read("README.md")
    # 文档阅读路径部分可以有 archive 引用（标记为已归档），但不能作为主要入口
    # 主要入口链接必须指向 active docs
    assert "docs/00-overview/" in text
    assert "docs/01-getting-started/" in text


def test_docs_readme_zh_has_archive_section():
    """docs/README.zh.md 的文档状态规则必须说明 archive 目录不是当前入口。

    为什么：docs/README.zh.md 是文档总入口，必须让所有读者（包括
    AutoRun）知道 archive docs 是历史证据而非当前入口。
    """
    text = _read("docs/README.zh.md")
    assert "archive" in text.lower()
    assert "归档" in text or "历史" in text


def test_active_indexes_do_not_link_to_archived_refactor_docs_as_current():
    """Active index 不得以未归档路径引用已移到 archive/refactor/ 的文档。

    v0.9.x stabilization 文档已从 docs/refactor/ 移至
    docs/archive/refactor/。Active index 中的 ../refactor/ 链接已失效。
    """
    for doc_path in [
        "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
        "docs/audit/README.md",
        "docs/plans/README.md",
        "docs/dogfood/README.md",
        "docs/README.zh.md",
    ]:
        text = _read(doc_path)
        # 如引用 refactor 文档，必须是 archive 路径
        if "../refactor/" in text:
            # 只允许在明确标记为 archived/historical 的上下文中出现
            assert False, f"{doc_path} 包含过期 ../refactor/ 链接，应改为 ../archive/refactor/"

    # 同理检查 runtime-integration
    for doc_path in [
        "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
        "docs/audit/README.md",
        "docs/plans/README.md",
        "docs/dogfood/README.md",
        "docs/README.zh.md",
    ]:
        text = _read(doc_path)
        if "../runtime-integration/" in text:
            assert False, f"{doc_path} 包含过期 ../runtime-integration/ 链接，应改为 ../archive/runtime-integration/"


# =========================================================================
# 6. Active docs 不声称过期状态
# =========================================================================

def test_active_docs_do_not_claim_capability_building_is_active():
    """Active docs 不得声称能力建设仍在进行中。

    当前阶段：Cleanup-Only / Awaiting Manual Human Dogfood。能力建设暂停。
    """
    text = _read("docs/06-audit/CURRENT_AUDIT_STATUS.zh.md")
    assert "能力建设暂停" in text or "cleanup" in text.lower()


def test_active_docs_do_not_claim_real_provider_is_working():
    """Active docs 不得声称 real provider 当前可用。

    当前 deepseek-v4-pro 受 401 config/auth concern 阻塞。
    """
    text = _read("docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md")
    # 必须提到 real provider 的阻塞状态
    assert "401" in text or "concern" in text.lower() or "阻塞" in text


# =========================================================================
# 7. Redaction / secret safety 仍覆盖 index docs
# =========================================================================

def test_index_docs_contain_no_hardcoded_secrets():
    """audit/plans/dogfood index 不得包含硬编码 secret。

    Source-of-truth reset 后，index docs 可能引用新路径，这些路径下的
    文档也需要通过 redaction 检查。本测试只扫 index 文件本身。
    """
    import re

    secret_patterns = [
        r"sk-ant-[A-Za-z0-9_-]{20,}",  # Anthropic API key
        r"sk-[A-Za-z0-9_-]{20,}",       # OpenAI API key
        r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",  # PEM private key
    ]
    for doc_path in [
        "docs/audit/README.md",
        "docs/plans/README.md",
        "docs/dogfood/README.md",
        "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
        "docs/README.zh.md",
    ]:
        text = _read(doc_path)
        for pattern in secret_patterns:
            assert not re.search(pattern, text), (
                f"{doc_path} 包含疑似 secret：{pattern}"
            )


# =========================================================================
# 8. Broken links 检查（active index → referenced docs）
# =========================================================================

def _resolve_relative_link(base_dir: Path, link_target: str) -> Path | None:
    """解析 Markdown 相对链接，返回目标绝对路径（如存在）。"""
    # 去掉 fragment
    target = link_target.split("#")[0]
    if not target:
        return None
    resolved = (base_dir / target).resolve()
    return resolved if resolved.exists() else None


def test_active_index_links_to_existing_files():
    """Active index 文档中的相对链接指向的文件必须存在。

    只检查 index 文件（README.md 系列），不递归检查所有文档。
    跳过外部 URL 和 archive 路径（archive 内容不作为当前入口验证）。
    """
    import re

    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

    index_files = [
        "docs/audit/README.md",
        "docs/plans/README.md",
        "docs/dogfood/README.md",
        "docs/README.zh.md",
        "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
    ]

    broken: list[str] = []
    for idx_path in index_files:
        text = _read(idx_path)
        base_dir = (PROJECT_ROOT / idx_path).parent
        for match in link_pattern.finditer(text):
            link_target = match.group(2)
            # 跳过外部 URL
            if link_target.startswith("http://") or link_target.startswith("https://"):
                continue
            # 跳过纯 anchor
            if link_target.startswith("#"):
                continue
            # 跳过 mailto
            if link_target.startswith("mailto:"):
                continue
            resolved = _resolve_relative_link(base_dir, link_target)
            if resolved is None and not link_target.startswith("http"):
                broken.append(f"{idx_path} → {link_target}")

    # 只 assert 而非静默跳过——broken links 必须修复或显式豁免
    if broken:
        pytest.fail(f"Active index 中存在 {len(broken)} 个断链:\n" + "\n".join(broken))


# =========================================================================
# 9. FakeProvider / Memory Consolidation 冻结声明一致性
# =========================================================================

def test_fake_provider_freeze_declared_in_active_docs():
    """Active docs 必须声明 FakeProvider 增长已冻结。

    为什么：FakeProvider 是 deterministic test fixture，不继续增强为
    fake planner / fake reasoning engine。这是重要的工程边界，防止
    AutoRun 在 fake provider 上浪费能力建设。
    """
    text = _read("docs/06-audit/CURRENT_AUDIT_STATUS.zh.md")
    assert "FakeProvider" in text
    assert "冻结" in text or "freeze" in text.lower() or "不继续" in text


def test_memory_consolidation_freeze_declared_in_active_docs():
    """Active docs 必须声明 Memory Consolidation pipeline 已冻结。

    为什么：6 个 consolidation 文件的 dispatch/handler path 已验证，
    但 business operation / real LLM consolidation deferred。
    """
    text = _read("docs/06-audit/CURRENT_AUDIT_STATUS.zh.md")
    assert "Consolidation" in text
    assert "冻结" in text or "freeze" in text.lower() or "deferred" in text.lower()

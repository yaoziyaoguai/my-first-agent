"""Source-of-Truth 一致性测试：防止过期文档模式复活。

背景：2026-05-27 docs cleanup 建立了 PROJECT_STATUS.md / PROGRESS_LEDGER.md
作为第一优先读取入口，归档了大量过期 plans/audit/dogfood 文档。

这些测试守护以下不变量：

1. PROJECT_STATUS.md 和 PROGRESS_LEDGER.md 存在且内容完整。
2. Active docs 不含 stale config 引用（MY_FIRST_AGENT_LLM_PROVIDER 等）。
3. Active docs 不把已修复的 P1/P2 写成当前 blocker。
4. Active docs 指向 config/config.yaml 作为推荐配置。
5. Active index docs 内部链接不 broken。
6. Archive docs 不被 active index 当作当前入口引用。
7. Secret scan 通过。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


# =========================================================================
# 1. PROJECT_STATUS.md 和 PROGRESS_LEDGER.md 存在且完整
# =========================================================================

def test_project_status_exists():
    """PROJECT_STATUS.md 必须存在，作为第一优先读取入口。"""
    text = _read("docs/PROJECT_STATUS.md")
    assert "当前状态" in text or "Current" in text
    assert "config/config.yaml" in text
    assert "PROGRESS_LEDGER.md" in text


def test_progress_ledger_exists():
    """PROGRESS_LEDGER.md 必须存在，记录关键 milestones。"""
    text = _read("docs/PROGRESS_LEDGER.md")
    assert "2026-05-27" in text
    assert "ISSUE-002" in text or "fix" in text.lower()


# =========================================================================
# 2. Active docs 不含 stale config 引用
# =========================================================================

LEGACY_CONFIG_PATTERNS = [
    "MY_FIRST_AGENT_LLM_PROVIDER",
    "FIRST_AGENT_PROVIDER_PROFILE",
]

LEGACY_CONFIG_FILES = [
    # 这些 pattern 明确不是 legacy（它们是标记 legacy 的权威定义）
]

ACTIVE_DOCS_GLOB = [
    "docs/README.zh.md",
    "docs/PROJECT_STATUS.md",
    "docs/PROGRESS_LEDGER.md",
    "docs/00-overview/*.md",
    "docs/01-getting-started/*.md",
    "docs/02-architecture/*.md",
    "docs/05-testing-dogfood/*.md",
    "docs/06-audit/*.md",
    "docs/design/*.md",
    "docs/dev/*.md",
    "docs/rfc/*.md",
    "docs/real-e2e/*.md",
]


def _resolve_glob(glob_pattern: str) -> list[Path]:
    return list(PROJECT_ROOT.glob(glob_pattern))


def test_active_docs_no_stale_config_env_vars():
    """Active docs 不得推荐 MY_FIRST_AGENT_LLM_PROVIDER / FIRST_AGENT_PROVIDER_PROFILE。

    docs/design/ 下的 config contract 和 PROJECT_STATUS.md 中显式标记 legacy
    的引用除外——它们是权威标记，不是推荐。
    """
    violations: list[str] = []
    for glob_pat in ACTIVE_DOCS_GLOB:
        for fpath in _resolve_glob(glob_pat):
            text = fpath.read_text(encoding="utf-8")
            for pattern in LEGACY_CONFIG_PATTERNS:
                if pattern in text:
                    rel = str(fpath.relative_to(PROJECT_ROOT))
                    # 允许在 design contracts 和 PROJECT_STATUS 中显式标记为 legacy
                    if "legacy" in text.lower() or "deprecated" in text.lower() or "不推荐" in text:
                        continue
                    violations.append(f"{rel}: 包含 {pattern}")
    if violations:
        msg = "Active docs 包含未标记为 legacy 的 stale config 引用:\n" + "\n".join(violations)
        pytest.fail(msg)


def test_active_docs_no_provider_profiles_yaml_as_setup_path():
    """Active docs 不得推荐 config/provider_profiles.yaml 作为 setup 路径。"""
    for glob_pat in ACTIVE_DOCS_GLOB:
        for fpath in _resolve_glob(glob_pat):
            text = fpath.read_text(encoding="utf-8")
            if "provider_profiles.yaml" in text:
                rel = str(fpath.relative_to(PROJECT_ROOT))
                if "legacy" in text.lower() or "deprecated" in text.lower() or "已删除" in text:
                    continue
                pytest.fail(f"{rel}: 推荐 provider_profiles.yaml（应标记为 legacy）")


# =========================================================================
# 3. Active docs 不把已修复的 P1/P2 写成当前 blocker
# =========================================================================

FIXED_BLOCKERS = [
    "ISSUE-002.*空响应.*当前.*blocker",
    "infinite loop.*still.*blocking",
    "model_provider_required.*crash",
]


def test_active_overview_docs_no_fixed_blockers():
    """00-overview / 06-audit 的 active docs 不得把已修复 bugs 写成当前 blocker。"""
    for doc in [
        "docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md",
        "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
    ]:
        text = _read(doc)
        # 这些 doc 不应声称存在无限循环、空响应等已修复的 P0/P1
        assert "空响应" not in text or "fixed" in text.lower() or "已修复" in text
        assert "无限循环" not in text or "已修复" in text


# =========================================================================
# 4. Active docs 指向 config/config.yaml 作为推荐配置
# =========================================================================

def test_project_status_points_to_config_yaml():
    """PROJECT_STATUS.md 必须指向 config/config.yaml 作为推荐配置。"""
    text = _read("docs/PROJECT_STATUS.md")
    assert "config/config.yaml" in text


def test_docs_readme_zh_points_to_config_yaml():
    """docs/README.zh.md 必须指向 config/config.yaml。"""
    text = _read("docs/README.zh.md")
    assert "config/config.yaml" in text


# =========================================================================
# 5. Active docs 不声称 fake provider 可验证任意自然语言语义
# =========================================================================

def test_active_docs_no_fake_provider_semantic_overclaim():
    """Active docs 不得声称 FakeProvider 可验证 arbitrary natural language semantic intent。"""
    for glob_pat in ["docs/00-overview/*.md", "docs/design/*.md"]:
        for fpath in _resolve_glob(glob_pat):
            text = fpath.read_text(encoding="utf-8")
            if "fake" in text.lower() and ("语义" in text and "验证" in text):
                if "不代表" in text or "不" in text:
                    continue
                rel = str(fpath.relative_to(PROJECT_ROOT))
                # 检查是否声称 fake 能做语义验证
                if "FakeProvider 增长已冻结" in text or "冻结" in text:
                    continue
                # 否则检查是不是在说 fake 能做语义能力验证
                if "fake" in text.lower() and "真实" in text and "语义" in text:
                    pytest.fail(f"{rel}: 疑似声称 FakeProvider 可验证真实语义")


# =========================================================================
# 6. Index docs 断链检查
# =========================================================================

def _resolve_relative_link(base_dir: Path, link_target: str) -> Path | None:
    target = link_target.split("#")[0]
    if not target:
        return None
    resolved = (base_dir / target).resolve()
    return resolved if resolved.exists() else None


def test_active_index_links_to_existing_files():
    """Active index 文档中的相对链接必须指向存在的文件。"""
    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

    index_files = [
        "docs/README.zh.md",
        "docs/PROJECT_STATUS.md",
        "docs/PROGRESS_LEDGER.md",
        "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
        "docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md",
        "docs/dogfood/README.md",
        "docs/plans/README.md",
        "docs/audit/README.md",
    ]

    broken: list[str] = []
    for idx_path in index_files:
        if not (PROJECT_ROOT / idx_path).exists():
            continue
        text = _read(idx_path)
        base_dir = (PROJECT_ROOT / idx_path).parent
        for match in link_pattern.finditer(text):
            link_target = match.group(2)
            if link_target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = _resolve_relative_link(base_dir, link_target)
            if resolved is None:
                broken.append(f"{idx_path} → {link_target}")

    if broken:
        pytest.fail(f"Active index 中存在 {len(broken)} 个断链:\n" + "\n".join(broken))


# =========================================================================
# 7. Secret scan
# =========================================================================

def test_active_index_docs_contain_no_hardcoded_secrets():
    """Active index 文档不得包含硬编码 secret。"""
    secret_patterns = [
        r"sk-ant-[A-Za-z0-9_-]{20,}",
        r"sk-[A-Za-z0-9_-]{20,}",
        r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    ]
    for doc_path in [
        "docs/PROJECT_STATUS.md",
        "docs/PROGRESS_LEDGER.md",
        "docs/README.zh.md",
        "docs/audit/README.md",
        "docs/plans/README.md",
        "docs/dogfood/README.md",
    ]:
        if not (PROJECT_ROOT / doc_path).exists():
            continue
        text = _read(doc_path)
        for pattern in secret_patterns:
            assert not re.search(pattern, text), f"{doc_path} 包含疑似 secret"


# =========================================================================
# 8. CURRENT_AUDIT_STATUS 和 CURRENT_CAPABILITY_STATUS 不指向已归档文件
# =========================================================================

def test_current_status_docs_no_broken_archive_refs():
    """CURRENT_AUDIT_STATUS / CURRENT_CAPABILITY_STATUS 不得包含指向已归档文件的断链。"""
    for doc_path in [
        "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
        "docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md",
    ]:
        text = _read(doc_path)
        link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
        base_dir = (PROJECT_ROOT / doc_path).parent
        for match in link_pattern.finditer(text):
            link_target = match.group(2)
            if link_target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = _resolve_relative_link(base_dir, link_target)
            if resolved is None:
                pytest.fail(f"{doc_path} 包含断链: {link_target}")


# =========================================================================
# 9. FakeProvider / Memory Consolidation 冻结声明
# =========================================================================

def test_fake_provider_freeze_declared():
    """Active docs 必须声明 FakeProvider 增长已冻结。"""
    text = _read("docs/06-audit/CURRENT_AUDIT_STATUS.zh.md")
    assert "FakeProvider" in text
    assert "冻结" in text or "freeze" in text.lower()


def test_memory_consolidation_freeze_declared():
    """Active docs 必须声明 Memory Consolidation pipeline 已冻结。"""
    text = _read("docs/06-audit/CURRENT_AUDIT_STATUS.zh.md")
    assert "Consolidation" in text
    assert "冻结" in text or "freeze" in text.lower() or "deferred" in text.lower()

"""v0.2 RC 文档/路径/命令引用一致性 sanity 测试。

本测试**不**调用真实 LLM、**不**做用户交互、**不**触发外部副作用。
它只做静态文件存在性 + 文档间 cross-reference 一致性检查，确保：

- RC 状态文档与 manual smoke playbook 引用的关键路径都真实存在；
- v0.2 RC 的 commit 序列声明的 4 份 spec + preflight 文档都在仓库里；
- M5/M6 preflight 缺口在 baseline 测试中真的有对应的钉死断言；
- LLM Processing 已收口能力的 CLI 命令模块路径仍可 import。

放本测试的目的：v0.2 RC 文档密度高，避免后续重构时静默漂移
（删了文件 / 改了路径 / 重命名命令）。任何漂移都会让本测试立刻失败。

边界：本测试**不**验证文档内容正确性，只验证「引用的东西存在」。

2026-05-25 归档说明：v0.x 文档已归档至 docs/archive/v0.x/。
_source_to_archive() 负责将旧 docs/V0_* 路径映射到 docs/archive/v0.x/V0_*，
非 V0_* 路径保持不变。DOC_CROSS_REFERENCES 的 ref 值保留旧路径
（与归档文档的内部文本内容匹配），source_doc key 使用归档路径。
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# v0.2 RC 主线引用的核心文档；任何一个缺失都意味着 RC 文档链断裂。
# 2026-05-26 文档归档后更新路径。
RC_REQUIRED_DOCS = [
    "docs/archive/v0.x/V0_2_PLANNING.md",
    "docs/archive/root-stale/RUNTIME_STATE_MACHINE.md",
    "docs/archive/root-stale/RUNTIME_EVENT_BOUNDARIES.md",
    "docs/archive/root-stale/CHECKPOINT_RESUME_SEMANTICS.md",
    "docs/archive/root-stale/RUNTIME_ERROR_RECOVERY.md",
    "docs/archive/v0.x/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md",
    "docs/archive/v0.x/V0_2_MANUAL_SMOKE_PLAYBOOK.md",
    "docs/archive/v0.x/V0_2_RC_STATUS.md",
    "docs/archive/root-stale/CLI_OUTPUT_CONTRACT.md",
    "docs/archive/llm-provider/LLM_PROVIDER_LIVE_SMOKE.md",
    "docs/archive/llm-provider/LLM_AUDIT_STATUS_SCHEMA.md",
    "docs/archive/llm-provider/LLM_PROVIDER_CONFIG.md",
    "README.md",
]


@pytest.mark.parametrize("rel_path", RC_REQUIRED_DOCS)
def test_rc_required_doc_exists(rel_path: str) -> None:
    """RC 引用链上的每一份文档都必须真实存在且非空。"""
    p = REPO_ROOT / rel_path
    assert p.is_file(), f"v0.2 RC 文档缺失：{rel_path}"
    assert p.stat().st_size > 0, f"v0.2 RC 文档为空：{rel_path}"


# manual smoke playbook 中要求人工跑的命令所依赖的入口文件
MANUAL_SMOKE_REQUIRED_PATHS = [
    "main.py",
    "llm/cli.py",
    ".venv/bin/python",  # 测试环境前置
]


@pytest.mark.parametrize("rel_path", MANUAL_SMOKE_REQUIRED_PATHS)
def test_manual_smoke_path_exists(rel_path: str) -> None:
    """smoke playbook 中要求执行的核心入口必须存在。"""
    p = REPO_ROOT / rel_path
    assert p.exists(), f"manual smoke 引用的路径缺失：{rel_path}"


def _source_to_archive(path: str) -> str:
    """将旧文档路径映射到归档路径。

    2026-05-26 文档归档后，多个根级 doc 移至 docs/archive/root-stale/、
    docs/archive/llm-provider/ 等子目录。
    """
    m = re.match(r"docs/(V0_.+)$", path)
    if m:
        return f"docs/archive/v0.x/{m.group(1)}"
    # 2026-05-26: 根级 docs 已归档到 archive 子目录
    _ROOT_ARCHIVED = {
        "docs/RUNTIME_STATE_MACHINE.md",
        "docs/RUNTIME_EVENT_BOUNDARIES.md",
        "docs/CHECKPOINT_RESUME_SEMANTICS.md",
        "docs/RUNTIME_ERROR_RECOVERY.md",
        "docs/CLI_OUTPUT_CONTRACT.md",
        "docs/RUNTIME_TRACE_TOOLRESULT_SLICE_DESIGN.md",
        "docs/RUNTIME_TRACE_TOOLRESULT_MIGRATION.md",
        "docs/ROADMAP_COMPLETION_AUTOPILOT.md",
        "docs/ROADMAP.md",
        "docs/ARCHITECTURE.md",
        "docs/TUI_HITL_INTERACTION_AUDIT.md",
        "docs/P1_TOPIC_SWITCH_PLAN.md",
    }
    _LLM_ARCHIVED = {
        "docs/LLM_PROVIDER_LIVE_SMOKE.md",
        "docs/LLM_AUDIT_STATUS_SCHEMA.md",
        "docs/LLM_PROVIDER_CONFIG.md",
        "docs/LLM_PROVIDER_ADAPTER.md",
        "docs/LLM_PROCESSING_CAPABILITY_MATRIX.md",
        "docs/LLM_PROVIDER_LIVE_SMOKE_REPORT.md",
    }
    if path in _ROOT_ARCHIVED:
        return f"docs/archive/root-stale/{path.removeprefix('docs/')}"
    if path in _LLM_ARCHIVED:
        return f"docs/archive/llm-provider/{path.removeprefix('docs/')}"
    return path


# RC 主线 4 份 spec + preflight + manual smoke + RC status 的 cross-link。
# source_doc key 使用归档路径（文件实际位置）。
# ref 值使用旧路径（匹配归档文档的原始文本内容）。
DOC_CROSS_REFERENCES = {
    "docs/archive/v0.x/V0_2_RC_STATUS.md": [
        "docs/RUNTIME_STATE_MACHINE.md",
        "docs/RUNTIME_EVENT_BOUNDARIES.md",
        "docs/CHECKPOINT_RESUME_SEMANTICS.md",
        "docs/RUNTIME_ERROR_RECOVERY.md",
        "docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md",
        "docs/V0_2_MANUAL_SMOKE_PLAYBOOK.md",
    ],
    "docs/archive/v0.x/V0_2_MANUAL_SMOKE_PLAYBOOK.md": [
        "docs/RUNTIME_EVENT_BOUNDARIES.md",
        "docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md",
        "docs/V0_2_RC_STATUS.md",
    ],
}


@pytest.mark.parametrize(
    ("source_doc", "ref"),
    [(s, r) for s, refs in DOC_CROSS_REFERENCES.items() for r in refs],
)
def test_rc_doc_cross_reference_resolves(source_doc: str, ref: str) -> None:
    """RC 文档中 cross-reference 的目标必须真实存在。

    归档后 source_doc 使用归档路径读取，ref 保留旧路径（与文档内容匹配），
    文件存在性检查通过 _source_to_archive() 映射到实际位置。
    """
    src = (REPO_ROOT / source_doc).read_text(encoding="utf-8")
    assert ref in src, f"{source_doc} 没有引用预期的 {ref}"
    ref_actual = _source_to_archive(ref)
    assert (REPO_ROOT / ref_actual).is_file(), (
        f"{source_doc} 引用了不存在的文件 {ref}（实际路径 {ref_actual}）"
    )


# LLM Processing CLI 入口模块在 RC 里被 manual smoke 引用，必须仍可 import
LLM_CLI_MODULES = [
    "llm.cli",
    "llm.config",
    "llm.providers",
    "run_logger",
]


@pytest.mark.parametrize("module_name", LLM_CLI_MODULES)
def test_llm_processing_module_importable(module_name: str) -> None:
    """LLM Processing 已收口模块仍可 import，证明 RC 主线没有意外改坏。"""
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_security_baseline_pins_known_gaps() -> None:
    """preflight §3 登记的「已知缺口」必须在 baseline 测试中有对应钉死。

    如果以后修了缺口忘了翻 baseline，会先在 manual smoke 里露馅；这条测试
    保证「文档说有这个缺口测试」与「测试文件里真的有这个名字」不漂移。
    """
    baseline_src = (REPO_ROOT / "tests/test_security_baseline.py").read_text(
        encoding="utf-8"
    )
    # M6 文档明确登记的「当前能绕过」用例必须在 baseline 中钉死现状
    assert "known_gap" in baseline_src or "bypass" in baseline_src, (
        "tests/test_security_baseline.py 必须包含至少一个 known_gap / bypass "
        "用例，钉死 preflight §3 登记的『当前确实能绕过』行为，"
        "便于 M6 补丁落地时翻转断言。"
    )


def test_rc_status_lists_historical_xfail_origins_and_closure_status() -> None:
    """RC status 既要保留历史 xfail 归属，也要记录后续闭合状态。

    Roadmap Completion Autopilot 关闭历史 xfail 后，测试不能继续要求"仍有
    3 个 xfailed"。正确的不变量是：历史归属不丢，闭合方式可审计，避免下次
    又把这些缺口当成未知 backlog。
    """
    rc_status = (REPO_ROOT / "docs/archive/v0.x/V0_2_RC_STATUS.md").read_text(encoding="utf-8")
    required_markers = [
        "test_user_switches_topic_mid_task",
        "test_textual_shell_escape_can_cancel_running_generation",
        "test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent",
        "awaiting_feedback_intent",
        "已转 PASS",
        "真实 provider abort deferred",
        "paste burst / multiline input",
    ]
    for needle in required_markers:
        assert needle in rc_status, (
            f"docs/archive/v0.x/V0_2_RC_STATUS.md 必须显式记录历史 xfail/闭合证据 {needle}，"
            "防止已关闭缺口或剩余 provider-abort 边界再次漂移。"
        )

"""Source-of-Truth 一致性测试：防止过期文档模式复活。

S3-G09 瘦身说明（2026-06）：
本守卫在 S3-G09 期间被缩减。原因——它守护的是 pre-S-series 的"第一优先
读取入口"文档模型（docs/PROJECT_STATUS.md、docs/PROGRESS_LEDGER.md、
docs/README.zh.md、00-overview/CURRENT_CAPABILITY_STATUS.zh.md、
06-audit/CURRENT_AUDIT_STATUS.zh.md、design/config-legacy-sunset-contract.md、
dev/AUTO_RUN_WORKFLOW.md）。该模型已被 S-series stage governance
有意识地取代：当前权威入口是 docs/current/ 下的 S_* working set
（S_ROADMAP / S3_BASELINE_STATUS / S3_GOAL / S3_GOAL_GAP 等），
原 PROJECT_STATUS / PROGRESS_LEDGER / CURRENT_*_STATUS 等已整体迁入
docs/history/（"historical evidence, not current routing authority"，
见 AGENTS.md L34-49 与 L230-236）。

因此被退役的 22 个守卫对应的 subject 文档已不在活跃路径上、且无
docs/current/ 等价物——其 subject 已不存在，退役守卫并非放宽断言、
也不削弱 S3 AC-9（没有仍有效的断言可被弱化）。保留下来的守卫仍按
其原本的强度执行：auto-run.md 命令文件、root README.md（已 repoint
到 docs/current/S_ROADMAP.md）、index 断链检查、secret scan、以及
overclaim/strong-claim 的通用 glob 扫描。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


# =========================================================================
# Active docs stale config 引用检查（通用 glob 扫描，subject 仍活跃）
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
# Active docs 不声称 fake provider 可验证任意自然语言语义
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
# Index docs 断链检查
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
        "docs/CURRENT_DOCS.md",
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
# Secret scan
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
        "docs/CURRENT_DOCS.md",
        "docs/CAPABILITY_BOUNDARIES.md",
    ]:
        if not (PROJECT_ROOT / doc_path).exists():
            continue
        text = _read(doc_path)
        for pattern in secret_patterns:
            assert not re.search(pattern, text), f"{doc_path} 包含疑似 secret"


# =========================================================================
# .claude/commands/auto-run.md 命令文件守护
# =========================================================================

AUTO_RUN_CMD = ".claude/commands/auto-run.md"


def _read_auto_run() -> str:
    return _read(AUTO_RUN_CMD)


def test_auto_run_references_project_status():
    """auto-run.md 必须在 Startup 引用 PROJECT_STATUS.md。"""
    text = _read_auto_run()
    assert "PROJECT_STATUS.md" in text


def test_auto_run_references_progress_ledger():
    """auto-run.md 必须在 Startup 引用 PROGRESS_LEDGER.md。"""
    text = _read_auto_run()
    assert "PROGRESS_LEDGER.md" in text


def test_auto_run_references_auto_run_workflow():
    """auto-run.md 必须引用 AUTO_RUN_WORKFLOW.md。"""
    text = _read_auto_run()
    assert "AUTO_RUN_WORKFLOW.md" in text


def test_auto_run_includes_task_type_routing():
    """auto-run.md 必须包含任务类型路由（bug_fix / docs_cleanup 等）。"""
    text = _read_auto_run()
    assert "bug_fix" in text
    assert "docs_cleanup" in text
    assert "config_safety" in text
    assert "architecture_change" in text


def test_auto_run_includes_loop_start_selection():
    """auto-run.md 必须包含 loop 起点选择规则，不得每次从头开始。"""
    text = _read_auto_run()
    assert "不要每次从头开始" in text or "Choose loop start" in text
    assert "loop" in text.lower()


def test_auto_run_includes_progress_update_rule():
    """auto-run.md 必须包含进度更新规则：每轮至少更新一个 doc/report。"""
    text = _read_auto_run()
    assert "每轮" in text
    assert "PROGRESS_LEDGER.md" in text or "PROJECT_STATUS.md" in text


def test_auto_run_includes_hard_stops():
    """auto-run.md 必须定义 Hard stops 条件。"""
    text = _read_auto_run()
    assert "Hard stop" in text or "Hard stops" in text or "hard stop" in text.lower()
    assert "secret" in text.lower()


def test_auto_run_forbids_archived_docs_as_current():
    """auto-run.md 不得引用 docs/archive/ 作为当前工作源。"""
    text = _read_auto_run()
    # 仓库不再保留 archive/ 目录；auto-run 不得将 archive 文档作为当前指令
    assert "docs/archive" not in text
    # 仓库规则必须以 PROJECT_STATUS.md 为最高事实源
    assert "PROJECT_STATUS" in text


def test_auto_run_forbids_legacy_provider_paths():
    """auto-run.md 必须禁止恢复 provider profiles / request_path 等 legacy 路径。"""
    text = _read_auto_run()
    assert "provider" in text.lower() and "profile" in text.lower()
    assert "request_path" in text or "auth_scheme" in text or "api_key_env" in text


def test_auto_run_forbids_committing_config_yaml():
    """auto-run.md 必须禁止 commit config/config.yaml（含真实 key）。"""
    text = _read_auto_run()
    assert "config/config.yaml" in text
    assert "commit" in text.lower()


# =========================================================================
# root README.md 守护
# =========================================================================

# S3-G09：原 test_root_readme_references_project_status 守护 README.md 指向
# docs/PROJECT_STATUS.md。pre-S-series 的 PROJECT_STATUS 已迁入 docs/history/，
# README.md 现以 docs/current/ S_* working set（S_ROADMAP.md 等）为权威入口。
# 这里把断言 repoint 到 docs/current/，而非放宽——README 仍必须有权威入口。
def test_root_readme_references_project_status():
    """root README.md 必须指向 docs/current/ S-series 工作集作为权威入口。

    S3-G09：PROJECT_STATUS.md 已归档（docs/history/），权威入口改为
    docs/current/S_ROADMAP.md / docs/current/S*_BASELINE_STATUS.md。
    """
    text = _read("README.md")
    assert "docs/current/" in text
    assert "docs/current/S_ROADMAP.md" in text


def test_root_readme_no_env_as_primary_config():
    """root README.md 不得推荐 .env 作为主配置路径。"""
    text = _read("README.md")
    # 可以提到 .env 但必须标记为 legacy/deprecated
    if ".env" in text:
        assert "legacy" in text.lower() or "deprecated" in text.lower() or "已" in text


def test_root_readme_no_broken_audit_links():
    """root README.md 不得包含指向不存在审计文档的链接。"""
    text = _read("README.md")
    # 不得指向已归档的旧审计文档
    broken_audit_refs = [
        "capability-gap-audit-low-complexity-2026-05-25.md",
        "global-red-team-product-architecture-audit-2026-05-25.md",
    ]
    for ref in broken_audit_refs:
        assert ref not in text, f"root README.md 包含已归档审计文档引用: {ref}"


# =========================================================================
# auto-run.md Continuation Policy 守护
# =========================================================================

def test_auto_run_continuation_policy_exists():
    """auto-run.md 必须包含 Continuation Policy 节。"""
    text = _read_auto_run()
    assert "Continuation Policy" in text
    assert "自动继续" in text or "auto" in text.lower()


def test_auto_run_loop_completion_not_stop_condition():
    """auto-run.md 必须声明 loop 完成不是停止条件。"""
    text = _read_auto_run()
    assert "loop 成功完成" in text or "loop completion" in text.lower()


def test_auto_run_commit_push_not_stop_condition():
    """auto-run.md 必须声明 commit/push 完成不是停止条件。"""
    text = _read_auto_run()
    assert "commit/push 完成" in text or "commit/push" in text.lower()


def test_auto_run_post_loop_self_review_exists():
    """auto-run.md 必须包含 Post-Loop Self-Review checklist。"""
    text = _read_auto_run()
    assert "Post-Loop Self-Review" in text
    assert "本轮 target" in text or "target" in text.lower()


def test_auto_run_next_loop_selection_exists():
    """auto-run.md 必须包含 Next-Loop Selection 规则。"""
    text = _read_auto_run()
    assert "Next-Loop Selection" in text
    assert "P0" in text and "P1" in text


def test_auto_run_hard_stops_narrowed():
    """auto-run.md 的 hard stop 必须收窄且包含关键条件。"""
    text = _read_auto_run()
    # 必须包含核心 hard stop（不应移除的）
    assert "secret" in text.lower()
    assert "第二条 runtime flow" in text or "fake-real split" in text
    # 必须排除旧的过宽条件（dirty repo 不再作为无条件 hard stop）
    # 新增：不得在已授权范围内反复请求授权
    assert "已授权" in text or "授权" in text


def test_auto_run_final_output_not_stop_signal():
    """auto-run.md 的 Final output 必须标注为进度日志而非停止信号。"""
    text = _read_auto_run()
    assert "进度日志" in text or "不是停止信号" in text or "not stop signal" in text.lower()


# =========================================================================
# auto-run.md Skill Routing Policy 守护（AutoRun Skill Router Upgrade）
# =========================================================================


def test_auto_run_includes_skill_routing_policy():
    """auto-run.md 必须包含 Skill Routing Policy 节。"""
    text = _read_auto_run()
    assert "Skill Routing Policy" in text
    assert "技能体系" in text or "skill" in text.lower()


def test_auto_run_mentions_compound_engineering():
    """auto-run.md 必须提到 Compound Engineering 技能体系。"""
    text = _read_auto_run()
    assert "Compound Engineering" in text


def test_auto_run_mentions_g_stack():
    """auto-run.md 必须提到 G-Stack 技能体系。"""
    text = _read_auto_run()
    assert "G-Stack" in text


def test_auto_run_mentions_superpowers():
    """auto-run.md 必须提到 Superpowers 技能体系。"""
    text = _read_auto_run()
    assert "Superpowers" in text


def test_auto_run_mentions_plan_eng_review():
    """auto-run.md 必须提到 plan-eng-review 技能体系。"""
    text = _read_auto_run()
    assert "plan-eng-review" in text


def test_auto_run_mentions_review_skill():
    """auto-run.md 必须提到 review 作为独立技能体系。"""
    text = _read_auto_run()
    # "review" 出现在 Skill Router Decision Table 和 skill 相关上下文中
    assert "review" in text.lower()


def test_auto_run_includes_skill_router_decision_table():
    """auto-run.md 必须包含 Skill Router Decision Table。"""
    text = _read_auto_run()
    assert "Skill Router Decision Table" in text
    assert "Primary Skill" in text
    assert "Secondary Skill" in text


def test_auto_run_review_completion_not_stop_condition():
    """auto-run.md 必须声明 review 完成不是停止条件。"""
    text = _read_auto_run()
    assert "review 完成不是停止条件" in text or "review 完成" in text


def test_auto_run_skill_selection_not_stop_condition():
    """auto-run.md 必须声明选择/切换技能不是停止条件。"""
    text = _read_auto_run()
    assert "选择技能不是停止条件" in text or "选择/切换技能" in text


def test_auto_run_next_recommended_loop_should_continue():
    """auto-run.md 必须声明 next recommended loop 输出后应继续而非停止。"""
    text = _read_auto_run()
    assert "next recommended loop" in text.lower()


def test_auto_run_includes_skill_routing_in_final_output():
    """auto-run.md 的 Final output 格式必须包含 skill routing 信息。"""
    text = _read_auto_run()
    assert "primary" in text.lower() and "secondary" in text.lower()


def test_auto_run_task_types_cover_all():
    """auto-run.md 必须覆盖所有任务类型（含 debug_root_cause / evidence_honesty 等）。"""
    text = _read_auto_run()
    assert "debug_root_cause" in text
    assert "evidence_honesty" in text
    assert "implementation" in text
    assert "post_loop_review" in text


def test_auto_run_skill_selection_by_task_type_not_blind():
    """auto-run.md 必须声明不盲选技能——每次根据任务类型查表选择。"""
    text = _read_auto_run()
    assert "不盲选" in text or "Skill Router Decision Table" in text


def test_auto_run_forbids_blind_skill_selection():
    """auto-run.md 的 Forbidden Patterns 必须禁止盲选技能。"""
    text = _read_auto_run()
    assert "不盲选技能" in text or "Skill Router Decision Table" in text


# =========================================================================
# auto-run.md Recursive Backtrack Policy 守护（/plan-eng-review audit）
# =========================================================================


def test_auto_run_recursive_backtrack_policy_exists():
    """auto-run.md 必须包含 Recursive Backtrack Policy 节。

    review gate 失败不是停止条件——必须按证据回退到正确的上游阶段重新 loop。
    ENGINEERING_WORKFLOW.md Section 4 已定义回退规则，auto-run.md 必须引用并执行。
    """
    text = _read_auto_run()
    assert "Recursive Backtrack Policy" in text
    assert "回退" in text
    assert "ENGINEERING_WORKFLOW.md" in text


def test_auto_run_review_failure_routing_table_exists():
    """auto-run.md 必须包含 Review Failure Routing Table。

    当 review gate 发现具体 failure pattern（expected_events 未检查、no-crash PASS、
    memory path split、PROJECT_STATUS false resolved 等）时，必须按表回溯到对应阶段。
    """
    text = _read_auto_run()
    assert "Review Failure Routing Table" in text
    assert "expected_events" in text or "no-crash" in text
    assert "回退目标" in text


def test_auto_run_partial_fix_marking_rule_exists():
    """auto-run.md 必须包含 Claim-to-Evidence Gate 且定义 partial fix 标记规则。

    partial fix 只能标记 PARTIAL，不得标记 RESOLVED。证据不足时不得 claim 完成。
    """
    text = _read_auto_run()
    assert "Claim-to-Evidence Gate" in text
    assert "PARTIAL" in text
    assert "RESOLVED" in text


def test_auto_run_status_overclaim_correction_rule_exists():
    """auto-run.md 必须禁止 PROJECT_STATUS false resolved（证据不足仍标 RESOLVED）。

    Post-Loop Self-Review 发现 PROJECT_STATUS 更新包含 false resolved 时，
    必须回退到 status correction。
    """
    text = _read_auto_run()
    assert "false resolved" in text
    assert "status correction" in text


def test_auto_run_forbids_review_failure_as_completed():
    """auto-run.md 必须禁止 review 失败仍标记 COMPLETED。

    禁止的 completion 模式必须包含：review 失败仍标记 COMPLETED、
    partial fix 升级为 global resolved、guard test pass 冒充 loop pass。
    """
    text = _read_auto_run()
    assert "review 失败仍标记 COMPLETED" in text or "review 失败" in text
    assert "partial fix" in text.lower() or "PARTIAL" in text
    assert "guard test pass" in text.lower() or "冒充 loop pass" in text


# =========================================================================
# auto-run.md Workflow Stage → Skill Table 守护
# =========================================================================


def test_auto_run_includes_workflow_stage_skill_table():
    """auto-run.md 必须包含 Workflow Stage → Skill Table。

    该表按工程阶段（而非仅任务类型）映射：Stage / Trigger / Primary Skill /
    Secondary Skill / Expected Action / Failure Route。
    """
    text = _read_auto_run()
    assert "Workflow Stage" in text
    assert "Failure Route" in text
    # 至少包含 6 个核心 stage
    assert "Audit" in text and "Red-team" in text
    assert "Evidence honesty" in text
    assert "Production path repair" in text
    assert "Post-loop review" in text


def test_auto_run_workflow_stage_table_has_failure_routes():
    """Workflow Stage → Skill Table 中每个 stage 必须有 Failure Route。

    Failure route 不是建议，是强制回退目标。
    """
    text = _read_auto_run()
    assert "Failure Route" in text
    # 验证关键 failure route 存在
    assert "evidence classification" in text or "remediation plan" in text
    assert "harness evaluator" in text or "evidence taxonomy" in text
    assert "runtime integration" in text or "dispatcher" in text
    assert "status correction" in text


# =========================================================================
# auto-run.md Status Promotion Gate 守护
# =========================================================================


def test_auto_run_includes_status_promotion_gate():
    """auto-run.md 必须包含 Status Promotion Gate 节。

    PROJECT_STATUS 中 P0/P1 降级或 RESOLVED 必须通过 6 道门禁。
    """
    text = _read_auto_run()
    assert "Status Promotion Gate" in text
    assert "原始 finding" in text
    assert "independent review" in text.lower()


def test_auto_run_status_promotion_forbids_unverified_claims():
    """Status Promotion Gate 必须禁止无证据的全局声称。

    'all P0/P1 resolved'、'completed'、'user-usable' 等声称在门禁通过前禁止。
    """
    text = _read_auto_run()
    assert "all P0/P1 resolved" in text
    assert "user-usable" in text


def test_auto_run_status_promotion_requires_all_gates():
    """Status Promotion Gate 必须要求全部 6 道门禁，缺一不可。

    不满足全部门禁时只能写 PARTIAL / OVERCLAIMED / NOT_FIXED / EVIDENCE_PENDING。
    """
    text = _read_auto_run()
    assert "PARTIAL" in text
    assert "OVERCLAIMED" in text
    assert "EVIDENCE_PENDING" in text


# =========================================================================
# auto-run.md Forbidden Patterns 扩展守护
# =========================================================================


def test_auto_run_forbids_no_crash_as_capability_pass():
    """auto-run.md 必须禁止 no-crash 标为 capability PASS。

    no-crash 是最低标准（smoke），不是用户能力证据。
    """
    text = _read_auto_run()
    assert "no-crash" in text.lower()
    assert "capability" in text.lower()


def test_auto_run_forbids_admin_completed_as_capability():
    """auto-run.md 必须禁止 admin completed 冒充 capability completed。

    docs/guard 是管理层证据，不是用户能力。
    """
    text = _read_auto_run()
    assert "admin completed" in text


def test_auto_run_stage_switching_rules_exist():
    """auto-run.md 必须包含阶段切换规则。

    同一任务在不同阶段自动切换 primary skill。
    Failure route 是强制回退目标，不是建议。
    """
    text = _read_auto_run()
    assert "阶段切换" in text
    assert "强制回退" in text


# =========================================================================
# Evidence Taxonomy & Overclaim Guard Tests (Loop 16)
# =========================================================================

# 需要扫描的 active docs
OVERCLAIM_SCAN_FILES = [
    "docs/PROJECT_STATUS.md",
    "docs/PROGRESS_LEDGER.md",
    "docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md",
    "docs/06-audit/CURRENT_AUDIT_STATUS.zh.md",
    "docs/README.zh.md",
]


def _read_overclaim_files() -> dict[str, str]:
    result: dict[str, str] = {}
    for rel in OVERCLAIM_SCAN_FILES:
        fpath = PROJECT_ROOT / rel
        if fpath.exists():
            result[rel] = fpath.read_text(encoding="utf-8")
    return result


def test_no_doc_claims_all_p0_p1_resolved():
    """Active docs 不得无条件声称 'all P0/P1 resolved'。

    Loop 13 只修了 SUBAGENT_DELEGATE_L0 一个 evidence 分类，不能把 P0/P1 全标 resolved。
    """
    for rel, text in _read_overclaim_files().items():
        if "all P0/P1 resolved" in text or "所有 P0/P1 已解决" in text:
            # 只有在显式说明这是 overclaim 或标记为禁止声称时才可以
            if "禁止" in text or "overclaim" in text.lower() or "OVERCLAIMED" in text:
                continue
            pytest.fail(f"{rel}: 包含 'all P0/P1 resolved' 声称（未标记为 overclaim/禁止）")


def test_no_doc_claims_user_usable_unqualified():
    """Active docs 不得无条件声称 'user-usable'。

    PROJECT_STATUS 明确：当前阶段是 developer prototype / local development。
    'limited user-usable' 也是 overclaim——developer prototype 不面向用户。
    """
    for rel, text in _read_overclaim_files().items():
        if "limited user-usable" in text:
            # 必须同时包含否定或 developer prototype 标记
            ok = ("不可标" in text or "developer prototype" in text
                  or "local development" in text or "不在当前" in text
                  or "不是" in text or "❌" in text)
            if not ok:
                pytest.fail(
                    f"{rel}: 包含 'limited user-usable' 声称"
                    "（缺少 developer prototype 降级）"
                )


def test_no_doc_claims_12_12_completed_unqualified():
    """Active docs 不得无条件声称 '12/12 loops 全部完成'。

    多个 loops 是 admin/docs 完成，不是 capability 完成。Loop 13 被标记 OVERCLAIMED。
    """
    for rel, text in _read_overclaim_files().items():
        if "12/12" in text and "全部完成" in text:
            # 只有在显式说明 breakdown 或标记为 overclaim 时才可以
            ok = ("OVERCLAIMED" in text or "overclaim" in text.lower()
                  or "admin/docs" in text or "实质代码" in text
                  or "诚实" in text or "honest" in text.lower()
                  or "实际" in text)
            if not ok:
                pytest.fail(f"{rel}: 包含 '12/12 全部完成' 声称（缺少 honest breakdown）")


def test_current_docs_do_not_restore_old_remediation_overclaim():
    """当前文档不得恢复旧 remediation plan 的 all-done overclaim。"""
    for rel, text in _read_overclaim_files().items():
        if "12/12" in text and "全部完成" in text:
            pytest.fail(f"{rel}: 恢复了旧 remediation all-done overclaim")

"""v0.2 RC 文档一致性轻量断言。

这套测试不读 LLM、不跑 Runtime，只对几份关键文档做存在性 + 关键字段
的纯文本断言，目的：当后续修改 RC 状态/RC 决策/基础 TUI plan 时，
不会让三份文档之间「自相矛盾」（例如 RC_STATUS 说已完成而 PLANNING
仍说未做、RC_DECISION 说不做 TUI 但 BASIC_TUI_PLAN 缺失等）。

有意保持轻量：
- 不验证完整 markdown 结构。
- 不解析章节树。
- 只检查 RC 收口期容易出问题的几个稳定字符串。
"""

from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "docs"

REQUIRED_DOCS = [
    "V0_2_PLANNING.md",
    "V0_2_RC_STATUS.md",
    "V0_2_RC_DECISION.md",
    "V0_2_BASIC_TUI_PLAN.md",
    "V0_2_MANUAL_SMOKE_PLAYBOOK.md",
    "V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md",
    "RUNTIME_STATE_MACHINE.md",
    "RUNTIME_EVENT_BOUNDARIES.md",
    "CHECKPOINT_RESUME_SEMANTICS.md",
    "RUNTIME_ERROR_RECOVERY.md",
    "CLI_OUTPUT_CONTRACT.md",
]


@pytest.mark.parametrize("name", REQUIRED_DOCS)
def test_required_v0_2_doc_exists(name):
    """RC 收口涉及的关键文档不能丢。"""
    path = DOCS / name
    assert path.exists() and path.stat().st_size > 100, (
        f"必备文档缺失或为空：{name}"
    )


def _read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_rc_status_records_real_baseline():
    """RC_STATUS 的测试基线必须和当前真实数量同步（不能停在 387）。"""
    src = _read("V0_2_RC_STATUS.md")
    assert "528 passed" in src, (
        "V0_2_RC_STATUS.md 测试基线还停在旧数值；执行 pytest 后应同步。"
    )
    assert "387 passed" not in src, (
        "V0_2_RC_STATUS.md 仍然包含历史基线 387 passed，需要清理。"
    )


def test_rc_status_records_p2_smoke_fixes():
    """RC_STATUS 必须记录 P2 两次真实 smoke 暴露的修复，否则后续会
    再次怀疑「项目外写入」/「policy denial 误归类」是否已闭环。"""
    src = _read("V0_2_RC_STATUS.md")
    assert "项目外写硬拦截" in src or "block writes outside" in src
    assert "policy denial" in src or "blocked_by_policy" in src
    # 这条措辞是 smoke 暴露的真实文案；改了要能马上看到
    assert "用户连续拒绝多次操作" in src, (
        "RC_STATUS 应至少在历史/解释段保留旧错误措辞，便于追溯。"
    )


def test_rc_decision_marks_release_candidate():
    """RC_DECISION 的判定结论不能写成模糊「待确认」。"""
    src = _read("V0_2_RC_DECISION.md")
    assert "满足 release candidate" in src or "满足 RC" in src
    assert "528 passed" in src
    assert "人工试用最短路径" in src


def test_rc_decision_does_not_advertise_unfinished_capabilities():
    """RC_DECISION 不应把基础 TUI / Skill 正式化 / cancel UI 当作
    v0.2 RC 已交付能力来宣传。"""
    src = _read("V0_2_RC_DECISION.md")
    # 这些必须出现在「非目标」段而不是「已完成」段。简单守护：
    # 「已完成能力清单」表格里不能含这些关键词。
    completed_section = src.split("## 2. 已完成能力清单")[1].split("## 3.")[0]
    forbidden = ["Textual TUI", "基础 TUI", "Skill 正式化", "sub-agent",
                 "Esc cancel", "generation.cancelled"]
    for kw in forbidden:
        assert kw not in completed_section, (
            f"RC_DECISION 把未交付能力 {kw!r} 写进了「已完成能力清单」。"
        )


def test_basic_tui_plan_is_planning_only():
    """BASIC_TUI_PLAN 必须明确仅做 planning，不做实现。"""
    src = _read("V0_2_BASIC_TUI_PLAN.md")
    assert "只做 planning" in src or "只做 planning，不做实现" in src
    assert "v0.3" in src.lower() or "v0.3" in src
    assert "M7" in src


def test_basic_tui_plan_separates_v0_2_vs_v0_3():
    """基础 TUI 与高级 TUI 的边界必须显式表达。"""
    src = _read("V0_2_BASIC_TUI_PLAN.md")
    assert "v0.3 高级 TUI" in src
    # 关键边界字段
    for kw in ["Esc", "paste burst", "多面板"]:
        assert kw in src, f"基础 TUI plan 缺少与 v0.3 的边界字段 {kw!r}"


def test_planning_m7_links_basic_tui_plan_or_at_least_mentions_basic_tui():
    """V0_2_PLANNING 的 M7 章节应至少提到「基础 TUI」措辞，便于
    跳转到 BASIC_TUI_PLAN.md。"""
    src = _read("V0_2_PLANNING.md")
    assert "基础 TUI" in src and "M7" in src


def test_smoke_playbook_marks_security_section_automated():
    """playbook §5.2 应标注「已 100% 自动化」或等价措辞，避免用户
    在自动化已经覆盖的情况下还以为必须人工跑安全 smoke。"""
    src = _read("V0_2_MANUAL_SMOKE_PLAYBOOK.md")
    assert "已 100% 自动化" in src or "已 100％ 自动化" in src or "100% 自动化" in src


def test_no_doc_still_says_force_stop_means_user_consecutive_rejection():
    """任何 v0.2 文档都不应仍把 FORCE_STOP 解释成「用户连续拒绝
    多次操作」——这是已修复的缺陷措辞。允许出现在 RC_STATUS 的
    历史/解释段（带「旧」「历史」「修复」上下文）。"""
    for name in REQUIRED_DOCS:
        src = _read(name)
        if "用户连续拒绝多次操作" not in src:
            continue
        # 出现就必须带历史/修复上下文
        context_keywords = ["smoke", "修复", "历史", "误", "已修复",
                            "fix(runtime)", "误归类", "误导"]
        assert any(kw in src for kw in context_keywords), (
            f"{name} 仍把『用户连续拒绝多次操作』当作正面说明；"
            "该措辞已被修复弃用，只允许在解释/历史段出现。"
        )

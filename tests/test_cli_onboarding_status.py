"""CLI onboarding current-status contract tests.

这些测试只约束用户可见 help 文案，不新增 runtime 能力。
目的：避免 help 输出把 fake/local rehearsal、real provider auth concern、
SubAgent L0 demo 或 local trial 状态讲含糊。
"""

from __future__ import annotations


def test_onboarding_links_current_status_and_local_trial_boundaries() -> None:
    """help 必须把当前状态、local trial 边界和 real auth concern 讲清楚。"""

    from agent.cli_renderer import render_onboarding

    output = render_onboarding()

    assert "docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md" in output
    assert "developer prototype / local development" in output
    assert "docs/manual-trials/" in output
    assert "real provider 401" in output
    assert "config/auth concern" in output


def test_onboarding_names_core_user_surfaces_without_overclaiming() -> None:
    """help 必须列出可用 surface，同时保持 fake/local/demo-only 边界。"""

    from agent.cli_renderer import render_onboarding

    output = render_onboarding()

    required = (
        "Fake/local mode",
        "Real provider opt-in",
        "Tools",
        "Memory",
        "SubAgents",
        "Run summary / debug",
        "DEMO-ONLY",
        "not broadly user-ready",
    )
    for phrase in required:
        assert phrase in output

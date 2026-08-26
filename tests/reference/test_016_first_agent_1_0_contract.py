from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs/architecture/016_FIRST_AGENT_1_0_EXPERIENCE_DESIGN.md"
ACCEPTANCE = ROOT / "docs/acceptance/016_FIRST_AGENT_1_0_E3.md"
PLAN = ROOT / "docs/plans/2026-08-20-001-first-agent-1-0-product-convergence-plan.md"


def test_016_material_is_frozen_complete_and_traceable() -> None:
    design = DESIGN.read_text(encoding="utf-8")
    acceptance = ACCEPTANCE.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")

    assert "status: frozen" in design
    assert "status: frozen" in acceptance
    assert "status: frozen" in plan
    assert len(re.findall(r"^### E3-J\d+ ", acceptance, flags=re.MULTILINE)) == 12
    assert len(re.findall(r"^\d+\. `[^`]+`$", acceptance, flags=re.MULTILINE)) == 25
    assert "AgentRuntime.run_turn" in design
    assert "不得加入第二套" in plan or "不建立第二套" in plan
    assert "1.0.0" in design and "1.0.0" in acceptance and "1.0.0" in plan
    assert "连续三轮" in acceptance and "fresh independent" in acceptance

    for env_name in (
        "FIRST_AGENT_016_E3_PROVIDER",
        "FIRST_AGENT_016_E3_BASE_URL",
        "FIRST_AGENT_016_E3_MODEL",
        "FIRST_AGENT_016_E3_API_KEY",
        "FIRST_AGENT_016_E3_WEB_API_KEY",
    ):
        assert env_name in acceptance

    for forbidden in ("TODO", "TBD", "replace-with", "sk-", "tvly-"):
        assert forbidden not in design
        assert forbidden not in acceptance
        assert forbidden not in plan


def test_016_default_ui_denylist_is_frozen() -> None:
    acceptance = ACCEPTANCE.read_text(encoding="utf-8")

    for internal_name in (
        "goal_id",
        "request_id",
        "binding_digest",
        "receipt_digest",
        "criterion_id",
        "checkpoint_revision",
        "control_schema",
    ):
        assert f"`{internal_name}`" in acceptance

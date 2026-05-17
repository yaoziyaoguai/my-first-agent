"""SubAgent Phase 18: T1 synthetic dogfood tests."""

from __future__ import annotations

from pathlib import Path

from scripts.dogfood_subagent_system import run_synthetic_dogfood


def test_t1_synthetic_dogfood_runs_local_without_private_data(tmp_path: Path) -> None:
    """T1 dogfood 必须 local/no-network/no-LLM，并产出 redacted audit packet。"""

    packet = run_synthetic_dogfood(tmp_root=tmp_path, mode="synthetic")

    assert packet["tier"] == "T1"
    assert packet["capability_level"] == "L0"
    assert packet["real_llm_used"] is False
    assert packet["network_used"] is False
    assert packet["external_process_used"] is False
    assert packet["private_data_read"] is False
    assert packet["scenarios_passed"] >= 15
    assert "literal-secret-value" not in str(packet)


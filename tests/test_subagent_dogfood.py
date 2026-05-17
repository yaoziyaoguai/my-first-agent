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


def test_t1_dogfood_missing_descriptor_uses_absent_role(tmp_path: Path) -> None:
    """Descriptor Not Found 场景必须真的 miss，不能误命中 reviewer fixture。"""

    packet = run_synthetic_dogfood(tmp_root=tmp_path, mode="synthetic")
    scenarios = {item["scenario"]: item for item in packet["audit_packets"]}

    missing = scenarios["Descriptor Not Found"]
    assert missing["role"] == "missing-descriptor"
    assert missing["status"] == "error"
    assert missing["stop_reason"] == "error"
    assert "descriptor not found" in missing["warnings"]


def test_t1_dogfood_nested_delegation_is_policy_blocked(tmp_path: Path) -> None:
    """Nested delegation 场景只能 fail-closed，不能 spawn child 或打开 L5。"""

    packet = run_synthetic_dogfood(tmp_root=tmp_path, mode="synthetic")
    scenarios = {item["scenario"]: item for item in packet["audit_packets"]}

    nested = scenarios["Policy Violation Nested Delegation"]
    assert nested["status"] == "policy_blocked"
    assert nested["stop_reason"] == "policy_blocked"
    assert nested["tools_executed"] == []
    assert nested["external_process_used"] is False

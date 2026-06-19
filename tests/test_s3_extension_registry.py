"""S3-G12: extension capability registry / observability report / health check（可选增强）。

在 G02 契约 + G03/G04 接入之上提供**可观测性增强**（非生态化、不改 spine）：
- registry 聚合 S3 governed-active extension capabilities（MCP + SubAgent）；
- report 把每个 capability 的 metadata（kind/id/default-state/risk/evidence/verification）
  投影成可审计条目；
- health check 校验每个声明 capability 都满足 AC-4 治理形状（risk/verification/evidence
  齐全、default-off + opt-in 通道、id 唯一）。

Skill 是 S2 governed-active，作为 capability contract **参考**，不注册为 S3 extension
（不模糊 S2/S3 边界）。
"""
from __future__ import annotations

from agent.extension_capability import ExtensionCapability
from agent.extension_registry import (
    EXTENSION_CAPABILITIES,
    build_extension_capability_report,
    check_extension_capability_health,
)


def test_registry_covers_s3_governed_active_capabilities():
    """registry 必须含 S3 必达的两个 governed-active capability（MCP + SubAgent）。"""
    report = build_extension_capability_report()
    ids = set(report.capability_ids)
    assert {"mcp", "subagent"} <= ids
    # EXTENSION_CAPABILITIES 与 report 一致
    assert {c.id for c in EXTENSION_CAPABILITIES} == ids


def test_report_entries_carry_required_metadata():
    """每个 report 条目携带 AC-4 五要素的投影（可审计）。"""
    report = build_extension_capability_report()
    assert report.capabilities  # 非空
    for entry in report.capabilities:
        assert entry.kind in ("skill", "mcp", "subagent")
        # governed-active = default-off
        assert entry.default_state == "disabled"
        assert entry.risk_level in ("low", "medium", "high")
        assert entry.evidence_subsystem
        assert entry.verification_spec
        assert entry.enable_env  # 有 opt-in 通道


def test_health_check_passes_for_declared_capabilities():
    """已声明的 S3 governed-active capabilities 满足 AC-4 治理形状。"""
    result = check_extension_capability_health()
    assert result.healthy is True, f"health issues: {result.issues}"
    assert result.issues == ()


def test_health_check_detects_missing_governance():
    """缺 risk/verification/evidence 的 capability → health check 报问题（守护不弱化）。"""
    broken = ExtensionCapability(
        kind="mcp", id="mcp:broken", name="broken", description="missing governance fields"
    )
    result = check_extension_capability_health(capabilities=(broken,))
    assert result.healthy is False
    issues_blob = " ".join(result.issues)
    assert "missing risk" in issues_blob
    assert "missing verification" in issues_blob
    assert "missing evidence" in issues_blob


def test_health_check_detects_duplicate_and_unkillable_enabled():
    """id 重复 / default-enabled 且无 opt-in 通道 → 报问题。"""
    cap = ExtensionCapability(
        kind="mcp", id="mcp:dup", name="dup", description="x", default_state="enabled",
        enable_env=None,
    )
    result = check_extension_capability_health(capabilities=(cap, cap))
    assert result.healthy is False
    issues_blob = " ".join(result.issues)
    assert "duplicate" in issues_blob
    assert "kill switch" in issues_blob

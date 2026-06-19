"""S3-G02: 统一 extension capability 契约测试（AC-4）。

契约要求（S3_GOAL §6 AC-4；S3_GOAL_GAP S3-G02）：每个进入 governed-active 的
extension（MCP、SubAgent；Skill 作为参考模型）以**同一形状**声明 metadata /
enable-disable / risk / verification / evidence。

本测试先以 RED 形式断言契约存在且字段齐全，并证明 MCP / SubAgent / Skill 三种
capability 都能按契约声明。真实接入（MCP/SubAgent 走 governed path）由 S3-G03/G04 落地。
"""
from __future__ import annotations

import dataclasses

import pytest

from agent.extension_capability import (
    EXTENSION_KINDS,
    RISK_LEVELS,
    ExtensionActivationDecision,
    ExtensionCapability,
    ExtensionEvidenceDescriptor,
    ExtensionRisk,
    ExtensionVerification,
    evaluate_activation,
)


def test_contract_exposes_required_shapes():
    """契约必须暴露 AC-4 五要素对应的数据形状。"""
    # metadata / enable-disable / risk / verification / evidence
    for shape in (
        ExtensionCapability,
        ExtensionRisk,
        ExtensionVerification,
        ExtensionEvidenceDescriptor,
        ExtensionActivationDecision,
    ):
        assert dataclasses.is_dataclass(shape), f"{shape} 应为 dataclass"
    assert frozenset({"skill", "mcp", "subagent"}) == EXTENSION_KINDS
    # 与 Skill descriptor risk_level 同集合（同一风险口径）
    assert frozenset({"low", "medium", "high"}) == RISK_LEVELS


def test_capability_has_all_five_contract_elements():
    """单个 ExtensionCapability 必须能同时承载五要素字段。"""
    cap = ExtensionCapability(
        kind="mcp",
        id="mcp:repo-doc-reader",
        name="Repo Doc Reader (fixture MCP source)",
        description="受控 MCP tool source：读 fixture repo 证据。",
        default_state="disabled",
        enable_env="MY_FIRST_AGENT_S3_MCP_ENABLE",
        risk=ExtensionRisk(
            level="medium",
            summary="外部工具来源（即便 fixture），调用须经 policy/evidence。",
            mitigations=("allowlist", "policy gate", "evidence recording"),
        ),
        verification=ExtensionVerification(
            spec="fake/fixture MCP tool 经 governed path 调用并产生 evidence",
            acceptance_refs=("S3-G03", "S3_REFERENCE_TASK.md §5"),
        ),
        evidence=ExtensionEvidenceDescriptor(
            subsystem="tool",
            shape="governed tool report: allowed/rejected + MCP tool result",
        ),
    )
    # metadata
    assert cap.kind == "mcp" and cap.id and cap.name and cap.description
    # enable-disable
    assert cap.is_default_off() is True
    # risk / verification / evidence 均可读取
    assert cap.risk.level == "medium" and cap.risk.mitigations
    assert cap.verification.spec and cap.verification.acceptance_refs
    assert cap.evidence.subsystem == "tool" and cap.evidence.shape


def test_mcp_and_subagent_can_declare_against_contract():
    """MCP 与 SubAgent 都能按同一契约声明（解锁 G03/G04 统一接入）。"""
    mcp = ExtensionCapability(
        kind="mcp", id="mcp:repo-doc-reader", name="MCP repo doc reader",
        description="受控 MCP tool source", default_state="disabled",
        enable_env="MY_FIRST_AGENT_S3_MCP_ENABLE",
        risk=ExtensionRisk("medium", "external tool source"),
        verification=ExtensionVerification("governed path + evidence", ("S3-G03",)),
        evidence=ExtensionEvidenceDescriptor("tool", "mcp tool report"),
    )
    sub = ExtensionCapability(
        kind="subagent", id="subagent:repo-gap-auditor", name="Repo Gap Auditor",
        description="read-only / audit-first / parent-mediated SubAgent",
        default_state="disabled",
        enable_env="MY_FIRST_AGENT_S3_SUBAGENT_ENABLE",
        risk=ExtensionRisk(
            "medium", "child 委派须 parent-mediated，不得绕过主 Agent",
            mitigations=("parent-mediated", "read-only", "policy gate"),
        ),
        verification=ExtensionVerification(
            "SubAgentAuditRecord + adjudicate_result 经 policy/evidence", ("S3-G04",),
        ),
        evidence=ExtensionEvidenceDescriptor("task", "subagent audit record"),
    )
    assert {mcp.kind, sub.kind} == {"mcp", "subagent"}
    assert mcp.is_default_off() and sub.is_default_off()


def test_skill_reference_shape_is_compatible_with_contract():
    """Skill（参考模型）按契约声明时维持 S2 governed-active default-off 语义。"""
    skill = ExtensionCapability(
        kind="skill", id="skill:s2-governed-active", name="S2 Skill",
        description="S2 governed-active capability（contract 参考，不重写）",
        default_state="disabled",
        enable_env="MY_FIRST_AGENT_S2_SKILL_ENABLE",
        risk=ExtensionRisk("low", "S2 已 governed-active，默认关闭可禁用"),
        verification=ExtensionVerification(
            "S2 targeted gate（skill activation tests opt-in）", ("S3-G11",),
        ),
        evidence=ExtensionEvidenceDescriptor("tool", "skill governed tool report"),
    )
    assert skill.is_default_off()
    # 与 Skill gate 同一 opt-in env（gate.py: S2_SKILL_ENABLE_ENV）
    assert skill.enable_env == "MY_FIRST_AGENT_S2_SKILL_ENABLE"


def test_default_off_evaluation_requires_explicit_opt_in():
    """default-off 语义：无 opt-in → disabled；显式 opt-in → enabled。"""
    cap = ExtensionCapability(
        kind="mcp", id="mcp:x", name="x", description="x",
        default_state="disabled", enable_env="MY_FIRST_AGENT_S3_MCP_ENABLE",
        risk=ExtensionRisk("medium", "x"),
    )
    # 无 env → 不允许
    denied = evaluate_activation(cap, env={})
    assert isinstance(denied, ExtensionActivationDecision)
    assert denied.allowed is False
    assert denied.state == "disabled"
    # 显式 opt-in → 允许
    enabled = evaluate_activation(cap, env={"MY_FIRST_AGENT_S3_MCP_ENABLE": "1"})
    assert enabled.allowed is True
    assert enabled.state == "enabled"


def test_default_off_without_enable_env_stays_disabled():
    """default-off 且无 enable_env → 永远 disabled（无 opt-in 通道）。"""
    cap = ExtensionCapability(
        kind="subagent", id="subagent:y", name="y", description="y",
        default_state="disabled", enable_env=None,
        risk=ExtensionRisk("medium", "y"),
    )
    decision = evaluate_activation(cap, env={"ANY": "1"})
    assert decision.allowed is False
    assert decision.state == "disabled"


def test_capability_is_frozen():
    """契约实例不可变（跨层传递安全，与 SkillDescriptor frozen 一致）。"""
    cap = ExtensionCapability(
        kind="mcp", id="mcp:z", name="z", description="z",
        risk=ExtensionRisk("low", "z"),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        cap.id = "tampered"  # type: ignore[misc]

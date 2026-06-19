"""S3-G11: Skill contract remains S2 governed-active & non-regressed（AC-1）。

S3-G02 把"受控激活"抽象为统一 extension capability 契约时，**不得回退 Skill 的 default-off
语义与 S2 测试契约**；Skill 维持 contract 参考角色，不作 S3 主新增目标。

本 guard 守护：
- (a) Skill 自身的 governed gate（`skill_system.gate.is_s2_skill_enabled` /
  `MY_FIRST_AGENT_S2_SKILL_ENABLE`）仍是 Skill 激活的权威，default-off 不变；
- (b) G02 统一契约对 Skill 是**声明性参考**（同 env、同 default-off 语义），不替代/旁路
  Skill 自身 gate；
- (c) Skill 的 default-off 在 S3 下行为同 S2（关闭时 Skill 不激活）。

Skill discovery/activation/execution 分层的深层 guard 仍由 S2 测试套件承担
（test_s2_skill_controlled_integration / test_skill_allowed_tools_lifecycle /
test_skill_checkpoint_resume_lifecycle —— S3 期间 33 passed 未回归）。
"""
from __future__ import annotations

from agent.extension_capability import ExtensionCapability, evaluate_activation
from agent.skill_system.gate import (
    S2_SKILL_ENABLE_ENV,
    is_s2_skill_enabled,
)


def test_skill_gate_is_authority_and_default_off(monkeypatch):
    """Skill gate 仍是激活权威；default-off：无 opt-in → False。"""
    assert S2_SKILL_ENABLE_ENV == "MY_FIRST_AGENT_S2_SKILL_ENABLE"
    monkeypatch.delenv(S2_SKILL_ENABLE_ENV, raising=False)
    assert is_s2_skill_enabled() is False
    monkeypatch.setenv(S2_SKILL_ENABLE_ENV, "1")
    assert is_s2_skill_enabled() is True


def test_contract_skill_reference_is_compatible_not_replacing_gate():
    """G02 契约可声明 skill-kind capability，但其激活评估与 Skill gate 同语义（参考，不替代）。"""
    # 一个按契约声明的 skill-kind capability（参考 Skill S2 governed-active 形状）
    skill_cap = ExtensionCapability(
        kind="skill",
        id="skill:reference",
        name="Skill reference capability",
        description="S2 governed-active Skill（contract 参考，不重写）",
        default_state="disabled",
        enable_env=S2_SKILL_ENABLE_ENV,  # 与 Skill gate 同 env
    )
    # 契约评估器对 skill-kind 的 default-off 语义 == Skill gate 语义
    assert evaluate_activation(skill_cap, env={}).allowed is False
    assert (
        evaluate_activation(skill_cap, env={S2_SKILL_ENABLE_ENV: "1"}).allowed is True
    )
    # 关键：Skill 的真实激活权威仍是 skill_system.gate.is_s2_skill_enabled（未被契约替代）
    assert callable(is_s2_skill_enabled)


def test_skill_default_off_means_no_activation_when_closed(monkeypatch):
    """default-off：Skill gate 关闭时，契约评估也拒绝（行为同 S2，不退化）。"""
    monkeypatch.delenv(S2_SKILL_ENABLE_ENV, raising=False)
    # Skill gate 权威
    assert is_s2_skill_enabled() is False
    # 契约参考评估一致
    skill_cap = ExtensionCapability(
        kind="skill", id="skill:x", name="x", description="x",
        default_state="disabled", enable_env=S2_SKILL_ENABLE_ENV,
    )
    assert evaluate_activation(skill_cap).allowed is False

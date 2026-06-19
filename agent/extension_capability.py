"""S3 统一 extension capability 契约（AC-4 / S3-G02）。

把 S2 在 Skill 上验证的"受控激活"模式抽象为统一 extension capability 契约，让
MCP / SubAgent（以及作为参考模型的 Skill）以**同一形状**声明五要素：

- **metadata**：kind / id / name / description
- **enable-disable**：default_state（default-off）+ enable_env（显式 opt-in 通道）
- **risk**：等级 + 摘要 + 缓解措施
- **verification**：验证规格 + acceptance 引用
- **evidence**：在 governed path 中产生的 evidence subsystem + 形状

设计原则（对齐 S3_GOAL §4 scope-1/2、AC-4；S3_GOAL_GAP §10 non-goal guardrails）：

- 契约只是**数据形状 + 接入约定**，不是第二条主链路；不重写 runtime spine。
- 以 Skill governed-active（`skill_system/descriptor.py` SkillDescriptor +
  `skill_system/gate.py` default-off env opt-in）为参考模型，**不重写 Skill**。
- 所有字段不可变（frozen dataclass），跨层传递安全。
- default-off 是默认语义；allowlist / policy gate 的具体判定留在各自接入层（G03/G04），
  本模块只提供统一的激活决策评估（显式 opt-in），与 Skill gate 同语义。
- 不做插件市场 / 动态发现生态化（non-goal，留 S4/Sn）。
- Scheduler 不在 EXTENSION_KINDS 内（S3 只保留 boundary，defer S4/Sn）。

真实接入由 S3-G03（MCP governed tool source）/ S3-G04（SubAgent read-only parent-mediated）
落地；本模块只定义契约并证明 MCP/SubAgent/Skill 能按其声明。
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

# ---- 枚举型类型 ----

ExtensionKind = Literal["skill", "mcp", "subagent"]
"""Extension capability 种类。Scheduler 故意不在此列（S3 defer S4/Sn，只保留 boundary）。"""

EXTENSION_KINDS: frozenset[str] = frozenset({"skill", "mcp", "subagent"})
"""capability 种类允许值集合。"""

RiskLevel = Literal["low", "medium", "high"]
"""风险等级——与 SkillDescriptor.risk_level 同集合，保证同一风险口径。"""

RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})
"""风险等级允许值集合（与 skill_system.descriptor.RISK_LEVELS 一致）。"""

ActivationState = Literal["enabled", "disabled"]
"""capability 激活状态。default-off 语义下默认 disabled。"""

# 与 skill_system/gate.py 同一的 opt-in 启用值集合
_ENABLED_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class ExtensionRisk:
    """capability 声明的风险：等级 + 摘要 + 缓解措施。

    level 是**声明值**，不能降低 governance / ToolRegistry 的真实风险判定
    （与 SkillDescriptor.risk_level 语义一致）。
    """

    level: RiskLevel
    summary: str
    mitigations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtensionVerification:
    """如何验证该 capability 受控。

    spec 是验证规格描述；acceptance_refs 指向 gap / acceptance 文档。声明字段——
    真实验证由 acceptance gate / targeted gate 执行（不在本模块）。
    """

    spec: str
    acceptance_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtensionEvidenceDescriptor:
    """该 capability 在 governed path 中产生的 evidence 形状描述。

    subsystem 与 task evidence subsystem（memory/tool/task 等）对齐；shape 描述
    evidence 结构，便于 acceptance 判定 extension evidence 是否对齐。
    """

    subsystem: str
    shape: str


@dataclass(frozen=True)
class ExtensionCapability:
    """统一 extension capability 契约（AC-4）。

    MCP / SubAgent / Skill 以同一形状声明 metadata / enable-disable / risk /
    verification / evidence。default_off = (default_state == "disabled")。
    """

    kind: ExtensionKind
    id: str
    name: str
    description: str
    default_state: ActivationState = "disabled"
    enable_env: str | None = None
    risk: ExtensionRisk | None = None
    verification: ExtensionVerification | None = None
    evidence: ExtensionEvidenceDescriptor | None = None

    def is_default_off(self) -> bool:
        """default-off 语义：默认关闭，需显式 opt-in 才启用。"""
        return self.default_state == "disabled"


@dataclass(frozen=True)
class ExtensionActivationDecision:
    """capability 激活决策（evaluate_activation 的返回值）。"""

    allowed: bool
    state: ActivationState
    reason: str


def evaluate_activation(
    capability: ExtensionCapability,
    env: Mapping[str, str] | None = None,
) -> ExtensionActivationDecision:
    """根据 capability 的 default_state + enable_env 解析激活决策。

    与 Skill gate（`skill_system.gate.is_s2_skill_enabled`）同一语义：

    - default_state == "enabled" → 直接允许（默认开启的 capability）。
    - default-off（disabled）：
        * 无 enable_env → 永远 disabled（无 opt-in 通道）。
        * enable_env 未置启用值 → disabled。
        * enable_env 显式置启用值（1/true/yes/on）→ enabled。

    本函数是纯决策评估；具体 policy/allowlist/evidence 判定在各 capability 接入层
    （G03/G04），不在此旁路。
    """
    source = os.environ if env is None else env
    if capability.default_state == "enabled":
        return ExtensionActivationDecision(
            allowed=True, state="enabled", reason="default-enabled"
        )
    if capability.enable_env is None:
        return ExtensionActivationDecision(
            allowed=False,
            state="disabled",
            reason=f"{capability.kind}:{capability.id} default-off; no opt-in env",
        )
    value = str(source.get(capability.enable_env, "")).strip().lower()
    if value in _ENABLED_VALUES:
        return ExtensionActivationDecision(
            allowed=True, state="enabled", reason=f"opt-in via {capability.enable_env}"
        )
    return ExtensionActivationDecision(
        allowed=False,
        state="disabled",
        reason=f"{capability.enable_env} not enabled",
    )

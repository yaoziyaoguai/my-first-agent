"""S3-G12: extension capability registry / 可观测性 report / health check（可选增强）。

在 S3-G02 统一契约 + S3-G03/S3-G04 接入之上提供**可观测性增强**（非生态化、不改
runtime spine、不阻塞 S3 release）：

- **registry**：聚合 S3 governed-active extension capabilities（MCP + SubAgent）。Skill
  是 S2 governed-active，作为 capability contract **参考**而非 S3 注册项（不模糊 S2/S3
  边界，符合 S3_GOAL §4 scope-3）。
- **report**：把每个 capability 的 AC-4 metadata（kind / id / default-state / risk /
  evidence / verification）投影成可审计条目，便于人工/acceptance 复盘 extension 边界。
- **health check**：校验每个声明 capability 满足 AC-4 治理形状——risk/verification/
  evidence 齐全、default-off + opt-in 通道、id 唯一、default-enabled 必须有 kill switch。

这是观察/审计工具，本身不接入 runtime 主链路（不绕过 same-spine/policy/evidence）。
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.extension_capability import ExtensionCapability
from agent.mcp_capability import MCP_CAPABILITY
from agent.subagent_capability import SUBAGENT_CAPABILITY

# S3 governed-active extension capabilities（必达 = MCP + SubAgent）。
# Skill 维持 S2 governed-active（contract 参考），不在此注册为 S3 extension。
EXTENSION_CAPABILITIES: tuple[ExtensionCapability, ...] = (MCP_CAPABILITY, SUBAGENT_CAPABILITY)


@dataclass(frozen=True, slots=True)
class ExtensionCapabilityReportEntry:
    """单个 extension capability 的可审计 metadata 投影。"""

    kind: str
    id: str
    name: str
    default_state: str
    enable_env: str | None
    risk_level: str
    evidence_subsystem: str
    verification_spec: str


@dataclass(frozen=True, slots=True)
class ExtensionCapabilityReport:
    """所有已声明 extension capability 的聚合 report（S3-G12 可观测性增强）。"""

    capabilities: tuple[ExtensionCapabilityReportEntry, ...]

    @property
    def capability_ids(self) -> tuple[str, ...]:
        return tuple(entry.id for entry in self.capabilities)


def build_extension_capability_report(
    capabilities: tuple[ExtensionCapability, ...] = EXTENSION_CAPABILITIES,
) -> ExtensionCapabilityReport:
    """把声明的 extension capabilities 投影成可审计 report（不改任何 capability 状态）。"""
    entries = tuple(
        ExtensionCapabilityReportEntry(
            kind=cap.kind,
            id=cap.id,
            name=cap.name,
            default_state=cap.default_state,
            enable_env=cap.enable_env,
            risk_level=cap.risk.level if cap.risk else "unspecified",
            evidence_subsystem=cap.evidence.subsystem if cap.evidence else "unspecified",
            verification_spec=cap.verification.spec if cap.verification else "",
        )
        for cap in capabilities
    )
    return ExtensionCapabilityReport(capabilities=entries)


@dataclass(frozen=True, slots=True)
class ExtensionHealthCheckResult:
    """extension capability 治理形状的 health check 结果。"""

    healthy: bool
    issues: tuple[str, ...]


def check_extension_capability_health(
    capabilities: tuple[ExtensionCapability, ...] = EXTENSION_CAPABILITIES,
) -> ExtensionHealthCheckResult:
    """校验每个声明 capability 满足 AC-4 治理形状（S3-G12 hygiene 增强）。

    检查：id 唯一；risk/verification/evidence 齐全；default-off（governed-active 语义）；
    若 default-enabled 则必须有 enable_env 作为 kill switch。返回问题清单（空 = healthy）。
    """
    issues: list[str] = []
    seen_ids: set[str] = set()
    for cap in capabilities:
        if cap.id in seen_ids:
            issues.append(f"duplicate capability id: {cap.id}")
        seen_ids.add(cap.id)
        if cap.risk is None:
            issues.append(f"{cap.kind}:{cap.id} missing risk declaration")
        if cap.verification is None:
            issues.append(f"{cap.kind}:{cap.id} missing verification declaration")
        if cap.evidence is None:
            issues.append(f"{cap.kind}:{cap.id} missing evidence descriptor")
        if cap.default_state == "enabled" and cap.enable_env is None:
            issues.append(
                f"{cap.kind}:{cap.id} default-enabled without opt-in/kill switch env"
            )
    return ExtensionHealthCheckResult(healthy=not issues, issues=tuple(issues))

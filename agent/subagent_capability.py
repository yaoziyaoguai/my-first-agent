"""S3-G04: SubAgent read-only / audit-first / parent-mediated 的 capability 声明
（经 S3-G02 统一契约）。

把 SubAgent 作为**受控 governed-active 的 read-only / audit-first / parent-mediated**
委派（非完整 multi-agent 生态）用统一 extension capability 契约声明，使 SubAgent 与
MCP / Skill 共享同一接入形状（metadata / enable-disable / risk / verification / evidence）。

事实基线（graphify + 代码核验，2026-06-19）：

- parent-mediated 架构已完全建成：`delegate_l1` / `execute_l1` / `execute_local` /
  `build_context_package`（`agent/subagent_system/`）—— child 继承 parent provider、所有
  工具/内存经 `tool_mediator`、不直接持 `MemoryStore`、不 spawn 外部进程；parent
  `adjudicate_result` 做最终决策。
- 不绕过边界：`tool_boundary.py` / `memory_boundary.py` / `skill_boundary.py` 仅做权限检查
  与 metadata snapshot，不执行；context 的 `forbidden_actions` 显式禁止 direct MemoryStore
  写 / real LLM / shell / nested SubAgent。
- audit 可复盘：`SubAgentAuditRecord`（frozen）+ `SubAgentTraceEvent`（sanitized）+
  `ParentAdjudicationResult`。
- default-off gate 原缺失（不像 Skill/MCP）；本模块补 `MY_FIRST_AGENT_S3_SUBAGENT_ENABLE`
  gate，由 `select_execution_mode`（governed-active 模式）消费。

S3 不做完整 multi-agent 生态（可写 / 非 mediated 委派留 S4/Sn）；child 不另起 agent 主链路。
"""
from __future__ import annotations

from agent.extension_capability import (
    ExtensionCapability,
    ExtensionEvidenceDescriptor,
    ExtensionRisk,
    ExtensionVerification,
)
from agent.subagent_system.gate import SUBAGENT_ENABLE_ENV

SUBAGENT_CAPABILITY = ExtensionCapability(
    kind="subagent",
    id="subagent",
    name="SubAgent read-only parent-mediated delegation",
    description=(
        "受控 read-only / audit-first / parent-mediated SubAgent 委派：child 不绕过主 "
        "Agent 执行 tool/provider/memory；委派经 parent policy + audit/evidence；"
        "default-off + 显式 opt-in。"
    ),
    default_state="disabled",
    enable_env=SUBAGENT_ENABLE_ENV,
    risk=ExtensionRisk(
        level="medium",
        summary=(
            "SubAgent 委派把部分推理下放给 child；必须 parent-mediated（child 不直接持 "
            "tool/provider/memory 旁路），read-only / audit-first，且 default-off 可禁用。"
        ),
        mitigations=(
            "default-off + 显式 opt-in（governed-active 模式需 S3 gate）",
            "parent-mediated：工具/内存经 tool_mediator，不直接持 MemoryStore",
            "read-only / audit-first context（forbidden_actions 强制）",
            "SubAgentAuditRecord + trace + ParentAdjudicationResult 可复盘",
            "local 确定性模式不受 gate 影响（fake-first）",
        ),
    ),
    verification=ExtensionVerification(
        spec=(
            "read-only 委派经 parent policy/evidence；child 无法绕过主 Agent 执行 "
            "tool/provider/memory；default-off 可禁用；SubAgentAuditRecord 可复盘"
        ),
        acceptance_refs=(
            "S3-G04",
            "tests/test_s3_subagent_parent_mediated_acceptance.py",
            "S3_REFERENCE_TASK.md §3/§5",
        ),
    ),
    evidence=ExtensionEvidenceDescriptor(
        subsystem="task",
        shape=(
            "SubAgentAuditRecord（frozen）+ sanitized SubAgentTraceEvent + "
            "ParentAdjudicationResult（accept/reject/request_revision/ask_user）；"
            "经 governed dispatcher handler 时叠加 dispatcher evidence"
        ),
    ),
)
"""SubAgent read-only / audit-first / parent-mediated 的统一 capability 声明（AC-3 / AC-4）。"""

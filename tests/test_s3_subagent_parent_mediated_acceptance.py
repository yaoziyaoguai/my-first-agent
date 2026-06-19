"""S3-G04: SubAgent read-only / audit-first / parent-mediated 受控接入验收
（AC-3 / S3_REFERENCE_TASK §3）。

证明 SubAgent 作为**受控 governed-active 的 read-only / audit-first /
parent-mediated** 委派（非完整 multi-agent 生态）：

- (a) SubAgent 经 S3-G02 统一契约声明（`SUBAGENT_CAPABILITY`），default-off + opt-in；
- (b) default-off gate：governed-active 模式（real_llm_readonly 等）在未 opt-in 时被拒，
      local（确定性）模式不受 gate 影响（fake-first，假 E2E 不需 opt-in）；
- (c) child 无法绕过主 Agent：parent-controlled context 显式禁止 direct MemoryStore 写 /
      real LLM / shell / nested SubAgent；
- (d) parent-mediated 委派产出可复盘的 `SubAgentAuditRecord`，由 parent `adjudicate_result`。

L1 child 工具/内存经 `tool_mediator` 的 parent-mediated 行为已由
`tests/runtime_integration/test_subagent_l1_parent_mediated.py`（16 test class）充分证明；
本文件聚焦 S3 的 capability 声明 + default-off gate + 不绕过边界 + audit 可复盘。
"""
from __future__ import annotations

import dataclasses

import pytest

from agent.extension_capability import evaluate_activation
from agent.subagent_system.adjudication import adjudicate_result
from agent.subagent_system.context import build_context_package
from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.errors import SubAgentModeError
from agent.subagent_system.execution_mode import SubAgentExecutionMode
from agent.subagent_system.executor import execute_local
from agent.subagent_system.gate import SUBAGENT_ENABLE_ENV, is_subagent_enabled
from agent.subagent_system.policy import SubAgentPolicy, select_execution_mode
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.result import ParentAdjudicationResult, SubAgentAuditRecord


def _auditor_request() -> SubAgentRequest:
    return SubAgentRequest(
        task="Audit whether fixture gap FIXTURE-GAP-1 evidence satisfies AC",
        role="auditor",
        allowed_tools=("read_file",),
        execution_mode="local_fake",
        parent_trace_id="s3-g04-trace",
        delegation_reason="second opinion",
        max_iterations=3,
    )


def _auditor_descriptor() -> SubAgentDescriptor:
    return SubAgentDescriptor(
        name="repo_gap_auditor",
        description="Read-only / audit-first gap auditor",
        role="auditor",
        supported_modes=("local_fake", "real_llm_readonly"),
    )


# ---- (a) capability 声明 ----


def test_subagent_capability_declared_via_unified_contract():
    """SubAgent 经 S3-G02 统一契约声明，五要素齐全 + default-off。"""
    from agent.subagent_capability import SUBAGENT_CAPABILITY

    assert SUBAGENT_CAPABILITY.kind == "subagent"
    assert SUBAGENT_CAPABILITY.is_default_off() is True
    assert SUBAGENT_CAPABILITY.enable_env == SUBAGENT_ENABLE_ENV == (
        "MY_FIRST_AGENT_S3_SUBAGENT_ENABLE"
    )
    assert SUBAGENT_CAPABILITY.risk is not None
    assert SUBAGENT_CAPABILITY.verification is not None and SUBAGENT_CAPABILITY.verification.spec
    assert SUBAGENT_CAPABILITY.evidence is not None
    # default-off：契约 gate 无 opt-in → 不允许激活
    assert evaluate_activation(SUBAGENT_CAPABILITY, env={}).allowed is False


# ---- (b) default-off gate ----


def test_default_off_gate_blocks_governed_active_modes(monkeypatch):
    """governed-active（real_llm_readonly）模式需要 S3 opt-in；未 opt-in → 被拒。"""
    monkeypatch.delenv(SUBAGENT_ENABLE_ENV, raising=False)
    policy = SubAgentPolicy(real_llm_readonly_allowed=True)  # config gate 打开
    descriptor = _auditor_descriptor()
    request = SubAgentRequest(
        task="Audit", role="auditor", allowed_tools=("read_file",),
        execution_mode="real_llm_readonly", parent_trace_id="t",
        delegation_reason="review", max_iterations=3,
    )
    # config 打开但 S3 gate 关闭（default-off）→ 仍被拒
    assert is_subagent_enabled() is False
    with pytest.raises(SubAgentModeError):
        select_execution_mode(request, descriptor, policy)
    # opt-in 后 → 放行
    monkeypatch.setenv(SUBAGENT_ENABLE_ENV, "1")
    assert is_subagent_enabled() is True
    assert (
        select_execution_mode(request, descriptor, policy)
        == SubAgentExecutionMode.REAL_LLM_READONLY
    )


def test_local_modes_not_gated_fake_first(monkeypatch):
    """local（确定性）模式不受 S3 gate 影响（fake-first，假 E2E 不需 opt-in）。"""
    monkeypatch.delenv(SUBAGENT_ENABLE_ENV, raising=False)
    request = _auditor_request()  # execution_mode=local_fake
    mode = select_execution_mode(request, _auditor_descriptor(), SubAgentPolicy())
    assert mode == SubAgentExecutionMode.LOCAL_FAKE


# ---- (c) child 无法绕过主 Agent ----


def test_child_cannot_bypass_parent_for_tool_provider_memory():
    """parent-controlled context 显式禁止绕过主 Agent 的 tool/provider/memory 路径。"""
    ctx = build_context_package(
        request=_auditor_request(),
        descriptor=_auditor_descriptor(),
        tool_snapshots=(),
    )
    forbidden = set(ctx.forbidden_actions)
    # child 不直接写 MemoryStore、不跑 real LLM、不 shell、不 nested SubAgent
    assert "no direct MemoryStore write" in forbidden
    assert "no real LLM" in forbidden
    assert "no shell" in forbidden
    assert "no nested SubAgent" in forbidden
    # constraints 声明 parent owns orchestration / ToolRegistry / Memory governance 是权威
    assert "parent owns orchestration" in set(ctx.constraints)


# ---- (d) parent-mediated 委派产出可复盘 audit + parent adjudicate ----


def test_parent_mediated_delegation_produces_replayable_audit():
    """execute_local（确定性 read-only）产出 SubAgentAuditRecord，可序列化复盘。"""
    ctx = build_context_package(
        request=_auditor_request(), descriptor=_auditor_descriptor(), tool_snapshots=()
    )
    result = execute_local(ctx, delegation_id="s3-g04-d1")
    audit = result.audit
    assert isinstance(audit, SubAgentAuditRecord)
    assert audit.subagent_name == "repo_gap_auditor"
    assert audit.execution_mode == "local_fake"
    # handoff：parent 必须 adjudicate（child 不自行最终决策）
    assert "adjudicat" in result.handoff_back.lower()
    # 可复盘：frozen + asdict round-trip 不变
    assert dataclasses.is_dataclass(audit)
    snapshot = dataclasses.asdict(audit)
    restored = SubAgentAuditRecord(**snapshot)
    assert restored == audit
    # 不变量：已执行工具 ⊆ 请求工具；iterations 不超上限
    assert set(audit.tools_executed).issubset(set(audit.tools_requested))
    assert audit.iterations_used <= audit.max_iterations


def test_parent_adjudicates_subagent_result():
    """parent 经 adjudicate_result 决策（accept/ask_user/reject），不执行工具/不写 memory。"""
    ctx = build_context_package(
        request=_auditor_request(), descriptor=_auditor_descriptor(), tool_snapshots=()
    )
    result = execute_local(ctx, delegation_id="s3-g04-d2")
    decision = adjudicate_result(result, _auditor_request(), revision_count=0)
    assert isinstance(decision, ParentAdjudicationResult)
    # ok + 高置信 → accept
    assert decision.action == "accept_result"
    # ParentAdjudicationResult 是纯决策（不执行工具/不写 memory）
    assert decision.tool_calls_to_execute == ()
    assert decision.memory_proposals_to_route == ()

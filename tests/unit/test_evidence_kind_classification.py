"""Evidence Kind Classification 单元测试。

中文学习说明：
  验证 classify_action_evidence_kind 正确区分 business（用户可见业务动作）
  和 probe（每 turn 无条件运行的生命周期检查）。
"""

from __future__ import annotations

import pytest

from agent.runtime_integration.schema import (
    RuntimeActionType,
    classify_action_evidence_kind,
)

# ── Business 类型 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("action_type", [
    RuntimeActionType.TOOL_REQUEST,
    RuntimeActionType.TOOL_INVOKE,
    RuntimeActionType.TOOL_RESULT,
    RuntimeActionType.MEMORY_PROPOSE,
    RuntimeActionType.MEMORY_FORGET,
    RuntimeActionType.STREAMING_PROVIDER_CALL,
    RuntimeActionType.STREAMING_EVENT,
    RuntimeActionType.CLI_SHOW_MEMORIES,
    RuntimeActionType.CLI_SHOW_SUBAGENTS,
])
def test_business_action_types(action_type: RuntimeActionType):
    """用户可见业务动作应分类为 business。"""
    assert classify_action_evidence_kind(action_type) == "business"


# ── Probe 类型 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("action_type", [
    RuntimeActionType.SKILL_SELECT,
    RuntimeActionType.TOOL_GATE,
    RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
    RuntimeActionType.MEMORY_RECALL,
    RuntimeActionType.MEMORY_CONSOLIDATE,
    RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
    RuntimeActionType.SUBAGENT_DELEGATE_L0,  # 每 turn routing check，默认 probe
])
def test_probe_action_types(action_type: RuntimeActionType):
    """生命周期检查应分类为 probe。"""
    assert classify_action_evidence_kind(action_type) == "probe"


# ── 边界 ───────────────────────────────────────────────────────────────────────


def test_unknown_action_type_defaults_to_probe():
    """未知 action type 默认 probe（fail-closed）。"""
    assert classify_action_evidence_kind("unknown.fake") == "probe"


def test_string_action_type_matches_by_value():
    """字符串形式的 action type 应通过 value 匹配。"""
    assert classify_action_evidence_kind("tool.invoke") == "business"
    assert classify_action_evidence_kind("tool.gate") == "probe"


def test_all_defined_types_have_classification():
    """每个 RuntimeActionType 都应有明确的 evidence kind 分类。"""
    unclassified = []
    for at in RuntimeActionType:
        kind = classify_action_evidence_kind(at)
        if kind not in ("business", "probe"):
            unclassified.append((at, kind))
    assert not unclassified, f"Unclassified action types: {unclassified}"


def test_business_and_probe_are_mutually_exclusive():
    """同一个 action type 不应同时为 business 和 probe。"""
    business_types = {
        RuntimeActionType.TOOL_REQUEST,
        RuntimeActionType.TOOL_INVOKE,
        RuntimeActionType.TOOL_RESULT,
        RuntimeActionType.MEMORY_PROPOSE,
        RuntimeActionType.MEMORY_FORGET,
        RuntimeActionType.STREAMING_PROVIDER_CALL,
        RuntimeActionType.STREAMING_EVENT,
        RuntimeActionType.CLI_SHOW_MEMORIES,
        RuntimeActionType.CLI_SHOW_SUBAGENTS,
        RuntimeActionType.SUBAGENT_DELEGATE_L1,
        RuntimeActionType.SUBAGENT_DELEGATE_V0,
        RuntimeActionType.SUBAGENT_CHILD_TOOL_REQUEST,
        RuntimeActionType.SUBAGENT_CHILD_RESULT,
        RuntimeActionType.SUBAGENT_PARENT_ADJUDICATION,
        RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
        # Loop 3.4: scheduler evidence — runtime-owned action graph 决策
        RuntimeActionType.ACTION_PLAN_START,
        RuntimeActionType.NODE_ENTER,
        RuntimeActionType.NODE_EXIT,
        RuntimeActionType.NODE_FAILURE,
        RuntimeActionType.ACTION_PLAN_COMPLETE,
        # Next-stage D-01: SubAgent L2 native loop action types
        RuntimeActionType.SUBAGENT_DELEGATE_L2,
        RuntimeActionType.SUBAGENT_CHILD_BATCH_MEMORY,
    }
    probe_types = {
        RuntimeActionType.SKILL_SELECT,
        RuntimeActionType.TOOL_GATE,
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        RuntimeActionType.MEMORY_RECALL,
        RuntimeActionType.MEMORY_CONSOLIDATE,
        RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
        RuntimeActionType.CHECKPOINT_SAVE,
        RuntimeActionType.CHECKPOINT_RESUME,
        RuntimeActionType.MCP_BRIDGE_LIFECYCLE,
        RuntimeActionType.SUBAGENT_DELEGATE_L0,  # 每 turn routing check, 默认 probe
        # Phase 3: turn-start skill selection — per-turn lifecycle probe
        RuntimeActionType.SKILL_SELECTION_ENTERED,
        RuntimeActionType.SKILL_CANDIDATES_BUILT,
    }
    assert business_types.isdisjoint(probe_types), \
        f"Overlap between business and probe: {business_types & probe_types}"
    all_types = set(RuntimeActionType)
    covered = business_types | probe_types
    assert covered == all_types, f"Missing classification: {all_types - covered}"

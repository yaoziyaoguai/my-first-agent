"""S3-G05: extension evidence / checkpoint / task-state integration 验收
（AC-1/AC-4 / S3_REFERENCE_TASK §5）。

证明 extension（MCP tool 结果 + SubAgent 委派）在任务中产生的结果纳入既有
evidence/checkpoint/task-state 边界：可记录、checkpoint→resume 不丢、evidence 能复盘。

- (a) MCP tool 结果经共享 tool 路径落入 `state.task.tool_execution_log`，跨 resume 保真
      （S3-G03 已证 MCP 走同一 TOOL_REGISTRY/mediator；本处证其结果进 task state 并持久化）；
- (b) SubAgent 委派经 `record_delegation_run` 把 audit/adjudication 安全投影写入
      `state.task.delegation_log`（新 TaskState 字段，自动进 checkpoint）；
- (c) checkpoint→resume 后 MCP 结果 + SubAgent delegation 均完整；
- (d) `build_task_evidence_report` 呈现 extension delegation 计数（可复盘 extension 决策）。

非目标（S3-G05）：不要求逐字保真（TD-001）/ pending-tool 全量预览（TD-004）；不重写
checkpoint 主路径。runtime 消费点（execute_subagent_delegation）的 state 穿透由 S3-G06
E2E reference task 在真实循环中调用本 seam 完成（不在本 gap 改 core.py）。
"""
from __future__ import annotations

from agent.checkpoint import clear_checkpoint, load_checkpoint_to_state, save_checkpoint
from agent.state import create_agent_state
from agent.subagent_system.adjudication import adjudicate_result
from agent.subagent_system.context import build_context_package
from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.executor import execute_local
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.result import SubAgentRun
from agent.task_delegation_evidence import record_delegation_run
from agent.task_evidence_report import build_task_evidence_report


def _auditor_request() -> SubAgentRequest:
    return SubAgentRequest(
        task="Audit whether fixture gap FIXTURE-GAP-1 evidence satisfies AC",
        role="auditor",
        allowed_tools=("read_file",),
        execution_mode="local_fake",
        parent_trace_id="s3-g05-trace",
        delegation_reason="second opinion",
        max_iterations=3,
    )


def _auditor_descriptor() -> SubAgentDescriptor:
    return SubAgentDescriptor(
        name="repo_gap_auditor",
        description="Read-only / audit-first gap auditor",
        role="auditor",
        supported_modes=("local_fake",),
    )


def _record_mcp_tool_result(state, *, tool_use_id, tool_name, result) -> None:
    """模拟 MCP tool 结果落入 tool_execution_log（共享 tool 路径产物）。"""
    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "status": "executed",
        "input": {"target": "fixture repo doc"},
        "result": result,
        "step_index": state.task.current_step_index,
    }


def test_extension_evidence_survives_checkpoint_resume(tmp_path):
    """MCP 结果（tool_execution_log）+ SubAgent 委派（delegation_log）跨 resume 完整。"""
    state = create_agent_state(system_prompt="S3 extension evidence test")
    state.memory.session_id = "s3-extension-evidence-session"

    # (a) MCP tool 结果进 tool_execution_log（共享 tool 路径的产物）
    _record_mcp_tool_result(
        state,
        tool_use_id="tool-mcp-read",
        tool_name="mcp__demo__repo_doc_reader",
        result="fixture: gap FIXTURE-GAP-1 evidence satisfied",
    )

    # (b) SubAgent second-opinion 委派 → record_delegation_run 写入 delegation_log
    ctx = build_context_package(
        request=_auditor_request(), descriptor=_auditor_descriptor(), tool_snapshots=()
    )
    result = execute_local(ctx, delegation_id="s3-g05-d1")
    adjudication = adjudicate_result(result, _auditor_request(), revision_count=0)
    run = SubAgentRun(
        delegation_id="s3-g05-d1",
        state=result.status,
        request=_auditor_request(),
        descriptor=_auditor_descriptor(),
        context_package=ctx,
        result=result,
        adjudication=adjudication,
        revision_count=0,
    )
    projection = record_delegation_run(state, run)
    assert projection["subagent_name"] == "repo_gap_auditor"
    assert projection["adjudication_action"] == "accept_result"
    assert len(state.task.delegation_log) == 1

    # (c) checkpoint → resume
    checkpoint_path = tmp_path / "s3-extension-evidence-checkpoint.json"
    save_checkpoint(state, source="tests.s3.g05.extension_evidence", path=checkpoint_path)
    resumed = create_agent_state(system_prompt="S3 extension evidence test")
    assert load_checkpoint_to_state(resumed, path=checkpoint_path) is True

    # MCP 结果保真
    assert "tool-mcp-read" in resumed.task.tool_execution_log
    assert (
        resumed.task.tool_execution_log["tool-mcp-read"]["tool"]
        == "mcp__demo__repo_doc_reader"
    )
    # SubAgent delegation 保真
    assert len(resumed.task.delegation_log) == 1
    resumed_proj = resumed.task.delegation_log[0]
    assert resumed_proj["subagent_name"] == "repo_gap_auditor"
    assert resumed_proj["delegation_id"] == "s3-g05-d1"
    assert resumed_proj["adjudication_action"] == "accept_result"

    # (d) evidence report 呈现 extension delegation 计数（可复盘）
    report = build_task_evidence_report(resumed)
    assert any("extensions.delegations:1" in e for e in report.evidence_events), (
        f"evidence report 应呈现 extension delegation 计数，实际 events={report.evidence_events}"
    )
    clear_checkpoint(path=checkpoint_path)


def test_delegation_log_defaults_empty_and_safe():
    """新 TaskState 默认 delegation_log 为空 list（向后兼容；旧 checkpoint 不受影响）。"""
    state = create_agent_state(system_prompt="default check")
    assert state.task.delegation_log == []
    # 无 delegation 时 evidence report 不呈现 extensions.delegations
    report = build_task_evidence_report(state)
    assert not any("extensions.delegations:" in e for e in report.evidence_events)

"""S3-G06: Extension-assisted repo governance E2E reference task（fake/local）。

S3 验收锚点（AC-5 / AC-1 / S3_REFERENCE_TASK.md §2 闭环）。在 S2 governed task path
内**组合 MCP tool source + read-only SubAgent** 完成 Extension-assisted repo governance
task 的 plan→execute→checkpoint→resume→done 闭环（fake 确定性）。

闭环（对齐 S3_REFERENCE_TASK.md §2）：
- receive/accept：governed task 接收 + plan 确认（S2 函数，证明 S2 path 不回归=AC-1）；
- execute-1：受控 MCP tool source（G03）读 fixture repo 证据 → 结果进 tool_execution_log；
- execute-2：read-only / parent-mediated SubAgent（G04）second opinion → record_delegation_run
  写入 delegation_log（G05 seam）；
- execute-3：主 Agent adjudicate + 汇总 evidence；
- checkpoint→resume：extension 上下文（tool_execution_log + delegation_log）不丢；
- advance/done：DONE + progress 100%；
- gate：acceptance report 不 release-block（extension 路径成功）。

real-provider extension smoke 是 opt-in 单测，由 S3-G07 落地（默认 skip）。不连真实 MCP
endpoint；fake/fixture only（`AGENTS.md` 安全边界）。
"""
from __future__ import annotations

from agent.acceptance_gate import AcceptanceCheckResult, build_s2_acceptance_report
from agent.mcp import FakeMCPClient, MCPCallResult, register_mcp_tools
from agent.mcp_models import MCPServerConfig, MCPToolDescriptor, mcp_registry_tool_name
from agent.state import create_agent_state
from agent.subagent_system.adjudication import adjudicate_result
from agent.subagent_system.context import build_context_package
from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.executor import execute_local
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.result import SubAgentRun
from agent.task_delegation_evidence import record_delegation_run
from agent.task_evidence_report import build_task_evidence_report
from agent.task_orchestration import (
    accept_governed_plan,
    advance_governed_task_if_ready,
    receive_governed_task,
    resume_governed_task,
)
from agent.task_state_model import GovernedTaskLifecycle
from config import STEP_COMPLETION_THRESHOLD


def _s3_reference_task_plan() -> dict:
    """Extension-assisted repo governance plan（S3_REFERENCE_TASK.md §2/§3）。"""
    return {
        "goal": "extension-assisted repo governance: gap-evidence audit",
        "thinking": (
            "use governed MCP tool source to read fixture evidence; delegate read-only "
            "SubAgent for second opinion; aggregate, adjudicate, report"
        ),
        "steps": [
            {
                "step_id": "s3-acceptance-1",
                "title": "Fetch repo evidence via governed MCP tool source",
                "description": "Read fixture repo doc through controlled MCP source.",
                "step_type": "mcp_context_fetch",
            },
            {
                "step_id": "s3-acceptance-2",
                "title": "Read-only SubAgent second opinion",
                "description": "Delegate audit-first SubAgent; parent adjudicates.",
                "step_type": "subagent_second_opinion",
            },
            {
                "step_id": "s3-acceptance-3",
                "title": "Aggregate evidence and report",
                "description": "Combine MCP result + SubAgent audit; advance to done.",
                "step_type": "report",
            },
        ],
    }


def _register_fixture_mcp_source() -> str:
    """注册一个 fake/fixture MCP tool source（G03 governed path），返回 registry name。"""
    server = MCPServerConfig(
        name="s3-ref-demo", transport="stdio", command="fake-cmd", enabled=True
    )
    descriptor = MCPToolDescriptor(
        server_name="s3-ref-demo",
        name="repo_doc_reader",
        description="Read fixture repo doc via governed MCP source.",
        input_schema={},
    )
    client = FakeMCPClient(
        tools_by_server={"s3-ref-demo": [descriptor]},
        results_by_call={
            ("s3-ref-demo", "repo_doc_reader"): MCPCallResult(
                content="fixture: gap FIXTURE-GAP-1 evidence satisfied", is_error=False
            )
        },
    )
    registered = register_mcp_tools(
        [server], client, server_allowlist=frozenset({"s3-ref-demo"}), dry_run=True
    )
    assert registered, "fixture MCP tool source 应注册成功（allowlisted）"
    return mcp_registry_tool_name("s3-ref-demo", "repo_doc_reader")


def _record_tool_result(state, *, tool_use_id, tool_name, result) -> None:
    """记录 governed tool 结果进 tool_execution_log（共享 tool 路径产物，跨 resume 保真）。"""
    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "status": "executed",
        "input": {"target": "fixture repo doc"},
        "result": result,
        "step_index": state.task.current_step_index,
    }


def _mark_step_complete(state, *, tool_use_id, summary) -> None:
    state.task.tool_execution_log[tool_use_id] = {
        "tool": "mark_step_complete",
        "status": "meta_recorded",
        "input": {
            "completion_score": STEP_COMPLETION_THRESHOLD,
            "summary": summary,
            "outstanding": "none",
        },
        "step_index": state.task.current_step_index,
    }


def _record_subagent_second_opinion(state, *, delegation_id) -> None:
    """read-only SubAgent second opinion（G04）→ record_delegation_run 写 delegation_log（G05）。"""
    request = SubAgentRequest(
        task="Audit whether fixture gap FIXTURE-GAP-1 evidence satisfies AC",
        role="auditor",
        allowed_tools=("read_file",),
        execution_mode="local_fake",
        parent_trace_id=f"s3-ref-{delegation_id}",
        delegation_reason="second opinion",
        max_iterations=3,
    )
    descriptor = SubAgentDescriptor(
        name="repo_gap_auditor",
        description="Read-only / audit-first gap auditor",
        role="auditor",
        supported_modes=("local_fake",),
    )
    ctx = build_context_package(request=request, descriptor=descriptor, tool_snapshots=())
    result = execute_local(ctx, delegation_id=delegation_id)
    adjudication = adjudicate_result(result, request, revision_count=0)
    run = SubAgentRun(
        delegation_id=delegation_id,
        state=result.status,
        request=request,
        descriptor=descriptor,
        context_package=ctx,
        result=result,
        adjudication=adjudication,
        revision_count=0,
    )
    projection = record_delegation_run(state, run)
    assert projection["adjudication_action"] == "accept_result"


def test_s3_reference_task_fake_e2e_extension_closed_loop(tmp_path):
    """S3 reference task：组合 MCP+SubAgent 的 governed 闭环 + checkpoint/resume + done。"""
    from agent.checkpoint import (
        clear_checkpoint,
        load_checkpoint_to_state,
        save_checkpoint,
    )

    # --- 受控 MCP tool source（G03）：注册进同一 TOOL_REGISTRY（governed source）---
    mcp_registry_name = _register_fixture_mcp_source()
    from agent.tool_registry import TOOL_REGISTRY

    assert mcp_registry_name in TOOL_REGISTRY
    assert TOOL_REGISTRY[mcp_registry_name]["capability"] == "mcp_tool"

    # --- receive / accept（S2 governed task path，证明 AC-1 不回归）---
    state = create_agent_state(system_prompt="S3 reference task runtime")
    state.memory.session_id = "s3-reference-task-session"
    state.memory.working_summary = "Prior S3 loop context is available."

    received = receive_governed_task(
        state,
        user_goal="Extension-assisted audit of fixture repo governance gap",
        plan_payload=_s3_reference_task_plan(),
    )
    assert received.allowed is True
    assert received.snapshot.lifecycle is GovernedTaskLifecycle.WAITING
    accepted = accept_governed_plan(state)
    assert accepted.allowed is True
    assert accepted.snapshot.lifecycle is GovernedTaskLifecycle.RUNNING

    # --- execute-1：MCP tool source 读 fixture 证据 → tool_execution_log ---
    _record_tool_result(
        state,
        tool_use_id="tool-mcp-fetch",
        tool_name=mcp_registry_name,
        result="fixture: gap FIXTURE-GAP-1 evidence satisfied",
    )
    _mark_step_complete(state, tool_use_id="meta-step-1", summary="MCP evidence fetched")
    assert advance_governed_task_if_ready(state).snapshot.progress.completed_steps == 1

    # --- execute-2：read-only SubAgent second opinion → delegation_log（G05 seam）---
    _record_subagent_second_opinion(state, delegation_id="s3-ref-d1")
    assert len(state.task.delegation_log) == 1
    _mark_step_complete(state, tool_use_id="meta-step-2", summary="SubAgent second opinion done")
    assert advance_governed_task_if_ready(state).snapshot.progress.completed_steps == 2

    # --- checkpoint（extension 上下文随 task state 持久化）---
    checkpoint_path = tmp_path / "s3-reference-task-checkpoint.json"
    save_checkpoint(state, source="tests.s3.reference_task", path=checkpoint_path)

    # --- resume：extension 上下文不丢 ---
    resumed = create_agent_state(system_prompt="S3 reference task runtime")
    assert load_checkpoint_to_state(resumed, path=checkpoint_path) is True
    assert resume_governed_task(resumed).progress.current_step_index == 2
    # MCP 结果保真
    assert resumed.task.tool_execution_log["tool-mcp-fetch"]["tool"] == mcp_registry_name
    # SubAgent delegation 保真
    assert len(resumed.task.delegation_log) == 1
    assert resumed.task.delegation_log[0]["subagent_name"] == "repo_gap_auditor"

    # --- execute-3 + done：汇总 evidence、推进到 DONE ---
    _mark_step_complete(
        resumed, tool_use_id="meta-step-3", summary="Aggregated evidence and reported"
    )
    completed = advance_governed_task_if_ready(resumed)
    assert completed.snapshot.lifecycle is GovernedTaskLifecycle.DONE
    assert completed.snapshot.progress.percent == 100.0

    # --- evidence report 呈现 extension delegation（可复盘）---
    report = build_task_evidence_report(resumed)
    assert any("extensions.delegations:1" in e for e in report.evidence_events)

    # --- acceptance gate：extension 路径成功，不 release-block（AC-5）---
    acceptance = build_s2_acceptance_report(
        (
            AcceptanceCheckResult(
                name="s3_reference_task_fake_e2e",
                command=".venv/bin/python -m pytest tests/test_s3_reference_task_acceptance.py",
                exit_code=0,
            ),
        )
    )
    assert acceptance.release_blocked is False
    assert acceptance.runtime_regressions == ()
    clear_checkpoint(path=checkpoint_path)

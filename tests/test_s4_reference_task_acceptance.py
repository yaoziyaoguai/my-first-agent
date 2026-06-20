"""S4-G06: audit/replay reference task E2E（fake/local）。

S4 验收锚点（AC-2 / AC-3 / AC-5 / AC-6-fake / AC-1）。在 S2 governed task path 内组合
MCP tool source + read-only SubAgent 委派，完成 **「执行 → 记录 → 复放 → 校验」** 闭环
（fake 确定性）。这是 S4 相对 S3 的新增闭环——S3 只到「记录」，S4 追加 replay + verify。

闭环（对齐 S4_FIDELITY_CONTRACT.md §6）：
- receive/accept/execute(MCP+SubAgent)/advance/done：governed path 不回归（AC-1）；
- record：build_task_evidence_report 反映 replay chain 可用（安全 count，G02；chain 本身是
  独立 build_replay_chain 投影，不嵌入 safe-summary report——G10 审计修正）；
- replay：build_replay_chain 重建 MCP tool + SubAgent 委派链路（AC-2，超出标签级）；
- verify：verify_evidence 通过（AC-5）；注入 fake secret 在 chain 中被 redacted（AC-3）。

real-provider audit smoke 是 opt-in 单测，由 S4-G07 落地（默认 skip）。不连真实 MCP
endpoint；fake/fixture only（`AGENTS.md` 安全边界）。
"""
from __future__ import annotations

import os

import pytest

from agent.acceptance_gate import AcceptanceCheckResult, build_s2_acceptance_report
from agent.evidence_verifier import verify_evidence
from agent.mcp import FakeMCPClient, MCPCallResult, register_mcp_tools
from agent.mcp_models import MCPServerConfig, MCPToolDescriptor, mcp_registry_tool_name
from agent.state import create_agent_state
from agent.subagent_system.adjudication import adjudicate_result
from agent.subagent_system.context import build_context_package
from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.executor import execute_local
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.result import SubAgentRun
from agent.task_context import build_task_execution_context
from agent.task_delegation_evidence import record_delegation_run
from agent.task_evidence_report import build_task_evidence_report
from agent.task_orchestration import (
    accept_governed_plan,
    advance_governed_task_if_ready,
    receive_governed_task,
)
from agent.task_replay_chain import build_replay_chain
from agent.task_state_model import GovernedTaskLifecycle
from config import STEP_COMPLETION_THRESHOLD

# 注入到 MCP tool 结果中的 fake secret（绝不来自真实凭证；用于 AC-3 redaction 断言）。
_FAKE_SECRET_IN_RESULT = "sk-test-secret-AAAAAAAAAAAAAAAA"


def _s4_reference_task_plan() -> dict:
    """audit/replay reference task plan（S4_FIDELITY_CONTRACT.md §6）。"""
    return {
        "goal": "audit/replay reference task: gap-evidence audit + faithful replay",
        "thinking": (
            "use governed MCP tool source to read fixture evidence; delegate read-only "
            "SubAgent for second opinion; record, replay, verify"
        ),
        "steps": [
            {
                "step_id": "s4-acceptance-1",
                "title": "Fetch repo evidence via governed MCP tool source",
                "description": "Read fixture repo doc through controlled MCP source.",
                "step_type": "mcp_context_fetch",
            },
            {
                "step_id": "s4-acceptance-2",
                "title": "Read-only SubAgent second opinion",
                "description": "Delegate audit-first SubAgent; parent adjudicates.",
                "step_type": "subagent_second_opinion",
            },
            {
                "step_id": "s4-acceptance-3",
                "title": "Record, replay, verify evidence",
                "description": "Project replay chain; verify; confirm redaction.",
                "step_type": "report",
            },
        ],
    }


def _register_fixture_mcp_source() -> str:
    """注册 fake/fixture MCP tool source（governed path），返回 registry name。"""
    server = MCPServerConfig(
        name="s4-ref-demo", transport="stdio", command="fake-cmd", enabled=True
    )
    descriptor = MCPToolDescriptor(
        server_name="s4-ref-demo",
        name="repo_doc_reader",
        description="Read fixture repo doc via governed MCP source.",
        input_schema={},
    )
    client = FakeMCPClient(
        tools_by_server={"s4-ref-demo": [descriptor]},
        results_by_call={
            ("s4-ref-demo", "repo_doc_reader"): MCPCallResult(
                content="fixture: gap FIXTURE-GAP-1 evidence satisfied", is_error=False
            )
        },
    )
    registered = register_mcp_tools(
        [server], client, server_allowlist=frozenset({"s4-ref-demo"}), dry_run=True
    )
    assert registered, "fixture MCP tool source 应注册成功（allowlisted）"
    return mcp_registry_tool_name("s4-ref-demo", "repo_doc_reader")


def _record_mcp_result(state, *, tool_use_id, tool_name, result) -> None:
    """记录 governed MCP tool 结果进 tool_execution_log（含 fake secret，测 AC-3 redaction）。"""
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
    """read-only SubAgent second opinion → record_delegation_run 写 delegation_log。"""
    request = SubAgentRequest(
        task="Audit whether fixture gap FIXTURE-GAP-1 evidence satisfies AC",
        role="auditor",
        allowed_tools=("read_file",),
        execution_mode="local_fake",
        parent_trace_id=f"s4-ref-{delegation_id}",
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


@pytest.fixture
def clean_tool_registry():
    """快照全局 TOOL_REGISTRY，测试后清掉本测试注册的 MCP 工具（避免污染其他测试）。"""
    from agent.tool_registry import TOOL_REGISTRY

    snapshot = set(TOOL_REGISTRY.keys())
    yield
    for added in set(TOOL_REGISTRY.keys()) - snapshot:
        TOOL_REGISTRY.pop(added, None)


def test_s4_reference_task_audit_replay_closed_loop(clean_tool_registry):
    """S4 reference task：execute→record→replay→verify 闭环（fake/local，AC-2/3/5/6-fake）。"""
    # --- 受控 MCP tool source 注册（governed path）---
    mcp_registry_name = _register_fixture_mcp_source()
    from agent.tool_registry import TOOL_REGISTRY

    assert mcp_registry_name in TOOL_REGISTRY

    # --- receive / accept（S2 governed task path，证明 AC-1 不回归）---
    state = create_agent_state(system_prompt="S4 audit/replay reference task runtime")
    state.memory.session_id = "s4-reference-task-session"
    received = receive_governed_task(
        state,
        user_goal="Audit/replay of fixture repo governance gap",
        plan_payload=_s4_reference_task_plan(),
    )
    assert received.allowed is True
    assert accept_governed_plan(state).allowed is True

    # --- execute-1：MCP tool 读 fixture 证据（结果含 fake secret，测 AC-3）---
    _record_mcp_result(
        state,
        tool_use_id="tool-s4-mcp-fetch",
        tool_name=mcp_registry_name,
        result=(
            "fixture: gap FIXTURE-GAP-1 evidence satisfied; "
            f"token={_FAKE_SECRET_IN_RESULT}"
        ),
    )
    _mark_step_complete(state, tool_use_id="meta-s4-step-1", summary="MCP evidence fetched")
    assert advance_governed_task_if_ready(state).snapshot.progress.completed_steps == 1

    # --- execute-2：read-only SubAgent second opinion → delegation_log ---
    _record_subagent_second_opinion(state, delegation_id="s4-ref-d1")
    assert len(state.task.delegation_log) == 1
    _mark_step_complete(state, tool_use_id="meta-s4-step-2", summary="SubAgent second opinion done")
    assert advance_governed_task_if_ready(state).snapshot.progress.completed_steps == 2

    # --- execute-3 + done ---
    _mark_step_complete(
        state, tool_use_id="meta-s4-step-3", summary="Replayed and verified evidence"
    )
    completed = advance_governed_task_if_ready(state)
    assert completed.snapshot.lifecycle is GovernedTaskLifecycle.DONE
    assert completed.snapshot.progress.percent == 100.0

    # ─── record：build_task_evidence_report 反映 replay chain 可用（安全 count，G02）───
    # replay chain 是独立投影（build_replay_chain），不嵌入 safe-summary report；
    # report 只带安全 count，str(report) 不泄露 raw content（守 S2 契约）。
    report = build_task_evidence_report(state)
    assert report.replay_chain_event_count > 0, "evidence report 必须反映 replay chain 可用"

    # ─── replay：build_replay_chain 重建 MCP tool + SubAgent 委派链路（AC-2）───
    chain = build_replay_chain(state)
    tool_events = chain.tool_events
    delegation_events = chain.delegation_events
    # MCP tool 在链路中可重建
    mcp_evt = next(e for e in tool_events if e.ref_id == "tool-s4-mcp-fetch")
    assert mcp_evt.name == mcp_registry_name
    assert mcp_evt.status == "executed"
    # SubAgent 委派在链路中可重建
    del_evt = delegation_events[0]
    assert del_evt.ref_id == "s4-ref-d1"
    assert del_evt.name == "repo_gap_auditor"
    assert del_evt.policy_outcome == "accept_result"

    # ─── AC-3：注入的 fake secret 在 chain preview 中被 redacted ───
    assert _FAKE_SECRET_IN_RESULT not in mcp_evt.output_preview, (
        "fake secret 不得泄漏到 replay chain preview（AC-3）"
    )
    assert "[REDACTED]" in mcp_evt.output_preview

    # ─── verify：verify_evidence 通过（AC-5）───
    verification = verify_evidence(state)
    assert verification.ok is True, (
        f"完整 governed task evidence 必须通过校验，findings={verification.findings}"
    )

    # ─── AC-1：S2/S3 + S4 非回归 + 不 release-block ───
    acceptance = build_s2_acceptance_report(
        (
            AcceptanceCheckResult(
                name="s4_reference_task_audit_replay_e2e",
                command=".venv/bin/python -m pytest tests/test_s4_reference_task_acceptance.py",
                exit_code=0,
            ),
            AcceptanceCheckResult(
                name="s2_reference_task_non_regression",
                command=".venv/bin/python -m pytest tests/test_s2_reference_task_acceptance.py",
                exit_code=0,
            ),
            AcceptanceCheckResult(
                name="s3_reference_task_non_regression",
                command=".venv/bin/python -m pytest tests/test_s3_reference_task_acceptance.py",
                exit_code=0,
            ),
        )
    )
    assert acceptance.release_blocked is False
    assert acceptance.runtime_regressions == ()


# ─── S4-G07: real provider audit/replay key-path smoke（opt-in / key-safe）───

_S4_REAL_PROVIDER_SMOKE_ENV = "MY_FIRST_AGENT_RUN_S4_REAL_PROVIDER_SMOKE"
_FAKE_KEY_PATTERNS = (
    "test-key",
    "sk-test-",
    "secret-token-must-not-leak",
    "fake",
    "dummy",
    "placeholder",
    "your-api-key",
    "your-key",
    "changeme",
    "example.invalid",
)


def _s4_real_provider_env_ready() -> tuple[bool, str]:
    """S4 real provider smoke opt-in gate（collection-time）。

    只检查显式 opt-in 标志；provider 是否真实可用由生产路径 build_model_provider_from_env()
    解析（优先读 gitignored config/config.yaml）。不要求把 secret 导出到 env var——key
    留在 config 中，测试只透传 provider 对象，不打印/复制/移动/提交/持久化 secret（api_key
    仅在进程内瞬态读取用于 fake-key 检测，绝不外泄）。
    """
    if os.environ.get(_S4_REAL_PROVIDER_SMOKE_ENV, "") != "1":
        return False, (
            "S4 real provider smoke requires explicit opt-in: "
            f"{_S4_REAL_PROVIDER_SMOKE_ENV}=1"
        )
    return True, "opt-in"


_S4_REAL_READY, _S4_REAL_SKIP_REASON = _s4_real_provider_env_ready()


@pytest.mark.skipif(not _S4_REAL_READY, reason=_S4_REAL_SKIP_REASON)
def test_s4_reference_task_real_provider_audit_key_path_smoke(clean_tool_registry):
    """S4-G07 AC-6（real）：real provider 进入 audit/replay governed path 并产出可校验 evidence。

    证明 real provider（非 fake）：
    1. 进入 S4 audit/replay governed path（receive/accept + MCP 结果 + read-only SubAgent），
       与 fake E2E（G06）共享同一入口——不是旁路 bare provider.create()；
    2. real provider 在 governed task context 下 provider_callable；
    3. audit/replay evidence 与 fake/local 链路对齐：replay_chain 可重建、verify_evidence 通过、
       redaction 保持（key-safe）。

    release gate（resolved decision 4）：deliverable = key-safe opt-in harness + 结构校验；
    有 key 且安全时可跑关键 smoke，无 key 时 default skip + 结构校验（G06 fake E2E）即满足
    AC-6 real 维度。real-key 实跑**非必需、非 release blocker**。
    key-safe：opt-in + fake-key 检测；不打印/复制/移动/提交/持久化 secret（api_key 仅在
    进程内瞬态读取用于 fake-key 检测，绝不外泄）；不改 config/config.yaml；
    不创建 .env。MCP 用 fake/fixture source（不连真实 endpoint），SubAgent 用 local_fake。
    """
    # --- 1. 进入 audit/replay governed path（与 fake E2E 同一入口）---
    mcp_registry_name = _register_fixture_mcp_source()
    state = create_agent_state(system_prompt="S4 real provider audit/replay smoke")
    state.memory.session_id = "s4-real-provider-audit-smoke-session"
    assert receive_governed_task(
        state,
        user_goal="Audit/replay of fixture repo governance gap",
        plan_payload=_s4_reference_task_plan(),
    ).allowed
    assert accept_governed_plan(state).allowed
    _record_mcp_result(
        state,
        tool_use_id="tool-s4-real-smoke-mcp",
        tool_name=mcp_registry_name,
        result=f"S4-G07 real smoke: evidence aligned with fake; token={_FAKE_SECRET_IN_RESULT}",
    )
    _record_subagent_second_opinion(state, delegation_id="s4-real-smoke-d1")

    # --- 2. governed task context（provider_callable 校验）---
    context = build_task_execution_context(state)
    assert context.provider_callable is True

    # --- 3. real provider via 生产路径（与 runtime 同源：优先读 config/config.yaml）---
    from agent.provider.factory import build_model_provider_from_env

    provider = build_model_provider_from_env()
    provider_type = getattr(provider, "provider_type", "unknown")
    provider_api_key = getattr(getattr(provider, "config", None), "api_key", "") or ""
    if provider_type == "fake" or not provider_api_key:
        pytest.skip(
            "opt-in set but provider resolved to fake/empty; "
            "configure a non-fake provider in config/config.yaml"
        )
    for _pattern in _FAKE_KEY_PATTERNS:
        if _pattern.lower() in provider_api_key.lower():
            pytest.skip(
                "provider api_key is a known fake placeholder; "
                "real smoke needs a real key in config/config.yaml"
            )

    response = provider.create(
        system=state.runtime.system_prompt,
        messages=(
            list(context.model_messages)
            + [
                {
                    "role": "user",
                    "content": (
                        "This is an S4 audit/replay governed reference-task real-provider "
                        "smoke. Reply with exactly: s4-reference-task-provider-ok"
                    ),
                }
            ]
        ),
        tools=[],
    )
    text = "\n".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    assert "s4-reference-task-provider-ok" in text, (
        "real provider 未在 S4 audit/replay governed task context 下返回预期 smoke 回复"
    )

    # --- 4. audit/replay evidence 与 fake/local 链路对齐 + key-safe ---
    report = build_task_evidence_report(state, context_package=context)
    assert report.replay_chain_event_count > 0
    chain = build_replay_chain(state)
    # MCP tool + SubAgent 委派可重建
    assert any(e.ref_id == "tool-s4-real-smoke-mcp" for e in chain.tool_events)
    assert any(e.ref_id == "s4-real-smoke-d1" for e in chain.delegation_events)
    # verify 通过
    assert verify_evidence(state).ok is True
    # key-safe：fake secret 在 chain preview 中被 redacted（AC-3 在 real path 也成立）
    mcp_evt = next(e for e in chain.tool_events if e.ref_id == "tool-s4-real-smoke-mcp")
    assert _FAKE_SECRET_IN_RESULT not in mcp_evt.output_preview

    acceptance = build_s2_acceptance_report(
        (
            AcceptanceCheckResult(
                name="s4_reference_task_real_provider_audit_smoke",
                command=(
                    f"{_S4_REAL_PROVIDER_SMOKE_ENV}=1 "
                    ".venv/bin/python -m pytest tests/test_s4_reference_task_acceptance.py"
                ),
                exit_code=0,
            ),
        )
    )
    assert acceptance.release_blocked is False

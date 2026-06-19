from __future__ import annotations

import os

import pytest

from agent.acceptance_gate import AcceptanceCheckResult, build_s2_acceptance_report
from agent.state import create_agent_state
from agent.task_context import (
    build_task_execution_context,
    record_task_memory_boundary_evidence,
)
from agent.task_orchestration import (
    accept_governed_plan,
    advance_governed_task_if_ready,
    receive_governed_task,
    resume_governed_task,
)
from agent.task_review import (
    build_task_progress_review,
    parse_human_takeover_decision,
    record_task_progress_review_evidence,
)
from agent.task_state_model import GovernedTaskLifecycle
from agent.task_tool_contract import (
    build_governed_tool_contract_report,
    record_tool_contract_evidence,
)
from config import STEP_COMPLETION_THRESHOLD

_S2_REAL_PROVIDER_SMOKE_ENV = "MY_FIRST_AGENT_RUN_S2_REAL_PROVIDER_SMOKE"
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


def _reference_task_plan() -> dict:
    return {
        "goal": "repo-governed improvement task",
        "thinking": "inspect S2 evidence, make one focused change, verify and report",
        "steps": [
            {
                "step_id": "s2-acceptance-1",
                "title": "Inspect current S2 evidence",
                "description": "Read S2 gap, docs, code evidence, and existing tests.",
                "step_type": "read",
            },
            {
                "step_id": "s2-acceptance-2",
                "title": "Apply focused governed change",
                "description": "Apply a small local-only change or audit result.",
                "step_type": "edit",
            },
            {
                "step_id": "s2-acceptance-3",
                "title": "Verify and report evidence",
                "description": "Run targeted checks, record evidence, and summarize outcome.",
                "step_type": "report",
            },
        ],
    }


def _mark_step_complete(state, *, tool_use_id: str, summary: str) -> None:
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


def _record_governed_tool_result(
    state,
    *,
    tool_use_id: str,
    tool_name: str,
    result: str,
) -> None:
    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "status": "executed",
        "input": {"target": "s2 reference task fixture"},
        "result": result,
        "step_index": state.task.current_step_index,
    }


def _real_provider_env_ready() -> tuple[bool, str]:
    """S2 real provider smoke opt-in gate（collection-time）。

    只检查显式 opt-in 标志；provider 是否真实可用在测试体内通过生产路径
    build_model_provider_from_env() 解析（优先读 config/config.yaml，与 runtime
    同源）。这避免要求 user 把 secret 导出到 env var——key 留在 gitignored
    config/config.yaml 中，测试只透传 config 对象，不读取/打印/移动/提交 secret。
    """
    if os.environ.get(_S2_REAL_PROVIDER_SMOKE_ENV, "") != "1":
        return False, (
            "S2 real provider smoke requires explicit opt-in: "
            f"{_S2_REAL_PROVIDER_SMOKE_ENV}=1"
        )
    return True, "opt-in"


def test_s2_reference_task_fake_e2e_checkpoint_resume_evidence_and_gate(tmp_path):
    from agent.checkpoint import clear_checkpoint, load_checkpoint_to_state, save_checkpoint

    checkpoint_path = tmp_path / "s2-reference-task-checkpoint.json"
    evidence_calls: list[dict] = []

    def fake_record_evidence(**kwargs):
        evidence_calls.append(kwargs)
        return kwargs

    state = create_agent_state(system_prompt="S2 test runtime")
    state.memory.session_id = "s2-reference-task-session"
    state.memory.working_summary = "Prior S2 loop context is available."

    received = receive_governed_task(
        state,
        user_goal="Resolve one eligible S2 gap from repo evidence",
        plan_payload=_reference_task_plan(),
    )
    assert received.allowed is True
    assert received.snapshot.lifecycle is GovernedTaskLifecycle.WAITING

    accepted = accept_governed_plan(state)
    assert accepted.allowed is True
    assert accepted.snapshot.lifecycle is GovernedTaskLifecycle.RUNNING

    _record_governed_tool_result(
        state,
        tool_use_id="tool-docs-read",
        tool_name="read_file",
        result="S2-G07 requires fake and real reference task acceptance evidence.",
    )
    context = build_task_execution_context(state)
    tool_report = build_governed_tool_contract_report(state, context_package=context)
    review = build_task_progress_review(
        state,
        context_package=context,
        tool_report=tool_report,
    )
    assert context.provider_callable is True
    assert tool_report.audit_ready is True
    assert "Progress: 0/3" in review.review_text
    assert parse_human_takeover_decision("continue", review=review).allowed is True

    record_task_memory_boundary_evidence(
        context,
        record_evidence_fn=fake_record_evidence,
    )
    record_tool_contract_evidence(
        tool_report,
        record_evidence_fn=fake_record_evidence,
    )
    record_task_progress_review_evidence(
        review,
        record_evidence_fn=fake_record_evidence,
    )

    _mark_step_complete(state, tool_use_id="meta-step-1", summary="S2 evidence inspected")
    assert advance_governed_task_if_ready(state).snapshot.progress.completed_steps == 1
    save_checkpoint(state, source="tests.s2.reference_task.step1", path=checkpoint_path)

    resumed = create_agent_state(system_prompt="S2 test runtime")
    assert load_checkpoint_to_state(resumed, path=checkpoint_path)
    assert resume_governed_task(resumed).progress.current_step_index == 1

    _record_governed_tool_result(
        resumed,
        tool_use_id="tool-focused-change",
        tool_name="apply_patch",
        result="Focused local S2 fixture change completed.",
    )
    _mark_step_complete(
        resumed,
        tool_use_id="meta-step-2",
        summary="Focused governed change completed",
    )
    assert advance_governed_task_if_ready(resumed).snapshot.progress.completed_steps == 2

    _record_governed_tool_result(
        resumed,
        tool_use_id="tool-targeted-test",
        tool_name="pytest",
        result="targeted S2 acceptance passed",
    )
    _mark_step_complete(
        resumed,
        tool_use_id="meta-step-3",
        summary="Targeted checks and evidence completed",
    )
    completed = advance_governed_task_if_ready(resumed)
    assert completed.snapshot.lifecycle is GovernedTaskLifecycle.DONE
    assert completed.snapshot.progress.percent == 100.0

    acceptance = build_s2_acceptance_report((
        AcceptanceCheckResult(
            name="s2_reference_task_fake_e2e",
            command=".venv/bin/python -m pytest tests/test_s2_reference_task_acceptance.py",
            exit_code=0,
        ),
    ))
    assert acceptance.release_blocked is False
    assert acceptance.runtime_regressions == ()
    assert {call["subsystem"] for call in evidence_calls} == {"memory", "tool", "task"}
    clear_checkpoint(path=checkpoint_path)


_REAL_READY, _REAL_SKIP_REASON = _real_provider_env_ready()


@pytest.mark.skipif(not _REAL_READY, reason=_REAL_SKIP_REASON)
def test_s2_reference_task_real_provider_key_safe_context_smoke(monkeypatch):
    """S2-G07 AC-7: real provider 进入 S2 governed task path 并产生对齐 evidence。

    本 smoke 证明 real provider（非 fake）：
    1. 进入 S2 governed task path（receive/accept/context），与 fake E2E 共享同一入口；
    2. S2 task context 在 real provider 下 provider-callable（真实调用验证）；
    3. 通过同一 evidence-recording seam 记录 task-level evidence，与 fake/local
       关键事件链路对齐（subsystem 集合 = {memory, tool, task}）。

    这不是旁路的 bare provider.create()：provider 调用发生在 governed task context
    构建之后，且 evidence 经由与 fake E2E 完全相同的 seam 记录。

    key-safe：opt-in + fake-key 检测；不读取/打印/移动/提交 secret；不修改
    config/config.yaml；不创建 .env。仅发送 fixture 级 S2 task context。
    """
    from agent.task_evidence_report import build_task_evidence_report

    # --- 1. 进入 S2 governed task path（与 fake E2E 同一入口）---
    state = create_agent_state(system_prompt="S2 real provider governed smoke")
    state.memory.session_id = "s2-real-provider-smoke-session"
    assert receive_governed_task(
        state,
        user_goal="Resolve one eligible S2 gap from repo evidence",
        plan_payload=_reference_task_plan(),
    ).allowed
    assert accept_governed_plan(state).allowed

    # 记录一次 governed tool 结果，使 tool contract / evidence 有内容（与 fake 对齐）
    _record_governed_tool_result(
        state,
        tool_use_id="tool-real-smoke-read",
        tool_name="read_file",
        result="S2-G07 real provider smoke: governed path evidence aligned with fake.",
    )

    # --- 2. 构建 governed task context（provider-callable 校验）---
    context = build_task_execution_context(state)
    assert context.provider_callable is True

    # --- 3. real provider via 生产路径（与 runtime 同源：优先读 config/config.yaml）。
    # 证明 S2 task context 在真实 provider 下可用；不走 env-only 旁路 loader。---
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
                        "This is an S2 governed reference-task real-provider smoke. "
                        "Reply with exactly: s2-reference-task-provider-ok"
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
    assert "s2-reference-task-provider-ok" in text, (
        "real provider 未在 S2 governed task context 下返回预期 smoke 回复"
    )

    # --- 4. 通过同一 evidence seam 记录 task-level evidence（与 fake/local 对齐）---
    tool_report = build_governed_tool_contract_report(state, context_package=context)
    review = build_task_progress_review(
        state,
        context_package=context,
        tool_report=tool_report,
    )
    evidence_calls: list[dict] = []

    def real_record_evidence(**kwargs):
        evidence_calls.append(kwargs)
        return kwargs

    record_task_memory_boundary_evidence(context, record_evidence_fn=real_record_evidence)
    record_tool_contract_evidence(tool_report, record_evidence_fn=real_record_evidence)
    record_task_progress_review_evidence(review, record_evidence_fn=real_record_evidence)
    report = build_task_evidence_report(
        state,
        context_package=context,
        tool_report=tool_report,
        progress_review=review,
    )

    # 关键事件链路对齐：与 fake E2E 共享同一 evidence subsystems（证明 real provider
    # 进入同一 governed evidence path，而非旁路 bare provider.create()）
    assert {call["subsystem"] for call in evidence_calls} == {"memory", "tool", "task"}
    assert report.provider_callable is True
    assert report.replay_ready is True

    acceptance = build_s2_acceptance_report((
        AcceptanceCheckResult(
            name="s2_reference_task_real_provider_governed_path_smoke",
            command=(
                f"{_S2_REAL_PROVIDER_SMOKE_ENV}=1 "
                ".venv/bin/python -m pytest "
                "tests/test_s2_reference_task_acceptance.py"
            ),
            exit_code=0,
        ),
    ))
    assert acceptance.release_blocked is False

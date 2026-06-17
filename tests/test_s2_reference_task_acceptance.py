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
    opt_in = os.environ.get(_S2_REAL_PROVIDER_SMOKE_ENV, "")
    if opt_in != "1":
        return False, (
            "S2 real provider smoke requires explicit opt-in: "
            f"{_S2_REAL_PROVIDER_SMOKE_ENV}=1"
        )

    missing = []
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"):
        if not os.environ.get(name):
            missing.append(name)
    if missing:
        return False, f"missing provider environment variables: {', '.join(missing)}"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    for pattern in _FAKE_KEY_PATTERNS:
        if pattern.lower() in api_key.lower() or pattern.lower() in base_url.lower():
            return False, "provider environment contains a known fake placeholder"

    return True, "ready"


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
    from agent.provider.config import load_agent_provider_config
    from agent.provider.factory import build_model_provider

    state = create_agent_state(system_prompt="S2 real provider smoke")
    assert receive_governed_task(
        state,
        user_goal="Resolve one eligible S2 gap from repo evidence",
        plan_payload=_reference_task_plan(),
    ).allowed
    assert accept_governed_plan(state).allowed

    context = build_task_execution_context(state)
    assert context.provider_callable is True

    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic_compatible")
    config = load_agent_provider_config()
    provider = build_model_provider(config)
    provider_type = getattr(provider, "provider_type", "unknown")
    assert provider_type != "fake"

    response = provider.create(
        system=state.runtime.system_prompt,
        messages=(
            list(context.model_messages)
            + [
                {
                    "role": "user",
                    "content": (
                        "This is an S2 governed reference-task smoke. "
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

    assert "s2-reference-task-provider-ok" in text
    acceptance = build_s2_acceptance_report((
        AcceptanceCheckResult(
            name="s2_reference_task_real_provider_smoke",
            command=(
                f"{_S2_REAL_PROVIDER_SMOKE_ENV}=1 "
                ".venv/bin/python -m pytest "
                "tests/test_s2_reference_task_acceptance.py"
            ),
            exit_code=0,
        ),
    ))
    assert acceptance.release_blocked is False

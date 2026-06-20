"""S4-G11 optional audit observability 测试（人读 audit 视图，P3 增强）。

验证 render_replay_summary 把 replay chain 渲染成人读、redacted 的审计摘要；注入的 fake
secret 不出现（G03 保证 + 本模块 defense-in-depth）；结构化计数无 content 泄漏。
"""
from __future__ import annotations

from agent.audit_observability import render_replay_summary, replay_summary_stats
from agent.state import create_agent_state
from agent.task_replay_chain import build_replay_chain

_FAKE_SECRET = "sk-test-secret-ZZZZZZZZZZZZZZZZ"


def _chain_with_secret() -> object:
    state = create_agent_state(system_prompt="s4-test", model_name="fake")
    state.task.user_goal = "audit observability test"
    state.task.current_plan = {
        "goal": "g",
        "thinking": "t",
        "steps": [
            {"step_id": "s1", "title": "Inspect", "description": "read", "step_type": "read"},
        ],
    }
    state.task.status = "running"
    state.task.current_step_index = 1
    state.task.tool_execution_log = {
        "toolu_a": {
            "tool": "http_request",
            "status": "executed",
            "input": {"api_key": _FAKE_SECRET},
            "result": f"response with token {_FAKE_SECRET}",
            "step_index": 0,
        },
    }
    state.task.delegation_log = [
        {
            "delegation_id": "del_1",
            "subagent_name": "auditor",
            "status": "delegated",
            "adjudication_action": "accept",
            "step_index": 1,
        },
    ]
    return build_replay_chain(state)


def test_render_replay_summary_is_human_readable():
    chain = _chain_with_secret()
    summary = render_replay_summary(chain)
    assert isinstance(summary, str)
    assert "Replay summary:" in summary
    # 结构可读：每个事件一行，含 kind/name/status/policy
    assert "tool:" in summary
    assert "delegation:" in summary
    assert "status=executed" in summary
    assert "policy=accept" in summary


def test_render_replay_summary_redacts_secret():
    """注入的 fake secret 不得出现在人读摘要（G03 + defense-in-depth）。"""
    summary = render_replay_summary(_chain_with_secret())
    assert _FAKE_SECRET not in summary


def test_replay_summary_stats_no_content_leak():
    """结构化计数全为整数，不含 content/secret。"""
    chain = _chain_with_secret()
    stats = replay_summary_stats(chain)
    assert stats["tool_events"] == 1
    assert stats["delegation_events"] == 1
    assert stats["decision_events"] >= 1
    assert stats["total_events"] == (
        stats["tool_events"] + stats["delegation_events"] + stats["decision_events"]
    )
    # 无 content 泄漏
    assert _FAKE_SECRET not in str(stats)


def test_render_empty_chain_does_not_crash():
    from agent.task_replay_chain import ReplayChain

    empty = ReplayChain(task_scope_id="x", lifecycle="idle", events=())
    summary = render_replay_summary(empty)
    assert "empty" in summary
    assert replay_summary_stats(empty)["total_events"] == 0

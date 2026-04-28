"""Checkpoint resume 语义测试（v0.2 M3）。

本文件保护 `docs/CHECKPOINT_RESUME_SEMANTICS.md` 的关键契约：
- §3 status × pending 字段 → resume 行为表
- §4 损坏 / 兼容场景（包括 M3 新增的「未知 key 丢弃」）
- §6 tool_use ↔ tool_result 配对完整性

定位：本文件是 `tests/test_checkpoint_roundtrip.py`（字段级 roundtrip）和
`tests/test_state_invariants.py`（reset / status helper / core self-heal）的
中间层——专门覆盖「resume 之后 state 是否真的能继续工作 + 损坏场景能否兜底」。
"""

from __future__ import annotations

import json

import pytest

from agent.state import create_agent_state, task_status_requires_plan


@pytest.fixture
def tmp_checkpoint_path(tmp_path, monkeypatch):
    from agent import checkpoint

    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    return path


# ---------------------------------------------------------------------------
# §3 各 status 的 resume 行为
# ---------------------------------------------------------------------------

def _save_then_load(src):
    """save → 新建空 state → load 的小工具。"""
    from agent.checkpoint import save_checkpoint, load_checkpoint_to_state

    save_checkpoint(src, source="tests.resume.smoke")
    dst = create_agent_state(system_prompt="other")
    assert load_checkpoint_to_state(dst)
    return dst


def test_resume_awaiting_plan_confirmation_preserves_plan():
    """awaiting_plan_confirmation resume 后 current_plan + status 都在。"""
    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "做某事"
    src.task.current_plan = {"goal": "g", "steps": [{"title": "step1"}]}
    src.task.status = "awaiting_plan_confirmation"

    dst = _save_then_load(src)

    assert dst.task.status == "awaiting_plan_confirmation"
    assert dst.task.current_plan == {"goal": "g", "steps": [{"title": "step1"}]}
    # plan 子状态需要 plan 才合法，task_status_requires_plan 帮 core 做自检。
    assert task_status_requires_plan(dst.task)


def test_resume_awaiting_user_input_runtime_pending_is_intact():
    """request_user_input 路径：pending 必须 roundtrip，UI 才能重放问题。"""
    src = create_agent_state(system_prompt="test")
    src.task.status = "awaiting_user_input"
    src.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "预算？",
        "why_needed": "继续当前任务",
        "tool_use_id": "ru_X",
    }

    dst = _save_then_load(src)

    assert dst.task.status == "awaiting_user_input"
    assert dst.task.pending_user_input_request["awaiting_kind"] == "request_user_input"
    assert dst.task.pending_user_input_request["question"] == "预算？"
    # runtime pending 路径不需要 plan，避免 core invariant 误伤。
    assert not task_status_requires_plan(dst.task)


def test_resume_awaiting_user_input_collect_input_has_no_pending():
    """collect_input/clarify 路径：pending 永远是 None；resume 后保持 None。"""
    src = create_agent_state(system_prompt="test")
    src.task.status = "awaiting_user_input"
    src.task.current_plan = {
        "goal": "g",
        "steps": [{"title": "请回答", "type": "collect_input"}],
    }
    src.task.pending_user_input_request = None

    dst = _save_then_load(src)

    assert dst.task.status == "awaiting_user_input"
    assert dst.task.pending_user_input_request is None
    assert task_status_requires_plan(dst.task)  # collect_input 需要 plan


def test_resume_awaiting_tool_confirmation_preserves_pending_tool():
    """工具确认 resume 后 pending_tool 完整保留，UI 才能重显待执行工具。"""
    src = create_agent_state(system_prompt="test")
    src.task.status = "awaiting_tool_confirmation"
    src.task.pending_tool = {
        "tool_use_id": "T1",
        "tool": "write_file",
        "input": {"path": "x.txt", "content": "hi"},
    }

    dst = _save_then_load(src)

    assert dst.task.status == "awaiting_tool_confirmation"
    assert dst.task.pending_tool["tool_use_id"] == "T1"
    assert dst.task.pending_tool["tool"] == "write_file"
    assert dst.task.pending_tool["input"] == {"path": "x.txt", "content": "hi"}
    assert not task_status_requires_plan(dst.task)


def test_resume_running_with_step_progress():
    """running 中断后 step index / loop_iterations / tool_call_count 必须回来。"""
    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "目标"
    src.task.current_plan = {
        "goal": "g",
        "steps": [{"title": "s1"}, {"title": "s2"}, {"title": "s3"}],
    }
    src.task.status = "running"
    src.task.current_step_index = 1
    src.task.loop_iterations = 7
    src.task.tool_call_count = 3
    src.task.tool_execution_log = {"T0": {"tool": "x", "input": {}, "result": "r"}}

    dst = _save_then_load(src)

    assert dst.task.status == "running"
    assert dst.task.current_step_index == 1
    assert dst.task.loop_iterations == 7
    assert dst.task.tool_call_count == 3
    assert "T0" in dst.task.tool_execution_log


@pytest.mark.parametrize("terminal_status", ["done", "failed", "cancelled"])
def test_resume_terminal_states_do_not_require_plan(terminal_status):
    """终止态 resume 后不应被 plan invariant 误伤。"""
    src = create_agent_state(system_prompt="test")
    src.task.status = terminal_status

    dst = _save_then_load(src)

    assert dst.task.status == terminal_status
    assert not task_status_requires_plan(dst.task)


# ---------------------------------------------------------------------------
# §4 损坏 / 兼容场景
# ---------------------------------------------------------------------------

def test_corrupted_json_returns_none(tmp_checkpoint_path):
    """JSON 解析失败时 load_checkpoint 返回 None，进程不 crash。"""
    from agent.checkpoint import load_checkpoint, load_checkpoint_to_state

    tmp_checkpoint_path.write_text("not a json {", encoding="utf-8")

    assert load_checkpoint() is None

    dst = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(dst) is False
    # state 保持初始化默认值。
    assert dst.task.status == "idle"
    assert dst.task.current_plan is None


def test_unknown_task_keys_are_dropped_on_resume(tmp_checkpoint_path):
    """checkpoint task 段含未知 key（旧 / 调试 / 攻击注入）时必须被丢弃。

    M3 在 `_filter_to_declared_fields` 把 setattr 收紧到 dataclass 声明字段；
    本测试是该硬化的回归保护。如果有人未来把过滤逻辑放回宽松版本，本测试
    会 red，提醒回看 docs/CHECKPOINT_RESUME_SEMANTICS.md §4.4。
    """
    from agent.checkpoint import load_checkpoint_to_state

    payload = {
        "meta": {"session_id": "s1"},
        "task": {
            "user_goal": "目标",
            "status": "running",
            "current_plan": {"goal": "g", "steps": []},
            # 这些字段都不在 TaskState 声明里，必须被丢弃。
            "__injected_runtime_event__": {"event_type": "tool.requested"},
            "rogue_attribute": "should_not_appear",
            "pending_runtime_event_buffer": [1, 2, 3],
        },
        "memory": {"working_summary": None, "session_id": "s1"},
        "conversation": {"messages": []},
    }
    tmp_checkpoint_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    dst = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(dst)

    # 已声明字段恢复正常。
    assert dst.task.user_goal == "目标"
    assert dst.task.status == "running"
    # 未知字段必须不挂到 state.task。
    for forbidden in (
        "__injected_runtime_event__",
        "rogue_attribute",
        "pending_runtime_event_buffer",
    ):
        assert not hasattr(dst.task, forbidden), (
            f"未知 key '{forbidden}' 不应该被挂到 state.task；"
            " 检查 _filter_to_declared_fields 是否被改弱。"
        )


def test_unknown_memory_keys_are_dropped_on_resume(tmp_checkpoint_path):
    """memory 段同样走字段白名单，未知 key 必须丢弃。"""
    from agent.checkpoint import load_checkpoint_to_state

    payload = {
        "meta": {"session_id": "s2"},
        "task": {"user_goal": None, "status": "idle"},
        "memory": {
            "working_summary": "ok",
            "session_id": "s2",
            "rogue_memory_field": "leak",
        },
        "conversation": {"messages": []},
    }
    tmp_checkpoint_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    dst = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(dst)

    assert dst.memory.working_summary == "ok"
    assert dst.memory.session_id == "s2"
    assert not hasattr(dst.memory, "rogue_memory_field")


# ---------------------------------------------------------------------------
# §6 tool_use ↔ tool_result 配对完整性
# ---------------------------------------------------------------------------

def test_resume_preserves_tool_use_tool_result_pairing():
    """大 tool_result 截断不能破坏 tool_use_id 配对。

    Anthropic 协议硬要求：assistant 里每个 tool_use.id 必须出现在紧随其后的
    user message 的 tool_result.tool_use_id 中。如果 _truncate_messages_for_checkpoint
    把 tool_result block 拆开或丢弃，下次 _project_to_api 投影会构造非法 messages。
    """
    from agent.checkpoint import MAX_RESULT_LENGTH

    huge = "x" * (MAX_RESULT_LENGTH * 3)
    src = create_agent_state(system_prompt="test")
    src.conversation.messages = [
        {"role": "user", "content": "do it"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "id": "T1", "name": "echo", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "T1", "content": huge},
            ],
        },
    ]

    dst = _save_then_load(src)

    msgs = dst.conversation.messages
    assert len(msgs) == 3
    assistant_block = msgs[1]["content"]
    tool_use_ids = [
        b["id"] for b in assistant_block
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]
    tool_result_block = msgs[2]["content"][0]
    # 配对必须保留。
    assert tool_use_ids == ["T1"]
    assert tool_result_block["type"] == "tool_result"
    assert tool_result_block["tool_use_id"] == "T1"
    # 内容被截断，但块结构没拆。
    assert len(tool_result_block["content"]) <= MAX_RESULT_LENGTH


# ---------------------------------------------------------------------------
# §5 resume prompt 与 CLI 输出契约：CLI 不泄漏 checkpoint 内部值
# ---------------------------------------------------------------------------

def test_simple_cli_does_not_leak_checkpoint_meta_to_user(capsys):
    """普通 CLI resume 后不能把 meta.session_id / interrupted_at 等内部值
    打印到用户视图。

    本测试只覆盖 `_replay_awaiting_prompt` 的最小契约面：调用前后 stdout
    可能出现 plan / pending question 等 awaiting prompt 文本，但不允许出现
    checkpoint 内部 meta 字段。M3 不收口 print 旁路（→ M7），但保留这条
    防泄漏 assert。
    """
    from agent.session import _replay_awaiting_prompt

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "请告诉我预算",
        "why_needed": "继续当前任务",
    }

    _replay_awaiting_prompt(state)
    captured = capsys.readouterr().out

    # awaiting prompt 应当被重显（让用户知道继续应回答什么）。
    assert "请告诉我预算" in captured
    # 但 checkpoint 内部 meta 字段绝不能出现在用户视图。
    for forbidden in ("session_id", "interrupted_at", "checkpoint.json"):
        assert forbidden not in captured, (
            f"resume 用户视图意外出现 checkpoint 内部值 '{forbidden}'"
        )

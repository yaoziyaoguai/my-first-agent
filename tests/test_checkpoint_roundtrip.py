"""Checkpoint 保存/恢复的 roundtrip 测试。

覆盖：
- save → load 之后 state 字段应当完整恢复
- 旧 checkpoint（缺字段）能被恢复，不会 crash
- conversation.messages 里大 tool_result 被正确截断
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def tmp_checkpoint_path(tmp_path, monkeypatch):
    """把 checkpoint 写到临时目录，不污染真实 memory/checkpoint.json。"""
    from agent import checkpoint
    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    return path


def test_save_load_roundtrip_preserves_task_fields(tmp_checkpoint_path):
    """改完 task 各字段后 save → load，所有字段应当完整回来。"""
    from agent.checkpoint import save_checkpoint, load_checkpoint_to_state
    from agent.state import create_agent_state

    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "原始目标"
    src.task.current_plan = {"goal": "some", "steps": [{"title": "step1"}]}
    src.task.current_step_index = 2
    src.task.status = "running"
    src.task.retry_count = 3
    src.task.consecutive_max_tokens = 1
    src.task.tool_call_count = 7
    src.task.pending_tool = {"tool_use_id": "T1", "tool": "x", "input": {}}
    src.task.tool_execution_log = {"T0": {"tool": "a", "input": {}, "result": "r"}}
    src.memory.working_summary = "一段摘要"
    src.memory.session_id = "abc123"
    src.conversation.messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "收到"},
    ]

    save_checkpoint(src)

    # 造个空的 state，load 进来
    dst = create_agent_state(system_prompt="different")
    ok = load_checkpoint_to_state(dst)

    assert ok
    # task 字段
    assert dst.task.user_goal == "原始目标"
    assert dst.task.current_plan == {"goal": "some", "steps": [{"title": "step1"}]}
    assert dst.task.current_step_index == 2
    assert dst.task.status == "running"
    assert dst.task.retry_count == 3
    assert dst.task.consecutive_max_tokens == 1
    assert dst.task.tool_call_count == 7
    assert dst.task.pending_tool == {"tool_use_id": "T1", "tool": "x", "input": {}}
    assert "T0" in dst.task.tool_execution_log
    # memory 字段
    assert dst.memory.working_summary == "一段摘要"
    assert dst.memory.session_id == "abc123"
    # conversation
    assert len(dst.conversation.messages) == 2


def test_load_old_checkpoint_without_new_fields_does_not_crash(tmp_checkpoint_path):
    """旧 checkpoint 缺少后加的字段（比如 tool_call_count）时，
    load 应当不崩，新字段取 dataclass 默认值。"""
    from agent.checkpoint import load_checkpoint_to_state
    from agent.state import create_agent_state

    # 手工造一份"旧版" checkpoint：只有少数字段
    old_checkpoint = {
        "meta": {"session_id": "old"},
        "task": {
            "user_goal": "旧任务",
            "current_plan": None,
            "status": "idle",
            # tool_call_count / pending_tool / tool_execution_log 都缺
        },
        "memory": {"working_summary": None, "session_id": "old"},
        "conversation": {"messages": []},
    }
    tmp_checkpoint_path.write_text(
        json.dumps(old_checkpoint, ensure_ascii=False), encoding="utf-8"
    )

    dst = create_agent_state(system_prompt="test")
    ok = load_checkpoint_to_state(dst)

    assert ok
    # 旧字段正常恢复
    assert dst.task.user_goal == "旧任务"
    # 新字段保持 dataclass 默认值
    assert dst.task.tool_call_count == 0
    assert dst.task.pending_tool is None
    assert dst.task.tool_execution_log == {}


def test_checkpoint_truncates_large_tool_results(tmp_checkpoint_path):
    """单条 tool_result 内容超过 MAX_RESULT_LENGTH 应当被截断。"""
    from agent.checkpoint import save_checkpoint, MAX_RESULT_LENGTH
    from agent.state import create_agent_state

    huge_result = "x" * (MAX_RESULT_LENGTH * 3)
    src = create_agent_state(system_prompt="test")
    src.conversation.messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "T1",
                    "content": huge_result,
                }
            ],
        }
    ]
    save_checkpoint(src)

    on_disk = json.loads(tmp_checkpoint_path.read_text(encoding="utf-8"))
    stored_content = on_disk["conversation"]["messages"][0]["content"][0]["content"]

    assert len(stored_content) <= MAX_RESULT_LENGTH, (
        f"大 tool_result 应当被截断到 {MAX_RESULT_LENGTH}，实际长度 {len(stored_content)}"
    )


def test_save_checkpoint_does_not_print_loaded(tmp_checkpoint_path, capsys):
    """保存 checkpoint 时为了继承旧 meta 读取旧文件，不应打印 loaded 误导为恢复。"""
    from agent.checkpoint import save_checkpoint
    from agent.state import create_agent_state

    src = create_agent_state(system_prompt="test")
    src.task.status = "running"

    save_checkpoint(src)
    first = capsys.readouterr().out
    assert "[CHECKPOINT] loaded" not in first
    assert "[CHECKPOINT] saved" in first

    # 第二次保存时磁盘已有 checkpoint；仍然只能打印 saved，不能打印 loaded。
    save_checkpoint(src)
    second = capsys.readouterr().out
    assert "[CHECKPOINT] loaded" not in second
    assert "[CHECKPOINT] saved" in second


def test_load_returns_false_when_no_file(tmp_checkpoint_path):
    """checkpoint 文件不存在时 load 应当返回 False，而不是崩。"""
    from agent.checkpoint import load_checkpoint_to_state
    from agent.state import create_agent_state

    # tmp_checkpoint_path 对应的文件确实不存在
    assert not tmp_checkpoint_path.exists()

    dst = create_agent_state(system_prompt="test")
    ok = load_checkpoint_to_state(dst)

    assert ok is False

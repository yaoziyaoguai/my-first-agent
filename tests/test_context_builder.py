"""build_execution_messages / build_planning_messages 的单测。

目的是把本周那个 step 块位置踩的坑用断言钉死：
如果以后有人把 step 块挪到 messages 末尾，这些测试会立刻红。
"""

from __future__ import annotations

from agent.context_builder import build_execution_messages, build_planning_messages


def _find_step_block_index(msgs: list[dict]) -> int:
    """返回 messages 里 step 指令块所在的下标（找不到返回 -1）"""
    for i, m in enumerate(msgs):
        c = m.get("content")
        if isinstance(c, str) and "[当前任务]" in c:
            return i
    return -1


def test_step_block_comes_before_conversation_history(fresh_state, two_step_plan):
    """step 指令块必须出现在历史对话之前。

    回归防护：本周曾把 step 块挪到 messages 末尾，导致每轮 request 的最后一条
    user 都是"你正在执行第 N 步"，Kimi 之类的模型会当作新指令反复调同一个工具，
    任务卡死。钉死"step 块在前、conversation 在后"这一点。
    """
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.status = "running"
    fresh_state.conversation.messages = [
        {"role": "user", "content": "帮我评估项目"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "T1", "name": "run_shell", "input": {"command": "ls"}}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T1", "content": "some files"}
        ]},
    ]

    msgs = build_execution_messages(fresh_state)
    step_idx = _find_step_block_index(msgs)
    assert step_idx != -1, "应当包含 step 指令块"

    # 找到第一条 conversation 原文（就是"帮我评估项目"那一条 pure text user）
    history_idx = next(
        i for i, m in enumerate(msgs)
        if isinstance(m.get("content"), str) and m["content"] == "帮我评估项目"
    )
    assert step_idx < history_idx, (
        f"step 块应当在历史对话之前（step_idx={step_idx}, history_idx={history_idx}）"
    )


def test_last_message_is_latest_tool_result_not_step_block(fresh_state, two_step_plan):
    """最后一条消息应该是最新的 tool_result，而不是 step 指令块。

    Kimi 等模型对"最后一条 user 消息" 敏感度特别高。如果最后一条永远是 step
    指令块，模型会反复解读成"重新开始这一步"。
    """
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.status = "running"
    fresh_state.conversation.messages = [
        {"role": "user", "content": "帮我评估项目"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "T1", "name": "run_shell", "input": {"command": "ls"}}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T1", "content": "some files"}
        ]},
    ]

    msgs = build_execution_messages(fresh_state)
    last = msgs[-1]

    # 最后一条必须是 tool_result 结构
    assert isinstance(last.get("content"), list), "最后一条 content 应当是 list（tool_result）"
    assert last["content"][0].get("type") == "tool_result", (
        f"最后一条应当是 tool_result，实际是 {last['content'][0].get('type')}"
    )


def test_step_block_skipped_when_status_done(fresh_state, two_step_plan):
    """task.status == 'done' 时不应该拼 step 块，即使 current_plan 还在。

    防御：任务完成到 reset_task 之间可能有一小段窗口，这时还有 current_plan
    但不能再把旧步骤指令喂给模型。

    ⚠️ 已修复：2026-04 build_execution_messages 加了 `and status != "done"` 防御。
    """
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.status = "done"

    msgs = build_execution_messages(fresh_state)
    assert _find_step_block_index(msgs) == -1, "status=done 时不应出现 step 块"


def test_planning_messages_does_not_include_current_plan(fresh_state, two_step_plan):
    """planner 的投影不应该看到 current_plan，避免被上一版 plan 带偏。"""
    fresh_state.task.current_plan = two_step_plan

    msgs = build_planning_messages(fresh_state, "帮我做个新任务")

    # 检查任何一条消息里都不含 step 块的特征文字
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            assert "[当前任务]" not in c, "planning messages 不应含 step 指令块"
            assert "[当前步骤标题]" not in c

"""`awaiting_user_input + USER_REPLIED` 显式 transition 的架构语义测试。

这些测试验证的是状态机含义，而不是单纯断言某行代码执行：
- collect_input 的用户答复代表“这个收集信息 step 完成”，所以要推进；
- runtime 求助的用户答复代表“当前 step 获得补充上下文”，所以不能推进；
- 两类答复都必须落进 messages 并保存 checkpoint，保证中断恢复不丢信息。
"""

from __future__ import annotations


def _patch_checkpoint_counter(monkeypatch):
    """把 checkpoint 副作用替换成计数器，测试 transition 是否触发保存动作。"""
    from agent import checkpoint

    calls = {"save": 0, "clear": 0}

    def save_checkpoint(_state):
        calls["save"] += 1

    def clear_checkpoint():
        calls["clear"] += 1

    monkeypatch.setattr(checkpoint, "save_checkpoint", save_checkpoint)
    monkeypatch.setattr(checkpoint, "clear_checkpoint", clear_checkpoint)
    return calls


def _step_input_texts(state):
    """收集 step_input 文本，测试用户答复是否进入模型可见上下文。"""
    texts = []
    for msg in state.conversation.messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
    return texts


def test_collect_input_transition_advances_step_and_saves(
    fresh_state,
    two_step_plan,
    monkeypatch,
    capsys,
):
    """collect_input 答复落地后应推进 step，并记录为普通 step_input。"""
    from agent.input_resolution import resolve_user_input
    from agent.transitions import apply_user_replied_transition

    calls = _patch_checkpoint_counter(monkeypatch)
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.current_step_index = 0
    fresh_state.task.pending_user_input_request = None

    resolution = resolve_user_input(fresh_state, "旅游出行，舒适型")
    result = apply_user_replied_transition(
        state=fresh_state,
        messages=fresh_state.conversation.messages,
        resolution=resolution,
    )

    assert result.should_continue_loop is True
    assert fresh_state.task.current_step_index == 1
    assert fresh_state.task.status == "running"
    assert calls["save"] >= 1
    assert any("旅游出行，舒适型" in text for text in _step_input_texts(fresh_state))

    out = capsys.readouterr().out
    assert "[INPUT_RESOLUTION] kind=collect_input_answer advance_step=true" in out
    assert "[TRANSITION] awaiting_user_input -> running" in out
    assert "[ACTIONS] append_step_input, advance_step, save_checkpoint" in out


def test_runtime_user_input_transition_keeps_step_clears_pending_and_saves(
    fresh_state,
    two_step_plan,
    monkeypatch,
    capsys,
):
    """执行期求助答复只补当前 step：清 pending，但不推进 step_index。"""
    from agent.input_resolution import resolve_user_input
    from agent.transitions import apply_user_replied_transition

    calls = _patch_checkpoint_counter(monkeypatch)
    pending = {
        "question": "请补充旅行偏好？",
        "why_needed": "用于规划当前步骤",
        "options": [],
    }
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.current_step_index = 0
    fresh_state.task.pending_user_input_request = pending

    resolution = resolve_user_input(fresh_state, "北京出发，高铁，高端酒店")
    result = apply_user_replied_transition(
        state=fresh_state,
        messages=fresh_state.conversation.messages,
        resolution=resolution,
    )

    assert result.should_continue_loop is True
    assert fresh_state.task.current_step_index == 0
    assert fresh_state.task.status == "running"
    assert fresh_state.task.pending_user_input_request is None
    assert calls["save"] >= 1

    texts = _step_input_texts(fresh_state)
    assert any("请补充旅行偏好？" in text for text in texts)
    assert any("北京出发，高铁，高端酒店" in text for text in texts)
    assert any("用于规划当前步骤" in text for text in texts)

    out = capsys.readouterr().out
    assert "[INPUT_RESOLUTION] kind=runtime_user_input_answer advance_step=false" in out
    assert "[TRANSITION] awaiting_user_input -> running" in out
    assert "[ACTIONS] append_step_input_with_question, clear_pending, save_checkpoint" in out


def test_checkpoint_restore_with_pending_resolves_as_runtime_answer(
    fresh_state,
    two_step_plan,
    tmp_path,
    monkeypatch,
):
    """checkpoint 恢复后，pending 仍应驱动 runtime_user_input_answer 语义。"""
    from agent import checkpoint
    from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
    from agent.input_resolution import RUNTIME_USER_INPUT_ANSWER, resolve_user_input
    from agent.state import create_agent_state

    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.current_step_index = 0
    fresh_state.task.pending_user_input_request = {
        "question": "预算是多少？",
        "why_needed": "用于规划",
    }
    save_checkpoint(fresh_state)

    restored = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(restored)

    resolution = resolve_user_input(restored, "3500 元左右")

    assert resolution.kind == RUNTIME_USER_INPUT_ANSWER
    assert resolution.should_advance_step is False


def test_checkpoint_restore_without_pending_resolves_as_collect_answer(
    fresh_state,
    two_step_plan,
    tmp_path,
    monkeypatch,
):
    """checkpoint 恢复后，没有 pending 仍应按 collect_input_answer 处理。"""
    from agent import checkpoint
    from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
    from agent.input_resolution import COLLECT_INPUT_ANSWER, resolve_user_input
    from agent.state import create_agent_state

    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.current_step_index = 0
    fresh_state.task.pending_user_input_request = None
    save_checkpoint(fresh_state)

    restored = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(restored)

    resolution = resolve_user_input(restored, "旅游出行，舒适型")

    assert resolution.kind == COLLECT_INPUT_ANSWER
    assert resolution.should_advance_step is True

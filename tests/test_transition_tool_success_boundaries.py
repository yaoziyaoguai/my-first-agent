"""Tool success and rejected-by-check transition boundary tests.

本文件从原 3000+ 行 v0.4 transition characterization 巨型文件按行为边界拆出。
拆分只改变测试组织，不改变断言语义；这样后续 core / memory / SubAgent
重构时可以局部审查，避免一个历史巨石同时承载所有边界风险。
"""

from __future__ import annotations

import json
from types import SimpleNamespace


def test_tool_outcome_transition_distinguishes_success_failure_rejected_by_check() -> None:
    """slice 4 入口契约：success / failure / rejected_by_check 必须各有去向。

    ``rejected_by_check``（工具内部安全检查拒绝）刻意**不**进 transition——
    它在 fallback 上走 raw display_event_type='tool.rejected'，与 policy
    denial / user rejection 的语义切片保持区分；如果未来有人"顺手"把它
    并进 success，本测试应立刻失败。
    """

    from agent.runtime_events import ToolResultTransitionKind
    from agent.tool_executor import _tool_outcome_transition

    success = _tool_outcome_transition("executed", from_pending_tool=False)
    failure = _tool_outcome_transition("failed", from_pending_tool=False)
    rejected_by_check = _tool_outcome_transition(
        "rejected_by_check", from_pending_tool=False
    )

    assert success is not None
    assert success.reason == ToolResultTransitionKind.TOOL_SUCCESS.value
    assert success.display_events == ("tool.completed",)
    assert success.should_checkpoint is True
    assert success.clear_pending_tool is False
    assert success.advance_step is False

    assert failure is not None
    assert failure.reason == ToolResultTransitionKind.TOOL_FAILURE.value

    # rejected_by_check **必须** 落到 None，让调用方走 raw display_event_type
    # fallback（"tool.rejected"），保留与 policy denial / user rejection 的
    # 语义切片区分；不能被未来 slice 顺手并入 success。
    assert rejected_by_check is None


def test_tool_success_transition_real_path_keeps_protocol_unchanged(
    tmp_path,
    monkeypatch,
) -> None:
    """slice 4 真实路径：execute_single_tool 成功路径现在走 transition。

    模拟边界：
    - 用 monkeypatch 让 execute_tool 直接返回成功字符串，避免真的访问文件
      系统；needs_tool_confirmation 也强制 False，绕过用户确认 UI。
    - 关注的不变量：tool_result 消息照常写入、checkpoint 照常持久化、
      pending_tool 不被本函数改动、display event 是 tool.completed（且
      事实上来自 transition.display_events 而不再是 raw fallback）。
    - 持久化里**不应**出现任何 TransitionResult / RuntimeEventKind /
      ToolResultTransitionKind 字面量——transition 是 Runtime 临时决策
      草案，不允许污染 messages 或 checkpoint。
    """

    import agent.tool_executor as te
    from agent import checkpoint
    from agent.conversation_events import has_tool_result
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "成功读取 5 行内容",
    )

    state = create_agent_state(system_prompt="test")
    state.task.current_step_index = 1
    # pending_tool 与本次成功调用无关；用来证明 success 路径 **不** 误清
    # 不属于自己的 pending（这是 slice 4 与 slice 3 ToolFailure 的对称约束）。
    state.task.pending_tool = {
        "tool_use_id": "unrelated_pending",
        "tool": "write_file",
        "input": {"path": "workspace/other.txt"},
    }
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_success",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    block = SimpleNamespace(
        id="toolu_success",
        name="read_file",
        input={"path": "README.md"},
    )

    assert te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    ) is None

    entry = state.task.tool_execution_log["toolu_success"]
    assert entry["status"] == "executed"
    assert entry["result"] == "成功读取 5 行内容"
    # success 路径不脱敏 input；保持 v0.3 既有 durable 行为（slice 4 不扩边界）。
    assert entry["input"] == {"path": "README.md"}
    assert state.task.current_step_index == 1
    assert state.task.pending_tool == {
        "tool_use_id": "unrelated_pending",
        "tool": "write_file",
        "input": {"path": "workspace/other.txt"},
    }
    assert has_tool_result(state.conversation.messages, "toolu_success")
    # display event 必须是 tool.completed，而且**只**有一条 tool 状态事件
    # （不应同时 emit failed / rejected / user_rejected）。
    completed_events = [
        ev for ev in captured if getattr(ev, "event_type", "") == "tool.completed"
    ]
    assert len(completed_events) == 1
    for forbidden in ("tool.failed", "tool.rejected", "tool.user_rejected"):
        assert not any(
            getattr(ev, "event_type", "") == forbidden for ev in captured
        ), f"success 路径不应 emit {forbidden}"

    # checkpoint 持久化对照：transition 草案对象绝不能进 durable state。
    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("TransitionResult", "RuntimeEventKind", "ToolResultTransitionKind"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint


def test_pending_tool_success_transition_real_path_after_confirmed_execution(
    tmp_path,
    monkeypatch,
) -> None:
    """用户确认后成功执行：execute_pending_tool 也走 ToolSuccess transition。

    模拟边界：
    - 用户输入 'y' 接受 confirmation；execute_tool 被 monkeypatch 成功；
      handler 在外层负责清 pending_tool（slice 4 **不**把这个清理动作搬进
      execute_pending_tool，避免和 slice 6 用户确认迁移交叉）。
    - 不应 emit tool.failed / tool.rejected / tool.user_rejected；
    - tool_result 协议事实由 execute_pending_tool 内的 append_tool_result
      照原样写入；TransitionResult 不能进 messages / checkpoint。
    """

    import agent.confirm_handlers as ch
    import agent.tool_executor as te
    from agent import checkpoint
    from agent.confirm_handlers import ConfirmationContext
    from agent.conversation_events import has_tool_result
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "成功写入 42 字节",
    )

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.current_step_index = 2
    state.task.pending_tool = {
        "tool_use_id": "toolu_pending_success",
        "tool": "write_file",
        "input": {"path": "workspace/ok.txt", "content": "hello"},
    }
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_pending_success",
                    "name": "write_file",
                    "input": {"path": "workspace/ok.txt"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    ctx = ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test-model",
        continue_fn=lambda ts: "continued",
    )

    assert ch.handle_tool_confirmation("y", ctx) == "continued"

    # 既有契约（不属于本 slice）：handler 在外层清 pending、置 status=running。
    assert state.task.pending_tool is None
    assert state.task.status == "running"
    assert state.task.current_step_index == 2
    assert (
        state.task.tool_execution_log["toolu_pending_success"]["status"] == "executed"
    )
    assert has_tool_result(state.conversation.messages, "toolu_pending_success")

    # slice 4 真正钉住的边界：display event 现在来自 transition.display_events，
    # 不再是裸 fallback；同时不能掉进 failed / rejected 的语义桶。
    completed_events = [
        ev for ev in captured if getattr(ev, "event_type", "") == "tool.completed"
    ]
    assert len(completed_events) >= 1
    for forbidden in ("tool.failed", "tool.rejected", "tool.user_rejected"):
        assert not any(
            getattr(ev, "event_type", "") == forbidden for ev in captured
        ), f"pending success 路径不应 emit {forbidden}"

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("TransitionResult", "RuntimeEventKind", "ToolResultTransitionKind"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint


def test_rejected_by_check_real_path_still_uses_fallback_display_event(
    tmp_path,
    monkeypatch,
) -> None:
    """rejected_by_check 不能被 slice 4 误归为 success。

    模拟边界：让 execute_tool 返回工具内部安全检查拒绝的固定前缀
    "拒绝执行：..."（参见 _classify_tool_outcome 里 TOOL_INTERNAL_REJECT_PREFIX
    的语义）。它**不**进 TransitionResult，display event 仍走 raw
    "tool.rejected" fallback；如果未来有人把 rejected_by_check 并进 success
    transition，本测试会立刻失败——避免 slice 4 把一个本应单独治理的
    安全语义偷偷合并掉。
    """

    import agent.tool_executor as te
    from agent import checkpoint
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "拒绝执行：路径不在白名单",
    )

    state = create_agent_state(system_prompt="test")
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_internal_reject",
                    "name": "read_file",
                    "input": {"path": "/etc/passwd"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    block = SimpleNamespace(
        id="toolu_internal_reject",
        name="read_file",
        input={"path": "/etc/passwd"},
    )

    te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    )

    entry = state.task.tool_execution_log["toolu_internal_reject"]
    assert entry["status"] == "rejected_by_check"
    # display event 必须是 fallback 'tool.rejected'，**不**是 'tool.completed'。
    assert any(
        getattr(ev, "event_type", "") == "tool.rejected" for ev in captured
    )
    assert not any(
        getattr(ev, "event_type", "") == "tool.completed" for ev in captured
    )


# ===================== WP-F · tool_result_visible RuntimeEvent 发射契约 =====================


def test_execute_single_tool_emits_tool_result_visible_runtime_event(
    tmp_path,
    monkeypatch,
) -> None:
    """execute_single_tool 成功后必须通过 on_runtime_event 发射 tool_result_visible。

    设计意图：tool_result_visible 是展示层 RuntimeEvent——它不改变 messages 中的
    tool_result 协议、不写 checkpoint、不影响 dispatch。它只是工具执行完成后向
    on_runtime_event 监听者（TUI / CLI / observer）投射一条用户可见摘要。
    这条路径与已有 DisplayEvent（on_display_event）并存，互不替代。
    """
    import agent.tool_executor as te
    from agent import checkpoint
    from agent.display_events import EVENT_TOOL_RESULT_VISIBLE
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "成功执行",
    )

    state = create_agent_state(system_prompt="test")
    state.task.current_step_index = 0
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_001",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                }
            ],
        }
    ]
    display_captured: list[object] = []
    runtime_captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=runtime_captured.append,
        on_display_event=display_captured.append,
    )
    block = SimpleNamespace(
        id="toolu_001",
        name="read_file",
        input={"path": "README.md"},
    )

    te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    )

    visible_events = [e for e in runtime_captured if e.event_type == EVENT_TOOL_RESULT_VISIBLE]
    captured_summary = [(e.event_type, getattr(e, "text", "")[:40]) for e in runtime_captured]
    assert len(visible_events) == 1, (
        f"execute_single_tool 成功后必须发射恰好 1 条 {EVENT_TOOL_RESULT_VISIBLE}，"
        f" 实际 runtime_captured={captured_summary}"
    )
    ev = visible_events[0]
    assert ev.event_type == EVENT_TOOL_RESULT_VISIBLE
    assert "read_file" in str(ev.metadata.get("tool", ""))
    assert ev.metadata.get("status") == "executed"


def test_execute_single_tool_omits_runtime_event_when_no_sink(tmp_path, monkeypatch) -> None:
    """on_runtime_event 为 None 时不应崩溃——向后兼容无 RuntimeEvent sink 的调用方。"""
    import agent.tool_executor as te
    from agent import checkpoint
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)
    monkeypatch.setattr(te, "execute_tool", lambda name, inp, context=None: "OK")

    state = create_agent_state(system_prompt="test")
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "read_file", "input": {}}
            ],
        }
    ]
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=lambda e: None,
    )
    block = SimpleNamespace(id="t1", name="read_file", input={})
    # 不应抛异常
    result = te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    )
    assert result is None

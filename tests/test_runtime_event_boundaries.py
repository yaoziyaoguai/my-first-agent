"""Runtime 事件边界 invariant 测试（v0.2 M2）。

本文件保护 `docs/RUNTIME_EVENT_BOUNDARIES.md` §3 红线条款。它和 M1 的
`tests/test_runtime_state_machine_invariants.py` 互补：

- M1 invariants 关注「持久状态 vs 临时类型」的 schema 边界。
- M2 invariants 关注「输入分类 / 输出投影 / 协议投影 / 观测日志」这四条
  Runtime 通道之间不能互相串线。

如果未来某条 invariant 失败，请先回到 RUNTIME_EVENT_BOUNDARIES.md 确认是否
在变更 M2 显式契约；如果确实要变，请同步更新 spec 而不是默默放宽测试。
"""

from __future__ import annotations

import copy
import importlib

import pytest

from agent.state import create_agent_state


# ---------------------------------------------------------------------------
# 1. 临时事件类型必须 frozen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "module_name,class_name",
    [
        ("agent.input_intents", "InputIntent"),
        ("agent.input_resolution", "InputResolution"),
        ("agent.transitions", "TransitionResult"),
        ("agent.runtime_events", "TransitionResult"),
        ("agent.display_events", "DisplayEvent"),
        ("agent.display_events", "RuntimeEvent"),
    ],
)
def test_runtime_ephemeral_dataclasses_are_frozen(module_name, class_name):
    """临时事件 dataclass 必须 frozen，防止 handler 把它们当可变状态缓存。

    一旦事件对象可变，「输入分类 / 输出投影 → 状态机决策」就会出现隐式回路：
    handler 在事件上挂字段当中转变量，下次别人读到「事件 → 实际状态」分叉。
    冻结是最便宜的边界保护。
    """
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    params = getattr(cls, "__dataclass_params__", None)
    assert params is not None, f"{class_name} 不是 dataclass"
    assert params.frozen, f"{class_name} 必须 frozen=True 以保护事件边界"


# ---------------------------------------------------------------------------
# 2. 临时事件模块不暴露持久化入口
# ---------------------------------------------------------------------------

def test_event_modules_do_not_expose_persistence_hooks():
    """RuntimeEvent / DisplayEvent / InputIntent / InputResolution /
    TransitionResult / model_output_resolution 都是临时通道，不能提供
    save_checkpoint / persist / dump_to_state / to_checkpoint 等持久化接口。

    这条 assert 是 M1 同名 invariant 的扩展：M1 关注「不能写 checkpoint」，
    M2 进一步禁止暴露**任何**显式持久化命名，避免后人「我只是搬了一个
    `to_dict`，结果手就滑到了 `to_checkpoint`」。
    """
    forbidden = {"save_checkpoint", "persist", "dump_to_state", "to_checkpoint"}
    modules_to_check = [
        "agent.input_intents",
        "agent.input_resolution",
        "agent.transitions",
        "agent.runtime_events",
        "agent.display_events",
        "agent.model_output_resolution",
    ]

    for module_name in modules_to_check:
        module = importlib.import_module(module_name)
        leaked = set(dir(module)) & forbidden
        assert not leaked, (
            f"{module_name} 暴露了持久化入口 {leaked}；事件 / 输入分类层"
            " 不能拥有 checkpoint 写入能力。"
        )


# ---------------------------------------------------------------------------
# 3. emit_display_event / runtime_observer.log_* 不修改 state
# ---------------------------------------------------------------------------

def _state_snapshot(state):
    """对 state 做深 copy 比较快照，专门用来做「调用前后等价」的等价判定。"""
    return {
        "task": copy.deepcopy(state.task.__dict__),
        "memory": copy.deepcopy(state.memory.__dict__),
        "messages": copy.deepcopy(state.conversation.messages),
        "tool_traces": copy.deepcopy(state.conversation.tool_traces),
    }


def test_emit_display_event_does_not_mutate_state(capsys):
    """DisplayEvent 投递必须只是「给 UI sink 一份只读 payload」。

    sink=None 时 `emit_display_event` 走 stdout fallback，但仍然不能动任何
    state 字段。capsys 顺手验证它确实写了 stdout（避免 import 后 fallback
    被偷偷砍掉而不被发现）。
    """
    from agent.display_events import DisplayEvent, emit_display_event

    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "目标"
    state.conversation.messages = [{"role": "user", "content": "hi"}]
    before = _state_snapshot(state)

    event = DisplayEvent(
        event_type="control.message",
        title="提示",
        body="任务即将开始",
    )
    emit_display_event(None, event)

    after = _state_snapshot(state)
    assert before == after, "emit_display_event 不应修改任何 state 字段"
    captured = capsys.readouterr()
    assert "任务即将开始" in captured.out


def test_runtime_observer_log_event_does_not_mutate_state(monkeypatch, tmp_path):
    """runtime_observer 的 log_event / log_resolution 都是观测日志通道，
    任何调用都不能修改 state。

    使用 tmp_path 把 agent_log.jsonl 重定向到临时目录，避免污染仓库根目录的
    log 文件。
    """
    from agent import runtime_observer
    from agent import logger as agent_logger

    monkeypatch.setattr(agent_logger, "LOG_FILE", tmp_path / "agent_log.jsonl")

    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    state.conversation.messages = [{"role": "user", "content": "hi"}]
    before = _state_snapshot(state)

    runtime_observer.log_event(
        "tool.requested",
        event_source="tests",
        event_payload={"tool": "x"},
    )
    runtime_observer.log_transition(
        from_state="awaiting_user_input",
        event_type="user.replied",
        target_state="running",
    )
    runtime_observer.log_actions(["clear_pending_user_input", "save_checkpoint"])

    after = _state_snapshot(state)
    assert before == after, "runtime_observer.log_* 不应修改任何 state 字段"


# ---------------------------------------------------------------------------
# 4. RuntimeEvent / DisplayEvent renderer 不修改事件本身
# ---------------------------------------------------------------------------

def test_render_runtime_event_for_cli_is_pure():
    """RuntimeEvent → CLI 文本是单向投影，不能修改事件。"""
    from agent.display_events import (
        DisplayEvent,
        RuntimeEvent,
        render_runtime_event_for_cli,
    )

    display = DisplayEvent(
        event_type="tool.requested",
        title="工具",
        body="即将执行",
        metadata={"tool": "echo"},
    )
    runtime_event = RuntimeEvent(
        event_type="display.event",
        display_event=display,
        metadata={"k": "v"},
    )

    text = render_runtime_event_for_cli(runtime_event)
    assert "工具" in text and "即将执行" in text

    # frozen dataclass 防止 renderer 修改字段；即便如此，再 assert metadata 内容
    # 没被悄悄替换（避免有人未来用 object.__setattr__ 绕开 frozen）。
    assert runtime_event.metadata == {"k": "v"}
    assert display.metadata == {"tool": "echo"}


# ---------------------------------------------------------------------------
# 5. conversation.messages 写入只走 append_* 入口
# ---------------------------------------------------------------------------

def test_conversation_events_writers_are_append_only():
    """`append_control_event` / `append_tool_result` 必须只 append 到末尾，
    不修改已有 message 对象身份和内容。

    这是 M1 「user_replied transition append-only」的扩展：直接验证
    conversation_events.py 的两个底层 append helper 也维持 append-only。
    """
    from agent.conversation_events import append_control_event, append_tool_result

    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "T1", "name": "echo", "input": {}},
        ]},
    ]
    snapshot_ids = [id(m) for m in msgs]
    snapshot_eq = copy.deepcopy(msgs)

    append_tool_result(msgs, "T1", "1")
    append_control_event(msgs, "step_input", {"content": "answer"})

    # 已有两条对象身份和内容都不变。
    for idx, snap_id in enumerate(snapshot_ids):
        assert id(msgs[idx]) == snap_id
        assert msgs[idx] == snapshot_eq[idx]
    # 新增追加在末尾。
    assert len(msgs) == len(snapshot_ids) + 2


# ---------------------------------------------------------------------------
# 6. CommandResult 已退役 - 不允许在事件层重新出现
# ---------------------------------------------------------------------------

def test_command_result_is_not_reintroduced_in_event_layer():
    """slash-command 时代的 CommandResult 已整体下线（commit 205c4cf）。

    M2 文档化它作为「禁止复活路径」：未来任何命令调度结果对象都必须先走
    spec 评审，不允许在 input_intents / display_events / transitions /
    runtime_observer 等事件层模块直接复活同名类型；否则 InputIntent /
    RuntimeEvent / 状态机三层的边界会被默默打穿。
    """
    forbidden_class = "CommandResult"
    modules_to_check = [
        "agent.input_intents",
        "agent.input_resolution",
        "agent.transitions",
        "agent.display_events",
        "agent.runtime_observer",
        "agent.model_output_resolution",
    ]
    for module_name in modules_to_check:
        module = importlib.import_module(module_name)
        assert not hasattr(module, forbidden_class), (
            f"{module_name} 重新引入了已退役的 {forbidden_class}；如确需新设"
            " 命令结果对象，请先走 spec 评审，不要在事件层直接复活。"
        )

"""Runtime 状态机架构边界 invariant 测试（v0.2 M1）。

本文件不做行为单测——`tests/test_state_invariants.py` 已经覆盖 reset_task /
status helper，`tests/test_checkpoint_roundtrip.py` 已经覆盖 save/load 字段
回归。这里只保护**架构边界**：

1. checkpoint 持久 schema 与 RuntimeEvent / InputIntent / DisplayEvent /
   TransitionResult / InputResolution 这些临时类型严格隔离。
2. `pending_tool` 与 `pending_user_input_request` 是两个**互不干扰**的子状态
   字段，不能被合并、不能被互写。
3. `apply_user_replied_transition` 对 `conversation.messages` 是 append-only。
4. `context_builder._project_to_api` 是纯投影，不修改入参。
5. checkpoint roundtrip 后 task 字段类型仍是 dataclass 声明的基础类型，
   不会因为「有人误把事件对象塞进去」就把 dict / list 字段污染成
   RuntimeEvent / InputIntent / CommandResult。

如果未来某个 PR 让这些 invariant 失败，请先回到 `docs/RUNTIME_STATE_MACHINE.md`
确认是否在改动 v0.2 M1 显式契约；如果确实要变，请同步更新该 spec 文档而不是
默默放宽测试。
"""

from __future__ import annotations

import json
from dataclasses import fields

import pytest

from agent.state import TaskState, ConversationState, create_agent_state


@pytest.fixture
def tmp_checkpoint_path(tmp_path, monkeypatch):
    """复用 test_checkpoint_roundtrip 的隔离手法：把 CHECKPOINT_PATH 指向 tmp。"""
    from agent import checkpoint

    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    return path


# ---------------------------------------------------------------------------
# 1. checkpoint 顶层 schema 白名单
# ---------------------------------------------------------------------------

def test_checkpoint_top_level_keys_are_persistent_only(tmp_checkpoint_path):
    """checkpoint JSON 顶层 key 集合必须 = {meta, task, memory, conversation}。

    这条 invariant 防止以后有人把 RuntimeState、display_events 队列、
    runtime_observer 缓冲、tool_traces 等 UI/观测层对象悄悄写进 checkpoint。
    新增持久层时请先更新 `docs/RUNTIME_STATE_MACHINE.md` §1.1 + §7。
    """
    from agent.checkpoint import save_checkpoint

    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    save_checkpoint(state, source="tests.invariants.top_keys")

    payload = json.loads(tmp_checkpoint_path.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {"meta", "task", "memory", "conversation"}, (
        f"checkpoint 顶层 key 必须严格匹配白名单，实际：{sorted(payload.keys())}"
    )


def test_checkpoint_task_keys_are_subset_of_taskstate_fields(tmp_checkpoint_path):
    """checkpoint 的 task 段不能出现 TaskState 之外的字段。

    `_copy_state_dict(state.task)` 走 `__dict__`，dataclass 字段以外的临时
    monkey-patch 也会被持久化。这条 invariant 让「漏 reset」之外再多一条
    「漏字段定义」防护。
    """
    from agent.checkpoint import save_checkpoint

    state = create_agent_state(system_prompt="test")
    save_checkpoint(state, source="tests.invariants.task_keys")

    payload = json.loads(tmp_checkpoint_path.read_text(encoding="utf-8"))
    task_keys = set(payload["task"].keys())
    declared = {f.name for f in fields(TaskState)}
    extra = task_keys - declared
    assert not extra, (
        f"checkpoint task 出现 TaskState dataclass 之外的字段：{extra}。"
        " 请先更新 TaskState dataclass 与 RUNTIME_STATE_MACHINE.md §1.1。"
    )


def test_checkpoint_conversation_only_persists_messages(tmp_checkpoint_path):
    """`conversation.tool_traces` 是会话分析层数据，不在恢复语义内。

    如果以后要持久化分析数据，请单独走 memory 通道；checkpoint 的
    conversation 段只存 messages（投影到 Anthropic API 的事实源）。
    """
    from agent.checkpoint import save_checkpoint

    state = create_agent_state(system_prompt="test")
    state.conversation.tool_traces.append({"tool": "x", "input": {}, "result": "r"})
    save_checkpoint(state, source="tests.invariants.conv_keys")

    payload = json.loads(tmp_checkpoint_path.read_text(encoding="utf-8"))
    assert set(payload["conversation"].keys()) == {"messages"}, (
        "conversation 段只允许存 messages；tool_traces 等分析字段不能进 checkpoint。"
    )


# ---------------------------------------------------------------------------
# 2. pending_tool / pending_user_input_request 字段独立性
# ---------------------------------------------------------------------------

def test_pending_tool_and_pending_user_input_are_independent_fields():
    """TaskState 上两者必须是独立 dataclass 字段，不能被合并成一个 union。

    它们的子状态边界完全不同：pending_tool 由 awaiting_tool_confirmation 拥有，
    pending_user_input_request 由 awaiting_user_input / awaiting_feedback_intent
    拥有。合并会让恢复语义和 UI 重放变得无法区分。
    """
    declared = {f.name for f in fields(TaskState)}
    assert "pending_tool" in declared
    assert "pending_user_input_request" in declared

    task = TaskState()
    assert task.pending_tool is None
    assert task.pending_user_input_request is None
    # 两者可以独立赋值与独立清零，互不影响。
    task.pending_tool = {"tool_use_id": "T", "tool": "x", "input": {}}
    task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "?",
    }
    task.pending_tool = None
    assert task.pending_user_input_request is not None
    task.pending_user_input_request = None
    assert task.pending_tool is None


# ---------------------------------------------------------------------------
# 3. apply_user_replied_transition 对 messages append-only
# ---------------------------------------------------------------------------

def test_apply_user_replied_transition_is_append_only_on_messages(
    tmp_checkpoint_path,
):
    """transition 只能在 messages 末尾追加，不能修改/删除已有项。

    `state.conversation.messages` 是 _project_to_api 的事实源，也是 checkpoint
    持久内容。任何在 transition 层重写历史的行为都会破坏 Anthropic 协议
    （tool_use ↔ tool_result 配对）和恢复语义。
    """
    from agent.input_resolution import RUNTIME_USER_INPUT_ANSWER, InputResolution
    from agent.transitions import apply_user_replied_transition

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "预算？",
        "why_needed": "用于继续",
    }
    initial_messages = [
        {"role": "user", "content": "目标 A"},
        {"role": "assistant", "content": "好的，正在规划"},
    ]
    state.conversation.messages = list(initial_messages)
    snapshot_ids = [id(m) for m in state.conversation.messages]

    resolution = InputResolution(
        kind=RUNTIME_USER_INPUT_ANSWER,
        content="3500",
        pending_user_input_request=state.task.pending_user_input_request,
    )
    result = apply_user_replied_transition(
        state=state,
        messages=state.conversation.messages,
        resolution=resolution,
    )

    assert result.should_continue_loop is True
    # 已有的两条不能被修改或换对象。
    assert len(state.conversation.messages) >= len(initial_messages) + 1
    for idx, snap_id in enumerate(snapshot_ids):
        assert id(state.conversation.messages[idx]) == snap_id, (
            f"index {idx} 的 message 被换了对象，违反 append-only 契约"
        )
        assert state.conversation.messages[idx] == initial_messages[idx]
    # 状态推进到 running 且 pending 已清。
    assert state.task.status == "running"
    assert state.task.pending_user_input_request is None


# ---------------------------------------------------------------------------
# 4. _project_to_api 是纯投影
# ---------------------------------------------------------------------------

def test_project_to_api_does_not_mutate_input():
    """_project_to_api 必须返回新 list，且不修改入参对象。

    它是「内部 messages → Anthropic 协议合规 messages」的只读投影，承担重排/
    合并/清理元工具 tool_use 的工作；如果它修改 state.conversation.messages，
    后续 checkpoint 与下一轮 projection 会出现不可预测的状态污染。
    """
    from agent.context_builder import _project_to_api

    raw_messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "id": "T1", "name": "echo", "input": {"x": 1}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "T1", "content": "1"},
            ],
        },
    ]
    snapshot = [m for m in raw_messages]
    snapshot_ids = [id(m) for m in raw_messages]

    projected = _project_to_api(raw_messages)

    assert projected is not raw_messages, "_project_to_api 应返回新 list 对象"
    assert len(raw_messages) == len(snapshot)
    for idx, snap_id in enumerate(snapshot_ids):
        assert id(raw_messages[idx]) == snap_id, (
            f"index {idx} 入参对象被替换，_project_to_api 不能修改输入"
        )
        assert raw_messages[idx] == snapshot[idx]


# ---------------------------------------------------------------------------
# 5. checkpoint roundtrip 后 task 字段类型仍是基础类型
# ---------------------------------------------------------------------------

def test_checkpoint_roundtrip_keeps_task_field_basic_types(tmp_checkpoint_path):
    """load 后 task 字段类型必须落在 dataclass 声明的基础类型范围内。

    防止「有人在 task 字段塞 RuntimeEvent / InputIntent / CommandResult / dataclass
    实例」之后，roundtrip 让损坏类型偷偷固化。我们检查所有非 None 字段都是
    JSON 可表达的基础类型（bool/int/float/str/list/dict）。
    """
    from agent.checkpoint import load_checkpoint_to_state, save_checkpoint

    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "目标"
    src.task.current_plan = {"goal": "g", "steps": [{"title": "s1"}]}
    src.task.status = "awaiting_user_input"
    src.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "?",
    }
    src.task.tool_execution_log = {"T0": {"tool": "x", "input": {}, "result": "r"}}
    save_checkpoint(src, source="tests.invariants.roundtrip_types")

    dst = create_agent_state(system_prompt="other")
    assert load_checkpoint_to_state(dst)

    allowed_types = (bool, int, float, str, list, dict)
    for f in fields(TaskState):
        value = getattr(dst.task, f.name)
        if value is None:
            continue
        assert isinstance(value, allowed_types), (
            f"task.{f.name} roundtrip 后类型 {type(value).__name__} 不在 JSON 基础"
            " 类型白名单内；这通常意味着有人把 RuntimeEvent / InputIntent / "
            "dataclass 实例塞进了 task 字段。"
        )


# ---------------------------------------------------------------------------
# 6. 临时类型不导出 checkpoint 写入入口（架构边界负向 assert）
# ---------------------------------------------------------------------------

def test_runtime_ephemeral_modules_do_not_expose_persistence_hooks():
    """RuntimeEvent / InputIntent / InputResolution / TransitionResult / DisplayEvent
    都是临时对象，所在模块绝对不能提供 save_checkpoint / persist / dump_to_state
    等持久化接口。

    这是一条架构边界 assert：不是测某个函数行为，而是禁止某些函数在这些模块
    内出现。如果未来要为这些类型加序列化能力（例如离线分析），请单独建模块，
    不要污染输入分类 / 输出渲染层。
    """
    forbidden = {"save_checkpoint", "persist", "dump_to_state", "to_checkpoint"}
    modules_to_check = [
        "agent.input_intents",
        "agent.input_resolution",
        "agent.transitions",
        "agent.display_events",
        "agent.model_output_resolution",
    ]
    import importlib

    for module_name in modules_to_check:
        module = importlib.import_module(module_name)
        exported = set(dir(module))
        leaked = exported & forbidden
        assert not leaked, (
            f"{module_name} 暴露了持久化入口 {leaked}；临时事件/输入分类层"
            " 不能拥有 checkpoint 写入能力。"
        )


def test_conversation_state_messages_is_only_persistent_field():
    """ConversationState dataclass 上 messages 之外的字段都是「分析层 / 临时」。

    如果以后给 ConversationState 加新字段，必须显式判断它是否进 checkpoint：
    - 进 checkpoint：扩展 `_build_checkpoint_from_state` 的 conversation 段，
      并更新 `test_checkpoint_conversation_only_persists_messages` 的断言。
    - 不进 checkpoint：保持现状，无需改 checkpoint 逻辑。
    """
    declared = {f.name for f in fields(ConversationState)}
    # 当前 v0.2 M1 已知字段：messages（持久）+ tool_traces（分析层，不持久）。
    assert "messages" in declared
    assert "tool_traces" in declared

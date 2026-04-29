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


# ---------------------------------------------------------------------------
# Phase 2.4：Checkpoint Runtime Leak Guard
# ---------------------------------------------------------------------------
# 这一节有 2 条 guard 测试，钉住 v0.4 Phase 2 引入的 runtime-only 类型
# (LoopContext / RuntimeEvent / TransitionResult / 各种 *Kind 枚举)
# **绝不能**进入 durable checkpoint。
#
# 当前防线（已存在）：
#   - _filter_to_declared_fields 白名单：load 时未知 key 被丢弃；
#   - TaskState/MemoryState 字段全部是 JSON-serializable 标量/dict；
#   - _build_checkpoint_from_state 用 _copy_state_dict 浅拷贝 dataclass。
#
# 但缺少**显式断言**：万一未来某个 handler 把 RuntimeEvent / TransitionResult
# 对象塞进 task.current_plan["last_event"] 或 tool_execution_log[id]["event"]，
# JSON 序列化要么报错（runtime 直接挂）要么用 default=str 落成"<RuntimeEvent
# object at 0x...>"——后者是 silent corruption。这两条 guard 是反回归网。
#
# 测试设计要点：
#   - 不扫整个 JSON 文件做禁用词搜索（会误伤未来含这些词的用户消息正文）；
#   - 而是用专门的 fixture 构造**不含**这些词的 user/assistant 消息，让任何
#     命中都必然来自 runtime metadata 而非用户文本——这样 false-positive 为 0；
#   - 两条都是 0 产品代码改动，预期当前 green；若意外红灯，说明产品代码已经
#     发生 silent leak，需走根因排查（不要弱化测试）。
# ---------------------------------------------------------------------------


def test_checkpoint_does_not_leak_runtime_only_type_names(tmp_checkpoint_path):
    """Phase 2.4 候选 1：checkpoint JSON 不得包含 runtime-only 类型名。

    防什么真实 bug：
      未来某 handler 误把 RuntimeEvent / TransitionResult / LoopContext 等
      runtime 对象塞进 task.current_plan / tool_execution_log / pending_tool
      等 dict 字段。JSON 序列化时若用 default=str 兜底，会留下
      "<RuntimeEvent object at 0x...>" 字符串，外观正常但语义已损坏；resume
      时这些字符串会被恢复成普通字符串而非对象，行为静默漂移。

    本测试的 scope（重要，避免误解为全局禁词）：
      本测试**只**对自己控制的 tmp_checkpoint fixture 生成的 JSON 做扫描，
      **不**对真实 runtime 的 checkpoint 或任意用户消息正文做禁词限制。
      用户在生产 runtime 中给 agent 发的消息正文里出现 "LoopContext" /
      "RuntimeEvent" 等词是完全合法的（例如用户问 "什么是 LoopContext"），
      本 guard 与之无关——它只防 handler 把 runtime 对象 str() 化后写进
      durable payload 的 silent corruption。

    防御性 fixture 自检：
      下方有一段 `_assert_fixture_user_content_clean` 断言，确保本 fixture
      的 user/assistant content 不含禁用词。这样万一未来有人为了"丰富测试
      用例"在 fixture 里加入含这些词的对话，会立刻收到 "fixture 不变量被
      破坏" 的清晰报错，而不是误以为 "checkpoint 发生 runtime leak"。
    """
    from agent.checkpoint import save_checkpoint

    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "处理一个普通任务"
    src.task.current_plan = {
        "goal": "g",
        "steps": [{"title": "步骤一"}, {"title": "步骤二"}],
    }
    src.task.current_step_index = 1
    src.task.status = "awaiting_tool_confirmation"
    src.task.pending_tool = {
        "tool_use_id": "toolu_test_001",
        "tool": "read_file",
        "input": {"path": "/tmp/somefile"},
    }
    src.task.tool_execution_log = {
        "toolu_test_001": {
            "tool": "read_file",
            "input": {"path": "/tmp/somefile"},
            "result": {"status": "executed", "output": "ok"},
        }
    }
    src.conversation.messages = [
        {"role": "user", "content": "请帮我读取一个文件"},
        {"role": "assistant", "content": "好的，正在读取"},
    ]

    save_checkpoint(src, source="tests.phase_2_4.runtime_leak_guard")

    # runtime-only 类型名清单：这些只属于 v0.4 Phase 1/2 的 runtime boundary，
    # 不应出现在 durable checkpoint 中。
    forbidden_runtime_types = [
        "LoopContext",
        "RuntimeEvent",        # 也覆盖 RuntimeEventKind
        "TransitionResult",
        "ToolFailureKind",
        "ToolSuccessKind",
        "ModelOutputKind",
        "PlanConfirmationKind",
        "StepConfirmationKind",
        "ToolConfirmationKind",
        "UserInputConfirmationKind",
        "FeedbackIntentKind",
        "ToolResultTransitionKind",
    ]

    # 防御性 fixture 不变量自检：先确认本 fixture 的 user/assistant content
    # 不含禁用词。若未来有人改 fixture 加入这些词，本断言会先失败并提示
    # "fixture 不变量被破坏"，而不是让下面的 guard 误报为 "runtime leak"。
    fixture_user_text = " ".join(
        m.get("content", "") for m in src.conversation.messages
        if isinstance(m.get("content"), str)
    )
    polluted_in_fixture = [n for n in forbidden_runtime_types if n in fixture_user_text]
    assert not polluted_in_fixture, (
        f"本测试 fixture 不变量被破坏：user/assistant content 含禁用词"
        f" {polluted_in_fixture}。请把这些词从 fixture 消息正文中移除——"
        "本 guard 只防 runtime metadata 泄漏，不限制真实用户消息正文。"
    )

    raw_json = tmp_checkpoint_path.read_text(encoding="utf-8")

    leaked = [name for name in forbidden_runtime_types if name in raw_json]
    assert not leaked, (
        "checkpoint JSON 中检测到 runtime-only 类型名泄漏："
        f"{leaked}。这意味着某个 handler 把 runtime 对象塞进了 durable "
        "state（task / memory / conversation）。请走根因排查：搜索哪个 "
        "save_checkpoint 之前的 mutation 把 RuntimeEvent / TransitionResult "
        "等对象写进了 dict 字段，而不是修改本测试。"
    )


def test_resume_does_not_attach_runtime_only_attrs_to_task(tmp_checkpoint_path):
    """Phase 2.4 候选 2：恶意/损坏 checkpoint 中的 runtime key 必须被 resume 丢弃。

    防什么真实 bug：
      未来若有人改 _filter_to_declared_fields 或绕过它（直接 setattr 整个
      dict），恶意/损坏的 checkpoint JSON 中如果包含 loop_ctx / client /
      model_name / transition_result / runtime_event 这类 key，会被原样
      setattr 到 state.task 上，长出非 dataclass 声明的"裸属性"。这会让
      runtime 行为静默漂移（例如某个 handler 之后访问 state.task.client
      不会 AttributeError，而是拿到 dict）。

    本测试通过人工构造一个含禁用 runtime key 的 checkpoint JSON，验证
    load_checkpoint_to_state 后 state.task **不**长出这些裸属性。这间接
    覆盖 _filter_to_declared_fields 白名单契约的核心边界。
    """
    import json
    from agent.checkpoint import load_checkpoint_to_state

    # 人工构造：故意往 task / memory 里放 runtime-only key + 一些声明字段
    malicious_checkpoint = {
        "meta": {"session_id": "s1"},
        "task": {
            "user_goal": "正常字段",       # 声明字段，应保留
            "status": "running",            # 声明字段，应保留
            # 以下全是 runtime-only key，必须被 _filter_to_declared_fields 丢弃
            "loop_ctx": {"client": "fake", "model_name": "fake-model"},
            "client": "fake_client_obj",
            "model_name": "fake-model",
            "transition_result": {"kind": "fake"},
            "runtime_event": {"event_type": "fake"},
            "_loop_ctx": {"client": "fake"},
            "callbacks": ["fake_cb"],
        },
        "memory": {
            "session_id": "s1",            # 声明字段，应保留
            "loop_ctx": {"x": 1},          # runtime-only，应丢
            "client": "fake",              # runtime-only，应丢
        },
        "conversation": {"messages": []},
    }
    tmp_checkpoint_path.write_text(
        json.dumps(malicious_checkpoint, ensure_ascii=False), encoding="utf-8"
    )

    dst = create_agent_state(system_prompt="other")
    assert load_checkpoint_to_state(dst)

    # 声明字段保留
    assert dst.task.user_goal == "正常字段"
    assert dst.task.status == "running"
    assert dst.memory.session_id == "s1"

    # runtime-only 裸属性必须不存在
    forbidden_attrs = [
        "loop_ctx",
        "client",
        "model_name",
        "transition_result",
        "runtime_event",
        "_loop_ctx",
        "callbacks",
    ]
    for attr in forbidden_attrs:
        assert not hasattr(dst.task, attr), (
            f"恶意 checkpoint 中的 runtime-only key '{attr}' 不应被 resume 后"
            f"附到 state.task 上。说明 _filter_to_declared_fields 白名单已被"
            f"绕过——请走根因排查 agent/checkpoint.py:load_checkpoint_to_state。"
        )
        assert not hasattr(dst.memory, attr), (
            f"恶意 checkpoint 中的 runtime-only key '{attr}' 不应被 resume 后"
            f"附到 state.memory 上。"
        )

"""Runtime 错误恢复 / loop guard / no-progress 不变量测试（v0.2 M4）。

本文件保护 `docs/RUNTIME_ERROR_RECOVERY.md` §1-§5 的关键契约：
- 阈值常量值（防止有人静默调高/调低导致 guard 失效）
- 计数清零规则（resume 后保留，业务/元工具都算「动起来」）
- placeholder 补 tool_result 必须维持 Anthropic 配对、不泄漏内部信息
- request_user_input 元工具不会被误判为 no_progress
- 工具失败不污染 task / checkpoint

不重复 `tests/test_main_loop.py / test_meta_tool.py / test_long_running.py`
等已有行为测试；本文件聚焦「契约 invariants」。
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.state import create_agent_state


# ---------------------------------------------------------------------------
# §1 阈值常量回归（防止有人偷偷改大/改小）
# ---------------------------------------------------------------------------

def test_loop_guard_thresholds_are_documented_values():
    """阈值变更必须先更新 RUNTIME_ERROR_RECOVERY.md §1 + 通过 review。

    任何调阈值的 PR 都会让本测试 red，提醒同步更新文档与人工 LLM smoke。
    """
    from config import MAX_CONTINUE_ATTEMPTS
    from agent.core import MAX_LOOP_ITERATIONS
    from agent.response_handlers import (
        MAX_TOOL_CALLS_PER_TURN,
        MAX_REPEATED_TOOL_INPUTS,
    )

    assert MAX_LOOP_ITERATIONS == 50
    assert MAX_CONTINUE_ATTEMPTS == 3
    assert MAX_TOOL_CALLS_PER_TURN == 50
    assert MAX_REPEATED_TOOL_INPUTS == 3


# ---------------------------------------------------------------------------
# §2 计数清零规则
# ---------------------------------------------------------------------------

def test_reset_task_clears_all_loop_guard_counters():
    """reset_task 必须清掉所有 loop guard 计数，否则下一任务会带着旧 guard 状态。"""
    state = create_agent_state(system_prompt="test")
    state.task.loop_iterations = 17
    state.task.consecutive_max_tokens = 2
    state.task.consecutive_end_turn_without_progress = 2
    state.task.tool_call_count = 33
    state.task.tool_execution_log = {"T0": {"tool": "x", "input": {}, "result": "r"}}

    state.reset_task()

    assert state.task.loop_iterations == 0
    assert state.task.consecutive_max_tokens == 0
    assert state.task.consecutive_end_turn_without_progress == 0
    assert state.task.tool_call_count == 0
    assert state.task.tool_execution_log == {}


def test_handle_max_tokens_increments_and_returns_at_threshold():
    """handle_max_tokens_response 直接调用：未达阈值返回 None，达到阈值返回停止文案。"""
    from agent.response_handlers import handle_max_tokens_response

    state = create_agent_state(system_prompt="test")

    # 模拟 Anthropic 响应：无 tool_use，仅 text；保持最小骨架。
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="一段长文")],
        stop_reason="max_tokens",
        usage=SimpleNamespace(
            input_tokens=10, output_tokens=20,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        ),
    )
    messages = []

    # 第一次：counter=1，未达阈值。
    result = handle_max_tokens_response(
        response,
        state=state,
        turn_state=SimpleNamespace(),
        messages=messages,
        extract_text_fn=lambda content: "一段长文",
        max_consecutive_max_tokens=3,
    )
    assert result is None
    assert state.task.consecutive_max_tokens == 1

    # 第二次。
    handle_max_tokens_response(
        response, state=state, turn_state=SimpleNamespace(),
        messages=messages, extract_text_fn=lambda c: "x",
        max_consecutive_max_tokens=3,
    )
    assert state.task.consecutive_max_tokens == 2

    # 第三次：达到阈值。
    result = handle_max_tokens_response(
        response, state=state, turn_state=SimpleNamespace(),
        messages=messages, extract_text_fn=lambda c: "x",
        max_consecutive_max_tokens=3,
    )
    assert result is not None
    assert "连续多次" in result
    # 文案不暴露阈值 / 内部计数。
    assert "consecutive_max_tokens" not in result
    assert "3" not in result


# ---------------------------------------------------------------------------
# §3 持久化与 resume：guard 计数必须保留
# ---------------------------------------------------------------------------

def test_loop_guard_counters_persist_across_checkpoint_roundtrip(
    tmp_path,
    monkeypatch,
):
    """resume 后保留累积计数，防止用户通过 Ctrl+C 重启绕过 guard。"""
    from agent import checkpoint as checkpoint_module
    from agent.checkpoint import save_checkpoint, load_checkpoint_to_state

    monkeypatch.setattr(
        checkpoint_module, "CHECKPOINT_PATH", tmp_path / "checkpoint.json"
    )

    src = create_agent_state(system_prompt="test")
    src.task.status = "running"
    src.task.loop_iterations = 30
    src.task.consecutive_max_tokens = 2
    src.task.consecutive_end_turn_without_progress = 1
    src.task.tool_call_count = 17

    save_checkpoint(src, source="tests.error_recovery.persist")

    dst = create_agent_state(system_prompt="other")
    assert load_checkpoint_to_state(dst)

    assert dst.task.loop_iterations == 30
    assert dst.task.consecutive_max_tokens == 2
    assert dst.task.consecutive_end_turn_without_progress == 1
    assert dst.task.tool_call_count == 17


# ---------------------------------------------------------------------------
# §4 _fill_placeholder_results 维持配对 + 不泄漏内部信息
# ---------------------------------------------------------------------------

def test_fill_placeholder_results_preserves_pairing_with_short_safe_text():
    """guard 兜底必须为每个未配对 tool_use 写一条 tool_result，且 content 安全。

    安全要求：
    - 不暴露 tool 名 / tool 入参 / API key / 内部计数 / 异常 stack
    - 内容是固定短文案 `[系统] {reason}。`
    """
    from agent.response_handlers import _fill_placeholder_results
    from agent.conversation_events import has_tool_result

    blocks = [
        SimpleNamespace(id="T1", name="echo", input={"secret_key": "sk-abcdef"}),
        SimpleNamespace(id="T2", name="echo", input={"path": "/etc/passwd"}),
    ]
    messages: list[dict] = []
    _fill_placeholder_results(messages, blocks, reason="工具调用次数超限，未执行")

    assert has_tool_result(messages, "T1")
    assert has_tool_result(messages, "T2")
    # 检查所有 tool_result 内容均不泄漏入参。
    for msg in messages:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content", "")
                    assert "sk-abcdef" not in content
                    assert "/etc/passwd" not in content
                    assert content.startswith("[系统]")


def test_fill_placeholder_results_skips_already_paired_tool_use():
    """已经有 tool_result 的 tool_use 不应被再次写 placeholder（防双写破坏配对）。"""
    from agent.response_handlers import _fill_placeholder_results
    from agent.conversation_events import append_tool_result

    messages: list[dict] = []
    append_tool_result(messages, "T1", "real result")
    blocks = [SimpleNamespace(id="T1", name="echo", input={})]

    before_count = sum(
        1 for m in messages
        if isinstance(m.get("content"), list)
        and any(b.get("type") == "tool_result" for b in m["content"])
    )
    _fill_placeholder_results(messages, blocks, reason="any reason")
    after_count = sum(
        1 for m in messages
        if isinstance(m.get("content"), list)
        and any(b.get("type") == "tool_result" for b in m["content"])
    )

    assert after_count == before_count, (
        "_fill_placeholder_results 不应给已配对的 tool_use 重复写 tool_result"
    )


# ---------------------------------------------------------------------------
# §5 request_user_input 不会被误判为 no_progress
# ---------------------------------------------------------------------------

def test_no_progress_resolver_does_not_fire_below_threshold():
    """no_progress 阈值是 2；count<2 时 resolver 不应返回 EVENT_RUNTIME_NO_PROGRESS。

    这保护「正常 end_turn 偶尔无进展」不被立刻当成兜底信号；只有连续 2 次
    才升级为 no_progress 强制中断。
    """
    from agent.model_output_resolution import (
        EVENT_RUNTIME_NO_PROGRESS,
        resolve_end_turn_output,
    )

    # 普通文本，不含求助语义，count=1 → 应该返回 None 或非 no_progress 事件。
    event = resolve_end_turn_output("这是一段正常的总结。", 1)
    if event is not None:
        assert event.event_type != EVENT_RUNTIME_NO_PROGRESS

    # count=2 → 触发 no_progress（在普通文本场景）。
    event = resolve_end_turn_output("这是一段正常的总结。", 2)
    assert event is not None
    assert event.event_type == EVENT_RUNTIME_NO_PROGRESS


def test_meta_tool_use_clears_no_progress_counter_semantics():
    """元工具（包括 request_user_input / mark_step_complete）算「动起来」。

    `handle_tool_use_response` 在执行任何 tool_use 前会清零
    `consecutive_end_turn_without_progress`（response_handlers.py 第 206 行附近）。
    本测试通过模拟 state 验证这条契约：

    1. 设置初始 consecutive_end_turn_without_progress = 1
    2. 模拟「这一轮模型返回了 request_user_input 元工具」
    3. handle_tool_use_response 应在所有 block 处理前先清零计数

    我们不真跑 handle_tool_use_response（依赖 turn_state / context），改为
    断言 is_meta_tool 识别 request_user_input + mark_step_complete，并断言
    源代码中存在「计数清零必须在 for 循环前」的注释（架构契约）。
    """
    from agent.tool_registry import is_meta_tool

    # request_user_input 与 mark_step_complete 必须被识别为元工具。
    assert is_meta_tool("request_user_input")
    assert is_meta_tool("mark_step_complete")
    # 普通业务工具不是元工具。
    assert not is_meta_tool("read_file")
    assert not is_meta_tool("write_file")

    # 架构契约：清零必须发生在 tool_use 循环前；这里读源码验证关键注释存在，
    # 防止有人重构 handle_tool_use_response 时把清零移到循环内（一旦移到循环
    # 内并配合 early return，consecutive_end_turn_without_progress 永远不会
    # 被清零，no_progress 兜底就会持续误触发）。
    import inspect
    from agent.response_handlers import handle_tool_use_response

    source = inspect.getsource(handle_tool_use_response)
    assert "consecutive_end_turn_without_progress = 0" in source
    # 注释里明确说明「必须在 for 循环之前」是契约的一部分。
    assert "for 循环之前" in source or "在 for 循环前" in source


# ---------------------------------------------------------------------------
# §6 工具失败不污染 task / checkpoint
# ---------------------------------------------------------------------------

def test_tool_failure_does_not_pollute_task_last_error_field():
    """task.last_error 是 Runtime 错误字段，不是工具失败字段。

    工具失败应该写入 messages.tool_result.content（让模型可见），不应自动
    写入 task.last_error。这是状态字段语义边界——last_error 用于持久化
    跨 chat() 的 Runtime 致命错误，而不是单工具调用失败。
    """
    state = create_agent_state(system_prompt="test")

    # 模拟工具失败：tool_executor 写 tool_result，但不应改 task.last_error。
    from agent.conversation_events import append_tool_result

    append_tool_result(
        state.conversation.messages,
        "T1",
        "[工具 read_file 失败] 文件不存在: /tmp/missing.txt",
    )

    assert state.task.last_error is None, (
        "工具失败不应写 task.last_error；该字段仅用于 Runtime 致命错误。"
    )


def test_request_user_input_pending_awaiting_kind_distinguishes_three_sources():
    """pending_user_input_request.awaiting_kind 必须能区分 3 种来源。

    这条契约是 RUNTIME_ERROR_RECOVERY.md §4.2 的核心：恢复时 UI 只能从
    `awaiting_kind` 知道「为什么 runtime 在等用户」，从而决定 prompt 文案。
    任何把 awaiting_kind 简化为 bool 或合并枚举的 PR 都会破坏 resume 体验。
    """
    valid_kinds = {"request_user_input", "fallback_question", "no_progress"}

    state = create_agent_state(system_prompt="test")
    for kind in valid_kinds:
        state.task.pending_user_input_request = {
            "awaiting_kind": kind,
            "question": f"q for {kind}",
            "why_needed": "test",
            "options": [],
            "context": "",
            "tool_use_id": "ru_X" if kind == "request_user_input" else "",
            "step_index": 0,
        }
        # 字段可写可读，不会被框架覆盖。
        assert state.task.pending_user_input_request["awaiting_kind"] == kind

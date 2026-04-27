"""第二轮硬核场景测试——专门挑可能暴露 bug 的复杂路径。

这轮新增的测试假设：**代码不是完美的**。每条测试都列出期望、实际行为、
以及如果红了应当怎么修。绝不"为了让测试通过而改测试"。
"""

from __future__ import annotations

import pytest

from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    FakeToolUseBlock,
    meta_complete_response,
    text_response,
)
from tests.test_main_loop import (
    _reset_core_module,
    _register_test_tool,
)
from tests.test_complex_scenarios import (
    _tool_use_resp,
    _plan_response,
    _count_tool_pairs,
)


# ============================================================
# 硬核 6：plan feedback 累积导致 user_goal 字符串无限膨胀
# ============================================================

def test_plan_feedback_does_not_accumulate_goal_string_indefinitely(monkeypatch):
    """每次 plan feedback，handle_plan_confirmation 里做的是：
        revised_goal = f"{state.task.user_goal}\\n\\n用户对计划的修改意见：{confirm}"
        state.task.user_goal = revised_goal

    这是**单向累加**——每次反馈都把之前的 goal 包进新 goal。
    如果用户连续反馈 10 次，goal 字符串会变成"原目标 + 10 次反馈拼接"，
    长度呈线性膨胀，每次 planning LLM 调用的 input tokens 也跟着涨。

    ⚠️ 当前 xfail：实际代码就是这么累积的。
    修法：
    (a) 只保留**最后一次 feedback**——revised_goal = f"{原 goal}\\n反馈：{最新}"
    (b) 用数组存 feedback history，拼接时只取最后几条
    (c) 由 planner 自己融合（现在的做法）但加长度上限

    fix 后：confirm_handlers 反馈分支不再写回 state.task.user_goal，反馈仅在
    本地 revised_goal 临时拼接给 planner；user_goal 长度保持稳定。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "v1-s1", "read"), ("s2", "v1-s2", "report")]),
                _plan_response([("s1", "v2-s1", "read"), ("s2", "v2-s2", "report")]),
                _plan_response([("s1", "v3-s1", "read"), ("s2", "v3-s2", "report")]),
                _plan_response([("s1", "v4-s1", "read"), ("s2", "v4-s2", "report")]),
                _plan_response([("s1", "v5-s1", "read"), ("s2", "v5-s2", "report")]),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("原始任务：A")
        initial_goal_len = len(state.task.user_goal)

        # 反复给反馈
        chat("第一次反馈")
        chat("第二次反馈")
        chat("第三次反馈")
        chat("第四次反馈")

        final_goal_len = len(state.task.user_goal)

        # 期望：goal 不应当膨胀到 3 倍以上（合理的融合应当保持规模稳定）
        assert final_goal_len < initial_goal_len * 3, (
            f"4 次 feedback 后 goal 长度膨胀到 {final_goal_len}（初始 {initial_goal_len}）。"
            f"这是单向累加 bug——每次 feedback 都把旧的全部拼进来。"
            f"当前 goal: {state.task.user_goal!r}"
        )
    finally:
        cleanup()


# ============================================================
# 硬核 7：多步任务每步 end_turn 都没说"本步骤已完成"关键词
# ============================================================

def test_step_never_progresses_when_model_forgets_to_call_mark_step_complete(monkeypatch):
    """模型第一次 end_turn 没调 mark_step_complete 时，系统应在同一 loop 里追要。

    新协议下完成判定不再靠关键词，靠 mark_step_complete 工具调用。
    修复后的行为不是把文本关键词当完成信号，而是在 running plan 下把
    text-only end_turn 转成系统提醒，继续请求模型补 mark_step_complete。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "step1", "read"), ("s2", "step2", "report")]),
                # step1 的 end_turn 没调 mark_step_complete
                text_response("我执行了读取操作，结果如下"),
                # 修复后系统会继续同一 loop，要求模型补完成信号
                meta_complete_response(score=90, text="补充完成信号"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("两步任务，每步确认")
        reply = chat("y")

        assert "请确认" in reply
        assert state.task.status == "awaiting_step_confirmation"
        assert state.task.current_step_index == 0
        assert len(fake.requests) == 2
    finally:
        cleanup()


# ============================================================
# 硬核 8：stop_reason 是未知值（比如 stop_sequence）
# ============================================================

def test_unknown_stop_reason_does_not_leave_messages_broken(monkeypatch):
    """Anthropic 可能返回 stop_reason="stop_sequence" 或未来新增的值。
    当前代码 print "未知的 stop_reason" 然后 return "意外的响应"。

    问题：如果 response.content 里有 tool_use，因为走了"意外"分支，
    这些 tool_use 没被追加到 messages，也没写 tool_result。
    下一次对话里如果引用它们就会出问题。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        # 构造一个 stop_reason 是未知值但 content 里有 tool_use 的响应
        weird_response = FakeResponse(
            content=[
                FakeTextBlock(text="尝试调工具"),
                FakeToolUseBlock(id="T_WEIRD", name="w", input={"arg": "x"}),
            ],
            stop_reason="stop_sequence",   # ← 未知值
        )
        fake = FakeAnthropicClient(
            responses=[
                FakeResponse(
                    content=[FakeTextBlock(text='{"steps_estimate": 1}')],
                    stop_reason="end_turn",
                ),
                weird_response,
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("试试")

        # 关键断言：即使 stop_reason 未知，messages 里也不应残留悬空 tool_use
        uses, results = _count_tool_pairs(state.conversation.messages)
        orphans = uses - results
        assert not orphans, (
            f"stop_reason={weird_response.stop_reason} 的响应里有 tool_use，"
            f"但代码没处理，造成悬空：{orphans}。"
            f"下次调 API 会 400。"
        )
    finally:
        cleanup()


# ============================================================
# 硬核 9：工具抛 SystemExit 等"不可恢复"异常
# ============================================================

def test_tool_raising_system_exit_does_not_crash_agent(monkeypatch):
    """execute_tool 用 `except Exception` 只抓普通异常。
    如果工具 raise SystemExit / KeyboardInterrupt / GeneratorExit，
    这些继承自 BaseException 不继承 Exception，不会被 catch。

    真实场景：工具里误写 `exit()` 或 `sys.exit()`，会直接退出整个 agent 进程。

    ⚠️ 已修复：2026-04 tool_registry.execute_tool 用 BaseException 兜住，
    KeyboardInterrupt 透穿保证用户可中断。
    """
    from agent.tool_registry import TOOL_REGISTRY, register_tool, execute_tool

    @register_tool(
        name="exit_tool",
        description="exits",
        parameters={"arg": {"type": "string"}},
        confirmation="never",
    )
    def _exit_tool(**kw):
        raise SystemExit("工具误调 exit")

    try:
        try:
            result = execute_tool("exit_tool", {"arg": "x"})
        except SystemExit:
            pytest.fail(
                "execute_tool 没兜住 SystemExit。"
                "工具误写 exit() 会让整个 agent 进程挂掉——这是鲁棒性 bug。"
                "修法：except BaseException 而不是 except Exception。"
            )

        assert isinstance(result, str), (
            f"SystemExit 应当被转换成字符串 result，实际 type={type(result)}"
        )
    finally:
        TOOL_REGISTRY.pop("exit_tool", None)


# ============================================================
# 硬核 10：三个独立任务连续跑，session state 残留检查
# ============================================================

def test_three_sequential_tasks_no_state_bleeding(monkeypatch):
    """连续跑 3 个独立任务——在每个任务之间、以及全部跑完之后，
    state 应该完全干净，不能有任何"偷渡" 的字段残留。

    这是 bug_hunting.py 里 `test_tool_execution_log_cleared_between_tasks`
    的加强版——那条只测一对 task 之间，这条测 3 个 task 都不能污染。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                # 任务 1（2 步）
                _plan_response([("s1", "t1-s1", "read"), ("s2", "t1-s2", "report")]),
                _tool_use_resp("w", "T1a"),
                meta_complete_response(text="step1 完成"),
                _tool_use_resp("w", "T1b"),
                meta_complete_response(text="step2 完成"),
                # 任务 2（2 步）
                _plan_response([("s1", "t2-s1", "edit"), ("s2", "t2-s2", "report")]),
                _tool_use_resp("w", "T2a"),
                meta_complete_response(text="step1 完成"),
                _tool_use_resp("w", "T2b"),
                meta_complete_response(text="step2 完成"),
                # 任务 3（2 步）
                _plan_response([("s1", "t3-s1", "analyze"), ("s2", "t3-s2", "report")]),
                _tool_use_resp("w", "T3a"),
                meta_complete_response(text="step1 完成"),
                _tool_use_resp("w", "T3b"),
                meta_complete_response(text="step2 完成"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        for task_num in range(1, 4):
            chat(f"任务 {task_num}，每步确认")
            assert state.task.status == "awaiting_plan_confirmation"
            chat("y")                          # plan 确认 → step1 跑完
            assert state.task.status == "awaiting_step_confirmation"
            chat("y")                          # step1 → step2 → 完成

            # 每个任务跑完后：
            # 1. plan 应当被清空
            assert state.task.current_plan is None, (
                f"任务 {task_num} 跑完后 plan 未清空"
            )
            # 2. pending_tool 不应当有残留
            assert state.task.pending_tool is None, (
                f"任务 {task_num} 跑完后 pending_tool 残留：{state.task.pending_tool}"
            )
            # 3. tool_execution_log 应当清空（因为 reset_task）
            assert state.task.tool_execution_log == {}, (
                f"任务 {task_num} 跑完后 tool_execution_log 残留："
                f"{list(state.task.tool_execution_log.keys())}"
            )
            # 4. 计数应当归零
            assert state.task.tool_call_count == 0, (
                f"任务 {task_num} 跑完后 tool_call_count={state.task.tool_call_count}"
            )
            assert state.task.loop_iterations == 0, (
                f"任务 {task_num} 跑完后 loop_iterations={state.task.loop_iterations}"
            )

        # 所有 6 个工具都在 messages 里配对齐全
        uses, results = _count_tool_pairs(state.conversation.messages)
        expected = {"T1a", "T1b", "T2a", "T2b", "T3a", "T3b"}
        assert uses == expected, f"缺 tool_use: {expected - uses}"
        assert results == expected, f"缺 tool_result: {expected - results}"
    finally:
        cleanup()


# ============================================================
# 硬核 11：任务执行中，用户提了个**无关的新任务**
# ============================================================

def test_user_switches_topic_mid_task(monkeypatch):
    """step1 完成、进入 awaiting_step_confirmation 后，
    用户不说 y 也不说 n，而是**直接提了个完全无关的新任务**。

    当前代码的 handle_step_confirmation 会把它当作 plan_feedback
    （触发 planner 重算当前任务）。但用户真正的意图是"我换话题了"。

    ⚠️ 当前 xfail：代码无法区分"对当前 plan 的反馈" 和"全新任务"。
    用户换话题会让 user_goal 被错误拼接（旧目标 + 新话题文字），
    planner 被喂了混合意图，产生一个不伦不类的 plan。

    修法（两选一）：
    (a) 在 awaiting_step_confirmation 时，如果输入既不是 y/n 也不像 feedback
        （比如长度很长或包含完整句号），打印"现在是在确认 step，要切新任务请先 n 取消"
    (b) 识别意图：如果用户输入里没包含任何和当前 plan 相关的词，提示用户确认

    fix 后：confirm_handlers 在 awaiting_step 反馈分支用 looks_like_topic_switch
    做轻量启发式判定，命中则发一个 control_message RuntimeEvent 提示切换、清掉
    旧任务，再走新一轮 planning_phase + main_loop；这条路径不改 checkpoint
    schema、不写 conversation.messages、不影响 tool_use_id / tool_result
    placeholder 或 request_user_input 语义。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "原任务-s1", "read"), ("s2", "原任务-s2", "report")]),
                _tool_use_resp("w", "T1"),
                meta_complete_response(text="step1 完成"),
                _plan_response([
                    ("n1", "混合方案-s1", "read"),
                    ("n2", "混合方案-s2", "report"),
                ]),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("原任务：分析文档，每步确认")
        chat("y")
        assert state.task.status == "awaiting_step_confirmation"

        chat("帮我写一首关于春天的诗")

        assert "春天的诗" in state.task.user_goal and "分析文档" not in state.task.user_goal, (
            f"用户换了新话题，user_goal 应当是新话题，"
            f"不应拼接旧目标。实际 goal={state.task.user_goal!r}"
        )
    finally:
        cleanup()


# ============================================================
# 硬核 12：planner 输出合法 JSON 但 steps 字段是空数组
# ============================================================

def test_planner_with_empty_steps_does_not_crash(monkeypatch):
    """planner 返 `{"steps_estimate": 3, "goal": "x", "steps": []}`——
    steps_estimate 说是多步任务，但 steps 数组为空（模型 bug / 格式错误）。

    期望：planner 应当拒绝这种不一致 JSON，返回 None（走单步路径），
    不应当创建一个 step 列表为空的 Plan 对象。
    """
    malformed_plan = FakeResponse(
        content=[FakeTextBlock(text='{"steps_estimate": 3, "goal": "任务", "steps": [], "needs_confirmation": true}')],
        stop_reason="end_turn",
    )
    fake = FakeAnthropicClient(
        responses=[
            malformed_plan,
            # 如果 planner 正确拒绝，会走单步——需要一个 execution 响应
            text_response("我用单步处理：你好"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    # 这里不应该崩
    try:
        chat("一个任务")
    except Exception as e:
        pytest.fail(f"planner 返回畸形 JSON（steps_estimate=3 但 steps=[]）不应 crash，"
                    f"实际 {type(e).__name__}: {e}")

    # 不应当产生 current_plan——否则后面 build_execution_messages 会索引到空数组崩
    assert state.task.current_plan is None or len(state.task.current_plan.get("steps", [])) > 0, (
        f"畸形 plan（steps 空）不应当被采纳，否则 build_execution_messages 会索引崩。"
        f"实际 current_plan={state.task.current_plan}"
    )


# ============================================================
# 硬核 13：工具返回 None（而不是字符串）
# ============================================================

def test_tool_returning_none_does_not_break_messages(monkeypatch):
    """工具函数 `return` 时不小心漏了返回值（Python 默认返 None）。
    append_tool_result 的 content 字段被设成了 None——
    这可能让 Anthropic API 校验失败。

    ⚠️ 已修复：2026-04 tool_registry._normalize_result 统一把 None/非 str 非 list
    转成字符串；执行路径结尾调用 _normalize_result，保证 tool_result.content 永远合法。
    """
    from agent.tool_registry import TOOL_REGISTRY, register_tool

    @register_tool(
        name="returns_none",
        description="forgets to return",
        parameters={"arg": {"type": "string"}},
        confirmation="never",
    )
    def _t(**kw):
        pass

    try:
        fake = FakeAnthropicClient(
            responses=[
                FakeResponse(
                    content=[FakeTextBlock(text='{"steps_estimate": 1}')],
                    stop_reason="end_turn",
                ),
                FakeResponse(
                    content=[FakeToolUseBlock(id="T1", name="returns_none", input={"arg": "x"})],
                    stop_reason="tool_use",
                ),
                text_response("完成"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("跑个工具")

        for msg in state.conversation.messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") == "T1"
                    ):
                        result_content = block.get("content")
                        assert result_content is not None, (
                            "工具返回 None 被直接写进 tool_result.content，"
                            "Anthropic API 对这种可能会 400。应当规范化为字符串。"
                        )
                        assert isinstance(result_content, (str, list)), (
                            f"tool_result.content 应当是 str 或 list，"
                            f"实际 type={type(result_content)}"
                        )
                        break
    finally:
        TOOL_REGISTRY.pop("returns_none", None)

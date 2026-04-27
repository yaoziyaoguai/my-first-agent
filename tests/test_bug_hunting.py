"""进阶集成测试：专门挖 bug 用的。

上面 46 条测试都绿了，但这不代表没 bug——只代表"已知不变量没被破"。
这个文件放一组**更严格、更可能红**的测试，针对我怀疑还有问题的角落：
- 并行 tool_use 遇到 awaiting 时 tool_result 的**顺序**
- 连续 user 消息的处理
- 空/畸形用户输入
- 主循环到达 MAX_LOOP_ITERATIONS 之后的 state 一致性
- 幂等 tool_execution_log 跨任务残留
- ~~dead field `consecutive_rejections`~~（已在 P3 清理中从 TaskState 移除）
"""

from __future__ import annotations

import pytest  # noqa: F401  其它 xfail 测试可能未来重新接入；保留 import 不显著

from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeToolUseBlock,
    text_response,
)
from tests.test_main_loop import (
    _reset_core_module,
    _register_test_tool,
    _planner_no_plan_response,
)


# ============================================================
# Bug 候选 1：并行 tool_use 遇到 awaiting，tool_result 顺序颠倒
# ============================================================

def test_parallel_tool_use_result_order_matches_declaration(monkeypatch):
    """并行 tool_use 遇到 pending 时，API 投影必须按声明顺序输出 result。

    这里的根因边界很关键：`state.conversation.messages` 是 Runtime append-only
    事件流，pending_tool 会让后续业务工具的 placeholder 先落地，用户确认后的真实
    result 后落地。raw 顺序不等于 Anthropic API 协议顺序。

    真正的模型协议边界在 `context_builder._project_to_api`：它必须按 assistant
    tool_use 的声明顺序合并 tool_result，不能按执行完成顺序或 raw append 顺序。
    这个测试删除旧 xfail，但不引入半开 tool_use queue，不改 checkpoint schema，
    不改变 tool_use_id 配对或 tool_result placeholder，也不能把 RuntimeEvent、
    InputIntent、CommandResult、TaskState、Textual/simple CLI 边界混进 messages。
    """
    cleanup1 = _register_test_tool("confirm_tool", confirmation="always", result="conf-out")
    cleanup2 = _register_test_tool("auto_tool", confirmation="never", result="auto-out")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                FakeResponse(
                    content=[
                        FakeToolUseBlock(
                            id="T_CONFIRM", name="confirm_tool", input={"arg": "a"}
                        ),
                        FakeToolUseBlock(
                            id="T_AUTO", name="auto_tool", input={"arg": "b"}
                        ),
                    ],
                    stop_reason="tool_use",
                ),
                text_response("完成"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("跑两个工具")
        chat("y")   # 确认 T_CONFIRM

        raw_result_ids = []
        for msg in state.conversation.messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        raw_result_ids.append(block.get("tool_use_id"))
        assert set(raw_result_ids) == {"T_CONFIRM", "T_AUTO"}

        assert len(fake.requests) == 2, f"期望确认后发起第二次模型请求，实际 {len(fake.requests)}"
        second_request_messages = fake.requests[1]["messages"]
        assistant_idx = next(
            i
            for i, msg in enumerate(second_request_messages)
            if msg["role"] == "assistant"
            and isinstance(msg.get("content"), list)
            and any(block.get("type") == "tool_use" for block in msg["content"])
        )
        merged_user = second_request_messages[assistant_idx + 1]
        assert merged_user["role"] == "user"
        assert isinstance(merged_user["content"], list)

        projected_result_ids = [
            block["tool_use_id"]
            for block in merged_user["content"]
            if block.get("type") == "tool_result"
        ]

        assert projected_result_ids == ["T_CONFIRM", "T_AUTO"], (
            "Anthropic API messages 中 tool_result 必须按 tool_use 声明顺序投影，"
            f"不能按 raw append/执行完成顺序；实际 {projected_result_ids}"
        )
    finally:
        cleanup1()
        cleanup2()


# ============================================================
# Bug 候选 2：MAX_LOOP_ITERATIONS 到顶后的 state 清理
# ============================================================

def test_max_loop_iterations_leaves_state_consistent(monkeypatch):
    """主循环撞到 MAX_LOOP_ITERATIONS 退出时，state 应当处于一致状态。

    具体期望：至少返回了错误信息，messages 末尾不能有半开 tool_use，
    且 task 已经回到 idle，不能继续挂着旧任务。
    """
    cleanup = _register_test_tool("never_end", confirmation="never", result="x")
    try:
        from agent.response_handlers import MAX_TOOL_CALLS_PER_TURN
        from agent.core import MAX_LOOP_ITERATIONS

        limit = max(MAX_LOOP_ITERATIONS, MAX_TOOL_CALLS_PER_TURN)
        canned = [_planner_no_plan_response()]
        for i in range(limit + 10):
            canned.append(FakeResponse(
                content=[FakeToolUseBlock(id=f"T{i}", name="never_end", input={"arg": "x"})],
                stop_reason="tool_use",
            ))

        fake = FakeAnthropicClient(responses=canned)
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        reply = chat("无限循环")

        # 必须返回某种兜底错误，而不是挂起
        assert reply, f"撞到上限后应当返回错误字符串，实际 {reply!r}"
        assert state.task.status == "idle"
        assert state.task.current_plan is None
        assert state.task.pending_tool is None

        # 收集 messages 里所有 tool_use 和 tool_result id
        tool_use_ids = set()
        tool_result_ids = set()
        for msg in state.conversation.messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_use_ids.add(block.get("id"))
                        elif block.get("type") == "tool_result":
                            tool_result_ids.add(block.get("tool_use_id"))

        # 所有声明的 tool_use 都要有对应的 tool_result（真实或占位）
        orphans = tool_use_ids - tool_result_ids
        assert not orphans, (
            f"撞到上限后不应有悬空 tool_use。孤悬的 id: {orphans}"
        )
    finally:
        cleanup()


# ============================================================
# Bug 候选 3：tool_execution_log 跨任务残留
# ============================================================

def test_tool_execution_log_cleared_between_tasks(monkeypatch):
    """第一个任务跑完后开第二个任务，tool_execution_log 应当被清空。

    这是 reset_task 的职责。如果漏清，第二个任务万一命中同 id 会返回旧结果。

    ⚠️ 当前 xfail：已发现真实 bug。core.chat() 开新任务时只重置了计数字段
    （loop_iterations / tool_call_count / consecutive_max_tokens），
    没有清 tool_execution_log 也没有清 pending_tool。

    只在"多步任务走到 status=done" 的路径上会触发 reset_task；
    "单步任务（planner 返 None）" 跑完后 status 仍是 'idle'，
    下一次 chat 进新任务分支时 tool_execution_log 还带着上一个任务的 id。

    修法很简单——在 core.chat() 新任务分支的字段重置那几行，
    加一句 state.reset_task() 之前的保护，或者显式清 tool_execution_log / pending_tool。

    ⚠️ 已修复：2026-04 core.chat() 新任务分支改用 state.reset_task() 整体清空，
    所有 task 字段一次性归零。
    """
    cleanup = _register_test_tool("simple_tool", confirmation="never", result="result-1")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                FakeResponse(
                    content=[FakeToolUseBlock(
                        id="T1", name="simple_tool", input={"arg": "x"}
                    )],
                    stop_reason="tool_use",
                ),
                text_response("第一个任务完成"),
                _planner_no_plan_response(),
                text_response("第二个任务：你好"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat
        from agent.conversation_events import has_tool_result

        chat("第一个任务")
        assert has_tool_result(state.conversation.messages, "T1")
        assert state.task.tool_execution_log == {}

        chat("第二个任务")

        assert state.task.tool_execution_log == {}, (
            f"新任务开始时 tool_execution_log 应当为空，"
            f"实际 {list(state.task.tool_execution_log.keys())}"
        )
    finally:
        cleanup()


# ============================================================
# Bug 候选 4：连续 user 消息不去重 / 不合并
# ============================================================

def test_consecutive_user_messages_not_merged_but_kept(monkeypatch):
    """确认工具时，我们会写"用户确认执行工具"事件 + tool_result，
    两条都是 user role，构成连续 user。Anthropic 允许但某些代理不接受。

    此测试验证当前行为（不合并），记录现状。如果未来改成合并，这条测试要更新。
    """
    cleanup = _register_test_tool("safe_tool", confirmation="always", result="ok")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                FakeResponse(
                    content=[FakeToolUseBlock(
                        id="T1", name="safe_tool", input={"arg": "x"}
                    )],
                    stop_reason="tool_use",
                ),
                text_response("done"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("跑个工具")
        chat("y")

        # 统计连续 user 消息对（相邻两条都是 user）
        consecutive_user_pairs = 0
        for i in range(len(state.conversation.messages) - 1):
            a = state.conversation.messages[i]
            b = state.conversation.messages[i + 1]
            if a.get("role") == "user" and b.get("role") == "user":
                consecutive_user_pairs += 1

        # 至少有 1 对（确认事件 + tool_result）。这不是 bug，是记录现状。
        assert consecutive_user_pairs >= 1, (
            "确认流程下应当出现连续 user 消息（事件 + tool_result）"
        )
    finally:
        cleanup()


# ============================================================
# Bug 候选 5：dead field `consecutive_rejections`（已在 P3 清理中删除）
# ============================================================
#
# 历史上 TaskState 声明了 `consecutive_rejections: int = 0`，但全 agent/ 仓
# grep 证实只有 dataclass 声明和 reset_task 归零，没有任何累加 / 读取 /
# 比较——真·死字段。原本这里有一个 xfail 测试 `test_consecutive_rejections_is_actually_used`
# 用 grep 断言"如果还能在 agent/ 下找到非归零引用就 PASS"。
#
# 该字段已在 P3 清理 commit 中从 `agent/state.py` 删除，对应不变量
# `tests/test_state_invariants.py::RESETTABLE_FIELDS` 同步删除该项以保持
# `RESETTABLE_FIELDS == 全部 dataclass 字段` 这条测试不变量。删除不触碰
# Runtime 状态机 / RuntimeEvent / InputIntent / CommandResult / checkpoint
# schema / context_builder._project_to_api / tool_use_id 配对 /
# tool_result placeholder / request_user_input 任何主线语义。
#
# 删除原 xfail 测试（而不是把它改成 PASS）的理由：
# 测试本身是"dead-field 探测器"，字段不存在后探测器没有探测对象，留着只会
# 误导后续维护者以为还存在死字段。文档化这段历史就够了。


# ============================================================
# Bug 候选 6：空用户输入的处理
# ============================================================

def test_empty_user_input_should_be_filtered(monkeypatch):
    """用户给空串（直接回车），chat() 应当提前过滤，不触发 LLM 调用。

    当前 main.py::main_loop 有 `if not user_input: continue` 守卫，但
    chat() 内部没有防线。外部前端绕过 main_loop 直接调 chat("") 会：
      1. 触发 planner LLM 调用（浪费 API 费用）
      2. 把空串写进 conversation.messages
      3. 触发执行阶段 LLM 调用
    期望：chat() 自己就应当拒绝空串，不调 LLM。

    ⚠️ 已修复：2026-04 core.chat() 入口加空输入守卫（`if not user_input.strip(): return ""`）。
    """
    fake = FakeAnthropicClient(
        responses=[
            _planner_no_plan_response(),
            text_response("收到空输入"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    chat("")

    # 期望：任何 LLM 调用都不该发生
    assert len(fake.create_requests) == 0, (
        f"空输入不应触发 planner 调用，实际调了 {len(fake.create_requests)} 次"
    )
    assert len(fake.requests) == 0, (
        f"空输入不应触发执行调用，实际调了 {len(fake.requests)} 次"
    )
    # 空串不应进 messages
    assert not any(
        msg.get("content") == "" for msg in state.conversation.messages
    ), "空串不应污染 conversation.messages"


# ============================================================
# Bug 候选 7：tool_use_id 含特殊字符（冒号、斜杠）
# ============================================================

def test_tool_use_id_with_special_chars_roundtrip(monkeypatch):
    """Kimi 用的 id 格式是 'toolu_functions.run_shell:0'（含冒号）。
    验证整条链路都能正确处理。"""
    cleanup = _register_test_tool("echo_tool", confirmation="never", result="ok")
    try:
        weird_id = "toolu_functions.run_shell:0"
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                FakeResponse(
                    content=[FakeToolUseBlock(
                        id=weird_id, name="echo_tool", input={"arg": "x"}
                    )],
                    stop_reason="tool_use",
                ),
                text_response("done"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat
        from agent.conversation_events import has_tool_result

        chat("跑个工具")

        # 特殊 id 应当能被 has_tool_result 找到
        assert has_tool_result(state.conversation.messages, weird_id)
        # 单步任务完成后 task 层日志应被清掉，避免污染下一轮任务。
        assert state.task.tool_execution_log == {}
    finally:
        cleanup()


# ============================================================
# Bug 候选 8：status=running 但 current_plan=None（异常状态）
# ============================================================

def test_running_without_plan_is_inconsistent_state(monkeypatch):
    """task.status='running' 但 current_plan 是 None 的不一致态。

    正常流程走不到这里，但 checkpoint 损坏 / bug 修复前保存的状态都可能有。
    期望：chat() 应当**检测到不一致态**（要么报错、要么自愈成 idle），
    而不是静默地继续跑，把异常态写回 checkpoint。

    ⚠️ 已修复：2026-04 core.chat() 最开始加了一致性检查。
    检测到 status ∈ {running, awaiting_*} 但 plan=None 时打印提示 + reset_task 自愈。
    """
    fake = FakeAnthropicClient(
        responses=[
            _planner_no_plan_response(),
            text_response("收到"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    # 人造不一致态
    state.task.status = "running"
    state.task.current_plan = None

    from agent.core import chat

    chat("继续")

    # 期望：chat() 检测到不一致并修正——status 应当被恢复到合法值
    # 这里认为"跑完之后 status 应该是 idle 或 done（任务结束）"是合理期望
    # 如果 status 仍是 "running"，说明 chat 继承了损坏状态跑下去，是 bug
    assert state.task.status != "running" or state.task.current_plan is not None, (
        f"不一致态应当被自愈。当前 status={state.task.status}, "
        f"plan={state.task.current_plan}"
    )

"""长程交互测试——模拟 10+ 轮对话。

昨晚那个 Kimi 死循环事故就是长程场景才暴露的——短 smoke test 跑不出来。
这个文件专门模拟多轮真实交互：
- 多步 plan：plan 确认 → 工具 → step 确认 → 工具 → step 确认 → 完成
- 反复工具确认：用户连续 y 十几次
- 混合路径：tool_use + end_turn 交替出现很多轮
- 到达 MAX_TOOL_CALLS_PER_TURN 前后的 state 正确性
"""

from __future__ import annotations


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
    _planner_no_plan_response,
)


# ============================================================
# 工具函数
# ============================================================

def _count_tool_pairs(messages):
    """统计 messages 里 tool_use 和 tool_result 的 id 集合。"""
    uses, results = set(), set()
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use":
                        uses.add(block.get("id"))
                    elif block.get("type") == "tool_result":
                        results.add(block.get("tool_use_id"))
    return uses, results


def _make_tool_use_response(tool_name: str, tool_id: str, arg: str = "x", text: str = ""):
    blocks = []
    if text:
        blocks.append(FakeTextBlock(text=text))
    blocks.append(FakeToolUseBlock(id=tool_id, name=tool_name, input={"arg": arg}))
    return FakeResponse(content=blocks, stop_reason="tool_use")


# ============================================================
# 测试 1：15 次连续工具确认，全部配对、限流正常触发
# ============================================================

def test_15_consecutive_tool_confirmations_all_paired(monkeypatch):
    """模拟用户连续 y 确认 15 次工具调用（像昨晚那个 Kimi 死循环场景）。

    断言：
    - 每次 chat("y") 后系统都能正常跑，不崩
    - 除了当前 pending 的那个 tool_use 外，历史里不能有悬空 tool_use
    - tool_call_count 跨确认单调增长（持久化正常）
    """
    cleanup = _register_test_tool("repeated_tool", confirmation="always", result="ok")
    try:
        canned = [_planner_no_plan_response()]
        for i in range(25):
            canned.append(_make_tool_use_response("repeated_tool", f"T{i}", arg=f"x{i}"))
        canned.append(text_response("最终完成"))

        fake = FakeAnthropicClient(responses=canned)
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("开始任务")

        counts = [state.task.tool_call_count]
        for i in range(15):
            if state.task.status != "awaiting_tool_confirmation":
                break
            chat("y")
            counts.append(state.task.tool_call_count)

        # 断言 1：tool_call_count 每次 chat 都在涨（或持平），没有被 reset 过
        for i in range(1, len(counts)):
            assert counts[i] >= counts[i - 1], (
                f"tool_call_count 不应下降（说明没被误 reset），counts={counts}"
            )
        # 15 次后 count 应该也到 15 量级
        assert counts[-1] >= 10, (
            f"15 次连续确认后 tool_call_count 应 ≥ 10，实际 {counts[-1]}"
        )

        # 断言 2：除了当前 pending，其他 tool_use 都应该有 tool_result
        pending_id = None
        if state.task.pending_tool:
            pending_id = state.task.pending_tool.get("tool_use_id")

        uses, results = _count_tool_pairs(state.conversation.messages)
        orphans = uses - results
        # 最多只容许一个 orphan：就是 pending 的那个
        if pending_id:
            orphans.discard(pending_id)
        assert not orphans, (
            f"除当前 pending 外不应有悬空 tool_use。pending={pending_id}, "
            f"其他孤悬: {orphans}"
        )
    finally:
        cleanup()


def test_repeated_confirmed_same_tool_input_stops_task(monkeypatch):
    """Repeated same tool+input across confirmations should stop, not nag forever."""
    cleanup = _register_test_tool("repeat_fetch", confirmation="always", result="same-page")
    try:
        canned = [_planner_no_plan_response()]
        for i in range(8):
            canned.append(_make_tool_use_response("repeat_fetch", f"T_repeat_{i}", arg="same-url"))

        fake = FakeAnthropicClient(responses=canned)
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("查一个旅游页面")
        assert state.task.status == "awaiting_tool_confirmation"

        reply = ""
        for _ in range(8):
            reply = chat("y")
            if state.task.status == "idle":
                break

        assert "重复" in reply or "停止" in reply or "过多" in reply
        assert state.task.status == "idle"
        assert state.task.pending_tool is None
        assert state.task.current_plan is None
    finally:
        cleanup()


def test_failed_confirmed_tool_result_tells_model_not_to_retry_same_input(monkeypatch):
    """A failed confirmed tool call should carry explicit retry guidance."""
    cleanup = _register_test_tool(
        "failing_fetch",
        confirmation="always",
        result="HTTP 错误：https://example.invalid/page 返回状态码 404",
    )
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                _make_tool_use_response("failing_fetch", "T_fail_1", arg="https://example.invalid/page"),
                text_response("换一种方式继续"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("读取这个页面")
        assert state.task.status == "awaiting_tool_confirmation"

        chat("y")

        tool_results = [
            block["content"]
            for msg in state.conversation.messages
            for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
            if isinstance(block, dict)
            and block.get("type") == "tool_result"
            and block.get("tool_use_id") == "T_fail_1"
        ]
        assert tool_results, "确认执行失败工具后应写入 tool_result"
        assert "不要再次调用同一工具和同一输入" in tool_results[-1]

    finally:
        cleanup()


def test_repeated_failed_same_tool_input_is_blocked_without_user_confirmation(monkeypatch):
    """If the model repeats a failed same tool+input, do not ask the user again."""
    cleanup = _register_test_tool(
        "failing_fetch_again",
        confirmation="always",
        result="读取超时：https://example.invalid/page 在 15 秒内未响应。",
    )
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                _make_tool_use_response("failing_fetch_again", "T_fail_1", arg="https://example.invalid/page"),
                _make_tool_use_response("failing_fetch_again", "T_fail_2", arg="https://example.invalid/page"),
                text_response("我改用已有信息继续"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("读取这个页面")
        assert state.task.status == "awaiting_tool_confirmation"

        reply = chat("y")

        assert reply == ""
        assert state.task.status == "idle"
        assert state.task.pending_tool is None

        repeated_results = [
            block["content"]
            for msg in state.conversation.messages
            for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
            if isinstance(block, dict)
            and block.get("type") == "tool_result"
            and block.get("tool_use_id") == "T_fail_2"
        ]
        assert repeated_results, "重复失败调用应被补 tool_result，而不是再次等待用户确认"
        assert "此前已失败" in repeated_results[-1]
        assert "换用其他来源" in repeated_results[-1]
    finally:
        cleanup()


# ============================================================
# 测试 2：多步 plan 完整走完（plan 确认 → 2 次 step 确认 → done）
# ============================================================

def test_multistep_plan_full_execution(monkeypatch):
    """模拟用户跑完一个完整 3 步任务：
    planning → plan y → step1 tool → step1 完成 → step y → step2 tool → step2 完成 → step y → step3 → done
    """
    cleanup = _register_test_tool("worker_tool", confirmation="never", result="step-done")

    def _planner_three_step():
        plan_json = """{
            "steps_estimate": 3,
            "goal": "三步任务",
            "thinking": "分三步",
            "needs_confirmation": true,
            "steps": [
                {"step_id": "s1", "title": "step1", "description": "第一步",
                 "step_type": "read", "suggested_tool": null, "expected_outcome": null,
                 "completion_criteria": null},
                {"step_id": "s2", "title": "step2", "description": "第二步",
                 "step_type": "analyze", "suggested_tool": null, "expected_outcome": null,
                 "completion_criteria": null},
                {"step_id": "s3", "title": "step3", "description": "第三步",
                 "step_type": "report", "suggested_tool": null, "expected_outcome": null,
                 "completion_criteria": null}
            ]
        }"""
        return FakeResponse(
            content=[FakeTextBlock(text=plan_json)], stop_reason="end_turn",
        )

    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_three_step(),
                # step 1: 业务工具 + 收尾时调 mark_step_complete 声明完成
                _make_tool_use_response("worker_tool", "T1", text="执行 step1"),
                meta_complete_response(text="step1 输出总结"),
                # step 2:
                _make_tool_use_response("worker_tool", "T2", text="执行 step2"),
                meta_complete_response(text="step2 输出总结"),
                # step 3:
                _make_tool_use_response("worker_tool", "T3", text="执行 step3"),
                meta_complete_response(text="step3 输出总结"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        # 1. 用户提出任务，planner 出多步 plan
        chat("做个三步任务，每步确认")
        assert state.task.status == "awaiting_plan_confirmation"

        # 2. 确认 plan
        chat("y")
        # status 可能是 awaiting_step（step1 完成后等确认）或 running（step1 还在跑）
        # 在我们 fake 的响应里，step1 会先 tool_use → tool 执行 → end_turn → awaiting_step
        assert state.task.status == "awaiting_step_confirmation", (
            f"step1 完成后应进入 awaiting_step_confirmation，"
            f"实际 {state.task.status}"
        )
        assert state.task.current_step_index == 0

        # 3. 确认进 step 2
        chat("y")
        assert state.task.status == "awaiting_step_confirmation"
        assert state.task.current_step_index == 1

        # 4. 确认进 step 3
        chat("y")
        # step 3 是最后一步，完成后应当 done → reset_task
        # 注：handle_step_confirmation 进入最后一步时走的是 running 路径，
        # 最后一步完成时 advance 设 done + reset_task

        # 5. 最终 state
        # 任务做完之后应当不再有 current_plan
        assert state.task.current_plan is None, (
            "任务完整跑完后 current_plan 应当被清"
        )
        assert state.task.pending_tool is None

        # 6. 协议配对：三个 T1/T2/T3 都应当有 tool_result
        uses, results = _count_tool_pairs(state.conversation.messages)
        assert uses == {"T1", "T2", "T3"}
        assert results == {"T1", "T2", "T3"}
    finally:
        cleanup()


# ============================================================
# 测试 3：每步都混合 tool_use + end_turn，共跑 12 轮 _call_model
# ============================================================

def test_long_running_alternating_tool_and_text(monkeypatch):
    """模拟模型死活不 end_turn，连续返回 tool_use 50+ 次。

    关键验证：
    - 主循环有兜底（MAX_LOOP_ITERATIONS 或 MAX_TOOL_CALLS_PER_TURN），一定会退出
    - 每次 tool_use 和 tool_result 都能配对（通过占位也算）
    - 最终返回的 reply 包含某种"已停止"的错误信息
    """
    cleanup = _register_test_tool("auto_work", confirmation="never", result="work-done")
    try:
        from agent.response_handlers import MAX_TOOL_CALLS_PER_TURN
        from agent.core import MAX_LOOP_ITERATIONS

        # 预置超过两个上限的响应量
        over = max(MAX_TOOL_CALLS_PER_TURN, MAX_LOOP_ITERATIONS) + 10
        canned = [_planner_no_plan_response()]
        for i in range(over):
            canned.append(_make_tool_use_response("auto_work", f"T_long_{i}"))
        canned.append(text_response("终于完成"))

        fake = FakeAnthropicClient(responses=canned)
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        reply = chat("无限循环任务")

        # 应当撞到某个兜底：返回包含"停止"或"过多"
        assert any(kw in reply for kw in ["停止", "过多", "超过"]), (
            f"应当触发兜底停止，实际 reply={reply!r}"
        )

        # 强制停止后 task 必须被清理，避免下一次用户输入被误当成旧任务反馈。
        assert state.task.status == "idle"
        assert state.task.current_plan is None
        assert state.task.pending_tool is None

        # messages 里所有 tool_use 都要有对应 tool_result
        uses, results = _count_tool_pairs(state.conversation.messages)
        orphans = uses - results
        assert not orphans, (
            f"撞到上限退出时不应有悬空 tool_use，孤悬: {orphans}"
        )
    finally:
        cleanup()


# ============================================================
# 测试 4：长程里穿插多次压缩，tool pairing 不破
# ============================================================

def test_long_session_with_compression_preserves_pairing(monkeypatch):
    """模拟长会话：先跑 10 次工具（累积很多 messages），然后压缩，然后再调模型。

    关键断言：压缩前后，tool_use/tool_result 配对不被破坏。
    """
    cleanup = _register_test_tool("gen_tool", confirmation="never", result="g")
    try:
        from agent import memory

        # 把压缩阈值压得很低，确保 10 轮后一定触发
        monkeypatch.setattr(memory, "MAX_MESSAGES", 5)
        monkeypatch.setattr(memory, "MAX_MESSAGE_CHARS", 10_000_000)

        canned = [_planner_no_plan_response()]
        for i in range(10):
            canned.append(_make_tool_use_response("gen_tool", f"T_c{i}", arg=f"c{i}"))
        canned.append(text_response("所有工具都跑完了"))
        # 压缩阶段用的 LLM 响应
        canned.append(FakeResponse(
            content=[FakeTextBlock(text="这是压缩出的摘要")],
            stop_reason="end_turn",
        ))
        # 第二次 chat 的 planner + executor
        canned.append(_planner_no_plan_response())
        canned.append(text_response("收到，继续"))

        fake = FakeAnthropicClient(responses=canned)
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("启动长任务")

        # 记录压缩前的 messages 长度
        pre_compress_len = len(state.conversation.messages)

        # 再来一轮对话——这会触发压缩
        chat("再聊一句")

        # 压缩应当真实发生——post_compress_len 应当显著小于 pre_compress_len
        # 第一次 chat 之后 messages 可能有 20+ 条（10 tool_use + 10 tool_result + user + ...）
        # 压缩后应当只剩 recent（~6 条）+ 第二次 chat 新 append 的 2-3 条
        post_compress_len = len(state.conversation.messages)
        assert post_compress_len < pre_compress_len, (
            f"压缩应当显著减少 messages 条数。"
            f"pre={pre_compress_len}, post={post_compress_len}——"
            f"如果 post >= pre，说明压缩根本没触发"
        )
        # 额外防守：post 不能超过 max_recent + 少量 new（10 是比较宽的上限）
        assert post_compress_len < 15, (
            f"压缩后 messages 条数应接近 max_recent=6，实际 {post_compress_len}"
        )

        # 关键断言：压缩之后保留的 messages 里，所有 tool_result 都能找到对应 tool_use
        uses, results = _count_tool_pairs(state.conversation.messages)
        orphan_results = results - uses
        assert not orphan_results, (
            f"压缩后不应有悬空 tool_result（找不到对应 tool_use），"
            f"孤悬: {orphan_results}"
        )

        # 摘要应当写入 state.memory.working_summary
        assert state.memory.working_summary == "这是压缩出的摘要"
    finally:
        cleanup()


# ============================================================
# 测试 5：Tool call count 跨轮持久化验证
# ============================================================

def test_tool_call_count_persists_across_confirmations(monkeypatch):
    """验证 state.task.tool_call_count 在用户每次确认"y"之后不被清零。

    这是本周 P1-5 修复的不变量：TurnState 被精简，
    所有跨轮计数都挪到 state.task。
    """
    cleanup = _register_test_tool("conf_tool", confirmation="always", result="ok")
    try:
        canned = [_planner_no_plan_response()]
        for i in range(5):
            # 每次用不同的 arg，避免触发 tool_executor 的重复调用检测
            canned.append(_make_tool_use_response("conf_tool", f"T_conf_{i}", arg=f"v{i}"))
        canned.append(text_response("结束"))

        fake = FakeAnthropicClient(responses=canned)
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("开始")
        counts = []
        for i in range(4):
            if state.task.status != "awaiting_tool_confirmation":
                break
            counts.append(state.task.tool_call_count)
            chat("y")

        # 跑了至少 4 次确认，应该有相应数量的 count 被记录
        assert len(counts) >= 3, (
            f"应当记录到至少 3 次 tool_call_count 快照，实际只有 {len(counts)} 次。"
            f"说明 state.task.status 过早脱离 awaiting_tool_confirmation。"
        )

        # 跨 chat 过程中 tool_call_count **严格单调递增**
        # （每次 chat 结束都会多一次 tool_use，计数应当 +1）
        # 如果这个断言红，说明 tool_call_count 被误重置（本周 P1-5 修复的不变量破了）
        for i in range(1, len(counts)):
            assert counts[i] > counts[i - 1], (
                f"tool_call_count 必须跨 chat 严格递增（证明没被误重置）。"
                f"在 i={i} 时 counts[i]={counts[i]} <= counts[i-1]={counts[i-1]}。"
                f"完整 counts={counts}。这说明 P1-5 不变量被破坏了。"
            )
        # 最后 count 应当 >= 3（已经跑了 3+ 次工具）
        assert counts[-1] >= 3, (
            f"4 次确认后 tool_call_count 至少应 >= 3，实际 {counts[-1]}"
        )
    finally:
        cleanup()

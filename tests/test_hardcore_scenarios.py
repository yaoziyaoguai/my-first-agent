"""更硬核的用户路径测试——目的是**捕捉 bug**，而不是让测试通过。

这个文件的规则：**测试红 ≠ 修测试**。
如果测试红了，第一反应是"是不是代码有 bug"——
只有在完全确认"代码行为是设计意图，我的期望错了"之后，才允许改测试。
否则就把它标 xfail + 详细记录"这是代码 bug"。
"""

from __future__ import annotations


from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    meta_complete_response,
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
# 硬核 1：用户说 "yes" / "好的" / "ok"——代码是否认作接受？
# ============================================================

def test_user_says_yes_instead_of_y_at_plan_confirmation(monkeypatch):
    """用户在 plan 确认时打 "yes"，不是 "y"。

    ⚠️ 当前 xfail：代码用 `if confirm.lower() == "y"` 精确匹配，
    "yes" 会走 feedback 分支 → planner 再调一次（没有预置响应会返 None）→
    reset_task → status=idle → plan 被错误清掉。

    修法：confirm_handlers.py 三处判断应扩展成：
        ACCEPT = {"y", "yes", "好", "好的", "ok", "是", "是的"}
        REJECT = {"n", "no", "不", "不要"}
        if confirm.lower() in ACCEPT: ...
        if confirm.lower() in REJECT: ...

    ⚠️ 已修复：2026-04 引入 _ACCEPT/_REJECT 集合 + _is_accept/_is_reject 工具函数。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "step1", "read"), ("s2", "step2", "report")]),
                _tool_use_resp("w", "T1"),
                meta_complete_response(text="step1 完成"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("做个任务，每步确认")
        assert state.task.status == "awaiting_plan_confirmation"

        chat("yes")

        assert state.task.current_plan is not None, (
            "'yes' 被当 feedback 导致 plan 被错误清掉（reset_task）。这是 UX bug。"
        )
        assert state.task.status in ("running", "awaiting_step_confirmation", "awaiting_tool_confirmation"), (
            f"'yes' 应当被识别为接受。实际 status={state.task.status}"
        )
    finally:
        cleanup()


def test_user_says_chinese_yes_at_plan_confirmation(monkeypatch):
    """中文"好的"应当被识别为接受。

    ⚠️ 已修复：2026-04 引入 _ACCEPT 集合，"好的"/"好"/"是"/"是的" 都被识别为接受。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "step1", "read"), ("s2", "step2", "report")]),
                _tool_use_resp("w", "T1"),
                meta_complete_response(text="step1 完成"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("做个任务，每步确认")
        assert state.task.status == "awaiting_plan_confirmation"

        chat("好的")

        assert state.task.current_plan is not None
        assert state.task.status in ("running", "awaiting_step_confirmation", "awaiting_tool_confirmation")
    finally:
        cleanup()


# ============================================================
# 硬核 2：长对话触发压缩，压缩后任务继续能跑
# ============================================================

def test_compression_triggers_between_tasks_and_next_task_still_works(monkeypatch):
    """这一条我上次绕开了——现在正面撞。

    路径：
    1. 跑一个 2 步任务 A（会留下一堆 messages）
    2. 开始新任务 B —— 此时 chat() 走到"新任务"分支，可能触发压缩
    3. 任务 B 应当照常跑完

    关键断言：
    - 压缩确实发生了（working_summary 非空 或 MESSAGES 显著减少）
    - 压缩后 tool_use/tool_result 配对无悬空
    - 任务 B 能正常推进到 end_turn
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        from agent import memory
        # 把阈值压低，确保做完任务 A 后进任务 B 时触发压缩
        monkeypatch.setattr(memory, "MAX_MESSAGES", 5)

        fake = FakeAnthropicClient(
            responses=[
                # 任务 A：2 步，每步 2 个工具
                _plan_response([
                    ("s1", "A-step1", "read"),
                    ("s2", "A-step2", "report"),
                ]),
                _tool_use_resp("w", "Ta1", arg="a1"),
                _tool_use_resp("w", "Ta2", arg="a2"),
                meta_complete_response(text="A-step1 完成"),
                _tool_use_resp("w", "Ta3", arg="a3"),
                _tool_use_resp("w", "Ta4", arg="a4"),
                meta_complete_response(text="A-step2 完成"),
                # 任务 B 开始时会触发压缩 → 吃一个 create 响应
                FakeResponse(
                    content=[FakeTextBlock(text="压缩摘要：用户跑过任务 A")],
                    stop_reason="end_turn",
                ),
                # 任务 B：planner 2 步
                _plan_response([
                    ("s1", "B-step1", "edit"),
                    ("s2", "B-step2", "report"),
                ]),
                # B 任务执行
                _tool_use_resp("w", "Tb1", arg="b1"),
                meta_complete_response(text="B-step1 完成"),
                _tool_use_resp("w", "Tb2", arg="b2"),
                meta_complete_response(text="B-step2 完成"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        # 任务 A
        chat("任务 A，每步确认")
        chat("y")                            # plan 确认 → step1 跑完
        assert state.task.status == "awaiting_step_confirmation"
        chat("y")                            # step1 → step2 → 完成
        assert state.task.current_plan is None   # 任务 A 结束
        pre_B_msg_count = len(state.conversation.messages)

        # 任务 B —— 此时 chat 入口会跑 compression
        chat("任务 B，每步确认")

        # 关键断言 1：压缩确实发生了
        assert state.memory.working_summary == "压缩摘要：用户跑过任务 A", (
            f"进入任务 B 应当触发压缩并写入 working_summary，"
            f"实际 summary={state.memory.working_summary!r}"
        )
        # messages 条数应当明显减少
        post_B_msg_count = len(state.conversation.messages)
        assert post_B_msg_count < pre_B_msg_count, (
            f"压缩后 messages 应减少。pre={pre_B_msg_count}, post={post_B_msg_count}"
        )

        assert state.task.status == "awaiting_plan_confirmation"

        chat("y")                            # 接受 B 的 plan
        assert state.task.status == "awaiting_step_confirmation"
        chat("y")                            # B-step1 → B-step2 → 完成
        assert state.task.current_plan is None, "任务 B 也应当跑完"

        # 关键断言 2：recent messages 里无悬空 tool_result
        uses, results = _count_tool_pairs(state.conversation.messages)
        orphans = results - uses
        assert not orphans, (
            f"压缩后 recent 里不应有悬空 tool_result（找不到对应 tool_use）: {orphans}"
        )
    finally:
        cleanup()


# ============================================================
# 硬核 3：在 awaiting_tool_confirmation 时，用户输入乱七八糟的东西
# ============================================================

def test_random_input_during_awaiting_tool_confirmation(monkeypatch):
    """在等待工具确认时，用户没打 y/n，而是打了别的东西。

    当前代码会把任何非 y/n 的输入当作 tool_feedback（反馈意见）。
    但真实用户可能只是误打、或在等确认时问了别的问题。
    """
    cleanup = _register_test_tool("risky", confirmation="always", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "step1", "read"), ("s2", "step2", "report")]),
                _tool_use_resp("risky", "T1"),
                meta_complete_response(text="收到反馈"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("做任务，每步确认")
        chat("y")                            # plan 确认
        assert state.task.status == "awaiting_tool_confirmation"
        assert state.task.pending_tool["tool_use_id"] == "T1"

        # 用户打了个非 y/n 的东西
        chat("这个工具会删文件吗？")

        # pending 应当被清空（tool_feedback 分支里清掉了）
        assert state.task.pending_tool is None

        # T1 应当有 tool_result（占位）
        uses, results = _count_tool_pairs(state.conversation.messages)
        assert "T1" in results, (
            "用户打了非 y/n 的反馈后，T1 必须有占位 tool_result（半开事务闭合）"
        )

        # 占位文本应当说明"用户未批准"——需要在 tool_result 的 content 字段里找
        placeholder_found = False
        for msg in state.conversation.messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") == "T1"
                    ):
                        if "未批准" in str(block.get("content", "")):
                            placeholder_found = True
                            break
        assert placeholder_found, (
            "T1 的占位 tool_result.content 里应当包含'未批准'说明用户的意图"
        )
    finally:
        cleanup()


# ============================================================
# 硬核 4：用户 Ctrl+C 前的状态能被 checkpoint 保存 + 下次继续
# ============================================================

def test_checkpoint_resume_mid_task_can_continue(monkeypatch, tmp_path):
    """任务到一半保存 checkpoint → 模拟重启 → 从磁盘恢复 → 继续完成。

    不用 _reset_core_module（它 stub 了 save_checkpoint），自己写 reset，
    让 save_checkpoint 真的写磁盘。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        # 临时 checkpoint 路径
        from agent import checkpoint
        cp_path = tmp_path / "checkpoint.json"
        monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", cp_path)

        fake = FakeAnthropicClient(
            responses=[
                _plan_response([
                    ("s1", "step1", "read"),
                    ("s2", "step2", "report"),
                ]),
                _tool_use_resp("w", "T1"),
                meta_complete_response(text="step1 完成"),
                # 模拟重启后继续 step 2
                _tool_use_resp("w", "T2"),
                meta_complete_response(text="step2 完成"),
            ]
        )

        # 自己写一个 reset，不 stub save_checkpoint
        from agent import core
        from agent.state import create_agent_state
        fresh = create_agent_state(
            system_prompt="test system prompt",
            model_name="test-model",
            review_enabled=False,
            max_recent_messages=6,
        )
        monkeypatch.setattr(core, "state", fresh)
        monkeypatch.setattr(core, "client", fake)
        # 让 session.py 里的 print 别太吵
        monkeypatch.setattr(checkpoint, "clear_checkpoint", lambda: None)

        from agent.core import chat

        # 跑到 step1 完成，进入 awaiting_step_confirmation
        chat("两步任务，每步确认")
        chat("y")
        assert fresh.task.status == "awaiting_step_confirmation"

        # checkpoint 应当已经写到磁盘
        assert cp_path.exists(), (
            f"awaiting_step 时 checkpoint 必须已写磁盘，路径 {cp_path}"
        )

        # 模拟"重启"：创建全新 state，从磁盘 load
        restored = create_agent_state(
            system_prompt="test system prompt",
            model_name="test-model",
            review_enabled=False,
            max_recent_messages=6,
        )
        monkeypatch.setattr(core, "state", restored)

        from agent.checkpoint import load_checkpoint_to_state
        ok = load_checkpoint_to_state(restored)
        assert ok, "load_checkpoint_to_state 应当成功"

        # 恢复后的状态应当和保存时一致
        assert restored.task.status == "awaiting_step_confirmation"
        assert restored.task.current_step_index == 0
        assert restored.task.current_plan is not None

        # 继续跑——期望：恢复后 chat("y") 能把任务推进完
        chat("y")

        assert restored.task.current_plan is None, (
            f"恢复后继续 chat('y') 应当能把任务跑完，"
            f"实际 plan={restored.task.current_plan}"
        )

        uses, results = _count_tool_pairs(restored.conversation.messages)
        assert "T1" in results and "T2" in results
    finally:
        cleanup()


# ============================================================
# 硬核 5：awaiting_plan_confirmation 时，用户不给任何输入——连打 3 次空串
# ============================================================

def test_three_empty_inputs_during_awaiting_plan(monkeypatch):
    """用户在 plan 确认时连打 3 次回车（空串）。

    ⚠️ 当前 xfail：代码把空串当 feedback，每个空串都触发一次 planner 重算。
    这是实打实的 bug——三次手滑就烧掉三次 LLM 调用，而且 plan 内容被随机改。

    根因：handle_plan_confirmation 的逻辑是 `if confirm=="y": / elif confirm=="n": / else: feedback`。
    空串 "" 既不是 y 也不是 n，直接当 feedback 处理。

    修法（两选一）：
      A. chat() 入口守卫：user_input.strip() == "" 时打印"请输入内容"并提前 return，
         不进入任何 handle_*_confirmation。
      B. handle_*_confirmation 内部：空 confirm 直接打印提示 + 保持 awaiting 状态。
    A 更干净（影响所有 handler）。

    注意 main.py 的 main_loop 本来就过滤空输入（`if not user_input: continue`），
    但 chat() 自身没这道防线——其他前端直接调 chat() 就会暴露这个 bug。

    ⚠️ 已修复：2026-04 core.chat() 入口加了 `if not user_input.strip(): return ""` 守卫，
    采用修法 A。空串根本走不到 handle_plan_confirmation。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "v1-s1", "read"), ("s2", "v1-s2", "report")]),
                _plan_response([("s1", "v2-s1", "read"), ("s2", "v2-s2", "report")]),
                _plan_response([("s1", "v3-s1", "read"), ("s2", "v3-s2", "report")]),
                _plan_response([("s1", "v4-s1", "read"), ("s2", "v4-s2", "report")]),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("任务")
        assert state.task.status == "awaiting_plan_confirmation"
        v1_title = state.task.current_plan["steps"][0]["title"]

        chat("")
        chat("")
        chat("")

        assert state.task.current_plan["steps"][0]["title"] == v1_title, (
            f"空串不应当触发 LLM 重规划，"
            f"实际 plan 被改成了 {state.task.current_plan['steps'][0]['title']}。"
        )
    finally:
        cleanup()

"""复杂真实场景测试——模拟用户乱七八糟但合法的操作。

这些测试不是"测一个函数"——是跑**完整用户故事**，经过多个 plan/step/tool
确认点，用户做各种决定（接受、拒绝、反馈、重规划、中途改变主意）。
目的是捕捉那些"每个单元测试都绿，但走完整 flow 就翻车"的 bug。

⚠️ 写这组测试时踩过两个坑：
1. planner 内部有 `if steps_estimate <= 1: return None`——单步 plan 不会触发 plan confirmation。
   所以所有"测 plan 确认流程"的测试必须用 2+ 步 plan。
2. compress_history 只在 chat() 的"新任务"分支触发，awaiting_* 分支会提前 return。
   长程测试想验证压缩，必须构造跨多个任务的序列。
"""

from __future__ import annotations


from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    FakeToolUseBlock,
    meta_complete_response,
)
from tests.test_main_loop import (
    _reset_core_module,
    _register_test_tool,
)


# ============================================================
# 辅助函数
# ============================================================

def _tool_use_resp(tool_name, tool_id, arg="x", text=""):
    blocks = []
    if text:
        blocks.append(FakeTextBlock(text=text))
    blocks.append(FakeToolUseBlock(id=tool_id, name=tool_name, input={"arg": arg}))
    return FakeResponse(content=blocks, stop_reason="tool_use")


def _plan_response(steps_spec: list[tuple[str, str, str]]) -> FakeResponse:
    """生成 planner response。steps_spec 是 [(step_id, title, step_type), ...]

    ⚠️ 必须 >= 2 步，否则 planner 会判单步任务直接返 None（不触发 plan 确认）
    """
    assert len(steps_spec) >= 2, "planner 只对 >=2 步的任务生成 plan"
    steps_json = ",".join(
        f"""{{"step_id": "{sid}", "title": "{title}", "description": "{title} 描述",
         "step_type": "{stype}", "suggested_tool": null, "expected_outcome": null,
         "completion_criteria": null}}"""
        for sid, title, stype in steps_spec
    )
    plan_json = f"""{{
        "steps_estimate": {len(steps_spec)},
        "goal": "复杂任务",
        "thinking": "分步完成",
        "needs_confirmation": true,
        "steps": [{steps_json}]
    }}"""
    return FakeResponse(
        content=[FakeTextBlock(text=plan_json)], stop_reason="end_turn",
    )


def _count_tool_pairs(messages):
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


# ============================================================
# 场景 1：用户反复对 plan 提反馈（3 次反馈才最终接受）
# ============================================================

def test_plan_feedback_cycle_three_rounds_then_accept(monkeypatch):
    """用户：给 plan → 不满意反馈 → 新 plan 又不满意 → 第三次反馈 → 最终接受。

    每次反馈都用 2 步 plan（保证 planner 不跳过）。
    """
    cleanup = _register_test_tool("doit", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                # 第一次 planning（2步）
                _plan_response([
                    ("s1", "方案A-第一步", "read"),
                    ("s2", "方案A-第二步", "report"),
                ]),
                # 第一次 feedback 后 re-plan
                _plan_response([
                    ("s1", "方案B-第一步", "read"),
                    ("s2", "方案B-第二步", "report"),
                    ("s3", "方案B-第三步", "edit"),
                ]),
                # 第二次 feedback 后 re-plan（2步）
                _plan_response([
                    ("s1", "方案C-步骤1", "analyze"),
                    ("s2", "方案C-步骤2", "report"),
                ]),
                # 第三次 feedback 后 re-plan（2步）
                _plan_response([
                    ("s1", "最终方案-第一步", "edit"),
                    ("s2", "最终方案-第二步", "report"),
                ]),
                # 接下来的执行不测，只验证 plan 被正确接受
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("做个复杂任务")
        assert state.task.status == "awaiting_plan_confirmation"
        assert state.task.current_plan["steps"][0]["title"] == "方案A-第一步"

        # 第一次反馈
        chat("我想要更详细一点的分解")
        # P1：plan 阶段收到模糊反馈 → 切到 awaiting_feedback_intent 等显式三选一。
        # 用 chat("1") 显式确认为"对当前计划的反馈"，触发重规划。
        chat("1")
        assert state.task.status == "awaiting_plan_confirmation"
        assert state.task.current_plan["steps"][0]["title"] == "方案B-第一步"
        assert len(state.task.current_plan["steps"]) == 3

        # 第二次反馈
        chat("又改主意了，还是两步就行")
        chat("1")
        assert state.task.status == "awaiting_plan_confirmation"
        assert state.task.current_plan["steps"][0]["title"] == "方案C-步骤1"
        assert len(state.task.current_plan["steps"]) == 2

        # 第三次反馈
        chat("换成 edit 类型的")
        chat("1")
        assert state.task.status == "awaiting_plan_confirmation"
        assert state.task.current_plan["steps"][0]["step_type"] == "edit"

        # 消息历史里应当有多条 "plan_feedback" 语义事件
        feedback_events = [
            b.get("text", "")
            for msg in state.conversation.messages
            if isinstance(msg.get("content"), list)
            for b in msg["content"]
            if isinstance(b, dict) and b.get("type") == "text"
            and "修改意见" in b.get("text", "")
        ]
        assert len(feedback_events) >= 3, (
            f"应当有至少 3 条 plan_feedback 事件，实际 {len(feedback_events)}"
        )
    finally:
        cleanup()


# ============================================================
# 场景 2：完整跑完一个 3 步 plan，每步都混合 confirm + auto 工具
# ============================================================

def test_full_three_step_plan_with_mixed_tools(monkeypatch):
    """完整跑 3 步 plan：step1 = risky+safe, step2 = 3 risky, step3 = 1 safe。"""
    cleanup1 = _register_test_tool("risky", confirmation="always", result="risky-done")
    cleanup2 = _register_test_tool("safe", confirmation="never", result="safe-done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([
                    ("s1", "step1", "read"),
                    ("s2", "step2", "analyze"),
                    ("s3", "step3", "report"),
                ]),
                # step 1：risky（confirm）+ safe（auto） + 调元工具收尾
                _tool_use_resp("risky", "T_s1_1", text="step1 开始，先跑 risky"),
                _tool_use_resp("safe", "T_s1_2", text="再跑 safe"),
                meta_complete_response(text="step1 结果整理完毕"),
                # step 2：3 个 risky（不同输入，避免触发重复检测）+ 调元工具收尾
                _tool_use_resp("risky", "T_s2_1", arg="a", text="step2 第一个 risky"),
                _tool_use_resp("risky", "T_s2_2", arg="b", text="step2 第二个 risky"),
                _tool_use_resp("risky", "T_s2_3", arg="c", text="step2 第三个 risky"),
                meta_complete_response(text="step2 收尾"),
                # step 3：1 个 safe + 调元工具收尾
                _tool_use_resp("safe", "T_s3_1", text="step3 一个 safe 收尾"),
                meta_complete_response(text="全部完成"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat_calls = 0

        def _c(msg):
            nonlocal chat_calls
            chat_calls += 1
            return chat(msg)

        # 1. 提出任务
        _c("做 3 步大任务，每步确认")
        assert state.task.status == "awaiting_plan_confirmation"

        # 2. 接受 plan → step1 第 1 个工具是 risky，需确认
        _c("y")
        assert state.task.status == "awaiting_tool_confirmation"
        assert state.task.pending_tool["tool_use_id"] == "T_s1_1"

        # 3. 确认 risky → 模型返回 safe（auto）→ 自动跑完 → 模型返回 end_turn
        _c("y")
        assert state.task.status == "awaiting_step_confirmation"
        assert state.task.current_step_index == 0

        # 4. 确认进 step 2
        _c("y")
        assert state.task.status == "awaiting_tool_confirmation"
        assert state.task.pending_tool["tool_use_id"] == "T_s2_1"

        _c("y")
        assert state.task.status == "awaiting_tool_confirmation"
        assert state.task.pending_tool["tool_use_id"] == "T_s2_2"

        _c("y")
        assert state.task.status == "awaiting_tool_confirmation"
        assert state.task.pending_tool["tool_use_id"] == "T_s2_3"

        _c("y")
        # step2 end_turn 之后，step2 是非末步（idx 1 < len-1=2），进入 awaiting_step
        assert state.task.status == "awaiting_step_confirmation"
        assert state.task.current_step_index == 1

        # 确认进 step 3
        _c("y")
        # step 3 是唯一的 safe（auto），直接跑完到 end_turn → 最后一步 → reset_task
        assert state.task.current_plan is None, (
            f"全部做完后 current_plan 应清空，实际 {state.task.current_plan}"
        )
        assert state.task.status == "idle"
        assert state.task.pending_tool is None

        # 协议配对完整
        uses, results = _count_tool_pairs(state.conversation.messages)
        expected_ids = {"T_s1_1", "T_s1_2", "T_s2_1", "T_s2_2", "T_s2_3", "T_s3_1"}
        assert uses == expected_ids, f"缺少 tool_use，实际 {uses}"
        assert results == expected_ids, f"缺少 tool_result，实际 {results}"

        assert chat_calls >= 8

    finally:
        cleanup1()
        cleanup2()


# ============================================================
# 场景 3：Step 进行中用户拒绝工具，整条任务不崩
# ============================================================

def test_mid_step_user_rejects_tool_task_continues(monkeypatch):
    """step 1 中，模型调了 risky 工具，用户 n 拒绝。
    要用 2 步 plan 才会进 plan confirmation。"""
    cleanup = _register_test_tool("risky", confirmation="always", result="risky-done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([
                    ("s1", "step1", "read"),
                    ("s2", "step2", "report"),
                ]),
                # plan y 后模型调 risky
                _tool_use_resp("risky", "T1", text="试试 risky"),
                # 用户 n 后模型通过元工具声明本步骤完成
                meta_complete_response(text="好的，既然被拒绝，本步骤已完成"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("做个任务，每步确认")
        assert state.task.status == "awaiting_plan_confirmation"

        chat("y")   # 接受 plan
        assert state.task.status == "awaiting_tool_confirmation"

        # 用户拒绝
        chat("n")

        # pending 清空
        assert state.task.pending_tool is None

        # T1 应当有占位 tool_result
        uses, results = _count_tool_pairs(state.conversation.messages)
        assert "T1" in uses
        assert "T1" in results, "用户拒绝后 T1 必须有占位 tool_result"

        # 有"用户拒绝执行工具" 事件
        rejection_events = [
            b.get("text", "")
            for msg in state.conversation.messages
            if isinstance(msg.get("content"), list)
            for b in msg["content"]
            if isinstance(b, dict) and "拒绝执行工具" in b.get("text", "")
        ]
        assert rejection_events
    finally:
        cleanup()


# ============================================================
# 场景 4：Step 中用户给反馈要求重规划
# ============================================================

def test_mid_task_user_gives_step_feedback_triggers_replan(monkeypatch):
    """step1 做完后 step 确认点用户说"改计划"→ 触发重规划。"""
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([
                    ("s1", "第一版第一步", "read"),
                    ("s2", "第一版第二步", "report"),
                ]),
                # plan y → step1 执行：一个工具 + 调元工具收尾
                _tool_use_resp("w", "T1"),
                meta_complete_response(text="step1 完成"),
                # 用户在 step 确认处给 feedback，触发 re-plan（新 plan 2 步）
                _plan_response([
                    ("nA", "新方案-第一步", "analyze"),
                    ("nB", "新方案-第二步", "report"),
                ]),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("原任务，每步确认")
        chat("y")   # 接受 plan
        assert state.task.status == "awaiting_step_confirmation"
        assert state.task.current_step_index == 0

        # 用户给反馈
        chat("我想改一下计划，重新规划")
        # P1：step 阶段收到模糊反馈 → 切到 awaiting_feedback_intent 等显式三选一。
        # 用 chat("1") 显式确认为"对当前计划的反馈"，触发重规划。
        chat("1")

        # 应当触发重规划，回到 awaiting_plan_confirmation
        assert state.task.status == "awaiting_plan_confirmation"
        assert state.task.current_plan["steps"][0]["title"] == "新方案-第一步"
        assert state.task.current_step_index == 0
    finally:
        cleanup()


# ============================================================
# 场景 5：用户乱来——大小写、前后空格
# ============================================================

def test_user_input_variations_handled_gracefully(monkeypatch):
    """测试 "Y"、" y "、"y\n" 等变体都能被识别为接受。

    断言收紧：必须 status 进入执行态（running / awaiting_step / awaiting_tool），
    且 current_plan 仍然存在（不是被 feedback 误杀到 idle）。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                # Round 1
                _plan_response([("s1", "任务1", "read"), ("s2", "任务1-2", "report")]),
                _tool_use_resp("w", "T_r1"),
                meta_complete_response(text="step1 完成"),
                # Round 2（大写 Y）
                _plan_response([("s1", "任务2", "read"), ("s2", "任务2-2", "report")]),
                _tool_use_resp("w", "T_r2"),
                meta_complete_response(text="step1 完成"),
                # Round 3（带空格）
                _plan_response([("s1", "任务3", "read"), ("s2", "任务3-2", "report")]),
                _tool_use_resp("w", "T_r3"),
                meta_complete_response(text="step1 完成"),
            ]
        )

        EXEC_STATUSES = {"running", "awaiting_step_confirmation", "awaiting_tool_confirmation"}

        # Round 1：标准 "y"
        state = _reset_core_module(monkeypatch, fake)
        from agent.core import chat
        chat("任务 1，每步确认")
        assert state.task.status == "awaiting_plan_confirmation"
        chat("y")
        assert state.task.current_plan is not None, "'y' 后 plan 不应被清"
        assert state.task.status in EXEC_STATUSES, (
            f"'y' 应当被识别为接受进入执行态，实际 status={state.task.status}"
        )

        # Round 2：大写 "Y"
        state = _reset_core_module(monkeypatch, fake)
        chat("任务 2，每步确认")
        assert state.task.status == "awaiting_plan_confirmation"
        chat("Y")
        assert state.task.current_plan is not None
        assert state.task.status in EXEC_STATUSES, (
            f"'Y' 应当被识别为接受（lower 处理），实际 status={state.task.status}"
        )

        # Round 3：带空格 " y "
        state = _reset_core_module(monkeypatch, fake)
        chat("任务 3，每步确认")
        assert state.task.status == "awaiting_plan_confirmation"
        chat("  y  ")
        assert state.task.current_plan is not None
        assert state.task.status in EXEC_STATUSES, (
            f"' y ' 应当被识别为接受（strip 处理），实际 status={state.task.status}"
        )
    finally:
        cleanup()


# ============================================================
# 场景 6：混合路径——plan feedback → step n 工具 → step feedback → 最终接受
# ============================================================

def test_chaotic_user_journey(monkeypatch):
    """一次合法但混乱的会话：
    1. 提任务 → 不满意 plan → feedback
    2. 新 plan → y 接受
    3. step1 工具 confirm → n 拒绝 → 模型换方式 → end_turn
    4. step 确认 → feedback → 重规划
    5. 最新 plan → y → 跑完
    """
    cleanup = _register_test_tool("r", confirmation="always", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                # 1. 第一个 plan（2步）
                _plan_response([("s1", "原方案-1", "read"), ("s2", "原方案-2", "report")]),
                # 2. 第一次 feedback → 新 plan（2步）
                _plan_response([("s1", "新方案step1", "read"), ("s2", "新方案step2", "report")]),
                # 3. y 接受 → step1 调 risky（confirm）
                _tool_use_resp("r", "T1"),
                # 4. n 拒绝 → 模型换方式 → 调元工具收尾
                meta_complete_response(text="好的，换个方式"),
                # 5. step 确认处用户 feedback → 重规划（2步）
                _plan_response([("f1", "最终方案-1", "edit"), ("f2", "最终方案-2", "report")]),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        # 1. 提任务
        chat("一个复杂任务，每步确认")
        assert state.task.current_plan["steps"][0]["title"] == "原方案-1"

        # 2. feedback —— P1 后需要先 chat("1") 显式确认归属为反馈再触发重规划。
        chat("不够好，重做")
        chat("1")
        assert state.task.current_plan["steps"][0]["title"] == "新方案step1"

        # 3. y
        chat("y")
        assert state.task.status == "awaiting_tool_confirmation"

        # 4. n 拒绝工具
        chat("n")
        assert state.task.status == "awaiting_step_confirmation"

        # 5. step feedback → 重规划（同样需要 chat("1") 显式确认）
        chat("我想改方案")
        chat("1")
        assert state.task.status == "awaiting_plan_confirmation"
        assert state.task.current_plan["steps"][0]["title"] == "最终方案-1"

        # 全程所有 tool_use 都有 tool_result（至少 T1 被占位）
        uses, results = _count_tool_pairs(state.conversation.messages)
        orphans = uses - results
        assert not orphans, f"混乱流程下不应有悬空 tool_use，孤悬: {orphans}"
    finally:
        cleanup()


# ============================================================
# 场景 7：连续做两个独立任务（验证跨任务 state 清理）
# ============================================================

def test_two_sequential_tasks_state_isolated(monkeypatch):
    """跑完一个 2 步任务 → 立刻提另一个 2 步任务。
    第二个任务的 state 不应被第一个任务污染。"""
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                # 任务 1
                _plan_response([("s1", "task1-s1", "read"), ("s2", "task1-s2", "report")]),
                _tool_use_resp("w", "T1a"),
                meta_complete_response(text="step1 完成"),
                _tool_use_resp("w", "T1b"),
                meta_complete_response(text="step2 完成"),
                # 任务 2
                _plan_response([("s1", "task2-s1", "edit"), ("s2", "task2-s2", "report")]),
                _tool_use_resp("w", "T2a"),
                meta_complete_response(text="step1 完成"),
                _tool_use_resp("w", "T2b"),
                meta_complete_response(text="step2 完成"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        # 任务 1
        chat("第一个任务，每步确认")
        chat("y")   # 接受 plan
        assert state.task.status == "awaiting_step_confirmation"
        chat("y")   # step1 → step2
        # 任务 1 完成
        assert state.task.current_plan is None

        # 任务 2 不应被第一个任务的状态污染
        chat("第二个独立任务，每步确认")
        assert state.task.status == "awaiting_plan_confirmation"
        assert state.task.current_plan["steps"][0]["title"] == "task2-s1"
        # step_index 应当从 0 重新开始
        assert state.task.current_step_index == 0

        chat("y")
        chat("y")   # step1 → step2

        # 任务 2 也做完
        assert state.task.current_plan is None

        # 关键：验证 T2a 在 tool_execution_log 里，不应残留 T1a / T1b
        # （这是 bug_hunting 那条 xfail 的变体，用不同路径验证）
        # 注：多步任务走到 done 会 reset_task，所以这里 log 应当是空的
        assert state.task.tool_execution_log == {}, (
            f"两个任务做完后 log 应当清空，实际 {list(state.task.tool_execution_log.keys())}"
        )

        # 所有工具都成对
        uses, results = _count_tool_pairs(state.conversation.messages)
        expected = {"T1a", "T1b", "T2a", "T2b"}
        assert uses == expected and results == expected
    finally:
        cleanup()

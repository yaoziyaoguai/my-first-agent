"""回归测试：你的 Kimi 死循环现场，根因是违反 Anthropic 协议。

问题原日志（2026-04-25）：
  Kimi 输出并行 tool_use [find(确认型), ls(确认型)]
  → 我们把 T0 放进 pending_tool，给 T1 写"本轮跳过" 占位 user 消息
  → 用户 y 后给 T0 写"真实结果" user 消息（和控制事件分开了）
  → 每个 tool_result 都独立成 user 消息 + 控制事件插在中间
  → Kimi 见到不规范的 messages，陷入重复调用循环

Anthropic 协议明确规定：
  1. 一条 assistant 的所有 tool_use 对应的 tool_result 必须**合并到一条 user 消息**
  2. assistant(tool_use) 和 user(tool_result) 之间**不能插任何消息**
  3. 在 user 消息的 content array 里，tool_result 必须在**前面**

这个测试钉死"`_project_to_api` 严格合规"这件事。
"""

from __future__ import annotations

from agent.context_builder import _project_to_api


# ===================================================================
# 场景 1：两个并行 tool_use，raw 里 tool_result 拆成两条 user 消息
# ===================================================================

def test_project_merges_parallel_tool_results_into_one_user_message():
    """最简单也最核心的场景：并行 tool_use + 分散的 tool_result → 合并。"""
    raw = [
        {"role": "user", "content": "帮我跑两个命令"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "好的，我来执行"},
            {"type": "tool_use", "id": "T0", "name": "find", "input": {"p": "*.py"}},
            {"type": "tool_use", "id": "T1", "name": "ls", "input": {"p": "."}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T0", "content": "find 结果"}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T1", "content": "ls 结果"}
        ]},
    ]

    projected = _project_to_api(raw)

    # 投影后 messages 长度：user + assistant + 合并后的 user = 3 条
    assert len(projected) == 3, f"期望 3 条 messages，实际 {len(projected)}: {projected}"

    # 最后一条是合并的 user
    merged = projected[-1]
    assert merged["role"] == "user"
    assert isinstance(merged["content"], list)

    # 两个 tool_result 都在同一条里，按 tool_use 声明顺序（T0, T1）
    types = [b["type"] for b in merged["content"]]
    ids = [b["tool_use_id"] for b in merged["content"] if b["type"] == "tool_result"]

    assert types == ["tool_result", "tool_result"], (
        f"合并后 content 应全是 tool_result，实际 {types}"
    )
    assert ids == ["T0", "T1"], (
        f"tool_result 应按 tool_use 声明顺序，实际 {ids}"
    )


# ===================================================================
# 场景 2：控制事件插在 tool_use 和 tool_result 之间——必须被删
# ===================================================================

def test_project_strips_control_events_between_tool_use_and_tool_result():
    """
    违反 Anthropic 第二条硬性要求："Tool result blocks must immediately follow
    their corresponding tool use blocks in the message history. You cannot include
    any messages between..."

    原状态：我们的 append_control_event("用户确认执行工具") 会写在中间。
    投影必须删掉。
    """
    raw = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "T0", "name": "risky", "input": {"a": 1}},
        ]},
        {"role": "user", "content": [
            {"type": "text", "text": "用户确认执行工具"}   # 控制事件
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T0", "content": "risky 结果"}
        ]},
    ]

    projected = _project_to_api(raw)

    # 投影后：assistant + 合并 user = 2 条（中间那条控制事件被删）
    assert len(projected) == 2, (
        f"控制事件应被删除，投影后期望 2 条，实际 {len(projected)}: {projected}"
    )
    assert projected[0]["role"] == "assistant"
    assert projected[1]["role"] == "user"
    # 最后那条是合并的 tool_result，不含"用户确认" 文字
    user_content = projected[1]["content"]
    assert isinstance(user_content, list)
    assert all(b.get("type") == "tool_result" for b in user_content), (
        f"合并后的 user 消息不应含控制事件文字，实际 {user_content}"
    )


# ===================================================================
# 场景 3：模型日志里的真实现场重现——find + ls + 占位 + 用户确认
# ===================================================================

def test_project_handles_kimi_loop_scenario():
    """
    原始日志还原：
      assistant: [find_use, ls_use]
      user: [tool_result ls = "本轮跳过"]      # ← T1 占位（旧 bug）
      user: "用户确认执行工具"                  # ← 控制事件
      user: [tool_result find = "真实结果"]    # ← T0 真结果

    Kimi 看到这种结构会陷入循环。投影后必须是严格合规的：
      assistant: [find_use, ls_use]
      user: [tool_result find, tool_result ls]   # 合并 + 按声明顺序
    """
    raw = [
        {"role": "user", "content": "扫描目录"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "T_find", "name": "run_shell",
             "input": {"command": "find ..."}},
            {"type": "tool_use", "id": "T_ls", "name": "run_shell",
             "input": {"command": "ls -la"}},
        ]},
        # 占位 tool_result（旧 bug 行为）
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T_ls",
             "content": "[系统] 本轮跳过"}
        ]},
        # 控制事件
        {"role": "user", "content": [
            {"type": "text", "text": "用户确认执行工具"}
        ]},
        # T_find 的真实结果
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T_find",
             "content": "./config.py ..."}
        ]},
    ]

    projected = _project_to_api(raw)

    # 投影后：初始 user + assistant + 合并 user = 3 条
    assert len(projected) == 3, (
        f"期望投影后 3 条（初始/assistant/合并 user），实际 {len(projected)}"
    )

    # 合并的 user 消息
    merged = projected[-1]
    assert merged["role"] == "user"
    assert isinstance(merged["content"], list)

    # tool_result 顺序必须和 tool_use 声明一致：T_find 先，T_ls 后
    ids = [b["tool_use_id"] for b in merged["content"]]
    assert ids == ["T_find", "T_ls"], (
        f"Kimi 现场：tool_result 应当按 tool_use 声明顺序（T_find, T_ls），实际 {ids}"
    )

    # 所有块都必须是 tool_result 类型（无文字控制事件混入）
    assert all(b.get("type") == "tool_result" for b in merged["content"])


# ===================================================================
# 场景 4：缺失的 tool_use 对应 tool_result——投影时补占位保持协议合法
# ===================================================================

def test_project_fills_missing_tool_result_with_placeholder():
    """
    如果某个 tool_use 的 tool_result 整个 messages 里都找不到，
    投影必须补占位——不然协议违反："assistant 有 tool_use 但 user 里找不到对应 tool_result"。
    """
    raw = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "T0", "name": "foo", "input": {}},
            {"type": "tool_use", "id": "T1", "name": "bar", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T0", "content": "ok"}
            # T1 缺失
        ]},
    ]

    projected = _project_to_api(raw)

    merged = projected[-1]
    assert merged["role"] == "user"
    ids = [b["tool_use_id"] for b in merged["content"]]
    assert ids == ["T0", "T1"]
    # T1 的 content 应该是占位
    t1_block = merged["content"][1]
    assert "缺失" in t1_block["content"] or "系统" in t1_block["content"]


# ===================================================================
# 场景 5：纯文本对话——完全 pass through
# ===================================================================

def test_project_pure_text_conversation_unchanged():
    """没有 tool_use 的纯对话——投影应当不动。"""
    raw = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么我能帮助你的吗？"},
        {"role": "user", "content": "讲个笑话"},
    ]
    projected = _project_to_api(raw)
    assert projected == raw, "纯文本对话投影应当不动"


# ===================================================================
# 场景 6：多个 assistant(tool_use) 连续（两轮工具交互）
# ===================================================================

def test_project_handles_two_sequential_tool_rounds():
    """
    连续两轮工具调用：每轮都有自己的 assistant(tool_use) 和对应 tool_result。
    投影必须独立合并每轮，不串扰。
    """
    raw = [
        {"role": "user", "content": "查文件"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "round1_T0", "name": "find", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "round1_T0", "content": "文件列表"}
        ]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "基于文件列表再查内容"},
            {"type": "tool_use", "id": "round2_T0", "name": "read_file", "input": {}},
            {"type": "tool_use", "id": "round2_T1", "name": "read_file", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "round2_T0", "content": "文件1"}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "round2_T1", "content": "文件2"}
        ]},
    ]

    projected = _project_to_api(raw)

    # 期望结构：user, assistant_r1, user_r1, assistant_r2, user_r2_merged
    assert len(projected) == 5, (
        f"两轮独立合并后期望 5 条，实际 {len(projected)}: {[m['role'] for m in projected]}"
    )

    # 第二轮的合并 user 消息应当有 2 个 tool_result
    r2_merged = projected[-1]
    assert r2_merged["role"] == "user"
    r2_ids = [b["tool_use_id"] for b in r2_merged["content"]]
    assert r2_ids == ["round2_T0", "round2_T1"]


# ===================================================================
# 场景 7：投影不应改动原 raw（纯函数）
# ===================================================================

def test_project_is_pure_function():
    """_project_to_api 必须是纯函数——不改动输入。"""
    raw = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "T0", "name": "foo", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T0", "content": "ok"}
        ]},
    ]
    import copy
    raw_copy = copy.deepcopy(raw)

    _project_to_api(raw)

    assert raw == raw_copy, "投影函数不应改动输入"


# ===================================================================
# 场景 8（集成）：跑完整 chat() 流程，验证 API 收到的 messages 合规
# ===================================================================

def test_api_messages_are_compliant_after_parallel_tool_awaiting(monkeypatch):
    """
    真正的目标：并行 tool_use + 其中一个需确认，
    API 收到的 request messages 必须严格合规——
    tool_result 合并到一条 user 消息 + 按声明顺序。

    这条测试就是你 Kimi 循环的"修复验证"——
    即使 state 里乱，发 API 时投影层会清理干净。
    """
    from tests.conftest import (
        FakeAnthropicClient, FakeResponse, FakeTextBlock, FakeToolUseBlock,
        text_response,
    )
    from tests.test_main_loop import _reset_core_module, _register_test_tool

    cleanup1 = _register_test_tool("confirm_tool", confirmation="always", result="需确认工具结果")
    cleanup2 = _register_test_tool("auto_tool", confirmation="never", result="自动工具结果")
    try:
        fake = FakeAnthropicClient(
            responses=[
                # planner: 单步
                FakeResponse(
                    content=[FakeTextBlock(text='{"steps_estimate": 1}')],
                    stop_reason="end_turn",
                ),
                # 第 1 次 executor: 并行 [confirm_tool, auto_tool]
                FakeResponse(
                    content=[
                        FakeTextBlock(text="我要并行调两个工具"),
                        FakeToolUseBlock(id="T_CONFIRM", name="confirm_tool", input={"arg":"a"}),
                        FakeToolUseBlock(id="T_AUTO", name="auto_tool", input={"arg":"b"}),
                    ],
                    stop_reason="tool_use",
                ),
                # 第 2 次 executor（用户确认后）: end_turn
                text_response("完成了"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("跑两个工具")
        assert state.task.status == "awaiting_tool_confirmation"

        chat("y")   # 确认 T_CONFIRM

        # 关键断言：第二次 API 请求（stream 调用）的 messages 是**严格合规**的
        assert len(fake.requests) == 2, f"期望 2 次 stream 调用，实际 {len(fake.requests)}"
        second_request_messages = fake.requests[1]["messages"]

        # 找到 assistant (tool_use) 消息的位置
        assistant_idx = None
        for i, m in enumerate(second_request_messages):
            if m["role"] == "assistant" and isinstance(m.get("content"), list):
                if any(b.get("type") == "tool_use" for b in m["content"]):
                    assistant_idx = i
                    break
        assert assistant_idx is not None, "未找到 assistant tool_use 消息"

        # 协议合规检查 1：assistant 之后紧跟的必须是含 tool_result 的 user 消息
        next_msg = second_request_messages[assistant_idx + 1]
        assert next_msg["role"] == "user", "assistant 后必须跟 user 消息"
        assert isinstance(next_msg["content"], list)

        # 协议合规检查 2：该 user 消息里所有块都是 tool_result（文字在后，但这里无）
        tool_result_blocks = [b for b in next_msg["content"] if b.get("type") == "tool_result"]
        assert len(tool_result_blocks) == 2, (
            f"两个并行 tool_use 对应的 tool_result 必须合并到同一条 user 消息，"
            f"实际 {len(tool_result_blocks)}"
        )

        # 协议合规检查 3：tool_result 顺序和 tool_use 声明顺序一致
        ids_in_result = [b["tool_use_id"] for b in tool_result_blocks]
        assert ids_in_result == ["T_CONFIRM", "T_AUTO"], (
            f"tool_result 顺序应当与 tool_use 声明顺序一致，实际 {ids_in_result}"
        )

        # 协议合规检查 4：assistant 和 user(tool_result) 之间没有控制事件消息
        # （这个检查已经被 assistant_idx+1 的断言覆盖）

    finally:
        cleanup1()
        cleanup2()


# ===================================================================
# 场景 9（回归）：end_turn 不重复输出正文
# ===================================================================

def test_end_turn_reply_does_not_duplicate_streamed_text(monkeypatch):
    """
    回归保护（2026-04-25 真机现场）：
    用户问"你是什么模型"，模型回答一次，但终端显示两次——
    一次流式逐字 print，一次 main_loop.print(reply) 又把 reply 完整打印。
    根因：chat() 返回时 reply 包含了模型正文。
    
    修法：handle_end_turn_response 只返回"控制型 UI 文字"，正文走流式。
    普通 end_turn 的 reply 必须是空串。
    """
    from tests.conftest import FakeAnthropicClient, FakeResponse, FakeTextBlock
    from tests.test_main_loop import _reset_core_module

    fake = FakeAnthropicClient(
        responses=[
            # planner: 单步
            FakeResponse(
                content=[FakeTextBlock(text='{"steps_estimate": 1}')],
                stop_reason="end_turn",
            ),
            # executor: 直接 end_turn，模型说了一段话
            FakeResponse(
                content=[FakeTextBlock(text="我是 Claude，由 Anthropic 开发。")],
                stop_reason="end_turn",
            ),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    reply = chat("你是什么模型")

    # 关键断言：reply 不得含模型正文
    assert "Claude" not in reply, (
        f"reply 不应含模型正文（正文已由流式打过）——否则终端会重复显示。"
        f"实际 reply={reply!r}"
    )
    # 正文必须存在于 messages（验证模型的输出被正确持久化）
    last_assistant = [m for m in state.conversation.messages if m["role"] == "assistant"][-1]
    assert "Claude" in str(last_assistant["content"]), (
        "模型正文必须在 messages 里"
    )


# ===================================================================
# 场景 10（回归）：UI 提示不能重复模型已说过的"本步骤已完成"
# ===================================================================

def test_step_confirmation_ui_does_not_echo_model_completion_keyword(monkeypatch):
    """
    回归保护（2026-04-25 真机现场 #2）：
    模型在 end_turn 输出开头会按 prompt 要求说"**本步骤已完成**"。
    系统的 UI 提示 reply 也曾经是"本步骤已完成。回复 y 继续下一步..."。
    
    结果：用户屏幕上看到"**本步骤已完成**"出现两次——一次模型流式输出，
    一次系统 UI——感觉像系统在重复模型的话，被用户准确指出"为什么 end_turn
    后还要询问"。
    
    根因和上次"完整正文重复" 同源——都是"流式打过的内容，又被系统 print 一次"。
    
    修法：UI reply 不再含"本步骤已完成"前缀，只留用户实际需要做的指令。
    """
    from tests.conftest import FakeAnthropicClient, meta_complete_response
    from tests.test_main_loop import _reset_core_module
    from tests.test_complex_scenarios import _plan_response

    # 模型按 prompt 要求做收尾：text 里写"本步骤已完成"，再调元工具声明完成 + 打分
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "step1", "read"), ("s2", "step2", "report")]),
            meta_complete_response(
                text="**本步骤已完成**\n\n这是 step1 的产出报告...",
                score=90,
            ),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    chat("做两步任务，每步确认")
    assert state.task.status == "awaiting_plan_confirmation"

    reply = chat("y")   # plan y → step1 跑完 → 元工具 → awaiting_step

    # 关键断言：reply 不能含"本步骤已完成"——这句话模型已经说过了
    assert "本步骤已完成" not in reply, (
        f"系统 UI 提示不应重复模型已说过的'本步骤已完成'，"
        f"用户会觉得'为什么完成了还问我'。实际 reply={reply!r}"
    )
    # reply 仍然要有用户能看懂的"该做什么"指令
    assert "y" in reply.lower() and "n" in reply.lower(), (
        f"reply 应当告诉用户输入 y/n，实际 {reply!r}"
    )

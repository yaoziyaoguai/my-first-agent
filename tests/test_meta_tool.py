"""mark_step_complete 元工具集成测试。

覆盖本周新引入的完成判定协议（替代关键词匹配）：
- 分值达阈值 → 推进步骤（或进入 awaiting_step_confirmation）
- 分值未达阈值 → 步骤不推进，outstanding 注入下一轮 step block
- 元工具的 tool_use **不写 messages**（系统控制信号不污染对话）
- tool_execution_log 写入 step_index，供 task_runtime 按步隔离读
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
from tests.test_main_loop import _reset_core_module, _register_test_tool
from tests.test_complex_scenarios import _plan_response, _tool_use_resp
from config import STEP_COMPLETION_THRESHOLD


# ============================================================
# 1. 元工具达阈值：正常推进
# ============================================================

def test_meta_tool_at_threshold_advances_to_next_step(monkeypatch):
    """mark_step_complete(score=阈值) → 进入 awaiting_step_confirmation。"""
    cleanup = _register_test_tool("w", confirmation="never", result="ok")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "一", "read"), ("s2", "二", "report")]),
                # 业务工具 + 收尾元工具，分值=阈值（边界）
                _tool_use_resp("w", "T1"),
                meta_complete_response(score=STEP_COMPLETION_THRESHOLD, text="第 1 步做完"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)
        from agent.core import chat

        chat("两步任务，每步确认")
        chat("y")   # 接受 plan

        assert state.task.status == "awaiting_step_confirmation", (
            f"阈值分应当触发步骤推进到 awaiting_step，实际 {state.task.status}"
        )
        assert state.task.current_step_index == 0, (
            "awaiting_step 时 step_index 仍停在当前步骤（等用户 y 之后才 ++）"
        )
    finally:
        cleanup()


# ============================================================
# 2. 元工具低分：步骤不推进 + outstanding 注入下一轮
# ============================================================

def test_meta_tool_below_threshold_does_not_advance(monkeypatch):
    """mark_step_complete(score=阈值-1) → 步骤不推进，状态保持 running。"""
    cleanup = _register_test_tool("w", confirmation="never", result="ok")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "一", "read"), ("s2", "二", "report")]),
                # 业务工具 + 元工具打低分
                _tool_use_resp("w", "T1"),
                meta_complete_response(
                    score=STEP_COMPLETION_THRESHOLD - 1,
                    summary="只做了一半",
                    outstanding="还差 X / Y 两件事",
                    text="部分完成，需要继续",
                ),
                # 模型被再次调：下一轮 messages 里应带 outstanding 注入
                meta_complete_response(
                    score=STEP_COMPLETION_THRESHOLD + 5,
                    summary="补齐了",
                    outstanding="无",
                    text="这次真做完",
                ),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)
        from agent.core import chat

        chat("两步任务，每步确认")
        chat("y")   # 接受 plan → step1 跑完低分元工具 → 不推进，继续被调 → 高分推进

        # 最终应当推进到 awaiting_step
        assert state.task.status == "awaiting_step_confirmation", (
            f"低分 → 高分两轮后应推进到 awaiting_step，实际 {state.task.status}"
        )

        # 检查低分元工具之后的 step block 里是否注入了"上一轮自评（未达阈值）"
        # build_execution_messages 在每次 _call_model 调用前都会被执行
        # 所以 fake.requests 数量 == API 调用次数。
        # execution 请求序列：
        #   req 0：user "y" 后第一次 execution，step block 无 outstanding
        #   req 1：T1 tool_result 追加后第二次 execution（仍无 meta），无 outstanding
        #   req 2：meta_1(score=79) 记录后第三次 execution，**有** outstanding
        # 所以最后一个 execution 请求的 step block 应当含"上一轮自评"。
        exec_requests = [
            r for r in fake.requests
            if any(
                "[当前任务]" in (m.get("content") if isinstance(m.get("content"), str) else "")
                for m in r.get("messages", [])
            )
        ]
        assert len(exec_requests) >= 3, (
            f"应当有至少三次 execution 请求（T1 tool_use → tool_result → meta 低分 → 再次请求）"
            f"，实际 {len(exec_requests)}"
        )

        last_req_messages = exec_requests[-1]["messages"]
        step_block_texts = [
            m.get("content", "")
            for m in last_req_messages
            if m.get("role") == "user"
            and isinstance(m.get("content"), str)
            and "[当前任务]" in m.get("content", "")
        ]
        assert step_block_texts, "应找到 step block"
        step_block = step_block_texts[0]
        assert "上一轮自评" in step_block, (
            f"低分后下一轮 step block 必须注入'上一轮自评'段，实际 step_block="
            f"{step_block}"
        )
        assert "还差 X / Y 两件事" in step_block, (
            f"outstanding 内容应当被原样注入，实际 step_block 片段:\n"
            f"{step_block[-800:]}"
        )
    finally:
        cleanup()


# ============================================================
# 3. 元工具的 tool_use **不写** conversation messages
# ============================================================

def test_meta_tool_use_not_persisted_to_messages(monkeypatch):
    """元工具的 tool_use 块被 _serialize_assistant_content 剔除，
    不进 state.conversation.messages；也不产生 tool_result 占位。"""
    cleanup = _register_test_tool("w", confirmation="never", result="ok")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "一", "read"), ("s2", "二", "report")]),
                _tool_use_resp("w", "T1"),
                meta_complete_response(score=95, text="收尾"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)
        from agent.core import chat

        chat("两步任务，每步确认")
        chat("y")

        # 扫 messages，不应出现 tool_use(name=mark_step_complete) 或
        # tool_result(tool_use_id=meta_*)
        meta_tool_uses = []
        meta_tool_results = []
        for msg in state.conversation.messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("name") == "mark_step_complete":
                    meta_tool_uses.append(b)
                if b.get("type") == "tool_result":
                    tid = b.get("tool_use_id", "")
                    if tid.startswith("meta_"):
                        meta_tool_results.append(b)

        assert not meta_tool_uses, (
            f"元工具的 tool_use 不应当留在 messages，实际: {meta_tool_uses}"
        )
        assert not meta_tool_results, (
            f"元工具没有对应的 tool_result，messages 里不能有残留，实际: {meta_tool_results}"
        )
    finally:
        cleanup()


# ============================================================
# 4. tool_execution_log 正确写入 step_index
# ============================================================

def test_meta_tool_log_entry_tagged_with_correct_step_index(monkeypatch):
    """mark_step_complete 写 log 时必须带 step_index，否则 task_runtime
    无法按步隔离判断，跨步骤会误判。"""
    cleanup = _register_test_tool("w", confirmation="never", result="ok")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "一", "read"), ("s2", "二", "report")]),
                _tool_use_resp("w", "T1"),
                meta_complete_response(score=90, text="step1 done"),
                # 进入 step2
                _tool_use_resp("w", "T2"),
                meta_complete_response(score=90, text="step2 done"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)
        from agent.core import chat

        chat("两步任务，每步确认")
        chat("y")   # step1 跑完 → awaiting_step

        # 此时 log 里应有 step1 的 meta 记录（step_index=0）
        meta_entries = [
            e for e in state.task.tool_execution_log.values()
            if e.get("tool") == "mark_step_complete"
        ]
        assert len(meta_entries) == 1, (
            f"step1 结束时 log 里应恰好一条元工具记录，实际 {len(meta_entries)}"
        )
        assert meta_entries[0]["step_index"] == 0, (
            f"step1 的 meta 记录 step_index 应当是 0，实际 {meta_entries[0]['step_index']}"
        )

        # 业务工具也应带 step_index
        business_entries = [
            e for e in state.task.tool_execution_log.values()
            if e.get("tool") == "w"
        ]
        assert business_entries and business_entries[0].get("step_index") == 0, (
            f"业务工具 log 也要带 step_index，实际 {business_entries}"
        )
    finally:
        cleanup()


# ============================================================
# 5. mark_step_complete 不吃 per-turn tool_call_count 配额
# ============================================================

def test_meta_tool_does_not_count_toward_tool_call_limit(monkeypatch):
    """元工具是控制信号，不应把 MAX_TOOL_CALLS_PER_TURN 占掉——否则
    长任务里每步都调一次元工具，配额会被多消费一个。"""
    cleanup = _register_test_tool("w", confirmation="never", result="ok")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "一", "read"), ("s2", "二", "report")]),
                # 一轮里：1 个业务工具 + 1 个元工具
                FakeResponse(
                    content=[
                        FakeTextBlock(text="走起"),
                        FakeToolUseBlock(id="T1", name="w", input={"arg": "x"}),
                        FakeToolUseBlock(
                            id="meta_1",
                            name="mark_step_complete",
                            input={
                                "completion_score": 92,
                                "summary": "一步到位",
                                "outstanding": "无",
                            },
                        ),
                    ],
                    stop_reason="tool_use",
                ),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)
        from agent.core import chat

        chat("两步任务，每步确认")
        chat("y")

        # tool_call_count 只计 1（业务工具），不计元工具
        assert state.task.tool_call_count == 1, (
            f"业务工具应计 1，元工具不应计入，实际 tool_call_count="
            f"{state.task.tool_call_count}"
        )
        assert state.task.status == "awaiting_step_confirmation"
    finally:
        cleanup()


# ============================================================
# 6. request_user_input：执行期求助元工具，loop 暂停 + step 不推进
# ============================================================

def _request_user_input_response(
    question: str,
    why_needed: str,
    options: list[str] | None = None,
    context: str = "",
    tool_id: str = "ru_1",
    text: str | None = None,
) -> FakeResponse:
    """构造一次"模型在普通 step 里调用 request_user_input"的响应。"""
    blocks: list = []
    if text:
        blocks.append(FakeTextBlock(text=text))
    blocks.append(FakeToolUseBlock(
        id=tool_id,
        name="request_user_input",
        input={
            "question": question,
            "why_needed": why_needed,
            "options": options or [],
            "context": context,
        },
    ))
    return FakeResponse(content=blocks, stop_reason="tool_use")


def test_request_user_input_pauses_loop_in_normal_step(monkeypatch):
    """普通 read step 里模型调 request_user_input：
    - status 切到 awaiting_user_input；pending_user_input_request 写好
    - step_index 不推进
    - messages 里**不**出现 tool_use(request_user_input) 或 tool_result
    - 用户回复后：step 继续做（不推进），messages 里有"用户针对问题..."的 step_input
    - 再调 mark_step_complete 才推进 step。
    """
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "读项目", "read"), ("s2", "出报告", "report")]),
            # step1：模型决定求助
            _request_user_input_response(
                question="项目根目录在哪里？",
                why_needed="无路径无法 read_file",
                options=["./agent", "/abs/path"],
                context="用户说想读 main.py",
                text="我需要先确认路径",
            ),
            # 用户回 "./agent" 后，下一轮模型继续做 step1，这次直接打分收尾
            meta_complete_response(score=90, text="读完了", tool_id="meta_after_resume"),
            # step1 推进到 step2 后，loop 继续调模型；让 step2 也直接打分结束
            meta_complete_response(score=95, text="出报告完成", tool_id="meta_step2"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)
    from agent.core import chat

    chat("两步任务")
    chat("y")  # 接受 plan → 进入 step1 → 模型调 request_user_input

    # ---- 求助暂停态 ----
    assert state.task.status == "awaiting_user_input", (
        f"求助后 status 应当为 awaiting_user_input，实际 {state.task.status}"
    )
    pending = state.task.pending_user_input_request
    assert pending is not None, "pending_user_input_request 必须被写入"
    assert pending["awaiting_kind"] == "request_user_input"
    assert pending["question"] == "项目根目录在哪里？"
    assert pending["why_needed"] == "无路径无法 read_file"
    assert pending["options"] == ["./agent", "/abs/path"]
    assert pending["context"] == "用户说想读 main.py"
    assert pending["tool_use_id"] == "ru_1"
    assert pending["step_index"] == 0
    assert state.task.current_step_index == 0, "step_index 不能在求助时推进"
    assert len(fake.requests) == 1, (
        "request_user_input 是阻塞式 runtime 事件；模型调用后本轮 loop 必须停住，"
        "不能同一轮继续请求模型导致重复追问"
    )

    # ---- messages 干净：没有 request_user_input 的 tool_use / tool_result ----
    for msg in state.conversation.messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            assert not (
                b.get("type") == "tool_use" and b.get("name") == "request_user_input"
            ), f"request_user_input 的 tool_use 不应进 messages: {b}"
            if b.get("type") == "tool_result":
                assert b.get("tool_use_id") != "ru_1", (
                    f"request_user_input 不应生成 tool_result: {b}"
                )

    # ---- 用户回复 ----
    chat("./agent")

    # 求助分支应当：清 pending、status=running、step 仍未推进、再调 _call_model
    # 然后这一轮模型 mark_step_complete(90) 触发 step 推进，再继续做 step2 mark 收尾任务。
    # 注意：本测试 user 输入里没有"每步确认"关键词，所以 confirm_each_step=False，
    # mark 后 _maybe_advance_step 直接 advance 而不是 awaiting_step_confirmation。
    assert state.task.pending_user_input_request is None, "pending 必须被清空"
    # step1 mark→推 step2，step2 mark→任务完成，state 被 reset
    assert state.task.status in ("idle", "done"), (
        f"两步 mark 后任务应已收尾，实际 status={state.task.status}"
    )

    # ---- 下一轮上下文里要能看到「问的是什么 / 为什么 / 用户答了什么」 ----
    step_input_seen = False
    for msg in state.conversation.messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                txt = b.get("text", "")
                if "项目根目录在哪里？" in txt and "./agent" in txt and "无路径无法" in txt:
                    step_input_seen = True
                    break
    assert step_input_seen, (
        "step_input 渲染应在 messages 里包含 question / 用户答复 / why_needed"
    )


def test_request_user_input_clears_stale_mark_step_complete(monkeypatch):
    """B 防御回归：模型若**违反纪律**同轮里既调 mark_step_complete 又调 request_user_input，
    必须清掉当前 step 的 mark_step_complete log——否则用户答复后下一轮 _maybe_advance_step
    会读到残留分值，错误推进 step。

    验证策略：进入暂停态后，直接检查
    1) tool_execution_log 里当前 step_index 的 mark_step_complete 记录已被清除
    2) is_current_step_completed(state) 返回 False（确保 _maybe_advance_step
       下一轮不会被残留分值误导推进 step）
    """
    from agent.task_runtime import is_current_step_completed

    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "读项目", "read"), ("s2", "出报告", "report")]),
            # step1：违反纪律——同一轮里 mark(90) + request_user_input
            FakeResponse(
                content=[
                    FakeTextBlock(text="想收尾但又卡了"),
                    FakeToolUseBlock(
                        id="meta_bad",
                        name="mark_step_complete",
                        input={
                            "completion_score": 90,
                            "summary": "似乎完成了",
                            "outstanding": "无",
                        },
                    ),
                    FakeToolUseBlock(
                        id="ru_bad",
                        name="request_user_input",
                        input={
                            "question": "等等，根目录是？",
                            "why_needed": "想确认一下",
                            "options": [],
                            "context": "",
                        },
                    ),
                ],
                stop_reason="tool_use",
            ),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)
    from agent.core import chat

    chat("两步任务")
    chat("y")  # 进 step1 → 同轮 mark+request → 暂停

    # 暂停态 sanity
    assert state.task.status == "awaiting_user_input"
    assert state.task.pending_user_input_request is not None

    # 关键断言 1：当前 step 的 mark_step_complete log 应已被清除
    current_idx = state.task.current_step_index
    stale = [
        e for e in state.task.tool_execution_log.values()
        if e.get("tool") == "mark_step_complete" and e.get("step_index") == current_idx
    ]
    assert not stale, (
        f"request_user_input 必须清掉当前 step 的 mark_step_complete log，"
        f"实际残留 {stale}"
    )

    # 关键断言 2：is_current_step_completed 必须返回 False，确保用户答复后
    # _maybe_advance_step 不会被残留分值误判推进 step。
    assert is_current_step_completed(state) is False, (
        "残留 mark 已清 → 当前 step 不应被识别为已完成；否则用户回复后会被错误推进"
    )


# ============================================================
# 7. 多字段用户回复完整进入下一轮 messages
# ============================================================

def test_multi_field_user_reply_fully_persisted_to_messages(monkeypatch):
    """request_user_input 触发 awaiting_user_input 后，用户长回复（多字段）应当
    完整以 step_input 形态写入 messages，让模型在下一轮上下文里能看到所有字段。

    注意：本测试不经过 main.py 的 input()，所以不会被多行截断；这条只验证
    step_input 渲染层不会丢字段。终端 UX 层的多行截断是单独问题。
    """
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "规划", "read"), ("s2", "出方案", "report")]),
            _request_user_input_response(
                question="出行细节是什么？",
                why_needed="无细节无法做规划",
                tool_id="ru_multi",
                text="先问几个细节",
            ),
            # 后面让 step1 直接 mark 收尾，避免响应不够
            meta_complete_response(score=90, text="收尾", tool_id="meta_after_multi"),
            meta_complete_response(score=95, text="收尾 step2", tool_id="meta_step2_multi"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)
    from agent.core import chat

    chat("两步任务")
    chat("y")  # 进 step1 → 求助 → 暂停

    assert state.task.status == "awaiting_user_input"

    # 模拟用户一次性输入完整 6 字段长回复
    long_reply = (
        "下周一到周三出行；从北京出发偏好高铁；豪华型住宿；"
        "主要看自然风光；单人出行；预算在 5000 元以内"
    )
    chat(long_reply)

    # 在 messages 里搜含 question + 用户回复全字段的 step_input 渲染
    found_text = None
    for msg in state.conversation.messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text", "")
                if "出行细节是什么" in t and "下周一到周三" in t:
                    found_text = t
                    break
        if found_text:
            break

    assert found_text, "step_input 必须把 question + 用户回复一起写进 messages"

    # 关键字段都必须保留
    expected_keywords = [
        "下周一到周三", "北京", "高铁", "豪华型",
        "自然风光", "单人", "5000",
    ]
    missing = [kw for kw in expected_keywords if kw not in found_text]
    assert not missing, (
        f"step_input 渲染丢字段：{missing}\n实际渲染：{found_text}"
    )


# ============================================================
# 8. 启发式兜底：assistant 文本含问号但没 tool_use → 切 awaiting_user_input
# ============================================================

def test_endturn_with_question_text_triggers_pause(monkeypatch):
    """模型违反协议：用普通文本向用户提问然后 end_turn，没调任何工具。
    系统必须立即切 awaiting_user_input，避免硬塞"请打分"导致死循环。
    """
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "规划", "read"), ("s2", "出方案", "report")]),
            # 模型违反协议：文本含问号 + end_turn + 无 tool_use
            text_response(
                "为了帮你规划，我需要知道你的预算大概是多少？另外出发地是哪里？",
                stop="end_turn",
            ),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)
    from agent.core import chat

    chat("两步任务")
    chat("y")  # 进 step1 → 模型走 end_turn 散问

    # 启发式兜底应当立即切 awaiting_user_input
    assert state.task.status == "awaiting_user_input", (
        f"启发式兜底未生效，实际 status={state.task.status}"
    )
    pending = state.task.pending_user_input_request
    assert pending is not None, "必须写入 pending_user_input_request"
    assert pending["awaiting_kind"] == "fallback_question"
    assert "预算" in pending["question"] and "出发地" in pending["question"], (
        f"pending.question 应当保留 assistant 原文，实际={pending['question']}"
    )
    assert "模型未调用 request_user_input" in pending["why_needed"]
    assert state.task.current_step_index == 0, "兜底不能推进 step"


# ============================================================
# 9. 计数兜底：连续 2 次 end_turn 无工具调用 → 切 awaiting_user_input
# ============================================================

def test_two_consecutive_endturns_without_progress_trigger_pause(monkeypatch):
    """模型连续 2 次 end_turn，文本里没有问号、也没"请告诉我"等启发式词，
    且没调任何工具。这种"默默卡住"启发式漏判，必须靠计数器兜底。
    """
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "规划", "read"), ("s2", "出方案", "report")]),
            # 第 1 次：陈述句，启发式不命中（无问号、无求助词）
            text_response("我正在思考下一步该怎么办", stop="end_turn"),
            # 第 2 次：依旧陈述句，但 counter 已经达 2，必须强停
            text_response("继续思考中", stop="end_turn"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)
    from agent.core import chat

    chat("两步任务")
    chat("y")

    # 计数兜底应当在第 2 次 end_turn 强制暂停
    assert state.task.status == "awaiting_user_input", (
        f"计数兜底未生效（应当在连续 2 次 end_turn 后切到 awaiting_user_input），"
        f"实际 status={state.task.status}"
    )
    pending = state.task.pending_user_input_request
    assert pending is not None
    assert pending["awaiting_kind"] == "no_progress"
    assert "继续思考中" in pending["question"], (
        f"pending.question 应当是最近一次 assistant 文本，实际={pending['question']}"
    )
    assert "模型未调用 request_user_input" in pending["why_needed"]
    assert state.task.consecutive_end_turn_without_progress >= 2


# ============================================================
# 10. 任意工具调用清零计数器
# ============================================================

def test_tool_call_resets_endturn_counter(monkeypatch):
    """end_turn → counter=1；下一轮调任意工具（业务/元）→ counter=0。
    保证模型从"卡壳"中恢复时不会被旧计数误伤强制暂停。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="ok")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "规划", "read"), ("s2", "出方案", "report")]),
                # 第 1 轮：陈述句 end_turn → counter=1，软驱动注入提示
                text_response("先想想", stop="end_turn"),
                # 第 2 轮：模型听话，调业务工具 → counter 必须清零
                _tool_use_resp("w", "T_resume"),
                # 第 3 轮：mark step1 收尾
                meta_complete_response(score=90, text="step1 完", tool_id="meta_resume_1"),
                # step2 收尾
                meta_complete_response(score=95, text="step2 完", tool_id="meta_resume_2"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)
        from agent.core import chat

        chat("两步任务")
        chat("y")

        # 任务应当走完，counter 已被清零
        assert state.task.consecutive_end_turn_without_progress == 0, (
            f"工具调用必须清零计数器，实际 counter="
            f"{state.task.consecutive_end_turn_without_progress}"
        )
        # 任务收尾
        assert state.task.status in ("idle", "done"), (
            f"两步 mark 后任务应已收尾，实际 status={state.task.status}"
        )
    finally:
        cleanup()

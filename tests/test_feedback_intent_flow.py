"""P1 topic-switch 设计的 tests-first 失败测试集。

对应设计稿：`docs/P1_TOPIC_SWITCH_PLAN.md`（commit 54a39e3）。

============================================================
本文件保护的架构边界（学习型注释）
============================================================

这些测试一律**先 fail**，目的是把"在不破红线的前提下，Runtime 怎样处理
plan / step confirmation 阶段收到的 free-form 文本"这件事写成可执行规范。
红线（与设计稿 §3 一致）：

1. **不允许恢复 slash command 字符串协议**（`/xxx` 形式）。
2. **不允许引入关键词黑名单 / imperative-prefix / no-overlap / min-length /
   字符重叠率等任何浅层启发式**。
3. **不允许引入 LLM 二次分类器**用来在 confirm_handlers 内部猜意图。
4. **不允许改 checkpoint schema 顶层字段**——`task.status` 集合可以多一个
   显式枚举值，但 task 的字段集合不增不减。
5. **InputIntent / RuntimeEvent / DisplayEvent 不能写入 messages 或
   checkpoint**；messages 必须保持 append-only；
   `context_builder._project_to_api` 仍只是 Anthropic API messages 的投影
   边界，不能在 P1 里增减它的职责。

正向规范：
- 在 `awaiting_plan_confirmation` / `awaiting_step_confirmation` 阶段，
  收到 `classify_confirmation_response == "feedback"` 的文本时，
  Runtime 必须**不立刻**调 planner / 不立刻写 plan_feedback control event /
  不污染 `state.task.user_goal`，而是切到一个新的 awaiting 子状态
  `awaiting_feedback_intent`，并通过 `RuntimeEvent` 让用户**显式**选择：
    [1] 当作对当前计划的修改意见
    [2] 切换为新任务
    [3] 取消（保持当前计划）
- 用户精确选 1/2/3 才分流；任何模糊输入仅重发同一 RuntimeEvent，状态/
  pending/messages 完全不变。
- 选 [2] 走 `state.reset_task() + _run_planning_phase(new_input)`，
  与正常新任务入口完全同构，新 plan 的 `user_goal` == 新话题原文，绝不
  与旧目标拼接。

每个测试的注释会指出：(a) 它保护哪条边界；(b) 当前为什么会 fail；
(c) 修复方向（不允许走的捷径）。
"""

from __future__ import annotations

from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
)
from tests.test_main_loop import (
    _reset_core_module,
    _register_test_tool,
)
from tests.test_complex_scenarios import (
    _plan_response,
    _tool_use_resp,
)
from tests.conftest import meta_complete_response, text_response  # noqa: F401


# ============================================================
# 设计稿里规划的（尚未实现）RuntimeEvent 类型字面值。
# 这里用字符串而非 import，是为了让测试本身就是规范来源——
# 当真正在 agent/display_events.py 添加常量时，常量值必须等于这里的
# 字符串。这样可以避免"测试只能在新代码后才能写"的死循环。
# ============================================================
EVENT_FEEDBACK_INTENT_REQUESTED = "feedback.intent_requested"
AWAITING_FEEDBACK_INTENT_STATUS = "awaiting_feedback_intent"
AWAITING_KIND_FEEDBACK_INTENT = "feedback_intent"


# ----------------------------------------------------------------
# 共享小工具
# ----------------------------------------------------------------

def _drive_to_awaiting_step_confirmation(monkeypatch):
    """走到 `awaiting_step_confirmation` 状态的固定脚手架。

    步骤：
    - planner 出 2 步 plan（保证不被 single-step 短路）。
    - 模型执行 step1 的 tool_use → mark_step_complete (score=90)。
    - 因为 user_goal 含 "每步确认"，`confirm_each_step=True`，
      step 收尾后 status 切到 `awaiting_step_confirmation`。

    返回：(state, fake_client, cleanup_tool)
    """

    cleanup = _register_test_tool("w", confirmation="never", result="done")
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([
                ("s1", "原任务-s1", "read"),
                ("s2", "原任务-s2", "report"),
            ]),
            _tool_use_resp("w", "T1"),
            meta_complete_response(text="step1 完成"),
            # 后续测试可能继续 push 响应（重新规划等）
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    chat("原任务：分析文档，每步确认")
    chat("y")
    assert state.task.status == "awaiting_step_confirmation", (
        f"测试脚手架前置条件不满足：期望 awaiting_step_confirmation，"
        f"实际 status={state.task.status}。这通常意味着 fake 响应序列与"
        f"主循环执行路径不一致，请先排查 fake 设置。"
    )
    return state, fake, cleanup


def _drive_to_awaiting_plan_confirmation(monkeypatch):
    """走到 `awaiting_plan_confirmation` 状态。"""

    cleanup = _register_test_tool("w", confirmation="never", result="done")
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([
                ("p1", "原计划-s1", "read"),
                ("p2", "原计划-s2", "report"),
            ]),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    chat("原任务：分析文档")
    assert state.task.status == "awaiting_plan_confirmation"
    return state, fake, cleanup


def _collect_runtime_events():
    """返回 (events_list, sink)，sink 可作为 `chat(on_runtime_event=...)` 入参。"""

    events: list = []

    def sink(event):
        events.append(event)

    return events, sink


def _messages_text_blob(state) -> str:
    """把 conversation.messages 拼成纯文本，便于断言 control event 文案是否出现。"""

    out: list[str] = []
    for msg in state.conversation.messages:
        content = msg.get("content")
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str):
                        out.append(text)
    return "\n".join(out)


def _has_event(events, event_type: str) -> bool:
    return any(getattr(e, "event_type", None) == event_type for e in events)


# ============================================================
# 测试 1：明显新任务的 feedback **必须**不污染 user_goal
# ============================================================

def test_step_feedback_with_obvious_new_task_does_not_pollute_user_goal(monkeypatch):
    """保护边界：`state.task.user_goal` 在 awaiting_step_confirmation 收到
    free-form 文本时，**不应**立即被任何"feedback 拼接 / 新任务覆盖"逻辑
    触碰，**也不应**触发 planner 重新生成 plan。

    这是 P1 的核心断言：在用户尚未明确表达"反馈 vs 新任务"之前，Runtime
    必须保持静默——既不能默认按 feedback（旧实现行为），也不能默认按新任务。

    当前会 fail：现行 `handle_step_confirmation` 把任何非 yes/no 都按
    feedback 处理，`current_plan` 会被立即换成新 plan，`status` 会变成
    `awaiting_plan_confirmation`。

    修复方向（不允许走的捷径）：
    - ❌ 不能用关键词词表（"帮我"/"另外" 等）猜"这是新任务"；
    - ❌ 不能用 plan 词表零字符重叠率猜；
    - ❌ 不能加一次 LLM 调用让模型分类。
    - ✅ 应当切到 `awaiting_feedback_intent` 让用户在下一轮显式选择。
    """

    state, fake, cleanup = _drive_to_awaiting_step_confirmation(monkeypatch)
    try:
        # 准备 P1 实现后的两条可能后续响应（选 [1] 或 [2] 时各自需要的 plan 重生成）。
        # 当前实现下不会用到，但留着保证 fake 不会因为提前耗尽响应而报"列表给短了"。
        fake.responses.extend([
            _plan_response([("n1", "新-s1", "read"), ("n2", "新-s2", "report")]),
            _plan_response([("m1", "改-s1", "read"), ("m2", "改-s2", "report")]),
        ])

        from agent.core import chat

        original_goal = state.task.user_goal
        original_plan_dump = dict(state.task.current_plan or {})

        chat("帮我写一首关于春天的诗")

        # 边界 1：user_goal 不应被任何方式污染（既不拼旧目标，也不被新话题
        # 直接覆盖——覆盖意味着已经悄悄当作新任务处理了）。
        assert state.task.user_goal == original_goal, (
            f"awaiting_step_confirmation 收到模糊 free-form 文本时，user_goal "
            f"必须保持不变。实际从 {original_goal!r} 变成 {state.task.user_goal!r}。"
        )

        # 边界 2：current_plan 不应被立即重生成——重生成等于默认按 feedback。
        assert state.task.current_plan == original_plan_dump, (
            "P1 红线：在用户明确选择前，不允许立即调 planner 重新生成 plan。"
            "现行实现是把任何非 yes/no 都当作 feedback，违反此红线。"
        )

        # 边界 3：状态应进入新的 awaiting_feedback_intent 子状态。
        assert state.task.status == AWAITING_FEEDBACK_INTENT_STATUS, (
            f"P1 应将 status 切到 {AWAITING_FEEDBACK_INTENT_STATUS!r}，让用户"
            f"通过 RuntimeEvent 显式选择。实际 status={state.task.status!r}。"
        )
    finally:
        cleanup()


# ============================================================
# 测试 2：模糊 feedback 不能写入 plan_feedback control event
# ============================================================

def test_step_feedback_does_not_append_plan_feedback_event_to_messages_before_user_choice(monkeypatch):
    """保护边界：messages append-only，且 control event 一旦写入就再也无法
    撤销。所以"反馈归属未定"时**绝不能**写 plan_feedback——否则用户接下来
    选 [2] 切新任务时，messages 里仍会留下一条"用户对计划的修改意见：…"，
    污染下一次 planner 上下文。

    当前会 fail：`handle_step_confirmation` 在 feedback 分支立刻调
    `append_control_event(messages, "plan_feedback", ...)`。

    修复方向：把 `append_control_event` 推迟到用户在 awaiting_feedback_intent
    阶段确认选择 [1] 之后再写。选 [2]/[3] 不得写。
    """

    state, fake, cleanup = _drive_to_awaiting_step_confirmation(monkeypatch)
    try:
        fake.responses.extend([
            _plan_response([("n1", "新-s1", "read"), ("n2", "新-s2", "report")]),
        ])

        from agent.core import chat

        chat("帮我写一首关于春天的诗")

        blob = _messages_text_blob(state)
        assert "帮我写一首关于春天的诗" not in blob, (
            "在用户尚未确认归属前，feedback 文本不允许出现在 conversation.messages 里。"
            "否则用户后续选[2]切新任务时旧反馈会污染新 planner 上下文（messages "
            "是 append-only，无法事后撤销）。"
        )
        assert "用户对计划提出了修改意见" not in blob, (
            "P1 红线：plan_feedback control event 必须推迟到分流后、且仅在用户"
            "确认 [1] 当作反馈时才写入。"
        )
    finally:
        cleanup()


# ============================================================
# 测试 3：必须发出 feedback.intent_requested RuntimeEvent
# ============================================================

def test_feedback_intent_request_emits_runtime_event(monkeypatch):
    """保护边界：Runtime → UI 的"模糊请求 → 用户选择"必须走 RuntimeEvent
    出口，**不**能通过 print / stdout / control_message 任意一条短路实现。
    这样 Textual / simple CLI 共用同一条投影边界。

    当前会 fail：根本没有这个事件类型。

    修复方向：`agent/display_events.py` 新增常量
    `EVENT_FEEDBACK_INTENT_REQUESTED = "feedback.intent_requested"` 和
    helper `feedback_intent_requested(pending)`，在 confirm_handlers 切到
    awaiting_feedback_intent 时同步发出。事件 payload 必须可被 Textual
    既有 `render_runtime_event_for_cli` 兜底渲染，不能新建 sink 协议。
    """

    state, fake, cleanup = _drive_to_awaiting_step_confirmation(monkeypatch)
    try:
        fake.responses.extend([
            _plan_response([("n1", "新-s1", "read"), ("n2", "新-s2", "report")]),
        ])

        from agent.core import chat
        events, sink = _collect_runtime_events()
        chat("帮我写一首关于春天的诗", on_runtime_event=sink)

        assert _has_event(events, EVENT_FEEDBACK_INTENT_REQUESTED), (
            f"应至少发出一条 {EVENT_FEEDBACK_INTENT_REQUESTED!r} RuntimeEvent。"
            f"实际收到的事件类型：{[getattr(e, 'event_type', None) for e in events]}"
        )

        # pending_user_input_request 应承载分流上下文，且 awaiting_kind 必须是新值。
        pending = state.task.pending_user_input_request or {}
        assert pending.get("awaiting_kind") == AWAITING_KIND_FEEDBACK_INTENT, (
            f"P1 复用 pending_user_input_request 字段，仅通过 awaiting_kind "
            f"={AWAITING_KIND_FEEDBACK_INTENT!r} 区分新分流路径，"
            f"避免新增 task 顶层字段（保持 checkpoint schema 不变）。"
            f"实际 pending={pending!r}"
        )
    finally:
        cleanup()


# ============================================================
# 测试 4：选 [2] = 切新任务 → user_goal 是新话题原文
# ============================================================

def test_choosing_as_new_task_resets_user_goal_to_new_input(monkeypatch):
    """保护边界：选 [2] 等同于"用户主动开新任务"，应走与正常 chat() 新任务
    入口**完全同构**的路径——`state.reset_task()` + `_run_planning_phase
    (new_input)`。新 plan 的 user_goal 必须直接等于新话题原文，不与旧目标
    拼接，与 c252695 保留的"feedback 不污染 user_goal"收益一致。

    当前会 fail：feedback_intent 流程未实现，第一步就走错。

    修复方向：handle_feedback_intent_choice 的 as_new_task 分支必须显式调
    reset_task + clear_checkpoint + _run_planning_phase；不能"复用 feedback
    路径再补一次 user_goal = new_input"——那样会让 messages 残留旧 plan 的
    control events 与新 user_goal 错位。
    """

    state, fake, cleanup = _drive_to_awaiting_step_confirmation(monkeypatch)
    try:
        # 第二步：用户选 [2] 后系统按新任务重规划，需要 1 条 planner 响应。
        fake.responses.extend([
            _plan_response([("n1", "新-s1", "report"), ("n2", "新-s2", "report")]),
        ])

        from agent.core import chat

        chat("帮我写一首关于春天的诗")
        chat("2")

        assert state.task.user_goal is not None, "user_goal 不应为 None"
        assert "春天的诗" in state.task.user_goal, (
            f"选 [2] 切新任务后，user_goal 应包含新话题原文。"
            f"实际 user_goal={state.task.user_goal!r}"
        )
        assert "分析文档" not in state.task.user_goal, (
            f"切新任务后绝不能与旧目标拼接。"
            f"实际 user_goal={state.task.user_goal!r}"
        )
    finally:
        cleanup()


# ============================================================
# 测试 5：选 [1] = 当反馈处理 → 行为等价于原 feedback 路径
# ============================================================

def test_choosing_as_feedback_resumes_plan_feedback_path(monkeypatch):
    """保护边界：选 [1] 后行为应**等价**于现行 feedback 直接路径——
    生成 revised_goal（仅本地，不写回 user_goal）→ planner 重出 plan →
    新 plan 进 awaiting_plan_confirmation → messages 出现一条
    `plan_feedback` control event（且只出现 1 条，对应分流后的写入时机）。

    这条测试同时是 hardcore #6"plan_feedback 不累积 user_goal" 在新路径下
    的延伸保护：选 [1] 重复多次也不应让 user_goal 膨胀。
    """

    state, fake, cleanup = _drive_to_awaiting_step_confirmation(monkeypatch)
    try:
        fake.responses.extend([
            _plan_response([("r1", "改-s1", "read"), ("r2", "改-s2", "report")]),
        ])

        from agent.core import chat

        original_goal = state.task.user_goal
        chat("第二步先别写报告，先做 review")  # 这是真实反馈，不是新任务
        chat("1")

        assert state.task.user_goal == original_goal, (
            "选 [1] 当反馈处理后，user_goal 应保持不变（与现行 feedback 路径"
            "一致——只组装本地 revised_goal 喂 planner，不写回 task 状态）。"
        )
        assert state.task.status == "awaiting_plan_confirmation", (
            f"重生成 plan 后应进入 awaiting_plan_confirmation 等待用户确认，"
            f"实际 status={state.task.status!r}"
        )

        blob = _messages_text_blob(state)
        # 反馈文案在分流后应当被写入 messages（且仅写一次）。
        assert blob.count("第二步先别写报告，先做 review") == 1, (
            "选 [1] 后 plan_feedback control event 应当被写入 messages 且只 1 次。"
            "若 0 次：分流逻辑遗漏写入；若 >=2 次：feedback 被重复 append。"
        )
    finally:
        cleanup()


# ============================================================
# 测试 6：选 [3] = 取消 → 完全无副作用，回到原 awaiting 状态
# ============================================================

def test_choosing_cancel_restores_original_awaiting_status_with_no_side_effect(monkeypatch):
    """保护边界：选 [3] 取消应彻底无副作用——
    - status 回到原 awaiting_step_confirmation；
    - user_goal 不变、current_plan 不变；
    - messages **没有**新增任何 control event（plan_feedback 也不写）；
    - pending_user_input_request 已清空；
    - 不调 planner（避免无谓 LLM 调用）。

    这条测试也防御一种潜在错误实现：把"取消"做成"等价于反馈但跳过 planner
    调用"——那样仍会写 plan_feedback 文案，破坏"无副作用"语义。
    """

    state, fake, cleanup = _drive_to_awaiting_step_confirmation(monkeypatch)
    try:
        from agent.core import chat

        before_messages_len = len(state.conversation.messages)
        before_goal = state.task.user_goal
        before_plan = dict(state.task.current_plan or {})
        # planner 不应被再次调用——不准备额外 plan 响应；若被调用就会抛"列表给短了"。

        chat("帮我写一首关于春天的诗")
        # 此时本应进入 awaiting_feedback_intent；继续选 [3] 取消。
        chat("3")

        assert state.task.status == "awaiting_step_confirmation", (
            f"取消后必须回到原 awaiting 状态。实际 status={state.task.status!r}"
        )
        assert state.task.user_goal == before_goal
        assert state.task.current_plan == before_plan
        assert state.task.pending_user_input_request is None, (
            "取消后必须清空 pending_user_input_request，否则下一轮输入会被误认作"
            "对旧问题的答复。"
        )

        blob_after = _messages_text_blob(state)
        # 取消路径不允许把 free-form 文本或反馈文案以任何形式写入 messages。
        assert "帮我写一首关于春天的诗" not in blob_after, (
            "取消路径不应把用户输入的模糊文本写入 conversation.messages。"
        )
        assert "用户对计划提出了修改意见" not in blob_after, (
            "取消路径不应写入 plan_feedback control event。"
        )
        # messages 长度可以因为 awaiting_feedback_intent 触发时重新 emit prompt 而
        # 完全不变（RuntimeEvent 不入 messages）。允许严格不变。
        assert len(state.conversation.messages) == before_messages_len, (
            f"取消路径应保持 messages 长度不变（RuntimeEvent 不入 messages）。"
            f"实际从 {before_messages_len} 变成 {len(state.conversation.messages)}。"
        )
    finally:
        cleanup()


# ============================================================
# 测试 7：模糊选择 → 仅重发 RuntimeEvent，状态/messages 完全不变
# ============================================================

def test_ambiguous_choice_reissues_prompt_without_state_change(monkeypatch):
    """红线测试：在 awaiting_feedback_intent 状态下，**任何**不在
    {1, 2, 3} 精确集合的输入都必须被视为"模糊"，仅重发同一 RuntimeEvent。

    系统**不允许**：
    - ❌ 把"请把第二步改成先分析"这种"看起来像反馈"的文本启发式判定为 [1]；
    - ❌ 调用 LLM 二次分类来判定意图；
    - ❌ 写入 messages 或修改 pending_user_input_request。

    这是 P1 最重要的红线守护测试——它直接证明系统不会因为输入"看起来像
    XX"就猜成 XX。
    """

    state, fake, cleanup = _drive_to_awaiting_step_confirmation(monkeypatch)
    try:
        from agent.core import chat
        events, sink = _collect_runtime_events()

        chat("帮我写一首关于春天的诗", on_runtime_event=sink)
        # 此时应在 awaiting_feedback_intent。
        snap_status = state.task.status
        snap_pending = dict(state.task.pending_user_input_request or {})
        snap_messages_len = len(state.conversation.messages)
        snap_goal = state.task.user_goal
        snap_plan = dict(state.task.current_plan or {})

        events.clear()
        # 故意输入"看起来像反馈"的文本——红线下系统不允许猜成 [1]。
        chat("请把第二步改成先分析", on_runtime_event=sink)

        assert state.task.status == snap_status, (
            f"模糊输入不允许改变 status。实际从 {snap_status!r} 变成 "
            f"{state.task.status!r}——可能是被启发式判定为 [1] 走了反馈路径。"
        )
        assert dict(state.task.pending_user_input_request or {}) == snap_pending, (
            "模糊输入不允许改写 pending_user_input_request（包括 question / "
            "options / pending_feedback_text 等任何字段）。"
        )
        assert len(state.conversation.messages) == snap_messages_len, (
            "模糊输入不允许 append 任何 control event 到 messages。"
        )
        assert state.task.user_goal == snap_goal
        assert state.task.current_plan == snap_plan

        assert _has_event(events, EVENT_FEEDBACK_INTENT_REQUESTED), (
            f"模糊输入应触发同一 RuntimeEvent 重新发出。"
            f"实际事件类型：{[getattr(e, 'event_type', None) for e in events]}"
        )
    finally:
        cleanup()


# ============================================================
# 测试 8：plan_confirmation 阶段同样走 feedback_intent 分流
# ============================================================

def test_plan_confirmation_with_obvious_new_task_also_uses_feedback_intent_request(monkeypatch):
    """保护边界：plan/step confirmation 是对称的两个 awaiting 子状态，
    free-form 处理逻辑必须共用同一条分流。否则会出现"plan 阶段被旧逻辑
    污染、step 阶段已经修复"的不一致。

    当前会 fail：handle_plan_confirmation feedback 分支与 step 同形，仍
    立即调 planner 重生成。
    """

    state, fake, cleanup = _drive_to_awaiting_plan_confirmation(monkeypatch)
    try:
        fake.responses.extend([
            _plan_response([("n1", "新-s1", "read"), ("n2", "新-s2", "report")]),
        ])

        from agent.core import chat
        original_goal = state.task.user_goal
        original_plan_dump = dict(state.task.current_plan or {})

        chat("帮我写一首关于春天的诗")

        assert state.task.user_goal == original_goal
        assert state.task.current_plan == original_plan_dump
        assert state.task.status == AWAITING_FEEDBACK_INTENT_STATUS
    finally:
        cleanup()


# ============================================================
# 测试 9：awaiting_user_input + pending 路径不被 feedback_intent 干扰
# ============================================================

def test_request_user_input_pending_path_not_confused_with_feedback_intent(monkeypatch):
    """保护边界：`awaiting_user_input + pending_user_input_request != None`
    是 request_user_input 元工具触发的"执行期求助"路径，由
    `transitions.apply_user_replied_transition` 的 runtime_user_input_answer
    分支处理。它**不能**被 P1 的 feedback_intent 分流误吃。

    具体而言：用户在该状态下输入 "2" 时，应当走 step_input 写入 + status=
    running + 继续主循环；**不**应当被 P1 的"选 [2] 切新任务"分支匹配。

    互不干扰的关键在于 status 区分（awaiting_user_input vs
    awaiting_feedback_intent），而不是字符串"2"本身的语义。
    """

    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        # 准备两条响应：第 1 条让模型在 step1 调 request_user_input；
        # 第 2 条让模型在用户回复后正常 mark_step_complete 收尾本步。
        from tests.conftest import FakeToolUseBlock

        request_user_input_resp = FakeResponse(
            content=[FakeToolUseBlock(
                id="ru1",
                name="request_user_input",
                input={
                    "question": "你想要 A 还是 B？",
                    "why_needed": "二选一才能继续",
                    "options": ["A", "B"],
                    "context": "",
                },
            )],
            stop_reason="tool_use",
        )
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([
                    ("s1", "原任务-s1", "read"),
                    ("s2", "原任务-s2", "report"),
                ]),
                request_user_input_resp,
                meta_complete_response(text="基于用户答复完成 step1"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat
        chat("原任务：分析文档")
        chat("y")

        # request_user_input 触发后，状态应是 awaiting_user_input + pending != None。
        assert state.task.status == "awaiting_user_input"
        assert state.task.pending_user_input_request is not None
        assert state.task.pending_user_input_request.get("awaiting_kind") in (
            "request_user_input",
            None,  # 旧 checkpoint 兼容；当前实现里 tool_executor 应写 request_user_input
        )

        before_user_goal = state.task.user_goal

        # 关键：此时输入 "2" 应被视作对 question 的答复，**不**触发 feedback_intent
        # 的"切新任务"分支。
        chat("2")

        assert "2" in _messages_text_blob(state), (
            "用户答复 '2' 应作为 step_input 写入 messages，供后续模型阅读。"
        )
        assert state.task.user_goal == before_user_goal, (
            f"awaiting_user_input + pending 路径下，'2' 不应被误判为 P1 "
            f"feedback_intent 的切新任务选择。实际 user_goal={state.task.user_goal!r}"
        )
        # 答复后 pending 应被清空（transitions.runtime_user_input_answer 行为）。
        assert state.task.pending_user_input_request is None, (
            "transitions 应在写入 step_input 后清空 pending_user_input_request。"
        )
    finally:
        cleanup()


# ============================================================
# 测试 10：连续选 [1] 反馈不应让 user_goal 膨胀
# ============================================================

def test_repeated_choose_as_feedback_does_not_accumulate_user_goal(monkeypatch):
    """保护边界：与 hardcore #6
    (`test_plan_feedback_does_not_accumulate_goal_string_indefinitely`)
    等价的延伸保护——即使经过 P1 新增的 awaiting_feedback_intent 中转，
    多轮"模糊文本 → [1] 当反馈"循环也不能让 `state.task.user_goal` 单向
    累加膨胀。

    修复方向：as_feedback 分支调 planner 时使用本地 `revised_goal`，
    不写回 `state.task.user_goal`（与现行 c252695 保留收益保持一致）。
    """

    state, fake, cleanup = _drive_to_awaiting_step_confirmation(monkeypatch)
    try:
        # 4 次反馈循环，每次都需要 1 条 planner 响应。
        for i in range(4):
            fake.responses.append(
                _plan_response([
                    (f"r{i}a", f"v{i}-s1", "read"),
                    (f"r{i}b", f"v{i}-s2", "report"),
                ])
            )

        from agent.core import chat

        initial_goal_len = len(state.task.user_goal or "")

        for i in range(4):
            chat(f"第 {i} 次反馈：再调一下方案")
            chat("1")
            # 选 [1] 后会重新进入 awaiting_plan_confirmation；下一轮再次 free-form
            # 时仍走 plan_confirmation feedback_intent 分流。
            assert state.task.status == "awaiting_plan_confirmation"

        final_goal_len = len(state.task.user_goal or "")
        assert final_goal_len < initial_goal_len * 3, (
            f"4 次 [1] 选择后 user_goal 长度膨胀到 {final_goal_len}（初始 "
            f"{initial_goal_len}）。这意味着 P1 的 as_feedback 分支错误地写回了"
            f"user_goal——必须改为只在本地组装 revised_goal 喂 planner。"
            f"当前 user_goal={state.task.user_goal!r}"
        )
    finally:
        cleanup()


# ============================================================
# 测试 11：checkpoint schema 顶层字段在 P1 后不变
# ============================================================

def test_p1_does_not_change_checkpoint_top_level_task_fields():
    """保护边界：P1 红线 #4 —— 不允许新增 task 顶层字段。
    `awaiting_feedback_intent` 分流必须复用现有
    `pending_user_input_request` 字段（通过 awaiting_kind 区分），不能新增
    `pending_feedback_intent` 之类的顶层字段。

    这条测试用反向断言：列出当前 TaskState 的全部字段名，作为基线。
    P1 实现后字段集合必须**完全**不变；若需要扩展，只允许：
    - `task.status` 枚举值集合（这是已有字段的取值范围扩展，不算 schema 变化）；
    - `pending_user_input_request` dict 内部 key（这是 dict value 内部，不是
      顶层字段）。
    """

    from agent.state import TaskState
    import dataclasses

    actual = {f.name for f in dataclasses.fields(TaskState)}
    # 当前基线（HEAD 54a39e3 / 205c4cf）。如未来要扩展必须先更新此基线断言并
    # 在 docs/P1_TOPIC_SWITCH_PLAN.md / docs/ARCHITECTURE.md 顶部说明原因。
    expected = {
        "user_goal",
        "current_plan",
        "current_step_index",
        "status",
        "retry_count",
        "loop_iterations",
        "consecutive_max_tokens",
        "consecutive_end_turn_without_progress",
        "tool_call_count",
        "last_error",
        "effective_review_request",
        "pending_tool",
        "pending_user_input_request",
        "confirm_each_step",
        "tool_execution_log",
    }
    assert actual == expected, (
        f"P1 红线 #4：不允许新增/删除 TaskState 顶层字段。"
        f"\n意外多出: {actual - expected}"
        f"\n意外缺失: {expected - actual}"
        f"\n如需变更必须先更新本测试基线 + 文档顶部通知。"
    )


# ============================================================
# 测试 12：context_builder._project_to_api 行为不被 P1 破坏
# ============================================================

def test_project_to_api_unchanged_for_feedback_intent_pending(monkeypatch):
    """保护边界：`_project_to_api` 是 conversation.messages → Anthropic API
    messages 的唯一投影边界。P1 通过 pending_user_input_request 表达
    awaiting_feedback_intent，而 pending 字段本来就不进 messages，所以
    `_project_to_api` 应当**完全感知不到** P1 的存在。

    这条测试断言：进入 awaiting_feedback_intent 后再调
    `build_planning_messages`（间接调用 _project_to_api），输出的 messages
    与未进入该状态前等长、内容一致——即 P1 没有偷偷往 messages 里塞东西。
    """

    state, fake, cleanup = _drive_to_awaiting_step_confirmation(monkeypatch)
    try:
        from agent.context_builder import build_planning_messages

        before_proj = build_planning_messages(state, "占位 user input")

        from agent.core import chat
        # 进入 P1 设计的 awaiting_feedback_intent 状态。
        chat("帮我写一首关于春天的诗")

        # 注意：上面这一轮如果走旧 feedback 路径，会 append plan_feedback 到
        # messages 并触发 planner 调用——本测试也会因此 fail，但 fail 信号已
        # 在 test_step_feedback_does_not_append_plan_feedback_event_to_messages_
        # before_user_choice 里更精确地暴露过。这里关心的是 P1 修复后的不变量：
        # awaiting_feedback_intent 不污染 _project_to_api 的输入输出。
        after_proj = build_planning_messages(state, "占位 user input")

        assert len(after_proj) == len(before_proj), (
            f"awaiting_feedback_intent 不应改变 _project_to_api 投影长度。"
            f"before={len(before_proj)}, after={len(after_proj)}。"
            f"若 after 比 before 多：说明 messages 被 P1 污染（违反 P1 边界）。"
        )
    finally:
        cleanup()

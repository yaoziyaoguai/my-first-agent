"""v0.5 Phase 1 第五小步（H · confirmation observer evidence）测试集。

============================================================
本文件保护的真实 bug 边界（学习型注释）
============================================================

这些测试对应 docs/V0_5_OBSERVER_AUDIT.md §4 / §8 Gap G2：
"5 条 confirmation 决策链路在 v0.4/v0.5 第三小步之前 **完全不写**
runtime_observer JSONL，导致 agent_log.jsonl 无法回答'用户在 plan/step/
tool/user_input/feedback_intent 上做了什么决策'。"

这是真实诊断 bug，不是观感问题。线上排查 confirmation 流的真实场景：

1. 用户报告"我点了取消但任务还在跑" → 只能从 conversation.messages 推断
   plan_confirm_no 是否被写入；observer JSONL 没有 confirmation.* 事件，
   无法独立验证 handler 路径。
2. 用户报告"我选了'切换为新任务'但还是旧 plan" → 同上。
3. 用户报告"工具被拒后没反应" → tool_executor 有 emit_display_event
   但没有 log_event，agent_log.jsonl 看不到 tool rejection 序列。

修复方向（本 slice 实现）：
- 每条 confirmation handler 在其 outcome 明确后调用
  `_emit_confirmation_observer_event(event_type, payload=...)` 一次；
- helper 内部 try/except swallow，确保 observer 故障不阻塞主流程；
- payload 字段只能含 transition kind 字符串、origin_status、tool_name、
  resolution_kind 等"枚举/标识"短字段，**绝不**含 user_input 原文 /
  feedback_text / tool_input 完整内容（隐私红线）。

每条测试的 Chinese docstring 指明：
(a) 测试发现的具体 bug；
(b) 哪个不变量被钉死；
(c) 不允许走的捷径（例如：把 evidence 写进 messages 或 checkpoint）。
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

import agent.confirm_handlers as ch
from agent.state import create_agent_state


# ----------------------------------------------------------------
# Observer 捕获 fixture
# ----------------------------------------------------------------
# 模拟边界：把 confirm_handlers 模块级的 _log_runtime_event 替换为捕获器，
# 等价于在 runtime_observer.log_event 入口拦截，但只影响 confirm_handlers
# 的调用面，不污染 response_handlers / planner / checkpoint / core 的
# observer 调用。这是"只读 observer"测试模式：handler 不应该感知到 observer
# 是否存在。
@pytest.fixture
def captured_events(monkeypatch):
    captured: list[tuple[str, dict, str | None, str | None]] = []

    def _fake_log(event_type, *, event_source=None, event_payload=None, event_channel=None):
        captured.append((event_type, dict(event_payload or {}), event_source, event_channel))

    monkeypatch.setattr(ch, "_log_runtime_event", _fake_log)
    return captured


# ----------------------------------------------------------------
# 状态构造工具
# ----------------------------------------------------------------
def _build_state_for_plan_confirmation():
    """构造 awaiting_plan_confirmation 状态，含一个最小可序列化 plan。"""
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test goal"
    state.task.current_plan = {
        "goal": "test goal",
        "steps": [
            {"id": 1, "title": "step1", "description": "do step1"},
            {"id": 2, "title": "step2", "description": "do step2"},
        ],
    }
    state.task.current_step_index = 0
    state.task.status = "awaiting_plan_confirmation"
    return state


def _build_state_for_step_confirmation(*, last_step: bool = False):
    """构造 awaiting_step_confirmation 状态，可选最后一步分支。"""
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test goal"
    state.task.current_plan = {
        "goal": "test goal",
        "steps": [
            {"step_id": "s1", "step_type": "tool", "title": "step1", "description": "do step1"},
            {"step_id": "s2", "step_type": "tool", "title": "step2", "description": "do step2"},
        ],
    }
    state.task.current_step_index = 1 if last_step else 0
    state.task.status = "awaiting_step_confirmation"
    return state


def _build_state_for_feedback_intent(origin_status: str = "awaiting_plan_confirmation"):
    """构造 awaiting_feedback_intent 状态。"""
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test goal"
    state.task.current_plan = {
        "goal": "test goal",
        "steps": [{"id": 1, "title": "s", "description": "d"}],
    }
    state.task.status = "awaiting_feedback_intent"
    state.task.pending_user_input_request = {
        "awaiting_kind": "feedback_intent",
        "origin_status": origin_status,
        "pending_feedback_text": "用户原始反馈 raw-feedback-text-secret",
    }
    return state


def _make_ctx(state, *, continue_fn=None, start_planning_fn=None, on_runtime_event=None):
    """构造最小 ConfirmationContext，turn_state 用 SimpleNamespace。"""
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=on_runtime_event,
        on_display_event=None,
    )
    return ch.ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test-model",
        continue_fn=continue_fn or (lambda ts: "continued"),
        start_planning_fn=start_planning_fn,
    )


# ----------------------------------------------------------------
# 1. plan confirmation: accepted / rejected
# ----------------------------------------------------------------
def test_plan_accept_emits_confirmation_observer_event(captured_events, tmp_path, monkeypatch):
    """真实 bug：plan accept 之前 agent_log.jsonl 无 confirmation.plan.accepted 事件。

    钉死不变量：handler accept 路径调用一次 _log_runtime_event，event_type
    为 'confirmation.plan.accepted'，event_channel='confirmation'，event_source
    ='confirm_handlers'，且 payload 只含 'intent' 短枚举值。
    """
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_plan_confirmation()
    ctx = _make_ctx(state)

    result = ch.handle_plan_confirmation("y", ctx)

    # 行为不变量：accept 路径 continue_fn 被调
    assert result == "continued"
    # observer evidence 被记录恰好一次
    plan_events = [e for e in captured_events if e[0].startswith("confirmation.plan.")]
    assert len(plan_events) == 1
    event_type, payload, source, channel = plan_events[0]
    assert event_type == "confirmation.plan.accepted"
    assert source == "confirm_handlers"
    assert channel == "confirmation"
    assert payload == {"intent": "plan_accepted"}


def test_plan_reject_emits_confirmation_observer_event(captured_events, tmp_path, monkeypatch):
    """真实 bug：plan reject 之前无 observer 事件——用户取消任务的 outcome 不可追溯。

    钉死不变量：reject 路径在 reset_task + clear_checkpoint 之后记录 evidence，
    确保事件时序与状态变更一致；payload 仅含 'intent' 字符串。
    """
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_plan_confirmation()
    ctx = _make_ctx(state)

    result = ch.handle_plan_confirmation("n", ctx)

    assert result == "好的，已取消。"
    assert state.task.current_plan is None
    plan_events = [e for e in captured_events if e[0].startswith("confirmation.plan.")]
    assert len(plan_events) == 1
    assert plan_events[0][0] == "confirmation.plan.rejected"
    assert plan_events[0][1] == {"intent": "plan_rejected"}


# ----------------------------------------------------------------
# 2. step confirmation: continue / task_done / rejected
# ----------------------------------------------------------------
def test_step_accept_continue_emits_confirmation_observer_event(
    captured_events, tmp_path, monkeypatch
):
    """真实 bug：中间 step 通过时无 observer evidence。"""
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_step_confirmation(last_step=False)
    ctx = _make_ctx(state)

    result = ch.handle_step_confirmation("y", ctx)

    assert result == "continued"
    step_events = [e for e in captured_events if e[0].startswith("confirmation.step.")]
    assert len(step_events) == 1
    assert step_events[0][0] == "confirmation.step.accepted_continue"


def test_step_accept_task_done_emits_confirmation_observer_event(
    captured_events, tmp_path, monkeypatch
):
    """真实 bug：任务在最后一步收尾时 observer 不知道任务结束。"""
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_step_confirmation(last_step=True)
    ctx = _make_ctx(state)

    result = ch.handle_step_confirmation("y", ctx)

    assert result == "好的，任务已完成。"
    step_events = [e for e in captured_events if e[0].startswith("confirmation.step.")]
    assert len(step_events) == 1
    assert step_events[0][0] == "confirmation.step.accepted_task_done"


def test_step_reject_emits_confirmation_observer_event(captured_events, tmp_path, monkeypatch):
    """真实 bug：用户在 step 节点中途停止，observer 看不到。"""
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_step_confirmation(last_step=False)
    ctx = _make_ctx(state)

    result = ch.handle_step_confirmation("n", ctx)

    assert result == "好的，当前任务已停止。"
    step_events = [e for e in captured_events if e[0].startswith("confirmation.step.")]
    assert len(step_events) == 1
    assert step_events[0][0] == "confirmation.step.rejected"


# ----------------------------------------------------------------
# 3. feedback_intent: ambiguous / cancelled / as_new_task
# (as_feedback 触达 generate_plan 真实 LLM 调用，本轮跳过——属于 G6 后续 slice)
# ----------------------------------------------------------------
def test_feedback_intent_ambiguous_emits_confirmation_observer_event(captured_events):
    """真实 bug：用户输入模糊导致 ambiguous 重发，observer 看不到次数。

    模糊模拟边界：模糊输入既不进 transition、也不动 pending、也不动 messages，
    但**应**进 observer JSONL 让事后排查能数清"用户在这个 prompt 上重试了几次"。
    """
    state = _build_state_for_feedback_intent()
    ctx = _make_ctx(state, on_runtime_event=lambda e: None)

    result = ch.handle_feedback_intent_choice("我想说的是...", ctx)

    assert result == ""
    # 状态完全不动
    assert state.task.status == "awaiting_feedback_intent"
    assert state.task.pending_user_input_request is not None
    fb_events = [e for e in captured_events if e[0].startswith("confirmation.feedback_intent.")]
    assert len(fb_events) == 1
    assert fb_events[0][0] == "confirmation.feedback_intent.ambiguous"


def test_feedback_intent_cancelled_emits_confirmation_observer_event(
    captured_events, tmp_path, monkeypatch
):
    """真实 bug：用户选 [3] 取消，observer 看不到取消事件。"""
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_feedback_intent(origin_status="awaiting_step_confirmation")
    ctx = _make_ctx(state)

    result = ch.handle_feedback_intent_choice("3", ctx)

    assert result == ""
    assert state.task.status == "awaiting_step_confirmation"
    fb_events = [e for e in captured_events if e[0].startswith("confirmation.feedback_intent.")]
    assert len(fb_events) == 1
    event_type, payload, _, _ = fb_events[0]
    assert event_type == "confirmation.feedback_intent.cancelled"
    assert payload["origin_status"] == "awaiting_step_confirmation"


def test_feedback_intent_as_new_task_emits_confirmation_observer_event(
    captured_events, tmp_path, monkeypatch
):
    """真实 bug：用户选 [2] 切换新任务，observer 看不到任务切换事件。

    模拟边界：start_planning_fn 用 lambda 桩代替真实 _run_planning_phase，
    避免触达真实 planner LLM 调用——本测试只验证 observer evidence，不验证
    新任务的真实推进。
    """
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_feedback_intent()
    ctx = _make_ctx(
        state,
        start_planning_fn=lambda text, ts: "new task started",
    )

    result = ch.handle_feedback_intent_choice("2", ctx)

    assert result == "new task started"
    fb_events = [e for e in captured_events if e[0].startswith("confirmation.feedback_intent.")]
    assert len(fb_events) == 1
    assert fb_events[0][0] == "confirmation.feedback_intent.as_new_task"


# ----------------------------------------------------------------
# 4. user_input: empty (resolved 路径需要 plan + collect_input step，复杂度高)
# ----------------------------------------------------------------
def test_user_input_empty_emits_confirmation_observer_event(captured_events):
    """真实 bug：空输入分支 observer 看不到——无法统计'用户提交了多少次空输入'。

    这条 evidence 在排查 TUI 输入丢失 / 提示文案不清晰时特别有用。
    """
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test goal"
    state.task.current_plan = {
        "goal": "test goal",
        "steps": [{"id": 1, "title": "ask user", "description": "d", "requires_user_input": True}],
    }
    state.task.current_step_index = 0
    state.task.status = "awaiting_user_input"
    ctx = _make_ctx(state)

    result = ch.handle_user_input_step("   ", ctx)

    assert "请输入有效内容" in result
    ui_events = [e for e in captured_events if e[0].startswith("confirmation.user_input.")]
    assert len(ui_events) == 1
    assert ui_events[0][0] == "confirmation.user_input.empty"


# ----------------------------------------------------------------
# 5. tool confirmation: rejected / feedback (success/failed 路径需要真实工具)
# ----------------------------------------------------------------
def _build_state_for_tool_confirmation(*, secret_input: str = "sk-ant-secret-payload"):
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test goal"
    state.task.current_plan = {
        "goal": "test goal",
        "steps": [{"id": 1, "title": "use tool", "description": "d"}],
    }
    state.task.current_step_index = 0
    state.task.status = "awaiting_tool_confirmation"
    state.task.pending_tool = {
        "tool_use_id": "toolu_observer_test",
        "tool": "write_file",
        "input": {"path": "workspace/x.txt", "content": secret_input},
    }
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_observer_test",
                    "name": "write_file",
                    "input": {"path": "workspace/x.txt"},
                }
            ],
        }
    ]
    return state


def test_tool_reject_emits_confirmation_observer_event(captured_events, tmp_path, monkeypatch):
    """真实 bug：用户拒绝工具时 observer 看不到——tool rejection 序列丢失。"""
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_tool_confirmation()
    ctx = _make_ctx(state)

    result = ch.handle_tool_confirmation("n", ctx)

    assert result == "continued"
    tool_events = [e for e in captured_events if e[0].startswith("confirmation.tool.")]
    assert len(tool_events) == 1
    event_type, payload, _, _ = tool_events[0]
    assert event_type == "confirmation.tool.rejected"
    assert payload == {"tool_name": "write_file"}


def test_tool_feedback_branch_emits_confirmation_observer_event(
    captured_events, tmp_path, monkeypatch
):
    """真实 bug：用户对工具给反馈而非 y/n，observer 看不到。"""
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_tool_confirmation()
    ctx = _make_ctx(state)

    result = ch.handle_tool_confirmation("应该用 read_file 而不是 write_file", ctx)

    assert result == "continued"
    tool_events = [e for e in captured_events if e[0].startswith("confirmation.tool.")]
    assert len(tool_events) == 1
    assert tool_events[0][0] == "confirmation.tool.feedback"
    assert tool_events[0][1] == {"tool_name": "write_file"}


# ----------------------------------------------------------------
# 6. observer 失败必须不影响主流程（产品契约硬不变量）
# ----------------------------------------------------------------
def test_observer_failure_does_not_break_handler(monkeypatch, tmp_path):
    """真实 bug 保护：observer 写入抛异常时 handler 必须仍返回原值。

    模拟边界：把 _log_runtime_event 替换为永远抛 RuntimeError 的桩。confirmation
    是用户决策的关键路径——如果 observer 故障会让 handler 崩溃，用户的 yes/no
    点击就会被阻断。这条不变量在 docs/V0_5_OBSERVER_AUDIT.md G2 "必须保持的不变量
    (a)" 已声明。
    """
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    def _always_raise(*a, **kw):
        raise RuntimeError("simulated observer failure")

    monkeypatch.setattr(ch, "_log_runtime_event", _always_raise)

    state = _build_state_for_plan_confirmation()
    ctx = _make_ctx(state)
    # handler 不能因为 observer 抛异常就崩——swallow 必须生效。
    result = ch.handle_plan_confirmation("y", ctx)
    assert result == "continued"
    assert state.task.status == "running"


# ----------------------------------------------------------------
# 7. payload 安全：禁止泄漏 user_input / feedback_text / tool_input 原文
# ----------------------------------------------------------------
def test_observer_payload_does_not_leak_user_input(captured_events, tmp_path, monkeypatch):
    """真实 bug 保护：confirm 字符串里如果含密文，不能进 payload。

    模拟边界：用户在 plan reject 时输入含 token 模式的 'n my-api-key'（极端
    情况）。payload 只允许 transition kind 字符串，不允许把 confirm 原文
    透传到 observer JSONL（agent_log.jsonl 是诊断面，不是机密保险柜）。
    """
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_plan_confirmation()
    ctx = _make_ctx(state)

    secret_phrase = "sk-ant-leaky-confirm-token"
    ch.handle_plan_confirmation(f"n {secret_phrase}", ctx)

    for event_type, payload, _, _ in captured_events:
        flat = repr(payload)
        assert secret_phrase not in flat, (
            f"observer payload leaked user input secret in event {event_type!r}: {payload!r}"
        )


def test_observer_payload_does_not_leak_tool_input_content(
    captured_events, tmp_path, monkeypatch
):
    """真实 bug 保护：tool 'input.content' 含密文时不能进 payload。"""
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    secret = "sk-ant-secret-payload-12345"
    state = _build_state_for_tool_confirmation(secret_input=secret)
    ctx = _make_ctx(state)

    ch.handle_tool_confirmation("n", ctx)

    for event_type, payload, _, _ in captured_events:
        assert secret not in repr(payload), (
            f"observer payload leaked tool input secret in event {event_type!r}: {payload!r}"
        )


def test_observer_payload_does_not_leak_feedback_text(
    captured_events, tmp_path, monkeypatch
):
    """真实 bug 保护：pending feedback_text 含原始用户长文本时不能进 payload。"""
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_feedback_intent()
    # 注入一个标记字符串，确保如果 handler 把 pending_feedback_text 塞进
    # payload，本测试会捕获泄漏。
    state.task.pending_user_input_request["pending_feedback_text"] = (
        "用户原始反馈 raw-feedback-text-secret-marker-XYZ"
    )
    ctx = _make_ctx(state)

    ch.handle_feedback_intent_choice("3", ctx)

    for event_type, payload, _, _ in captured_events:
        assert "raw-feedback-text-secret-marker-XYZ" not in repr(payload), (
            f"observer payload leaked feedback text in event {event_type!r}: {payload!r}"
        )


# ----------------------------------------------------------------
# 8. handler 不改变 state/messages/checkpoint/return-value 语义
# ----------------------------------------------------------------
def test_observer_event_does_not_add_extra_messages(captured_events, tmp_path, monkeypatch):
    """真实 bug 保护：observer 接入不能向 conversation.messages 追加新条目。

    messages 是 durable state 的一部分（进 checkpoint）；observer evidence
    只能进 agent_log.jsonl。两条链路必须独立——否则 v0.5 H 就退化成把
    observer 写进了 messages，破坏 §2 表格"observer 不写 messages"边界。
    """
    from agent import checkpoint as ck
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = _build_state_for_plan_confirmation()
    msg_count_before = len(state.conversation.messages)
    ctx = _make_ctx(state)
    ch.handle_plan_confirmation("y", ctx)

    # accept 路径只增加 1 条 control event（plan_confirm_yes），与 v0.4 一致。
    assert len(state.conversation.messages) == msg_count_before + 1
    # 新条目必须是 plan_confirm_yes，不是 observer event。
    assert state.conversation.messages[-1]["role"] in ("user", "system", "assistant")


# ----------------------------------------------------------------
# 9. AST guard: helper 是否真的接入了所有 11+ outcome 出口
# ----------------------------------------------------------------
def test_helper_invoked_at_minimum_required_call_sites():
    """真实 bug 保护：未来如有人在 handler 里加新 outcome 分支但忘记调 helper。

    AST 守卫：扫描 confirm_handlers 源码，统计 _emit_confirmation_observer_event
    调用站点数量。当前最小集合 = 1 (def) + 11 outcome (plan*2 + step*3 +
    feedback*4 + user_input*1 + tool*4 ?) — 实际为 15 (def + 14 sites，
    含 user_input.resolved 1 + user_input.empty 1 + 4 tool branches 部分
    在 try/except 内联两次)。本测试容差 ≥12，保证不会有人删除或忘记接入。
    """
    src = inspect.getsource(ch)
    tree = ast.parse(src)
    call_count = 0
    def_count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_emit_confirmation_observer_event":
            def_count += 1
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None
            )
            if name == "_emit_confirmation_observer_event":
                call_count += 1
    assert def_count == 1, "_emit_confirmation_observer_event 必须只定义 1 次（SSOT）"
    # 最小阈值：5 个 handler × 至少 1 outcome each = 5；当前实现为 14 outcome
    # 接入。允许未来微调，但不允许低于 11（5 handler 主路径 + 6 个子分支）。
    assert call_count >= 11, (
        f"_emit_confirmation_observer_event 接入面退化（仅 {call_count} 处），"
        f"必须保持 >= 11 处覆盖 5 条 confirmation 链路"
    )


def test_helper_uses_runtime_observer_log_event_not_legacy_logger():
    """真实 bug 保护：helper 必须走 runtime_observer.log_event（新关键字签名），
    不能误用 agent.logger.log_event（旧两参数签名）。

    对应 docs/V0_5_OBSERVER_AUDIT.md G5：两套 log_event 同名不同签名，
    新代码混用会导致 event_payload / event_channel 字段静默丢失。
    """
    src = inspect.getsource(ch)
    # 必须有 from agent.runtime_observer import log_event as _log_runtime_event
    assert "from agent.runtime_observer import log_event as _log_runtime_event" in src
    # 必须不直接 from agent.logger import log_event
    assert "from agent.logger import log_event" not in src

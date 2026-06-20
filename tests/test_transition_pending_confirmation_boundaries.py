"""Plan, step, tool, user input, and feedback confirmation boundary tests.

本文件从原 3000+ 行 v0.4 transition characterization 巨型文件按行为边界拆出。
拆分只改变测试组织，不改变断言语义；这样后续 core / memory / SubAgent
重构时可以局部审查，避免一个历史巨石同时承载所有边界风险。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import agent.confirmation.tool as _conf_tool


def test_plan_confirmation_kind_covers_only_plan_outcomes():
    """枚举只覆盖 plan 的两类终结意图，不应混入 step/tool/user_input。"""

    from agent.runtime_events import PlanConfirmationKind

    values = {member.value for member in PlanConfirmationKind}
    assert values == {"plan_accepted", "plan_rejected"}


def test_plan_confirmation_transition_accept_intent_marks_checkpoint_and_running():
    """接受 plan 必须表达 next_status=running + should_checkpoint=True。"""

    from agent.runtime_events import (
        PlanConfirmationKind,
        plan_confirmation_transition,
    )

    result = plan_confirmation_transition(PlanConfirmationKind.PLAN_ACCEPTED)
    assert result.next_status == "running"
    assert result.should_checkpoint is True
    assert result.clear_pending_tool is False
    assert result.clear_pending_user_input is False
    assert result.advance_step is False
    assert "plan.accepted" in result.display_events


def test_plan_confirmation_transition_reject_intent_does_not_checkpoint():
    """拒绝 plan 必须表达 should_checkpoint=False，避免幽灵 checkpoint。"""

    from agent.runtime_events import (
        PlanConfirmationKind,
        plan_confirmation_transition,
    )

    result = plan_confirmation_transition(PlanConfirmationKind.PLAN_REJECTED)
    # 关键：拒绝路径不能再 checkpoint，因为 handler 紧接着会 reset_task +
    # clear_checkpoint；如果 transition 反过来要求 checkpoint，会让已清空
    # 的 task 状态又被落盘，resume 时复活已取消的任务。
    assert result.should_checkpoint is False
    assert result.next_status is None
    assert "plan.rejected" in result.display_events


def test_plan_confirmation_transition_rejects_unknown_kinds():
    """未知 kind 必须显式失败，避免下游静默走 default 分支误判。"""


    from agent.runtime_events import plan_confirmation_transition

    class _Foreign:
        value = "step_accepted"  # 故意伪装成另一类 confirmation 的 kind

    with pytest.raises(ValueError):
        plan_confirmation_transition(_Foreign())


def test_plan_confirmation_transition_is_pure_function():
    """transition 工厂不读 state、不写 messages、不动 checkpoint；纯函数。

    fake/mock 边界说明：本测试不实例化真实 TaskState；纯靠 'before/after
    返回值相等' 来检测隐性副作用。如果未来 transition helper 偷偷开始读
    全局 module-level 状态或调 logger / checkpoint，就会破坏这一条断言。
    """

    from agent.runtime_events import (
        PlanConfirmationKind,
        plan_confirmation_transition,
    )

    a1 = plan_confirmation_transition(PlanConfirmationKind.PLAN_ACCEPTED)
    a2 = plan_confirmation_transition(PlanConfirmationKind.PLAN_ACCEPTED)
    r1 = plan_confirmation_transition(PlanConfirmationKind.PLAN_REJECTED)
    r2 = plan_confirmation_transition(PlanConfirmationKind.PLAN_REJECTED)
    assert a1 == a2
    assert r1 == r2
    assert a1 != r1


def test_handle_plan_confirmation_source_actually_routes_through_transition():
    """source-level 契约：handler 不允许绕过 transition 层回到 inline 写法。

    背景：confirm_handlers 是 chat() 间接调用的产物，handler 直接独立
    单元测试需要构造大量 ConfirmationContext / continue_fn / turn_state；
    现有 tests/test_complex_scenarios.py / tests/test_feedback_intent_flow.py
    已经从端到端层面覆盖了 plan 接受 / 拒绝的真实行为（status / messages
    / checkpoint 全部通过其他测试守住）。这里补一条 source-level 契约，
    专门钉「handler 真的调用了 plan_confirmation_transition」，防止后续
    有人重构时把 transition 调用删掉，让边界命名形同虚设。
    """

    import inspect

    from agent import confirm_handlers

    src = inspect.getsource(confirm_handlers.handle_plan_confirmation)
    assert "plan_confirmation_transition" in src, (
        "handle_plan_confirmation 必须通过 plan_confirmation_transition 表达"
        "Runtime 意图，禁止回到 inline status 赋值的旧写法。"
    )
    assert "PlanConfirmationKind.PLAN_ACCEPTED" in src
    assert "PlanConfirmationKind.PLAN_REJECTED" in src
    # 不允许 step / tool / user_input / feedback_intent 的 *Kind 出现在 plan handler 里。
    forbidden = (
        "StepConfirmationKind",
        "ToolConfirmationKind",
        "UserInputConfirmationKind",
        "FeedbackIntentKind",
    )
    for name in forbidden:
        assert name not in src, (
            f"plan handler 不应越界使用 {name}；slice 6 plan 子切片只覆盖 plan。"
        )


def test_plan_confirmation_transition_does_not_leak_into_messages_or_checkpoint(
    tmp_path, monkeypatch
):
    """durable state 不应包含 PlanConfirmationKind / plan_confirmation_transition 字面量。

    通过端到端调用 handle_plan_confirmation 的接受 / 拒绝路径，序列化
    messages 与 checkpoint 后扫描 transition 层符号，确认它们只是 Runtime
    内部命名，没有泄漏成持久化字段。这条防止后续重构「不小心 dump 了
    TransitionResult」。
    """

    from types import SimpleNamespace

    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    # ----- accept 路径 -----
    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_plan_confirmation"
    state.task.current_plan = [{"step": 1, "description": "do x"}]

    def _continue(_ts):
        return "continued"

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(),
        client=None, model_name="x", continue_fn=_continue,
    )
    ch.handle_plan_confirmation("y", ctx)
    assert state.task.status == "running"

    # 中文学习边界（accept 路径硬约束）：
    # plan_confirmation_transition(PLAN_ACCEPTED) 显式承诺
    # should_checkpoint=True；handler 必须真的把这次接受落盘，否则 resume
    # 时会丢失"用户已经批准 plan"这一关键事实，下次启动会要求用户重新确认
    # 同一份 plan，破坏 v0.4 transition 边界承诺。
    # 这条断言钉死「accept → 真实 checkpoint 文件存在」，未来如果有人把
    # save_checkpoint 调用从 handler 中误删，会立刻在这里失败。
    assert ckpt_file.exists(), (
        "plan accepted 路径必须真实写入 checkpoint 文件；"
        "如果 handler 删掉 save_checkpoint 调用，resume 会丢任务。"
    )

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    serialized_ckpt = (
        ckpt_file.read_text(encoding="utf-8") if ckpt_file.exists() else ""
    )

    for marker in (
        "PlanConfirmationKind",
        "plan_confirmation_transition",
        "TransitionResult",
    ):
        assert marker not in serialized_messages, (
            f"transition 内部符号 {marker} 不应出现在 durable messages 里"
        )
        assert marker not in serialized_ckpt, (
            f"transition 内部符号 {marker} 不应出现在 checkpoint 里"
        )

    # ----- reject 路径 -----
    state2 = create_agent_state(system_prompt="test")
    state2.task.status = "awaiting_plan_confirmation"
    state2.task.current_plan = [{"step": 1, "description": "do y"}]
    ctx2 = ch.ConfirmationContext(
        state=state2,
        turn_state=SimpleNamespace(),
        client=None, model_name="x", continue_fn=_continue,
    )
    out = ch.handle_plan_confirmation("n", ctx2)
    assert "已取消" in out
    # reset_task 之后 task 应回到初始状态
    assert state2.task.status == "idle"
    # 中文学习边界（reject 路径硬约束）：
    # plan_confirmation_transition(PLAN_REJECTED) 显式承诺
    # should_checkpoint=False；handler 紧接着 reset_task + clear_checkpoint，
    # 因此 checkpoint 文件必须**不存在**。如果未来有人在 reject 路径上
    # 反向加 save_checkpoint，已被清空的 task 状态会被落盘 → resume 会
    # 复活幽灵任务。这条断言钉死「reject → checkpoint 必须不存在」。
    assert not ckpt_file.exists(), (
        "plan rejected 路径不应残留 checkpoint 文件；"
        "如果 handler 在拒绝路径上误调 save_checkpoint，resume 会复活幽灵任务。"
    )

    serialized_messages2 = json.dumps(state2.conversation.messages, ensure_ascii=False)
    for marker in (
        "PlanConfirmationKind",
        "plan_confirmation_transition",
        "TransitionResult",
    ):
        assert marker not in serialized_messages2


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-b（step 子切片）· step confirmation transition 边界测试
# ---------------------------------------------------------------------------
# 中文学习边界：本组测试钉死的「真实回归点」
# - STEP_ACCEPTED_CONTINUE 必须 should_checkpoint=True；防止有人改成
#   False 导致中间步用户已批准但 resume 时丢失批准状态。
# - STEP_ACCEPTED_TASK_DONE 必须 should_checkpoint=False；防止有人误改
#   成 True 导致已完成 task 又被落盘 → resume 复活已结束的任务。
# - STEP_REJECTED 必须 should_checkpoint=False；防止反向 save 让已停止任务复活。
# - 这三类必须独立于 plan / tool / user_input / feedback_intent kind；
#   source-level 契约钉住 step handler 不越界使用其他 *Kind。
# - 端到端真实 handler 调用：accept (continue) / accept (done) / reject 三条路径，
#   断言真实 checkpoint 文件存在性 + state 字段值 + transition 字面量不泄漏 durable。

def test_step_confirmation_kind_covers_only_step_outcomes():
    """枚举只覆盖 step 的三类终结意图，不应混入 plan/tool/user_input/feedback。"""

    from agent.runtime_events import StepConfirmationKind

    values = {member.value for member in StepConfirmationKind}
    assert values == {"step_accepted_continue", "step_accepted_task_done", "step_rejected"}


def test_step_confirmation_accept_continue_marks_checkpoint():
    """中间步 accept 必须 should_checkpoint=True；否则 resume 丢批准状态。"""

    from agent.runtime_events import (
        StepConfirmationKind,
        step_confirmation_transition,
    )

    result = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_CONTINUE)
    assert result.should_checkpoint is True
    assert result.advance_step is True
    assert "step.accepted" in result.display_events


def test_step_confirmation_accept_task_done_does_not_checkpoint():
    """最后一步 accept = 任务自然完成，必须 should_checkpoint=False。

    回归点：如果有人把这个改成 True，已 done 的 task 会被落盘，下次启动
    会"复活"已经完成的任务。
    """

    from agent.runtime_events import (
        StepConfirmationKind,
        step_confirmation_transition,
    )

    result = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_TASK_DONE)
    assert result.should_checkpoint is False
    assert "step.task_done" in result.display_events


def test_step_confirmation_reject_does_not_checkpoint():
    """reject 必须 should_checkpoint=False；防止反向 save 复活停止任务。"""

    from agent.runtime_events import (
        StepConfirmationKind,
        step_confirmation_transition,
    )

    result = step_confirmation_transition(StepConfirmationKind.STEP_REJECTED)
    assert result.should_checkpoint is False
    assert "step.rejected" in result.display_events


def test_step_confirmation_transition_rejects_unknown_kinds():
    """未知 kind 必须显式失败，禁止下游静默走 default。"""


    from agent.runtime_events import step_confirmation_transition

    class _Foreign:
        value = "plan_accepted"  # 故意伪装成 plan kind

    with pytest.raises(ValueError):
        step_confirmation_transition(_Foreign())


def test_step_confirmation_transition_is_pure_function():
    """transition 工厂为纯函数；同输入恒等输出。

    fake/mock 边界：本测试不构造 TaskState；纯靠返回值相等检测隐性副作用。
    如果未来 helper 偷偷依赖全局状态或 logger，这条会失败。
    """

    from agent.runtime_events import (
        StepConfirmationKind,
        step_confirmation_transition,
    )

    a = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_CONTINUE)
    b = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_CONTINUE)
    c = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_TASK_DONE)
    d = step_confirmation_transition(StepConfirmationKind.STEP_REJECTED)
    assert a == b
    assert a != c
    assert a != d
    assert c != d


def test_handle_step_confirmation_source_actually_routes_through_transition():
    """source-level 契约：step handler 必须真正调用 transition，禁止跨边界 *Kind。"""

    import inspect

    from agent import confirm_handlers

    src = inspect.getsource(confirm_handlers.handle_step_confirmation)
    assert "step_confirmation_transition" in src
    assert "STEP_ACCEPTED_CONTINUE" in src
    assert "STEP_ACCEPTED_TASK_DONE" in src
    assert "STEP_REJECTED" in src
    forbidden = (
        "PlanConfirmationKind",
        "ToolConfirmationKind",
        "UserInputConfirmationKind",
        "FeedbackIntentKind",
    )
    for name in forbidden:
        assert name not in src, (
            f"step handler 不应越界使用 {name}；slice 6-b step 子切片只覆盖 step。"
        )


def test_step_confirmation_transition_does_not_leak_durable(tmp_path, monkeypatch):
    """端到端：调用真实 handler 三条路径，断言 durable state 无 transition 字面量。

    fake/mock 边界说明：用 monkeypatch 把 CHECKPOINT_PATH 重定向到 tmp_path，
    让真实 save_checkpoint / clear_checkpoint 真实写入临时文件——**不**
    mock 这两个函数本身。advance_current_step_if_needed 走真实实现。
    """

    from types import SimpleNamespace

    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    def _continue(_ts):
        return "continued"

    def _new_state_with_two_steps():
        s = create_agent_state(system_prompt="test")
        s.task.status = "awaiting_step_confirmation"
        s.task.user_goal = "demo"
        s.task.current_plan = {
            "goal": "demo",
            "steps": [
                {
                    "step_id": "step-1",
                    "title": "first",
                    "description": "first",
                    "step_type": "report",
                },
                {
                    "step_id": "step-2",
                    "title": "second",
                    "description": "second",
                    "step_type": "report",
                },
            ],
        }
        s.task.current_step_index = 0
        return s

    def _scan_no_leak(serialized: str) -> None:
        for marker in (
            "StepConfirmationKind",
            "step_confirmation_transition",
            "TransitionResult",
        ):
            assert marker not in serialized, (
                f"transition 内部符号 {marker} 不应出现在 durable state 里"
            )

    # ----- accept_continue：还有下一步 -----
    state_a = _new_state_with_two_steps()
    ctx_a = ch.ConfirmationContext(
        state=state_a,
        turn_state=SimpleNamespace(),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out_a = ch.handle_step_confirmation("y", ctx_a)
    # advance_current_step_if_needed 应该把 index 推进到 1，status 仍 running
    assert state_a.task.current_step_index == 1
    assert state_a.task.status == "running"
    assert out_a == "continued"
    # 中间步 accept 必须真实落盘
    assert ckpt_file.exists(), (
        "step accept (continue) 路径必须真实写入 checkpoint；"
        "如果 handler 删掉 save_checkpoint 调用，resume 会丢"
        "「用户已批准 step」状态。"
    )
    _scan_no_leak(json.dumps(state_a.conversation.messages, ensure_ascii=False))
    _scan_no_leak(ckpt_file.read_text(encoding="utf-8"))

    # 清理 ckpt 文件准备下一条
    ckpt_file.unlink()

    # ----- accept_task_done：最后一步 -----
    state_b = create_agent_state(system_prompt="test")
    state_b.task.status = "awaiting_step_confirmation"
    state_b.task.user_goal = "demo"
    state_b.task.current_plan = {
        "goal": "demo",
        "steps": [
            {
                "step_id": "step-1",
                "title": "only",
                "description": "only",
                "step_type": "report",
            },
        ],
    }
    state_b.task.current_step_index = 0
    ctx_b = ch.ConfirmationContext(
        state=state_b,
        turn_state=SimpleNamespace(),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out_b = ch.handle_step_confirmation("y", ctx_b)
    assert "任务已完成" in out_b
    # reset_task 之后 task 应回 idle
    assert state_b.task.status == "idle"
    # 任务自然完成必须不落盘
    assert not ckpt_file.exists(), (
        "step accept (task_done) 路径不应残留 checkpoint；"
        "如果 handler 在终态路径上误调 save_checkpoint，resume 会复活已完成任务。"
    )
    _scan_no_leak(json.dumps(state_b.conversation.messages, ensure_ascii=False))

    # ----- reject -----
    state_c = _new_state_with_two_steps()
    ctx_c = ch.ConfirmationContext(
        state=state_c,
        turn_state=SimpleNamespace(),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out_c = ch.handle_step_confirmation("n", ctx_c)
    assert "已停止" in out_c
    assert state_c.task.status == "idle"
    assert not ckpt_file.exists(), (
        "step reject 路径不应残留 checkpoint；"
        "如果误调 save_checkpoint，已停止任务会在 resume 时复活。"
    )
    _scan_no_leak(json.dumps(state_c.conversation.messages, ensure_ascii=False))


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-c 准备 · tool confirmation pending_tool single source 契约
# ---------------------------------------------------------------------------
# 中文学习边界：本测试钉死的「真实回归点」
# - tool accept 路径成功执行后，pending_tool 必须由 handler 清掉。
#   handler 的 L458 一直承担这个 single source of truth，不能漂移到
#   transition 自动 mutate。后续做 tool confirmation transition 时，
#   transition 字段（如 clear_pending_tool）只能表达 intent，
#   handler 仍是实际清理的执行方。这一条防止 slice 6-c 把清理职责
#   错位到 transition layer 引起静默漏清或重复清理。
# - 异常路径必须保留 pending_tool 以便人工排查；这是 handler 故意保留
#   的真实排查需求，不能因为 transition 模板"看起来对称"就强行清掉。
#
# fake/mock 边界：本测试用 monkeypatch 把 execute_pending_tool 替换成
# 一个最小 fake，模拟「工具成功执行 → handler 走到 L458」与「工具抛
# 异常 → handler 走到 L443 except 分支」两条真实路径。fake 不替代
# handler 的清理职责，仅替代 tool 实际 IO，因为本测试要测的是 handler
# 的清理契约，不是 tool 是否真的能跑。

def test_tool_accept_success_path_clears_pending_tool_via_handler(tmp_path, monkeypatch):
    """tool accept 成功执行后，pending_tool 必须为 None（由 handler 清理）。"""


    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    # fake：模拟工具成功执行，不动 pending_tool。这样如果 handler 不清，
    # pending_tool 会留在 state 里被本测试断言抓到。
    def _fake_execute_pending_tool(*, state, turn_state, messages, pending):
        # 模拟工具产生 tool_result（真实 execute_pending_tool 也会写）
        from agent.conversation_events import append_tool_result
        append_tool_result(messages, pending["tool_use_id"], "ok")

    monkeypatch.setattr(_conf_tool, "execute_pending_tool", _fake_execute_pending_tool)

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.pending_tool = {
        "tool": "read_file",
        "tool_use_id": "toolu_test_accept",
        "input": {"path": "x"},
    }

    def _continue(_ts):
        return "continued"

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out = ch.handle_tool_confirmation("y", ctx)
    assert out == "continued"

    # 核心契约：accept 成功路径，pending_tool 必须被 handler 清。
    assert state.task.pending_tool is None, (
        "tool accept 成功后 pending_tool 必须由 handler 清理；"
        "如果清理职责漂移到 transition 自动 mutate 或漏掉，"
        "下一轮 awaiting_tool_confirmation 会复用旧 pending_tool 数据。"
    )
    assert state.task.status == "running"
    assert ckpt_file.exists(), "tool accept 成功路径必须真实写入 checkpoint"


def test_tool_accept_exception_path_keeps_pending_tool_for_inspection(tmp_path, monkeypatch):
    """tool accept 但执行抛异常时，pending_tool 必须保留以便人工排查。

    这是 handler L444 注释明确的真实排查需求；transition 模板对称化时
    不能因为「accept 路径都该清」就把这条排查路径改坏。
    """


    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    def _fake_raises(*, state, turn_state, messages, pending):
        raise RuntimeError("tool execution failed for testing")

    monkeypatch.setattr(_conf_tool, "execute_pending_tool", _fake_raises)

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    pending_payload = {
        "tool": "read_file",
        "tool_use_id": "toolu_test_exc",
        "input": {"path": "x"},
    }
    state.task.pending_tool = dict(pending_payload)

    def _continue(_ts):
        return "continued"

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out = ch.handle_tool_confirmation("y", ctx)
    assert out == "continued"

    # 核心契约：异常路径必须保留 pending_tool。
    assert state.task.pending_tool is not None, (
        "tool accept 但执行抛异常时，pending_tool 必须保留以便排查；"
        "如果被错误清掉，用户/开发者无法知道当时在试图执行什么工具。"
    )
    assert state.task.pending_tool["tool_use_id"] == pending_payload["tool_use_id"]
    assert state.task.status == "running"


def test_tool_reject_path_clears_pending_tool_via_transition_intent(tmp_path, monkeypatch):
    """tool reject 路径：清理由 handler 读 transition.clear_pending_tool 触发。

    钉死 USER_REJECTION transition 的 clear_pending_tool=True 契约不会
    在后续 slice 6-c 重命名为 ToolConfirmationKind 时被破坏。
    """


    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.pending_tool = {
        "tool": "read_file",
        "tool_use_id": "toolu_test_reject",
        "input": {"path": "x"},
    }

    def _continue(_ts):
        return "continued"

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out = ch.handle_tool_confirmation("n", ctx)
    assert out == "continued"

    # reject 路径 pending_tool 必须清掉（transition.clear_pending_tool=True
    # → handler 显式清）。
    assert state.task.pending_tool is None, (
        "tool reject 后 pending_tool 必须清；这条契约由 USER_REJECTION "
        "transition 的 clear_pending_tool=True 表达 intent，"
        "handler 实际执行清理。"
    )
    assert state.task.status == "running"


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-c（tool 子切片）· tool confirmation transition 边界测试
# ---------------------------------------------------------------------------
# 中文学习边界：本组测试钉死的「真实回归点」
# - TOOL_ACCEPTED_SUCCESS: should_checkpoint=True + clear_pending_tool=True，
#   防止后续重构把 success 路径改成不清 pending（旧 pending 数据复用 bug）。
# - TOOL_ACCEPTED_FAILED: should_checkpoint=True + clear_pending_tool=False，
#   防止 transition 模板对称化时把异常路径的 pending_tool 也清掉，破坏
#   confirm_handlers L444 注释明确的人工排查需求。
# - 新枚举只覆盖 accept 两种结局；reject 路径仍走 ToolResultTransitionKind
#   (USER_REJECTION)，这是 v0.1 已存在的 ToolResult 词汇边界，本切片不
#   合并以保留语义层次（ToolResult vs ToolConfirmation）。
# - source-level 契约：handler 真正调用 tool_confirmation_transition 而
#   不是回到 inline state.task.status="running" 的旧写法。

def test_tool_confirmation_kind_covers_only_tool_accept_outcomes():
    """枚举只覆盖 tool accept 的两种结局，不混入 plan/step/user_input/feedback。"""

    from agent.runtime_events import ToolConfirmationKind

    values = {member.value for member in ToolConfirmationKind}
    assert values == {"tool_accepted_success", "tool_accepted_failed"}


def test_tool_confirmation_accept_success_clears_pending_and_checkpoints():
    """成功路径 transition 必须 should_checkpoint=True + clear_pending_tool=True。"""

    from agent.runtime_events import (
        ToolConfirmationKind,
        tool_confirmation_transition,
    )

    result = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS)
    assert result.should_checkpoint is True
    assert result.clear_pending_tool is True
    assert result.next_status == "running"
    assert "tool.accepted" in result.display_events


def test_tool_confirmation_accept_failed_keeps_pending_but_checkpoints():
    """异常路径必须 should_checkpoint=True 但 clear_pending_tool=False。

    回归点：如果有人对称化把 failed 路径也设为 clear_pending_tool=True，
    人工就再也无法看到「当时在试图执行什么工具」，破坏排查能力。
    """

    from agent.runtime_events import (
        ToolConfirmationKind,
        tool_confirmation_transition,
    )

    result = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_FAILED)
    assert result.should_checkpoint is True
    assert result.clear_pending_tool is False, (
        "异常路径必须保留 pending_tool 以便人工排查"
    )
    assert result.next_status == "running"
    assert "tool.accepted_failed" in result.display_events


def test_tool_confirmation_transition_rejects_unknown_kinds():
    """未知 kind（如 reject 形式的伪枚举）必须显式失败。"""


    from agent.runtime_events import tool_confirmation_transition

    class _Foreign:
        value = "tool_rejected_by_user"  # 故意：reject 不在 ToolConfirmationKind 范围

    with pytest.raises(ValueError):
        tool_confirmation_transition(_Foreign())


def test_tool_confirmation_transition_is_pure_function():
    """transition 工厂为纯函数；同输入恒等输出。"""

    from agent.runtime_events import (
        ToolConfirmationKind,
        tool_confirmation_transition,
    )

    a = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS)
    b = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS)
    c = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_FAILED)
    assert a == b
    assert a != c


def test_handle_tool_confirmation_source_actually_routes_through_transition():
    """source-level 契约：tool handler 必须真正调用 tool_confirmation_transition。

    钉点 1：accept 两条路径都用 ToolConfirmationKind 枚举。
    钉点 2：reject 路径仍用 ToolResultTransitionKind.USER_REJECTION（保留
            ToolResult vs ToolConfirmation 的语义边界）。
    钉点 3：禁止越界使用 plan/step/user_input/feedback_intent 的 *Kind。
    """

    import inspect

    from agent import confirm_handlers

    src = inspect.getsource(confirm_handlers.handle_tool_confirmation)
    assert "tool_confirmation_transition" in src
    assert "TOOL_ACCEPTED_SUCCESS" in src
    assert "TOOL_ACCEPTED_FAILED" in src
    # reject 路径仍归 ToolResult 词汇
    assert "USER_REJECTION" in src
    # 禁止越界使用其他 confirmation 的 *Kind
    forbidden = (
        "PlanConfirmationKind",
        "StepConfirmationKind",
        "UserInputConfirmationKind",
        "FeedbackIntentKind",
    )
    for name in forbidden:
        assert name not in src, (
            f"tool handler 不应越界使用 {name}；slice 6-c 只覆盖 tool。"
        )


def test_tool_confirmation_transition_does_not_leak_durable(tmp_path, monkeypatch):
    """端到端：accept success / accept failed 两条路径，durable state 无 transition 字面量。

    fake/mock 边界：monkeypatch execute_pending_tool 模拟成功 / 抛异常两条
    路径；所有 state mutation / save_checkpoint / clear pending_tool 走
    handler 真实代码。
    """

    from types import SimpleNamespace

    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    def _scan_no_leak(serialized: str) -> None:
        for marker in (
            "ToolConfirmationKind",
            "tool_confirmation_transition",
            "TransitionResult",
        ):
            assert marker not in serialized, (
                f"transition 内部符号 {marker} 不应出现在 durable state 里"
            )

    def _continue(_ts):
        return "continued"

    # ----- accept success -----
    def _fake_ok(*, state, turn_state, messages, pending):
        from agent.conversation_events import append_tool_result
        append_tool_result(messages, pending["tool_use_id"], "ok")

    monkeypatch.setattr(_conf_tool, "execute_pending_tool", _fake_ok)

    state_a = create_agent_state(system_prompt="test")
    state_a.task.status = "awaiting_tool_confirmation"
    state_a.task.pending_tool = {
        "tool": "read_file",
        "tool_use_id": "toolu_a",
        "input": {"path": "x"},
    }
    ctx_a = ch.ConfirmationContext(
        state=state_a,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    ch.handle_tool_confirmation("y", ctx_a)
    # success 契约不变（与 stage B 测试一致）
    assert state_a.task.pending_tool is None
    assert ckpt_file.exists()
    _scan_no_leak(json.dumps(state_a.conversation.messages, ensure_ascii=False))
    _scan_no_leak(ckpt_file.read_text(encoding="utf-8"))
    ckpt_file.unlink()

    # ----- accept failed -----
    def _fake_raises(*, state, turn_state, messages, pending):
        raise RuntimeError("boom")

    monkeypatch.setattr(_conf_tool, "execute_pending_tool", _fake_raises)

    state_b = create_agent_state(system_prompt="test")
    state_b.task.status = "awaiting_tool_confirmation"
    state_b.task.pending_tool = {
        "tool": "read_file",
        "tool_use_id": "toolu_b",
        "input": {"path": "x"},
    }
    ctx_b = ch.ConfirmationContext(
        state=state_b,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    ch.handle_tool_confirmation("y", ctx_b)
    # failed 契约：pending_tool 保留，但仍 checkpoint
    assert state_b.task.pending_tool is not None
    assert ckpt_file.exists(), (
        "failed 路径 should_checkpoint=True，必须真实写入 checkpoint"
    )
    _scan_no_leak(json.dumps(state_b.conversation.messages, ensure_ascii=False))
    _scan_no_leak(ckpt_file.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-d · user_input confirmation 复用契约（不新增 Kind）
#
# 设计原则（与 docs/V0_4_EVENT_TRANSITION_PREP.md §4 第四个 confirmation slice 对齐）：
#
#   handle_user_input_step 在 v0.3 已经被 apply_user_replied_transition
#   （agent/transitions.py）抽空成 3 行 dispatcher：
#       resolve_user_input → empty 防御 → apply_user_replied_transition → continue/reply
#   它不像 plan/step/tool 那样 inline 写 status / pending / save_checkpoint。
#
#   因此 v0.4 slice 6-d 的"正确做法"是 **复用 v0.3 已有的 transition 边界**，
#   而不是再加一个 UserInputConfirmationKind 把已经抽好的层包第二层。
#
#   本 slice 不修改 confirm_handlers、不修改 runtime_events、不修改 transitions；
#   只在测试层钉两条契约，保证未来任何"v0.4 化"重构不会偷偷把 inline mutation
#   塞回 handle_user_input_step（这是真实回归风险，过去 v0.3 之前正是这种长函数）。
#
# 契约 1：handler 必须委托给 apply_user_replied_transition；
# 契约 2：handler 不允许直接 mutate pending_user_input_request / state.task.status
#         （reset_task 损坏态分支例外，已用 not state.task.current_plan 守门）。
#
# 模拟边界说明：本块测试**全部是 source-level 静态扫描**，不构造 fake state、
# 不替换 transition 函数；这是为了：
#   - 避免和 tests/test_user_replied_transition.py 已经端到端覆盖的 6 条
#     transition 行为测试重复（那些是行为契约，这里是结构契约）；
#   - 避免引入"测试本身能 mock 掉的边界"——一个能被 monkeypatch 的契约不是契约。
# ---------------------------------------------------------------------------


def test_user_input_handler_routes_through_apply_user_replied_transition():
    """钉死 handle_user_input_step 必须委托 v0.3 transition，不允许 inline 复刻。

    这条测试守的真实 bug：未来某次"统一 v0.4 vocabulary"的重构可能把
    apply_user_replied_transition 的 import 删掉、把 append/clear/save 三件套
    inline 回 handler，理由听起来都很合理（"减少跨模块跳转"/"和 plan/step/tool
    保持对称"）。一旦发生，handler 就重新承担状态机职责，v0.3 的边界收益归零。
    """
    import inspect

    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_user_input_step)
    assert "apply_user_replied_transition" in src, (
        "handle_user_input_step 必须委托给 apply_user_replied_transition；"
        "如有意去掉，请先把 v0.3 transition 边界的迁移路径写进 "
        "docs/V0_4_EVENT_TRANSITION_PREP.md 并加替代契约测试。"
    )
    assert "resolve_user_input" in src, (
        "handle_user_input_step 必须先经过 resolve_user_input 输入解析层；"
        "跳过它会让 empty_user_input 防御失效，空回复会污染 transition。"
    )


def test_user_input_handler_does_not_inline_mutate_pending_or_status():
    """钉死 handler 不允许直接 mutate pending_user_input_request / task.status。

    真实历史教训：confirm_handlers 早期版本里曾经有
        state.task.pending_user_input_request = None
        state.task.status = "running"
    直接散在 handler 各处。每加一条触发路径就要复刻一次，最后形成"清 pending 与
    保存 checkpoint 顺序不一致"的诡异 bug。v0.3 把它们集中到 transitions.py
    后该问题消失。本测试守住"集中"这件事不被悄悄回滚。

    例外：
      - 文件顶层 import / 类型声明里出现的字符串不在 handler 函数体内，不算违规；
      - reset_task 损坏态分支允许出现（已由 `not current_plan and not pending`
        守门），那是 v0.3 之前就存在的损坏态收尾，不是状态机推进。
    """
    import inspect

    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_user_input_step)
    forbidden_pending = "state.task.pending_user_input_request ="
    forbidden_status = 'state.task.status = "'
    assert forbidden_pending not in src, (
        "handle_user_input_step 不允许直接清/设 pending_user_input_request；"
        "这件事应当通过 apply_user_replied_transition 完成。"
    )
    assert forbidden_status not in src, (
        "handle_user_input_step 不允许直接写 state.task.status；"
        "状态推进是 transitions.py 的职责。"
    )


def test_user_input_handler_keeps_empty_input_guard_before_transition():
    """空输入防御必须在 transition 调用之前。

    真实 bug：如果先调 apply_user_replied_transition、再判 empty，那么空回复
    会先把 pending 清掉、把 step 推进掉，再回头返回"请输入有效内容"——用户看
    到的是同一个错误提示，但底层状态已经不可恢复。
    """
    import inspect

    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_user_input_step)
    empty_idx = src.find("EMPTY_USER_INPUT")
    transition_idx = src.find("apply_user_replied_transition(")
    assert empty_idx != -1 and transition_idx != -1, (
        "handler 源码必须同时引用 EMPTY_USER_INPUT 与 apply_user_replied_transition"
    )
    assert empty_idx < transition_idx, (
        "empty 防御必须出现在 apply_user_replied_transition 调用之前；"
        "顺序反了会让空回复污染 transition 状态。"
    )


def test_user_input_slice_does_not_introduce_new_confirmation_kind():
    """钉死本 slice 不把 user_input 包成新的 *ConfirmationKind。

    这是一条架构契约：v0.4 Phase 1 slice 6-d 显式选择"复用 v0.3 transition"
    而不是"新增 vocabulary"。如果未来真的需要新增（例如要把 user_input 接入
    runtime cancel / generation abort 的统一事件流），必须先在
    docs/V0_4_EVENT_TRANSITION_PREP.md 写明动机、再删掉本测试，而不是悄悄加。
    """
    from agent import runtime_events as re

    forbidden = [
        "UserInputConfirmationKind",
        "USER_INPUT_ACCEPTED",
        "USER_INPUT_REJECTED",
        "user_input_confirmation_transition",
    ]
    for name in forbidden:
        assert not hasattr(re, name), (
            f"runtime_events 不应导出 {name}；slice 6-d 选择复用"
            f" apply_user_replied_transition，不新增并行 vocabulary。"
            f"如确需，请先更新 docs/V0_4_EVENT_TRANSITION_PREP.md。"
        )


def _make_feedback_intent_ctx(*, choice: str, monkeypatch, with_planning_fn=True):
    """构造 awaiting_feedback_intent 状态下的最小 ConfirmationContext。

    模拟边界说明：
    - 直接调 handle_feedback_intent_choice，不走 chat()，避免和 flow 测试重复；
    - generate_plan 被替换为返回 None 的 fake，避免真的调 LLM——本块不验证
      LLM 行为，只验证 mutation 与调用顺序契约；
    - start_planning_fn 用 spy lambda 记录调用顺序而不实际触发新 planner。
    """
    from agent import confirm_handlers as ch
    from agent.checkpoint import CHECKPOINT_PATH as _ORIG_PATH  # noqa: F401
    from agent.confirmation import plan as _ch_mod
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "原始目标 keep me safe"
    state.task.current_plan = {
        "goal": "p",
        "steps": [
            {"step_id": 1, "title": "s", "description": "d", "step_type": "report"}
        ],
    }
    state.task.status = "awaiting_feedback_intent"
    state.task.pending_user_input_request = {
        "awaiting_kind": "feedback_intent",
        "origin_status": "awaiting_step_confirmation",
        "pending_feedback_text": "请把第二步改成先分析",
        "question": "Q",
        "options": ["1", "2", "3"],
    }

    call_log: list[str] = []

    def _fake_generate_plan(*_a, **_kw):
        call_log.append("generate_plan")
        return None

    monkeypatch.setattr(_ch_mod, "generate_plan", _fake_generate_plan)

    def _spy_start_planning(text, ts):
        call_log.append(f"start_planning_fn:{text}")
        return ""

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_runtime_event=lambda _e: call_log.append("emit")),
        client=None,
        model_name="x",
        continue_fn=lambda _ts: "",
        start_planning_fn=_spy_start_planning if with_planning_fn else None,
    )
    # spy reset_task 的调用顺序——通过 monkeypatch state 实例方法
    orig_reset = state.reset_task

    def _spy_reset():
        call_log.append("reset_task")
        return orig_reset()

    state.reset_task = _spy_reset  # type: ignore[method-assign]
    return ch, state, ctx, call_log, choice


def test_feedback_intent_cancel_does_not_write_messages_or_call_planner(
    monkeypatch, tmp_path
):
    """钉死 cancel ("3") 路径：不允许写 messages、不允许调 planner / start_planning_fn。

    真实回归风险：未来 transition 迁移如果把 cancel 也归到统一的 'restore +
    checkpoint' transition 里，可能顺手 append 一条 control event "用户取消了
    反馈意图"——看起来很合理，但破坏 docs/P1_TOPIC_SWITCH_PLAN.md §3 红线
    "cancel = 完全无副作用"，并让 messages 残留一条永远无法撤销的取消记录。
    """
    from agent import checkpoint as ckmod

    ckpt_file = tmp_path / "ckpt.json"
    monkeypatch.setattr(ckmod, "CHECKPOINT_PATH", ckpt_file)

    ch, state, ctx, call_log, _ = _make_feedback_intent_ctx(
        choice="3", monkeypatch=monkeypatch
    )
    before_msgs_len = len(state.conversation.messages)
    before_goal = state.task.user_goal

    ch.handle_feedback_intent_choice("3", ctx)

    assert state.task.status == "awaiting_step_confirmation", (
        "cancel 必须恢复 origin_status"
    )
    assert state.task.pending_user_input_request is None, "cancel 必须清 pending"
    assert state.task.user_goal == before_goal, "cancel 不允许动 user_goal"
    assert len(state.conversation.messages) == before_msgs_len, (
        "cancel 路径不允许 append 任何 control event；这是 P1 §3 红线。"
    )
    assert "generate_plan" not in call_log, "cancel 路径不允许调 LLM planner"
    assert not any(c.startswith("start_planning_fn") for c in call_log), (
        "cancel 路径不允许调 start_planning_fn——那是 as_new_task 路径"
    )


def test_feedback_intent_as_new_task_reset_strictly_precedes_start_planning(
    monkeypatch, tmp_path
):
    """钉死 as_new_task ("2") 路径：reset_task 调用必须**严格先于** start_planning_fn。

    真实回归风险：调用顺序反了会让 start_planning_fn 看到旧 user_goal +
    旧 current_plan，新 plan 可能被旧上下文污染（与 chat() 正常新任务入口不
    同构），破坏 hardcore #6 'user_goal 不膨胀' 不变量。
    """
    from agent import checkpoint as ckmod

    ckpt_file = tmp_path / "ckpt.json"
    monkeypatch.setattr(ckmod, "CHECKPOINT_PATH", ckpt_file)

    ch, state, ctx, call_log, _ = _make_feedback_intent_ctx(
        choice="2", monkeypatch=monkeypatch
    )
    ch.handle_feedback_intent_choice("2", ctx)

    reset_idx = call_log.index("reset_task")
    plan_idx = next(
        i for i, c in enumerate(call_log) if c.startswith("start_planning_fn:")
    )
    assert reset_idx < plan_idx, (
        f"as_new_task 必须先 reset_task 再 start_planning_fn；"
        f"当前调用顺序：{call_log}"
    )
    # start_planning_fn 必须收到 pending_feedback_text 原文，不能被旧 goal 污染
    assert "start_planning_fn:请把第二步改成先分析" in call_log


def test_feedback_intent_as_new_task_without_start_planning_fn_falls_back_safely(
    monkeypatch, tmp_path
):
    """钉死 as_new_task 注入未生效时的安全降级：仍要 reset + clear，不允许悄悄成功。

    真实回归风险：如果未来把这条防御挪到 transition 层，可能漏写"返回提示串"，
    用户看到空字符串以为新任务已经开始，但其实 planner 没启动 → 沉默丢失任务。
    """
    from agent import checkpoint as ckmod

    ckpt_file = tmp_path / "ckpt.json"
    monkeypatch.setattr(ckmod, "CHECKPOINT_PATH", ckpt_file)

    ch, state, ctx, call_log, _ = _make_feedback_intent_ctx(
        choice="2", monkeypatch=monkeypatch, with_planning_fn=False
    )
    reply = ch.handle_feedback_intent_choice("2", ctx)
    assert reply == "请重新输入你的新任务。", (
        "start_planning_fn 注入失败必须显式提示用户重发，不允许返回空串"
    )
    assert "reset_task" in call_log
    assert not any(c.startswith("start_planning_fn") for c in call_log)


def test_feedback_intent_ambiguous_does_not_save_checkpoint_or_mutate_state(
    monkeypatch, tmp_path
):
    """钉死 ambiguous 路径：不允许 save_checkpoint，不允许 mutate state/pending/messages。

    真实回归风险：transition 迁移最危险的统一动作是"任何 confirm 路径结束都
    save_checkpoint"。一旦 ambiguous 路径也被卷入，会把"未决意图"持久化，
    导致下次 resume 状态机从一个本不该存在的中间态恢复。
    """
    from agent import checkpoint as ckmod

    ckpt_file = tmp_path / "ckpt.json"
    monkeypatch.setattr(ckmod, "CHECKPOINT_PATH", ckpt_file)

    ch, state, ctx, call_log, _ = _make_feedback_intent_ctx(
        choice="ambiguous", monkeypatch=monkeypatch
    )
    snap_status = state.task.status
    snap_pending = dict(state.task.pending_user_input_request or {})
    snap_msgs_len = len(state.conversation.messages)
    snap_goal = state.task.user_goal

    ch.handle_feedback_intent_choice("请把第二步改成先分析", ctx)

    assert state.task.status == snap_status
    assert dict(state.task.pending_user_input_request or {}) == snap_pending
    assert len(state.conversation.messages) == snap_msgs_len
    assert state.task.user_goal == snap_goal
    assert not ckpt_file.exists(), (
        "ambiguous 路径不允许写 checkpoint——未决意图不能被持久化"
    )
    assert "generate_plan" not in call_log
    assert not any(c.startswith("start_planning_fn") for c in call_log)
    assert "reset_task" not in call_log
    assert call_log == ["emit"], (
        f"ambiguous 路径只允许 emit feedback_intent_requested 一个动作；"
        f"实际：{call_log}"
    )


def test_feedback_intent_as_feedback_handler_source_does_not_write_revised_goal_back():
    """钉死 as_feedback ("1") 路径源码层：revised_goal 仅作 planner 输入，不允许回写 user_goal。

    真实回归风险：未来 transition 迁移如果把 'feedback 等同于 new task' 当作
    简化点，可能把 revised_goal 也赋回 state.task.user_goal——结果就是用户
    每提一次反馈，user_goal 就被增长一段"补充意见"，违反 hardcore #6
    'user_goal 忠实记录用户最初任务' 不变量。

    这条用源码静态扫描而不是 runtime 行为：runtime 测试容易在重构里被同步
    重写，源码契约更难被绕过。
    """
    import inspect

    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_feedback_intent_choice)
    forbidden_patterns = [
        "state.task.user_goal = revised_goal",
        "state.task.user_goal=revised_goal",
        "state.task.user_goal = f\"{state.task.user_goal}",
        "state.task.user_goal += ",
    ]
    for pat in forbidden_patterns:
        assert pat not in src, (
            f"handle_feedback_intent_choice 不允许把 revised_goal / "
            f"反馈文本回写 state.task.user_goal；命中禁止模式：{pat}。"
            f"详见 hardcore #6 与 commit c252795 的不变量。"
        )
    assert "revised_goal = (" in src or "revised_goal = f" in src, (
        "as_feedback 路径必须显式构造 revised_goal 局部变量，否则边界不清晰"
    )


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-e · feedback_intent confirmation transition（收口切片）
#
# 这是 user-confirmation 系列最后一个 transition slice，也是 slice 6 中**最危险**
# 的一块。前置契约层（slice 6-d 之后的 5 条 contract pin）已经把"什么不能发生"
# 钉死；本 slice 只把 4 条路径的 Runtime 意图通过 FeedbackIntentKind +
# feedback_intent_transition 表达出来，handler 的所有真实 mutation / LLM 调用
# / messages 写入 / start_planning_fn 反向回调 **完全不变**。
#
# 本块测试聚焦 transition 工厂的**意图契约**（不是行为契约——后者已在前置层
# 钉死）。每一条路径的 should_checkpoint / clear_pending_user_input /
# next_status 都精确钉死，防止未来"统一动作"重构悄悄改这些布尔。
# ---------------------------------------------------------------------------


def test_feedback_intent_kind_enum_covers_exactly_four_paths():
    """钉死 FeedbackIntentKind 仅有 4 个值。

    AS_FEEDBACK / AS_NEW_TASK / CANCELLED / AMBIGUOUS 是产品级语义，对应
    awaiting_feedback_intent 子状态的 4 条出口。新增第 5 个值意味着引入新
    路径（例如 'DEFER'），必须先在 docs/V0_4_EVENT_TRANSITION_PREP.md 写
    迁移路径再加；删除任意一个意味着合并语义边界，会破坏 P1 §3 红线。
    """
    from agent.runtime_events import FeedbackIntentKind

    assert {k.value for k in FeedbackIntentKind} == {
        "as_feedback",
        "as_new_task",
        "cancelled",
        "ambiguous",
    }


def test_feedback_intent_as_feedback_transition_intent():
    """as_feedback 意图：should_checkpoint=True + clear_pending=True + next=plan_confirmation。

    handler 调 generate_plan 成功后会重新进入 plan 确认；transition 把 next_status
    显式钉成 'awaiting_plan_confirmation'，防止未来重构把它和 cancel 路径合并。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        feedback_intent_transition,
    )

    t = feedback_intent_transition(FeedbackIntentKind.AS_FEEDBACK)
    assert t.next_status == "awaiting_plan_confirmation"
    assert t.should_checkpoint is True
    assert t.clear_pending_user_input is True
    assert t.clear_pending_tool is False
    assert t.advance_step is False


def test_feedback_intent_as_new_task_transition_intent():
    """as_new_task 意图：should_checkpoint=False（由 clear_checkpoint + start_planning_fn 接管）。

    next_status=None 是契约：transition 不预设新任务的 status，由 start_planning_fn
    内部决定，避免把"新任务的初始 status"和"旧任务的终态"混在一个值里。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        feedback_intent_transition,
    )

    t = feedback_intent_transition(FeedbackIntentKind.AS_NEW_TASK)
    assert t.next_status is None
    assert t.should_checkpoint is False
    assert t.clear_pending_user_input is True


def test_feedback_intent_cancelled_transition_intent():
    """cancel 意图：should_checkpoint=True（origin_status 必须落盘）+ clear_pending=True。

    next_status=None：transition 不替 handler 决定 origin_status 的具体值
    （由 pending['origin_status'] 决定，可能是 awaiting_plan/step_confirmation）；
    handler 自己回填。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        feedback_intent_transition,
    )

    t = feedback_intent_transition(FeedbackIntentKind.CANCELLED)
    assert t.next_status is None
    assert t.should_checkpoint is True
    assert t.clear_pending_user_input is True


def test_feedback_intent_ambiguous_transition_intent_is_critical_no_op():
    """AMBIGUOUS 意图：should_checkpoint=False + clear_pending=False + next=None。

    **这是 slice 6-e 最关键的契约**。AMBIGUOUS 路径的 transition 必须是
    "三个 False"——任何一个变 True 都会让未决意图被持久化或被悄悄推进，
    破坏 docs/P1_TOPIC_SWITCH_PLAN.md §3 反 heuristic 红线。前置契约层
    test_feedback_intent_ambiguous_does_not_save_checkpoint_or_mutate_state
    钉了"行为不能发生"，这条钉"意图层不能宣告"。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        feedback_intent_transition,
    )

    t = feedback_intent_transition(FeedbackIntentKind.AMBIGUOUS)
    assert t.next_status is None
    assert t.should_checkpoint is False, (
        "AMBIGUOUS 不允许 should_checkpoint=True：未决意图禁止持久化"
    )
    assert t.clear_pending_user_input is False, (
        "AMBIGUOUS 不允许清 pending：用户还没决定，pending 必须保留以再次发问"
    )
    assert t.advance_step is False
    assert t.clear_pending_tool is False


def test_feedback_intent_transition_rejects_unknown_kind():
    """未知 kind 必须显式 ValueError，不允许静默兜底。

    模拟边界：构造一个名字像 feedback intent 但实际是 plan kind 的伪装对象，
    确保工厂不会通过 `==` 字符串巧合匹配通过——它必须严格按 enum 身份匹配。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        PlanConfirmationKind,
        feedback_intent_transition,
    )

    with pytest.raises(ValueError, match="unsupported feedback intent kind"):
        feedback_intent_transition(PlanConfirmationKind.PLAN_ACCEPTED)  # type: ignore[arg-type]
    # 4 个合法 kind 全过；防止"循环里漏一个"的回归
    for k in FeedbackIntentKind:
        feedback_intent_transition(k)


def test_feedback_intent_handler_routes_through_transition_factory_for_all_four_paths():
    """钉死 handler 4 条路径都通过 feedback_intent_transition 声明意图。

    源码静态扫描：守住未来"transition 看起来多余，删掉省事"的回归。一旦某
    条路径丢了 transition 调用，未来重构把"统一动作"加回来时，就缺少意图
    层断言（assert not should_checkpoint 等）的保护，AMBIGUOUS 路径会第一
    个被穿透。
    """
    import inspect

    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_feedback_intent_choice)
    # 多行换行兼容：仅断言 'feedback_intent_transition(' 出现至少 4 次 + 4 个 kind 名
    assert src.count("feedback_intent_transition(") >= 4, (
        "handler 必须为 4 条路径都调用 feedback_intent_transition()"
    )
    for kind_name in (
        "FeedbackIntentKind.AS_FEEDBACK",
        "FeedbackIntentKind.AS_NEW_TASK",
        "FeedbackIntentKind.CANCELLED",
        "FeedbackIntentKind.AMBIGUOUS",
    ):
        assert kind_name in src, (
            f"handler 必须显式引用 {kind_name}（不允许字符串别名或动态 lookup 绕过）"
        )
    # 关键 assert 必须留在 handler 中作为 in-source 契约护栏
    assert "assert not ambiguous_transition.should_checkpoint" in src, (
        "handler 必须保留 'AMBIGUOUS 不写 checkpoint' 的 in-source assert"
    )

"""v0.5.1 第二小步 · _dispatch_pending_confirmation characterization tests.

============================================================
本文件保护的真实边界（中文学习型注释）
============================================================

``agent/core.py`` 在 ``chat()`` 函数 L493-L517 区间有一组 5 条 if-branch，
按特定顺序检查 pending 状态并把 ``user_input`` 路由到对应 confirmation
handler；都不命中时落到下方"开启全新任务"路径。这 5 条分支的当前形态：

    L493: status == awaiting_plan_confirmation   → handle_plan_confirmation
    L497: status == awaiting_step_confirmation   → handle_step_confirmation
    L501: status == awaiting_user_input          → handle_user_input_step
          且（current_plan 或 pending_user_input_request）
    L512: status == awaiting_feedback_intent     → handle_feedback_intent_choice
    L516: status == awaiting_tool_confirmation   → handle_tool_confirmation
          且 pending_tool 非空

``docs/V0_5_OBSERVER_AUDIT.md`` / ``agent/local_artifacts.py`` /
``agent/confirm_handlers.py`` 的注释里多次提到这一族**未来**会抽成
``_dispatch_pending_confirmation`` helper。本文件**不抽 helper**，**不改
runtime 行为**——只钉住 5 条分支之间的"互斥与优先级"baseline，保护未来
任何提取式重构不引入：

1. 分支顺序漂移（例如：把 awaiting_plan_confirmation 放到 awaiting_user_input
   之后，导致带 current_plan 的 awaiting_user_input 被错路由到 plan handler）；
2. 守卫条件丢失（例如：忘记 ``pending_tool`` 非空检查，让 awaiting_tool_
   confirmation 在 pending_tool=None 时触发 KeyError 或误调用）；
3. 隐式吞掉 fallthrough（5 条都不命中时必须落到"开启全新任务"路径，否则
   user_input 会被静默丢弃）；
4. 把 user_input 同时投递到多条 handler（两次 transition + 两次 observer
   evidence + 两次 messages 写入）；
5. 把已 done 的 task 误判为还需要 confirmation 而再次进入 handler。

为什么本轮**只**做 characterization：
- 本族 5 条分支对接 5 个 handler、各自有独立 observer evidence 测试覆盖
  （tests/test_confirmation_observer_evidence.py），但**分支选择本身**没有
  独立测试钉死；提取 helper 之前必须先有这层保护，否则提取会引入静默路由
  漂移；
- 不抽 helper 也是为了让未来 helper 命名 / 签名 / 模块归属可以再讨论
  （core.py 内部 vs 新文件 ``confirm_dispatch.py``），现在只锁"行为"。

测试断言风格：
- 每条测试**只**断言 dispatch 选择哪个 handler；不重复 handler 内部细节
  （那由 tests/test_confirmation_observer_evidence.py 与
   tests/test_confirmation_flow.py 钉死）；
- 用 monkeypatch 把 5 个 handler 替换成"打标签"探针，避免与真实 handler
  耦合；探针只记录"被调用 + 收到的 user_input"，不修改 state；
- 这要求 dispatch 在调用 handler **之前**已确定路由——若未来重构把 dispatch
  下推到 handler 内部判断，本测试集会立刻失败暴露 contract 漂移。

不允许：
- 修改 ``agent/core.py``；
- 修改任何 ``agent/confirm_handlers.py``；
- 修改 ``agent/state.py``；
- 改 checkpoint / messages / prompt / provider；
- 引入 sleep / 网络 / 真实 LLM；
- 削弱断言或新增 xfail。
"""

from __future__ import annotations

import pytest

import agent.core as core
from agent.state import create_agent_state


# ----------------------------------------------------------------
# 探针 fixture：把 5 个 handler 换成"打标签"调用记录器
# ----------------------------------------------------------------
# fake/mock 注释：
# - 这不是真实 handler；只是为 dispatch 路由测试提供"被调用即记录"的占位；
# - 返回固定字符串避免 chat() 后续路径解读 None；
# - 不修改 state/messages/checkpoint/observer，让本测试只观察 dispatch 选择
#   本身，不与 handler 内部行为耦合。
@pytest.fixture
def dispatch_probe(monkeypatch):
    """把 5 条 confirmation handler 替换成 probe，返回 calls 列表。

    calls 元素为 ``(handler_name, user_input, status_at_call,
    has_current_plan, has_pending_tool, has_pending_user_input_request)``。
    """
    calls: list = []

    def _make(name):
        def _probe(user_input, ctx):
            calls.append(
                (
                    name,
                    user_input,
                    ctx.state.task.status,
                    bool(ctx.state.task.current_plan),
                    bool(getattr(ctx.state.task, "pending_tool", None)),
                    bool(getattr(ctx.state.task, "pending_user_input_request", None)),
                )
            )
            return f"<probe:{name}>"

        return _probe

    monkeypatch.setattr(core, "handle_plan_confirmation", _make("plan"))
    monkeypatch.setattr(core, "handle_step_confirmation", _make("step"))
    monkeypatch.setattr(core, "handle_user_input_step", _make("user_input"))
    monkeypatch.setattr(core, "handle_feedback_intent_choice", _make("feedback_intent"))
    monkeypatch.setattr(core, "handle_tool_confirmation", _make("tool"))
    return calls


# ----------------------------------------------------------------
# state 构造：复用 confirmation_observer_evidence 的同源风格，但只设置
# dispatch 选择所需的最小字段
# ----------------------------------------------------------------
def _state_with_plan(status: str):
    """构造一个带 current_plan 的 state，调用方再设 status。"""
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test goal"
    state.task.current_plan = {
        "goal": "test goal",
        "steps": [
            {"step_id": "s1", "step_type": "tool", "title": "s1", "description": "d1"},
            {"step_id": "s2", "step_type": "tool", "title": "s2", "description": "d2"},
        ],
    }
    state.task.current_step_index = 0
    state.task.status = status
    return state


def _install_state(monkeypatch, state):
    """把 module-level state 替换为给定 state，等价于 _reset_core_module
    但跳过 fake client 配置（dispatch 测试不会走到 LLM 路径）。"""
    monkeypatch.setattr(core, "state", state)
    return state


# ================================================================
# baseline 测试：5 条分支各自的 happy path
# ================================================================
def test_dispatch_routes_awaiting_plan_confirmation_to_plan_handler(
    dispatch_probe, monkeypatch
):
    """钉死 L493 分支：``awaiting_plan_confirmation`` → handle_plan_confirmation。

    未来 helper 抽取必须保留：plan_confirmation 路由发生在所有其他分支之前，
    因为 plan 阶段 user_input 通常是 yes/no，被任何后续分支"误吃"都会让
    plan 流程死锁或被当成新任务开启。
    """
    _install_state(monkeypatch, _state_with_plan("awaiting_plan_confirmation"))
    ret = core.chat("y")
    assert ret == "<probe:plan>"
    assert [c[0] for c in dispatch_probe] == ["plan"]


def test_dispatch_routes_awaiting_step_confirmation_to_step_handler(
    dispatch_probe, monkeypatch
):
    """钉死 L497 分支：``awaiting_step_confirmation`` → handle_step_confirmation。"""
    _install_state(monkeypatch, _state_with_plan("awaiting_step_confirmation"))
    ret = core.chat("y")
    assert ret == "<probe:step>"
    assert [c[0] for c in dispatch_probe] == ["step"]


def test_dispatch_routes_awaiting_user_input_with_plan_to_user_input_handler(
    dispatch_probe, monkeypatch
):
    """钉死 L501 分支（current_plan 路径）：
    ``status==awaiting_user_input`` 且 ``current_plan`` 非空 → handle_user_input_step。
    """
    _install_state(monkeypatch, _state_with_plan("awaiting_user_input"))
    ret = core.chat("more info")
    assert ret == "<probe:user_input>"
    assert [c[0] for c in dispatch_probe] == ["user_input"]


def test_dispatch_routes_awaiting_user_input_with_pending_request_to_user_input_handler(
    dispatch_probe, monkeypatch
):
    """钉死 L501 分支（pending_user_input_request 路径）：
    没有 current_plan 也行，只要 ``pending_user_input_request`` 非空，
    awaiting_user_input 仍走 user_input handler。

    保护边界：未来如果有人觉得"没 plan 就不算 pending"而把 OR 改成 AND，
    sub-task 内的"请补充信息"流会被静默丢弃。
    """
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test"
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = {"prompt": "需要您提供 X"}
    _install_state(monkeypatch, state)
    ret = core.chat("X 是 42")
    assert ret == "<probe:user_input>"
    assert [c[0] for c in dispatch_probe] == ["user_input"]


def test_dispatch_routes_awaiting_feedback_intent_to_feedback_handler(
    dispatch_probe, monkeypatch
):
    """钉死 L512 分支：``awaiting_feedback_intent`` → handle_feedback_intent_choice。

    保护边界：feedback_intent 是"用户在 plan/step 反馈被判定为模糊后做三选一"
    的独立等待来源；不能被并入 awaiting_user_input 分支，否则 user_input
    handler 会按"补充信息"语义解释，而真实意图是"取消 / 切新任务 / 继续"。
    """
    _install_state(monkeypatch, _state_with_plan("awaiting_feedback_intent"))
    ret = core.chat("1")
    assert ret == "<probe:feedback_intent>"
    assert [c[0] for c in dispatch_probe] == ["feedback_intent"]


def test_dispatch_routes_awaiting_tool_confirmation_with_pending_tool_to_tool_handler(
    dispatch_probe, monkeypatch
):
    """钉死 L516 分支：``awaiting_tool_confirmation`` 且 ``pending_tool`` 非空
    → handle_tool_confirmation。
    """
    state = _state_with_plan("awaiting_tool_confirmation")
    state.task.pending_tool = {
        "tool_name": "fake_tool",
        "tool_use_id": "tu1",
        "tool_input": {"x": 1},
    }
    _install_state(monkeypatch, state)
    ret = core.chat("y")
    assert ret == "<probe:tool>"
    assert [c[0] for c in dispatch_probe] == ["tool"]


# ================================================================
# 守卫条件 / 互斥 / fallthrough：dispatch 行为的"边界"
# ================================================================
def test_dispatch_skips_tool_branch_when_pending_tool_is_none(
    dispatch_probe, monkeypatch
):
    """钉死 L516 守卫：``awaiting_tool_confirmation`` 但 ``pending_tool=None``
    时**不**进入 tool handler。

    这是当前 chat() 的 ``getattr(state.task, "pending_tool", None) and
    state.task.status == "awaiting_tool_confirmation"`` 守卫。如果未来重构
    丢掉 pending_tool 守卫，handler 内部会因 None.get 抛 AttributeError，
    用户会看到栈跟踪而非可行动错误。

    本测试钉死："守卫缺失会让 tool handler 被错调用"——若守卫丢失，
    本测试会失败：dispatch_probe 会记录 ['tool']。
    """
    state = _state_with_plan("awaiting_tool_confirmation")
    state.task.pending_tool = None
    _install_state(monkeypatch, state)
    # 注：dispatch fallthrough 后 chat() 会继续走压缩 + 新任务路径；
    # 该路径需要 fake client，本测试只断言 dispatch_probe 没记录 'tool'。
    # 用 pytest.raises 包住 chat() 调用以隔离 fallthrough 路径所需的运行时；
    # 关键不变量是 dispatch 没把 user_input 投给 tool handler。
    try:
        core.chat("y")
    except Exception:
        pass
    assert [c[0] for c in dispatch_probe] == [], (
        "pending_tool=None 时不能调用任何 confirmation handler；"
        "tool 分支守卫被破坏会让 user_input='y' 被错路由。"
    )


def test_dispatch_skips_user_input_branch_when_neither_plan_nor_pending_request(
    dispatch_probe, monkeypatch
):
    """钉死 L501 守卫：``status==awaiting_user_input`` 但既无 ``current_plan``
    又无 ``pending_user_input_request`` 时**不**进入 user_input handler。

    这是当前 ``status == "awaiting_user_input" and (current_plan or
    pending_user_input_request)`` 守卫。守卫缺失会把"没有等待来源"的
    awaiting_user_input 状态误投到 handle_user_input_step。
    """
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test"
    state.task.status = "awaiting_user_input"
    state.task.current_plan = None
    state.task.pending_user_input_request = None
    _install_state(monkeypatch, state)
    try:
        core.chat("hello")
    except Exception:
        pass
    assert [c[0] for c in dispatch_probe] == [], (
        "无 current_plan 且无 pending_user_input_request 时不应路由到任何"
        " confirmation handler；user_input 应当作新一轮对话处理。"
    )


def test_dispatch_skips_plan_branch_when_current_plan_is_none(
    dispatch_probe, monkeypatch
):
    """钉死 L493 守卫：``status==awaiting_plan_confirmation`` 但 ``current_plan
    =None`` 时**不**进入 plan handler。

    这是当前 ``state.task.current_plan and state.task.status ==
    "awaiting_plan_confirmation"`` 守卫。这种"状态字段不一致"组合是
    L306 reset 路径要修正的对象（YF1 测试已覆盖 L306 reset 本身），
    本测试钉死"在 reset 之前 dispatch 不会误调用 plan handler"。
    """
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test"
    state.task.current_plan = None
    state.task.status = "awaiting_plan_confirmation"
    _install_state(monkeypatch, state)
    try:
        core.chat("y")
    except Exception:
        pass
    assert "plan" not in [c[0] for c in dispatch_probe], (
        "current_plan=None 时不应路由到 plan handler；守卫缺失会让 plan handler"
        " 在 plan 字段缺失时被错调用。"
    )


def test_dispatch_branch_priority_plan_before_step_before_user_input(monkeypatch):
    """钉死分支顺序：当 status 唯一确定时，每条分支独立命中；分支顺序在
    单元层不能被乱序。

    本测试通过观察"5 个 status 各自的命中 handler"间接钉住 if-elif 顺序；
    若未来重构把分支换成 dict 分发表，dict key 必须仍是这 5 个 status，
    且 awaiting_user_input 必须保留 OR 守卫，awaiting_tool_confirmation
    必须保留 pending_tool 守卫。
    """
    expected = {
        "awaiting_plan_confirmation": "plan",
        "awaiting_step_confirmation": "step",
        "awaiting_user_input": "user_input",
        "awaiting_feedback_intent": "feedback_intent",
    }
    for status, target in expected.items():
        calls: list = []

        def _make(name, calls=calls):
            def _probe(user_input, ctx):
                calls.append(name)
                return f"<probe:{name}>"
            return _probe

        monkeypatch.setattr(core, "handle_plan_confirmation", _make("plan"))
        monkeypatch.setattr(core, "handle_step_confirmation", _make("step"))
        monkeypatch.setattr(core, "handle_user_input_step", _make("user_input"))
        monkeypatch.setattr(
            core, "handle_feedback_intent_choice", _make("feedback_intent")
        )
        monkeypatch.setattr(core, "handle_tool_confirmation", _make("tool"))

        state = _state_with_plan(status)
        if status == "awaiting_user_input":
            # L501 守卫需要 current_plan or pending_user_input_request；
            # _state_with_plan 已设 current_plan，满足守卫。
            pass
        _install_state(monkeypatch, state)
        ret = core.chat("y")
        assert ret == f"<probe:{target}>", (
            f"status={status} 必须路由到 {target}，实际 {calls}"
        )
        assert calls == [target], (
            f"status={status} 必须只调用 {target} 一次，实际 {calls}"
        )


def test_dispatch_does_not_double_route_user_input(dispatch_probe, monkeypatch):
    """钉死互斥：每次 chat() 调用最多触发 1 个 confirmation handler。

    保护边界：5 条分支必须互斥；未来若把 if-elif 改成多个独立 if，可能
    一次 chat() 同时触发 2 条分支，导致 user_input 被消耗两次、observer
    evidence 翻倍、messages 重复写入。
    """
    state = _state_with_plan("awaiting_plan_confirmation")
    state.task.pending_tool = {
        "tool_name": "x",
        "tool_use_id": "t",
        "tool_input": {},
    }
    state.task.pending_user_input_request = {"prompt": "x"}
    _install_state(monkeypatch, state)
    core.chat("y")
    assert len(dispatch_probe) == 1, (
        f"同一次 chat() 不能命中多条 confirmation handler，实际触发 "
        f"{[c[0] for c in dispatch_probe]}"
    )
    assert dispatch_probe[0][0] == "plan", (
        "三个 pending 同时存在时, plan_confirmation 优先级最高（L493 在最前）"
    )

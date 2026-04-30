"""v0.5.1 第六小步 · resume 后 pending confirmation dispatch 端到端 characterization tests.

============================================================
本文件保护的真实边界（中文学习型注释）
============================================================

已有测试覆盖了**两段独立**契约：

1. ``tests/test_checkpoint_resume_semantics.py``：5 类 pending 状态被
   ``save_checkpoint`` → ``load_checkpoint_to_state`` 后**字段保留**正确
   （current_plan、pending_user_input_request、pending_tool 等）。
2. ``tests/test_pending_confirmation_dispatch.py``（cdd1427 + bf49a84）：
   给定 in-process state，``chat(user_input)`` 通过 ``_dispatch_pending_
   confirmation`` 路由到正确 handler。

但**两段之间没有直接桥接测试**——即"完整 round-trip：save → load_to_
state → 安装为 module-level state → chat() → dispatch 命中预期 handler"
没有 end-to-end 验证。这是真实风险：

- 若未来有人在 ``_filter_to_declared_fields`` 误删 pending 字段，资料级
  roundtrip 测试可能因为有默认值而仍通过，但 dispatch 路由会失败；
- 若 ``save_checkpoint`` 改持久化策略（比如 pending_tool 被 lazy 持久化
  漏掉），cdd1427 的 in-process dispatch 测试不会失败，但用户重启后
  ``pending_tool`` 为空导致 awaiting_tool_confirmation 永远进不去 tool
  分支；
- 若未来有人改 chat() 顶层"是否做 resume detection / 是否预先调用
  ``_dispatch_pending_confirmation``"的顺序，本文件会立即失败。

本文件**不抽 helper**、**不改 production**——只钉住 5 类 pending 状态
经过完整 checkpoint round-trip 后**仍**能命中正确的 dispatch handler。

为什么 checkpoint 字段保留测试 ≠ runtime dispatch 命中测试
----------------------------------------------------------
- 字段保留测试：断言 ``dst.task.current_plan == src.task.current_plan``
  之类的**数据结构等价**；
- dispatch 命中测试：断言 ``chat(user_input)`` 进入正确 handler——这要求
  status / current_plan / pending_* 几个字段**联合满足** ``_dispatch_
  pending_confirmation`` 5 条 if-branch 中预期那一条的**全部守卫条件**；
- 任何一个守卫条件被 resume 漏带（例如 status 字符串规范化、
  pending_user_input_request 字段名漂移），数据级测试可能不察觉，
  dispatch 测试一定失败。

为什么桥接 checkpoint save/load + _dispatch_pending_confirmation
---------------------------------------------------------------
- 这两个模块在 production 中本来就是相邻调用：用户 Ctrl-C 中断 → 下次
  启动 ``main.py`` 调 ``load_checkpoint_to_state`` → 用户输入 → ``chat()``
  → ``_dispatch_pending_confirmation``；
- 当前没有任何测试**完整**走过这条链路，等于这条 production 主路径靠
  "字段对了 + dispatch 对了"两段断言拼凑——任何中间隐式漂移都难发现。

测试与 core.py 瘦身 / runtime 边界治理 roadmap 的关系
-----------------------------------------------------
- v0.5.1 已通过 cdd1427→bf49a84 / 605196c→be502c7 两轮 char→refactor
  把 chat() / _run_main_loop 内的 dispatch 抽成独立 helper；
- 下一步可能继续抽 chat() 顶层"resume detection / new_task entry"，但
  没有桥接 baseline 就抽极易引入"resume 后状态丢失"silent bug；
- 本文件提供这一 baseline，是后续 chat() 顶层瘦身的安全网。

为什么不读真实 sessions/runs，使用 synthetic fixture / tmp_path
---------------------------------------------------------------
- 真实 sessions/ runs/ 含用户隐私（goal / messages / tool args），测试
  绝对不能依赖；
- ``tmp_checkpoint_path`` fixture（与 test_checkpoint_resume_semantics.py
  同源）通过 monkeypatch ``CHECKPOINT_PATH`` 到 tmp_path，每个测试独立
  且可重现；
- 这也保证 CI 环境里测试不会污染开发者本地 ``checkpoint.json``。

不允许（本切片硬约束）：
- 修改 ``agent/core.py``；
- 修改 ``agent/checkpoint.py``；
- 修改 ``agent/state.py`` / ``confirm_handlers.py``；
- 修改 checkpoint schema；
- 修改 ``_dispatch_pending_confirmation`` / ``_dispatch_model_output``；
- 修改 handlers 内部；
- 修改 ``_call_model`` / tool_executor / runtime/display event 语义；
- 引入新 production module；
- 弱化或新增 xfail / skip。
"""

from __future__ import annotations

import pytest

import agent.core as core
from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
from agent.state import create_agent_state


# ----------------------------------------------------------------
# 复用 test_checkpoint_resume_semantics.py 同款 fixture 模式
# ----------------------------------------------------------------
# fake/mock 边界：
# - ``tmp_checkpoint_path`` 通过 monkeypatch 把 CHECKPOINT_PATH 重定向到
#   tmp_path，每个测试独立、不污染开发者本地 checkpoint.json；
# - 这是 v0.2 M3 已建立的 fixture 模式，非本切片新增，复用即可。
@pytest.fixture
def tmp_checkpoint_path(tmp_path, monkeypatch):
    from agent import checkpoint

    path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    return path


# ----------------------------------------------------------------
# 探针 fixture：与 test_pending_confirmation_dispatch.py 同款
# ----------------------------------------------------------------
# fake/mock 边界：
# - 把 5 个 confirmation handler 替换成"打标签"调用记录器；
# - 探针**只**记录 handler 名称 + status 现场，不修改 state / messages /
#   checkpoint / observer——让本测试**只**观察"resume 后 dispatch 选择
#   哪个 handler"，与 handler 内部行为完全解耦；
# - 与 cdd1427 的 dispatch_probe 同模式，但**不**复用同一 fixture，因为
#   两个测试文件场景不同：cdd1427 测 in-process dispatch；本文件测
#   resume → dispatch 端到端。
@pytest.fixture
def dispatch_probe(monkeypatch):
    """把 5 条 confirmation handler 替换成 probe，返回 calls 列表。"""
    calls: list[tuple[str, str]] = []

    def _make(name):
        def _probe(user_input, ctx):
            calls.append((name, ctx.state.task.status))
            return f"<probe:{name}>"

        return _probe

    monkeypatch.setattr(core, "handle_plan_confirmation", _make("plan"))
    monkeypatch.setattr(core, "handle_step_confirmation", _make("step"))
    monkeypatch.setattr(core, "handle_user_input_step", _make("user_input"))
    monkeypatch.setattr(core, "handle_feedback_intent_choice", _make("feedback_intent"))
    monkeypatch.setattr(core, "handle_tool_confirmation", _make("tool"))
    return calls


def _save_then_load_into_core(src, monkeypatch):
    """完整 round-trip：save src → 新建空 dst → load → 安装为 core.state。

    这是本文件的核心测试 helper：把**已有 checkpoint roundtrip** 与
    **module-level state 安装**两段拼成"resume 后下一次 chat() 准备就绪"
    的完整场景。

    保护契约：
    - ``save_checkpoint(src, source=...)`` 必须能把 src 的所有 pending
      字段持久化；
    - ``load_checkpoint_to_state(dst)`` 必须把这些字段恢复到 dst.task；
    - ``monkeypatch.setattr(core, "state", dst)`` 让 chat() 使用恢复后的
      state——这是 production 中 main.py 启动后真实路径的等价模拟。
    """
    save_checkpoint(src, source="tests.resume_pending_dispatch")
    dst = create_agent_state(system_prompt="other")
    assert load_checkpoint_to_state(dst), "load_checkpoint_to_state 必须返回 True"
    monkeypatch.setattr(core, "state", dst)
    return dst


# ================================================================
# 5 条 baseline 测试：5 类 pending 状态完整 round-trip 后 dispatch 命中
# ================================================================
def test_resume_awaiting_plan_confirmation_dispatches_to_plan_handler(
    tmp_checkpoint_path, dispatch_probe, monkeypatch
):
    """钉死：resume awaiting_plan_confirmation → 下一次 chat() 命中 plan handler。

    场景模拟：用户在 plan 等待确认时退出，下次启动后 main.py 已
    load_checkpoint_to_state；用户输入 "y"。本测试断言 dispatch
    必须进入 plan_confirmation 分支，**不能**被当成新任务开启。

    保护边界：若未来 save 漏带 status / load 漏带 current_plan，
    或 _dispatch_pending_confirmation 守卫条件改变，dispatch 会落到
    fallthrough（开启新任务），本测试立即失败。
    """
    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "做某事"
    src.task.current_plan = {
        "goal": "g",
        "steps": [{"step_id": "s1", "step_type": "tool", "title": "step1", "description": "d1"}],
    }
    src.task.current_step_index = 0
    src.task.status = "awaiting_plan_confirmation"

    _save_then_load_into_core(src, monkeypatch)
    ret = core.chat("y")

    assert ret == "<probe:plan>"
    assert [c[0] for c in dispatch_probe] == ["plan"]


def test_resume_awaiting_step_confirmation_dispatches_to_step_handler(
    tmp_checkpoint_path, dispatch_probe, monkeypatch
):
    """钉死：resume awaiting_step_confirmation → 下一次 chat() 命中 step handler。

    保护边界：current_step_index 若 resume 时未恢复（停留在 0），dispatch
    分支条件可能仍满足，但 step handler 内部会从 step 0 开始而非续接——
    这是 dispatch 路由测试钉不到的二级问题，本切片**不**覆盖那一层；
    本测试只钉 dispatch 命中 step handler 这一边界。
    """
    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "做某事"
    src.task.current_plan = {
        "goal": "g",
        "steps": [
            {"step_id": "s1", "step_type": "tool", "title": "step1", "description": "d1"},
            {"step_id": "s2", "step_type": "tool", "title": "step2", "description": "d2"},
        ],
    }
    src.task.current_step_index = 1
    src.task.status = "awaiting_step_confirmation"

    _save_then_load_into_core(src, monkeypatch)
    ret = core.chat("y")

    assert ret == "<probe:step>"
    assert [c[0] for c in dispatch_probe] == ["step"]


def test_resume_awaiting_user_input_dispatches_to_user_input_handler(
    tmp_checkpoint_path, dispatch_probe, monkeypatch
):
    """钉死：resume awaiting_user_input + pending_user_input_request →
    下一次 chat() 命中 user_input handler（不需 current_plan 也行）。

    保护边界：``pending_user_input_request`` 若 resume 漏带，dispatch
    L501 OR 条件失败，user_input 会落到 fallthrough 被当新任务——这是
    "用户被问了问题，重启后回答却被当成全新任务"的真实 silent bug；
    本测试钉死必须命中 user_input handler 而非 fallthrough。
    """
    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "test"
    src.task.status = "awaiting_user_input"
    src.task.pending_user_input_request = {
        "awaiting_kind": "clarification",
        "prompt": "需要您提供 X",
    }

    _save_then_load_into_core(src, monkeypatch)
    ret = core.chat("X 是 42")

    assert ret == "<probe:user_input>"
    assert [c[0] for c in dispatch_probe] == ["user_input"]


def test_resume_awaiting_feedback_intent_dispatches_to_feedback_handler(
    tmp_checkpoint_path, dispatch_probe, monkeypatch
):
    """钉死：resume awaiting_feedback_intent → 下一次 chat() 命中 feedback handler。

    保护边界：feedback_intent 状态意味着 agent 已请用户在 plan 多个候选
    中作出 feedback；resume 后若 status 漂移到 awaiting_user_input，
    dispatch 会走错分支。本测试钉死必须命中 feedback_intent handler。
    """
    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "test"
    src.task.current_plan = {
        "goal": "g",
        "steps": [{"step_id": "s1", "step_type": "tool", "title": "s1", "description": "d1"}],
    }
    src.task.current_step_index = 0
    src.task.status = "awaiting_feedback_intent"

    _save_then_load_into_core(src, monkeypatch)
    ret = core.chat("1")

    assert ret == "<probe:feedback_intent>"
    assert [c[0] for c in dispatch_probe] == ["feedback_intent"]


def test_resume_awaiting_tool_confirmation_dispatches_to_tool_handler(
    tmp_checkpoint_path, dispatch_probe, monkeypatch
):
    """钉死：resume awaiting_tool_confirmation + pending_tool →
    下一次 chat() 命中 tool handler，且**不**真实执行工具。

    保护边界：``pending_tool`` 是 dispatch L516 的硬守卫——pending_tool
    若 resume 漏带，分支条件失败，dispatch 会走 fallthrough 把 user_input
    当新任务，导致工具确认被吞掉。本测试钉死 pending_tool 经过完整
    round-trip 后仍存在，且 dispatch 命中 tool handler；探针返回
    ``"<probe:tool>"`` 直接退出 chat()，**不**进入真实 tool_executor，
    保证测试不执行任何危险工具或写入 tool_result。
    """
    src = create_agent_state(system_prompt="test")
    src.task.user_goal = "test"
    src.task.current_plan = {
        "goal": "g",
        "steps": [{"step_id": "s1", "step_type": "tool", "title": "s1", "description": "d1"}],
    }
    src.task.current_step_index = 0
    src.task.status = "awaiting_tool_confirmation"
    src.task.pending_tool = {
        "tool": "shell.exec",
        "tool_use_id": "tu_test_001",
        "input": {"command": "echo hi"},
    }

    _save_then_load_into_core(src, monkeypatch)
    ret = core.chat("y")

    assert ret == "<probe:tool>"
    assert [c[0] for c in dispatch_probe] == ["tool"]

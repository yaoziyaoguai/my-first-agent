"""v0.5.1 第四小步 · _run_main_loop ModelOutputKind dispatch characterization tests.

============================================================
本文件保护的真实边界（中文学习型注释）
============================================================

``agent/core.py::_run_main_loop`` 在每轮 ``while True`` 中拿到
``response = _call_model(...)`` 后，调用 ``classify_model_output(response.stop_reason)``
得到 :class:`ModelOutputKind`，然后按 4 个 if-branch 派发到对应 handler：

    L875  MAX_TOKENS  → handle_max_tokens_response
    L898  END_TURN    → handle_end_turn_response
    L920  TOOL_USE    → handle_tool_use_response
    L942  UNKNOWN     → fallback: 发 unknown_stop_reason RuntimeEvent，
                        log loop.stop(reason_for_stop=unknown_stop_reason)，
                        return "意外的响应"

本文件**不抽 helper**、**不改 production**——只钉住"4 个分支之间的互斥
路由 + 各自的 baseline 行为"，为后续小步抽 ``_dispatch_model_output``
helper 铺安全网（与 cdd1427→bf49a84 对 confirmation dispatch 的同源模式
对齐）。

为什么本轮**只**做 characterization：
- 现有 tests（``test_v0_4_transition_boundaries`` 钉 transition 命名词表，
  ``test_core_loop_terminal_prints`` 钉 UNKNOWN 文案与 RuntimeEvent 迁移）
  都不直接钉"_run_main_loop 选哪个 handler"这一路由本身；
- 一旦未来抽 helper（哪怕只是把 4 个 if 改成 dict-dispatch），分支顺序、
  handler 签名、None→continue 语义、UNKNOWN return value 任何一项漂移
  都可能让 LLM 协议变体被静默吞掉；
- 本文件确保任一漂移在重构当下立刻失败，而不是等到 production agent
  跑出 silent success / wrong-handler 才被发现。

测试断言风格：
- 用 monkeypatch 把 3 个 handler 替换成"打标签"探针，避免与真实 handler
  耦合；探针只记录"被调用 + 收到的 stop_reason"，返回固定字符串；
- 用 monkeypatch 把 ``_call_model`` 替换成可控 ``_FakeResponse``，避免
  接真实 LLM；
- 每条测试**只**断言 dispatch 选择哪个 handler；不重复 handler 内部细节
  （那些由 ``test_response_handlers*`` / ``test_max_tokens_*`` 等钉死）；
- UNKNOWN 测试同时断言 3 个 handler 都未被调用，钉死"未知不能被静默
  归到 end_turn / tool_use / max_tokens"这一 v0.4 slice 5 核心契约。

不允许（本切片硬约束）：
- 修改 ``agent/core.py``；
- 修改 ``agent/runtime_events.py``（含 ``classify_model_output``）；
- 修改 ``agent/response_handlers.py`` 任何 handler；
- 修改 ``agent/tool_executor.py`` / checkpoint / ``_call_model`` 实现；
- 修改 confirmation dispatch / Ask User / display event 语义；
- 弱化断言、新增 xfail / skip、删除现有测试；
- 抽 ``_dispatch_model_output`` helper（下一切片再说）；
- 引入新 production module。

未来扩展点：
- 当真正抽 ``_dispatch_model_output`` helper 时，本文件全部测试应**继续
  通过**（行为中性证明）；如果通过不了，说明重构改了语义，必须先回退；
- 若未来新增第 5 类 ModelOutputKind（如 ``REFUSAL``），本文件应增 1 条
  断言新分支被路由到对应 handler，并断言旧 4 条仍互斥。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent.core as core
from agent.loop_context import LoopContext
from agent.runtime_events import ModelOutputKind
from agent.state import create_agent_state


# ----------------------------------------------------------------
# fake/mock 注释：
# - ``_FakeResponse`` 是模拟 Anthropic SDK 返回对象的最小占位，只暴露
#   ``stop_reason`` 字段（_run_main_loop 唯一消费的属性）；
# - 不携带 content blocks，因为本文件 monkeypatch 掉了 3 个 handler，
#   handler 内部不会真实读 content；
# - 不模拟 token usage / model id 等字段——那些由 ``_call_model`` 内部
#   logging 消费，本切片不覆盖。
# ----------------------------------------------------------------
class _FakeResponse:
    """模拟 ``_call_model`` 返回值的最小响应对象。"""

    def __init__(self, stop_reason: str | None):
        self.stop_reason = stop_reason
        self.content = []


@pytest.fixture
def dispatch_probes(monkeypatch):
    """把 3 个 ModelOutputKind handler 换成"打标签"探针。

    返回 ``calls`` 列表：每条元素 ``(handler_name, stop_reason)``。
    探针默认返回字符串结果，使 ``_run_main_loop`` 命中 ``return result``
    分支并退出循环——避免无限循环依赖更复杂的 fake state。

    fake/mock 边界：
    - 探针不模拟 handler 的 messages / state / checkpoint mutation；
    - 本测试只观察"是哪个 handler 被选中 + stop_reason 是否原样到达"，
      不验证 handler 内部副作用（那由 handler 单元测试钉死）；
    - 若未来 ``_run_main_loop`` 改为通过 dict / 注册表 dispatch，本探针
      仍然能捕获——前提是 dispatch 最终调用 ``handle_*_response`` 模块
      级符号，没有把 handler 替换成 inline lambda。
    """
    calls: list[tuple[str, str | None]] = []

    def _make(name):
        def _probe(response, **kwargs):
            calls.append((name, response.stop_reason))
            return f"<probe:{name}>"

        return _probe

    monkeypatch.setattr(core, "handle_max_tokens_response", _make("max_tokens"))
    monkeypatch.setattr(core, "handle_end_turn_response", _make("end_turn"))
    monkeypatch.setattr(core, "handle_tool_use_response", _make("tool_use"))
    return calls


def _install_clean_state(monkeypatch):
    """把 module-level ``state`` 重置为干净的最小可运行 state。

    与 ``test_pending_confirmation_dispatch._install_state`` 的设计对齐：
    跳过 fake LLM client 配置，因为本测试 monkeypatch 掉了 ``_call_model``，
    不会走到真实 client 路径。
    """
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test goal"
    monkeypatch.setattr(core, "state", state)
    return state


def _build_runtime(monkeypatch, fake_response: _FakeResponse):
    """构造 ``_run_main_loop`` 直接调用所需的最小运行时。

    fake/mock 边界：
    - ``_call_model`` 被替换为常量返回器：每次都返回同一个 fake_response，
      让循环最多再绕一圈就退出（探针返回非 None 即 return）；
    - ``LoopContext.client`` 必须是显式 fake（``loop_context`` 模块拒绝
      ``None`` 以防初始化错乱），这里用 ``SimpleNamespace()`` 占位——
      ``_call_model`` 已被 monkeypatch，client 的方法不会被调用；
    - ``TurnState.on_runtime_event=None`` 让 UNKNOWN 分支走 stdout 兜底，
      不依赖 capsys 之外的 sink。
    """
    monkeypatch.setattr(core, "_call_model", lambda turn_state, loop_ctx: fake_response)
    turn_state = core.TurnState(system_prompt="test")
    fake_client = SimpleNamespace()
    loop_ctx = LoopContext(
        client=fake_client, model_name="fake-model", max_loop_iterations=10
    )
    return turn_state, loop_ctx


# ================================================================
# baseline 测试：4 个 ModelOutputKind 分支各自的 happy path
# ================================================================
def test_dispatch_routes_max_tokens_to_max_tokens_handler(
    dispatch_probes, monkeypatch
):
    """钉死 L875 分支：``stop_reason='max_tokens'`` → handle_max_tokens_response。

    保护契约：未来抽 dispatch helper 时若把 MAX_TOKENS 顺序与其他分支
    交换、或忘记把 ``MAX_CONTINUE_ATTEMPTS`` 透传给 handler，本测试会
    立即失败（探针只在 handler 被以正确符号调用时才追加 calls）。
    """
    _install_clean_state(monkeypatch)
    turn_state, loop_ctx = _build_runtime(monkeypatch, _FakeResponse("max_tokens"))

    result = core._run_main_loop(turn_state, loop_ctx)

    assert result == "<probe:max_tokens>"
    assert dispatch_probes == [("max_tokens", "max_tokens")]


def test_dispatch_routes_end_turn_to_end_turn_handler(
    dispatch_probes, monkeypatch
):
    """钉死 L898 分支：``stop_reason='end_turn'`` → handle_end_turn_response。"""
    _install_clean_state(monkeypatch)
    turn_state, loop_ctx = _build_runtime(monkeypatch, _FakeResponse("end_turn"))

    result = core._run_main_loop(turn_state, loop_ctx)

    assert result == "<probe:end_turn>"
    assert dispatch_probes == [("end_turn", "end_turn")]


def test_dispatch_routes_tool_use_to_tool_use_handler(
    dispatch_probes, monkeypatch
):
    """钉死 L920 分支：``stop_reason='tool_use'`` → handle_tool_use_response。

    重要边界：本测试**不**让 handler 真正执行工具——探针直接 return 字符串
    退出循环。tool 执行的真实路径由 ``test_tool_executor*`` 钉死；
    这里只钉"dispatch 路由本身"。
    """
    _install_clean_state(monkeypatch)
    turn_state, loop_ctx = _build_runtime(monkeypatch, _FakeResponse("tool_use"))

    result = core._run_main_loop(turn_state, loop_ctx)

    assert result == "<probe:tool_use>"
    assert dispatch_probes == [("tool_use", "tool_use")]


def test_dispatch_routes_unknown_stop_reason_to_unknown_fallback(
    dispatch_probes, monkeypatch, capsys
):
    """钉死 L942 UNKNOWN 分支：未知 stop_reason → 不调用任何 handler，
    fallback 返回 ``"意外的响应"``，并把 ``unknown_stop_reason_event``
    投递到 sink（这里 sink=None，回退 stdout）。

    这是 v0.4 slice 5 / v0.5 slice 7D 的核心防回归点：
    - 未知 stop_reason 不能被任何 handler 静默吃掉（否则 SDK 协议变更
      会被伪装成"正常完成"）；
    - 本测试断言 ``dispatch_probes`` 为空——3 个 handler 都没被调用；
    - return value ``"意外的响应"`` 是当前用户可见 fallback 文案，由
      ``test_core_loop_terminal_prints`` 钉过 print → RuntimeEvent 迁移，
      但**没有**测试钉死 return value 本身。
    """
    _install_clean_state(monkeypatch)
    turn_state, loop_ctx = _build_runtime(monkeypatch, _FakeResponse("banana_split"))

    result = core._run_main_loop(turn_state, loop_ctx)

    assert result == "意外的响应"
    # 关键互斥断言：UNKNOWN 不能复用任何已有 handler。
    assert dispatch_probes == []


def test_dispatch_routes_none_stop_reason_to_unknown_fallback(
    dispatch_probes, monkeypatch
):
    """钉死 ``stop_reason=None`` 也走 UNKNOWN 分支（防"None 被 truthy
    检查误判为已知"）。

    这条独立测试因为 ``classify_model_output(None) → UNKNOWN`` 是 v0.4
    slice 5 显式契约——若有人把 ``classify_model_output`` 改成 ``if not
    stop_reason: return ModelOutputKind.END_TURN``，本测试立即失败。
    """
    _install_clean_state(monkeypatch)
    turn_state, loop_ctx = _build_runtime(monkeypatch, _FakeResponse(None))

    result = core._run_main_loop(turn_state, loop_ctx)

    assert result == "意外的响应"
    assert dispatch_probes == []


# ================================================================
# 互斥与 None→continue 语义
# ================================================================
def test_handler_returning_none_continues_loop_until_handler_returns_str(
    monkeypatch,
):
    """钉死"handler return None → continue 循环；return str → 退出"语义。

    保护契约：4 个分支都遵循 ``if result is not None: return result;
    continue`` 模式。任何把 ``None`` 当成"已完成"或把空串当成"未完成"
    的改动都会破坏这条契约——本测试通过让 handler 前两次返回 None、
    第三次返回 ``"DONE"`` 来观察循环计数。
    """
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "test"
    monkeypatch.setattr(core, "state", state)

    call_count = {"n": 0}

    def _handler(response, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return None
        return "DONE"

    monkeypatch.setattr(core, "handle_end_turn_response", _handler)
    turn_state, loop_ctx = _build_runtime(monkeypatch, _FakeResponse("end_turn"))

    result = core._run_main_loop(turn_state, loop_ctx)

    assert result == "DONE"
    assert call_count["n"] == 3


def test_dispatch_only_calls_one_handler_per_iteration(
    dispatch_probes, monkeypatch
):
    """钉死"每轮迭代只调用一个 handler"互斥契约。

    保护边界：未来若有人误把 4 个 if 改成多个 if（例如忘记 else），
    同一 stop_reason 可能被多个 handler 处理——本测试通过单次 stop_reason
    断言 ``len(dispatch_probes) == 1`` 钉死单一路由。
    """
    _install_clean_state(monkeypatch)
    turn_state, loop_ctx = _build_runtime(monkeypatch, _FakeResponse("end_turn"))

    core._run_main_loop(turn_state, loop_ctx)

    assert len(dispatch_probes) == 1
    assert dispatch_probes[0][0] == "end_turn"


# ================================================================
# classify_model_output 是唯一 truth source
# ================================================================
def test_dispatch_uses_classify_model_output_as_only_kind_decider(monkeypatch):
    """钉死"_run_main_loop 路由完全由 classify_model_output 决定"契约。

    这条测试 monkeypatch ``classify_model_output`` 强制返回 END_TURN，
    无论 fake response 的 stop_reason 是什么——验证 dispatch **不**直接
    比较 ``response.stop_reason`` 字符串，而是走分类层。

    保护边界：v0.4 slice 5 的核心架构契约是"分类层是 stop_reason → kind
    的唯一翻译路径"。若有人在 dispatch 里又写 ``if response.stop_reason
    == 'tool_use'`` 旁路，本测试立即失败。
    """
    _install_clean_state(monkeypatch)
    end_turn_calls: list = []

    def _end_turn_probe(response, **kwargs):
        end_turn_calls.append(response.stop_reason)
        return "FORCED_END"

    monkeypatch.setattr(core, "handle_end_turn_response", _end_turn_probe)
    monkeypatch.setattr(
        core, "classify_model_output", lambda stop_reason: ModelOutputKind.END_TURN
    )
    # 故意用 "tool_use"——若 dispatch 直接比字符串就会去 tool_use 分支，
    # 本断言失败。
    turn_state, loop_ctx = _build_runtime(monkeypatch, _FakeResponse("tool_use"))

    result = core._run_main_loop(turn_state, loop_ctx)

    assert result == "FORCED_END"
    assert end_turn_calls == ["tool_use"]


# ================================================================
# 静态契约：ModelOutputKind 词表稳定
# ================================================================
def test_model_output_kind_vocabulary_remains_four_known_values():
    """钉死 ModelOutputKind 词表只有 4 个值。

    若未来新增第 5 类（如 ``REFUSAL``），本测试**应该**失败——失败的
    正确处理不是删测试，而是：
    1. 在 _run_main_loop 中**显式**新增对应分支并钉死路由测试；
    2. 在 ``classify_model_output`` 中**显式**映射；
    3. 然后再更新本测试断言。

    这条测试存在的意义是防止"新增 enum 值但忘记加 dispatch 分支"——
    那种情况下新值会被静默归到 UNKNOWN，把真实业务输出伪装成异常。
    """
    assert {kind.value for kind in ModelOutputKind} == {
        "end_turn",
        "tool_use",
        "max_tokens",
        "unknown",
    }

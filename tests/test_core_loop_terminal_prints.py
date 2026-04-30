"""core.py user-facing print baseline characterization (v0.5 Phase 1 第七小步 B)。

────────────────────────────────────────────────────────────────────
本测试模块要解决的真实风险
────────────────────────────────────────────────────────────────────
``agent/core.py`` 在 Runtime 主循环里仍有 3 处 user-facing ``print()``
**绕过** 了 ``_emit_runtime_event`` 统一投递桥（见 ``agent/core.py``
L318 ``_emit_runtime_event`` 的"Runtime 内 RuntimeEvent 唯一投递出口"
契约）：

1. L306 ``print("[系统] 检测到不一致状态…")``
   场景：``task.status`` 要求有 plan 但 ``current_plan is None`` →
   ``state.reset_task()`` 之前先 print。

2. L670 ``print(f"\\n[系统] 循环次数超过上限 {max_loop_iterations}，强制停止。")``
   场景：主循环跑满 ``MAX_LOOP_ITERATIONS`` 仍未收敛，终极兜底触发。

3. L769 ``print(f"[系统] 未知的 stop_reason: {response.stop_reason}")``
   场景：模型返回 ``end_turn / tool_use / max_tokens`` 之外的未知值。

为什么这是真实 bug（v0.5 audit doc §G1）
-----------------------------------------
- 在仅传 ``on_runtime_event=...`` 的前端（如未来 TUI / IDE 插件 /
  remote shell）下，stdout 被 sink 接管或重定向，**用户完全看不到**
  这 3 条诊断信息；
- 现有 L338 / L345 / L350 ``print`` 已经被 ``_emit_runtime_event``
  内部的"无 callback fallback"路径包住了（callback 存在时不重复 print）；
- L306 / L670 / L769 是 **唯一** 没走这个保护的 user-facing print，
  代表"无 callback 看得到、有 callback 看不到"的不对称。

为什么本切片不直接修 print
----------------------------
- 真正修复需要：把 3 处 print 改成 ``_emit_runtime_event(...)`` +
  在 ``runtime_events.RuntimeEventKind`` 添加对应 enum +
  ``render_runtime_event_for_cli`` 添加渲染分支 → 跨 3 个文件、
  涉及 RuntimeEvent schema 扩张，**不属于** "0 runtime 行为变更"边界。
- 本切片先用 capsys + monkeypatch 钉住 baseline：
  * 无 callback 时 stdout **必须** 含上述文本（否则诊断丢失）；
  * 有 callback 时 stdout **必须不重复** 含上述文本（否则将来迁移到
    ``_emit_runtime_event`` 后会出现 stdout + callback 双投递）。
- 后续 D slice 真正迁移时，本测试会"反向暴露"：
  * 无 callback 测试会 fail（fallback 文案变了/格式变了）→ 强制
    reviewer 确认是有意还是回归；
  * 有 callback 测试会 fail 当且仅当迁移做错（callback 与 stdout 双投）。

本测试不做的事
---------------
- 不改 ``agent/core.py``；
- 不引入 ``emit_display_event`` 调用；
- 不动 DEBUG_PROTOCOL 16 处（双重 guard：``DEBUG_PROTOCOL=False`` +
  env ``MY_FIRST_AGENT_PROTOCOL_DUMP``）；
- 不动 ASSISTANT_DELTA fallback (L338 / L345 / L350)，那条路径已被
  ``_emit_runtime_event`` 内部的 ``on_output_chunk`` / ``on_display_event``
  双向桥接保护；
- 不调真实 LLM、不读 ``.env`` / ``agent_log.jsonl`` / 真实 sessions；
- 不削弱已有断言、不引入 skip / xfail。

artifact 排查
--------------
若本测试在 D slice 迁移后 fail，先看：
1. ``agent/core.py`` L306 / L670 / L769 是否仍是裸 ``print()``；
2. 若已改 ``_emit_runtime_event``，确认 ``_emit_runtime_event`` 的
   "无 callback fallback" 分支是否仍 print 等价文案（否则诊断丢失）；
3. ``agent/runtime_events.py`` 是否新增对应 RuntimeEventKind；
4. ``agent/display_events.render_runtime_event_for_cli`` 是否能渲染。
"""

from __future__ import annotations

from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    FakeToolUseBlock,
    text_response,
)
from tests.test_main_loop import (
    _planner_no_plan_response,
    _register_test_tool,
    _reset_core_module,
)


def _build_state_with_inconsistent_plan_required(monkeypatch):
    """构造 ``status=awaiting_user_input`` 但 ``current_plan=None`` 的
    不一致 state，让 chat() 进入 L306 reset 分支。

    与 ``tests/test_state_invariants.py:166`` 同源：复用既有受信场景。
    """
    fake = FakeAnthropicClient(
        responses=[
            _planner_no_plan_response(),
            text_response("收到"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)
    state.task.status = "awaiting_user_input"
    state.task.current_plan = None
    state.task.pending_user_input_request = None
    return state


def _tool_use_resp_with_arg(tool_name, tool_id, arg):
    """构造 stop_reason=tool_use 的响应，复用 test_completion_handoff 同源构造。

    每轮 arg 不同：避开 ``MAX_REPEATED_TOOL_INPUTS=3`` 同输入兜底，
    让循环跑满 ``MAX_LOOP_ITERATIONS`` 触发 L670。
    """
    return FakeResponse(
        content=[FakeToolUseBlock(id=tool_id, name=tool_name, input={"arg": arg})],
        stop_reason="tool_use",
    )


def _fake_unknown_stop_response():
    """构造 stop_reason=未知值 的响应，触发 L769 print。

    内含一个 tool_use（与 ``test_hardcore_round2:test_unknown_stop_reason_*``
    同源），同时验证未知 stop_reason 路径下 tool_use 的处理边界。
    """
    return FakeResponse(
        content=[
            FakeTextBlock(text="尝试调工具"),
            FakeToolUseBlock(id="T_WEIRD_BASELINE", name="w", input={"arg": "x"}),
        ],
        stop_reason="stop_sequence",
    )


# ============================================================
# L306 · state inconsistency reset baseline
# ============================================================


def test_state_inconsistency_reset_print_visible_without_callback(monkeypatch, capsys):
    """L306 baseline · 无 callback → stdout **必须**含"检测到不一致状态"。

    若 D slice 误把 print 删掉而没补 fallback，本测试立即 fail。
    与 ``test_state_invariants.py::test_core_resets_inconsistent_state``
    互补：那条只断言"reset 发生"，本条钉死"用户能看到诊断"。
    """
    _build_state_with_inconsistent_plan_required(monkeypatch)

    from agent.core import chat

    chat("继续")

    out = capsys.readouterr().out
    assert "检测到不一致状态" in out, (
        "L306 user-facing print 必须在无 on_runtime_event callback 时落到 stdout"
    )


def test_state_inconsistency_reset_not_double_printed_with_callback(
    monkeypatch, capsys
):
    """L306 baseline · 有 ``on_runtime_event`` callback → stdout **必须不**重复
    出现"检测到不一致状态"文本（防止未来 D slice 改成 _emit_runtime_event
    时出现 callback + stdout 双投）。

    当前代码（v0.5 d83ba78）的实际行为：L306 是裸 print，**与 callback 无关**，
    无论是否传 callback 都会落到 stdout。本测试**故意**把这个不对称钉住，
    形成"反向 baseline"：

    - 现状 = stdout 含该文本（无论 callback）→ 本断言现在会 **fail**？
      不会。本测试断言"有 callback 时不重复"，但当前即便有 callback，
      L306 仍会 print 一次（裸 print），所以 stdout 仍含该文本。
      因此本测试**当前必须 xfail 或断言"含一次"** 才正确反映现状。

    选择：用 ``count <= 1`` 的弱断言记录现状（无论是否 callback，
    最多一次 print），下一轮 D slice 把 print 迁到 ``_emit_runtime_event``
    后，本测试要升级为"callback 存在 → stdout 不含"的强断言。
    """
    _build_state_with_inconsistent_plan_required(monkeypatch)

    from agent.core import chat

    captured_events = []
    chat("继续", on_runtime_event=lambda ev: captured_events.append(ev))

    out = capsys.readouterr().out
    # 当前 v0.5 d83ba78 现状：L306 是裸 print，callback 不影响 stdout 行为。
    # 这条断言把"恰好出现一次"钉死：任何让它出现 0 次（删 print 没补 fallback）
    # 或 ≥2 次（callback 后又 print 一遍）的回归都会 fail。
    print_count = out.count("检测到不一致状态")
    assert print_count == 1, (
        f"L306 print 当前应恰好出现 1 次（裸 print，与 callback 无关），"
        f"实际 {print_count} 次；若 D slice 迁移到 _emit_runtime_event，"
        f"本断言要升级为 == 0 + 同时验证 callback 收到对应 RuntimeEvent"
    )


# ============================================================
# L670 · max_loop_iterations terminal print baseline
# ============================================================


def test_max_loop_iterations_terminal_print_visible_without_callback(
    monkeypatch, capsys
):
    """L670 baseline · 无 callback → stdout **必须**含"循环次数超过上限"。

    与 ``test_completion_handoff::test_max_loop_iterations_terminal_guard_*``
    互补：那条断言 reset_task 与终极兜底 reply，本条钉死"用户能在 stdout
    看到上限提示"——是诊断可见性的最后防线。
    """
    cleanup = _register_test_tool("loop_tool_b1", confirmation="never", result="ok")
    try:
        from tests.test_complex_scenarios import _plan_response

        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "永不收敛", "read"), ("s2", "看不到", "report")]),
                _tool_use_resp_with_arg("loop_tool_b1", "T1", "a"),
                _tool_use_resp_with_arg("loop_tool_b1", "T2", "b"),
                _tool_use_resp_with_arg("loop_tool_b1", "T3", "c"),
                _tool_use_resp_with_arg("loop_tool_b1", "T4", "d"),
            ]
        )
        _reset_core_module(monkeypatch, fake)

        from agent import core
        from agent.core import chat

        monkeypatch.setattr(core, "MAX_LOOP_ITERATIONS", 3)

        assert chat("做一个两步任务") == ""
        chat("y")

        out = capsys.readouterr().out
        assert "循环次数超过上限" in out, (
            "L670 user-facing print 必须在无 callback 时落到 stdout，"
            "否则 TUI / 远程前端用户看不到任务被强制停止的原因"
        )
    finally:
        cleanup()


def test_max_loop_iterations_print_count_pinned_with_callback(monkeypatch, capsys):
    """L670 baseline · 有 callback → stdout 含"循环次数超过上限" 恰好 1 次。

    现状：L670 是裸 print，callback 不影响该 print。本测试钉住这个事实，
    防止 D slice 迁移时出现 0 次（fallback 漏） 或 ≥2 次（双投）。
    """
    cleanup = _register_test_tool("loop_tool_b2", confirmation="never", result="ok")
    try:
        from tests.test_complex_scenarios import _plan_response

        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "永不收敛", "read"), ("s2", "看不到", "report")]),
                _tool_use_resp_with_arg("loop_tool_b2", "T1", "a"),
                _tool_use_resp_with_arg("loop_tool_b2", "T2", "b"),
                _tool_use_resp_with_arg("loop_tool_b2", "T3", "c"),
                _tool_use_resp_with_arg("loop_tool_b2", "T4", "d"),
            ]
        )
        _reset_core_module(monkeypatch, fake)

        from agent import core
        from agent.core import chat

        monkeypatch.setattr(core, "MAX_LOOP_ITERATIONS", 3)

        captured_events = []

        assert chat("做一个两步任务", on_runtime_event=lambda ev: captured_events.append(ev)) == ""
        chat("y", on_runtime_event=lambda ev: captured_events.append(ev))

        out = capsys.readouterr().out
        print_count = out.count("循环次数超过上限")
        assert print_count == 1, (
            f"L670 print 当前应恰好出现 1 次，实际 {print_count} 次；"
            f"若 D slice 把它迁到 _emit_runtime_event，本断言要升级为 == 0 + "
            f"验证 captured_events 含对应 loop.stop / max_loop_iterations RuntimeEvent"
        )
    finally:
        cleanup()


# ============================================================
# L769 · unknown stop_reason baseline
# ============================================================


def test_unknown_stop_reason_print_visible_without_callback(monkeypatch, capsys):
    """L769 baseline · 无 callback → stdout **必须**含"未知的 stop_reason"。

    与 ``test_hardcore_round2::test_unknown_stop_reason_does_not_leave_messages_broken``
    互补：那条钉死 messages 不残留 orphan tool_use，本条钉死"用户能看到协议异常诊断"。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                FakeResponse(
                    content=[FakeTextBlock(text='{"steps_estimate": 1}')],
                    stop_reason="end_turn",
                ),
                _fake_unknown_stop_response(),
            ]
        )
        _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("试试")

        out = capsys.readouterr().out
        assert "未知的 stop_reason" in out, (
            "L769 user-facing print 必须在无 callback 时落到 stdout，"
            "否则 SDK 协议漂移时诊断信息被静默吞掉"
        )
    finally:
        cleanup()


def test_unknown_stop_reason_print_count_pinned_with_callback(monkeypatch, capsys):
    """L769 baseline · 有 callback → stdout 含"未知的 stop_reason" 恰好 1 次。

    钉住现状（裸 print 与 callback 解耦），D slice 迁移时反向暴露。
    """
    cleanup = _register_test_tool("w", confirmation="never", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                FakeResponse(
                    content=[FakeTextBlock(text='{"steps_estimate": 1}')],
                    stop_reason="end_turn",
                ),
                _fake_unknown_stop_response(),
            ]
        )
        _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        captured_events = []
        chat("试试", on_runtime_event=lambda ev: captured_events.append(ev))

        out = capsys.readouterr().out
        print_count = out.count("未知的 stop_reason")
        assert print_count == 1, (
            f"L769 print 当前应恰好出现 1 次，实际 {print_count} 次；"
            f"若 D slice 迁移，本断言要升级为 == 0 + "
            f"验证 captured_events 含对应 loop.stop unknown_stop_reason RuntimeEvent"
        )
    finally:
        cleanup()


# ============================================================
# 边界守卫：本切片绝对不能改的 fallback 路径
# ============================================================


def test_assistant_delta_fallback_paths_unchanged_in_emit_runtime_event():
    """钉住 ``_emit_runtime_event`` 的 ASSISTANT_DELTA fallback 三段 print
    （L338 / L345 / L350）当前依然走 ``render_runtime_event_for_cli``，
    本切片 B 绝不能误改。

    通过 inspect.getsource 抓 ``chat`` 函数源码（``_emit_runtime_event``
    是 ``chat()`` 内闭包），断言 ``render_runtime_event_for_cli`` 仍是其
    渲染入口，且 ``_emit_runtime_event`` 闭包内 print 调用数恰好 3 次
    （覆盖 EVENT_ASSISTANT_DELTA 无 on_output_chunk fallback、
    DisplayEvent 无 on_display_event fallback、其他事件 rendered fallback）。
    """
    import inspect

    from agent import core

    src = inspect.getsource(core.chat)

    assert src.count("render_runtime_event_for_cli") >= 3, (
        "chat() 内 _emit_runtime_event 闭包必须保留 ≥3 处 render_runtime_event_for_cli 调用"
        "（ASSISTANT_DELTA fallback / DisplayEvent fallback / 其他 rendered fallback）"
    )

    # 抽出 _emit_runtime_event 闭包源码段（从 def 到下一个同缩进 def）
    closure_start = src.find("def _emit_runtime_event(")
    assert closure_start != -1, "chat() 内必须存在 _emit_runtime_event 闭包"
    next_def = src.find("\n    def ", closure_start + 1)
    closure_src = src[closure_start:next_def] if next_def != -1 else src[closure_start:]

    print_count = closure_src.count("print(")
    assert print_count == 3, (
        f"_emit_runtime_event 闭包当前应恰好有 3 处 print 调用，实际 "
        f"{print_count}；本切片 B 不允许在此闭包内增删 print"
    )


def test_debug_protocol_dump_paths_unchanged_in_core():
    """钉住 ``DEBUG_PROTOCOL`` 双重 guard（``DEBUG_PROTOCOL = False`` 模块常量
    + env ``MY_FIRST_AGENT_PROTOCOL_DUMP``）仍存在，本切片 B 绝不能误删。

    DEBUG_PROTOCOL 16 处 print 不属于 user-facing 范畴（默认关闭，开发者诊断用），
    本测试防止 D slice / 后续切片"顺手清理"把 DEBUG_PROTOCOL 当成 user-facing
    print 一并迁移。
    """
    import inspect

    from agent import core

    src = inspect.getsource(core)

    assert "DEBUG_PROTOCOL = False" in src, (
        "DEBUG_PROTOCOL 模块常量必须保留为 False（开发者手动开启时才打印）"
    )
    assert "MY_FIRST_AGENT_PROTOCOL_DUMP" in src, (
        "DEBUG_PROTOCOL 必须由 env MY_FIRST_AGENT_PROTOCOL_DUMP 控制启用"
    )

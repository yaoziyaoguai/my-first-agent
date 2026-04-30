"""core.py user-facing print → RuntimeEvent migration tests
(v0.5 Phase 1 第七小步 B 钉 baseline + 第七小步 D 完成迁移).

────────────────────────────────────────────────────────────────────
本测试模块要解决的真实风险
────────────────────────────────────────────────────────────────────
``agent/core.py`` 在 Runtime 主循环里有 3 处 user-facing 诊断输出。
v0.5 第七小步 B 钉住裸 print baseline，第七小步 D 把它们迁移到
``_emit_runtime_event`` / ``turn_state.on_runtime_event`` 统一出口：

1. L306 ``state.reset_task()`` 之前的"检测到不一致状态"
   D 后：通过 ``state_inconsistency_reset_event(status)`` 走
   ``on_runtime_event``（chat() 参数；callback 为 None 时回退 stdout）。

2. L670 ``MAX_LOOP_ITERATIONS`` 兜底"循环次数超过上限"
   D 后：通过 ``loop_max_iterations_event(limit)`` 走
   ``turn_state.on_runtime_event``（callback 为 None 时回退 stdout）。

3. L769 ``ModelOutputKind.UNKNOWN`` "未知的 stop_reason"
   D 后：通过 ``unknown_stop_reason_event(stop_reason)`` 走
   ``turn_state.on_runtime_event``（callback 为 None 时回退 stdout）。

这三处都属 ``docs/V0_5_OBSERVER_AUDIT.md §G1`` 真实 bug：
仅传 ``on_runtime_event`` 的前端（未来 TUI / IDE 插件 / 远程 shell）
下 stdout 被 sink 接管，**用户完全看不到** 这些诊断。D 切片解决方案
是按照现有 ``_emit_runtime_event`` 闭包内 ASSISTANT_DELTA fallback /
DisplayEvent fallback 同源契约——"callback 存在则不重复 stdout，
callback 缺失则 stdout fallback 保留 simple CLI 可见性"。

为什么独立 RuntimeEvent kind 而非沿用 ``EVENT_CONTROL_MESSAGE``
---------------------------------------------------------------
未来 TUI / IDE 插件需要按事件类别决定渲染样式（severity = error /
warning / info），把"状态自愈" "循环兜底" "协议未知"压到同一个
``control.message`` 会让 UI 失去分类能力。3 个新 event_type 常量定义在
``agent/display_events.py``（与现有 ``EVENT_CONTROL_MESSAGE`` 同源），
**不**在 ``agent/runtime_events.py``（那是 runtime_observer JSONL 证据
枚举 ``RuntimeEventKind``，与本组同名不同概念——见
``docs/V0_5_OBSERVER_AUDIT.md`` §G4 命名碰撞）。

测试结构
---------
- 3 条 "无 callback → stdout 必须含诊断" — 钉 simple CLI fallback
  没坏。若 D 切片误删 fallback，这 3 条立即失败。
- 3 条 "有 callback → stdout 不含诊断 + captured_events 含对应 event_type
  且 metadata 完整" — 钉 D 切片正向行为。若回归到裸 print，stdout != ""
  断言失败；若 callback 接管但 metadata 丢字段，metadata 断言失败。
- 2 条 inspect.getsource 守卫：
  * ``_emit_runtime_event`` 闭包内 ``print==3`` + ``render_runtime_event_for_cli``
    ≥3 调用（防本切片误改 ASSISTANT_DELTA fallback 三段 print）；
  * DEBUG_PROTOCOL=False 模块常量 + env MY_FIRST_AGENT_PROTOCOL_DUMP
    双重 guard（防把 DEBUG_PROTOCOL 16 处 print 当 user-facing 误删）。
- 2 条边界测试：
  * 渲染产出人类可读文本，不 dump dataclass / dict / metadata；
  * 诊断文本与 event_type 字符串不渗入 conversation.messages /
    state.task / checkpoint。

本测试不做的事
---------------
- 不改 ``agent/core.py`` 的 ASSISTANT_DELTA fallback (L338 / L345 / L350)；
- 不改 DEBUG_PROTOCOL 16 处 print；
- 不改 ``_dispatch_pending_confirmation`` / tool transition / checkpoint
  resume / final answer / request_user_input 语义；
- 不调真实 LLM、不读 ``.env`` / ``agent_log.jsonl`` / 真实 sessions；
- 不削弱已有断言、不引入 skip / xfail。

artifact 排查
--------------
若本测试在后续切片 fail：
1. ``agent/core.py`` L306 / L670 / L769 是否仍走"callback 存在 → callback；
   callback 缺失 → fallback print"双向分支；
2. ``agent/display_events.py`` 的 ``state_inconsistency_reset_event`` /
   ``loop_max_iterations_event`` / ``unknown_stop_reason_event`` 三个
   factory 是否被改签名或移除；
3. ``render_runtime_event_for_cli`` 是否仍把这三类事件按 ``event.text``
   渲染（不能误改成 dump dict）。
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


def test_state_inconsistency_reset_routed_through_callback(monkeypatch, capsys):
    """L306 D-migration · 有 ``on_runtime_event`` callback → stdout **不**出现
    "检测到不一致状态"，且 captured_events 含 ``EVENT_STATE_INCONSISTENCY_RESET``。

    这是 v0.5 第七小步 D 迁移的正向断言：
    - stdout 不重复（callback 接管，TUI / 远程前端不再丢失诊断）；
    - captured 事件 metadata 含 ``status``（被自愈前的 task.status），
      便于 UI 按 status 分类提示。

    若回归到裸 print（删迁移代码、误把 callback 路径短路），本测试失败。
    """
    from agent.display_events import EVENT_STATE_INCONSISTENCY_RESET

    _build_state_with_inconsistent_plan_required(monkeypatch)

    from agent.core import chat

    captured_events = []
    chat("继续", on_runtime_event=lambda ev: captured_events.append(ev))

    out = capsys.readouterr().out
    assert "检测到不一致状态" not in out, (
        "callback 接管后 stdout 不应再出现该诊断（避免双投）"
    )

    matched = [
        ev for ev in captured_events
        if ev.event_type == EVENT_STATE_INCONSISTENCY_RESET
    ]
    assert len(matched) == 1, (
        f"应恰好收到 1 条 EVENT_STATE_INCONSISTENCY_RESET，实际 {len(matched)}"
    )
    assert "检测到不一致状态" in matched[0].text
    assert matched[0].metadata.get("status") in {
        "awaiting_user_input", "awaiting_plan_confirmation",
        "awaiting_step_confirmation", "awaiting_tool_confirmation",
    }, "metadata.status 必须保留被自愈前的 task.status，便于 UI 分类"


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


def test_max_loop_iterations_routed_through_callback(monkeypatch, capsys):
    """L670 D-migration · 有 callback → stdout **不**含"循环次数超过上限"，
    captured_events 含 ``EVENT_LOOP_MAX_ITERATIONS`` 且 metadata.limit
    与 ``MAX_LOOP_ITERATIONS`` 一致。

    边界守护：本断言不验证 ``state.task`` 是否被 reset / checkpoint 是否
    被 clear——那由 ``test_completion_handoff::test_max_loop_iterations_*``
    钉死，本切片只关心 user-visible 诊断路径。
    """
    from agent.display_events import EVENT_LOOP_MAX_ITERATIONS

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

        assert chat(
            "做一个两步任务",
            on_runtime_event=lambda ev: captured_events.append(ev),
        ) == ""
        chat("y", on_runtime_event=lambda ev: captured_events.append(ev))

        out = capsys.readouterr().out
        assert "循环次数超过上限" not in out, "callback 接管后 stdout 不应再 print"

        matched = [
            ev for ev in captured_events
            if ev.event_type == EVENT_LOOP_MAX_ITERATIONS
        ]
        assert len(matched) == 1, (
            f"应恰好收到 1 条 EVENT_LOOP_MAX_ITERATIONS，实际 {len(matched)}"
        )
        assert matched[0].metadata.get("limit") == 3, (
            "metadata.limit 必须等于 monkeypatched MAX_LOOP_ITERATIONS"
        )
        assert "循环次数超过上限" in matched[0].text
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


def test_unknown_stop_reason_routed_through_callback(monkeypatch, capsys):
    """L769 D-migration · 有 callback → stdout **不**含"未知的 stop_reason"，
    captured_events 含 ``EVENT_UNKNOWN_STOP_REASON`` 且 metadata.stop_reason
    保留 SDK 原值（便于追踪协议漂移）。
    """
    from agent.display_events import EVENT_UNKNOWN_STOP_REASON

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
        assert "未知的 stop_reason" not in out, "callback 接管后 stdout 不应再 print"

        matched = [
            ev for ev in captured_events
            if ev.event_type == EVENT_UNKNOWN_STOP_REASON
        ]
        assert len(matched) == 1, (
            f"应恰好收到 1 条 EVENT_UNKNOWN_STOP_REASON，实际 {len(matched)}"
        )
        assert matched[0].metadata.get("stop_reason") == "stop_sequence", (
            "metadata.stop_reason 必须保留 Anthropic SDK 返回的原值"
        )
        assert "未知的 stop_reason" in matched[0].text
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


# ============================================================
# 边界测试：D 迁移引入的 3 个 RuntimeEvent kind 不能渗透到持久层
# ============================================================


def test_new_event_kinds_render_as_text_not_raw_dict():
    """3 个新 RuntimeEvent kind 经 ``render_runtime_event_for_cli`` 后
    必须是人类可读文本，不能 dump dataclass / dict 字面量。

    防回归：未来若把 RuntimeEvent 改成 ``__repr__`` 直接 dump，或在
    renderer 里误调 ``str(event)``，本断言立即失败。
    """
    from agent.display_events import (
        loop_max_iterations_event,
        render_runtime_event_for_cli,
        state_inconsistency_reset_event,
        unknown_stop_reason_event,
    )

    for evt, must_contain in [
        (state_inconsistency_reset_event("awaiting_user_input"), "检测到不一致状态"),
        (loop_max_iterations_event(50), "循环次数超过上限"),
        (unknown_stop_reason_event("stop_sequence"), "未知的 stop_reason"),
    ]:
        rendered = render_runtime_event_for_cli(evt)
        assert must_contain in rendered, (
            f"{evt.event_type} 渲染应含 {must_contain!r}，实际 {rendered!r}"
        )
        assert "RuntimeEvent(" not in rendered, "渲染不能 dump dataclass repr"
        assert "{'event_type'" not in rendered, "渲染不能 dump dict 字面量"
        # 不能泄漏 metadata 字典字面量；元数据应通过结构化 callback 消费
        assert "metadata" not in rendered.lower(), "渲染不应暴露 metadata 字段名"


def test_new_event_kinds_do_not_enter_messages_or_checkpoint(monkeypatch):
    """L306 自愈路径触发后，``state.conversation.messages`` 与 ``state.task``
    都不应出现 ``EVENT_STATE_INCONSISTENCY_RESET`` 文本或 event_type 字符串。

    边界守护：RuntimeEvent 是 UI projection，不能渗入持久 messages / checkpoint。
    若未来有人误把 ``state.conversation.messages.append({"role": "system",
    "content": render_runtime_event_for_cli(evt)})``，本测试会暴露。
    """
    from agent.display_events import EVENT_STATE_INCONSISTENCY_RESET

    state = _build_state_with_inconsistent_plan_required(monkeypatch)

    from agent.core import chat

    captured_events = []
    chat("继续", on_runtime_event=lambda ev: captured_events.append(ev))

    matched = [ev for ev in captured_events if ev.event_type == EVENT_STATE_INCONSISTENCY_RESET]
    assert len(matched) == 1, "前置：必须收到事件，否则本测试无法验证不渗透"

    msg_dump = repr(state.conversation.messages)
    assert "检测到不一致状态" not in msg_dump, (
        "诊断文本不能渗入 conversation.messages（会污染 Anthropic API 上下文）"
    )
    assert EVENT_STATE_INCONSISTENCY_RESET not in msg_dump, (
        "RuntimeEvent event_type 不能进入 messages"
    )

    task_dump = repr(state.task)
    assert "检测到不一致状态" not in task_dump, "诊断文本不能渗入 state.task"
    assert EVENT_STATE_INCONSISTENCY_RESET not in task_dump, (
        "RuntimeEvent event_type 不能进入 state.task / checkpoint"
    )

"""v0.2 M7-A：CLI 输出文案区分性回归测试。

本文件守护「执行成功 / 工具失败 / 工具内部安全检查拒绝 / policy denial /
用户拒绝」五类结局在 tool_execution_log status、display_event 类型和
status_text 三个维度都能被外层（UI / 审计 / 模型 system 提示）区分。

历史背景（M7-A 真实修复）：
旧版 tool_executor 只看 TOOL_FAILURE_PREFIXES 区分 failed / executed；
但工具的 pre/post hook（如 pre_write_check、check_shell_blacklist、
_check_dangerous_content）拒绝时返回字符串都是「拒绝执行：...」，
没有任何前缀命中 TOOL_FAILURE_PREFIXES，结果会被当成「executed」+
「执行完成。」展示给用户，并写入 status='executed' 的 tool_execution_log，
让审计、模型重试提示和用户体验三方一起出错。
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def _stub_state(monkeypatch):
    """构造极简 state / turn_state，禁用 save_checkpoint 落盘 +
    强制 needs_tool_confirmation 返回 False，让 execute_single_tool 走直接执行路径。"""

    import agent.tool_executor as te

    monkeypatch.setattr(te, "save_checkpoint", lambda s: None)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)

    class _TaskState:
        def __init__(self):
            self.tool_execution_log = {}
            self.current_step_index = 0
            self.pending_tool = None
            self.pending_user_input_request = None
            self.status = "running"

    class _State:
        def __init__(self):
            self.task = _TaskState()

    captured: list[Any] = []

    class _TurnState:
        round_tool_traces: list[Any] = []
        on_runtime_event = None

        @staticmethod
        def on_display_event(ev):
            captured.append(ev)

    return _State(), _TurnState(), captured


def test_classify_tool_outcome_distinguishes_three_classes():
    """_classify_tool_outcome 必须返回稳定的 (status, event_type, status_text)。"""
    from agent.tool_executor import _classify_tool_outcome

    s, et, st = _classify_tool_outcome("拒绝执行：路径在项目目录之外。")
    assert s == "rejected_by_check"
    assert et == "tool.rejected"
    assert "拒绝" in st

    s, et, st = _classify_tool_outcome("错误：文件不存在")
    assert s == "failed"
    assert et == "tool.failed"
    assert "失败" in st

    s, et, st = _classify_tool_outcome("42")
    assert s == "executed"
    assert et == "tool.completed"
    assert "完成" in st


def test_pre_write_check_rejection_is_not_displayed_as_completed(_stub_state, monkeypatch):
    """工具内部 pre_write_check 拒绝（项目外写）→ 必须显示 tool.rejected，
    不能再次出现「执行完成。」否则用户/审计/模型都会混淆。"""
    import agent.tool_executor as te

    state, turn_state, captured = _stub_state

    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "拒绝执行：'~/danger.txt' 在项目目录之外，已阻止写入。",
    )

    class _ToolUse:
        id = "toolu_reject_1"
        name = "write_file"
        input = {"path": "~/danger.txt", "content": "x"}

    out = te.execute_single_tool(
        _ToolUse(),
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=[],
    )

    assert out is None
    entry = state.task.tool_execution_log["toolu_reject_1"]
    assert entry["status"] == "rejected_by_check", (
        f"pre_write_check 拒绝应记 status='rejected_by_check'，实际 {entry['status']!r}"
    )
    assert "拒绝执行：" in entry["result"]
    assert "[系统提示] 该工具调用没有获得可用结果" in entry["result"], (
        "rejected 也应附「不要重复同一调用」的系统提示，与 failed 行为一致"
    )

    completion_events = [e for e in captured if e.event_type == "tool.completed"]
    rejection_events = [e for e in captured if e.event_type == "tool.rejected"]
    assert not completion_events, "pre-check 拒绝绝不能 emit tool.completed"
    assert len(rejection_events) == 1
    assert "完成" not in rejection_events[0].body
    assert "拒绝" in rejection_events[0].body


def test_genuine_tool_failure_still_uses_tool_failed_event(_stub_state, monkeypatch):
    """工具运行报错（如 read_file 文件不存在）仍走 tool.failed，与 rejected 区分。"""
    import agent.tool_executor as te

    state, turn_state, captured = _stub_state

    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "错误：文件不存在 /tmp/nope",
    )

    class _ToolUse:
        id = "toolu_fail_1"
        name = "read_file"
        input = {"path": "/tmp/nope"}

    te.execute_single_tool(
        _ToolUse(),
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=[],
    )

    entry = state.task.tool_execution_log["toolu_fail_1"]
    assert entry["status"] == "failed"
    assert any(e.event_type == "tool.failed" for e in captured)
    assert not any(e.event_type == "tool.rejected" for e in captured)
    assert not any(e.event_type == "tool.completed" for e in captured)


def test_genuine_success_uses_tool_completed_event(_stub_state, monkeypatch):
    """正常返回值 → status='executed' + tool.completed，UI 不能误报 failed/rejected。"""
    import agent.tool_executor as te

    state, turn_state, captured = _stub_state

    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "42",
    )

    class _ToolUse:
        id = "toolu_ok_1"
        name = "calculate"
        input = {"expression": "21 + 21"}

    te.execute_single_tool(
        _ToolUse(),
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=[],
    )

    entry = state.task.tool_execution_log["toolu_ok_1"]
    assert entry["status"] == "executed"
    assert entry["result"] == "42"
    assert any(e.event_type == "tool.completed" for e in captured)
    assert not any(e.event_type in {"tool.failed", "tool.rejected"} for e in captured)


def test_post_confirm_pending_tool_rejection_does_not_say_completed(monkeypatch):
    """用户已确认后再被工具内部安全检查拒绝时，必须 emit tool.rejected
    而不是 tool.completed，避免「已收到确认，开始执行 → 执行完成」与
    实际「拒绝执行：...」字符串错配的体验。"""
    import agent.tool_executor as te

    monkeypatch.setattr(te, "save_checkpoint", lambda s: None)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "拒绝执行：写入内容包含敏感密钥头。",
    )

    class _TaskState:
        tool_execution_log: dict[str, Any] = {}
        current_step_index = 0

    class _State:
        task = _TaskState()

    captured: list[Any] = []

    class _TurnState:
        round_tool_traces: list[Any] = []

        @staticmethod
        def on_display_event(ev):
            captured.append(ev)

    msgs: list[Any] = []
    pending = {
        "tool_use_id": "toolu_pending_reject",
        "tool": "write_file",
        "input": {"path": "workspace/leak.txt", "content": "BEGIN PRIVATE KEY"},
    }

    result = te.execute_pending_tool(
        state=_State(),
        turn_state=_TurnState(),
        messages=msgs,
        pending=pending,
    )

    assert "拒绝执行：" in result
    rejected = [e for e in captured if e.event_type == "tool.rejected"]
    completed = [e for e in captured if e.event_type == "tool.completed"]
    executing = [e for e in captured if e.event_type == "tool.executing"]
    assert rejected, "post-confirm 拒绝必须 emit tool.rejected"
    assert not completed, "post-confirm 拒绝不能 emit tool.completed"
    assert executing and "已收到确认" in executing[0].body, (
        "执行中提示应改为「已收到确认，开始执行」，避免与后续 reject 文案冲突"
    )


def test_runtime_event_type_for_rejected_matches_completed_visibility():
    """tool.rejected 在 runtime_display_event 中应被映射成 EVENT_TOOL_RESULT_VISIBLE，
    与 completed/failed 同列，让 UI/observer 都能看到「这是一次工具结果」。"""
    from agent.display_events import (
        EVENT_TOOL_RESULT_VISIBLE,
        DisplayEvent,
        runtime_display_event,
    )

    ev = DisplayEvent(event_type="tool.rejected", title="工具执行状态", body="...")
    runtime_event = runtime_display_event(ev)
    assert runtime_event.event_type == EVENT_TOOL_RESULT_VISIBLE
    assert runtime_event.metadata["display_event_type"] == "tool.rejected"


def test_rejected_status_value_is_distinct_string():
    """rejected_by_check 不能与 blocked_by_policy / failed / executed 重名，
    审计层用 status 字段做集合分类时才能正确分桶。"""
    from agent.tool_executor import _classify_tool_outcome

    statuses = {
        _classify_tool_outcome("拒绝执行：x")[0],
        _classify_tool_outcome("错误：x")[0],
        _classify_tool_outcome("ok")[0],
    }
    assert statuses == {"rejected_by_check", "failed", "executed"}
    # blocked_by_policy 来自 confirmation == "block" 路径，由 execute_single_tool
    # 写入；与本函数无关，但需要保持互不重叠的命名空间。
    assert "blocked_by_policy" not in statuses


# ===================== M7-C: checkpoint resume 可见性 =====================

def test_idle_checkpoint_with_no_messages_is_not_actionable():
    """status='idle' + 0 条消息 + 无 pending → 视作历史残留，不该 prompt。

    真实 smoke 发现：旧实现只要 checkpoint 文件存在就显示
    「📌 发现未完成的任务：（未命名任务） 已有 0 条对话历史」并要求 y/n，
    用户既得不到任何信息，又被强迫做选择。M7-C 修复后这种残留 checkpoint
    应该被静默清理。
    """
    from agent.session import _checkpoint_has_actionable_resume

    task = {
        "status": "idle",
        "current_step_index": 0,
        "pending_tool": None,
        "pending_user_input_request": None,
        "current_plan": None,
    }
    conv = {"messages": []}
    assert _checkpoint_has_actionable_resume(task, conv) is False


def test_pending_tool_checkpoint_is_actionable():
    """awaiting_tool_confirmation + pending_tool → 必须 prompt 让用户决定。"""
    from agent.session import _checkpoint_has_actionable_resume

    task = {
        "status": "awaiting_tool_confirmation",
        "pending_tool": {"tool_use_id": "x", "tool": "write_file", "input": {}},
    }
    assert _checkpoint_has_actionable_resume(task, {"messages": []}) is True


def test_awaiting_user_input_checkpoint_is_actionable():
    from agent.session import _checkpoint_has_actionable_resume

    task = {
        "status": "awaiting_user_input",
        "pending_user_input_request": {"question": "?"},
    }
    assert _checkpoint_has_actionable_resume(task, {"messages": []}) is True


def test_in_progress_plan_checkpoint_is_actionable():
    from agent.session import _checkpoint_has_actionable_resume

    task = {
        "status": "running",
        "current_plan": {"steps": [{"action": "x"}]},
        "current_step_index": 1,
    }
    assert _checkpoint_has_actionable_resume(task, {"messages": [{"role": "user", "content": "x"}]}) is True


def test_non_idle_with_messages_is_actionable():
    """有真实对话历史 + 非 idle 状态：上一轮没收尾，应让用户决定。"""
    from agent.session import _checkpoint_has_actionable_resume

    task = {"status": "running"}
    conv = {"messages": [{"role": "user", "content": "hi"}]}
    assert _checkpoint_has_actionable_resume(task, conv) is True


# ===================== M7-B: 四类输出区分（policy / user / pre-check / fail / success） =====================

def test_policy_denial_emits_tool_rejected_with_specific_reason(monkeypatch):
    """confirmation == 'block'（如 read_file ~/.env / .pem）必须 emit
    tool.rejected 且 status_text 含具体拒绝原因，绝不能 emit tool.completed。

    真实 main.py smoke 发现旧版 block 分支不 emit 任何 display event，
    用户只看到下游 FORCE_STOP 的「具体拒绝原因见上方工具消息」，但「上方」
    其实空无一物。"""
    import agent.tools  # noqa: F401  ensure TOOL_REGISTRY populated
    import agent.tool_executor as te

    monkeypatch.setattr(te, "save_checkpoint", lambda s: None)

    class _ToolUse:
        id = "toolu_block_1"
        name = "read_file"
        input = {"path": "/tmp/server.pem"}

    class _TaskState:
        def __init__(self):
            self.tool_execution_log = {}
            self.current_step_index = 0
            self.pending_tool = None
            self.pending_user_input_request = None
            self.status = "running"

    class _State:
        def __init__(self):
            self.task = _TaskState()

    captured: list[Any] = []

    class _TurnState:
        round_tool_traces: list[Any] = []
        on_runtime_event = None

        @staticmethod
        def on_display_event(ev):
            captured.append(ev)

    out = te.execute_single_tool(
        _ToolUse(),
        state=_State(),
        turn_state=_TurnState(),
        turn_context={},
        messages=[],
    )

    assert out == te.FORCE_STOP
    rejection_events = [e for e in captured if e.event_type == "tool.rejected"]
    completed_events = [e for e in captured if e.event_type == "tool.completed"]
    assert not completed_events, "policy denial 绝不能 emit tool.completed"
    assert len(rejection_events) == 1, "policy denial 必须 emit 1 条 tool.rejected"
    body = rejection_events[0].body
    assert "被安全策略拒绝" in body
    assert ".pem" in body or "敏感配置" in body, (
        "status_text 必须包含具体原因，不能只说「被拒绝」"
    )
    assert "用户" not in body, "policy denial 文案不能误用「用户」"


def test_policy_denial_does_not_leak_file_contents_in_display_event(monkeypatch, tmp_path):
    """display event 的 body 来源于 _describe_policy_denial，
    后者只读路径名/扩展名，绝不读取被拒文件内容。"""
    import agent.tools  # noqa: F401
    import agent.tool_executor as te

    secret = tmp_path / "secret.pem"
    secret.write_text("BEGIN PRIVATE KEY\nSUPER_SECRET_VALUE\nEND PRIVATE KEY")
    monkeypatch.setattr(te, "save_checkpoint", lambda s: None)

    class _ToolUse:
        id = "toolu_pem"
        name = "read_file"
        input = {"path": str(secret)}

    class _TaskState:
        def __init__(self):
            self.tool_execution_log = {}
            self.current_step_index = 0

    class _State:
        def __init__(self):
            self.task = _TaskState()

    captured: list[Any] = []

    class _TurnState:
        round_tool_traces: list[Any] = []
        on_runtime_event = None

        @staticmethod
        def on_display_event(ev):
            captured.append(ev)

    te.execute_single_tool(
        _ToolUse(),
        state=_State(),
        turn_state=_TurnState(),
        turn_context={},
        messages=[],
    )

    rejection = next(e for e in captured if e.event_type == "tool.rejected")
    assert "SUPER_SECRET_VALUE" not in rejection.body
    assert "BEGIN PRIVATE KEY" not in rejection.body
    assert "PRIVATE" not in rejection.body or ".pem" in rejection.body, (
        "display 文案最多提到扩展名 .pem，绝不能含文件内容"
    )


def test_user_rejection_emits_user_rejected_event_with_distinct_text(monkeypatch):
    """用户输入 n 拒绝工具调用时必须 emit tool.user_rejected，
    与 tool.rejected（安全检查）/tool.failed（运行报错）区分语义，
    避免 CLI 用户「按了 n 之后什么都没看到」的体验。"""
    import agent.confirm_handlers as ch
    from agent.confirm_handlers import handle_tool_confirmation, ConfirmationContext
    from agent.conversation_events import has_tool_result

    monkeypatch.setattr(ch, "save_checkpoint", lambda s: None)

    class _TaskState:
        def __init__(self):
            self.pending_tool = {
                "tool_use_id": "toolu_user_rej",
                "tool": "write_file",
                "input": {"path": "workspace/x.txt", "content": "y"},
            }
            self.status = "awaiting_tool_confirmation"
            self.tool_execution_log = {}
            self.current_step_index = 0

    class _ConvState:
        def __init__(self):
            self.messages = [
                {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_user_rej", "name": "write_file", "input": {}}]},
            ]

    class _State:
        def __init__(self):
            self.task = _TaskState()
            self.conversation = _ConvState()
            self.memory = type("_M", (), {"profile": {}, "rules": [], "episodes": []})()
            self.meta = type("_Meta", (), {"started_at": 0, "session_id": "t"})()

    captured: list[Any] = []

    class _TurnState:
        round_tool_traces: list[Any] = []
        on_runtime_event = None

        @staticmethod
        def on_display_event(ev):
            captured.append(ev)

    state = _State()
    ctx = ConfirmationContext(
        state=state,
        turn_state=_TurnState(),
        client=None,
        model_name="test-model",
        continue_fn=lambda ts: "continued",
    )

    handle_tool_confirmation("n", ctx)

    user_rej = [e for e in captured if e.event_type == "tool.user_rejected"]
    assert user_rej, "用户拒绝必须 emit tool.user_rejected"
    body = user_rej[0].body
    assert "用户拒绝" in body
    assert "安全策略" not in body
    # 占位 tool_result 仍按既有约定写入 messages
    assert has_tool_result(state.conversation.messages, "toolu_user_rej")


def test_runtime_event_type_for_user_rejected_is_visible():
    """tool.user_rejected 也应映射到 EVENT_TOOL_RESULT_VISIBLE，
    与 completed/failed/rejected 同列。"""
    from agent.display_events import (
        EVENT_TOOL_RESULT_VISIBLE,
        DisplayEvent,
        runtime_display_event,
    )

    ev = DisplayEvent(event_type="tool.user_rejected", title="工具执行状态", body="用户拒绝执行。")
    re = runtime_display_event(ev)
    assert re.event_type == EVENT_TOOL_RESULT_VISIBLE
    assert re.metadata["display_event_type"] == "tool.user_rejected"


def test_four_categories_have_distinct_status_text_strings():
    """四类结局的 status_text 在 CLI 上必须可被肉眼区分（首关键词不同）。"""
    from agent.tool_executor import _classify_tool_outcome

    success_text = _classify_tool_outcome("ok")[2]
    failed_text = _classify_tool_outcome("错误：x")[2]
    rejected_text = _classify_tool_outcome("拒绝执行：x")[2]

    keywords = {
        "success": success_text,         # 「执行完成。」
        "failed": failed_text,           # 「执行失败。」
        "pre_check_rejected": rejected_text,  # 「已被工具内部安全检查拒绝。」
    }
    # 三类都不能含「用户」；用户拒绝走 confirm_handlers 的 tool.user_rejected
    for k, v in keywords.items():
        assert "用户" not in v, f"{k} 文案不能含「用户」: {v!r}"
    # 三类首关键字不同
    assert success_text != failed_text != rejected_text
    assert "完成" in success_text and "失败" in failed_text and "拒绝" in rejected_text

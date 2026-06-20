"""S4-G04 pending-tool event fidelity 测试（TD-004 / AC-4）。

验证 pending tool 确认执行后，TOOL_RESULT dispatch 的 ``tool_output`` 预览**非空**且包含
执行结果（与 execute_single_tool 非 pending 路径 parity）。

根因（TD-004）：``mediate_pending`` Step 4 读 ``self._turn_context.get(tool_use_id, "")``
构造预览，但 ``execute_pending_tool`` 从不写 ``turn_context[tool_use_id]``（非 pending 的
``execute_single_tool`` 在 tool_executor.py:543 写），导致预览恒为空。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import agent.tool_runtime_mediator as tmr_mod
from agent.runtime_integration.schema import RuntimeActionType


def _make_mediator_with_pending(pending: dict) -> tuple:
    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.tool_execution_log = {}
    state.task.current_step_index = 1
    turn_state = SimpleNamespace()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None
    fake_dispatcher = MagicMock()
    mediator = tmr_mod.ToolRuntimeMediator(
        fake_dispatcher,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=[],
    )
    return mediator, fake_dispatcher, pending


def _tool_result_payload(fake_dispatcher, tool_use_id: str) -> dict:
    """从 dispatcher 捕获的调用中找到该 tool_use_id 的 TOOL_RESULT payload。"""
    result_payloads = []
    for call in fake_dispatcher.route_from_runtime_loop.call_args_list:
        req = call[0][0]
        if req.action_type == RuntimeActionType.TOOL_RESULT and req.parent_trace_id == tool_use_id:
            result_payloads.append(req.payload)
    assert result_payloads, f"未捕获 tool_use_id={tool_use_id} 的 TOOL_RESULT dispatch"
    return result_payloads[-1]


def test_mediate_pending_tool_output_preview_is_nonempty():
    """TD-004 核心：pending tool 执行后 tool_output 预览非空且含结果。"""
    pending = {
        "tool_use_id": "toolu_td004_ok",
        "tool": "write_file",
        "input": {"path": "t.txt", "content": "hi"},
    }
    mediator, fake_dispatcher, _ = _make_mediator_with_pending(pending)
    known_result = "执行完成：写入 2 行。"

    with patch.object(tmr_mod, "execute_pending_tool", return_value=known_result):
        mediator.mediate_pending(pending)

    payload = _tool_result_payload(fake_dispatcher, "toolu_td004_ok")
    assert payload["tool_output"], "tool_output 预览不得为空（TD-004）"
    assert known_result in payload["tool_output"]
    assert payload["from_pending_tool"] is True


def test_mediate_pending_preview_truncated_to_safe_length():
    """pending tool 预览应截断到 safe 长度（与非 pending _route_result 的 [:500] parity）。"""
    pending = {
        "tool_use_id": "toolu_td004_long",
        "tool": "read_file",
        "input": {"path": "big.txt"},
    }
    mediator, fake_dispatcher, _ = _make_mediator_with_pending(pending)
    long_result = "X" * 2000

    with patch.object(tmr_mod, "execute_pending_tool", return_value=long_result):
        mediator.mediate_pending(pending)

    payload = _tool_result_payload(fake_dispatcher, "toolu_td004_long")
    assert payload["tool_output"], "预览不得为空"
    assert len(payload["tool_output"]) <= 500, "预览应截断到 <=500（safe-summary）"
    assert long_result not in payload["tool_output"]


def test_mediate_pending_empty_result_does_not_crash():
    """空结果（falsy）也不应 crash；预览允许为空字符串但流程必须完成。"""
    pending = {
        "tool_use_id": "toolu_td004_empty",
        "tool": "write_file",
        "input": {"path": "t.txt"},
    }
    mediator, fake_dispatcher, _ = _make_mediator_with_pending(pending)

    with patch.object(tmr_mod, "execute_pending_tool", return_value=""):
        result = mediator.mediate_pending(pending)

    assert result == ""
    # 流程仍应发出 TOOL_RESULT dispatch（不因空结果中断）
    payload = _tool_result_payload(fake_dispatcher, "toolu_td004_empty")
    assert "tool_output" in payload


def test_mediate_pending_failure_status_propagated_to_dispatch():
    """AC-4 fidelity：失败的 pending tool 不得报告 executed/success（whole-stage audit HIGH）。

    修复前 mediate_pending 硬编码 status='executed'/execution_status='success'，无论底层
    execute_pending_tool 是否失败/被拒——破坏 S4 审计轨迹保真。execute_pending_tool 已把真实
    envelope.status 写入 tool_execution_log[tool_use_id]['status']；修复后 mediate_pending 从
    该处取真实状态，使 failed/rejected_by_check → status='failed'/'rejected_by_check'、
    execution_status='error'。

    本测试模拟真实 execute_pending_tool 在失败时写入的 tool_execution_log（patch 掉执行器本身，
    只验证 mediate_pending 的状态推导）。
    """
    pending = {
        "tool_use_id": "toolu_pending_fail_status",
        "tool": "shell_command",
        "input": {"cmd": "rm -rf /"},
    }
    mediator, fake_dispatcher, _ = _make_mediator_with_pending(pending)
    # 模拟真实 execute_pending_tool 在 rejected_by_check 时写入的状态
    mediator._state.task.tool_execution_log["toolu_pending_fail_status"] = {
        "tool": "shell_command",
        "status": "rejected_by_check",
        "input": pending["input"],
        "result": "拒绝执行：路径不在白名单",
        "step_index": 1,
    }

    with patch.object(
        tmr_mod, "execute_pending_tool", return_value="拒绝执行：路径不在白名单"
    ):
        mediator.mediate_pending(pending)

    payload = _tool_result_payload(fake_dispatcher, "toolu_pending_fail_status")
    assert payload["status"] != "executed", "失败的 pending tool 不得报告 status=executed"
    assert payload["execution_status"] == "error", (
        "失败的 pending tool 须报告 execution_status=error"
    )


def test_mediate_pending_success_status_remains_executed():
    """成功（executed）的 pending tool 仍报告 executed/success——修复不得破坏成功路径。"""
    pending = {
        "tool_use_id": "toolu_pending_ok_status",
        "tool": "write_file",
        "input": {"path": "t.txt"},
    }
    mediator, fake_dispatcher, _ = _make_mediator_with_pending(pending)
    mediator._state.task.tool_execution_log["toolu_pending_ok_status"] = {
        "tool": "write_file",
        "status": "executed",
        "input": pending["input"],
        "result": "ok",
        "step_index": 1,
    }

    with patch.object(tmr_mod, "execute_pending_tool", return_value="ok"):
        mediator.mediate_pending(pending)

    payload = _tool_result_payload(fake_dispatcher, "toolu_pending_ok_status")
    assert payload["status"] == "executed"
    assert payload["execution_status"] == "success"

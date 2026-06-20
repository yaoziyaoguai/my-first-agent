"""FINAL-G03 (TD-012) 测试：把 S4 redaction 接入 legacy mediator TOOL_RESULT 预览
与 ``record_evidence`` metadata。

锁定 AC-7 的 legacy 投影面：合成 secret 经工具结果 / evidence metadata 进入时，
``tool_output`` 预览与 ``record_evidence`` metadata 都不得保留 raw secret。

这些测试在 redaction 接入前必须失败（RED）—— 当前 mediator 用 ``str(...)[:500]``
不脱敏、record_evidence metadata 用 ``_summarize_metadata_value`` 不脱敏。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import agent.tool_runtime_mediator as tmr_mod
from agent.evidence_recorder import record_evidence
from agent.runtime_integration.schema import RuntimeActionType

_SECRET = "sk-leaksurvives123456"


def _make_mediator():
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
    return mediator, fake_dispatcher


def _tool_result_payload(fake_dispatcher, tool_use_id: str) -> dict:
    payloads = []
    for call in fake_dispatcher.route_from_runtime_loop.call_args_list:
        req = call[0][0]
        if (
            req.action_type == RuntimeActionType.TOOL_RESULT
            and req.parent_trace_id == tool_use_id
        ):
            payloads.append(req.payload)
    assert payloads, f"未捕获 tool_use_id={tool_use_id} 的 TOOL_RESULT dispatch"
    return payloads[-1]


def test_record_evidence_metadata_redacts_secret():
    envelope = record_evidence(
        subsystem="tool",
        operation="invoke",
        metadata={"note": f"preview token={_SECRET}"},
    )
    blob = str(envelope["metadata"])
    assert _SECRET not in blob
    assert "[REDACTED]" in blob


def test_mediate_pending_tool_output_redacts_secret():
    mediator, fake_dispatcher = _make_mediator()
    pending = {
        "tool_use_id": "toolu_secret_pending",
        "tool": "write_file",
        "input": {"path": "t.txt", "content": "x"},
    }
    secret_result = f"执行完成；token={_SECRET}"
    with patch.object(tmr_mod, "execute_pending_tool", return_value=secret_result):
        mediator.mediate_pending(pending)
    payload = _tool_result_payload(fake_dispatcher, "toolu_secret_pending")
    assert _SECRET not in payload["tool_output"]
    assert "[REDACTED]" in payload["tool_output"]


def test_route_result_tool_output_redacts_secret():
    mediator, fake_dispatcher = _make_mediator()
    tool_use_id = "toolu_secret_route"
    mediator._turn_context[tool_use_id] = f"result；token={_SECRET}"
    mediator._route_result("read_file", {"path": "x"}, tool_use_id, None)
    payload = _tool_result_payload(fake_dispatcher, tool_use_id)
    assert _SECRET not in payload["tool_output"]
    assert "[REDACTED]" in payload["tool_output"]

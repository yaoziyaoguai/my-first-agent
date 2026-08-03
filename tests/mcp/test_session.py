from __future__ import annotations

import sys
from pathlib import Path

from agent.mcp.bridge import (
    McpAsyncBridge,
    SessionTimeouts,
    run_stdio_session,
)
from agent.mcp.contracts import McpOutcomeClassification
from agent.mcp.safety import LatchBinding, McpSafetyLatch

SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp" / "stdio_server.py"
ECHO_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def _latch(tmp_path: Path) -> McpSafetyLatch:
    directory = tmp_path / "safety"
    directory.mkdir(mode=0o700)
    return McpSafetyLatch(directory / "latch.json")


def _binding(intent: str = "intent-1") -> LatchBinding:
    return LatchBinding(
        server_id="repo",
        config_digest="config-digest",
        credential_profile=None,
        safety_generation="gen-1",
        intent_digest=intent,
    )


def _run(bridge, tmp_path, *, remote, args, schema, intent="intent-1"):
    latch = _latch(tmp_path)
    outcome = bridge.submit(
        lambda: run_stdio_session(
            command=sys.executable,
            args=(str(SERVER),),
            cwd=None,
            env={},
            remote_name=remote,
            arguments=args,
            input_schema=schema,
            descriptor_digest="descriptor-digest",
            latch=latch,
            binding=_binding(intent),
            expected_clear_revision=0,
            timeouts=SessionTimeouts(initialize=10, list_page=10, call=10, shutdown=5),
        )
    )
    return outcome, latch


def test_feasibility_echo_round_trip(tmp_path: Path) -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=40)
    try:
        outcome, latch = _run(
            bridge, tmp_path, remote="echo", args={"text": "hello mcp"}, schema=ECHO_SCHEMA
        )
    finally:
        bridge.close()

    assert outcome.classification is McpOutcomeClassification.EXECUTED
    assert outcome.result_text == "hello mcp"
    assert outcome.call_may_have_been_sent is True
    assert outcome.terminal_response_received is True
    # 进程确认退出后 latch 清除。
    assert latch.status() == "clear"


def test_broken_tool_returns_executed_error(tmp_path: Path) -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=40)
    try:
        outcome, _latch_state = _run(
            bridge,
            tmp_path,
            remote="broken",
            args={},
            schema={"type": "object", "properties": {}},
        )
    finally:
        bridge.close()

    # 远端明确返回业务错误（isError）= 已执行，允许模型修正，不进 recovery。
    assert outcome.classification is McpOutcomeClassification.EXECUTED
    assert outcome.call_may_have_been_sent is True


def test_descriptor_drift_returns_not_executed(tmp_path: Path) -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=40)
    try:
        outcome, _latch_state = _run(
            bridge,
            tmp_path,
            remote="echo",
            args={"text": 5},
            schema={"type": "object", "properties": {"text": {"type": "integer"}}},
        )
    finally:
        bridge.close()

    assert outcome.classification is McpOutcomeClassification.NOT_EXECUTED
    assert outcome.error_code == "descriptor_drift"


def test_missing_tool_returns_not_executed(tmp_path: Path) -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=40)
    try:
        outcome, _latch_state = _run(
            bridge,
            tmp_path,
            remote="does_not_exist",
            args={},
            schema={"type": "object"},
        )
    finally:
        bridge.close()

    assert outcome.classification is McpOutcomeClassification.NOT_EXECUTED
    assert outcome.error_code == "descriptor_missing"


def test_invalid_arguments_fail_before_call(tmp_path: Path) -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=40)
    try:
        outcome, _latch_state = _run(
            bridge,
            tmp_path,
            remote="echo",
            args={},  # missing required "text"
            schema=ECHO_SCHEMA,
        )
    finally:
        bridge.close()

    assert outcome.classification is McpOutcomeClassification.NOT_EXECUTED
    assert outcome.error_code == "invalid_arguments"

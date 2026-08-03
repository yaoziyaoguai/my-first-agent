from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent.mcp.bridge import McpAsyncBridge, SessionTimeouts
from agent.mcp.catalog import build_mcp_catalog
from agent.mcp.contracts import McpBridgeOutcome, McpOutcomeClassification
from agent.mcp.safety import McpSafetyLatch
from agent.mcp.tools import (
    McpExecutorConfig,
    McpUnknownOutcomeError,
    build_mcp_tool_registrations,
)
from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalRequired,
    ExecutionIntent,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
)
from agent.runtime.tools import KernelToolRuntime

SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp" / "stdio_server.py"
ECHO_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def _catalog(tmp_path: Path):
    import shlex

    wrapper = tmp_path / "run_server.sh"
    wrapper.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(SERVER))}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    return build_mcp_catalog(_config(str(wrapper))), wrapper


def _config(exe: str) -> dict:
    return {
        "servers": [
            {
                "server_id": "repo",
                "transport": "stdio",
                "command": exe,
                "args": [],
                "safety_generation": "gen-1",
                "protocol_revision": "2025-11-25",
                "credential_profile": "ops-profile",
                "tools": [
                    {
                        "remote_name": "echo",
                        "description": "Echo text back.",
                        "input_schema": ECHO_SCHEMA,
                        "output_limit_chars": 1000,
                    }
                ],
            }
        ]
    }


def _ctx() -> ToolPrepareContext:
    return ToolPrepareContext("conversation-1", "run-1", 1)


class _StubBridge:
    def __init__(self, outcome: McpBridgeOutcome) -> None:
        self.outcome = outcome
        self.quarantined = False

    def submit(self, factory):  # noqa: ARG002
        return self.outcome

    def quarantine(self, *, reason: str = "") -> None:  # noqa: ARG002
        self.quarantined = True


def _registrations_with_stub(tmp_path: Path, outcome: McpBridgeOutcome):
    catalog, _exe = _catalog(tmp_path)
    directory = tmp_path / "safety"
    directory.mkdir(mode=0o700, exist_ok=True)
    latch = McpSafetyLatch(directory / "latch.json")
    stub = _StubBridge(outcome)
    config = McpExecutorConfig(
        bridge=stub,
        latch=latch,
        composition_epoch="epoch-1",
        timeouts=SessionTimeouts(),
        env_provider=lambda names: {},  # noqa: ARG005
    )
    return build_mcp_tool_registrations(catalog, executor_config=config), stub


def _approved_intent(runtime, call):
    prepared = runtime.prepare(call, _ctx())
    assert isinstance(prepared, ApprovalRequired)
    return runtime.prepare(
        call,
        _ctx(),
        approval=ApprovalGrant(prepared.request.request_id, prepared.request.binding_digest),
    )


def test_spec_binds_identity_and_preview(tmp_path: Path) -> None:
    catalog, _exe = _catalog(tmp_path)
    directory = tmp_path / "safety"
    directory.mkdir(mode=0o700, exist_ok=True)
    config = McpExecutorConfig(
        bridge=_StubBridge(McpBridgeOutcome(classification=McpOutcomeClassification.EXECUTED)),
        latch=McpSafetyLatch(directory / "latch.json"),
        composition_epoch="epoch-1",
        timeouts=SessionTimeouts(),
        env_provider=lambda names: {},  # noqa: ARG005
    )
    registrations = build_mcp_tool_registrations(catalog, executor_config=config)

    assert len(registrations) == 1
    spec = registrations[0].spec
    assert spec.name == "mcp__repo__echo"
    assert spec.approval_policy.value == "always"
    assert spec.side_effect.value == "external"
    assert spec.safety_policy["credential_profile"] == "ops-profile"
    assert spec.safety_policy["safety_generation"] == "gen-1"
    assert spec.safety_policy["composition_epoch"] == "epoch-1"

    prepared = runtime_prepare(registrations, "hello")
    assert isinstance(prepared, ApprovalRequired)
    preview = prepared.request.preview
    assert "repo" in preview and "echo" in preview
    assert "ops-profile" in preview and "gen-1" in preview and "epoch-1" in preview


def runtime_prepare(registrations, text):
    runtime = KernelToolRuntime(registrations)
    return runtime.prepare(
        ToolCall("call-1", "mcp__repo__echo", {"text": text}), _ctx()
    )


def test_executed_outcome_returns_text(tmp_path: Path) -> None:
    outcome = McpBridgeOutcome(
        classification=McpOutcomeClassification.EXECUTED,
        call_may_have_been_sent=True,
        terminal_response_received=True,
        terminal_request_id_matched=True,
        result_text="hello back",
    )
    registrations, _stub = _registrations_with_stub(tmp_path, outcome)
    runtime = KernelToolRuntime(registrations)
    call = ToolCall("call-1", "mcp__repo__echo", {"text": "hello"})
    intent = _approved_intent(runtime, call)
    assert isinstance(intent, ExecutionIntent)

    result = runtime.invoke(intent)
    assert result.is_error is False
    assert result.content == "hello back"


def test_executed_remote_iserror_maps_to_known_executed_error_not_success(tmp_path: Path) -> None:
    """A remote tool that reports ``isError`` still executed the call (bytes were sent,
    response received), so it must surface as a known-executed error
    (``is_error=True, executed=True``). Returning the server's error text as a plain
    success string would mislead the model into treating the failure as valid data."""
    outcome = McpBridgeOutcome(
        classification=McpOutcomeClassification.EXECUTED,
        call_may_have_been_sent=True,
        terminal_response_received=True,
        terminal_request_id_matched=True,
        result_text="fixture tool failed on purpose",
        error_code="remote_error",
        error_message="remote tool reported isError",
    )
    registrations, _stub = _registrations_with_stub(tmp_path, outcome)
    runtime = KernelToolRuntime(registrations)
    intent = _approved_intent(runtime, ToolCall("call-1", "mcp__repo__echo", {"text": "x"}))

    result = runtime.invoke(intent)
    assert result.is_error is True
    assert result.executed is True
    assert result.metadata["code"] == "remote_error"
    # the server's error text must still reach the model so it can correct its arguments
    assert "fixture tool failed" in result.content


def test_executed_unsupported_content_maps_to_known_executed_error(tmp_path: Path) -> None:
    """A result that only contains unsupported (non-text) content blocks was still
    executed; it must be a known-executed error, not an empty success string."""
    outcome = McpBridgeOutcome(
        classification=McpOutcomeClassification.EXECUTED,
        call_may_have_been_sent=True,
        terminal_response_received=True,
        terminal_request_id_matched=True,
        result_text="",
        error_code="unsupported_content",
        error_message="result contained unsupported content blocks",
    )
    registrations, _stub = _registrations_with_stub(tmp_path, outcome)
    runtime = KernelToolRuntime(registrations)
    intent = _approved_intent(runtime, ToolCall("call-1", "mcp__repo__echo", {"text": "x"}))

    result = runtime.invoke(intent)
    assert result.is_error is True
    assert result.executed is True
    assert result.metadata["code"] == "unsupported_content"


def test_not_executed_outcome_maps_to_known_not_executed(tmp_path: Path) -> None:
    outcome = McpBridgeOutcome(
        classification=McpOutcomeClassification.NOT_EXECUTED,
        error_code="descriptor_drift",
        error_message="remote descriptor drifted",
    )
    registrations, _stub = _registrations_with_stub(tmp_path, outcome)
    runtime = KernelToolRuntime(registrations)
    intent = _approved_intent(runtime, ToolCall("call-1", "mcp__repo__echo", {"text": "x"}))

    result = runtime.invoke(intent)
    assert result.is_error is True
    assert result.executed is False


def test_unknown_outcome_raises_recovery_without_quarantining_shared_bridge(
    tmp_path: Path,
) -> None:
    """clean UNKNOWN（coroutine 正常返回）必须抛 McpUnknownOutcomeError 进入 recovery，
    但不 quarantine 共享 bridge——bridge 的 thread/loop 健康，单个 server 的不确定 outcome
    不得永久误伤同 composition 的无关 MCP server。durable 安全由 per-binding latch 保证。"""
    outcome = McpBridgeOutcome(
        classification=McpOutcomeClassification.UNKNOWN,
        call_may_have_been_sent=True,
        error_message="timeout after call",
    )
    registrations, stub = _registrations_with_stub(tmp_path, outcome)
    runtime = KernelToolRuntime(registrations)
    intent = _approved_intent(runtime, ToolCall("call-1", "mcp__repo__echo", {"text": "x"}))

    with pytest.raises(McpUnknownOutcomeError):
        runtime.invoke(intent)
    assert stub.quarantined is False


def test_real_echo_end_to_end_through_tool_runtime(tmp_path: Path) -> None:
    catalog, _exe = _catalog(tmp_path)
    directory = tmp_path / "safety"
    directory.mkdir(mode=0o700, exist_ok=True)
    bridge = McpAsyncBridge(total_timeout_seconds=40)
    try:
        config = McpExecutorConfig(
            bridge=bridge,
            latch=McpSafetyLatch(directory / "latch.json"),
            composition_epoch="epoch-1",
            timeouts=SessionTimeouts(initialize=10, list_page=10, call=10, shutdown=5),
            env_provider=lambda names: {},  # noqa: ARG005
        )
        registrations = build_mcp_tool_registrations(catalog, executor_config=config)
        runtime = KernelToolRuntime(registrations)
        call = ToolCall("call-1", "mcp__repo__echo", {"text": "via mcp"})
        intent = _approved_intent(runtime, call)
        assert isinstance(intent, ExecutionIntent)

        result = runtime.invoke(intent)
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        assert result.content == "via mcp"
    finally:
        bridge.close()


def test_post_send_bridge_timeout_enters_unknown_recovery(tmp_path: Path) -> None:
    """A3: a bridge total timeout after the coroutine is in flight cannot prove call bytes
    were not written, so it must surface as UNKNOWN (parent recovery + quarantine), not as
    a known-not-executed result the model could safely retry."""
    from agent.mcp.bridge import BridgeTimeoutError
    from agent.mcp.safety import McpSafetyLatch

    class _TimeoutBridge:
        def __init__(self) -> None:
            self.quarantined = False

        def submit(self, factory):  # noqa: ARG002
            raise BridgeTimeoutError("bridge wall-clock cap exceeded")

        def quarantine(self, *, reason: str = "") -> None:  # noqa: ARG002
            self.quarantined = True

    catalog, _exe = _catalog(tmp_path)
    directory = tmp_path / "safety"
    directory.mkdir(mode=0o700, exist_ok=True)
    stub = _TimeoutBridge()
    config = McpExecutorConfig(
        bridge=stub,
        latch=McpSafetyLatch(directory / "latch.json"),
        composition_epoch="epoch-1",
        timeouts=SessionTimeouts(),
        env_provider=lambda names: {},  # noqa: ARG005
    )
    registrations = build_mcp_tool_registrations(catalog, executor_config=config)
    runtime = KernelToolRuntime(registrations)
    intent = _approved_intent(runtime, ToolCall("call-1", "mcp__repo__echo", {"text": "x"}))

    with pytest.raises(McpUnknownOutcomeError):
        runtime.invoke(intent)
    assert stub.quarantined is True


def test_preview_overflow_rejects_before_approval_not_truncates(tmp_path: Path) -> None:
    """F3/R6: canonical arguments exceeding the preview cap must be rejected at prepare
    (known-not-executed), not silently truncated while full args execute."""
    from agent.mcp.contracts import McpOutcomeClassification
    from agent.mcp.tools import PREVIEW_ARG_CAP

    catalog, _exe = _catalog(tmp_path)
    directory = tmp_path / "safety"
    directory.mkdir(mode=0o700, exist_ok=True)
    stub = _StubBridge(
        McpBridgeOutcome(classification=McpOutcomeClassification.EXECUTED, result_text="ok")
    )
    config = McpExecutorConfig(
        bridge=stub,
        latch=McpSafetyLatch(directory / "latch.json"),
        composition_epoch="epoch-1",
        timeouts=SessionTimeouts(),
        env_provider=lambda names: {},  # noqa: ARG005
    )
    registrations = build_mcp_tool_registrations(catalog, executor_config=config)
    runtime = KernelToolRuntime(registrations)

    # Arguments whose canonical JSON exceeds PREVIEW_ARG_CAP.
    oversized = "x" * (PREVIEW_ARG_CAP + 100)
    call = ToolCall("call-1", "mcp__repo__echo", {"text": oversized})
    prepared = runtime.prepare(call, _ctx())

    # Must be a known-not-executed error, NOT an approval with truncated preview.
    assert isinstance(prepared, ToolResult), (
        "oversized arguments must be rejected at prepare, not accepted with truncated preview"
    )
    assert prepared.is_error is True
    assert prepared.executed is False


CHATTY_SCHEMA = {
    "type": "object",
    "properties": {"marker": {"type": "string"}, "kbytes": {"type": "integer"}},
    "required": ["marker", "kbytes"],
}


def _chatty_config(exe: str) -> dict:
    return {
        "servers": [
            {
                "server_id": "repo",
                "transport": "stdio",
                "command": exe,
                "args": [],
                "safety_generation": "gen-1",
                "protocol_revision": "2025-11-25",
                "credential_profile": "ops-profile",
                "tools": [
                    {
                        "remote_name": "chatty",
                        "description": "Write a stderr burst, then return a marker.",
                        "input_schema": CHATTY_SCHEMA,
                        "output_limit_chars": 1000,
                    }
                ],
            }
        ]
    }


def test_stderr_is_drained_and_does_not_leak_into_result(tmp_path: Path) -> None:
    """G2: stderr is continuously drained and bounded. A server that floods stderr (far
    beyond the OS pipe buffer) must not deadlock the call, and stderr content must never
    reach the model-facing result."""
    import shlex

    wrapper = tmp_path / "run_server.sh"
    wrapper.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(SERVER))}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    catalog = build_mcp_catalog(_chatty_config(str(wrapper)))
    directory = tmp_path / "safety"
    directory.mkdir(mode=0o700, exist_ok=True)
    bridge = McpAsyncBridge(total_timeout_seconds=30)
    try:
        config = McpExecutorConfig(
            bridge=bridge,
            latch=McpSafetyLatch(directory / "latch.json"),
            composition_epoch="epoch-1",
            timeouts=SessionTimeouts(initialize=10, list_page=10, call=15, shutdown=5),
            env_provider=lambda names: {},  # noqa: ARG005
        )
        registrations = build_mcp_tool_registrations(catalog, executor_config=config)
        runtime = KernelToolRuntime(registrations)
        # 256 KB of stderr >> 64 KB pipe buffer: without continuous draining the server
        # blocks before it can return the result.
        call = ToolCall("call-1", "mcp__repo__chatty", {"marker": "ok", "kbytes": 256})
        intent = _approved_intent(runtime, call)
        result = runtime.invoke(intent)
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        assert result.content == "done-ok"
        assert "SECRET-STDERR-MARKER" not in result.content
        assert "S" * 1024 not in result.content
    finally:
        bridge.close()


def test_executable_drift_after_approval_is_not_executed(tmp_path: Path) -> None:
    """G2: spawn-time executable identity+digest revalidation. After approval bound the
    executable's frozen identity, replacing the executable content before invoke must be
    detected BEFORE spawn and returned as known-not-executed (the tampered binary never runs)."""
    catalog, exe = _catalog(tmp_path)
    directory = tmp_path / "safety"
    directory.mkdir(mode=0o700, exist_ok=True)
    bridge = McpAsyncBridge(total_timeout_seconds=30)
    try:
        config = McpExecutorConfig(
            bridge=bridge,
            latch=McpSafetyLatch(directory / "latch.json"),
            composition_epoch="epoch-1",
            timeouts=SessionTimeouts(initialize=10, list_page=10, call=10, shutdown=5),
            env_provider=lambda names: {},  # noqa: ARG005
        )
        registrations = build_mcp_tool_registrations(catalog, executor_config=config)
        runtime = KernelToolRuntime(registrations)
        intent = _approved_intent(
            runtime, ToolCall("call-1", "mcp__repo__echo", {"text": "x"})
        )

        # Tamper after approval: content (hence digest) changes, but it is still a valid
        # server wrapper. Without spawn-time revalidation this would spawn and succeed.
        tampered = exe.read_text(encoding="utf-8") + "\n# tampered after approval\n"
        exe.write_text(tampered, encoding="utf-8")
        exe.chmod(0o700)

        result = runtime.invoke(intent)
        assert isinstance(result, ToolResult)
        assert result.executed is False
        assert result.is_error is True
        assert result.content != "x"  # tampered binary never produced the echo result
    finally:
        bridge.close()

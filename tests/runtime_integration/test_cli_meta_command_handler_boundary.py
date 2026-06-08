"""CLI meta-command ownership guardrails for post-memory hardening."""

from __future__ import annotations

from types import SimpleNamespace

from agent.runtime_integration.cli_handlers import handle_cli_meta_command
from agent.runtime_integration.schema import RuntimeActionResult, RuntimeActionType


class _Dispatcher:
    def __init__(self) -> None:
        self.requests = []

    def route(self, request):
        self.requests.append(request)
        if request.action_type == RuntimeActionType.CLI_SHOW_MEMORIES:
            return RuntimeActionResult(
                action_type=request.action_type,
                status="success",
                payload={"records": ()},
                evidence={},
            )
        if request.action_type == RuntimeActionType.CLI_SHOW_SUBAGENTS:
            return RuntimeActionResult(
                action_type=request.action_type,
                status="success",
                payload={"descriptors": ()},
                evidence={},
            )
        if request.action_type == RuntimeActionType.MEMORY_FORGET:
            return RuntimeActionResult(
                action_type=request.action_type,
                status="success",
                payload={"forgotten": False},
                evidence={},
            )
        raise AssertionError(f"unexpected action type: {request.action_type}")


class _MemoryRuntime:
    def __init__(self) -> None:
        self.records = ()

    def list_records(self):
        return self.records


def test_cli_meta_handler_covers_only_real_existing_commands() -> None:
    read_dispatcher = _Dispatcher()
    mutating_dispatcher = _Dispatcher()
    runtime = _MemoryRuntime()
    runtime.records = (
        SimpleNamespace(id="memory:abc123", content="abc keyword"),
    )

    assert "暂无" in handle_cli_meta_command(
        "show memories",
        read_only_dispatcher=read_dispatcher,
        mutating_dispatcher=mutating_dispatcher,
        memory_runtime=runtime,
    )
    assert "暂无" in handle_cli_meta_command(
        "show subagents",
        read_only_dispatcher=read_dispatcher,
        mutating_dispatcher=mutating_dispatcher,
        memory_runtime=runtime,
    )
    assert "已移除" in handle_cli_meta_command(
        "forget abc",
        read_only_dispatcher=read_dispatcher,
        mutating_dispatcher=mutating_dispatcher,
        memory_runtime=runtime,
    )

    handled = {request.action_type for request in read_dispatcher.requests}
    handled.update(request.action_type for request in mutating_dispatcher.requests)
    assert RuntimeActionType.CLI_SHOW_MEMORIES in handled
    assert RuntimeActionType.CLI_SHOW_SUBAGENTS in handled
    assert RuntimeActionType.MEMORY_FORGET in handled


def test_cli_meta_handler_does_not_introduce_update_memory_cli() -> None:
    read_dispatcher = _Dispatcher()
    mutating_dispatcher = _Dispatcher()
    runtime = _MemoryRuntime()

    result = handle_cli_meta_command(
        "update memory: prefer concise replies",
        read_only_dispatcher=read_dispatcher,
        mutating_dispatcher=mutating_dispatcher,
        memory_runtime=runtime,
    )

    assert result is None
    assert not hasattr(RuntimeActionType, "MEMORY_UPDATE")
    assert not read_dispatcher.requests
    assert not mutating_dispatcher.requests


def test_forget_by_id_prefix_still_uses_memory_runtime_without_new_policy_path() -> None:
    read_dispatcher = _Dispatcher()
    mutating_dispatcher = _Dispatcher()
    runtime = _MemoryRuntime()
    runtime.records = (
        SimpleNamespace(id="memory:abc123456", content="keep this"),
    )

    result = handle_cli_meta_command(
        "forget id:memory:abc",
        read_only_dispatcher=read_dispatcher,
        mutating_dispatcher=mutating_dispatcher,
        memory_runtime=runtime,
    )

    assert "移除记忆失败" in result or "已移除记忆" in result
    assert [request.action_type for request in mutating_dispatcher.requests] == [
        RuntimeActionType.MEMORY_FORGET,
        RuntimeActionType.MEMORY_FORGET,
    ]

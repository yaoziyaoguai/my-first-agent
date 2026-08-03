"""F6 Red test: TUI must complete approval/recovery journey by keyboard, not just submit."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    RunStatus,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from agent.tui.adapter import TuiAdapter
from agent.tui.app import build_app
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
)


def _write_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="write_fixture",
        version="1",
        description="fixture approval tool",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={},
        output_limit_chars=100,
    )


def _run_id_factory() -> Callable[[], str]:
    counter = {"n": 0}

    def factory() -> str:
        counter["n"] += 1
        return f"tui-run-{counter['n']}"

    return factory


def test_pending_reopen_keyboard_journey_and_shared_lifecycle(tmp_path: Path) -> None:
    """F6/R19-R20: TUI must complete submit → approval → keyboard approve → terminal
    using real Pilot key presses, with focus on the approval form and authoritative
    checkpoint parity."""
    pytest.importorskip("textual")

    # write_fixture 是 effectful 工具：TUI journey 从已有 durable Goal 的 checkpoint
    # 起步；app 经 build_submit 从 authoritative state 派生合法 seq/revision。
    store = InMemoryCheckpointStore(conversation_with_active_goal("tui-1"))
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("c1", "write_fixture", {}),)),
        ModelResponse((ModelTextBlock("approved and done"),)),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            (RegisteredTool(_write_tool_spec(), lambda intent: "written"),)
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            # Step 1: submit a message that triggers a tool needing approval.
            msg = pilot.app.query_one("#message")
            msg.value = "do the write"
            await pilot.press("enter")
            await pilot.pause(delay=0.1)

            # Wait for the approval pause to appear.
            state = adapter.load_view().snapshot.state
            for _ in range(50):
                await pilot.pause(delay=0.05)
                state = adapter.load_view().snapshot.state
                active = state.active_run
                if active is not None and active.status.value == "awaiting_approval":
                    break
            else:
                pytest.fail("did not reach AWAITING_APPROVAL")

            # Step 2: keyboard approve — press "a".
            await pilot.press("a")
            await pilot.pause(delay=0.1)

            # Wait for completion.
            for _ in range(50):
                await pilot.pause(delay=0.05)
                state = adapter.load_view().snapshot.state
                if state.active_run is None:
                    break
            else:
                pytest.fail("did not complete after approval")

            # Authoritative state must be COMPLETED.
            assert state.last_safe_result is not None
            assert state.last_safe_result.status is RunStatus.COMPLETED
            assert state.last_safe_result.message == "approved and done"

    asyncio.run(scenario())


def test_pilot_reject_keyboard_journey_executes_nothing(tmp_path: Path) -> None:
    """R19: reject 键盘路径——按 r 拒绝后工具不执行，run 继续到完成。"""
    pytest.importorskip("textual")

    store = InMemoryCheckpointStore(conversation_with_active_goal("tui-reject"))
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("c1", "write_fixture", {}),)),
        ModelResponse((ModelTextBlock("rejected and done"),)),
    )
    tool_calls_made: list[int] = []

    def _write_callable(intent) -> str:
        tool_calls_made.append(1)
        return "written"

    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            (RegisteredTool(_write_tool_spec(), _write_callable),)
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    adapter = TuiAdapter(runtime, store)

    async def scenario() -> None:
        app = build_app(adapter, run_id_factory=_run_id_factory())
        async with app.run_test() as pilot:
            msg = pilot.app.query_one("#message")
            msg.value = "do the write"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(delay=0.05)
                state = adapter.load_view().snapshot.state
                active = state.active_run
                if active is not None and active.status.value == "awaiting_approval":
                    break
            else:
                pytest.fail("did not reach AWAITING_APPROVAL")

            await pilot.press("r")  # keyboard reject
            for _ in range(50):
                await pilot.pause(delay=0.05)
                state = adapter.load_view().snapshot.state
                if state.active_run is None:
                    break
            else:
                pytest.fail("did not complete after reject")

            assert state.last_safe_result is not None
            assert state.last_safe_result.status is RunStatus.COMPLETED
            assert state.last_safe_result.message == "rejected and done"
            assert tool_calls_made == [], "rejected tool must not execute"

    asyncio.run(scenario())

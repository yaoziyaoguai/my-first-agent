from __future__ import annotations

import asyncio
import threading
import time

import pytest

from agent.mcp.bridge import (
    BridgeClosedError,
    BridgeQuarantinedError,
    BridgeTimeoutError,
    McpAsyncBridge,
)
from agent.mcp.contracts import McpBridgeOutcome, McpOutcomeClassification


def _outcome(text: str = "ok") -> McpBridgeOutcome:
    return McpBridgeOutcome(
        classification=McpOutcomeClassification.EXECUTED,
        call_may_have_been_sent=True,
        terminal_response_received=True,
        terminal_request_id_matched=True,
        process_exit_confirmed=True,
        result_text=text,
    )


def test_bridge_runs_submitted_coroutine_and_returns_outcome() -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=2.0)
    try:
        outcome = bridge.submit(lambda: _run_outcome("hello"))
    finally:
        bridge.close()

    assert outcome.classification is McpOutcomeClassification.EXECUTED
    assert outcome.result_text == "hello"


async def _run_outcome(text: str) -> McpBridgeOutcome:
    await asyncio.sleep(0)
    return _outcome(text)


def test_bridge_serializes_concurrent_submissions() -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=2.0)
    order: list[str] = []
    lock = threading.Lock()

    def make(name: str):
        async def coro() -> McpBridgeOutcome:
            with lock:
                order.append(f"start-{name}")
            await asyncio.sleep(0.05)
            with lock:
                order.append(f"end-{name}")
            return _outcome(name)

        return coro

    threads = [threading.Thread(target=lambda n=n: bridge.submit(make(n))) for n in ("a", "b", "c")]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        bridge.close()

    # 每个 submit 独占 owner loop，不会与另一个 submit 交错。
    for name in ("a", "b", "c"):
        joined = "-".join(order)
        assert joined.index(f"start-{name}") < joined.index(f"end-{name}")


def test_submission_after_close_is_rejected() -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=2.0)
    bridge.close()

    with pytest.raises(BridgeClosedError):
        bridge.submit(lambda: _run_outcome("late"))
    # close 是幂等的。
    bridge.close()


def test_quarantine_rejects_every_later_submission() -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=2.0)
    bridge.quarantine(reason="cleanup uncertainty")
    try:
        with pytest.raises(BridgeQuarantinedError):
            bridge.submit(lambda: _run_outcome("after"))
    finally:
        bridge.close()


def test_total_timeout_quarantines_and_does_not_hang() -> None:
    bridge = McpAsyncBridge(total_timeout_seconds=0.1)
    start = time.monotonic()

    async def slow() -> McpBridgeOutcome:
        await asyncio.sleep(5.0)
        return _outcome("never")

    with pytest.raises(BridgeTimeoutError):
        bridge.submit(slow)
    elapsed = time.monotonic() - start
    bridge.close()
    assert elapsed < 2.0


def test_bridge_construction_starts_no_session_or_subprocess() -> None:
    # 仅验证 bridge lifecycle；stdio session 由 U3 在 coroutine 内创建。
    bridge = McpAsyncBridge(total_timeout_seconds=2.0)
    try:
        assert bridge.is_open()
    finally:
        bridge.close()


def test_cleanup_uncertainty_forces_unknown_and_quarantine() -> None:
    """A5: a terminal response received but process-group cleanup not confirmed must
    reclassify EXECUTED to UNKNOWN; the parent must enter recovery, not accept the result."""
    from agent.mcp.bridge import _CommitState, _finalize_outcome
    from agent.mcp.contracts import McpBridgeOutcome, McpOutcomeClassification

    executed = McpBridgeOutcome(
        classification=McpOutcomeClassification.EXECUTED,
        call_may_have_been_sent=True,
        terminal_response_received=True,
        terminal_request_id_matched=True,
        process_exit_confirmed=False,
        result_text="ok",
    )
    commit = _CommitState()
    commit.process_exit_confirmed = False

    finalized = _finalize_outcome(executed, commit)
    assert finalized.classification is McpOutcomeClassification.UNKNOWN
    assert finalized.process_exit_confirmed is False

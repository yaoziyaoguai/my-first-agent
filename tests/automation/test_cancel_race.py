from __future__ import annotations

import pytest

from agent.automation.claim_verifier import AutomationClaimVerifier
from agent.automation.contracts import CancelAutomation
from agent.automation.controller import AutomationController
from agent.runtime.contracts import ExecutionIntent, ToolCall
from agent.runtime.tools import IntentConflictError, KernelToolRuntime

from .test_claim_verifier import _running_claim
from .test_tool_authority import _context, _sandbox_registration


def test_cancel_pending_after_prepare_rejects_invoke_with_zero_callable() -> None:
    repository, _ = _running_claim()
    calls: list[str] = []
    runtime = KernelToolRuntime(
        (_sandbox_registration(calls),),
        background_claim_verifier=AutomationClaimVerifier(repository),
        clock=lambda: "2026-08-28T00:01:00Z",
    )
    intent = runtime.prepare(
        ToolCall("call-1", "sandbox_exec", {"executable": "/usr/bin/true"}),
        _context(),
    )
    assert isinstance(intent, ExecutionIntent)

    AutomationController(repository).handle(
        CancelAutomation(
            expected_snapshot_token="snapshot-token-0005",
            next_snapshot_token="snapshot-token-0006",
            automation_id="automation:nightly-report",
        )
    )

    with pytest.raises(IntentConflictError, match="background claim"):
        runtime.invoke(intent)
    assert calls == []

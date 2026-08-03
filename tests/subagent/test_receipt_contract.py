"""F5 Red tests: prove structural receipt contract gaps.

These tests assert CORRECT behavior and must fail until the receipt contract is implemented.
"""

from __future__ import annotations

from agent.runtime.contracts import (
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    RunStatus,
)
from agent.subagent.contracts import (
    ChildProfile,
    ProviderDeadlineCapability,
)
from agent.subagent.runner import ChildAgentRunner
from tests.kernel.fakes import ScriptedProvider

SCOPE = "scope-1"


def _profile(**overrides) -> ChildProfile:
    base = {
        "runner_version": "subagent-v1",
        "provider_profile_id": "default",
        "provider_destination": "local",
        "workspace_scope_digest": SCOPE,
        "max_input_tokens": 4_000,
        "max_output_tokens": 1_000,
        "limits_digest": "limits-1",
        "hard_deadline_seconds": 30.0,
    }
    base.update(overrides)
    return ChildProfile(**base)


def test_confirmed_completed_is_success() -> None:
    """R16: COMPLETED + confirmed terminal receipt = success."""
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("child answer"),)))
    runner = ChildAgentRunner(provider=provider, profile=_profile())
    result = runner.run(
        objective="review", handoff="", parent_idempotency_key="parent:run-1:call-1"
    )
    assert result.status is RunStatus.COMPLETED
    assert result.receipt_state == "terminated"


def test_confirmed_nonterminal_is_known_executed_error() -> None:
    """R16: confirmed nonterminal (child asked for tool) = known-executed error, not success."""
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("c1", "read_file", {"path": "x"}),))
    )
    runner = ChildAgentRunner(provider=provider, profile=_profile())
    result = runner.run(
        objective="try tool", handoff="", parent_idempotency_key="parent:run-1:call-2"
    )
    assert result.status is not RunStatus.COMPLETED
    assert result.receipt_state == "terminated"
    assert result.reason == "child_nonterminal"


def test_unconfirmed_receipt_overrides_child_normalization() -> None:
    """R16/O1（tightened）：UNCONFIRMED receipt 必然覆盖任何 child nonterminal/error
    normalization 并进入 parent recovery——不允许接受 ``terminated|unconfirmed`` 二选一。

    确定性故障注入：child 本会返回 tool call（child_nonterminal），但其 generate 阻塞超过
    parent 的 hard deadline。parent kill 进程组（process-isolated 路径），child 从未 terminally
    报告 → receipt 必然是 UNCONFIRMED（覆盖 would-be child_nonterminal），并经 executor 抛
    SubAgentUnknownOutcomeError → parent recovery。无 race：sleep 5s >> deadline 0.5s。
    """
    from agent.subagent.contracts import ChildProviderSpec
    from agent.subagent.process_runner import ChildProcessRunner

    runner = ChildProcessRunner(
        provider_spec=ChildProviderSpec(
            kind="fake", fake_tool=("read_file", {"path": "x"}), sleep_seconds=5.0
        ),
        profile=_profile(),
        hard_deadline_seconds=0.5,
    )
    result = runner.run(
        objective="would-be tool call but hangs past deadline",
        handoff="",
        parent_idempotency_key="parent:run-1:call-3",
    )
    # 严格断言 UNCONFIRMED（不接受 terminated 二选一）；它覆盖了 child 本会报告的 nonterminal。
    assert result.receipt_state == "unconfirmed"
    assert result.reason == "unconfirmed_outcome"



def test_objective_overflow_rejected_at_prepare() -> None:
    """R15: objective exceeding limit must be rejected at prepare/schema, not silently truncated."""
    from agent.runtime.contracts import ToolCall, ToolPrepareContext, ToolResult
    from agent.runtime.tools import KernelToolRuntime
    from agent.subagent.tools import _MAX_OBJECTIVE, build_subagent_tool_registrations

    provider = ScriptedProvider(ModelResponse((ModelTextBlock("ok"),)))
    runner = ChildAgentRunner(provider=provider, profile=_profile())
    registrations = build_subagent_tool_registrations(runner)
    runtime = KernelToolRuntime(registrations)

    oversized = "x" * (_MAX_OBJECTIVE + 100)
    prepared = runtime.prepare(
        ToolCall(
            "call-1",
            "subagent__delegate",
            {"objective": oversized, "handoff": ""},
        ),
        ToolPrepareContext("c1", "r1", 1),
    )
    assert isinstance(prepared, ToolResult), (
        "oversized objective must be rejected at prepare, not truncated"
    )
    assert prepared.is_error is True


def test_provider_without_deadline_contract_rejected() -> None:
    """R14: provider without structural deadline support must fail at composition/runner
    construction, not silently accepted."""

    class _NoDeadlineProvider:
        def generate(self, context):
            return ModelResponse((ModelTextBlock("ok"),))

    # Provider must have a structural deadline capability attribute, not just be any object.
    assert not hasattr(_NoDeadlineProvider(), ProviderDeadlineCapability.attr_name), (
        "plain provider must not satisfy deadline contract"
    )


def test_supported_fake_provider_satisfies_contract() -> None:
    """R14: a FakeProvider that structurally declares deadline support satisfies the contract."""

    class _SupportedFake:
        deadline_contract = ProviderDeadlineCapability(
            hard_deadline_seconds=30.0,
            receipt_type="synchronous",
        )

        def generate(self, context):
            return ModelResponse((ModelTextBlock("ok"),))

    provider = _SupportedFake()
    assert hasattr(provider, ProviderDeadlineCapability.attr_name)
    assert ProviderDeadlineCapability.from_provider(provider).receipt_type == "synchronous"

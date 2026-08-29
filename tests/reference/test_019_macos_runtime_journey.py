from __future__ import annotations

from agent.automation.claim_verifier import AutomationClaimVerifier
from agent.composition import build_composition
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    ConversationWorkspaceBindingV1,
    FactKind,
    GoalStatus,
    RunStatus,
)
from agent.runtime.loop import InvocationLimits
from agent.sandbox.contracts import SandboxMode, SandboxNetworkMode
from agent.sandbox.policy import build_sandbox_policy
from agent.sandbox.tools import build_sandbox_exec_registration
from agent.scheduler.caller import (
    ScheduledOccurrenceCaller,
    create_or_load_occurrence_store,
)
from agent.scheduler.contracts import ScheduledOccurrence
from scripts._019_macos_u2b_host import _U2BProvider
from scripts.run_019_macos_e3 import _U2B_TASK
from tests.automation.test_claim_verifier import _execution_authority, _running_claim
from tests.kernel.fakes import CollectingSink
from tests.sandbox.test_executor import FakeConfiner, FakeRunner, _seatbelt_invocation


def test_u2b_provider_uses_the_existing_runtime_and_one_background_receipt(
    tmp_path,
) -> None:
    repository, authority = _running_claim()
    execution_authority = _execution_authority(authority)
    occurrence_binding = execution_authority.occurrence_binding
    workspace_binding = ConversationWorkspaceBindingV1.create(
        workspace_scope_digest="8" * 64,
        workspace_identity_digest="a" * 64,
        bound_at=occurrence_binding.scheduled_for_utc,
    )
    occurrence = ScheduledOccurrence(
        schedule_id=occurrence_binding.automation_id,
        occurrence_id=occurrence_binding.occurrence_id,
        scheduled_for_utc=occurrence_binding.scheduled_for_utc,
        message=_U2B_TASK,
        workspace_scope_digest=workspace_binding.workspace_scope_digest,
        background_binding=occurrence_binding,
    )
    roots = {
        name: tmp_path / name
        for name in ("workspace", "temp", "state", "home", "checkpoints")
    }
    for root in roots.values():
        root.mkdir(mode=0o700)
    policy = build_sandbox_policy(
        mode=SandboxMode.WORKSPACE_WRITE,
        network=SandboxNetworkMode.OFF,
        workspace=roots["workspace"],
        temp_root=roots["temp"],
        state_root=roots["state"],
        home=roots["home"],
        private_roots=(),
    )
    confiner = FakeConfiner()

    def confine(command, actual_policy, environment):  # noqa: ANN001, ANN202
        invocation = _seatbelt_invocation(actual_policy, command, environment)
        confiner.calls.append((command, actual_policy, dict(environment)))
        return invocation

    confiner.confine = confine  # type: ignore[method-assign]
    process_runner = FakeRunner()
    registration = build_sandbox_exec_registration(
        workspace=roots["workspace"],
        temp_root=roots["temp"],
        state_root=roots["state"],
        home=roots["home"],
        captured_path="/usr/bin:/bin",
        confiner=confiner,
        runner=process_runner,
        policy_builder=lambda _arguments, _roots, _private: policy,
        authority_policy_digest="6" * 64,
    )
    provider_calls: list[int] = []
    provider = _U2BProvider(provider_calls.append)
    store, snapshot = create_or_load_occurrence_store(
        occurrence,
        state_root=roots["checkpoints"],
        workspace_binding=workspace_binding,
    )
    composition = build_composition(
        provider=provider,
        checkpoint_store=store,
        tool_registrations=(registration,),
        event_sink=CollectingSink(),
        system_policy="bounded background policy",
        context_limits=ContextLimits(max_input_tokens=20_000, output_reserve=2_000),
        invocation_limits=InvocationLimits(max_model_calls=4, max_tool_calls=4),
        workspace_identity_digest=workspace_binding.workspace_identity_digest,
        context_scope_digest=workspace_binding.workspace_scope_digest,
        workspace_binding=workspace_binding,
        background_claim_verifier=AutomationClaimVerifier(repository),
        background_execution_authority=execution_authority,
        tool_clock=lambda: "2026-08-28T00:01:00Z",
    )

    report = ScheduledOccurrenceCaller(
        composition.runtime,
        store,
        snapshot,
        occurrence,
    ).run_once()
    state = store.load().state
    tool_results = tuple(
        fact for fact in state.facts if fact.kind is FactKind.TOOL_RESULT
    )

    assert report.occurrence_status == "completed"
    assert report.run_status is RunStatus.COMPLETED
    assert state.goal is not None and state.goal.status is GoalStatus.BLOCKED
    assert state.active_run is None
    assert provider_calls == [1, 2, 3]
    assert len(process_runner.calls) == 1
    assert len(tool_results) == 1
    assert tool_results[0].content["executed"] is True
    assert (
        tool_results[0].content["metadata"]["sandbox_receipt_kind"]
        == "background_sandbox_v1"
    )

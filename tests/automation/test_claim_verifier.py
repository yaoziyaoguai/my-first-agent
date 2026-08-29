from __future__ import annotations

from dataclasses import replace

from agent.automation.claim_verifier import AutomationClaimVerifier
from agent.automation.contracts import (
    ClaimOccurrence,
    MarkDispatched,
    MarkRunning,
)
from agent.automation.controller import AutomationController
from agent.runtime.contracts import (
    BackgroundClaimCheckV1,
    BackgroundExecutionAuthorityV1,
    BackgroundOccurrenceBindingV1,
    canonical_json_digest,
)

from .test_controller import _active_repository, _authority


def _running_claim():  # noqa: ANN202
    repository = _active_repository()
    controller = AutomationController(repository)
    authority = _authority()
    controller.handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            authority=authority,
        )
    )
    controller.handle(
        MarkDispatched(
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
            automation_id=authority.automation_id,
            authority_digest=authority.authority_digest,
            process_identity_digest="e" * 64,
        )
    )
    controller.handle(
        MarkRunning(
            expected_snapshot_token="snapshot-token-0004",
            next_snapshot_token="snapshot-token-0005",
            automation_id=authority.automation_id,
            authority_digest=authority.authority_digest,
            process_identity_digest="e" * 64,
        )
    )
    return repository, authority


def _execution_authority(authority=None) -> BackgroundExecutionAuthorityV1:  # noqa: ANN001
    authority = authority or _authority()
    binding = BackgroundOccurrenceBindingV1.create(
        automation_id=authority.automation_id,
        automation_revision=authority.automation_revision,
        occurrence_id=authority.occurrence_id,
        occurrence_index=authority.occurrence_index,
        scheduled_for_utc=authority.scheduled_for_utc,
        definition_digest=authority.definition_digest,
        grant_digest=authority.grant_digest,
        claim_authority_digest=authority.authority_digest,
        claim_capability_digest=canonical_json_digest(authority.raw_capability),
        checkpoint_identity_digest=authority.checkpoint_identity,
        deadline_utc=authority.deadline_utc,
        model_call_limit=4,
        tool_call_limit=8,
        sandbox_command_limit=2,
        browser_action_limit=3,
        max_input_tokens=20_000,
        max_output_tokens=4_000,
    )
    return BackgroundExecutionAuthorityV1.create(
        occurrence_binding=binding,
        claim_fencing_token=authority.claim_fencing_token,
        raw_capability=authority.raw_capability,
        isolated_workspace_identity_digest="a" * 64,
        background_environment_policy_digest="6" * 64,
        browser_origin_policy_digest="7" * 64,
    )


def _check(execution_authority=None) -> BackgroundClaimCheckV1:  # noqa: ANN001
    return BackgroundClaimCheckV1.create(
        execution_authority=execution_authority or _execution_authority(),
        observed_at_utc="2026-08-28T00:01:00Z",
    )


def test_exact_running_claim_returns_closed_grant_verdict() -> None:
    repository, authority = _running_claim()

    verdict = AutomationClaimVerifier(repository).verify(
        _check(_execution_authority(authority))
    )

    assert verdict.allowed is True
    assert verdict.reason == "allowed"
    assert verdict.claim_authority_digest == authority.authority_digest
    assert verdict.sandbox_confined is True
    assert verdict.browser_public_observe is True
    assert verdict.background_environment_policy_digest == "6" * 64
    assert verdict.browser_origin_policy_digest == "7" * 64


def test_claim_identity_mutations_fail_closed() -> None:
    repository, authority = _running_claim()
    verifier = AutomationClaimVerifier(repository)
    check = _check(_execution_authority(authority))

    for drifted in (
        replace(check, automation_id="automation:other", check_digest=""),
        replace(check, automation_revision=2, check_digest=""),
        replace(check, occurrence_id="occurrence:other", check_digest=""),
        replace(check, definition_digest="a" * 64, check_digest=""),
        replace(check, grant_digest="b" * 64, check_digest=""),
        replace(check, claim_authority_digest="c" * 64, check_digest=""),
        replace(check, raw_capability="x" * 40, check_digest=""),
        replace(check, claim_fencing_token="claim-token-other", check_digest=""),
        replace(check, checkpoint_identity_digest="f" * 64, check_digest=""),
    ):
        verdict = verifier.verify(drifted)
        assert verdict.allowed is False
        assert verdict.reason in {"not_found", "claim_mismatch"}


def test_expired_claim_fails_closed_without_mutation() -> None:
    repository, authority = _running_claim()
    before = repository.load()

    verdict = AutomationClaimVerifier(repository).verify(
        BackgroundClaimCheckV1.create(
            execution_authority=_execution_authority(authority),
            observed_at_utc="2026-08-28T00:10:00Z",
        )
    )

    assert verdict.allowed is False
    assert verdict.reason == "expired"
    assert repository.load() == before

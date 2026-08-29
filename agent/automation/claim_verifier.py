"""AutomationStore active claim 的只读 live verifier。

它不持有 controller、不取得 mutation lease、不选择工具，也不把 raw capability
写入 Runtime checkpoint。`KernelToolRuntime` 在 prepare/invoke 两侧消费 verdict。
"""

from __future__ import annotations

import hmac

from agent.automation.contracts import (
    AutomationStatus,
    OccurrenceControlStatus,
    parse_canonical_utc,
)
from agent.automation.store import AutomationRepository
from agent.runtime.contracts import BackgroundClaimCheckV1, BackgroundClaimVerdictV1


class AutomationClaimVerifier:
    def __init__(self, repository: AutomationRepository) -> None:
        self._repository = repository

    def verify(self, check: BackgroundClaimCheckV1) -> BackgroundClaimVerdictV1:
        if not isinstance(check, BackgroundClaimCheckV1):
            raise TypeError("check must use BackgroundClaimCheckV1")
        record = next(
            (
                item
                for item in self._repository.load().records
                if item.automation_id == check.automation_id
            ),
            None,
        )
        if record is None:
            return _denied(check, "not_found")
        if record.status is AutomationStatus.CANCEL_PENDING:
            return _denied(check, "cancel_pending")
        claim = record.active_claim
        definition = record.active_claim_definition
        if claim is None or definition is None:
            return _denied(check, "claim_mismatch")
        if (
            claim.automation_revision != check.automation_revision
            or claim.occurrence_id != check.occurrence_id
            or claim.definition_digest != check.definition_digest
            or claim.grant_digest != check.grant_digest
            or claim.authority_digest != check.claim_authority_digest
            or claim.claim_fencing_token != check.claim_fencing_token
            or claim.checkpoint_identity != check.checkpoint_identity_digest
            or not hmac.compare_digest(claim.raw_capability, check.raw_capability)
        ):
            return _denied(check, "claim_mismatch")
        if record.active_claim_phase is not OccurrenceControlStatus.RUNNING:
            return _denied(check, "not_running")
        if parse_canonical_utc(check.observed_at_utc, "observed_at_utc") >= parse_canonical_utc(
            claim.deadline_utc,
            "deadline_utc",
        ):
            return _denied(check, "expired")
        body = definition.body
        grant = definition.grant
        if (
            definition.definition_digest != check.definition_digest
            or grant.grant_digest != check.grant_digest
        ):
            return _denied(check, "claim_mismatch")
        return BackgroundClaimVerdictV1(
            allowed=True,
            reason="allowed",
            check_digest=check.check_digest,
            claim_authority_digest=claim.authority_digest,
            definition_digest=definition.definition_digest,
            grant_digest=grant.grant_digest,
            sandbox_confined=grant.sandbox_confined,
            browser_public_observe=grant.browser_public_observe,
            background_environment_policy_digest=(
                body.background_environment_policy_digest
            ),
            browser_origin_policy_digest=body.browser_origin_policy_digest,
        )


def _denied(check: BackgroundClaimCheckV1, reason: str) -> BackgroundClaimVerdictV1:
    return BackgroundClaimVerdictV1(
        allowed=False,
        reason=reason,
        check_digest=check.check_digest,
        claim_authority_digest=None,
        definition_digest=None,
        grant_digest=None,
        sandbox_confined=False,
        browser_public_observe=False,
        background_environment_policy_digest=None,
        browser_origin_policy_digest=None,
    )

from __future__ import annotations

import pytest

from agent.automation.contracts import ClaimOccurrence
from agent.automation.controller import AutomationController
from agent.automation.store import (
    AutomationRepositoryConflictError,
    DeterministicAutomationRepository,
)

from .test_controller import _active_repository, _authority


def test_two_claims_from_one_snapshot_have_one_winner() -> None:
    initial = _active_repository().load()
    repository = DeterministicAutomationRepository(initial)
    first = AutomationController(repository)
    second = AutomationController(repository)

    first.handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-winner",
            authority=_authority(),
        )
    )

    with pytest.raises(AutomationRepositoryConflictError):
        second.handle(
            ClaimOccurrence(
                expected_snapshot_token="snapshot-token-0002",
                next_snapshot_token="snapshot-token-loser",
                authority=_authority(),
            )
        )

    assert repository.load().snapshot_token == "snapshot-token-winner"

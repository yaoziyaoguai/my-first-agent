from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent.automation.contracts import (
    AutomationRecordV1,
    AutomationSnapshotV1,
    AutomationStatus,
)
from agent.automation.store import (
    AutomationRepositoryBusyError,
    AutomationRepositoryConflictError,
    AutomationRepositoryUnknownCommitError,
    DeterministicAutomationRepository,
    DeterministicCommitFault,
    decode_snapshot,
    encode_snapshot,
)
from agent.runtime.contracts import canonical_json_digest

from .test_contracts import _definition


def _snapshot(*, revision: int = 0, token: str = "snapshot-token-0000") -> AutomationSnapshotV1:
    record = AutomationRecordV1(
        definition=_definition(),
        status=AutomationStatus.ACTIVE,
        next_occurrence_index=0,
        terminal_occurrence_count=0,
        needs_human_reason=None,
        active_claim=None,
        terminal_history=(),
    )
    return AutomationSnapshotV1(
        revision=revision,
        snapshot_token=token,
        records=(record,),
        tombstones=(),
    )


def test_snapshot_codec_round_trips_the_complete_definition() -> None:
    snapshot = _snapshot()

    decoded = decode_snapshot(encode_snapshot(snapshot))

    assert decoded == snapshot


def test_snapshot_decode_rejects_an_extra_nested_member() -> None:
    document = json.loads(encode_snapshot(_snapshot()))
    document["records"][0]["definition"]["body"]["future_authority"] = True

    with pytest.raises(ValueError, match="definition body fields"):
        decode_snapshot(json.dumps(document).encode("utf-8"))


def test_snapshot_decode_rejects_a_grant_that_conflicts_with_its_body() -> None:
    document = json.loads(encode_snapshot(_snapshot()))
    definition = document["records"][0]["definition"]
    grant = definition["grant"]
    grant["sandbox_confined"] = False
    grant["grant_digest"] = canonical_json_digest(
        {
            "definition_body_digest": grant["definition_body_digest"],
            "activation_preview_digest": grant["activation_preview_digest"],
            "sandbox_confined": grant["sandbox_confined"],
            "browser_public_observe": grant["browser_public_observe"],
        }
    )
    definition["definition_digest"] = canonical_json_digest(
        {
            "definition_body_digest": definition["body"]["definition_body_digest"],
            "grant_digest": grant["grant_digest"],
        }
    )

    with pytest.raises(ValueError, match="sandbox grant must match"):
        decode_snapshot(json.dumps(document).encode("utf-8"))


def test_snapshot_decode_rejects_oversized_input_before_json_parse() -> None:
    with pytest.raises(ValueError, match="too large"):
        decode_snapshot(b" " * (4 * 1024 * 1024 + 1))


def test_deterministic_repository_lease_is_nonblocking() -> None:
    repository = DeterministicAutomationRepository(_snapshot())

    with repository.try_acquire(), pytest.raises(AutomationRepositoryBusyError):
        repository.try_acquire()


def test_compare_and_swap_has_one_winner() -> None:
    repository = DeterministicAutomationRepository(_snapshot())
    winner = replace(
        _snapshot(),
        revision=1,
        snapshot_token="snapshot-token-0001",
    )

    with repository.try_acquire():
        repository.compare_and_swap(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot=winner,
        )

    with repository.try_acquire(), pytest.raises(AutomationRepositoryConflictError):
        repository.compare_and_swap(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot=replace(
                winner,
                snapshot_token="snapshot-token-loser",
            ),
        )

    assert repository.load() == winner


def test_unknown_after_commit_requires_reload_instead_of_retry() -> None:
    repository = DeterministicAutomationRepository(_snapshot())
    committed = replace(
        _snapshot(),
        revision=1,
        snapshot_token="snapshot-token-0001",
    )
    repository.arm_commit_fault(DeterministicCommitFault.AFTER_COMMIT)

    with repository.try_acquire(), pytest.raises(AutomationRepositoryUnknownCommitError):
        repository.compare_and_swap(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot=committed,
        )

    assert repository.load() == committed


def test_unknown_before_commit_preserves_the_previous_snapshot() -> None:
    original = _snapshot()
    repository = DeterministicAutomationRepository(original)
    repository.arm_commit_fault(DeterministicCommitFault.BEFORE_COMMIT)

    with repository.try_acquire(), pytest.raises(AutomationRepositoryUnknownCommitError):
        repository.compare_and_swap(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot=replace(
                original,
                revision=1,
                snapshot_token="snapshot-token-0001",
            ),
        )

    assert repository.load() == original

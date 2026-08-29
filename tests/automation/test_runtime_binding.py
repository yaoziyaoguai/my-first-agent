from __future__ import annotations

import json

import pytest

from agent.runtime.checkpoint import (
    CheckpointInvariantError,
    CheckpointVersionError,
    LocalCheckpointStore,
)
from agent.runtime.contracts import (
    BackgroundOccurrenceBindingV1,
    ConversationState,
    ModelResponse,
    ModelTextBlock,
    PersistedModelResponseV1,
    ProviderCallIntentV1,
    SubmitMessage,
)
from agent.runtime.state import (
    accept_action,
    begin_provider_call,
    claim_run,
    record_provider_response,
)
from agent.scheduler.caller import create_or_load_occurrence_store
from agent.scheduler.contracts import ScheduledOccurrence, SchedulerError


def _binding(**overrides: object) -> BackgroundOccurrenceBindingV1:
    values: dict[str, object] = {
        "automation_id": "automation:nightly-report",
        "automation_revision": 1,
        "occurrence_id": "occurrence:0000",
        "occurrence_index": 0,
        "scheduled_for_utc": "2026-08-28T00:00:00Z",
        "definition_digest": "1" * 64,
        "grant_digest": "2" * 64,
        "claim_authority_digest": "3" * 64,
        "claim_capability_digest": "4" * 64,
        "checkpoint_identity_digest": "5" * 64,
        "deadline_utc": "2026-08-28T00:10:00Z",
        "model_call_limit": 4,
        "tool_call_limit": 8,
        "sandbox_command_limit": 2,
        "browser_action_limit": 3,
        "max_input_tokens": 20_000,
        "max_output_tokens": 4_000,
    }
    values.update(overrides)
    return BackgroundOccurrenceBindingV1.create(**values)


def _occurrence(binding: BackgroundOccurrenceBindingV1 | None):
    return ScheduledOccurrence(
        schedule_id="nightly-report",
        occurrence_id="occurrence:0000",
        scheduled_for_utc="2026-08-28T00:00:00Z",
        message="Build the bounded report.",
        workspace_scope_digest="6" * 64,
        background_binding=binding,
    )


def _provider_boundary_state(*, with_response: bool) -> ConversationState:
    initial = ConversationState.new(
        "conversation:background",
        background_occurrence_binding=_binding(),
    )
    action = SubmitMessage(
        conversation_id=initial.conversation_id,
        action_seq=1,
        expected_revision=0,
        run_id="run:background",
        message="Build the bounded report.",
    )
    accepted = accept_action(initial, action).state
    claimed = claim_run(accepted, "invocation:one")
    intent = ProviderCallIntentV1.create(
        action_seq=1,
        provider_call_index=1,
        context_digest="a" * 64,
        disclosure_digest=None,
        occurrence_binding_digest=_binding().binding_digest,
    )
    executing = begin_provider_call(claimed, intent, input_tokens=123)
    if not with_response:
        return executing
    return record_provider_response(
        executing,
        PersistedModelResponseV1.create(
            request_digest=intent.request_digest,
            response=ModelResponse((ModelTextBlock("bounded result"),)),
        ),
    )


def test_background_binding_round_trips_in_current_checkpoint(tmp_path) -> None:
    binding = _binding()
    path = tmp_path / "checkpoint.json"
    store = LocalCheckpointStore.initialize(
        path,
        ConversationState.new("conversation:background", background_occurrence_binding=binding),
    )

    assert store.load().state.background_occurrence_binding == binding
    assert json.loads(path.read_text())["schema_version"] == 8


def test_background_binding_rejects_extra_checkpoint_member(tmp_path) -> None:
    binding = _binding()
    path = tmp_path / "checkpoint.json"
    LocalCheckpointStore.initialize(
        path,
        ConversationState.new("conversation:background", background_occurrence_binding=binding),
    )
    document = json.loads(path.read_text())
    document["state"]["background_occurrence_binding"]["raw_capability"] = "forged"
    path.write_text(json.dumps(document))

    with pytest.raises(CheckpointVersionError):
        LocalCheckpointStore(path).load()


def test_binding_digest_covers_declared_budget_and_authority() -> None:
    original = _binding()

    assert _binding(model_call_limit=5).binding_digest != original.binding_digest
    assert _binding(claim_authority_digest="a" * 64).binding_digest != original.binding_digest
    assert "raw_capability" not in original.__dataclass_fields__


def test_scheduler_initializes_background_binding_only_when_explicitly_supplied(
    tmp_path,
) -> None:
    ordinary_root = tmp_path / "ordinary"
    bound_root = tmp_path / "bound"
    ordinary_root.mkdir(mode=0o700)
    bound_root.mkdir(mode=0o700)
    ordinary_store, _ = create_or_load_occurrence_store(
        _occurrence(None),
        state_root=ordinary_root,
    )
    bound_store, _ = create_or_load_occurrence_store(
        _occurrence(_binding()),
        state_root=bound_root,
    )

    assert ordinary_store.load().state.background_occurrence_binding is None
    assert bound_store.load().state.background_occurrence_binding == _binding()


def test_existing_checkpoint_rejects_background_binding_drift(tmp_path) -> None:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    create_or_load_occurrence_store(_occurrence(_binding()), state_root=root)

    with pytest.raises(SchedulerError, match="identity conflict"):
        create_or_load_occurrence_store(
            _occurrence(_binding(grant_digest="a" * 64)),
            state_root=root,
        )


@pytest.mark.parametrize("with_response", [False, True])
def test_provider_boundary_round_trips_in_current_checkpoint(
    tmp_path,
    with_response: bool,
) -> None:
    state = _provider_boundary_state(with_response=with_response)
    store = LocalCheckpointStore.initialize(tmp_path / "checkpoint.json", state)

    assert store.load().state == state


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("request_digest", "c" * 64),
        ("intent_digest", "d" * 64),
    ],
)
def test_checkpoint_rejects_mutated_provider_intent(
    tmp_path,
    field: str,
    replacement: str,
) -> None:
    path = tmp_path / "checkpoint.json"
    LocalCheckpointStore.initialize(
        path,
        _provider_boundary_state(with_response=True),
    )
    document = json.loads(path.read_text())
    document["state"]["active_run"]["provider_call_intent"][field] = replacement
    path.write_text(json.dumps(document))

    with pytest.raises(CheckpointInvariantError):
        LocalCheckpointStore(path).load()


def test_checkpoint_rejects_mutated_persisted_model_response(tmp_path) -> None:
    path = tmp_path / "checkpoint.json"
    LocalCheckpointStore.initialize(
        path,
        _provider_boundary_state(with_response=True),
    )
    document = json.loads(path.read_text())
    document["state"]["active_run"]["persisted_model_response"]["response"][
        "blocks"
    ][0]["text"] = "forged result"
    path.write_text(json.dumps(document))

    with pytest.raises(CheckpointInvariantError):
        LocalCheckpointStore(path).load()

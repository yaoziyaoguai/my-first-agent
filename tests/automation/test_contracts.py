from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from agent.automation.contracts import (
    AutomationBudgetsV1,
    AutomationDefinitionBodyV1,
    AutomationDefinitionV1,
    AutomationRecordV1,
    AutomationScheduleV1,
    AutomationSnapshotV1,
    AutomationStatus,
    BackgroundAuthorityGrantV1,
    CatchUpRule,
    ExecutionMode,
    OccurrenceSummaryV1,
    ScheduleKind,
)


def _digest(character: str) -> str:
    return character * 64


def _schedule() -> AutomationScheduleV1:
    return AutomationScheduleV1(
        kind=ScheduleKind.FIXED_INTERVAL_UTC,
        anchor_utc="2026-08-28T00:00:00Z",
        interval_seconds=3_600,
        catch_up=CatchUpRule.LATEST_ONE,
        misfire_grace_seconds=300,
    )


def _budgets() -> AutomationBudgetsV1:
    return AutomationBudgetsV1(
        occurrence_deadline_seconds=600,
        model_calls=4,
        tool_calls=8,
        sandbox_commands=2,
        browser_actions=3,
        max_input_tokens=20_000,
        max_output_tokens=4_000,
    )


def _body(**overrides: object) -> AutomationDefinitionBodyV1:
    values: dict[str, object] = {
        "automation_id": "automation:nightly-report",
        "revision": 1,
        "label": "Nightly report",
        "task_text": "Build the bounded nightly report.",
        "source_workspace_binding_digest": _digest("1"),
        "execution_mode": ExecutionMode.FRESH_OCCURRENCE,
        "provider_descriptor_digest": _digest("2"),
        "trust_profile_digest": _digest("3"),
        "credential_environment_name": "MODEL_API_KEY",
        "provider_disclosure_request_digest": _digest("4"),
        "schedule": _schedule(),
        "required_start_utc": "2026-08-28T00:00:00Z",
        "expires_at_utc": "2026-09-28T00:00:00Z",
        "max_occurrences": 30,
        "budgets": _budgets(),
        "source_snapshot_digest": _digest("5"),
        "background_environment_policy_digest": _digest("6"),
        "browser_origin_policy_digest": _digest("7"),
        "wake_adapter_policy_digest": _digest("8"),
    }
    values.update(overrides)
    return AutomationDefinitionBodyV1(**values)


def _definition(**body_overrides: object) -> AutomationDefinitionV1:
    body = _body(**body_overrides)
    grant = BackgroundAuthorityGrantV1.create(
        body=body,
        activation_preview_digest=_digest("9"),
        sandbox_confined=True,
        browser_public_observe=True,
    )
    return AutomationDefinitionV1.create(body=body, grant=grant)


def test_definition_digest_binds_every_authority_field() -> None:
    original = _definition()
    changed_body = replace(
        original.body,
        budgets=replace(original.body.budgets, tool_calls=9, budgets_digest=""),
        definition_body_digest="",
    )
    changed = AutomationDefinitionV1.create(
        body=changed_body,
        grant=BackgroundAuthorityGrantV1.create(
            body=changed_body,
            activation_preview_digest=_digest("9"),
            sandbox_confined=True,
            browser_public_observe=True,
        ),
    )

    assert changed.body.definition_body_digest != original.body.definition_body_digest
    assert changed.grant.grant_digest != original.grant.grant_digest
    assert changed.definition_digest != original.definition_digest


def test_grant_cannot_bind_a_different_definition_body() -> None:
    original = _definition()
    drifted_body = _body(task_text="Different task")

    with pytest.raises(ValueError, match="definition body"):
        AutomationDefinitionV1.create(body=drifted_body, grant=original.grant)


def test_grant_and_definition_bind_the_activation_preview() -> None:
    body = _body()
    first = BackgroundAuthorityGrantV1.create(
        body=body,
        activation_preview_digest=_digest("9"),
        sandbox_confined=True,
        browser_public_observe=True,
    )
    second = BackgroundAuthorityGrantV1.create(
        body=body,
        activation_preview_digest=_digest("a"),
        sandbox_confined=True,
        browser_public_observe=True,
    )

    assert first.grant_digest != second.grant_digest
    assert AutomationDefinitionV1.create(body=body, grant=first).definition_digest != (
        AutomationDefinitionV1.create(body=body, grant=second).definition_digest
    )


def test_contracts_are_immutable() -> None:
    definition = _definition()

    with pytest.raises(FrozenInstanceError):
        definition.body.label = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("occurrence_deadline_seconds", 29),
        ("occurrence_deadline_seconds", 3_601),
        ("model_calls", 0),
        ("model_calls", 17),
        ("tool_calls", 0),
        ("tool_calls", 33),
        ("sandbox_commands", -1),
        ("sandbox_commands", 17),
        ("browser_actions", -1),
        ("browser_actions", 33),
        ("max_input_tokens", 0),
        ("max_input_tokens", 100_001),
        ("max_output_tokens", 0),
        ("max_output_tokens", 20_001),
    ],
)
def test_budget_bounds_fail_closed(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field):
        replace(_budgets(), **{field: value})


@pytest.mark.parametrize("field", ["task_text", "credential_value", "workspace_path"])
def test_external_summary_has_no_private_or_host_path_field(field: str) -> None:
    assert field not in OccurrenceSummaryV1.__dataclass_fields__


def test_whole_second_utc_is_required() -> None:
    with pytest.raises(ValueError, match="canonical UTC"):
        replace(_schedule(), anchor_utc="2026-08-28T00:00:00.100Z")

    assert datetime.strptime(_schedule().anchor_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    ) == datetime(2026, 8, 28, tzinfo=UTC)


def test_once_schedule_forbids_an_interval() -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        AutomationScheduleV1(
            kind=ScheduleKind.ONCE_UTC,
            anchor_utc="2026-08-28T00:00:00Z",
            interval_seconds=60,
            catch_up=CatchUpRule.NONE,
            misfire_grace_seconds=0,
        )


def test_no_tool_definition_has_an_explicit_empty_grant() -> None:
    budgets = replace(
        _budgets(),
        sandbox_commands=0,
        browser_actions=0,
        budgets_digest="",
    )
    body = _body(
        budgets=budgets,
        background_environment_policy_digest=None,
        browser_origin_policy_digest=None,
    )

    definition = AutomationDefinitionV1.create_from_body(
        body,
        activation_preview_digest=_digest("9"),
        sandbox_confined=False,
        browser_public_observe=False,
    )

    assert definition.grant.sandbox_confined is False
    assert definition.grant.browser_public_observe is False


def test_needs_human_record_must_pause_future_scheduling() -> None:
    with pytest.raises(ValueError, match="needs-human record must be paused"):
        AutomationRecordV1(
            definition=_definition(),
            status=AutomationStatus.ACTIVE,
            next_occurrence_index=0,
            terminal_occurrence_count=0,
            needs_human_reason="model_outcome_unknown",
            active_claim=None,
            terminal_history=(),
        )


def test_snapshot_enforces_the_nonterminal_automation_bound() -> None:
    records = tuple(
        AutomationRecordV1(
            definition=_definition(automation_id=f"automation:{index:02d}"),
            status=AutomationStatus.ACTIVE,
            next_occurrence_index=0,
            terminal_occurrence_count=0,
            needs_human_reason=None,
            active_claim=None,
            terminal_history=(),
        )
        for index in range(33)
    )

    with pytest.raises(ValueError, match="32 non-terminal"):
        AutomationSnapshotV1(
            revision=1,
            snapshot_token="snapshot-token-0001",
            records=records,
            tombstones=(),
        )

from __future__ import annotations

import pytest

from agent.automation.cli import decode_reconcile_request
from agent.automation.reconcile import ReconcileAutomationsV1


def test_trigger_payload_has_only_schema_and_optional_delivery_identity() -> None:
    request = decode_reconcile_request(
        '{"delivery_id":"delivery:one","schema_version":1}'
    )

    assert request == ReconcileAutomationsV1(delivery_id="delivery:one")
    assert set(ReconcileAutomationsV1.__dataclass_fields__) == {
        "schema_version",
        "delivery_id",
    }


@pytest.mark.parametrize(
    "field",
    ["state_root", "workspace_path", "task", "provider", "credential", "tool"],
)
def test_trigger_payload_rejects_every_authority_or_locator_field(field: str) -> None:
    with pytest.raises(ValueError, match="fields must be exact"):
        decode_reconcile_request(
            f'{{"schema_version":1,"delivery_id":null,"{field}":"forbidden"}}'
        )


def test_trigger_payload_rejects_duplicate_and_noncanonical_json() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        decode_reconcile_request(
            '{"schema_version":1,"schema_version":1,"delivery_id":null}'
        )
    with pytest.raises(ValueError, match="canonical"):
        decode_reconcile_request('{"schema_version": 1, "delivery_id": null}')

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from agent.runtime.ports import ModelAttemptBudgetExhaustedError
from agent.transport_audit import TransportAttemptLedger


def _claim_one_model_attempt(path: str) -> str:
    try:
        TransportAttemptLedger(Path(path), max_model_attempts=1).record(
            "model", "https://provider.example/v1"
        )
    except ModelAttemptBudgetExhaustedError:
        return "exhausted"
    return "recorded"


def test_transport_attempt_ledger_is_payload_free_and_append_only(tmp_path: Path) -> None:
    path = tmp_path / "transport-attempts.jsonl"
    ledger = TransportAttemptLedger(path)

    ledger.record("model", "https://provider.example/v1")
    ledger.record("web", "https://api.tavily.com")

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records == [
        {
            "schema": "first-agent/transport-attempt/v1",
            "kind": "model",
            "destination_digest": hashlib.sha256(
                b"https://provider.example/v1"
            ).hexdigest(),
        },
        {
            "schema": "first-agent/transport-attempt/v1",
            "kind": "web",
            "destination_digest": hashlib.sha256(
                b"https://api.tavily.com"
            ).hexdigest(),
        },
    ]
    encoded = path.read_text(encoding="utf-8")
    assert "provider.example" not in encoded
    assert "api.tavily.com" not in encoded


def test_transport_attempt_ledger_rejects_symlink_target(tmp_path: Path) -> None:
    real = tmp_path / "real.jsonl"
    real.write_text("sentinel\n", encoding="utf-8")
    link = tmp_path / "link.jsonl"
    link.symlink_to(real)

    with pytest.raises(OSError):
        TransportAttemptLedger(link).record("model", "https://provider.example")

    assert real.read_text(encoding="utf-8") == "sentinel\n"


def test_transport_attempt_ledger_blocks_model_dispatch_at_cumulative_limit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "transport-attempts.jsonl"
    ledger = TransportAttemptLedger(path, max_model_attempts=2)

    ledger.record("model", "https://provider.example/v1")
    ledger.record("web", "https://search.example/v1")
    ledger.record("model", "https://provider.example/v1")

    with pytest.raises(ModelAttemptBudgetExhaustedError):
        TransportAttemptLedger(path, max_model_attempts=2).record(
            "model", "https://provider.example/v1"
        )

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["kind"] for record in records] == ["model", "web", "model"]


def test_transport_attempt_ledger_reserves_the_last_budget_across_processes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "transport-attempts.jsonl"

    with ProcessPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(_claim_one_model_attempt, [str(path)] * 4))

    assert outcomes.count("recorded") == 1
    assert outcomes.count("exhausted") == 3
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_transport_attempt_ledger_rejects_corruption_without_appending(
    tmp_path: Path,
) -> None:
    path = tmp_path / "transport-attempts.jsonl"
    path.write_text("not-json\n", encoding="utf-8")
    path.chmod(0o600)
    before = path.read_bytes()

    with pytest.raises(OSError, match="malformed"):
        TransportAttemptLedger(path, max_model_attempts=2).record(
            "model", "https://provider.example/v1"
        )

    assert path.read_bytes() == before


def test_transport_attempt_ledger_rejects_a_non_private_parent(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    path = shared / "transport-attempts.jsonl"

    with pytest.raises(OSError, match="parent"):
        TransportAttemptLedger(path, max_model_attempts=2).record(
            "model", "https://provider.example/v1"
        )

    assert not path.exists()

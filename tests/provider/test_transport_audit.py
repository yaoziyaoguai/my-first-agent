from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent.transport_audit import TransportAttemptLedger


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

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent.runtime.checkpoint import (
    CheckpointInvariantError,
    CheckpointMalformedError,
    CheckpointMissingError,
    CheckpointSecurityError,
    CheckpointVersionError,
    LocalCheckpointStore,
)
from agent.runtime.contracts import ConversationState


def _write_fixture(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o600)


def test_missing_malformed_and_invalid_are_distinct_and_byte_stable(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "state.json"
    with pytest.raises(CheckpointMissingError):
        LocalCheckpointStore(missing).load()

    malformed = tmp_path / "malformed" / "state.json"
    _write_fixture(malformed, b"{not-json")
    original = malformed.read_bytes()
    with pytest.raises(CheckpointMalformedError):
        LocalCheckpointStore(malformed).load()
    assert malformed.read_bytes() == original

    valid = tmp_path / "invalid" / "state.json"
    LocalCheckpointStore.initialize(valid, ConversationState.new("conversation-1"))
    document = json.loads(valid.read_text(encoding="utf-8"))
    document["state"]["revision"] = -1
    _write_fixture(valid, json.dumps(document).encode())
    invalid_bytes = valid.read_bytes()
    with pytest.raises(CheckpointInvariantError):
        LocalCheckpointStore(valid).load()
    assert valid.read_bytes() == invalid_bytes


def test_version_and_unknown_fields_fail_closed(tmp_path: Path) -> None:
    version_path = tmp_path / "version" / "state.json"
    LocalCheckpointStore.initialize(version_path, ConversationState.new("conversation-1"))
    version_doc = json.loads(version_path.read_text(encoding="utf-8"))
    version_doc["schema_version"] = 99
    _write_fixture(version_path, json.dumps(version_doc).encode())
    with pytest.raises(CheckpointVersionError):
        LocalCheckpointStore(version_path).load()

    unknown_path = tmp_path / "unknown" / "state.json"
    LocalCheckpointStore.initialize(unknown_path, ConversationState.new("conversation-1"))
    unknown_doc = json.loads(unknown_path.read_text(encoding="utf-8"))
    unknown_doc["state"]["surprise"] = True
    _write_fixture(unknown_path, json.dumps(unknown_doc).encode())
    with pytest.raises(CheckpointVersionError, match="unknown fields"):
        LocalCheckpointStore(unknown_path).load()


def test_semantically_invalid_active_run_is_rejected_without_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "semantic" / "state.json"
    LocalCheckpointStore.initialize(path, ConversationState.new("conversation-1"))
    document = json.loads(path.read_text(encoding="utf-8"))
    document["state"]["active_run"] = {
        "run_id": "run-1",
        "status": "runnable",
        "phase": "tool",
        "owner_invocation_id": None,
        "batch_cursor": 0,
        "pending_request": None,
        "executing_intent": None,
        "tool_calls": [],
        "approval_grant": None,
        "approved_request_ids": [],
        "rejected_request_ids": [],
    }
    _write_fixture(path, json.dumps(document).encode())
    original = path.read_bytes()

    with pytest.raises(CheckpointInvariantError, match="valid current tool call"):
        LocalCheckpointStore(path).load()

    assert path.read_bytes() == original


def test_symlink_and_multi_link_state_fail_security_checks(tmp_path: Path) -> None:
    real_path = tmp_path / "real" / "state.json"
    LocalCheckpointStore.initialize(real_path, ConversationState.new("conversation-1"))

    symlink_path = tmp_path / "link" / "state.json"
    symlink_path.parent.mkdir(mode=0o700)
    symlink_path.symlink_to(real_path)
    with pytest.raises(CheckpointSecurityError):
        LocalCheckpointStore(symlink_path).load()

    hardlink_path = tmp_path / "hard" / "state.json"
    hardlink_path.parent.mkdir(mode=0o700)
    os.link(real_path, hardlink_path)
    with pytest.raises(CheckpointSecurityError, match="link count"):
        LocalCheckpointStore(real_path).load()

"""018 Task 7：owner-only download quarantine 的 durable closed contract。"""

import os

import pytest

from agent.browser.quarantine import (
    DOWNLOAD_MAX_BYTES,
    BrowserQuarantine,
    BrowserQuarantineError,
)


def test_store_inspect_delete_keeps_download_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "browser-download.tmp"
    source.write_bytes(b"download payload")
    quarantine = BrowserQuarantine(tmp_path / "state" / "browser-quarantine")

    receipt = quarantine.store(
        source,
        session_ref="session-0123456789abcdef",
        action_digest="a" * 64,
        browser_identity_digest="b" * 64,
        source_origin="https://site.example.test",
        suggested_name="../../report.txt",
        mime_type="text/plain",
    )

    assert receipt.quarantine_id.startswith("download-")
    assert receipt.normalized_name.startswith(receipt.quarantine_id)
    assert receipt.suggested_name_digest != "../../report.txt"
    assert receipt.byte_size == len(b"download payload")
    assert len(receipt.sha256) == 64
    assert not any(workspace.iterdir())
    assert oct((tmp_path / "state" / "browser-quarantine").stat().st_mode & 0o777) == "0o700"
    assert quarantine.inspect(receipt) == receipt

    quarantine.delete(receipt)
    with pytest.raises(BrowserQuarantineError, match="download is unavailable"):
        quarantine.inspect(receipt)


def test_store_rejects_symlink_and_oversize_without_consumable_receipt(tmp_path):
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
    target = tmp_path / "target"
    target.write_bytes(b"secret")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(BrowserQuarantineError, match="regular no-follow file"):
        quarantine.store(
            link,
            session_ref="session-0123456789abcdef",
            action_digest="a" * 64,
            browser_identity_digest="b" * 64,
            source_origin="https://site.example.test",
            suggested_name="secret.txt",
            mime_type="text/plain",
        )
    outside_directory = tmp_path / "outside-directory"
    outside_directory.mkdir()
    (outside_directory / "payload").write_bytes(b"outside")
    linked_directory = tmp_path / "linked-directory"
    linked_directory.symlink_to(outside_directory, target_is_directory=True)
    with pytest.raises(BrowserQuarantineError, match="regular no-follow file"):
        quarantine.store(
            linked_directory / "payload",
            session_ref="session-0123456789abcdef",
            action_digest="a" * 64,
            browser_identity_digest="b" * 64,
            source_origin="https://site.example.test",
            suggested_name="outside.txt",
            mime_type="text/plain",
        )

    oversized = tmp_path / "oversized"
    with oversized.open("wb") as stream:
        stream.truncate(DOWNLOAD_MAX_BYTES + 1)
    with pytest.raises(BrowserQuarantineError, match="download exceeds"):
        quarantine.store(
            oversized,
            session_ref="session-0123456789abcdef",
            action_digest="a" * 64,
            browser_identity_digest="b" * 64,
            source_origin="https://site.example.test",
            suggested_name="large.bin",
            mime_type="application/octet-stream",
        )


def test_store_never_overwrites_an_existing_opaque_download(tmp_path, monkeypatch):
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    monkeypatch.setattr(
        "agent.browser.quarantine.secrets.token_hex", lambda _bytes: "1" * 16
    )
    common = {
        "session_ref": "session-0123456789abcdef",
        "action_digest": "a" * 64,
        "browser_identity_digest": "b" * 64,
        "source_origin": "https://site.example.test",
        "suggested_name": "file.bin",
        "mime_type": "application/octet-stream",
    }
    receipt = quarantine.store(first, **common)

    with pytest.raises(BrowserQuarantineError, match="already exists"):
        quarantine.store(second, **common)

    assert quarantine.inspect(receipt) == receipt


def test_quarantine_root_rejects_symlinked_parent_without_writing_outside(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-state"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(BrowserQuarantineError, match="real directory"):
        BrowserQuarantine(linked_parent / "browser-quarantine")

    assert list(outside.iterdir()) == []


def test_clear_session_removes_only_exact_session_downloads(tmp_path):
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    common = {
        "action_digest": "a" * 64,
        "browser_identity_digest": "b" * 64,
        "source_origin": "https://site.example.test",
        "suggested_name": "file.bin",
        "mime_type": "application/octet-stream",
    }
    one = quarantine.store(first, session_ref="session-1111111111111111", **common)
    two = quarantine.store(second, session_ref="session-2222222222222222", **common)

    quarantine.clear_session("session-1111111111111111")
    with pytest.raises(BrowserQuarantineError):
        quarantine.inspect(one)
    assert quarantine.inspect(two) == two
    assert os.path.commonpath([str(tmp_path), str(quarantine.root)]) == str(tmp_path)


def test_clear_session_rejects_replaced_session_directory_without_following(tmp_path):
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
    source = tmp_path / "source"
    source.write_bytes(b"payload")
    session_ref = "session-1111111111111111"
    quarantine.store(
        source,
        session_ref=session_ref,
        action_digest="a" * 64,
        browser_identity_digest="b" * 64,
        source_origin="https://site.example.test",
        suggested_name="file.bin",
        mime_type="application/octet-stream",
    )
    session_directory = next((quarantine.root / "downloads").iterdir())
    original = tmp_path / "original-session"
    session_directory.rename(original)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "must-remain"
    victim.write_bytes(b"not quarantine data")
    session_directory.symlink_to(outside, target_is_directory=True)

    with pytest.raises(BrowserQuarantineError):
        quarantine.clear_session(session_ref)

    assert victim.read_bytes() == b"not quarantine data"

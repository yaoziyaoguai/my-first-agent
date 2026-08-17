from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent.web.profile import (
    TAVILY_DESTINATION,
    TAVILY_TRUST_NOTICE_DIGEST,
    TAVILY_TRUST_NOTICE_ID,
    WebProfileError,
    WebProfileV1,
    load_web_profile,
    save_web_profile,
    web_profile_path,
)


def _profile(**overrides) -> WebProfileV1:
    values = {
        "credential_env": "FIRST_AGENT_WEB_API_KEY",
        "timeout_seconds": 10.0,
        "max_results": 5,
    }
    values.update(overrides)
    return WebProfileV1(**values)


def test_web_profile_round_trip_is_owner_only_atomic_and_non_secret(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    profile = _profile()

    path = save_web_profile(state_root, profile)

    assert path == web_profile_path(state_root)
    assert load_web_profile(state_root) == profile
    assert path.stat().st_mode & 0o777 == 0o600
    assert state_root.stat().st_mode & 0o777 == 0o700
    serialized = path.read_text(encoding="utf-8")
    assert "FIRST_AGENT_WEB_API_KEY" in serialized
    assert "credential" not in json.loads(serialized)
    assert "secret-value" not in serialized


def test_web_profile_has_only_fixed_tavily_public_input_contract() -> None:
    profile = _profile()

    assert profile.provider == "tavily"
    assert profile.destination == TAVILY_DESTINATION
    assert profile.search_depth == "basic"
    assert profile.extract_depth == "basic"
    assert profile.trust_notice_id == TAVILY_TRUST_NOTICE_ID
    assert profile.trust_notice_digest == TAVILY_TRUST_NOTICE_DIGEST
    assert len(profile.profile_digest) == 64

    with pytest.raises(WebProfileError):
        _profile(destination="https://example.com")
    with pytest.raises(WebProfileError):
        _profile(search_depth="advanced")
    with pytest.raises(WebProfileError):
        _profile(max_results=21)
    with pytest.raises(WebProfileError):
        _profile(credential_env="BAD-NAME")


def test_web_profile_load_is_strict_and_rejects_tamper(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    path = save_web_profile(state_root, _profile())
    document = json.loads(path.read_text(encoding="utf-8"))
    document["unknown"] = True
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(WebProfileError, match="unknown or missing"):
        load_web_profile(state_root)

    del document["unknown"]
    document["profile_digest"] = "0" * 64
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(WebProfileError, match="digest"):
        load_web_profile(state_root)


def test_web_profile_rejects_symlink_hardlink_and_unsafe_mode(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    path = save_web_profile(state_root, _profile())
    alias = tmp_path / "alias"
    alias.symlink_to(state_root, target_is_directory=True)
    with pytest.raises(WebProfileError, match="symlink"):
        load_web_profile(alias)

    hardlink = tmp_path / "web-profile-hardlink.json"
    os.link(path, hardlink)
    with pytest.raises(WebProfileError, match="single hard link"):
        load_web_profile(state_root)
    hardlink.unlink()

    path.chmod(0o644)
    with pytest.raises(WebProfileError, match="0600"):
        load_web_profile(state_root)


def test_missing_web_profile_is_explicitly_disabled(tmp_path: Path) -> None:
    assert load_web_profile(tmp_path / "missing") is None

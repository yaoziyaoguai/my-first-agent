"""013 U1 — ProviderProfileV1 non-secret profile 合同测试。

覆盖:strict schema、round-trip、owner-only/no-follow/single-link、atomic write、
normalization、控制字符拒绝、FakeProvider 不可持久化、AgentProviderConfig 投影。
"""

from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path

import pytest

from agent.provider.config import AgentProviderConfig
from agent.provider.profile import (
    PROFILE_FILE_NAME,
    ProviderProfileError,
    ProviderProfileV1,
    load_provider_profile,
    profile_path,
    save_provider_profile,
    to_provider_config,
)

SECRET_SENTINEL = "sk-super-secret-credential-value-013"


def _profile(**overrides) -> ProviderProfileV1:
    fields = {
        "provider_type": "openai_compatible",
        "model": "everyday-model",
        "base_url": "https://provider.example",
        "credential_env": "FIRST_AGENT_API_KEY",
        "thinking_mode": None,
        "request_path": None,
        "strict_tools": False,
        "timeout_seconds": 30.0,
    }
    fields.update(overrides)
    return ProviderProfileV1(**fields)


@pytest.fixture()
def state_root(tmp_path: Path) -> Path:
    return tmp_path / "state" / "v1"


class TestRoundTripAndNormalization:
    def test_round_trip_preserves_fields(self, state_root: Path) -> None:
        saved = _profile()
        save_provider_profile(state_root, saved)
        loaded = load_provider_profile(state_root)
        assert loaded == saved

    def test_base_url_trailing_slash_and_model_whitespace_normalized(
        self, state_root: Path
    ) -> None:
        profile = _profile(base_url="https://provider.example/api/", model="  m1  ")
        assert profile.base_url == "https://provider.example/api"
        assert profile.model == "m1"

    def test_missing_profile_loads_as_none(self, state_root: Path) -> None:
        assert load_provider_profile(state_root) is None

    def test_profile_path_is_fixed_file_name(self, state_root: Path) -> None:
        assert profile_path(state_root) == state_root / PROFILE_FILE_NAME
        assert PROFILE_FILE_NAME == "provider-profile.json"

    def test_anthropic_profile_round_trip(self, state_root: Path) -> None:
        saved = _profile(provider_type="anthropic_compatible")
        save_provider_profile(state_root, saved)
        assert load_provider_profile(state_root) == saved


class TestNoSecretContract:
    def test_profile_has_no_credential_field(self) -> None:
        profile = _profile()
        assert not hasattr(profile, "credential")
        assert "credential" not in {
            name for name in dir(profile) if not name.startswith("_")
        } - {"credential_env"}

    def test_serialized_file_contains_only_allowlisted_keys(self, state_root: Path) -> None:
        save_provider_profile(state_root, _profile())
        payload = json.loads(profile_path(state_root).read_text(encoding="utf-8"))
        assert set(payload) == {
            "schema_version",
            "provider_type",
            "model",
            "base_url",
            "credential_env",
            "thinking_mode",
            "request_path",
            "strict_tools",
            "timeout_seconds",
        }
        assert payload["schema_version"] == 1

    def test_serialized_file_never_contains_ambient_secret(
        self, state_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FIRST_AGENT_API_KEY", SECRET_SENTINEL)
        save_provider_profile(state_root, _profile())
        raw = profile_path(state_root).read_text(encoding="utf-8")
        assert SECRET_SENTINEL not in raw
        assert "Authorization" not in raw


class TestStrictSchema:
    def _write_raw(self, state_root: Path, payload: dict) -> None:
        save_provider_profile(state_root, _profile())
        path = profile_path(state_root)
        path.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(path, 0o600)

    def _valid_payload(self) -> dict:
        return {
            "schema_version": 1,
            "provider_type": "openai_compatible",
            "model": "everyday-model",
            "base_url": "https://provider.example",
            "credential_env": "FIRST_AGENT_API_KEY",
            "thinking_mode": None,
            "request_path": None,
            "strict_tools": False,
            "timeout_seconds": 30.0,
        }

    def test_unknown_field_rejected(self, state_root: Path) -> None:
        payload = self._valid_payload() | {"proxy": "http://127.0.0.1:8080"}
        self._write_raw(state_root, payload)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)

    def test_missing_field_rejected(self, state_root: Path) -> None:
        payload = self._valid_payload()
        del payload["credential_env"]
        self._write_raw(state_root, payload)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("schema_version", 2),
            ("schema_version", "1"),
            ("schema_version", True),
            ("provider_type", 5),
            ("model", None),
            ("base_url", ["https://provider.example"]),
            ("credential_env", 7),
            ("thinking_mode", "enabled"),
            ("thinking_mode", True),
            ("request_path", 7),
            ("strict_tools", "yes"),
            ("timeout_seconds", "30"),
            ("timeout_seconds", True),
            ("timeout_seconds", None),
        ],
    )
    def test_type_or_value_invalid_rejected(
        self, state_root: Path, field: str, value
    ) -> None:
        payload = self._valid_payload() | {field: value}
        self._write_raw(state_root, payload)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)

    def test_non_object_document_rejected(self, state_root: Path) -> None:
        save_provider_profile(state_root, _profile())
        path = profile_path(state_root)
        path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
        os.chmod(path, 0o600)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)

    def test_truncated_document_rejected(self, state_root: Path) -> None:
        save_provider_profile(state_root, _profile())
        path = profile_path(state_root)
        raw = path.read_text(encoding="utf-8")
        path.write_text(raw[: len(raw) // 2], encoding="utf-8")
        os.chmod(path, 0o600)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)

    def test_oversize_document_rejected(self, state_root: Path) -> None:
        save_provider_profile(state_root, _profile())
        path = profile_path(state_root)
        payload = self._valid_payload() | {"model": "m" * 200_000}
        path.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(path, 0o600)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)


class TestFileSafety:
    def test_saved_file_is_owner_only_regular_single_link(self, state_root: Path) -> None:
        save_provider_profile(state_root, _profile())
        info = profile_path(state_root).lstat()
        assert stat.S_ISREG(info.st_mode)
        assert stat.S_IMODE(info.st_mode) == 0o600
        assert info.st_nlink == 1
        assert info.st_uid == os.getuid()
        root_info = state_root.lstat()
        assert stat.S_IMODE(root_info.st_mode) == 0o700

    def test_symlink_profile_file_fails_closed(self, state_root: Path, tmp_path: Path) -> None:
        save_provider_profile(state_root, _profile())
        target = tmp_path / "elsewhere.json"
        target.write_text(
            profile_path(state_root).read_text(encoding="utf-8"), encoding="utf-8"
        )
        os.chmod(target, 0o600)
        profile_path(state_root).unlink()
        profile_path(state_root).symlink_to(target)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)

    def test_symlink_state_root_component_fails_closed(
        self, state_root: Path, tmp_path: Path
    ) -> None:
        save_provider_profile(state_root, _profile())
        alias = tmp_path / "alias-root"
        alias.symlink_to(state_root)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(alias)
        with pytest.raises(ProviderProfileError):
            save_provider_profile(alias, _profile())

    def test_unsafe_file_mode_fails_closed(self, state_root: Path) -> None:
        save_provider_profile(state_root, _profile())
        os.chmod(profile_path(state_root), 0o644)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)

    def test_unsafe_parent_mode_fails_closed(self, state_root: Path) -> None:
        save_provider_profile(state_root, _profile())
        os.chmod(state_root, 0o755)
        try:
            with pytest.raises(ProviderProfileError):
                load_provider_profile(state_root)
        finally:
            os.chmod(state_root, 0o700)

    def test_wrong_owner_fails_closed(
        self, state_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_provider_profile(state_root, _profile())
        real_uid = os.getuid()
        monkeypatch.setattr(os, "getuid", lambda: real_uid + 1)
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)

    def test_hard_linked_profile_fails_closed(self, state_root: Path, tmp_path: Path) -> None:
        save_provider_profile(state_root, _profile())
        os.link(profile_path(state_root), tmp_path / "hardlink.json")
        with pytest.raises(ProviderProfileError):
            load_provider_profile(state_root)

    def test_interrupted_replace_leaves_previous_profile_loadable(
        self, state_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = _profile(model="original-model")
        save_provider_profile(state_root, original)

        def broken_replace(*args, **kwargs):
            raise OSError("simulated crash before atomic replace")

        monkeypatch.setattr(os, "replace", broken_replace)
        with pytest.raises((ProviderProfileError, OSError)):
            save_provider_profile(state_root, _profile(model="next-model"))
        monkeypatch.undo()
        assert load_provider_profile(state_root) == original
        leftovers = [
            entry
            for entry in os.listdir(state_root)
            if entry != PROFILE_FILE_NAME
        ]
        assert leftovers == []

    def test_failed_file_fsync_removes_hidden_temporary_profile(
        self, state_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            os,
            "fsync",
            lambda _fd: (_ for _ in ()).throw(OSError("simulated file fsync failure")),
        )

        with pytest.raises(OSError, match="simulated file fsync failure"):
            save_provider_profile(state_root, _profile())

        assert os.listdir(state_root) == []


class TestFieldValidation:
    @pytest.mark.parametrize(
        "base_url",
        [
            "http://provider.example",
            "https://user:pass@provider.example",
            "https://provider.example?x=1",
            "https://provider.example#frag",
            "ftp://provider.example",
            "https://",
            "provider.example",
            "https://provider.example/\x00",
            "https://provider.example/\x1b[31m",
            "https://[broken",
            "https://provider.example:not-a-port",
            "https://provider.example:99999",
            "",
        ],
    )
    def test_invalid_base_url_rejected(self, base_url: str) -> None:
        with pytest.raises(ProviderProfileError):
            _profile(base_url=base_url)

    @pytest.mark.parametrize(
        "base_url",
        [
            "https://provider.example",
            "https://provider.example:8443/api",
            "http://127.0.0.1:8080",
            "http://localhost:9999",
        ],
    )
    def test_valid_base_url_accepted(self, base_url: str) -> None:
        assert _profile(base_url=base_url).base_url == base_url

    @pytest.mark.parametrize("model", ["", "   ", "a\x00b", "a\nb", "m" * 300])
    def test_invalid_model_rejected(self, model: str) -> None:
        with pytest.raises(ProviderProfileError):
            _profile(model=model)

    @pytest.mark.parametrize(
        "env_name",
        ["", "BAD NAME", "1BAD", "A=B", "A\x00B", "PATH!", "E" * 200],
    )
    def test_invalid_credential_env_rejected(self, env_name: str) -> None:
        with pytest.raises(ProviderProfileError):
            _profile(credential_env=env_name)

    def test_fake_provider_cannot_be_persisted(self) -> None:
        with pytest.raises(ProviderProfileError):
            _profile(provider_type="fake")

    def test_unknown_provider_type_rejected(self) -> None:
        with pytest.raises(ProviderProfileError):
            _profile(provider_type="mystery")

    def test_thinking_mode_disabled_requires_openai_compatible(self) -> None:
        assert (
            _profile(thinking_mode="disabled").thinking_mode == "disabled"
        )
        with pytest.raises(ProviderProfileError):
            _profile(provider_type="anthropic_compatible", thinking_mode="disabled")

    def test_strict_tools_and_request_path_require_openai_compatible(self) -> None:
        profile = _profile(
            request_path="/chat/completions",
            strict_tools=True,
        )
        assert profile.request_path == "/chat/completions"
        assert profile.strict_tools is True
        with pytest.raises(ProviderProfileError):
            _profile(provider_type="anthropic_compatible", strict_tools=True)

    @pytest.mark.parametrize(
        "request_path",
        ["", "chat/completions", "//other", "/a?b", "/a#b", "/a\n"],
    )
    def test_invalid_request_path_rejected(self, request_path: str) -> None:
        with pytest.raises(ProviderProfileError):
            _profile(request_path=request_path)

    @pytest.mark.parametrize(
        "timeout", [0.0, -1.0, math.inf, math.nan, 100_000.0]
    )
    def test_invalid_timeout_rejected(self, timeout: float) -> None:
        with pytest.raises(ProviderProfileError):
            _profile(timeout_seconds=timeout)


class TestProviderConfigProjection:
    def test_projection_builds_remote_provider_config(self) -> None:
        profile = _profile(
            thinking_mode="disabled",
            request_path="/chat/completions",
            strict_tools=True,
            timeout_seconds=45.0,
        )
        config = to_provider_config(profile, credential=SECRET_SENTINEL)
        assert isinstance(config, AgentProviderConfig)
        assert config.provider_type == "openai_compatible"
        assert config.model == "everyday-model"
        assert config.base_url == "https://provider.example"
        assert config.credential == SECRET_SENTINEL
        assert config.timeout == 45.0
        assert config.thinking_mode == "disabled"
        assert config.request_path == "/chat/completions"
        assert config.strict_tools is True
        assert config.endpoint == "https://provider.example/chat/completions"
        descriptor = config.descriptor()
        assert descriptor.remote is True
        assert descriptor.family == "openai_compatible"

    def test_projection_without_credential_for_descriptor_only(self) -> None:
        config = to_provider_config(_profile(), credential=None)
        assert config.credential is None
        assert config.descriptor().model == "everyday-model"

    @pytest.mark.parametrize(
        ("provider_type", "base_url", "expected"),
        [
            (
                "openai_compatible",
                "https://provider.example",
                "https://provider.example/v1/chat/completions",
            ),
            (
                "openai_compatible",
                "https://provider.example/v1",
                "https://provider.example/v1/chat/completions",
            ),
            (
                "anthropic_compatible",
                "https://provider.example/v1",
                "https://provider.example/v1/messages",
            ),
            (
                "openai_compatible",
                "https://gateway.example/api/v1",
                "https://gateway.example/api/v1/chat/completions",
            ),
        ],
    )
    def test_projection_does_not_duplicate_root_v1_path(
        self, provider_type: str, base_url: str, expected: str
    ) -> None:
        config = AgentProviderConfig(
            provider_type=provider_type,
            model="model-1",
            base_url=base_url,
        )

        assert config.endpoint == expected

"""013 日常入口：一次 non-secret setup，之后在 cwd 无参数启动。"""

from __future__ import annotations

from pathlib import Path

import pytest

import main as entrypoint
from agent.continuity import sessions
from agent.memory.store import MemoryStore
from agent.provider.fake_provider import FakeProvider
from agent.provider.profile import (
    ProviderProfileV1,
    load_provider_profile,
    save_provider_profile,
)


def _profile(**overrides) -> ProviderProfileV1:
    values = {
        "provider_type": "openai_compatible",
        "model": "saved-model",
        "base_url": "https://saved.example/v1",
        "credential_env": "SAVED_PROVIDER_KEY",
        "thinking_mode": None,
        "request_path": None,
        "strict_tools": False,
        "timeout_seconds": 31.0,
    }
    values.update(overrides)
    return ProviderProfileV1(**values)


def test_setup_saves_profile_without_session_provider_or_credential_read(
    tmp_path: Path, monkeypatch
) -> None:
    state_root = tmp_path / "state-root"
    monkeypatch.setenv("SETUP_PROVIDER_KEY", "secret-that-must-not-be-read-or-written")
    monkeypatch.setattr(
        entrypoint,
        "open_workspace_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("setup must not open a conversation")
        ),
    )
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("setup must not construct or call a provider")
        ),
    )
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "setup",
            "--provider",
            "openai_compatible",
            "--model",
            "daily-model",
            "--base-url",
            "https://provider.example/v1/",
            "--credential-env",
            "SETUP_PROVIDER_KEY",
            "--request-path",
            "/chat/completions",
            "--strict-tools",
            "--state-root",
            str(state_root),
        ],
        write_fn=output.append,
    )

    assert exit_code == 0
    profile = load_provider_profile(state_root)
    assert profile is not None
    assert profile.model == "daily-model"
    assert profile.base_url == "https://provider.example/v1"
    assert profile.credential_env == "SETUP_PROVIDER_KEY"
    assert profile.request_path == "/chat/completions"
    assert profile.strict_tools is True
    raw = (state_root / "provider-profile.json").read_text(encoding="utf-8")
    assert "secret-that-must-not-be-read-or-written" not in raw
    rendered = "\n".join(output)
    assert "Secret values were not stored" in rendered
    assert "SETUP_PROVIDER_KEY" in rendered
    assert "secret-that-must-not-be-read-or-written" not in rendered


def test_no_profile_exits_before_checkpoint_or_provider_io(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        entrypoint,
        "open_workspace_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("missing profile must stop before checkpoint I/O")
        ),
    )
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("missing profile must stop before provider I/O")
        ),
    )
    output: list[str] = []

    exit_code = entrypoint.main(
        ["--state-root", str(tmp_path / "missing-state")],
        write_fn=output.append,
    )

    assert exit_code == 2
    assert len(output) == 1
    assert output[0].startswith("First Agent is not configured.")
    assert "first-agent setup" in output[0]
    assert "--provider" in output[0]


def test_no_argument_start_uses_saved_profile_and_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "daily-workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    state_root = entrypoint.default_state_root(home)
    monkeypatch.setattr(entrypoint, "default_state_root", lambda: state_root)
    monkeypatch.setattr(sessions, "default_state_root", lambda _home=None: state_root)
    save_provider_profile(state_root, _profile())
    monkeypatch.setenv("SAVED_PROVIDER_KEY", "fixture-secret")
    monkeypatch.chdir(workspace)
    captured = []
    captured_limits = []
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda config: captured.append(config) or FakeProvider(),
    )
    build_composition = entrypoint.build_composition

    def capture_composition(**kwargs):
        captured_limits.append(kwargs["invocation_limits"])
        return build_composition(**kwargs)

    monkeypatch.setattr(entrypoint, "build_composition", capture_composition)
    output: list[str] = []

    exit_code = entrypoint.main([], input_fn=lambda _: "/exit", write_fn=output.append)

    assert exit_code == 0
    assert len(captured) == 1
    assert captured[0].provider_type == "openai_compatible"
    assert captured[0].model == "saved-model"
    assert captured[0].base_url == "https://saved.example/v1"
    assert captured[0].credential == "fixture-secret"
    assert captured[0].request_path == "/v1/chat/completions"
    assert captured[0].strict_tools is False
    assert len(captured_limits) == 1
    assert captured_limits[0].max_invalid_repairs == 4
    assert tuple(state_root.glob("workspaces/*/*.json"))
    rendered = "\n".join(output)
    assert "First Agent is ready in: daily-workspace" in rendered
    assert "openai_compatible" in rendered and "saved-model" in rendered
    assert str(state_root) not in rendered


def test_main_composition_uses_memory_scope_without_weakening_workspace_identity(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    memory_path = tmp_path / "memory" / "store.json"
    memory_path.parent.mkdir(mode=0o700)
    context_scope = entrypoint.workspace_scope_digest_for(workspace)
    store = MemoryStore.create(
        memory_path,
        workspace_scope_digest=context_scope,
        profile=entrypoint.provider_trust_profile(
            profile_id="default",
            provider_family="fake",
            destination="local",
        ),
    )
    store.remember("the release marker is ORCHID-014")

    contexts = []
    original_generate = FakeProvider.generate

    def capture_generate(self, context):
        contexts.append(context)
        return original_generate(self, context)

    monkeypatch.setattr(FakeProvider, "generate", capture_generate)
    inputs = iter(("what is the release marker", "/exit"))

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
            "--memory-store",
            str(memory_path),
        ],
        input_fn=lambda _prompt: next(inputs),
        write_fn=lambda _message: None,
    )

    assert exit_code == 0
    assert len(contexts) == 1
    assert "ORCHID-014" in repr(contexts[0].messages)
    assert contexts[0].goal_bootstrap is not None
    assert contexts[0].goal_bootstrap.workspace_identity_digest.startswith("workspace:v1:")


@pytest.mark.parametrize(
    "base_url",
    [
        "https://[broken",
        "https://provider.example:not-a-port",
        "https://provider.example:99999",
    ],
)
def test_setup_rejects_malformed_base_url_without_traceback_or_profile(
    tmp_path: Path, base_url: str
) -> None:
    state_root = tmp_path / "state-root"
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "setup",
            "--provider",
            "openai_compatible",
            "--model",
            "model-1",
            "--base-url",
            base_url,
            "--state-root",
            str(state_root),
        ],
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == ["Setup failed: ProviderProfileError: base URL is malformed"]
    assert not (state_root / "provider-profile.json").exists()


def test_ready_output_escapes_workspace_terminal_controls(tmp_path: Path) -> None:
    workspace = tmp_path / "daily\n\x1b[2J-workspace"
    workspace.mkdir()
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(tmp_path / "state-root"),
            "--provider",
            "fake",
        ],
        input_fn=lambda _prompt: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 0
    rendered = "\n".join(output)
    assert "\x1b" not in rendered
    assert "\\u000a" in rendered
    assert "\\u001b" in rendered


def test_complete_explicit_provider_group_overrides_profile(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    save_provider_profile(state_root, _profile())
    monkeypatch.setenv("EXPLICIT_KEY", "explicit-secret")
    captured = []
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda config: captured.append(config) or FakeProvider(),
    )

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "anthropic_compatible",
            "--model",
            "explicit-model",
            "--base-url",
            "https://explicit.example/anthropic",
            "--credential-env",
            "EXPLICIT_KEY",
        ],
        input_fn=lambda _: "/exit",
        write_fn=lambda _message: None,
    )

    assert exit_code == 0
    assert len(captured) == 1
    assert captured[0].provider_type == "anthropic_compatible"
    assert captured[0].model == "explicit-model"
    assert captured[0].base_url == "https://explicit.example/anthropic"
    assert captured[0].credential == "explicit-secret"


def test_partial_explicit_provider_group_never_merges_with_profile(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    save_provider_profile(state_root, _profile())
    monkeypatch.setattr(
        entrypoint,
        "open_workspace_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("partial provider config must fail before checkpoint I/O")
        ),
    )
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--model",
            "must-not-merge",
        ],
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == [
        "Startup failed: ValueError: explicit provider configuration must include "
        "--provider, --model, and --base-url together"
    ]


def test_explicit_fake_remains_available_without_a_saved_profile(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    inputs = iter(("hello", "/exit"))
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
        ],
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
    )

    assert exit_code == 0
    assert "hello" in output


def test_missing_credential_reports_only_selected_environment_name(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    save_provider_profile(
        state_root,
        _profile(credential_env="NOT_CONFIGURED_013_KEY"),
    )
    monkeypatch.delenv("NOT_CONFIGURED_013_KEY", raising=False)
    output: list[str] = []

    exit_code = entrypoint.main(
        ["--workspace", str(workspace), "--state-root", str(state_root)],
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == [
        "Startup failed: ValueError: credential environment variable is not set: "
        "NOT_CONFIGURED_013_KEY"
    ]

from __future__ import annotations

from pathlib import Path

import main as entrypoint
from agent.provider.profile import load_provider_profile


def test_no_argument_setup_guides_non_secret_fields_and_gives_one_next_step(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setenv("GUIDED_MODEL_KEY", "secret-must-not-be-read")
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("setup must not construct a provider")
        ),
    )
    answers = iter(
        (
            "openai_compatible",
            "guided-model",
            "https://provider.example/v1",
            "GUIDED_MODEL_KEY",
        )
    )
    prompts: list[str] = []
    output: list[str] = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    exit_code = entrypoint.main(
        ["setup", "--state-root", str(state_root)],
        input_fn=answer,
        write_fn=output.append,
    )

    assert exit_code == 0
    profile = load_provider_profile(state_root)
    assert profile is not None
    assert profile.provider_type == "openai_compatible"
    assert profile.model == "guided-model"
    assert profile.base_url == "https://provider.example/v1"
    assert profile.credential_env == "GUIDED_MODEL_KEY"
    assert profile.request_path is None
    assert profile.thinking_mode == "disabled"
    assert profile.strict_tools is False
    assert len(prompts) == 4
    rendered = "\n".join(output)
    assert "export GUIDED_MODEL_KEY=" in rendered
    assert "first-agent" in rendered
    assert "secret-must-not-be-read" not in rendered
    assert "ProviderProfileError" not in rendered


def test_guided_setup_cancel_writes_nothing(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    output: list[str] = []

    exit_code = entrypoint.main(
        ["setup", "--state-root", str(state_root)],
        input_fn=lambda _prompt: (_ for _ in ()).throw(EOFError),
        write_fn=output.append,
    )

    assert exit_code == 2
    assert not (state_root / "provider-profile.json").exists()
    assert output == ["Setup cancelled; no configuration was saved."]


def test_partial_noninteractive_setup_fails_without_prompt_or_exception_type(
    tmp_path: Path,
) -> None:
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "setup",
            "--provider",
            "openai_compatible",
            "--state-root",
            str(tmp_path / "state"),
        ],
        input_fn=lambda _prompt: (_ for _ in ()).throw(
            AssertionError("partial automation settings must not prompt")
        ),
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == [
        "Setup needs --provider, --model, and --base-url together, or no options for guided setup."
    ]

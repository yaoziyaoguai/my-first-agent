from __future__ import annotations

from pathlib import Path

import main as entrypoint
from agent.web.profile import TAVILY_DESTINATION, WebProfileV1, load_web_profile, save_web_profile


def test_no_argument_web_setup_discloses_and_requires_current_confirmation(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    output: list[str] = []

    exit_code = entrypoint.main(
        ["setup-web", "--state-root", str(state_root)],
        input_fn=lambda prompt: "yes" if "Enable" in prompt else "no",
        write_fn=output.append,
    )

    assert exit_code == 0
    profile = load_web_profile(state_root)
    assert profile is not None
    assert profile.credential_env == "FIRST_AGENT_WEB_API_KEY"
    rendered = "\n".join(output)
    assert TAVILY_DESTINATION in rendered
    assert "third party" in rendered.lower() or "第三方" in rendered
    assert "FIRST_AGENT_WEB_API_KEY" in rendered
    assert "export FIRST_AGENT_WEB_API_KEY=" in rendered
    assert "first-agent" in rendered


def test_rejected_web_setup_writes_nothing(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    output: list[str] = []

    exit_code = entrypoint.main(
        ["setup-web", "--state-root", str(state_root)],
        input_fn=lambda _prompt: "no",
        write_fn=output.append,
    )

    assert exit_code == 1
    assert not (state_root / "web-profile.json").exists()
    assert output[-1] == "Web setup cancelled; no configuration was saved."


def test_complete_automation_web_setup_requires_explicit_yes(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "setup-web",
            "--credential-env",
            "AUTOMATION_WEB_KEY",
            "--timeout",
            "12",
            "--max-results",
            "4",
            "--state-root",
            str(state_root),
        ],
        input_fn=lambda _prompt: (_ for _ in ()).throw(
            AssertionError("automation flags must not enter guided prompt")
        ),
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == ["Automated Web setup requires --yes after reviewing Tavily handling."]
    assert not (state_root / "web-profile.json").exists()


def test_missing_web_credential_preserves_local_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    save_web_profile(
        state_root,
        WebProfileV1(credential_env="MISSING_016_WEB_KEY"),
    )
    monkeypatch.delenv("MISSING_016_WEB_KEY", raising=False)
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--provider",
            "fake",
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
        ],
        input_fn=lambda _prompt: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 0
    rendered = "\n".join(output)
    assert "Web: temporarily unavailable" in rendered
    assert "MISSING_016_WEB_KEY" in rendered
    assert "Startup failed" not in rendered

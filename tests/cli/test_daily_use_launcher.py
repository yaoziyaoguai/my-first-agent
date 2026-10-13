from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

LAUNCHER = (
    Path(__file__).parents[2]
    / "docs"
    / "handoffs"
    / "2026-09-13-daily-use-repair-v3"
    / "launch_deepseek.py"
)


def test_launcher_executes_installed_entry_with_minimal_environment(tmp_path: Path) -> None:
    secure = tmp_path / "secure"
    secure.mkdir(mode=0o700)
    key_file = secure / "deepseek.key"
    key_file.write_text("sk-synthetic123\n", encoding="ascii")
    key_file.chmod(0o600)
    capture = tmp_path / "capture.json"
    fake_entry = tmp_path / "first-agent"
    fake_entry.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv, 'env': dict(os.environ)}}, open({str(capture)!r}, 'w'))\n",
        encoding="utf-8",
    )
    fake_entry.chmod(fake_entry.stat().st_mode | stat.S_IXUSR)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    ledger = secure / "attempts.jsonl"
    environment = dict(os.environ)
    environment["UNRELATED_SECRET"] = "must-not-cross-exec"

    completed = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            "--first-agent",
            str(fake_entry),
            "--key-file",
            str(key_file),
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--audit-ledger",
            str(ledger),
            "--max-model-attempts",
            "8",
            "--project-path",
            "config",
            "--without-owner-preferences",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""
    captured = json.loads(capture.read_text(encoding="utf-8"))
    assert captured["env"]["FIRST_AGENT_DOGFOOD_API_KEY"] == "sk-synthetic123"
    assert "UNRELATED_SECRET" not in captured["env"]
    assert captured["argv"][1:] == [
        "--workspace",
        str(workspace),
        "--state-root",
        str(state_root),
        "--provider",
        "openai_compatible",
        "--model",
        "deepseek-v4-flash",
        "--base-url",
        "https://api.deepseek.com",
        "--request-path",
        "/chat/completions",
        "--credential-env",
        "FIRST_AGENT_DOGFOOD_API_KEY",
        "--thinking-mode",
        "disabled",
        "--timeout",
        "90",
        "--transport-audit-ledger",
        str(ledger),
        "--max-model-attempts",
        "8",
        "--project-path",
        "config",
        "--without-owner-preferences",
    ]


def test_launcher_rejects_insecure_key_without_disclosing_it(tmp_path: Path) -> None:
    secure = tmp_path / "secure"
    secure.mkdir(mode=0o700)
    key_file = secure / "deepseek.key"
    key_file.write_text("sk-do-not-display\n", encoding="ascii")
    key_file.chmod(0o644)
    fake_entry = tmp_path / "first-agent"
    fake_entry.write_text(f"#!{sys.executable}\n", encoding="utf-8")
    fake_entry.chmod(fake_entry.stat().st_mode | stat.S_IXUSR)

    completed = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            "--first-agent",
            str(fake_entry),
            "--key-file",
            str(key_file),
            "--workspace",
            str(tmp_path / "workspace"),
            "--state-root",
            str(tmp_path / "state"),
            "--audit-ledger",
            str(secure / "attempts.jsonl"),
            "--max-model-attempts",
            "8",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "credential file unavailable or unsafe" in completed.stderr
    assert "sk-do-not-display" not in completed.stderr

"""LLM Processing MVP tests.

The MVP must be auditable without storing raw input text in runs/*.jsonl and
must be runnable with a fake provider when no real key is configured.
"""

from __future__ import annotations

import json
from pathlib import Path

from llm.cli import main as process_cli_main
from llm.pipeline import process_file
from llm.providers import FakeProvider
from run_logger import LLM_CALL_ALLOWED_FIELDS, RunLogger


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_process_file_fake_provider_logs_llm_calls_without_raw_text(tmp_path):
    input_text = "SECRET_RAW_TEXT should never be written to the run jsonl."
    input_path = tmp_path / "input.txt"
    input_path.write_text(input_text, encoding="utf-8")
    logger = RunLogger(
        state_path=tmp_path / "state.json",
        runs_dir=tmp_path / "runs",
        run_id="test-run",
    )

    result = process_file(
        input_path,
        provider=FakeProvider(),
        logger=logger,
    )

    assert result.status == "ok"
    assert result.run_path == tmp_path / "runs" / "test-run.jsonl"
    run_log = result.run_path.read_text(encoding="utf-8")
    assert "SECRET_RAW_TEXT" not in run_log

    events = _read_jsonl(result.run_path)
    llm_calls = [entry for entry in events if entry["event"] == "llm_call"]
    assert [entry["payload"]["prompt_version"] for entry in llm_calls] == [
        "triager.v1",
        "distiller.v1",
        "linker.v1",
    ]

    for entry in llm_calls:
        payload = entry["payload"]
        assert set(payload) == LLM_CALL_ALLOWED_FIELDS
        assert payload["provider"] == "fake"
        assert payload["model"] == "fake-llm"
        assert payload["input_file_hash"] == result.input_file_hash
        assert payload["status"] == "ok"
        assert payload["error"] is None


def test_process_command_uses_fake_provider_without_real_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MY_FIRST_AGENT_LLM_PROVIDER", raising=False)
    input_path = tmp_path / "note.txt"
    input_path.write_text("raw process command input", encoding="utf-8")
    state_path = tmp_path / "state.json"
    runs_dir = tmp_path / "runs"

    exit_code = process_cli_main(
        [
            str(input_path),
            "--state-path",
            str(state_path),
            "--runs-dir",
            str(runs_dir),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert Path(output["run_path"]).exists()
    assert state_path.exists()
    assert "raw process command input" not in Path(output["run_path"]).read_text(
        encoding="utf-8"
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "ok"
    assert state["input_file_hash"] == output["input_file_hash"]
    assert state["last_run_id"] == output["run_id"]


def test_main_process_dispatch_does_not_start_interactive_session(
    tmp_path,
    monkeypatch,
    capsys,
):
    from main import main

    input_path = tmp_path / "input.txt"
    input_path.write_text("dispatch input", encoding="utf-8")

    called = {"init": False}

    def fail_if_interactive_session_starts():
        called["init"] = True
        raise AssertionError("interactive session should not start")

    monkeypatch.setattr("main.init_session", fail_if_interactive_session_starts)

    exit_code = main(
        [
            "process",
            str(input_path),
            "--state-path",
            str(tmp_path / "state.json"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    assert exit_code == 0
    assert called["init"] is False
    assert json.loads(capsys.readouterr().out)["status"] == "ok"

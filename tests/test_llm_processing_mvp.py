"""LLM Processing MVP tests.

The MVP must be auditable without storing raw input text in runs/*.jsonl and
must be runnable with a fake provider when no real key is configured.
"""

from __future__ import annotations

import json
from pathlib import Path

from llm.audit import STATUS_SCHEMA_VERSION, build_status, scan_inputs
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
            "process",
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


def test_provider_preflight_fake_passes_without_real_key(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MY_FIRST_AGENT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    exit_code = process_cli_main(["preflight"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["status"] == "ok"
    assert output["provider"] == {"configured": True, "name": "fake"}
    assert output["api_key"]["status"] == "not_required"
    assert output["model"]["configured"] is True
    assert output["base_url"]["configured"] is False
    assert output["live"] == {"enabled": False, "status": "not_requested"}
    assert not (tmp_path / "state.json").exists()
    assert not (tmp_path / "runs").exists()


def test_provider_preflight_missing_key_is_readable_error(monkeypatch, capsys):
    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    exit_code = process_cli_main(["preflight"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["status"] == "error"
    assert output["api_key"] == {"env": "ANTHROPIC_API_KEY", "status": "missing"}
    assert "api_key_missing:ANTHROPIC_API_KEY" in output["errors"]


def test_provider_preflight_redacts_present_key(monkeypatch, capsys):
    secret_key = "SECRET_ANTHROPIC_KEY_VALUE"
    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret_key)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")

    exit_code = process_cli_main(["preflight"])

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert exit_code in {0, 1}
    assert secret_key not in output_text
    assert "https://example.invalid" not in output_text
    assert output["api_key"] == {"env": "ANTHROPIC_API_KEY", "status": "present"}
    assert output["base_url"] == {"configured": True}
    assert output["model"]["name"] == "claude-test"


def test_provider_preflight_missing_model_is_explicit(monkeypatch, capsys):
    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SECRET_KEY")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("MY_FIRST_AGENT_LLM_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("MY_FIRST_AGENT_LLM_BASE_URL", raising=False)

    exit_code = process_cli_main(["preflight"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["status"] == "error"
    assert output["model"] == {"configured": False, "name": None, "source": None}
    assert "model_missing:anthropic" in output["errors"]
    assert "base_url_missing:anthropic" in output["warnings"]


def test_provider_preflight_unknown_provider_is_explicit(monkeypatch, capsys):
    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "unknown-provider")

    exit_code = process_cli_main(["preflight"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["status"] == "error"
    assert output["provider"] == {"configured": False, "name": "unknown-provider"}
    assert "unknown_provider:unknown-provider" in output["errors"]


def test_provider_preflight_does_not_persist_secret_or_prompt(
    tmp_path,
    monkeypatch,
    capsys,
):
    secret_key = "SECRET_PREFLIGHT_KEY"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret_key)

    process_cli_main(["preflight"])

    output_text = capsys.readouterr().out
    assert secret_key not in output_text
    assert "Provider connectivity preflight" not in output_text
    assert not (tmp_path / "state.json").exists()
    assert not (tmp_path / "runs").exists()


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


def test_main_preflight_dispatch_does_not_start_interactive_session(
    monkeypatch,
    capsys,
):
    from main import main

    called = {"init": False}

    def fail_if_interactive_session_starts():
        called["init"] = True
        raise AssertionError("interactive session should not start")

    monkeypatch.setattr("main.init_session", fail_if_interactive_session_starts)

    exit_code = main(["preflight", "--provider", "fake"])

    assert exit_code == 0
    assert called["init"] is False
    assert json.loads(capsys.readouterr().out)["provider"]["name"] == "fake"


def test_scan_inputs_reports_metadata_without_persisting_raw_text(tmp_path):
    secret = "SCAN_SECRET_RAW_TEXT"
    input_path = tmp_path / "input.txt"
    input_path.write_text(secret, encoding="utf-8")

    entries = scan_inputs(tmp_path)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.path == str(input_path.resolve())
    assert entry.size == len(secret)
    assert entry.input_file_hash
    assert not (tmp_path / "state.json").exists()
    assert not (tmp_path / "runs").exists()
    assert secret not in entry.__dict__.values()


def test_scan_command_outputs_metadata_only(tmp_path, capsys):
    secret = "SCAN_COMMAND_SECRET"
    input_path = tmp_path / "input.txt"
    input_path.write_text(secret, encoding="utf-8")

    exit_code = process_cli_main(["scan", str(input_path)])

    assert exit_code == 0
    output_text = capsys.readouterr().out
    assert secret not in output_text
    output = json.loads(output_text)
    assert output["inputs"][0]["path"] == str(input_path.resolve())
    assert output["inputs"][0]["size"] == len(secret)


def test_status_handles_missing_state_and_runs(tmp_path):
    status = build_status(
        state_path=tmp_path / "missing-state.json",
        runs_dir=tmp_path / "missing-runs",
    )

    assert status["latest_run"]["run_id"] is None
    assert status["llm_calls"] == []
    assert "state_missing" in status["warnings"]
    assert "runs_missing_or_empty" in status["warnings"]


def test_status_default_output_schema_is_stable(tmp_path):
    state_path = tmp_path / "state.json"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_path = runs_dir / "run-stable.jsonl"
    state_path.write_text(
        json.dumps(
            {
                "last_run_id": "run-stable",
                "status": "ok",
                "input_file_hash": "stable-hash",
                "run_path": str(run_path),
            }
        ),
        encoding="utf-8",
    )
    run_path.write_text(
        "\n".join(
            [
                json.dumps({"event": "process_started", "payload": {}}),
                json.dumps(
                    {
                        "event": "llm_call",
                        "payload": {
                            "provider": "fake",
                            "model": "fake-llm",
                            "prompt_version": "triager.v1",
                            "input_file_hash": "stable-hash",
                            "tokens": 4,
                            "latency": 5,
                            "status": "ok",
                            "error": None,
                        },
                    }
                ),
                json.dumps({"event": "process_completed", "payload": {}}),
            ]
        ),
        encoding="utf-8",
    )

    status = build_status(state_path=state_path, runs_dir=runs_dir)

    assert set(status) == {
        "schema_version",
        "query",
        "state_path",
        "runs_dir",
        "latest_run",
        "runs",
        "llm_calls",
        "errors",
        "warnings",
        "allowed_llm_call_fields",
    }
    assert status["schema_version"] == STATUS_SCHEMA_VERSION
    assert status["query"] == {"run_id": None}
    assert status["latest_run"] == {
        "run_id": "run-stable",
        "status": "ok",
        "input_file_hash": "stable-hash",
        "run_path": str(run_path),
        "latest_event": "process_completed",
        "llm_call_count": 1,
    }
    assert status["runs"] == [status["latest_run"]]
    assert status["allowed_llm_call_fields"] == sorted(LLM_CALL_ALLOWED_FIELDS)


def test_status_reads_llm_call_whitelist_and_skips_corrupt_jsonl(tmp_path):
    raw_text = "STATUS_SECRET_RAW_TEXT"
    state_path = tmp_path / "state.json"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_path = runs_dir / "run-1.jsonl"
    state_path.write_text(
        json.dumps(
            {
                "last_run_id": "run-1",
                "status": "ok",
                "input_file_hash": "abc123",
                "run_path": str(run_path),
            }
        ),
        encoding="utf-8",
    )
    run_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "llm_call",
                        "payload": {
                            "provider": "fake",
                            "model": "fake-llm",
                            "prompt_version": "triager.v1",
                            "input_file_hash": "abc123",
                            "tokens": 3,
                            "latency": 1,
                            "status": "ok",
                            "error": None,
                            "raw_text": raw_text,
                        },
                    }
                ),
                "{bad json",
            ]
        ),
        encoding="utf-8",
    )

    status = build_status(state_path=state_path, runs_dir=runs_dir)

    assert raw_text not in json.dumps(status, ensure_ascii=False)
    assert status["latest_run"]["run_id"] == "run-1"
    assert status["llm_calls"] == [
        {
            "provider": "fake",
            "model": "fake-llm",
            "prompt_version": "triager.v1",
            "input_file_hash": "abc123",
            "tokens": 3,
            "latency": 1,
            "status": "ok",
            "error": None,
        }
    ]
    assert any(warning.startswith("invalid_jsonl:") for warning in status["warnings"])


def test_status_run_id_queries_specific_run_without_state_mutation(tmp_path):
    state_path = tmp_path / "state.json"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    state_path.write_text(
        json.dumps(
            {
                "last_run_id": "latest",
                "status": "ok",
                "input_file_hash": "latest-hash",
                "run_path": str(runs_dir / "latest.jsonl"),
            }
        ),
        encoding="utf-8",
    )
    (runs_dir / "latest.jsonl").write_text(
        json.dumps({"event": "process_completed", "payload": {}}),
        encoding="utf-8",
    )
    (runs_dir / "target.jsonl").write_text(
        json.dumps(
            {
                "event": "llm_call",
                "payload": {
                    "provider": "fake",
                    "model": "fake-llm",
                    "prompt_version": "distiller.v1",
                    "input_file_hash": "target-hash",
                    "tokens": 8,
                    "latency": 13,
                    "status": "ok",
                    "error": None,
                },
            }
        ),
        encoding="utf-8",
    )
    before_state = state_path.read_text(encoding="utf-8")

    status = build_status(
        state_path=state_path,
        runs_dir=runs_dir,
        run_id="target",
    )

    assert state_path.read_text(encoding="utf-8") == before_state
    assert status["query"] == {"run_id": "target"}
    assert status["latest_run"]["run_id"] == "target"
    assert status["latest_run"]["status"] is None
    assert status["latest_run"]["input_file_hash"] is None
    assert status["llm_calls"][0]["prompt_version"] == "distiller.v1"


def test_status_run_id_missing_is_stable(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    status = build_status(
        state_path=tmp_path / "missing-state.json",
        runs_dir=runs_dir,
        run_id="does-not-exist",
    )

    assert status["query"] == {"run_id": "does-not-exist"}
    assert status["runs"] == []
    assert status["llm_calls"] == []
    assert status["latest_run"] == {
        "run_id": "does-not-exist",
        "status": None,
        "input_file_hash": None,
        "run_path": None,
        "latest_event": None,
        "llm_call_count": 0,
    }
    assert "run_missing:does-not-exist" in status["warnings"]


def test_status_run_id_rejects_path_traversal(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    outside_log = tmp_path / "outside.jsonl"
    outside_log.write_text(
        json.dumps(
            {
                "event": "llm_call",
                "payload": {
                    "provider": "fake",
                    "model": "fake-llm",
                    "prompt_version": "triager.v1",
                    "input_file_hash": "outside-hash",
                    "tokens": 1,
                    "latency": 1,
                    "status": "ok",
                    "error": None,
                },
            }
        ),
        encoding="utf-8",
    )

    status = build_status(
        state_path=tmp_path / "missing-state.json",
        runs_dir=runs_dir,
        run_id="../outside",
    )

    assert status["runs"] == []
    assert status["llm_calls"] == []
    assert "run_id_invalid:../outside" in status["warnings"]


def test_status_command_outputs_warnings_without_raw_text(tmp_path, capsys):
    raw_text = "STATUS_COMMAND_SECRET"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_path = runs_dir / "latest.jsonl"
    run_path.write_text(
        json.dumps(
            {
                "event": "llm_call",
                "payload": {
                    "provider": "fake",
                    "model": "fake-llm",
                    "prompt_version": "linker.v1",
                    "input_file_hash": "def456",
                    "tokens": 1,
                    "latency": 2,
                    "status": "error",
                    "error": "ProviderError",
                    "completion": raw_text,
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = process_cli_main(
        [
            "status",
            "--state-path",
            str(tmp_path / "missing.json"),
            "--runs-dir",
            str(runs_dir),
        ]
    )

    assert exit_code == 0
    output_text = capsys.readouterr().out
    assert raw_text not in output_text
    output = json.loads(output_text)
    assert output["errors"] == [
        {
            "prompt_version": "linker.v1",
            "error": "ProviderError",
            "status": "error",
        }
    ]


def test_status_command_run_id_outputs_specific_run(tmp_path, capsys):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "chosen.jsonl").write_text(
        json.dumps(
            {
                "event": "llm_call",
                "payload": {
                    "provider": "fake",
                    "model": "fake-llm",
                    "prompt_version": "triager.v1",
                    "input_file_hash": "chosen-hash",
                    "tokens": 1,
                    "latency": 1,
                    "status": "ok",
                    "error": None,
                    "prompt": "MUST_NOT_LEAK",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = process_cli_main(
        [
            "status",
            "--runs-dir",
            str(runs_dir),
            "--state-path",
            str(tmp_path / "missing-state.json"),
            "--run-id",
            "chosen",
        ]
    )

    output_text = capsys.readouterr().out
    assert exit_code == 0
    assert "MUST_NOT_LEAK" not in output_text
    output = json.loads(output_text)
    assert output["query"] == {"run_id": "chosen"}
    assert output["latest_run"]["run_id"] == "chosen"
    assert output["llm_calls"][0]["input_file_hash"] == "chosen-hash"

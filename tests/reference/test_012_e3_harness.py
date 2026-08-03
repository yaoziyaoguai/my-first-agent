from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_012_e3.py"


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env={"PATH": os.environ.get("PATH", ""), **env},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_e3_harness_reports_exact_missing_and_partial_config_without_network() -> None:
    missing = _run({})
    assert missing.returncode == 2
    assert missing.stderr == ""
    assert missing.stdout.strip() == (
        "NEEDS_E3_CONFIG(stage=U8, required=FIRST_AGENT_E3_PROVIDER,"
        "FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)"
    )

    partial = _run({"FIRST_AGENT_E3_PROVIDER": "openai_compatible"})
    assert partial.returncode == 2
    assert partial.stderr == ""
    assert partial.stdout.strip() == "E3_BLOCKED(stage=U8, reason=incomplete_config)"


def test_e3_harness_uses_production_http_runtime_and_contains_no_parallel_fake_path() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert "build_model_provider" in imported
    assert "build_composition" in imported
    assert "LocalCheckpointStore" in imported
    assert "FakeProvider" not in source
    assert "ScriptedProvider" not in source
    assert "CodingLoop" not in source
    assert "AgentRuntime(" not in source  # composition owns the one production Runtime instance


def test_e3_harness_sanitizes_unexpected_internal_error(monkeypatch, capsys) -> None:
    from scripts import run_012_e3

    monkeypatch.setenv("FIRST_AGENT_E3_PROVIDER", "openai_compatible")
    monkeypatch.setenv("FIRST_AGENT_E3_BASE_URL", "https://provider.invalid")
    monkeypatch.setenv("FIRST_AGENT_E3_MODEL", "fixture-model")
    monkeypatch.setenv("FIRST_AGENT_E3_API_KEY", "fixture-key")

    def fail_without_crossing_evidence_boundary(_config) -> None:  # noqa: ANN001
        raise ValueError("private-path-and-response-body")

    monkeypatch.setattr(run_012_e3, "run_e3", fail_without_crossing_evidence_boundary)

    assert run_012_e3.main() == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == "E3_BLOCKED(stage=U8, reason=model_incompatible)\n"


def test_checkpoint_secret_oracle_matches_exact_headers_not_domain_field_substrings() -> None:
    from scripts.run_012_e3 import _checkpoint_contains_forbidden

    assert not _checkpoint_contains_forbidden(
        b'{"goal_authorizations":[],"note":"authorization is governed"}',
        api_key="fixture-secret",
        system_policy="fixture system policy",
    )
    assert _checkpoint_contains_forbidden(
        b'{"authorization":"Bearer fixture"}',
        api_key="fixture-secret",
        system_policy="fixture system policy",
    )
    assert _checkpoint_contains_forbidden(
        b'{"header":"X-API-Key: fixture"}',
        api_key="fixture-secret",
        system_policy="fixture system policy",
    )
    assert _checkpoint_contains_forbidden(
        b'{"value":"fixture-secret"}',
        api_key="fixture-secret",
        system_policy="fixture system policy",
    )
    assert _checkpoint_contains_forbidden(
        b'{"value":"fixture system policy"}',
        api_key="fixture-secret",
        system_policy="fixture system policy",
    )
    escaped_policy = "fixture system policy\nwith a quoted \"instruction\""
    assert _checkpoint_contains_forbidden(
        json.dumps({"nested": {"value": escaped_policy}}).encode(),
        api_key="fixture-secret",
        system_policy=escaped_policy,
    )
    escaped_secret = "fixture-secret\nwith-a-newline"
    assert _checkpoint_contains_forbidden(
        json.dumps({"nested": [escaped_secret]}).encode(),
        api_key=escaped_secret,
        system_policy="fixture system policy",
    )

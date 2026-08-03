from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.provider.protocol import ProviderProtocolError

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_013_e3.py"


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


def test_013_e3_reports_exact_missing_and_partial_config_without_network() -> None:
    missing = _run({})
    assert missing.returncode == 2
    assert missing.stderr == ""
    assert missing.stdout.strip() == (
        "NEEDS_013_E3_CONFIG(required=FIRST_AGENT_E3_PROVIDER,"
        "FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)"
    )

    partial = _run({"FIRST_AGENT_E3_PROVIDER": "openai_compatible"})
    assert partial.returncode == 2
    assert partial.stderr == ""
    assert partial.stdout.strip() == "013_E3_BLOCKED(reason=incomplete_config)"


def test_013_e3_uses_product_main_and_production_http_adapter_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert "build_model_provider" in imported
    assert "LocalCheckpointStore" in imported
    assert "FakeProvider" not in source
    assert "ScriptedProvider" not in source
    assert "MockTransport" not in source
    assert "AgentRuntime(" not in source
    assert "product_main.main(" in source
    assert 'patch.object(\n        product_main, "build_model_provider"' in source
    assert 'product_main, "_build_provider"' not in source
    assert 'product_main.main([], input_fn=driver' in source
    run_product = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_product"
    )
    assert "--state-root" not in ast.unparse(run_product)
    assert 'argv.extend(("--request-path", "/chat/completions", "--strict-tools"))' in source


def test_013_e3_receipt_schema_names_all_twelve_boolean_claims() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    expected = {
        "setup_profile_is_non_secret",
        "no_argument_start_uses_saved_profile_and_cwd",
        "disclosure_has_zero_sends_before_contextual_ack",
        "ask_and_discuss_create_no_goal_or_file_effect",
        "discussion_creates_goal_only_after_artifact_request",
        "goal_is_durable_before_file_effect",
        "contextual_approval_binds_exact_pending_request",
        "artifact_is_read_back_and_verified_done",
        "restart_recovers_same_goal_without_implicit_send_or_effect",
        "existing_workspace_sentinels_are_unchanged",
        "successful_journeys_require_no_continue_action",
        "default_output_exposes_no_protocol_identifier_or_secret",
    }
    tree = ast.parse(source)
    claim_keys = {
        key.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "claims" for target in node.targets)
        and isinstance(node.value, ast.Dict)
        for key in node.value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert claim_keys == expected


def test_013_e3_sanitizes_unexpected_internal_error(monkeypatch, capsys) -> None:
    from scripts import run_013_e3

    monkeypatch.setenv("FIRST_AGENT_E3_PROVIDER", "openai_compatible")
    monkeypatch.setenv("FIRST_AGENT_E3_BASE_URL", "https://provider.invalid")
    monkeypatch.setenv("FIRST_AGENT_E3_MODEL", "fixture-model")
    monkeypatch.setenv("FIRST_AGENT_E3_API_KEY", "fixture-key")

    def fail_without_crossing_evidence_boundary(_config) -> None:  # noqa: ANN001
        raise ValueError("private-path-and-response-body")

    monkeypatch.setattr(run_013_e3, "run_e3", fail_without_crossing_evidence_boundary)

    assert run_013_e3.main() == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == "013_E3_BLOCKED(reason=model_incompatible)\n"


def test_recording_provider_clears_stale_error_after_success() -> None:
    from scripts.run_013_e3 import _RecordingProvider

    class FailThenSucceed:
        calls = 0

        def generate(self, _context):  # noqa: ANN001, ANN201
            self.calls += 1
            if self.calls == 1:
                raise ProviderProtocolError("malformed_control")
            return object()

    provider = _RecordingProvider(FailThenSucceed())
    with pytest.raises(ProviderProtocolError):
        provider.generate(object())

    result = provider.generate(object())

    assert result is not None
    assert provider.last_error is None

from __future__ import annotations

import ast
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from agent.composition import build_web_resources
from agent.provider.protocol import ProviderAuthError, ProviderProtocolError
from agent.runtime.contracts import (
    ContinuationPhase,
    ConversationState,
    EgressClass,
    ExecutionAuthorityClass,
    RecordedRunResult,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
)
from agent.runtime.state import accept_action, mark_executing, start_tool_batch
from agent.web.client import WebAuthError, WebProtocolError, WebRateLimitError
from agent.web.profile import WebProfileV1

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_014_e3.py"

EXPECTED_CLAIMS = {
    "profiles_are_non_secret_and_fixed_destination",
    "history_is_current_workspace_and_identity_bound",
    "cross_workspace_and_private_history_are_absent",
    "workspace_search_is_bounded_and_source_receipted",
    "model_send_waits_for_source_data_class_disclosure",
    "web_search_has_zero_calls_before_exact_approval",
    "web_extract_has_zero_calls_before_exact_approval",
    "tavily_is_the_only_web_destination",
    "search_and_extract_receipt_kinds_are_distinct",
    "hostile_source_changes_no_authority_or_admission",
    "goal_is_durable_before_artifact_write",
    "restart_reuses_only_persisted_observations",
    "artifact_and_manifest_are_read_back_with_three_source_kinds",
    "citation_oracle_rederives_all_linkages",
    "goal_is_verified_done_only_after_citation_evidence",
    "workspace_sentinels_are_unchanged",
    "successful_journeys_require_no_mode_or_continue_action",
    "receipt_and_default_output_expose_no_secret_or_private_path",
    "web_approval_discloses_third_party_handling_and_notice_drift_invalidates_binding",
}


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


def test_014_e3_reports_exact_missing_and_partial_config_without_network() -> None:
    missing = _run({})
    assert missing.returncode == 2
    assert missing.stderr == ""
    assert missing.stdout.strip() == (
        "NEEDS_014_E3_CONFIG(required=FIRST_AGENT_014_E3_PROVIDER,"
        "FIRST_AGENT_014_E3_BASE_URL,FIRST_AGENT_014_E3_MODEL,"
        "FIRST_AGENT_014_E3_API_KEY,FIRST_AGENT_014_E3_WEB_API_KEY)"
    )

    partial = _run({"FIRST_AGENT_014_E3_PROVIDER": "openai_compatible"})
    assert partial.returncode == 2
    assert partial.stderr == ""
    assert partial.stdout.strip() == "014_E3_BLOCKED(reason=incomplete_config)"


def test_014_e3_uses_product_main_and_real_http_adapters_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert "build_model_provider" in imported
    assert "build_web_resources" in imported
    assert "LocalCheckpointStore" in imported
    assert "TavilyClient" not in imported
    assert "FakeProvider" not in source
    assert "ScriptedProvider" not in source
    assert "MockTransport" not in source
    assert "AgentRuntime(" not in source
    assert 'patch.object(product_main, "build_model_provider"' in source
    assert 'patch.object(product_main, "build_web_resources"' in source
    assert 'product_main.main([], input_fn=driver' in source
    assert 'product_main, "_build_provider"' not in source
    assert 'product_main, "build_composition"' not in source
    assert "trust_env=False" in source
    assert "follow_redirects=False" in source


def test_014_e3_baseline_uses_one_bounded_probe_then_reports_limits() -> None:
    from scripts import run_014_e3

    assert "Call list_files exactly once with path '.'" in run_014_e3._BASELINE_PROMPT
    assert (
        "Call history_search exactly once with query 'workspace artifacts'"
        in run_014_e3._BASELINE_PROMPT
    )
    assert "Do not retry either tool" in run_014_e3._BASELINE_PROMPT


def test_014_e3_workspace_journey_freezes_one_bounded_text_search() -> None:
    from scripts import run_014_e3

    assert (
        "Call search_text exactly once with query 'observation date' and root '.'"
        in run_014_e3._ANSWER_PROMPT
    )
    assert "Do not use history tools" in run_014_e3._ANSWER_PROMPT


def test_014_e3_hostile_journey_uses_a_real_workspace_source() -> None:
    from scripts import run_014_e3

    assert run_014_e3._HOSTILE_PATH == "hostile/source-instructions.txt"
    assert "owner_preference_confirm" in run_014_e3._HOSTILE_TEXT
    assert "goal_proposal" in run_014_e3._HOSTILE_TEXT
    assert "DATA-ONLY-014" in run_014_e3._HOSTILE_PROMPT


def test_014_e3_can_inject_post_response_network_unknown_once() -> None:
    from scripts import run_014_e3

    traffic = run_014_e3._WebTraffic(fail_next_response=True)
    request = httpx.Request("POST", "https://api.tavily.com/search")
    response = httpx.Response(200, request=request)

    with pytest.raises(httpx.ReadError):
        traffic.on_response(response)

    assert traffic.statuses == [200]
    assert traffic.failed_responses == 1
    assert traffic.fail_next_response is False


def test_014_e3_crash_hook_persists_executing_before_process_interrupt(tmp_path) -> None:
    from scripts import run_014_e3

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    capture = run_014_e3._SessionCapture(
        crash_after_executing_tool="write_file",
    )
    opened = capture(workspace, state_root=tmp_path / "state")
    assert opened.store is not None and opened.snapshot is not None
    state = opened.snapshot.state
    started = accept_action(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-crash",
            message="write one file",
        ),
    ).state
    batched = start_tool_batch(
        started,
        (ToolCall("write-crash", "write_file", {"path": "notes/crash.md"}),),
    )
    executing = mark_executing(
        batched,
        tool_call_id="write-crash",
        intent_digest="intent-crash",
        idempotency_key="idempotency-crash",
        side_effect=SideEffectClass.WRITE,
        egress=EgressClass.NONE,
        operation="write_file",
        request_identity="idempotency-crash",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    lease = opened.store.try_acquire(state.conversation_id)
    assert lease is not None
    try:
        with pytest.raises(run_014_e3._InjectedProcessCrash):
            opened.store.compare_and_swap(opened.snapshot, executing)
    finally:
        lease.release()

    persisted = opened.store.load().state
    assert persisted.active_run is not None
    assert persisted.active_run.phase is ContinuationPhase.EXECUTING
    assert capture.crashed_after_executing is True


def test_014_e3_artifact_requires_readback_before_manifest_build() -> None:
    from scripts import run_014_e3

    instruction = run_014_e3._ARTIFACT_READBACK_INSTRUCTION
    assert "read the report back before calling build_citation_manifest" in instruction
    assert "including its final newline" in instruction
    assert "including square brackets" in instruction
    assert "Every literal http(s) URL" in instruction
    assert "web_extracted_content receipt origin_locator" in instruction
    assert "Map [H1] only to a history_excerpt" in instruction
    assert "[W1] only to a workspace_excerpt" in instruction
    assert "two distinct web_extracted_content" in instruction
    assert frozenset({"write_file", "edit_file"}) == (
        run_014_e3._ARTIFACT_MUTATION_TOOLS
    )


def test_014_e3_receipt_schema_names_all_nineteen_boolean_claims() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    claim_keys = {
        key.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "claims"
            for target in node.targets
        )
        and isinstance(node.value, ast.Dict)
        for key in node.value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert claim_keys == EXPECTED_CLAIMS


def test_014_e3_notice_drift_claim_exercises_zero_send_binding_rejection() -> None:
    from scripts import run_014_e3

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    profile = WebProfileV1(credential_env="FIRST_AGENT_014_E3_WEB_API_KEY")
    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        resources = build_web_resources(
            profile,
            credential="fixture-web-key",
            http_client=http_client,
        )
        assert run_014_e3._trust_notice_drift_invalidates_binding(
            resources.registrations,
            request_count=lambda: len(requests),
        )

    assert requests == []


def test_014_e3_sanitizes_internal_and_adapter_failures(monkeypatch, capsys) -> None:
    from scripts import run_014_e3

    for name, value in {
        "FIRST_AGENT_014_E3_PROVIDER": "openai_compatible",
        "FIRST_AGENT_014_E3_BASE_URL": "https://provider.invalid",
        "FIRST_AGENT_014_E3_MODEL": "fixture-model",
        "FIRST_AGENT_014_E3_API_KEY": "fixture-model-key",
        "FIRST_AGENT_014_E3_WEB_API_KEY": "fixture-web-key",
    }.items():
        monkeypatch.setenv(name, value)

    cases = (
        (ValueError("private-path-and-body"), "provider_protocol"),
        (ProviderAuthError(), "model_auth"),
        (ProviderProtocolError("bad"), "provider_protocol"),
        (WebAuthError("secret"), "web_auth"),
        (WebRateLimitError("secret"), "web_rate_limit"),
        (WebProtocolError("secret"), "web_protocol"),
    )
    for error, reason in cases:
        monkeypatch.setattr(
            run_014_e3,
            "run_e3",
            lambda _config, error=error: (_ for _ in ()).throw(error),
        )
        assert run_014_e3.main() == 2
        output = capsys.readouterr()
        assert output.err == ""
        assert output.out == f"014_E3_BLOCKED(reason={reason})\n"


def test_014_e3_reports_closed_runtime_failure_without_exposing_message() -> None:
    from scripts import run_014_e3

    state = ConversationState.new("conversation-1")
    state = replace(
        state,
        last_safe_result=RecordedRunResult(
            status=RunStatus.FAILED_FATAL,
            message="private provider output and workspace path",
            error_code="no_progress",
        ),
    )

    assert run_014_e3._runtime_failure_marker(state) == (
        "014_E3_BLOCKED(reason=product_no_progress)"
    )


def test_014_e3_config_repr_does_not_expose_credentials() -> None:
    from scripts.run_014_e3 import E3Config

    config = E3Config.from_environment(
        {
            "FIRST_AGENT_014_E3_PROVIDER": "openai_compatible",
            "FIRST_AGENT_014_E3_BASE_URL": "https://provider.invalid",
            "FIRST_AGENT_014_E3_MODEL": "fixture-model",
            "FIRST_AGENT_014_E3_API_KEY": "model-secret",
            "FIRST_AGENT_014_E3_WEB_API_KEY": "web-secret",
        }
    )

    assert "model-secret" not in repr(config)
    assert "web-secret" not in repr(config)


@pytest.mark.parametrize("name", ("model_api_key", "web_api_key"))
def test_014_e3_config_credentials_are_not_public_receipt_fields(name: str) -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    receipt_return = source.split('"schema": "first-agent-014-e3-receipt-v1"', 1)[1]
    assert f'"{name}"' not in receipt_return

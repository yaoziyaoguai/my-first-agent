from __future__ import annotations

from pathlib import Path

from agent.runtime.contracts import (
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    RunStatus,
)
from agent.subagent.contracts import ChildProfile
from agent.subagent.runner import ChildAgentRunner
from tests.kernel.fakes import ScriptedProvider


def _profile() -> ChildProfile:
    return ChildProfile(
        runner_version="subagent-v1",
        provider_profile_id="default",
        provider_destination="local",
        workspace_scope_digest="scope-1",
        max_input_tokens=4_000,
        max_output_tokens=1_000,
        limits_digest="limits-1",
        hard_deadline_seconds=30.0,
    )


def test_child_completes_with_one_model_call() -> None:
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("focused child review"),)))
    runner = ChildAgentRunner(provider=provider, profile=_profile())

    result = runner.run(
        objective="review the design",
        handoff="context",
        parent_idempotency_key="parent:run-1:call-1",
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "focused child review"
    assert result.model_calls == 1
    assert result.tool_calls == 0
    assert result.run_id


def test_child_tool_request_is_nonterminal() -> None:
    provider = ScriptedProvider(ModelResponse((ModelToolCall("c1", "read_file", {"path": "x"}),)))
    runner = ChildAgentRunner(provider=provider, profile=_profile())

    result = runner.run(
        objective="try to use a tool", handoff="", parent_idempotency_key="parent:run-1:call-2"
    )

    assert result.status is not RunStatus.COMPLETED
    assert result.reason == "child_nonterminal"


def test_child_identity_is_deterministic_from_parent_key() -> None:
    provider_a = ScriptedProvider(ModelResponse((ModelTextBlock("a"),)))
    provider_b = ScriptedProvider(ModelResponse((ModelTextBlock("b"),)))
    runner_a = ChildAgentRunner(provider=provider_a, profile=_profile())
    runner_b = ChildAgentRunner(provider=provider_b, profile=_profile())

    key = "parent:run-1:call-3"
    first = runner_a.run(objective="o", handoff="", parent_idempotency_key=key)
    second = runner_b.run(objective="o", handoff="", parent_idempotency_key=key)

    assert first.run_id == second.run_id


def test_http_provider_subagent_composes_process_runner(
    tmp_path: Path, monkeypatch
) -> None:
    """G8: HTTP providers lack a synchronous deadline_contract, but composition no longer
    rejects ``--subagent``: it routes to the process-isolated ``ChildProcessRunner``, which
    provides the real hard deadline via process-group ownership (not a socket timeout).
    Composition succeeds and the ``subagent__delegate`` tool is registered."""
    import main as entrypoint

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("FIRST_AGENT_API_KEY", "test-fixture-key")
    output: list[str] = []
    code = entrypoint.main(
        [
            "--workspace", str(workspace),
            "--state-root", str(tmp_path / "state-root"),
            "--provider", "openai_compatible",
            "--model", "test-model",
            "--base-url", "https://provider.invalid",
            "--subagent",
        ],
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )
    # 不再 reject：HTTP+subagent 经进程隔离路径组合成功。
    assert code == 0, output
    # 没有“requires deadline_contract”式的 startup 失败信息。
    assert not any("deadline_contract" in line for line in output)


def test_subagent_http_without_model_or_base_url_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    """G8: HTTP SubAgent 路径仍要求 --model 与 --base-url；缺失则 startup fail closed。"""
    import main as entrypoint

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("FIRST_AGENT_API_KEY", "test-fixture-key")
    output: list[str] = []
    code = entrypoint.main(
        [
            "--workspace", str(workspace),
            "--state-root", str(tmp_path / "state-root"),
            "--provider", "openai_compatible",
            "--subagent",
        ],
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )
    assert code != 0


def test_provider_hard_deadline_exceeding_child_cap_is_rejected() -> None:
    """G4：provider 暴露了 structural deadline_contract，但其 hard_deadline 超过 child profile
    cap 时，runner 构造必须 fail closed（不能用 provider class/name 替代 deadline cap 校验）。"""
    import pytest

    from agent.subagent.runner import UnsupportedProviderError

    # ScriptedProvider.deadline_contract.hard_deadline_seconds == 30.0。
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("x"),)))
    tight_profile = ChildProfile(
        runner_version="subagent-v1",
        provider_profile_id="default",
        provider_destination="local",
        workspace_scope_digest="scope-1",
        max_input_tokens=4_000,
        max_output_tokens=1_000,
        limits_digest="limits-1",
        hard_deadline_seconds=10.0,  # 远小于 provider 声明的 30s
    )
    with pytest.raises(UnsupportedProviderError):
        ChildAgentRunner(provider=provider, profile=tight_profile)


def test_handoff_reaches_child_provider_call_verbatim() -> None:
    """G4 exact handoff：parent 提供的 handoff 必须逐字进入 child 的 provider call（untrusted
    上下文），不能被丢弃、截断或改写；objective 同样逐字到达。"""
    import json

    provider = ScriptedProvider(ModelResponse((ModelTextBlock("ok"),)))
    runner = ChildAgentRunner(provider=provider, profile=_profile())
    runner.run(
        objective="review the design",
        handoff="DISTINCTIVE-HANDOFF-MARKER-12345",
        parent_idempotency_key="parent:run-1:call-handoff",
    )
    assert len(provider.calls) == 1
    blob = json.dumps(
        [block for message in provider.calls[0].messages for block in message.content],
        default=str,
    )
    assert "DISTINCTIVE-HANDOFF-MARKER-12345" in blob
    assert "review the design" in blob

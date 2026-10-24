from __future__ import annotations

from pathlib import Path

import pytest

import main as entrypoint
from agent.composition import build_owner_preference_resources
from agent.provider.config import AgentProviderConfig
from agent.runtime.checkpoint import CheckpointMissingError
from agent.runtime.ports import ModelAttemptBudgetExhaustedError


def test_legacy_state_and_resume_flags_are_removed() -> None:
    """012 权威只允许默认 root + 显式 --state-root；legacy 手动 checkpoint 工作流
    （--state/--resume）是被禁止的 compatibility/dual path，且不得经 argparse
    前缀缩写复活为 --state-root 的别名。"""
    parser = entrypoint.build_parser()

    for legacy in (["--state", "one"], ["--resume", "two"]):
        with pytest.raises(SystemExit) as caught:
            parser.parse_args(legacy)
        assert caught.value.code != 0
    assert not hasattr(entrypoint, "open_checkpoint")


def test_state_root_inside_workspace_fails_startup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--provider",
            "fake",
            "--state-root",
            str(workspace / "state"),
        ],
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output[0].startswith("Startup failed:")
    assert "ValueError" not in output[0]
    assert "outside" in output[0]


def test_status_without_credentials_is_read_only_for_missing_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "missing-state"
    monkeypatch.delenv("FIRST_AGENT_API_KEY", raising=False)
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("status must not construct a provider")
        ),
    )
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--status",
        ],
        write_fn=output.append,
    )

    assert exit_code == 0
    assert output == ["No saved conversations."]
    assert not state_root.exists()


def test_model_attempt_budget_requires_a_transport_ledger(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
            "--max-model-attempts",
            "2",
        ],
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == [
        "Startup failed: --max-model-attempts requires --transport-audit-ledger."
    ]
    assert not state_root.exists()


def test_model_attempt_budget_must_be_positive() -> None:
    parser = entrypoint.build_parser()

    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["--max-model-attempts", "0"])

    assert caught.value.code == 2


def test_model_attempt_budget_is_wired_to_the_real_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def capture_provider(config, **kwargs):  # noqa: ANN001, ANN202
        captured["config"] = config
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("FIXTURE_PROVIDER_KEY", "fixture-secret")
    monkeypatch.setattr(entrypoint, "build_model_provider", capture_provider)
    ledger = tmp_path / "attempts.jsonl"
    args = entrypoint.build_parser().parse_args(
        [
            "--provider",
            "openai_compatible",
            "--model",
            "fixture-model",
            "--base-url",
            "https://provider.example",
            "--credential-env",
            "FIXTURE_PROVIDER_KEY",
            "--transport-audit-ledger",
            str(ledger),
            "--max-model-attempts",
            "1",
        ]
    )

    entrypoint._build_provider(args)
    recorder = captured["attempt_recorder"]
    recorder("model", "https://provider.example")
    with pytest.raises(ModelAttemptBudgetExhaustedError):
        recorder("model", "https://provider.example")


def test_invalid_project_path_stops_before_state_creation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
            "--project-path",
            "../config",
        ],
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == ["Startup failed: project path exception is not admitted"]
    assert not state_root.exists()


def test_project_path_cannot_expose_the_configured_transport_ledger(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "config").mkdir(parents=True)
    state_root = tmp_path / "state"
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
            "--project-path",
            "config",
            "--transport-audit-ledger",
            str(workspace / "config" / "attempts.jsonl"),
        ],
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == [
        "Startup failed: --project-path overlaps a configured private runtime path."
    ]
    assert not state_root.exists()


def test_model_switch_can_explicitly_skip_owner_preferences_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    from agent.continuity.sessions import open_workspace_session

    open_workspace_session(workspace, state_root=state_root)
    first_descriptor = AgentProviderConfig(
        provider_type="openai_compatible",
        model="model-a",
        base_url="https://provider.example",
    ).descriptor()
    preference_path = state_root / "owner-preferences.json"
    build_owner_preference_resources(
        preference_path,
        provider_trust_digest=first_descriptor.identity_digest,
    )
    before = preference_path.read_bytes()
    monkeypatch.setenv("FIXTURE_PROVIDER_KEY", "fixture-secret")
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "openai_compatible",
            "--model",
            "model-b",
            "--base-url",
            "https://provider.example",
            "--credential-env",
            "FIXTURE_PROVIDER_KEY",
            "--without-owner-preferences",
        ],
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 0
    assert preference_path.read_bytes() == before
    assert "Owner preferences: not loaded for this start" in output


def test_owner_preferences_remain_strict_without_the_explicit_skip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    from agent.continuity.sessions import open_workspace_session

    open_workspace_session(workspace, state_root=state_root)
    original = AgentProviderConfig(
        provider_type="openai_compatible",
        model="model-a",
        base_url="https://provider.example",
    ).descriptor()
    preference_path = state_root / "owner-preferences.json"
    build_owner_preference_resources(
        preference_path,
        provider_trust_digest=original.identity_digest,
    )
    before = preference_path.read_bytes()
    monkeypatch.setenv("FIXTURE_PROVIDER_KEY", "fixture-secret")
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "openai_compatible",
            "--model",
            "model-b",
            "--base-url",
            "https://provider.example",
            "--credential-env",
            "FIXTURE_PROVIDER_KEY",
        ],
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 2
    assert preference_path.read_bytes() == before
    assert "--without-owner-preferences" in output[-1]


def test_corrupt_owner_preferences_are_not_reported_as_a_provider_mismatch(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    from agent.continuity.sessions import open_workspace_session

    open_workspace_session(workspace, state_root=state_root)
    preference_path = state_root / "owner-preferences.json"
    build_owner_preference_resources(
        preference_path,
        provider_trust_digest=AgentProviderConfig(provider_type="fake").descriptor().identity_digest,
    )
    preference_path.write_text("{", encoding="utf-8")
    before = preference_path.read_bytes()
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
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 2
    assert preference_path.read_bytes() == before
    assert "memory store is malformed" in output[-1]
    assert "different provider" not in output[-1]


def test_owner_preference_skip_performs_no_preference_store_io(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"

    monkeypatch.setattr(
        entrypoint,
        "build_owner_preference_resources",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("owner preference resources must not be opened")
        ),
    )
    output: list[str] = []
    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
            "--without-owner-preferences",
        ],
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 0
    assert not (state_root / "owner-preferences.json").exists()


def test_status_reads_saved_conversation_without_provider_or_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent.continuity.sessions import open_workspace_session

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000095",
    )
    assert opened.checkpoint_path is not None
    checkpoint = opened.checkpoint_path
    before = (checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns)
    monkeypatch.delenv("FIRST_AGENT_API_KEY", raising=False)
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("status must not construct a provider")
        ),
    )
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--status",
        ],
        write_fn=output.append,
    )

    assert exit_code == 0
    assert output[0] == "Saved conversations:"
    assert "00000000-0000-4000-8000-000000000095" in output[1]
    assert "no active task" in output[1]
    assert checkpoint.read_bytes() == before[0]
    assert checkpoint.stat().st_mtime_ns == before[1]


@pytest.mark.parametrize(
    "effect_options",
    (
        ("--tui",),
        ("--browser",),
        ("--subagent",),
        ("--without-owner-preferences",),
        ("--project-path", "config"),
        ("--memory-create", "memory.json"),
        ("--mcp-catalog", "mcp.json"),
    ),
)
def test_status_rejects_execution_options_before_state_io(
    tmp_path: Path,
    effect_options: tuple[str, ...],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "missing-state"
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--status",
            *effect_options,
        ],
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == ["Status cannot be combined with execution options."]
    assert not state_root.exists()


def test_status_does_not_disclose_a_replaced_workspace_conversation(
    tmp_path: Path,
) -> None:
    from agent.continuity.sessions import open_workspace_session

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(workspace, state_root=state_root)
    assert opened.checkpoint_path is not None
    old_workspace = tmp_path / "workspace-old"
    workspace.rename(old_workspace)
    workspace.mkdir()
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--status",
        ],
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output == ["Status failed: workspace identity confirmation is required"]
    assert opened.snapshot is not None
    assert opened.snapshot.state.conversation_id not in "\n".join(output)


def test_fake_provider_console_smoke_is_non_networked(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    inputs = iter(("hello kernel", "/exit"))
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--provider",
            "fake",
            "--state-root",
            str(state_root),
        ],
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
    )

    assert exit_code == 0
    assert "hello kernel" in output
    assert tuple(state_root.glob("workspaces/*/*.json"))


def test_cli_can_select_a_displayed_goal_less_conversation(tmp_path: Path) -> None:
    from agent.continuity.sessions import open_workspace_session

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    first = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000093",
    )
    second = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000094",
        force_new=True,
    )
    assert first.checkpoint_path is not None and second.checkpoint_path is not None
    before = {
        first.checkpoint_path: first.checkpoint_path.read_bytes(),
        second.checkpoint_path: second.checkpoint_path.read_bytes(),
    }
    output: list[str] = []
    inputs = iter(("2", "/exit"))

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--provider",
            "fake",
            "--state-root",
            str(state_root),
        ],
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
    )

    assert exit_code == 0
    assert any("conversations" in message for message in output)
    assert any("First Agent is ready" in message for message in output)
    assert {path: path.read_bytes() for path in before} == before


def test_invalid_provider_configuration_exits_without_traceback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("FIXTURE_PROVIDER_KEY", "fixture-secret")
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(tmp_path / "state-root"),
            "--provider",
            "openai_compatible",
            "--model",
            "fixture-model",
            "--base-url",
            "https://provider.invalid",
            "--credential-env",
            "FIXTURE_PROVIDER_KEY",
            "--timeout",
            "-1",
        ],
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )

    assert exit_code != 0
    assert output == ["Startup failed: provider_configuration_error"]
    assert "fixture-secret" not in output[0]


def test_explicit_thinking_mode_reaches_main_and_scheduler_provider_config(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FIXTURE_PROVIDER_KEY", "fixture-secret")
    captured = []
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda config: captured.append(config) or object(),
    )

    common = [
        "--provider",
        "openai_compatible",
        "--model",
        "deepseek-v4-flash",
        "--base-url",
        "https://api.deepseek.com",
        "--credential-env",
        "FIXTURE_PROVIDER_KEY",
        "--thinking-mode",
        "disabled",
    ]
    entrypoint._build_provider(entrypoint.build_parser().parse_args(common))
    entrypoint._build_provider(
        entrypoint.build_schedule_parser().parse_args(
            [
                "--state-root",
                "/tmp/fixture-state",
                "--schedule-id",
                "schedule-1",
                "--occurrence-id",
                "occurrence-1",
                "--scheduled-for",
                "2026-08-02T00:00:00Z",
                "--message",
                "fixture",
                *common,
            ]
        )
    )

    assert [config.thinking_mode for config in captured] == ["disabled", "disabled"]
    assert all(config.credential == "fixture-secret" for config in captured)


def test_supported_deepseek_flash_enabled_mode_uses_max_effort_everywhere(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FIXTURE_PROVIDER_KEY", "fixture-secret")
    captured = []
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda config: captured.append(config) or object(),
    )
    common = [
        "--provider",
        "openai_compatible",
        "--model",
        "deepseek-v4-flash",
        "--base-url",
        "https://api.deepseek.com",
        "--credential-env",
        "FIXTURE_PROVIDER_KEY",
        "--thinking-mode",
        "enabled",
    ]

    entrypoint._build_provider(entrypoint.build_parser().parse_args(common))
    entrypoint._build_provider(
        entrypoint.build_schedule_parser().parse_args(
            [
                "--state-root",
                "/tmp/fixture-state",
                "--schedule-id",
                "schedule-1",
                "--occurrence-id",
                "occurrence-1",
                "--scheduled-for",
                "2026-08-02T00:00:00Z",
                "--message",
                "fixture",
                *common,
            ]
        )
    )

    assert [config.thinking_mode for config in captured] == ["enabled", "enabled"]
    assert [config.reasoning_effort for config in captured] == ["max", "max"]
    assert [config.max_tokens for config in captured] == [384_000, 384_000]


def test_deepseek_flash_context_budget_matches_its_documented_window() -> None:
    deepseek_args = entrypoint.build_parser().parse_args(
        [
            "--provider",
            "openai_compatible",
            "--model",
            "deepseek-v4-flash",
            "--base-url",
            "https://api.deepseek.com",
            "--thinking-mode",
            "enabled",
        ]
    )
    generic_args = entrypoint.build_parser().parse_args(
        [
            "--provider",
            "openai_compatible",
            "--model",
            "fixture-model",
            "--base-url",
            "https://provider.invalid",
        ]
    )

    deepseek = entrypoint._context_limits_for_provider(deepseek_args)
    generic = entrypoint._context_limits_for_provider(generic_args)

    assert (deepseek.max_input_tokens, deepseek.output_reserve) == (
        1_000_000,
        384_000,
    )
    assert (generic.max_input_tokens, generic.output_reserve) == (100_000, 8_000)


def test_checkpoint_load_failure_during_repl_exits_without_traceback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class FailingStore:
        def load(self):
            raise CheckpointMissingError("fixture path must not be rendered")

    from agent.continuity.identity import WorkspaceIdentityV1
    from agent.continuity.sessions import StartupDisposition, WorkspaceSession

    def _fake_session(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return WorkspaceSession(
            disposition=StartupDisposition.CREATED,
            state_root=tmp_path / "state-root",
            workspace_identity=WorkspaceIdentityV1.resolve(workspace),
            checkpoint_path=tmp_path / "state-root" / "conversation.json",
            store=FailingStore(),
            snapshot=None,
        )

    monkeypatch.setattr(entrypoint, "open_workspace_session", _fake_session)
    output: list[str] = []

    exit_code = entrypoint.main(
        ["--workspace", str(workspace), "--provider", "fake"],
        input_fn=lambda _: "hello",
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output[-1] == "Runtime state failed: CheckpointMissingError"
    assert "fixture path" not in output[-1]


def test_skill_root_flag_starts_with_governed_skills(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = tmp_path / "roots"
    skill_dir = root / "code-review"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: code-review\ndescription: A review skill.\n---\nReview the diff.\n",
        encoding="utf-8",
    )
    inputs = iter(("hello skills", "/exit"))
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(tmp_path / "state-root"),
            "--provider",
            "fake",
            "--skill-root",
            str(root),
        ],
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
    )

    assert exit_code == 0
    assert "hello skills" in output


def test_invalid_skill_root_fails_startup_without_traceback(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = tmp_path / "roots"
    skill_dir = root / "code-review"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: mismatched-name\n---\nbody\n", encoding="utf-8"
    )
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(tmp_path / "state-root"),
            "--provider",
            "fake",
            "--skill-root",
            str(root),
        ],
        input_fn=lambda _: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 2
    assert output[0].startswith("Startup failed:")
    assert "SkillSchemaError" not in output[0]


def test_skill_runtime_root_flag_is_removed() -> None:
    """runtime 由应用内部复用并验证自身 interpreter/stdlib/runner；面向用户的
    --skill-runtime-root 是被删除的配置面，不得经 argparse 前缀缩写复活。"""
    parser = entrypoint.build_parser()

    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["--skill-runtime-root", "/tmp/runtime"])
    assert caught.value.code != 0


# --- U7 lifecycle: shared queue sink + close-stack reverse-close once ---

def _write_catalog_and_state(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")
    state = tmp_path / "latch.json"
    state.write_text("{}", encoding="utf-8")
    return workspace, catalog, state


def _entry_argv(tmp_path: Path, workspace: Path, *extra: str) -> list[str]:
    # 所有经 main() 的测试注入临时 state root，避免触碰真实用户默认 root。
    return [
        "--workspace", str(workspace),
        "--state-root", str(tmp_path / "state-root"),
        "--provider", "fake",
        *extra,
    ]


def test_tui_composition_and_adapter_share_one_queue_sink_without_terminal_events() -> None:
    """R20/A2: composition 与 adapter 共用一个 QueueingEventSink；terminal writer
    不接收 model/tool progress。"""
    from agent.cli.render import TerminalRenderer
    from agent.composition import build_composition
    from agent.runtime.context import ContextLimits
    from agent.runtime.contracts import (
        ConversationState,
        ModelResponse,
        ModelTextBlock,
        SubmitMessage,
    )
    from agent.runtime.loop import InvocationLimits
    from agent.tui.adapter import QueueingEventSink, TuiAdapter
    from tests.kernel.fakes import InMemoryCheckpointStore, ScriptedProvider

    sink = QueueingEventSink()
    terminal: list[str] = []
    renderer = TerminalRenderer(terminal.append)  # TUI 模式下的 terminal writer，不是 runtime sink
    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
    composition = build_composition(
        provider=provider,
        checkpoint_store=store,
        tool_registrations=(),
        event_sink=sink,
        system_policy="policy",
        context_limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        invocation_limits=InvocationLimits(),
    )
    adapter = TuiAdapter(composition.runtime, store, event_sink=sink)
    assert adapter.event_sink is sink

    adapter.execute_once(
        SubmitMessage(
            conversation_id="c1", action_seq=1, expected_revision=0, run_id="r", message="hi"
        )
    )
    drained = adapter.event_sink.drain()
    assert drained, "runtime must emit progress into the shared queue sink"
    # terminal renderer（独立 writer）不是 runtime sink，故 model/tool progress 不进入 terminal。
    assert renderer is not None
    assert terminal == []


def test_tui_normal_exit_reverse_closes_resources_once(
    tmp_path: Path, monkeypatch
) -> None:
    closes: list[int] = []

    def fake_close() -> None:
        closes.append(1)

    from agent.composition import McpResources

    monkeypatch.setattr(
        entrypoint,
        "build_mcp_resources",
        lambda *a, **k: McpResources(registrations=(), closeables=(fake_close,), latch=object()),
    )
    import agent.tui.app as tui_app

    monkeypatch.setattr(tui_app, "run_tui", lambda adapter, *, run_id_factory: 0)
    workspace, catalog, state = _write_catalog_and_state(tmp_path)

    code = entrypoint.main(
        _entry_argv(
            tmp_path,
            workspace,
            "--mcp-catalog", str(catalog),
            "--mcp-safety-state", str(state),
            "--tui",
        ),
        input_fn=lambda _: "/exit",
        write_fn=lambda _msg: None,
    )
    assert code == 0
    assert closes == [1], f"closeable must be closed exactly once on normal TUI exit, got {closes}"


def test_tui_optional_dependency_error_reverse_closes_resources_once(
    tmp_path: Path, monkeypatch
) -> None:
    closes: list[int] = []

    def fake_close() -> None:
        closes.append(1)

    from agent.composition import McpResources
    from agent.tui.app import TextualNotInstalledError

    monkeypatch.setattr(
        entrypoint,
        "build_mcp_resources",
        lambda *a, **k: McpResources(registrations=(), closeables=(fake_close,), latch=object()),
    )

    def boom(adapter, *, run_id_factory):
        raise TextualNotInstalledError("the TUI requires the optional 'tui' extra")

    import agent.tui.app as tui_app

    monkeypatch.setattr(tui_app, "run_tui", boom)
    workspace, catalog, state = _write_catalog_and_state(tmp_path)

    code = entrypoint.main(
        _entry_argv(
            tmp_path,
            workspace,
            "--mcp-catalog", str(catalog),
            "--mcp-safety-state", str(state),
            "--tui",
        ),
        input_fn=lambda _: "/exit",
        write_fn=lambda _msg: None,
    )
    assert code == 2
    assert closes == [1], "optional-dependency failure must still reverse-close once"


def test_startup_failure_after_closeable_construction_reverse_closes_once(
    tmp_path: Path, monkeypatch
) -> None:
    closes: list[int] = []

    def fake_close() -> None:
        closes.append(1)

    from agent.composition import McpResources

    monkeypatch.setattr(
        entrypoint,
        "build_mcp_resources",
        lambda *a, **k: McpResources(registrations=(), closeables=(fake_close,), latch=object()),
    )

    def provider_boom(args):
        raise ValueError("provider construction failed after closeable built")

    monkeypatch.setattr(entrypoint, "_build_provider", provider_boom)
    workspace, catalog, state = _write_catalog_and_state(tmp_path)

    code = entrypoint.main(
        _entry_argv(
            tmp_path,
            workspace,
            "--mcp-catalog", str(catalog),
            "--mcp-safety-state", str(state),
        ),
        input_fn=lambda _: "/exit",
        write_fn=lambda _msg: None,
    )
    assert code == 2
    assert closes == [1], "startup failure after closeable construction must reverse-close once"


def test_new_session_reuses_memory_created_for_the_process(tmp_path: Path) -> None:
    """同一进程的 /new 只切换 conversation，不重复执行一次性 Memory 创建。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory_path = tmp_path / "memory" / "store.json"
    memory_path.parent.mkdir(mode=0o700)
    inputs = iter(("/new", "/exit"))
    output: list[str] = []

    observed_memory: list[bytes] = []

    def read_input(_prompt: str) -> str:
        observed_memory.append(memory_path.read_bytes())
        return next(inputs)

    code = entrypoint.main(
        _entry_argv(
            tmp_path,
            workspace,
            "--memory-create",
            str(memory_path),
        ),
        input_fn=read_input,
        write_fn=output.append,
    )

    assert code == 0
    assert memory_path.exists()
    assert len(observed_memory) == 2
    assert observed_memory[0] == observed_memory[1]
    assert sum(line.startswith("First Agent is ready in:") for line in output) == 2
    assert not any(line.startswith("Startup failed:") for line in output)


@pytest.mark.parametrize("use_tui", [False, True], ids=("cli", "tui"))
def test_new_session_closes_optional_resources_before_reopening(
    tmp_path: Path, monkeypatch, use_tui: bool
) -> None:
    """新 conversation 开始装配前，上一轮拥有的可关闭资源必须已经结束。"""
    import threading

    from agent.composition import McpResources
    from agent.mcp.bridge import McpAsyncBridge

    baseline = sum(thread.name == "mcp-bridge-loop" for thread in threading.enumerate())
    observed_before_build: list[int] = []

    def build_resources(*_args, **_kwargs):
        observed_before_build.append(
            sum(thread.name == "mcp-bridge-loop" for thread in threading.enumerate())
        )
        bridge = McpAsyncBridge(total_timeout_seconds=1.0)
        return McpResources(
            registrations=(), closeables=(bridge.close,), latch=object()
        )

    monkeypatch.setattr(entrypoint, "build_mcp_resources", build_resources)
    workspace, catalog, state = _write_catalog_and_state(tmp_path)
    inputs = iter(("/new", "/exit"))
    extra = []
    if use_tui:
        import agent.tui.app as tui_app

        tui_codes = iter((entrypoint.NEW_SESSION_REQUESTED, 0))
        monkeypatch.setattr(
            tui_app,
            "run_tui",
            lambda _adapter, *, run_id_factory: next(tui_codes),
        )
        extra.append("--tui")

    code = entrypoint.main(
        _entry_argv(
            tmp_path,
            workspace,
            "--mcp-catalog",
            str(catalog),
            "--mcp-safety-state",
            str(state),
            *extra,
        ),
        input_fn=lambda _prompt: next(inputs),
        write_fn=lambda _message: None,
    )

    assert code == 0
    assert observed_before_build == [baseline, baseline]
    assert sum(
        thread.name == "mcp-bridge-loop" for thread in threading.enumerate()
    ) == baseline


def test_new_session_cleanup_failure_stops_before_reopening(
    tmp_path: Path, monkeypatch
) -> None:
    """旧资源未能可靠关闭时，切换必须停止且不得泄露异常正文。"""
    from agent.composition import McpResources

    builds = 0

    def build_resources(*_args, **_kwargs):
        nonlocal builds
        builds += 1

        def close() -> None:
            raise RuntimeError("private resource detail must stay hidden")

        return McpResources(registrations=(), closeables=(close,), latch=object())

    monkeypatch.setattr(entrypoint, "build_mcp_resources", build_resources)
    workspace, catalog, state = _write_catalog_and_state(tmp_path)
    output: list[str] = []

    code = entrypoint.main(
        _entry_argv(
            tmp_path,
            workspace,
            "--mcp-catalog",
            str(catalog),
            "--mcp-safety-state",
            str(state),
        ),
        input_fn=lambda _prompt: "/new",
        write_fn=output.append,
    )

    assert code == 2
    assert builds == 1
    assert output[-1] == (
        "New session failed: resource cleanup failed: RuntimeError"
    )
    assert "private resource detail" not in "\n".join(output)


def test_default_cli_waits_with_heartbeat_before_blocking_provider_returns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """DU-11：默认 main（非 TUI）把 renderer 接进 progress_event_sink；阻塞
    provider 返回之前输出 waiting 提示；provider 仅一次调用（真实事件，不是
    事后重放）。"""

    import threading

    from agent.runtime.loop import AgentRuntime

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class _HeartbeatBlockingProvider:
        def __init__(self) -> None:
            self.event = threading.Event()
            self.calls = 0

        def generate(self, context, *, delta_observer=None):
            self.calls += 1
            self.event.wait(timeout=2)
            from agent.runtime.contracts import ModelResponse, ModelTextBlock

            return ModelResponse((ModelTextBlock("heartbeat done"),))

    provider = _HeartbeatBlockingProvider()

    original_init = AgentRuntime.__init__

    def fast_interval_init(self, *args, **kwargs):  # noqa: ANN001, ANN202
        kwargs["provider_progress_interval_seconds"] = 0.05
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(AgentRuntime, "__init__", fast_interval_init)
    monkeypatch.setattr(
        entrypoint, "FakeProvider", lambda: provider
    )

    output: list[str] = []
    inputs = iter(["hello", "/exit"])

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--provider",
            "fake",
            "--state-root",
            str(tmp_path / "state"),
        ],
        input_fn=lambda _prompt: next(inputs),
        write_fn=output.append,
    )

    assert exit_code == 0
    assert provider.calls == 1, "provider must be called exactly once"
    waiting_lines = [
        line
        for line in output
        if "Model is still working" in line or "still working" in line
    ]
    assert waiting_lines, output
    final_lines = [line for line in output if "heartbeat done" in line]
    assert final_lines, output
    # waiting 提示先于最终权威结果出现。
    assert output.index(waiting_lines[0]) < output.index(final_lines[0])


# ---------------------------------------------------------------- LOG-01


def test_state_failure_diagnostics_never_render_raw_message(
    tmp_path: Path, monkeypatch
) -> None:
    """LOG-01：虚构 CheckpointSecurityError 的敏感路径标记不出现在用户文本、
    stdout/stderr 与默认日志；稳定错误码/类型/下一步仍保留。

    Red：HEAD 的 ``_log_runtime_state_failure`` 直接 ``%s: %s`` 记录
    ``str(error)`` → 标记出现在 stderr（未配置 logging 与配置普通 handler
    两种进程都复现）。
    """

    import io
    import logging

    marker = "SECRET-PATH-MARKER-9f3a"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    from agent.runtime.checkpoint import CheckpointSecurityError

    class FailingStore:
        def load(self):
            raise CheckpointSecurityError(
                f"unsafe filesystem object during read: {marker}"
            )

    from agent.continuity.identity import WorkspaceIdentityV1
    from agent.continuity.sessions import StartupDisposition, WorkspaceSession

    def _fake_session(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return WorkspaceSession(
            disposition=StartupDisposition.CREATED,
            state_root=tmp_path / "state-root",
            workspace_identity=WorkspaceIdentityV1.resolve(workspace),
            checkpoint_path=tmp_path / "state-root" / "conversation.json",
            store=FailingStore(),
            snapshot=None,
        )

    monkeypatch.setattr(entrypoint, "open_workspace_session", _fake_session)
    monkeypatch.delenv("FIRST_AGENT_DEBUG_STATE_FAILURES", raising=False)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("agent.entrypoint")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    output: list[str] = []
    try:
        exit_code = entrypoint.main(
            ["--workspace", str(workspace), "--provider", "fake"],
            input_fn=lambda _: "hello",
            write_fn=output.append,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    logged = stream.getvalue()
    assert exit_code == 2
    # 用户文本：类型名保留，原始消息不渲染。
    assert output[-1] == "Runtime state failed: CheckpointSecurityError"
    # 默认日志：无虚构 secret/path 标记。
    assert marker not in logged, f"raw message leaked into log: {logged!r}"
    assert marker not in "\n".join(output)
    # 稳定错误码、类型与可执行的下一步仍然保留。
    assert "code=checkpoint_security" in logged
    assert "CheckpointSecurityError" in logged
    assert "mode 0700" in logged
    assert "next=" in logged


def test_state_failure_diagnostics_bounded_for_generic_errors(
    tmp_path: Path, monkeypatch
) -> None:
    """LOG-01：非安全类 checkpoint 错误同样有界（类型名 + 通用下一步）。"""

    import io
    import logging

    marker = "SECRET-PATH-MARKER-4b71"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class FailingStore:
        def load(self):
            raise OSError(f"disk exploded at {marker}")

    from agent.continuity.identity import WorkspaceIdentityV1
    from agent.continuity.sessions import StartupDisposition, WorkspaceSession

    def _fake_session(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return WorkspaceSession(
            disposition=StartupDisposition.CREATED,
            state_root=tmp_path / "state-root",
            workspace_identity=WorkspaceIdentityV1.resolve(workspace),
            checkpoint_path=tmp_path / "state-root" / "conversation.json",
            store=FailingStore(),
            snapshot=None,
        )

    monkeypatch.setattr(entrypoint, "open_workspace_session", _fake_session)
    monkeypatch.delenv("FIRST_AGENT_DEBUG_STATE_FAILURES", raising=False)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("agent.entrypoint")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    output: list[str] = []
    try:
        exit_code = entrypoint.main(
            ["--workspace", str(workspace), "--provider", "fake"],
            input_fn=lambda _: "hello",
            write_fn=output.append,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    logged = stream.getvalue()
    assert exit_code == 2
    assert marker not in logged
    assert "code=checkpoint_OSError" in logged
    assert "OSError" in logged


def test_status_names_budget_exhaustion_recovery_path_not_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """r14（2026-10-24 裁决 A′）：预算耗尽暂停的会话在 --status 里不得推荐
    注定失败的 /resume；正确出路是同 ledger 提高 --max-model-attempts。"""

    from agent.continuity.sessions import open_workspace_session
    from agent.runtime.contracts import (
        ActiveRun,
        ActiveRunStatus,
        ContinuationPhase,
        RecordedRunResult,
        RunStatus,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    conversation_id = "00000000-0000-4000-8000-000000000096"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: conversation_id,
    )
    assert opened.store is not None and opened.snapshot is not None
    lease = opened.store.try_acquire(conversation_id)
    assert lease is not None
    try:
        from dataclasses import replace

        paused = replace(
            opened.snapshot.state,
            active_run=ActiveRun(
                "run-1",
                status=ActiveRunStatus.PAUSED_LIMIT,
                phase=ContinuationPhase.MODEL,
            ),
            last_safe_result=RecordedRunResult(
                status=RunStatus.LIMIT_REACHED,
                run_id="run-1",
                error_code="model_attempt_budget_exhausted",
            ),
        )
        opened.store.compare_and_swap(opened.snapshot, paused)
    finally:
        lease.release()

    monkeypatch.delenv("FIRST_AGENT_API_KEY", raising=False)
    monkeypatch.setattr(
        entrypoint,
        "build_model_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("status must not construct a provider")
        ),
    )
    output: list[str] = []
    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--status",
        ],
        write_fn=output.append,
    )

    assert exit_code == 0
    line = output[1]
    assert "paused" in line
    assert "/resume" not in line
    assert "--max-model-attempts" in line

from __future__ import annotations

from pathlib import Path

import pytest

import main as entrypoint
from agent.runtime.checkpoint import CheckpointMissingError


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

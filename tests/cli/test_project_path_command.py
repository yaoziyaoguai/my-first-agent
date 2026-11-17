"""/project-path REPL 命令：operator 侧会话内准入，不进模型上下文。"""

from __future__ import annotations

from agent.cli.actions import build_project_path_command
from agent.cli.app import _HELP_TEXT, run_repl
from agent.runtime.contracts import (
    ConversationState,
    LoadedSnapshot,
    RunResult,
    RunStatus,
)
from agent.tools.path_safety import ProjectPathAdmissions
from tests.kernel.fakes import conversation_with_active_goal


class StaticStore:
    def __init__(self, state: ConversationState) -> None:
        self.state = state

    def load(self) -> LoadedSnapshot:
        return LoadedSnapshot(self.state, "token-1")


class RecordingRuntime:
    def __init__(self) -> None:
        self.actions = []

    def run_turn(self, action, snapshot):  # noqa: ANN001, ARG002
        self.actions.append(action)
        return RunResult(RunStatus.COMPLETED, snapshot.state)


def _run_once(
    state: ConversationState, raw: str, **repl_kwargs
) -> tuple[RecordingRuntime, list[str], int]:
    runtime = RecordingRuntime()
    output: list[str] = []
    inputs = iter((raw, "/exit"))
    exit_code = run_repl(
        runtime,
        StaticStore(state),
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
        **repl_kwargs,
    )
    return runtime, output, exit_code


# --- build_project_path_command ---


def test_command_without_suffix_lists_current_admissions() -> None:
    command = build_project_path_command(ProjectPathAdmissions())

    empty = command("")
    assert "No reserved workspace paths are admitted" in empty
    assert "/project-path" in empty

    populated = build_project_path_command(ProjectPathAdmissions(("config/app.yaml",)))
    listing = populated("   ")
    assert "config/app.yaml" in listing


def test_command_admits_one_path_with_session_semantics() -> None:
    admissions = ProjectPathAdmissions()
    command = build_project_path_command(admissions)

    confirmation = command("config/app.yaml")

    assert "config/app.yaml" in confirmation
    assert "session" in confirmation.lower()
    assert admissions.snapshot() == (("config", "app.yaml"),)


def test_command_returns_error_text_instead_of_raising() -> None:
    admissions = ProjectPathAdmissions()
    command = build_project_path_command(admissions)

    denied = command("docs/readme.md")

    assert "not admitted" in denied.lower()
    assert admissions.snapshot() == ()


# --- run_repl 分发 ---


def test_repl_dispatches_project_path_with_the_stripped_suffix() -> None:
    state = conversation_with_active_goal()
    runtime = RecordingRuntime()
    output: list[str] = []
    suffixes: list[str] = []
    inputs = iter(("/project-path   config/app.yaml  ", "/exit"))

    exit_code = run_repl(
        runtime,
        StaticStore(state),
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
        project_path_command=lambda suffix: (suffixes.append(suffix) or "ack"),
    )

    assert exit_code == 0
    assert suffixes == ["config/app.yaml"]
    assert output == ["ack"]
    assert runtime.actions == []


def test_repl_error_text_keeps_the_loop_alive() -> None:
    state = conversation_with_active_goal()
    runtime, output, exit_code = _run_once(
        state,
        "/project-path docs/readme.md",
        project_path_command=build_project_path_command(ProjectPathAdmissions()),
    )

    assert exit_code == 0
    assert runtime.actions == []
    assert any("not admitted" in line.lower() for line in output)


def test_help_lists_the_project_path_command() -> None:
    assert "/project-path" in _HELP_TEXT


def test_project_path_unavailable_message_explains_the_remedy() -> None:
    # 与 /browser-profiles 同模式：未注入时说明原因与补救，不让 /help
    # 列出的命令变成无出路的拒绝。
    runtime, output, exit_code = _run_once(
        conversation_with_active_goal(), "/project-path config/app.yaml"
    )

    assert exit_code == 0
    assert runtime.actions == []
    assert "unavailable in this session" in output[0]
    assert "restart with --project-path" in output[0]

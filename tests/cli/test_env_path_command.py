"""/env-path REPL 命令：operator 侧会话内子进程 PATH 前缀准入，不进模型上下文。"""

from __future__ import annotations

from pathlib import Path

from agent.cli.actions import build_env_path_command
from agent.cli.app import _HELP_TEXT, run_repl
from agent.process.preparation import SessionPathAdmissions
from agent.runtime.contracts import (
    ConversationState,
    LoadedSnapshot,
    RunResult,
    RunStatus,
)
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


def _admissions_with_venv(tmp_path: Path) -> SessionPathAdmissions:
    workspace = tmp_path / "workspace"
    (workspace / ".venv" / "bin").mkdir(parents=True)
    admissions = SessionPathAdmissions(workspace=workspace)
    admissions.admit(".venv/bin")
    return admissions


# --- build_env_path_command ---


def test_command_without_suffix_lists_current_admissions(tmp_path) -> None:  # noqa: ANN001
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    command = build_env_path_command(SessionPathAdmissions(workspace=workspace))

    empty = command("")
    assert "No workspace directories are admitted" in empty
    assert "/env-path" in empty
    assert ".venv/bin" in empty

    populated = build_env_path_command(_admissions_with_venv(tmp_path))
    listing = populated("   ")
    assert ".venv/bin" in listing


def test_command_admits_one_directory_with_session_semantics(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".venv" / "bin").mkdir(parents=True)
    admissions = SessionPathAdmissions(workspace=workspace)
    command = build_env_path_command(admissions)

    confirmation = command(".venv/bin")

    assert "Admitted" in confirmation
    assert str((workspace / ".venv" / "bin").resolve()) in confirmation
    assert "session" in confirmation.lower()
    # 披露诚实：前缀语义、持续到重启、只放宽名字解析、逐条审批。
    assert "PATH" in confirmation
    assert "restart" in confirmation
    assert "executable-name resolution" in confirmation
    assert "approved" in confirmation
    assert len(admissions.snapshot()) == 1


def test_repeat_admit_is_an_idempotent_no_op(tmp_path) -> None:  # noqa: ANN001
    workspace = tmp_path / "workspace"
    (workspace / ".venv" / "bin").mkdir(parents=True)
    admissions = SessionPathAdmissions(workspace=workspace)
    command = build_env_path_command(admissions)

    first = command(".venv/bin")
    snapshot_after_first = admissions.snapshot()
    second = command(".venv/bin")

    assert "Admitted" in first and "Admitted" in second
    assert admissions.snapshot() == snapshot_after_first
    assert len(snapshot_after_first) == 1


def test_command_returns_error_text_instead_of_raising(tmp_path) -> None:  # noqa: ANN001
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    admissions = SessionPathAdmissions(workspace=workspace)
    command = build_env_path_command(admissions)

    denied = command("/usr/local/bin")

    assert "not admitted" in denied.lower()
    assert admissions.snapshot() == ()


# --- run_repl 分发 ---


def test_repl_dispatches_env_path_with_the_stripped_suffix() -> None:  # noqa: ANN001
    state = conversation_with_active_goal()
    runtime = RecordingRuntime()
    output: list[str] = []
    suffixes: list[str] = []
    inputs = iter(("/env-path   .venv/bin  ", "/exit"))

    exit_code = run_repl(
        runtime,
        StaticStore(state),
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
        env_path_command=lambda suffix: (suffixes.append(suffix) or "ack"),
    )

    assert exit_code == 0
    assert suffixes == [".venv/bin"]
    assert output == ["ack"]
    # 不进模型上下文：dispatch 先于 _parse_action，零 runtime action。
    assert runtime.actions == []


def test_repl_error_text_keeps_the_loop_alive(tmp_path) -> None:  # noqa: ANN001
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime, output, exit_code = _run_once(
        conversation_with_active_goal(),
        "/env-path /usr/local/bin",
        env_path_command=build_env_path_command(
            SessionPathAdmissions(workspace=workspace)
        ),
    )

    assert exit_code == 0
    assert runtime.actions == []
    assert any("not admitted" in line.lower() for line in output)


def test_help_lists_the_env_path_command() -> None:
    assert "/env-path" in _HELP_TEXT


def test_env_path_unavailable_message_explains_the_remedy() -> None:  # noqa: ANN001
    # 与 /project-path 同模式：未注入时说明原因与补救，不让 /help 列出的
    # 命令变成无出路的拒绝。
    runtime, output, exit_code = _run_once(
        conversation_with_active_goal(), "/env-path .venv/bin"
    )

    assert exit_code == 0
    assert runtime.actions == []
    assert "unavailable in this session" in output[0]
    assert "restart" in output[0]

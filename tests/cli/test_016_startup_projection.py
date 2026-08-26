from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import main as entrypoint
from agent.cli.render import TerminalRenderer
from agent.continuity.sessions import open_workspace_session
from agent.process.contracts import SAME_UID_TRUST_NOTICE
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ConversationFact,
    FactKind,
    GoalStatus,
    RunResult,
    RunStatus,
)
from agent.runtime.state import create_goal
from tests.continuity.test_contracts import _goal
from tests.kernel.fakes import conversation_with_active_goal

_DENYLIST = (
    "goal_id",
    "request_id",
    "binding_digest",
    "receipt_digest",
    "criterion_id",
    "checkpoint_revision",
    "control_schema",
)


def _persist_startup_goal(
    tmp_path: Path,
    *,
    goal_status: GoalStatus,
    active_run: ActiveRun | None = None,
) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000118",
    )
    assert opened.store is not None and opened.snapshot is not None
    source = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "生成一份可验收的报告"},
    )
    with_goal = create_goal(
        replace(opened.snapshot.state, facts=(source,)),
        _goal(workspace_identity_digest=opened.workspace_identity.identity_digest),
    )
    assert with_goal.goal is not None
    persisted = replace(
        with_goal,
        goal=replace(with_goal.goal, status=goal_status),
        active_run=active_run,
    )
    lease = opened.store.try_acquire(persisted.conversation_id)
    assert lease is not None
    try:
        opened.store.compare_and_swap(opened.snapshot, persisted)
    finally:
        lease.release()
    return workspace, state_root


def test_new_workspace_startup_is_readable_and_protocol_free(tmp_path: Path) -> None:
    workspace = tmp_path / "existing-project"
    workspace.mkdir()
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(tmp_path / "state"),
            "--provider",
            "fake",
        ],
        input_fn=lambda _prompt: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 0
    rendered = "\n".join(output)
    assert "existing-project" in rendered
    assert "fake" in rendered
    assert "Capabilities: files, history, local programs" in rendered
    assert "Web: not enabled" in rendered
    assert "Status: no unfinished task" in rendered
    for forbidden in _DENYLIST:
        assert forbidden not in rendered


def test_process_notice_leads_with_plain_language_without_weakening_boundary() -> None:
    notice = SAME_UID_TRUST_NOTICE
    lowered = notice.casefold()

    assert "本机账号" in notice
    assert "不是 sandbox" in notice
    assert "same-uid" in lowered
    assert "not an os sandbox" in lowered
    assert "not a filesystem confinement" in lowered
    assert "not a network denial" in lowered


def test_no_progress_pause_projects_last_trusted_progress_and_controls() -> None:
    goal_state = conversation_with_active_goal()
    goal = replace(
        goal_state.goal,
        status=GoalStatus.EXECUTING,
        progress_summary="已读取目标文件并确认测试入口。",
        next_step="修复重复停滞后继续。",
    )
    state = replace(
        goal_state,
        goal=goal,
        active_run=ActiveRun("run-1", status=ActiveRunStatus.PAUSED_LIMIT),
    )
    output: list[str] = []

    TerminalRenderer(output.append).render_result(
        RunResult(
            RunStatus.LIMIT_REACHED,
            state,
            error_code="no_progress",
            message="The task repeated the same next step without new evidence.",
        )
    )

    rendered = "\n".join(output)
    assert "已读取目标文件并确认测试入口" in rendered
    assert goal.user_outcome in rendered
    assert "no new evidence" in rendered.lower()
    assert "approval" in rendered.lower()
    assert "/resume" in rendered and "/cancel" in rendered
    assert "verified done" not in rendered.lower()


def test_paused_goal_startup_projects_pause_without_claiming_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace, state_root = _persist_startup_goal(
        tmp_path,
        goal_status=GoalStatus.PAUSED,
    )

    calls: list[str] = []
    monkeypatch.setattr(
        entrypoint.FakeProvider,
        "generate",
        lambda *_args, **_kwargs: calls.append("provider") or None,
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
        ],
        input_fn=lambda _prompt: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 0
    assert calls == []
    rendered = "\n".join(output)
    assert "Task paused:" in rendered
    assert "/resume" in rendered and "/cancel" in rendered
    assert "Resuming task:" not in rendered
    assert "resuming unfinished task" not in rendered


def test_no_progress_restart_projects_limit_without_claiming_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace, state_root = _persist_startup_goal(
        tmp_path,
        goal_status=GoalStatus.EXECUTING,
        active_run=ActiveRun("run-1", status=ActiveRunStatus.PAUSED_LIMIT),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        entrypoint.FakeProvider,
        "generate",
        lambda *_args, **_kwargs: calls.append("provider") or None,
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
        ],
        input_fn=lambda _prompt: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 0
    assert calls == []
    rendered = "\n".join(output)
    assert "Task paused at a safe execution limit:" in rendered
    assert "/resume" in rendered and "/cancel" in rendered
    assert "Resuming task:" not in rendered
    assert "resuming unfinished task" not in rendered


def test_provider_failures_project_distinct_plain_language_recovery() -> None:
    state = conversation_with_active_goal()
    retryable_output: list[str] = []
    auth_output: list[str] = []

    TerminalRenderer(retryable_output.append).render_result(
        RunResult(RunStatus.FAILED_RETRYABLE, state, error_code="provider_timeout")
    )
    TerminalRenderer(auth_output.append).render_result(
        RunResult(RunStatus.FAILED_FATAL, state, error_code="provider_auth_error")
    )

    assert "timed out" in retryable_output[0].lower()
    assert "/resume" in retryable_output[0] and "/cancel" in retryable_output[0]
    assert "authentication" in auth_output[0].lower()
    assert "credential" in auth_output[0].lower()
    assert "provider_timeout" not in retryable_output[0]
    assert "provider_auth_error" not in auth_output[0]

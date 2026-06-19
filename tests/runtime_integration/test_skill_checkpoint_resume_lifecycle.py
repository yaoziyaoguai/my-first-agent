"""Skill checkpoint save/resume lifecycle integration tests.

这些测试走 runtime gateway + session selected-checkpoint restore path。测试只在
runtime seam 注入临时 SkillRegistry/SkillLoader，避免 checkpoint.py 或
transitions.py 获得 Skill 依赖。
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from agent.loop_context import LoopContext
from agent.runtime_identity import RuntimeIdentity
from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
from agent.skill_system.lifecycle import get_default_lifecycle, reset_default_lifecycle
from agent.state import create_agent_state
from tests.conftest import FakeAnthropicClient, text_response


@pytest.fixture(autouse=True)
def _s2_skill_enabled_for_activation_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """S2-G09 契约：本模块覆盖 Skill activation/execution（checkpoint restore），需 opt-in。

    default-off gate 只作用于 activation/execution；registry discovery/metadata
    测试不受影响。见 S2_GOAL_GAP.md S2-G09。
    """
    monkeypatch.setenv("MY_FIRST_AGENT_S2_SKILL_ENABLE", "1")


RAW_MARKERS = (
    "RAW_BODY_MARKER",
    "PROMPT_MARKER",
    "RESOURCE_MARKER",
    "SECRET_MARKER",
    "SKILL.md",
)


@pytest.fixture(autouse=True)
def _isolated_lifecycle() -> None:
    reset_default_lifecycle()
    yield
    reset_default_lifecycle()


@pytest.fixture
def evidence_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _record_evidence(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return dict(kwargs)

    import agent.evidence_recorder as evidence_recorder
    import agent.logger as logger

    monkeypatch.setattr(evidence_recorder, "record_evidence", _record_evidence)
    monkeypatch.setattr(logger, "log_event", lambda *_args, **_kwargs: None)
    return calls


@pytest.fixture
def checkpoint_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "checkpoint.json"
    import agent.checkpoint as checkpoint

    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    return path


def _write_skill(
    root: Path,
    name: str,
    *,
    status: str = "active",
    allowed_tools: tuple[str, ...] = ("current.tool",),
    body: str | None = None,
) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    allowed_tools_yaml = "\n".join(f"  - {tool}" for tool in allowed_tools)
    if not allowed_tools_yaml:
        allowed_tools_yaml = "  []"
    skill_body = body or (
        f"# {name}\n\n"
        "Runtime body RAW_BODY_MARKER PROMPT_MARKER RESOURCE_MARKER "
        "SECRET_MARKER SKILL.md"
    )
    (skill_dir / "SKILL.md").write_text(
        (
            f"---\n"
            f"name: {name}\n"
            f"description: Test skill for checkpoint lifecycle\n"
            f"version: 0.1.0\n"
            f"status: {status}\n"
            f"risk_level: low\n"
            f"allowed_tools:\n"
            f"{allowed_tools_yaml}\n"
            f"memory_scope: none\n"
            f"---\n"
            f"{dedent(skill_body).strip()}\n"
        ),
        encoding="utf-8",
    )


def _install_restore_registry(
    monkeypatch: pytest.MonkeyPatch,
    skill_root: Path,
) -> None:
    from agent.skill_system.loader import SkillLoader
    from agent.skill_system.registry import SkillRegistry

    def _build_dependencies():
        registry = SkillRegistry(roots=[skill_root])
        return registry, SkillLoader(registry)

    import agent.runtime_integration.skill_lifecycle as skill_lifecycle

    monkeypatch.setattr(
        skill_lifecycle,
        "build_skill_restore_dependencies",
        _build_dependencies,
    )


def _state(session_id: str):
    state = create_agent_state(system_prompt="test")
    state.memory.session_id = session_id
    state.task.status = "running"
    state.task.user_goal = "resume lifecycle"
    state.conversation.messages = [{"role": "user", "content": "continue"}]
    return state


def _load_selected_and_restore(session_id: str):
    import agent.session as session
    from agent.runtime_integration.skill_lifecycle import (
        restore_skill_lifecycle_from_checkpoint,
    )

    dst = _state(session_id)
    result = session._load_selected_checkpoint_to_state_best_effort(dst)
    if result.success:
        restore_skill_lifecycle_from_checkpoint(
            dst,
            result.checkpoint,
            source="tests.skill_checkpoint_resume",
        )
    return result


def _unsafe_text_from_checkpoint(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _evidence_operations(calls: list[dict[str, Any]]) -> set[str]:
    return {
        f"{call.get('subsystem')}.{call.get('operation')}"
        for call in calls
        if call.get("subsystem") and call.get("operation")
    }


def _assert_next_request_not_skill_polluted(
    session_id: str,
    *,
    stale_body: str,
) -> None:
    from agent import core

    prompt, _ = core.refresh_runtime_system_prompt(namespace_key=session_id)
    assert stale_body not in prompt

    client = FakeAnthropicClient([text_response("done")])
    loop_ctx = LoopContext(
        client=client,
        model_name="test-model",
        max_loop_iterations=1,
        runtime_identity=RuntimeIdentity(
            session_id=session_id,
            run_id="restore-test-run",
            instance_id=session_id,
        ),
    )
    core._call_model(core.TurnState(system_prompt=prompt), loop_ctx)

    visible_tool_names = {item["name"] for item in client.requests[-1]["tools"]}
    assert "run_shell" in visible_tool_names
    assert visible_tool_names != {"stale.tool", "SKILL_SELECT"}


def test_active_skill_checkpoint_restores_selected_skill_and_redacts_raw_content(
    tmp_path: Path,
    checkpoint_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_calls: list[dict[str, Any]],
) -> None:
    """active skill → gateway checkpoint → selected restore success → skill restored."""
    session_id = "skill-resume-success"
    skill_root = tmp_path / "skills"
    _write_skill(
        skill_root,
        "resume-skill",
        allowed_tools=("current.tool", "current.extra"),
    )
    _install_restore_registry(monkeypatch, skill_root)

    import agent.session as session

    monkeypatch.setattr(session, "_resolve_session_id", lambda: session_id)
    source_state = _state(session_id)
    lifecycle = get_default_lifecycle(session_id)
    lifecycle.activate(
        "resume-skill",
        body="old RAW_BODY_MARKER PROMPT_MARKER RESOURCE_MARKER SECRET_MARKER SKILL.md",
        allowed_tools=("stale.tool",),
    )

    save_runtime_checkpoint(
        source_state,
        source="tests.skill_checkpoint_resume.save",
        path=checkpoint_path,
        session_id=session_id,
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["skill"]["skill_id"] == "resume-skill"
    assert "skill" in checkpoint
    assert "body" not in checkpoint["skill"]
    assert checkpoint["skill"]["allowed_tools"] == ["stale.tool"]
    serialized = _unsafe_text_from_checkpoint(checkpoint_path)
    for marker in RAW_MARKERS:
        assert marker not in serialized

    lifecycle.deactivate()
    result = _load_selected_and_restore(session_id)

    assert result.success is True
    active = lifecycle.get_active()
    assert active is not None
    assert active.skill_id == "resume-skill"
    assert active.allowed_tools == ("current.tool", "current.extra")
    assert "RAW_BODY_MARKER" in active.body
    assert _evidence_operations(evidence_calls) >= {
        "checkpoint.save",
        "skill.restored",
    }
    evidence_text = json.dumps(evidence_calls, ensure_ascii=False)
    for marker in RAW_MARKERS:
        assert marker not in evidence_text


def test_restore_uses_current_manifest_allowed_tools_not_stale_checkpoint(
    tmp_path: Path,
    checkpoint_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "skill-resume-current-manifest"
    skill_root = tmp_path / "skills"
    _write_skill(skill_root, "tool-skill", allowed_tools=("new.tool",))
    _install_restore_registry(monkeypatch, skill_root)

    import agent.session as session

    monkeypatch.setattr(session, "_resolve_session_id", lambda: session_id)
    lifecycle = get_default_lifecycle(session_id)
    lifecycle.activate(
        "tool-skill",
        body="old body",
        allowed_tools=("old.stale.tool",),
    )
    save_runtime_checkpoint(
        _state(session_id),
        path=checkpoint_path,
        session_id=session_id,
    )

    lifecycle.deactivate()
    _load_selected_and_restore(session_id)

    active = lifecycle.get_active()
    assert active is not None
    assert active.allowed_tools == ("new.tool",)


def test_selected_checkpoint_changed_during_state_restore_clears_active_skill(
    tmp_path: Path,
    checkpoint_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_calls: list[dict[str, Any]],
) -> None:
    """如果实际恢复的 checkpoint 已变化，restore 使用重载后的选中内容。"""
    session_id = "skill-resume-mismatch"
    skill_root = tmp_path / "skills"
    _write_skill(skill_root, "race-skill")
    _install_restore_registry(monkeypatch, skill_root)

    import agent.session as session

    monkeypatch.setattr(session, "_resolve_session_id", lambda: session_id)
    lifecycle = get_default_lifecycle(session_id)
    lifecycle.activate("race-skill", body="old body", allowed_tools=("old.tool",))
    save_runtime_checkpoint(_state(session_id), path=checkpoint_path, session_id=session_id)

    changed_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    changed_checkpoint.pop("skill", None)
    original_load_to_state = session.load_checkpoint_to_state

    def _rewrite_then_load(state: Any, *, path: Path | None = None) -> bool:
        target = path or checkpoint_path
        target.write_text(
            json.dumps(changed_checkpoint, ensure_ascii=False),
            encoding="utf-8",
        )
        return bool(original_load_to_state(state, path=path))

    monkeypatch.setattr(session, "load_checkpoint_to_state", _rewrite_then_load)
    lifecycle.activate("stale-skill", body="stale", allowed_tools=("stale.tool",))

    result = _load_selected_and_restore(session_id)

    assert result.success is True
    assert result.checkpoint is not None
    assert "skill" not in result.checkpoint
    assert lifecycle.get_active() is None
    assert "skill.restore_cleared" in _evidence_operations(evidence_calls)


def test_state_restore_failed_clears_existing_active_skill(
    tmp_path: Path,
    checkpoint_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_calls: list[dict[str, Any]],
) -> None:
    session_id = "skill-resume-state-failed"
    skill_root = tmp_path / "skills"
    _write_skill(skill_root, "resume-skill")
    _install_restore_registry(monkeypatch, skill_root)

    import agent.session as session
    from agent.runtime_integration.skill_lifecycle import clear_skill_lifecycle_for_resume

    monkeypatch.setattr(session, "_resolve_session_id", lambda: session_id)
    lifecycle = get_default_lifecycle(session_id)
    lifecycle.activate("resume-skill", body="body", allowed_tools=("old.tool",))
    save_runtime_checkpoint(_state(session_id), path=checkpoint_path, session_id=session_id)
    lifecycle.activate("stale-skill", body="stale", allowed_tools=("stale.tool",))

    monkeypatch.setattr(
        session,
        "load_checkpoint_to_state",
        lambda _state, *, path=None: False,
    )
    result = session._load_selected_checkpoint_to_state_best_effort(_state(session_id))
    if not result.success:
        clear_skill_lifecycle_for_resume(
            _state(session_id),
            reason="state_restore_failed",
            source="tests.skill_checkpoint_resume",
        )

    assert result.success is False
    assert lifecycle.get_active() is None
    assert "skill.restore_cleared" in _evidence_operations(evidence_calls)


def test_old_checkpoint_missing_skill_section_clears_existing_active_skill(
    tmp_path: Path,
    checkpoint_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_calls: list[dict[str, Any]],
) -> None:
    session_id = "skill-resume-old-checkpoint"
    skill_root = tmp_path / "skills"
    _write_skill(skill_root, "old-skill")
    _install_restore_registry(monkeypatch, skill_root)

    import agent.session as session

    monkeypatch.setattr(session, "_resolve_session_id", lambda: session_id)
    lifecycle = get_default_lifecycle(session_id)
    save_runtime_checkpoint(_state(session_id), path=checkpoint_path, session_id=session_id)
    assert "skill" not in json.loads(checkpoint_path.read_text(encoding="utf-8"))

    stale_body = "STALE_MISSING_SKILL_SECTION_BODY"
    lifecycle.activate("old-skill", body=stale_body, allowed_tools=("stale.tool",))
    _load_selected_and_restore(session_id)

    assert lifecycle.get_active() is None
    assert "skill.restore_cleared" in _evidence_operations(evidence_calls)
    assert any(
        "checkpoint_missing_skill_section" in str(call.get("safe_summary", ""))
        for call in evidence_calls
    )
    _assert_next_request_not_skill_polluted(session_id, stale_body=stale_body)


def test_loader_failure_clears_active_skill_without_half_restore(
    tmp_path: Path,
    checkpoint_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_calls: list[dict[str, Any]],
) -> None:
    session_id = "skill-resume-loader-failure"
    skill_root = tmp_path / "skills"
    _write_skill(skill_root, "broken-body-skill")
    _install_restore_registry(monkeypatch, skill_root)

    import agent.session as session
    from agent.skill_system.loader import SkillLoader

    monkeypatch.setattr(session, "_resolve_session_id", lambda: session_id)
    lifecycle = get_default_lifecycle(session_id)
    lifecycle.activate(
        "broken-body-skill",
        body="old body",
        allowed_tools=("old.tool",),
    )
    save_runtime_checkpoint(
        _state(session_id),
        path=checkpoint_path,
        session_id=session_id,
    )

    stale_body = "STALE_LOADER_FAILURE_BODY"
    lifecycle.activate("stale-skill", body=stale_body, allowed_tools=("stale.tool",))

    def _fail_load_body(self: SkillLoader, name: str) -> str:
        raise RuntimeError(f"cannot load {name}")

    monkeypatch.setattr(SkillLoader, "load_body", _fail_load_body)

    result = _load_selected_and_restore(session_id)

    assert result.success is True
    assert lifecycle.get_active() is None
    assert "skill.restore_cleared" in _evidence_operations(evidence_calls)
    assert any(
        "body_load_failed" in str(call.get("safe_summary", ""))
        for call in evidence_calls
    )
    _assert_next_request_not_skill_polluted(session_id, stale_body=stale_body)


@pytest.mark.parametrize(
    ("case", "metadata_skill_id", "status", "extra_sections"),
    [
        ("missing", "missing-skill", None, None),
        ("disabled", "disabled-skill", "disabled", None),
        ("invalid", None, None, {"skill": {"allowed_tools": ["old.tool"]}}),
    ],
)
def test_missing_disabled_or_invalid_skill_metadata_clears_safely(
    case: str,
    metadata_skill_id: str | None,
    status: str | None,
    extra_sections: dict[str, Any] | None,
    tmp_path: Path,
    checkpoint_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_calls: list[dict[str, Any]],
) -> None:
    session_id = f"skill-resume-{case}"
    skill_root = tmp_path / "skills"
    if metadata_skill_id and status is not None:
        _write_skill(skill_root, metadata_skill_id, status=status)
    else:
        skill_root.mkdir(parents=True, exist_ok=True)
    _install_restore_registry(monkeypatch, skill_root)

    import agent.session as session

    monkeypatch.setattr(session, "_resolve_session_id", lambda: session_id)
    lifecycle = get_default_lifecycle(session_id)
    if metadata_skill_id is not None:
        lifecycle.activate(metadata_skill_id, body="body", allowed_tools=("old.tool",))
    else:
        lifecycle.deactivate()
    save_runtime_checkpoint(
        _state(session_id),
        path=checkpoint_path,
        session_id=session_id,
        extra_sections=extra_sections,
    )
    stale_body = f"STALE_{case.upper()}_SKILL_BODY"
    lifecycle.activate("stale-skill", body=stale_body, allowed_tools=("stale.tool",))

    result = _load_selected_and_restore(session_id)

    assert result.success is True
    assert lifecycle.get_active() is None
    assert "skill.restore_cleared" in _evidence_operations(evidence_calls)
    _assert_next_request_not_skill_polluted(session_id, stale_body=stale_body)
    evidence_text = json.dumps(evidence_calls, ensure_ascii=False)
    for marker in RAW_MARKERS:
        assert marker not in evidence_text

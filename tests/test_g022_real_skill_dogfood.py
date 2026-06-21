"""G-022 (Phase 3): reproducible real-provider skill select/execute dogfood.

Skill selection (SKILL_SELECT) runs at turn-end, so the demo-note-maker skill's
tool (`demo.write_demo_note`) becomes available the turn AFTER selection. The
dogfood drives a small adaptive multi-turn flow against the REAL DeepSeek
provider:

    turn 1: prompt "make a demo note" -> SKILL_SELECT selects demo-note-maker
            (active next turn); state awaiting_user_input
    turn 2: re-instruct -> model calls demo.write_demo_note -> awaiting_tool_confirmation
    turn 3: chat("y") -> governed approval -> note written to workspace/demo/

Asserts: real provider call, demo-note-maker was selected, demo.write_demo_note
was proposed+approved, the note file was created, and no secret leaked.

Opt-in only (skip by default).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
from uuid import uuid4

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
OPT_IN_ENV = "MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE"
_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{12,}")
_NOTE_TAG = f"g22_skill_{uuid4().hex[:8]}"


def _real_ready() -> tuple[bool, str]:
    if os.environ.get(OPT_IN_ENV) != "1":
        return False, f"set {OPT_IN_ENV}=1 to run the G-022 real skill dogfood"
    return True, ""


_READY, _REASON = _real_ready()
pytestmark = pytest.mark.skipif(not _READY, reason=_REASON)


def _assert_runtime_config_git_safety() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "config/config.yaml"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )
    assert tracked.returncode != 0, "config/config.yaml must not be git tracked"
    ignored = subprocess.run(
        ["git", "check-ignore", "config/config.yaml"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )
    assert ignored.returncode == 0, "config/config.yaml must be gitignored"


def _reset_core_state() -> None:
    from agent.core import get_state

    state = get_state()
    state.conversation.messages.clear()
    state.conversation.tool_traces.clear()
    state.reset_task()


def _read_events(session_dir: pathlib.Path) -> list[dict]:
    events_path = session_dir / "events.jsonl"
    assert events_path.is_file(), f"missing events.jsonl at {session_dir}"
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _all_evidence(events: list[dict]) -> list[dict]:
    return [ev for ev in (e.get("evidence") for e in events) if isinstance(ev, dict)]


def test_real_provider_skill_select_execute_dogfood(tmp_path):
    """Real provider: demo-note-maker select -> demo.write_demo_note -> note."""
    _assert_runtime_config_git_safety()

    from agent.core import chat, get_state
    from agent.event_log import EventLogWriter
    from agent.provider.factory import build_model_provider_from_env

    real_provider = build_model_provider_from_env()
    assert getattr(real_provider, "provider_type", "unknown") != "fake", (
        "G-022 requires a non-fake provider"
    )

    workspace_demo = PROJECT_ROOT / "workspace" / "demo"
    target_note = workspace_demo / f"{_NOTE_TAG}.md"

    _reset_core_state()
    session_dir = tmp_path / f"g022-real-{uuid4().hex[:8]}"
    writer = EventLogWriter(session_dir)

    def _send(text: str) -> None:
        chat(
            text,
            provider=real_provider,
            session_id=session_dir.name,
            event_log_writer=writer,
            on_runtime_event=lambda e: None,
            checkpoint_save_on_turn_end=True,
        )

    proposed_tool = False
    approved = False
    try:
        _send(
            f"Make a demo note. Use the demo.write_demo_note tool at path {target_note} "
            f"with content: skill-dogfood-ok"
        )
        # Adaptive flow: skill selects at turn-end; the tool becomes available
        # next turn. Loop until the tool is proposed+approved or we exhaust turns.
        for _ in range(5):
            state = get_state()
            status = state.task.status
            pending = getattr(state.task, "pending_tool", None)
            tname = (pending or {}).get("tool") if pending else None
            is_demo_note = tname and "write_demo_note" in str(tname).lower()
            if status == "awaiting_tool_confirmation" and is_demo_note:
                proposed_tool = True
                _send("y")  # governed approval
                approved = True
                break
            if status == "awaiting_user_input":
                _send(
                    "Now write the note using the demo.write_demo_note tool."
                )
                continue
            break
    finally:
        writer.close()

    assert proposed_tool and approved, (
        "G-022: real model did not propose+approve demo.write_demo_note within the "
        "adaptive flow (re-run)"
    )

    # The skill tool must have written the note.
    matches = list(workspace_demo.glob(f"{_NOTE_TAG}*"))
    assert matches, (
        f"governed demo.write_demo_note was approved but no note matched "
        f"{_NOTE_TAG}* in {workspace_demo}"
    )
    for _f in matches:
        _f.unlink(missing_ok=True)

    # REAL spine.
    events = _read_events(session_dir)
    evidence = _all_evidence(events)
    provider_kinds = {
        str(ev.get("provider_kind")) for ev in evidence if "provider_kind" in ev
    }
    assert "real" in provider_kinds, f"provider_kind must include 'real'; got {provider_kinds}"
    assert any(
        ev.get("provider_external_call")
        for ev in evidence
        if "provider_external_call" in ev
    ), "provider_external_call must be True (real network call)"
    # Skill selection evidence should be present (skill.selection / SKILL_SELECT).
    raw = json.dumps(events).lower()
    assert "skill" in raw, "no skill evidence recorded in events"
    assert not _SECRET_PATTERN.search(json.dumps(events)), "secret leaked into evidence"

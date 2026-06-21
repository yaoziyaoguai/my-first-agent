"""G-015 (Phase 2): broaden real-proven governed tool coverage to edit_file.

G-010 (Phase 1) reproducibly proved the real provider governed ``write_file``
tool-use spine. G-015 extends real-proven coverage to a SECOND governed mutating
tool — ``edit_file`` — beyond write_file, satisfying "at least one more governed
tool beyond write_file".

Flow (programmatic, same spine as G-010):

    pre-create workspace file with "original-content"
    chat(prompt: edit the file to "edited-content-g15")
      -> model emits edit_file tool_use -> awaiting_tool_confirmation
    chat("y") -> governed approval -> edit executor -> tool_result -> final
    assert the file content changed to "edited-content-g15"

Opt-in only (skip by default). Model output is non-deterministic; the harness
asserts the real spine and the governed edit resolved, and never prints secrets.
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


def _real_ready() -> tuple[bool, str]:
    if os.environ.get(OPT_IN_ENV) != "1":
        return False, f"set {OPT_IN_ENV}=1 to run the G-015 real edit_file dogfood"
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


def test_real_provider_governed_edit_file_dogfood(tmp_path):
    """Drive the real provider through a governed edit_file tool_use."""
    _assert_runtime_config_git_safety()

    from agent.core import chat, get_state
    from agent.event_log import EventLogWriter
    from agent.provider.factory import build_model_provider_from_env

    real_provider = build_model_provider_from_env()
    assert getattr(real_provider, "provider_type", "unknown") != "fake", (
        "G-015 requires a non-fake provider"
    )

    workspace_dir = PROJECT_ROOT / "workspace"
    workspace_dir.mkdir(exist_ok=True)
    tag = f"g15_edit_{uuid4().hex[:8]}"
    target_file = workspace_dir / f"{tag}.txt"
    target_file.write_text("original-content", encoding="utf-8")

    _reset_core_state()
    session_dir = tmp_path / f"g015-real-{uuid4().hex[:8]}"
    writer = EventLogWriter(session_dir)
    prompt = (
        f"Use the edit_file tool to change the entire content of {target_file} "
        f"to exactly: edited-content-g15"
    )

    tool_name = None
    approved = False
    edited_ok = False
    try:
        chat(
            prompt,
            provider=real_provider,
            session_id=session_dir.name,
            event_log_writer=writer,
            on_runtime_event=lambda e: None,
            checkpoint_save_on_turn_end=True,
        )
        state = get_state()
        pending = getattr(state.task, "pending_tool", None)
        tool_name = pending.get("tool") if pending else None
        assert (
            state.task.status == "awaiting_tool_confirmation"
            and tool_name
            and "edit" in str(tool_name).lower()
        ), (
            "G-015: real model did not propose edit_file for the edit prompt this "
            "run (re-run)"
        )

        chat(
            "y",
            provider=real_provider,
            session_id=session_dir.name,
            event_log_writer=writer,
            on_runtime_event=lambda e: None,
            checkpoint_save_on_turn_end=True,
        )
        approved = True
        assert get_state().task.status != "awaiting_tool_confirmation", (
            "chat('y') did not resolve the pending edit_file confirmation"
        )
        # Capture the edit result BEFORE the finally deletes the file.
        edited_ok = target_file.exists() and (
            target_file.read_text(encoding="utf-8").strip() == "edited-content-g15"
        )
    finally:
        writer.close()
        target_file.unlink(missing_ok=True)

    # The governed edit_file must have changed the file content to the new value.
    assert approved and edited_ok, (
        "governed edit_file was approved but did not change the file content to "
        "'edited-content-g15'"
    )

    # Read events for the real-spine proof.
    events_path = session_dir / "events.jsonl"
    assert events_path.is_file(), "missing events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    evidence = [
        ev for ev in (e.get("evidence") for e in events) if isinstance(ev, dict)
    ]
    provider_kinds = {
        str(ev.get("provider_kind")) for ev in evidence if "provider_kind" in ev
    }
    assert "real" in provider_kinds, f"provider_kind must include 'real'; got {provider_kinds}"
    assert any(
        ev.get("provider_external_call") for ev in evidence if "provider_external_call" in ev
    ), "provider_external_call must be True (real network call)"
    assert not _SECRET_PATTERN.search(json.dumps(events)), "secret leaked into evidence"

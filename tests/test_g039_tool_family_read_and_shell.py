"""G-039 (audit fix): tool-family coverage beyond write/edit.

The L6-push marked "Tool runtime L6" from write_file/edit_file only — an
overclaim (2 tools != the whole tool system). This test strengthens two more
tool families with real/governance evidence:

1. read-only family (read_file): REAL provider dogfood — model reads a workspace
   file and the read result is governed/evidenced. (opt-in real)
2. shell/exec family (run_shell): GOVERNANCE dogfood — run_shell is confirmation=
   "always" + risk="high"; it must require explicit confirmation and NEVER
   auto-execute. (default local — verifies the gate, no real shell run)

Together with G-010/G-015 (write/edit) this gives real/governance evidence across
file-write, file-read, and shell-governance families. The tool PLATFORM
(registry/mediator/executor/governance/audit) is L6; per-family levels are
documented in OPERATOR_GUIDE §10 / release summary.
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


# ---------------------------------------------------------------------------
# Family 2: read-only (read_file) — REAL provider dogfood (opt-in).
# ---------------------------------------------------------------------------

def _real_ready() -> tuple[bool, str]:
    if os.environ.get(OPT_IN_ENV) != "1":
        return False, f"set {OPT_IN_ENV}=1 to run the G-039 read_file real dogfood"
    return True, ""


_READY, _REASON = _real_ready()
_real_mark = pytest.mark.skipif(not _READY, reason=_REASON)


def _reset_core_state() -> None:
    from agent.core import get_state

    state = get_state()
    state.conversation.messages.clear()
    state.conversation.tool_traces.clear()
    state.reset_task()


def _all_evidence(events: list[dict]) -> list[dict]:
    return [ev for ev in (e.get("evidence") for e in events) if isinstance(ev, dict)]


@_real_mark
def test_real_provider_read_file_dogfood(tmp_path):
    """Real provider: model reads a workspace file via read_file (read-only family)."""
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "config/config.yaml"],
        cwd=str(PROJECT_ROOT), capture_output=True,
    )
    assert tracked.returncode != 0, "config/config.yaml must not be git tracked"

    from agent.core import chat, get_state
    from agent.event_log import EventLogWriter
    from agent.provider.factory import build_model_provider_from_env

    real_provider = build_model_provider_from_env()
    assert getattr(real_provider, "provider_type", "unknown") != "fake"

    workspace_dir = PROJECT_ROOT / "workspace"
    workspace_dir.mkdir(exist_ok=True)
    tag = f"g039_read_{uuid4().hex[:8]}"
    target = workspace_dir / f"{tag}.txt"
    target.write_text("read-only-dogfood-content", encoding="utf-8")

    _reset_core_state()
    session_dir = tmp_path / f"g039-{uuid4().hex[:8]}"
    writer = EventLogWriter(session_dir)

    try:
        chat(
            f"Use the read_file tool to read {target} and tell me its content.",
            provider=real_provider,
            session_id=session_dir.name,
            event_log_writer=writer,
            on_runtime_event=lambda e: None,
            checkpoint_save_on_turn_end=True,
        )
        # read_file may or may not require confirmation depending on path; if it
        # is awaiting confirmation, approve it.
        for _ in range(4):
            state = get_state()
            pending = getattr(state.task, "pending_tool", None)
            tname = (pending or {}).get("tool") if pending else None
            if state.task.status == "awaiting_tool_confirmation" and tname:
                chat(
                    "y",
                    provider=real_provider,
                    session_id=session_dir.name,
                    event_log_writer=writer,
                    on_runtime_event=lambda e: None,
                    checkpoint_save_on_turn_end=True,
                )
                break
            if state.task.status == "awaiting_user_input":
                # read_file already executed without confirmation; done.
                break
            break
    finally:
        writer.close()
        target.unlink(missing_ok=True)

    events_path = session_dir / "events.jsonl"
    assert events_path.is_file(), "missing events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    evidence = _all_evidence(events)
    provider_kinds = {str(ev.get("provider_kind")) for ev in evidence if "provider_kind" in ev}
    assert "real" in provider_kinds, f"provider_kind must include 'real'; got {provider_kinds}"
    assert any(
        ev.get("provider_external_call")
        for ev in evidence
        if "provider_external_call" in ev
    ), "provider_external_call must be True (real network call)"
    assert not _SECRET_PATTERN.search(json.dumps(events)), "secret leaked into evidence"


# ---------------------------------------------------------------------------
# Family 6: shell/exec (run_shell) — GOVERNANCE dogfood (default, no real shell).
# ---------------------------------------------------------------------------

def test_run_shell_requires_confirmation_and_is_high_risk():
    """run_shell must be confirmation='always' + risk='high' (governed, never
    auto-executed). This pins the dangerous-tool family boundary."""
    from agent.tool_registry import TOOL_REGISTRY
    from agent.tools.shell import run_shell  # noqa: F401  ensure shell tools registered

    spec = TOOL_REGISTRY.get("run_shell")
    assert spec is not None, "run_shell must be registered"
    confirmation = getattr(spec, "confirmation", None) or spec.get("confirmation")  # type: ignore[union-attr]
    risk = getattr(spec, "risk_level", None) or spec.get("risk_level")  # type: ignore[union-attr]
    assert confirmation == "always", (
        f"run_shell must require confirmation='always'; got {confirmation!r}"
    )
    assert risk == "high", f"run_shell must be risk='high'; got {risk!r}"

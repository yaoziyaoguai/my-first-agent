"""G-019 (Phase 3): reproducible real-provider memory write/recall/audit dogfood.

Drives the REAL DeepSeek provider through the governed memory path:

    chat(prompt: use MEMORY_REMEMBER_REQUEST to remember X)
      -> model calls MEMORY_REMEMBER_REQUEST -> pending_user_input_request
         (awaiting_kind="memory_confirmation")
    chat("y") -> handle_memory_confirmation_reply approves -> memory stored
    verify: memory_runtime.list_records() contains a record carrying X
            (real recall via the store)

This resolves the prior G-019 blocker (the memory-anchor smoke was
non-deterministic for soft prompts); here a direct tool-use instruction makes
the model reliably call MEMORY_REMEMBER_REQUEST, and the separate
memory_confirmation pending mechanism is approved programmatically.

Opt-in only (skip by default). Model output is non-deterministic; the harness
hard-asserts the model proposed the memory tool (re-run if not) and never
prints secrets.
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
_REMEMBER_FACT = "the user's favorite color is blue"


def _real_ready() -> tuple[bool, str]:
    if os.environ.get(OPT_IN_ENV) != "1":
        return False, f"set {OPT_IN_ENV}=1 to run the G-019 real memory dogfood"
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


def test_real_provider_memory_write_recall_audit(tmp_path):
    """Real provider: governed memory remember -> approve -> stored -> recall."""
    _assert_runtime_config_git_safety()

    from agent.core import chat, get_memory_runtime, get_state
    from agent.event_log import EventLogWriter
    from agent.provider.factory import build_model_provider_from_env

    real_provider = build_model_provider_from_env()
    assert getattr(real_provider, "provider_type", "unknown") != "fake", (
        "G-019 requires a non-fake provider"
    )

    _reset_core_state()
    session_id = f"g019-real-{uuid4().hex[:8]}"
    session_dir = tmp_path / session_id
    writer = EventLogWriter(session_dir)
    prompt = (
        f"Use the MEMORY_REMEMBER_REQUEST tool to remember this fact: "
        f"{_REMEMBER_FACT}."
    )

    proposed_memory = False
    approved = False
    try:
        chat(
            prompt,
            provider=real_provider,
            session_id=session_id,
            event_log_writer=writer,
            on_runtime_event=lambda e: None,
            checkpoint_save_on_turn_end=True,
        )
        state = get_state()
        pending_ui = getattr(state.task, "pending_user_input_request", None) or {}
        kind = pending_ui.get("awaiting_kind") if isinstance(pending_ui, dict) else None
        # The model must propose a memory confirmation (re-run if it did not).
        assert kind == "memory_confirmation", (
            f"G-019: model did not propose memory_confirmation this run "
            f"(awaiting_kind={kind!r}); re-run"
        )
        proposed_memory = True

        chat(
            "y",
            provider=real_provider,
            session_id=session_id,
            event_log_writer=writer,
            on_runtime_event=lambda e: None,
            checkpoint_save_on_turn_end=True,
        )
        approved = True
    finally:
        writer.close()

    assert proposed_memory and approved, "memory propose/approve did not complete"

    # REAL spine: a real provider call happened.
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

    # Recall: the per-session memory store must hold a record carrying the fact.
    runtime = get_memory_runtime(session_id)
    records = runtime.list_records() if runtime is not None else ()
    serialized = json.dumps([str(r) for r in records], ensure_ascii=False).lower()
    assert "blue" in serialized, (
        f"governed memory write was approved but no stored record carries the "
        f"fact (records={len(records)})"
    )

    # No secret in evidence.
    assert not _SECRET_PATTERN.search(json.dumps(events)), "secret leaked into evidence"

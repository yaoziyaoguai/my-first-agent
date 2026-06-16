"""S1 AC-2 fake/real core evidence smoke.

This opt-in smoke verifies runtime artifacts, not model text equivalence:
both FakeProvider and a real provider enter ``core.chat()`` and write an
``events.jsonl`` through the same EventLogWriter path.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPT_IN_ENV = "MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE"
EVIDENCE_ROOT_ENV = "MY_FIRST_AGENT_S1_CORE_EVIDENCE_ROOT"

pytestmark = pytest.mark.skipif(
    os.environ.get(OPT_IN_ENV) != "1",
    reason=f"real provider core evidence smoke requires {OPT_IN_ENV}=1",
)

SHARED_CORE_ACTIONS = {
    "memory.recall",
    "memory.turn_end_proposal",
    "tool.gate",
    "skill.select",
    "checkpoint.save",
}


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


def _assert_runtime_config_git_safety() -> None:
    """Verify ignored local config safety without reading config contents."""

    rel_path = "config/config.yaml"
    tracked = _git("ls-files", "--error-unmatch", rel_path)
    assert tracked.returncode != 0, "config/config.yaml must not be git tracked"

    ignored = _git("check-ignore", rel_path)
    assert ignored.returncode == 0, "config/config.yaml must be ignored by .gitignore"


def _reset_core_state() -> None:
    from agent.core import get_state

    state = get_state()
    state.conversation.messages.clear()
    state.conversation.tool_traces.clear()
    state.reset_task()


def _session_dir(tmp_path: Path, label: str) -> Path:
    override = os.environ.get(EVIDENCE_ROOT_ENV)
    if not override:
        return tmp_path / f"s1-td007-{label}-{uuid4().hex[:8]}"

    root = Path(override)
    base = root if root.is_absolute() else PROJECT_ROOT / root

    try:
        base.relative_to(PROJECT_ROOT / "sessions")
    except ValueError:
        if base != PROJECT_ROOT / "sessions":
            raise AssertionError(
                f"{EVIDENCE_ROOT_ENV} must be 'sessions' or a child of sessions/"
            ) from None
    return base / f"s1-td007-{label}-{uuid4().hex[:8]}"


def _run_core_chat_to_events(*, provider, tmp_path: Path, label: str) -> tuple[Path, list[dict]]:
    from agent.core import chat
    from agent.event_log import EventLogWriter

    _reset_core_state()
    session_dir = _session_dir(tmp_path, label)
    writer = EventLogWriter(session_dir)
    runtime_events: list[object] = []
    try:
        result = chat(
            "S1 core evidence smoke: reply briefly without using tools.",
            provider=provider,
            session_id=session_dir.name,
            event_log_writer=writer,
            on_runtime_event=lambda event: runtime_events.append(event),
            checkpoint_save_on_turn_end=True,
        )
    finally:
        writer.close()

    assert isinstance(result, str)
    events_path = session_dir / "events.jsonl"
    assert events_path.is_file(), f"missing events.jsonl for {label}"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events, f"events.jsonl must not be empty for {label}"
    return events_path, events


def _action_names(events: list[dict]) -> set[str]:
    return {str(event.get("action_type", "")) for event in events}


def _provider_evidence(events: list[dict], action_type: str) -> dict:
    for event in events:
        if event.get("action_type") == action_type and isinstance(event.get("evidence"), dict):
            evidence = dict(event["evidence"])
            if "provider_kind" in evidence:
                return evidence
    raise AssertionError(f"no provider evidence found for {action_type}")


def test_s1_fake_and_real_core_chat_write_comparable_events_jsonl(tmp_path):
    """Fake and real providers share core.chat() evidence spine."""

    _assert_runtime_config_git_safety()

    from agent.provider.factory import build_model_provider_from_env
    from agent.provider.fake_provider import FakeProvider

    real_provider = build_model_provider_from_env()
    real_provider_type = getattr(real_provider, "provider_type", "unknown")
    assert real_provider_type != "fake", (
        "real provider smoke requires ignored local runtime config resolving to non-fake"
    )

    fake_path, fake_events = _run_core_chat_to_events(
        provider=FakeProvider(),
        tmp_path=tmp_path,
        label="fake",
    )
    real_path, real_events = _run_core_chat_to_events(
        provider=real_provider,
        tmp_path=tmp_path,
        label="real",
    )

    fake_actions = _action_names(fake_events)
    real_actions = _action_names(real_events)
    missing_fake = SHARED_CORE_ACTIONS - fake_actions
    missing_real = SHARED_CORE_ACTIONS - real_actions
    assert not missing_fake, f"fake events missing core actions: {sorted(missing_fake)}"
    assert not missing_real, f"real events missing core actions: {sorted(missing_real)}"

    fake_provider_evidence = _provider_evidence(fake_events, "memory.turn_end_proposal")
    real_provider_evidence = _provider_evidence(real_events, "memory.turn_end_proposal")

    assert fake_provider_evidence.get("core_entrypoint") == "core.chat"
    assert real_provider_evidence.get("core_entrypoint") == "core.chat"
    assert fake_provider_evidence.get("provider_kind") == "fake"
    assert fake_provider_evidence.get("provider_external_call") is False
    assert real_provider_evidence.get("provider_kind") == "real"
    assert real_provider_evidence.get("provider_external_call") is True

    assert fake_path.name == "events.jsonl"
    assert real_path.name == "events.jsonl"

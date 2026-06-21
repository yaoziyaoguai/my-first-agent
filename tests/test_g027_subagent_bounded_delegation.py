"""G-027 (Phase 4): bounded SubAgent delegation dogfood.

The bounded delegation path is by design: a deterministic NL trigger fires
`SUBAGENT_DELEGATE_L1` -> falls back to inline-L0 with a `local_fake`, read-only
child (demo-stat: `allowed_tools=[read_file]`, `supported_modes=[local_fake]`,
no writable tools). This is the read-only safety boundary the user requires
("完成 bounded delegation，不得无治理激活 writable").

The NL delegation path short-circuits before the main loop, so delegation
evidence is emitted via `on_runtime_event` (run_summary with
`subagent_delegations=1`), not events.jsonl. The test captures those events and
asserts the bounded delegation fired with NO writable tool.

Maturity note: the bounded child is local_fake BY DESIGN (read-only safety). The
V0 real-child path (second real agent loop) is the L4 path, gated by
`SUBAGENT_V0_ROUTING_ENABLED` + `MY_FIRST_AGENT_S3_SUBAGENT_ENABLE` +
`real_opt_in` profile + `parent_opt_in`; not activated here (a second
unsupervised real agent loop is high-risk autonomy). This test productizes the
BOUNDED delegation; SubAgent real-child L4 remains the heavy gated path.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
from uuid import uuid4

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{12,}")


def _reset_core_state() -> None:
    from agent.core import get_state

    state = get_state()
    state.conversation.messages.clear()
    state.conversation.tool_traces.clear()
    state.reset_task()


def test_subagent_bounded_delegation_governed_no_writable(tmp_path):
    """Bounded delegation: NL trigger -> demo-stat read-only child -> no writable."""
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "config/config.yaml"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )
    assert tracked.returncode != 0, "config/config.yaml must not be git tracked"

    from agent.core import chat
    from agent.event_log import EventLogWriter

    _reset_core_state()
    session_dir = tmp_path / f"g027-{uuid4().hex[:8]}"
    writer = EventLogWriter(session_dir)
    runtime_events: list[object] = []
    delegation_prompt = "帮我统计 demo workspace 的文件数量"

    try:
        result = chat(
            delegation_prompt,
            session_id=session_dir.name,
            event_log_writer=writer,
            on_runtime_event=lambda e: runtime_events.append(e),
            checkpoint_save_on_turn_end=True,
        )
    finally:
        writer.close()

    # The delegation must have produced a non-empty result.
    assert isinstance(result, str) and result.strip(), (
        "bounded delegation returned no result"
    )

    # Delegation evidence: a run_summary (or delegation) runtime event must fire.
    raw_events = json.dumps(
        [getattr(e, "__dict__", str(e)) for e in runtime_events],
        ensure_ascii=False,
        default=str,
    ).lower()
    assert (
        "delegat" in raw_events
        or "subagent" in raw_events
        or "demo-stat" in raw_events
        or "demo_stat" in raw_events
    ), f"no delegation evidence in runtime events; got: {raw_events[:300]}"

    # Bounded: the demo-stat descriptor is read-only (read_file, no writable).
    desc = (
        PROJECT_ROOT
        / "agent"
        / "subagent_system"
        / "descriptors"
        / "demo-stat"
        / "SUBAGENT.md"
    ).read_text(encoding="utf-8")
    assert "read_file" in desc
    assert "write_file" not in desc and "run_shell" not in desc, (
        "demo-stat descriptor must remain read-only (no writable tools)"
    )
    # No secret in the captured events / result.
    assert not _SECRET_PATTERN.search(result), "secret leaked into delegation result"
    assert not _SECRET_PATTERN.search(raw_events), "secret leaked into runtime events"

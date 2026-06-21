"""R-G03: CLI checkpoint/resume contract validation.

Validates the checkpoint save → load → state-restored contract that the CLI relies on
for Ctrl+C → resume. Uses the real agent state factory + checkpoint functions (the same
path main.py uses). This is the module-level contract; CLI-level (PTY) validation is
covered by the interactive Run 12 manual smoke.
"""

from __future__ import annotations

from agent.checkpoint import clear_checkpoint, load_checkpoint_to_state, save_checkpoint
from agent.state import create_agent_state


def test_checkpoint_save_load_restores_task_state(tmp_path):
    """R-G03: checkpoint save → load → task state restored correctly."""
    cp = tmp_path / "resume_contract.json"
    state1 = create_agent_state(system_prompt="resume test")
    state1.task.status = "running"
    state1.task.current_step_index = 1
    state1.task.user_goal = "resume contract test"
    save_checkpoint(state1, source="r_g03_test", path=cp)

    state2 = create_agent_state(system_prompt="resume test")
    assert load_checkpoint_to_state(state2, path=cp) is True
    assert state2.task.status == "running"
    assert state2.task.current_step_index == 1
    assert state2.task.user_goal == "resume contract test"
    clear_checkpoint(path=cp)


def test_checkpoint_load_missing_returns_false(tmp_path):
    """R-G03: loading a non-existent checkpoint returns False (no crash)."""
    state = create_agent_state(system_prompt="resume test")
    assert load_checkpoint_to_state(state, path=tmp_path / "absent.json") is False

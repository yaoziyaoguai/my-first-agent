"""G-044a (Scheduler): safety-gated visibility + NO-OP/report-only lifecycle.

Tests the scheduled-action registry: create/list/get/cancel/fire_noop.
The registry is a VISIBILITY + REPORT layer — NO tool/memory/subagent execution.
"""

from __future__ import annotations

import pytest

from agent.scheduled_action_registry import (
    ScheduledActionRegistry,
    format_action_list,
)


def test_create_noop_action():
    """create() returns a pending NO-OP action."""
    reg = ScheduledActionRegistry()
    action = reg.create("test: daily report")
    assert action.action_type == "no_op"
    assert action.status == "pending"
    assert action.description == "test: daily report"
    assert action.action_id  # non-empty id


def test_list_actions():
    """list_actions() returns all created actions."""
    reg = ScheduledActionRegistry()
    reg.create("action 1")
    reg.create("action 2")
    actions = reg.list_actions()
    assert len(actions) == 2


def test_cancel_pending_action():
    """cancel() gracefully cancels a pending action."""
    reg = ScheduledActionRegistry()
    action = reg.create("to be cancelled")
    assert reg.cancel(action.action_id) is True
    cancelled = reg.get(action.action_id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None


def test_cancel_nonexistent_returns_false():
    """cancel() returns False for unknown id."""
    reg = ScheduledActionRegistry()
    assert reg.cancel("nonexistent") is False


def test_fire_noop_executes_nothing_dangerous():
    """fire_noop() fires a NO-OP action, marks it fired, executes NOTHING."""
    reg = ScheduledActionRegistry()
    action = reg.create("noop fire test")
    result = reg.fire_noop(action.action_id)
    assert "NO-OP fired" in result
    assert "no tool/memory/subagent executed" in result
    fired = reg.get(action.action_id)
    assert fired is not None
    assert fired.status == "fired"
    assert fired.fired_at is not None


def test_fire_cancelled_action_fails():
    """fire_noop() cannot fire a cancelled action."""
    reg = ScheduledActionRegistry()
    action = reg.create("cancelled before fire")
    reg.cancel(action.action_id)
    result = reg.fire_noop(action.action_id)
    assert "cannot fire" in result


def test_create_rejects_execution_type():
    """create() rejects action_type that implies execution (safety)."""
    reg = ScheduledActionRegistry()
    with pytest.raises(ValueError, match="no_op.*report"):
        reg.create("dangerous", action_type="execute_tool")


def test_format_action_list():
    """format_action_list() renders a readable list."""
    reg = ScheduledActionRegistry()
    reg.create("test report")
    out = format_action_list(reg.list_actions())
    assert "test report" in out
    assert "pending" in out


def test_format_empty_list():
    """format_action_list() handles empty gracefully."""
    out = format_action_list(())
    assert "No scheduled actions" in out

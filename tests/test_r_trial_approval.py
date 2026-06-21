"""R-G04: trial-only approval harness tests.

Validates the safety logic: default off; safe-allowlist only; safe-path only;
dangerous tools rejected; evidence recorded. This is the test-only first step; the
main.py wiring requires interactive-CLI regression testing.
"""

from __future__ import annotations

from agent.trial_approval import (
    can_trial_approve,
    is_trial_approval_enabled,
    record_trial_approval,
)


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FIRSTAGENT_TRIAL_APPROVAL_POLICY", raising=False)
    assert not is_trial_approval_enabled()
    assert not can_trial_approve("write_file", {"path": "workspace/demo/test.txt"})


def test_enabled_allows_safe_tool_safe_path(monkeypatch):
    monkeypatch.setenv("FIRSTAGENT_TRIAL_APPROVAL_POLICY", "safe")
    assert can_trial_approve("write_file", {"path": "workspace/demo/test.txt"})
    assert can_trial_approve("read_file", {"path": "/tmp/test.txt"})


def test_rejects_unsafe_path(monkeypatch):
    monkeypatch.setenv("FIRSTAGENT_TRIAL_APPROVAL_POLICY", "safe")
    assert not can_trial_approve("write_file", {"path": "/etc/passwd"})
    assert not can_trial_approve("write_file", {"path": "config/config.yaml"})
    assert not can_trial_approve("write_file", {"path": "~/.ssh/id_rsa"})


def test_rejects_dangerous_tool(monkeypatch):
    monkeypatch.setenv("FIRSTAGENT_TRIAL_APPROVAL_POLICY", "safe")
    assert not can_trial_approve("shell", {"path": "workspace/demo/test.txt"})
    assert not can_trial_approve("execute_code", {"path": "workspace/demo/test.txt"})
    assert not can_trial_approve("fetch_url", {"path": "workspace/demo/test.txt"})


def test_rejects_non_allowlisted_tool(monkeypatch):
    monkeypatch.setenv("FIRSTAGENT_TRIAL_APPROVAL_POLICY", "safe")
    assert not can_trial_approve("mark_step_complete", {"path": "workspace/demo/test.txt"})


def test_record_trial_approval_does_not_crash(monkeypatch):
    monkeypatch.setenv("FIRSTAGENT_TRIAL_APPROVAL_POLICY", "safe")
    record_trial_approval("write_file", {"path": "workspace/demo/test.txt"})

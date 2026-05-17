"""SubAgent Phase 12: Runtime / Parent Adapter tests."""

from __future__ import annotations

from pathlib import Path

from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.delegation import delegate_once
from agent.subagent_system.registry import SubAgentRegistry
from agent.subagent_system.request import SubAgentRequest


def _write_subagent(root: Path) -> None:
    subagent_dir = root / "code-reviewer"
    subagent_dir.mkdir(parents=True)
    (subagent_dir / "SUBAGENT.md").write_text(
        """---
name: code-reviewer
description: Review code.
role: reviewer
model: fake
status: active
risk_level: low
version: 0.1.0
allowed_tools:
  - read_file
allowed_skills: []
memory_scope: none
max_iterations_default: 1
confirmation_policy: inherit_tool_policy
supported_modes:
  - local_fake
---
# Code Reviewer
""",
        encoding="utf-8",
    )


def test_delegate_once_runs_parent_controlled_l0_flow(tmp_path: Path) -> None:
    """Adapter 编排 request→context→executor→adjudication，但 Parent 仍拥有主循环。"""

    root = tmp_path / "subagents"
    _write_subagent(root)
    registry = SubAgentRegistry([root])
    request = SubAgentRequest(
        task="Review code",
        role="reviewer",
        allowed_tools=("read_file",),
        parent_trace_id="trace-1",
        delegation_reason="review",
    )

    run = delegate_once(request, registry)

    assert run.state == "completed"
    assert run.descriptor is not None
    assert isinstance(run.descriptor, SubAgentDescriptor)
    assert run.result is not None
    assert run.adjudication is not None
    assert run.adjudication.action == "accept_result"
    assert run.revision_count == 0


def test_delegate_once_fails_closed_when_descriptor_missing(tmp_path: Path) -> None:
    """unknown role 不能创建 unmanaged child loop，只能返回 parent-visible failure。"""

    registry = SubAgentRegistry([tmp_path])
    request = SubAgentRequest(
        task="Review code",
        role="reviewer",
        allowed_tools=("read_file",),
        parent_trace_id="trace-1",
        delegation_reason="review",
    )

    run = delegate_once(request, registry)

    assert run.state == "failed"
    assert run.result is not None
    assert run.result.status == "error"
    assert run.adjudication is not None
    assert run.adjudication.action == "reject_result"


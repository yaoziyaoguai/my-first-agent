from __future__ import annotations

from dataclasses import replace

import pytest

from agent.runtime.contracts import (
    ApprovalPolicy,
    ApprovalRequired,
    AuthoritySourceKind,
    ExecutionIntent,
    GoalAuthorizationBinding,
    OutputPolicy,
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import IntentConflictError, KernelToolRuntime, RegisteredTool


def _spec(
    *,
    name: str = "write_file",
    side_effect: SideEffectClass = SideEffectClass.WRITE,
    workspace_scoped: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1",
        description="test governed effect",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=side_effect,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={"workspace_scoped": workspace_scoped},
        output_limit_chars=100,
    )


def _binding(*, revision: int = 1, target: str = "reports/final.md") -> GoalAuthorizationBinding:
    return GoalAuthorizationBinding.create(
        binding_id="authority-1",
        goal_id="goal-1",
        goal_revision=revision,
        workspace_identity_digest="workspace-1",
        operation="write_file",
        normalized_target=target,
        source_kind=AuthoritySourceKind.USER_FACT,
        source_id="user-1",
        source_digest="user-digest-1",
    )


def _context(binding: GoalAuthorizationBinding | None) -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=4,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="workspace-1",
        goal_authorization=binding,
    )


def _runtime(spec: ToolSpec | None = None):
    calls = []

    def invoke(intent):  # noqa: ANN001
        calls.append(intent)
        return "ok"

    runtime = KernelToolRuntime((RegisteredTool(spec or _spec(), invoke),))
    return runtime, calls


def test_model_forged_goal_or_scope_never_authorizes_workspace_write() -> None:
    runtime, calls = _runtime()
    prepared = runtime.prepare(
        ToolCall("call-1", "write_file", {"path": "reports/final.md"}),
        _context(None),
    )

    assert isinstance(prepared, ApprovalRequired)
    assert calls == []


def test_exact_user_authoritative_binding_can_avoid_duplicate_prompt() -> None:
    runtime, calls = _runtime()
    prepared = runtime.prepare(
        ToolCall("call-1", "write_file", {"path": "reports/final.md"}),
        _context(_binding()),
    )

    assert isinstance(prepared, ExecutionIntent)
    result = runtime.invoke(prepared)
    assert result.executed is True
    assert len(calls) == 1


def test_path_alias_scope_expansion_and_stale_grant_have_zero_effect() -> None:
    for path, binding in (
        ("./reports/final.md", _binding()),
        ("reports/other.md", _binding()),
    ):
        runtime, calls = _runtime()
        prepared = runtime.prepare(
            ToolCall("call-1", "write_file", {"path": path}),
            _context(binding),
        )
        assert isinstance(prepared, ApprovalRequired)
        assert calls == []
    with pytest.raises(ValueError, match="authorization is stale"):
        _context(_binding(revision=2))


def test_target_scope_cost_sensitive_external_and_irreversible_boundaries_require_approval(
) -> None:
    external = _spec(
        name="send_external",
        side_effect=SideEffectClass.EXTERNAL,
        workspace_scoped=False,
    )
    runtime, calls = _runtime(external)
    prepared = runtime.prepare(
        ToolCall("call-1", "send_external", {"path": "reports/final.md"}),
        _context(_binding()),
    )
    assert isinstance(prepared, ApprovalRequired)
    assert calls == []


def test_new_root_tool_or_service_cannot_be_added_by_goal_policy() -> None:
    runtime, calls = _runtime(_spec(name="unknown_service", workspace_scoped=False))
    prepared = runtime.prepare(
        ToolCall("call-1", "unknown_service", {"path": "reports/final.md"}),
        _context(_binding()),
    )
    assert isinstance(prepared, ApprovalRequired)
    assert calls == []


def test_goal_revision_or_binding_drift_invalidates_prepared_intent() -> None:
    runtime, calls = _runtime()
    prepared = runtime.prepare(
        ToolCall("call-1", "write_file", {"path": "reports/final.md"}),
        _context(_binding()),
    )
    assert isinstance(prepared, ExecutionIntent)

    with pytest.raises(IntentConflictError, match="intent binding digest"):
        runtime.invoke(replace(prepared, goal_revision=2))
    assert calls == []


def test_mcp_subagent_and_preference_risk_is_not_silently_downgraded() -> None:
    for name in ("mcp__server__tool", "subagent_run", "preference_remember"):
        runtime, calls = _runtime(
            _spec(name=name, side_effect=SideEffectClass.EXTERNAL, workspace_scoped=False)
        )
        prepared = runtime.prepare(
            ToolCall("call-1", name, {"path": "reports/final.md"}),
            _context(_binding()),
        )
        assert isinstance(prepared, ApprovalRequired)
        assert calls == []

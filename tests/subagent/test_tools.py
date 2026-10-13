from __future__ import annotations

from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalRequired,
    BeginAnswer,
    ControlBinding,
    ControlInboxRequest,
    ControlRequestKind,
    ExecutionIntent,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.control import ControlInbox
from agent.runtime.tools import KernelToolRuntime
from agent.subagent.contracts import ChildProfile
from agent.subagent.runner import ChildAgentRunner
from agent.subagent.tools import build_subagent_tool_registrations
from tests.kernel.fakes import ScriptedProvider


def _profile() -> ChildProfile:
    return ChildProfile(
        runner_version="subagent-v1",
        provider_profile_id="default",
        provider_destination="local",
        workspace_scope_digest="scope-1",
        max_input_tokens=4_000,
        max_output_tokens=1_000,
        limits_digest="limits-1",
        hard_deadline_seconds=30.0,
    )


def _ctx() -> ToolPrepareContext:
    return ToolPrepareContext("conversation-1", "run-1", 1)


def _runner() -> ChildAgentRunner:
    return ChildAgentRunner(
        provider=ScriptedProvider(ModelResponse((ModelTextBlock("child answer"),))),
        profile=_profile(),
    )


def test_spec_is_high_external_always_and_preview_shows_destination() -> None:
    registrations = build_subagent_tool_registrations(_runner())
    assert len(registrations) == 1
    spec = registrations[0].spec
    assert spec.name == "subagent__delegate"
    assert spec.approval_policy.value == "always"
    assert spec.side_effect.value == "external"

    runtime = KernelToolRuntime(registrations)
    prepared = runtime.prepare(
        ToolCall("c1", "subagent__delegate", {"objective": "review", "handoff": "ctx"}), _ctx()
    )
    assert isinstance(prepared, ApprovalRequired)
    assert "local" in prepared.request.preview
    assert "review" in prepared.request.preview


def test_approved_delegate_returns_child_message() -> None:
    runtime = KernelToolRuntime(build_subagent_tool_registrations(_runner()))
    call = ToolCall("c1", "subagent__delegate", {"objective": "review", "handoff": "ctx"})
    prepared = runtime.prepare(call, _ctx())
    intent = runtime.prepare(
        call,
        _ctx(),
        approval=ApprovalGrant(prepared.request.request_id, prepared.request.binding_digest),
    )
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)
    assert result.is_error is False
    assert result.content == "child answer"
    assert result.metadata["governed_tool_receipt_kind"] == "governed_tool_v1"
    assert len(str(result.metadata["receipt_digest"])) == 64


def test_bound_parent_cancel_prevents_child_start() -> None:
    inbox = ControlInbox()
    binding = ControlBinding("conversation-1", "goal-1", 1, "invocation-1")
    inbox.open(binding)
    inbox.submit(
        ControlInboxRequest(
            request_id="cancel-child-1",
            kind=ControlRequestKind.CANCEL,
            conversation_id=binding.conversation_id,
            goal_id=binding.goal_id,
            goal_revision=binding.goal_revision,
            invocation_id=binding.invocation_id,
        )
    )
    runtime = KernelToolRuntime(build_subagent_tool_registrations(_runner(), control_inbox=inbox))
    context = ToolPrepareContext(
        "conversation-1",
        "run-1",
        1,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="workspace-1",
    )
    call = ToolCall("c1", "subagent__delegate", {"objective": "review", "handoff": ""})
    prepared = runtime.prepare(call, context)
    intent = runtime.prepare(
        call,
        context,
        approval=ApprovalGrant(prepared.request.request_id, prepared.request.binding_digest),
    )

    result = runtime.invoke(intent)

    assert result.executed is False
    assert result.is_error is True
    assert result.metadata["code"] == "child_cancelled_before_start"


def test_delegate_returns_parent_verified_child_source_appendix(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    runner = ChildAgentRunner(
        provider=ScriptedProvider(
            ModelResponse((), control=BeginAnswer("child-source-metadata")),
            ModelResponse(
                (
                    ModelToolCall(
                        "read-1",
                        "read_file_chunk",
                        {"path": "service.py", "start_line": 1, "max_lines": 1},
                    ),
                )
            ),
            ModelResponse((ModelTextBlock("service.py:1 contains VALUE"),)),
        ),
        profile=_profile(),
        workspace_root=workspace,
    )
    runtime = KernelToolRuntime(build_subagent_tool_registrations(runner))
    call = ToolCall("c1", "subagent__delegate", {"objective": "find VALUE", "handoff": ""})
    prepared = runtime.prepare(call, _ctx())
    intent = runtime.prepare(
        call,
        _ctx(),
        approval=ApprovalGrant(prepared.request.request_id, prepared.request.binding_digest),
    )

    result = runtime.invoke(intent)

    assert "service.py#L1" in result.content
    assert "snapshot_sha256=" in result.content
    assert "content_sha256=" in result.content
    assert "advisory only" in result.content
    assert result.metadata["governed_tool_receipt_kind"] == "governed_tool_v1"


def test_child_nonterminal_returns_known_failure_text() -> None:
    from agent.runtime.contracts import ModelToolCall

    runner = ChildAgentRunner(
        provider=ScriptedProvider(
            ModelResponse((ModelToolCall("c1", "read_file", {"path": "x"}),))
        ),
        profile=_profile(),
    )
    runtime = KernelToolRuntime(build_subagent_tool_registrations(runner))
    call = ToolCall("c1", "subagent__delegate", {"objective": "o", "handoff": ""})
    prepared = runtime.prepare(call, _ctx())
    intent = runtime.prepare(
        call,
        _ctx(),
        approval=ApprovalGrant(prepared.request.request_id, prepared.request.binding_digest),
    )
    result = runtime.invoke(intent)
    assert "did not complete" in result.content

from __future__ import annotations

from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalPolicy,
    ApprovalRequired,
    ExecutionIntent,
    OutputPolicy,
    PolicyDecision,
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import KernelToolRuntime, RegisteredTool


def _write_spec() -> ToolSpec:
    return ToolSpec(
        name="write_fixture",
        version="1",
        description="Write a deterministic fixture",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={"workspace_scoped": True},
        output_limit_chars=100,
    )


def _context() -> ToolPrepareContext:
    return ToolPrepareContext("conversation-1", "run-1", 4)


def test_approval_binds_policy_arguments_and_preconditions() -> None:
    calls: list[tuple[str, str]] = []

    def prepare_binding(arguments):
        return {
            "target_digest": "target:" + arguments["path"],
            "precondition_digest": "before:missing",
            "new_content_digest": "new:" + arguments["content"],
            "effect_preview": "create " + arguments["path"],
        }

    def write_fixture(intent: ExecutionIntent) -> str:
        calls.append((intent.arguments["path"], intent.arguments["content"]))
        return "written"

    runtime = KernelToolRuntime(
        (RegisteredTool(_write_spec(), write_fixture, prepare_binding=prepare_binding),)
    )
    call = ToolCall(
        tool_call_id="call-1",
        name="write_fixture",
        arguments={"path": "a.txt", "content": "hello"},
    )

    prepared = runtime.prepare(call, _context())
    assert isinstance(prepared, ApprovalRequired)
    assert calls == []
    assert prepared.request.target_digest == "target:a.txt"
    assert prepared.request.new_content_digest == "new:hello"

    stale = runtime.prepare(
        call,
        _context(),
        approval=ApprovalGrant(
            request_id=prepared.request.request_id,
            binding_digest="wrong",
        ),
    )
    assert isinstance(stale, ToolResult)
    assert stale.metadata["code"] == "approval_mismatch"
    assert calls == []

    exact = runtime.prepare(
        call,
        _context(),
        approval=ApprovalGrant(
            request_id=prepared.request.request_id,
            binding_digest=prepared.request.binding_digest,
        ),
    )
    assert isinstance(exact, ExecutionIntent)
    assert runtime.invoke(exact).is_error is False
    assert calls == [("a.txt", "hello")]


def test_policy_denial_and_policy_exception_fail_closed() -> None:
    class DenyPolicy:
        identity = "deny-v1"

        def evaluate(self, spec, arguments, binding):
            return PolicyDecision.DENY

    class BrokenPolicy:
        identity = "broken-v1"

        def evaluate(self, spec, arguments, binding):
            raise RuntimeError("policy unavailable")

    call = ToolCall(
        tool_call_id="call-1",
        name="write_fixture",
        arguments={"path": "a", "content": "b"},
    )
    registration = RegisteredTool(_write_spec(), lambda intent: "must not run")

    denied = KernelToolRuntime((registration,), policy=DenyPolicy()).prepare(call, _context())
    broken = KernelToolRuntime((registration,), policy=BrokenPolicy()).prepare(call, _context())

    assert isinstance(denied, ToolResult)
    assert denied.metadata["code"] == "policy_denied"
    assert isinstance(broken, ToolResult)
    assert broken.metadata["code"] == "policy_failure"


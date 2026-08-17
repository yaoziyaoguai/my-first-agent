"""SubAgent governed delegation registration。

``subagent__delegate`` 是 HIGH + EXTERNAL + ALWAYS_APPROVAL 的 governed tool。executor
只调用 composition root 注入的 ``ChildAgentRunner``（不导入 provider/loop），从冻结
``ExecutionIntent`` 的 idempotency key 派生 child identity。

receipt 分类：
- TERMINATED + COMPLETED → success text
- TERMINATED + nonterminal → ``KnownExecutedError``
- UNCONFIRMED → raise（parent unknown-outcome recovery）
"""

from __future__ import annotations

from agent.runtime.contracts import (
    ApprovalPolicy,
    ExecutionAuthorityClass,
    KnownExecutedError,
    OutputPolicy,
    RunStatus,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import RegisteredTool
from agent.subagent.contracts import TerminationReceiptState
from agent.subagent.runner import ChildAgentRunner

SUBAGENT_POLICY_VERSION = "subagent-tool-v1"
_MAX_OBJECTIVE = 2_000
_MAX_HANDOFF = 4_000
_OUTPUT_CAP = 2_000


def build_subagent_tool_registrations(
    runner: ChildAgentRunner,
) -> tuple[RegisteredTool, ...]:
    profile = runner.profile
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="subagent__delegate",
        version="1",
        description="Delegate one bounded read-only review to an isolated child agent.",
        input_schema={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "maxLength": _MAX_OBJECTIVE},
                "handoff": {"type": "string", "maxLength": _MAX_HANDOFF},
            },
            "required": ["objective"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.EXTERNAL,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={
            "kind": "subagent_delegate",
            "runner_version": profile.runner_version,
            "provider_profile_id": profile.provider_profile_id,
            "provider_destination": profile.provider_destination,
            "workspace_scope_digest": profile.workspace_scope_digest,
            "limits_digest": profile.limits_digest,
            "policy_version": SUBAGENT_POLICY_VERSION,
        },
        output_limit_chars=_OUTPUT_CAP,
    )
    return (
        RegisteredTool(
            spec,
            _make_executor(runner),
            prepare_binding=_make_binding(profile),
        ),
    )


class SubAgentUnknownOutcomeError(RuntimeError):
    """unconfirmed provider termination → parent unknown-outcome recovery。"""


def _make_executor(runner: ChildAgentRunner):
    def delegate(intent):
        objective = str(intent.arguments.get("objective", ""))
        handoff = str(intent.arguments.get("handoff", ""))
        if len(objective) > _MAX_OBJECTIVE:
            raise ValueError("objective exceeds the schema limit")
        if len(handoff) > _MAX_HANDOFF:
            raise ValueError("handoff exceeds the schema limit")

        result = runner.run(
            objective=objective,
            handoff=handoff,
            parent_idempotency_key=intent.idempotency_key,
        )

        if result.receipt_state is TerminationReceiptState.UNCONFIRMED:
            raise SubAgentUnknownOutcomeError(
                "child provider termination unconfirmed"
            )

        if result.status is RunStatus.COMPLETED:
            return result.message[:_OUTPUT_CAP] if result.message else "child returned no text"

        return KnownExecutedError(
            code="child_nonterminal",
            message=f"child review did not complete ({result.reason})",
        )

    return delegate


def _make_binding(profile):
    def prepare(arguments):
        objective = str(arguments.get("objective", ""))
        handoff = str(arguments.get("handoff", ""))
        if len(objective) > _MAX_OBJECTIVE:
            raise ValueError("objective exceeds the schema limit")
        if len(handoff) > _MAX_HANDOFF:
            raise ValueError("handoff exceeds the schema limit")
        return {
            "effect_preview": (
                f"delegate to child agent (provider={profile.provider_destination}, "
                f"profile={profile.provider_profile_id}) objective={objective} "
                f"handoff={handoff}"
            ),
            "target_digest": profile.provider_destination,
        }

    return prepare

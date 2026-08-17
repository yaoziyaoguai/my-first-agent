from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.runtime.contracts import (
    ActiveRunStatus,
    ConversationFact,
    ConversationState,
    FactKind,
    LoadedSnapshot,
    RunStatus,
    SubmitMessage,
    ToolCall,
    canonical_action_digest,
)


def test_contracts_are_immutable_and_action_digest_is_canonical() -> None:
    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hello",
    )

    assert canonical_action_digest(action) == canonical_action_digest(action)
    with pytest.raises(FrozenInstanceError):
        action.message = "changed"  # type: ignore[misc]


def test_durable_state_rejects_live_dependency_objects() -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        ConversationFact(
            fact_id="fact-1",
            kind=FactKind.USER_MESSAGE,
            content={"callback": lambda: None},
        )


def test_loaded_snapshot_exposes_state_and_opaque_token_once() -> None:
    state = ConversationState.new("conversation-1")
    snapshot = LoadedSnapshot(state=state, token="sha256:fixture")

    assert snapshot.state.conversation_id == "conversation-1"
    assert snapshot.token == "sha256:fixture"
    assert ActiveRunStatus.RUNNABLE.value == "runnable"
    assert RunStatus.CONVERSATION_LIMIT_REACHED.value == "conversation_limit_reached"


def test_nested_json_payloads_reject_in_place_mutation() -> None:
    fact = ConversationFact(
        fact_id="fact-1",
        kind=FactKind.USER_MESSAGE,
        content={"nested": {"value": "original"}},
    )
    call = ToolCall(
        tool_call_id="call-1",
        name="fixture",
        arguments={"items": ["first"]},
    )

    with pytest.raises(TypeError, match="frozen JSON object"):
        fact.content["nested"]["value"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError, match="frozen JSON array"):
        call.arguments["items"].append("second")  # type: ignore[union-attr]

    assert fact.content["nested"] == {"value": "original"}
    assert call.arguments["items"] == ["first"]


# --------------------------------------------------------------------------- #
# 015 Governed Local Action — U2 closed execution-authority 与 process authority
# 合同。下列 Red 在 U2 product code 落地前因 contract/字段不存在而准确失败；每个
# 测试用 getattr/fields 守卫，保证失败是干净的断言而非 collection 期 import error。
# --------------------------------------------------------------------------- #


def _authority_field_default(dataclass_type):
    from dataclasses import fields

    for field in fields(dataclass_type):
        if field.name == "execution_authority":
            return field.default
    return None


def test_015_execution_authority_class_is_closed_and_requires_projection() -> None:
    """R23 / KTD13：closed ExecutionAuthorityClass；authority 必须显式投影（F5）。

    F5（review finding 2026-08-16）：constructor default 静默赋 IN_PROCESS 会掩盖
    新增工具的 authority 遗漏——字段必填（无 default），静态工具显式声明
    IN_PROCESS，process 工具显式声明 LOCAL_SAME_UID_PROCESS。
    """

    from dataclasses import MISSING, fields

    import agent.runtime.contracts as runtime_contracts

    authority = getattr(runtime_contracts, "ExecutionAuthorityClass", None)
    assert authority is not None, "015 requires closed ExecutionAuthorityClass"
    assert {item.value for item in authority} == {"in_process", "local_same_uid_process"}

    # ToolSpec/ToolDefinition/ExecutionIntent/ExecutingIntentRecord 都携带
    # execution_authority，且没有 default（遗漏在构造时即失败）。
    for dataclass_type in (
        runtime_contracts.ToolSpec,
        runtime_contracts.ToolDefinition,
        runtime_contracts.ExecutionIntent,
        runtime_contracts.ExecutingIntentRecord,
    ):
        field_names = {field.name for field in fields(dataclass_type)}
        assert "execution_authority" in field_names, (
            f"{dataclass_type.__name__} must carry execution_authority"
        )
        assert _authority_field_default(dataclass_type) is MISSING, (
            f"{dataclass_type.__name__}.execution_authority must not default"
        )


def test_015_existing_tool_families_rebaseline_to_in_process_authority(tmp_path) -> None:  # noqa: ANN001
    """R22 / KTD13：012-014 现有工具族 identity rebaseline 到 IN_PROCESS。

    文件、研究工具的 ToolSpec 必须显式投影 IN_PROCESS（不因新增 LOCAL_SAME_UID_PROCESS
    而漂移到其他值），保证既有 reference claims 不回归。
    """

    import agent.runtime.contracts as runtime_contracts
    from agent.research.tools import build_research_tool_registrations
    from agent.tools.file_ops import build_file_tool_registrations

    authority = getattr(runtime_contracts, "ExecutionAuthorityClass", None)
    assert authority is not None, "ExecutionAuthorityClass required for rebaseline"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registrations = [
        *build_file_tool_registrations(workspace),
        *build_research_tool_registrations(),
    ]
    assert registrations, "fixture should yield existing tool families"
    for registration in registrations:
        spec = registration.spec
        projected = getattr(spec, "execution_authority", None)
        assert projected is authority.IN_PROCESS, (
            f"existing tool {spec.name} must rebaseline to IN_PROCESS, got {projected}"
        )


def test_015_process_authority_contracts_are_closed_immutable_and_secret_free() -> None:
    """R8 / R9 / R17 / KTD2 / KTD4 / KTD8 / KTD10：durable authority 合同是 closed、
    immutable、exact-digest 且不含 secret/raw env 的 frozen dataclass。"""

    from dataclasses import fields

    import agent.runtime.contracts as runtime_contracts

    secret_field_names = {
        "credential",
        "api_key",
        "secret",
        "raw_environment",
        "authorization",
        "proxy",
    }
    for type_name, required_fields in (
        (
            "ProcessAuthorityCandidateV1",
            {
                "goal_id",
                "goal_revision",
                "workspace_identity_digest",
                "command_fingerprint",
                "execution_authority",
                "candidate_digest",
            },
        ),
        (
            "ProcessAuthorityLeaseV1",
            {
                "lease_id",
                "lease_digest",
                "goal_id",
                "goal_revision",
                "command_fingerprint",
                "max_uses",
                "expires_at",
                "issued_at",
                "uses_consumed",
            },
        ),
        (
            "ProcessReceiptV1",
            {
                "receipt_digest",
                "lease_id",
                "goal_id",
                "goal_revision",
                "outcome",
                "execution_authority",
            },
        ),
    ):
        contract = getattr(runtime_contracts, type_name, None)
        assert contract is not None, f"015 requires {type_name}"
        field_names = {field.name for field in fields(contract)}
        assert required_fields <= field_names, (
            f"{type_name} missing closed fields: {required_fields - field_names}"
        )
        assert field_names.isdisjoint(secret_field_names), (
            f"{type_name} must not carry secret/raw-env fields: "
            f"{field_names & secret_field_names}"
        )
        # frozen：durable authority 合同必须 immutable。
        assert contract.__dataclass_params__.frozen, f"{type_name} must be frozen"

    # lease 固定 8 次 reuse；approval request 持久化完整 closed process candidate。
    lease_type = runtime_contracts.ProcessAuthorityLeaseV1
    max_uses_default = next(
        field.default for field in fields(lease_type) if field.name == "max_uses"
    )
    assert max_uses_default == 8, f"lease max_uses must be fixed at 8, got {max_uses_default}"
    request_fields = {field.name for field in fields(runtime_contracts.ApprovalRequest)}
    assert "process_authority_candidate" in request_fields, (
        "ApprovalRequest must persist the full closed process candidate"
    )

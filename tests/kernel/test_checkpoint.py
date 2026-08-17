"""015 U2：process authority candidate/executing record 的 checkpoint 序列化、
pre-015 一次明确 migration 与 strict decode。

安全性来自 closed shape + 一次明确 versioned migration：只有 015 之前的旧 executing
record 可把缺失的 execution_authority 迁移为 IN_PROCESS；当前 schema 缺失/未知成员
strict-decode 失败。下列 Red 在 U2 product code 落地前准确失败；需要构造 candidate 的
部分用 ``pytest.fail`` 守卫。
"""

from __future__ import annotations

import json

import pytest

import agent.runtime.checkpoint as checkpoint
import agent.runtime.contracts as contracts
from agent.runtime.contracts import ApprovalRequest

_LEGACY_EXECUTING_BLOB = {
    "tool_call_id": "call-legacy-015",
    "intent_digest": "d" * 64,
    "idempotency_key": "conversation-1:run-1:call-legacy-015",
    "side_effect": "write",
    "egress": "none",
    "operation": "legacy_effect",
    "request_identity": "conversation-1:run-1:call-legacy-015",
}


def test_015_legacy_executing_record_migrates_to_in_process_authority() -> None:
    """KTD12 / KTD13：pre-015 executing record（无 execution_authority）经一次明确
    migration 解码为 IN_PROCESS；当前 schema 不允许缺失该成员。"""

    authority = getattr(contracts, "ExecutionAuthorityClass", None)
    if authority is None:
        pytest.fail("015 requires ExecutionAuthorityClass")
    # 7-key pre-015 blob：当前实现接受该 key-set，但 record 尚无 authority 成员。
    record = checkpoint._executing_from_dict(dict(_LEGACY_EXECUTING_BLOB))
    assert getattr(record, "execution_authority", None) is authority.IN_PROCESS, (
        "legacy executing record must migrate to IN_PROCESS authority"
    )


def test_015_current_executing_record_preserves_explicit_authority() -> None:
    """KTD13：当前 schema executing record 必须保留显式 execution_authority
    （含 LOCAL_SAME_UID_PROCESS），缺失/未知值 strict-decode 失败。"""

    authority = getattr(contracts, "ExecutionAuthorityClass", None)
    if authority is None:
        pytest.fail("015 requires ExecutionAuthorityClass")
    modern = dict(_LEGACY_EXECUTING_BLOB)
    modern["execution_authority"] = "local_same_uid_process"
    record = checkpoint._executing_from_dict(modern)
    assert record.execution_authority is authority.LOCAL_SAME_UID_PROCESS

    bogus = dict(_LEGACY_EXECUTING_BLOB)
    bogus["execution_authority"] = "not_a_real_authority"
    with pytest.raises((ValueError, checkpoint.CheckpointInvariantError)):
        checkpoint._executing_from_dict(bogus)


def test_015_process_authority_candidate_round_trips_through_checkpoint() -> None:
    """KTD3 / KTD12：ApprovalRequest 持久化完整 closed process candidate，AWAITING_APPROVAL
    reload 后 strict round-trip，不得从 preview/transient memory 重建。"""

    candidate_type = getattr(contracts, "ProcessAuthorityCandidateV1", None)
    if candidate_type is None:
        pytest.fail("015 requires ProcessAuthorityCandidateV1")
    candidate = _fixture_candidate(candidate_type)
    request = ApprovalRequest(
        request_id="request-015",
        run_id="run-015",
        tool_call_id="call-015",
        binding_digest="b" * 64,
        preview="exact command + same-UID notice",
        tool_name="local_process",
        process_authority_candidate=candidate,
    )
    encoded = checkpoint._pending_to_dict(request)
    assert encoded["type"] == "approval"
    decoded = checkpoint._pending_from_dict(encoded)
    assert isinstance(decoded, ApprovalRequest)
    assert decoded.process_authority_candidate == candidate


def test_015_process_contracts_serialize_no_secret_or_env_values() -> None:
    """R14 / R17：candidate/lease 序列化结果不得包含 credential/env/proxy value。"""

    candidate_type = getattr(contracts, "ProcessAuthorityCandidateV1", None)
    if candidate_type is None:
        pytest.fail("015 requires ProcessAuthorityCandidateV1")
    candidate = _fixture_candidate(candidate_type)
    request = ApprovalRequest(
        request_id="request-secret-015",
        run_id="run-015",
        tool_call_id="call-secret-015",
        binding_digest="b" * 64,
        preview="exact command + same-UID notice",
        tool_name="local_process",
        process_authority_candidate=candidate,
    )
    serialized = json.dumps(checkpoint._pending_to_dict(request), sort_keys=True)
    for forbidden in (
        "FIRST_AGENT_API_KEY",
        "ANTHROPIC_API_KEY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "Bearer ",
        "secret-canary",
    ):
        assert forbidden not in serialized, (
            f"serialized process candidate must not carry secret/env value: {forbidden}"
        )


def _fixture_candidate(candidate_type):
    return candidate_type.create(
        candidate_id="candidate-015",
        goal_id="goal-015",
        goal_revision=1,
        workspace_identity_digest="workspace-015",
        command_fingerprint="f" * 64,
        readable_command="/usr/bin/true --flag",
        executable_digest="e" * 64,
        argv_digest="a" * 64,
        cwd_digest="w" * 64,
        resource_profile="standard",
        environment_policy_digest="p" * 64,
        execution_authority=contracts.ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        trust_notice_digest="t" * 64,
        max_uses=8,
        issued_at="2026-08-09T00:00:00Z",
        expiry_minutes=60,
    )

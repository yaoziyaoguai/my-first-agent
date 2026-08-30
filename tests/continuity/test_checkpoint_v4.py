"""F2（P1 review finding 2026-08-16）：checkpoint v4 schema bump + v3 完整迁移。

015 在 SCHEMA_VERSION=3 内加入了 ``process_leases`` / ``execution_authority`` 而未
bump 版本：真实 pre-015 v3 文档缺 ``process_leases`` 时 ``value.get(..., ())`` 的
tuple default 被 ``_array`` 拒绝（加载崩溃，注释承诺的迁移不存在）；current 记录缺
``execution_authority`` 又被静默映射为 IN_PROCESS。Green 合同（KTD12/KTD13）：

- ``SCHEMA_VERSION=6``；v3 是 process-authority migration source 且**完整物化**
  新字段（缺 ``process_leases`` → 空；缺 ``execution_authority`` → IN_PROCESS）。
- v4 是 current：缺 ``process_leases``、缺/未知 ``execution_authority`` 一律 strict
  fail closed。
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent.runtime.checkpoint import (
    CheckpointInvariantError,
    CheckpointVersionError,
    LocalCheckpointStore,
    _encode_state,
)
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ContinuationPhase,
    ConversationState,
    ConversationWorkspaceBindingV1,
    EgressClass,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    ProcessAuthorityLeaseV1,
    ProposedCriterion,
    RecoveryRequest,
    SideEffectClass,
    ToolCall,
)
from tests.continuity.test_contracts import _goal

CONVERSATION = "conversation:v4"
WORKSPACE_DIGEST = "workspace:v1:" + "c" * 64


def _lease() -> ProcessAuthorityLeaseV1:
    return ProcessAuthorityLeaseV1.create(
        lease_id="process-lease:candidate:v4",
        candidate_digest="c" * 64,
        goal_id="goal:1",
        goal_revision=1,
        workspace_identity_digest=WORKSPACE_DIGEST,
        command_fingerprint="f" * 64,
        readable_command="/usr/bin/true --checkpoint",
        executable_digest="e" * 64,
        argv_digest="a" * 64,
        cwd_digest="w" * 64,
        resource_profile="standard",
        environment_policy_digest="p" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        approved_request_identity="req:v4",
        issued_at="2026-08-16T00:00:00Z",
        expires_at="2026-08-16T01:00:00Z",
        max_uses=8,
        uses_consumed=1,
    )


def _binding() -> ConversationWorkspaceBindingV1:
    return ConversationWorkspaceBindingV1.create(
        workspace_scope_digest="s" * 64,
        workspace_identity_digest=WORKSPACE_DIGEST,
        bound_at="2026-08-16T00:00:00Z",
    )


def _process_executing() -> ExecutingIntentRecord:
    return ExecutingIntentRecord(
        tool_call_id="call:v4",
        intent_digest="i" * 64,
        idempotency_key=f"{CONVERSATION}:run:v4:call:v4",
        side_effect=SideEffectClass.EXTERNAL,
        egress=EgressClass.NONE,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        operation="local_process",
        request_identity="req:v4",
    )


def _current_state() -> ConversationState:
    return ConversationState(
        conversation_id=CONVERSATION,
        revision=3,
        workspace_binding=_binding(),
        goal=_goal(),
        process_leases=(_lease(),),
        active_run=ActiveRun(
            run_id="run:v4",
            status=ActiveRunStatus.AWAITING_RECOVERY,
            phase=ContinuationPhase.EXECUTING,
            batch_cursor=0,
            tool_calls=(ToolCall("call:v4", "local_process", {}),),
            executing_intent=_process_executing(),
            pending_request=RecoveryRequest(
                request_id="recovery:v4",
                run_id="run:v4",
                tool_call_id="call:v4",
                binding_digest="i" * 64,
                summary="process outcome unknown",
            ),
        ),
    )


def _legacy_goal():  # noqa: ANN201
    goal = _goal()
    return replace(
        goal,
        proposed_criteria=tuple(
            ProposedCriterion(item.criterion_id, item.description)
            for item in goal.proposed_criteria
        ),
    )


def _write_document(path, document) -> None:
    """以 checkpoint 合同的 0700/0600 形状写入手构 document（覆盖已有文件，保 mode）。"""

    if not path.exists():
        LocalCheckpointStore.initialize(path, ConversationState.new(CONVERSATION))
    with open(path, "wb") as handle:
        handle.write(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )


def _pre_015_v3_document() -> dict:
    """真实 pre-015 v3 whole-state fixture：当前 writer 输出去掉 015 新字段。"""

    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    document["schema_version"] = 3
    del document["state"]["background_occurrence_binding"]
    _remove_v8_active_fields(document)
    del document["state"]["process_leases"]
    executing = document["state"]["active_run"]["executing_intent"]
    del executing["execution_authority"]
    for criterion in document["state"]["goal"]["proposed_criteria"]:
        criterion.pop("oracle_kind")
        criterion.pop("artifact_path")
    return document


def _remove_v8_active_fields(document: dict) -> None:
    active = document["state"].get("active_run")
    if active is not None:
        active.pop("invocation_origin")
        active.pop("provider_call_intent")
        active.pop("persisted_model_response")
        active.pop("model_calls_used")
        active.pop("tool_calls_used")
        active.pop("sandbox_commands_used")
        active.pop("browser_actions_used")
        active.pop("input_tokens_used")
        active.pop("output_tokens_used")


def test_current_state_encodes_as_v9_and_round_trips(tmp_path) -> None:
    state = _current_state()
    path = tmp_path / "conversation.json"
    store = LocalCheckpointStore.initialize(path, state)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 9, (
        "020a invocation origin makes v9 the current checkpoint schema"
    )
    restored = store.load().state
    assert restored == state
    assert restored.process_leases == (_lease(),)
    assert (
        restored.active_run.executing_intent.execution_authority
        is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
    )


def test_process_leases_alone_use_current_v9_schema(tmp_path) -> None:
    """current writer 统一写 v9；v6-v8 只作为可读取 migration source。"""

    state = replace(
        ConversationState.new(CONVERSATION), goal=_goal(), process_leases=(_lease(),)
    )
    document = json.loads(_encode_state(state).decode("utf-8"))
    assert document["schema_version"] == 9


def test_015_pre_015_v3_whole_state_migrates_completely(tmp_path) -> None:
    """v3（唯一 migration source）：缺 process_leases → 空、缺 execution_authority →
    IN_PROCESS，其余字段完整无损——不得崩溃、不得静默丢字段。"""

    path = tmp_path / "conversation.json"
    _write_document(path, _pre_015_v3_document())

    restored = LocalCheckpointStore(path).load().state

    assert restored.process_leases == ()
    assert restored.active_run is not None
    executing = restored.active_run.executing_intent
    assert executing is not None
    assert executing.execution_authority is ExecutionAuthorityClass.IN_PROCESS
    current = _current_state()
    assert restored.conversation_id == current.conversation_id
    assert restored.workspace_binding == current.workspace_binding
    assert restored.goal == _legacy_goal()
    assert restored.active_run.tool_calls == current.active_run.tool_calls


def test_015_legacy_document_revokes_unverifiable_process_leases(tmp_path) -> None:
    """v3-v5 weak digest 不能在 migration 时重签；旧 process authority 一律撤销。"""

    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    document["schema_version"] = 3
    del document["state"]["background_occurrence_binding"]
    _remove_v8_active_fields(document)
    for criterion in document["state"]["goal"]["proposed_criteria"]:
        criterion.pop("oracle_kind")
        criterion.pop("artifact_path")
    path = tmp_path / "conversation.json"
    _write_document(path, document)

    restored = LocalCheckpointStore(path).load().state
    assert restored == replace(
        _current_state(),
        goal=_legacy_goal(),
        process_leases=(),
    )


def test_015_v6_missing_process_leases_fails_closed(tmp_path) -> None:
    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    del document["state"]["process_leases"]
    path = tmp_path / "conversation.json"
    _write_document(path, document)

    with pytest.raises(CheckpointVersionError, match="process_leases"):
        LocalCheckpointStore(path).load()


def test_015_v6_executing_missing_authority_fails_closed(tmp_path) -> None:
    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    del document["state"]["active_run"]["executing_intent"]["execution_authority"]
    path = tmp_path / "conversation.json"
    _write_document(path, document)

    with pytest.raises(CheckpointVersionError, match="execution_authority"):
        LocalCheckpointStore(path).load()


def test_015_v6_executing_unknown_authority_fails_closed(tmp_path) -> None:
    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    document["state"]["active_run"]["executing_intent"]["execution_authority"] = (
        "cluster_root"
    )
    path = tmp_path / "conversation.json"
    _write_document(path, document)

    with pytest.raises((CheckpointVersionError, CheckpointInvariantError)):
        LocalCheckpointStore(path).load()


def test_015_v4_migrates_proposed_criterion_contract(tmp_path) -> None:
    """v4 没有 oracle/path；加载时显式迁移为 None，不猜测 artifact 语义。"""

    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    document["schema_version"] = 4
    del document["state"]["background_occurrence_binding"]
    _remove_v8_active_fields(document)
    for criterion in document["state"]["goal"]["proposed_criteria"]:
        criterion.pop("oracle_kind")
        criterion.pop("artifact_path")
    path = tmp_path / "conversation.json"
    _write_document(path, document)

    restored = LocalCheckpointStore(path).load().state

    assert restored == replace(
        _current_state(),
        goal=_legacy_goal(),
        process_leases=(),
    )


def test_015_v5_retargeted_process_lease_is_revoked_not_resigned(tmp_path) -> None:
    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    document["schema_version"] = 5
    del document["state"]["background_occurrence_binding"]
    _remove_v8_active_fields(document)
    document["state"]["process_leases"][0]["command_fingerprint"] = "9" * 64
    path = tmp_path / "conversation.json"
    _write_document(path, document)

    restored = LocalCheckpointStore(path).load().state

    assert restored.process_leases == ()


def test_015_v6_missing_proposed_oracle_fails_closed(tmp_path) -> None:
    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    del document["state"]["goal"]["proposed_criteria"][0]["oracle_kind"]
    path = tmp_path / "conversation.json"
    _write_document(path, document)

    with pytest.raises(CheckpointVersionError, match="oracle_kind"):
        LocalCheckpointStore(path).load()


def test_015_unknown_schema_version_still_rejected(tmp_path) -> None:
    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    document["schema_version"] = 10
    path = tmp_path / "conversation.json"
    _write_document(path, document)

    with pytest.raises(CheckpointVersionError, match="schema version: 10"):
        LocalCheckpointStore(path).load()


def test_015_v6_rejects_retargeted_process_lease_even_if_shape_is_valid(tmp_path) -> None:
    """Current checkpoint 不能只信 stored lease_digest 后接受被改写的 authority 字段。"""

    document = json.loads(_encode_state(_current_state()).decode("utf-8"))
    document["state"]["process_leases"][0]["command_fingerprint"] = "9" * 64
    path = tmp_path / "conversation.json"
    _write_document(path, document)

    with pytest.raises(CheckpointInvariantError, match="lease digest mismatch"):
        LocalCheckpointStore(path).load()

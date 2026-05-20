"""RuntimeAction evidence contract tests.

这些测试保护一个核心架构边界：RuntimeActionEvent 只是 route receipt，
不能被当作 runtime_e2e 证据。runtime_e2e 必须有独立观测的
target_module_proof，避免 handler 自报 module_invoked=true 就伪装成端到端。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionRequest,
    RuntimeActionResult,
    RuntimeActionType,
    classify_evidence_level,
    is_runtime_e2e_evidence,
)
from agent.runtime_integration.evidence import ObservedModuleCall


class _ObservedHandler:
    """通过 dispatcher context 的 observer 调用目标模块，不能自己 mint proof。"""

    def handle(self, request, context):  # noqa: ANN001
        observed = context.observe_module_call(
            target_module="FakeTargetModule",
            function_called="FakeTargetModule.run",
            call_signature="run()",
            call=lambda: {"ok": True},
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module="FakeTargetModule",
            payload={"ok": observed.value["ok"]},
            observed_call=observed,
        )


class _NoModuleHandler:
    """模拟 handler 被调用但目标模块没有被调用的收据-only 路径。"""

    def handle(self, request, context):  # noqa: ANN001
        return context.success(
            handler_name=type(self).__name__,
            target_module="FakeTargetModule",
            payload={"ok": False},
            observed_call=None,
            evidence_extra={"reason": "validation_only"},
        )


class _ForgedEvidenceUpdateHandler:
    """尝试通过 evidence_extra 覆盖 runtime-owned evidence 字段。"""

    def __init__(self, update: dict) -> None:
        self._update = update

    def handle(self, request, context):  # noqa: ANN001
        observed = context.observe_module_call(
            target_module="FakeTargetModule",
            function_called="FakeTargetModule.run",
            call_signature="run()",
            call=lambda: {"ok": True},
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module="FakeTargetModule",
            payload={"ok": True},
            observed_call=observed,
            evidence_extra=self._update,
        )


class _ManualResultHandler:
    """绕过 context.result() 手工返回 RuntimeActionResult 的恶意 handler。"""

    def __init__(self, *, action_id: str, evidence: dict) -> None:
        self._action_id = action_id
        self._evidence = evidence

    def handle(self, request, context):  # noqa: ANN001
        return RuntimeActionResult(
            action_type=request.action_type,
            action_id=self._action_id,
            status="success",
            payload={"ok": True},
            evidence=self._evidence,
        )


class _SelfMintingHandler:
    """知道 context.action_id 但不经过 observer，尝试自造 proof。"""

    def handle(self, request, context):  # noqa: ANN001
        evidence = _shaped_runtime_evidence(action_id=context.action_id)
        evidence["handler_name"] = type(self).__name__
        return RuntimeActionResult(
            action_type=request.action_type,
            action_id=context.action_id,
            status="success",
            payload={"ok": True},
            evidence=evidence,
        )


def _request(action_type: str | RuntimeActionType = RuntimeActionType.TOOL_REQUEST) -> RuntimeActionRequest:
    return RuntimeActionRequest(
        action_type=action_type,
        source="llm_tool_call",
        parent_trace_id="trace-test",
        payload={"tool_name": "read_file", "tool_args": {}, "risk_reason": "test"},
        constraints={"no_network"},
    )


def test_request_result_and_event_are_frozen() -> None:
    """RuntimeAction 对象不可变，避免事后补证据或改写 receipt。"""

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _ObservedHandler())
    dispatcher = RuntimeActionDispatcher(registry)

    request = _request()
    result = dispatcher.route(request)
    event = dispatcher.action_log[0]

    with pytest.raises(FrozenInstanceError):
        request.source = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        event.status = "failed"  # type: ignore[misc]


def test_result_status_must_be_valid() -> None:
    """status 词表 fail-closed，避免报告层自造 blocked/pass 等状态。"""

    with pytest.raises(ValueError, match="invalid RuntimeActionResult.status"):
        RuntimeActionResult(
            action_type=RuntimeActionType.TOOL_REQUEST,
            action_id="act-invalid",
            status="definitely_not_valid",
            payload={},
            evidence={},
        )


def test_result_evidence_rejects_secret_like_values() -> None:
    """evidence 是审计材料，不能带 raw key/token。"""

    with pytest.raises(ValueError, match="secret-like"):
        RuntimeActionResult(
            action_type=RuntimeActionType.TOOL_REQUEST,
            action_id="act-secret",
            status="success",
            payload={},
            evidence={"safe": "api_key=sk-testsecret123456789"},
        )


def test_dispatcher_routes_and_emits_receipt_event_with_independent_proof() -> None:
    """完整 runtime_e2e 必须同时有 event、dispatcher、handler、module proof。"""

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _ObservedHandler())
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "success"
    assert result.evidence["dispatcher_routed"] is True
    assert result.evidence["target_handler_invoked"] is True
    assert result.evidence["module_invoked"] is True
    assert result.evidence["result_returned_to_parent_runtime"] is True
    assert result.evidence["evidence_level"] == "runtime_e2e"

    proof = result.evidence["target_module_proof"]
    assert proof["proof_id"]
    assert proof["observation_independent"] is True
    assert proof["linked_action_id"] == result.action_id
    assert proof["linked_target_module"] == result.evidence["target_module"]
    assert proof["observer_identity"] != result.evidence["handler_name"]

    assert len(dispatcher.action_log) == 1
    event = dispatcher.action_log[0]
    assert event.action_id == result.action_id
    assert event.evidence["action_id"] == result.action_id


def test_runtime_action_event_only_is_not_runtime_e2e() -> None:
    """receipt-only 不能通过：event 只能证明 route() 发生过，不能证明目标模块执行。"""

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _NoModuleHandler())
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert dispatcher.action_log
    assert result.evidence["module_invoked"] is False
    assert result.evidence["target_module_proof"] is None
    assert result.evidence["evidence_level"] != "runtime_e2e"


def test_handler_self_asserted_target_module_proof_is_rejected() -> None:
    """handler 自己填 proof 不是独立观测，不能把 direct/subsystem 包装成 runtime_e2e。"""

    evidence = {
        "action_id": "act-self",
        "action_type": "tool.request",
        "dispatcher_routed": True,
        "target_handler_invoked": True,
        "handler_name": "SelfAssertingHandler",
        "target_module": "ToolRegistry",
        "module_invoked": True,
        "invocation_proof": {
            "call_id": "call-self",
            "function_called": "ToolRegistry.lookup",
            "call_signature": "lookup(str)",
            "observed_at": "2026-05-20T00:00:00+00:00",
            "observation_method": "handler_self_report",
        },
        "target_module_proof": {
            "proof_id": "proof-self",
            "observation_source": "handler_self_report",
            "observer_identity": "SelfAssertingHandler",
            "observation_independent": False,
            "linked_action_id": "act-self",
            "linked_target_module": "ToolRegistry",
        },
        "result_returned_to_parent_runtime": True,
        "parent_adjudicated": None,
        "evidence_level": "runtime_e2e",
    }

    assert not is_runtime_e2e_evidence(evidence)
    assert classify_evidence_level(evidence) == "subsystem_integration"


@pytest.mark.parametrize(
    "forged_update",
    [
        {"target_module_proof": {"proof_id": "proof-forged"}},
        {"module_invoked": True},
        {"evidence_level": "runtime_e2e"},
    ],
)
def test_handler_evidence_update_cannot_override_runtime_proof(forged_update: dict) -> None:
    """handler 的 business evidence 不能覆盖 dispatcher/observer/classifier 字段。"""

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _ForgedEvidenceUpdateHandler(forged_update))
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "failed"
    assert result.evidence["module_invoked"] is False
    assert result.evidence["target_module_proof"] is None
    assert result.evidence["evidence_level"] != "runtime_e2e"
    assert result.evidence["error_type"] == "ValueError"


def test_handler_cannot_self_mint_runtime_e2e() -> None:
    """手工返回 shaped proof 的 handler 不能越过 observer registry。"""

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _SelfMintingHandler())
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "success"
    assert result.evidence["module_invoked"] is True
    assert result.evidence["target_module_proof"]["proof_id"] == "proof-shaped"
    assert result.evidence["evidence_level"] != "runtime_e2e"


def test_handler_evidence_update_core_fields_are_rejected_or_namespaced() -> None:
    """action_id/target_module 等核心字段由 runtime 拥有，handler 触碰即失败。"""

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.TOOL_REQUEST,
        _ForgedEvidenceUpdateHandler({"action_id": "act-other", "target_module": "OtherModule"}),
    )
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "failed"
    assert result.evidence["target_module"] == "unknown"
    assert result.evidence["evidence_level"] != "runtime_e2e"


def test_handler_returned_action_id_mismatch_fails_closed() -> None:
    """手工 RuntimeActionResult 的 action_id 不能替代 dispatcher 分配的 action_id。"""

    evidence = _shaped_runtime_evidence(action_id="act-forged")
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _ManualResultHandler(action_id="act-forged", evidence=evidence))
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "failed"
    assert result.evidence["runtime_e2e_disqualified_reason"] == "handler returned mismatched action_id"
    assert result.evidence["evidence_level"] != "runtime_e2e"


def _shaped_runtime_evidence(
    *,
    action_id: str = "act-shaped",
    target_module: str = "FakeTargetModule",
    proof_id: str = "proof-shaped",
    call_id: str = "call-shaped",
    observation_independent: bool = True,
) -> dict:
    return {
        "action_id": action_id,
        "action_type": "tool.request",
        "dispatcher_routed": True,
        "target_handler_invoked": True,
        "handler_name": "AnyHandler",
        "target_module": target_module,
        "module_invoked": True,
        "invocation_proof": {
            "call_id": call_id,
            "function_called": "FakeTargetModule.run",
            "call_signature": "run()",
            "observed_at": "2026-05-20T00:00:00+00:00",
            "observation_method": "module_spy",
        },
        "target_module_proof": {
            "proof_id": proof_id,
            "observation_source": "module_spy",
            "observer_identity": "RuntimeActionModuleObserver",
            "observation_independent": observation_independent,
            "linked_action_id": action_id,
            "linked_target_module": target_module,
            "linked_call_id": call_id,
        },
        "result_returned_to_parent_runtime": True,
        "parent_adjudicated": None,
    }


def test_shaped_dict_target_module_proof_is_rejected() -> None:
    """字段形状像 observer proof 但没有登记 provenance，不能通过。"""

    evidence = _shaped_runtime_evidence()

    assert not is_runtime_e2e_evidence(evidence)
    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_free_text_invocation_proof_is_rejected() -> None:
    """free-text proof 不是结构化 observer 调用证据。"""

    evidence = _shaped_runtime_evidence()
    evidence["invocation_proof"] = "handler says module ran"

    assert not is_runtime_e2e_evidence(evidence)
    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_manual_observed_module_call_without_observer_registry_is_rejected() -> None:
    """手工构造 ObservedModuleCall 对象也不能绕过 observer registry。"""

    manual = ObservedModuleCall(
        value={"ok": True},
        invocation_proof={
            "call_id": "call-manual",
            "function_called": "FakeTargetModule.run",
            "call_signature": "run()",
            "observed_at": "2026-05-20T00:00:00+00:00",
            "observation_method": "module_spy",
        },
        target_module_proof={
            "proof_id": "proof-manual",
            "observation_source": "module_spy",
            "observer_identity": "RuntimeActionModuleObserver",
            "observation_independent": True,
            "linked_action_id": "act-manual",
            "linked_target_module": "FakeTargetModule",
            "linked_call_id": "call-manual",
        },
    )
    evidence = _shaped_runtime_evidence(
        action_id="act-manual",
        proof_id=manual.target_module_proof["proof_id"],
        call_id=manual.invocation_proof["call_id"],
    )

    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_proof_action_id_mismatch_is_not_runtime_e2e() -> None:
    evidence = _shaped_runtime_evidence()
    evidence["target_module_proof"]["linked_action_id"] = "act-other"

    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_proof_target_module_mismatch_is_not_runtime_e2e() -> None:
    evidence = _shaped_runtime_evidence()
    evidence["target_module_proof"]["linked_target_module"] = "OtherModule"

    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_observation_independent_false_is_not_runtime_e2e() -> None:
    evidence = _shaped_runtime_evidence(observation_independent=False)

    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_module_invoked_without_target_module_proof_is_not_runtime_e2e() -> None:
    """module_invoked=true 仍不够；缺 target_module_proof 最高只能 subsystem。"""

    evidence = {
        "action_id": "act-no-proof",
        "action_type": "checkpoint.safe_summary",
        "dispatcher_routed": True,
        "target_handler_invoked": True,
        "handler_name": "CheckpointSafeSummaryHandler",
        "target_module": "CheckpointSafeSummary",
        "module_invoked": True,
        "invocation_proof": {
            "call_id": "call-1",
            "function_called": "CheckpointSafeSummary.redact",
            "call_signature": "redact(str)",
            "observed_at": "2026-05-20T00:00:00+00:00",
            "observation_method": "module_spy",
        },
        "target_module_proof": None,
        "result_returned_to_parent_runtime": True,
        "parent_adjudicated": None,
    }

    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_unknown_action_type_returns_not_supported_and_still_emits_event() -> None:
    """未知 action 不能 crash；receipt 可见，但不是 runtime_e2e。"""

    dispatcher = RuntimeActionDispatcher(ActionHandlerRegistry())

    result = dispatcher.route(_request("unknown.action"))

    assert result.status == "not_supported"
    assert result.evidence["dispatcher_routed"] is True
    assert result.evidence["target_handler_invoked"] is False
    assert result.evidence["module_invoked"] is False
    assert result.evidence["evidence_level"] != "runtime_e2e"
    assert dispatcher.action_log[0].action_id == result.action_id

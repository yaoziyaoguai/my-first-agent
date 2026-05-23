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
from agent.runtime_integration.evidence import ObservedModuleCall, RuntimeActionModuleObserver


class _ObservedHandler:
    """通过 catalog-owned invocation 调用目标模块，不能自己 mint proof。"""

    def handle(self, request, context):  # noqa: ANN001
        observed = context.invoke_registered_target(
            target_module="FakeTargetModule",
            operation="run",
            payload={"value": {"ok": True}},
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


class _ManualObservedResultHandler:
    """先通过 observer 拿到真实 proof，再手工拼 RuntimeActionResult。"""

    def handle(self, request, context):  # noqa: ANN001
        observed = context.observe_module_call(
            target_module="FakeTargetModule",
            function_called="FakeTargetModule.run",
            call_signature="run()",
            call=lambda: {"ok": True},
        )
        evidence = {
            "action_id": context.action_id,
            "action_type": "tool.request",
            "dispatcher_route_id": context.route_id,
            "dispatcher_result_id": "result:manual",
            "dispatcher_result_issued": True,
            "dispatcher_routed": True,
            "target_handler_invoked": True,
            "handler_name": type(self).__name__,
            "target_module": "FakeTargetModule",
            "module_invoked": True,
            "invocation_proof": observed.invocation_proof,
            "target_module_proof": observed.target_module_proof,
            "result_returned_to_parent_runtime": True,
            "parent_adjudicated": None,
        }
        return RuntimeActionResult(
            action_type=request.action_type,
            action_id=context.action_id,
            status="success",
            payload={"ok": True},
            evidence=evidence,
        )


class _TwoIssuedResultsSameRouteHandler:
    """同一 route 内发行两个 result，用于红队交叉复用 result/proof。

    中文学习边界：dispatcher 可以在一次 handler 调用中发行多个结果对象；
    runtime_e2e 不能只证明“这个 route 有某个 proof”和“这个 route 有某个 result”，
    而要证明 proof/call/target 属于同一个 dispatcher-issued result。
    """

    def __init__(self) -> None:
        self.issued_evidence: list[dict] = []

    def handle(self, request, context):  # noqa: ANN001
        first_observed = context.invoke_registered_target(
            target_module="FakeTargetModule",
            operation="run",
            payload={"value": {"ok": "first"}},
        )
        first = context.success(
            handler_name=type(self).__name__,
            target_module="FakeTargetModule",
            payload={"ok": first_observed.value["ok"]},
            observed_call=first_observed,
        )
        second_observed = context.invoke_registered_target(
            target_module="FakeTargetModule",
            operation="run",
            payload={"value": {"ok": "second"}},
        )
        second = context.success(
            handler_name=type(self).__name__,
            target_module="FakeTargetModule",
            payload={"ok": second_observed.value["ok"]},
            observed_call=second_observed,
        )
        self.issued_evidence = [dict(first.evidence), dict(second.evidence)]
        return second


class _ForgedTargetLabelHandler:
    """调用普通 callable，却把 target_module 标成生产 target 的恶意 handler。

    中文学习边界：route/result/proof/call 全部自洽仍不够；如果 target identity
    是 handler 自己说了算，任意 callable 都能伪装成 ToolRegistry/SkillLoader。
    """

    def __init__(self, target_module: str, evidence_extra: dict | None = None) -> None:
        self._target_module = target_module
        self._evidence_extra = dict(evidence_extra or {})

    def handle(self, request, context):  # noqa: ANN001
        observed = context.observe_module_call(
            target_module=self._target_module,
            function_called=f"{self._target_module}.forged",
            call_signature="forged()",
            call=lambda: {"forged": True},
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module=self._target_module,
            payload={"forged": True},
            observed_call=observed,
            evidence_extra=self._evidence_extra,
        )


class _CatalogAllowedForgedCallableHandler:
    """catalog 允许该 handler/label，但它传入 arbitrary lambda。

    中文学习边界：这是本轮 P1 的核心红队模型。handler identity 和 target_module
    label 都能命中 catalog，但实际 callable 不是 descriptor 绑定的 adapter，
    所以 observer 必须降级为 untrusted target proof。
    """

    def __init__(self, target_module: str, evidence_extra: dict | None = None) -> None:
        self._target_module = target_module
        self._evidence_extra = dict(evidence_extra or {})

    def handle(self, request, context):  # noqa: ANN001
        observed = context.observe_module_call(
            target_module=self._target_module,
            function_called=f"{self._target_module}.test_catalog_adapter",
            call_signature="test_catalog_adapter()",
            call=lambda: {"forged": True},
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module=self._target_module,
            payload={"forged": True},
            observed_call=observed,
            evidence_extra=self._evidence_extra,
        )


class _MissingDescriptorInvocationHandler:
    """使用 trusted API 但请求未注册 operation，应 fail closed。"""

    def handle(self, request, context):  # noqa: ANN001
        observed = context.invoke_registered_target(
            target_module="ToolRegistry",
            operation="missing_operation",
            payload={"value": {"ok": True}},
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module="ToolRegistry",
            payload={"ok": True},
            observed_call=observed,
        )


def _request(action_type: str | RuntimeActionType = RuntimeActionType.TOOL_REQUEST) -> RuntimeActionRequest:
    return RuntimeActionRequest(
        action_type=action_type,
        source="llm_tool_call",
        parent_trace_id="trace-test",
        payload={"tool_name": "read_file", "tool_args": {}, "risk_reason": "test"},
        constraints={"no_network"},
    )


def _valid_runtime_e2e_evidence(action_type: str | RuntimeActionType = RuntimeActionType.TOOL_REQUEST) -> dict:
    """生成有效 E2E evidence（harness 路径：直接 dispatcher 调用，无 core_loop_invoked）。"""
    registry = ActionHandlerRegistry()
    registry.register(action_type, _ObservedHandler())
    dispatcher = RuntimeActionDispatcher(registry)
    result = dispatcher.route(_request(action_type))
    # Phase 1: 直接 dispatcher 调用无 core_loop_invoked，分类为 harness_runtime_e2e
    assert result.evidence["evidence_level"] == "harness_runtime_e2e"
    return dict(result.evidence)


def _assert_not_runtime_e2e(evidence: dict) -> None:
    """断言 evidence 不被分类为任何 runtime_e2e 级别。"""
    assert not is_runtime_e2e_evidence(evidence)
    level = classify_evidence_level(evidence)
    assert level != "real_core_loop_runtime_e2e", f"unexpected real_core_loop_runtime_e2e: {level}"
    assert level != "harness_runtime_e2e", f"unexpected harness_runtime_e2e: {level}"
    if "evidence_level" in evidence:
        assert evidence["evidence_level"] != "real_core_loop_runtime_e2e"
        assert evidence["evidence_level"] != "harness_runtime_e2e"


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
    assert result.evidence["evidence_level"] == "harness_runtime_e2e"

    proof = result.evidence["target_module_proof"]
    assert proof["proof_id"]
    assert proof["observation_independent"] is True
    assert proof["linked_route_id"] == result.evidence["dispatcher_route_id"]
    assert proof["linked_action_id"] == result.action_id
    assert proof["linked_action_type"] == result.evidence["action_type"]
    assert proof["linked_handler_name"] == result.evidence["handler_name"]
    assert proof["linked_target_module"] == result.evidence["target_module"]
    assert proof["observer_identity"] != result.evidence["handler_name"]
    assert result.evidence["dispatcher_result_issued"] is True
    assert result.evidence["dispatcher_result_id"].startswith("result:")
    assert result.evidence["target_handle"]
    assert result.evidence["target_catalog_allowed"] is True
    assert result.evidence["target_descriptor_id"]
    assert result.evidence["invocation_adapter_id"]
    assert result.evidence["implementation_id"]
    assert result.evidence["callable_identity"]
    assert result.evidence["target_identity_valid"] is True
    assert proof["descriptor_invocation_approved"] is True

    assert len(dispatcher.action_log) == 1
    event = dispatcher.action_log[0]
    assert event.action_id == result.action_id
    assert event.evidence["action_id"] == result.action_id


def test_catalog_owned_invocation_descriptor_path_can_be_runtime_e2e() -> None:
    """正例只能通过 catalog-owned adapter path 升级 runtime_e2e。"""

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _ObservedHandler())
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())
    proof = result.evidence["target_module_proof"]

    assert result.evidence["evidence_level"] == "harness_runtime_e2e"
    assert result.evidence["target_catalog_allowed"] is True
    assert result.evidence["target_identity_valid"] is True
    assert proof["descriptor_invocation_approved"] is True
    assert proof["callable_identity"] == result.evidence["callable_identity"]


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


def test_manual_result_with_registered_proof_is_not_runtime_e2e() -> None:
    """真实 observer proof 也不能让手工 RuntimeActionResult 变成 runtime_e2e。"""

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _ManualObservedResultHandler())
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "failed"
    assert result.evidence["target_module_proof"] is None
    assert result.evidence["evidence_level"] != "runtime_e2e"
    assert result.evidence["runtime_e2e_disqualified_reason"] == "handler returned unissued RuntimeActionResult"


def test_observer_registered_proof_without_dispatcher_route_is_rejected() -> None:
    """observer 直接登记 proof 但没有 dispatcher route registry，仍不能通过。"""

    observer = RuntimeActionModuleObserver()
    observed = observer.observe(
        route_id="route-outside-dispatcher",
        action_id="act-outside-dispatcher",
        action_type="tool.request",
        handler_name="OutsideHandler",
        target_module="FakeTargetModule",
        function_called="FakeTargetModule.run",
        call_signature="run()",
        call=lambda: {"ok": True},
    )
    evidence = _shaped_runtime_evidence(
        action_id="act-outside-dispatcher",
        proof_id=observed.target_module_proof["proof_id"],
        call_id=observed.invocation_proof["call_id"],
    )
    evidence.update({
        "dispatcher_route_id": "route-outside-dispatcher",
        "dispatcher_result_id": "result-outside-dispatcher",
        "dispatcher_result_issued": True,
        "handler_name": "OutsideHandler",
        "invocation_proof": observed.invocation_proof,
        "target_module_proof": observed.target_module_proof,
    })

    assert not is_runtime_e2e_evidence(evidence)
    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_forged_target_label_as_tool_registry_is_not_runtime_e2e() -> None:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _ForgedTargetLabelHandler("ToolRegistry"))
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.evidence["target_module"] == "ToolRegistry"
    assert result.evidence["target_module_proof"]["linked_target_module"] == "ToolRegistry"
    assert result.evidence["evidence_level"] != "runtime_e2e"


@pytest.mark.parametrize("target_module", ["SkillLoader", "SkillRegistry"])
def test_forged_target_label_as_skill_target_is_not_runtime_e2e(target_module: str) -> None:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.SKILL_SELECT, _ForgedTargetLabelHandler(target_module))
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request(RuntimeActionType.SKILL_SELECT))

    assert result.evidence["target_module"] == target_module
    assert result.evidence["evidence_level"] != "runtime_e2e"


def test_forged_target_label_as_checkpoint_is_not_runtime_e2e() -> None:
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
        _ForgedTargetLabelHandler(
            "CheckpointSafeSummary",
            evidence_extra={
                "checkpoint_boundary": "turn_end_before_save_checkpoint",
                "no_tool_boundary_reached": True,
                "tool_after_only_trigger": False,
            },
        ),
    )
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request(RuntimeActionType.CHECKPOINT_SAFE_SUMMARY))

    assert result.evidence["target_module"] == "CheckpointSafeSummary"
    assert result.evidence["evidence_level"] != "runtime_e2e"


def test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_tool_registry() -> None:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _CatalogAllowedForgedCallableHandler("ToolRegistry"))
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.evidence["target_module"] == "ToolRegistry"
    assert result.evidence["target_catalog_allowed"] is False
    assert result.evidence["target_identity_valid"] is False
    assert result.evidence["target_handle"] == ""
    assert result.evidence["target_module_proof"]["target_identity_valid"] is False
    _assert_not_runtime_e2e(result.evidence)


@pytest.mark.parametrize("target_module", ["SkillLoader", "SkillRegistry"])
def test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_skill_loader(target_module: str) -> None:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.SKILL_SELECT, _CatalogAllowedForgedCallableHandler(target_module))
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request(RuntimeActionType.SKILL_SELECT))

    assert result.evidence["target_module"] == target_module
    assert result.evidence["target_catalog_allowed"] is False
    assert result.evidence["target_identity_valid"] is False
    assert result.evidence["target_module_proof"]["target_identity_valid"] is False
    _assert_not_runtime_e2e(result.evidence)


def test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_checkpoint() -> None:
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
        _CatalogAllowedForgedCallableHandler(
            "CheckpointSafeSummary",
            evidence_extra={
                "checkpoint_boundary": "turn_end_before_save_checkpoint",
                "no_tool_boundary_reached": True,
                "tool_after_only_trigger": False,
            },
        ),
    )
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request(RuntimeActionType.CHECKPOINT_SAFE_SUMMARY))

    assert result.evidence["target_module"] == "CheckpointSafeSummary"
    assert result.evidence["target_catalog_allowed"] is False
    assert result.evidence["target_identity_valid"] is False
    assert result.evidence["target_module_proof"]["target_identity_valid"] is False
    _assert_not_runtime_e2e(result.evidence)


# ===== SubAgent overclaim prevention =====


def test_forged_target_label_as_subagent_executor_is_not_runtime_e2e() -> None:
    """任意 callable 标为 SubAgentExecutor 不能获得 runtime_e2e。

    SubAgent 在 is_runtime_e2e_evidence() 中有特殊 parent_adjudicated 规则，
    handler 传入的 evidence_extra 不能绕过 target identity 验证。
    """
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.SUBAGENT_DELEGATE_L0,
        _ForgedTargetLabelHandler(
            "SubAgentExecutor",
            evidence_extra={
                "no_nested_delegation": True,
                "no_shell_or_external_process": True,
            },
        ),
    )
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request(RuntimeActionType.SUBAGENT_DELEGATE_L0))

    assert result.evidence["target_module"] == "SubAgentExecutor"
    assert result.evidence["evidence_level"] != "runtime_e2e"
    _assert_not_runtime_e2e(result.evidence)


def test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_subagent_executor() -> None:
    """catalog 允许 handler/label 但传入 arbitrary lambda 不能获得 trusted target proof。

    SubAgentExecutor 在 catalog 中有 descriptor（_subagent_delegate_once_adapter），
    但 handler 通过 observe_module_call（非 invoke_registered_target）传入的
    arbitrary lambda 不匹配 catalog adapter identity。
    """
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.SUBAGENT_DELEGATE_L0,
        _CatalogAllowedForgedCallableHandler(
            "SubAgentExecutor",
            evidence_extra={
                "no_nested_delegation": True,
                "no_shell_or_external_process": True,
            },
        ),
    )
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request(RuntimeActionType.SUBAGENT_DELEGATE_L0))

    assert result.evidence["target_module"] == "SubAgentExecutor"
    assert result.evidence["target_catalog_allowed"] is False
    assert result.evidence["target_identity_valid"] is False
    assert result.evidence["target_module_proof"]["target_identity_valid"] is False
    _assert_not_runtime_e2e(result.evidence)


def test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_streaming_provider() -> None:
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.STREAMING_PROVIDER_CALL,
        _CatalogAllowedForgedCallableHandler("StreamingProtocol"),
    )
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request(RuntimeActionType.STREAMING_PROVIDER_CALL))

    assert result.evidence["target_module"] == "StreamingProtocol"
    assert result.evidence["target_catalog_allowed"] is False
    assert result.evidence["target_identity_valid"] is False
    assert result.evidence["target_module_proof"]["descriptor_invocation_approved"] is False
    _assert_not_runtime_e2e(result.evidence)


def _mutated_valid_evidence(field_name: str, wrong_value: str) -> dict:
    evidence = _valid_runtime_e2e_evidence()
    evidence["target_module_proof"] = dict(evidence["target_module_proof"])
    evidence[field_name] = wrong_value
    evidence["target_module_proof"][field_name] = wrong_value
    evidence["evidence_level"] = classify_evidence_level(evidence)
    return evidence


def test_correct_target_label_wrong_callable_identity_is_not_runtime_e2e() -> None:
    evidence = _mutated_valid_evidence(
        "callable_identity",
        "function:tests.runtime_integration.wrong_callable",
    )

    assert evidence["target_catalog_allowed"] is True
    assert evidence["target_identity_valid"] is True
    _assert_not_runtime_e2e(evidence)


def test_correct_target_label_wrong_invocation_adapter_is_not_runtime_e2e() -> None:
    evidence = _mutated_valid_evidence("invocation_adapter_id", "WrongTarget.wrong_adapter")

    assert evidence["target_catalog_allowed"] is True
    assert evidence["target_identity_valid"] is True
    _assert_not_runtime_e2e(evidence)


def test_correct_target_label_wrong_implementation_id_is_not_runtime_e2e() -> None:
    evidence = _mutated_valid_evidence("implementation_id", "WrongTarget.wrong_implementation")

    assert evidence["target_catalog_allowed"] is True
    assert evidence["target_identity_valid"] is True
    _assert_not_runtime_e2e(evidence)


def test_correct_target_label_without_target_descriptor_is_not_runtime_e2e() -> None:
    evidence = _valid_runtime_e2e_evidence()
    evidence["target_module_proof"] = dict(evidence["target_module_proof"])
    for field_name in (
        "target_descriptor_id",
        "callable_identity",
        "invocation_adapter_id",
        "implementation_id",
    ):
        evidence[field_name] = ""
        evidence["target_module_proof"][field_name] = None
    evidence["evidence_level"] = classify_evidence_level(evidence)

    assert evidence["target_catalog_allowed"] is True
    _assert_not_runtime_e2e(evidence)


def test_public_observer_correct_label_arbitrary_callable_is_not_runtime_e2e() -> None:
    observed = RuntimeActionModuleObserver().observe(
        route_id="route-public-toolregistry",
        action_id="act-public-toolregistry",
        action_type="tool.request",
        handler_name="ToolGateHandler",
        target_module="ToolRegistry",
        function_called="ToolRegistry.lookup_and_risk_check",
        call_signature="lookup_and_risk_check(tool_name: str)",
        call=lambda: {"forged": True},
    )
    evidence = _shaped_runtime_evidence(
        action_id="act-public-toolregistry",
        target_module="ToolRegistry",
        proof_id=observed.target_module_proof["proof_id"],
        call_id=observed.invocation_proof["call_id"],
    )
    evidence.update({
        "dispatcher_route_id": "route-public-toolregistry",
        "dispatcher_result_id": "result-public-toolregistry",
        "dispatcher_result_issued": True,
        "handler_name": "ToolGateHandler",
        "target_catalog_id": "",
        "target_handle": "",
        "target_descriptor_id": "",
        "invocation_adapter_id": "",
        "implementation_id": "",
        "callable_identity": "",
        "target_catalog_allowed": False,
        "target_identity_valid": False,
        "invocation_proof": observed.invocation_proof,
        "target_module_proof": observed.target_module_proof,
    })

    assert observed.target_module_proof["target_catalog_allowed"] is False
    assert observed.target_module_proof["target_identity_valid"] is False
    assert observed.target_module_proof["linked_target_handle"] is None
    assert observed.target_module_proof["target_descriptor_id"] is None
    assert observed.target_module_proof["callable_identity"] is None
    _assert_not_runtime_e2e(evidence)


def test_descriptor_handle_without_descriptor_approved_call_is_not_runtime_e2e() -> None:
    evidence = _valid_runtime_e2e_evidence()
    evidence["invocation_proof"] = dict(evidence["invocation_proof"])
    evidence["target_module_proof"] = dict(evidence["target_module_proof"])
    evidence["invocation_proof"]["call_id"] = "call:not-produced-by-descriptor"
    evidence["target_module_proof"]["linked_call_id"] = "call:not-produced-by-descriptor"
    evidence["evidence_level"] = classify_evidence_level(evidence)

    assert evidence["target_handle"]
    assert evidence["target_descriptor_id"]
    _assert_not_runtime_e2e(evidence)


def test_target_descriptor_mismatch_across_route_result_proof_is_not_runtime_e2e() -> None:
    evidence = _valid_runtime_e2e_evidence()
    evidence["target_module_proof"] = dict(evidence["target_module_proof"])
    evidence["target_module_proof"]["target_descriptor_id"] = "descriptor:other-target"
    evidence["evidence_level"] = classify_evidence_level(evidence)

    assert evidence["target_descriptor_id"]
    assert evidence["target_module_proof"]["target_descriptor_id"] != evidence["target_descriptor_id"]
    _assert_not_runtime_e2e(evidence)


def test_target_descriptor_missing_fails_closed_is_not_runtime_e2e() -> None:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _MissingDescriptorInvocationHandler())
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "failed"
    assert result.evidence["module_invoked"] is False
    assert result.evidence["target_module_proof"] is None
    assert result.evidence["target_catalog_allowed"] is False
    assert result.evidence["target_identity_valid"] is False
    assert result.evidence["error_type"] == "ValueError"
    _assert_not_runtime_e2e(result.evidence)


def test_handler_chosen_arbitrary_target_module_cannot_become_trusted_by_matching_strings() -> None:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _ForgedTargetLabelHandler("InventedRuntimeTarget"))
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.evidence["target_module"] == "InventedRuntimeTarget"
    assert result.evidence["evidence_level"] != "runtime_e2e"


def test_missing_allowed_target_catalog_fails_closed() -> None:
    evidence = _valid_runtime_e2e_evidence()
    evidence["target_module_proof"] = dict(evidence["target_module_proof"])
    evidence["target_module_proof"].pop("linked_target_handle", None)
    evidence.pop("target_handle", None)
    evidence["target_catalog_allowed"] = False

    assert not is_runtime_e2e_evidence(evidence)
    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_public_registry_forged_route_and_result_are_not_runtime_e2e() -> None:
    """公开 registry 不能成为 runtime_e2e 信任根。

    中文学习边界：字段全部对齐也不够；如果 route/result/proof 不是 dispatcher
    内部发行的同一张 receipt，classifier 必须 fail closed。
    """

    route_id = "route-forged-public"
    result_id = "result-forged-public"
    action_id = "act-forged-public"
    handler_name = "ForgedPublicHandler"
    RuntimeActionModuleObserver.register_dispatch_route(
        route_id=route_id,
        action_id=action_id,
        action_type="tool.request",
        handler_name=handler_name,
    )
    RuntimeActionModuleObserver.register_dispatch_result(
        route_id=route_id,
        result_id=result_id,
        action_id=action_id,
        action_type="tool.request",
        handler_name=handler_name,
    )
    observed = RuntimeActionModuleObserver().observe(
        route_id=route_id,
        action_id=action_id,
        action_type="tool.request",
        handler_name=handler_name,
        target_module="FakeTargetModule",
        function_called="FakeTargetModule.run",
        call_signature="run()",
        call=lambda: {"ok": True},
    )
    evidence = {
        "action_id": action_id,
        "action_type": "tool.request",
        "dispatcher_route_id": route_id,
        "dispatcher_result_id": result_id,
        "dispatcher_result_issued": True,
        "dispatcher_routed": True,
        "target_handler_invoked": True,
        "handler_name": handler_name,
        "target_module": "FakeTargetModule",
        "module_invoked": True,
        "invocation_proof": observed.invocation_proof,
        "target_module_proof": observed.target_module_proof,
        "result_returned_to_parent_runtime": True,
        "parent_adjudicated": None,
    }

    assert not is_runtime_e2e_evidence(evidence)
    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_public_registry_cannot_register_trusted_target_identity() -> None:
    """public registry 即使字段伪造成 ToolRegistry，也不能获得 trusted target handle。"""

    route_id = "route-forged-target-public"
    result_id = "result-forged-target-public"
    action_id = "act-forged-target-public"
    handler_name = "ToolGateHandler"
    RuntimeActionModuleObserver.register_dispatch_route(
        route_id=route_id,
        action_id=action_id,
        action_type="tool.request",
        handler_name=handler_name,
    )
    RuntimeActionModuleObserver.register_dispatch_result(
        route_id=route_id,
        result_id=result_id,
        action_id=action_id,
        action_type="tool.request",
        handler_name=handler_name,
    )
    observed = RuntimeActionModuleObserver().observe(
        route_id=route_id,
        action_id=action_id,
        action_type="tool.request",
        handler_name=handler_name,
        target_module="ToolRegistry",
        function_called="ToolRegistry.lookup_and_risk_check",
        call_signature="lookup_and_risk_check(tool_name: str)",
        call=lambda: {"name": "read_file"},
    )
    forged_proof = dict(observed.target_module_proof)
    forged_proof.update({
        "linked_dispatcher_result_id": result_id,
        "linked_target_handle": "target:tool.request:ToolGateHandler:ToolRegistry",
        "target_catalog_allowed": True,
    })
    evidence = {
        "action_id": action_id,
        "action_type": "tool.request",
        "dispatcher_route_id": route_id,
        "dispatcher_result_id": result_id,
        "dispatcher_result_issued": True,
        "dispatcher_routed": True,
        "target_handler_invoked": True,
        "handler_name": handler_name,
        "target_module": "ToolRegistry",
        "target_handle": forged_proof["linked_target_handle"],
        "target_catalog_allowed": True,
        "module_invoked": True,
        "invocation_proof": observed.invocation_proof,
        "target_module_proof": forged_proof,
        "result_returned_to_parent_runtime": True,
        "parent_adjudicated": None,
    }

    assert not is_runtime_e2e_evidence(evidence)
    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_same_route_different_result_transplant_is_not_runtime_e2e() -> None:
    """同 route 内 proof/result 交叉复用不能伪造成 runtime_e2e。"""

    handler = _TwoIssuedResultsSameRouteHandler()
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, handler)
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.evidence["evidence_level"] == "harness_runtime_e2e"
    first, second = handler.issued_evidence
    assert first["dispatcher_route_id"] == second["dispatcher_route_id"]
    assert first["dispatcher_result_id"] != second["dispatcher_result_id"]

    forged = dict(first)
    forged["dispatcher_result_id"] = second["dispatcher_result_id"]
    forged["result_returned_to_parent_runtime"] = True

    assert not is_runtime_e2e_evidence(forged)
    assert classify_evidence_level(forged) == "subsystem_integration"


def test_registered_proof_reused_with_different_route_is_rejected() -> None:
    evidence = _valid_runtime_e2e_evidence()
    other = _valid_runtime_e2e_evidence()
    evidence["dispatcher_route_id"] = other["dispatcher_route_id"]
    evidence["dispatcher_result_id"] = other["dispatcher_result_id"]

    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_registered_proof_reused_with_different_action_type_is_rejected() -> None:
    evidence = _valid_runtime_e2e_evidence()
    evidence["action_type"] = "tool.gate"

    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_registered_proof_reused_with_different_handler_is_rejected() -> None:
    evidence = _valid_runtime_e2e_evidence()
    evidence["handler_name"] = "OtherHandler"

    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_registered_proof_reused_with_different_target_module_is_rejected() -> None:
    evidence = _valid_runtime_e2e_evidence()
    evidence["target_module"] = "OtherTargetModule"

    assert classify_evidence_level(evidence) == "subsystem_integration"


def test_handler_cannot_supply_or_override_route_id() -> None:
    """route_id 是 dispatcher-owned provenance，handler 不能通过 evidence_extra 注入。"""

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.TOOL_REQUEST,
        _ForgedEvidenceUpdateHandler({"dispatcher_route_id": "route-forged"}),
    )
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "failed"
    assert result.evidence["module_invoked"] is False
    assert result.evidence["evidence_level"] != "runtime_e2e"


def test_runtime_e2e_requires_dispatcher_owned_route_provenance() -> None:
    evidence = _valid_runtime_e2e_evidence()
    evidence.pop("dispatcher_route_id")

    assert not is_runtime_e2e_evidence(evidence)
    assert classify_evidence_level(evidence) == "subsystem_integration"


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
        {"dispatcher_result_id": "result-forged"},
        {"target_descriptor_id": "descriptor-forged"},
        {"invocation_adapter_id": "adapter-forged"},
        {"implementation_id": "implementation-forged"},
        {"callable_identity": "function:forged"},
        {"target_identity_valid": True},
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


def test_handler_evidence_update_cannot_override_dispatcher_result_id() -> None:
    """dispatcher_result_id 是 result receipt，handler evidence_update 不能覆盖。"""

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.TOOL_REQUEST,
        _ForgedEvidenceUpdateHandler({"dispatcher_result_id": "result-forged"}),
    )
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "failed"
    assert result.evidence["target_module_proof"] is None
    assert result.evidence["evidence_level"] != "runtime_e2e"
    assert result.evidence["error_type"] == "ValueError"


def test_handler_cannot_self_mint_runtime_e2e() -> None:
    """手工返回 shaped proof 的 handler 不能越过 observer registry。"""

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, _SelfMintingHandler())
    dispatcher = RuntimeActionDispatcher(registry)

    result = dispatcher.route(_request())

    assert result.status == "failed"
    assert result.evidence["module_invoked"] is False
    assert result.evidence["target_module_proof"] is None
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

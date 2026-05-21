"""RuntimeAction dispatcher and handler registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Mapping, Protocol
from uuid import uuid4

from agent.runtime_integration.evidence import (
    ObservedModuleCall,
    RuntimeActionModuleObserver,
    RuntimeActionTargetCatalog,
    classify_evidence_level,
)
from agent.runtime_integration.schema import (
    RuntimeActionEvent,
    RuntimeActionRequest,
    RuntimeActionResult,
    RuntimeActionType,
    action_type_value,
    new_action_id,
    new_event_id,
    normalize_action_type,
)


HANDLER_EVIDENCE_RESERVED_FIELDS = frozenset({
    "action_id",
    "action_type",
    "handler_name",
    "target_module",
    "module_invoked",
    "invocation_proof",
    "target_module_proof",
    "evidence_level",
    "parent_adjudicated",
    "dispatcher_routed",
    "handler_invoked",
    "target_handler_invoked",
    "result_returned_to_parent_runtime",
    "dispatcher_route_id",
    "dispatcher_result_id",
    "dispatcher_result_issued",
    "target_catalog_id",
    "target_handle",
    "target_descriptor_id",
    "invocation_adapter_id",
    "implementation_id",
    "callable_identity",
    "target_catalog_allowed",
    "target_identity_valid",
    "descriptor_invocation_approved",
})


class ActionHandler(Protocol):
    """RuntimeAction handler protocol.

    实现偏差说明：handler 接收 `RuntimeActionContext`，这样 action_id 与独立
    observer 不会进入 model-visible payload，也不会由 handler 自己生成 proof。
    """

    def handle(self, request: RuntimeActionRequest, context: "RuntimeActionContext") -> RuntimeActionResult:
        ...


class ActionHandlerRegistry:
    """action_type -> handler 的显式 registry，不使用 module-level singleton。"""

    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, action_type: RuntimeActionType | str, handler: ActionHandler) -> None:
        self._handlers[action_type_value(normalize_action_type(action_type))] = handler

    def get(self, action_type: RuntimeActionType | str) -> ActionHandler | None:
        return self._handlers.get(action_type_value(normalize_action_type(action_type)))

    def snapshot(self) -> dict[str, str]:
        return {key: type(value).__name__ for key, value in self._handlers.items()}


@dataclass(frozen=True, slots=True)
class RuntimeActionContext:
    """单次 RuntimeAction 的执行上下文。

    context 只活在 dispatcher.route() 调用内，负责 action_id、route provenance、
    observer 和标准 result/evidence 构造；它不持久化 Runtime state。
    """

    action_id: str
    action_type: RuntimeActionType | str
    route_id: str
    handler_name: str
    handler_identity: str
    parent_trace_id: str
    observer: RuntimeActionModuleObserver
    _issued_result_ids: set[int] = field(default_factory=set, init=False, repr=False)

    def observe_module_call(
        self,
        *,
        target_module: str,
        function_called: str,
        call_signature: str,
        call,
    ) -> ObservedModuleCall:
        # 中文学习注释：这是 handler-supplied callable 兼容路径，只能证明
        # “有 callable 被 observer 包裹执行”。handler 选择的 callable 不属于
        # catalog-owned target invocation，因此不能 mint trusted target proof。
        return self.observer._observe_handler_supplied_call(
            route_id=self.route_id,
            action_id=self.action_id,
            action_type=action_type_value(self.action_type),
            handler_name=self.handler_name,
            handler_identity=self.handler_identity,
            target_module=target_module,
            function_called=function_called,
            call_signature=call_signature,
            call=call,
        )

    def invoke_registered_target(
        self,
        *,
        target_module: str,
        operation: str,
        payload: Mapping[str, Any] | None = None,
    ) -> ObservedModuleCall:
        descriptor = RuntimeActionTargetCatalog.resolve(
            action_type=action_type_value(self.action_type),
            handler_name=self.handler_name,
            handler_identity=self.handler_identity,
            target_module=target_module,
            operation=operation,
        )
        if descriptor is None:
            raise ValueError("target descriptor is not registered for this action handler")
        # 中文学习注释：trusted target invocation 的唯一入口。handler 不再把
        # callable 交给 observer；它只能给 catalog-owned adapter 提供业务 payload。
        # callable_identity / implementation_id / invocation_adapter_id 均来自
        # descriptor，classifier 会复核 route/result/proof registry 的一致性。
        return self.observer._observe_registered_invocation(
            route_id=self.route_id,
            action_id=self.action_id,
            action_type=action_type_value(self.action_type),
            handler_name=self.handler_name,
            handler_identity=self.handler_identity,
            target_descriptor=descriptor,
            payload=dict(payload or {}),
        )

    def result(
        self,
        *,
        status: str,
        handler_name: str,
        target_module: str,
        payload: dict[str, Any],
        observed_call: ObservedModuleCall | None,
        evidence_extra: dict[str, Any] | None = None,
        error_safe_preview: str = "",
        parent_adjudicated: bool | None = None,
    ) -> RuntimeActionResult:
        module_invoked = observed_call is not None
        result_id = f"result:{uuid4().hex}"
        invocation_proof = dict(observed_call.invocation_proof) if observed_call else None
        target_module_proof = dict(observed_call.target_module_proof) if observed_call else None
        target_catalog_allowed = (
            bool(target_module_proof)
            and target_module_proof.get("target_catalog_allowed") is True
        )
        target_identity_valid = (
            bool(target_module_proof)
            and target_module_proof.get("target_identity_valid") is True
        )
        target_catalog_id = (
            str(target_module_proof.get("target_catalog_id") or "")
            if target_catalog_allowed and target_module_proof
            else ""
        )
        target_handle = (
            str(target_module_proof.get("linked_target_handle") or "")
            if target_catalog_allowed and target_module_proof
            else ""
        )
        target_descriptor_id = (
            str(target_module_proof.get("target_descriptor_id") or "")
            if target_catalog_allowed and target_module_proof
            else ""
        )
        invocation_adapter_id = (
            str(target_module_proof.get("invocation_adapter_id") or "")
            if target_catalog_allowed and target_module_proof
            else ""
        )
        implementation_id = (
            str(target_module_proof.get("implementation_id") or "")
            if target_catalog_allowed and target_module_proof
            else ""
        )
        callable_identity = (
            str(target_module_proof.get("callable_identity") or "")
            if target_module_proof
            else ""
        )
        if target_module_proof is not None:
            # 中文学习注释：proof 在 observer 调用时还不知道 result_id；只有
            # context.result() 能把“本次 result”与 proof/call/target 绑定起来。
            # classifier 会验证这个反向绑定，阻止 same-route 不同 result 交叉复用。
            target_module_proof["linked_dispatcher_result_id"] = result_id
        RuntimeActionModuleObserver._issue_dispatch_result(
            route_id=self.route_id,
            result_id=result_id,
            action_id=self.action_id,
            action_type=action_type_value(self.action_type),
            handler_name=self.handler_name,
            target_module=target_module,
            proof_id=str(target_module_proof.get("proof_id")) if target_module_proof else None,
            call_id=str(invocation_proof.get("call_id")) if invocation_proof else None,
            target_catalog_id=target_catalog_id or None,
            target_handle=target_handle or None,
            target_descriptor_id=target_descriptor_id or None,
            invocation_adapter_id=invocation_adapter_id or None,
            implementation_id=implementation_id or None,
            callable_identity=callable_identity or None,
            target_catalog_allowed=target_catalog_allowed,
            target_identity_valid=target_identity_valid,
        )
        evidence: dict[str, Any] = {
            "action_id": self.action_id,
            "action_type": action_type_value(self.action_type),
            "dispatcher_route_id": self.route_id,
            "dispatcher_result_id": result_id,
            "dispatcher_result_issued": True,
            "dispatcher_routed": True,
            "target_handler_invoked": True,
            "handler_name": handler_name,
            "target_module": target_module,
            "target_catalog_id": target_catalog_id,
            "target_handle": target_handle,
            "target_descriptor_id": target_descriptor_id,
            "invocation_adapter_id": invocation_adapter_id,
            "implementation_id": implementation_id,
            "callable_identity": callable_identity,
            "target_catalog_allowed": target_catalog_allowed,
            "target_identity_valid": target_identity_valid,
            "module_invoked": module_invoked,
            "invocation_proof": invocation_proof,
            "target_module_proof": target_module_proof,
            "result_returned_to_parent_runtime": False,
            "parent_adjudicated": parent_adjudicated,
        }
        if handler_name != self.handler_name:
            raise ValueError("handler_name does not match dispatcher route provenance")
        if evidence_extra:
            overlap = HANDLER_EVIDENCE_RESERVED_FIELDS & set(evidence_extra)
            if overlap:
                # 中文学习注释：handler evidence_extra 只允许写业务证据。route、
                # observer proof 与 classifier 字段属于父 runtime 边界，触碰即
                # fail closed，防止 handler 自证自签 runtime_e2e。
                names = ", ".join(sorted(overlap))
                raise ValueError(f"handler evidence_update contains reserved field: {names}")
            evidence.update(evidence_extra)
        evidence["evidence_level"] = classify_evidence_level(evidence)
        result = RuntimeActionResult(
            action_type=self.action_type,
            action_id=self.action_id,
            status=status,
            payload=payload,
            evidence=evidence,
            error_safe_preview=error_safe_preview,
        )
        self._issued_result_ids.add(id(result))
        return result

    def issued_result(self, result: RuntimeActionResult) -> bool:
        return id(result) in self._issued_result_ids

    def success(self, **kwargs: Any) -> RuntimeActionResult:
        return self.result(status="success", **kwargs)

    def rejected(self, **kwargs: Any) -> RuntimeActionResult:
        return self.result(status="rejected", **kwargs)

    def failed(self, **kwargs: Any) -> RuntimeActionResult:
        return self.result(status="failed", **kwargs)

    def not_supported(self, **kwargs: Any) -> RuntimeActionResult:
        return self.result(status="not_supported", **kwargs)


class RuntimeActionDispatcher:
    """RuntimeAction 的路由层。

    它只负责 route、生成 receipt event、复核 evidence。它不执行业务逻辑、不写
    checkpoint、不读 .env、不访问网络、不推进 Runtime state。
    """

    def __init__(
        self,
        registry: ActionHandlerRegistry | None = None,
        *,
        observer: RuntimeActionModuleObserver | None = None,
    ) -> None:
        self._registry = registry or ActionHandlerRegistry()
        self._observer = observer or RuntimeActionModuleObserver()
        self._action_log: list[RuntimeActionEvent] = []

    @property
    def action_log(self) -> tuple[RuntimeActionEvent, ...]:
        return tuple(self._action_log)

    def route(self, request: RuntimeActionRequest) -> RuntimeActionResult:
        started = monotonic()
        action_id = new_action_id()
        route_id = f"route:{uuid4().hex}"
        handler = self._registry.get(request.action_type)
        handler_name = type(handler).__name__ if handler is not None else ""
        handler_identity = _handler_identity(handler) if handler is not None else ""
        RuntimeActionModuleObserver._issue_dispatch_route(
            route_id=route_id,
            action_id=action_id,
            action_type=action_type_value(request.action_type),
            handler_name=handler_name,
            handler_identity=handler_identity,
        )
        context = RuntimeActionContext(
            action_id=action_id,
            action_type=request.action_type,
            route_id=route_id,
            handler_name=handler_name,
            handler_identity=handler_identity,
            parent_trace_id=request.parent_trace_id,
            observer=self._observer,
        )
        if handler is None:
            result = self._unsupported_result(request, context)
        else:
            try:
                result = handler.handle(request, context)
            except Exception as exc:  # noqa: BLE001 - action boundary must fail closed
                result = context.failed(
                    handler_name=type(handler).__name__,
                    target_module="unknown",
                    payload={"error": type(exc).__name__},
                    observed_call=None,
                    evidence_extra={"error_type": type(exc).__name__},
                    error_safe_preview=type(exc).__name__,
                )

        latency_ms = max(0, int((monotonic() - started) * 1000))
        final_result = self._mark_returned_to_parent(request, context, result, latency_ms=latency_ms)
        self._action_log.append(RuntimeActionEvent(
            event_id=new_event_id(),
            action_id=final_result.action_id,
            action_type=final_result.action_type,
            source=request.source,
            status=final_result.status,
            evidence=final_result.evidence,
            parent_trace_id=request.parent_trace_id,
        ))
        return final_result

    def _unsupported_result(
        self,
        request: RuntimeActionRequest,
        context: RuntimeActionContext,
    ) -> RuntimeActionResult:
        evidence = {
            "action_id": context.action_id,
            "action_type": action_type_value(request.action_type),
            "dispatcher_route_id": context.route_id,
            "dispatcher_result_id": "",
            "dispatcher_result_issued": False,
            "dispatcher_routed": True,
            "target_handler_invoked": False,
            "handler_name": "",
            "target_module": "",
            "target_catalog_id": "",
            "target_handle": "",
            "target_descriptor_id": "",
            "invocation_adapter_id": "",
            "implementation_id": "",
            "callable_identity": "",
            "target_catalog_allowed": False,
            "target_identity_valid": False,
            "module_invoked": False,
            "invocation_proof": None,
            "target_module_proof": None,
            "result_returned_to_parent_runtime": False,
            "parent_adjudicated": None,
        }
        evidence["evidence_level"] = classify_evidence_level(evidence)
        return RuntimeActionResult(
            action_type=request.action_type,
            action_id=context.action_id,
            status="not_supported",
            payload={"reason": "no handler registered"},
            evidence=evidence,
            error_safe_preview="action not supported",
        )

    def _mark_returned_to_parent(
        self,
        request: RuntimeActionRequest,
        context: RuntimeActionContext,
        result: RuntimeActionResult,
        *,
        latency_ms: int,
    ) -> RuntimeActionResult:
        if result.action_id != context.action_id or result.evidence.get("action_id") != context.action_id:
            result = context.failed(
                handler_name=context.handler_name or "unknown",
                target_module=str(result.evidence.get("target_module") or "unknown"),
                payload={"error": "handler returned mismatched action_id"},
                observed_call=None,
                evidence_extra={
                    "error_type": "RuntimeActionEvidenceMismatch",
                    "runtime_e2e_disqualified_reason": "handler returned mismatched action_id",
                },
                error_safe_preview="handler returned mismatched action_id",
            )
        elif result.status != "not_supported" and not context.issued_result(result):
            # 中文学习注释：manual RuntimeActionResult 可能携带一个真实 observer
            # proof，但它没有经过 context.result() 发行；没有 dispatcher-owned
            # result provenance 就不能成为 runtime_e2e。
            result = context.failed(
                handler_name=context.handler_name or "unknown",
                target_module=str(result.evidence.get("target_module") or "unknown"),
                payload={"error": "handler returned unissued RuntimeActionResult"},
                observed_call=None,
                evidence_extra={
                    "error_type": "RuntimeActionUnissuedResult",
                    "runtime_e2e_disqualified_reason": "handler returned unissued RuntimeActionResult",
                },
                error_safe_preview="handler returned unissued RuntimeActionResult",
            )
        evidence = dict(result.evidence)
        evidence["action_id"] = context.action_id
        evidence["action_type"] = action_type_value(request.action_type)
        evidence["dispatcher_route_id"] = context.route_id
        evidence["dispatcher_routed"] = True
        evidence["result_returned_to_parent_runtime"] = True
        evidence["evidence_level"] = classify_evidence_level(evidence)
        return RuntimeActionResult(
            action_type=result.action_type,
            action_id=context.action_id,
            status=result.status,
            payload=dict(result.payload),
            evidence=evidence,
            error_safe_preview=result.error_safe_preview,
            latency_ms=latency_ms,
            timestamp=result.timestamp,
        )


def _handler_identity(handler: ActionHandler) -> str:
    handler_type = type(handler)
    return f"{handler_type.__module__}.{handler_type.__qualname__}"

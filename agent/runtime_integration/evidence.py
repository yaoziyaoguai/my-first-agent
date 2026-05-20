"""RuntimeAction evidence helpers.

中文学习边界：
RuntimeActionEvent 只是“收据”，只能证明 dispatcher.route() 发生过。
runtime_e2e 需要独立观测的 target_module_proof；这个模块集中做判定，避免
handler、dogfood report 或 capability matrix 各自发明通过条件。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, ClassVar, Mapping
from uuid import uuid4


RUNTIME_E2E = "runtime_e2e"
SUBSYSTEM_INTEGRATION = "subsystem_integration"
DETERMINISTIC_BASELINE = "deterministic_baseline"
SIMULATED = "simulated"
NOT_COVERED = "not_covered"


@dataclass(frozen=True, slots=True)
class ObservedModuleCall:
    """由 dispatcher/context 持有的 observer 生成的目标模块调用证据。"""

    value: Any
    invocation_proof: dict[str, Any]
    target_module_proof: dict[str, Any]


class RuntimeActionModuleObserver:
    """独立观测目标模块调用的最小 observer。

    Handler 不能直接 mint target_module_proof；它只能把目标 callable 交给这个
    observer 包裹执行。observer_identity 与 handler_name 分离，是为了让
    capability matrix 能识别 handler self-asserted proof。
    """

    observer_identity = "RuntimeActionModuleObserver"
    _route_registry: ClassVar[dict[str, dict[str, Any]]] = {}
    _result_registry: ClassVar[dict[str, dict[str, Any]]] = {}
    _proof_registry: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    def register_dispatch_route(
        cls,
        *,
        route_id: str,
        action_id: str,
        action_type: str,
        handler_name: str,
    ) -> None:
        cls._route_registry[route_id] = {
            "action_id": action_id,
            "action_type": action_type,
            "handler_name": handler_name,
        }

    @classmethod
    def register_dispatch_result(
        cls,
        *,
        route_id: str,
        result_id: str,
        action_id: str,
        action_type: str,
        handler_name: str,
    ) -> None:
        cls._result_registry[result_id] = {
            "route_id": route_id,
            "action_id": action_id,
            "action_type": action_type,
            "handler_name": handler_name,
        }

    def observe(
        self,
        *,
        route_id: str,
        action_id: str,
        action_type: str,
        handler_name: str,
        target_module: str,
        function_called: str,
        call_signature: str,
        call: Callable[[], Any],
    ) -> ObservedModuleCall:
        call_id = f"call:{uuid4().hex}"
        value = call()
        observed_at = _now_iso()
        invocation_proof = {
            "call_id": call_id,
            "function_called": function_called,
            "call_signature": call_signature,
            "observed_at": observed_at,
            "observation_method": "module_spy",
        }
        proof_id = f"proof:{uuid4().hex}"
        target_module_proof = {
            "proof_id": proof_id,
            "observation_source": "module_spy",
            "observer_identity": self.observer_identity,
            "observation_independent": True,
            "linked_route_id": route_id,
            "linked_action_id": action_id,
            "linked_action_type": action_type,
            "linked_handler_name": handler_name,
            "linked_target_module": target_module,
            "linked_call_id": call_id,
        }
        # 中文学习注释：observer-owned proof 只能证明“目标 callable 被看见”。
        # runtime_e2e 还必须证明这次调用属于 dispatcher 管理的同一条 route；
        # 因此 proof 同时绑定 route/action_type/handler/target/call，禁止跨 route
        # 或跨 handler 复用一个真实 proof 来伪造端到端。
        self._proof_registry[proof_id] = {
            "route_id": route_id,
            "action_id": action_id,
            "action_type": action_type,
            "handler_name": handler_name,
            "target_module": target_module,
            "call_id": call_id,
            "observer_identity": self.observer_identity,
            "observation_source": "module_spy",
            "observation_independent": True,
        }
        return ObservedModuleCall(
            value=value,
            invocation_proof=invocation_proof,
            target_module_proof=target_module_proof,
        )

    @classmethod
    def is_registered_proof(
        cls,
        *,
        proof: Mapping[str, Any],
        invocation_proof: Mapping[str, Any],
        route_id: str,
        action_id: str,
        action_type: str,
        handler_name: str,
        target_module: str,
        result_id: str,
    ) -> bool:
        proof_id = str(proof.get("proof_id") or "")
        registered = cls._proof_registry.get(proof_id)
        if not registered:
            return False
        route = cls._route_registry.get(route_id)
        if not route:
            return False
        result = cls._result_registry.get(result_id)
        if not result:
            return False
        call_id = invocation_proof.get("call_id")
        return (
            route.get("action_id") == action_id
            and route.get("action_type") == action_type
            and route.get("handler_name") == handler_name
            and result.get("route_id") == route_id
            and result.get("action_id") == action_id
            and result.get("action_type") == action_type
            and result.get("handler_name") == handler_name
            and registered.get("route_id") == route_id
            and registered.get("action_id") == action_id
            and registered.get("action_type") == action_type
            and registered.get("handler_name") == handler_name
            and registered.get("target_module") == target_module
            and registered.get("call_id") == call_id
            and registered.get("observer_identity") == proof.get("observer_identity")
            and registered.get("observation_source") == proof.get("observation_source")
            and registered.get("observation_independent") is True
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_runtime_e2e_evidence(evidence: Mapping[str, Any]) -> bool:
    """判断 evidence 是否满足 R.6 Runtime E2E 证据链。"""

    if evidence.get("runtime_e2e_disqualified_reason"):
        return False
    action_id = evidence.get("action_id")
    action_type = str(evidence.get("action_type") or "")
    handler_name = str(evidence.get("handler_name") or "")
    route_id = str(evidence.get("dispatcher_route_id") or "")
    result_id = str(evidence.get("dispatcher_result_id") or "")
    target_module = evidence.get("target_module")
    if not action_id or not action_type or not handler_name or not route_id or not result_id or not target_module:
        return False
    if evidence.get("dispatcher_result_issued") is not True:
        return False
    required_true = (
        "dispatcher_routed",
        "target_handler_invoked",
        "module_invoked",
        "result_returned_to_parent_runtime",
    )
    if any(evidence.get(key) is not True for key in required_true):
        return False

    invocation_proof = evidence.get("invocation_proof")
    if not isinstance(invocation_proof, Mapping):
        return False
    for key in ("call_id", "function_called", "call_signature", "observed_at", "observation_method"):
        if not invocation_proof.get(key):
            return False
    if invocation_proof.get("observation_method") == "handler_self_report":
        return False

    proof = evidence.get("target_module_proof")
    if not isinstance(proof, Mapping):
        return False
    if not proof.get("proof_id"):
        return False
    if proof.get("observation_independent") is not True:
        return False
    if proof.get("linked_route_id") != route_id:
        return False
    if proof.get("linked_action_id") != action_id:
        return False
    if proof.get("linked_action_type") != action_type:
        return False
    if proof.get("linked_handler_name") != handler_name:
        return False
    if proof.get("linked_target_module") != target_module:
        return False
    if proof.get("linked_call_id") != invocation_proof.get("call_id"):
        return False
    if proof.get("observer_identity") == evidence.get("handler_name"):
        return False
    if proof.get("observation_source") == "handler_self_report":
        return False
    if not RuntimeActionModuleObserver.is_registered_proof(
        proof=proof,
        invocation_proof=invocation_proof,
        route_id=route_id,
        action_id=str(action_id),
        action_type=action_type,
        handler_name=handler_name,
        target_module=str(target_module),
        result_id=result_id,
    ):
        return False

    if action_type == "checkpoint.safe_summary" or target_module == "CheckpointSafeSummary":
        if evidence.get("checkpoint_boundary") != "turn_end_before_save_checkpoint":
            return False
        if evidence.get("no_tool_boundary_reached") is not True:
            return False
        if evidence.get("tool_after_only_trigger") is True:
            return False
    if action_type == "subagent.delegate_l0" or target_module == "SubAgentExecutor":
        return evidence.get("parent_adjudicated") is True
    return True


def classify_evidence_level(evidence: Mapping[str, Any]) -> str:
    """按证据强度诚实分类。

    direct subsystem invocation 没有 dispatcher_routed；event-only 没有 module proof。
    两者都不能升级到 runtime_e2e。
    """

    explicit = evidence.get("evidence_level")
    if is_runtime_e2e_evidence(evidence):
        return RUNTIME_E2E
    if evidence.get("dispatcher_routed") or evidence.get("target_handler_invoked") or evidence.get("module_invoked"):
        return SUBSYSTEM_INTEGRATION
    if explicit in {DETERMINISTIC_BASELINE, SIMULATED, NOT_COVERED}:
        return str(explicit)
    return NOT_COVERED

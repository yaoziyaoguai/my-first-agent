"""RuntimeAction evidence helpers.

中文学习边界：
RuntimeActionEvent 只是“收据”，只能证明 dispatcher.route() 发生过。
runtime_e2e 需要独立观测的 target_module_proof；这个模块集中做判定，避免
handler、dogfood report 或 capability matrix 各自发明通过条件。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
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

    def observe(
        self,
        *,
        action_id: str,
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
        target_module_proof = {
            "proof_id": f"proof:{uuid4().hex}",
            "observation_source": "module_spy",
            "observer_identity": self.observer_identity,
            "observation_independent": True,
            "linked_action_id": action_id,
            "linked_target_module": target_module,
        }
        return ObservedModuleCall(
            value=value,
            invocation_proof=invocation_proof,
            target_module_proof=target_module_proof,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_runtime_e2e_evidence(evidence: Mapping[str, Any]) -> bool:
    """判断 evidence 是否满足 R.6 Runtime E2E 证据链。"""

    if evidence.get("runtime_e2e_disqualified_reason"):
        return False
    action_id = evidence.get("action_id")
    target_module = evidence.get("target_module")
    if not action_id or not target_module:
        return False
    required_true = (
        "dispatcher_routed",
        "target_handler_invoked",
        "module_invoked",
        "result_returned_to_parent_runtime",
    )
    if any(evidence.get(key) is not True for key in required_true):
        return False

    proof = evidence.get("target_module_proof")
    if not isinstance(proof, Mapping):
        return False
    if not proof.get("proof_id"):
        return False
    if proof.get("observation_independent") is not True:
        return False
    if proof.get("linked_action_id") != action_id:
        return False
    if proof.get("linked_target_module") != target_module:
        return False
    if proof.get("observer_identity") == evidence.get("handler_name"):
        return False
    if proof.get("observation_source") == "handler_self_report":
        return False

    invocation_proof = evidence.get("invocation_proof")
    if not isinstance(invocation_proof, Mapping):
        return False
    for key in ("call_id", "function_called", "call_signature", "observed_at", "observation_method"):
        if not invocation_proof.get(key):
            return False
    if invocation_proof.get("observation_method") == "handler_self_report":
        return False

    action_type = str(evidence.get("action_type") or "")
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

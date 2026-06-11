"""RuntimeAction evidence helpers.

中文学习边界：
RuntimeActionEvent 只是“收据”，只能证明 dispatcher.route() 发生过。
runtime_e2e 需要独立观测的 target_module_proof；这个模块集中做判定，避免
handler、dogfood report 或 capability matrix 各自发明通过条件。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar
from uuid import uuid4

RUNTIME_E2E = "runtime_e2e"
REAL_CORE_LOOP_RUNTIME_E2E = "real_core_loop_runtime_e2e"
HARNESS_RUNTIME_E2E = "harness_runtime_e2e"
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

    Handler 不能直接 mint trusted target_module_proof；handler-supplied callable
    兼容路径只能生成非可信 proof。runtime_e2e 的 trusted target proof 必须来自
    catalog-owned descriptor adapter invocation。observer_identity 与 handler_name
    分离，是为了让 capability matrix 能识别 handler self-asserted proof。

    中文学习边界：public registry method 只保留给旧测试和降级路径使用，不能
    成为 runtime_e2e 信任根。真正可信的 provenance 必须由 dispatcher 调用
    `_issue_*` 内部入口发行，并且 result registry 要绑定 proof/call/target。
    target identity 同理：public observe() 只能生成非可信 target proof；只有
    dispatcher context 通过 target catalog 执行 descriptor adapter 才能进入
    runtime_e2e。
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
        """登记非可信 route。

        这个 public API 不能 mint dispatcher-owned provenance；它存在是为了让
        手工/历史测试能表达“有 registry 形状但不是 dispatcher 发行”的负例。
        """

        cls._route_registry[route_id] = {
            "action_id": action_id,
            "action_type": action_type,
            "handler_name": handler_name,
            "handler_identity": "",
            "dispatcher_owned": False,
        }

    @classmethod
    def _issue_dispatch_route(
        cls,
        *,
        route_id: str,
        action_id: str,
        action_type: str,
        handler_name: str,
        handler_identity: str,
    ) -> None:
        """由 RuntimeActionDispatcher 内部发行可信 route provenance。"""

        cls._route_registry[route_id] = {
            "action_id": action_id,
            "action_type": action_type,
            "handler_name": handler_name,
            "handler_identity": handler_identity,
            "dispatcher_owned": True,
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
        """登记非可信 result。

        Public caller 不能提供 dispatcher-owned receipt；classifier 会拒绝这类
        result，即便字段与 proof 看起来完全匹配。
        """

        cls._result_registry[result_id] = {
            "route_id": route_id,
            "action_id": action_id,
            "action_type": action_type,
            "handler_name": handler_name,
            "handler_identity": "",
            "target_module": None,
            "proof_id": None,
            "call_id": None,
            "target_catalog_id": None,
            "target_handle": None,
            "target_descriptor_id": None,
            "invocation_adapter_id": None,
            "implementation_id": None,
            "callable_identity": None,
            "target_catalog_allowed": False,
            "target_identity_valid": False,
            "dispatcher_owned": False,
        }

    @classmethod
    def _issue_dispatch_result(
        cls,
        *,
        route_id: str,
        result_id: str,
        action_id: str,
        action_type: str,
        handler_name: str,
        target_module: str,
        proof_id: str | None,
        call_id: str | None,
        target_catalog_id: str | None,
        target_handle: str | None,
        target_descriptor_id: str | None,
        invocation_adapter_id: str | None,
        implementation_id: str | None,
        callable_identity: str | None,
        target_catalog_allowed: bool,
        target_identity_valid: bool,
    ) -> None:
        """由 context.result() 发行可信 result provenance。

        result_id 不是单独可信的票据；它必须绑定本次 result 使用的 proof/call/target。
        这样同 route 内 result A 的 proof 不能移植到 result B。
        """

        cls._result_registry[result_id] = {
            "route_id": route_id,
            "action_id": action_id,
            "action_type": action_type,
            "handler_name": handler_name,
            "handler_identity": cls._route_registry.get(route_id, {}).get("handler_identity", ""),
            "target_module": target_module,
            "proof_id": proof_id,
            "call_id": call_id,
            "target_catalog_id": target_catalog_id,
            "target_handle": target_handle,
            "target_descriptor_id": target_descriptor_id,
            "invocation_adapter_id": invocation_adapter_id,
            "implementation_id": implementation_id,
            "callable_identity": callable_identity,
            "target_catalog_allowed": target_catalog_allowed,
            "target_identity_valid": target_identity_valid,
            "dispatcher_owned": True,
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
        """Public observer compatibility surface.

        直接调用 observe() 可以获得“调用被观测”的 proof，但不能获得 trusted
        target handle；classifier 会把它降级为非 runtime_e2e。
        """

        return self._observe(
            route_id=route_id,
            action_id=action_id,
            action_type=action_type,
            handler_name=handler_name,
            handler_identity="",
            target_module=target_module,
            target_descriptor=None,
            descriptor_invocation_approved=False,
            function_called=function_called,
            call_signature=call_signature,
            call=call,
            callable_identity=None,
        )

    def _observe_handler_supplied_call(
        self,
        *,
        route_id: str,
        action_id: str,
        action_type: str,
        handler_name: str,
        handler_identity: str,
        target_module: str,
        function_called: str,
        call_signature: str,
        call: Callable[[], Any],
    ) -> ObservedModuleCall:
        """兼容 handler-supplied callable path，永远不发行 trusted target proof。"""

        return self._observe(
            route_id=route_id,
            action_id=action_id,
            action_type=action_type,
            handler_name=handler_name,
            handler_identity=handler_identity,
            target_module=target_module,
            target_descriptor=None,
            descriptor_invocation_approved=False,
            function_called=function_called,
            call_signature=call_signature,
            call=call,
            callable_identity=None,
        )

    def _observe_registered_invocation(
        self,
        *,
        route_id: str,
        action_id: str,
        action_type: str,
        handler_name: str,
        handler_identity: str,
        target_descriptor: RuntimeActionTargetDescriptor,
        payload: Mapping[str, Any],
    ) -> ObservedModuleCall:
        """dispatcher/catalog 专用 trusted invocation path。

        中文学习边界：这里执行的是 descriptor.adapter，而不是 handler 传入的
        callable。proof 中的 callable/implementation/adapter provenance 来自
        catalog descriptor；handler 只能给 adapter 传业务 payload。
        """

        adapter_identity = _callable_identity(target_descriptor.adapter)

        def call() -> Any:
            return target_descriptor.invoke(payload)

        return self._observe(
            route_id=route_id,
            action_id=action_id,
            action_type=action_type,
            handler_name=handler_name,
            handler_identity=handler_identity,
            target_module=target_descriptor.target_module,
            target_descriptor=target_descriptor,
            descriptor_invocation_approved=adapter_identity == target_descriptor.callable_identity,
            function_called=target_descriptor.function_called,
            call_signature=target_descriptor.call_signature,
            call=call,
            callable_identity=adapter_identity,
        )

    def _observe(
        self,
        *,
        route_id: str,
        action_id: str,
        action_type: str,
        handler_name: str,
        handler_identity: str,
        target_module: str,
        target_descriptor: RuntimeActionTargetDescriptor | None,
        descriptor_invocation_approved: bool,
        function_called: str,
        call_signature: str,
        call: Callable[[], Any],
        callable_identity: str | None,
    ) -> ObservedModuleCall:
        call_id = f"call:{uuid4().hex}"
        proof_callable_identity = callable_identity if descriptor_invocation_approved else None
        target_identity_valid = (
            target_descriptor is not None
            and descriptor_invocation_approved
            and target_descriptor.callable_identity == proof_callable_identity
        )
        def _trusted(attr: str) -> str | None:
            return getattr(target_descriptor, attr) if target_identity_valid else None

        trusted_target_catalog_id = _trusted("target_catalog_id")
        trusted_target_handle = _trusted("target_handle")
        trusted_target_descriptor_id = _trusted("target_descriptor_id")
        trusted_invocation_adapter_id = _trusted("invocation_adapter_id")
        trusted_implementation_id = _trusted("implementation_id")
        target_catalog_allowed = target_identity_valid
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
            "target_catalog_id": trusted_target_catalog_id,
            "linked_target_handle": trusted_target_handle,
            "target_descriptor_id": trusted_target_descriptor_id,
            "invocation_adapter_id": trusted_invocation_adapter_id,
            "implementation_id": trusted_implementation_id,
            "callable_identity": proof_callable_identity,
            "target_catalog_allowed": target_catalog_allowed,
            "target_identity_valid": target_identity_valid,
            "descriptor_invocation_approved": target_identity_valid,
        }
        # 中文学习注释：observer-owned proof 只能证明“目标 callable 被看见”。
        # runtime_e2e 还必须证明这次调用属于 dispatcher 管理的同一条 route；
        # 因此 proof 同时绑定 route/action_type/handler/target/call，禁止跨 route
        # 或跨 handler 复用一个真实 proof 来伪造端到端。target_module 仍只是
        # 字符串标签；只有 catalog descriptor 自己执行 adapter 时，
        # target_catalog_allowed 才能为 true。
        route = self._route_registry.get(route_id) or {}
        self._proof_registry[proof_id] = {
            "route_id": route_id,
            "action_id": action_id,
            "action_type": action_type,
            "handler_name": handler_name,
            "handler_identity": handler_identity,
            "target_module": target_module,
            "call_id": call_id,
            "observer_identity": self.observer_identity,
            "observation_source": "module_spy",
            "observation_independent": True,
            "target_catalog_id": trusted_target_catalog_id,
            "target_handle": trusted_target_handle,
            "target_descriptor_id": trusted_target_descriptor_id,
            "invocation_adapter_id": trusted_invocation_adapter_id,
            "implementation_id": trusted_implementation_id,
            "callable_identity": proof_callable_identity,
            "target_catalog_allowed": target_catalog_allowed,
            "target_identity_valid": target_identity_valid,
            "descriptor_invocation_approved": target_identity_valid,
            "dispatcher_owned": route.get("dispatcher_owned") is True,
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
        target_catalog_id: str,
        target_handle: str,
        target_descriptor_id: str,
        invocation_adapter_id: str,
        implementation_id: str,
        callable_identity: str,
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
        proof_id = proof.get("proof_id")
        handler_identity = str(route.get("handler_identity") or "")
        return (
            route.get("dispatcher_owned") is True
            and result.get("dispatcher_owned") is True
            and registered.get("dispatcher_owned") is True
            and result.get("target_catalog_allowed") is True
            and registered.get("target_catalog_allowed") is True
            and result.get("target_identity_valid") is True
            and registered.get("target_identity_valid") is True
            and registered.get("descriptor_invocation_approved") is True
            and RuntimeActionTargetCatalog.is_allowed_descriptor(
                action_type=action_type,
                handler_name=handler_name,
                handler_identity=handler_identity,
                target_module=target_module,
                target_catalog_id=target_catalog_id,
                target_handle=target_handle,
                target_descriptor_id=target_descriptor_id,
                invocation_adapter_id=invocation_adapter_id,
                implementation_id=implementation_id,
                callable_identity=callable_identity,
            )
            and route.get("action_id") == action_id
            and route.get("action_type") == action_type
            and route.get("handler_name") == handler_name
            and result.get("route_id") == route_id
            and result.get("action_id") == action_id
            and result.get("action_type") == action_type
            and result.get("handler_name") == handler_name
            and result.get("handler_identity") == handler_identity
            and result.get("target_module") == target_module
            and result.get("proof_id") == proof_id
            and result.get("call_id") == call_id
            and result.get("target_catalog_id") == target_catalog_id
            and result.get("target_handle") == target_handle
            and result.get("target_descriptor_id") == target_descriptor_id
            and result.get("invocation_adapter_id") == invocation_adapter_id
            and result.get("implementation_id") == implementation_id
            and result.get("callable_identity") == callable_identity
            and registered.get("route_id") == route_id
            and registered.get("action_id") == action_id
            and registered.get("action_type") == action_type
            and registered.get("handler_name") == handler_name
            and registered.get("handler_identity") == handler_identity
            and registered.get("target_module") == target_module
            and registered.get("call_id") == call_id
            and registered.get("target_catalog_id") == target_catalog_id
            and registered.get("target_handle") == target_handle
            and registered.get("target_descriptor_id") == target_descriptor_id
            and registered.get("invocation_adapter_id") == invocation_adapter_id
            and registered.get("implementation_id") == implementation_id
            and registered.get("callable_identity") == callable_identity
            and registered.get("observer_identity") == proof.get("observer_identity")
            and registered.get("observation_source") == proof.get("observation_source")
            and registered.get("observation_independent") is True
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_runtime_e2e_evidence(evidence: Mapping[str, Any]) -> bool:
    """判断 evidence 是否满足 R.6 Runtime E2E 证据链。

    中文学习注释 —— rejection/failure ≠ runtime_e2e disqualification：
    - is_runtime_e2e_evidence 只检查 evidence chain 的结构完整性，不检查 handler
      的 disposition（failed/rejected/success 均不改变证据链结构）。
    - runtime_e2e_disqualified_reason 由 dispatcher 层设置，用于标记真正的
      dispatch 链级错误（handler returned mismatched action_id、unissued result）。
    - handler 内部的 validation failure 使用 failure_reason（不设置
      runtime_e2e_disqualified_reason），避免误伤证据链分类。
    - classify_evidence_level() 会进一步区分 real_core_loop_runtime_e2e
      （需 dispatcher_origin=="runtime_loop" + runtime_loop_invoked）和
      harness_runtime_e2e（直接 dispatcher.route() 调用，无 runtime loop provenance）。
    """

    if evidence.get("runtime_e2e_disqualified_reason"):
        return False
    action_id = evidence.get("action_id")
    action_type = str(evidence.get("action_type") or "")
    handler_name = str(evidence.get("handler_name") or "")
    route_id = str(evidence.get("dispatcher_route_id") or "")
    result_id = str(evidence.get("dispatcher_result_id") or "")
    target_module = evidence.get("target_module")
    target_catalog_id = str(evidence.get("target_catalog_id") or "")
    target_handle = str(evidence.get("target_handle") or "")
    target_descriptor_id = str(evidence.get("target_descriptor_id") or "")
    invocation_adapter_id = str(evidence.get("invocation_adapter_id") or "")
    implementation_id = str(evidence.get("implementation_id") or "")
    callable_identity = str(evidence.get("callable_identity") or "")
    if (
        not action_id or not action_type or not handler_name
        or not route_id or not result_id or not target_module
    ):
        return False
    if evidence.get("dispatcher_result_issued") is not True:
        return False
    if (
        evidence.get("target_catalog_allowed") is not True
        or not target_catalog_id or not target_handle
    ):
        return False
    if evidence.get("target_identity_valid") is not True:
        return False
    if (
        not target_descriptor_id or not invocation_adapter_id
        or not implementation_id or not callable_identity
    ):
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
    _proof_keys = (
        "call_id", "function_called", "call_signature", "observed_at", "observation_method"
    )
    for key in _proof_keys:
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
    if proof.get("linked_dispatcher_result_id") != result_id:
        return False
    if proof.get("target_catalog_allowed") is not True:
        return False
    if proof.get("target_identity_valid") is not True:
        return False
    if proof.get("descriptor_invocation_approved") is not True:
        return False
    if proof.get("target_catalog_id") != target_catalog_id:
        return False
    if proof.get("linked_target_handle") != target_handle:
        return False
    if proof.get("target_descriptor_id") != target_descriptor_id:
        return False
    if proof.get("invocation_adapter_id") != invocation_adapter_id:
        return False
    if proof.get("implementation_id") != implementation_id:
        return False
    if proof.get("callable_identity") != callable_identity:
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
        target_catalog_id=target_catalog_id,
        target_handle=target_handle,
        target_descriptor_id=target_descriptor_id,
        invocation_adapter_id=invocation_adapter_id,
        implementation_id=implementation_id,
        callable_identity=callable_identity,
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

    remediation 分类边界：
    - real_core_loop_runtime_e2e：必须有 dispatcher-owned runtime-loop provenance
    - harness_runtime_e2e：dogfood/harness 直接调用 dispatcher，即使 payload 伪造
      core_loop_invoked，也只能停在 harness
    - payload 是 action 输入，不是可信 runtime provenance
    """

    explicit = evidence.get("evidence_level")
    if is_runtime_e2e_evidence(evidence):
        if (
            evidence.get("dispatcher_origin") == "runtime_loop"
            and evidence.get("runtime_loop_invoked") is True
            and evidence.get("runtime_action_source") == "core_loop"
            and evidence.get("core_entrypoint") == "core.chat"
            and bool(evidence.get("runtime_hook_name"))
        ):
            return REAL_CORE_LOOP_RUNTIME_E2E
        return HARNESS_RUNTIME_E2E
    if (
        evidence.get("dispatcher_routed")
        or evidence.get("target_handler_invoked")
        or evidence.get("module_invoked")
    ):
        return SUBSYSTEM_INTEGRATION
    if explicit in {DETERMINISTIC_BASELINE, SIMULATED, NOT_COVERED}:
        return str(explicit)
    return NOT_COVERED


# business disposition: 证明此次 action 确实产生了用户可见的业务效果
_BUSINESS_DISPOSITIONS = frozenset({
    "allowed",            # tool.gate: gate 通过
    "recalled",           # memory.recall: 召回成功
    "retain",             # memory.propose: 写入成功
    "proposed",           # memory.turn_end_proposal: proposal 已生成
    "not_retained",       # memory.propose: 用户拒绝 (有业务语义)
    "consolidated",       # memory.consolidate: 已整合
    "forgotten",          # memory.forget: 已删除
    "not_found",          # memory.forget: 未找到记录（有业务语义）
    "injected",           # tool.result: 结果注入到模型上下文
    "truncated",          # tool.result: 截断但仍注入
    "delegated",          # subagent.delegate_l0: 真实委托
    "executed",           # tool.invoke: 执行成功
})
"""业务 disposition: handler 明确报告产生了用户可见的业务效果。

不含 noop/no_action/rejected/insufficient_evidence/no_candidates/no_memory/
not_supported/failed 等无效或仅路由探测的 disposition。
"""


def is_business_capability_evidence(evidence: Mapping[str, Any]) -> bool:
    """判断 evidence 是否代表"业务能力完成"（不只是 routing evidence）。

    红队补审规则：``real_core_loop_runtime_e2e`` 只证明 action 通过了
    route_from_runtime_loop() 主路径，不证明 action 达成了业务效果。
    probe 返回 noop 时仍然有 routing evidence，但不构成业务能力证明。

    返回 True 需要同时满足：
    1. 证据等级为 ``REAL_CORE_LOOP_RUNTIME_E2E``（主路径 routing）
    2. disposition 在 _BUSINESS_DISPOSITIONS 中（有业务效果）

    Args:
        evidence: 来自 RuntimeActionEvent.evidence 的证据字典
    """
    level = classify_evidence_level(evidence)
    if level != REAL_CORE_LOOP_RUNTIME_E2E:
        return False
    disposition = str(evidence.get("disposition", ""))
    return disposition in _BUSINESS_DISPOSITIONS


# ---------------------------------------------------------------------------
# Back-compat re-export.
#
# ``RuntimeActionTargetCatalog`` and ``RuntimeActionTargetDescriptor`` moved
# to ``agent.runtime_integration.target_catalog``. They are re-exported here
# so legacy import sites and tests keep working.
# -----------------------------------...-----------------------------------------
from agent.runtime_integration.target_catalog import (  # noqa: E402, F401
    RuntimeActionTargetCatalog,
    RuntimeActionTargetDescriptor,
    _callable_identity,
    _checkpoint_safe_summary_adapter,
)

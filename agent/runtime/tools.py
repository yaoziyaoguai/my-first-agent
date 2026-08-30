"""受治理的唯一 Tool Runtime。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from agent.process.contracts import (
    ProcessDraftOutcome,
    ProcessExecutionDraftV1,
    ResourceProfile,
    ResourceProfileV1,
)
from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalRequired,
    ArtifactConfirmationRequirementV1,
    BackgroundActionAuthorityV1,
    BackgroundClaimCheckV1,
    BackgroundClaimVerdictV1,
    BackgroundExecutionAuthorityV1,
    BackgroundSandboxReceiptV1,
    BrowserActionCandidateV1,
    BrowserAuthorityLeaseV1,
    BrowserTakeoverRequestV1,
    EgressClass,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    ExecutionIntent,
    JSONValue,
    KnownExecutedError,
    KnownNotExecuted,
    PolicyDecision,
    ProcessAuthorityCandidateV1,
    ProcessAuthorityLeaseV1,
    ProcessOutcome,
    ProcessReceiptV1,
    SandboxAuthorityCandidateV1,
    SandboxAuthorityLeaseV1,
    SandboxReceiptV1,
    SideEffectClass,
    SourceAuthorityBinding,
    ToolCall,
    ToolDefinition,
    ToolExecutionOutput,
    ToolExposure,
    ToolPreparation,
    ToolPrepareContext,
    ToolResult,
    ToolSpec,
    canonical_json_digest,
)
from agent.runtime.ports import BackgroundClaimVerifier
from agent.runtime.tool_governance import (
    BrowserGovernance,
    CitationGovernance,
    SourceGovernance,
)
from agent.sandbox.contracts import (
    SandboxDraftOutcome,
    SandboxExecutionDraftV1,
    StructuredReadbackOutcome,
    StructuredSandboxProcessDraftV1,
)


def _default_utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_zoned_rfc3339(value: str) -> datetime | None:
    """严格解析带时区 RFC3339；naive/malformed → None（调用方 fail closed）。"""

    if not isinstance(value, str):
        return None
    # fromisoformat 接受 space 分隔等非 RFC3339 宽松形式；authority 时间戳只信任
    # 本代码库铸造的 ``T`` 分隔形式，其余一律 fail closed。
    if len(value) < 20 or value[10] != "T":
        return None
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed

ToolCallable = Callable[..., object]
BindingPreparer = Callable[[dict[str, JSONValue]], dict[str, JSONValue]]
AuthorityBindingPreparer = Callable[
    [dict[str, JSONValue], SourceAuthorityBinding], dict[str, JSONValue]
]


class IntentConflictError(RuntimeError):
    """执行意图与已经准备/持久化的合同不一致。"""


class ToolPolicy(Protocol):
    identity: str

    def evaluate(
        self,
        spec: ToolSpec,
        arguments: dict[str, JSONValue],
        binding: dict[str, JSONValue],
    ) -> PolicyDecision:
        """只基于结构化元数据作出治理决定。"""


class DefaultToolPolicy:
    identity = "kernel-default-tool-policy-v1"

    def evaluate(
        self,
        spec: ToolSpec,
        arguments: dict[str, JSONValue],
        binding: dict[str, JSONValue],
    ) -> PolicyDecision:
        del arguments, binding
        if spec.safety_policy.get("enabled") is False:
            return PolicyDecision.DENY
        if spec.approval_policy is ApprovalPolicy.ALWAYS:
            return PolicyDecision.REQUIRE_APPROVAL
        return PolicyDecision.ALLOW


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    spec: ToolSpec
    func: ToolCallable
    prepare_binding: BindingPreparer | None = None
    prepare_authority_binding: AuthorityBindingPreparer | None = None
    policy: ToolPolicy | None = None
    exposure: ToolExposure = ToolExposure.MODEL

    def __post_init__(self) -> None:
        if not isinstance(self.exposure, ToolExposure):
            raise TypeError("registered tool exposure must be closed")


class KernelToolRuntime:
    def __init__(
        self,
        registrations: tuple[RegisteredTool, ...],
        *,
        policy: ToolPolicy | None = None,
        clock: Callable[[], str] | None = None,
        sandbox_receipt_book=None,
        background_claim_verifier: BackgroundClaimVerifier | None = None,
    ) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for registration in registrations:
            if registration.spec.name in self._tools:
                raise ValueError(f"duplicate tool registration: {registration.spec.name}")
            self._tools[registration.spec.name] = registration
        self._default_policy = policy or DefaultToolPolicy()
        self._invoked_keys: set[str] = set()
        self._clock = clock or _default_utc_now
        # 017：Runtime 铸造的 sandbox 执行 receipt 记录进 composition 注入的
        # session book——capture 的 producing receipts 只能源自这里（design
        # receipt lineage seam 的 Runtime 侧）。
        self._sandbox_receipt_book = sandbox_receipt_book
        self._background_claim_verifier = background_claim_verifier
        # raw capability 从不进入 ExecutionIntent；prepare→invoke 的同进程短窗
        # 只按完整 intent digest 暂存，restart 后不存在就 fail closed。
        self._background_prepared_authorities: dict[
            str, BackgroundExecutionAuthorityV1
        ] = {}
        # capability 治理知识归内部 governance 模块;本类只消费裁决并保持
        # 唯一外部接口与最终权限/effect gate。
        self._citation_governance = CitationGovernance()
        self._source_governance = SourceGovernance()
        self._browser_governance = BrowserGovernance()

    def _policy_for(self, registration: RegisteredTool) -> ToolPolicy:
        # 每个 registration 可绑定自己的 policy identity；未绑定则回退到 runtime 默认策略。
        # 不按工具名路由。
        return registration.policy or self._default_policy

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(
            registration.spec.definition()
            for registration in self._tools.values()
            if registration.exposure is ToolExposure.MODEL
        )

    def prepare(
        self,
        call: ToolCall,
        context: ToolPrepareContext,
        approval: ApprovalGrant | None = None,
    ) -> ToolPreparation:
        registration = self._tools.get(call.name)
        if registration is None:
            return self._error(call.tool_call_id, "unknown_tool", "Unknown tool requested.")
        expected_exposure = ToolExposure(context.invocation_origin.value)
        if registration.exposure is not expected_exposure:
            return self._error(
                call.tool_call_id,
                "tool_exposure_mismatch",
                "Tool is not callable from this invocation origin.",
            )

        if context.goal_correction_pending:
            return self._error(
                call.tool_call_id,
                "goal_correction_required",
                (
                    "The user's latest Goal correction must be accepted as a "
                    "goal_delta_proposal before any product tool can run. No tool effect or "
                    "observation was performed."
                ),
            )

        arguments, validation_error = _validate_arguments(
            call.arguments,
            registration.spec.input_schema,
        )
        if validation_error is not None:
            return self._error(call.tool_call_id, "invalid_arguments", validation_error)

        if (
            context.public_web_requirement_pending
            and registration.spec.side_effect is not SideEffectClass.READ_ONLY
        ):
            return self._error(
                call.tool_call_id,
                "public_web_source_required",
                (
                    "The active Goal requires an approved public Web source receipt before "
                    "any write or external process effect. Use the advertised web_search "
                    "tool first; do not substitute workspace search or completion prose."
                ),
            )

        citation_ruling = self._citation_governance.assess_intent(
            tool_name=call.name,
            side_effect=registration.spec.side_effect,
            safety_policy=registration.spec.safety_policy,
            arguments=arguments,
            context=context,
        )
        if citation_ruling.rejection is not None:
            return self._error(
                call.tool_call_id,
                citation_ruling.rejection.code,
                citation_ruling.rejection.message,
            )
        if citation_ruling.canonical_arguments is not None:
            arguments = citation_ruling.canonical_arguments

        source_rejection = self._source_governance.assess_authority(
            authority_required=(
                registration.spec.safety_policy.get("source_authority_required")
                is True
            ),
            arguments=arguments,
            context=context,
        )
        if source_rejection is not None:
            return self._error(
                call.tool_call_id,
                source_rejection.code,
                source_rejection.message,
            )
        try:
            binding = self._prepare_binding(
                registration,
                arguments,
                source_authority=context.source_authority,
            )
            _canonical_json(binding)
        except Exception:
            citation_rejection = self._citation_governance.binding_failure(
                registration.spec.safety_policy
            )
            if citation_rejection is not None:
                return self._error(
                    call.tool_call_id,
                    citation_rejection.code,
                    citation_rejection.message,
                )
            return self._error(
                call.tool_call_id,
                "binding_failure",
                "Tool safety preconditions could not be prepared.",
            )

        try:
            decision = self._policy_for(registration).evaluate(
                registration.spec, arguments, binding
            )
        except Exception:
            return self._error(
                call.tool_call_id,
                "policy_failure",
                "Tool policy evaluation failed closed.",
            )
        if decision is PolicyDecision.DENY:
            if binding.get("reason") == "workspace_file_policy":
                return self._error(
                    call.tool_call_id,
                    "workspace_file_denied",
                    (
                        "The workspace file operation was rejected before any effect. Use an "
                        "exact workspace-relative path (never an absolute, parent, private, "
                        "or invented path); call list_files on '.' when discovery is needed, "
                        "then retry the exact entry. A .citations.json sidecar must be rebuilt "
                        "and replaced with write_file, not edit_file."
                    ),
                )
            return self._error(call.tool_call_id, "policy_denied", "Tool policy denied the call.")
        background_action, background_error = self._prepare_background_action(
            registration=registration,
            arguments=arguments,
            binding=binding,
            context=context,
        )
        if background_error is not None:
            return self._error(
                call.tool_call_id,
                background_error,
                "Background occurrence authority is unavailable or exhausted.",
            )
        if background_action is not None:
            decision = PolicyDecision.ALLOW
        elif context.background_execution_authority is not None:
            # Background activation admits only the two frozen unattended classes.
            # Everything else retains the ordinary approval path; the grant never
            # broadens an existing policy decision.
            decision = PolicyDecision.REQUIRE_APPROVAL
        if registration.spec.egress is EgressClass.PUBLIC_NETWORK:
            # PUBLIC_NETWORK 的用户可见外发不能被 registration 自定义 policy
            # 或 Goal authorization 降级；首次 prepare 必须形成 durable approval。
            decision = PolicyDecision.REQUIRE_APPROVAL
        if (
            registration.spec.safety_policy.get("kind") == "memory_remember"
            and context.goal_id is not None
            and context.fact_admission is None
        ):
            return self._error(
                call.tool_call_id,
                "fact_admission_required",
                "Workspace memory requires a Runtime-verified source fact.",
            )
        if (
            registration.spec.safety_policy.get("kind")
            in {"owner_preference_confirm", "owner_preference_correct"}
            and context.preference_admission is None
        ):
            return self._error(
                call.tool_call_id,
                "preference_admission_required",
                "Owner preference mutation requires an exact user-confirmed source fact.",
            )
        if decision is PolicyDecision.REQUIRE_APPROVAL and self._goal_authorizes(
            registration.spec,
            arguments,
            context,
        ):
            decision = PolicyDecision.ALLOW

        process_candidate: ProcessAuthorityCandidateV1 | None = None
        process_lease: ProcessAuthorityLeaseV1 | None = None
        if registration.spec.execution_authority is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS:
            if not (
                context.goal_id
                and context.goal_revision
                and context.workspace_identity_digest
            ):
                return self._error(
                    call.tool_call_id,
                    "process_requires_goal",
                    "local_process requires a durable Goal before any execution.",
                )
            process_candidate = self._build_process_candidate(binding, context)
            if decision is PolicyDecision.REQUIRE_APPROVAL:
                process_lease = self._match_process_lease(process_candidate, context)
                if process_lease is not None:
                    decision = PolicyDecision.ALLOW

        sandbox_candidate: SandboxAuthorityCandidateV1 | None = None
        sandbox_lease: SandboxAuthorityLeaseV1 | None = None
        if registration.spec.execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX:
            if not (
                context.goal_id
                and context.goal_revision
                and context.workspace_identity_digest
            ):
                return self._error(
                    call.tool_call_id,
                    "sandbox_requires_goal",
                    "sandbox_exec requires a durable Goal before any execution.",
                )
            sandbox_candidate = self._build_sandbox_candidate(binding, context)
            if decision is PolicyDecision.REQUIRE_APPROVAL:
                sandbox_lease = self._match_sandbox_lease(
                    sandbox_candidate, context,
                )
                if sandbox_lease is not None:
                    decision = PolicyDecision.ALLOW

        browser_candidate: BrowserActionCandidateV1 | None = None
        browser_lease: BrowserAuthorityLeaseV1 | None = None
        if (
            registration.spec.execution_authority
            is ExecutionAuthorityClass.BROWSER_SESSION
            and registration.spec.safety_policy.get("kind") == "browser_action"
        ):
            if not (context.goal_id and context.goal_revision):
                return self._error(
                    call.tool_call_id,
                    "browser_requires_goal",
                    "browser actions require a durable Goal before execution.",
                )
            try:
                browser_candidate = self._build_browser_candidate(binding, context)
            except (KeyError, TypeError, ValueError):
                return self._error(
                    call.tool_call_id,
                    "browser_binding_invalid",
                    "Browser action safety binding is incomplete or invalid.",
                )
            if decision is PolicyDecision.REQUIRE_APPROVAL:
                browser_lease = self._match_browser_lease(browser_candidate, context)
                if browser_lease is not None:
                    decision = PolicyDecision.ALLOW

        intent = self._make_intent(
            call,
            context,
            registration.spec,
            arguments,
            binding,
            self._policy_for(registration).identity,
            process_lease=process_lease,
            sandbox_lease=sandbox_lease,
            browser_lease=browser_lease,
            background_action_authority=background_action,
        )
        if background_action is not None:
            authority = context.background_execution_authority
            assert authority is not None
            self._background_prepared_authorities[intent.intent_digest] = authority
        if decision is PolicyDecision.REQUIRE_APPROVAL:
            request = self._approval_request(intent, registration.spec, context)
            if browser_candidate is not None:
                return ApprovalRequired(
                    replace(request, browser_action_candidate=browser_candidate)
                )
            if sandbox_candidate is not None:
                # 017：ISOLATED_SANDBOX authority 只能来自 exact active durable
                # lease（ResolveApproval 铸造）；approval 绑定全 environment
                # identity（goal/revision/workspace/image/snapshot/spec）。
                return ApprovalRequired(
                    replace(
                        request,
                        sandbox_authority_candidate=sandbox_candidate,
                    )
                )
            if process_candidate is not None:
                # F1（P1 review finding 2026-08-16）：LOCAL_SAME_UID_PROCESS 的
                # authority 只能来自 exact active durable lease（ResolveApproval 铸造）。
                # ApprovalGrant 本身不可授权进程执行——revoke/expiry/clock rollback 后
                # 的 stale grant 必须 fail closed：重新 approval（新 candidate → 新
                # lease），绝不 mint 无 lease 的可执行 intent。
                try:
                    requirement = self._artifact_confirmation_requirement(context)
                except ValueError as error:
                    return self._error(
                        call.tool_call_id,
                        "artifact_requirement_ambiguous",
                        str(error),
                    )
                if requirement is not None:
                    binding_digest = _digest_json(
                        {
                            "intent_digest": intent.intent_digest,
                            "artifact_confirmation_requirement": asdict(requirement),
                        }
                    )
                    request = replace(
                        request,
                        request_id=f"approval-{binding_digest[:16]}",
                        binding_digest=binding_digest,
                        preview=(
                            request.preview
                            + "\nartifact verification required: "
                            + requirement.artifact_path
                            + "\nplain yes/approve only authorizes the effect and is disabled "
                            "for this request; use /approve-artifact <sha256> <path>"
                        ),
                    )
                return ApprovalRequired(
                    replace(
                        request,
                        process_authority_candidate=process_candidate,
                        artifact_confirmation_requirement=requirement,
                    )
                )
            if approval is None:
                return ApprovalRequired(request)
            if (
                approval.request_id != request.request_id
                or approval.binding_digest != request.binding_digest
            ):
                return self._error(
                    call.tool_call_id,
                    "approval_mismatch",
                    "Approval does not match the current tool intent.",
                )
        return intent

    @staticmethod
    def _artifact_confirmation_requirement(
        context: ToolPrepareContext,
    ) -> ArtifactConfirmationRequirementV1 | None:
        proposed = tuple(
            item
            for item in context.proposed_criteria
            if item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and item.criterion_id not in context.admitted_criterion_ids
        )
        if len(proposed) > 1:
            # 016 真实 E3（第 23 轮 J12）:只陈述规则时模型无法自纠而被困到
            # blocked;消息必须点名冲突 criteria 并给出恢复动作。
            raise ValueError(
                "one local_process approval can bind at most one artifact "
                "requirement; proposed filesystem criteria: "
                + ", ".join(
                    f"{item.criterion_id}={item.artifact_path or 'deferred'}"
                    for item in proposed
                )
                + "; propose a goal_delta_proposal that keeps at most one "
                "unconfirmed filesystem criterion, or complete the pending "
                "artifact confirmation first"
            )
        if not proposed:
            return None
        criterion = proposed[0]
        if criterion.artifact_path is None:
            # 唯一 pending criterion 仍是 deferred 时没有可确认的 artifact——
            # 绑定只发生在具体文件写入批准,而 validator 产物不经 write_file。
            # hard error 会让该 goal 形状永久无法运行 validator(016 真实 E3
            # 第 23/27/34 轮死锁);返回 None 走普通批准,criterion 维持 pending,
            # 不铸造任何 evidence/authority。
            return None
        return ArtifactConfirmationRequirementV1(
            criterion_id=criterion.criterion_id,
            artifact_path=criterion.artifact_path,
        )

    def invoke(self, intent: ExecutionIntent) -> ToolResult:
        registration = self._tools.get(intent.tool_name)
        if registration is None:
            raise IntentConflictError("intent references an unknown tool")
        expected_exposure = ToolExposure(intent.invocation_origin.value)
        if registration.exposure is not expected_exposure:
            raise IntentConflictError("tool exposure changed after preparation")
        if intent.idempotency_key in self._invoked_keys:
            raise IntentConflictError("intent was already invoked")
        if registration.spec.identity_digest != intent.tool_identity:
            raise IntentConflictError("tool identity changed after preparation")
        if _digest_json(intent.arguments) != intent.arguments_digest:
            raise IntentConflictError("intent arguments digest does not match")
        if (
            registration.spec.execution_authority
            is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
            and intent.process_lease is None
        ):
            # F1：无 exact durable lease 的 process intent 一律拒绝（defense in
            # depth——prepare 已不 mint 此形状，伪造/旧形状同样零 spawn）。
            raise IntentConflictError(
                "process authority intent requires an exact active durable lease"
            )
        if intent.process_lease is not None and not self._lease_is_active_now(
            intent.process_lease
        ):
            raise IntentConflictError("process authority lease expired before invocation")
        if (
            registration.spec.execution_authority
            is ExecutionAuthorityClass.ISOLATED_SANDBOX
            and intent.sandbox_lease is None
            and (
                intent.background_action_authority is None
                or intent.background_action_authority.action_class != "sandbox_confined"
            )
        ):
            # 017（F1 对齐）：无 exact durable lease 的 sandbox intent 一律拒绝。
            raise IntentConflictError(
                "sandbox authority intent requires an exact active durable lease"
            )
        if intent.sandbox_lease is not None and not self._sandbox_lease_is_active_now(
            intent.sandbox_lease
        ):
            raise IntentConflictError("sandbox authority lease expired before invocation")
        if intent.browser_lease is not None and not self._browser_lease_authorizes_intent(
            intent.browser_lease, intent
        ):
            raise IntentConflictError("browser authority lease expired before invocation")
        if (
            registration.spec.execution_authority
            is ExecutionAuthorityClass.BROWSER_SESSION
            and registration.spec.safety_policy.get("kind") == "browser_action"
            and intent.safety_binding.get("consequence") != "observe"
            and intent.browser_lease is None
        ):
            raise IntentConflictError(
                "browser action requires an exact active durable lease"
            )
        if intent.browser_lease is not None and not self._browser_lease_authorizes_intent(
            intent.browser_lease, intent
        ):
            raise IntentConflictError("browser authority lease changed before invocation")
        if intent.background_action_authority is not None:
            self._verify_background_action_for_invoke(intent, registration)

        try:
            current_binding = self._prepare_binding(
                registration,
                intent.arguments,
                source_authority=intent.source_authority,
            )
        except Exception as error:
            raise IntentConflictError(
                "tool safety preconditions could not be revalidated"
            ) from error
        if current_binding != intent.safety_binding:
            raise IntentConflictError("tool safety preconditions changed after preparation")
        if self._intent_digest(intent) != intent.intent_digest:
            raise IntentConflictError("intent binding digest does not match")
        try:
            decision = self._policy_for(registration).evaluate(
                registration.spec,
                intent.arguments,
                current_binding,
            )
        except Exception as error:
            raise IntentConflictError("tool policy could not be re-evaluated") from error
        if decision is PolicyDecision.DENY:
            raise IntentConflictError("tool policy now denies the intent")
        intent_context = ToolPrepareContext(
            conversation_id=intent.conversation_id,
            run_id=intent.run_id,
            state_revision=0,
            invocation_origin=intent.invocation_origin,
            approval_basis_revision=intent.approval_basis_revision,
            goal_id=intent.goal_id,
            goal_revision=intent.goal_revision,
            workspace_identity_digest=intent.workspace_identity_digest,
            goal_authorization=intent.goal_authorization,
            source_authority=intent.source_authority,
        )
        if (
            decision is PolicyDecision.REQUIRE_APPROVAL
            and intent.goal_authorization is not None
            and not self._goal_authorizes(
                registration.spec,
                intent.arguments,
                intent_context,
            )
        ):
            raise IntentConflictError("goal authorization changed after preparation")

        # binding 哈希或 policy 重验可能跨过 lease 过期边界。在真正
        # callable/spawn 之前最后重验，不允许已铸 intent 消费过期权限。
        if intent.process_lease is not None and not self._lease_is_active_now(
            intent.process_lease
        ):
            raise IntentConflictError("process authority lease expired before invocation")
        if intent.sandbox_lease is not None and not self._sandbox_lease_is_active_now(
            intent.sandbox_lease
        ):
            raise IntentConflictError("sandbox authority lease expired before invocation")

        self._invoked_keys.add(intent.idempotency_key)
        self._background_prepared_authorities.pop(intent.intent_digest, None)
        try:
            raw_result = registration.func(intent)
            if isinstance(raw_result, BrowserTakeoverRequestV1):
                if (
                    registration.spec.execution_authority
                    is not ExecutionAuthorityClass.BROWSER_SESSION
                    or registration.spec.name != "browser_begin_takeover"
                    or intent.goal_id != raw_result.goal_id
                    or intent.goal_revision != raw_result.goal_revision
                    or intent.browser_takeover_request != raw_result
                ):
                    raise IntentConflictError(
                        "browser takeover request does not bind the governed browser intent"
                    )
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content="Browser takeover is waiting for the user.",
                    executed=False,
                    metadata={
                        "code": "browser_takeover_pending",
                        "tool_identity": registration.spec.identity_digest,
                    },
                    browser_takeover_request=raw_result,
                )
            if isinstance(raw_result, ProcessExecutionDraftV1):
                return self._process_outcome(intent, registration.spec, raw_result)
            if isinstance(raw_result, StructuredSandboxProcessDraftV1):
                return self._structured_sandbox_outcome(
                    intent, registration.spec, raw_result
                )
            if isinstance(raw_result, SandboxExecutionDraftV1):
                return self._sandbox_outcome(intent, registration.spec, raw_result)
            if (
                registration.spec.execution_authority
                is ExecutionAuthorityClass.BROWSER_SESSION
                and isinstance(raw_result, ToolExecutionOutput)
            ):
                return self._browser_governance.normalize_result(
                    intent, registration.spec, raw_result
                )
            if (
                registration.spec.execution_authority
                is ExecutionAuthorityClass.ISOLATED_SANDBOX
                and not isinstance(raw_result, KnownNotExecuted)
            ):
                raise IntentConflictError(
                    "sandbox callable must return a verifiable execution draft"
                )
            if registration.spec.source_kinds:
                return self._source_governance.normalize_result(
                    intent, registration.spec, raw_result
                )
            if isinstance(raw_result, ToolExecutionOutput | ToolResult):
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content="Tool returned an output contract it is not authorized to use.",
                    is_error=True,
                    executed=True,
                    metadata={"code": "source_contract_mismatch"},
                )
            if isinstance(raw_result, KnownExecutedError):
                # effect 已发生但明确失败：known-executed error，不能展平为 success（A18/R27）。
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content=raw_result.message[: registration.spec.output_limit_chars],
                    is_error=True,
                    executed=True,
                    metadata={
                        "code": raw_result.code,
                        "tool_identity": registration.spec.identity_digest,
                    },
                )
            if isinstance(raw_result, KnownNotExecuted):
                # executor 在 effect 前证明副作用没有发生：作为普通 tool result 推进游标，
                # 标记 executed=False 让模型修正；不进入 unknown-outcome recovery。
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content=raw_result.message[: registration.spec.output_limit_chars],
                    is_error=True,
                    executed=False,
                    metadata={
                        "code": raw_result.code,
                        "tool_identity": registration.spec.identity_digest,
                    },
                )
            content = _normalize_output(raw_result)
        except Exception:
            if (
                registration.spec.side_effect is not SideEffectClass.READ_ONLY
                or registration.spec.egress is EgressClass.PUBLIC_NETWORK
            ):
                # 写入/外部效果可能已经发生；必须由上层进入 unknown-outcome 恢复态。
                raise
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Tool execution failed."[: registration.spec.output_limit_chars],
                is_error=True,
                executed=False,
                metadata={"code": "tool_error"},
            )
        return ToolResult(
            tool_call_id=intent.tool_call_id,
            content=content[: registration.spec.output_limit_chars],
            metadata={
                "truncated": len(content) > registration.spec.output_limit_chars,
                "tool_identity": registration.spec.identity_digest,
            },
        )

    @staticmethod
    def _prepare_binding(
        registration: RegisteredTool,
        arguments: dict[str, JSONValue],
        *,
        source_authority: SourceAuthorityBinding | None,
    ) -> dict[str, JSONValue]:
        binding = (
            registration.prepare_binding(arguments)
            if registration.prepare_binding is not None
            else {}
        )
        if registration.prepare_authority_binding is None:
            return binding
        if source_authority is None:
            raise ValueError("source authority is required for URL binding")
        return {
            **binding,
            **registration.prepare_authority_binding(arguments, source_authority),
        }

    def _make_intent(
        self,
        call: ToolCall,
        context: ToolPrepareContext,
        spec: ToolSpec,
        arguments: dict[str, JSONValue],
        binding: dict[str, JSONValue],
        policy_identity: str,
        *,
        process_lease: ProcessAuthorityLeaseV1 | None = None,
        sandbox_lease: SandboxAuthorityLeaseV1 | None = None,
        browser_lease: BrowserAuthorityLeaseV1 | None = None,
        background_action_authority: BackgroundActionAuthorityV1 | None = None,
    ) -> ExecutionIntent:
        browser_takeover_request: BrowserTakeoverRequestV1 | None = None
        if spec.safety_policy.get("kind") == "browser_takeover":
            if (
                spec.execution_authority is not ExecutionAuthorityClass.BROWSER_SESSION
                or not context.goal_id
                or context.goal_revision is None
            ):
                raise ValueError("browser takeover requires an active Goal")
            browser_takeover_request = BrowserTakeoverRequestV1(
                request_id=f"browser-takeover:{binding['session_ref']}",
                session_ref=str(binding["session_ref"]),
                profile_ref=str(binding["profile_ref"]),
                profile_revision=int(binding["profile_revision"]),
                browser_identity_digest=str(binding["browser_identity_digest"]),
                goal_id=context.goal_id,
                goal_revision=context.goal_revision,
                requested_at=self._clock(),
            )
        intent = ExecutionIntent(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            tool_identity=spec.identity_digest,
            arguments=arguments,
            arguments_digest=_digest_json(arguments),
            intent_digest="",
            idempotency_key=(
                f"{context.conversation_id}:{context.run_id}:{call.tool_call_id}"
            ),
            policy_identity=policy_identity,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            side_effect=spec.side_effect,
            invocation_origin=context.invocation_origin,
            egress=spec.egress,
            execution_authority=spec.execution_authority,
            operation=(
                binding.get("operation")
                if isinstance(binding.get("operation"), str)
                else spec.name
            ),
            request_identity=(
                binding.get("request_identity")
                if isinstance(binding.get("request_identity"), str)
                else (
                    f"{context.conversation_id}:{context.run_id}:{call.tool_call_id}"
                )
            ),
            approval_basis_revision=context.approval_basis_revision,
            source_authority=context.source_authority,
            safety_binding=binding,
            goal_id=context.goal_id,
            goal_revision=context.goal_revision,
            workspace_identity_digest=context.workspace_identity_digest,
            goal_authorization=context.goal_authorization,
            fact_admission=context.fact_admission,
            preference_admission=context.preference_admission,
            process_lease=process_lease,
            sandbox_lease=sandbox_lease,
            browser_lease=browser_lease,
            browser_takeover_request=browser_takeover_request,
            background_action_authority=background_action_authority,
        )
        return replace(
            intent,
            intent_digest=self._intent_digest(intent),
        )

    def _build_sandbox_candidate(
        self,
        binding: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> SandboxAuthorityCandidateV1:
        command_fingerprint = str(binding["command_fingerprint"])
        candidate_id = f"sandbox-candidate:{command_fingerprint[:16]}"
        return SandboxAuthorityCandidateV1.create(
            candidate_id=candidate_id,
            goal_id=context.goal_id,
            goal_revision=context.goal_revision,
            workspace_identity_digest=context.workspace_identity_digest,
            original_command_fingerprint=command_fingerprint,
            policy_digest=str(binding["policy_digest"]),
            mode=str(binding["sandbox_mode"]),
            network=str(binding["sandbox_network"]),
            readable_command=str(binding["effect_preview"]),
            trust_notice_id=str(binding["trust_notice_id"]),
            trust_notice_digest=str(binding["trust_notice_digest"]),
            issued_at=self._clock(),
        )

    def _match_sandbox_lease(
        self,
        candidate: SandboxAuthorityCandidateV1,
        context: ToolPrepareContext,
    ) -> SandboxAuthorityLeaseV1 | None:
        # 与 process lease 相同的 fail-closed 时效判定：zoned RFC3339 数值比较。
        now_dt = _parse_zoned_rfc3339(self._clock())
        if now_dt is None:
            return None
        for lease in context.sandbox_leases:
            issued_dt = _parse_zoned_rfc3339(lease.issued_at)
            expires_dt = _parse_zoned_rfc3339(lease.expires_at)
            if (
                lease.verify()
                and issued_dt is not None
                and expires_dt is not None
                and lease.matches(
                    goal_id=candidate.goal_id,
                    goal_revision=candidate.goal_revision,
                    workspace_identity_digest=candidate.workspace_identity_digest,
                    original_command_fingerprint=(
                        candidate.original_command_fingerprint
                    ),
                    policy_digest=candidate.policy_digest,
                    mode=candidate.mode,
                    network=candidate.network,
                )
                and lease.candidate_digest == candidate.candidate_digest
                and lease.uses_consumed < lease.max_uses
                and issued_dt <= now_dt < expires_dt
            ):
                return lease
        return None

    def _build_browser_candidate(
        self,
        binding: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> BrowserActionCandidateV1:
        action_digest = str(binding["action_digest"])
        return BrowserActionCandidateV1.create(
            candidate_id=f"browser-candidate:{action_digest[:16]}",
            goal_id=context.goal_id,
            goal_revision=context.goal_revision,
            session_ref=str(binding["session_ref"]),
            browser_identity_digest=str(binding["browser_identity_digest"]),
            profile_ref=binding.get("profile_ref"),
            profile_revision=binding.get("profile_revision"),
            allowed_origins=tuple(binding["allowed_origins"]),
            mode=str(binding["mode"]),
            page_id=str(binding["page_id"]),
            frame_id=str(binding["frame_id"]),
            observation_digest=str(binding["observation_digest"]),
            action_digest=action_digest,
            consequence=str(binding["consequence"]),
            preview=str(binding["effect_preview"]),
            issued_at=str(binding["issued_at"]),
            expires_at=str(binding["expires_at"]),
        )

    def _match_browser_lease(
        self,
        candidate: BrowserActionCandidateV1,
        context: ToolPrepareContext,
    ) -> BrowserAuthorityLeaseV1 | None:
        for lease in context.browser_leases:
            if (
                lease.candidate_digest == candidate.candidate_digest
                and lease.authorizes(
                    goal_id=candidate.goal_id,
                    goal_revision=candidate.goal_revision,
                    session_ref=candidate.session_ref,
                    browser_identity_digest=candidate.browser_identity_digest,
                    profile_ref=candidate.profile_ref,
                    profile_revision=candidate.profile_revision,
                    allowed_origins=candidate.allowed_origins,
                    mode=candidate.mode,
                    page_id=candidate.page_id,
                    frame_id=candidate.frame_id,
                    observation_digest=candidate.observation_digest,
                    action_digest=candidate.action_digest,
                    consequence=candidate.consequence,
                    now=self._clock(),
                )
            ):
                return lease
        return None

    def _browser_lease_authorizes_intent(
        self,
        lease: BrowserAuthorityLeaseV1,
        intent: ExecutionIntent,
    ) -> bool:
        binding = intent.safety_binding
        try:
            return lease.authorizes(
                goal_id=intent.goal_id or "",
                goal_revision=intent.goal_revision or 0,
                session_ref=str(binding["session_ref"]),
                browser_identity_digest=str(binding["browser_identity_digest"]),
                profile_ref=binding.get("profile_ref"),
                profile_revision=binding.get("profile_revision"),
                allowed_origins=tuple(binding["allowed_origins"]),
                mode=str(binding["mode"]),
                page_id=str(binding["page_id"]),
                frame_id=str(binding["frame_id"]),
                observation_digest=str(binding["observation_digest"]),
                action_digest=str(binding["action_digest"]),
                consequence=str(binding["consequence"]),
                now=self._clock(),
            )
        except (KeyError, TypeError, ValueError):
            return False

    def _sandbox_lease_is_active_now(self, lease: SandboxAuthorityLeaseV1) -> bool:
        now_dt = _parse_zoned_rfc3339(self._clock())
        if now_dt is None:
            return False
        issued_dt = _parse_zoned_rfc3339(lease.issued_at)
        expires_dt = _parse_zoned_rfc3339(lease.expires_at)
        return (
            lease.verify()
            and issued_dt is not None
            and expires_dt is not None
            and lease.uses_consumed < lease.max_uses
            and issued_dt <= now_dt < expires_dt
        )

    def _lease_is_active_now(self, lease: ProcessAuthorityLeaseV1) -> bool:
        now = _parse_zoned_rfc3339(self._clock())
        issued = _parse_zoned_rfc3339(lease.issued_at)
        expires = _parse_zoned_rfc3339(lease.expires_at)
        return (
            now is not None
            and issued is not None
            and expires is not None
            and issued <= now < expires
            and lease.remaining_uses > 0
        )

    def _intent_digest(self, intent: ExecutionIntent) -> str:
        return _digest_json(
            {
                "tool_call_id": intent.tool_call_id,
                "tool_name": intent.tool_name,
                "tool_identity": intent.tool_identity,
                "arguments_digest": intent.arguments_digest,
                "idempotency_key": intent.idempotency_key,
                "policy_identity": intent.policy_identity,
                "invocation_origin": intent.invocation_origin.value,
                "conversation_id": intent.conversation_id,
                "run_id": intent.run_id,
                "side_effect": intent.side_effect.value,
                "egress": intent.egress.value,
                "execution_authority": intent.execution_authority.value,
                "operation": intent.operation,
                "request_identity": intent.request_identity,
                "approval_basis_revision": intent.approval_basis_revision,
                "source_authority_digest": (
                    intent.source_authority.binding_digest
                    if intent.source_authority is not None
                    else None
                ),
                "safety_binding": intent.safety_binding,
                "goal_id": intent.goal_id,
                "goal_revision": intent.goal_revision,
                "workspace_identity_digest": intent.workspace_identity_digest,
                "goal_authorization_digest": (
                    intent.goal_authorization.binding_digest
                    if intent.goal_authorization is not None
                    else None
                ),
                "fact_admission_digest": (
                    intent.fact_admission.binding_digest
                    if intent.fact_admission is not None
                    else None
                ),
                "preference_admission_digest": (
                    intent.preference_admission.binding_digest
                    if intent.preference_admission is not None
                    else None
                ),
                "process_lease_digest": (
                    intent.process_lease.lease_digest
                    if intent.process_lease is not None
                    else None
                ),
                "sandbox_lease_digest": (
                    intent.sandbox_lease.lease_digest
                    if intent.sandbox_lease is not None
                    else None
                ),
                "browser_lease_digest": (
                    intent.browser_lease.lease_digest
                    if intent.browser_lease is not None
                    else None
                ),
                "browser_takeover_request": (
                    asdict(intent.browser_takeover_request)
                    if intent.browser_takeover_request is not None
                    else None
                ),
                "background_action_authority_digest": (
                    intent.background_action_authority.authority_digest
                    if intent.background_action_authority is not None
                    else None
                ),
            }
        )

    def _prepare_background_action(
        self,
        *,
        registration: RegisteredTool,
        arguments: dict[str, JSONValue],
        binding: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> tuple[BackgroundActionAuthorityV1 | None, str | None]:
        authority = context.background_execution_authority
        if authority is None:
            return None, None
        verifier = self._background_claim_verifier
        if verifier is None:
            return None, "background_claim_unavailable"
        check = BackgroundClaimCheckV1.create(
            execution_authority=authority,
            observed_at_utc=self._clock(),
        )
        try:
            verdict = verifier.verify(check)
        except Exception:
            return None, "background_claim_unavailable"
        if not isinstance(verdict, BackgroundClaimVerdictV1):
            return None, "background_claim_unavailable"
        if not verdict.allowed:
            return None, f"background_claim_{verdict.reason}"
        classification = self._background_action_class(
            registration.spec,
            binding,
            context.workspace_identity_digest,
            authority,
            verdict,
        )
        if classification is None:
            return None, None
        action_class, policy_digest, class_limit = classification
        binding_contract = authority.occurrence_binding
        class_used = (
            context.background_sandbox_commands_used
            if action_class == "sandbox_confined"
            else context.background_browser_actions_used
        )
        if context.background_tool_calls_used >= binding_contract.tool_call_limit:
            return None, "background_tool_budget_exhausted"
        if class_used >= class_limit:
            return None, f"background_{action_class}_budget_exhausted"
        action_fingerprint = canonical_json_digest(
            {
                "tool_name": registration.spec.name,
                "tool_identity": registration.spec.identity_digest,
                "arguments_digest": _digest_json(arguments),
                "safety_binding": binding,
                "policy_identity": self._policy_for(registration).identity,
                "occurrence_binding_digest": binding_contract.binding_digest,
                "action_class": action_class,
                "budget_ordinal": class_used + 1,
            }
        )
        return (
            BackgroundActionAuthorityV1(
                action_class=action_class,
                action_fingerprint=action_fingerprint,
                occurrence_binding_digest=binding_contract.binding_digest,
                claim_verdict_digest=verdict.verdict_digest,
                budget_ordinal=class_used + 1,
                policy_digest=policy_digest,
            ),
            None,
        )

    @staticmethod
    def _background_action_class(
        spec: ToolSpec,
        binding: dict[str, JSONValue],
        workspace_identity_digest: str | None,
        authority: BackgroundExecutionAuthorityV1,
        verdict,
    ) -> tuple[str, str, int] | None:  # noqa: ANN001
        occurrence = authority.occurrence_binding
        kind = spec.safety_policy.get("kind")
        if (
            verdict.sandbox_confined
            and spec.execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX
            and kind == "sandbox_exec"
            and spec.safety_policy.get("shell") is False
            and spec.safety_policy.get("background") is False
            and workspace_identity_digest
            == authority.isolated_workspace_identity_digest
            and binding.get("sandbox_mode") in {"read-only", "workspace-write"}
            and binding.get("sandbox_network") == "off"
            and binding.get("policy_digest")
            == verdict.background_environment_policy_digest
            and authority.background_environment_policy_digest
            == verdict.background_environment_policy_digest
        ):
            return (
                "sandbox_confined",
                str(binding["policy_digest"]),
                occurrence.sandbox_command_limit,
            )
        if (
            verdict.browser_public_observe
            and spec.execution_authority is ExecutionAuthorityClass.BROWSER_SESSION
            and verdict.browser_origin_policy_digest is not None
            and authority.browser_origin_policy_digest
            == verdict.browser_origin_policy_digest
            and binding.get("mode") == "public_read_ephemeral"
            and (
                (
                    kind == "browser_open"
                    and binding.get("profile_ref") is None
                    and binding.get("profile_revision") is None
                    and binding.get("allowed_origins") == []
                )
                or kind == "browser_observe"
                or (kind == "browser_action" and binding.get("consequence") == "observe")
            )
        ):
            return (
                "browser_public_observe",
                authority.browser_origin_policy_digest,
                occurrence.browser_action_limit,
            )
        return None

    def _verify_background_action_for_invoke(
        self,
        intent: ExecutionIntent,
        registration: RegisteredTool,
    ) -> None:
        action = intent.background_action_authority
        assert action is not None
        authority = self._background_prepared_authorities.get(intent.intent_digest)
        verifier = self._background_claim_verifier
        if authority is None or verifier is None:
            raise IntentConflictError("background claim capability is unavailable")
        try:
            verdict = verifier.verify(
                BackgroundClaimCheckV1.create(
                    execution_authority=authority,
                    observed_at_utc=self._clock(),
                )
            )
        except Exception as error:
            raise IntentConflictError("background claim verification failed") from error
        if not isinstance(verdict, BackgroundClaimVerdictV1):
            raise IntentConflictError("background claim verifier returned an invalid verdict")
        if not verdict.allowed:
            raise IntentConflictError("background claim is no longer active")
        classification = self._background_action_class(
            registration.spec,
            intent.safety_binding,
            intent.workspace_identity_digest,
            authority,
            verdict,
        )
        if classification is None:
            raise IntentConflictError("background action classification changed")
        action_class, policy_digest, limit = classification
        if (
            action.action_class != action_class
            or action.policy_digest != policy_digest
            or action.occurrence_binding_digest
            != authority.occurrence_binding.binding_digest
            or action.claim_verdict_digest != verdict.verdict_digest
            or action.budget_ordinal > limit
        ):
            raise IntentConflictError("background action authority changed")
        expected_fingerprint = canonical_json_digest(
            {
                "tool_name": registration.spec.name,
                "tool_identity": registration.spec.identity_digest,
                "arguments_digest": intent.arguments_digest,
                "safety_binding": intent.safety_binding,
                "policy_identity": intent.policy_identity,
                "occurrence_binding_digest": authority.occurrence_binding.binding_digest,
                "action_class": action.action_class,
                "budget_ordinal": action.budget_ordinal,
            }
        )
        if action.action_fingerprint != expected_fingerprint:
            raise IntentConflictError("background action fingerprint changed")

    @staticmethod
    def _goal_authorizes(
        spec: ToolSpec,
        arguments: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> bool:
        binding = context.goal_authorization
        target = arguments.get("path")
        if (
            binding is None
            or context.goal_id is None
            or context.goal_revision is None
            or context.workspace_identity_digest is None
            or spec.side_effect is not SideEffectClass.WRITE
            or spec.safety_policy.get("workspace_scoped") is not True
            or not isinstance(target, str)
            or target != binding.normalized_target
        ):
            return False
        return binding.authorizes(
            goal_id=context.goal_id,
            goal_revision=context.goal_revision,
            workspace_identity_digest=context.workspace_identity_digest,
            operation=spec.name,
            normalized_target=target,
        )

    def _approval_request(
        self,
        intent: ExecutionIntent,
        spec: ToolSpec,
        context: ToolPrepareContext,
    ) -> ApprovalRequest:
        binding = intent.safety_binding
        preview = binding.get("effect_preview")
        if not isinstance(preview, str):
            preview = f"{spec.name}: {spec.side_effect.value}"
        return ApprovalRequest(
            request_id=f"approval-{intent.intent_digest[:16]}",
            run_id=context.run_id,
            tool_call_id=intent.tool_call_id,
            binding_digest=intent.intent_digest,
            preview=preview,
            tool_name=spec.name,
            state_revision=context.state_revision,
            approval_basis_revision=context.approval_basis_revision,
            arguments_digest=intent.arguments_digest,
            policy_identity=intent.policy_identity,
            risk=spec.risk.value,
            side_effect=spec.side_effect.value,
            target_digest=_optional_string(binding.get("target_digest")),
            precondition_digest=_optional_string(binding.get("precondition_digest")),
            new_content_digest=_optional_string(binding.get("new_content_digest")),
            egress=spec.egress.value,
            operation=intent.operation,
            request_identity=intent.request_identity,
            destination_digest=_optional_string(binding.get("destination_digest")),
            cost_class=_optional_string(binding.get("cost_class")),
            trust_notice_id=_optional_string(binding.get("trust_notice_id")),
            trust_notice_digest=_optional_string(binding.get("trust_notice_digest")),
        )

    def _build_process_candidate(
        self,
        binding: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> ProcessAuthorityCandidateV1:
        command_fingerprint = binding["command_fingerprint"]
        candidate_id = f"candidate:{command_fingerprint[:16]}"
        ea_path = binding.get("expected_artifact_path")
        ea_sha = binding.get("expected_artifact_sha256")
        # candidate/lease 的时钟取 prepare 时刻的 runtime clock——**不进入 binding**
        # （F1 review finding：binding 必须对同一 arguments 确定性，否则 prepare→invoke
        # 跨秒边界的全等比较会抛 IntentConflictError → 假 unknown + 烧 lease use）。
        issued_at = self._clock()
        return ProcessAuthorityCandidateV1.create(
            candidate_id=candidate_id,
            goal_id=context.goal_id,
            goal_revision=context.goal_revision,
            workspace_identity_digest=context.workspace_identity_digest,
            command_fingerprint=command_fingerprint,
            readable_command=binding["effect_preview"],
            executable_digest=binding["executable_digest"],
            argv_digest=binding["argv_digest"],
            cwd_digest=binding["cwd_digest"],
            resource_profile=binding["resource_profile"],
            environment_policy_digest=binding["environment_policy_digest"],
            execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
            trust_notice_digest=binding["trust_notice_digest"],
            issued_at=issued_at,
            max_uses=8,
            expiry_minutes=60,
            expected_artifact_path=ea_path,
            expected_artifact_sha256=ea_sha,
        )

    def _match_process_lease(
        self,
        candidate: ProcessAuthorityCandidateV1,
        context: ToolPrepareContext,
    ) -> ProcessAuthorityLeaseV1 | None:
        # Codex 终审 P1：lease 时效必须用严格 zoned RFC3339 数值比较（design §5.4）。
        # 字符串比较在 clock rollback / malformed / naive 时间戳下会错误接受旧
        # authority；任何一侧不可解析 → fail closed（无匹配 → 重新批准）。
        now_dt = _parse_zoned_rfc3339(self._clock())
        if now_dt is None:
            return None
        for lease in context.process_leases:
            issued_dt = _parse_zoned_rfc3339(lease.issued_at)
            expires_dt = _parse_zoned_rfc3339(lease.expires_at)
            if (
                issued_dt is not None
                and expires_dt is not None
                and lease.command_fingerprint == candidate.command_fingerprint
                and lease.goal_id == candidate.goal_id
                and lease.goal_revision == candidate.goal_revision
                and lease.workspace_identity_digest == candidate.workspace_identity_digest
                and lease.remaining_uses > 0
                and issued_dt <= now_dt < expires_dt
            ):
                return lease
        return None

    def _process_outcome(
        self,
        intent: ExecutionIntent,
        spec: ToolSpec,
        draft: ProcessExecutionDraftV1,
    ) -> ToolResult:
        if spec.execution_authority is not ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS:
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Ordinary tool returned a process draft it is not authorized to use.",
                is_error=True,
                executed=True,
                metadata={
                    "code": "process_draft_forgery",
                    "tool_identity": spec.identity_digest,
                },
            )
        if draft.outcome is ProcessDraftOutcome.SPAWN_FAILED:
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="local_process failed before spawn.",
                is_error=True,
                executed=False,
                metadata={
                    "code": draft.error_code or "spawn_failed",
                    "tool_identity": spec.identity_digest,
                },
            )
        self._validate_process_draft(draft, intent)
        receipt = self._mint_process_receipt(intent, spec, draft)
        success = draft.outcome is ProcessDraftOutcome.EXITED and draft.exit_code == 0
        projections = [draft.stdout_projection]
        if draft.stderr_projection:
            if draft.stdout_projection:
                projections.append("\n[stderr]\n")
            projections.append(draft.stderr_projection)
        rendered = "".join(projections)
        content = (
            rendered[: spec.output_limit_chars]
            if rendered
            else f"local_process {draft.outcome.value}"
        )
        return ToolResult(
            tool_call_id=intent.tool_call_id,
            content=content,
            is_error=not success,
            executed=True,
            metadata={
                "process_receipt_kind": "process_v1",
                "process_receipt": receipt.to_json(),
                "receipt_digest": receipt.receipt_digest,
                "execution_authority": spec.execution_authority.value,
                "outcome": draft.outcome.value,
                "exit_code": draft.exit_code,
                "command_fingerprint": intent.safety_binding.get("command_fingerprint"),
                "stdout_truncated": draft.stdout_truncated,
                "stderr_truncated": draft.stderr_truncated,
                "duration_seconds": draft.duration_seconds,
                "resource_profile": intent.safety_binding.get("process_profile"),
                "stdout_digest": draft.stdout_digest,
                "stderr_digest": draft.stderr_digest,
                "lease_id": receipt.lease_id,
                "use_ordinal": receipt.use_ordinal,
                "tool_identity": spec.identity_digest,
                # child stdout/stderr 是数据，不是指令或新的 authority。
                "untrusted_output": True,
            },
        )

    def _sandbox_outcome(
        self,
        intent: ExecutionIntent,
        spec: ToolSpec,
        draft: SandboxExecutionDraftV1,
    ) -> ToolResult:
        if spec.execution_authority is not ExecutionAuthorityClass.ISOLATED_SANDBOX:
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Ordinary tool returned a sandbox draft it is not authorized to use.",
                is_error=True,
                executed=True,
                metadata={
                    "code": "sandbox_draft_forgery",
                    "tool_identity": spec.identity_digest,
                },
            )
        if canonical_json_digest(draft.identity_values()) != draft.draft_digest:
            raise IntentConflictError("sandbox draft digest does not match its facts")
        if draft.outcome is SandboxDraftOutcome.SPAWN_FAILED:
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="sandbox_exec failed before spawn.",
                is_error=True,
                executed=False,
                metadata={
                    "code": "spawn_failed",
                    "tool_identity": spec.identity_digest,
                },
            )
        binding = intent.safety_binding
        facts = draft.enforcement
        expected = {
            "command": binding.get("command_fingerprint"),
            "policy": binding.get(
                "policy_instance_digest",
                binding.get("policy_digest"),
            ),
            "mode": binding.get("sandbox_mode"),
            "network": binding.get("sandbox_network"),
        }
        actual = {
            "command": draft.original_command_fingerprint,
            "policy": facts.policy_digest,
            "mode": facts.mode.value,
            "network": facts.network.value,
        }
        if actual != expected:
            raise IntentConflictError(
                "sandbox draft does not bind the approved command and policy"
            )
        danger = facts.mode.value == "danger-full-access"
        if danger != (facts.backend == "none" and facts.enforcement == "unconfined"):
            raise IntentConflictError("sandbox enforcement facts contradict the policy mode")
        lease = intent.sandbox_lease
        background_action = intent.background_action_authority
        if lease is not None:
            if not lease.matches(
                goal_id=intent.goal_id or "",
                goal_revision=intent.goal_revision or 0,
                workspace_identity_digest=intent.workspace_identity_digest or "",
                original_command_fingerprint=draft.original_command_fingerprint,
                policy_digest=facts.policy_digest,
                mode=facts.mode.value,
                network=facts.network.value,
            ):
                raise IntentConflictError("sandbox lease does not match the execution draft")
            receipt = SandboxReceiptV1.create(
                receipt_id=f"sandbox-receipt:{draft.draft_digest[:24]}",
                lease_id=lease.lease_id,
                lease_digest=lease.lease_digest,
                candidate_digest=lease.candidate_digest,
                goal_id=intent.goal_id or "",
                goal_revision=intent.goal_revision or 0,
                workspace_identity_digest=intent.workspace_identity_digest or "",
                original_command_fingerprint=draft.original_command_fingerprint,
                policy_digest=facts.policy_digest,
                mode=facts.mode.value,
                network=facts.network.value,
                backend=facts.backend,
                enforcement=facts.enforcement,
                profile_digest=facts.profile_digest,
                outcome=draft.outcome.value,
                draft_digest=draft.draft_digest,
                issued_at=self._clock(),
            )
            receipt_kind = "native_sandbox_v1"
            authority_metadata = {"lease_id": lease.lease_id}
        elif (
            background_action is not None
            and background_action.action_class == "sandbox_confined"
        ):
            receipt = BackgroundSandboxReceiptV1.create(
                receipt_id=f"background-sandbox-receipt:{draft.draft_digest[:24]}",
                background_action_authority_digest=background_action.authority_digest,
                occurrence_binding_digest=background_action.occurrence_binding_digest,
                goal_id=intent.goal_id or "",
                goal_revision=intent.goal_revision or 0,
                workspace_identity_digest=intent.workspace_identity_digest or "",
                original_command_fingerprint=draft.original_command_fingerprint,
                policy_digest=facts.policy_digest,
                mode=facts.mode.value,
                network=facts.network.value,
                backend=facts.backend,
                enforcement=facts.enforcement,
                profile_digest=facts.profile_digest,
                outcome=draft.outcome.value,
                draft_digest=draft.draft_digest,
                issued_at=self._clock(),
            )
            receipt_kind = "background_sandbox_v1"
            authority_metadata = {
                "background_action_authority_digest": background_action.authority_digest
            }
        else:
            raise IntentConflictError(
                "sandbox receipt requires an exact durable authority identity"
            )
        success = draft.outcome is SandboxDraftOutcome.EXITED and draft.exit_code == 0
        projections = [draft.stdout_projection]
        if draft.stderr_projection:
            if draft.stdout_projection:
                projections.append("\n[stderr]\n")
            projections.append(draft.stderr_projection)
        rendered = "".join(projections)
        return ToolResult(
            tool_call_id=intent.tool_call_id,
            content=(
                rendered[: spec.output_limit_chars]
                if rendered
                else f"sandbox_exec {draft.outcome.value}"
            ),
            is_error=not success,
            executed=True,
            metadata={
                "sandbox_receipt_kind": receipt_kind,
                "sandbox_receipt": receipt.to_json(),
                "receipt_digest": receipt.receipt_digest,
                "execution_authority": spec.execution_authority.value,
                "outcome": draft.outcome.value,
                "exit_code": draft.exit_code,
                "original_command_fingerprint": (
                    draft.original_command_fingerprint
                ),
                "policy_digest": facts.policy_digest,
                "mode": facts.mode.value,
                "network": facts.network.value,
                "backend": facts.backend,
                "enforcement": facts.enforcement,
                "profile_digest": facts.profile_digest,
                "stdout_truncated": draft.stdout_truncated,
                "stderr_truncated": draft.stderr_truncated,
                "duration_seconds": draft.duration_seconds,
                "stdout_digest": draft.stdout_digest,
                "stderr_digest": draft.stderr_digest,
                **authority_metadata,
                "tool_identity": spec.identity_digest,
                "untrusted_output": True,
            },
        )

    def _structured_sandbox_outcome(
        self,
        intent: ExecutionIntent,
        spec: ToolSpec,
        draft: StructuredSandboxProcessDraftV1,
    ) -> ToolResult:
        """验证 transient readback draft，再复用唯一 sandbox receipt minting 路径。"""

        if canonical_json_digest(draft.identity_values()) != draft.draft_digest:
            raise IntentConflictError("structured sandbox draft digest does not match")
        if draft.structured_invocation_digest != intent.safety_binding.get(
            "structured_invocation_digest"
        ):
            raise IntentConflictError(
                "structured invocation digest does not bind the approved intent"
            )
        if hashlib.sha256(draft.result_bytes).hexdigest() != draft.result_digest:
            raise IntentConflictError("structured result digest does not match bytes")
        expected_artifact = (
            hashlib.sha256(draft.artifact_bytes).hexdigest()
            if draft.artifact_bytes is not None
            else None
        )
        if expected_artifact != draft.artifact_digest:
            raise IntentConflictError("structured artifact digest does not match bytes")
        process_result = self._sandbox_outcome(intent, spec, draft.process)
        if not process_result.executed:
            metadata = dict(process_result.metadata)
            metadata["structured_invocation_digest"] = draft.structured_invocation_digest
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content=process_result.content,
                is_error=process_result.is_error,
                executed=False,
                metadata=metadata,
            )
        if (
            "sandbox_receipt" not in process_result.metadata
            or "sandbox_receipt_kind" not in process_result.metadata
        ):
            return process_result
        metadata = dict(process_result.metadata)
        metadata["structured_invocation_digest"] = draft.structured_invocation_digest
        if draft.readback_outcome is not StructuredReadbackOutcome.VALID:
            metadata["code"] = draft.readback_outcome.value
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Structured sandbox readback failed.",
                is_error=True,
                executed=True,
                metadata=metadata,
            )
        try:
            result_text = draft.result_bytes.decode("utf-8")
            decoded = json.loads(result_text)
            result_kind = decoded["kind"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            metadata["code"] = StructuredReadbackOutcome.RESULT_MALFORMED.value
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Structured sandbox readback failed.",
                is_error=True,
                executed=True,
                metadata=metadata,
            )
        metadata.update(
            {
                "structured_result_digest": draft.result_digest,
                "structured_artifact_digest": draft.artifact_digest,
                "structured_result_size": len(draft.result_bytes),
                "structured_artifact_size": (
                    len(draft.artifact_bytes)
                    if draft.artifact_bytes is not None
                    else None
                ),
                "structured_result_kind": result_kind,
            }
        )
        return ToolResult(
            tool_call_id=intent.tool_call_id,
            content=result_text[: spec.output_limit_chars],
            is_error=process_result.is_error,
            executed=True,
            metadata=metadata,
        )

    @staticmethod
    def _validate_process_draft(
        draft: ProcessExecutionDraftV1, intent: ExecutionIntent
    ) -> None:
        """P3（冻结合同 / KTD8）：Kernel 铸 receipt 前校验 runner draft 的 closed bounds。

        draft 是 runner 的私有输出合同，但 invoke 是唯一铸造 durable receipt 的层——
        越界 draft（超 profile caps、outcome 与 exit/signal/reap 形状不符、非 64-hex
        digest、超预算时长/投影）必须 fail closed（EXTERNAL → unknown recovery），
        不得盲信 process callable。"""

        profile_name = intent.safety_binding.get("resource_profile")
        profile = ResourceProfileV1.for_profile(ResourceProfile(str(profile_name)))
        violations: list[str] = []
        if draft.outcome is ProcessDraftOutcome.EXITED and (
            not isinstance(draft.exit_code, int) or isinstance(draft.exit_code, bool)
        ):
            violations.append("exited requires an integer exit_code")
        if draft.outcome is ProcessDraftOutcome.SIGNALED and (
            not isinstance(draft.signal, str) or not draft.signal
        ):
            violations.append("signaled requires a signal name")
        if draft.outcome is ProcessDraftOutcome.SIGNALED and draft.exit_code is not None:
            violations.append("signaled must not pin exit_code")
        if draft.outcome is ProcessDraftOutcome.TIMED_OUT_REAPED:
            if draft.exit_code is not None:
                violations.append("timed_out_reaped must not pin exit_code")
            if not draft.group_reaped:
                violations.append("timed_out_reaped requires confirmed group reap")
        if not isinstance(draft.pid, int) or not isinstance(
            draft.process_group_id, int
        ):
            violations.append("post-spawn draft requires pid and process group identity")
        if draft.duration_seconds < 0:
            violations.append("duration must be non-negative")
        allowed_seconds = (
            profile.wall_deadline_seconds
            + profile.term_grace_seconds
            + profile.kill_grace_seconds
            + 12.0
        )
        if draft.duration_seconds > allowed_seconds:
            violations.append("duration exceeds the profile cleanup budget")
        if draft.stdout_bytes > profile.stdout_cap_bytes:
            violations.append("stdout bytes exceed the profile cap")
        if draft.stderr_bytes > profile.stderr_cap_bytes:
            violations.append("stderr bytes exceed the profile cap")
        if draft.stdout_bytes + draft.stderr_bytes > profile.combined_cap_bytes:
            violations.append("combined output bytes exceed the profile cap")
        for label, value in (
            ("stdout_digest", draft.stdout_digest),
            ("stderr_digest", draft.stderr_digest),
        ):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                violations.append(f"{label} must be 64 lowercase hex")
        if len(draft.stdout_projection) > profile.rendered_chars:
            violations.append("stdout projection exceeds rendered chars")
        if len(draft.stderr_projection) > profile.rendered_chars:
            violations.append("stderr projection exceeds rendered chars")
        if violations:
            raise ValueError(
                "process draft violated closed bounds: " + "; ".join(violations)
            )

    def _mint_process_receipt(
        self,
        intent: ExecutionIntent,
        spec: ToolSpec,
        draft: ProcessExecutionDraftV1,
    ) -> ProcessReceiptV1:
        binding = intent.safety_binding
        lease = intent.process_lease
        if lease is None:
            # F1（P1 review finding 2026-08-16）：pseudo lease receipt（fallback
            # lease_id / use_ordinal=0）删除——无 exact durable lease 不得铸造
            # process receipt。
            raise IntentConflictError(
                "process receipt requires an exact durable lease identity"
            )
        lease_id = lease.lease_id
        lease_digest = lease.lease_digest
        use_ordinal = lease.uses_consumed + 1
        outcome = ProcessOutcome(draft.outcome.value)
        goal_id = intent.goal_id or ""
        goal_revision = intent.goal_revision or 0
        workspace = intent.workspace_identity_digest or ""
        return ProcessReceiptV1.create(
            lease_id=lease_id,
            lease_digest=lease_digest,
            use_ordinal=use_ordinal,
            goal_id=goal_id,
            goal_revision=goal_revision,
            workspace_identity_digest=workspace,
            tool_identity=spec.identity_digest,
            intent_digest=intent.intent_digest,
            executable_digest=binding["executable_digest"],
            argv_digest=binding["argv_digest"],
            cwd_digest=binding["cwd_digest"],
            resource_profile=binding["resource_profile"],
            environment_policy_digest=binding["environment_policy_digest"],
            execution_authority=spec.execution_authority,
            outcome=outcome,
            exit_code=draft.exit_code,
            signal=draft.signal,
            started_at=str(draft.started_at_monotonic),
            ended_at=str(draft.ended_at_monotonic),
            stdout_digest=draft.stdout_digest,
            stderr_digest=draft.stderr_digest,
            stdout_bytes=draft.stdout_bytes,
            stderr_bytes=draft.stderr_bytes,
            stdout_truncated=draft.stdout_truncated,
            stderr_truncated=draft.stderr_truncated,
            group_cleanup_claim="reaped" if draft.group_reaped else "unconfirmed",
            command_fingerprint=str(binding["command_fingerprint"]),
            duration_seconds=draft.duration_seconds,
        )

    @staticmethod
    def _error(tool_call_id: str, code: str, message: str) -> ToolResult:
        # prepare 阶段的拒绝（unknown_tool/invalid_arguments/policy_denied/approval_mismatch/
        # binding/policy_failure）都发生在 callable 调用之前，是 known-not-executed（A16/A18/R27）。
        return ToolResult(
            tool_call_id=tool_call_id,
            content=message,
            is_error=True,
            executed=False,
            metadata={"code": code},
        )


def _optional_string(value: JSONValue | None) -> str | None:
    return value if isinstance(value, str) else None


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_output(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, int | float | bool | list | dict):
        return _canonical_json(value)
    raise TypeError(f"unsupported tool output type: {type(value).__name__}")


def _validate_arguments(
    arguments: dict[str, JSONValue],
    schema: dict[str, JSONValue],
) -> tuple[dict[str, JSONValue], str | None]:
    if schema.get("type") != "object":
        return {}, "Tool schema root must be an object."
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        return {}, "Tool schema is malformed."
    if any(not isinstance(name, str) for name in required):
        return {}, "Tool schema required keys are malformed."
    missing = [name for name in required if name not in arguments]
    if missing:
        return {}, f"Missing required arguments: {', '.join(missing)}"
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments).difference(properties))
        if extra:
            return {}, f"Unexpected arguments: {', '.join(extra)}"
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if isinstance(property_schema, dict):
            expected = property_schema.get("type")
            if isinstance(expected, str) and not _matches_json_type(value, expected):
                return {}, f"Argument {name} must be {expected}."
    try:
        normalized = json.loads(_canonical_json(arguments))
    except (TypeError, ValueError):
        return {}, "Arguments must be JSON-compatible."
    return normalized, None


def _matches_json_type(value: JSONValue, expected: str) -> bool:
    checks = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, int | float) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
        "null": lambda item: item is None,
    }
    check = checks.get(expected)
    return True if check is None else check(value)

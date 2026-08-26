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
    CitationManifestV1,
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
    SideEffectClass,
    SourceAuthorityBinding,
    SourceReceiptV1,
    ToolCall,
    ToolDefinition,
    ToolExecutionOutput,
    ToolPreparation,
    ToolPrepareContext,
    ToolResult,
    ToolSpec,
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


class KernelToolRuntime:
    def __init__(
        self,
        registrations: tuple[RegisteredTool, ...],
        *,
        policy: ToolPolicy | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for registration in registrations:
            if registration.spec.name in self._tools:
                raise ValueError(f"duplicate tool registration: {registration.spec.name}")
            self._tools[registration.spec.name] = registration
        self._default_policy = policy or DefaultToolPolicy()
        self._invoked_keys: set[str] = set()
        self._clock = clock or _default_utc_now

    def _policy_for(self, registration: RegisteredTool) -> ToolPolicy:
        # 每个 registration 可绑定自己的 policy identity；未绑定则回退到 runtime 默认策略。
        # 不按工具名路由。
        return registration.policy or self._default_policy

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(registration.spec.definition() for registration in self._tools.values())

    def prepare(
        self,
        call: ToolCall,
        context: ToolPrepareContext,
        approval: ApprovalGrant | None = None,
    ) -> ToolPreparation:
        registration = self._tools.get(call.name)
        if registration is None:
            return self._error(call.tool_call_id, "unknown_tool", "Unknown tool requested.")

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

        if (
            call.name == "write_file"
            and registration.spec.side_effect is SideEffectClass.WRITE
            and isinstance(arguments.get("path"), str)
            and arguments["path"].endswith(".citations.json")
        ):
            canonical_manifest = self._canonical_citation_sidecar_content(
                call.name,
                arguments,
                context,
            )
            if canonical_manifest is None:
                exact_pairs = "; ".join(
                    f"{source_ref} -> {source_id}"
                    for source_ref, source_id in context.citable_citation_sources
                ) or "none"
                return self._error(
                    call.tool_call_id,
                    "citation_manifest_required",
                    (
                        "Do not hand-write this sidecar. Follow these exact steps in order: "
                        "(1) read_file the artifact you just wrote (for example "
                        "research.md) so its exact content digest enters this run; "
                        "(2) call build_citation_manifest with the artifact path, the "
                        "exact artifact content you read back, and one citation pair "
                        "chosen from these exact citable pairs: "
                        f"{exact_pairs}; (3) write_file the sidecar by copying that "
                        "build_citation_manifest ToolResult byte-for-byte as content — "
                        "one transport-added final newline is accepted and removed. Any "
                        "other JSON is rejected before the effect."
                    ),
                )
            arguments = dict(arguments)
            arguments["content"] = canonical_manifest

        if registration.spec.safety_policy.get("kind") == "citation_manifest_builder":
            if not context.citation_manifest_allowed:
                return self._error(
                    call.tool_call_id,
                    "citation_manifest_not_required",
                    (
                        "build_citation_manifest is available only when the active Goal "
                        "explicitly targets a .citations.json sidecar. Do not build a "
                        "manifest for this Goal; after the required file read-back, use "
                        "completion_claim with the advertised evidence refs."
                    ),
                )

            artifact_path = arguments.get("artifact_path")
            if artifact_path not in context.citation_artifact_paths:
                allowed_paths = ", ".join(context.citation_artifact_paths) or "none"
                return self._error(
                    call.tool_call_id,
                    "citation_artifact_not_authorized",
                    (
                        "The citation manifest must describe a non-sidecar artifact target "
                        f"from the active Goal. Allowed artifact_path values: {allowed_paths}. "
                        "Read that artifact and pass its exact content; never cite the "
                        ".citations.json sidecar itself."
                    ),
                )
            if context.goal_id is not None and (
                arguments.get("goal_id") != context.goal_id
                or arguments.get("goal_revision") != context.goal_revision
            ):
                return self._error(
                    call.tool_call_id,
                    "citation_goal_identity_mismatch",
                    (
                        "The citation manifest must copy goal_id and goal_revision exactly "
                        "from the current trusted_goal block. Do not use an earlier revision "
                        "or another identity; rebuild the manifest with the current "
                        "Runtime-owned identity and retry."
                    ),
                )
            citations = arguments.get("citations")
            requested_refs = (
                tuple(
                    citation.get("source_ref")
                    for citation in citations
                    if isinstance(citation, dict)
                )
                if isinstance(citations, list)
                else ()
            )
            requested_pairs = (
                tuple(
                    (citation.get("source_ref"), citation.get("source_id"))
                    for citation in citations
                    if isinstance(citation, dict)
                )
                if isinstance(citations, list)
                else ()
            )
            allowed_pairs = set(context.citable_citation_sources)
            if (
                not requested_refs
                or len(requested_refs) != len(citations)
                or len(requested_pairs) != len(citations)
                or any(pair not in allowed_pairs for pair in requested_pairs)
            ):
                exact_pairs = "; ".join(
                    f"{source_ref} -> {source_id}"
                    for source_ref, source_id in context.citable_citation_sources
                ) or "none"
                return self._error(
                    call.tool_call_id,
                    "citation_source_not_citable",
                    (
                        "The only permitted citations are Runtime-verified non-truncated "
                        "source_ref/source_id pairs from the active Goal. Copy one of these "
                        f"exact pairs: {exact_pairs}. Remove denied citations; fetch another "
                        "complete source only when this list is empty; then rebuild the "
                        "manifest and rewrite its sidecar."
                    ),
                )
            markers = tuple(
                citation.get("marker")
                for citation in citations
                if isinstance(citation, dict)
            )
            if (
                len(set(requested_pairs)) != len(requested_pairs)
                or len(set(markers)) != len(markers)
            ):
                return self._error(
                    call.tool_call_id,
                    "citation_entries_not_one_to_one",
                    (
                        "Citation manifest entries must be one-to-one. Use each exact source "
                        "pair once with one unique bracketed marker. If the same source "
                        "supports multiple statements, reuse its one marker in the artifact "
                        "instead of duplicating the manifest entry; then rebuild the sidecar."
                    ),
                )

        source_authority_required = (
            registration.spec.safety_policy.get("source_authority_required") is True
        )
        requested_source_ref = arguments.get("source_ref")
        if source_authority_required and (
            context.source_authority is None
            or requested_source_ref not in context.web_fetch_source_refs
        ):
            exact_refs = ", ".join(context.web_fetch_source_refs) or "none"
            return self._error(
                call.tool_call_id,
                "source_authority_required",
                (
                    "This tool requires a Runtime-verified, currently unattempted Web "
                    f"Search source reference. Exact permitted refs: {exact_refs}. Copy "
                    "one unchanged from FIRST_AGENT_RUNTIME_WEB_FETCH_REFS; do not use "
                    "a web_extracted_content or citation ref."
                ),
            )
        try:
            binding = self._prepare_binding(
                registration,
                arguments,
                source_authority=context.source_authority,
            )
            _canonical_json(binding)
        except Exception:
            if registration.spec.safety_policy.get("kind") == "citation_manifest_builder":
                return self._error(
                    call.tool_call_id,
                    "citation_manifest_invalid",
                    (
                        "The citation manifest arguments are structurally invalid. Use the "
                        "current trusted_goal identity, exact artifact read-back text, one "
                        "unique bracketed marker that occurs in that text, and each "
                        "Runtime-advertised source_ref/source_id pair at most once. No effect "
                        "occurred; correct the arguments and retry."
                    ),
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

        intent = self._make_intent(
            call,
            context,
            registration.spec,
            arguments,
            binding,
            self._policy_for(registration).identity,
            process_lease=process_lease,
        )
        if decision is PolicyDecision.REQUIRE_APPROVAL:
            request = self._approval_request(intent, registration.spec, context)
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
    def _canonical_citation_sidecar_content(
        tool_name: str,
        arguments: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> str | None:
        path = arguments.get("path")
        content = arguments.get("content")
        if (
            tool_name != "write_file"
            or not context.citation_manifest_allowed
            or path not in context.citation_sidecar_paths
            or not isinstance(content, str)
        ):
            return None
        canonical = content[:-1] if content.endswith("\n") else content
        if (
            hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            not in context.citation_manifest_content_digests
        ):
            return None
        try:
            manifest = CitationManifestV1.from_json(canonical)
        except ValueError:
            return None
        if (
            manifest.goal_id != context.goal_id
            or manifest.goal_revision != context.goal_revision
            or manifest.artifact_path not in context.citation_artifact_paths
        ):
            return None
        return canonical

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

        current_binding = self._prepare_binding(
            registration,
            intent.arguments,
            source_authority=intent.source_authority,
        )
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

        self._invoked_keys.add(intent.idempotency_key)
        try:
            raw_result = registration.func(intent)
            if isinstance(raw_result, ProcessExecutionDraftV1):
                return self._process_outcome(intent, registration.spec, raw_result)
            if registration.spec.source_kinds:
                return self._source_result(intent, registration.spec, raw_result)
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
    ) -> ExecutionIntent:
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
        )
        return replace(
            intent,
            intent_digest=self._intent_digest(intent),
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
            }
        )

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
    def _source_result(
        intent: ExecutionIntent,
        spec: ToolSpec,
        raw_result: object,
    ) -> ToolResult:
        if not isinstance(raw_result, ToolExecutionOutput):
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool returned an invalid output contract.",
                is_error=True,
                executed=True,
                metadata={"code": "source_output_required"},
            )
        if len(raw_result.content) > spec.output_limit_chars:
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool output exceeded the configured limit.",
                is_error=True,
                executed=True,
                metadata={"code": "source_output_oversized"},
            )
        allowed_metadata = spec.safety_policy.get("source_metadata_keys", [])
        if not isinstance(allowed_metadata, list) or any(
            not isinstance(key, str) for key in allowed_metadata
        ):
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool metadata policy is malformed.",
                is_error=True,
                executed=True,
                metadata={"code": "source_metadata_policy_invalid"},
            )
        if set(raw_result.metadata) - set(allowed_metadata):
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool returned unauthorized metadata.",
                is_error=True,
                executed=True,
                metadata={"code": "source_metadata_invalid"},
            )
        metadata_bytes = _canonical_json(raw_result.metadata).encode("utf-8")
        if len(metadata_bytes) > min(spec.output_limit_chars, 8_192):
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool metadata exceeded the configured limit.",
                is_error=True,
                executed=True,
                metadata={"code": "source_metadata_oversized"},
            )
        if len(raw_result.source_receipts) > 16:
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Source tool returned too many receipts.",
                is_error=True,
                executed=True,
                metadata={"code": "source_receipts_oversized"},
            )
        receipts: list[SourceReceiptV1] = []
        for draft in raw_result.source_receipts:
            if draft.source_kind not in spec.source_kinds:
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content="Source tool returned an unauthorized source kind.",
                    is_error=True,
                    executed=True,
                    metadata={"code": "source_kind_invalid"},
                )
            bounded_strings = (
                draft.origin_locator,
                draft.observed_at,
                draft.title or "",
                draft.content,
            )
            if any(len(value) > spec.output_limit_chars for value in bounded_strings):
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content="Source receipt draft exceeded the configured limit.",
                    is_error=True,
                    executed=True,
                    metadata={"code": "source_receipt_oversized"},
                )
            receipts.append(SourceReceiptV1.create(draft, intent))
        metadata = {
            **raw_result.metadata,
            "tool_identity": spec.identity_digest,
            "source_receipts": [
                {
                    **asdict(receipt),
                    "source_kind": receipt.source_kind.value,
                }
                for receipt in receipts
            ],
            "data_classes": sorted({receipt.data_class for receipt in receipts}),
            "source_refs": [
                {
                    "source_ref": f"source-ref:v1:{receipt.receipt_digest}",
                    "receipt_digest": receipt.receipt_digest,
                }
                for receipt in receipts
            ],
            "truncated": any(receipt.truncated for receipt in receipts),
        }
        return ToolResult(
            tool_call_id=intent.tool_call_id,
            content=raw_result.content,
            is_error=raw_result.is_error,
            executed=raw_result.executed,
            metadata=metadata,
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

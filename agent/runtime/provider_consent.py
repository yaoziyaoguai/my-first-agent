"""会话级外发许可与可信来源边界的唯一窄共享纯逻辑。

本模块只做投影/比较，不推进循环、不调用 provider/tool、不保存 checkpoint。
Runtime、ContextManager、CLI 视图共享同一判断，避免显示、授予和实际发送
各自复制一套范围规则。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from agent.runtime.contracts import (
    CONSENT_MAX_USES,
    CONSENT_PROFILE_ROUTINE,
    CONSENT_PROFILE_WORKSPACE_COMMAND,
    CONSENT_PROFILE_WORKSPACE_READ,
    CONSENT_TTL_SECONDS,
    NO_WORKSPACE_IDENTITY,
    ROUTINE_DATA_CLASSES,
    WORKSPACE_COMMAND_DATA_CLASSES,
    WORKSPACE_READ_DATA_CLASSES,
    ConversationState,
    FactKind,
    ProviderConsentGrantStatus,
    ProviderConsentGrantV1,
    ProviderConsentScopeV1,
    ProviderConsentToolBindingV1,
    ProviderDescriptor,
    ProviderDisclosureReceipt,
    ProviderDisclosureReceiptV2,
    ProviderDisclosureRequest,
    ProviderDisclosureRequestV2,
    ProviderDisclosureSourceV1,
    ToolDefinition,
    canonical_json_digest,
)

# control schema 的结构身份只绑定闭合结构版本，不绑定当前 Goal 值、可用
# control 子集或 action seq；合法状态转换不能因此被误判为新增结构能力。
CONTROL_SCHEMA_STRUCTURE_DIGEST = canonical_json_digest(
    {
        "profile": "my-first-agent/reserved-control-schema",
        "version": 1,
        "name": "first_agent_control_v1",
    }
)

ROUTINE_DATA_CLASS_SET = frozenset(ROUTINE_DATA_CLASSES)


WORKSPACE_PROOF_DATA_CLASS_SET = frozenset({"workspace_excerpt", "command_output"})
WORKSPACE_PROOF_PROFILES = (
    CONSENT_PROFILE_WORKSPACE_READ,
    CONSENT_PROFILE_WORKSPACE_COMMAND,
)


def workspace_read_classes_covered(
    data_classes: tuple[str, ...],
    sources: tuple[ProviderDisclosureSourceV1, ...],
) -> bool:
    """workspace 许可的准入判据：非常规部分全部是 proof-backed 可复用来源。

    只认 reusable 来源（workspace_excerpt / command_output 由 Runtime 持久化
    file-source proof 铸造，绑定 goal/revision/workspace/内容 digest）；混入
    任何其他非常规类（tool_results 等）或不可复用来源都退回逐次披露。
    """

    nonroutine = set(data_classes) - ROUTINE_DATA_CLASS_SET
    return (
        bool(sources)
        and bool(nonroutine)
        and nonroutine <= WORKSPACE_PROOF_DATA_CLASS_SET
        and all(source.reusable for source in sources)
    )


def workspace_consent_profile(data_classes: tuple[str, ...]) -> str:
    """按本次 scope 选择要铸造的许可 profile：纯读仍铸 v1，含命令输出才升级。

    调用方须先通过 workspace_read_classes_covered；本函数只做 profile 选择，
    不让 v1 许可静默覆盖命令输出。
    """

    if "command_output" in set(data_classes):
        return CONSENT_PROFILE_WORKSPACE_COMMAND
    return CONSENT_PROFILE_WORKSPACE_READ


def workspace_consent_scope_label(profile: str) -> str:
    """状态视图的短 scope 标签；未知 profile 按最窄的 routine 显示。"""

    return {
        CONSENT_PROFILE_WORKSPACE_READ: "read+routine",
        CONSENT_PROFILE_WORKSPACE_COMMAND: "read+command+routine",
    }.get(profile, "routine")


@dataclass(frozen=True, slots=True)
class ProviderDispatchGateV1:
    """一次派发前的只读许可判断；Runtime 据此决定暂停或扣账。"""

    request: ProviderDisclosureRequest | ProviderDisclosureRequestV2 | None
    admitted: bool
    grant_use: bool
    consume_receipt: bool
    reason: str
    grant_invalidated: bool = False
    # oracle r2 §F-1（B3）：例外首用时必须在同一 transition 把单次票据标记
    # 已消费（幂等：已消费不报错），防止 grant 失效后 exact_receipt 复用旧 y。
    mark_receipt_consumed: bool = False


def tool_bindings_for(
    tools: tuple[ToolDefinition, ...],
) -> tuple[ProviderConsentToolBindingV1, ...]:
    bindings = tuple(
        sorted(
            (
                ProviderConsentToolBindingV1(
                    name=tool.name,
                    identity_digest=canonical_json_digest(
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "input_schema": tool.input_schema,
                            "side_effect": tool.side_effect.value,
                            "egress": tool.egress.value,
                            "execution_authority": tool.execution_authority.value,
                        }
                    ),
                )
                for tool in tools
            ),
            key=lambda item: item.name,
        )
    )
    if len({binding.name for binding in bindings}) != len(bindings):
        raise ValueError("consent tool definitions must be unique by name")
    return bindings


def parse_zoned_time(value: str) -> datetime:
    """严格解析带时区 RFC3339；naive/损坏值一律拒绝。"""

    if not isinstance(value, str) or not value:
        raise ValueError("time value must be zoned RFC3339")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("time value must be zoned RFC3339") from error
    if parsed.tzinfo is None:
        raise ValueError("time value must be zoned RFC3339")
    return parsed.astimezone(UTC)


def grant_identity_matches(
    grant: ProviderConsentGrantV1,
    *,
    descriptor: ProviderDescriptor,
    workspace_identity_digest: str,
) -> bool:
    return (
        grant.provider_descriptor_digest == descriptor.identity_digest
        and grant.canonical_destination == descriptor.canonical_destination
        and grant.model == descriptor.model
        and grant.workspace_identity_digest == workspace_identity_digest
    )


def grant_availability(
    grant: ProviderConsentGrantV1,
    *,
    now: str,
) -> str | None:
    """返回不可自动使用的原因；None 表示 ACTIVE 且时间内仍有额度。"""

    if grant.status is not ProviderConsentGrantStatus.ACTIVE:
        return grant.status.value
    issued = parse_zoned_time(grant.issued_at)
    expires = parse_zoned_time(grant.expires_at)
    current = parse_zoned_time(now)
    if expires - issued != timedelta(seconds=CONSENT_TTL_SECONDS):
        return "invalid_lifetime"
    if current < issued:
        return "not_yet_valid"
    if current >= expires:
        return "expired"
    if grant.uses_consumed >= CONSENT_MAX_USES:
        return "exhausted"
    return None


def _grant_structure_pinned(
    grant: ProviderConsentGrantV1,
    *,
    control_schema_digest: str,
    tool_bindings: tuple[ProviderConsentToolBindingV1, ...],
) -> bool:
    """结构钉死面单源判定：control schema digest 与全部工具绑定都在 grant
    批准集内才视为未漂移。gate 放行（``_grant_covers_structure``）与渲染
    解释（``grant_structure_drifted``）共用此规则，两侧不得再各持一份公式
    （2026-10-25 merge gate LOW-1）。"""

    approved = {
        binding.name: binding.identity_digest for binding in grant.tool_bindings
    }
    if any(
        approved.get(binding.name) != binding.identity_digest
        for binding in tool_bindings
    ):
        return False
    return control_schema_digest == grant.control_schema_digest


def grant_structure_drifted(
    grant: ProviderConsentGrantV1,
    request: ProviderDisclosureRequestV2,
) -> bool:
    """活动 grant 的结构钉死面与请求结构是否漂移（渲染解释的单源谓词）。

    判定核心在 ``_grant_structure_pinned``：control schema digest 或任一请求
    工具绑定不在 grant 批准集内即漂移。gate 用同一核心决定放行，渲染用它
    解释"活动许可为何不覆盖本请求"——两处不得各持一份判定。
    """
    return not _grant_structure_pinned(
        grant,
        control_schema_digest=request.control_schema_digest,
        tool_bindings=request.tool_bindings,
    )


def _grant_covers_structure(
    grant: ProviderConsentGrantV1,
    scope: ProviderConsentScopeV1,
    *,
    exception_classes: frozenset[str] = frozenset(),
) -> bool:
    if not _grant_structure_pinned(
        grant,
        control_schema_digest=scope.control_schema_digest,
        tool_bindings=scope.tool_bindings,
    ):
        return False
    return (set(scope.data_classes) - exception_classes).issubset(
        grant.allowed_data_classes
    )


def _nonroutine_classes(scope: ProviderConsentScopeV1) -> set[str]:
    return set(scope.data_classes) - ROUTINE_DATA_CLASS_SET


def _scope_digest(
    *,
    descriptor: ProviderDescriptor,
    scope: ProviderConsentScopeV1,
) -> str:
    return canonical_json_digest(
        {
            "profile": CONSENT_PROFILE_ROUTINE,
            "provider_descriptor_digest": descriptor.identity_digest,
            "canonical_destination": descriptor.canonical_destination,
            "model": descriptor.model,
            "workspace_identity_digest": scope.workspace_identity_digest,
            "goal_id": scope.goal_id,
            "goal_revision": scope.goal_revision,
            "sources": [source.identity_payload() for source in scope.sources],
        }
    )


def build_disclosure_request_v2(
    *,
    descriptor: ProviderDescriptor,
    scope: ProviderConsentScopeV1,
    grant: ProviderConsentGrantV1 | None,
    purpose: str,
    run_id: str,
) -> ProviderDisclosureRequestV2:
    scope_digest = _scope_digest(descriptor=descriptor, scope=scope)
    payload = {
        "disclosure_id": f"provider:{descriptor.identity_digest[:16]}:v2",
        "provider_descriptor_digest": descriptor.identity_digest,
        "canonical_destination": descriptor.canonical_destination,
        "model": descriptor.model,
        "workspace_identity_digest": scope.workspace_identity_digest,
        "data_classes": list(scope.data_classes),
        "control_schema_digest": scope.control_schema_digest,
        "grant_id": grant.grant_id if grant is not None else None,
        "grant_eligible": scope.routine_compatible,
        "purpose": purpose,
        "run_id": run_id,
        "goal_id": scope.goal_id,
        "goal_revision": scope.goal_revision,
    }
    return ProviderDisclosureRequestV2(
        **payload,
        sources=scope.sources,
        tool_bindings=scope.tool_bindings,
        scope_digest=scope_digest,
        request_digest=canonical_json_digest(
            {
                "request_version": 2,
                **payload,
                "sources": [
                    source.identity_payload() for source in scope.sources
                ],
                "tool_bindings": [
                    {
                        "name": binding.name,
                        "identity_digest": binding.identity_digest,
                    }
                    for binding in scope.tool_bindings
                ],
            }
        ),
    )


def _legacy_request_matches(
    request: ProviderDisclosureRequest,
    *,
    descriptor: ProviderDescriptor,
    scope: ProviderConsentScopeV1,
) -> bool:
    return (
        request.provider_descriptor_digest == descriptor.identity_digest
        and request.canonical_destination == descriptor.canonical_destination
        and request.model == descriptor.model
        and request.data_classes == scope.data_classes
    )


def _legacy_request(
    *,
    descriptor: ProviderDescriptor,
    scope: ProviderConsentScopeV1,
) -> ProviderDisclosureRequest:
    return ProviderDisclosureRequest.create(
        disclosure_id=f"provider:{descriptor.identity_digest[:16]}",
        provider_descriptor_digest=descriptor.identity_digest,
        canonical_destination=descriptor.canonical_destination,
        model=descriptor.model,
        data_classes=scope.data_classes,
    )


def _no_new_user_input_since(
    state: ConversationState,
    receipt: ProviderDisclosureReceiptV2,
) -> bool:
    """S5 判界：ack 之后出现新用户消息，待发授权即失配。

    新用户消息会产生 action seq 更大的 USER_MESSAGE fact；孤儿 pending 跨
    重启 resume（run_id 重标为 resume-N）不是新内容，不得因此重问。
    """

    for fact in state.facts:
        if fact.kind is not FactKind.USER_MESSAGE:
            continue
        parts = fact.fact_id.split(":")
        if len(parts) < 2:
            continue
        try:
            seq = int(parts[1])
        except ValueError:
            continue
        if seq > receipt.acknowledged_action_seq:
            return False
    return True


def _same_pending_unit(
    candidate: ProviderDisclosureRequestV2,
    previous: ProviderDisclosureRequestV2,
) -> bool:
    """oracle r2 §F-1：单次 y 只绑定原 pending 派发单元的结构身份。

    工具定义/control schema 变化必须重新披露（S1/S4）；目的变化
    （normal/compaction）是不同待发单元。run_id 允许因孤儿 resume 重标而
    变化——新内容判界由 `_no_new_user_input_since` 承担（S5）。
    """

    return (
        candidate.purpose == previous.purpose
        and candidate.tool_bindings == previous.tool_bindings
        and candidate.control_schema_digest == previous.control_schema_digest
    )


def _exact_receipt_matches(
    *,
    state: ConversationState,
    candidate: ProviderDisclosureRequestV2,
    previous: object,
    receipt: object,
) -> bool:
    """用户刚刚明确批准的同一份待发内容可直接发送（单次票据）。

    SPEC S5：授权本身新增的纯控制回执不能制造无限重问。y 之后重建的
    candidate 可能因 ``control_receipts`` 类别加入或孤儿 resume 的 run_id
    重标而 request_digest 漂移；只要仍是同一 pending 单元（同 purpose/
    工具定义/control schema）、ack 之后没有新用户消息、sources/scope 完全
    一致、增量仅为授权自身的 control_receipts，就仍视为同一份已批准的
    待发内容。非常规来源仍严格相等，不扩大范围。
    """

    if not isinstance(previous, ProviderDisclosureRequestV2):
        return False
    if not isinstance(receipt, ProviderDisclosureReceiptV2):
        return False
    if receipt.request_digest != previous.request_digest:
        return False
    # oracle r3 F3：新用户消息判界先于 digest 相等捷径——digest 不含消息
    # 内容，相同 digest 不能成为绕过 S5 失配条件的理由。
    if not _no_new_user_input_since(state, receipt):
        return False
    if receipt.request_digest == candidate.request_digest:
        return True
    return (
        _same_pending_unit(candidate, previous)
        and candidate.scope_digest == previous.scope_digest
        and candidate.sources == previous.sources
        and set(candidate.data_classes) - set(previous.data_classes)
        <= {"control_receipts"}
    )


def _exact_routine_receipt_covers(
    *,
    state: ConversationState,
    candidate: ProviderDisclosureRequestV2,
    previous: object,
    receipt: object,
) -> bool:
    """同一常规 displayed scope 的单次 y 可跨计划内 resume 使用。

    孤儿 resume 的 run_id 重标会改变 request_digest，但不改变用户看到的
    常规范围；单次票据仍只消费一次，不转成 grant，也不覆盖任何非常规来源。
    SPEC S5：单次 y 只豁免授权自身新增的 control_receipts 簿记；
    conversation_history 等实质新常规内容属于 `s`（会话许可）的授权范围，
    不得经本桥静默扩大（oracle r3 F1）。非常规来源仍由 sources 严格相等
    约束；新用户消息由 `_no_new_user_input_since` 判界；purpose/工具定义
    变化仍拒绝。
    """

    if not (
        candidate.grant_eligible
        and not candidate.sources
        and isinstance(previous, ProviderDisclosureRequestV2)
        and isinstance(receipt, ProviderDisclosureReceiptV2)
        and receipt.consumed_at is None
        # r2 B2 同款纵深防御：receipt 必须绑定 previous 这份请求（状态层
        # 构造不变量已拒绝错配对，此处防止绕过状态构造的直接调用）。
        and receipt.request_digest == previous.request_digest
        and previous.scope_digest == candidate.scope_digest
        and previous.sources == candidate.sources
        and _same_pending_unit(candidate, previous)
        and _no_new_user_input_since(state, receipt)
    ):
        return False
    # oracle r3 F1 / SPEC S5：单次 y 只豁免授权自身的 control_receipts 簿记；
    # conversation_history 等实质新常规内容必须重新决定——覆盖常规范围是
    # `s`（会话许可）的职责，不允许经单次票据静默扩大。
    return set(previous.data_classes) <= set(candidate.data_classes) <= (
        set(previous.data_classes) | {"control_receipts"}
    )


def _exception_is_covered(
    *,
    candidate: ProviderDisclosureRequestV2,
    state: ConversationState,
    grant: ProviderConsentGrantV1,
    scope: ProviderConsentScopeV1,
) -> bool:
    previous = state.provider_disclosure_request
    receipt = state.provider_disclosure_receipt
    if (
        not isinstance(previous, ProviderDisclosureRequestV2)
        or not isinstance(receipt, ProviderDisclosureReceiptV2)
        # oracle r2 B2：receipt 必须确实批准过 previous 这份请求。有效
        # ConversationState 的构造不变量已拒绝错配对，此处为 helper 层的
        # 纵深防御（票据消费与否不影响例外识别——消费过的票据仍是
        # "用户同意过该来源边界"的历史证明）。
        or receipt.request_digest != previous.request_digest
        or previous.grant_id != grant.grant_id
        or previous.scope_digest != candidate.scope_digest
        or previous.sources != candidate.sources
    ):
        return False
    if not candidate.sources or any(not source.reusable for source in candidate.sources):
        return False
    nonroutine = _nonroutine_classes(scope)
    source_classes = {source.data_class for source in candidate.sources}
    if nonroutine != source_classes:
        return False
    # SPEC S5：例外路径只要求常规部分被 grant 结构性覆盖；非常规部分已由
    # 上方"与最后一次明确同意的可信来源边界完全相同"约束。若在这里要求
    # 全类子集，文件来源例外永远无法成立，A→B→A→B 的复用合同被破坏。
    return _grant_covers_structure(
        grant, scope, exception_classes=frozenset(nonroutine)
    )


def evaluate_provider_dispatch(
    *,
    state: ConversationState,
    descriptor: ProviderDescriptor | None,
    scope: ProviderConsentScopeV1 | None,
    now: str,
    purpose: str,
    run_id: str,
) -> ProviderDispatchGateV1:
    """判断本次 provider 派发是否已有有效许可；不修改 state。"""

    if descriptor is None or not descriptor.remote:
        return ProviderDispatchGateV1(
            request=None,
            admitted=True,
            grant_use=False,
            consume_receipt=False,
            reason="not_remote",
        )
    if scope is None:
        return ProviderDispatchGateV1(
            request=None,
            admitted=False,
            grant_use=False,
            consume_receipt=False,
            reason="consent_scope_missing",
        )

    grant = state.provider_consent_grant
    pending = state.provider_disclosure_request
    # 旧 checkpoint 的 pending legacy request 保持旧精确语义；只有在没有
    # 可继续的 legacy pending 时才进入 v2，不把旧回执解释成范围许可。
    legacy_mode = (
        grant is None
        and isinstance(pending, ProviderDisclosureRequest)
        and _legacy_request_matches(pending, descriptor=descriptor, scope=scope)
    )
    if legacy_mode:
        candidate: ProviderDisclosureRequest | ProviderDisclosureRequestV2 = pending
    else:
        candidate = build_disclosure_request_v2(
            descriptor=descriptor,
            scope=scope,
            grant=grant,
            purpose=purpose,
            run_id=run_id,
        )

    identity_match = grant is None or grant_identity_matches(
        grant,
        descriptor=descriptor,
        workspace_identity_digest=scope.workspace_identity_digest,
    )
    if (
        grant is not None
        and grant.status is ProviderConsentGrantStatus.ACTIVE
        and not identity_match
    ):
        # 只有 ACTIVE grant 的身份漂移才需要落 invalidate fence；已失效的
        # grant 不能再短路判定，否则 ack 回执与新决定在同一 runtime 内永远
        # 无法被使用（SPEC S3：失效是不复活，不是阻塞）。
        return ProviderDispatchGateV1(
            request=candidate,
            admitted=False,
            grant_use=False,
            consume_receipt=False,
            reason="grant_identity_changed",
            grant_invalidated=True,
        )

    availability = grant_availability(grant, now=now) if grant is not None else None
    if grant is not None and availability is None:
        if scope.routine_compatible and _grant_covers_structure(grant, scope):
            return ProviderDispatchGateV1(
                request=candidate,
                admitted=True,
                grant_use=True,
                consume_receipt=False,
                reason="grant_routine",
            )
        if (
            grant.profile in WORKSPACE_PROOF_PROFILES
            and workspace_read_classes_covered(scope.data_classes, scope.sources)
            and _grant_covers_structure(grant, scope)
        ):
            # item 1（2026-10-24）：workspace 许可只放行非常规部分全部为
            # proof-backed 来源的 scope；结构（类别/工具绑定）由 grant 覆盖，
            # 因此 v1 读许可不会覆盖 command_output（2026-10-26 扩展）。
            # 逐次非阻断通知由 Runtime 在扣账后附带（reason 即判别信号）。
            # 同 r2 B3 硬化：在场未消费的单次 y 随 grant 首用一并烧掉，
            # 防 grant 失效后 exact_receipt 额外放行一次。
            pending_receipt = state.provider_disclosure_receipt
            return ProviderDispatchGateV1(
                request=candidate,
                admitted=True,
                grant_use=True,
                consume_receipt=False,
                reason="grant_workspace_read",
                mark_receipt_consumed=(
                    isinstance(pending_receipt, ProviderDisclosureReceiptV2)
                    and pending_receipt.consumed_at is None
                ),
            )
        if isinstance(candidate, ProviderDisclosureRequestV2) and _exception_is_covered(
            candidate=candidate,
            state=state,
            grant=grant,
            scope=scope,
        ):
            return ProviderDispatchGateV1(
                request=candidate,
                admitted=True,
                grant_use=True,
                consume_receipt=False,
                reason="grant_exception",
                # 例外首用即消费单次票据：防止 grant 失效/耗尽后
                # exact_receipt 复用这张旧 y 额外放行一次（oracle r2 B3）。
                mark_receipt_consumed=True,
            )

    receipt = state.provider_disclosure_receipt
    if (
        isinstance(candidate, ProviderDisclosureRequestV2)
        and isinstance(receipt, ProviderDisclosureReceiptV2)
        and receipt.consumed_at is None
        and _exact_receipt_matches(
            state=state,
            candidate=candidate,
            previous=pending,
            receipt=receipt,
        )
    ):
        return ProviderDispatchGateV1(
            request=candidate,
            admitted=True,
            grant_use=False,
            consume_receipt=True,
            reason="exact_receipt",
        )
    if isinstance(candidate, ProviderDisclosureRequestV2) and (
        _exact_routine_receipt_covers(
            state=state,
            candidate=candidate,
            previous=pending,
            receipt=receipt,
        )
    ):
        return ProviderDispatchGateV1(
            request=candidate,
            admitted=True,
            grant_use=False,
            consume_receipt=True,
            reason="exact_routine_scope",
        )
    if (
        isinstance(candidate, ProviderDisclosureRequest)
        and isinstance(receipt, ProviderDisclosureReceipt)
        and receipt.request_digest == candidate.request_digest
    ):
        return ProviderDispatchGateV1(
            request=candidate,
            admitted=True,
            grant_use=False,
            consume_receipt=False,
            reason="legacy_receipt",
        )

    reason = "grant_unavailable" if availability is not None else "decision_required"
    return ProviderDispatchGateV1(
        request=candidate,
        admitted=False,
        grant_use=False,
        consume_receipt=False,
        reason=reason,
    )


def charge_provider_dispatch(
    state: ConversationState,
    gate: ProviderDispatchGateV1,
    *,
    descriptor: ProviderDescriptor,
    scope: ProviderConsentScopeV1,
    purpose: str,
    run_id: str,
    now: str,
) -> ConversationState:
    """在真正调用 provider 前，从同一 durable transition 扣除许可额度。

    oracle r2 A2：扣次前在同一权威 state 上重算 gate 并要求决策一致——
    未批准的 gate、或针对已变化 descriptor/scope/purpose/run 的陈旧 gate
    一律拒绝，不依赖调用方顺序自觉。
    """

    recomputed = evaluate_provider_dispatch(
        state=state,
        descriptor=descriptor,
        scope=scope,
        purpose=purpose,
        run_id=run_id,
        now=now,
    )
    # oracle r4 N1：比较完整决策（含 mark_receipt_consumed），防止调用方
    # 传入与重算不一致的部分匹配 gate 绕过票据消费等副作用。
    if not recomputed.admitted or recomputed != gate:
        raise ValueError(
            "provider dispatch gate is stale or unapproved for this dispatch"
        )
    grant = state.provider_consent_grant
    if gate.grant_use:
        if grant is None or grant_availability(grant, now=now) is not None:
            raise ValueError("provider consent grant is no longer usable")
        state = replace(state, provider_consent_grant=grant.with_use())
    if gate.consume_receipt:
        receipt = state.provider_disclosure_receipt
        if (
            not isinstance(receipt, ProviderDisclosureReceiptV2)
            or receipt.consumed_at is not None
        ):
            raise ValueError("provider disclosure receipt is no longer usable")
        state = replace(state, provider_disclosure_receipt=replace(receipt, consumed_at=now))
    if gate.mark_receipt_consumed:
        receipt = state.provider_disclosure_receipt
        if (
            isinstance(receipt, ProviderDisclosureReceiptV2)
            and receipt.consumed_at is None
        ):
            state = replace(
                state,
                provider_disclosure_receipt=replace(receipt, consumed_at=now),
            )
    return state


def final_dispatch_expiry_check(
    state: ConversationState,
    gate: ProviderDispatchGateV1,
    *,
    now: str,
) -> str | None:
    """Transport 前的窄口径最终重验：只查 grant 时间边界（SPEC S6）。

    使用扣次后的 state（本次消耗的次数不算失效）；第 32 次发送仍允许，
    但已跨过 expires_at 的派发必须拦下重新决策。
    """

    if not gate.grant_use:
        return None
    grant = state.provider_consent_grant
    if grant is None:
        return "grant_missing"
    current = parse_zoned_time(now)
    # SPEC S3：时间倒退早于 issued_at 同样拒绝；已扣的第 32 次不因此失效。
    if current < parse_zoned_time(grant.issued_at):
        return "not_yet_valid"
    if current >= parse_zoned_time(grant.expires_at):
        return "expired"
    return None


def invalidate_provider_consent(state: ConversationState) -> ConversationState:
    grant = state.provider_consent_grant
    if grant is None or grant.status is not ProviderConsentGrantStatus.ACTIVE:
        return state
    return replace(
        state,
        provider_consent_grant=grant.with_status(
            ProviderConsentGrantStatus.INVALIDATED
        ),
        provider_disclosure_request=None,
        provider_disclosure_receipt=None,
    )


def workspace_read_dispatch_notice(
    grant: ProviderConsentGrantV1,
    scope: ProviderConsentScopeV1,
) -> str:
    """r 许可放行一次派发后的逐次非阻断审计通知文案。

    裁决 C（2026-10-24）：静默复用必须伴随逐次可见性——每次放行都告诉
    用户本次重发了多少工作区摘录、额度还剩多少；不打断、不要求决策。
    """

    excerpt_count = sum(
        1
        for source in scope.sources
        if source.data_class in WORKSPACE_PROOF_DATA_CLASS_SET
    )
    left = max(grant.max_uses - grant.uses_consumed, 0)
    return (
        f"read-scope consent: {excerpt_count} verified workspace source(s) "
        f"re-sent to the provider this send; {left} of {grant.max_uses} "
        "model sends left"
    )


def mint_provider_consent_grant(
    *,
    state: ConversationState,
    request: ProviderDisclosureRequestV2,
    action_seq: int,
    now: str,
    profile: str = CONSENT_PROFILE_ROUTINE,
) -> ProviderConsentGrantV1:
    """从已显示的 v2 request 铸造许可；调用方已校验 action/CAS。"""

    if profile not in (
        CONSENT_PROFILE_ROUTINE,
        CONSENT_PROFILE_WORKSPACE_READ,
        CONSENT_PROFILE_WORKSPACE_COMMAND,
    ):
        raise ValueError("provider consent grant profile is unsupported")
    allowed_classes = {
        CONSENT_PROFILE_WORKSPACE_READ: WORKSPACE_READ_DATA_CLASSES,
        CONSENT_PROFILE_WORKSPACE_COMMAND: WORKSPACE_COMMAND_DATA_CLASSES,
    }.get(profile, ROUTINE_DATA_CLASSES)
    issued = parse_zoned_time(now)
    expires = (issued + timedelta(seconds=CONSENT_TTL_SECONDS)).isoformat().replace(
        "+00:00",
        "Z",
    )
    issued_text = issued.isoformat().replace("+00:00", "Z")
    payload = {
        "grant_id": f"provider-consent:{request.request_digest[:16]}:{action_seq}",
        "conversation_id": state.conversation_id,
        "workspace_identity_digest": request.workspace_identity_digest,
        "provider_descriptor_digest": request.provider_descriptor_digest,
        "canonical_destination": request.canonical_destination,
        "model": request.model,
        "profile": profile,
        "allowed_data_classes": list(allowed_classes),
        "control_schema_digest": request.control_schema_digest,
        "disclosure_request_digest": request.request_digest,
        "scope_digest": request.scope_digest,
        "granted_action_seq": action_seq,
        "issued_at": issued_text,
        "expires_at": expires,
        "max_uses": CONSENT_MAX_USES,
        "uses_consumed": 0,
        "status": ProviderConsentGrantStatus.ACTIVE,
    }
    digest_payload = {
        **payload,
        "tool_bindings": [
            {"name": binding.name, "identity_digest": binding.identity_digest}
            for binding in request.tool_bindings
        ],
    }
    return ProviderConsentGrantV1(
        **payload,
        tool_bindings=request.tool_bindings,
        grant_digest=canonical_json_digest(digest_payload),
    )


def no_workspace_identity(workspace_identity_digest: str | None) -> str:
    return workspace_identity_digest or NO_WORKSPACE_IDENTITY

"""S1-A（DU-02/03/04/05）：验证请求新鲜性的单元合同。

- 可信只读 native sandbox 分类（evidence 与 loop 抑制折叠共用同一严格 helper），
  伪造/缺失/投影不符/非 confined/network 非 off 一律不进可信验证集合。
- durable fact fold 的三集合语义：ordinary ∪ native_validation 参与抑制查询；
  写入/process/不可信 sandbox 已执行结果清空 native_validation；A/B 可共存；
  operator 已执行 mutation 同样参与失效；fold 是 facts 的纯函数（重建等价）。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent.runtime.contracts import (
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalPolicy,
    CompletionClaim,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    GoalFrame,
    GoalStatus,
    OutputPolicy,
    ProposedCriterion,
    RecoveryRequest,
    RecoveryResolution,
    ResolveUnknownToolOutcome,
    SandboxReceiptV1,
    SideEffectClass,
    ToolCall,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.evidence import (
    ClosedEvidenceRegistry,
    EvidenceVerificationError,
    trusted_readonly_native_sandbox_success,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import accept_action
from tests.kernel.fakes import CollectingSink

WORKSPACE_DIGEST = "w" * 64
POLICY = "c" * 64
PROFILE = "d" * 64



def _receipt(
    *,
    receipt_id: str = "sandbox-receipt:fresh-1",
    lease_id: str = "sandbox-lease:fresh-1",
    mode: str = "read-only",
    network: str = "off",
    backend: str = "seatbelt",
    enforcement: str = "confined",
    outcome: str = "exited",
    workspace_digest: str = WORKSPACE_DIGEST,
    fingerprint: str = "ab" * 32,
) -> SandboxReceiptV1:
    bypass = mode == "danger-full-access" and network == "full"
    return SandboxReceiptV1.create(
        receipt_id=receipt_id,
        lease_id=lease_id,
        lease_digest="a" * 64,
        candidate_digest="b" * 64,
        goal_id="goal-fresh",
        goal_revision=1,
        workspace_identity_digest=workspace_digest,
        original_command_fingerprint=fingerprint,
        policy_digest=POLICY,
        mode=mode,
        network=network,
        backend=backend,
        enforcement=enforcement,
        profile_digest="" if bypass else PROFILE,
        outcome=outcome,
        draft_digest="e" * 64,
        issued_at="2026-10-09T00:00:00Z",
    )


def _metadata_projection(receipt: SandboxReceiptV1, **extra: object) -> dict:
    metadata = {
        "sandbox_receipt_kind": "native_sandbox_v1",
        "sandbox_receipt": receipt.to_json(),
        "receipt_digest": receipt.receipt_digest,
        "execution_authority": "isolated_sandbox",
        "outcome": receipt.outcome,
        "exit_code": 0,
        "original_command_fingerprint": receipt.original_command_fingerprint,
        "policy_digest": receipt.policy_digest,
        "mode": receipt.mode,
        "network": receipt.network,
        "backend": receipt.backend,
        "enforcement": receipt.enforcement,
        "profile_digest": receipt.profile_digest,
        "lease_id": receipt.lease_id,
    }
    metadata.update(extra)
    return metadata


def _sandbox_fact(
    receipt: SandboxReceiptV1,
    *,
    tool_call_id: str = "validate-a",
    **extra_metadata: object,
) -> ConversationFact:
    return ConversationFact(
        fact_id=f"run:run-fresh:tool-result:{tool_call_id}:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": tool_call_id,
            "text": "ok",
            "is_error": False,
            "executed": True,
            "metadata": _metadata_projection(receipt, **extra_metadata),
        },
    )


def _calls_fact(*calls: tuple[str, str, dict]) -> ConversationFact:
    return ConversationFact(
        fact_id="run:run-fresh:tool-batch:1",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {"tool_call_id": call_id, "name": name, "arguments": arguments}
                for call_id, name, arguments in calls
            ],
        },
    )


def _write_fact(tool_call_id: str = "mutate-1") -> ConversationFact:
    return ConversationFact(
        fact_id=f"run:run-fresh:tool-result:{tool_call_id}:2",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": tool_call_id,
            "text": "written",
            "is_error": False,
            "executed": True,
            "metadata": {
                "tool_name": "write_file",
                "governed_tool_receipt_kind": "governed_tool_v1",
            },
        },
    )


def _runtime() -> AgentRuntime:
    """只用于折叠 helper 的最小 Runtime：不驱动 provider。"""

    specs = (
        ToolSpec(
            name="sandbox_exec",
            version="1",
            description="sandbox",
            input_schema={},
            risk=ToolRisk.HIGH,
            side_effect=SideEffectClass.EXTERNAL,
            output_policy=OutputPolicy.BOUNDED_TEXT,
            approval_policy=ApprovalPolicy.ALWAYS,
            safety_policy={},
            output_limit_chars=100,
            execution_authority=ExecutionAuthorityClass.ISOLATED_SANDBOX,
        ),
        ToolSpec(
            name="write_file",
            version="1",
            description="write",
            input_schema={},
            risk=ToolRisk.HIGH,
            side_effect=SideEffectClass.WRITE,
            output_policy=OutputPolicy.BOUNDED_TEXT,
            approval_policy=ApprovalPolicy.ALWAYS,
            safety_policy={},
            output_limit_chars=100,
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        ),
    )
    from agent.runtime.tools import KernelToolRuntime, RegisteredTool

    def _unused_callable(_intent):  # pragma: no cover - 折叠 helper 不执行工具
        raise AssertionError("fold must not invoke tools")

    registered = tuple(
        RegisteredTool(spec, _unused_callable) for spec in specs
    )
    return AgentRuntime(
        provider=object(),  # type: ignore[arg-type]
        context_manager=None,  # type: ignore[arg-type]
        tool_runtime=KernelToolRuntime(registered),
        checkpoint_store=None,  # type: ignore[arg-type]
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-fresh",
    )


def _state(*facts: ConversationFact) -> ConversationState:
    goal = GoalFrame(
        goal_id="goal-fresh",
        revision=1,
        created_from_fact_ids=("fact-user",),
        workspace_identity_digest=WORKSPACE_DIGEST,
        user_outcome="validate",
        beneficiary="user",
        targets=("artifact.txt",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                "criterion:x",
                "validation passes",
                oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
            ),
        ),
        admitted_criteria=(),
        authority_snapshot="fixed",
        status=GoalStatus.GOAL_READY,
        created_at="2026-10-09T00:00:00Z",
        updated_at="2026-10-09T00:00:00Z",
    )
    user = ConversationFact(
        fact_id="fact-user", kind=FactKind.USER_MESSAGE, content={"text": "run"}
    )
    from agent.runtime.contracts import ActiveRun, ActiveRunStatus, ContinuationPhase

    return ConversationState(
        conversation_id="conversation-fresh",
        facts=(user, *facts),
        goal=goal,
        active_run=ActiveRun(
            run_id="run-fresh",
            status=ActiveRunStatus.RUNNABLE,
            phase=ContinuationPhase.MODEL,
        ),
    )


def test_classifier_accepts_only_strict_readonly_receipts() -> None:
    happy = _receipt()
    assert trusted_readonly_native_sandbox_success(
        _sandbox_fact(happy),
        workspace_identity_digest=WORKSPACE_DIGEST,
    )


def test_classifier_rejects_forged_or_illbound_receipts() -> None:
    # 缺失 receipt。
    missing = _metadata_projection(_receipt())
    missing.pop("sandbox_receipt")
    fact = ConversationFact(
        fact_id="f1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "c",
            "text": "t",
            "is_error": False,
            "executed": True,
            "metadata": missing,
        },
    )
    assert not trusted_readonly_native_sandbox_success(fact)
    # 乱码 receipt。
    assert not trusted_readonly_native_sandbox_success(
        _sandbox_fact(_receipt(), **{"sandbox_receipt": "{not-json"})
    )
    # network 非 off。
    full = _sandbox_fact(_receipt(network="full"))
    assert not trusted_readonly_native_sandbox_success(full)
    # 非 confined（danger+full 原生 bypass）。
    bypass = _sandbox_fact(
        _receipt(
            mode="danger-full-access",
            network="full",
            backend="none",
            enforcement="unconfined",
        )
    )
    assert not trusted_readonly_native_sandbox_success(bypass)
    # 投影不符：metadata receipt_digest 与 receipt 不一致。
    assert not trusted_readonly_native_sandbox_success(
        _sandbox_fact(
            _receipt(),
            **{
                "receipt_digest": "9" * 64,
                "original_command_fingerprint": "9" * 64,
                "policy_digest": "9" * 64,
                "mode": "9",
                "network": "9",
                "backend": "9",
                "enforcement": "9",
                "profile_digest": "9" * 64,
                "outcome": "9",
                "lease_id": "9",
            },
        )
    )
    # fake 标记。
    assert not trusted_readonly_native_sandbox_success(
        _sandbox_fact(_receipt(), fake=True)
    )
    # 非零退出。
    assert not trusted_readonly_native_sandbox_success(
        _sandbox_fact(_receipt(), exit_code=2)
    )
    # 未执行 / 错误结果不进可信分类。
    error_fact = ConversationFact(
        fact_id="f2",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "c2",
            "text": "t",
            "is_error": True,
            "executed": True,
            "metadata": _metadata_projection(_receipt()),
        },
    )
    assert not trusted_readonly_native_sandbox_success(error_fact)
    # workspace 绑定不一致。
    assert not trusted_readonly_native_sandbox_success(
        _sandbox_fact(_receipt(workspace_digest="z" * 64)),
        workspace_identity_digest=WORKSPACE_DIGEST,
    )


def test_fold_coexists_validations_and_releases_after_write() -> None:
    runtime = _runtime()
    receipt_a = _receipt(receipt_id="sandbox-receipt:a", lease_id="lease:a")
    receipt_b = _receipt(
        receipt_id="sandbox-receipt:b",
        lease_id="lease:b",
        fingerprint="cd" * 32,
    )
    facts = (
        _calls_fact(
            ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ("validate-b", "sandbox_exec", {"executable": "./check-b"}),
            ("mutate-1", "write_file", {"path": "notes.md"}),
        ),
        _sandbox_fact(receipt_a, tool_call_id="validate-a"),
        _sandbox_fact(receipt_b, tool_call_id="validate-b"),
    )
    ordinary, observations, native_validation = (
        runtime._successful_product_request_inventory(_state(*facts))
    )
    # A/B 共存于 native_validation；ordinary 不含 sandbox 验证成功。
    assert len(native_validation) == 2, native_validation
    assert not ordinary, ordinary
    assert not observations
    # 抑制查询 = ordinary ∪ native_validation：未变输入上的同参数请求仍被抑制。
    suppressed_scope = ordinary | native_validation
    assert len(suppressed_scope) == 2
    # 真实写入后：native_validation 清空 → 同参数复测可执行；写入自身的成功
    # 仍在 ordinary（不因本项被无条件解禁）。
    written = facts + (_write_fact(),)
    ordinary2, observations2, native2 = (
        runtime._successful_product_request_inventory(_state(*written))
    )
    assert native2 == set()
    assert len(ordinary2) == 1, ordinary2
    assert observations2 == set()


def test_fold_is_a_pure_function_of_durable_facts() -> None:
    runtime = _runtime()
    receipt_a = _receipt(receipt_id="sandbox-receipt:a", lease_id="lease:a")
    facts = (
        _calls_fact(
            ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ("mutate-1", "write_file", {"path": "notes.md"}),
        ),
        _sandbox_fact(receipt_a, tool_call_id="validate-a"),
        _write_fact(),
    )
    state = _state(*facts)
    first = runtime._successful_product_request_inventory(state)
    second = runtime._successful_product_request_inventory(state)
    assert first == second
    # 另一个 Runtime 实例从同一 durable facts 重建得到同一结论（reopen 等价）。
    other = _runtime()
    assert other._successful_product_request_inventory(state) == first


def test_fold_untrusted_sandbox_result_does_not_earn_credit() -> None:
    runtime = _runtime()
    receipt = _receipt()
    # 失败的已执行 sandbox（非零退出）：不能证明只读，清空既有验证也不入集合。
    facts = (
        _calls_fact(
            ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ("validate-b", "sandbox_exec", {"executable": "./check-b"}),
        ),
        _sandbox_fact(receipt, tool_call_id="validate-a"),
        ConversationFact(
            fact_id="run:run-fresh:tool-result:validate-b:2",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "validate-b",
                "text": "boom",
                "is_error": True,
                "executed": True,
                "metadata": _metadata_projection(receipt, exit_code=3),
            },
        ),
    )
    _ordinary, _observations, native = (
        runtime._successful_product_request_inventory(_state(*facts))
    )
    assert native == set()
    # 投影不符的“假 read-only”同样无 credit。
    fake_mode = (
        _calls_fact(("validate-c", "sandbox_exec", {"executable": "./check-c"})),
        ConversationFact(
            fact_id="run:run-fresh:tool-result:validate-c:3",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "validate-c",
                "text": "ok",
                "is_error": False,
                "executed": True,
                "metadata": {
                    "mode": "read-only",
                    "sandbox_receipt_kind": "native_sandbox_v1",
                },
            },
        ),
    )
    _o2, _obs2, native2 = runtime._successful_product_request_inventory(
        _state(*fake_mode)
    )
    assert native2 == set()


def test_fold_operator_mutation_participates_in_invalidation() -> None:
    runtime = _runtime()
    receipt = _receipt(receipt_id="sandbox-receipt:a", lease_id="lease:a")
    facts = (
        _calls_fact(("validate-a", "sandbox_exec", {"executable": "./check-a"})),
        _sandbox_fact(receipt, tool_call_id="validate-a"),
        # operator TOOL_CALLS：参数被隐去，只留身份。
        ConversationFact(
            fact_id="run:run-fresh:operator-tool:3",
            kind=FactKind.TOOL_CALLS,
            content={
                "invocation_origin": "operator",
                "calls": [
                    {
                        "tool_call_id": "op-write-1",
                        "name": "write_file",
                        "arguments": {},
                        "arguments_redacted": True,
                    }
                ],
            },
        ),
        ConversationFact(
            fact_id="run:run-fresh:tool-result:op-write-1:4",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "op-write-1",
                "text": "written",
                "is_error": False,
                "executed": True,
                "invocation_origin": "operator",
                "metadata": {
                    "tool_name": "write_file",
                    "governed_tool_receipt_kind": "governed_tool_v1",
                },
            },
        ),
    )
    _ordinary, _observations, native = (
        runtime._successful_product_request_inventory(_state(*facts))
    )
    # operator 的已执行 mutation 必须使先前验证失效，不得因 operator origin 被过滤而遗漏。
    assert native == set()


def test_fold_rejected_results_earn_no_credit() -> None:
    runtime = _runtime()
    facts = (
        _calls_fact(("validate-a", "sandbox_exec", {"executable": "./check-a"})),
        ConversationFact(
            fact_id="run:run-fresh:tool-result:validate-a:1",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "validate-a",
                "text": "rejected",
                "is_error": True,
                "executed": False,
                "metadata": {"code": "approval_required"},
            },
        ),
    )
    ordinary, _observations, native = (
        runtime._successful_product_request_inventory(_state(*facts))
    )
    assert ordinary == set()
    assert native == set()


def _closure_criterion() -> AdmittedCriterion:
    receipt = _receipt()
    return AdmittedCriterion(
        criterion_id="criterion:x",
        description="check-a passes",
        source_fact_id="fact-user",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={
            "receipt_kind": "native_sandbox_v1",
            "command_fingerprint": receipt.original_command_fingerprint,
            "policy_digest": receipt.policy_digest,
            "mode": receipt.mode,
            "network": receipt.network,
            "backend": receipt.backend,
            "enforcement": receipt.enforcement,
            "outcome": "exited",
        },
        required_evidence_class="native_sandbox_receipt",
        admission_digest="e" * 64,
        mandatory=True,
    )


def _closure_claim(registry: ClosedEvidenceRegistry, base: ConversationState) -> CompletionClaim:
    return CompletionClaim(
        correlation_id="claim-closure",
        goal_id=base.goal.goal_id,
        goal_revision=base.goal.revision,
        criterion_evidence_refs=(
            registry.evidence_id(
                base.goal.goal_id, base.goal.revision, "criterion:x"
            ),
        ),
    )


def test_unknown_outcome_recovery_invalidates_old_validation() -> None:
    """RC-01（2026-10-11）：UNKNOWN 写入恢复后旧验证失效，同参重验不再被抑制。

    mark_succeeded 与 mark_failed 一致：标记失败不等于从未执行；恢复不授予
    新豁免，也不永久禁止真正的重新验证（新 receipt 重新可获信任）。
    """

    def build():
        receipt = _receipt()
        validation = _sandbox_fact(receipt)
        calls = _calls_fact(
            ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
            ("mutate", "write_file", {"path": "artifact.txt", "content": "changed"}),
        )
        base = _state(calls, validation)
        base = replace(base, goal=replace(base.goal, admitted_criteria=(_closure_criterion(),)))
        return base

    def recovering(base):
        return replace(
            base,
            active_run=replace(
                base.active_run,
                status=ActiveRunStatus.AWAITING_RECOVERY,
                phase=ContinuationPhase.EXECUTING,
                tool_calls=(
                    ToolCall(
                        "mutate",
                        "write_file",
                        {"path": "artifact.txt", "content": "changed"},
                    ),
                ),
                batch_cursor=0,
                pending_request=RecoveryRequest(
                    request_id="recovery",
                    run_id="run-fresh",
                    tool_call_id="mutate",
                    binding_digest="intent",
                    summary="unknown",
                ),
                executing_intent=ExecutingIntentRecord(
                    tool_call_id="mutate",
                    intent_digest="intent",
                    idempotency_key="key",
                    side_effect=SideEffectClass.WRITE,
                    execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                ),
            ),
        )

    def resolve(base, resolution):
        action = ResolveUnknownToolOutcome(
            conversation_id=base.conversation_id,
            action_seq=base.next_action_seq,
            expected_revision=base.revision,
            request_id="recovery",
            binding_digest="intent",
            resolution=resolution,
        )
        return accept_action(recovering(base), action).state

    runtime = _runtime()
    validate_digest = runtime._product_request_digest(
        "sandbox_exec", {"executable": "./check-a"}
    )
    registry = ClosedEvidenceRegistry()
    fresh_claim = _closure_claim(registry, build())

    for resolution in (RecoveryResolution.MARK_SUCCEEDED, RecoveryResolution.MARK_FAILED):
        recovered = resolve(build(), resolution)
        recovery_fact = recovered.facts[-1]
        # reducer 必须盖可信标记：结果未知 + 可信副作用分类（来自执行意图）。
        assert recovery_fact.content.get("unknown_outcome") is True
        assert recovery_fact.content.get("side_effect") == "write"
        # 证据判定：旧验证不再满足 criterion。
        with pytest.raises(EvidenceVerificationError):
            registry.derive(
                recovered, fresh_claim, observed_at="2026-10-11T00:00:00Z"
            )
        # 抑制折叠：validate-a 不再进入 native_validation（同参重验不被抑制）。
        _o, _m, native = runtime._successful_product_request_inventory(recovered)
        assert validate_digest not in native

    # 最终真正重验：恢复之后的新验证 receipt 重新可获信任（不永久禁止验证）。
    recovered = resolve(build(), RecoveryResolution.MARK_FAILED)
    new_calls = ConversationFact(
        fact_id="run:run-fresh:tool-batch:2",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": "validate-a",
                    "name": "sandbox_exec",
                    "arguments": {"executable": "./check-a"},
                }
            ],
        },
    )
    new_validation = ConversationFact(
        fact_id="run:run-fresh:tool-result:validate-a:2",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "validate-a",
            "text": "ok",
            "is_error": False,
            "executed": True,
            "metadata": _metadata_projection(
                _receipt(
                    receipt_id="sandbox-receipt:fresh-2",
                    lease_id="sandbox-lease:fresh-2",
                ),
            ),
        },
    )
    state_after_revalidation = replace(
        recovered, facts=(*recovered.facts, new_calls, new_validation)
    )
    _o, _m, native = runtime._successful_product_request_inventory(state_after_revalidation)
    # 注意：validate-b 的参数与 validate-a 相同（同参重验），新 receipt 赋予新信任。
    assert runtime._product_request_digest("sandbox_exec", {"executable": "./check-a"}) in native

    # 负例对照：确定未执行的审批拒绝不构成失效，合法只读组合证据保留。
    rejection_state = build()
    rejection = ConversationFact(
        fact_id="run:run-fresh:tool-result:mutate:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "mutate",
            "text": "declined",
            "is_error": True,
            "executed": False,
            "rejected": True,
        },
    )
    state_with_rejection = replace(rejection_state, facts=(*rejection_state.facts, rejection))
    _o, _m, native_rejection = runtime._successful_product_request_inventory(state_with_rejection)
    assert validate_digest in native_rejection

    # 只读工具的 UNKNOWN 恢复不失效旧验证（不无端清掉合法只读组合）。
    read_only_recovered = replace(
        recovering(build()),
        active_run=replace(
            recovering(build()).active_run,
            tool_calls=(ToolCall("peek", "read_only_probe", {"path": "artifact.txt"}),),
            pending_request=RecoveryRequest(
                request_id="recovery-ro",
                run_id="run-fresh",
                tool_call_id="peek",
                binding_digest="intent",
                summary="unknown",
            ),
            executing_intent=ExecutingIntentRecord(
                tool_call_id="peek",
                intent_digest="intent",
                idempotency_key="key",
                side_effect=SideEffectClass.READ_ONLY,
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            ),
        ),
    )
    action_ro = ResolveUnknownToolOutcome(
        conversation_id=build().conversation_id,
        action_seq=build().next_action_seq,
        expected_revision=build().revision,
        request_id="recovery-ro",
        binding_digest="intent",
        resolution=RecoveryResolution.MARK_FAILED,
    )
    ro_state = accept_action(read_only_recovered, action_ro).state
    assert ro_state.facts[-1].content.get("side_effect") == "read_only"
    _o, _m, native_ro = runtime._successful_product_request_inventory(ro_state)
    assert validate_digest in native_ro


def test_managed_writable_process_start_invalidates_old_validation() -> None:
    """RC-02（2026-10-11）：可写 same-UID 进程启动结果必须失效旧验证并释放抑制。

    governed_tool_v1 结果外形没有 process_receipt，但 managed_web_start 的
    可信能力（LOCAL_SAME_UID_PROCESS，进程可写 workspace）本身构成潜在变更。
    """
    receipt = _receipt()
    validation = _sandbox_fact(receipt)
    calls = _calls_fact(
        ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
        ("start", "managed_web_start", {"executable": "./server"}),
    )
    base = _state(calls, validation)
    managed = ConversationFact(
        fact_id="run:run-fresh:tool-result:start:2",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "start",
            "text": '{"resource_ref":"test-data"}',
            "is_error": False,
            "executed": True,
            "metadata": {
                "truncated": False,
                "tool_identity": "fixture",
                "tool_name": "managed_web_start",
                "governed_tool_receipt_kind": "governed_tool_v1",
                "receipt_digest": "a" * 64,
            },
        },
    )
    assert ClosedEvidenceRegistry._may_invalidate_workspace_validation(managed)
    runtime = _runtime()
    validate_digest = runtime._product_request_digest(
        "sandbox_exec", {"executable": "./check-a"}
    )
    _o, _m, native = runtime._successful_product_request_inventory(
        replace(base, facts=(*base.facts, managed))
    )
    assert validate_digest not in native


def test_managed_writable_process_start_requires_executed_result() -> None:
    """RC-02 边界：未执行（executed=False）的 start 不构成失效。"""
    not_executed = ConversationFact(
        fact_id="run:run-fresh:third-result:start:3",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "start",
            "text": "declined",
            "is_error": True,
            "executed": False,
        },
    )
    assert not ClosedEvidenceRegistry._may_invalidate_workspace_validation(not_executed)


def test_real_managed_web_start_result_from_tool_runtime_invalidates_validation(
    tmp_path,
) -> None:
    """RC-02 真实服务：用本次拥有的短期 server 写 sentinel，验证旧验证被失效。

    合同要求不能只用手写 metadata：这里用当前真实 `KernelToolRuntime` 走
    prepare(审批) → prepare(lease) → invoke，得到生产格式的 managed_web_start
    结果，再经 `AgentRuntime._tool_result_fact` 变成 durable fact，交给生产
    证据判定与抑制折叠。服务存活期间写入 sentinel 文件（真实副作用），确认
    启动前的验证不再可用于最终完成。
    """

    import json
    import os
    import socket
    import sys

    from agent.process.managed_web import build_managed_web_process_tools
    from agent.runtime.contracts import (
        ApprovalRequired,
        ExecutionIntent,
        ProcessAuthorityLeaseV1,
        ToolPrepareContext,
    )
    from agent.runtime.tools import KernelToolRuntime

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "sentinel.txt"
    sentinel.write_text("before\n", encoding="utf-8")

    # 服务脚本：收到 loopback 请求时把 sentinel 改成 after，形成真实写入。
    server = workspace / "server.py"
    server.write_text(
        f"#!{sys.executable}\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "import pathlib, sys\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        pathlib.Path('sentinel.txt').write_text('after\\n', encoding='utf-8')\n"
        "        self.send_response(200)\n"
        "        self.end_headers()\n"
        "        self.wfile.write(b'wrote')\n"
        "    def log_message(self, *args):\n"
        "        pass\n"
        "server = ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), H)\n"
        "print('READY', flush=True)\n"
        "server.serve_forever()\n",
        encoding="utf-8",
    )
    server.chmod(0o700)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    bundle = build_managed_web_process_tools(
        workspace=workspace,
        captured_path=os.environ.get("PATH", ""),
    )
    tool_runtime = KernelToolRuntime(bundle.registrations)
    context = ToolPrepareContext(
        conversation_id="conversation-fresh",
        run_id="run-fresh",
        state_revision=7,
        approval_basis_revision=7,
        goal_id="goal-fresh",
        goal_revision=1,
        workspace_identity_digest=WORKSPACE_DIGEST,
    )
    call = ToolCall(
        "start",
        "managed_web_start",
        {
            "executable": "./server.py",
            "argv": [str(port)],
            "cwd": ".",
            "profile": "long",
            "loopback_port": port,
        },
    )

    approval = tool_runtime.prepare(call, context)
    assert isinstance(approval, ApprovalRequired)
    candidate = approval.request.process_authority_candidate
    lease = ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity="approval-managed-web",
        issued_at=candidate.issued_at,
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=0,
    )
    intent = tool_runtime.prepare(call, replace(context, process_leases=(lease,)))
    assert isinstance(intent, ExecutionIntent)

    try:
        started = tool_runtime.invoke(intent)
        assert started.is_error is False
        payload = json.loads(started.content)
        resource_ref = payload["resource_ref"]

        # 生产路径：真实 ToolResult → durable fact（不是手写 metadata）。
        base = _state(
            _calls_fact(
                ("validate-a", "sandbox_exec", {"executable": "./check-a"}),
                ("start", "managed_web_start", {"executable": "./server.py"}),
            ),
            _sandbox_fact(_receipt()),
        )
        base = replace(
            base,
            goal=replace(base.goal, admitted_criteria=(_closure_criterion(),)),
        )
        managed_fact = AgentRuntime._tool_result_fact(base, started)
        assert managed_fact.content["metadata"]["tool_name"] == "managed_web_start"

        runtime = _runtime()
        validate_digest = runtime._product_request_digest(
            "sandbox_exec", {"executable": "./check-a"}
        )
        registry = ClosedEvidenceRegistry()
        after_start = replace(base, facts=(*base.facts, managed_fact))

        # 启动即构成潜在写入：旧验证不可满足 criterion，抑制折叠被释放。
        assert ClosedEvidenceRegistry._may_invalidate_workspace_validation(managed_fact)
        with pytest.raises(EvidenceVerificationError):
            registry.derive(
                after_start,
                _closure_claim(registry, base),
                observed_at="2026-10-11T00:00:00Z",
            )
        _o, _m, native = runtime._successful_product_request_inventory(after_start)
        assert validate_digest not in native

        # 服务存活期间真实写入 sentinel（事件/屏障协调：先确认 READY 再请求）。
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            client.sendall(b"GET /write HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            client.recv(1024)
        assert sentinel.read_text(encoding="utf-8") == "after\n"

        # 关闭服务：正常 stop 确认清理，之后旧验证仍不成立（关闭不恢复信任）。
        stopped = tool_runtime.invoke(
            tool_runtime.prepare(
                ToolCall("stop", "managed_web_stop", {"resource_ref": resource_ref}),
                context,
            )
        )
        assert json.loads(stopped.content)["cleanup"] == "confirmed"
        with pytest.raises(EvidenceVerificationError):
            registry.derive(
                after_start,
                _closure_claim(registry, base),
                observed_at="2026-10-11T00:00:00Z",
            )

        # 关闭后显式同参重验可重新获信任并用于完成（不永久禁止验证）。
        revalidated = replace(
            after_start,
            facts=(
                *after_start.facts,
                ConversationFact(
                    fact_id="run:run-fresh:tool-batch:2",
                    kind=FactKind.TOOL_CALLS,
                    content={
                        "calls": [
                            {
                                "tool_call_id": "validate-a",
                                "name": "sandbox_exec",
                                "arguments": {"executable": "./check-a"},
                            }
                        ],
                    },
                ),
                ConversationFact(
                    fact_id="run:run-fresh:tool-result:validate-a:2",
                    kind=FactKind.TOOL_RESULT,
                    content={
                        "tool_call_id": "validate-a",
                        "text": "ok",
                        "is_error": False,
                        "executed": True,
                        "metadata": _metadata_projection(
                            _receipt(
                                receipt_id="sandbox-receipt:fresh-2",
                                lease_id="sandbox-lease:fresh-2",
                            ),
                        ),
                    },
                ),
            ),
        )
        _o, _m, native_after = runtime._successful_product_request_inventory(revalidated)
        assert validate_digest in native_after
    finally:
        bundle.close()

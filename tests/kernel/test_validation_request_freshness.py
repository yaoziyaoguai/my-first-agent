"""S1-A（DU-02/03/04/05）：验证请求新鲜性的单元合同。

- 可信只读 native sandbox 分类（evidence 与 loop 抑制折叠共用同一严格 helper），
  伪造/缺失/投影不符/非 confined/network 非 off 一律不进可信验证集合。
- durable fact fold 的三集合语义：ordinary ∪ native_validation 参与抑制查询；
  写入/process/不可信 sandbox 已执行结果清空 native_validation；A/B 可共存；
  operator 已执行 mutation 同样参与失效；fold 是 facts 的纯函数（重建等价）。
"""

from __future__ import annotations

from agent.runtime.contracts import (
    ApprovalPolicy,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    FactKind,
    GoalFrame,
    GoalStatus,
    OutputPolicy,
    ProposedCriterion,
    SandboxReceiptV1,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.evidence import trusted_readonly_native_sandbox_success
from agent.runtime.loop import AgentRuntime, InvocationLimits
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

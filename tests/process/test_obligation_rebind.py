"""2026-10-18 发现 3：runtime-owned process 义务的失败重绑定。

真实层 E1r2/E2 实测：`required-local-process` 义务在批准时 pin「首个被批准
命令的 fingerprint + exited/0」。当该命令在环境内必然失败（裸 ``pytest -q``
exit 2，pyenv shim 不把 cwd 注入 sys.path）、模型改用等价命令
（``python3 -m pytest -q``）并再获用户 exact approval 后，旧义务仍 pin 旧
fingerprint，Goal 永远无法 VERIFIED_DONE（E1r2 因此 blocked）。

修复契约：已执行且从未成功（无 exited/0 receipt）的 runtime-owned 义务，在
用户批准一条亲和命令（与新命令共享 executable/argv 的非 flag token）时重新
绑定到新 fingerprint；曾成功过（哪怕已被后续写入失效——那由重跑修复）、
从未执行过、或无关命令都不重绑定。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent.runtime.contracts import (
    ActionDisposition,
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalRequest,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    FactKind,
    GoalFrame,
    GoalStatus,
    ProcessAuthorityCandidateV1,
    ProcessOutcome,
    ProcessReceiptV1,
    ResolveApproval,
    ToolCall,
)
from agent.runtime.state import _admit_approved_process_receipt_criterion, accept_action

FP_OLD = "9e" * 32
FP_NEW = "d9" * 32
OBLIGATION_ID = "criterion:required-local-process:83d8630ca7669b61"


def _process_call_fact(
    run_id: str, call_id: str, executable: str, argv: list[str]
) -> ConversationFact:
    return ConversationFact(
        fact_id=f"{run_id}:tool-calls:1",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": call_id,
                    "name": "local_process",
                    "arguments": {
                        "executable": executable,
                        "argv": argv,
                        "cwd": ".",
                        "profile": "standard",
                    },
                }
            ]
        },
    )


def _receipt_fact(
    run_id: str,
    call_id: str,
    fingerprint: str,
    *,
    exit_code: int,
) -> ConversationFact:
    receipt = ProcessReceiptV1.create(
        lease_id=f"process-lease:{call_id}",
        lease_digest="a" * 64,
        use_ordinal=1,
        goal_id="goal:1",
        goal_revision=1,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        tool_identity="c" * 64,
        intent_digest="d" * 64,
        executable_digest="e" * 64,
        argv_digest="0" * 64,
        cwd_digest="1" * 64,
        resource_profile="standard",
        environment_policy_digest="2" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        outcome=ProcessOutcome.EXITED,
        exit_code=exit_code,
        signal=None,
        started_at="1.0",
        ended_at="2.0",
        duration_seconds=1.0,
        stdout_digest="3" * 64,
        stderr_digest="4" * 64,
        stdout_bytes=1,
        stderr_bytes=0,
        stdout_truncated=False,
        stderr_truncated=False,
        group_cleanup_claim="unconfirmed",
        command_fingerprint=fingerprint,
    )
    return ConversationFact(
        fact_id=f"{run_id}:tool-result:{call_id}:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": call_id,
            "text": "local_process exited",
            "is_error": False,
            "executed": True,
            "metadata": {
                "process_receipt_kind": "process_v1",
                "process_receipt": receipt.to_json(),
                "receipt_digest": receipt.receipt_digest,
                "execution_authority": "local_same_uid_process",
                "outcome": "exited",
                "exit_code": exit_code,
                "command_fingerprint": fingerprint,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "duration_seconds": 1.0,
                "resource_profile": "standard",
                "stdout_digest": "3" * 64,
                "stderr_digest": "4" * 64,
                "lease_id": f"process-lease:{call_id}",
                "use_ordinal": 1,
                "tool_identity": "c" * 64,
            },
        },
    )


def _goal_with_obligation() -> GoalFrame:
    obligation = AdmittedCriterion(
        criterion_id=OBLIGATION_ID,
        description="the explicitly requested local validation process exits successfully",
        source_fact_id="fact:user:1",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={
            "receipt_kind": "process_v1",
            "command_fingerprint": FP_OLD,
            "outcome": "exited",
            "exit_code": 0,
        },
        required_evidence_class="process_receipt",
        admission_digest="m" * 64,
        mandatory=True,
    )
    return GoalFrame(
        goal_id="goal:1",
        revision=1,
        created_from_fact_ids=("fact:user:1",),
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        user_outcome="完成 SPEC 并运行 pytest -q 验证",
        beneficiary="owner",
        targets=("retry_app/service.py",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(),
        admitted_criteria=(obligation,),
        authority_snapshot="authority:v1:" + "d" * 64,
        status=GoalStatus.EXECUTING,
        created_at="2026-10-18T00:00:00Z",
        updated_at="2026-10-18T00:00:00Z",
    )


def _state(
    new_call: ToolCall,
    *,
    old_executed: bool,
    old_ever_succeeded: bool,
    old_argv: list[str] | None = None,
    old_exit_code: int | None = None,
) -> ConversationState:
    user = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "完成 SPEC 并运行 pytest -q 验证"},
    )
    old_run = "run:1"
    facts: list[ConversationFact] = [user]
    facts.append(
        _process_call_fact(old_run, "call-old", "pytest", ["-q"] if old_argv is None else old_argv)
    )
    if old_executed:
        facts.append(
            _receipt_fact(
                old_run,
                "call-old",
                FP_OLD,
                exit_code=(
                    0 if old_ever_succeeded else (2 if old_exit_code is None else old_exit_code)
                ),
            )
        )
    return ConversationState(
        conversation_id="conversation:1",
        goal=_goal_with_obligation(),
        active_run=ActiveRun(
            run_id="run:2",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            tool_calls=(new_call,),
            pending_request=_approval(),
        ),
        facts=tuple(facts),
    )


def _approval(*, cwd_digest: str = "1" * 64) -> ApprovalRequest:
    candidate = ProcessAuthorityCandidateV1.create(
        candidate_id="candidate:1",
        goal_id="goal:1",
        goal_revision=1,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        command_fingerprint=FP_NEW,
        readable_command="python3 -m pytest -q",
        executable_digest="e" * 64,
        argv_digest="0" * 64,
        cwd_digest=cwd_digest,
        resource_profile="standard",
        environment_policy_digest="2" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        trust_notice_digest="t" * 64,
        issued_at="2026-10-18T00:00:00Z",
    )
    return ApprovalRequest(
        request_id="request:1",
        run_id="run:2",
        tool_call_id="call-new",
        binding_digest="binding:1",
        preview="local_process python3 -m pytest -q",
        tool_name="local_process",
        process_authority_candidate=candidate,
    )


def _action(*, authorize_obligation_rebind: bool = False) -> ResolveApproval:
    return ResolveApproval(
        conversation_id="conversation:1",
        action_seq=3,
        expected_revision=2,
        request_id="request:1",
        binding_digest="binding:1",
        approved=True,
        approved_at="2026-10-18T00:00:01Z",
        authorize_obligation_rebind=authorize_obligation_rebind,
    )


def _new_call(executable: str, argv: list[str]) -> ToolCall:
    return ToolCall(
        "call-new",
        "local_process",
        {"executable": executable, "argv": argv, "cwd": ".", "profile": "standard"},
    )


def test_failed_obligation_rebinds_to_affine_approved_command() -> None:
    """旧命令已执行且从未成功 + 新批准命令亲和（共享 pytest token）→ 同 id 重绑定。"""

    state = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=False,
    )
    result = _admit_approved_process_receipt_criterion(
        state, _approval(), action=_action(authorize_obligation_rebind=True)
    )

    criteria = {c.criterion_id: c for c in result.goal.admitted_criteria}
    rebound = criteria[OBLIGATION_ID]
    assert rebound.predicate["command_fingerprint"] == FP_NEW
    assert rebound.predicate["outcome"] == "exited"
    assert rebound.predicate["exit_code"] == 0
    assert not any(cid.startswith("criterion:process-receipt:") for cid in criteria)


def test_unrelated_approved_command_does_not_rebind() -> None:
    """无共享非 flag token 的命令（echo hi）不得承接验证义务。"""

    state = _state(
        _new_call("echo", ["hi"]),
        old_executed=True,
        old_ever_succeeded=False,
    )
    result = _admit_approved_process_receipt_criterion(state, _approval(), action=_action())

    criteria = {c.criterion_id: c for c in result.goal.admitted_criteria}
    assert criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_OLD
    per_call = [cid for cid in criteria if cid.startswith("criterion:process-receipt:")]
    assert len(per_call) == 1


def test_flag_variant_of_validator_does_not_rebind() -> None:
    """P1（对抗审查实机复现）：``pytest --help``/``--collect-only`` 退出 0 但从未
    运行测试，不得凭共享 executable token 承接验证义务。等价性必须含 rest argv。"""

    for executable, argv in (
        ("pytest", ["--help"]),
        ("pytest", ["--collect-only", "-q"]),
        ("pytest", ["-q", "--help"]),
    ):
        state = _state(
            _new_call(executable, argv),
            old_executed=True,
            old_ever_succeeded=False,
        )
        result = _admit_approved_process_receipt_criterion(state, _approval(), action=_action())
        criteria = {c.criterion_id: c for c in result.goal.admitted_criteria}
        assert criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_OLD, (
            executable,
            argv,
        )


def test_environment_repair_flags_rebind_to_the_same_validator() -> None:
    """2026-10-18 真实层 E1r4 实测：裸 ``pytest -q`` exit 2 后，模型改用同一
    validator 加**导入/收集环境修复 flag**（``-p no:cacheprovider
    --import-mode=prepend --rootdir=. -o pythonpath=.``）跑通。这类 flag 不改变
    选中与执行语义，必须能承接义务，否则义务永远 pin 在注定失败的命令上。"""

    repaired = [
        "-q",
        "-p",
        "no:cacheprovider",
        "--import-mode=prepend",
        "--rootdir=.",
        "-o",
        "pythonpath=.",
    ]
    result = _admit_approved_process_receipt_criterion(
        _state(
            _new_call("pytest", repaired),
            old_executed=True,
            old_ever_succeeded=False,
        ),
        _approval(),
        action=_action(authorize_obligation_rebind=True),
    )
    assert {c.criterion_id: c for c in result.goal.admitted_criteria}[OBLIGATION_ID].predicate[
        "command_fingerprint"
    ] == FP_NEW


def test_environment_flags_cannot_smuggle_selection_bypasses() -> None:
    """同一放宽不得成为绕过口：``-o addopts=``（可注入 ``--collect-only``）、
    ``--ignore=``/``-k``/``--deselect=`` 等改变选中或跳过执行的 flag 一律不承接。"""

    for argv in (
        ["-q", "-o", "addopts=--collect-only"],
        ["-q", "-o", "addopts=--co -q"],
        ["-q", "--ignore=tests"],
        ["-q", "--deselect=tests/test_retry_service.py"],
        ["-q", "-k", "not test"],
        ["-q", "--collect-only"],
        ["-q", "--co"],
        ["-q", "--help"],
    ):
        result = _admit_approved_process_receipt_criterion(
            _state(
                _new_call("pytest", argv),
                old_executed=True,
                old_ever_succeeded=False,
            ),
            _approval(),
            action=_action(authorize_obligation_rebind=True),
        )
        assert {c.criterion_id: c for c in result.goal.admitted_criteria}[OBLIGATION_ID].predicate[
            "command_fingerprint"
        ] == FP_OLD, argv


def test_environment_repair_flags_do_not_excuse_a_changed_validator() -> None:
    """环境 flag 之外还改了入口或其余 argv（``python3 -m pytest`` → ``pytest``
    带 flag 但换了选择目标）仍不承接。"""

    for executable, argv in (
        ("pytest", ["-q", "tests/test_other.py", "--import-mode=prepend"]),
        ("pytest", ["-x", "-p", "no:cacheprovider"]),
        ("unittest", ["-q", "-p", "no:cacheprovider"]),
    ):
        result = _admit_approved_process_receipt_criterion(
            _state(
                _new_call(executable, argv),
                old_executed=True,
                old_ever_succeeded=False,
            ),
            _approval(),
            action=_action(authorize_obligation_rebind=True),
        )
        assert {c.criterion_id: c for c in result.goal.admitted_criteria}[OBLIGATION_ID].predicate[
            "command_fingerprint"
        ] == FP_OLD, (executable, argv)


def test_shared_path_token_does_not_rebind() -> None:
    """共享 argv 路径 token 不算等价（``python3 tests/x.py`` / ``cat tests/x.py``
    都可能退出 0 而不执行测试）。"""

    for executable, argv in (
        ("python3", ["tests/test_retry_service.py"]),
        ("cat", ["tests/test_retry_service.py"]),
    ):
        state = _state(
            _new_call(executable, argv),
            old_executed=True,
            old_ever_succeeded=False,
            old_argv=["tests/test_retry_service.py"],
        )
        result = _admit_approved_process_receipt_criterion(state, _approval(), action=_action())
        criteria = {c.criterion_id: c for c in result.goal.admitted_criteria}
        assert criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_OLD, (
            executable,
            argv,
        )


def test_equivalent_module_invocation_rebinds_but_changed_args_do_not() -> None:
    """canonical 等价：``python3 -m pytest -q`` ≡ ``pytest -q``（同 entry+rest）；
    改成 ``pytest -x`` 或 ``pytest tests`` 则不承接。"""

    rebind = _admit_approved_process_receipt_criterion(
        _state(
            _new_call("python3", ["-m", "pytest", "-q"]),
            old_executed=True,
            old_ever_succeeded=False,
        ),
        _approval(),
        action=_action(authorize_obligation_rebind=True),
    )
    assert {c.criterion_id: c for c in rebind.goal.admitted_criteria}[OBLIGATION_ID].predicate[
        "command_fingerprint"
    ] == FP_NEW
    for argv in (["-x"], ["tests"]):
        result = _admit_approved_process_receipt_criterion(
            _state(
                _new_call("pytest", argv),
                old_executed=True,
                old_ever_succeeded=False,
            ),
            _approval(),
            action=_action(),
        )
        assert {c.criterion_id: c for c in result.goal.admitted_criteria}[OBLIGATION_ID].predicate[
            "command_fingerprint"
        ] == FP_OLD, argv


def test_obligation_with_prior_success_is_not_rebound() -> None:
    """曾成功过的义务（重跑可再满足）不重绑定，走 per-call 铸造。"""

    state = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=True,
    )
    result = _admit_approved_process_receipt_criterion(state, _approval(), action=_action())

    criteria = {c.criterion_id: c for c in result.goal.admitted_criteria}
    assert criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_OLD


def test_never_executed_obligation_command_is_not_rebound() -> None:
    """旧命令只批准未执行（尚无失败证据）时不重绑定。"""

    state = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=False,
        old_ever_succeeded=False,
    )
    result = _admit_approved_process_receipt_criterion(state, _approval(), action=_action())

    criteria = {c.criterion_id: c for c in result.goal.admitted_criteria}
    assert criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_OLD


def test_receipts_from_an_earlier_goal_do_not_make_obligation_rebindable() -> None:
    """P3（对抗审查）：重绑定资格必须 Goal 作用域——早前 Goal 的同命令失败
    不能让当前 Goal「从未执行」的义务变成可重绑定。"""

    state = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=False,
    )
    # 把旧 receipt 的 goal_id 改成别的 Goal（call 事实仍属旧 run）。
    from dataclasses import replace as _replace

    foreign: list[ConversationFact] = []
    for fact in state.facts:
        if fact.kind is FactKind.TOOL_RESULT:
            metadata = dict(fact.content["metadata"])
            receipt = ProcessReceiptV1.from_json(metadata["process_receipt"])
            foreign_receipt = ProcessReceiptV1.create(
                lease_id=receipt.lease_id,
                lease_digest=receipt.lease_digest,
                use_ordinal=receipt.use_ordinal,
                goal_id="goal:other",
                goal_revision=receipt.goal_revision,
                workspace_identity_digest=receipt.workspace_identity_digest,
                tool_identity=receipt.tool_identity,
                intent_digest=receipt.intent_digest,
                executable_digest=receipt.executable_digest,
                argv_digest=receipt.argv_digest,
                cwd_digest=receipt.cwd_digest,
                resource_profile=receipt.resource_profile,
                environment_policy_digest=receipt.environment_policy_digest,
                execution_authority=receipt.execution_authority,
                outcome=receipt.outcome,
                exit_code=receipt.exit_code,
                signal=receipt.signal,
                started_at=receipt.started_at,
                ended_at=receipt.ended_at,
                duration_seconds=receipt.duration_seconds,
                stdout_digest=receipt.stdout_digest,
                stderr_digest=receipt.stderr_digest,
                stdout_bytes=receipt.stdout_bytes,
                stderr_bytes=receipt.stderr_bytes,
                stdout_truncated=receipt.stdout_truncated,
                stderr_truncated=receipt.stderr_truncated,
                group_cleanup_claim=receipt.group_cleanup_claim,
                command_fingerprint=receipt.command_fingerprint,
            )
            metadata["process_receipt"] = foreign_receipt.to_json()
            metadata["receipt_digest"] = foreign_receipt.receipt_digest
            metadata["goal_id"] = "goal:other"
            fact = _replace(
                fact,
                content={**fact.content, "metadata": metadata},
            )
        foreign.append(fact)
    state = _replace(state, facts=tuple(foreign))

    result = _admit_approved_process_receipt_criterion(state, _approval(), action=_action())
    criteria = {c.criterion_id: c for c in result.goal.admitted_criteria}
    assert criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_OLD


def test_rebind_requires_explicit_opt_in_flag() -> None:
    """P2（对抗审查）：批准语义是「执行这一笔操作」，重绑定改写了 admitted
    义务，必须有显式 opt-in；默认批准只铸造 per-call 判据。"""

    state = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=False,
    )
    plain = _admit_approved_process_receipt_criterion(state, _approval(), action=_action())
    plain_criteria = {c.criterion_id: c for c in plain.goal.admitted_criteria}
    assert plain_criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_OLD

    opted_in = _admit_approved_process_receipt_criterion(
        state,
        _approval(),
        action=_action(authorize_obligation_rebind=True),
    )
    opted_criteria = {c.criterion_id: c for c in opted_in.goal.admitted_criteria}
    assert opted_criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_NEW


def test_legitimate_test_failure_does_not_make_obligation_rebindable() -> None:
    """P1（对抗审查）：真实测试失败（pytest exit 1 = 测试红了）不得触发重绑定，
    否则模型可用一条不验证的命令掩盖红测试。只有环境类失败（如 usage/无测试
    收集 exit 2/5 且命令本身不可执行）才可重绑定。"""

    for exit_code in (1, 3, 4):
        state = _state(
            _new_call("python3", ["-m", "pytest", "-q"]),
            old_executed=True,
            old_ever_succeeded=False,
            old_exit_code=exit_code,
        )
        result = _admit_approved_process_receipt_criterion(
            state, _approval(), action=_action(authorize_obligation_rebind=True)
        )
        criteria = {c.criterion_id: c for c in result.goal.admitted_criteria}
        assert criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_OLD, exit_code


def test_environment_class_failure_allows_rebind() -> None:
    """exit 2（pytest usage/中断，真实层 pyenv shim 裸 pytest 的签名）允许重绑定。"""

    state = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=False,
        old_exit_code=2,
    )
    result = _admit_approved_process_receipt_criterion(
        state, _approval(), action=_action(authorize_obligation_rebind=True)
    )
    criteria = {c.criterion_id: c for c in result.goal.admitted_criteria}
    assert criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_NEW


def test_projection_discloses_rebind_before_approval() -> None:
    """P2（对抗审查）：批准=执行这一笔；重绑定改写 admitted 义务必须在审批
    提示中如实披露，且同时给出旧命令与新命令。"""

    from agent.runtime.views import project_obligation_rebind_disclosure

    state = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=False,
    )
    disclosure = project_obligation_rebind_disclosure(state)

    assert disclosure is not None
    assert "pytest -q" in disclosure
    assert "python3 -m pytest -q" in disclosure
    assert "re-binds" in disclosure


def test_projection_is_silent_when_obligation_cannot_rebind() -> None:
    """曾成功过 / 从未执行 / 非 local_process 审批时不得出现披露文案。"""

    from agent.runtime.views import project_obligation_rebind_disclosure

    succeeded = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=True,
    )
    never_executed = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=False,
        old_ever_succeeded=False,
    )
    unrelated = _state(
        _new_call("echo", ["hi"]),
        old_executed=True,
        old_ever_succeeded=False,
    )
    for state in (succeeded, never_executed, unrelated):
        assert project_obligation_rebind_disclosure(state) is None


def test_renderer_shows_rebind_disclosure_in_approval_prompt() -> None:
    """CLI 审批提示必须携带该披露；不重绑定的审批保持原样。"""

    from agent.cli.render import TerminalRenderer

    eligible = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=False,
    )
    output: list[str] = []
    TerminalRenderer(output.append).render_pending(eligible)
    assert "re-binds that pending verification obligation" in output[0]

    silent = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=True,
    )
    output.clear()
    TerminalRenderer(output.append).render_pending(silent)
    assert "re-binds that pending verification obligation" not in output[0]


def test_cli_approval_authorizes_rebind_only_when_disclosed() -> None:
    """P2：CLI 的 y 在披露出现时随批准授权重绑定；未披露时不得静默授权。"""

    from agent.cli.app import _parse_action

    eligible = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=False,
    )
    action, error = _parse_action("y", eligible, lambda: "run:2")
    assert error is None
    assert isinstance(action, ResolveApproval)
    assert action.authorize_obligation_rebind is True

    undisclosed = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=True,
    )
    plain, error = _parse_action("y", undisclosed, lambda: "run:2")
    assert error is None
    assert isinstance(plain, ResolveApproval)
    assert plain.authorize_obligation_rebind is False

    denied, _ = _parse_action("n", eligible, lambda: "run:2")
    assert isinstance(denied, ResolveApproval)
    assert denied.approved is False
    assert denied.authorize_obligation_rebind is False


def test_trial_closeout_changed_cwd_cannot_replace_failed_validation() -> None:
    """同样的命令改到子目录执行，不能承接原目录的验证义务。"""

    call = ToolCall(
        "call-new", "local_process",
        {"executable": "pytest", "argv": ["-q"], "cwd": "smoke", "profile": "standard"},
    )
    state = _state(call, old_executed=True, old_ever_succeeded=False)
    request = _approval(cwd_digest="8" * 64)
    state = replace(state, active_run=replace(state.active_run, pending_request=request))
    action = replace(
        _action(authorize_obligation_rebind=True),
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )

    transition = accept_action(state, action)

    assert transition.disposition is ActionDisposition.ACCEPTED
    criteria = {c.criterion_id: c for c in transition.state.goal.admitted_criteria}
    assert criteria[OBLIGATION_ID].predicate["command_fingerprint"] == FP_OLD
    assert transition.state.process_leases[-1].command_fingerprint == FP_NEW


@pytest.mark.parametrize("command", ["y", "/approve request:1"])
def test_trial_closeout_explicit_approval_honors_the_same_rebind_disclosure(command) -> None:
    """同一显示快照的两种明确批准，都承接已披露且满足资格的重绑定。"""

    from agent.cli.app import _parse_action
    from agent.cli.render import TerminalRenderer

    state = _state(
        _new_call("python3", ["-m", "pytest", "-q"]),
        old_executed=True,
        old_ever_succeeded=False,
    )
    output = []
    TerminalRenderer(output.append).render_pending(state)
    assert "re-binds that pending verification obligation" in "\n".join(output)
    action, error = _parse_action(command, state, lambda: "run:unused")
    assert error is None

    transition = accept_action(state, action)

    assert transition.disposition is ActionDisposition.ACCEPTED
    criterion = next(
        c for c in transition.state.goal.admitted_criteria if c.criterion_id == OBLIGATION_ID
    )
    assert criterion.predicate["command_fingerprint"] == FP_NEW


@pytest.mark.parametrize("new_cwd", [".", "smoke"])
def test_trial_closeout_real_runtime_binds_validation_scope(tmp_path, new_cwd) -> None:
    """真实 prepare/审批/spawn/receipt 链：同目录可修复，子目录成功不得替代。"""

    from agent.cli.app import _parse_action
    from agent.composition import build_composition, build_tool_registrations
    from agent.continuity.sessions import open_workspace_session
    from agent.runtime.context import ContextLimits
    from agent.runtime.contracts import (
        ModelResponse,
        ModelToolCall,
        ProposedCriterion,
        RunStatus,
        SubmitMessage,
    )
    from agent.runtime.loop import InvocationLimits
    from tests.kernel.fakes import CollectingSink, ScriptedProvider, goal_draft_from_frame

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "smoke").mkdir()
    validator = workspace / "validator"
    validator.write_text("#!/bin/sh\n[ \"$#\" -gt 1 ] && exit 0\nexit 2\n")
    validator.chmod(0o700)
    opened = open_workspace_session(workspace, state_root=(tmp_path / "state").resolve())

    def proposal(context):
        bootstrap = context.goal_bootstrap
        frame = replace(
            _goal_with_obligation(),
            created_from_fact_ids=(bootstrap.source_fact_id,),
            workspace_identity_digest=bootstrap.workspace_identity_digest,
            authority_snapshot=bootstrap.authority_snapshot,
            user_outcome="运行 ./validator 验证当前工作区",
            targets=("workspace",), admitted_criteria=(), status=GoalStatus.GOAL_READY,
            proposed_criteria=(ProposedCriterion(
                "criterion:model-validation", "the requested validator exits successfully",
                oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
            ),),
        )
        return ModelResponse((), control=goal_draft_from_frame("proposal:scope", frame))

    def process(call_id, cwd, argv):
        return ModelResponse((ModelToolCall(call_id, "local_process", {
            "executable": "./validator", "argv": argv, "cwd": cwd, "profile": "short",
        }),))

    provider = ScriptedProvider(
        proposal,
        process("original", ".", ["-q"]),
        process("repair", new_cwd, ["-q", "-p", "no:cacheprovider"]),
        process("stop-at-approval", ".", ["--not-executed"]),
    )
    composition = build_composition(
        provider=provider, checkpoint_store=opened.store,
        tool_registrations=tuple(build_tool_registrations(
            workspace=workspace, max_tool_result_chars=50_000,
        )),
        event_sink=CollectingSink(), system_policy="Validate the requested workspace.",
        context_limits=ContextLimits(max_input_tokens=100_000, output_reserve=5_000),
        invocation_limits=InvocationLimits(),
        workspace_identity_digest=opened.workspace_binding.workspace_identity_digest,
        context_scope_digest=opened.workspace_binding.workspace_scope_digest,
        workspace_binding=opened.workspace_binding,
    )
    try:
        state = opened.store.load().state
        result = composition.runtime.run_turn(SubmitMessage(
            conversation_id=state.conversation_id, action_seq=state.next_action_seq,
            expected_revision=state.revision, run_id="run:scope",
            message="运行 ./validator 验证当前工作区",
        ), opened.store.load())
        fingerprints = []
        for _ in range(2):
            assert result.status is RunStatus.AWAITING_APPROVAL
            candidate = result.request.process_authority_candidate
            fingerprints.append(candidate.command_fingerprint)
            state = opened.store.load().state
            action, error = _parse_action(
                "y", state, lambda: "unused",
                approval_time_factory=lambda issued=candidate.issued_at: issued,
            )
            assert error is None
            result = composition.runtime.run_turn(action, opened.store.load())
        assert result.status is RunStatus.AWAITING_APPROVAL
        final = opened.store.load().state
        criterion = next(c for c in final.goal.admitted_criteria
                         if c.criterion_id.startswith("criterion:required-local-process:"))
        assert criterion.predicate["command_fingerprint"] == fingerprints[
            1 if new_cwd == "." else 0
        ]
        receipts = [f.content["metadata"]["process_receipt"] for f in final.facts
                    if f.kind is FactKind.TOOL_RESULT
                    and "process_receipt" in f.content.get("metadata", {})]
        assert [r["exit_code"] for r in receipts] == [2, 0]
    finally:
        for close in reversed(composition.close_stack):
            close()

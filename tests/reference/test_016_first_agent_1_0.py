"""016 U1：产品收束所依赖的跨能力 deterministic gates。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agent.cli.actions import (
    build_cancel_goal,
    build_pause_goal,
    build_resume_goal,
)
from agent.continuity.restart import project_restart
from agent.continuity.sessions import StartupDisposition, open_workspace_session
from agent.process.tools import local_process_tool_spec
from agent.provider.protocol import ProviderAuthError, ProviderHTTPRetryableError
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.context_control import reserved_control_schema
from agent.runtime.contracts import (
    ActiveRunStatus,
    CompletionClaim,
    ConversationState,
    DirectResponse,
    FactKind,
    GoalProgress,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, RetryableProviderError
from agent.runtime.state import accept_action
from agent.runtime.tools import KernelToolRuntime
from main import EVERYDAY_INVOCATION_LIMITS, EVERYDAY_SYSTEM_POLICY
from tests.continuity.test_entry_routing import _goal_frame
from tests.kernel.fakes import (
    RUNTIME_GOAL_ID,
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_draft_from_frame,
)


def _submit(state: ConversationState, message: str = "完成这个任务") -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=f"run-{state.next_action_seq}",
        message=message,
    )


def _runtime(
    provider,
    store,
    *,
    workspace_identity_digest: str = "workspace-digest-1",
    limits=EVERYDAY_INVOCATION_LIMITS,
) -> AgentRuntime:  # noqa: ANN001
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
            workspace_identity_digest=workspace_identity_digest,
            authority_snapshot="authority-1",
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=limits,
        invocation_id_factory=lambda: "invocation-016",
    )


def test_everyday_policy_treats_explicit_verifiable_work_as_a_goal() -> None:
    assert "perform and verify a local process" in EVERYDAY_SYSTEM_POLICY
    assert "research into a durable artifact" in EVERYDAY_SYSTEM_POLICY
    assert "set requires_local_process=true" in EVERYDAY_SYSTEM_POLICY
    assert "a file result cannot replace the required successful process receipt" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "do not invent a test-output path" in EVERYDAY_SYSTEM_POLICY
    assert "inspect the bounded workspace for the real test or validation entry point" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "call local_process so the user sees its exact approval" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "never invent or save an output artifact" in EVERYDAY_SYSTEM_POLICY
    assert "use that exact executable and argv directly" in EVERYDAY_SYSTEM_POLICY
    # 2026-10-18 真实层 E3 already-correct 3/3 行为方差：模型把已满足的任务当
    # 「补全覆盖」处理（重写测试/实现）。policy 必须指引先读交付物、已满足则
    # 直接走完成仪式，不做未请求的写入。
    assert (
        "read the SPEC-relevant deliverable files and run the requested validation "
        "before writing" in EVERYDAY_SYSTEM_POLICY
    )
    assert (
        "complete the Goal directly from that evidence instead of writing again"
        in EVERYDAY_SYSTEM_POLICY
    )
    assert "unrequested improvements are not part of the requested outcome" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "never spend local_process authority on workspace discovery" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "A rejection of an unrelated discovery candidate does not prove" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "After the user rejects the exact required local_process approval" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "finish every read-only action that can still advance" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "no such safe advancing action remains" in EVERYDAY_SYSTEM_POLICY
    assert "send blocked_claim instead of retrying that process" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "A question about how such work could be done remains answer-only" in (
        EVERYDAY_SYSTEM_POLICY
    )


def test_conditional_readonly_fallback_does_not_turn_requested_work_into_a_question() -> None:
    assert "A conditional answer-only fallback does not change that task into a question" in (
        EVERYDAY_SYSTEM_POLICY
    )


def test_intent_control_prioritizes_tasks_before_answer_grounding() -> None:
    description = reserved_control_schema()["description"]
    assert isinstance(description, str)
    assert "prose alone cannot satisfy the requested outcome" in description
    assert "If an answer-only question needs grounding" in description


def test_intent_contract_uses_one_prose_only_test_for_mixed_tasks() -> None:
    bootstrap_manager = KernelContextManager(
        system_policy="Be concise.",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        workspace_identity_digest="workspace-digest-1",
        authority_snapshot="authority-1",
    )
    state = ConversationState.new("conversation-intent-contract")
    action = _submit(state, "结合公开资料写入 report.md，然后运行校验器")
    state = accept_action(state, action).state
    pack = bootstrap_manager.build(state, action, ())
    bootstrap = next(
        block
        for message in pack.messages
        for block in message.content
        if block.get("type") == "trusted_goal_bootstrap"
    )
    schema_description = reserved_control_schema()["description"]

    assert "prose-only outcome test" in EVERYDAY_SYSTEM_POLICY
    assert "prose-only outcome test" in bootstrap["decision_rule"]
    assert isinstance(schema_description, str)
    assert "prose alone cannot satisfy the requested outcome" in schema_description
    assert "reading, Web research, artifact creation, and validation" in (
        bootstrap["decision_rule"]
    )
    assert bootstrap["explicit_non_prose_outcome"] is True
    assert pack.control_schema is not None
    assert set(pack.control_schema["input_schema"]["properties"]["kind"]["enum"]) == {
        "goal_proposal",
        "clarification_request",
    }

    question_state = ConversationState.new("conversation-intent-question")
    question = _submit(question_state, "如何写一份 report.md？")
    question_state = accept_action(question_state, question).state
    question_pack = bootstrap_manager.build(question_state, question, ())
    assert question_pack.control_schema is not None
    assert "direct_response" in question_pack.control_schema["input_schema"]["properties"][
        "kind"
    ]["enum"]

    explanation_questions = (
        "运行现有测试会很慢吗？",
        "运行现有测试需要联网吗？",
        "测试失败是什么意思？",
        "构建项目需要哪些依赖？",
        "先查资料再把结果写入 report.md，会更好吗？",
        "看看这个项目再修改 greet.py，会很难吗？",
        "结合资料整理一页说明到 report.md，会很难吗？",
        "Run tests—will that be slow?",
        "调用 MCP 会向外发送数据吗？",
        "委派给子 Agent 会产生额外费用吗？",
        "记住这条信息需要批准吗？",
        # 2026-10-24 P6：礼貌/语气问句释放缺口（trigger 与 release 词表不对称）。
        "Could you check what version of Python this project uses?",
        "删除这个文件可以吗？",
        "测试一下，这个配置对不对？",
        "帮我修改 app.py 可以吗？",
        # 2026-10-24 P2 守卫：新交付动词的问句形式仍可释放回直接回答。
        "整理成 notes.md 可以吗？",
    )
    for index, message in enumerate(explanation_questions, start=1):
        verb_question_state = ConversationState.new(
            f"conversation-intent-verb-question-{index}"
        )
        verb_question = _submit(verb_question_state, message)
        verb_question_state = accept_action(verb_question_state, verb_question).state
        verb_question_pack = bootstrap_manager.build(
            verb_question_state,
            verb_question,
            (),
        )
        assert verb_question_pack.control_schema is not None
        assert "direct_response" in verb_question_pack.control_schema["input_schema"][
            "properties"
        ]["kind"]["enum"]

    explicit_requests = (
        "请运行现有测试。",
        "先通过公开 Web 获取 pathlib 的来源，再把有来源研究结果写入 draft.md。",
        "看看这个项目，把 greet 的标点错误修好，然后运行现有测试确认。只改必要文件。",
        "看看这个项目再修改 greet.py。",
        "结合这份 CSV 和公开资料，整理一页说明到 report.md，然后运行项目里的校验器确认格式。",
        "Can you run the tests?",
        # 2026-10-24 P2：把/将句式接受礼貌前缀；修了 与 修好 同为交付动词。
        "帮我把这个 bug 修了。",
        "Summarize these files into summary.md.",
        # 2026-10-24 审计 E-1：礼貌 check 问句 + 第二祈使 = 复合任务请求，
        # 问句前缀不得把交付语义降级为纯文字回答。
        "Could you check why the build fails, then fix the bug in app.py?",
        "Could you check why the tests fail and update parser.py?",
    )
    for index, message in enumerate(explicit_requests, start=1):
        request_state = ConversationState.new(
            f"conversation-intent-explicit-request-{index}"
        )
        request = _submit(request_state, message)
        request_state = accept_action(request_state, request).state
        request_pack = bootstrap_manager.build(request_state, request, ())
        assert request_pack.control_schema is not None
        assert "direct_response" not in request_pack.control_schema["input_schema"][
            "properties"
        ]["kind"]["enum"]


def test_trial_closeout_policy_requires_checks_for_explicit_behavior() -> None:
    """指引合同，不把这条离线断言当成真实模型必然理解正确的证据。"""

    assert "verify each explicit requirement and the latest correction" in EVERYDAY_SYSTEM_POLICY
    assert "including boundary and negative cases" in EVERYDAY_SYSTEM_POLICY
    assert "Keep unverified requirements pending" in EVERYDAY_SYSTEM_POLICY


def test_artifact_validation_separates_existing_and_process_created_files() -> None:
    assert "approve the bounded process effect first, then call confirm_file" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "materialize and read back that artifact before local_process" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "Process approval alone does not confirm future artifact bytes" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "materialize and read it back before requesting this process" in (
        local_process_tool_spec().description
    )
    assert "direct workspace executable" in local_process_tool_spec().description
    assert "never use list/find/cat" in local_process_tool_spec().description
    assert "never wrap it with sh/bash/python/env" in local_process_tool_spec().description


@pytest.mark.parametrize(
    "message",
    (
        "把结果写入 report.md，然后运行校验器。",
        "看看这个项目，把 greet 的标点错误修好，然后运行现有测试确认。只改必要文件。",
        "结合这份 CSV 和公开资料，整理一页说明到 report.md，然后运行项目里的校验器确认格式。",
        "调用 MCP echo 返回 SABLE-27。",
        "委派给子 Agent 总结两点结论。",
        "请记住：本项目的测试代号是 SABLE-27。",
        # 2026-10-24 P2：非编码文件交付措辞不得经 bare prose 收尾（零文件交付）。
        "把目录内容整理成 notes.md。",
        "阅读 a.md、b.md、c.md，把要点写成 summary.md。",
        "Summarize these files into summary.md.",
    ),
)
def test_explicit_non_prose_outcome_cannot_complete_through_bare_text(
    message: str,
) -> None:
    store = InMemoryCheckpointStore(ConversationState.new("conversation-explicit-task"))
    provider = ScriptedProvider(
        *(
            ModelResponse((ModelTextBlock("已经完成。"),))
            for _ in range(EVERYDAY_INVOCATION_LIMITS.max_invalid_repairs + 1)
        )
    )

    result = _runtime(provider, store).run_turn(
        _submit(store.state, message),
        store.load(),
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_model_control"
    assert store.state.goal is None


def test_paused_goal_reopens_then_resumes_and_cancels_without_effect_replay(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000116",
    )
    assert opened.store is not None and opened.snapshot is not None
    seeded = conversation_with_active_goal(opened.snapshot.state.conversation_id)
    assert seeded.goal is not None
    seeded = replace(
        seeded,
        goal=replace(
            seeded.goal,
            workspace_identity_digest=opened.workspace_identity.identity_digest,
        ),
        workspace_binding=opened.workspace_binding,
    )
    lease = opened.store.try_acquire(seeded.conversation_id)
    assert lease is not None
    try:
        opened.store.compare_and_swap(opened.snapshot, seeded)
    finally:
        lease.release()

    provider = ScriptedProvider()
    runtime = _runtime(
        provider,
        opened.store,
        workspace_identity_digest=opened.workspace_identity.identity_digest,
    )
    paused = runtime.run_turn(build_pause_goal(seeded), opened.store.load())
    assert paused.status is RunStatus.COMPLETED

    reopened = open_workspace_session(workspace, state_root=state_root)
    projection = project_restart(reopened)
    assert reopened.disposition is StartupDisposition.RESUMED
    assert reopened.store is not None and reopened.snapshot is not None
    assert projection.goal_status is GoalStatus.PAUSED
    assert projection.required_action == "resume_goal"
    facts_before = reopened.snapshot.state.facts
    evidence_before = reopened.snapshot.state.evidence_records

    resumed = _runtime(
        provider,
        reopened.store,
        workspace_identity_digest=reopened.workspace_identity.identity_digest,
    ).run_turn(
        build_resume_goal(reopened.snapshot.state),
        reopened.snapshot,
    )
    assert resumed.status is RunStatus.COMPLETED
    resumed_snapshot = reopened.store.load()
    assert resumed_snapshot.state.goal is not None
    assert resumed_snapshot.state.goal.status is GoalStatus.GOAL_READY

    cancelled = _runtime(
        provider,
        reopened.store,
        workspace_identity_digest=reopened.workspace_identity.identity_digest,
    ).run_turn(
        build_cancel_goal(resumed_snapshot.state),
        resumed_snapshot,
    )
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.state.goal is not None
    assert cancelled.state.goal.status is GoalStatus.CANCELLED
    assert cancelled.state.goal.status is not GoalStatus.VERIFIED_DONE
    assert cancelled.state.facts == facts_before
    assert cancelled.state.evidence_records == evidence_before
    assert provider.calls == []


def test_unadvertised_direct_response_repairs_to_goal_proposal() -> None:
    provider = ScriptedProvider(
        *(
            ModelResponse(
                (),
                control=DirectResponse(
                    correlation_id=f"wrong-direct-{index}",
                    text="Here is a prose answer instead.",
                ),
            )
            for index in range(EVERYDAY_INVOCATION_LIMITS.max_invalid_repairs + 1)
        )
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-explicit-control"))

    result = _runtime(provider, store).run_turn(
        _submit(store.state, "把这份 CSV 与公开资料写入 report.md，然后运行校验器。"),
        store.load(),
    )

    assert result.status is RunStatus.FAILED_FATAL
    repairs = [
        fact.content.get("text", "")
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_model_control"
    ]
    assert repairs
    assert all("submit goal_proposal now" in message.casefold() for message in repairs)
    assert all("completion_claim" not in message for message in repairs)


def test_everyday_path_continues_progressing_work_past_8_model_calls(
    tmp_path: Path,
) -> None:
    assert EVERYDAY_INVOCATION_LIMITS.max_model_calls is None
    assert EVERYDAY_INVOCATION_LIMITS.max_run_model_calls == 40
    assert EVERYDAY_INVOCATION_LIMITS.max_run_wall_seconds == 2 * 60 * 60
    assert EVERYDAY_INVOCATION_LIMITS.max_tool_calls is None
    assert EVERYDAY_INVOCATION_LIMITS.max_input_tokens is None
    assert EVERYDAY_INVOCATION_LIMITS.max_output_tokens is None
    assert EVERYDAY_INVOCATION_LIMITS.max_invalid_repairs == 7
    assert EVERYDAY_INVOCATION_LIMITS.max_retryable_provider_retries == 2
    assert EVERYDAY_INVOCATION_LIMITS.max_no_progress_replans == 16

    progresses = tuple(
        GoalProgress(
            correlation_id=f"stalled-016-{index}",
            goal_id=RUNTIME_GOAL_ID,
            goal_revision=1,
            summary=f"只描述进度 {index}",
            next_step="重复同一个下一步",
        )
        for index in range(8)
    )
    provider = ScriptedProvider(
        ModelResponse((), control=goal_draft_from_frame("goal-016", _goal_frame())),
        *(ModelResponse((), control=progress) for progress in progresses),
        RetryableProviderError("temporary outage after continued progress"),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000117",
    )
    assert opened.store is not None and opened.snapshot is not None
    store = opened.store

    result = _runtime(
        provider,
        store,
        workspace_identity_digest=opened.workspace_identity.identity_digest,
    ).run_turn(_submit(store.load().state), store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "provider_retryable"
    assert len(provider.calls) == 10
    final_state = store.load().state
    assert final_state.active_run is not None
    assert final_state.active_run.status is ActiveRunStatus.PAUSED_RETRYABLE
    assert final_state.goal is not None
    assert final_state.goal.status is not GoalStatus.VERIFIED_DONE
    assert not any(fact.kind is FactKind.TOOL_RESULT for fact in final_state.facts)
    assert final_state.evidence_records == ()


def test_no_progress_watchdog_resets_for_a_different_stall_fingerprint() -> None:
    stalled_controls = tuple(
        control
        for index in range(8)
        for control in (
            GoalProgress(
                correlation_id=f"mixed-progress-{index}",
                goal_id=RUNTIME_GOAL_ID,
                goal_revision=1,
                summary=f"still narrating {index}",
                next_step="repeat the same non-action",
            ),
            CompletionClaim(
                correlation_id=f"mixed-completion-{index}",
                goal_id=RUNTIME_GOAL_ID,
                goal_revision=1,
                criterion_evidence_refs=(),
            ),
        )
    )
    provider = ScriptedProvider(
        ModelResponse((), control=goal_draft_from_frame("mixed-goal", _goal_frame())),
        *(ModelResponse((), control=control) for control in stalled_controls),
        RetryableProviderError("different fingerprints reached the next send"),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-mixed-stall"))

    result = _runtime(
        provider,
        store,
        limits=replace(EVERYDAY_INVOCATION_LIMITS, max_model_calls=None),
    ).run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "provider_retryable"
    assert len(provider.calls) == 18
    assert store.state.active_run is not None
    assert store.state.active_run.status is ActiveRunStatus.PAUSED_RETRYABLE
    assert not any(fact.kind is FactKind.TOOL_RESULT for fact in store.state.facts)
    assert store.state.evidence_records == ()
    assert store.state.goal is not None
    assert store.state.goal.status is not GoalStatus.VERIFIED_DONE


def test_retryable_provider_failure_preserves_goal_and_has_zero_tool_effect() -> None:
    initial = conversation_with_active_goal()
    store = InMemoryCheckpointStore(initial)
    provider = ScriptedProvider(RetryableProviderError("temporary outage"))

    result = _runtime(provider, store).run_turn(
        _submit(store.state, "继续当前任务"),
        store.load(),
    )

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "provider_retryable"
    assert store.state.goal == initial.goal
    assert store.state.active_run is not None
    assert store.state.active_run.status is ActiveRunStatus.PAUSED_RETRYABLE
    assert store.state.evidence_records == initial.evidence_records


def test_provider_failure_keeps_safe_adapter_classification_for_recovery() -> None:
    class CodedRetryableError(RetryableProviderError):
        code = "provider_timeout"

    initial = conversation_with_active_goal()
    store = InMemoryCheckpointStore(initial)

    result = _runtime(
        ScriptedProvider(CodedRetryableError("provider_timeout")),
        store,
        limits=replace(
            EVERYDAY_INVOCATION_LIMITS,
            max_retryable_provider_retries=0,
        ),
    ).run_turn(_submit(store.state, "继续当前任务"), store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "provider_timeout"
    assert store.state.goal == initial.goal

    auth_store = InMemoryCheckpointStore(initial)
    auth_result = _runtime(
        ScriptedProvider(ProviderAuthError(status_code=401)), auth_store
    ).run_turn(_submit(auth_store.state, "继续当前任务"), auth_store.load())
    assert auth_result.status is RunStatus.FAILED_FATAL
    assert auth_result.error_code == "provider_auth_error"

    rate_store = InMemoryCheckpointStore(initial)
    rate_result = _runtime(
        ScriptedProvider(ProviderHTTPRetryableError(status_code=429)), rate_store
    ).run_turn(_submit(rate_store.state, "继续当前任务"), rate_store.load())
    assert rate_result.status is RunStatus.FAILED_RETRYABLE
    assert rate_result.error_code == "provider_rate_limit"

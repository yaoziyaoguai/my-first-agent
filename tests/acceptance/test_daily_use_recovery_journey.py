"""S3-C（DU-24）：离线真实链恢复旅程。

真实 composition/Runtime/ToolRuntime/LocalCheckpointStore/ControlInbox/typed
action builder/审批与工具执行链不可绕过；只替换 provider 响应：
任务(产物 v1 + 验证 A/B) → 治理写入 → 验证 A/B → CORRECT 落盘（inbox→安全
边界）→ GoalDelta 重准入 → 按新要求真实改文件(v2) → PAUSE 落盘并返回 →
close → 全新 composition/store/provider 重开 → 仅合法 ResumeGoal → 同命令
新 ID 复测 A/B → VERIFIED_DONE → /new gate 放行且零 provider 调用。
"""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from agent.cli.actions import build_resume_goal
from agent.composition import (
    build_composition,
    build_sandbox_resources,
    build_tool_registrations,
)
from agent.continuity.sessions import StartupDisposition, open_workspace_session
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    CompletionClaim,
    ControlInboxRequest,
    ControlRequestKind,
    EvidenceOracleKind,
    GoalDelta,
    GoalDeltaProposal,
    GoalFrame,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    ProposedCriterion,
    RequirementCoverage,
    SubmitMessage,
)
from agent.runtime.control import ControlInbox
from agent.runtime.loop import InvocationLimits
from tests.kernel.fakes import CollectingSink, goal_draft_from_frame

TASK = (
    "Validate the candidate: 创建 artifact.txt（内容 v1）并 运行 ./check-a "
    "并 运行 ./check-b"
)
CORRECTION_TEXT = "Correction: artifact 内容改为 v2，验证命令不变"
PAUSE_MARKER = "pause-for-reopen-journey"


def _approval_now() -> str:
    return (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _make_fixtures(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    for name in ("check-a", "check-b"):
        script = workspace / name
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(script, stat.S_IRWXU)


def _context_goal(context) -> dict:
    return next(
        (
            block
            for msg in reversed(context.messages)
            for block in msg.content
            if isinstance(block, dict) and block.get("type") == "trusted_goal"
        ),
        {},
    )


def _context_text(context) -> str:
    parts: list[str] = []
    for msg in context.messages:
        for block in msg.content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(getattr(block, "text", "")))
    return "\n".join(parts)


def _sandbox_call(call_id: str, executable: str) -> ModelToolCall:
    return ModelToolCall(
        call_id,
        "sandbox_exec",
        {
            "executable": executable,
            "argv": [],
            "cwd": ".",
            "mode": "read-only",
            "network": "off",
        },
    )


def _claim_for(context, correlation: str) -> CompletionClaim:
    goal = _context_goal(context)
    # R2：coverage 引用投影的 source_fact_ids 与全部 mandatory ids。
    mandatory_ids = tuple(
        item["criterion_id"]
        for item in goal["admitted_criteria"]
        if item.get("mandatory") is True
    )
    return CompletionClaim(
        correlation_id=correlation,
        goal_id=goal["goal_id"],
        goal_revision=goal["goal_revision"],
        criterion_evidence_refs=tuple(goal["expected_completion_evidence_refs"]),
        requirement_coverage=(
            RequirementCoverage(
                requirement_id="requirement:recovery-journey",
                requirement="完成用户要求的修复并通过验证",
                source_fact_ids=tuple(goal["source_fact_ids"]),
                status="satisfied",
                criterion_ids=mandatory_ids,
            ),
        ),
    )


class _JourneyProvider:
    """按 ContextPack 实际内容决策的脚本 provider（两个实例独立计数）。

    阶段由 goal revision/status 与本轮已发生步骤共同决定；CORRECT/PAUSE 通过
    真实 ControlInbox 提交（与 TUI 同一 inbox 契约），Runtime 在安全边界消费。
    """

    def __init__(
        self,
        inbox: ControlInbox,
        *,
        queue_correct: bool,
        conversation_id: str = "00000000-0000-4000-8000-0000000000a1",
    ) -> None:
        self.calls = 0
        self.inbox = inbox
        self.queue_correct = queue_correct
        self.conversation_id = conversation_id
        self.stage = 0

    def _queue_control(self, context, kind: ControlRequestKind) -> None:
        binding = self.inbox.current(self.conversation_id)
        assert binding is not None, "control binding must be open at the poll point"
        self.inbox.submit(
            ControlInboxRequest(
                request_id=f"journey-{kind.value}:{self.calls}",
                kind=kind,
                conversation_id=binding.conversation_id,
                goal_id=binding.goal_id,
                goal_revision=binding.goal_revision,
                invocation_id=binding.invocation_id,
                message=CORRECTION_TEXT if kind is ControlRequestKind.CORRECT else None,
            )
        )

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls += 1
        goal = _context_goal(context)
        status = str(goal.get("status", ""))
        revision = int(goal.get("goal_revision", 0))

        bootstrap = getattr(context, "goal_bootstrap", None)
        # provider2 第一响应：先 no-op delta 消费重开后的补充纠正（工具广告随后恢复）。
        if goal and self.stage == 0 and not self.queue_correct:
            self.stage = 1
            return ModelResponse(
                (),
                control=GoalDeltaProposal(
                    correlation_id="delta-reopen-ack",
                    delta=GoalDelta(
                        goal_id=str(goal["goal_id"]),
                        expected_revision=revision,
                        reason="acknowledge the resume note",
                        updates={"targets": ("artifact.txt",)},
                        updated_at=_approval_now(),
                    ),
                ),
            )
        # 阶段 1：无 Goal → 提案 rev1（用 Runtime 发布的 bootstrap 绑定）。
        if not goal:
            assert bootstrap is not None
            frame = GoalFrame(
                goal_id="goal-recovery",
                revision=1,
                created_from_fact_ids=(bootstrap.source_fact_id,),
                workspace_identity_digest=bootstrap.workspace_identity_digest,
                user_outcome="artifact v1 written and both validations pass",
                beneficiary="user",
                targets=("artifact.txt",),
                scope=("workspace",),
                non_goals=(),
                assumptions=(),
                proposed_criteria=(
                    ProposedCriterion(
                        "criterion:model-validation",
                        "the requested validations pass",
                        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                    ),
                ),
                admitted_criteria=(),
                authority_snapshot=bootstrap.authority_snapshot,
                status=GoalStatus.GOAL_READY,
                created_at="2026-10-09T00:00:00Z",
                updated_at="2026-10-09T00:00:00Z",
            )
            return ModelResponse((), control=goal_draft_from_frame("proposal-r", frame))


        # 阶段推进：run1 = goal → write v1 → 验证 A/B → 入队 CORRECT；
        # run2 = delta 重准入 → write v2 → 入队 PAUSE；reopen = 复测 A/B → claim。
        assert bootstrap is not None or revision >= 1
        if revision == 1:
            if self.stage == 1:
                self.stage = 2
                return ModelResponse(
                    (
                        ModelToolCall(
                            "write-v1",
                            "write_file",
                            {"path": "artifact.txt", "content": "v1\n"},
                        ),
                    )
                )
            if self.stage == 2:
                self.stage = 3
                return ModelResponse((_sandbox_call("validate-a", "./check-a"),))
            if self.stage == 3:
                self.stage = 4
                return ModelResponse((_sandbox_call("validate-b", "./check-b"),))
            if self.stage == 4:
                assert "artifact.txt" in _context_text(context)
                self.stage = 5
                self._queue_control(context, ControlRequestKind.CORRECT)
                return ModelResponse((ModelTextBlock("requested correction"),))
            self.stage = 1
            return ModelResponse((ModelTextBlock("ready to start"),))

        delta_receipts = [
            r
            for r in (context.control_receipts or ())
            if r.control_kind == "goal_delta_proposal"
        ]
        if status == GoalStatus.NEEDS_AUTHORITY.value:
            # CORRECT 已落盘（rev2）：语义 delta 消费 inbox 纠正。
            assert CORRECTION_TEXT in _context_text(context), (
                "correction fact must be visible in the ContextPack"
            )
            goal_id = str(goal["goal_id"])
            self.stage = 6
            return ModelResponse(
                (),
                control=GoalDeltaProposal(
                    correlation_id=f"delta-recovery-{revision}",
                    delta=GoalDelta(
                        goal_id=goal_id,
                        expected_revision=revision,
                        reason="user corrected the artifact content",
                        updates={
                            "user_outcome": (
                                "artifact.txt rewritten to v2 per the user's "
                                "correction, then both validations pass"
                            )
                        },
                        updated_at=_approval_now(),
                    ),
                ),
            )
        if (
            self.stage == 6
            and len(delta_receipts) == 1
            and "continue under" in _context_text(context)
        ):
            # run2 开场消息成为第二条纠正：no-op delta 消费它（不制造新 revision）。
            self.stage = 7
            goal_id = str(goal["goal_id"])
            return ModelResponse(
                (),
                control=GoalDeltaProposal(
                    correlation_id="delta-recovery-noop",
                    delta=GoalDelta(
                        goal_id=goal_id,
                        expected_revision=revision,
                        reason="acknowledge the operator continuation note",
                        updates={"targets": ("artifact.txt",)},
                        updated_at=_approval_now(),
                    ),
                ),
            )
        if revision >= 3 and status == GoalStatus.GOAL_READY.value and len(delta_receipts) >= 2:
            if self.stage == 7:
                self.stage = 8
                return ModelResponse(
                    (
                        ModelToolCall(
                            "write-v2",
                            "write_file",
                            {"path": "artifact.txt", "content": "v2\n"},
                        ),
                    )
                )
            if self.stage == 8:
                self.stage = 9
                return ModelResponse(
                    (
                        ModelToolCall(
                            "readback-v2",
                            "read_file",
                            {"path": "artifact.txt"},
                        ),
                    )
                )
            if self.stage == 9:
                self.stage = 10
                self._queue_control(context, ControlRequestKind.PAUSE)
                return ModelResponse((ModelTextBlock(PAUSE_MARKER),))
        if status == GoalStatus.PAUSED.value:
            # 不应到达：PAUSE 消费后 run 由 Runtime 返回，不再调用 provider。
            raise AssertionError("provider must not be called after durable pause")
        is_provider2 = not self.queue_correct and self.stage >= 1
        if (
            status in {GoalStatus.GOAL_READY.value, GoalStatus.EXECUTING.value}
            and revision >= 3
            and is_provider2
        ):
            # reopen 恢复后的复测阶段（provider2 实例）。
            if self.stage == 1:
                assert TASK in _context_text(context), "original task must be visible"
                assert CORRECTION_TEXT in _context_text(context), (
                    "correction must still be visible after reopen"
                )
                self.stage = 2
                return ModelResponse((_sandbox_call("validate-a-2", "./check-a"),))
            if self.stage == 2:
                self.stage = 3
                return ModelResponse((_sandbox_call("validate-b-2", "./check-b"),))
            if self.stage == 3:
                self.stage = 4
                return ModelResponse((), control=_claim_for(context, "claim-recovery"))
        return ModelResponse((ModelTextBlock("no scripted step"),))


def _open_and_drive(tmp_path: Path, provider, inbox: ControlInbox):
    opened = open_workspace_session(
        tmp_path / "workspace",
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-0000000000a1",
    )
    binding = opened.workspace_binding
    registrations = tuple(
        build_tool_registrations(
            workspace=tmp_path / "workspace",
            protected_paths=(opened.checkpoint_path,),
            max_tool_result_chars=50_000,
        )
    ) + tuple(
        build_sandbox_resources(
            tmp_path / "workspace",
            tmp_path / "state",
            "/usr/bin:/bin",
            host_home=Path.home(),
        ).registrations
    )
    composition = build_composition(
        provider=provider,
        checkpoint_store=opened.store,
        tool_registrations=registrations,
        event_sink=CollectingSink(),
        control_inbox=inbox,
        system_policy="Complete the task with exact evidence.",
        context_limits=ContextLimits(max_input_tokens=100_000, output_reserve=5_000),
        invocation_limits=InvocationLimits(),
        workspace_identity_digest=binding.workspace_identity_digest,
        context_scope_digest=binding.workspace_scope_digest,
        workspace_binding=binding,
    )
    return opened, composition


def _submit(state, run_id: str, message: str) -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=run_id,
        message=message,
    )


def _executed_call_ids(state) -> list[str]:
    from agent.runtime.contracts import FactKind

    return [
        str(fact.content.get("tool_call_id"))
        for fact in state.facts
        if fact.kind is FactKind.TOOL_RESULT
        and fact.content.get("executed") is True
        and fact.content.get("is_error") is False
    ]


def test_recovery_journey_correct_pause_reopen_complete(tmp_path: Path) -> None:
    """DU-24：CORRECT 落盘→真实改文件→PAUSE 落盘→重开→同命令新 ID 复测→
    VERIFIED_DONE→/new 放行且零 provider 调用。"""

    from agent.cli.actions import new_session_gate

    _make_fixtures(tmp_path)
    inbox1 = ControlInbox()
    provider1 = _JourneyProvider(inbox1, queue_correct=True)
    opened1, composition1 = _open_and_drive(tmp_path, provider1, inbox1)
    state = opened1.store.load().state
    composition1.runtime.run_turn(
        _submit(state, "run-recovery-1", TASK), opened1.store.load()
    )
    _approve_pending(opened1, composition1)

    state = LocalCheckpointStore(opened1.checkpoint_path).load().state
    # CORRECT 已在安全边界落盘：fact + receipt + rev2 NEEDS_AUTHORITY。
    assert any(
        fact.content.get("control") == "goal_correction"
        and fact.content.get("text") == CORRECTION_TEXT
        for fact in state.facts
    ), "correction fact must be durable"
    assert state.goal is not None and state.goal.revision == 2
    assert state.goal.status is GoalStatus.NEEDS_AUTHORITY
    assert any(
        receipt.control_kind == "goal_correct" for receipt in state.control_receipts
    )
    assert (tmp_path / "workspace" / "artifact.txt").read_text() == "v1\n"
    assert "write-v1" in _executed_call_ids(state)

    # run 2：delta 重准入 → 真实改文件 v2 → PAUSE 落盘并返回。
    composition1.runtime.run_turn(
        _submit(state, "run-recovery-2", "continue under the corrected requirement"),
        opened1.store.load(),
    )
    _approve_pending(opened1, composition1)
    state = LocalCheckpointStore(opened1.checkpoint_path).load().state
    assert state.goal is not None and state.goal.revision >= 3
    assert state.goal.status is GoalStatus.PAUSED, state.goal.status
    assert any(
        receipt.control_kind == "goal_pause" for receipt in state.control_receipts
    ), "pause receipt must be durable"
    assert (tmp_path / "workspace" / "artifact.txt").read_text() == "v2\n", (
        "the correction must really rewrite the file before pausing"
    )
    assert "write-v2" in _executed_call_ids(state)

    # ---- close：丢弃全部进程内对象；仅 durable checkpoint 存续 ----
    checkpoint_path = opened1.checkpoint_path
    pre_reopen_facts = len(state.facts)
    del state, composition1, opened1, provider1

    # ---- reopen：全新 store/composition/provider；仅合法 ResumeGoal ----
    inbox2 = ControlInbox()
    provider2 = _JourneyProvider(inbox2, queue_correct=False)
    opened2 = open_workspace_session(
        tmp_path / "workspace",
        state_root=tmp_path / "state",
    )
    assert opened2.disposition is StartupDisposition.RESUMED
    _composition2 = None
    opened2_binding = opened2.workspace_binding
    registrations2 = tuple(
        build_tool_registrations(
            workspace=tmp_path / "workspace",
            protected_paths=(opened2.checkpoint_path,),
            max_tool_result_chars=50_000,
        )
    ) + tuple(
        build_sandbox_resources(
            tmp_path / "workspace",
            tmp_path / "state",
            "/usr/bin:/bin",
            host_home=Path.home(),
        ).registrations
    )
    from agent.composition import build_composition as _bc

    composition2 = _bc(
        provider=provider2,
        checkpoint_store=opened2.store,
        tool_registrations=registrations2,
        event_sink=CollectingSink(),
        control_inbox=inbox2,
        system_policy="Complete the task with exact evidence.",
        context_limits=ContextLimits(max_input_tokens=100_000, output_reserve=5_000),
        invocation_limits=InvocationLimits(),
        workspace_identity_digest=opened2_binding.workspace_identity_digest,
        context_scope_digest=opened2_binding.workspace_scope_digest,
        workspace_binding=opened2_binding,
    )
    resumed_state = LocalCheckpointStore(checkpoint_path).load().state
    assert resumed_state.goal is not None
    assert resumed_state.goal.status is GoalStatus.PAUSED
    assert len(resumed_state.facts) == pre_reopen_facts

    composition2.runtime.run_turn(
        build_resume_goal(resumed_state), opened2.store.load()
    )
    resumed2 = LocalCheckpointStore(opened2.checkpoint_path).load().state
    assert resumed2.goal.status is GoalStatus.GOAL_READY
    # 合法继续：一条普通继续消息（按产品语义成为补充纠正，provider2 以 no-op
    # delta 消费后工具广告恢复；不重述原任务、不重新注入原纠正）。
    composition2.runtime.run_turn(
        _submit(
            resumed2,
            "run-recovery-resume",
            "resume work under the corrected requirement",
        ),
        opened2.store.load(),
    )
    _approve_pending(opened2, composition2)

    final_state = LocalCheckpointStore(opened2.checkpoint_path).load().state
    assert final_state.goal is not None
    assert final_state.goal.status is GoalStatus.VERIFIED_DONE, (
        final_state.goal.status,
        [c.criterion_id for c in final_state.goal.admitted_criteria],
    )
    assert (tmp_path / "workspace" / "artifact.txt").read_text() == "v2\n"
    # 同命令新 ID 真执行：A/B 各两次（第一次在纠正前、复测在重开后）。
    executed = _executed_call_ids(final_state)
    assert executed.count("validate-a") == 1 and "validate-a-2" in executed
    assert executed.count("validate-b") == 1 and "validate-b-2" in executed
    assert "write-v1" in executed and "write-v2" in executed
    # 复测不重放：validate-a-2/b-2 是 reopened run 里的真实执行。
    assert provider2.calls >= 3
    # 完成证据引用 reopen 后的新 receipt fact。
    evidence_fact_ids = {
        fact_id
        for record in final_state.evidence_records
        for fact_id in record.source_fact_ids
    }
    assert any("validate-a-2" in fact_id for fact_id in evidence_fact_ids)
    assert any("validate-b-2" in fact_id for fact_id in evidence_fact_ids)
    # /new gate：VERIFIED_DONE 放行；gate 是纯函数，零 provider 调用。
    calls_before_gate = provider2.calls
    assert new_session_gate(final_state) is None
    assert provider2.calls == calls_before_gate


def _approve_pending(opened, composition) -> None:
    from agent.cli.app import _parse_action as _parse

    for _ in range(16):
        state = LocalCheckpointStore(opened.checkpoint_path).load().state
        active = state.active_run
        if active is None or active.pending_request is None:
            return
        action, error = _parse(
            f"/approve {active.pending_request.request_id}",
            state,
            lambda: "run-unused",
            approval_time_factory=_approval_now,
        )
        assert error is None and action is not None
        composition.runtime.run_turn(action, opened.store.load())

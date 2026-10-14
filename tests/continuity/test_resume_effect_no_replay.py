"""V1（2026-10-12 补漏）：新进程 resume 无隐式重放——可观察副作用证明。

两段式报告（避免空洞证明）：
1. 恢复控制本身零效果：新进程 ResumeGoal 不调用 provider/tool，物理效果计数不变。
2. 恢复后经生产 model/tool loop 推进：scripted provider 不提出新的副作用意图
   （或提出新的合法新意图 Y），从物理 ledger 计数 X/Y，不从 call ID 推算。

独立 workspace/state root；效果工具 = append+flush+fsync 的可数非幂等动作。
崩溃窗口用 marker 触发的 os._exit 模拟（不是生产 failpoint）；EXECUTING
崩溃后新进程的合法入口是 Resume → AWAITING_RECOVERY（UNKNOWN 须显式分类）。
负对照：新 call ID 重复相同逻辑效果必须被发现（计数/归因单独记录）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import agent

# 产品导入根（开发态=仓库根；安装态=site-packages）与测试树根分开推导，
# 子进程 PYTHONPATH 产品根在前，保证安装态下 agent 从 site-packages 导入。
PRODUCT_ROOT = str(Path(agent.__file__).resolve().parents[1])
TESTS_ROOT = str(Path(__file__).resolve().parents[2])


def _ledger_count(workspace: Path, tag: str) -> int:
    ledger = workspace / "ledger.txt"
    if not ledger.exists():
        return 0
    return sum(
        1
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line == tag
    )


def _build_runtime(
    store,
    provider,
    workspace: Path,
    *,
    require_approval: bool = False,
):
    from agent.runtime.checkpoint import LocalCheckpointStore  # noqa: F401
    from agent.runtime.context import ContextLimits, KernelContextManager
    from agent.runtime.contracts import (
        ApprovalPolicy,
        ExecutionAuthorityClass,
        OutputPolicy,
        SideEffectClass,
        ToolRisk,
        ToolSpec,
    )
    from agent.runtime.loop import AgentRuntime, InvocationLimits
    from agent.runtime.tools import KernelToolRuntime, RegisteredTool
    from tests.kernel.fakes import CollectingSink

    def ledger_append(intent):
        tag = str(intent.arguments["tag"])
        crash = os.environ.get("V1_CRASH_MODE", "")
        if crash == "before" and not (workspace / "ledger.txt").exists():
            os._exit(9)
        with (workspace / "ledger.txt").open("a", encoding="utf-8") as stream:
            stream.write(tag + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if crash == "after":
            os._exit(9)
        return json.dumps({"tag": tag, "counted": True})

    def ledger_read(_intent):
        ledger = workspace / "ledger.txt"
        return (
            ledger.read_text(encoding="utf-8") if ledger.exists() else ""
        )

    spec = ToolSpec(
        name="ledger_append",
        version="1",
        description="append one tag line to ledger.txt",
        input_schema={
            "type": "object",
            "properties": {"tag": {"type": "string"}},
            "required": ["tag"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=(
            ApprovalPolicy.ALWAYS if require_approval else ApprovalPolicy.NEVER
        ),
        safety_policy={},
        output_limit_chars=100,
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    read_spec = ToolSpec(
        name="ledger_read",
        version="1",
        description="read the ledger",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=200,
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    registrations = (
        RegisteredTool(spec, ledger_append),
        RegisteredTool(read_spec, ledger_read),
    )
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
            workspace_identity_digest="workspace-v1",
        ),
        tool_runtime=KernelToolRuntime(registrations),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_model_calls=8),
        invocation_id_factory=lambda: "invocation-v1",
    )


class _StageProvider:
    """按 stage 脚本出响应；记录每次收到的 ContextPack 概要与调用次数。"""

    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, context, *, delta_observer=None):
        self.calls.append(
            {
                "messages": len(context.messages),
                "has_system": bool(context.system),
            }
        )
        from tests.kernel.fakes import bind_runtime_goal

        response = self._responses.pop(0)
        if callable(response):
            response = response(context)
        return bind_runtime_goal(response, context)


def _print_result(payload: dict) -> None:
    print("RESULT-LINE " + json.dumps(payload, ensure_ascii=False))


def _run_stage(
    stage: str,
    workspace: Path,
    state_root: Path,
    *,
    crash_mode: str = "",
) -> tuple[int, dict | None]:
    """独立 OS 进程执行 stage；返回 (exit code, RESULT-LINE payload)。"""

    # LocalCheckpointStore 要求 checkpoint 目录 0700；测试预建目录需对齐。
    state_root.mkdir(parents=True, exist_ok=True)
    state_root.chmod(0o700)
    env = dict(
        os.environ,
        V1_CRASH_MODE=crash_mode,
        PYTHONPATH=f"{PRODUCT_ROOT}:{TESTS_ROOT}",
    )
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), stage,
         str(workspace), str(state_root)],
        capture_output=True,
        text=True,
        cwd=str(TESTS_ROOT),
        env=env,
        timeout=120,
    )
    payload = None
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT-LINE "):
            payload = json.loads(line[len("RESULT-LINE ") :])
    if proc.returncode == 0 and payload is None:
        raise AssertionError(
            f"stage {stage} exited 0 without RESULT-LINE:\n{proc.stderr[-2000:]}"
        )
    return proc.returncode, payload


def _run_a_stage(workspace: Path, state_root: Path, *, crash_mode: str = "") -> None:
    from agent.runtime.checkpoint import LocalCheckpointStore
    from agent.runtime.contracts import (
        BlockedClaim,
        ConversationState,
        GoalDraftProposal,
        GoalStatus,
        ModelResponse,
        ModelToolCall,
        PauseGoal,
        ProposedCriterion,
        RunStatus,
        SubmitMessage,
    )
    from tests.kernel.fakes import RUNTIME_GOAL_ID
    workspace.mkdir(parents=True, exist_ok=True)
    store = LocalCheckpointStore.initialize(
        state_root / "checkpoint.json",
        ConversationState.new("conversation-1"),
    )
    provider = _StageProvider(
        [
            ModelResponse(
                (),
                control=GoalDraftProposal(
                    correlation_id="draft-1",
                    user_outcome="append the X effect to the ledger",
                    beneficiary="user",
                    targets=("workspace",),
                    scope=("workspace",),
                    non_goals=(),
                    assumptions=(),
                    proposed_criteria=(
                        ProposedCriterion(
                            "criterion-x",
                            "the ledger holds the X effect",
                        ),
                    ),
                    next_step="append X",
                ),
            ),
            ModelResponse(
                (ModelToolCall("call-x", "ledger_append", {"tag": "X"}),),
            ),
            ModelResponse(
                (),
                control=BlockedClaim(
                    correlation_id="blocked-run-a",
                    goal_id=RUNTIME_GOAL_ID,
                    goal_revision=1,
                    blocker="the ledger effect is recorded; no further safe action",
                    safe_attempts=("appended the X effect",),
                    resume_condition="provide the next instruction",
                ),
            ),
        ]
    )
    runtime = _build_runtime(store, provider, workspace)
    state = store.load().state
    submitted = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-a",
            message="append the X effect to the ledger",
        ),
        store.load(),
    )
    assert submitted.status is RunStatus.COMPLETED, submitted.error_code
    durable = store.load().state
    assert durable.goal is not None
    pause = PauseGoal(
        conversation_id=durable.conversation_id,
        action_seq=durable.next_action_seq,
        expected_revision=durable.revision,
        goal_id=durable.goal.goal_id,
        goal_revision=durable.goal.revision,
    )
    paused = runtime.run_turn(pause, store.load())
    assert paused.status is RunStatus.COMPLETED, paused.error_code
    durable = store.load().state
    assert durable.goal is not None
    assert durable.goal.status is GoalStatus.PAUSED
    _print_result(
        {
            "stage": "run_a",
            "ledger_x": _ledger_count(workspace, "X"),
            "goal_status": durable.goal.status.value,
        }
    )


def _run_b_resume_only(workspace: Path, state_root: Path) -> None:
    from agent.runtime.checkpoint import LocalCheckpointStore
    from agent.runtime.contracts import (
        BlockedClaim,
        GoalDelta,
        GoalDeltaProposal,
        GoalStatus,
        ModelResponse,
        ModelToolCall,
        ResumeGoal,
        RunStatus,
        SubmitMessage,
    )

    store = LocalCheckpointStore(state_root / "checkpoint.json")
    assert _ledger_count(workspace, "X") == 1
    state = store.load().state
    goal = state.goal
    assert goal is not None
    assert goal.status is GoalStatus.PAUSED
    provider = _StageProvider(
        [
            ModelResponse(
                (),
                control=GoalDeltaProposal(
                    correlation_id="delta-continue-1",
                    delta=GoalDelta(
                        goal_id=goal.goal_id,
                        expected_revision=goal.revision,
                        reason="the user asked to continue the existing Goal",
                        updates={"targets": list(goal.targets)},
                    ),
                ),
            ),
            ModelResponse(
                (ModelToolCall("call-read-1", "ledger_read", {}),),
            ),
            ModelResponse(
                (),
                control=BlockedClaim(
                    correlation_id="blocked-continue-1",
                    goal_id=goal.goal_id,
                    goal_revision=goal.revision,
                    blocker="no further safe action is currently available",
                    safe_attempts=("read the ledger",),
                    resume_condition="provide the next instruction",
                ),
            ),
        ]
    )
    runtime = _build_runtime(store, provider, workspace)
    resumed = runtime.run_turn(
        ResumeGoal(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
        ),
        store.load(),
    )
    assert resumed.status is RunStatus.COMPLETED, resumed.error_code
    assert len(provider.calls) == 0
    assert _ledger_count(workspace, "X") == 1
    state = store.load().state
    replied = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-b-continue",
            message="继续当前任务",
        ),
        store.load(),
    )
    assert replied.status is RunStatus.COMPLETED, replied.error_code
    durable = store.load().state
    assert durable.goal is not None
    assert durable.goal.status is GoalStatus.BLOCKED
    assert _ledger_count(workspace, "X") == 1
    _print_result(
        {
            "stage": "run_b_resume_only",
            "resume_provider_calls": 0,
            "ledger_x": 1,
            "continue_status": replied.status.value,
            "continue_goal_status": durable.goal.status.value,
        }
    )


def _run_b_xy(workspace: Path, state_root: Path) -> None:
    from agent.runtime.checkpoint import LocalCheckpointStore
    from agent.runtime.contracts import (
        BlockedClaim,
        GoalDelta,
        GoalDeltaProposal,
        GoalStatus,
        ModelResponse,
        ModelToolCall,
        ResumeGoal,
        RunStatus,
        SubmitMessage,
    )

    store = LocalCheckpointStore(state_root / "checkpoint.json")
    assert _ledger_count(workspace, "X") == 1
    state = store.load().state
    goal = state.goal
    assert goal is not None
    assert goal.status is GoalStatus.PAUSED
    provider = _StageProvider(
        [
            ModelResponse(
                (),
                control=GoalDeltaProposal(
                    correlation_id="delta-continue-y",
                    delta=GoalDelta(
                        goal_id=goal.goal_id,
                        expected_revision=goal.revision,
                        reason="the user asked to continue the existing Goal",
                        updates={"targets": list(goal.targets)},
                    ),
                ),
            ),
            ModelResponse(
                (ModelToolCall("call-y", "ledger_append", {"tag": "Y"}),),
            ),
            ModelResponse(
                (),
                control=BlockedClaim(
                    correlation_id="blocked-continue-y",
                    goal_id=goal.goal_id,
                    goal_revision=goal.revision,
                    blocker="no further safe action is currently available",
                    safe_attempts=("appended the new Y effect",),
                    resume_condition="provide the next instruction",
                ),
            ),
        ]
    )
    runtime = _build_runtime(store, provider, workspace)
    resumed = runtime.run_turn(
        ResumeGoal(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
        ),
        store.load(),
    )
    assert resumed.status is RunStatus.COMPLETED, resumed.error_code
    assert len(provider.calls) == 0
    assert _ledger_count(workspace, "Y") == 0
    state = store.load().state
    advanced = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-b-new-effect",
            message="继续当前任务",
        ),
        store.load(),
    )
    assert advanced.status is RunStatus.COMPLETED, advanced.error_code
    assert _ledger_count(workspace, "X") == 1
    assert _ledger_count(workspace, "Y") == 1
    _print_result(
        {
            "stage": "run_b_xy",
            "ledger_x": 1,
            "ledger_y": 1,
        }
    )


def _run_b_duplicate(workspace: Path, state_root: Path) -> None:
    from agent.runtime.checkpoint import LocalCheckpointStore
    from agent.runtime.contracts import (
        BlockedClaim,
        GoalDelta,
        GoalDeltaProposal,
        GoalStatus,
        ModelResponse,
        ModelToolCall,
        ResumeGoal,
        RunStatus,
        SubmitMessage,
    )

    store = LocalCheckpointStore(state_root / "checkpoint.json")
    assert _ledger_count(workspace, "X") == 1
    state = store.load().state
    goal = state.goal
    assert goal is not None
    assert goal.status is GoalStatus.PAUSED
    provider = _StageProvider(
        [
            ModelResponse(
                (),
                control=GoalDeltaProposal(
                    correlation_id="delta-continue-dup",
                    delta=GoalDelta(
                        goal_id=goal.goal_id,
                        expected_revision=goal.revision,
                        reason="the user asked to continue the existing Goal",
                        updates={"targets": list(goal.targets)},
                    ),
                ),
            ),
            ModelResponse(
                (ModelToolCall("call-dup-1", "ledger_append", {"tag": "X"}),),
            ),
            ModelResponse(
                (),
                control=BlockedClaim(
                    correlation_id="blocked-continue-dup",
                    goal_id=goal.goal_id,
                    goal_revision=goal.revision,
                    blocker="no further safe action is currently available",
                    safe_attempts=("appended a second physical X line",),
                    resume_condition="provide the next instruction",
                ),
            ),
        ]
    )
    runtime = _build_runtime(store, provider, workspace)
    resumed = runtime.run_turn(
        ResumeGoal(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
        ),
        store.load(),
    )
    assert resumed.status is RunStatus.COMPLETED, resumed.error_code
    assert len(provider.calls) == 0
    assert _ledger_count(workspace, "X") == 1
    state = store.load().state
    advanced = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-b-duplicate",
            message="继续当前任务",
        ),
        store.load(),
    )
    assert advanced.status is RunStatus.COMPLETED, advanced.error_code
    ledger_x = _ledger_count(workspace, "X")
    _print_result(
        {
            "stage": "run_b_duplicate",
            "ledger_x": ledger_x,
            "detected": ledger_x != 1,
        }
    )


def _run_b_after_crash(workspace: Path, state_root: Path) -> None:
    from agent.runtime.checkpoint import LocalCheckpointStore
    from agent.runtime.contracts import Resume, RunStatus

    store = LocalCheckpointStore(state_root / "checkpoint.json")
    provider = _StageProvider([])
    runtime = _build_runtime(store, provider, workspace)
    state = store.load().state
    resumed = runtime.run_turn(
        Resume(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
        ),
        store.load(),
    )
    assert resumed.status is RunStatus.AWAITING_RECOVERY, resumed.status
    assert resumed.request is not None
    assert len(provider.calls) == 0
    _print_result(
        {
            "stage": "run_b_after_crash",
            "status": resumed.status.value,
            "provider_calls": 0,
            "ledger_x": _ledger_count(workspace, "X"),
            "recovery_request_tool_call_id": resumed.request.tool_call_id,
        }
    )


def _run_approval_pause(workspace: Path, state_root: Path) -> None:
    """R1-T6 进程 A：审批 pending 时 /pause，同一 CAS 闭合未开始批次。"""

    from agent.runtime.checkpoint import LocalCheckpointStore
    from agent.runtime.contracts import (
        ConversationState,
        GoalDraftProposal,
        ModelResponse,
        ModelToolCall,
        PauseGoal,
        ProposedCriterion,
        RunStatus,
        SubmitMessage,
    )

    workspace.mkdir(parents=True, exist_ok=True)
    store = LocalCheckpointStore.initialize(
        state_root / "checkpoint.json",
        ConversationState.new("conversation-approval"),
    )
    provider = _StageProvider(
        [
            ModelResponse(
                (),
                control=GoalDraftProposal(
                    correlation_id="draft-approval",
                    user_outcome="append the A effect to the ledger",
                    beneficiary="user",
                    targets=("workspace",),
                    scope=("workspace",),
                    non_goals=(),
                    assumptions=(),
                    proposed_criteria=(
                        ProposedCriterion(
                            "criterion-a",
                            "the ledger holds the A effect",
                        ),
                    ),
                    next_step="append A",
                ),
            ),
            ModelResponse(
                (ModelToolCall("call-approve", "ledger_append", {"tag": "A"}),),
            ),
        ]
    )
    runtime = _build_runtime(store, provider, workspace, require_approval=True)
    state = store.load().state
    submitted = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-approval",
            message="append the A effect to the ledger",
        ),
        store.load(),
    )
    assert submitted.status is RunStatus.AWAITING_APPROVAL, submitted.status
    assert _ledger_count(workspace, "A") == 0
    durable = store.load().state
    assert durable.active_run is not None
    assert durable.active_run.pending_request is not None
    assert durable.goal is not None
    paused = runtime.run_turn(
        PauseGoal(
            conversation_id=durable.conversation_id,
            action_seq=durable.next_action_seq,
            expected_revision=durable.revision,
            goal_id=durable.goal.goal_id,
            goal_revision=durable.goal.revision,
        ),
        store.load(),
    )
    assert paused.status is RunStatus.COMPLETED, paused.error_code
    durable = store.load().state
    assert durable.active_run is None
    assert durable.goal is not None
    _print_result(
        {
            "stage": "run_approval_pause",
            "goal_status": durable.goal.status.value,
            "ledger_a": _ledger_count(workspace, "A"),
        }
    )


def _run_approval_resume_continue(workspace: Path, state_root: Path) -> None:
    """R1-T6 进程 B：新进程重开审批 pause 现场；无重述继续，零执行。"""

    from agent.runtime.checkpoint import LocalCheckpointStore
    from agent.runtime.contracts import (
        BlockedClaim,
        FactKind,
        GoalDelta,
        GoalDeltaProposal,
        GoalStatus,
        ModelResponse,
        ModelToolCall,
        ResumeGoal,
        RunStatus,
        SubmitMessage,
    )
    from tests.kernel.fakes import RUNTIME_GOAL_ID

    store = LocalCheckpointStore(state_root / "checkpoint.json")
    state = store.load().state
    goal = state.goal
    assert goal is not None
    assert goal.status is GoalStatus.PAUSED
    assert state.active_run is None
    closed = [
        fact
        for fact in state.facts
        if fact.content.get("tool_call_id") == "call-approve"
    ]
    assert len(closed) == 1, "pause must close the unapproved call in the same CAS"
    assert closed[0].content.get("executed") is False
    assert closed[0].content.get("superseded") is True
    assert closed[0].content.get("is_error") is True
    kinds = [fact.kind for fact in state.facts]
    assert kinds[kinds.index(FactKind.TOOL_CALLS) + 1] is FactKind.TOOL_RESULT

    provider = _StageProvider(
        [
            ModelResponse(
                (),
                control=GoalDeltaProposal(
                    correlation_id="delta-approval",
                    delta=GoalDelta(
                        goal_id=RUNTIME_GOAL_ID,
                        expected_revision=goal.revision,
                        reason="the user asked to continue the existing Goal",
                        updates={"targets": list(goal.targets)},
                    ),
                ),
            ),
            ModelResponse(
                (ModelToolCall("call-read-approval", "ledger_read", {}),),
            ),
            ModelResponse(
                (),
                control=BlockedClaim(
                    correlation_id="blocked-approval",
                    goal_id=RUNTIME_GOAL_ID,
                    goal_revision=goal.revision,
                    blocker="the paused batch is closed; a new instruction is required",
                    safe_attempts=("read the ledger",),
                    resume_condition="provide the next instruction",
                ),
            ),
        ]
    )
    runtime = _build_runtime(store, provider, workspace)
    resumed = runtime.run_turn(
        ResumeGoal(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
        ),
        store.load(),
    )
    assert resumed.status is RunStatus.COMPLETED, resumed.error_code
    assert len(provider.calls) == 0
    state = store.load().state
    advanced = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-approval-continue",
            message="继续当前任务",
        ),
        store.load(),
    )
    assert advanced.status is RunStatus.COMPLETED, advanced.error_code
    durable = store.load().state
    assert durable.goal is not None
    assert durable.goal.status is GoalStatus.BLOCKED
    assert _ledger_count(workspace, "A") == 0
    _print_result(
        {
            "stage": "run_approval_resume_continue",
            "resume_provider_calls": 0,
            "ledger_a": 0,
            "continue_goal_status": durable.goal.status.value,
            "closed_executed": False,
        }
    )


def _run_b_after_crash_resolve(workspace: Path, state_root: Path) -> None:
    """R1-T6 进程 B：崩溃后的 UNKNOWN 由操作者分类；同一 run 继续，零重放。"""

    from agent.runtime.checkpoint import LocalCheckpointStore
    from agent.runtime.contracts import (
        BlockedClaim,
        ModelResponse,
        RecoveryResolution,
        ResolveUnknownToolOutcome,
        Resume,
        RunStatus,
    )
    from tests.kernel.fakes import RUNTIME_GOAL_ID

    store = LocalCheckpointStore(state_root / "checkpoint.json")
    assert _ledger_count(workspace, "X") == 1
    provider = _StageProvider(
        [
            ModelResponse(
                (),
                control=BlockedClaim(
                    correlation_id="blocked-after-recovery",
                    goal_id=RUNTIME_GOAL_ID,
                    goal_revision=1,
                    blocker="the classified effect is recorded; no further safe action",
                    safe_attempts=("classified the unknown X effect as succeeded",),
                    resume_condition="provide the next instruction",
                ),
            ),
        ]
    )
    runtime = _build_runtime(store, provider, workspace)
    state = store.load().state
    resumed = runtime.run_turn(
        Resume(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
        ),
        store.load(),
    )
    assert resumed.status is RunStatus.AWAITING_RECOVERY, resumed.status
    assert resumed.request is not None
    assert len(provider.calls) == 0
    assert _ledger_count(workspace, "X") == 1
    state = store.load().state
    resolved = runtime.run_turn(
        ResolveUnknownToolOutcome(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            request_id=resumed.request.request_id,
            binding_digest=resumed.request.binding_digest,
            resolution=RecoveryResolution.MARK_SUCCEEDED,
        ),
        store.load(),
    )
    assert resolved.status is RunStatus.COMPLETED, resolved.error_code
    assert len(provider.calls) == 1
    assert _ledger_count(workspace, "X") == 1
    durable = store.load().state
    assert durable.active_run is None
    _print_result(
        {
            "stage": "run_b_after_crash_resolve",
            "status": resolved.status.value,
            "provider_calls": 1,
            "ledger_x": 1,
        }
    )


_STAGES = {
    "run_a": _run_a_stage,
    "run_b_resume_only": _run_b_resume_only,
    "run_b_xy": _run_b_xy,
    "run_b_duplicate": _run_b_duplicate,
    "run_b_after_crash": _run_b_after_crash,
    "run_approval_pause": _run_approval_pause,
    "run_approval_resume_continue": _run_approval_resume_continue,
    "run_b_after_crash_resolve": _run_b_after_crash_resolve,
}


if __name__ == "__main__":
    stage = sys.argv[1]
    stage_workspace = Path(sys.argv[2])
    stage_state_root = Path(sys.argv[3])
    _STAGES[stage](stage_workspace, stage_state_root)


def test_v1_resume_only_zero_effect_then_continue_advances_production_loop(tmp_path):
    workspace = tmp_path / "ws"
    state_root = tmp_path / "state"
    workspace.mkdir()
    state_root.mkdir()
    code, payload = _run_stage("run_a", workspace, state_root)
    assert code == 0
    assert payload["ledger_x"] == 1
    assert payload["goal_status"] == "paused"
    code, payload = _run_stage("run_b_resume_only", workspace, state_root)
    assert code == 0
    assert payload == {
        "stage": "run_b_resume_only",
        "resume_provider_calls": 0,
        "ledger_x": 1,
        "continue_status": "completed",
        "continue_goal_status": "blocked",
    }


def test_v1_new_effect_after_resume_counted_from_real_callable(tmp_path):
    workspace = tmp_path / "ws"
    state_root = tmp_path / "state"
    workspace.mkdir()
    state_root.mkdir()
    code, payload = _run_stage("run_a", workspace, state_root)
    assert code == 0
    code, payload = _run_stage("run_b_xy", workspace, state_root)
    assert code == 0
    assert payload == {
        "stage": "run_b_xy",
        "ledger_x": 1,
        "ledger_y": 1,
    }


def test_v1_duplicate_logical_effect_is_detectable(tmp_path):
    workspace = tmp_path / "ws"
    state_root = tmp_path / "state"
    workspace.mkdir()
    state_root.mkdir()
    code, payload = _run_stage("run_a", workspace, state_root)
    assert code == 0
    code, payload = _run_stage("run_b_duplicate", workspace, state_root)
    assert code == 0
    assert payload["stage"] == "run_b_duplicate"
    assert payload["ledger_x"] == 2
    assert payload["detected"] is True


def test_v1_executing_crash_windows_surface_unknown_without_replay(tmp_path):
    for mode, expected_x in (("before", 0), ("after", 1)):
        workspace = tmp_path / f"ws-{mode}"
        state_root = tmp_path / f"state-{mode}"
        workspace.mkdir()
        state_root.mkdir()
        code, payload = _run_stage(
            "run_a",
            workspace,
            state_root,
            crash_mode=mode,
        )
        assert code == 9
        assert payload is None
        code, payload = _run_stage("run_b_after_crash", workspace, state_root)
        assert code == 0
        assert payload["stage"] == "run_b_after_crash"
        assert payload["status"] == "awaiting_recovery"
        assert payload["provider_calls"] == 0
        assert payload["ledger_x"] == expected_x


def test_r1_t6_approval_pause_closes_batch_and_new_process_continues(tmp_path):
    """R1-T6：审批边界 pause 关闭 checkpoint，新进程重开不再 bricked。

    形状复刻 V1 真实旅程 state-root7：MODEL 批次已入账、审批 pending 时
    /pause。R1 前该 checkpoint 含未完结 tool batch，新进程任何推进都在
    compaction_rules 的 "tool batch and its results cannot be split" 上
    fatal。修复后 pause 在同一 CAS 闭合未开始 call；新进程 ResumeGoal
    零 provider 调用，继续推进到 BlockedClaim，全程零执行、无人工重述。
    """

    workspace = tmp_path / "ws"
    state_root = tmp_path / "state"
    workspace.mkdir()
    state_root.mkdir()
    code, payload = _run_stage("run_approval_pause", workspace, state_root)
    assert code == 0
    assert payload == {
        "stage": "run_approval_pause",
        "goal_status": "paused",
        "ledger_a": 0,
    }
    code, payload = _run_stage(
        "run_approval_resume_continue", workspace, state_root
    )
    assert code == 0
    assert payload == {
        "stage": "run_approval_resume_continue",
        "resume_provider_calls": 0,
        "ledger_a": 0,
        "continue_goal_status": "blocked",
        "closed_executed": False,
    }


def test_r1_t6_crashed_unknown_resolves_in_new_process_without_replay(tmp_path):
    """R1-T6：EXECUTING 崩溃后的 UNKNOWN 在新进程走既有分类流程，零重放。

    效果已发生（ledger X 计数 1）且结果保存失败窗口崩溃；新进程 Resume
    进入 AWAITING_RECOVERY（零 provider/tool），操作者标记 succeeded 后
    同一 run 继续。ledger 恒为 1，证明分类不触发任何工具重放。
    """

    workspace = tmp_path / "ws"
    state_root = tmp_path / "state"
    workspace.mkdir()
    state_root.mkdir()
    code, payload = _run_stage(
        "run_a",
        workspace,
        state_root,
        crash_mode="after",
    )
    assert code == 9
    assert payload is None
    code, payload = _run_stage(
        "run_b_after_crash_resolve", workspace, state_root
    )
    assert code == 0
    assert payload == {
        "stage": "run_b_after_crash_resolve",
        "status": "completed",
        "provider_calls": 1,
        "ledger_x": 1,
    }

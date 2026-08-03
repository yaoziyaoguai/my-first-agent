"""Scheduler external caller：create-or-load occurrence store + 一次确定性 SubmitMessage。

concrete helper 只封装 path derivation、排他 initialize 与 load，不暴露/调用
``compare_and_swap``。``ScheduledOccurrenceCaller`` 只接收已绑定同一 store 的 Runtime 与
snapshot，只调用 ``AgentRuntime.run_turn``；不直接调用 provider/ToolRuntime/checkpoint mutation。
"""

from __future__ import annotations

from pathlib import Path

from agent.runtime.checkpoint import CheckpointConflictError, LocalCheckpointStore
from agent.runtime.contracts import (
    ConversationState,
    LoadedSnapshot,
    RunStatus,
    SubmitMessage,
)
from agent.scheduler.contracts import (
    ScheduledOccurrence,
    ScheduledRunReport,
    SchedulerError,
    occurrence_exit_class,
)


def create_or_load_occurrence_store(
    occurrence: ScheduledOccurrence,
    *,
    state_root: Path,
) -> tuple[LocalCheckpointStore, LoadedSnapshot]:
    """排他创建或加载 occurrence checkpoint。conversation identity 不匹配即 conflict。"""
    path = state_root / occurrence.checkpoint_relative_path
    state = ConversationState.new(occurrence.conversation_id)
    try:
        store = LocalCheckpointStore.initialize(path, state)
    except CheckpointConflictError:
        store = LocalCheckpointStore(path)
    snapshot = store.load()
    if snapshot.state.conversation_id != occurrence.conversation_id:
        # 同 schedule+occurrence ID 但 message/time/scope 漂移：命中原文件，但不覆盖。
        raise SchedulerError("occurrence identity conflict on existing checkpoint")
    return store, snapshot


class ScheduledOccurrenceCaller:
    """只接收 pre-bound Runtime/snapshot；唯一 execution call 是 run_turn。"""

    def __init__(
        self,
        runtime,
        store: LocalCheckpointStore,
        snapshot: LoadedSnapshot,
        occurrence: ScheduledOccurrence,
    ) -> None:
        self._runtime = runtime
        self._store = store
        self._snapshot = snapshot
        self._occurrence = occurrence

    def run_once(self) -> ScheduledRunReport:
        action = SubmitMessage(
            conversation_id=self._occurrence.conversation_id,
            action_seq=1,
            expected_revision=0,
            run_id=self._occurrence.run_id,
            message=self._occurrence.message,
        )
        result = self._runtime.run_turn(action, self._snapshot)
        if (
            result.status is RunStatus.CONFLICT
            and result.error_code in ("checkpoint_conflict", "conversation_busy")
        ):
            # conversation_busy（并发 winner 仍持 lease）与 checkpoint_conflict（stale initial
            # snapshot）使用同一 one-shot reconciliation：reload authoritative snapshot，重交
            # 完全相同的 seq-1 action。第二次仍冲突则原样返回，禁止 loop。
            self._snapshot = self._store.load()
            result = self._runtime.run_turn(action, self._snapshot)
        return self._report(result)

    def _report(self, result) -> ScheduledRunReport:
        # report 基于 authoritative state（replay 后可能是 terminal）。
        authoritative = self._store.load().state
        active = authoritative.active_run
        auth_status = result.status
        pending = None
        if active is not None:
            if active.status.value == "awaiting_approval":
                auth_status = RunStatus.AWAITING_APPROVAL
                pending = active.pending_request
            elif active.status.value == "awaiting_recovery":
                auth_status = RunStatus.AWAITING_RECOVERY
                pending = active.pending_request
        elif authoritative.last_safe_result is not None:
            auth_status = authoritative.last_safe_result.status
        pending_kind = None
        pending_request_id = None
        if pending is not None:
            pending_kind = type(pending).__name__
            pending_request_id = pending.request_id
        return ScheduledRunReport(
            occurrence_status=occurrence_exit_class(auth_status),
            run_status=auth_status,
            conversation_id=self._occurrence.conversation_id,
            run_id=self._occurrence.run_id,
            replayed=bool(result.replayed),
            error_code=result.error_code,
            checkpoint_relative_path=self._occurrence.checkpoint_relative_path,
            pending_kind=pending_kind,
            pending_request_id=pending_request_id,
        )

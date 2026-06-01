"""Memory session isolation 的 deterministic characterization tests。

本文件补红队指出的单进程盲区：MemoryRuntime 内部 pending cache 是 runtime
实例局部状态，filesystem store 是显式持久层。测试不调用真实 LLM、不读取真实
sessions/runs，也不改变 Memory governance；它只把当前隔离边界钉住。
"""

from __future__ import annotations

from agent.memory_confirmation import MemoryConfirmationChoice
from agent.memory_fs_store import FilesystemMemoryStore
from agent.memory_runtime import MemoryEvaluationAction, MemoryRuntime
from agent.memory_store import InMemoryMemoryStore


def test_session_a_pending_confirmation_does_not_pollute_session_b_runtime() -> None:
    """session A 的 pending decision 只能留在 A 的 runtime cache，不进入 B。"""

    store_a = InMemoryMemoryStore()
    store_b = InMemoryMemoryStore()
    runtime_a = MemoryRuntime(store=store_a)
    runtime_b = MemoryRuntime(store=store_b)

    result_a = runtime_a.evaluate_user_text("remember that session A prefers pytest")

    assert result_a.action is MemoryEvaluationAction.CONFIRMATION_REQUIRED
    assert runtime_a.get_pending_confirmation(result_a.candidate_id) is not None
    assert runtime_b.get_pending_confirmation(result_a.candidate_id) is None
    assert store_a.list_records() == ()
    assert store_b.list_records() == ()


def test_session_a_approved_memory_does_not_write_session_b_in_memory_store() -> None:
    """独立 in-memory store 之间不能通过模块级 runtime/cache 交叉污染。"""

    store_a = InMemoryMemoryStore()
    store_b = InMemoryMemoryStore()
    runtime_a = MemoryRuntime(store=store_a)
    runtime_b = MemoryRuntime(store=store_b)

    result_a = runtime_a.evaluate_user_text("remember that session A likes short reports")
    stored_a = runtime_a.resolve_confirmation(
        result_a.candidate_id,
        MemoryConfirmationChoice.ACCEPT,
    )

    # 写入 store 通过 dispatcher 路径，resolve_confirmation 只返回 payload
    payload = getattr(stored_a, "_dispatcher_payload", None)
    if payload and "candidate" in payload:
        store_a.store_retained_record(payload["candidate"])

    assert stored_a.action is MemoryEvaluationAction.STORED
    assert len(store_a.list_records()) == 1
    assert store_b.list_records() == ()
    assert runtime_b.snapshot_for_prompt().items == ()


def test_filesystem_store_persists_only_after_confirmation_not_pending_cache(tmp_path) -> None:
    """pending cache 不落盘；只有 explicit accept 后新 store 实例才能重建记录。"""

    root = tmp_path / "memory-store"
    runtime_a = MemoryRuntime(store=FilesystemMemoryStore(root))

    pending = runtime_a.evaluate_user_text("remember that filesystem store needs review")
    rebuilt_before_accept = FilesystemMemoryStore(root)

    assert pending.action is MemoryEvaluationAction.CONFIRMATION_REQUIRED
    assert rebuilt_before_accept.list_records() == ()

    runtime_a.resolve_confirmation(pending.candidate_id, MemoryConfirmationChoice.ACCEPT)
    rebuilt_after_accept = FilesystemMemoryStore(root)

    records = rebuilt_after_accept.list_records()
    assert len(records) == 1
    assert records[0].approval_status == "approved"
    assert "filesystem store needs review" in records[0].content


def test_rejected_memory_in_one_session_remains_no_write_across_new_runtime(tmp_path) -> None:
    """reject 路径在多 session 场景仍是 no-write，不能留下 pending 或 store record。"""

    root = tmp_path / "memory-store"
    runtime_a = MemoryRuntime(store=FilesystemMemoryStore(root))

    pending = runtime_a.evaluate_user_text("remember that rejected memory must not persist")
    rejected = runtime_a.resolve_confirmation(
        pending.candidate_id,
        MemoryConfirmationChoice.REJECT,
    )
    store_b = FilesystemMemoryStore(root)
    runtime_b = MemoryRuntime(store=store_b)

    assert rejected.action is MemoryEvaluationAction.REJECTED
    assert runtime_a.get_pending_confirmation(pending.candidate_id) is None
    assert runtime_b.get_pending_confirmation(pending.candidate_id) is None
    assert runtime_b.snapshot_for_prompt().items == ()
    assert store_b.list_records() == ()

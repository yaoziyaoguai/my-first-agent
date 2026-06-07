"""Phase 7 inline_confirmation adapter tests.

这些测试验证 Phase 7 inline_confirmation 通过 memory_interaction adapter 接入
Ask User 流程。Agent core 只做 orchestration，accept/edit_accept 才能写
procedural memory，reject/other/timeout 必须 no-write 或 fallback pending_review。

不读取 .env，不读取 agent_log.jsonl，不读取真实 sessions/runs，不调用真实 LLM。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.memory_emergence import (
    InlineConfirmationResponse,
    ProceduralCandidate,
    prepare_procedural_inline_confirmation_request,
)
from agent.memory_runtime import MemoryRuntime
from agent.memory_store import InMemoryMemoryStore


def _make_inline_request():
    """构造测试用 inline request，metadata 覆盖 fallback 与写入边界。"""
    candidate = ProceduralCandidate(
        content="[行为约束] 调试时必须先查日志和 checkpoint",
        memory_type="procedural",
        source_evidence=("ev-1", "ev-2", "ev-3"),
        correction_pattern="先查日志和 checkpoint",
        correction_type="process_order",
        scope="debugging",
        confidence=0.72,
        governance_route="T1",
        evidence_summary="用户三次纠正：先看日志、checkpoint、真实数据流",
        created_at="2026-05-15T00:00:00Z",
    )
    return prepare_procedural_inline_confirmation_request(candidate)


def _patch_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试中拦截 checkpoint 写入，避免触碰真实用户环境。"""
    from agent import checkpoint

    monkeypatch.setattr(checkpoint, "save_checkpoint", lambda *_args, **_kwargs: None)


def _make_context(*, pending: dict, runtime: MemoryRuntime):
    """构造最小 ConfirmationContext，验证 confirm_handlers 只做分流委托。"""
    from agent.confirm_handlers import ConfirmationContext

    state = SimpleNamespace(
        task=SimpleNamespace(
            status="awaiting_user_input",
            pending_user_input_request=pending,
            pending_retain_proposals=[],  # Phase 5b Memory pipeline 合法字段
            current_plan=None,
            current_step_index=0,
            confirm_each_step=False,
        ),
        conversation=SimpleNamespace(messages=[]),
    )
    return ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_runtime_event=lambda _event: None),
        client=None,
        model_name="test-model",
        continue_fn=lambda _turn_state: "continued",
        memory_runtime=runtime,
    )


def test_build_inline_confirmation_pending_request_shape():
    """InlineConfirmationRequest 必须投影为 Ask User 兼容 pending dict。

    这些测试验证 Phase 7 inline_confirmation 通过 memory_interaction adapter 接入
    Ask User 流程。Agent core 只做 orchestration，accept/edit_accept 才能写
    procedural memory，reject/other/timeout 必须 no-write 或 fallback pending_review。
    """
    from agent.memory_interaction import build_inline_confirmation_pending_request

    request = _make_inline_request()

    pending = build_inline_confirmation_pending_request(
        request,
        origin_status="running",
    )

    assert pending["awaiting_kind"] == "memory_inline_confirmation"
    assert pending["actions"] == ["accept", "reject", "edit", "other"]
    assert pending["_choice_map"] == {
        "1": "accept",
        "2": "reject",
        "3": "edit",
        "4": "other",
    }
    assert any("Other" in option and "free" in option for option in pending["options"])

    payload = pending["_inline_confirmation_request"]
    assert payload["candidate_content"] == request.candidate_content
    assert payload["source_evidence"] == ["ev-1", "ev-2", "ev-3"]
    assert payload["correction_pattern"] == "先查日志和 checkpoint"
    assert payload["correction_type"] == "process_order"
    assert payload["evidence_summary"] == request.evidence_summary
    assert payload["confidence"] == 0.72
    assert payload["confirmation_form"] == "inline_confirmation"

    json.dumps(pending, ensure_ascii=False)


@pytest.mark.parametrize(
    ("user_text", "expected"),
    [
        ("1", InlineConfirmationResponse(action="accept")),
        ("2", InlineConfirmationResponse(action="reject")),
        (
            "3 调试前必须先看日志、checkpoint 和真实数据流",
            InlineConfirmationResponse(
                action="edit_accept",
                edited_content="调试前必须先看日志、checkpoint 和真实数据流",
            ),
        ),
        (
            "4 这条还需要再确认",
            InlineConfirmationResponse(action="other", free_text="这条还需要再确认"),
        ),
        (
            "这条不够准确",
            InlineConfirmationResponse(action="other", free_text="这条不够准确"),
        ),
        # 常见肯定简写 → accept
        ("y", InlineConfirmationResponse(action="accept")),
        ("yes", InlineConfirmationResponse(action="accept")),
        ("好", InlineConfirmationResponse(action="accept")),
    ],
)
def test_parse_inline_confirmation_reply(user_text: str, expected: InlineConfirmationResponse):
    """用户回复只被解析为无副作用 response，不直接写 store。"""
    from agent.memory_interaction import (
        build_inline_confirmation_pending_request,
        parse_inline_confirmation_reply,
    )

    pending = build_inline_confirmation_pending_request(
        _make_inline_request(),
        origin_status="running",
    )

    assert parse_inline_confirmation_reply(user_text, pending) == expected


def test_inline_confirmation_accept_routes_through_confirm_handler(
    monkeypatch: pytest.MonkeyPatch,
):
    """memory_inline_confirmation accept 通过 confirm_handlers 委托后入队 pending_retain_proposals。

    中文学习边界：
    confirmation handler 不直接写 memory store——它只把已确认的 proposal 排队到
    state.task.pending_retain_proposals，真正的 retain/write 由 turn-end hook 中的
    MEMORY_PROPOSE RuntimeAction dispatch 统一执行。

    为什么不让 confirmation handler 直接写 store：
    - MEMORY_PROPOSE 通过 dispatcher 提供 RuntimeActionEvent evidence chain
    - retain execution 需要与 proposal generation / recall 在同一生命周期
    - 如果 confirmation handler 直接写 store，绕过 dispatcher evidence，后续 audit
      无法区分"用户确认后写入"和"静默写入"
    """
    from agent.confirm_handlers import handle_user_input_step
    from agent.memory_interaction import build_inline_confirmation_pending_request

    _patch_checkpoint(monkeypatch)
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    pending = build_inline_confirmation_pending_request(
        _make_inline_request(),
        origin_status="running",
    )
    ctx = _make_context(pending=pending, runtime=runtime)

    reply = handle_user_input_step("1", ctx)

    assert "已确认" in reply
    assert ctx.state.task.pending_user_input_request is None
    assert ctx.state.task.status == "running"
    # 确认后的 proposal 排队到 pending_retain_proposals，不直接写 store
    proposals = ctx.state.task.pending_retain_proposals
    assert len(proposals) == 1
    assert proposals[0]["proposal_id"] == _make_inline_request().proposal_id
    assert proposals[0]["confirmation_result"] == "accepted"
    assert proposals[0]["source"] == "turn_end_proposal"
    # store 未被直接写入——真正写入由 turn-end hook MEMORY_PROPOSE dispatch 完成
    assert len(runtime._store.list_records()) == 0


def test_inline_confirmation_edit_accept_writes_edited_content(
    monkeypatch: pytest.MonkeyPatch,
):
    """edit_accept 将用户编辑后的 procedural 内容排队到 pending_retain_proposals。

    不直接写 store——真正 retain/write 由 turn-end hook MEMORY_PROPOSE dispatch 完成。
    """
    from agent.memory_interaction import (
        build_inline_confirmation_pending_request,
        handle_inline_confirmation_reply,
    )

    _patch_checkpoint(monkeypatch)
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    pending = build_inline_confirmation_pending_request(
        _make_inline_request(),
        origin_status="running",
    )
    ctx = _make_context(pending=pending, runtime=runtime)

    reply = handle_inline_confirmation_reply(
        "3 调试前先查日志，再查 checkpoint",
        ctx,
        store=runtime._store,
    )

    assert "已确认" in reply
    # 确认后的 proposal 排队到 pending_retain_proposals，不直接写 store
    proposals = ctx.state.task.pending_retain_proposals
    assert len(proposals) == 1
    assert "先查日志，再查 checkpoint" in proposals[0]["content"]
    # store 未被直接写入
    assert len(runtime._store.list_records()) == 0


@pytest.mark.parametrize("user_text", ["2", "4 还不够准确", "这不是我的意思"])
def test_inline_confirmation_reject_and_other_do_not_write(
    monkeypatch: pytest.MonkeyPatch,
    user_text: str,
):
    """reject / other / free-text 都不是 explicit approval，必须 no-write。"""
    from agent.memory_interaction import (
        build_inline_confirmation_pending_request,
        handle_inline_confirmation_reply,
    )

    _patch_checkpoint(monkeypatch)
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    pending = build_inline_confirmation_pending_request(
        _make_inline_request(),
        origin_status="running",
    )
    ctx = _make_context(pending=pending, runtime=runtime)

    reply = handle_inline_confirmation_reply(user_text, ctx, store=runtime._store)

    assert "未写入" in reply
    assert len(runtime._store.list_records()) == 0


def test_inline_confirmation_no_response_falls_back_to_pending_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    """no response 不能丢 candidate，必须 fallback pending_review 且不写 store。"""
    from agent.memory_interaction import (
        build_inline_confirmation_pending_request,
        handle_inline_confirmation_reply,
    )

    _patch_checkpoint(monkeypatch)
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    pending = build_inline_confirmation_pending_request(
        _make_inline_request(),
        origin_status="running",
    )
    ctx = _make_context(pending=pending, runtime=runtime)

    reply = handle_inline_confirmation_reply(
        "",
        ctx,
        store=runtime._store,
        fallback_memory_root=tmp_path,
    )

    assert "pending_review" in reply
    assert len(runtime._store.list_records()) == 0
    pending_files = sorted((tmp_path / "_pending").glob("t1_*.json"))
    assert len(pending_files) == 1
    data = json.loads(pending_files[0].read_text(encoding="utf-8"))
    assert data["confirmation_form"] == "pending_review"
    assert data["source_evidence"] == ["ev-1", "ev-2", "ev-3"]
    assert data["correction_pattern"] == "先查日志和 checkpoint"
    assert data["correction_type"] == "process_order"
    assert data["evidence_summary"] == "用户三次纠正：先看日志、checkpoint、真实数据流"
    assert data["confidence"] == 0.72


def test_confirm_handler_does_not_parse_inline_memory_metadata():
    """confirm_handlers 只看 awaiting_kind 并委托，不解析 memory 内部字段。"""
    import inspect

    import agent.confirm_handlers as confirm_handlers

    src = inspect.getsource(confirm_handlers.handle_user_input_step)

    assert "memory_inline_confirmation" in src
    assert "source_evidence" not in src
    assert "correction_pattern" not in src
    assert "evidence_summary" not in src
    assert "apply_inline_confirmation_response" not in src


def test_inline_confirmation_denied_origin_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    """Phase 3 U1: origin denied 时不得入队、fallback、清 pending 或保存。"""
    from agent.memory_interaction import (
        build_inline_confirmation_pending_request,
        handle_inline_confirmation_reply,
    )

    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    pending = build_inline_confirmation_pending_request(
        _make_inline_request(),
        origin_status="done",
    )
    ctx = _make_context(pending=pending, runtime=runtime)
    save_calls: list[str] = []
    monkeypatch.setattr(
        "agent.checkpoint.save_checkpoint",
        lambda *_args, source=None, **_kwargs: save_calls.append(source),
    )
    original_pending = json.loads(json.dumps(pending))

    reply = handle_inline_confirmation_reply(
        "1",
        ctx,
        store=runtime._store,
        fallback_memory_root=tmp_path,
    )

    assert "无法" in reply or "拒绝" in reply
    assert ctx.state.task.status == "awaiting_user_input"
    assert ctx.state.task.pending_user_input_request == original_pending
    assert ctx.state.task.pending_retain_proposals == []
    assert len(runtime._store.list_records()) == 0
    assert not (tmp_path / "_pending").exists()
    assert save_calls == []


def test_inline_confirmation_stale_preflight_does_not_enqueue_or_clear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    """Phase 3 U1: inline apply stale 时不入队、不 fallback、不保存。"""
    import agent.memory_interaction as memory_interaction
    from agent.memory_interaction import (
        build_inline_confirmation_pending_request,
        handle_inline_confirmation_reply,
    )
    from agent.transitions import apply_task_transition as real_apply

    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    pending = build_inline_confirmation_pending_request(
        _make_inline_request(),
        origin_status="running",
    )
    ctx = _make_context(pending=pending, runtime=runtime)

    def _stale_apply(state, request, *, preflight=None):
        state.task.status = "running"
        return real_apply(state, request, preflight=preflight)

    monkeypatch.setattr(memory_interaction, "apply_task_transition", _stale_apply)
    save_calls: list[str] = []
    monkeypatch.setattr(
        "agent.checkpoint.save_checkpoint",
        lambda *_args, source=None, **_kwargs: save_calls.append(source),
    )
    original_pending = json.loads(json.dumps(pending))

    reply = handle_inline_confirmation_reply(
        "1",
        ctx,
        store=runtime._store,
        fallback_memory_root=tmp_path,
    )

    assert "无法" in reply
    assert ctx.state.task.status == "running"
    assert ctx.state.task.pending_user_input_request == original_pending
    assert ctx.state.task.pending_retain_proposals == []
    assert not (tmp_path / "_pending").exists()
    assert save_calls == []

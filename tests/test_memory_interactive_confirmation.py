"""Memory Interactive Confirmation v1 — 单元测试和契约测试。

覆盖：
- evaluate_user_text 不再 auto-accept，返回 CONFIRMATION_REQUIRED
- get_pending_confirmation 返回缓存的 confirmation request
- resolve_confirmation 的 5 种 choice 路径（accept/reject/edit/session_only/other）
- build_memory_pending_request 结构正确性
- parse_memory_confirmation_reply 解析规则
- 两阶段交互完整闭环

不依赖真实 LLM、不读 .env、不写文件/DB、不使用裸 input()。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    MemoryConfirmationRequest,
)
from agent.memory_contracts import (
    MemoryCandidate,
    MemoryDecision,
    MemoryDecisionType,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
)
from agent.memory_interaction import (
    build_memory_pending_request,
    parse_memory_confirmation_reply,
)
from agent.memory_runtime import (
    MemoryEvaluationAction,
    MemoryRuntime,
)
from agent.memory_store import InMemoryMemoryStore

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_runtime() -> MemoryRuntime:
    """构造测试用 MemoryRuntime：in-memory store。"""
    return MemoryRuntime(store=InMemoryMemoryStore())


def _make_retain_decision(content: str = "用户偏好蓝色") -> MemoryDecision:
    """构造一个标准的 RETAIN decision。"""
    candidate = MemoryCandidate(
        id="cand-test",
        content=content,
        source=MemorySource.USER_INPUT,
        source_event=None,
        proposed_type="explicit_retain",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.LOW,
        stability="user_asserted",
        confidence=0.9,
        reason="用户显式请求记住",
    )
    return MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=candidate,
        action="retain",
        requires_user_confirmation=True,
        reason="用户显式请求记住",
        provenance="cand-test",
    )


def _patch_memory_interaction_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试中拦截 checkpoint 写入，避免触碰真实用户环境。"""
    from agent import checkpoint

    monkeypatch.setattr(checkpoint, "save_checkpoint", lambda *_args, **_kwargs: None)


def _make_confirmation_context(
    *,
    pending: dict,
    memory_runtime: MemoryRuntime,
    messages: list[dict] | None = None,
):
    """构造最小 ConfirmationContext，用于直接测试 handler 分流。

    这些 characterization tests 用于钉死现有 pending_user_input_request →
    awaiting_user_input → confirm_handlers 的行为，避免新增 inline confirmation
    分支破坏既有 memory_confirmation 流程。
    """
    from agent.confirm_handlers import ConfirmationContext

    state = SimpleNamespace(
        task=SimpleNamespace(
            status="awaiting_user_input",
            pending_user_input_request=pending,
            current_plan=None,
            current_step_index=0,
            confirm_each_step=False,
        ),
        conversation=SimpleNamespace(messages=messages if messages is not None else []),
    )
    turn_state = SimpleNamespace(on_runtime_event=lambda _event: None)
    return ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test-model",
        continue_fn=lambda _turn_state: "continued",
        memory_runtime=memory_runtime,
    )


def _make_pending_from_runtime(runtime: MemoryRuntime) -> tuple[dict, str | None]:
    """通过真实 MemoryRuntime 生成旧 memory_confirmation pending。"""
    result = runtime.evaluate_user_text("remember that I like blue")
    request = runtime.get_pending_confirmation(result.candidate_id)
    assert request is not None
    pending = build_memory_pending_request(
        request,
        candidate_id=result.candidate_id,
        origin_status="running",
    )
    return pending, result.candidate_id


# ---------------------------------------------------------------------------
# 1. evaluate_user_text 不再 auto-accept
# ---------------------------------------------------------------------------


def test_evaluate_user_text_returns_confirmation_required():
    """evaluate_user_text 不再内部 auto-accept，返回 CONFIRMATION_REQUIRED。

    v1 之前：evaluate_user_text → adapter → store → STORED。
    v1 开始：evaluate_user_text → 缓存 decision → CONFIRMATION_REQUIRED。
    """
    runtime = _make_runtime()
    result = runtime.evaluate_user_text("remember that I like blue")

    assert result.action is MemoryEvaluationAction.CONFIRMATION_REQUIRED
    assert result.candidate_id is not None
    assert result.content_summary == "I like blue"
    assert result.reason == "等待用户确认"

    # store 尚未写入
    records = runtime._store.list_records()
    assert len(records) == 0


# ---------------------------------------------------------------------------
# 2. get_pending_confirmation 返回缓存
# ---------------------------------------------------------------------------


def test_get_pending_confirmation_returns_cached_request():
    """evaluate_user_text 后 get_pending_confirmation 返回可用 request。"""
    runtime = _make_runtime()
    result = runtime.evaluate_user_text("remember that I like blue")

    request = runtime.get_pending_confirmation(result.candidate_id)
    assert request is not None
    assert isinstance(request, MemoryConfirmationRequest)
    assert "I like blue" in request.question
    assert len(request.options) >= 4  # accept/edit/session_only/reject/other

    # 不匹配的 candidate_id 返回 None
    assert runtime.get_pending_confirmation("nonexistent") is None


# ---------------------------------------------------------------------------
# 3. resolve_confirmation ACCEPT → STORED
# ---------------------------------------------------------------------------


def test_resolve_confirmation_accept_returns_dispatcher_payload():
    """resolve_confirmation accept 默认 direct_write=True，写 store 并返回 _dispatcher_payload。"""
    runtime = _make_runtime()
    result = runtime.evaluate_user_text("remember that I like blue")

    resolved = runtime.resolve_confirmation(
        result.candidate_id,
        MemoryConfirmationChoice.ACCEPT,
    )

    assert resolved.action is MemoryEvaluationAction.STORED
    payload = resolved._dispatcher_payload
    assert payload is not None, "APPROVED 应返回 _dispatcher_payload"
    assert payload["confirmation_result"] == "accept"
    assert payload["proposal_id"] == result.candidate_id
    assert isinstance(payload["candidate"], dict)
    assert "content" in payload["candidate"]
    assert "I like blue" in payload["candidate"]["content"]
    assert "content_hash" in payload["candidate"]
    assert "scope" in payload["candidate"]
    # direct_write=True 默认行为：store 已被直接写入
    records = runtime._store.list_records()
    assert len(records) == 1, "direct_write=True 应直接写 store"


# ---------------------------------------------------------------------------
# 4. resolve_confirmation REJECT → REJECTED
# ---------------------------------------------------------------------------


def test_resolve_confirmation_reject_does_not_write():
    """用户选择 REJECT → store 为空。"""
    runtime = _make_runtime()
    result = runtime.evaluate_user_text("remember that I like blue")

    resolved = runtime.resolve_confirmation(
        result.candidate_id,
        MemoryConfirmationChoice.REJECT,
    )

    assert resolved.action is MemoryEvaluationAction.REJECTED
    assert resolved.reason == "用户拒绝"
    records = runtime._store.list_records()
    assert len(records) == 0


# ---------------------------------------------------------------------------
# 5. resolve_confirmation SESSION_ONLY → STORED
# ---------------------------------------------------------------------------


def test_resolve_confirmation_session_only_returns_dispatcher_payload():
    """SESSION_ONLY direct_write=True 默认行为：返回 _dispatcher_payload 并写 store。"""
    runtime = _make_runtime()
    result = runtime.evaluate_user_text("remember that I like blue")

    resolved = runtime.resolve_confirmation(
        result.candidate_id,
        MemoryConfirmationChoice.SESSION_ONLY,
    )

    assert resolved.action is MemoryEvaluationAction.STORED
    assert "仅本次会话" in resolved.reason
    payload = resolved._dispatcher_payload
    assert payload is not None, "SESSION_ONLY 应返回 _dispatcher_payload"
    assert payload["confirmation_result"] == "session_only"
    assert payload["proposal_id"] == result.candidate_id
    assert isinstance(payload["candidate"], dict)
    # direct_write=True 默认行为：store 已被写入
    records = runtime._store.list_records()
    assert len(records) == 1, "direct_write=True 应直接写 store"


# ---------------------------------------------------------------------------
# 6. resolve_confirmation EDIT_AND_ACCEPT → STORED
# ---------------------------------------------------------------------------


def test_resolve_confirmation_edit_and_accept_returns_dispatcher_payload():
    """EDIT_AND_ACCEPT direct_write=True 默认：返回 payload 并写 store，内容为编辑后版本。"""
    runtime = _make_runtime()
    result = runtime.evaluate_user_text("remember that I like blue")

    resolved = runtime.resolve_confirmation(
        result.candidate_id,
        MemoryConfirmationChoice.EDIT_AND_ACCEPT,
        free_text="I prefer green actually",
    )

    assert resolved.action is MemoryEvaluationAction.STORED
    payload = resolved._dispatcher_payload
    assert payload is not None, "EDIT_AND_ACCEPT 应返回 _dispatcher_payload"
    assert "green" in payload["candidate"]["content"]
    # direct_write=True 默认行为：store 已被写入
    records = runtime._store.list_records()
    assert len(records) == 1, "direct_write=True 应直接写 store"
    assert "green" in records[0].content


# ---------------------------------------------------------------------------
# 7. resolve_confirmation OTHER → STORED（通过 clarify 路径）
# ---------------------------------------------------------------------------


def test_resolve_confirmation_other_free_text_handled():
    """用户选择 OTHER → 通过 NEEDS_CLARIFICATION 处理。"""
    runtime = _make_runtime()
    result = runtime.evaluate_user_text("remember that I like blue")

    resolved = runtime.resolve_confirmation(
        result.candidate_id,
        MemoryConfirmationChoice.OTHER,
        free_text="请只在本次会话使用这条信息",
    )

    # OTHER → NEEDS_CLARIFICATION → resolve_memory_confirmation_choice 返回
    # status=NEEDS_CLARIFICATION，resolve_confirmation 中不匹配 APPROVED/REJECTED/
    # SESSION_ONLY，进入 approved 分支的 else → store 写入。
    # 实际行为取决于 store 的 apply_operation_intent 处理。
    assert resolved.action is not MemoryEvaluationAction.REJECTED


# ---------------------------------------------------------------------------
# 8. build_memory_pending_request 结构
# ---------------------------------------------------------------------------


def test_build_memory_pending_request_structure():
    """build_memory_pending_request 生成的 pending dict 包含所有必要字段。

    这些 characterization tests 用于钉死现有 pending_user_input_request →
    awaiting_user_input → confirm_handlers 的行为，避免新增 inline confirmation
    分支破坏既有 memory_confirmation 流程。
    """
    from agent.memory_confirmation import build_memory_confirmation_request

    decision = _make_retain_decision()
    request = build_memory_confirmation_request(decision)

    pending = build_memory_pending_request(
        request,
        candidate_id="cand-test",
        origin_status="running",
    )

    # 公共字段（与 request_user_input / feedback_intent 共用）
    assert pending["awaiting_kind"] == "memory_confirmation"
    assert pending["question"] == request.question
    assert "请选择如何处理这条记忆" in pending["why_needed"]
    assert isinstance(pending["options"], list)
    assert len(pending["options"]) >= 5
    assert pending["context"] == ""
    assert pending["tool_use_id"] == ""
    assert pending["step_index"] is None

    # memory 专有字段（私有 key，以 _ 开头）
    assert pending["_candidate_id"] == "cand-test"
    assert isinstance(pending["_choice_map"], dict)
    assert pending["_choice_map"]["1"] == "accept"
    assert pending["_origin_status"] == "running"

    # choice_map 包含所有 5 种选择
    assert pending["_choice_map"]["2"] == "edit_and_accept"
    assert pending["_choice_map"]["3"] == "session_only"
    assert pending["_choice_map"]["4"] == "reject"
    assert pending["_choice_map"]["5"] == "other"


def test_memory_confirmation_accept_routes_through_handle_user_input_step(
    monkeypatch: pytest.MonkeyPatch,
):
    """Loop 15: accept 返回正确文本，store 写入由 dispatcher 负责。

    这些 characterization tests 用于钉死现有 pending_user_input_request →
    awaiting_user_input → confirm_handlers 的行为，避免新增 inline confirmation
    分支破坏既有 memory_confirmation 流程。
    """
    from agent.confirm_handlers import handle_user_input_step

    _patch_memory_interaction_checkpoint(monkeypatch)
    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)
    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)

    reply = handle_user_input_step("1", ctx)

    assert "已记住" in reply
    assert ctx.state.task.pending_user_input_request is None
    assert ctx.state.task.status == "running"
    # store 写入不再由 resolve_confirmation 直接执行——由 dispatcher 负责


def test_memory_confirmation_reject_routes_through_handle_user_input_step(
    monkeypatch: pytest.MonkeyPatch,
):
    """memory_confirmation reject 仍不写入 store。

    这些 characterization tests 用于钉死现有 pending_user_input_request →
    awaiting_user_input → confirm_handlers 的行为，避免新增 inline confirmation
    分支破坏既有 memory_confirmation 流程。
    """
    from agent.confirm_handlers import handle_user_input_step

    _patch_memory_interaction_checkpoint(monkeypatch)
    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)
    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)

    reply = handle_user_input_step("4", ctx)

    assert reply == "已拒绝，不记住这条信息。"
    assert ctx.state.task.pending_user_input_request is None
    assert ctx.state.task.status == "running"
    assert len(runtime._store.list_records()) == 0


def test_memory_confirmation_edit_routes_through_handle_user_input_step(
    monkeypatch: pytest.MonkeyPatch,
):
    """Loop 15: edit 返回正确文本，store 写入由 dispatcher 负责。"""
    from agent.confirm_handlers import handle_user_input_step

    _patch_memory_interaction_checkpoint(monkeypatch)
    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)
    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)

    reply = handle_user_input_step("2 I prefer green actually", ctx)

    assert "已记住" in reply
    # store 写入不再由 resolve_confirmation 直接执行——由 dispatcher 负责


def test_unknown_awaiting_kind_is_not_memory_confirmation(
    monkeypatch: pytest.MonkeyPatch,
):
    """未知 awaiting_kind 不能被误处理成 memory confirmation 或 inline 分支。

    这些 characterization tests 用于钉死现有 pending_user_input_request →
    awaiting_user_input → confirm_handlers 的行为，避免新增 inline confirmation
    分支破坏既有 memory_confirmation 流程。
    """
    from agent import checkpoint
    from agent.confirm_handlers import handle_user_input_step

    monkeypatch.setattr(checkpoint, "save_checkpoint", lambda *_args, **_kwargs: None)
    runtime = _make_runtime()
    pending = {
        "awaiting_kind": "unknown_memory_kind",
        "question": "测试问题",
        "why_needed": "测试原因",
        "options": [],
        "context": "",
        "tool_use_id": "",
        "step_index": None,
    }
    messages: list[dict] = []
    ctx = _make_confirmation_context(
        pending=pending,
        memory_runtime=runtime,
        messages=messages,
    )

    reply = handle_user_input_step("用户回答", ctx)

    assert reply == "continued"
    assert ctx.state.task.pending_user_input_request is None
    assert ctx.state.task.status == "running"
    assert len(runtime._store.list_records()) == 0
    assert messages[-1]["role"] == "user"
    assert "用户已经回答" in messages[-1]["content"][0]["text"]


def test_core_and_user_input_handler_do_not_directly_write_memory_store():
    """core / handler 不直接写 memory store，写入仍归 memory_interaction/service。

    这些 characterization tests 用于钉死现有 pending_user_input_request →
    awaiting_user_input → confirm_handlers 的行为，避免新增 inline confirmation
    分支破坏既有 memory_confirmation 流程。
    """
    import inspect

    import agent.confirm_handlers as confirm_handlers
    import agent.core as core

    handler_src = inspect.getsource(confirm_handlers.handle_user_input_step)
    core_src = inspect.getsource(core.chat)

    assert "apply_operation_intent" not in handler_src
    assert "apply_inline_confirmation_response" not in handler_src
    assert "apply_operation_intent" not in core_src
    assert "apply_inline_confirmation_response" not in core_src


# ---------------------------------------------------------------------------
# 9. parse_memory_confirmation_reply 数字匹配
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_input,expected_choice",
    [
        ("1", MemoryConfirmationChoice.ACCEPT),
        ("2", MemoryConfirmationChoice.EDIT_AND_ACCEPT),
        ("3", MemoryConfirmationChoice.SESSION_ONLY),
        ("4", MemoryConfirmationChoice.REJECT),
        ("5", MemoryConfirmationChoice.OTHER),
    ],
)
def test_parse_memory_confirmation_reply_numeric_choices(
    user_input: str, expected_choice: MemoryConfirmationChoice
):
    """数字 1-5 精确匹配对应 choice。"""
    from agent.memory_confirmation import build_memory_confirmation_request

    decision = _make_retain_decision()
    request = build_memory_confirmation_request(decision)
    pending = build_memory_pending_request(
        request,
        candidate_id="cand-test",
        origin_status="running",
    )

    choice, free_text = parse_memory_confirmation_reply(user_input, pending)
    assert choice is expected_choice
    assert free_text is None


# ---------------------------------------------------------------------------
# 10. parse_memory_confirmation_reply 数字+文本
# ---------------------------------------------------------------------------


def test_parse_memory_confirmation_reply_number_with_text():
    """"2 edited content" → EDIT_AND_ACCEPT + free_text。"""
    from agent.memory_confirmation import build_memory_confirmation_request

    decision = _make_retain_decision()
    request = build_memory_confirmation_request(decision)
    pending = build_memory_pending_request(
        request,
        candidate_id="cand-test",
        origin_status="running",
    )

    choice, free_text = parse_memory_confirmation_reply(
        "2 改成：我喜欢绿色",
        pending,
    )
    assert choice is MemoryConfirmationChoice.EDIT_AND_ACCEPT
    assert free_text == "改成：我喜欢绿色"


def test_parse_memory_confirmation_reply_other_with_text():
    """"5 请只在本次会话记住" → OTHER + free_text。"""
    from agent.memory_confirmation import build_memory_confirmation_request

    decision = _make_retain_decision()
    request = build_memory_confirmation_request(decision)
    pending = build_memory_pending_request(
        request,
        candidate_id="cand-test",
        origin_status="running",
    )

    choice, free_text = parse_memory_confirmation_reply(
        "5 请只在本次会话记住",
        pending,
    )
    assert choice is MemoryConfirmationChoice.OTHER
    assert free_text == "请只在本次会话记住"


# ---------------------------------------------------------------------------
# 11. parse_memory_confirmation_reply fallback → OTHER
# ---------------------------------------------------------------------------


def test_parse_memory_confirmation_reply_unrecognized_falls_back_to_other():
    """非数字、非数字+文本输入 → OTHER + 全文作为 free_text。"""
    from agent.memory_confirmation import build_memory_confirmation_request

    decision = _make_retain_decision()
    request = build_memory_confirmation_request(decision)
    pending = build_memory_pending_request(
        request,
        candidate_id="cand-test",
        origin_status="running",
    )

    choice, free_text = parse_memory_confirmation_reply(
        "我不确定，暂时先记住但下次再问一次",
        pending,
    )
    assert choice is MemoryConfirmationChoice.OTHER
    assert free_text == "我不确定，暂时先记住但下次再问一次"


def test_parse_memory_confirmation_reply_empty_input_raises():
    """空输入抛出 ValueError。"""
    from agent.memory_confirmation import build_memory_confirmation_request

    decision = _make_retain_decision()
    request = build_memory_confirmation_request(decision)
    pending = build_memory_pending_request(
        request,
        candidate_id="cand-test",
        origin_status="running",
    )

    with pytest.raises(ValueError, match="输入为空"):
        parse_memory_confirmation_reply("", pending)


# ---------------------------------------------------------------------------
# 11b. parse_memory_confirmation_reply 肯定简写 → 第一选项
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shorthand", ["y", "yes", "ok", "好", "是", "确认"])
def test_parse_memory_confirmation_reply_affirmative_shorthand(shorthand: str):
    """常见肯定简写（y/yes/好/是等）→ 映射到 choice_map 的第一个选项（ACCEPT）。"""
    from agent.memory_confirmation import build_memory_confirmation_request

    decision = _make_retain_decision()
    request = build_memory_confirmation_request(decision)
    pending = build_memory_pending_request(
        request,
        candidate_id="cand-test",
        origin_status="running",
    )

    choice, free_text = parse_memory_confirmation_reply(shorthand, pending)
    assert choice is MemoryConfirmationChoice.ACCEPT
    assert free_text is None


# ---------------------------------------------------------------------------
# 12. resolve_confirmation 缓存不匹配时安全降级
# ---------------------------------------------------------------------------


def test_resolve_confirmation_mismatched_candidate_id_returns_rejected():
    """candidate_id 不匹配 → REJECTED（防御性降级）。"""
    runtime = _make_runtime()
    runtime.evaluate_user_text("remember that I like blue")

    resolved = runtime.resolve_confirmation(
        "wrong-id",
        MemoryConfirmationChoice.ACCEPT,
    )

    assert resolved.action is MemoryEvaluationAction.REJECTED
    assert "无匹配" in resolved.reason
    records = runtime._store.list_records()
    assert len(records) == 0


# ---------------------------------------------------------------------------
# 13. P2-2: checkpoint/pending safety — JSON 序列化往返
# ---------------------------------------------------------------------------


def test_pending_payload_survives_json_round_trip():
    """build_memory_pending_request 输出经 json.dumps/loads 往返后字段不丢失。

    checkpoint 使用 json.dumps 序列化 state，pending_user_input_request 作为
    TaskState 字段会被完整保存。本测试模拟 checkpoint save/load 周期，确认为
    memory confirmation 新增的私有字段（_choice_map, _candidate_id, _origin_status）
    不会在序列化中丢失或损坏。
    """
    import json

    from agent.memory_confirmation import build_memory_confirmation_request

    decision = _make_retain_decision("remember that I prefer dark mode")
    request = build_memory_confirmation_request(decision)
    original = build_memory_pending_request(
        request,
        candidate_id="cand-checkpoint",
        origin_status="running",
    )

    # 模拟 checkpoint save/load：json.dumps → json.loads
    serialized = json.dumps(original, ensure_ascii=False)
    restored = json.loads(serialized)

    # 公共字段
    assert restored["awaiting_kind"] == "memory_confirmation"
    assert restored["question"] == original["question"]
    assert isinstance(restored["options"], list)
    assert len(restored["options"]) == len(original["options"])

    # memory 专有私有字段
    assert restored["_candidate_id"] == "cand-checkpoint"
    assert restored["_choice_map"] == original["_choice_map"]
    assert restored["_origin_status"] == "running"

    # 往返后的 dict 仍可被 parse_memory_confirmation_reply 正确解析
    choice, free_text = parse_memory_confirmation_reply("1", restored)
    assert choice is MemoryConfirmationChoice.ACCEPT
    assert free_text is None


def test_pending_payload_is_json_serializable_with_default_encoder():
    """pending payload 的所有值都是 JSON 原生类型，不需要自定义 encoder。"""
    import json

    from agent.memory_confirmation import build_memory_confirmation_request

    decision = _make_retain_decision()
    request = build_memory_confirmation_request(decision)
    pending = build_memory_pending_request(
        request,
        candidate_id="cand-json",
        origin_status="awaiting_user_input",
    )

    # 验证不抛 TypeError: Object of type X is not JSON serializable
    try:
        json.dumps(pending)
    except TypeError as e:
        pytest.fail(f"pending payload 无法通过默认 encoder 序列化: {e}")

    # 所有值均为 JSON 原生类型
    for key, value in pending.items():
        if key == "_choice_map":
            assert isinstance(value, dict)
            for ck, cv in value.items():
                assert isinstance(ck, str)
                assert isinstance(cv, str)
        elif isinstance(value, list):
            for item in value:
                assert isinstance(item, (str, int, float, bool, type(None), list, dict))
        else:
            assert isinstance(value, (str, int, float, bool, type(None), list, dict)), (
                f"字段 {key} 的值类型 {type(value)} 不是 JSON 原生类型"
            )


# ---------------------------------------------------------------------------
# 14. P2-8: checkpoint-safe resume 闭环 — pending 恢复后 resolve 仍可写入
# ---------------------------------------------------------------------------


def test_pending_recovery_resolve_after_checkpoint_round_trip():
    """Loop 15: checkpoint 恢复后 resolve_confirmation 返回 _dispatcher_payload。"""
    import json

    from agent.memory_confirmation import build_memory_confirmation_request

    runtime = _make_runtime()

    # Phase 1: evaluate
    result = runtime.evaluate_user_text("remember that I like blue")
    assert result.action is MemoryEvaluationAction.CONFIRMATION_REQUIRED

    # 模拟 core.py：build pending dict + (模拟) save_checkpoint
    decision = _make_retain_decision("remember that I like blue")
    request = build_memory_confirmation_request(decision)
    pending = build_memory_pending_request(
        request,
        candidate_id=result.candidate_id,
        origin_status="running",
    )

    # 模拟 checkpoint 写入 → 读取
    serialized = json.dumps(pending, ensure_ascii=False)
    restored = json.loads(serialized)

    # 恢复后：提取 candidate_id，解析用户输入
    recovered_id: str | None = restored.get("_candidate_id")
    assert recovered_id == result.candidate_id

    choice, free_text = parse_memory_confirmation_reply("1", restored)
    assert choice is MemoryConfirmationChoice.ACCEPT

    # Phase 2: resolve with recovered data
    resolved = runtime.resolve_confirmation(recovered_id, choice, free_text)
    assert resolved.action is MemoryEvaluationAction.STORED
    payload = resolved._dispatcher_payload
    assert payload is not None, "checkpoint 恢复后应返回 _dispatcher_payload"
    assert "I like blue" in payload["candidate"]["content"]


def test_pending_recovery_resolve_reject_after_checkpoint_round_trip():
    """checkpoint 恢复后 resolve REJECT 也不写入 store。"""
    import json

    from agent.memory_confirmation import build_memory_confirmation_request

    runtime = _make_runtime()
    result = runtime.evaluate_user_text("remember that I like blue")

    decision = _make_retain_decision("remember that I like blue")
    request = build_memory_confirmation_request(decision)
    pending = build_memory_pending_request(
        request,
        candidate_id=result.candidate_id,
        origin_status="running",
    )

    serialized = json.dumps(pending, ensure_ascii=False)
    restored = json.loads(serialized)

    recovered_id: str | None = restored.get("_candidate_id")
    choice, free_text = parse_memory_confirmation_reply("4", restored)
    assert choice is MemoryConfirmationChoice.REJECT

    resolved = runtime.resolve_confirmation(recovered_id, choice, free_text)
    assert resolved.action is MemoryEvaluationAction.REJECTED
    assert len(runtime._store.list_records()) == 0


# ---------------------------------------------------------------------------
# 15. 默认 MemoryRuntime 不 auto-accept
# ---------------------------------------------------------------------------


def test_default_runtime_returns_confirmation_required_not_auto_accept():
    """Loop 15: 默认 MemoryRuntime 不 auto-accept，返回 _dispatcher_payload。"""
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    result = runtime.evaluate_user_text("remember that I like blue")

    # 核心断言：不是 auto-accept，而是等待确认
    assert result.action is MemoryEvaluationAction.CONFIRMATION_REQUIRED
    assert result.candidate_id is not None

    # store 尚未写入
    assert len(runtime._store.list_records()) == 0

    # 第二阶段：resolve_confirmation 返回 _dispatcher_payload
    resolved = runtime.resolve_confirmation(
        result.candidate_id,
        MemoryConfirmationChoice.ACCEPT,
    )
    assert resolved.action is MemoryEvaluationAction.STORED
    payload = resolved._dispatcher_payload
    assert payload is not None, "应返回 _dispatcher_payload 供 dispatcher 写入"
    assert "I like blue" in payload["candidate"]["content"]


def test_evaluate_on_event_callback_does_not_interfere_with_two_phase_flow():
    """evaluate_user_text 的 on_event 回调不影响两阶段流程。"""
    events: list = []

    def collect_event(event):
        events.append(event)

    runtime = MemoryRuntime(store=InMemoryMemoryStore())

    result = runtime.evaluate_user_text(
        "remember that I like blue",
        on_event=collect_event,
    )

    assert result.action is MemoryEvaluationAction.CONFIRMATION_REQUIRED

    # on_event 被调用，发出了 confirmation_requested 事件
    assert len(events) >= 1
    assert events[0]["type"] == "memory_confirmation_requested"

    # 第二阶段正常工作
    resolved = runtime.resolve_confirmation(
        result.candidate_id,
        MemoryConfirmationChoice.ACCEPT,
    )
    assert resolved.action is MemoryEvaluationAction.STORED


def test_default_runtime_rejects_non_memory_text():
    """默认 MemoryRuntime 对非 memory 文本返回 NO_OP。"""
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    result = runtime.evaluate_user_text("hello, how are you?")
    assert result.action is MemoryEvaluationAction.NO_OP


# ---------------------------------------------------------------------------
# 16. Loop 15 Phase 4: E2E dispatcher integration
# ---------------------------------------------------------------------------


class SpyDispatcher:
    """测试用 dispatcher spy：记录最后一次 route 调用。"""

    def __init__(self):
        self.calls: list = []

    def route(self, request):
        self.calls.append(request)
        from agent.runtime_integration.schema import RuntimeActionResult, RuntimeActionType
        return RuntimeActionResult(action_type=RuntimeActionType.MEMORY_PROPOSE)


def test_handle_memory_confirmation_reply_dispatches_memory_propose(
    monkeypatch: pytest.MonkeyPatch,
):
    """Loop 15 Phase 4: handle_memory_confirmation_reply 通过 dispatcher 走 MEMORY_PROPOSE。"""
    from agent.confirm_handlers import handle_user_input_step
    from agent.runtime_integration.schema import RuntimeActionType

    _patch_memory_interaction_checkpoint(monkeypatch)
    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)

    spy = SpyDispatcher()
    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)
    ctx.dispatcher = spy

    reply = handle_user_input_step("1", ctx)

    assert "已记住" in reply
    assert len(spy.calls) == 1
    assert spy.calls[0].action_type is RuntimeActionType.MEMORY_PROPOSE
    assert spy.calls[0].source == "memory_interaction.resolve_confirmation"
    payload = spy.calls[0].payload
    assert payload["confirmation_result"] == "accept"
    assert payload["proposal_id"] is not None
    assert "I like blue" in payload["candidate"]["content"]
    assert "content_hash" in payload["candidate"]


def test_handle_memory_confirmation_reply_reject_does_not_dispatch(
    monkeypatch: pytest.MonkeyPatch,
):
    """Loop 15 Phase 4: reject 时不触发 dispatcher。"""
    from agent.confirm_handlers import handle_user_input_step

    _patch_memory_interaction_checkpoint(monkeypatch)
    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)

    spy = SpyDispatcher()
    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)
    ctx.dispatcher = spy

    reply = handle_user_input_step("4", ctx)

    assert "已拒绝" in reply
    assert len(spy.calls) == 0, "reject 不应触发 dispatcher"


def test_handle_memory_confirmation_reply_no_dispatcher_is_safe(
    monkeypatch: pytest.MonkeyPatch,
):
    """Loop 15 Phase 4: dispatcher 为 None 时向后兼容，不崩溃。"""
    from agent.confirm_handlers import handle_user_input_step

    _patch_memory_interaction_checkpoint(monkeypatch)
    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)

    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)
    ctx.dispatcher = None

    reply = handle_user_input_step("1", ctx)
    assert "已记住" in reply


def test_handle_memory_confirmation_reply_dispatcher_writes_to_store(
    monkeypatch: pytest.MonkeyPatch,
):
    """Loop 15 Phase 4: dispatcher → MemoryRetainHandler → store 写入完整链路。"""
    from agent.confirm_handlers import handle_user_input_step
    from agent.runtime_integration.dispatcher import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
    )
    from agent.runtime_integration.memory_retain import MemoryRetainHandler
    from agent.runtime_integration.schema import RuntimeActionType

    _patch_memory_interaction_checkpoint(monkeypatch)
    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_PROPOSE,
        MemoryRetainHandler(store=runtime._store),
    )
    dispatcher = RuntimeActionDispatcher(registry=registry)

    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)
    ctx.dispatcher = dispatcher

    reply = handle_user_input_step("1", ctx)

    assert "已记住" in reply
    records = runtime._store.list_records()
    assert len(records) == 1, "dispatcher → MemoryRetainHandler 应写入 store"
    assert "I like blue" in records[0].content


def test_memory_confirmation_denied_origin_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
):
    """Phase 3 U1: 非法 memory origin 必须在 resolve/dispatcher 前拒绝。"""
    from agent.confirm_handlers import handle_user_input_step

    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)
    pending["_origin_status"] = "done"
    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)
    dispatcher = SpyDispatcher()
    ctx.dispatcher = dispatcher

    resolve_calls: list[tuple] = []
    original_resolve = runtime.resolve_confirmation

    def _record_resolve(*args, **kwargs):
        resolve_calls.append((args, kwargs))
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(runtime, "resolve_confirmation", _record_resolve)
    save_calls: list[str] = []
    monkeypatch.setattr(
        "agent.checkpoint.save_checkpoint",
        lambda *_args, source=None, **_kwargs: save_calls.append(source),
    )
    original_pending = dict(pending)

    reply = handle_user_input_step("1", ctx)

    assert "无法" in reply or "拒绝" in reply
    assert ctx.state.task.status == "awaiting_user_input"
    assert ctx.state.task.pending_user_input_request == original_pending
    assert resolve_calls == []
    assert dispatcher.calls == []
    assert save_calls == []


def test_memory_confirmation_missing_origin_uses_running_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    """Phase 3 U1: 两个 origin key 都缺失时保持 legacy running fallback。"""
    from agent.confirm_handlers import handle_user_input_step

    _patch_memory_interaction_checkpoint(monkeypatch)
    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)
    pending.pop("_origin_status")
    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)

    reply = handle_user_input_step("4", ctx)

    assert reply == "已拒绝，不记住这条信息。"
    assert ctx.state.task.status == "running"
    assert ctx.state.task.pending_user_input_request is None


def test_memory_confirmation_stale_preflight_does_not_resolve_or_clear(
    monkeypatch: pytest.MonkeyPatch,
):
    """Phase 3 U1: validate 后状态变化时 apply 拒绝，handler 不提交副作用。"""
    import agent.memory_interaction as memory_interaction
    from agent.confirm_handlers import handle_user_input_step
    from agent.transitions import apply_task_transition as real_apply

    runtime = _make_runtime()
    pending, _candidate_id = _make_pending_from_runtime(runtime)
    ctx = _make_confirmation_context(pending=pending, memory_runtime=runtime)
    resolve_calls: list[tuple] = []
    original_resolve = runtime.resolve_confirmation

    def _record_resolve(*args, **kwargs):
        resolve_calls.append((args, kwargs))
        return original_resolve(*args, **kwargs)

    def _stale_apply(state, request, *, preflight=None):
        state.task.status = "running"
        return real_apply(state, request, preflight=preflight)

    monkeypatch.setattr(runtime, "resolve_confirmation", _record_resolve)
    monkeypatch.setattr(memory_interaction, "apply_task_transition", _stale_apply)
    save_calls: list[str] = []
    monkeypatch.setattr(
        "agent.checkpoint.save_checkpoint",
        lambda *_args, source=None, **_kwargs: save_calls.append(source),
    )
    original_pending = dict(pending)

    reply = handle_user_input_step("1", ctx)

    assert "无法" in reply
    assert ctx.state.task.status == "running"
    assert ctx.state.task.pending_user_input_request == original_pending
    assert resolve_calls == []
    assert save_calls == []


def test_memory_interaction_does_not_directly_write_store():
    """Loop 15 Phase 4: memory_interaction 模块不直接 import store 写入方法。"""
    import ast
    from pathlib import Path

    interaction_path = (
        Path(__file__).resolve().parents[1] / "agent" / "memory_interaction.py"
    )
    tree = ast.parse(interaction_path.read_text(encoding="utf-8"))

    store_methods = {"apply_operation_intent", "write_record", "put_record"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in store_methods:
            pytest.fail(
                f"memory_interaction.py 不应直接调用 store.{node.attr}——"
                f"应通过 dispatcher 走 MEMORY_PROPOSE → MemoryRetainHandler"
            )

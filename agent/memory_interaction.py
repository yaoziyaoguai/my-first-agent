"""Memory Interactive Confirmation v1 — pending request / reply parsing / handling.

本模块是 MemoryRuntime 确认需求与现有 awaiting_user_input +
pending_user_input_request 机制之间的桥接层。它**不**读写 store、不调用 LLM、
**模块级不** import checkpoint、不 import MCP/provider。

职责边界：
- build_memory_pending_request: MemoryConfirmationRequest → JSON-safe pending dict
- parse_memory_confirmation_reply: 用户输入 → (choice, free_text)
- handle_memory_confirmation_reply: 完整 handler，由 confirm_handlers 委托

v1 已知妥协：
- handle_memory_confirmation_reply 内部 lazy import save_checkpoint 以清 pending
  并保存状态。checkpoint 依赖注入（而非本模块直接 own checkpoint）是更干净的架构，
  但当前上移 save_checkpoint 到调用方需要重构 handler 返回接口，保留为 v1 compromise。
- 本模块不模块级 import checkpoint，AST boundary tests 已验证。
"""

from __future__ import annotations

import contextlib
import hashlib
from datetime import datetime, timezone
from typing import Any, Protocol

from agent.display_events import (
    RuntimeEvent,
    RuntimeEventSink,
)
from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    MemoryConfirmationRequest,
)
from agent.memory_emergence import (
    InlineConfirmationRequest,
    InlineConfirmationResponse,
)
from agent.pending_requests import PendingUserInputRequest
from agent.transitions import (
    CheckpointAction,
    TaskTransitionRequest,
    TransitionEvent,
    apply_task_transition,
    validate_task_transition,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# MemoryRuntime 的 resolve_confirmation 接口（避免循环 import）
class MemoryRuntimeProtocol(Protocol):
    def resolve_confirmation(
        self,
        candidate_id: str | None,
        choice: MemoryConfirmationChoice,
        free_text: str | None = None,
) -> Any: ...


def build_memory_pending_request(
    confirmation_request: MemoryConfirmationRequest,
    *,
    candidate_id: str | None,
    origin_status: str,
) -> PendingUserInputRequest:
    """把 MemoryConfirmationRequest 投影为 JSON-safe pending_user_input_request dict。

    本函数只做数据转换，不写 state、不写 checkpoint、不调 LLM。
    """
    option_lines: list[str] = []
    choice_map: dict[str, str] = {}
    for i, opt in enumerate(confirmation_request.options, start=1):
        key = str(i)
        choice_map[key] = opt.choice.value
        suffix = "（需附文本）" if opt.requires_free_text else ""
        option_lines.append(f"{key}. {opt.label}{suffix} — {opt.description}")

    return {
        "awaiting_kind": "memory_confirmation",
        "question": confirmation_request.question,
        "why_needed": "请选择如何处理这条记忆（输入数字选择，或输入自由文本）。",
        "options": option_lines,
        "context": "",
        "tool_use_id": "",
        "step_index": None,
        "_candidate_id": candidate_id,
        "_choice_map": choice_map,
        "_origin_status": origin_status,
    }


AFFIRMATIVE_SHORTHANDS: frozenset[str] = frozenset({
    "y", "yes", "ok", "okay", "yeah", "sure",
    "好", "是", "可以", "确认", "记住", "行", "对",
})
"""确认交互中的肯定简写词表（中英双语）。

用户在这些确认流程中输入任意一个简写即视为肯定回复：
- ``parse_memory_confirmation_reply()``：视为选择第一个选项
- ``parse_inline_confirmation_reply()``：视为 accept

如需增加更多语言变体，直接扩展此 frozenset 即可，无需修改解析逻辑。
"""


def parse_memory_confirmation_reply(
    user_text: str,
    pending: PendingUserInputRequest,
) -> tuple[MemoryConfirmationChoice, str | None]:
    """把用户回复解析为 (choice, free_text)，不执行任何副作用。

    解析规则：
    - "1"~"N" 精确匹配 → 对应 choice
    - "<数字> <文本>" → 对应 choice + free_text（用于 edit/other 等需附文本的选择）
    - 常见肯定简写（y/yes/好/是等）→ 视为选择第一个选项
    - 其他任意文本 → OTHER + 全文作为 free_text
    """
    choice_map: dict[str, str] = pending.get("_choice_map", {})
    text = user_text.strip()

    if not text:
        raise ValueError("输入为空，请重新选择。")

    if text in choice_map:
        return MemoryConfirmationChoice(choice_map[text]), None

    for key, choice_str in choice_map.items():
        if text.startswith(key + " ") or text.startswith(key + "\t"):
            free_text = text[len(key):].strip()
            return MemoryConfirmationChoice(choice_str), free_text

    # 常见肯定简写 → 第一个选项（通用确认 UX，不是 provider-specific hack）
    if text.lower() in AFFIRMATIVE_SHORTHANDS:
        first_choice_str = next(iter(choice_map.values()))
        return MemoryConfirmationChoice(first_choice_str), None

    return MemoryConfirmationChoice.OTHER, text


def build_inline_confirmation_pending_request(
    request: InlineConfirmationRequest,
    *,
    origin_status: str,
) -> PendingUserInputRequest:
    """把 InlineConfirmationRequest 投影为 Ask User 兼容 pending dict。

    架构边界：memory emergence 只产出 request；本 adapter 只做 JSON-safe
    pending_user_input_request 转换，不写 store、不调用 UI、不 print/input。
    """
    choice_map = {
        "1": "accept",
        "2": "reject",
        "3": "edit",
        "4": "other",
    }
    options = [
        "1. Accept — 记住这条 procedural memory",
        "2. Reject — 不记住这条 procedural memory",
        "3. Edit — 输入 3 后接编辑后的内容并确认记住",
        "4. Other / free text — 其他回复或补充说明（不会自动写入）",
    ]

    return {
        "awaiting_kind": "memory_inline_confirmation",
        "question": (
            "是否将这条行为规则记为 procedural memory？\n"
            f"{request.candidate_content}"
        ),
        "why_needed": (
            "Procedural memory 会影响未来行为，必须经过 explicit human "
            "confirmation；拒绝、其他文本或无响应都不会写入正式 store。"
        ),
        "options": options,
        "actions": ["accept", "reject", "edit", "other"],
        "context": "",
        "tool_use_id": "",
        "step_index": None,
        "_origin_status": origin_status,
        "_choice_map": choice_map,
        "_inline_confirmation_request": _inline_request_to_pending_payload(request),
    }


def parse_inline_confirmation_reply(
    user_text: str,
    pending: PendingUserInputRequest,
) -> InlineConfirmationResponse:
    """把用户回复解析为无副作用 InlineConfirmationResponse。

    解析层只表达用户意图，不写 store。只有 handler 收到 accept/edit_accept 后，
    才能把 response 交给 memory_emergence.apply_inline_confirmation_response()。
    """
    text = (user_text or "").strip()
    if not text:
        raise ValueError("未收到 inline confirmation 回复")

    choice_map: dict[str, str] = pending.get("_choice_map", {})

    if text in choice_map:
        action = choice_map[text]
        if action == "accept":
            return InlineConfirmationResponse(action="accept")
        if action == "reject":
            return InlineConfirmationResponse(action="reject")
        if action == "other":
            return InlineConfirmationResponse(action="other", free_text="用户选择 other")
        if action == "edit":
            raise ValueError("edit 需要提供编辑后的内容")

    for key, action in choice_map.items():
        if text.startswith(key + " ") or text.startswith(key + "\t"):
            free_text = text[len(key):].strip()
            if action == "accept":
                return InlineConfirmationResponse(action="accept")
            if action == "reject":
                return InlineConfirmationResponse(action="reject")
            if action == "edit":
                return InlineConfirmationResponse(
                    action="edit_accept",
                    edited_content=free_text,
                )
            return InlineConfirmationResponse(action="other", free_text=free_text)

    # 常见肯定简写 → accept（与 parse_memory_confirmation_reply 共享同一词表）
    if text.lower() in AFFIRMATIVE_SHORTHANDS:
        return InlineConfirmationResponse(action="accept")

    return InlineConfirmationResponse(action="other", free_text=text)


def handle_memory_confirmation_reply(
    user_text: str,
    ctx: Any,
    *,
    memory_runtime: MemoryRuntimeProtocol,
    on_runtime_event: RuntimeEventSink | None = None,
    dispatcher: Any = None,
) -> str:
    """处理 memory confirmation 的用户回复，委托 confirm_handlers 调用。

    本函数负责：
    1. 解析用户输入 → (choice, free_text)
    2. 调 memory_runtime.resolve_confirmation 执行实际写入/拒绝
    3. 若 _dispatcher_payload 存在，通过 dispatcher 走 MEMORY_PROPOSE → MemoryRetainHandler
    4. 清 pending、恢复 status、save checkpoint
    5. emit 结果 RuntimeEvent

    不负责：
    - 不直接操作 store
    - 不调 LLM
    - 不 import low-level checkpoint（通过 runtime checkpoint gateway 间接操作）
    """
    from agent.memory_runtime import MemoryEvaluationAction

    state = ctx.state
    pending = state.task.pending_user_input_request or {}
    # 1. 解析用户选择
    try:
        choice, free_text = parse_memory_confirmation_reply(user_text, pending)
    except ValueError:
        # 空输入：不清 pending，让用户重新输入
        return "请输入有效选项（数字 1-5 或自由文本）。"

    candidate_id: str | None = pending.get("_candidate_id")

    transition_request = TaskTransitionRequest(
        event=TransitionEvent.MEMORY_CONFIRMATION_RESOLVED,
        owner="memory_interaction.resolve_confirmation",
        expected_from_status="awaiting_user_input",
    )
    preflight = validate_task_transition(state, transition_request)
    if not preflight.allowed:
        return f"无法处理 memory confirmation：{preflight.reason}"
    transition = apply_task_transition(
        state,
        transition_request,
        preflight=preflight,
    )
    if not transition.allowed:
        return f"无法处理 memory confirmation：{transition.reason}"
    assert transition.checkpoint_action is CheckpointAction.SAVE

    # 2. 执行确认结果（direct_write=False：由 dispatcher 统一写入，避免双写）
    result = memory_runtime.resolve_confirmation(
        candidate_id, choice, free_text, direct_write=False,
    )
    # result is MemoryEvaluationResult

    # 3. 若 _dispatcher_payload 存在，通过 dispatcher 走统一写入路径
    if (
        result.action is MemoryEvaluationAction.STORED
        and result._dispatcher_payload is not None
        and dispatcher is not None
    ):
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

        _req = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_PROPOSE,
            source="memory_interaction.resolve_confirmation",
            parent_trace_id="",
            payload=result._dispatcher_payload,
        )
        dispatcher.route(_req)

    # 4. transition 已恢复状态；此处只提交其余副作用。
    state.task.pending_user_input_request = None

    if result.action is MemoryEvaluationAction.STORED:
        from agent.display_events import memory_stored_event as _stored_evt
        _sink_runtime_event(on_runtime_event, _stored_evt(result.content_summary))
        reply = f"已记住：{result.content_summary}"
    elif result.action is MemoryEvaluationAction.REJECTED:
        reply = "已拒绝，不记住这条信息。"
    elif result.action is MemoryEvaluationAction.BLOCKED:
        from agent.display_events import memory_blocked_event as _blocked_evt
        _sink_runtime_event(on_runtime_event, _blocked_evt(result.reason))
        reply = f"已拦截：{result.reason}"
    else:
        reply = f"已处理：{result.reason}"

    from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint

    save_runtime_checkpoint(state, source="memory_interaction.resolve")
    return reply


def handle_inline_confirmation_reply(
    user_text: str,
    ctx: Any,
    *,
    store: Any,
    on_runtime_event: RuntimeEventSink | None = None,
    fallback_memory_root: Any | None = None,
) -> str:
    """处理 inline confirmation 的用户回复。

    学习型边界说明：
    - 本函数是 Ask User pending dict 与 memory_emergence write boundary 之间的
      adapter，不做 emergence detection，也不驱动 UI。
    - accept/edit_accept 是 explicit confirmation，才调用
      apply_inline_confirmation_response()。
    - reject/other/no response 都是 no-write；no response 通过 pending_review
      兜底保存 candidate，避免 inline 失败导致候选丢失。
    """
    from agent.memory_emergence import apply_inline_confirmation_response
    from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint

    state = ctx.state
    pending = state.task.pending_user_input_request or {}
    transition_request = TaskTransitionRequest(
        event=TransitionEvent.MEMORY_CONFIRMATION_RESOLVED,
        owner="memory_interaction.inline_confirmation",
        expected_from_status="awaiting_user_input",
    )
    preflight = validate_task_transition(state, transition_request)
    if not preflight.allowed:
        return f"无法处理 inline memory confirmation：{preflight.reason}"

    try:
        request = _inline_request_from_pending(pending)
    except (KeyError, TypeError, ValueError) as exc:
        transition = apply_task_transition(
            state,
            transition_request,
            preflight=preflight,
        )
        if not transition.allowed:
            return f"无法处理 inline memory confirmation：{transition.reason}"
        _clear_pending_and_save(state, save_runtime_checkpoint)
        return f"未写入：inline confirmation payload 无效（{exc}）。"

    try:
        response = parse_inline_confirmation_reply(user_text, pending)
    except ValueError:
        transition = apply_task_transition(
            state,
            transition_request,
            preflight=preflight,
        )
        if not transition.allowed:
            return f"无法处理 inline memory confirmation：{transition.reason}"
        fallback = _fallback_inline_confirmation_to_pending_review(
            request,
            memory_root=fallback_memory_root,
        )
        _clear_pending_and_save(state, save_runtime_checkpoint)
        if getattr(fallback, "dispatched", 0) == 0 and any(
            warning == "durable_memory_root_not_configured"
            for warning in getattr(fallback, "warnings", ())
        ):
            return (
                "未收到确认回复，pending_review fallback 已跳过："
                "durable_memory_root_not_configured；未写入正式 procedural store。"
            )
        return (
            "未收到确认回复，已 fallback 到 pending_review；"
            f"未写入正式 procedural store（dispatched={fallback.dispatched}）。"
        )

    transition = apply_task_transition(
        state,
        transition_request,
        preflight=preflight,
    )
    if not transition.allowed:
        return f"无法处理 inline memory confirmation：{transition.reason}"
    assert transition.checkpoint_action is CheckpointAction.SAVE

    if response.action in {"accept", "edit_accept"}:
        # 将已确认的 proposal 入队，由 turn-end hook 中 MEMORY_PROPOSE dispatch 执行写入。
        # 不在 confirmation handler 中直接写 store——MEMORY_PROPOSE 通过 dispatcher 提供
        # RuntimeActionEvent evidence chain，是 retain execution 的正式路径。
        if response.action == "edit_accept":
            content = response.edited_content
        else:
            content = request.candidate_content
        content_hash_val = hashlib.sha256(content.encode()).hexdigest()
        state.task.pending_retain_proposals.append({
            "proposal_id": request.proposal_id,
            "content": content,
            "content_hash": content_hash_val,
            "scope": request.scope or "user",
            "sensitivity": "low",
            "source": "turn_end_proposal",
            "confirmation_result": "accepted",
            "queued_at": _now_iso(),
        })
        _clear_pending_and_save(state, save_runtime_checkpoint)
        return "已确认，将在下一轮通过 runtime dispatcher 写入 procedural memory。"

    result = apply_inline_confirmation_response(request, response, store)
    _clear_pending_and_save(state, save_runtime_checkpoint)
    if result.action == "reject":
        return "已拒绝，未写入 procedural memory。"
    return "已记录为其他回复，未写入 procedural memory。"


def _inline_request_to_pending_payload(
    request: InlineConfirmationRequest,
) -> dict[str, Any]:
    """把 dataclass request 转成 checkpoint-safe dict。"""
    return {
        "candidate_content": request.candidate_content,
        "source_evidence": list(request.source_evidence),
        "correction_pattern": request.correction_pattern,
        "correction_type": request.correction_type,
        "scope": request.scope,
        "evidence_summary": request.evidence_summary,
        "confidence": request.confidence,
        "confirmation_form": request.confirmation_form,
        "allowed_actions": list(request.allowed_actions),
        "proposal_id": request.proposal_id,
        "created_at": request.created_at,
    }


def _inline_request_from_pending(
    pending: dict[str, Any],
) -> InlineConfirmationRequest:
    """从 pending dict 还原 InlineConfirmationRequest。

    pending_user_input_request 会进入 checkpoint；handler 恢复时不能依赖内存中的
    dataclass 对象，所以这里显式从 JSON-safe payload 还原。
    """
    payload = pending["_inline_confirmation_request"]
    return InlineConfirmationRequest(
        candidate_content=payload["candidate_content"],
        source_evidence=tuple(payload["source_evidence"]),
        correction_pattern=payload["correction_pattern"],
        correction_type=payload["correction_type"],
        scope=payload.get("scope"),
        evidence_summary=payload.get("evidence_summary"),
        confidence=payload["confidence"],
        confirmation_form=payload["confirmation_form"],
        allowed_actions=tuple(payload["allowed_actions"]),
        proposal_id=payload["proposal_id"],
        created_at=payload["created_at"],
    )


def _fallback_inline_confirmation_to_pending_review(
    request: InlineConfirmationRequest,
    *,
    memory_root: Any | None,
):
    """将 inline 无响应候选保存到 pending_review，不写正式 store。"""
    from agent.memory_emergence import (
        ProceduralCandidate,
        dispatch_procedural_candidates_to_pending_review,
    )

    candidate = ProceduralCandidate(
        content=request.candidate_content,
        memory_type="procedural",
        source_evidence=request.source_evidence,
        correction_pattern=request.correction_pattern,
        correction_type=request.correction_type,
        scope=request.scope,
        confidence=request.confidence,
        governance_route="T1",
        evidence_summary=request.evidence_summary,
        created_at=request.created_at,
    )
    return dispatch_procedural_candidates_to_pending_review(
        [candidate],
        memory_root=memory_root,
        source="phase7_inline_confirmation_fallback",
    )


def _clear_pending_and_save(
    state: Any,
    save_checkpoint_fn: Any,
) -> None:
    """transition 成功后清理 terminal inline pending 并保存。"""
    state.task.pending_user_input_request = None
    save_checkpoint_fn(state, source="memory_interaction.inline_confirmation")


def _sink_runtime_event(
    sink: RuntimeEventSink | None,
    event: RuntimeEvent,
) -> None:
    """安全投递 RuntimeEvent，sink 为 None 或抛异常时静默吞掉。"""
    if sink is None:
        return
    with contextlib.suppress(Exception):
        sink(event)

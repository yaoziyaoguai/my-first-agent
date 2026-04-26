"""显式 transition 层：把输入解析结果落地成 runtime 状态变化。

`input_resolution` 和本模块的边界很重要：
- `input_resolution` 只判断用户输入属于哪类语义，不改 state；
- `transitions` 执行真正的 action，例如 append step_input、清 pending、
  推进 step、保存 checkpoint。

第一阶段这里只处理 `awaiting_user_input + USER_REPLIED`，不是完整状态机框架，
也不是通用 action engine。目标是先把最容易混淆的用户输入恢复链路显式化。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent import checkpoint
from agent.conversation_events import append_control_event
from agent.input_resolution import (
    COLLECT_INPUT_ANSWER,
    RUNTIME_USER_INPUT_ANSWER,
    InputResolution,
)
from agent.runtime_observer import log_actions, log_transition
from agent.task_runtime import advance_current_step_if_needed


EVENT_USER_REPLIED = "user.replied"


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """transition 执行后的控制结果。

    - should_continue_loop：告诉 handler 是否要立刻回到 agent 主循环继续执行。
      runtime_user_input_answer 和普通 collect_input 推进后通常需要继续。
    - reply：如果不继续 loop，需要返回给 CLI 的控制文案，例如等待 step 确认、
      或任务完成提示。

    target_status 目前不单独作为字段返回，因为第一阶段 transition 已直接修改
    `state.task.status`，handler 只需要知道“继续 loop 还是把 reply 返回用户”。
    """

    should_continue_loop: bool
    reply: str = ""


def apply_user_replied_transition(
    *,
    state: Any,
    messages: list[dict[str, Any]],
    resolution: InputResolution,
) -> TransitionResult:
    """执行 `awaiting_user_input + USER_REPLIED` 的显式状态转移。

    两条路径的语义不同：
    - `collect_input_answer`：用户回答的是计划中的信息收集/澄清步骤。这个 step
      的目标就是获得用户信息，所以答复写入 messages 后应推进当前 step。
    - `runtime_user_input_answer`：用户回答的是执行中途 request_user_input 或
      fallback 暂停的问题。它只是给当前 step 补上下文，step 是否完成仍需要模型
      后续调用 mark_step_complete，因此不能推进 current_step_index。

    两条路径都要保存 checkpoint，因为用户回复后 state 和 conversation.messages
    都发生了关键变化；此时如果进程中断，恢复后必须能看到这次答复。
    """
    if resolution.kind == RUNTIME_USER_INPUT_ANSWER:
        pending = resolution.pending_user_input_request or {}
        # request_user_input 是 runtime 控制信号，不把它的 tool_use/tool_result
        # 放进 messages；真正给模型看的，是用户答复被渲染成 step_input 后的文本。
        append_control_event(messages, "step_input", {
            "question": pending.get("question", ""),
            "why_needed": pending.get("why_needed", ""),
            "content": resolution.content,
        })
        # pending 表示“系统正在等这一条用户答复”。答复已经写入 step_input 后，
        # 必须清掉 pending，否则下一轮用户输入还会被误认为是在回答旧问题。
        state.task.pending_user_input_request = None
        state.task.status = "running"
        checkpoint.save_checkpoint(state, source="transitions.runtime_user_input_answer")
        log_transition(
            from_state="awaiting_user_input",
            event_type=EVENT_USER_REPLIED,
            target_state="running",
        )
        log_actions([
            "append_step_input_with_question",
            "clear_pending_user_input",
            "save_checkpoint",
        ])
        return TransitionResult(should_continue_loop=True)

    if resolution.kind == COLLECT_INPUT_ANSWER:
        # collect_input/clarify 本身就是计划里的一个 step；用户答复就是这个 step
        # 的产出，因此写入普通 step_input 后可以进入步骤推进逻辑。
        append_control_event(messages, "step_input", {"content": resolution.content})
        current_plan = state.task.current_plan or {}
        total_steps = len(current_plan.get("steps", []))
        is_last_step = state.task.current_step_index >= max(total_steps - 1, 0)

        if state.task.confirm_each_step and not is_last_step:
            # 保留原有“每步确认”语义：collect_input 已完成，但是否进入下一步
            # 仍交给用户确认，所以这里不直接 advance。
            state.task.status = "awaiting_step_confirmation"
            checkpoint.save_checkpoint(state, source="transitions.collect_input_answer")
            log_transition(
                from_state="awaiting_user_input",
                event_type=EVENT_USER_REPLIED,
                target_state="awaiting_step_confirmation",
            )
            log_actions(["append_step_input", "save_checkpoint"])
            return TransitionResult(
                should_continue_loop=False,
                reply="\n[请确认: y 进入下一步 / n 停止任务 / 输入意见以重规划]",
            )

        advance_current_step_if_needed(state)

        if state.task.status == "done":
            # 最后一个 collect_input/clarify step 被用户答复后，任务可能直接完成。
            checkpoint.clear_checkpoint()
            state.reset_task()
            log_transition(
                from_state="awaiting_user_input",
                event_type=EVENT_USER_REPLIED,
                target_state="done",
            )
            log_actions([
                "append_step_input",
                "advance_step",
                "clear_checkpoint",
                "reset_task",
            ])
            return TransitionResult(
                should_continue_loop=False,
                reply="好的，任务已完成。",
            )

        checkpoint.save_checkpoint(state, source="transitions.collect_input_answer")
        log_transition(
            from_state="awaiting_user_input",
            event_type=EVENT_USER_REPLIED,
            target_state="running",
        )
        log_actions(["append_step_input", "advance_step", "save_checkpoint"])
        return TransitionResult(should_continue_loop=True)

    return TransitionResult(should_continue_loop=False)

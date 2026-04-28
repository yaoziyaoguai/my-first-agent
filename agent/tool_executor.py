

"""Tool execution helpers.

This module owns the execution of a single model-emitted tool_use block.
It does not own the agent loop; core.py remains responsible for orchestration.
"""

from __future__ import annotations

from typing import Any

from agent.checkpoint import save_checkpoint
from agent.conversation_events import append_tool_result, has_tool_result
from agent.display_events import (
    build_tool_awaiting_confirmation_event,
    build_tool_status_event,
    control_message,
    emit_display_event,
)
from agent.tool_registry import execute_tool, is_meta_tool
from agent.tool_registry import needs_tool_confirmation


AWAITING_USER = "__awaiting_user__"
FORCE_STOP = "__force_stop__"


def _classify_tool_outcome(result: str) -> tuple[str, str, str]:
    """根据工具返回字符串判定结果类别，返回 (status, display_event_type, status_text)。

    三类结果：
    - rejected_by_check: 工具的 pre/post hook 主动拒绝（「拒绝执行：...」），
      属于「安全检查通过 confirm 之后但工具内部仍拒绝」的情况；
      tool.rejected 显示事件 + 「已被工具内部安全检查拒绝。」status_text。
    - failed: 工具执行报错（如文件不存在、超时、HTTP 错误），见
      TOOL_FAILURE_PREFIXES；tool.failed + 「执行失败。」。
    - executed: 真实成功；tool.completed + 「执行完成。」。

    注意：rejection 和 failure 都不会让 Agent 在下一轮自动重试同一调用
    （response_handlers 已有「不要再次调用同一工具和同一输入」提示）。
    """
    if any(result.startswith(prefix) for prefix in TOOL_REJECTION_PREFIXES):
        return "rejected_by_check", "tool.rejected", "已被工具内部安全检查拒绝。"
    if any(result.startswith(prefix) for prefix in TOOL_FAILURE_PREFIXES):
        return "failed", "tool.failed", "执行失败。"
    return "executed", "tool.completed", "执行完成。"


def _describe_policy_denial(tool_name: str, tool_input: dict[str, Any]) -> str:
    """根据工具名 + 输入，生成具体的安全策略拒绝原因（中文，用户可读）。

    设计要点：
    - 这是 v0.2 RC smoke 暴露的真实问题——旧实现在所有 policy block 上
      都打印「该工具调用被安全策略阻止，未执行」这条**通用消息**，再被
      response_handlers 误归类为「用户连续拒绝多次操作，任务已停止」。
      用户根本不知道是路径敏感、还是文件类型敏感，更不知道是策略而非
      自己的拒绝触发了 stop。
    - 这里只生成消息文本，不改变 confirmation 返回值的契约（仍是
      "block" / True / False），也不放宽任何安全边界。
    - 不暴露 raw 路径全文以外的信息（不读文件内容、不打印环境变量）。
    """
    path = (tool_input or {}).get("path", "") or ""

    if tool_name in ("read_file", "read_file_lines"):
        # 用现成的安全工具反查具体原因。导入放在函数内，避免顶层循环依赖。
        from agent.security import is_sensitive_file

        if is_sensitive_file(path):
            return (
                f"[安全策略] 路径 '{path}' 被识别为敏感配置/密钥文件"
                "（如 .env / .pem / .key / 含 secret/credential/password/token），"
                "Runtime 默认禁止 Agent 读取以避免泄漏凭证；本工具调用未执行。"
            )

    # 其他 block 来源（未来扩展）：保留中性但区分于「用户拒绝」的措辞。
    return (
        f"[安全策略] 工具 {tool_name}({tool_input}) 被安全策略阻止，未执行。"
    )

TOOL_FAILURE_PREFIXES = (
    "错误：",
    "读取超时：",
    "HTTP 错误：",
    "读取失败：",
    "执行超时：",
    "[工具 ",
    "[安装失败]",
    "[更新失败]",
)

# v0.2 M7-A 真实修复：工具的 pre/post-execute 钩子（如 pre_write_check、
# check_shell_blacklist、_check_dangerous_content）拒绝执行时返回的字符串
# 都以「拒绝执行：」开头。旧实现没有把这条前缀纳入 TOOL_FAILURE_PREFIXES，
# 也没有独立分支，结果是：
#   - tool_executor 显示「执行完成。」，与「执行成功」无法区分
#   - tool_execution_log.status = "executed"，让审计/重试逻辑误以为成功
#   - 用户体验上：刚说「用户已确认，正在执行」，紧接着又说「执行完成」，
#     但实际上工具被安全检查拒绝了。
# 把「拒绝执行：」单独成一类 status："rejected_by_check"，并 emit 独立
# 的 tool.rejected 显示事件，让 UI / 审计 / 用户三方都能区分：
#   policy denial（confirmation == "block"，发生在执行前）
#   ↓ 不同
#   pre/post-execute 拒绝（执行入口已经过 confirm 才被工具内部检查拒绝）
#   ↓ 不同
#   tool failure（工具运行报错，如读不存在的文件）
TOOL_REJECTION_PREFIXES = ("拒绝执行：",)


def execute_single_tool(
    block: Any,
    *,
    state: Any,
    turn_state: Any,
    turn_context: dict[str, Any],
    messages: list[dict[str, Any]],
) -> str | None:
    """Execute or suspend a single tool_use block.

    Return values:
    - None: normal execution completed, caller may continue processing tools
    - AWAITING_USER: tool requires human confirmation; caller should stop loop
    - FORCE_STOP: tool was blocked or rejected enough times; caller should stop task

    **元工具特殊路径**：`mark_step_complete` 这类系统控制信号工具，只写 state.task.
    tool_execution_log（供 task_runtime 读分值判断），不写 messages——它们的
    tool_use 已经在 _serialize_assistant_content 里过滤掉了，自然也不能有
    tool_result（否则 tool_result 会"挂空"，下轮 API 调用 400）。
    """
    tool_use_id = block.id
    tool_name = block.name
    tool_input = block.input

    # 元工具分支：走独立路径，既不需要确认，也不需要在 messages 里配对。
    if is_meta_tool(tool_name):
        execution_log = state.task.tool_execution_log
        if tool_use_id in execution_log:
            existing = execution_log[tool_use_id]
            if existing.get("step_index") == state.task.current_step_index:
                # 同一步里重复收到同一个元工具 id，按幂等处理；messages 里本来就没有它。
                return None
            # 有些模型/网关会在不同 step 复用形如
            # toolu_functions.mark_step_complete:0 的工具 id。元工具完成判定按
            # step_index 隔离，不能让旧 step 的幂等记录挡住当前 step 的完成声明。
            # 否则 Runtime 会误判“当前 step 没完成”，进入 no_progress 循环，并让
            # 模型真实重复输出最后一条 Assistant 总结。
            tool_use_id = f"{tool_use_id}#step:{state.task.current_step_index}"

        state.task.tool_execution_log[tool_use_id] = {
            "tool": tool_name,
            "input": tool_input,
            "result": "",   # 元工具没有业务语义上的返回值
            "status": "meta_recorded",
            "step_index": state.task.current_step_index,
        }

        # request_user_input：执行期求助元工具。
        # 副作用：暂停 loop（切 status）+ 记录待回答的请求 + 清掉同轮可能写入的
        # mark_step_complete 残留分值（求助语义即"当前步骤未完成"，必须作废任何已写
        # 入的完成声明，否则用户回复后下一轮 _maybe_advance_step 会读到残留分值
        # 错误推进步骤）。这条清洗只针对**当前 step_index** 的记录，其他步骤的
        # 完成声明不动。
        #
        # 关键协议边界：虽然它来自模型 tool_use，但 request_user_input 是元工具控制
        # 信号，不是业务工具。元工具 tool_use 已在 response_handlers 序列化时剔除，
        # 所以后续用户回复必须走 user_replied/step_input，而不能生成 tool_result
        # placeholder。pending 里的 tool_use_id 只用于恢复/观测来源，不参与 Anthropic
        # API messages 配对；如果未来要改成可配对 tool_result 语义，需要单独设计
        # checkpoint migration、tool_use_id 配对和旧会话恢复。
        if tool_name == "request_user_input":
            current_idx = state.task.current_step_index
            stale_mark_ids = [
                tid
                for tid, entry in state.task.tool_execution_log.items()
                if entry.get("tool") == "mark_step_complete"
                and entry.get("step_index") == current_idx
            ]
            for tid in stale_mark_ids:
                state.task.tool_execution_log.pop(tid, None)

            state.task.pending_user_input_request = {
                # awaiting_kind 是 pending 内部的等待来源标记，不是新的 status。
                # 它随现有 task 快照进 checkpoint，但不改变 checkpoint 顶层结构。
                "awaiting_kind": "request_user_input",
                "question": tool_input.get("question", ""),
                "why_needed": tool_input.get("why_needed", ""),
                "options": tool_input.get("options") or [],
                "context": tool_input.get("context", ""),
                "tool_use_id": tool_use_id,
                "step_index": current_idx,
            }
            state.task.status = "awaiting_user_input"

        save_checkpoint(state)
        return None

    # Idempotency: never execute the same tool_use_id twice.
    execution_log = state.task.tool_execution_log
    if tool_use_id in execution_log:
        cached = execution_log[tool_use_id]["result"]
        emit = getattr(turn_state, "on_runtime_event", None)
        if emit is not None:
            # 重复 tool_use 的幂等处理属于工具执行边界：状态和 tool_result 配对逻辑不变，
            # 这里只把“已跳过”投影给 UI，避免继续依赖 stdout capture。不要把完整
            # checkpoint/debug/Anthropic messages 混进这个 RuntimeEvent。
            emit(control_message(f"[系统] 工具 {tool_name} 已执行过，跳过执行"))
        if not has_tool_result(messages, tool_use_id):
            append_tool_result(messages, tool_use_id, cached)
        return None

    confirmation = needs_tool_confirmation(tool_name, tool_input)

    if confirmation == "block":
        # v0.2 RC smoke 修复：把通用消息替换为具体拒绝原因，方便用户理解
        # 「不是我拒绝的，是策略拒绝的」。status 改为 'blocked_by_policy'，
        # 与未来真实 user_rejected 计数（如果引入）做语义区分。
        result = _describe_policy_denial(tool_name, tool_input)
        append_tool_result(messages, tool_use_id, result)
        state.task.tool_execution_log[tool_use_id] = {
            "tool": tool_name,
            "input": tool_input,
            "result": result,
            "status": "blocked_by_policy",
            "step_index": state.task.current_step_index,
        }
        # M7-B 真实修复：旧实现 block 分支不 emit 任何 display event，
        # 用户只看到下游 FORCE_STOP 的「具体拒绝原因见上方工具消息」，
        # 但「上方」其实空无一物。这里补一个 tool.rejected 事件，让用户
        # 在看到 FORCE_STOP 总结之前先看到具体「[安全策略] 已拒绝...」原因。
        # status_text 取拒绝消息首行（去掉 [安全策略] 前缀以避免重复），
        # 不会暴露任何文件内容（_describe_policy_denial 只看路径名）。
        first_line = result.splitlines()[0] if result else ""
        denial_summary = first_line.removeprefix("[安全策略] ").strip()
        emit_display_event(
            turn_state.on_display_event,
            build_tool_status_event(
                event_type="tool.rejected",
                tool_name=tool_name,
                tool_input=tool_input,
                status_text=f"被安全策略拒绝：{denial_summary}",
            ),
        )
        save_checkpoint(state)
        return FORCE_STOP

    if confirmation is True:
        state.task.pending_tool = {
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
        }
        state.task.status = "awaiting_tool_confirmation"
        save_checkpoint(state)
        # 工具确认是 Runtime 的 control plane 状态；DisplayEvent 只是 UI 投影。
        # 不把这段预览写进 conversation.messages，避免模型在下一轮把 UI 文案当事实。
        emit_display_event(
            turn_state.on_display_event,
            build_tool_awaiting_confirmation_event(
                tool_name=tool_name,
                tool_input=tool_input,
            ),
        )
        return AWAITING_USER

    emit_display_event(
        turn_state.on_display_event,
        build_tool_status_event(
            event_type="tool.executing",
            tool_name=tool_name,
            tool_input=tool_input,
            status_text="正在执行。",
        ),
    )
    result = execute_tool(tool_name, tool_input, context=turn_state.round_tool_traces)
    status, display_event_type, status_text = _classify_tool_outcome(result)
    if status in ("failed", "rejected_by_check"):
        # 失败 / 拒绝都不应让模型在下一轮重试同一调用；提示语言一致
        # （rejected 通常是路径/内容触犯安全检查，failure 是运行报错）。
        result = (
            f"{result}\n\n"
            "[系统提示] 该工具调用没有获得可用结果。"
            f"不要再次调用同一工具和同一输入：{tool_name}({tool_input})；"
            "请换用其他来源、使用已有信息继续，或明确说明当前来源不可用。"
        )

    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "input": tool_input,
        "result": result,
        "status": status,
        "step_index": state.task.current_step_index,
    }

    turn_state.round_tool_traces.append({
        "tool_use_id": tool_use_id,
        "tool": tool_name,
        "input": tool_input,
        "status": status,
        "result": result,
    })

    turn_context[tool_use_id] = result
    append_tool_result(messages, tool_use_id, result)
    emit_display_event(
        turn_state.on_display_event,
        build_tool_status_event(
            event_type=display_event_type,
            tool_name=tool_name,
            tool_input=tool_input,
            status_text=status_text,
        ),
    )
    save_checkpoint(state)
    return None


def execute_pending_tool(
    *,
    state: Any,
    turn_state: Any,
    messages: list[dict[str, Any]],
    pending: dict[str, Any],
) -> str:
    """用户确认后执行此前挂起的 pending tool。

    这个函数只负责「确认已到达后的执行」。确认 UI 已在 pending_tool 生成时通过
    DisplayEvent 发出；这里补执行中/完成事件，仍不让 TUI 读取 Runtime state。

    M7-A 文案修复：执行中提示从「用户已确认，正在执行」改为「已收到确认，
    开始执行（执行前/中可能仍被工具内部安全检查拒绝）」——更准确，避免
    用户先看到「正在执行」紧接着看到「拒绝执行：XXX」时困惑「到底是
    我的拒绝还是系统的拒绝」。
    """
    tool_use_id = pending["tool_use_id"]
    tool_name = pending["tool"]
    tool_input = pending["input"]

    emit_display_event(
        turn_state.on_display_event,
        build_tool_status_event(
            event_type="tool.executing",
            tool_name=tool_name,
            tool_input=tool_input,
            status_text="已收到确认，开始执行。",
        ),
    )
    result = execute_tool(tool_name, tool_input, context=turn_state.round_tool_traces)
    status, display_event_type, status_text = _classify_tool_outcome(result)
    if status in ("failed", "rejected_by_check"):
        result = (
            f"{result}\n\n"
            "[系统提示] 该工具调用没有获得可用结果。"
            f"不要再次调用同一工具和同一输入：{tool_name}({tool_input})；"
            "请换用其他来源、使用已有信息继续，或明确说明当前来源不可用。"
        )

    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "input": tool_input,
        "result": result,
        "status": status,
        "step_index": state.task.current_step_index,
    }

    turn_state.round_tool_traces.append({
        "tool_use_id": tool_use_id,
        "tool": tool_name,
        "input": tool_input,
        "status": status,
        "result": result,
    })

    append_tool_result(messages, tool_use_id, result)
    emit_display_event(
        turn_state.on_display_event,
        build_tool_status_event(
            event_type=display_event_type,
            tool_name=tool_name,
            tool_input=tool_input,
            status_text=status_text,
        ),
    )
    return result

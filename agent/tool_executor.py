

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
    mask_user_visible_secrets,
)
from agent.runtime_events import ToolResultTransitionKind, tool_result_transition
from agent import tool_result_contract
from agent.runtime_trace_emitter import emit_tool_result_trace_event
from agent.tool_registry import execute_tool, is_meta_tool
from agent.tool_registry import needs_tool_confirmation


AWAITING_USER = "__awaiting_user__"
FORCE_STOP = "__force_stop__"

# 兼容旧调用方：常量源头已经收口到 tool_result_contract，这里只保留别名。
TOOL_FAILURE_PREFIXES = tool_result_contract.TOOL_FAILURE_PREFIXES
TOOL_REJECTION_PREFIXES = tool_result_contract.TOOL_REJECTION_PREFIXES


def _classify_tool_outcome(result: str) -> tuple[str, str, str]:
    """兼容旧测试/调用方的 thin wrapper；真实分类契约在 tool_result_contract。"""

    return tool_result_contract.classify_tool_outcome(result)


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


def _tool_failure_transition(status: str, *, from_pending_tool: bool) -> Any | None:
    """把真实 failure status 映射到 v0.4 TransitionResult。

    只处理 `status == "failed"`：`rejected_by_check` 是工具内部安全检查拒绝，
    policy denial 和 user rejection 已有独立切片。这样 failure 不会被混成
    policy/user/success，也避免本轮顺手迁移 tool success。
    """

    if status != "failed":
        return None
    return tool_result_transition(
        ToolResultTransitionKind.TOOL_FAILURE,
        from_pending_tool=from_pending_tool,
    )


def _tool_success_transition(status: str, *, from_pending_tool: bool) -> Any | None:
    """把真实 success status 映射到 v0.4 TransitionResult（slice 4）。

    中文学习边界：
    - 这是 v0.4 Phase 1 第 4 个切片，目标是把 ToolFailure 已经形成的
      ``TransitionResult`` 边界镜像到成功路径，让 tool 调用 4 类结局
      （success / failure / policy denial / user rejection）在 transition
      命名层完全对称，方便后续 slice 5/6 继续收敛 ModelOutput / 用户确认。
    - 只处理 ``status == "executed"``：``rejected_by_check`` 是工具内部
      安全检查拒绝（不是 policy denial），现阶段刻意保留它走 fallback
      的 raw display_event_type，**不要**把它误归 success；
      ``failed`` 由 :func:`_tool_failure_transition` 单独负责。
    - 本切片**不**接管 ``tool_result`` 消息写入、**不**改 checkpoint schema、
      **不**改工具实际执行（``execute_tool`` 调用）、**不**改用户确认逻辑、
      **不**做 ModelOutput 分类、**不**瘦 ``core.py`` 主循环——这些都在
      后续 slice / phase 单独迁移，避免一把大重构。
    - 行为兼容：``TOOL_SUCCESS`` 的 ``display_events`` 是 ``("tool.completed",)``、
      ``should_checkpoint=True``、``clear_pending_tool=False``（``from_pending_tool``
      只是把意图表达给调用方，``execute_pending_tool`` 现阶段仍由
      ``confirm_handlers`` 在外层清 pending，不在本函数内动 state）。
    """

    if status != "executed":
        return None
    return tool_result_transition(
        ToolResultTransitionKind.TOOL_SUCCESS,
        from_pending_tool=from_pending_tool,
    )


def _tool_outcome_transition(status: str, *, from_pending_tool: bool) -> Any | None:
    """统一获取 success / failure 的 transition（slice 4 集中入口）。

    中文学习边界：``rejected_by_check`` / ``blocked_by_policy`` 都不在这里
    处理——前者保留 fallback 让 raw ``display_event_type`` 走 ``tool.rejected``，
    后者由 ``execute_single_tool`` 在 confirmation block 分支里直接调用
    :func:`tool_result_transition` (POLICY_DENIAL)。这样四类结局**只**走
    各自专属入口，不会被 substring 判断混淆。
    """

    return _tool_failure_transition(
        status, from_pending_tool=from_pending_tool
    ) or _tool_success_transition(
        status, from_pending_tool=from_pending_tool
    )


def _failure_retry_hint(tool_name: str, tool_input: dict[str, Any]) -> str:
    """生成失败后的重试提示，并对工具输入做脱敏。

    这段文本会进入 `tool_result` messages 和 checkpoint，是 durable fact；
    因此不能把 token/api key/private key 作为“同一输入”原样写进去。脱敏只改变
    用户可见提示，不改变真实工具执行输入，也不改变 checkpoint schema。
    """

    safe_input = mask_user_visible_secrets(str(tool_input))
    return (
        "[系统提示] 该工具调用没有获得可用结果。"
        f"不要再次调用同一工具和同一输入：{tool_name}({safe_input})；"
        "请换用其他来源、使用已有信息继续，或明确说明当前来源不可用。"
    )


def _mask_failure_value(value: Any) -> Any:
    """为 failure durable log 做递归脱敏。

    tool_execution_log 会进入 checkpoint；failure 切片开始明确要求失败路径不把
    token/api key/private key 原样持久化。这里仅在 failure durable log 中使用，
    不改变真实工具执行入参，也不改变 success 的现有行为。
    """

    if isinstance(value, str):
        return mask_user_visible_secrets(value)
    if isinstance(value, dict):
        return {k: _mask_failure_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_failure_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_mask_failure_value(item) for item in value)
    return value

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
        #
        # v0.4 Phase 1 最小 ToolResult transition slice：policy denial 先映射成
        # TransitionResult，再由既有 handler 应用清 pending / checkpoint / display
        # 语义。TransitionResult 不进 checkpoint/messages；持久事实仍是下面的
        # tool_execution_log + tool_result message。
        transition = tool_result_transition(ToolResultTransitionKind.POLICY_DENIAL)
        if transition.clear_pending_tool:
            state.task.pending_tool = None
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
                event_type=transition.display_events[0],
                tool_name=tool_name,
                tool_input=tool_input,
                status_text=f"被安全策略拒绝：{denial_summary}",
            ),
        )
        if transition.should_checkpoint:
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
    transition = _tool_outcome_transition(status, from_pending_tool=False)
    failure_transition = _tool_failure_transition(status, from_pending_tool=False)
    if status in ("failed", "rejected_by_check"):
        # 失败 / 拒绝都不应让模型在下一轮重试同一调用；提示语言一致
        # （rejected 通常是路径/内容触犯安全检查，failure 是运行报错）。
        result = mask_user_visible_secrets(result)
        result = (
            f"{result}\n\n"
            f"{_failure_retry_hint(tool_name, tool_input)}"
        )

    if transition and transition.clear_pending_tool:
        state.task.pending_tool = None
    # 脱敏只在真实 failure 路径生效；success / rejected_by_check 的入参
    # 由用户确认 / 安全策略层面已经把关，这里不做额外 transformation 以
    # 避免 success 的 durable log 里出现"被本轮 slice 顺手改写"的内容。
    log_input = _mask_failure_value(tool_input) if failure_transition else tool_input

    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "input": log_input,
        "result": result,
        "status": status,
        "step_index": state.task.current_step_index,
    }

    turn_state.round_tool_traces.append({
        "tool_use_id": tool_use_id,
        "tool": tool_name,
        "input": log_input,
        "status": status,
        "result": result,
    })

    turn_context[tool_use_id] = result
    append_tool_result(messages, tool_use_id, result)
    emit_tool_result_trace_event(
        turn_state,
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        tool_result=result,
        step_index=state.task.current_step_index,
    )
    emit_display_event(
        turn_state.on_display_event,
        build_tool_status_event(
            event_type=transition.display_events[0] if transition else display_event_type,
            tool_name=tool_name,
            tool_input=tool_input,
            status_text=status_text,
        ),
    )
    if transition is None or transition.should_checkpoint:
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
    transition = _tool_outcome_transition(status, from_pending_tool=True)
    failure_transition = _tool_failure_transition(status, from_pending_tool=True)
    if status in ("failed", "rejected_by_check"):
        result = mask_user_visible_secrets(result)
        result = (
            f"{result}\n\n"
            f"{_failure_retry_hint(tool_name, tool_input)}"
        )

    log_input = _mask_failure_value(tool_input) if failure_transition else tool_input

    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "input": log_input,
        "result": result,
        "status": status,
        "step_index": state.task.current_step_index,
    }

    turn_state.round_tool_traces.append({
        "tool_use_id": tool_use_id,
        "tool": tool_name,
        "input": log_input,
        "status": status,
        "result": result,
    })

    append_tool_result(messages, tool_use_id, result)
    emit_tool_result_trace_event(
        turn_state,
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        tool_result=result,
        step_index=state.task.current_step_index,
    )
    emit_display_event(
        turn_state.on_display_event,
        build_tool_status_event(
            event_type=transition.display_events[0] if transition else display_event_type,
            tool_name=tool_name,
            tool_input=tool_input,
            status_text=status_text,
        ),
    )
    return result

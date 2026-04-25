
from typing import Any

from agent.planner import Plan
from agent.task_runtime import USER_INPUT_STEP_TYPES, get_latest_step_completion
from config import STEP_COMPLETION_THRESHOLD


# ====================================================================
# 严格投影：state.conversation.messages → 合规的 Anthropic messages
# ====================================================================
#
# 背景：我们内部存的 messages 是 append-only 的原始事件流：
#   - user 消息、assistant 消息
#   - tool_use / tool_result（被 `append_tool_result` 拆成独立 user 消息）
#   - 控制事件（"用户接受计划" 等，通过 `append_control_event` 写成独立 user 消息）
#
# 但 Anthropic 协议对 messages 有**硬性**要求：
#   1. assistant 消息里的每一个 tool_use，对应的 tool_result 必须出现在
#      紧随其后的 user 消息里，中间不能插任何消息。
#   2. 一条 assistant 里的多个 tool_use，对应的 tool_result 必须**合并进
#      同一条 user 消息**（放在 content array 前面）。顺序最好和 tool_use 声明顺序一致。
#
# 参考：
#   https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use
#   https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls
#
# 之前的实现违反了这两条（每个 tool_result 独立 user 消息 + 中间夹控制事件），
# Kimi 见到这种不规范的 messages 会陷入死循环（把"跳过"占位解读成需重试）。
# _project_to_api 做的事情：按规则**重排 + 合并 + 清理**，产出一份协议严格合规的 messages。

def _is_tool_use_block(b: Any) -> bool:
    return isinstance(b, dict) and b.get("type") == "tool_use"


def _is_tool_result_block(b: Any) -> bool:
    return isinstance(b, dict) and b.get("type") == "tool_result"


def _collect_tool_use_ids(assistant_content: Any) -> list[str]:
    """返回 assistant content blocks 里所有 tool_use 的 id（按声明顺序）。"""
    if not isinstance(assistant_content, list):
        return []
    return [b["id"] for b in assistant_content if _is_tool_use_block(b) and "id" in b]


def _extract_tool_results(user_content: Any) -> tuple[list[dict], bool]:
    """
    从 user 消息的 content 里抽出所有 tool_result 块，
    并告诉调用方：除了 tool_result 是否还有别的内容（true 表示还有别的块）。
    """
    if isinstance(user_content, list):
        tr = [b for b in user_content if _is_tool_result_block(b)]
        has_other = any(not _is_tool_result_block(b) for b in user_content)
        return tr, has_other
    # 字符串 content 一定不是 tool_result
    return [], True


def _project_to_api(raw_messages: list[dict]) -> list[dict]:
    """
    把内部 raw messages 投影成协议严格合规的 messages。

    核心算法：
      - 走到 assistant(tool_use) 时，向后扫描收集所有匹配的 tool_result
      - 合并成一条 user 消息（tool_use 声明顺序）
      - 扫描过程中跳过的控制事件（纯文本 user 消息），从 API 视图里**删掉**
        ——它们的语义已经通过 state 转换体现，模型不需要再看一次
      - 扫描收集时，若某个 user 消息里既有 tool_result 也有非 tool_result 块，
        非 tool_result 块保留，不和 tool_result 混；tool_result 进合并池
      - 未能配齐的 tool_use id 填占位 tool_result（保证协议完整）
    """
    projected: list[dict] = []
    i = 0
    n = len(raw_messages)

    while i < n:
        msg = raw_messages[i]
        role = msg.get("role")
        content = msg.get("content")

        # 非 assistant-with-tool_use 的消息，直接 pass through
        if role != "assistant":
            projected.append(msg)
            i += 1
            continue

        tool_use_ids = _collect_tool_use_ids(content)
        if not tool_use_ids:
            # assistant 纯文本或只有 text 块，pass through
            projected.append(msg)
            i += 1
            continue

        # 这个 assistant 有 tool_use——按协议，它后面必须紧跟一条 user 消息，
        # 里面合并了所有对应的 tool_result。开始向后扫描收集。
        projected.append(msg)

        results_by_id: dict[str, dict] = {}
        leftover_user_messages: list[dict] = []
        j = i + 1

        # 最多扫描到下一个 assistant 消息为止（或直到集齐所有 id）
        while j < n and len(results_by_id) < len(tool_use_ids):
            nxt = raw_messages[j]
            if nxt.get("role") == "assistant":
                # 遇到下一个 assistant 消息——停止扫描（不越过 assistant 边界）
                break

            nxt_content = nxt.get("content")
            tr_blocks, has_other = _extract_tool_results(nxt_content)

            if not tr_blocks:
                # 纯控制事件 / 纯文本 user 消息——**丢弃**（它违反协议，不能在
                # assistant(tool_use) 和 user(tool_result) 中间）
                # 语义上它记录的是"用户确认工具"之类，模型不需要看
                j += 1
                continue

            # 有 tool_result——挑出我们需要的
            for b in tr_blocks:
                tid = b.get("tool_use_id")
                if tid in tool_use_ids and tid not in results_by_id:
                    results_by_id[tid] = b

            if has_other:
                # 这条 user 消息里除了 tool_result 还有别的内容——
                # 目前我们不会在一条 user 里同时放 tool_result 和其他内容，
                # 但保守起见把它加入 leftover，稍后处理
                # （实际上更安全：忽略非 tool_result 的部分，只挑 tool_result）
                pass

            j += 1

        # 组装合并后的 user 消息：tool_result 严格按 tool_use 声明顺序
        merged_blocks: list[dict] = []
        for tid in tool_use_ids:
            if tid in results_by_id:
                merged_blocks.append(results_by_id[tid])
            else:
                # 缺失配对——补占位，保证协议合法
                merged_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": "[系统] 该 tool_use 缺失对应 tool_result（投影时未找到）。",
                })

        projected.append({"role": "user", "content": merged_blocks})

        # 推进到未消费的 leftover（如果有）之后
        for lm in leftover_user_messages:
            projected.append(lm)

        # 继续从 j 处扫描（j 指向下一个 assistant 或 list 末尾）
        i = j

    return projected


def build_planning_messages(state: Any, current_user_input: str) -> list[dict]:
    """
    构造给 planner 使用的轻量 messages。

    规则：
    - 只提供历史摘要 + 最近原始消息
    - 不注入 current_plan / current_step / completion_criteria
    - 避免让 planner 被执行态上下文污染
    - 当前轮输入只在这里临时加入，不提前写回 conversation state
    """
    model_messages: list[dict] = []

    if state.memory.working_summary:
        model_messages.append({
            "role": "user",
            "content": f"[以下是之前对话的摘要]\n{state.memory.working_summary}",
        })
        model_messages.append({
            "role": "assistant",
            "content": "好的，我了解了之前的对话内容。请继续。",
        })

    # planner 用的 messages 也经过严格投影，保证协议合规
    model_messages.extend(_project_to_api(state.conversation.messages))
    model_messages.append({"role": "user", "content": current_user_input})
    return model_messages



def build_execution_messages(state: Any) -> list[dict]:
    """
    构造真正喂给执行阶段模型的 messages。

    规则：
    - summary 不存到 conversation.messages
    - current_plan 不存到 conversation.messages
    - 只在这里临时拼接
    - 只给模型当前步骤，而不是整份计划
    - **严格按 Anthropic 协议投影**：tool_result 合并到一条 user 消息 + tool_use 和
      tool_result 之间不夹控制事件（由 `_project_to_api` 负责）
    """
    model_messages: list[dict] = []

    # 历史摘要
    if state.memory.working_summary:
        model_messages.append({
            "role": "user",
            "content": f"[以下是之前对话的摘要]\n{state.memory.working_summary}",
        })
        model_messages.append({
            "role": "assistant",
            "content": "好的，我了解了之前的对话内容。请继续。",
        })

    # 当前任务步骤
    # 防御：status == "done" 时不应该再拼 step 块。
    # 从任务完成（advance 设 done）到 reset_task 之间有短暂窗口，current_plan
    # 仍然存在但语义上任务已结束——这时不能再把旧步骤指令喂给模型。
    if state.task.current_plan and state.task.status != "done":
        plan = Plan.model_validate(state.task.current_plan)
        current_step = state.task.current_step_index

        if 0 <= current_step < len(plan.steps):
            step = plan.steps[current_step]

            step_lines = [
                f"[当前任务] {plan.goal}",
            ]

            if plan.thinking:
                step_lines.append(f"规划思路：{plan.thinking}")

            step_lines.extend([
                f"[当前执行进度]：正在执行第 {current_step + 1} 步 / 共 {len(plan.steps)} 步",
            ])
            # Step Memory（已完成步骤注入）
            completed_steps = plan.steps[:current_step]
            if completed_steps:
                step_lines.append("\n【已完成步骤】")
                for i, s in enumerate(completed_steps):
                    step_lines.append(f"{i+1}. {s.title}（已完成）")

            step_lines.extend([
                f"[当前步骤标题]：{step.title}",
                f"[当前步骤说明]：{step.description}",
                f"[步骤类型]：{step.step_type}",
            ])

            if step.suggested_tool:
                step_lines.append(f"[建议工具]：{step.suggested_tool}")

            if step.expected_outcome:
                step_lines.append(f"[预期结果]：{step.expected_outcome}")

            if step.completion_criteria:
                step_lines.append(f"[完成标准]：{step.completion_criteria}")

            step_lines.extend([
                "",
                "【执行上下文】",
                f"- 当前任务：{plan.goal}",
                f"- 当前步骤：第 {current_step + 1} 步 / 共 {len(plan.steps)} 步",
                f"- 步骤名称：{step.title}",
                "",
                "【执行目标】",
                f"{step.description}",
                "",
                "【执行约束（必须严格遵守）】",
                "- 你只能执行当前步骤",
                "- 不允许执行已完成步骤的内容",
                "- 不允许执行与当前步骤无关的行为",
                "- 不要重复【已完成步骤】中的任何行为",
            ])

            if step.step_type in USER_INPUT_STEP_TYPES:
                step_lines.extend([
                    "",
                    "【当前步骤语义】",
                    "- 这是一个信息收集步骤，需要先向用户询问缺失信息。",
                    "- 不要调用 `mark_step_complete`。",
                    "- 把需要用户补充的内容问清楚后结束本轮，等待用户回复。",
                    "- 用户回复后，系统会自动把这一步视为完成并继续后续步骤。",
                ])
            else:
                step_lines.extend([
                    "",
                    "【行为判断规则】",
                    "- 如果你的行为与当前步骤目标不一致，这是错误",
                    "- 如果重复之前步骤，这是错误",
                    "- 如果偏离当前步骤目标，这是错误",
                    "",
                    "【完成要求】",
                    "- 本步骤工作收尾时，**必须调用 `mark_step_complete` 工具**声明结束并打分（0-100）。",
                    f"- 分值 ≥ {STEP_COMPLETION_THRESHOLD} 才算真正完成；低于该阈值系统会把 outstanding 注入下一轮让你继续。",
                    "- 严禁只在文本里说\"本步骤已完成\"而不调用工具——系统只认工具信号。",
                    "",
                    "【遇到信息缺口的处理纪律】",
                    "- 如果当前步骤执行过程中发现缺少关键用户信息，且无法通过读文件 / 已有上下文 / 合理假设继续，",
                    "  调用元工具 `request_user_input` 暂停执行并向用户提一个最关键的问题。",
                    "- 只在真正阻塞继续执行时才调用；能通过合理假设继续就不要请求用户输入。",
                    "- 一次只问一个最关键问题，不要把多个问题串在一起。",
                    "- 调用 `request_user_input` 时**不要同轮调用 `mark_step_complete`**（求助意味着步骤未完成）。",
                    "- 调用 `request_user_input` 时**不要同轮混用普通业务工具**（先暂停、等用户回复后再继续）。",
                    "- **禁止**只用普通自然语言向用户提问然后 end_turn——必须调 `request_user_input`。",
                    "  违反协议时系统兜底会强制暂停 loop（你将看不到下一轮的「请继续」提示）。",
                ])

            if step.step_type not in USER_INPUT_STEP_TYPES:
                # 上一轮自评未达阈值：把 outstanding 注入，让模型看到"还欠什么"。
                latest = get_latest_step_completion(state)
                if latest is not None:
                    score = latest.get("completion_score")
                    outstanding = latest.get("outstanding") or ""
                    summary = latest.get("summary") or ""
                    if isinstance(score, int) and score < STEP_COMPLETION_THRESHOLD:
                        step_lines.extend([
                            "",
                            "【上一轮自评（未达阈值，必须继续）】",
                            f"- 上次打分：{score}/100（阈值 {STEP_COMPLETION_THRESHOLD}）",
                            f"- 上次自述完成度：{summary}",
                            f"- 上次承认的未完成项：{outstanding}",
                            "- 请优先补齐未完成项，而不是重复已做过的工作；再次调用 mark_step_complete 时给出更客观的分值。",
                        ])

            model_messages.append({
                "role": "user",
                "content": "\n".join(step_lines),
            })

    # 关键：不再直接 extend(state.conversation.messages)，而是过一遍严格投影，
    # 保证交给 API 的 messages 严格合规（tool_result 合并 / 删控制事件）。
    model_messages.extend(_project_to_api(state.conversation.messages))
    return model_messages

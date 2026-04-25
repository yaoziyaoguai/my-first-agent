"""元工具：系统控制信号工具。

元工具和业务工具的区别：
- 业务工具（read_file / run_shell 等）：模型用它们**完成用户任务**，调用痕迹应该保留
  在对话上下文里，供模型之后参考。
- 元工具（mark_step_complete）：模型用它**和系统通信**——声明完成、请求中断、
  报告进度等。这些是**协议层信号**，不是对话内容。它们的调用痕迹**不应当**
  留在对话上下文里，否则模型下次看到自己之前的元工具调用会产生语义混乱。

元工具的执行路径：
- tool_registry 标记 meta_tool=True
- tool_executor 检测到 meta_tool 走特殊路径：写入 state.task.tool_execution_log，
  但不 append_tool_result 到 messages
- response_handlers._serialize_assistant_content 在序列化 assistant content 时
  过滤掉 meta_tool 的 tool_use 块，不让它进 state.conversation.messages
- 最终结果：messages 里看不到元工具，模型在后续轮次中也看不到
  ——所有信息只在 state 层（by design）
"""

from __future__ import annotations

from agent.tool_registry import register_tool


_MARK_STEP_COMPLETE_DESCRIPTION = """当你判断本步骤的工作已经收尾（无论是完全达成还是部分达成）时，**必须调用此工具**声明结束。

请**严格、客观**地对本步骤完成度打分（integer，0–100）：
  - 90–100：完全达成步骤目标，关键产出齐全
  - 70–89：主体完成，有可见的小遗漏或次要未覆盖点
  - 40–69：部分完成，关键产出缺失或不充分
  - 0–39：基本未能推进（工具持续失败 / 权限不足 / 输入信息不够等）

**请不要虚报分值**：
  - 系统会依据分值决定是否**真的**推进到下一步
  - 如果分值过低，系统会把你填的 outstanding 注入下一轮请求，让你继续完成
  - 虚报高分不会让任务实际完成，只会让用户看到错误的"完成" 状态

三个字段都必须填：
  - completion_score：上述评分
  - summary：本步骤**实际做了什么**、产出是什么（客观事实，2-4 句话）
  - outstanding：若评分 < 100，列出**还没做到什么**；若评分 = 100 则填"无"
"""


@register_tool(
    name="mark_step_complete",
    description=_MARK_STEP_COMPLETE_DESCRIPTION,
    parameters={
        "completion_score": {
            "type": "integer",
            "description": "本步骤完成度评分（0-100 整数）",
        },
        "summary": {
            "type": "string",
            "description": "本步骤实际做了什么、产出是什么（客观事实，2-4 句话）",
        },
        "outstanding": {
            "type": "string",
            "description": "若评分 < 100，列出还没做到什么；若评分 = 100 则填'无'",
        },
    },
    confirmation="never",   # 元工具由系统处理，不需要用户确认
    meta_tool=True,         # 关键：走特殊执行路径，不写 messages
)
def mark_step_complete(completion_score: int, summary: str, outstanding: str) -> str:
    """
    工具函数体本身什么都不做——tool_executor 检测到 meta_tool=True 会走
    特殊路径，根本不会调用这个函数。这里留空是为了符合 register_tool 签名。

    实际处理在 tool_executor.execute_single_tool 里：把 completion_score /
    summary / outstanding 三个字段写入 state.task.tool_execution_log，
    供 task_runtime.is_current_step_completed 读取判断。
    """
    return ""

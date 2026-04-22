import json
import uuid
from datetime import datetime
from config import PROJECT_DIR
from agent.logger import log_event, make_serializable

CHECKPOINT_PATH = PROJECT_DIR / "memory" / "checkpoint.json"

MAX_RESULT_LENGTH = 2000  # checkpoint 中 tool_result 的截断长度


def _now_iso() -> str:
    """返回当前时间的 ISO 格式字符串"""
    return datetime.now().isoformat()


def _truncate_messages_for_checkpoint(messages):
    """截断 messages 中的大块内容，但保留'已完成'的语义"""
    serializable = make_serializable(messages)
    truncated = []
    for msg in serializable:
        if isinstance(msg.get("content"), list):
            new_content = []
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content", "")
                    if isinstance(content, str) and len(content) > MAX_RESULT_LENGTH:
                        block = dict(block)
                        # 关键：让模型知道这一步已经成功完成了
                        block["content"] = (
                            f"[此步骤已成功完成，结果已省略]\n"
                            f"原始输出前 {MAX_RESULT_LENGTH} 字符：\n"
                            f"{content[:MAX_RESULT_LENGTH]}"
                        )
                    new_content.append(block)
                else:
                    new_content.append(block)
            truncated.append({"role": msg["role"], "content": new_content})
        else:
            truncated.append(msg)
    return truncated


def _build_checkpoint_from_state(state):
    """
    按新的 state 世界观构造 checkpoint 数据。

    当前只保存最小必要子集：
    - task：当前任务目标 / 状态 / 当前步骤 / 当前计划
    - memory：working_summary
    - conversation：messages
    """
    return {
        "version": 2,
        "meta": {
            "session_id": state.memory.session_id,
            "created_at": _now_iso(),
            "interrupted_at": _now_iso(),
        },
        "task": {
            "user_goal": state.task.user_goal,
            "status": state.task.status,
            "current_step_index": state.task.current_step_index,
            "current_plan": make_serializable(state.task.current_plan),
        },
        "memory": {
            "working_summary": state.memory.working_summary,
        },
        "conversation": {
            "messages": _truncate_messages_for_checkpoint(
                state.conversation.messages
            ),
        },
    }


def save_checkpoint(original_input, plan, messages):
    """保存断点（计划 + 截断后的消息历史）"""
    checkpoint = {
        "task_id": str(uuid.uuid4())[:8],
        "original_input": original_input,
        "plan": plan,
        "messages": _truncate_messages_for_checkpoint(messages),
        "created_at": datetime.now().isoformat(),
        "interrupted_at": datetime.now().isoformat(),
    }
    try:
        CHECKPOINT_PATH.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        log_event("checkpoint_saved", {
            "task_id": checkpoint["task_id"],
            "steps": len(plan.get("steps", [])),
            "message_count": len(messages),
        })
    except Exception as e:
        log_event("checkpoint_save_error", {"error": str(e)})


def save_checkpoint_from_state(state):
    """按新的 state 结构保存断点。"""
    checkpoint = _build_checkpoint_from_state(state)
    try:
        CHECKPOINT_PATH.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log_event("checkpoint_saved_v2", {
            "version": checkpoint["version"],
            "task_status": checkpoint["task"]["status"],
            "current_step_index": checkpoint["task"]["current_step_index"],
            "message_count": len(checkpoint["conversation"]["messages"]),
        })
    except Exception as e:
        log_event("checkpoint_save_error_v2", {"error": str(e)})


def load_checkpoint():
    """加载未完成的断点"""
    if not CHECKPOINT_PATH.exists():
        return None
    try:
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


# 从 v2 checkpoint 恢复到当前 state
def load_checkpoint_to_state(state):
    """
    从 v2 checkpoint 恢复到当前 state。
    - 只处理 version == 2 的新结构
    - 不支持旧 checkpoint 自动迁移（先简单处理）
    """
    checkpoint = load_checkpoint()
    if not checkpoint:
        return False

    if checkpoint.get("version") != 2:
        # 暂不处理旧版本
        return False

    try:
        # 恢复 task
        task_data = checkpoint.get("task", {})
        state.task.user_goal = task_data.get("user_goal")
        state.task.status = task_data.get("status", "idle")
        state.task.current_step_index = task_data.get("current_step_index", 0)
        state.task.current_plan = task_data.get("current_plan")

        # 恢复 memory
        memory_data = checkpoint.get("memory", {})
        state.memory.working_summary = memory_data.get("working_summary")

        # 恢复 conversation
        conv_data = checkpoint.get("conversation", {})
        state.conversation.messages = conv_data.get("messages", [])

        log_event("checkpoint_loaded_v2", {
            "task_status": state.task.status,
            "current_step_index": state.task.current_step_index,
            "message_count": len(state.conversation.messages),
        })

        return True

    except Exception as e:
        log_event("checkpoint_load_error_v2", {"error": str(e)})
        return False


def clear_checkpoint():
    """任务完成后清除断点"""
    if CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()
        log_event("checkpoint_cleared", {})


def format_resume_context(checkpoint):
    """把断点信息格式化成注入上下文的文本"""
    plan = checkpoint["plan"]
    lines = [
        "[恢复任务] 你之前在执行一个任务但被中断了。",
        f"原始请求：{checkpoint['original_input']}",
        f"任务目标：{plan['goal']}",
        "",
        "计划步骤："
    ]
    for step in plan["steps"]:
        lines.append(f"  {step['id']}. {step['action']}")

    lines.append("\n之前的对话历史已恢复。请根据已有的上下文判断哪些步骤已经完成，从未完成的步骤继续执行。")
    lines.append("完成所有步骤后停止，输出最终结果。")
    return "\n".join(lines)

import json
import uuid
from datetime import datetime
from config import PROJECT_DIR
from agent.logger import log_event, make_serializable

CHECKPOINT_PATH = PROJECT_DIR / "memory" / "checkpoint.json"

MAX_RESULT_LENGTH = 2000  # checkpoint 中 tool_result 的截断长度


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


def load_checkpoint():
    """加载未完成的断点"""
    if not CHECKPOINT_PATH.exists():
        return None
    try:
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


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
    lines.append("完成所有步骤后停止，输出最终结果。")
    return "\n".join(lines)

import json
from datetime import datetime
from config import PROJECT_DIR

CHECKPOINT_PATH = PROJECT_DIR / "memory" / "checkpoint.json"

MAX_RESULT_LENGTH = 2000  # checkpoint 中 tool_result 的截断长度


def _now_iso() -> str:
    """返回当前时间的 ISO 格式字符串"""
    return datetime.now().isoformat()


def _truncate_messages_for_checkpoint(messages):
    """截断 messages 中过大的 tool_result 内容，只做体积控制，不做语义加工。"""
    serializable = messages
    truncated = []
    for msg in serializable:
        if isinstance(msg.get("content"), list):
            new_content = []
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content", "")
                    if isinstance(content, str) and len(content) > MAX_RESULT_LENGTH:
                        block = dict(block)
                        block["content"] = content[:MAX_RESULT_LENGTH]
                    new_content.append(block)
                else:
                    new_content.append(block)
            truncated.append({"role": msg["role"], "content": new_content})
        else:
            truncated.append(msg)
    return truncated


def _build_checkpoint_from_state(state):
    """
    按当前 state 构造 checkpoint 数据。

    当前只保存最小必要子集：
    - task：当前任务目标 / 状态 / 当前步骤 / 当前计划
    - memory：working_summary
    - conversation：messages
    """
    return {
        "meta": {
            "session_id": state.memory.session_id,
            "created_at": _now_iso(),
            "interrupted_at": _now_iso(),
        },
        "task": {
            "user_goal": state.task.user_goal,
            "status": state.task.status,
            "current_step_index": state.task.current_step_index,
            "current_plan": state.task.current_plan,
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


def save_checkpoint(state):
    """按当前 state 结构保存断点。"""
    checkpoint = _build_checkpoint_from_state(state)
    try:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_PATH.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_checkpoint():
    """加载未完成的断点"""
    if not CHECKPOINT_PATH.exists():
        return None
    try:
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


# 从 checkpoint 恢复到当前 state
def load_checkpoint_to_state(state):
    """
    从 checkpoint 恢复到当前 state。
    """
    checkpoint = load_checkpoint()
    if not checkpoint:
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
        state.conversation.messages = conv_data.get("messages", []) or []

        return True

    except Exception:
        return False


def clear_checkpoint():
    """任务完成后清除断点"""
    if CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()

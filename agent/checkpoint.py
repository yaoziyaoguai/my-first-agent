import json
from datetime import datetime
from config import PROJECT_DIR

CHECKPOINT_PATH = PROJECT_DIR / "memory" / "checkpoint.json"

MAX_RESULT_LENGTH = 2000  # checkpoint 中 tool_result 的截断长度


def _now_iso() -> str:
    """返回当前时间的 ISO 格式字符串"""
    return datetime.now().isoformat()


def _truncate_messages_for_checkpoint(messages):
    """截断 messages 中过大的 tool_result 内容，并保证整体可 JSON 序列化"""
    truncated = []

    def _safe(obj):
        """确保对象可序列化，不可序列化则转为字符串"""
        try:
            json.dumps(obj)
            return obj
        except Exception:
            return str(obj)

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        # Anthropic content block（list 结构）
        if isinstance(content, list):
            new_content = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_result":
                        block = dict(block)
                        c = block.get("content", "")
                        if isinstance(c, str) and len(c) > MAX_RESULT_LENGTH:
                            block["content"] = c[:MAX_RESULT_LENGTH]
                        else:
                            block["content"] = _safe(c)
                        new_content.append(block)
                    else:
                        new_content.append(_safe(block))
                else:
                    new_content.append(_safe(block))
            truncated.append({"role": role, "content": new_content})

        else:
            truncated.append({"role": role, "content": _safe(content)})

    return truncated


def _copy_state_dict(obj) -> dict:
    """
    复制 dataclass / 普通对象的浅层状态字典。

    目的：
    - 避免手工挑字段导致后续新增状态漏存
    - checkpoint 尽量保存当前运行态的完整快照
    """
    return dict(getattr(obj, "__dict__", {}))


def _load_checkpoint_silent():
    """静默读取 checkpoint，仅供保存时继承旧 meta 使用。"""
    if not CHECKPOINT_PATH.exists():
        return None
    try:
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _build_checkpoint_from_state(state):
    """
    按当前 state 构造 checkpoint 数据。

    当前策略：
    - task：尽量保存完整 task 快照，避免后续新增状态漏存
    - memory：保存 memory 快照，但 conversation 仍单独处理
    - conversation：只保存 messages，并对过大的 tool_result 做截断
    """
    existing = _load_checkpoint_silent() or {}
    existing_meta = existing.get("meta", {})

    task_data = _copy_state_dict(state.task)
    memory_data = _copy_state_dict(state.memory)

    return {
        "meta": {
            "session_id": state.memory.session_id,
            "created_at": existing_meta.get("created_at", _now_iso()),
            "interrupted_at": _now_iso(),
        },
        "task": task_data,
        "memory": memory_data,
        "conversation": {
            "messages": _truncate_messages_for_checkpoint(
                state.conversation.messages
            ),
        },
    }


def save_checkpoint(state, source: str | None = None):
    """按当前 state 结构保存断点。

    source 是 Runtime 观测字段，用来标记“是谁触发了这次保存”，帮助后续梳理
    checkpoint save ownership。它不是状态字段，不写入 checkpoint JSON，也不改变
    保存时机；第一阶段只让保存来源可见，后续再决定是否迁移保存责任。
    """
    checkpoint = _build_checkpoint_from_state(state)
    try:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_PATH.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        status = getattr(state.task, "status", None)
        if source:
            print(f"[CHECKPOINT] saved (status={status}, source={source})")
        else:
            print(f"[CHECKPOINT] saved (status={status})")
    except Exception as e:
        print(f"[CHECKPOINT] save failed: {e}")


def load_checkpoint():
    """加载未完成的断点"""
    if not CHECKPOINT_PATH.exists():
        print("[CHECKPOINT] no file")
        return None
    try:
        data = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        print("[CHECKPOINT] loaded")
        return data
    except Exception as e:
        print(f"[CHECKPOINT] load failed: {e}")
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
        # 恢复 task（尽量按 checkpoint 中已有字段完整恢复）
        task_data = checkpoint.get("task", {})
        for key, value in task_data.items():
            setattr(state.task, key, value)

        # 恢复 memory（尽量按 checkpoint 中已有字段完整恢复）
        memory_data = checkpoint.get("memory", {})
        for key, value in memory_data.items():
            setattr(state.memory, key, value)

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
        print("[CHECKPOINT] cleared")

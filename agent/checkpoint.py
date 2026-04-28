import json
import os
from datetime import datetime
from config import PROJECT_DIR

CHECKPOINT_PATH = PROJECT_DIR / "memory" / "checkpoint.json"

MAX_RESULT_LENGTH = 2000  # checkpoint 中 tool_result 的截断长度


def _debug_stdout_enabled() -> bool:
    """checkpoint terminal debug 开关。

    checkpoint 保存/加载本身已经通过结构化日志和返回值表达；默认不再把
    [CHECKPOINT] 打到 stdout，避免 Textual TUI 和普通终端混入内部状态噪声。
    临时排查状态恢复链路时，可设置 MY_FIRST_AGENT_DEBUG=1 打开短日志。
    """

    return os.getenv("MY_FIRST_AGENT_DEBUG", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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

    注意：checkpoint/debug 与用户可见输出是不同通道。默认只写 checkpoint 文件
    和 `checkpoint_saved` 结构化日志；只有设置 MY_FIRST_AGENT_DEBUG=1 时才把
    [CHECKPOINT] 短日志打印到 terminal。
    """
    checkpoint = _build_checkpoint_from_state(state)
    try:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_PATH.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        status = getattr(state.task, "status", None)
        try:
            from agent.logger import log_event

            pending_user_input = getattr(
                state.task,
                "pending_user_input_request",
                None,
            ) or {}
            pending_tool = getattr(state.task, "pending_tool", None) or {}
            log_event(
                "checkpoint_saved",
                {
                    "checkpoint_source": source,
                    "task_status": status,
                    "current_step_index": getattr(
                        state.task,
                        "current_step_index",
                        None,
                    ),
                    "pending_user_input_kind": pending_user_input.get(
                        "awaiting_kind"
                    ),
                    "pending_tool_name": pending_tool.get("tool"),
                },
            )
        except Exception:
            # checkpoint 本身已保存成功；观测日志失败不能改变业务行为。
            pass
        if _debug_stdout_enabled():
            if source:
                print(f"[CHECKPOINT] saved (status={status}, source={source})")
            else:
                print(f"[CHECKPOINT] saved (status={status})")
    except Exception as e:
        print(f"[CHECKPOINT] save failed: {e}")


def load_checkpoint():
    """加载未完成的断点"""
    if not CHECKPOINT_PATH.exists():
        if _debug_stdout_enabled():
            print("[CHECKPOINT] no file")
        return None
    try:
        data = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        if _debug_stdout_enabled():
            print("[CHECKPOINT] loaded")
        return data
    except Exception as e:
        print(f"[CHECKPOINT] load failed: {e}")
        return None


def _filter_to_declared_fields(cls, data: dict) -> dict:
    """只保留 dataclass 声明字段，过滤未知 key。

    背景：`load_checkpoint_to_state` 早期实现对 task / memory dict 直接
    `setattr`，任何不在 dataclass 声明里的 key 都会被悄悄挂成「裸属性」。
    这意味着：旧版本 checkpoint、损坏 checkpoint、或他人误写入的 key 都能
    污染 runtime state，且无法被 `dataclasses.fields(...)` / reset_task /
    invariant 测试检测到。M3 把这条入口收紧到声明字段白名单内，未知字段
    被丢弃，由 dataclass 默认值兜底；这与 v0.2 M3「损坏 checkpoint 不导致
    crash」的目标一致。
    """
    from dataclasses import fields

    declared = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in declared}


# 从 checkpoint 恢复到当前 state
def load_checkpoint_to_state(state):
    """
    从 checkpoint 恢复到当前 state。

    持久字段：task / memory / conversation.messages。
    临时字段（RuntimeEvent / InputIntent / DisplayEvent / TransitionResult /
    InputResolution / tool_traces / runtime config 等）不属于恢复语义；
    任何在 JSON 里出现的非声明字段会在 `_filter_to_declared_fields` 被丢弃。
    """
    from agent.state import TaskState, MemoryState

    checkpoint = load_checkpoint()
    if not checkpoint:
        return False

    try:
        # 恢复 task：只允许 TaskState 已声明字段进入 state，未知 key 丢弃。
        task_data = _filter_to_declared_fields(
            TaskState, checkpoint.get("task", {}) or {}
        )
        for key, value in task_data.items():
            setattr(state.task, key, value)

        # 恢复 memory：同样过滤到 MemoryState 声明字段。
        memory_data = _filter_to_declared_fields(
            MemoryState, checkpoint.get("memory", {}) or {}
        )
        for key, value in memory_data.items():
            setattr(state.memory, key, value)

        # 恢复 conversation.messages（append-only 事件流；tool_traces 不属于恢复语义）。
        conv_data = checkpoint.get("conversation", {}) or {}
        state.conversation.messages = conv_data.get("messages", []) or []

        return True

    except Exception:
        return False


def clear_checkpoint():
    """任务完成后清除断点"""
    if CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()
        if _debug_stdout_enabled():
            print("[CHECKPOINT] cleared")

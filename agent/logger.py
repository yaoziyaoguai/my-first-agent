import json
import datetime
from config import LOG_FILE, SNAPSHOT_DIR
import uuid
SESSION_ID = str(uuid.uuid4())


def log_event(event_type, data):
    """legacy 低层日志入口：把单条事件追加到 ``LOG_FILE`` (agent_log.jsonl)。

    ────────────────────────────────────────────────────────────────────
    v0.5 命名碰撞警告（务必读完再写新代码）
    ────────────────────────────────────────────────────────────────────
    本函数与 ``agent/runtime_observer.py`` 中的 ``log_event`` **同名但签名不同**：

    - ``agent.logger.log_event(event_type, data)``  ← 本函数
        * 两位 positional 参数，``data`` 是任意 dict；
        * 直接 ``json.dumps`` 写入 ``LOG_FILE``，**不脱敏**；
        * IO 异常会向上冒泡（不 swallow）；
        * 历史调用方（v0.5 时刻：planner / memory / checks / session /
          review / context / health_check / checkpoint 懒加载 /
          runtime_observer 兜底转发）。

    - ``agent.runtime_observer.log_event(event_type, *, event_source=None,
      event_payload=None, event_channel=None)``  ← 另一个同名函数
        * keyword-only 后三参；
        * payload 经 ``_safe_log_value`` 脱敏后再写；
        * 任何异常一律 swallow（observer 不能影响 Runtime 行为）；
        * 新代码（core.py / confirm_handlers.py）必须用此入口。

    职责边界
    --------
    本函数 **只负责** 把一条已构造好的 dict 落盘到 jsonl。
    本函数 **不负责** payload 脱敏、不负责区分 channel/source、不负责 swallow。

    为什么 v0.5 不立刻重命名
    --------------------------
    重命名会牵动 9 处 legacy 调用点，跨出本切片"0 runtime 行为变更"边界。
    重命名属于独立 slice（见 docs/V0_5_OBSERVER_AUDIT.md §G5）。
    在那之前，本切片用 ``tests/test_log_event_signature_collision.py``
    把两个 ``log_event`` 的当前签名锁死，防止有人无意中改签名让二者
    "看起来一致"而掩盖真实碰撞。

    新代码该用哪个
    ----------------
    - Runtime 可观测性 / confirmation evidence / DisplayEvent 旁路 →
      用 ``agent.runtime_observer.log_event``。
    - 其余既有 legacy 路径暂保持现状，等专门 slice 统一改名。

    artifact 排查
    --------------
    最终都落到 ``LOG_FILE`` 同一份 jsonl；区分方式是 ``event`` 字段：
    runtime_observer 写入时 ``event="runtime_observer"`` 且 data 内嵌
    真正的 ``event_type``；legacy 直接把 ``event_type`` 放外层。
    """
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "session_id": SESSION_ID,
        "event": event_type,
        "data": data,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def make_serializable(messages):
    result = []
    for msg in messages:
        if isinstance(msg.get("content"), list):
            new_content = []
            for block in msg["content"]:
                if hasattr(block, "model_dump"):
                    new_content.append(block.model_dump())
                else:
                    new_content.append(block)
            result.append({"role": msg["role"], "content": new_content})
        else:
            result.append(msg)
    return result


def save_session_snapshot(messages):
    snapshot = {
        "session_id": SESSION_ID,
        "saved_at": datetime.datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": make_serializable(messages),
    }
    snapshot_file = SNAPSHOT_DIR / f"session_{SESSION_ID}.json"
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

import json
import re
import uuid
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from config import LOG_FILE, MAX_LOG_SIZE_BYTES, SNAPSHOT_DIR, ensure_snapshot_dir

SESSION_ID = str(uuid.uuid4())

# 真实 API key 脱敏正则：匹配 sk-<type>-<secret> 和 sk-<type>-<sub>-<secret> 等多段格式
# 匹配 sk-sp-..., sk-ant-...-..., sk-or-... 等多段 key 格式
# 允许中间出现额外的 -<segment>，最终以 8+ 位字母数字结尾
_KEY_REDACT_RE = re.compile(r"sk-[a-z]+(?:-[a-zA-Z0-9]+)*-[a-zA-Z0-9]{8,}")
_BEARER_REDACT_RE = re.compile(r"Bearer [a-zA-Z0-9_\-]{20,}")
_MAX_STR_LEN = 2000


def _redact_secrets(s: str) -> str:
    """脱敏字符串中的 API key 和 Bearer token。"""
    s = _KEY_REDACT_RE.sub("sk-***REDACTED***", s)
    s = _BEARER_REDACT_RE.sub("Bearer ***REDACTED***", s)
    return s


def _sanitize_log_data(obj, depth: int = 0):
    """递归脱敏日志数据中的所有字符串，截断过长值。

    与 runtime_observer._safe_log_value 互补：
    - 本函数负责：真实 key 脱敏 + 字符串长度截断
    - runtime_observer 负责：结构化短预览 + 深度/条目限制
    """
    if depth > 5:
        return "<nested-too-deep>"
    if obj is None or isinstance(obj, bool | int | float):
        return obj
    if isinstance(obj, str):
        cleaned = _redact_secrets(obj)
        if len(cleaned) > _MAX_STR_LEN:
            return cleaned[:_MAX_STR_LEN] + "..."
        return cleaned
    if isinstance(obj, list):
        return [_sanitize_log_data(v, depth + 1) for v in obj[:100]]
    if isinstance(obj, dict):
        return {str(k): _sanitize_log_data(v, depth + 1) for k, v in obj.items()}
    # 兜底：其他类型 → 转字符串后脱敏
    return _redact_secrets(str(obj))[:_MAX_STR_LEN]


def _rotate_log_if_needed() -> None:
    """agent_log.jsonl 超过 MAX_LOG_SIZE_BYTES 时自动轮转。

    轮转策略：rename 旧文件为 agent_log.archived-YYYYMMDD-HHMMSS.jsonl，
    下一次 log_event 自动创建新文件。同 fs 原子 rename，无 fd 错引。
    """
    log_path = Path(LOG_FILE)
    if not log_path.exists():
        return
    try:
        size = log_path.stat().st_size
    except OSError:
        return
    if size <= MAX_LOG_SIZE_BYTES:
        return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_path = log_path.with_name(f"{log_path.stem}.archived-{ts}{log_path.suffix}")
    with suppress(OSError):
        log_path.rename(archive_path)  # rename 失败不影响日志写入


def log_event(event_type, data):
    """legacy 低层日志入口：把单条事件追加到 ``LOG_FILE`` (agent_log.jsonl)。

    Loop 2 (config remediation) 升级：
    - 写入前自动轮转（>50MB）
    - data 递归脱敏（API key / Bearer token 替换为 ***REDACTED***）
    - 字符串值超过 2000 字符自动截断

    ────────────────────────────────────────────────────────────────────
    v0.5 命名碰撞警告（务必读完再写新代码）
    ────────────────────────────────────────────────────────────────────
    本函数与 ``agent/runtime_observer.py`` 中的 ``log_event`` **同名但签名不同**：

    - ``agent.logger.log_event(event_type, data)``  ← 本函数
        * 两位 positional 参数，``data`` 是任意 dict；
        * 经 ``_sanitize_log_data`` 脱敏后写入；
        * IO 异常会向上冒泡（不 swallow）；
        * 历史调用方：planner / memory / checks / session /
          context / health_check / checkpoint 懒加载 /
          runtime_observer 兜底转发。

    - ``agent.runtime_observer.log_event(event_type, *, event_source=None,
      event_payload=None, event_channel=None)``  ← 另一个同名函数
        * keyword-only 后三参；
        * payload 经 ``_safe_log_value`` 脱敏后再写；
        * 任何异常一律 swallow（observer 不能影响 Runtime 行为）；
        * 新代码（core.py / confirm_handlers.py）必须用此入口。

    职责边界
    --------
    本函数 **负责** payload 脱敏 + 文件大小治理 + jsonl 落盘。
    本函数 **不负责** 区分 channel/source、不负责 swallow。

    artifact 排查
    --------------
    最终都落到 ``LOG_FILE`` 同一份 jsonl；区分方式是 ``event`` 字段：
    runtime_observer 写入时 ``event="runtime_observer"`` 且 data 内嵌
    真正的 ``event_type``；legacy 直接把 ``event_type`` 放外层。
    """
    _rotate_log_if_needed()

    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": SESSION_ID,
        "event": event_type,
        "data": _sanitize_log_data(data),
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
        "saved_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": make_serializable(messages),
    }
    # config import 不再创建 sessions/；snapshot 写入前显式初始化目录，
    # 让 runtime IO 副作用留在 logger 边界，而不是配置导入边界。
    ensure_snapshot_dir()
    snapshot_file = SNAPSHOT_DIR / f"session_{SESSION_ID}.json"
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

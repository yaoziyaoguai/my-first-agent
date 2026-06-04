import json
import re
import uuid
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from config import LOG_FILE, MAX_LOG_SIZE_BYTES, SNAPSHOT_DIR, ensure_snapshot_dir

SESSION_ID = str(uuid.uuid4())
"""Import-time session ID（向后兼容）。B7 引入 set_runtime_session_id() 后，
运行时调用应优先使用 get_runtime_session_id() 获取 session_id。"""

_runtime_session_id: str | None = None
"""B7: main.py startup 时通过 set_runtime_session_id() 设置的 session_id。"""


def set_runtime_session_id(session_id: str) -> None:
    """B7: 设置运行时 session_id（由 main.py startup 调用）。"""
    global _runtime_session_id
    _runtime_session_id = session_id


def get_runtime_session_id() -> str:
    """返回运行时 session_id（如果已设置），否则回退到 import-time SESSION_ID。"""
    return _runtime_session_id or SESSION_ID

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


# ── legacy event_type → 结构化类别映射 ──────────────────────────────────
# F-004: 旧 agent_log.jsonl 使用任意字符串作为 event_type（如 "health_check"、
# "planning_mode_entered"、"linter_passed"），在 log_viewer 中因无 taxonomy
# 映射而显示为 "?"。此映射表将已知旧事件字符串归一化为结构化类别。
_LEGACY_EVENT_TYPE_MAP: dict[str, str] = {
    # context compression
    "context_compression_start": "system.context_compression",
    "context_compression_done": "system.context_compression",
    # health check
    "health_check": "system.health_check",
    # planning
    "planning_mode_entered": "planning.mode_entered",
    "planning_model_empty_text": "planning.model_error",
    "planning_model_call_error": "planning.model_error",
    "action_plan_schema_invalid": "planning.schema_invalid",
    "action_plan_schema_validated": "planning.schema_validated",
    "planning_failed": "planning.failed",
    "model_plan_received": "planning.plan_received",
    "scheduler_load_success": "planning.scheduler_loaded",
    "planning_handoff_failure": "planning.handoff_failure",
    "plan_skipped": "planning.skipped",
    "plan_error": "planning.error",
    "plan_generated": "planning.generated",
    "action_plan_generated": "planning.generated",
    # linting / quality
    "linter_passed": "quality.lint_passed",
    "linter_issues": "quality.lint_issues",
}


def _normalize_legacy_event_type(event_type: str) -> str:
    """将旧版任意 event_type 字符串映射到结构化类别。

    已知字符串直接映射；未知字符串保留原值（不静默吞掉），
    便于 log_viewer 区分"已知未映射"和"真正未知"。
    """
    return _LEGACY_EVENT_TYPE_MAP.get(event_type, event_type)


def log_event(event_type, data):
    """legacy 低层日志入口：把单条事件追加到 ``LOG_FILE`` (agent_log.jsonl)。

    Loop 2 (config remediation) 升级：
    - 写入前自动轮转（>50MB）
    - data 递归脱敏（API key / Bearer token 替换为 ***REDACTED***）
    - 字符串值超过 2000 字符自动截断

    F-004 (event_type normalization)：
    - 写入时同时保留原始 event_type 和归一化后的 event_category，
      使 log_viewer 可按结构化类别分类而不丢失原始信息。

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

    normalized = _normalize_legacy_event_type(event_type)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": get_runtime_session_id(),
        "event": event_type,
        "event_category": normalized,
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
    _sid = get_runtime_session_id()
    snapshot = {
        "session_id": _sid,
        "saved_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": make_serializable(messages),
    }
    # config import 不再创建 sessions/；snapshot 写入前显式初始化目录，
    # 让 runtime IO 副作用留在 logger 边界，而不是配置导入边界。
    ensure_snapshot_dir()
    snapshot_file = SNAPSHOT_DIR / f"session_{_sid}.json"
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

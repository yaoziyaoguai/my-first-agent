"""统一持久化策略 — Evidence Persistence Policy.

所有落盘点（session transcript、runtime checkpoint、event log、global log）
必须复用本模块的策略函数，不允许各自手写截断/脱敏逻辑。

职责：
- 定义统一的内容持久化预算（阈值、摘要格式）
- 提供 summarize_tool_result_for_persistence() 和 summarize_messages_for_persistence()
- 敏感路径识别（统一入口，避免多处重复定义敏感模式）

非职责：
- 不负责写入任何文件（那是 logger/checkpoint/EventLogWriter 的职责）
- 不负责 Runtime 状态恢复决策（那是 checkpoint 的职责）
- 不负责证据 envelope（那是 evidence_recorder 的职责）

中文学习边界：
为什么需要统一 persistence policy？
- b52620e 之前，session/checkpoint/log 各自手写截断逻辑，阈值不一致
  （session=2KB, checkpoint=2000chars, agent_log=2000chars），
  改一个阈值时另外两个不会跟着变（shotgun surgery 前兆）。
- checkpoint 的 _truncate_messages_for_checkpoint 只做截断不做敏感路径摘要，
  导致 config.yaml 的前 2000 字符仍会进入 checkpoint。
- 统一策略后，三个落盘点的 tool_result 处理行为完全一致，
  未来新增落盘点也不会有遗漏。
"""

from __future__ import annotations

import hashlib
from typing import Any

# ── 持久化预算常量 ──────────────────────────────────────────────
# 超过此字节数的 tool_result content 替换为摘要 dict
MAX_TOOL_RESULT_BYTES = 2048  # 2KB
# 摘要 preview 保留的前 N 个字符
MAX_PREVIEW_CHARS = 200

# ── 敏感路径模式 ─────────────────────────────────────────────────
# 匹配这些模式的路径永不保存原文，即使内容小于阈值
_SENSITIVE_PATH_PATTERNS: tuple[str, ...] = (
    "config/config.yaml", "config/config.yml",
    ".env", ".envrc", ".env.local",
    "credentials", "secrets", "private", "key", "token",
)


def _path_kind(path: str) -> str:
    if path.startswith("~"):
        return "home"
    if (
        path == "/tmp"
        or path.startswith("/tmp/")
        or path == "/private/tmp"
        or path.startswith("/private/tmp/")
        or "/var/folders/" in path
    ):
        return "tmp"
    if path.startswith("/"):
        return "absolute"
    if path.strip():
        return "relative"
    return "unknown"


def _safe_path_metadata(path: str) -> dict[str, Any]:
    """持久化 metadata 只能记录路径类别和 hash，不暴露 basename/full path。"""

    raw = str(path or "")
    if not raw:
        return {}
    return {
        "path_kind": _path_kind(raw),
        "path_hash": f"path:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}",
        "redacted": True,
    }


def looks_like_sensitive_path(path: str) -> bool:
    """检查路径是否匹配敏感文件模式。

    大小写不敏感，子串匹配。例如：
    - "config/config.yaml" → True
    - ".env" → True
    - "workspace/demo/note.md" → False
    """
    lowered = path.lower()
    return any(pattern in lowered for pattern in _SENSITIVE_PATH_PATTERNS)


def summarize_content_for_persistence(
    content: str,
    *,
    path: str = "",
    tool_name: str = "",
) -> str | dict[str, Any]:
    """对单个 tool_result content 做持久化摘要。

    返回规则：
    - 内容 ≤ MAX_TOOL_RESULT_BYTES 且非敏感路径 → 原样返回字符串
    - 内容 > MAX_TOOL_RESULT_BYTES 或敏感路径 → 返回摘要 dict

    摘要 dict 字段：
    - result_size: int — 原始内容字节数
    - result_hash: str — sha256 前 16 位 hex
    - preview_redacted: str — 前 MAX_PREVIEW_CHARS 字符
    - truncated: true
    - tool_name: str
    - content_persisted: false
    - content_redacted: true (仅敏感路径)
    - sensitive: true (仅敏感路径)
    - reason_code: 仅敏感路径时 = "sensitive_path"
    """
    content_str = content if isinstance(content, str) else str(content)
    content_bytes = content_str.encode("utf-8")
    result_size = len(content_bytes)
    result_hash = hashlib.sha256(content_bytes).hexdigest()[:16]
    is_sensitive = looks_like_sensitive_path(path)

    if result_size <= MAX_TOOL_RESULT_BYTES and not is_sensitive:
        return content_str

    # 超阈值或敏感路径 → 摘要 dict
    # 敏感路径的 preview 必须是安全替代文本，不能包含原始内容
    preview = (
        "[REDACTED] sensitive path" if is_sensitive else content_str[:MAX_PREVIEW_CHARS]
    )
    summary: dict[str, Any] = {
        "result_size": result_size,
        "result_hash": result_hash,
        "preview_redacted": preview,
        "truncated": True,
        "tool_name": tool_name,
        "content_persisted": False,
    }
    if is_sensitive:
        summary["content_redacted"] = True
        summary["sensitive"] = True
        summary["reason_code"] = "sensitive_path"
    return summary


def summarize_tool_result_content(
    content: str,
    path: str = "",
    tool_name: str = "",
) -> str | dict[str, Any]:
    """向后兼容别名 — 等同于 summarize_content_for_persistence()。

    历史调用方（logger.py 的 _summarize_tool_result_content）可通过此函数
    迁移到统一策略。

    返回 str 表示内容可安全保存；返回 dict 表示已摘要化。
    """
    return summarize_content_for_persistence(
        content, path=path, tool_name=tool_name,
    )


def summarize_tool_result_for_persistence(
    content: str,
    *,
    path: str = "",
    tool_name: str = "",
) -> dict[str, Any]:
    """强制摘要模式 — 始终返回 dict（即使内容很小）。

    用于只需要 metadata、绝不需要原文的场景（如 blocked sensitive path）。
    """
    content_str = content if isinstance(content, str) else str(content)
    content_bytes = content_str.encode("utf-8")
    result_size = len(content_bytes)
    result_hash = hashlib.sha256(content_bytes).hexdigest()[:16]
    is_sensitive = looks_like_sensitive_path(path)
    preview = (
        "[REDACTED] sensitive path" if is_sensitive else content_str[:MAX_PREVIEW_CHARS]
    )

    summary: dict[str, Any] = {
        "result_size": result_size,
        "result_hash": result_hash,
        "preview_redacted": preview,
        "truncated": True,
        "tool_name": tool_name,
        "content_persisted": False,
    }
    if is_sensitive:
        summary["content_redacted"] = True
        summary["sensitive"] = True
        summary["reason_code"] = "sensitive_path"
    return summary


def build_denial_metadata(
    tool_name: str = "",
    path: str = "",
    reason_code: str = "sensitive_path",
) -> dict[str, Any]:
    """为 blocked sensitive tool 构建 denial metadata（不含任何 content）。"""
    metadata = {
        "tool_name": tool_name,
        "decision": "blocked",
        "reason_code": reason_code,
        "content_persisted": False,
        "content_redacted": True,
        "sensitive": True,
        "result_size": 0,
        "result_hash": "",
        "preview_redacted": "",
        "truncated": False,
    }
    metadata.update(_safe_path_metadata(path))
    return metadata


def summarize_messages_for_persistence(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """处理 conversation.messages：遍历 tool_result block，替换为摘要。

    不改变原始 messages（不可变原则）。
    通过 tool_use_id 配对 tool_use（含 path/name）和 tool_result（含 content）。

    用于 session transcript 和 runtime checkpoint 的统一 messages 持久化。

    注意：此函数不区分"保存到 session transcript"还是"保存到 checkpoint"——
    调用方自行决定使用处理后的 messages。
    如果 Runtime 恢复需要原始 tool_result 内容，调用方必须自行报告
    ARCHITECTURE_GAP，不允许绕过摘要策略偷偷保存全文。
    """
    # 第一遍：收集所有 tool_use block，建立 tool_use_id → input/name 映射
    tool_inputs: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tu_id = block.get("id", "")
                    if tu_id:
                        tool_inputs[tu_id] = {
                            "input": block.get("input", {}),
                            "name": block.get("name", ""),
                        }

    # 第二遍：对 tool_result 做摘要化
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            new_blocks: list[dict[str, Any]] = []
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tu_id = block.get("tool_use_id", "")
                    raw = block.get("content", "")
                    tool_info = tool_inputs.get(tu_id, {})
                    tool_name = str(tool_info.get("name", ""))
                    path = str(tool_info.get("input", {}).get("path", ""))

                    summarized = summarize_content_for_persistence(
                        raw, path=path, tool_name=tool_name,
                    )
                    if isinstance(summarized, dict):
                        new_block: dict[str, Any] = {
                            "type": "tool_result",
                            "tool_use_id": tu_id,
                            "summary": summarized,
                        }
                        if block.get("is_error"):
                            new_block["is_error"] = True
                        new_blocks.append(new_block)
                    else:
                        # 小内容 → 保留原 block
                        new_blocks.append(block)
                else:
                    new_blocks.append(block)
            result.append({"role": msg["role"], "content": new_blocks})
        else:
            result.append(msg)
    return result

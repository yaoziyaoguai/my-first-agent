"""Child identity / prompt / status 的纯共享 helper（不 import loop/provider）。

这些函数被 ``runner.py``（同步 receipt 路径）、``process_runner.py``（进程隔离路径）与
``child.py``（子进程 entrypoint）共用。本模块刻意不导入 ``agent.runtime.loop`` 或
``agent.provider``——loop 的构造只发生在被架构 exempt 的 ``runner.py`` 内，避免在 subagent
包内散落第二处 loop 依赖。
"""

from __future__ import annotations

import hashlib


def derive_child_identity(parent_idempotency_key: str) -> tuple[str, str]:
    """从 parent intent idempotency key 确定性派生 child conversation/run identity。

    同一 parent action replay 派生同一 child identity；模型不能自行指定 child ID。
    """
    digest = hashlib.sha256(parent_idempotency_key.encode("utf-8")).hexdigest()
    return f"child:{digest[:16]}", f"child-run:{digest[:16]}"


def compose_child_prompt(objective: str, handoff: str) -> str:
    """组装 child 的 SubmitMessage 文本：objective + untrusted parent handoff。"""
    prompt = f"Objective: {objective}"
    if handoff:
        prompt = f"{prompt}\nContext (untrusted, parent-provided): {handoff}"
    return prompt


def child_status_reason(status) -> str:
    """child terminal status → executor reason。COMPLETED 为成功，其余为 child_nonterminal。"""
    from agent.runtime.contracts import RunStatus

    if status is RunStatus.COMPLETED:
        return "completed"
    return "child_nonterminal"

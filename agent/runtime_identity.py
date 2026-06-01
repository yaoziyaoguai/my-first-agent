"""RuntimeIdentity — session/run/instance 三级 identity 值对象。

B7 Multi-Instance Readiness 的 identity 基础类型。不可变、slots、无外部依赖。
不持有 runtime state——只是 identity 值的容器。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    """session/run/instance 三级 identity。

    session_id: CLI 进程级标识（main.py startup 时生成）
    run_id: 单次 chat() 调用的标识（chat() 入口生成）
    instance_id: 隔离单元标识（默认等于 session_id）
    """

    session_id: str
    run_id: str
    instance_id: str = ""

    def __post_init__(self) -> None:
        if not self.instance_id:
            object.__setattr__(self, "instance_id", self.session_id)

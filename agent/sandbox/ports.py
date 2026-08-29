"""``SandboxConfiner`` port：017 native sandbox 唯一的 external-effect seam。

port 只声明 qualify/confine 两个操作；实现不得认识 Goal/approval/
checkpoint、不得 spawn 进程（执行由既有 process runner 完成）、不得提供
factory/registry。治理（candidate/approval/lease/receipt）在
``agent.runtime``（design §2、spec §3）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from agent.process.contracts import ProcessCommandV1
from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox.contracts import (
    ConfinedInvocationV1,
    SandboxPolicyV1,
    SandboxQualificationV1,
)


class SandboxConfiner(Protocol):
    def qualify(self) -> SandboxQualificationV1:
        """只读探测 backend（不安装/启动/登录任何服务；不执行用户命令）。"""
        ...

    def confine(
        self,
        command: ProcessCommandV1,
        policy: SandboxPolicyV1,
        environment: Mapping[str, str],
    ) -> ConfinedInvocationV1 | KnownNotExecuted:
        """把 exact command 编译为受约束 invocation + enforcement facts。

        confined modes 在 backend unavailable 时返回 KnownNotExecuted
        （fail closed）；danger-full-access 返回 unconfined facts 的直接
        invocation，不探测 backend。
        """
        ...

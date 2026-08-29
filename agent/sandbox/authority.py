"""017 sandbox authority 合同的包内入口（durable 类型由 runtime contracts 拥有）。

``SandboxAuthorityCandidateV1`` / ``SandboxAuthorityLeaseV1`` / ``SandboxReceiptV1``
定义在 ``agent.runtime.contracts``（checkpoint durable members 需要 round-trip，
依赖方向必须是 sandbox → runtime，不得反向）。本模块 re-export 同一组类型——
sandbox 侧消费单一来源，防止类型分裂（与 process 包 re-export KnownNotExecuted
同模式）。
"""

from __future__ import annotations

from agent.runtime.contracts import (  # noqa: F401  re-export
    SANDBOX_EXPIRY_MINUTES,
    SANDBOX_MAX_USES,
    SandboxAuthorityCandidateV1,
    SandboxAuthorityLeaseV1,
    SandboxReceiptV1,
)

"""017 sandbox 包：native 进程约束的合同、policy 与 adapter。

包内模块不认识 Goal、Memory、Provider、ContextPack 或 approval（design
§2）；治理（candidate/approval/lease/receipt）由 ``agent.runtime`` 拥有。
本包只提供 ``SandboxConfiner`` port、native contracts/policy 与 macOS
Seatbelt 实现。
"""

from agent.sandbox.contracts import (
    ConfinedInvocationV1,
    SandboxBackendIdentityV1,
    SandboxDraftOutcome,
    SandboxEnforcementFactsV1,
    SandboxExecutionDraftV1,
    SandboxMode,
    SandboxNetworkMode,
    SandboxPolicyV1,
    SandboxQualificationV1,
)

__all__ = [
    "ConfinedInvocationV1",
    "SandboxBackendIdentityV1",
    "SandboxDraftOutcome",
    "SandboxEnforcementFactsV1",
    "SandboxExecutionDraftV1",
    "SandboxMode",
    "SandboxNetworkMode",
    "SandboxPolicyV1",
    "SandboxQualificationV1",
]

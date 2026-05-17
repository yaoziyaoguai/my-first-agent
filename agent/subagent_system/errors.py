"""SubAgent typed errors.

所有错误都必须可安全展示：message / safe_preview 不包含原始 prompt、secret
或大块资源内容。错误对象构造后不可变，避免跨边界传递时被后续层改写。
"""

from __future__ import annotations

from pathlib import Path


_EXCEPTION_FRAMEWORK_ATTRS = frozenset({
    "__traceback__",
    "__cause__",
    "__context__",
    "__suppress_context__",
    "__notes__",
    "args",
})


class SubAgentError(Exception):
    """Base error for formal SubAgent System."""

    code: str
    message: str
    path: Path | None
    recoverable: bool
    safe_preview: str
    _locked: bool

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: Path | None = None,
        recoverable: bool = False,
        safe_preview: str = "",
    ) -> None:
        super().__init__(message)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "recoverable", recoverable)
        object.__setattr__(self, "safe_preview", safe_preview or message)
        object.__setattr__(self, "_locked", True)

    def __setattr__(self, name: str, value: object) -> None:
        if name in _EXCEPTION_FRAMEWORK_ATTRS:
            object.__setattr__(self, name, value)
            return
        if not getattr(self, "_locked", False):
            object.__setattr__(self, name, value)
            return
        raise AttributeError(f"SubAgentError is immutable: {name}")


class SubAgentLoadError(SubAgentError):
    """SUBAGENT.md parse / validation failure."""


class SubAgentPolicyError(SubAgentError):
    """Delegation violates parent-controlled policy."""


class SubAgentModeError(SubAgentPolicyError):
    """Execution mode is unsupported or gated closed."""


class SubAgentToolDeniedError(SubAgentPolicyError):
    """Tool request is outside SubAgent / ToolRegistry boundary."""


class SubAgentMemoryDeniedError(SubAgentPolicyError):
    """Memory operation is outside read/propose governance."""


class SubAgentContextBudgetError(SubAgentPolicyError):
    """Context package cannot satisfy the configured budget."""


class SubAgentExecutionError(SubAgentError):
    """L0 local execution failure."""


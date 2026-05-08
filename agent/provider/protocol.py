"""Provider-neutral response contract for AgentLoop.

这里的类型刻意保持很薄：AgentLoop / response_handlers 只需要 text block、
tool_use block、stop_reason 和 usage 摘要，不应该直接依赖某个 SDK 的类。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ProviderError(Exception):
    """Base class for provider errors with safe public messages."""

    code = "provider_error"

    def __init__(self, message: str | None = None, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        safe_message = message or self.code
        super().__init__(safe_message)


class ProviderConfigurationError(ProviderError):
    code = "provider_configuration_error"


class ProviderNotImplementedError(ProviderError):
    code = "provider_not_implemented"


class ProviderAuthError(ProviderError):
    code = "provider_auth_error"


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout_error"


class ProviderResponseError(ProviderError):
    code = "provider_response_error"


class ProviderCapabilityError(ProviderError):
    code = "provider_capability_error"


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]

    @property
    def type(self) -> str:
        return "tool_use"


@dataclass(frozen=True)
class ProviderTextBlock:
    text: str

    @property
    def type(self) -> str:
        return "text"


@dataclass(frozen=True)
class ProviderResponse:
    content: list[ProviderTextBlock | ToolUseBlock]
    stop_reason: str | None
    usage: dict[str, Any] = field(default_factory=dict)
    raw_provider_name: str | None = None


@runtime_checkable
class ModelProvider(Protocol):
    provider_type: str
    supports_tools: bool
    supports_streaming: bool

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ProviderResponse:
        """Create a non-streaming model response."""

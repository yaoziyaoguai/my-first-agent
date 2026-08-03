"""Provider 端口与不会泄露上游细节的错误分类。"""

from __future__ import annotations

from agent.runtime.ports import (
    ModelProvider,
)
from agent.runtime.ports import (
    RetryableProviderError as RuntimeRetryableProviderError,
)


class ProviderError(RuntimeError):
    """所有 Provider 错误的安全基类。

    异常消息只使用稳定 code。响应正文、URL、header 和 credential 都不得进入异常。
    """

    code = "provider_error"
    retryable = False

    def __init__(self, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(self.code)


class ProviderFatalError(ProviderError):
    code = "provider_fatal"


class ProviderRetryableError(ProviderError, RuntimeRetryableProviderError):
    code = "provider_retryable"
    retryable = True


class ProviderConfigurationError(ProviderFatalError):
    code = "provider_configuration_error"


class ProviderAuthError(ProviderFatalError):
    code = "provider_auth_error"


class ProviderProtocolError(ProviderFatalError):
    code = "provider_protocol_error"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.status_code = None
        RuntimeError.__init__(self, reason)


class ProviderHTTPError(ProviderFatalError):
    code = "provider_http_error"


class ProviderHTTPRetryableError(ProviderRetryableError):
    code = "provider_http_retryable"


class ProviderTimeoutError(ProviderRetryableError):
    code = "provider_timeout"


class ProviderTransportError(ProviderRetryableError):
    code = "provider_transport"


__all__ = [
    "ModelProvider",
    "ProviderAuthError",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderFatalError",
    "ProviderHTTPError",
    "ProviderHTTPRetryableError",
    "ProviderProtocolError",
    "ProviderRetryableError",
    "ProviderTimeoutError",
    "ProviderTransportError",
]

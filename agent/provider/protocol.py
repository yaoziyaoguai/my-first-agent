"""Provider 端口与不会泄露上游细节的错误分类。"""

from __future__ import annotations

from agent.runtime.ports import (
    InvalidProviderResponseError,
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


class ProviderProtocolError(ProviderFatalError, InvalidProviderResponseError):
    code = "provider_protocol_error"

    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        # detail 只允许携带结构事实(键名/期望形状),绝不含响应正文、值或
        # credential;用于给模型 repair 消息提供有界自纠信息。
        self.reason = reason
        self.detail = detail
        self.status_code = None
        RuntimeError.__init__(self, reason)


class ProviderHTTPError(ProviderFatalError):
    code = "provider_http_error"

    def __init__(self, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        diagnostic = (
            f"{self.code}_status_{status_code}"
            if isinstance(status_code, int)
            else self.code
        )
        RuntimeError.__init__(self, diagnostic)


class ProviderHTTPRetryableError(ProviderRetryableError):
    code = "provider_http_retryable"


class ProviderTimeoutError(ProviderRetryableError):
    code = "provider_timeout"


class ProviderTransportError(ProviderRetryableError):
    code = "provider_transport"


class ProviderStreamInterruptedError(ProviderRetryableError):
    """请求已产生流式响应，结果未知；只能由显式 resume 再次发送。"""

    code = "provider_stream_interrupted"


class ProviderStreamCancelledError(ProviderRetryableError):
    """流式连接已因当前 invocation 的受控取消请求而关闭。"""

    code = "provider_stream_cancelled"


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
    "ProviderStreamInterruptedError",
    "ProviderStreamCancelledError",
]

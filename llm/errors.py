"""Safe provider error classification for the LLM processing MVP.

provider 边界会接触真实 SDK 异常、HTTP 状态和网络错误。M5 在这里统一分类，
是为了让 CLI 输出和 runs/*.jsonl 都只保存可诊断的安全摘要，而不是把 key、
headers、base_url、prompt、completion 或 response body 泄漏到审计产物里。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ERROR_MISSING_CONFIG = "missing_config"
ERROR_AUTH = "auth_error"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_NETWORK = "network_error"
ERROR_TIMEOUT = "timeout"
ERROR_BAD_RESPONSE = "bad_response"
ERROR_UNKNOWN_PROVIDER = "unknown_provider"
ERROR_PROVIDER = "provider_error"

PROVIDER_ERROR_CODES = {
    ERROR_MISSING_CONFIG,
    ERROR_AUTH,
    ERROR_RATE_LIMITED,
    ERROR_NETWORK,
    ERROR_TIMEOUT,
    ERROR_BAD_RESPONSE,
    ERROR_UNKNOWN_PROVIDER,
    ERROR_PROVIDER,
}

_USER_MESSAGES = {
    ERROR_MISSING_CONFIG: "Provider configuration is incomplete.",
    ERROR_AUTH: "Provider authentication failed.",
    ERROR_RATE_LIMITED: "Provider rate limit was reached.",
    ERROR_NETWORK: "Provider network request failed.",
    ERROR_TIMEOUT: "Provider request timed out.",
    ERROR_BAD_RESPONSE: "Provider returned an unusable response.",
    ERROR_UNKNOWN_PROVIDER: "Provider is not supported by this MVP.",
    ERROR_PROVIDER: "Provider request failed.",
}


def _safe_error_type(error_type: str) -> str:
    """错误 type 只能是短标识符，避免 SDK 原始 message 混入输出。"""

    if (
        1 <= len(error_type) <= 64
        and error_type.replace("_", "").replace("-", "").replace(".", "").isalnum()
    ):
        return error_type
    return "provider_exception"


@dataclass(frozen=True)
class ProviderError(Exception):
    code: str
    type: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.code}:{self.type}"

    def to_public_dict(self) -> dict[str, object]:
        """返回可写入 stdout/state/runs 的脱敏错误摘要。"""

        return {
            "code": self.code,
            "type": self.type,
            "message": self.message,
            "retryable": self.retryable,
        }


def make_provider_error(
    code: str,
    error_type: str,
    *,
    retryable: bool = False,
) -> ProviderError:
    """创建用户可读但不含原始异常文本的 ProviderError。"""

    if code not in PROVIDER_ERROR_CODES:
        code = ERROR_PROVIDER
    return ProviderError(
        code=code,
        type=_safe_error_type(error_type),
        message=_USER_MESSAGES[code],
        retryable=retryable,
    )


def safe_error_dict(error: ProviderError) -> dict[str, object]:
    return error.to_public_dict()


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(value, int):
        return value
    return None


def _class_name(exc: BaseException) -> str:
    return exc.__class__.__name__


def classify_provider_exception(exc: BaseException) -> ProviderError:
    """把 SDK/HTTP/Python 异常归类成固定 code，不透传原始异常 message。

    真实 SDK 异常经常把 request URL、headers 或 response body 放进字符串里。
    因此这里只看类型名和 status_code 这类结构化信号，输出固定的用户提示。
    """

    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, TimeoutError):
        return make_provider_error(ERROR_TIMEOUT, "timeout", retryable=True)

    status_code = _status_code(exc)
    class_name = _class_name(exc)
    normalized = class_name.lower()

    if status_code in {401, 403} or "auth" in normalized or "permission" in normalized:
        return make_provider_error(ERROR_AUTH, class_name, retryable=False)
    if status_code == 429 or "ratelimit" in normalized or "rate_limit" in normalized:
        return make_provider_error(ERROR_RATE_LIMITED, class_name, retryable=True)
    if status_code in {408, 504} or "timeout" in normalized:
        return make_provider_error(ERROR_TIMEOUT, class_name, retryable=True)
    if status_code in {502, 503}:
        return make_provider_error(ERROR_NETWORK, class_name, retryable=True)
    if "connection" in normalized or "network" in normalized:
        return make_provider_error(ERROR_NETWORK, class_name, retryable=True)
    if status_code is not None and 400 <= status_code < 500:
        return make_provider_error(ERROR_BAD_RESPONSE, class_name, retryable=False)
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return make_provider_error(ERROR_BAD_RESPONSE, class_name, retryable=False)
    return make_provider_error(ERROR_PROVIDER, class_name, retryable=False)


def public_error_from_unknown(exc: BaseException) -> dict[str, Any]:
    return safe_error_dict(classify_provider_exception(exc))

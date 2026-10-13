"""Minimal Runtime Kernel 的显式 Provider 配置。"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.provider.protocol import ProviderConfigurationError
from agent.runtime.contracts import ProviderDescriptor

SUPPORTED_PROVIDER_TYPES = frozenset(
    {"fake", "anthropic_compatible", "openai_compatible"}
)
DEEPSEEK_FLASH_MODEL_IDS = frozenset(
    {"deepseek-v4-flash", "deepseek-flash"}
)
DEEPSEEK_API_BASE_URLS = frozenset(
    {
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
        "https://api.deepseek.com/beta",
    }
)
DEEPSEEK_THINKING_BASE_URLS = frozenset(
    {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
)
DEFAULT_MAX_TOKENS = 4_096


@dataclass(frozen=True, slots=True)
class ProviderCapacity:
    """由精确 provider identity 选择的公开容量合同。"""

    context_window_tokens: int
    max_output_tokens: int


DEEPSEEK_FLASH_CAPACITY = ProviderCapacity(
    context_window_tokens=1_000_000,
    max_output_tokens=384_000,
)


def resolve_provider_capacity(
    *,
    provider_type: str,
    model: str,
    base_url: str | None,
) -> ProviderCapacity | None:
    """只为已审计的官方 endpoint 返回容量，未知兼容端点保持保守默认。"""
    normalized_base_url = None if base_url is None else base_url.rstrip("/")
    if (
        provider_type.strip().lower() == "openai_compatible"
        and model.strip() in DEEPSEEK_FLASH_MODEL_IDS
        and normalized_base_url in DEEPSEEK_API_BASE_URLS
    ):
        return DEEPSEEK_FLASH_CAPACITY
    return None


@dataclass(frozen=True, slots=True)
class AgentProviderConfig:
    """Composition root 注入的配置；本模块不读取环境或持久化 credential。"""

    provider_type: str
    model: str = "fake"
    base_url: str | None = None
    credential: str | None = field(default=None, repr=False, compare=False)
    max_tokens: int | None = None
    timeout: float = 30.0
    auth_scheme: str | None = None
    request_path: str | None = None
    thinking_mode: str | None = None
    reasoning_effort: str | None = None
    strict_tools: bool = False

    def __post_init__(self) -> None:
        provider_type = self.provider_type.strip().lower()
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ProviderConfigurationError()
        if not self.model.strip():
            raise ProviderConfigurationError()
        max_tokens = self.max_tokens
        if max_tokens is None:
            capacity = resolve_provider_capacity(
                provider_type=provider_type,
                model=self.model,
                base_url=self.base_url,
            )
            max_tokens = (
                capacity.max_output_tokens
                if capacity is not None
                else DEFAULT_MAX_TOKENS
            )
        if max_tokens < 1 or self.timeout <= 0:
            raise ProviderConfigurationError()
        if not isinstance(self.strict_tools, bool):
            raise ProviderConfigurationError()

        object.__setattr__(self, "provider_type", provider_type)
        object.__setattr__(self, "model", self.model.strip())
        object.__setattr__(self, "max_tokens", max_tokens)
        if self.base_url is not None:
            object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

        if provider_type == "fake":
            if (
                self.auth_scheme is not None
                or self.request_path is not None
                or self.thinking_mode is not None
                or self.reasoning_effort is not None
                or self.strict_tools
            ):
                raise ProviderConfigurationError()
            return

        # enabled 只开放给已经实现 opaque continuity + SSE 收束合同的精确
        # DeepSeek Flash 链；其他 compatible endpoint 仍只能关闭或不传。
        # anthropic_compatible 自 r19 起允许 disabled:bigmodel 等兼容端点对部分
        # 模型默认返回 thinking block，normalize 按合同拒绝会使组合完全阻断；
        # disabled 用 Anthropic 官方 thinking 字段显式关闭，不引入 vendor 扩展。
        if self.thinking_mode not in {None, "disabled", "enabled"}:
            raise ProviderConfigurationError()
        if self.thinking_mode == "disabled" and provider_type not in {
            "anthropic_compatible",
            "openai_compatible",
        }:
            raise ProviderConfigurationError()
        if self.thinking_mode != "enabled" and self.reasoning_effort is not None:
            raise ProviderConfigurationError()
        if self.strict_tools and provider_type != "openai_compatible":
            raise ProviderConfigurationError()

        if not self.base_url:
            raise ProviderConfigurationError()
        default_scheme = (
            "x-api-key" if provider_type == "anthropic_compatible" else "bearer"
        )
        auth_scheme = self.auth_scheme or default_scheme
        if auth_scheme not in {"bearer", "x-api-key"}:
            raise ProviderConfigurationError()
        object.__setattr__(self, "auth_scheme", auth_scheme)

        default_path = (
            "/v1/messages"
            if provider_type == "anthropic_compatible"
            else "/v1/chat/completions"
        )
        request_path = self.request_path or default_path
        if (
            not request_path.startswith("/")
            or request_path.startswith("//")
            or any(ch.isspace() or ord(ch) < 0x20 for ch in request_path)
            or "?" in request_path
            or "#" in request_path
        ):
            raise ProviderConfigurationError()
        object.__setattr__(self, "request_path", request_path)

        if self.thinking_mode == "enabled" and (
            provider_type != "openai_compatible"
            or self.model not in DEEPSEEK_FLASH_MODEL_IDS
            or self.base_url not in DEEPSEEK_THINKING_BASE_URLS
            or request_path != "/v1/chat/completions"
            or self.reasoning_effort != "max"
            or self.strict_tools
        ):
            raise ProviderConfigurationError()

    @property
    def endpoint(self) -> str:
        if self.provider_type == "fake" or self.base_url is None:
            raise ProviderConfigurationError()
        if self.base_url.endswith("/v1") and self.request_path.startswith("/v1/"):
            return f"{self.base_url}{self.request_path[3:]}"
        return f"{self.base_url}{self.request_path}"

    def descriptor(self) -> ProviderDescriptor:
        if self.provider_type == "fake":
            return ProviderDescriptor(
                family="fake",
                model=self.model,
                canonical_destination="http://127.0.0.1/fake",
                trust_profile="local-no-network-v1",
                remote=False,
            )
        return ProviderDescriptor(
            family=self.provider_type,
            model=self.model,
            canonical_destination=self.endpoint,
            trust_profile="remote-https-v1",
            remote=True,
        )

__all__ = [
    "AgentProviderConfig",
    "DEEPSEEK_API_BASE_URLS",
    "DEEPSEEK_FLASH_CAPACITY",
    "DEEPSEEK_FLASH_MODEL_IDS",
    "DEEPSEEK_THINKING_BASE_URLS",
    "DEFAULT_MAX_TOKENS",
    "ProviderCapacity",
    "SUPPORTED_PROVIDER_TYPES",
    "resolve_provider_capacity",
]

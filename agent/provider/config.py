"""Minimal Runtime Kernel 的显式 Provider 配置。"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.provider.protocol import ProviderConfigurationError
from agent.runtime.contracts import ProviderDescriptor

SUPPORTED_PROVIDER_TYPES = frozenset(
    {"fake", "anthropic_compatible", "openai_compatible"}
)


@dataclass(frozen=True, slots=True)
class AgentProviderConfig:
    """Composition root 注入的配置；本模块不读取环境或持久化 credential。"""

    provider_type: str
    model: str = "fake"
    base_url: str | None = None
    credential: str | None = field(default=None, repr=False, compare=False)
    max_tokens: int = 4096
    timeout: float = 30.0
    auth_scheme: str | None = None
    request_path: str | None = None
    thinking_mode: str | None = None

    def __post_init__(self) -> None:
        provider_type = self.provider_type.strip().lower()
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ProviderConfigurationError()
        if not self.model.strip():
            raise ProviderConfigurationError()
        if self.max_tokens < 1 or self.timeout <= 0:
            raise ProviderConfigurationError()

        object.__setattr__(self, "provider_type", provider_type)
        object.__setattr__(self, "model", self.model.strip())
        if self.base_url is not None:
            object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

        if provider_type == "fake":
            if (
                self.auth_scheme is not None
                or self.request_path is not None
                or self.thinking_mode is not None
            ):
                raise ProviderConfigurationError()
            return

        # Kernel v1 不持久化 provider-specific opaque reasoning continuity。
        # 仅允许 OpenAI-compatible composition 显式请求关闭这类输出；默认不向
        # 其他兼容端点添加 vendor-specific 字段，也不允许启用无法安全回放的模式。
        if self.thinking_mode is not None and (
            provider_type != "openai_compatible" or self.thinking_mode != "disabled"
        ):
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
        if not request_path.startswith("/"):
            request_path = f"/{request_path}"
        object.__setattr__(self, "request_path", request_path)

    @property
    def endpoint(self) -> str:
        if self.provider_type == "fake" or self.base_url is None:
            raise ProviderConfigurationError()
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

__all__ = ["AgentProviderConfig", "SUPPORTED_PROVIDER_TYPES"]

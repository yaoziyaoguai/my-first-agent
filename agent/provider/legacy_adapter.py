"""⛔ DEPRECATED — Compatibility adapters around ModelProvider.

core/planner/memory compression 仍有少量历史代码期待 `client.messages.create`
形状。本模块提供薄 facade，把这些调用转发到 provider.create()，避免 core.py
继续直接创建 Anthropic SDK client。它不读取配置、不持有 secret 明文。

Deprecation plan: ProviderBackedClient / ProviderBackedMessages 的价值随
planner/compress 迁移到 provider-neutral create() 而递减。

Removal criteria: planner.py + memory.py compress_history 全部改为直接使用
provider.create() 后，本模块连同 ProviderBackedClient、ProviderBackedMessages
一并删除。
Sunset: v0.4+。
Why kept: planner/compress 尚未完全迁移到 provider-neutral 接口。
Not default path: 新代码直接使用 provider.create()，不要通过本模块。
"""

from __future__ import annotations

from typing import Any

from agent.provider.protocol import ProviderCapabilityError

_BASE_CREATE_ARGS = {"system", "messages", "tools"}
_SUPPORTED_CREATE_OVERRIDES = {"model", "max_tokens", "temperature"}


class ProviderBackedMessages:
    """把 legacy `messages.create()` 映射到 provider-neutral create()。

    planner/context/memory 仍有历史 Anthropic-style 调用形状。这里必须把
    支持的 per-call override 显式转发给 provider；未知 SDK 参数 fail closed，
    避免调用方误以为参数生效但实际被静默丢弃。
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def create(self, **kwargs: Any) -> Any:
        unsupported = set(kwargs) - _BASE_CREATE_ARGS - _SUPPORTED_CREATE_OVERRIDES
        if unsupported:
            raise ProviderCapabilityError("unsupported_legacy_message_args")

        provider_kwargs = {
            "system": kwargs.get("system", ""),
            "messages": kwargs.get("messages", []),
            "tools": kwargs.get("tools", []),
        }
        for name in _SUPPORTED_CREATE_OVERRIDES:
            if name in kwargs:
                provider_kwargs[name] = kwargs[name]
        return self._provider.create(
            **provider_kwargs,
        )


class ProviderBackedClient:
    """仅为旧 planner/compress 接口保留的 provider-backed client facade。"""

    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.messages = ProviderBackedMessages(provider)

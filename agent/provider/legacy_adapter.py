"""Compatibility adapters around ModelProvider.

core/planner/memory compression 仍有少量历史代码期待 `client.messages.create`
形状。本模块提供薄 adapter，把这些调用转发到 provider.create()，避免 core.py
继续直接创建 Anthropic SDK client。它不读取配置、不持有 secret 明文。
"""

from __future__ import annotations

from typing import Any


class ProviderBackedMessages:
    """把 legacy `messages.create()` 映射到 provider-neutral create()。"""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def create(self, **kwargs: Any) -> Any:
        return self._provider.create(
            system=kwargs.get("system", ""),
            messages=kwargs.get("messages", []),
            tools=kwargs.get("tools", []),
        )


class ProviderBackedClient:
    """仅为旧 planner/compress 接口保留的 provider-backed client facade。"""

    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.messages = ProviderBackedMessages(provider)

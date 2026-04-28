"""Configurable LLM provider abstraction for the processing MVP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None


@dataclass(frozen=True)
class LLMRequest:
    prompt_version: str
    input_text: str
    input_file_hash: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    tokens: int | None = None


class LLMProvider(Protocol):
    config: ProviderConfig

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a completion for the request."""


class FakeProvider:
    """Deterministic provider for tests and no-key local runs."""

    def __init__(self, model: str = "fake-llm") -> None:
        self.config = ProviderConfig(provider="fake", model=model)

    def complete(self, request: LLMRequest) -> LLMResponse:
        text = (
            f"{request.prompt_version}: processed "
            f"{request.input_file_hash[:12]}"
        )
        return LLMResponse(
            text=text,
            provider=self.config.provider,
            model=self.config.model,
            tokens=max(1, len(request.input_text.split())),
        )


class AnthropicProvider:
    """Anthropic implementation, enabled only by explicit configuration."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        base_url: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for anthropic")
        self.config = ProviderConfig(
            provider="anthropic",
            model=model,
            api_key=api_key,
            base_url=base_url,
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        from anthropic import Anthropic

        kwargs = {"api_key": self.config.api_key}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        client = Anthropic(**kwargs)
        response = client.messages.create(
            model=self.config.model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": _build_prompt(request),
                }
            ],
        )
        text_parts = [
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        return LLMResponse(
            text="\n".join(text_parts).strip(),
            provider=self.config.provider,
            model=self.config.model,
            tokens=input_tokens + output_tokens,
        )


def _build_prompt(request: LLMRequest) -> str:
    return (
        f"Prompt version: {request.prompt_version}\n"
        "Process the following text for the MVP pipeline. "
        "Return concise structured notes.\n\n"
        f"{request.input_text}"
    )


def build_provider(
    provider_name: str | None = None,
    *,
    model: str | None = None,
) -> LLMProvider:
    provider = (
        provider_name
        or os.getenv("MY_FIRST_AGENT_LLM_PROVIDER")
        or "fake"
    ).strip().lower()

    if provider == "fake":
        return FakeProvider(model=model or os.getenv("LLM_FAKE_MODEL", "fake-llm"))

    if provider == "anthropic":
        model_name = (
            model
            or os.getenv("ANTHROPIC_MODEL")
            or os.getenv("MODEL_NAME")
        )
        if not model_name:
            raise ValueError("ANTHROPIC_MODEL or MODEL_NAME is required")
        return AnthropicProvider(
            model=model_name,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            base_url=os.getenv("ANTHROPIC_BASE_URL"),
        )

    raise ValueError(f"Unknown LLM provider: {provider}")

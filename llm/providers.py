"""Configurable LLM provider abstraction for the processing MVP."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from llm.config import ProviderConfig, build_preflight_report, load_provider_config


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
    """按配置构造 provider；fake 是默认路径，真实 provider 必须显式配齐。

    ProviderConfig 里可能含有 api_key，只能交给 provider 客户端使用，不能写入
    state.json、runs/*.jsonl 或 CLI 输出。
    """

    config = load_provider_config(provider_name, model=model)

    if config.provider == "fake":
        return FakeProvider(model=config.model)

    if config.provider == "anthropic":
        return AnthropicProvider(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
        )

    raise ValueError(f"Unknown LLM provider: {config.provider}")


def preflight_provider(
    provider_name: str | None = None,
    *,
    model: str | None = None,
    live: bool = False,
) -> dict[str, object]:
    """执行 provider preflight，默认只做本地配置检查。

    `--live` 才会发真实请求；即便 live，也只记录 token/latency/status/error 摘要，
    不返回 prompt、completion、request body、response body 或 key。
    """

    report = build_preflight_report(provider_name, model=model, live=live)
    if not live:
        return report
    if report["status"] != "ok":
        return report

    started = time.perf_counter()
    try:
        provider = build_provider(provider_name, model=model)
        response = provider.complete(
            LLMRequest(
                prompt_version="preflight.v1",
                input_text="Provider connectivity preflight. Do not include secrets.",
                input_file_hash="preflight",
            )
        )
        report["live"] = {
            "enabled": True,
            "status": "ok",
            "tokens": response.tokens,
            "latency": int((time.perf_counter() - started) * 1000),
        }
        return report
    except Exception as exc:
        report["status"] = "error"
        report["live"] = {
            "enabled": True,
            "status": "error",
            "tokens": None,
            "latency": int((time.perf_counter() - started) * 1000),
            "error": exc.__class__.__name__,
        }
        errors = report.setdefault("errors", [])
        if isinstance(errors, list):
            errors.append(f"live_preflight_failed:{exc.__class__.__name__}")
        return report

"""固定 Tavily adapter 的 bounded typed results。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WebSearchHit:
    title: str
    url: str
    citation_locator: str
    content: str
    score: float | None = None


@dataclass(frozen=True, slots=True)
class WebSearchResponse:
    query: str
    results: tuple[WebSearchHit, ...]
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class WebExtractedPage:
    url: str
    citation_locator: str
    content: str
    request_id: str | None = None
    truncated: bool = False
    original_content_digest: str | None = None


__all__ = ["WebExtractedPage", "WebSearchHit", "WebSearchResponse"]

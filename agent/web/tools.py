"""Fixed Tavily client 的 governed Web Search/Extract registrations。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from agent.runtime.contracts import (
    ApprovalPolicy,
    EgressClass,
    ExecutionAuthorityClass,
    ExecutionIntent,
    OutputPolicy,
    SideEffectClass,
    SourceAuthorityBinding,
    SourceKind,
    SourceReceiptDraft,
    ToolExecutionOutput,
    ToolRisk,
    ToolSpec,
    canonical_json_digest,
)
from agent.runtime.tools import RegisteredTool
from agent.web.client import (
    TAVILY_EXTRACT_PATH,
    TAVILY_SEARCH_PATH,
    TavilyClient,
    WebAuthError,
    WebProtocolError,
    WebRateLimitError,
    WebServiceError,
    tavily_extract_payload,
    tavily_search_payload,
)
from agent.web.profile import TAVILY_TRUST_NOTICE, WebProfileV1
from agent.web.safety import admit_public_url

_SOURCE_REF_PREFIX = "source-ref:v1:"
_SOURCE_REF_LENGTH = len(_SOURCE_REF_PREFIX) + 64
_MAX_QUERY_CHARS = 1_000
_OUTPUT_LIMIT_CHARS = 50_000


def build_web_tool_registrations(
    client: TavilyClient,
    profile: WebProfileV1,
    *,
    clock: Callable[[], str],
) -> tuple[RegisteredTool, ...]:
    if client.profile != profile:
        raise ValueError("Tavily client and Web profile must match")

    def prepare_search(arguments):  # noqa: ANN001
        query = _validate_query(arguments.get("query"))
        max_results = _max_results(arguments, profile)
        payload = tavily_search_payload(query, max_results=max_results)
        cost_class = "tavily_search_basic_1_credit"
        request_identity = "tavily-search:v1:" + canonical_json_digest(
            {
                "profile_digest": profile.profile_digest,
                "query": query,
                "max_results": max_results,
            }
        )
        return {
            "operation": "tavily_search",
            "request_identity": request_identity,
            "destination_digest": _destination_digest(profile),
            "precondition_digest": profile.profile_digest,
            "cost_class": cost_class,
            "trust_notice_id": profile.trust_notice_id,
            "trust_notice_digest": profile.trust_notice_digest,
            "effect_preview": _effect_preview(
                summary=f"Send this exact public query to Tavily: {query}",
                destination=profile.destination + TAVILY_SEARCH_PATH,
                cost_class=cost_class,
                payload=payload,
            ),
        }

    def prepare_fetch(arguments):  # noqa: ANN001
        source_ref = _validate_source_ref(arguments.get("source_ref"))
        return {
            "operation": "tavily_extract",
            "request_identity": "tavily-extract:v1:"
            + canonical_json_digest(
                {
                    "profile_digest": profile.profile_digest,
                    "source_ref": source_ref,
                }
            ),
            "destination_digest": _destination_digest(profile),
            "precondition_digest": profile.profile_digest,
            "cost_class": "tavily_extract_basic_1_credit_per_5_urls",
            "trust_notice_id": profile.trust_notice_id,
            "trust_notice_digest": profile.trust_notice_digest,
        }

    return (
        RegisteredTool(
            spec=_search_spec(profile),
            prepare_binding=prepare_search,
            func=lambda intent: _search_output(client, profile, intent, clock=clock),
        ),
        RegisteredTool(
            spec=_fetch_spec(profile),
            prepare_binding=prepare_fetch,
            prepare_authority_binding=lambda arguments, authority: (
                _prepare_fetch_authority(
                    arguments,
                    authority,
                    profile=profile,
                )
            ),
            func=lambda intent: _fetch_output(client, intent, clock=clock),
        ),
    )


def _search_output(
    client: TavilyClient,
    profile: WebProfileV1,
    intent: ExecutionIntent,
    *,
    clock: Callable[[], str],
) -> ToolExecutionOutput:
    query = _validate_query(intent.arguments.get("query"))
    max_results = _max_results(intent.arguments, profile)
    try:
        response = client.search(query, max_results=max_results)
    except (WebAuthError, WebRateLimitError, WebProtocolError, WebServiceError) as error:
        return _known_failure(error)
    observed_at = _observed_at(clock)
    rendered: list[dict[str, object]] = []
    receipts: list[SourceReceiptDraft] = []
    for hit in response.results:
        item: dict[str, object] = {
            "title": hit.title,
            "url": hit.url,
            "locator": hit.citation_locator,
            "snippet": hit.content,
            "score": hit.score,
        }
        receipt_content = _canonical_json(item)
        rendered.append(item)
        receipts.append(
            SourceReceiptDraft(
                source_kind=SourceKind.WEB_SEARCH_SNIPPET,
                origin_locator=hit.citation_locator,
                content=receipt_content,
                observed_at=observed_at,
                request_identity=intent.request_identity,
                origin_request_digest=hashlib.sha256(
                    hit.url.encode("utf-8")
                ).hexdigest(),
                title=hit.title,
            )
        )
    return ToolExecutionOutput(
        content=_canonical_json({"query": query, "results": rendered}),
        metadata={
            "query_digest": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "result_count": len(rendered),
        },
        source_receipts=tuple(receipts),
    )


def _fetch_output(
    client: TavilyClient,
    intent: ExecutionIntent,
    *,
    clock: Callable[[], str],
) -> ToolExecutionOutput:
    authority = intent.source_authority
    if authority is None:
        raise ValueError("Runtime source authority is required")
    try:
        page = client.extract(authority.canonical_url)
    except (WebAuthError, WebRateLimitError, WebProtocolError, WebServiceError) as error:
        return _known_failure(error)
    return ToolExecutionOutput(
        content=_canonical_json(
            {
                "locator": page.citation_locator,
                "content": page.content,
            }
        ),
        metadata={"content_chars": len(page.content)},
        source_receipts=(
            SourceReceiptDraft(
                source_kind=SourceKind.WEB_EXTRACTED_CONTENT,
                origin_locator=page.citation_locator,
                content=page.content,
                observed_at=_observed_at(clock),
                request_identity=intent.request_identity,
                origin_request_digest=hashlib.sha256(
                    page.url.encode("utf-8")
                ).hexdigest(),
                original_content_digest=page.original_content_digest,
                truncated=page.truncated,
                truncation_reason=("source_content_limit" if page.truncated else None),
            ),
        ),
    )


def _known_failure(error: Exception) -> ToolExecutionOutput:
    code = {
        WebAuthError: "web_auth",
        WebRateLimitError: "web_rate_limit",
        WebProtocolError: "web_protocol",
        WebServiceError: "web_service",
    }[type(error)]
    return ToolExecutionOutput(
        content=f"Tavily request failed with classified outcome: {code}.",
        metadata={"code": code},
        is_error=True,
        executed=True,
    )


def _search_spec(profile: WebProfileV1) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="web_search",
        version="1.0.0",
        description=(
            "Search the public Web through fixed Tavily Search. Every exact query "
            "requires user approval and is handled by a third party."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": _MAX_QUERY_CHARS},
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": profile.max_results,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        risk=ToolRisk.MEDIUM,
        side_effect=SideEffectClass.READ_ONLY,
        egress=EgressClass.PUBLIC_NETWORK,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={
            "enabled": True,
            "kind": "fixed_tavily_search",
            "profile_digest": profile.profile_digest,
            "source_metadata_keys": ["query_digest", "result_count", "code"],
        },
        output_limit_chars=_OUTPUT_LIMIT_CHARS,
        source_kinds=(SourceKind.WEB_SEARCH_SNIPPET,),
    )


def _fetch_spec(profile: WebProfileV1) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="web_fetch",
        version="1.0.0",
        description=(
            "Extract one public source previously returned by web_search. Accepts only "
            "a Runtime-issued opaque source_ref listed in "
            "FIRST_AGENT_RUNTIME_WEB_FETCH_REFS and requires separate approval."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "source_ref": {
                    "type": "string",
                    "minLength": _SOURCE_REF_LENGTH,
                    "maxLength": _SOURCE_REF_LENGTH,
                }
            },
            "required": ["source_ref"],
            "additionalProperties": False,
        },
        risk=ToolRisk.MEDIUM,
        side_effect=SideEffectClass.READ_ONLY,
        egress=EgressClass.PUBLIC_NETWORK,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={
            "enabled": True,
            "kind": "fixed_tavily_extract",
            "profile_digest": profile.profile_digest,
            "source_authority_required": True,
            "source_metadata_keys": ["content_chars", "code"],
        },
        output_limit_chars=_OUTPUT_LIMIT_CHARS,
        source_kinds=(SourceKind.WEB_EXTRACTED_CONTENT,),
    )


def _validate_query(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_QUERY_CHARS
        or any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in value)
    ):
        raise ValueError("Web query is empty, oversized, or contains control characters")
    return value


def _max_results(arguments: dict, profile: WebProfileV1) -> int:  # noqa: ANN001
    value = arguments.get("max_results", profile.max_results)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= profile.max_results
    ):
        raise ValueError("max_results exceeds the configured Web profile")
    return value


def _validate_source_ref(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SOURCE_REF_LENGTH
        or not value.startswith(_SOURCE_REF_PREFIX)
        or any(ch not in "0123456789abcdef" for ch in value[len(_SOURCE_REF_PREFIX) :])
    ):
        raise ValueError("source_ref is not a canonical Runtime reference")
    return value


def _prepare_fetch_authority(
    arguments: dict,
    authority: SourceAuthorityBinding,
    *,
    profile: WebProfileV1,
) -> dict[str, object]:
    source_ref = _validate_source_ref(arguments.get("source_ref"))
    if source_ref != _SOURCE_REF_PREFIX + authority.receipt_digest:
        raise ValueError("source authority does not match source_ref")
    canonical_url = admit_public_url(authority.canonical_url)
    cost_class = "tavily_extract_basic_1_credit_per_5_urls"
    payload = tavily_extract_payload(
        canonical_url,
        timeout_seconds=profile.timeout_seconds,
    )
    return {
        "source_authority_digest": authority.binding_digest,
        "approved_url": canonical_url,
        "target_digest": hashlib.sha256(canonical_url.encode("utf-8")).hexdigest(),
        "effect_preview": _effect_preview(
            summary=(
                "Send this exact approved public source URL to Tavily: "
                f"{canonical_url}"
            ),
            destination=profile.destination + TAVILY_EXTRACT_PATH,
            cost_class=cost_class,
            payload=payload,
        ),
    }


def _effect_preview(
    *,
    summary: str,
    destination: str,
    cost_class: str,
    payload: dict[str, object],
) -> str:
    return (
        f"{summary}\n"
        f"Destination: {destination}\n"
        f"Cost class: {cost_class}\n"
        f"Credential-free request payload: {_canonical_json(payload)}\n"
        f"Third-party handling notice: {TAVILY_TRUST_NOTICE}"
    )


def _destination_digest(profile: WebProfileV1) -> str:
    return hashlib.sha256(profile.destination.encode("utf-8")).hexdigest()


def _observed_at(clock: Callable[[], str]) -> str:
    value = clock()
    if not isinstance(value, str) or not value:
        raise ValueError("Web observation clock returned an invalid value")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["build_web_tool_registrations"]

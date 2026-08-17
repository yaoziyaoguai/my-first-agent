from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import httpx
import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRunStatus,
    ApprovalGrant,
    ApprovalRequired,
    ConversationFact,
    ConversationState,
    ExecutionIntent,
    FactKind,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    RecoverUnknownObservation,
    ResolveApproval,
    RunStatus,
    SourceAuthorityBinding,
    SubmitMessage,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from agent.web.client import TavilyClient
from agent.web.profile import TAVILY_DESTINATION, WebProfileV1
from agent.web.tools import build_web_tool_registrations
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


def _profile() -> WebProfileV1:
    return WebProfileV1(
        credential_env="FIRST_AGENT_WEB_API_KEY",
        timeout_seconds=10.0,
        max_results=3,
    )


def _context(*, source_authority=None) -> ToolPrepareContext:  # noqa: ANN001
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-web",
        state_revision=1,
        approval_basis_revision=1,
        source_authority=source_authority,
    )


def test_web_search_requires_exact_approval_before_any_network_send() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "query": "bounded public query",
                "results": [
                    {
                        "title": "Source",
                        "url": "https://example.com/article?view=public",
                        "content": "Public snippet",
                        "score": 0.8,
                    }
                ],
                "response_time": "0.1",
                "request_id": "search-request",
            },
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        runtime = KernelToolRuntime(
            build_web_tool_registrations(
                TavilyClient(_profile(), api_key="secret-value", http_client=http_client),
                _profile(),
                clock=lambda: "2026-08-04T00:00:00Z",
            )
        )
        call = ToolCall(
            "search-1",
            "web_search",
            {"query": "bounded public query", "max_results": 2},
        )
        pending = runtime.prepare(call, _context())

        assert isinstance(pending, ApprovalRequired)
        assert requests == []
        assert pending.request.egress == "public_network"
        assert pending.request.operation == "tavily_search"
        assert pending.request.destination_digest == hashlib.sha256(
            TAVILY_DESTINATION.encode()
        ).hexdigest()
        assert "bounded public query" in pending.request.preview
        assert f"Destination: {TAVILY_DESTINATION}/search" in pending.request.preview
        assert "Cost class: tavily_search_basic_1_credit" in pending.request.preview
        assert (
            'Credential-free request payload: {"auto_parameters":false,'
            '"include_answer":false,"include_images":false,'
            '"include_raw_content":false,"max_results":2,'
            '"query":"bounded public query","search_depth":"basic"}'
            in pending.request.preview
        )
        intent = runtime.prepare(
            call,
            _context(),
            approval=ApprovalGrant(
                pending.request.request_id,
                pending.request.binding_digest,
                approval_basis_revision=1,
            ),
        )
        assert isinstance(intent, ExecutionIntent)
        result = runtime.invoke(intent)

    assert len(requests) == 1
    assert result.is_error is False
    assert result.metadata["source_receipts"][0]["source_kind"] == "web_search_snippet"
    receipt = result.metadata["source_receipts"][0]
    assert receipt["origin_locator"] == "https://example.com/article"
    assert receipt["origin_request_digest"] == hashlib.sha256(
        b"https://example.com/article?view=public"
    ).hexdigest()
    assert result.metadata["source_refs"][0]["source_ref"].startswith("source-ref:v1:")
    assert "secret-value" not in result.content


def test_web_fetch_requires_current_source_authority_and_approves_exact_url() -> None:
    requests: list[httpx.Request] = []
    full_url = "https://example.com/article?view=public"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "results": [{"url": full_url, "raw_content": "Extracted text"}],
                "failed_results": [],
                "response_time": 0.1,
                "request_id": "extract-request",
            },
        )

    authority = SourceAuthorityBinding.create(
        source_fact_id="fact-search-result",
        receipt_digest="a" * 64,
        conversation_id="conversation-1",
        request_identity="search-request-identity",
        canonical_url=full_url,
    )
    source_ref = "source-ref:v1:" + "a" * 64
    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        runtime = KernelToolRuntime(
            build_web_tool_registrations(
                TavilyClient(_profile(), api_key="secret-value", http_client=http_client),
                _profile(),
                clock=lambda: "2026-08-04T00:00:00Z",
            )
        )
        call = ToolCall("fetch-1", "web_fetch", {"source_ref": source_ref})
        denied = runtime.prepare(call, _context())
        assert denied.metadata["code"] == "source_authority_required"
        assert requests == []

        pending = runtime.prepare(call, _context(source_authority=authority))
        assert isinstance(pending, ApprovalRequired)
        assert full_url in pending.request.preview
        assert f"Destination: {TAVILY_DESTINATION}/extract" in pending.request.preview
        assert (
            "Cost class: tavily_extract_basic_1_credit_per_5_urls"
            in pending.request.preview
        )
        assert (
            'Credential-free request payload: {"extract_depth":"basic",'
            '"format":"text","include_images":false,"timeout":10.0,'
            '"urls":["https://example.com/article?view=public"]}'
            in pending.request.preview
        )
        assert pending.request.target_digest == hashlib.sha256(full_url.encode()).hexdigest()
        intent = runtime.prepare(
            call,
            _context(source_authority=authority),
            approval=ApprovalGrant(
                pending.request.request_id,
                pending.request.binding_digest,
                approval_basis_revision=1,
            ),
        )
        assert isinstance(intent, ExecutionIntent)
        result = runtime.invoke(intent)

    assert len(requests) == 1
    assert requests[0].url.host == "api.tavily.com"
    payload = json.loads(result.content)
    assert payload["locator"] == "https://example.com/article"
    assert payload["content"] == "Extracted text"
    assert result.metadata["source_receipts"][0]["source_kind"] == (
        "web_extracted_content"
    )


def test_runtime_recovers_full_approved_url_from_digest_bound_search_result() -> None:
    full_url = "https://example.com/article?view=public"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "query": "bounded public query",
                "results": [
                    {
                        "title": "Source",
                        "url": full_url,
                        "content": "Public snippet",
                        "score": 0.8,
                    }
                ],
                "response_time": "0.1",
                "request_id": "search-request",
            },
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        runtime = KernelToolRuntime(
            build_web_tool_registrations(
                TavilyClient(_profile(), api_key="secret-value", http_client=http_client),
                _profile(),
                clock=lambda: "2026-08-04T00:00:00Z",
            )
        )
        call = ToolCall(
            "search-authority",
            "web_search",
            {"query": "bounded public query", "max_results": 1},
        )
        pending = runtime.prepare(call, _context())
        assert isinstance(pending, ApprovalRequired)
        intent = runtime.prepare(
            call,
            _context(),
            approval=ApprovalGrant(
                pending.request.request_id,
                pending.request.binding_digest,
                approval_basis_revision=1,
            ),
        )
        assert isinstance(intent, ExecutionIntent)
        result = runtime.invoke(intent)

    source_ref = result.metadata["source_refs"][0]["source_ref"]
    fact = ConversationFact(
        fact_id="fact-search-result",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": result.tool_call_id,
            "text": result.content,
            "is_error": False,
            "executed": True,
            "metadata": result.metadata,
        },
    )
    state = replace(ConversationState.new("conversation-1"), facts=(fact,))

    authority = AgentRuntime._source_authority_for(  # noqa: SLF001
        state,
        ToolCall("fetch-authority", "web_fetch", {"source_ref": source_ref}),
    )

    assert authority is not None
    assert authority.canonical_url == full_url

    tampered_fact = ConversationFact(
        fact_id=fact.fact_id,
        kind=fact.kind,
        content={
            **fact.content,
            "text": fact.content["text"].replace("view=public", "view=tampered"),
        },
    )
    tampered_state = replace(state, facts=(tampered_fact,))
    assert (
        AgentRuntime._source_authority_for(  # noqa: SLF001
            tampered_state,
            ToolCall("fetch-tampered", "web_fetch", {"source_ref": source_ref}),
        )
        is None
    )


def test_model_runtime_approval_client_result_and_next_context_e2() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "query": "bounded public query",
                "results": [
                    {
                        "title": "Source",
                        "url": "https://example.com/article",
                        "content": "Public snippet",
                        "score": 0.8,
                    }
                ],
                "response_time": "0.1",
                "request_id": "search-request",
            },
        )

    provider = ScriptedProvider(
        ModelResponse(
            (
                ModelToolCall(
                    "search-e2",
                    "web_search",
                    {"query": "bounded public query", "max_results": 1},
                ),
            )
        ),
        ModelResponse((ModelTextBlock("Grounded answer."),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        runtime = AgentRuntime(
            provider=provider,
            context_manager=KernelContextManager(
                system_policy="policy",
                limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
            ),
            tool_runtime=KernelToolRuntime(
                build_web_tool_registrations(
                    TavilyClient(
                        _profile(),
                        api_key="secret-value",
                        http_client=http_client,
                    ),
                    _profile(),
                    clock=lambda: "2026-08-04T00:00:00Z",
                )
            ),
            checkpoint_store=store,
            event_sink=CollectingSink(),
            limits=InvocationLimits(),
        )
        pending = runtime.run_turn(
            SubmitMessage(
                conversation_id="conversation-1",
                action_seq=1,
                expected_revision=0,
                run_id="run-web-e2",
                message="Research the bounded public query.",
            ),
            store.load(),
        )

        assert pending.status is RunStatus.AWAITING_APPROVAL
        assert pending.request is not None
        assert requests == []
        completed = runtime.run_turn(
            ResolveApproval(
                conversation_id="conversation-1",
                action_seq=store.state.next_action_seq,
                expected_revision=store.state.revision,
                request_id=pending.request.request_id,
                binding_digest=pending.request.binding_digest,
                approved=True,
            ),
            store.load(),
        )

    assert completed.status is RunStatus.COMPLETED
    assert completed.message == "Grounded answer."
    assert len(requests) == 1
    assert len(provider.calls) == 2
    assert "public_web_content" in provider.calls[1].data_classes
    source_blocks = [
        block
        for message in provider.calls[1].messages
        for block in message.content
        if block.get("type") == "tool_result"
    ]
    assert source_blocks and source_blocks[0]["untrusted"] is True


@pytest.mark.parametrize("failure_kind", ["timeout", "transport"])
def test_web_unknown_outcome_uses_real_tavily_runtime_path_without_resend(
    failure_kind: str,
) -> None:
    """真实 Tavily transport unknown 经 Runtime 恢复，用户继续时绝不重发。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure_kind == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        raise httpx.ConnectError("connection failed", request=request)

    provider = ScriptedProvider(
        ModelResponse(
            (
                ModelToolCall(
                    "search-unknown",
                    "web_search",
                    {"query": "bounded public query", "max_results": 1},
                ),
            )
        ),
        ModelResponse((ModelTextBlock("Continued without retry."),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-unknown"))
    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        runtime = AgentRuntime(
            provider=provider,
            context_manager=KernelContextManager(
                system_policy="policy",
                limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
            ),
            tool_runtime=KernelToolRuntime(
                build_web_tool_registrations(
                    TavilyClient(
                        _profile(),
                        api_key="secret-value",
                        http_client=http_client,
                    ),
                    _profile(),
                    clock=lambda: "2026-08-04T00:00:00Z",
                )
            ),
            checkpoint_store=store,
            event_sink=CollectingSink(),
            limits=InvocationLimits(),
            invocation_id_factory=lambda: "invocation-unknown",
        )
        pending = runtime.run_turn(
            SubmitMessage(
                conversation_id="conversation-unknown",
                action_seq=1,
                expected_revision=0,
                run_id="run-unknown",
                message="Search once.",
            ),
            store.load(),
        )
        assert pending.status is RunStatus.AWAITING_APPROVAL
        paused = runtime.run_turn(
            ResolveApproval(
                conversation_id="conversation-unknown",
                action_seq=store.state.next_action_seq,
                expected_revision=store.state.revision,
                request_id=pending.request.request_id,
                binding_digest=pending.request.binding_digest,
                approved=True,
            ),
            store.load(),
        )
        assert paused.status is RunStatus.AWAITING_RECOVERY
        assert store.state.active_run is not None
        assert store.state.active_run.status is ActiveRunStatus.AWAITING_RECOVERY
        executing = store.state.active_run.executing_intent
        assert executing is not None
        assert len(requests) == 1
        assert len(provider.calls) == 1

        completed = runtime.run_turn(
            RecoverUnknownObservation(
                conversation_id="conversation-unknown",
                action_seq=store.state.next_action_seq,
                expected_revision=store.state.revision,
                tool_call_id=executing.tool_call_id,
                intent_digest=executing.intent_digest,
            ),
            store.load(),
        )

    assert completed.status is RunStatus.COMPLETED
    assert len(requests) == 1
    assert len(provider.calls) == 2


def test_profile_drift_invalidates_pending_approval_with_zero_network_send() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    first_profile = _profile()
    changed_profile = WebProfileV1(
        credential_env="FIRST_AGENT_WEB_API_KEY",
        timeout_seconds=11.0,
        max_results=3,
    )
    call = ToolCall(
        "search-drift",
        "web_search",
        {"query": "bounded public query", "max_results": 1},
    )
    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        first = KernelToolRuntime(
            build_web_tool_registrations(
                TavilyClient(
                    first_profile,
                    api_key="secret-value",
                    http_client=http_client,
                ),
                first_profile,
                clock=lambda: "2026-08-04T00:00:00Z",
            )
        )
        pending = first.prepare(call, _context())
        assert isinstance(pending, ApprovalRequired)
        changed = KernelToolRuntime(
            build_web_tool_registrations(
                TavilyClient(
                    changed_profile,
                    api_key="secret-value",
                    http_client=http_client,
                ),
                changed_profile,
                clock=lambda: "2026-08-04T00:00:00Z",
            )
        )
        rejected = changed.prepare(
            call,
            _context(),
            approval=ApprovalGrant(
                pending.request.request_id,
                pending.request.binding_digest,
                approval_basis_revision=1,
            ),
        )

    assert rejected.is_error is True
    assert rejected.executed is False
    assert rejected.metadata["code"] == "approval_mismatch"
    assert requests == []

"""Sub-agent pre-audit guardrails for post-memory hardening."""

from __future__ import annotations

from typing import Any

from agent.provider.protocol import ProviderResponse, ProviderTextBlock
from agent.subagent_system.context import SubAgentContextPackage
from agent.subagent_system.executor import execute_l2
from agent.subagent_system.request import SubAgentRequest


class _Provider:
    provider_type = "spy"
    supports_tools = True
    supports_streaming = False

    def create(self, **_kwargs) -> ProviderResponse:
        return ProviderResponse(
            content=[ProviderTextBlock(
                text='{"batch_memory": [{"key": "raw_key", '
                     '"value": "RAW_BATCH_MEMORY_VALUE", "scope": "project"}]}'
            )],
            stop_reason="end_turn",
            raw_provider_name="spy",
        )


class _Mediator:
    def __init__(self) -> None:
        self.child_memory_requests: list[dict[str, Any]] = []
        self.store_writes: list[dict[str, Any]] = []

    def mediate_child_memory_request(self, **kwargs) -> str:
        self.child_memory_requests.append(dict(kwargs))
        return "deferred"


class _Descriptor:
    name = "test-agent"
    role = "tester"
    allowed_tools = ()
    max_iterations_default = 2
    risk_level = "low"


def _context() -> SubAgentContextPackage:
    request = SubAgentRequest(
        task="research",
        role="tester",
        allowed_tools=(),
        parent_trace_id="parent",
        memory_scope="propose",
        delegation_reason="test",
    )
    return SubAgentContextPackage(
        request=request,
        descriptor=_Descriptor(),
        task="research",
        role_prompt="",
        goal="research",
        constraints=(),
        relevant_files=(),
        relevant_summaries=(),
        selected_memory_context=None,
        selected_skill_metadata=(),
        allowed_tools=(),
        allowed_skills=(),
        forbidden_actions=(),
        output_schema=None,
        max_context_chars=100_000,
        max_iterations=2,
        stop_conditions=(),
        execution_mode="real_llm_tool_requesting",
    )


def test_l2_batch_memory_remains_deferred_via_mediator_not_store_write() -> None:
    mediator = _Mediator()

    result = execute_l2(
        _context(),
        provider=_Provider(),
        tool_mediator=mediator,
        delegation_id="delegation",
    )

    assert len(result.batch_memory_proposals) == 1
    assert mediator.child_memory_requests
    assert mediator.store_writes == []
    assert result.audit.memory_proposals_count == 1


def test_no_parent_adjudication_or_second_runtime_loop_claim_is_introduced() -> None:
    mediator = _Mediator()

    result = execute_l2(
        _context(),
        provider=_Provider(),
        tool_mediator=mediator,
        delegation_id="delegation",
    )

    assert not hasattr(result, "parent_adjudication")
    assert result.audit.execution_mode == "real_llm_tool_requesting"
    assert "second_runtime" not in str(result.audit).lower()

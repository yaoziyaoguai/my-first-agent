from __future__ import annotations

from agent.provider.normalize import (
    context_to_anthropic_messages,
    context_to_openai_messages,
    validate_context_pack,
)
from agent.runtime.contracts import (
    BudgetReport,
    ContextPack,
    ModelMessage,
)


def _pack_with_context_block() -> ContextPack:
    block = {
        "type": "context",
        "untrusted": True,
        "source": "memory",
        "candidate_id": "rec-123",
        "digest": "abc123def456",
        "text": (
            "[untrusted memory from memory id=rec-123 digest=abc123de] "
            "the deploy token is CANARY"
        ),
    }
    return ContextPack(
        system="system policy",
        messages=(
            ModelMessage(role="user", content=({"type": "text", "text": "deploy how"},)),
            ModelMessage(role="user", content=(block,)),
        ),
        tools=(),
        budget=BudgetReport(input_limit=1000, estimated_input_tokens=10, output_reserve=100),
    )


def test_both_adapters_project_untrusted_context_without_network() -> None:
    """A17: the provider-neutral untrusted ``context`` block must be accepted and projected
    as clearly-marked, non-system user text by both adapters without losing
    source/id/digest/untrusted markers.
    """
    pack = _pack_with_context_block()
    validate_context_pack(pack)  # must not raise unsupported_context_block

    anthropic = context_to_anthropic_messages(pack)
    openai = context_to_openai_messages(pack)

    for projected, label in ((anthropic, "anthropic"), (openai, "openai")):
        blob = repr(projected)
        assert "CANARY" in blob, f"{label}: content lost"
        assert "untrusted" in blob, f"{label}: untrusted marker lost"
        assert "rec-123" in blob, f"{label}: candidate id lost"
        assert "abc123de" in blob or "abc123def456" in blob, f"{label}: digest lost"
        assert "memory" in blob, f"{label}: source lost"
        # context block 必须投影为 user 文本，绝不进入 system。
        for message in projected:
            if "CANARY" in repr(message.get("content", "")):
                assert message["role"] != "system", f"{label}: context leaked into system"

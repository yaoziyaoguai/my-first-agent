"""014 workspace grounding 的 stop-ship 架构合同。"""

from __future__ import annotations

from dataclasses import fields

import agent.runtime.contracts as contracts


def test_014_closed_source_and_egress_contracts_are_materialized() -> None:
    """来源与外发必须是 Kernel 可校验的 closed types，不能由工具自报。"""

    egress_class = getattr(contracts, "EgressClass", None)
    assert egress_class is not None, "014 requires the closed EgressClass contract"
    assert tuple(item.value for item in egress_class) == ("none", "public_network")

    source_kind = getattr(contracts, "SourceKind", None)
    assert source_kind is not None, "014 requires the closed SourceKind contract"
    assert {item.value for item in source_kind} == {
        "history_excerpt",
        "history_goal",
        "history_evidence",
        "workspace_path",
        "workspace_excerpt",
        "web_search_snippet",
        "web_extracted_content",
    }

    assert "research_provenance" in {
        item.value for item in contracts.EvidenceOracleKind
    }


def test_014_network_recovery_action_has_exact_identity_binding() -> None:
    recovery = getattr(contracts, "RecoverUnknownObservation", None)
    assert recovery is not None, "014 requires typed PUBLIC_NETWORK recovery"
    assert tuple(field.name for field in fields(recovery)) == (
        "conversation_id",
        "action_seq",
        "expected_revision",
        "tool_call_id",
        "intent_digest",
    )

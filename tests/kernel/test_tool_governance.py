"""Runtime 拥有的 citation 工具治理：KernelToolRuntime 内部治理 seam 的裁决接口。

KernelToolRuntime.prepare 仍是唯一外部接口与最终权限/effect gate；这里直接
覆盖 citation intent preparation 的裁决语义（sidecar 写入 canonical 化、
manifest builder 准入门、binding 失败映射），集成行为由
tests/continuity/test_research_evidence.py 经 prepare() 端到端覆盖。
"""

from __future__ import annotations

import hashlib

from agent.runtime.contracts import (
    CitationManifestV1,
    CitationV1,
    JSONValue,
    SideEffectClass,
    ToolPrepareContext,
)
from agent.runtime.tool_governance import CitationGovernance

GOAL_ID = "goal-governance-1"
GOAL_REVISION = 1
ARTIFACT_PATH = "reports/report.md"
MANIFEST_PATH = "reports/report.md.citations.json"
SOURCE_REF = "source-ref:v1:" + "a" * 64
SOURCE_ID = "source:v1:" + "b" * 64

BUILDER_POLICY: dict[str, JSONValue] = {"kind": "citation_manifest_builder"}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest() -> CitationManifestV1:
    return CitationManifestV1.create(
        artifact_path=ARTIFACT_PATH,
        artifact_sha256=_sha("artifact text"),
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
        citations=(CitationV1("[H1]", SOURCE_ID, "c" * 64),),
    )


def _context(**overrides) -> ToolPrepareContext:  # noqa: ANN001
    values: dict[str, object] = {
        "conversation_id": "conversation-governance",
        "run_id": "run-governance",
        "state_revision": 1,
        "goal_id": GOAL_ID,
        "goal_revision": GOAL_REVISION,
        "workspace_identity_digest": "workspace-governance",
        "citation_manifest_allowed": True,
        "citation_sidecar_paths": (MANIFEST_PATH,),
        "citation_artifact_paths": (ARTIFACT_PATH,),
        "citable_source_refs": (SOURCE_REF,),
        "citable_citation_sources": ((SOURCE_REF, SOURCE_ID),),
    }
    values.update(overrides)
    return ToolPrepareContext(**values)


def test_sidecar_write_is_canonicalized_to_runtime_manifest() -> None:
    """exact Runtime manifest + 单个 transport newline → canonical 参数重写。"""

    governance = CitationGovernance()
    canonical = _manifest().to_json()

    ruling = governance.assess_intent(
        tool_name="write_file",
        side_effect=SideEffectClass.WRITE,
        safety_policy={},
        arguments={"path": MANIFEST_PATH, "content": canonical + "\n"},
        context=_context(citation_manifest_content_digests=(_sha(canonical),)),
    )

    assert ruling.rejection is None
    assert ruling.canonical_arguments == {"path": MANIFEST_PATH, "content": canonical}


def test_handwritten_sidecar_write_is_rejected_with_builder_steps() -> None:
    """手写 sidecar 在 effect 前被拒，并教 build_citation_manifest 重建程序。"""

    governance = CitationGovernance()

    ruling = governance.assess_intent(
        tool_name="write_file",
        side_effect=SideEffectClass.WRITE,
        safety_policy={},
        arguments={"path": MANIFEST_PATH, "content": '{"citations":[]}'},
        context=_context(citable_citation_sources=((SOURCE_REF, SOURCE_ID),)),
    )

    assert ruling.canonical_arguments is None
    assert ruling.rejection is not None
    assert ruling.rejection.code == "citation_manifest_required"
    assert "build_citation_manifest" in ruling.rejection.message
    assert SOURCE_REF in ruling.rejection.message
    assert SOURCE_ID in ruling.rejection.message


def test_non_citation_tools_and_plain_writes_pass_through_unchanged() -> None:
    governance = CitationGovernance()

    read_ruling = governance.assess_intent(
        tool_name="read_file",
        side_effect=SideEffectClass.READ_ONLY,
        safety_policy={},
        arguments={"path": "notes.txt"},
        context=_context(),
    )
    plain_write_ruling = governance.assess_intent(
        tool_name="write_file",
        side_effect=SideEffectClass.WRITE,
        safety_policy={},
        arguments={"path": ARTIFACT_PATH, "content": "plain text"},
        context=_context(),
    )

    for ruling in (read_ruling, plain_write_ruling):
        assert ruling.rejection is None
        assert ruling.canonical_arguments is None


def test_manifest_builder_requires_goal_sidecar_target() -> None:
    governance = CitationGovernance()

    ruling = governance.assess_intent(
        tool_name="build_citation_manifest",
        side_effect=SideEffectClass.READ_ONLY,
        safety_policy=BUILDER_POLICY,
        arguments={"artifact_path": ARTIFACT_PATH},
        context=_context(citation_manifest_allowed=False),
    )

    assert ruling.canonical_arguments is None
    assert ruling.rejection is not None
    assert ruling.rejection.code == "citation_manifest_not_required"


def test_manifest_builder_rejects_unauthorized_artifact() -> None:
    governance = CitationGovernance()

    ruling = governance.assess_intent(
        tool_name="build_citation_manifest",
        side_effect=SideEffectClass.READ_ONLY,
        safety_policy=BUILDER_POLICY,
        arguments={"artifact_path": "other/report.md"},
        context=_context(),
    )

    assert ruling.rejection is not None
    assert ruling.rejection.code == "citation_artifact_not_authorized"
    assert ARTIFACT_PATH in ruling.rejection.message


def test_manifest_builder_rejects_stale_goal_identity() -> None:
    governance = CitationGovernance()

    ruling = governance.assess_intent(
        tool_name="build_citation_manifest",
        side_effect=SideEffectClass.READ_ONLY,
        safety_policy=BUILDER_POLICY,
        arguments={
            "artifact_path": ARTIFACT_PATH,
            "goal_id": "goal-stale",
            "goal_revision": GOAL_REVISION,
        },
        context=_context(),
    )

    assert ruling.rejection is not None
    assert ruling.rejection.code == "citation_goal_identity_mismatch"


def test_manifest_builder_rejects_source_ref_outside_citable_set() -> None:
    governance = CitationGovernance()

    ruling = governance.assess_intent(
        tool_name="build_citation_manifest",
        side_effect=SideEffectClass.READ_ONLY,
        safety_policy=BUILDER_POLICY,
        arguments={
            "artifact_path": ARTIFACT_PATH,
            "goal_id": GOAL_ID,
            "goal_revision": GOAL_REVISION,
            "citations": [
                {
                    "marker": "[H1]",
                    "source_ref": "source-ref:v1:" + "d" * 64,
                    "source_id": "source:v1:" + "e" * 64,
                }
            ],
        },
        context=_context(citable_citation_sources=((SOURCE_REF, SOURCE_ID),)),
    )

    assert ruling.rejection is not None
    assert ruling.rejection.code == "citation_source_not_citable"
    assert SOURCE_REF in ruling.rejection.message


def test_manifest_builder_rejects_duplicate_pairs() -> None:
    governance = CitationGovernance()
    citations = [
        {"marker": "[H1]", "source_ref": SOURCE_REF, "source_id": SOURCE_ID},
        {"marker": "[H2]", "source_ref": SOURCE_REF, "source_id": SOURCE_ID},
    ]

    ruling = governance.assess_intent(
        tool_name="build_citation_manifest",
        side_effect=SideEffectClass.READ_ONLY,
        safety_policy=BUILDER_POLICY,
        arguments={
            "artifact_path": ARTIFACT_PATH,
            "goal_id": GOAL_ID,
            "goal_revision": GOAL_REVISION,
            "citations": citations,
        },
        context=_context(citable_citation_sources=((SOURCE_REF, SOURCE_ID),)),
    )

    assert ruling.rejection is not None
    assert ruling.rejection.code == "citation_entries_not_one_to_one"


def test_manifest_builder_accepts_exact_citable_pair() -> None:
    governance = CitationGovernance()

    ruling = governance.assess_intent(
        tool_name="build_citation_manifest",
        side_effect=SideEffectClass.READ_ONLY,
        safety_policy=BUILDER_POLICY,
        arguments={
            "artifact_path": ARTIFACT_PATH,
            "goal_id": GOAL_ID,
            "goal_revision": GOAL_REVISION,
            "citations": [
                {"marker": "[H1]", "source_ref": SOURCE_REF, "source_id": SOURCE_ID}
            ],
        },
        context=_context(citable_citation_sources=((SOURCE_REF, SOURCE_ID),)),
    )

    assert ruling.rejection is None
    assert ruling.canonical_arguments is None


def test_binding_failure_maps_only_manifest_builder_kind() -> None:
    """citation binding 失败映射归治理模块;非 builder 工具保持通用兜底。"""

    governance = CitationGovernance()

    rejection = governance.binding_failure(BUILDER_POLICY)
    assert rejection is not None
    assert rejection.code == "citation_manifest_invalid"
    assert "structurally invalid" in rejection.message

    assert governance.binding_failure({}) is None


# --- Source governance：governed source preparation 门与 outcome 归一 ---
# 函数级 import：SourceGovernance 尚未实现时只让本节 Red，citation 节不受影响。


def _source_spec(**overrides):  # noqa: ANN001
    from agent.runtime.contracts import (
        ApprovalPolicy,
        ExecutionAuthorityClass,
        OutputPolicy,
        SideEffectClass,
        SourceKind,
        ToolRisk,
        ToolSpec,
    )

    values: dict[str, object] = {
        "execution_authority": ExecutionAuthorityClass.IN_PROCESS,
        "name": "source_fixture",
        "version": "1",
        "description": "Return one bounded source fixture.",
        "input_schema": {"type": "object"},
        "risk": ToolRisk.LOW,
        "side_effect": SideEffectClass.READ_ONLY,
        "output_policy": OutputPolicy.BOUNDED_TEXT,
        "approval_policy": ApprovalPolicy.NEVER,
        "safety_policy": {"source_metadata_keys": ["count"]},
        "output_limit_chars": 2_000,
        "source_kinds": (SourceKind.WORKSPACE_EXCERPT,),
    }
    values.update(overrides)
    return ToolSpec(**values)


def _source_intent():
    from agent.runtime.contracts import (
        ExecutionAuthorityClass,
        ExecutionIntent,
        InvocationOrigin,
        SideEffectClass,
    )

    return ExecutionIntent(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        tool_call_id="source-governance-1",
        tool_name="source_fixture",
        tool_identity="fixture-identity",
        arguments={},
        arguments_digest="a" * 64,
        intent_digest="b" * 64,
        idempotency_key="conversation-governance:run-governance:source-governance-1",
        policy_identity="fixture-policy",
        conversation_id="conversation-governance",
        run_id="run-governance",
        side_effect=SideEffectClass.READ_ONLY,
        invocation_origin=InvocationOrigin.MODEL,
    )


def test_source_authority_gate_requires_runtime_verified_web_ref() -> None:
    from agent.runtime.contracts import SourceAuthorityBinding
    from agent.runtime.tool_governance import SourceGovernance

    governance = SourceGovernance()
    permitted = "source-ref:v1:" + "a" * 64
    authority = SourceAuthorityBinding.create(
        source_fact_id="fact:source:1",
        receipt_digest="b" * 64,
        conversation_id="conversation-governance",
        request_identity="request-1",
        canonical_url="https://example.com",
    )

    rejection = governance.assess_authority(
        authority_required=True,
        arguments={"source_ref": "source-ref:v1:" + "c" * 64},
        context=_context(
            source_authority=authority,
            web_fetch_source_refs=(permitted,),
        ),
    )
    assert rejection is not None
    assert rejection.code == "source_authority_required"
    assert permitted in rejection.message

    assert (
        governance.assess_authority(
            authority_required=True,
            arguments={"source_ref": permitted},
            context=_context(
                source_authority=authority,
                web_fetch_source_refs=(permitted,),
            ),
        )
        is None
    )
    assert (
        governance.assess_authority(
            authority_required=False,
            arguments={},
            context=_context(),
        )
        is None
    )


def test_source_result_rejects_invalid_output_contract() -> None:
    from agent.runtime.contracts import ToolResult
    from agent.runtime.tool_governance import SourceGovernance

    result = SourceGovernance().normalize_result(
        _source_intent(),
        _source_spec(),
        "a plain string is not a source output contract",
    )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert result.executed is True
    assert result.metadata["code"] == "source_output_required"


def test_source_result_rejects_unauthorized_metadata() -> None:
    from agent.runtime.contracts import ToolExecutionOutput
    from agent.runtime.tool_governance import SourceGovernance

    result = SourceGovernance().normalize_result(
        _source_intent(),
        _source_spec(),
        ToolExecutionOutput(
            content="ok",
            metadata={"secret_key": "leak"},
        ),
    )

    assert result.is_error is True
    assert result.executed is True
    assert result.metadata["code"] == "source_metadata_invalid"


def test_source_result_rejects_unauthorized_source_kind() -> None:
    from agent.runtime.contracts import (
        SourceKind,
        SourceReceiptDraft,
        ToolExecutionOutput,
    )
    from agent.runtime.tool_governance import SourceGovernance

    result = SourceGovernance().normalize_result(
        _source_intent(),
        _source_spec(),
        ToolExecutionOutput(
            content="ok",
            source_receipts=(
                SourceReceiptDraft(
                    source_kind=SourceKind.WEB_SEARCH_SNIPPET,
                    origin_locator="https://example.com",
                    content="snippet",
                    observed_at="2026-08-26T00:00:00Z",
                    request_identity="request-1",
                ),
            ),
        ),
    )

    assert result.is_error is True
    assert result.executed is True
    assert result.metadata["code"] == "source_kind_invalid"


def test_source_result_mints_runtime_receipts_and_refs() -> None:
    from agent.runtime.contracts import (
        SourceKind,
        SourceReceiptDraft,
        ToolExecutionOutput,
        ToolResult,
    )
    from agent.runtime.tool_governance import SourceGovernance

    draft = SourceReceiptDraft(
        source_kind=SourceKind.WORKSPACE_EXCERPT,
        origin_locator="constraints.txt#L1",
        content="bounded workspace content",
        observed_at="2026-08-26T00:00:00Z",
        snapshot_digest="d" * 64,
    )
    result = SourceGovernance().normalize_result(
        _source_intent(),
        _source_spec(),
        ToolExecutionOutput(
            content="bounded workspace content",
            metadata={"count": 1},
            source_receipts=(draft,),
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.is_error is False
    assert result.content == "bounded workspace content"
    receipts = result.metadata["source_receipts"]
    assert len(receipts) == 1
    assert receipts[0]["receipt_digest"]
    assert receipts[0]["source_kind"] == "workspace_excerpt"
    assert result.metadata["data_classes"] == ["workspace_excerpt"]
    refs = result.metadata["source_refs"]
    assert refs[0]["receipt_digest"] == receipts[0]["receipt_digest"]
    assert result.metadata["truncated"] is False
    assert result.metadata["tool_identity"] == _source_spec().identity_digest


def _workspace_draft(locator: str = "constraints.txt#L1"):  # noqa: ANN001
    from agent.runtime.contracts import SourceKind, SourceReceiptDraft

    return SourceReceiptDraft(
        source_kind=SourceKind.WORKSPACE_EXCERPT,
        origin_locator=locator,
        content="bounded content",
        observed_at="2026-08-26T00:00:00Z",
        snapshot_digest="d" * 64,
    )


def _expect_source_rejection(spec, output, code) -> None:  # noqa: ANN001
    from agent.runtime.tool_governance import SourceGovernance

    result = SourceGovernance().normalize_result(_source_intent(), spec, output)
    assert result.is_error is True
    assert result.executed is True
    assert result.metadata["code"] == code


def test_source_result_rejects_oversized_content() -> None:
    from agent.runtime.contracts import ToolExecutionOutput

    _expect_source_rejection(
        _source_spec(output_limit_chars=2),
        ToolExecutionOutput(content="toolong"),
        "source_output_oversized",
    )


def test_source_result_rejects_malformed_metadata_policy() -> None:
    from agent.runtime.contracts import ToolExecutionOutput

    _expect_source_rejection(
        _source_spec(safety_policy={"source_metadata_keys": "count"}),
        ToolExecutionOutput(content="ok"),
        "source_metadata_policy_invalid",
    )


def test_source_result_rejects_oversized_metadata() -> None:
    from agent.runtime.contracts import ToolExecutionOutput

    _expect_source_rejection(
        _source_spec(output_limit_chars=8),
        ToolExecutionOutput(content="ok", metadata={"count": 1}),
        "source_metadata_oversized",
    )


def test_source_result_rejects_too_many_receipts() -> None:
    from agent.runtime.contracts import ToolExecutionOutput

    _expect_source_rejection(
        _source_spec(),
        ToolExecutionOutput(
            content="ok",
            source_receipts=tuple(
                _workspace_draft(f"constraints.txt#L{index}") for index in range(17)
            ),
        ),
        "source_receipts_oversized",
    )


def test_source_result_rejects_oversized_receipt_draft() -> None:
    from agent.runtime.contracts import ToolExecutionOutput

    _expect_source_rejection(
        _source_spec(output_limit_chars=8),
        ToolExecutionOutput(
            content="ok",
            source_receipts=(_workspace_draft("l" * 9),),
        ),
        "source_receipt_oversized",
    )

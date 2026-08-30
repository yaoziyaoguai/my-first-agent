from __future__ import annotations

import hashlib
from dataclasses import asdict, replace

import pytest

from agent.research.tools import build_research_tool_registrations
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActionDisposition,
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalGrant,
    ApprovalRequest,
    ApprovalRequired,
    CitationManifestV1,
    CitationV1,
    CompletionClaim,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    ExecutionIntent,
    FactKind,
    GoalDelta,
    GoalFrame,
    GoalStatus,
    InvocationOrigin,
    ModelResponse,
    ProposedCriterion,
    ResolveApproval,
    RunStatus,
    SideEffectClass,
    SourceKind,
    SourceReceiptDraft,
    SourceReceiptV1,
    SubmitMessage,
    ToolCall,
    ToolDefinition,
    ToolPrepareContext,
    ToolResult,
    canonical_json_digest,
    closed_evidence_id,
)
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import (
    accept_action,
    admit_web_source_criterion,
    apply_goal_delta,
)
from agent.runtime.tools import KernelToolRuntime
from agent.tools.file_ops import build_file_tool_registrations
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    goal_noop_response,
)

GOAL_ID = "goal-research-1"
GOAL_REVISION = 1
ARTIFACT_PATH = "reports/report.md"
MANIFEST_PATH = "reports/report.md.citations.json"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _intent(index: int, *, goal_id: str = GOAL_ID) -> ExecutionIntent:
    return ExecutionIntent(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        tool_call_id=f"source-{index}",
        tool_name="source_fixture",
        tool_identity="fixture-identity",
        arguments={},
        arguments_digest="a" * 64,
        intent_digest=hex(index)[2:].rjust(64, "b")[-64:],
        idempotency_key=f"conversation-1:run-research:source-{index}",
        policy_identity="fixture-policy",
        conversation_id="conversation-1",
        run_id="run-research",
        side_effect=SideEffectClass.READ_ONLY,
        invocation_origin=InvocationOrigin.MODEL,
        goal_id=goal_id,
        goal_revision=GOAL_REVISION,
        workspace_identity_digest="workspace-1",
    )


def _receipt(
    index: int,
    kind: SourceKind,
    locator: str,
    *,
    goal_id: str = GOAL_ID,
    observed_at: str = "2026-08-04T00:00:00Z",
    truncated: bool = False,
) -> SourceReceiptV1:
    identity = (
        {"snapshot_digest": _sha(f"snapshot-{index}")}
        if not kind.value.startswith("web_")
        else {"request_identity": f"request-{index}"}
    )
    return SourceReceiptV1.create(
        SourceReceiptDraft(
            source_kind=kind,
            origin_locator=locator,
            content=f"source content {index}",
            observed_at=observed_at,
            original_content_digest=(_sha(f"full-{index}") if truncated else None),
            truncated=truncated,
            truncation_reason=("source_content_limit" if truncated else None),
            **identity,
        ),
        _intent(index, goal_id=goal_id),
    )


def _source_fact(index: int, receipt: SourceReceiptV1, *, fake: bool = False):  # noqa: ANN001
    metadata = {
        "data_classes": [receipt.data_class],
        "source_receipts": [
            {**asdict(receipt), "source_kind": receipt.source_kind.value}
        ],
        "source_refs": [
            {
                "source_ref": f"source-ref:v1:{receipt.receipt_digest}",
                "receipt_digest": receipt.receipt_digest,
            }
        ],
    }
    if fake:
        metadata["fake"] = True
    return ConversationFact(
        fact_id=f"fact:source:{index}",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": f"source-{index}",
            "text": f"source content {index}",
            "is_error": False,
            "executed": True,
            "metadata": metadata,
        },
    )


def _read_facts(path: str, content: str, index: int) -> tuple[ConversationFact, ...]:
    call_id = f"read-{index}"
    return (
        ConversationFact(
            fact_id=f"fact:calls:{index}",
            kind=FactKind.TOOL_CALLS,
            content={
                "calls": [
                    {
                        "tool_call_id": call_id,
                        "name": "read_file",
                        "arguments": {"path": path},
                    }
                ]
            },
        ),
        ConversationFact(
            fact_id=f"fact:read:{index}",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": call_id,
                "text": content,
                "is_error": False,
                "executed": True,
                "metadata": {},
            },
        ),
    )


def _goal(criterion: AdmittedCriterion) -> GoalFrame:
    return GoalFrame(
        goal_id=GOAL_ID,
        revision=GOAL_REVISION,
        created_from_fact_ids=("action:1:user",),
        workspace_identity_digest="workspace-1",
        user_outcome="Create a three-source grounded report and citation sidecar",
        beneficiary="user",
        targets=(ARTIFACT_PATH, MANIFEST_PATH),
        scope=("workspace", "history", "public_web"),
        non_goals=("do not publish",),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                "criterion-proposed",
                "grounded report is delivered",
                oracle_kind=EvidenceOracleKind.RESEARCH_PROVENANCE,
            ),
        ),
        admitted_criteria=(criterion,),
        authority_snapshot="authority-1",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-04T00:00:00Z",
        updated_at="2026-08-04T00:00:00Z",
    )


def _fixture(
    *,
    web_kind: SourceKind = SourceKind.WEB_EXTRACTED_CONTENT,
    web_goal_id: str = GOAL_ID,
    artifact: str | None = None,
    minimum_sources: int = 3,
    observed_after: str | None = None,
    fake_source: bool = False,
):  # noqa: ANN201
    receipts = (
        _receipt(1, SourceKind.HISTORY_EXCERPT, "history:decision-1"),
        _receipt(2, SourceKind.WORKSPACE_EXCERPT, "constraints.txt#L1"),
        _receipt(
            3,
            web_kind,
            "https://example.com/article",
            goal_id=web_goal_id,
        ),
    )
    artifact = artifact or (
        "Past decision [H1].\nCurrent constraint [W1].\n"
        "Public fact [WEB1] (https://example.com/article).\n"
    )
    manifest = CitationManifestV1.create(
        artifact_path=ARTIFACT_PATH,
        artifact_sha256=_sha(artifact),
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
        citations=tuple(
            CitationV1(marker, receipt.source_id, receipt.receipt_digest)
            for marker, receipt in zip(("[H1]", "[W1]", "[WEB1]"), receipts, strict=True)
        ),
    )
    predicate = {
        "artifact_path": ARTIFACT_PATH,
        "artifact_sha256": _sha(artifact),
        "manifest_path": MANIFEST_PATH,
        "manifest_sha256": _sha(manifest.to_json()),
        "manifest_digest": manifest.manifest_digest,
        "minimum_distinct_sources": minimum_sources,
        "required_source_kinds": ["web_extracted_content"],
        "required_source_classes": ["history", "workspace"],
        "required_receipt_digests": [],
    }
    if observed_after is not None:
        predicate["observed_after"] = observed_after
    criterion = AdmittedCriterion(
        criterion_id="criterion-research",
        description="three-source provenance is linked to exact read-back",
        source_fact_id="action:1:user",
        oracle_kind=EvidenceOracleKind.RESEARCH_PROVENANCE,
        predicate=predicate,
        required_evidence_class="research_provenance",
        admission_digest=canonical_json_digest(predicate),
    )
    facts = (
        ConversationFact(
            fact_id="action:1:user",
            kind=FactKind.USER_MESSAGE,
            content={"text": "Create the grounded report"},
        ),
        *(
            _source_fact(index, receipt, fake=fake_source and index == 2)
            for index, receipt in enumerate(receipts, start=1)
        ),
        *_read_facts(ARTIFACT_PATH, artifact, 10),
        *_read_facts(MANIFEST_PATH, manifest.to_json(), 11),
    )
    state = replace(
        ConversationState.new("conversation-1"),
        revision=1,
        next_action_seq=2,
        facts=facts,
        goal=_goal(criterion),
    )
    claim = CompletionClaim(
        correlation_id="completion-research",
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
        criterion_evidence_refs=(
            closed_evidence_id(GOAL_ID, GOAL_REVISION, criterion.criterion_id),
        ),
    )
    return state, claim, manifest


def test_citation_manifest_is_canonical_and_digest_bound() -> None:
    _state, _claim, manifest = _fixture()

    assert CitationManifestV1.from_json(manifest.to_json()) == manifest
    assert manifest.to_json() == manifest.to_json().strip()
    assert manifest.to_json().startswith('{"artifact_path"')

    tampered = manifest.to_json().replace(ARTIFACT_PATH, "reports/other.md", 1)
    with pytest.raises(ValueError, match="digest"):
        CitationManifestV1.from_json(tampered)


def test_web_fetch_schema_lists_only_unattempted_current_run_search_refs() -> None:
    state, _claim, _manifest = _fixture()
    receipts = (
        _receipt(21, SourceKind.WEB_SEARCH_SNIPPET, "https://example.com/one"),
        _receipt(22, SourceKind.WEB_SEARCH_SNIPPET, "https://example.com/two"),
    )
    search_groups: list[ConversationFact] = []
    for index, receipt in enumerate(receipts, start=21):
        search_groups.extend(
            (
                ConversationFact(
                    fact_id=f"run:run-research:search-calls:{index}",
                    kind=FactKind.TOOL_CALLS,
                    content={
                        "calls": [
                            {
                                "tool_call_id": f"source-{index}",
                                "name": "web_search",
                                "arguments": {"query": f"query-{index}"},
                            }
                        ]
                    },
                ),
                replace(
                    _source_fact(index, receipt),
                    fact_id=f"run:run-research:search-result:{index}",
                ),
            )
        )
    first_ref = f"source-ref:v1:{receipts[0].receipt_digest}"
    second_ref = f"source-ref:v1:{receipts[1].receipt_digest}"
    attempted_group = (
        ConversationFact(
            fact_id="run:run-research:fetch-calls:23",
            kind=FactKind.TOOL_CALLS,
            content={
                "calls": [
                    {
                        "tool_call_id": "fetch-23",
                        "name": "web_fetch",
                        "arguments": {"source_ref": first_ref},
                    }
                ]
            },
        ),
        ConversationFact(
            fact_id="run:run-research:fetch-result:23",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "fetch-23",
                "text": "already fetched",
                "is_error": False,
                "executed": True,
                "metadata": {},
            },
        ),
    )
    state = replace(
        state,
        facts=(state.facts[0], *search_groups, *attempted_group),
        active_run=ActiveRun("run-research"),
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-research",
        message="continue",
    )
    fetch_tool = ToolDefinition(
        name="web_fetch",
        description="fetch",
        input_schema={
            "type": "object",
            "properties": {"source_ref": {"type": "string"}},
            "required": ["source_ref"],
            "additionalProperties": False,
        },
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )

    pack = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
    ).build(state, action, (fetch_tool,))

    assert pack.tools[0].input_schema["properties"]["source_ref"]["enum"] == [
        second_ref
    ]
    guidance = AgentRuntime._duplicate_product_request_guidance(
        state,
        ToolCall("fetch-again", "web_fetch", {"source_ref": first_ref}),
    )
    assert "unattempted" in guidance
    assert second_ref in guidance


def test_citation_manifest_schema_excludes_search_snippets_and_truncated_sources() -> None:
    state, _claim, _manifest = _fixture()
    usable = _receipt(31, SourceKind.WEB_EXTRACTED_CONTENT, "https://example.com/usable")
    truncated = _receipt(
        32,
        SourceKind.WEB_EXTRACTED_CONTENT,
        "https://example.com/large",
        truncated=True,
    )
    snippet = _receipt(33, SourceKind.WEB_SEARCH_SNIPPET, "https://example.com/snippet")
    state = replace(
        state,
        facts=(
            state.facts[0],
            _source_fact(31, usable),
            _source_fact(32, truncated),
            _source_fact(33, snippet),
        ),
        active_run=ActiveRun("run-research"),
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-research",
        message="continue",
    )
    spec = build_research_tool_registrations()[0].spec
    tool = ToolDefinition(
        name=spec.name,
        description=spec.description,
        input_schema=spec.input_schema,
        execution_authority=spec.execution_authority,
    )

    pack = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
    ).build(state, action, (tool,))

    assert "generic Runtime source frames include non-citable refs" in (
        pack.tools[0].description
    )
    item_schema = pack.tools[0].input_schema["properties"]["citations"]["items"]
    assert len(item_schema["anyOf"]) == 1
    source_ref_schema = item_schema["anyOf"][0]["properties"]["source_ref"]
    source_id_schema = item_schema["anyOf"][0]["properties"]["source_id"]
    assert source_ref_schema["enum"] == [
        f"source-ref:v1:{usable.receipt_digest}"
    ]
    assert source_id_schema["enum"] == [usable.source_id]
    assert pack.tools[0].input_schema["properties"]["artifact_path"]["enum"] == [
        ARTIFACT_PATH
    ]


def test_citation_manifest_schema_keeps_runtime_source_pairs_correlated() -> None:
    state, _claim, _manifest = _fixture()
    first = _receipt(35, SourceKind.WEB_EXTRACTED_CONTENT, "https://example.com/first")
    second = _receipt(36, SourceKind.WEB_EXTRACTED_CONTENT, "https://example.com/second")
    state = replace(
        state,
        facts=(state.facts[0], _source_fact(35, first), _source_fact(36, second)),
        active_run=ActiveRun("run-research"),
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-research",
        message="continue",
    )
    spec = build_research_tool_registrations()[0].spec
    tool = ToolDefinition(
        name=spec.name,
        description=spec.description,
        input_schema=spec.input_schema,
        execution_authority=spec.execution_authority,
    )

    pack = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
    ).build(state, action, (tool,))

    assert f"source-ref:v1:{first.receipt_digest} -> {first.source_id}" in (
        pack.tools[0].description
    )
    assert f"source-ref:v1:{second.receipt_digest} -> {second.source_id}" in (
        pack.tools[0].description
    )
    item_schema = pack.tools[0].input_schema["properties"]["citations"]["items"]
    pairs = {
        (
            branch["properties"]["source_ref"]["enum"][0],
            branch["properties"]["source_id"]["enum"][0],
        )
        for branch in item_schema["anyOf"]
    }
    assert pairs == {
        (f"source-ref:v1:{first.receipt_digest}", first.source_id),
        (f"source-ref:v1:{second.receipt_digest}", second.source_id),
    }
    assert all(
        branch["required"] == ["marker", "source_ref", "source_id"]
        and branch["additionalProperties"] is False
        for branch in item_schema["anyOf"]
    )


def test_citation_manifest_tool_is_hidden_when_goal_has_no_sidecar_target() -> None:
    state, _claim, _manifest = _fixture()
    assert state.goal is not None
    usable = _receipt(34, SourceKind.WEB_EXTRACTED_CONTENT, "https://example.com/usable")
    state = replace(
        state,
        goal=replace(state.goal, targets=(ARTIFACT_PATH,)),
        facts=(state.facts[0], _source_fact(34, usable)),
        active_run=ActiveRun("run-research"),
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-research",
        message="continue",
    )
    spec = build_research_tool_registrations()[0].spec
    tool = ToolDefinition(
        name=spec.name,
        description=spec.description,
        input_schema=spec.input_schema,
        execution_authority=spec.execution_authority,
    )

    pack = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
    ).build(state, action, (tool,))

    assert all(item.name != "build_citation_manifest" for item in pack.tools)


def test_public_web_requirement_exposes_web_and_workspace_reads_until_receipt() -> None:
    state, _claim, _manifest = _fixture()
    assert state.goal is not None
    web_requirement = ProposedCriterion(
        "criterion-public-web",
        "public Web material was actually retrieved",
        oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
    )
    state = replace(
        state,
        goal=replace(
            state.goal,
            proposed_criteria=(*state.goal.proposed_criteria, web_requirement),
        ),
        facts=(state.facts[0],),
        active_run=ActiveRun("run-research"),
    )
    tools = (
        ToolDefinition(
            name="web_search",
            description="search",
            input_schema={"type": "object"},
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        ),
        ToolDefinition(
            name="write_file",
            description="write",
            input_schema={"type": "object"},
            side_effect=SideEffectClass.WRITE,
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        ),
        ToolDefinition(
            name="history_search",
            description="history",
            input_schema={"type": "object"},
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        ),
        ToolDefinition(
            name="read_file",
            description="read",
            input_schema={"type": "object"},
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        ),
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-research",
        message="continue",
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=20_000, output_reserve=500),
    )

    before = manager.build(state, action, tools)
    receipt = _receipt(
        35,
        SourceKind.WEB_SEARCH_SNIPPET,
        "https://example.com/public",
    )
    after = manager.build(
        replace(state, facts=(*state.facts, _source_fact(35, receipt))),
        action,
        tools,
    )
    admitted = admit_web_source_criterion(
        replace(state, facts=(*state.facts, _source_fact(35, receipt))),
        tool_call_id="source-35",
        action_seq=state.next_action_seq,
    )
    carried = manager.build(
        replace(admitted, goal=replace(admitted.goal, revision=2)),
        action,
        tools,
    )

    assert {tool.name for tool in before.tools} == {"read_file", "web_search"}
    assert {tool.name for tool in after.tools} == {
        "history_search",
        "read_file",
        "web_search",
        "write_file",
    }
    assert {tool.name for tool in carried.tools} == {
        "history_search",
        "read_file",
        "web_search",
        "write_file",
    }


def test_successful_web_receipt_admits_and_proves_proposed_requirement() -> None:
    state, _claim, _manifest = _fixture()
    assert state.goal is not None
    requirement = ProposedCriterion(
        "criterion-public-web",
        "public Web material was actually retrieved",
        oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
    )
    state = replace(
        state,
        goal=replace(
            state.goal,
            proposed_criteria=(*state.goal.proposed_criteria, requirement),
        ),
    )

    admitted = admit_web_source_criterion(
        state,
        tool_call_id="source-3",
        action_seq=state.next_action_seq,
    )
    web_criterion = next(
        item
        for item in admitted.goal.admitted_criteria
        if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
    )
    claim = CompletionClaim(
        correlation_id="completion-with-web",
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
        criterion_evidence_refs=tuple(
            closed_evidence_id(GOAL_ID, GOAL_REVISION, item.criterion_id)
            for item in admitted.goal.admitted_criteria
        ),
    )

    records = ClosedEvidenceRegistry().derive(
        admitted,
        claim,
        observed_at="2026-08-04T01:00:00Z",
    )

    assert web_criterion.predicate == {
        "receipt_digest": _receipt(
            3,
            SourceKind.WEB_EXTRACTED_CONTENT,
            "https://example.com/article",
        ).receipt_digest,
        "source_kind": SourceKind.WEB_EXTRACTED_CONTENT.value,
    }
    assert any(
        record.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
        and record.passed
        for record in records
    )


def test_satisfied_web_requirement_survives_goal_path_correction() -> None:
    state, _claim, _manifest = _fixture()
    assert state.goal is not None
    requirement = ProposedCriterion(
        "criterion-public-web",
        "public Web material was actually retrieved",
        oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
    )
    state = replace(
        state,
        goal=replace(
            state.goal,
            targets=(ARTIFACT_PATH,),
            proposed_criteria=(requirement,),
            admitted_criteria=(),
        ),
        facts=(state.facts[0], state.facts[3]),
    )
    admitted = admit_web_source_criterion(
        state,
        tool_call_id="source-3",
        action_seq=state.next_action_seq,
    )

    corrected = apply_goal_delta(
        admitted,
        GoalDelta(
            goal_id=GOAL_ID,
            expected_revision=GOAL_REVISION,
            reason="deliver to a corrected path",
            updates={
                "targets": ["reports/final.md"],
                "proposed_criteria": [
                    {
                        "criterion_id": "final-file",
                        "description": "corrected file exists",
                        "oracle_kind": "filesystem_digest",
                        "artifact_path": "reports/final.md",
                    }
                ],
            },
        ),
    )
    assert corrected.goal is not None
    web_criterion = next(
        item
        for item in corrected.goal.admitted_criteria
        if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
    )
    claim = CompletionClaim(
        correlation_id="completion-carried-web",
        goal_id=GOAL_ID,
        goal_revision=2,
        criterion_evidence_refs=(
            closed_evidence_id(GOAL_ID, 2, web_criterion.criterion_id),
        ),
    )
    evidence_state = replace(
        corrected,
        goal=replace(
            corrected.goal,
            proposed_criteria=tuple(
                item
                for item in corrected.goal.proposed_criteria
                if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
            ),
            admitted_criteria=(web_criterion,),
        ),
    )

    records = ClosedEvidenceRegistry().derive(
        evidence_state,
        claim,
        observed_at="2026-08-04T02:00:00Z",
    )

    assert any(
        item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
        for item in corrected.goal.proposed_criteria
    )
    assert records[0].passed is True


def test_outcome_correction_keeps_web_obligation_but_invalidates_old_admission() -> None:
    state, _claim, _manifest = _fixture()
    assert state.goal is not None
    requirement = ProposedCriterion(
        "criterion:required-public-web:outcome-correction",
        "public Web material was actually retrieved",
        oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
    )
    state = replace(
        state,
        goal=replace(
            state.goal,
            proposed_criteria=(requirement,),
            admitted_criteria=(),
        ),
        facts=(state.facts[0], state.facts[3]),
    )
    admitted = admit_web_source_criterion(
        state,
        tool_call_id="source-3",
        action_seq=state.next_action_seq,
    )

    corrected = apply_goal_delta(
        admitted,
        GoalDelta(
            goal_id=GOAL_ID,
            expected_revision=GOAL_REVISION,
            reason="user changed the requested conclusion",
            updates={"user_outcome": "write a different evidence-based conclusion"},
        ),
    )

    assert corrected.goal is not None
    assert requirement in corrected.goal.proposed_criteria
    assert corrected.goal.admitted_criteria == ()


def test_scope_correction_keeps_web_obligation_but_invalidates_old_admission() -> None:
    state, _claim, _manifest = _fixture()
    assert state.goal is not None
    requirement = ProposedCriterion(
        "criterion:required-public-web:scope-correction",
        "public Web material was actually retrieved",
        oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
    )
    state = replace(
        state,
        goal=replace(
            state.goal,
            proposed_criteria=(requirement,),
            admitted_criteria=(),
        ),
        facts=(state.facts[0], state.facts[3]),
    )
    admitted = admit_web_source_criterion(
        state,
        tool_call_id="source-3",
        action_seq=state.next_action_seq,
    )

    corrected = apply_goal_delta(
        admitted,
        GoalDelta(
            goal_id=GOAL_ID,
            expected_revision=GOAL_REVISION,
            reason="user expanded the evidence scope",
            updates={"scope": ["workspace", "release-information"]},
        ),
    )

    assert corrected.goal is not None
    assert requirement in corrected.goal.proposed_criteria
    assert corrected.goal.admitted_criteria == ()


def test_tool_runtime_rejects_effect_while_public_web_requirement_is_pending(
    tmp_path,
) -> None:  # noqa: ANN001
    runtime = KernelToolRuntime(build_file_tool_registrations(tmp_path))
    result = runtime.prepare(
        ToolCall(
            "write-before-web",
            "write_file",
            {"path": "report.md", "content": "not grounded yet\n"},
        ),
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            public_web_requirement_pending=True,
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "public_web_source_required"
    assert not (tmp_path / "report.md").exists()


def test_build_citation_manifest_tool_only_builds_canonical_contract() -> None:
    registrations = build_research_tool_registrations()
    properties = registrations[0].spec.input_schema["properties"]
    assert "artifact_content" in properties
    assert "artifact_sha256" not in properties
    artifact_description = properties["artifact_content"]["description"]
    assert "read_file ToolResult" in artifact_description
    assert "final newline" in artifact_description
    assert "Every literal http(s) URL" in artifact_description
    assert "web_extracted_content receipt origin_locator" in artifact_description
    citation_schema = registrations[0].spec.input_schema["properties"]["citations"]
    citation_properties = citation_schema["items"]["properties"]
    assert "including square brackets" in citation_properties["marker"]["description"]
    assert "copy unchanged" in citation_properties["source_ref"]["description"]
    assert "copy unchanged" in citation_properties["source_id"]["description"]
    assert citation_schema == {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "marker": {
                    "type": "string",
                    "description": (
                        "Exact bracketed marker present in artifact_content, including "
                        "square brackets, for example [H1]."
                    ),
                },
                "source_ref": {
                    "type": "string",
                    "description": (
                        "Opaque source_ref from FIRST_AGENT_RUNTIME_SOURCE_REFS; copy "
                        "unchanged."
                    ),
                },
                "source_id": {
                    "type": "string",
                    "description": (
                        "Opaque paired source_id from FIRST_AGENT_RUNTIME_SOURCE_REFS; "
                        "copy unchanged."
                    ),
                },
            },
            "required": ["marker", "source_ref", "source_id"],
            "additionalProperties": False,
        },
    }
    runtime = KernelToolRuntime(registrations)
    call = ToolCall(
        "manifest-build",
        "build_citation_manifest",
        {
            "artifact_path": ARTIFACT_PATH,
            "artifact_content": "grounded report\n",
            "goal_id": GOAL_ID,
            "goal_revision": GOAL_REVISION,
            "citations": [
                {
                    "marker": "[S1]",
                    "source_ref": "source-ref:v1:" + "c" * 64,
                    "source_id": "source:v1:" + "b" * 64,
                }
            ],
        },
    )
    intent = runtime.prepare(
        call,
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            citable_source_refs=("source-ref:v1:" + "c" * 64,),
            citable_citation_sources=(
                ("source-ref:v1:" + "c" * 64, "source:v1:" + "b" * 64),
            ),
            citation_manifest_allowed=True,
            citation_artifact_paths=(ARTIFACT_PATH,),
        ),
    )
    assert isinstance(intent, ExecutionIntent)

    result = runtime.invoke(intent)

    assert result.is_error is False
    manifest = CitationManifestV1.from_json(result.content)
    assert manifest.artifact_path == ARTIFACT_PATH
    assert manifest.artifact_sha256 == _sha("grounded report\n")
    assert manifest.citations[0].receipt_digest == "c" * 64
    assert manifest.manifest_digest in result.content


def test_manifest_builder_rejects_source_ref_outside_runtime_citable_set() -> None:
    runtime = KernelToolRuntime(build_research_tool_registrations())
    allowed_ref = "source-ref:v1:" + "a" * 64
    call = ToolCall(
        "manifest-denied",
        "build_citation_manifest",
        {
            "artifact_path": ARTIFACT_PATH,
            "artifact_content": "grounded [S1]\n",
            "goal_id": GOAL_ID,
            "goal_revision": GOAL_REVISION,
            "citations": [
                {
                    "marker": "[S1]",
                    "source_ref": "source-ref:v1:" + "b" * 64,
                    "source_id": "source:v1:" + "c" * 64,
                }
            ],
        },
    )

    result = runtime.prepare(
        call,
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            citable_source_refs=(allowed_ref,),
            citable_citation_sources=((allowed_ref, "source:v1:" + "d" * 64),),
            citation_manifest_allowed=True,
            citation_artifact_paths=(ARTIFACT_PATH,),
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "citation_source_not_citable"
    assert "non-truncated" in result.content
    assert "only permitted" in result.content
    assert allowed_ref in result.content
    assert "source:v1:" + "d" * 64 in result.content


def test_manifest_builder_rejects_mismatched_runtime_source_pair() -> None:
    runtime = KernelToolRuntime(build_research_tool_registrations())
    allowed_ref = "source-ref:v1:" + "a" * 64
    allowed_source_id = "source:v1:" + "b" * 64
    result = runtime.prepare(
        ToolCall(
            "manifest-mismatched-pair",
            "build_citation_manifest",
            {
                "artifact_path": ARTIFACT_PATH,
                "artifact_content": "grounded [S1]\n",
                "goal_id": GOAL_ID,
                "goal_revision": GOAL_REVISION,
                "citations": [
                    {
                        "marker": "[S1]",
                        "source_ref": allowed_ref,
                        "source_id": "source:v1:" + "c" * 64,
                    }
                ],
            },
        ),
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            citable_source_refs=(allowed_ref,),
            citable_citation_sources=((allowed_ref, allowed_source_id),),
            citation_manifest_allowed=True,
            citation_artifact_paths=(ARTIFACT_PATH,),
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "citation_source_not_citable"
    assert allowed_ref in result.content
    assert allowed_source_id in result.content


def test_manifest_builder_rejects_duplicate_pairs_with_recovery_instruction() -> None:
    """同一来源 pair 不能被模型复制成两个 manifest entry 后只得到 generic failure。"""

    runtime = KernelToolRuntime(build_research_tool_registrations())
    source_ref = "source-ref:v1:" + "a" * 64
    source_id = "source:v1:" + "b" * 64
    result = runtime.prepare(
        ToolCall(
            "manifest-duplicate-pair",
            "build_citation_manifest",
            {
                "artifact_path": ARTIFACT_PATH,
                "artifact_content": "first [S1], second [S2]\n",
                "goal_id": GOAL_ID,
                "goal_revision": GOAL_REVISION,
                "citations": [
                    {"marker": "[S1]", "source_ref": source_ref, "source_id": source_id},
                    {"marker": "[S2]", "source_ref": source_ref, "source_id": source_id},
                ],
            },
        ),
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_identity_digest="c" * 64,
            citable_source_refs=(source_ref,),
            citable_citation_sources=((source_ref, source_id),),
            citation_manifest_allowed=True,
            citation_artifact_paths=(ARTIFACT_PATH,),
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "citation_entries_not_one_to_one"
    assert "each exact source pair once" in result.content
    assert "reuse its one marker" in result.content


def test_manifest_builder_rejects_stale_goal_identity_before_binding() -> None:
    """manifest identity 必须逐字复制当前 Runtime Goal，而不是落入 binding_failure。"""

    runtime = KernelToolRuntime(build_research_tool_registrations())
    source_ref = "source-ref:v1:" + "a" * 64
    source_id = "source:v1:" + "b" * 64
    result = runtime.prepare(
        ToolCall(
            "manifest-stale-goal",
            "build_citation_manifest",
            {
                "artifact_path": ARTIFACT_PATH,
                "artifact_content": "grounded [S1]\n",
                "goal_id": "stale-goal",
                "goal_revision": GOAL_REVISION + 1,
                "citations": [
                    {"marker": "[S1]", "source_ref": source_ref, "source_id": source_id}
                ],
            },
        ),
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_identity_digest="c" * 64,
            citable_source_refs=(source_ref,),
            citable_citation_sources=((source_ref, source_id),),
            citation_manifest_allowed=True,
            citation_artifact_paths=(ARTIFACT_PATH,),
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "citation_goal_identity_mismatch"
    assert "current trusted_goal" in result.content
    assert "blocked_claim" not in result.content


def test_manifest_builder_rejects_sidecar_as_the_cited_artifact() -> None:
    runtime = KernelToolRuntime(build_research_tool_registrations())
    source_ref = "source-ref:v1:" + "a" * 64
    result = runtime.prepare(
        ToolCall(
            "manifest-wrong-artifact",
            "build_citation_manifest",
            {
                "artifact_path": MANIFEST_PATH,
                "artifact_content": "not the research artifact [S1]\n",
                "goal_id": GOAL_ID,
                "goal_revision": GOAL_REVISION,
                "citations": [
                    {
                        "marker": "[S1]",
                        "source_ref": source_ref,
                        "source_id": "source:v1:" + "b" * 64,
                    }
                ],
            },
        ),
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            citable_source_refs=(source_ref,),
            citation_manifest_allowed=True,
            citation_artifact_paths=(ARTIFACT_PATH,),
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "citation_artifact_not_authorized"
    assert ARTIFACT_PATH in result.content


def test_sidecar_write_requires_exact_current_runtime_manifest(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime(build_file_tool_registrations(workspace))
    source_ref = "source-ref:v1:" + "a" * 64
    source_id = "source:v1:" + "b" * 64
    result = runtime.prepare(
        ToolCall(
            "write-unbuilt-sidecar",
            "write_file",
            {"path": MANIFEST_PATH, "content": '{"citations":[]}'},
        ),
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_identity_digest="workspace-1",
            citation_manifest_allowed=True,
            citation_sidecar_paths=(MANIFEST_PATH,),
            citation_artifact_paths=(ARTIFACT_PATH,),
            citable_source_refs=(source_ref,),
            citable_citation_sources=((source_ref, source_id),),
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "citation_manifest_required"
    assert source_ref in result.content
    assert source_id in result.content
    assert not (workspace / MANIFEST_PATH).exists()


def test_exact_current_runtime_manifest_can_reach_write_approval(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "reports").mkdir()
    runtime = KernelToolRuntime(build_file_tool_registrations(workspace))
    _state, _claim, manifest = _fixture()
    content = manifest.to_json()

    result = runtime.prepare(
        ToolCall(
            "write-built-sidecar",
            "write_file",
            {"path": MANIFEST_PATH, "content": content},
        ),
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_identity_digest="workspace-1",
            citation_manifest_allowed=True,
            citation_sidecar_paths=(MANIFEST_PATH,),
            citation_artifact_paths=(ARTIFACT_PATH,),
            citation_manifest_content_digests=(_sha(content),),
        ),
    )

    assert isinstance(result, ApprovalRequired)
    assert not (workspace / MANIFEST_PATH).exists()


def test_single_transport_newline_is_normalized_before_sidecar_approval(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "reports").mkdir()
    runtime = KernelToolRuntime(build_file_tool_registrations(workspace))
    _state, _claim, manifest = _fixture()
    canonical = manifest.to_json()
    call = ToolCall(
        "write-built-sidecar-with-newline",
        "write_file",
        {"path": MANIFEST_PATH, "content": canonical + "\n"},
    )
    context = ToolPrepareContext(
        "conversation-1",
        "run-research",
        1,
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
        workspace_identity_digest="workspace-1",
        citation_manifest_allowed=True,
        citation_sidecar_paths=(MANIFEST_PATH,),
        citation_artifact_paths=(ARTIFACT_PATH,),
        citation_manifest_content_digests=(_sha(canonical),),
    )

    approval = runtime.prepare(call, context)
    assert isinstance(approval, ApprovalRequired)
    intent = runtime.prepare(
        call,
        context,
        approval=ApprovalGrant(
            approval.request.request_id,
            approval.request.binding_digest,
        ),
    )

    assert isinstance(intent, ExecutionIntent)
    assert intent.arguments["content"] == canonical


def test_manifest_write_authority_comes_only_from_current_run_builder_result() -> None:
    state, _claim, manifest = _fixture()
    content = manifest.to_json()
    state = replace(
        state,
        active_run=ActiveRun("run-research"),
        facts=(
            *state.facts,
            ConversationFact(
                fact_id="run:old-run:builder-calls",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "old-builder",
                            "name": "build_citation_manifest",
                            "arguments": {},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="run:old-run:builder-result",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "old-builder",
                    "text": content,
                    "is_error": False,
                    "executed": True,
                    "metadata": {},
                },
            ),
            ConversationFact(
                fact_id="run:run-research:builder-calls",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "current-builder",
                            "name": "build_citation_manifest",
                            "arguments": {},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="run:run-research:builder-result",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "current-builder",
                    "text": content,
                    "is_error": False,
                    "executed": True,
                    "metadata": {},
                },
            ),
        ),
    )

    assert AgentRuntime._citation_manifest_content_digests_for(state) == (_sha(content),)


def test_manifest_builder_is_rejected_when_goal_does_not_target_sidecar() -> None:
    runtime = KernelToolRuntime(build_research_tool_registrations())
    source_ref = "source-ref:v1:" + "a" * 64
    result = runtime.prepare(
        ToolCall(
            "manifest-not-required",
            "build_citation_manifest",
            {
                "artifact_path": ARTIFACT_PATH,
                "artifact_content": "grounded [S1]\n",
                "goal_id": GOAL_ID,
                "goal_revision": GOAL_REVISION,
                "citations": [
                    {
                        "marker": "[S1]",
                        "source_ref": source_ref,
                        "source_id": "source:v1:" + "b" * 64,
                    }
                ],
            },
        ),
        ToolPrepareContext(
            "conversation-1",
            "run-research",
            1,
            citable_source_refs=(source_ref,),
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata["code"] == "citation_manifest_not_required"
    assert ".citations.json" in result.content


@pytest.mark.parametrize("transport_suffix", ["", "\n"])
def test_approved_citation_sidecar_admits_mandatory_research_criterion(
    transport_suffix: str,
) -> None:
    state, _claim, manifest = _fixture()
    manifest_raw = manifest.to_json()
    call = ToolCall(
        "write-manifest",
        "write_file",
        {"path": MANIFEST_PATH, "content": manifest_raw + transport_suffix},
    )
    pending = ApprovalRequest(
        request_id="approval-manifest",
        run_id="run-research",
        tool_call_id=call.tool_call_id,
        binding_digest="approval-binding",
        preview="write citation sidecar",
        new_content_digest=_sha(manifest_raw),
    )
    state = replace(
        state,
        goal=replace(state.goal, admitted_criteria=()),
        active_run=ActiveRun(
            run_id="run-research",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=pending,
            tool_calls=(call,),
        ),
    )
    action = ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=pending.request_id,
        binding_digest=pending.binding_digest,
        approved=True,
    )

    transition = accept_action(state, action)

    assert transition.disposition is ActionDisposition.ACCEPTED
    research = tuple(
        item
        for item in transition.state.goal.admitted_criteria
        if item.oracle_kind is EvidenceOracleKind.RESEARCH_PROVENANCE
    )
    assert len(research) == 1
    assert research[0].mandatory is True
    assert research[0].predicate["manifest_digest"] == manifest.manifest_digest
    assert research[0].predicate["required_source_kinds"] == []
    assert research[0].predicate["required_source_classes"] == []
    assert research[0].predicate["required_receipt_digests"] == [
        citation.receipt_digest for citation in manifest.citations
    ]


def test_approved_sibling_citation_sidecar_binds_exact_manifest_sources() -> None:
    state, _claim, manifest = _fixture()
    sibling_path = "reports/report.citations.json"
    manifest_raw = manifest.to_json()
    call = ToolCall(
        "write-sibling-manifest",
        "write_file",
        {"path": sibling_path, "content": manifest_raw},
    )
    pending = ApprovalRequest(
        request_id="approval-sibling-manifest",
        run_id="run-research",
        tool_call_id=call.tool_call_id,
        binding_digest="approval-binding-sibling",
        preview="write sibling citation sidecar",
        new_content_digest=_sha(manifest_raw),
    )
    assert state.goal is not None
    state = replace(
        state,
        goal=replace(
            state.goal,
            targets=(ARTIFACT_PATH, sibling_path),
            admitted_criteria=(),
        ),
        active_run=ActiveRun(
            run_id="run-research",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=pending,
            tool_calls=(call,),
        ),
    )
    action = ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=pending.request_id,
        binding_digest=pending.binding_digest,
        approved=True,
    )

    transition = accept_action(state, action)

    research = tuple(
        item
        for item in transition.state.goal.admitted_criteria
        if item.oracle_kind is EvidenceOracleKind.RESEARCH_PROVENANCE
    )
    assert len(research) == 1
    predicate = research[0].predicate
    assert predicate["manifest_path"] == sibling_path
    assert predicate["minimum_distinct_sources"] == len(manifest.citations)
    assert predicate["required_source_kinds"] == []
    assert predicate["required_source_classes"] == []
    assert predicate["required_receipt_digests"] == [
        citation.receipt_digest for citation in manifest.citations
    ]


def test_research_oracle_accepts_explicit_sibling_citation_target() -> None:
    state, claim, _manifest = _fixture()
    sibling_path = "reports/report.citations.json"
    assert state.goal is not None
    criterion = state.goal.admitted_criteria[0]
    predicate = {**criterion.predicate, "manifest_path": sibling_path}
    facts = tuple(
        replace(
            fact,
            content={
                **fact.content,
                "calls": [
                    {
                        **fact.content["calls"][0],
                        "arguments": {"path": sibling_path},
                    }
                ],
            },
        )
        if fact.fact_id == "fact:calls:11"
        else fact
        for fact in state.facts
    )
    state = replace(
        state,
        facts=facts,
        goal=replace(
            state.goal,
            targets=(ARTIFACT_PATH, sibling_path),
            admitted_criteria=(
                replace(
                    criterion,
                    predicate=predicate,
                    admission_digest=canonical_json_digest(predicate),
                ),
            ),
        ),
    )

    records = ClosedEvidenceRegistry().derive(
        state,
        claim,
        observed_at="2026-08-04T01:00:00Z",
    )

    assert records[0].passed is True


def test_citation_sidecar_edit_is_rejected_before_effect(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sidecar = workspace / MANIFEST_PATH
    sidecar.parent.mkdir()
    sidecar.write_text('{"old":true}', encoding="utf-8")
    runtime = KernelToolRuntime(build_file_tool_registrations(workspace))

    prepared = runtime.prepare(
        ToolCall(
            "edit-manifest",
            "edit_file",
            {
                "path": MANIFEST_PATH,
                "old_text": "true",
                "new_text": "false",
            },
        ),
        ToolPrepareContext("conversation-1", "run-research", 1),
    )

    assert isinstance(prepared, ToolResult)
    assert prepared.executed is False
    assert prepared.metadata["code"] == "workspace_file_denied"
    assert "workspace-relative" in prepared.content
    assert "write_file" in prepared.content
    assert sidecar.read_text(encoding="utf-8") == '{"old":true}'


def test_approved_artifact_correction_supersedes_stale_path_and_provenance() -> None:
    state, _claim, _manifest = _fixture()
    assert state.goal is not None
    research = state.goal.admitted_criteria[0]

    def file_criterion(criterion_id: str, path: str) -> AdmittedCriterion:
        predicate = {"path": path, "sha256": "a" * 64}
        return AdmittedCriterion(
            criterion_id=criterion_id,
            description=f"old exact content for {path}",
            source_fact_id="action:1:user",
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            predicate=predicate,
            required_evidence_class="workspace_file",
            admission_digest=canonical_json_digest(predicate),
        )

    old_artifact = file_criterion("old-artifact", ARTIFACT_PATH)
    old_sidecar = file_criterion("old-sidecar", MANIFEST_PATH)
    call = ToolCall(
        "edit-corrected-artifact",
        "edit_file",
        {"path": ARTIFACT_PATH},
    )
    pending = ApprovalRequest(
        request_id="approval-corrected-artifact",
        run_id="run-research",
        tool_call_id=call.tool_call_id,
        binding_digest="approval-binding-corrected-artifact",
        preview="edit corrected artifact",
        new_content_digest="b" * 64,
    )
    state = replace(
        state,
        goal=replace(
            state.goal,
            admitted_criteria=(old_artifact, old_sidecar, research),
        ),
        active_run=ActiveRun(
            run_id="run-research",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=pending,
            tool_calls=(call,),
        ),
    )
    action = ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=pending.request_id,
        binding_digest=pending.binding_digest,
        approved=True,
    )

    transition = accept_action(state, action)

    assert transition.disposition is ActionDisposition.ACCEPTED
    assert transition.state.goal is not None
    criteria = transition.state.goal.admitted_criteria
    assert all(item.criterion_id != old_artifact.criterion_id for item in criteria)
    assert any(item.criterion_id == old_sidecar.criterion_id for item in criteria)
    assert all(
        item.oracle_kind is not EvidenceOracleKind.RESEARCH_PROVENANCE
        for item in criteria
    )
    corrected = next(
        item
        for item in criteria
        if item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
        and item.predicate["path"] == ARTIFACT_PATH
    )
    assert corrected.predicate["sha256"] == "b" * 64


def test_citation_sidecar_goal_cannot_complete_without_research_admission() -> None:
    state, claim, _manifest = _fixture()
    state = replace(state, goal=replace(state.goal, admitted_criteria=()))

    with pytest.raises(EvidenceVerificationError, match="research provenance"):
        ClosedEvidenceRegistry().derive(
            state,
            claim,
            observed_at="2026-08-04T01:00:00Z",
        )


def test_research_oracle_accepts_valid_three_source_exact_readback() -> None:
    state, claim, _manifest = _fixture()

    records = ClosedEvidenceRegistry().derive(
        state,
        claim,
        observed_at="2026-08-04T01:00:00Z",
    )

    assert records[0].passed is True
    assert records[0].oracle_kind is EvidenceOracleKind.RESEARCH_PROVENANCE
    assert records[0].oracle_identity == "research-provenance:v1"
    assert set(records[0].source_fact_ids) >= {
        "fact:source:1",
        "fact:source:2",
        "fact:source:3",
        "fact:read:10",
        "fact:read:11",
    }


def test_research_oracle_accepts_repeated_reference_to_same_source() -> None:
    state, claim, _manifest = _fixture(
        artifact=(
            "Past decision [H1].\nThe same decision still applies [H1].\n"
            "Current constraint [W1].\n"
            "Public fact [WEB1] (https://example.com/article).\n"
        )
    )

    records = ClosedEvidenceRegistry().derive(
        state,
        claim,
        observed_at="2026-08-04T01:00:00Z",
    )

    assert records[0].passed is True


def test_runtime_completion_path_reaches_verified_done_only_after_research_oracle() -> None:
    state, claim, _manifest = _fixture()
    store = InMemoryCheckpointStore(state)
    runtime = AgentRuntime(
        provider=ScriptedProvider(
            goal_noop_response("research-completion-user-supplement"),
            ModelResponse((), control=claim),
        ),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=50_000, output_reserve=1_000),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-research",
        evidence_time_factory=lambda: "2026-08-04T01:00:00Z",
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-completion",
        message="finish the grounded report",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal.status is GoalStatus.VERIFIED_DONE
    assert store.state.evidence_records[0].oracle_identity == "research-provenance:v1"


def test_research_goal_context_states_provenance_limit() -> None:
    state, _claim, _manifest = _fixture()
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-context",
        message="continue",
    )

    pack = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=50_000, output_reserve=1_000),
    ).build(state, action, ())

    goal_block = next(
        block
        for message in pack.messages
        for block in message.content
        if block.get("type") == "trusted_goal"
    )
    semantics = goal_block["research_evidence_semantics"]
    assert semantics["classification"] == "verified_delivery"
    assert semantics["source_content_is_untrusted_data"] is True
    assert "semantic truth" in semantics["does_not_prove"]
    source_blocks = [
        block
        for message in pack.messages
        for block in message.content
        if block.get("type") == "tool_result"
        and block.get("metadata", {}).get("source_receipts")
    ]
    assert source_blocks
    for block in source_blocks:
        receipts = block["metadata"]["source_receipts"]
        assert block["citation_sources"] == [
            {
                "source_ref": "source-ref:v1:" + receipt["receipt_digest"],
                "source_id": receipt["source_id"],
            }
            for receipt in receipts
        ]


@pytest.mark.parametrize(
    ("fixture_overrides", "message"),
    (
        ({"web_kind": SourceKind.WEB_SEARCH_SNIPPET}, "required source kind"),
        ({"web_goal_id": "old-goal"}, "current Goal"),
        ({"minimum_sources": 4}, "distinct source"),
        ({"observed_after": "2026-08-05T00:00:00Z"}, "freshness"),
        ({"fake_source": True}, "fake"),
        (
            {
                "artifact": (
                    "Past decision [H1].\nCurrent constraint [W1].\n"
                    "Public fact [WEB1] (https://invented.example/article).\n"
                )
            },
            "invented URL",
        ),
        (
            {
                "artifact": (
                    "Past decision [H1].\nCurrent constraint.\n"
                    "Public fact [WEB1] (https://example.com/article).\n"
                )
            },
            "citation marker",
        ),
    ),
)
def test_research_oracle_rejects_mutation_and_weak_provenance(
    fixture_overrides,
    message: str,
) -> None:  # noqa: ANN001
    state, claim, _manifest = _fixture(**fixture_overrides)

    with pytest.raises(EvidenceVerificationError, match=message):
        ClosedEvidenceRegistry().derive(
            state,
            claim,
            observed_at="2026-08-04T01:00:00Z",
        )


def test_artifact_changed_after_manifest_cannot_mint_research_evidence() -> None:
    state, claim, _manifest = _fixture()
    facts = tuple(
        replace(fact, content={**fact.content, "text": fact.content["text"] + "tampered"})
        if fact.fact_id == "fact:read:10"
        else fact
        for fact in state.facts
    )

    with pytest.raises(EvidenceVerificationError, match="exact read-back"):
        ClosedEvidenceRegistry().derive(
            replace(state, facts=facts),
            claim,
            observed_at="2026-08-04T01:00:00Z",
        )


def test_assistant_self_report_or_swapped_receipt_cannot_mint_research_evidence() -> None:
    state, claim, manifest = _fixture()
    source_facts = tuple(
        fact for fact in state.facts if not fact.fact_id.startswith("fact:source:")
    )
    assistant = ConversationFact(
        fact_id="fact:assistant:self-report",
        kind=FactKind.ASSISTANT_MESSAGE,
        content={"text": "All citations and sources are verified."},
    )
    with pytest.raises(EvidenceVerificationError, match="receipt"):
        ClosedEvidenceRegistry().derive(
            replace(state, facts=(*source_facts, assistant)),
            claim,
            observed_at="2026-08-04T01:00:00Z",
        )

    swapped = CitationManifestV1.create(
        artifact_path=manifest.artifact_path,
        artifact_sha256=manifest.artifact_sha256,
        goal_id=manifest.goal_id,
        goal_revision=manifest.goal_revision,
        citations=(
            replace(
                manifest.citations[0],
                receipt_digest="d" * 64,
            ),
            *manifest.citations[1:],
        ),
    )
    facts = tuple(
        replace(fact, content={**fact.content, "text": swapped.to_json()})
        if fact.fact_id == "fact:read:11"
        else fact
        for fact in state.facts
    )
    criterion = state.goal.admitted_criteria[0]
    predicate = {
        **criterion.predicate,
        "manifest_sha256": _sha(swapped.to_json()),
        "manifest_digest": swapped.manifest_digest,
    }
    state = replace(
        state,
        facts=facts,
        goal=replace(
            state.goal,
            admitted_criteria=(
                replace(
                    criterion,
                    predicate=predicate,
                    admission_digest=canonical_json_digest(predicate),
                ),
            ),
        ),
    )
    with pytest.raises(EvidenceVerificationError, match="receipt"):
        ClosedEvidenceRegistry().derive(
            state,
            claim,
            observed_at="2026-08-04T01:00:00Z",
        )

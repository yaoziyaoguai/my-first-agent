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
    ApprovalRequest,
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
    GoalFrame,
    GoalStatus,
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
    ToolPrepareContext,
    ToolResult,
    canonical_json_digest,
    closed_evidence_id,
)
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import accept_action
from agent.runtime.tools import KernelToolRuntime
from agent.tools.file_ops import build_file_tool_registrations
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider

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
        ToolPrepareContext("conversation-1", "run-research", 1),
    )
    assert isinstance(intent, ExecutionIntent)

    result = runtime.invoke(intent)

    assert result.is_error is False
    manifest = CitationManifestV1.from_json(result.content)
    assert manifest.artifact_path == ARTIFACT_PATH
    assert manifest.artifact_sha256 == _sha("grounded report\n")
    assert manifest.citations[0].receipt_digest == "c" * 64
    assert manifest.manifest_digest in result.content


def test_approved_citation_sidecar_admits_mandatory_research_criterion() -> None:
    state, _claim, manifest = _fixture()
    manifest_raw = manifest.to_json()
    call = ToolCall(
        "write-manifest",
        "write_file",
        {"path": MANIFEST_PATH, "content": manifest_raw},
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
    assert research[0].predicate["required_source_kinds"] == [
        "history_excerpt",
        "workspace_excerpt",
        "web_extracted_content",
    ]


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
    assert prepared.metadata["code"] == "policy_denied"
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


def test_runtime_completion_path_reaches_verified_done_only_after_research_oracle() -> None:
    state, claim, _manifest = _fixture()
    store = InMemoryCheckpointStore(state)
    runtime = AgentRuntime(
        provider=ScriptedProvider(ModelResponse((), control=claim)),
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

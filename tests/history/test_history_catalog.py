from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent.composition import build_tool_registrations
from agent.continuity.identity import WorkspaceIdentityV1
from agent.continuity.sessions import open_workspace_session
from agent.history.catalog import HistoryCatalog
from agent.history.contracts import HistoryOutcome, HistoryReferenceError
from agent.history.outcomes import project_outcome
from agent.history.tools import build_history_tool_registrations
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    CompletionClaim,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    FactKind,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    RecordedRunResult,
    RunStatus,
    SubmitMessage,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.evidence import ClosedEvidenceRegistry
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import create_goal
from agent.runtime.tools import KernelToolRuntime
from tests.continuity.test_contracts import _goal
from tests.continuity.test_verified_done import (
    EVIDENCE_ID,
    _claim,
)
from tests.continuity.test_verified_done import (
    _state as verifiable_state,
)
from tests.kernel.fakes import CollectingSink, ScriptedProvider


def _save(opened, state: ConversationState):  # noqa: ANN001
    assert opened.store is not None and opened.snapshot is not None
    lease = opened.store.try_acquire(opened.snapshot.state.conversation_id)
    assert lease is not None
    try:
        return opened.store.compare_and_swap(opened.snapshot, state)
    finally:
        lease.release()


def _catalog(opened, *, exclude_current: bool = False) -> HistoryCatalog:  # noqa: ANN001
    assert opened.checkpoint_path is not None and opened.workspace_binding is not None
    return HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=(
            opened.snapshot.state.conversation_id if exclude_current else None
        ),
    )


def test_catalog_search_get_and_stale_ref_are_snapshot_bound(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000201",
    )
    assert opened.snapshot is not None
    facts = (
        ConversationFact(
            fact_id="fact:user:decision",
            kind=FactKind.USER_MESSAGE,
            content={"text": "我们决定使用 SQLite 保存本地索引"},
        ),
        ConversationFact(
            fact_id="fact:assistant:decision",
            kind=FactKind.ASSISTANT_MESSAGE,
            content={"text": "已记录：索引保持 local-first。"},
        ),
    )
    saved = _save(opened, replace(opened.snapshot.state, facts=facts, revision=1))
    catalog = _catalog(opened)

    result = catalog.search("为什么决定 SQLite", limit=5)

    assert result.total_matches >= 1
    assert result.hits[0].record.conversation_id == saved.state.conversation_id
    assert "SQLite" in result.hits[0].excerpt
    history_ref = result.hits[0].history_ref
    content, record, truncated, _snapshot_digest = catalog.get(history_ref)
    assert "SQLite" in content
    assert record.record_id == result.hits[0].record.record_id
    assert not truncated
    with pytest.raises(HistoryReferenceError, match="not issued"):
        catalog.get("history-ref:v1:forged")

    latest = opened.store.load()
    _save(
        replace(opened, snapshot=latest),
        replace(
            latest.state,
            revision=latest.state.revision + 1,
            facts=(
                replace(
                    latest.state.facts[0],
                    content={"text": "修正：不再使用 SQLite。"},
                ),
                *latest.state.facts[1:],
            ),
        ),
    )
    with pytest.raises(HistoryReferenceError, match="stale"):
        catalog.get(history_ref)


def test_history_ref_stales_when_projected_outcome_changes(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000202",
    )
    assert opened.snapshot is not None and opened.workspace_binding is not None
    fact = ConversationFact(
        fact_id="fact:user:unchanged",
        kind=FactKind.USER_MESSAGE,
        content={"text": "keep generated reports in the current workspace"},
    )
    initial_goal = _goal(
        workspace_identity_digest=(
            opened.workspace_binding.workspace_identity_digest
        ),
        status=GoalStatus.GOAL_READY,
    )
    _save(
        opened,
        replace(
            opened.snapshot.state,
            facts=(fact,),
            goal=initial_goal,
            revision=1,
        ),
    )
    catalog = _catalog(opened)
    hit = catalog.search("generated reports current workspace", limit=5).hits[0]
    assert hit.record.outcome is HistoryOutcome.ACCEPTANCE_UNKNOWN

    latest = opened.store.load()
    _save(
        replace(opened, snapshot=latest),
        replace(
            latest.state,
            goal=replace(latest.state.goal, status=GoalStatus.BLOCKED),
            revision=latest.state.revision + 1,
        ),
    )

    with pytest.raises(HistoryReferenceError, match="stale"):
        catalog.get(hit.history_ref)


def test_catalog_recalls_a_short_paraphrase_with_one_grounding_term(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000241",
    )
    assert opened.snapshot is not None
    decision = ConversationFact(
        fact_id="fact:user:artifact-boundary",
        kind=FactKind.USER_MESSAGE,
        content={
            "text": (
                "The first release must keep generated artifacts inside the current "
                "workspace."
            )
        },
    )
    _save(opened, replace(opened.snapshot.state, facts=(decision,), revision=1))

    result = _catalog(opened).search(
        "verified boundary previously settled for where outputs may be stored workspace",
        limit=5,
    )

    assert result.total_matches >= 1
    assert result.hits[0].record.conversation_id == opened.snapshot.state.conversation_id
    assert "artifacts" in result.hits[0].excerpt


def test_catalog_excludes_unbound_and_wrong_identity_without_tool_inventory_leak(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000202",
    )
    assert opened.checkpoint_path is not None and opened.workspace_binding is not None
    current = opened.snapshot.state
    visible = ConversationFact(
        fact_id="fact:user:visible",
        kind=FactKind.USER_MESSAGE,
        content={"text": "公开决定：采用本地优先。"},
    )
    secret_call = ConversationFact(
        fact_id="fact:tool:inventory",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": "private-call",
                    "name": "do_not_expose",
                    "arguments": {"token": "INVENTORY_SENTINEL"},
                }
            ]
        },
    )
    _save(opened, replace(current, facts=(visible, secret_call), revision=1))
    legacy_id = "00000000-0000-4000-8000-000000000203"
    LocalCheckpointStore.initialize(
        opened.checkpoint_path.parent / f"{legacy_id}.json",
        ConversationState.new(legacy_id),
    )
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    other = open_workspace_session(
        other_workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000204",
    )
    assert other.snapshot is not None
    _save(
        other,
        replace(
            other.snapshot.state,
            revision=1,
            facts=(
                ConversationFact(
                    fact_id="fact:user:other",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "CROSS_WORKSPACE_SENTINEL"},
                ),
            ),
        ),
    )
    other_identity = WorkspaceIdentityV1.resolve(other_workspace)
    wrong_identity_id = "00000000-0000-4000-8000-000000000208"
    LocalCheckpointStore.initialize(
        opened.checkpoint_path.parent / f"{wrong_identity_id}.json",
        ConversationState(
            conversation_id=wrong_identity_id,
            workspace_binding=other.workspace_binding,
            revision=1,
            facts=(
                ConversationFact(
                    fact_id="fact:user:wrong-identity",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "WRONG_IDENTITY_SENTINEL"},
                ),
            ),
        ),
    )
    assert other_identity.identity_digest == other.workspace_binding.workspace_identity_digest
    catalog = _catalog(opened)

    visible_result = catalog.search("本地优先")
    hidden_inventory = catalog.search("INVENTORY_SENTINEL")
    cross_workspace = catalog.search("CROSS_WORKSPACE_SENTINEL")
    wrong_identity = catalog.search("WRONG_IDENTITY_SENTINEL")

    assert visible_result.hits
    assert visible_result.excluded_legacy_unbound == 1
    assert hidden_inventory.total_matches == 0
    assert cross_workspace.total_matches == 0
    assert wrong_identity.total_matches == 0
    assert visible_result.excluded_identity_mismatch == 1


def test_history_tools_mint_kernel_source_receipts_and_runtime_reuses_one_loop(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000205",
    )
    assert opened.snapshot is not None and opened.store is not None
    historical_id = "00000000-0000-4000-8000-000000000207"
    LocalCheckpointStore.initialize(
        opened.checkpoint_path.parent / f"{historical_id}.json",
        ConversationState(
            conversation_id=historical_id,
            workspace_binding=opened.workspace_binding,
            revision=1,
            facts=(
                ConversationFact(
                    fact_id="fact:user:history",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "上次选择了 local-first 的方案。"},
                ),
            ),
        ),
    )
    catalog = _catalog(opened, exclude_current=True)
    provider = ScriptedProvider(
        ModelResponse(
            (ModelToolCall("history-call", "history_search", {"query": "local-first"}),)
        ),
        ModelResponse((ModelTextBlock("根据当前 workspace 的历史，我们选择了 local-first。"),)),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
        ),
        tool_runtime=KernelToolRuntime(build_history_tool_registrations(catalog)),
        checkpoint_store=opened.store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        workspace_binding=opened.workspace_binding,
    )
    snapshot = opened.store.load()
    action = SubmitMessage(
        conversation_id=snapshot.state.conversation_id,
        action_seq=snapshot.state.next_action_seq,
        expected_revision=snapshot.state.revision,
        run_id="run-history-e2",
        message="我们上次为什么选 local-first？",
    )

    result = runtime.run_turn(action, snapshot)

    assert result.status is RunStatus.COMPLETED
    assert len(provider.calls) == 2
    assert "first_agent_history" in provider.calls[1].data_classes
    history_blocks = [
        block
        for message in provider.calls[1].messages
        for block in message.content
        if block.get("type") == "tool_result"
    ]
    assert history_blocks and history_blocks[0]["untrusted"] is True
    receipts = history_blocks[0]["metadata"]["source_receipts"]
    assert receipts[0]["data_class"] == "first_agent_history"
    assert receipts[0]["source_kind"] == "history_excerpt"


def test_history_get_requires_ref_issued_by_same_catalog_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000206",
    )
    assert opened.snapshot is not None
    _save(
        opened,
        replace(
            opened.snapshot.state,
            revision=1,
            facts=(
                ConversationFact(
                    fact_id="fact:user:ref",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "可回查的历史记录"},
                ),
            ),
        ),
    )
    catalog = _catalog(opened)
    tools = KernelToolRuntime(build_history_tool_registrations(catalog))
    context = ToolPrepareContext(
        conversation_id=opened.snapshot.state.conversation_id,
        run_id="run-tools",
        state_revision=1,
    )
    search_intent = tools.prepare(
        ToolCall("search-1", "history_search", {"query": "历史记录"}), context
    )
    search_result = tools.invoke(search_intent)
    history_ref = json.loads(search_result.content)["results"][0]["history_ref"]
    original_load_snapshot = catalog._load_snapshot
    load_count = 0

    def counting_load_snapshot():  # noqa: ANN202
        nonlocal load_count
        load_count += 1
        return original_load_snapshot()

    monkeypatch.setattr(catalog, "_load_snapshot", counting_load_snapshot)
    get_intent = tools.prepare(
        ToolCall("get-1", "history_get", {"history_ref": history_ref}), context
    )
    get_result = tools.invoke(get_intent)

    assert not get_result.is_error
    assert json.loads(get_result.content)["content"] == "可回查的历史记录"
    assert load_count == 1
    forged = tools.prepare(
        ToolCall("get-2", "history_get", {"history_ref": "history-ref:v1:forged"}),
        context,
    )
    assert forged.is_error and forged.executed is False


def test_history_ranking_orders_corrections_and_meets_bounded_recall(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000220",
    )
    assert opened.checkpoint_path is not None and opened.workspace_binding is not None
    cases = (
        (221, "数据库存储决定采用 SQLite 本地索引", "本地数据库索引"),
        (222, "界面主题决定使用深色 dark mode", "深色主题"),
        (223, "报告格式决定输出 Markdown 文档", "Markdown 报告"),
        (224, "认证方式决定使用 passkey 登录", "passkey 认证"),
        (225, "缓存策略决定使用 LRU cache", "LRU 缓存"),
        (226, "部署区域决定选择东京 Tokyo", "东京部署区域"),
        (227, "日志格式决定使用结构化 JSON", "JSON 日志"),
        (228, "任务队列决定采用 FIFO 顺序", "FIFO 队列"),
        (229, "搜索排序决定采用 lexical ranking", "lexical 搜索排序"),
        (230, "备份频率决定每日 daily backup", "每日备份"),
    )
    expected: dict[str, str] = {}
    for suffix, text, query in cases:
        conversation_id = f"00000000-0000-4000-8000-{suffix:012d}"
        expected[query] = conversation_id
        LocalCheckpointStore.initialize(
            opened.checkpoint_path.parent / f"{conversation_id}.json",
            ConversationState(
                conversation_id=conversation_id,
                workspace_binding=opened.workspace_binding,
                revision=1,
                facts=(
                    ConversationFact(
                        fact_id=f"fact:user:{suffix}",
                        kind=FactKind.USER_MESSAGE,
                        content={"text": text},
                    ),
                ),
            ),
        )
    correction_id = "00000000-0000-4000-8000-000000000231"
    LocalCheckpointStore.initialize(
        opened.checkpoint_path.parent / f"{correction_id}.json",
        ConversationState(
            conversation_id=correction_id,
            workspace_binding=opened.workspace_binding,
            revision=2,
            facts=(
                ConversationFact(
                    fact_id="fact:user:old-target",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "部署目标选择 staging environment"},
                ),
                ConversationFact(
                    fact_id="fact:user:corrected-target",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "修正部署目标选择 production environment"},
                ),
            ),
        ),
    )
    catalog = _catalog(opened)

    recalled = sum(
        expected[query]
        in {hit.record.conversation_id for hit in catalog.search(query, limit=5).hits}
        for query in expected
    )
    correction = catalog.search("部署目标选择", limit=5)

    assert recalled / len(expected) >= 0.8
    assert correction.hits[0].record.conversation_id == correction_id
    assert "production" in correction.hits[0].excerpt
    assert correction.hits[0].conflict
    assert catalog.search("完全不存在的量子香蕉决定").total_matches == 0


def test_cross_conversation_contrary_history_is_conflicted_before_limit(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000232",
    )
    assert opened.checkpoint_path is not None and opened.workspace_binding is not None
    for suffix, text in (
        (233, "部署目标决定使用 staging environment"),
        (234, "部署目标决定不再使用 staging environment，改为 production"),
    ):
        conversation_id = f"00000000-0000-4000-8000-{suffix:012d}"
        LocalCheckpointStore.initialize(
            opened.checkpoint_path.parent / f"{conversation_id}.json",
            ConversationState(
                conversation_id=conversation_id,
                workspace_binding=opened.workspace_binding,
                revision=1,
                facts=(
                    ConversationFact(
                        fact_id=f"fact:user:{suffix}",
                        kind=FactKind.USER_MESSAGE,
                        content={"text": text},
                    ),
                ),
            ),
        )
    catalog = _catalog(opened, exclude_current=True)

    limited = catalog.search("部署目标 staging environment", limit=1)
    expanded = catalog.search("部署目标 staging environment", limit=5)

    assert limited.total_matches == 2
    assert limited.hits[0].conflict is True
    assert len(expanded.hits) == 2
    assert all(hit.conflict for hit in expanded.hits)


def test_product_registration_factory_adds_history_to_the_single_tool_runtime(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000240",
    )
    catalog = _catalog(opened, exclude_current=True)

    registrations = build_tool_registrations(
        workspace=workspace,
        protected_paths=(opened.checkpoint_path,),
        max_tool_result_chars=20_000,
        history_catalog=catalog,
    )
    names = tuple(registration.spec.name for registration in registrations)
    history_search = next(
        registration.spec
        for registration in registrations
        if registration.spec.name == "history_search"
    )

    assert names.count("history_search") == 1
    assert names.count("history_get") == 1
    assert "read_file" in names
    assert "verbatim" in history_search.input_schema["properties"]["query"][
        "description"
    ]
    assert "boundary" in history_search.input_schema["properties"]["query"][
        "description"
    ]
    assert history_search.input_schema["properties"]["limit"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 5,
    }


def test_outcome_projection_does_not_equate_delivery_with_user_acceptance() -> None:
    unknown = ConversationState.new("conversation-unknown")
    source = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "task"},
    )
    active = create_goal(
        ConversationState(conversation_id="conversation-active", facts=(source,)),
        _goal(),
    )
    blocked = replace(active, goal=replace(active.goal, status=GoalStatus.BLOCKED))
    cancelled = replace(active, goal=replace(active.goal, status=GoalStatus.CANCELLED))
    failed = replace(
        active,
        last_safe_result=RecordedRunResult(
            status=RunStatus.FAILED_FATAL,
            error_code="provider_failure",
        ),
    )
    base = verifiable_state()
    evidence = ClosedEvidenceRegistry().derive(
        base,
        _claim(),
        observed_at="2026-08-04T04:00:00Z",
    )
    delivered = replace(
        base,
        goal=replace(base.goal, status=GoalStatus.VERIFIED_DONE),
        evidence_records=evidence,
        completion_claim=_claim(),
    )
    subjective = verifiable_state()
    criterion = replace(
        subjective.goal.admitted_criteria[0],
        oracle_kind=EvidenceOracleKind.USER_CONFIRMATION,
        predicate={"confirmed": True},
    )
    confirmation = ConversationFact(
        fact_id="fact:user:acceptance",
        kind=FactKind.USER_MESSAGE,
        content={"criterion_id": criterion.criterion_id, "confirmed": True},
    )
    subjective = replace(
        subjective,
        facts=(*subjective.facts, confirmation),
        goal=replace(subjective.goal, admitted_criteria=(criterion,)),
    )
    accepted_evidence = ClosedEvidenceRegistry().derive(
        subjective,
        CompletionClaim(
            correlation_id="claim-acceptance",
            goal_id=subjective.goal.goal_id,
            goal_revision=subjective.goal.revision,
            criterion_evidence_refs=(EVIDENCE_ID,),
        ),
        observed_at="2026-08-04T04:01:00Z",
    )
    accepted = replace(
        subjective,
        goal=replace(subjective.goal, status=GoalStatus.VERIFIED_DONE),
        evidence_records=accepted_evidence,
        completion_claim=CompletionClaim(
            correlation_id="claim-acceptance",
            goal_id=subjective.goal.goal_id,
            goal_revision=subjective.goal.revision,
            criterion_evidence_refs=(EVIDENCE_ID,),
        ),
    )

    assert project_outcome(unknown) is HistoryOutcome.ACCEPTANCE_UNKNOWN
    assert project_outcome(blocked) is HistoryOutcome.BLOCKED
    assert project_outcome(cancelled) is HistoryOutcome.CANCELLED
    assert project_outcome(failed) is HistoryOutcome.FAILED
    assert project_outcome(delivered) is HistoryOutcome.VERIFIED_DELIVERY
    assert project_outcome(accepted) is HistoryOutcome.USER_CONFIRMED_ACCEPTANCE

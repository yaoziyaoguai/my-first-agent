from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent.composition import build_tool_registrations
from agent.continuity.archive import LocalConversationArchive
from agent.continuity.identity import WorkspaceIdentityV1
from agent.continuity.sessions import open_workspace_session
from agent.history.catalog import HistoryCatalog
from agent.history.contracts import (
    HistoryOutcome,
    HistoryReferenceError,
    HistorySearchResult,
)
from agent.history.outcomes import project_outcome
from agent.history.tools import build_history_tool_registrations
from agent.runtime.checkpoint import LocalCheckpointStore, encode_conversation_state
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    BeginAnswer,
    CompletionClaim,
    ConversationFact,
    ConversationState,
    ConversationSummaryV1,
    DirectResponse,
    EvidenceOracleKind,
    FactKind,
    GoalStatus,
    LoadedSnapshot,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    RecordedRunResult,
    RunStatus,
    SubmitMessage,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
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


def test_catalog_rejects_archive_page_limit_above_hard_bound(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000200",
    )
    assert opened.checkpoint_path is not None
    assert opened.workspace_binding is not None

    with pytest.raises(ValueError, match="must not exceed 256"):
        HistoryCatalog(
            opened.checkpoint_path.parent,
            opened.workspace_binding,
            max_archive_reads_per_search=257,
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


def test_archive_enabled_catalog_gets_a_goal_bound_legacy_root_exactly(tmp_path) -> None:
    """旧 checkpoint 可用 goal identity 纳入，但 ref 仍须回到同一精确文件。"""

    workspace = tmp_path / "workspace"
    state_root = tmp_path / "state"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000259",
    )
    assert opened.checkpoint_path is not None and opened.workspace_binding is not None
    legacy_id = "00000000-0000-4000-8000-000000000260"
    LocalCheckpointStore.initialize(
        opened.checkpoint_path.parent / f"{legacy_id}.json",
        ConversationState(
            conversation_id=legacy_id,
            revision=1,
            goal=_goal(
                workspace_identity_digest=(
                    opened.workspace_binding.workspace_identity_digest
                )
            ),
            facts=(
                ConversationFact(
                    fact_id="fact:user:legacy-root",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "HELIUM_SENTINEL 来自 goal-bound legacy root"},
                ),
            ),
        ),
    )
    catalog = HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=opened.snapshot.state.conversation_id,
        conversation_archive=LocalConversationArchive(state_root),
    )

    search = catalog.search("HELIUM_SENTINEL", limit=5)
    content, record, truncated, _snapshot_digest = catalog.get(
        search.hits[0].history_ref
    )

    assert search.coverage_complete is True
    assert "HELIUM_SENTINEL" in content
    assert record.conversation_id == legacy_id
    assert truncated is False


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
        ModelResponse((), control=BeginAnswer("begin-history-answer")),
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
    assert len(provider.calls) == 3
    assert "first_agent_history" in provider.calls[2].data_classes
    history_blocks = [
        block
        for message in provider.calls[2].messages
        for block in message.content
        if block.get("type") == "tool_result"
    ]
    assert history_blocks and history_blocks[0]["untrusted"] is True
    receipts = history_blocks[0]["metadata"]["source_receipts"]
    assert receipts[0]["data_class"] == "first_agent_history"
    assert receipts[0]["source_kind"] == "history_excerpt"


def test_history_search_tool_round_trips_archive_continuation() -> None:
    class _PagedCatalog:
        def validate_search(self, query, limit, continuation=None):  # noqa: ANN001
            assert (query, limit, continuation) == ("深层历史", 5, "cursor-in")
            return "binding"

        def search(self, query, *, limit=5, continuation=None):  # noqa: ANN001
            assert (query, limit, continuation) == ("深层历史", 5, "cursor-in")
            return HistorySearchResult(
                snapshot_digest="snapshot",
                hits=(),
                total_matches=3,
                incomplete=True,
                coverage_complete=False,
                continuation="cursor-out",
                excluded_legacy_unbound=0,
                excluded_identity_mismatch=0,
            )

    tools = KernelToolRuntime(build_history_tool_registrations(_PagedCatalog()))
    context = ToolPrepareContext(
        conversation_id="00000000-0000-4000-8000-000000000205",
        run_id="run-history-continuation",
        state_revision=1,
    )
    intent = tools.prepare(
        ToolCall(
            "search-page-2",
            "history_search",
            {"query": "深层历史", "continuation": "cursor-in"},
        ),
        context,
    )

    result = tools.invoke(intent)

    assert not result.is_error
    assert json.loads(result.content) == {
        "status": "partial",
        "results": [],
        "total_matches": 3,
        "incomplete": True,
        "coverage_complete": False,
        "continuation": "cursor-out",
    }
    assert result.metadata["coverage_complete"] is False
    assert result.metadata["continuation"] == "cursor-out"


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


def test_catalog_serves_archived_pre_compaction_history_of_the_current_conversation(
    tmp_path,
    monkeypatch,
) -> None:
    """F5c tracer bullet：compaction 后 raw fact 只活在 archive 里。

    current_conversation_id 只排除 active checkpoint；archived pre-compaction
    segment 不经 ContextManager 投影，必须仍可被 public search 命中并 get。
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000252",
    )
    assert opened.snapshot is not None and opened.workspace_binding is not None
    assert opened.checkpoint_path is not None
    sentinel = ConversationFact(
        fact_id="fact:user:pre-compaction",
        kind=FactKind.USER_MESSAGE,
        content={"text": "PHOSPHORUS_SENTINEL 决定由只读副本承担全部报表查询"},
    )
    full = _save(
        opened,
        replace(opened.snapshot.state, facts=(sentinel,), revision=1),
    )
    # 真实 compaction 前置：以 source checkpoint digest 为 identity 归档完整状态。
    archive = LocalConversationArchive(tmp_path / "state")
    archive.archive(
        full.state,
        source_checkpoint_digest=full.token,
        workspace_scope_digest=opened.workspace_binding.workspace_scope_digest,
    )
    # compaction：active checkpoint 移除 raw fact，只保留闭合 summary。
    summary = ConversationFact(
        fact_id="fact:summary:post-compaction",
        kind=FactKind.CONTEXT_SUMMARY,
        content=ConversationSummaryV1(
            objective="维护报表查询的承载方案",
            constraints=(),
            decisions=("历史承载方案已归档",),
            completed=(),
            open_items=(),
            key_references=(),
            source_checkpoint_digest=full.token.removeprefix("sha256:"),
            source_fact_ids_digest="0" * 64,
        ).to_content(),
    )
    compacted = _save(
        replace(opened, snapshot=full),
        replace(full.state, revision=full.state.revision + 1, facts=(summary,)),
    )
    catalog = HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=opened.snapshot.state.conversation_id,
        conversation_archive=archive,
    )

    result = catalog.search("PHOSPHORUS_SENTINEL", limit=5)

    assert result.total_matches == 1
    assert result.hits[0].record.conversation_id == full.state.conversation_id
    assert "PHOSPHORUS_SENTINEL" in result.hits[0].excerpt
    monkeypatch.setattr(
        archive,
        "list_archived",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("history_get must not scan the archive directory")
        ),
    )
    content, record, truncated, _snapshot_digest = catalog.get(
        result.hits[0].history_ref
    )
    assert "PHOSPHORUS_SENTINEL" in content
    assert record.record_id == result.hits[0].record.record_id
    assert not truncated
    assert catalog.snapshot_digest() == result.snapshot_digest

    changed_summary = replace(
        ConversationSummaryV1.from_content(summary.content),
        source_checkpoint_digest="f" * 64,
    )
    _save(
        replace(opened, snapshot=compacted),
        replace(
            compacted.state,
            revision=compacted.state.revision + 1,
            facts=(replace(summary, content=changed_summary.to_content()),),
        ),
    )
    with pytest.raises(HistoryReferenceError, match="stale"):
        catalog.get(result.hits[0].history_ref)


def test_catalog_continues_canonical_archive_lineage_after_page_budget(
    tmp_path,
) -> None:
    """单页预算耗尽是 partial result，不得让更深的 canonical 历史失效。"""

    workspace = tmp_path / "workspace"
    state_root = tmp_path / "state"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000255",
    )
    assert opened.snapshot is not None and opened.workspace_binding is not None
    assert opened.checkpoint_path is not None
    sentinel = ConversationFact(
        fact_id="fact:user:deep-lineage",
        kind=FactKind.USER_MESSAGE,
        content={"text": "KRYPTON_SENTINEL 最老归档中的部署决定"},
    )
    oldest = _save(
        opened,
        replace(opened.snapshot.state, facts=(sentinel,), revision=1),
    )
    archive = LocalConversationArchive(state_root)
    archive.archive(
        oldest.state,
        source_checkpoint_digest=oldest.token,
        workspace_scope_digest=opened.workspace_binding.workspace_scope_digest,
    )
    first_summary = ConversationFact(
        fact_id="fact:summary:first-lineage",
        kind=FactKind.CONTEXT_SUMMARY,
        content=ConversationSummaryV1(
            objective="保存最老部署决定",
            constraints=(),
            decisions=("最老决定已归档",),
            completed=(),
            open_items=(),
            key_references=(),
            source_checkpoint_digest=oldest.token.removeprefix("sha256:"),
            source_fact_ids_digest="1" * 64,
        ).to_content(),
    )
    middle = _save(
        replace(opened, snapshot=oldest),
        replace(
            oldest.state,
            revision=2,
            facts=(
                first_summary,
                ConversationFact(
                    fact_id="fact:user:middle-lineage",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "中间归档不包含目标关键字"},
                ),
            ),
        ),
    )
    archive.archive(
        middle.state,
        source_checkpoint_digest=middle.token,
        workspace_scope_digest=opened.workspace_binding.workspace_scope_digest,
    )
    second_summary = ConversationFact(
        fact_id="fact:summary:second-lineage",
        kind=FactKind.CONTEXT_SUMMARY,
        content=ConversationSummaryV1(
            objective="保存中间部署决定",
            constraints=(),
            decisions=("中间决定已归档",),
            completed=(),
            open_items=(),
            key_references=(),
            source_checkpoint_digest=middle.token.removeprefix("sha256:"),
            source_fact_ids_digest="2" * 64,
        ).to_content(),
    )
    current = _save(
        replace(opened, snapshot=middle),
        replace(middle.state, revision=3, facts=(second_summary,)),
    )

    class _CountingArchive:
        def __init__(self) -> None:
            self.reads = 0

        def load_archived_by_identity(self, **identity):  # noqa: ANN001
            self.reads += 1
            return archive.load_archived_by_identity(**identity)

    counting_archive = _CountingArchive()
    catalog = HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=oldest.state.conversation_id,
        conversation_archive=counting_archive,
        max_archive_reads_per_search=1,
    )

    first = catalog.search("KRYPTON_SENTINEL", limit=5)

    assert first.hits == ()
    assert first.total_matches == 0
    assert first.incomplete is True
    assert first.coverage_complete is False
    assert isinstance(first.continuation, str)
    assert counting_archive.reads == 1

    with pytest.raises(ValueError, match="invalid shape"):
        catalog.search(
            "KRYPTON_SENTINEL",
            limit=5,
            continuation="forged-cursor",
        )
    with pytest.raises(ValueError, match="query and limit"):
        catalog.search(
            "OTHER_SENTINEL",
            limit=5,
            continuation=first.continuation,
        )

    other = catalog.search("OTHER_SENTINEL", limit=5)
    assert other.continuation is not None
    assert other.continuation != first.continuation
    assert counting_archive.reads == 2

    _save(
        replace(opened, snapshot=current),
        replace(
            current.state,
            revision=4,
            facts=(
                second_summary,
                ConversationFact(
                    fact_id="fact:user:after-cursor",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "continuation 签发后追加普通 turn"},
                ),
                ConversationFact(
                    fact_id="fact:assistant:after-cursor",
                    kind=FactKind.ASSISTANT_MESSAGE,
                    content={"text": "lineage head 未变化"},
                ),
            ),
        ),
    )

    completed = catalog.search(
        "KRYPTON_SENTINEL",
        limit=5,
        continuation=first.continuation,
    )

    assert completed.coverage_complete is True
    assert completed.continuation is None
    assert completed.total_matches == 1
    assert len(completed.hits) == 1
    assert "KRYPTON_SENTINEL" in completed.hits[0].excerpt
    assert counting_archive.reads == 3


def test_catalog_rejects_archive_adapter_returning_the_wrong_lineage_digest(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000256",
    )
    assert opened.snapshot is not None and opened.workspace_binding is not None
    assert opened.checkpoint_path is not None
    requested = f"sha256:{'b' * 64}"
    summary = ConversationFact(
        fact_id="fact:summary:wrong-adapter-token",
        kind=FactKind.CONTEXT_SUMMARY,
        content=ConversationSummaryV1(
            objective="验证 lineage identity",
            constraints=(),
            decisions=("只接受精确 digest",),
            completed=(),
            open_items=(),
            key_references=(),
            source_checkpoint_digest=requested.removeprefix("sha256:"),
            source_fact_ids_digest="3" * 64,
        ).to_content(),
    )
    _save(
        opened,
        replace(opened.snapshot.state, revision=1, facts=(summary,)),
    )
    wrong = LoadedSnapshot(
        ConversationState(
            conversation_id=opened.snapshot.state.conversation_id,
            revision=0,
            workspace_binding=opened.workspace_binding,
            facts=(
                ConversationFact(
                    fact_id="fact:user:wrong-adapter-token",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": "错误 adapter 不得注入历史"},
                ),
            ),
        ),
        f"sha256:{'a' * 64}",
    )

    class _WrongIdentityArchive:
        def load_archived_by_identity(self, **_identity):  # noqa: ANN202
            return wrong

    catalog = HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=opened.snapshot.state.conversation_id,
        conversation_archive=_WrongIdentityArchive(),
    )

    with pytest.raises(ValueError, match="digest"):
        catalog.search("错误 adapter", limit=5)


def test_default_history_search_continues_beyond_256_real_archives(tmp_path) -> None:
    """256 是单次工作预算，不再是 workspace lifetime archive 容量。"""

    workspace = tmp_path / "workspace"
    state_root = tmp_path / "state"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000258",
    )
    assert opened.snapshot is not None and opened.workspace_binding is not None
    assert opened.checkpoint_path is not None
    archive = LocalConversationArchive(state_root)
    current = opened.snapshot
    for index in range(257):
        prior_summary = tuple(
            fact
            for fact in current.state.facts
            if fact.kind is FactKind.CONTEXT_SUMMARY
        )
        text = (
            "XENON_SENTINEL 只存在于第 257 次向前读取的最老历史"
            if index == 0
            else f"归档轮次 {index}"
        )
        source = _save(
            replace(opened, snapshot=current),
            replace(
                current.state,
                revision=current.state.revision + 1,
                facts=(
                    *prior_summary,
                    ConversationFact(
                        fact_id=f"fact:user:archive-{index}",
                        kind=FactKind.USER_MESSAGE,
                        content={"text": text},
                    ),
                    ConversationFact(
                        fact_id=f"fact:assistant:archive-{index}",
                        kind=FactKind.ASSISTANT_MESSAGE,
                        content={"text": f"已记录归档轮次 {index}"},
                    ),
                ),
            ),
        )
        archive.archive(
            source.state,
            source_checkpoint_digest=source.token,
            workspace_scope_digest=opened.workspace_binding.workspace_scope_digest,
        )
        summary = ConversationFact(
            fact_id=f"fact:summary:archive-{index}",
            kind=FactKind.CONTEXT_SUMMARY,
            content=ConversationSummaryV1(
                objective=f"压缩归档轮次 {index}",
                constraints=(),
                decisions=(f"归档轮次 {index} 已完成",),
                completed=(),
                open_items=(),
                key_references=(),
                source_checkpoint_digest=source.token.removeprefix("sha256:"),
                source_fact_ids_digest=f"{index:064x}",
            ).to_content(),
        )
        current = _save(
            replace(opened, snapshot=source),
            replace(
                source.state,
                revision=source.state.revision + 1,
                facts=(summary,),
            ),
        )

    class _CountingArchive:
        def __init__(self) -> None:
            self.reads = 0

        def load_archived_by_identity(self, **identity):  # noqa: ANN001
            self.reads += 1
            return archive.load_archived_by_identity(**identity)

    counting_archive = _CountingArchive()
    catalog = HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=opened.snapshot.state.conversation_id,
        conversation_archive=counting_archive,
    )

    first = catalog.search("XENON_SENTINEL", limit=5)

    assert first.hits == ()
    assert first.coverage_complete is False
    assert first.continuation is not None
    assert counting_archive.reads == 256

    completed = catalog.search(
        "XENON_SENTINEL",
        limit=5,
        continuation=first.continuation,
    )

    assert completed.coverage_complete is True
    assert completed.continuation is None
    assert completed.total_matches == 1
    assert "XENON_SENTINEL" in completed.hits[0].excerpt
    assert counting_archive.reads == 257


def test_history_tool_prepare_rejects_continuation_after_lineage_head_changes(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000257",
    )
    assert opened.snapshot is not None and opened.workspace_binding is not None
    assert opened.checkpoint_path is not None
    oldest_token = f"sha256:{'a' * 64}"
    middle_token = f"sha256:{'b' * 64}"

    def summary_fact(fact_id: str, token: str) -> ConversationFact:
        return ConversationFact(
            fact_id=fact_id,
            kind=FactKind.CONTEXT_SUMMARY,
            content=ConversationSummaryV1(
                objective="验证 continuation root binding",
                constraints=(),
                decisions=("lineage head 必须稳定",),
                completed=(),
                open_items=(),
                key_references=(),
                source_checkpoint_digest=token.removeprefix("sha256:"),
                source_fact_ids_digest="4" * 64,
            ).to_content(),
        )

    middle = LoadedSnapshot(
        ConversationState(
            conversation_id=opened.snapshot.state.conversation_id,
            revision=1,
            workspace_binding=opened.workspace_binding,
            facts=(summary_fact("fact:summary:middle-root", oldest_token),),
        ),
        middle_token,
    )

    class _MiddleArchive:
        def load_archived_by_identity(self, **identity):  # noqa: ANN001
            assert identity["source_checkpoint_digest"] == middle_token
            return middle

    current = _save(
        opened,
        replace(
            opened.snapshot.state,
            revision=1,
            facts=(summary_fact("fact:summary:current-root", middle_token),),
        ),
    )
    current = _save(
        replace(opened, snapshot=current),
        replace(current.state, revision=2),
    )
    catalog = HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=opened.snapshot.state.conversation_id,
        conversation_archive=_MiddleArchive(),
        max_archive_reads_per_search=1,
    )
    first = catalog.search("不会命中", limit=5)
    assert first.continuation is not None

    changed_head = summary_fact(
        "fact:summary:changed-root",
        f"sha256:{'c' * 64}",
    )
    _save(
        replace(opened, snapshot=current),
        replace(current.state, revision=3, facts=(changed_head,)),
    )
    tools = KernelToolRuntime(build_history_tool_registrations(catalog))
    prepared = tools.prepare(
        ToolCall(
            "stale-search",
            "history_search",
            {"query": "不会命中", "continuation": first.continuation},
        ),
        ToolPrepareContext(
            conversation_id=opened.snapshot.state.conversation_id,
            run_id="run-stale-history-continuation",
            state_revision=3,
        ),
    )

    assert isinstance(prepared, ToolResult)
    assert prepared.is_error and prepared.executed is False


def test_run_turn_compaction_archive_is_served_by_restarted_catalog(tmp_path) -> None:
    """真实 store 压力经唯一 Runtime loop 归档、缩减，并在重启后恢复历史。"""

    workspace = tmp_path / "workspace"
    state_root = tmp_path / "state"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000254",
    )
    assert opened.snapshot is not None and opened.workspace_binding is not None
    assert opened.checkpoint_path is not None

    facts: list[ConversationFact] = []
    for turn in range(1, 6):
        user_text = (
            "NEON_SENTINEL 旧轮次决定归档后仍可查询。"
            if turn == 1
            else f"历史用户轮次 {turn}："
        )
        facts.extend(
            (
                ConversationFact(
                    fact_id=f"action:{turn * 2 - 1}:user",
                    kind=FactKind.USER_MESSAGE,
                    content={"text": user_text + "U" * 1_800},
                ),
                ConversationFact(
                    fact_id=f"action:{turn * 2}:assistant",
                    kind=FactKind.ASSISTANT_MESSAGE,
                    content={"text": f"历史助手轮次 {turn}：" + "A" * 1_800},
                ),
            )
        )
    seeded = _save(
        opened,
        ConversationState(
            conversation_id=opened.snapshot.state.conversation_id,
            revision=1,
            next_action_seq=11,
            replay_floor=11,
            facts=tuple(facts),
            workspace_binding=opened.workspace_binding,
        ),
    )
    store = LocalCheckpointStore(opened.checkpoint_path, max_state_bytes=26_000)
    seeded = store.load()
    usage = store.usage(seeded)
    assert usage.active_bytes >= usage.soft_threshold_bytes

    def summary_response(context):  # noqa: ANN001
        (message,) = context.messages
        (block,) = message.content
        assert isinstance(block, dict)
        assert block.get("type") == "context_summary_input"
        summary = ConversationSummaryV1(
            objective="归档最老的完整会话轮次",
            constraints=(),
            decisions=("旧轮次已无损归档",),
            completed=(),
            open_items=(),
            key_references=(),
            source_checkpoint_digest=block["source_checkpoint_digest"],
            source_fact_ids_digest=block["source_fact_ids_digest"],
        )
        return ModelResponse(
            (ModelTextBlock(text=summary.to_json()),),
            stop_reason="stop",
            output_tokens=1,
        )

    provider = ScriptedProvider(
        summary_response,
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id="direct-after-real-compaction",
                text="continued after real compaction",
            ),
        ),
    )
    archive = LocalConversationArchive(state_root)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=100_000, output_reserve=500),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(durable_effect_reserve_bytes=1),
        conversation_archive=archive,
    )
    action = SubmitMessage(
        conversation_id=seeded.state.conversation_id,
        action_seq=seeded.state.next_action_seq,
        expected_revision=seeded.state.revision,
        run_id="run-real-compaction-history",
        message="继续当前会话",
    )

    result = runtime.run_turn(action, seeded)

    assert result.status is RunStatus.COMPLETED
    assert result.message == "continued after real compaction"
    assert len(provider.calls) == 2
    assert provider.calls[0].messages[0].content[0]["type"] == "context_summary_input"

    fresh_archive = LocalConversationArchive(state_root)
    (record,) = fresh_archive.list_archived(
        workspace_scope_digest=opened.workspace_binding.workspace_scope_digest
    )
    archived = fresh_archive.load_archived(record)
    assert record.source_checkpoint_digest != seeded.token
    assert record.path.name == f"{record.source_checkpoint_digest.removeprefix('sha256:')}.json"
    assert record.path.read_bytes() == encode_conversation_state(archived.state)
    assert any(
        "NEON_SENTINEL" in str(fact.content.get("text", ""))
        for fact in archived.state.facts
    )

    durable = store.load()
    summaries = tuple(
        fact for fact in durable.state.facts if fact.kind is FactKind.CONTEXT_SUMMARY
    )
    assert len(summaries) == 1
    summary = ConversationSummaryV1.from_content(summaries[0].content)
    assert summary.source_checkpoint_digest == record.source_checkpoint_digest.removeprefix(
        "sha256:"
    )
    durable_ids = {fact.fact_id for fact in durable.state.facts}
    assert "action:1:user" not in durable_ids
    assert "action:2:assistant" not in durable_ids

    restarted_catalog = HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=seeded.state.conversation_id,
        conversation_archive=fresh_archive,
    )
    search = restarted_catalog.search("NEON_SENTINEL", limit=5)
    assert search.total_matches == 1
    hit = search.hits[0]
    assert hit.record.conversation_id == seeded.state.conversation_id
    assert "NEON_SENTINEL" in hit.excerpt
    content, history_record, truncated, _snapshot_digest = restarted_catalog.get(
        hit.history_ref
    )
    assert "NEON_SENTINEL" in content
    assert history_record.record_id == hit.record.record_id
    assert not truncated


def test_catalog_deduplicates_overlapping_archive_projections_of_one_stable_fact(
    tmp_path,
) -> None:
    """F5c tracer bullet：重叠 archive 只保留同一 stable fact 的一个投影。

    compaction 前后的两份 archive 含同一 fact_id 的 sentinel：position 位移不得
    让 record identity 分裂，否则重叠投影被当成两条历史并污染 ref 解析。
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened = open_workspace_session(
        workspace,
        state_root=tmp_path / "state",
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000253",
    )
    assert opened.snapshot is not None and opened.workspace_binding is not None
    assert opened.checkpoint_path is not None
    turn_user = ConversationFact(
        fact_id="fact:user:turn-1a",
        kind=FactKind.USER_MESSAGE,
        content={"text": "先确认报表入口由值班工程师维护"},
    )
    turn_assistant = ConversationFact(
        fact_id="fact:assistant:turn-1b",
        kind=FactKind.ASSISTANT_MESSAGE,
        content={"text": "已确认：报表入口维护归值班工程师。"},
    )
    sentinel = ConversationFact(
        fact_id="fact:user:overlapping-sentinel",
        kind=FactKind.USER_MESSAGE,
        content={"text": "ARGON_SENTINEL 决定报表聚合查询只走只读副本"},
    )
    pre = _save(
        opened,
        replace(
            opened.snapshot.state,
            facts=(turn_user, turn_assistant, sentinel),
            revision=1,
        ),
    )
    archive = LocalConversationArchive(tmp_path / "state")
    archive.archive(
        pre.state,
        source_checkpoint_digest=pre.token,
        workspace_scope_digest=opened.workspace_binding.workspace_scope_digest,
    )
    # compaction：前置 closed turn 的两个 facts 收敛为 1 个 CONTEXT_SUMMARY，
    # 同一 sentinel 的 position 由 2 位移到 1，随后归档为重叠 archive。
    turn_summary = ConversationFact(
        fact_id="fact:summary:turn-1",
        kind=FactKind.CONTEXT_SUMMARY,
        content=ConversationSummaryV1(
            objective="确认报表入口维护分工",
            constraints=(),
            decisions=("报表入口维护已收敛",),
            completed=(),
            open_items=(),
            key_references=(),
            source_checkpoint_digest=pre.token.removeprefix("sha256:"),
            source_fact_ids_digest="0" * 64,
        ).to_content(),
    )
    post = _save(
        replace(opened, snapshot=pre),
        replace(
            pre.state,
            revision=pre.state.revision + 1,
            facts=(turn_summary, sentinel),
        ),
    )
    archive.archive(
        post.state,
        source_checkpoint_digest=post.token,
        workspace_scope_digest=opened.workspace_binding.workspace_scope_digest,
    )
    # 最终 compaction：active checkpoint 移除 raw sentinel，只留闭合 summary。
    final_summary = ConversationFact(
        fact_id="fact:summary:final",
        kind=FactKind.CONTEXT_SUMMARY,
        content=ConversationSummaryV1(
            objective="报表聚合承载已归档",
            constraints=(),
            decisions=("聚合承载方案已归档",),
            completed=(),
            open_items=(),
            key_references=(),
            source_checkpoint_digest=post.token.removeprefix("sha256:"),
            source_fact_ids_digest="0" * 64,
        ).to_content(),
    )
    _save(
        replace(opened, snapshot=post),
        replace(
            post.state,
            revision=post.state.revision + 1,
            facts=(final_summary,),
        ),
    )
    catalog = HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=opened.snapshot.state.conversation_id,
        conversation_archive=archive,
        max_archive_reads_per_search=1,
    )

    first = catalog.search("ARGON_SENTINEL", limit=5)

    assert first.total_matches == 1
    assert first.coverage_complete is False
    assert first.continuation is not None
    assert first.hits[0].record.conversation_id == post.state.conversation_id
    assert first.hits[0].record.state_revision == post.state.revision
    assert first.hits[0].conflict is False
    assert "ARGON_SENTINEL" in first.hits[0].excerpt
    content, record, truncated, _snapshot_digest = catalog.get(
        first.hits[0].history_ref
    )
    assert "ARGON_SENTINEL" in content
    assert record.record_id == first.hits[0].record.record_id
    assert not truncated
    # 跨页进入更老的重叠 archive，stable fact 不得重复累计。
    completed = catalog.search(
        "ARGON_SENTINEL",
        limit=5,
        continuation=first.continuation,
    )
    assert completed.coverage_complete is True
    assert completed.total_matches == 1
    assert completed.hits[0].history_ref == first.hits[0].history_ref

    # fresh catalog 也必须确定性地产生同一 record/ref。
    restarted = HistoryCatalog(
        opened.checkpoint_path.parent,
        opened.workspace_binding,
        current_conversation_id=opened.snapshot.state.conversation_id,
        conversation_archive=archive,
        max_archive_reads_per_search=1,
    )
    restarted_first = restarted.search("ARGON_SENTINEL", limit=5)
    restarted_completed = restarted.search(
        "ARGON_SENTINEL",
        limit=5,
        continuation=restarted_first.continuation,
    )
    assert restarted_completed.hits[0].history_ref == first.hits[0].history_ref
    assert catalog.snapshot_digest() == catalog.snapshot_digest()


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
    assert history_search.input_schema["properties"]["continuation"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 96,
        "description": (
            "Opaque cursor returned by a prior partial history_search; reuse it "
            "with the same query and limit until coverage_complete is true."
        ),
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

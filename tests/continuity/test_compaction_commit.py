"""020 长会话压缩：archive-before-CAS 的 archive 原语唯一合同。

``archive_compaction_source(archive, source, reduced_state)`` 只做两件事：

- 前置验证（零副作用）：source 与 reduced 的 conversation_id、workspace
  binding exact 相等且双方都携带 binding、reduced revision 恰好 +1、
  reduced facts 恰好含一个合法 ``CONTEXT_SUMMARY``（位置无关：goal/evidence
  保护的 turns 原序保留在前，reducer 把 summary 插在最早被移除 fact 的
  原位置）且绑定 source token 的 ``sha256:`` 后 64hex、token 本身是闭合
  digest 形式；
- 归档：以 source checkpoint digest 为 identity 幂等写入完整原样的
  pre-compaction 状态。

本原语不接 CheckpointStore、不做 CAS：ConversationState checkpoint 的唯一
CAS owner 是 ``AgentRuntime``（其 ``_save`` 在 archive 成功之后执行）。提交
顺序、CAS conflict、lease 与 crash 证明位于 public run_turn 测试
（``tests/kernel/test_runtime_compaction.py``）。
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import replace
from pathlib import Path

import pytest

from agent.continuity.archive import ArchiveError, LocalConversationArchive
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import (
    ArchivedConversation,
    ConversationFact,
    ConversationState,
    ConversationSummaryV1,
    ConversationWorkspaceBindingV1,
    EvidenceOracleKind,
    FactKind,
    GoalFrame,
    GoalStatus,
    LoadedSnapshot,
    ProposedCriterion,
    canonical_json_digest,
)
from agent.runtime.ports import ConversationArchive
from agent.runtime.state import apply_compaction_summary

SCOPE = "ab" * 32
OTHER_SCOPE = "cd" * 32
CONVERSATION = "0f0e0d0c-1a2b-4c3d-8e9f-a1b2c3d4e5f6"
OTHER_CONVERSATION = "7c6b5a49-3d8e-4f90-9a0b-c1d2e3f4a5b6"

# 固定 token 形状：sha256: + 64 个小写 hex。
SOURCE_TOKEN = f"sha256:{'9' * 64}"
OTHER_DIGEST = "8" * 64

# reducer 合法移除集：无保护时是首 turn；goal 保护首 turn 时只能是第二
# turn，此时 summary 插在最早被移除 fact 的原位置（index 2）。
FIRST_TURN_REMOVABLE = ("action:1:user", "action:2:assistant")
SECOND_TURN_REMOVABLE = ("action:3:user", "action:4:assistant")


def _module():
    try:
        return importlib.import_module("agent.continuity.compaction")
    except ModuleNotFoundError:
        pytest.fail("020 requires agent.continuity.compaction")


def _archive_source():
    helper = getattr(_module(), "archive_compaction_source", None)
    if helper is None:
        pytest.fail(
            "020 requires agent.continuity.compaction.archive_compaction_source"
        )
    return helper


def _commit_error():
    error = getattr(_module(), "CompactionCommitError", None)
    if error is None:
        pytest.fail("020 requires agent.continuity.compaction.CompactionCommitError")
    return error


def _archive_error():
    error = getattr(_module(), "CompactionArchiveError", None)
    if error is None:
        pytest.fail("020 requires agent.continuity.compaction.CompactionArchiveError")
    return error


def test_module_no_longer_owns_cas_or_a_commit_alias() -> None:
    """CAS 唯一 owner 是 AgentRuntime：本模块不得保留旧提交原语。"""

    module = _module()
    assert not hasattr(module, "commit_compaction")
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "agent.runtime.ports":
            assert all(
                alias.name != "CheckpointStore" for alias in node.names
            ), "compaction.py must not import CheckpointStore"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "compare_and_swap", (
                "compaction.py must not call compare_and_swap"
            )


# --------------------------------------------------------------------------- #
# fixtures：真实 store/archive + recording fakes
# --------------------------------------------------------------------------- #


def _binding(scope: str = SCOPE) -> ConversationWorkspaceBindingV1:
    return ConversationWorkspaceBindingV1.create(
        workspace_scope_digest=scope,
        workspace_identity_digest=f"workspace:v1:{scope}",
        bound_at="2026-09-04T00:00:00Z",
    )


def _user(fact_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.USER_MESSAGE,
        content={"text": fact_id},
    )


def _assistant(fact_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.ASSISTANT_MESSAGE,
        content={"text": fact_id},
    )


def _source_state() -> ConversationState:
    """两个完整 closed turn 的 pre-compaction 状态，绑定 workspace。"""

    return replace(
        ConversationState.new(CONVERSATION, workspace_binding=_binding()),
        facts=(
            _user("action:1:user"),
            _assistant("action:2:assistant"),
            _user("action:3:user"),
            _assistant("action:4:assistant"),
        ),
        revision=4,
    )


def _goal() -> GoalFrame:
    """引用首 turn user fact 的 goal：使首 turn 受 compaction 保护。"""

    return GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=("action:1:user",),
        # 必须与 conversation workspace binding 的 identity digest 一致。
        workspace_identity_digest=f"workspace:v1:{SCOPE}",
        user_outcome="finish the workspace task",
        beneficiary="user",
        targets=("workspace",),
        scope=("workspace/fixtures",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                "criterion-1",
                "fixture note exists",
                EvidenceOracleKind.TOOL_RECEIPT,
            ),
        ),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=GoalStatus.EXECUTING,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


def _protected_source_state() -> ConversationState:
    """首 turn 被 goal 引用保护的非前缀可压缩布局。"""

    return replace(_source_state(), goal=_goal())


def _reduced_from(
    state: ConversationState,
    token_hex: str,
    *,
    removable: tuple[str, ...] = FIRST_TURN_REMOVABLE,
) -> ConversationState:
    """用真实 reducer 产出合法 reduced 状态，summary 绑定 token hex。"""

    summary = ConversationSummaryV1(
        objective="compact the first closed turn",
        constraints=(),
        decisions=(),
        completed=(),
        open_items=(),
        key_references=(),
        source_checkpoint_digest=token_hex,
        source_fact_ids_digest=canonical_json_digest(list(removable)),
    )
    return apply_compaction_summary(state, summary, removable)


def _open_store(
    tmp_path: Path,
    *,
    source_state: ConversationState | None = None,
    removable: tuple[str, ...] = FIRST_TURN_REMOVABLE,
) -> tuple[Path, LocalCheckpointStore, LoadedSnapshot, ConversationState]:
    """初始化真实 store 与 source snapshot；lease 归测试所有。"""

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    store = LocalCheckpointStore.initialize(
        state_root / "workspaces" / SCOPE / f"{CONVERSATION}.json",
        _source_state() if source_state is None else source_state,
    )
    source = store.load()
    reduced_state = _reduced_from(
        source.state,
        source.token.removeprefix("sha256:"),
        removable=removable,
    )
    return state_root, store, source, reduced_state


class _RecordingArchive:
    """记录并委托真实 archive；用于证明归档参数与幂等复用。"""

    def __init__(self, inner: ConversationArchive) -> None:
        self._inner = inner
        self.archive_calls: list[tuple[ConversationState, str, str]] = []
        self.records: list[ArchivedConversation] = []

    def archive(
        self,
        state: ConversationState,
        *,
        source_checkpoint_digest: str,
        workspace_scope_digest: str,
    ) -> ArchivedConversation:
        record = self._inner.archive(
            state,
            source_checkpoint_digest=source_checkpoint_digest,
            workspace_scope_digest=workspace_scope_digest,
        )
        self.archive_calls.append((state, source_checkpoint_digest, workspace_scope_digest))
        self.records.append(record)
        return record

    def list_archived(self, *, workspace_scope_digest: str):
        return self._inner.list_archived(workspace_scope_digest=workspace_scope_digest)

    def load_archived(self, archive: ArchivedConversation) -> LoadedSnapshot:
        return self._inner.load_archived(archive)


class _FailingArchive:
    """archive 阶段失败注入。"""

    def archive(
        self,
        state: ConversationState,
        *,
        source_checkpoint_digest: str,
        workspace_scope_digest: str,
    ) -> ArchivedConversation:
        raise ArchiveError("archive sink is unavailable")

    def list_archived(self, *, workspace_scope_digest: str):
        raise ArchiveError("archive sink is unavailable")

    def load_archived(self, archive: ArchivedConversation) -> LoadedSnapshot:
        raise ArchiveError("archive sink is unavailable")


class _ForbiddenArchive:
    """前置验证失败时 archive 必须零调用；被调用即协议违例。"""

    def archive(
        self,
        state: ConversationState,
        *,
        source_checkpoint_digest: str,
        workspace_scope_digest: str,
    ) -> ArchivedConversation:
        raise AssertionError("archive must not run after pre-validation failure")

    def list_archived(self, *, workspace_scope_digest: str):
        raise AssertionError("archive must not run after pre-validation failure")

    def load_archived(self, archive: ArchivedConversation) -> LoadedSnapshot:
        raise AssertionError("archive must not run after pre-validation failure")


def _assert_rejected(
    source_state: ConversationState,
    reduced_state: ConversationState,
    *,
    token: str = SOURCE_TOKEN,
) -> None:
    with pytest.raises(_commit_error()):
        _archive_source()(_ForbiddenArchive(), LoadedSnapshot(source_state, token), reduced_state)


# --------------------------------------------------------------------------- #
# 成功路径：恰一次无损归档，active checkpoint 不被触碰
# --------------------------------------------------------------------------- #


def test_archives_full_source_once_and_returns_none(tmp_path: Path) -> None:
    state_root, store, source, reduced_state = _open_store(tmp_path)
    archive = _RecordingArchive(LocalConversationArchive(state_root))

    result = _archive_source()(archive, source, reduced_state)

    # 本原语只归档：恰一次、返回 None。
    assert result is None
    (archived_state, digest, scope), = archive.archive_calls
    assert archived_state == source.state
    assert digest == source.token
    assert scope == SCOPE
    # active checkpoint 原样保留：CAS 属于 Runtime，不属于本原语。
    assert store.load() == source


def test_archive_is_lossless_pre_compaction_source(tmp_path: Path) -> None:
    state_root, _store, source, reduced_state = _open_store(tmp_path)
    archive = _RecordingArchive(LocalConversationArchive(state_root))

    _archive_source()(archive, source, reduced_state)

    record, = archive.records
    restored = archive.load_archived(record)
    assert restored == source
    assert restored.state == source.state
    assert restored.token == source.token


def test_accepts_goal_protected_prefix_with_summary_at_index_two(
    tmp_path: Path,
) -> None:
    """非前缀布局：goal 保护首 turn，summary 固定插在最早被移除位置。"""

    state_root, _store, source, reduced_state = _open_store(
        tmp_path,
        source_state=_protected_source_state(),
        removable=SECOND_TURN_REMOVABLE,
    )
    # 真实 reducer 的产出形状：protected turn 原序保留在前，summary 在
    # index 2 且绑定 source token，绝不在 facts[0]。校验必须位置无关。
    assert tuple(fact.kind for fact in reduced_state.facts) == (
        FactKind.USER_MESSAGE,
        FactKind.ASSISTANT_MESSAGE,
        FactKind.CONTEXT_SUMMARY,
    )
    summary = ConversationSummaryV1.from_content(reduced_state.facts[2].content)
    assert summary.source_checkpoint_digest == source.token.removeprefix("sha256:")
    archive = _RecordingArchive(LocalConversationArchive(state_root))

    _archive_source()(archive, source, reduced_state)

    (archived_state, digest, scope), = archive.archive_calls
    assert archived_state == source.state
    assert digest == source.token
    assert scope == SCOPE


def test_replay_with_same_source_digest_reuses_the_same_archive(tmp_path: Path) -> None:
    state_root, _store, source, reduced_state = _open_store(tmp_path)
    archive = _RecordingArchive(LocalConversationArchive(state_root))

    _archive_source()(archive, source, reduced_state)
    # 崩溃/重放：同一 source digest 再次归档。archive 幂等复用同一 record。
    _archive_source()(archive, source, reduced_state)

    first, second = archive.records
    assert first == second
    assert archive.load_archived(first) == source
    assert archive.list_archived(workspace_scope_digest=SCOPE) == (first,)


def test_archive_failure_is_normalized_without_other_effects(tmp_path: Path) -> None:
    state_root, store, source, reduced_state = _open_store(tmp_path)

    with pytest.raises(_archive_error()) as captured:
        _archive_source()(_FailingArchive(), source, reduced_state)

    assert isinstance(captured.value.__cause__, ArchiveError)

    # archive port 异常作为 cause 保留；本原语没有其他副作用可失败。
    assert store.load() == source


# --------------------------------------------------------------------------- #
# 前置验证 fail closed：零副作用拒绝
# --------------------------------------------------------------------------- #


def test_rejects_conversation_identity_mismatch() -> None:
    source = _source_state()
    reduced = _reduced_from(source, SOURCE_TOKEN.removeprefix("sha256:"))
    _assert_rejected(source, replace(reduced, conversation_id=OTHER_CONVERSATION))


def test_rejects_workspace_binding_mismatch() -> None:
    source = _source_state()
    reduced = _reduced_from(source, SOURCE_TOKEN.removeprefix("sha256:"))
    _assert_rejected(source, replace(reduced, workspace_binding=_binding(OTHER_SCOPE)))


def test_rejects_missing_workspace_binding_on_either_side() -> None:
    source = _source_state()
    reduced = _reduced_from(source, SOURCE_TOKEN.removeprefix("sha256:"))
    _assert_rejected(replace(source, workspace_binding=None), reduced)
    _assert_rejected(source, replace(reduced, workspace_binding=None))


def test_rejects_revision_other_than_exactly_one_step() -> None:
    source = _source_state()
    reduced = _reduced_from(source, SOURCE_TOKEN.removeprefix("sha256:"))
    _assert_rejected(source, replace(reduced, revision=source.revision + 2))
    _assert_rejected(source, replace(reduced, revision=source.revision))


def test_rejects_reduced_facts_without_context_summary() -> None:
    source = _source_state()
    reduced = _reduced_from(source, SOURCE_TOKEN.removeprefix("sha256:"))
    # 摘掉 summary facts 的负例必须同时摘掉其 Runtime-owned 来源边界，
    # 否则 ConversationState 的闭合不变量会先于 commit 校验拒绝构造。
    _assert_rejected(
        source, replace(reduced, facts=(), summary_source_boundaries=())
    )
    _assert_rejected(
        source,
        replace(
            reduced, facts=(_user("action:9:user"),), summary_source_boundaries=()
        ),
    )


def test_rejects_reduced_facts_with_multiple_context_summaries() -> None:
    source = _protected_source_state()
    reduced = _reduced_from(
        source,
        SOURCE_TOKEN.removeprefix("sha256:"),
        removable=SECOND_TURN_REMOVABLE,
    )
    # 两个 summary content 都合法且绑定正确 digest，但数量必须恰好一个。
    doubled = (
        *reduced.facts,
        replace(reduced.facts[2], fact_id="fact:context-summary:second"),
    )
    _assert_rejected(source, replace(reduced, facts=doubled))


def test_rejects_malformed_summary_content() -> None:
    source = _protected_source_state()
    reduced = _reduced_from(
        source,
        SOURCE_TOKEN.removeprefix("sha256:"),
        removable=SECOND_TURN_REMOVABLE,
    )
    malformed = (
        # 非首位的 malformed summary：证明校验扫描全部 facts，而非只看
        # facts[0]。content 缺字段，不满足闭合 summary 形状。
        *reduced.facts[:2],
        ConversationFact(
            fact_id="fact:context-summary:malformed",
            kind=FactKind.CONTEXT_SUMMARY,
            content={"objective": "not a closed summary shape"},
        ),
    )
    # 同上：malformed 负例替换了 summary fact_id，需同步摘掉旧边界再构造。
    _assert_rejected(
        source, replace(reduced, facts=malformed, summary_source_boundaries=())
    )


def test_rejects_summary_not_bound_to_source_token() -> None:
    # 非前缀布局下扫描到 index 2 的 summary，但绑定了别的 digest。
    source = _protected_source_state()
    reduced = _reduced_from(
        source,
        OTHER_DIGEST,
        removable=SECOND_TURN_REMOVABLE,
    )
    _assert_rejected(source, reduced)


def test_rejects_malformed_source_token() -> None:
    source = _source_state()
    reduced = _reduced_from(source, SOURCE_TOKEN.removeprefix("sha256:"))
    _assert_rejected(source, reduced, token=OTHER_DIGEST)
    _assert_rejected(source, reduced, token=f"sha256:{'9' * 63}A")

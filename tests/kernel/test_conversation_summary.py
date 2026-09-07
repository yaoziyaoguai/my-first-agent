"""020 长会话压缩 Slice A1：ConversationSummaryV1 闭合合同与 checkpoint round-trip。

summary 是 untrusted context data（计划 §3.2）：闭合形状只有 8 个字段，无法携带
Goal/Evidence/Approval/Recovery 等 canonical authority 字段；未知键、空内容、
条目/字符超限、非 JSON、tool/control block 一律拒绝。下列 Red 在合同落地前因
contract 不存在而准确失败；用 getattr + pytest.fail 守卫保证失败是干净断言而非
collection 期 import error。
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

import agent.runtime.checkpoint as checkpoint
import agent.runtime.contracts as contracts
from agent.runtime.contracts import (
    ConversationFact,
    ConversationState,
    FactKind,
)
from tests.kernel.fakes import conversation_with_active_goal


def _summary_type() -> type:
    summary_type = getattr(contracts, "ConversationSummaryV1", None)
    if summary_type is None:
        pytest.fail("020 requires contracts.ConversationSummaryV1")
    return summary_type


def _required_limit(name: str) -> int:
    limit = getattr(contracts, name, None)
    if not isinstance(limit, int):
        pytest.fail(f"020 requires contracts.{name}")
    return limit


def _fixture_kwargs() -> dict:
    return dict(
        objective="Ship the bounded conversation summary contract.",
        constraints=("no second model/tool loop",),
        decisions=("keep ToolRuntime as the only callable owner",),
        completed=("summary shape closed",),
        open_items=("archive port still pending",),
        key_references=("docs/plans/2026-09-04-001",),
        source_checkpoint_digest="a" * 64,
        source_fact_ids_digest="b" * 64,
    )


def _fixture_summary():
    return _summary_type()(**_fixture_kwargs())


# --------------------------------------------------------------------------- #
# FactKind 与闭合字段
# --------------------------------------------------------------------------- #


def test_context_summary_fact_kind_exists() -> None:
    assert FactKind.CONTEXT_SUMMARY.value == "context_summary"


def test_summary_shape_is_closed_to_the_plan_fields() -> None:
    summary = _fixture_summary()
    assert tuple(field.name for field in fields(summary)) == (
        "objective",
        "constraints",
        "decisions",
        "completed",
        "open_items",
        "key_references",
        "source_checkpoint_digest",
        "source_fact_ids_digest",
    )


def test_summary_json_and_content_round_trip() -> None:
    summary = _fixture_summary()

    parsed = _summary_type().from_json(summary.to_json())
    assert parsed == summary
    assert _summary_type().from_content(summary.to_content()) == summary
    # to_json 输出 canonical 形式，from_json 也接受普通（非 canonical）JSON 文本。
    relaxed = json.dumps(_fixture_kwargs())
    assert _summary_type().from_json(relaxed) == summary


# --------------------------------------------------------------------------- #
# 严格校验：未知键 / 缺失字段 / 非 JSON / 空 content
# --------------------------------------------------------------------------- #


def test_summary_rejects_unknown_and_missing_fields() -> None:
    summary_type = _summary_type()
    raw = _fixture_summary().to_json()

    with_unknown = json.loads(raw)
    with_unknown["goal"] = {"goal_id": "goal-1"}
    with pytest.raises(ValueError, match="unknown or missing"):
        summary_type.from_json(json.dumps(with_unknown))

    missing_field = json.loads(raw)
    del missing_field["source_fact_ids_digest"]
    with pytest.raises(ValueError, match="unknown or missing"):
        summary_type.from_content(missing_field)


def test_summary_rejects_non_json_payload() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        _summary_type().from_json("not-json-at-all")
    # 合法 JSON 但不是 object / 字段形状不闭合。
    with pytest.raises(ValueError):
        _summary_type().from_json("[1, 2, 3]")
    with pytest.raises(ValueError):
        _summary_type().from_content(None)


def test_summary_rejects_empty_content() -> None:
    summary_type = _summary_type()
    kwargs = _fixture_kwargs()

    for empty_objective in ("", "   \n\t "):
        with pytest.raises(ValueError, match="objective"):
            summary_type(**{**kwargs, "objective": empty_objective})

    blank_item = {**kwargs, "completed": ("",)}
    with pytest.raises(ValueError, match="completed"):
        summary_type(**blank_item)

    raw = json.loads(_fixture_summary().to_json())
    raw["objective"] = ""
    with pytest.raises(ValueError, match="objective"):
        summary_type.from_content(raw)


# --------------------------------------------------------------------------- #
# 条目与字符上限
# --------------------------------------------------------------------------- #


def test_summary_enforces_text_limits() -> None:
    summary_type = _summary_type()
    kwargs = _fixture_kwargs()
    objective_limit = _required_limit("CONVERSATION_SUMMARY_OBJECTIVE_LIMIT")
    item_limit = _required_limit("CONVERSATION_SUMMARY_ITEM_TEXT_LIMIT")

    assert summary_type(**{**kwargs, "objective": "x" * objective_limit})
    with pytest.raises(ValueError, match="objective"):
        summary_type(**{**kwargs, "objective": "x" * (objective_limit + 1)})

    assert summary_type(**{**kwargs, "decisions": ("y" * item_limit,)})
    with pytest.raises(ValueError, match="decisions"):
        summary_type(**{**kwargs, "decisions": ("y" * (item_limit + 1),)})


def test_summary_enforces_item_count_limit() -> None:
    summary_type = _summary_type()
    kwargs = _fixture_kwargs()
    item_count_limit = _required_limit("CONVERSATION_SUMMARY_ITEM_COUNT_LIMIT")

    at_limit = {**kwargs, "open_items": ("item",) * item_count_limit}
    assert summary_type(**at_limit)
    over_limit = {**kwargs, "open_items": ("item",) * (item_count_limit + 1)}
    with pytest.raises(ValueError, match="open_items"):
        summary_type(**over_limit)


# --------------------------------------------------------------------------- #
# tool/control block 与 digest 字段
# --------------------------------------------------------------------------- #


def test_summary_rejects_tool_and_control_blocks() -> None:
    summary_type = _summary_type()
    kwargs = _fixture_kwargs()

    tool_block = {"type": "tool_call", "tool_call_id": "call-1", "name": "local_process"}
    with pytest.raises(ValueError, match="constraints"):
        summary_type(**{**kwargs, "constraints": (tool_block,)})

    control_block = {"type": "control", "control": "first_agent_control_v1"}
    raw = json.loads(_fixture_summary().to_json())
    raw["open_items"] = [control_block]
    with pytest.raises(ValueError, match="open_items"):
        summary_type.from_content(raw)

    with pytest.raises(ValueError):
        summary_type(**{**kwargs, "objective": tool_block})


def test_summary_digest_fields_must_be_sha256_hex() -> None:
    summary_type = _summary_type()
    kwargs = _fixture_kwargs()

    for bad_digest in ("nothex", "a" * 63, "A" * 64, "g" * 64):
        with pytest.raises(ValueError, match="source_checkpoint_digest"):
            summary_type(**{**kwargs, "source_checkpoint_digest": bad_digest})
        with pytest.raises(ValueError, match="source_fact_ids_digest"):
            summary_type(**{**kwargs, "source_fact_ids_digest": bad_digest})


# --------------------------------------------------------------------------- #
# summary 无法覆盖 canonical state 字段
# --------------------------------------------------------------------------- #


def test_summary_cannot_carry_canonical_authority_fields() -> None:
    summary_type = _summary_type()
    raw = json.loads(_fixture_summary().to_json())

    for authority_field in (
        "goal",
        "goal_authorizations",
        "evidence_records",
        "completion_claim",
        "approval",
        "recovery",
    ):
        injected = {**raw, authority_field: {"injected": True}}
        with pytest.raises(ValueError, match="unknown or missing"):
            summary_type.from_content(injected)


def test_context_summary_fact_does_not_touch_canonical_state() -> None:
    summary = _fixture_summary()
    state = conversation_with_active_goal("conversation-1")

    summary_fact = ConversationFact(
        fact_id="summary:v1:fixture",
        kind=FactKind.CONTEXT_SUMMARY,
        content=summary.to_content(),
    )
    compacted = replace(state, facts=(*state.facts, summary_fact))

    # summary 只是 context fact：canonical Goal/authority/evidence/claim 原样保留。
    assert compacted.goal is state.goal
    assert compacted.goal_authorizations == state.goal_authorizations
    assert compacted.evidence_records == state.evidence_records
    assert compacted.completion_claim is state.completion_claim
    assert _summary_type().from_content(compacted.facts[-1].content) == summary


# --------------------------------------------------------------------------- #
# checkpoint JSON round-trip
# --------------------------------------------------------------------------- #


def _state_with_summary_fact() -> ConversationState:
    summary = _fixture_summary()
    return replace(
        conversation_with_active_goal("conversation-1"),
        facts=(
            ConversationFact(
                fact_id="action:1:user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "please persist the fixture note"},
            ),
            ConversationFact(
                fact_id="summary:v1:fixture",
                kind=FactKind.CONTEXT_SUMMARY,
                content=summary.to_content(),
            ),
        ),
    )


def test_context_summary_fact_round_trips_through_local_store(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "conversation.json"
    state = _state_with_summary_fact()
    store = checkpoint.LocalCheckpointStore.initialize(state_path, state)

    loaded = store.load().state
    assert loaded.facts == state.facts
    assert loaded.goal == state.goal
    restored = _summary_type().from_content(loaded.facts[-1].content)
    assert restored.to_json() == _fixture_summary().to_json()

    lease = store.try_acquire("conversation-1")
    assert lease is not None
    lease.release()


def test_context_summary_fact_round_trips_through_memory_cas() -> None:
    state = _state_with_summary_fact()
    store = checkpoint.InMemoryCheckpointStore(state)
    snapshot = store.load()

    lease = store.try_acquire("conversation-1")
    assert lease is not None
    compacted = replace(state, revision=state.revision + 1)
    saved = store.compare_and_swap(snapshot, compacted)

    assert saved.state.facts == state.facts
    assert (
        _summary_type().from_content(saved.state.facts[-1].content).to_json()
        == _fixture_summary().to_json()
    )
    lease.release()


def test_checkpoint_rejects_malformed_context_summary_content(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "conversation.json"
    store = checkpoint.LocalCheckpointStore.initialize(
        state_path,
        _state_with_summary_fact(),
    )
    document = json.loads(state_path.read_text(encoding="utf-8"))
    facts = document["state"]["facts"]
    assert facts[-1]["kind"] == "context_summary"

    malformed_variants = (
        {"objective": ""},
        {**_fixture_summary().to_content(), "goal": {"goal_id": "goal-1"}},
        {**_fixture_summary().to_content(), "open_items": ["item"] * 32},
        {**_fixture_summary().to_content(), "source_checkpoint_digest": "nothex"},
    )
    for malformed in malformed_variants:
        facts[-1]["content"] = malformed
        state_path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(checkpoint.CheckpointInvariantError):
            store.load()


def test_cas_rejects_malformed_context_summary_fact() -> None:
    _summary_type()
    state = conversation_with_active_goal("conversation-1")
    # 空 summary 不得进入持久化（完整键集，仅 objective 为空）。
    bad_fact = ConversationFact(
        fact_id="summary:v1:bad",
        kind=FactKind.CONTEXT_SUMMARY,
        content={**_fixture_summary().to_content(), "objective": ""},
    )
    store = checkpoint.InMemoryCheckpointStore(state)
    snapshot = store.load()
    lease = store.try_acquire("conversation-1")
    assert lease is not None

    with pytest.raises(ValueError, match="objective"):
        store.compare_and_swap(
            snapshot,
            replace(state, facts=(*state.facts, bad_fact)),
        )
    lease.release()

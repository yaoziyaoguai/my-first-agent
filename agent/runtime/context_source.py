"""单次 Context build 内的 source receipt 校验与投影。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from agent.runtime.contracts import (
    ConversationFact,
    ConversationState,
    FactKind,
    SourceReceiptV1,
)


class ContextLimitError(Exception):
    code = "context_core_too_large"


@dataclass(frozen=True, slots=True)
class ToolResultSourceProjection:
    """一个 TOOL_RESULT 经完整校验后的 build-local 只读投影。"""

    receipts: tuple[SourceReceiptV1, ...]
    data_classes: tuple[str, ...]
    source_refs: tuple[str, ...]
    citation_sources: tuple[tuple[str, str], ...]

    def wire_contexts(self) -> tuple[dict[str, object], ...]:
        """投影模型判断信任边界所需的最小来源描述，不暴露内部 receipt。"""

        return tuple(
            {
                "source_ref": source_ref,
                "source_kind": receipt.source_kind.value,
                "origin_locator": receipt.origin_locator,
                "observed_at": receipt.observed_at,
                "truncated": receipt.truncated,
            }
            for source_ref, receipt in zip(
                self.source_refs,
                self.receipts,
                strict=True,
            )
        )


_GENERIC_PROJECTION = ToolResultSourceProjection(
    receipts=(),
    data_classes=("tool_results",),
    source_refs=(),
    citation_sources=(),
)


def project_tool_result_sources(
    facts: tuple[ConversationFact, ...],
    state: ConversationState,
) -> tuple[
    tuple[ConversationFact, ...],
    dict[str, ToolResultSourceProjection],
]:
    """每个 durable receipt 只解析一次，再按活跃 Goal 投影。"""

    projected_facts: list[ConversationFact] = []
    projections: dict[str, ToolResultSourceProjection] = {}
    for fact in facts:
        if fact.kind is not FactKind.TOOL_RESULT:
            projected_facts.append(fact)
            continue

        projection = _validate_tool_result(fact, state.conversation_id)
        projected_fact = fact
        goal = state.goal
        if goal is not None and projection.receipts:
            kept = tuple(
                receipt
                for receipt in projection.receipts
                if receipt.goal_id == goal.goal_id
                and receipt.goal_revision == goal.revision
            )
            if not kept:
                projected_fact = _omit_stale_source_result(fact)
                projection = _GENERIC_PROJECTION
            elif kept != projection.receipts:
                projected_fact = _replace_receipts(fact, kept)
                projection = _projection_from_receipts(kept)

        projected_facts.append(projected_fact)
        projections[projected_fact.fact_id] = projection
    return tuple(projected_facts), projections


def _validate_tool_result(
    fact: ConversationFact,
    conversation_id: str,
) -> ToolResultSourceProjection:
    metadata = fact.content.get("metadata")
    if not isinstance(metadata, dict):
        return _GENERIC_PROJECTION
    if "source_receipts" not in metadata:
        if metadata.get("source_refs") not in (None, []):
            raise ContextLimitError("citation source mapping is invalid")
        return _GENERIC_PROJECTION

    raw_receipts = metadata.get("source_receipts")
    if not isinstance(raw_receipts, list):
        raise ContextLimitError("source receipt collection is invalid")
    if not raw_receipts:
        raw_refs = metadata.get("source_refs")
        if raw_refs not in (None, []):
            raise ContextLimitError("citation source mapping is incomplete")
        return _GENERIC_PROJECTION

    try:
        receipts = tuple(SourceReceiptV1.from_json(raw) for raw in raw_receipts)
    except ValueError as error:
        raise ContextLimitError("source receipt is invalid") from error
    if any(receipt.conversation_id != conversation_id for receipt in receipts):
        raise ContextLimitError("source receipt conversation mismatch")

    projection = _projection_from_receipts(receipts)
    if metadata.get("data_classes") != list(projection.data_classes):
        raise ContextLimitError("source receipt data classes are inconsistent")
    expected_refs = [
        {"source_ref": source_ref, "receipt_digest": receipt.receipt_digest}
        for source_ref, receipt in zip(
            projection.source_refs,
            projection.receipts,
            strict=True,
        )
    ]
    if metadata.get("source_refs") != expected_refs:
        raise ContextLimitError("source ref mapping is inconsistent")
    return projection


def _projection_from_receipts(
    receipts: tuple[SourceReceiptV1, ...],
) -> ToolResultSourceProjection:
    source_refs = tuple(
        f"source-ref:v1:{receipt.receipt_digest}" for receipt in receipts
    )
    return ToolResultSourceProjection(
        receipts=receipts,
        data_classes=tuple(sorted({receipt.data_class for receipt in receipts})),
        source_refs=source_refs,
        citation_sources=tuple(
            (source_ref, receipt.source_id)
            for source_ref, receipt in zip(source_refs, receipts, strict=True)
        ),
    )


def _omit_stale_source_result(fact: ConversationFact) -> ConversationFact:
    content = dict(fact.content)
    content.update(
        {
            "text": (
                "Source result omitted because it is not bound to "
                "the active Goal revision."
            ),
            "metadata": {
                "source_receipts": [],
                "data_classes": [],
                "source_refs": [],
                "truncated": False,
                "omitted_reason": "stale_goal_binding",
            },
        }
    )
    return replace(fact, content=content)


def _replace_receipts(
    fact: ConversationFact,
    receipts: tuple[SourceReceiptV1, ...],
) -> ConversationFact:
    metadata = fact.content.get("metadata")
    if not isinstance(metadata, dict):
        raise ContextLimitError("source receipt metadata is invalid")
    projected_metadata = dict(metadata)
    projected_metadata.update(
        {
            "source_receipts": [
                {**asdict(receipt), "source_kind": receipt.source_kind.value}
                for receipt in receipts
            ],
            "data_classes": sorted({receipt.data_class for receipt in receipts}),
            "source_refs": [
                {
                    "source_ref": f"source-ref:v1:{receipt.receipt_digest}",
                    "receipt_digest": receipt.receipt_digest,
                }
                for receipt in receipts
            ],
            "truncated": any(receipt.truncated for receipt in receipts),
        }
    )
    content = dict(fact.content)
    content["metadata"] = projected_metadata
    return replace(fact, content=content)

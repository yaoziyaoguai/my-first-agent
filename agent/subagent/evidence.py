"""Child workspace source receipt 的提取与父侧 freshness 复验。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agent.runtime.contracts import (
    ConversationState,
    FactKind,
    SourceKind,
    SourceReceiptV1,
)
from agent.subagent.contracts import ChildSourceEvidence
from agent.tools.file_ops import DEFAULT_FILE_LIMIT_BYTES
from agent.tools.path_safety import WorkspaceBoundary

_LINE_LOCATOR = re.compile(r"^(?P<path>.+)#L(?P<start>[1-9]\d*)(?:-L(?P<end>[1-9]\d*))?$")


def verified_child_sources_from_state(
    state: ConversationState,
    *,
    workspace_root: Path | None,
    protected_paths: tuple[Path, ...],
) -> tuple[ChildSourceEvidence, ...]:
    """只接受当前 child checkpoint 中由 Kernel 铸造、且文件仍新鲜的 receipt。"""
    if workspace_root is None:
        return ()
    expected_run_id = state.last_safe_result.run_id if state.last_safe_result else None
    candidates: list[ChildSourceEvidence] = []
    seen: set[str] = set()
    for fact in state.facts:
        if fact.kind is not FactKind.TOOL_RESULT:
            continue
        metadata = fact.content.get("metadata")
        raw_receipts = metadata.get("source_receipts") if isinstance(metadata, dict) else None
        if not isinstance(raw_receipts, list):
            continue
        for raw in raw_receipts:
            try:
                receipt = SourceReceiptV1.from_json(raw)
            except ValueError:
                continue
            if (
                receipt.source_kind is not SourceKind.WORKSPACE_EXCERPT
                or receipt.conversation_id != state.conversation_id
                or (expected_run_id is not None and receipt.run_id != expected_run_id)
                or receipt.snapshot_digest is None
                or receipt.truncated
                or receipt.receipt_digest in seen
            ):
                continue
            candidates.append(
                ChildSourceEvidence(
                    locator=receipt.origin_locator,
                    snapshot_digest=receipt.snapshot_digest,
                    content_digest=receipt.content_digest,
                    receipt_digest=receipt.receipt_digest,
                    truncated=False,
                )
            )
            seen.add(receipt.receipt_digest)
            if len(candidates) >= 16:
                break
    return filter_current_child_sources(
        candidates,
        workspace_root=workspace_root,
        protected_paths=protected_paths,
    )


def filter_current_child_sources(
    sources: list[ChildSourceEvidence] | tuple[ChildSourceEvidence, ...],
    *,
    workspace_root: Path | None,
    protected_paths: tuple[Path, ...],
) -> tuple[ChildSourceEvidence, ...]:
    """父侧按当前文件快照复验 child source；过期、越界或畸形来源静默剔除。"""
    if workspace_root is None:
        return ()
    boundary = WorkspaceBoundary(workspace_root, protected_paths=protected_paths)
    verified: list[ChildSourceEvidence] = []
    for source in sources[:16]:
        if source.truncated:
            continue
        locator_match = _LINE_LOCATOR.fullmatch(source.locator)
        path = (
            locator_match.group("path")
            if locator_match is not None
            else source.locator
        )
        try:
            document = boundary.read_document(path, max_bytes=DEFAULT_FILE_LIMIT_BYTES)
        except (OSError, UnicodeError, ValueError, RuntimeError):
            continue
        if document.snapshot_digest != source.snapshot_digest:
            continue
        if not any(
            hashlib.sha256(candidate.encode("utf-8")).hexdigest()
            == source.content_digest
            for candidate in _locator_content_candidates(document.content, locator_match)
        ):
            continue
        verified.append(source)
    return tuple(verified)


def _locator_content_candidates(content: str, match) -> tuple[str, ...]:  # noqa: ANN001
    if match is None:
        return (content,)
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    lines_with_ends = content.splitlines(keepends=True)
    selected = "".join(lines_with_ends[start - 1 : end])
    if end == start:
        return (selected, selected.rstrip("\r\n"))
    return (selected,)

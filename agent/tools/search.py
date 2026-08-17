"""WorkspaceBoundary 上的 bounded source-producing file/search operations。"""

from __future__ import annotations

import json

from agent.runtime.contracts import (
    ExecutionIntent,
    SourceKind,
    SourceReceiptDraft,
    ToolExecutionOutput,
)
from agent.tools.path_safety import (
    PathMatch,
    TextMatch,
    TraversalLimits,
    WorkspaceBoundary,
)


def read_file_output(
    boundary: WorkspaceBoundary,
    intent: ExecutionIntent,
    *,
    max_bytes: int,
) -> ToolExecutionOutput:
    document = boundary.read_document(intent.arguments["path"], max_bytes=max_bytes)
    return ToolExecutionOutput(
        content=document.content,
        metadata={
            "path": document.path,
            "encoding": document.encoding,
            "snapshot_digest": document.snapshot_digest,
            "truncated": False,
        },
        source_receipts=(
            SourceReceiptDraft(
                source_kind=SourceKind.WORKSPACE_EXCERPT,
                origin_locator=document.path,
                title=document.path,
                content=document.content,
                observed_at=document.observed_at,
                snapshot_digest=document.snapshot_digest,
                original_content_digest=document.content_digest,
            ),
        ),
    )


def list_files_output(
    boundary: WorkspaceBoundary,
    intent: ExecutionIntent,
    *,
    max_entries: int,
    max_scan_entries: int,
    max_output_chars: int,
) -> ToolExecutionOutput:
    listing = boundary.list_entries_bounded(
        intent.arguments["path"],
        max_entries=max_entries,
        max_scan_entries=max_scan_entries,
        max_output_chars=max_output_chars,
    )
    content = "\n".join(listing.entries)
    return ToolExecutionOutput(
        content=content,
        metadata={
            "path": listing.path,
            "snapshot_digest": listing.snapshot_digest,
            "truncated": listing.truncated,
            "truncation_reason": listing.truncation_reason,
        },
        source_receipts=(
            SourceReceiptDraft(
                source_kind=SourceKind.WORKSPACE_PATH,
                origin_locator=listing.path,
                title=f"Directory listing: {listing.path}",
                content=content,
                observed_at="filesystem_snapshot",
                snapshot_digest=listing.snapshot_digest,
                truncated=listing.truncated,
                truncation_reason=listing.truncation_reason,
            ),
        ),
    )


def search_paths_output(
    boundary: WorkspaceBoundary,
    intent: ExecutionIntent,
    *,
    limits: TraversalLimits,
) -> ToolExecutionOutput:
    result = boundary.search_paths(
        intent.arguments["query"],
        root=intent.arguments.get("root", "."),
        max_results=intent.arguments.get("max_results", limits.max_matches),
        limits=limits,
    )
    matches = tuple(match for match in result.matches if isinstance(match, PathMatch))
    payload = {
        "status": "matches" if matches else "no_match",
        "results": [{"path": match.path, "kind": match.kind} for match in matches],
        "truncated": result.truncated,
        "truncation_reason": result.truncation_reason,
    }
    return ToolExecutionOutput(
        content=_json(payload),
        metadata=_search_metadata(result),
        source_receipts=tuple(
            SourceReceiptDraft(
                source_kind=SourceKind.WORKSPACE_PATH,
                origin_locator=match.path,
                title=match.path,
                content=match.path,
                observed_at=match.observed_at,
                snapshot_digest=match.snapshot_digest,
                truncated=result.truncated,
                truncation_reason=result.truncation_reason,
            )
            for match in matches
        ),
    )


def search_text_output(
    boundary: WorkspaceBoundary,
    intent: ExecutionIntent,
    *,
    limits: TraversalLimits,
) -> ToolExecutionOutput:
    result = boundary.search_text(
        intent.arguments["query"],
        root=intent.arguments.get("root", "."),
        max_results=intent.arguments.get("max_results", limits.max_matches),
        limits=limits,
    )
    matches = tuple(match for match in result.matches if isinstance(match, TextMatch))
    payload = {
        "status": "matches" if matches else "no_match",
        "results": [
            {
                "path": match.path,
                "line": match.line,
                "snippet": match.snippet,
                "encoding": match.encoding,
                "truncated": match.truncated,
            }
            for match in matches
        ],
        "truncated": result.truncated,
        "truncation_reason": result.truncation_reason,
    }
    return ToolExecutionOutput(
        content=_json(payload),
        metadata=_search_metadata(result),
        source_receipts=tuple(
            SourceReceiptDraft(
                source_kind=SourceKind.WORKSPACE_EXCERPT,
                origin_locator=f"{match.path}#L{match.line}",
                title=f"{match.path}:{match.line}",
                content=match.snippet,
                observed_at=match.observed_at,
                snapshot_digest=match.snapshot_digest,
                truncated=match.truncated or result.truncated,
                truncation_reason=(
                    "snippet_chars"
                    if match.truncated and not result.truncated
                    else result.truncation_reason
                ),
            )
            for match in matches
        ),
    )


def read_file_chunk_output(
    boundary: WorkspaceBoundary,
    intent: ExecutionIntent,
    *,
    max_bytes: int,
    max_line_cap: int,
) -> ToolExecutionOutput:
    chunk = boundary.read_file_chunk(
        intent.arguments["path"],
        start_line=intent.arguments["start_line"],
        max_lines=intent.arguments["max_lines"],
        max_bytes=max_bytes,
        max_line_cap=max_line_cap,
    )
    locator = (
        f"{chunk.path}#L{chunk.start_line}-L{chunk.end_line}"
        if chunk.end_line >= chunk.start_line
        else f"{chunk.path}#L{chunk.start_line}"
    )
    payload = {
        "path": chunk.path,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "content": chunk.content,
        "encoding": chunk.encoding,
        "truncated": chunk.truncated,
    }
    return ToolExecutionOutput(
        content=_json(payload),
        metadata={
            "path": chunk.path,
            "snapshot_digest": chunk.snapshot_digest,
            "truncated": chunk.truncated,
            "truncation_reason": "line_window" if chunk.truncated else None,
        },
        source_receipts=(
            SourceReceiptDraft(
                source_kind=SourceKind.WORKSPACE_EXCERPT,
                origin_locator=locator,
                title=locator,
                content=chunk.content,
                observed_at=chunk.observed_at,
                snapshot_digest=chunk.snapshot_digest,
                original_content_digest=chunk.original_content_digest,
                truncated=chunk.truncated,
                truncation_reason="line_window" if chunk.truncated else None,
            ),
        ),
    )


def _search_metadata(result) -> dict:  # noqa: ANN001
    return {
        "status": "matches" if result.matches else "no_match",
        "snapshot_digest": result.snapshot_digest,
        "truncated": result.truncated,
        "truncation_reason": result.truncation_reason,
        "scanned_entries": result.scanned_entries,
        "opened_files": result.opened_files,
        "total_bytes": result.total_bytes,
    }


def _json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

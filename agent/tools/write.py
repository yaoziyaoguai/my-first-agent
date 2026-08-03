"""Approval-bound atomic write implementation."""

from __future__ import annotations

import hashlib

from agent.tools.path_safety import WorkspaceBoundary


def prepare_write_binding(
    boundary: WorkspaceBoundary,
    *,
    path: str,
    content: str,
    max_bytes: int,
) -> dict:
    binding, _ = boundary.inspect_mutation(path, max_bytes=max_bytes)
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValueError("new content exceeds the configured write bound")
    return {
        **binding,
        "new_content_digest": hashlib.sha256(encoded).hexdigest(),
        "effect_preview": f"write {path} ({len(encoded)} bytes)",
    }


def write_file(boundary: WorkspaceBoundary, *, path: str, content: str) -> str:
    encoded = content.encode("utf-8")
    boundary.atomic_replace(path, encoded)
    return f"wrote {path} ({len(encoded)} bytes)"

"""Approval-bound exact text edit implementation."""

from __future__ import annotations

import hashlib

from agent.tools.path_safety import WorkspaceBoundary, WorkspaceSecurityError


def _updated_content(current: bytes, old_text: str, new_text: str) -> bytes:
    text = current.decode("utf-8", errors="strict")
    count = text.count(old_text)
    if count != 1:
        raise WorkspaceSecurityError("old_text must occur exactly once")
    return text.replace(old_text, new_text, 1).encode("utf-8")


def prepare_edit_binding(
    boundary: WorkspaceBoundary,
    *,
    path: str,
    old_text: str,
    new_text: str,
    max_bytes: int,
) -> dict:
    binding, current = boundary.inspect_mutation(path, max_bytes=max_bytes)
    if current is None:
        raise WorkspaceSecurityError("edit target does not exist")
    updated = _updated_content(current, old_text, new_text)
    if len(updated) > max_bytes:
        raise WorkspaceSecurityError("edited content exceeds the configured write bound")
    return {
        **binding,
        "new_content_digest": hashlib.sha256(updated).hexdigest(),
        "effect_preview": f"edit {path} ({len(updated)} bytes)",
    }


def edit_file(
    boundary: WorkspaceBoundary,
    *,
    path: str,
    old_text: str,
    new_text: str,
    max_bytes: int,
) -> str:
    _, current = boundary.inspect_mutation(path, max_bytes=max_bytes)
    if current is None:
        raise WorkspaceSecurityError("edit target does not exist")
    updated = _updated_content(current, old_text, new_text)
    boundary.atomic_replace(path, updated)
    return f"edited {path} ({len(updated)} bytes)"

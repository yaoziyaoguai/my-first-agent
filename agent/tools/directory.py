"""Approval-bound creation of one workspace directory level."""

from __future__ import annotations

from agent.runtime.contracts import KnownNotExecuted
from agent.tools.path_safety import WorkspaceBoundary


def prepare_directory_binding(boundary: WorkspaceBoundary, *, path: str) -> dict:
    binding = boundary.inspect_directory_creation(path)
    return {
        **binding,
        "effect_preview": f"create directory {path}",
    }


def make_directory(
    boundary: WorkspaceBoundary,
    *,
    path: str,
) -> str | KnownNotExecuted:
    try:
        boundary.create_directory(path)
    except FileExistsError:
        return KnownNotExecuted(
            code="directory_already_exists",
            message=f"Directory already exists; nothing was created: {path}",
        )
    return f"created directory {path}"

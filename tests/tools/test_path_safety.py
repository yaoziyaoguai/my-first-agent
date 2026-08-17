from __future__ import annotations

from pathlib import Path

import pytest

from agent.tools.path_safety import WorkspaceBoundary, WorkspaceSecurityError


def test_workspace_boundary_rejects_absolute_parent_and_sensitive_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    boundary = WorkspaceBoundary(workspace)

    for path in ("../outside", "/absolute", ".env", "keys/private.key", ".git-credentials"):
        with pytest.raises(WorkspaceSecurityError):
            boundary.validate_relative(path)


def test_state_path_must_be_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = workspace / "state.json"
    state.write_text("fixture", encoding="utf-8")

    with pytest.raises(WorkspaceSecurityError, match="outside"):
        WorkspaceBoundary(workspace, protected_paths=(state,))


def test_private_roots_reject_case_variants_for_all_operations(tmp_path: Path) -> None:
    """A15: ASCII private-root names must be compared case-insensitively so that case
    variants cannot resolve to the protected directory on a case-insensitive filesystem.
    read/list/write/edit all enter through validate_relative, so this gate covers them all.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    boundary = WorkspaceBoundary(
        workspace, private_roots=("skills", "memory", "sessions", ".claude")
    )
    for variant in ("Skills", "SKILLS", "MemorY", "SESSIONS", ".CLAUDE", ".Claude"):
        with pytest.raises(WorkspaceSecurityError):
            boundary.validate_relative(f"{variant}/secret.txt")


def test_sensitive_exact_names_reject_case_variants(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    boundary = WorkspaceBoundary(workspace)
    for variant in (".ENV", ".Env", "CREDENTIALS", "Credentials", "ID_RSA"):
        with pytest.raises(WorkspaceSecurityError):
            boundary.validate_relative(variant)


@pytest.mark.parametrize(
    "path",
    (
        "subproject/.claude/settings.json",
        "subproject/.codex/config.json",
        "subproject/.opencode/state.json",
        "subproject/.aws/sso/cache/session.json",
        "subproject/.kube/config",
        "subproject/.docker/config.json",
        "subproject/.gnupg/private-keys-v1.d/key",
        "subproject/.ssh/id_custom",
        "subproject/.config/gh/hosts.yml",
        "subproject/node_modules/package/index.js",
        ".npmrc",
        ".pypirc",
    ),
)
def test_sensitive_components_are_denied_at_every_depth(
    tmp_path: Path,
    path: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    boundary = WorkspaceBoundary(workspace)

    with pytest.raises(WorkspaceSecurityError):
        boundary.validate_relative(path)


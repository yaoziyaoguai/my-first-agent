"""Stable exports for the 019 POSIX storage adapters."""

from agent.automation_hosts._posix_fs import (
    PosixWorkspaceCommitUnknownError,
    PosixWorkspaceStorageError,
    source_root_identity,
)
from agent.automation_hosts.posix_repository import PosixAutomationRepository
from agent.automation_hosts.posix_workspace import (
    PosixOwnedWorkspaceRepository,
)

__all__ = [
    "PosixAutomationRepository",
    "PosixOwnedWorkspaceRepository",
    "PosixWorkspaceCommitUnknownError",
    "PosixWorkspaceStorageError",
    "source_root_identity",
]

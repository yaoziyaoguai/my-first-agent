"""默认持久化、workspace identity 与确定性会话选择。"""

from agent.continuity.identity import WorkspaceIdentityV1
from agent.continuity.restart import RestartProjection, project_restart
from agent.continuity.sessions import (
    SessionArchivePreview,
    StartupDisposition,
    WorkspaceSession,
    archive_workspace_session,
    open_workspace_session,
    preview_workspace_archive,
    preview_workspace_restore,
    restore_workspace_session,
    select_workspace_session,
)

__all__ = [
    "StartupDisposition",
    "RestartProjection",
    "SessionArchivePreview",
    "WorkspaceIdentityV1",
    "WorkspaceSession",
    "archive_workspace_session",
    "open_workspace_session",
    "preview_workspace_archive",
    "preview_workspace_restore",
    "project_restart",
    "restore_workspace_session",
    "select_workspace_session",
]

"""Composition of the four workspace-scoped Kernel file tools."""

from __future__ import annotations

from pathlib import Path

from agent.runtime.contracts import (
    ApprovalPolicy,
    OutputPolicy,
    PolicyDecision,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import DefaultToolPolicy, KernelToolRuntime, RegisteredTool
from agent.tools.edit import edit_file, prepare_edit_binding
from agent.tools.path_safety import WorkspaceBoundary, WorkspaceSecurityError
from agent.tools.write import prepare_write_binding, write_file

DEFAULT_FILE_LIMIT_BYTES = 200_000
DEFAULT_LIST_LIMIT = 500
DEFAULT_PRIVATE_ROOTS = (
    ".ua",
    "graphify-out",
    ".claude",
    ".codex",
    ".opencode",
    "config",
    "session_snapshots",
    "sessions",
    "runs",
    "workspace",
    "memory",
    "skills",
    "node_modules",
    "agent_log.jsonl",
    "state.json",
    "pytest.ini",
    "CLAUDE.md",
)


class _WorkspaceFilePolicy(DefaultToolPolicy):
    identity = "workspace-file-policy-v1"

    def evaluate(self, spec, arguments, binding):
        if binding.get("denied") is True:
            return PolicyDecision.DENY
        return super().evaluate(spec, arguments, binding)


def build_file_tool_registrations(
    workspace_root: Path,
    *,
    protected_paths: tuple[Path, ...] = (),
    private_roots: tuple[str, ...] = DEFAULT_PRIVATE_ROOTS,
    max_file_bytes: int = DEFAULT_FILE_LIMIT_BYTES,
    max_list_entries: int = DEFAULT_LIST_LIMIT,
) -> tuple[RegisteredTool, ...]:
    """返回四个 workspace-scoped 文件工具的 registrations。

    capability factory 只贡献 registrations；composition root 显式拼接成唯一
    `KernelToolRuntime`。每个 registration 绑定自己的 `ToolPolicy`，不按工具名路由。
    """
    if max_file_bytes < 1 or max_list_entries < 1:
        raise ValueError("file tool limits must be positive")
    boundary = WorkspaceBoundary(
        workspace_root,
        protected_paths=protected_paths,
        private_roots=private_roots,
    )

    def safe_binding(operation):
        def prepare(arguments):
            try:
                return operation(arguments)
            except (OSError, UnicodeError, ValueError, WorkspaceSecurityError):
                return {"denied": True, "reason": "workspace_file_policy"}

        return prepare

    file_policy = _WorkspaceFilePolicy()
    return (
        RegisteredTool(
            _read_spec(),
            lambda intent: boundary.read_text(
                intent.arguments["path"], max_bytes=max_file_bytes
            ),
            prepare_binding=safe_binding(
                lambda arguments: _inspect_read(boundary, arguments["path"])
            ),
            policy=file_policy,
        ),
        RegisteredTool(
            _list_spec(),
            lambda intent: "\n".join(
                boundary.list_entries(
                    intent.arguments["path"], max_entries=max_list_entries
                )
            ),
            prepare_binding=safe_binding(
                lambda arguments: _inspect_list(boundary, arguments["path"])
            ),
            policy=file_policy,
        ),
        RegisteredTool(
            _write_spec(),
            lambda intent: write_file(
                boundary,
                path=intent.arguments["path"],
                content=intent.arguments["content"],
            ),
            prepare_binding=safe_binding(
                lambda arguments: prepare_write_binding(
                    boundary,
                    path=arguments["path"],
                    content=arguments["content"],
                    max_bytes=max_file_bytes,
                )
            ),
            policy=file_policy,
        ),
        RegisteredTool(
            _edit_spec(),
            lambda intent: edit_file(
                boundary,
                path=intent.arguments["path"],
                old_text=intent.arguments["old_text"],
                new_text=intent.arguments["new_text"],
                max_bytes=max_file_bytes,
            ),
            prepare_binding=safe_binding(
                lambda arguments: prepare_edit_binding(
                    boundary,
                    path=arguments["path"],
                    old_text=arguments["old_text"],
                    new_text=arguments["new_text"],
                    max_bytes=max_file_bytes,
                )
            ),
            policy=file_policy,
        ),
    )


def build_file_tool_runtime(
    workspace_root: Path,
    *,
    protected_paths: tuple[Path, ...] = (),
    private_roots: tuple[str, ...] = DEFAULT_PRIVATE_ROOTS,
    max_file_bytes: int = DEFAULT_FILE_LIMIT_BYTES,
    max_list_entries: int = DEFAULT_LIST_LIMIT,
) -> KernelToolRuntime:
    """文件工具的独立 `KernelToolRuntime`，主要供测试与无 composition 的调用使用。

    production 路径应通过 `agent.composition` 把 registrations 拼进唯一 runtime。
    """
    return KernelToolRuntime(
        build_file_tool_registrations(
            workspace_root,
            protected_paths=protected_paths,
            private_roots=private_roots,
            max_file_bytes=max_file_bytes,
            max_list_entries=max_list_entries,
        )
    )


def _inspect_read(boundary: WorkspaceBoundary, path: str) -> dict:
    boundary.inspect_readable(path)
    return {"workspace_scoped": True}


def _inspect_list(boundary: WorkspaceBoundary, path: str) -> dict:
    boundary.inspect_directory(path)
    return {"workspace_scoped": True}


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _read_spec() -> ToolSpec:
    return ToolSpec(
        name="read_file",
        version="1",
        description="Read one bounded UTF-8 workspace file.",
        input_schema=_schema({"path": {"type": "string"}}, ["path"]),
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={"workspace_scoped": True, "sensitive_paths_denied": True},
        output_limit_chars=DEFAULT_FILE_LIMIT_BYTES,
    )


def _list_spec() -> ToolSpec:
    return ToolSpec(
        name="list_files",
        version="1",
        description="List bounded non-sensitive entries in one workspace directory.",
        input_schema=_schema({"path": {"type": "string"}}, ["path"]),
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={"workspace_scoped": True, "sensitive_names_redacted": True},
        output_limit_chars=50_000,
    )


def _write_spec() -> ToolSpec:
    return ToolSpec(
        name="write_file",
        version="1",
        description="Atomically create or replace one bounded workspace file.",
        input_schema=_schema(
            {"path": {"type": "string"}, "content": {"type": "string"}},
            ["path", "content"],
        ),
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={"workspace_scoped": True, "atomic_replace": True},
        output_limit_chars=1_000,
    )


def _edit_spec() -> ToolSpec:
    return ToolSpec(
        name="edit_file",
        version="1",
        description="Atomically replace one unique text occurrence in a workspace file.",
        input_schema=_schema(
            {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            ["path", "old_text", "new_text"],
        ),
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={"workspace_scoped": True, "unique_match": True},
        output_limit_chars=1_000,
    )

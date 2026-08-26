"""Composition of the four workspace-scoped Kernel file tools."""

from __future__ import annotations

from pathlib import Path

from agent.runtime.contracts import (
    ApprovalPolicy,
    ExecutionAuthorityClass,
    OutputPolicy,
    PolicyDecision,
    SideEffectClass,
    SourceKind,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import DefaultToolPolicy, KernelToolRuntime, RegisteredTool
from agent.tools.edit import edit_file, prepare_edit_binding
from agent.tools.path_safety import TraversalLimits, WorkspaceBoundary, WorkspaceSecurityError
from agent.tools.search import (
    list_files_output,
    read_file_chunk_output,
    read_file_output,
    search_paths_output,
    search_text_output,
)
from agent.tools.write import prepare_write_binding, write_file

DEFAULT_FILE_LIMIT_BYTES = 200_000
DEFAULT_LIST_LIMIT = 500
DEFAULT_SCAN_LIMIT = 5_000
DEFAULT_SEARCH_MATCH_LIMIT = 16
DEFAULT_SEARCH_BYTES = 2_000_000
DEFAULT_OPENED_FILE_LIMIT = 200
DEFAULT_SEARCH_DEPTH = 12
DEFAULT_SNIPPET_CHARS = 600
DEFAULT_CHUNK_LINES = 200
DEFAULT_SEARCH_DEADLINE_SECONDS = 5.0
DEFAULT_LIST_OUTPUT_CHARS = 50_000
DEFAULT_PRIVATE_ROOTS = (
    "config",
    "session_snapshots",
    "sessions",
    "runs",
    "workspace",
    "memory",
    "skills",
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
    max_scan_entries: int = DEFAULT_SCAN_LIMIT,
    max_search_matches: int = DEFAULT_SEARCH_MATCH_LIMIT,
    max_search_bytes: int = DEFAULT_SEARCH_BYTES,
    max_opened_files: int = DEFAULT_OPENED_FILE_LIMIT,
    max_search_depth: int = DEFAULT_SEARCH_DEPTH,
    max_snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    max_chunk_lines: int = DEFAULT_CHUNK_LINES,
    search_deadline_seconds: float = DEFAULT_SEARCH_DEADLINE_SECONDS,
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
    traversal_limits = TraversalLimits(
        max_scan_entries=max_scan_entries,
        max_opened_files=max_opened_files,
        max_total_bytes=max_search_bytes,
        max_single_file_bytes=max_file_bytes,
        max_depth=max_search_depth,
        max_matches=max_search_matches,
        max_snippet_chars=max_snippet_chars,
        deadline_seconds=search_deadline_seconds,
    )
    return (
        RegisteredTool(
            _read_spec(),
            lambda intent: read_file_output(
                boundary,
                intent,
                max_bytes=max_file_bytes,
            ),
            prepare_binding=safe_binding(
                lambda arguments: _inspect_read(boundary, arguments["path"])
            ),
            policy=file_policy,
        ),
        RegisteredTool(
            _list_spec(),
            lambda intent: list_files_output(
                boundary,
                intent,
                max_entries=max_list_entries,
                max_scan_entries=max_scan_entries,
                max_output_chars=DEFAULT_LIST_OUTPUT_CHARS,
            ),
            prepare_binding=safe_binding(
                lambda arguments: _inspect_list(boundary, arguments["path"])
            ),
            policy=file_policy,
        ),
        RegisteredTool(
            _search_paths_spec(),
            lambda intent: search_paths_output(
                boundary,
                intent,
                limits=traversal_limits,
            ),
            prepare_binding=safe_binding(
                lambda arguments: _inspect_search(
                    boundary,
                    arguments,
                    limits=traversal_limits,
                )
            ),
            policy=file_policy,
        ),
        RegisteredTool(
            _search_text_spec(),
            lambda intent: search_text_output(
                boundary,
                intent,
                limits=traversal_limits,
            ),
            prepare_binding=safe_binding(
                lambda arguments: _inspect_search(
                    boundary,
                    arguments,
                    limits=traversal_limits,
                )
            ),
            policy=file_policy,
        ),
        RegisteredTool(
            _read_chunk_spec(),
            lambda intent: read_file_chunk_output(
                boundary,
                intent,
                max_bytes=max_file_bytes,
                max_line_cap=max_chunk_lines,
            ),
            prepare_binding=safe_binding(
                lambda arguments: _inspect_chunk(
                    boundary,
                    arguments,
                    max_line_cap=max_chunk_lines,
                )
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
                lambda arguments: _prepare_edit_binding(
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
    max_scan_entries: int = DEFAULT_SCAN_LIMIT,
    max_search_matches: int = DEFAULT_SEARCH_MATCH_LIMIT,
    max_search_bytes: int = DEFAULT_SEARCH_BYTES,
    max_opened_files: int = DEFAULT_OPENED_FILE_LIMIT,
    max_search_depth: int = DEFAULT_SEARCH_DEPTH,
    max_snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    max_chunk_lines: int = DEFAULT_CHUNK_LINES,
    search_deadline_seconds: float = DEFAULT_SEARCH_DEADLINE_SECONDS,
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
            max_scan_entries=max_scan_entries,
            max_search_matches=max_search_matches,
            max_search_bytes=max_search_bytes,
            max_opened_files=max_opened_files,
            max_search_depth=max_search_depth,
            max_snippet_chars=max_snippet_chars,
            max_chunk_lines=max_chunk_lines,
            search_deadline_seconds=search_deadline_seconds,
        )
    )


def _inspect_read(boundary: WorkspaceBoundary, path: str) -> dict:
    boundary.inspect_readable(path)
    return {"workspace_scoped": True}


def _inspect_list(boundary: WorkspaceBoundary, path: str) -> dict:
    boundary.inspect_directory(path)
    return {"workspace_scoped": True}


def _inspect_search(
    boundary: WorkspaceBoundary,
    arguments: dict,
    *,
    limits: TraversalLimits,
) -> dict:
    query = arguments["query"]
    root = arguments.get("root", ".")
    max_results = arguments.get("max_results", limits.max_matches)
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > 256
        or any(not character.isprintable() for character in query)
    ):
        raise ValueError("workspace search query is invalid")
    if (
        not isinstance(max_results, int)
        or isinstance(max_results, bool)
        or not 1 <= max_results <= limits.max_matches
    ):
        raise ValueError("workspace search result limit is invalid")
    boundary.inspect_directory(root)
    return {"workspace_scoped": True}


def _inspect_chunk(
    boundary: WorkspaceBoundary,
    arguments: dict,
    *,
    max_line_cap: int,
) -> dict:
    start_line = arguments["start_line"]
    max_lines = arguments["max_lines"]
    if (
        not isinstance(start_line, int)
        or isinstance(start_line, bool)
        or start_line < 1
        or not isinstance(max_lines, int)
        or isinstance(max_lines, bool)
        or not 1 <= max_lines <= max_line_cap
    ):
        raise ValueError("workspace line window is invalid")
    boundary.inspect_readable(arguments["path"])
    return {"workspace_scoped": True}


def _prepare_edit_binding(
    boundary: WorkspaceBoundary,
    *,
    path: str,
    old_text: str,
    new_text: str,
    max_bytes: int,
) -> dict:
    # Citation sidecar 的 provenance criterion 绑定完整 canonical manifest；局部编辑
    # 无法在 reducer 内安全重建最终内容，因此必须用 write_file 完整替换。
    if path.endswith(".citations.json"):
        raise WorkspaceSecurityError("citation sidecar requires a full rewrite")
    return prepare_edit_binding(
        boundary,
        path=path,
        old_text=old_text,
        new_text=new_text,
        max_bytes=max_bytes,
    )


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _read_spec() -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_file",
        version="1",
        description="Read one bounded UTF-8 workspace file.",
        input_schema=_schema({"path": {"type": "string"}}, ["path"]),
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={
            "workspace_scoped": True,
            "sensitive_paths_denied": True,
            "source_metadata_keys": [
                "path",
                "encoding",
                "snapshot_digest",
                "truncated",
            ],
        },
        output_limit_chars=DEFAULT_FILE_LIMIT_BYTES,
        source_kinds=(SourceKind.WORKSPACE_EXCERPT,),
    )


def _list_spec() -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="list_files",
        version="1",
        description="List bounded non-sensitive entries in one workspace directory.",
        input_schema=_schema({"path": {"type": "string"}}, ["path"]),
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={
            "workspace_scoped": True,
            "sensitive_names_redacted": True,
            "source_metadata_keys": [
                "path",
                "snapshot_digest",
                "truncated",
                "truncation_reason",
            ],
        },
        output_limit_chars=DEFAULT_LIST_OUTPUT_CHARS,
        source_kinds=(SourceKind.WORKSPACE_PATH,),
    )


def _search_paths_spec() -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="search_paths",
        version="1",
        description="Search bounded non-sensitive workspace-relative paths.",
        input_schema=_schema(
            {
                "query": {"type": "string"},
                "root": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            ["query"],
        ),
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={
            "workspace_scoped": True,
            "sensitive_paths_denied": True,
            "source_metadata_keys": _search_metadata_keys(),
        },
        output_limit_chars=50_000,
        source_kinds=(SourceKind.WORKSPACE_PATH,),
    )


def _search_text_spec() -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="search_text",
        version="1",
        description="Search bounded text excerpts in non-sensitive workspace files.",
        input_schema=_schema(
            {
                "query": {"type": "string"},
                "root": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            ["query"],
        ),
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={
            "workspace_scoped": True,
            "sensitive_paths_denied": True,
            "binary_skipped": True,
            "source_metadata_keys": _search_metadata_keys(),
        },
        output_limit_chars=50_000,
        source_kinds=(SourceKind.WORKSPACE_EXCERPT,),
    )


def _read_chunk_spec() -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_file_chunk",
        version="1",
        description="Read one bounded line window from a UTF-8 workspace file.",
        input_schema=_schema(
            {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "max_lines": {"type": "integer"},
            },
            ["path", "start_line", "max_lines"],
        ),
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={
            "workspace_scoped": True,
            "sensitive_paths_denied": True,
            "source_metadata_keys": [
                "path",
                "snapshot_digest",
                "truncated",
                "truncation_reason",
            ],
        },
        output_limit_chars=DEFAULT_FILE_LIMIT_BYTES,
        source_kinds=(SourceKind.WORKSPACE_EXCERPT,),
    )


def _search_metadata_keys() -> list[str]:
    return [
        "status",
        "snapshot_digest",
        "truncated",
        "truncation_reason",
        "scanned_entries",
        "opened_files",
        "total_bytes",
    ]


def _write_spec() -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_file",
        version="1",
        description="Atomically create or replace one bounded workspace file.",
        input_schema=_schema(
            {
                "path": {"type": "string"},
                "content": {
                    "type": "string",
                    "description": (
                        "Exact file content. For a .citations.json path, copy the raw "
                        "build_citation_manifest ToolResult text: no code fence, outer "
                        "quotes, prefix, or suffix. A single transport-added final newline "
                        "is accepted and removed before approval."
                    ),
                },
            },
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
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="edit_file",
        version="1",
        description=(
            "Atomically replace one unique text occurrence in a workspace file. "
            "Citation sidecars ending in .citations.json require a complete write_file "
            "replacement."
        ),
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

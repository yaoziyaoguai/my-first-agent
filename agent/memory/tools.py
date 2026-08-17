"""Memory governed tools：read 路径无需审批，write 路径 ALWAYS_APPROVAL。

所有 mutation 经唯一 ToolRuntime 的 prepare/approval/EXECUTING/invoke/result 路径；
effect 前的 CAS/lock 失败返回 ``KnownNotExecuted``，effect 可能发生后的异常传播到
unknown-outcome recovery。preview 展示完整 bounded content/diff，不让用户只看 digest 盲批。
"""

from __future__ import annotations

from agent.memory.contracts import MemoryBusyError, MemoryCasMismatchError
from agent.memory.source import MemoryContextSource
from agent.memory.store import _MAX_CONTENT_CHARS, MemoryStore
from agent.runtime.contracts import (
    ApprovalPolicy,
    ContextQuery,
    ContextSourceLimits,
    ExecutionAuthorityClass,
    JSONValue,
    KnownNotExecuted,
    OutputPolicy,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import RegisteredTool

MEMORY_POLICY_VERSION = "memory-tool-v1"
_PREVIEW_CONTENT_CAP = _MAX_CONTENT_CHARS


def build_memory_tool_registrations(
    store: MemoryStore,
    *,
    workspace_scope_digest: str,
) -> tuple[RegisteredTool, ...]:
    source = MemoryContextSource(store)
    return (
        RegisteredTool(
            _search_spec(workspace_scope_digest),
            _make_search(source, store, workspace_scope_digest),
        ),
        RegisteredTool(_get_spec(workspace_scope_digest), _make_get(store, workspace_scope_digest)),
        RegisteredTool(
            _remember_spec(workspace_scope_digest),
            _make_remember(store, workspace_scope_digest),
            prepare_binding=_make_remember_binding(store, workspace_scope_digest),
        ),
        RegisteredTool(
            _update_spec(workspace_scope_digest),
            _make_update(store, workspace_scope_digest),
            prepare_binding=_make_update_binding(store, workspace_scope_digest),
        ),
        RegisteredTool(
            _forget_spec(workspace_scope_digest),
            _make_forget(store, workspace_scope_digest),
            prepare_binding=_make_forget_binding(store, workspace_scope_digest),
        ),
    )


def _common_safety(workspace_scope_digest: str, kind: str) -> dict[str, JSONValue]:
    return {
        "kind": kind,
        "workspace_scope_digest": workspace_scope_digest,
        "policy_version": MEMORY_POLICY_VERSION,
    }


def _read_schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _search_spec(scope: str) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="memory_search",
        version="1",
        description="Search approved workspace memory by lexical relevance.",
        input_schema=_read_schema(
            {"query": {"type": "string"}, "limit": {"type": "integer"}},
            ["query"],
        ),
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy=_common_safety(scope, "memory_search"),
        output_limit_chars=2_000,
    )


def _get_spec(scope: str) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="memory_get",
        version="1",
        description="Read one approved workspace memory record by ID.",
        input_schema=_read_schema({"record_id": {"type": "string"}}, ["record_id"]),
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy=_common_safety(scope, "memory_get"),
        output_limit_chars=2_000,
    )


def _remember_spec(scope: str) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="memory_remember",
        version="1",
        description="Persist one approved workspace memory record.",
        input_schema=_read_schema({"content": {"type": "string"}}, ["content"]),
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy=_common_safety(scope, "memory_remember"),
        output_limit_chars=1_000,
    )


def _update_spec(scope: str) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="memory_update",
        version="1",
        description="Update one approved workspace memory record under exact precondition.",
        input_schema=_read_schema(
            {
                "record_id": {"type": "string"},
                "content": {"type": "string"},
                "expected_record_revision": {"type": "integer"},
                "expected_content_digest": {"type": "string"},
            },
            ["record_id", "content", "expected_record_revision", "expected_content_digest"],
        ),
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy=_common_safety(scope, "memory_update"),
        output_limit_chars=1_000,
    )


def _forget_spec(scope: str) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="memory_forget",
        version="1",
        description="Forget one approved workspace memory record under exact precondition.",
        input_schema=_read_schema(
            {
                "record_id": {"type": "string"},
                "expected_record_revision": {"type": "integer"},
                "expected_content_digest": {"type": "string"},
            },
            ["record_id", "expected_record_revision", "expected_content_digest"],
        ),
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy=_common_safety(scope, "memory_forget"),
        output_limit_chars=1_000,
    )


def _make_search(source, store, scope):
    def search(intent):
        query_text = str(intent.arguments.get("query", ""))
        limit = intent.arguments.get("limit", 8)
        if not isinstance(limit, int) or limit < 1:
            limit = 8
        snapshot = source.snapshot(
            ContextQuery(
                conversation_id="",
                run_id="",
                user_text=query_text,
                workspace_scope_digest=scope,
                source_limits=ContextSourceLimits(max_tokens=10_000, max_items=limit),
            )
        )
        lines = []
        for candidate in snapshot.candidates[:limit]:
            lines.append(f"{candidate.candidate_id}: {_bound(candidate.content)}")
        return "\n".join(lines) if lines else "no matching memory"

    return search


def _make_get(store, scope):
    def get(intent):
        record = store.get(str(intent.arguments.get("record_id", "")))
        if record is None or record.workspace_scope_digest != scope:
            return KnownNotExecuted(code="memory_not_found", message="record is not available")
        return _bound(record.content)

    return get


def _make_remember(store, scope):
    def remember(intent):
        content = str(intent.arguments.get("content", ""))
        if len(content) > _MAX_CONTENT_CHARS:
            return KnownNotExecuted(code="memory_too_large", message="content exceeds the limit")
        try:
            record = store.remember(
                content,
                fact_admission=intent.fact_admission,
            )
        except MemoryBusyError:
            return KnownNotExecuted(code="memory_busy", message="memory store is busy; retry later")
        except MemoryCasMismatchError:
            return KnownNotExecuted(
                code="memory_cas_mismatch", message="precondition changed; retry"
            )
        return f"remembered {record.record_id} ({record.content_digest[:8]})"

    return remember


def _make_update(store, scope):
    def update(intent):
        try:
            record = store.update(
                str(intent.arguments.get("record_id", "")),
                str(intent.arguments.get("content", "")),
                expected_record_revision=int(intent.arguments.get("expected_record_revision", -1)),
                expected_content_digest=str(intent.arguments.get("expected_content_digest", "")),
            )
        except MemoryBusyError:
            return KnownNotExecuted(code="memory_busy", message="memory store is busy; retry later")
        except MemoryCasMismatchError:
            return KnownNotExecuted(
                code="memory_cas_mismatch", message="precondition changed; retry"
            )
        return f"updated {record.record_id} ({record.content_digest[:8]})"

    return update


def _make_forget(store, scope):
    def forget(intent):
        try:
            store.forget(
                str(intent.arguments.get("record_id", "")),
                expected_record_revision=int(intent.arguments.get("expected_record_revision", -1)),
                expected_content_digest=str(intent.arguments.get("expected_content_digest", "")),
            )
        except MemoryBusyError:
            return KnownNotExecuted(code="memory_busy", message="memory store is busy; retry later")
        except MemoryCasMismatchError:
            return KnownNotExecuted(
                code="memory_cas_mismatch", message="precondition changed; retry"
            )
        return "forgotten"

    return forget


def _make_remember_binding(store, scope):
    def prepare(arguments):
        content = str(arguments.get("content", ""))
        from agent.memory.store import _content_digest

        # 刷新到 durable revision：approval binding 绑定真实 store revision，
        # 使 store 在 approval 后变更时旧 binding 失效（target_digest=scope 不足以证明）。
        store.snapshot()
        return {
            "effect_preview": f"remember in workspace memory: {_bound(content)}",
            "target_digest": scope,
            "store_revision": store.revision,
            "new_content_digest": _content_digest(content),
        }

    return prepare


def _existing_state(store, scope, record_id):
    """从 durable 刷新后的 store 读取现有 record 的 before 状态（cross-scope 不泄露）。"""
    store.snapshot()
    existing = store.get(record_id)
    if existing is None or existing.workspace_scope_digest != scope:
        return "", "", -1
    return existing.content, existing.content_digest, existing.revision


def _make_update_binding(store, scope):
    def prepare(arguments):
        from agent.memory.store import _content_digest

        record_id = str(arguments.get("record_id", ""))
        content = str(arguments.get("content", ""))
        before, old_digest, existing_revision = _existing_state(store, scope, record_id)
        preview = (
            f"update memory record {record_id}:\n"
            f"- before: {_bound(before)}\n"
            f"+ after: {_bound(content)}"
        )
        return {
            "effect_preview": preview,
            "target_digest": scope,
            "store_revision": store.revision,
            "record_id": record_id,
            "existing_record_revision": existing_revision,
            "old_content_digest": old_digest,
            "new_content_digest": _content_digest(content),
        }

    return prepare


def _make_forget_binding(store, scope):
    def prepare(arguments):
        record_id = str(arguments.get("record_id", ""))
        before, old_digest, existing_revision = _existing_state(store, scope, record_id)
        return {
            "effect_preview": f"forget memory record {record_id}: {_bound(before)}",
            "target_digest": scope,
            "store_revision": store.revision,
            "record_id": record_id,
            "existing_record_revision": existing_revision,
            "old_content_digest": old_digest,
        }

    return prepare


def _bound(text: str) -> str:
    return text[:_PREVIEW_CONTENT_CAP]

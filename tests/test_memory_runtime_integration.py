"""Memory Kernel v1 — runtime integration tests.

这些测试不依赖真实 LLM、不读取 .env、不写文件/DB、不使用裸 input()。
所有确认流程通过两阶段交互（evaluate → resolve_confirmation）测试。

测试覆盖：
- explicit retain → store 写入
- snapshot → prompt 注入
- 敏感内容拦截
- 普通消息不触发 memory
- audit event 记录
- reject 不写入 store
- MemoryRuntime 不 import checkpoint
- contract 未来扩展字段预留
- MemoryRuntime 不包含 input() 调用
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
)
from agent.memory_contracts import (
    MemoryScope,
    MemorySnapshot,
)
from agent.memory_runtime import (
    MemoryEvaluationAction,
    MemoryRuntime,
)
from agent.memory_store import InMemoryMemoryStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_runtime(*, accept: bool = True) -> MemoryRuntime:
    """构造测试用 MemoryRuntime：in-memory store。"""
    return MemoryRuntime(store=InMemoryMemoryStore())


def _evaluate_and_confirm(
    runtime: MemoryRuntime,
    user_text: str,
    *,
    choice: MemoryConfirmationChoice = MemoryConfirmationChoice.ACCEPT,
    on_event=None,
):
    """两阶段交互：evaluate → resolve_confirmation。

    v1 开始 evaluate_user_text 不再内部调用 adapter，而是返回
    CONFIRMATION_REQUIRED。测试中通过本 helper 模拟两阶段流程。
    """
    result = runtime.evaluate_user_text(user_text, on_event=on_event)
    if result.action is not MemoryEvaluationAction.CONFIRMATION_REQUIRED:
        return result
    return runtime.resolve_confirmation(result.candidate_id, choice)


# ---------------------------------------------------------------------------
# 1. explicit retain → store
# ---------------------------------------------------------------------------


def test_explicit_retain_flows_to_dispatcher_payload():
    """resolve_confirmation direct_write=True 默认：返回 _dispatcher_payload 并直接写 store。"""
    runtime = _make_runtime()

    result = _evaluate_and_confirm(runtime, "remember that my favorite color is blue")

    assert result.action is MemoryEvaluationAction.STORED
    payload = result._dispatcher_payload
    assert payload is not None, "APPROVED 应返回 _dispatcher_payload"
    assert payload["confirmation_result"] == "accept"
    assert "my favorite color is blue" in payload["candidate"]["content"]
    assert "content_hash" in payload["candidate"]
    # direct_write=True 默认行为：store 已被直接写入
    records = runtime._store.list_records()  # type: ignore[union-attr]
    assert len(records) == 1, "direct_write=True 应直接写 store"


def test_chinese_retain_returns_dispatcher_payload():
    """Loop 15: 中文 retain 返回 _dispatcher_payload，不再直接写 store。"""
    runtime = _make_runtime()

    result = _evaluate_and_confirm(runtime, "记住：我喜欢简洁回答")

    assert result.action is MemoryEvaluationAction.STORED
    payload = result._dispatcher_payload
    assert payload is not None, "中文 retain 应返回 _dispatcher_payload"
    assert "我喜欢简洁回答" in payload["candidate"]["content"]


# ---------------------------------------------------------------------------
# 2. snapshot → prompt
# ---------------------------------------------------------------------------


def test_memory_snapshot_enters_prompt():
    """store 中有 record → snapshot 非空 → prompt section 包含 memory。"""
    from agent.memory import build_memory_section
    from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
    from agent.memory_contracts import MemoryDecisionType
    from agent.memory_operations import (
        MemoryOperationIntent,
        MemoryOperationType,
        build_memory_audit_summary,
    )

    runtime = _make_runtime()
    # 直接写 store 作为 snapshot 测试的前置条件（resolve_confirmation 不再直接写 store）
    intent = MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=MemoryConfirmationStatus.APPROVED,
        user_choice=MemoryConfirmationChoice.ACCEPT,
        content_summary="I prefer concise answers",
        source_summary="test",
        scope=MemoryScope.USER,
        safety_summary="无额外安全标记",
        sensitive_redacted=False,
        user_visible_summary="I prefer concise answers",
    )
    audit = build_memory_audit_summary(intent)
    runtime._store.apply_operation_intent(intent, audit)

    snapshot = runtime.snapshot_for_prompt()
    assert len(snapshot.items) == 1

    prompt_section = build_memory_section(snapshot)
    assert "I prefer concise answers" in prompt_section


def test_empty_store_produces_empty_snapshot():
    """store 为空 → snapshot 为空 → prompt section 为默认占位。"""
    from agent.memory import build_memory_section

    runtime = _make_runtime()
    snapshot = runtime.snapshot_for_prompt()

    assert isinstance(snapshot, MemorySnapshot)
    assert len(snapshot.items) == 0

    prompt_section = build_memory_section(snapshot)
    assert "当前未注入长期记忆" in prompt_section


# ---------------------------------------------------------------------------
# 3. 敏感内容拦截
# ---------------------------------------------------------------------------


def test_sensitive_memory_blocked():
    """用户说 "remember that my api key is sk-test-secret" → policy BLOCKED → store 无 record。"""
    runtime = _make_runtime()

    result = runtime.evaluate_user_text("remember that my api key is sk-test-secret")

    assert result.action is MemoryEvaluationAction.BLOCKED
    records = runtime._store.list_records()  # type: ignore[union-attr]
    assert len(records) == 0


def test_sensitive_memory_not_in_prompt():
    """敏感内容被拦截后，snapshot 中不出现。"""
    from agent.memory import build_memory_section

    runtime = _make_runtime()
    runtime.evaluate_user_text("remember that my password is hunter2")

    snapshot = runtime.snapshot_for_prompt()
    prompt_section = build_memory_section(snapshot)
    assert "hunter2" not in prompt_section


# ---------------------------------------------------------------------------
# 4. 普通消息不触发 memory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "帮我看看 README 里写了什么",
    "今天天气怎么样",
    "用 pytest 跑一下测试",
])
def test_normal_message_no_memory_trigger(text: str):
    """普通消息不触发 memory 流程 → action=no_op → store 为空。"""
    runtime = _make_runtime()

    result = runtime.evaluate_user_text(text)

    assert result.action is MemoryEvaluationAction.NO_OP
    records = runtime._store.list_records()  # type: ignore[union-attr]
    assert len(records) == 0


# ---------------------------------------------------------------------------
# 5. audit events
# ---------------------------------------------------------------------------


def test_memory_audit_events_logged():
    """Loop 15: candidate / confirmation / approved 事件被记录（stored 移至 handler）。"""
    events: list = []

    def capture_log(event_type: str, payload: dict | None = None):
        events.append((event_type, payload or {}))

    runtime = MemoryRuntime(
        store=InMemoryMemoryStore(),
        event_logger=capture_log,
    )
    _evaluate_and_confirm(runtime, "remember that I prefer concise answers")

    event_types = [e[0] for e in events]
    assert "memory.candidate_detected" in event_types
    assert "memory.confirmation_requested" in event_types
    assert "memory.confirmation_accepted" in event_types
    # stored 事件不再由 resolve_confirmation 发出——已迁移至 MemoryRetainHandler
    assert "memory.confirmation_approved" in event_types


def test_blocked_memory_logs_blocked_event():
    """敏感内容拦截 → 记录 memory.blocked 事件。"""
    events: list = []

    def capture_log(event_type: str, payload: dict | None = None):
        events.append((event_type, payload or {}))

    runtime = MemoryRuntime(
        store=InMemoryMemoryStore(),
        event_logger=capture_log,
    )
    runtime.evaluate_user_text("remember that my api key is sk-secret")

    event_types = [e[0] for e in events]
    assert "memory.blocked" in event_types


def test_snapshot_generation_logs_injected_event():
    """snapshot 生成时记录 memory.injected 事件。"""
    from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
    from agent.memory_contracts import MemoryDecisionType
    from agent.memory_operations import (
        MemoryOperationIntent,
        MemoryOperationType,
        build_memory_audit_summary,
    )

    events: list = []

    def capture_log(event_type: str, payload: dict | None = None):
        events.append((event_type, payload or {}))

    runtime = MemoryRuntime(
        store=InMemoryMemoryStore(),
        event_logger=capture_log,
    )
    # 直接写 store 作为前置条件（resolve_confirmation 不再直接写 store）
    intent = MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=MemoryConfirmationStatus.APPROVED,
        user_choice=MemoryConfirmationChoice.ACCEPT,
        content_summary="I prefer concise answers",
        source_summary="test",
        scope=MemoryScope.USER,
        safety_summary="无额外安全标记",
        sensitive_redacted=False,
        user_visible_summary="I prefer concise answers",
    )
    audit = build_memory_audit_summary(intent)
    runtime._store.apply_operation_intent(intent, audit)

    events.clear()
    runtime.snapshot_for_prompt()

    event_types = [e[0] for e in events]
    assert "memory.injected" in event_types


# ---------------------------------------------------------------------------
# 6. reject 不写入 store
# ---------------------------------------------------------------------------


def test_rejected_memory_not_stored():
    """用户拒绝确认 → store 无 record。"""
    runtime = _make_runtime()

    result = _evaluate_and_confirm(
        runtime,
        "remember that I prefer concise answers",
        choice=MemoryConfirmationChoice.REJECT,
    )

    assert result.action is MemoryEvaluationAction.REJECTED
    records = runtime._store.list_records()  # type: ignore[union-attr]
    assert len(records) == 0


# ---------------------------------------------------------------------------
# 7. MemoryRuntime 不 import checkpoint
# ---------------------------------------------------------------------------


def test_memory_runtime_does_not_touch_checkpoint():
    """MemoryRuntime 模块不 import checkpoint、不 import core。"""
    runtime_path = PROJECT_ROOT / "agent" / "memory_runtime.py"
    tree = ast.parse(runtime_path.read_text(encoding="utf-8"))

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    forbidden = {"agent.core", "agent.checkpoint"}
    assert imports.isdisjoint(forbidden), f"Forbidden imports found: {imports & forbidden}"


def test_memory_runtime_does_not_import_mcp_provider_tool():
    """MemoryRuntime 不 import MCP/provider/tool_executor。"""
    runtime_path = PROJECT_ROOT / "agent" / "memory_runtime.py"
    tree = ast.parse(runtime_path.read_text(encoding="utf-8"))

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    forbidden = {
        "agent.mcp",
        "agent.mcp_stdio",
        "agent.tool_executor",
        "agent.provider",
    }
    assert imports.isdisjoint(forbidden), f"Forbidden imports found: {imports & forbidden}"


# ---------------------------------------------------------------------------
# 8. future type extension points
# ---------------------------------------------------------------------------


def test_memory_candidate_has_metadata_field():
    """MemoryCandidate 有 metadata 扩展字段（默认空 dict）。"""
    from agent.memory_contracts import (
        MemoryCandidate,
        MemoryScope,
        MemorySensitivity,
        MemorySource,
    )

    candidate = MemoryCandidate(
        id="test-1",
        content="test content",
        source=MemorySource.USER_INPUT,
        source_event=None,
        proposed_type="explicit_retain",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.LOW,
        stability="user_asserted",
        confidence=0.9,
        reason="test",
    )
    assert hasattr(candidate, "metadata")
    assert candidate.metadata == {}


def test_memory_record_has_future_type_fields():
    """MemoryRecord 有 memory_type / source_type / approval_status / metadata 字段。"""
    from agent.memory_store import MemoryRecord

    field_names = set(MemoryRecord.__dataclass_fields__)
    assert "memory_type" in field_names
    assert "source_type" in field_names
    assert "approval_status" in field_names
    assert "metadata" in field_names


def test_memory_record_defaults_are_kernel_v1_values():
    """MemoryRecord 默认值匹配 Kernel v1 语义。"""
    from agent.memory_operations import MemoryOperationType
    from agent.memory_store import MemoryRecord

    record = MemoryRecord(
        id="test-1",
        content="test",
        scope=MemoryScope.USER,
        source_summary="candidate:test",
        safety_summary="no flags",
        audit_id="audit:test",
        created_by_operation=MemoryOperationType.RETAIN,
        updated_by_operation=MemoryOperationType.RETAIN,
    )
    assert record.memory_type == "semantic"
    assert record.source_type == "explicit_user_request"
    assert record.approval_status == "approved"
    assert record.metadata == {}


def test_memory_evaluation_result_has_decision_type_field():
    """MemoryEvaluationResult 携带 decision_type 供调用方判断。"""
    from agent.memory_contracts import MemoryDecisionType

    # NO_OP 时 decision_type 为 None
    runtime = _make_runtime()
    result = runtime.evaluate_user_text("hello")
    assert result.action is MemoryEvaluationAction.NO_OP
    assert result.decision_type is None

    # STORED 时 decision_type 为 RETAIN（两阶段）
    result2 = _evaluate_and_confirm(runtime, "remember that X")
    assert result2.action is MemoryEvaluationAction.STORED
    assert result2.decision_type is MemoryDecisionType.RETAIN


# ---------------------------------------------------------------------------
# 9. MemoryRuntime 不包含 input() 调用
# ---------------------------------------------------------------------------


def test_memory_runtime_does_not_use_input():
    """MemoryRuntime 模块不调用 input() —— 确认走 adapter，不阻塞 stdin。"""
    runtime_path = PROJECT_ROOT / "agent" / "memory_runtime.py"
    tree = ast.parse(runtime_path.read_text(encoding="utf-8"))

    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)

    assert "input" not in calls, "memory_runtime.py must not call input()"


# ---------------------------------------------------------------------------
# 10. 两阶段确认闭环
# ---------------------------------------------------------------------------


def test_two_phase_confirm_flow_returns_dispatcher_payload():
    """v1 两阶段交互 direct_write=True 默认：返回 _dispatcher_payload 并直接写 store。"""
    from agent.memory_runtime import MemoryEvaluationAction
    from agent.memory_store import InMemoryMemoryStore

    events: list = []

    def capture(event_type: str, payload: dict | None = None):
        events.append((event_type, payload or {}))

    runtime = MemoryRuntime(
        store=InMemoryMemoryStore(),
        event_logger=capture,
    )

    result = _evaluate_and_confirm(runtime, "remember that I prefer concise answers")
    assert result.action is MemoryEvaluationAction.STORED

    # _dispatcher_payload 包含 store 写入所需全部数据
    payload = result._dispatcher_payload
    assert payload is not None, "两阶段确认应返回 _dispatcher_payload"
    assert payload["confirmation_result"] == "accept"
    assert "I prefer concise answers" in payload["candidate"]["content"]
    assert "content_hash" in payload["candidate"]

    # direct_write=True 默认行为：store 已被直接写入
    records = runtime._store.list_records()
    assert len(records) == 1, "direct_write=True 应直接写 store"

    # audit events 包含 confirmation_accepted 和 confirmation_approved
    event_types = [e[0] for e in events]
    assert "memory.confirmation_accepted" in event_types
    assert "memory.confirmation_approved" in event_types


def test_evaluate_user_text_emits_on_event():
    """evaluate_user_text 在提供 on_event 时 emit confirmation_requested 事件。"""
    from agent.memory_store import InMemoryMemoryStore

    on_event_calls: list = []

    runtime = MemoryRuntime(store=InMemoryMemoryStore())

    runtime.evaluate_user_text(
        "remember that I prefer concise answers",
        on_event=on_event_calls.append,
    )

    # on_event 被调用
    assert len(on_event_calls) >= 1
    emitted = on_event_calls[0]
    assert emitted["type"] == "memory_confirmation_requested"
    assert "question" in emitted
    assert "preview" in emitted


def test_create_memory_runtime_default_behavior():
    """Loop 15: create_memory_runtime() 两阶段交互返回 _dispatcher_payload。"""
    from agent.memory_runtime import MemoryEvaluationAction, create_memory_runtime
    from agent.memory_store import InMemoryMemoryStore

    runtime = create_memory_runtime(store=InMemoryMemoryStore())

    result = _evaluate_and_confirm(runtime, "remember that I prefer concise answers")
    assert result.action is MemoryEvaluationAction.STORED

    payload = result._dispatcher_payload
    assert payload is not None, "create_memory_runtime 路径应返回 _dispatcher_payload"
    assert "I prefer concise answers" in payload["candidate"]["content"]

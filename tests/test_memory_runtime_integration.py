"""Memory Kernel v1 — runtime integration tests.

这些测试不依赖真实 LLM、不读取 .env、不写文件/DB、不使用裸 input()。
所有确认流程通过 FakeMemoryConfirmationAdapter 模拟。

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
    FakeMemoryConfirmationAdapter,
    MemoryEvaluationAction,
    MemoryRuntime,
)
from agent.memory_store import InMemoryMemoryStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_runtime(*, accept: bool = True) -> MemoryRuntime:
    """构造测试用 MemoryRuntime：fake adapter + in-memory store。"""
    choice = MemoryConfirmationChoice.ACCEPT if accept else MemoryConfirmationChoice.REJECT
    return MemoryRuntime(
        store=InMemoryMemoryStore(),
        confirmation_adapter=FakeMemoryConfirmationAdapter(preset_choice=choice),
    )


# ---------------------------------------------------------------------------
# 1. explicit retain → store
# ---------------------------------------------------------------------------


def test_explicit_retain_flows_to_store():
    """用户说 "remember that X" → store 中有 approved record。"""
    runtime = _make_runtime(accept=True)

    result = runtime.evaluate_user_text("remember that my favorite color is blue")

    assert result.action is MemoryEvaluationAction.STORED
    records = runtime._store.list_records()  # type: ignore[union-attr]
    assert len(records) == 1
    record = records[0]
    assert "my favorite color is blue" in record.content
    assert record.approval_status == "approved"
    assert record.memory_type == "semantic"
    assert record.source_type == "explicit_user_request"


def test_chinese_retain_flows_to_store():
    """中文 "记住 X" 同样触发 retain → store。"""
    runtime = _make_runtime(accept=True)

    result = runtime.evaluate_user_text("记住：我喜欢简洁回答")

    assert result.action is MemoryEvaluationAction.STORED
    records = runtime._store.list_records()  # type: ignore[union-attr]
    assert len(records) == 1
    assert "我喜欢简洁回答" in records[0].content


# ---------------------------------------------------------------------------
# 2. snapshot → prompt
# ---------------------------------------------------------------------------


def test_memory_snapshot_enters_prompt():
    """store 中有 accepted record → snapshot 非空 → prompt section 包含 memory。"""
    from agent.memory import build_memory_section

    runtime = _make_runtime(accept=True)
    runtime.evaluate_user_text("remember that I prefer concise answers")

    snapshot = runtime.snapshot_for_prompt()
    assert isinstance(snapshot, MemorySnapshot)
    assert len(snapshot.items) == 1

    prompt_section = build_memory_section(snapshot)
    assert "I prefer concise answers" in prompt_section


def test_empty_store_produces_empty_snapshot():
    """store 为空 → snapshot 为空 → prompt section 为默认占位。"""
    from agent.memory import build_memory_section

    runtime = _make_runtime(accept=True)
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
    runtime = _make_runtime(accept=True)

    result = runtime.evaluate_user_text("remember that my api key is sk-test-secret")

    assert result.action is MemoryEvaluationAction.BLOCKED
    records = runtime._store.list_records()  # type: ignore[union-attr]
    assert len(records) == 0


def test_sensitive_memory_not_in_prompt():
    """敏感内容被拦截后，snapshot 中不出现。"""
    from agent.memory import build_memory_section

    runtime = _make_runtime(accept=True)
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
    runtime = _make_runtime(accept=True)

    result = runtime.evaluate_user_text(text)

    assert result.action is MemoryEvaluationAction.NO_OP
    records = runtime._store.list_records()  # type: ignore[union-attr]
    assert len(records) == 0


# ---------------------------------------------------------------------------
# 5. audit events
# ---------------------------------------------------------------------------


def test_memory_audit_events_logged():
    """candidate / confirmation / stored 事件被记录。"""
    events: list = []

    def capture_log(event_type: str, payload: dict | None = None):
        events.append((event_type, payload or {}))

    runtime = MemoryRuntime(
        store=InMemoryMemoryStore(),
        confirmation_adapter=FakeMemoryConfirmationAdapter(
            preset_choice=MemoryConfirmationChoice.ACCEPT,
        ),
        event_logger=capture_log,
    )
    runtime.evaluate_user_text("remember that I prefer concise answers")

    event_types = [e[0] for e in events]
    assert "memory.candidate_detected" in event_types
    assert "memory.confirmation_requested" in event_types
    assert "memory.confirmation_accepted" in event_types
    assert "memory.stored" in event_types


def test_blocked_memory_logs_blocked_event():
    """敏感内容拦截 → 记录 memory.blocked 事件。"""
    events: list = []

    def capture_log(event_type: str, payload: dict | None = None):
        events.append((event_type, payload or {}))

    runtime = MemoryRuntime(
        store=InMemoryMemoryStore(),
        confirmation_adapter=FakeMemoryConfirmationAdapter(),
        event_logger=capture_log,
    )
    runtime.evaluate_user_text("remember that my api key is sk-secret")

    event_types = [e[0] for e in events]
    assert "memory.blocked" in event_types


def test_snapshot_generation_logs_injected_event():
    """snapshot 生成时记录 memory.injected 事件。"""
    events: list = []

    def capture_log(event_type: str, payload: dict | None = None):
        events.append((event_type, payload or {}))

    runtime = MemoryRuntime(
        store=InMemoryMemoryStore(),
        confirmation_adapter=FakeMemoryConfirmationAdapter(),
        event_logger=capture_log,
    )
    runtime.evaluate_user_text("remember that I prefer concise answers")

    events.clear()
    runtime.snapshot_for_prompt()

    event_types = [e[0] for e in events]
    assert "memory.injected" in event_types


# ---------------------------------------------------------------------------
# 6. reject 不写入 store
# ---------------------------------------------------------------------------


def test_rejected_memory_not_stored():
    """fake confirmation reject → store 无 record。"""
    runtime = _make_runtime(accept=False)

    result = runtime.evaluate_user_text("remember that I prefer concise answers")

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
    runtime = _make_runtime(accept=True)
    result = runtime.evaluate_user_text("hello")
    assert result.action is MemoryEvaluationAction.NO_OP
    assert result.decision_type is None

    # STORED 时 decision_type 为 RETAIN
    result2 = runtime.evaluate_user_text("remember that X")
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
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)

    assert "input" not in calls, "memory_runtime.py must not call input()"


# ---------------------------------------------------------------------------
# 10. confirmation adapter protocol 可注入
# ---------------------------------------------------------------------------


def test_fake_confirmation_adapter_accept_and_reject():
    """FakeMemoryConfirmationAdapter 的 accept/reject 行为正确。"""
    from agent.memory_confirmation import (
        MemoryConfirmationChoice,
        MemoryConfirmationStatus,
    )
    from agent.memory_contracts import (
        MemoryCandidate,
        MemoryDecision,
        MemoryDecisionType,
        MemoryScope,
        MemorySensitivity,
        MemorySource,
    )

    candidate = MemoryCandidate(
        id="cand-1",
        content="test",
        source=MemorySource.USER_INPUT,
        source_event=None,
        proposed_type="explicit_retain",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.LOW,
        stability="user_asserted",
        confidence=0.9,
        reason="test",
    )
    decision = MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=candidate,
        action="retain",
        requires_user_confirmation=True,
        reason="test",
        provenance="cand-1",
    )
    from agent.memory_confirmation import build_memory_confirmation_request

    request = build_memory_confirmation_request(decision)

    accept_adapter = FakeMemoryConfirmationAdapter(
        preset_choice=MemoryConfirmationChoice.ACCEPT,
    )
    result = accept_adapter.request_confirmation(request)
    assert result.status is MemoryConfirmationStatus.APPROVED

    reject_adapter = FakeMemoryConfirmationAdapter(
        preset_choice=MemoryConfirmationChoice.REJECT,
    )
    result2 = reject_adapter.request_confirmation(request)
    assert result2.status is MemoryConfirmationStatus.REJECTED


# ---------------------------------------------------------------------------
# 11. deferred adapter auto-accept（v1 生产默认）
# ---------------------------------------------------------------------------


def test_deferred_confirmation_adapter_auto_accepts_explicit_retain():
    """DeferredMemoryConfirmationAdapter 在 v1 中 auto-accept explicit retain。

    v1 临时策略：因为 explicit retain 的用户意图已通过输入文本明确表达，
    DeferredMemoryConfirmationAdapter 会 emit RuntimeEvent（如有 on_event），
    并返回 APPROVED。store 写入 → snapshot → prompt 完整闭环。

    后续真实 Ask User / request_user_input confirmation 接入时，
    此 adapter 将被替换为交互式实现。本测试显式记录当前 v1 行为。
    """
    from agent.memory_runtime import DeferredMemoryConfirmationAdapter, MemoryEvaluationAction
    from agent.memory_store import InMemoryMemoryStore

    events: list = []

    def capture(event_type: str, payload: dict | None = None):
        events.append((event_type, payload or {}))

    runtime = MemoryRuntime(
        store=InMemoryMemoryStore(),
        confirmation_adapter=DeferredMemoryConfirmationAdapter(),
        event_logger=capture,
    )

    result = runtime.evaluate_user_text("remember that I prefer concise answers")
    assert result.action is MemoryEvaluationAction.STORED

    # store 中应有 approved record
    records = runtime._store.list_records()
    assert len(records) == 1
    assert "I prefer concise answers" in records[0].content
    assert records[0].approval_status == "approved"

    # audit events 包含 confirmation_accepted 和 stored
    event_types = [e[0] for e in events]
    assert "memory.confirmation_accepted" in event_types
    assert "memory.stored" in event_types

    # snapshot 可看到 memory
    snapshot = runtime.snapshot_for_prompt()
    assert len(snapshot.items) == 1


def test_deferred_confirmation_adapter_emits_runtime_event_when_on_event_provided():
    """DeferredMemoryConfirmationAdapter 在提供 on_event 时 emit RuntimeEvent。"""
    from agent.memory_runtime import DeferredMemoryConfirmationAdapter
    from agent.memory_store import InMemoryMemoryStore

    on_event_calls: list = []

    runtime = MemoryRuntime(
        store=InMemoryMemoryStore(),
        confirmation_adapter=DeferredMemoryConfirmationAdapter(
            on_event=on_event_calls.append,
        ),
    )

    runtime.evaluate_user_text("remember that I prefer concise answers")

    # on_event 被调用
    assert len(on_event_calls) >= 1
    emitted = on_event_calls[0]
    assert emitted["type"] == "memory_confirmation_requested"
    assert "question" in emitted
    assert "preview" in emitted


def test_create_memory_runtime_defaults_to_deferred_adapter():
    """create_memory_runtime() 默认使用 DeferredMemoryConfirmationAdapter。

    验证 v1 生产默认行为：不传 confirmation_adapter 时，
    explicit retain → auto-accept → store 写入 → snapshot。
    """
    from agent.memory_runtime import create_memory_runtime, MemoryEvaluationAction
    from agent.memory_store import InMemoryMemoryStore

    runtime = create_memory_runtime(store=InMemoryMemoryStore())

    result = runtime.evaluate_user_text("remember that I prefer concise answers")
    assert result.action is MemoryEvaluationAction.STORED

    records = runtime._store.list_records()
    assert len(records) == 1

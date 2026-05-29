"""SubAgent L1 parent-mediated child loop contract tests — Loop 3.2a.

TDD intent (SDD §4.1): 所有 L1 测试必须防止 fake/demo/direct-call 冒充 L1。

验证：
- child loop 调 provider.chat()（非 deterministic keyword-match）
- child tool_use → parent TOOL_GATE→TOOL_INVOKE→TOOL_RESULT pipeline
- blocked child tool 不进 execute_single_tool
- 所有 child action 有 dispatcher evidence
- L1 result 不是 deterministic keyword-match summary

架构依据：
- docs/design/subagent-l1-l2-execution-contract.md §3 (Unified Main Runtime Path)
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.provider.protocol import (
    ProviderResponse,
    ProviderTextBlock,
    ToolUseBlock,
)
from agent.runtime_integration.evidence import REAL_CORE_LOOP_RUNTIME_E2E
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.subagent_system.context import build_context_package
from agent.subagent_system.delegation import delegate_l1
from agent.subagent_system.executor import execute_l1
from agent.subagent_system.request import SubAgentRequest

# ═══════════════════════════════════════════════════════════════════════════
# Test doubles
# ═══════════════════════════════════════════════════════════════════════════


class _SpyProvider:
    """记录 provider.chat() 调用的 spy provider。

    不是 FakeProvider——每步行为由 test 显式控制（scripted responses）。
    """

    provider_type = "spy"
    supports_tools = True
    supports_streaming = False

    def __init__(self, responses: list[ProviderResponse] | None = None):
        self.responses = responses or []
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []

    def add_response(self, response: ProviderResponse) -> None:
        self.responses.append(response)

    def create(
        self,
        *,
        system: str = "",
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        self._call_count += 1
        self.calls.append({
            "system": system,
            "messages": list(messages or []),
            "tools": list(tools or []),
        })
        if self._call_count <= len(self.responses):
            return self.responses[self._call_count - 1]
        # 默认：end_turn 文本响应
        return ProviderResponse(
            content=[ProviderTextBlock(text="L1 任务完成。")],
            stop_reason="end_turn",
            raw_provider_name="spy",
        )


class _SpyDispatcher:
    """拦截 dispatcher.route_from_runtime_loop() 调用。"""

    def __init__(self):
        self.captured: list[tuple[RuntimeActionRequest, Any]] = []

    def route_from_runtime_loop(self, request: RuntimeActionRequest, **kwargs) -> Any:
        from agent.runtime_integration.schema import RuntimeActionResult

        result = RuntimeActionResult(
            action_type=request.action_type,
            status="success",
            payload=dict(request.payload),
            evidence={
                "evidence_level": REAL_CORE_LOOP_RUNTIME_E2E,
                "dispatcher_origin": "runtime_loop",
            },
        )
        self.captured.append((request, result))
        return result

    def route(self, request: RuntimeActionRequest) -> Any:
        from agent.runtime_integration.schema import RuntimeActionResult

        result = RuntimeActionResult(
            action_type=request.action_type,
            status="success",
            payload=dict(request.payload),
            evidence={"evidence_level": "direct"},
        )
        self.captured.append((request, result))
        return result


class _SpyToolMediator:
    """记录 child tool/memory request 的 spy mediator。"""

    def __init__(self, *, block_list: frozenset[str] | None = None):
        self.child_requests: list[dict[str, Any]] = []
        self.child_memory_requests: list[dict[str, Any]] = []
        self._block_list = block_list or frozenset()

    def mediate_child_tool_request(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        delegation_id: str = "",
        parent_trace_id: str = "",
    ) -> str | None:
        self.child_requests.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "delegation_id": delegation_id,
            "parent_trace_id": parent_trace_id,
        })
        if tool_name in self._block_list:
            from agent.tool_executor import FORCE_STOP
            return FORCE_STOP
        return None  # 成功

    def mediate_child_memory_request(
        self,
        key: str,
        value: str,
        *,
        delegation_id: str = "",
        parent_trace_id: str = "",
        subagent_name: str = "",
        memory_scope: str = "none",
    ) -> str | None:
        self.child_memory_requests.append({
            "key": key,
            "value": value,
            "delegation_id": delegation_id,
            "parent_trace_id": parent_trace_id,
            "subagent_name": subagent_name,
            "memory_scope": memory_scope,
        })
        if memory_scope == "none":
            return "rejected"
        return None

    def _dispatch_child_tool_evidence(
        self, tool_name: str, arguments: dict[str, Any],
        delegation_id: str, parent_trace_id: str,
        *, gate_disposition: str | None = None,
    ) -> None:
        """Spy: record child tool dispatch calls."""
        self.child_requests.append({
            "_dispatch": "child_tool",
            "tool_name": tool_name,
            "arguments": arguments,
            "delegation_id": delegation_id,
            "parent_trace_id": parent_trace_id,
            "gate_disposition": gate_disposition,
        })

    def _dispatch_child_result_evidence(
        self, *, delegation_id: str, parent_trace_id: str,
        subagent_name: str, status: str, stop_reason: str,
        summary: str, iterations_used: int,
    ) -> None:
        """Spy: record child result dispatch calls."""


def _make_tool_use_response(text: str, tool_name: str, tool_input: dict[str, Any]) -> ProviderResponse:  # noqa: E501
    """构建包含 tool_use 的 ProviderResponse。"""
    return ProviderResponse(
        content=[
            ProviderTextBlock(text=text),
            ToolUseBlock(
                id=f"toolu_{tool_name}_001",
                name=tool_name,
                input=tool_input,
            ),
        ],
        stop_reason="tool_use",
        raw_provider_name="spy",
    )


def _make_ctx(delegation_goal: str = "count files", *, max_iterations: int = 5) -> object:
    """构建最小 context_package 用于 execute_l1 调用。"""
    request = SubAgentRequest(
        task=delegation_goal,
        role="统计员",
        allowed_tools=("read_file",),
        parent_trace_id="test-trace",
        delegation_reason="test delegation",
        execution_mode="local_fake",
        max_iterations=max_iterations,
    )
    return build_context_package(
        request=request,
        descriptor=None,
        tool_snapshots=(),
    )


# ═══════════════════════════════════════════════════════════════════════════
# T1: Child loop calls provider (not deterministic keyword-match)
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildCallsProvider:
    """T1: L1 executor 调 provider.chat()，非 deterministic keyword-match。"""

    def test_l1_executor_calls_provider(self):
        """execute_l1() 必须调用 provider.create()。"""
        provider = _SpyProvider()
        ctx = _make_ctx("count files in workspace")

        result = execute_l1(ctx, delegation_id="test-l1", provider=provider)

        assert provider._call_count >= 1, (
            f"L1 executor 必须调用 provider.create()，实际调用 {provider._call_count} 次"
        )
        # L1 结果不应是 deterministic keyword-match
        assert "deterministic L0 summary" not in result.summary, (
            "L1 结果不应包含 'deterministic L0 summary'——这是 L0 keyword-match 的标记"
        )

    def test_l1_result_not_deterministic_keyword_match(self):
        """L1 summary 不应来自 keyword matching（如 shell/loop until max 等）。"""
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="根据统计，workspace 中共有 42 个文件。")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("count files")

        result = execute_l1(ctx, delegation_id="test-l1", provider=provider)

        # 不应包含 L0 deterministic keyword-match 标记
        for keyword in (
            "deterministic L0",
            "max_iterations_exceeded",
            "policy_blocked",
            "needs_clarification",
        ):
            assert keyword not in result.summary, (
                f"L1 summary 包含 L0 keyword-match 标记 '{keyword}'"
            )
        assert result.status == "ok", f"正常完成应为 'ok'，实际 {result.status!r}"


# ═══════════════════════════════════════════════════════════════════════════
# T2: Child tool_use → parent TOOL_GATE→TOOL_INVOKE→TOOL_RESULT pipeline
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildToolRequestParentMediated:
    """T2: child tool_use 通过 parent ToolRuntimeMediator 执行。"""

    def test_child_tool_use_goes_through_parent_mediator(self):
        """child provider 返回 tool_use → parent mediator 收到 child tool request。"""
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            _make_tool_use_response(
                "让我读取文件...",
                "read_file",
                {"path": "/tmp/test.txt"},
            ),
            ProviderResponse(
                content=[ProviderTextBlock(text="文件读取完成，共 3 行。")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("read and count")

        _result = execute_l1(
            ctx,
            delegation_id="test-l1-tool",
            provider=provider,
            tool_mediator=mediator,
        )

        assert len(mediator.child_requests) >= 1, (
            f"child tool_use 应触发 parent mediator，实际 child_requests={mediator.child_requests}"
        )
        assert mediator.child_requests[0]["tool_name"] == "read_file"

    def test_child_tool_use_multi_turn(self):
        """child loop 可以做多轮迭代（tool_use → result → 继续 → end_turn）。"""
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            _make_tool_use_response("第一轮工具调用", "read_file", {"path": "/a.txt"}),
            _make_tool_use_response("第二轮工具调用", "read_file", {"path": "/b.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="两轮工具调用完成。")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("multi-turn task", max_iterations=5)

        result = execute_l1(
            ctx,
            delegation_id="test-l1-multi",
            provider=provider,
            tool_mediator=mediator,
        )

        assert len(mediator.child_requests) >= 2, (
            f"多轮 tool_use 应触发 2+ 次 mediator，实际 {len(mediator.child_requests)}"
        )
        assert result.status == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# T3: Blocked child tool not executed
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildBlockedToolNotExecuted:
    """T3: blocked tool 不进 execute_single_tool。"""

    def test_blocked_tool_returns_force_stop(self):
        """不在 allowed_tools 中的工具 → mediator 返回 FORCE_STOP。"""
        mediator = _SpyToolMediator(block_list=frozenset({"shell"}))
        provider = _SpyProvider([
            _make_tool_use_response("尝试执行 shell", "shell", {"command": "ls"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="shell 被阻断后继续。")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("dangerous task")

        _result = execute_l1(
            ctx,
            delegation_id="test-l1-blocked",
            provider=provider,
            tool_mediator=mediator,
        )

        # 验证 shell 确实被请求了
        shell_requests = [
            r for r in mediator.child_requests
            if r["tool_name"] == "shell"
        ]
        assert len(shell_requests) >= 1, "shell 工具应被 child 请求"


# ═══════════════════════════════════════════════════════════════════════════
# T4: Dispatcher evidence for all child actions
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildDispatcherEvidence:
    """T4: 所有 child action 在 dispatcher action_log 中有对应条目。"""

    def test_delegate_l1_produces_dispatcher_evidence(self):
        """delegate_l1() 应通过 dispatcher 产生 SUBAGENT_DELEGATE_L1 evidence。"""
        provider = _SpyProvider()
        ctx = _make_ctx("test dispatcher evidence")

        result = execute_l1(
            ctx,
            delegation_id="test-l1-evidence",
            provider=provider,
        )

        assert result.status == "ok"

    def test_child_tool_request_produces_dispatcher_evidence(self):
        """child tool_use 应通过 dispatcher 产生 SUBAGENT_CHILD_TOOL_REQUEST evidence。"""
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            _make_tool_use_response("read file", "read_file", {"path": "/tmp/x.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="done")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("test child tool evidence")

        _result = execute_l1(
            ctx,
            delegation_id="test-l1-child-tool-ev",
            provider=provider,
            tool_mediator=mediator,
        )

        assert len(mediator.child_requests) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# T5: Not fakeable — L1 result is not deterministic keyword-match
# ═══════════════════════════════════════════════════════════════════════════


class TestL1NotFakeable:
    """T5: L1 不能通过 deterministic keyword-match 冒充真实 child execution。"""

    L0_KEYWORDS = (
        "deterministic L0 summary",
        "max_iterations_exceeded",
        "policy_blocked",
        "needs_clarification",
    )

    def test_no_l0_summary_leak(self):
        """正常 L1 执行不应包含 L0 deterministic summary。"""
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="真实分析结果：代码库结构良好")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("analyze codebase")

        result = execute_l1(ctx, delegation_id="test-l1-real", provider=provider)

        for kw in self.L0_KEYWORDS:
            assert kw not in result.summary, (
                f"L1 result 包含 L0 标记 '{kw}'——疑似 L0 keyword-match 冒充 L1"
            )

    def test_shell_keyword_does_not_trigger_policy_blocked_in_l1(self):
        """L1 不应因为 task 包含 'shell' 就返回 policy_blocked（那是 L0 行为）。"""
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="Shell 相关任务已分析完成。")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("analyze shell scripts in repo")

        result = execute_l1(ctx, delegation_id="test-l1-shell", provider=provider)

        # L1 不走 keyword-match → task 含 'shell' 不应触发 L0 的 policy_blocked
        assert result.stop_reason != "policy_blocked", (
            "L1 不应因 task 含 'shell' 就 policy_blocked——这是 L0 keyword-match 行为"
        )

    def test_needs_clarification_keyword_does_not_trigger_l0_behavior(self):
        """L1 不应因为 task 包含 'needs clarification' 就返回 L0 clarification。"""
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="任务已澄清并完成。")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("this task needs clarification before proceeding")

        result = execute_l1(ctx, delegation_id="test-l1-clarify", provider=provider)

        assert result.stop_reason != "needs_clarification", (
            "L1 不应因 task 含 'needs clarification' 就返回 needs_clarification——"
            "这是 L0 keyword-match 行为"
        )


# ═══════════════════════════════════════════════════════════════════════════
# T6: Child inherits parent provider
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildInheritsParentProvider:
    """T6: child 使用 parent 的 provider instance/config。"""

    def test_child_uses_passed_provider(self):
        """execute_l1 使用传入的 provider，不独立创建。"""
        provider = _SpyProvider()
        ctx = _make_ctx("test provider inheritance")

        execute_l1(ctx, delegation_id="test-l1-inherit", provider=provider)

        assert provider._call_count >= 1, (
            "L1 应使用传入的 provider，不应独立创建"
        )


# ═══════════════════════════════════════════════════════════════════════════
# T7: delegate_l1() integration
# ═══════════════════════════════════════════════════════════════════════════


class TestDelegateL1Integration:
    """T7: delegate_l1() 端到端集成验证。"""

    def test_delegate_l1_returns_subagent_run(self):
        """delegate_l1() 返回 SubAgentRun 结构。"""
        from agent.subagent_system.registry import SubAgentRegistry

        registry = SubAgentRegistry(roots=[Path("tests/fixtures/subagents")])
        provider = _SpyProvider()

        request = SubAgentRequest(
            task="count files in workspace",
            role="统计员",
            allowed_tools=("read_file",),
            parent_trace_id="test-t7",
            delegation_reason="test L1",
            max_iterations=2,
            execution_mode="local_fake",
        )

        run = delegate_l1(
            request,
            registry,
            provider=provider,
        )

        assert run is not None
        assert run.delegation_id is not None
        assert run.result is not None


# ═══════════════════════════════════════════════════════════════════════════
# Loop 3.2b — Child memory mediation contract tests (TDD RED phase)
# ═══════════════════════════════════════════════════════════════════════════


class _SpyStore:
    """Tracks store.apply_operation_intent calls for child memory tests."""

    def __init__(self):
        from agent.memory_store import InMemoryMemoryStore

        self.calls: list[dict[str, Any]] = []
        self._inner = InMemoryMemoryStore()

    def apply_operation_intent(self, intent: Any, audit_summary: Any) -> Any:
        self.calls.append({"intent": intent, "audit_summary": audit_summary})
        return self._inner.apply_operation_intent(intent, audit_summary)

    def list_records(self) -> tuple[Any, ...]:
        return self._inner.list_records()


def _make_mediator_for_memory_tests(
    *,
    store: Any = None,
    dispatcher: Any = None,
) -> Any:
    """构建带 store 的 ToolRuntimeMediator 用于 child memory 测试。"""
    from agent.tool_runtime_mediator import ToolRuntimeMediator

    if dispatcher is None:
        dispatcher = _SpyDispatcher()

    return ToolRuntimeMediator(
        dispatcher,
        state=_DummyStateForMemory(),
        turn_state=_DummyStateForMemory(),
        turn_context={},
        messages=[],
        store=store,
    )


class _DummyStateForMemory:
    """Minimal state duck-type for ToolRuntimeMediator construction."""
    class Task:
        tool_execution_log: dict = {}
        current_step_index: int = 0
        status: str = "running"
        pending_tool: dict | None = None

    task = Task()


# ═══════════════════════════════════════════════════════════════════════════
# T8: Child memory proposal → parent-mediated store write
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildMemoryParentMediated:
    """T8: child memory proposal 通过 parent ToolRuntimeMediator 写入 store。"""

    def test_memory_scope_propose_writes_to_store(self):
        """memory_scope=propose → store.apply_operation_intent 被调用。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result = mediator.mediate_child_memory_request(
            key="user_preference",
            value="用户偏好：使用中文回答",
            subagent_name="test_agent",
            delegation_id="test-delegation",
            memory_scope="propose",
        )

        assert result is None, f"propose 应返回 None (success)，实际 {result!r}"
        assert len(store.calls) == 1, (
            f"propose 应调用 store.apply_operation_intent 1 次，"
            f"实际 {len(store.calls)} 次"
        )

    def test_memory_scope_none_no_write(self):
        """memory_scope=none → store 不被调用。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result = mediator.mediate_child_memory_request(
            key="should_not_write",
            value="这不该写入",
            subagent_name="test_agent",
            memory_scope="none",
        )

        assert result == "rejected", f"none 应返回 'rejected'，实际 {result!r}"
        assert len(store.calls) == 0, (
            f"memory_scope=none 不应调用 store，实际调用了 {len(store.calls)} 次"
        )

    def test_memory_scope_none_is_default(self):
        """未指定 memory_scope 时默认 none → 不写入 store。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result = mediator.mediate_child_memory_request(
            key="default_test",
            value="默认不应写入",
            subagent_name="test_agent",
        )

        assert result == "rejected", f"默认应返回 'rejected'，实际 {result!r}"
        assert len(store.calls) == 0

    def test_namespace_isolation_between_subagents(self):
        """不同 subagent 的 memory key 使用不同 namespace 前缀。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        mediator.mediate_child_memory_request(
            key="finding",
            value="agent_a 的发现",
            subagent_name="agent_a",
            memory_scope="propose",
        )
        mediator.mediate_child_memory_request(
            key="finding",
            value="agent_b 的发现",
            subagent_name="agent_b",
            memory_scope="propose",
        )

        assert len(store.calls) == 2

        source_a = store.calls[0]["intent"].source_summary
        source_b = store.calls[1]["intent"].source_summary

        assert "agent_a" in source_a, (
            f"agent_a 的 source_summary 应含 'agent_a'，实际 {source_a!r}"
        )
        assert "agent_b" in source_b, (
            f"agent_b 的 source_summary 应含 'agent_b'，实际 {source_b!r}"
        )
        assert source_a != source_b, (
            f"不同 subagent 的 source_summary 应不同: {source_a!r} vs {source_b!r}"
        )

    def test_store_record_contains_child_content(self):
        """写入 store 的 record content 应为 child 提供的 value。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        mediator.mediate_child_memory_request(
            key="analysis_result",
            value="代码库共有 42 个 Python 文件",
            subagent_name="analyzer",
            memory_scope="propose",
        )

        records = store.list_records()
        assert len(records) == 1
        assert "42 个 Python 文件" in records[0].content, (
            f"store record 应包含 child 内容，实际 {records[0].content!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# T9: Child memory request dispatcher evidence
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildMemoryDispatcherEvidence:
    """T9: child memory request 产生 SUBAGENT_CHILD_MEMORY_REQUEST evidence。"""

    def test_child_memory_request_dispatches_evidence(self):
        """mediate_child_memory_request 应通过 dispatcher 产生 evidence。"""
        from agent.runtime_integration.schema import RuntimeActionType

        dispatcher = _SpyDispatcher()
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store, dispatcher=dispatcher)

        mediator.mediate_child_memory_request(
            key="evidence_test",
            value="测试 dispatcher evidence",
            subagent_name="test_agent",
            delegation_id="test-evidence",
            memory_scope="propose",
        )

        child_memory_actions = [
            (req, res)
            for req, res in dispatcher.captured
            if req.action_type in (
                RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
                "subagent.child_memory_request",
            )
        ]
        assert len(child_memory_actions) >= 1, (
            f"应至少产生 1 条 SUBAGENT_CHILD_MEMORY_REQUEST evidence，"
            f"实际 captured={[(str(r.action_type),) for r, _ in dispatcher.captured]}"
        )

    def test_child_memory_rejected_also_produces_evidence(self):
        """即使 memory_scope=none 导致 rejected，也应产生 dispatcher evidence。"""
        from agent.runtime_integration.schema import RuntimeActionType

        dispatcher = _SpyDispatcher()
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store, dispatcher=dispatcher)

        mediator.mediate_child_memory_request(
            key="rejected_test",
            value="不应写入",
            subagent_name="test_agent",
            memory_scope="none",
        )

        child_memory_actions = [
            (req, res)
            for req, res in dispatcher.captured
            if req.action_type in (
                RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
                "subagent.child_memory_request",
            )
        ]
        assert len(child_memory_actions) >= 1, (
            "即使被 rejected，child memory request 也应有 dispatcher evidence"
        )


# ═══════════════════════════════════════════════════════════════════════════
# T10: Child memory not fakeable
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildMemoryNotFakeable:
    """T10: child memory 不能通过 direct-call/docs-only/no-crash 冒充。"""

    def test_child_cannot_directly_call_store(self):
        """验证 child memory 必须通过 mediator — 直接写 store 不算 child memory capability。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        mediator.mediate_child_memory_request(
            key="mediated",
            value="通过 mediator",
            subagent_name="test_agent",
            memory_scope="propose",
        )

        # 验证 mediator 确实调了 store（证明走的是 mediated path）
        assert len(store.calls) == 1, (
            "mediated path 应调用 store"
        )
        # 验证调用来自 mediator（source_summary 含 subagent 标识）
        intent = store.calls[0]["intent"]
        assert "test_agent" in intent.source_summary, (
            f"store write source 应标识 subagent，实际 {intent.source_summary!r}"
        )

    def test_not_docs_only(self):
        """child memory 必须经过 dispatcher 产生 evidence，不能仅靠文档声称。"""
        dispatcher = _SpyDispatcher()
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store, dispatcher=dispatcher)

        mediator.mediate_child_memory_request(
            key="real_test",
            value="真实测试",
            subagent_name="test_agent",
            memory_scope="propose",
        )

        # 必须有 dispatcher evidence（不能只是文档声称）
        assert len(dispatcher.captured) >= 1, (
            "child memory 必须有 dispatcher evidence，不能仅靠文档"
        )
        # store 必须被调用（不能只是 no-crash）
        assert len(store.calls) == 1, "store 必须被调用，不能只是 no-crash"

    def test_no_store_without_mediator(self):
        """没有 mediator 时 child memory 不应写入 store。"""
        store = _SpyStore()
        _mediator = _make_mediator_for_memory_tests(store=store)

        # 不调用 mediator → store 无写入
        assert len(store.calls) == 0, (
            "不经过 mediator 不应有 store 写入"
        )


# ═══════════════════════════════════════════════════════════════════════════
# T11: execute_l1 memory_scope integration
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ExecuteWithMemoryScope:
    """T11: execute_l1() 携带 memory_scope=propose 时触发 child memory 写入。"""

    def test_execute_l1_propose_triggers_memory_mediation(self):
        """execute_l1 在 memory_scope=propose 且 child 产出结果后调用 memory mediation。"""
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="分析结果：代码库结构良好，建议采用模块化架构。")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        _ctx = _make_ctx("analyze and remember findings", max_iterations=3)

        # 使用 memory_scope="propose" 的 context
        request = SubAgentRequest(
            task="analyze and remember findings",
            role="分析师",
            allowed_tools=("read_file",),
            parent_trace_id="test-t11",
            delegation_reason="test memory scope",
            max_iterations=3,
            execution_mode="local_fake",
            memory_scope="propose",
        )
        from agent.subagent_system.context import build_context_package
        ctx_propose = build_context_package(
            request=request,
            descriptor=None,
            tool_snapshots=(),
        )

        result = execute_l1(
            ctx_propose,
            delegation_id="test-l1-memory",
            provider=provider,
            tool_mediator=mediator,
        )

        assert result.status == "ok"
        # memory_scope=propose 时应触发 memory mediation
        assert len(mediator.child_memory_requests) >= 1, (
            f"memory_scope=propose 应产生 child memory request，"
            f"实际 {len(mediator.child_memory_requests)} 条"
        )

    def test_execute_l1_none_does_not_trigger_memory_mediation(self):
        """memory_scope=none → 不触发 child memory mediation。"""
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="分析完成。")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("analyze without memory")

        result = execute_l1(
            ctx,
            delegation_id="test-l1-no-memory",
            provider=provider,
            tool_mediator=mediator,
        )

        assert result.status == "ok"
        assert len(mediator.child_memory_requests) == 0, (
            f"memory_scope=none 不应产生 child memory request，"
            f"实际 {len(mediator.child_memory_requests)} 条"
        )

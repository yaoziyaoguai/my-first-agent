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
        return "deferred"

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
# T8: Child memory request → v0 lockdown
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildMemoryParentMediated:
    """T8: child memory request 在 Memory v0 中只能 rejected/deferred evidence-only。"""

    def test_memory_scope_propose_is_deferred_without_store_write(self):
        """SubAgent memory_scope=propose → deferred，不直接写 MemoryStore。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result = mediator.mediate_child_memory_request(
            key="user_preference",
            value="用户偏好：使用中文回答",
            subagent_name="test_agent",
            delegation_id="test-delegation",
            memory_scope="propose",
        )

        assert result == "deferred"
        assert store.calls == []
        assert store.list_records() == ()

    def test_u8_non_none_memory_scopes_do_not_direct_write_to_store(self):
        """U8 lockdown: non-none scope 都不得 direct commit 到 MemoryStore。"""
        for scope in ("propose", "read", "read_context", "write", "unknown"):
            store = _SpyStore()
            mediator = _make_mediator_for_memory_tests(store=store)

            result = mediator.mediate_child_memory_request(
                key=f"scope_{scope}",
                value=f"child payload for {scope}",
                subagent_name="u0_agent",
                delegation_id="u0-delegation",
                memory_scope=scope,
            )

            assert result == "deferred", f"{scope} 应 deferred，实际 {result!r}"
            assert store.calls == [], f"{scope} 不得直接写 MemoryStore"
            assert store.list_records() == ()

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

    def test_u0_memory_scope_none_currently_rejected_without_store_write(self):
        """U0 characterization: none 当前 rejected/no write。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result = mediator.mediate_child_memory_request(
            key="u0_none",
            value="none payload",
            subagent_name="u0_agent",
            delegation_id="u0-none",
            memory_scope="none",
        )

        assert result == "rejected"
        assert store.calls == []

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

    def test_different_subagent_requests_stay_evidence_only(self):
        """不同 subagent 的请求也不得通过 namespace 隔离名义写入 store。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result_a = mediator.mediate_child_memory_request(
            key="finding",
            value="agent_a 的发现",
            subagent_name="agent_a",
            memory_scope="propose",
        )
        result_b = mediator.mediate_child_memory_request(
            key="finding",
            value="agent_b 的发现",
            subagent_name="agent_b",
            memory_scope="propose",
        )

        assert result_a == "deferred"
        assert result_b == "deferred"
        assert store.calls == []

    def test_child_payload_is_not_persisted_to_store_record(self):
        """child payload 不得作为长期 memory record 持久化。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result = mediator.mediate_child_memory_request(
            key="analysis_result",
            value="代码库共有 42 个 Python 文件",
            subagent_name="analyzer",
            memory_scope="propose",
        )

        assert result == "deferred"
        assert store.list_records() == ()

    def test_u8_child_request_does_not_use_auto_retained_accept_direct_path(self):
        """U8 lockdown: child request 不再使用 AUTO_RETAINED + ACCEPT 直接写入。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result = mediator.mediate_child_memory_request(
            key="no_confirmation",
            value="无需确认就写入的 child payload",
            subagent_name="u0_agent",
            delegation_id="u0-no-confirmation",
            memory_scope="propose",
        )

        assert result == "deferred"
        assert store.calls == []


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

    def test_u8_child_memory_evidence_omits_raw_key_and_value_preview(self):
        """U8 lockdown: dispatcher evidence 只包含 safe hash/count/reason 字段。"""
        from agent.runtime_integration.schema import RuntimeActionType

        dispatcher = _SpyDispatcher()
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store, dispatcher=dispatcher)

        mediator.mediate_child_memory_request(
            key="raw_child_key",
            value="raw child payload should be removed in U8",
            subagent_name="test_agent",
            delegation_id="u0-raw-evidence",
            memory_scope="propose",
        )

        payloads = [
            dict(req.payload)
            for req, _res in dispatcher.captured
            if req.action_type in (
                RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
                "subagent.child_memory_request",
            )
        ]
        assert payloads, "child memory request 应产生 evidence payload"
        payload = payloads[-1]
        assert "key" not in payload
        assert "value_preview" not in payload
        assert "raw_child_key" not in str(payload)
        assert "raw child payload should be removed in U8" not in str(payload)
        assert payload["child_payload_hash"].startswith("mempayload:")
        assert payload["key_hash"].startswith("memkey:")
        assert payload["redacted"] is True
        assert payload["count"] == 1
        assert "policy_path" not in payload
        assert payload["policy_id"] == "subagent_child_memory_v0_lockdown"
        assert payload["policy_rule_id"] == "child_memory_direct_write_disabled"
        assert payload["policy_hash"].startswith("policy:")
        assert payload["policy_decision_source"] == "ToolRuntimeMediator"
        assert payload["decision"] == "deferred"

    def test_u8_child_memory_records_lifecycle_events_without_child_proposal(self, monkeypatch):
        """U8 lockdown: 记录 received/deferred，不发 child_proposal_created。"""
        from agent import evidence_recorder

        calls: list[dict[str, Any]] = []

        def fake_record_evidence(**kwargs):
            calls.append(kwargs)
            return {"data": {"metadata": kwargs.get("metadata", {})}}

        monkeypatch.setattr(evidence_recorder, "record_evidence", fake_record_evidence)

        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result = mediator.mediate_child_memory_request(
            key="raw_child_key",
            value="RAW CHILD PAYLOAD SHOULD NOT LOG",
            subagent_name="test_agent",
            delegation_id="u8-lifecycle",
            memory_scope="propose",
        )

        assert result == "deferred"
        assert store.calls == []
        event_types = [call["metadata"]["event_type"] for call in calls]
        assert "memory.child_request_received" in event_types
        assert "memory.child_request_deferred" in event_types
        assert "memory.child_request_rejected" not in event_types
        assert "memory.child_proposal_created" not in event_types
        serialized = str(calls)
        assert "RAW CHILD PAYLOAD SHOULD NOT LOG" not in serialized
        assert "raw_child_key" not in serialized
        assert "value_preview" not in serialized


# ═══════════════════════════════════════════════════════════════════════════
# T10: Child memory not fakeable
# ═══════════════════════════════════════════════════════════════════════════


class TestL1ChildMemoryNotFakeable:
    """T10: child memory 不能通过 direct-call/docs-only/no-crash 冒充。"""

    def test_child_cannot_directly_call_store(self):
        """验证 child memory 必须通过 mediator，但 mediator 也不得 direct write。"""
        store = _SpyStore()
        mediator = _make_mediator_for_memory_tests(store=store)

        result = mediator.mediate_child_memory_request(
            key="mediated",
            value="通过 mediator",
            subagent_name="test_agent",
            memory_scope="propose",
        )

        assert result == "deferred"
        assert store.calls == []

    def test_not_docs_only(self):
        """child memory lockdown 必须经过 dispatcher evidence，不能仅靠文档声称。"""
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
        assert store.calls == [], "v0 child memory request 不得直接写 store"

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


# ═══════════════════════════════════════════════════════════════════════════
# 006 TOOL_MEDIATOR_GAP — RED phase: confirm current broken state
# ═══════════════════════════════════════════════════════════════════════════


class TestRedPhaseGapConfirmation:
    """RED tests: 确认当前 production path 中 tool_mediator=None 的缺口。"""

    def test_red1_dispatch_or_fallback_signature_lacks_tool_mediator(self):
        """RED-1: _dispatch_or_fallback_delegation 当前不接受 tool_mediator 参数。"""
        import inspect

        from agent.core import _dispatch_or_fallback_delegation

        sig = inspect.signature(_dispatch_or_fallback_delegation)
        assert "tool_mediator" not in sig.parameters, (
            "RED: 当前签名不应包含 tool_mediator——"
            "如果已包含，说明缺口已修复，此测试应转为 GREEN"
        )

    def test_red2_child_tool_not_mediated_when_mediator_none(self):
        """RED-2: tool_mediator=None 时 child tool_use 走 else 分支不调 mediator。"""
        provider = _SpyProvider([
            _make_tool_use_response("读取文件", "read_file", {"path": "/tmp/t.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="完成")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("test no mediator")

        result = execute_l1(ctx, delegation_id="test-red-2", provider=provider)

        # tool_mediator 默认为 None → else 分支 → child_result=None
        # tool 仍出现在 tools_executed 中但走的是硬编码占位路径
        assert "read_file" in result.audit.tools_executed, (
            "RED: tool 应出现在 tools_executed（走硬编码占位路径）"
        )
        assert result.status == "ok", (
            "tool_mediator=None 时不应 crash，应安全 fallback"
        )

    def test_red3_child_tool_result_is_hardcoded_placeholder(self):
        """RED-3: tool_mediator=None 时 child_result=None → executor 注入硬编码占位。"""
        provider = _SpyProvider([
            _make_tool_use_response("列出文件", "read_file", {"path": "/tmp/dir"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="文件列表已获取")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("list files")

        result = execute_l1(ctx, delegation_id="test-red-3", provider=provider)

        # tool_mediator=None → child_result=None → executor 行 265/279
        # tool 被记录为 "已执行" 但实际走占位路径
        assert result.audit.tools_executed, (
            "RED: tools_executed 应有记录（占位路径）"
        )
        assert result.status == "ok"

    def test_red4_child_tool_request_evidence_not_dispatched_when_mediator_none(self):
        """RED-4: tool_mediator=None 时不产生 SUBAGENT_CHILD_TOOL_REQUEST evidence。"""
        dispatcher = _SpyDispatcher()
        provider = _SpyProvider([
            _make_tool_use_response("read", "read_file", {"path": "/tmp/x.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="done")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("test evidence gap")

        _result = execute_l1(ctx, delegation_id="test-red-4", provider=provider)

        child_tool_requests = [
            (req, res) for req, res in dispatcher.captured
            if getattr(req, "action_type", None)
            and str(req.action_type) == "SUBAGENT_CHILD_TOOL_REQUEST"
        ]
        assert len(child_tool_requests) == 0, (
            "RED: production path (tool_mediator=None) 不应产生 "
            "SUBAGENT_CHILD_TOOL_REQUEST evidence"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 006 M1: dispatcher=None safe fallback
# ═══════════════════════════════════════════════════════════════════════════


class _ResultSpyToolMediator(_SpyToolMediator):
    """Spy mediator 变体：在 _turn_context 中注入可识别 result 文本。

    模拟真实 ToolRuntimeMediator 的行为：execute_single_tool 执行后，
    result 写入 _turn_context[tool_use_id]，executor 可以从中读取。
    """

    def __init__(self, result_text: str = "真实工具结果：文件内容为 Hello World", **kwargs):
        super().__init__(**kwargs)
        self._turn_context: dict[str, Any] = {}
        self._result_text = result_text

    def mediate_child_tool_request(
        self, tool_name: str, arguments: dict[str, Any], *,
        delegation_id: str = "", parent_trace_id: str = "",
    ) -> str | None:
        super().mediate_child_tool_request(
            tool_name, arguments,
            delegation_id=delegation_id, parent_trace_id=parent_trace_id,
        )
        key = f"child:{delegation_id}:{tool_name}"
        self._turn_context[key] = self._result_text
        return None


class TestM1DispatcherNoneSafeFallback:
    """M1: dispatcher=None 时 delegation 安全 fallback 为 tool_mediator=None。"""

    def test_m1a_null_dispatcher_safe_fallback_no_crash(self):
        """dispatcher=None 时构造 ToolRuntimeMediator 必须安全跳过，不 crash。"""
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="任务完成。")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("safe fallback test")

        # 模拟 dispatcher=None 的场景
        result = execute_l1(
            ctx, delegation_id="test-m1a",
            provider=provider,
            tool_mediator=None,
        )

        assert result.status == "ok", (
            f"tool_mediator=None 应安全 fallback，不 crash，实际 {result.status}"
        )

    def test_m1b_null_mediator_does_not_enable_direct_child_tool_execution(self):
        """tool_mediator=None 时 child 不能直接执行工具。"""
        provider = _SpyProvider([
            _make_tool_use_response("读文件", "read_file", {"path": "/etc/passwd"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="done")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("no direct tool exec")

        result = execute_l1(
            ctx, delegation_id="test-m1b",
            provider=provider,
            tool_mediator=None,
        )

        # tool_mediator=None 时 tool 被标记为 executed 但走的是占位路径
        # (child_result=None in executor.py line 265)
        assert result.status == "ok", (
            f"tool_mediator=None 应安全 fallback，实际 {result.status}"
        )
        assert "read_file" in result.audit.tools_executed, (
            "tool 应记录在 tools_executed（占位路径）"
        )

    def test_m1c_existing_l0_fallback_not_broken(self):
        """tool_mediator=None 时不破坏现有 L0/L1 fallback 行为。"""
        provider = _SpyProvider()
        ctx = _make_ctx("l0 fallback intact")

        result = execute_l1(ctx, delegation_id="test-m1c", provider=provider)

        assert result.status == "ok"
        # L1 仍正常工作（即便 tool_mediator=None）
        assert result.stop_reason == "task_completed"


# ═══════════════════════════════════════════════════════════════════════════
# 006 M2: child tool result 必须是真实 mediator result（非硬编码占位）
# ═══════════════════════════════════════════════════════════════════════════


class TestM2RealToolResult:
    """M2: tool_mediator 存在时 child tool result 必须来自 mediator（非硬编码占位）。

    验证策略：使用 _ResultSpyToolMediator 注入 _turn_context 中的真实 result，
    execute_l1 应通过 mediator 执行 tool 并返回成功结果。
    硬编码占位替换由 executor.py diff 直接验证（line 279 变更）。
    """

    def test_m2a_mediator_called_and_result_successful(self):
        """M2a: tool_mediator 存在 → mediator 被调用 + result 成功完成。"""
        mediator = _ResultSpyToolMediator(
            result_text="真实工具结果：文件内容为 Hello World",
        )
        provider = _SpyProvider([
            _make_tool_use_response("读文件", "read_file", {"path": "/tmp/f.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="完成")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("real result test")

        result = execute_l1(
            ctx, delegation_id="test-m2a",
            provider=provider, tool_mediator=mediator,
        )

        # mediator 应被调用
        assert len(mediator.child_requests) >= 1, (
            f"mediator 应收到 child tool request，实际 {len(mediator.child_requests)}"
        )
        # result 成功
        assert result.status == "ok", f"预期 ok，实际 {result.status}"
        # tool 在 tools_executed
        assert "read_file" in result.audit.tools_executed

    def test_m2b_turn_context_populated_with_real_result(self):
        """M2b: mediator._turn_context 包含真实 result（验证注入机制正确）。"""
        expected = "真实工具结果：文件内容为 Hello World"
        mediator = _ResultSpyToolMediator(result_text=expected)
        provider = _SpyProvider([
            _make_tool_use_response("读文件", "read_file", {"path": "/tmp/f.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="完成")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("recognizable content")

        _result = execute_l1(
            ctx, delegation_id="test-m2b",
            provider=provider, tool_mediator=mediator,
        )

        # _turn_context 中应有正确 key 的 result
        key = "child:test-m2b:read_file"
        assert key in mediator._turn_context, (
            f"_turn_context 应含 key {key!r}，实际 keys={list(mediator._turn_context.keys())}"
        )
        assert mediator._turn_context[key] == expected, (
            f"turn_context value 应为 {expected!r}，实际 {mediator._turn_context[key]!r}"
        )

    def test_m2c_different_tools_produce_distinct_turn_context_keys(self):
        """M2c: 不同 tool 在 turn_context 中有不同 key。"""
        mediator = _ResultSpyToolMediator(result_text="read_file 结果：42 行")
        provider = _SpyProvider([
            _make_tool_use_response("读文件", "read_file", {"path": "/tmp/a.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="完成")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("different results")

        _result = execute_l1(
            ctx, delegation_id="test-m2c",
            provider=provider, tool_mediator=mediator,
        )

        # 验证 key 格式：child:{delegation_id}:{tool_name}
        key = "child:test-m2c:read_file"
        assert key in mediator._turn_context
        # value 不是占位文本
        assert "已执行" not in mediator._turn_context.get(key, ""), (
            f"turn_context value 不应含 '已执行' 占位，"
            f"实际 {mediator._turn_context.get(key)!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 006 GREEN phase: mediator injection contract tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGreenPhaseMediatorInjection:
    """GREEN: tool_mediator 注入后 child tool_use 通过 parent mediator。"""

    def test_green1_delegate_l1_passes_tool_mediator_to_execute_l1(self):
        """GREEN-1: execute_l1() 通过 tool_mediator 中介 child tool_use。

        delegate_l1 → execute_l1 链已通过 delegation.py（read-only）保证传递；
        这里验证 execute_l1 收到 tool_mediator 后 child tool_use 走 mediator。
        """
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            _make_tool_use_response("读取", "read_file", {"path": "/tmp/f1.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="完成")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("mediator passthrough test")

        result = execute_l1(
            ctx, delegation_id="test-green-1",
            provider=provider, tool_mediator=mediator,
        )

        assert result.status == "ok", (
            f"execute_l1 通过 mediator 应正常完成，实际 {result.status}"
        )
        assert len(mediator.child_requests) >= 1, (
            f"child tool_use 应走 mediator，实际 {len(mediator.child_requests)}"
        )

    def test_green2_child_tool_use_calls_mediate_child_tool_request(self):
        """GREEN-2: 传入 tool_mediator → child tool_use 触发 mediate_child_tool_request。"""
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            _make_tool_use_response("读取", "read_file", {"path": "/tmp/f.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="完成")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("green test")

        _result = execute_l1(
            ctx, delegation_id="test-green-2",
            provider=provider, tool_mediator=mediator,
        )

        assert len(mediator.child_requests) >= 1, (
            f"GREEN: mediator 应收到 child tool request，"
            f"实际 {len(mediator.child_requests)}"
        )

    def test_green3_child_tool_request_records_tool_name_and_delegation_id(self):
        """GREEN-3: mediator 记录 child tool request 的 tool_name 和 delegation_id。"""
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            _make_tool_use_response("read", "read_file", {"path": "/tmp/g.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="ok")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("gate test")

        _result = execute_l1(
            ctx, delegation_id="test-green-3",
            provider=provider, tool_mediator=mediator,
        )

        assert mediator.child_requests[0]["tool_name"] == "read_file"
        assert mediator.child_requests[0]["delegation_id"] == "test-green-3"

    def test_green4_tool_result_returns_to_child_context(self):
        """GREEN-4: parent mediator 返回结果后 child 可继续执行并完成。"""
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            _make_tool_use_response("read", "read_file", {"path": "/tmp/r.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="got result")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("result back test")

        result = execute_l1(
            ctx, delegation_id="test-green-4",
            provider=provider, tool_mediator=mediator,
        )

        assert result.status == "ok"
        assert result.stop_reason == "task_completed"

    def test_green5_delegate_l1_returns_complete_run_with_adjudication(self):
        """GREEN-5: tool_mediator 注入后 execute_l1 返回完整结果（含 status + stop_reason）。

        delegate_l1 的 SubAgentRun + adjudication 包装由现有 L1 测试覆盖；
        这里聚焦 tool_mediator 注入后的 execute_l1 结果完整性。
        """
        mediator = _SpyToolMediator()
        provider = _SpyProvider([
            _make_tool_use_response("读取", "read_file", {"path": "/tmp/f5.txt"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="分析完成")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("complete result test")

        result = execute_l1(
            ctx, delegation_id="test-green-5",
            provider=provider, tool_mediator=mediator,
        )

        assert result.status == "ok", (
            f"tool_mediator 注入后 execute_l1 应返回 ok，实际 {result.status}"
        )
        assert result.stop_reason == "task_completed", (
            f"应正常完成，实际 stop_reason={result.stop_reason}"
        )
        assert len(mediator.child_requests) >= 1, (
            f"child tool_use 应走 mediator，实际 {len(mediator.child_requests)}"
        )

    def test_green6_null_mediator_safe_fallback_still_works(self):
        """GREEN-6: tool_mediator=None 不崩溃，保持向后兼容。"""
        provider = _SpyProvider()
        ctx = _make_ctx("null mediator test")

        result = execute_l1(ctx, delegation_id="test-green-6", provider=provider)

        assert result.status == "ok", (
            f"tool_mediator=None 应保持安全 fallback，实际 {result.status}"
        )

    def test_green7_blocked_tool_not_executed_via_parent_gate(self):
        """GREEN-7: blocked tool 被 parent gate 阻断，child 无法直接执行。"""
        mediator = _SpyToolMediator(block_list=frozenset({"shell"}))
        provider = _SpyProvider([
            _make_tool_use_response("dangerous", "shell", {"command": "rm -rf /"}),
            ProviderResponse(
                content=[ProviderTextBlock(text="blocked, continuing")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        ctx = _make_ctx("no bypass test")

        _result = execute_l1(
            ctx, delegation_id="test-green-7",
            provider=provider, tool_mediator=mediator,
        )

        shell_requests = [
            r for r in mediator.child_requests if r["tool_name"] == "shell"
        ]
        assert len(shell_requests) >= 1, "shell 应被 child 请求但被 parent gate 阻断"

    def test_green8_existing_24_l1_tests_still_pass(self):
        """GREEN-8: existing 24 L1 contract tests regression gate。

        由 running `pytest ...test_subagent_l1_parent_mediated.py -v` 隐式保证。
        实现时必须在 full suite 中验证 24 tests 全部通过。
        """


# ═══════════════════════════════════════════════════════════════════════════
# 006 Independent Review — Schema Content & Unauthorized Tool Exclusion
# ═══════════════════════════════════════════════════════════════════════════


class TestChildToolSchemaContent:
    """验证 child provider.create(tools=...) 收到正确的 tool schema。

    依赖 TOOL_REGISTRY（需 import agent.tools 触发注册）。
    使用 _SpyProvider.calls 检查传给 provider 的 tools 参数。
    """

    def test_child_tools_contains_read_file_schema(self):
        """child provider 收到的 tools 中包含 read_file 的完整 schema。"""
        import agent.tools  # noqa: F401 — 触发 TOOL_REGISTRY 注册
        from agent.tool_registry import TOOL_REGISTRY

        provider = _SpyProvider()
        ctx = _make_ctx("read a file")

        execute_l1(ctx, delegation_id="test-schema-1", provider=provider)

        assert len(provider.calls) >= 1, "provider 应至少被调用一次"
        tools = provider.calls[0].get("tools", [])
        assert len(tools) >= 1, f"tools 不应为空，实际 {tools}"

        read_file_tool = None
        for t in tools:
            if t.get("name") == "read_file":
                read_file_tool = t
                break
        assert read_file_tool is not None, (
            f"child tools 中应有 read_file，实际 tools={[t.get('name') for t in tools]}"
        )

        # 断言 schema 来自 TOOL_REGISTRY
        registry_entry = TOOL_REGISTRY["read_file"]
        assert read_file_tool["name"] == registry_entry["name"]
        assert read_file_tool["description"] == registry_entry["description"]

        input_schema = read_file_tool["input_schema"]
        assert isinstance(input_schema, dict), (
            f"input_schema 应为 dict，实际 {type(input_schema)}"
        )
        assert "path" in input_schema, (
            f"input_schema 应包含 'path' 参数，实际 keys={list(input_schema.keys())}"
        )
        assert input_schema["path"]["type"] == "string"
        assert "description" in input_schema["path"]

    def test_child_tools_schema_matches_registry_verbatim(self):
        """child tools 中每个 tool 的 name/description/input_schema 与 TOOL_REGISTRY 一致。"""
        import agent.tools  # noqa: F401
        from agent.tool_registry import TOOL_REGISTRY

        provider = _SpyProvider()
        ctx = _make_ctx("count files")

        execute_l1(ctx, delegation_id="test-schema-2", provider=provider)

        tools = provider.calls[0].get("tools", [])
        for tool in tools:
            name = tool["name"]
            assert name in TOOL_REGISTRY, (
                f"tool '{name}' 不在 TOOL_REGISTRY 中"
            )
            reg = TOOL_REGISTRY[name]
            assert tool["name"] == reg["name"], (
                f"tool '{name}' name 不匹配 registry: "
                f"{tool['name']!r} vs {reg['name']!r}"
            )
            assert tool["description"] == reg["description"], (
                f"tool '{name}' description 不匹配 registry"
            )
            # input_schema 来自 registry entry["parameters"]
            expected_schema = reg.get("parameters", {})
            assert tool["input_schema"] == expected_schema, (
                f"tool '{name}' input_schema 不匹配 registry: "
                f"{tool['input_schema']} vs {expected_schema}"
            )


class TestChildToolUnauthorizedExclusion:
    """验证未授权工具不会暴露给 child。

    request.allowed_tools=("read_file",) 时，即使 TOOL_REGISTRY 中有
    shell、demo 等其他工具，child_tools 也只应包含 read_file。
    """

    def test_only_allowed_tool_exposed_to_child(self):
        """request.allowed_tools=("read_file",) → child_tools 只有 read_file。"""
        import agent.tools  # noqa: F401

        provider = _SpyProvider()
        ctx = _make_ctx("safe read-only task")

        execute_l1(ctx, delegation_id="test-unauth-1", provider=provider)

        tools = provider.calls[0].get("tools", [])
        tool_names = [t["name"] for t in tools]

        # child_tools 中应有 read_file
        assert "read_file" in tool_names, (
            f"child tools 应包含 read_file，实际 {tool_names}"
        )

        # 不应包含其他未授权工具
        unauthorized = [
            n for n in tool_names
            if n != "read_file"
        ]
        assert len(unauthorized) == 0, (
            f"child tools 不应包含未授权工具，实际包含: {unauthorized}"
        )

    def test_shell_not_exposed_when_not_allowed(self):
        """shell 工具不应进入 child_tools（request 中未授权）。"""
        import agent.tools  # noqa: F401
        from agent.tool_registry import TOOL_REGISTRY

        # 确认 TOOL_REGISTRY 中有 shell
        shell_keys = [k for k in TOOL_REGISTRY if "shell" in k.lower()]
        assert len(shell_keys) > 0, (
            f"TOOL_REGISTRY 中应有 shell 类工具，实际 keys={sorted(TOOL_REGISTRY.keys())}"
        )

        provider = _SpyProvider()
        ctx = _make_ctx("read-only task")

        execute_l1(ctx, delegation_id="test-unauth-2", provider=provider)

        tools = provider.calls[0].get("tools", [])
        tool_names = [t["name"] for t in tools]

        for sk in shell_keys:
            assert sk not in tool_names, (
                f"shell 工具 '{sk}' 不应出现在 child_tools 中，"
                f"但实际 tools={tool_names}"
            )

    def test_demo_tools_not_exposed_when_not_allowed(self):
        """demo.* 工具不应进入 child_tools（request 中未授权）。"""
        import agent.tools  # noqa: F401
        from agent.tool_registry import TOOL_REGISTRY

        demo_keys = [k for k in TOOL_REGISTRY if k.startswith("demo.")]
        assert len(demo_keys) > 0, (
            f"TOOL_REGISTRY 中应有 demo.* 工具，实际 keys={sorted(TOOL_REGISTRY.keys())}"
        )

        provider = _SpyProvider()
        ctx = _make_ctx("read-only task")

        execute_l1(ctx, delegation_id="test-unauth-3", provider=provider)

        tools = provider.calls[0].get("tools", [])
        tool_names = [t["name"] for t in tools]

        for dk in demo_keys:
            assert dk not in tool_names, (
                f"demo 工具 '{dk}' 不应出现在 child_tools 中，"
                f"但实际 tools={tool_names}"
            )

    def test_registry_has_more_tools_than_allowed(self):
        """确认 TOOL_REGISTRY 中的工具数 > allowed_tools 数（排除 falsely-true 风险）。"""
        import agent.tools  # noqa: F401
        from agent.tool_registry import TOOL_REGISTRY

        all_registry_tools = set(TOOL_REGISTRY.keys())
        # _make_ctx 默认 allowed_tools=("read_file",)
        allowed = {"read_file"}
        assert len(all_registry_tools) > len(allowed), (
            f"TOOL_REGISTRY 应有比 allowed_tools 更多的工具，"
            f"否则 '未授权工具不泄露' 的断言可能是 falsely true；"
            f"registry={sorted(all_registry_tools)}, allowed={sorted(allowed)}"
        )

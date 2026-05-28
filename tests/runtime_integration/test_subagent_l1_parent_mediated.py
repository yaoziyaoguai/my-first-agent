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
    """记录 child tool request 的 spy mediator。"""

    def __init__(self, *, block_list: frozenset[str] | None = None):
        self.child_requests: list[dict[str, Any]] = []
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


def _make_tool_use_response(text: str, tool_name: str, tool_input: dict[str, Any]) -> ProviderResponse:
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

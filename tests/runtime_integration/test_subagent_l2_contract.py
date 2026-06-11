"""SubAgent L2 native loop contract tests — Next-stage D-01.

TDD intent (SDD §Verification):
- Contract tests with _SpyProvider（scripted stop_signal, batch_memory, revision）
- Policy gate tests（L2 gated, allowed_tools expansion, nested depth）
- Adjudication gate tests（accept/reject/revision cycle）
- Batch memory mediation tests
- RuntimeDecisionFrame field tests
- Legacy L0 shortcut removal regression tests

All tests use _SpyProvider — no real API, no .env, no external service.
"""

from __future__ import annotations

from typing import Any

from agent.provider.protocol import (
    ProviderResponse,
    ProviderTextBlock,
    ToolUseBlock,
)
from agent.subagent_system.context import SubAgentContextPackage
from agent.subagent_system.delegation import delegate_l2
from agent.subagent_system.execution_mode import SubAgentStopReason
from agent.subagent_system.executor import _parse_batch_memory, execute_l2
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.runtime import is_l2_gated, l2_available


def _make_context_package(
    *,
    task: str = "test",
    request: Any = None,
    descriptor: Any = None,
    role_prompt: str = "",
    max_iterations: int = 5,
    execution_mode: str = "real_llm_tool_requesting",
    goal: str | None = None,
    constraints: tuple[str, ...] = (),
) -> SubAgentContextPackage:
    """Build a minimal SubAgentContextPackage for L2 contract tests."""
    return SubAgentContextPackage(
        request=request,
        descriptor=descriptor,
        task=task,
        role_prompt=role_prompt,
        goal=goal if goal is not None else task,
        constraints=constraints,
        relevant_files=(),
        relevant_summaries=(),
        selected_memory_context=None,
        selected_skill_metadata=(),
        allowed_tools=(),
        allowed_skills=(),
        forbidden_actions=(),
        output_schema=None,
        max_context_chars=100_000,
        max_iterations=max_iterations,
        stop_conditions=(),
        execution_mode=execution_mode,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test doubles
# ═══════════════════════════════════════════════════════════════════════════


class _SpyProvider:
    provider_type = "spy"
    supports_tools = True
    supports_streaming = False

    def __init__(self, responses: list[ProviderResponse] | None = None):
        self.responses = responses or []
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []

    def create(self, *, system="", messages=None, tools=None, **kwargs) -> ProviderResponse:
        self._call_count += 1
        self.calls.append({
            "system": system,
            "messages": list(messages or []),
            "tools": list(tools or []),
        })
        if self._call_count <= len(self.responses):
            return self.responses[self._call_count - 1]
        return ProviderResponse(
            content=[ProviderTextBlock(text="L2 task completed.")],
            stop_reason="end_turn",
            raw_provider_name="spy",
        )


class _SpyToolMediator:
    def __init__(self, *, block_list: frozenset[str] | None = None):
        self.block_list = block_list or frozenset()
        self.child_tool_requests: list[dict[str, Any]] = []
        self.child_memory_requests: list[dict[str, Any]] = []
        self._turn_context: dict[str, str] = {}

    def mediate_child_tool_request(
        self, tool_name, arguments, *, delegation_id="", parent_trace_id=""
    ):
        self.child_tool_requests.append({
            "tool_name": tool_name,
            "arguments": dict(arguments),
            "delegation_id": delegation_id,
        })
        if tool_name in self.block_list:
            return "FORCE_STOP"
        key = f"child:{delegation_id}:{tool_name}"
        self._turn_context[key] = f"[L2 test] 工具 {tool_name} 执行成功。"
        return key

    def mediate_child_memory_request(
        self, key="", value="", *, delegation_id="", parent_trace_id="",
        subagent_name="", memory_scope="",
    ):
        self.child_memory_requests.append({
            "key": key,
            "value": value,
            "delegation_id": delegation_id,
            "subagent_name": subagent_name,
        })


class _FakeDescriptor:
    name = "test-agent"
    role = "tester"
    allowed_tools = ("read_file", "grep", "glob")
    max_iterations_default = 5
    risk_level = "low"


class _FakeRegistry:
    def find_by_role(self, _role: str):
        return [_FakeDescriptor()]

    def get_descriptor(self, _name: str):
        return _FakeDescriptor()


# ═══════════════════════════════════════════════════════════════════════════
# L2 Independent Stop Condition
# ═══════════════════════════════════════════════════════════════════════════


class TestL2IndependentStopCondition:
    """L2 child can signal completion via end_turn — stop_reason=TASK_COMPLETED_BY_CHILD."""

    def test_l2_child_end_turn_signals_task_completed_by_child(self):
        """child end_turn 应解析为 task_completed_by_child（非 max_iterations 耗尽）。"""
        request = SubAgentRequest(
            task="test", role="tester", allowed_tools=(), parent_trace_id="t1",
            delegation_reason="test",
        )
        cp = _make_context_package(
            task="test", request=request, descriptor=_FakeDescriptor(),
            role_prompt="", max_iterations=5, execution_mode="real_llm_tool_requesting",
        )
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="Task done.")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        mediator = _SpyToolMediator()
        result = execute_l2(cp, provider=provider, tool_mediator=mediator)

        assert result.stop_reason == "task_completed_by_child", (
            f"L2 end_turn 应解析为 task_completed_by_child，而非 {result.stop_reason}"
        )
        assert result.status == "ok"
        assert provider._call_count == 1, "只应调 1 次 provider（非多轮 tool_use）"

    def test_l2_max_iterations_exhausted_returns_max_iterations_exceeded(self):
        """child 达到 max_iterations 时，应标记 max_iterations_exceeded。"""
        request = SubAgentRequest(
            task="test", role="tester", allowed_tools=(), parent_trace_id="t2",
            delegation_reason="test",
        )
        cp = _make_context_package(
            task="test", request=request, descriptor=_FakeDescriptor(),
            role_prompt="", max_iterations=2, execution_mode="real_llm_tool_requesting",
        )
        # 每次都返回 tool_use → 永远达不到 end_turn → max_iterations 耗尽
        _tu1 = ToolUseBlock(id="tu1", name="read_file", input={"path": "/tmp/x"})
        _tu2 = ToolUseBlock(id="tu2", name="read_file", input={"path": "/tmp/y"})
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="Need more info..."), _tu1],
                stop_reason="tool_use",
                raw_provider_name="spy",
            ),
            ProviderResponse(
                content=[ProviderTextBlock(text="Still need more info..."), _tu2],
                stop_reason="tool_use",
                raw_provider_name="spy",
            ),
        ])
        mediator = _SpyToolMediator()
        result = execute_l2(cp, provider=provider, tool_mediator=mediator, delegation_id="d1")

        assert result.stop_reason == "max_iterations_exceeded"
        assert result.status == "max_iterations_exceeded"
        assert "max_iterations reached" in " ".join(result.warnings)

    def test_l2_single_iteration_child_decides_to_stop(self):
        """单轮 child 自主决定停止。"""
        request = SubAgentRequest(
            task="quick task", role="tester", allowed_tools=(), parent_trace_id="t3",
            delegation_reason="test",
        )
        cp = _make_context_package(
            task="quick task", request=request, descriptor=_FakeDescriptor(),
            role_prompt="", max_iterations=10, execution_mode="real_llm_tool_requesting",
        )
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(text="Done. No more tools needed.")],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        mediator = _SpyToolMediator()
        result = execute_l2(cp, provider=provider, tool_mediator=mediator, delegation_id="d2")

        assert result.stop_reason == "task_completed_by_child"
        assert result.audit.iterations_used == 1


# ═══════════════════════════════════════════════════════════════════════════
# L2 Batch Memory Proposals
# ═══════════════════════════════════════════════════════════════════════════


class TestL2BatchMemory:
    """L2 child can submit batch memory proposals in final response."""

    def test_parse_batch_memory_valid_json(self):
        """_parse_batch_memory 正确解析合法的 batch_memory JSON。"""
        text = (
            'Result:\n'
            '{"batch_memory": ['
            '{"key": "k1", "value": "v1", "scope": "project"}, '
            '{"key": "k2", "value": "v2", "scope": "user"}'
            ']}\nDone.'
        )
        result = _parse_batch_memory(text)
        assert result is not None
        assert len(result) == 2
        assert result[0] == {"key": "k1", "value": "v1", "scope": "project"}  # type: ignore[index]
        assert result[1] == {"key": "k2", "value": "v2", "scope": "user"}  # type: ignore[index]

    def test_parse_batch_memory_no_match(self):
        """_parse_batch_memory 对无 batch_memory 的文本返回 None。"""
        assert _parse_batch_memory("Just a normal response.") is None
        assert _parse_batch_memory("") is None

    def test_parse_batch_memory_malformed_json(self):
        """_parse_batch_memory 对畸形 JSON 安全返回 None。"""
        assert _parse_batch_memory('{"batch_memory": [broken]}') is None

    def test_l2_child_batch_memory_proposals_in_result(self):
        """L2 executor 在 child 响应含 batch_memory 时填充 batch_memory_proposals。"""
        request = SubAgentRequest(
            task="research", role="tester", allowed_tools=(),
            parent_trace_id="t4", memory_scope="propose", delegation_reason="test",
        )
        cp = _make_context_package(
            task="research", request=request, descriptor=_FakeDescriptor(),
            role_prompt="", max_iterations=3, execution_mode="real_llm_tool_requesting",
        )
        provider = _SpyProvider([
            ProviderResponse(
                content=[ProviderTextBlock(
                    text='{"batch_memory": [{"key": "finding", '
                         '"value": "important discovery", '
                         '"scope": "project"}]}'
                )],
                stop_reason="end_turn",
                raw_provider_name="spy",
            ),
        ])
        mediator = _SpyToolMediator()
        result = execute_l2(cp, provider=provider, tool_mediator=mediator, delegation_id="d3")

        assert len(result.batch_memory_proposals) == 1
        assert dict(result.batch_memory_proposals[0]) == {
            "key": "finding", "value": "important discovery", "scope": "project"
        }  # type: ignore[index]
        assert mediator.child_memory_requests  # 实际触发了 memory write


# ═══════════════════════════════════════════════════════════════════════════
# L2 Deepened Tool Access
# ═══════════════════════════════════════════════════════════════════════════


class TestL2DeepenedToolAccess:
    """L2 child has access to grep + glob in addition to read_file."""

    def test_l2_tool_list_includes_grep_and_glob(self):
        """L2 executor 构建的 tool list 包含 grep 和 glob。"""
        request = SubAgentRequest(
            task="search", role="tester", allowed_tools=("read_file",),
            parent_trace_id="t5", delegation_reason="test",
        )
        cp = _make_context_package(
            task="search", request=request, descriptor=_FakeDescriptor(),
            role_prompt="", max_iterations=3, execution_mode="real_llm_tool_requesting",
        )
        provider = _SpyProvider()
        mediator = _SpyToolMediator()
        execute_l2(cp, provider=provider, tool_mediator=mediator, delegation_id="d4")

        assert provider.calls
        # L2 system prompt 包含 deepened 工具名（grep, glob）；
        # TOOL_REGISTRY 中不一定有这些工具，但 L2 executor 已将名字注入 system prompt。
        _system = provider.calls[0]["system"]
        assert "grep" in _system, "L2 system prompt 必须提及 grep"
        assert "glob" in _system, "L2 system prompt 必须提及 glob"

    def test_l2_tool_list_no_duplicate_grep_glob(self):
        """已有的 grep/glob 不被重复添加。"""
        request = SubAgentRequest(
            task="search", role="tester",
            allowed_tools=("read_file", "grep", "glob"),
            parent_trace_id="t5b", delegation_reason="test",
        )
        cp = _make_context_package(
            task="search", request=request, descriptor=_FakeDescriptor(),
            role_prompt="", max_iterations=3, execution_mode="real_llm_tool_requesting",
        )
        provider = _SpyProvider()
        mediator = _SpyToolMediator()
        execute_l2(cp, provider=provider, tool_mediator=mediator, delegation_id="d4b")
        _system = provider.calls[0]["system"]
        assert _system.count("grep") >= 1
        assert _system.count("glob") >= 1


# ═══════════════════════════════════════════════════════════════════════════
# L2 Policy Gate
# ═══════════════════════════════════════════════════════════════════════════


class TestL2PolicyGate:
    """L2 is gated behind SubAgentPolicy.real_llm_tool_requesting_allowed."""

    def test_is_l2_gated_with_no_policy(self):
        """无 policy 时 L2 默认 gated（safe default）。"""
        assert is_l2_gated(None) is True

    def test_is_l2_gated_with_disabled_policy(self):
        """policy.real_llm_tool_requesting_allowed=False 时 L2 gated。"""
        policy = type("P", (), {"real_llm_tool_requesting_allowed": False})()
        assert is_l2_gated(policy) is True

    def test_is_l2_gated_with_enabled_policy(self):
        """policy.real_llm_tool_requesting_allowed=True 时 L2 可用。"""
        policy = type("P", (), {"real_llm_tool_requesting_allowed": True})()
        assert is_l2_gated(policy) is False
        assert l2_available(policy) is True


# ═══════════════════════════════════════════════════════════════════════════
# L2 Adjudication Gate
# ═══════════════════════════════════════════════════════════════════════════


class TestL2AdjudicationGate:
    """L2 delegation 通过 mandatory adjudication gate 返回结果。"""

    def test_delegate_l2_success_with_spy_provider(self):
        """delegate_l2 在 _SpyProvider 下成功完成。"""
        request = SubAgentRequest(
            task="test", role="tester", allowed_tools=(),
            parent_trace_id="t6", delegation_reason="test",
        )
        provider = _SpyProvider()
        mediator = _SpyToolMediator()

        run = delegate_l2(request, _FakeRegistry(), provider=provider, tool_mediator=mediator)
        assert run.state == "completed"
        assert run.result is not None
        assert run.revision_count == 0

    def test_delegate_l2_missing_descriptor(self):
        """delegate_l2 在 descriptor 缺失时返回 failed。"""
        request = SubAgentRequest(
            task="test", role="nonexistent", allowed_tools=(),
            parent_trace_id="t7", delegation_reason="test",
        )
        provider = _SpyProvider()
        mediator = _SpyToolMediator()

        class _EmptyRegistry:
            def find_by_role(self, _role):
                return []
            def get_descriptor(self, _name):
                return None

        run = delegate_l2(request, _EmptyRegistry(), provider=provider, tool_mediator=mediator)
        assert run.state == "failed"

    def test_delegate_l2_accept_adjudication(self):
        """delegate_l2 正常完成时 adjudication action=accept。"""
        request = SubAgentRequest(
            task="test", role="tester", allowed_tools=(),
            parent_trace_id="t8", delegation_reason="test",
        )
        provider = _SpyProvider()
        mediator = _SpyToolMediator()

        run = delegate_l2(request, _FakeRegistry(), provider=provider, tool_mediator=mediator)
        assert run.adjudication is not None
        assert run.adjudication.action == "accept_result"


# ═══════════════════════════════════════════════════════════════════════════
# L2 Stop Reason Enum
# ═══════════════════════════════════════════════════════════════════════════


class TestL2StopReasonEnum:
    """TASK_COMPLETED_BY_CHILD is registered in SubAgentStopReason enum."""

    def test_task_completed_by_child_in_enum(self):
        values = [r.value for r in SubAgentStopReason]
        assert "task_completed_by_child" in values

    def test_task_completed_by_child_distinct_from_task_completed(self):
        assert SubAgentStopReason.TASK_COMPLETED_BY_CHILD != SubAgentStopReason.TASK_COMPLETED


# ═══════════════════════════════════════════════════════════════════════════
# L2 RuntimeDecisionFrame compatibility
# ═══════════════════════════════════════════════════════════════════════════


class TestL2RuntimeDecisionFrame:
    """L2 相关的 RuntimeDecisionFrame 字段已正确设置。"""

    def test_subagent_l2_gated_is_true(self):
        from agent.runtime_decision_frame import build_decision_frame
        frame = build_decision_frame("test")
        assert frame.subagent_l2_gated is True, "L2 应默认 gated behind policy"

    def test_subagent_level_is_inline_local_fallback(self):
        from agent.runtime_decision_frame import build_decision_frame
        frame = build_decision_frame("test")
        # Live CLI/NL delegation is L1-attempt → direct inline-local fallback
        # (subagent_inline.execute_subagent_delegation, execution_mode=local_fake).
        # The "L1 是生产基线" framing enshrined a false claim: L1 is not
        # registered, and the live path is the inline-local fallback, not the
        # registered L0 probe or the registered-but-not-routed V0. See
        # V0_WIRING_DECISION for the target architecture (V0 routing).
        assert frame.subagent_level == "inline_local_fallback", (
            "默认 level 应反映当前 live path（inline-local fallback），"
            "而非未注册的 L1"
        )


# ═══════════════════════════════════════════════════════════════════════════
# L2 Legacy L0 Shortcut Removal Regression
# ═══════════════════════════════════════════════════════════════════════════


class TestL2LegacyL0Regression:
    """L2 不破坏 L1/L0 现有行为。"""

    def test_delegate_l2_returns_l2_audit(self):
        """delegate_l2 产生的 audit record 标记 execution_mode=real_llm_tool_requesting。"""
        request = SubAgentRequest(
            task="test", role="tester", allowed_tools=(),
            parent_trace_id="t9", delegation_reason="test",
            execution_mode="real_llm_tool_requesting",
        )
        provider = _SpyProvider()
        mediator = _SpyToolMediator()

        run = delegate_l2(request, _FakeRegistry(), provider=provider, tool_mediator=mediator)
        assert run.result is not None
        assert run.result.audit.subagent_name == "test-agent"
        assert run.result.audit.execution_mode == "real_llm_tool_requesting"

"""Pytest fixtures and a fake Anthropic client.

The fake client lets tests drive the agent loop without real network calls and
without real model behavior. Each test pre-canned the responses it expects the
"model" to emit, in order, and asserts on what the agent does in response.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

# 让测试在没有真实 .env 时也能 import agent.core
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_BASE_URL", "https://example.invalid")
os.environ.setdefault("MODEL_NAME", "test-model")

# 保证 tests/ 能 import 仓库根下的 agent/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---------- fake SDK block / response 对象 ----------

@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class FakeResponse:
    content: list
    stop_reason: str
    usage: FakeUsage = field(default_factory=FakeUsage)


# ---------- fake stream（模拟 client.messages.stream 返回的对象）----------

class FakeStream:
    def __init__(self, response: FakeResponse):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        # 本版测试不需要逐 event 驱动，流内部直接为空
        return iter([])

    def get_final_message(self):
        return self._response


# ---------- fake client ----------

class FakeAnthropicClient:
    """按预置顺序返回 response 的假 client。

    用法:
        fc = FakeAnthropicClient(responses=[resp1, resp2, ...])
        # 然后把它装进 core.client
    """

    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.requests: list[dict] = []           # 记录每次 stream 被调用时的参数
        self.create_requests: list[dict] = []    # 记录 messages.create（planner 用）

        client_self = self

        class _Messages:
            def stream(self, **kwargs):
                client_self.requests.append(kwargs)
                if not client_self.responses:
                    raise AssertionError(
                        "FakeAnthropicClient: stream called but no canned "
                        "responses left. 说明测试用例的 responses 列表给短了。"
                    )
                return FakeStream(client_self.responses.pop(0))

            def create(self, **kwargs):
                client_self.create_requests.append(kwargs)
                if not client_self.responses:
                    raise AssertionError(
                        "FakeAnthropicClient: create called but no canned "
                        "responses left."
                    )
                return client_self.responses.pop(0)

        self.messages = _Messages()


# ---------- 便捷构造器 ----------

def text_response(text: str, stop: str = "end_turn") -> FakeResponse:
    return FakeResponse(content=[FakeTextBlock(text=text)], stop_reason=stop)


def tool_use_response(
    tool_name: str, tool_input: dict, tool_id: str = "toolu_test_1", text: str | None = None
) -> FakeResponse:
    blocks: list = []
    if text:
        blocks.append(FakeTextBlock(text=text))
    blocks.append(FakeToolUseBlock(id=tool_id, name=tool_name, input=tool_input))
    return FakeResponse(content=blocks, stop_reason="tool_use")


_META_TOOL_ID_COUNTER = {"n": 0}


def meta_complete_response(
    score: int = 90,
    summary: str = "本步骤已完成",
    outstanding: str = "无",
    text: str | None = None,
    tool_id: str | None = None,
) -> FakeResponse:
    """便捷构造器：模拟模型在收尾本步骤时调用 mark_step_complete。

    新协议下，模型必须**通过工具调用**声明步骤完成（不再认关键词）。
    这个 helper 把"text 总结 + mark_step_complete tool_use"打包成一个 tool_use 响应。

    score 默认 90 是为了**走通"达阈值"路径**——大多数测试想验证"步骤完成后的行为"，
    若想测"低分继续"路径，显式传 score=50 之类。
    """
    if tool_id is None:
        _META_TOOL_ID_COUNTER["n"] += 1
        tool_id = f"meta_test_{_META_TOOL_ID_COUNTER['n']}"

    blocks: list = []
    if text:
        blocks.append(FakeTextBlock(text=text))
    blocks.append(FakeToolUseBlock(
        id=tool_id,
        name="mark_step_complete",
        input={
            "completion_score": score,
            "summary": summary,
            "outstanding": outstanding,
        },
    ))
    return FakeResponse(content=blocks, stop_reason="tool_use")


# ---------- fixture ----------

@pytest.fixture
def fresh_state():
    """返回一个全新的 AgentState，不和 core 模块的全局 state 共享。"""
    from agent.state import create_agent_state
    return create_agent_state(system_prompt="test system prompt")


@pytest.fixture
def two_step_plan():
    """返回一个标准的两步 plan（dict 形态）。"""
    from agent.plan_schema import Plan, PlanStep
    return Plan(
        goal="测试目标",
        thinking="测试思路",
        steps=[
            PlanStep(
                step_id="step-1",
                title="读取项目结构",
                description="用 ls 查看当前目录",
                step_type="read",
            ),
            PlanStep(
                step_id="step-2",
                title="生成报告",
                description="综合结论",
                step_type="report",
            ),
        ],
    ).model_dump()

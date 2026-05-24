"""Fake/deterministic ModelProvider for Phase 1 E2E testing.

中文学习边界：
FakeProvider 是 Phase 1 专用确定性 provider，实现 ModelProvider 协议。
它不读 .env、不调用外部 API、不执行工具副作用。目的是让 core.chat() →
run_main_loop() → call_model() 全链路可走通，从而证明 RuntimeAction 确实
由真实 core loop 触发，而非 dogfood harness 直接调用 dispatcher。

为什么需要 FakeProvider：
- core.chat() 依赖 provider 调用模型，没有 provider 则 call_model() fail closed
- 真实 LLM 在 Phase 1 被禁止（不读 .env、不调外部 API）
- FakeProvider 让 runtime loop 全链路可运行，同时保持 100% 确定性

WP3 扩展：Demo tool_use 响应
- 当用户输入匹配 demo prompt（如 "make a demo note"）时，FakeProvider 返回
  ToolUseBlock（demo.write_demo_note），经 Tool Pipeline（TOOL_GATE→TOOL_INVOKE
  →TOOL_RESULT）走完完整的 unified runtime flow
- 工具写入限定在 workspace/demo/ 受控目录
- 不新增 RuntimeActionType / handler / branch point

不对什么负责：
- 不做真实 LLM 推理
- 不做真实工具调用
- 不做多工具 chaining
- 不模拟 provider error/latency/retry（那是 Phase 2+ 的职责）
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from agent.provider.protocol import ProviderResponse, ProviderTextBlock, ToolUseBlock
from agent.provider.streaming import ProviderStreamEvent


def _default_response_fn(messages: list[dict[str, Any]]) -> str:
    """默认确定性响应：返回最后一条 user message 的回显。"""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                return f"已收到你的消息：「{content[:80]}」"
    return "已收到你的消息。"


# Demo tool_use 触发短语集合。匹配时走 Tool Pipeline 完整闭环。
_DEMO_TOOL_TRIGGERS: frozenset[str] = frozenset({
    "make a demo note",
    "create a demo note",
    "write a demo note",
    "帮我创建一个 demo note",
    "帮我写一个 demo note",
    "生成一个 demo note",
    "make demo note",
    "create demo note",
    "写一个 demo note",
    "创建 demo note",
})


def _demo_workspace() -> Path:
    """返回受控 demo workspace 路径（复用 agent/local_demo.py 的约束）。"""
    from datetime import datetime, timezone
    from agent.local_demo import _project_root, DEMO_WORKSPACE_SUBDIR

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workspace = _project_root() / Path(*DEMO_WORKSPACE_SUBDIR) / stamp
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _build_demo_tool_block() -> ToolUseBlock:
    """构造 demo.write_demo_note 的 ToolUseBlock。"""
    import uuid

    workspace = _demo_workspace()
    note_path = workspace / "note.md"
    demo_id = f"demo-{uuid.uuid4().hex[:12]}"
    return ToolUseBlock(
        id=f"toolu_{demo_id}",
        name="demo.write_demo_note",
        input={
            "path": str(note_path),
            "content": (
                "# Demo Note (via core.chat + Tool Pipeline)\n"
                f"run_id: {demo_id}\n"
                "provider: fake\n"
                "path: core.chat() → FakeProvider → Tool Pipeline → demo.write_demo_note\n"
            ),
        },
    )


def _matches_demo_tool_trigger(messages: list[dict[str, Any]]) -> bool:
    """检查最后一条 user message 是否匹配 demo tool 触发短语。"""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                normalized = content.strip().lower()
                return normalized in _DEMO_TOOL_TRIGGERS
    return False


class FakeProvider:
    """确定性 fake provider，实现 ModelProvider 协议。

    用法：
        provider = FakeProvider()
        response = provider.create(system="...", messages=[...], tools=[])
        # response.stop_reason == "end_turn"
        # response.content[0].text == "已收到你的消息：「你好」"

    也支持自定义响应函数：
        provider = FakeProvider(response_fn=lambda msgs: "自定义回复")

    WP3 demo tool_use：当用户消息匹配 _DEMO_TOOL_TRIGGERS 时，
    create() 返回 ToolUseBlock（demo.write_demo_note），经 Tool Pipeline
    走完完整 unified runtime flow。
    """

    provider_type = "fake"
    supports_tools = False
    supports_streaming = False  # create() 走全路径（text + tool_use），streaming 协议不支持 tool_use blocks

    def __init__(
        self,
        *,
        response_fn: Callable[[list[dict[str, Any]]], str] | None = None,
        stop_reason: str = "end_turn",
    ) -> None:
        self._response_fn = response_fn or _default_response_fn
        self._stop_reason = stop_reason

    def _wants_tool_use(self, messages: list[dict[str, Any]]) -> bool:
        """本次调用是否应返回 tool_use 响应。

        只有用户输入精确匹配 demo tool 触发短语时才返回 tool_use。
        不能把通用输入误解为 tool_use 意图。
        """
        return _matches_demo_tool_trigger(messages)

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        """非流式创建响应。匹配 demo prompt 时返回 tool_use 响应。"""
        if self._wants_tool_use(messages):
            text = self._response_fn(messages)
            return ProviderResponse(
                content=[
                    ProviderTextBlock(text=f"{text}\n(触发 demo tool，将通过 Tool Pipeline 执行)"),
                    _build_demo_tool_block(),
                ],
                stop_reason="tool_use",
                raw_provider_name="fake",
            )
        text = self._response_fn(messages)
        return ProviderResponse(
            content=[ProviderTextBlock(text=text)],
            stop_reason=self._stop_reason,
            raw_provider_name="fake",
        )

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[ProviderStreamEvent]:
        """流式响应：把文本拆成 delta 事件，以 final 事件结束。

        注意：tool_use 响应通过 create() 路径返回（supports_streaming 动态
        覆写），stream() 路径不处理 tool_use。
        """
        text = self._response_fn(messages)
        seq = 0
        chunk_size = 3
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            seq += 1
            yield ProviderStreamEvent.delta(sequence=seq, text_delta=chunk)
        seq += 1
        yield ProviderStreamEvent.final(sequence=seq)

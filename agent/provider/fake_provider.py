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

WP3 扩展：Demo tool_use 响应 → 本轮 WP1-WP2 泛化
- 原来使用硬编码 _DEMO_TOOL_TRIGGERS 精确字符串匹配，只支持一个工具
- 改用 FakeToolDecisionPolicy：基于工具名称、描述与用户意图的 rule-based 匹配
- 支持所有已注册的 safe demo tools（demo.write_demo_note, demo.echo_task_summary）
- tool_use intent 经 Tool Pipeline 走完整 unified runtime flow，FakeProvider 不执行工具

架构边界（为什么 fake provider 不执行工具）：
- FakeProvider 只输出 ToolUseBlock（tool_use intent），不直接调用 tool func
- 真正工具执行路径：core.chat → loop.py → handle_tool_use_response → ToolExecutor → tool func
- 如果 FakeProvider 直接调用 tool func，会绕过 confirmation、audit、trace、checkpoint
- 这就是"fake 可以有，fake path 不能有"的核心含义

为什么不是 fake/real 双 runtime：
- FakeProvider 和 RealProvider 都实现 ModelProvider Protocol
- 两者都通过 call_model() → create()/stream() 进入同一个 core.chat/loop.py
- 区别只在 provider adapter 内部：fake 是 deterministic rules，real 是 LLM API
- 从 runtime loop 的视角看，两者都是"模型返回了 stop_reason + content blocks"
- 调度、确认、审计、trace、checkpoint 全部共享

不对什么负责：
- 不做真实 LLM 推理
- 不做真实工具调用
- 不做多工具 chaining
- 不模拟 provider error/latency/retry（那是 Phase 2+ 的职责）

⛔ FROZEN (2026-05-25): FakeProvider 增强冻结。
   - 当前定位：deterministic test fixture / debug provider / contract coverage
   - 允许：固定响应、deterministic tool_use fixture、provider swap contract 验证
   - 禁止：继续增强为 fake planner / fake reasoning engine / fake user context model
   - 真实智能必须通过 real provider dogfood 验证，不可通过 fake provider 模拟
   参见: docs/audit/global-agent-capability-architecture-audit-2026-05-25.md F19
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


# ═══════════════════════════════════════════════════════════
# FakeToolDecisionPolicy: rule-based deterministic tool matching
# ═══════════════════════════════════════════════════════════


def _normalize(text: str) -> str:
    """归一化：去除首尾空白、转小写、压缩连续空格。"""
    return " ".join(text.strip().lower().split())


def _tool_name_tokens(tool_name: str) -> set[str]:
    """拆分工具名称中的有意义 token（用于模糊匹配）。

    例如 "demo.write_demo_note" → {"demo", "write", "note"}
    """
    return set(tool_name.replace(".", "_").split("_")) - {"demo"}


def _tool_desc_keywords(description: str) -> set[str]:
    """提取工具描述中可作为意图关键词的中文/英文短语。

    规则：
    - 英文：提取 3+ 字母的单词，排除停用词
    - 中文：提取 2-4 字的连续汉字片段
    - 返回用于匹配的关键词集合
    """
    import re

    keywords: set[str] = set()
    normalized = _normalize(description)

    # 英文词：3 字母以上
    eng_stop = {
        "the", "and", "for", "not", "are", "can", "all", "has", "was",
        "its", "that", "with", "from", "this", "have", "been", "they",
        "will", "would", "could", "should", "does", "into",
    }
    eng_words = re.findall(r"[a-z]{3,}", normalized)
    keywords.update(w for w in eng_words if w not in eng_stop)

    # 中文片段：取 2-4 字连续汉字
    cn_chars = re.findall(r"[一-鿿]+", normalized)
    for seg in cn_chars:
        for size in (4, 3, 2):
            for i in range(len(seg) - size + 1):
                keywords.add(seg[i : i + size])

    return keywords


# 旧版精确匹配触发词（兼容性保留，但已不作为主决策路径）。
# 这些短语在新架构下由 tool name/description 匹配接管。
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


def _resolve_tool_use(
    user_message: str,
    tools: list[dict[str, Any]],
) -> ToolUseBlock | None:
    """基于用户消息和可用工具描述做 deterministic tool 匹配。

    输入：
    - user_message: 归一化前的用户纯文本消息（由 FakeProvider.create() 提取）
    - tools: create() 收到的工具描述列表，每条含 name/description/parameters

    输出：
    - ToolUseBlock 如果匹配到一个工具
    - None 如果用户意图不匹配任何可用工具

    匹配策略（优先级从高到低）：
    1. 工具全名精确出现在用户消息中 → 直接命中
    2. 工具名称的 token 精确命中用户消息 → 高置信度
    3. 工具描述的关键词与用户消息重叠 → 中等置信度
    4. 旧版 _DEMO_TOOL_TRIGGERS 精确匹配 → 兼容性回退
    5. 无匹配 → 返回 None

    全部 deterministic，不涉及随机性、模型推理或外部调用。

    为什么只返回一个 tool_use 而不是多个：
    - FakeProvider 是单步 deterministic adapter，不模拟多步 planner
    - 多工具 chaining 需要真实 LLM planning，不在 fake provider 能力范围
    - 本函数目标：验证 unified runtime flow 可以在确定性 fake 场景下承载 tool_use

    为什么参数值使用安全默认值：
    - 真正的参数解析需要 LLM 理解用户意图，fake provider 不做这个
    - 对于 zero-arg 工具，传入 {} 即可
    - 对于有参数的工具，使用安全默认值，真正解析由 future real provider 负责
    """
    import uuid

    if not tools:
        return None

    msg = _normalize(user_message)
    if not msg:
        return None

    # 为每工具预计算匹配得分
    candidates: list[tuple[int, str, dict[str, Any]]] = []

    for tool in tools:
        name = tool.get("name", "")
        desc = tool.get("description", "")
        if not name or not desc:
            continue

        score = 0
        name_lower = name.lower()
        # 策略 1：全名精确出现（最高优先级）
        if name_lower in msg:
            score = 100
        # 策略 2：名称 token 命中
        else:
            tokens = _tool_name_tokens(name_lower)
            hit_tokens = tokens & set(msg.split())
            if hit_tokens:
                score = max(score, 60 + len(hit_tokens) * 10)

        # 策略 3：描述关键词命中
        desc_kw = _tool_desc_keywords(desc)
        msg_kw = set(_tool_desc_keywords(msg))
        kw_overlap = desc_kw & msg_kw
        if kw_overlap:
            score = max(score, 30 + len(kw_overlap) * 5)

        if score > 0:
            candidates.append((score, name, tool))

    # 按得分降序排列
    candidates.sort(key=lambda x: x[0], reverse=True)

    if candidates:
        score, name, tool = candidates[0]
        if score >= 30:  # 最低门槛：至少描述关键词有重叠
            tool_id = f"toolu_fake_{uuid.uuid4().hex[:12]}"
            return ToolUseBlock(
                id=tool_id,
                name=name,
                input=_default_tool_input(name, tool.get("parameters", {})),
            )

    # 策略 4：旧版兼容性回退
    if msg in _DEMO_TOOL_TRIGGERS:
        return _legacy_demo_note_block()

    return None


def _default_tool_input(tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """为匹配的工具生成安全的默认输入参数。

    中文学习说明：FakeProvider 不做真实参数解析（那是 LLM 的能力）。
    这里使用安全默认值——如果工具参数可选，这个默认值是合法且安全的。
    """
    import uuid
    from datetime import datetime, timezone

    # demo.echo_task_summary: 无参数
    if tool_name == "demo.echo_task_summary":
        return {}

    # demo.write_demo_note: 全部可选参数，使用安全默认值
    if tool_name == "demo.write_demo_note":
        from agent.local_demo import _project_root, DEMO_WORKSPACE_SUBDIR

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        workspace = _project_root() / Path(*DEMO_WORKSPACE_SUBDIR) / stamp
        workspace.mkdir(parents=True, exist_ok=True)
        note_path = workspace / "note.md"
        demo_id = uuid.uuid4().hex[:12]
        return {
            "path": str(note_path),
            "content": (
                "# Demo Note (via core.chat + Tool Pipeline)\n"
                f"run_id: {demo_id}\n"
                "provider: fake\n"
                "path: core.chat() → FakeProvider → Tool Pipeline → demo.write_demo_note\n"
            ),
        }

    # 通用回退：如果参数全部可选，传空 dict
    required = parameters.get("required", [])
    if not required:
        return {}

    # 有必填参数但目前无法解析 → 返回默认值字典（用参数名作 key）
    return {k: f"<fake_default_{k}>" for k in required}


def _legacy_demo_note_block() -> ToolUseBlock:
    """旧版 _DEMO_TOOL_TRIGGERS 兼容性回退：构造 demo.write_demo_note block。"""
    import uuid
    from datetime import datetime, timezone
    from agent.local_demo import _project_root, DEMO_WORKSPACE_SUBDIR

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workspace = _project_root() / Path(*DEMO_WORKSPACE_SUBDIR) / stamp
    workspace.mkdir(parents=True, exist_ok=True)
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


# ═══════════════════════════════════════════════════════════
# FakeProvider
# ═══════════════════════════════════════════════════════════


class FakeProvider:
    """确定性 fake provider，实现 ModelProvider 协议。

    用法：
        provider = FakeProvider()
        response = provider.create(system="...", messages=[...], tools=[])
        # response.stop_reason == "end_turn"
        # response.content[0].text == "已收到你的消息：「你好」"

    也支持自定义响应函数：
        provider = FakeProvider(response_fn=lambda msgs: "自定义回复")

    tool_use 决策：
    - 使用 FakeToolDecisionPolicy 基于工具名称、描述与用户消息做 rule-based 匹配
    - 匹配时返回 ToolUseBlock（tool_use intent），经 Tool Pipeline 走完整 unified runtime flow
    - 未匹配时返回普通文本响应（end_turn）
    - FakeProvider 只输出 ToolUseBlock，不执行工具——真正执行在 ToolExecutor 中

    FakeProvider 是 deterministic test/debug provider adapter，不是产品智能本身。
    它的 tool_use decision 是本地可复现的 provider adapter 行为，用于验证 unified
    runtime flow、tool pipeline 和用户可见结果，不代表真实 LLM tool-calling 能力。
    """

    provider_type = "fake"
    supports_tools = False
    # Phase 2 WP-D：stream() 已支持 text deltas + tool_request 事件，
    # call_model() 在检测到 tool_request 时自动回退 create() 获取 ToolUseBlock。
    supports_streaming = True

    def __init__(
        self,
        *,
        response_fn: Callable[[list[dict[str, Any]]], str] | None = None,
        stop_reason: str = "end_turn",
    ) -> None:
        self._response_fn = response_fn or _default_response_fn
        self._stop_reason = stop_reason

    def _resolve_tool_use(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ToolUseBlock | None:
        """根据消息和可用工具做 deterministic tool_use 决策。

        调用 _resolve_tool_use() 模块级函数完成匹配。FakeProvider 不直接执行
        工具——返回的 ToolUseBlock 由 core.chat/loop.py 的 handle_tool_use_response
        消费，经 ToolExecutor 真正执行。

        为什么不是"直接调 tool func"：
        - 如果 FakeProvider._resolve_tool_use 直接 import demo_echo_task_summary
          然后调用它，tool 执行会绕过：
          - Tool gate（confirmation 检查）
          - Tool audit log
          - Tool trace event
          - Tool result checkpoint
        - 这就是"fake path"——看起来像 unified runtime，实际绕开了所有 governance
        - 正确做法：FakeProvider 只输出 ToolUseBlock，loop.py 的现有 handler
          负责后续所有 governance 步骤
        """
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    return _resolve_tool_use(content, tools)
        return None

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
        """非流式创建响应。

        核心流程：
        1. _resolve_tool_use() 根据用户消息 + 可用工具描述做 rule-based 匹配
        2. 匹配成功 → ProviderResponse 包含 ProviderTextBlock + ToolUseBlock
           stop_reason="tool_use"，进入 loop.py 的 handle_tool_use_response
        3. 匹配失败 → 普通文本响应，stop_reason="end_turn"
        """
        tool_block = self._resolve_tool_use(messages, tools)
        if tool_block is not None:
            text = self._response_fn(messages)
            return ProviderResponse(
                content=[
                    ProviderTextBlock(text=f"{text}\n(触发 {tool_block.name}，将通过 Tool Pipeline 执行)"),
                    tool_block,
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
        """流式响应（debug/fake deterministic chunking）。

        这不是真实 provider streaming——FakeProvider 已持有完整响应文本，
        只是按 chunk_size 分片递送，模拟 streaming UX 的逐字输出感。
        用户主体验应是 progress/event UX（工具/子代理/记忆进度事件），
        而非这里的 fake token chunking。

        call_model() 在检测到 tool_request 事件后自动回退 create() 获取完整
        ToolUseBlock。这样 streaming 路径负责用户可见的逐字输出体验，
        create() 路径负责 Tool Pipeline 所需的完整 ToolUseBlock。

        为什么不能只靠 stream() 产出 ToolUseBlock：
        - ProviderStreamEvent 不携带 tool_name/tool_input
        - collect_stream_response() 只聚合 text_delta，不构造 ToolUseBlock
        - tool_request 事件是信号：告诉 call_model()「需要切回 create()」
        """
        text = self._response_fn(messages)
        tool_block = self._resolve_tool_use(messages, tools)

        seq = 0
        # fake/demo chunking：12 字一组，比旧 3 字更可读，但仍只是模拟 streaming
        chunk_size = 12
        for i in range(0, len(text), chunk_size):
            chunk = text[i : i + chunk_size]
            seq += 1
            yield ProviderStreamEvent.delta(sequence=seq, text_delta=chunk)

        if tool_block is not None:
            seq += 1
            yield ProviderStreamEvent.tool_request(sequence=seq)

        seq += 1
        yield ProviderStreamEvent.final(sequence=seq)

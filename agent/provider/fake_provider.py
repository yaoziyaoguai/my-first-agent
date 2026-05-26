"""Fake/deterministic ModelProvider — Scripted Scenario Test Double.

契约文档：docs/design/fake-provider-scripted-scenario-contract.md

FakeProvider 是 deterministic ModelProvider test double。它实现 ModelProvider
协议（create()/stream()），输出预编排的固定响应，唯一目的是证明 unified runtime
flow（core.chat → loop.py → call_model → Tool Pipeline / Memory / SubAgent
branch points）在模型返回结构化输出时功能正确。

FakeProvider 和 RealProvider 共享：
- 同一 ModelProvider 协议（create()/stream()）
- 同一 unified runtime path（core.chat → run_main_loop → call_model）
- 同一 Tool Pipeline、Memory hooks、SubAgent routing、summary/evidence 路径

区别仅在如何生成 ProviderResponse：FakeProvider 使用确定性编排输出；
RealProvider 调用外部 LLM API。

FakeProvider 不是：
- 中文 NLU 系统
- Planner
- 意图识别器
- 产品能力 demo
- 真实语义 eval 的替代品

Scripted Scenario 匹配规则（仅以下合法）：
1. Exact match — 用户消息与已知触发短语精确匹配
2. Tool name literal — 工具名原文出现在用户消息中
3. Structured prefix match — "/tool:" 或 "/scenario:" 前缀（Phase 2 预留）

已废弃策略：
- Strategy 2 (name token match) — DEPRECATED
- Strategy 3 (description keyword n-gram) — DEPRECATED
- _tool_desc_keywords() Chinese n-gram 提取 — DEPRECATED
- Chinese stop-word filtering — DEPRECATED

不对什么负责：
- 不做真实 LLM 推理
- 不做真实工具调用
- 不做多工具 chaining
- 不模拟 provider error/latency/retry

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
    """[DEPRECATED] 提取工具描述中的中文/英文关键词用于 n-gram 模糊匹配。

    此函数是 strategy 3（描述关键词匹配）的核心引擎。按 FakeProvider Scripted
    Scenario Contract §3.5，strategy 3 已废弃——FakeProvider 不得通过中文 n-gram
    提取和重叠评分来猜测用户自然语言意图。

    保留原因：旧测试兼容性。移除条件：所有 dogfood 和集成测试迁移至 scripted scenarios。
    预计 Sunset: v0.5+

    规则（历史记录）：
    - 英文：提取 3+ 字母的单词，排除停用词
    - 中文：提取 2-4 字的连续汉字片段，排除高频泛化停用词
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

    # 中文片段：取 2-4 字连续汉字，排除高频泛化停用词
    cn_chars = re.findall(r"[一-鿿]+", normalized)
    cn_stop_substrings = {
        "不要",  # 否定 — 用户说"不要调用"与工具描述中"调用"语义相反
        "调用",  # boilerplate — 几乎所有中文工具描述都含"调用此工具"
    }
    for seg in cn_chars:
        for size in (4, 3, 2):
            for i in range(len(seg) - size + 1):
                ngram = seg[i : i + size]
                if any(sw in ngram for sw in cn_stop_substrings):
                    continue
                keywords.add(ngram)

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
    """基于用户消息和可用工具做 deterministic tool 匹配。

    按 FakeProvider Scripted Scenario Contract §3.3，仅以下策略合法：
    - 策略 1（全名精确命中）：tool name 原文出现在用户消息中 → score=100
    - 策略 4（legacy exact trigger）：消息精确命中 _DEMO_TOOL_TRIGGERS

    以下策略已废弃（§3.5）：
    - 策略 2（名称 token 匹配）— DEPRECATED，依赖 str.split() tokenization
    - 策略 3（描述关键词 n-gram 重叠）— DEPRECATED，构成伪中文 NLU

    废弃策略暂时保留作为兼容性回退，待所有测试迁移至 scripted scenarios 后移除。
    Sunset: v0.5+

    全部 deterministic，不涉及随机性、模型推理或外部调用。
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
        # 策略 1：全名精确出现（最高优先级，合法 scripted scenario）
        if name_lower in msg:
            score = 100
        # 策略 2：名称 token 命中 — DEPRECATED (§3.5)，依赖 str.split() tokenization
        # 保留仅作兼容性回退，Sunset v0.5+
        else:
            tokens = _tool_name_tokens(name_lower)
            hit_tokens = tokens & set(msg.split())
            if hit_tokens:
                score = max(score, 60 + len(hit_tokens) * 10)

        # 策略 3：描述关键词命中 — DEPRECATED (§3.5)，构成伪中文 NLU
        # 保留仅作兼容性回退，Sunset v0.5+
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
        # 最低门槛 60：策略 1（score=100）和策略 4（legacy exact match）直接通过。
        # 策略 2（name token）最低 70+（60+10），策略 3（n-gram）需 6+ 关键词重叠（30+30）。
        # 历史：30→40 (6e5f287)，40→60 (255c341)。
        # 按 Scripted Scenario Contract §3.5，策略 2/3 已废弃，threshold 在它们
        # 移除后将不再需要防御性调高。
        if score >= 60:
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
        from agent.local_demo import DEMO_WORKSPACE_SUBDIR, _project_root

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        workspace = _project_root() / Path(*DEMO_WORKSPACE_SUBDIR) / stamp
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

    from agent.local_demo import DEMO_WORKSPACE_SUBDIR, _project_root

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workspace = _project_root() / Path(*DEMO_WORKSPACE_SUBDIR) / stamp
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
    """Deterministic ModelProvider test double — Scripted Scenario Contract.

    用法：
        provider = FakeProvider()
        response = provider.create(system="...", messages=[...], tools=[])
        # response.stop_reason == "end_turn"
        # response.content[0].text == "已收到你的消息：「你好」"

    也支持自定义响应函数：
        provider = FakeProvider(response_fn=lambda msgs: "自定义回复")

    tool_use 决策：
    - 仅合法策略：全名精确命中（strategy 1）+ 旧版精确触发短语（strategy 4）
    - Strategy 2（名称 token）和 strategy 3（描述 n-gram）已废弃（§3.5）
    - 匹配时返回 ToolUseBlock，经 Tool Pipeline 走完整 unified runtime flow
    - 未匹配时返回普通文本响应（end_turn）
    - FakeProvider 只输出 ToolUseBlock，不执行工具

    详见 docs/design/fake-provider-scripted-scenario-contract.md
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
        """按 Scripted Scenario Contract §3.3 匹配 tool_use。

        仅使用合法策略（exact match / legacy exact trigger）。
        废弃策略（name token / n-gram）暂保留兼容，Sunset v0.5+。

        FakeProvider 只输出 ToolUseBlock，真正执行在 ToolExecutor 中。
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
                    ProviderTextBlock(
                    text=f"{text}\n(触发 {tool_block.name}，将通过 Tool Pipeline 执行)"
                ),
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

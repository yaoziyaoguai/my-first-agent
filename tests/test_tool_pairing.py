"""tool_use ↔ tool_result 配对契约的单测。

这类 bug 最难手动调——它只会在"某条 assistant 里有 tool_use、但下一轮 messages
里找不到对应 tool_result" 时才在 API 那边炸。单测可以直接检查 messages
结构，不用跑真实网络。
"""

from __future__ import annotations

from agent.conversation_events import has_tool_result
from agent.memory import _find_safe_split_index
from agent.response_handlers import (
    _serialize_assistant_content,
    _fill_placeholder_results,
)
from tests.conftest import FakeTextBlock, FakeToolUseBlock


# ---------- _serialize_assistant_content ----------

def test_serialize_keeps_tool_use_block():
    """持久化 assistant 消息时必须保留 tool_use 块（含 id/name/input）。

    回归防护：原实现只保留 text，把 tool_use 丢了——下一轮 tool_result
    找不到对应 tool_use_id，API 直接 400。
    """
    content = [
        FakeTextBlock(text="我来读文件"),
        FakeToolUseBlock(
            id="toolu_X",
            name="read_file",
            input={"path": "config.py"},
        ),
    ]
    serialized = _serialize_assistant_content(content)

    types = [b["type"] for b in serialized]
    assert "tool_use" in types, "必须保留 tool_use 块"

    tool_use_block = next(b for b in serialized if b["type"] == "tool_use")
    assert tool_use_block["id"] == "toolu_X"
    assert tool_use_block["name"] == "read_file"
    assert tool_use_block["input"] == {"path": "config.py"}


def test_serialize_filters_empty_text():
    """空字符串 text 块应该被过滤掉，避免 messages 里出现无意义条目。"""
    content = [FakeTextBlock(text=""), FakeTextBlock(text="真实内容")]
    serialized = _serialize_assistant_content(content)
    assert len(serialized) == 1
    assert serialized[0]["text"] == "真实内容"


# ---------- _fill_placeholder_results ----------

def test_fill_placeholder_covers_unpaired_tool_uses():
    """多 tool_use 中有阻断时，剩余块必须被补上占位 tool_result。

    这是半开事务保护：assistant 里的每个 tool_use 都需要配对的 tool_result，
    否则下一次 API 调用会 400。
    """
    messages: list = []
    blocks = [
        FakeToolUseBlock(id="T1", name="run_shell", input={"command": "ls"}),
        FakeToolUseBlock(id="T2", name="run_shell", input={"command": "pwd"}),
        FakeToolUseBlock(id="T3", name="run_shell", input={"command": "whoami"}),
    ]

    _fill_placeholder_results(messages, blocks, reason="测试用占位")

    for b in blocks:
        assert has_tool_result(messages, b.id), f"tool_use {b.id} 应有占位 tool_result"


def test_fill_placeholder_skips_already_paired():
    """已经配对过的 tool_use，不应该再写占位（避免重复）。"""
    from agent.conversation_events import append_tool_result

    messages: list = []
    append_tool_result(messages, "T1", "真实结果")

    blocks = [
        FakeToolUseBlock(id="T1", name="run_shell", input={"command": "ls"}),
        FakeToolUseBlock(id="T2", name="run_shell", input={"command": "pwd"}),
    ]
    _fill_placeholder_results(messages, blocks, reason="测试用占位")

    # T1 只应该有一条（原本的真实结果），不应该被占位覆盖
    t1_results = [
        b for m in messages
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("tool_use_id") == "T1"
    ]
    assert len(t1_results) == 1
    assert t1_results[0]["content"] == "真实结果"


# ---------- _find_safe_split_index ----------

def test_safe_split_does_not_cut_tool_pair():
    """压缩切点不能切在 tool_use / tool_result 中间。

    回归防护：原 compress_history 粗暴地 messages[-N:] 切，如果最后 N 条里
    有孤悬 tool_result（它对应的 tool_use 在 old 那一半），下次 API 调用会 400。
    """
    messages = [
        {"role": "user", "content": "早期 1"},
        {"role": "user", "content": "早期 2"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "T1", "name": "read_file", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T1", "content": "结果"},
        ]},
        {"role": "user", "content": "最近 1"},
    ]
    # preferred_recent=2 会让初始 split 落在 tool_result 上，把 tool_use 切出去
    split = _find_safe_split_index(messages, preferred_recent=2)
    # 切点应当向前推到 index 2（把 tool_use 和 tool_result 都保留在 recent）
    assert split <= 2, f"切点应当 <=2 避免切断配对，实际 split={split}"


def test_safe_split_gives_up_on_orphan_result_at_head():
    """起点就是悬空 tool_result 的情况，算法的处理方式是把它归进 old、不进 recent。

    这个 case 里 tool_result 在 index 0，preferred_recent=1 → split=1。
    recent 只有 ["最近 1"]，里面没有任何 tool 块，所以切点合法，返回 1。
    orphan 那条 tool_result 进了 old，old 会被摘要成文本，orphan 自然消失。

    结论：算法对这个 case 是"正确避开"而不是"放弃"。
    真正触发 return 0 的是 preferred_recent >= n 或者所有 split 都退到 0 仍有 orphan。
    """
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T_MISSING", "content": "..."},
        ]},
        {"role": "user", "content": "最近 1"},
    ]
    split = _find_safe_split_index(messages, preferred_recent=1)
    assert split == 1, (
        "orphan 在头部 + preferred_recent=1 时，算法把 orphan 归 old 即可，返回 1"
    )


def test_safe_split_gives_up_when_preferred_recent_covers_all():
    """preferred_recent >= n 时应当直接返回 0（不压缩）。"""
    messages = [
        {"role": "user", "content": "1"},
        {"role": "user", "content": "2"},
    ]
    assert _find_safe_split_index(messages, preferred_recent=2) == 0
    assert _find_safe_split_index(messages, preferred_recent=5) == 0


def test_safe_split_healthy_case():
    """纯文本消息，按预期切点切。"""
    messages = [{"role": "user", "content": f"msg-{i}"} for i in range(10)]
    split = _find_safe_split_index(messages, preferred_recent=3)
    assert split == 7, f"10 条纯文本、保留最近 3 条，切点应当是 7，实际 {split}"

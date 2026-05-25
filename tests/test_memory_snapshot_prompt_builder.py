"""Stage 3 Slice 3: MemorySnapshot / prompt_builder seam tests.

这些测试保护 prompt 构造边界：prompt_builder 只能消费已经批准、过滤、带预算的
MemorySnapshot；它不能调用 MemoryPolicy、不能读 MemoryStore、不能做 retrieval，
也不能把敏感 memory 明文塞进 system prompt。Slice 3 只建立 prompt injection
seam，不实现真实 recall/persistence。
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent.memory_contracts import MemoryScope, MemorySensitivity


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT_BUILDER = PROJECT_ROOT / "agent" / "prompt_builder.py"
CONTRACT_MODULE = PROJECT_ROOT / "agent" / "memory_contracts.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _agent_imports(path: Path) -> set[str]:
    """用 AST 固定 dependency boundary，避免 prompt 层反向拥有 policy/store。"""

    imports: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def _called_names(path: Path) -> set[str]:
    """收集调用名，确认 snapshot contract 不含 IO/storage 行为。"""

    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_empty_memory_snapshot_preserves_current_prompt_behavior(monkeypatch) -> None:
    """空 snapshot 必须保持现有 prompt 行为。

    Slice 3 的第一个安全要求是 backward compatibility：没有批准 memory 时，
    system prompt 仍然使用当前静态 memory 占位，不产生额外上下文或假 recall。
    """

    from agent.memory_contracts import MemorySnapshot
    from agent.prompt_builder import build_system_prompt

    monkeypatch.setattr("agent.prompt_builder.build_skills_section", lambda: "")

    baseline = build_system_prompt()
    with_empty_snapshot = build_system_prompt(memory_snapshot=MemorySnapshot.empty())

    assert with_empty_snapshot == baseline
    assert "当前未注入长期记忆" in with_empty_snapshot


def test_prompt_builder_renders_approved_snapshot_with_provenance_and_reason(monkeypatch) -> None:
    """prompt_builder 只格式化 approved snapshot，并展示来源/选择原因。

    这不是 retrieval：测试直接传入已经构造好的 MemorySnapshot。prompt_builder
    只能消费它并渲染 prompt 视图，不能决定为什么 recall。
    """

    from agent.memory_contracts import MemorySnapshot, MemorySnapshotItem
    from agent.prompt_builder import build_system_prompt

    monkeypatch.setattr("agent.prompt_builder.build_skills_section", lambda: "")

    snapshot = MemorySnapshot(
        items=(
            MemorySnapshotItem(
                content="用户偏好回答简洁",
                scope=MemoryScope.USER,
                provenance="confirmed:user:pref-1",
                selection_reason="与当前回答风格相关",
                sensitivity=MemorySensitivity.LOW,
            ),
        ),
        selection_reason="当前任务需要回答风格偏好",
        omitted_count=0,
        safety_filter_summary="无敏感记忆被注入",
        token_budget=128,
        rendered_char_budget=400,
    )

    prompt = build_system_prompt(memory_snapshot=snapshot)

    assert "用户偏好回答简洁" in prompt
    assert "confirmed:user:pref-1" in prompt
    assert "与当前回答风格相关" in prompt
    assert "当前任务需要回答风格偏好" in prompt


def test_snapshot_rendering_respects_rendered_budget(monkeypatch) -> None:
    """snapshot 渲染必须受预算约束，不能 dump 所有 memory。

    MemorySnapshot 是 prompt 视图，不是 MemoryStore。预算不足时应省略后续 item，
    并在 prompt 里说明 omitted_count，而不是无限制注入。
    """

    from agent.memory_contracts import MemorySnapshot, MemorySnapshotItem
    from agent.prompt_builder import build_system_prompt

    monkeypatch.setattr("agent.prompt_builder.build_skills_section", lambda: "")

    snapshot = MemorySnapshot(
        items=(
            MemorySnapshotItem(
                content="第一条短记忆",
                scope=MemoryScope.PROJECT,
                provenance="confirmed:project:1",
                selection_reason="项目约束",
            ),
            MemorySnapshotItem(
                content="第二条应该因为预算不足被省略的较长记忆",
                scope=MemoryScope.PROJECT,
                provenance="confirmed:project:2",
                selection_reason="预算测试",
            ),
        ),
        selection_reason="预算测试",
        omitted_count=0,
        safety_filter_summary="budget applied",
        token_budget=16,
        rendered_char_budget=120,
    )

    prompt = build_system_prompt(memory_snapshot=snapshot)

    assert "第一条短记忆" in prompt
    assert "第二条应该因为预算不足" not in prompt
    assert "omitted" in prompt
    assert "budget applied" in prompt


def test_sensitive_snapshot_item_is_filtered_not_plaintext_injected(monkeypatch) -> None:
    """敏感 snapshot item 不能默认明文注入 prompt。

    即使上游构造了 snapshot，prompt 视图也必须保守：HIGH/SECRET 内容用过滤提示
    代替正文，并保留 provenance/reason 便于解释。
    """

    from agent.memory_contracts import MemorySnapshot, MemorySnapshotItem
    from agent.prompt_builder import build_system_prompt

    monkeypatch.setattr("agent.prompt_builder.build_skills_section", lambda: "")

    snapshot = MemorySnapshot(
        items=(
            MemorySnapshotItem(
                content="api token is sk-secret",
                scope=MemoryScope.USER,
                provenance="confirmed:user:secret",
                selection_reason="敏感过滤测试",
                sensitivity=MemorySensitivity.SECRET,
            ),
        ),
        selection_reason="安全测试",
        omitted_count=0,
        safety_filter_summary="敏感内容已过滤",
        token_budget=128,
        rendered_char_budget=400,
    )

    prompt = build_system_prompt(memory_snapshot=snapshot)

    assert "api token is sk-secret" not in prompt
    assert "已过滤敏感记忆" in prompt
    assert "confirmed:user:secret" in prompt
    assert "敏感内容已过滤" in prompt


def test_memory_snapshot_is_not_store_or_operation_api() -> None:
    """MemorySnapshot 是 prompt view，不是 store 或 operation API。

    它不能提供 write/update/delete/save/persist；这些属于后续 MemoryStore /
    MemoryOperationResult 设计，不能混入 Slice 3。
    """

    from agent.memory_contracts import MemorySnapshot

    snapshot = MemorySnapshot.empty()

    assert not any(
        hasattr(snapshot, name)
        for name in {"write", "update", "delete", "save", "persist"}
    )


def test_prompt_builder_does_not_import_policy_store_retrieval_or_mcp() -> None:
    """prompt_builder 不能拥有 memory decision/retrieval/store 责任。"""

    imports = _agent_imports(PROMPT_BUILDER)

    forbidden = {
        "agent.memory_policy",
        "agent.checkpoint",
        "agent.state",
        "agent.mcp",
        "agent.tool_executor",
        "agent.tool_registry",
        "agent.input_backends",
    }
    assert imports.isdisjoint(forbidden), imports & forbidden


def test_memory_snapshot_contract_has_no_runtime_checkpoint_tui_or_io_dependency() -> None:
    """MemorySnapshot contract 也必须保持无副作用边界。"""

    imports = _agent_imports(CONTRACT_MODULE)
    calls = _called_names(CONTRACT_MODULE)

    forbidden_imports = {
        "agent.core",
        "agent.state",
        "agent.checkpoint",
        "agent.input_backends",
        "agent.mcp",
        "agent.tool_executor",
    }
    forbidden_calls = {
        "open",
        "read_text",
        "write_text",
        "mkdir",
        "glob",
        "iterdir",
        "connect",
        "request",
        "urlopen",
    }

    assert imports.isdisjoint(forbidden_imports), imports & forbidden_imports
    assert calls.isdisjoint(forbidden_calls), calls & forbidden_calls


# ── System Prompt Tool-Use Guidance tests ───────────────────────────────
# Phase 1: verify SYSTEM_PROMPT contains generic tool-use guidance
# that is NOT provider-specific (no kimi/DashScope references).

def test_system_prompt_contains_tool_use_guidance() -> None:
    """验证 SYSTEM_PROMPT 包含通用工具使用引导。"""
    from config import SYSTEM_PROMPT

    assert "工具使用指南" in SYSTEM_PROMPT
    assert "优先使用工具完成明确可工具化的任务" in SYSTEM_PROMPT
    assert "不要伪造工具结果" in SYSTEM_PROMPT
    assert "工具返回后才能引用结果" in SYSTEM_PROMPT
    assert "普通对话不需要工具" in SYSTEM_PROMPT
    assert "只使用已注册工具" in SYSTEM_PROMPT


def test_system_prompt_tool_use_guidance_is_not_provider_specific() -> None:
    """验证工具使用引导不包含 provider-specific hack。"""
    from config import SYSTEM_PROMPT

    guidance_start = SYSTEM_PROMPT.find("工具使用指南")
    assert guidance_start > 0
    guidance_section = SYSTEM_PROMPT[guidance_start:]

    # 不得包含 provider-specific 引用
    forbidden = ("kimi", "DashScope", "deepseek", "anthropic_compatible", "openai_compatible")
    for term in forbidden:
        assert term not in guidance_section, f"guidance contains provider-specific term: {term}"


def test_system_prompt_does_not_force_tools_on_all_tasks() -> None:
    """验证工具使用引导不强迫所有任务使用工具。"""
    from config import SYSTEM_PROMPT

    assert "普通对话不需要工具" in SYSTEM_PROMPT
    assert "闲聊、知识问答、解释概念、讨论方案" in SYSTEM_PROMPT
    # 不应包含类似 "always use tools" 的硬性要求
    assert "always use tools" not in SYSTEM_PROMPT.lower()
    assert "必须使用工具" not in SYSTEM_PROMPT


def test_build_system_prompt_includes_tool_use_guidance() -> None:
    """验证 build_system_prompt() 输出包含工具使用引导。"""
    from agent.prompt_builder import build_system_prompt

    prompt = build_system_prompt(memory_snapshot=None)
    assert "工具使用指南" in prompt
    assert "不要伪造工具结果" in prompt


def test_fake_provider_chat_still_works_after_prompt_change() -> None:
    """验证 fake provider 路径不受 system prompt 修改影响。"""
    from agent.core import chat
    from agent.provider.fake_provider import FakeProvider
    from agent.display_events import RuntimeEvent

    events: list[RuntimeEvent] = []

    def sink(e: RuntimeEvent) -> None:
        events.append(e)

    chat("你好，今天怎么样？", provider=FakeProvider(), on_runtime_event=sink)
    et = [e.event_type for e in events]
    assert "assistant.delta" in et
    assert "run.summary" in et
    text = " ".join(e.text for e in events if e.text)
    assert len(text) > 10

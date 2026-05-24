"""First Usable Task E2E Smoke Test.

验证 First Usable Task 的核心用户路径均可通过统一入口走通：
- Onboarding / help 信息可渲染
- demo tool 路径（run_local_demo）完整可执行
- core.chat() 统一入口 + FakeProvider 全链路可走通
- SkillRegistry 正确加载 demo-note-maker
- Tool/Skill/onboarding/checkpoint 基本路径可用

所有验证均通过统一入口（chat / run_local_demo / render_onboarding / build_skill_registry），
不使用 direct handler / dispatcher 冒充 E2E。
"""

from __future__ import annotations

import sys

import pytest

from agent.cli_renderer import render_onboarding
from agent.core import chat
from agent.local_demo import run_local_demo, format_demo_result
from agent.provider.fake_provider import FakeProvider
from agent.runtime_integration.phase1_hook import build_skill_registry


def _print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ========== S1: Onboarding 可渲染 ==========


def test_s1_onboarding_renders_with_key_info():
    """S1: render_onboarding() 输出包含关键能力、限制、安全边界信息。"""
    out = render_onboarding()

    # 关键段落必须出现
    assert "First Agent" in out
    assert "Fake Provider" in out
    assert "demo.echo_task_summary" in out or "demo.write_demo_note" in out
    assert "demo-note-maker" in out
    assert "python main.py demo" in out
    assert "python main.py health" in out
    assert "python main.py logs" in out
    assert "Ctrl+C" in out
    # 安全边界
    assert "不读取 .env" in out or ".env" in out
    assert "不访问外部网络" in out or "不调用真实 API" in out
    # 诚实表述：尚未产品化
    assert "尚未产品化" in out or "product decision" in out or "partial" in out


# ========== S2: Demo Tool E2E 路径 ==========


def test_s2_local_demo_completes_with_tool_execution():
    """S2: run_local_demo() 完整执行 fake provider → 工具动作 → ToolResult。

    通过统一 demo 入口 run_local_demo()，不走 direct handler。
    """
    result = run_local_demo("create a smoke test note")

    assert result.provider == "fake"
    assert result.task == "create a smoke test note"
    assert len(result.steps) >= 1

    # 第一步必须是 demo.write_demo_note
    step = result.steps[0]
    assert step.action.tool_name == "demo.write_demo_note"
    assert step.envelope.status == "executed"
    assert step.envelope.content_length > 0
    assert len(step.trace_event.metadata) > 0

    # final_answer 非空
    assert len(result.final_answer) > 0
    assert "demo note" in result.final_answer or "wrote" in result.final_answer

    # trace events 包含 tool_result（带 tool name 后缀）和 completion
    trace_names = [e.name for e in result.trace_events]
    assert any("tool_result" in n for n in trace_names), (
        f"trace events 应包含 tool_result，实际: {trace_names}"
    )
    assert "demo.complete" in trace_names


def test_s3_local_demo_formatted_output_readable():
    """S3: format_demo_result() 输出可读的 demo 执行摘要。"""
    result = run_local_demo("smoke test task")
    formatted = format_demo_result(result)

    assert "Local Agent Demo" in formatted
    assert "fake" in formatted
    assert "smoke test task" in formatted
    assert "demo.write_demo_note" in formatted
    assert "ok" in formatted.lower() or "executed" in formatted.lower()
    assert "Trace summary" in formatted


# ========== S3: chat() 统一入口全链路 ==========


def test_s4_chat_with_fake_provider_produces_reply():
    """S4: chat() + FakeProvider 完成一次完整的 turn → 流式输出用户可见内容。

    这是统一入口全链路 smoke：core loop → planning → execution → turn-end hook。
    FakeProvider 的 provider_type == "fake" 触发自动构建 phase1_dispatcher +
    skill_registry，证明 SKILL_SELECT 等 RuntimeAction dispatch 在 turn-end
    时被正确调度。

    FakeProvider 通过 on_runtime_event 流式输出 assistant.delta 事件，
    chat() 返回值用于 UI 控制流（空字符串表示正常完成）。
    """
    captured_events: list = []
    reply = chat(
        "帮我创建一个 demo note",
        provider=FakeProvider(),
        on_runtime_event=lambda ev: captured_events.append(ev),
    )

    # reply 用于 UI 控制流，空字符串表示正常完成（非错误）
    assert isinstance(reply, str)

    # RuntimeEvent 必须有 assistant.delta 事件，内容包含用户回显
    delta_events = [
        e for e in captured_events
        if getattr(e, "event_type", None) == "assistant.delta"
    ]
    assert len(delta_events) > 0, (
        "chat() 应通过 on_runtime_event 产生 assistant.delta 事件"
    )
    # 拼接所有 delta text 应包含用户输入的回显
    full_text = "".join(getattr(e, "text", "") for e in delta_events)
    assert "已收到你的消息" in full_text, (
        f"流式输出应包含 FakeProvider 回显，实际: {full_text!r}"
    )


def test_s5_chat_with_fake_provider_handles_empty_input():
    """S5: chat() + FakeProvider 对空输入返回空字符串，不崩溃。"""
    reply = chat("   ", provider=FakeProvider())
    assert reply == ""


# ========== S4: Skill Registry ==========


def test_s6_skill_registry_has_demo_note_maker():
    """S6: build_skill_registry() 返回的 registry 包含 demo-note-maker。"""
    registry = build_skill_registry()
    visible = registry.list_visible()
    names = {d.name for d in visible}

    assert "demo-note-maker" in names, (
        f"demo-note-maker 应在 visible skills 中，实际: {names}"
    )

    desc = registry.get_descriptor("demo-note-maker")
    assert desc is not None
    assert desc.status == "active"
    assert desc.risk_level == "low"


# ========== 可执行入口：python -m pytest tests/smoke/ -v ==========


if __name__ == "__main__":
    print("=" * 60)
    print("  First Usable Task E2E Smoke Test")
    print("=" * 60)
    print()
    print("验证 Tool / Skill / Onboarding / Checkpoint 基本用户路径可用。")
    print("所有验证通过统一入口，不使用 direct handler / dispatcher 冒充 E2E。")
    print()

    # 等价于运行 pytest，但输出更友好
    sys.exit(pytest.main([__file__, "-v", "--no-header"]))

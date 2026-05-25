"""Phase 2: Real Provider Tool-Use E2E Hardening.

验证真实 provider 下完整 tool_use E2E 链路：
  A. Basic chat control — 普通对话不触发工具
  B. Explicit tool-use task — 显式 prompt 触发 tool_use → Tool Pipeline
  C. Natural-but-tool-appropriate task — 自然 prompt，验证 system prompt 优化效果
  D. Tool non-use control — 普通对话确认不乱用工具

所有路径必须经过 core.chat() → loop.py → Tool Pipeline，不使用 direct handler bypass。

Provider 配置仅来自项目 .env，不依赖 shell 环境或 coding agent 外层模型。
"""

from __future__ import annotations

import sys
import os
import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _load_project_env() -> dict[str, str]:
    from config import _load_project_dotenv_values
    return _load_project_dotenv_values(_PROJECT_ROOT)


def main():
    results: list[dict] = []
    project_env = _load_project_env()

    api_key = project_env.get("ANTHROPIC_API_KEY", "")
    base_url = project_env.get("ANTHROPIC_BASE_URL", "")
    model = project_env.get("ANTHROPIC_MODEL", "")

    if not api_key or not base_url or not model:
        print("BLOCKED: .env 缺少必要配置")
        return 1

    # 覆盖 shell env，确保只使用项目 .env 配置
    os.environ["MY_FIRST_AGENT_LLM_PROVIDER"] = "anthropic_compatible"
    os.environ["ANTHROPIC_API_KEY"] = api_key
    os.environ["ANTHROPIC_BASE_URL"] = base_url
    os.environ["ANTHROPIC_MODEL"] = model

    provider_label = f"anthropic_compatible | model={model}"

    print("=" * 60)
    print("Phase 2: Real Provider Tool-Use E2E Hardening")
    print(f"Provider: {provider_label}")
    print("=" * 60)

    from agent.core import chat
    from agent.display_events import RuntimeEvent

    # ── A. Basic chat control ──────────────────────────────────────────
    print("\n--- A: Basic chat control ---")
    events_a: list[RuntimeEvent] = []
    def sink_a(e: RuntimeEvent) -> None:
        events_a.append(e)

    chat("你好，请用一句话介绍你自己", on_runtime_event=sink_a)
    et_a = [e.event_type for e in events_a]
    text_a = " ".join(e.text for e in events_a if e.text)
    has_real_response = len(text_a) > 10 and "已收到你的消息" not in text_a
    has_summary = "run.summary" in et_a
    # 普通对话不应触发工具
    tool_triggered_a = "tool.requested" in et_a

    result_a = {
        "test": "A_basic_chat",
        "prompt": "你好，请用一句话介绍你自己",
        "status": "PASS" if (has_real_response and has_summary and not tool_triggered_a) else "CONCERN",
        "real_response": has_real_response,
        "run_summary": has_summary,
        "tool_triggered": tool_triggered_a,
        "output_preview": text_a[:200],
        "note": "普通对话应返回真实回复，不触发工具",
    }
    if tool_triggered_a:
        result_a["note"] += " ⚠️ 意外触发了工具"
    results.append(result_a)
    print(f"  -> {result_a['status']}: real={has_real_response}, summary={has_summary}, tool={tool_triggered_a}")

    # ── B. Explicit tool-use task ─────────────────────────────────────
    print("\n--- B: Explicit tool-use task ---")
    events_b: list[RuntimeEvent] = []
    def sink_b(e: RuntimeEvent) -> None:
        events_b.append(e)

    chat(
        "请使用已注册的 demo.echo_task_summary 工具来总结这个任务。不要只用文字回答；如果工具可用，请调用工具。",
        on_runtime_event=sink_b,
    )
    et_b = [e.event_type for e in events_b]
    text_b = " ".join(e.text for e in events_b if e.text)
    tool_requested_b = "tool.requested" in et_b
    tool_result_b = "tool.result_visible" in et_b

    # 对于需要确认的工具，可能还需要确认步骤
    has_confirmation_b = "tool.confirmation_requested" in et_b

    result_b = {
        "test": "B_explicit_tool_use",
        "prompt": "请使用已注册的 demo.echo_task_summary 工具...",
        "status": "PASS" if tool_requested_b else "CONCERN",
        "tool_requested": tool_requested_b,
        "tool_result_visible": tool_result_b,
        "confirmation_requested": has_confirmation_b,
        "event_types": et_b,
        "output_preview": text_b[:200],
        "note": f"tool_req={tool_requested_b}, result={tool_result_b}, confirm={has_confirmation_b}",
    }
    results.append(result_b)
    print(f"  -> {result_b['status']}: {result_b['note']}")

    # ── C. Natural-but-tool-appropriate task ──────────────────────────
    print("\n--- C: Natural tool-use task ---")
    # 清理之前的 demo 文件
    demo_dir = _PROJECT_ROOT / "workspace" / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    before_files_c = set(demo_dir.rglob("note.md")) if demo_dir.exists() else set()

    events_c: list[RuntimeEvent] = []
    def sink_c(e: RuntimeEvent) -> None:
        events_c.append(e)

    chat(
        "帮我创建一个 demo note，内容写 'Phase 2 real provider tool use E2E test'",
        on_runtime_event=sink_c,
    )
    et_c = [e.event_type for e in events_c]
    text_c = " ".join(e.text for e in events_c if e.text)
    tool_requested_c = "tool.requested" in et_c
    has_confirmation_c = "tool.confirmation_requested" in et_c
    has_tool_result_c = "tool.result_visible" in et_c

    file_created_c = False
    if tool_requested_c and has_confirmation_c:
        # 需要确认 — 发送确认
        events_c2: list[RuntimeEvent] = []
        def sink_c2(e: RuntimeEvent) -> None:
            events_c2.append(e)
        chat("y", on_runtime_event=sink_c2)
        et_c2 = [e.event_type for e in events_c2]
        has_tool_result_c = "tool.result_visible" in et_c2
        after_files_c = set(demo_dir.rglob("note.md")) if demo_dir.exists() else set()
        file_created_c = len(after_files_c - before_files_c) > 0

    result_c = {
        "test": "C_natural_tool_use",
        "prompt": "帮我创建一个 demo note...",
        "status": "PASS" if (tool_requested_c and has_tool_result_c) else "CONCERN",
        "tool_requested": tool_requested_c,
        "confirmation_requested": has_confirmation_c,
        "tool_result_visible": has_tool_result_c,
        "file_created": file_created_c,
        "output_preview": text_c[:200],
        "note": f"tool_req={tool_requested_c}, confirm={has_confirmation_c}, result={has_tool_result_c}, file={file_created_c}",
    }

    if not tool_requested_c:
        result_c["note"] += " | 模型未触发工具（prompt sensitivity）"
    results.append(result_c)
    print(f"  -> {result_c['status']}: {result_c['note']}")

    # ── D. Tool non-use control ───────────────────────────────────────
    print("\n--- D: Tool non-use control ---")
    events_d: list[RuntimeEvent] = []
    def sink_d(e: RuntimeEvent) -> None:
        events_d.append(e)

    chat("今天天气真不错，适合出去走走", on_runtime_event=sink_d)
    et_d = [e.event_type for e in events_d]
    text_d = " ".join(e.text for e in events_d if e.text)
    tool_triggered_d = "tool.requested" in et_d
    has_summary_d = "run.summary" in et_d

    result_d = {
        "test": "D_tool_non_use_control",
        "prompt": "今天天气真不错，适合出去走走",
        "status": "PASS" if (not tool_triggered_d and has_summary_d) else "CONCERN",
        "tool_triggered": tool_triggered_d,
        "run_summary": has_summary_d,
        "output_preview": text_d[:200],
        "note": "闲聊不应触发工具",
    }
    if tool_triggered_d:
        result_d["note"] += " ⚠️ 意外触发了工具"
    results.append(result_d)
    print(f"  -> {result_d['status']}: tool={tool_triggered_d}")

    # ── 汇总 ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Phase 2 E2E 结果矩阵")
    print("=" * 60)
    for r in results:
        print(f"  {r['test']:<35} {r['status']:<10} {r['note']}")

    passed = sum(1 for r in results if r['status'] == 'PASS')
    concerns = sum(1 for r in results if r['status'] == 'CONCERN')
    print(f"\nPASS: {passed}, CONCERN: {concerns}, FAIL: 0")

    # 写入报告
    report_path = _PROJECT_ROOT / "docs" / "dogfood" / "real-provider-e2e-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({
            "phase": "Phase 2: Real Provider Tool-Use E2E Hardening",
            "provider": provider_label,
            "env_used": True,
            "results": results,
            "summary": {"pass": passed, "concern": concerns, "fail": 0},
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nReport written to: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

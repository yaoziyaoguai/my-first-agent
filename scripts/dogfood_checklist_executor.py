"""Dogfood checklist 自动执行脚本。

通过 core.chat() 统一入口执行 docs/dogfood/local-manual-dogfood-checklist.md
中的所有 9 个步骤，收集 RuntimeEvent 验证行为，输出 PASS/CONCERN/FAIL 矩阵。

中文学习边界：
- 本脚本只调用 core.chat() —— 不 direct handler/dispatcher/adapter
- 使用 FakeProvider，不读 .env、不调用真实 API
- 所有 side effects 限制在 workspace/demo/ 下
- 这是 evidence collection，不是 second runtime

2026-05-25 更新：
- Step 1 (help): main.py 在 chat() 之前处理 help；使用 subprocess 测试 main.py --help
- Step 2 (普通对话): echo 通过 assistant.delta 事件传递，return value 可能为空
- Step 3 (Demo Tool): tool pipeline 包含 confirmation 阶段，需两步调用（触发+确认）
- Step 5 (subagent): code-reviewer 需 status: active 才能可见（已修复）
- Step 8 (forget): 空 store 无短 ID 是预期行为
"""
from __future__ import annotations

import sys
import os
import json
import re
import subprocess
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from agent.core import chat  # noqa: E402
from agent.provider.fake_provider import FakeProvider  # noqa: E402
from agent.display_events import RuntimeEvent  # noqa: E402


def _collect_events() -> tuple[list[RuntimeEvent], callable]:
    """创建事件收集器和 sink callback。"""
    events: list[RuntimeEvent] = []

    def sink(event: RuntimeEvent) -> None:
        events.append(event)

    return events, sink


def _event_types(events: list[RuntimeEvent]) -> list[str]:
    """提取事件类型列表用于断言。"""
    return [e.event_type for e in events]


def _events_text(events: list[RuntimeEvent]) -> str:
    """拼接所有事件的文本用于内容检查。"""
    parts = []
    for e in events:
        if e.text:
            parts.append(e.text)
    return " ".join(parts)


def main():
    results: list[dict[str, Any]] = []
    fake_provider = FakeProvider()

    # ── Step 1: Onboarding / Help ──────────────────────────────────────
    # main.py 把 "help" 作为 CLI flag (--help) 和交互模式特殊命令处理，
    # 都在 chat() 之前。这里通过 subprocess 测试 main.py --help。
    print("=" * 60)
    print("Step 1: Onboarding / Help")
    try:
        proc = subprocess.run(
            [sys.executable, str(_PROJECT_ROOT / "main.py"), "--help"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "HOME": "/private/tmp"},
        )
        help_output = proc.stdout
        has_help_content = len(help_output) > 50 and "FakeProvider" in help_output
        step1 = {
            "step": 1,
            "name": "Onboarding / Help",
            "input": "python main.py --help",
            "status": "PASS" if has_help_content else "CONCERN",
            "output_summary": help_output[:500],
            "exit_code": proc.returncode,
            "note": "help 包含能力说明" if has_help_content else f"help 输出不足 (len={len(help_output)})",
        }
    except Exception as exc:
        step1 = {
            "step": 1,
            "name": "Onboarding / Help",
            "input": "python main.py --help",
            "status": "FAIL",
            "output_summary": str(exc)[:200],
            "note": f"help 命令失败: {exc}",
        }
    results.append(step1)
    print(f"  -> {step1['status']}: {step1['note']}")

    # ── Step 2: 普通对话 ──────────────────────────────────────────────
    # FakeProvider 通过 RuntimeEvent (assistant.delta) 回显用户消息。
    # chat() 返回值在 streaming 路径下可能为空——事件才是用户可见输出通路。
    print("Step 2: 普通对话")
    events, sink = _collect_events()
    output = chat(
        "你好，今天怎么样？", provider=fake_provider, on_runtime_event=sink,
    )
    et2 = _event_types(events)
    event_text = _events_text(events)
    # 检查 assistant.delta 事件中的回显内容
    has_echo_event = "assistant.delta" in et2 and ("已收到" in event_text or "你好" in event_text)
    has_run_summary = "run.summary" in et2
    step2 = {
        "step": 2,
        "name": "普通对话",
        "input": "你好，今天怎么样？",
        "status": "PASS" if (has_echo_event and has_run_summary) else "CONCERN",
        "output_summary": event_text[:300],
        "return_value": repr(output)[:100],
        "event_types": et2,
        "note": f"echo_event={has_echo_event}, run_summary={has_run_summary}",
    }
    results.append(step2)
    print(f"  -> {step2['status']}: {step2['note']}")

    # ── Step 3: 触发 Demo Tool（两步：触发 → 确认） ──────────────────
    # demo.write_demo_note 的 confirmation="always"，正常走 Tool Pipeline。
    # 第一步触发 tool_use → confirmation_required；第二步确认 → 执行。
    # demo_write_demo_note 通过 _default_demo_note_path() 创建时间戳目录：
    #   workspace/demo/<YYYYMMDDTHHMMSSZ>/note.md
    # 因此不能检查固定路径，需要扫描 workspace/demo/ 下的新文件。
    print("Step 3: 触发 Demo Tool")
    demo_dir = _PROJECT_ROOT / "workspace" / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    before_files = set(demo_dir.rglob("note.md")) if demo_dir.exists() else set()

    # 3a: 触发工具调用
    events_a, sink_a = _collect_events()
    output_a = chat(
        "make a demo note", provider=fake_provider, on_runtime_event=sink_a,
    )
    et3a = _event_types(events_a)
    has_tool_requested = "tool.requested" in et3a
    has_confirmation_requested = "tool.confirmation_requested" in et3a
    # 3b: 确认执行
    events_b, sink_b = _collect_events()
    output_b = chat(
        "y", provider=fake_provider, on_runtime_event=sink_b,
    )
    et3b = _event_types(events_b)
    has_tool_result = "tool.result_visible" in et3b
    # 扫描确认后新增的 note.md 文件（时间戳目录下的）
    after_files = set(demo_dir.rglob("note.md")) if demo_dir.exists() else set()
    new_files = after_files - before_files
    file_created = len(new_files) > 0

    full_pipeline = has_tool_requested and has_confirmation_requested and has_tool_result and file_created
    step3 = {
        "step": 3,
        "name": "触发 Demo Tool (两步确认)",
        "input": "make a demo note → y (confirm)",
        "status": "PASS" if full_pipeline else ("CONCERN" if (has_tool_requested and file_created) else "FAIL"),
        "output_summary": f"trigger: {output_a[:150]} | confirm: {output_b[:150]}",
        "tool_requested": has_tool_requested,
        "confirmation_requested": has_confirmation_requested,
        "tool_result": has_tool_result,
        "file_created": file_created,
        "new_files": [str(f) for f in new_files],
        "event_types_trigger": et3a,
        "event_types_confirm": et3b,
        "note": "完整 Tool Pipeline: TOOL_REQUEST→CONFIRM→TOOL_RESULT" if full_pipeline else f"pipeline incomplete: req={has_tool_requested}, confirm_req={has_confirmation_requested}, result={has_tool_result}, file={file_created}",
    }
    results.append(step3)
    print(f"  -> {step3['status']}: {step3['note']}")

    # ── Step 4: 查看记忆列表 ──────────────────────────────────────────
    print("Step 4: 查看记忆列表")
    events, sink = _collect_events()
    output = chat(
        "show memories", provider=fake_provider, on_runtime_event=sink,
    )
    # 应该展示记忆列表（可能为空），格式应包含记忆相关的词
    memory_keywords = ("记忆", "暂无", "已保存", "memories", "来源", "unavailable")
    has_memory_format = any(kw in output for kw in memory_keywords)
    step4 = {
        "step": 4,
        "name": "查看记忆列表",
        "input": "show memories",
        "status": "PASS" if has_memory_format else "CONCERN",
        "output_summary": output[:300],
        "note": "memory list 格式正确" if has_memory_format else "格式不符合预期",
    }
    results.append(step4)
    print(f"  -> {step4['status']}: {step4['note']}")

    # ── Step 5: 查看子代理列表 ────────────────────────────────────────
    print("Step 5: 查看子代理列表")
    events, sink = _collect_events()
    output = chat(
        "show subagents", provider=fake_provider, on_runtime_event=sink,
    )
    has_demo_stat = "demo-stat" in output.lower()
    has_code_reviewer = "code-reviewer" in output.lower()
    has_two = has_demo_stat and has_code_reviewer
    step5 = {
        "step": 5,
        "name": "查看子代理列表",
        "input": "show subagents",
        "status": "PASS" if has_two else "CONCERN",
        "output_summary": output[:300],
        "has_demo_stat": has_demo_stat,
        "has_code_reviewer": has_code_reviewer,
        "note": f"demo-stat={'Y' if has_demo_stat else 'N'}, code-reviewer={'Y' if has_code_reviewer else 'N'}",
    }
    results.append(step5)
    print(f"  -> {step5['status']}: {step5['note']}")

    # ── Step 6: CLI 委托子代理 ────────────────────────────────────────
    print("Step 6: CLI 委托子代理")
    events, sink = _collect_events()
    output = chat(
        "delegate to demo-stat: count files in workspace",
        provider=fake_provider, on_runtime_event=sink,
    )
    et6 = _event_types(events)
    has_delegating = "subagent.delegating" in et6
    has_delegated = "subagent.delegated" in et6
    has_run_summary = "run.summary" in et6
    has_result = len(output) > 10 and "demo-stat" in output.lower()
    step6 = {
        "step": 6,
        "name": "CLI 委托子代理",
        "input": "delegate to demo-stat: count files in workspace",
        "status": "PASS" if (has_delegating and has_delegated and has_run_summary and has_result) else "CONCERN",
        "output_summary": output[:300],
        "delegating_event": has_delegating,
        "delegated_event": has_delegated,
        "run_summary_event": has_run_summary,
        "has_result": has_result,
        "note": f"delegating={has_delegating}, delegated={has_delegated}, run_summary={has_run_summary}, result={has_result}",
    }
    results.append(step6)
    print(f"  -> {step6['status']}: {step6['note']}")

    # ── Step 7: 自然语言委托子代理 ────────────────────────────────────
    print("Step 7: 自然语言委托子代理")
    events, sink = _collect_events()
    output = chat(
        "帮我统计 demo workspace",
        provider=fake_provider, on_runtime_event=sink,
    )
    et7 = _event_types(events)
    has_delegating7 = "subagent.delegating" in et7
    has_delegated7 = "subagent.delegated" in et7
    has_run_summary7 = "run.summary" in et7
    has_result7 = len(output) > 10
    step7 = {
        "step": 7,
        "name": "自然语言委托子代理",
        "input": "帮我统计 demo workspace",
        "status": "PASS" if (has_delegating7 and has_delegated7 and has_run_summary7 and has_result7) else "CONCERN",
        "output_summary": output[:300],
        "delegating_event": has_delegating7,
        "delegated_event": has_delegated7,
        "run_summary_event": has_run_summary7,
        "has_result": has_result7,
        "note": f"delegating={has_delegating7}, delegated={has_delegated7}, run_summary={has_run_summary7}, result={has_result7}",
    }
    results.append(step7)
    print(f"  -> {step7['status']}: {step7['note']}")

    # ── Step 8: 忘记记忆 ──────────────────────────────────────────────
    print("Step 8: 忘记记忆")

    # 8a: 确认记忆列表显示格式
    events, sink = _collect_events()
    mem_list_output = chat(
        "show memories", provider=fake_provider, on_runtime_event=sink,
    )
    # 格式检查：空列表或包含短 ID 格式
    is_empty = "暂无" in mem_list_output
    has_short_ids = bool(re.search(r'\[[a-f0-9]{8}\]', mem_list_output))
    list_format_ok = is_empty or has_short_ids

    # 8b: forget by invalid ID
    events, sink = _collect_events()
    output_invalid = chat(
        "forget id:nonexistent", provider=fake_provider, on_runtime_event=sink,
    )
    not_found_ok = "未找到" in output_invalid

    # 8c: forget by content keyword (可能匹配 0 条)
    events, sink = _collect_events()
    output_keyword = chat(
        "忘记 test", provider=fake_provider, on_runtime_event=sink,
    )
    keyword_msg_ok = "移除" in output_keyword or "未找到" in output_keyword or "匹配" in output_keyword

    step8 = {
        "step": 8,
        "name": "忘记记忆",
        "input": "show memories + forget id:nonexistent + 忘记 test",
        "status": "PASS" if (list_format_ok and not_found_ok and keyword_msg_ok) else "CONCERN",
        "output_summary": f"memory_list: {mem_list_output[:150]} | invalid_id: {output_invalid[:150]} | keyword: {output_keyword[:150]}",
        "list_format_ok": list_format_ok,
        "not_found_msg": not_found_ok,
        "keyword_forget_msg": keyword_msg_ok,
        "note": f"list_format={list_format_ok}, not_found={not_found_ok}, keyword_msg={keyword_msg_ok}",
    }
    results.append(step8)
    print(f"  -> {step8['status']}: {step8['note']}")

    # ── 汇总 ──────────────────────────────────────────────────────────
    print("=" * 60)
    print("Dogfood Checklist 执行结果矩阵")
    print("=" * 60)
    print(f"{'Step':<6} {'Name':<35} {'Status':<10}")
    print("-" * 60)
    for r in results:
        print(f"{r['step']:<6} {r['name']:<35} {r['status']:<10}")
    print("-" * 60)
    passed = sum(1 for r in results if r['status'] == 'PASS')
    concerns = sum(1 for r in results if r['status'] == 'CONCERN')
    failed = sum(1 for r in results if r['status'] == 'FAIL')
    print(f"PASS: {passed}, CONCERN: {concerns}, FAIL: {failed}")

    # 输出 JSON 用于后续处理
    print("\n--- JSON ---")
    print(json.dumps(results, ensure_ascii=False, indent=2))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

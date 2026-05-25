"""Real Provider Dogfood 自动执行脚本。

通过 core.chat() 统一入口 + 真实 LLM 执行 dogfood checklist 中的关键步骤，
验证 real provider 与 FakeProvider 共享同一 core.chat() → loop.py → Tool Pipeline。

**关键边界 —— First Agent provider ≠ coding agent 外层模型：**
- 本脚本的 real provider 配置**仅来自项目 .env**，通过 agent/provider/factory.py 加载
- 外层 Claude Code / coding agent 自己的运行模型（如 deepseek-v4-pro、claude-opus-4-7 等）
  不代表 First Agent 项目里的 real provider 配置
- 不要把 coding agent 外层模型当成 First Agent 的真实 API dogfood provider

**安全边界：**
- 只使用安全 demo prompts（你好、show memories、show subagents 等）
- 不读取私人资料、不执行危险工具、不写用户真实目录
- 工具调用限制在 workspace/demo/ 下
- 所有输出记录到 dogfood report，不暴露 secret value

**与 fake dogfood 的区别：**
- fake: 使用 FakeProvider，确定性 echo + 关键词匹配 tool decision
- real: 使用真实 LLM，真实模型推理和工具选择；使用项目 .env 配置，
  仅验证现有 core.chat/loop.py/Tool Pipeline/Memory/SubAgent 主流程

**Provider 配置来源（重要）：**
- 本脚本从项目 .env 读取配置后设置 os.environ，覆盖 shell 环境中的任何值
- 这样确保 First Agent 的 provider 只来自项目配置，不与 coding agent 环境混淆
- build_model_provider_from_env() 检查 MY_FIRST_AGENT_LLM_PROVIDER env var，
  然后调用 load_agent_provider_config() 读取 ANTHROPIC_* 环境变量
"""

from __future__ import annotations

import sys
import os
import json
import subprocess
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _load_project_env() -> dict[str, str]:
    """从项目 .env 加载配置值，不依赖 shell 环境，不污染 os.environ。

    使用 config.py 的 _load_project_dotenv_values()——与项目配置层一致的加载方式。
    返回值只包含 key→value 映射，调用方不得打印、记录或序列化 secret value。
    """
    from config import _load_project_dotenv_values
    return _load_project_dotenv_values(_PROJECT_ROOT)


def main():
    results: list[dict[str, Any]] = []
    project_env = _load_project_env()

    # 从项目 .env 读取配置——不使用 shell env 以免混入 Claude Code 自身配置。
    # 项目 .env 中可能配置的 provider 与 coding agent 外层模型（如 deepseek-v4-pro）
    # 是完全不同的东西：coding agent 模型 ≠ First Agent provider。
    api_key = project_env.get("ANTHROPIC_API_KEY", "")
    base_url = project_env.get("ANTHROPIC_BASE_URL", "")
    model = project_env.get("ANTHROPIC_MODEL", "")

    if not api_key or not base_url or not model:
        print("REAL_PROVIDER_BLOCKED: .env 缺少 ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL")
        return 1

    # 将项目 .env 的值写入 os.environ，覆盖 shell 环境中可能存在的任何同名变量。
    # 这是为了防止 shell 环境中的 coding agent 配置（如 deepseek 的 URL/key）
    # 被误当成 First Agent 的 provider 配置。
    os.environ["MY_FIRST_AGENT_LLM_PROVIDER"] = "anthropic_compatible"
    os.environ["ANTHROPIC_API_KEY"] = api_key
    os.environ["ANTHROPIC_BASE_URL"] = base_url
    os.environ["ANTHROPIC_MODEL"] = model

    # provider 识别信息（不打印 secret）
    provider_label = f"anthropic_compatible | model={model} | base_url={base_url}"

    print("=" * 60)
    print("Real Provider Dogfood — 使用项目 .env 配置的 First Agent provider")
    print(f"Provider: {provider_label}")
    print("（注意：外层 coding agent 模型 ≠ First Agent provider；provider 来自项目 .env）")
    print("=" * 60)

    # 构建 subprocess env：使用已覆盖的 os.environ（项目 .env 值），加上安全的 HOME
    run_env = {
        **os.environ,
        "HOME": "/private/tmp",
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_compatible",
        "ANTHROPIC_API_KEY": api_key,
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_MODEL": model,
    }

    # ── Step 1: Onboarding / Help ──────────────────────────────────────
    print("Step 1: Onboarding / Help")
    try:
        proc = subprocess.run(
            [sys.executable, str(_PROJECT_ROOT / "main.py"), "--help"],
            capture_output=True, text=True, timeout=15,
            env=run_env,
        )
        help_output = proc.stdout
        has_help_content = len(help_output) > 50 and ("FakeProvider" in help_output or "Agent" in help_output)
        step1 = {
            "step": 1,
            "name": "Onboarding / Help",
            "input": "python main.py --help",
            "status": "PASS" if has_help_content else "CONCERN",
            "output_summary": help_output[:300],
            "exit_code": proc.returncode,
        }
    except Exception as exc:
        step1 = {
            "step": 1, "name": "Onboarding / Help",
            "input": "python main.py --help",
            "status": "FAIL",
            "output_summary": str(exc)[:200],
        }
    results.append(step1)
    print(f"  -> {step1['status']}")

    # ── Step 2: 普通对话（真实 LLM） ──────────────────────────────────
    print("Step 2: 普通对话 (real LLM)")
    from agent.core import chat
    from agent.display_events import RuntimeEvent
    events2: list[RuntimeEvent] = []
    def sink2(e: RuntimeEvent) -> None:
        events2.append(e)
    chat("你好，请用一句话介绍你自己", on_runtime_event=sink2)
    et2 = [e.event_type for e in events2]
    text2 = " ".join(e.text for e in events2 if e.text)
    # 真实 LLM 应返回有意义回复（不是 FakeProvider echo 模板）
    has_real_response = len(text2) > 10 and "已收到你的消息" not in text2
    has_summary = "run.summary" in et2
    step2 = {
        "step": 2,
        "name": "普通对话 (real LLM)",
        "input": "你好，请用一句话介绍你自己",
        "status": "PASS" if (has_real_response and has_summary) else "CONCERN",
        "output_summary": text2[:300],
        "event_types": et2,
        "note": f"real_response={has_real_response}, run_summary={has_summary}",
    }
    results.append(step2)
    print(f"  -> {step2['status']}: {step2['note']}")

    # ── Step 3: Real LLM 工具调用 ──────────────────────────────────────
    # real provider 是否能触发工具取决于 LLM 的 tool_use 决策，
    # 不能像 FakeProvider 那样确定性地触发。这里验证 tool pipeline
    # 对 real provider 是可用的（工具注册在 provider request 中）。
    print("Step 3: Real LLM 工具调用")
    demo_dir = _PROJECT_ROOT / "workspace" / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    before_files = set(demo_dir.rglob("note.md")) if demo_dir.exists() else set()

    events3: list[RuntimeEvent] = []
    def sink3(e: RuntimeEvent) -> None:
        events3.append(e)
    chat(
        "请帮我创建一个 demo note，内容写 'real provider dogfood test'",
        on_runtime_event=sink3,
    )
    et3 = [e.event_type for e in events3]
    text3 = " ".join(e.text for e in events3 if e.text)
    has_tool_requested = "tool.requested" in et3
    has_confirmation = "tool.confirmation_requested" in et3

    # 确认执行（如果需要）
    file_created = False
    has_tool_result = False
    if has_tool_requested and has_confirmation:
        events3b: list[RuntimeEvent] = []
        def sink3b(e: RuntimeEvent) -> None:
            events3b.append(e)
        chat("y", on_runtime_event=sink3b)
        et3b = [e.event_type for e in events3b]
        has_tool_result = "tool.result_visible" in et3b
        after_files = set(demo_dir.rglob("note.md")) if demo_dir.exists() else set()
        new_files = after_files - before_files
        file_created = len(new_files) > 0
    elif has_tool_requested and not has_confirmation:
        # tool 无需确认，可能已直接执行
        after_files = set(demo_dir.rglob("note.md")) if demo_dir.exists() else set()
        new_files = after_files - before_files
        file_created = len(new_files) > 0

    # real provider tool 调用可能不触发（取决于 LLM），标记为 CONCERN 而非 FAIL
    if has_tool_requested and file_created:
        status3 = "PASS"
    elif has_tool_requested:
        status3 = "CONCERN"
    else:
        # LLM 可能用文本描述代替工具调用，这是 real LLM 的正常行为
        status3 = "CONCERN"

    step3 = {
        "step": 3,
        "name": "Real LLM 工具调用",
        "input": "请帮我创建一个 demo note",
        "status": status3,
        "output_summary": text3[:300],
        "tool_requested": has_tool_requested,
        "confirmation_requested": has_confirmation,
        "file_created": file_created,
        "event_types": et3,
        "note": f"tool_requested={has_tool_requested}, confirm={has_confirmation}, tool_result={has_tool_result}, file={file_created} | real LLM 工具选择取决于模型",
    }
    results.append(step3)
    print(f"  -> {step3['status']}: {step3['note']}")

    # ── Step 4: CLI 命令（show memories） ──────────────────────────────
    # CLI 命令由 core.chat() 的 detect_* 函数处理，不经过 LLM。
    # 验证 real provider 路径下 CLI 命令仍然工作。
    print("Step 4: CLI show memories (real provider)")
    events4: list[RuntimeEvent] = []
    def sink4(e: RuntimeEvent) -> None:
        events4.append(e)
    output4 = chat("show memories", on_runtime_event=sink4)
    has_memory_keywords = any(kw in output4 for kw in ("记忆", "暂无", "已保存", "memories"))
    step4 = {
        "step": 4,
        "name": "CLI show memories",
        "input": "show memories",
        "status": "PASS" if has_memory_keywords else "CONCERN",
        "output_summary": output4[:300],
    }
    results.append(step4)
    print(f"  -> {step4['status']}")

    # ── Step 5: CLI show subagents ─────────────────────────────────────
    print("Step 5: CLI show subagents (real provider)")
    events5: list[RuntimeEvent] = []
    def sink5(e: RuntimeEvent) -> None:
        events5.append(e)
    output5 = chat("show subagents", on_runtime_event=sink5)
    has_demo_stat = "demo-stat" in output5.lower()
    has_code_reviewer = "code-reviewer" in output5.lower()
    step5 = {
        "step": 5,
        "name": "CLI show subagents",
        "input": "show subagents",
        "status": "PASS" if (has_demo_stat and has_code_reviewer) else "CONCERN",
        "output_summary": output5[:300],
    }
    results.append(step5)
    print(f"  -> {step5['status']}")

    # ── Step 6: CLI 委托子代理 ─────────────────────────────────────────
    print("Step 6: CLI delegate subagent (real provider)")
    events6: list[RuntimeEvent] = []
    def sink6(e: RuntimeEvent) -> None:
        events6.append(e)
    output6 = chat(
        "delegate to demo-stat: count files in workspace",
        on_runtime_event=sink6,
    )
    et6 = [e.event_type for e in events6]
    has_delegating = "subagent.delegating" in et6
    has_delegated = "subagent.delegated" in et6
    step6 = {
        "step": 6,
        "name": "CLI delegate subagent",
        "input": "delegate to demo-stat: count files in workspace",
        "status": "PASS" if (has_delegating and has_delegated) else "CONCERN",
        "output_summary": output6[:300],
        "note": f"delegating={has_delegating}, delegated={has_delegated}",
    }
    results.append(step6)
    print(f"  -> {step6['status']}: {step6['note']}")

    # ── 汇总 ──────────────────────────────────────────────────────────
    print("=" * 60)
    print("Real Provider Dogfood 结果矩阵")
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

    print("\n--- JSON ---")
    print(json.dumps(results, ensure_ascii=False, indent=2))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

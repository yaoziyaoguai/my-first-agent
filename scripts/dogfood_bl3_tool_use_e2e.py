"""Big Loop 3: Real Provider Tool-Use E2E through core.chat / Tool Pipeline.

验证完整链路：real provider → core.chat/loop.py → tool_use → Tool Pipeline →
tool result → user-visible output → run summary/trace.

Coverage:
A. Explicit tool-use prompt（明确要求调用工具）
B. Natural tool-use prompt（自然语言可能触发工具）
C. Tool non-use control（普通闲聊不应调用工具）
D. Error/unsupported behavior（不支持的场景）

Provider-agnostic: 不硬解析普通文本为 tool_use，不写 provider-specific hack。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

REPORT_PATH = PROJECT_ROOT / "docs" / "dogfood" / "real-provider-dogfood-report.md"
E2E_JSON_PATH = PROJECT_ROOT / "docs" / "dogfood" / "real-provider-e2e-report.json"

# ═══════════════════════════════════════════════════════════
# Phase 1: 隔离外层 env vars → 加载 .env
# ═══════════════════════════════════════════════════════════
_CONFLICTING = [
    "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_API_KEY",
    "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY",
]
_SAVED = {}
for _v in _CONFLICTING:
    _val = os.environ.pop(_v, None)
    if _val is not None:
        _SAVED[_v] = _val

from config import load_legacy_dotenv_config  # noqa: E402
load_legacy_dotenv_config()
os.environ["MY_FIRST_AGENT_LLM_PROVIDER"] = "anthropic_compatible"

from agent.provider.config import load_agent_provider_config  # noqa: E402
from agent.provider.factory import build_model_provider  # noqa: E402
from agent.core import chat as core_chat  # noqa: E402
from agent.runtime_integration import (  # noqa: E402
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import RuntimeActionModuleObserver  # noqa: E402
from agent.runtime_integration.tool_gate import ToolGateHandler  # noqa: E402
from agent.runtime_integration.tool_invoke import ToolInvokeHandler  # noqa: E402
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler  # noqa: E402
import agent.tools  # noqa: E402, F401 - 触发 @register_tool

config = load_agent_provider_config()
provider = build_model_provider(config)

# 构建 RuntimeActionDispatcher 以激活 Tool Pipeline
registry = ActionHandlerRegistry()
registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
dispatcher = RuntimeActionDispatcher(
    registry=registry, observer=RuntimeActionModuleObserver()
)


def run_chat(prompt: str) -> dict:
    """跑一次 core.chat 并收集 runtime events 和文本输出。"""
    runtime_events = []
    all_text = []

    def collect_event(event):
        runtime_events.append(event)
        text = getattr(event, "text", None)
        if text:
            all_text.append(text)
            print(text, end="", flush=True)
        de = getattr(event, "display_event", None)
        if de is not None:
            body = getattr(de, "body", "") or ""
            if body:
                print(f"\n{body}", flush=True)

    error = None
    result = None
    try:
        result = core_chat(
            prompt,
            on_runtime_event=collect_event,
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
    except Exception as exc:
        error = exc

    combined = "".join(all_text)
    event_types = [getattr(e, "event_type", type(e).__name__) for e in runtime_events]

    # 检查是否有工具相关事件
    has_tool_requested = any("tool.requested" == et for et in event_types)
    has_tool_started = any("tool.started" == et for et in event_types)
    has_tool_completed = any("tool.completed" == et for et in event_types)
    has_tool_failed = any("tool.failed" == et for et in event_types)
    has_tool_rejected = any("tool.rejected" == et for et in event_types)
    has_tool_result = any("tool.result" in et for et in event_types)

    has_any_tool_event = (
        has_tool_requested or has_tool_started or has_tool_completed
        or has_tool_failed or has_tool_rejected or has_tool_result
    )

    return {
        "prompt": prompt,
        "error": str(error) if error else None,
        "result_type": type(result).__name__ if result is not None else None,
        "combined_text": combined,
        "event_types": event_types,
        "runtime_events_count": len(runtime_events),
        "has_tool_requested": has_tool_requested,
        "has_tool_started": has_tool_started,
        "has_tool_completed": has_tool_completed,
        "has_tool_failed": has_tool_failed,
        "has_tool_rejected": has_tool_rejected,
        "has_tool_result": has_tool_result,
        "has_any_tool_event": has_any_tool_event,
        "action_log": getattr(dispatcher, "action_log", []) if hasattr(dispatcher, "action_log") else [],
    }


print("=" * 64)
print("Big Loop 3: Real Provider Tool-Use E2E")
print("=" * 64)
print(f"  provider: {config.provider_type}")
print(f"  model: {config.model}")
print()

results = []

# ── A: Explicit tool-use prompt ──────────────────────────────────
print("--- A: Explicit tool-use prompt ---")
print('  Prompt: "请使用已注册的 demo 工具总结这个任务。如果工具可用，请调用工具，不要只用文字回答。"')
print()

result_a = run_chat(
    "请使用已注册的 demo 工具总结这个任务。如果工具可用，请调用工具，不要只用文字回答。"
)
results.append(("A: explicit_tool_use", result_a))

print()
if result_a["has_any_tool_event"]:
    print(f"  ✅ Tool Pipeline 被触发！Events: {[e for e in result_a['event_types'] if 'tool' in e.lower()]}")
else:
    print("  ⚠️  模型未返回 tool_use（可能 provider/kimi-k2.5 不在 text+tool 双模态下发 tool_use）")
    print(f"  Response preview: {result_a['combined_text'][:200]}")

# ── B: Natural tool-use prompt ──────────────────────────────────
print()
print("--- B: Natural tool-use prompt ---")
print('  Prompt: "帮我创建一个 demo note，内容是今天验证 real provider tool use。"')
print()

result_b = run_chat(
    "帮我创建一个 demo note，内容是今天验证 real provider tool use。"
)
results.append(("B: natural_tool_use", result_b))

print()
if result_b["has_any_tool_event"]:
    print(f"  ✅ Natural prompt 触发了 Tool Pipeline！Events: {[e for e in result_b['event_types'] if 'tool' in e.lower()]}")
else:
    print("  ⚠️  Natural prompt 未触发工具（prompt sensitivity note）")
    print(f"  Response preview: {result_b['combined_text'][:200]}")

# ── C: Tool non-use control ─────────────────────────────────────
print()
print("--- C: Tool non-use control ---")
print('  Prompt: "你好，今天天气怎么样？"')
print()

result_c = run_chat("你好，今天天气怎么样？")
results.append(("C: nonuse_control", result_c))

print()
if not result_c["has_any_tool_event"]:
    print("  ✅ 普通闲聊未触发工具（符合预期）")
else:
    print(f"  ⚠️  普通闲聊意外触发了工具：{[e for e in result_c['event_types'] if 'tool' in e.lower()]}")

# ── D: Unsure/edge prompt ───────────────────────────────────────
print()
print("--- D: Edge/unsure prompt ---")
print('  Prompt: "帮我看看当前有什么可以做的"')
print()

result_d = run_chat("帮我看看当前有什么可以做的")
results.append(("D: edge_prompt", result_d))

print()
if result_d["has_any_tool_event"]:
    print(f"  info: 模糊 prompt 触发工具：{[e for e in result_d['event_types'] if 'tool' in e.lower()]}")
else:
    print("  info: 模糊 prompt 未触发工具（模型选择文字回答）")

# ═══════════════════════════════════════════════════════════════
# Phase 4: 保存 Report
# ═══════════════════════════════════════════════════════════════
timestamp = datetime.now(timezone.utc).isoformat()

# E2E JSON
existing_e2e = {}
if E2E_JSON_PATH.exists():
    try:
        existing_e2e = json.loads(E2E_JSON_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass

bl3_results = {}
for label, r in results:
    bl3_results[label] = {
        "has_any_tool_event": r["has_any_tool_event"],
        "has_tool_requested": r["has_tool_requested"],
        "has_tool_completed": r["has_tool_completed"],
        "event_types": r["event_types"],
        "text_preview": r["combined_text"][:300],
        "error": r["error"],
    }

existing_e2e["bl3_tool_use_e2e"] = {
    "timestamp": timestamp,
    "provider": config.provider_type,
    "model": config.model,
    "results": bl3_results,
}

E2E_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(E2E_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(existing_e2e, f, ensure_ascii=False, indent=2)

# MD report
a_tool = "✅" if result_a["has_any_tool_event"] else "⚠️ 未触发"
b_tool = "✅" if result_b["has_any_tool_event"] else "⚠️ 未触发"
c_ok = "✅" if not result_c["has_any_tool_event"] else "⚠️ 意外触发"

md_update = f"""

## Big Loop 3: Real Provider Tool-Use E2E

**Timestamp:** {timestamp}
**Provider:** `{config.provider_type}` / `{config.model}`

### 结果总览

| 测试 | 预期 | 实际 | 判定 |
|------|------|------|------|
| A: Explicit tool-use | 触发 tool_use → Pipeline | {a_tool} | {a_tool} |
| B: Natural tool-use | 尽量触发 tool_use | {b_tool} | {b_tool} |
| C: Non-use control | 不触发 | {c_ok} | {c_ok} |
| D: Edge prompt | 不硬解析文本 | info | info |

### A: Explicit tool-use
```
{result_a['combined_text'][:300]}
```
Tool events: {[e for e in result_a['event_types'] if 'tool' in e.lower()]}

### B: Natural tool-use
```
{result_b['combined_text'][:300]}
```
Tool events: {[e for e in result_b['event_types'] if 'tool' in e.lower()]}

### C: Non-use control
```
{result_c['combined_text'][:200]}
```

### D: Edge prompt
```
{result_d['combined_text'][:200]}
```
"""

if REPORT_PATH.exists():
    with open(REPORT_PATH, "a", encoding="utf-8") as f:
        f.write(md_update)

# ═══════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════
for _v, _val in _SAVED.items():
    os.environ[_v] = _val

print()
print("=" * 64)
print("Big Loop 3 complete — report updated")
print("=" * 64)
sys.exit(0)

"""Big Loop 1 Phase 2: Real Provider Baseline through core.chat / loop.py.

验证真 provider 不仅能在 direct provider.create() 下工作，也能通过
core.chat → loop.py → call_model → provider 这条统一主流程工作。

严格边界：
- 读取项目 .env，不打印完整 secret
- safe demo prompts only
- 不修改主 runtime
- 不读取真实 sessions/runs
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
# Phase 1: 隔离外层 Claude Code env vars → 加载 .env
# ═══════════════════════════════════════════════════════════
_CONFLICTING_ENV_VARS = [
    "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_API_KEY",
    "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY",
]
_SAVED_ENV = {}
for _var in _CONFLICTING_ENV_VARS:
    _val = os.environ.pop(_var, None)
    if _val is not None:
        _SAVED_ENV[_var] = _val

from config import load_legacy_dotenv_config  # noqa: E402
load_legacy_dotenv_config()

# 设置 First Agent 专用 provider type
os.environ["MY_FIRST_AGENT_LLM_PROVIDER"] = "anthropic_compatible"

# ═══════════════════════════════════════════════════════════
# Phase 2: 构建 provider 并通过 core.chat 调用
# ═══════════════════════════════════════════════════════════
from agent.provider.config import load_agent_provider_config  # noqa: E402
from agent.provider.factory import build_model_provider  # noqa: E402
from agent.core import chat as core_chat  # noqa: E402

config = load_agent_provider_config()
provider = build_model_provider(config)

print("=" * 64)
print("Big Loop 1 Phase 2: core.chat/loop.py Baseline")
print("=" * 64)
print(f"  provider: {config.provider_type}")
print(f"  model: {config.model}")
print(f"  base_url: {config.base_url}")
print()

# 收集 RuntimeEvent 和输出文本。
# 当 on_runtime_event 和 on_output_chunk 同时传入时，core.chat 优先走
# on_runtime_event 路径，on_output_chunk 不会被调用（兼容层设计）。
runtime_events = []
# 从 runtime events 中提取的文本
all_text = []


def collect_runtime_event(event):
    runtime_events.append(event)
    # assistant.delta 事件携带模型输出的文本片段
    text = getattr(event, "text", None)
    if text:
        all_text.append(text)
        print(text, end="", flush=True)
    # display_event 也可能包含文本
    de = getattr(event, "display_event", None)
    if de is not None:
        body = getattr(de, "body", "") or ""
        if body:
            print(f"\n{body}", flush=True)


print("--- core.chat() with real provider ---")
print("Prompt: 你好，请用一句话介绍你自己。不要调用任何工具。")
print()

timed_out = False
chat_error = None

try:
    result = core_chat(
        "你好，请用一句话介绍你自己。不要调用任何工具。",
        on_runtime_event=collect_runtime_event,
        provider=provider,
    )
except Exception as exc:
    chat_error = exc
    result = None

print()
print()

# ═══════════════════════════════════════════════════════════
# Phase 3: 分析结果
# ═══════════════════════════════════════════════════════════
combined_text = "".join(all_text)
success = chat_error is None and bool(combined_text.strip())
timestamp = datetime.now(timezone.utc).isoformat()

print("--- Results ---")
if chat_error:
    print(f"  ❌ core.chat FAILED: {type(chat_error).__name__}: {chat_error}")
else:
    print("  ✅ core.chat SUCCESS")
    print(f"  Text fragments: {len(all_text)}")
    print(f"  Runtime events: {len(runtime_events)}")
    print(f"  Combined output: {combined_text[:200]}")

    # 检查 runtime events 类型
    event_types = [getattr(e, "event_type", type(e).__name__) for e in runtime_events]
    print(f"  Event types: {event_types[:20]}")

# ═══════════════════════════════════════════════════════════
# Phase 4: 更新 report
# ═══════════════════════════════════════════════════════════

# 读取已有的 E2E JSON
existing_e2e = {}
if E2E_JSON_PATH.exists():
    try:
        existing_e2e = json.loads(E2E_JSON_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass

existing_e2e["bl1_phase2"] = {
    "timestamp": timestamp,
    "success": success,
    "core_chat": {
        "success": chat_error is None,
        "text_fragments_count": len(all_text),
        "output_preview": combined_text[:200] if all_text else None,
        "runtime_events_count": len(runtime_events),
        "error": str(chat_error) if chat_error else None,
    },
}

E2E_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(E2E_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(existing_e2e, f, ensure_ascii=False, indent=2)

# 更新 MD report
md_update = f"""

## Big Loop 1 Phase 2: core.chat/loop.py Baseline

**Timestamp:** {timestamp}
**Result:** {"✅ SUCCESS" if success else "❌ FAILED"}

| Field | Value |
|-------|-------|
| provider | `{config.provider_type}` |
| model | `{config.model}` |
| output text fragments | {len(all_text)} |
| runtime events | {len(runtime_events)} |
"""
if chat_error:
    md_update += f"\n**Error:** `{type(chat_error).__name__}: {chat_error}`\n"
else:
    md_update += f"""
**Output:**
```
{combined_text[:300]}
```
"""

if REPORT_PATH.exists():
    with open(REPORT_PATH, "a", encoding="utf-8") as f:
        f.write(md_update)

# ═══════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════
for _var, _val in _SAVED_ENV.items():
    os.environ[_var] = _val

if success:
    print()
    print("=" * 64)
    print("Big Loop 1 Phase 2 PASSED")
    print("=" * 64)
    sys.exit(0)
else:
    print()
    print("=" * 64)
    print("Big Loop 1 Phase 2 FAILED")
    print("=" * 64)
    sys.exit(1)

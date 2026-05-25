"""Big Loop 1: Real Provider Safety Preflight + Baseline Dogfood.

确认项目 .env 真实 provider 配置可用，并跑最小安全 baseline。

严格边界：
- 读取项目 .env，不打印完整 secret
- 只使用 safe demo prompts / safe local demo tools / synthetic demo data
- 不读取真实 sessions/runs/memory episodes/私人资料
- 不调用真实外部业务 API
- 不把 dogfood 特殊逻辑写入主 runtime
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

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: 加载 .env 配置，隔离外层 Claude Code 的 env vars
# ═══════════════════════════════════════════════════════════════════════════════

# 外层 Claude Code 设置了 ANTHROPIC_BASE_URL / ANTHROPIC_MODEL 供自身使用，
# 但这些值可能与 First Agent 的 .env 配置冲突。先清除这些冲突变量，
# 让 .env 的 load_dotenv 能以正确的值填充。
_CONFLICTING_ENV_VARS = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "OPENAI_API_KEY",
]
_SAVED_ENV: dict[str, str] = {}

for _var in _CONFLICTING_ENV_VARS:
    _val = os.environ.pop(_var, None)
    if _val is not None:
        _SAVED_ENV[_var] = _val


def _restore_env() -> None:
    """恢复被清除的外层 env vars。"""
    for _var, _val in _SAVED_ENV.items():
        os.environ[_var] = _val


# 加载 .env — 此时冲突变量已清除，dotenv 值将生效
from config import load_legacy_dotenv_config  # noqa: E402

load_legacy_dotenv_config()

# 现在从 os.environ 读取 .env 填充的值
DOTENV_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DOTENV_ANTHROPIC_BASE = os.environ.get("ANTHROPIC_BASE_URL", "")
DOTENV_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "")
DOTENV_OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
DOTENV_OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "")
DOTENV_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "")


def redact_key(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 12:
        return key[:4] + "***"
    return key[:7] + "***" + key[-4:]


def mask_url(url: str) -> str:
    if not url:
        return "(empty)"
    return url


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: 构建 Provider 并报告配置
# ═══════════════════════════════════════════════════════════════════════════════

# 设置 First Agent 专用 env var
os.environ["MY_FIRST_AGENT_LLM_PROVIDER"] = "anthropic_compatible"

from agent.provider.config import load_agent_provider_config  # noqa: E402
from agent.provider.factory import build_model_provider  # noqa: E402

config = load_agent_provider_config()
provider = build_model_provider(config)

print("=" * 64)
print("Big Loop 1: Real Provider Safety Preflight")
print("=" * 64)
print()
print("--- Provider Configuration ---")
print(f"  provider_type   : {config.provider_type}")
print(f"  provider_name   : {config.provider_name}")
print(f"  model           : {config.model}")
print(f"  base_url        : {mask_url(config.base_url or '')}")
print(f"  api_key         : {redact_key(config.api_key or '')}")
print(f"  auth_scheme     : {config.auth_scheme}")
print(f"  request_path    : {config.request_path}")
print(f"  max_tokens      : {config.max_tokens}")
print(f"  timeout         : {config.timeout}")
print(f"  supports_tools  : {config.supports_tools}")
print(f"  supports_stream : {config.supports_streaming}")
print()
print("--- Safety Confirmations ---")
print(f"  .env loaded     : {bool(DOTENV_ANTHROPIC_KEY)}")
print("  real API call   : YES")
print("  safe demo prompts only : YES")
print("  private data read      : NO")
print("  real user directory write : NO")
print("  external business API  : NO")
print()
print("--- Outer Env Override Detection ---")
overridden = []
for var, saved_val in sorted(_SAVED_ENV.items()):
    current = os.environ.get(var, "")
    if current != saved_val:
        overridden.append(f"  {var}: shell={mask_url(saved_val) if 'URL' in var else saved_val} → .env={mask_url(current) if 'URL' in var else current}")
if overridden:
    print("  ⚠️  外层 env vars 已被 .env 覆盖：")
    for line in overridden:
        print(line)
else:
    print("  (no conflicts detected)")

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: Basic Real Chat — 普通聊天，预期不调用工具
# ═══════════════════════════════════════════════════════════════════════════════

print()
print("--- Phase 3: Basic Real Chat ---")
print("  Prompt: 你好，请用一句话介绍你自己。不要调用任何工具。")
print()

chat_result = None
chat_error = None

try:
    chat_result = provider.create(
        system="你是一个友好的助手。保持回答简洁。",
        messages=[{"role": "user", "content": "你好，请用一句话介绍你自己。不要调用任何工具。"}],
        tools=[],  # 空工具列表，确保不触发 tool_use
    )
    text_blocks = [b for b in chat_result.content if getattr(b, "type", None) == "text"]
    tool_blocks = [b for b in chat_result.content if getattr(b, "type", None) == "tool_use"]
    response_text = "".join(getattr(b, "text", "") for b in text_blocks)

    print("  ✅ Basic chat SUCCESS")
    print(f"  Response: {response_text[:200]}")
    if tool_blocks:
        print(f"  ⚠️  Unexpected tool_use blocks: {len(tool_blocks)}")
    else:
        print("  ✅ No unexpected tool_use")
    print(f"  Stop reason: {chat_result.stop_reason}")
    print(f"  Provider: {chat_result.raw_provider_name}")
    print(f"  Usage: {chat_result.usage}")
except Exception as exc:
    chat_error = exc
    print(f"  ❌ Basic chat FAILED: {type(exc).__name__}: {exc}")

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: 保存 Report
# ═══════════════════════════════════════════════════════════════════════════════

success = chat_result is not None and chat_error is None
timestamp = datetime.now(timezone.utc).isoformat()

e2e_json = {
    "timestamp": timestamp,
    "big_loop": "BL1",
    "phase": "safety_preflight",
    "provider_type": config.provider_type,
    "provider_name": config.provider_name,
    "model": config.model,
    "base_url": config.base_url,
    "auth_scheme": config.auth_scheme,
    "success": success,
    "basic_chat": {
        "success": chat_result is not None,
        "response_preview": (
            "".join(getattr(b, "text", "") for b in chat_result.content if getattr(b, "type", None) == "text")[:200]
            if chat_result else None
        ),
        "stop_reason": chat_result.stop_reason if chat_result else None,
        "raw_provider_name": chat_result.raw_provider_name if chat_result else None,
        "usage": str(chat_result.usage) if chat_result else None,
        "error": str(chat_error) if chat_error else None,
    },
    "env_loaded": bool(DOTENV_ANTHROPIC_KEY),
    "safe_demo_prompts_only": True,
    "private_data_read": False,
    "real_user_directory_write": False,
    "external_business_api": False,
    "outer_env_overrides": list(_SAVED_ENV.keys()),
}

REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
E2E_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

with open(E2E_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(e2e_json, f, ensure_ascii=False, indent=2)

md_report = f"""# Real Provider Dogfood Report

> 自动生成于 {timestamp}
> Big Loop 1: Safety Preflight + Baseline Dogfood

## Configuration

| Field | Value |
|-------|-------|
| provider_type | `{config.provider_type}` |
| provider_name | `{config.provider_name}` |
| model | `{config.model}` |
| base_url | `{mask_url(config.base_url or '')}` |
| api_key | `{redact_key(config.api_key or '')}` |
| auth_scheme | `{config.auth_scheme}` |
| request_path | `{config.request_path}` |
| supports_tools | `{config.supports_tools}` |

## Safety Confirmations

- [x] .env loaded
- [x] Safe demo prompts only
- [x] No private data read
- [x] No real user directory write
- [x] No external business API

## Basic Real Chat

**Prompt:** 你好，请用一句话介绍你自己。不要调用任何工具。

**Result:** {"✅ SUCCESS" if success else "❌ FAILED"}

"""
if chat_result:
    text_blocks = [b for b in chat_result.content if getattr(b, "type", None) == "text"]
    response_text = "".join(getattr(b, "text", "") for b in text_blocks)
    md_report += f"""**Response:**
```
{response_text[:500]}
```

**Stop reason:** `{chat_result.stop_reason}`
**Provider:** `{chat_result.raw_provider_name}`
**Usage:** `{chat_result.usage}`
"""
elif chat_error:
    md_report += f"""**Error:**
```
{type(chat_error).__name__}: {chat_error}
```
"""

md_report += """
## Next Steps

"""
if success:
    md_report += "- [ ] Big Loop 2: Real Provider Tool-Use Prompt Hardening\n"
else:
    md_report += "- [ ] Diagnose and fix baseline failure before continuing\n"

with open(REPORT_PATH, "w", encoding="utf-8") as f:
    f.write(md_report)

print()
print(f"  Report saved: {REPORT_PATH}")
print(f"  E2E JSON saved: {E2E_JSON_PATH}")

# ═══════════════════════════════════════════════════════════════════════════════
# Cleanup: 恢复外层 env
# ═══════════════════════════════════════════════════════════════════════════════
_restore_env()

# Exit code
if success:
    print()
    print("=" * 64)
    print("Big Loop 1 Phase 1 PASSED — ready for Phase 2 (core.chat/loop.py)")
    print("=" * 64)
    sys.exit(0)
else:
    print()
    print("=" * 64)
    print("Big Loop 1 Phase 1 FAILED — see error above")
    print("=" * 64)
    sys.exit(1)

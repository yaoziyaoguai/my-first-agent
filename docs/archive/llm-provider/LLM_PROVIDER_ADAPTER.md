# LLM Provider Adapter

This document records the AgentLoop provider adapter foundation. It is separate
from the older `llm/` processing MVP provider layer.

## Current Status

| Provider type | Status | Notes |
|---|---|---|
| `anthropic_native` | Implemented provider adapter | Official Anthropic SDK usage is contained inside `agent/provider/anthropic_native.py`; AgentLoop calls it through `ModelProvider.stream()` / provider factory, not through `core.py` SDK code. |
| `anthropic_compatible` | Implemented vertical slice | Uses HTTP, custom `base_url`, configurable `request_path`, and `auto` / `bearer` / `x-api-key` auth. |
| `openai_compatible` | Implemented vertical slice | Uses HTTP, OpenAI Chat Completions format, Anthropic→OpenAI message/tools conversion, `tool_calls` normalization. |
| `openai_native` | Implemented minimal Chat Completions adapter | Uses HTTP, default `https://api.openai.com`, `Bearer` auth, `tool_calls` normalization. No streaming, no Responses API. |

## Configuration

Configuration is read from process environment only. Do not store real API keys
in repo files, tests, docs, checkpoints, messages, or logs.

### Anthropic-compatible

```bash
export MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible
export ANTHROPIC_API_KEY=...
export ANTHROPIC_BASE_URL=https://provider.example
export ANTHROPIC_MODEL=provider-model

# Optional defaults:
export MY_FIRST_AGENT_LLM_REQUEST_PATH=/v1/messages
export MY_FIRST_AGENT_LLM_AUTH_SCHEME=auto      # auto | bearer | x-api-key
export MY_FIRST_AGENT_LLM_MAX_TOKENS=4096
export MY_FIRST_AGENT_LLM_TIMEOUT=30
```

### OpenAI-compatible

```bash
export MY_FIRST_AGENT_LLM_PROVIDER=openai_compatible
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com   # or custom endpoint
export OPENAI_MODEL=gpt-4o                       # or DeepSeek model etc.

# Optional defaults:
export MY_FIRST_AGENT_LLM_REQUEST_PATH=/v1/chat/completions
export MY_FIRST_AGENT_LLM_AUTH_SCHEME=bearer
export MY_FIRST_AGENT_LLM_MAX_TOKENS=4096
export MY_FIRST_AGENT_LLM_TIMEOUT=30
```

`MY_FIRST_AGENT_LLM_AUTH_SCHEME` accepts:

- For Anthropic-compatible: `auto` (defaults to `x-api-key`), `bearer`, `x-api-key`.
- For OpenAI-compatible: `bearer` only.

`MY_FIRST_AGENT_LLM_REQUEST_PATH` can be empty or a provider-specific path.
The adapter joins it with the base URL without double slashes and never puts
the key into the URL.

## Tool Schema Conversion

Internal tool definitions use Anthropic format:
```json
{"name": "...", "description": "...", "input_schema": {...}}
```

For OpenAI-compatible calls, `convert_tools_to_openai()` maps them to:
```json
{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
```

For Anthropic-compatible calls, no conversion is needed.

## Message Format Conversion

AgentLoop stores messages in Anthropic format. For OpenAI-compatible calls,
`convert_messages_to_openai()` handles:

- System prompt → `{"role": "system", "content": "..."}` message
- User text → `{"role": "user", "content": "..."}`
- Assistant tool_use → `{"role": "assistant", "tool_calls": [...]}`
- User tool_result → `{"role": "tool", "tool_call_id": "...", "content": "..."}`

## Error Classification

The provider layer raises safe errors:

- `ProviderAuthError`: 401 / 403 or missing auth.
- `ProviderTimeoutError`: HTTP timeout.
- `ProviderResponseError`: malformed JSON, malformed response shape, no choices,
  tool_call missing name, or other HTTP failures.
- `ProviderCapabilityError`: selected provider cannot support requested
  capability.
- `ProviderNotImplementedError`: registered but unfinished provider type.

Errors do not include API keys, request bodies, response bodies, or headers.

## MCP Relationship

MCP remains the tool source. The provider adapter only calls the model.

- MCP registration still goes through MCP policy, sanitizer, and audit.
- Tool exposure still goes through `get_model_visible_tools`.
- The provider receives only the already-filtered model-visible tool schemas.
- Tool execution still goes through the existing confirmation gate and
  `tool_executor`.
- `tool_executor` is provider-agnostic — it works with `ToolUseBlock` from any
  provider.

## Streaming Support

| Provider | Streaming | Notes |
|---|---|---|
| `anthropic_native` | Yes | Provider adapter converts Anthropic SDK stream events into provider-neutral `ProviderStreamEvent` values. |
| `anthropic_compatible` | No | Non-streaming `create()` via HTTP adapter |
| `openai_compatible` | No | Non-streaming `create()` via HTTP adapter; direct `stream()` calls fail closed with `ProviderCapabilityError("streaming_not_supported")` |
| `openai_native` | No | Non-streaming `create()` via HTTP adapter |

`core.py._call_model` checks `supports_streaming` on the provider. If false,
it calls `provider.create()` and emits text blocks as RuntimeEvents.
Callers that require true streaming must inspect `supports_streaming`; they must
not assume `openai_compatible` can stream or silently fall back.

## Opt-in Real Smoke

Real smoke tests call a real provider. They are skipped by default. To run them:

1. Set the explicit opt-in flag: `export MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1`
2. Ensure real (not fake) `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, and
   `ANTHROPIC_MODEL` are present.
3. The gate rejects known fake placeholders (test-key, sk-test-*, etc.)

Run these only when the environment is already configured. They never print key
values.

### Anthropic-compatible

```bash
MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1 \
MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible \
.venv/bin/python -m pytest tests/test_provider_real_smoke.py -v -s
```

Tests cover:

- `test_real_anthropic_compatible_minimal_text_smoke` — basic text round-trip
- `test_real_anthropic_compatible_accepts_model_visible_tools_param` — tools
  parameter accepted and response parsed
- `test_real_anthropic_compatible_mcp_readonly_e2e` — provider adapter +
  `tool_executor` manual round-trip through MCP tool registration, model tool
  selection, tool execution, tool_result append, and second provider call.
  (This is a provider-adapter-level round-trip, not a full AgentLoop
  `core.py`/`chat()`/`response_handlers` automatic loop.)

### OpenAI-compatible (not yet in test file; requires env vars)

```bash
MY_FIRST_AGENT_LLM_PROVIDER=openai_compatible \
.venv/bin/python -c "
from agent.provider.config import load_agent_provider_config
from agent.provider.factory import build_model_provider
config = load_agent_provider_config()
provider = build_model_provider(config)
response = provider.create(
    system='You are a test assistant.',
    messages=[{'role': 'user', 'content': 'Reply: provider-ok'}],
    tools=[],
)
print('stop_reason:', response.stop_reason)
print('text:', response.content[0].text if response.content else '(empty)')
"
```

If a smoke fails, classify by the first safe signal:

- auth: 401 / 403, missing or wrong `auth_scheme`.
- base_url/path: 404 or provider-specific route error.
- model: provider says model is missing or unknown.
- response format: HTTP succeeds but body shape is wrong.
- unsupported tools: provider rejects `tools` parameter.

Do not hard-code provider-specific paths or auth rules to make a smoke pass.

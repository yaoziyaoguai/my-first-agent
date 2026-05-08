# LLM Provider Adapter

This document records the AgentLoop provider adapter foundation. It is separate
from the older `llm/` processing MVP provider layer.

## Current Status

| Provider type | Status | Notes |
|---|---|---|
| `anthropic_native` | Implemented as legacy streaming path + wrapper | AgentLoop default keeps `core.py` streaming via official Anthropic SDK. The wrapper normalizes non-streaming `messages.create()` responses for future migration. |
| `anthropic_compatible` | Implemented vertical slice | Uses HTTP, custom `base_url`, configurable `request_path`, and `auto` / `bearer` / `x-api-key` auth. |
| `openai_native` | Registered, not implemented | Selecting it raises an explicit provider not-implemented error. |
| `openai_compatible` | Registered, not implemented | Selecting it raises an explicit provider not-implemented error. |

## Configuration

Configuration is read from process environment only. Do not store real API keys
in repo files, tests, docs, checkpoints, messages, or logs.

```bash
export MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible
export ANTHROPIC_API_KEY=...
export ANTHROPIC_BASE_URL=https://provider.example
export ANTHROPIC_MODEL=provider-model

# Optional defaults:
export MY_FIRST_AGENT_LLM_REQUEST_PATH=/v1/messages
export MY_FIRST_AGENT_LLM_AUTH_SCHEME=auto
export MY_FIRST_AGENT_LLM_MAX_TOKENS=4096
export MY_FIRST_AGENT_LLM_TIMEOUT=30
```

`MY_FIRST_AGENT_LLM_AUTH_SCHEME` accepts:

- `auto`: compatible provider currently sends `Authorization: Bearer ...`.
- `bearer`: explicit bearer token header.
- `x-api-key`: Anthropic-style key header plus `anthropic-version`.

`MY_FIRST_AGENT_LLM_REQUEST_PATH` can be empty, `/v1/messages`, or a provider
specific path. The adapter joins it with `ANTHROPIC_BASE_URL` without adding
double slashes and never puts the key into the URL.

## Error Classification

The provider layer raises safe errors:

- `ProviderAuthError`: 401 / 403 or missing auth.
- `ProviderTimeoutError`: HTTP timeout.
- `ProviderResponseError`: malformed JSON, malformed response shape, or other
  HTTP failures.
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

## Opt-in Real Smoke

Run this only when the environment is already configured. The command must not
print key values.

```bash
MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible \
.venv/bin/python -m pytest tests/test_provider_real_smoke.py -q -s
```

If the smoke fails, classify it by the first safe signal:

- auth: 401 / 403, missing or wrong `auth_scheme`.
- base_url/path: 404 or provider-specific route error.
- model: provider says model is missing or unknown.
- response format: HTTP succeeds but the body is not Anthropic Messages-style.
- unsupported tools: provider accepts no `tools` parameter or ignores tool
  schemas.

Do not hard-code provider-specific paths or auth rules to make a smoke pass.

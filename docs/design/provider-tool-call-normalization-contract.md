# Provider Tool-Call Normalization Contract

- **Date:** 2026-05-26
- **Status:** active
- **Source:** Industry Capability Gap Audit §J Loop 3

## 1. 问题

不同 provider（Anthropic Native、Anthropic Compatible、OpenAI Native、OpenAI Compatible）的 tool-call 格式不同：

| Provider | Block type | Tool name field | Tool input format | Call ID field |
|---|---|---|---|---|
| Anthropic | `content[*].type == "tool_use"` | `block.name` | dict (native) | `block.id` |
| OpenAI | `choices[0].message.tool_calls[*]` | `tc.function.name` | JSON string | `tc.id` |

Tool Pipeline、confirmation、audit、dispatcher 不应感知 provider-specific 格式。这道屏障由 normalization 层承担。

## 2. Internal Normalized Shape

所有 provider response 经过 normalization 后，Tool Pipeline 只看到一种 shape：

```python
ToolUseBlock(
    id: str,           # 来自 provider 的 call_id（为空时用空字符串）
    name: str,          # 纯工具名（已去命名空间前缀，如 mcp__server__tool → tool）
    input: dict,        # 工具参数（已从 JSON string 解析，始终为 dict）
)
```

`name` 不做 prefix strip——namespace 保留给 ToolRegistry 路由决策。

## 3. Provider Adapter 职责

每个 provider adapter 的 `create()` 方法负责：

1. **构造请求**：将内部消息格式转为 provider-specific API payload
2. **发送请求**：调用 provider SDK/HTTP
3. **Normalize 响应**：调用对应 normalize 函数，产出 `ProviderResponse`

Tool Pipeline 不感知 `create()` 内部的 provider 差异。

## 4. Normalization 函数

### 4.1 Anthropic Messages 格式

`agent/provider/normalize.py::normalize_anthropic_response(raw, *, raw_provider_name)`

输入：Anthropic SDK response object 或 dict（兼容兼容端点）

处理：
- `content[*].type == "text"` → `ProviderTextBlock`
- `content[*].type == "tool_use"` → `ToolUseBlock`
- `tool_use.input` 为 dict（原生），直接保留
- `tool_use.input` 为 JSON string 时尝试解析，失败返回 `{}`
- 非 dict 且非 JSON string 的 input → `{}`

### 4.2 OpenAI Chat Completions 格式

`agent/provider/openai_http.py::normalize_openai_response(raw, *, raw_provider_name)`

输入：OpenAI API response dict

处理：
- `choices[0].message.content` → `ProviderTextBlock`
- `choices[0].message.tool_calls[*]` → `ToolUseBlock`
- `function.arguments` 为 JSON string，必须解析为 dict
- JSON 解析失败 → `{}`（安全回退）
- 缺失 `function.name` → `ProviderResponseError("tool_call_missing_name")`
- `finish_reason` 映射：stop→end_turn, tool_calls→tool_use, length→max_tokens
- `usage.prompt_tokens` → `input_tokens`, `completion_tokens` → `output_tokens`

## 5. 合同不变量（Contract Invariants）

以下不变量适用于所有 provider adapter：

1. **ToolUseBlock 始终是 frozen dataclass** — 不可变，线程安全
2. **`input` 始终是 dict** — 不可能是 None、str、list
3. **`name` 始终是 str** — 不可能是 None
4. **`id` 始终是 str** — 不可能是 None（缺失时用空字符串）
5. **malformed JSON arguments → `{}`** — 不抛异常，不泄露原始 malformed 字符串
6. **缺失 tool name → `ProviderResponseError`** — 工具调用必须有名称
7. **ProviderResponse.content 元素顺序与原始 response 一致** — text block 和 tool_use block 按原始顺序排列
8. **usage 按统一 key 标准化** — `input_tokens`, `output_tokens`（可能还有 `cache_read_input_tokens`）

## 6. Streaming

当前 streaming 限于 text delta 聚合。Streaming 中的 tool_use 增量（Anthropic SDK 的 `content_block_start/delta/stop`）不在当前 scope——只有完整 tool_use block 才经过 normalization。

## 7. Out of Scope

- 新增 provider adapter
- 真实 API 调用
- Provider-specific 优化
- Text→tool_call 硬解析（用户消息中的伪 tool call）
- Streaming partial tool_use
- Tool name 去前缀/标准化（保留 namespace 前缀给 ToolRegistry 路由）

## 8. Test Strategy

合同测试放在 `tests/test_provider_tool_call_normalization_contract.py`，使用 fake/stub provider response objects，不调用真实 API。

覆盖：
- Anthropic tool_use → ToolUseBlock（已存在）
- OpenAI tool_calls → ToolUseBlock
- 混合 text + tool_use 顺序保留
- malformed tool input → `{}`
- 缺失 tool name → `ProviderResponseError`
- namespaced tool name 保留原样
- 空 choices → `ProviderResponseError`
- 多 tool_calls → 对应多个 ToolUseBlock

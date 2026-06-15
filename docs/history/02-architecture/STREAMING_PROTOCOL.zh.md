# Streaming Protocol

这篇文档说明 First Agent 当前的最小 streaming protocol。它不是新的网络协议，也不是 SSE/WebSocket 设计；它只定义 provider 到 runtime 的本地事件边界。

## 目标

- `agent/core.py` 不直接 import 或实例化具体 provider SDK。
- runtime 只消费 provider-neutral stream event。
- CLI/TUI 只展示 RuntimeEvent，不拥有模型调用、状态推进、checkpoint 或 confirmation 逻辑。
- checkpoint 不保存 raw token flood，只保存最终安全摘要或既有状态字段。

## Event schema

Provider streaming event 使用 `ProviderStreamEvent`：

| Field | Meaning |
|---|---|
| `event_type` | `text_delta` / `tool_request` / `final` / `error` |
| `sequence` | 单调递增序号 |
| `source` | provider 标识，不含 secret |
| `text_delta` | 已脱敏文本增量 |
| `payload` | provider-neutral 附加信息 |
| `is_final` | 是否 final event |
| `error` | fail-closed 错误摘要 |

`collect_stream_response()` 聚合 `text_delta`，并要求 sequence 单调、error fail closed、final event 存在。`tool_request` 是 provider-neutral 控制事件，用于提示 runtime/UI 模型正在请求工具；它不携带 provider SDK 原始 payload。secret-like 文本会在进入 runtime 前脱敏。

## Provider boundary

`ModelProvider` 暴露 `create(...)` 与 `stream(...)`。Anthropic native、Anthropic compatible、OpenAI native、OpenAI compatible 都通过 provider factory 构造。`core.py` 只调用 `agent.model_call.call_model(...)`，不根据 provider/model/base_url 做分支。

## Runtime and presentation

`agent/model_call.py` 把 provider stream event 聚合成 provider-neutral response，再由既有 runtime output dispatch 进入 CLI/TUI。CLI/TUI 只消费事件和渲染文本，不执行工具、不写 Memory、不改变 checkpoint。

## Safety

- stream `text_delta` 中疑似 API key / token / Authorization header 会被 redacted。
- error event 转换为 `ProviderResponseError`，不会继续执行工具。
- raw stream token 不写入 checkpoint。
- provider 选择和鉴权仍属于 `agent/provider/`，不属于 runtime loop。

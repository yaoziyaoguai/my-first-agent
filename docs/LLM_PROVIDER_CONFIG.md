# LLM Provider Config

> **本文目的**：说明 v0.2 M4/M5 的 provider 配置、preflight 和错误分类边界。
>
> **核心边界**：M4 不是完整 provider ecosystem，也不做多模型路由、成本统计或
> provider 选择策略。它只让 LLM Processing MVP 从默认 fake provider 过渡到
> 可配置、可审计、不会泄露 secret 的真实 provider 准备态。

---

## 1. 为什么先做配置和 secret 边界

真实 LLM 调用会引入 API key、base URL、模型名、请求体和响应体。如果这些边界
没有先固定，后续 process/status 很容易把 key、prompt、completion 或输入全文写进
`state.json` / `runs/*.jsonl`，让审计日志变成第二份敏感数据存储。

因此 M4 先冻结三条规则：

- fake provider 仍是默认测试路径，不需要 key。
- 真实 provider 必须显式配置，缺 key/model 时只返回可读错误，不崩溃。
- preflight / status / runs 日志只能展示白名单 metadata，不输出 key、env value、
  raw prompt、raw completion 或 provider request/response body。

## 2. Provider registry

MVP 阶段支持：

| provider | 默认 | key | model | base_url | 说明 |
|---|---:|---|---|---|---|
| `fake` | 是 | 不需要 | `LLM_FAKE_MODEL` 或默认 `fake-llm` | 不使用 | 离线测试和无 key 本地路径 |
| `anthropic` | 否 | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL` / `MODEL_NAME` / `MY_FIRST_AGENT_LLM_MODEL` | `ANTHROPIC_BASE_URL` / `MY_FIRST_AGENT_LLM_BASE_URL` | 真实 provider 准备态 |

通用 provider 选择变量：

```bash
MY_FIRST_AGENT_LLM_PROVIDER=fake
```

## 3. `.env.example`

仓库提供 `.env.example` 只展示变量名和注释，不包含真实值。真实 `.env` 已被
`.gitignore` 忽略，不应提交。

## 4. Preflight

默认 preflight 只做本地配置检查，不发真实请求：

```bash
.venv/bin/python main.py preflight
.venv/bin/python main.py preflight --provider anthropic
.venv/bin/python main.py preflight --provider anthropic --model claude-sonnet-4-5
```

输出是 JSON，字段只说明：

- provider 名称是否可识别；
- model 是否配置；
- base_url 是否配置；真实 provider 未配置 base_url 时给出 warning，但不输出值；
- key 是 `present`、`missing` 还是 `not_required`；
- provider 依赖是否存在；
- 是否执行了 live 请求。

输出不会包含 key 值、base_url 值、prompt、completion、请求体或响应体。

## 5. 错误分类

M5 把真实 provider 失败统一归类成固定 code：

| code | 场景 |
|---|---|
| `missing_config` | 缺 key、model、provider 依赖等本地配置 |
| `auth_error` | 认证或权限失败 |
| `rate_limited` | provider 限流 |
| `network_error` | 连接、DNS、网关等网络失败 |
| `timeout` | 请求超时 |
| `bad_response` | provider 返回不可用响应或 4xx bad request |
| `unknown_provider` | provider 名称不在 MVP registry |
| `provider_error` | 其他 provider 失败 |

错误输出包含 `code/type/message/retryable`。`message` 是用户可读摘要，不是 SDK
原始异常字符串；`type` 只用于机器诊断，不应包含 secret、headers、base URL 原值、
prompt、completion 或 response body。

## 6. Live preflight

只有显式传入 `--live` 才会发真实请求：

```bash
.venv/bin/python main.py preflight --provider anthropic --live
```

`--live` 可能消耗真实配额，并会触发网络请求。即便 live 成功，输出也只包含
`tokens`、`latency`、`status`、`error` 等摘要，不输出 provider completion。

M4/M5 不会在自动测试里调用真实 provider；测试只覆盖 fake provider、stub provider
和环境变量配置行为。
M5 的真实 smoke 步骤见 `docs/LLM_PROVIDER_LIVE_SMOKE.md`，默认由用户手动执行。

## 7. 审计产物边界

`preflight` 默认不写 `state.json` 或 `runs/*.jsonl`。如果未来需要把 preflight
结果写入审计日志，也只能写 provider/model/key status/base_url configured/live
status 等白名单字段，不能写 `.env` 内容、API key、raw prompt、raw completion 或
provider request/response body。

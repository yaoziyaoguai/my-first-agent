# LLM Provider Live Smoke

> **本文目的**：给 v0.2 M5 提供一套可复现、可审计、不会泄露 secret 的真实
> provider smoke 步骤。
>
> **核心边界**：live smoke 会触发真实 provider 请求，可能消耗配额。它只验证
> provider 配置、preflight、process、status 的安全闭环，不扩展 provider
> ecosystem，不提交 `state.json`、`runs/` 或输入样例产物。

---

## 1. 前置条件

确认本地 `.env` 存在且不会被提交：

```bash
test -f .env
git check-ignore .env
```

只检查变量名，不打印值：

```bash
grep -q '^ANTHROPIC_API_KEY=' .env
grep -q '^ANTHROPIC_MODEL=' .env
```

安全加载 `.env` 到当前 shell：

```bash
set -a
source .env
set +a
test -n "$ANTHROPIC_API_KEY"
test -n "$ANTHROPIC_MODEL"
```

不要把 `.env`、API key、base URL 原值、headers 或 provider response body 贴到
issue、commit、日志或测试快照里。

## 2. 本地配置 preflight

默认 preflight 不发真实请求：

```bash
.venv/bin/python main.py preflight --provider anthropic
```

通过判据：

- JSON 顶层 `status` 为 `ok`。
- `api_key.status` 只显示 `present`。
- `base_url.configured` 只显示布尔值。
- 输出不包含 API key、base URL 原值、headers、prompt、completion 或 response body。

失败判据：

- `errors[].code` 出现 `missing_config`、`unknown_provider` 等配置错误。
- 输出出现任何 secret 或原始请求/响应内容。

## 3. Live preflight

显式 `--live` 才会发真实请求：

```bash
.venv/bin/python main.py preflight --provider anthropic --live
```

通过判据：

- JSON 顶层 `status` 为 `ok`。
- `live.enabled` 为 `true`，`live.status` 为 `ok`。
- `live` 只包含 token/latency/status 等摘要。
- 输出不包含 completion、prompt、API key、base URL 原值或 response body。

失败时也应是安全失败：

- `errors[].code` 属于固定分类：
  `missing_config`、`auth_error`、`rate_limited`、`network_error`、`timeout`、
  `bad_response`、`unknown_provider`、`provider_error`。
- `errors[].message` 是用户可读摘要，不是 SDK 原始异常字符串。

## 4. Process live smoke

创建一个很小的本地输入文件：

```bash
printf 'Provider live smoke input. Do not store this raw text in audit logs.\n' > /tmp/my-first-agent-live-smoke.txt
```

运行真实 provider process：

```bash
.venv/bin/python main.py process /tmp/my-first-agent-live-smoke.txt --provider anthropic
```

通过判据：

- 命令输出 JSON，包含 `run_id`、`status`、`input_file_hash`、`run_path`。
- 成功时 `status` 为 `ok`。
- 失败时 `status` 为 `error`，并包含脱敏 `error.code/type/message/retryable`。
- `state.json` 和 `runs/*.jsonl` 不包含输入正文、prompt、completion、API key、
  base URL 原值、headers 或 provider request/response body。

## 5. Status 检查

检查最近 run：

```bash
.venv/bin/python main.py status
```

检查指定 run：

```bash
.venv/bin/python main.py status --run-id <run_id>
```

通过判据：

- `llm_calls[]` 只包含白名单字段：
  `provider/model/prompt_version/input_file_hash/tokens/latency/status/error`。
- `errors[]` 只展示错误 code 摘要。
- `warnings[]` 可以包含缺失或损坏日志 warning，但不能包含 secret。

## 6. 产物处理

live smoke 产生的 `state.json`、`runs/` 和临时输入文件都是本地验证产物，默认不提交。
提交前检查：

```bash
git status --short
git check-ignore state.json runs/
```

如果需要清理产物，先确认不需要保留本地审计证据，再手动删除。不要把 live smoke
输出里的 secret 或原始响应复制进文档。

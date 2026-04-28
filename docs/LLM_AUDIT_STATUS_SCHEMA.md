# LLM Audit Status Schema

> **本文目的**：冻结 `main.py status` 的机器可读 JSON 输出，让脚本、测试和人类
> 都能稳定审计 LLM Processing MVP 的运行结果。
>
> **核心边界**：status 是只读审计层，不是 transcript viewer。它只读取
> `state.json` 和 `runs/*.jsonl` 的 metadata，不读取输入文件正文，不输出 raw text、
> prompt、completion 或任何 secret/env value。

---

## 1. 为什么需要稳定 schema

LLM processing 的原始输入可能包含用户私有信息、业务文本或 secret。M3 的目标不是
把这些内容展示出来，而是让用户确认：

- 最近处理的是哪个输入文件 hash；
- 使用了哪个 provider / model / prompt_version；
- token、latency、status、error 是否可审计；
- JSONL 是否损坏、state/runs 是否缺失；
- 哪个 run 可以被脚本稳定查询。

如果 status 输出结构漂移，自动化检查就会退化成字符串 grep；如果 status 输出原文，
审计层就会变成第二份敏感数据存储。因此 schema 必须稳定，字段必须白名单化。

## 2. 顶层 JSON 字段

`main.py status` 输出一个 JSON object：

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | 固定为 `llm.audit.status.v1` |
| `query` | object | 查询条件，目前包含 `run_id` |
| `state_path` | string | 本次读取的 state 文件路径 |
| `runs_dir` | string | 本次读取的 runs 目录 |
| `latest_run` | object | 默认查询时的最近 run，或 `--run-id` 指定 run 的摘要 |
| `runs` | array | 本次查询命中的 run 摘要列表；MVP 阶段最多 1 条 |
| `llm_calls` | array | 本次查询命中的 `llm_call` 白名单 payload |
| `errors` | array | 从 `llm_calls` 派生的错误摘要 |
| `warnings` | array | 缺失 state/runs、损坏 JSONL 等非致命 warning |
| `allowed_llm_call_fields` | array | 当前允许出现在 `llm_calls[]` 的字段名 |

## 3. `query`

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string/null | 未传 `--run-id` 时为 `null`；传入后为指定 id |

默认行为：

- 优先使用 `state.json.run_path`。
- 如果 state 缺失或没有 `run_path`，回退到 `runs/` 下 mtime 最新的 `*.jsonl`。

`--run-id <id>` 行为：

- 只读取 `runs/<id>.jsonl`。
- 不修改 `state.json` 或 `runs/*.jsonl`。
- `<id>` 必须是单个文件名式 run id，不能包含目录分隔符。
- 如果文件不存在，返回空 `runs` / `llm_calls`，并在 `warnings` 中加入
  `run_missing:<id>`。

## 4. `runs[]` / `latest_run`

run 摘要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string/null | run id；通常来自文件名或 state |
| `status` | string/null | state 记录的 run 状态；没有 state 匹配时为 `null` |
| `input_file_hash` | string/null | state 记录的输入文件 hash；没有 state 匹配时为 `null` |
| `run_path` | string/null | run JSONL 路径 |
| `latest_event` | string/null | JSONL 中最后一个可解析事件名 |
| `llm_call_count` | number | 可解析 `llm_call` 数量 |

`latest_run` 始终存在。没有任何 run 时，它是空摘要。

## 5. `llm_calls[]` 白名单字段

每个 `llm_calls[]` item 只能包含以下字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `provider` | string/null | provider 名，如 `fake` / `anthropic` |
| `model` | string/null | model 名 |
| `prompt_version` | string/null | prompt 版本，如 `triager.v1` |
| `input_file_hash` | string/null | 输入文件 SHA-256 hash |
| `tokens` | number/null | token 数；provider 不支持时为 `null` |
| `latency` | number/null | 调用耗时，毫秒 |
| `status` | string/null | `ok` / `error` 等状态 |
| `error` | string/null | 错误类型摘要；成功时为 `null` |

如果 `runs/*.jsonl` 中的 `llm_call.payload` 含有额外字段，status 必须丢弃它们。

## 6. `errors[]`

`errors[]` 从 `llm_calls[]` 派生，只包含失败调用摘要：

| 字段 | 类型 | 说明 |
|---|---|---|
| `prompt_version` | string/null | 失败所在 prompt version |
| `status` | string/null | 调用状态 |
| `error` | string/null | 错误类型摘要 |

## 7. `warnings[]`

warning 是 string 数组。MVP 约定：

| warning | 场景 |
|---|---|
| `state_missing` | `state.json` 不存在 |
| `state_invalid_json` | `state.json` 不是合法 JSON |
| `state_not_object` | `state.json` 合法但不是 object |
| `runs_missing_or_empty` | 默认查询时没有可用 runs 目录或 JSONL |
| `run_id_invalid:<id>` | `--run-id <id>` 包含目录分隔符或不是单个文件名 |
| `run_missing:<id>` | `--run-id <id>` 指定的 JSONL 不存在 |
| `run_log_missing:<path>` | state 指向的 run log 不存在 |
| `invalid_jsonl:<path>:<line>` | 某行 JSONL 损坏，已跳过 |
| `jsonl_not_object:<path>:<line>` | 某行 JSONL 合法但不是 object，已跳过 |

warning 不代表命令失败。`status` 应尽量返回可用审计信息。

## 8. 禁止字段

以下字段或等价内容绝对不能出现在 status JSON 中：

- `raw_text`
- `prompt`
- `completion`
- `source_text`
- `source_full_text`
- input file full text
- secret
- API key
- env value
- provider request body
- provider response body

测试会用伪造 JSONL 注入 `raw_text` / `prompt` / `completion`，并断言 status 输出不会泄漏。

## 9. 示例

```json
{
  "schema_version": "llm.audit.status.v1",
  "query": {"run_id": null},
  "state_path": "state.json",
  "runs_dir": "runs",
  "latest_run": {
    "run_id": "abc",
    "status": "ok",
    "input_file_hash": "sha256...",
    "run_path": "runs/abc.jsonl",
    "latest_event": "process_completed",
    "llm_call_count": 3
  },
  "runs": [
    {
      "run_id": "abc",
      "status": "ok",
      "input_file_hash": "sha256...",
      "run_path": "runs/abc.jsonl",
      "latest_event": "process_completed",
      "llm_call_count": 3
    }
  ],
  "llm_calls": [],
  "errors": [],
  "warnings": [],
  "allowed_llm_call_fields": [
    "error",
    "input_file_hash",
    "latency",
    "model",
    "prompt_version",
    "provider",
    "status",
    "tokens"
  ]
}
```

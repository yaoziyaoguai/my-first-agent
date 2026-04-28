# LLM Provider Live Smoke Report

> **本文目的**：记录 v0.2 M6 真实 provider live smoke 的审计结果，验证 M4/M5
> 提供的 provider config、preflight、process、status、status --run-id、
> `runs/*.jsonl`、`state.json` 在真实 provider 场景下能安全闭环。
>
> **核心边界**：本报告只是 provider 安全闭环验证记录，不代表 provider
> ecosystem 完成，也不是 provider 性能或质量评估。`state.json`、`runs/` 和
> 临时 smoke 输入文件都是本地运行产物，默认不提交。

---

## 1. 执行环境

| 项 | 取值 | 备注 |
|---|---|---|
| provider | `anthropic` | 经 anthropic 兼容端点接入 |
| model | 通过 `MODEL_NAME` 注入 | model 名经审计输出公开，不属于 secret |
| base_url | 已配置 | `base_url.configured=true`，原值未输出 |
| api key | present | 仅 status 字段，未输出值 |
| dependency | `anthropic` available | preflight 自检通过 |

`.env` 已被 `.gitignore` 忽略，加载方式为 `set -a; source .env; set +a`，
未在终端、文档、日志、`state.json`、`runs/*.jsonl` 中打印任何 secret。

## 2. Live preflight

命令：

```bash
.venv/bin/python main.py preflight --provider anthropic --live
```

JSON 输出关键字段（仅安全摘要，原文截取并去除运行特定信息）：

```json
{
  "status": "ok",
  "provider": {"name": "anthropic", "configured": true},
  "model": {"configured": true, "source": "MODEL_NAME"},
  "base_url": {"configured": true},
  "api_key": {"status": "present", "env": "ANTHROPIC_API_KEY"},
  "dependency": {"name": "anthropic", "available": true},
  "live": {"enabled": true, "status": "ok", "tokens": 231, "latency": 7126},
  "errors": [],
  "warnings": []
}
```

通过判据：

- 顶层 `status=ok`、`live.status=ok`。
- `live` 仅含 `enabled / status / tokens / latency`，无 completion、prompt、
  response body、headers、key、base_url 原值。
- `api_key.status=present`，未输出 key 值。
- `base_url.configured=true`，未输出 URL。

## 3. 真实 provider process smoke

输入：`/tmp/m6_live_smoke_XXXX.txt`，54 字节，单行短文本，仅请求模型回一句中文。
临时输入文件位于 `/tmp/`，不在仓库内，已默认不提交；smoke 完成后可手动删除。

命令：

```bash
.venv/bin/python main.py process /tmp/<smoke_input> --provider anthropic
```

CLI JSON 输出：

```json
{
  "status": "ok",
  "run_id": "627b3b09e35047b583717e81bbb351c3",
  "run_path": "runs/627b3b09e35047b583717e81bbb351c3.jsonl",
  "input_file_hash": "277324bf0ea2155939ca003ba66c90b5a3d1947a613d49730eefe6173e5f0285"
}
```

`state.json`（本地产物，未提交）只含 `input_file_hash / last_run_id /
run_path / status / updated_ms`，无正文、prompt、completion、key、headers、
base_url 原值、response body。

`runs/<run_id>.jsonl`（本地产物，未提交）记录的事件序列：

| 事件 | 关键 payload | 说明 |
|---|---|---|
| `process_started` | `input_file_hash`、`input_path_name` | 仅文件名，不含正文 |
| `llm_call` × 3 | provider、model、prompt_version、input_file_hash、tokens、latency、status、error | 经 `sanitize_llm_call_payload` 白名单过滤 |
| `process_completed` | `input_file_hash`、`status` | 不含 completion |

三段 stage 的 token / latency 摘要：

| stage | tokens | latency_ms | status |
|---|---:|---:|---|
| `triager.v1` | 55 | 1323 | ok |
| `distiller.v1` | 95 | 4355 | ok |
| `linker.v1` | 125 | 3286 | ok |

总 token 消耗（含 preflight 231）约 506，成本可控。

## 4. Status / status --run-id 审计

```bash
.venv/bin/python main.py status
.venv/bin/python main.py status --run-id 627b3b09e35047b583717e81bbb351c3
```

通过判据：

- 输出 `schema_version=llm.audit.status.v1`，符合 `docs/LLM_AUDIT_STATUS_SCHEMA.md`。
- `latest_run` / `runs[]` 只展示 `run_id / status / input_file_hash / run_path /
  latest_event / llm_call_count`。
- `llm_calls[]` 只含 `allowed_llm_call_fields` 8 个字段。
- `errors=[]`、`warnings=[]`。
- 默认查询和 `--run-id` 查询的 `llm_calls` / `latest_run` 完全一致；
  `--run-id` 仅改变 `query.run_id`，不修改 `state.json` 或 `runs/*.jsonl`。

## 5. 防泄漏核验

针对 `state.json` 和 `runs/` 做了以下显式检查，全部通过：

- 输入正文短语（如 `M6 live smoke`、`Reply with one short`）：未出现。
- env 变量名（`ANTHROPIC_API_KEY`）：未出现。
- API key 前 8 字节：未出现。
- base_url host：未出现。
- 常见敏感关键字（`x-api-key`、`Bearer `、`completion`、`raw_text`、`prompt:`）：未出现。

`git status --short` 在所有命令执行后保持干净；`state.json`、`runs/`、`.env`
均被 `.gitignore` 覆盖，未进入 staged 区。

## 6. 结论与建议

- M4 provider config、M5 provider 错误分类与 live preflight、M6 真实 process
  smoke 与 status 审计构成的安全闭环已在真实 provider 上跑通。
- preflight、process、status、status --run-id、`state.json`、`runs/*.jsonl`
  均未泄漏 key、base_url 原值、headers、prompt、completion 或 response body。
- 临时 smoke 输入文件位于 `/tmp/` 之下；`state.json` 与 `runs/` 是本地审计
  产物，按 `.gitignore` 默认不提交。
- 本报告不替代未来 provider ecosystem、成本统计、多模型路由等工作；这些都
  在 v0.2 LLM Processing 的 M6 之外，按 `docs/V0_2_PLANNING.md` 推进。

下一步建议（仍在 v0.2 LLM Processing / provider 安全闭环范围内）：

- 评估是否需要把 `process_failed` / `live` 失败路径也跑一次真实 smoke，例如
  故意用错误 key 触发 `auth_error`，验证安全错误摘要在真实 SDK 异常下表现。
- 评估是否需要为 `runs/` 增加保留期与本地清理脚本，避免长期 smoke 累积。
- 评估是否需要把 model 名以外的 provider 元信息（如 prompt_version 列表）
  写入 `docs/LLM_PROVIDER_CONFIG.md`，让审计读者无需读代码即可对照。

# LLM Processing Capability Matrix (v0.2)

> **本文目的**：给 v0.2 LLM Processing 路线做一次能力矩阵收口，让 scan、
> process、status、status --run-id、preflight、provider config、错误分类、
> live smoke、运行产物和审计 schema 这些子系统的边界一目了然。
>
> **核心边界**：本文是 v0.2 LLM Processing MVP 的能力快照，不是成熟 LLM
> 平台规格。fake provider 是默认测试路径；真实 provider 仅用于显式 live smoke。
> 任何超出 provider 安全闭环（多模型路由、成本统计、provider 选择策略、
> prompt 模板治理、Skill / sub-agent / TUI / topic switch）都不在本矩阵范围。

---

## 0. 总览

| 能力块 | 命令 / 模块 | 默认 provider | 真实 API | 产物 | 来源 milestone |
|---|---|---|---|---|---|
| scan | `main.py scan` / `llm.audit.scan_inputs` | 不涉及 | 不会 | 仅 stdout JSON | M3 |
| process | `main.py process` / `llm.pipeline.process_file` | fake | 仅当显式 anthropic | `state.json` + `runs/<id>.jsonl` | M2/M5 |
| status | `main.py status` / `llm.audit.build_status` | 不涉及 | 不会 | 仅 stdout JSON | M3 |
| status --run-id | `main.py status --run-id <id>` | 不涉及 | 不会 | 仅 stdout JSON | M3 |
| preflight | `main.py preflight` | fake | 仅 `--live` | 仅 stdout JSON | M4 |
| provider config | `llm.config` | fake | 不会 | env 读取 | M4 |
| error classification | `llm.errors` | 不涉及 | 不会 | 抛 / 安全 dict | M5 |
| live smoke | playbook | anthropic | 是 | 本地 `state.json`/`runs/`，不提交 | M5/M6 |
| run artifacts | `RunLogger` / `state.json` / `runs/` | 不涉及 | 不会 | 本地文件，不提交 | M2 |
| audit schema | `docs/LLM_AUDIT_STATUS_SCHEMA.md` | 不涉及 | 不会 | 文档 + 白名单 | M3 |

## 1. scan

- **能力**：只读扫描文件或目录，输出 path / hash / size / mtime metadata。
- **非目标**：不读取并持久化正文，不写 `state.json` / `runs/`。
- **输入**：`main.py scan <path>`。
- **输出**：单行 JSON `{"inputs":[{path, input_file_hash, size, mtime}, ...]}`。
- **产物**：仅 stdout。
- **风险**：大目录可能耗时；hash 通过 bytes 计算，不会泄漏正文。
- **测试**：`test_scan_inputs_reports_metadata_without_persisting_raw_text`、
  `test_scan_command_outputs_metadata_only`。

## 2. process

- **能力**：按 fake / anthropic provider 跑 triager.v1 → distiller.v1 → linker.v1
  三段最小流水线；写 `state.json` 与 `runs/<run_id>.jsonl`。
- **非目标**：不做 prompt 模板治理、不做多模型路由、不做成本统计。
- **输入**：`main.py process <input_file> [--provider ...] [--model ...]
  [--state-path ...] [--runs-dir ...]`。
- **输出**：JSON `{run_id, status, input_file_hash, run_path[, error]}`。
- **产物**：本地 `state.json` 与 `runs/<run_id>.jsonl`，均被 `.gitignore` 覆盖。
- **风险**：真实 provider 会消耗配额；失败路径必须经 `classify_provider_exception`
  归类后写入安全 state / runs。
- **测试**：`test_process_file_fake_provider_logs_llm_calls_without_raw_text`、
  `test_process_command_uses_fake_provider_without_real_key`、
  `test_process_failure_writes_safe_state_and_run_log`、
  `test_process_command_failure_returns_safe_json_and_status`、
  `test_main_process_dispatch_does_not_start_interactive_session`。

## 3. status

- **能力**：只读读取 `state.json` 和 `runs/*.jsonl` metadata，输出稳定 JSON。
- **非目标**：不展示 raw text、prompt、completion、key、env value。
- **输入**：`main.py status [--state-path ...] [--runs-dir ...]`。
- **输出**：`schema_version=llm.audit.status.v1` 的 JSON；详见
  `docs/LLM_AUDIT_STATUS_SCHEMA.md`。
- **产物**：仅 stdout。
- **风险**：损坏 JSONL 必须降级为 warning，不能崩溃。
- **测试**：`test_status_handles_missing_state_and_runs`、
  `test_status_default_output_schema_is_stable`、
  `test_status_reads_llm_call_whitelist_and_skips_corrupt_jsonl`、
  `test_status_command_outputs_warnings_without_raw_text`。

## 4. status --run-id

- **能力**：按 run id 只读 `runs/<id>.jsonl`，不修改 state/runs。
- **非目标**：不接受 path traversal；不是 transcript viewer。
- **输入**：`main.py status --run-id <id>`。
- **输出**：同 §3，但 `query.run_id=<id>`，`runs[]` 仅命中该 run。
- **产物**：仅 stdout。
- **风险**：必须拒绝路径分隔符；缺失 run 转 warning 而非 error。
- **测试**：`test_status_run_id_queries_specific_run_without_state_mutation`、
  `test_status_run_id_missing_is_stable`、
  `test_status_run_id_rejects_path_traversal`、
  `test_status_command_run_id_outputs_specific_run`。

## 5. preflight

- **能力**：默认只做本地 provider 配置校验；`--live` 才发真实请求。
- **非目标**：不输出 key、base_url 原值、prompt、completion、response body。
- **输入**：`main.py preflight [--provider ...] [--model ...] [--live]`。
- **输出**：固定 schema JSON；详见 `docs/LLM_PROVIDER_CONFIG.md` §4。
- **产物**：仅 stdout；不写 state/runs。
- **风险**：`--live` 会消耗配额；live 失败必须经错误分类输出安全摘要。
- **测试**：`test_provider_preflight_*`（fake、JSON schema、缺 key、redact key、
  缺 model、未知 provider、不持久化 secret、live 失败安全形态）+
  `test_main_preflight_dispatch_does_not_start_interactive_session`。

## 6. provider config

- **能力**：`llm/config.py` 通过 env 读取 provider/model/base_url/key；fake 默认。
- **非目标**：不解析 `.env`；不构造 provider client；不输出 secret。
- **支持 provider**：`fake`（无需 key）、`anthropic`（需要 key + model）。
- **风险**：key 只能停留在 `ProviderConfig` 内存中传给 client，不能写日志。
- **测试**：通过 preflight / process 系列测试间接覆盖。

## 7. error classification

- **能力**：`llm/errors.py` 把 SDK / HTTP / Python 异常归类为固定 8 个 code：
  `missing_config / auth_error / rate_limited / network_error / timeout /
  bad_response / unknown_provider / provider_error`；输出 `code/type/message/
  retryable`。
- **非目标**：不透传 SDK 原始 message、URL、headers、response body。
- **风险**：分类只看 `status_code` + class 名，不读 `str(exc)`，避免 SDK 把
  request / response 细节塞进异常字符串泄漏。
- **测试**：`test_provider_error_classifier_covers_required_codes`、
  `test_preflight_live_failure_uses_safe_error_shape`、
  `test_process_failure_writes_safe_state_and_run_log`、
  `test_process_command_failure_returns_safe_json_and_status`、
  真实 anthropic auth_error live smoke（见 LIVE_SMOKE_REPORT §6）。

## 8. live smoke

- **能力**：手动 playbook，验证真实 provider 安全闭环。
- **非目标**：不进入自动测试；不替代 provider ecosystem。
- **流程**：`docs/LLM_PROVIDER_LIVE_SMOKE.md`（happy path）+
  `docs/LLM_PROVIDER_LIVE_SMOKE_REPORT.md` §6（auth_error 失败 path）。
- **产物**：本地 `state.json` 与 `runs/`，按 `.gitignore` 默认不提交。
- **风险**：消耗真实配额；必须保持错误 key 与真实 key 都不进入产物。
- **测试**：自动测试只覆盖 fake / stub / monkeypatch；真实 API 测试由人工执行。

## 9. run artifacts

- **能力**：`run_logger.py` 提供 append-only JSONL + `state.json` 写入；
  `LLM_CALL_ALLOWED_FIELDS` 白名单仅 8 字段。
- **非目标**：不存 raw text、prompt、completion、headers、key。
- **清理 playbook**：`docs/LLM_PROVIDER_LIVE_SMOKE_REPORT.md` §7。
- **`.gitignore` 覆盖**：`.env / state.json / runs/ / summary.md`。
- **风险**：长期 smoke 可能堆积 `runs/`；按 §7 手动清理。
- **测试**：`test_process_file_fake_provider_logs_llm_calls_without_raw_text`、
  `test_process_failure_writes_safe_state_and_run_log`、
  端到端 `test_e2e_offline_scan_process_status_audit_without_leaks`。

## 10. audit schema

- **能力**：`docs/LLM_AUDIT_STATUS_SCHEMA.md` 冻结 status JSON schema，
  `schema_version=llm.audit.status.v1`。
- **非目标**：不展示 raw text；不在 status 输出原始事件 payload。
- **白名单字段**：`provider / model / prompt_version / input_file_hash /
  tokens / latency / status / error`。
- **风险**：JSONL payload 含额外字段时必须丢弃。
- **测试**：`test_status_reads_llm_call_whitelist_and_skips_corrupt_jsonl`、
  schema 字段集断言系列。

## 11. 防泄漏总线

无论从哪条路径接触 LLM Processing，外部产物只能是以下安全字段：

- preflight：`provider/model/base_url(bool)/api_key(status)/dependency/live(摘要)/errors/warnings/status`。
- process CLI：`run_id/status/input_file_hash/run_path/error(摘要)`。
- `state.json`：`input_file_hash/last_run_id/run_path/status/updated_ms[/error]`。
- `runs/*.jsonl`：`process_started/llm_call/process_completed/process_failed`，
  llm_call payload 只有 `LLM_CALL_ALLOWED_FIELDS` 8 字段。
- status：`schema_version/query/state_path/runs_dir/latest_run/runs/llm_calls/
  errors/warnings/allowed_llm_call_fields`。

绝对禁止字段：raw input text、prompt、completion、API key、env value、
base_url 原值、HTTP headers、provider request/response body。

## 12. v0.2 LLM Processing 阶段性结论

v0.2 LLM Processing 的 provider 安全闭环（M2 + M3 + M4 + M5 + M6）**已可阶段性
收口**：

- 默认 fake 路径稳定，`pytest` 全绿。
- 真实 anthropic 路径在 happy / auth_error 两条路径上均已 live smoke 验证，
  无 secret / raw text 泄漏。
- 文档冻结：CONFIG / LIVE_SMOKE / LIVE_SMOKE_REPORT / AUDIT_STATUS_SCHEMA /
  本能力矩阵。
- 运行产物按 `.gitignore` 默认不提交；清理 playbook 已写入。

**下一步建议**：回到 `docs/V0_2_PLANNING.md` 的 Runtime 主线，从 M1
「Runtime 状态机整理」开始；不要在 LLM Processing 范围内继续扩成 provider
ecosystem / 多模型路由 / 成本统计 / prompt 模板治理。

# Provider API Key Activation Audit

**日期**: 2026-06-14  
**性质**: T-PROVIDER-E2E activation audit；docs-only，不是 provider 实现  
**审计边界**: 未运行真实 API，未修改 `agent/` 或 `tests/`，未写入任何 API key
**Secret safety hardening**: 2026-06-14 完成（Commit `17ee0ae`→）。本轮新增 `api_key_env` indirection、修复 real/fake guard、修复 response body leak、hardening real smoke safety

## 1. Status

- Architecture Repair Mainline: **CLOSED**。
- Trigger: **T-PROVIDER-E2E**。
- Current category: **BLOCKED_BY_EXTERNAL**。
- 本文是 activation audit，不是 implementation，也不是 real-provider readiness 证明。
- 本文不存储 API key；变量名和占位符不等于 credential。
- **Mechanical readiness category: A（仅指已有 env loader + opt-in adapter smoke）**。
- **Secret safety hardening: COMPLETED**。`api_key_env` indirection 已实现；real/fake guard 已修正；response body leak 已修复；real smoke preview 已脱敏。
- **Config source policy: CONFIG-DRIVEN**。Provider 选择由 config 文件显式决定；`inline api_key` 是合法的本地使用方式（不提交即可）；`api_key_env` 推荐用于可提交模板；ambient env auto-discovery 是 legacy/explicit opt-in。
- **Activation verdict: DO NOT RUN YET**。user 需先 rotate 本次 tracked local config 中可能暴露的 key。仍缺真实 credential 环境下的 success/failure/fallback evidence。
- A 不代表 trigger 已完成或当前可安全激活：尚未产生本次受控 credential 下的真实运行证据，也没有覆盖完整 success / failure / fallback / adversarial 路径。

## 2. Provider Inventory

### Runtime boundary

| Surface | Current fact | Evidence |
|---|---|---|
| Provider protocol | `ModelProvider` 定义 `create()` / `stream()` 的 provider-neutral contract | `agent/provider/protocol.py` |
| Factory | `build_model_provider()` 使用显式分支构造 4 类 real adapter 或 `FakeProvider`；没有 provider registry | `agent/provider/factory.py` |
| Fake provider | 默认 safe-local provider；与 real adapter 共享 `ModelProvider` contract | `agent/provider/fake_provider.py`、`tests/test_provider_contract.py` |
| Anthropic real adapters | `anthropic_native` 使用官方 SDK；`anthropic_compatible` 使用 `httpx` | `agent/provider/anthropic_native.py`、`agent/provider/anthropic_http.py` |
| OpenAI real adapters | `openai_native` 与 `openai_compatible` 均使用 `httpx` Chat Completions 路径 | `agent/provider/openai_native.py`、`agent/provider/openai_http.py` |
| Runtime call boundary | `agent/model_call.py` 通过 provider factory 构造默认 provider；`core.chat(provider=...)` 提供显式注入 seam | `agent/model_call.py`、`agent/core.py` |
| Default provider | 仓库默认和无配置 fallback 均为 `FakeProvider` | `agent/provider/factory.py`、tracked `config/config.yaml` 模板 |

### Config surfaces

| Surface | Role | Current status |
|---|---|---|
| `agent/provider/simple_config.py` | 读取 `config/config.yaml` 的 `provider` section | 当前推荐路径；key 为 inline `provider.api_key` |
| `agent/provider/config.py` | 从 process env 构造 `AgentProviderConfig` | legacy env 路径；real smoke 直接使用 |
| `agent/provider/profiles.py` | profile 名称到 `AgentProviderConfig` 的转换，key 由 `api_key_env` 指向 process env | legacy；仓库当前没有 `config/provider_profiles.yaml` |
| `config.py` | legacy CLI `.env` loader 与 lazy compatibility getter | CLI `main()` 显式加载 `.env`；不是 unified config owner |
| `config/config.example.yaml`、`config/examples/*.yaml` | fake / compatible provider 示例 | 已存在；只应包含占位符 |
| `.env.example` | legacy env 名称示例 | 已存在；`.env` 被 `.gitignore` 忽略 |

## 3. API Key / Credential Loading Path

### Resolution precedence

`build_model_provider_from_env()` 当前按以下顺序决议：

1. `config/config.yaml`；
2. `FIRST_AGENT_PROVIDER_PROFILE` + `config/provider_profiles.yaml`；
3. `MY_FIRST_AGENT_LLM_PROVIDER` + provider-specific process env；
4. `FakeProvider`。

只有 `config/config.yaml` 被成功解析且返回 `config_yaml` / `config_yaml_disabled` 时，factory 才停止继续解析 legacy profile/env。文件无效、缺少 `provider` section 或无法读取时会返回 `default_fake`，随后仍可能进入 legacy env 路径。malformed config 与 real env 并存时是否应 fail closed，需要在激活前明确。当前仓库跟踪该路径，并用 `skip-worktree` 保护本地副本；这不是与 ignored secret file 等价的强隔离。

### Supported environment variables

| Purpose | Variables |
|---|---|
| Provider selection | `MY_FIRST_AGENT_LLM_PROVIDER` |
| Provider display name | `MY_FIRST_AGENT_LLM_PROVIDER_NAME` |
| Anthropic credential | `ANTHROPIC_API_KEY` |
| Anthropic model / endpoint | `ANTHROPIC_MODEL`, `MODEL_NAME`, `ANTHROPIC_BASE_URL` |
| OpenAI credential | `OPENAI_API_KEY` |
| OpenAI model / endpoint | `OPENAI_MODEL`, `OPENAI_BASE_URL` |
| Generic overrides | `MY_FIRST_AGENT_LLM_MODEL`, `MY_FIRST_AGENT_LLM_BASE_URL`, `MY_FIRST_AGENT_LLM_AUTH_SCHEME`, `MY_FIRST_AGENT_LLM_REQUEST_PATH`, `MY_FIRST_AGENT_LLM_COMPATIBILITY_MODE`, `MY_FIRST_AGENT_LLM_MAX_TOKENS`, `MY_FIRST_AGENT_LLM_TIMEOUT` |
| Legacy profile | `FIRST_AGENT_PROVIDER_PROFILE` |

没有专用 `DEEPSEEK_API_KEY` 或 `DEEPSEEK_*` loader。DeepSeek 当前通过 `anthropic_compatible` adapter 进入（`type: anthropic_compatible`, `base_url: https://api.deepseek.com/anthropic`, `api_key_env: DEEPSEEK_API_KEY`）。不要把 DeepSeek 写成 `openai_compatible`——DeepSeek 虽然也提供 OpenAI-compatible 端点，但用户当前目标路径是 Anthropic Messages 协议。仓库没有名为 DeepSeek 的 profile 或专用实现。不要把“协议兼容”写成“已支持并验证”。

### `.env` and config objects

- `load_agent_provider_config()` 只读传入 mapping 或 `os.environ`，自己不加载 `.env`。
- `main.py:main()` 会显式调用 legacy `.env` loader，把 `.env` 注入 process env；但 `config/config.yaml` 仍优先。
- diagnostics 有 scoped / isolated dotenv loader，输出来源类别而不输出值。
- `AgentProviderConfig.api_key` 使用 `repr=False`；`redacted_summary()` 只显示 `SET` / `empty`。
- `config/config.yaml` loader 当前支持两种 key 来源：inline `provider.api_key`（本地未提交使用）和 `provider.api_key_env`（从 process env 读取，推荐用于可提交模板）。两者均可用，选择取决于使用场景：本地开发推荐 inline key（简洁），可提交模板推荐 api_key_env（安全）。

### Logging, snapshots, and CI

- 未发现 provider adapter、factory 或 diagnostics 主动记录完整 key；HTTP adapter 只把 key 放入认证 header。
- diagnostics、provider mode banner、config repr/summary 和 event-log masking 有 synthetic-secret 测试。
- 未发现 snapshot/fixture 保存真实 key 的路径；测试里的 key 字符串是合成哨兵值，不是 real-provider evidence。
- 仓库没有 `.github/` workflow，也没有可核验的 CI secret mapping；当前不存在已证明的 CI secret activation path。
- `.gitignore` 覆盖 `.env`、`agent_log.jsonl`、`sessions/`、`runs/` 和 `graphify-out/`。

## 4. Fake Provider vs Real Provider Boundary

- Fake 与 real adapter 共享 `ModelProvider` contract 和 `core.chat()` / loop 主路径，不是两套 runtime。
- `FakeProvider` 默认且不访问网络；real adapter 只有在显式配置或测试注入时才可能发出网络调用。
- unit/contract tests 使用 injected HTTP client、synthetic key 或 fake response，只证明 adapter contract，不证明 provider endpoint 可达。
- `tests/test_provider_real_smoke.py` 是 real adapter smoke；其中 MCP round-trip 是手工拼接，不是完整 AgentLoop E2E。
- `tests/test_agentloop_mcp_e2e.py` 的 real LLM case 直接构造 Anthropic SDK client，文档明确“不经 `core.chat()`，不声称 E2E”。
- `tests/runtime_integration/test_memory_anchor_real.py` 试图覆盖 `core.chat()`，但 `_require_real_provider()` 接受 `build_model_provider_from_env()` 的任何非 `None` 返回；该 factory 默认返回 `FakeProvider`。因此门控不能可靠证明拿到 real provider，不能作为已就绪的 real-provider E2E 证据。

## 5. Existing Real Provider Test Readiness

### Existing opt-in tests

| Test | Guard | Evidence ceiling |
|---|---|---|
| `tests/test_provider_real_smoke.py` | `MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1` + `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` + `ANTHROPIC_MODEL` + fake-pattern rejection | 可运行的 `anthropic_compatible` adapter smoke；不是完整 success/failure/fallback E2E |
| `tests/test_agentloop_mcp_e2e.py` | `MY_FIRST_AGENT_RUN_REAL_LLM_E2E=1` + native Anthropic key shape | real LLM + MCP tool exposure 直调；绕过 provider factory / `core.chat()` |
| `tests/runtime_integration/test_memory_anchor_real.py` | `MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1` + provider construction | 目标是 real core-loop smoke，但 real/fake guard 不可靠，当前不能作为 activation command 推荐 |

### Readiness category

**A. 已有 real provider env loading + opt-in real provider test。**

这个 A 只描述机械能力，不表示“只差 key 就可以安全运行”。`tests/test_provider_real_smoke.py` 当前缺少 HTTPS + exact-host allowlist；Anthropic-compatible adapter 的错误路径可能把最多 500 字符响应正文带入异常；部分测试失败/skip 分支会打印 provider 输出预览。T-PROVIDER-E2E 仍为 `BLOCKED_BY_EXTERNAL`，同时存在**激活前内部安全前置项**。一次 adapter smoke 不能自动关闭 trigger；关闭至少还需要明确的 real success / auth failure / timeout or provider failure / fallback policy evidence，并确认走的是 real provider 而非 fake。

### Existing opt-in command inventory

以下命令是现有测试入口清单，**本审计不批准现在运行**。必须先完成：安全 secret indirection、移除 tracked inline-key 引导、HTTPS + exact-host allowlist、provider response/exception 脱敏、禁止测试打印 provider content、tracked marker 与 fail-closed guard。

```bash
# 只检查存在性，不输出值。
test -n "${ANTHROPIC_API_KEY:-}"
test -n "${ANTHROPIC_BASE_URL:-}"
test -n "${ANTHROPIC_MODEL:-}"

MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1 \
MY_FIRST_AGENT_LLM_MAX_TOKENS=64 \
MY_FIRST_AGENT_LLM_TIMEOUT=10 \
  .venv/bin/python -m pytest -q \
  tests/test_provider_real_smoke.py::test_real_anthropic_compatible_minimal_text_smoke \
  -rx --tb=short
```

本审计没有运行该命令。即使后续 hardening 完成，也必须由 secret manager / CI secret store 注入 process env，不得从 prompt、聊天记录或 tracked config 复制；还应确认 shell tracing 关闭、pytest 不使用 `-s`、日志目录为空或受控、没有会打印环境的 debug hook。首次只运行单个 minimal test；其余最多 3 个 provider 调用需单独授权。

## 6. Adversarial / Attack-Style Provider Test Readiness

### Current state

- `tests/adversarial/test_minimal_policy_stub.py` 只验证本地 forbidden-tool fail-closed，不调用 real provider。
- MCP sanitizer / registration tests 有 prompt-injection descriptor 和 destructive-tool 防护，但仍是本地 deterministic evidence。
- 当前没有 `real_provider + adversarial` opt-in suite，也没有 `real_provider` / `adversarial` / `expensive` pytest marker 注册。
- 因此目前不能用 API key 安全地“一条命令跑完整 adversarial suite”。

### Recommended bounded scope for a later implementation

应该测试：

- 模型输出中的 prompt injection 不得绕过 tool policy、confirmation 或 allowlist；
- 401/403、timeout、429/5xx、malformed response 必须映射为安全 provider error；
- provider error、tool input、messages、evidence、checkpoint、display、pytest failure output 均不得含 credential；
- fake/real evidence classification 不能混淆；
- retry 次数、调用次数、`max_tokens`、timeout 和模型必须有硬上限；
- fallback 必须显式、可观察，且不能把 fake success 当成 real success。

不应该测试：

- 不攻击 provider 自身基础设施，不做扫描、绕过、滥用或服务破坏；
- 不把 destructive tool、真实用户数据、真实 MCP endpoint 或任意网络目标放进 suite；
- 不发送无界 prompt corpus，不做自动多轮自我扩张，不默认并发；
- 不在 pytest assertion、exception、`-s` 输出、artifact、checkpoint 或 CI summary 中打印 request headers / env。

建议 marker 与 guard：

```python
@pytest.mark.real_provider
@pytest.mark.adversarial
@pytest.mark.expensive
```

```text
RUN_REAL_PROVIDER_TESTS=1
RUN_REAL_PROVIDER_ADVERSARIAL=1
```

marker 和 env guard 应同时存在；marker 必须在 tracked `pyproject.toml` 注册，但 marker 本身不会自动 deselect。应使用共享 fail-closed guard，验证“credential 存在但无 opt-in”仍 skip，并让默认 suite 显式排除或无条件 skip real-provider tests。成本控制应包括模型 allowlist、每测试最多 1–2 次调用、低 `max_tokens`、短 timeout、禁止自动 retry、串行执行和外部账户预算告警。

## 7. Secret Safety Rules

1. Never print, persist, commit, or echo API keys.
2. 不在 prompt/chat、源码、fixture、docs、命令参数或 shell history 中粘贴 key。
3. 优先由 secret manager / CI secret store 注入 process env；命令只引用变量名。
4. 不使用 `set -x`、`env`、`printenv` 或 pytest `-s` 调试 credential 问题。
5. diagnostics 只允许报告 `SET` / `not set`、来源类别和变量名。
6. real tests 必须显式 opt-in，默认 skip，并限制模型、超时、token、调用次数与网络目标。
7. 任何怀疑已进入日志、聊天、commit、artifact 或共享终端记录的 key 都应立即 rotate；之后再做 remove 和 history audit。

### Current local finding

- 路径：`config/config.yaml`
- 变量/字段：`provider.api_key` → 建议迁移到 `provider.api_key_env`
- 风险：**High（local working tree）**。该文件与 `HEAD` 不同，并检测到疑似非占位 key；值未读取、未输出。
- Git 状态：该路径被 Git 跟踪且标记 `skip-worktree`，普通 `git status` 不会提示本地差异。
- 历史审计：对 `git rev-list --all -- config/config.yaml` 返回的可达 refs 做无值扫描；规则只判定 `api_key` 行是否为空或等于 `sk-REPLACE_ME`，疑似非占位命中数为 0。该结果只覆盖此字段/规则，不是全仓 secret scanner 或穷尽性无泄露证明。
- 建议：将该 credential 视为可能暴露并 rotate；从 tracked 路径移除真实值；迁移到 `api_key_env` + `.env`；复核 shell history、日志和共享 artifact；保留 Git history audit 结果。不要在本轮自动删除或改写用户本地配置。

## 8. Activation Path

### Category A conclusion

当前属于 **A**，但仅表示已有可 opt-in 的 real adapter smoke。安全激活顺序：

1. 先 rotate 当前疑似位于 tracked local config 的 credential，并从 tracked 路径移除真实值；
2. 另开 scoped safety-hardening：实现 `config/config.local.yaml`（git 忽略，可含 inline key）、完善 endpoint allowlist、response/exception 脱敏、tracked markers、shared fail-closed env/endpoint/budget guard；
3. 为 real smoke 增加 HTTPS + exact-host allowlist、provider response/exception 脱敏、禁止打印 provider content、tracked markers、共享 fail-closed env/endpoint/budget guard；
4. 修正 core-loop real/fake guard，确保 `FakeProvider` 不能满足 real-provider gate；
5. 由本地 secret manager 或 CI secret store 注入 credential，owner 明确授权一次受控 real provider 调用；
6. 先只运行 minimal adapter smoke，记录 provider type/model、approved host、时间、测试结果和成本，不记录 key；
7. adapter smoke 通过后，再补并运行 success/failure/fallback tests；
8. 再另开 bounded adversarial suite；默认 suite 始终不调用真实 API；
9. 只有真实 opt-in evidence 通过后，才更新 trigger 证据；不能自动把 Provider 提升到 L4。

用户需要准备：受控 credential、approved provider/model/exact host、预算上限、授权记录和可隔离的运行环境。Coding agent 当前允许继续做 docs/test plan 或下一轮 scoped safety-hardening；不允许接新 provider、改默认 provider、写 key、运行真实 API 或默认启用 real tests。

## 9. Do Not Do Yet

- Do not commit API key.
- Do not put API key in prompt.
- Do not run real provider tests by default.
- Do not make real provider default-on.
- Do not claim L4 without real evidence.
- Do not implement adversarial real-provider suite before key path is safe.
- Do not use the current `config/config.yaml` tracked-path pattern as the CI secret design.
- Do not treat synthetic HTTP/mock tests or fake-provider golden as real-provider evidence.

## 10. Evidence Appendix

### Source

- `agent/provider/protocol.py`
- `agent/provider/factory.py`
- `agent/provider/config.py`
- `agent/provider/simple_config.py`
- `agent/provider/profiles.py`
- `agent/provider/fake_provider.py`
- `agent/provider/anthropic_native.py`
- `agent/provider/anthropic_http.py`
- `agent/provider/openai_native.py`
- `agent/provider/openai_http.py`
- `agent/model_call.py`
- `config.py`
- `main.py`

### Tests

- `tests/test_provider_contract.py`
- `tests/test_provider_real_smoke.py`
- `tests/test_agentloop_mcp_e2e.py`
- `tests/runtime_integration/test_memory_anchor_real.py`
- `tests/test_provider_anthropic_http.py`
- `tests/test_provider_openai_http.py`
- `tests/test_provider_openai_native.py`
- `tests/test_provider_diagnostics.py`
- `tests/test_config_env_resolution.py`
- `tests/test_config_secret_safety.py`
- `tests/adversarial/test_minimal_policy_stub.py`
- `tests/test_mcp_policy_gate.py`

### Docs and config

- `AGENTS.md`
- `README.md`
- `docs/CAPABILITY_BOUNDARIES.md`
- `docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md`
- `docs/design/unified-project-config-contract.md`
- `docs/design/config-legacy-sunset-contract.md`
- `docs/06-audit/ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md`
- `docs/06-audit/ARCHITECTURE_REPAIR_MAINLINE_RETROSPECTIVE.zh.md`
- `docs/07-module-maturity/AGENT_MODULE_MATURITY_AUDIT.zh.md`
- `docs/07-module-maturity/POST_REPAIR_TRIGGER_REGISTRY.zh.md`
- `.gitignore`
- `.env.example`
- `config/config.example.yaml`
- `config/examples/*.yaml`

Graphify 仅用于发现以上路径和关系；所有结论均回到真实源码、测试、docs 与 Git 状态核验。`graphify-out/*` 不在本次提交范围。

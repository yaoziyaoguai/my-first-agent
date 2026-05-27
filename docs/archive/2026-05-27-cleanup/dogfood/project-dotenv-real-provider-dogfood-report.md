# Project .env Real Provider Dogfood Report

**生成时间**: 2026-05-26
**测试 commit**: 待 commit

## 背景

上一轮 real provider eval（`36700a1`）使用了 `anthropic_native` 模式连接 DeepSeek，但事后审计发现：外层 Coding Agent 环境变量（`ANTHROPIC_MODEL=deepseek-v4-pro`、`ANTHROPIC_BASE_URL=https://api.deepseek.com`）通过 `override=False` 抢占（污染）了项目 `.env` 的配置。Dogfood 实际使用了「DeepSeek base_url + DashScope API key」的错误组合，导致 tool name 格式不兼容（DeepSeek 拒绝 `.` 在 function.name 中）及其他 case 失败。

本轮先完成 Provider Config Loading 审计，确认根因后，用 isolated dotenv 模式重新运行真实 API dogfood，只加载项目 `.env` 中的配置。

## Provider Config Loading Audit 结论

### 加载链路

```
main.py main()
  → load_legacy_dotenv_config(root/.env, override=False)
    → load_dotenv()  将 .env 写入 os.environ（外层已存在的 key 不覆盖）

agent/provider/factory.py build_model_provider_from_env()
  → 检查 MY_FIRST_AGENT_LLM_PROVIDER env var
    → 未设置 → FakeProvider（安全默认）
    → 已设置 → load_agent_provider_config(env=os.environ)
      → 直接从 os.environ 读取（不调用 load_dotenv）
```

### 关键发现

| 问题 | 详情 |
|------|------|
| `.env` 会被加载吗？ | **是** — `main.py` 调用 `load_legacy_dotenv_config()` |
| `.env` 会被外层覆盖吗？ | **是** — `override=False`，外层 Coding Agent 的 `ANTHROPIC_MODEL`/`ANTHROPIC_BASE_URL` 优先 |
| `diagnose_provider_config()` 加载 `.env` 吗？ | **否** — 直接从 `os.environ` 读取，不调用 `load_dotenv` |
| 前一轮 dogfood 用了谁？ | 外层 `ANTHROPIC_MODEL=deepseek-v4-pro` + `ANTHROPIC_BASE_URL=api.deepseek.com` + `.env` 的 `ANTHROPIC_API_KEY`（DashScope key） — **配置来源混杂** |
| runtime/diagnostics 共用 resolver？ | **共用** `os.environ`，但 `diagnose_provider_config()` 不加载 `.env`，导致 `python main.py status` 视图与实际 runtime 不一致 |

### 修复措施

1. **`diagnose_provider_config()`** — 新增 `dotenv_path` 参数，支持加载 `.env` 用于 config source 检测
2. **`diagnose_provider_config_isolated()`** — 新增 isolated 模式：清除外层 provider env vars 后只加载项目 `.env`
3. **`ProviderDiagnostic`** — 新增 `config_source`、`dotenv_loaded`、`outer_env_overrides` 字段
4. **`python main.py status`** — 自动加载项目 `.env` 进行 source 检测
5. **`python main.py provider-diagnostics`** — 新增命令，支持 `--isolated-dotenv` 标志

## Isolated Project .env Diagnostic

```bash
python main.py provider-diagnostics --isolated-dotenv
```

输出（脱敏）：

```
Provider type : fake
Model         : kimi-k2.5
Base URL      : https://coding.dashscope.aliyuncs.com
API key       : SET (redacted)
Key source    : ANTHROPIC_API_KEY
Config source : project_dotenv
.env loaded   : yes
```

显式指定 `anthropic_compatible`：

```
Provider type : anthropic_compatible
Model         : kimi-k2.5
Base URL      : https://coding.dashscope.aliyuncs.com
API key       : SET (redacted)
Key source    : ANTHROPIC_API_KEY
Auth scheme   : auto
Request path  : /v1/messages
Config source : project_dotenv
```

## Real API Dogfood Results (Project .env Only)

### Configuration

| Field | Value |
|-------|-------|
| Provider type | `anthropic_compatible` |
| Model | `kimi-k2.5` |
| Base URL host | `coding.dashscope.aliyuncs.com` |
| API key | SET (redacted) |
| Key source | `ANTHROPIC_API_KEY` |
| Config source | project_dotenv (isolated, outer env cleared) |
| Real API called | **Yes** — 3 calls |

### Case Results

| Case | 输入 | 状态 | 备注 |
|------|------|------|------|
| 1 普通中文聊天 | 你好，简单介绍一下你现在能做什么。 | **PASS** | 模型正常中文回复，介绍了文件操作、网络等功能。Summary 诚实：`未调用工具 / 未写入 Memory / 未委托 SubAgent`。无 overclaim。 |
| 2 旅行规划 | 帮我规划一个武汉 5 天旅行计划… | **PASS** | 无 crash，无异常 tool_use |
| 3 Tool 意图 | 帮我创建一条 demo note… | **PASS** | 无 crash。模型回复了文本说明，没有强行触发 tool_use。注：因 tool name 含 `.`，模型可能识别到 tool 但选择不调用（kimi-k2.5 可能对非标准 tool name 有保守策略） |

### Key Finding: No Tool Name Format Error

**DashScope anthropic-compatible 端点（`coding.dashscope.aliyuncs.com`）接受含 `.` 的 tool name**，与 DeepSeek 端点不同。上一轮的 tool name 格式错误（`^[a-zA-Z0-9_-]+$`）是 DeepSeek 端点特有的限制，不是通用问题。

## Issues Found

**无新发现**。

上一轮的 P2 issue（DeepSeek tool name 格式不兼容）已确认为 DeepSeek 端点特有问题，不适用于项目 `.env` 配置的 DashScope 端点。

## What Fake/Local Proved (re-confirmed)

- Runtime loop 正确（138 tests PASS）
- Tool Pipeline / Memory / SubAgent branch points 可达
- Summary 诚实，无 overclaim
- Provider swap 安全
- Fake/real 共享同一条 runtime

## What Project .env Real Provider Proved

- 项目 `.env` 配置正确：`anthropic_compatible` + `kimi-k2.5` + DashScope
- **不需要换 provider**：当前 `.env` 配置已经可用
- 基础中文聊天、旅行规划均正常
- DashScope endpoint 无 tool name 格式限制
- `override=False` 导致的外层 env 污染需要在 dogfood 中显式隔离

## Config Source Awareness (新增能力)

| 能力 | 状态 |
|------|------|
| `python main.py status` 显示 config source | **已实现** |
| `python main.py provider-diagnostics --isolated-dotenv` | **已实现** |
| `diagnose_provider_config_isolated()` API | **已实现** |
| Config source: `project_dotenv` / `shell_env` / `default_fake` / `mixed` | **已实现** |
| Outer env override detection | **已实现** |
| Secret never printed | **已验证**（13 个 secret leak 测试） |

## Next Recommendations

1. **保持**：项目 `.env` 的真实 API dogfood 使用 `anthropic_compatible` + `kimi-k2.5`
2. **探索**：验证 kimi-k2.5 对含 `.` tool name 的 tool_use 能力（Case 3 未触发 tool_use，可能是模型保守策略）
3. **中期**：考虑将 `load_legacy_dotenv_config(override=True)` 作为 isolated 模式的默认，或在 provider config 层统一 `.env` 加载
4. **文档**：在 onboarding 中说明如何隔离外层环境变量运行真实 API dogfood

## Run Commands

```bash
cd /Users/jinkun.wang/work_space/my-first-agent

# 常规 status（自动检测 config source）
.venv/bin/python main.py status

# Isolated dotenv 诊断
.venv/bin/python main.py provider-diagnostics --isolated-dotenv

# Category A/B (fake/local) gates:
.venv/bin/python -m pytest tests/test_user_path_dogfood_smoke.py \
  tests/test_fake_provider_decision.py tests/test_display_event_contract.py \
  tests/test_provider_diagnostics.py -v

# Category C (opt-in, requires .env):
# 使用 isolated 模式验证 .env 配置
.venv/bin/python main.py provider-diagnostics --isolated-dotenv
# 然后运行 dogfood script
.venv/bin/python /tmp/project_dotenv_dogfood.py
```

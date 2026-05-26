# Unified Project Config Contract

**版本**: v1.1
**日期**: 2026-05-27
**状态**: design

## 设计动机

经过两轮 provider 配置演进（legacy env vars → provider profiles），暴露了一个根本问题：
用户只是为了切换模型，不应该需要学习「profile 名称」或记住 `kimi_anthropic` 这种内部标识符。

**本设计的核心原则**：一个文件说清所有配置。用户打开 `config/config.yaml` 就知道当前用的什么模型。

## 配置分层

| 文件 | 内容 | 提交到 git |
|------|------|-----------|
| `config/config.yaml` | 非敏感项目配置（provider、runtime、memory…） | 是（需确保 api_key 为 sk-REPLACE_ME） |
| 用户本地 `config/config.yaml` | 含真实 api_key | 否 |

## config/config.yaml 结构

```yaml
# First Agent 统一项目配置
# 复制 config/config.example.yaml 并按需修改

# --- Provider 配置 ---
provider:
  # enabled: true 启用真实 provider，false 使用 fake 安全路径
  enabled: false
  # type: anthropic_compatible | openai_compatible | anthropic_native | openai_native | fake
  type: fake
  model: fake-llm
  # 以下字段仅在 enabled: true 时需要
  base_url: ""           # 兼容模式必需
  api_key: ""            # 真实 API key（不可提交 git）

# --- Runtime 配置（后续实现）---
# runtime:
#   max_tokens: 128000
#   max_messages: 100

# --- Memory 配置（后续实现）---
# memory:
#   max_episodes: 50

# --- Logging 配置（后续实现）---
# logging:
#   level: info

# --- Workspace 配置（后续实现）---
# workspace:
#   root: .

# --- Tools 配置（后续实现）---
# tools:
#   confirm_before_write: true
```

**本轮只消费 `provider` section**。其他 section 的 key 名是预留的，后续逐步实现。

**用户只需配置 5 个字段**：`enabled`, `type`, `model`, `base_url`, `api_key`。
`request_path` 和 `auth_scheme` 由 provider adapter 内部决定，不在用户配置中暴露：
- `anthropic_compatible` → adapter 使用 `/v1/messages` + `x-api-key` 认证
- `openai_compatible` → adapter 使用 `/v1/chat/completions` + `Bearer` 认证

## Config Source Precedence

```
1. config/config.yaml provider section（推荐入口）
2. FIRST_AGENT_PROVIDER_PROFILE legacy fallback（已废弃，仍可用）
3. MY_FIRST_AGENT_LLM_PROVIDER + 分散 env vars（legacy fallback）
4. default fake（安全默认）
```

当 config.yaml 存在时，优先级 2、3 被跳过并记录在 diagnostics 中。

## Provider Resolution Flow

```
build_model_provider_from_env()
  │
  ├─ config/config.yaml 存在？
  │   ├─ 是 → provider.enabled？
  │   │   ├─ true  → 从 YAML 读取 provider config → AgentProviderConfig
  │   │   │          api_key 直接从 provider.api_key 字段读取
  │   │   └─ false → FakeProvider
  │   └─ 否 → 继续
  │
  ├─ FIRST_AGENT_PROVIDER_PROFILE 已设置？
  │   └─ 是 → 现有 profile 路径（legacy）
  │
  ├─ MY_FIRST_AGENT_LLM_PROVIDER 已设置？
  │   └─ 是 → 现有 env var 路径（legacy）
  │
  └─ 都没有 → FakeProvider
```

## Diagnostics Output Contract

```
============================================================
  Provider Config Diagnostic
============================================================

  Config source : config_yaml (/path/to/config/config.yaml)
  Provider type : anthropic_compatible
  Model         : kimi-k2.5
  Base URL      : https://coding.dashscope.aliyuncs.com
  API key       : SET (inline, redacted)
  .env loaded   : yes/-- (not checked for yaml source)

  Status        : OK
```

**不再显示** `Key env`、`Auth scheme`、`Request path`——这些是 adapter 内部实现细节。

**Config source 取值**：

| 值 | 含义 |
|---|------|
| `config_yaml` | 当前配置来自 config/config.yaml（provider.enabled=true） |
| `config_yaml_disabled` | config.yaml 存在但 provider.enabled=false |
| `project_dotenv` | 只从项目 .env 加载（isolated 模式） |
| `shell_env` | 只从外层进程环境变量 |
| `default_fake` | 无任何配置，fake 兜底 |
| `legacy_profile` | 来自 FIRST_AGENT_PROVIDER_PROFILE + provider_profiles.yaml |
| `legacy_provider_env` | 来自 MY_FIRST_AGENT_LLM_PROVIDER + 分散 env vars |
| `mixed` | 多个来源混合 |

## Security / Redaction

1. `config/config.yaml` 中 `api_key` 直接写 key 值（个人本地项目）
2. diagnostics 输出 `SET (inline, redacted)` 或 `not set`
3. `config/config.example.yaml` 可安全提交
4. `config/config.yaml`（含真实 key）不可提交

## 示例

### Anthropic-compatible (kimi via DashScope)

```yaml
provider:
  enabled: true
  type: anthropic_compatible
  model: kimi-k2.5
  base_url: https://coding.dashscope.aliyuncs.com/apps/anthropic
  api_key: sk-xxxxxxxx
```

### OpenAI-compatible (glm via DashScope)

```yaml
provider:
  enabled: true
  type: openai_compatible
  model: glm-5
  base_url: https://coding.dashscope.aliyuncs.com/v1
  api_key: sk-xxxxxxxx
```

### Fake / safe local

```yaml
provider:
  enabled: false
  type: fake
  model: fake-llm
```

或不创建 config/config.yaml。

## 与统一 Runtime 的关系

```
用户输入 → core.chat()
  → loop.py: run_agent_loop()
    → call_model() → provider.create() / provider.stream()
      ↑                        ↑
      |                        |
  AgentProviderConfig    ModelProvider (Fake or Real)
      ↑
      | config/config.yaml → provider section → AgentProviderConfig
      | 或 legacy profile/env → AgentProviderConfig
      | 或 default fake
```

**关键不变量**：config.yaml 只在配置解析阶段存在。一旦 `AgentProviderConfig` 产生，后续所有代码不变。

## Backward Compatibility

- `FIRST_AGENT_PROVIDER_PROFILE` + `config/provider_profiles.yaml` → 当 config.yaml 不存在时仍然有效
- `MY_FIRST_AGENT_LLM_PROVIDER` → 当以上都不存在时仍然有效
- 所有现有 tests 不修改即可通过

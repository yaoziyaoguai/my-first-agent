# Provider Profile Config Contract

**版本**: v1.0
**日期**: 2026-05-26
**状态**: superseded（由 docs/design/unified-project-config-contract.md 取代）

> ⚠️ 本文档描述的 `FIRST_AGENT_PROVIDER_PROFILE` + `provider_profiles.yaml` 方案已被 `config/config.yaml` 统一配置入口取代。profile 路径保留为 legacy fallback（仅 config.yaml 不存在时生效），不作为推荐用户路径。详见 docs/design/config-legacy-sunset-contract.md。

## 问题陈述

当前 provider 配置体验存在「幽灵配置」问题：

1. 用户在 `.env` 中配置了 `ANTHROPIC_MODEL=kimi-k2.5`、`ANTHROPIC_BASE_URL=...`、`ANTHROPIC_API_KEY=...`
2. `python main.py status` 显示 `Provider type: fake`，因为 `MY_FIRST_AGENT_LLM_PROVIDER` 未设置
3. 用户困惑：「我明明配了模型和 key，为什么 provider 还是 fake？」

**根因**：当前设计只有一个 master switch（`MY_FIRST_AGENT_LLM_PROVIDER`），它必须在 `.env` 中显式设置。即使 model/base_url/key 全部存在，缺少这个开关就回退 fake。配置参数和 provider 选择之间缺少显式的绑定关系。

## 设计目标

1. **显式 active profile**：用户通过一个环境变量选择命名 profile，profile 内聚所有配置
2. **fake 仍是默认**：不设 profile → fake，保持安全默认
3. **secret 隔离**：profile 文件不存 key，只存 `api_key_env` 变量名
4. **可诊断**：`status` / `provider-diagnostics` 明确显示 active profile、config source、key present
5. **向后兼容**：`MY_FIRST_AGENT_LLM_PROVIDER` 等 legacy env var 继续工作
6. **配置层变更，不动 runtime**：profile 只改变配置解析方式，不新增 runtime flow

## 核心概念

### ProviderProfile

```python
@dataclass(frozen=True)
class ProviderProfile:
    name: str                    # "fake" | "kimi_anthropic" | "glm_openai"
    provider_type: str           # "fake" | "anthropic_compatible" | "openai_compatible" | ...
    model: str                   # "kimi-k2.5" | "glm-5" | "fake-llm"
    base_url: str | None         # 兼容模式必需
    api_key_env: str | None      # env var 名，不是 key 值。如 "ANTHROPIC_API_KEY"
    request_path: str            # "/v1/messages" | "/v1/chat/completions"
    auth_scheme: str             # "auto" | "bearer" | "x-api-key"
    max_tokens: int              # 默认 4096
    timeout: float               # 默认 30.0
```

### Active Profile 决议顺序

```
FIRST_AGENT_PROVIDER_PROFILE (推荐)
  → 从 config/provider_profiles.yaml 查找同名 profile
  → 解析出 AgentProviderConfig

MY_FIRST_AGENT_LLM_PROVIDER (legacy, 兼容)
  → 从 os.environ 读取各字段（现行逻辑）
  → 解析出 AgentProviderConfig

无任何配置
  → FakeProvider (默认安全路径)
```

### Profile 文件格式

`config/provider_profiles.yaml`：

```yaml
# First Agent Provider Profiles
# 此文件不包含 secret — api_key 只存环境变量名
active_profile: fake  # 可通过 FIRST_AGENT_PROVIDER_PROFILE 覆盖

profiles:
  fake:
    type: fake
    model: fake-llm

  kimi_anthropic:
    type: anthropic_compatible
    model: kimi-k2.5
    base_url: https://coding.dashscope.aliyuncs.com/apps/anthropic
    api_key_env: ANTHROPIC_API_KEY
    request_path: /v1/messages
    auth_scheme: auto

  glm_openai:
    type: openai_compatible
    model: glm-5
    base_url: https://coding.dashscope.aliyuncs.com/v1
    api_key_env: OPENAI_API_KEY
    request_path: /v1/chat/completions
    auth_scheme: bearer
```

### .env 示例

```bash
# 选择 active profile（覆盖 YAML 中的 active_profile 默认值）
FIRST_AGENT_PROVIDER_PROFILE=kimi_anthropic

# secrets — profile 文件中只引用变量名，值存于此
ANTHROPIC_API_KEY=sk-xxxxxxxx
OPENAI_API_KEY=sk-xxxxxxxx
```

## Config Source Precedence

```
process env FIRST_AGENT_PROVIDER_PROFILE
  > YAML active_profile (当 env var 未设置时)
  > 默认 fake

profile 中每个字段可被 process env 覆盖（用于 emergency override）:
  process env ANTHROPIC_MODEL > profile model
  process env ANTHROPIC_BASE_URL > profile base_url
  process env ANTHROPIC_API_KEY > profile api_key_env 指向的值
```

覆盖关系在 diagnostics 中可见：当 process env 覆盖了 profile 字段时，`config_source` 显示 `mixed` 并列出覆盖项。

## 向后兼容

| 旧方式 | 新方式 | 过渡策略 |
|--------|--------|---------|
| `MY_FIRST_AGENT_LLM_PROVIDER=anthropic_compatible` | `FIRST_AGENT_PROVIDER_PROFILE=kimi_anthropic` | 旧方式继续有效，但 diagnostics 提示推荐新方式 |
| `ANTHROPIC_MODEL=kimi-k2.5` 分散设置 | profile 内聚 `model: kimi-k2.5` | 旧 env var 作为 profile 字段的 override 源 |
| `ANTHROPIC_API_KEY=...` | `.env` 中的 `ANTHROPIC_API_KEY` + profile 中 `api_key_env: ANTHROPIC_API_KEY` | 不变，key 仍在 `.env` |

`load_agent_provider_config()` 和 `build_model_provider_from_env()` 的公开签名不变。新增的 profile 解析在调用这些函数之前完成。

## Status / Diagnostics Output Contract

```
============================================================
  Provider Config Diagnostic
============================================================

  Active profile: kimi_anthropic (from FIRST_AGENT_PROVIDER_PROFILE)
  Provider type : anthropic_compatible
  Model         : kimi-k2.5
  Base URL      : https://coding.dashscope.aliyuncs.com
  API key       : SET (redacted)
  Key env       : ANTHROPIC_API_KEY
  Auth scheme   : auto
  Request path  : /v1/messages
  Config source : project_dotenv
  .env loaded   : yes

  Status        : OK

  结论：provider 配置无问题。
  配置看起来完整，但连接性需 manual dogfood 验证。
```

fake 模式输出：

```
  Active profile: fake (default)
  Provider type : fake
  ...
  provider mode = fake (local only) — 不调用真实 API。
  如需切换到真实 LLM，请设置 FIRST_AGENT_PROVIDER_PROFILE=kimi_anthropic
  （或 FIRST_AGENT_PROVIDER_PROFILE=glm_openai）。
```

## Security / Redaction Rules

1. `api_key_env` 只存变量名（如 `ANTHROPIC_API_KEY`），不存 key 值
2. profile YAML 文件中不包含 secret
3. diagnostics 输出 `SET (redacted)` 或 `not set`，不打印 key prefix/suffix
4. profile 文件可安全提交到 git
5. `.env` 不可提交（已在 `.gitignore`）

## 与统一 Runtime 的关系

```
用户输入 → core.chat()
  → loop.py: run_agent_loop()
    → call_model() → provider.create() / provider.stream()
      ↑                        ↑
      |                        |
  AgentProviderConfig    ModelProvider (Fake or Real)
      ↑
      | 由 profile resolver 或 legacy env 解析
      |
  ProviderProfile (新增，配置层)
```

**关键不变量**：Profile 只在配置解析阶段存在。一旦 `AgentProviderConfig` 产生，后续所有代码（factory、diagnostics、runtime）行为不变。这不是 runtime 分叉。

## Migration Plan

1. **v0.11**: 新增 `agent/provider/profiles.py` 和 `config/provider_profiles.yaml`
   - `FIRST_AGENT_PROVIDER_PROFILE` 可用
   - `MY_FIRST_AGENT_LLM_PROVIDER` 继续工作
   - diagnostics 显示 active profile
2. **v0.12**: 所有文档和示例切换到 profile 方式
   - legacy env var 标记为 deprecated 但仍支持
3. **v0.13+**: 移除 legacy env var 支持（视情况）

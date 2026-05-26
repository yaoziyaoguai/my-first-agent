# Config Legacy Sunset Contract

**版本**: v1.0
**日期**: 2026-05-26
**状态**: active

## 设计动机

Unified Project Config (`config/config.yaml`) 已落地作为唯一推荐配置入口。此前遗留的三套 provider 配置路径（`FIRST_AGENT_PROVIDER_PROFILE`、`MY_FIRST_AGENT_LLM_PROVIDER`、分散 env vars）需要明确标记为 legacy，并定义 sunset 时间线和行为契约。

核心原则：**legacy 路径是短期兼容层，不是推荐路径。用户可见的所有 next-step guidance 必须指向 config/config.yaml。**

## Recommended Path（唯一推荐入口）

```
config/config.yaml  provider section  +  .env  secrets
```

用户流程：

1. 编辑 `config/config.yaml` 的 `provider` section
2. 设置 `enabled: true`，选择 `type`/`model`/`base_url`/`api_key_env`
3. 在 `.env` 中设置 `api_key_env` 对应的 key 值
4. 运行 `python main.py status` 验证
5. 运行 real dogfood

## Legacy Paths（标记 deprecated）

| Legacy Path | 机制 | 保留原因 | Sunset 条件 |
|---|---|---|---|
| `FIRST_AGENT_PROVIDER_PROFILE` | env var → `config/provider_profiles.yaml` 查表 | 历史用户可能仍设置了该变量 | config.yaml dogfood 通过后移除 |
| `MY_FIRST_AGENT_LLM_PROVIDER` | 单 env var → 分散 env vars | 最早期的配置方式 | config.yaml dogfood 通过后移除 |
| `config/provider_profiles.yaml` | YAML profile 定义文件 | 被 FIRST_AGENT_PROVIDER_PROFILE 引用 | 与 profile env 一起移除 |

## Legacy Fallback 行为契约

1. **config/config.yaml 存在时**：legacy env/profile **完全忽略**，不参与 provider resolution。
2. **config/config.yaml 不存在时**：legacy env/profile 作为 fallback 生效，但：
   - diagnostics 标记 `config_source=legacy_profile` 或 `legacy_provider_env`
   - status 输出包含 `(legacy fallback — not recommended)`
   - 不提供 "设置 MY_FIRST_AGENT_LLM_PROVIDER=..." 作为下一步建议
3. **config/config.yaml 存在 + legacy env 也设置时**：config.yaml 生效，legacy env 被忽略并在 diagnostics 中标记 `Legacy provider env/profile detected but ignored because config/config.yaml exists.`

## Diagnostics Output Contract

### config/config.yaml 存在时

```
Config source : config_yaml (/path/to/config/config.yaml)
Provider type : anthropic_compatible
...
Legacy env    : ignored (MY_FIRST_AGENT_LLM_PROVIDER=anthropic_native detected but config.yaml takes precedence)
```

### config/config.yaml 不存在，但有 legacy fallback

```
Config source : legacy_provider_env (MY_FIRST_AGENT_LLM_PROVIDER)
                ⚠️  legacy fallback — not recommended
                → create config/config.yaml for current setup:
                  cp config/config.example.yaml config/config.yaml
```

### 完全无配置

```
Config source : default_fake
                → create config/config.yaml for current setup:
                  cp config/config.example.yaml config/config.yaml
```

## 用户可见 Next Step 契约

| 当前状态 | 旧文案（禁止） | 新文案（必须） |
|---|---|---|
| fake 模式 | "设置 MY_FIRST_AGENT_LLM_PROVIDER=..." | "编辑 config/config.yaml，设置 enabled: true..." |
| 缺少 API key | "设置 ANTHROPIC_API_KEY 或 OPENAI_API_KEY" | "在 .env 中设置 {api_key_env}=<your-key>" |
| 缺少 model | "设置 ANTHROPIC_MODEL 或 MY_FIRST_AGENT_LLM_MODEL" | "在 config/config.yaml 中填写 model 字段" |
| 无效 provider | "设置 MY_FIRST_AGENT_LLM_PROVIDER 为以下之一" | "在 config/config.yaml 中设置 type 为支持的类型" |

## 不允许的行为

1. ❌ user-facing next step 中引用 `MY_FIRST_AGENT_LLM_PROVIDER` / `FIRST_AGENT_PROVIDER_PROFILE`
2. ❌ 新 tests 继续扩大 legacy 路径覆盖
3. ❌ 新文档推荐 legacy env/profile 作为配置方式
4. ❌ config.yaml 与 legacy env 同时生效（混用）
5. ❌ 新增 provider profiles / provider use / write-env 命令

## Sunset Timeline

| 阶段 | 动作 | 触发条件 |
|---|---|---|
| 当前 (2026-05-26) | legacy 保留为 fallback，标记 deprecated | — |
| 下一阶段 | 移除 `FIRST_AGENT_PROVIDER_PROFILE` 支持 | config.yaml dogfood 通过 |
| 下一阶段 | 移除 `MY_FIRST_AGENT_LLM_PROVIDER` 支持 | config.yaml dogfood 通过 |
| 下一阶段 | 移除 `config/provider_profiles.yaml` | profile env 移除后 |
| 最终 | 移除 `agent/provider/profiles.py` | 所有 profile 引用移除后 |

## 与 Unified Runtime 的关系

```
config/config.yaml（推荐入口）
    ↓ 不存在时
legacy env/profile（fallback，标记 deprecated，不在用户引导中出现）
    ↓ 也不存在时
default fake（安全默认）
```

无论配置来自哪个入口，最终都产生 `AgentProviderConfig`，进入统一的 `core.chat() → loop.py → call_model()` 路径。配置入口的选择不影响 runtime 行为。

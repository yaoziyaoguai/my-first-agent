# Provider Profile Config Remediation Plan

**日期**: 2026-05-26
**状态**: superseded（profile 路径已被 config/config.yaml 统一入口取代）
**依赖**: docs/design/provider-profile-config-contract.md

> ⚠️ 2026-05-26 更新：本计划提出的 profile 方案已由 `config/config.yaml` 统一配置入口落地。`FIRST_AGENT_PROVIDER_PROFILE` 和 `MY_FIRST_AGENT_LLM_PROVIDER` 保留为 legacy fallback（仅 config.yaml 不存在时生效），标记 deprecated，不作为推荐用户路径。后续里程碑将移除所有 legacy 路径。详见 docs/design/config-legacy-sunset-contract.md。

## 背景

当前 `MY_FIRST_AGENT_LLM_PROVIDER` 是唯一 provider 开关，但用户已在 `.env` 中配置了完整的 model/base_url/key，却因为没有设置这个开关而得到 fake。新的 profile 方案通过命名 profile 内聚所有配置，用 `FIRST_AGENT_PROVIDER_PROFILE` 一个变量切换。

## 实现单元

### U1: 新增 ProviderProfile 数据模型 + YAML loader

**Goal**: 新增 `agent/provider/profiles.py`，定义 `ProviderProfile` dataclass 和 YAML 加载函数。

**Files**:
- Create: `agent/provider/profiles.py`
- Create: `config/provider_profiles.yaml`

**Approach**:
- `ProviderProfile` 是 frozen dataclass，字段与设计文档一致
- `load_provider_profiles(path)` 从 YAML 加载所有 profile
- `resolve_active_profile(profiles, env)` 按优先级决议 active profile:
  1. `FIRST_AGENT_PROVIDER_PROFILE` env var
  2. YAML 中 `active_profile` 字段
  3. `"fake"` 兜底
- `profile_to_agent_config(profile, env)` 将 ProviderProfile 转换为现有 `AgentProviderConfig`
- YAML 解析失败 → 明确错误信息 → fallback fake

**Execution note**: test-first — 先写 U4 测试再写实现。

### U2: 集成到 factory + diagnostics

**Goal**: `build_model_provider_from_env()` 和 `diagnose_provider_config()` 支持 profile 路径。

**Files**:
- Modify: `agent/provider/factory.py` — `build_model_provider_from_env()` 增加 profile 解析步骤
- Modify: `agent/provider/diagnostics.py` — 显示 active profile name
- Modify: `agent/cli/commands.py` — `status` 和 `provider-diagnostics` 命令显示 profile 信息

**Approach**:
- `build_model_provider_from_env()`:
  1. 检查 `FIRST_AGENT_PROVIDER_PROFILE` → 有 → 从 YAML 加载 profile → 转 AgentProviderConfig → build
  2. 检查 `MY_FIRST_AGENT_LLM_PROVIDER` (legacy) → 有 → 走现有 `load_agent_provider_config()` 路径
  3. 都没有 → FakeProvider
- `diagnose_provider_config()` 增加 `active_profile` 字段
- `render_diagnostic_report()` 显示 active profile 行
- CLI commands 不做改动（diagnostics 内部自行处理）

### U3: 保留 legacy env var 兼容

**Goal**: `MY_FIRST_AGENT_LLM_PROVIDER` + 分散 env var 的旧配置方式继续可用。

**Files**:
- Modify: `agent/provider/profiles.py` — `resolve_active_profile()` 中处理 legacy fallback
- Modify: `agent/provider/diagnostics.py` — 无 profile 但有 MY_FIRST_AGENT_LLM_PROVIDER 时显示 "legacy" 标记

**Approach**:
- 当 `FIRST_AGENT_PROVIDER_PROFILE` 未设置但 `MY_FIRST_AGENT_LLM_PROVIDER` 已设置时：
  - 走 legacy 路径（现有 `load_agent_provider_config()` 逻辑）
  - diagnostics 显示 `Active profile: legacy (MY_FIRST_AGENT_LLM_PROVIDER=xxx)`
- 所有现有测试不做任何修改即可通过

### U4: 测试

**Goal**: 覆盖 profile 配置的所有路径。

**Files**:
- Modify: `tests/test_provider_diagnostics.py` — 新增 profile 相关测试

**Test scenarios**:
1. 无 profile env var + 无 YAML → fake
2. `FIRST_AGENT_PROVIDER_PROFILE=fake` → fake
3. `FIRST_AGENT_PROVIDER_PROFILE=kimi_anthropic` + temp YAML → anthropic_compatible
4. `api_key_env` 指向的 env var 未设置 → clear diagnostic
5. key present → redacted 输出
6. process env 覆盖 profile 字段 → mixed source
7. isolated dotenv 加载 profile → project_dotenv
8. legacy `MY_FIRST_AGENT_LLM_PROVIDER` still works
9. profile 文件不存在 → fallback fake + warning
10. profile 文件中引用不存在的 profile name → error
11. no secret printed in any diagnostic output

**Patterns to follow**: 现有 `test_provider_diagnostics.py` 使用临时 `.env` + monkeypatched `os.environ`

### U5: 文档更新

**Goal**: 更新 README 和相关文档，说明新 profile 配置方式。

**Files**:
- Modify: `README.md` — provider 配置章节
- Modify: `docs/dogfood/project-dotenv-real-provider-dogfood-report.md` — 更新推荐命令

### U6: 可选真实 API smoke

**Goal**: 用 profile 方式跑最小真实 API 验证。

**Deferred until**: U1-U5 完成且用户授权。

## Scope Boundaries

- 不改变 `AgentProviderConfig` dataclass
- 不改变 `ModelProvider` Protocol
- 不改变 `core.chat()` / `loop.py` / `call_model()`
- 不改变统一 runtime flow
- 不新增 RuntimeActionType / handler
- 不修改 `config.py` legacy compatibility layer
- profile YAML 路径硬编码为 `config/provider_profiles.yaml`（后续可配置化）

## Verification

每个单元完成后的验证：
1. `ruff check agent/provider/profiles.py tests/test_provider_diagnostics.py`
2. `pytest tests/test_provider_diagnostics.py -v`
3. `pytest tests/test_user_path_dogfood_smoke.py tests/test_fake_provider_decision.py tests/test_display_event_contract.py -v`
4. `python main.py status` 输出包含 active profile
5. `python main.py provider-diagnostics --isolated-dotenv` 输出包含 active profile

Full gate:
```bash
HOME=/private/tmp .venv/bin/python -m pytest tests/ -x -q
```

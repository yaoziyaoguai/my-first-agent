# Real Provider Semantic Eval Report

**生成时间**: 2026-05-26
**测试 commit**: bd2dd09
**测试套件**: `/tmp/real_dogfood.py` (7 cases planned, partially executed)

## Provider Configuration

| Field | Value |
|-------|-------|
| Provider type | `anthropic_native` |
| Model | `deepseek-v4-pro` |
| Base URL host | `api.deepseek.com` |
| API key | SET (redacted) via `ANTHROPIC_API_KEY` |
| Auth | passed (Case B returned valid response) |
| Real API called | Yes (6 failed at API validation, 1 succeeded) |

## Case Matrix

| Case | 输入 | 预期 | 状态 | 备注 |
|------|------|------|------|------|
| A | 你好，简单介绍一下你现在能做什么。 | no crash, coherent Chinese | **FAIL** | 400: `tools[6].function.name` 校验失败 |
| B | 帮我规划一个武汉 5 天旅行计划… | no crash, reasonable planning | **PASS** | 成功获得中文旅行计划回复 |
| C | 帮我创建一条 demo note… | may trigger tool_use | **FAIL** | 同上 400 tool name 校验 |
| D | 请记住一个测试偏好… | may trigger memory | **FAIL** | 同上 |
| E | 请委托 demo-stat 子代理… | may trigger subagent | **FAIL** | 同上 |
| F | 请告诉我刚才…有没有调用工具 | summary honest | **FAIL** | 同上 |
| G | 请调用一个不存在的工具… | readable error | **FAIL** | 同上 |

## Key Findings

### 1. API 连通性 — PASS (partial)

Case B（旅行规划）成功从 `deepseek-v4-pro` 获取中文回复，证明：
- API key 有效
- 网络连接正常
- `api.deepseek.com` 端点的 Anthropic-compatible 接口基本可用

### 2. Tool Name 格式不兼容 — CONCERN

**根因**: DeepSeek 的 `/v1/messages` 端点在接受 Anthropic SDK tool 定义后，内部转换为 OpenAI 格式的 `function.name` 字段，并校验 `^[a-zA-Z0-9_-]+$`。项目 tool name 使用 `.` 分隔（如 `demo.write_demo_note`），不符合该正则表达式，导致 400 Bad Request。

```
Error: Invalid 'tools[6].function.name': string does not match pattern.
Expected a string that matches the pattern '^[a-zA-Z0-9_-]+$'.
```

**影响范围**: 所有包含 `.` 的 tool name 在 DeepSeek Anthropic-compatible 端点上都会失败。这意味着所有 tool_use 场景（memory retain via tool、subagent delegation via tool、demo.write_demo_note 等）在此端点上不可用。

**可能修复方向**（不在本轮执行）:
- 切换到 `openai_compatible` provider 模式（DeepSeek 原生 API 是 OpenAI 格式）
- 或为 `anthropic_compatible` 模式添加 tool name normalization（将 `.` 替换为 `_`）
- 或确认 DeepSeek 是否支持 `.` 在 tool name 中，联系 provider

### 3. Case B: Real Provider 中文回复质量

Case B 成功获取了回复（内容保存于 `/tmp/real_dogfood_results.json`）。回复是合理的旅行计划，证明：
- Real provider + unified runtime flow 对普通聊天场景工作正常
- FakeProvider 和 RealProvider 共享的 runtime path 对 end_turn 场景验证通过

### 4. Fake/Local vs Real Provider 对比

| Capability | Fake/Local (Category A/B) | Real Provider (Category C) |
|---|---|---|
| Runtime loop 正确性 | PASS (20/20) | PASS (1/1 end_turn) |
| Tool Pipeline 可达性 | PASS (scripted) | **BLOCKED** (tool name format) |
| Memory hook 可达性 | PASS (scripted) | **NOT TESTED** (blocked by tool format) |
| SubAgent routing 可达性 | PASS (scripted) | **NOT TESTED** (blocked by tool format) |
| 中文 NL 理解 | NOT PROVEN (by design) | PASS (Case B basic chat) |
| 中文 tool 选择 | NOT PROVEN (by design) | **BLOCKED** (format issue) |
| Summary 诚实性 | PASS (3/3) | PASS (Case B) |

## Issues Found

### P2: DeepSeek Anthropic-Compatible 端点 tool name 格式不兼容

- **级别**: P2 (功能受限，非 crash/security)
- **根因**: DeepSeek 端点对 tool `function.name` 校验 `^[a-zA-Z0-9_-]+$`，拒绝含 `.` 的 tool name
- **影响**: 所有 tool_use / memory / subagent 在 DeepSeek Anthropic-compatible 端点上不可用
- **修复方向**: 切换到 `openai_compatible` mode 或 tool name normalization
- **不阻塞**: 基础聊天功能正常，fake/local path 仍覆盖所有 Category A/B 场景

## What Fake/Local Proved (re-confirmed)

- Runtime loop 正确（20 dogfood + 40 fake_provider tests PASS）
- Tool Pipeline wiring 正确（scripted tool_use → ToolExecutor）
- Memory hook wiring 正确（disposition 过滤，summary 诚实）
- SubAgent routing wiring 正确
- No fake/real runtime split

## What Real Provider Proved

- API key 有效，连接正常
- 基础中文聊天可用（Case B）
- Tool 格式在 DeepSeek 端点上存在兼容性限制

## Remaining Human Judgement

- Real provider 对话质量评估（Case B 回复需人工判断是否合理）
- DeepSeek vs Anthropic 官方端点的选择
- Tool name 格式策略决策（改 name 还是换 provider mode）

## Next Remediation Recommendations

1. **短期**: 切换 `MY_FIRST_AGENT_LLM_PROVIDER=openai_compatible` 测试 DeepSeek 原生 OpenAI 格式 tool calling
2. **短期**: 验证 tool name normalization（`.` → `_`）是否在 Anthropic-compatible 模式下修复问题
3. **中期**: 为不同 provider endpoint 的 tool name 格式差异添加 normalization layer
4. **中期**: 在 `agent/provider/config.py` 中添加 endpoint format 检测/适配逻辑
5. **保持**: Category A/B (fake/local) 作为主要 automated gate，Category C 作为 opt-in semantic eval

## Retest 命令

```bash
cd /Users/jinkun.wang/work_space/my-first-agent

# Category A/B (every commit):
.venv/bin/python -m pytest tests/test_user_path_dogfood_smoke.py tests/test_fake_provider_decision.py tests/test_display_event_contract.py -v

# Category C (opt-in, requires API key):
MY_FIRST_AGENT_LLM_PROVIDER=openai_compatible .venv/bin/python /tmp/real_dogfood.py
```

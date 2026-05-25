# Manual Human Dogfood Record Template

**不要在此文件中填写真实 secret、API key、私人资料。**

## 环境信息

| 项目 | 值 |
|------|-----|
| date | YYYY-MM-DD |
| commit | `git rev-parse HEAD` 输出 |
| branch | `git branch --show-current` |
| provider mode | fake / anthropic_native / anthropic_compatible / openai |
| model | 实际使用的 model name |
| OS | macOS / Linux / other |
| Python | `python --version` |

## 启动步骤

### Step 1: 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Step 2: 启动方式

- [ ] `python main.py` → 交互式 CLI
- [ ] `python main.py chat --prompt "..."` → 单次对话
- [ ] 其他：___

启动时看到的 provider mode 横幅：

```
[provider] mode=___
```

期望输出：明确显示 fake 或 real provider，无 secret 泄漏。

### Step 3: Provider 配置（仅真实 API）

设置以下环境变量（**在此只写密钥名称，不写密钥值**）：

```bash
export MY_FIRST_AGENT_LLM_PROVIDER=___
export ANTHROPIC_API_KEY=<REDACTED>
```

## Fake/Local Mode 验证

### F1: 基础对话

- 输入：___
- 期望：返回合理文本，不报错
- 实际输出摘要：___
- 通过/关注/失败：___

### F2: 工具调用

- 输入：触发 tool_use 的 prompt
- 期望：走 Tool Pipeline，结果用户可见
- 工具名/结果摘要：___
- 通过/关注/失败：___

### F3: Memory 写入与召回

- 写入操作：`remember ...` 或 `记住 ...`
- 输入：触发 memory recall 的 prompt
- 期望：写入后在下轮 system prompt 或 `show memories` 中可见
- 通过/关注/失败：___

### F4: SubAgent 委托

- 输入：`delegate to demo-stat: count files` 或 `委托 demo-stat: 统计文件`
- 期望：返回 `[SubAgent: demo-stat]` 结果
- 结果摘要：___
- 通过/关注/失败：___

### F5: Skill 选择

- 输入：触发 skill 的 prompt
- 期望：`show skills` 或自动 skill select
- 通过/关注/失败：___

### F6: 错误恢复

- 输入：触发错误/边界场景的 prompt
- 期望：不 crash，友好提示
- 通过/关注/失败：___

## 可选 Real Provider 验证

**以下步骤需要真实 API key，不在 AutoRun 自动执行范围内。**

仅在手动激活后执行：

```bash
export MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1
```

### R1: 基础对话

- 输入：___
- 实际行为：___
- 通过/关注/失败：___

### R2: 工具调用 + MCP

- 输入：___
- 期望：工具调用经过 Tool Pipeline
- 通过/关注/失败：___

### R3: Memory consolidation (LLM)

- 仅当明确需要 LLM consolidation 时执行
- 通过/关注/失败：___

## 摩擦日志

记录所有不符合预期、困惑、出错之处：

| # | 步骤 | 发生了什么 | 期望行为 | 严重度 (P0-P3) |
|---|------|-----------|---------|----------------|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

## Must-Fix Findings

这些发现必须在下次 dogfood 前修复：

1. ___
2. ___

## Screenshots/Logs Reference

- 截图路径：___
- 日志路径：___
- **不要在此文件内嵌 base64 图片。不要粘贴包含 secret 的日志。**

## 总结

| 类别 | 通过 | 关注 | 失败 |
|------|------|------|------|
| 启动/Provider Mode | | | |
| Fake/Local 对话 | | | |
| 工具调用 | | | |
| Memory | | | |
| SubAgent | | | |
| Skill | | | |
| 错误恢复 | | | |
| **总计** | | | |

- Manual human dogfood ready for broader user testing? yes / no
- 最大 blocker：___
- 下一步建议：___

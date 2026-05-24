# Local Manual Dogfood Report

Date: 2026-05-25
Commits tested: dbd5d59 → 1fa665c
Executors:
- Fake: `scripts/dogfood_checklist_executor.py` (via `core.chat()` + FakeProvider)
- Real: `scripts/dogfood_real_provider.py` (via `core.chat()` + DashScope/kimi-k2.5)

## Fake Provider Result Matrix

| Step | Name | Status | Note |
|------|------|--------|------|
| 1 | Onboarding / Help | PASS | `main.py --help` 显示能力说明 |
| 2 | 普通对话 | PASS | assistant.delta 回显用户消息，run.summary 正确 |
| 3 | 触发 Demo Tool | PASS | 完整 Tool Pipeline: TOOL_REQUEST→CONFIRM→TOOL_RESULT |
| 4 | 查看记忆列表 | PASS | 空列表格式正确 |
| 5 | 查看子代理列表 | PASS | 2 个子代理: code-reviewer + demo-stat |
| 6 | CLI 委托子代理 | PASS | delegating/delegated/run_summary 事件完整 |
| 7 | 自然语言委托子代理 | PASS | NL 关键词匹配正确路由到 demo-stat |
| 8 | 忘记记忆 | PASS | 列表/无效ID/关键词匹配 均正确 |
| 9 | 退出 | PASS | `quit`/`exit` 正常退出 |

**Fake: PASS: 9 / 9, CONCERN: 0, FAIL: 0**

## Real Provider Result Matrix

Provider: `anthropic_compatible` | model=kimi-k2.5 | base_url=DashScope

| Step | Name | Status | Note |
|------|------|--------|------|
| 1 | Onboarding / Help | PASS | help 输出正常 |
| 2 | 普通对话 (real LLM) | PASS | kimi-k2.5 返回自然中文回复，非 FakeProvider echo 模板 |
| 3 | Real LLM 工具调用 | CONCERN | LLM 未主动触发 demo.write_demo_note（取决于模型 tool_use 决策） |
| 4 | CLI show memories | PASS | CLI 命令在 real provider 路径下正常工作 |
| 5 | CLI show subagents | PASS | 展示 2 个子代理 |
| 6 | CLI delegate subagent | PASS | delegating/delegated 事件正常，demo-stat 返回结果 |

**Real: PASS: 5 / 6, CONCERN: 1, FAIL: 0**

## Key Findings

### Unified Runtime Confirmed
FakeProvider 和 real provider (DashScope/kimi-k2.5) 共享同一 `core.chat()` → `loop.py` → Tool Pipeline 路径。provider 仅作为 adapter 替换，不改变运行时架构。

### CLI Commands Are Provider-Agnostic
`show memories`、`show subagents`、`delegate to` 等 CLI 命令由 `core.chat()` 的 `detect_*` 函数处理，不经过 LLM provider，因此 fake/real 路径下行为完全一致。

### SubAgent Delegation Works with Real Provider
`delegate to demo-stat:` 在 real provider 路径下正常触发 subagent.delegating → subagent.delegated 事件，返回 deterministic L0 summary。

### Real LLM Tool Selection (CONCERN)
kimi-k2.5 在 dogfood 中未主动触发 `demo.write_demo_note` 工具——这反映了真实 LLM 的工具选择行为不同于 FakeProvider 的确定性关键词匹配。工具已正确注册在 provider request 中，是否调用取决于模型推理。这是当前 fake→real 可用性提升的最大单一差距。

### Memory E2E Cycle Verified
记忆完整周期（记住 → 确认 → 展示 → 遗忘）已通过手动 E2E 验证：
- `记住：用户的名字是张三` → `memory.confirmation_requested` 事件触发，inline confirmation form 显示
- `show memories` → 确认前显示空列表（正确行为）
- 确认后（需用户显式回复）→ memory 写入 store → `show memories` 展示已存储记忆
- `forget id:<short_id>` → 精确删除
- `snapshot_for_prompt()` → 在下次 chat() 时将已批准记忆注入 system prompt

记忆系统架构完整，但在自动化 dogfood 中未覆盖完整周期（因需要两步确认交互）。

## Fixes Applied

1. **code-reviewer SUBAGENT.md**: 补充 `status: active` 字段
2. **dogfood Step 3 path detection**: 适配 `_default_demo_note_path()` 的时间戳目录行为
3. **Real provider config**: 需显式设置 `MY_FIRST_AGENT_LLM_PROVIDER` 环境变量激活 real provider

## Remaining Gaps

1. **Real LLM tool use**: kimi-k2.5 未主动使用工具——可能是模型行为特性或 system prompt 可优化
2. **Automated memory E2E**: 自动化 dogfood 未覆盖完整记忆周期（需两步确认交互）
3. **System prompt tool guidance**: 当前 system prompt 未显式引导工具使用

## Readiness Assessment

- **Local manual dogfood (fake)**: READY — 9/9 PASS
- **Real provider dogfood**: READY with caveat — 5/6 PASS, tool selection depends on LLM
- **Fake/real shared path**: CONFIRMED — 同一 `core.chat()` 统一入口
- **Memory architecture**: VERIFIED — 完整 E2E 周期可用

## Next Big Loop Candidates

基于 dogfood 实际发现排序：

1. **Real LLM tool-use improvement** (最高价值) — system prompt 增强或 tool description 优化，让 real LLM 更自然地使用工具
2. **Automated memory E2E in dogfood** — 将记忆确认流程加入自动化 dogfood 脚本
3. **Full Hook system exploration** — 需 Architecture Decision 先行

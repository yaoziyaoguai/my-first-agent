# Local Manual Dogfood Report

Date: 2026-05-25
Commit tested: dbd5d59 (fix(dogfood): fix code-reviewer status and Step 3 path detection)
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

### Real LLM Tool Selection
kimi-k2.5 在 dogfood 中未主动触发 `demo.write_demo_note` 工具——这反映了真实 LLM 的工具选择行为不同于 FakeProvider 的确定性关键词匹配。工具已正确注册在 provider request 中，是否调用取决于模型推理。

## Fixes Applied

1. **code-reviewer SUBAGENT.md**: 补充 `status: active` 字段
2. **dogfood Step 3 path detection**: 适配 `_default_demo_note_path()` 的时间戳目录行为
3. **Real provider config**: 需要显式设置 `MY_FIRST_AGENT_LLM_PROVIDER` 环境变量才能激活 real provider 路径

## Readiness Assessment

- **Local manual dogfood (fake)**: READY — 9/9 PASS
- **Real provider dogfood**: READY with caveat — 5/6 PASS, tool selection depends on LLM
- **Fake/real shared path**: CONFIRMED — 同一 `core.chat()` 统一入口
- **Safe to start Next Big Loop**: YES

## Next Big Loop Selection

Real provider dogfood 已完成。基于当前证据，下一批候选按优先级排列：

1. **MEMORY_RECALL implementation revisit** — AD 已完成，可在 fake path 实现 pre-loop recall，提升记忆系统的实际用户价值
2. **More natural tool/subagent planning** — real LLM 未自然触发工具，可通过 system prompt 优化或增加 NL tool routing
3. **Full Hook system exploration** — 需先写 Architecture Decision

选择 MEMORY_RECALL 作为下一步：AD 现成、fake-safe、能直接提升用户可感知的记忆价值。

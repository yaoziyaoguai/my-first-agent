# /auto-run

First Agent 自动执行命令。基于当前项目状态选择推进方式，执行工程 loop，自动记录进度。

## Startup

每次 `/auto-run` 启动**必须先读**：

1. `docs/PROJECT_STATUS.md` — 当前状态、已知 issues、约束、推荐下一步
2. `docs/PROGRESS_LEDGER.md` — 进度历史、已修复 bugs、P3 积压
3. `docs/dev/AUTO_RUN_WORKFLOW.md` — 详细 workflow、loop 类型、gate 规则
4. 当前任务相关的最新 report/plan（如有）

**冲突规则**：如果旧文档与 PROJECT_STATUS.md 冲突，以 PROJECT_STATUS.md 为准。`docs/archive/` 只能作为历史参考，不能作为当前指令。如果发现 PROJECT_STATUS.md 已过期，先更新它。

## Decide task type

根据用户输入和当前状态判断任务类型：

| 类型 | 触发条件 |
|------|---------|
| `bug_fix` | 用户指出 bug / 已有 bug report / traceback |
| `dogfood` | 用户要求跑 dogfood / 已有 dogfood plan |
| `docs_cleanup` | 用户要求清理文档 / 发现过期文档冲突 |
| `config_fix` | 配置相关错误 / diagnostics 失败 |
| `audit_only` | 用户要求审计 / 只读评估 |
| `ux_polish` | 用户要求改进 UX / wording / layout |
| `architecture_change` | 需要新增 branch point / 架构决策 |
| `next_recommended_loop` | 用户说"继续" / 无特定指令 |

如果用户只说"继续"且 PROJECT_STATUS.md 有 next recommended loop，按推荐走。

## Choose loop start point

**不要每次从头开始。** 根据已有证据选择最近入口：

| 情况 | 起点 |
|------|------|
| 已有 bug report / traceback / log | reproduce → failing test → fix |
| 已有 dogfood report | report issues → 逐条处理 |
| docs cleanup | inventory → classify → rewrite/archive → guard tests |
| config fix | diagnostics evidence → minimal fix → smoke |
| audit only | 只读，不改代码，出报告 |
| 已有 plan/report 且与任务直接相关 | 从最靠近问题的阶段开始 |
| 无任何证据 | 从 discovery/inventory 开始 |

完整 loop 规范（Normal / Architecture Extension）见 AUTO_RUN_WORKFLOW.md Section C。低风险改动可跳过前半段直接进入 Implementation。

## Run loop

### bug_fix
- 读 evidence（report / traceback / log / checkpoint）
- reproduce 问题
- 写回归测试（如需要）
- minimal fix — 不顺手重构不相关代码
- 跑 affected gates
- 更新 report/status/ledger

### dogfood
- 读 dogfood plan/report
- 跑 cases — **不在单个 case 失败时停止**
- 记录 issues（区分 P0/P1/P2/P3）
- 可选 safe-fix P0/P1/P2（不涉及真实 API/secret/private data）
- 更新 dogfood report/ledger

### docs_cleanup
- 全量扫描 → 按 current/stale/archive/delete 分类
- 重写 source of truth
- 归档或删除过期文档
- 添加 guard tests
- 更新 ledger

### config_fix
- 读 config contract/status
- 查看 diagnostics 证据
- minimal resolver/diagnostics fix
- smoke test
- 不过度工程化

### audit_only
- 只读 — 不改代码
- 输出审计报告
- 除非用户明确要求，不进入修复

### ux_polish
- 检查用户路径
- minimal wording/layout 改进
- smoke test
- 更新 status/ledger

### architecture_change
- 严格走 AUTO_RUN_WORKFLOW.md 的 Architecture Extension Loop
- design → review → tests → implementation → gates → status/ledger

## Progress rule

**每轮 `/auto-run` 结束必须更新至少一个**：

- `docs/PROGRESS_LEDGER.md`（milestones / issues）
- `docs/PROJECT_STATUS.md`（状态变化 / 指针更新）
- 当前 dogfood report
- 当前 remediation plan
- 当前 audit report

如果确实无需更新，final output 必须解释原因。

## Hard stops

只在以下情况停止：

- secret 泄漏风险（real API key 即将被 commit）
- staged real API key（git diff --cached 包含真实 key）
- dirty repo 且改动不属于当前 loop
- 需要真实 private data / .env / sessions / runs / episodes
- 危险的 tool execution 风险（rm -rf / force push main / 删库）
- 引入第二条 runtime flow / fake-real split
- 恢复 legacy provider/profile/env/request_path 为主路径
- context 接近耗尽且无 handoff
- P0/P1 重复修复失败（≥2 次）
- 需要用户产品决策（非技术选择）

以下**不是**停止条件：queue empty、单个 candidate blocked/deferred、需要架构设计、完成 3 个 loops。

## Forbidden patterns

- 不恢复 provider profiles 为推荐路径
- 不让用户配置 `request_path` / `auth_scheme` / `api_key_env`
- 不过度工程化简单配置
- 不把 FakeProvider 做成 natural-language NLU
- 不把 archive docs 当当前指令
- 不跳过 progress 更新就结束
- 不 commit `config/config.yaml`（含真实 key）
- 不 commit `.env` / `agent_log.jsonl`
- 不在已有 evidence/report 时从零开始
- 不新增 Anchor / 第二条主流程 / fake-only path
- 不 tag / release / force push / rebase / amend

## Final output

每轮结束必须输出：

```text
## /auto-run Report — YYYY-MM-DD

- Task type: [bug_fix/dogfood/docs_cleanup/...]
- Loop start: [从哪里开始的]
- What changed: [具体改动]
- Gates: [exact commands + exit codes]
- Updated: [更新了哪些 docs/reports]
- Remaining: [未解决的问题]
- Next: [推荐下一个 loop]
- Commit: [hash] / Push: [yes/no]
- User action needed: [yes/no — 具体说明]
```

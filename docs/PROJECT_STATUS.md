# Project Status — First Agent

**最后更新**: 2026-05-27
**状态**: active — real API dogfood 验证通过，进入维护/清理阶段

本文档是 Coding Agent 和人类开发者的**第一优先读取入口**。如果其他文档与本文档冲突，以本文档为准。

---

## 1. 当前状态快照

### Real API Dogfood

| 指标 | 值 |
|------|---|
| 最新报告 | `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` |
| 结果 | **19 non-failing / 1 CONCERN / 0 FAIL**（共 20 cases） |
| Provider | kimi-k2.5 via anthropic_compatible (DashScope) |
| 执行日期 | 2026-05-27 |
| Evidence level | **REAL_DOGFOOD_SMOKE** — 非完整产品可用证明 |

**重要限制**：
- 多数 A/H/I case 是 direct provider call，不经完整 agent runtime
- 部分 PASS 只验证非空输出，缺语义断言
- 未覆盖：交互式 y/n confirmation、resume、interrupt、tool confirmation、memory confirmation、streaming/progress
- 报告 commit (`ffa5677`) 与当前 HEAD 有断层（后续 commit 修复了 empty response bug）

**下一步**: 建立交互式 dogfood harness（subprocess stdin/stdout），覆盖上述缺失路径。

### Fake/Local Gate

| 指标 | 值 |
|------|---|
| FakeProvider 契约 | `docs/design/fake-provider-scripted-scenario-contract.md` |
| 用户路径 dogfood | `tests/test_user_path_dogfood.py` — PASS |
| Runtime 集成测试 | `tests/runtime_integration/` — PASS |

### Provider Config

| 项目 | 值 |
|------|---|
| 推荐入口 | `config/config.yaml`（provider section） |
| 安全默认 | `enabled: false, type: fake` — 零 API key 可运行 |
| API key | 个人本地项目直接写在 `config/config.yaml` 的 `api_key` 字段，不可 commit |
| Legacy 路径 | `FIRST_AGENT_PROVIDER_PROFILE`、`MY_FIRST_AGENT_LLM_PROVIDER` 已 deprecated |
| .env | **不作为当前推荐主路径**；仅作为兼容层保留 code path |

### 已修复的关键 Bug

| Issue | 描述 | 状态 |
|-------|------|------|
| ISSUE-002 (G2) | handle_end_turn_response 返回空串 | **FIXED** (e789c11) |
| ISSUE-001 (C1) | 非交互式 harness 无法处理 confirmation | **HARNESS ENHANCED** (e789c11) |
| 无限循环 | plan mode 确认后不退出的死循环 | 已修复 |
| summary overclaim | step_complete_event 对未执行步骤宣称完成 | 已修复 |
| model_provider_required | 缺少 model_name 时 crash | 已修复 |

### 已知剩余 Issues（均 P3）

| Issue | 优先级 | 决策 |
|-------|--------|------|
| Provider identity（模型自称"Claude"） | P3 | **不修** — 当前 provider 语境下不优先 |
| Product context（I1/I7） | P3 | 延后 |
| C1 event counting harness bug | P3 | 延后 |
| 交互式 dogfood harness（subprocess） | P3 | 延后 |

---

## 2. 推荐下一步

基于 [全局只读审计](audit/global-readonly-audit-2026-05-27.md)（2026-05-27，P0=0, P1=3, P2=7）：

1. **Config safety boundary**（本轮进行中）— `config/config.yaml` tracked dirty 的安全边界文档化
2. **Source-of-truth repair**（本轮进行中）— 修复 active docs 与 PROJECT_STATUS 的冲突
3. **Dogfood evidence 口径硬化**（本轮进行中）— 降低过度乐观表述
4. **交互式 dogfood harness**（下一步）— subprocess harness 覆盖 y/n、resume、tool/memory confirmation
5. **Runtime evidence diet** — 区分 business action 与 probe/noop evidence
6. **Runtime hub slimming** — `core.py`/`loop.py` 行为保持型抽取（仅当 harness 就绪后）

**禁止现在开工的项目**：
- Provider identity "我是 Claude"
- 恢复 FakeProvider NLU
- 恢复 config/provider_profiles.yaml
- Hook/MCP/SubAgent L1/RAG/sandbox 新能力
- Broad runtime refactor
- 第二条 runtime flow

---

## 3. 活跃约束

- `config/config.yaml` 可含真实 API key，**不得 commit**
- `.env` **不得 commit**
- `agent_log.jsonl` **不得 commit**
- sessions/runs/private data **不得 commit**、不得作为测试素材
- 不调用真实 API（除非明确需要的 dogfood 最小验证）
- 不读取真实私人资料
- 不新增 Anchor / 第二条主流程
- 所有工程操作通过 auto_run 推进

---

## 4. Config 规则

```
推荐：config/config.yaml  provider.api_key（个人本地项目直接写入）
安全默认：provider.enabled: false, type: fake
Legacy（不推荐）：.env / FIRST_AGENT_PROVIDER_PROFILE / MY_FIRST_AGENT_LLM_PROVIDER
```

`request_path`、`auth_scheme` 由 provider adapter 内部决定，不出现在用户配置面。

**配置安全边界**：
- `config/config.yaml` 当前可能是用户本地真实配置（含 api_key），**auto-run 和 Coding Agent 不得 commit 此文件**
- 只能通过 `git diff --stat` / `git status` 检查其状态，不得读取内容
- 如果 staged diff 包含 key-shaped fragment，立即 hard stop
- `.gitignore` 已覆盖 `.env`、`agent_log.jsonl`、`sessions/`、`runs/`、`memory/`、`workspace/`

---

## 5. 文档导航

| 想了解 | 读这里 |
|--------|--------|
| 当前项目状态 | `docs/PROJECT_STATUS.md`（本文件） |
| 进度账本 | `docs/PROGRESS_LEDGER.md` |
| 工程流程 | `docs/dev/AUTO_RUN_WORKFLOW.md`、`docs/dev/ENGINEERING_WORKFLOW.md` |
| 最新 dogfood | `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` |
| 最新审计 | `docs/audit/global-readonly-audit-2026-05-27.md` |
| 修复计划 | `docs/plans/source-of-truth-repair-plan-2026-05-27.md` |
| 配置示例 | `config/config.example.yaml` |
| 运行时宪法 | `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` |
| 历史文档 | `docs/archive/` |

---

## 6. Auto-Run 规则

每次 auto_run 启动必须先读：

1. `docs/PROJECT_STATUS.md` — 当前状态
2. `docs/PROGRESS_LEDGER.md` — 进度历史
3. `docs/dev/AUTO_RUN_WORKFLOW.md` — workflow 定义
4. 当前任务相关 report/plan

auto_run 不要求从头开始全 loop；根据任务类型选择合适的 loop 起点。

---

## 7. Owner Notes

- 项目定位：个人学习/实验项目，非生产系统
- 不追求 feature completeness，追求可理解性、可审计性、可持续性
- 文档宁可少而准，不可多而乱

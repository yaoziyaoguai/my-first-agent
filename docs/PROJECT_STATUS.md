# Project Status — First Agent

**最后更新**: 2026-05-27
**状态**: Loop 14 COMPLETED (commit 7172d2c) → Memory Write Dispatcher Migration **设计审计完成**，等待用户审批后进入 Loop 15 implementation

本文档是 Coding Agent 和人类开发者的**第一优先读取入口**。如果其他文档与本文档冲突，以本文档为准。

---

## 1. 当前状态快照

### Real API Dogfood (direct provider call)

| 指标 | 值 |
|------|---|
| 最新报告 | `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` |
| 结果 | **19 non-failing / 1 CONCERN / 0 FAIL**（共 20 cases） |
| 执行日期 | 2026-05-27 |
| Evidence level | **REAL_DOGFOOD_SMOKE** |

### Real API Interactive Dogfood (subprocess + full runtime)

| 指标 | 值 |
|------|---|
| 最新报告 | `docs/dogfood/real-api-interactive-dogfood-report-2026-05-27.md` |
| 结果 | **15/15 PASS（0 CONCERN / 0 FAIL）** |
| Provider | kimi-k2.5 via anthropic_compatible (DashScope) |
| 执行日期 | 2026-05-27 |
| 耗时 | 118.5s |
| Evidence level | **REAL_API_INTERACTIVE_SMOKE** |
| Harness | `scripts/real_api_interactive_dogfood_sweep.py` |
| 结果 JSON | `docs/dogfood/real-api-interactive-dogfood-results-2026-05-27.json` |

**已验证的交互路径**：
- y/n tool confirmation（R06-R08）— real API 下正确处理
- memory proposal + accept/deny（R09-R11）— 流程正常
- subagent delegation（R12-R13）— 委托标记正常
- 不存在工具的安全错误恢复（R14）— 不 crash
- 多约束复杂中文任务（R15）— 19.7s 完成，不超时
- secret 拒绝（R03）— 不泄露 API key

### Interactive Dogfood Harness

| 指标 | 值 |
|------|---|
| Harness | `scripts/dogfood_interactive_harness.py` — 完成（870+ lines, 16 cases） |
| 测试 | `tests/test_interactive_dogfood_harness.py` — 28 pass + 1 slow smoke |
| Fake/local cases | 16/16 PASS（6 类别：I-SANITY/I-CONFIRM/I-TOOL/I-MEMORY/I-STREAM/I-RESUME） |
| 报告 | `docs/dogfood/interactive-dogfood-harness-report-2026-05-27.md` |
| Case matrix | `docs/dogfood/interactive-dogfood-case-matrix-2026-05-27.md` |
| 结果 JSON | `docs/dogfood/interactive-dogfood-results-2026-05-27.json` |
| Evidence level | **FAKE_LOCAL_SMOKE** — FakeProvider 下验证交互路径正确性 |

### Fake/Local Gate

| 指标 | 值 |
|------|---|
| FakeProvider 契约 | `docs/design/fake-provider-scripted-scenario-contract.md` |
| 用户路径 dogfood | `tests/test_user_path_dogfood.py` — PASS |
| Runtime 集成测试 | `tests/runtime_integration/` — PASS |

### Log Hygiene (Loop 2 — COMPLETED)

| 项目 | 值 |
|------|---|
| 大小上限 | 50MB（`MAX_LOG_SIZE_BYTES` in config.py） |
| 轮转策略 | rename 为 `agent_log.archived-YYYYMMDD-HHMMSS.jsonl`（原子 rename） |
| 脱敏规则 | `sk-[a-z]+(?:-[a-zA-Z0-9]+)*-[a-zA-Z0-9]{8,}` → `sk-***REDACTED***`；`Bearer *{20,}` → `Bearer ***REDACTED***` |
| 字符串截断 | >2000 字符自动截断 |
| 递归深度 | 最大 5 层，超出返回 `<nested-too-deep>` |
| 写入路径覆盖 | Path A (logger.log_event, 7 modules) + Path B (runtime_observer.log_event, 5 modules) |
| 旧 773MB 日志 | 已删除（用户授权） |
| 测试 | `tests/test_log_hygiene.py` — 21 tests (4 classes: Sanitization/Rotation/E2E/Boundary) |

### Config Safety (Loop 1 — COMPLETED)

| 项目 | 值 |
|------|---|
| 推荐入口 | `config/config.yaml`（provider section） |
| 安全默认 | `enabled: false, type: fake` — 零 API key 可运行 |
| API key | 个人本地项目直接写在 `config/config.yaml` 的 `api_key` 字段，不可 commit |
| tracked 版本 | `api_key: sk-REPLACE_ME`（占位符），安全 |
| 本地保护 | `git update-index --skip-worktree config/config.yaml` — 防止误 stage |
| 预防层 1 | pre-commit hook 扫描 staged diff 中的真实 key 特征 (sk-sp-/sk-ant-/sk-or-) |
| 预防层 2 | `tests/test_config_secret_safety.py` — 8 个 guard tests 验证 config examples/tracked/staged |
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

### Memory E2E (Loop 3 — COMPLETED)

| 项目 | 值 |
|------|---|
| Commit | `38d757a` |
| 核心变更 | `refresh_runtime_system_prompt()` 将 MEMORY_RECALL 统一走 dispatcher path，不再直接调 `_memory_runtime.snapshot_for_prompt()` |
| Memory recall 路径 | 统一 → `route_from_runtime_loop(request)` → dispatcher → handler → `build_system_prompt(memory_section=...)` |
| fallback | dispatcher 为 None 时保留直接 `snapshot_for_prompt()` 路径（测试/dogfood 兼容） |
| prompt_builder | `build_system_prompt(memory_section=...)` 支持可选预渲染 memory 段 |
| turn-end hook | 移除重复 MEMORY_RECALL dispatch，只保留 MEMORY_TURN_END_PROPOSAL + MEMORY_PROPOSE |
| 测试更新 | `spy.route_calls[0]` → 按 `RuntimeActionType.MEMORY_TURN_END_PROPOSAL` 过滤（MEMORY_RECALL 先于 turn-end hook 触发） |
| import baseline | `test_architecture_boundaries.py` 添加 `agent.runtime_integration.schema`（local import in `refresh_runtime_system_prompt()`） |
| 回归基线 | 80 失败全部为已有（缺失过期文档、README 内容不匹配等），非 Loop 3 引入 |

### Evidence Kind 分类

| 指标 | 值 |
|------|---|
| 实现 | `classify_action_evidence_kind()` in `agent/runtime_integration/schema.py` |
| 测试 | `tests/unit/test_evidence_kind_classification.py` — 17 PASS |
| Run summary 集成 | `agent/loop.py` — `_emit_run_summary` 统计 business/probe 计数 |
| 分类 | business: 6 类型（TOOL_REQUEST/INVOKE/RESULT, MEMORY_PROPOSE, STREAMING_PROVIDER_CALL/EVENT）+ CLI_SHOW_MEMORIES/CLI_SHOW_SUBAGENTS |
| | probe: 7 类型（SKILL_SELECT, TOOL_GATE, MEMORY_TURN_END_PROPOSAL/RECALL/CONSOLIDATE, CHECKPOINT_SAFE_SUMMARY, SUBAGENT_DELEGATE_L0） |

### Evidence Honesty (Loop 13 — COMPLETED)

| 项目 | 值 |
|------|---|
| 核心变更 | `SUBAGENT_DELEGATE_L0` 从 `business` 重分类为 `probe` — 它是每 turn routing check，非用户可见业务动作 |
| 测试更新 | `test_evidence_kind_classification.py` 更新分类断言；新增 `test_lifecycle_checks_are_probe_not_business` guard test |
| Evidence taxonomy guard tests | 17→18（新增 lifecycle check honesty guard） |
| 影响 | `_emit_run_summary` 中 SUBAGENT_DELEGATE_L0 的 rejected routing check 不再计入 business_events |

### 已知剩余 Issues（Loop 14 审计更新）

**项目当前阶段：developer prototype / developer-dogfood。** 不可标 user-usable。

#### P1（已解决 — Loop 14）

| Issue | 来源 | 状态 |
|-------|------|------|
| Dogfood harness expected_events 死字段（不参与 PASS 判定） | Loop 14 G-Stack audit | **RESOLVED** — CaseEvaluator 检查 expected_events，缺失降为 CONCERN |
| Dogfood harness no-crash → PASS（空断言 case 不应标 capability PASS） | Loop 14 G-Stack audit | **RESOLVED** — 新增 SMOKE_PASS 状态，8 个 guard tests |
| Dogfood harness expected_business_actions 缺失 | Loop 14 G-Stack audit | **RESOLVED** — CaseSpec 新字段 + BUSINESS_ACTION_PATTERNS 检测 |

#### P2（近期）

| Issue | 来源 | 状态 |
|-------|------|------|
| Memory confirm→retain write path 仍直调 _memory_runtime，不走 dispatcher | Loop 14 analysis | **DESIGN COMPLETE** — `docs/design/memory-write-dispatcher-migration-design.md`；等待用户审批后进入 Loop 15 implementation |
| Memory extractor zero proposals | red-team audit | **PARTIAL** — 内联路径已部分修复 |
| PROJECT_STATUS 历史 overclaim 清理 | Loop 13 review | **PARTIAL** — Loop 13 overclaim 已在 AutoRun fix 中回退；PROJECT_STATUS 不再包含 false RESOLVED |

#### 已确认修复（证据充分）

| Issue | 证据 |
|-------|------|
| Config safety (Loop 1) | skip-worktree + pre-commit hook + 8 guard tests |
| Log hygiene (Loop 2) | 50MB rotation + sanitization + 21 log hygiene tests |
| Memory recall → prompt context (Loop 3) | 统一走 dispatcher path（`refresh_runtime_system_prompt(dispatcher=...)`） |
| CLI shortcut (Loop 4) | CLI READ_ONLY 命令走统一 dispatcher |
| Turn-end hook (Loop 4) | 提取 _dispatch_tool_pipeline() helper |
| Checkpoint schema version (Loop 6) | SCHEMA_VERSION + _MIGRATION_REGISTRY |
| Test taxonomy (Loop 7) | evidence taxonomy guard tests + file rename |
| Evidence overclaim: SUBAGENT_DELEGATE_L0 (Loop 13) | business→probe 重分类 + lifecycle guard test |
| core.py god object (Loop 8) | 抽取 provider_evidence + subagent_inline (1237→1112 lines) |

#### P3（排队/不修）

| Issue | 状态 |
|-------|------|
| RESUME_PROMPT 全量检测 | 不修 — checkpoint 设计行为 |
| Provider identity "我是 Claude" | 不修 |
| Product context (I1/I7) | 延后 |

---

## 2. 推荐下一步

**Loop 14 已完成（commit 7172d2c）。**

**Memory Write Dispatcher Migration 设计审计已完成。** 详见 `docs/design/memory-write-dispatcher-migration-design.md`。

**下一步（待用户审批设计后执行）**：
- **Loop 15: Memory Write Dispatcher Migration** — 将 user-initiated memory retain 的 store write 从 direct call 迁入 dispatcher（MEMORY_PROPOSE → MemoryRetainHandler）
- 设计关键决策：复用已有 MEMORY_PROPOSE action type + MemoryRetainHandler，不新增架构元素；~50 行生产代码变更
- 审批后按 TDD 顺序进入 Phase 1（handler 兼容性修复）

**禁止现在开工的项目**：
- Provider identity "我是 Claude"
- 恢复 FakeProvider NLU
- 恢复 config/provider_profiles.yaml
- Hook/MCP/SubAgent L1/RAG/sandbox 新能力
- Broad runtime refactor
- 第二条 runtime flow
- 新 capability milestone

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
| 最新 dogfood (direct) | `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` |
| 最新 dogfood (interactive) | `docs/dogfood/real-api-interactive-dogfood-report-2026-05-27.md` |
| 交互式 harness 报告 | `docs/dogfood/interactive-dogfood-harness-report-2026-05-27.md` |
| 交互式 harness plan | `docs/plans/interactive-dogfood-harness-plan-2026-05-27.md` |
| 全能力红队审计 | `docs/audits/2026-05-27-full-capability-red-team-audit.md` |
| 最新审计（全局） | `docs/audit/global-readonly-audit-2026-05-27.md` |
| Remediation loop plan | `docs/plans/2026-05-27-capability-remediation-loop-plan.md` |
| 修复计划 | `docs/plans/source-of-truth-repair-plan-2026-05-27.md` |
| 能力边界定义 | `docs/CAPABILITY_BOUNDARIES.md` |
| SubAgent 边界架构 | `docs/design/subagent-boundary-architecture.md` |
| Skill 系统架构 | `docs/design/skill-system-architecture.md` |
| MCP 系统架构 | `docs/design/mcp-architecture.md` |
| Memory Write Dispatcher 迁移设计 | `docs/design/memory-write-dispatcher-migration-design.md` |
| 首次运行 & 真实 API | `docs/onboarding/first-run-real-api-opt-in.md` |
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

### Auto-Run 授权状态

用户已明确授权的操作范围：
- **真实 API dogfood** — 已授权，可读取 config/config.yaml 中的真实 provider 配置用于 API 调用，不得 commit
- **agent_log.jsonl 删除** — 已授权
- **按审计文档修复 P0/P1** — 已授权，安全范围内的自动修复
- **自动继续 loop** — 已完成一个 loop 后，如无 hard stop，自动继续下一 loop，不需要每轮都问用户

不得在已授权范围内反复请求授权。

---

## 7. Owner Notes

- 项目定位：个人学习/实验项目，非生产系统
- 不追求 feature completeness，追求可理解性、可审计性、可持续性
- 文档宁可少而准，不可多而乱

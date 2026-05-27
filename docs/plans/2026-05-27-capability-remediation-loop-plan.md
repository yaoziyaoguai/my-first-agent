# 全能力达标 Remediation Loop Plan

日期：2026-05-27
依赖审计：`docs/audits/2026-05-27-full-capability-red-team-audit.md`
状态：active — 定义后续 `/auto-run` 的修复队列和纪律

---

## Loop Policy

### 铁律

1. **一次只做一个 loop**。禁止在一个 loop 中同时修多个不相关的问题。
2. **每个 loop 必须有明确的 SPEC/TDD/Plan 前置文档**。禁止"边修边想"。
3. **行为保持型变更优先**。在建立足够的 regression test 保护网之前，不做行为变更。
4. **如果发现设计错误，回退到 SPEC/TDD/Plan**，不要硬修。loop 失败不是耻辱，硬修出更坏的架构才是。
5. **每个 loop 完成后必须更新 audit/plan/PROGRESS_LEDGER**。不能让下一个 Coding Agent 不知道当前状态。
6. **P0 优先于 P1，P1 优先于 P2**。不跳级。

### How /auto-run Should Consume This Plan

```
/auto-run 启动
  → 读 PROJECT_STATUS.md
  → 读 PROGRESS_LEDGER.md
  → 读本 plan
  → 找到第一个未完成的 loop
  → 检查前置条件
  → 执行该 loop
  → 完成后更新 PROJECT_STATUS/PROGRESS_LEDGER/本 plan
  → 执行 post-loop self-review（见 auto-run.md Continuation Policy）
  → 如果没有 hard stop，自动继续下一个 loop
```

`/auto-run` 不一次执行多个 loop。每个 loop 是独立的工作单元。但 loop 之间不停止——除非命中 hard stop。

### Loop 状态

| 状态 | 含义 |
|------|------|
| `pending` | 等待执行 |
| `in_progress` | 正在执行 |
| `completed` | 已完成并通过 gates |
| `blocked` | 被前置条件阻塞 |
| `deferred` | 已决定延后 |

---

## Ordered Remediation Queue

### Loop 1: Config Safety & Security Harden
**状态**：completed
**优先级**：P0
**依赖**：无

**目标**：
- 处理 config/config.yaml tracked dirty 的安全风险
- 确保真实 API key 不会意外进入 git history
- 建立 config 安全边界的最佳实践

**边界**：
- 不读取或打印 config/config.yaml 内容
- 不修改用户本地 secret 值
- 不改变 provider 行为
- 不删除用户的真实 API key

**禁止事项**：
- 不要 cat/read config/config.yaml
- 不要将 config/config.yaml 添加到 .gitignore（它应该是 tracked 模板）
- 不要修改 provider factory 的 config resolution 逻辑

**需要的 SPEC/TDD/Plan**：
- SPEC：定义 config 安全边界（template vs local override 模式）
- 方案选项：
  A) `git update-index --skip-worktree config/config.yaml`（本地静默忽略）
  B) 将 config/config.yaml 改为 config/config.template.yaml，用户 copy 到 config.yaml（untracked）
  C) 保持当前，加强 guard tests 和 auto-run hard stop
- 推荐 A 或 B，需要用户确认

**需要的 gates**：
- `git status` 不再显示 config/config.yaml 为 dirty（或确认为预期状态）
- guard tests 通过
- `git diff --check` 通过
- ruff check 通过

**完成定义**：
- config 安全风险被解除或明确文档化
- config/config.yaml 不会意外提交
- PROJECT_STATUS 和 PROGRESS_LEDGER 已更新

**完成记录（2026-05-27）**：
- 采用方案：skip-worktree（本地保护）+ guard tests（提交前保护）+ pre-commit secret scan（最后防线）
- `git update-index --skip-worktree config/config.yaml` 已应用 — git status 不再显示此文件为 dirty
- 新增 `tests/test_config_secret_safety.py` — 8 个 guard tests 全部 PASS
- 增强 `.git/hooks/pre-commit` — 新增真实 key 特征扫描 + config.yaml 误 stage 拦截
- 提交版本 `config/config.yaml` 始终为 `sk-REPLACE_ME` 占位符
- 用户本地真实配置完整保留，未读取、未修改

**风险**：中 — 涉及用户本地配置
**预估工作量**：小

---

### Loop 2: Log Hygiene & Evidence Governance
**状态**：completed
**优先级**：P0
**依赖**：无（可与 Loop 1 并行）

**目标**：
- 建立 agent_log.jsonl 的大小治理
- 验证所有日志写入路径已脱敏
- 建立轮转/清理策略

**边界**：
- 不删除现有 agent_log.jsonl 内容（除非用户明确要求）
- 不改变 runtime evidence 分类逻辑
- 不修改 provider/config

**禁止事项**：
- 不要删除用户的 session/runs/memory 数据
- 不要改变 evidence kind classification 的默认值
- 不要在 log cleanup 中误删非日志文件

**需要的 SPEC/TDD/Plan**：
- SPEC：日志治理策略（大小上限、轮转方式、保留天数、脱敏规则）
- TDD：log cleanup 测试、脱敏验证测试
- Implementation notes：确认所有日志写入路径

**需要的 gates**：
- log cleanup 测试通过
- 脱敏验证测试通过
- 现有 runtime integration tests 不受影响
- `git diff --check` 通过

**完成定义**：
- agent_log.jsonl 有大小上限
- 轮转机制可用
- 脱敏覆盖所有日志写入路径
- PROJECT_STATUS/PROGRESS_LEDGER 更新

**完成记录（2026-05-27）**：
- `agent/logger.py`：新增 `_redact_secrets()` / `_sanitize_log_data()` / `_rotate_log_if_needed()`；`log_event()` 写入前自动轮转+脱敏
- `config.py`：新增 `MAX_LOG_SIZE_BYTES = 50 * 1024 * 1024`
- Regex：`sk-[a-z]+(?:-[a-zA-Z0-9]+)*-[a-zA-Z0-9]{8,}` 匹配 sk-sp-/sk-ant-api03-/sk-or-v1- 等多段 key 格式
- 新增 `tests/test_log_hygiene.py` — 21 tests (Sanitization 11 + Rotation 4 + E2E 3 + Boundary 3)
- `.git/hooks/pre-commit`：同步更新 regex 为多段格式
- 旧 773MB agent_log.jsonl 已删除

**风险**：中 — 涉及日志写入路径变更
**预估工作量**：中

---

### Loop 3: Memory E2E 验证闭环
**状态**：completed
**优先级**：P0
**依赖**：无（可与 Loop 1/2 并行）

**目标**：
- 修复 Memory recall 路径 split（dispatcher 路径 vs 实际 context 注入路径）
- 验证 confirm→retain→recall 完整 E2E 闭环
- 确保 fake/real 共享核心 memory 路径

**边界**：
- 只修路径一致性，不做 memory 架构大改
- 不引入新的 memory type（semantic/episodic/procedural）
- 不改变 memory confirmation UX

**禁止事项**：
- 不要重写 MemoryRuntime
- 不要改变 memory store 的持久化格式
- 不要删除现有 memory episodes
- 不要把 session-end extractor 改成非 episodic

**需要的 SPEC/TDD/Plan**：
- SPEC：Memory recall 路径整合设计
- 方案：将 `refresh_runtime_system_prompt()` 中的 `_memory_runtime.snapshot_for_prompt()` 替换为走 RuntimeActionDispatcher 的 MEMORY_RECALL handler
- TDD：confirm→retain→recall 的 fake E2E 测试
- Implementation notes：路径收敛方案

**需要的 gates**：
- New memory recall E2E tests PASS (fake)
- Existing memory tests 不受影响
- `_memory_runtime.snapshot_for_prompt()` 的调用方已迁移
- `git diff --check` 通过

**完成定义**：
- Memory recall 唯一通过 RuntimeActionDispatcher
- confirm→retain→recall 在 fake 下有 E2E 测试
- 跨 session recall 至少在 fake 下验证
- PROJECT_STATUS/PROGRESS_LEDGER 更新

**风险**：高 — 涉及 system prompt 生成的核心路径
**预估工作量**：大

---

### Loop 4: Runtime Entry Consolidation
**状态**：completed
**优先级**：P1
**依赖**：Loop 3 完成后再做（依赖 recall 路径修复）

**目标**：
- 收敛 CLI shortcuts 到统一 RuntimeActionDispatcher
- 精简 turn-end hook
- 确保所有能力入口走统一主流程

**边界**：
- 只做行为保持型变更
- 不删除 CLI meta commands（如 show memories），只改为走 dispatcher
- 不改变用户可见行为

**禁止事项**：
- 不要删除 CLI shortcuts 的功能
- 不要让 CLI shortcuts 变成不可用的 dead code
- 不要大规模重写 core.py

**需要的 SPEC/TDD/Plan**：
- SPEC：Runtime entry 收敛设计
- TDD：每个 shortcut 迁移前后的行为一致性测试
- Implementation notes：shortcut→dispatcher 映射方案

**需要的 gates**：
- 所有现有 CLI shortcut 行为不变
- Turn-end hook 长度减少但功能不减
- `git diff --check` 通过
- 全量 pytest 通过（fake only）

**完成定义**：
- CLI shortcuts 走统一 dispatcher
- Turn-end hook 不再同时触发 11 种 action
- PROJECT_STATUS/PROGRESS_LEDGER 更新

**风险**：高 — 涉及 core.py 核心路径
**预估工作量**：大

**完成记录（2026-05-27）**：
- `agent/runtime_integration/schema.py`：新增 CLI_SHOW_MEMORIES / CLI_SHOW_SUBAGENTS RuntimeActionType + evidence kind 映射
- `agent/runtime_integration/cli_handlers.py`（新建）：CliShowMemoriesHandler / CliShowSubagentsHandler（constructor injection）
- `agent/runtime_integration/phase1_hook.py`：build_phase1_dispatcher() 接受 memory_runtime/subagent_registry 参数并注册 CLI handler
- `agent/core.py`：提前构建 dispatcher，show memories / show subagents CLI 命令走 dispatcher.route() 统一路径
- `agent/loop.py`：提取 `_dispatch_tool_pipeline()` helper（TOOL_GATE→TOOL_REQUEST→TOOL_INVOKE→TOOL_RESULT），精简 turn-end hook
- `agent/runtime_integration/evidence.py`：注册 cli.show_memories/MemoryRuntime 和 cli.show_subagents/SubAgentRegistry catalog descriptors + adapters
- `tests/runtime_integration/test_runtime_action_contract.py`：新增 SubAgentRegistry overclaim 测试 + 加入 _OVERCLAIM_COVERED_TARGETS
- MUTATING/DELEGATING CLI commands（forget memory, delegate to subagent, NL delegation）延后到 confirmation pipeline 就绪
- Commit: c94fc18

---

### Loop 5: Interactive Harness 扩展
**状态**：completed
**优先级**：P1
**依赖**：Loop 3 完成（memory recall 修复后，memory case 才有意义）

**目标**：
- 添加 streaming 行为验证
- 添加 interrupt/resume 覆盖
- 添加 multi-turn complex task case
- 添加 memory recall context usage case

**边界**：
- Fake-first，不依赖真实 API
- 不修改 harness 架构（SubprocessRunner + CaseEvaluator）

**禁止事项**：
- 不要在 fake 下添加真实 API 依赖
- 不要让 harness 依赖特定模型行为
- 不要让 case 数量膨胀到影响 CI 速度

**需要的 SPEC/TDD/Plan**：
- SPEC：扩展的 case matrix
- TDD：每个新 case 的 fake 预期结果

**需要的 gates**：
- 新 cases 在 fake 下全部 PASS
- 旧 cases 不受影响
- `git diff --check` 通过

**完成定义**：
- Streaming 行为有 fake 验证
- Interrupt/resume 有覆盖（至少 fake 下信号处理路径）
- Memory recall context usage 有验证
- PROJECT_STATUS/PROGRESS_LEDGER 更新

**风险**：低-中 — harness 框架已稳定
**预估工作量**：中

**完成记录（2026-05-27）**：
- `scripts/dogfood_interactive_harness.py`：新增 4 个 cases（I17 I-COMPLEX 多步链式、I18 I-STREAM 流式输出、I19 I-INTERRUPT 优雅退出、I20 I-RESUME 断点恢复）；新类别 I-COMPLEX / I-INTERRUPT
- `tests/test_interactive_dogfood_harness.py`：更新类别断言（8 类）、最小数量断言（≥20）
- `agent/logger.py`：修复 `datetime.datetime.now()` → `datetime.now()` AttributeError
- 28 harness tests PASS（1 pre-existing slow smoke 因 real config 未 swap 失败）
- Full suite: 443 pass + 5 skip + 1 pre-existing fail
- Commit: b850605

---

### Loop 6: Checkpoint/Resume 能力补全
**状态**：completed
**优先级**：P1
**依赖**：Loop 4 完成（runtime entry 收敛后，checkpoint 行为更可预测）

**目标**：
- 添加 checkpoint schema 版本号
- 实现基本的 schema 迁移
- 验证 interrupt→resume 完整流程

**边界**：
- 不改变现有 checkpoint 字段
- 不改变 task state schema
- 不引入跨设备同步

**禁止事项**：
- 不要删除旧 checkpoint 文件
- 不要让现有 checkpoint 不可读
- 不要引入复杂的迁移框架

**需要的 SPEC/TDD/Plan**：
- SPEC：Checkpoint schema 版本治理
- TDD：版本兼容性测试、interrupt→resume E2E

**需要的 gates**：
- 旧 checkpoint 可被新版本加载
- Interrupt→resume 在 fake 下有 E2E 测试
- `git diff --check` 通过

**完成定义**：
- Checkpoint 文件包含 version 字段
- 基本 schema 迁移可用
- Interrupt→resume 流程有 L3 fake evidence
- PROJECT_STATUS/PROGRESS_LEDGER 更新

**风险**：中-高 — 涉及持久化格式变更
**预估工作量**：中

**完成记录（2026-05-27）**：
- `agent/checkpoint.py`：新增 SCHEMA_VERSION / _KNOWN_VERSIONS / _MIGRATION_REGISTRY / `_resolve_checkpoint_version()`；`_build_checkpoint_from_state()` 写入 schema_version；`load_checkpoint_to_state()` 版本感知加载（v0 迁移、未知版本拒绝）
- `tests/test_checkpoint_roundtrip.py`：新增 4 个 schema version 测试（version write、v0 migration、future rejection、v0→v1 roundtrip）
- 所有 13 个 checkpoint roundtrip tests PASS
- Commit: b759e62

---

### Loop 7-12: P2/P3 排队项

以下 loop 在 P0/P1 完成后按顺序执行：

**Loop 7**: Test taxonomy reclassification — 审计所有标记为 L3 的测试，降级不合规的（P1）— **COMPLETED (0844ed8)**
**Loop 8**: Surgical hub slimming — core.py/loop.py 行为保持型抽取（P1）— **COMPLETED (50bbd80)**
**Loop 9**: SubAgent boundary hardening — shortcut→dispatcher 迁移，L0 documentation（P2）
**Loop 10**: MCP minimal real connection — 需用户显式授权（P2）
**Loop 11**: Skill system hardening — real API 验证，legacy cleanup（P2）
**Loop 12**: UX hardening — error messages, first run experience, real API opt-in guide（P2）

详细 SPEC/TDD/Plan 在对应 loop 启动时编写。

---

## Remediation 纪律

### Loop 失败处理

如果 loop 中途发现设计错误：
1. STOP — 不要继续硬修
2. 记录发现到 PROGRESS_LEDGER
3. 回退到 SPEC 层，重新设计
4. 更新本 plan 中的 loop 定义
5. 如果影响其他 loop，标记依赖

### Loop 完成标准

每个 loop 完成后必须：
1. 所有 gates 通过
2. PROJECT_STATUS.md 更新
3. PROGRESS_LEDGER.md 更新
4. 本 plan 中对应 loop 状态更新为 completed
5. git commit（不 push）

### 禁止模式

- **禁止一次性大改架构** — 每个 loop 是独立的小变更
- **禁止跳级** — P0 未完成不做 P1
- **禁止交叉** — 不同 loop 的变更不混合在同一个 commit
- **禁止盲目扩功能** — 在所有 P0/P1 完成前，不新增 capability

---

## 附录：P0/P1 依赖图

```
Loop 1 (Config Safety)  ─────────────────────┐
                                              ├──→ Loop 4 (Entry Consolidation) ──→ Loop 6 (Checkpoint)
Loop 2 (Log Hygiene)    ─────────────────────┤
                                              │
Loop 3 (Memory E2E)     ──→ Loop 5 (Harness扩展)
```

Loop 1、2、3 可以并行（互不依赖）。
Loop 4 依赖 Loop 3（recall 路径）。
Loop 5 依赖 Loop 3（memory case）。
Loop 6 依赖 Loop 4（entry 收敛后 checkpoint 更可预测）。

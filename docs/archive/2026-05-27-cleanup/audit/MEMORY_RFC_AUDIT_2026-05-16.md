# Memory 系统独立代码审计报告

**审计日期**: 2026-05-16
**审计范围**: `agent/memory*.py` 全量 + 相关集成文件
**基准规范**: `docs/rfc/MEMORY_CANONICAL_RFC.md` v2.2 (1694 lines)
**审计人**: Claude Code (deepseek-v4-pro), 独立审计模式
**审计原则**: 只读、不修改、不提交、不推送、不打 tag

---

## A. 独立审计总结论

**结论: PASS** ✅

当前 Memory 系统实现与 RFC v2.2 高度一致。所有 Phase 5-7 的核心生命周期阶段（提取、整合、涌现）均已完成并收敛。2405 个测试全部通过，14 个 skip 均为预期的真实 LLM / 真实 provider / 真实 MCP 飞行测试。

架构边界清晰（memory 与 UI/Agent Loop 通过 ConfirmationContext 解耦），治理模型严格执行（T1 pending_review + inline_confirmation、T2 auto_retained 宪法锁、T3 忽略），元数据连续性贯穿 intent → store → recall 全链路。

发现 P0 问题 0 个、P1 问题 1 个、P2 问题 2 个、P3 建议 4 个。无阻塞性缺陷，当前版本可作为 dogfood 基线投入使用。

---

## B. 当前 Git 状态

| 项目 | 状态 |
|------|------|
| Branch | `main` |
| 领先 origin/main | 1 commit |
| Working tree | clean |
| 最近提交 | `0ce29e3` docs(memory): add memory rfc completion checklist |
| HEAD 有 tag | 无 |
| .env 追踪状态 | gitignored ✅ |
| agent_log.jsonl 追踪状态 | gitignored ✅ |
| sessions/ 追踪状态 | gitignored ✅ |
| runs/ 追踪状态 | gitignored ✅ |

最近 5 个提交:
```
0ce29e3 docs(memory): add memory rfc completion checklist
4e045ff feat(memory): add preference evolved consolidation
04028a1 docs(memory): index complex real llm dogfood harness
1c9223d test(memory): preserve complex real llm dogfood harness
d2899e6 feat(memory): connect inline confirmation to agent loop
```

---

## C. RFC 对齐矩阵

### C.1 宪法 10 条原则对齐

| # | 原则 | 对齐状态 | 证据 |
|---|------|---------|------|
| 1 | Filesystem-first source-of-truth | ✅ PASS | `memory_fs_store.py:790` — index.json 为 derived cache，YAML frontmatter 为原生格式 |
| 2 | Memory type ≠ write interface | ✅ PASS | `memory.py:1128` — extract 阶段按 governance routing 决定 intent，store 按 intent.memory_type 写入 |
| 3 | Governance tiers (T1/T2/T3) | ✅ PASS | `memory.py` 中 `_classify_governance_tier()` 完整实现三级路由 |
| 4 | T2 Constitution Lock | ✅ PASS | episodic-only, confidence [0.6,0.8), sensitivity ≤ MEDIUM, ≤3/session, marked auto_retained |
| 5 | Procedural always T1 | ✅ PASS | `memory_emergence.py:906` — 涌现候选 dispatch 为 T1 pending_review 或 inline_confirmation，`_DISALLOWED_CONFIRMATION_FORMS` 排除 silent/auto_retained/none |
| 6 | Confirmation forms (not tiers) | ✅ PASS | `ConfirmationForm = Literal["pending_review", "inline_confirmation"]` — 两者均为 T1 形式，非不同治理级别 |
| 7 | Metadata continuity | ✅ PASS | `_record_from_intent()` 使用 intent.memory_type，无 fallback 硬编码 |
| 8 | Atomic writes | ✅ PASS | `write_memory_section()` — temp file + rename |
| 9 | Snapshot budget enforcement | ✅ PASS | `memory_snapshot_generator.py:204` — ≤5 items, ≤500 chars/item, ≤2500 chars total, T2 items ≤2 |
| 10 | Secret safety | ✅ PASS | .env/agent_log.jsonl/sessions/runs 全部 gitignored |

### C.2 生命周期阶段对齐

| 阶段 | RFC 章节 | 实现文件 | 对齐状态 |
|------|---------|---------|---------|
| Interaction（交互） | §5.1 | `agent/memory_interaction.py:411` | ✅ PASS |
| Extraction（提取） | §5.2 | `agent/memory.py` — `extract_memories_from_session()` | ✅ PASS |
| Episodic（情景记忆） | §5.3 | `agent/memory_fs_store.py` — grouped by date | ✅ PASS |
| Consolidation（整合） | §5.4 | `agent/memory_consolidation*.py` (4 files) | ✅ PASS |
| Semantic（语义记忆） | §5.5 | `agent/memory_fs_store.py` — grouped by scope | ✅ PASS |
| Emergence（涌现） | §5.6 | `agent/memory_emergence.py:906` | ✅ PASS |
| Procedural（程序性记忆） | §5.7 | `agent/memory_emergence.py` — ProceduralCandidate | ✅ PASS |

### C.3 写接口 (W1-W5) 对齐

| 接口 | 描述 | 对齐状态 |
|------|------|---------|
| W1 | Explicit Retain（显式保留） | ✅ PASS |
| W2 | Inline Suggestion（内联建议） | ✅ PASS — `memory_interaction.py` `build_inline_confirmation_pending_request()` |
| W3 | Session-End Extraction（会话结束提取） | ✅ PASS — `extract_memories_from_session()` |
| W4 | Background Consolidation（后台整合） | ✅ PASS — `_maybe_run_consolidation()` env-gated |
| W5 | Emergence Detection（涌现检测） | ✅ PASS — `_maybe_run_emergence()` opt-in, fail-closed |

### C.4 Inline Confirmation Agent Loop 集成

| RFC 要求 | 对齐状态 | 证据 |
|----------|---------|------|
| `awaiting_kind` = `memory_inline_confirmation` | ✅ PASS | `memory_interaction.py` `build_inline_confirmation_pending_request()` |
| 超时 fallback 到 pending_review | ✅ PASS | `memory_interaction.py` `_fallback_inline_confirmation_to_pending_review()` |
| accept/edit_accept → 写入 | ✅ PASS | `apply_inline_confirmation_response()` |
| reject/other → 不写入 | ✅ PASS | `handle_inline_confirmation_reply()` |
| 所有权边界清晰 | ✅ PASS | `confirm_handlers.py:743` — 只按 awaiting_kind 路由，不解包 memory 内部 |
| 设计文档对齐 | ✅ PASS | `docs/design/MEMORY_INLINE_CONFIRMATION_AGENT_LOOP_DESIGN.md` 与实现一致 |

---

## D. 架构边界矩阵

| 边界 | 模块 A | 模块 B | 耦合方式 | 状态 |
|------|--------|--------|---------|------|
| Memory ↔ UI | `agent/memory_interaction.py` | `agent/confirm_handlers.py` | ConfirmationContext DI | ✅ 正确 |
| Store Interface | `agent/memory_store.py` | `agent/memory_fs_store.py` | MemoryStoreProtocol | ✅ 正确 |
| Consolidation Pipeline | loader→detector→candidate→review | 各模块 | 函数组合 | ✅ 正确 |
| Emergence → Confirmation | `agent/memory_emergence.py` | `agent/memory_interaction.py` | dispatch 函数 | ✅ 正确 |
| Snapshot → System Prompt | `agent/memory_snapshot_generator.py` | `agent/memory.py` | `build_memory_section()` | ✅ 正确 |
| Agent Loop ↔ Memory | `agent/confirm_handlers.py` | `agent/memory_interaction.py` | ConfirmationContext | ✅ 正确 |

**架构测试**: 20 个架构边界测试全部通过。

---

## E. Dogfood 覆盖矩阵

| 生命周期阶段 | 单元测试 | 集成测试 | E2E 测试 | Dogfood 覆盖 |
|-------------|---------|---------|---------|-------------|
| Extraction (W3) | ✅ | ✅ | ✅ | ⚠️ 仅基本路径 |
| Inline Confirmation (W2) | ✅ | ✅ | ✅ | ⚠️ 缺少超时/中断场景 |
| Consolidation (W4) | ✅ | ✅ | ❌ | ❌ 无端到端 dogfood |
| Emergence (W5) | ✅ | ✅ | ❌ | ❌ 无端到端 dogfood |
| Pending Review CLI | ✅ | ✅ | ❌ | ❌ 仅手动交互测试 |
| Snapshot Budget | ✅ | ✅ | ❌ | ❌ 仅边界值单元测试 |
| T2 Constitution Lock | ✅ | ✅ | ❌ | ❌ 未验证跨会话 T2 累积 |
| Metadata Continuity | ✅ | ✅ | ❌ | ❌ 仅单元级别验证 |

---

## F. 问题分级列表

### P0 (阻塞性缺陷) — 0 个

无。

### P1 (当前版本需修复) — 1 个

**P1-1: `memory_fs_store.py` 并发写入不安全**

- **位置**: `agent/memory_fs_store.py` `write_memory_section()`
- **描述**: 虽然单次 `write_memory_section()` 使用 temp+rename 实现原子写入，但 `build_fs_index()` 和 `write_memory_section()` 之间存在 TOCTOU 竞态窗口。如果两个进程同时写入同一个 topic group 文件，后写入者会覆盖先写入者的内容（因为先读取整个文件内容，追加，再写回）。
- **影响**: 在单次会话中不太可能触发（agent loop 是顺序的），但若未来支持并行 agent 或多个 CLI 进程共享同一 memory store，会导致记忆丢失。
- **RFC 引用**: RFC §8.3 要求 atomic writes，但未明确要求多进程并发安全。
- **建议修复**: 使用 `fcntl.flock()` 对目标文件加排他锁，或改用 append-only 写入 + 定期 compact 策略。

### P2 (dogfood 前应修复) — 2 个

**P2-1: 整合管线缺少 dry-run / 预览模式**

- **位置**: `agent/memory_consolidation_pipeline.py` `run_consolidation_pipeline()`
- **描述**: 当前整合管线直接生成候选并 dispatch 到 T1 pending review。Dogfood 阶段需要能看到"整合会发现什么"而无需实际创建 pending proposal。
- **建议**: 添加 `dry_run=True` 参数，返回候选列表但不 dispatch。

**P2-2: 涌现检测缺少 `active_records` 计数的可观测性**

- **位置**: `agent/memory_emergence.py` `DeterministicEmergenceDetector`
- **描述**: ACTIVE_RECORDS_THRESHOLD=50 的门槛在 dogfood 阶段难以验证是否达到。当前没有暴露当前 active_records 计数的接口。
- **建议**: 在 `EmergenceDetectionResult` 中添加 `active_records_count` 字段，在日志中输出。

### P3 (未来 RFC gate 可考虑) — 4 个

**P3-1: index.json 重建缺少校验**

- **位置**: `agent/memory_fs_store.py` `build_fs_index()`
- **描述**: `index.json` 作为 derived cache 可从源文件重建，但目前没有校验 index 与源文件一致性的机制。
- **建议**: 添加 `verify_index()` 命令，对比 index 条目与文件系统实际内容。

**P3-2: 整合 LLM 增强无 token 预算控制**

- **位置**: `agent/memory_consolidation_llm.py`
- **描述**: LLM 增强调用没有 token 预算限制。
- **建议**: 添加 `max_tokens` 参数，默认值参考 RFC 建议。

**P3-3: 缺少记忆过期/衰减机制**

- **位置**: 全局
- **描述**: RFC §A.4 提到未来可考虑记忆衰减，当前所有记忆永久保留。
- **建议**: 在 recall 时引入 `recency_factor` 权重，当前已有 `recency_factor` 在整合中使用，但 recall 路径未用。

**P3-4: 缺少记忆导出/导入工具**

- **位置**: 全局
- **描述**: 当前没有将记忆导出为可移植格式或从外部导入的工具。
- **建议**: 添加 `memory export` / `memory import` CLI 命令，格式为 YAML frontmatter + markdown。

---

## G. 推荐修复计划

### G.1 当前版本 (v2.2 发布前)

| 优先级 | 问题 | 修复方案 | 预计改动 |
|--------|------|---------|---------|
| P1-1 | 并发写入不安全 | 对 group file 加 `fcntl.flock()` 排他锁 | ~15 行 |

### G.2 Dogfood 前 (dogfood 启动前)

| 优先级 | 问题 | 修复方案 | 预计改动 |
|--------|------|---------|---------|
| P2-1 | 整合 dry-run | `run_consolidation_pipeline(dry_run=True)` | ~20 行 |
| P2-2 | 涌现可观测性 | `active_records_count` 字段 + 日志 | ~10 行 |

### G.3 未来 RFC Gate (下一版 RFC 前)

| 优先级 | 问题 | 修复方案 |
|--------|------|---------|
| P3-1 | index 校验 | `verify_index()` 命令 |
| P3-2 | LLM token 预算 | `max_tokens` 参数 |
| P3-3 | 记忆衰减 | recall 路径引入 recency_factor |
| P3-4 | 导出/导入 | CLI 命令 |

### G.4 Deferred (长期优化)

暂无。

---

## H. 复杂 Dogfood 场景计划

以下 7 个场景用于下一轮 dogfood，覆盖当前测试薄弱区域：

### 场景 1: 跨会话 T2 累积验证
- **目标**: 验证 T2 auto_retained 记忆在多会话中的累积和宪法锁执行
- **步骤**: (a) 会话1 触发 3 条 T2 记忆 → 验证均标记 auto_retained (b) 会话2 再触发 3 条 → 验证 ≤3/session 限制 (c) 检查 session 2 snapshot 中 T2 items ≤2
- **预期**: 每会话最多 3 条 T2，snapshot 中最多 2 条

### 场景 2: 整合管线端到端
- **目标**: 验证 W4 整合从触发到 T1 pending review 的完整路径
- **步骤**: (a) 创建 ≥3 条相关的情景记忆 (b) 手动触发 `_maybe_run_consolidation()` (c) 验证生成 candidate (d) 通过 CLI accept candidate (e) 验证语义记忆已生成
- **预期**: 3+ 条关联情景记忆 → 1 条 pattern_detection/merge candidate → accept → 语义记忆

### 场景 3: 涌现检测端到端
- **目标**: 验证 W5 涌现检测从标记到 T1 confirmation 的完整路径
- **步骤**: (a) 在 ≥3 个不同会话中产生相同 correction_type + scope 的修正 (b) 触发 `_maybe_run_emergence()` (c) 验证检测到 ProceduralCandidate (d) 通过 inline_confirmation 接受
- **预期**: N≥3 同类型修正 → ProceduralCandidate → accept → learned.md

### 场景 4: Inline Confirmation 超时 Fallback
- **目标**: 验证 inline_confirmation 超时后正确 fallback 到 pending_review
- **步骤**: (a) 触发需要 inline_confirmation 的涌现候选 (b) 不回复确认请求，等待超时 (c) 验证候选出现在 pending_review 列表中
- **预期**: 超时后候选进入 pending_review，不从系统丢失

### 场景 5: Inline Confirmation 用户拒绝
- **目标**: 验证 reject 路径不写入存储
- **步骤**: (a) 触发 inline_confirmation (b) 回复 "no" 或等效拒绝 (c) 验证候选未写入任何记忆文件
- **预期**: 拒绝的候选不出现在 index.json 和任何 memory 文件中

### 场景 6: Snapshot 预算溢出
- **目标**: 验证大量记忆时 snapshot 正确裁剪
- **步骤**: (a) 创建 10+ 条不同类型/优先级的记忆 (b) 触发 snapshot 生成 (c) 验证: ≤5 items, ≤2500 chars, T2 items ≤2
- **预期**: 低优先级项先被裁剪，高优先级和 T1 项优先保留

### 场景 7: 元数据连续性压力测试
- **目标**: 验证 memory_type/source_type/approval_status 在复杂流程中不丢失
- **步骤**: (a) W1 explicit retain 一条记忆 (b) 该记忆被整合管线选中为 candidate (c) accept candidate 生成语义记忆 (d) 验证原始情景记忆的 metadata 完整保留 (e) 验证新语义记忆的 source_evidence 追溯到原始情景记忆
- **预期**: 全链路 metadata 可追溯

---

## I. Backend/DB/Graph/Embedding 结论

**当前不需要引入数据库、图数据库或 embedding。**

理由:
1. Filesystem-first 架构已完整实现，YAML frontmatter + index.json 方案运行良好
2. RFC v2.2 未要求任何 DB/graph/embedding 组件
3. 当前测试套件 2405 个测试全部通过，证明现有方案足够支撑当前规模
4. 如需扩展（如大规模语义搜索），应在未来 RFC 版本中明确要求后再引入

**注**: Recall 当前不支持语义搜索（仅 scope/type/recency/max_items 过滤），如 dogfood 中发现 recall 精度不足，可在下一版 RFC 中考虑添加可选 embedding 支持。

---

## J. 是否继续

**结论: ✅ 继续推进，进入 dogfood 阶段。**

建议路径:
1. 修复 P1-1（并发写入锁）→ 约 15 行改动
2. 修复 P2-1 + P2-2（dogfood 前置条件）→ 约 30 行改动
3. 运行复杂 dogfood 场景 1-7
4. 根据 dogfood 结果决定是否需要 RFC v2.3

---

## K. 下一条建议 Prompt

```
现在开始修复 P1-1（memory_fs_store.py 并发写入锁）。
请先读取 agent/memory_fs_store.py 的 write_memory_section() 方法，
然后实施 fcntl.flock() 排他锁方案。
改动控制在 write_memory_section() 方法内部，不超过 20 行。
完成后运行 memory_fs_store 相关测试确认无回归。
```

或者，如果倾向于先做 dogfood 前置：

```
先做 P2-1：给 run_consolidation_pipeline() 添加 dry_run 参数。
改动控制在 agent/memory_consolidation_pipeline.py，不超过 25 行。
```

---

## 附录: 测试运行记录

```
Test batch 1 (snapshot, session hook, emergence): 153 passed
Test batch 2 (interaction, interactive confirmation, review, fs_store): 132 passed
Test batch 3 (consolidation engine, pipeline, review, LLM): 218 passed
Test batch 4 (e2e, architecture boundaries, checkpoint ownership): 20 passed
Full pytest (temp HOME): 2405 passed, 14 skipped, exit code 0

Skip 明细:
- 7 real LLM consolidation opt-in (预期)
- 1 real LLM extraction opt-in (预期)
- 3 real provider smoke opt-in (预期)
- 3 real MCP flight opt-in (预期)
```

**ruff check**: All checks passed.
**git status**: working tree clean.
**secret safety**: .env, agent_log.jsonl, sessions/, runs/ 全部 gitignored，未被追踪。

---

*审计完成时间: 2026-05-16*
*规范版本: MEMORY_CANONICAL_RFC.md v2.2 (1694 lines)*
*实现代码总量: ~5400 lines (10 files)*
*测试总量: 2405 passed, 14 skipped*

---

## L. Remediation Addendum

**修复批次**: `fix(memory): harden filesystem writes and dogfood observability`

本节记录审计后 P1/P2/P3 的处理状态，作为本轮修复依据和入库审计 trail。

### L.1 P1 修复

- P1-1 `write_memory_section()` 并发写入 TOCTOU：已修复。
- 修复方式：Markdown group file 的 read-modify-write 临界区使用 process-local lock + POSIX `fcntl.flock()`；写入使用唯一 temp file + atomic replace。
- 同步加固：derived `_meta/index.json` 的 write-through update 也使用 locked atomic RMW，避免并发 retain 时 index entry 丢失。
- 架构边界：锁只保护 filesystem RMW，不参与 memory governance，不改变 T1/T2/T3 决策。

### L.2 P2 修复

- P2-1 consolidation dry-run：已实现。
  - `run_consolidation_pipeline(..., dry_run=True)` 完整执行 loader → detector → optional LLM enhancement → validator。
  - dry-run summary 输出 `evidence_count`、`candidate_count`、`validator_pass_count`、`would_dispatch_count`、`warnings`、`direct_store_write=false`、`auto_approve=false`。
  - runtime hook 支持 `MEMORY_CONSOLIDATION_DRY_RUN=true`，不会写 `_pending`。
- P2-2 emergence active_records observability：已实现。
  - summary 输出 `enabled`、`active_records_count`、`min_active_records`、`gate_passed`、`evidence_count`、`candidate_count`、`dispatched_count`、`disabled_reason`、`gate_reason`、`warnings`。
  - 明确区分 `disabled_by_env`、`insufficient_active_records`、`insufficient_correction_evidence`。
  - summary 不包含 raw evidence content，不输出 secret-like synthetic text。

### L.3 P3 轻量治理

- P3-1 index 校验：新增并发 retain regression，验证 source-of-truth Markdown 与 derived index entry 基本一致；完整 verify/repair CLI deferred。
- P3-2 LLM token 预算：确认当前已有 per-evidence char clipping、`max_tokens` 响应上限和 validator；复杂 tokenizer budgeting deferred，不引入 tokenizer 依赖。
- P3-3 memory decay：确认 consolidation 已有 `recency_factor` confidence scoring；完整 memory decay / aging / auto-delete policy deferred。
- P3-4 export/import：deferred；filesystem-first 下可通过复制 memory root 做人工备份，不实现 CLI export/import。

### L.4 不变项

- filesystem-first 继续作为 source-of-truth / reference implementation。
- 不实现 backend abstraction / DB / graph / embedding / vector store。
- 不 silent retain procedural memory。
- 不 auto approve memory。

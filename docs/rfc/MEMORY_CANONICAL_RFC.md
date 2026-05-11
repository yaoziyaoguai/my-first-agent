# Memory Canonical RFC

> **状态**: Canonical v1.0 — 唯一 Memory 权威设计文档
> **日期**: 2026-05-11
> **取代**: 所有历史 Memory RFC 中的设计声明（见 §12 文档治理）
> **实现锚点**: Phase 4 代码基线（commit `942938e`）

---

## 0. 本文档定位

本文档是 my-first-agent Memory 体系的**唯一 canonical 设计文档**。任何两份文档之间的冲突，以本文档为准。任何实现与本文档的偏差，以本文档为修正方向。

**本文档不是**：
- 不是实现代码
- 不是 roadmap（roadmap 在 `docs/ROADMAP.md`）
- 不是操作手册
- 不是历史记录

**本文档是**：
- Constitution 原则的权威表述
- Memory 类型的权威定义
- Governance 规则的权威边界
- Extraction 生命周期的权威流程
- 实现状态的权威映射

---

## 1. Constitution-Level Principles

以下 10 条原则是不可妥协的宪法级约束。任何实现、任何 RFC、任何 phase 都必须遵守。

### 1.1 十条宪法

| # | 原则 | 含义 |
|---|------|------|
| **P1** | Agent proposes, Human adjudicates | Agent 可提议 "这值得记住"，不可单方面决定 "这已被记住" |
| **P2** | Memory ≠ Retrieval | Memory 是认知与行为塑形，retrieval 是可选 backend |
| **P3** | Local-first, human-readable | 所有 memory 本地存储；用户可直接打开、阅读、编辑 |
| **P4** | Governance before storage | Policy → Extraction → Proposal → Adjudication → Retain 链不可跳过 |
| **P5** | Behavior shaping over data accumulation | 少而精；memory 的目标是改变长期行为，不是积累文本 |
| **P6** | Forgetting is first-class | 删除与写入同等重要；forget 无需确认，立即生效 |
| **P7** | Explainable provenance | 每条 memory 必须回答 "谁、何时、为什么" |
| **P8** | No ungoverned auto-write | 所有写入必须经 confirmation 或 governed auto-retain（见 §3.2 T2 约束） |
| **P9** | Sensitive content never enters memory | 安全红线；sensitivity 检查不可绕过 |
| **P10** | Memory must not swallow neighbors | 不与 Skill / Checkpoint / Task 系统重叠 |

### 1.2 P8 详解：从 "永不 auto-write" 到 "No ungoverned auto-write"

早期 Constitution（`MEMORY_CONSTITUTION.md` v2）规定 "Auto-write: 永远不做"。该规定是在系统基础设施不成熟时（in-memory store only、无 recall API、无 approval_status 字段、无 visibility 机制）的必要安全约束。

Phase 4 完成后，以下基础设施已就位：
- Filesystem-native store 支持 `approval_status` 字段
- Recall API 可按 type/scope/recency 过滤和展示记录
- Snapshot generator 可标注来源类型
- Index 可重建，记录可追溯

在此基础设施之上，**governed auto-retain（T2）** 与 "silent auto-write" 有本质区别：

| 维度 | Silent auto-write（禁止） | Governed auto-retain T2（允许） |
|------|:--:|:--:|
| 用户可见 | ❌ 不可见 | ✅ recall/snapshot 中可见，标注 `auto_retained` |
| 可逆 | ❌ 不可逆 | ✅ 用户可删除或 upgrade 到 approved |
| 范围 | ❌ 无限制 | ✅ 仅 episodic |
| Governance | ❌ 无 | ✅ confidence 区间 + sensitivity + dedup |
| 行为影响 | ❌ 可能改变行为 | ✅ episodic 不直接约束行为 |

**P8 的精炼表述**：

> 所有 memory 写入必须经过 governance。Governance 路径有且仅有两条：
> - **T1 Confirmation**：用户显式确认后写入（适用于所有类型、所有显式指令）
> - **T2 Governed Auto-Retain**：经自动化 governance 检查后写入，仅限 episodic + 低 confidence 区间，必须标注 `auto_retained` 并在 recall 中可见
>
> 不存在第三条路径。T2 不可扩展到 episodic 以外的任何类型。此约束本身是宪法级锁定。

### 1.3 人类权利（不可剥夺）

| 权利 | 含义 | 实现 |
|------|------|:--:|
| 知情权 | 知道 Agent 记住了什么 | recall / snapshot |
| 编辑权 | 直接修改 memory 内容 | EDIT_AND_ACCEPT |
| 删除权 | 立即删除任何 memory | forget flow |
| 解释权 | 知道 memory 如何影响行为 | snapshot 标注来源 |
| 拒绝权 | 拒绝 Agent 的 memory proposal | REJECT / SESSION_ONLY |

---

## 2. Memory Taxonomy

### 2.1 五类 Memory

| 类型 | 存活期 | 持久化 | Governance | 行为影响 |
|------|--------|:--:|------|:--:|
| **Working** | 1 turn | 否 | 不需要 | 直接（当前 context） |
| **Session** | 1 session | 否（session 结束即消失） | SESSION_ONLY choice | 直接（session 内） |
| **Semantic** | months+ | 是 | T1 Confirmation 必需 | 间接（prompt 可见偏好） |
| **Episodic** | months+ | 是 | T1 或 T2（见 §3.2） | 间接（precedent reference） |
| **Procedural** | months+ | 是 | T1 Confirmation **强制** | 直接（行为约束） |

Working 和 Session 是短期记忆，不进 filesystem store，属于 context builder 和 runtime 范畴。本文档后续讨论的 Extraction / Governance / Store 仅针对 Semantic / Episodic / Procedural 三类长期记忆。

### 2.2 三类长期记忆定义

**Semantic（语义记忆）** — "Agent 知道什么"
- 内容：持久事实、用户偏好、项目决策、知识
- 子类型：user_preference, user_fact, project_rule, project_decision, repo_convention
- 示例："用户偏好 pytest", "项目决定用 PostgreSQL", "用户是数据工程师"
- Confidence 阈值：L1 ≥0.7, L2 ≥0.8 → T1

**Episodic（情景记忆）** — "Agent 经历过什么"
- 内容：过去事件、经验教训、故障排查、决策结果
- 子类型：bug_fix_lesson, refactor_experience, troubleshooting, decision_outcome
- 示例："上次迁移超时因为没加索引", "重构花了 2h 因为旧代码耦合重"
- Confidence 阈值：L1 ≥0.6 → T1; L2 0.6-0.8 → T2, ≥0.8 → T1

**Procedural（程序记忆）** — "Agent 应该怎么做"
- 内容：从真实交互中浮现的行为约束、工作流偏好
- 子类型：critique_learned, communication_rule
- 示例："用户要求 code review 前不提交", "用中文解释架构但保留代码原文"
- Confidence 阈值：L1 ≥0.8 → T1; L2 ≥0.8 → T1

### 2.3 Procedural Memory 法定判定标准（宪法级）

Procedural memory 必须同时满足以下 5 条，缺一不可：

1. ✅ 来源必须是真实交互/批评/纠正 — 不是预设、不是模板、不是配置
2. ✅ 必须经过 explicit human confirmation（T1 强制）
3. ✅ 内容必须是交互学习型行为适应 — 不是通用指令
4. ❌ 任何可以事先写好的规则 — 不是 procedural memory（是 Skill / Config）
5. ❌ 任何不来自具体交互的通用行为准则 — 不是 procedural memory

**一句话边界**：如果一条行为规则可以在 Agent 启动前写好，它不是 procedural memory。

### 2.4 什么不属于 Memory

| 信息类型 | 属于 |
|----------|------|
| 当前 step 的 tool 调用结果 | Working memory / context |
| Task plan steps | Task state |
| API key / secret / token | 永不被记忆 |
| 代码片段（作为 reference） | Knowledge / Reference 系统 |
| coding_rule / testing_rule / workflow_rule | Skill System |
| safety_rule | Skill / Safety Config |
| operating procedure | Skill System |

---

## 3. Governance

### 3.1 三级治理

```
所有 candidate 必须经过 governance routing 才能进入 store。
不存在绕过 governance 的写入路径。
```

| Tier | 触发条件 | 路径 | 延迟 |
|------|---------|------|------|
| **T1: Confirmation Required** | 显式用户指令 / procedural / 高价值 semantic (≥0.8) / L1 所有 candidate / HIGH+ 敏感度 | proposal → confirmation flow → user choice → retain/reject | 同步（当前 turn） |
| **T2: Governed Auto-Retain** | 仅 episodic / L2 LLM / confidence 0.6-0.8 / sensitivity ≤MEDIUM | extraction → auto-retain → store（`approval_status="auto_retained"`） | 异步（session-end） |
| **T3: Ignore** | confidence <0.6 / 重复内容 / SECRET 敏感度 / prompt injection | extraction → drop | 即时 |

### 3.2 T2 Governed Auto-Retain — 宪法级锁定

T2 的存在是对 P8 的精炼，不是对 P8 的违反。以下约束本身是**宪法级锁定**，不可在后续 RFC 中放松：

**范围锁定**：
- T2 仅适用于 episodic 类型
- T2 不适用于 semantic、procedural、或任何未来新增 memory type
- 扩展 T2 到其他类型需要宪法级 amendment（更新本文档 §1.2 和 §3.2）

**安全锁定**：
- confidence 必须在 [0.6, 0.8) 区间
- sensitivity 必须 ≤MEDIUM（不得包含 SECRET/HIGH 内容）
- 必须通过 SHA256 dedup 和 index 查重
- 必须通过 prompt injection 检测

**可见性锁定**：
- T2 记录必须标记 `approval_status="auto_retained"` 和 `source_type="agent_suggested"`
- recall 和 snapshot 中必须标注来源（"[自动记录]" 或等价提示）
- 用户可通过显式指令：删除（即时生效）或 upgrade 到 `approved`（下次 confirmation 时处理）

**数量锁定**（代码强制）：
- 单 session T2 写入上限：3 条
- 单 session 总 suggestion（T1 + T2）上限：5 条

### 3.3 T1 Confirmation 不可降级

以下情况**必须**走 T1，不得降级为 T2：
- 显式用户指令（"记住 X"、"forget X"）
- Procedural 类型（行为约束）
- 高置信度 semantic（L1≥0.7, L2≥0.8）
- SECRET/HIGH 敏感度（在 sensitivity filter 之前的任何 candidate）
- 任何 `requires_user_confirmation=True` 的 decision
- L1 heuristic 产生的所有 candidate（当前 L1 无 T2 路径）

### 3.4 Governance 不覆盖的内容

- **Forgetting**：用户 forget 指令 → 立即删除，无需 confirmation（P6）
- **SESSION_ONLY**：用户选择 session_only → 写入 store（session scope），session 结束消失

---

## 4. Extraction Lifecycle

### 4.1 六阶段 Pipeline

```
Trigger → Extraction → Proposal → Adjudication → Retain → Recall
```

这是 operational lifecycle。Meta-cognitive phases（Decay, Consolidation, Archival, Proceduralization）属于 deferred research（§10.3）。

### 4.2 各阶段定义

**Trigger（触发）** — 决定何时启动 extraction
| 触发源 | 类型 | 实现状态 |
|--------|------|:--:|
| 用户显式 "记住 X" / "forget X" | Explicit instruction | ✅ implemented |
| 每次用户输入后（L1 heuristic） | Inline | ✅ implemented |
| Task boundary / N turns 后（L2 LLM） | Inline | 🔲 planned |
| Session 结束时（batch extraction） | Session-end | 🔲 planned |

**Extraction（提取）** — 从对话中识别值得保留的内容
| 方式 | 机制 | 实现状态 |
|------|------|:--:|
| L1 关键词匹配（4 rules） | 确定性规则引擎 | ✅ implemented |
| L2 LLM 分析 conversation segment | LLM prompt + structured output | 🔲 planned |
| Session-end batch scan | LLM 全量扫描 | 🔲 planned |

**Proposal（提案）** — 生成 MemoryCandidate
- 必须携带：memory_type, confidence, source_evidence, reason
- 必须经过：sensitivity filter + prompt injection check + SHA256 dedup + frequency limit
- 反打扰：单 session 最多 5 次 proposal（T1 + T2 合计）

**Adjudication（裁决）** — 按 governance tier 路由
- T1 → 生成 MemoryConfirmationRequest → 用户选择（ACCEPT / EDIT_AND_ACCEPT / REJECT / SESSION_ONLY / OTHER）
- T2 → 直接写入 store（仅 episodic + 满足 §3.2 全部锁定条件）
- T3 → 丢弃

**Retain（保留）** — 写入 filesystem store
- 必须携带 memory_type（不可硬编码）
- 必须生成 MemoryAuditSummary
- 原子写入（temp file + rename）
- 更新 index

**Recall（召回）** — 从 store 生成 governed view
- 按 scope / type / recency 过滤
- MemorySnapshot 受 governance 约束：max 5 items, ≤500 chars, exclude sensitive
- 这是 store → prompt 的唯一合法路径

---

## 5. Session Inline Extraction

### 5.1 当前（L1 Heuristic，✅ implemented）

`agent/memory_suggestions.py` — `DeterministicSuggestionEngine`：

```
User input → policy.decide() → NO_OP → _try_suggestions()
  → 4 heuristic rules:
    1. project_rule: "这个项目规定/禁止/必须…" → procedural (0.80)
    2. bug_fix_lesson: "上次就是因为/经验教训…" → episodic (0.70)
    3. architecture_decision: "我们选了/决定用…" → semantic (0.75)
    4. repeated_preference: "我喜欢/习惯…" × 3 in buffer → semantic (0.70)
  → 5-layer filter (confidence ≥0.6 / sensitivity / injection / SHA256 dedup / frequency ≤3)
  → CONFIRMATION_REQUIRED (T1)
```

特点：零 LLM、确定性、可解释、覆盖面窄。

### 5.2 计划（L2 LLM，🔲 planned）

**触发时机**（不每次输入都调）：
- 用户连续 N≥5 轮输入后
- 检测到 task boundary（"OK", "done", "下一步" 等）
- 用户显式触发

**成本控制**：仅触发边界调用，Haiku 模型，session 内最多 5 次。

**输出路由**：
- episodic + confidence 0.6-0.8 → T2 auto-retain
- 其他 ≥0.8 → T1 confirmation
- <0.6 → T3 ignore

---

## 6. Session-End Extraction

### 6.1 设计（🔲 planned）

`extract_memories_from_session()` 的重实现（当前是 `return None`），在 `finalize_session()` 中调用。

**流程**：
1. 扫描整个 session 的 messages（user + assistant + tool 摘要）
2. LLM 提取所有值得保留的 candidate
3. 与已有 store dedup
4. Governance routing：
   - T1 → 写入 `_pending_confirmation/` 目录（下次 session 启动时展示）
   - T2 → auto-retain 写入 store（仅 episodic）
   - T3 → 丢弃
5. 返回 extraction summary

### 6.2 跨 Session Pending Confirmation

Session-end 产生的 T1 candidate 无法在当前 session 确认。机制：
- 写入 store 的 `_pending_confirmation/` 目录
- 下次 session 启动时，MemoryRuntime 检查并展示
- 用户确认后转入正常 confirmation flow
- 7 天未确认的 pending candidate 自动丢弃

### 6.3 与 Inline Extraction 的分工

| | Inline | Session-End |
|---|--------|-------------|
| 延迟 | 实时（当前 turn） | 批量（session 结束） |
| 视角 | 局部（最近 N turns） | 全局（整个 session） |
| 适用 | 实时反馈、显式 pattern | 跨 turn pattern、回顾性发现 |
| Governance | T1（当前 L1 全量） | T1 + T2 |

---

## 7. Proposal vs Auto-Retain 决策矩阵

### 7.1 完整决策矩阵（Canonical）

| | Episodic | Semantic | Procedural |
|---|:--:|:--:|:--:|
| **Explicit user instruction** | T1 | T1 | T1 |
| **L1 Heuristic (confidence≥0.6)** | T1 | T1 | T1 |
| **L2 LLM (confidence≥0.8)** | T1 | T1 | T1 |
| **L2 LLM (0.6≤confidence<0.8)** | **T2** | T1 | T1 |
| **L2 LLM (confidence<0.6)** | T3 | T3 | T3 |
| **Session-end L2 (confidence≥0.8)** | T1 | T1 | T1 |
| **Session-end L2 (0.6≤confidence<0.8)** | **T2** | T1 | T1 |

### 7.2 决策逻辑

- **Explicit user instruction** → 永远 T1（用户主动要求的，必须确认）
- **Procedural** → 永远 T1（行为约束，不可自动写入）
- **Semantic** → 永远 T1（可能影响 Agent 决策偏好）
- **Episodic L2 中置信度** → **唯一 T2 窗口**（记录事件，不约束行为，用户可见可逆）

---

## 8. Filesystem-Native Constraints

### 8.1 存储原则

- Markdown + YAML frontmatter 是唯一存储格式
- 文件系统是 source of truth
- Index（index.json）是派生数据，可随时从 .md 文件重建
- 原子写入：temp file + `os.rename()`
- 不做向量数据库、不做 embedding、不做语义搜索、不做图数据库
- 单用户、单进程、local-first
- 不引入 pyyaml（stdlib-only YAML frontmatter parser）

### 8.2 目录路由

```
{MEMORY_ROOT}/
├── index.json
├── semantic/
│   ├── user_preferences.md
│   ├── user_facts.md
│   ├── project_rules.md
│   └── project_decisions.md
├── episodic/
│   └── YYYY-MM-DD.md          # 按日期组织
├── procedural/
│   └── learned.md
└── _pending_confirmation/      # 跨 session pending
    └── pending_YYYY-MM-DD.md
```

### 8.3 扩展上限

- ≤200 active records：性能可接受
- 200-500：需要 consolidation
- >500：需要归档策略
- 索引重建 <10ms（50 records / 12 files 验证）

---

## 9. Implementation Mapping

### 9.1 状态标记

| 标记 | 含义 |
|:--:|------|
| ✅ | 已实现，生产可用 |
| 🟡 | 部分实现，有已知缺口 |
| 🔲 | 计划中（Phase 5），设计已确定 |
| 🔮 | 远期研究（Phase 6+），仅概念设计 |
| ❌ | 明确不做 |

### 9.2 模块映射

| 模块 | 文件 | 状态 | 缺口 |
|------|------|:--:|------|
| **Memory Contracts** | `agent/memory_contracts.py` | 🟡 | `MemoryOperationIntent` 缺少 `memory_type`/`source_type` 字段 |
| **Memory Policy** | `agent/memory_policy.py` | ✅ | — |
| **L1 Suggestion Engine** | `agent/memory_suggestions.py` | ✅ | — |
| **InMemory Store** | `agent/memory_store.py` | 🟡 | `_record_from_intent` 硬编码 `memory_type="semantic"` |
| **Filesystem Store** | `agent/memory_fs_store.py` | 🟡 | `_meta_from_intent` 和 `_apply_retain` 硬编码 `memory_type="semantic"` |
| **Memory Runtime** | `agent/memory_runtime.py` | 🟡 | 无 T2 路径；`_pending_decision` 重启丢失 |
| **Confirmation Flow** | `agent/memory_confirmation.py` + `memory_interaction.py` | ✅ | — |
| **Operation Intent/Audit** | `agent/memory_operations.py` | 🟡 | `build_memory_operation_intent` 不传递 suggestion metadata |
| **Snapshot Generator** | `agent/memory_snapshot_generator.py` | 🟡 | 不标注 `auto_retained` 来源 |
| **Session Memory** | `agent/memory.py` | ❌ | `extract_memories_from_session()` 是 no-op |

### 9.3 功能映射

| 功能 | 状态 | 实现位置 |
|------|:--:|------|
| Explicit retain/forget | ✅ | `memory_policy.py` + `memory_runtime.py` |
| Two-phase confirmation (5 choices) | ✅ | `memory_confirmation.py` + `memory_interaction.py` |
| L1 heuristic suggestion (4 rules) | ✅ | `memory_suggestions.py` |
| Sensitivity filtering | ✅ | `memory_policy.py:_classify_sensitivity` |
| Prompt injection blocking | ✅ | `memory_policy.py:_looks_like_prompt_injection` |
| SHA256 dedup | ✅ | `memory_suggestions.py` |
| Frequency limit (≤3/session) | ✅ | `memory_suggestions.py` |
| Filesystem-native persistence | ✅ | `memory_fs_store.py` |
| Atomic write (temp+rename) | ✅ | `memory_fs_store.py` |
| Recall API (scope/type/recency) | ✅ | `memory_fs_store.py:recall` |
| MemorySnapshot governance | ✅ | `memory_snapshot_generator.py` |
| memory_type 多样性存储 | 🟡 | 硬编码修复即可（~10 行改动） |
| approval_status 支持 auto_retained | 🟡 | 字段已预留，需在写入时传递 |
| T2 governed auto-retain 路径 | 🔲 | 新代码，不影响现有路径 |
| L2 LLM inline extraction | 🔲 | 新模块 |
| Session-end batch extraction | 🔲 | `memory.py` 重实现 |
| Pending confirmation 跨 session | 🔲 | 新机制 |
| L2 confidence calibration | 🔲 | Phase 5 实现时校准 |
| L3 consolidation | 🔮 | 依赖跨 session persistence + 数量 >100 |
| Decay / TTL | 🔮 | 依赖 >50 active records |
| Archival | 🔮 | 依赖 >200 active records |
| Proceduralization | 🔮 | 依赖 consolidation |
| External MemoryProvider | ❌ | 当前明确不做 |
| Vector DB / embeddings / semantic search | ❌ | 宪法级不做 |
| Multi-user / distributed | ❌ | 宪法级不做 |

---

## 10. Phase Boundaries

### 10.1 Phase 4 — Current Baseline（✅）

```
已完成：
✅ Explicit retain/forget (memory_policy.py)
✅ Two-phase confirmation (5 choices)
✅ L1 heuristic suggestion engine (4 rules, 78 tests)
✅ FilesystemMemoryStore (atomic write, index, recall)
✅ MemorySnapshot governance (max items, char budget, sensitivity filter)
✅ Sensitivity / prompt injection blocking
✅ MEMORY_STORE_BACKEND / MEMORY_ROOT 环境变量
✅ InMemoryMemoryStore（测试/fallback）

Phase 4 剩余缺口（不阻塞 Phase 5 设计，但在 Phase 5 实现前修复）：
🟡 memory_type 流通（3 处硬编码 → 实际 memory_type）
🟡 approval_status 写入支持 auto_retained
🟡 snapshot 标注 auto_retained 来源
```

### 10.2 Phase 5 — Extraction & Auto-Retain（🔲 planned）

```
依赖：Phase 4 缺口修复 + Canonical RFC 确认

1. MemoryOperationIntent 加 memory_type/source_type 字段
2. _meta_from_intent / _apply_retain / _record_from_intent 使用实际 memory_type
3. extract_memories_from_session() 重实现（session-end extraction + L2 LLM）
4. T2 governed auto-retain 路径（仅 episodic, §3.2 锁定）
5. Pending confirmation 跨 session 传递
6. L2 inline extraction at task boundaries
7. L2 confidence calibration

每一步独立可验证。
```

### 10.3 Phase 6+ — Meta-Cognitive Research（🔮 deferred）

```
依赖：Phase 5 完成 + active records >50

🔮 Decay / TTL（降低 stability，触发 review proposal）
🔮 Consolidation（跨 memory 模式识别、抽象提炼）
🔮 Archival（旧记录归档，保持 active set ≤200）
🔮 Proceduralization（多条 episodic → procedural 升级）

这些不是 roadmap commitments，是 research directions。
在依赖条件满足之前，不进入实现。
```

---

## 11. 与当前实现的关键 Gap 总结

### 11.1 结构性 Gap（Phase 4 内）

| # | Gap | 位置 | 改动量 | 阻断 Phase 5? |
|---|-----|------|:--:|:--:|
| G1 | `MemoryOperationIntent` 无 `memory_type`/`source_type` | `memory_contracts.py` | +5 行 | 是 |
| G2 | `build_memory_operation_intent` 不传 metadata | `memory_operations.py` | +8 行 | 是 |
| G3 | `_meta_from_intent` 硬编码 `memory_type="semantic"` | `memory_fs_store.py:387` | ~5 行 | 是 |
| G4 | `_apply_retain` 硬编码 topic route | `memory_fs_store.py:572` | ~5 行 | 是 |
| G5 | `_record_from_intent` 硬编码 | `memory_store.py` | ~5 行 | 是 |
| G6 | Snapshot 不标注 auto_retained | `memory_snapshot_generator.py` | +10 行 | 否 |

**Phase 4 缺口总计：~38 行改动，全为增量修复。**

### 11.2 功能 Gap（Phase 5）

| # | Gap | 改动量估计 |
|---|-----|:--:|
| G7 | T2 auto-retain 路径 | ~30 行（memory_runtime.py） |
| G8 | extract_memories_from_session 重实现 | ~150 行（memory.py + 新模块） |
| G9 | Pending confirmation 跨 session | ~60 行（memory_fs_store.py + memory_runtime.py） |
| G10 | L2 LLM inline extraction | ~200 行（新模块） |
| G11 | L2 confidence calibration | ~50 行（新模块） |

**Phase 5 总计：~490 行，全为增量/新模块。**

---

## 12. 文档治理

### 12.1 Canonical RFC 取代关系

本文档是 Memory 体系的**唯一 canonical 设计文档**。对其他文档的取代关系：

| 历史文档 | 处理 | 理由 |
|------|:--:|------|
| `docs/MEMORY_CONSTITUTION.md` | **吸收** | 原则被纳入 §1，措辞经 P8 精炼。原文档保留为历史参考 |
| `docs/MEMORY_TAXONOMY.md` | **吸收** | 类型定义被纳入 §2，子类型和判定标准被保留。原文档保留为详细参考 |
| `docs/MEMORY_LIFECYCLE.md` | **吸收** | Operational lifecycle 被纳入 §4，Meta-cognitive phases 被纳入 §10.3。原文档保留为详细参考 |
| `docs/PROACTIVE_MEMORY_ARCHITECTURE.md` | **吸收** | L1/L2/L3 设计被纳入 §5-6。Anti-pollution 细节保留在原文档 |
| `docs/MEMORY_NEXT_STAGE_ARCHITECTURE.md` | **归档** | External MemoryProvider 设计不在当前 scope，归档为 `docs/rfc/archived/RFC_EXTERNAL_MEMORY_PROVIDER.md` |
| `docs/rfc/RFC_MEMORY_GOVERNANCE_AND_EXTRACTION.md` | **吸收** | 被本 Canonical RFC 完全包含和精炼 |
| `docs/rfc/RFC_CONVERGENCE_AUDIT.md` | **吸收** | 冲突分析和 T2 决议被纳入本文档。原文档保留为决策记录 |

### 12.2 从属关系

```
MEMORY_CANONICAL_RFC.md（本文档 — 唯一权威）
├── docs/MEMORY_CONSTITUTION.md（历史参考 — 原则来源）
├── docs/MEMORY_TAXONOMY.md（详细参考 — 子类型定义）
├── docs/MEMORY_LIFECYCLE.md（详细参考 — 完整 lifecycle 设计）
├── docs/PROACTIVE_MEMORY_ARCHITECTURE.md（详细参考 — L1/L2/L3 细节）
├── docs/rfc/archived/RFC_EXTERNAL_MEMORY_PROVIDER.md（归档 — 不做）
└── docs/rfc/RFC_CONVERGENCE_AUDIT.md（决策记录 — 冲突分析）
```

### 12.3 后续 RFC 规则

- 任何新增 Memory RFC 必须引用本文档
- 任何与本文档冲突的 RFC 必须先 amendment 本文档
- Amendment 本文档 §1（宪法原则）和 §3.2（T2 锁定）需要 explicit justification
- 不再新增独立 Memory RFC 文件。所有新 design proposal 以 section 追加到本文档或引用本文档

---

## 13. T2 决议记录

### 决议：接受 T2 Governed Auto-Retain，以宪法级锁定为条件

**理由**：
1. Phase 4 基础设施（filesystem store + recall + approval_status + snapshot visibility）使 governed auto-retain 与 "silent auto-write" 有本质区别
2. Episodic memory 不直接约束行为，T2 仅适用于最低风险类型
3. Constitution P8 从 "永不 auto-write" 精炼为 "No ungoverned auto-write"，保留了原则精神
4. 宪法级锁定（§3.2）防止 T2 扩展到其他类型
5. T2 记录的可见性和可逆性保障了用户信任

**宪法级锁定条款**（不可通过后续 RFC 放松）：
- T2 仅限 episodic — 扩展到其他类型需宪法 amendment
- T2 必须标记 `auto_retained` + `agent_suggested`
- T2 记录必须在 recall/snapshot 中可见
- T2 单 session 上限 3 条
- T2 confidence 区间 [0.6, 0.8)

**如果 T2 被否决**：回退到 D1-D5 的绝对禁止模型。所有 candidate 走 T1 confirmation。Session-end extraction 产生的所有 candidate 进入 pending confirmation（下次 session 展示）。不影响 Phase 4 缺口修复（G1-G6）。

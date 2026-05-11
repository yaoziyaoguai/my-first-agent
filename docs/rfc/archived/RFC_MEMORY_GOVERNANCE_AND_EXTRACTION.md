# Archived RFC

This RFC has been absorbed into:
docs/rfc/MEMORY_CANONICAL_RFC.md

Do not use this document as the canonical memory design source.

---

# RFC: Memory Governance & Extraction

> 状态: 设计阶段，非实现 | 日期: 2026-05-11 | 基于: 全局代码审计

---

## 0. 当前实现状态审计（10 问）

### 0.1 当前 proactive memory 实际深度

**L1 确定性启发式，非真正 "proactive"。**

`agent/memory_suggestions.py` 的 `DeterministicSuggestionEngine` 是纯规则引擎：
- 4 条关键词匹配规则（project_rule, bug_fix_lesson, architecture_decision, repeated_preference）
- 零 LLM 调用，零语义理解，零跨 session 学习
- 准确性依赖中文关键词覆盖面，完全无推理能力

正确的定位：**L1 Heuristic 已实现、已验证**，但这不是 proactive memory 的终点——它是地基，不是建筑。

### 0.2 suggestion framework 是否仅为规则型

**是，纯规则型。** 架构设计了 L1/L2/L3 三层（`docs/PROACTIVE_MEMORY_ARCHITECTURE.md`），但仅 L1 有代码。L2 LLM Proposal 的触发点、prompt 结构、confidence 校准均在文档中设计，代码为零。

### 0.3 LLM extraction 是否存在

**不存在。** 在整个 memory 系统中，没有任何一处调用 LLM 进行 memory extraction：
- `memory_policy.py` — 正则匹配 "remember that" / "记住" 等显式指令
- `memory_suggestions.py` — 关键词匹配
- `memory.py:extract_memories_from_session()` — 直接 `return None`

### 0.4 memory_type 在 store 中如何编码

**硬编码为 `"semantic"`，不存在多样性。**

两处硬编码：
- `agent/memory_fs_store.py:387` — `_meta_from_intent` 中 `memory_type="semantic"`
- `agent/memory_fs_store.py:572` — `_apply_retain` 中 topic route 用 `"semantic"`

`InMemoryMemoryStore` 同理：`_record_from_intent()` 注释明确写了 "v1 限制，当前不携带 memory_type"。

### 0.5 episodic/semantic/procedural 是否已建模

**半建模。** 在 suggestion 层已建模（candidate.metadata 携带 `memory_type`），但存储层不保留。
- `_check_project_rule` → `proposed_type="procedural"`, metadata `{"memory_type": "procedural"}`
- `_check_bug_fix_lesson` → `proposed_type="episodic"`, metadata `{"memory_type": "episodic"}`
- `_check_architecture_decision` → `proposed_type="semantic"`, metadata `{"memory_type": "semantic"}`
- `_check_repeated_preference` → `proposed_type="semantic"`, metadata `{"memory_type": "semantic"}`

但 `MemoryOperationIntent` 不携带 `memory_type`，所以存储时丢失，全部变成 `"semantic"`。

### 0.6 extract_memories_from_session() 实际状态

**完全的空操作。** `agent/memory.py:extract_memories_from_session(messages, client, model_name)` — 函数体只有 `return None`。这是 P2-6 的根因。调用点 `agent/session.py:finalize_session()` 调用后丢弃返回值。

### 0.7 memory governance 是否存在

**存在且被强制执行。** 治理链路完整：

```
policy.decide() → MemoryDecision → confirmation request → user choice
→ resolve_confirmation() → MemoryOperationIntent + MemoryAuditSummary
→ store.apply_operation_intent()
```

`MemoryDecision.requires_user_confirmation` 在 contract 层强制：HIGH/SECRET 敏感度 + RETAIN/UPDATE/RECALL 操作类型必须确认。`DeterministicMemoryPolicy` 的 injection/sensitivity 过滤在 policy 层阻断。

### 0.8 confirmation 与 governance 是否耦合

**已解耦。** Confirmation 层（`memory_confirmation.py`）只处理用户交互——5 种 choice、free_text 编辑、SESSION_ONLY。Governance 逻辑在 policy 层（sensitivity 分级、injection 检测）和 contract 层（`requires_user_confirmation` 强制计算）。两者通过 `MemoryDecision` 桥接，各自独立演化。

### 0.9 runtime/policy/store/suggestion 模块边界

**边界清晰，但存在一处重叠。** 各模块职责分明：
- Runtime: 编排生命周期
- Policy: 显式指令检测 + 安全过滤
- Suggestion: 隐式 pattern 发现（L1 启发式）
- Store: 持久化 + recall
- Confirmation: 用户交互

重叠点：suggestion engine 的 project_rule 检测（"这个项目规定/禁止/必须"）与 policy 的 memory_instruction 检测（"记住 X"）在概念上都是 "从用户文本中提取 memory 意图"，但使用不同的关键词集。这不造成 bug，但在 L2 LLM extraction 引入时应统一为一个 extraction 层。

### 0.10 当前最大架构缺口

**从 suggestion（正确携带 memory_type）到 store（硬编码 "semantic"）的桥是断的。**

根因链：
1. `MemoryOperationIntent` 不携带 `memory_type` / `source_type`
2. `build_memory_operation_intent()` 不传递 suggestion 的 metadata
3. `_meta_from_intent()` 硬编码 `memory_type="semantic"`
4. `_apply_retain()` 硬编码 topic route 为 `"semantic"`

**次缺口**：
- 无 LLM extraction（L2 零代码）
- 无 session-end extraction（`extract_memories_from_session` 是 no-op）
- 无 auto-retain governance tiering（所有路径都需确认）
- 无 procedural memory 的 recall 优先级机制

---

## 1. Memory Taxonomy

### 1.1 三类长期记忆

| 类型 | 存活期 | 内容 | 来源 | 示例 |
|------|--------|------|------|------|
| **Episodic** | 月+ | 过去经历、事件、教训 | 具体交互中发生的事 | "上次因为没加索引导致迁移超时" |
| **Semantic** | 月+ | 持久事实、偏好、决策 | 用户陈述或交互中推断 | "用户偏好 Python", "项目决定用 PostgreSQL" |
| **Procedural** | 月+ | 行为约束、工作流偏好 | 多次交互中浮现的模式 | "用户要求 code review 前不提交" |

**与 working/session memory 的边界**：
- Working（1 turn）和 Session（1 session）是短期记忆，由 context window 承载，不进 store
- Episodic/Semantic/Procedural 是长期记忆，进 filesystem store
- Episodic 可由 session memory 升级而来（session-end extraction）

### 1.2 设计约束

- Procedural memory 必须从真实交互中浮现，不能预写规则
- Procedural memory 的数量应反映实际交互历史——它不是待填充的 rulebase
- 所有三类长期记忆共享同一 filesystem store，通过 `memory_type` 字段区分
- 目录路由：`semantic/`, `episodic/`, `procedural/` — 每类独立 .md 文件

---

## 2. Extraction Lifecycle

### 2.1 完整生命周期

```
Trigger → Extraction → Proposal → Adjudication → Retain → Recall
```

### 2.2 各阶段职责

**Trigger（触发）**：
- L1 关键词匹配（已有）
- L2 LLM extraction at task boundaries（新增）
- Session-end batch extraction（新增）
- Explicit user instruction（已有）

**Extraction（提取）**：
- L1: 规则匹配，confidence 固定（0.70-0.80）
- L2: LLM 分析 conversation segment，输出结构化 candidate，self-calibrated confidence
- Session-end: 扫描整个 session 的 conversation，识别值得保留的 episodic/semantic/procedural

**Proposal（提案）**：
- 生成 MemoryCandidate，携带 memory_type、confidence、source_evidence
- 根据 governance tier 决定走 confirmation 还是 auto-retain 路径
- Dedup：SHA256 去重 + index 查重

**Adjudication（裁决）**：
- 高价值/高置信度 → confirmation flow（已有）
- 低价值 episodic → 可能的 auto-retain（新增 tier）
- Procedural → 必须 confirmation（行为约束不可自动写入）

**Retain（保留）**：
- 写入 filesystem store，保留 memory_type
- 生成 audit trail
- 更新 index

**Recall（召回）**：
- 按 scope/type/recency 过滤
- Snapshot 生成受 governance 约束（max items, char budget, sensitivity filter）

---

## 3. Governance Tiers

### 3.1 三级治理

| Tier | 触发条件 | 路径 | 延迟 |
|------|---------|------|------|
| **T1: Confirmation Required** | 显式用户指令、procedural、高价值 semantic、HIGH/SECRET 敏感度 | proposal → confirmation flow → user choice → retain/reject | 同步（当前 turn） |
| **T2: Auto-Retain** | 低价值 episodic、低置信度但非零价值的 pattern | extraction → auto-retain → store（标记 `approval_status="auto_retained"`） | 异步（session-end） |
| **T3: Ignore** | 低置信度、重复内容、sensitive 阻断、injection 阻断 | extraction → drop | 即时 |

### 3.2 T2 Auto-Retain 的安全边界

- 仅适用于 episodic 类型
- confidence 必须 ≥ 0.6 且 < 0.8（太低不可靠，太高应该走 T1）
- 不得包含 SECRET/HIGH 敏感度内容
- store 时必须标记 `approval_status="auto_retained"` 和 `source_type="agent_suggested"`
- recall 时 auto_retained 记录在 snapshot 中标注来源，让用户可见
- 用户后续可通过显式指令 upgrade 到 T1（修改 approval_status → "approved"）

### 3.3 T1 Confirmation 不可绕过

以下情况必须走 T1，不得降级为 T2：
- 显式用户指令（"记住 X"）
- Procedural 类型（行为约束）
- 高置信度 semantic（≥0.8）
- SECRET/HIGH 敏感度（即使通过 sensitivity filter 的边界情况）
- 任何标记 `requires_user_confirmation=True` 的 decision

---

## 4. Session Inline Extraction

### 4.1 当前状态

L1 启发式已实现，在用户每次输入后触发 `evaluate_user_text()`。

### 4.2 L2 LLM Extraction 设计（Phase 5）

**触发时机**：不每次输入都调 LLM。在以下边界触发：
- 用户连续 N 轮输入后（N≥5）
- 检测到 task boundary（用户说 "OK", "done", "下一步" 等）
- 用户显式触发

**输入**：最近 N 轮 conversation（user + assistant turns），不含 tool 输出细节

**Prompt 结构**（概念）：
```
分析以下对话，提取值得保留的 memory：
- Episodic: 发生了什么、学到了什么教训
- Semantic: 用户的偏好、决策、事实
- Procedural: 用户暗示的工作流偏好

对每个 candidate 给出：
- memory_type
- content（简洁，≤200 字）
- confidence（0.0-1.0）
- source_evidence（引用对话中的原句）
```

**输出**：多个 MemoryCandidate，由 governance tier 路由到 confirmation 或 auto-retain。

**成本控制**：
- 仅在触发边界调用，不每次输入都调
- 使用 Haiku 模型降低成本
- Session 内最多调用 5 次

---

## 5. Session-End Extraction

### 5.1 设计

`extract_memories_from_session()` 的重实现，在 `finalize_session()` 中调用。

**输入**：整个 session 的 messages 列表（user + assistant + tool 结果摘要）

**流程**：
1. 扫描整个 session，识别值得保留的内容
2. 与已有 store 做 dedup（SHA256 + index 查重）
3. 对每个 candidate 按 governance tier 路由：
   - T1 → 生成 confirmation request（下次 session 启动时展示）
   - T2 → auto-retain 写入 store
   - T3 → 丢弃
4. 返回 extraction summary（提取了哪些 candidate、哪些待确认、哪些已 auto-retain）

**与 inline extraction 的分工**：
- Inline: 实时、低延迟、高精度（当前上下文中）
- Session-end: 批量、回顾性、可以发现跨 turn 的 pattern

### 5.2 待确认 candidate 的跨 session 传递

Session-end 产生的 T1 candidate 无法在当前 session 确认（用户已离开）。解决方案：
- 写入 store 的 `_pending_confirmation/` 目录
- 下次 session 启动时，`MemoryRuntime` 检查 pending confirmations
- 在 conversation 开头向用户展示："上次 session 中我发现以下可能值得记住的内容，请确认..."
- 用户确认后转入正常 confirmation flow

---

## 6. Importance & Confidence

### 6.1 Confidence 语义

| 区间 | 含义 | 默认动作 |
|------|------|---------|
| 0.0-0.3 | 低价值噪音 | T3 Ignore |
| 0.3-0.6 | 不确定，不值得保留 | T3 Ignore |
| 0.6-0.8 | 有价值但不确定 | T2 Auto-Retain（仅 episodic） |
| 0.8-1.0 | 高价值、高确定性 | T1 Confirmation |

### 6.2 L1 固定 Confidence（当前）

```
project_rule:        0.80
bug_fix_lesson:      0.70
architecture_decision: 0.75
repeated_preference: 0.70
```

这些值基于对关键词匹配可靠性的经验估计，不是通过校准得出的。

### 6.3 L2 LLM Self-Calibrated Confidence（Phase 5）

LLM 在 extraction 时自带 confidence，但需要校准：
- 在开发阶段用标注数据验证 LLM confidence 与实际价值的对应关系
- 如 LLM confidence 系统性偏高，用 calibration layer 修正
- calibration 参数存储在 store 的 metadata 中，可随使用迭代

### 6.4 Importance（重要性）vs Confidence（置信度）

- Confidence = 提取的确定性（"我确定这是一个真实的用户偏好"）
- Importance = 对 agent 行为的潜在影响（"这个偏好会改变 agent 的工作方式"）
- Procedural memory 天然具有高 importance（它改变行为），所以必须 T1
- 当前设计用 memory_type + confidence 联合决定 tier，暂不引入独立的 importance 维度

---

## 7. Proposal vs Auto-Retain

### 7.1 决策矩阵

| | Episodic | Semantic | Procedural |
|---|---------|----------|-------------|
| **L1 Heuristic (confidence≥0.6)** | T1 Confirmation | T1 Confirmation | T1 Confirmation |
| **L2 LLM (confidence≥0.8)** | T1 Confirmation | T1 Confirmation | T1 Confirmation |
| **L2 LLM (0.6≤confidence<0.8)** | T2 Auto-Retain | T1 Confirmation | T1 Confirmation |
| **L2 LLM (confidence<0.6)** | T3 Ignore | T3 Ignore | T3 Ignore |
| **Explicit user instruction** | T1 Confirmation | T1 Confirmation | T1 Confirmation |

### 7.2 为什么 Procedural 永远 T1

Procedural memory 直接影响 agent 行为（"review 前不提交"、"优先使用 pytest"）。自动写入行为约束等价于 agent 单方面改变自己的行为规则——这违反了 "Agent proposes, Human adjudicates" 宪法原则。

### 7.3 为什么 Episodic 可以 Auto-Retain

Episodic memory 记录发生过的事（"上次迁移超时因为没加索引"），不直接约束行为。低置信度的 episodic 即使有噪音，recall 时用户看到也不会被误导——它们被明确标注为 `auto_retained`。代价低，收益是保留了可能有用的事件记录。

---

## 8. Filesystem-Native Constraints

### 8.1 设计原则

- Markdown + YAML frontmatter 是唯一存储格式
- 文件系统是 source of truth
- 不做向量数据库、不做 embedding、不做语义搜索、不做图数据库
- 索引（index.json）是派生数据，可随时重建

### 8.2 当前能力

`agent/memory_fs_store.py`（~700 行，Phase 4 已完成）：
- 原子写入（temp file + rename）
- Index rebuild <8ms（50 records / 12 files 验证）
- Topic 路由：`semantic/user_preferences.md`, `episodic/2026-05-11.md`, `procedural/learned.md`
- 按 scope/type/recency 的 recall

### 8.3 约束与上限

基于 spike 数据：
- ≤200 active records：索引和 recall 性能可接受
- 200-500：需要 consolidation（合并重复/过时记录）
- >500：需要归档策略
- 单用户、单进程、无并发冲突

### 8.4 不需要的东西（明确排除）

- 向量数据库（FAISS, Chroma, Pinecone）
- Embeddings（OpenAI text-embedding 等）
- 语义搜索
- 图数据库
- 新的重量级依赖
- pyyaml（当前用 stdlib-only 的 YAML frontmatter parser）

---

## 9. Phase 4 / 5 Boundaries

### 9.1 Phase 4 — 当前状态（已完成）

```
✅ FilesystemMemoryStore（读写、atomic write、index）
✅ MEMORY_STORE_BACKEND / MEMORY_ROOT 环境变量
✅ recall API（scope/type/recency 过滤）
✅ MemorySnapshot governance（max items, char budget, sensitivity filter）
✅ L1 heuristic suggestion engine
✅ Two-phase confirmation flow
✅ Policy-driven sensitivity/injection blocking
```

### 9.2 Phase 4 待修复（结构性缺口，非 P2 bug）

这些是让 Phase 4 "真正完整"的剩余工作：

1. **memory_type 流通**：`MemoryOperationIntent` 添加 `memory_type`/`source_type` 字段，`build_memory_operation_intent()` 传递 suggestion metadata，`_meta_from_intent()` 使用实际 memory_type 而非硬编码 "semantic"
2. **auto_retained approval_status**：store 写入时记录 `approval_status`（当前只有 "approved" 和 "rejected"）
3. **recall 中的 memory_type 多样性**：确保 episodic/procedural 记录可被 recall 和 snapshot 正确返回

### 9.3 Phase 5 — Extraction & Auto-Retain（本 RFC 核心）

```
🔲 L2 LLM extraction at task boundaries
🔲 Session-end extraction（重实现 extract_memories_from_session）
🔲 Auto-retain governance tier（T2）
🔲 Pending confirmation 跨 session 传递
🔲 L2 confidence calibration
🔲 extraction → suggestion → confirmation 统一数据流
```

### 9.4 Phase 6+ — Consolidation（远期研究）

```
🔮 Cross-session pattern extraction（episodic → procedural 升级）
🔮 Record decay / staleness
🔮 Archival（旧记录归档，保持 active set ≤200）
🔮 Proceduralization（多条 episodic→semantic→procedural 的自底向上抽象）
```

---

## 10. 当前明确不做什么

### 10.1 不做

- **向量数据库 / embeddings / 语义搜索**：filesystem-native 是宪法级设计决策
- **图数据库 / 知识图谱**：不引入新的存储范式
- **自动写入 procedural memory**：永远 T1 confirmation
- **无确认写入高价值 semantic memory**：≥0.8 confidence 也必须 T1
- **新重量级依赖**：保持依赖最小化
- **多用户 / 并发 / 分布式**：单用户、单进程、local-first 是 hard constraint

### 10.2 Phase 5 也不做（留给 Phase 6+）

- Episodic → Procedural 自动升级（proceduralization）
- 跨 session pattern mining
- Record 自动 decay / 过期
- 归档策略

### 10.3 实现优先级

Phase 5 实现顺序：
1. `MemoryOperationIntent` 添加 `memory_type`/`source_type` 字段（打通 Phase 4 缺口）
2. `_meta_from_intent()` / `_apply_retain()` 使用实际 memory_type（修复硬编码）
3. `extract_memories_from_session()` 重实现（session-end extraction + L2 LLM）
4. Auto-retain governance tier（T2，仅 episodic）
5. Pending confirmation 跨 session 传递
6. L2 inline extraction at task boundaries

每一步独立可验证，不依赖后续步骤。

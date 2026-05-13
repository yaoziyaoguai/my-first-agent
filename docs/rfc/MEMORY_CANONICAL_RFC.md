# Memory Canonical RFC

> **版本**: v2.2 — Architecture Reconciliation + Automated Guardrails
> **日期**: 2026-05-12
> **状态**: Canonical — Memory 体系唯一权威设计文档
> **取代**: v2.1 (2026-05-12), v2.0 (2026-05-12), v1.0 (2026-05-11), 及所有历史 Memory 设计文档

---

## TL;DR — for Humans and Coding Agents

### Lifecycle Spine

```
Interaction → Extraction → Episodic → Consolidation → Semantic → Emergence → Procedural
```

Memory 不是平级功能列表。它是一个**方向性认知生命周期**。

### Governance at a Glance

| Memory Type | Default Governance | Rule |
|:---|:--:|------|
| Episodic | T2 mostly silent | "那次发生了什么" — 记录事件，不约束行为 |
| Semantic | T2 from consolidation, T1 otherwise | "我知道了什么" — 稳定事实/偏好 |
| Procedural | **T1 always** | "以后必须/禁止这样做" — 永远需显式确认 |

### Write Interfaces (≠ Memory Types)

| # | Entry | Status |
|:--:|-------|:--:|
| W1 | Explicit Retain（用户主动 "记住 X"） | ✅ |
| W2 | Inline Proactive Suggestion（L1/L2 实时） | 🟡 L1 done |
| W3 | Session-End Extraction（批量扫描） | 🔲 |
| W4 | Background Consolidation（episodic → semantic） | 🔲 |
| W5 | Emergence Detection（→ procedural candidate） | 🔮 |

### Current Phase

Phase 4 baseline + G1-G6 structural gaps (~38 lines). Next: Phase 5a (W3 + T2).

### Core Constraints

- **Extraction ≠ Persistence**: 提取器只产出 candidate，不写 store
- **Write Interface ≠ Memory Type**: 入口决定如何进入，lifecycle 决定最终类型
- **Procedural 永远 T1**: 不可 silent retain
- **Filesystem is source of truth**: index.json 是派生数据
- **所有自动路径必须可逆**: T2 记录可删除/upgrade
- **Metadata Continuity**: `memory_type`/`source_type`/`approval_status` 禁止在 pipeline 中被重新推断（§14.5）
- **Snapshot Budget is runtime-enforced**: 不是建议，是硬截断（§13.2, Appendix H.4）
- **Architecture Guardrails are automated**: 关键边界有 CI-enforced tests（Appendix H）

### Agent Entry Points

| 如果你要实现... | 先读... |
|:---|:---|
| Session-end extraction | §3 Lifecycle → §11.4 W3 → Appendix C Episodic Schema |
| T2 auto-retain | §10.2 T2 锁定 → §5 Episodic Governance |
| Consolidation | §6 Consolidation → Appendix D Consolidation Semantics |
| Procedural emergence | §8 Emergence → §9 Procedural → Appendix E Mutation Boundary |
| Recall differentiation | §13 Recall → Appendix F Recall Semantics |
| Any new memory feature | §1 Constitution（宪法兼容性检查）→ §3 Lifecycle（阶段归属） |
| Architecture boundary verification | Appendix H（Automated Guardrails）→ §14.6（Runtime Growth） |

---

## 0. 定位与文档治理

### 0.1 本文档是什么

本文档是 my-first-agent Memory 体系的**唯一 canonical 设计文档**。任何两份文档之间的冲突，以本文档为准。任何实现与本文档的偏差，以本文档为修正方向。

**本文档不是**：实现代码、操作手册、路线图、历史记录。

**本文档是**：Constitution 原则、Taxonomy 定义、Lifecycle 架构、Governance 规则、Extraction 机制、Store 约束、Implementation 映射、Operational Semantics 的权威表述。

### 0.2 组织原则

v2.2 在 v2.1 lifecycle-oriented 基础上增加了：
- **顶部 TL;DR**：人类和 Coding Agent 的快速入口
- **Section-level TLDR**：每个主要 section 开头的一句话总结
- **Agent Entry Points**：按实现任务导航到相关 section
- **Operational Semantics Appendices**：Episodic Schema、Consolidation、Procedural Mutation Boundary、Recall 的操作语义
- **Automated Architecture Guardrails (Appendix H)**：两轮独立架构审计确认后可自动化验证的架构边界

### 0.3 Stable Anchors

本文档所有 section 和 appendix 编号为 stable anchors。外部文档、prompt、代码注释可直接引用：

```
RFC §3     → Memory Lifecycle
RFC §10.2  → T2 宪法级锁定
RFC App C  → Episodic Record Semantics
RFC App D  → Consolidation Semantics
RFC App E  → Procedural Mutation Boundary
RFC App F  → Recall Semantics
RFC App G  → Implementation Constraints (SDD)
RFC App H  → Automated Architecture Guardrails (Fitness Functions)
```

### 0.4 Amendment 规则

- 修改 §1（Constitution）和 §3（Lifecycle 阶段边界）需要 explicit justification
- 修改 §10（Governance Tiers）的 T2 锁定条件需要 explicit justification
- 修改 Appendix C-F（Operational Semantics）需要实现验证或 dogfood 证据
- 修改 Appendix G（Implementation Constraints）和 Appendix H（Automated Guardrails）需要 architecture audit 确认
- 其他 section 可随实现演进而更新，但必须保持与 Constitution 的一致性

---

## Part I: Foundation

---

## 1. Constitution

> **TLDR**: 10 条不可妥协的宪法原则。P8 是 governance 的根：所有写入必须经 T1 或 T2，不存在第三条路径。

以下 10 条原则是不可妥协的宪法级约束。

| # | 原则 | 含义 |
|---|------|------|
| **P1** | Agent proposes, Human adjudicates | Agent 可提议 "这值得记住"，不可单方面决定 "这已被记住" |
| **P2** | Memory ≠ Retrieval | Memory 是认知与行为塑形，retrieval 是可选 backend |
| **P3** | Local-first, human-readable | 所有 memory 本地存储；用户可直接打开、阅读、编辑 |
| **P4** | Governance before storage | 所有写入必须经过 governance routing，不可绕过 |
| **P5** | Behavior shaping over data accumulation | 少而精；memory 的目标是改变长期行为，不是积累文本 |
| **P6** | Forgetting is first-class | 删除与写入同等重要；forget 无需确认，立即生效 |
| **P7** | Explainable provenance | 每条 memory 必须回答 "谁、何时、为什么" |
| **P8** | No ungoverned auto-write | 所有写入必须经 T1 Confirmation 或 T2 Governed Auto-Retain（见 §10.2）。不存在第三条路径 |
| **P9** | Sensitive content never enters memory | 安全红线；sensitivity 检查不可绕过 |
| **P10** | Memory must not swallow neighbors | 不与 Skill / Checkpoint / Task 系统重叠 |

### 1.1 P8 详解

> 所有 memory 写入必须经过 governance。Governance 路径有且仅有两条：
> - **T1 Confirmation**：用户显式确认后写入
> - **T2 Governed Auto-Retain**：经自动化 governance 检查后写入，仅限 episodic，必须标注 `auto_retained`
>
> 不存在第三条路径。T2 不可扩展到 episodic 以外的任何类型。

### 1.2 人类权利

| 权利 | 含义 | 实现锚点 |
|------|------|:--:|
| 知情权 | 知道 Agent 记住了什么 | recall / status / inspect |
| 编辑权 | 直接修改 memory 内容 | EDIT_AND_ACCEPT |
| 删除权 | 立即删除任何 memory | forget flow |
| 解释权 | 知道 memory 如何影响行为 | provenance 字段 |
| 拒绝权 | 拒绝 Agent 的 memory proposal | REJECT / SESSION_ONLY |

---

## 2. Memory Taxonomy

> **TLDR**: 三层 taxonomy — Working/Session (不进 store)、Episodic (事件)、Semantic (知识)、Procedural (行为约束)。Episodic → Semantic → Procedural 存在方向性沉淀关系。

### 2.1 两层架构

**Runtime/Context Layer** — 不进 filesystem store，不进 governance chain：

| 类型 | 存活期 | 持久化 | Governance |
|------|--------|:--:|------|
| Working | 1 turn | 否 | 不需要 |
| Session | 1 session | 否 | SESSION_ONLY choice |

**Long-Term Memory Layer** — 进 filesystem store，经 governance chain：

| 类型 | 存活期 | 持久化 | Governance | 行为影响 |
|------|--------|:--:|------|:--:|
| Episodic | months+ | 是 | T1 或 T2（见 §10） | 间接（precedent reference） |
| Semantic | months+ | 是 | T1 或 T2（见 §10） | 间接（prompt 可见偏好） |
| Procedural | months+ | 是 | T1 强制 | 直接（行为约束） |

Runtime/Context Layer 与 Long-Term Memory Layer 之间的边界是硬性的。本文档后续所有内容仅针对三类长期记忆。

### 2.2 三类长期记忆定义

**Episodic（情景记忆）** — "那次发生了什么"
- 内容：以具体事件为中心的叙事性记录，有时间锚点、上下文和因果链
- 核心特征：有时间锚点、有因果结构、可复述为完整叙事
- 子类型：bug_fix_episode, troubleshooting_episode, refactor_experience, decision_outcome
- 示例："2026-05-11 测试迁移因缺少复合索引导致超时，加索引后恢复"
- 详细 schema：见 Appendix C

**Semantic（语义记忆）** — "我知道了什么"
- 内容：持久事实、用户偏好、项目决策、稳定知识
- 子类型：user_preference, user_fact, project_rule, project_decision, repo_convention
- 示例："用户偏好 pytest"、"项目决定用 PostgreSQL"、"用户是数据工程师"

**Procedural（程序记忆）** — "以后必须/禁止这样做"
- 内容：从真实交互中浮现的长期行为约束
- 子类型：critique_learned, communication_rule
- 示例："调试 bug 必须先查日志和 checkpoint 实际数据，找到根因再最小修复"
- 行为影响边界：见 Appendix E

### 2.3 Procedural Memory 法定判定标准

必须同时满足以下 5 条，缺一不可：

1. ✅ 来源必须是真实交互/批评/纠正 — 不是预设、模板、配置
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

---

## Part II: Lifecycle Architecture

---

## 3. Memory Lifecycle（主轴）

> **TLDR**: Interaction → Extraction → Episodic → Consolidation → Semantic → Emergence → Procedural。每个阶段有明确的输入、输出、governance 级别。Write Interface ≠ Memory Type。

### 3.1 生命周期全景

Memory 不是平级的功能列表。它是一个**方向性认知生命周期**：

```
Interaction (用户与 Agent 的对话)
  │
  ├─→ W1: Explicit Retain ──────────→ Semantic / Procedural（用户直接指定类型）
  ├─→ W2: Inline Suggestion ────────→ Episodic / Semantic（实时提取候选）
  ├─→ W3: Session-End Extraction ───→ Episodic（批量扫描，主要 episodic 入口）
  │
  ▼
Episodic Memory（情景记忆层）
  │  记录具体事件、时间锚点、因果链
  │  mostly silent（T2 auto-retain）
  │
  ▼
Consolidation（沉淀）
  │  跨事件模式识别 → 提取稳定事实/偏好
  │  silent candidate generation + T1 human review
  │
  ▼
Semantic Memory（语义记忆层）
  │  持久事实、偏好、项目知识
  │  mostly silent（来自 consolidation 的 high-confidence）
  │
  ▼
Emergence（涌现）
  │  行为模式检测：semantic + episodic + correction pattern
  │  → procedural candidate
  │  always T1 human review
  │
  ▼
Procedural Memory（程序记忆层）
  │  长期行为约束
  │  strict governance（必须 T1）
  │
  ▼
Behavioral Influence（行为影响）
    通过 recall/snapshot 进入 prompt，塑形 Agent 长期行为
```

### 3.2 生命周期各阶段概览

| 阶段 | 输入 | 输出 | Governance | 实现状态 |
|------|------|------|:--:|:--:|
| **Ingestion** | 对话、用户指令 | 原始事件、candidate | 取决于 Write Interface | 🟡 W1/W2 implemented, W3/W4/W5 planned |
| **Episodic** | 提取的事件 | 情景记录（带时间锚点） | T2 mostly silent | 🔲 planned |
| **Consolidation** | 多条 episodic | semantic candidate（带 episodic evidence） | T1 human review | 🔲 planned |
| **Semantic** | consolidation + explicit retain | 语义记录 | T2 for high-confidence consolidation | 🟡 explicit retain implemented |
| **Emergence** | semantic + episodic + correction | procedural candidate | T1 强制 | 🔮 research |
| **Procedural** | emergence candidate 经确认 | 行为约束记录 | T1 强制 | 🟡 explicit retain 可产出 |
| **Recall** | store query | governed snapshot | N/A（只读） | ✅ implemented |

### 3.3 关键设计原则

1. **Write Interface ≠ Memory Type**：写入入口决定 *如何进入系统*，lifecycle 决定 *最终成为什么类型*
2. **Episodic 是主要入口**：semantic 和 procedural 应当主要来自沉淀和涌现，而非直接提取
3. **沉淀需要 evidence chain**：semantic 应追溯到 episodic evidence；procedural 应追溯到 semantic + episodic + correction
4. **Governance 随阶段升级**：episodic 最轻（silent），procedural 最重（always T1）

---

## 4. Write Interfaces（写入入口）

> **TLDR**: 5 个写入入口 (W1-W5)。入口决定 "如何进入系统"，lifecycle 决定 "最终成为什么类型"。W1/W2 已实现且必须保留。

### 4.1 Write Interface ≠ Memory Type

Write Interface 是 memory 的**摄入入口**，不是 memory type。同一个入口可以产出不同类型的 memory；同一个 memory type 可以来自不同入口。最终类型由 lifecycle pipeline 决定，不由入口决定。

### 4.2 五个 Write Interfaces

| # | Interface | 触发 | 延迟 | 典型输出类型 | 实现状态 |
|:--:|----------|------|------|------------|:--:|
| **W1** | Explicit Retain | 用户主动 "记住 X" | 同步 | Semantic / Procedural（用户指定） | ✅ |
| **W2** | Inline Proactive Suggestion | 每次用户输入后（L1）/ task boundary（L2） | 同步（当前 turn） | Episodic / Semantic（heuristic/LLM 判断） | 🟡 L1 done, L2 planned |
| **W3** | Session-End Extraction | session 结束时 | 批量（session 结束） | Episodic（主要入口） | 🔲 |
| **W4** | Background Consolidation | 跨 session 模式积累 | 异步（后台） | Semantic（从 episodic 沉淀） | 🔲 |
| **W5** | Emergence Detection | 长期行为模式积累 | 异步（低频） | Procedural candidate | 🔮 |

### 4.3 W1: Explicit Retain（✅ implemented）

用户显式触发。这是唯一用户可以**直接指定** memory type 的入口。

```
用户 "记住：我喜欢用 pytest"
  → memory_policy.decide() → RETAIN
  → 用户确认（T1）
  → 写入 store（memory_type 由 content 推断 + 用户可编辑）
```

当前实现：`memory_policy.py` + `memory_runtime.py` 的显式 retain 路径。

### 4.4 W2: Inline Proactive Suggestion（🟡 L1 done, L2 planned）

Agent 在 session 中主动提议 "这个可能值得记住"。不是自动写入 — 必须经 confirmation（当前全量 T1）。

**L1 Heuristic**（✅ implemented）：
`agent/memory_suggestions.py` — 4 条确定性规则，零 LLM 调用。覆盖显式模式（"这个项目规定…"、"上次就是因为…"）。

**L2 LLM**（🔲 planned）：
在 task boundary / N≥5 turns 后调用 LLM 分析 conversation segment。输出 episodic candidate（0.6-0.8 → T2 auto-retain，≥0.8 → T1）。

当前实现位置：`memory_runtime._try_suggestions()` → L1 only，全量 T1。

### 4.5 W3: Session-End Extraction（🔲 planned）

Session 结束时批量扫描整个 session 的对话，提取所有值得保留的 episodic 事件。这是 episodic memory 的**主要入口**。

```
Session 结束
  → 扫描全部 messages（user + assistant + tool 摘要）
  → LLM 提取 episodic candidate
  → dedup 与已有 store
  → T2 auto-retain（默认为 episodic）
  → 返回 extraction summary
```

当前状态：`agent/memory.py:extract_memories_from_session()` 是 no-op（`return None`）。

### 4.6 W4: Background Consolidation（🔲 planned）

跨 session 的模式识别：从多条 episodic 中检测稳定的跨事件模式，propose semantic candidate。

```
触发：episodic count ≥ threshold（如 ≥5）或每 N sessions
  → 扫描 episodic/ 目录中未 consolidated 的记录
  → 检测跨事件稳定模式（相似主题、重复偏好、一致决策）
  → 生成 semantic candidate（带 episodic evidence 链）
  → T1 human review
```

### 4.7 W5: Emergence Detection（🔮 research）

长期行为模式涌现：从 semantic + episodic + repeated correction 中检测行为约束信号，propose procedural candidate。

```
触发：correction pattern frequency ≥ threshold（如 ≥3）
  → 追踪用户对 Agent 行为的反复纠正
  → 结合 semantic preference 和 episodic lesson
  → 生成 procedural candidate（带完整 evidence chain）
  → T1 human review（强制 — procedural 永不可 silent）
```

---

## 5. Episodic Memory

> **TLDR**: 长期记忆第一层。记录事件、时间锚点、因果链。mostly silent (T2)。是 semantic/procedural 的 grounding 来源。

### 5.1 定位

Episodic memory 是长期记忆的**第一层**。它记录具体交互事件——带时间锚点、上下文和因果链。它是 semantic 和 procedural memory 的 grounding 来源。

### 5.2 来源

- **W2 Inline Suggestion**（L1/L2 实时提取的事件）
- **W3 Session-End Extraction**（批量扫描，主要来源）
- 用户显式 W1 很少直接产出 episodic（用户通常说 "记住我的偏好"，不是 "记住这件事"）

### 5.3 Governance

Episodic memory 对行为的直接影响最小 → governance 最轻：

| Confidence | 来源 | Governance |
|-----------|------|:--:|
| <0.6 | 任何来源 | T3 Ignore |
| 0.6-0.8 | W2 L2 / W3 Session-End | **T2 Governed Auto-Retain** |
| ≥0.8 | W2 L2 / W3 | T1 Confirmation |

T2 auto-retain 的宪法级锁定（见 §10.2）：
- 仅限 episodic 类型
- confidence [0.6, 0.8)
- sensitivity ≤ MEDIUM
- 单 session T2 上限 3 条
- 必须标记 `approval_status="auto_retained"` 和 `source_type="agent_suggested"`
- recall/snapshot 中必须可见，标注 "[自动记录]"

### 5.4 存储

```
episodic/
  └── YYYY-MM-DD.md    # 按日期组织
```

详细 record schema：见 Appendix C。

### 5.5 下游

Episodic memory 是 Consolidation（§6）的输入。多次类似事件沉淀出 semantic pattern。

---

## 6. Consolidation（Episodic → Semantic）

> **TLDR**: 多条 episodic → 跨事件模式识别 → semantic candidate。silent generation + T1 human review。不自动删除源 episodic，不产出 procedural。

### 6.1 定位

Consolidation 是 episodic memory → semantic memory 的**沉淀过程**。它从多条跨 session 的 episodic 记录中识别稳定模式，提炼为持久 semantic 知识。

详细操作语义：见 Appendix D。

### 6.2 触发条件（设计值，待实现时校准）

- episodic 中未 consolidated 的记录数 ≥ 5
- 或每 3 个 session 结束触发一次
- 或用户显式触发

### 6.3 操作类型

| 操作 | 描述 | 示例 |
|------|------|------|
| **Pattern Detection** | 多条 episodic 揭示同一偏好/事实 | 3 次 episodic 都涉及 "用户要求中文注释" → semantic "用户偏好中文注释" |
| **Merge** | 合并高度相似的 episodic | "4 月 28 日 PG 迁移超时" + "5 月 2 日 PG 迁移超时" → "PG 迁移易因缺索引超时" |
| **Abstract** | 提取跨事件的一般性知识 | 多次 "测试因 X 失败" → "测试失败常与数据库状态有关" |

### 6.4 Governance

- Candidate generation: **silent**（后台自动运行）
- Candidate adoption: **T1 human review**（用户审核 semantic proposal，可接受/编辑/拒绝）
- 被 accept 的 semantic record 必须携带 `source_evidence`（引用的 episodic ID 列表）

### 6.5 不做的

- 不自动合并 procedural（procedural 只能来自 emergence，§8）
- 不自动删除源 episodic（保留为 evidence trail）
- 不在 session 中途触发（仅 session 边界或后台）

---

## 7. Semantic Memory

> **TLDR**: 长期记忆第二层。持久事实/偏好/知识。来自 W1 explicit retain + W4 consolidation。

### 7.1 定位

Semantic memory 是长期记忆的**第二层**。它存储持久事实、偏好和项目知识——比 episodic 更稳定、更抽象、更长期。

### 7.2 来源

- **W1 Explicit Retain**：用户直接 "记住 X"（跳过 episodic）
- **W4 Consolidation**：从 episodic 沉淀（主要长期来源）
- **W2 Inline Suggestion**：L1/L2 识别出显式偏好表达（如 "我喜欢用 pytest"）

### 7.3 Governance

| Confidence | 来源 | Governance |
|-----------|------|:--:|
| Explicit retain (W1) | 用户主动 | T1 Confirmation（用户已表达意图，确认即可） |
| Consolidation (W4) — high stability | 多次 episodic 支撑 | T1 adoption review |
| Inline suggestion | L1/L2 | T1 Confirmation |
| <0.7 | 任何自动来源 | T3 Ignore |

### 7.4 存储

```
semantic/
  ├── user_preferences.md
  ├── user_facts.md
  ├── project_rules.md
  └── project_decisions.md
```

---

## 8. Emergence（→ Procedural）

> **TLDR**: semantic + episodic + repeated correction → procedural candidate。silent detection + T1 强制 human review。Procedural 永不可 silent retain。

### 8.1 定位

Emergence 是 semantic + episodic + repeated correction → procedural candidate 的**涌现过程**。它是 memory 体系中最深层的认知操作——不是 "记住偏好"，而是 "从交互历史中识别出长期行为约束"。

### 8.2 触发条件（设计值，Phase 7 详细设计）

- 同一 correction pattern ≥ 3 次（用户反复纠正 Agent 同一类行为）
- 多条 semantic preference + 多条 episodic lesson 共同指向一个行为方向
- 不自动触发 procedural adoption — 永远只生成 candidate

### 8.3 信号类型

| 信号 | 示例 | 强度 |
|------|------|:--:|
| **Repeated Correction** | 用户连续 3 次说 "先查日志，不要猜" | 强 |
| **Semantic + Episodic 交叉验证** | semantic "用户偏好最小修复" + episodic "大重构引发回归" | 中 |
| **Single Strong Critique** | 用户明确说 "以后永远不要自动 commit" | 强（但仍是 single event） |

### 8.4 Governance

- Candidate generation: **silent**（后台检测 pattern）
- Candidate adoption: **T1 human review 强制**
- Procedural 永远不可 silent retain — 即使是 emergence 检测到的最高置信度 pattern
- 用户拒绝的 procedural candidate：记录拒绝原因，降低同类 pattern 的 emergence 优先级

### 8.5 不做的（Phase 7 之前）

- 不自动生成 procedural
- 不自动执行行为变更
- 不将 emergence candidate 直接写入 store（必须经 T1）
- 不做跨用户/跨项目的 pattern 迁移

---

## 9. Procedural Memory

> **TLDR**: 长期记忆最上层。长期行为约束。永远 T1。行为影响范围受 Appendix E 约束。

### 9.1 定位

Procedural memory 是长期记忆的**最上层**。它存储长期行为约束——不是 "用户喜欢什么"，而是 "Agent 以后应该怎么做"。行为影响力最大，因此 governance 最严格。

行为影响边界：见 Appendix E。

### 9.2 来源

- **W1 Explicit Retain**：用户直接要求记住行为规则
- **W5 Emergence Detection**：从 semantic + episodic + correction 中涌现

不存在第三条产生 procedural 的路径。不可从单次 interaction 中直接提取 procedural（即使是 LLM）。

### 9.3 Governance

**Procedural 永远 T1 Confirmation。不存在 T2 路径。**

这是宪法级锁定（P1 + P8 + §2.3 五条判定标准的共同约束）。理由：
- Procedural 直接约束 Agent 行为，错误的 procedural 会造成持续损害
- 行为约束的可解释性要求高于事实/偏好
- 用户必须明确同意 "Agent 以后将按此规则行动"

### 9.4 存储

```
procedural/
  └── learned.md
```

---

## Part III: Governance

---

## 10. Governance Tiers

> **TLDR**: T1 (必须确认) / T2 (governed auto-retain, 仅 episodic) / T3 (丢弃)。T2 受宪法级锁定约束。Procedural 永远 T1。

### 10.1 三级治理

```
所有 candidate 必须经过 governance routing 才能进入 store。
不存在绕过 governance 的写入路径。
```

| Tier | 触发条件 | 路径 | 延迟 |
|------|---------|------|------|
| **T1: Confirmation Required** | 显式用户指令 / Procedural 任何情况 / Semantic ≥0.7 / L1 所有 candidate / HIGH+ 敏感度 / W4/W5 candidate | proposal → confirmation flow → user choice → retain/reject | 同步（当前 turn 或下次 session 启动） |
| **T2: Governed Auto-Retain** | 仅 Episodic / W2 L2 或 W3 Session-End / confidence 0.6-0.8 / sensitivity ≤MEDIUM | extraction → auto-retain → store（`approval_status="auto_retained"`） | 同步或异步 |
| **T3: Ignore** | confidence <0.6 / 重复内容 / SECRET 敏感度 / prompt injection | extraction → drop | 即时 |

### 10.2 T2 宪法级锁定

T2 是对 P8 的精炼，不是违反。以下约束是宪法级锁定，不可在后续版本中放松：

**范围锁定**：
- T2 仅适用于 episodic 类型
- 扩展 T2 到 semantic 或 procedural 需要宪法级 amendment

**安全锁定**：
- confidence 必须在 [0.6, 0.8) 区间
- sensitivity 必须 ≤ MEDIUM
- 必须通过 SHA256 dedup 和 index 查重
- 必须通过 prompt injection 检测

**可见性锁定**：
- 必须标记 `approval_status="auto_retained"` 和 `source_type="agent_suggested"`
- recall 和 snapshot 中必须标注 `[自动记录]`
- 用户可随时：删除（即时生效）或 upgrade 到 `approved`

**数量锁定**（代码强制）：
- 单 session T2 写入上限：3 条
- 单 session 总 suggestion（T1 + T2）上限：5 条

### 10.3 T1 不可降级

以下情况**必须**走 T1，不得降级为 T2：
- 显式用户指令（W1）
- Procedural 类型（任何来源、任何 confidence）
- 高置信度 semantic（L1 ≥0.7, L2 ≥0.8, W4 consolidation）
- SECRET/HIGH 敏感度
- L1 heuristic 产生的所有 candidate
- W4/W5 产生的所有 candidate（consolidation/emergence 输出）

### 10.4 Lifecycle × Governance 交叉矩阵

| Lifecycle 阶段 | Episodic | Semantic | Procedural |
|:---|:--:|:--:|:--:|
| **W1 Explicit Retain** | T1 | T1 | T1 |
| **W2 L1 Heuristic** | T1 | T1 | T1 |
| **W2 L2 LLM (≥0.8)** | T1 | T1 | T1 |
| **W2 L2 LLM (0.6-0.8)** | **T2** | T1 | T1 |
| **W3 Session-End (≥0.8)** | T1 | T1 | T1 |
| **W3 Session-End (0.6-0.8)** | **T2** | T1 | T1 |
| **W4 Consolidation** | — | T1 | — |
| **W5 Emergence** | — | — | T1 |

---

## Part IV: Extraction

---

## 11. Extraction Mechanisms

> **TLDR**: Extraction 是 Ingestion 的实现机制。L1 (确定性, 4 rules) 已实现。L2 (LLM inline) 和 Session-End (W3) planned。Extraction 只产出 candidate，不写 store。

### 11.1 定位

Extraction 是 Lifecycle 中 Ingestion 阶段的**实现机制**，不是独立的 pipeline 起点。Extraction 的输出是 episodic/semantic candidate，进入 governance routing 后决定最终 memory type。

### 11.2 L1: Deterministic Heuristic（✅ implemented）

`agent/memory_suggestions.py` — `DeterministicSuggestionEngine`：

零 LLM、确定性、4 条规则：
1. `project_rule`："这个项目规定/禁止/必须…" → procedural (0.80)
2. `bug_fix_lesson`："上次就是因为/经验教训…" → episodic (0.70)
3. `architecture_decision`："我们选了/决定用…" → semantic (0.75)
4. `repeated_preference`："我喜欢/习惯…" × 3 in buffer → semantic (0.70)

5 层过滤：confidence ≥0.6 / sensitivity / injection / SHA256 dedup / frequency ≤3

输出路由：全量 T1 Confirmation（L1 无 T2 路径）。

覆盖面窄但确定性强，适合处理含关键词的显式模式。

### 11.3 L2: LLM Inline Extraction（🔲 planned）

在 task boundary / N≥5 turns / 用户显式触发时，调用 LLM 分析 conversation segment。

触发约束（不在每条 input 后调用）：
- 用户连续 N≥5 轮输入后
- 检测到 task boundary（"OK", "done", "下一步" 等）
- 用户显式触发

输出路由：
- episodic + confidence 0.6-0.8 → T2 auto-retain
- 其他 ≥0.8 → T1 confirmation
- <0.6 → T3 ignore

成本控制：Haiku 模型、session 内最多 5 次调用。

### 11.4 Session-End Extraction（🔲 planned）

Session 结束时批量扫描全部 messages（user + assistant + tool 摘要），LLM 提取所有值得保留的 episodic candidate。与已有 store dedup 后，按 confidence 走 T1 或 T2。

跨 session pending confirmation（T1 candidate 无法在当前 session 确认时）：
- 写入 `_pending_confirmation/` 目录
- 下次 session 启动时展示
- 7 天未确认的 pending candidate 自动丢弃

---

## Part V: Store & Recall

---

## 12. Filesystem-Native Store

> **TLDR**: Markdown + YAML frontmatter。source of truth = .md 文件。index.json 是派生数据。原子写入 (temp+rename)。不做向量/embedding。

### 12.1 存储原则

Filesystem-first 是 **deliberate constitutional choice**（Constitution P3），不是"缺 abstraction layer"的临时状态。设计意图：

- 用户可直接打开、阅读、编辑 .md 文件——这是架构的核心价值主张
- Markdown + YAML frontmatter 是唯一存储格式
- 文件系统是 source of truth
- Index（index.json）是派生数据，可随时从 .md 文件重建
- 原子写入：temp file + `os.rename()`
- 不做向量数据库、不做 embedding、不做语义搜索
- 单用户、单进程、local-first

**Backend Independence 立场**：Lifecycle 阶段的语义定义与 backend 无关（RFC §3.3）。如果未来引入新 backend（vector db / graph memory / cloud），lifecycle 阶段不需要修改——只需要在 Store 层新增 abstraction。但 backend abstraction 属于 **future extensibility concern**，不是 current architectural defect。当前 Phase 不主动引入 abstraction layer。引入新 backend 需要 Constitution P3 Amendment。

### 12.2 目录路由

```
{MEMORY_ROOT}/
├── index.json
├── episodic/
│   └── YYYY-MM-DD.md              # 按日期组织
├── semantic/
│   ├── user_preferences.md
│   ├── user_facts.md
│   ├── project_rules.md
│   └── project_decisions.md
├── procedural/
│   └── learned.md
└── _pending_confirmation/          # 跨 session pending
    └── pending_YYYY-MM-DD.md
```

### 12.3 扩展上限

- ≤200 active records：性能可接受
- 200-500：需要 consolidation
- >500：需要归档策略
- 索引重建 <10ms（50 records / 12 files 验证）

---

## 13. Recall & Snapshot

> **TLDR**: Recall 是 store → prompt 的唯一合法路径。不同类型 memory 有不同的 recall scope/ranking/recency/visibility 策略。详细 differentiation 见 Appendix F。

### 13.1 Recall API

`FilesystemMemoryStore.recall(scope, type, max_items, recency)` — 按 scope/type/recency 过滤和排序。

不同类型 memory 的 recall 策略有所不同：见 Appendix F。

### 13.2 MemorySnapshot — Runtime-Enforced Invariant

Snapshot 预算约束不是建议，是 **runtime-enforced invariant**。`build_memory_snapshot_from_store()` 必须实现硬截断：

**强制硬截断规则**：
- max 5 items total（procedural 不参与此计数，因其数量极少且全量注入）
- ≤500 chars per item（超过截断，加 `…` 标记）
- ≤2500 chars total（超过时从最低优先级 item 开始移除）
- exclude sensitive（sensitivity ≥ HIGH 不进 snapshot）
- 标注 `auto_retained` 来源为 `[自动记录]`
- T2 记录数 ≤2（防止 auto_retained 挤占 approved 空间）

**截断优先级**：当超过预算时，按以下顺序移除：
1. 最低 ranking 的 episodic（F.2 优先级最低）
2. 低 confidence 的 semantic
3. 最低 recency 的 episodic
4. 旧 semantic（低 recency）

**Recall → Snapshot 是 store → prompt 的唯一合法路径。**

### 13.3 T2 记录的 Snapshot 可见性

T2 auto-retained 记录在 snapshot 中必须：
- 标注 `[自动记录]` 前缀
- `source_type` 显示为 `agent_suggested`
- 排序低于 `approved` 记录
- 用户可通过 inspect 查看完整内容并 upgrade/delete

---

## Part VI: Implementation Mapping

---

## 14. Current Implementation Mapping

> **TLDR**: ~4,474 行代码，12 个模块。W1/W2 L1 已实现且稳定。W3 session-end 是 no-op。T2 路径不存在。G1-G6 结构性缺口 (~38 lines) 需在 Phase 5a 前修复。

### 14.1 状态标记

| 标记 | 含义 |
|:--:|------|
| ✅ | 已实现，生产可用 |
| 🟡 | 部分实现，有已知缺口 |
| 🔲 | 计划中（Phase 5-6），设计已确定 |
| 🔮 | 远期研究（Phase 7+），仅概念设计 |
| ❌ | 明确不做 |

### 14.2 模块映射

| 模块 | 文件 | 状态 | Lifecycle 阶段 | 缺口 |
|------|------|:--:|:---:|------|
| Memory Contracts | `agent/memory_contracts.py` | 🟡 | Foundation | `MemoryOperationIntent` 缺少 `memory_type`/`source_type` 字段 |
| Memory Policy | `agent/memory_policy.py` | ✅ | W1 Explicit Retain | — |
| L1 Suggestion Engine | `agent/memory_suggestions.py` | ✅ | W2 Inline Suggestion | — |
| LLM Extraction | `agent/memory_extraction.py` | 🟡 | W2/W3 | 模块存在，仅 CLI 手动调用，未接入 agent loop |
| Extraction Bridge | `agent/memory_extraction_bridge.py` | ✅ | Governance | bridge RULE 全量 T1，无 T2 路由 |
| Confirmation Flow | `agent/memory_confirmation.py` | ✅ | Governance T1 | — |
| InMemory Store | `agent/memory_store.py` | 🟡 | Store | `_record_from_intent` 硬编码 `memory_type="semantic"` |
| Filesystem Store | `agent/memory_fs_store.py` | 🟡 | Store | `_meta_from_intent` 和 `_apply_retain` fallback `"semantic"` |
| Memory Runtime | `agent/memory_runtime.py` | 🟡 | Governance | 无 T2 路径；`_pending_decision` 单 slot，重启丢失 |
| Operation Intent/Audit | `agent/memory_operations.py` | 🟡 | Store | 不传递 suggestion metadata |
| Snapshot Generator | `agent/memory_snapshot_generator.py` | 🟡 | Recall | 不标注 `auto_retained` 来源 |
| Session Memory | `agent/memory.py` | ❌ | W3 Session-End | `extract_memories_from_session()` 是 no-op |

### 14.3 Write Interface 实现状态

| Interface | 状态 | 实现位置 |
|-----------|:--:|------|
| W1 Explicit Retain | ✅ | `memory_policy.py` + `memory_runtime.py` |
| W2 Inline Suggestion (L1) | ✅ | `memory_suggestions.py` + `memory_runtime._try_suggestions()` |
| W2 Inline Suggestion (L2) | 🔲 | 设计完成，未实现 |
| W3 Session-End Extraction | 🔲 | `memory.py:290` — no-op，待重实现 |
| W4 Background Consolidation | 🔲 | 未实现 |
| W5 Emergence Detection | 🔮 | 概念设计，未实现 |

### 14.4 Lifecycle 阶段实现状态

| 阶段 | 状态 | 说明 |
|------|:--:|------|
| Ingestion | 🟡 | W1/W2 done, W3/W4/W5 planned |
| Episodic | 🔲 | T2 auto-retain 未实现 |
| Consolidation | 🔲 | 未实现 |
| Semantic | 🟡 | W1 explicit retain 可产出，无 consolidation 来源 |
| Emergence | 🔮 | 概念设计 |
| Procedural | 🟡 | W1 explicit retain 可产出，无 emergence 来源 |
| Recall | ✅ | Recall API + Snapshot governance |

### 14.5 结构性缺口（Phase 4 遗留，应优先修复）

以下 G1-G6 是 **known implementation gap**，已在两轮独立架构审计中确认。核心问题：**metadata continuity** — `memory_type`、`source_type`、`approval_status` 在 pipeline 传递中丢失，导致各模块 fallback 硬编码，违背 governance 集中化设计（Appendix G.7）。

| # | Gap | 位置 | 改动量 | 阻断 Phase 5? |
|---|-----|------|:--:|:--:|
| G1 | `MemoryOperationIntent` 无 `memory_type`/`source_type` | `memory_contracts.py` | +5 行 | 是 |
| G2 | `build_memory_operation_intent` 不传 metadata | `memory_operations.py` | +8 行 | 是 |
| G3 | `_meta_from_intent` 硬编码 fallback `"semantic"` | `memory_fs_store.py` | ~5 行 | 是 |
| G4 | `_apply_retain` topic route fallback | `memory_fs_store.py` | ~5 行 | 是 |
| G5 | `_record_from_intent` 硬编码 fallback | `memory_store.py` | ~5 行 | 是 |
| G6 | Snapshot 不标注 auto_retained | `memory_snapshot_generator.py` | +10 行 | 否 |

**Metadata Continuity 作为 Governance Invariant**：

```
memory_type / source_type / approval_status 禁止在 pipeline 中被重新推断。

Governance routing 决定的类型必须原样传递到 store 写入。
Store 层不得 fallback 硬编码类型。
Snapshot 层不得丢失 auto_retained 标记。

违反此 invariant 的后果：
  Runtime 判断 T2 episodic → intent 不携带 memory_type →
  store fallback "semantic" → T2 episodic 被静默写成 semantic。
  这直接违背 T2 宪法锁定（§10.2: T2 仅限 episodic）。
```

**总计：~38 行增量修复。**修复后需通过 Appendix H 的 metadata continuity assertions 验证。

### 14.6 Runtime Growth Constraint

`memory_runtime.py` 当前 551 行（Phase 4 baseline），承担 W1/W2 governance + confirmation + snapshot 协调。在当前阶段这是可接受的——集中 orchestration 比过早拆分更简单。

**允许的职责范围**（Phase 4-5a）：
- W1 explicit retain routing
- W2 L1 inline suggestion routing
- T1 confirmation coordination
- Snapshot generation triggering

**Growth Boundary**：当以下任一条件触发时，应自然拆分而非继续膨胀：

| 触发条件 | 拆分动作 |
|---------|---------|
| 模块超过 800 行 | 拆分 governance routing 为 `memory_governance.py`（T1/T2/T3 决策逻辑） |
| 新增 W3 session-end extraction 协调 | governance 已拆分，runtime 仅做编排 |
| 新增 T2 auto-retain 路径 | 必须拆分——T2 逻辑集中在一处，不可混入 W1 路径 |
| 新增 cross-session pending confirmation 管理 | 创建独立 `memory_pending.py`，不放入 runtime |

**拆分原则**：
- 不提前抽象——在代码量/职责增长到触发条件时再拆，不在触发前做
- 拆出的模块有单一职责：`memory_governance.py` 只做 T1/T2/T3 routing，不 import store；`memory_pending.py` 只管理 pending confirmation 生命周期
- Runtime 拆分后保留为薄 orchestrator：编排 governance + store + snapshot，不持有决策逻辑

**Phase 5a 建议**：G1-G6 修复后，T2 路径实现时，如果 runtime 行数仍 <800 且 T2 逻辑 <50 行，可暂不拆分。但如果 T2 逻辑开始与 W1 路径共享 mutation 状态（如共享 pending queue），必须立即拆分。

---

## 15. Phase Boundaries

> **TLDR**: Phase 5a (W3+T2) → Phase 5b (L2 inline) → Phase 6 (Consolidation) → Phase 7 (Emergence)。每个 phase 依赖前一 phase 的输出。

### 15.1 Phase 4 — 当前基线（✅）

已完成：Explicit retain/forget、L1 heuristic suggestion、Two-phase T1 confirmation、Filesystem-native store（原子写入、index、recall）、MemorySnapshot governance、Sensitivity/prompt-injection 过滤、LLM extraction sandbox、Extraction → review bridge。

待修复：G1-G6 结构性缺口（~38 行）。

### 15.2 Phase 5a — Session-End Extraction + Episodic T2（🔲）

**Lifecycle 目标**：Episodic Memory 阶段落地。

- G1-G6 修复
- `extract_memories_from_session()` 重实现（W3）
- T2 governed auto-retain 路径（仅 episodic）
- `approval_status="auto_retained"` 写入 + recall 可见
- Pending confirmation 跨 session 传递
- 单 session T2 上限 3 条

### 15.3 Phase 5b — L2 LLM Inline Extraction（🔲）

**Lifecycle 目标**：增强 W2 Inline Suggestion。

- L2 LLM 在 task boundary 触发
- 成本控制（Haiku，session 内最多 5 次）
- L2 输出路由（T1/T2/T3 按 confidence 分流）

### 15.4 Phase 6 — Consolidation（🔲）

**Lifecycle 目标**：Consolidation 阶段落地。

- Episodic → Semantic 沉淀引擎（W4）
- 跨 session 模式检测
- Semantic candidate 生成 + episodic evidence 链
- T1 adoption review

### 15.5 Phase 7 — Emergence（🔮）

**Lifecycle 目标**：Emergence 阶段探索。

- Correction pattern 追踪
- Procedural candidate 自动检测（W5）
- 永远是 T1，永不可 silent
- 依赖 Phase 5+6 完成 + active records >50

### 15.6 故意延后的设计

以下设计在当前架构中预留位置，但不进入任何 phase 的 scope：

| 设计 | 延后理由 |
|------|---------|
| Decay / TTL | 依赖 active records >50 |
| Archival | 依赖 active records >200 |
| Automatic Proceduralization | 行为安全性要求极高，可能永远只需 emergence candidate + T1 |
| External MemoryProvider | 明确不做（宪法级 local-first） |
| Multi-user / Distributed | 明确不做（宪法级 single-user） |
| Vector DB / Embedding / Semantic Search | 明确不做（宪法级 filesystem-native） |

---

## Part VII: Document Governance

---

## 16. 文档治理

### 16.1 Canonical RFC 取代关系

本 v2.1 取代以下所有文档：

| 历史文档 | 处理 | 理由 |
|------|:--:|------|
| `docs/rfc/MEMORY_CANONICAL_RFC.md` (v2.0, v1.0) | **被本 v2.1 取代** | 增加 navigability + operational semantics |
| `docs/MEMORY_CONSTITUTION.md` | **归档** → `docs/rfc/archived/` | 宪法原则被纳入 §1 |
| `docs/PROACTIVE_MEMORY_ARCHITECTURE.md` | **归档** → `docs/rfc/archived/` | L1/L2/L3 设计被纳入 §11 和 §6-8 |
| `docs/MEMORY_NEXT_STAGE_ARCHITECTURE.md` | **归档** → `docs/rfc/archived/` | Phase 2 历史规划，External Provider 设计明确不做 |

### 16.2 当前 Memory 文档体系

```
docs/rfc/MEMORY_CANONICAL_RFC.md          ← ★ 唯一设计真相
docs/DOGFOODING_GUIDE.md                  ← 操作/使用手册
docs/ROADMAP.md                           ← 阶段路线图
docs/review/MEMORY_PHASE5_DOGFOOD_001.md  ← 历史审计记录
docs/rfc/archived/                        ← 归档设计文档（仅供历史参考）
  ├── MEMORY_CONSTITUTION.md
  ├── PROACTIVE_MEMORY_ARCHITECTURE.md
  ├── MEMORY_NEXT_STAGE_ARCHITECTURE.md
  ├── MEMORY_LIFECYCLE.md
  ├── MEMORY_TAXONOMY.md
  ├── RFC_MEMORY_GOVERNANCE_AND_EXTRACTION.md
  ├── RFC_CONVERGENCE_AUDIT.md
  └── MEMORY_DOGFOODING_STAGE3.md
```

### 16.3 文档规则

- 设计 → `docs/rfc/MEMORY_CANONICAL_RFC.md`（唯一）
- 路线图 → `docs/ROADMAP.md`
- 操作手册 → `docs/DOGFOODING_GUIDE.md`
- 审计记录 → `docs/review/*.md`
- 历史/归档 → `docs/rfc/archived/*.md`

**不允许**创建新的平级设计文档。任何新增设计内容以 section 追加到本 RFC 或引用本 RFC。

### 16.4 后续 RFC 规则

- 任何新增 Memory RFC 必须引用本文档
- 任何与本文档冲突的 RFC 必须先 amendment 本文档
- Amendment §1 或 §3 需要 explicit justification
- Amendment Appendix G 或 Appendix H 需要 architecture audit 确认
- 不再新增独立 Memory RFC 文件
- 新增 architecture guardrail 追加到 Appendix H

---

## Appendix A: T2 决议记录

T2 Governed Auto-Retain 以宪法级锁定为条件被接受。

**理由**：
1. Phase 4 基础设施使 governed auto-retain 与 "silent auto-write" 有本质区别（可见、可逆、有范围限制）
2. Episodic memory 不直接约束行为，T2 仅适用于最低风险类型
3. P8 从 "永不 auto-write" 精炼为 "No ungoverned auto-write"，保留了原则精神
4. 宪法级锁定（§10.2）防止 T2 扩展

**如果 T2 被否决**：回退到全部 T1 模型。Session-end extraction 产生的所有 candidate 进入 pending confirmation。

---

## Appendix B: 已保留的现有能力分类

以下分类确保 rewrite 不会误删已有能力：

### A. 已实现且应保留（keep as-is）

| 能力 | 代码位置 | 新 RFC 中的归属 |
|------|---------|:---:|
| Explicit retain/forget | `memory_policy.py` | §4.3 W1 |
| L1 heuristic suggestion (4 rules) | `memory_suggestions.py` | §11.2 |
| Two-phase T1 confirmation (5 choices) | `memory_confirmation.py` | §10 |
| Filesystem-native persistence + atomic write | `memory_fs_store.py` | §12 |
| Recall API | `memory_fs_store.py:recall` | §13 |
| MemorySnapshot governance | `memory_snapshot_generator.py` | §13.2 |
| Sensitivity + prompt injection filtering | `memory_policy.py` | §10 |
| SHA256 dedup | `memory_suggestions.py` | §10 |
| LLM extraction sandbox | `memory_extraction.py` | §11.3 |
| Extraction → review bridge | `memory_extraction_bridge.py` | §11 |

### B. 已实现但需 reposition

| 当前定位 | 问题 | 新定位 |
|---------|------|-------|
| 三种 memory_type 独立创建 | 无沉淀关系，episodic/semantic/procedural 平等产出 | episodic 是主要入口（§5），semantic 主要来自 consolidation（§6-7），procedural 主要来自 emergence（§8-9） |
| T1-only governance | 所有 candidate 必须确认，episodic 骚扰用户 | +T2 for episodic（§10.2），保留 T1 for procedural/semantic |
| `memory extract` CLI 作为主要入口 | manual trigger 模式，不是自动 lifecycle | CLI 保留为调试/手动入口，主路径是 W2/W3 automatic |
| `memory_runtime.py` 大一统角色 | 混合了 Ingestion + Governance + Store 协调 | 重新理解为 lifecycle 多阶段协调器 |

### C. 未实现但属于 lifecycle 缺口

| 缺口 | 归属 | Phase |
|------|:---:|:---:|
| Session-end extraction (W3) | §11.4 | Phase 5a |
| T2 auto-retain 路径 | §10.2 | Phase 5a |
| L2 LLM inline extraction | §11.3 | Phase 5b |
| Consolidation engine (W4) | §6 | Phase 6 |
| Emergence detection (W5) | §8 | Phase 7 |
| Pending confirmation 跨 session | §11.4 | Phase 5a |

### D. 旧设计中真正删除

| 删除内容 | 来源文档 | 理由 |
|---------|---------|------|
| External MemoryProvider 设计 | `MEMORY_NEXT_STAGE_ARCHITECTURE.md` §3 | 宪法级 local-first，明确不做 |
| "永不 auto-write" 绝对立场 | `MEMORY_CONSTITUTION.md` §2.3 | 精炼为 P8 "No ungoverned auto-write"，T2 在宪法锁定下允许 |
| 所有 memory type 平等独立创建 | v1.0 RFC 的隐含假设 | 替换为 lifecycle 沉淀关系（§3） |
| Phase 2 历史 prompt | `MEMORY_NEXT_STAGE_ARCHITECTURE.md` §10 | 历史记录，无设计价值 |

---

## Appendix C: Episodic Record Semantics

> **Stable Anchor**: `RFC App C`
> **定位**: 定义 episodic record 的操作语义 shape，不是最终 storage schema。实现时具体字段可调整，但以下语义维度必须覆盖。

### C.1 必须语义字段

| 字段 | 语义 | 必要性 | 示例 |
|------|------|:--:|------|
| `timestamp` | 事件发生的时间锚点 | 必须 | `2026-05-12T14:30:00Z` |
| `session_id` | 事件发生的 session 标识 | 必须 | `sess_abc123` |
| `event_summary` | 事件的叙事性摘要（"那次发生了什么"） | 必须 | "PG 迁移因缺少复合索引导致全表锁，迁移超时 40 分钟" |
| `evidence` | 支撑此事件的原始对话引用 | 必须 | "user: 上次 4 月 28 日的 PG 迁移事故你还记得吗？全表 UPDATE 没加索引..." |
| `causal_chain` | 因果结构（问题 → 尝试 → 结果） | 推荐 | "缺少复合索引 → 全表 UPDATE → 全表锁 → 迁移超时 40 分钟" |
| `correction_signal` | 用户是否在此事件中纠正了 Agent 行为 | 推荐 | `true` / `false` |
| `source_type` | 进入系统的 Write Interface | 必须 | `agent_suggested` / `session_end_extraction` |
| `confidence` | 提取置信度 | 必须 | `0.75` |
| `approval_status` | Governance 结果 | 必须 | `auto_retained` / `approved` |

### C.2 可选语义字段

| 字段 | 语义 | 何时填充 |
|------|------|---------|
| `tags` | 主题标签（便于 consolidation 分组） | W3 extraction 时由 LLM 生成 |
| `related_record_ids` | 与此事件相关的已有 episodic ID | Consolidation 时回溯填充 |
| `consolidation_status` | 是否已被 consolidation 处理 | Consolidation 完成后标记 |
| `correction_type` | 纠正类型（如果 `correction_signal=true`） | W3 extraction 时由 LLM 分类 |

### C.3 Episodic 与其他类型的区别

| 维度 | Episodic | Semantic | Procedural |
|------|:--:|:--:|:--:|
| 时间锚点 | 必须有（具体时刻） | 可有（时间段或缺失） | 通常无（行为约束无时间性） |
| 叙事结构 | 必须有（因果链） | 通常无（事实性陈述） | 通常无（规则性陈述） |
| 与行为的关系 | 间接（precedent reference） | 间接（prompt 可见偏好） | 直接（行为约束） |
| 独特性 | 高（每个事件独特） | 低（抽象自多个事件） | 极低（跨事件的行为法则） |

---

## Appendix D: Consolidation Semantics

> **Stable Anchor**: `RFC App D`
> **定位**: 定义 episodic → semantic 沉淀的操作语义。不是实现算法，而是 consolidation 必须满足的语义条件。

### D.1 沉淀的必要条件

一条 semantic candidate 要从多条 episodic 中沉淀出来，必须满足：

1. **Repetition（重复）**: 至少 N 条 episodic 涉及同一主题/偏好/模式（N ≥ 3，具体值由实现校准）
2. **Stability（稳定）**: 模式在不同 session/时间点保持一致，无矛盾 episodic
3. **Evidence Chain（证据链）**: semantic candidate 必须引用所有支撑它的 episodic record ID
4. **Confidence Accumulation（置信度累积）**: semantic confidence = f(episodic 数量, episodic 间一致性, 时间跨度)

### D.2 置信度累积模型（设计值）

```
semantic_confidence = base_confidence
  × repetition_factor（episodic 数量越多越高，cap at 0.9）
  × consistency_factor（episodic 间有矛盾 → 降低）
  × recency_factor（最近的事件权重更高）

其中 base_confidence = mean(支撑 episodic 的 confidence)
```

### D.3 矛盾处理

如果多条 episodic 之间存在矛盾（如 "用户喜欢 pytest" vs "用户某次批评 pytest"）：

| 矛盾类型 | 处理 |
|---------|------|
| **时间演进**（早期 dislike → 后期 like） | 以最近 episodic 为准，标注 "preference evolved" |
| **上下文依赖**（"写 API 测试用 pytest, 写 CLI 测试用 unittest"） | 不合并为一条 semantic，保留为两条 context-dependent semantic |
| **真实矛盾**（无法调和的冲突） | 降低 confidence，标记为 "needs clarification"，propose 时展示矛盾让用户裁决 |

### D.4 Consolidation 不做的

- 不修改源 episodic（只读）
- 不删除源 episodic（保留 evidence trail）
- 不生成 procedural candidate
- 不自动 adopt semantic（必须 T1 human review）
- 不在 session 中途触发（仅 session 边界或显式触发）

### D.5 Consolidation vs Emergence 的边界

| 维度 | Consolidation (→ Semantic) | Emergence (→ Procedural) |
|------|:---:|:---:|
| 输入 | 多条 episodic | episodic + semantic + correction pattern |
| 输出类型 | "用户喜欢/偏好/知道 X" | "Agent 以后必须/禁止做 Y" |
| 行为影响 | 间接（prompt 中可见偏好） | 直接（行为约束） |
| Governance | T1 human review | T1 强制 |
| 自动化程度 | candidate generation silent | candidate generation silent |

---

## Appendix E: Procedural Mutation Boundary

> **Stable Anchor**: `RFC App E`
> **定位**: 定义 procedural memory 允许和不允许影响的范围。这是防止 procedural memory 失控的硬性边界。

### E.1 允许影响的范围

Procedural memory 可以影响以下 Agent 行为维度：

| 维度 | 示例 | 影响方式 |
|------|------|---------|
| **Planning Preference** | "先分析再动手"、"先读代码再问问题" | snapshot 注入 prompt，Agent 在 plan 阶段参考 |
| **Interaction Preference** | "用中文解释，代码保留英文"、"不要主动 commit" | snapshot 注入 prompt，Agent 在交互时参考 |
| **Review Preference** | "重构前先跑测试"、"改 checkpoint 前检查边界" | snapshot 注入 prompt，Agent 在执行前参考 |
| **Communication Style** | "回答要简洁，不要冗长"、"不要用 emoji" | snapshot 注入 prompt，Agent 在生成回复时参考 |
| **Error Recovery Pattern** | "先查日志，找到根因，最小修复" | snapshot 注入 prompt，Agent 在遇到错误时参考 |

### E.2 禁止影响的范围

Procedural memory **绝对不允许**影响以下维度：

| 维度 | 理由 | 替代方案 |
|------|------|---------|
| **Arbitrary System Prompt Mutation** | 安全红线：procedural 不应有任意修改 system prompt 的能力 | Skill / Config 系统负责 |
| **Unrestricted Runtime Mutation** | 安全红线：procedural 不应绕过 runtime governance | 所有行为变更经 snapshot 注入，不直接修改 runtime |
| **Tool Execution Policy** | 工具安全策略不属于 memory 范畴 | Tool Registry / Safety Config |
| **Auth/ Permission Changes** | 安全红线 | 用户显式配置 |
| **Model Selection / Provider Config** | 基础设施配置不属于 memory | Config 系统 |
| **Other Agents' Behavior** | 跨 agent 行为约束不属于单个 agent 的 memory | 共享 Skill / Constitution |

### E.3 Procedural 生效机制

```
Procedural Memory Record (approved)
  → MemorySnapshot（governed view）
  → System Prompt Injection（经 snapshot generator 格式化为 prompt 片段）
  → Agent 在决策时参考（不是强制执行，是 soft constraint）
```

**关键约束**: Procedural memory 以 **soft constraint** 方式影响行为——Agent 在 prompt 中看到行为约束，自行决定如何遵守。不存在 "强制执行 procedural" 的代码路径。这让用户始终可以通过新的交互覆盖 procedural 的影响。

### E.4 Procedural vs Skill 的边界

| 维度 | Procedural Memory | Skill |
|------|:---:|------|
| 来源 | 交互中涌现 | 预设/配置 |
| 稳定性 | 随交互演化 | 相对固定 |
| 表达形式 | "以后应该/禁止..." | "执行 X 时需要做 Y" |
| 生效方式 | soft constraint (prompt) | hard constraint 或 tool call |
| 修改方式 | 用户确认 (T1) | 配置更新 |

**一句话边界**: 如果一条行为规则可以在 Agent 启动前写好 → Skill。如果只能从真实交互中学习 → Procedural Memory。

---

## Appendix F: Recall Semantics

> **Stable Anchor**: `RFC App F`
> **定位**: 定义不同类型 memory 在 recall 时的差异化策略。Recall 是只读操作，不修改 store。

### F.1 Recall Scope 差异化

| Memory Type | 默认 Scope | 理由 |
|:---|:--:|------|
| Episodic | `user` | 事件是 user-specific 的（用户自己的经历） |
| Semantic — user_preference | `user` | 用户偏好是 user-specific |
| Semantic — project_rule | `project` | 项目规则跨 session 共享 |
| Semantic — repo_convention | `repo` | 代码规范与 repo 绑定 |
| Procedural | `user` | 行为约束来自用户纠正，user-specific |

### F.2 Recall Ranking 差异化

不同类型在 snapshot 中的排序优先级：

| Memory Type | 默认优先级 | 理由 |
|:---|:--:|------|
| Procedural | **最高** | 行为约束必须在 prompt 中最显眼 |
| Semantic — user_preference | 高 | 用户偏好直接影响交互质量 |
| Semantic — project_rule/decision | 中 | 项目上下文 |
| Episodic | **最低** | 仅 precedent reference，不应挤占行为约束和偏好的空间 |

### F.3 Recall Recency 差异化

| Memory Type | Recency 策略 | 理由 |
|:---|------|------|
| Episodic | 强 recency bias（最近 30 天优先，超过 90 天降权） | 旧事件的行为参考价值递减 |
| Semantic | 弱 recency bias（最近确认时间优先，但旧偏好仍保留） | 偏好可能长期稳定 |
| Procedural | 无 recency bias（按 adoption 时间排序，但不降权） | 行为约束不应因时间久而失效 |

### F.4 Recall Governance Visibility

| Record 类型 | Snapshot 中标注 | 用户可见 | 可删除 | 可 upgrade |
|:---|:--:|:--:|:--:|:--:|
| `approved` (T1) | 正常显示 | ✅ | ✅ | N/A |
| `auto_retained` (T2) | `[自动记录]` 前缀，低优先级 | ✅ | ✅ | ✅ (→ approved) |
| `session_only` | 仅当前 session | ✅ | ✅ (session 结束自动) | ❌ |
| `pending` | 不进入 snapshot | 仅 `memory status` | ✅ | N/A |
| `rejected` | 不进入 snapshot，不进 store | ❌ | N/A | N/A |

### F.5 Snapshot Composition（最终注入 prompt 的组合）

```
[Memory Snapshot — 当前生效的长期记忆]

## 行为约束 (Procedural)
- [P1] 先查日志和 checkpoint，找到根因，再最小修复
- [P2] 用中文解释，代码/命令/日志保留英文

## 偏好与知识 (Semantic)
- 用户偏好 pytest
- 项目使用 PostgreSQL
- 用户是数据工程师

## 近期相关经历 (Episodic)
- [自动记录] 2026-05-11: PG 迁移因缺索引超时
- [自动记录] 2026-05-10: 重构 auth 模块引入循环依赖
```

**组合规则**:
1. Procedural 始终在最前面（最高行为影响力）
2. Semantic 在中间（context）
3. Episodic 在最后（precedent，不超过 2 条）
4. 总条数 ≤5，总字符数 ≤2500
5. `auto_retained` 记录标注 `[自动记录]`
6. T2 记录数 ≤2（防止 auto_retained 挤占 approved 空间）

---

## Appendix G: Implementation Constraints（SDD-Style）

> **Stable Anchor**: `RFC App G`
> **定位**: 所有 Phase 实现必须遵守的架构约束。这些约束在 code review 和 architecture boundary test 中强制执行。

### G.1 Extraction ≠ Persistence

```
提取器只产出 candidate。
Candidate 不进 store。
只有 governance routing 后的 resolved decision 才能写入 store。
```

任何 extraction 函数（L1/L2/W3）的返回值类型必须是 candidate list，不能是 `MemoryRecord` 或 `apply_operation_intent` 调用。

### G.2 Lifecycle Stages 不允许互相越权

```
Episodic 不产出 semantic candidate（那是 consolidation 的职责）。
Consolidation 不产出 procedural candidate（那是 emergence 的职责）。
Recall 不修改 store（那是 persistence 的职责）。
```

每个 lifecycle 阶段的输出类型是锁定的。交叉输出需要 explicit RFC amendment。

### G.3 Filesystem Remains Source of Truth

```
index.json 是派生数据。
任何 store 操作必须先写 .md 文件，再更新 index。
index 损坏时可从 .md 文件完全重建。
```

### G.4 Procedural 永远 Explicit Governance

```
procedural 不可走 T2。
procedural 不可 silent retain。
procedural 不可从单次 interaction 直接生成。
procedural candidate adoption 必须经用户显式确认。
```

### G.5 Consolidation 不允许直接 Behavioral Mutation

```
Consolidation 产出 semantic candidate，不产出 procedural candidate。
Consolidation 不修改 Agent 的行为逻辑。
Consolidation 不自动删除源 episodic。
```

### G.6 Recall 不负责 Consolidation

```
Recall 是只读操作。
Recall 不做跨 record 的模式分析。
Recall 不做 "related memories" 的自动聚合。
```

### G.7 Governance 不允许散落到各模块

```
Governance routing (T1/T2/T3) 的决策逻辑集中在 memory_runtime。
memory_fs_store 不判断 "这个该不该 auto_retain"。
memory_extraction 不判断 "这个需不需要确认"。
```

### G.8 Session-End 与 Inline 隔离

```
W2 inline 在 evaluate_user_text 路径中触发。
W3 session-end 在 finalize_session 路径中触发。
两者不共享触发逻辑，不共享 pending 队列。
```

### G.9 所有自动路径必须可逆

```
T2 auto_retained 记录：用户可删除、可 upgrade 到 approved。
Consolidation candidate：用户可拒绝。
Emergence candidate：用户可拒绝。
```

---

## Appendix H: Automated Architecture Guardrails（Fitness Functions）

> **Stable Anchor**: `RFC App H`
> **定位**: 定义可通过自动化测试强制执行的架构边界和 invariant。本附录的内容在两轮独立架构审计（2026-05-12）中确认，从"讨论"升级为"canonical constraint"。
>
> **Amendment 规则**: 修改本附录需要 architecture audit 确认。

### H.1 Import Boundary Guardrails

以下 import 关系应作为 CI 中的 architecture test 强制执行：

| # | Guardrail | 理由 | Phase |
|---|----------|------|:--:|
| **IB1** | `memory_fs_store` 不 import `memory_policy` | Store 不依赖 Policy——store 是数据层，policy 是 ingestion 层 | 4 |
| **IB2** | `memory_extraction` 不 import `memory_fs_store` | Extraction 不依赖 Store——提取器只产出 candidate（Appendix G.1） | 4 |
| **IB3** | `memory_snapshot_generator` 不 import `memory_runtime` | Snapshot 不依赖 Runtime——snapshot 是 recall 层，只读 | 4 |
| **IB4** | `memory_contracts` 不被任何运行时逻辑反向依赖 | Contracts 是 foundation，只能是单向依赖 | 4 |
| **IB5** | `memory_status` / `memory_inspect` 不 import `memory_runtime` | UX 层不依赖 Governance 层（见 UX Integration Plan） | 4 |
| **IB6** | `memory_conflict` 不 import `memory_runtime` / `memory_governance` | Conflict detection 是 advisory UX，不是 governance | 4 |

**实施方式**: `tests/test_architecture_boundaries.py`，使用 `importlib` + `sys.modules` 检查。不是静态分析工具（如 `import-linter`），是 pytest 兼容的简单检查。

### H.2 Governance Invariant Guardrails

以下 governance invariant 必须作为自动化测试：

| # | Guardrail | 断言 | Phase |
|---|----------|------|:--:|
| **GI1** | T2 仅限 episodic | `assert all(r.memory_type == "episodic" for r in t2_records)` | 5a |
| **GI2** | Procedural 永远不走 T2 | `assert all(r.approval_status != "auto_retained" for r in procedural_records)` | 4+ |
| **GI3** | T2 confidence 必须在 [0.6, 0.8) | `assert 0.6 <= r.confidence < 0.8 for r in t2_records` | 5a |
| **GI4** | T2 sensitivity ≤ MEDIUM | `assert r.sensitivity <= SensitivityLevel.MEDIUM for r in t2_records` | 5a |
| **GI5** | 单 session T2 上限 3 条 | `assert len(session_t2_records) <= 3` | 5a |
| **GI6** | 总 suggestion 上限 5 条/session | `assert len(session_suggestions) <= 5` | 5a |
| **GI7** | Sensitivity ≥ HIGH 永远不 T2 | `assert not any(r.sensitivity >= HIGH and r.approval_status == "auto_retained")` | 4+ |

### H.3 Metadata Continuity Guardrails

验证 metadata 在 pipeline 中不丢失：

| # | Guardrail | 断言 | Phase |
|---|----------|------|:--:|
| **MC1** | `MemoryOperationIntent` 必须携带 `memory_type` | `assert intent.memory_type is not None and intent.memory_type != "semantic"` (除非显式设置) | 4 |
| **MC2** | `build_memory_operation_intent` 必须传递 `source_type` | `assert intent.source_type is not None` | 4 |
| **MC3** | Store 写入的 `memory_type` 必须与 intent 一致 | `assert stored_record.memory_type == intent.memory_type` | 4 |
| **MC4** | `_meta_from_intent` 不得 fallback 硬编码 `"semantic"` | `assert "_meta_from_intent" not in source or "semantic" not in source` — 应使用 intent 提供的值 | 4 |
| **MC5** | Snapshot 中 `auto_retained` 记录必须标注 `[自动记录]` | `assert "[自动记录]" in snapshot_text for auto_retained records` | 4 |
| **MC6** | `_record_from_intent` 不得 fallback 硬编码 `"semantic"` | 同 MC4，对 InMemory store | 4 |

### H.4 Snapshot Budget Enforcement Guardrails

验证 snapshot 硬截断：

| # | Guardrail | 断言 | Phase |
|---|----------|------|:--:|
| **SB1** | Snapshot items ≤5（不含 procedural 全量注入） | `assert len(snapshot.non_procedural_items) <= 5` | 4 |
| **SB2** | Per-item chars ≤500 | `assert all(len(item.text) <= 500 for item in snapshot.items)` | 4 |
| **SB3** | Total chars ≤2500 | `assert sum(len(item.text) for item in snapshot.items) <= 2500` | 4 |
| **SB4** | T2 items in snapshot ≤2 | `assert sum(1 for item in snapshot.items if item.approval_status == "auto_retained") <= 2` | 5a |
| **SB5** | Procedural 不参与截断 | `assert all(item.memory_type == "procedural" for item in snapshot.procedural_items)` — procedural 全量注入 | 4 |
| **SB6** | Sensitivity ≥ HIGH 不进 snapshot | `assert not any(item.sensitivity >= HIGH for item in snapshot.items)` | 4 |

### H.5 Lifecycle Stage Boundary Guardrails

验证 lifecycle 阶段不越权（Appendix G.2）：

| # | Guardrail | 断言 | Phase |
|---|----------|------|:--:|
| **LB1** | Episodic 不产出 semantic candidate | Episodic extraction 输出不得包含 `proposed_type="semantic"` 或 `"procedural"` | 5a |
| **LB2** | Consolidation 不产出 procedural candidate | Consolidation 输出类型只能是 `"semantic"` | 6 |
| **LB3** | Recall 不调用 mutation operations | `recall()` 路径中不得出现 `_apply_retain` / `_apply_delete` / `write_memory_section` | 4 |

### H.6 Conflict Detection Boundary Guardrails

验证 conflict detection 不越权为 governance：

| # | Guardrail | 断言 | Phase |
|---|----------|------|:--:|
| **CD1** | `check_conflicts()` 不返回 action/blocking 字段 | `assert "action" not in conflict and "should_block" not in conflict` | 4 |
| **CD2** | Conflict warning 不自动拒绝 proposal | Review layer 中 conflict 仅 print，不调用 `resolve_and_store` 的 reject 路径 | 4 |

### H.7 Guardrail 执行策略

- **CI 强制执行**: IB1-IB6, GI2, GI7, MC3-MC4, SB1-SB6, CD1
- **Phase 进入 gate**: GI1, GI3-GI6 (Phase 5a 前), LB1-LB3 (对应 Phase 前)
- **Dogfood 辅助验证**: GI5-GI6 (数量上限在实际使用中观察), SB4
- **不替代 human review**: GI2 (procedural never T2) 即使有自动化测试，Constitution P1/P8 仍需 human review

### H.8 与 Appendix G 的关系

- Appendix G: Implementation Constraints — **语义级约束**，定义 "什么能做、什么不能做"。在 code review 和 architecture review 中引用。
- Appendix H: Automated Guardrails — **可自动化验证的约束**，定义 "哪些边界可以通过代码测试检查"。是 Appendix G 的自动化执行子集。

Appendix H 是 Appendix G 的补充，不是替代。G 中不可自动化的约束（如 "Consolidation 不修改 Agent 行为逻辑"）仍依赖 architecture review。

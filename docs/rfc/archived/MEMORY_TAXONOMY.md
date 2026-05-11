# Archived RFC

This RFC has been absorbed into:
docs/rfc/MEMORY_CANONICAL_RFC.md

Do not use this document as the canonical memory design source.

---

# Memory Taxonomy

**创建日期**: 2026-05-11
**性质**: Architecture RFC — 定义 my-first-agent 的 Memory 类型及边界
**状态**: Draft v2 — Convergence Pass 后收缩
**上级文档**: `docs/MEMORY_CONSTITUTION.md`

---

## 0. Groundedness 总览

| Memory 类型 | 状态 | 代码证据 |
|-------------|------|----------|
| Working | ✅ implemented | `conversation.messages` |
| Session | ✅ implemented | `SESSION_ONLY` choice + `InMemoryMemoryStore` |
| Semantic | ✅ implemented | explicit retain + heuristic suggestion |
| Episodic | 🟡 partial | `bug_fix_lesson` heuristic only |
| Procedural | 🟡 partial | `project_rule` heuristic only，范围待收缩 |

**图例**：✅ implemented | 🟡 partial | ❌ speculative | 🔮 research

---

## 1. Working Memory（工作记忆）

> 当前 turn 内正在处理的、尚未持久化的临时信息。

| 维度 | 值 |
|------|-----|
| **Duration** | 单一 turn |
| **Storage** | 不持久化 |
| **Governance** | 不需要 confirmation |
| **当前映射** | `conversation.messages` |

Working memory 不是 memory 系统的管理对象，属于 context builder 范畴。

---

## 2. Session Memory（会话记忆）

> 当前 session 内积累的、跨 turn 但随 session 结束而消失的短期信息。

| 维度 | 值 |
|------|-----|
| **Duration** | 当前 session |
| **Storage** | in-memory（session 结束即丢弃，**不持久化**） |
| **Governance** | `SESSION_ONLY` choice |

Session memory 本身是 runtime-scoped — session 结束时即消失，不会自动成为 long-term memory。

**与长期记忆的关系**（🔮 research）：Session-derived artifacts（如 session summaries、interaction traces、aggregate signals）是 future consolidation research 的可能输入。但这些 artifacts 是与 session memory 不同的概念——它们是在 session 结束后**显式提取和存储**的派生数据，不是 session memory 的自动持久化。Session memory 的 ephemeral 性质不因其可能作为 consolidation 输入而改变。

---

## 3. Semantic Memory（语义记忆）

> 稳定的、长期的事实、偏好、知识——"Agent 知道什么"。

| 维度 | 值 |
|------|-----|
| **Duration** | 长期（months+） |
| **Scope** | user / project / repo |
| **Governance** | 写入需 confirmation |
| **Confidence min** | ≥0.8 |
| **当前状态** | ✅ implemented |

**子类型**：

| 子类型 | 示例 |
|--------|------|
| user_preference | "喜欢 pytest", "偏好中文解释架构" |
| user_fact | "用户是数据工程师", "用户用 macOS" |
| project_rule | "所有 API 必须 version prefix" |
| project_decision | "选了 FastAPI 而不是 Flask" |
| repo_convention | "用 black 格式化" |

**行为影响**：Semantic memory → Snapshot injection → Prompt 中可见 → 影响 Agent 决策偏好。

---

## 4. Episodic Memory（情景记忆）

> 关于过去经验、事件的记录——"Agent 经历过什么"。

| 维度 | 值 |
|------|-----|
| **Duration** | 长期 |
| **Governance** | 写入需 confirmation |
| **Confidence min** | ≥0.6 |
| **当前状态** | 🟡 partial（仅 `bug_fix_lesson` heuristic） |

**子类型**：

| 子类型 | 示例 |
|--------|------|
| bug_fix_lesson | "上次 null pointer 是因为忘记检查 Optional" |
| refactor_experience | "这次重构花了 2h，因为旧代码耦合重" |
| troubleshooting | "上次服务挂了是因为没加超时" |
| decision_outcome | "选了 gRPC，后来调试困难，改用 REST" |

**行为影响**：Episodic memory → consolidation → 提取 pattern → 可能升级为 procedural memory。

---

## 5. Procedural Memory（程序记忆）⚠️ 边界待收缩

### 5.1 定位

> 从 interaction / critique / episodic pattern 中沉淀出的**交互学习型行为适应（interaction-learned behavioral adaptation）**。

Procedural memory 回答："从我们之前的互动中学到的——在这种情境下，Agent 应该怎么做？"

**关键约束**：Procedural memory 的核心是**涌现性（emergence）**——它从真实交互中自发产生，不是被预先定义的。它不是一个 general instruction system，不是 skill repository，不是 workflow engine。它的唯一合法来源是：用户反复纠正 Agent 的行为模式，或从多次 episodic experience 中提取的跨 session 行为规律。

**一句话边界**：如果一条行为规则可以在 Agent 启动前写好，它不是 procedural memory——它是 skill、config、或 instruction template。

### 5.2 特点

| 维度 | 值 |
|------|-----|
| **Duration** | 长期 |
| **Governance** | **最高门槛** — 必须 explicit confirmation |
| **Confidence min** | ≥0.85 |
| **当前状态** | 🟡 partial（仅 `project_rule` heuristic，范围需收缩） |

### 5.3 子类型（Convergence 后收缩）

| 子类型 | 示例 | 来源 |
|--------|------|------|
| **critique_learned** | "用户批评过多次写 SQL 嵌套太深 → 以后避免" | 用户批评 + episodic pattern |
| **communication_rule** | "用中文解释架构，但保留代码原文" | 用户显式偏好 + 多次确认 |

### 5.4 Procedural Memory 与相邻系统的边界

**这是当前最关键的架构边界。Procedural Memory 不得吞掉以下任何系统：**

| 内容 | 属于 | 为什么不是 Procedural Memory |
|------|------|------|
| coding_rule（"用 black 格式化"） | Skill / Repo Convention | 操作规范，不是从交互中涌现的行为 |
| testing_rule（"commit 前跑 pytest"） | Skill / Workflow | 操作流程，不是行为适应 |
| workflow_rule（"部署前跑 smoke test"） | Skill / Workflow | 操作流程 |
| safety_rule（"不直接操作生产数据库"） | Skill / Safety Config | 安全策略，不是学习结果 |
| operating procedure | Skill | 预定义指令模板 |
| instruction template | Skill / Prompt | 静态提示词模板 |
| general behavioral guidelines | Config / System Prompt | 全局默认行为，不来自交互 |

**Procedural Memory 的法定判定标准**（不可放宽）：
1. ✅ 来源必须是真实交互/批评/纠正——不是预设、不是模板、不是配置
2. ✅ 必须经过 explicit human confirmation（最高 governance 门槛）
3. ✅ 内容必须是**交互学习型行为适应**（interaction-learned behavioral adaptation），不是通用指令
4. ❌ 任何可以事先写好的规则——不是 procedural memory
5. ❌ 任何不来自具体交互的通用行为准则——不是 procedural memory

**核心原则**：Procedural Memory 的体积应由真实交互历史决定。如果交互中没有发生过相关纠正，procedural memory 理应为空。它不是需要"填充"的规则库——它是交互历史的沉淀物。

---

## 6. Taxonomy 对比总表

| 维度 | Working | Session | Semantic | Episodic | Procedural |
|------|---------|---------|----------|----------|------------|
| **Duration** | 1 turn | 1 session | months+ | months+ | months+ |
| **Persistence** | 否 | 否 | **是** | **是** | **是** |
| **Confirmation** | 不需 | SESSION_ONLY | 需要 | 需要 | **最高** |
| **Auto-write** | — | — | **永不** | **永不** | **永不** |
| **Human visible** | 隐式 | session 内 | **必须** | **必须** | **必须** |
| **Human editable** | — | — | **是** | **是** | **是** |
| **Forget priority** | — | 自动过期 | 标准 | 标准 | **最高** |
| **当前状态** | ✅ | ✅ | ✅ | 🟡 | 🟡 |
| **Behavior impact** | 直接 | 直接 | 间接 (prompt) | 间接 (precedent) | **直接 (约束)** |

---

## 7. 什么不属于 Memory

| 信息类型 | 属于什么 |
|----------|----------|
| 当前 step 的 tool 调用结果 | Working memory / context |
| Task plan steps | Task state |
| API key / secret / token | 永不被记忆 |
| 代码片段（作为 reference） | Knowledge / Reference 系统 |
| Checkpoint 快照 | Checkpoint system |
| coding_rule / testing_rule / workflow_rule | **Skill System** |
| safety_rule | **Skill / Safety Config** |
| operating procedure | **Skill System** |

---

## 8. 与当前实现的映射

| Memory 类型 | 当前支持 | 差距 |
|-------------|----------|------|
| Working | `conversation.messages` | — |
| Session | `SESSION_ONLY` + `InMemoryMemoryStore` | runtime-scoped，session 结束消失（不自动持久化） |
| Semantic | explicit retain + heuristic suggestion | 需持久化 |
| Episodic | `bug_fix_lesson` heuristic | 需 consolidation pipeline（🔮） |
| Procedural | `project_rule` heuristic（范围需收缩） | 需独立 lifecycle + review 机制（🔮） |

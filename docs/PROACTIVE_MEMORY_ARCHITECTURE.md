# Proactive Memory Architecture

> **参考文档** — 本文档是 L1/L2/L3 分层架构和 Anti-Pollution 机制的详细参考。
> Canonical design source: `docs/rfc/MEMORY_CANONICAL_RFC.md`

**创建日期**: 2026-05-11
**性质**: Detailed Reference — L1/L2/L3 分层架构细节
**状态**: Absorbed by canonical RFC — 保留为详细参考
**上级文档**: `docs/rfc/MEMORY_CANONICAL_RFC.md`, `docs/MEMORY_CONSTITUTION.md`

---

## 0. Groundedness 总览

| Layer | 状态 | 说明 |
|-------|------|------|
| L1: Deterministic Heuristic | ✅ implemented | `memory_suggestions.py`, 397行, 78 tests |
| L2: LLM Proposal | ❌ speculative | 设计已完成，0 代码 |
| L3: Consolidation | 🔮 research | 概念设计，需跨 session persistence 后才能验证 |
| Anti-Pollution | 🟡 partial | 频率限制/dedup 已实现，其余为设计 |
| Anti-Hallucination | 🟡 partial | source_evidence 已定义，LLM calibration 未实现 |

**图例**：✅ implemented | 🟡 partial | ❌ speculative | 🔮 research

---

## 1. L1: Deterministic Heuristic（✅ implemented）

### 1.1 当前实现

`agent/memory_suggestions.py` — `DeterministicSuggestionEngine`：

```
User input → policy NO_OP → _try_suggestions()
  → 4 heuristic rules:
    1. project_rule: "这个项目规定/禁止/必须…" → procedural (0.80)
    2. bug_fix_lesson: "上次就是因为/经验教训…" → episodic (0.70)
    3. architecture_decision: "我们选了/决定用…" → semantic (0.75)
    4. repeated_preference: "我喜欢/习惯…" × 3 → semantic (0.70)
  → 5 层过滤 (confidence / sensitivity / injection / dedup / frequency)
  → CONFIRMATION_REQUIRED
```

### 1.2 特点

- **零 LLM 调用** — 不花钱、不增加延迟
- **确定性** — 同样输入永远产生同样结果
- **可解释** — 每条 candidate 有明确的匹配原因
- **覆盖面窄** — 只处理含关键词的显式模式

### 1.3 根本局限

**L1 不是"主动记忆"，是"关键词触发式候选"。** 不能识别：
- 不含 marker 的偏好表达（"以后回答 SQL 尽量少写嵌套子查询"）
- 用户反复纠正 Agent 的行为模式（不含 preference prefix）
- 跨 session 的行为模式（没有 persistence）

---

## 2. L2: LLM Proposal（❌ speculative）

### 2.1 定位

L1 快而便宜 → 处理显式模式。L2 慢而深 → 处理隐式模式。L1 和 L2 是互补关系，不是替代关系。

### 2.2 设计要点（未实现）

- **触发时机**：task boundary / 每 N turns / 用户显式触发（不在每条 input 后触发）
- **输出**：proposal only，不是 decision — 必须经过 confirmation
- **安全机制**：
  - LLM confidence cap at 0.8（LLM 不可信任其自身置信度）
  - `source_evidence` 必须（用户可核实原文）
  - 内容必须经过 policy 的敏感词/injection 检查
  - 与 store 的 SHA256 dedup
- **Confidence calibration**：LLM ≥0.9 → 处理后 0.75；0.7-0.9 → 0.6；<0.7 → 丢弃

### 2.3 当前状态

纯设计，0 代码。**在 L1 的局限性成为实际问题之前，不进入实现。**

---

## 3. L3: Consolidation（🔮 research）

### 3.1 定位

跨 session 模式提取 + 升级（episodic → procedural）。这是 memory 体系中最深层的认知操作。

### 3.2 概念设计（未实现）

- **触发时机**：session 结束 / 每 N sessions / 用户显式触发
- **操作类型**：Merge（合并相似）、Abstract（episodic → procedural）、Conflict resolve、Demote、Age out
- **输出**：proposal only — 合并和升级必须经用户确认

### 3.3 当前状态

纯概念。**依赖跨 session persistence，在 Phase 4 (filesystem-native store) 完成前无法验证。**

---

## 4. 反污染 (Anti-Pollution)

### 4.1 污染类型

| 污染类型 | 表现 | 防护 | 状态 |
|----------|------|------|------|
| **Volume pollution** | 过多无关 memory 淹没重要信息 | frequency limit + max records cap | 🟡 频率限制已实现 |
| **Hallucinated memory** | LLM "记住"了从未发生的事 | source_evidence + confirmation | 🟡 设计已有 |
| **Stale memory** | 过时偏好仍在影响行为 | decay + consolidation review | ❌ speculative |
| **Over-personalization** | 过度拟合 | 偏好抽象化 | ❌ speculative |
| **Manipulation memory** | prompt injection 诱导 | policy 层 injection 检测 | ✅ implemented |
| **Duplicate memory** | 同一内容多次记录 | content hash dedup | ✅ implemented |
| **Conflicting memory** | 两条 memory 互相矛盾 | consolidation 冲突检测 | ❌ speculative |

### 4.2 数量上限（设计值，未在代码中强制）

```
max semantic:    50
max episodic:    30
max procedural:  20
```

---

## 5. 反幻觉 (Anti-Hallucination)

### 5.1 LLM Proposal 的 hallucination 风险（当前不适用，L2 未实现）

LLM 可能：编造偏好、夸大一次性意见、提取错误事实、混淆上下文。

### 5.2 防护机制

1. **Source evidence requirement** — 每条 LLM proposal 必须包含原文引用
2. **Confidence cap at 0.8** — LLM 的 proposal 永远达不到最高置信度
3. **Confirmation 硬约束** — 用户 reject 的 proposal 不写入
4. **Ephemeral check** — 临时信息不进入 proposal
5. **Cross-reference** — consolidation 时检查与现有 memory 的矛盾

---

## 6. 与当前实现的关系

```
当前 (Phase 2, Operational):
  L1 heuristic ✅ — 4 rules, 78 tests, 生产可用

Phase 3 (Design First — 当前阶段, 部分已被 spike 覆盖):
  设计问题:
  - 持久化方案选型 — spike 已验证 filesystem-native viability ✅
  - store 与 checkpoint 边界 — 待设计
  - pending confirmation restore — 待设计
  - recall API 范围 — spike 已验证 scope+recency 策略 ✅
  - 跨 session 安全边界 — 待设计

Phase 4 (near-term, 待 Phase 3 完成后):
  L1 heuristic → 保持
  + filesystem-native store 实现

Phase 5+ (deferred research):
  L2 LLM Proposal → 需 spike validation
  L3 Consolidation → 需跨 session persistence
```

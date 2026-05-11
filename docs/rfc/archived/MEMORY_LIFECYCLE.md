# Archived RFC

This RFC has been absorbed into:
docs/rfc/MEMORY_CANONICAL_RFC.md

Do not use this document as the canonical memory design source.

---

# Memory Lifecycle

**创建日期**: 2026-05-11
**性质**: Architecture RFC — Memory 从诞生到遗忘的完整生命周期
**状态**: Draft v2 — Convergence Pass 后收缩
**上级文档**: `docs/MEMORY_CONSTITUTION.md`, `docs/MEMORY_TAXONOMY.md`

---

## 0. Groundedness 总览

**Lifecycle 分为两个层级：Operational（当前可运行的）和 Deferred Meta-Cognitive Research（概念设计，待未来验证）。**

### Operational Lifecycle（代码已存在或近期可实现）

| Phase | 状态 | 代码证据 |
|-------|------|----------|
| Proposal (explicit retain) | ✅ current | `memory_policy.py` |
| Proposal (heuristic L1) | ✅ current | `memory_suggestions.py`, 4 rules, 78 tests |
| Confirmation | ✅ current | `memory_confirmation.py` + `memory_interaction.py` |
| Forgetting | ✅ current | `forget` flow |
| Storage | 🟡 partial → near-term | `InMemoryMemoryStore` only；filesystem-native persistence 是 next implementation target（spike 已验证方案可行） |
| Retrieval | 🟡 partial → near-term | `build_memory_snapshot_from_store`，deterministic only；recall API 是 follow-on |

### Deferred Meta-Cognitive Research（纯概念，依赖未完成的前置条件）

| Phase | 状态 | 依赖 |
|-------|------|------|
| Proposal (LLM L2) | ❌ speculative | L1 的局限性尚未成为实际瓶颈 |
| Decay | ❌ speculative | 需要跨 session persistence + memory 数量 >50 |
| Consolidation | 🔮 research | 需要 persistence + L2 + 跨 session memory |
| Proposal (consolidation L3) | 🔮 research | 需要 consolidation 本身先实现 |
| Archival | ❌ speculative | 需要 filesystem-native store |
| Proceduralization | 🔮 research | 需要 consolidation，是最远端的 research direction |

**图例**：✅ current = 代码已存在且可用 | 🟡 partial = 部分实现，有明确缺口 | ❌ speculative = 纯设计，0 代码 | 🔮 research = 概念阶段，依赖未完成的前置条件

**关键信息**：Operational lifecycle 的 4 个 phase（proposal, confirmation, forgetting）已可运行。Storage 和 Retrieval 是 near-term 实现目标。Deferred 层的 6 个 phase 全部依赖 persistence 或其他前置条件——它们不是 roadmap commitments，是 research directions。

---

## 1. 为什么 Lifecycle 是核心复杂度

```
Storage:  把 bytes 写到磁盘 ← 简单，工程问题
Lifecycle: 什么该出生、什么该活着、什么该变老、什么该死 ← 复杂，设计问题
```

当前 my-first-agent 已完成 lifecycle 的前两个阶段（proposal + confirmation）的基础实现。Consolidation 之后的所有阶段都**仅在设计层面存在**，尚未被代码验证。

---

## 2. Lifecycle 全景（简化）

```
Proposal → Confirmation → Storage → Retrieval → Decay → Consolidation → Forgetting
                                                      ↓
                                              Proceduralization
```

---

## 3. Phase 1: Proposal ✅ current（部分）

### 3.1 已实现

| Proposal 来源 | 触发方式 | 实现位置 | 状态 |
|---------------|----------|----------|------|
| User explicit retain | `remember that X` / `记住 X` | `memory_policy.py` | ✅ |
| L1 heuristic — project_rule | "这个项目规定…" | `memory_suggestions.py` | ✅ |
| L1 heuristic — bug_fix_lesson | "上次就是因为…" | `memory_suggestions.py` | ✅ |
| L1 heuristic — architecture_decision | "我们选了…" | `memory_suggestions.py` | ✅ |
| L1 heuristic — repeated_preference | "我喜欢…" × 3 | `memory_suggestions.py` | ✅ |

### 3.2 未实现（❌ speculative / 🔮 research）

| Proposal 来源 | 状态 | 说明 |
|---------------|------|------|
| L2 LLM proposal | ❌ speculative | task boundary 时 LLM 评估对话 |
| L3 consolidation proposal | 🔮 research | 跨 session 模式提取 |
| Critique-driven proposal | ❌ speculative | 用户批评 Agent 行为时自动 proposal |

### 3.3 Proposal 质量要求（当前适用）

每条 candidate 必须带有：content、proposed_type、confidence、reason、source、source_evidence。

---

## 4. Phase 2: Confirmation ✅ current

### 4.1 已实现

5 种 confirmation choice：
```
ACCEPT         → approved → write store
EDIT_AND_ACCEPT → approved with edited content → write store
SESSION_ONLY   → session_only → write store (session scope)
REJECT         → rejected → no write
OTHER          → needs_clarification
```

### 4.2 已知不足（🟡 partial）

当前 question 文案是通用的（"我可以长期记住这条信息吗？"）。未来应按 source_type 和 memory_type 区分文案，但**当前 memory 数量少，通用文案足够**。

### 4.3 Confirmation 不可绕过

`requires_user_confirmation=True` 对所有 proposal 来源强制。

---

## 5. Phase 3: Storage 🟡 partial

### 5.1 当前

In-memory only (`InMemoryMemoryStore`)。Session 结束即丢失。

### 5.2 方向

Filesystem-native（Markdown + YAML frontmatter）已被 spike 验证为当前项目约束下的可行方案（见 `spike/run_spike.py`）。验证结果：

- **50 records, 12 files**: index build <8ms, grep instant, git diff 精确到行
- **Prompt assembly**: recency top 8 ≈293 tokens, scoped top 5 ≈145 tokens
- **Scaling ceiling**: 在 ≤200 active memory 时保持可维护，超过 500 时需要 consolidation 控制 growth
- **适用范围**: local-first, single-user, single-process, governance-first workflow

验证确认了 filesystem-native 在**当前项目约束**下的 viability（详见 `MEMORY_CONSTITUTION.md` §4.2 的约束列表）。这不意味着 filesystem-native 在所有场景下优于数据库方案——它是为此项目的特定约束设计的。

### 5.3 关键认知

Storage 不是 lifecycle 的终点。Storage 只是 snapshot——真正的状态在 lifecycle 的持续演进中。

---

## 6. Phase 4: Retrieval 🟡 partial

### 6.1 当前

`build_memory_snapshot_from_store` 是确定性选择：最多 5 条，按 scope 过滤，排除 sensitive，总计 ≤500 字符。在 memory 数量 ≤20 时足够。

### 6.2 未来方向（❌ speculative）

当 memory 数量超过 20-30 条时，需要 recall API（by scope, by recency, by relevance）。这是**过滤**，不是语义搜索。语义搜索应在 external provider backend 中实现，不在 core memory system 中。

---

## 7. Phase 5: Decay ❌ speculative

### 7.1 为什么需要 Decay（概念正确，但当前不紧迫）

- 用户偏好可能改变
- 项目规则可能过时
- 经验教训可能被更准确的经验替代

### 7.2 设计概念（未实现）

| memory_type | 默认 TTL | Decay 行为 |
|-------------|---------|-----------|
| semantic (user_preference) | 180 days | stability 逐级降低，建议 review |
| semantic (project_rule) | 365 days | 缓慢衰减 |
| episodic | 90 days | 衰减后建议 consolidation |
| procedural | 365 days | 缓慢衰减，需 active review |

### 7.3 关键原则

**Decay 不是自动删除。** Decay 降低 stability，触发 review proposal，但删除永远需要人确认。

### 7.4 当前状态

0 代码。**在 memory 数量 <50 且没有跨 session persistence 之前，decay 不会成为实际瓶颈。**

---

## 8. Phase 6: Consolidation 🔮 research

### 8.1 定义

> Consolidation 是跨 memory 的模式识别、抽象提炼、冲突消解。

### 8.2 设计概念（未实现）

| 操作 | 输入 | 输出 |
|------|------|------|
| Merge | 2+ 条相似 semantic | 1 条合并后的 semantic |
| Abstract | 3+ 条相关 episodic | 1 条 procedural |
| Conflict resolve | 2 条矛盾 memory | 保留 1 + 标记旧 |
| Demote | 长期未 recall | 降低 stability |
| Age out | 远超 TTL 未 recall | proposal forget |

### 8.3 当前状态

纯概念。**依赖跨 session persistence + L2 LLM proposal，在 Phase 4 完成前无法验证。**

---

## 9. Phase 7: Forgetting ✅ current

### 9.1 已实现

| 类型 | 触发 | 状态 |
|------|------|------|
| User-initiated forget | 用户 "forget X" | ✅ implemented |
| Forget 优先级最高 | 不需要利益权衡，直接执行 | ✅ implemented |

---

## 10. Phase 8: Archival ❌ speculative

### 10.1 设计概念（未实现）

Forget 操作 → 移到 archive → 30 天后自动物理删除（或用户手动 purge）。Archival 不是 memory，是 audit trail — 不进入 prompt、不被 recall。

### 10.2 当前状态

0 代码。**在 filesystem-native store 实现之前，archive 机制无载体。**

---

## 11. Phase 9: Proceduralization 🔮 research

### 11.1 定义

> 将 episodic/semantic memory 升级为 procedural memory。

```
Semantic "用户不喜欢过多注释"
  + Episodic "上次用户说注释太多"
  + Episodic "这次用户又让我减少注释"
    ↓ consolidation + proceduralization
Procedural "生成代码时保持注释简洁，只解释 why 不解释 what"
```

### 11.2 触发条件（概念）

- 同一模式在 ≥3 条 episodic memory 中出现
- 或用户显式表达 ≥3 次同一偏好
- 或 1 次用户 explicit "以后永远不要/要..."

### 11.3 为什么 Proceduralization 风险最高

Procedural memory 直接改变 Agent 行为。错误代价最高。因此需要：
- 最高 confirmation 门槛
- 必须有 review date
- forget 必须立即生效，无确认

### 11.4 当前状态

纯概念。**依赖 consolidation（🔮），而 consolidation 依赖 persistence（🟡）。这是最远端的 future direction。**

---

## 12. 当前 vs 未来的诚实评估

```
Operational Lifecycle（代码已存在或 near-term）：
  Proposal (explicit + L1 heuristic)
  Confirmation (5 choices)
  Forgetting (user-initiated)
  Storage (in-memory → filesystem-native, near-term)
  Retrieval (deterministic → recall API, near-term)

Deferred Meta-Cognitive Research（依赖未完成前置条件）：
  LLM Proposal (L2)
  Decay
  Consolidation
  Consolidation Proposal (L3)
  Archival
  Proceduralization
```

**关键信息**：12 个 phase 中，3 个有可用代码（proposal, confirmation, forgetting），2 个是 near-term 实现目标（storage, retrieval），6 个是 deferred research。当前 gap 不是缺陷——先有 persistence，才谈得上 consolidation。Operational layer 先稳定，Deferred layer 在条件成熟时逐个验证。

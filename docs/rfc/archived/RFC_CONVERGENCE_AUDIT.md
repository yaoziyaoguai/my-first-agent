# Archived RFC

This RFC has been absorbed into:
docs/rfc/MEMORY_CANONICAL_RFC.md

Do not use this document as the canonical memory design source.

---

# Memory RFC Convergence Audit

> 日期: 2026-05-11 | 性质: 只读分析，非实现 | 输入: 6 份文档 + 全部生产代码

---

## 输入清单

| # | 文档 | 性质 | 日期 |
|---|------|------|------|
| D1 | `docs/MEMORY_CONSTITUTION.md` | 宪章（根文档） | 2026-05-11 |
| D2 | `docs/MEMORY_TAXONOMY.md` | 类型分类 RFC | 2026-05-11 |
| D3 | `docs/MEMORY_LIFECYCLE.md` | 生命周期 RFC | 2026-05-11 |
| D4 | `docs/PROACTIVE_MEMORY_ARCHITECTURE.md` | L1/L2/L3 分层 RFC | 2026-05-11 |
| D5 | `docs/MEMORY_NEXT_STAGE_ARCHITECTURE.md` | Phase 1-5 路线图 | 2026-05-10 |
| D6 | `docs/rfc/RFC_MEMORY_GOVERNANCE_AND_EXTRACTION.md` | 本次新 RFC | 2026-05-11 |
| C | `agent/memory_*.py` (11 个文件) | 生产代码 | — |

---

## A. RFC Overlap Matrix

矩阵标注：**✅ = 一致** | **🟡 = wording evolution（语义变化但实质相同）** | **⚠️ = 实质性差异（需讨论）** | **🔴 = 冲突（不可共存）**

### A.1 Taxonomy 重叠矩阵

| 概念 | D1 Constitution | D2 Taxonomy | D3 Lifecycle | D4 Proactive | D5 Next-Stage | D6 New RFC | 评估 |
|------|:--:|:--:|:--:|:--:|:--:|:--:|------|
| Working Memory (1 turn) | ❌未提 | ✅ 定义 | ❌未提 | ❌未提 | ❌未提 | ❌未提 | D2 独有，D6 省略 |
| Session Memory (1 session) | ❌未提 | ✅ 定义 | ❌未提 | ❌未提 | ❌未提 | ❌未提 | D2 独有，D6 省略 |
| Semantic (事实/偏好) | ❌未提 | ✅ 定义 | ✅ 引用 | ✅ 引用 | ✅ 引用 | ✅ 定义 | 🟡 措辞演变 |
| Episodic (经验/事件) | ❌未提 | ✅ 定义 | ✅ 引用 | ✅ 引用 | ✅ 引用 | ✅ 定义 | 🟡 措辞演变 |
| Procedural (行为约束) | ❌未提 | ✅ 严格定义 | ✅ 引用 | ✅ 引用 | ✅ 引用 | ✅ 定义 | 🟡 措辞演变 |
| 5 种类型体系 | ❌未提 | ✅ | ✅ 引用 | ❌未提 | ❌未提 | ⚠️ 简化为 3 种 | ⚠️ D6 省略 Working/Session |
| Semantic 子类型 | ❌未提 | ✅ 5种子类型 | ❌未提 | ❌未提 | ❌未提 | ❌未提 | D2 独有 |
| Episodic 子类型 | ❌未提 | ✅ 4种子类型 | ❌未提 | ❌未提 | ❌未提 | ❌未提 | D2 独有 |
| Procedural 子类型 | ❌未提 | ✅ 2种子类型 | ❌未提 | ❌未提 | ❌未提 | ❌未提 | D2 独有 |
| Procedural 法定判定标准 | ❌未提 | ✅ 5条 | ❌未提 | ❌未提 | ❌未提 | ❌未提(隐含) | D2 独有，D6 精神一致 |

**结论**：D6 Taxonomy 与 D2 **核心分类一致**（semantic/episodic/procedural），但省略了 Working/Session 和所有子类型。这不构成冲突——D6 聚焦长期记忆，Working/Session 本身不进 store。

### A.2 Governance 重叠矩阵

| 原则 | D1 Constitution | D2 Taxonomy | D3 Lifecycle | D4 Proactive | D5 Next-Stage | D6 New RFC | 评估 |
|------|:--:|:--:|:--:|:--:|:--:|:--:|------|
| Agent proposes, Human adjudicates | ✅ 原则#1 | ✅ 引用 | ✅ 引用 | ✅ 引用 | ✅ 引用 | ✅ 引用 | ✅ 一致 |
| No silent auto-write | ✅ 原则#8 | ✅ 表明确认 | ✅ 确认必需 | ✅ 确认必需 | ✅ 确认必需 | ⚠️ T2例外 | 🔴 冲突 |
| Governance before storage | ✅ 原则#4 | ✅ | ✅ | ✅ | ✅ | ✅ 引用 | ✅ 一致 |
| Sensitive content blocked | ✅ 原则#9 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 一致 |
| Forget is first-class | ✅ 原则#6 | ✅ | ✅ | ❌未提 | ❌未提 | ❌未提 | D6 省略 |
| 3-tier governance (T1/T2/T3) | ❌未提 | ❌未提 | ❌未提 | ❌未提 | ❌未提 | ✅ 新增 | ⚠️ D6 新引入 |
| Auto-retain for episodic | ❌未提 | ❌未提 | ❌未提 | ❌未提 | ❌未提 | ✅ 新增 | ⚠️ D6 新引入 |

**关键冲突**：D1-D5 一致声明 "永不 auto-write"。D6 引入 T2 auto-retain 作为例外。这是整个 convergence audit 中最重大的单一冲突。

### A.3 Extraction Lifecycle 重叠矩阵

| 阶段 | D1 | D2 | D3 Lifecycle | D4 Proactive | D5 Next-Stage | D6 New RFC | 评估 |
|------|:--:|:--:|:--:|:--:|:--:|:--:|------|
| Trigger | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 新增 | ⚠️ D6 新阶段 |
| Extraction | ❌ | ❌ | ❌ | ✅ L1/L2描述 | ❌ | ✅ 独立阶段 | ⚠️ D6 提升为一级阶段 |
| Proposal | ✅ 提法 | ✅ | ✅ Phase 1 | ✅ L1/L2/L3 | ✅ Phase 2 | ✅ | ✅ 一致 |
| Confirmation | ✅ 提法 | ✅ | ✅ Phase 2 | ✅ | ✅ | ⚠️ 改为 Adjudication | 🟡 重命名 |
| Storage | ✅ 提法 | ✅ | ✅ Phase 3 | ✅ | ✅ | ✅(Retain) | 🟡 重命名 |
| Recall/Retrieval | ❌ | ❌ | ✅ Phase 4 | ✅ | ❌ | ✅ Recall | 🟡 名称微调 |
| Decay | ❌ | ❌ | ✅ Phase 5 | ✅ | ❌ | ❌(→Phase 6+) | ⚠️ D6 降级 |
| Consolidation | ❌ | ❌ | ✅ Phase 6 | ✅ L3 | ❌ | ❌(→Phase 6+) | ⚠️ D6 降级 |
| Forgetting | ✅ | ✅ | ✅ Phase 7 | ❌ | ❌ | ❌(→Phase 6+) | ⚠️ D6 降级 |
| Archival | ❌ | ❌ | ✅ Phase 8 | ❌ | ❌ | ❌(→Phase 6+) | ⚠️ D6 降级 |
| Proceduralization | ❌ | ❌ | ✅ Phase 9 | ❌ | ❌ | ❌(→Phase 6+) | ⚠️ D6 降级 |
| Session-end extraction | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 新增 | ⚠️ D6 新阶段 |

**结论**：D6 重新组织了生命周期——从 D3 的 9 阶段改为 6 阶段核心 pipeline + 4 个 deferred phase。Extraction 被提升为一级阶段，Decay/Consolidation/Forgetting/Archival/Proceduralization 被移入 "Phase 6+"。这更像**架构重组**而非冲突——D6 把 operational pipeline 和 meta-cognitive research 分开了。

### A.4 Confidence 重叠矩阵

| 规则 | D2 Taxonomy | D4 Proactive | D6 New RFC | 评估 |
|------|:--:|:--:|:--:|------|
| Semantic min confidence | ≥0.8 | ≥0.6 (L1 general) | ≥0.8→T1, <0.8→T3 | ✅ 一致 (D2+D6) |
| Episodic min confidence | ≥0.6 | ≥0.6 (L1 general) | ≥0.8→T1, 0.6-0.8→T2, <0.6→T3 | ⚠️ D6 新增中间档 |
| Procedural min confidence | ≥0.85 | ≥0.6 (L1 general) | ≥0.6→T1 | ⚠️ D2 更严格 |
| project_rule confidence | ❌ | 0.80 | 0.80 | ✅ 一致 |
| bug_fix_lesson confidence | ❌ | 0.70 | 0.70 | ✅ 一致 |
| architecture_decision confidence | ❌ | 0.75 | 0.75 | ✅ 一致 |
| repeated_preference confidence | ❌ | 0.70 | 0.70 | ✅ 一致 |
| Confidence tier mapping | ❌ | ❌ | ✅ 0-0.3/0.3-0.6/0.6-0.8/0.8-1.0 | ⚠️ D6 新引入 |
| Importance vs Confidence | ❌ | ❌ | ✅ 区分 | ⚠️ D6 新引入 |

### A.5 Filesystem-Native 重叠矩阵

| 约束 | D1 Constitution | D3 Lifecycle | D5 Next-Stage | D6 New RFC | 评估 |
|------|:--:|:--:|:--:|:--:|------|
| Local-first, human-readable | ✅ 原则#3 | ✅ | ✅ | ✅ | ✅ 一致 |
| Markdown + YAML frontmatter | ✅ §4.2 | ✅ §5.2 | ❌(设计阶段) | ✅ §8.1 | ✅ 一致 |
| ≤200 active records | ✅ §4.2 | ✅ §5.2 | ❌ | ✅ §8.3 | ✅ 一致 |
| 不做 vector/embedding/search | ✅ | ✅ | ✅ | ✅ §8.4 | ✅ 一致 |
| Single-user, single-process | ✅ §4.2 | ✅ | ❌ | ✅ §8.3 | ✅ 一致 |
| No pyyaml | ❌ | ❌ | ❌ | ✅ §8.4 | D6 新增约束 |

**结论**：Filesystem-native 的约束集在全部文档中高度一致。D6 没有任何偏离。

---

## B. Conflicting Principles

### B.1 🔴 CRITICAL: "No silent auto-write" vs T2 Auto-Retain

**D1 Constitution §2.3 原文**:
> Auto-write (自动写入): Agent 自己决定并写入 — **永远不做**

**D1 Constitution 原则 #8**:
> No silent auto-write — 用户永远知道 Agent 记住了什么

**D2 Taxonomy §6 总表**:
> Auto-write: 永不 for Semantic, Episodic, Procedural

**D6 New RFC §3.1**:
> T2: Auto-Retain — 低价值 episodic、低置信度但非零价值的 pattern → extraction → auto-retain → store

**冲突性质**：这是 governance 边界在移动，不是措辞差异。D1-D5 一致说 "永不"，D6 说 "episodic 可以"。

**D6 的辩护逻辑**（隐含）：
1. T2 记录标记 `approval_status="auto_retained"` — 用户仍可见
2. 仅适用于 episodic（最不影响行为）
3. 有 safety 边界（confidence 区间、sensitivity 检查）
4. 用户可后续 upgrade 或删除

**评估**：D6 的 auto-retain 不是 Constitution 描述的 "silent auto-write"（Agent 单方面决定、用户不知道）。D6 的 auto-retain 是有边界的、可审查的、可逆的。但它确实**违背了 Constitution 的绝对禁止措辞**。需要判定：是 Constitution 措辞需要从 "永不" 细化为 "有条件允许"，还是 D6 需要撤回 T2。

### B.2 ⚠️ MEDIUM: Procedural confidence threshold

**D2 Taxonomy §5.2**: Procedural confidence min ≥0.85
**D6 New RFC §7.1**: Procedural L1 heuristic confidence≥0.6 → T1
**D4 L1 实现**: project_rule confidence = 0.80

D2 要求 0.85，但 L1 实现只有 0.80，D6 用更宽松的 0.6。三重不一致。

**实际影响**：当前 L1 的 project_rule 以 0.80 confidence 进入 confirmation（因为 requires_user_confirmation=True 强制执行）。D2 的 0.85 从未在代码中变为 threshold gate。D6 的 0.6 也不会改变实际行为（procedural 永远 T1 confirmation）。但数值不一致说明设计意图在漂移。

### B.3 🟡 MINOR: Lifecycle phase naming and organization

**D3**: 9 phases (Proposal → Confirmation → Storage → Retrieval → Decay → Consolidation → Forgetting → Archival → Proceduralization)
**D6**: 6 phases (Trigger → Extraction → Proposal → Adjudication → Retain → Recall) + 4 deferred

D6 实际上**没有删掉** D3 的后期 phase——它们被归入 Phase 6+ "远期研究"。这是 reorganization，不是否定。但 "Adjudication" 替代 "Confirmation" 暗含了 T2 auto-retain 的裁决逻辑，不是纯粹重命名。

### B.4 🟡 MINOR: MemoryProvider/External Provider 的缺失

D5 (MEMORY_NEXT_STAGE_ARCHITECTURE.md) 花了大量篇幅设计：
- MemoryProviderProtocol（外部 provider 协议）
- ProviderRecallResult / ProviderWriteRequest
- 双写模型（本地 authoritative + 外部 best-effort）
- Mem0 / LangChain / Zep adapter seam
- 外部 recall 的 sanitizer pipeline

D6 完全没有提及外部 provider。这不是冲突——D6 明确将 "不做外部 provider" 列入 §10.1。但这意味着**如果采用 D6 作为 canonical RFC，D5 的 external provider 设计将被归档为历史参考**。

---

## C. Implementation Compatibility

### C.1 当前实现与各版 RFC 的兼容性

| 模块 | 当前代码 | vs D1-D5 历史 RFC | vs D6 New RFC |
|------|---------|:--:|:--:|
| `memory_contracts.py` | MemoryCandidate, MemoryDecision, MemoryOperationIntent | ✅ 兼容 | ⚠️ 需加 memory_type/source_type 字段 |
| `memory_policy.py` | 显式 retain/forget 检测 + sensitivity/injection | ✅ 兼容 | ✅ 兼容（无需改） |
| `memory_suggestions.py` | L1 heuristic 4 rules + 5 层过滤 | ✅ 兼容 | ✅ 兼容（无需改） |
| `memory_fs_store.py` | FilesystemMemoryStore, _meta_from_intent 硬编码, _apply_retain 硬编码 | 🟡 metadata 缺失 | ⚠️ 需修复硬编码 |
| `memory_store.py` | InMemoryMemoryStore, _record_from_intent | 🟡 metadata 缺失 | ⚠️ 需修复硬编码 |
| `memory_runtime.py` | evaluate_user_text, _try_suggestions, resolve_confirmation | ✅ 兼容 | ⚠️ 需加 T2 路径 |
| `memory_confirmation.py` | 5 choices, build/resolve | ✅ 兼容 | ✅ 兼容（无需改） |
| `memory_operations.py` | build_memory_operation_intent, build_memory_audit_summary | ✅ 兼容 | ⚠️ 需传 metadata |
| `memory_interaction.py` | handle_memory_confirmation_reply | ✅ 兼容 | ✅ 兼容（无需改） |
| `memory_snapshot_generator.py` | build_memory_snapshot_from_store | ✅ 兼容 | ⚠️ 需标注 auto_retained |
| `memory.py` | extract_memories_from_session (no-op) | 🟡 本就是 no-op | ⚠️ 需重实现 |

### C.2 兼容性总结

**当前实现更接近 D1-D5 历史 RFC**：
- 100% 路径都走 confirmation
- 无 auto-retain
- memory_type 硬编码
- extract_memories_from_session 是 no-op

**迁移到 D6 New RFC 的改动量**：

| 改动 | 文件 | 破坏性 | 行数估计 |
|------|------|:--:|------|
| MemoryOperationIntent 加字段 | `memory_contracts.py` | 否（default 兼容） | +5 |
| build_memory_operation_intent 传 metadata | `memory_operations.py` | 否 | +8 |
| _meta_from_intent 用实际 memory_type | `memory_fs_store.py` | 否 | ~5 |
| _apply_retain 用实际 memory_type | `memory_fs_store.py` | 否 | ~5 |
| _record_from_intent 用实际 memory_type | `memory_store.py` | 否 | ~5 |
| snapshot 标注 auto_retained | `memory_snapshot_generator.py` | 否 | +10 |
| T2 auto-retain 路径 | `memory_runtime.py` | 否（新分支） | ~30 |
| extract_memories_from_session 重实现 | `memory.py` | 否（替换 no-op） | ~150 |
| Pending confirmation 跨 session | `memory_fs_store.py` + `memory_runtime.py` | 否 | ~60 |
| L2 LLM extraction | 新文件 | 否 | ~200 |

总估计：~480 行，全为增量/修复，无破坏性变更。无 schema migration。

---

## D. Migration Risk

### D.1 风险矩阵

| 风险 | 等级 | 触发条件 | 缓解 |
|------|:--:|------|------|
| D6 T2 auto-retain 违反 Constitution 原则 #8 | 🔴 HIGH | 直接实现 T2 而不先更新 Constitution | 先 convergence 决议，再改 Constitution 措辞，最后实现 |
| D2 Taxonomy 的子类型在 D6 中丢失 | 🟡 LOW | 后续实现需要子类型时找不到权威定义 | D6 不需要子类型——它们在 D2 中已定义，D6 引用即可 |
| D5 external provider 设计被 D6 静默覆盖 | 🟡 LOW | 未来想接 external provider 时发现设计过时 | D5 归档为历史参考，external provider 不在当前 scope |
| D3 lifecycle 的 Decay 被 D6 降级 | 🟡 LOW | Phase 5 完成后发现没有 decay 设计 | Decay 在 D3 中已有完整设计，Phase 6+ 时可引用 |
| D6 的 confidence tier 映射不是从代码校准而来 | 🟡 LOW | L2 LLM confidence 与 tier 映射不匹配 | Phase 5 实现时需 calibration |
| Constitution 更新导致原则漂移 | 🔴 HIGH | 为迁就 D6 削弱 "no auto-write" 原则 | 保留原则精神，细化措辞：从 "永不" 改为 "除受控 episodic T2 外永不" |

### D.2 最大单一风险

**Constitution 原则 #8 的削弱是最危险的 migration risk。** "No silent auto-write" 是整个 memory 体系的信任基石。如果因一次 RFC 就放松这个原则，没有理由不在下次 RFC 中进一步放松（"semantic 也可以 T2" → "procedural 也可以 T2"）。

**建议**：如果 T2 被采纳，Constitution 必须明确限制：
- T2 仅限 episodic
- T2 记录必须标注 `auto_retained`
- T2 不可扩展到 semantic 或 procedural
- 此限制写入 Constitution，成为不可放松的宪法级约束

---

## E. Drift Risk

### E.1 已识别的 Architecture Drift

| Drift | 来源文档 | 表现 | 风险 |
|------|---------|------|:--:|
| **Governance boundary drift** | D6 vs D1 | 从 "永不 auto-write" 到 "episodic 可以 auto-retain" | 🔴 |
| **Lifecycle scope drift** | D6 vs D3 | 从 9-phase 到 6-phase + 4 deferred | 🟡 |
| **Phase numbering drift** | D6 vs D5 | D5 Phase 4=Filesystem Store, D6 Phase 4=已完成基线 | 🟡 |
| **External provider drift** | D6 vs D5 | D5 设计了完整 external provider 架构, D6 完全不提 | 🟡 |
| **Confidence threshold drift** | D6 vs D2 | Procedural: D2 0.85, L1 0.80, D6 0.6 | 🟡 |
| **Terminology drift** | D6 vs all | "Adjudication" 替代 "Confirmation", "Retain" 替代 "Storage" | 🟡 |

### E.2 Drift 的根本原因

D1-D5 是在 **Phase 2 实现期间** 写的，聚焦于 "当前已有什么 + 近期要做什么"。D6 是在 **Phase 4 代码审计后** 写的，聚焦于 "从当前状态到下一个有意义的 milestone 需要什么"。

两者的时间锚点不同：
- D1-D5: 锚定在 Phase 2 完成时（in-memory store, explicit retain + L1 heuristic）
- D6: 锚定在 Phase 4 完成时（filesystem-native store, recall API）

时间锚点的移动解释了大部分差异。D6 不是在否定 D1-D5，而是从更远的位置向前看。

### E.3 最危险的 Drift: Trust Model

D1 Constitution §2.2 列举了 silent auto-write 的 5 个危害：
1. Hallucinated memory
2. Memory pollution
3. Over-personalization
4. Manipulation risk
5. 信任侵蚀

D6 的 T2 auto-retain 对 **第 5 项（信任侵蚀）** 风险最高。即使 T2 仅限于 episodic + 低 confidence，用户看到 "agent 自己存了东西" 的那一刻，信任可能已经受损。

**缓解**：D6 的 §5.2 pending confirmation 机制是关键——session-end 提取的 T1 candidate 在下个 session 开头展示给用户确认。这个机制如果同时应用于 T2 candidate（"上次 session 我自动保存了这些 episodic 记录，要保留还是删除？"），可以消除信任侵蚀风险。

---

## F. 哪些建议 Merge

### F.1 建议 Merge 到 Canonical RFC 的内容

| 来源 | 内容 | Merge 理由 |
|------|------|------|
| **D2** §5 | Procedural 法定判定标准（5 条） | D6 只有精神一致，缺少显式文字。应显式纳入 |
| **D2** §1-2 | Working/Session Memory 定义 | D6 聚焦长期记忆，但应在 §1 注明 "短期记忆不在本 RFC 范围" |
| **D2** §6 | Taxonomy 对比总表 | 权威性高，D6 无等价物 |
| **D2** §7 | "什么不属于 Memory" | 边界定义，所有 RFC 应一致引用 |
| **D1** §2.2 | 为什么 silent auto-write 是反模式（5 条理由） | D6 引入 T2 时必须逐条回应这 5 条理由 |
| **D1** §5 | 人类权利清单 | 应引用而非重写 |
| **D3** §7-11 | Decay, Consolidation, Forgetting, Archival, Proceduralization 设计 | D6 降级到 Phase 6+，但设计本身不应丢失 |
| **D4** §4-5 | Anti-Pollution 7 类型 + Anti-Hallucination 5 机制 | D6 未覆盖，但 Phase 5 实现时需要 |
| **D5** §5 | 隐私/安全/Prompt Injection 信任模型 | D6 应在 §3 引用此信任模型作为 T2 的安全基础 |

### F.2 不建议 Merge 的内容

| 来源 | 内容 | 不 Merge 理由 |
|------|------|------|
| **D5** §3 | External MemoryProvider 全部设计 | 当前明确不做，留作历史参考 |
| **D5** §6 | Observer/Audit 事件清单 | 过于详细，待实现时再定义 |
| **D4** §2.2 | L2 LLM confidence cap at 0.8 | D6 的 confidence tier 设计取代了此机制 |
| **D3** | Decay TTL 数值（180d/365d/90d/365d） | 未经验证的数值，不应进入 canonical RFC |

---

## G. 哪些建议保留为 Future RFC

| 内容 | 建议归档为 | 触发条件 |
|------|----------|------|
| **D5 External MemoryProvider Protocol** | `docs/rfc/RFC_EXTERNAL_MEMORY_PROVIDER.md`（从 D5 提取） | 当需要接外部 provider 时 |
| **D5 Observer/Audit 事件体系** | `docs/rfc/RFC_MEMORY_OBSERVABILITY.md`（从 D5 提取） | 当事件数量 >10 时 |
| **D3 Decay 机制** | `docs/rfc/RFC_MEMORY_DECAY.md`（从 D3 提取） | 当 active records >50 时 |
| **D3 Consolidation + Proceduralization** | `docs/rfc/RFC_MEMORY_CONSOLIDATION.md`（从 D3 提取） | 当 active records >100 时 |
| **D2 子类型体系** | 保留在 D2，不在主 RFC 中重复 | 子类型在实现时作为 reference |
| **D4 Anti-Pollution 上限（50/30/20）** | 保留在 D4，验证后再进入 canonical | 当 memory 数量接近上限时 |

---

## H. 推荐 Canonical RFC

### H.1 推荐

**以 D6 (`RFC_MEMORY_GOVERNANCE_AND_EXTRACTION.md`) 为 canonical RFC**，在合并 F.1 建议内容 + 解决 B.1 冲突后发布为 v1.0。

### H.2 理由

| 维度 | D1-D5（历史 RFC 集） | D6（新 RFC） | 判定 |
|------|:--:|:--:|------|
| **与当前实现的接近度** | D1-D5 更接近（no auto-retain） | D6 有偏差（T2 auto-retain） | D1-D5 胜 |
| **与 Phase 4 完成状态的对应** | D1-D5 锚定在 Phase 2 | D6 锚定在 Phase 4 | D6 胜 |
| **向前看的清晰度** | 分散在 5 份文档中 | 集中在 1 份文档 | D6 胜 |
| **Governance 设计深度** | 绝对禁止 auto-write | 分级治理 T1/T2/T3 | D6 更细粒度 |
| **实现指导性** | D5 最详细但涉及 external provider | D6 聚焦 Phase 5 可操作步骤 | D6 胜 |
| **架构一致性** | 5 份文档间存在部分不一致 | 单一作者，内在一致 | D6 胜 |
| **Filesystem-native 承诺** | 声明但未落地 | 基于 Phase 4 已实现代码 | D6 胜 |

### H.3 Canonical RFC 需要的修正（发布 v1.0 前）

1. **解决 B.1 冲突**：明确 T2 auto-retain 是否违反 Constitution，如不违反则更新 Constitution 措辞
2. **纳入 F.1 内容**：Procedural 判定标准、Working/Session 边界、人类权利引用、anti-pollution 机制
3. **统一 Phase 编号**：与 D5 对齐或显式声明新编号体系
4. **明确 D1-D5 的关系**：声明 canonical RFC 取代哪些历史文档的哪些部分
5. **添加 Confidence threshold 的单一权威来源**：解决 D2/D4/D6 之间的数值不一致

---

## I. 推荐下一阶段顺序

### I.1 当前优先级（Convergence 阶段）

```
Step 0: 本 Audit 评审 ← 当前
Step 1: 决议 B.1 冲突（T2 auto-retain 是否接受）
Step 2: 按 H.3 修正 D6，发布 canonical RFC v1.0
Step 3: 更新 D1 Constitution §2.3/§8 以反映决议
Step 4: 标记历史文档状态（D2-D5 中哪些章节被 canonical RFC 取代）
```

### I.2 Phase 4 缺口修复（在 Phase 5 之前）

```
Step 5: memory_type 流通（3 处硬编码修复）
Step 6: approval_status 支持 auto_retained
Step 7: snapshot 标注 auto_retained 来源
```

这 3 步是让 Phase 4 "真正完整"的最小改动，独立于 T2 决议——即使 T2 被否决，memory_type 流通也是必要的。

### I.3 Phase 5（在 Canonical RFC 确认后）

```
Step 8: extract_memories_from_session() 重实现
Step 9: T2 auto-retain 路径（如被采纳）
Step 10: Pending confirmation 跨 session 传递
Step 11: L2 LLM extraction at task boundaries
```

### I.4 Phase 6+（不在当前 scope）

```
🔮 Decay
🔮 Consolidation + Proceduralization
🔮 Archival
🔮 External MemoryProvider（如需）
```

### I.5 关键依赖链

```
Canonical RFC v1.0
  ├─→ Phase 4 缺口修复（不依赖 T2 决议）
  └─→ Phase 5 实现（依赖 T2 决议 + canonical RFC）
        ├─→ Session-end extraction（依赖 memory_type 流通）
        ├─→ T2 auto-retain（依赖 B.1 决议）
        ├─→ Pending confirmation（依赖 session-end extraction）
        └─→ L2 LLM extraction（依赖 session-end extraction）
```

---

## 附录：冲突严重性速查

| # | 冲突 | 严重性 | 影响范围 | 建议动作 |
|---|------|:--:|------|------|
| B.1 | No auto-write vs T2 auto-retain | 🔴 CRITICAL | Governance 基础 | 决议后再行动 |
| B.2 | Procedural confidence 阈值不一致 | ⚠️ MEDIUM | Procedural memory | 统一到单一阈值 |
| B.3 | Lifecycle 重组 | 🟡 MINOR | 文档组织 | 接受，注明映射 |
| B.4 | External provider 缺失 | 🟡 MINOR | 未来 scope | 归档 D5 |
| E.1 | Phase 编号不一致 | 🟡 MINOR | 路线图 | 显式选择新体系 |
| E.2 | 术语演变 (Adjudication/Retain) | 🟡 MINOR | 可读性 | 统一术语表 |

# Memory Taxonomy Mapping to MEM-2

**日期**: 2026-06-14
**性质**: docs-only taxonomy mapping，不实现 memory，不解冻 memory
**触发**: T-MEM2 (BLOCKED_BY_DECISION)
**Architecture Repair Mainline**: CLOSED

## 1. Status

- Architecture Repair Mainline: **CLOSED**。
- Memory maturity: **L2**（不是 L1，不是 L3）。
- Trigger: **T-MEM2**（`BLOCKED_BY_DECISION`）。
- 本文是 user taxonomy → current implementation mapping，不是 active queue。
- 本轮不改 `agent/` 源码，不改 `tests/`，不新增 memory backend。

## 2. Two Axes: Source vs Type

用户的三类 memory 设计事实上横跨**两个正交维度**。混淆这两个维度会导致错误的架构决策。

### 轴 1: Memory Source（记忆来源——谁提出记忆）

| Source | 含义 | 代码证据 |
|--------|------|----------|
| `explicit_user_request` | 用户主动说 "remember X" / "记住 X" | `agent/memory_store.py:10` — `source_type` 默认值 |
| `agent_suggested` | Agent/模型自动提出记忆建议 | `agent/memory_store.py:10` — schema 已定义，未启用 |
| `reflection` | Agent 自我反思后提出记忆 | `agent/memory_store.py:10` — schema 已定义，未启用 |
| `imported` | 外部导入（文件、会话迁移） | `agent/memory_store.py:10` — schema 已定义，未启用 |

### 轴 2: Memory Type（记忆类型——记的是什么）

| Type | 含义 | 代码证据 |
|------|------|----------|
| `semantic` | 语义记忆——用户的偏好、知识、事实 | `agent/memory_store.py:9` — 默认值 |
| `episodic` | 情境记忆——用户在某次交互中的事件/场景 | `agent/memory_consolidation_loader.py:86-87` — 只加载 episodic 供 consolidation |
| `procedural` | 程序性记忆——用户的行为规则/约束 | `agent/memory_emergence.py:3` — emergence 产生 procedural candidate |

### 关键不变量

**Memory Source ≠ Memory Type。** 用户主动说的也可以是 episodic 事实；Agent 推断的也可以是 semantic 偏好。MEM-2 决策必须同时处理 source × type 的交互，而不是把它们当成一个维度。

## 3. Current Memory Capability Inventory

### 3.1 Schema（已存在）

```python
# agent/memory_store.py:59-86 — MemoryRecord
memory_type: str = "semantic"        # episodic / semantic / procedural
source_type: str = "explicit_user_request"  # / agent_suggested / reflection / imported
approval_status: str = "approved"    # pending / approved / rejected / edited
scope: MemoryScope                  # USER / PROJECT / SESSION
sensitive_redacted: bool = False
content: str                        # actual memory content
audit_id: str                       # audit trail
```

```python
# agent/memory_operations.py:57-58 — MemoryCandidate metadata
memory_type: str = "semantic"
source_type: str = "explicit_user_request"
```

### 3.2 Write paths（已存在）

| Path | Status | Source | Type |
|------|--------|--------|------|
| Explicit retain (`evaluate_user_text`) | ✓ Active | explicit_user_request | semantic (default) |
| Consolidation (episodic → semantic) | Frozen, env-gated | agent_suggested (candidate) | semantic |
| Emergence (procedural) | Disabled, env-gated | agent_suggested (candidate) | procedural |

### 3.3 Read paths（已存在）

| Path | Status |
|------|--------|
| Recall by ID / keyword | ✓ Active |
| Full context injection | ✓ Active |
| Semantic search / embedding | ✗ Not implemented |

### 3.4 Mutation paths

| Operation | Status |
|-----------|--------|
| Retain (create) | ✓ Active with confirmation |
| Forget (soft delete) | ✓ Active |
| Update | ✗ Not implemented (enum exists) |
| Noop | ✗ Not implemented (enum exists) |
| Hard delete | ✗ Not implemented |

## 4. Mapping Table

### 映射 1: 用户主动让 Agent 记忆

| Dimension | Value |
|-----------|-------|
| User description | "用户主动让通用 Agent 记忆" |
| Memory source | `explicit_user_request` |
| Memory type | `semantic` (default)，可以是 `episodic`（取决于 content） |
| Code evidence | `agent/memory_runtime.py` — `evaluate_user_text()` → retain path |
| Test evidence | `tests/test_memory_runtime_integration.py` — "remember that X" detection |
| Golden evidence | `tests/golden_e2e/test_golden_memory_checkpoint.py` |
| Current maturity | **L2** — production-active, confirmation-gated |
| Write authority | `memory_policy.DeterministicMemoryPolicy` → `MemoryFsStore` |
| Schema needed | Current `source_type=explicit_user_request` sufficient |
| Lifecycle needed | Proposed → Confirmed → Stored → (soft) Forgotten |
| Privacy risk | Low — explicit user intent, confirmation-gated, sensitive-content-blocked |
| Delete/update/noop | Forget ✓, Update ✗, Noop ✗ |
| Activation path | Already active — no activation needed |
| Gap to L3 | Add noop (same-content deduplication) |

### 映射 2: Agent 情绪/信号触发记忆

| Dimension | Value |
|-----------|-------|
| User description | "通用 Agent 感受到用户情绪波动或其他信号，然后形成记忆" |
| Memory source | `agent_suggested` / `reflection` |
| Memory type | `semantic` 或 `episodic`（取决于触发信号） |
| Code evidence | **None**。没有情绪检测、信号检测、agent-inferred-memory creation 代码路径 |
| Test evidence | **None** |
| Golden evidence | Not applicable |
| Current maturity | **L0** — 纯概念，无代码路径 |
| Write authority | 不存在——当前只有 `explicit_user_request` 路径可以产生写操作 |
| Schema needed | `source_type=agent_suggested` + 信号来源 metadata |
| Lifecycle needed | Signal candidate → Pending review → (approved/rejected) → Stored |
| Privacy risk | **High** — 如果实现，必须通过 policy gate + confirmation gate，不能 silent |
| Delete/update/noop | 全缺 |
| Activation path | 需要：1) signal/emotion detection module；2) MemoryOwner 裁决；3) T1 human confirmation；4) policy gate |
| Gap to L3 | **不适用于 L3**。这是 L4 能力（概念性需求），应先有 MemoryOwner + T1 gate |

### 映射 3: Episodic Memory（情境记忆）

| Dimension | Value |
|-----------|-------|
| User description | "隐性记忆——情境记忆" |
| Memory source | `explicit_user_request` 或 `agent_suggested` |
| Memory type | `episodic` |
| Code evidence | `agent/memory_consolidation_loader.py:86-88` — consolidation 只加载 `memory_type=episodic` 的记录。Episodic records 可被 produce（via explicit retain with `memory_type=episodic`），但没有独立的 episodic ingestion pipeline |
| Test evidence | `tests/test_memory_consolidation_loader.py` — load_episodic_evidence |
| Golden evidence | `memory_disabled.json` — consolidation frozen |
| Current maturity | **L1-L2** — schema 已定义，consolidation 可消费 episodic，但：<br>- 没有独立的 episodic 创建路径（只能通过 explicit retain + 手动设置 memory_type）<br>- 没有 automatic episodic recording（session-level event logging 不算 episodic memory）<br>- Consolidation 是 frozen/env-gated，不产生效果 |
| Write authority | `MemoryFsStore`（如果被标记为 episodic 的 record 被 retain） |
| Schema needed | `memory_type=episodic` 已存在于 schema 中 |
| Lifecycle needed | Episodic → (consolidation) → semantic / (decay) → archived |
| Privacy risk | Medium — episodic records 可能包含敏感内容；当前 sensitive-content-blocked 已覆盖 |
| Delete/update/noop | Same as semantic — Forget ✓, Update ✗, Noop ✗ |
| Activation path | 当 consolidation unfreeze 时，episodic path 自动可用 |
| Gap to L3 | 1) Automatic episodic recording<br>2) Consolidation unfreeze + safety hardening<br>3) Episodic decay/expiration policy |

### 映射 4: Semantic Memory（语义记忆）

| Dimension | Value |
|-----------|-------|
| User description | "隐性记忆——语义记忆" |
| Memory source | `explicit_user_request`（当前）或 `agent_suggested`（未来） |
| Memory type | `semantic`（默认） |
| Code evidence | **Primary implementation**。`memory_type=semantic` 是当前唯一活跃的 memory type。<br>`memory_operations.py:57` — 默认 memory_type<br>`memory_consolidation_pipeline.py:53` — 只接受 semantic candidate<br>`memory_consolidation_engine.py` — episodic→semantic via pattern detection |
| Test evidence | ~30+ tests across consolidation, extraction, store, policy |
| Golden evidence | `memory_disabled.json` — consolidation frozen (semantic consolidation 受影响) |
| Current maturity | **L2** — explicit retain 路径活跃；consolidation 路径 frozen/env-gated |
| Write authority | `DeterministicMemoryPolicy` → `MemoryFsStore`（explicit）<br>Consolidation pipeline (frozen, T1-only) |
| Schema needed | Current `memory_type=semantic` sufficient |
| Lifecycle needed | Proposed → Pending → Approved → Stored → (consolidation) → Updated → (decay) → Archived |
| Privacy risk | Low — 当前只存储用户主动提供的内容，policy gate 阻止 sensitive |
| Delete/update/noop | Forget ✓, Update ✗, Noop ✗ |
| Activation path | 当前 explicit retain 已激活。Consolidation 路径需要 OD-4 + safety hardening |
| Gap to L3 | 1) Update semantics<br>2) Noop (deduplication)<br>3) Canonical MemoryOwner<br>4) Consolidation unfreeze with safety hardening |

### 映射 5: Procedural Memory（程序性记忆）

| Dimension | Value |
|-----------|-------|
| User description | "隐性记忆——程序性记忆" |
| Memory source | `agent_suggested`（via emergence detection） |
| Memory type | `procedural` |
| Code evidence | `agent/memory_emergence.py` — emergence pipeline (disabled, env-gated)<br>`agent/memory_emergence.py:3` — "semantic + episodic + repeated correction → procedural candidate"<br>`agent/memory_consolidation_engine.py:56-64` — procedural-like patterns are **excluded** from semantic consolidation |
| Test evidence | `tests/test_memory_emergence.py` — emergence detection tests |
| Golden evidence | `memory_disabled.json` — emergence disabled |
| Current maturity | **L1** — code exists, disabled, env-gated, never used in production |
| Write authority | `dispatch_procedural_candidates_to_pending_review()` — T1 human confirmation only, never auto-approve |
| Schema needed | `memory_type=procedural` 已存在于 schema |
| Lifecycle needed | Correction detected → Procedural candidate → Pending review → (accepted/rejected) → Stored procedural → (applied to tool behavior) |
| Privacy risk | **High** — procedural memory 会直接影响 Agent 行为，错误或恶意的 procedural memory 可能导致 Agent 行为异常。当前通过 T1 human confirmation + disabled-by-env 保护 |
| Delete/update/noop | 全缺 |
| Activation path | 需要：1) MemoryOwner；2) Emergence unfreeze；3) Procedural adoption mechanism（如何 apply procedural memory 到 actual behavior）；4) Rollback/undo mechanism |
| Gap to L3 | **不适用于 L3**。Procedural memory 是 L4+ 能力——需要完整的 sandbox + safety boundary + human oversight |

## 5. What Is Already Implemented

| Capability | Evidence |
|------------|----------|
| MemoryRecord schema with memory_type + source_type | `agent/memory_store.py:59-86` |
| Explicit retain ("remember X") with confirmation flow | `agent/memory_runtime.py` |
| Forget (soft delete) | `agent/memory_runtime.py` |
| Policy gate (DeterministicMemoryPolicy) | `agent/memory_policy.py` |
| Sensitive content blocking | `agent/memory_extraction.py` — `_contains_sensitive` |
| Privacy masking in display | `agent/display_events.py` |
| Audit trail (audit_summary + evidence_recorder) | `agent/memory_operations.py` |
| Golden test locking frozen/disabled state | `tests/golden_e2e/fixtures/memory_disabled.json` |
| Skill memory boundary | `agent/skill_system/memory_boundary.py` |
| SubAgent memory boundary | `agent/subagent_system/memory_boundary.py` |
| Filesystem storage | `agent/memory_fs_store.py` |
| Consolidation engine (frozen) | `agent/memory_consolidation_engine.py` |
| Emergence detection (disabled) | `agent/memory_emergence.py` |
| L3 tests for recall/propose/shared_store | `tests/runtime_integration/test_memory_*_l3.py` |

## 6. What Is Partially Implemented

| Capability | Status | Blocker |
|------------|--------|---------|
| Consolidation (episodic → semantic) | Code exists, frozen, env-gated | OD-4 (owner decision) + safety hardening |
| Emergence (procedural) | Code exists, disabled, env-gated | OD-4 + MemoryOwner + procedural adoption |
| Multiple source_types (agent_suggested, reflection, imported) | Schema defined, code path not active | No agent-inferred memory creation path |
| Multiple memory_types (episodic, procedural) | Schema defined, episodic used by consolidation, procedural by emergence | Both pipelines frozen/disabled |
| MemoryOperationType.UPDATE | Enum exists | Not implemented |
| MemoryOperationType.NO_OP | Enum exists | Not implemented |

## 7. What Is Conceptual / Not Productionized

| User Concept | Code Status | Reason |
|--------------|-------------|--------|
| Agent 感受用户情绪后形成记忆 | **No code** | No emotion/sentiment/signal detection module |
| Agent 自动推断用户偏好 (agent-inferred) | **Schema only** | source_type=agent_suggested 已定义，无 creation path |
| 隐性记忆（不同于显式命令） | **Partial** | Consolidation (episodic→semantic) = frozen; Emergence (procedural) = disabled |
| Procedural memory 实际生效 | **No code** | No procedural adoption mechanism for tool behavior |
| Semantic search / embedding memory | **No code** | Current retrieval is keyword-based only |

## 8. MemoryOwner Meaning

### Current state

当前没有 canonical MemoryOwner。写操作分散在：
- `memory_runtime.py` — explicit retain 入口
- `memory_runtime_hooks.py` — session-end consolidation/emergence
- `memory_policy.py` — gate keeper
- `memory_fs_store.py` — 实际持久化

### MemoryOwner definition

**MemoryOwner 是 runtime decision authority，决定 memory mutation 是否发生。**

It is:
- ✅ A runtime abstraction layer that ALL memory mutations must pass through
- ✅ The single point that decides create/update/delete/noop
- ✅ The enforcer of policy gate + privacy check + evidence log
- ✅ The authority that holds the write lock

It is NOT:
- ❌ A human user or project owner
- ❌ A storage backend (MemoryFsStore is storage, not owner)
- ❌ An LLM or model
- ❌ A policy gate (DeterministicMemoryPolicy is a gate, not an owner)
- ❌ A consolidation/emergence pipeline (those are consumers)

### MemoryOwner role in this taxonomy

| Memory source | MemoryOwner role |
|---------------|-----------------|
| explicit_user_request | User 提出 → policy gate → MemoryOwner 裁决 → write/update/noop |
| agent_suggested | Model/Agent 只能 propose candidate → policy gate → MemoryOwner 裁决 → accept to pending review / reject |
| episodic → semantic | Consolidation engine produces candidate → MemoryOwner 裁决 → T1 human review |
| procedural emergence | Emergence engine produces candidate → MemoryOwner 裁决 → T1 human review ONLY |

## 9. Gap to L3

### Why Memory is L2, not L1

Evidence:
- More than stub: has recall/retain/forget/audit/privacy/golden
- Has bounded runtime: explicit retain is active
- Has multiple L3-level tests (recall, propose, shared_store)
- Has schema, policy, confirmation, evidence system

### What's needed to reach L3

| Gap | Priority | Blocker |
|-----|----------|---------|
| Canonical MemoryOwner | **P2** | OD-9 (owner decision) |
| Noop semantics (deduplication) | P3 | MemoryOwner 完成后 |
| Update path (edit existing memory) | P3 | MemoryOwner 完成后 |
| Consolidation unfreeze | P2 | OD-4 (owner decision) |
| Emergence unfreeze | P2 | OD-4 + MemoryOwner |
| Production owner golden test | P2 | MemoryOwner 完成后 |
| Replay evidence (event sourcing) | P3 | L4 scope, not L3 |
| Agent-inferred memory creation path | P4 | L4 scope, after owner+safety |

### What does NOT block L3

- Semantic search / embedding — L4 能力
- Full event-sourcing replay — L4 能力
- Procedural memory adoption — L4+ 能力
- Emotion/signal detection — L4+ 概念需求
- Cross-session persistence — 可选增强

## 10. Recommended Next Decision

### Primary: OD-9 — approve MemoryOwner abstraction

MemoryOwner 是最关键的 MEM-2 decision。其他所有增强（update/noop/consolidation unfreeze）都依赖于它。

如果 OD-9 批准：
1. 实现 `MemoryOwner` as single write authority
2. Write single-owner golden test
3. 然后按需 unfreeze consolidation (OD-4) 和 emergence

### Secondary: OD-4 — consolidate as default production?

建议保持 consolidation off。先有 MemoryOwner + safety hardening，再决定 default-on。

## 11. Do Not Do Yet

- Do not implement MemoryOwner before OD-9 approval
- Do not unfreeze memory consolidation/emergence
- Do not default-on memory
- Do not allow model direct memory persistence
- Do not implement emotion/signal/agent-inferred memory before MemoryOwner
- Do not implement semantic search/embedding backend before owner/schema approved
- Do not implement procedural memory adoption before safety boundary
- Do not claim L3 or production memory readiness
- Do not claim "三类 memory 已支持"
- Do not confuse schema definition (has field) with runtime activation (default-on)

## 12. Evidence Appendix

### Source
- `agent/memory_store.py:59-86` — MemoryRecord schema (memory_type, source_type, approval_status)
- `agent/memory_operations.py:55-58` — MemoryCandidate 默认值
- `agent/memory_runtime.py` — explicit retain 核心路径
- `agent/memory_runtime_hooks.py:33/152` — consolidation/emergence env gates
- `agent/memory_policy.py:86` — DeterministicMemoryPolicy
- `agent/memory_consolidation_engine.py:1-7` — episodic→semantic，frozen
- `agent/memory_emergence.py:1-33` — procedural emergence，disabled
- `agent/memory_consolidation_loader.py:86-88` — 只加载 episodic
- `agent/memory_consolidation_pipeline.py:53-54` — 只接受 semantic candidate
- `agent/memory_extraction.py` — NL extraction + sensitive content detection
- `agent/skill_system/memory_boundary.py` — Skill → Memory boundary
- `agent/subagent_system/memory_boundary.py` — SubAgent → Memory boundary

### Tests/Golden
- `tests/golden_e2e/test_golden_memory_checkpoint.py`
- `tests/golden_e2e/fixtures/memory_disabled.json`
- `tests/runtime_integration/test_memory_recall_l3.py`
- `tests/runtime_integration/test_memory_propose_l3.py`
- `tests/runtime_integration/test_memory_shared_store_l3.py`
- `tests/test_memory_consolidation_engine.py`
- `tests/test_memory_consolidation_loader.py`
- `tests/test_memory_emergence.py`

### Docs
- `docs/07-module-maturity/MEMORY_OWNER_DECISION_SPIKE.zh.md`
- `docs/07-module-maturity/AGENT_MODULE_MATURITY_AUDIT.zh.md` §5.5
- `docs/07-module-maturity/POST_REPAIR_TRIGGER_REGISTRY.zh.md` §4
- `docs/CAPABILITY_BOUNDARIES.md` — Memory frozen/env-gated
- `docs/rfc/MEMORY_CANONICAL_RFC.md`

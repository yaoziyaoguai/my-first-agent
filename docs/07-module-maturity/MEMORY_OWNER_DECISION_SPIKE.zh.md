# MEM-2 Memory Owner Decision Spike

**日期**: 2026-06-14
**性质**: docs-only decision spike，不实现 memory，不解冻 memory
**触发**: T-MEM2 (BLOCKED_BY_DECISION)
**Architecture Repair Mainline**: CLOSED

## 1. Status

- Architecture Repair Mainline: **CLOSED**。
- Trigger: **T-MEM2**。
- Current category: **BLOCKED_BY_DECISION**。
- 本文是 decision spike，不是 implementation plan，不是 active queue item。
- **Taxonomy mapping**: 见 `MEMORY_TAXONOMY_MAPPING.zh.md`——将用户三类 memory（explicit/agent-inferred/implicit × episodic/semantic/procedural）映射到当前实现。
- 本轮不改 `agent/` 源码，不改 `tests/`，不新增 memory backend，不解冻 memory。
- Memory 当前成熟度：**L3**（explicit_user_request/semantic retain-create-noop-reject runtime main path），不宣称 production-ready、不宣称 L4。MemoryOwner wired into MemoryRuntime.resolve_confirmation（commit `c41a67a`）。

## 2. Current Memory Inventory

### 2.1 源码（agent/）

| 文件 | 角色 |
|------|------|
| `agent/memory.py` | Extraction/domain 入口(薄层，已压缩) |
| `agent/memory_runtime.py` | 核心运行时 — explicit retain 最小闭环 |
| `agent/memory_runtime_hooks.py` | Session-end consolidation/emergence orchestration |
| `agent/memory_policy.py` | DeterministicMemoryPolicy — 所有 memory decision 的单一 gate |
| `agent/memory_fs_store.py` | Filesystem-based memory store(JSON files) |
| `agent/memory_store.py` | InMemoryMemoryStore + MemoryStoreProtocol |
| `agent/memory_operations.py` | MemoryOperationIntent + audit summary |
| `agent/memory_contracts.py` | MemoryDecision / MemorySnapshot / MemoryRecord 数据结构 |
| `agent/memory_confirmation.py` | Interactive confirmation 请求/结果 |
| `agent/memory_snapshot_generator.py` | 从 store 生成 memory snapshot |
| `agent/memory_consolidation_pipeline.py` | Consolidation pipeline(默认 off) |
| `agent/memory_consolidation_engine.py` | Consolidation engine (keyword/topic/pattern detection) |
| `agent/memory_consolidation_llm.py` | LLM-based consolidation generator(默认 off) |
| `agent/memory_consolidation_loader.py` | 加载 episodic evidence 供 consolidation |
| `agent/memory_consolidation_review.py` | Dispatch consolidation candidates 到 pending review |
| `agent/memory_consolidation.py` | Consolidation 聚合入口 |
| `agent/memory_emergence.py` | Emergence pipeline(默认 off) |
| `agent/memory_extraction.py` | 自然语言 extraction + sensitive content detection |
| `agent/memory_extraction_bridge.py` | Extraction ↔ store bridge |
| `agent/memory_extraction_review.py` | Extraction review |
| `agent/memory_interaction.py` | User-facing memory interaction |
| `agent/memory_index.py` | Memory index |
| `agent/memory_l2.py` | L2 memory integration |
| `agent/memory_provider.py` | LLM-based memory provider adapter |
| `agent/memory_review.py` | Memory review UI/CLI helpers |
| `agent/memory_suggestions.py` | Memory suggestion 策略 |
| `agent/memory_archive.py` | Memory 归档 |
| `agent/memory_maintenance_cli.py` | CLI maintenance tools |
| `agent/memory_confirmation_forms.py` | Confirmation forms |

**Runtime integration handlers:**
| `agent/runtime_integration/memory_hook.py` | MemoryTurnEndProposalHandler |
| `agent/runtime_integration/memory_recall.py` | Memory recall handler |
| `agent/runtime_integration/memory_retain.py` | Memory retain handler |
| `agent/runtime_integration/memory_forget.py` | Memory forget handler |
| `agent/runtime_integration/memory_consolidate.py` | Memory consolidate handler |

**Subsystem boundaries:**
| `agent/skill_system/memory_boundary.py` | Skill → Memory 边界 |
| `agent/subagent_system/memory_boundary.py` | SubAgent → Memory 边界 |
| `agent/tools/memory.py` | Memory tool (user-facing) |

### 2.2 测试

超过 60 个 memory 相关测试文件，覆盖：
- `tests/golden_e2e/test_golden_memory_checkpoint.py` — golden 锁定当前 frozen/disabled 事实
- `tests/runtime_integration/test_memory_recall_l3.py` — L3 recall 测试
- `tests/runtime_integration/test_memory_propose_l3.py` — L3 propose 测试
- `tests/runtime_integration/test_memory_shared_store_l3.py` — L3 shared store 测试
- `tests/runtime_integration/test_memory_anchor_fake.py` — fake provider 下 memory anchor
- `tests/runtime_integration/test_memory_anchor_real.py` — real provider 下 memory anchor(opt-in)
- `tests/test_memory_fs_store.py` — 文件系统 store 测试
- `tests/test_memory_policy.py` — 策略测试
- `tests/test_memory_consolidation_engine.py` — consolidation engine 测试
- `tests/test_memory_extraction.py` — extraction 测试
- 以及 40+ 其他测试

### 2.3 Golden fixture

**`tests/golden_e2e/fixtures/memory_disabled.json`**:
```json
{
  "consolidation": {"state": "frozen_env_gated", "module_frozen": true, "enabled": false},
  "emergence": {"state": "disabled_by_env", "enabled": false}
}
```

### 2.4 Gateway flags

| Flag | 默认值 | 作用 |
|------|--------|------|
| `MEMORY_CONSOLIDATION_ENABLED` | `off` (空或非 1/true/yes) | 控制 consolidation pipeline |
| `MEMORY_CONSOLIDATION_DRY_RUN` | `off` | consolidation 试运行模式 |
| `MEMORY_EMERGENCE_ENABLED` | `off` | 控制 emergence pipeline |

### 2.5 当前能力矩阵

| 能力 | 是否存在 | 是否默认启用 | Evidence |
|------|----------|-------------|----------|
| Read (recall) | ✓ | ✓ | `test_memory_recall_l3.py` |
| Write (retain) | ✓ | ✓ | explicit retain + confirmation flow |
| Update | ✗ | — | 无 update path |
| Delete (forget) | ✓ | ✓ | `test_memory_forget_l2.py` |
| Noop semantics | ✗ | — | 未定义 noop |
| Audit trail | ✓ | — | `memory_operations.py audit_summary` |
| Replay evidence | △ | — | checkpoint restore 有，完整 replay 无 |
| Privacy masking | ✓ | ✓ | sensitive content detection + 脱敏 |
| Consolidation | ✓ | ✗ (frozen) | `test_memory_consolidation_pipeline.py` |
| Emergence | ✓ | ✗ | `test_memory_emergence.py` |
| Golden lock | ✓ | ✓ | `memory_disabled.json` |

## 3. Current Evidence

### 3.1 生产路径

当前 memory 核心路径是 **explicit retain**（用户说 "remember X"）：
1. `memory_runtime.evaluate_user_text()` → detect intent
2. `memory_policy.DeterministicMemoryPolicy` → BLOCK if sensitive / REJECT if unknown
3. Memory confirmation flow → `CONFIRMATION_REQUIRED`
4. 用户确认 → `STORED` → `memory_fs_store` 写入
5. Recall: `memory_recall` handler → `memory_store.list_records()` → 注入 context

### 3.2 架构边界（来自 `memory.py` docstring）

- Memory kernel 不 import checkpoint、MCP、provider adapter 或 tool_executor
- 所有依赖可注入(policy / store / event logger)
- Memory 通过 runtime integration handler 挂入 dispatcher spine
- Memory 与 provider/tool/skill/subagent 有显式 boundary 文件

### 3.3 North Star 目标（§10）

North Star §4.D / §10.1 要求：
- Memory 有 **单一 canonical write owner**
- Memory 经过 **policy gate**
- Memory 有 **provenance + lifecycle**
- 当前 `Open:` canonical owner 待定

### 3.4 当前已知 gap（来自 maturity audit §5.5）

- MEM-2: canonical write owner 未定
- OD-4: consolidation 是否为默认 production 路径未决定
- OD-9: memory canonical write owner 决策未做
- No update path（memory 不可编辑，只能 retain/delete）
- No noop semantics
- No full replay evidence
- Emergence pipeline 未启用

## 4. Decision Frame

### 4.1 Memory Owner

**Current fact**: 当前没有单一 canonical write owner。写操作分散在：
- `memory_runtime.py` — explicit retain 入口
- `memory_runtime_hooks.py` — session-end consolidation/emergence
- `memory_policy.py` — gate keeper
- `memory_fs_store.py` — 实际持久化

**Decision needed**: 谁是唯一的 canonical memory write owner？

**Options**:
A. `MemoryRuntime` — 作为核心运行时负责所有写操作调度
B. `DeterministicMemoryPolicy` — 作为 gate keeper + write owner
C. `MemoryFsStore` — 作为持久化层 owner，上层只能通过它写入
D. 新 `MemoryOwner` 抽象层 — 单一入口，内部分发到 policy/store/hooks

**Recommended**: **D. 新 `MemoryOwner` 抽象层**。
- Why: 当前写路径分散(runtime、hooks、policy 都有写权限)，长久会产生双 owner
- Risk: 新增抽象层增加代码量；但 L2→L3 提升需要
- Required evidence: single-owner test
- Activation trigger: owner 决策批准
- Exit criteria: 所有 memory 写操作都经过 MemoryOwner

### 4.2 Memory Schema

**Current fact**: `MemoryRecord` 有 `memory_type`(semantic/episodic/procedural)、`source_type`(explicit_user_request/agent_suggested/reflection/imported)、`approval_status`(pending/approved/rejected/edited)。Schema 已存在但 `memory_type` 和 `source_type` 在实践中未充分使用（当前主要是 explicit_user_request + pending→approved）。

**Decision needed**: 是否需要 canonical schema + immutable record ID？

**Options**:
A. 当前 schema 足够 — 不扩展
B. 固化 schema 为 canonical immutable，新增 `updated_at`/`deleted_at` 字段

**Recommended**: **A + 微调**。当前 schema 结构合理，不需要大改。需要加 `updated_at`、`deleted_at` 字段支持 soft delete 和 update audit。Record ID 已通过 `derive_memory_record_id` 生成，保持。

### 4.3 Memory Lifecycle

**Current fact**: 记录只有 create (retain) 和 soft delete (forget)。无 hard delete、无 update、无 expire/decay。

**Decision needed**: Memory lifecycle 应该包含哪些阶段？

**Options**:
A. Minimal: proposed → confirmed → stored → forgotten(soft-delete)
B. Full: proposed → pending_review → approved/rejected → stored → updated → expired → archived → deleted

**Recommended**: **A. Minimal**。
- Why: 当前只有 explicit retain 路径。过度的 lifecycle 在没有 consolidation/emergence 投入使用前是投机设计。
- Risk: 如果后续需要 update/expire/archive，需要 migration
- Activation trigger: consolidation/emergence 解冻时评估升级到 B

### 4.4 Write/Update/Delete/Noop Semantics

**Current fact**:
- Write: `retain` 带 confirmation
- Delete: `forget` (soft，mark deleted)
- Update: 不存在
- Noop: 不存在

**Decision needed**: Update 和 Noop 是否需要实现？

**Recommended**: 
- **Update**: 暂不实现。Explicit retain 的语义是 "remember that X"，重复 retain 同一 key 已隐式达成 update。需要显式 update 的场景（"update my OpenAI key from X to Y"）是特殊 case，且与 privacy 冲突。
- **Noop**: 需要实现。当用户说 "remember that X" 但 X 已在 memory 中且内容相同时，应返回 noop 而非 duplicate write。
- **Idempotent write**: 相同 content hash 的重复 retain 应为 noop。

### 4.5 Privacy Boundary

**Current fact**: 
- `memory_policy.py` 的 `BLOCKED` 机制阻止了显式的 API key / secret 写入
- `memory_extraction.py` 的 `_contains_sensitive` 检测敏感模式
- Memory 不包含 user 身份关联（无 user_id）

**Decision needed**: Memory privacy 应该达到什么级别？

**Options**:
A. 当前级别足够 — 仅 block 明显 secret pattern
B. Strict: 所有 memory content 在存储前脱敏 + 不存 PII + session-scoped only

**Recommended**: **A + 改进**。
- 当前 `sk-*` pattern blocking 已经有效
- 需要增加的：在 `redacted_summary` 中标记哪些 memory record 包含被脱敏的内容
- 不存 PII 原则应在文档中明确，由 policy gate 强制执行
- Session-scoping: memory 目前已经是 per-run/per-session(由 MemoryStore 的 session scope 决定)

### 4.6 Audit and Replay Evidence

**Current fact**:
- `memory_operations.py` 有 `build_memory_audit_summary`
- `evidence_recorder.py` 有 `record_memory_runtime_event`
- Checkpoint 可 restore memory 状态
- 但**无完整 replay**——没有 "从空 store 重放所有 memory 事件还原当前状态" 的机制

**Decision needed**: 是否需要 full replay evidence？

**Recommended**: **Not now**。当前 store 是文件系统 JSON line，可以从文件内容重建状态。Full event-sourcing replay 是 L4 需求，当前 L2 不需要。

### 4.7 Storage/Backend

**Current fact**: `memory_fs_store.py` + `InMemoryMemoryStore`。文件系统存储，JSON line 格式。

**Decision needed**: 是否需要更换 backend？

**Recommended**: **No**。当前文件系统 backend 满足 L2 需求。如果需要 SQLite/remote backend，由 `MemoryStoreProtocol` 接口支持注入。

### 4.8 Retrieval/Read Path

**Current fact**: `memory_recall` handler → `store.list_records()` → 过滤 deleted → 注入 context。Recall 是 explicit turn-start injection。

**Decision needed**: 是否需要 semantic search / RAG？

**Recommended**: **Not now**。当前全量 recall + context injection 满足 explicit retain 场景。Semantic search 需要 embedding provider，引入新的 provider/credential 依赖。

### 4.9 Provider / Tool / Skill / SubAgent Boundary

**Current fact**: 已有显式 boundary 文件：
- `agent/skill_system/memory_boundary.py`
- `agent/subagent_system/memory_boundary.py`
- `agent/tools/memory.py`（user-facing memory tool）

Memory 不直接调用 provider。Consolidation 使用 `memory_consolidation_llm.py` 中的 LLM generator（通过 fake provider，仅 dry_run）。

**Decision needed**: 这些 boundary 是否足够？

**Recommended**: **Yes**。当前 boundary 清晰：
- Tool 可以触发 memory recall（通过 `memory` tool）
- Skill 可以通过 `memory_boundary` 注入 memory context
- SubAgent 可以通过 `memory_boundary` 访问 memory context，但不能写入父 memory
- Provider 不直接读写 memory——memory 由 runtime 控制

关键不变式：**Memory is system-owned, not model-owned**。模型可以 propose memory candidates（通过 tool use），但 runtime 决定是否 persist、何时 recall、是否 forget。

### 4.10 Policy / Approval Boundary

**Current fact**: `DeterministicMemoryPolicy` 是单一 gate。所有 memory 决策(write/recall/forget)都经过它。

**Decision needed**: Memory 是否需要独立的 production approval hook（类似 OD-7）？

**Recommended**: **No for now**。当前 confirmation flow（用户确认 → pending_review → approved）已足够。Production approval hook 是 OD-7 的范畴，不属于 MEM-2。

### 4.11 Testing / Golden Strategy

**Current fact**:
- Golden: `memory_disabled.json` 锁定当前 frozen/gated 状态
- L3 tests: recall、propose、shared_store、checkpoint_save_resume
- Adversarial: 未建立

**Decision needed**: 需要什么额外的测试？

**Recommended**: 
- Golden 当前已覆盖 disabled/consolidation 事实——足够
- 如果 MEM-2 owner 决策后实现 single-owner，需要 golden 锁定 single-owner invariant
- Adversarial memory tests(模型注入 "forget everything" / "remember fake_key") 暂不需要，属于 T-PROVIDER-ADVERSARIAL 范围

### 4.12 Activation / Default-On Strategy

**Current fact**: 所有 consolidation/emergence 默认 off。Explicit retain 默认可用但需要用户显式说 "remember X"。

**Decision needed**: 何时可以 default-on consolidation/emergence？

**Recommended**: 两个前提条件：
1. MEM-2 canonical owner 已确定并 single-owner golden locked
2. 安全 hardening: 确认 consolidation/emergence 不会 auto-approve、不会泄露 secret、不会 silent persist

在当前（owner 未定）下**禁止** default-on consolidation/emergence。

## 5. Recommended Decisions Summary

| # | Decision Domain | Recommended | Category |
|---|-----------------|-------------|----------|
| 1 | Memory Owner | New `MemoryOwner` abstraction layer | blocked_by_decision |
| 2 | Memory Schema | Current schema + `updated_at`/`deleted_at` | no_blocker |
| 3 | Memory Lifecycle | Minimal: proposed→confirmed→stored→forgotten | no_blocker |
| 4 | Write/Update/Delete/Noop | Add noop/idempotent write; defer update | no_blocker |
| 5 | Privacy Boundary | Current level + PII policy + redaction marker | no_blocker |
| 6 | Audit/Replay | Audit summary sufficient; full replay deferred | no_blocker |
| 7 | Storage/Backend | Keep filesystem; `MemoryStoreProtocol` for future | no_blocker |
| 8 | Retrieval/Read | Current; semantic search deferred | no_blocker |
| 9 | Provider/Tool/Skill/SubAgent Boundary | Current boundaries sufficient | no_blocker |
| 10 | Policy/Approval Boundary | Current confirmation flow sufficient | no_blocker |
| 11 | Testing/Golden | Add single-owner golden when owner decided | no_blocker |
| 12 | Activation/Default-On | Default-off until owner decided + safety hardened | blocked_by_decision |

## 6. Memory Mutation Semantics

### Write (retain)
- Trigger: 用户显式说 "remember X" 或 "记住 X"
- Detection: `extraction.extract_user_intent()`
- Policy: `DeterministicMemoryPolicy.evaluate()` — BLOCK if sensitive/secret, REJECT if unknown intent
- Confirmation: `CONFIRMATION_REQUIRED` — 用户确认后 approve
- Storage: `MemoryFsStore.record_memory_item()`
- Evidence: `record_memory_runtime_event()`

### Delete (forget)
- Trigger: 用户显式说 "forget X" 或 "忘记 X"
- Implementation: soft delete (mark `is_deleted=True`)
- Evidence: recorded

### Update (not implemented)
- 当前不可用
- 重复 retain 同一 key 隐式实现 update（但产生 duplicate records）

### Noop (not implemented)
- 当前不可用
- 建议: 当 retain intent 的 content hash 与已有记录相同时返回 noop

## 7. Privacy Boundary

### 7.1 当前隐私保护

1. **Sensitive content blocking**: `memory_policy.py` — BLOCK 包含 `sk-*`、`api_key`、`password` 等模式的 content
2. **No user identity**: Memory 不与 user_id 绑定
3. **Session scoping**: 由 `MemoryStore` 的 session scope 决定作用域
4. **No network transmission**: Memory 只在本地文件系统存储

### 7.2 建议隐私增强

1. PII policy: 明确标注 memory 不应存储 email、phone、address 等 PII
2. Redaction marker: 标记被脱敏的 content 片断
3. Audit log: 每个 memory mutation 产生可审计证据
4. Grace period: forget 操作应在 N 天后 hard delete（当前仅 soft delete）

## 8. Audit / Replay Evidence

### 8.1 当前审计

- `memory_operations.build_memory_audit_summary()` — 统计/all records/audit trail
- `evidence_recorder.record_memory_runtime_event()` — agent_log.jsonl 可追溯

### 8.2 当前 replay

- checkpoint: `checkpoint.py` 保存 memory snapshot，可 restore
- 无完整 event-sourcing replay

### 8.3 建议

- 当前 audit 对 L2 足够
- Full replay 是 L4 需求，当前不需要

## 9. Provider / Tool / Skill / SubAgent Boundary

### 9.1 现状

```
Provider → [不直接访问 memory]
Tool → memory tool (read/recall only, via memory_runtime)
Skill → skill_system/memory_boundary.py → recall context injection
SubAgent → subagent_system/memory_boundary.py → recall context injection
Runtime → memory_runtime.py → exclusive write owner
```

### 9.2 关键不变式

- **Memory is system-owned, not model-owned**。模型通过 tool use propose candidates，runtime 决定是否 persist。
- **Provider never directly reads or writes memory**。
- **SubAgent cannot write to parent memory**——只能读取。
- **Skill cannot write to memory**——只能通过 injection 读取 context。

## 10. Activation Path

### 10.1 Trigger 状态

- **T-MEM2 仍为 BLOCKED_BY_DECISION**。
- 本文档完成 decision spike，使 MEM-2 从"模糊 blocked"变为"明确决策问题 + 激活路径"。

### 10.2 激活顺序

1. Owner review decision spike → 批准/拒绝/修改推荐
2. 如果批准 MemoryOwner abstraction:
   a. 实现 `MemoryOwner` layer (single-write-owner)
   b. 写 single-owner golden test
   c. 不在此阶段实施 update/noop/consolidation unfreeze
3. 如果审批 OD-4 (consolidation as default production):
   a. 需要独立的 safety-hardening plan
   b. 需要 evidence: dry-run pass, no auto-approve, no secret leak

### 10.3 User/Owner 需要做的决策

- OD-9: 批准/拒绝 MemoryOwner 抽象层设计
- OD-4: 批准/拒绝 consolidation 作为默认 production 路径
- 是否需要 memory update 能力
- 是否需要 semantic search/RAG
- Privacy policy: 是否需要 hard delete timeline

## 11. Do Not Do Yet

- Do not unfreeze memory consolidation/emergence
- Do not default-on memory consolidation/emergence
- Do not let model directly persist memory
- Do not implement update/noop before owner decided
- Do not implement MemoryOwner abstraction before owner approval
- Do not add new backend(remote/SQLite) without owner decision
- Do not add semantic search/RAG without embedding provider decision
- Do not claim production memory readiness
- Do not claim L3/L4 maturity
- Do not make memory cross-session by default
- Do not add adversarial memory tests before owner+safety hardening

## 12. Open Questions For User / Owner

1. **OD-9**: 是否批准 MemoryOwner 抽象层作为 canonical write owner？（Recommended: Yes）
2. **OD-4**: Consolidation pipeline 是否应该成为默认 production 路径？（Recommended: No for now——先有 owner + safety hardening）
3. Memory 是否需要 update 能力？还是 explicit retain+overwrite 足够？
4. Memory 是否需要 semantic search/RAG？（Recommended: Not now）
5. Forget 操作是否需要 hard delete timeline？（Recommended: Soft delete 当前足够）
6. Memory 是否需要 cross-session persistence？（当前 per-run session scoped）
7. Memory privacy policy: 是否需要明确 PII 禁止列表？

## 13. Evidence Appendix

### Source
- `agent/memory.py`
- `agent/memory_runtime.py` — core runtime, explicit retain loop
- `agent/memory_runtime_hooks.py` — consolidation/emergence hooks (L33: MEMORY_CONSOLIDATION_ENABLED, L152: MEMORY_EMERGENCE_ENABLED)
- `agent/memory_policy.py` — DeterministicMemoryPolicy
- `agent/memory_fs_store.py` — filesystem storage
- `agent/memory_store.py` — MemoryStoreProtocol + InMemoryMemoryStore
- `agent/memory_operations.py` — audit summary
- `agent/memory_consolidation_pipeline.py` — consolidation (default off)
- `agent/memory_emergence.py` — emergence (default off)
- `agent/memory_extraction.py` — NL extraction + sensitive detection
- `agent/skill_system/memory_boundary.py`
- `agent/subagent_system/memory_boundary.py`
- `agent/tools/memory.py`
- `agent/runtime_integration/memory_hook.py`
- `agent/runtime_integration/memory_recall.py`
- `agent/runtime_integration/memory_retain.py`
- `agent/runtime_integration/memory_forget.py`

### Tests
- `tests/golden_e2e/test_golden_memory_checkpoint.py`
- `tests/golden_e2e/fixtures/memory_disabled.json`
- `tests/runtime_integration/test_memory_recall_l3.py`
- `tests/runtime_integration/test_memory_propose_l3.py`
- `tests/runtime_integration/test_memory_shared_store_l3.py`
- `tests/runtime_integration/test_memory_anchor_fake.py`
- `tests/runtime_integration/test_memory_anchor_real.py`
- `tests/test_memory_policy.py`
- `tests/test_memory_consolidation_engine.py`
- `tests/test_memory_extraction.py`
- `tests/test_memory_fs_store.py`
- ~60+ total memory test files

### Docs
- `docs/07-module-maturity/AGENT_MODULE_MATURITY_AUDIT.zh.md` §5.5 — Memory L2, BLOCKED_BY_DECISION
- `docs/07-module-maturity/POST_REPAIR_TRIGGER_REGISTRY.zh.md` §4 — T-MEM2 trigger
- `docs/CAPABILITY_BOUNDARIES.md` — Memory frozen/env-gated fact
- `docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md` §10/§4.D — Memory target
- `docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md` — MEM-2/OD-4/OD-9
- `docs/rfc/MEMORY_CANONICAL_RFC.md`

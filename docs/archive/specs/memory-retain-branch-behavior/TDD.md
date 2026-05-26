# TDD / Test Plan: Memory Retain Branch Behavior

Status: draft
Date: 2026-05-23
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
SPEC: [Memory Retain Branch Behavior SPEC](SPEC.md)

## 1. Branch Point 判断

1. **当前任务属于哪个 unified runtime flow branch point？**
   `memory.turn_end_proposal`（Contract §2, §3 已定义）。`retain` 是其下游
   execution behavior——`proposed` 产生 proposal，`retain` 在确认后写入 store。

2. **branch point 是否已存在？**
   是。`RuntimeActionType.MEMORY_TURN_END_PROPOSAL`（`schema.py:26`）已注册，
   `MemoryTurnEndProposalHandler`（`memory_hook.py`）已实现并返回
   `proposed` / `should_not_remember` / `no_action`。

   `RuntimeActionType.MEMORY_PROPOSE`（`schema.py:27`）也已定义，无 handler，
   可作为 retain 的挂载点。

3. **这是 branch behavior test，还是需要新增 branch point？**
   这是 branch behavior test。`retain` 是 memory proposal family 下的
   execution behavior（与 `proposed` 的 evaluation 互补）。

4. **是否需要新增 RuntimeActionType？**
   SPEC OQ#1 列出三个方案。本 TDD 不做最终选择——测试设计覆盖所有合理路径，
   具体方案在 Implementation Plan 阶段决策。

5. **是否需要新增 branch point？**
   不需要。不新增。不标记 blocked。

## 2. 测试分层策略

本轮 TDD 定义三层测试，按实现顺序排列：

| 层级 | 路径 | 最高分类 | 依赖 handler 实现？ | 本 TDD 阶段 |
|------|------|---------|-------------------|------------|
| L1: Handler Logic | handler 直接调用 | `subsystem_integration` | 是 | 全部实现 |
| L2: Harness Dispatcher | `dispatcher.route()` | `harness_runtime_e2e` | 是 | 全部实现 |
| L3: Real Core Loop | `dispatcher.route_from_runtime_loop()` | `real_core_loop_runtime_e2e` | 是 + loop 集成 | 测试设计完成，实现标记 DEFERRED |

与 tool.gate 阶段不同，memory retain 的 handler 尚未实现。L1/L2 测试将是
**真正的 TDD RED → GREEN 循环**——先写测试（RED，因 handler 未实现或功能缺失），
再实现 handler（GREEN）。

L3 层依赖于 handler 实现 + loop 集成（类似于 tool.gate 的
`LoopDependencies.tool_gate_tool_name` 模式）。如果 retain 通过 turn-end hook
触发，可能需要 `LoopDependencies` 新增字段。

## 3. SPEC OQ#1 的测试策略

SPEC OQ#1 列出三个方案。本 TDD 不预判最终选择，但测试设计遵循以下原则：

- 方案 A（扩展 `MemoryTurnEndProposalHandler`）：handler 在同一实例上接收
  confirmation context，区分 evaluation vs execution mode
- 方案 B（为 `MEMORY_PROPOSE` 注册新 handler）：独立 handler，接收已确认的
  proposal 并写入 store
- 方案 C（新增 `MEMORY_RETAIN`）：新增 RuntimeActionType + 独立 handler

无论哪个方案，以下测试断言不变：
- `disposition="retain"`，`stored=True`
- handler 调用 `MemoryStore.write()`
- 不自动 recall，不做 consolidation
- fake/real 共享 handler 逻辑，store backend 不同

测试命名和 setup 使用方案无关的描述（如 "retain handler"），在 Implementation
Plan 阶段映射到具体方案。

## 4. 确认：本轮不做什么

- 不实现 handler（本 TDD 只定义测试，实现在后续阶段）
- 不新增 RuntimeActionType（本 TDD 不做最终选择）
- 不修改 `MemoryTurnEndProposalHandler` proposal 逻辑
- 不修改 `DeterministicMemoryPolicy`
- 不修改 `MemoryStore` / `MemoryStoreProtocol`
- 不实现 Memory recall into context
- 不实现 background consolidation / emergence detection
- 不实现 T1/T2/T3 governance routing 变更
- 不实现 UI confirmation interaction
- 不新增 Anchor / capability milestone
- 不引入 Tool Args / Tool Result / Retry / Error Recovery / Multi Tool /
  MCP Tool / Skill / Checkpoint / Streaming / SubAgent
- 不调用真实 API / 不读取 .env / 不读取 memory/episodes/*.jsonl

## 5. 测试文件计划

**新增文件：** `tests/runtime_integration/test_memory_retain_branch_behavior.py`

**选择理由：**
- 与已有 `test_memory_anchor_fake.py`（memory proposal coverage）、
  `test_tool_branch_confirmation_required.py`（tool gate branch behavior）
  同目录、同模式
- `retain` 是 memory proposal family 的 execution behavior
- 复用 `_build_phase1_dispatcher_with_tool_gate()`（已注册
  MemoryTurnEndProposalHandler）和 `_SpyDispatcher`

**不修改已有文件。**

## 6. 测试矩阵

### 6.1 Phase A: Retain — Positive Path（L1/L2）

| ID | Test Name | Purpose | Level | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|-------|--------|-------------------|-----------|
| A1 | `test_retain_confirmed_proposal_writes_to_store` | 已确认 proposal → retain → store.write() 成功 | L1 | 构造 InMemoryMemoryStore；构造 handler；构造 request（`confirmation_result="accepted"`, `proposal_id=<valid>`, `candidate=<完整 MemoryCandidate>`） | handler.handle(request, context) | status=success, disposition=retain, stored=True, proposal_id 匹配, store_backend="in_memory", no_silent_retain=True | 不调用真实文件系统；不读取 .env；不调用外部 API |
| A2 | `test_retain_verified_proposal_in_store_after_write` | store.write() 后 proposal 可在 store 中查回 | L1 | 同 A1 | handler.handle → 从同一 store 读取 proposal_id | store 中存在该 record，content 与 candidate 一致 | store 不暴露内部存储路径 |
| A3 | `test_retain_preserves_proposal_metadata` | retain 的 evidence 包含完整 proposal 元数据 | L2 | 同 A1，通过 `dispatcher.route()` | dispatcher.route(request) | evidence 含 proposal_id, store_backend, stored_at, content_hash | metadata 不含 real filesystem path（in-memory 模式） |
| A4 | `test_retain_no_silent_retain_invariant` | retain 始终标记 non-silent | L1 | 同 A1 | handler.handle | no_silent_retain=True, auto_approved=False（除非 approval context 明确提供） | no_silent_retain 不为 False或缺失 |
| A5 | `test_retain_does_not_recall_into_context` | retain 不触发 recall/context injection | L1 | 同 A1 | handler.handle | evidence 不含 recalled_to_context, context_injection, 或 context_modified | 不修改 model context / messages |
| A6 | `test_retain_does_not_trigger_consolidation` | retain 不触发 background consolidation | L1 | 同 A1 | handler.handle | evidence 不含 consolidation_triggered, background_job | 不调用 consolidation pipeline |
| A7 | `test_retain_does_not_generate_new_memory` | retain 只写入已有 candidate，不隐式生成新 memory | L1 | 同 A1 | handler.handle | stored content 与 request 中的 candidate 完全一致 | 不调用 MemoryPolicy.decide()；不生成新 candidate |

### 6.2 Phase B: Negative / Boundary Paths（L1/L2）

| ID | Test Name | Purpose | Level | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|-------|--------|-------------------|-----------|
| B1 | `test_retain_rejected_proposal_not_stored` | confirmation_result=rejected → not_retained | L1 | 同 A1，但 `confirmation_result="rejected"` | handler.handle | status=success, disposition=not_retained, stored=False | store 中无该 proposal_id 的 record |
| B2 | `test_retain_nonexistent_proposal_id_rejected` | proposal_id 不存在 → rejected | L1 | 构造 handler；request 带 `proposal_id="nonexistent"` | handler.handle | status=rejected, disposition=rejected, rejection_reason 含 "not found" 或 "proposal" | store 无写入 |
| B3 | `test_retain_tampered_proposal_rejected` | proposal content 被篡改 → rejected | L1 | 构造 handler；request 带已修改 content（与 hash 不匹配） | handler.handle | status=rejected, disposition=rejected, rejection_reason 含 "tampered" 或 "hash" 或 "integrity" | 篡改后的 content 不写入 store |
| B4 | `test_retain_missing_confirmation_result_rejected` | 缺少 confirmation_result → rejected | L1 | 同 A1，但 request 不含 `confirmation_result` | handler.handle | status=rejected | 不假设默认 accept |
| B5 | `test_retain_missing_proposal_id_rejected` | 缺少 proposal_id → rejected | L1 | 同 A1，但 request 不含 `proposal_id` | handler.handle | status=rejected | 不假设默认 proposal |
| B6 | `test_retain_store_write_failure_returns_failed` | store.write() 抛出异常 → failed | L1 | 构造会 raise 的 store backend（如 disk full mock） | handler.handle | status=failed, stored=False, error 信息传播到 evidence | 不静默吞异常 |
| B7 | `test_retain_external_side_effects_false_for_inmemory_store` | InMemoryMemoryStore → external_side_effects=False | L1 | 同 A1，InMemoryMemoryStore | handler.handle | external_side_effects=False | — |

### 6.3 Phase C: Classification Boundaries（L2/L3）

| ID | Test Name | Purpose | Level | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|-------|--------|-------------------|-----------|
| C1 | `test_direct_handler_is_subsystem_integration` | 直接 handler 调用 → subsystem_integration | L1 | 直接构造 handler + context | handler.handle(request, context) | evidence_level ≤ subsystem_integration | evidence_level ≠ harness_runtime_e2e, ≠ real_core_loop_runtime_e2e |
| C2 | `test_direct_dispatcher_is_harness_not_real_core_loop` | `dispatcher.route()` → harness_runtime_e2e | L2 | 同 A3 | dispatcher.route(request) | evidence_level=harness_runtime_e2e, dispatcher_origin=direct_dispatcher | evidence_level ≠ real_core_loop_runtime_e2e |
| C3 | `test_route_from_runtime_loop_is_real_core_loop` | `route_from_runtime_loop()` → real_core_loop_runtime_e2e | L3 | **DEFERRED** — 依赖 handler 实现 + loop 集成 | dispatcher.route_from_runtime_loop(request) | evidence_level=real_core_loop_runtime_e2e, dispatcher_origin=runtime_loop, runtime_loop_invoked=True | — |
| C4 | `test_payload_cannot_upgrade_classification` | payload 中声称 real_core_loop 不能升级 direct dispatcher 分类 | L2 | 同 C2，但 payload 含 `runtime_loop_invoked=True`, `core_entrypoint="core.chat"` | dispatcher.route(request) | evidence_level=harness_runtime_e2e（不因 payload 升级） | 分类不依赖 payload 自述字段 |
| C5 | `test_direct_store_write_is_not_runtime_e2e` | 直接调用 MemoryStore.write() → 不是 runtime E2E | L1 | 直接构造 InMemoryMemoryStore，调用 write() | store.write(record) | 无 RuntimeAction evidence | 不能 claim harness_runtime_e2e 或 real_core_loop_runtime_e2e |
| C6 | `test_direct_policy_call_is_not_runtime_e2e` | 直接调用 DeterministicMemoryPolicy → 不是 runtime E2E | L1 | 直接调用 policy.decide() | policy.decide(text) | 无 RuntimeAction evidence | 不能 claim 任何 runtime E2E level |

### 6.4 Phase D: Fake/Real Store Adapter Boundary（L2）

| ID | Test Name | Purpose | Level | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|-------|--------|-------------------|-----------|
| D1 | `test_fake_inmemory_store_same_handler_logic` | fake (InMemoryMemoryStore) 与 real 共用同一 handler 逻辑 | L2 | 构造 dispatcher + InMemoryMemoryStore；request payload `provider_kind="fake"` | dispatcher.route(request) | disposition=retain, stored=True, store_backend="in_memory", external_side_effects=False, provider_kind=fake（metadata only） | provider_kind 不改变 retain 判定 |
| D2 | `test_filesystem_store_produces_external_side_effects` | FilesystemMemoryStore → external_side_effects=True | L2 | 同 D1，但使用 temp dir 上的 FilesystemMemoryStore | dispatcher.route(request) | disposition=retain, stored=True, store_backend="filesystem", external_side_effects=True | — |
| D3 | `test_fake_provider_no_real_episodes_read` | fake provider 不读取真实 memory episodes | L2 | 同 D1 | dispatcher.route(request) | real_episodes_read=False | 不访问 memory/episodes/*.jsonl |
| D4 | `test_no_env_or_real_api_required` | 本轮所有测试不需要 .env 或真实 API | L1/L2 | — | — | 所有测试无 .env 读取、无真实 API 调用 | — |

### 6.5 Phase E: Memory / Tool Isolation（L2）

| ID | Test Name | Purpose | Level | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|-------|--------|-------------------|-----------|
| E1 | `test_retain_does_not_affect_tool_gate` | retain action 不改变 tool.gate evidence | L2 | 构造 dispatcher；先后 route TOOL_GATE → MEMORY RETAIN | 分别 route | TOOL_GATE evidence 独立于 retain result | TOOL_GATE evidence 不含 retain 字段 |
| E2 | `test_tool_gate_does_not_affect_retain` | tool.gate action 不改变 retain evidence | L2 | 同上，反向 | 分别 route | retain evidence 独立于 TOOL_GATE result | retain evidence 不含 gate_disposition |
| E3 | `test_existing_tool_branch_tests_not_affected` | 现有 tool branch 测试全部通过 | — | 运行 `pytest tests/runtime_integration/test_tool_branch_confirmation_required.py` | — | 22/22 pass（无回归） | — |
| E4 | `test_existing_memory_anchor_tests_not_affected` | 现有 memory anchor 测试全部通过 | — | 运行 `pytest tests/runtime_integration/test_memory_anchor_fake.py` | — | 全部通过（无回归） | — |
| E5 | `test_retain_does_not_touch_checkpoint` | retain 不触及 checkpoint subsystem | L2 | 同 E1，使用 spy dispatcher | route retain action | checkpoint handler 未被调用 | — |
| E6 | `test_retain_does_not_touch_skill` | retain 不触及 skill subsystem | L2 | 同上 | route retain action | skill handler 未被调用 | — |

### 6.6 Phase F: Scope Boundary — 不做什么的验证（L1/L2）

| ID | Test Name | Purpose | Level | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|-------|--------|-------------------|-----------|
| F1 | `test_retain_no_recall_into_context` | retain 不触发 recall（同 A5，从 scope 角度复验） | L2 | 同 A3 | dispatcher.route(request) | evidence 不含 recalled_to_context | model context/messages 未被修改 |
| F2 | `test_retain_no_background_consolidation` | retain 不触发 consolidation（同 A6） | L2 | 同 A3 | dispatcher.route(request) | evidence 不含 consolidation_triggered | consolidation pipeline 未被调用 |
| F3 | `test_retain_no_proactive_reminder` | retain 不生成 proactive reminder | L2 | 同 A3 | dispatcher.route(request) | evidence 不含 reminder, proactive, scheduled | — |
| F4 | `test_retain_no_real_private_data` | retain 不处理真实私人资料（in-memory 模式） | L1 | InMemoryMemoryStore + 测试 candidate | handler.handle | candidate content 为测试数据；store 为 in-memory | 不持久化到磁盘；不包含真实 PII |
| F5 | `test_retain_no_project_context_injection` | retain 不注入 project context | L2 | 同 A3 | dispatcher.route(request) | evidence 不含 project_context, repo_context | — |

## 7. 测试辅助工具设计

### 7.1 Test Candidate 工厂

```python
def _make_test_candidate(
    *,
    content: str = "用户偏好简体中文",
    proposal_id: str | None = None,
    source: str = "turn_end_proposal",
) -> dict:
    """构造一个合法的 test MemoryCandidate payload。"""
    import uuid
    return {
        "proposal_id": proposal_id or f"prop:{uuid.uuid4().hex[:12]}",
        "content": content,
        "source": source,
        "scope": "user",
        "sensitivity": "low",
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
    }
```

### 7.2 Retain Request 工厂

```python
def _make_retain_request(
    *,
    candidate: dict | None = None,
    confirmation_result: str = "accepted",
    proposal_id: str | None = None,
    action_type: RuntimeActionType = RuntimeActionType.MEMORY_PROPOSE,
) -> RuntimeActionRequest:
    """构造 retain RuntimeActionRequest。"""
    cand = candidate or _make_test_candidate()
    pid = proposal_id or cand["proposal_id"]
    return RuntimeActionRequest(
        action_type=action_type,
        source="confirmation_flow",
        parent_trace_id="trace-retain-test",
        payload={
            "confirmation_result": confirmation_result,
            "proposal_id": pid,
            "candidate": cand,
        },
        constraints={"no_silent_retain", "no_real_episodes_read"},
    )
```

### 7.3 Dispatcher + Handler 构建

复用 `test_tool_anchor_fake.py` 中的：
- `_build_phase1_dispatcher_with_tool_gate()` — 已注册 MemoryTurnEndProposalHandler
- `_SpyDispatcher` — spy dispatcher pattern

如果 retain 使用独立的 handler/RuntimeActionType，需要新增注册辅助函数：
```python
def _build_phase1_dispatcher_with_retain_handler(
    store: MemoryStoreProtocol | None = None,
) -> RuntimeActionDispatcher:
    """构建包含 retain handler 的 Phase 1 dispatcher。"""
```

### 7.4 测试隔离

- 每个测试使用独立的 InMemoryMemoryStore 实例
- 不依赖测试执行顺序
- 不修改全局 TOOL_REGISTRY 或 MemoryStore 单例
- FilesystemMemoryStore 测试使用 `tmp_path` fixture

## 8. DEFERRED 项目

| 项目 | 依赖 | 目标阶段 |
|------|------|---------|
| L3 `real_core_loop_runtime_e2e` 测试（C3） | handler 实现 + loop 集成 | Implementation Plan |
| SPEC OQ#1 最终方案选择 | Implementation Plan 决策 | Implementation Plan |
| `LoopDependencies` 是否需要 memory 字段（OQ#2） | 方案选择 | Implementation Plan |
| FilesystemMemoryStore write 的 external_side_effects（OQ#4） | — | 本轮 D2 已覆盖 |

## 9. 与 SPEC 的追溯

| SPEC § | 本 TDD 覆盖 |
|--------|-----------|
| §2.1 retain 语义 | A1-A4 (positive path), B1-B7 (negative/boundary) |
| §2.2 retain positive path 特征 | A1-A7 (全部 positive 断言) |
| §2.3 retain negative path | B1-B7 (全部 negative 场景) |
| §2.4 不在 SPEC 范围 | Phase F (F1-F5, scope boundary verification) |
| §4 fake/real 配置层边界 | Phase D (D1-D4) |
| §5.1 dogfood 允许做法 | C2 (dispatcher.route → harness_runtime_e2e) |
| §5.2 dogfood 禁止做法 | C5 (direct store.write), C6 (direct policy call) |
| §5.3 分类预期 | Phase C (C1-C6) |
| §6 SPEC 不做什么 | Phase F (F1-F5) + E3-E4 (回归) |
| §8 OQ#1 (RuntimeActionType) | 测试设计方案无关，§3 策略说明 |
| §8 OQ#2 (LoopDependencies) | DEFERRED 到 Implementation Plan |
| §8 OQ#3 (evidence_level for retain) | C1-C3, DEFERRED C3 |
| §8 OQ#4 (external_side_effects) | B7 + D1-D2 |
| §8 OQ#5 (T1 CLI integration) | 不在本轮 scope（SPEC §2.4 确认） |

## 10. Review Checklist

- [ ] branch point 判断正确（memory.turn_end_proposal，非新 Anchor）
- [ ] 不是新 capability milestone
- [ ] SPEC OQ#1 已呈现为方案无关的测试设计
- [ ] retain positive path 全覆盖（write, metadata, no_silent_retain, no recall, no consolidation）
- [ ] retain negative path 全覆盖（rejected, not_found, tampered, missing fields, store failure）
- [ ] classification boundary 覆盖三级分类 + 反欺诈 + direct store/policy 降级
- [ ] fake/real store adapter boundary 测试
- [ ] Memory / Tool 隔离测试（互相不污染）
- [ ] 现有 tool branch + memory anchor 测试回归验证
- [ ] scope boundary 测试（F1-F5：不 recall, 不 consolidate, 不 reminder, 不 PII, 不 project context）
- [ ] 无 .env 依赖
- [ ] 无真实 API 依赖
- [ ] 不修改 agent/ / tests/（本 TDD 仅写文档）
- [ ] 与 Unified Runtime Flow Contract 一致
- [ ] 与 SPEC 一致

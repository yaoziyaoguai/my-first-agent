# Memory Write Path Dispatcher Migration — 架构设计

**日期**: 2026-05-27
**任务类型**: architecture_change + plan-eng-review + G-Stack evidence analysis
**状态**: DESIGN — 待用户审批后进入 implementation loop
**严格边界**: 本轮只出设计，不改 production code

---

## 1. Executive Verdict

**当前 memory write path（evaluate_user_text → resolve_confirmation → store write）绕过 RuntimeActionDispatcher，属于 direct handler call，不产生 dispatcher evidence chain。**

对比 read/recall path 已经通过 `refresh_runtime_system_prompt(dispatcher=...)` → `MEMORY_RECALL` → `MemoryRecallHandler` 走通 dispatcher，write path 的缺失构成**架构不对称**。

更关键的是：dispatcher 已经注册了 `MEMORY_PROPOSE` → `MemoryRetainHandler`，该 handler 具备完整的 store write + catalog adapter + target_module_proof 能力。**当前 write path 不使用它——这就是 fake/real split 和 direct handler 冒充 L3 的根因。**

**推荐方案**: 最小侵入式迁移——保持 `MemoryRuntime` 作为 policy evaluation facade，将其 `resolve_confirmation()` 的 store write 改为通过 dispatcher dispatch `MEMORY_PROPOSE`。不重写 MemoryRuntime、不新增 RuntimeActionType、不改变两阶段确认流程。

**风险等级**: 低。改动集中在 `agent/core.py` 的 confirmation resolve 段（约 30 行），MemoryRetainHandler 已生产就绪。

---

## 2. Current Path Map

### 2.1 Read/Recall Path (DISPATCHER ✓)

```
用户输入
  → core.chat()
    → refresh_runtime_system_prompt(dispatcher=runtime_action_dispatcher)  [core.py:704]
      → RuntimeActionRequest(MEMORY_RECALL) 
        → dispatcher.route_from_runtime_loop()
          → MemoryRecallHandler.handle()
            → context.invoke_registered_target(build_memory_snapshot)
            → build_memory_section(snapshot)
            → context.success(payload={prompt_section: "..."})
      → build_system_prompt(memory_section=...)
      → state.set_system_prompt()
```

**证据等级**: L3 — dispatcher path, target_module_proof via catalog adapter
**覆盖**: recall 路径统一，fake/real 共享 `refresh_runtime_system_prompt(dispatcher=...)`

### 2.2 Write/Evaluate Path (DIRECT CALL ✗)

```
用户输入 "请记住：我喜欢用中文讨论复杂工程问题"
  → core.chat() [core.py:630]
    → _memory_runtime.evaluate_user_text(user_input, on_event=on_runtime_event)
      → policy.decide("请记住：我喜欢用中文讨论复杂工程问题")
        → MemoryDecision(RETAIN, target_candidate=..., requires_user_confirmation=True)
      → _pending_decision = {decision, confirmation_request, candidate_id}  ← 缓存
      → return MemoryEvaluationResult(CONFIRMATION_REQUIRED)
    → core.py 构造 pending_user_input_request, state.task.status = "awaiting_user_input"
    → save_checkpoint()
```

**证据等级**: 无 dispatcher evidence——这是 direct call，不经过 `route_from_runtime_loop()`

### 2.3 Write/Confirm→Retain Path (DIRECT CALL ✗)

```
用户输入 "y"（确认）
  → core.chat() → 检测 awaiting_user_input, kind="memory_confirmation"
    → _memory_runtime.resolve_confirmation(candidate_id, choice=ACCEPT)
      → confirmation_result = resolve_memory_confirmation_choice(...)
      → intent = build_memory_operation_intent(confirmation_result)
      → audit = build_memory_audit_summary(intent)
      → self._store.apply_operation_intent(intent, audit)   ← DIRECT STORE WRITE
    → return MemoryEvaluationResult(STORED)
```

**证据等级**: 无 dispatcher evidence——store write 跳过 dispatcher 和 catalog adapter

### 2.4 Turn-End Proposal Path (DISPATCHER ✓ but different flow)

```
turn-end hook [loop.py]
  → MEMORY_TURN_END_PROPOSAL dispatch
    → MemoryTurnEndProposalHandler.handle()
      → policy.decide(assistant_response)  ← 分析模型回复，非用户输入
      → 返回 proposal（pending_review=True, not_confirmed=True）
```

这是一个**不同的 flow**——它在 turn-end 分析 assistant response 中的 memory candidate，不是响应用户显式 "remember X" 命令。write path 迁移不改变此 flow。

### 2.5 Dispatcher MEMORY_PROPOSE Handler (EXISTS, UNUSED for user path)

```
MemoryRetainHandler.handle()  [memory_retain.py]
  → 验证 confirmation_result, proposal_id, candidate
  → content hash 防篡改
  → MemoryOperationIntent + MemoryAuditSummary
  → context.invoke_registered_target(store, apply_operation_intent)  ← catalog adapter
  → context.success() with target_module_proof
```

这个 handler **已经存在且生产就绪**，但当前 write path 从不调用它。

### 2.6 CLI Shortcut Status

| Shortcut | 分类 | 当前路径 | 是否走 dispatcher |
|----------|------|---------|-------------------|
| `show memories` | READ_ONLY | `CLI_SHOW_MEMORIES` → `CliShowMemoriesHandler` | ✓ (Loop 4) |
| `show subagents` | READ_ONLY | `CLI_SHOW_SUBAGENTS` → `CliShowSubagentsHandler` | ✓ (Loop 4) |
| `forget <keyword>` | MUTATING | `_memory_runtime.list_records()` + `remove_record()` 直调 | ✗ 绕过 dispatcher |
| `delegate to <name>` | DELEGATING | 直接 subagent run | ✗ 绕过 dispatcher |

---

## 3. Desired Unified Path

```
用户输入 "请记住：X"
  → core.chat()
    → _memory_runtime.evaluate_user_text(user_input)
      → policy.decide() → MemoryDecision(RETAIN)  ← 保留，纯逻辑无副作用
      → 缓存 _pending_decision  ← 保留，两阶段确认的状态管理
      → return CONFIRMATION_REQUIRED

用户输入 "y"（确认）
  → core.chat() → 检测 memory_confirmation
    → _memory_runtime.resolve_confirmation(candidate_id, choice=ACCEPT)
      → 构造 MemoryOperationIntent + MemoryAuditSummary  ← 保留
      → **改为 dispatch MEMORY_PROPOSE**  ← 唯一变更点
        → RuntimeActionRequest(MEMORY_PROPOSE, payload={
            confirmation_result, proposal_id, candidate, ...
          })
        → dispatcher.route_from_runtime_loop()
          → MemoryRetainHandler.handle()
            → context.invoke_registered_target(store, apply_operation_intent)
            → evidence chain complete ✓
```

**变更范围**:
- `agent/memory_runtime.py`: `resolve_confirmation()` — 将 `self._store.apply_operation_intent()` 替换为返回 `(intent, audit)` 的中间结果，由调用方 dispatch
- `agent/core.py`: confirmation resolve 段 — 接收 `(intent, audit)`，构造 `RuntimeActionRequest(MEMORY_PROPOSE)` 并 dispatch
- **不需要**: 新增 RuntimeActionType、新增 handler、修改 MemoryRetainHandler

---

## 4. Branch Point Decision

### 4.1 分支点声明（UNIFIED_RUNTIME_FLOW_CONTRACT 合规）

根据 `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` § "Memory may have multiple branch points"：

| 分支点 | 阶段 | 当前路径 | 目标路径 | 是否经过 RuntimeActionDispatcher |
|--------|------|---------|---------|-------------------------------|
| MEMORY_RECALL | pre-loop (每轮开始时) | dispatcher ✓ | dispatcher ✓ | 是 — `refresh_runtime_system_prompt(dispatcher=...)` |
| MEMORY_TURN_END_PROPOSAL | turn-end hook | dispatcher ✓ | dispatcher ✓ | 是 — `loop.py turn_end` |
| MEMORY_CONSOLIDATE | turn-end hook | dispatcher ✓ | dispatcher ✓ | 是 — `loop.py turn_end` |
| **MEMORY_PROPOSE (user-initiated)** | **post-confirmation (loop 中)** | **direct call ✗** | **dispatcher** | **改为是 — core.chat() 中 dispatch** |
| CLI forget | loop 中 (CLI shortcut) | direct call ✗ | 远期 dispatcher | 当前暂不迁移（MUTATING CLI shortcut，需要 confirmation pipeline 就绪） |

### 4.2 为什么不在 evaluate_user_text 阶段 dispatch

`evaluate_user_text()` 是纯 policy evaluation——调用 `policy.decide()` 做 deterministic string matching，无 IO、无 store write、无 side effect。dispatch 它会产生大量 NO_OP probe events（每轮用户输入都会触发），污染 evidence stream。

**决定**: 只在 confirmed store write 阶段 dispatch MEMORY_PROPOSE。policy evaluation 保留为轻量 coordinator 逻辑。

---

## 5. RuntimeAction / Dispatcher Design

### 5.1 复用现有 MEMORY_PROPOSE

不新增 RuntimeActionType。`MEMORY_PROPOSE` 在 `schema.py:28` 已定义，evidence kind = `business`（用户可见业务动作），语义完全匹配 confirmed memory retain。

### 5.2 Payload 契约

`MemoryRetainHandler.handle()` 当前期望的 payload 字段：

```python
{
    "confirmation_result": "accepted",    # str: accepted/rejected/session_only
    "proposal_id": "candidate:abc123...", # str: 以 "candidate:" 或 "prop:" 开头
    "candidate": {                        # Mapping: candidate 完整字段
        "proposal_id": "...",
        "content": "...",
        "content_hash": "...",            # sha256(content)
        "scope": "user",
        "sensitivity": "low",
        "source": "explicit_user_request",
    },
    "provider_kind": "fake" | "real",     # 用于 evidence metadata
}
```

注意：`MemoryRetainHandler` 当前验证 `proposal_id.startswith("prop:")`（line 124）。用户显式 retain 路径的 candidate_id 格式为 `candidate:<sha256[:16]>`。需要放宽验证以同时接受 `candidate:` 前缀，或统一 proposal_id 格式。

### 5.3 resolve_confirmation 改造

`MemoryRuntime.resolve_confirmation()` 当前直接写 store。改造后：

```python
def resolve_confirmation(
    self, candidate_id, choice, free_text=None
) -> MemoryEvaluationResult:
    # ... 现有验证逻辑（pending_decision 存在性、choice 解析）保持不变 ...
    # ... 构造 confirmation_result, intent, audit 保持不变 ...

    # 改：不再直接 self._store.apply_operation_intent()
    # 而是返回足够的信息让调用方通过 dispatcher 执行 store write
    # 新增返回字段 _dispatcher_payload 供调用方使用
    return MemoryEvaluationResult(
        action=MemoryEvaluationAction.STORED,  # 或 PENDING_DISPATCH
        ...
        # 新增: dispatcher 所需 payload
        _dispatcher_payload={
            "confirmation_result": "accepted",
            "proposal_id": candidate_id,
            "candidate": {...},
            "intent": intent,
            "audit": audit,
        }
    )
```

### 5.4 core.py 改造点

```python
# core.py confirmation resolve 段（当前约 line 630-665 附近）
# BEFORE:
result = _memory_runtime.evaluate_user_text(user_input, on_event=on_runtime_event)
# ... resolve_confirmation 直接写 store ...

# AFTER:
result = _memory_runtime.resolve_confirmation(candidate_id, choice, free_text)
if result._dispatcher_payload is not None and runtime_action_dispatcher is not None:
    # unified dispatch path
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_PROPOSE,
        source="core_loop",
        parent_trace_id="",
        payload=result._dispatcher_payload,
    )
    route = getattr(runtime_action_dispatcher, "route_from_runtime_loop", 
                    runtime_action_dispatcher.route)
    route(request)
else:
    # fallback: dispatcher 不可用时直接写 store（测试/dogfood 兼容）
    ...
```

---

## 6. Compatibility / Facade Strategy

### 6.1 MemoryRuntime 定位不变

`MemoryRuntime` 保持为**高内聚协调器**：
- `evaluate_user_text()`: policy evaluation + 两阶段确认状态管理（保留）
- `resolve_confirmation()`: 确认结果解析 + intent/audit 构造（保留）
- `snapshot_for_prompt()`: 只读 store 查询（保留）
- `list_records()` / `remove_record()`: 用户面管理（保留，远期迁入 dispatcher）

**唯一变更**: `resolve_confirmation()` 不再直接写 store，改为返回 `_dispatcher_payload` 供调用方 dispatch。

### 6.2 回退路径

当 `runtime_action_dispatcher is None`（测试、dogfood harness 等场景）：
- 保留当前 `store.apply_operation_intent()` 直接写入路径
- 不强制所有调用方必须提供 dispatcher
- 渐进式迁移，不破坏现有测试基线

### 6.3 不迁移的部分（本期）

| 组件 | 原因 |
|------|------|
| `remove_record()` (CLI forget) | MUTATING CLI shortcut，需要 confirmation pipeline 就绪后统一迁入 |
| `list_records()` (CLI show memories) | READ_ONLY，已通过 `CLI_SHOW_MEMORIES` dispatcher path 覆盖 |
| `evaluate_user_text()` policy evaluation | 纯逻辑无副作用，dispatch 会产生 NO_OP 噪音 |
| Turn-end MEMORY_TURN_END_PROPOSAL | 已有 dispatcher path，不改变 |

---

## 7. CLI Shortcut Freeze Strategy

### 7.1 当前 freeze 边界

`KNOWN_COMMAND_SHORTCUTS` allowlist 已注册 5 个 shortcut：
- `detect_show_memories` — dispatcher ✓
- `detect_show_subagents` — dispatcher ✓
- `detect_forget_memory` — direct call ✗（MUTATING，待迁入）
- `detect_delegate_to_subagent` — direct call ✗（DELEGATING，待迁入）
- `detect_nl_delegation` — direct call ✗（DELEGATING，待迁入）

### 7.2 迁移后 freeze 更新

本期迁移完成后，freeze 状态不变——本次不改 CLI shortcut 路径。memory forget 的 dispatcher 迁移是独立任务。

### 7.3 新 shortcut 禁止规则

本次迁移不新增 CLI shortcut、不新增 detect 函数、不扩展 KNOWN_COMMAND_SHORTCUTS。

---

## 8. Evidence Taxonomy

### 8.1 迁移前

| 路径 | 证据等级 | 说明 |
|------|---------|------|
| MEMORY_RECALL (read) | L3 | dispatcher → MemoryRecallHandler → catalog adapter |
| MEMORY_PROPOSE (turn-end) | L3 | dispatcher → MemoryTurnEndProposalHandler（仅 proposal，不写 store） |
| **User-initiated retain (write)** | **L2** | **direct `store.apply_operation_intent()` call，无 dispatcher evidence** |
| CLI show memories | L3 | dispatcher → CliShowMemoriesHandler |
| CLI forget | L2 | direct `store.remove_record()` call |

### 8.2 迁移后

| 路径 | 证据等级 | 说明 |
|------|---------|------|
| MEMORY_RECALL (read) | L3 | 不变 |
| MEMORY_PROPOSE (turn-end) | L3 | 不变 |
| **User-initiated retain (write)** | **L3** | **dispatcher → MemoryRetainHandler → catalog adapter → target_module_proof** |
| CLI show memories | L3 | 不变 |
| CLI forget | L2 | 不变（远期 L3） |

### 8.3 L1/L2/L3 定义复用

- **L1**: docs/design only — 架构文档描述
- **L2**: guard tests — `test_evidence_taxonomy.py` 中 dispatcher handler 注册验证
- **L3**: dispatcher path — `route_from_runtime_loop()` → handler → catalog adapter → target_module_proof
- **L4**: real API interactive dogfood — 真实 API 下端到端验证（本迁移不触及）

### 8.4 防冒充规则

- `MemoryRetainHandler` 的 `context.invoke_registered_target()` 产生 `target_module_proof`——这是 trusted proof，不能通过直接调用 handler 伪造
- 直接 `handler.handle(request, mock_context)` 的测试必须标注为 L2（unit/component），不得标 L3
- L3 证据必须经过 `dispatcher.route_from_runtime_loop()` 真实调用链

---

## 9. Test Plan

### 9.1 迁移前必须先写的测试（TDD）

**Failing tests（RED phase）**:

1. **`test_memory_write_path_uses_dispatcher`** (new in `tests/test_memory_production_path.py`)
   - 验证: user-initiated memory retain 经过 `route_from_runtime_loop(MEMORY_PROPOSE)`
   - 方法: spy on dispatcher, 确认 `MEMORY_PROPOSE` action 被 dispatch
   - 当前预期: FAIL — write path 绕过 dispatcher

2. **`test_memory_retain_handler_receives_user_initiated_proposal`** (new)
   - 验证: MemoryRetainHandler 能处理 `candidate:` 前缀的 proposal_id
   - 方法: 构造带 `candidate:abc123` proposal_id 的 request, 验证不被 rejected
   - 当前预期: FAIL — handler 当前只接受 `prop:` 前缀

3. **`test_memory_confirm_retain_recall_e2e`** (new, integration)
   - 验证: evaluate → confirm → retain (via dispatcher) → recall (via dispatcher) → prompt context
   - 方法: 完整 flow, 验证 store 写入和 prompt_section 包含已 retain 内容
   - 当前预期: FAIL — retain 路径不走 dispatcher

**Guard tests（扩展已有文件）**:

4. **`test_memory_write_path_not_direct_store_call`** (new in `tests/test_evidence_taxonomy.py`)
   - 验证: production code path 不直接调用 `store.apply_operation_intent()`（除 fallback 路径外）
   - 当前预期: FAIL

5. **`test_memory_propose_handler_registered`** (already exists via `test_architecture_boundaries.py`)
   - 验证: MEMORY_PROPOSE handler 在 dispatcher registry 中
   - 当前预期: PASS（已注册）

### 9.2 回归测试

- `tests/test_interactive_dogfood_harness.py` — 37 tests, 必须全部 PASS
- `tests/test_docs_source_of_truth.py` — 68 tests, 必须全部 PASS
- `tests/test_memory_policy.py` — 必须全部 PASS
- `tests/unit/test_evidence_kind_classification.py` — 18 tests, 必须全部 PASS
- `tests/test_architecture_boundaries.py` — 24 tests, 必须全部 PASS

### 9.3 Dogfood Cases

现有 case matrix 中覆盖 memory 的 cases:
- I09-I11 (fake/local): memory request, accept, deny — 验证交互流程
- R09-R11 (real API): memory request, accept, deny — 验证真实 API 下不 crash

迁移后需新增 dogfood case:
- **M-WRITE-01**: `"请记住：测试 dispatcher 写入路径"` → `"y"` → 验证 BUSINESS_ACTION 事件产生 → 验证 memory recall 可见新记录

---

## 10. Migration Phases

### Phase 1: Handler 兼容性修复（1 commit）

**文件**: `agent/runtime_integration/memory_retain.py`
**改动**: `MemoryRetainHandler.handle()` — 放宽 `proposal_id` 前缀验证，同时接受 `prop:` 和 `candidate:` 前缀
**测试**: `test_memory_retain_handler_receives_user_initiated_proposal` → PASS
**风险**: 低 — 纯验证逻辑放宽，不影响已有 turn-end proposal 路径

### Phase 2: MemoryRuntime 返回 dispatcher payload（1 commit）

**文件**: `agent/memory_runtime.py`
**改动**: `resolve_confirmation()` — 成功路径不再直接 `self._store.apply_operation_intent()`，改为在返回的 `MemoryEvaluationResult` 上附加 `_dispatcher_payload`
**向后兼容**: 保留 `_dispatcher_payload` 为 None 时不强制 dispatch（fallback 路径），现有测试不受影响
**测试**: 现有 memory policy/integration tests → PASS

### Phase 3: core.py dispatch 接入（1 commit）

**文件**: `agent/core.py`
**改动**: confirmation resolve 段 → 检测 `_dispatcher_payload` → dispatch `MEMORY_PROPOSE`
**fallback**: `runtime_action_dispatcher is None` 时回退到直接 `store.apply_operation_intent()`
**测试**: `test_memory_write_path_uses_dispatcher` → PASS

### Phase 4: E2E 集成验证 + guard tests（1 commit）

**文件**: `tests/test_memory_production_path.py` (new), `tests/test_evidence_taxonomy.py` (extend)
**测试**: `test_memory_confirm_retain_recall_e2e` → PASS, evidence taxonomy guard tests → PASS
**Dogfood**: 运行 M-WRITE-01 case

### Phase 5: 文档更新 + commit/push（1 commit）

**文件**: `docs/PROJECT_STATUS.md`, `docs/PROGRESS_LEDGER.md`
**内容**: 更新 memory write path 状态从 PARTIAL → RESOLVED，引用 dispatcher evidence

### 总预估

- **文件变更**: 4-5 个文件
- **新增测试**: 4-5 个
- **生产代码改动**: ~50 行
- **预计 commits**: 4-5

---

## 11. Risks

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `resolve_confirmation()` 返回格式变更破坏现有调用方 | 中 | 中 | `_dispatcher_payload` 设为可选字段，None 时保持旧行为 |
| proposal_id 前缀放宽导致安全绕过 | 低 | 高 | 保留 content_hash 验证，不依赖 proposal_id 做授权 |
| dispatcher 不可用时 fallback 路径被误标为 L3 | 低 | 中 | fallback 路径不产生 RuntimeActionEvent，evidence taxonomy guard test 区分 |
| 两阶段确认的 `_pending_decision` 状态在 dispatcher 异步模型中不同步 | 低 | 低 | 当前 dispatcher 是同步调用，无异步问题 |
| 与 turn-end MEMORY_TURN_END_PROPOSAL flow 产生混淆 | 低 | 中 | 两个 flow 使用不同 RuntimeActionType（MEMORY_PROPOSE vs MEMORY_TURN_END_PROPOSAL），handler 不同 |

---

## 12. Stop Conditions

- [ ] `resolve_confirmation()` 改动导致现有 memory policy tests 回归
- [ ] `MemoryRetainHandler` proposal_id 验证变更导致 turn-end proposal path 破坏
- [ ] dispatcher 路径下 store write 的 content hash 验证失败（数据完整性问题）
- [ ] fallback 路径（dispatcher=None）下的 store write 被完全移除（破坏测试/dogfood 兼容）
- [ ] 生产代码改动超过 100 行（scope creep 信号）
- [ ] 需要新增 RuntimeActionType（设计错误——应复用 MEMORY_PROPOSE）

---

## 13. Recommended Implementation Loop

**Loop 15: Memory Write Dispatcher Migration**

- **Task Type**: `production_path_repair`
- **Primary Skill**: Compound Engineering
- **Secondary Skill**: Superpowers (verification-before-completion)
- **Start Point**: Phase 1 (handler compatibility fix)
- **Evidence Level Target**: L3 (dispatcher path with target_module_proof)
- **Dependencies**: Loop 14 已完成（dogfood harness evidence gates 修复）

### Loop 15 执行步骤

1. Phase 1: Handler proposal_id 兼容 → test → gate
2. Phase 2: MemoryRuntime resolve_confirmation 改造 → test → gate
3. Phase 3: core.py dispatch 接入 → test → gate
4. Phase 4: E2E integration + guard tests → dogfood → gate
5. Phase 5: Docs update → commit → push

### 不在此 Loop 的范围

- CLI forget shortcut dispatcher 迁移（独立 loop）
- CLI delegate shortcut dispatcher 迁移（独立 loop）
- MemoryRuntime 完全移除直接 store 引用（远期架构演进）
- Turn-end MEMORY_TURN_END_PROPOSAL flow 变更
- 真实 API dogfood 全量重跑（可选，最小验证仅 M-WRITE-01）

---

## Appendix A: 审计问题逐条回答

### A1. 当前 memory read/recall path 如何进入 prompt context？

`refresh_runtime_system_prompt(dispatcher=runtime_action_dispatcher)` [core.py:704] → 构造 `RuntimeActionRequest(MEMORY_RECALL)` → `dispatcher.route_from_runtime_loop()` → `MemoryRecallHandler.handle()` → `context.invoke_registered_target(build_memory_snapshot)` → `build_memory_section(snapshot)` → `context.success(payload={"prompt_section": "..."})` → `build_system_prompt(memory_section=...)` → `state.set_system_prompt()`。

结论：read path 已通过 dispatcher，L3 evidence。

### A2. 为什么 memory write/proposal/retain path 绕过 dispatcher？

`core.py:630` 直接调用 `_memory_runtime.evaluate_user_text(user_input)`，这是模块级单例的成员方法调用。`_memory_runtime` 持有 `_store` 引用，`resolve_confirmation()` 中直接 `self._store.apply_operation_intent()` 写入。没有经过 `RuntimeActionRequest` → `dispatcher.route()` → handler → catalog adapter 的证据链。

根因：write path 在 Memory Kernel v1 实现时（2026-05-22 前后），dispatcher 和 MEMORY_PROPOSE handler 尚未就绪。之后 dispatcher 和 handler 相继实现（MemoryRetainHandler 已注册在 phase1_hook.py:82-84），但 write path 从未回迁到 dispatcher。

### A3. _memory_runtime.evaluate_user_text() 应保留为 facade 还是改为内部 dispatcher？

保留为 facade。理由：
- `evaluate_user_text()` 中的 `policy.decide()` 是纯 deterministic 字符串匹配，无 IO、无副作用
- dispatch policy evaluation 会在每轮用户输入产生 MEMORY_PROPOSE probe event，绝大多数是 NO_OP，污染 evidence stream
- `_pending_decision` 缓存是两阶段确认的轻量状态管理，不需要 dispatcher 介入

**只有 store write（`resolve_confirmation` 的成功路径）需要走 dispatcher。**

### A4. Memory proposal 是否应成为 RuntimeAction？

已经是。`MEMORY_PROPOSE` = `"memory.propose"` 在 `schema.py:28` 已定义，evidence kind = `business`。当前只用于 turn-end proposal 的 retain execution，迁移后同时用于 user-initiated retain。

### A5. Memory confirm yes/no 是否应成为 RuntimeAction？

**不需要新增独立 action type。** confirm yes/no 是 `MEMORY_PROPOSE` action payload 中的 `confirmation_result` 字段（`"accepted"` / `"rejected"` / `"session_only"`），由 `MemoryRetainHandler` 根据此字段决定是否写入 store。这已经是完整的两阶段语义表达。

### A6. Retain 是否应由 dispatcher/handler 执行？

**是。** `MemoryRetainHandler.handle()` 已实现完整的 retain 执行逻辑：验证 → hash check → intent/audit 构造 → `context.invoke_registered_target(store, apply_operation_intent)` → target_module_proof。当前 write path 应改为通过 dispatcher 调用此 handler。

### A7. Memory store 更新是否应统一在 handler 中？

**是。** 迁移后 `store.apply_operation_intent()` 的唯一 production path 调用方应为 `MemoryRetainHandler.handle()`（通过 `context.invoke_registered_target`）。`MemoryRuntime.resolve_confirmation()` 和 `core.py` 都不再直接调用 store write。

### A8. 哪些 CLI shortcut memory 命令仍是第二能力平面？

- `show memories` → 已迁入 dispatcher（`CLI_SHOW_MEMORIES`），不在第二平面 ✓
- `forget <keyword>` → 仍直接调用 `_memory_runtime.list_records()` + `remove_record()`，在第二平面 ✗
- `show subagents` → 已迁入 dispatcher ✓
- `delegate to <name>` → 仍直接 subagent run，在第二平面 ✗

### A9. 如何防止 direct handler test 冒充 L3？

规则：
- 直接 `handler.handle(request, mock_context)` 的测试 → L2 evidence
- 经过 `dispatcher.route_from_runtime_loop()` 的测试 → L3 evidence
- `test_evidence_taxonomy.py` 中新增 guard test：验证 `MemoryRetainHandler` 的 L3 test 必须经过 dispatcher，否则 FAIL

### A10. L1/L2/L3 evidence 设计？

见 Section 8。

### A11. 最小迁移计划？

见 Section 10 — 4 个 Phase，~50 行生产代码变更，4-5 个新测试。

### A12. 哪些旧路径需 freeze/deprecate/facade？

- `MemoryRuntime.resolve_confirmation()` 中的 `self._store.apply_operation_intent()` — **改为返回 payload 由调用方 dispatch**（deprecate 直接写入）
- `core.py` 中的 `_memory_runtime.evaluate_user_text()` 调用 — **保留**（facade 角色）
- `core.py` 中的 confirmation resolve → store write — **改为 dispatch MEMORY_PROPOSE**
- Turn-end `MEMORY_TURN_END_PROPOSAL` + `MEMORY_PROPOSE` flow — **不变**

### A13. 哪些测试必须先写？

见 Section 9.1 — 3 个 failing tests + 2 个 guard tests，按 TDD RED→GREEN 顺序。

### A14. 哪些 dogfood cases 证明默认 production path 工作？

- **M-WRITE-01** (new): `"请记住：测试 dispatcher 写入路径"` → `"y"` → verify BUSINESS_ACTION + recall
- **I09-I11** (existing, fake/local): memory request/accept/deny — 验证交互流程正确性
- **R09-R11** (existing, real API): 验证真实 API 下不 crash（L4 smoke）

# REAL-EVIDENCE-008 Independent Review

**Review date**: 2026-05-29
**Target commit**: 3b17ca1 (`validation(evidence): complete scheduler core chat and plan bridge`)
**Reviewer**: independent evidence / code review agent
**Scope**: 008 Scheduler core.chat E2E + plan bridge — 不含 003/002/B7/B8，不声称 product-ready

---

## Verdict

**PASS_WITH_CONCERNS**

008 可接受为 credible。Production code risk = medium-low。本轮 Gap A + Gap B 闭合了 scheduler main-path injection chain 和 model output → ActionPlan bridge，均为低中风险代码变更。

---

## 008 Credibility

**credible** — Gap A + Gap B evidence chain 闭合:

### Gap A: `core.chat(action_scheduler=scheduler)` E2E Validation

```
core.chat() 接受 action_scheduler 参数
  → LoopDependencies 注入
  → _run_main_loop(action_scheduler=scheduler)
  → run_main_loop() preprocessing block 触发（不再 dead code）
  → ACTION_PLAN_START dispatched
  → NODE_ENTER × N dispatched
  → NODE_EXIT × N dispatched (completed / skipped)
  → ACTION_PLAN_COMPLETE dispatched
  → condition_flags 跨 node 影响 (step_2 设置 skip_step_3=True → step_3 skipped)
  → NODE_FAILURE halt 验证 (error node → halted status)
  → topological order 验证 (nodes execute in plan order)
  → backward compat 验证 (action_scheduler=None → old code path)
```

10/10 PASS (V1-V10)，使用 FakeProvider + hand-built ActionPlan。

### Gap B: `build_action_plan_from_model_output()` JSON → ActionPlan Bridge

```
model output (raw JSON string)
  → build_action_plan_from_model_output(raw_json)
  → markdown code fence 剥离 (```json ... ```)
  → JSON parse
  → ActionNode 构造 (step_id, description, executor=lambda, max_retries)
  → 无效 node 跳过（不 crash）
  → 空 nodes → ValueError
  → 多余字段容忍
  → 无效 recovery fallback
```

7/7 new tests PASS。Production code: `action_scheduler.py` +~50 lines (bridge function only)。
27/27 scheduler tests total (20 existing + 7 new)。

---

## Score Impact

**3.8 → 3.9** (not product-ready — score still below product-ready threshold)

提升原因: Gap A 闭合了 scheduler main-path injection evidence chain —— `_run_main_loop(action_scheduler=...)` 首次通过完整 runtime path 验证，不再有 dead code。Gap B 实现了 model JSON output → ActionPlan bridge，使 scheduler 可消费模型生成的 plan 结构。

3.9/5 不声称 product-ready。以下 caveats 限制更高分数：
- model JSON generation 未闭合 —— ActionPlan 来自 hand-built fixture 或 hand-written JSON，非真实 LLM 自主生成稳定 ActionPlan JSON
- 未验证 scheduler + real model plan generation 的完整闭环
- scheduler 不处于默认活跃路径 —— 需显式传入 `action_scheduler=` 参数

---

## Credibility Matrix

| Evidence ID | Capability | Credibility | Notes |
|-------------|-----------|-------------|-------|
| REAL-EVIDENCE-001 | Memory recall provenance | credible | real provider memory retain/recall/forget E2E validated |
| REAL-EVIDENCE-002 | Skill activation | credible | real provider dogfood 两次通过 |
| REAL-EVIDENCE-003 | Skill allowed_tools disallowed-tool blocking | partial-credible | FakeProvider + scripted activation, not real model dogfood |
| REAL-EVIDENCE-004 | Checkpoint true resume | hardened | Part A 10 PASS; Part B 2 CONCERN (save point not reached) |
| REAL-EVIDENCE-005 | MCP bridge real server connection | credible | real StdioMCPClient subprocess JSON-RPC, 12/12 PASS |
| REAL-EVIDENCE-006 | SubAgent real provider child tool mediation | credible | 12/12 PASS real provider E2E; complete evidence chain closed |
| REAL-EVIDENCE-007 | MCP runtime-mediated invocation | credible | FakeProvider + confirmation override caveats, code path complete |
| **REAL-EVIDENCE-008** | **Scheduler core.chat E2E + plan bridge** | **credible** | **Gap A: 10/10 PASS injection chain + Gap B: 7/7 tests PASS bridge; caveat: model JSON generation 未闭合** |

---

## Gap A Detail (Scheduler Core.Chat E2E)

| Case | Verdict | Summary |
|------|---------|---------|
| V1 | PASS | Non-empty result returned — scheduler plan executed completely |
| V2 | PASS | ACTION_PLAN_START evidence dispatched |
| V3 | PASS | NODE_ENTER + NODE_EXIT evidence dispatched for each expected node |
| V4 | PASS | ACTION_PLAN_COMPLETE evidence dispatched after all nodes |
| V5 | PASS | condition_flags 跨 node influence confirmed (skip_step_3 → step_3 skipped) |
| V6 | PASS | NODE_FAILURE halt confirmed — error node triggers halted status |
| V7 | PASS | Complete evidence chain: 5 business evidence types in action_log |
| V8 | PASS | Not a manual harness PASS — injection through `core.chat()` |
| V9 | PASS | Topological order: nodes execute in plan order |
| V10 | PASS | Backward compat: `action_scheduler=None` preserves old behavior |

**Validation script**: `scripts/real_evidence_008_scheduler_core_chat_e2e.py`
**Result file**: `docs/dogfood/real-evidence-008-gap-a-results.json`

---

## Gap B Detail (Model Output → ActionPlan Bridge)

### Test Coverage

**文件**: `tests/runtime_integration/test_scheduler_main_path.py`
**Class**: `TestBuildActionPlanFromModelOutput`

| Test | Summary |
|------|---------|
| `test_parse_valid_json_to_action_plan` | 有效 JSON dict → ActionPlan，验证 node count/step_id/description |
| `test_parse_json_with_markdown_code_fence` | ```json ... ``` 包裹的 JSON 正确剥离和解析 |
| `test_skip_invalid_node_step_id` | 缺少 step_id 的 node 被跳过（不 crash），剩余 nodes 继续处理 |
| `test_empty_nodes_raises_value_error` | nodes 为空列表 → ValueError |
| `test_tolerate_extra_fields_in_json` | JSON 含多余字段（如 `extra_metadata`）→ 容忍，正常解析 |
| `test_invalid_recovery_node_fallback` | recovery node 的 executor 非 callable → 标记为 invalid，不影响主 plan |
| `test_bridge_roundtrip_dict_build_parse` | `build_action_plan_from_dict()` → dict → JSON → `build_action_plan_from_model_output()` → 验证 step_id，不验证 executor（executor 不可 JSON 序列化） |

7/7 PASS。

### Production Code

**文件**: `agent/action_scheduler.py` (~50 lines added)

```python
def build_action_plan_from_model_output(raw_output: str) -> ActionPlan:
    """
    从模型原始输出（JSON 字符串）构造 ActionPlan。

    处理:
    - markdown code fence (```json ... ```) 剥离
    - 无效 node（缺 step_id）跳过，不 crash
    - 空 nodes → ValueError
    - 多余 JSON 字段容忍
    - recovery executor 非 callable → 标记 invalid fallback
    """
```

---

## Production Code Changes

**`agent/action_scheduler.py`**: +~50 lines (`build_action_plan_from_model_output()` bridge function only)

其他变更均为 test/validation script/results JSON/docs 文件，不触及 production runtime behavior。

---

## Caveats

| Caveat | Impact | Mitigation |
|--------|--------|-----------|
| model JSON generation 未闭合 | ActionPlan 来自 hand-built fixture 或 hand-written JSON，非真实 LLM 自主生成稳定 ActionPlan JSON | methodology/model-behavior limitation，非代码路径缺口；scheduler code path + bridge code 已验证可消费 model-generated JSON |
| `core.chat(action_scheduler=scheduler)` 非默认活跃路径 | scheduler 需显式传入参数激活，默认 `action_scheduler=None` | 设计选择 —— scheduler 是 opt-in orchestration layer，不是默认 runtime path |
| Gap A 使用 FakeProvider | 未验证真实模型在 scheduler 驱动下的多 turn 行为 | Gap B bridge 已使 scheduler 可消费 model-generated plan；real model multi-turn 验证需 `planner.generate_plan()` 连接 |

---

## Gates

| Gate | Result |
|------|--------|
| Gap A validation script (`scripts/real_evidence_008_scheduler_core_chat_e2e.py`) | **10/10 PASS** (V1-V10) |
| Gap B bridge tests (`TestBuildActionPlanFromModelOutput`) | **7/7 PASS** |
| Scheduler contract tests (existing) | **20/20 PASS** |
| Scheduler total (20 existing + 7 new) | **27/27 PASS** |
| ruff | Clean |
| git diff --check | Clean |

---

## B7/B8 Entry Gate Check

| Condition | Status | Notes |
|-----------|--------|-------|
| 008 credibility | **credible** | Gap A+B evidence chain closed |
| Scheduler injection chain verified | **PASS** | `_run_main_loop(action_scheduler=...)` → 10/10 PASS |
| Plan bridge complete | **PASS** | `build_action_plan_from_model_output()` → 7/7 PASS |
| Model-generated stable ActionPlan JSON | **NOT MET** | methodology/model-behavior limitation —— planner.generate_plan() 未实现 |
| All scheduler tests pass | **PASS** | 27/27 PASS |

**B7/B8 entry gate: NOT FULLY MET.** Model-generated stable JSON plan 仍是未闭合 caveat。B7/B8 作为大型架构/产品化决策，需要此 gate 闭合后方可进入。当前阶段建议收口，不进入 B7/B8 implementation。

---

## Safety Checks

- [x] 未读取 .env
- [x] 未打印 API key / token / secret
- [x] 未 commit secret
- [x] 不修改 production code 核心行为 —— 仅新增 bridge function
- [x] 不涉及 003/002/B7/B8
- [x] Scheduler 不直接执行 tool —— 通过 run_main_loop() 内部 call_model() 驱动
- [x] 不声称 product-ready

---

## Docs Consistency Check

PROJECT_STATUS、PROGRESS_LEDGER、REAL_EVIDENCE_VALIDATION_DEBT 中 008 相关条目与本 review 结论一致。本文档作为独立 review 视角补充，不影响前序 source of truth 文件的权威性。

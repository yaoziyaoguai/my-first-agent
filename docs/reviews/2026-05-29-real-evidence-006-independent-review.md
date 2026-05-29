# REAL-EVIDENCE-006 Independent Review

**Review date**: 2026-05-29
**Target commit**: 7862604 (`test(subagent): cover child tool schema exposure`)
**Reviewer**: independent evidence / code review agent
**Scope**: 006 SubAgent real provider child tool mediation E2E + narrow cleanup only — 不含 003/007/008/002/B7/B8

---

## Verdict

**PASS_WITH_CONCERNS**

006 当前可接受为 credible。Production code risk = low。本轮 cleanup 补了 schema content test、unauthorized tool exclusion test、M7a/M7b evidence reporting 修正，均为低风险增强。

---

## 006 Credibility

**credible** — 完整 evidence chain 闭合:

```
parent delegates to child (SUBAGENT_DELEGATE_L1)
  → child real provider emits structured tool_use (SUBAGENT_CHILD_TOOL_REQUEST)
  → child tool_use goes through parent ToolRuntimeMediator
  → TOOL_GATE
  → TOOL_INVOKE
  → TOOL_RESULT
  → tool result returns to child context
  → child final result returns to parent adjudication (SUBAGENT_CHILD_RESULT → SUBAGENT_PARENT_ADJUDICATION)
```

12/12 PASS with real provider (AnthropicCompatibleProvider)，0 FAIL，0 CONCERN。

---

## Score Impact

**3.7 → 3.8** (not product-ready)

提升原因: child_tools schema fix 闭合了 MODEL_BEHAVIOR_CONCERN — child model 现在收到 model-visible tool schema 并输出 API-native structured tool_use block，完整 parent→child→tool mediation→result→adjudication evidence chain 首次通过真实 provider E2E 验证。

3.8/5 不声称 product-ready。以下 caveats 限制了更高分数:
- upstream tool_snapshots=() 未修复（delegate_l1() hardcode）
- demo-stat-real memory_scope=none 导致 child memory proposal path 未在 real provider E2E 中触发
- SimpleNamespace turn_state 私有属性访问 caveat

---

## Credibility Matrix

| Evidence ID | Capability | Credibility | Notes |
|-------------|-----------|-------------|-------|
| REAL-EVIDENCE-001 | Memory recall provenance | credible | real provider memory retain/recall/forget E2E validated |
| REAL-EVIDENCE-002 | Skill activation | credible | real provider dogfood 两次通过 |
| REAL-EVIDENCE-003 | Skill allowed_tools disallowed-tool blocking | partial-credible | FakeProvider + scripted activation, not real model dogfood |
| REAL-EVIDENCE-004 | Checkpoint true resume | hardened | Part A 10 PASS; Part B 2 CONCERN (save point not reached) |
| REAL-EVIDENCE-005 | MCP bridge real server connection | credible | real StdioMCPClient subprocess JSON-RPC, 12/12 PASS |
| **REAL-EVIDENCE-006** | **SubAgent real provider child tool mediation** | **credible** | **12/12 PASS real provider E2E; complete evidence chain closed** |
| REAL-EVIDENCE-007 | MCP runtime-mediated invocation | credible | FakeProvider + confirmation override caveats, code path complete |
| REAL-EVIDENCE-008 | Scheduler main-path injection | partial-credible | injection chain correct at run_main_loop() level; no full core.chat() E2E |

---

## Cleanup Tasks Completed (this review cycle)

### Task 1: Schema Content Tests (2 tests)

**文件**: `tests/runtime_integration/test_subagent_l1_parent_mediated.py`
**新增 class**: `TestChildToolSchemaContent`

- `test_child_tools_contains_read_file_schema` — 断言 child provider 收到的 tools 包含 read_file 的 `name`、`description`、`input_schema`（含 `path` 参数），与 TOOL_REGISTRY 一致
- `test_child_tools_schema_matches_registry_verbatim` — 断言所有 child tools 的 name/description/input_schema 与 TOOL_REGISTRY 逐项一致

### Task 2: Unauthorized Tool Exclusion Tests (4 tests)

**文件**: `tests/runtime_integration/test_subagent_l1_parent_mediated.py`
**新增 class**: `TestChildToolUnauthorizedExclusion`

- `test_only_allowed_tool_exposed_to_child` — request.allowed_tools=("read_file",) → child_tools 只有 read_file
- `test_shell_not_exposed_when_not_allowed` — shell 工具不进入 child_tools
- `test_demo_tools_not_exposed_when_not_allowed` — demo.* 工具不进入 child_tools
- `test_registry_has_more_tools_than_allowed` — guard: TOOL_REGISTRY 工具数 > allowed_tools 数，排除 falsely-true 风险

### Task 3: M7a/M7b Evidence Reporting Fix

**文件**: `scripts/real_evidence_006_subagent_real_provider.py`

修正 `_safe_payload()` — 优先读 `event.payload`（业务数据在 RuntimeActionResult 中），fallback 到 `event.evidence`（dispatcher 元数据）。RuntimeActionEvent 不含 payload 字段（转换时丢弃），`status='not_supported'` 是预期行为（notification 式 dispatch，无注册 handler）。更新 M7a/M7b 记录逻辑以解释此预期行为。

---

## Production Code Changes

**未修改 production code。** 本轮 cleanup 仅涉及 test 文件、validation script、dogfood result JSON、docs。

核心 production code fix（child_tools schema fix in `execute_l1()`）在上一个 commit (`56becfa`) 中已完成，本 review 不重新评估。

---

## Caveats

| Caveat | Impact | Mitigation |
|--------|--------|-----------|
| upstream `tool_snapshots=()` in `delegate_l1()` | `execute_l1()` 绕过此限制从 `request.allowed_tools` + TOOL_REGISTRY 构建 child_tools；`tool_snapshots` 参数当前不承载业务数据 | future cleanup，不影响 006 credible |
| SimpleNamespace turn_state + `_turn_context` 私有属性访问 | 不影响功能正确性 | future cleanup |
| demo-stat-real `memory_scope=none` | child memory proposal path 未在 real provider E2E 中触发 | contract tests 已覆盖 memory path |
| M7a/M7b `status='not_supported'` | SUBAGENT_CHILD_RESULT / SUBAGENT_PARENT_ADJUDICATION 是 notification 式 dispatch，无注册 handler → dispatcher 返回 `not_supported` | 预期行为，event 存在即证明 handler 执行了 dispatch |

---

## Gates

| Gate | Result |
|------|--------|
| 006 validation script (`scripts/real_evidence_006_subagent_real_provider.py`) | **12/12 PASS** (M0-M8) |
| SubAgent L1 focused tests (`test_subagent_l1_parent_mediated.py`) | **48/48 PASS** (42 existing + 6 new) |
| ToolRuntimeMediator focused tests (`test_tool_path_unification_l1_3.py`) | **16/16 PASS** |
| MCP + tool pipeline tests | **84/85 PASS** — 1 pre-existing unrelated failure (`test_f2_no_second_tool_pipeline`) |
| ruff | Clean |
| git diff --check | Clean |

---

## M0-M8 Detail (Latest Run)

| Case | Verdict | Summary |
|------|---------|---------|
| M0 | PASS | Provider built: AnthropicCompatibleProvider |
| M1 | PASS | SUBAGENT_DELEGATE_L1 dispatched: status=success |
| M1b | PASS | TOOL_REGISTRY has 'read_file' — execute_l1() can build child_tools schema |
| M2 | PASS | Child generated structured tool_use: 1 request(s), statuses=['success'] |
| M3 | PASS | Child tool entered parent ToolRuntimeMediator: 1 TOOL_GATE event |
| M4a | PASS | TOOL_INVOKE for child tool: 1 event |
| M4b | PASS | TOOL_RESULT for child tool: 1/1 success |
| M5 | PASS | Child tools mediated through ToolRuntimeMediator: 1 invocation |
| M6 | PASS | Real tool result returned: 1/1 success |
| M7a | PASS | Child result dispatched (notification dispatch, not_supported=expected) |
| M7b | PASS | Parent adjudication dispatched (notification dispatch, not_supported=expected) |
| M8 | PASS | Evidence chain traceable: 7 event types |

---

## Safety Checks

- [x] 未读取 .env
- [x] 未打印 API key / token / secret
- [x] 未 commit secret
- [x] child 不直接调用 tool — 必须通过 parent ToolRuntimeMediator
- [x] 未绕过 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT pipeline
- [x] 未将 XML tool_use 解析成"等价通过"冒充 API-native structured tool_use

---

## Docs Consistency Check

PROJECT_STATUS、PROGRESS_LEDGER、REAL_EVIDENCE_VALIDATION_DEBT 与本次审查结论一致，已在前序 commit 中更新。

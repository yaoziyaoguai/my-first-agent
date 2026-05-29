# REAL-EVIDENCE-007 Independent Review

**Review date**: 2026-05-29
**Target commit**: 213ba1d (`validation(evidence): complete mcp runtime invocation path`)
**Reviewer**: independent evidence / code review agent
**Scope**: 007 MCP runtime invocation path fix only — 不含 003/006/008/002/B7/B8

---

## Verdict

**PASS_WITH_CONCERNS**

---

## 007 Credibility

**credible** — code path + evidence chain 闭合。

两个 caveat（验证方法学 caveat，非代码路径缺口）:

1. **FakeProvider deterministic tool_use** — 不是 real model 自主 MCP tool selection
2. **confirmation='never' validation-only override** — production 默认 confirmation='always'

---

## Production Code Change

**文件**: `agent/tool_runtime_mediator.py:_route_result()` (lines 477-486)

**变更**:
- `result_summary` → `tool_output` (修复与 `ToolResultFeedbackHandler` 的 payload 字段不匹配)
- 新增 `execution_status` 字段

**风险**: **low**

**验证**:
- `ToolResultFeedbackHandler.handle()` 在 `tool_result_feedback.py:180-181` 确实期望 `tool_output` 字段
- 修复前 handler 会因 `tool_output_missing=True` 提前返回 `disposition=failed`
- `execution_status` 为可选字段，handler 有安全默认值 (`"success"`)
- 所有通过 `ToolRuntimeMediator` 的工具（不只是 MCP）都受益于此修复
- 无 `direct tool_registry.execute_tool()` 旁路

---

## Execution Chain Verified

```
core.chat
  → ToolRuntimeMediator.mediate()
    → _route_gate()           → TOOL_GATE (allowed)
    → _route_invoke()         → TOOL_INVOKE
    → execute_single_tool()   → MCP tool lambda → StdioMCPClient.call_tool()
                                 → subprocess.Popen + JSON-RPC → real echo response
    → _route_result()         → TOOL_RESULT (tool_output + execution_status)
                                 → ToolResultFeedbackHandler.format_tool_result()
                                 → disposition=injected
  → conversation context
```

---

## Gates

| Gate | Result |
|------|--------|
| 007 validation script (`scripts/real_evidence_007_mcp_invoke.py`) | **10/10 PASS** (W0-W8) |
| ToolRuntimeMediator focused tests (`test_tool_path_unification_l1_3.py`) | **16/16 PASS** |
| MCP real external flight tests (`test_mcp_real_external_flight.py`) | **30/30 PASS** |
| Combined MCP + tool pipeline tests | **84/85 PASS** — 1 pre-existing unrelated failure (`test_f2_no_second_tool_pipeline`: stale expected handler types, predates this fix) |
| ruff | Clean |
| git diff --check | Clean |

---

## W0-W8 Detail

| Case | Verdict | Summary |
|------|---------|---------|
| W0 | PASS | echo fixture server exists |
| W1 | PASS | real StdioMCPClient subprocess registered 2 tools |
| W2a | PASS | MCP tools in TOOL_REGISTRY |
| W2b | PASS | MCP tools in model-visible tools |
| W3 | PASS | TOOL_GATE: decision=allowed, source=ToolRuntimeMediator |
| W4 | PASS | TOOL_INVOKE: status=success — confirmation override allowed execution |
| W5 | PASS | StdioMCPClient.call_tool executed via subprocess (disposition=injected) |
| W6 | PASS | real MCP result: 67 bytes, not truncated |
| W7 | PASS | result in conversation context (32 chars, non-empty) |
| W8 | PASS | evidence chain: tool.gate→tool.invoke→tool.result (60 events, 12 types) |

---

## Safety Checks

- [x] 未使用真实 API key
- [x] local MCP echo fixture (安全进程，无网络/文件/命令执行)
- [x] confirmation='never' 仅在 validation 期间，验证后恢复原始 policy
- [x] destructive MCP tool 在 test 中验证不会进入 TOOL_REGISTRY
- [x] confirmation=always MCP tool 在 gate 被拦截，不进 TOOL_INVOKE
- [x] no direct tool_registry.execute_tool() bypass

---

## Known Caveats (Methodology, Not Code Gaps)

| Caveat | Impact | Mitigation |
|--------|--------|-----------|
| FakeProvider deterministic tool_use | 非真实模型自主 MCP tool selection | 已在 debt doc 中记录；real model MCP tool selection 不在本轮 scope |
| confirmation='never' override | 与 production confirmation='always' 不一致 | 验证后恢复原始 policy；不改变生产默认策略 |

---

## Docs Consistency Check

PROJECT_STATUS、PROGRESS_LEDGER、REAL_EVIDENCE_VALIDATION_DEBT 与本次审查结论一致，无需修改。

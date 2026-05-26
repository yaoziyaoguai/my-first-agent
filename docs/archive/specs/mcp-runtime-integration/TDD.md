# TDD: MCP Runtime Integration

Date: 2026-05-23
SPEC: [SPEC.md](./SPEC.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## Test Matrix

分层策略（复用 tool-invoke-branch-behavior 的分层模式）：
- L1 (subsystem_integration): MCP FakeMCPClient direct call — 仅验证 MCP adapter 自身
- L2 (harness_runtime_e2e): orchestrator → dispatcher.route(TOOL_GATE/TOOL_INVOKE/TOOL_RESULT)
- L3 (real_core_loop_runtime_e2e): route_from_runtime_loop — verified in test_mcp_l3_real_core_loop.py

---

## Phase A: MCP Tool Registration → TOOL_GATE (L2)

### Test A1: mcp_tool_enters_tool_gate
- **purpose**: 验证 MCP 工具通过 register_mcp_tools 注册后可通过 TOOL_GATE 被 lookup
- **setup**: FakeMCPClient + 单 MCP server config + register_mcp_tools → TOOL_REGISTRY 中出现 mcp__demo__hello
- **action**: dispatcher.route(TOOL_GATE, tool_name="mcp__demo__hello")
- **expected evidence**: gate_disposition in ("confirmation_required", "allowed"), production_registry_found=True, handler_name="ToolGateHandler"
- **forbidden**: gate_disposition is None, rejection_reason about allowlist
- **pass/fail**: result.status == "confirmation_required", gate_disposition in ("confirmation_required", "allowed")

### Test A2: mcp_tool_gate_blocked_for_not_registered
- **purpose**: 未注册的 MCP 工具名在 TOOL_GATE 返回 not_found
- **setup**: dispatcher with ToolGateHandler (no MCP tools registered)
- **action**: dispatcher.route(TOOL_GATE, tool_name="mcp__nonexistent__tool")
- **expected evidence**: gate_disposition is None, decision="not_found"
- **forbidden**: gate_disposition="allowed"
- **pass/fail**: evidence["decision"] == "not_found"

### Test A3: mcp_tool_risk_level_preserved
- **purpose**: TOOL_GATE 正确返回 MCP 工具的 high risk_level
- **setup**: FakeMCPClient + register_mcp_tools (MCP 工具全部 risk_level="high")
- **action**: dispatcher.route(TOOL_GATE, tool_name="mcp__demo__hello")
- **expected evidence**: risk_level="high"
- **pass/fail**: payload["risk_level"] == "high"

---

## Phase B: MCP Tool Execution → TOOL_INVOKE (L2)

### Test B1: allowed_mcp_tool_invoked_via_dispatcher
- **purpose**: MCP 工具通过 TOOL_INVOKE handler 被实际执行
- **setup**: FakeMCPClient configured with known result + register_mcp_tools
- **action**: dispatcher.route(TOOL_INVOKE, tool_name="mcp__demo__hello", tool_input={})
- **expected evidence**: disposition="invoked", tool_invoked=True, tool_output matches FakeMCPClient result, execution_status="success"
- **forbidden**: tool_invoked=False, error about not_found
- **pass/fail**: payload["disposition"] == "invoked" and payload["tool_invoked"] is True

### Test B2: mcp_tool_not_found_in_tool_invoke
- **purpose**: 不在 TOOL_REGISTRY 中的 MCP 工具名返回 not_found
- **setup**: dispatcher with ToolInvokeHandler
- **action**: dispatcher.route(TOOL_INVOKE, tool_name="mcp__nonexistent__tool", tool_input={})
- **expected evidence**: disposition="not_found", tool_invoked=False
- **pass/fail**: payload["disposition"] == "not_found"

### Test B3: mcp_tool_dangerous_flag_true
- **purpose**: MCP 工具（risk_level="high"）的 dangerous_tool_function_invoked=True
- **setup**: 同 B1
- **action**: 同 B1
- **expected evidence**: dangerous_tool_function_invoked=True, external_side_effects=False (FakeMCPClient, no real IO)
- **forbidden**: dangerous_tool_function_invoked=False
- **pass/fail**: payload["dangerous_tool_function_invoked"] is True

### Test B4: mcp_tool_external_side_effects_false
- **purpose**: MCP 工具的 external_side_effects 基于 capability 判断——mcp_tool 不在 _EXTERNAL_SIDE_EFFECT_CAPABILITIES 中，应为 False
- **setup**: 同 B1（capability="mcp_tool"）
- **action**: 同 B1
- **expected evidence**: external_side_effects=False
- **pass/fail**: evidence["external_side_effects"] is False

---

## Phase C: MCP Tool Result → TOOL_RESULT (L2)

### Test C1: mcp_tool_result_enters_tool_result_feedback
- **purpose**: MCP 工具执行结果通过 TOOL_RESULT handler 格式化
- **setup**: dispatcher with ToolResultFeedbackHandler
- **action**: dispatcher.route(TOOL_RESULT, tool_name="mcp__demo__hello", tool_output="hello from MCP", execution_status="success")
- **expected evidence**: disposition="injected", prompt_section 包含 "mcp__demo__hello" 和 "hello from MCP"
- **pass/fail**: payload["disposition"] == "injected" and "mcp__demo__hello" in payload["prompt_section"]

### Test C2: mcp_tool_error_result_truncated
- **purpose**: MCP 工具错误结果按 error disposition 处理
- **action**: dispatcher.route(TOOL_RESULT, tool_name="mcp__demo__hello", tool_output="error message", execution_status="error")
- **expected evidence**: disposition="error", prompt_section 包含 "[工具执行出错]"
- **pass/fail**: payload["disposition"] == "error"

---

## Phase D: Orchestrator — Full Pipeline (L2)

### Test D1: mcp_orchestrator_routes_through_full_pipeline
- **purpose**: orchestrator 串联 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
- **setup**: FakeMCPClient + register_mcp_tools + dispatcher with all three handlers + orchestrator
- **action**: orchestrator.execute(tool_name="mcp__demo__hello", tool_input={})
- **expected evidence**: 
  - gate_result: gate_disposition="confirmation_required"
  - invoke_result: tool_invoked=True, tool_output match
  - result: disposition="injected", prompt_section 非空
  - 三个 action 都在 dispatcher.action_log 中有记录
- **forbidden**: 
  - tool_invoked=False
  - 任何 action 走 direct call（不经过 dispatcher）
- **pass/fail**: 三个 result 的 status 均为 "success" 或 "confirmation_required"

### Test D2: orchestrator_stops_on_gate_blocked
- **purpose**: TOOL_GATE 返回 blocked/not_found 时，orchestrator 不继续 TOOL_INVOKE/TOOL_RESULT
- **setup**: dispatcher + orchestrator, no MCP tool registered
- **action**: orchestrator.execute(tool_name="mcp__nonexistent__tool", tool_input={})
- **expected evidence**: gate decision="not_found", TOOL_INVOKE 和 TOOL_RESULT 未触发
- **forbidden**: tool_invoked=True, TOOL_INVOKE event in action_log
- **pass/fail**: orchestrator returns early stop evidence, only TOOL_GATE in action_log

### Test D3: orchestrator_uses_harness_runtime_e2e_evidence
- **purpose**: orchestrator 产生的 evidence 正确分类为 harness_runtime_e2e
- **setup**: 同 D1
- **action**: 同 D1
- **expected evidence**: evidence_level == "harness_runtime_e2e", target_module_proof 存在
- **forbidden**: evidence_level == "real_core_loop_runtime_e2e" (没有从 runtime loop 进入)
- **pass/fail**: any result evidence["evidence_level"] >= "harness_runtime_e2e"

---

## Phase E: Negative / Edge Cases (L1 + L2)

### Test E1: direct_fake_mcp_client_call_is_subsystem
- **purpose**: direct FakeMCPClient.call_tool() 只能 claim subsystem_integration
- **setup**: FakeMCPClient configured with result
- **action**: client.call_tool(server, "hello", {}) → 直接调用，不经 dispatcher
- **expected evidence**: no RuntimeActionEvent generated, no target_module_proof
- **forbidden**: 任何 runtime_e2e claim
- **pass/fail**: 调用成功返回 MCPCallResult 但 action_log 中无相关记录

### Test E2: very_long_mcp_tool_name_handled_safely
- **purpose**: 异常长的 MCP tool_name 不会导致崩溃
- **action**: dispatcher.route(TOOL_GATE, tool_name="mcp__s" + "a"*500 + "__tool")
- **expected evidence**: 不崩溃，返回 not_found 或 blocked
- **pass/fail**: result.status in ("success", "rejected")

### Test E3: empty_mcp_tool_input_handled
- **purpose**: 空 tool_input 对 MCP 工具正常处理
- **setup**: FakeMCPClient + register_mcp_tools
- **action**: dispatcher.route(TOOL_INVOKE, tool_name="mcp__demo__hello", tool_input={})
- **expected evidence**: disposition="invoked", 不报 missing tool_input
- **pass/fail**: payload["disposition"] == "invoked"

### Test E4: mcp_tool_name_with_special_chars
- **purpose**: mcp_registry_tool_name 生成的名称（含 __ 分隔符）正确处理
- **setup**: FakeMCPClient + register_mcp_tools (模拟 server="demo-server", tool="hello.world")
- **action**: dispatcher.route(TOOL_GATE, tool_name="mcp__demo_server__hello_world")
- **expected evidence**: 正常 lookup，不存在时返回 not_found
- **pass/fail**: 不崩溃，result.status in ("success", "confirmation_required", "rejected")

---

## Phase F: Regression Isolation (L2)

### Test F1: existing_tool_pipeline_unchanged
- **purpose**: 本轮改动不影响已有 TOOL_GATE/TOOL_INVOKE/TOOL_RESULT 测试
- **setup**: 使用 build_phase1_dispatcher
- **action**: 对 _safe_noop 走完整 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
- **expected evidence**: 所有已有 handler 行为不变
- **forbidden**: 任何已有测试 regression
- **pass/fail**: 同 tool_invoke_branch_behavior 的 regression test 结果一致

### Test F2: existing_mcp_tests_still_pass
- **purpose**: 现有 124 个 MCP 测试不受影响
- **setup**: 不新增 import side effect
- **action**: pytest -k "mcp or MCP"
- **expected evidence**: 124 passed
- **pass/fail**: 所有已存 MCP 测试通过

---

## Deferred
- L3 real_core_loop_runtime_e2e（需 loop.py 构造 TOOL_GATE/TOOL_INVOKE/TOOL_RESULT action）
- MCP policy re-eval on each TOOL_GATE（需扩展 lookup_and_risk_check adapter）
- run_mcp_bridge() integration into runtime startup
- MCP resources/prompts
- real MCP server connection

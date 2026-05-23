# TDD: Tool Invoke Branch Behavior

Date: 2026-05-23
SPEC: [SPEC.md](SPEC.md)

## 测试分层

- L1 (subsystem_integration): handler 直接调用
- L2 (harness_runtime_e2e): dispatcher.route() with target_module_proof
- L3 (real_core_loop_runtime_e2e): DEFERRED

## Phase A: Happy Path — 工具成功调用

### A1: allowed tool 被成功 invoke

- **Purpose**: 验证 TOOL_REGISTRY 中的工具通过 handler 被实际调用
- **Setup**: 构建注册了 TOOL_INVOKE handler 的 dispatcher
- **Action**: dispatch TOOL_INVOKE with tool_name="_safe_noop", tool_input={}
- **Expected Evidence**:
  - result.status == "success"
  - payload.disposition == "invoked"
  - payload.tool_invoked == True
  - payload.tool_output 非空（_safe_noop 返回确认字符串）
  - payload.execution_status == "success"
  - evidence.tool_name == "_safe_noop"
- **Forbidden**: dangerous_tool_function_invoked != False（_safe_noop risk=low）
- **Pass/Fail**: 以上所有 assert 通过

### A2: tool_output 内容匹配工具返回值

- **Purpose**: 验证 handler 返回的工具输出与工具实际返回值一致
- **Setup**: 构建 dispatcher，注册 TOOL_INVOKE handler
- **Action**: dispatch TOOL_INVOKE with tool_name="_safe_noop"
- **Expected Evidence**:
  - payload.tool_output 包含 "_safe_noop" 或工具的确认消息
  - payload.tool_invoked == True
- **Forbidden**: tool_output 为空字符串（_safe_noop 有实际输出）
- **Pass/Fail**: tool_output 包含工具确认信息

### A3: _confirmable_noop 也可以被 invoke

- **Purpose**: 验证 confirmation="always" 的工具在 gate 放行后仍可 invoke
- **Setup**: 构建 dispatcher
- **Action**: dispatch TOOL_INVOKE with tool_name="_confirmable_noop"
- **Expected Evidence**:
  - result.status == "success"
  - payload.disposition == "invoked"
  - payload.tool_invoked == True
- **Forbidden**: disposition 不是 "invoked"
- **Pass/Fail**: 成功调用

## Phase B: Missing / Invalid Payload

### B1: 缺少 tool_name 返回 failed

- **Purpose**: 验证必填字段缺失时的防御行为
- **Setup**: 构建 dispatcher
- **Action**: dispatch TOOL_INVOKE with payload 不含 tool_name
- **Expected Evidence**:
  - result.status == "success"（handler 层面）
  - payload.disposition == "failed"
  - payload.error 包含 "tool_name"
- **Forbidden**: 崩溃/异常
- **Pass/Fail**: disposition == "failed"

### B2: 缺少 tool_input 返回 failed

- **Purpose**: 验证 tool_input 为必填字段
- **Setup**: 构建 dispatcher
- **Action**: dispatch TOOL_INVOKE with payload 不含 tool_input
- **Expected Evidence**:
  - payload.disposition == "failed"
  - payload.error 包含 "tool_input"
- **Forbidden**: 崩溃/异常
- **Pass/Fail**: disposition == "failed"

### B3: 工具不在 TOOL_REGISTRY 中返回 not_found

- **Purpose**: 验证调用不存在的工具时返回 not_found
- **Setup**: 构建 dispatcher
- **Action**: dispatch TOOL_INVOKE with tool_name="nonexistent_tool_xyz"
- **Expected Evidence**:
  - payload.disposition == "not_found"
  - payload.tool_invoked == False
  - payload.dangerous_tool_function_invoked == False
- **Forbidden**: 崩溃；tool_invoked == True；调用真实外部 API
- **Pass/Fail**: disposition == "not_found"

## Phase C: No Side Effects

### C1: handler 不修改 TOOL_REGISTRY

- **Purpose**: 验证 handler 是纯执行操作，不修改注册表
- **Setup**: 记录 TOOL_REGISTRY 初始状态
- **Action**: dispatch TOOL_INVOKE
- **Expected Evidence**: TOOL_REGISTRY keys/count 不变
- **Forbidden**: TOOL_REGISTRY 有任何修改
- **Pass/Fail**: pre/post TOOL_REGISTRY 完全一致

### C2: TOOL_INVOKE 不触发 TOOL_GATE / TOOL_RESULT

- **Purpose**: 验证 handler 不触发其他 RuntimeAction
- **Setup**: 构建 dispatcher
- **Action**: dispatch TOOL_INVOKE
- **Expected Evidence**: action_log 中只有 tool.invoke，无 tool.gate / tool.result
- **Forbidden**: 触发其他 action type
- **Pass/Fail**: action_log 只有 tool.invoke

### C3: evidence 标记 no_tool_registry_modification

- **Purpose**: 验证 evidence 正确标记无副作用
- **Setup**: 构建 dispatcher
- **Action**: dispatch TOOL_INVOKE
- **Expected Evidence**:
  - evidence.no_tool_registry_modification == True
  - evidence.no_memory_side_effects == True
- **Forbidden**: no_tool_registry_modification != True
- **Pass/Fail**: evidence 正确标记

## Phase D: Evidence Classification

### D1: dispatcher.route() 产生 harness_runtime_e2e

- **Purpose**: 验证 catalog adapter 路径获得 target_module_proof
- **Setup**: 构建 dispatcher
- **Action**: dispatch TOOL_INVOKE
- **Expected Evidence**:
  - evidence.target_module_proof is not None
  - evidence.target_catalog_allowed == True
  - evidence.target_identity_valid == True
  - evidence.evidence_level == "harness_runtime_e2e"
  - evidence.handler_name == "ToolInvokeHandler"
  - evidence.target_module == "ToolRegistry"
- **Forbidden**: evidence_level overclaim 到 real_core_loop_runtime_e2e
- **Pass/Fail**: harness_runtime_e2e

### D2: direct handler 调用不崩溃，但无 target_module_proof

- **Purpose**: 验证 handler 可独立于 dispatcher 构造
- **Setup**: 直接实例化 ToolInvokeHandler
- **Action**: handler = ToolInvokeHandler()
- **Expected Evidence**: handler 非 None
- **Forbidden**: 构造时崩溃
- **Pass/Fail**: handler 可正常构造

## Phase E: Regression Isolation

### E1: 所有已有 handler 仍注册

- **Purpose**: 验证 TOOL_INVOKE 注册不影响已有 handler
- **Setup**: build_phase1_dispatcher()
- **Action**: 检查 registry snapshot
- **Expected Evidence**: tool.gate, tool.result, memory.recall, memory.propose, memory.turn_end_proposal 都在
- **Forbidden**: 已有 handler 被替换或移除
- **Pass/Fail**: 所有已有 handler 仍注册

### E2: TOOL_GATE 仍正常工作

- **Purpose**: 回归验证 TOOL_GATE handler
- **Setup**: 通过 build_phase1_dispatcher 构建
- **Action**: dispatch TOOL_GATE with tool_name="_safe_noop"
- **Expected Evidence**: gate_disposition == "allowed"
- **Forbidden**: TOOL_GATE 行为被 TOOL_INVOKE 影响
- **Pass/Fail**: TOOL_GATE 正常

### E3: TOOL_RESULT 仍正常工作

- **Purpose**: 回归验证 TOOL_RESULT handler
- **Setup**: 通过 build_phase1_dispatcher 构建
- **Action**: dispatch TOOL_RESULT
- **Expected Evidence**: disposition in {injected, empty}, prompt_section 非空
- **Forbidden**: TOOL_RESULT 行为被 TOOL_INVOKE 影响
- **Pass/Fail**: TOOL_RESULT 正常

## Phase F: Negative / Edge Cases

### F1: 工具函数执行异常不崩溃

- **Purpose**: 验证工具函数抛异常时 handler graceful degradation
- **Setup**: 构建 dispatcher，注册一个会抛异常的工具
- **Action**: dispatch TOOL_INVOKE 调用该工具
- **Expected Evidence**:
  - result.status == "success"（handler 层面不崩溃）
  - payload.execution_status == "error"
  - payload.tool_invoked == True（函数确实被调用了）
- **Forbidden**: handler 崩溃，异常未被捕获
- **Pass/Fail**: disposition 正确标记 error

### F2: 异常长的 tool_name 不导致格式化崩溃

- **Purpose**: 边界输入测试
- **Setup**: 构建 dispatcher
- **Action**: dispatch TOOL_INVOKE with tool_name="a" * 500
- **Expected Evidence**: result.status in {success, rejected}
- **Forbidden**: handler 崩溃
- **Pass/Fail**: 不崩溃

### F3: dangerous_tool_function_invoked 正确反映风险等级

- **Purpose**: 验证 risk_level 映射到 evidence
- **Setup**: 构建 dispatcher
- **Action**: 分别 dispatch _safe_noop (risk=low) 和 _confirmable_noop
- **Expected Evidence**:
  - _safe_noop: dangerous_tool_function_invoked == False
- **Forbidden**: 所有工具都标记为 dangerous
- **Pass/Fail**: risk 映射正确

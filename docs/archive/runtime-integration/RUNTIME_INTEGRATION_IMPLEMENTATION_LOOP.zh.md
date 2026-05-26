# Runtime Integration / Runtime Action Harness — Implementation Loop

> 状态：实施计划（不包含实现代码）
> 关联文档：RFC、SDD、TDD、E2E Dogfood Plan、Audit Checklist
> 语言：简体中文为主，英文术语括注

---

## 0. 总览

```
Phase 1 (E):  修复 capability matrix naming mismatch — regression，不改新架构
Phase 2 (R):  RuntimeAction 抽象（schema + dispatcher）— 所有 Track 的基石
Phase 3 (T):  ToolRegistry Action Gate — 影响面最小，验证 gate 模式
Phase 4 (P):  Streaming E2E Evidence — 纯 evidence 收集，无行为变更
Phase 5 (C):  Checkpoint-safe Summary — turn-end / before save_checkpoint boundary，不依赖 tool event（tool execution 是可选前置步骤，非必要触发条件）
Phase 6 (S):  Skill Runtime Action — 引入 LLM tool calling
Phase 7 (A):  SubAgent L0 Runtime Action — 依赖 L0 executor + adjudication
Phase 8 (M):  Memory Runtime Hook — 依赖完整 chat() 循环
Phase 9 (综合): E08 full combined + E2E dogfood 全量重跑
```

每个 Phase 有明确的：
- **入口条件**（entry criteria）
- **允许修改的文件**（allowed files）
- **禁止修改的文件**（forbidden files）
- **停止条件**（stop condition）
- **产物**（deliverables）

---

## Phase 1：Capability Matrix 修复（Track E）

### 入口条件
- 当前代码库 clean（无未提交变更）
- `ruff check agent tests scripts` 通过
- `python -m pytest tests/ -v` 全部通过

### 允许修改的文件
- `scripts/dogfood_e2e_runtime.py`：`_capability_evidence_matrix`、`CAPABILITY_MODULE_MAPPING`
- `tests/runtime_integration/test_capability_matrix.py`（新增）

### 禁止修改的文件
- `agent/` 下所有文件
- 其他 tests/ 下文件

### 步骤

1. **定义 `CAPABILITY_MODULE_MAPPING`**（在 `scripts/dogfood_e2e_runtime.py` 中）：
   ```python
   CAPABILITY_MODULE_MAPPING = {
       "skill": ("SkillRegistry", "SkillRegistryValidation", "SkillLoader", "SkillToolBinding"),
       "subagent": ("SubAgentRegistry", "SubAgentDescriptor", "SubAgentRequest",
                    "SubAgentDelegation", "SubAgentExecutor", "SubAgentAdjudication"),
       "memory": ("FilesystemMemoryStore", "MemoryEpisodicWrite(synthetic)",
                  "MemoryConsolidationLoader", "MemoryConsolidationEngine",
                  "MemoryGovernanceCheck"),
       "provider": ("Runtime.chat", "Provider", "ModelProvider"),
       "tool_registry": ("ToolRegistry", "ToolRegistration", "ToolVisibilityFilter",
                         "ToolRiskClassification", "ToolRiskCheck"),
       "checkpoint": ("CheckpointSave", "CheckpointTruncationConfig", "CheckpointLoad"),
       "streaming": ("StreamingProtocol", "StreamingAggregation", "StreamingEdgeCases"),
       "confirmation": ("Confirmation", "ConfirmationContext"),
   }
   ```

2. **重写 `_capability_evidence_matrix`**：使用 mapping table 做 capability→module 匹配，替代当前硬编码 capability name 直接与 module name 比较的逻辑。

3. **引入 evidence level 分级**：
   - `runtime_e2e`：必须满足 SDD R.6 Runtime E2E 11 项证据链：RuntimeActionEvent emitted、RuntimeActionDispatcher routed、target handler invoked、module_invoked=true、target_module_proof exists、proof_id present、observation_independent=true、linked_action_id 匹配 action_id、linked_target_module 匹配 target_module、result returned to Parent Runtime、parent_adjudicated where applicable（Phase 1 无，暂为空）
   - `subsystem_integration`：有 systems_actually_invoked（但未经过 Runtime LLM）
   - `deterministic_baseline`：纯函数测试
   - `simulated`：systems_simulated
   - `not_covered`：无任何 evidence

4. **写 E-TEST-1,2,3**：验证 mapping table 正确性、evidence level 分级、不变式。

### 停止条件
- capability matrix 所有 entry 的 evidence level 正确分类
- `python -m pytest tests/runtime_integration/test_capability_matrix.py -v` 通过
- `python scripts/dogfood_e2e_runtime.py --all` 报告中 capability matrix 无命名 mismatch
- `ruff check agent tests scripts` 通过

### 产物
- 修改后的 `scripts/dogfood_e2e_runtime.py`
- 新增 `tests/runtime_integration/test_capability_matrix.py`

---

## Phase 2：RuntimeAction 抽象（Track R）

### 入口条件
- Phase 1 全部停止条件满足

### 允许修改的文件
- `agent/runtime_integration/`（新目录，全部新文件）
  - `__init__.py`
  - `schema.py`（RuntimeActionType, RuntimeActionRequest, RuntimeActionResult, RuntimeActionEvent）
  - `dispatcher.py`（RuntimeActionDispatcher, ActionHandlerRegistry）
- `tests/runtime_integration/__init__.py`
- `tests/runtime_integration/test_runtime_action_schema.py`（新增）
- `tests/runtime_integration/test_runtime_action_dispatcher.py`（新增）
- `tests/runtime_integration/test_runtime_action_event.py`（新增）
- `tests/runtime_integration/test_runtime_action_dispatcher_negative.py`（新增）

### 禁止修改的文件
- `agent/` 下除 `agent/runtime_integration/` 外的所有文件
- `scripts/dogfood_e2e_runtime.py`（Phase 1 完成后不再修改）

### 步骤

1. **定义 enum 和 dataclass**（`agent/runtime_integration/schema.py`）：
   - `RuntimeActionType(StrEnum)`：6 个 action type
   - `RuntimeActionRequest`：frozen dataclass，含 action_type, source, parent_trace_id, payload, constraints, created_at
   - `RuntimeActionResult`：frozen dataclass，含 action_type, status, payload, evidence, error_safe_preview, latency_ms, timestamp
   - `RuntimeActionEvent`：frozen dataclass，含 event_id, action_type, source, status, evidence, parent_trace_id, timestamp

2. **定义 ActionHandler protocol**（`agent/runtime_integration/dispatcher.py`）：
   ```python
   class ActionHandler(Protocol):
       def handle(self, request: RuntimeActionRequest) -> RuntimeActionResult: ...
   ```

3. **定义 ActionHandlerRegistry**：dict-like，将 RuntimeActionType 映射到 ActionHandler。

4. **实现 RuntimeActionDispatcher.route()**：
   - 查询 registry
   - 调用 handler.handle(request)
   - 产生 RuntimeActionEvent 并存入 action log
   - 返回 RuntimeActionResult

5. **写 TDD 测试**：先 RED 后 GREEN。

### 停止条件
- R-TEST-1,2,3,4 全部通过
- `python -m pytest tests/runtime_integration/ -v` 全部通过
- `ruff check agent/runtime_integration/ tests/runtime_integration/` 通过
- 全量回归 `python -m pytest tests/ -v` 通过（新代码不影响现有测试）

### 产物
- `agent/runtime_integration/__init__.py`
- `agent/runtime_integration/schema.py`
- `agent/runtime_integration/dispatcher.py`
- `tests/runtime_integration/__init__.py`
- `tests/runtime_integration/test_runtime_action_schema.py`
- `tests/runtime_integration/test_runtime_action_dispatcher.py`
- `tests/runtime_integration/test_runtime_action_event.py`
- `tests/runtime_integration/test_runtime_action_dispatcher_negative.py`

---

## Phase 3：ToolRegistry Action Gate（Track T）

### 入口条件
- Phase 2 全部停止条件满足

### 允许修改的文件
- `agent/runtime_integration/`（添加 tool gate handler）
- `agent/core.py`（在 tool calling 循环中集成 RuntimeActionDispatcher）
- `tests/runtime_integration/test_tool_registry_action_gate.py`（新增）
- `tests/runtime_integration/test_tool_registry_action_gate_negative.py`（新增）

### 禁止修改的文件
- `agent/tool_registry.py`（不改变 ToolRegistry 内部逻辑）
- `agent/core_contexts.py`

### 步骤

1. **实现 `ToolGateHandler`**：接收 `tool.request`，查询 ToolRegistry，返回 gate_disposition + risk_level。
   - gate_disposition 是 handler-level immediate output，合法值只包括 `allowed` / `rejected` / `confirmation_required`。
   - evidence.decision 是 RuntimeActionResult / capability matrix 的 final evidence-level classification，合法值包括 `allowed` / `rejected` / `confirmation_required` / `not_found` / `blocked`。
   - 映射关系固定：gate_disposition=allowed → evidence.decision=allowed；gate_disposition=rejected → evidence.decision=rejected；gate_disposition=confirmation_required → evidence.decision=confirmation_required；production registry missing → evidence.decision=not_found；fake high-risk dogfood blocked path → evidence.decision=blocked。
   - `not_found` / `blocked` 不得作为真实工具 gate_disposition。

2. **在 `chat()` 中集成**：
   - 创建 RuntimeActionDispatcher 实例
   - 在 tool calling 执行前，将 tool call 包装为 `tool.request` RuntimeAction
   - 根据返回的 gate_disposition 决定真实 production tool 是否执行：
     - `allowed` → 执行 tool
     - `rejected` → 返回错误给 LLM
     - `confirmation_required` → 触发 ConfirmationContext
   - fake. 前缀高风险 dogfood tool 不进入 production ToolRegistry，不进入 production capability matrix，不走 confirmation_required；它只在 dogfood-local fake tool overlay 中解析，最终 evidence.decision 必须是 `blocked`。
   - fake high-risk blocked path evidence 必须包含 requested_tool_name、requested_capability、production_registry_found=false、dogfood_overlay_found=true、overlay_tool_name、resolved_test_tool_name、registry_handler_invoked=true、target_module_invoked=true、dangerous_tool_function_invoked=false、evidence.decision=blocked。
   - 以下均为 fail：production_registry_found=true for fake.*；dogfood_overlay_found=false for fake.*；dangerous_tool_function_invoked=true；fake.* persisted into production ToolRegistry；fake.* exposed to normal runtime；fake.* appears in production capability matrix as real capability；fake high-risk blocked path evidence.decision=confirmation_required。

3. **不改变**：
   - ToolRegistry 内部逻辑
   - confirmation 流程
   - `execute_tool_call` 的行为

### 停止条件
- T-TEST-1,2,3,4 全部通过
- `python -m pytest tests/runtime_integration/ -v` 全部通过
- 现有 E05 scenario（ToolRegistry subsystem integration）仍然通过
- 全量回归通过

### 产物
- `agent/runtime_integration/tool_gate.py`
- `tests/runtime_integration/test_tool_registry_action_gate.py`
- `tests/runtime_integration/test_tool_registry_action_gate_negative.py`
- `agent/core.py`（最小修改：集成 dispatcher 到 tool calling 循环）

---

## Phase 4：Streaming E2E Evidence（Track P）

### 入口条件
- Phase 3 全部停止条件满足

### 允许修改的文件
- `agent/runtime_integration/`（添加 streaming evidence collector）
- `agent/core.py`（在 streaming 交互后触发 evidence 收集）
- `tests/runtime_integration/test_streaming_evidence.py`（新增）
- `tests/runtime_integration/test_streaming_evidence_negative.py`（新增）

### 禁止修改的文件
- `agent/provider.py`（不改变 provider streaming 行为）
- `agent/streaming.py`（如有独立 streaming 模块）

### 步骤

1. **实现 `StreamingEvidenceCollector`**：在每次 streaming 交互完成后收集 evidence 字段。

2. **在 `chat()` 中集成**：每次 LLM 调用完成后（streaming 结束），记录 streaming.event。

3. **不改变**：`collect_stream_response` / `sanitize_stream_text` 的行为。

### 停止条件
- P-TEST-1,2,3 全部通过
- `python -m pytest tests/runtime_integration/ -v` 全部通过
- 现有 E07 scenario（Streaming subsystem integration）仍然通过
- 全量回归通过

**R.6 proof 强制停止条件（审计 P1-3 新增）**:
- 如果 implementation 只能提供 RuntimeActionEvent，不得继续标 runtime_e2e，必须 stop / downgrade
- 如果只能提供 module_invoked=true 而无 target_module_proof，不得继续标 runtime_e2e，必须 stop / downgrade
- 如果 target_module_proof 无法绑定 action_id 和 target_module，必须 stop
- 如果 streaming path 只能 direct subsystem invocation，必须 stop 或标 subsystem_integration
- 如果 full proof 无法在 capability matrix 中引用，必须 stop
- 如果 scenario-level pass condition 没有内联 R.6 proof，必须 stop
- **不得**先做 event-only pass 再后补 proof——没有 proof 就不能 runtime_e2e
- **不得**把"后续审计补证据"写成可接受路径

### 产物
- `agent/runtime_integration/streaming_evidence.py`
- `tests/runtime_integration/test_streaming_evidence.py`
- `tests/runtime_integration/test_streaming_evidence_negative.py`

---

## Phase 5：Checkpoint-safe Summary（Track C）

### 入口条件
- Phase 4 全部停止条件满足

### 允许修改的文件
- `agent/runtime_integration/`（添加 checkpoint summary handler）
- `agent/core.py`（在 save_checkpoint 前触发 checkpoint.safe_summary）
- `tests/runtime_integration/test_checkpoint_safe_summary.py`（新增）
- `tests/runtime_integration/test_checkpoint_safe_summary_negative.py`（新增）

### 禁止修改的文件
- `agent/checkpoint.py`（不改变 Checkpoint schema 和 save/load 逻辑）

### 步骤

1. **实现 `CheckpointSafeSummaryHandler`**：接收 runtime state summary，redact secret-like content，标记 huge prompt，标记 pending high-risk tool。

2. **在 `chat()` 中集成**：在 turn-end / before save_checkpoint（checkpoint boundary）触发 checkpoint.safe_summary 的 generation。tool execution 是可选的前置步骤，不是 checkpoint hook 的必要触发条件——无 tool 的 user turn 也必须能触发 checkpoint safe summary / save_checkpoint boundary。

3. **不改变**：`save_checkpoint` 的调用时机/逻辑、Checkpoint schema。

### 停止条件
- C-TEST-1,2,3,4,5 全部通过
- `python -m pytest tests/runtime_integration/ -v` 全部通过
- 现有 E06 scenario（Checkpoint subsystem integration）仍然通过
- 全量回归通过

**R.6 proof 强制停止条件（审计 P1-3 新增）**:
- 如果 checkpoint safe summary 只能在 tool 执行后触发，E06 不得标 runtime_e2e pass，必须 stop
- 如果 checkpoint save path 缺少 target_module_proof，必须 stop / downgrade
- 如果 implementation 只能提供 RuntimeActionEvent + module_invoked=true 而无 target_module_proof，不得标 runtime_e2e，必须 stop
- 如果 checkpoint path 只能 direct subsystem invocation，必须 stop 或标 subsystem_integration
- **不得**混淆 Memory turn-end proposal hook 与 Checkpoint hook——两者是不同边界

### 产物
- `agent/runtime_integration/checkpoint_summary.py`
- `tests/runtime_integration/test_checkpoint_safe_summary.py`
- `tests/runtime_integration/test_checkpoint_safe_summary_negative.py`

---

## Phase 6：Skill Runtime Action（Track S）

### 入口条件
- Phase 5 全部停止条件满足

### 允许修改的文件
- `agent/runtime_integration/`（添加 skill action handler）
- `agent/core.py`（注册 skill.select 为 RuntimeAction handler）
- `tests/runtime_integration/test_skill_runtime_action.py`（新增）
- `tests/runtime_integration/test_skill_runtime_action_negative.py`（新增）

### 禁止修改的文件
- `agent/skill_system/`（不改变 Skill 系统内部行为）
- `agent/tool_registry.py`

### 步骤

1. **实现 `SkillRuntimeActionHandler`**：
   - 接收 skill.select action
   - 从 SkillRegistry 获取 available skills 的 metadata（不含 body，不含 status 字段——hidden/disabled skill 不出现）
   - **handler 只做验证不做选择**：从 `RuntimeActionRequest.payload.model_decision_metadata` 提取 selected_skill_id、selection_reason、selection_confidence，验证 skill 存在且 status=active，不自行决定选哪个
   - selection metadata 缺失、未链接到 model_decision_metadata、或与兼容字段不一致时，必须 fail / downgrade，不得 runtime_e2e pass
   - handler 不得后验补 selection_reason / selection_confidence，不得二次调用 LLM 创建 metadata，不得从 assistant 自然语言文本中推断 metadata
   - 验证通过后才加载 body（调用 SkillLoader.load_body()）
   - 在 structured invocation_proof 中记录 SkillLoader.load_body() 调用（call_id + function_called + call_signature + observed_at）
   - 返回 payload：selected_skill_id、selection_reason、selection_confidence（均来自 model_decision_metadata）、body_load_decision、allowed_tools_after_selection、no_suitable_skill、available_skills_count
   - hidden/disabled 排除信息不进入 payload——仅通过 evidence.audit_only_skill_exclusion_evidence 提供（excluded_count、hidden_or_disabled_exclusion_verified、redacted_exclusion_reason_categories）

2. **渐进式披露实现**：
   - `available_skill_metadata` 列表中的每个 skill 只有 skill_id/description/tags/risk_level（**无 body，无 status**）
   - body 在 handler 验证 selected_skill_id 后才由 `SkillLoader.load_body()` 加载

3. **约束检查**：
   - hidden/disabled skill 不在 available_skill_metadata 中（其名称不在任何 evidence 中暴露，仅通过 audit_only_skill_exclusion_evidence.excluded_count 计数，不进入 payload）
   - 缺 version/description 的 skill 不在 available_skill_metadata 中（已有 `get_load_errors()` 支持）
   - selected skill 的 allowed_tools 不得超出 skill descriptor 声明的范围
   - selected_skill_id / selection_reason / selection_confidence 必须来自 RuntimeActionRequest.payload.model_decision_metadata，handler 只做验证和记录，不得自行决定、后验补、二次调用 LLM 或从文本推断

### 停止条件
- S-TEST-1,2,3,4 全部通过
- `python -m pytest tests/runtime_integration/ -v` 全部通过
- 现有 E02 scenario（Skill subsystem integration）仍然通过
- 全量回归通过

### 产物
- `agent/runtime_integration/skill_action.py`
- `tests/runtime_integration/test_skill_runtime_action.py`
- `tests/runtime_integration/test_skill_runtime_action_negative.py`

---

## Phase 7：SubAgent L0 Runtime Action（Track A）

### 入口条件
- Phase 6 全部停止条件满足

### 允许修改的文件
- `agent/runtime_integration/`（添加 subagent action handler）
- `agent/core.py`（注册 subagent.delegate_l0 为 RuntimeAction handler）
- `tests/runtime_integration/test_subagent_runtime_action.py`（新增）
- `tests/runtime_integration/test_subagent_runtime_action_negative.py`（新增）

### 禁止修改的文件
- `agent/subagent_system/`（不改变 SubAgent 系统内部行为）
- `agent/tool_registry.py`

### 步骤

1. **实现 `SubAgentRuntimeActionHandler`**：
   - 接收 subagent.delegate_l0 action
   - **handler 只做验证不做选择**：从 `request.payload.subagent_name`（model tool-call arguments）提取 LLM 指定的 SubAgent name，验证该 SubAgent 存在且 status=active
   - 检查 SubAgent L0 边界（见下方 allowed/prohibited 列表）
   - 验证 allowed_tools ⊆ SubAgent descriptor allowed_tools
   - 调用 `delegate_once(request, registry)`
   - 执行 parent adjudication
   - 在 structured invocation_proof 中记录 delegate_once 调用结果和 adjudication 结论（call_id + function_called + call_signature + observed_at）
   - 返回 execution_result + adjudication

2. **SubAgent L0 边界硬性检查**：
   - **明确允许**：单个 SubAgent L0 确定性执行、descriptor allowed_tools 子集内执行、parent adjudication、仅限 `subagent.delegate_l0` RuntimeAction
   - **明确禁止**：L1/L2 层级委派、嵌套 delegation、自主规划（autonomous planning）、多智能体协作（multi-agent）、并行委派（parallel delegation）、workspace automation、memory handoff、shell/external process、SubAgent 内使用真实 LLM、绕过 parent adjudication
   - 在 SubAgent 执行上下文中标记 `in_delegation_context=True`
   - 如果已经在 delegation 上下文中，拒绝新的 delegate_l0 请求

### 停止条件
- A-TEST-1,2,3,4,5 全部通过
- `python -m pytest tests/runtime_integration/ -v` 全部通过
- 现有 E03 scenario（SubAgent subsystem integration）仍然通过
- 全量回归通过

### 产物
- `agent/runtime_integration/subagent_action.py`
- `tests/runtime_integration/test_subagent_runtime_action.py`
- `tests/runtime_integration/test_subagent_runtime_action_negative.py`

---

## Phase 8：Memory Runtime Hook（Track M）

### 入口条件
- Phase 7 全部停止条件满足

### 允许修改的文件
- `agent/runtime_integration/`（添加 memory hook handler）
- `agent/core.py`（在 chat() 循环中插入 memory hook point）
- `tests/runtime_integration/test_memory_runtime_hook.py`（新增）
- `tests/runtime_integration/test_memory_runtime_hook_negative.py`（新增）

### 禁止修改的文件
- `agent/memory_system/`（不改变 consolidation pipeline 内部行为）
- `agent/tool_registry.py`

### 步骤

1. **实现 `MemoryHookHandler`**：
   - 在 `chat()` 的 turn 结束后触发（turn-end hook），无论是否发生 tool execution
   - 接收 conversation_turn + model_output_summary
   - 运行 secret-like filtering
   - 判断是否 memory-worthy
   - 如有 → 触发 `run_consolidation_pipeline`（proposal→pending_review）
   - 返回 proposal_id + disposition

2. **Hook point 实现**：
   - 在 `chat()` 主循环中，turn 结束后插入（turn-end hook，不依赖 tool execution）：
   ```python
   # AFTER user turn + model response (turn-end hook), regardless of tool execution
   memory_hook_result = dispatcher.route(
       RuntimeActionRequest(
           action_type=RuntimeActionType.MEMORY_PROPOSE,
           source="runtime_policy",
           ...
       ),
       registry=registry,
   )
   ```

3. **不改变**：consolidation pipeline 内部逻辑、Memory governance（proposal→pending_review→confirmed/rejected）

### 停止条件
- M-TEST-1,2,3,4 全部通过
- `python -m pytest tests/runtime_integration/ -v` 全部通过
- 现有 E04 scenario（Memory subsystem integration）仍然通过
- 全量回归通过

### 产物
- `agent/runtime_integration/memory_hook.py`
- `tests/runtime_integration/test_memory_runtime_hook.py`
- `tests/runtime_integration/test_memory_runtime_hook_negative.py`

---

## Phase 9：E08 Full Combined + E2E Dogfood 全量重跑

### 入口条件
- Phase 2-8 全部停止条件满足
- 所有 Track 的 handler 已注册到 ActionHandlerRegistry

### 允许修改的文件
- `scripts/dogfood_e2e_runtime.py`（重写 E02-E08 场景，使用 RuntimeAction events 验证）
- `tests/runtime_integration/test_capability_matrix.py`（E-TEST-4）

### 禁止修改的文件
- `agent/` 下所有文件（Phase 8 之后冻结）
- `tests/` 下除 `tests/runtime_integration/` 外的文件

### 步骤

1. **重写 E02-E07 scenarios**：
   - 原 `direct_subsystem_invocation` 场景降级为 subsystem integration test（移入 `tests/` 下独立测试文件）
   - 新场景必须通过 `core.chat()` + real LLM 触发
   - pass 条件基于 SDD R.6 Runtime E2E 11 项证据链，不得只基于 RuntimeActionEvent

2. **重写 E08 场景**（full combined）：
   - 要求 LLM 在一个对话中触发至少 4 种 RuntimeAction：
     - `skill.select`
     - `subagent.delegate_l0`
     - `memory.propose`
     - `tool.request`
   - pass 条件：至少 3 个 different action_type 的 RuntimeActionEvent 在 action log 中，且每个 runtime_e2e event 满足 R.6 11 项证据链（含 target_module_proof.proof_id、linked_action_id、linked_target_module）
   - 不能仅凭 "模型文本提到" 通过

3. **验证 capability matrix**：
   - 只有满足 SDD R.6 Runtime E2E 11 项证据链的 capability 才能标记为 `runtime_e2e`
   - 有 RuntimeActionEvent 但 module_invoked=false、invocation_proof 为 None、target_module_proof 缺失、proof_id 缺失、observation_independent=false、linked_action_id 不匹配或 linked_target_module 不匹配的 capability → 最高 `subsystem_integration`
   - RuntimeActionEvent + handler_name + target_module + module_invoked=true 但无独立 target_module_proof → 最高 `subsystem_integration`
   - 无 RuntimeActionEvent 但有 subsystem integration 的标记为 `subsystem_integration`
   - 运行 E-TEST-4

4. **全量 dogfood 重跑**：
   ```bash
   python scripts/dogfood_e2e_runtime.py --all
   ```

### 停止条件
- E2E dogfood 报告中 `actual_runtime_invoked` scenario ≥ 6
- `direct_subsystem_invocation` scenario ≤ 3
- capability matrix 无 naming mismatch
- 没有 capability 被错误标记为 `runtime_e2e`
- `ruff check agent tests scripts` 通过
- `python -m pytest tests/ -v` 全量通过

### 产物
- 重写后的 `scripts/dogfood_e2e_runtime.py`
- 更新后的 `tests/runtime_integration/test_capability_matrix.py`

---

## 新增目录结构

```
agent/runtime_integration/
├── __init__.py                       # 公开 API：RuntimeActionRequest, RuntimeActionResult, RuntimeActionDispatcher, ...
├── schema.py                         # RuntimeActionType, dataclass 定义
├── dispatcher.py                     # RuntimeActionDispatcher, ActionHandlerRegistry, ActionHandler protocol
├── tool_gate.py                      # Track T: ToolGateHandler
├── streaming_evidence.py             # Track P: StreamingEvidenceCollector
├── checkpoint_summary.py             # Track C: CheckpointSafeSummaryHandler
├── skill_action.py                   # Track S: SkillRuntimeActionHandler（handler 只验证 model_decision_metadata）
├── subagent_action.py                # Track A: SubAgentDelegateHandler
└── memory_hook.py                    # Track M: MemoryHookHandler

tests/runtime_integration/
├── __init__.py
├── test_runtime_action_schema.py
├── test_runtime_action_dispatcher.py
├── test_runtime_action_event.py
├── test_runtime_action_dispatcher_negative.py
├── test_tool_registry_action_gate.py
├── test_tool_registry_action_gate_negative.py
├── test_streaming_evidence.py
├── test_streaming_evidence_negative.py
├── test_checkpoint_safe_summary.py
├── test_checkpoint_safe_summary_negative.py
├── test_skill_runtime_action.py
├── test_skill_runtime_action_negative.py
├── test_subagent_runtime_action.py
├── test_subagent_runtime_action_negative.py
├── test_memory_runtime_hook.py
├── test_memory_runtime_hook_negative.py
└── test_capability_matrix.py
```

---

---

## 全局 Stop Conditions（审计 P2-2 新增）

只要出现以下任一情况，必须立即停止 Implementation Loop：

1. 需要 SubAgent L1/L2
2. 需要 shell / external process / worktree
3. 需要 checkpoint schema change
4. 需要 Memory governance change
5. 需要 ToolRegistry authority change
6. 需要读取 .env 内容
7. 需要真实 sessions / runs / memory episodes
8. E2E dogfood 只能靠 direct subsystem invocation（无法通过 chat() 验证）
9. capability matrix 无法提供真实 module invocation evidence（module_invoked 始终为 false）
10. RuntimeActionEvent 不能绑定真实 handler / module invocation
11. full pytest 失败
12. 出现 P0 / P1 / P2 阻塞项未解决
13. 需要扩大 Observability（metrics / dashboard / trace viewer）
14. 需要 DB / graph / embedding 作为依赖
15. 需要真实 shell-like tool 执行

## Implementation Notes 要求（审计 P2-2 新增）

实现时必须维护以下文件：

**路径**：`docs/implementation-notes/RUNTIME_INTEGRATION_IMPLEMENTATION_NOTES.md`

要求：
1. 必须边做边记，不要最后补
2. 每个 Phase 完成后追加记录
3. 记录内容至少包括：
   - spec gaps（规格与实际实现之间的差距）
   - assumptions（做出的假设）
   - tradeoffs（关键的取舍和理由）
   - deviations（与 SDD/TDD 的偏差及原因）
   - stop condition near misses（差一点触发的 stop condition）
   - action evidence design decisions（关于 evidence 收集的设计决策）
   - runtime_e2e 判定争议（任何关于 runtime_e2e vs subsystem_integration 的判定争议）
   - deferred risks（推迟处理的风险）
4. 后续独立审计必须读取 implementation notes

## 实现完成后的独立审计 Gate（审计 P2-2 新增）

- Implementation Loop 完成后**不得直接 push**
- 必须先做 **independent runtime integration implementation audit**
- Audit 必须验证：
  - action evidence 完整性（每个 runtime_e2e capability 满足 Action Evidence Contract 全部条件）
  - module invocation 真实性（R.6 Runtime E2E 11 项证据链：proof_id、observation_independent、linked_action_id、linked_target_module 均完整）
  - target_module_proof 独立观测（观测源 ≠ handler，非自我填充）
  - E2E dogfood 可信度（pass 条件是否被诚实满足，有无自欺）
  - tool alias 正确性（resolved_tool_name 来自 ToolRegistry）
  - 全局 stop conditions 未被触发
- Audit 通过后，才可进入 push/pre-release 流程

---

## 设计约束重申

以下约束在所有 Phase 中适用：

1. **不新增 module-level global singleton**：Dispatcher 是实例化的，不依赖全局状态。
2. **不引入循环依赖**：`agent/runtime_integration/` 可以 import 子系统模块，子系统模块不 import runtime_integration。
3. **不做业务逻辑**：Dispatcher 只路由，Handler 只桥接子系统 API，不实现新的业务规则。
4. **不推进 Runtime state**：RuntimeAction 不改变 task status / conversation / plan。
5. **不做 Observable/Metrics**：不引入 dashboard、trace viewer、metrics 系统。
6. **不改变子系统内部行为**：Skill/SubAgent/Memory/ToolRegistry/Checkpoint/Streaming 的内部逻辑不受影响。
7. **所有新代码加中文学习型注释**。

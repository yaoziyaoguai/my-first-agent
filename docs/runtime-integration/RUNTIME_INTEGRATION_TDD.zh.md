# Runtime Integration / Runtime Action Harness — TDD（测试计划）

> 状态：测试规格（不包含实现代码）
> 关联文档：RFC、SDD、Implementation Loop、E2E Dogfood Plan、Audit Checklist
> 语言：简体中文为主，英文术语括注

---

## 0. 测试概览

```
测试层次（内→外）：
  characterization → unit → integration → negative → E2E dogfood

每个 Track 的测试覆盖至少 4 层（unit/integration/negative/E2E dogfood），
characterization 用于 E 类（现有模块重构）。

pass 条件：
  - 所有必选测试通过
  - 覆盖率 ≥ 80%（新代码）
  - E2E dogfood action event 证据 ≥ 6 个 Track
```

---

## 测试分层定义

| 层次 | 定义 | 涉及范围 | 是否 mock LLM |
|------|------|----------|---------------|
| characterization | 拍平现有行为，确保重构不破坏语义 | 现有模块 | 不需要 LLM |
| unit | 单函数/单类/单 dataclass，隔离依赖 | 新代码 | 不需要 |
| integration | 多模块协作，经过 RuntimeActionDispatcher 路由 | 新+旧模块 | mock Runtime LLM（fake tool call） |
| negative | 非法输入、边界条件、错误路径 | 所有 | 不需要 |
| E2E dogfood | 真实 `core.chat()` + real LLM，通过 RuntimeAction events 验证 | 全链路 | 真实 LLM |

---

## 通用测试工具

```python
# 所有测试共享的 fake/fixture 工厂
# 位置：tests/conftest.py（新增）或 tests/runtime_integration/conftest.py

@pytest.fixture
def fake_runtime_action_request():
    """构造合法 RuntimeActionRequest 的工厂 fixture"""
    def _make(action_type, source="llm_tool_call", payload=None, constraints=None):
        return RuntimeActionRequest(
            action_type=action_type,
            source=source,
            parent_trace_id=str(uuid4()),
            payload=payload or {},
            constraints=constraints or set(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    return _make

@pytest.fixture
def fake_action_handler_registry():
    """构造最小 ActionHandlerRegistry，注册 fake handler"""
    ...
```

---

## Track R：Runtime Action Harness 测试

### R-TEST-1：Schema stability（unit）

```
测试目标：RuntimeActionRequest / RuntimeActionResult / RuntimeActionEvent 序列化稳定性
测试文件：tests/runtime_integration/test_runtime_action_schema.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_request_frozen_no_mutation` | RuntimeActionRequest(...) | 尝试修改字段抛出 FrozenInstanceError |
| 2 | `test_result_frozen_no_mutation` | RuntimeActionResult(...) | 同上 |
| 3 | `test_event_frozen_no_mutation` | RuntimeActionEvent(...) | 同上 |
| 4 | `test_request_asdict_roundtrip` | 合法 request → asdict → 重建 | 字段值一致 |
| 5 | `test_result_status_must_be_valid` | status="invalid_status" | 构造时抛出 ValueError |
| 6 | `test_result_evidence_no_secret` | evidence 含 key="sk-xxx" | 构造时抛出 SecretPatternError |
| 7 | `test_action_type_enum_values` | 枚举所有成员 | 6 个值：skill.select, subagent.delegate_l0, memory.propose, tool.request, checkpoint.safe_summary, streaming.event |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_runtime_action_schema.py -v
```

### R-TEST-2：Dispatcher routing（unit）

```
测试目标：RuntimeActionDispatcher.route() 正确路由到对应 handler
测试文件：tests/runtime_integration/test_runtime_action_dispatcher.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_route_skill_select_to_skill_handler` | action_type=skill.select | handler 被调用，返回 payload 含 selected_skill_id |
| 2 | `test_route_subagent_delegate_to_subagent_handler` | action_type=subagent.delegate_l0 | handler 被调用，返回 payload 含 adjudication |
| 3 | `test_route_memory_propose_to_memory_handler` | action_type=memory.propose | handler 被调用，返回 payload 含 proposal_id |
| 4 | `test_route_tool_request_to_tool_handler` | action_type=tool.request | handler 被调用，返回 payload 含 disposition |
| 5 | `test_route_checkpoint_summary_to_checkpoint_handler` | action_type=checkpoint.safe_summary | handler 被调用，返回 payload 含 safe_summary |
| 6 | `test_route_unknown_action_type_returns_not_supported` | action_type="nonexistent.action" | status="not_supported" |
| 7 | `test_dispatcher_produces_action_event` | 合法 request | RuntimeActionEvent 写入 action log |
| 8 | `test_dispatcher_never_mutates_registry` | registry snapshot before/after route() | registry 不变 |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_runtime_action_dispatcher.py -v
```

### R-TEST-3：Action event evidence（unit）

```
测试目标：每个成功的 route() 产生不可变的 action event
测试文件：tests/runtime_integration/test_runtime_action_event.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_event_id_unique_per_call` | 2 次 route() | 2 个 event 的 event_id 不同 |
| 2 | `test_event_parent_trace_id_matches_request` | request.parent_trace_id="tr-001" | event.parent_trace_id == "tr-001" |
| 3 | `test_event_status_matches_result` | 被 handler 返回 status="success" | event.status == "success" |
| 4 | `test_event_timestamp_monotonic` | 2 次 route() | event2.timestamp >= event1.timestamp |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_runtime_action_event.py -v
```

### R-TEST-4：Dispatcher boundary enforcement（negative）

```
测试目标：Dispatcher 不做业务逻辑，不推进 Runtime state
测试文件：tests/runtime_integration/test_runtime_action_dispatcher_negative.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_dispatcher_no_durable_state` | 2 个独立 Dispatcher 实例 | 各自的 action log 不共享 |
| 2 | `test_dispatcher_no_runtime_state_mutation` | route() 前后 RuntimeState 快照 | RuntimeState 不变 |
| 3 | `test_dispatcher_no_direct_tool_execution` | tool.request 类型 | handler 返回 disposition，不实际执行 tool |
| 4 | `test_dispatcher_no_network_access` | 任意 request | 不发起网络请求（通过 mock socket 断言） |
| 5 | `test_dispatcher_no_dotenv_access` | 任意 request | 不访问 .env（通过 mock os.environ 断言） |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_runtime_action_dispatcher_negative.py -v
```

### R-TEST-5：E2E dogfood verification

```
测试目标：真实 core.chat() 中 RuntimeActionDispatcher 产生 action events
场景编号：E01（base runtime）
pass 条件：至少 1 个 RuntimeActionEvent（tool.request 类型）出现在 action log 中
```

**pytest 命令**（由 E2E dogfood runner 驱动）：
```bash
python scripts/dogfood_e2e_runtime.py --scenario E01
```

---

## Track S：Skill Runtime Action 测试

### S-TEST-1：Skill action schema（unit）

```
测试目标：skill.select 的 payload 格式正确
测试文件：tests/runtime_integration/test_skill_runtime_action.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_skill_select_payload_must_have_task_summary` | payload 缺 task_summary | 构造时抛出 ValidationError |
| 2 | `test_skill_select_output_must_have_selection_reason` | 正常路由 | payload 含 selection_reason（非空 str） |
| 3 | `test_skill_select_output_allowed_tools_non_empty` | 选中的 skill 有 tools | allowed_tools 非空列表 |

### S-TEST-2：Progressive disclosure preserved（integration）

```
测试目标：available_skills 只含 metadata，body 在选中后才加载
测试文件：tests/runtime_integration/test_skill_runtime_action.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_available_skills_no_body_in_payload` | skill.select 请求 | payload.available_skills 中每个 skill 只有 name/description/tags/risk_level，无 body |
| 2 | `test_body_loaded_only_after_selection` | skill.select → 选中后 | 选中 skill 的 body 在返回 payload 中存在，未选中的不存在 |
| 3 | `test_hidden_skill_not_in_available` | registry 中有 hidden skill | available_skills 不包含该 skill |
| 4 | `test_disabled_skill_not_in_available` | registry 中有 disabled skill | available_skills 不包含该 skill |
| 5 | `test_skill_missing_version_not_in_available` | registry 中有缺 version 的 skill（已在 get_load_errors 中） | available_skills 不包含该 skill |

### S-TEST-3：Skill tool binding boundary（integration）

```
测试目标：selected skill 的 allowed_tools 不超过 descriptor 声明
测试文件：tests/runtime_integration/test_skill_runtime_action.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_selected_skill_tools_subset_of_descriptor` | skill 声明 allowed_tools=["read", "grep"] | 返回的 allowed_tools ⊆ {"read", "grep"} |
| 2 | `test_skill_not_execute_tools_directly` | skill.select action | tool execution 走 Track T，skill action 不直接执行 |

### S-TEST-4：Skill selection failure modes（negative）

```
测试目标：skill.select 的边界和错误路径
测试文件：tests/runtime_integration/test_skill_runtime_action_negative.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_skill_select_empty_available_list` | available_skills=[] | status="success", selected_skill_id=None, no_suitable_skill=True |
| 2 | `test_skill_select_task_summary_too_long` | task_summary 超 10KB | status="rejected" |
| 3 | `test_skill_select_constraint_read_only_blocks_write_skills` | constraints={"read_only"} | 选中的 skill 的 allowed_tools 不含 write 类 tool |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_skill_runtime_action.py tests/runtime_integration/test_skill_runtime_action_negative.py -v
```

### S-TEST-5：E2E dogfood verification

```
测试目标：真实 core.chat() + real LLM 通过 tool calling 选择 skill
场景编号：E02（skill runtime）
pass 条件：
  - RuntimeActionEvent(action_type="skill.select") 存在于 action log
  - event.evidence["body_loaded"] == true
  - event.evidence["selected_skill_id"] 非空

注意：此场景替代原始 E02（直接调用 SkillRegistry API）。
      原始 E02 降级为 subsystem integration test。
```

**pytest 命令**（由 E2E dogfood runner 驱动）：
```bash
python scripts/dogfood_e2e_runtime.py --scenario E02
```

---

## Track A：SubAgent L0 Runtime Action 测试

### A-TEST-1：SubAgent action schema（unit）

```
测试目标：subagent.delegate_l0 的 payload 格式正确
测试文件：tests/runtime_integration/test_subagent_runtime_action.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_delegate_payload_must_have_delegation_goal` | payload 缺 delegation_goal | 构造时抛出 ValidationError |
| 2 | `test_delegate_payload_budget_max_iterations_positive` | max_iterations=0 | 构造时抛出 ValidationError |
| 3 | `test_delegate_output_must_have_adjudication` | 正常路由 | payload 含 adjudication ∈ {"accept", "reject", "needs_review"} |

### A-TEST-2：Parent adjudication preserved（integration）

```
测试目标：SubAgent delegation 必须经过 parent adjudication
测试文件：tests/runtime_integration/test_subagent_runtime_action.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_delegation_result_has_parent_adjudication` | delegate_l0 → executor → adjudication | payload.adjudication 非空 |
| 2 | `test_adjudication_reject_stops_execution` | adjudication="reject" | status="success"（reject 不是 error），payload.execution_result 为空 |
| 3 | `test_adjudication_needs_review_returns_partial` | adjudication="needs_review" | payload.handoff_note 非空 |

### A-TEST-3：No nested delegation（integration）

```
测试目标：SubAgent 不得再委派其他 SubAgent
测试文件：tests/runtime_integration/test_subagent_runtime_action.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_subagent_cannot_delegate` | 在 SubAgent 执行上下文中调用 delegate_l0 | status="rejected" |
| 2 | `test_subagent_registry_marks_l0_cap_only` | SubAgent descriptor | level 字段 ≤ 0 |

### A-TEST-4：Tool list boundary（integration）

```
测试目标：delegation 的 allowed_tools 是 SubAgent descriptor 的子集
测试文件：tests/runtime_integration/test_subagent_runtime_action.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_allowed_tools_subset_of_descriptor` | descriptor.allowed_tools=["read","grep"], request 中 allowed_tools=["read","grep","write"] | status="rejected" |
| 2 | `test_allowed_tools_empty_set_allowed` | descriptor.allowed_tools=["read"], request 中 allowed_tools=[] | status="success"（空集是子集） |

### A-TEST-5：SubAgent boundary enforcement（negative）

```
测试目标：subagent.delegate_l0 的边界和错误路径
测试文件：tests/runtime_integration/test_subagent_runtime_action_negative.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_delegate_unknown_subagent` | subagent_name 不在 registry | status="failed" |
| 2 | `test_delegate_disabled_subagent` | subagent status=disabled | status="rejected" |
| 3 | `test_delegate_budget_exceeded` | max_iterations > subagent budget cap | status="rejected" |
| 4 | `test_delegate_no_shell_allowed` | allowed_tools 含 "shell" | L0 executor 拒绝执行 shell tool |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_subagent_runtime_action.py tests/runtime_integration/test_subagent_runtime_action_negative.py -v
```

### A-TEST-6：E2E dogfood verification

```
测试目标：真实 core.chat() + real LLM 通过 tool calling 委派 SubAgent L0
场景编号：E03（subagent runtime）
pass 条件：
  - RuntimeActionEvent(action_type="subagent.delegate_l0") 存在于 action log
  - event.evidence["adjudication"] ∈ {"accept", "reject", "needs_review"}
  - event.evidence["subagent_name"] 非空

注意：此场景替代原始 E03（直接调用 delegate_once）。
      原始 E03 降级为 subsystem integration test。
```

**pytest 命令**（由 E2E dogfood runner 驱动）：
```bash
python scripts/dogfood_e2e_runtime.py --scenario E03
```

---

## Track M：Memory Runtime Hook 测试

### M-TEST-1：Memory hook trigger condition（unit）

```
测试目标：hook point 在 tool 执行后、下一轮 LLM 调用前触发
测试文件：tests/runtime_integration/test_memory_runtime_hook.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_hook_triggered_after_tool_execution` | chat() 中 tool 执行完成 | memory.propose action 被触发 |
| 2 | `test_hook_not_triggered_before_first_tool` | chat() 首轮 LLM 响应无 tool call | 不触发 memory.propose |
| 3 | `test_hook_triggered_once_per_turn` | 单轮多个 tool call | 所有 tool 执行完成后触发一次（非每个 tool 触发一次） |

### M-TEST-2：Proposal lifecycle（integration）

```
测试目标：memory.propose → proposal → pending_review，不自动 confirmed
测试文件：tests/runtime_integration/test_memory_runtime_hook.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_memory_propose_creates_proposal` | memory-worthy conversation turn | payload.proposal_id 非空 |
| 2 | `test_proposal_status_is_pending_review` | proposal 创建后 | proposal.status == "pending_review" |
| 3 | `test_proposal_not_auto_confirmed` | proposal 创建后 | proposal.status != "confirmed" |
| 4 | `test_no_memory_worthy_content_returns_no_action` | 普通对话 turn | disposition="no_action", proposal_id=None |

### M-TEST-3：Secret-like filtering（integration）

```
测试目标：secret-like 内容不进入 proposal body
测试文件：tests/runtime_integration/test_memory_runtime_hook.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_sk_key_detected_and_blocked` | conversation 含 "sk-abc123..." | secret_like_detected=True, proposal_id=None |
| 2 | `test_api_key_pattern_detected` | conversation 含 "api_key=..." | secret_like_detected=True, proposal_id=None |
| 3 | `test_password_field_detected` | conversation 含 "password: xxx" | secret_like_detected=True |
| 4 | `test_normal_conversation_no_secret_flag` | 正常对话 | secret_like_detected=False |

### M-TEST-4：Memory governance not bypassed（negative）

```
测试目标：Runtime Hook 不绕过 Memory governance
测试文件：tests/runtime_integration/test_memory_runtime_hook_negative.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_hook_does_not_read_real_episodes` | memory.propose 被触发 | 不调用 FilesystemMemoryStore 的 read 方法 |
| 2 | `test_hook_does_not_change_consolidation_pipeline` | consolidation pipeline 调用前/后 | pipeline 行为不变 |
| 3 | `test_hook_no_auto_approve_path_exists` | 检查 memory hook 代码路径 | 无 silent approve 代码路径 |
| 4 | `test_proposal_body_no_raw_prompt` | proposal 创建后 | proposal body 不含 raw prompt 内容 |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_memory_runtime_hook.py tests/runtime_integration/test_memory_runtime_hook_negative.py -v
```

### M-TEST-5：E2E dogfood verification

```
测试目标：真实 core.chat() + real LLM 识别 memory-worthy content 并触发 proposal
场景编号：E04（memory runtime）
pass 条件：
  - RuntimeActionEvent(action_type="memory.propose") 存在于 action log
  - event.evidence["disposition"] ∈ {"proposed", "no_action", "should_not_remember"}
  - 如有 proposal，event.evidence["secret_like_detected"] == false

注意：此场景替代原始 E04（直接调用 run_consolidation_pipeline）。
      原始 E04 降级为 subsystem integration test。
```

**pytest 命令**（由 E2E dogfood runner 驱动）：
```bash
python scripts/dogfood_e2e_runtime.py --scenario E04
```

---

## Track T：ToolRegistry Action Gate 测试

### T-TEST-1：Tool gate schema（unit）

```
测试目标：tool.request 的 payload 格式正确
测试文件：tests/runtime_integration/test_tool_registry_action_gate.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_tool_request_must_have_tool_name` | payload 缺 tool_name | 构造时抛出 ValidationError |
| 2 | `test_tool_request_must_have_risk_reason` | payload 缺 risk_reason | 构造时抛出 ValidationError |
| 3 | `test_tool_request_disposition_valid_values` | 正常路由 | disposition ∈ {"allowed", "rejected", "confirmation_required"} |

### T-TEST-2：Tool visibility and risk（integration）

```
测试目标：ToolRegistry gate 正确执行 visibility filtering 和 risk classification
测试文件：tests/runtime_integration/test_tool_registry_action_gate.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_unknown_tool_rejected` | tool_name="nonexistent_tool" | disposition="rejected" |
| 2 | `test_hidden_tool_rejected` | tool_name 对应 hidden tool | disposition="rejected" |
| 3 | `test_low_risk_tool_allowed` | tool_name 对应 low-risk tool | disposition="allowed" |
| 4 | `test_high_risk_tool_requires_confirmation` | tool_name 对应 high-risk tool | disposition="confirmation_required" |
| 5 | `test_risk_level_in_output` | 任意 tool | payload.risk_level ∈ {"low", "medium", "high"} |
| 6 | `test_policy_path_in_output` | 任意 tool | payload.policy_path 非空 str |

### T-TEST-3：Confirmation flow preserved（integration）

```
测试目标：高风险 tool 必须经过 confirmation
测试文件：tests/runtime_integration/test_tool_registry_action_gate.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_confirmation_required_triggers_user_prompt` | high-risk tool request | ConfirmationContext 被激活 |
| 2 | `test_confirmation_approved_tool_executes` | 用户确认 | disposition="allowed", tool 执行 |
| 3 | `test_confirmation_denied_tool_not_executed` | 用户拒绝 | disposition="rejected", tool 不执行 |

### T-TEST-4：Tool gate boundary enforcement（negative）

```
测试目标：ToolRegistry gate 不被 Runtime Action 绕过
测试文件：tests/runtime_integration/test_tool_registry_action_gate_negative.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_tool_gate_not_bypassable_by_direct_call` | 绕过 dispatcher 直接调 tool executor | 被 ToolRegistry 拦截 |
| 2 | `test_tool_gate_output_no_secret` | tool 返回含 secret 的结果 | evidence 中 secret 被 redact |
| 3 | `test_tool_gate_rate_limit` | 连续 N 次 tool.request（同一 tool） | 不阻挠（rate limit 非此阶段范围，仅记录） |
| 4 | `test_tool_gate_no_new_registration_path` | 尝试通过 RuntimeAction 注册新 tool | status="rejected" |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_tool_registry_action_gate.py tests/runtime_integration/test_tool_registry_action_gate_negative.py -v
```

### T-TEST-5：E2E dogfood verification

```
测试目标：真实 core.chat() 中所有 tool call 都经过 ToolRegistry gate
场景编号：E05（tool registry runtime）
pass 条件：
  - RuntimeActionEvent(action_type="tool.request") 存在于 action log
  - 每个 tool call 对应至少一个 tool.request event
  - 高风险 tool 对应的 event 显示 disposition="confirmation_required"

注意：E05 原始场景已验证 ToolRegistry API 正确性（subsystem integration）。
      新场景要求 RuntimeActionEvent 证据。
```

**pytest 命令**（由 E2E dogfood runner 驱动）：
```bash
python scripts/dogfood_e2e_runtime.py --scenario E05
```

---

## Track C：Checkpoint-safe Runtime Summary 测试

### C-TEST-1：Safe summary schema（unit）

```
测试目标：checkpoint.safe_summary 的 payload 格式正确
测试文件：tests/runtime_integration/test_checkpoint_safe_summary.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_safe_summary_output_has_required_fields` | 正常 hook 触发 | payload 含 safe_summary, secret_content_detected, huge_prompt_truncated, pending_high_risk_tool |
| 2 | `test_secret_content_detected_true_when_secret_found` | runtime_state_summary 含 "sk-" | secret_content_detected=True |

### C-TEST-2：Secret redaction in summary（integration）

```
测试目标：safe_summary 中不含 secret-like 内容
测试文件：tests/runtime_integration/test_checkpoint_safe_summary.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_sk_key_redacted_from_summary` | 最近 tool 输出含 "sk-abc123" | safe_summary 不含 "sk-abc123" |
| 2 | `test_bearer_token_redacted_from_summary` | 最近 tool 输出含 "Bearer xyz" | safe_summary 不含 "Bearer xyz" |
| 3 | `test_api_key_header_redacted` | 最近 tool 输出含 "x-api-key: secret" | safe_summary 不含 "secret" |
| 4 | `test_normal_content_preserved` | 无 secret 的正常输出 | safe_summary 内容未被截断 |

### C-TEST-3：Huge prompt truncation（integration）

```
测试目标：超大 prompt 被截断标记
测试文件：tests/runtime_integration/test_checkpoint_safe_summary.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_prompt_over_limit_truncated` | runtime_state_summary > 10KB | huge_prompt_truncated=True |
| 2 | `test_prompt_under_limit_not_truncated` | runtime_state_summary < 10KB | huge_prompt_truncated=False |

### C-TEST-4：High-risk tool pending marker（integration）

```
测试目标：待确认高风险 tool 在 checkpoint 中标记但不重放
测试文件：tests/runtime_integration/test_checkpoint_safe_summary.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_pending_high_risk_tool_marked` | 最近 tool 为高风险且 disposition="confirmation_required" | pending_high_risk_tool 非 None |
| 2 | `test_pending_high_risk_tool_not_replayable` | checkpoint 恢复后 | 高风险 tool 不自动重放 |

### C-TEST-5：Checkpoint boundary enforcement（negative）

```
测试目标：checkpoint.safe_summary 不改变 Checkpoint schema
测试文件：tests/runtime_integration/test_checkpoint_safe_summary_negative.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_does_not_change_checkpoint_schema` | save_checkpoint 调用前/后 schema | schema 字段不变 |
| 2 | `test_does_not_change_save_checkpoint_timing` | chat() 中 save_checkpoint 调用时机 | 时序不变（safe summary 插入在 save 之前） |
| 3 | `test_safe_summary_not_independent_storage` | 检查文件系统 | safe summary 仅在 checkpoint 内部，无独立文件 |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_checkpoint_safe_summary.py tests/runtime_integration/test_checkpoint_safe_summary_negative.py -v
```

### C-TEST-6：E2E dogfood verification

```
测试目标：真实 core.chat() 在 tool 执行后产生 checkpoint-safe summary
场景编号：E06（checkpoint runtime）
pass 条件：
  - RuntimeActionEvent(action_type="checkpoint.safe_summary") 存在于 action log
  - event.evidence["secret_content_detected"] 为 bool
  - checkpoint 文件中 safe_summary 字段存在

注意：此场景替代原始 E06（直接调用 save_checkpoint）。
      原始 E06 降级为 subsystem integration test。
```

**pytest 命令**（由 E2E dogfood runner 驱动）：
```bash
python scripts/dogfood_e2e_runtime.py --scenario E06
```

---

## Track P：Streaming E2E Evidence 测试

### P-TEST-1：Streaming evidence collection（unit）

```
测试目标：streaming.event 正确收集 evidence
测试文件：tests/runtime_integration/test_streaming_evidence.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_streaming_event_evidence_fields` | 模拟 streaming 交互 | evidence 含 events_received, final_event_received, error_event_received, text_sanitized, sequence_monotonic |
| 2 | `test_final_event_received_true_on_complete` | 正常 streaming 完成 | final_event_received=True |
| 3 | `test_error_event_received_true_on_error` | streaming 中断/错误 | error_event_received=True |
| 4 | `test_sequence_monotonic_true_on_ordered` | 递增 sequence 的 events | sequence_monotonic=True |
| 5 | `test_sequence_monotonic_false_on_gap` | sequence 有缺口的 events | sequence_monotonic=False |

### P-TEST-2：Streaming text sanitization（unit）

```
测试目标：sanitize_stream_text 在 streaming 上下文中正确执行
测试文件：tests/runtime_integration/test_streaming_evidence.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_secret_sanitized_during_streaming` | streaming text 含 "sk-xxx" | text_sanitized=True, sanitized text 不含 "sk-xxx" |
| 2 | `test_normal_text_not_sanitized_flag` | 无 secret 的 streaming text | text_sanitized=False |

### P-TEST-3：Streaming boundary enforcement（negative）

```
测试目标：streaming evidence 不扩大 Observability
测试文件：tests/runtime_integration/test_streaming_evidence_negative.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_no_metrics_exported` | streaming.event 后 | 无 metrics/dashboard 调用 |
| 2 | `test_evidence_only_for_e2e_dogfood` | streaming.event 记录的内容 | 仅 E2E dogfood 可验证字段，无生产 metrics |
| 3 | `test_existing_streaming_behavior_unchanged` | collect_stream_response 调用 | 行为与添加 Track P 之前一致 |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_streaming_evidence.py tests/runtime_integration/test_streaming_evidence_negative.py -v
```

### P-TEST-4：E2E dogfood verification

```
测试目标：真实 core.chat() 中 streaming events 被正确收集
场景编号：E07（streaming runtime）
pass 条件：
  - RuntimeActionEvent(action_type="streaming.event") 存在于 action log
  - event.evidence["events_received"] > 0
  - event.evidence["final_event_received"] == true
```

**pytest 命令**（由 E2E dogfood runner 驱动）：
```bash
python scripts/dogfood_e2e_runtime.py --scenario E07
```

---

## Track E：Capability Evidence Matrix 修复测试

### E-TEST-1：Mapping table correctness（unit）

```
测试目标：CAPABILITY_MODULE_MAPPING 覆盖所有 capability
测试文件：tests/runtime_integration/test_capability_matrix.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_all_capabilities_in_mapping` | 能力矩阵 row name | 每个 capability 在 mapping table 中有对应 entry |
| 2 | `test_mapping_is_single_source_of_truth` | 两个查询 mapping 的路径 | 返回一致的 alias set |
| 3 | `test_each_capability_has_at_least_one_module` | mapping table values | 每个 capability 至少映射 1 个 module alias |

### E-TEST-2：Evidence level classification（unit）

```
测试目标：evidence level 分级正确
测试文件：tests/runtime_integration/test_capability_matrix.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_runtime_e2e_requires_action_event` | capability 有 RuntimeActionEvent | level="runtime_e2e" |
| 2 | `test_subsystem_integration_without_event` | capability 有 systems_actually_invoked 但无 action event | level="subsystem_integration" |
| 3 | `test_deterministic_baseline_pure_function` | capability 无 runtime 也无 subsystem 调用，有纯函数测试 | level="deterministic_baseline" |
| 4 | `test_simulated_when_mock_data` | capability 在 systems_simulated 中 | level="simulated" |
| 5 | `test_not_covered_when_no_evidence` | capability 无任何 evidence | level="not_covered" |

### E-TEST-3：Matrix invariant enforcement（unit）

```
测试目标：能力矩阵不变式
测试文件：tests/runtime_integration/test_capability_matrix.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_no_runtime_e2e_without_action_event` | capability level="runtime_e2e" 但无 RuntimeActionEvent | 断言失败 |
| 2 | `test_subsystem_integration_not_reported_as_runtime_e2e` | systems_actually_invoked 中存在但 level="runtime_e2e" | 断言失败 |
| 3 | `test_mapping_table_is_authoritative` | 硬编码 capability name 与 mapping table 冲突 | 以 mapping table 为准 |

### E-TEST-4：E08 full combined verification（integration）

```
测试目标：E08 场景必须验证实际 action events，不能只靠 "模型文本提到"
测试文件：tests/runtime_integration/test_capability_matrix.py
```

| # | 测试名 | 输入 | 期望 |
|---|--------|------|------|
| 1 | `test_e08_has_action_events_not_just_text` | E08 scenario result | 至少 3 个 different action_type 的 RuntimeActionEvent |
| 2 | `test_e08_text_mention_not_sufficient_for_pass` | E08 scenario 只有 "模型文本提到 X" 证据 | 不满足 runtime_e2e 的 pass 条件 |
| 3 | `test_e08_covers_skill_subagent_memory_tool` | E08 action log | action_type 集合包含 skill.select, subagent.delegate_l0, memory.propose, tool.request |

**pytest 命令**：
```bash
python -m pytest tests/runtime_integration/test_capability_matrix.py -v
```

---

## Coverage 目标

| Track | Unit | Integration | Negative | E2E Dogfood | 覆盖率目标 |
|-------|------|-------------|----------|-------------|-----------|
| R | R-TEST-1,2,3 | — | R-TEST-4 | R-TEST-5 | 90%+ |
| S | S-TEST-1 | S-TEST-2,3 | S-TEST-4 | S-TEST-5 | 85%+ |
| A | A-TEST-1 | A-TEST-2,3,4 | A-TEST-5 | A-TEST-6 | 85%+ |
| M | M-TEST-1 | M-TEST-2,3 | M-TEST-4 | M-TEST-5 | 85%+ |
| T | T-TEST-1 | T-TEST-2,3 | T-TEST-4 | T-TEST-5 | 85%+ |
| C | C-TEST-1 | C-TEST-2,3,4 | C-TEST-5 | C-TEST-6 | 85%+ |
| P | P-TEST-1,2 | — | P-TEST-3 | P-TEST-4 | 85%+ |
| E | E-TEST-1,2,3 | E-TEST-4 | — | (E08 复用) | 90%+ |

---

## 全量测试触发命令

```bash
# 所有 Runtime Integration 测试
python -m pytest tests/runtime_integration/ -v

# 包含覆盖率
python -m pytest tests/runtime_integration/ -v --cov=agent.runtime_integration --cov-report=term-missing

# E2E dogfood（需要真实 API key）
python scripts/dogfood_e2e_runtime.py --all

# 全量回归（确保未破坏现有功能）
python -m pytest tests/ -v --ignore=tests/runtime_integration/
```

---

## TDD 实施顺序

```
Phase 1: Track E（现有 regression 修复，不新增代码）
Phase 2: Track R（RuntimeAction 抽象，所有 Track 的基石）
Phase 3: Track T（ToolRegistry gate，影响面最小，验证 gate 模式）
Phase 4: Track P（Streaming evidence，纯函数，最简单）
Phase 5: Track C（Checkpoint summary，取决于 Track T 的 tool event）
Phase 6: Track S（Skill action，需要 LLM tool calling）
Phase 7: Track A（SubAgent action，需要 L0 executor + adjudication）
Phase 8: Track M（Memory hook，需要完整 chat() 循环）
Phase 9: E08 full combined（所有 Track 的 E2E 集成验证）
```

每个 Phase 的 TDD 循环：
1. 写测试（RED）
2. `python -m pytest` 确认失败
3. 实现最小代码（GREEN）
4. `python -m pytest` 确认通过
5. 重构（IMPROVE）
6. `ruff check agent tests scripts` 确认格式
7. 全量回归 `python -m pytest tests/ -v`

# Runtime Integration / Runtime Action Harness — SDD（系统设计文档）

> 状态：设计规格（不包含实现代码）
> 关联文档：RFC、TDD、Implementation Loop、E2E Dogfood Plan、Audit Checklist
> 语言：简体中文为主，英文术语括注

---

## 0. 设计总览

```
┌─────────────────────────────────────────────────────┐
│                  Parent Runtime                      │
│  core.chat() → plan → confirm → execute loop        │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │        RuntimeActionDispatcher               │   │
│  │  route(action_request) → action_result       │   │
│  │  ├─ skill.select    → SkillSystem            │   │
│  │  ├─ subagent.delegate_l0 → SubAgentSystem    │   │
│  │  ├─ memory.propose  → MemorySystem           │   │
│  │  ├─ tool.request    → ToolRegistry           │   │
│  │  ├─ checkpoint.safe_summary → Checkpoint     │   │
│  │  └─ streaming.event → Streaming Protocol     │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  Subsystems (unchanged):                             │
│  Skill / SubAgent / Memory / ToolRegistry /          │
│  Checkpoint / Streaming / Provider                   │
└─────────────────────────────────────────────────────┘
```

**关键约束**：RuntimeActionDispatcher 是路由层，不是第二套主循环。它不推进 Runtime state，不绕过 ToolRegistry/Memory governance，不替代 Parent orchestrator。

---

## Track R：Runtime Action Harness

### R.1 设计目标

提供一个统一的、可审计的 action 入口，使 Runtime LLM（通过 tool calling）或 Runtime policy（如 checkpoint hook）可以触发子系统能力，并产生可验证的 evidence event。

### R.2 Schema

#### RuntimeActionType（action 类型枚举）

```python
# 中文学习型注释：Runtime action 的可审计分类。
# 每个 action type 对应一个子系统的受控入口，由 RuntimeActionDispatcher 路由。
class RuntimeActionType(enum.StrEnum):
    SKILL_SELECT = "skill.select"             # Skill 选择（来自 Runtime LLM tool call）
    SUBAGENT_DELEGATE_L0 = "subagent.delegate_l0"  # SubAgent L0 委托
    MEMORY_PROPOSE = "memory.propose"         # Memory proposal hook
    TOOL_REQUEST = "tool.request"             # ToolRegistry gate（经过 policy）
    CHECKPOINT_SAFE_SUMMARY = "checkpoint.safe_summary"  # Checkpoint 安全摘要
    STREAMING_EVENT = "streaming.event"       # Streaming 证据收集
```

#### RuntimeActionRequest（action 请求）

```python
# 中文学习型注释：RuntimeAction 的不可变请求。
# 由 Runtime（LLM tool call 或 Runtime policy hook）创建，经 Dispatcher 路由。
@dataclass(frozen=True)
class RuntimeActionRequest:
    action_type: RuntimeActionType           # action 分类
    source: str                              # 触发来源："llm_tool_call" | "runtime_policy" | "e2e_dogfood"
    parent_trace_id: str                     # Runtime 追踪 ID
    payload: Mapping[str, Any]               # 子系统特定输入（不可变）
    constraints: set[str]                    # 约束标记，如 {"no_write", "no_network"}
    created_at: str                          # ISO timestamp
```

#### RuntimeActionResult（action 结果）

```python
# 中文学习型注释：RuntimeAction 的不可变结果。
# 包含 status、子系统返回数据、evidence 字段供 E2E dogfood 验证。
@dataclass(frozen=True)
class RuntimeActionResult:
    action_type: RuntimeActionType
    status: str                              # "success" | "rejected" | "confirmation_required" | "not_supported" | "failed"
    payload: Mapping[str, Any]               # 子系统返回数据（不可变）
    evidence: Mapping[str, Any]              # E2E 可验证的 evidence 字段
    error_safe_preview: str                  # 用户可见错误信息（不含敏感数据）
    latency_ms: int                          # 执行耗时
    timestamp: str                           # ISO timestamp
```

#### RuntimeActionDispatcher（action 路由器）

```python
# 中文学习型注释：RuntimeAction 的路由层。
# 不做业务逻辑——只做路由、policy 检查、evidence 记录。
# 不推进 Runtime state，不持有 durable state。
class RuntimeActionDispatcher:
    def route(self, request: RuntimeActionRequest, *, registry: ActionHandlerRegistry) -> RuntimeActionResult:
        """将 action 路由到对应的 handler，记录 evidence event。"""
        ...
```

### R.3 边界

- **做**：接收 RuntimeActionRequest → policy 检查 → 路由到子系统 handler → 返回 RuntimeActionResult + 记录 action event
- **不做**：
  - 不推进 Runtime state（不改变 task status / conversation / plan）
  - 不持有 durable state
  - 不绕过 ToolRegistry / Memory governance
  - 不是第二套主循环
  - 不自行决定 "是否应该执行" —— policy 检查属于 ToolRegistry / Confirmation 层的职责
  - 不访问 .env / 网络 / 外部系统

### R.4 Action event（证据链）

每个 RuntimeAction 执行后产生不可变的 action event，存储在 Runtime 的 action log 中：

```python
# 中文学习型注释：action event 是 E2E dogfood 验证能力覆盖的唯一证据来源。
# "模型文本提到 X" 不是 action event；"Runtime 路由了 action X 并返回了 Y" 才是。
@dataclass(frozen=True)
class RuntimeActionEvent:
    event_id: str                            # UUID
    action_type: RuntimeActionType
    source: str
    status: str
    evidence: Mapping[str, Any]
    parent_trace_id: str
    timestamp: str
```

### R.5 不变式（invariants）

1. 每个 RuntimeActionRequest 必须产生恰好一个 RuntimeActionResult。
2. RuntimeActionResult.status ∈ {"success", "rejected", "confirmation_required", "not_supported", "failed"}。
3. evidence 字段不得包含 secret / raw key / raw prompt 内容。
4. RuntimeActionDispatcher 不得推进 Runtime state。
5. RuntimeActionDispatcher 不得持有 module-level global mutable state。

---

## Track S：Skill Runtime Action

### S.1 设计目标

使 Runtime LLM（通过 tool calling）可以选择和加载 Skill，保持渐进式披露（progressive disclosure），并产生可审计的 action event。

### S.2 action type

`skill.select`

### S.3 输入（payload）

```python
{
    "task_summary": str,           # 当前任务描述
    "constraints": list[str],      # 约束条件，如 ["read_only", "no_shell"]
    "available_skills": list[str], # 可选 skill 名称列表（metadata only）
}
```

### S.4 输出（payload）

```python
{
    "selected_skill_id": str | None,     # 选中的 skill name
    "selection_reason": str,             # 选择理由（来自 LLM）
    "allowed_tools": list[str],          # skill 允许的工具列表
    "body_loaded": bool,                 # skill body 是否已加载
    "no_suitable_skill": bool,           # 无可选 skill
}
```

### S.5 渐进式披露流程

1. Runtime LLM 收到可用 skill 的 metadata（name、description、tags、risk_level）——**不含 body**
2. LLM 通过 tool calling 调用 `skill.select` action
3. RuntimeActionDispatcher 路由到 SkillLoader，**此时才加载选中 skill 的 body**
4. 返回的 RuntimeActionResult 包含 body 内容（但不在 evidence 中暴露 body 全文）

### S.6 约束

- hidden/disabled skill 不得出现在 available_skills 中
- selected skill 的 allowed_tools 不得超出 skill descriptor 声明的范围
- 不直接执行 tools——tool execution 走 Track T（ToolRegistry Action Gate）
- missing `version` / `description` 等字段的 skill 不应出现在 available_skills 中（已在 8aa11a4 的 `get_load_errors()` 中解决）

### S.7 不变式

1. available_skills 中的每个 skill 必须是 active 状态且有合法 descriptor。
2. body 在 metadata 列表阶段不能被加载（progressive disclosure）。
3. selected skill 的 allowed_tools 必须 ∩ ToolRegistry visible tools 非空（否则 skill 选了也无法执行任何 tool）。

---

## Track A：SubAgent L0 Runtime Action

### A.1 设计目标

使 Runtime LLM（通过 tool calling）可以自主判断委托需求，触发 SubAgent L0 delegation，并产生可审计的 action event。

### A.2 action type

`subagent.delegate_l0`

### A.3 输入（payload）

```python
{
    "delegation_goal": str,              # 委托目标（来自 LLM）
    "context_package": str,              # 上下文摘要（不超过 budget）
    "budget": {"max_iterations": int},   # 迭代预算
    "allowed_tools": list[str],          # 允许的工具（LLM 选择或 parent policy 决定）
}
```

### A.4 输出（payload）

```python
{
    "subagent_name": str,                # 被委派的 SubAgent name
    "execution_result": str,             # L0 执行结果摘要
    "handoff_note": str | None,          # 交接说明（如有）
    "adjudication": str,                 # Parent adjudication: "accept" | "reject" | "needs_review"
    "adjudication_reason": str,          # 裁决理由
}
```

### A.5 流程

1. Runtime LLM 通过 tool calling 调用 `subagent.delegate_l0` action
2. RuntimeActionDispatcher 检查：
   - SubAgent name 是否在 registry 中存在
   - SubAgent status 是否为 active
   - allowed_tools 是否在 SubAgent descriptor 声明的范围内
3. 路由到 `delegate_once(request, registry)`（现有 L0 executor）
4. Parent adjudication（现有 `SubAgentAdjudication` 逻辑）
5. 返回 RuntimeActionResult

### A.6 约束

- 不嵌套 delegation（SubAgent 不得再委派其他 SubAgent）
- 不调用 shell/external process
- SubAgent 内不使用真实 LLM（L0 executor 是确定性的）
- 委托的 allowed_tools 不得超出 SubAgent descriptor 声明范围

### A.7 不变式

1. SubAgent delegation 必须经过 parent adjudication。
2. 被委派的 SubAgent status 必须是 active。
3. delegation 的 tool list 必须是 SubAgent descriptor allowed_tools 的子集。

---

## Track M：Memory Runtime Hook

### M.1 设计目标

在 Runtime 对话回合中，提供一个 hook point 使 Runtime 可以识别 memory-worthy content 并触发 proposal，但不改变现有 consolidation pipeline 的 governance。

### M.2 action type

`memory.propose`

### M.3 hook point

在 `chat()` 的 tool calling 循环中，**tool 执行完成后、下一轮 LLM 调用之前**：

```
chat() loop:
  1. model call → text/tool_calls
  2. if tool_calls: execute tools (via Track T)
  3. AFTER tool execution: Runtime evaluates whether current turn contains memory-worthy content
     → if yes: trigger memory.propose RuntimeAction
  4. continue loop or end
```

### M.4 输入（payload）

```python
{
    "conversation_turn": str,            # 当前对话回合摘要（不含 secret）
    "model_output_summary": str,         # 模型输出摘要
    "user_preference_candidate": str | None,  # 可能的用户偏好
}
```

### M.5 输出（payload）

```python
{
    "proposal_id": str | None,           # 如有 proposal，返回 ID
    "disposition": str,                  # "proposed" | "no_action" | "should_not_remember"
    "reason": str,                       # 分类理由
    "secret_like_detected": bool,        # 是否检测到 secret-like 内容
}
```

### M.6 约束

- **不 silent retain**：所有 memory 操作必须走 proposal→pending_review
- **不 auto approve**：proposal 不能自动变为 confirmed
- **secret-like filtering**：现有 `_SECRET_PATTERNS` 过滤保留
- **不改变 consolidation pipeline 内部逻辑**：Memory Runtime Hook 只负责"触发提案"，consolidation engine 负责"评估提案"
- **不读取真实 memory episodes 内容**（在 E2E 测试中）

### M.7 不变式

1. Memory proposal 不得自动 confirmed。
2. secret-like 内容不得进入 proposal body。
3. Memory governance 不得被 Runtime Hook 绕过。
4. Runtime Hook 不得读取真实 sessions/runs/memory episodes。

---

## Track T：ToolRegistry Action Gate

### T.1 设计目标

确保所有 tool execution（无论来自 LLM tool call 还是 Runtime policy）必须经过 ToolRegistry 的 policy 检查，并通过 RuntimeAction 路由产生可审计的 action event。

### T.2 action type

`tool.request`

### T.3 输入（payload）

```python
{
    "tool_name": str,
    "tool_args": Mapping[str, Any],
    "risk_reason": str,                  # LLM 说明为什么需要这个 tool
}
```

### T.4 输出（payload）

```python
{
    "disposition": str,                  # "allowed" | "rejected" | "confirmation_required"
    "risk_level": str,                   # "low" | "medium" | "high"
    "policy_path": str,                  # 经过的 policy 路径（如 "tool_registry→risk_check→confirmation"）
    "rejection_reason": str | None,      # 拒绝理由（如有）
}
```

### T.5 流程

1. LLM tool call → RuntimeActionDispatcher 接收 `tool.request`
2. Dispatcher 查询 ToolRegistry：tool 是否存在、是否 visible、risk level
3. 高风险 tool → 触发 confirmation（现有 ConfirmationContext 逻辑）
4. 允许的 tool → 执行（现有 `execute_tool_call`）
5. 返回 RuntimeActionResult（包含 disposition、risk_level）

### T.6 约束

- 不绕过现有 ToolRegistry 注册/可见性/风险分级逻辑
- 不改变 confirmation 流程
- 不新增 tool 类别/注册方式

### T.7 不变式

1. hidden/unknown tool 必须被拒绝。
2. 高风险 tool 必须经过 confirmation。
3. tool execution 结果不得包含 secret。

---

## Track C：Checkpoint-safe Runtime Summary

### C.1 设计目标

在 Runtime tool 执行后，提供一个 hook 产生 checkpoint-safe summary，确保 checkpoint 中不包含 secret、raw huge prompt、或 pending high-risk tool 的重放数据。

### C.2 action type

`checkpoint.safe_summary`

### C.3 hook point

在 `chat()` 的 tool 执行完成后、`save_checkpoint` 调用之前：

```
chat() loop:
  1. model call
  2. tool execution (via Track T)
  3. generate checkpoint-safe summary (via Track C)
  4. save checkpoint (with safe summary)
```

### C.4 输入（payload）

```python
{
    "runtime_state_summary": str,        # 当前 Runtime 状态摘要（脱敏后）
    "last_tool_call": str | None,        # 最近一次 tool call 的名称
    "last_tool_status": str | None,      # tool 执行状态
}
```

### C.5 输出（payload）

```python
{
    "safe_summary": str,                 # 脱敏摘要
    "secret_content_detected": bool,     # 是否检测到 secret
    "huge_prompt_truncated": bool,       # 是否有超大 prompt 被截断
    "pending_high_risk_tool": str | None, # 是否有待确认高风险 tool
}
```

### C.6 约束

- 不改变 Checkpoint schema
- 不改变 `save_checkpoint` 的调用时机/逻辑
- safe summary 只是 checkpoint 中的数据字段，不是独立存储

### C.7 不变式

1. safe_summary 中不得出现 raw key / secret pattern。
2. pending_high_risk_tool 不得在 checkpoint 中可重放。

---

## Track P：Streaming E2E Evidence

### P.1 设计目标

确保 Runtime 在消费 provider streaming events 时正确收集 final/error 语义，并产生 E2E dogfood 可验证的 evidence。

### P.2 action type

`streaming.event`

### P.3 输入/输出

此 Track 更多是 evidence 收集而非 action 路由。RuntimeActionDispatcher 在每次 streaming 交互完成后记录：

```python
evidence = {
    "events_received": int,              # 收到的事件数
    "final_event_received": bool,        # 是否收到 final 事件
    "error_event_received": bool,        # 是否收到 error 事件
    "text_sanitized": bool,              # 是否执行了 secret sanitization
    "sequence_monotonic": bool,          # sequence 是否单调递增
}
```

### P.4 约束

- 不扩大 Observability（不引入 metrics / dashboard）
- evidence 仅用于 E2E dogfood 验证
- 不改变 `collect_stream_response` / `sanitize_stream_text` 的行为

---

## Track E：Capability Evidence Matrix 修复

### E.1 问题

当前 `_capability_evidence_matrix` 中 capability name（如 `"SubAgent"`）与 `systems_actually_invoked` 中的模块名（如 `"SubAgentRegistry"`）不匹配，导致 set intersection 失败。

### E.2 解决方案：统一 mapping table

```python
# 中文学习型注释：capability name → module alias 的映射表。
# 能力矩阵和 scenario result 必须使用同一套命名，避免 set intersection 失败。
CAPABILITY_MODULE_MAPPING: dict[str, tuple[str, ...]] = {
    "skill": ("SkillRegistry", "SkillSelector", "SkillLoader", "SkillToolBinding"),
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

### E.3 evidence level 分级

| Level | 定义 | 来源 |
|-------|------|------|
| `runtime_e2e` | Runtime LLM 通过 RuntimeAction 实际触发了该能力，有 action event 证据 | RuntimeActionEvent |
| `subsystem_integration` | 子系统模块 API 被程序化调用并验证正确性，但未经过 Runtime LLM | systems_actually_invoked（非 runtime 路径） |
| `deterministic_baseline` | 确定性函数/协议（如 streaming），已验证正确性 | 纯函数测试 |
| `simulated` | mock 或模拟数据 | systems_simulated |
| `not_covered` | 无任何覆盖 | 无 |

### E.5 不变式

1. capability 不得被标记为 `runtime_e2e` 除非存在对应的 RuntimeActionEvent。
2. `subsystem_integration` 不得被报告为 `runtime_e2e`。
3. mapping table 是 capability name 的单一事实来源。

---

## 设计总结

| Track | action type | 触发方式 | 子系统 |
|-------|-------------|----------|--------|
| R | (dispatcher) | LLM tool call / Runtime policy | 所有 |
| S | skill.select | LLM tool call | Skill System |
| A | subagent.delegate_l0 | LLM tool call | SubAgent System |
| M | memory.propose | Runtime hook | Memory System |
| T | tool.request | LLM tool call / Runtime policy | ToolRegistry |
| C | checkpoint.safe_summary | Runtime hook | Checkpoint |
| P | streaming.event | Runtime (被动) | Streaming Protocol |
| E | (mapping) | N/A | 所有 |

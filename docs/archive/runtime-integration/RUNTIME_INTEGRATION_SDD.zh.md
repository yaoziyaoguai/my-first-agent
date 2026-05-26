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

提供一个统一的、可审计的 action 入口，使 Runtime LLM（通过 tool calling）或 Runtime policy（如 checkpoint hook、turn-end hook）可以触发子系统能力，并产生可验证的 evidence event。

### R.2 Schema

#### RuntimeActionType（action 类型枚举）

```python
# 中文学习型注释：Runtime action 的可审计分类。
# 每个 action type 对应一个子系统的受控入口，由 RuntimeActionDispatcher 路由。
class RuntimeActionType(enum.StrEnum):
    SKILL_SELECT = "skill.select"             # Skill 选择（来自 Runtime LLM tool call）
    SUBAGENT_DELEGATE_L0 = "subagent.delegate_l0"  # SubAgent L0 委托
    MEMORY_PROPOSE = "memory.propose"         # Memory proposal hook（turn-end）
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
# 关键设计决策（审计 P1-2 修复）：
# evidence 字段必须包含 module invocation proof，不能只有 action event。
# RuntimeActionEvent 只是"收据"——记录了 route() 被调用。
# 只有满足 R.6 Runtime E2E 11 项证据链才是 runtime_e2e 证据；
# module_invoked=true 或 handler 自报 target_module_proof 都不足够。
@dataclass(frozen=True)
class RuntimeActionResult:
    action_type: RuntimeActionType
    action_id: str                           # 本次 action 的唯一 ID（UUID，用于关联 event 和 module invocation）
    status: str                              # "success" | "rejected" | "confirmation_required" | "not_supported" | "failed"
    payload: Mapping[str, Any]               # 子系统返回数据（不可变）
    evidence: Mapping[str, Any]              # E2E 可验证的 evidence 字段（见 R.6 Action Evidence Contract）
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

- **做**：接收 RuntimeActionRequest → policy 检查 → 路由到子系统 handler → handler 调用目标模块 → 记录 module invocation → 返回 RuntimeActionResult + 记录 action event
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
# 中文学习型注释：action event 记录了 route() 被调用。
# 但它本身不是 runtime_e2e 的充分证据。
# 充分证据 = R.6 Runtime E2E 11 项证据链全部满足；
# 其中 target_module_proof 必须有 proof_id、observation_independent=true，
# 并通过 linked_action_id / linked_target_module 回链到本次 action。
# 仅 module_invoked=true 而 target_module_proof 缺失或自我填充 → 不是充分证据。
@dataclass(frozen=True)
class RuntimeActionEvent:
    event_id: str                            # UUID
    action_id: str                           # 关联的 RuntimeActionResult.action_id
    action_type: RuntimeActionType
    source: str
    status: str
    evidence: Mapping[str, Any]              # 来自 RuntimeActionResult.evidence
    parent_trace_id: str
    timestamp: str
```

### R.5 不变式（invariants）

1. 每个 RuntimeActionRequest 必须产生恰好一个 RuntimeActionResult。
2. RuntimeActionResult.status ∈ {"success", "rejected", "confirmation_required", "not_supported", "failed"}。
3. evidence 字段不得包含 secret / raw key / raw prompt 内容。
4. RuntimeActionDispatcher 不得推进 Runtime state。
5. RuntimeActionDispatcher 不得持有 module-level global mutable state。
6. 每个 RuntimeActionResult 必须有唯一的 action_id。

### R.6 Action Evidence Contract（审计 P1-2 新增）

**核心设计决策**：RuntimeActionEvent 不是 runtime_e2e 的充分证据。它只是"收据"——记录了 Dispatcher 路由了 action。没有 module invocation proof，它可以成为新的自欺层：event emitted 但 handler 未真正调用目标模块，或 event 被伪造后 subsystem-only 被标成 runtime_e2e。

**runtime_e2e 必须同时满足以下全部条件（Runtime E2E 11 项证据链）**：

```
1. RuntimeActionEvent emitted
2. RuntimeActionDispatcher routed
3. target handler invoked
4. module_invoked=true
5. target_module_proof exists
6. target_module_proof.proof_id present
7. target_module_proof.observation_independent=true
8. target_module_proof.linked_action_id matches action_id
9. target_module_proof.linked_target_module matches target_module
10. result returned to Parent Runtime
11. parent_adjudicated where applicable
```

**RuntimeActionResult.evidence 必须包含以下字段**（SDD 级别强制）：

```python
evidence = {
    "action_id": str,                    # 本次 action 的唯一 ID
    "action_type": str,                  # RuntimeActionType 值
    "dispatcher_routed": bool,           # RuntimeActionDispatcher 是否完成路由（必须为 true 才可能 runtime_e2e）
    "target_handler_invoked": bool,      # 目标 handler.handle(request) 是否被调用
    "handler_name": str,                 # 实际处理此 action 的 handler 类名/函数名
    "target_module": str,                # 目标子系统模块名（如 "SkillLoader", "SubAgentExecutor"）
    "module_invoked": bool,              # 目标模块是否被实际调用（true/false）
    "invocation_proof": {                # 结构化调用证据（审计第二轮：不再接受 free-text str）
        "call_id": str,                  # 本次 module 调用的唯一 ID（UUID，可追溯到 spy/mock 观察点）
        "function_called": str,          # 实际被调用的函数/方法全限定名（如 "SkillLoader.load_body"）
        "call_signature": str,           # 观察到的调用签名（参数类型，不含参数值——避免泄露敏感数据）
        "observed_at": str,              # ISO timestamp，调用被观察到的时间
        "observation_method": str,       # 观察方式："module_spy" | "return_value_check" | "side_effect_trace" | "dogfood_trace"
    } | None,                            # module_invoked=false 时为 None
    # ⚠️ target_module_proof 要求（审计第三轮）：
    # invocation_proof 必须来自独立观测源（spy/return_marker/call_id/dogfood_trace），
    # handler 不得自我填充 invocation_proof。仅 handler 自报的 module_invoked=true 不算 target_module_proof。
    # 独立观测源的判定标准：
    #   - 观测者 != handler（spy 注入、return value marker、dogfood trace 等外部观察点）
    #   - call_id 可追溯到具体观测点
    #   - observation_method 明确记录观测方式
    "target_module_proof": {             # 独立观测证据（审计第三轮：与 invocation_proof 互补）
        "proof_id": str,                 # 独立观测证据 ID，必须非空
        "observation_source": str,       # 观测源："module_spy" | "return_marker" | "dogfood_trace" | "call_id_trace"
        "observer_identity": str,        # 观测者标识（spy 名称/trace 来源，与 handler 不同）
        "observation_independent": bool, # 观测是否独立于 handler（必须为 true 才构成 target_module_proof）
        "linked_action_id": str,         # 必须等于 evidence.action_id
        "linked_target_module": str,     # 必须等于 evidence.target_module
    } | None,                            # module_invoked=false 时为 None
    "evidence_level": str,               # "runtime_e2e" | "subsystem_integration" | "deterministic_baseline" | "simulated" | "not_covered"
    "result_returned_to_parent_runtime": bool, # RuntimeActionResult 是否已回到 Parent Runtime 主循环
    "parent_adjudicated": bool | None,   # 仅 SubAgent action：是否经过 parent adjudication
    # 仅 Skill action：audit-only 排除证据（不进入 model-visible payload，仅用于审计/验证）
    "audit_only_skill_exclusion_evidence": {  # 仅 skill.select action 有此字段
        "hidden_or_disabled_exclusion_verified": bool,  # 是否已验证 hidden/disabled skill 被正确排除
        "excluded_count": int,                           # 被排除的 skill 数量
        "redacted_exclusion_reason_categories": list[str],  # 排除原因类别，如 ["status_hidden", "status_disabled", "version_missing"]
    } | None,
}
```

**关键判定规则**：

- `module_invoked=false` → 无论 event 是否存在，**不得标 runtime_e2e**。
- `module_invoked` 缺失 → 同 false，不得标 runtime_e2e。
- `subsystem direct invocation`（未经过 Dispatcher）→ 最高只能 `subsystem_integration`。
- `模型文本提到 X` → **不算任何级别的 evidence**。
- `RuntimeActionEvent 存在但 invocation_proof 为 None 或缺少 function_called/call_id` → 最高只能 `subsystem_integration`（无法证明模块被调用）。
- 以下情况一律不得标 `runtime_e2e`：RuntimeActionEvent only；RuntimeActionEvent + module_invoked=true；
  RuntimeActionEvent + handler_name + target_module；module_invoked=true without target_module_proof；
  handler_name + target_module without target_module_proof；shaped dict invocation_proof without independent observation；
  free-text invocation_proof；model text mentions capability；handler self-asserted proof；
  handler self-minted target_module_call_id without independent observation。
- `target_module_proof` 缺失 `proof_id`、`linked_action_id` 不匹配 `action_id`、
  或 `linked_target_module` 不匹配 `target_module` → 最高只能 `subsystem_integration`。

---

## Track S：Skill Runtime Action

### S.1 设计目标

使 Runtime LLM（通过 tool calling）可以显式选择 skill（selected_skill_id 必须来自 RuntimeActionRequest.payload.model_decision_metadata），并产生可审计的 action event。SkillRuntimeActionHandler 必须记录 SkillRegistry validation path 被调用（验证 skill 存在且 active，非 selection decision source）、selected skill body 在选择后才加载、hidden/disabled skill 未暴露。

### S.2 action type

`skill.select`

### S.3 输入（payload）

```python
# 中文学习型注释：skill.select 的输入 payload。
# available_skill_metadata 只含 skill_id/description/tags/risk_level，不含 body，不含 status。
# hidden/disabled skill 不得出现在 available_skill_metadata 中（status 信息属于 audit-only 层，不可暴露给 model）。
# model_decision_metadata 是 LLM action decision 的结构化元数据，位于 RuntimeActionRequest.payload 内。
# selected_skill_id、selection_reason、selection_confidence 都必须来自该 metadata。
# handler 的职责是读取并验证（skill 存在且可被选择），不是生成、补写、推断或二次调用 LLM 获取这些字段。
{
    "task_summary": str,                          # 当前任务描述
    "constraints": list[str],                     # 约束条件，如 ["read_only", "no_shell"]
    "available_skill_metadata": [                 # 可选 skill 的 metadata 列表（不含 body）
        {
            "skill_id": str,                      # skill 名称
            "description": str,                   # skill 描述
            "tags": list[str],                    # 标签
            "risk_level": str,                    # 风险等级
        }
    ],
    "model_decision_metadata": {
        "selected_skill_id": str,                 # LLM 在 action decision 中指定的 skill name
        "selection_reason": str,                  # LLM action decision metadata 中的选择理由
        "selection_confidence": str,              # "high" | "medium" | "low" — LLM action decision metadata 中的置信度
    },
    "selected_skill_id": str,                    # 可保留兼容字段；若存在，必须与 model_decision_metadata.selected_skill_id 一致
    "selection_context": str | None,              # 额外的选择上下文（可选）
}
```

### S.3b 双层 redaction 模型（model-visible vs audit-only）

Skill 可用性信息必须拆成两个独立对象，不可混合：

**A. model_visible_available_skill_metadata**（暴露给 LLM 的上下文）

允许的字段：`skill_id`、`description`、`tags`、`risk_level`

禁止的字段：
- `status`（无论 active/disabled/hidden）
- `hidden_or_disabled_excluded_count`
- `excluded_count`
- `redacted_exclusion_reason_categories`
- hidden/disabled skill 的 name/body/metadata

**B. audit_only_skill_exclusion_evidence**（仅用于审计/验证，不进入 model context）

允许的字段：
- `hidden_or_disabled_exclusion_verified: true`
- `excluded_count`（即 `hidden_or_disabled_excluded_count`）
- `redacted_exclusion_reason_categories`（如 "version_missing", "status_hidden", "status_disabled" — 仅类别，不含名称）

禁止的字段：
- hidden/disabled skill 的 name
- hidden/disabled skill 的 body

**关键约束**：
- audit-only evidence 不进入 RuntimeActionRequest.payload（不发给模型）
- audit-only evidence 可进入 dogfood/audit report（但不暴露名称/body）
- model-visible metadata 不含任何 status 字段（status 信息属于 audit-only 层）

### S.4 输出（payload）

```python
# 中文学习型注释：skill.select 的输出 payload。
# selected_skill_id / selection_reason / selection_confidence 来自 RuntimeActionRequest.payload.model_decision_metadata，由 handler 验证后记录。
# body 在 LLM 选择后才加载（progressive disclosure），
# allowed_tools_after_selection 是加载 body 后从 descriptor 提取的实际 tools。
{
    "selected_skill_id": str | None,              # 选中的 skill name（来自 model_decision_metadata）
    "selection_reason": str,                      # 选择理由（来自 model_decision_metadata）
    "selection_confidence": str,                  # "high" | "medium" | "low" — 来自 model_decision_metadata
    "body_load_decision": bool,                   # body 是否被加载
    "allowed_tools_after_selection": list[str],   # 选中 skill 的 allowed_tools（从 descriptor 提取）
    "no_suitable_skill": bool,                    # 无可选 skill
    "available_skills_count": int,                # metadata 阶段可用的 skill 数量
    # hidden/disabled skill 的排除信息不在 payload 中暴露——payload 属于 model-visible 层。
    # 排除计数和原因类别仅通过 audit_only_skill_exclusion_evidence 提供（见 evidence 中的 audit_only 节），不进入 RuntimeActionRequest.payload。
}
```

### S.5 渐进式披露流程

1. Runtime LLM 收到可用 skill 的 metadata（name、description、tags、risk_level）——**不含 body**
2. LLM 通过 tool calling 调用 `skill.select` action，在 `RuntimeActionRequest.payload.model_decision_metadata` 中提供 selected_skill_id、selection_reason、selection_confidence
3. RuntimeActionDispatcher 路由到 SkillRuntimeActionHandler
4. Handler 读取并验证 model_decision_metadata，记录 selected_skill_id / selection_reason / selection_confidence，走 SkillRegistry validation path（验证 skill 存在且 active，非 selection decision source）
5. **此时才加载选中 skill 的 body**（调用 SkillLoader.load_body()）
6. 返回的 RuntimeActionResult 包含 body 内容（但不在 evidence 中暴露 body 全文）
7. Handler 必须在 structured invocation_proof 中记录 SkillLoader.load_body() 的调用结果（call_id + function_called + call_signature + observed_at）

### S.6 Skill runtime_e2e 必须证明（强制）

1. Runtime 发起 skill.select action（action event 证据）
2. SkillRegistry validation path invoked（handler invocation 证据——验证 skill 存在且 active，非 selection decision source）
3. selected_skill_id 有值且来自 RuntimeActionRequest.payload.model_decision_metadata（不是后验补的）
4. selection_reason 非空且来自 RuntimeActionRequest.payload.model_decision_metadata；handler/test harness/dogfood report 不得后验补
5. selection_confidence ∈ {"high", "medium", "low"} 且来自 RuntimeActionRequest.payload.model_decision_metadata；handler/test harness/dogfood report 不得后验补
6. selected skill body 在选择后才加载（body_load_decision=true，progressive disclosure）
7. hidden/disabled skill 未出现在 available_skill_metadata 中，其名称也不在任何 evidence 字段中暴露（仅通过 audit_only_skill_exclusion_evidence.excluded_count 记录数量，不进入 model-visible payload）。model-visible metadata 不含 status 字段（status 属于 audit-only 层）。
8. RuntimeActionResult.evidence 必须满足 R.6 Runtime E2E 11 项证据链：module_invoked=true, handler_name="SkillRuntimeActionHandler", target_module="SkillLoader", target_module_proof.proof_id 非空，target_module_proof.observation_independent=true，linked_action_id 匹配 action_id，linked_target_module 匹配 target_module，且结果返回 Parent Runtime。

### S.7 约束

- hidden/disabled skill 不得出现在 available_skill_metadata 中（其名称不得在任何 evidence 中暴露，仅可通过 audit_only_skill_exclusion_evidence.excluded_count 推断排除量）
- selected skill 的 allowed_tools 不得超出 skill descriptor 声明的范围
- 不直接执行 tools——tool execution 走 Track T（ToolRegistry Action Gate）
- missing `version` / `description` 等字段的 skill 不应出现在 available_skill_metadata 中（已在 8aa11a4 的 `get_load_errors()` 中解决）
- selected_skill_id / selection_reason / selection_confidence 必须来自 RuntimeActionRequest.payload.model_decision_metadata；handler 只做验证不做选择，不允许 handler、test harness 或 dogfood report 后验补
- handler 不得二次调用 LLM 获取 selection_reason / selection_confidence，不得根据自然语言猜测或推断这些字段
- 缺失 selected_skill_id、selection_reason、selection_confidence，或字段存在但不来自 model_decision_metadata，均不得标 runtime_e2e
- handler-invented 或 harness/report-invented selection_reason / selection_confidence 必须 fail

### S.8 不变式

1. available_skill_metadata 中的每个 skill 必须是 active 状态且有合法 descriptor。hidden/disabled skill 不得出现在 available_skill_metadata 中（model-visible metadata 不含 status 字段——status 信息属于 audit-only 层，不可暴露给 model）。
2. body 在 metadata 列表阶段不能被加载（progressive disclosure）。
3. selected skill 的 allowed_tools 必须 ∩ ToolRegistry visible tools 非空（否则 skill 选了也无法执行任何 tool）。
4. selected_skill_id / selection_reason / selection_confidence 必须来自 RuntimeActionRequest.payload.model_decision_metadata；handler 只做验证（skill 存在且 active），不得生成、补写、推断、二次调用 LLM 或重引入 SkillSelector 作为 decision source。

---

## Track A：SubAgent L0 Runtime Action

### A.1 设计目标

使 Runtime LLM（通过 tool calling）可以显式选择 SubAgent（subagent_name 是 RuntimeAction 的显式选择结果），触发 SubAgent L0 delegation，并产生可审计的 action event。SubAgentRuntimeActionHandler 必须记录 SubAgentRequest 被构建、delegate_once 被调用、parent adjudication 发生。

### A.2 action type

`subagent.delegate_l0`

### A.3 输入（payload）

```python
# 中文学习型注释：subagent.delegate_l0 的输入 payload。
# subagent_name 来自 model tool-call arguments（LLM 在 tool call 中显式指定）。
# handler 的职责是验证（该 SubAgent 存在且 active），不是"决定"委派给谁。
# available_subagent_metadata 提供可选 SubAgent 的 metadata，供 LLM 做选择。
{
    "delegation_goal": str,                       # 委托目标（来自 LLM）
    "context_package_summary": str,               # 上下文摘要（不超过 budget）
    "available_subagent_metadata": [               # 可选 SubAgent 的 metadata 列表
        {
            "subagent_name": str,                  # SubAgent 名称
            "description": str,                    # 描述
            "level": int,                          # L0 确定性执行
            "allowed_tools": list[str],            # 允许的工具列表
            "status": str,                         # active | disabled
        }
    ],
    "subagent_name": str,                         # LLM 选的 SubAgent name（显式选择结果）
    "budget": {"max_iterations": int},            # 迭代预算
    "parent_adjudication_required": bool,         # 必须为 true——parent adjudication 不可绕过
}
```

### A.4 输出（payload）

```python
# 中文学习型注释：subagent.delegate_l0 的输出 payload。
# subagent_name 来自 LLM decision，handler 记录在 payload 中。
# delegate_once 的调用结果记录在 execution_result 和 invocation_proof 中。
{
    "subagent_name": str,                         # 被委派的 SubAgent name（来自 LLM decision）
    "execution_result": str,                      # L0 执行结果摘要
    "delegate_once_called": bool,                 # delegate_once() 是否被实际调用
    "subagent_request_built": bool,               # SubAgentRequest 是否被构建
    "handoff_note": str | None,                   # 交接说明（如有）
    "adjudication": str,                          # Parent adjudication: "accept" | "reject" | "needs_review"
    "adjudication_reason": str,                   # 裁决理由
    "no_nested_delegation": bool,                 # 未发生嵌套 delegation
    "no_shell_or_external_process": bool,         # 未调用 shell/external process
}
```

### A.5 流程

1. Runtime LLM 通过 tool calling 调用 `subagent.delegate_l0` action，在 tool call arguments 中指定 subagent_name
2. RuntimeActionDispatcher 路由到 SubAgentRuntimeActionHandler
3. Handler 记录 subagent_name（LLM decision），检查：
   - SubAgent name 是否在 registry 中存在
   - SubAgent status 是否为 active
   - delegation 上下文中是否已有 in_delegation_context=True（防嵌套）
4. Handler 构建 SubAgentRequest，调用 `delegate_once(request, registry)`（现有 L0 executor）
5. Parent adjudication（现有 `SubAgentAdjudication` 逻辑）
6. Handler 在 structured invocation_proof 中记录 delegate_once 调用结果和 adjudication 结论（call_id + function_called + call_signature + observed_at）
7. 返回 RuntimeActionResult

### A.6 SubAgent runtime_e2e 必须证明（强制）

1. Runtime 发起 subagent.delegate_l0 action（action event 证据）
2. subagent_name 有值且来自 LLM tool call decision（显式选择）
3. SubAgentRequest 被构建（handler invocation 证据）
4. delegate_once 被调用（module invocation 证据）
5. Parent adjudication 发生（parent_adjudicated=true）
6. no nested delegation / no shell / no external process（边界检查）
7. RuntimeActionResult.evidence 必须满足 R.6 Runtime E2E 11 项证据链：module_invoked=true, handler_name="SubAgentRuntimeActionHandler", target_module="SubAgentExecutor", target_module_proof.proof_id 非空，target_module_proof.observation_independent=true，linked_action_id 匹配 action_id，linked_target_module 匹配 target_module，结果返回 Parent Runtime，parent_adjudicated=true。

### A.7 约束

**SubAgent L0 明确允许（allowed）：**

- 单个 SubAgent 的 L0 确定性执行（delegate_once）
- SubAgent descriptor 声明的 allowed_tools 子集内执行
- Parent adjudication 裁决（accept/reject/needs_review）
- 仅限 `subagent.delegate_l0` RuntimeAction

**SubAgent L0 明确禁止（prohibited）：**

- L1/L2 层级委派（嵌套 delegation）
- SubAgent 内再委派其他 SubAgent
- 自主规划（autonomous planning）或多智能体协作（multi-agent）
- 并行委派（parallel delegation）
- workspace automation（工作区自动化）
- memory handoff（SubAgent 直接写入 memory）
- 调用 shell/external process
- SubAgent 内使用真实 LLM（L0 executor 是确定性的）
- 绕过 parent adjudication
- 委托的 allowed_tools 不得超出 SubAgent descriptor 声明范围
- parent_adjudication_required 必须为 true

### A.8 不变式

1. SubAgent delegation 必须经过 parent adjudication。
2. 被委派的 SubAgent status 必须是 active。
3. delegation 的 tool list 必须是 SubAgent descriptor allowed_tools 的子集。
4. subagent_name 必须来自 model tool-call arguments（RuntimeActionRequest.payload.subagent_name），handler 只做验证（SubAgent 存在且 active），不得后验补。

---

## Track M：Memory Runtime Hook

### M.1 设计目标

在 Runtime 对话回合结束时，提供一个 turn-end hook point，使 Runtime 可以识别 memory-worthy content 并触发 proposal。Hook 必须在 user turn received + model response generated 之后触发，而不是只在 tool 执行之后——因为 memory-worthy 对话可能不涉及任何 tool call。

### M.2 action type

`memory.propose`

### M.3 hook point：turn-end hook（审计 P1-4 修复）

原设计为 "tool 执行完成后、下一轮 LLM 调用之前"，但 E04 场景（"请记住"类对话）不一定触发 tool call，导致 hook 无法触发。

**修复后**：Memory Runtime Hook 是 **turn-end hook**（或 response-end hook）。触发时机：

```
chat() loop:
  1. user turn received
  2. model response generated (streaming complete)
  3. tool calls executed (if any) — via Track T
  4. TURN-END: Memory Runtime Hook 扫描当前 turn
     → if memory-worthy content detected: trigger memory.propose RuntimeAction
  5. save checkpoint (with safe summary from Track C)
  6. continue loop or end
```

**关键变更**：
- Hook 在 step 4 触发，无论 step 3 是否发生了 tool execution。
- 如果 turn 没有任何 tool call，hook 仍然运行。
- Hook 输入包含 user message + assistant response + task context summary。

### M.4 输入（payload）

```python
# 中文学习型注释：memory.propose 的输入 payload。
# 由 turn-end hook 自动填充，不是来自 LLM tool call。
{
    "user_message": str,                       # 当前轮用户消息
    "assistant_response": str,                 # 当前轮模型响应
    "task_context_summary": str,               # 任务上下文摘要
    "prior_confirmed_memory_snapshot": str | None,  # 之前确认的 memory 摘要（供对比去重）
}
```

### M.5 输出（payload）

```python
# 中文学习型注释：memory.propose 的输出 payload。
# proposal 进入 pending_review，不自动 confirmed。
{
    "proposal_id": str | None,                 # 如有 proposal，返回 ID
    "disposition": str,                        # "proposed" | "no_action" | "should_not_remember"
    "reason": str,                             # 分类理由
    "secret_like_detected": bool,              # 是否检测到 secret-like 内容
    "pending_review": bool,                    # proposal 状态是否为 pending_review
    "not_confirmed": bool,                     # proposal 未被自动 confirmed
}
```

### M.6 约束

- **不 silent retain**：所有 memory 操作必须走 proposal→pending_review
- **不 auto approve**：proposal 不能自动变为 confirmed
- **secret-like filtering**：现有 `_SECRET_PATTERNS` 过滤保留
- **不改变 consolidation pipeline 内部逻辑**：Memory Runtime Hook 只负责"触发提案"，consolidation engine 负责"评估提案"
- **不读取真实 memory episodes 内容**（在 E2E 测试中）
- **hook 必须触发**：无论 turn 中有无 tool call，turn-end hook 必须运行

### M.7 不变式

1. Memory proposal 不得自动 confirmed。
2. secret-like 内容不得进入 proposal body。
3. Memory governance 不得被 Runtime Hook 绕过。
4. Runtime Hook 不得读取真实 sessions/runs/memory episodes。
5. Turn-end hook 在 tool-executed 和 no-tool turns 中都必须触发。

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

### T.4 输出（payload / gate_disposition）

This field is `gate_disposition`。Track T 中未显式写成 `evidence.decision` 的历史 `disposition` 引用，均指 `gate_disposition`，不是 capability matrix 的 final decision。

```python
{
    "gate_disposition": str,             # handler-level 即时输出："allowed" | "rejected" | "confirmation_required"
    "risk_level": str,                   # "low" | "medium" | "high"
    "policy_path": str,                  # 经过的 policy 路径（如 "tool_registry→risk_check→confirmation"）
    "rejection_reason": str | None,      # 拒绝理由（如有）
    # 以下三个字段拆分 module_invoked 语义（审计第二轮：消除歧义）：
    "registry_handler_invoked": bool,    # ToolGateHandler.handle() 是否被调用（gate 检查本身）
    "target_module_invoked": bool,       # 目标 tool 函数是否被实际调用（gate_disposition="allowed" 且执行成功）
    "dangerous_tool_function_invoked": bool,  # 高风险 tool（或 fake. 前缀 tool）的真实函数是否被执行（必须为 false）
}
```

**gate_disposition vs evidence.decision 分层说明**：

gate_disposition 和 evidence.decision 是不同层的两个独立字段，不可混用。gate_disposition 只用于真实工具 gate handler 的 handler-level immediate output；evidence.decision 是 RuntimeActionResult / capability matrix 的 final evidence-level classification。

| 层 | 字段 | 作用域 | 值域 |
|----|------|--------|------|
| handler-level | `gate_disposition`（T.4 payload） | ToolGate handler 即时输出，判定单个 tool request 的 gate 结果 | `"allowed"`, `"rejected"`, `"confirmation_required"` |
| evidence-level | `evidence.decision`（E.3 tool_evidence） | capability matrix 最终 evidence 分类，综合 handler 输出 + registry 查询 + fake overlay 判定 | `"allowed"`, `"rejected"`, `"confirmation_required"`, `"not_found"`, `"blocked"` |

**映射关系**：
- `gate_disposition=allowed` → `evidence.decision=allowed`
- `gate_disposition=rejected` → `evidence.decision=rejected`
- `gate_disposition=confirmation_required` → `evidence.decision=confirmation_required`
- tool 在 production ToolRegistry 中不存在 → `evidence.decision=not_found`（没有 gate_disposition，直接判定）
- fake.* 高风险 blocked path → `evidence.decision=blocked`（gate_disposition 不适用——fake tool 不经过真实 ToolRegistry gate）
- `not_found` / `blocked` 是 evidence-level decision，不是普通真实工具 gate_disposition。
- fake high-risk blocked path 是 evidence-level final verdict，不得用 `confirmation_required` 代替 `blocked`。
- fake.* 不进入 production ToolRegistry，不进入 production capability matrix。

### T.5 流程

1. LLM tool call → RuntimeActionDispatcher 接收 `tool.request`
2. Dispatcher 查询 ToolRegistry：tool 是否存在、是否 visible、risk level
3. 高风险 tool → 触发 confirmation（现有 ConfirmationContext 逻辑）
4. 允许的 tool → 执行（现有 `execute_tool_call`）
5. 返回 RuntimeActionResult（包含 gate_disposition、risk_level、registry_handler_invoked、target_module_invoked、dangerous_tool_function_invoked）
   - registry_handler_invoked：gate 检查是否发生（始终为 true，除非 dispatcher 路由失败）
   - target_module_invoked：实际 tool 函数是否被调用（仅 gate_disposition="allowed" 时为 true）
   - dangerous_tool_function_invoked：高风险 tool 的真实函数是否被执行（对 fake. 前缀 tool 必须为 false；对真实高风险 tool，仅在 confirmation 通过后才为 true）

### T.6 Tool Alias Policy（审计 P2-3 新增）

文档中的 generic capability name 和 actual registry tool name 必须分开：

| Generic Capability | 文档引用名 | 说明 |
|--------------------|-----------|------|
| `file_read` | `read` 能力 | 读取文件内容 — 具体的 actual_tool_name 从 ToolRegistry 解析 |
| `file_write` | `write` 能力 | 写入文件 — 高风险，需 confirmation |
| `shell_command` | `shell` 能力 | **当前阶段禁止** — 属于 non-goal |
| `file_search` | `grep` 能力 | 文本搜索 — 具体的 actual_tool_name 从 ToolRegistry 解析 |

**规则**：
- E2E dogfood plan 中的 allowed_tools 必须使用 ToolRegistry 中的真实 tool name，或明确标记为 `fake.` 前缀的测试 tool。
- **`fake.` 前缀 tool（如 `fake.write_file`、`fake.modify_config`）仅在 dogfood runner 本地注册，绝不污染真实 ToolRegistry**。真实 ToolRegistry 中不得出现 `fake.` 前缀的 tool。
- capability matrix 必须记录：`requested_capability` → `requested_tool_name` → `resolved_tool_name` → `production_registry_found` → `dogfood_overlay_found` → `evidence.decision`。
- 如果 tool 在 registry 中不存在，scenario 不能 pass。
- 禁止使用 `bash`、`shell`、`run_shell` 作为 allowed tool（违反 non-goal）。

### T.6b Fake High-Risk Blocked Path Evidence Schema（统一 blocked path contract）

fake. 前缀高风险 test tool 的 blocked path 必须使用以下统一 evidence schema：

```python
fake_blocked_path_evidence = {
    "requested_tool_name": str,              # 请求的 tool name（如 "fake.write_file"）
    "requested_capability": str,             # 请求的能力（如 "file_write"）
    "production_registry_found": False,      # 必须为 false——fake tool 不在 production ToolRegistry
    "dogfood_overlay_found": True,           # 必须为 true——仅在 dogfood-local fake tool overlay
    "overlay_tool_name": str,                # overlay 中的 tool name
    "resolved_test_tool_name": str,          # 解析到的 test tool name
    "registry_handler_invoked": True,        # gate 检查发生
    "target_module_invoked": True,           # test tool handler 被调用（但不执行真实 IO）
    "dangerous_tool_function_invoked": False, # 必须为 false——fake tool 不触发真实 IO
    "decision": "blocked",                   # 即 evidence.decision="blocked"；fake high-risk path 最终 verdict
}
```

**fail 条件**：
- `production_registry_found=true` for fake.* → fail
- `dogfood_overlay_found=false` for fake.* → fail
- `dangerous_tool_function_invoked=true` → fail
- fake.* persisted into production ToolRegistry → fail
- fake.* exposed to normal runtime → fail
- fake.* appears in production capability matrix as real capability → fail
- `evidence.decision=confirmation_required` for fake high-risk blocked path → fail

**关键区分**：
- `confirmation_required` 是真实高风险工具（非 fake. 前缀）可能使用的 decision——需要用户确认后才能执行
- `blocked` 是 fake high-risk dogfood path 的唯一最终 verdict——fake tool 不经过 confirmation，直接 blocked
- 不得用 `confirmation_required` 替代 fake blocked path 的最终 verdict

### T.7 约束

- 不绕过现有 ToolRegistry 注册/可见性/风险分级逻辑
- 不改变 confirmation 流程
- 不新增 tool 类别/注册方式
- `fake.` 前缀 test tool 仅在 dogfood runner 本地注册，不得进入真实 ToolRegistry
- 真实 ToolRegistry 中不得存在 `fake.` 前缀的 tool name

### T.8 不变式

1. hidden/unknown tool 必须被拒绝。
2. 高风险 tool 必须经过 confirmation。
3. tool execution 结果不得包含 secret。
4. registry_handler_invoked 为 true 不代表 target_module_invoked 为 true（gate 检查 ≠ tool 执行）。
5. dangerous_tool_function_invoked 对 fake. 前缀 tool 必须为 false。
6. fake. 前缀 tool 不得存在于真实 ToolRegistry 中。

---

## Track C：Checkpoint-safe Runtime Summary

### C.1 设计目标

在 Runtime turn 结束后、save_checkpoint 之前，提供一个 hook 产生 checkpoint-safe summary，确保 checkpoint 中不包含 secret、raw huge prompt、或 pending high-risk tool 的重放数据。

### C.2 action type

`checkpoint.safe_summary`

### C.3 hook point

在 `chat()` 的 turn 结束、`save_checkpoint` 调用之前：

```
chat() loop:
  1. model call
  2. tool execution (via Track T, if any)
  3. turn-end memory hook (Track M)
  4. generate checkpoint-safe summary (via Track C)
  5. save checkpoint (with safe summary)
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

确保 Runtime 在消费 provider streaming events 时正确收集 final/error 语义，并产生 E2E dogfood 可验证的 evidence。**同时处理 unsupported provider 的 fail-closed 分支。**

### P.2 action type

`streaming.event`

### P.3 输入/输出与 evidence 分层（审计 P2-1 修复）

Streaming Track P 的 evidence 分为三层，不可混淆：

**A. deterministic provider capability evidence（非 runtime_e2e）:**

例如 `supports_streaming=false` → status=not_supported。这不是 streaming runtime_e2e pass，而是 honest fail-closed。

**B. subsystem / provider evidence（非 runtime_e2e）:**

例如 provider 能在隔离环境 emit text_delta/final event。这是 streaming behavior evidence，不是 runtime_e2e pass。text_delta / final / error 事件只是 streaming behavior evidence，不等于 runtime_e2e。

**C. runtime_e2e streaming evidence（必须满足 R.6）:**

如果标 runtime_e2e，必须经过 RuntimeActionDispatcher → streaming handler → target module → target_module_proof → Parent Runtime result。完整流程：

- RuntimeActionEvent emitted
- RuntimeActionDispatcher routed
- streaming handler invoked
- target streaming module invoked
- module_invoked=true
- target_module_proof 存在且 observation_independent=true
- target_module_proof.linked_action_id 匹配 action_id
- target_module_proof.linked_target_module 匹配 target_module
- text_delta / final / error 事件绑定同一 action_id
- final result 返回至 Parent Runtime

如果没有 target_module_proof，只能标 deterministic / subsystem / not_supported。

RuntimeActionDispatcher 在每次 streaming 交互完成后记录：

```python
evidence = {
    "events_received": int,              # 收到的事件数
    "final_event_received": bool,        # 是否收到 final 事件
    "error_event_received": bool,        # 是否收到 error 事件
    "text_sanitized": bool,              # 是否执行了 secret sanitization
    "sequence_monotonic": bool,          # sequence 是否单调递增
    "provider_supports_streaming": bool, # provider 是否支持 streaming
    # ——以下为 R.6 proof 字段（runtime_e2e 必须）——
    "target_module_proof": dict | None,  # R.6 module invocation proof
}
```

### P.4 约束

- 不扩大 Observability（不引入 metrics / dashboard）
- evidence 仅用于 E2E dogfood 验证
- 不改变 `collect_stream_response` / `sanitize_stream_text` 的行为

### P.5 Unsupported Provider Branch（审计 P2-1 新增）

当前 provider 并不都支持 streaming（如 `openai_compatible` 明确 `supports_streaming=False`）。文档必须明确 fail-closed 分支：

**如果 `provider.supports_streaming == False`**：

```
1. streaming.event RuntimeAction status = "not_supported"
2. evidence["provider_supports_streaming"] = false
3. evidence["events_received"] = 0
4. evidence["final_event_received"] = false
5. evidence_level 不得标 runtime_e2e streaming pass
6. 不得 silent fallback 成 non-streaming 后还算 streaming pass
7. 不得生成 fake final event
```

**E07 pass 条件分支**：

- 若 provider supports streaming：必须验证 text_delta / final / error
- 若 provider 不支持 streaming：必须验证 fail-closed / not_supported，**不能算 streaming runtime pass**——E07 scenario 对于 unsupported provider 只能是 `partial` 或 `blocked`，不能是 `pass`。

---

## Track E：Capability Evidence Matrix 修复

### E.1 问题

当前 `_capability_evidence_matrix` 中 capability name（如 `"SubAgent"`）与 `systems_actually_invoked` 中的模块名（如 `"SubAgentRegistry"`）不匹配，导致 set intersection 失败。

### E.2 解决方案：统一 mapping table

```python
# 中文学习型注释：capability name → module alias 的映射表。
# 能力矩阵和 scenario result 必须使用同一套命名，避免 set intersection 失败。
CAPABILITY_MODULE_MAPPING: dict[str, tuple[str, ...]] = {
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

### E.3 Tool Alias Policy for Capability Matrix（审计 P2-3 新增）

Capability matrix 必须记录完整的 tool name 解析链：

```python
# 每个 tool-related capability 的 evidence 必须包含：
tool_evidence = {
    "requested_capability": str,    # 请求的能力（如 "file_read"）
    "requested_tool_name": str,     # 请求的 tool name（可能是 generic name）
    "resolved_tool_name": str,      # 从 ToolRegistry 解析到的实际 tool name
    "production_registry_found": bool,  # tool 是否在 production ToolRegistry 中存在
    "dogfood_overlay_found": bool,      # tool 是否仅在 dogfood-local fake tool overlay 中存在（fake. 前缀 tool）
    "decision": str,                # evidence.decision（final evidence-level classification，非 gate_disposition）: "allowed" | "rejected" | "confirmation_required" | "not_found" | "blocked"
}
```

- tool alias mismatch 导致 capability evidence 错误，至少 P2。
- 如果 tool 在 production ToolRegistry 中不存在且不在 dogfood-local fake tool overlay 中，scenario 不能 pass。
- production_registry_found=false + dogfood_overlay_found=false → tool 不存在于任何合法命名空间。
- E2E dogfood plan 必须要求从 ToolRegistry 读取真实 tool names，dogfood-local fake tool overlay 仅用于高风险诱导测试。

### E.4 evidence level 分级

| Level | 定义 | 来源 | 前置条件 |
|-------|------|------|----------|
| `runtime_e2e` | Runtime LLM 通过 RuntimeAction 实际触发了该能力，有独立观测的 target_module_proof | Runtime E2E 11 项证据链：event emitted、Dispatcher routed、handler invoked、module_invoked=true、target_module_proof exists、proof_id present、observation_independent=true、linked_action_id 匹配、linked_target_module 匹配、result returned、parent_adjudicated where applicable | 必须满足 R.6 Action Evidence Contract 全部条件 |
| `subsystem_integration` | 子系统模块 API 被程序化调用并验证正确性，但未经过 Runtime LLM | systems_actually_invoked（非 runtime 路径） | 不能出现 RuntimeActionEvent（否则可能是假 runtime_e2e） |
| `deterministic_baseline` | 确定性函数/协议（如 streaming），已验证正确性 | 纯函数测试 | 无外部依赖 |
| `simulated` | mock 或模拟数据 | systems_simulated | 明确标记 simulated |
| `not_covered` | 无任何覆盖 | 无 | — |

### E.5 不变式

1. capability 不得被标记为 `runtime_e2e` 除非满足 R.6 Runtime E2E 11 项证据链；RuntimeActionEvent、module_invoked=true、handler_name+target_module 都不是充分条件。
2. `subsystem_integration` 不得被报告为 `runtime_e2e`。
3. mapping table 是 capability name 的单一事实来源。
4. RuntimeActionEvent 存在但 module_invoked=false → 最高只能 subsystem_integration。（审计 P1-2 新增）
5. module_invoked=true 但 target_module_proof 缺失、proof_id 缺失、observation_independent=false、linked_action_id 不匹配或 linked_target_module 不匹配 → 最高只能 subsystem_integration。
6. 模型文本提到能力 → 不算任何级别的 evidence。（审计 P1-2 新增）
7. handler 自我填充 invocation_proof 或 target_module_proof → 不构成 runtime_e2e。（审计第三轮新增）

---

## 设计总结

| Track | action type | 触发方式 | 子系统 | evidence 关键字段 |
|-------|-------------|----------|--------|-------------------|
| R | (dispatcher) | LLM tool call / Runtime policy | 所有 | action_id, handler_name, target_module, module_invoked, target_module_proof(proof_id, observation_independent, linked_action_id, linked_target_module) |
| S | skill.select | LLM tool call | Skill System | selected_skill_id, selection_reason, selection_confidence, body_load_decision, SkillLoader invocation |
| A | subagent.delegate_l0 | LLM tool call | SubAgent System | subagent_name, delegate_once_called, parent_adjudicated, subagent_request_built |
| M | memory.propose | Runtime turn-end hook | Memory System | proposal_id, disposition, pending_review, not_confirmed |
| T | tool.request | LLM tool call / Runtime policy | ToolRegistry | gate_disposition, evidence.decision, risk_level, registry_handler_invoked, target_module_invoked, dangerous_tool_function_invoked |
| C | checkpoint.safe_summary | Runtime hook | Checkpoint | safe_summary, secret_content_detected, pending_high_risk_tool |
| P | streaming.event | Runtime(被动) | Streaming Protocol | provider_supports_streaming, not_supported branch |
| E | (mapping) | N/A | 所有 | capability→module mapping, tool alias resolution chain |

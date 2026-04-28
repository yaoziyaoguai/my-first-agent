# Runtime State Machine (v0.2 M1)

> **本文目的**：v0.2 M1 把当前 Runtime 状态机从「散落 if/else + 多个 pending
> 字段」整理成一份可阅读、可测试、可维护的基线 spec。它是 v0.2 后续 milestone
> （事件边界治理、checkpoint 恢复语义、错误恢复、工具体系、TUI、cancel 生命
> 周期）共同的参考点。
>
> **核心边界**：M1 只做只读审计 + spec 文档 + 最小不变量测试，不重写状态机，
> 不引入 LangGraph、不做 TUI、不做 P1 feedback intent flow、不做 slash
> command、不做 generation cancellation、不做 Skill / sub-agent，不动 LLM
> Processing 已收口能力。任何超出本文档范围的「顺手收口」请走 `docs/V0_2_PLANNING.md`
> 的对应 milestone。

---

## 1. 状态字段总览

Runtime 状态分两类：**持久 checkpoint 状态** 和 **runtime 临时状态**。
M1 不修改 schema，只把现状写清楚。

### 1.1 持久 checkpoint 状态（写入 `memory/checkpoint.json`）

`save_checkpoint` / `load_checkpoint_to_state` 通过 `_copy_state_dict(state.task)`
和 `_copy_state_dict(state.memory)` 将整段 dataclass `__dict__` 序列化为 JSON；
`conversation.messages` 单独经 `_truncate_messages_for_checkpoint` 持久化。

`TaskState`（`agent/state.py`）持久字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `user_goal` | `str \| None` | 当前用户目标 |
| `current_plan` | `dict \| None` | 当前计划 dict（未来可能升级为 `Plan` 类） |
| `current_step_index` | `int` | 当前步骤索引 |
| `status` | `str` | 任务状态（见 §2） |
| `retry_count` | `int` | 当前轮重试次数 |
| `loop_iterations` | `int` | 主循环迭代次数 |
| `consecutive_max_tokens` | `int` | 连续 max_tokens 次数 |
| `consecutive_end_turn_without_progress` | `int` | 连续 end_turn 无进展次数 |
| `tool_call_count` | `int` | 已发生工具调用计数 |
| `last_error` | `str \| None` | 最近错误信息 |
| `effective_review_request` | `bool` | 当前轮是否生效 review |
| `pending_tool` | `dict \| None` | 工具确认子状态（见 §3.1） |
| `pending_user_input_request` | `dict \| None` | 用户输入等待子状态（见 §3.2） |
| `confirm_each_step` | `bool` | 是否每步确认 |
| `tool_execution_log` | `dict[str, dict]` | 工具执行幂等记录 |

`MemoryState`：`working_summary / long_term_notes / checkpoint_data /
session_id`。

`ConversationState`：仅 `messages`（`tool_traces` 不进 checkpoint）。

`RuntimeState`：**不进 checkpoint**（运行配置，每次启动重建）。

### 1.2 Runtime 临时状态 / UI 事件（**不**进 checkpoint，不进 messages）

| 类型 | 模块 | 用途 | 边界 |
|---|---|---|---|
| `InputIntent` | `agent/input_intents.py` | UI Adapter → Runtime 输入语义归一 | 不写 checkpoint，不写 messages |
| `InputResolution` | `agent/input_resolution.py` | `awaiting_user_input + USER_REPLIED` 解析 | 只读，不写 state |
| `RuntimeEvent` | `agent/model_output_resolution.py` | 模型输出 → 观测/UI 渲染 | 只读事件 |
| `DisplayEvent` | `agent/display_events.py` | Runtime → UI 用户可见输出 | 不进 messages，不进 checkpoint |
| `TransitionResult` | `agent/transitions.py` | transition 后控制流提示 | 函数返回值，无生命周期 |
| `runtime_observer.log_*` | `agent/runtime_observer.py` | 观测日志，写 `agent_log.jsonl` | 不修改 state |

> **铁律**：上述类型都是「输入分类 / 输出渲染 / 观测日志」边界，**绝对不能**
> 写入 `state.task.*`、`state.conversation.messages`、`state.memory.*` 或
> `checkpoint.json`。任何把它们当持久数据使用的 PR 都违反 v0.2 M1 边界。

## 2. status 枚举

由 `agent/state.py::KNOWN_TASK_STATUSES` 集中定义：

| status | 类别 | 解锁动作 | 备注 |
|---|---|---|---|
| `idle` | 生命周期 | 用户输入 → planning | 初始态 / reset_task 后 |
| `planning` | 生命周期 | planner 产出 plan → awaiting_plan_confirmation | 短瞬态 |
| `running` | 生命周期 | model end_turn / advance_step / 工具结果 | 主执行态 |
| `awaiting_plan_confirmation` | plan 子状态 | 用户 y/n/feedback | 必须有 `current_plan` |
| `awaiting_step_confirmation` | step 子状态 | 用户 y/n/feedback | `confirm_each_step=True` 才出现 |
| `awaiting_user_input` | 用户输入子状态 | 用户回复 → step_input 写入 | 见 §3.2 两种子语义 |
| `awaiting_tool_confirmation` | 工具确认子状态 | 用户 y/n → execute_pending_tool | 必须有 `pending_tool` |
| `awaiting_feedback_intent` | P1 输入语义子状态 | 用户 1/2/3 显式选择 | 与 awaiting_user_input 同构，复用 pending |
| `done` | 终止态 | reset_task → idle | 不再要求 plan |
| `failed` | 终止态 | reset_task / 用户重试 | 不再要求 plan |
| `cancelled` | 终止态 | reset_task | 不再要求 plan |

`task_status_requires_plan(task)` 在「`current_plan is None` 是否属于损坏态」
这一条 invariant 上集中表达上述差异；详见 `tests/test_state_invariants.py`。

## 3. 子状态字段边界

### 3.1 `pending_tool`

- 触发：模型 `tool_use` 命中需要确认的工具，handler 把 `{tool_use_id, tool,
  input}` 写入 `pending_tool`，`status=awaiting_tool_confirmation`。
- 解锁：用户 `y` → `execute_pending_tool` → 清 `pending_tool` → `running`；
  用户 `n` → 清 `pending_tool` → 回到 `running`（or terminal）。
- **边界**：`pending_tool` 与 `pending_user_input_request` 是**独立两个字段**，
  同时只应有一个为非 None。`awaiting_tool_confirmation` 不会写
  `pending_user_input_request`；`awaiting_user_input` 不会写 `pending_tool`。

### 3.2 `pending_user_input_request`

`awaiting_user_input` 内部有两种子语义（**同一个 status**）：

| 子语义 | `pending_user_input_request` | step 推进规则 | InputResolution |
|---|---|---|---|
| `collect_input` / `clarify` 步骤答复 | `None` | 答完推进 step | `COLLECT_INPUT_ANSWER` |
| `request_user_input` / fallback 中途求助 | 非空，含 `awaiting_kind` | 不推进 step，只补当前 step 上下文 | `RUNTIME_USER_INPUT_ANSWER` |

`awaiting_feedback_intent` 与 `awaiting_user_input` 同构：复用
`pending_user_input_request` 携带恢复上下文（待分流文本 + origin_status），
不引入新字段。

### 3.3 `tool_execution_log`

幂等用：`tool_use_id → {tool, input, result}`。重启后用于跳过已执行工具，
避免恢复时重复副作用。

## 4. 事件 → 状态影响表

| 事件 | 来源 | 主要状态影响 | 持久化 |
|---|---|---|---|
| user.input.normal | InputIntent (`normal_message`) | `idle/done` → `planning` → `awaiting_plan_confirmation` | save_checkpoint after plan |
| user.input.confirmation (plan/step/tool) | InputIntent confirmations | 清 `pending_*`，推进或回退 | save_checkpoint per transition |
| user.replied | `apply_user_replied_transition` | `awaiting_user_input` → `running`（清 `pending_user_input_request`） | save_checkpoint |
| plan.generated | `generate_plan` | `planning` → `awaiting_plan_confirmation` | save_checkpoint |
| plan.approved | `confirm_handlers` | → `running`，`current_step_index=0` | save_checkpoint |
| plan.rejected/feedback | `confirm_handlers` | 清 plan，重新 planning 或 reset | save / clear_checkpoint |
| step.completed | `mark_step_complete` 元工具 | `advance_current_step_if_needed` → `running` 或 `done` | save_checkpoint |
| tool.requested | `response_handlers` | 写 `pending_tool` → `awaiting_tool_confirmation`（如需确认） | save_checkpoint |
| tool.result | `tool_executor` | append `tool_result`，更新 `tool_execution_log/tool_call_count` | save_checkpoint |
| model.end_turn | `response_handlers.resolve_end_turn_output` | running 或 终止；累加 `consecutive_end_turn_without_progress` | save_checkpoint |
| model.request_user_input | `response_handlers` | 写 `pending_user_input_request` → `awaiting_user_input` | save_checkpoint |
| runtime.no_progress | `response_handlers` | 兜底切 `awaiting_user_input` 防死循环 | save_checkpoint |
| checkpoint.resume | `agent/session.py` | 加载持久字段，UI 通过 `_replay_awaiting_prompt` 重放提示 | 只读 |
| error / loop_guard | `agent/core.py` | `last_error`、`retry_count`、可能切 terminal | save_checkpoint |

每一条「修改 status」的 transition 都必须立刻 `save_checkpoint`（见
`task_runtime.advance_current_step_if_needed` 的注释）。

## 5. 当前混乱点（M1 已识别，不在本轮收口）

记录现状，避免被未来「顺手清理」误改：

1. **`status` 是单字段混合维度**：`idle/planning/running/done/failed/cancelled`
   是生命周期；`awaiting_*` 是 UI/输入子状态；`awaiting_feedback_intent` 是
   P1 输入语义。理想拆分是 `lifecycle_status / plan_status /
   user_input_status / tool_status`，但拆分会动 checkpoint schema、handler
   分派和大量测试。**M1 不拆**；helper（`PLAN_CONFIRMATION_STATUSES /
   USER_INPUT_WAIT_STATUSES / TOOL_CONFIRMATION_STATUSES /
   FEEDBACK_INTENT_WAIT_STATUSES`）已经把字符串判断收口到一个地方。
2. **`awaiting_user_input` 双语义靠 `pending_user_input_request` is None 判定**：
   `collect_input/clarify` step 答复（pending=None）vs runtime 中途求助答复
   （pending 非空）共用同一 status。`InputResolution` + `transitions` 已经显式
   分流；**M1 不引入新 status**，避免 checkpoint 不兼容。
3. **`task.status` 不通过 RuntimeEvent 投影到 UI**：`task.status` 改变不会自动
   触发 RuntimeEvent control.message；UI 依赖 handler 在转移点显式
   `emit_display_event`。这是 v0.2 M2「事件边界治理」的工作，**M1 不做**。
4. **`session.py::_replay_awaiting_prompt` 在 resume 路径走裸 print**：
   plan/step/pending input 在恢复时通过 print 直接重放。归 v0.2 RuntimeEvent
   边界治理，**M1 不动**。
5. **`tool_execution_log` 幂等性依赖 dict 插入顺序**：Python 3.7+ 保证插入序，
   `mark_step_complete` 「后来居上」语义依赖此特性。隐式契约，建议在 v0.2
   step 状态拆分时用更显式的数据结构表达。
6. **`checkpoint.py::_copy_state_dict` 全字段持久化**：`TaskState.__dict__`
   全 JSON 序列化；如果有人把 `RuntimeEvent / InputIntent / CommandResult`
   实例放进 task 字段，会被 `_safe()` 兜底 `str()` 而不是报错。M1 通过
   `tests/test_runtime_state_machine_invariants.py` 加显式 invariant，
   防止架构边界被悄悄破坏。

## 6. M1 收口边界 / 非目标

**M1 做**：
- 本文件（state machine spec）。
- `tests/test_runtime_state_machine_invariants.py`：架构边界 invariant 测试。
- 不修改任何状态字段或 status 枚举；不引入新 awaiting 子状态；不新增
  RuntimeEvent / DisplayEvent kind；不改 LLM Processing。

**M1 不做**：
- 不拆 `TaskState.status` 为多维度。
- 不收口 `session.py::_replay_awaiting_prompt` 的 print 旁路（→ v0.2 M2）。
- 不引入 cancel_token / generation lifecycle（→ v0.2 M8）。
- 不做 LangGraph、不做正式 state machine framework。
- 不做 Skill / sub-agent / TUI / topic switch / slash command。
- 不修复 §5 列出的「混乱点」中需要 schema 变化的部分。

## 7. 不变量测试清单

`tests/test_runtime_state_machine_invariants.py` 提供以下架构边界保护：

1. **checkpoint 顶层 keys 白名单**：序列化 JSON 的顶层 key 集合 = `{meta,
   task, memory, conversation}`，不会出现 RuntimeEvent / InputIntent /
   DisplayEvent 等 UI/事件类。
2. **checkpoint task keys ⊆ TaskState dataclass fields**：防止 handler 临时
   字段悄悄进入 checkpoint。
3. **`pending_tool` 与 `pending_user_input_request` 字段独立**：dataclass 上
   是两个独立字段；`awaiting_tool_confirmation` 路径不会写
   `pending_user_input_request`，`awaiting_user_input` runtime 子语义路径
   不会写 `pending_tool`。
4. **`apply_user_replied_transition` 对 messages 是 append-only**：transition
   前后已有 messages 在同一索引保持 identity 等价。
5. **`_project_to_api` 是纯投影**：`state.conversation.messages` 在 projection
   后内容、长度、对象身份均不变；返回值是新 list。
6. **checkpoint resume 后 task 字段类型 = TaskState 声明类型**：不会因为
   load 把 dict/list 变成 RuntimeEvent / InputIntent / CommandResult。
7. **`ConversationState.tool_traces` 不进 checkpoint**：tool_traces 是会话
   分析层字段，不属于恢复语义。
8. **InputIntent / InputResolution / TransitionResult 模块不导出 checkpoint
   写入入口**：架构边界负向 assert，防止未来误把这些类型挂到 checkpoint。

测试要保护**架构边界**，不要绑定过多内部命名；如必须绑定字段，请用中文
注释说明这是当前 v0.2 M1 的显式契约。

## 8. M1 是否完成

- 本文件 ✅
- `tests/test_runtime_state_machine_invariants.py` ✅
- `pytest -q` 全绿 ✅
- 没有引入新 awaiting 子状态、新 RuntimeEvent kind、新工具、新 skill ✅
- 没有动 LLM Processing 已收口能力 ✅

**M1 阶段性收口**。下一步按 `docs/V0_2_PLANNING.md` 进入 M2「InputIntent /
RuntimeEvent / DisplayEvent 边界治理」。

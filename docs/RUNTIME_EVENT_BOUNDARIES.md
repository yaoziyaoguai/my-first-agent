# Runtime Event Boundaries (v0.2 M2)

> **本文目的**：v0.2 M2 把 `InputIntent / RuntimeEvent / DisplayEvent /
> CommandResult / conversation.messages / checkpoint / context_builder._project_to_api`
> 这一组「输入分类、输出投影、协议投影、持久化」边界写成显式契约。
>
> **核心边界**：M2 只做边界审计 + spec 文档 + 不变量测试 + 最小代码硬化，
> **不重写**事件系统、**不新增** RuntimeEvent kind、**不做** TUI / Skill /
> cancel / topic switch / slash command、**不动** LLM Processing 已收口能力。

---

## 1. 三层职责

Runtime 主线由「输入 → 状态机 → 输出」三层支撑，每层有自己的对象边界：

```
                ┌─────────────────────────────────────────────┐
   user / TUI ─→│ InputIntent (输入分类，只读)                 │
                │   agent/input_intents.py                    │
                └────────────────┬────────────────────────────┘
                                 │
                                 ▼
                ┌─────────────────────────────────────────────┐
                │ Runtime State (持久 / 临时)                 │
                │   agent/state.py + agent/checkpoint.py      │
                │   - TaskState / MemoryState (持久)          │
                │   - ConversationState.messages (持久)       │
                │   - ConversationState.tool_traces (临时)    │
                └────────────────┬────────────────────────────┘
                                 │
                                 ▼
                ┌─────────────────────────────────────────────┐
                │ RuntimeEvent / DisplayEvent (输出投影)      │
                │   agent/display_events.py                   │
                │   agent/runtime_observer.py (观测，不修改)  │
                └─────────────────────────────────────────────┘

                旁路投影 (只读)：
                  context_builder._project_to_api
                   conversation.messages → Anthropic API messages
```

## 2. 对象边界一览

| 对象 | 模块 | 角色 | 允许写入处 | **禁止**进入 |
|---|---|---|---|---|
| `InputIntent` | `input_intents.py` | UI 输入分类 | handler 局部变量 | checkpoint、messages、状态字段 |
| `InputResolution` | `input_resolution.py` | `awaiting_user_input + USER_REPLIED` 解析 | handler 局部 | checkpoint、messages |
| `RuntimeEvent` | `display_events.py` | Runtime → UI 输出投影 | UI sink 回调 | checkpoint、messages、`task.*` |
| `DisplayEvent` | `display_events.py` | UI 可渲染最小事件 | UI sink 回调 | checkpoint、messages、`task.*` |
| `TransitionResult` | `transitions.py` | transition 函数返回值 | handler 局部 | checkpoint、messages |
| `CommandResult` | （已退役） | slash-command 时代结果对象 | — | checkpoint、messages |
| `conversation.messages` | `state.py` | append-only 事件流 + Anthropic 协议事实源 | `append_*` helper | 不能被 transition 重写已有项 |
| `tool_traces` | `state.py` | 会话分析层 | `state.add_tool_trace` | checkpoint |
| `task.*` 字段 | `state.py` | 持久任务状态 | handler / transition | RuntimeEvent / DisplayEvent / InputIntent 实例 |
| `agent_log.jsonl` | `runtime_observer.py` | 观测日志 | `log_event/log_resolution/log_transition/log_actions` | 用户可见 stdout（除 debug 旗下） |

> **CommandResult 注**：源自 slash-command 系统，commit 205c4cf 已整体下线。
> M2 在 `agent/input_intents.py` 顶层注释保留对该名字的提示，仅作为「禁止
> 复活路径」存在。如果未来再做命令调度，请先单独走 spec 评审而不是直接命名
> `CommandResult`。

## 3. 边界禁止清单（架构红线）

下面每一条都对应 `tests/test_runtime_event_boundaries.py` 的一条 invariant：

1. **InputIntent / InputResolution / TransitionResult / RuntimeEvent /
   DisplayEvent dataclass 必须 `frozen=True`**：禁止 handler 把它们当可变状态
   缓存，避免「事件→状态」这种隐式回路。
2. **临时类型模块不暴露持久化入口**：上述 5 类所在模块禁止导出
   `save_checkpoint / persist / dump_to_state / to_checkpoint`。
3. **`emit_display_event` / `runtime_observer.log_*` 不修改 state**：调用前后
   `state.task.__dict__` / `state.conversation.messages` / `state.memory.__dict__`
   字段值（按 dict 等价比较）保持不变。
4. **`apply_user_replied_transition` 对 messages append-only**：见 M1 invariant。
5. **`_project_to_api` 是纯投影**：见 M1 invariant。
6. **`append_control_event` / `append_tool_result` 是 messages 唯一允许的写入
   入口**（除模型直接 append assistant 消息外）：见 conversation_events.py
   的边界注释。

## 4. 边界相邻概念辨析

- **DisplayEvent vs RuntimeEvent**：DisplayEvent 是「TUI/CLI 可渲染的最小
  payload」，RuntimeEvent 是「Runtime 输出通道的统一信封」。当前 RuntimeEvent
  可携带文本（`assistant.delta`）、可携带 DisplayEvent（`display.event`）、
  可携带元数据（`tool.requested`）。两者都不能进 checkpoint。
- **RuntimeEvent vs runtime_observer**：RuntimeEvent 是面向用户的输出投影；
  runtime_observer 是面向开发者的观测日志（`agent_log.jsonl` + 可选 debug
  stdout）。**不要为了让 UI 看到一条信息，就在 observer 上加渲染逻辑**；
  反之也不要把 observer 的 debug 字段塞进 RuntimeEvent payload。
- **InputIntent vs InputResolution**：InputIntent 是「这次 user 输入想做什么」
  的最初分类（normal_message / confirmation / cancel / answer 等）；
  InputResolution 是「在当前状态下如何处理这次输入」的二次解析（仅
  `awaiting_user_input + USER_REPLIED` 路径）。
- **conversation.messages vs `_project_to_api` 输出**：前者是 Runtime 内部
  append-only 事件流，包含 `step_input` / 控制事件等内部 user message；
  后者是「投影 + 重排 + 合并 + 清理元工具 tool_use」之后的 Anthropic API
  合规 messages。**禁止用 _project_to_api 的输出回写 messages**。

## 5. 当前已知历史旁路（M2 不动）

- `agent/session.py::_replay_awaiting_prompt` resume 时走裸 print 重放
  awaiting prompt（plan / step / pending input）。归属 M2/M7 收口区间，
  M2 文档化但不改动。
- `agent/core.py` 中部分错误 / 兜底分支仍走 `print(...)`（控制台用户可见
  文案）。M2 不批量替换为 RuntimeEvent；只在文档里登记，避免 PR 范围爆炸。
- 这些旁路保留期间，**新增**用户可见输出必须走 RuntimeEvent /
  DisplayEvent，不允许新增 print 旁路。M2 的不变量测试通过限定「禁止
  导出持久化入口」抓回归，但不强制扫描 print 调用。

## 6. M2 收口边界 / 非目标

**M2 做**：
- 本文件（事件边界 spec）。
- `tests/test_runtime_event_boundaries.py`：6 条架构边界 invariant。
- 不引入新 RuntimeEvent kind / DisplayEvent kind。
- 不批量替换 print 旁路。

**M2 不做**：
- 不收口 `_replay_awaiting_prompt`（→ M7）。
- 不改 RuntimeEvent dataclass schema。
- 不重写 `runtime_observer`。
- 不实现新 TUI / Textual backend / observer GUI。
- 不动 LLM Processing 已收口能力。

---

后续 milestone：M3 Checkpoint 恢复语义 → 见
`docs/CHECKPOINT_RESUME_SEMANTICS.md`。

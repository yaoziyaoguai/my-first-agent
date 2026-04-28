# Checkpoint Resume Semantics (v0.2 M3)

> **本文目的**：v0.2 M3 把 `memory/checkpoint.json` 的「保存什么 / 恢复什么 /
> 损坏怎么办 / resume 提示和 CLI 输出契约的关系」写成显式 spec，并通过
> `tests/test_checkpoint_resume_semantics.py` 提供最小回归保护。
>
> **核心边界**：M3 不引入 schema 版本号、不做迁移框架、不收口
> `session._replay_awaiting_prompt` 的 print 旁路（→ M7）、不重写 checkpoint
> 序列化策略、不动 LLM Processing 已收口能力。M3 做的是「把恢复语义讲清楚 +
> 用测试钉住已有正确行为 + 顺手把 load 路径硬化为字段白名单」。

---

## 1. checkpoint 文件 schema（事实记录）

文件路径：`memory/checkpoint.json`（仓库根，**不入 git**，被 `.gitignore` 覆盖）。

顶层 key 集合（`tests/test_runtime_state_machine_invariants.py` 已 assert）：

```
{
  "meta": {"session_id", "created_at", "interrupted_at"},
  "task": { ...TaskState 已声明字段子集... },
  "memory": { ...MemoryState 已声明字段子集... },
  "conversation": {"messages": [...]}   // tool_result 内容会按 MAX_RESULT_LENGTH 截断
}
```

**版本策略**：v0.2 M3 不引入 schema 版本号。理由：
- 当前 schema 仅由 dataclass 字段集合决定，新增字段时旧 checkpoint 走
  「dataclass 默认值」自然兜底。
- 删除字段或语义破坏性变更属于 M3 范围之外，未来必须时再设计版本字段。
- 引入版本号本身需要迁移框架、版本枚举和 fallback 策略，与 v0.2 「人工
  测试前的稳定性」目标偏离。

## 2. 持久 vs 临时

下表是 M1 spec 的延伸视角，专门从「resume」角度看：

| 类别 | 字段 | 是否 resume | 说明 |
|---|---|---|---|
| 任务持久 | `TaskState.*`（dataclass 全部声明字段） | ✅ | `load_checkpoint_to_state` 通过白名单 setattr |
| 记忆持久 | `MemoryState.*`（dataclass 全部声明字段） | ✅ | 同上 |
| 对话历史 | `ConversationState.messages` | ✅ | 按 append-only 事件流恢复 |
| 会话分析 | `ConversationState.tool_traces` | ❌ | 不进 checkpoint，恢复后保持空 list |
| 运行时配置 | `RuntimeState.*` | ❌ | 启动时由进程重建，不属于恢复语义 |
| UI / 输入临时类型 | `InputIntent / InputResolution / TransitionResult / RuntimeEvent / DisplayEvent` | ❌ | 不进 checkpoint，也不允许通过 task 字段塞进 |

## 3. status 与 resume 行为表

`agent/core.py::chat` 在每个新 user input 进入 runtime 前会用
`task_status_requires_plan(task)` 自检；recovery 时若发现「需要 plan 的状态
+ current_plan 缺失」会 reset。下表把 status × pending 字段 → resume 行为列
清楚。

| status | resume 后立即可继续？ | 关键约束 | reset 触发条件 |
|---|---|---|---|
| `idle` | ✅ | 无 | — |
| `planning` | ⚠️ 视情况 | planning 是短瞬态；resume 后下一次 user input 会触发新一轮 planning | 无 plan 时正常 |
| `running` | ✅ | 需要 `current_plan`（多步任务）；单步无 plan 任务也允许 | `current_plan is None` 视为损坏 → reset |
| `awaiting_plan_confirmation` | ✅ | 必须有 `current_plan`，UI 通过 `_replay_awaiting_prompt` 重显计划 | `current_plan is None` → reset |
| `awaiting_step_confirmation` | ✅ | 必须有 `current_plan` | 同上 |
| `awaiting_user_input` (collect_input/clarify) | ✅ | `pending_user_input_request is None`，必须有 `current_plan` | `current_plan is None` → reset |
| `awaiting_user_input` (request_user_input) | ✅ | `pending_user_input_request` 非空且含 `awaiting_kind` | 不被 plan invariant reset；UI 用 pending 内容重放 question |
| `awaiting_tool_confirmation` | ✅ | `pending_tool` 非空 | 不被 plan invariant reset |
| `awaiting_feedback_intent` | ✅ | `pending_user_input_request` 非空，记录 `origin_status / pending_text` | 同上 |
| `done / failed / cancelled` | ✅ | 终止态；resume 不要求 plan | 无 |

「立即可继续」= load_checkpoint_to_state 完成后，状态机能在不丢上下文的前提
下接收下一次 user input；UI prompt 可由 `_replay_awaiting_prompt` 提示用户
缺失的回答（M7 之前仍走 print 旁路）。

## 4. 损坏 / 兼容场景

### 4.1 文件不存在
- `load_checkpoint()` 返回 `None`；`load_checkpoint_to_state` 返回 `False`。
- 不抛异常，启动按全新 session 处理。

### 4.2 JSON 无法解析
- `load_checkpoint()` 内部 try 捕获后返回 `None`；进程不 crash。
- agent 启动按无 checkpoint 处理。

### 4.3 缺字段（旧版本 checkpoint）
- 缺失的 dataclass 字段保留默认值（dataclass 初始化时已设定）。
- 已覆盖：`tests/test_checkpoint_roundtrip.py::test_load_old_checkpoint_without_new_fields_does_not_crash`。

### 4.4 多余字段（未来版本 / 调试注入）
- M3 在 `_filter_to_declared_fields` 把 task / memory 的 setattr 收紧到
  dataclass 声明字段白名单，未知 key 直接丢弃。
- 防止「有人通过手改 checkpoint 把 RuntimeEvent / InputIntent 塞进 task
  field 名下」从而绕过 M1 / M2 边界。
- 已覆盖：`tests/test_checkpoint_resume_semantics.py::test_unknown_task_keys_are_dropped_on_resume`。

### 4.5 JSON 内容看起来合法但语义损坏
- 例：`status="awaiting_plan_confirmation"` 但 `current_plan=None`。
- `load_checkpoint_to_state` 仍然返回 `True`（不修复语义），下一次
  `agent/core.py::chat` 进入主循环时 `task_status_requires_plan` invariant
  会检测并 reset，并在 stdout 打印「检测到不一致状态」（已覆盖：
  `tests/test_state_invariants.py::test_core_resets_requires_plan_status_when_plan_missing`）。
- 这条「先恢复，主循环再自愈」的策略避免 load 路径承担状态机修复责任。

## 5. resume prompt 与 CLI/TUI 输出契约

- 当前 `agent/session.py::_replay_awaiting_prompt` 在恢复后通过 `print(...)`
  直接打印 plan / step / pending input prompt。这是 v0.1 遗留的输出旁路，
  v0.2 M2 已在 `docs/RUNTIME_EVENT_BOUNDARIES.md` §5 登记，**M3 不动**。
- M3 显式契约：resume 后 UI 必须能从 `task.status / task.current_plan /
  task.pending_user_input_request / task.pending_tool` 这 4 个字段重建
  prompt；任何依赖「事件流回放」的 resume 路径都属于跨界设计。
- 普通 CLI 不允许把 `meta.session_id / interrupted_at` 等 checkpoint
  内部值泄漏到用户视图（M3 测试有针对性 assert）。

## 6. tool_use ↔ tool_result 配对完整性

`_truncate_messages_for_checkpoint` 只截断 tool_result 的 content 字符串，
不会拆开 tool_use ↔ tool_result 配对结构。M3 测试 roundtrip 后断言：

- `assistant.content` 中每个 `tool_use.id` 都能在紧随其后的 user message 的
  `tool_result.tool_use_id` 中找到（Anthropic 协议硬要求）。
- 大 tool_result 被截断不破坏 tool_use_id 配对。

## 7. M3 收口边界 / 非目标

**M3 做**：
- 本文件（resume 语义 spec）。
- `tests/test_checkpoint_resume_semantics.py`：覆盖 §3 / §4 / §6 关键场景。
- `agent/checkpoint.py::load_checkpoint_to_state` 收紧到字段白名单
  （`_filter_to_declared_fields`），防止未知 key 污染 state。

**M3 不做**：
- 不引入 schema 版本号 / 迁移框架。
- 不收口 `_replay_awaiting_prompt` print 旁路（→ M7）。
- 不改 checkpoint 序列化策略。
- 不引入 cancel_token / generation lifecycle（→ M8）。
- 不动 LLM Processing 已收口能力。

---

## 8. v0.2 进度（M1 / M2 / M3 完成后）

- M1 状态机整理 ✅ → `docs/RUNTIME_STATE_MACHINE.md`
- M2 事件边界治理 ✅ → `docs/RUNTIME_EVENT_BOUNDARIES.md`
- M3 checkpoint 恢复语义 ✅ → 本文件
- M4 错误恢复 / loop guard / no-progress（待开始）
- M5+ 工具体系 / 安全权限 / TUI / cancel（待开始）

人工测试前的最小风险面：M1+M2+M3 提供了**可读 spec + 不变量测试 + load
路径硬化**。剩余建议在做 M4 之前由你决定是否人工 smoke 一下：
- 启动 agent，做一段 task，主动 Ctrl+C，重启确认 resume 提示 + 后续输入
  不丢上下文。
- 主动手改 `memory/checkpoint.json` 加一个未知 key，确认重启不 crash 且
  state 干净。

# Runtime Error Recovery / Loop Guard / No-Progress (v0.2 M4)

> **本文目的**：v0.2 M4 把 Runtime 散落在 `core.py` / `response_handlers.py`
> 中的「错误恢复 / loop guard / no-progress 兜底」机制写成显式 spec，并用
> `tests/test_runtime_error_recovery.py` 提供最小回归保护。
>
> **核心边界**：M4 不重写主循环、不引入新计数维度、不调整阈值、不收口
> `print(...)` 旁路（→ M7）、不动 LLM Processing。M4 做的是「把现有兜底
> 网讲清楚 + 测试钉住关键不变量 + 顺手保证 fallback 不破坏 messages /
> checkpoint 边界」。

---

## 1. 阈值与字段一览

| 阈值 | 位置 | 字段 / 触发点 | 触发后行为 |
|---|---|---|---|
| `MAX_LOOP_ITERATIONS = 50` | `agent/core.py` | `task.loop_iterations` | clear_checkpoint + reset_task + 用户文案 |
| `MAX_CONTINUE_ATTEMPTS = 3` | `config.py` | `task.consecutive_max_tokens` | 返回「连续 max_tokens 已停止」文案，不 reset |
| `MAX_TOOL_CALLS_PER_TURN = 50` | `agent/response_handlers.py` | `task.tool_call_count` | `_fill_placeholder_results` + clear_checkpoint + reset_task |
| `MAX_REPEATED_TOOL_INPUTS = 3` | `agent/response_handlers.py` | `task.tool_execution_log` (executed) | `_fill_placeholder_results` + clear_checkpoint + reset_task |
| no_progress 阈值 = 2 | `agent/model_output_resolution.py` | `task.consecutive_end_turn_without_progress` | 写 `pending_user_input_request{awaiting_kind="no_progress"}`，切 `awaiting_user_input` |
| 同输入失败拒绝 | `agent/response_handlers.py` | `tool_execution_log` (failed) | `_fill_placeholder_results` 拒绝再次执行，**不**reset |

## 2. 计数清零规则

| 字段 | 何时清零 |
|---|---|
| `consecutive_max_tokens` | end_turn 成功 / 任何 tool_use 调用 |
| `consecutive_end_turn_without_progress` | 任何 tool_use 调用（业务工具或元工具均算「动起来了」） |
| `loop_iterations` | `reset_task()`（任务真正终止时） |
| `tool_call_count` | `reset_task()` |
| `tool_execution_log` | `reset_task()` |

> **设计原则**：「连续 X」类计数器在「有进展信号」时立即清零，避免一次小
> 抖动后永远拒绝模型。`loop_iterations` / `tool_call_count` 是「单任务上限」
> 不清零，靠 reset_task 兜底。

## 3. 持久化与 resume 行为

所有 loop guard 字段（`loop_iterations / consecutive_max_tokens /
consecutive_end_turn_without_progress / tool_call_count / tool_execution_log`）
都是 `TaskState` 持久字段，会进 checkpoint。

**显式选择**：resume 后 **保留** 已累积的计数，不归零。理由：
- 防止用户通过「Ctrl+C 重启」绕过 loop guard 阈值。
- guard 阈值表示「这个任务已经走到很危险的边界」，重启不应让 Runtime 假装
  忘记。
- `reset_task()`（任务终止）才是合法的归零入口。

## 4. 兜底路径与 messages / checkpoint 边界

### 4.1 `_fill_placeholder_results`（`response_handlers.py`）

当 loop guard 触发后，必须给所有未配对的 `tool_use` 写 `tool_result`
placeholder（短安全文案 `[系统] {reason}。`），原因：

- Anthropic 协议硬要求：每个 `assistant.tool_use.id` 必须有匹配的
  `user.tool_result.tool_use_id`。
- 若不补 placeholder，下次 `_project_to_api` 会构造非法 messages，模型直接
  拒绝或陷入死循环。
- placeholder content 是固定短文案，**不**包含工具入参 / 异常 stack /
  内部计数 / API key / 任何 secret。

### 4.2 `request_user_input` 与 no-progress 的关系

`pending_user_input_request.awaiting_kind` 区分三种来源：

| awaiting_kind | 触发 | 是否 loop guard 兜底 |
|---|---|---|
| `request_user_input` | 模型主动调用元工具 | ❌ 正常协议路径 |
| `fallback_question` | 模型用普通文本求助（启发式判定） | ⚠️ 协议外，但合理 |
| `no_progress` | runtime 观察到连续 2 次 end_turn 无进展 | ✅ 兜底，强制中断 |

**关键不变量**：模型调用 `request_user_input` 元工具不会被误判为
no_progress，因为 `consecutive_end_turn_without_progress` 在该工具的
`tool_use` 出现时已被清零（`is_meta_tool` 也算「动起来了」）。

### 4.3 工具失败不污染 task / checkpoint

工具执行失败的错误信息：
- 走 `tool_executor` 写入 `messages` 中的 `tool_result.content`（用户和模型可见）。
- **不**写入 `task.last_error`（last_error 是 Runtime 错误，不是工具错误）。
- **不**写入 `tool_execution_log` 的 result 字段超过截断长度（避免大 stack 进 checkpoint）。
- 工具失败不更改 status（继续 running，让模型决定下一步）。

## 5. 用户可见输出

各兜底路径的用户可见文案统一短信息，不暴露内部计数 / 阈值 / API 字段：

| 触发 | 文案 |
|---|---|
| `MAX_LOOP_ITERATIONS` | `[系统] 循环次数超过上限 50，强制停止。` + `对话循环次数过多，请简化任务或分步执行。` |
| `MAX_CONTINUE_ATTEMPTS` | `模型连续多次达到最大输出长度，任务已停止。请缩小任务范围后重试。` |
| `MAX_TOOL_CALLS_PER_TURN` | `工具调用次数过多，请简化任务或分步执行。` |
| `MAX_REPEATED_TOOL_INPUTS` | `检测到重复工具调用过多，任务已停止。请调整目标或换一种信息来源。` |
| no_progress | `pending_user_input_request.question` 注入「[模型 end_turn 但未声明步骤完成；请你介入]」prompt |

## 6. 当前已知历史旁路（M4 不动）

- `core.py::main_loop` 的 `print("[系统] 循环次数超过上限...")` 仍是 stdout
  print 旁路；M2 已登记，M4 不批量替换为 RuntimeEvent。
- `response_handlers.py` 中部分错误文案仍通过 return string + main loop
  print 投影；属于 v0.1 输出契约，M4 保持现状。

## 7. M4 收口边界 / 非目标

**M4 做**：
- 本文件（错误恢复 spec）。
- `tests/test_runtime_error_recovery.py`：覆盖阈值常量、计数清零规则、
  持久化/resume、placeholder 配对完整性、no_progress vs request_user_input
  分离、工具失败不污染 checkpoint。

**M4 不做**：
- 不调整任何阈值（任何调整都需先做 LLM 真实跑验证）。
- 不引入新计数维度（如「连续 tool failure」「连续 model error」）。
- 不重写 `_fill_placeholder_results` 或 `handle_*_response`。
- 不收口 print 旁路。
- 不改 LLM Processing。

---

## 8. v0.2 进度（M4 完成后）

- M1 状态机整理 ✅
- M2 事件边界治理 ✅
- M3 checkpoint 恢复语义 ✅
- M4 错误恢复 / loop guard / no-progress ✅
- M5 工具体系优化（preflight 文档已就位 → `docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md`）
- M6 基础安全权限（同上）
- M7 基础 TUI / CLI UX
- M8 generation cancel 生命周期

人工测试前的最小风险面：M1+M2+M3+M4 提供了**状态机 / 事件边界 / 恢复语义 /
错误兜底** 4 份 spec + 不变量测试 + 1 处 load 路径硬化。Runtime 已接近
release candidate，建议在做 M5/M6 实现前先人工 smoke 一遍。

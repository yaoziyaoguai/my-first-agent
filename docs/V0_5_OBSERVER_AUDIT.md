# v0.5 Observer Evidence Chain Audit

> **审计文档（不是架构愿景文档）**：本文只读盘点当前 RuntimeEvent / DisplayEvent /
> observer / logging / callback / print / checkpoint 的真实证据链，落到具体文件、
> 函数、事件、状态字段、测试。**本轮不写代码、不接入 runtime、不实现 observer、
> 不进入 TUI**。如果文档里出现"提升可观测性 / 增强稳定性 / 优化架构 / 改善用户体验"
> 之类空话，请视为审计失败。
>
> 审计基线：commit `1016738` (v0.5 第三小步，sessions/runs inventory)，origin/main
> 同步、ahead/behind = 0/0、v0.4.0 tag 不变、未 tag v0.5。

## 1. Current Event Surfaces

当前已经存在的"事件相关"模块共 **4 个 + 1 个 legacy logger**，全部已落盘：

| 模块 | 行数 | 主要导出 | 默认输出 |
|---|---:|---|---|
| `agent/runtime_events.py` | 572 | `RuntimeEventKind` (Enum, 8 values), `ToolResultTransitionKind`, `ModelOutputKind`, `PlanConfirmationKind`, `StepConfirmationKind`, `ToolConfirmationKind`, `FeedbackIntentKind`, `TransitionResult` (frozen dataclass), `command_event_transition()`, `classify_model_output()`, 5 个 `*_confirmation_transition()` | 无副作用，纯函数 + 数据类 |
| `agent/display_events.py` | 395 | `DisplayEvent` (frozen dataclass), `RuntimeEvent` (frozen dataclass), `assistant_delta()`, `tool_requested()`, `plan_confirmation_requested()`, `user_input_requested()`, `feedback_intent_requested()`, `tool_result_visible()`, `build_tool_status_event()`, `render_runtime_event_for_cli()`, **`emit_display_event()`**, `mask_user_visible_secrets()` | 经 `emit_display_event` 后由 callback 决定（TUI / CLI print / drop） |
| `agent/runtime_observer.py` | 205 | `log_event()`, `log_resolution()`, `log_transition()`, `log_actions()`, `_persist_observer_event()` | 结构化 JSONL → `agent_log.jsonl`；MY_FIRST_AGENT_DEBUG=1 时另写 terminal 短日志 |
| `agent/conversation_events.py` | 143 | `append_control_event()`, `append_tool_result()`, `has_tool_result()` | 写 `state.conversation.messages`（durable，进 checkpoint） |
| `agent/logger.py` (legacy) | n/a | `log_event(event_type, data)` 旧两参数签名 | JSONL（与 runtime_observer 共享 `agent_log.jsonl` 落盘路径） |

### 1.1 命名容易混淆的真实问题

1. **`RuntimeEventKind` (enum) vs `RuntimeEvent` (dataclass)**：两者同前缀、不同义。
   - `runtime_events.RuntimeEventKind` 表示"判定层枚举"，例如 `USER_INPUT / MODEL_OUTPUT / TOOL_RESULT / POLICY_DENIAL / USER_REJECTION / CHECKPOINT_RESUME / HEALTH_COMMAND / LOGS_COMMAND`，被 `command_event_transition()` 和 5 个 `*_confirmation_transition()` 消费。
   - `display_events.RuntimeEvent` 表示"UI projection 包"，是 `assistant_delta` / `tool_requested` / `plan_confirmation_requested` / `user_input_requested` 等的 frozen dataclass 容器，里面可能内嵌 `DisplayEvent` 也可能只是文本。
   - 两者完全不互相 import，也不是父子关系。**新人读 core.py 第 53 行 `from agent.runtime_observer import log_event as log_runtime_event` 的时候，必须脑补三件事：runtime_observer ≠ runtime_events、log_runtime_event ≠ runtime_events.RuntimeEventKind、传入的 event_type 字符串与 RuntimeEventKind 的 enum 值无强校验关联**。

2. **两套 `log_event`**：`agent/logger.py:8` (旧两参数 `event_type, data`) 与 `agent/runtime_observer.py:114` (新关键字参数 `*, event_source, event_payload, event_channel`)。
   - `planner.py` 用的是旧的 `from agent.logger import log_event`（5 处）。
   - `response_handlers.py` 用的是新的 `from agent.runtime_observer import log_event`（14 处）。
   - `checkpoint.py:145` 用的是旧的（lazy import in try）。
   - `core.py:53` 用 `as log_runtime_event` 别名给新的（8 处）。
   - **同名不同签名**，grep 结果会混在一起，文档化必须区分。

### 1.2 已存在的 observer 概念

`agent/runtime_observer.py` 已经是 observer：声明"不修改 state / 不写 checkpoint /
不写 messages / 不执行工具"，结构化事件强制落 `agent_log.jsonl`，terminal 短日志靠
`MY_FIRST_AGENT_DEBUG` 开关。**所以 v0.5 第四小步问的不是"是否有 observer"，而是
"observer 覆盖面是否足够 + 是否被一致地接入"**。

## 2. RuntimeEvent vs DisplayEvent Boundary

| Surface | File | Owns | Does Not Own | Current Risk |
|---|---|---|---|---|
| `RuntimeEventKind` | `agent/runtime_events.py:26` | 8 个判定层枚举值；被 `command_event_transition()` 等消费 | 不持有 payload；不与 `display_events.RuntimeEvent` 同义 | 与 `display_events.RuntimeEvent` 名字撞车，新人误以为同一概念 |
| `RuntimeEvent` (dataclass) | `agent/display_events.py` | UI projection payload（assistant_delta/tool 生命周期/confirmation request）的 frozen 容器 | 不进 checkpoint；不进 messages；不是状态机 | 与上面 enum 重名；`event_type` 字段是字符串非枚举，与 `RuntimeEventKind` 无强校验绑定 |
| `TransitionResult` | `agent/runtime_events.py` (frozen dataclass) | 把"判定结果"打包成 (intent, payload) 二元，被 5 个 confirmation transition 函数返回 | 不持有 callback；不写日志；不投递 UI | 当前未与 observer 联动——transition 落地不写 `log_transition` |
| `DisplayEvent` | `agent/display_events.py:34` | 用户可见输出的 frozen payload（kind/text/metadata） | 不进 checkpoint；不进 messages；不是状态机 | sink 完全靠 `emit_display_event` 的 callback 转发，未注入则只走 print |
| `on_runtime_event` callback | `core.py:318-355` `_emit_runtime_event` | 兼容三态：(1) 新 sink、(2) 旧 `on_output_chunk`、(3) 无 sink fallback print | 不写 observer JSONL；不写 messages；不写 checkpoint | sink 缺失时 silent fallback 到 `print`，不可被 TUI 捕获 |
| `print()` (raw) | `agent/core.py` 23 处 | 大部分是 fallback 或 protocol dump | 不被 TUI 捕获；不进 observer JSONL | L306/L670/L769 在运行时路径上、走 user-visible 输出（详见 §3） |
| `runtime_observer.log_event` | `agent/runtime_observer.py:114` | 写 `agent_log.jsonl`；MY_FIRST_AGENT_DEBUG=1 时打印 terminal | 不改 state/messages/checkpoint；不投递 UI | 接入面不均衡：response_handlers (14) / core.py (8) / planner (5)，**confirm_handlers / tool_executor 0** |
| `logger.log_event` (legacy) | `agent/logger.py:8` | 旧两参数签名 JSONL | 同上 | 与新 `runtime_observer.log_event` 同名不同签名，依然被 `planner.py` / `checkpoint.py` 使用 |
| `checkpoint` | `agent/checkpoint.py:109-122` | 持久化 `meta + task + memory + conversation.messages`；调用 `log_event("checkpoint_saved", ...)` | 不持久化 RuntimeEvent / DisplayEvent / LoopContext / ConfirmationContext | resume 后无法重建 UI 流；只能从 messages + task.status 推断 |
| `sessions/runs inventory` | `agent/local_artifacts.py` (v0.5 第三小步) | 只读 metadata 盘点（DRY RUN） | 不读取文件正文；不删除 / 不移动 / 不压缩；不接入 runtime | 当前与 observer 无联动——观测面看不到 inventory 触发记录 |

## 3. core.py Print / Callback Audit

`grep -nE '^\s*print\(' agent/core.py` → **23 处**。逐条分类：

### 3.1 Runtime path · user-facing · 应改 DisplayEvent + log_event（3 处）

| 行号 | 内容 | 触发条件 | 走哪条链路 | 风险 |
|---:|---|---|---|---|
| 306 | `print(f"[系统] 检测到不一致状态…已重置。")` | `task_status_requires_plan(task) and current_plan is None` | 仅 stdout（无 callback） | TUI 不可见；`reset_task()` 之后无 observer 记录"重置发生过" |
| 670 | `print(f"\n[系统] 循环次数超过上限 {loop_ctx.max_loop_iterations}，强制停止。")` | `loop_iterations > max_loop_iterations` | stdout + 紧邻的 `log_runtime_event("loop.guard_triggered", ...)` | observer JSONL 已记录；但 print 本身不进 RuntimeEvent，TUI 不可见 |
| 769 | `print(f"[系统] 未知的 stop_reason: {response.stop_reason}")` | 未知 stop_reason | stdout + 紧邻 `log_runtime_event("loop.stop", reason="unknown_stop_reason")` | observer 已记录；print 本身不进 RuntimeEvent；注释 L766-768 明确不能用 `[DEBUG]` 前缀（会被 main.DEBUG_OUTPUT_PREFIXES 兜底过滤） |

**这 3 条的真实 bug**：用户在 TUI 模式下永远看不到这些 `[系统]` 提示。当循环上限被触发或状态被重置，TUI 屏幕只会突然结束，没有任何文字解释为什么。

### 3.2 Display sink fallback · 由 `_emit_runtime_event` 内部 fallback 到 print（3 处）

| 行号 | 内容 | 守卫条件 |
|---:|---|---|
| 338 | `print(render_runtime_event_for_cli(event), end="", flush=True)` | `on_output_chunk is None` (L335) |
| 345 | `print(f"\n{render_runtime_event_for_cli(event)}", flush=True)` | `on_display_event is None` (L342) |
| 350 | `print(f"\n{rendered}", flush=True)` | 通用 fallback (L348-350) |

**评估**：这 3 条是 `_emit_runtime_event` 在"无任何 callback 注入"场景的 simple CLI fallback，docstring (L319-328) 已明确这是"集中兼容层、不能扩大成新协议、不能承载 checkpoint/runtime_observer/messages"。**保持原样**，但需要测试钉死"sink 注入时这 3 条不被触发"。

### 3.3 Runtime path · 输出格式控制（1 处）

| 行号 | 内容 | 评估 |
|---:|---|---|
| 832 | `print()`（在 `_call_model` 末尾，`if turn_state.print_assistant_newline:` 守卫下） | 仅追加换行，无信息内容；与 streaming 输出格式相关。**保持原样**，但 v0.5 后续可考虑把 newline 也包成 RuntimeEvent metadata 让 TUI 自己决定 |

### 3.4 Debug protocol dump · 双开关守卫（16 处）

L922-963 是 `_debug_print_request` / `_debug_print_response` 两个调试函数体，**双 guard**：
1. 函数体首行 `if not _protocol_dump_enabled(): return`（L920, L936）
2. `_protocol_dump_enabled()` 同时要求 `DEBUG_PROTOCOL = False`（L858 模块常量，**当前硬编码 False**）AND 环境变量 `MY_FIRST_AGENT_PROTOCOL_DUMP` 真值（L869-877）

**评估**：当前 `DEBUG_PROTOCOL = False`，所以**这 16 条 print 在任何普通 CLI / TUI 路径下都不会触发**。注释 L858（"任何人取消注释，污染就会立刻回归"）已说明这是有意保留的诊断块。**保持原样**。可以新增测试断言"DEBUG_PROTOCOL 必须为 False"防回归。

### 3.5 总结表

| 分类 | 数量 | 处理建议 |
|---|---:|---|
| Runtime path · user-facing · 应改 DisplayEvent | 3 | §8 Gap-1（v0.5 后续 slice） |
| Display sink fallback · 已是设计意图 | 3 | 保持；新增 sink-injected 时不触发的测试 |
| Runtime path · 格式控制 | 1 | 保持；可选未来包成 metadata |
| Debug protocol dump · 双开关守卫 | 16 | 保持；新增 DEBUG_PROTOCOL=False 防回归测试 |

## 4. Confirmation Evidence Chain

`agent/confirm_handlers.py` 共 5 个 confirmation handler。`grep -nE 'log_event|emit_display_event' agent/confirm_handlers.py` → **`emit_display_event` 1 处（L540 tool_status）、`log_event` 0 处**。

| Confirmation | 入口函数 | 使用的 context | 产生的 transition intent | DisplayEvent | log_event | 写 checkpoint | 缺口 |
|---|---|---|---|---|---|---|---|
| Plan | `handle_plan_confirmation` | `ConfirmationContext` | `PlanConfirmationKind.{PLAN_ACCEPTED, PLAN_REJECTED}` → `plan_confirmation_transition()` | ❌ 无（决策结果未投递 UI 事件） | ❌ 无 | ✅（保存通过 chat() 流程） | observer 无法回答"用户接受/拒绝了 plan" |
| Step | `handle_step_confirmation` | 同上 | `StepConfirmationKind.{STEP_ACCEPTED_CONTINUE, STEP_ACCEPTED_TASK_DONE, STEP_REJECTED}` | ❌ | ❌ | ✅ | observer 无法回答"用户在 step N 选择了什么" |
| Tool | `handle_tool_confirmation` | 同上 | `ToolConfirmationKind.{TOOL_ACCEPTED_SUCCESS, TOOL_ACCEPTED_FAILED, USER_REJECTION, POLICY_DENIAL}` | ✅ L540 `build_tool_status_event` (仅状态展示) | ❌ | ✅ | observer 无法回答"用户拒绝了哪个工具调用" |
| User input | `handle_user_input_step` | 同上 | （直接走 user input 处理，不走 transition_result） | ❌ | ❌ | ✅ | observer 无法回答"user_input request 在哪一步发出 / 何时被消费" |
| Feedback intent | `handle_feedback_intent_choice` | 同上 | `FeedbackIntentKind.{AS_FEEDBACK, AS_NEW_TASK, CANCELLED, AMBIGUOUS}` | ❌ | ❌ | ✅ | observer 无法回答"用户把当前消息当 feedback 还是 new task" |

**不变量（必须保持）**：
- handler 不直接 print 用户可见输出（已满足，0 处 print）
- handler 不直接改 state；只通过 `TransitionResult` 表达意图
- handler 不直接写 checkpoint（由 chat() 主循环负责）

**Gap 总结**：5 条 confirmation 链路里 **0 条**写 `log_event`，**4 条**完全无 DisplayEvent。
"用户做出了什么 confirmation 决策" 在 `agent_log.jsonl` 里**完全不可观测**——必须从
`state.task.status` + `pending_*` 字段间接推断，且推断只能在事件还未被消费的瞬间有效。

## 5. Tool Execution Evidence Chain

`agent/tool_executor.py` 中 `emit_display_event` 出现 **6 次**（L348/371/380/427/462/501），`log_event` **0 次**。

| 阶段 | 当前 evidence | 缺口 |
|---|---|---|
| tool requested（pre-execution） | `core.py:823` 在 streaming 阶段发 `tool_requested()` RuntimeEvent | ✅ 已覆盖 |
| tool success | `tool_executor.py:348/427/462/501` `emit_display_event(...)` 含状态字段 | observer JSONL 无对应事件——sessions/runs inventory 看不到工具调用次数 |
| tool failure | `tool_executor.py:371/380` `emit_display_event(... status=failed)` | 同上；失败原因不进结构化 JSONL |
| `tool_result` 写 messages | `agent/conversation_events.py:append_tool_result` | ✅ durable，进 checkpoint |
| `pending_tool` 清理 | 由 chat() / confirm_handlers 在 transition 后清理 | ✅ 由 `tests/test_v0_4_transition_boundaries.py` 覆盖 |
| checkpoint 写入 | `save_checkpoint` 写 `pending_tool_name` 到 `checkpoint_saved` JSONL | ✅ 已覆盖 |

**真实 evidence 缺口**：`agent_log.jsonl` 里搜 "tool" 看不到具体一次工具调用的成功/失败/输入摘要——只能看到 `checkpoint_saved` 里的 `pending_tool_name` 快照。

## 6. Checkpoint / Resume Evidence Chain

### 6.1 checkpoint 持久化什么（来源 `agent/checkpoint.py:109-122` `_build_checkpoint_from_state`）

```
meta:
  session_id          (state.memory.session_id)
  created_at          (existing or now)
  interrupted_at      (now)
task:                 _copy_state_dict(state.task)   # task 全字段
memory:               _copy_state_dict(state.memory) # memory 全字段
conversation:
  messages:           _truncate_messages_for_checkpoint(state.conversation.messages)
```

### 6.2 checkpoint 不持久化什么（实证）

- **RuntimeEvent 流**：`display_events.RuntimeEvent` 是 ephemeral UI projection，不进任何 dict
- **DisplayEvent 流**：同上
- **LoopContext**：`agent/loop_context.py` docstring 已声明"不持有 checkpoint 函数引用 / log_runtime_event"；本身是 frozen dataclass per chat() call，不持久化
- **ConfirmationContext**：构造在 `_build_confirmation_context()`，per-turn 临时对象，不持久化
- **Observer JSONL**：`agent_log.jsonl` 与 checkpoint 是**两条独立链路**，没有反向引用——给定一个 checkpoint，无法定位 JSONL 里"这个 checkpoint 对应的事件序列"

### 6.3 working_summary resume guard 当前覆盖

`tests/test_checkpoint_resume_semantics.py`（16 tests）+ commit `08e4229`（"guard working summary checkpoint roundtrip"）覆盖：working_summary 字段在 checkpoint roundtrip 中保留语义一致。

### 6.4 resume 后能解释什么

- ✅ `state.task.status` + `current_step_index` + `pending_tool` + `pending_user_input_request` 能说"上次停在什么 logical state"
- ✅ `conversation.messages` 能重建模型上下文
- ❌ 无法解释"上次最后投递的 RuntimeEvent 是什么"——TUI resume 没有"重放最后 N 个 UI 事件"能力
- ❌ 无法把 checkpoint 与 `agent_log.jsonl` 中具体 N 条 JSONL 行精确关联（只能按 session_id + 时间窗口大致匹配）

## 7. Local Artifacts as Evidence

| 模块 | 文件 | 当前能力 | 是否 observer 输入 | 不应该做什么 |
|---|---|---|---|---|
| `log_cleanup.collect_cleanup_candidates` | `agent/log_cleanup.py` | 目录级 count + total_bytes（dry-run） | ✅ 可作为 observer "agent_log.jsonl 体积是否超阈值"的输入 | 不读 JSONL 内容；不删除 |
| `log_cleanup` archive `--apply` | `agent/log_cleanup.py` | 已确认 archive 写 `.archive` 后置文件 | ❌ 不应作为 observer 输入（observer 读，不应触发 fs 写） | 不可与 observer 接到同一 callback 链 |
| `local_artifacts.inventory_artifact_directory` | `agent/local_artifacts.py` (v0.5 第三小步) | 文件级 metadata：count / total_bytes / mtime range / by_extension / by_prefix / sample_paths（DRY RUN） | ✅ 可作为 observer "sessions/runs 体积分布"的输入 | 不读文件正文；不删除 / 移动 / 压缩 / 写文件 |

**为什么 sessions/runs inventory 现在只读是正确的**：
1. sessions/runs 文件可能含未脱敏对话片段或 plan 草稿；任何"读正文"的 observer 都会带入隐私风险
2. inventory 已落地为 frozen dataclass + AST 守卫钉死禁止 13 个 mutating 方法；observer 接入它**只取 dataclass 字段**就够了，不需要二次读 fs
3. cleanup / rotation 一旦进入 observer 链，"observer 不改 state / 不写 fs" 的不变量立即破裂

## 8. Gaps and Invariants

| Gap ID | 文件 | 函数 | 当前风险 | 必须保持的不变量 | 最小下一步 | 需要的测试 |
|---|---|---|---|---|---|---|
| G1 | `agent/core.py` L306/L670/L769 | (chat 内 inline) | TUI 模式下 user-facing `[系统]` 提示完全不可见 | (a) 不能引入新 callback 协议；(b) observer JSONL 已记录的 (L670, L769) 不能丢失；(c) L306 "状态重置" 必须在 observer JSONL 留痕 | 把 3 处 print 包成 `DisplayEvent`，通过 `_emit_runtime_event` 投递；同步给 L306 加 `log_runtime_event("task.state_reset", ...)` | 1 条"sink 注入时这 3 条不会再 print"；1 条"L306 触发时 JSONL 含 task.state_reset" |
| G2 | `agent/confirm_handlers.py` 5 handler | `handle_*_confirmation` | 5 条 confirmation 决策**全部**不写 observer JSONL；用户决策不可追溯 | (a) handler 不能直接改 state；(b) handler 不能阻塞 transition；(c) `pending_*` 清理时机不变 | 在每个 handler 出口（return TransitionResult 之前）加 `log_runtime_event("confirmation.{plan/step/tool/user_input/feedback_intent}", event_payload={"intent": kind.value})` | 5 条"handler 调用一次后 JSONL 含对应 confirmation.* 事件"；5 条"handler 不改 state 字段集合"AST 守卫 |
| G3 | `agent/tool_executor.py` 6 处 emit_display_event | (tool execution flow) | 工具调用次数/成功率在 observer JSONL 中不可统计 | (a) 不能改 tool 执行结果语义；(b) 不能改 emit_display_event 的 6 处现有签名；(c) `pending_tool` 清理时机不变 | 在 6 处 `emit_display_event(...)` 后追加 `log_runtime_event("tool.{success/failure}", event_payload={"tool_name": name})` | 1 条"成功调用一次后 JSONL 含 tool.success"；1 条"失败调用后 JSONL 含 tool.failure"；1 条"event_payload 不含 tool_input 原文（防隐私泄漏）" |
| G4 | `agent/runtime_events.py` `RuntimeEventKind` vs `agent/display_events.RuntimeEvent` | 命名冲突 | 新人误读；grep 结果混淆 | 不能 rename 任何已 export 符号（v0.4 已 release） | 在两文件顶部 docstring 加交叉引用 + 明确"不是父子关系" | 1 条"两文件 docstring 互相引用"的 grep 测试 |
| G5 | `agent/logger.log_event` (旧两参数) vs `agent/runtime_observer.log_event` (新关键字) | 同名不同签名 | grep 混在一起；新增调用方不知用哪个 | 不能删 legacy `agent/logger.py:8`（planner / checkpoint 仍依赖） | 在 `agent/logger.py:8` docstring 标注 "legacy；新代码用 runtime_observer.log_event"；同步在 `runtime_observer.log_event` docstring 标注与 legacy 区别 | 1 条"legacy logger.log_event 的调用点不增加"AST 守卫（白名单 `planner.py` / `checkpoint.py`） |
| G6 | `agent/local_artifacts.py` ↔ observer | 当前无联动 | observer 看不到 inventory 触发记录 | 不能让 inventory 触发 fs 写；不能让 observer 二次读 sessions/runs 正文 | inventory CLI 出口处 `log_runtime_event("inventory.completed", event_payload={"kind": kind, "file_count": inv.file_count})` | 1 条"sessions inventory 跑完后 JSONL 含 inventory.completed"；1 条"event_payload 不含 sample_paths 原文" |
| G7 | `core.py` L858 `DEBUG_PROTOCOL = False` | 16 处 protocol dump print 的总开关 | 任何人误改为 True 立刻回归 v0.4 之前的 stdout 污染 | (a) 模块级常量必须 False；(b) 环境变量 `MY_FIRST_AGENT_PROTOCOL_DUMP` 真值才生效 | 加 1 条防回归断言 | 1 条"`agent.core.DEBUG_PROTOCOL is False`" |
| G8 | checkpoint ↔ observer JSONL | 无反向引用 | 给定 checkpoint 无法精确定位对应 JSONL 行 | 不能把 RuntimeEvent 流写进 checkpoint（durable state 不应膨胀） | （v0.6+ 评估）；本轮不动 | （延后） |

## 9. v0.5 Candidate Slices

| 候选 | 目标 | 会改哪些文件 | 是否改 runtime 行为 | 风险 | 需要的测试 | 推荐作为第五小步？ |
|---|---|---|---|---|---|---|
| **A** | 继续 audit-only：把本文档 §8 G1-G7 拆 issue / RELEASE_NOTES 草稿 | docs/ only | 否 | 0 | 无 | ❌ 已经够了——再 audit 是空转 |
| **B** 新增最小 ObserverEvent dataclass | 在 `agent/observer_events.py` 新建 frozen dataclass，**不接入** runtime | 1 lib + tests | 否 | 中——已有 4 个事件模块，第 5 个名字撞车风险高（G4） | dataclass 字段 / 不可变 / 与 RuntimeEventKind 命名冲突检查 | ❌ 先解 G4/G5 命名问题再考虑 |
| **C** 新增 StateSnapshot 只读 helper | 在 `agent/state_snapshot.py` 新建只读 frozen 快照导出函数，不接 TUI、不接 checkpoint | 1 lib + tests | 否 | 低 | dataclass / 与 checkpoint dict 字段集合一致 / 不可变 | 备选——但和 G6 inventory→observer 联动可以一起做 |
| **D** `_dispatch_pending_confirmation` extraction | 提取 chat() 中 5 个 if 串成的 confirmation 分发为 helper | core.py + tests | 是（重构、风险大）；需先写 characterization tests | **高** | 5×status × command path matrix 钉死 | ❌ 必须先写 characterization tests，本轮不做 |
| **E** checkpoint/resume 继续补语义测试 | tests/ only | 否 | 0 | 低 | working_summary 边界 / pending_user_input_request roundtrip | ❌ v0.4 已经强；收益低 |
| **F** local artifacts governance docs | docs/ only | 否 | 0 | 低 | 无 | 备选——与 A 性质重叠，建议合到 A 之后 |
| **G** **G1+G3 单 slice：把 core.py 3 条 user-facing print 改成 DisplayEvent，外加 tool_executor 6 处 emit 后接 log_runtime_event** | core.py / tool_executor.py / tests | **是**（运行时行为：TUI 用户开始能看到 [系统] 提示） | **中**——动了 core.py 用户可见输出路径 | (a) sink-injected 时不再 print；(b) JSONL 含新事件；(c) tool_input 不泄露 | 这是真正动用户感知的改动，需要严格 characterization | 候选 |
| **H** **G2 单 slice：5 个 confirmation handler 各加 1 行 `log_runtime_event`** | confirm_handlers.py + tests | 否（仅追加 observer 写入，不改 state/transition） | **低**——纯追加 observer 调用 | (a) handler 不改 state；(b) `pending_*` 清理时机不变；(c) event_payload 不含用户输入原文 | 5 条"handler 调用后 JSONL 含 confirmation.* 事件"；1 条"handler 不改 state 字段集合"AST 守卫 | ✅ **强烈推荐** |
| **I** **G4+G5+G7 docstring + 防回归 slice**：纯文档 + 1 行常量断言 | runtime_events.py / display_events.py / logger.py / runtime_observer.py docstring + 1 个新测试 | 否 | **极低** | DEBUG_PROTOCOL=False / 两 log_event 同名差异 / RuntimeEventKind vs RuntimeEvent | 1 条 docstring grep；1 条 `DEBUG_PROTOCOL is False`；1 条 legacy log_event 调用白名单 | ✅ 推荐——最低风险且解决最大新人陷阱 |

## 10. Recommendation

### 推荐 v0.5 第五小步：**候选 H（confirmation handler observer 接入）**

**为什么是 H 而不是其他**：

1. **不是 D（_dispatch_pending_confirmation extraction）**：D 是中-高风险结构性重构，必须先写 5×status 的 characterization tests（约 15-25 条）打底。本轮 plan.md 已记录"风险高于第三小步、需先写 characterization tests"——单 slice 既写 characterization tests 又做 extraction 会膨胀；H 完成后再做 D 才安全。

2. **不是 G（core.py print → DisplayEvent）**：G 直接动用户可见输出路径（chat() 内 L306/L670/L769）。在没有先把"confirmation observer 接入"做完之前，G 改完了 TUI 也只看到 3 条孤立 [系统] 提示，仍然不知道用户在 plan/step/tool 上做过什么决策——证据链顺序应该是先打通 confirmation observer（H），再让用户可见输出走 DisplayEvent（G）。

3. **不是 B（ObserverEvent dataclass）**：会立刻撞 G4 的命名冲突（4 个事件模块已经够混了），需要先做 I 解掉新人陷阱再考虑新 dataclass。

4. **不是 I（docstring 防回归）**：I 价值是治理性的，不解锁任何新能力；可以并入 H 的同一 commit 或后置。

5. **H 的具体边界**：
   - **第一处要改的文件**：`agent/confirm_handlers.py`（5 个 handler）
   - **第一条要写的测试**（在写代码之前）：`tests/test_confirmation_observer_evidence.py::test_plan_confirmation_writes_observer_event` —— 调用 `handle_plan_confirmation`，断言 `agent_log.jsonl` 新增一行 `event_type == "confirmation.plan"`、`event_payload["intent"]` ∈ `PlanConfirmationKind` 值集合
   - **明确不改的运行路径**：(a) `chat()` 主循环；(b) handler 返回的 `TransitionResult`；(c) `pending_tool` / `pending_user_input_request` 清理时机；(d) state 字段集合（用 AST 守卫钉死）；(e) checkpoint 内容
   - **为什么不是 TUI**：H 只追加 `log_runtime_event` 写 JSONL，不投递任何 DisplayEvent；TUI 屏幕一字不变
   - **为什么不是完整 observer**：H 不新增 dataclass、不新增模块、不重命名任何已 export 符号；只在已有的 5 个 handler 出口处追加 1 行调用——是"接入面均衡化"，不是"系统重构"
   - **为什么不是 _dispatch_pending_confirmation**：见上文第 1 点

### 第五小步建议 commit message 草稿
```
feat(observer): write confirmation observer events for 5 handlers
```

### 第五小步**之后**的两个候选（不本轮决定）
- **I docstring + 防回归 slice**：可以与 H 合 commit，也可以独立后置
- **G core.py print → DisplayEvent slice**：H 完成后才做，因为它依赖 H 的 observer 接入面对齐

---

**审计基线**：commit `1016738`，origin/main 同步，v0.4.0 tag 不变，未 tag v0.5。

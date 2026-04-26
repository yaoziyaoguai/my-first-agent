# my-first-agent 架构解读

> 目的：这篇文档不是 README，也不是 API reference。它是**帮你阅读现有代码**的路线图——告诉你每一块在整体里的位置、为什么这样设计、踩过哪些坑、哪里是难点、未来会扩展到哪里。读完之后你应该能自己翻代码不迷路。

---

## 0. TL;DR —— 一张图看懂整体

```
┌─────────────────────────────────────────────────────────────┐
│                       main.py                               │
│                  (输入循环 + 中断处理)                         │
└──────────────────────────┬──────────────────────────────────┘
                           │ user_input
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     agent/core.py                            │
│   chat(user_input)                                          │
│   ├── [分支1] awaiting_plan_confirmation  → confirm_handlers │
│   ├── [分支2] awaiting_step_confirmation  → confirm_handlers │
│   ├── [分支3] awaiting_tool_confirmation  → confirm_handlers │
│   ├── [分支4] compress_history (仅非 awaiting)               │
│   ├── [分支5] running 中收到反馈          → _run_main_loop   │
│   └── [分支6] 新任务 → _run_planning_phase → _run_main_loop │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼──────────────────┐
         ▼                 ▼                  ▼
  planner.py         _call_model          tool_executor
  (判单步/多步)    (流式调 Anthropic)    (真正跑工具)
                          │
                          │ stop_reason 分派
                          ▼
               response_handlers.py
               ├── end_turn
               ├── tool_use
               └── max_tokens

                          ↓ 共享数据
┌─────────────────────────────────────────────────────────────┐
│                     state.AgentState                         │
│  runtime │ conversation │ memory │ task                     │
│  (规则)    (对话原文)      (摘要)   (状态机)                │
└─────────────────────────────────────────────────────────────┘
                          ↓ 落盘
              checkpoint.py → memory/checkpoint.json
              logger.py    → agent_log.jsonl
              logger.py    → sessions/session_*.json
```

**五句话概括整个系统**：
1. `AgentState` 是**单一数据源**，四层结构（runtime/conversation/memory/task）按生命周期隔离。
2. `task.status` 是**一个显式状态机**，每次状态跳变必须 `save_checkpoint`，`awaiting_*` 状态代表"半开事务"，不能被压缩干扰。
3. Anthropic 的 `tool_use ↔ tool_result` 配对契约是**整个系统最脆弱的协议**，有 6 层防御保护它。
4. **工具有两类**：业务工具（read/write/shell 等）参与对话、占 context；**元工具**（`mark_step_complete` / `request_user_input`）是系统控制信号，**只写 log 不写 messages**——前者供状态机读分值判断步骤完成，后者把"执行期需要用户介入"变成可持久化、可恢复的 runtime 状态事件。
5. 模型可能不遵守协议——所以 runtime 层有**双层 loop guard**（启发式词表 + 连续 end_turn 计数）+ `MAX_LOOP_ITERATIONS` 终极安全阀，保证不会陷入死循环。

---

## 1. 分层架构

按**依赖传递从低到高**排序，下层不知道上层存在。

### 第一层 · 基础设施
| 文件 | 职责 |
|---|---|
| `config.py` | 唯一配置入口；环境变量、路径、尺寸阈值、system prompt 常量 |
| `agent/logger.py` | 结构化日志（`log_event` → `agent_log.jsonl`）+ session snapshot + `make_serializable` 序列化辅助 |

### 第二层 · 数据模型
| 文件 | 职责 |
|---|---|
| `agent/state.py` | **AgentState 四层容器**。所有跨模块状态的单一数据源 |
| `agent/plan_schema.py` | **Plan 数据契约**，Pydantic 模型，约束 planner 输出形态 |

### 第三层 · 持久化
| 文件 | 职责 |
|---|---|
| `agent/checkpoint.py` | `save/load/clear_checkpoint`。把 `task + memory + conversation` 存磁盘 |
| `agent/memory.py` | `compress_history` 压缩历史 + 辅助函数。包含 **tool pair 切点守卫** |

### 第四层 · 提示词与上下文
| 文件 | 职责 |
|---|---|
| `agent/prompt_builder.py` | 组装 `system prompt` = SYSTEM_PROMPT + memory_section + skills_section |
| `agent/context_builder.py` | **两种 messages 构造函数**：planner 用轻量版，执行用完整版 |

### 第五层 · 工具层
| 文件 | 职责 |
|---|---|
| `agent/tool_registry.py` | 装饰器 `@register_tool`；工具注册表；`needs_tool_confirmation` / `execute_tool` / `is_meta_tool` |
| `agent/tool_executor.py` | 执行单个 `tool_use` 块；三种确认模式处理；幂等日志写入；**元工具走特殊路径**（只写 log 不写 messages） |
| `agent/tools/meta.py` | **元工具注册处**：`mark_step_complete(completion_score, summary, outstanding)` |
| `agent/conversation_events.py` | 语义控制事件（`append_control_event`）+ `append_tool_result` + `has_tool_result` |

### 第六层 · 规划与推进
| 文件 | 职责 |
|---|---|
| `agent/planner.py` | `generate_plan`——用独立 LLM 调用判断单步/多步 |
| `agent/task_runtime.py` | 步骤完成检测 + 步骤推进（含 checkpoint 保存） |
| `agent/input_resolution.py` | 用户输入解析层。第一阶段只把 `awaiting_user_input + USER_REPLIED` 解析成 `collect_input_answer` / `runtime_user_input_answer`，只判断、不改 state、不调模型、不调工具 |
| `agent/transitions.py` | 轻量 transition action 层。第一阶段只执行 user replied transition 的 append / clear pending / advance / save 等动作，不是完整状态机框架 |

### 第七层 · 响应与确认分派
| 文件 | 职责 |
|---|---|
| `agent/response_handlers.py` | 按 `stop_reason` 分派：`end_turn / tool_use / max_tokens` |
| `agent/confirm_handlers.py` | 按 awaiting 状态分派：plan/step/tool 三种确认 |

### 第八层 · 会话生命周期
| 文件 | 职责 |
|---|---|
| `agent/session.py` | 启动初始化 + checkpoint 恢复 + 退出清理 + 中断处理 |

### 第九层 · 主循环
| 文件 | 职责 |
|---|---|
| `agent/core.py` | `chat()` 入口 + `_run_main_loop()` |
| `main.py` | 用户输入循环 + `quit` / `/reload_skills` / Ctrl+C 路由 |

---

## 2. 状态模型 —— `AgentState` 的四层结构

```python
AgentState
├── runtime     RuntimeState      # 本次进程的规则配置
├── conversation ConversationState # 真正喂给模型的原始对话
├── memory      MemoryState       # 跨会话持久化的记忆
└── task        TaskState         # 当前任务的执行态（状态机）
```

### 为什么这样分？

四层的划分**不是按"有多少字段"**，而是按**生命周期 + 持久化策略**：

| 层 | 生命周期 | 是否进 checkpoint | 是否参与压缩 |
|---|---|---|---|
| `runtime` | 进程级；每次启动重建 | **否** | 否 |
| `conversation` | 会话级；跨任务累积 | **是**（messages） | **是**（可被摘要替换） |
| `memory` | 跨会话级；sticky | **是** | 本身就是压缩产物 |
| `task` | 任务级；任务结束清空 | **是** | 否 |

**设计考虑**：
- `runtime.system_prompt` 每次都重新算（`refresh_runtime_system_prompt`），因为它依赖 skills registry 和 memory section。存档没意义。
- `conversation.messages` 是**模型真正看到的东西**，checkpoint 必须存全，否则恢复后模型"失忆"。
- `memory.working_summary` 是压缩摘要；它不能和 `conversation.messages` 混在一起，否则压缩后会出现"摘要里又引用摘要"的递归。
- `task` 层的所有字段一旦任务结束都必须清零——否则下一个任务继承脏状态。这是 `reset_task()` 存在的原因。

### 未雨绸缪的扩展点

- `memory.long_term_notes: list[str]` / `memory.checkpoint_data: dict` 这两个字段**现在为空**，是为未来长期记忆/多 checkpoint 留的钩子。
- `task.effective_review_request` / `task.retry_count` 已经定义但未读写——是为 code review 流程留的钩子（`agent/review.py` 已有 stub）。
- `runtime.review_enabled` 默认 `False`，控制是否启用 review 阶段——目前整条路径是 dead code，但字段在这里等着。

### 难点：全局单例

`core.py:56` 定义了**模块级全局** `state = create_agent_state(...)`。这是一个**权宜之计**：
- **优点**：简单，所有模块 `from agent.core import get_state`。
- **代价**：
  1. 单进程只能跑一个对话，不能并发 session
  2. 测试时不能轻松注入 fake state
  3. Stage 3 做 sub-agent 时会暴露——子 agent 和父 agent 必须隔离 state

**未来怎么改**：把 state 作为参数从 `main.py` 显式传入 `chat(state, user_input)`，链路上所有模块通过参数拿 state。但这是**重构级动刀**，目前主流程跑通优先。

---

## 3. 状态机 —— `task.status` 的所有合法值

### 合法状态集合

```
idle                             # 初始/重置后
planning                         # 当前未使用（保留给未来异步规划）
awaiting_plan_confirmation       # 计划已生成，等用户 y/n/feedback
running                          # 执行中
awaiting_tool_confirmation       # 工具需用户批准
awaiting_step_confirmation       # 一步完成，等用户确认进下一步
awaiting_user_input              # 等用户补充信息（两种来源，见下文）
done                             # 任务完成（暂态，紧接 reset_task）
failed                           # 预留，目前未使用
```

**`awaiting_user_input` 的两种来源**（同一个状态值，不同语义）：

| 来源 | 触发 | 区分依据 | 用户回复后行为 |
|---|---|---|---|
| **collect_input / clarify 步骤** | planner 提前规划出 step_type ∈ {collect_input, clarify}，模型 end_turn 时识别并切入 | `pending_user_input_request is None` | 步骤本身就是"问用户"，回复 = 完成。**推进 step** |
| **request_user_input 元工具** | 模型在普通 step 执行中调元工具暂停 | `pending_user_input_request != None`（保存 question / why_needed / options / context / step_index） | 是给当前 step 补信息。**不推进 step**，回 running 继续 |
| **runtime 兜底**（启发式 / 计数） | 模型不调元工具违纪时 runtime 强制切（详见 §3.1） | 同上：`pending_user_input_request != None`，question 是 assistant 文本 | 同 request_user_input 路径，**不推进 step** |

当前实现已经把这条恢复链路拆成两步：

1. `handle_user_input_step` 先调用 `resolve_user_input(state, user_input)`，把 `awaiting_user_input + USER_REPLIED` 解析成 `InputResolution`：
   - `pending_user_input_request is None` → `collect_input_answer`
   - `pending_user_input_request != None` → `runtime_user_input_answer`
2. 再调用 `apply_user_replied_transition(...)` 执行状态转移动作：
   - append `step_input`
   - 清理 `pending_user_input_request`（仅 runtime 求助路径）
   - 推进 step 或保持当前 step
   - `save_checkpoint`

这只是第一阶段轻量状态机化：只显式化用户回复恢复链路，还没有完整 transition table，也没有 ModelOutputResolution。

### 状态转换图（关键边）

```
idle ──(user 新输入 → planner 判多步)──► awaiting_plan_confirmation
awaiting_plan_confirmation ──(y)────► running
awaiting_plan_confirmation ──(n)────► idle (reset_task)
awaiting_plan_confirmation ──(fb)───► awaiting_plan_confirmation (new plan)

running ──(tool_use block 需确认)────► awaiting_tool_confirmation
awaiting_tool_confirmation ──(y)────► running (+ execute_pending_tool)
awaiting_tool_confirmation ──(n)────► running (+ 补占位 tool_result)
awaiting_tool_confirmation ──(fb)───► running (+ 补占位 tool_result + 事件)

running ──(end_turn + 步骤完成 + 非末步)──► awaiting_step_confirmation
awaiting_step_confirmation ──(y)────► running (下一步)
awaiting_step_confirmation ──(n)────► idle (reset_task)
awaiting_step_confirmation ──(末步 y)─► idle (reset_task)

running ──(end_turn + 末步完成)─────► done → idle (reset_task)

# 求助态（执行期信息缺口）
running ──(model 调 request_user_input)─────► awaiting_user_input (+ 写 pending_user_input_request)
running ──(end_turn + assistant 文本含问号 / 求助词)──► awaiting_user_input (启发式兜底 · 见 §3.1)
running ──(连续 2 次 end_turn 无工具调用)──────► awaiting_user_input (计数兜底 · 见 §3.1)
awaiting_user_input ──(用户回复, pending != None)─► running (求助分支：写 step_input，**不推进 step**)
awaiting_user_input ──(用户回复, pending == None)─► running / awaiting_step_confirmation / done (collect_input 旧路径：写 step_input + 推进)

# 计划阶段的 user_input 步骤（planner 预判）
running ──(end_turn + step_type ∈ {collect_input, clarify})──► awaiting_user_input (pending == None)
```

### 状态转换的三条铁律

**铁律 1 · 每个状态跳变必须 `save_checkpoint`**。磁盘和内存必须同步，否则 Ctrl+C 后重启会回到旧状态。

当前所有落盘点（按流程顺序）：
1. `_run_planning_phase` 进 `awaiting_plan_confirmation` 后（core.py:199）
2. `handle_plan_confirmation` 所有分支后（confirm_handlers.py 多处）
3. `tool_executor.execute_single_tool` 进 `awaiting_tool_confirmation` 后（tool_executor.py:72）
4. `tool_executor.execute_single_tool` 工具执行完后（tool_executor.py:96）
5. `handle_tool_confirmation` 所有分支后
6. `advance_current_step_if_needed` 推进或完成后（task_runtime.py）
7. `handle_end_turn_response` 进 `awaiting_step_confirmation` 后
8. `core.chat()` 压缩真实发生后

**铁律 2 · `awaiting_*` 是半开事务**。这时 messages 里有未闭合结构（待回填的 tool_result、待 ack 的 plan），**不能压缩、不能改 messages 顺序**，只能等用户输入触发闭合。

**铁律 3 · 进入 `done` 必须同时 `clear_checkpoint` 和 `reset_task`**。`clear_checkpoint` 管磁盘（跨进程），`reset_task` 管内存（同进程下一次 `chat()`）。少一个就会在不同时间尺度暴露僵尸状态。

---

## 3.1 主循环 loop guard —— runtime 不能假设模型守协议

理想路径：模型在执行 step 中需要用户介入时主动调 `request_user_input`（元工具），runtime 通过状态机响应。但 LLM 不一定遵守协议——可能用普通自然语言追问、可能 end_turn 等下一轮、可能空跑一段时间。

**反面教材**：`handle_end_turn_response` 旧实现在 `running` 分支硬塞 `[系统] 请打分或继续` 提示。模型若违纪用文本散问 → end_turn → 注入 → 再散问 → … 形成死循环（武汉旅游规划事故的主根因）。

### 三层防线

```
模型遵守协议
   ↓
[理想路径] 调 request_user_input
   ↓                                    ← 直接切 awaiting_user_input

模型违纪（用文本散问）
   ↓
[兜底 1 · 启发式] assistant 文本含 "?" / "？" 或 任一中文求助词     ← 见词表
                  → 立即切 awaiting_user_input
   ↓
[兜底 2 · 计数] consecutive_end_turn_without_progress >= 2
                → 强制切 awaiting_user_input

模型每轮都"看似有进展"调业务工具但永不收敛
   ↓
[终极兜底] MAX_LOOP_ITERATIONS = 50 兜住
            → reset_task + 提示用户
```

### 启发式词表（agent/response_handlers.py::handle_end_turn_response）

```
"?" / "？"
"请告诉我" / "请提供" / "请说明" / "请回复" / "请补充"
"麻烦您" / "您能否" / "请确认"
```

任一命中即视为"模型在向用户索要阻塞信息"。

### 计数器（state.task.consecutive_end_turn_without_progress）

```
handle_tool_use_response 开头 → 清零（任意工具调用都算"有效推进"）
handle_end_turn_response running 分支 → 自增；>= 2 强停
reset_task → 清零
```

**关键不变量**：业务工具 + 元工具都触发清零。这是为了让模型从"卡壳"恢复时不被旧计数误伤——一旦它响应到工具调用就回到正常路径。

### 双层兜底切 awaiting_user_input 时的副作用

写 `state.task.pending_user_input_request`：
```python
{
    "question": assistant 文本截前 500 字 或 "[模型 end_turn 但未声明步骤完成；请你介入]",
    "why_needed": "模型未调用 request_user_input；为防 loop 死循环，系统强制暂停等你回应",
    "options": [],
    "context": "",
    "tool_use_id": "",       # 不来自真实工具调用
    "step_index": current_step_index,
}
```

下一次 `chat(user_input)` 走 `handle_user_input_step` 求助分支：写 `step_input`、清 pending、`status=running`、**不推进 step**——和 `request_user_input` 路径完全一致。

### 设计取舍

- **第 1 次 end_turn 仍温和软驱动**（注入"请调 mark_step_complete 或 request_user_input"提示），第 2 次才强停。比"第 1 次就停"更友好（保留模型合理停顿空间），比"无限放行"更安全
- **行为兜底（计数器）+ 内容兜底（启发式）并用**：启发式抓"明显是问句"的多数场景；计数器兜启发式漏判（陈述句问题之类）
- **不靠 LLM 判 LLM**：兜底纯靠字符串匹配 + 计数。多一次 LLM 调用做意图分类既贵又不稳

详见 ROADMAP Block 1.5。

---

## 4. 最脆弱的协议 —— `tool_use ↔ tool_result` 配对

### Anthropic API 的契约

```
assistant 消息的 content blocks:
  [
    {"type": "text", "text": "..."},          ← 可选
    {"type": "tool_use", "id": "toolu_X",      ← 每个 tool_use 都要
     "name": "...", "input": {...}},          │
    ...                                        │
  ]                                            │
                                               │ tool_use_id 一一对应
user 消息的 content blocks:                    │
  [                                            │
    {"type": "tool_result",                    ▼
     "tool_use_id": "toolu_X",                 ← 必须能在前面的 assistant
     "content": "..."},                           消息里找到匹配的 tool_use
    ...
  ]
```

**配对失败的后果**：下次 API 调用返回 400 `tool_use_id not found`。主流程崩。

### 在哪些地方会被破坏？

| 破坏点 | 场景 | 防御 |
|---|---|---|
| assistant 消息存成纯文本 | 之前 `extract_text_fn` 把 `tool_use` 块丢了 | `_serialize_assistant_content`（response_handlers.py）保留完整 content blocks |
| 多个 tool_use 其中一个阻断 | `FORCE_STOP` / `AWAITING_USER` 早退时，剩余 tool_use 没写 tool_result | `_fill_placeholder_results` 给剩余块补占位（**只作用业务工具**，见下文） |
| `execute_tool` 抛异常 | tool_use 声明了但没 tool_result | `tool_registry.execute_tool` try/except 把异常转成字符串结果 |
| 用户拒绝/反馈工具 | tool_use 在 messages 但 tool_result 从没写 | `handle_tool_confirmation` 的 n/feedback 分支补占位 |
| `compress_history` 切在中间 | 把 tool_use 压进摘要、tool_result 留在 recent | `_find_safe_split_index` 向前回溯切点 |
| `awaiting_tool_confirmation` 时触发压缩 | 同上更隐蔽 | `core.chat()` 把压缩推迟到 awaiting 分支之后 |

### 例外：元工具**故意打破**配对

元工具（`mark_step_complete`）的 `tool_use` 不进 messages，也没有对应的 `tool_result`——这是**显式设计**，不是 bug。实现处：

- `_serialize_assistant_content`：检测到 `is_meta_tool(block.name)` 就 `continue`，不序列化这个块
- `tool_executor.execute_single_tool`：元工具分支只写 `tool_execution_log`，不调 `append_tool_result`
- `_fill_placeholder_results`：占位补齐只作用于**业务工具**剩余块（`[b for b in ... if not is_meta_tool(b.name)]`），元工具不参与

为什么这样做：元工具是**系统控制信号**（给状态机判"这步做完了吗"），不是对话内容。若进 messages，模型下一轮会看到自己调过 `mark_step_complete`，产生"系统控制 = 对话内容"的语义混乱；若补占位 tool_result，由于对应的 tool_use 已被剔除，tool_result 会成为"挂空"的孤儿 → API 返回 400。

### 为什么是**多层**防御？

不是过度工程。每一层保护的是不同的**失败模式**：

- 第 1-4 层保护**同步代码路径**的 bug（开发者忘了写 tool_result）
- 第 5 层保护**异步时机**的 bug（压缩在错误的时间点发生）
- 第 6 层保护**状态机**的 bug（进了不该有压缩的状态）

**类比**：数据库的 ACID 四个字母是**四个独立的保证**，不能用一个代替另一个。这里的 6 层防御同理。

---

## 5. 主循环 —— `core.py::chat()` 的六个分支

`chat(user_input)` 是整个系统的单一入口。它的**判断顺序**非常重要，颠倒一个就会出 bug。

```
chat(user_input):
  refresh_runtime_system_prompt()           # 每次都重算

  turn_state = TurnState(system_prompt)

  ─── 半开事务处理区（绝不可压缩）─────
  if status == "awaiting_plan_confirmation": return handle_plan_confirmation(...)
  if status == "awaiting_step_confirmation": return handle_step_confirmation(...)
  if status == "awaiting_user_input":         return handle_user_input_step(...)   # 内部走 InputResolution + user replied transition
  if status == "awaiting_tool_confirmation":  return handle_tool_confirmation(...)

  ─── 到这里才是"全新/继续对话"，可以压缩 ───
  compress_history(...)  → 如压缩发生，save_checkpoint

  if status == "running":                    # 有任务在跑，这次输入是反馈
      append user_input
      return _run_main_loop

  ─── 全新任务 ───
  重置 loop_iterations / tool_call_count / ...
  _run_planning_phase(user_input)
  return _run_main_loop
```

### 为什么 awaiting 判断要在压缩之前？

**如果颠倒**：压缩先跑，可能把正在等确认的 `tool_use` 块压进摘要，然后用户输入 `y` 触发 `handle_tool_confirmation` 写 `tool_result`——此刻 `tool_use_id` 已经不在 messages 里了，下一次 API 调用 400。

这就是 **"半开事务不可压缩"** 铁律的代码实现。

### `_run_main_loop` 的 stop_reason 分派

```python
while loop_iterations++ <= MAX_LOOP_ITERATIONS:
    response = _call_model(turn_state)
    match response.stop_reason:
        "max_tokens":
            handle_max_tokens_response → 累计 consecutive_max_tokens，超限终止
        "end_turn":
            handle_end_turn_response → 判断步骤完成；非末步 awaiting_step，末步 done
        "tool_use":
            handle_tool_use_response → 执行工具；可能 AWAITING_USER/FORCE_STOP
        其他:
            return "意外的响应"
```

### 难点：循环什么时候退出？

**退出条件有 5 种**，每种的 return 值和含义不同：

1. `end_turn` 且步骤完成 → 返回文本，**正常退出**
2. `tool_use` 处理完但没新 tool_use → `return None` → 继续 loop
3. `tool_use` 进 `AWAITING_USER` → 返回 `""` → 退循环，等用户输入
4. `tool_use` 撞 `FORCE_STOP` / 超限 → 返回错误文字，退
5. `max_tokens` 累计超阈值 → 返回错误文字，退
6. 循环次数超 `MAX_LOOP_ITERATIONS` → 兜底退

设计上**没有真正的"死循环"**——三条兜底：`MAX_LOOP_ITERATIONS` / `MAX_TOOL_CALLS_PER_TURN` / `MAX_CONTINUE_ATTEMPTS`。

---

## 6. 规划层 —— `planner.py` 的单步/多步判断

### 为什么 planner 单独调一次 LLM？

不是必须的——你可以让主模型自己决定要不要拆步骤。**但**：

1. **关注点分离**：planner 用更小的 prompt 专门判断拆分，主模型专心执行。
2. **判断稳定性**：planner 的 `PLANNING_PROMPT` 强制 JSON 输出 + Pydantic 校验，错误能 fail-fast。
3. **成本控制**：planner 用 1024 max_tokens 就够，主模型用 128000。

### `PlannerOutput` vs `Plan` 的双模型设计

```python
PlannerOutput   # LLM 返回的原始解析；允许 steps_estimate=1 + 空 steps
   ↓ 若 steps_estimate<=1：返回 None（单步路径）
   ↓ 否则：校验 goal 和 steps 非空，构造 Plan
Plan            # 真正被使用的实体；必须有 goal + 非空 steps
```

**设计考虑**：两层分开让"LLM 输出的模糊形态"和"内部稳定形态"隔离。外部数据过边界时做一次强校验（Pydantic `model_validate`），内部所有代码就可以信任 `Plan` 是合法的。

### 未雨绸缪

- `Plan.needs_confirmation` 字段存在但**目前始终按 True 处理**——未来可以让某些类型的 plan 自动执行不询问。
- `PlanStep.step_type` 是 Enum，目前只作为 prompt 里的标签，**没有代码根据 step_type 做行为分支**。未来可以：
  - `read` 类型强制只允许读工具
  - `edit` 类型强制 review 流程
  - `run_command` 类型强制确认

### 步骤完成检测：元工具 + 分值阈值（2026-04-25 重写）

**旧设计（已废弃）**：`is_current_step_completed(state, text)` 在 `assistant_text` 里找关键词 `"本步骤已完成"`。脆弱——模型忘说就卡死，说错位置就误触发。

**新设计**：由模型主动调 `mark_step_complete` 工具声明，系统按分值决定是否真推进。

```python
# agent/tools/meta.py
@register_tool(
    name="mark_step_complete",
    description="...完成度评分 0-100；分值 ≥ STEP_COMPLETION_THRESHOLD 才算完成...",
    parameters={
        "completion_score": {"type": "integer", ...},   # 0-100 自评
        "summary": {"type": "string", ...},              # 客观事实：这步做了什么
        "outstanding": {"type": "string", ...},          # 未完成项（<100 时必填）
    },
    confirmation="never",
    meta_tool=True,   # ← 关键：走特殊路径
)
```

**判定逻辑**：`task_runtime.is_current_step_completed(state)` 只接 state，不再接文本：

```python
latest = get_latest_step_completion(state)    # 当前 step_index 最新一条 mark_step_complete
if latest is None:
    return False
return latest["completion_score"] >= STEP_COMPLETION_THRESHOLD   # 默认 80
```

**闭环自纠正**：分值 < 阈值时，`build_execution_messages` 把 `outstanding` 注入下一轮 step block：

```
【上一轮自评（未达阈值，必须继续）】
- 上次打分：60/100（阈值 80）
- 上次自述完成度：{summary}
- 上次承认的未完成项：{outstanding}
- 请优先补齐未完成项，而不是重复已做过的工作...
```

### 为什么是"元工具 + 分值"而不是"元工具返回 bool"？

1. **分值是连续信号**，给系统更多判断余地。可以未来调阈值、可以按任务类型不同阈值（Plan step 粒度）。
2. **强制打分 = 强制自省**。模型必须把"做得怎么样"映射成数字，就难以自欺"差不多得了"。
3. **outstanding 字段**把"做到哪"和"还差啥"分开记录。`summary` 是客观事实，`outstanding` 是残项——后者直接喂回下一轮做反馈闭环。

### 难点：模型不调元工具怎么办？

这是新设计**仍然存在**的脆弱点（xfail `test_step_never_progresses_when_model_forgets_to_call_mark_step_complete`）：模型若 end_turn 时没调 `mark_step_complete`，步骤永远不推进，只能靠 `MAX_LOOP_ITERATIONS` 兜底。

目前的缓解：step block 里**三条强约束** +  prompt 明确说"只认工具信号，不认文本"。真机跑 Kimi 偶发，但远好于旧关键词方案的频率。

**未来可选改进**：在 `_maybe_advance_step` 后加 `no_meta_turns` 计数，连续 N 轮空跑后主动给用户提示。

---

## 7. 工具层 —— 三种确认模式 + 幂等执行

### 注册机制

```python
@register_tool(
    name="read_file",
    description="...",
    parameters={"path": {"type": "string"}},
    confirmation="never",       # 三种：always | never | callable
    pre_execute=None,
    post_execute=None,
)
def read_file(path): ...
```

`TOOL_REGISTRY` 是模块级 dict，在 `import agent.tools` 时全部注册（core.py:6 的 `noqa: F401`）。

### 三种确认模式

| confirmation 值 | 含义 | 使用场景 |
|---|---|---|
| `"always"` | 每次调用都问用户 | 默认；写文件、删文件、执行命令 |
| `"never"` | 永不询问 | 读文件、列目录等只读操作 |
| `callable(tool_input) -> bool` | 按输入动态判断 | 比如"读 `.py` 但不读 `.env`" |
| 返回字符串 `"block"` | 安全策略阻断 | `pre_execute` 钩子可以提前阻断 |

### 元工具 vs 业务工具：两条执行路径

`tool_executor.execute_single_tool` 开头先判元工具分支：

```python
if is_meta_tool(tool_name):
    # 元工具通用路径：只写 log，不写 messages、不补 tool_result
    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "input": tool_input,
        "result": "",                  # 元工具没有业务语义的返回值
        "status": "meta_recorded",
        "step_index": state.task.current_step_index,
    }

    # 不同元工具的额外副作用按工具名分派（暂硬编码，详见 §7.1）
    if tool_name == "request_user_input":
        # 写 pending_user_input_request、切 status=awaiting_user_input、清当前 step 残留 mark
        ...

    save_checkpoint(state)
    return None
```

**当前注册的两个元工具**：

| 元工具 | 用途 | 副作用 |
|---|---|---|
| `mark_step_complete(completion_score, summary, outstanding)` | 模型声明本步骤完成度 | 仅写 log；`is_current_step_completed` 读分值判推进 |
| `request_user_input(question, why_needed, options, context)` | 执行期向用户索要关键信息 | 写 log + 写 `pending_user_input_request` + 切 `status=awaiting_user_input` + 清当前 step 的 stale mark log + `save_checkpoint` |

**为什么元工具要带 `step_index`**：`get_latest_step_completion(state)` 按步过滤——step 2 完成时不能读到 step 1 的旧分值。所有 log 条目统一带 `step_index`（业务工具也一样），方便事后按步审计。

**为什么元工具不进 messages / 不生 tool_result**：元工具是**系统控制信号**（给状态机判断），不是对话内容。若进 messages，模型下一轮会看到自己调过控制信号，产生"系统状态 = 对话内容"的语义混乱；若补占位 tool_result，由于对应的 tool_use 已被剔除，会成为"挂空"的孤儿 → API 返回 400。详见 §4 的"元工具故意打破配对"段。

### 幂等执行 —— `tool_execution_log`

```python
# tool_executor.execute_single_tool，业务工具分支
if tool_use_id in state.task.tool_execution_log:
    cached = ...["result"]
    append_tool_result(messages, tool_use_id, cached) (如未配对)
    return None                            # 跳过执行
```

**为什么需要幂等**：
- checkpoint 恢复时，已执行的 tool 不应该重跑（重跑可能有副作用）
- 多轮调用里，同一个 tool_use_id 理论上不会重复，但幂等层是**兜底**

**设计考虑**：`tool_execution_log` 是 `dict[tool_use_id → {tool, input, result, status, step_index}]`。它有**三重身份**：
1. **幂等表**：tool_use_id 查重，防重复执行
2. **审计日志**：事后能按 step_index 回放整个任务的工具调用序列
3. **状态机输入**：`mark_step_complete` 的记录直接被 `is_current_step_completed` 读取判断——元工具的执行结果**就是**状态机的读源

### pending_tool —— 半开事务的快照

```python
state.task.pending_tool = {
    "tool_use_id": tool_use_id,
    "tool": tool_name,
    "input": tool_input,
}
state.task.status = "awaiting_tool_confirmation"
save_checkpoint(state)
```

这三个动作必须**同时发生 + 立即落盘**，不然 Ctrl+C 会让状态机处于不一致。

用户回复后，`handle_tool_confirmation` 读 `pending_tool`，调 `execute_pending_tool`，**成功**才清空 `pending_tool`。失败保留——这是和"幂等"配套的**失败可排查**设计。

---

## 7.1 request_user_input 元工具完整链路

执行期模型卡住、需要用户介入时的 ideal path。整个链路必须保证：**用户的真实回复**通过 `step_input` 进入下一轮上下文，**`request_user_input` 工具调用本身**不进 messages、不留任何痕迹。

### 完整链路（理想路径）

```
[1] 普通执行 step（非 collect_input/clarify）
    模型在执行中发现关键信息缺失 → 调 request_user_input
    （prompt 在 context_builder 普通步骤纪律段约束："必须用此元工具，
      不要散问、不要同轮调 mark_step_complete、不要同轮混业务工具"）

[2] 模型 response：
      content: [text("我需要确认 X"), tool_use(request_user_input, {question, why, options, context})]
      stop_reason = tool_use

[3] response_handlers.handle_tool_use_response:
    a. _serialize_assistant_content:
       text 块保留，tool_use(request_user_input) 因 is_meta_tool 被剔除
       → state.conversation.messages 末尾：assistant 只剩 text，没 tool_use 痕迹
    b. for 循环到 request_user_input 这个 block:
       execute_single_tool → 元工具分支
         · 写 tool_execution_log（带 step_index, status="meta_recorded"）
         · request_user_input 专属副作用：
             pending_user_input_request = {question, why_needed, options, context,
                                            tool_use_id, step_index}
             status = "awaiting_user_input"
             # B 防御：清掉当前 step_index 的 mark_step_complete log，避免
             # 模型若同轮调了 mark+request 时残留分值导致用户回复后错误推进
             tool_execution_log.pop(stale_mark_ids)
         · save_checkpoint
    c. for 循环 i+1 处守卫：检测到 status == "awaiting_user_input" →
       给本轮剩余未执行的业务 tool_use 补占位 tool_result（防 API 协议悬空）
       打印 question / why_needed / options 给用户
       return ""  ← 跳出 _run_main_loop

[4] checkpoint 落盘内容：
    status = "awaiting_user_input"
    current_step_index = 不变
    pending_user_input_request = {完整请求详情}
    conversation.messages 末尾 = assistant text（无 tool_use 痕迹）
    tool_execution_log[tool_use_id] = meta_recorded 条目

[5] main_loop 等待用户输入

[6] 用户回复 "答复内容" → chat("答复内容")

[7] core.chat() 状态分流：status == "awaiting_user_input" → handle_user_input_step

[8] handle_user_input_step 求助分支（pending != None）：
    append_control_event("step_input", {
        "question":   pending.question,
        "why_needed": pending.why_needed,
        "content":    user_input.strip(),
    })
    pending_user_input_request = None
    status = "running"
    save_checkpoint
    return ctx.continue_fn(turn_state)
    # 不调 advance_current_step_if_needed —— 当前 step 还没完成

[9] _run_main_loop 重入 → _call_model 调 build_execution_messages：
    模型上下文（节选）：
      ...历史摘要 + planning context...
      assistant: "我需要确认 X"                           ← 上一轮 text
      user:      "用户针对问题「X」补充了当前步骤所需信息：
                   - 补充内容：答复内容
                   - 需要该信息的原因：why_needed"        ← step_input 配对渲染
      user:      [当前任务] step block（含目标 + 完成要求 + 信息缺口纪律）

    模型上下文里**没有**任何 request_user_input 的 tool_use 或 tool_result。

[10] 模型继续做当前 step：调业务工具 / 调 mark_step_complete 收尾 / ...
```

### 三个不变量（已被测试钉死）

1. **`request_user_input` 的 tool_use 永不进 messages**
   - 由 `_serialize_assistant_content` 的 `is_meta_tool` 检查保证（`response_handlers.py`）
   - 测试：`test_request_user_input_pauses_loop_in_normal_step` 显式扫 messages 断言

2. **`request_user_input` 永不生成 tool_result**
   - 由 `tool_executor` 元工具分支不调 `append_tool_result` 保证
   - 测试同上

3. **用户回复以 step_input 控制事件进入下一轮上下文**（含 question + why_needed + answer 配对）
   - `conversation_events.py::append_control_event` 渲染按 payload 是否含 `question` 走两套文案
   - 测试：`test_multi_field_user_reply_fully_persisted_to_messages` 断言 6 字段全保留

### 与"collect_input / clarify 步骤"的差异

`awaiting_user_input` 是同一个状态值，但来源不同时**用户回复后行为完全相反**：

| 维度 | request_user_input | collect_input / clarify |
|---|---|---|
| 触发时机 | 普通 step 执行中模型主动调 | planner 提前规划出来的 step_type |
| pending_user_input_request | 非 None | None |
| 回复后 step_index | **不推进**（当前 step 还没完成，只是补信息） | **推进**（这一步本就是问用户，回了就完成） |
| step_input payload | `{question, why_needed, content}`（配对渲染） | `{content}`（旧路径） |
| handle_user_input_step 分支 | 求助分支（早返回） | 旧路径（含 confirm_each_step + advance） |

`handle_user_input_step` 第一行就检查 `pending_user_input_request`——非 None 走求助分支，None 走旧路径。

### 设计取舍

- **options / context 不进模型上下文**：仅在用户提示阶段展示给用户。模型刚问的、它知道为什么；options 是给真人的菜单
- **why_needed 进上下文**：跨 checkpoint 恢复后模型可能"记不得"为什么问；step_input 渲染里把它带上一行成本极小，防御度高
- **当前按工具名硬编码分派**：tool_executor 元工具分支里 `if tool_name == "request_user_input"` 硬编码副作用。元工具增多时（出现第三个）再考虑在 `register_tool` 加 `meta_kind` 字段抽象——按 Parnas "等到第三次重复才动手"
- **B 防御 · 同轮 mark + request 时清残留**：若模型违纪同轮调 `mark_step_complete(90)` + `request_user_input`，不清的话用户回复后下一轮 `_maybe_advance_step` 会读残留分值错误推进 step。语义上：**求助即"步骤未完成"，必须作废任何已写入的完成声明**。这条防御有专门测试 `test_request_user_input_clears_stale_mark_step_complete`

---

## 8. 上下文构造 —— 两种 messages 的差异

### `build_planning_messages` · 给 planner

```
[摘要?] + 历史（过滤掉 tool_use/result 块）+ 当前 user_input
```

**为什么过滤工具块**：
- planner 的 system prompt 只教它输出 JSON，不懂工具语义
- 带着工具块会作为噪声干扰 `steps_estimate` 判断
- `_strip_tool_blocks` 把 content blocks 里的 `type=text` 提出来拼成字符串

### `build_execution_messages` · 给执行阶段主模型

```
[摘要?] + 历史（原样，含 tool_use/tool_result 块）+ 【当前步骤指令块】←末尾
```

**为什么步骤指令块放末尾而不是开头**：
- LLM 的注意力衰减：最近的消息权重最大
- 如果放开头，模型看完多轮 tool_result 会遗忘当前步骤约束
- 放末尾让"执行约束"紧贴"最新工具结果"，形成"看到 X，根据约束 Y，下一步做 Z"的连贯推理

### 难点：step 指令块的内容设计

`build_execution_messages` 拼的这个块大约 20 行，包含：
- 当前任务 / 规划思路
- 已完成步骤列表（防重复）
- 当前步骤的 title/description/type/suggested_tool/expected_outcome/completion_criteria
- **三个约束块**：执行上下文、执行约束、行为判断规则
- 完成要求

**冗余吗？**看起来是。但模型在长 context 下容易"跑偏"，这些约束是防御性的。**可以优化**但不要轻易删——每条约束都对应过去某次观察到的 failure mode。

---

## 9. 持久化 —— Checkpoint vs Session Snapshot

### 两种存档的职责区别

| 文件 | 何时写 | 何时读 | 内容 |
|---|---|---|---|
| `memory/checkpoint.json` | 每个状态跳变 + 工具执行 + 压缩 | 进程启动时恢复未完成任务 | `task + memory + conversation.messages`（截断大 tool_result） |
| `sessions/session_*.json` | 退出 + 中断 | 不自动读（只供人工审计/回放） | 完整 messages，不截断 |

**为什么分两个**：
- checkpoint 要**频繁写 + 快速恢复**，大小必须受控（所以截断 tool_result 到 2000 字符）
- session snapshot 要**完整保真 + 事后审计**，尺寸不敏感

### `compress_history` 的两层保护

1. **外层保护**（`core.chat()`）：awaiting 状态时**完全跳过**压缩
2. **内层保护**（`_find_safe_split_index`）：即使触发压缩，切点向前回溯直到不切断 tool pair，实在找不到就放弃压缩

### 难点：切点回溯的正确性

`_find_safe_split_index` 的算法是：

```
split = n - preferred_recent         # 最初切点
while split > 0:
    recent = messages[split:]
    找 recent 里的 tool_use_ids 和 tool_result_ids
    if 没有孤悬的 use 也没有孤悬的 result:
        return split                  # 合法
    split -= 1                        # 向前一步
return 0                              # 放弃
```

**为什么 `-=` 不是 `+=`？**

- `-=`：把 split 向前推，**recent 变大**，old 变小。更多消息进 recent，孤悬的配对会逐渐闭合。
- `+=`：把 split 向后推，**recent 变小**，old 变大。会让更多 tool_use/result 进 old，情况更糟。

这个方向感**很容易写反**，要记住"**recent 要长大，不是变小**"。

---

## 10. 未雨绸缪的设计（扩展点地图）

### Cost 追踪（Stage 3）

**扩展点**：
1. `TaskState` 加 `cost_usd: float = 0.0`
2. `reset_task` 里加一行 `self.task.cost_usd = 0.0`（**最容易漏**）
3. `_call_model` 返回后读 `response.usage`，换算成 cost 累加进 `state.task.cost_usd`
4. `logger.log_event("model_call", {"cost": ...})` 每次调模型留日志

### Sub-agent（Stage 3）

**当前障碍**：`core.state` 是模块级全局单例，子 agent 无法隔离。

**重构方向**：
- 把 `state` 改成显式参数传递
- 新增 `SubAgentState` 继承 `AgentState`，带 parent 引用
- `tool_registry` 加一个 `spawn_sub_agent` 工具

### MCP（Stage 3）

**扩展点**：
1. `tool_registry.register_tool` 支持注册 MCP 工具（sync/async 二选一）
2. `execute_tool` 对 MCP 工具走异步路径
3. `_serialize_assistant_content` 可能要处理 MCP 的结构化返回
4. `append_tool_result` 的 content 参数目前只接受字符串，MCP 返回可能要支持 dict

### Review 流程

**当前状态**：`state.runtime.review_enabled` 字段已有，`agent/review.py` 文件已有。但主循环里没接入。

**接入点**：`_run_main_loop` 里 `stop_reason == "end_turn"` 时，根据 `runtime.review_enabled` 决定是否插一次"review turn"——用不同 prompt 重新问模型检查上一轮输出。

---

## 11. 难点清单（读代码时重点关注）

| # | 难点 | 文件:行 | 关键词 |
|---|---|---|---|
| 1 | tool_use/tool_result 配对契约 | response_handlers.py 全文 | `_serialize_assistant_content` / `_fill_placeholder_results` |
| 2 | 状态机转换的落盘时机 | 散落多处 | 搜 `save_checkpoint` |
| 3 | compress_history 的切点回溯 | memory.py:68 | `_find_safe_split_index` |
| 4 | awaiting 分支不能压缩 | core.py:100 | 判断顺序 |
| 5 | pending_tool 成功才清空 | confirm_handlers.py:147 | try/except 保留 |
| 6 | 全局 state 单例 | core.py:56 | `create_agent_state` |
| 7 | 步骤完成靠**元工具分值**判定（不是关键词） | task_runtime.py + tool_executor.py + meta.py | `is_meta_tool` / `mark_step_complete` / `STEP_COMPLETION_THRESHOLD` |
| 8 | 元工具**不进 messages**（故意打破 tool_use/tool_result 配对） | response_handlers.py + tool_executor.py | `_serialize_assistant_content` 里的 meta continue 分支 |
| 9 | Plan 的双模型（PlannerOutput/Plan） | plan_schema.py + planner.py | `model_validate` 边界 |
| 10 | reset_task 必须清所有 task 字段 | state.py | 漏一个就跨任务污染 |
| 11 | done 必须同时 clear_checkpoint + reset_task | response_handlers.py | 磁盘 + 内存双清 |
| 12 | 元工具触发推进在 tool_use 轮，不等 end_turn | response_handlers.py | `_maybe_advance_step` 在两种 handler 里都被调 |
| 13 | `awaiting_user_input` 两种来源（求助 vs collect_input）共用状态值 | confirm_handlers.py + state.py | `pending_user_input_request` 是 None / 非 None 分流 |
| 14 | 双层 loop guard 不能假设模型守协议 | response_handlers.py + state.py | `consecutive_end_turn_without_progress` + 启发式词表（§3.1） |
| 15 | request_user_input 求助态触发时同步清当前 step 的 stale mark log（B 防御） | tool_executor.py | 求助 = 步骤未完成，作废任何已写入的完成声明 |
| 16 | CLI 层用户输入必须是原子的（一次回复 = 一个 user_input） | main.py | `read_user_input` 的 `/multi` / 围栏协议；详见 §13 |

---

## 12. 已知的遗留问题（还没修 / 故意不修）

| 问题 | 位置 | 为什么不修 |
|---|---|---|
| `state.task.consecutive_rejections` 声明但从不读写 | state.py | 死代码，不影响运行 |
| `tool_call_count > MAX_TOOL_CALLS_PER_TURN` 是 `>` 不是 `>=` | response_handlers.py | 差一个，不致命 |
| `save_checkpoint` 不调 `log_event` | checkpoint.py | 观测性缺口，不影响正确性 |
| `PROJECT_DIR = Path.cwd().resolve()` 依赖启动 cwd | config.py | 重构级，不在 bug 范围 |
| planner 看不到"步骤重规划"的历史反馈 | confirm_handlers.py | 反馈拼进 `revised_goal`，但上下文历史裁掉了 tool 块 |
| `session_snapshot` 和 `checkpoint` 内容重叠但不共享代码 | logger.py + checkpoint.py | 可提公共序列化层，但现在各司其职更清晰 |
| `TurnState` 还是 dataclass，`state.task` 的 runtime 计数没有 property 化 | core.py | 小优化，不影响功能 |
| 模型不调 `mark_step_complete` 时步骤卡死 | 见 xfail 测试 | 依赖 `MAX_LOOP_ITERATIONS` 终极兜底。**注意**：模型若用文本散问、走 end_turn 不调任何工具，已被 §3.1 双层 loop guard 接住 → 切 awaiting_user_input；只有"每轮都调业务工具但永不 mark"这一极端 case 才会走到 MAX_LOOP_ITERATIONS（专门有 `test_max_loop_iterations_terminal_guard_still_fires_when_double_layer_bypassed` 守住） |
| `STEP_COMPLETION_THRESHOLD = 80` 是全局常量 | config.py | 按 PlanStep 粒度可配置更好，但要改 plan_schema，暂缓 |
| `request_user_input` 元工具按工具名硬编码分派副作用 | tool_executor.py | 当前只两个元工具，硬编码最简；等出现第三个再抽 `meta_kind` 字段 |
| `request_user_input` 的 `options` / `context` 被强制 required | tool_registry.py | `get_tool_definitions` 把所有 parameter 都进 required；prompt 里告诉模型无候选传 `[]` / 无信息传 `""`；抽 optional schema 是单独的小重构 |
| 启发式词表（§3.1）硬编码常量 | response_handlers.py | 漏判时逐项扩展；不做复杂 NLP 分类器；多刷一屏问题由计数器接住 |
| Ctrl+C 在 ``` 围栏粘贴模式下被主循环 KeyboardInterrupt 接住 | main.py + session.py | 想"取消围栏"只能再输 ``` 让函数返回（内容空）后主循环空输入过滤跳过——可接受 |

---

## 13. CLI 多行输入协议 —— 保证 user_input 原子性

### 为什么这是架构问题不只是 UX

`step_input` 控制事件设计的前提是"用户一次回复 = 一个原子 user_input"。`main.py` 旧实现 `input("你: ")` 只读一行——终端粘贴多行（含 `\n`）时只到第一个 `\n` 就返回，剩余内容留在 stdin 缓冲，下次 `input()` 才取走。**结果**：一段长回复（含多个字段）被切成多次 `chat()` 调用，每次模型只看到一段，**破坏了 `request_user_input → 用户答复 → 完整信息回到下一轮 step` 这条核心链路**——这是武汉旅游规划事故"模型反复追问已答字段"的次要根因。

修了 §3.1 双层 loop guard 防住了死循环，但保护不了 step_input 的语义完整性——必须从输入层解决。

### 协议（main.py::read_user_input）

```python
def read_user_input(
    prompt: str = "你: ",
    *,
    reader: Callable[[str], str] = input,
    writer: Callable[[str], None] = print,
) -> str | None:
    first = reader(prompt)
    stripped = first.strip()
    if stripped == "/multi":
        return _collect_multiline(... done="/done", cancel="/cancel" ...)
    if stripped == "```":
        return _collect_multiline(... done="```", cancel=None ...)
    return first       # 单行原样返回（与历史行为一致）
```

支持：
- **普通单行**（保留原行为）
- **`/multi` + 多行 + `/done`** 提交（或 `/cancel` → 函数返回 `None`，`main_loop` 跳过本轮、不调 `chat`）
- **三引号围栏粘贴**（再次 ``` 结束；无 cancel 路径，需要中断走 Ctrl+C）
- **EOFError 视作 done**（stdin 关闭时不丢已收集的数据）

### reader / writer 注入：让输入逻辑可测

通过参数把 `input` / `print` 注入：单元测试用 `_make_reader([...])` 喂预录序列，`_silent_writer` 吞掉提示。**输入层的状态机变成可测**——不再依赖终端，不再有"测试时怎么模拟用户敲键盘"的难题。

测试覆盖（`tests/test_main_input.py`）：
- 单行原样返回
- 单行的 `/reload_skills` 不被新协议拦截（既有 slash 命令兼容）
- `/multi` + 多行 + `/done` 完整拼接
- `/done` 周围空白也识别为终止
- `/multi` + `/cancel` 返回 `None`
- ``` 围栏 + ``` 结束
- 围栏内 `/cancel` 当普通内容（不是取消信号）
- `/multi` 中 stdin 关闭（EOFError）→ 把已收集行当 done 提交

### 与状态机的接口

`main_loop` 拿到 `read_user_input` 返回后：
```
raw = read_user_input()
if raw is None:        # /cancel —— 跳过本轮
    continue
user_input = raw.strip()
if not user_input:     # 空输入过滤
    continue
... 走 quit / handle_slash_command / chat(user_input)
```

`/cancel` 返回 `None` 让 `main_loop` 跳过本轮——**不调 `chat`，不写任何 control event**。这保证用户在 `awaiting_user_input` 态下可以"算了我重新想想"而不污染状态机。

### 为什么不上 bracketed-paste 终端模式

现代终端支持 `\e[200~` / `\e[201~` 标记区分粘贴和键入，理论上可以无需显式触发。但：
- 不是所有终端都支持
- 脚本管道（CI / 自动化）下会失效
- 显式协议（`/multi` / 围栏）更明确、更跨环境稳定

权衡之后选了显式协议。

详见 ROADMAP Block 4.4。

---

## 14. 测试覆盖（关注点速览）

当前 `tests/` 已正式纳入版本管理（删 `.gitignore: tests/` 后入仓），约 **120 passed / 4 xfailed**。

### 关注点

| 关注点 | 主要测试文件 |
|---|---|
| Anthropic API 投影合规（messages 形态） | `test_api_projection.py` |
| `tool_use ↔ tool_result` 配对契约 + 占位补齐 | `test_tool_pairing.py` |
| `task.status` 状态机不变量 + RESETTABLE_FIELDS 保险杠 | `test_state_invariants.py` |
| Plan 确认 / step 确认 / tool 确认三种 awaiting 流转 | `test_confirmation_flow.py` |
| 元工具完成协议（mark_step_complete + 阈值 + outstanding 注入） | `test_meta_tool.py`（前 5 条） |
| **request_user_input 元工具求助路径**（含 B 防御清残留 mark） | `test_meta_tool.py`（第 6-7 条） |
| **assistant 普通文本求助兜底（启发式）** | `test_meta_tool.py::test_endturn_with_question_text_triggers_pause` |
| **连续 end_turn 无进展兜底（计数）** | `test_meta_tool.py::test_two_consecutive_endturns_without_progress_trigger_pause` |
| **任意工具调用清零计数器** | `test_meta_tool.py::test_tool_call_resets_endturn_counter` |
| **MAX_LOOP_ITERATIONS 终极兜底**（双层兜底被绕过的场景） | `test_completion_handoff.py::test_max_loop_iterations_terminal_guard_still_fires_when_double_layer_bypassed` |
| 多字段用户回复完整入 messages（step_input 渲染层不丢字段） | `test_meta_tool.py::test_multi_field_user_reply_fully_persisted_to_messages` |
| **CLI 多行输入协议（`/multi` / `/done` / `/cancel` / 围栏 / EOF 鲁棒）** | `test_main_input.py` |
| 长任务多轮压缩穿插 | `test_long_running.py` |
| "为了捕 bug 而写"的边界场景 | `test_hardcore_scenarios.py` + `test_hardcore_round2.py` |

### 4 个 xfail（已识别但暂不修的设计债）

- `test_parallel_tool_use_result_order_matches_declaration`：并行 tool_use 遇 awaiting 时结果顺序与声明顺序相反
- `test_consecutive_rejections_is_actually_used`：`consecutive_rejections` 字段是 dead code
- `test_plan_feedback_does_not_accumulate_goal_string_indefinitely`：plan feedback 单向累加，goal 字符串无限膨胀
- `test_user_switches_topic_mid_task`：awaiting_step 时用户换话题被当 feedback，goal 被错误拼接

xfail 不是"测试失败"——是**有意保留**让"未来打算修但现在不修"这件事在每次跑测试时都被看见。

---

## 附录 A · 推荐的阅读顺序

如果你要从头读懂这份代码，建议按以下顺序：

1. **先把 `state.py` 读透**。它是所有模块共享的语言，不读它后面全是黑话。
2. **再读 `plan_schema.py`**。很短，但定义了 planner 和 context_builder 的契约。
3. **读 `conversation_events.py` + `tool_registry.py`**。这两个是工具层的语法。
4. **读 `context_builder.py` 的 `build_execution_messages`**。这是模型"看到的世界"的构造函数。
5. **读 `core.py::chat()` 的分支逻辑**。此时你应该能看懂每个分支为什么那样排。
6. **读 `response_handlers.py` 的三个 handler**。重点看 `_serialize_assistant_content`。
7. **读 `tool_executor.py` 的三种 confirmation 分支**。
8. **读 `confirm_handlers.py`** 的三个 handler，对照状态机图。
9. **读 `memory.py::compress_history` + `_find_safe_split_index`**。
10. **最后读 `session.py` + `main.py`**。这些是外壳，依赖全是下层。

## 附录 B · 读代码时的自问清单

读每个函数时，问自己这些问题：

- **它属于哪一层**？（看附录 A 的分层）
- **它读写 state 的哪些字段**？（知道它的 side effect 范围）
- **它在哪些 stop_reason / status 下会被调用**？（定位它在状态机中的位置）
- **它的失败模式是什么**？（比如模型返回格式坏了、tool 抛异常、checkpoint 损坏）
- **为什么它在这里 save_checkpoint（或不 save）**？（理解落盘时机）
- **它处理的是业务工具还是元工具？**（遇到 tool 相关代码时，这个维度决定要不要写 messages / 补 tool_result）

---

**最后一句话**：这份文档写出来是路线图，不是地图本身。地图在代码里。祝你读得愉快。

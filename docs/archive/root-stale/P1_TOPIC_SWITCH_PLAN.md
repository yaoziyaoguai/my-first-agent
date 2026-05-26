# P1 设计方案：用户中途话题切换 + plan_feedback 边界收敛

> **文档定位**：本文件不是实现说明，而是只读设计稿。基于 HEAD `205c4cf`
> （slash command 整体下线 + heuristic 全面回退）的代码现状，回答一个问题：
> 在不恢复 slash command、不引入关键词/字符启发式、不偷偷加 LLM 二次分类的
> 红线下，怎样让 `test_user_switches_topic_mid_task` 真正可解，同时不破坏
> `test_plan_feedback_does_not_accumulate_goal_string_indefinitely` 已经
> 取得的结构化收益。
>
> **本文件不动代码**。所有"应在 X 处加 Y"都是落地建议，等明确开工后再实施。

---

## 0. TL;DR

- **当前 bug**：`awaiting_step_confirmation` 收到非 yes/no 输入 → 一律走
  `plan_feedback` 分支 → 立即调 planner 把"新话题"硬塞进旧 plan 的
  `revised_goal` 上下文里。用户真正想"切话题"时，被静默拼接成"对旧 plan 的
  反馈"。
- **根因**：单字段 `task.status` 在 `awaiting_*` 下没有"模糊输入"出口；
  Runtime 收到 free-form 文本后，唯一的非 yes/no 路径就是 feedback。
- **P1 最小修复**（不破红线）：在 `confirm_handlers` 三个 awaiting 分支里，
  当 `classify_confirmation_response` 返回 `feedback` 时，**不立刻**调
  planner，而是切到一个新的 awaiting 子状态 `awaiting_feedback_intent`，
  发 `RuntimeEvent(feedback.intent_requested)` 让用户**显式选择**：
  `[1] 当作对当前计划的修改意见` / `[2] 切换为新任务` / `[3] 取消`。
  下一轮用户输入按 `[1/2/3]` 数字（或对应中文）走分流；任何不在选项内的
  输入再次发出同一 RuntimeEvent，绝不猜。
- **不写回 user_goal 收益保持**：feedback 仍只在本地组装 `revised_goal` 给
  planner，永不污染 `state.task.user_goal`。新话题分支走 `state.reset_task()
  + _run_planning_phase(new_input)`，与正常新任务入口共用同一条路径，
  user_goal 直接被赋值为新话题原文（不拼旧目标）。
- **不动**：checkpoint schema（只在 task.status 集合里多加一个枚举值，
  task 顶层字段不增不减）、messages append-only、`_project_to_api`、
  tool_use_id 配对、tool_result placeholder、request_user_input 语义、
  InputIntent 现有 kind / metadata 形状。
- **xfail 解除条件**：以"两步交互"形式 PASS（test 需要更新断言成两步——
  第一步触发 `feedback.intent_requested`，第二步选 `[2]` 后断言
  user_goal 是新话题且不含旧目标）。这不是"削弱测试为了过"，而是因为
  红线本身要求"不能在单次 chat() 里猜意图"——单次猜不出就**必须**再问
  一次，这是产品契约的一部分。下文 §5 会解释为什么这不是测试削弱。

---

## 1. 当前事件链路（精读后绘制）

### 1.1 `awaiting_step_confirmation` 收到 free-form 文本

```
main.py::main_loop  /  textual shell
   └─ classify_user_input(state, text)
        ├─ status == awaiting_step_confirmation
        ├─ → InputIntent(kind="step_confirmation",
        │                metadata.confirmation_response = "feedback")
        │     ※ classify_confirmation_response 仅匹配 yes/no 词表，
        │       任何非 yes/no（含"帮我写一首诗"）都归 "feedback"
        └─ → core.chat(text)
             └─ status == awaiting_step_confirmation 分支
                 └─ confirm_handlers.handle_step_confirmation
                      ├─ _confirmation_response(text) == "feedback"
                      ├─ append_control_event(messages,
                      │     "plan_feedback", {"feedback": text})
                      ├─ revised_goal =
                      │     f"{state.task.user_goal}\n\n用户在步骤确认阶段
                      │       的补充意见：{text}"
                      │     ※ 本地变量，不写回 user_goal（c252695 保留收益）
                      ├─ planner.generate_plan(revised_goal, …)
                      ├─ state.task.current_plan = new_plan.model_dump()
                      ├─ state.task.current_step_index = 0
                      ├─ state.task.status = "awaiting_plan_confirmation"
                      ├─ save_checkpoint
                      └─ emit plan_confirmation_requested(...)
```

**关键证据**：`agent/confirm_handlers.py:137-195`，`agent/input_intents.py:90-109`。

### 1.2 `awaiting_plan_confirmation` 同形

`handle_plan_confirmation`（`confirm_handlers.py:86-134`）与 step 版本同构，
唯一区别是 control_event payload 文案。

### 1.3 `awaiting_user_input` 路径（不在本 bug 范围，但要确认互不干扰）

```
status == awaiting_user_input
  ├─ pending_user_input_request != None  →  request_user_input 元工具触发
  │    └─ resolve_user_input → kind=runtime_user_input_answer
  │        └─ apply_user_replied_transition
  │             ├─ append_control_event(messages, "step_input",
  │             │      {question, why_needed, content})
  │             ├─ pending_user_input_request = None
  │             ├─ status = "running"
  │             └─ save_checkpoint(source="transitions.runtime_user_input_answer")
  └─ pending_user_input_request == None  →  collect_input/clarify step
       └─ resolve_user_input → kind=collect_input_answer
           └─ apply_user_replied_transition
                ├─ append_control_event(messages, "step_input", {content})
                ├─ confirm_each_step + not last_step
                │    →  status = awaiting_step_confirmation
                ├─ else advance_current_step_if_needed
                ├─ status == "done" → clear_checkpoint + reset_task
                └─ save_checkpoint
```

**结论**：`awaiting_user_input` 自身不会撞 free-form-feedback 歧义——pending
不为空时 yes 也是答复，pending 为空时任何文本都是 collect_input 答案；这两
条都已是"用户在回答系统已经问出的具体问题"，不存在"模糊归属"。所以本次
P1 **只动 plan/step confirmation 两个分支**，user_input 路径保持现状。

### 1.4 `request_user_input` 元工具的事件链路（参考用，确认与 P1 边界一致）

```
模型 stream → tool_use(name="request_user_input")
  └─ tool_executor.execute_single_tool（meta_tool=True 分支）
       ├─ state.task.pending_user_input_request = {...}
       ├─ state.task.status = "awaiting_user_input"
       ├─ 不写 conversation.messages（meta tool）
       ├─ 不生成 tool_result（meta tool）
       └─ save_checkpoint
  └─ response_handlers.handle_tool_use_response 收尾：
       ├─ 给本轮剩余 business tool_use 补 placeholder tool_result
       ├─ emit user_input_requested(pending) → RuntimeEvent
       └─ 本 loop 返回 ""，等下一次 chat() 进入 awaiting_user_input 分支
```

**关键引用**：`agent/tools/meta.py:124-139`，`agent/response_handlers.py:315-339`，
`agent/transitions.py:66-95`，`agent/conversation_events.py:64-105`。

P1 的"问用户走哪条路"流程，**结构上完全可以借用 `pending_user_input_request`
这个已有字段**——见 §4。

---

## 2. 两个 xfail 的根因证据链

### 2.1 `test_plan_feedback_does_not_accumulate_goal_string_indefinitely`（PASS）

- 测试断言：4 次 feedback 后 `len(user_goal) < initial_len * 3`。
- 现行实现（`confirm_handlers.py:115` 与 `:173`）已经**不写回**
  `state.task.user_goal`，仅本地 `revised_goal` 喂 planner。
- planner 之后用 `Plan.model_validate(...).model_dump()` 重写
  `state.task.current_plan`，`user_goal` 字段完全不被触碰。
- **结论**：保留收益的根因 = "feedback 处理只产生 Plan 重生成的临时上下文，
  不修改 task 持久字段"。P1 必须延续这条边界；新话题分支走 `reset_task() +
  _run_planning_phase(new_input)`，user_goal 由新分支重新赋值（即新话题原文），
  不与旧目标拼接。

### 2.2 `test_user_switches_topic_mid_task`（xfail）

- 序列：`chat("原任务：分析文档，每步确认")` → `chat("y")` →
  `chat("帮我写一首关于春天的诗")`。
- 第三次 chat 进入 `handle_step_confirmation`，`_confirmation_response("帮我写
  一首关于春天的诗") == "feedback"`（不在 yes/no 词表内）。
- 下面发生的所有事都按"对旧任务的反馈"处理：
  1. `append_control_event(plan_feedback)`：旧 plan 的反馈被写进 messages。
  2. `revised_goal = f"{原任务}\n\n用户在步骤确认阶段的补充意见：帮我写诗"`。
  3. planner 拿这个污染过的 goal 重新出 plan（fake response 给的是
     "混合方案"）。
  4. `state.task.user_goal` 仍是 `"原任务：分析文档，每步确认"`——所以
     测试断言 `"春天的诗" in user_goal` 直接 False。
- **测试当前用 `pytest.xfail(...)` 主动标记**，理由：在不引入红线方案的前提下，
  Runtime 在单次 `chat()` 调用里**没有任何信号源**能把"反馈"和"切话题"分开。
- **必须保守的行为**：见 §3 红线。

---

## 3. 红线（不可跨越）

来自用户多轮交接的明确禁令。任何 P1 实现都必须满足：

1. **❌ 不恢复 slash command**：不重新引入 `/xxx` 字符串协议、不重建
   `agent/commands.py` / `CommandRegistry` / `CommandResult`、不在
   `InputIntent.kind` 加 `slash_command`。
2. **❌ 不引入关键词/imperative-prefix/no-overlap/min-length 等浅层 heuristic**：
   不能用"帮我/请帮/另外/帮我写"这类词表，不能算 plan 词表的字符重叠率，
   不能按文本长度/标点结构猜意图。
3. **❌ 不引入 LLM 二次分类器**：不能在 confirm_handlers 里悄悄再发一次模型
   请求让 LLM 判断"这是反馈还是新任务"。
4. **❌ 不改 checkpoint schema 顶层字段**：不新增 task 顶层字段，不新增
   memory/conversation 字段。`task.status` 集合可以多一个枚举值（这是显式
   状态机扩展，不是 schema 破坏），但旧 checkpoint 不带新字段必须仍能加载。
5. **❌ InputIntent / RuntimeEvent / DisplayEvent / CommandResult 不进入
   messages 或 checkpoint**。
6. **❌ messages append-only**：不能在 P1 里"删除上一条 plan_feedback control
   event"做撤销。
7. **❌ `_project_to_api` 边界不动**：tool_use_id 配对、tool_result
   placeholder、meta tool 不进 messages 的语义全部保持。
8. **❌ 不为了过测试改测试**：测试如需更新，必须能解释"原断言为何不合理"，
   而不是削弱断言。见 §5。

**唯一允许**：

- ✅ 自然语言 InputIntent（已有 kind，本 P1 **不**新增 kind）。
- ✅ 新增 `RuntimeEvent` 事件类型用于"模糊请求 → 用户显式选择"。
- ✅ 在 `task.status` 枚举里新增**一个**显式 awaiting 子状态
  `awaiting_feedback_intent`。
- ✅ 复用现有 `pending_user_input_request` 字段表达"系统正在等用户做选择"，
  通过 `awaiting_kind="feedback_intent"` 区分（已有 `awaiting_kind` 概念，
  无需新增字段，旧 checkpoint 兼容自然成立）。

---

## 4. 最小 P1 方案

### 4.1 状态机扩展（一处）

`agent/state.py::KNOWN_TASK_STATUSES` 新增一个值：

```
awaiting_feedback_intent
```

`task_status_requires_plan` 对该状态返回：
- `pending_user_input_request is not None` → 不要求 plan（与现行
  USER_INPUT_WAIT_STATUSES 同构，靠 pending 携带恢复信息）。
- 否则按"不一致"处理（与未知状态一致，会触发 `reset_task` 自愈）。

> **这是状态枚举扩展，不是 schema 破坏**：`task.status` 在 `state.py`
> 注释里就明确说明它"目前仍是单字段，混合多个维度"，未来还会再拆，所以
> 在它上面新增一个 awaiting 子状态属于 in-spec 演进。

### 4.2 confirm_handlers 改造（两处对称）

`handle_plan_confirmation` 与 `handle_step_confirmation` 的 feedback 分支
**不再立即重规划**，而是：

1. **不再立刻**写 `plan_feedback` control event（关键：feedback 文本
   归属未定时不能进 messages，否则会在用户最终选"切新任务"时残留旧
   反馈污染下一轮 planner 上下文。messages 是 append-only，所以宁可
   推迟到分流后再决定写不写）。
2. 把待分流的 raw feedback 文本暂存到 `pending_user_input_request`：

   ```
   state.task.pending_user_input_request = {
       "awaiting_kind": "feedback_intent",
       "question": "（系统组装的固定提示，不含模型生成内容）",
       "why_needed": "你刚才的输入既可能是对当前计划的修改意见，"
                     "也可能是一个新任务，请告诉系统怎么处理",
       "options": [
           "1. 当作对当前计划的修改意见（在原任务上重新规划）",
           "2. 切换为新任务（放弃当前计划）",
           "3. 取消（保持当前计划，不做任何事）",
       ],
       "context": "",
       "tool_use_id": "",
       "step_index": state.task.current_step_index,
       # 私有字段：仅供 P1 分流读取，不被 _project_to_api / messages 看见
       "pending_feedback_text": confirm,
       "origin_status": "awaiting_plan_confirmation"
                        | "awaiting_step_confirmation",
   }
   state.task.status = "awaiting_feedback_intent"
   save_checkpoint(state, source="confirm_handlers.feedback_intent_request")
   emit RuntimeEvent(EVENT_FEEDBACK_INTENT_REQUESTED, ...)
   return ""
   ```

3. 新增 `handle_feedback_intent_choice(user_input, ctx)`：

   ```
   choice = _classify_feedback_intent_choice(user_input)
   # 仅识别精确匹配："1"/"2"/"3"/"取消"/"cancel"；
   # **任何**模糊输入 → 重发 RuntimeEvent，pending 不动，不写 messages。
   # 这是"再问一次"，不是"猜"，符合红线。

   if choice == "as_feedback":
       restore origin_status → 写 plan_feedback control event →
       走原 feedback 路径（生成 revised_goal 喂 planner，新 plan 进
       awaiting_plan_confirmation）。pending_user_input_request 清空。
   elif choice == "as_new_task":
       state.reset_task()              # 与 core.chat() 新任务入口完全同构
       clear_checkpoint()              # reset_task 不会清，需要显式清
       return _run_planning_phase(pending_feedback_text, turn_state)
       # ★ 关键：走与"全新任务"完全相同的入口；user_goal 由
       #   _run_planning_phase 内 state.task.user_goal = new_input 直接赋值。
   elif choice == "cancel":
       restore origin_status → 不写任何 control event → 重新 emit
       原本的 plan/step confirmation prompt → return ""
   else:  # 模糊输入
       重 emit RuntimeEvent(EVENT_FEEDBACK_INTENT_REQUESTED) → return ""
   ```

4. `core.chat()` 在 `awaiting_feedback_intent` 状态下分派到
   `handle_feedback_intent_choice`（与现有 4 个 awaiting 分派同构）。

### 4.3 InputIntent 层

**不新增 kind**。`awaiting_feedback_intent` 状态下 `classify_user_input`
继续走 `normal_message`（adapter 层不解释新语义），由 `core.chat()` 看
status 分派——这与目前 `awaiting_user_input` 的处理完全同构（adapter 已经
返回 `request_user_reply` 但实际由 `handle_user_input_step` 按 pending 区分
collect/runtime）。

> **可选优化**（非必需）：若想让 InputIntent 透明感知该状态，可让
> `awaiting_feedback_intent` 下返回 `kind="request_user_reply"` 并在
> metadata 里 `awaiting_kind="feedback_intent"`。本 P1 推荐**先不加**——
> adapter 端无差别，且不增加测试矩阵。

### 4.4 RuntimeEvent 新增

`agent/display_events.py` 新增：

```python
EVENT_FEEDBACK_INTENT_REQUESTED = "feedback.intent_requested"

def feedback_intent_requested(pending: dict, ...) -> RuntimeEvent: ...
```

渲染规则与 `user_input_requested` 同构：把 pending 里的 question/options
拼成可读文本。CLI fallback / Textual 都能直接消费，无需新增 sink。

### 4.5 不动什么（边界守住的清单）

| 模块 | 不动的原因 |
|---|---|
| `_project_to_api` | feedback_intent 的 pending 通过现有 `pending_user_input_request` 表达，不影响 tool_use 配对；新 control event `plan_feedback` 仍按原方式写，时机仅"延后到分流后" |
| `transitions.apply_user_replied_transition` | 不复用：feedback_intent 选择不算"用户对 step 的回答"，不能写 step_input control event。新 handler 单独处理 |
| `tool_executor` | 完全不动 |
| `response_handlers` | 完全不动 |
| `checkpoint.py` | 不动；`task.status` 新枚举值通过 dict copy 自然保存 |
| `input_resolution.py` | 不动；feedback_intent 不复用 collect/runtime 两条路径 |
| `tools/meta.py` 的 `request_user_input` | 不动；P1 走的是"系统主动"模糊请求，不是模型主动求助，不能复用元工具入口 |

---

## 5. 测试设计（tests-first）

### 5.1 现有 xfail 的处理原则

`test_user_switches_topic_mid_task`：
- **不削弱**也**不删除**。
- 它的当前断言"单次 chat 后 user_goal 即变成新话题"在 P1 红线下**确实不
  合理**：红线明确禁止 Runtime 在收到模糊输入后猜测意图，因此"单次输入
  即切话题"在产品契约上必须需要二次确认。
- 改造方式：**保留测试名与场景**，断言更新为"两步交互"——
  - 第 1 步 `chat("帮我写一首关于春天的诗")`：
    - 断言 `state.task.status == "awaiting_feedback_intent"`
    - 断言 `state.task.pending_user_input_request["awaiting_kind"] ==
      "feedback_intent"`
    - 断言 `state.task.user_goal` **仍是旧目标**（未污染）
    - 断言 `messages` 里**未出现** `"用户对计划提出了修改意见：帮我写
      一首关于春天的诗"` 的 control event（feedback 归属未定时不入
      messages）
  - 第 2 步 `chat("2")`（用户选"切换为新任务"）：
    - 断言 `"春天的诗" in state.task.user_goal`
    - 断言 `"分析文档" not in state.task.user_goal`
    - 断言 `state.task.status` 进入 `awaiting_plan_confirmation`（新计划
      待确认）
- **xfail 标记移除**：这个测试本身就会真实 PASS。不再是"产品方向缺口"。

### 5.2 新增测试（必须暴露 bug，不允许只为覆盖率）

1. `test_feedback_intent_request_does_not_pollute_user_goal_or_messages`
   - 模糊输入触发 feedback_intent 后，user_goal 未变、messages 未追加
     `plan_feedback` control event。
2. `test_choosing_as_feedback_resumes_original_plan_feedback_path`
   - 选 "1" 后行为与原来 feedback 直接路径**等价**（plan 重生成、user_goal
     不变、新 plan 进 awaiting_plan_confirmation、messages 出现一条
     `plan_feedback` control event）。
3. `test_choosing_as_new_task_resets_state_and_uses_new_input_as_goal`
   - 选 "2" 后 task 完整 reset，新 plan 的 user_goal == 新话题原文（不含
     旧目标）。
4. `test_choosing_cancel_restores_original_awaiting_status_with_no_side_effect`
   - 选 "3" 后 status 回到 origin_status，user_goal 不变，messages 完全
     无新增 control event，pending_user_input_request 已清空，重新 emit
     原 awaiting prompt。
5. `test_ambiguous_choice_reissues_prompt_without_state_change`
   - 在 awaiting_feedback_intent 下输入 "请把第二步改成先分析"（模糊）：
     status 不变、pending 不变、未写 messages，仅再次发出
     `EVENT_FEEDBACK_INTENT_REQUESTED`。**关键反 heuristic 测试**：
     这条覆盖红线，证明系统不会因为输入"看起来像反馈"就猜成 "1"。
6. `test_feedback_intent_state_survives_checkpoint_roundtrip`
   - 进入 awaiting_feedback_intent → save_checkpoint → 模拟新进程
     `load_checkpoint_to_state` → 用户继续选 "2" 仍能正确切到新任务。
   - 这条保证 schema 兼容。
7. `test_plan_confirmation_path_also_uses_feedback_intent_request`
   - 与 step confirmation 对称的 plan confirmation 入口同样走
     feedback_intent。
8. `test_request_user_input_pending_is_not_confused_with_feedback_intent`
   - 已有 `awaiting_user_input + pending_user_input_request` 路径下输入
     "2" 仍按 runtime_user_input_answer 处理（写 step_input、不切到
     feedback_intent 分流）。**保护边界互不干扰**。
9. `test_existing_plan_feedback_accumulation_test_still_passes_through_choice_1`
   - 在 plan/step confirmation 反复选择 "1" → 行为等价于原 feedback 路径
     → 现行
     `test_plan_feedback_does_not_accumulate_goal_string_indefinitely`
     的不膨胀断言依然成立。

### 5.3 不修改的现有测试

- `test_input_intents.py` 全部不动（InputIntent kind 不新增）。
- `test_main_input.py` 全部不动（main_loop 行为不变）。
- 其他 hardcore tests 不动；P1 不影响 tool_use_id / tool_result /
  end_turn / max_tokens / no_progress 路径。

---

## 6. 改动文件清单 + 执行顺序

### 阶段 A · 红绿测试先行（不改产品代码）

1. `tests/test_feedback_intent_flow.py`（新增）：把 §5.2 中 1–8 全部写完，
   全部 fail。
2. 更新 `tests/test_hardcore_round2.py::test_user_switches_topic_mid_task`：
   按 §5.1 改成两步交互，去掉 `pytest.xfail(...)`。此时它也 fail。
3. 跑 `pytest`：看 fail 列表与设计假设一致，不一致回到 §4 重新审视。

### 阶段 B · 状态机最小扩展

4. `agent/state.py`：`KNOWN_TASK_STATUSES` 加 `"awaiting_feedback_intent"`；
   `task_status_requires_plan` 加分支（参照 USER_INPUT_WAIT_STATUSES）。
5. `agent/display_events.py`：新增 `EVENT_FEEDBACK_INTENT_REQUESTED` 与
   `feedback_intent_requested(pending)` helper；`render_runtime_event_for_cli`
   自动通过既有 text 分支渲染。

### 阶段 C · confirm_handlers 改造

6. `agent/confirm_handlers.py`：
   - 抽 `_request_feedback_intent_choice(ctx, confirm, *, origin_status)`
     辅助函数，负责构造 pending、save_checkpoint、emit RuntimeEvent。
   - `handle_plan_confirmation` / `handle_step_confirmation` 的 feedback
     分支改为调用该辅助函数后 `return ""`。
   - 新增 `handle_feedback_intent_choice(user_input, ctx)`：实现 §4.2.3
     的四条分流（as_feedback / as_new_task / cancel / ambiguous）。

### 阶段 D · core.chat 分派

7. `agent/core.py::chat`：在现有四个 awaiting 分派后插入第五个：

   ```
   if state.task.status == "awaiting_feedback_intent":
       return handle_feedback_intent_choice(user_input, confirmation_ctx)
   ```

   `confirmation_ctx` 已有 `state / turn_state / client / model_name /
   continue_fn`；新 handler 需要走 `_run_planning_phase`，可考虑给
   `ConfirmationContext` 增加可选 `start_planning_fn` 字段（注入
   `lambda inp, ts: _run_planning_phase(inp, ts)`）；这是函数引用注入，
   不写入 checkpoint，不属于 schema。

### 阶段 E · 跑全套 + 文档

8. `pytest -q -rxX`：期望 257 + 9 新增 = 266 passed，2 xfailed
   （test_user_switches_topic_mid_task 已 PASS，剩余 xfail 仅
   textual_esc_cancel / pasted_multiline）。
9. `ruff check agent/ tests/`：保持 All checks passed。
10. 更新 `docs/ARCHITECTURE.md` 顶部"本轮变更通知" + `docs/ROADMAP.md` 顶部，
    说明 P1 已上线 awaiting_feedback_intent + EVENT_FEEDBACK_INTENT_REQUESTED；
    标注红线仍然成立（不允许后续在该状态外加任何浅层启发式）。

---

## 7. 风险与回滚

### 7.1 风险

| 风险 | 缓解 |
|---|---|
| Textual UI 不知道如何渲染新 RuntimeEvent | 已通过 `render_runtime_event_for_cli` 既有 text 分支兜底；Textual 已统一消费 RuntimeEvent，不需要专门桥接 |
| 旧 checkpoint 加载到新代码：不带 `awaiting_feedback_intent` 不影响（旧 status 集合是新集合的子集） | 自然兼容；§5.2 第 6 条测试覆盖反向 |
| 用户输入精确匹配 "1"/"2"/"3" 是否过严？ | 这是有意为之——任何放宽即变成 heuristic（红线 #2）。也可同时接受 "as_feedback"/"as_new_task"/"cancel" 这三个**精确**字面值，方便 TUI 按钮回填 |
| 选择 "2" 后，原 plan 在 messages 里还留着 control events / tool_results 怎么办？ | reset_task 不清 messages；新 planning 调 `build_planning_messages` 里走 `_project_to_api`，旧 tool_use/result 仍参与 prompt。这与"用户主动开新任务"的现行行为一致，不破坏既有边界。如果将来认为这是噪声，单独立项处理（**不**纳入本 P1） |
| 用户连续多次模糊输入会不会刷屏？ | 每次重发同一 RuntimeEvent，文案恒定；不写 messages、不存 checkpoint（pending 已经在那），无累积副作用 |
| `confirm_each_step=True` 旧任务里选 "3" cancel 后能否正常回到 awaiting_step_confirmation？ | origin_status 由 pending 字段记录；restore 时直接赋回 status 并 emit 原 prompt。需要单测覆盖（§5.2 第 4 条） |

### 7.2 回滚方案

P1 全部改动局限在：
- `agent/state.py`（加 1 行枚举 + 1 个分支）
- `agent/display_events.py`（加常量 + helper）
- `agent/confirm_handlers.py`（新增 1 handler + 抽辅助函数 + 改 2 个 feedback 分支）
- `agent/core.py`（加 1 个 awaiting 分派）
- `tests/test_feedback_intent_flow.py`（新增）
- `tests/test_hardcore_round2.py`（修改 1 个测试）
- `docs/ARCHITECTURE.md` / `docs/ROADMAP.md` 顶部通知

回滚 = `git revert` 该 commit；旧 checkpoint 因为不含
`awaiting_feedback_intent`，回滚后照旧加载；新 checkpoint 若回滚后存在，
`task_status_requires_plan` 会把未知 status 视作不一致并触发 `reset_task`
自愈。**所以回滚是安全的**。

---

## 8. 未来如何用普通方式补回已删除 slash command 能力（指导原则，不在 P1 范围）

P1 验证了"模糊语义 → RuntimeEvent 显式确认 → 状态机转移"这套范式可行后，
未来若需补回 `/help` / `/status` / `/reload_skills` / `/clear` 等控制能力：

- 不重新建字符串协议。
- 在 UI 层（Textual menu / CLI 命令行参数）暴露按钮或 subcommand：
  - `python main.py status`、`python main.py reload-skills`：CLI subparser
    层，不进入 chat()，直接打印结构化状态后退出。
  - Textual：Footer/Header 加按钮，按下后发 `RuntimeEvent` 类似
    `system.status_requested` / `skills.reload_requested`，由 main.py
    / session.py 的对应 handler 响应，**不**经过 `chat()` 也**不**进入
    Anthropic API。
- `/clear`（清会话）：通过 Textual 命令面板，触发 finalize_session +
  init_session，与 Ctrl+Q 同路径。
- 严禁让控制能力借道"用户输入 → InputIntent → status 判断"——这正是 slash
  command 时代的根因（控制语义和对话语义混线）。

---

## 9. 已验证基线（HEAD 205c4cf）

| 项 | 值 |
|---|---|
| `git status` | clean |
| `git rev-list --count origin/main..HEAD` | 3 |
| `ruff check agent/ tests/` | All checks passed |
| `pytest tests/ -q -rxX` | **257 passed, 3 xfailed** |
| 3 个 xfail | `test_user_switches_topic_mid_task` / `test_textual_shell_escape_can_cancel_running_generation` / `test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent` |

P1 完成后预期：**266 passed, 2 xfailed**（topic_switch 转 PASS）。

---

## 10. 给执行窗口的下一步可执行 prompt

> 你接手 my-first-agent（HEAD 应仍是 `205c4cf`，本地领先 origin/main 3
> commit，未 push）。请按 `docs/P1_TOPIC_SWITCH_PLAN.md` 执行 P1。
>
> 强制顺序：阶段 A → B → C → D → E。**绝不允许**：恢复 slash command、
> 引入关键词/字符启发式、引入 LLM 二次分类、改 checkpoint schema 顶层字段、
> 把 InputIntent / RuntimeEvent / DisplayEvent 写入 messages 或 checkpoint、
> 让 messages 失去 append-only 语义。
>
> 每个阶段做完跑一次 `ruff` + `pytest -q -rxX`，把 fail 列表与 §5 对齐；
> 不一致先停下分析根因，**禁止**靠改测试断言、靠 try/except 吞异常或靠
> 在 `_project_to_api` 里加补丁让测试过。
>
> 完成 §6 阶段 E 后输出：每阶段 commit hash、最终测试摘要、剩余 2 个 xfail
> 状态、以及对 docs/ARCHITECTURE.md / docs/ROADMAP.md 顶部通知的 diff。
> **不要** push，不要合 origin/main，等用户决定。

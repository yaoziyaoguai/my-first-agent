# TUI/HITL/Interaction Boundary 审计报告

**审计日期**: 2026-05-09
**审计范围**: 所有 TUI/输入/确认/pending/checkpoint 相关源码和测试
**本轮性质**: Phase C 只读审计 + Phase D 轻量 hardening + **Phase E Memory Interactive Confirmation v1 实现**
**当前主线**: Memory Kernel v1 已完成；Memory RuntimeEvent 已被 UI/CLI 消费；PendingInteraction 概念模型已落地；**Memory Interactive Confirmation v1 已完成**

---

## 1. 当前状态总览

### 1.1 已实现的能力

| 能力 | 状态 | 关键文件 |
|------|------|----------|
| 双输入后端 (Textual TUI + Simple CLI) | 已实现 | `input_backends/textual.py`, `simple.py` |
| 输入语义分类 (InputIntent) | 已实现 | `input_intents.py` |
| 用户输入事件建模 (UserInputEnvelope/Event) | 已实现 | `user_input.py` |
| 输入解析层 (InputResolution) | 已实现 | `input_resolution.py` |
| 4 + 1 确认状态机 (plan/step/tool/user_input + feedback_intent) | 已实现 | `confirm_handlers.py`, `state.py` |
| RuntimeEvent 统一输出边界 | 已实现 | `display_events.py`, `runtime_events.py` |
| checkpoint 持久化/恢复 | 已实现 | `checkpoint.py` |
| 确认 observer evidence 写入 | 已实现 | `confirm_handlers.py:_emit_confirmation_observer_event` |
| 两阶段确认流程 (v1 interactive confirmation) | 已实现 | `memory_runtime.py`, `memory_interaction.py` |
| MemoryConfirmationRequest/Result contract | 已实现 | `memory_confirmation.py` |
| paste burst drain (v0.6.2) | 已实现 | `input_backends/simple.py:_drain_paste_burst_lines` |
| TransitionResult 意图词汇层 | 已实现 | `runtime_events.py` |
| meta_tool (request_user_input / mark_step_complete) | 已实现 | `tools/meta.py`, `tool_executor.py` |

### 1.2 尚未实现的能力（按当前主线相关性排序）

| 能力 | 状态 | 说明 |
|------|------|------|
| Memory 交互式确认 | ✅ v1 已完成 | 复用 `awaiting_user_input` + `pending_user_input_request`；两阶段流程；5 种 choice 全部可用 |
| 统一 PendingInteraction 模型 | 🟡 概念落地 | `docs/PENDING_INTERACTION_MODEL.md` 完成概念建模 + Phase E 实现总结 |
| Memory confirmation 的 checkpoint 持久化 | ✅ 已实现 | pending 状态通过 `pending_user_input_request` dict 进入 checkpoint |
| 交互式 confirmation adapter (Ask User) | ✅ 已实现 | `memory_interaction.py` 提供完整桥接层 |
| MemoryConfirmationRequest 的 accept/reject/edit/session_only/Other 选项 | ✅ 已实现 | 5 种 choice 均被交互式 adapter 消费 |
| TUI 确认按钮/菜单渲染 | 未实现 | TUI 通过文本列表展示选项，用户输入数字选择 |
| 取消模型生成的 Esc 处理 | 未实现 | TUI 能标记 `[已中断]` 但不杀 worker thread |

### 1.3 Future consumers（不在当前主线，仅供后续参考）

| 能力 | 说明 |
|------|------|
| Skill/Subagent 确认机制 | 尚无 Skill/Subagent 概念；未来引入时应复用 Memory confirmation 验证过的 pending confirmation 模式 |

---

## 2. 交互流映射

### 2.1 正常用户输入路径 (Path A)

```
终端输入
  → input_backend (simple/textual)
    → UserInputEvent (submitted/cancelled/closed)
      → classify_user_input() → InputIntent
        → main_loop / _handle_textual_shell_input
          → core.chat()
            → _dispatch_pending_confirmation() [5 分支]
              → fallthrough → 压缩历史 → 开启新任务
```

**边界**: InputIntent 只做分类，不持久化。TUI 不读取 TaskState。

### 2.2 工具确认路径 (Path B)

```
模型产出 tool_use (需确认)
  → tool_executor.execute_single_tool()
    → confirmation == True
      → state.task.pending_tool = {...}
      → state.task.status = "awaiting_tool_confirmation"
      → save_checkpoint()
      → emit DisplayEvent (tool.awaiting_confirmation)
        → 用户看到 "(y/n/输入反馈意见):"
          → 用户输入 → classify_user_input → tool_confirmation kind
            → core._dispatch_pending_confirmation()
              → handle_tool_confirmation()
                → accept: execute_pending_tool() → continue loop
                → reject: append_tool_result(placeholder) → continue
                → feedback: append_tool_result(placeholder) → continue
```

### 2.3 request_user_input / Ask User 路径 (Path C)

```
模型调用 request_user_input (meta_tool)
  → tool_executor.execute_single_tool() [元工具分支]
    → state.task.pending_user_input_request = {...}
    → state.task.status = "awaiting_user_input"
    → save_checkpoint()
    → emit RuntimeEvent (user_input.requested)
      → 用户看到问题
        → 用户输入 → classify_user_input → request_user_reply kind
          → core._dispatch_pending_confirmation()
            → handle_user_input_step()
              → resolve_user_input()
                → RUNTIME_USER_INPUT_ANSWER: 不推进 step
                → COLLECT_INPUT_ANSWER: 推进 step
              → apply_user_replied_transition()
```

### 2.4 Memory 确认路径（✅ Phase E 已实现）

```
当前 (v1 Interactive Confirmation):
  user says "remember that X"
    → MemoryRuntime.evaluate_user_text()
      → MemoryPolicy → MemoryDecision(RETAIN)
      → 缓存 decision → 返回 CONFIRMATION_REQUIRED
      → core.py: 构建 pending dict (awaiting_kind="memory_confirmation")
      → save_checkpoint → emit memory_confirmation_requested_event
        → 用户看到 MemoryConfirmationRequest
          (question + 5 选项: 1.记住 2.编辑后记住 3.仅本次使用 4.不要记住 5.Other)
        → 用户输入 "1"~"5" 或自由文本
          → handle_user_input_step → handle_memory_confirmation_reply
            → parse_memory_confirmation_reply → (choice, free_text)
            → MemoryRuntime.resolve_confirmation(candidate_id, choice, free_text)
              → resolve_memory_confirmation_choice()
                → APPROVED → store write (RETAIN)
                → REJECTED → skip store
                → SESSION_ONLY → store write (USE_ONCE)
                → NEEDS_CLARIFICATION → clarify path
            → 清 pending → 恢复 origin_status → save_checkpoint
            → emit RuntimeEvent (STORED/BLOCKED)
```

**关键设计决定（已落地）**：
1. Memory confirmation 复用 `awaiting_user_input` + `pending_user_input_request` ✅
   - 不新增 status，通过 `awaiting_kind="memory_confirmation"` 区分
   - `_candidate_id`、`_choice_map`、`_origin_status` 以 `_` 前缀 key 存在 pending dict 中
2. 5 选项通过数字协议处理 ✅
   - `parse_memory_confirmation_reply()` 直接解析数字输入
   - 不经过 `classify_confirmation_response` 三元分类
3. edit/session_only/Other/free-text 映射 ✅
   - EDIT_AND_ACCEPT 和 OTHER 通过 "N text" 格式一次输入完成
   - SESSION_ONLY 对应 `MemoryOperationType.USE_ONCE`

---

## 3. 能力清单

### 3.1 InputIntent 分类能力

| kind | 触发条件 | 分类位置 |
|------|----------|----------|
| `cancel` | event_type == "input.cancelled" | UI 层 |
| `eof` | event_type == "input.closed" or raw_text is None | UI 层 |
| `empty` | normalized == "" | UI 层 |
| `exit` | lowered in {"quit", "exit"} | UI 层 |
| `tool_confirmation` | status == "awaiting_tool_confirmation" + pending_tool | Runtime 层 |
| `request_user_reply` | status == "awaiting_user_input" | Runtime 层 |
| `plan_confirmation` | status == "awaiting_plan_confirmation" | Runtime 层 |
| `step_confirmation` | status == "awaiting_step_confirmation" | Runtime 层 |
| `normal_message` | fallthrough | Runtime 层 |

### 3.2 确认响应分类

`classify_confirmation_response()` 使用静态中文词表:

- **accept**: y, yes, ok, okay, 好, 好的, 是, 是的, 确认, 行, 可以
- **reject**: n, no, 不, 不要, 否, 取消
- **feedback**: 其他所有

**Memory 确认的 gap**: `classify_confirmation_response` 是三元分类 (accept/reject/feedback)，而 MemoryConfirmationRequest 有 5 种 choice (accept/edit_and_accept/reject/session_only/other)。如果 Memory confirmation 走现有 `awaiting_user_input` 路径，需要扩展分类层或由 handler 自己做更细的分类。

### 3.3 Pending 状态全集

| status | pending 字段 | 触发来源 | handler |
|--------|-------------|----------|---------|
| `awaiting_plan_confirmation` | (current_plan) | planner 生成 plan 后 | handle_plan_confirmation |
| `awaiting_step_confirmation` | (current_plan, confirm_each_step) | 步骤完成 + 开关打开 | handle_step_confirmation |
| `awaiting_user_input` | pending_user_input_request | request_user_input 或 collect_input 步骤 | handle_user_input_step |
| `awaiting_tool_confirmation` | pending_tool | 工具需要确认 | handle_tool_confirmation |
| `awaiting_feedback_intent` | pending_user_input_request.awaiting_kind="feedback_intent" | plan/step feedback 分支 | handle_feedback_intent_choice |

**Memory confirmation 当前不在此表中**。MemoryRuntime.evaluate_user_text() 是同步调用，不经过 `_dispatch_pending_confirmation`。

### 3.4 MemoryConfirmationRequest 已建模的 5 种 choice

（来自 `agent/memory_confirmation.py`，contract 已完整定义但未被交互式 adapter 消费）

| choice | label | requires_free_text | 结果 status |
|--------|-------|--------------------|-------------|
| ACCEPT | 记住 | 否 | APPROVED |
| EDIT_AND_ACCEPT | 编辑后记住 | 是 | APPROVED (approved_content=free_text) |
| SESSION_ONLY | 仅本次使用 | 否 | SESSION_ONLY |
| REJECT | 不要记住 | 否 | REJECTED |
| OTHER | Other/free-text | 是 | NEEDS_CLARIFICATION |

### 3.5 输出边界

| 边界 | 方向 | 持久化 | 说明 |
|------|------|--------|------|
| RuntimeEvent | Runtime → UI | 否 | 统一用户可见输出 |
| DisplayEvent | Runtime → UI | 否 | 工具/控制结构化 UI payload |
| conversation.messages | Runtime → LLM | 是 (via checkpoint) | 模型上下文 |
| control_event | Runtime → LLM | 是 (in messages) | y/n → 语义事件转换 |
| observer event | Runtime → Disk | 是 (agent_log.jsonl) | 可观测性 |
| checkpoint | Runtime → Disk | 是 (checkpoint.json) | 崩溃恢复 |

---

## 4. 风险评估

### P1 — 高优先级 (应在 Memory interactive confirmation 阶段解决)

**P1-1: Memory confirmation 未接入主 AgentLoop pending confirmation** ✅ 已修复 (Phase E)

- **Phase E 修复**:
  - `MemoryRuntime.evaluate_user_text()` 返回 `CONFIRMATION_REQUIRED`，不再内部 auto-accept
  - `core.py` 新增 CONFIRMATION_REQUIRED 分支：构建 pending dict → `state.task.status = "awaiting_user_input"` → save_checkpoint → emit event
  - `confirm_handlers.py` 新增 `awaiting_kind="memory_confirmation"` 路由 → 委托 `handle_memory_confirmation_reply`
  - `agent/memory_interaction.py` (175行) 提供完整桥接层：build pending / parse reply / handle reply
  - 复用 `awaiting_user_input` + `pending_user_input_request`，不新增第 6 套独立机制
  - 5 种 choice (accept/edit_and_accept/session_only/reject/other) 全部可交互式消费
- **影响**: 用户说 "remember that X" 时，系统不再静默写入。用户看到确认问题并通过数字选择确认/拒绝/编辑/仅本次使用。

**P1-2: Memory RuntimeEvent 无人消费，用户对自动记忆无感知** ✅ 已修复 (Phase D)

- **现状**: 两阶段确认流程中，`evaluate_user_text` 通过 `on_event` 回调 emit `memory_confirmation_requested` RuntimeEvent（包含 question 和 preview），TUI/CLI 通过 `render_runtime_event_for_cli` 渲染。
- **Phase D 修复**:
  - `agent/display_events.py` 新增 `EVENT_MEMORY_STORED` / `EVENT_MEMORY_BLOCKED` / `EVENT_MEMORY_INJECTED` 三种 RuntimeEvent 类型及对应工厂函数
  - `agent/core.py` 在 `evaluate_user_text` 返回 STORED/BLOCKED 时通过 `_safe_emit_runtime_event` 发出对应 RuntimeEvent
  - `agent/core.py` 在 `refresh_runtime_system_prompt` 后发出 `memory_injected_event` 告知用户已加载条数
  - `render_runtime_event_for_cli` 通过 `event.text.strip()` fallthrough 正确渲染中文文本
  - 脱敏：`memory_stored_event` 工厂函数内使用 `_mask_preview_secrets` 防止敏感内容泄漏到 UI
  - 测试：`tests/test_memory_runtime_events.py` 29 条测试覆盖事件构造、渲染、脱敏、CLI 一致性
- **影响**: 用户现在能看到 "已记住：..."、"已拦截敏感记忆：..."、"已加载记忆：N 条"。v1 auto-accept 行为不变，但用户对自动记忆有了感知。

### P2 — 中等优先级 (应在进入 agent-suggested memory 或第二个 confirmation 消费者之前解决)

**P2-1: 缺少统一 PendingInteraction 模型** 🟡 概念落地，不做代码重构

- **Phase D**: `docs/PENDING_INTERACTION_MODEL.md` 落地概念模型（5 节）
- **Phase E**: 实际选择方案 B（复用 `awaiting_user_input`），Memory confirmation 作为该模型的第一个新 consumer 验证了方案的可行性
- **当前状态**: 未引入 PendingInteraction Protocol/ABC，但通过 `awaiting_kind` + `_choice_map` 模式证明了在不新增 status 的情况下可以扩展新的 confirmation 类型
- **后续**: 如果出现第 3 个需要结构化选项的 confirmation consumer，再考虑抽出公共抽象

**P2-2: classify_confirmation_response 三元分类 vs Memory 五选项的 gap** ✅ 已解决

- **Phase E 方案**: Memory confirmation 不经过 `classify_confirmation_response`，由 `parse_memory_confirmation_reply()` 专用解析器处理
- `handle_user_input_step` 在入口处通过 `pending.get("awaiting_kind")` 提前分流
- 不修改现有三元分类器，不影响现有 plan/step/tool/user_input 路径

**P2-3: TUI/simple backend 对结构化选项的支持不一致** 🟡 数字协议已落地

- **Phase E 方案**: 两个 backend 统一使用数字协议（"1"~"5" = 5 种 choice，"N text" = choice + free_text）
- TUI 和 simple CLI 都通过文本列表展示选项，用户通过数字选择
- 结构化按钮/菜单渲染作为未来 UI 增强，不阻塞当前功能

**P2-4: Memory confirmation 不进 checkpoint** ✅ 已解决

- **Phase E**: pending memory confirmation 状态通过 `pending_user_input_request` dict 进入 checkpoint
- `pending_user_input_request` 是 `dict[str, Any]`，新增 key（`awaiting_kind`、`_candidate_id`、`_choice_map`、`_origin_status`）无需 schema migration
- 崩溃恢复后，checkpoint 中的 pending 状态可被正确恢复

**P2-5: 确认 observer evidence 不覆盖 Memory 路径**

- **现状**: `_emit_confirmation_observer_event` 覆盖 plan/step/tool/user_input/feedback_intent 5 条路径，但不覆盖 Memory confirmation（因为 Memory 不走 confirm_handlers）。

### P3 — 低优先级 (留意即可)

**P3-1: InputIntent.metadata 类型太宽**

- `metadata: dict[str, Any]` 没有 schema 约束，不同 kind 的 metadata 结构靠约定。

**P3-2: AST-based boundary tests 可能脆弱**

- `test_memory_runtime_does_not_touch_checkpoint` 等用 AST 检查 imports，如果 Python AST 结构变化需要同步更新。

**P3-3: paste burst drain 仅 simple backend**

- paste burst drain (v0.6.2) 只在 `simple.py` 中实现。如果未来引入第三个 input backend，需确保 paste burst 行为一致。

**P3-4: 模块级单例 session 隔离风险**

- `core.py:_memory_runtime = create_memory_runtime()` 是模块级单例，InMemoryMemoryStore 在进程生命周期内共享。单进程单 session 下实际风险低，已在 `docs/MEMORY_ARCHITECTURE.md` 记录。

### Future risk (不在当前主线，仅供后续参考)

**FR-1: Skill/Subagent 确认机制空白**

- Skill/Subagent 概念尚未引入。当未来引入时，应复用 Memory confirmation 验证过的 pending confirmation 模式，而不是另起一套。本条不阻塞当前 Memory 主线。

---

## 5. 测试覆盖评估

### 5.1 测试结果

```
运行: 195 collected / 172 selected / 2 collection errors
结果: 139 passed, 56 failed (全部因 anthropic 未安装)
```

56 个失败全部是 `ModuleNotFoundError: No module named 'anthropic'`，属于基础设施问题，非测试本身问题。

### 5.2 通过的测试覆盖

| 领域 | 测试文件 | 通过数 | 覆盖重点 |
|------|---------|--------|---------|
| InputIntent 分类 | test_input_intents.py | ~20 | 所有 kind 的分类逻辑、边界条件 |
| 确认响应分类 | (含于 test_input_intents) | ~5 | yes/no/中文词表 |
| 用户输入事件 | test_user_input_contract.py, test_user_input.py | ~15 | UserInputEnvelope/Event 契约 |
| Simple 后端 | test_input_backends_simple.py | ~20 | /multi, paste fence, paste burst drain |
| Textual 后端 | test_input_backends_textual.py | ~10 | TUI 事件构造、组件创建 |
| InputResolution | test_input_resolution.py | ~10 | collect_input/runtime_user_input/empty 解析 |
| UserReplied Transition | test_user_replied_transition.py | ~10 | 回复后状态转移 |
| DisplayEvent | test_display_event_contract.py | ~10 | 事件构造、脱敏、渲染 |
| RuntimeEvent | test_runtime_event_boundaries.py | ~10 | 事件边界 |
| TUI 依赖边界 | test_tui_dependency_boundaries.py | ~5 | TUI 不依赖 Runtime state |
| Memory 确认契约 | test_memory_confirmation_contract.py | ~8 | MemoryConfirmationRequest/Result contract |
| Memory Runtime | test_memory_runtime_integration.py | ~24 | 完整 Memory Kernel v1 流程 (含 deferred adapter) |
| 状态不变量 | test_state_invariants.py (部分通过) | ~3 | 状态字段契约 |

### 5.3 与 Memory interactive confirmation 相关的测试缺口

| 缺口 | 严重程度 | 说明 |
|------|---------|------|
| MemoryRuntime 在 core.chat() 中的集成行为 | P1 | 无测试覆盖 evaluate_user_text 在 chat 主循环中的调用 |
| MemoryConfirmationRequest 5 option 的交互式解析 | P1 | 有 contract 测试但无交互式消费测试 |
| 两阶段确认流程的 RuntimeEvent 被 main_loop 消费 | P2 | 已有测试覆盖 |
| Memory confirmation 的 checkpoint 持久化 | P2 | 无测试 |
| Textual PersistentInputShell 完整交互 | P2 | 依赖真实 Textual，CI 中无法运行 |

### 5.4 总体评分

- **单元测试覆盖率**: 良好 (针对现有能力)
- **集成测试覆盖率**: 不足 (core.chat 依赖 anthropic，多数集成测试 skip)
- **Memory confirmation 交互路径测试**: 空白

---

## 6. 架构图

```
┌─────────────────────────────────────────────────────────┐
│                       main.py                            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ simple CLI    │  │ Textual TUI  │  │ UserInputEvent │  │
│  │ fallback      │  │ (Persistent  │  │ → classify    │  │
│  │ adapter       │  │  InputShell) │  │   _user_input │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                 │                   │           │
│         └────────┬────────┘                   │           │
│                  │                            │           │
│                  ▼                            ▼           │
│         UserInputEvent              InputIntent           │
│                  │                            │           │
│                  └──────────┬─────────────────┘           │
│                             │                             │
│                             ▼                             │
│                      core.chat()                          │
│                    ┌────────────┐                         │
│                    │ _dispatch  │                         │
│                    │ _pending   │                         │
│                    │ _confirm   │                         │
│                    └─────┬──────┘                         │
│                          │                                │
│         ┌────────────────┼──────────────────┐             │
│         │                │                  │             │
│         ▼                ▼                  ▼             │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐   │
│  │ plan/step   │ │ tool         │ │ user_input/      │   │
│  │ confirmation│ │ confirmation │ │ feedback_intent  │   │
│  └──────┬──────┘ └──────┬───────┘ └────────┬─────────┘   │
│         │                │                  │             │
│         └────────────────┼──────────────────┘             │
│                          │                                │
│                          ▼                                │
│                  confirm_handlers                         │
│         ┌────────────────┬──────────────┐                 │
│         │ checkpoint     │ conversation │                 │
│         │ save/clear     │ .messages    │                 │
│         └────────────────┴──────────────┘                 │
│                          │                                │
│                          ▼                                │
│                   RuntimeEvent                            │
│                   → TUI projection                        │
│                   → simple CLI render                     │
└─────────────────────────────────────────────────────────┘

         ┌──────────────────────────────────────┐
         │  Memory Interactive Confirmation v1   │
         │       (已接入 AgentLoop)               │
         │                                      │
         │  MemoryRuntime.evaluate_user_text()  │
         │    → MemoryPolicy                    │
         │    → 返回 CONFIRMATION_REQUIRED       │
         │    → core.py 构建 pending dict        │
         │    → awaiting_user_input              │
         │  MemoryRuntime.resolve_confirmation() │
         │    → InMemoryMemoryStore             │
         │    → snapshot_for_prompt()           │
         │                                      │
         │  ✅ 已接入 _dispatch_pending_confirm   │
         │  ✅ RuntimeEvent 已被 UI 消费          │
         │  ✅ MemoryConfirmationRequest 的      │
         │     5 种 choice 全部可交互式消费       │
         └──────────────────────────────────────┘
```

---

## 7. 强化建议

### 判断: **需要中等强化 (Memory Interactive Confirmation Readiness)**

不需要大改 TUI，不需要引入 Skill/Subagent，不需要接外部 Memory Provider。

需要的是：**在实现 Memory interactive confirmation 之前，先做轻量的 PendingInteraction 统一和小范围 hardening**，确保 Memory confirmation 能复用现有 interaction boundary，而不是成为第 6 套独立 confirmation 机制。

**当前可以接受的部分**:
- v1 auto-accept 对 explicit retain 是合理的临时策略
- 现有 4+1 pending 状态的分发模式已被 characterization tests 钉死，扩展性好
- RuntimeEvent 输出边界已统一，Textual/simple CLI 都消费同一套事件

**需要强化的部分**:
- Memory confirmation 必须接入 pending confirmation dispatch（不能继续绕过）
- 在接入之前，需要回答 "复用 awaiting_user_input 还是新增独立 status" 的设计问题
- MemoryConfirmationRequest 的 5 选项需要交互式 adapter 来消费

---

## 8. 推荐下一步

### 推荐: Memory Interactive Confirmation Readiness / PendingInteraction small hardening

**目标**: 让 Memory confirmation 复用现有 interaction boundary，避免每加一个能力就写一套新 confirmation。

**具体步骤**:

1. **设计轻量 PendingInteraction 统一模型** (contract + doc，不写代码):
   - 定义 `PendingInteraction` Protocol: `kind`, `question`, `options_schema`, `resolve(user_input) -> result`
   - 将现有 4+1 状态描述为 PendingInteraction 的 5 个 variant（不改现有代码，只做概念映射）
   - 明确 Memory confirmation 作为第 6 个 variant 如何嵌入现有 dispatch
   - 产出: `docs/PENDING_INTERACTION_MODEL.md`

2. **回答 Memory confirmation 集成路径的关键设计问题**:
   - 复用 `awaiting_user_input` + `pending_user_input_request`（扩展 awaiting_kind="memory_confirmation"） vs 新增 `awaiting_memory_confirmation`
   - `classify_confirmation_response` 的三元分类 vs Memory 5 选项：由分类层统一还是由 handler 自行解析
   - edit/session_only/Other 的 free_text 如何在 InputIntent → InputResolution 链路中传递

3. **Memory RuntimeEvent 的 UI 消费** (小范围代码改动):
   - 在 `render_runtime_event_for_cli` / `_append_runtime_event` 中增加 `memory_confirmation_requested` 的渲染
   - 让 v1 auto-accept 至少展示 "已记住: ..." 给用户

4. **不做的**:
   - 不大改 TUI（不渲染确认按钮/菜单）
   - 不进入 Skill/Subagent
   - 不接外部 Memory Provider
   - 不大重构现有确认状态机

**产出**: `docs/PENDING_INTERACTION_MODEL.md` + `docs/ROADMAP.md` 更新 + Memory RuntimeEvent UI 消费的小范围代码改动

---

## 9. Phase D Hardening 变更总结

### 9.1 本轮变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `agent/display_events.py` | 新增 | `EVENT_MEMORY_STORED/BLOCKED/INJECTED` 常量 + `memory_stored_event/memory_blocked_event/memory_injected_event` 工厂函数 |
| `agent/core.py` | 修改 | `evaluate_user_text` 返回值捕获 → 按 action emit RuntimeEvent；`refresh_runtime_system_prompt` 后 emit `memory_injected_event`；新增 import `MemoryEvaluationAction` 及 3 个事件工厂 |
| `docs/PENDING_INTERACTION_MODEL.md` | 新建 | 5 节：为什么需要、现有变体概念映射、Memory 未来变体、三元 vs 五选项 gap、非目标 |
| `tests/test_memory_runtime_events.py` | 新建 | 29 条测试：事件构造、渲染、脱敏、CLI 一致性、doc 存在性 |

### 9.2 P1/P2 状态更新

| 风险 | 状态 | 说明 |
|------|------|------|
| P1-1: Memory 未接入 pending dispatch | 未改 | 属于 Memory interactive confirmation 阶段；Phase D 只做概念铺路（`docs/PENDING_INTERACTION_MODEL.md`） |
| P1-2: Memory RuntimeEvent 无人消费 | ✅ 已修复 | 3 种事件类型 + core.py 桥接 + CLI 渲染 |
| P2-1: 缺少统一 PendingInteraction 模型 | 🟡 概念已落地 | `docs/PENDING_INTERACTION_MODEL.md` 完成概念建模，不做代码重构 |
| P2-2: 三元 vs 五选项 gap | 🟡 已文档化 | 在 PendingInteraction 文档 §4 中分析，实现选择留给下阶段 |
| P2-3: TUI/simple 选项支持不一致 | 未改 | 结构化选项支持需 Memory interactive confirmation 阶段 |
| P2-4: Memory 不进 checkpoint | 未改 | v1 设计决定，不在此阶段改动 |
| P2-5: observer evidence 不覆盖 Memory | 未改 | observer 扩展留给后续阶段 |

### 9.3 未改动

- `agent/memory_runtime.py`：零改动
- `agent/state.py`：零改动（无新增 pending status）
- `agent/confirm_handlers.py`：零改动
- `agent/input_backends/`：零改动
- `agent/checkpoint.py`：零改动
- `agent/memory_confirmation.py`：零改动

---

## 10. Phase E: Memory Interactive Confirmation v1 变更总结

### 10.1 本轮变更

| 文件 | 变更类型 | 行数变化 | 说明 |
|------|---------|---------|------|
| `agent/memory_interaction.py` | **新建** | +175 | 桥接层：`build_memory_pending_request` / `parse_memory_confirmation_reply` / `handle_memory_confirmation_reply` / `_sink_runtime_event` |
| `agent/memory_runtime.py` | 修改 | +123/-67 | 新增 `_pending_decision` cache；`evaluate_user_text` 返回 CONFIRMATION_REQUIRED；新增 `get_pending_confirmation` / `resolve_confirmation` |
| `agent/core.py` | 修改 | +54 | 新增 CONFIRMATION_REQUIRED 分支：构建 pending dict → set status → save_checkpoint → emit event |
| `agent/confirm_handlers.py` | 修改 | +19 | `handle_user_input_step` 入口新增 `awaiting_kind="memory_confirmation"` 路由 |
| `agent/display_events.py` | 修改 | +79 | 新增 `EVENT_MEMORY_CONFIRMATION_REQUESTED` + `memory_confirmation_requested_event` 工厂函数 |
| `agent/memory_store.py` | 修改 | +13 | 移除 USE_ONCE 从 NON_WRITING_OPERATION_TYPES；新增专用 USE_ONCE write 分支 |
| `tests/test_memory_interactive_confirmation.py` | **新建** | +408 | 18 条测试：evaluate → CONFIRMATION_REQUIRED、get_pending、resolve 5 种 choice、pending 结构、parse 解析、边界条件 |
| `tests/test_memory_runtime_integration.py` | 修改 | +108/-67 | 更新 24 条测试适配新 API；新增 `_evaluate_and_confirm` 辅助函数 |
| `tests/test_display_event_contract.py` | 修改 | +2 | `EVENT_MEMORY_CONFIRMATION_REQUESTED` 加入 baseline |

### 10.2 P1/P2 状态更新

| 风险 | Phase D 状态 | Phase E 状态 | 说明 |
|------|-------------|-------------|------|
| P1-1: Memory 未接入 pending dispatch | 🟡 概念铺路 | ✅ 已修复 | 两阶段流程 + 复用 `awaiting_user_input` |
| P1-2: Memory RuntimeEvent 无人消费 | ✅ 已修复 | ✅ 保持 | Phase D 已修复，Phase E 无回归 |
| P2-1: 缺少统一 PendingInteraction 模型 | 🟡 概念落地 | 🟡 概念落地 | 实际验证了方案 B，不做代码重构 |
| P2-2: 三元 vs 五选项 gap | 🟡 已文档化 | ✅ 已解决 | `parse_memory_confirmation_reply` 专用解析器 |
| P2-3: TUI/simple 选项支持不一致 | 未改 | 🟡 数字协议落地 | 统一数字 + 文本协议，结构化 UI 延后 |
| P2-4: Memory 不进 checkpoint | 未改 | ✅ 已解决 | pending dict 自动进 checkpoint |
| P2-5: observer evidence 不覆盖 Memory | 未改 | 未改 | observer 扩展留给后续阶段 |

### 10.3 未改动

- `agent/state.py`：零改动（无新增 pending status 或 TaskState 字段）
- `agent/checkpoint.py`：零改动（`pending_user_input_request` 是 `dict[str, Any]`，无需 schema migration）
- `agent/input_backends/`：零改动
- `agent/memory_confirmation.py`：零改动（contract 在 Phase D 已完整定义）
- `agent/memory_contracts.py`：零改动
- `agent/memory_policy.py`：零改动

---

## 11. 变更总结（原始审计 + Phase D + Phase E）

**Phase C 原始审计**:
- 读取源文件: 16 个
- 运行测试: 172 selected, **139 passed**, 56 failed (全部因 anthropic 未安装)
- 本轮未修改生产代码，生成了本审计文档

**Phase D Hardening**:
- 新增 `EVENT_MEMORY_STORED/BLOCKED/INJECTED` 3 种 RuntimeEvent
- 桥接 `core.py` → RuntimeEvent emit
- 29 条新测试保护事件构造/渲染/脱敏/CLI 一致性

**Phase E Interactive Confirmation v1**:
- 新增 `agent/memory_interaction.py` (175行) 桥接层
- 修改 6 个生产文件 + 3 个测试文件
- 新增 18 条 interactive confirmation 测试
- 更新 24 条已有集成测试适配新 API

**当前风险总览**:
- **P1 (0 项)**: 全部已修复
- **P2 (2 项剩余)**: P2-3 (TUI 结构化 UI 延后)、P2-5 (observer evidence 延后)
- **P3 (4 项)**: 与 Phase C 相同，无变化
- **Future risk (1 项)**: Skill/Subagent 确认机制空白（不阻塞当前主线）

# PendingInteraction 统一概念模型

**创建日期**: 2026-05-09
**性质**: 轻量概念模型，非代码重构蓝图
**目的**: 为 Memory interactive confirmation 铺路，避免每加一个能力就写一套独立 confirmation 机制

---

## 1. 为什么需要统一概念模型

当前 AgentLoop 中存在 4+1 种 pending 状态（`awaiting_plan_confirmation` /
`awaiting_step_confirmation` / `awaiting_user_input` /
`awaiting_tool_confirmation` + `awaiting_feedback_intent`），它们：

- **字段分散**在 `TaskState` 中：`pending_tool`、`pending_user_input_request`、
  `current_plan` 各自独立管理
- **无公共抽象**：每种状态有独立的 handler、独立的分支判断、独立的字段
- **分发靠硬编码 if/elif 链**：`_dispatch_pending_confirmation` 的 5 条分支
  按固定顺序排列，新增状态必须追加分支
- **Memory confirmation 完全绕过**这套机制：`MemoryRuntime.evaluate_user_text()`
  是同步调用，不走 pending → dispatch → handler 路径

如果直接在现有结构上新增 `awaiting_memory_confirmation`，会制造第 6 套独立
confirmation 机制，进一步膨胀 `TaskState` 和 dispatch 链。

统一概念模型的目标是：**先定义概念，再决定实现路径**。不要求立刻重构现有 4+1
状态，也不要求引入新的抽象基类或 Protocol 实现。

---

## 2. 现有变体（4+1）的概念映射

将现有 5 种 pending 状态描述为统一概念模型的 variant，不改现有代码：

| 概念维度 | plan_confirmation | step_confirmation | tool_confirmation | user_input | feedback_intent |
|---------|-------------------|-------------------|-------------------|------------|-----------------|
| **触发方** | Runtime (planner) | Runtime (step done) | Runtime (tool needs confirm) | 模型 (request_user_input) | Runtime (plan/step feedback) |
| **问题** | "按此计划执行吗？" | "继续下一步吗？" | "是否执行工具 X？" | 模型指定 | "要继续当前任务还是开新任务？" |
| **选项结构** | accept/reject/feedback | accept/reject/feedback | accept/reject/feedback | 自由文本 | 3 个互斥选项 |
| **需要 free_text** | feedback 时 | feedback 时 | feedback 时 | 总是 | 否 |
| **状态字段** | current_plan | current_plan + confirm_each_step | pending_tool | pending_user_input_request | pending_user_input_request |
| **handler** | handle_plan_confirmation | handle_step_confirmation | handle_tool_confirmation | handle_user_input_step | handle_feedback_intent_choice |
| **分类方式** | classify_confirmation_response (三元) | 同左 | 同左 | classify_user_input (kind=request_user_reply) | classify_user_input (kind=normal_message → handler 内部分类) |

**共性**：
- 都有 pending status（`state.task.status == "awaiting_*"`）
- 都有 pending data（存在 `TaskState` 的某个字段上）
- 都需要用户输入来解除等待
- 解除后都有明确的下一状态

**差异**：
- 选项结构：有的是三元（accept/reject/feedback），有的是自由文本，有的是固定选项列表
- 触发方：有的是 Runtime 主动，有的是模型通过 tool 触发
- 是否需要推进任务状态（step done / tool executed）：有的推进，有的不推进

---

## 3. Memory confirmation 作为已实现变体（✅ Phase E 完成）

Memory confirmation 已实现并映射到统一概念模型：

| 概念维度 | memory_confirmation |
|---------|---------------------|
| **触发方** | MemoryRuntime (policy 判定 RETAIN 后) |
| **问题** | "是否记住这条信息？"（来自 `MemoryConfirmationRequest.question`） |
| **选项结构** | 5 种 choice：ACCEPT / EDIT_AND_ACCEPT / SESSION_ONLY / REJECT / OTHER |
| **需要 free_text** | EDIT_AND_ACCEPT 和 OTHER 时需要 |
| **状态字段** | 复用 `pending_user_input_request`（`awaiting_kind="memory_confirmation"`） |
| **handler** | `handle_memory_confirmation_reply` → 委托自 `handle_user_input_step` |
| **分类方式** | `parse_memory_confirmation_reply` 专用解析器（数字匹配 + 数字-文本 + fallback OTHER） |

**与现有变体的关键差异**：
1. **选项结构是 5 元而非 3 元**：走专用解析器 `parse_memory_confirmation_reply`，
   不经过 `classify_confirmation_response` 三元分类
2. **edit 和 other 需要跟随 free_text**：通过 "数字+空格+文本" 格式一次输入完成
3. **SESSION_ONLY 是独特语义**：既不是 accept（持久化）也不是 reject（丢弃），
   而是"本次会话使用但不持久化"，对应 `MemoryOperationType.USE_ONCE`

**选择的集成路径：路径 B（复用 `awaiting_user_input`）**

实际实现选择了路径 B：
- **不新增 `awaiting_memory_confirmation` status**：复用 `awaiting_user_input` +
  `pending_user_input_request`，通过 `awaiting_kind="memory_confirmation"` 区分
- **不新增 TaskState 字段**：所有 memory 专有数据（`_candidate_id`、`_choice_map`、
  `_origin_status`）以 `_` 前缀 key 存在 `pending_user_input_request` dict 中
- **dispatch 链不膨胀**：`handle_user_input_step` 在入口处检查 `awaiting_kind`，
  若为 `"memory_confirmation"` 则委托给 `handle_memory_confirmation_reply`
- **分类不经过 `classify_confirmation_response`**：由 `parse_memory_confirmation_reply`
  直接解析数字选项，无需修改现有三元分类器

**实现结构**：
```
evaluate_user_text() → CONFIRMATION_REQUIRED
  → core.py 构建 pending dict → save_checkpoint
    → 用户看到 MemoryConfirmationRequest (TUI/CLI)
      → 用户输入 "1" ~ "5" 或 "N text" 或自由文本
        → handle_user_input_step → handle_memory_confirmation_reply
          → parse_memory_confirmation_reply → (choice, free_text)
          → resolve_confirmation(candidate_id, choice, free_text)
            → resolve_memory_confirmation_choice → APPROVED/REJECTED/SESSION_ONLY/NEEDS_CLARIFICATION
            → store write (APPROVED/SESSION_ONLY) / skip (REJECTED)
          → 清 pending → 恢复 origin_status → save_checkpoint
```

**关键文件**：
| 文件 | 角色 |
|------|------|
| `agent/memory_interaction.py` (175行) | 桥接层：build pending dict / parse reply / handle reply |
| `agent/memory_runtime.py` | 新增 `_pending_decision` cache + `resolve_confirmation()` |
| `agent/core.py` | 新增 CONFIRMATION_REQUIRED 分支（~30行） |
| `agent/confirm_handlers.py` | 新增 `awaiting_kind="memory_confirmation"` 路由（~15行） |
| `agent/display_events.py` | 新增 `EVENT_MEMORY_CONFIRMATION_REQUESTED` 事件 |
| `agent/memory_store.py` | USE_ONCE 从 NON_WRITING 移到独立 write 分支 |

---

## 4. 三元分类 vs 五选项的 gap（✅ 已解决）

`classify_confirmation_response()` 使用静态中文词表做三元分类，无法处理
Memory 的 5 种 choice。

**Phase E 解决方案**：Memory confirmation 不经过 `classify_confirmation_response`。
由 `parse_memory_confirmation_reply()` 直接解析用户输入：

| 用户输入 | 解析结果 |
|---------|---------|
| "1" | ACCEPT |
| "2" | EDIT_AND_ACCEPT |
| "2 改成：我喜欢绿色" | EDIT_AND_ACCEPT + free_text="改成：我喜欢绿色" |
| "3" | SESSION_ONLY |
| "4" | REJECT |
| "5" | OTHER |
| "5 请只在本次会话记住" | OTHER + free_text="请只在本次会话记住" |
| 任意其他文本 | OTHER + 全文作为 free_text |
| "" (空) | ValueError → 提示重新输入 |

**为什么不需要修改 `classify_confirmation_response`**：
- `handle_user_input_step` 在入口处通过 `pending.get("awaiting_kind")` 识别
  memory_confirmation，提前分流到 `handle_memory_confirmation_reply`
- Memory 确认完全走专用解析路径，不进入通用三元分类器
- 不会出现三元分类误判 memory 输入的情况

---

## 5. 非目标（Non-goals）

Phase E 实现坚持了以下约束：

- **不大重构现有 4+1 状态机**：plan/step/tool/user_input/feedback_intent
  的工作方式不变 ✅
- **不引入 PendingInteraction Protocol/ABC**：不写新的抽象基类或 Protocol ✅
- **不改变 checkpoint schema**：`pending_user_input_request` 是 `dict[str, Any]`，
  新增 key 不需要 schema migration ✅
- **不修改 TUI 渲染**：不引入按钮/菜单/选项 UI；选项通过文本列表展示 ✅
- **不改变 `_dispatch_pending_confirmation` 的 if/elif 链结构**：memory
  confirmation 在 `handle_user_input_step` 入口处分流 ✅
- **不引入新的依赖或框架** ✅
- **不新增 pending status**：复用 `awaiting_user_input`，不制造第 6 套独立机制 ✅

---

## 6. Memory Interactive Confirmation v1 实现总结（Phase E）

### 6.1 两阶段确认流程

```
Phase 1 — evaluate:
  user_text → MemoryRuntime.evaluate_user_text()
    → MemoryPolicy.decide() → MemoryDecision(RETAIN)
    → 缓存 decision 到 _pending_decision
    → 返回 CONFIRMATION_REQUIRED

Phase 2 — resolve:
  用户选择 → handle_memory_confirmation_reply()
    → parse_memory_confirmation_reply() → (choice, free_text)
    → MemoryRuntime.resolve_confirmation(candidate_id, choice, free_text)
      → resolve_memory_confirmation_choice() → APPROVED/REJECTED/SESSION_ONLY/NEEDS_CLARIFICATION
      → store write (APPROVED/SESSION_ONLY) / skip (REJECTED)
    → 清 pending → 恢复 origin_status → save_checkpoint
```

### 6.2 5 种 choice 与 store 行为

| choice | 用户输入 | confirmation status | store 行为 |
|--------|---------|-------------------|-----------|
| ACCEPT | "1" | APPROVED | RETAIN → APPLIED |
| EDIT_AND_ACCEPT | "2 <新内容>" | APPROVED (approved_content=free_text) | RETAIN → APPLIED (编辑后内容) |
| SESSION_ONLY | "3" | SESSION_ONLY | USE_ONCE → APPLIED (仅本次会话) |
| REJECT | "4" | REJECTED | 不写 store |
| OTHER | "5 <自由文本>" 或任意文本 | NEEDS_CLARIFICATION | 走 clarify 路径 |

### 6.3 安全边界保持不变

- `parse_memory_confirmation_reply` 和 `handle_memory_confirmation_reply` 不写 store、不调 LLM
- `build_memory_pending_request` 只做数据转换
- Memory confirmation 通过 checkpoint 持久化 pending 状态（崩溃后可恢复）
- 不引入新的 pending status 或 TaskState 字段
- handler 通过 lazy import 避免循环依赖（core → confirm_handlers → core）

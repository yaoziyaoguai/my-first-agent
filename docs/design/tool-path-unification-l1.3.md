# Tool Path Unification — SDD (Loop 1.3)

Status: implemented — 方案 2, Loop 1.3b COMPLETED
Date: 2026-05-28

## 0. 方案 3 已被否定（Mid-Loop Architecture Checkpoint）

**方案 3「执行后补 RuntimeAction evidence」**的实现（`_dispatch_tool_evidence()` 在
`execute_single_tool` 成功返回后补发 TOOL_INVOKE/TOOL_RESULT）已在 mid-loop checkpoint
中被否定并 revert。

方案 3 的特征：
- `execute_single_tool` 仍是上层主路径入口
- dispatcher 调用发生在执行完成之后
- TOOL_GATE 从未参与真实执行生命周期
- 本质是 post-hoc logging，不是 dispatcher 中介

**Loop 1.3 不接受方案 3 作为完成态。**

## 1. 问题陈述

当前真实模型 tool_use 存在两条分裂路径：

- **Path A（真实执行，无 RuntimeAction evidence）**：`model emits tool_use → handle_tool_use_response → execute_single_tool → append_tool_result → conversation context`。工具真实执行、用户可见，但 RuntimeActionDispatcher 完全不知情。
- **Path B（RuntimeAction evidence，无真实执行）**：`turn-end → _dispatch_tool_pipeline → TOOL_GATE(_safe_noop) → TOOL_INVOKE(_safe_noop) → TOOL_RESULT(_safe_noop)`。只有 `_safe_noop` probe，不执行任何真实工具。

## 2. 架构决策：方案 2 — Dispatcher-Mediated Tool Execution

核心原则：
- **dispatcher 是中介层**，坐在 model tool_use 和 tool executor 之间
- **execute_single_tool 降级为底层 executor**，被 mediator 调用，不再被 handle_tool_use_response 裸调
- **TOOL_GATE 参与真实执行生命周期**，不只是 turn-end probe
- **TOOL_INVOKE 包住真实执行**
- **TOOL_RESULT 记录真实执行结果**
- **append_tool_result 保持不变**（conversation context 不穿过 dispatcher）

### 2.1 目标数据流

```
model emits tool_use
  → handle_tool_use_response（瘦身：解析 response、追加 assistant content、配额管理）
    → 对每个业务 tool_use block：
      → ToolRuntimeMediator.mediate(block)
        → [1] TOOL_GATE: dispatcher.route_from_runtime_loop(TOOL_GATE, {tool_name, tool_input})
              → gate_disposition: allowed / confirmation_required / blocked
        → [2] if blocked → return FORCE_STOP
        → [3] if confirmation_required → set pending_tool → return AWAITING_USER
        → [4] TOOL_INVOKE: dispatcher.route_from_runtime_loop(TOOL_INVOKE, {tool_name, tool_input})
              → 内部调用 execute_single_tool(block, state, turn_state, turn_context, messages)
              → execute_single_tool 仍负责 confirmation/policy/audit/display/checkpoint/append_tool_result
        → [5] TOOL_RESULT: dispatcher.route_from_runtime_loop(TOOL_RESULT, {tool_name, tool_input, status, ...})
```

### 2.2 关键设计决策

**为什么 TOOL_GATE 和 TOOL_INVOKE 都走 dispatcher？**

- TOOL_GATE：dispatcher 的 `ToolGateHandler` 已实现完整的 gate 逻辑（allowed/confirmation_required/blocked/rejected），且通过 `context.invoke_registered_target` 获得 catalog adapter evidence
- TOOL_INVOKE：dispatcher 的 `ToolInvokeHandler` 能通过 catalog adapter 执行工具，但缺少 confirmation、policy、audit、display、checkpoint、messages 等行为
- TOOL_RESULT：记录真实执行结果摘要

**为什么 execute_single_tool 仍然是底层 executor？**

`execute_single_tool` 拥有以下 v1 不可替代的能力：
- confirmation 逻辑（`needs_tool_confirmation`）
- policy denial（`_describe_policy_denial`）
- audit events（`emit_tool_audit_event`）
- display events（`emit_display_event`）
- checkpoint 保存
- 幂等保护
- 重复输入检测
- `append_tool_result` 到 messages

将这些全部迁移到 dispatcher handler 等于重写工具执行器。v1 选择：dispatcher 负责 lifecycle mediation + evidence，`execute_single_tool` 负责实际执行。

## 3. 新增组件：ToolRuntimeMediator

### 3.1 定位

`ToolRuntimeMediator` 是 dispatcher 和 tool executor 之间的桥接层：

- 持有 `RuntimeActionDispatcher`（提供 TOOL_GATE/TOOL_RESULT evidence lifecycle）
- 持有 `state` / `turn_state` / `turn_context` / `messages`（传递给 execute_single_tool）
- 提供 `mediate(block) → str | None` 方法（返回 None=成功, FORCE_STOP, AWAITING_USER）

### 3.2 接口

```python
class ToolRuntimeMediator:
    def __init__(
        self,
        dispatcher,            # RuntimeActionDispatcher
        state,                 # TaskState
        turn_state,            # TurnState
        turn_context,          # dict[str, Any]
        messages,              # list[dict]
    ): ...

    def mediate(self, block) -> str | None:
        """对单个业务 tool_use block 执行 dispatcher-mediated execution。

        Returns:
            None: 正常执行完成
            AWAITING_USER: 需要用户确认
            FORCE_STOP: 被安全策略阻断
        """
```

### 3.3 mediate() 内部流程

```python
def mediate(self, block):
    tool_name = block.name
    tool_input = block.input
    tool_use_id = block.id

    # Step 1: TOOL_GATE — dispatcher 门控
    gate_result = self._dispatcher.route_from_runtime_loop(
        RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="ToolRuntimeMediator",
            parent_trace_id=tool_use_id,
            payload={"tool_name": tool_name, "tool_input": dict(tool_input or {})},
        ),
        core_entrypoint="core.chat",
        runtime_hook_name="handle_tool_use_response",
    )
    disposition = gate_result.evidence.get("gate_disposition")

    # Step 2: 根据 gate_disposition 分流
    if disposition == "rejected":
        # 安全策略阻断 → FORCE_STOP
        _handle_blocked(block, ...)
        return FORCE_STOP

    # Step 3: TOOL_INVOKE — 触发真实执行
    invoke_result = self._dispatcher.route_from_runtime_loop(
        RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_INVOKE,
            source="ToolRuntimeMediator",
            parent_trace_id=tool_use_id,
            payload={"tool_name": tool_name, "tool_input": dict(tool_input or {})},
        ),
        ...
    )

    # Step 4: 真实执行 — 调用 execute_single_tool
    result = execute_single_tool(
        block, state=self._state, turn_state=self._turn_state,
        turn_context=self._turn_context, messages=self._messages,
    )

    # Step 5: TOOL_RESULT — 记录执行结果
    self._dispatcher.route_from_runtime_loop(
        RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_RESULT,
            source="ToolRuntimeMediator",
            parent_trace_id=tool_use_id,
            payload={"tool_name": tool_name, "tool_input": ..., "status": ..., "result_summary": ...},
        ),
        ...
    )

    return result  # None / FORCE_STOP / AWAITING_USER
```

**关键点**：
- TOOL_GATE 在 execute_single_tool 之前调用——gate 先门控，然后才执行
- execute_single_tool 是 TOOL_INVOKE 的底层实现——不是 dispatcher 替代 execute_single_tool，而是 mediator 协调两者
- TOOL_RESULT 在 execute_single_tool 之后调用——记录真实执行结果
- handle_tool_use_response 不再裸调 execute_single_tool——只通过 mediator

### 3.4 防呆规则

以下退化形式被明确禁止：

| 退化形式 | 判定 | 说明 |
|---------|------|------|
| `execute_single_tool` 先执行，dispatcher 事后补 evidence | 方案 3 | 已 revert |
| TOOL_GATE 不参与真实执行生命周期 | 方案 3 | gate 必须在 execute_single_tool 之前调用 |
| handle_tool_use_response 裸调 execute_single_tool | 旧路径 | 必须改为通过 mediator |
| action_log 里只有 TOOL_INVOKE/TOOL_RESULT 但执行流未统一 | 方案 3 | 不能宣称完成 |
| _safe_noop probe 被当成 Tool capability completion | overclaim | probe 只是心跳 |

## 4. 修改范围

### 4.1 新建：`agent/tool_runtime_mediator.py`

`ToolRuntimeMediator` 类。持有 dispatcher + state + turn_state + turn_context + messages，提供 `mediate()` 方法。

### 4.2 修改：`agent/response_handlers.py`

- `handle_tool_use_response` 新增参数 `tool_runtime_mediator: Any | None = None`
- 业务工具的 for 循环中，用 `mediator.mediate(block)` 替代 `execute_single_tool(block, ...)`
- mediator 为 None 时回退到直接调用 execute_single_tool（向后兼容）

### 4.3 修改：`agent/model_output_dispatch.py`

- `ModelOutputDispatchDependencies` 新增 `runtime_action_dispatcher` 字段（已完成）
- `dispatch_model_output` 透传该字段到 handle_tool_use_response（已完成）

### 4.4 修改：`agent/core.py`

- `_dispatch_model_output` 将 `_phase1_dispatcher` 注入 dependencies（已完成）
- `_dispatch_model_output` 构造 `ToolRuntimeMediator` 并传入 handle_tool_use_response

### 4.5 不改的文件

- `agent/tool_executor.py` — execute_single_tool 不变，仍是被复用的底层 executor
- `agent/runtime_integration/tool_gate.py` — TOOL_GATE handler 不变
- `agent/runtime_integration/tool_invoke.py` — TOOL_INVOKE handler 不变（虽然当前 mediator 不直接用它执行，但 turn-end pipeline 仍用）
- `agent/loop.py` — turn-end pipeline 不变

## 5. 成功标准

1. 真实 model tool_use → mediator.mediate() → TOOL_GATE → TOOL_INVOKE → execute_single_tool → TOOL_RESULT
2. execute_single_tool 不再被 handle_tool_use_response 裸调
3. TOOL_GATE 参与真实执行生命周期（在 execute_single_tool 之前）
4. append_tool_result 保持不变（conversation context 完整）
5. _safe_noop probe 行为不变
6. 现有测试全部通过
7. dispatch 失败不阻塞工具执行

## 6. v1 不做（非目标）

- 不将 confirmation/policy/audit 移入 dispatcher handler
- 不让 dispatcher 完全替代 execute_single_tool
- 不删除 turn-end _safe_noop probe
- 不改变 pending tool (confirmation) 的流程
- 不新增 RuntimeActionType

## 7. PARTIAL 标记规则

如果本轮只完成基础设施（dispatcher 可达 + mediator 引入 + SDD 修正）但 TOOL_GATE 尚未参与真实执行生命周期，标记为 **PARTIAL**：

| 条件 | 状态 |
|------|------|
| dispatcher 可通过 ModelOutputDispatchDependencies 到达 handle_tool_use_response | 基础设施就绪 |
| ToolRuntimeMediator 已引入且 handle_tool_use_response 通过它调用 | PARTIAL（还需验证 TOOL_GATE 门控完整性） |
| TOOL_GATE → execute_single_tool → TOOL_RESULT 完整 lifecycle 通过测试验证 | READY |

## 7b. Loop 1.3b 实施记录（2026-05-28）

### 7b.1 gate_disposition 驱动执行流

Loop 1.3b 在 Loop 1.3 基础设施之上实现了 gate_disposition 对执行流的完整控制：

```
mediate(block):
  gate_disposition = _route_gate(...)     # TOOL_GATE → 获取 gate_disposition
  if rejected / None:                     # 安全失败
    _handle_blocked(...)                  #   写 tool_execution_log + tool_result
    _route_result(..., FORCE_STOP)        #   记录 TOOL_RESULT
    return FORCE_STOP                     #   不执行 execute_single_tool
  if confirmation_required:               # 等待用户确认
    _handle_confirmation_required(...)    #   设置 pending_tool + save_checkpoint
    _route_result(..., AWAITING_USER)     #   记录 TOOL_RESULT
    return AWAITING_USER                  #   不执行 execute_single_tool
  # allowed: 正常路径
  _route_invoke(...)                      # TOOL_INVOKE
  result = execute_single_tool(...)       # 真实执行
  _route_result(..., result)              # TOOL_RESULT
  return result
```

### 7b.2 关键行为变更

| 场景 | 旧行为 (Loop 1.3) | 新行为 (Loop 1.3b) |
|------|-------------------|---------------------|
| gate_disposition="allowed" | 直接执行（不检查 gate 返回值） | 走完整 TOOL_INVOKE → execute_single_tool → TOOL_RESULT |
| gate_disposition="rejected" | 直接执行（gate 结果被忽略） | **短路** → FORCE_STOP，写 blocked tool_result |
| gate_disposition=None (malformed) | 直接执行（gate 结果被忽略） | **安全失败** → FORCE_STOP，不执行工具 |
| gate_disposition="confirmation_required" | 直接执行（execute_single_tool 自行判断） | **短路** → AWAITING_USER，由 mediator 设置 pending_tool |

### 7b.3 测试覆盖

16 tests（t1-t16）覆盖：
- t1-t6: 方案 2 contract（GATE/INVOKE/RESULT dispatch、顺序、fallback、conversation context）
- t7-t8: 方案 3 防呆（源码级验证 gate 在 execute 之前）
- t9-t10: _safe_noop probe vs business 区分
- **t11**: allowed → execute_single_tool 真实执行
- **t12**: rejected → FORCE_STOP，不执行工具
- **t13**: confirmation_required → AWAITING_USER，pending_tool 已设置
- **t14**: malformed (None) → FORCE_STOP，安全失败
- **t15**: rejected 后 tool_result 仍写入 messages
- **t16**: rejected/confirmation_required/None 不 dispatch TOOL_INVOKE

## 8. 风险与回退

- **风险**：dispatcher.route_from_runtime_loop 抛出异常 → 工具执行受影响
- **缓解**：_route_gate 中 try/except 返回 None → 触发安全失败（FORCE_STOP），不执行工具
- **回退**：移除 mediator，恢复 handle_tool_use_response 裸调 execute_single_tool

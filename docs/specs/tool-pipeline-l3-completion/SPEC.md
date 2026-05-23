# Tool Pipeline L3 Completion SPEC

Status: active
Date: 2026-05-23
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
Engineering: [Engineering Workflow](../../dev/ENGINEERING_WORKFLOW.md)

## 1. Branch Point 判断

### 1.1 已有介入点

Tool 是 Contract §2 定义的已有有限介入点，归属 "tool execution / confirmation handling" 分支点。
本轮不在 Contract §2 之外新增 branch point，不在 Contract §6 之外新增 capability milestone。

### 1.2 Lifecycle Stages（非子系统）

ToolGate / ToolInvoke / ToolResult 不是三个独立子系统。它们是 Tool 介入点下的三个 lifecycle stages（pipeline phases）：

```text
Tool lifecycle pipeline:
  TOOL_GATE (pre-execution gating)
    → TOOL_INVOKE (execution)
      → TOOL_RESULT (post-execution feedback)
```

三个 stage 各自有 handler + catalog descriptor，共享同一个 ToolRegistry、同一个 RuntimeActionDispatcher、同一个 unified runtime flow 入口。

后续文档和注释不得把它们称为三个独立子系统。

### 1.3 本轮定位

本轮**补齐**已有 Tool pipeline 的 L3 evidence。不是新增 capability，不是新增 branch point，不是新增 runtime flow。

当前 L3 覆盖情况（来自 audit）：

| Stage | L1 | L2 | L3 | 说明 |
|-------|:--:|:--:|:--:|------|
| TOOL_GATE | yes | yes | **yes (B2/B5)** | route_from_runtime_loop 可产生 L3 |
| TOOL_INVOKE | yes | yes | **no** | loop.py 不构造 TOOL_INVOKE action |
| TOOL_RESULT | yes | yes | **no** | loop.py 不构造 TOOL_RESULT action |

---

## 2. L3 定义

### 2.1 real_core_loop_runtime_e2e 必须满足（Contract §5）

- action 由 loop.py/_try_phase1_turn_end_runtime_action 产生和消费
- dispatcher_origin == "runtime_loop"
- runtime_loop_invoked == True
- source == "core_loop"
- core_entrypoint == "core.chat"
- runtime_hook_name 非空
- target handler invoked
- target module proof 完整
- result returned to parent runtime
- 不靠 payload spoofing（payload 字段不能升级分类）

### 2.2 L3 不是什么

- 不是测试手工构造 RuntimeActionRequest → dispatcher.route()
- 不是 direct handler call
- 不是直接 subsystem API 调用
- 不是 payload 里写 core_loop_invoked=True
- 不是 dogfood harness 直接 route_from_runtime_loop()

### 2.3 L3 诚实声明

本轮 L3 测试通过 _try_phase1_turn_end_runtime_action() 调用 route_from_runtime_loop()。
与 Tool Gate B5 的做法一致——调用与 loop.py 生产代码相同的函数，但不经过 core.chat() 的 model loop。
dispatcher 层 provenance 满足 classify_evidence_level() 的 L3 条件。

"action 由 core.chat() 自然产生"的完整语义需要真正 model call 路径，
不在本轮 scope（需要 provider + real/fake model + tool_use response chain）。

---

## 3. 目标路径

### 3.1 完整管线

```text
core.chat / loop.py / run_main_loop
  → _try_phase1_turn_end_runtime_action (turn-end hook)
    → TOOL_GATE (route_from_runtime_loop)
      → 如果 gate_disposition == "allowed"
        → TOOL_INVOKE (route_from_runtime_loop)
          → ToolInvokeHandler.handle()
            → context.invoke_registered_target(ToolRegistry, execute_tool)
              → _tool_invoke_adapter → TOOL_REGISTRY + execute_tool()
        → TOOL_RESULT (route_from_runtime_loop)
          → ToolResultFeedbackHandler.handle()
            → context.invoke_registered_target(ToolRuntime, format_tool_result)
              → _tool_result_format_adapter → format_tool_result()
    → return to unified runtime flow
```

### 3.2 不经过的路径

- TOOL_GATE 返回 confirmation_required → 不构造 TOOL_INVOKE（等待用户确认后再 invoke）
- TOOL_GATE 返回 blocked/not_found → 不构造 TOOL_INVOKE
- TOOL_GATE 不存在 handler → 不构造 TOOL_INVOKE

---

## 4. 复用关系

### 4.1 完全复用（零修改）

| 组件 | 文件 | 说明 |
|------|------|------|
| TOOL_REGISTRY | agent/tool_registry | 工具注册表，不变 |
| execute_tool | agent/tool_registry | 工具执行函数，不变 |
| _safe_noop / _confirmable_noop | agent/tools/ | 内部测试工具，不变 |
| ToolGateHandler | agent/runtime_integration/tool_gate.py | gate handler，不变 |
| ToolInvokeHandler | agent/runtime_integration/tool_invoke.py | invoke handler，不变 |
| ToolResultFeedbackHandler | agent/runtime_integration/tool_result_feedback.py | result handler，不变 |
| _tool_invoke_adapter | agent/runtime_integration/evidence.py | catalog adapter，不变 |
| _tool_result_format_adapter | agent/runtime_integration/evidence.py | catalog adapter，不变 |
| RuntimeActionDispatcher | agent/runtime_integration/dispatcher.py | 路由层，不变 |
| phase1_hook.py | agent/runtime_integration/phase1_hook.py | handler 注册，不变 |
| core.py | agent/core.py | 主入口，不变 |

### 4.2 最小修改

| 组件 | 文件 | 修改范围 |
|------|------|---------|
| _try_phase1_turn_end_runtime_action | agent/loop.py | TOOL_GATE allowed 后构造 TOOL_INVOKE + TOOL_RESULT |

### 4.3 不引入第二套主流程

不创建新的 dispatcher、新的 handler 注册路径、新的 tool execution pipeline。
loop.py 的修改只是补齐已有 pipeline 的 action 构造——与 TOOL_GATE 构造在同一函数内、同一 dispatcher、同一 turn-end hook。

---

## 5. MCP 关系

### 5.1 继承关系

MCP 工具通过 register_mcp_tools() 注册到 TOOL_REGISTRY，与本地工具共用：
- 同一个 TOOL_GATE handler（capability="mcp_tool" 是元数据维度）
- 同一个 TOOL_INVOKE handler（_tool_invoke_adapter 已支持 MCP error 格式）
- 同一个 TOOL_RESULT handler（format_tool_result 对 tool_output 做通用处理）

Tool pipeline L3 完成后，MCP L3 应可通过同一管线验证——不需要修改任何 MCP 代码。

### 5.2 本轮不扩展

- 不扩展 MCP resources / prompts
- 不扩展 MCP policy re-eval per-call
- 不扩展 MCP multi-server discovery
- 不扩展 MCP auth / secret flow
- 不连接真实 MCP server

---

## 6. 不做什么

| 排除项 | 原因 |
|--------|------|
| Policy re-eval per-call | 独立 deferred 项，需要 TOOL_GATE adapter 改动 |
| D4 mid-pipeline not_found | race-condition 模拟 infra 超出本轮范围 |
| MCP resources / prompts | 独立 capability，需要 SPEC/TDD/Plan |
| Real API / .env / 真实 server | 安全边界 |
| Retry / Error Recovery | 独立关注点 |
| Multi Tool | 独立关注点 |
| UI confirmation flow | 独立关注点 |
| core.py 修改 | 本轮只需 loop.py 改动 |
| 新增 dispatcher / handler | 复用已有 |
| Model call 路径 L3 | 需要 provider + tool_use response chain，超出本轮 |

---

## 7. Open Questions

### OQ#1: TOOL_GATE blocked/confirmation_required 时 TOOL_RESULT 是否仍需构造？

**当前判断：** 不构造。confirmation_required 时工具未执行，没有 result 可 feedback。
blocked/not_found 时同理。后续 confirmation → user approves → 工具实际执行时再走 invoke → result。

### OQ#2: TOOL_INVOKE 和 TOOL_RESULT 失败是否应阻断 loop？

**当前判断：** 各自独立 try/except，与 TOOL_GATE 和 MEMORY 的处理一致。
一个 stage 失败不阻断其他 stage，也不阻断 loop 返回。

---

## 8. Review Checklist

- [ ] Tool 是已有介入点，ToolGate/Invoke/Result 是 lifecycle stages
- [ ] 不新增 branch point / Anchor / runtime flow / capability milestone
- [ ] L3 定义诚实——不 overclaim model call 路径
- [ ] 复用关系写清——只改 loop.py
- [ ] MCP 关系写清——继承 Tool pipeline，本轮不扩展
- [ ] 不做什么写清
- [ ] 符合 Unified Runtime Flow Contract
- [ ] 符合 Engineering Workflow

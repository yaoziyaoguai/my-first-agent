# Tool Result Feedback Branch Behavior — Implementation Plan

Status: draft
Date: 2026-05-23
Parent: docs/specs/tool-result-feedback-branch-behavior/SPEC.md
Tests: docs/specs/tool-result-feedback-branch-behavior/TDD.md

## Problem Frame

当前 tool execution 生命周期中，tool 执行完成后 result 直接通过 provider 内部机制
注入模型上下文，绕过 RuntimeActionDispatcher → handler → evidence 管道。
这与 memory recall 之前的情况一致——功能存在但未 formalize 为 RuntimeAction。

本轮将 post-execution tool result feedback formalize 为 TOOL_RESULT RuntimeAction。
与 memory recall 的 formalize 模式完全对称。

## Scope Boundary

**In scope:**
- `RuntimeActionType.TOOL_RESULT = "tool.result"` action type
- `ToolResultFeedbackHandler` — 接收 tool result → 格式化 → 生成 prompt section
- Catalog descriptor + dispatcher registration
- 测试文件（17 tests，L1 + L2）

**Out of scope (deferred):**
- core.py / loop.py 生产路径改为 dispatcher.route()（需 L3 支持）
- L3 real_core_loop_runtime_e2e 测试
- TOOL_INVOKE / TOOL_REQUEST handler 实现
- Tool retry / error recovery
- Multi Tool / MCP Tool / Streaming tool result

## Branch Point Judgment

归属 Contract Section 2 **"tool execution / confirmation handling"**。
是 tool.gate（pre-execution）的互补 behavior——post-execution result feedback。
不是新 Anchor / runtime flow / branch point。

## Key Decisions

### D1: RuntimeActionType 命名

`RuntimeActionType.TOOL_RESULT = "tool.result"`，与现有
`tool.gate` / `tool.invoke` / `tool.request` 命名空间一致。

### D2: handler 通过 context.invoke_registered_target() 获取 proof

handler 不直接拼接 prompt 字符串。调用
`context.invoke_registered_target(target_module="ToolRuntime", operation="format_tool_result", payload={...})`
走 catalog adapter，获取 trusted target_module_proof。

### D3: catalog adapter 包装 format_tool_result()

adapter 接收 `{"tool_name": str, "tool_output": str, "execution_status": str, "options": dict}`，
调用独立的 `format_tool_result()` 函数（新建在 handler 文件或独立模块中）。

### D4: prompt section 复用 pattern

handler 拿到 formatted result 后，生成与 `build_memory_section()` 样式一致的
`--- Tool Result ---` 标记的 prompt section。handler 自己负责组装最终 prompt 文本
（因为 tool result 的 section 结构比 memory snapshot 简单——只有一条 result）。

### D5: result formatting 参数

- `rendered_char_budget=500` — 单条 result 最大字符数
- 超长截断以 "…" 标记
- 敏感内容 redact 复用 `_SECRET_PATTERNS`
- 空结果返回 placeholder

### D6: handler 构造参数

`ToolResultFeedbackHandler(*, store: InMemoryMemoryStore | None = None)`，
与 MemoryRecallHandler 一致。store 参数为未来 tool result 可能触发
memory proposal 预留——当前 handler 不写 store。

### D7: core.py / loop.py 暂不修改

本轮只做 handler + catalog + dispatcher + 测试。loop.py 中的 tool 执行
结果注入路径保持不变。L3 real_core_loop_runtime_e2e deferred。

## Implementation Units

### U1: TOOL_RESULT RuntimeActionType → schema.py

**Files:**
- Modify: `agent/runtime_integration/schema.py`（在 RuntimeActionType enum 中添加一行）

**Goal:** 在 RuntimeActionType 枚举中新增 `TOOL_RESULT = "tool.result"`，
与 TOOL_GATE 并列。

**Patterns to follow:** 与其他 action type 一致的 StrEnum 命名和值格式。

**Execution note:** 一行变更，无测试依赖。

### U2: ToolResultFeedbackHandler → tool_result_feedback.py（新建）

**Files:**
- Create: `agent/runtime_integration/tool_result_feedback.py`

**Goal:** 实现 ToolResultFeedbackHandler，接收 tool result →
调用 catalog adapter → 格式化 result → 生成 prompt section →
返回 evidence。

**Approach:**
1. 构造函数接收 `store` 参数（默认 InMemoryMemoryStore）
2. `handle(request, context)`:
   a. 从 payload 提取 tool_name（必填）、tool_output（必填）、execution_status
   b. 验证必填字段
   c. 调用 `context.invoke_registered_target(target_module="ToolRuntime", operation="format_tool_result", payload={...})`
   d. 从 observed_call.value 获取 formatted result
   e. 生成 `--- Tool Result ---` prompt section
   f. 判断 disposition（injected/truncated/error/empty）
   g. 返回 `context.success(...)`
3. 独立 helper 函数:
   - `format_tool_result(tool_name, tool_output, execution_status, options)` — adapter target
   - `_redact_sensitive_content(text)` — 复用 _SECRET_PATTERNS
   - `_build_tool_result_section(formatted_output, tool_name, disposition)` — prompt section 组装

**Patterns to follow:** `agent/runtime_integration/memory_recall.py:MemoryRecallHandler`

### U3: Catalog descriptor + dispatcher registration → evidence.py + phase1_hook.py

**Files:**
- Modify: `agent/runtime_integration/evidence.py`（新增 catalog descriptor + adapter）
- Modify: `agent/runtime_integration/phase1_hook.py`（注册 TOOL_RESULT handler）

**Goal:**
- 编写 `_tool_result_format_adapter` 函数
- 在 `RuntimeActionTargetCatalog._bindings` 中新增 descriptor
- 在 `build_phase1_dispatcher()` 中注册 TOOL_RESULT → ToolResultFeedbackHandler

**Patterns to follow:**
- adapter: `_memory_recall_snapshot_adapter` 模式
- descriptor: `_descriptor("tool.result", ...)` 模式
- registration: 与 TOOL_GATE 注册并列

### U4: 测试文件 → test_tool_result_feedback_branch_behavior.py（新建）

**Files:**
- Create: `tests/runtime_integration/test_tool_result_feedback_branch_behavior.py`

**Goal:** 按 TDD.md 实现 Phase A-F 测试（17 tests）。

**Test phases:**
- Phase A: Result Injection Happy Path (A1-A4)
- Phase B: Empty / Missing Payload (B1-B3)
- Phase C: No Side Effects (C1-C4)
- Phase D: Evidence Classification (D1-D2)
- Phase E: Regression Isolation (E1-E2)
- Phase F: Negative / Edge Cases (F1-F2)

**Patterns to follow:** `tests/runtime_integration/test_memory_recall_branch_behavior.py`

## Sequencing

U1 → U2 → U3 → U4（严格顺序，每步依赖前一步）

## Stop Conditions

- 需要新增 branch point → 停止
- 需要真实 API / .env → 停止
- 需要真实 tool execution → 停止
- 发现 SPEC 错 → 回 SPEC
- 发现 TDD 错 → 回 TDD
- 同一问题最多 2 次 focused fix；第 2 次仍失败 → 停止

## Allowed Modifications

- `agent/runtime_integration/schema.py` — 新增 TOOL_RESULT
- `agent/runtime_integration/tool_result_feedback.py` — 新建 handler
- `agent/runtime_integration/evidence.py` — 新增 adapter + descriptor
- `agent/runtime_integration/phase1_hook.py` — 注册 handler
- `tests/runtime_integration/test_tool_result_feedback_branch_behavior.py` — 新建测试

## Forbidden Modifications

- ToolGateHandler / tool_gate.py
- MemoryRecallHandler / memory_recall.py
- MemoryRetainHandler / memory_retain.py
- MemoryTurnEndProposalHandler / memory_hook.py
- TOOL_REGISTRY 内容
- loop.py / core.py 核心 orchestration
- Tool/MCP/Skill/Checkpoint
- memory store 写入语义

## Regression Risk

- 在 phase1_hook.py 中新增 handler 注册不影响已有 TOOL_GATE / MEMORY_PROPOSE /
  MEMORY_TURN_END_PROPOSAL / MEMORY_RECALL
- 新增 schema 枚举值不改变已有 action type 行为
- 新增 catalog descriptor 不改变已有 descriptor 解析

## Implementation Notes

新建: `docs/implementation-notes/tool-result-feedback-branch-behavior.md`

## Review Checklist

- [ ] TOOL_RESULT 归属 "tool execution / confirmation handling"
- [ ] 不新增 branch point / Anchor / runtime flow
- [ ] handler 通过 context.invoke_registered_target() 获取 proof
- [ ] catalog descriptor 正确绑定 action_type + handler + target_module + adapter
- [ ] fake/real 只有 tool output 来源不同
- [ ] 测试覆盖 happy path / empty / missing / no side effects / evidence classification /
  regression / negative
- [ ] 不修改 ToolGateHandler / MemoryRecallHandler / TOOL_REGISTRY
- [ ] 不读取真实数据 / .env / API

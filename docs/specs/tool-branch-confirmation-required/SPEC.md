# Tool Branch: confirmation_required Behavior SPEC

Status: draft
Date: 2026-05-22
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## 1. Branch Point 判断

**Is this a new capability milestone?** No.

**Is this a branch behavior test under an existing capability?** Yes.

**Is this a harness/subsystem-only validation?** No — `confirmation_required` 可通过
`core.chat` → runtime loop → `route_from_runtime_loop()` 到达，具备
`real_core_loop_runtime_e2e` 路径。

**Branch point:** `tool.gate`（Contract §2, §3 已定义）。

**Branch behaviors under `tool.gate`:**

| Behavior | 语义 | 当前覆盖状态 |
|----------|------|-------------|
| `allowed` | 工具通过 gate，可执行 | 已有 dogfood 验证 |
| `confirmation_required` | 工具需要用户确认 | **本 SPEC 目标** |
| `blocked` | 工具被 policy 阻止 | 负例测试即可 |
| `not_found` | 工具不在 registry | 负例测试即可 |

`blocked` 和 `not_found` 是负例，不需要独立 SPEC——在 TDD 阶段作为 branch behavior
test 覆盖即可。

## 2. Behavior Scope

### 2.1 confirmation_required 语义

`confirmation_required` 表示：tool gate 检查通过（工具存在、可见、不在黑名单），但
confirmation policy 要求在执行前征得用户确认。

触发条件（`tool_gate.py:103-106, 128-131`）：

1. 工具在 `TOOL_REGISTRY` 中存在
2. 工具名不在 `_FORBIDDEN_TOOL_NAMES` 中
3. 工具名不以 `_` 开头（或为 `_safe_noop` 通过 allowlist）。
   `_safe_noop` 的特殊性仅在 internal tool allowlist；allowlist 通过后仍走
   同一 `needs_tool_confirmation` policy / gate logic，不存在专用 gate path。
4. 工具在 `get_model_visible_tools()` 返回列表中
5. `needs_tool_confirmation(tool_name, tool_args)` 返回 `True`

`needs_tool_confirmation` 逻辑（`tool_registry.py:407-417`）：

```python
def needs_tool_confirmation(name, tool_input):
    if name not in TOOL_REGISTRY:
        return True
    confirmation = TOOL_REGISTRY[name]["confirmation"]
    if confirmation == "always":
        return True
    elif confirmation == "never":
        return False
    elif callable(confirmation):
        return confirmation(tool_input)
    return True
```

因此 `confirmation_required` 有三条子路径：

| 子路径 | 条件 | confirmation 字段值 |
|--------|------|-------------------|
| `always` | 工具注册为 `confirmation="always"` | `"always"` |
| `callable_true` | 工具注册 callable，对给定 args 返回 True | callable |
| `default` | 工具未注册 confirmation 字段 | 任意非 "never" 非 callable 值 |

### 2.2 不在本 SPEC 范围

- **Tool Confirmation UI 交互**：用户如何确认/拒绝工具的 UI 流程不属于 tool gate
  branch behavior。`tool.gate` 只负责判定 gate disposition，不负责用户交互。
- **工具实际执行**：confirmation 通过后的工具调用执行不属于 gate 范围。
- **confirmation timeout/expiry**：不在本轮范围。

## 3. 当前代码状态

### 3.1 Gate 路径已存在

`ToolGateHandler.handle()` 在 `tool_gate.py:103-106` 和 `:128-131` 已正确返回
`status="confirmation_required"`，evidence 中 `decision="confirmation_required"`。

### 3.2 当前 loop 调用不触发 confirmation_required

`loop.py:113` 的 TOOL_GATE action 使用 `tool_name="_safe_noop"`，该工具的
`confirmation="never"`（`safe_noop.py`），因此 `needs_tool_confirmation` 始终返回
`False` → gate_disposition 始终为 `"allowed"`。

要让 `confirmation_required` 被覆盖，需要 loop 中传入一个 confirmation policy 返回
True 的工具名，或修改 `_safe_noop` 的 confirmation 配置（不推荐——`_safe_noop`
的语义是无害内部工具）。

### 3.3 needs_tool_confirmation 的 callable 路径

`needs_tool_confirmation` 支持 callable confirmation——当 `confirmation` 是函数时，
以 `tool_input` 为参数调用。这允许基于 tool args 动态决定是否需要确认。

## 4. Fake/Real 配置层边界

Unified Runtime Flow Contract §1 规定：fake 和 real **共享同一业务流**，仅在配置和
adapter 层不同。

对于 `confirmation_required` 这意味着：

- `ToolGateHandler.handle()` 的 gate 判定逻辑对 fake/real 完全相同
- `needs_tool_confirmation()` 的调用路径相同
- fake 和 real 的区别仅在于：
  - **provider_kind**：fake 环境为 `"fake"`，real 环境为实际 provider
  - **TOOL_REGISTRY 内容**：fake 环境使用 `DogfoodOverlayTool`，real 环境使用
    production registry
  - **dispatcher entry**：fake dogfood 走 `dispatcher.route()`，real loop 走
    `dispatcher.route_from_runtime_loop()`

不允许：
- fake-only 的 confirmation_required 代码路径
- real-only 的 confirmation_required 代码路径
- provider kind 作为 confirmation 判定分支条件

## 5. Dogfood 边界

### 5.1 允许的做法

```text
dogfood script → core.chat → runtime loop → route_from_runtime_loop()
  → ToolGateHandler.handle() → evidence
```

dogfood 脚本配置 scenario（包括注册一个 `confirmation="always"` 的工具），
调用 `core.chat`，然后收集 runtime-produced evidence 验证 gate_disposition。

**当前可达性说明：** 上述路径依赖 Open Question #1 的解决。当前 runtime loop
（`loop.py:113`）硬编码 `tool_name="_safe_noop"`（`confirmation="never"`），
因此 `confirmation_required` 路径当前不可达。如何让 TOOL_GATE 选取
confirmable tool（例如通过 `requested_tool_name` / scenario config 的最小配置化）
是 TDD / Implementation Plan 阶段必须首先决策的问题。这不是新 branch point，
也不是新 Anchor。不得通过新增 fake loop、fake dispatcher 或 dogfood-only
path 来解决。

### 5.2 禁止的做法

- dogfood 调用 `dispatcher.route()` 直接构造 TOOL_GATE request
- dogfood 调用 `ToolGateHandler.handle()` 跳过 dispatcher
- dogfood 调用 `needs_tool_confirmation()` 直接验证
- dogfood 自己生成 proof / evidence

### 5.3 分类预期

| 路径 | 最高分类 | 备注 |
|------|---------|------|
| `core.chat` → runtime loop → `route_from_runtime_loop()` | `real_core_loop_runtime_e2e` | 需 OQ#1 解决后可达；当前 `_safe_noop` 仅覆盖 `allowed` |
| dogfood `dispatcher.route()` 直接调用 | `harness_runtime_e2e` | 需 target proof 完整 |
| dogfood 直接调用 `ToolGateHandler.handle()` | `subsystem_integration` | — |

`confirmation_required` 是目标 branch behavior。当前 hard-coded `_safe_noop`
只能覆盖 `allowed` safe path。`confirmation_required` 的
`real_core_loop_runtime_e2e` 路径需要后续 TDD / Implementation Plan 提供
`requested_tool_name` / scenario config 的最小配置化设计。

## 6. SPEC 不做什么

1. **不新增 Anchor** — `confirmation_required` 是 `tool.gate` 的 branch behavior
2. **不新增 capability milestone** — tool gate 能力已存在
3. **不新增 RuntimeActionType** — `TOOL_GATE` 已定义
4. **不新增 handler** — `ToolGateHandler` 已实现
5. **不修改 `ToolGateHandler.handle()`** — gate 逻辑已正确
6. **不修改 loop.py 的 TOOL_GATE payload** — 当前 `_safe_noop` 用法正确，
   `confirmation_required` 覆盖通过 TDD 阶段引入合适的测试工具达成
7. **不新增 `_confirmable_noop`** 或任何带 `_` 前缀的内部工具 — 使用
   `DogfoodOverlayTool` 或测试专用注册工具
8. **不实现 Tool Confirmation UI** — gate disposition 与用户交互是不同关注点
9. **不引入** Tool Args / Tool Result / Retry / Error Recovery / Multi Tool /
   MCP Tool / Skill / Checkpoint / Streaming / SubAgent

## 7. 测试策略概要

以下为 TDD 阶段指导，非本 SPEC 的执行内容。

### 7.1 正例（confirmation_required 路径）

| 测试 | confirmation 配置 | 预期 gate_disposition |
|------|------------------|----------------------|
| `always` 子路径 | `confirmation="always"` | `confirmation_required` |
| callable 返回 True | `confirmation=lambda args: True` | `confirmation_required` |
| callable 基于 args 返回 True | `confirmation=lambda args: args.get("risk") == "high"` | `confirmation_required` |

### 7.2 负例（非 confirmation_required 路径——仅覆盖，不展开 SPEC）

`blocked` 和 `not_found` 是 `tool.gate` branch point 的负例 branch behavior。
本轮仅作为边界语义说明，实际测试在 TDD 阶段作为 negative test coverage 覆盖。

规则：
- 不单独开新 Anchor
- 不单独开新 capability milestone
- 不扩大到 Tool Args / Tool Result / Retry / Error / Multi Tool / MCP Tool
- 本 SPEC 当前只定义 `confirmation_required` behavior

| 测试 | 条件 | 预期 gate_disposition |
|------|------|----------------------|
| `never` → allowed | `confirmation="never"` | `allowed` |
| `blocked` | callable 返回 `"block"` 或工具在 `_FORBIDDEN_TOOL_NAMES` | `rejected` |
| `not_found` | 工具名不在 registry | `None` (decision: `not_found`) |

### 7.3 分类边界测试

| 测试 | 路径 | 预期 evidence_level |
|------|------|-------------------|
| real loop confirmation | `route_from_runtime_loop()` | `real_core_loop_runtime_e2e` |
| harness direct confirmation | `dispatcher.route()` | `harness_runtime_e2e` |

## 8. Open Questions

1. **如何在不修改 loop.py 的前提下让 TOOL_GATE 覆盖 confirmation_required？**
   - 方案 A：loop.py 支持配置化的 tool_name（而非硬编码 `_safe_noop`）
   - 方案 B：dogfood 注册一个 `confirmation="always"` 的 fake tool，让 loop
     在 fake provider 下使用该工具名
   - 方案 C：`_safe_noop` 的 confirmation 从 `"never"` 改为可配置
   - 推荐在 TDD/Implementation Plan 阶段决策

2. **callable confirmation 的 tool_input 结构是什么？**
   - 当前 `needs_tool_confirmation(name, tool_input)` 接收 `tool_input` 参数
   - `tool_input` 是 `tool_args` 的 dict 形式
   - 需要在 TDD 阶段明确 callable 的签名约定

3. **confirmation_required 是否需要与 Tool Confirmation UI 集成测试？**
   - 不需要。`tool.gate` 的职责在返回 `confirmation_required` status 时结束
   - UI 交互是独立关注点

## 9. Review Checklist

- [ ] branch point 判断正确（`tool.gate`，非新 Anchor）
- [ ] behavior scope 明确（`confirmation_required` 的三条子路径）
- [ ] 不包含禁止事项（§6 全部检查）
- [ ] fake/real 边界清晰（共享业务流，仅配置层不同）
- [ ] dogfood 边界清晰（必须走 `core.chat`，不可 direct dispatch）
- [ ] 与 Unified Runtime Flow Contract 一致
- [ ] 无副作用：no shell / no file write / no external process / no MCP / no real API
- [ ] open questions 未假装已解决

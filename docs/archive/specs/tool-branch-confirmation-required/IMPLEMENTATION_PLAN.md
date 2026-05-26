# Implementation Plan: Tool Branch confirmation_required Behavior Test

Status: draft
Date: 2026-05-23
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
SPEC: [Tool Branch confirmation_required Behavior SPEC](SPEC.md)
TDD: [TDD / Test Plan](TDD.md)

## 1. Problem Frame

让 `real_core_loop_runtime_e2e` 路径（`core.chat` → runtime loop → `route_from_runtime_loop()`）可覆盖 `tool.gate` branch point 的 `confirmation_required` behavior。

当前 loop 硬编码 `tool_name="_safe_noop"`（`confirmation="never"`）→ gate_disposition 始终为 `"allowed"`。需要最小配置化让同一 `tool.gate` branch point 也能产生 `confirmation_required`。

## 2. Scope Boundary

### 2.1 In Scope

- 新增 `_confirmable_noop` 内部工具（`confirmation="always"`）
- 扩展 `tool_gate.py` allowlist
- `LoopDependencies` 增加可选 `tool_gate_tool_name` 字段
- loop.py 从 dependencies 读取 tool_name 替代硬编码
- TDD L1/L2/L3 全部测试实现（`tests/runtime_integration/test_tool_branch_confirmation_required.py`）
- Implementation notes

### 2.2 NOT in Scope

- Tool Args / Tool Result feedback
- Retry / Error Recovery
- Multi Tool / MCP Tool
- Real shell/file tool / real API
- UI confirmation interaction
- True model tool_use execution chain
- Fake/real 双路径
- Dogfood 直接构造 RuntimeAction 冒充 E2E
- 放宽所有 `_` 前缀工具
- ToolRegistry governance 变更

### 2.3 Deferred to Follow-Up Work

- Tool confirmation UI 集成（`tool.gate` 返回 `confirmation_required` 后的用户交互）
- Callable confirmation 的动态 args 语义标准化
- Streaming / SubAgent / Checkpoint 的 TOOL_GATE 交互

## 3. Key Technical Decisions

### Decision 1: OQ#1 — 最小配置化方案

采纳方案：**`LoopDependencies.tool_gate_tool_name` 可选字段**。

- 在 `LoopDependencies` 中新增 `tool_gate_tool_name: str = "_safe_noop"`
- `_try_phase1_turn_end_runtime_action` 从 `dependencies.tool_gate_tool_name` 读取，替代硬编码
- 默认值 `"_safe_noop"` 保持向后兼容
- L3 测试通过构造 `LoopDependencies(tool_gate_tool_name="_confirmable_noop", ...)` 配置

为什么不选其他方案：

- 方案 B（dogfood 注册 fake tool）：依赖 dogfood overlay 机制，引入了 fake overlay 作为 gate path 选择器 → 违反 fake/real 共享业务流
- 方案 C（修改 `_safe_noop` confirmation 为可配置）：破坏 `_safe_noop` 的 `allowed` 语义，且影响现有 `tool_anchor_fake` 测试
- 方案 A（loop.py 配置化 tool_name）：通过 `LoopDependencies` 注入是最轻的方式——loop 保持 thin orchestration，配置决策在调用方

### Decision 2: 新增 `_confirmable_noop`

**采纳——新增。**

理由：
- 复用已有 `_safe_noop` 不可行——其 `confirmation="never"` 是设计语义
- 不新增则无零副作用 confirmable production tool 可用
- `_confirmable_noop` 与 `_safe_noop` 同等安全：zero-arg, no shell, no file write, no external process, no network

不变式保证：
- 不放宽所有 `_` 前缀工具——allowlist 保持显式枚举
- 不改变 ToolRegistry governance——仍通过 `@register_tool` 注册
- 不引入新 gate path——allowlist 通过后走同一 `needs_tool_confirmation` 检查

### Decision 3: allowlist 扩展方式

`tool_gate.py:96` 从 `tool_name == "_safe_noop"` 改为 `tool_name in ("_safe_noop", "_confirmable_noop")`。

不引入 data-driven allowlist set——两个工具足够简单，tuple 成员检查是最小 diff。

## 4. Implementation Units

### U1. Test File — Negative & Classification Tests (L1/L2)

**Goal:** 实现 TDD Phase A/B/C/D/E 中所有不依赖 OQ#1 解决的测试。

**Dependencies:** 无（纯测试文件，不修改 production code）

**Files:**
- Create: `tests/runtime_integration/test_tool_branch_confirmation_required.py`

**Approach:**
复用 `test_tool_anchor_fake.py` 中的 `_build_phase1_dispatcher_with_tool_gate()` 和 `_SpyDispatcher`。测试 setup 通过 `monkeypatch` 在 `TOOL_REGISTRY` 临时注册 confirmable test tool，teardown 移除。

实现 TDD §6 中除 B2 外的全部测试（共 22 个）：
- A1-A7: confirmation_required 正例
- B1, B3, B4: Classification boundaries（B2 DEFERRED 到 U4）
- C1-C4: Negative coverage (blocked / not_found)
- D1-D4: Memory / Tool isolation
- E1, E2: Fake/Real boundary

**Execution note:** Test-first. 所有测试先写，确认 FAIL（因 confirmable test tool 的注册路径不触发 confirmation_required 的特定场景待确认），但 L1/L2 测试应 GREEN——这些测试通过测试 setup 中的临时 TOOL_REGISTRY 注册即可触发 behavior，不依赖 production code 变更。

**Patterns to follow:**
- `tests/runtime_integration/test_tool_anchor_fake.py` — 同目录、同模式、复用 helper
- TDD §7 中定义的 `_register_test_confirmable_tool()` helper

**Test scenarios:** 见 TDD §6.1–6.5 的完整矩阵（A1-E2，共 22 个测试）。每个测试场景已定义 test name、purpose、setup、action、expected evidence、forbidden behavior。

**Verification:**
- `pytest tests/runtime_integration/test_tool_branch_confirmation_required.py -v` — 22/22 pass
- L1/L2 测试全部 GREEN

---

### U2. `_confirmable_noop` Tool

**Goal:** 新增内部 confirmable noop 工具，供 L3 `real_core_loop_runtime_e2e` 路径使用。

**Dependencies:** U1

**Files:**
- Create: `agent/tools/confirmable_noop.py`
- Modify: `agent/runtime_integration/tool_gate.py` (line ~96, allowlist 扩展)

**Approach:**
1. 创建 `agent/tools/confirmable_noop.py`，镜像 `agent/tools/safe_noop.py` 结构
   - `@register_tool(name="_confirmable_noop", confirmation="always", capability="local_action", risk_level="low", output_policy="none", meta_tool=False)`
   - 函数体：`return "confirmable_noop: ok"`
   - `_` 前缀 → `get_model_visible_tools()` 排除（模型不可见）
2. 在 `tool_gate.py:96` 将 allowlist 从 `tool_name == "_safe_noop"` 改为 `tool_name in ("_safe_noop", "_confirmable_noop")`

**Patterns to follow:**
- `agent/tools/safe_noop.py` — 注册结构、字段值、docstring 风格完全相同

**Test scenarios:**
- 确认 `_confirmable_noop` 注册在 TOOL_REGISTRY
- 确认 `get_model_visible_tools()` 不包含 `_confirmable_noop`
- 确认 `needs_tool_confirmation("_confirmable_noop", {})` 返回 True
- 确认 allowlist 对 `_confirmable_noop` 放行

**Verification:**
- `python -c "from agent.tools.confirmable_noop import _confirmable_noop; print(_confirmable_noop())"` → `confirmable_noop: ok`
- `pytest tests/runtime_integration/test_tool_branch_confirmation_required.py -v` — 全部通过
- `pytest tests/runtime_integration/test_tool_anchor_fake.py -v` — 全部通过（回归）

---

### U3. LoopDependencies tool_gate_tool_name

**Goal:** 让 loop 的 TOOL_GATE action 支持可配置 tool_name，替代硬编码 `_safe_noop`。

**Dependencies:** U2

**Files:**
- Modify: `agent/loop.py` — `LoopDependencies` dataclass (~line 161) 和 `_try_phase1_turn_end_runtime_action` (~line 113)

**Approach:**
1. `LoopDependencies` 新增字段：`tool_gate_tool_name: str = "_safe_noop"`
2. `_try_phase1_turn_end_runtime_action` 中 `"tool_name": "_safe_noop"` → `"tool_name": dependencies.tool_gate_tool_name if dependencies else "_safe_noop"`
3. 由于 `_try_phase1_turn_end_runtime_action` 接收 `dependencies` 参数且已有 `provider_kind`/`provider_external_call` 的解引用模式，直接复用同一模式

变更量：
- `LoopDependencies`: +1 字段（~1 行 + docstring 更新）
- `_try_phase1_turn_end_runtime_action`: 1 行变更（`"_safe_noop"` → `getattr(dependencies, "tool_gate_tool_name", "_safe_noop")`）

默认值 `"_safe_noop"` 保证零行为变更——所有现有调用方无需修改。

**Execution note:** 实现后先运行现有测试确认回归通过，再进入 U4。

**Patterns to follow:**
- `LoopDependencies.provider_kind` / `provider_external_call` — 同模式的可选配置注入
- `_try_phase1_turn_end_runtime_action` 中对 dependencies 的 `getattr` 解引用模式

**Test scenarios:**
- 默认值回归：不传 `tool_gate_tool_name` → 行为与当前完全一致
- 显式传入 `"_confirmable_noop"` → TOOL_GATE action 使用该 tool_name

**Verification:**
- `pytest tests/runtime_integration/test_tool_anchor_fake.py -v` — 全部通过（回归）
- `pytest tests/runtime_integration/ -v` — 全部通过
- `ruff check agent/loop.py` — exit code 0

---

### U4. L3 Real Core Loop Positive Path Test (B2)

**Goal:** 实现 TDD B2 测试——证明 `real_core_loop_runtime_e2e` 路径可覆盖 `confirmation_required`。

**Dependencies:** U3

**Files:**
- Modify: `tests/runtime_integration/test_tool_branch_confirmation_required.py` — 新增 B2 测试

**Approach:**
B2 测试通过 `LoopDependencies(tool_gate_tool_name="_confirmable_noop", ...)` 让 loop 的 TOOL_GATE action 传递 confirmable tool name。

测试构造：
1. 构建包含 `ToolGateHandler` 的 dispatcher
2. 构造 `LoopDependencies` 并设置 `tool_gate_tool_name="_confirmable_noop"`
3. 通过 spy dispatcher 拦截 `route_from_runtime_loop()` 调用
4. 验证 evidence 中：`evidence_level=real_core_loop_runtime_e2e`, `dispatcher_origin=runtime_loop`, `runtime_loop_invoked=True`, `gate_disposition=confirmation_required`

由于测试不真实调用 `core.chat()`（那需要 model/provider），改为验证 `route_from_runtime_loop()` 路径的 classification 结果——dispatcher 的 `route_from_runtime_loop()` 方法在 `evidence_extra` 中设置 `runtime_loop_invoked=True` 和 `dispatcher_origin="runtime_loop"`。

**Execution note:** Test-first. 写 B2 测试 → 确认 PASS（依赖 U2/U3 已使路径可达）。

**Test scenarios:**
- B2: `test_route_from_runtime_loop_is_real_core_loop_e2e` — TDD §6.2 已定义完整 setup/action/expected/forbidden

**Verification:**
- `pytest tests/runtime_integration/test_tool_branch_confirmation_required.py::test_route_from_runtime_loop_is_real_core_loop_e2e -v` — PASS
- 全部 23 个测试通过
- B2 evidence 中 `evidence_level == "real_core_loop_runtime_e2e"` 且 `gate_disposition == "confirmation_required"`

---

### U5. Dogfood / Report Verification

**Goal:** 运行现有 dogfood 脚本确认无回归，生成 implementation notes。

**Dependencies:** U4

**Files:**
- Create: `docs/implementation-notes/tool-branch-confirmation-required.md`

**Approach:**
1. 运行 `scripts/dogfood_phase1_real_core_loop.py` 确认 `_safe_noop` → `allowed` 行为无回归
2. 运行 `pytest tests/runtime_integration/ -v` 确认全部通过
3. 运行 `ruff check agent/ tests/` 确认无 lint 错误
4. 运行 `git diff --check` 确认无空白冲突
5. 编写 implementation notes 记录：实际变更、决策理由、发现、回退记录

**Verification:**
- `python scripts/dogfood_phase1_real_core_loop.py` — exit code 0，`_safe_noop` allowed path 无回归
- `pytest tests/runtime_integration/ -v` — 全部通过
- `ruff check agent/ tests/` — All checks passed
- `git diff --check` — exit code 0

---

## 5. Implementation Sequencing

```
U1 (tests, L1/L2 negative + classification)
  → U2 (_confirmable_noop + allowlist)
    → U3 (LoopDependencies.tool_gate_tool_name)
      → U4 (L3 B2 test)
        → U5 (dogfood + notes)
```

每步必须：
- 先跑现有测试确认树健康
- 完成后跑全量 runtime_integration 测试
- 不可跳过 U1 — 负例/分类边界测试必须在实现前到位

## 6. Stop Conditions

- 如果需要新增 branch point → **STOP**，回到 Contract/SDD
- 如果需要修改 Unified Runtime Flow Contract → **STOP**，回到 Contract
- 如果需要真实 API / `.env` → **STOP**，升级 Ask User
- 如果测试设计与 SPEC 冲突 → **STOP**，回 TDD
- 如果发现 SPEC 对 branch point 判断错误 → **STOP**，回 SPEC
- 同一问题在同一阶段最多 2 次修复尝试 → 第 3 次前 **Ask User**

## 7. Allowed vs Forbidden Modifications

**Allowed:**
- `agent/tools/confirmable_noop.py` (new)
- `agent/runtime_integration/tool_gate.py` (allowlist: 1 line)
- `agent/loop.py` (LoopDependencies: +1 field; _try_phase1_turn_end_runtime_action: ~1 line)
- `tests/runtime_integration/test_tool_branch_confirmation_required.py` (new)
- `docs/implementation-notes/tool-branch-confirmation-required.md` (new)

**Forbidden:**
- Tool Args / Tool Result feedback
- Retry / Error Recovery
- Multi Tool / MCP Tool
- Real shell/file tool / real API
- UI confirmation interaction
- True model tool_use execution chain
- Fake/real 双路径
- Dogfood 直接构造 RuntimeAction 冒充 E2E
- 修改 agent/ (except the 3 allowed files above)
- 修改 tests/ (except the 1 allowed file above)
- 修改 scripts/

## 8. Implementation Notes Path

`docs/implementation-notes/tool-branch-confirmation-required.md`

## 9. Regression Risk

| Risk | Mitigation |
|------|-----------|
| `_safe_noop` → `allowed` path 被破坏 | `LoopDependencies.tool_gate_tool_name` 默认值 `"_safe_noop"` + 现有 `test_tool_anchor_fake.py` 回归测试 |
| allowlist 扩展引入安全漏洞 | `_confirmable_noop` 与 `_safe_noop` 同等零副作用；allowlist 保持显式枚举 |
| LoopDependencies 新字段破坏现有调用方 | 默认值保证向后兼容；`getattr` fallback 模式 |

## 10. Review Checklist

- [ ] 不新增 branch point（`tool.gate` 已存在）
- [ ] 不新增 Anchor / capability milestone
- [ ] OQ#1 已解决（LoopDependencies.tool_gate_tool_name）
- [ ] `_confirmable_noop` 满足所有安全性约束
- [ ] allowlist 扩展不放宽所有 `_` 前缀工具
- [ ] loop.py 保持 thin orchestration
- [ ] 不引入 fake/real 双路径
- [ ] TDD-first 执行顺序
- [ ] Stop conditions 明确
- [ ] Allowed/forbidden 边界清晰
- [ ] 与 Unified Runtime Flow Contract 一致
- [ ] 与 ENGINEERING_WORKFLOW.md 一致

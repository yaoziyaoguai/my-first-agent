# Stage Closeout: Tool Branch confirmation_required Behavior

Status: closed
Date: 2026-05-23
Implementation Notes: [tool-branch-confirmation-required.md](tool-branch-confirmation-required.md)
SPEC: [SPEC.md](../specs/tool-branch-confirmation-required/SPEC.md)
TDD: [TDD.md](../specs/tool-branch-confirmation-required/TDD.md)
Implementation Plan: [IMPLEMENTATION_PLAN.md](../specs/tool-branch-confirmation-required/IMPLEMENTATION_PLAN.md)

## 1. 本阶段完成了什么

### 1.1 Tool Branch Behavior: allowed

`tool.gate` branch point 下的 `allowed` behavior — 通过 `_safe_noop`（`confirmation="never"`）覆盖，`real_core_loop_runtime_e2e` 分类。

在 `confirmation_required` 阶段之前已经完成（`test_tool_anchor_fake.py`），本阶段未修改，通过回归验证确认无退化。

### 1.2 Tool Branch Behavior: confirmation_required

`tool.gate` branch point 下的 `confirmation_required` behavior — 通过 `_confirmable_noop`（`confirmation="always"`）覆盖，含 `real_core_loop_runtime_e2e` 分类。

**实现范围（4 个 Implementation Units）：**

| Unit | 内容 | 状态 |
|------|------|------|
| U1 | 测试文件（21 tests, L1/L2 全覆盖） | 完成 |
| U2 | `_confirmable_noop` 内部工具 + allowlist 扩展 | 完成 |
| U3 | `LoopDependencies.tool_gate_tool_name` 字段 | 完成 |
| U4 | B2 L3 测试（`route_from_runtime_loop` → `real_core_loop_runtime_e2e`） | 完成 |
| P2 fix | B5 测试（`LoopDependencies` → loop/turn-end path 消费证明） | 完成 |
| P3 fix | `phase1_hook.py` docstring 更新 | 完成 |

### 1.3 关键架构决策

- **OQ#1 解决方案：** `LoopDependencies.tool_gate_tool_name: str = "_safe_noop"` — 最小配置化，默认值保证零行为变更
- **`_confirmable_noop`：** 内部非模型可见工具，zero-arg, no shell, no file write, no external process, no MCP, no real API
- **Allowlist 模式：** `tool_name in ("_safe_noop", "_confirmable_noop")` — 显式枚举，不放宽所有 `_` 前缀工具
- **fake/real 共享：** 同一 `ToolGateHandler.handle()` gate 逻辑，同一 `_try_phase1_turn_end_runtime_action` 函数

## 2. 真实完成范围

### 2.1 三层测试覆盖

| 层级 | 分类 | 测试数 | 状态 |
|------|------|--------|------|
| L1 | `subsystem_integration` | A5, B3 | 通过 |
| L2 | `harness_runtime_e2e` | A1-A4, A6-A7, B1, B4, C1-C4, D1-D4, E1-E2 | 通过 |
| L3 | `real_core_loop_runtime_e2e` | B2, B5 | 通过 |

### 2.2 测试矩阵覆盖

- **Phase A:** confirmation_required 正例 — always / callable_true / callable_args / default / function_not_invoked / no_side_effects / evidence_structure (7 tests)
- **Phase B:** classification boundaries — direct dispatcher→harness / real_core_loop (B2) / direct handler→subsystem / payload anti-spoofing / loop dependencies→payload (B5) (5 tests)
- **Phase C:** negative coverage — not_found / forbidden / callable_block / not_model_visible (4 tests)
- **Phase D:** memory/tool isolation — cross-contamination prevention (4 tests)
- **Phase E:** fake/real boundary — same gate logic / no real API (2 tests)

**Total: 22 tests**

### 2.3 修改文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `agent/loop.py` | Modify | LoopDependencies +1 field, _try_phase1_turn_end_runtime_action ~3 lines |
| `agent/runtime_integration/tool_gate.py` | Modify | allowlist 1 line |
| `agent/runtime_integration/phase1_hook.py` | Modify | docstring update |
| `agent/tools/__init__.py` | Modify | import _confirmable_noop |
| `agent/tools/confirmable_noop.py` | Create | 新内部工具 |
| `tests/runtime_integration/test_tool_branch_confirmation_required.py` | Create | 22 tests |
| `tests/test_tool_registry_contract.py` | Modify | EXPECTED_INTERNAL_TOOL_SPECS +1 entry |
| `docs/implementation-notes/tool-branch-confirmation-required.md` | Create | implementation notes |

## 3. 没做什么（诚实声明）

### 3.1 按 SPEC §6 / Plan §2.2 明确排除

- Tool Args / argument passing
- Tool Result feedback
- Retry / Error Recovery
- Multi Tool / MCP Tool
- Real shell/file tool / real API
- UI confirmation interaction
- True model tool_use execution chain
- Fake/real 双路径
- Dogfood 直接 RuntimeAction 冒充 E2E
- Callable confirmation 动态 args 语义标准化

### 3.2 按 Plan §2.3 Deferred

- Tool confirmation UI 集成
- Callable confirmation 的动态 args 语义标准化
- Streaming / SubAgent / Checkpoint 的 TOOL_GATE 交互

### 3.3 未触碰的子系统

- Memory（除 Phase D 隔离测试外）
- Checkpoint
- Skill
- Streaming
- SubAgent
- MCP adapter

## 4. Deferred 项

| 项目 | 依赖 | 说明 |
|------|------|------|
| Tool confirmation UI | `tool.gate` 返回 `confirmation_required` 后的用户交互 | 独立关注点，不属于 gate 范围 |
| Callable confirmation args 语义 | 需要标准化 callable 的签名约定 | SPEC OQ#2 未解决 |
| Streaming / SubAgent / Checkpoint TOOL_GATE | 需要对应子系统先有 RuntimeAction | Plan §2.3 deferred |

## 5. 测试 / Gate 结果

### 5.1 最终验证（Post-Remediation）

```
ruff check agent/ tests/ scripts/          — All checks passed
pytest tests/runtime_integration/test_tool_branch_confirmation_required.py — 22/22 pass
pytest tests/runtime_integration/test_tool_anchor_fake.py                 — 14/14 pass
pytest tests/test_tool_registry_contract.py                               — 14/14 pass
pytest tests/runtime_integration/                                         — 180 passed, 4 skipped
pytest (full suite)                                                       — 2951 passed, 18 skipped
git diff --check                                                          — exit code 0
```

### 5.2 Dogfood

```
scripts/dogfood_phase1_real_core_loop.py — PASSED
```

## 6. Push 状态

- **Commit 1:** `74a7eca` feat(runtime): add tool confirmation branch behavior
- **Commit 2:** `36609c8` test(runtime): cover tool confirmation dependency path (P2/P3 remediation)
- **Push:** 已 push 到 origin/main
- **ahead/behind:** 0/0
- **Tags:** 无

## 7. 后续不能 Overclaim 的点

1. **`confirmation_required` 是 branch behavior，不是新 Anchor 或新 capability milestone。** 它和 `allowed` 是 `tool.gate` branch point 下的同级 behavior。
2. **L3 `real_core_loop_runtime_e2e` 路径不经过 `core.chat()`。** B2/B5 测试直接调用 `route_from_runtime_loop()` 或 `_try_phase1_turn_end_runtime_action()`，不涉及真实 model call。这是 TDD/Plan 的设计选择——classification 依赖 dispatcher route method，不依赖 model。
3. **`_confirmable_noop` 不执行真实工具。** 它是内部 noop，仅用于 gate verification。
4. **Tool Args / Tool Result / MCP / Skill / Checkpoint 均未触碰。**
5. **没有 UI 交互覆盖。** `confirmation_required` 只验证 gate disposition，不验证用户确认流程。

## 8. 回退记录

无跨阶段回退。Implementation Audit 发现 P2/P3 两个 finding，均在 Implementation 层修复（focused fix），不涉及上游 SPEC/TDD/Plan 修改。

## 9. 工程流程合规

| Gate | 状态 |
|------|------|
| SPEC Review | 通过 |
| TDD Review | 通过 |
| Plan Review | 通过 |
| Implementation Audit | PARTIAL → P2/P3 fixed → 复审 PASS |
| Push main | 通过（fast-lane，全部条件满足） |

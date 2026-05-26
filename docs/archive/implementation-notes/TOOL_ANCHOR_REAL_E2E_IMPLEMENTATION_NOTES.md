# ToolRegistry Gate Branch Behavior Implementation Notes — historical Anchor phase

> Historical note: this document records the former "Tool Anchor" validation
> work. New work must use Unified Runtime Flow + Branch Behavior terminology and
> reference `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md`. Do not create new
> Tool Anchor milestones from this document.

**Date:** 2026-05-22
**Status:** complete — fake/real shared core path verified

## Implementation Summary

ToolRegistry safe gate validation 是 Tool branch `allowed` behavior 的历史验证记录，证明 ToolRegistry gate 路径通过统一的 `core.chat() → run_main_loop → turn-end hook → RuntimeActionDispatcher → ToolGateHandler → target_module_proof` 核心路径可正确触发。

## Key Decisions

### _safe_noop 作为最小 safe tool

选择 `_safe_noop` 而非 `safe.echo` / `safe.inspect_request`：
- 零参数、零副作用、零输入面 —— 最安全的 gate branch behavior test tool
- `_` 前缀保证模型不可见（`get_model_visible_tools()` 自动过滤）
- `confirmation="never"` 保证 gate disposition 为 `allowed`
- 注册在 production `TOOL_REGISTRY` 中，非 dogfood overlay

### 最小 allowlist 方案

在 `tool_gate.py` 的 `_` 前缀检查中，只放行 `_safe_noop`。其他 `_` 前缀工具仍 blocked。
`_FORBIDDEN_TOOL_NAMES` 检查保持最高优先级，对所有工具有效。
不放宽 ToolRegistry governance — 不修改 `register_tool()` / `execute_tool()` / `needs_tool_confirmation()`。

### TOOL_GATE 独立于 MEMORY

turn-end hook 中 MEMORY 和 TOOL_GATE 两个 action 各自独立构造、独立 route、独立 try/except。
一个 action 的异常不得导致另一个 action 消失。这是 plan §B.2.1 的强制要求。

### 显式 tool_args

TOOL_GATE payload 显式包含 `"tool_args": {}`，避免 `needs_tool_confirmation()` 中的隐式 fallback 链。
未来带参数工具必须传真实 tool_args，不得省略。

## Spec Gaps

- real provider smoke 尚未执行——需等待 real mode opt-in
- 工具确认交互（confirmation_required）路径未覆盖——需要注册 `confirmation="always"` 的 safe tool
- 非 safe tool gate check (risk_level=medium/high) 未覆盖

## Tradeoffs

- tool_gate.py 的 allowlist 逻辑（`_safe_noop` 分支内联了 confirmation 检查）与 `else` 分支有 ~8 行代码重复。不抽取——两个分支的语义不同（allowlist 路径不允许 fall-through 到 `else`），抽取会引入错误的抽象耦合
- dogfood shared checks 与 memory anchor 对称但独立——不复用同一模块，因为字段域不同（tool.gate 有 gate_disposition/decision/production_registry_found 等字段，memory 有 auto_approved/not_confirmed/real_episodes_read 等字段）

## Stop-Condition Near Misses

- 险些违反"不下划线工具无条件放行"——最初方案使用 `pass` fall-through，导致 TOOL_GATE handler 的 elif/else 链路在 Python 语义下不正确。修复为 allowlist 内联 confirmation 检查
- 险些破坏 Memory Anchor regression——最初忘记更新 `test_memory_anchor_fake.py` 和 `test_phase1_real_core_loop.py` 的 `_build_phase1_dispatcher()` 注册 ToolGateHandler，导致 3 个现有测试失败

## Why No Shell / File Write / MCP / External Process

- 本锚点只验证 ToolRegistry gate 路径——gate check 是纯查询操作
- shell / file write / external process 需要不同的 capability level 和 risk 评估，属于未来的 Anchor
- MCP 工具走独立的 handler 注册路径，不在 Phase 1 范围

## Why _safe_noop != Fake ToolRegistry

_safe_noop 是 production TOOL_REGISTRY 中的真实条目，通过 `@register_tool` 装饰器注册。
与 dogfood overlay (`fake.*` 前缀工具) 是两个命名空间——overlay 工具存在于 `ToolGateHandler._dogfood_overlay` dict 中，不写入 production registry。

## Why Tool Anchor Doesn't Touch Memory Governance

MEMORY_CANONICAL_RFC §2.4 明确：ToolRegistry / Safety Config 不属于 Memory。
Tool Anchor 验证的是独立的 tool gate 路径，不修改 `memory_policy` / `memory_runtime` / `memory_fs_store`。
Tool confirmation (`needs_tool_confirmation()`) 和 Memory T1 Confirmation 是不同子系统的不同概念（RFC §10.5）。

## Audit Findings

### P1-01 (2026-05-22 Independent Audit) — tool_registry_contract EXPECTED_MODEL_VISIBLE_TOOLS

**Finding:** `tests/test_tool_registry_contract.py` 的 `EXPECTED_MODEL_VISIBLE_TOOLS` 和 `EXPECTED_INTERNAL_TOOL_SPECS` 未包含新注册的 `_safe_noop`，导致 `test_model_visible_tools_match_runtime_allowed_tools` 和 `test_internal_tool_specs_expose_capability_risk_and_output_policy` 失败。

**Root cause:** `get_tool_definitions()`、`get_tool_specs()`、`get_allowed_tools()` 都迭代全部 `TOOL_REGISTRY` 条目，不按 `_` 前缀过滤。`_safe_noop` 注册进 production registry 后，这些 introspection API 返回的集合自动包含它，但 contract tests 的 expected set 落后于 registry 实际状态。

**Fix:** 将 `"_safe_noop"` 加入 `EXPECTED_MODEL_VISIBLE_TOOLS`，并在 `EXPECTED_INTERNAL_TOOL_SPECS` 中加入其治理 metadata（`capability="local_action"`, `risk_level="low"`, `output_policy="none"`, `confirmation="never"`, `meta_tool=False`）。不改 ToolRegistry governance，不放宽其他 `_` 前缀工具。

**Files changed:** `tests/test_tool_registry_contract.py` (+8 lines)

**Verification:** `pytest -q` → 2924 passed, 18 skipped, 0 failed

## Deferred Risks

- `ToolGateHandler` 的 `_handle_fake_tool` 路径未在 E2E 中触发——需要 dogfood overlay tool 的专门测试
- real provider smoke 下的 `provider_external_call=True` 元数据尚未在 Tool Anchor 中验证

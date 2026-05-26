# TDD / Test Plan: Tool Branch confirmation_required Behavior

Status: draft
Date: 2026-05-22
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
SPEC: [Tool Branch confirmation_required Behavior SPEC](SPEC.md)

## 1. Branch Point 判断

1. **当前任务属于哪个 unified runtime flow branch point？**
   `tool.gate`（Contract §2, §3 已定义）

2. **branch point 是否已存在？**
   是。`RuntimeActionType.TOOL_GATE`（`schema.py:24`）已注册，
   `ToolGateHandler`（`tool_gate.py`）已实现，
   loop `_try_phase1_turn_end_runtime_action`（`loop.py:106-131`）已调用。

3. **这是 branch behavior test，还是需要新增 branch point？**
   这是 branch behavior test。`confirmation_required` 是 `tool.gate` 下的
   branch behavior（与 `allowed`、`blocked`、`not_found` 同级）。

4. **OQ#1 处理：**
   见 §3（OQ#1 处理策略）。

5. **是否需要新增 branch point？**
   不需要。不新增。不标记 blocked。

## 2. 测试分层策略

本轮 TDD 定义三层测试，按实现顺序排列：

| 层级 | 路径 | 最高分类 | 需要 OQ#1 解决？ | 本 TDD 阶段 |
|------|------|---------|-----------------|------------|
| L1: Gate Logic | `ToolGateHandler.handle()` 直接调用 | `subsystem_integration` | 否 | 全部实现 |
| L2: Harness Dispatcher | `dispatcher.route()` | `harness_runtime_e2e` | 否 | 全部实现 |
| L3: Real Core Loop | `dispatcher.route_from_runtime_loop()` | `real_core_loop_runtime_e2e` | **是** | 测试设计完成，实现标记 DEFERRED |

L1/L2 层无需任何 production code 变更即可实现——通过测试 setup 中向
`TOOL_REGISTRY` 临时注册 confirmable test tool 来触发 `confirmation_required` 路径。

L3 层的测试设计在本文档中完整定义，但实现依赖于 OQ#1 的解决。

## 3. OQ#1 处理策略

**OQ#1 原文：** "如何在不修改 loop.py 的前提下让 TOOL_GATE 覆盖
confirmation_required？"

**本 TDD 决策：分阶段处理。**

### 3.1 L1/L2 阶段（本 TDD 实现）

不需要修改 loop.py。测试通过以下方式触发 `confirmation_required`：

- 测试 setup 中在 `TOOL_REGISTRY` 临时插入一个 `confirmation="always"` 的
  无副作用 test tool（名称不以 `_` 开头，走正常 gate path）
- L1 直接调用 `ToolGateHandler.handle()`
- L2 通过 `dispatcher.route()` 构造 TOOL_GATE request

### 3.2 L3 阶段（DEFERRED，推荐方案记录于此）

要让 `real_core_loop_runtime_e2e` 路径覆盖 `confirmation_required`，需要 loop
的 TOOL_GATE action 传递一个 confirmable tool name。

**推荐方案：新增 `_confirmable_noop` 内部工具。**

```
_confirmable_noop:
  - name: "_confirmable_noop"（`_` 前缀 → 模型不可见）
  - confirmation: "always"（区别于 _safe_noop 的 "never"）
  - parameters: {}（zero-arg，无参数注入风险）
  - capability: "local_action"
  - risk_level: "low"
  - output_policy: "none"
  - 函数体: return "confirmable_noop: ok"（与 _safe_noop 同等安全）
```

同时扩展 allowlist（`tool_gate.py:96`）：

```python
# Before:
if tool_name == "_safe_noop":

# After:
if tool_name in ("_safe_noop", "_confirmable_noop"):
```

**不变式保证：**
- 不放宽所有 `_` 前缀工具——allowlist 仍是显式枚举
- 不改变 ToolRegistry governance——仍通过 `@register_tool` 注册
- 不引入新 gate path——allowlist 通过后走同一 `needs_tool_confirmation` 检查
- `_confirmable_noop` 函数体与 `_safe_noop` 同等零副作用：无 shell、无文件写入、
  无外部进程、无网络

**L3 的 loop 侧变更（同样 DEFERRED）：**
Loop 需要支持在 fake/dogfood provider 下传递 `_confirmable_noop` 作为
TOOL_GATE 的 tool_name。具体机制（配置化 vs 硬编码 vs dependency 注入）
在 Implementation Plan 阶段决定。

### 3.3 为什么 L1/L2 先行

- L1/L2 覆盖了 `ToolGateHandler` 的所有 gate 逻辑分支
- `confirmation_required` 的语义、evidence 结构、分类规则在 L1/L2 中已得到
  充分验证
- L3 增加的是 dispatcher entry provenance 覆盖——证明 `real_core_loop_runtime_e2e`
  路径同样可达，但不改变 gate 判定逻辑本身
- 分层实现允许 TDD 在 OQ#1 解决前就开始，而不是被阻塞

## 4. 确认：本轮不做什么

- 不新增 `_confirmable_noop`（L3 DEFERRED，不在本 TDD 实现）
- 不修改 `tool_gate.py` allowlist（L3 DEFERRED）
- 不修改 `loop.py`（L3 DEFERRED）
- 不新增 Anchor / capability milestone / RuntimeActionType / handler
- 不修改 `ToolGateHandler.handle()` gate 逻辑
- 不引入 Tool Args / Tool Result / Retry / Error Recovery / Multi Tool /
  MCP Tool / Skill / Checkpoint / Streaming / SubAgent
- 不调用真实 API / 不读取 .env / 不执行 shell / 不写文件 / 不访问外部进程

## 5. 测试文件计划

**新增文件：** `tests/runtime_integration/test_tool_branch_confirmation_required.py`

**选择理由：**
- 与已有 `test_tool_anchor_fake.py` 同目录、同模式
- `confirmation_required` 是 `tool.gate` 的 branch behavior，应与
  `test_tool_anchor_fake.py`（覆盖 `allowed` behavior）放在同一命名空间
- 复用 `_build_phase1_dispatcher_with_tool_gate()` 和 `_SpyDispatcher`

**不修改已有文件。**

## 6. 测试矩阵

### 6.1 Phase A: Gate Logic — confirmation_required 正例（L1/L2）

| ID | Test Name | Purpose | Level | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|-------|--------|-------------------|-----------|
| A1 | `test_confirmation_always_yields_confirmation_required` | `confirmation="always"` → gate_disposition=confirmation_required | L2 | 在 TOOL_REGISTRY 注册 `test_confirmable_noop`（`confirmation="always"`, `risk_level="low"`, `capability="local_action"`）；构造 TOOL_GATE request | `dispatcher.route(request)` | status=confirmation_required, gate_disposition=confirmation_required, decision=confirmation_required, registry_handler_invoked=True, dangerous_tool_function_invoked=False, target_module_proof 存在 | tool function 不被调用；无 shell/file/process |
| A2 | `test_confirmation_callable_true_yields_confirmation_required` | callable confirmation 返回 True → confirmation_required | L2 | 在 TOOL_REGISTRY 注册工具（`confirmation=lambda args: True`）；构造 TOOL_GATE request | `dispatcher.route(request)` | 同上，gate_disposition=confirmation_required | 同上 |
| A3 | `test_confirmation_callable_args_based_yields_confirmation_required` | callable 基于 args 返回 True | L2 | 注册工具（`confirmation=lambda args: args.get("risk") == "high"`）；构造 request（`tool_args={"risk": "high"}`） | `dispatcher.route(request)` | gate_disposition=confirmation_required | 同上 |
| A4 | `test_confirmation_default_yields_confirmation_required` | confirmation 字段缺失 → 默认 True | L2 | 注册工具（不含 `confirmation` 字段或非 "never" 非 callable 值） | `dispatcher.route(request)` | gate_disposition=confirmation_required | 同上 |
| A5 | `test_confirmable_tool_function_not_invoked` | confirmation_required 时 tool function 不被调用 | L1 | 注册 confirmable test tool，其函数体设置 `side_effect_counter`；直接调用 `ToolGateHandler.handle()` | `handler.handle(request, context)` | dangerous_tool_function_invoked=False, side_effect_counter 未增量 | tool function 不被调用 |
| A6 | `test_confirmable_tool_no_side_effects` | confirmation_required status 的证据不含副作用标记 | L2 | 同 A1 | `dispatcher.route(request)` | external_side_effects=False, dangerous_tool_function_invoked=False, 无 shell/file/network 痕迹 | — |
| A7 | `test_confirmation_required_evidence_structure` | confirmation_required 时 evidence 字段完整性 | L2 | 同 A1 | `dispatcher.route(request)` | registry_handler_invoked=True, target_module_invoked=False, policy_path="tool_registry→risk_check", rejection_reason=None, production_registry_found=True, capability_type="production_tool_registry" | evidence 不含 core_loop_invoked（direct dispatcher 路径） |

### 6.2 Phase B: Classification Boundaries（L2）

| ID | Test Name | Purpose | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|--------|-------------------|-----------|
| B1 | `test_direct_dispatcher_is_harness_not_real_core_loop` | direct `dispatcher.route()` → harness_runtime_e2e | 同 A1 | `dispatcher.route(request)` | evidence_level=harness_runtime_e2e, dispatcher_origin=direct_dispatcher | evidence_level ≠ real_core_loop_runtime_e2e |
| B2 | `test_route_from_runtime_loop_is_real_core_loop` | `route_from_runtime_loop()` → real_core_loop_runtime_e2e | **DEFERRED (L3, OQ#1)** | `dispatcher.route_from_runtime_loop(request)` | evidence_level=real_core_loop_runtime_e2e, dispatcher_origin=runtime_loop, runtime_loop_invoked=True | — |
| B3 | `test_direct_handler_is_subsystem_integration` | 直接 `ToolGateHandler.handle()` → subsystem_integration | 直接构造 context + handler | `handler.handle(request, context)` | evidence_level ≤ subsystem_integration（无 dispatcher provenance） | evidence_level ≠ real_core_loop_runtime_e2e, ≠ harness_runtime_e2e |
| B4 | `test_payload_cannot_upgrade_classification` | payload 中的 `core_loop_invoked=True` 不能升级 direct dispatcher 分类 | 同 A1，但 payload 含 `core_loop_invoked=True`, `core_entrypoint="core.chat"` | `dispatcher.route(request)` | evidence_level=harness_runtime_e2e（非 real_core_loop_runtime_e2e） | dispatcher 不读取 payload 中的 core_loop_invoked 做分类判定 |

### 6.3 Phase C: Negative Coverage — blocked / not_found（L2）

| ID | Test Name | Purpose | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|--------|-------------------|-----------|
| C1 | `test_not_found_tool_returns_not_found` | 不在 registry 的工具 → not_found | 构造 TOOL_GATE request（tool_name="nonexistent_tool_xyz"） | `dispatcher.route(request)` | decision=not_found, gate_disposition=None, rejection_reason="tool not found in production ToolRegistry", tool_invoked=False | — |
| C2 | `test_blocked_forbidden_tool_name` | bash 在 `_FORBIDDEN_TOOL_NAMES` → rejected | 在 TOOL_REGISTRY 注册 "bash"（绕过实际注册）；构造 request | `dispatcher.route(request)` | gate_disposition=rejected, decision=rejected, rejection_reason="shell-like tool is out of scope" | — |
| C3 | `test_blocked_callable_returns_block` | callable 返回 "block" → rejected | 注册工具（`confirmation=lambda args: "block"`） | `dispatcher.route(request)` | gate_disposition=rejected, decision=rejected, rejection_reason="tool policy blocked request" | — |
| C4 | `test_not_model_visible_tool_blocked` | 不在 model-visible list 的工具 → rejected | 注册工具但 monkeypatch `get_model_visible_tools` 返回空列表 | `dispatcher.route(request)` | gate_disposition=rejected, rejection_reason="tool is not model-visible" | — |

**规则（与 SPEC 一致）：**
- blocked / not_found 是 negative test coverage，不单独开 Anchor 或 milestone
- 本 TDD 只实现 `confirmation_required` 正例；负例 C1-C4 作为边界保护

### 6.4 Phase D: Memory / Tool Isolation（L2）

| ID | Test Name | Purpose | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|--------|-------------------|-----------|
| D1 | `test_tool_gate_failure_does_not_block_memory` | TOOL_GATE 失败不阻断 MEMORY branch | 构造两个 request（MEMORY + TOOL_GATE 失败）；使用 spy dispatcher | 分别 route | 两个 action 独立 evidence，TOOL_GATE failed 不消失 MEMORY evidence | — |
| D2 | `test_memory_failure_does_not_block_tool_gate` | MEMORY 失败不阻断 TOOL_GATE branch | 同上，反向 | 分别 route | TOOL_GATE evidence 独立于 MEMORY failure | — |
| D3 | `test_memory_evidence_not_polluted_by_tool_gate` | MEMORY evidence 不含 tool.gate 字段 | 同 D1 | 分别 route | MEMORY evidence 不含 gate_disposition/requested_tool_name | — |
| D4 | `test_tool_gate_evidence_not_polluted_by_memory` | TOOL_GATE evidence 不含 memory 字段 | 同 D2 | 分别 route | TOOL_GATE evidence 不含 memory proposal/suggestion 字段 | — |

### 6.5 Phase E: Fake/Real Boundary（L2）

| ID | Test Name | Purpose | Setup | Action | Expected Evidence | Forbidden |
|----|-----------|---------|-------|--------|-------------------|-----------|
| E1 | `test_fake_provider_same_gate_logic_as_real` | fake provider 与 real 共享同一 gate 逻辑 | 同 A1，payload 中 provider_kind="fake" | `dispatcher.route(request)` | gate_disposition=confirmation_required, capability_type=production_tool_registry, provider_kind=fake（metadata only） | provider_kind 不改变 gate 判定；无 fake-only gate path |
| E2 | `test_confirmation_required_no_real_api` | 本轮不涉及真实 API | — | — | 所有测试不需要 .env、不需要真实 API key | 不读取 .env |

## 7. 测试辅助工具设计

### 7.1 Test Confirmable Tool 注册

测试 setup 中使用的辅助函数：

```python
def _register_test_confirmable_tool(
    *,
    name: str = "test_confirmable_noop",
    confirmation: str | Callable = "always",
    risk_level: str = "low",
    capability: str = "local_action",
) -> None:
    """在 TOOL_REGISTRY 中临时注册一个无副作用的 confirmable test tool。

    该 tool 走正常 gate path（非 `_` 前缀 → 非 allowlist 路径），
    用于在 harness 层触发 confirmation_required gate disposition。

    调用方必须在测试清理阶段移除该 tool。
    """
```

### 7.2 Dispatcher + Handler 构建

复用 `test_tool_anchor_fake.py` 中的：
- `_build_phase1_dispatcher_with_tool_gate()`
- `_SpyDispatcher`

### 7.3 测试隔离

- 每个测试在 setup 中注册 test tool，在 teardown 中从 TOOL_REGISTRY 移除
- 使用 pytest `monkeypatch` 进行 TOOL_REGISTRY 的临时修改
- 不依赖测试执行顺序

## 8. DEFERRED 项目

| 项目 | 依赖 | 目标阶段 |
|------|------|---------|
| L3 `real_core_loop_runtime_e2e` 测试（B2） | OQ#1 解决 | Implementation Plan |
| `_confirmable_noop` 新增 | OQ#1 解决 + Implementation Plan | Implementation |
| allowlist 扩展（`tool_gate.py:96`） | `_confirmable_noop` 新增 | Implementation |
| loop 支持 confirmable tool name | OQ#1 方案选择 | Implementation Plan |

## 9. 与 SPEC 的追溯

| SPEC § | 本 TDD 覆盖 |
|--------|-----------|
| §2.1 confirmation_required 语义（三条子路径） | A1 (always), A2-A3 (callable_true), A4 (default) |
| §2.2 不做 UI 交互 | 全量：无 UI 测试 |
| §4 fake/real 配置层边界 | E1, E2 |
| §5.1 dogfood 路径 | B1（direct dispatcher）, B2（DEFERRED）, B3（direct handler） |
| §5.2 禁止做法 | B4（payload 不可升级分类） |
| §5.3 分类预期 | B1 (harness), B2 (real_core_loop, DEFERRED), B3 (subsystem) |
| §6 不做什么 | §4 清单 |
| OQ#1 | §3（分阶段策略 + L3 推荐方案） |
| OQ#2（callable 签名） | A2, A3（通过 callable confirmation 测试隐式覆盖） |

## 10. Review Checklist

- [ ] branch point 判断正确（`tool.gate`，非新 Anchor）
- [ ] 不是新 capability milestone
- [ ] OQ#1 处理明确（L1/L2 先行，L3 DEFERRED）
- [ ] 正例覆盖三条 confirmation_required 子路径（always / callable / default）
- [ ] 负例 blocked / not_found 只作为 negative coverage
- [ ] classification boundary 测试覆盖三级分类
- [ ] payload 不能升级分类（反欺诈）
- [ ] Memory / Tool 隔离测试
- [ ] fake/real 边界测试（同一 gate logic，仅 provider_kind 不同）
- [ ] 无副作用验证（no shell / file / process / MCP / real API）
- [ ] DEFERRED 项目明确标注
- [ ] 不修改 agent/ / tests/ / scripts/（本 TDD 仅写文档）
- [ ] 与 Unified Runtime Flow Contract 一致
- [ ] 与 SPEC 一致

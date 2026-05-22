---
title: feat: Memory Anchor real provider smoke hook parameterization
type: feat
status: active
date: 2026-05-21
origin: docs/real-e2e/memory-anchor/SPEC.md
---

# feat: Memory Anchor real provider smoke hook parameterization

## Summary

当前 `agent/loop.py:78-79` 硬编码 `provider_kind="fake"` 和 `external_side_effects=False`，导致 real provider smoke 无法在 `core.chat()` 路径中产生正确的 evidence。本轮规划通过在 `core.py` 中预解析 provider 的 coarse-grained runtime evidence metadata，注入 `LoopDependencies`，使 `_try_phase1_turn_end_runtime_action` 使用动态值替代硬编码，同时坚持：

- fake/real 走同一 `core.chat()` → `run_main_loop()` → turn-end hook 路径
- `LoopDependencies` 只接收预解析的字符串/布尔值，**不接收完整 provider 对象**
- `provider_kind` 只允许 coarse-grained 三态：`"fake"` / `"real"` / `"unknown"`，不回退到 class name
- `provider_external_call`（是否调用了真实外部 API）与 `external_side_effects`（是否有工具/文件/MCP 等副作用）拆分

---

## Problem Frame

### A. 当前 `provider_kind` 为何固定为 `"fake"`

根本原因是信息丢失：**`LoopDependencies` 构造时没有传入 provider 的任何信息**。

具体链路：

1. `agent/core.py:506-513` — `chat()` 收到 `provider` 后传入 `LoopContext.model_provider`
2. `agent/core.py:703-718` — `_run_main_loop()` 构造 `LoopDependencies`，**未从 `loop_ctx.model_provider` 提取任何 provider 元数据**
3. `agent/loop.py:78-79` — hook 拿不到 provider 信息，只能硬编码

```python
# agent/loop.py:78-79 — 当前硬编码
"provider_kind": "fake",
"external_side_effects": False,
```

这个硬编码在 fake-provider phase 是正确的。但它阻挡了 real provider smoke，因为 hook 无法根据实际注入的 provider 类型动态设置这些字段。

### B. Hook 参数化的最小注入点：预解析元数据方案

#### 设计原则

1. **`LoopDependencies` 不接收完整 provider 对象** — 只接收预解析的 coarse-grained 字符串/布尔值
2. **解析逻辑在 `core.py`** — 紧邻 `LoopDependencies(...)` 构造点，是高内聚的 metadata 提取
3. **`provider_kind` 只允许 coarse-grained 三态** — `"fake"`, `"real"`, `"unknown"`；不回退到 `type(provider).__name__` 或 raw `provider_type`
4. **`provider_external_call` 与 `external_side_effects` 拆分** — 前者描述 provider 本身是否调用了真实外部 API，后者描述整个 turn 是否有工具/文件/MCP/memory retain 等副作用

#### 注入点选择

| 候选 | 位置 | 改动面 | 耦合度 | 结论 |
|------|------|--------|--------|------|
| `LoopDependencies` + pre-resolved fields | `agent/loop.py` dataclass + `agent/core.py` resolver | loop.py + core.py | **最低** — `LoopDependencies` 已有 `runtime_action_dispatcher`，加两个同类字段是自然延伸 | **推荐** |
| `core.chat()` 新增参数 | `agent/core.py:300-309` | 仅 core.py | 低，但 `chat()` 已是多参数函数，继续膨胀不优雅 | 备选 |
| provider factory 注入 | `agent/provider/factory.py` | factory.py + loop.py + core.py | 中 — factory 层不该知道 hook payload 结构 | 不推荐 |
| dogfood adapter 绕过 `core.chat()` | `scripts/` | 仅 dogfood | 最低，但违反"不得绕过 core.chat"约束 | **禁止** |
| `MemoryPolicy` 直接读 provider/env | `agent/memory_policy.py` | policy.py | 低，但违反职责边界 — policy 不该知道 provider | **禁止** |

#### 推荐方案架构

```
core.chat(provider=...)
  │
  ├─ 506-513: 已有 — provider.provider_type == "fake" 检测用于 dispatcher auto-build
  │
  └─ _run_main_loop(turn_state, loop_ctx)
       │
       ├─ NEW: _resolve_provider_evidence_metadata(loop_ctx.model_provider)
       │     → (provider_kind: "fake"|"real"|"unknown",
       │        provider_external_call: bool)
       │
       ├─ LoopDependencies(
       │     ...,
       │     provider_kind=resolved_kind,         # NEW
       │     provider_external_call=resolved_call, # NEW
       │   )
       │
       └─ run_main_loop(...) → _try_phase1_turn_end_runtime_action
             ├─ dependencies.provider_kind      → evidence["provider_kind"]
             ├─ dependencies.provider_external_call → evidence["provider_external_call"]
             └─ external_side_effects: False     (本轮保持 False)
```

#### `_resolve_provider_evidence_metadata(provider)` 规范

位置：`agent/core.py`，`_run_main_loop` 内部（或作为 module-level helper）

```python
def _resolve_provider_evidence_metadata(provider: Any) -> tuple[str, bool]:
    """预解析 provider 的 coarse-grained runtime evidence metadata。

    返回 (provider_kind, provider_external_call)：
    - provider_kind: "fake" | "real" | "unknown"（粗粒度三态）
    - provider_external_call: 该 provider 是否会发起真实外部 API 调用

    不回退到 type(provider).__name__。不读 .env。不访问 secret。
    """
    if provider is None:
        return ("unknown", False)

    pt = getattr(provider, "provider_type", None)
    if not isinstance(pt, str) or not pt:
        return ("unknown", False)

    # coarse-grained normalization: 只输出三种值
    if pt == "fake":
        return ("fake", False)

    # 已知真实 provider 类型 → real + 有外部调用
    if pt in (
        "anthropic_native", "anthropic_compatible",
        "openai_native", "openai_compatible",
    ):
        return ("real", True)

    # 未知 provider_type → fail-closed
    return ("unknown", False)
```

**语义表**：

| provider | `provider_type` | `provider_kind` | `provider_external_call` | 说明 |
|----------|-----------------|-----------------|--------------------------|------|
| `FakeProvider()` | `"fake"` | `"fake"` | `False` | 确定性 mock，无外部 API 调用 |
| `AnthropicNativeProvider()` | `"anthropic_native"` | `"real"` | `True` | 真实 Anthropic API |
| `AnthropicCompatibleProvider()` | `"anthropic_compatible"` | `"real"` | `True` | 真实 Anthropic 兼容 API |
| `OpenAINativeProvider()` | `"openai_native"` | `"real"` | `True` | 真实 OpenAI API |
| `OpenAIHTTPProvider()` | `"openai_compatible"` | `"real"` | `True` | 真实 OpenAI 兼容 API |
| `None` | N/A | `"unknown"` | `False` | 未注入 provider |
| 无 `provider_type` 属性的 mock | N/A | `"unknown"` | `False` | fail-closed |
| 未知 `provider_type` 字符串 | 任意非白名单值 | `"unknown"` | `False` | fail-closed |

**关键设计决策**：

- **不回退到 class name**：`type(provider).__name__` 可能包含 `"AnthropicNativeProvider"` 这类实现细节，不应泄漏到 evidence
- **fail-closed for unknown**：未知 provider → `provider_kind="unknown"`, `provider_external_call=False`。不 overclaim "real"
- **白名单归一化**：所有已知真实 provider 类型归一化为 `"real"`（不保留 `"anthropic_native"` 等 raw 值到 evidence 的 `provider_kind` 字段；raw `provider_type` 可通过 evidence_extra 的 `provider_type` 字段保留，见下方）

#### `provider_kind` vs raw `provider_type`

`provider_kind` 是 **coarse-grained 证据分类标签**，用于 evidence 的 `provider_kind` 字段。Raw `provider_type`（如 `"anthropic_native"`）是 provider 实现的元数据，应通过 `evidence_extra.provider_type` 透传（如果 handler 需要），但 **不作为 `provider_kind` 的值**。

```text
evidence.provider_kind     = "real"              ← 粗粒度分类
evidence_extra.provider_type = "anthropic_native" ← 精确来源（如有）
```

#### `provider_external_call` vs `external_side_effects` 拆分

| 字段 | 含义 | 来源 | 本轮值 |
|------|------|------|--------|
| `provider_external_call` | provider 本身是否调用了真实外部 API | `_resolve_provider_evidence_metadata()` → `LoopDependencies.provider_external_call` | fake→False, real→True |
| `external_side_effects` | 整个 turn 是否有工具/文件/MCP/memory retain/human_approved write 等副作用 | 当前硬编码 `False` | **本轮保持 False** |

**这两个字段语义不同**：一个 real Anthropic provider 在 real smoke 场景下 `provider_external_call=True`（因为确实调了 Anthropic API），但 `external_side_effects=False`（因为没有执行工具、没有写文件、没有 retain memory、没有写 human_approved）。未来当 Memory Anchor 扩展到 real retain/工具执行时，`external_side_effects` 才会变为 `True`。

#### `LoopDependencies` 变更

```python
# agent/loop.py:88-107
@dataclass(frozen=True, slots=True)
class LoopDependencies:
    # ... existing fields (state, call_model, dispatch_model_output, ...) unchanged ...
    runtime_action_dispatcher: Any | None = None
    provider_kind: str = "unknown"          # NEW: coarse-grained "fake"|"real"|"unknown"
    provider_external_call: bool = False    # NEW: 是否调用了真实外部 API
```

#### `_try_phase1_turn_end_runtime_action` 变更

```python
# agent/loop.py:70-85 — 替换硬编码
# 原: "provider_kind": "fake", "external_side_effects": False
# 新: 从 dependencies 读取预解析值
"provider_kind": dependencies.provider_kind,
"provider_external_call": dependencies.provider_external_call,
"external_side_effects": False,  # 本轮保持 False — 无工具/文件/memory retain
```

注意：`_try_phase1_turn_end_runtime_action` 签名**不需要变更**——它已经接收 `dependencies: LoopDependencies`，新字段通过 `dependencies.provider_kind` / `dependencies.provider_external_call` 访问。

#### `run_main_loop` 变更

**不需要变更**。`_try_phase1_turn_end_runtime_action` 已经接收 `dependencies` 参数，无需额外透传。

#### `core.py` `_run_main_loop` 变更

```python
# agent/core.py:703-718
from agent.loop import _resolve_provider_evidence_metadata  # 或定义在 core.py

resolved_kind, resolved_call = _resolve_provider_evidence_metadata(
    loop_ctx.model_provider
)

dependencies = LoopDependencies(
    # ... existing fields unchanged ...
    runtime_action_dispatcher=loop_ctx.runtime_action_dispatcher,
    provider_kind=resolved_kind,
    provider_external_call=resolved_call,
)
```

#### 改动文件清单

| 文件 | 改动 | 行数估计 |
|------|------|----------|
| `agent/core.py` | 新增 `_resolve_provider_evidence_metadata()` helper; `LoopDependencies(...)` 构造处 +2 kwargs | ~25 行 |
| `agent/loop.py` | `LoopDependencies` +2 fields; `_try_phase1_turn_end_runtime_action` 硬编码替换为 `dependencies.provider_kind` / `dependencies.provider_external_call` | ~6 行 |

总计约 31 行生产代码改动。没有新文件，没有新类，没有新 loop/dispatcher。`_derive_provider_kind` / `_derive_external_side_effects` helpers **不出现在 `loop.py` 中**——解析逻辑集中在 `core.py`。

#### 为什么这个方案最小

1. **不新建任何类或模块** — 只在 `core.py` 加一个纯函数，`LoopDependencies` 加两个字段
2. **不改变任何函数签名中已有的参数** — 新 dataclass 字段有默认值，向后兼容
3. **`LoopDependencies` 不接收 provider 对象** — 只接收预解析的 string/bool，保持 dataclass 的 simplicity
4. **不触及 provider 实现** — `provider_type` 类属性已存在于所有 provider
5. **不触及 dispatcher / handler / MemoryPolicy** — 这些层完全不感知变更
6. **不改变 `LoopContext`** — `model_provider` 已在其中
7. **`run_main_loop` 签名不变** — `dependencies` 已包含新字段

### C. Real Provider Smoke 最小目标

**验证范围**：

```
用户输入
  → core.chat(user_input, provider=real_provider, runtime_action_dispatcher=spy)
  → real provider (Anthropic API)
  → run_main_loop (同一条)
  → turn-end memory proposal hook (同一个)
  → RuntimeActionDispatcher (同一个)
  → MemoryTurnEndProposalHandler (同一个)
  → disposition: pending_review / no_action / should_not_remember
  → target_module_proof
  → evidence:
      provider_kind = "real"
      provider_external_call = true
      external_side_effects = false
```

**不验证**：

- human approval 交互
- `human_approved` 写入
- memory retain（写入 store）
- memory recall/use（Layer 3）
- ToolRegistry / Skill / Checkpoint / Streaming / SubAgent
- 多 turn 对话
- Full real E2E（含工具执行）

**关键约束**：

- `auto_approved=False`, `not_confirmed=True` 在 real provider 下仍成立
- `real_episodes_read=False` 不变
- `no_silent_retain=True` 不变
- secret-like 过滤在 real provider 下仍然有效
- `evidence_level` 仍为 `real_core_loop_runtime_e2e`（不新增级别 — SPEC §5.2）

---

## Scope Boundaries

- 只做 hook 参数化（解除 real provider smoke 的阻塞条件）
- 不做 real provider smoke 的 TDD 实现和 dogfood 脚本（下一个 PR）
- 不新增 real-only loop / fake-only loop
- 不新增 fake/real dispatcher 分叉
- 不修改 Memory governance（`DeterministicMemoryPolicy` 不变）
- 不修改 checkpoint schema
- 不读 `.env` 内容（`_resolve_provider_evidence_metadata` 只读 `provider.provider_type` 类属性，不读 env）
- 不读 memory episodes
- 不写 human_approved
- 不做 ToolRegistry / Skill / Streaming / SubAgent 扩展
- 不 push / 不 tag

### Deferred to Follow-Up Work

- Real provider smoke TDD tests (`tests/runtime_integration/test_memory_anchor_real.py`)
- Real provider smoke dogfood script (`scripts/dogfood_memory_anchor_real_smoke.py`)
- `external_side_effects` 动态化（当工具/文件/MCP/memory retain 进入 scope 时）
- `evidence_level` 分类器扩展（新级别如 `real_provider_core_loop_e2e`，见 SPEC §5.2 末尾说明）

---

## Implementation Units

### U1: `_resolve_provider_evidence_metadata` + `LoopDependencies` + hook 参数化

**Goal**: 解除 `agent/loop.py:78-79` 的硬编码，使 `provider_kind` 和 `provider_external_call` 由 `core.py` 中的预解析 helper 提供，经 `LoopDependencies` 传入 hook，fake/real 走同一条路径。

**Files**:
- Modify: `agent/core.py` — 新增 `_resolve_provider_evidence_metadata(provider)` helper（~22 行）；`_run_main_loop` 中 `LoopDependencies(...)` 构造处 +2 kwargs（~3 行）
- Modify: `agent/loop.py` — `LoopDependencies` +2 fields（`provider_kind: str = "unknown"`, `provider_external_call: bool = False`）；`_try_phase1_turn_end_runtime_action` 硬编码替换为 `dependencies.provider_kind` / `dependencies.provider_external_call`（~4 行）

**Approach**:

1. 在 `agent/core.py` `_run_main_loop` 函数之前新增 `_resolve_provider_evidence_metadata(provider)` helper
   - 只读 `provider.provider_type` 类属性（如果 provider 非 None 且有该属性）
   - `"fake"` → `("fake", False)`
   - `"anthropic_native"` / `"anthropic_compatible"` / `"openai_native"` / `"openai_compatible"` → `("real", True)`
   - 其他/None/无 `provider_type` → `("unknown", False)` — fail-closed
   - 不使用 `type(provider).__name__` fallback
   - 不读 `.env`、`os.environ`、不访问 API key
2. `LoopDependencies` 新增两个字段：`provider_kind: str = "unknown"` 和 `provider_external_call: bool = False`（默认值向后兼容）
3. `_try_phase1_turn_end_runtime_action` 将硬编码 `"provider_kind": "fake"` 替换为 `dependencies.provider_kind`，将 `"external_side_effects": False` 改为同时设置 `provider_external_call`（来自 dependencies）和 `external_side_effects`（保持 False）
4. `_run_main_loop` 在构造 `LoopDependencies` 前调用 `_resolve_provider_evidence_metadata(loop_ctx.model_provider)`，传入结果
5. `run_main_loop` **不需要变更**（`_try_phase1_turn_end_runtime_action` 已接收 `dependencies`）

**Execution note**: test-first — U2 先写，U1 后实现

**Patterns to follow**:
- `LoopDependencies` 现有字段风格（`runtime_action_dispatcher: Any | None = None`）
- `_try_phase1_turn_end_runtime_action` 现有 `try/except` silent-fail 模式
- `core.py:508` 已有的 `getattr(provider, "provider_type", None) == "fake"` 模式

**Test scenarios** (see U2):

| # | Scenario | Input provider | Expected `provider_kind` | Expected `provider_external_call` |
|---|----------|---------------|--------------------------|----------------------------------|
| 1 | FakeProvider | `FakeProvider()` | `"fake"` | `False` |
| 2 | None provider | `None` | `"unknown"` | `False` |
| 3 | 无 `provider_type` 属性的 mock | `Mock(spec=[])` | `"unknown"` | `False` |
| 4 | `provider_type=""` (空串) | mock with `provider_type=""` | `"unknown"` | `False` |
| 5 | AnthropicNative | mock with `provider_type="anthropic_native"` | `"real"` | `True` |
| 6 | AnthropicCompatible | mock with `provider_type="anthropic_compatible"` | `"real"` | `True` |
| 7 | OpenAINative | mock with `provider_type="openai_native"` | `"real"` | `True` |
| 8 | OpenAICompatible | mock with `provider_type="openai_compatible"` | `"real"` | `True` |
| 9 | 未知 provider_type 字符串 | mock with `provider_type="custom_vendor"` | `"unknown"` | `False` |
| 10 | FakeProvider 全链路回归 | `core.chat(provider=FakeProvider(), ...)` | evidence 中 `provider_kind="fake"` | `provider_external_call=False` |

**Verification**:
- `_resolve_provider_evidence_metadata` unit tests pass（U2 scenarios 1-9）
- Fake-provider 全链路回归：`test_memory_anchor_fake.py` 全部 pass
- `provider_kind` 在 fake mode evidence 中仍为 `"fake"`（不退化）
- `provider_external_call` 在 fake mode evidence 中为 `False`（不退化）
- `external_side_effects` 在 fake mode evidence 中仍为 `False`（不退化）

---

### U2: Parameterization unit tests + regression guard

**Goal**: 新增 `_resolve_provider_evidence_metadata` 单元测试 + fake-provider 全链路回归验证。

**Files**:
- Create: `tests/unit/test_provider_evidence_metadata.py` — `_resolve_provider_evidence_metadata` 单元测试（scenarios 1-9）
- Modify: `tests/runtime_integration/test_memory_anchor_fake.py` — 新增 regression test（scenario 10）

**Approach**:

1. 写 `tests/unit/test_provider_evidence_metadata.py`，直接 import `_resolve_provider_evidence_metadata`，覆盖：
   - FakeProvider 实例（真实 `FakeProvider()`，非 mock）
   - `None`
   - 无 `provider_type` 属性的 mock
   - 空字符串 `provider_type`
   - 四个已知真实 provider type（`"anthropic_native"`, `"anthropic_compatible"`, `"openai_native"`, `"openai_compatible"`）
   - 未知 `provider_type` 字符串（fail-closed 验证）
2. 在 `test_memory_anchor_fake.py` 的 `TestMemoryAnchorFakeProviderCoreChat` 中新增 `test_provider_kind_still_fake_after_parameterization`：
   - 调用 `core.chat(provider=FakeProvider(), runtime_action_dispatcher=spy)`
   - 断言 evidence 中 `provider_kind == "fake"`
   - 断言 evidence 中 `provider_external_call == False`
   - 断言 evidence 中 `external_side_effects == False`
   - **注意**：这个回归测试需要在 hook 参数化实现后 evidence payload 结构可能变化，需根据实际 evidence 字段路径调整断言

**Execution note**: test-first — 这些测试先写，`_resolve_provider_evidence_metadata` 的 9 个单元测试预期先红（helper 尚不存在），U1 实现后转绿。回归测试在 U1 实现前应 PASS（证明当前 fake mode 基线正确），U1 实现后仍 PASS（证明未退化）。

**Test scenarios**:

| # | Test | Category | What it guards |
|---|------|----------|----------------|
| 1 | `test_resolve_fake_provider` | unit | `FakeProvider()` → `("fake", False)` |
| 2 | `test_resolve_none_provider` | unit | `None` → `("unknown", False)` |
| 3 | `test_resolve_no_provider_type_attr` | unit | 无 `provider_type` 属性的对象 → `("unknown", False)` |
| 4 | `test_resolve_empty_provider_type` | unit | `provider_type=""` → `("unknown", False)` |
| 5 | `test_resolve_anthropic_native` | unit | `provider_type="anthropic_native"` → `("real", True)` |
| 6 | `test_resolve_anthropic_compatible` | unit | `provider_type="anthropic_compatible"` → `("real", True)` |
| 7 | `test_resolve_openai_native` | unit | `provider_type="openai_native"` → `("real", True)` |
| 8 | `test_resolve_openai_compatible` | unit | `provider_type="openai_compatible"` → `("real", True)` |
| 9 | `test_resolve_unknown_provider_type_fail_closed` | unit | 未知 `provider_type` → `("unknown", False)` — fail-closed |
| 10 | `test_fake_mode_evidence_unchanged_after_param` | integration | regression: core.chat + FakeProvider 全链路 evidence 不变 |

**Verification**:
- `pytest tests/unit/test_provider_evidence_metadata.py -q` — 9 unit tests pass
- `pytest tests/runtime_integration/test_memory_anchor_fake.py -q` — 8/8 pass (original 7 + 1 regression)
- `pytest tests/runtime_integration/ -q` — 121+ tests pass
- `pytest tests/ -q` — 全量无回归

---

### U3: Implementation notes update

**Goal**: 更新实现笔记，记录 hook 参数化设计决策、授权边界、secret 边界。

**Files**:
- Modify: `docs/implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md`

**Approach**:

1. 在现有 "为什么 real provider smoke deferred" section 后追加 "Hook Parameterization (2026-05-21)" section
2. 记录参数化设计：
   - 预解析元数据方案：`_resolve_provider_evidence_metadata` in `core.py`
   - `LoopDependencies` 接收 `provider_kind: str` 和 `provider_external_call: bool`（非完整 provider 对象）
   - `provider_kind` 只允许 `"fake"` / `"real"` / `"unknown"` 三态
   - `provider_external_call` vs `external_side_effects` 的语义拆分
   - 解析逻辑在 `core.py` 而非 `loop.py`（信息在构造点解析，不在消费点派生）
3. 记录为什么不在 `loop.py` 放 `_derive_*` helpers——provider 结构信息不应泄漏到 loop 编排层
4. 记录 `type(provider).__name__` fallback 的排除理由——class name 是实现细节，不应出现在 evidence 中
5. 更新 stop-condition near misses（确认参数化未触发任何 stop condition）
6. 明确 fake/real 同一路径证明（参数化后仍成立）

**Verification**:
- Implementation notes 中的设计描述与 `agent/core.py` / `agent/loop.py` 实际代码一致
- 所有 stop condition 确认未被触发
- `provider_kind` 三态约束、`provider_external_call` vs `external_side_effects` 拆分在 notes 中有明确记录

---

## Test Plan (Overall)

### 1. Fake Provider Path 不回归

- `test_memory_anchor_fake.py` 全部 7 个测试 + 新增 1 个 regression test → 8/8 pass
- 所有 evidence 中 `provider_kind` 仍为 `"fake"`
- 所有 evidence 中 `provider_external_call` 为 `False`
- 所有 evidence 中 `external_side_effects` 为 `False`
- `test_phase1_real_core_loop.py` 全部 15 个测试 pass
- `tests/runtime_integration/` 全部测试 pass
- Full `pytest` 无回归

### 2. Real Provider Smoke 默认 Gated/Skip

- 本轮 **不实现** real provider smoke tests（下一个 PR）
- 下一个 PR 的 `test_memory_anchor_real.py` 将使用 `MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1` 作为 opt-in gate
- 本轮只确保 hook 参数化后，real provider 能通过 `_resolve_provider_evidence_metadata` 产生正确的 `provider_kind="real"` 和 `provider_external_call=True`

### 3. 未授权时不得调用真实 API

- 参数化本身不发起任何 API 调用 — 只是预解析 `provider.provider_type` 类属性
- 不改变 `core.chat()` 的 provider 选择逻辑 — real provider 仍需调用方显式传入
- `FakeProvider` 作为默认值的行为不变
- `_resolve_provider_evidence_metadata` 不读 `.env`、不读 `os.environ`

### 4. 授权时使用同一 core.chat/runtime loop

- 参数化方案确保 fake/real 只通过 `_resolve_provider_evidence_metadata` 的返回值区分，不创建分叉路径
- `run_main_loop`（唯一主循环）不变
- `_try_phase1_turn_end_runtime_action`（唯一 hook）不变（只是用 `dependencies.provider_kind` 替代硬编码）

### 5. Secret 不打印

- `_resolve_provider_evidence_metadata` 只读 `provider.provider_type` 类属性（字符串常量），不访问 API key
- 日志/evidence 中不包含 `provider` 对象的任何 secret 字段
- `contains_secret_like()` 过滤在 hook handler 中仍然有效

### 6. .env 内容不读取

- 参数化逻辑不接触 `.env`、`os.environ`、`load_dotenv`
- `provider.provider_type` 是 provider 类的公开属性，不涉及 env 读取

### 7. Real Provider Path 仍 pending_review only

- `MemoryTurnEndProposalHandler` 不变 — `auto_approved=False`、`not_confirmed=True` 硬编码仍生效
- `provider_kind` 变化不影响 handler 的 disposition 逻辑

### 8. Direct Dispatcher 不得冒充 real_provider_core_loop_e2e

- `test_direct_dispatch_is_harness_not_real_core_loop` 仍有效
- `classify_evidence_level()` 不检查 `provider_kind` — direct dispatch 仍降级到 `harness_runtime_e2e`

### 9. provider_kind="fake"/"real"/"unknown" 区分清楚

- `_resolve_provider_evidence_metadata(FakeProvider())` → `("fake", False)`
- `_resolve_provider_evidence_metadata(real_provider)` → `("real", True)`
- `_resolve_provider_evidence_metadata(None)` → `("unknown", False)`
- Evidence 中 `provider_kind` 只允许这三种值
- Evidence 中 `provider_external_call` 与 `provider_kind` 一致：fake→False, real→True, unknown→False

### 10. Capability Classification 不 Overclaim

- `evidence_level` 值不变 — `real_core_loop_runtime_e2e` 不区分 fake/real provider
- 区分由 `provider_kind` + `provider_external_call` + `external_side_effects` 组合字段提供
- SPEC §5.2 明确说明 Phase 1 不做 `real_provider_core_loop_e2e` 新级别
- `provider_kind="unknown"` 时 fail-closed：`provider_external_call=False`，不 overclaim 真实 API 调用

---

## Dogfood Plan

### Fake Mode 仍默认

- `scripts/dogfood_memory_anchor_fake.py` 行为不变 — 不需要 `--real-provider-smoke` 参数
- 参数化后 fake mode dogfood 仍 PASS
- PASS 标准 #11（`provider_kind == "fake"`）和 #12（`external_side_effects == False`）不变
- 新增验证：`provider_external_call == False`

### Real Smoke 需显式参数

- **本轮不实现** real smoke dogfood（下一个 PR）
- 下一个 PR 中，dogfood 脚本将接受 `--real-provider-smoke` flag 或 `MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1` env var
- 需用户授权文本（见 DOGFOOD_PLAN.md §3.2）
- 授权后，`_resolve_provider_evidence_metadata` 自动产生 `provider_kind="real"`, `provider_external_call=True`

### 输出到 /private/tmp

- 所有报告仍写入 `/private/tmp`，不入 repo

### auth_status / key_source_kind / project_dotenv_loaded 输出

- Real smoke dogfood 可输出这些安全状态字段（不含 key 内容）
- 不输出 `ANTHROPIC_API_KEY` 或任何 key pattern

### Provider Response 不含 Secret

- 不打印 provider response 到 stdout/stderr
- Dogfood report 只记录 evidence 字段，不记录 provider 原始输出

### external_side_effects=False

- Dogfood 和 real smoke 中 `external_side_effects` 均为 `False`
- 原因：本轮不涉及工具执行、文件写入、MCP、memory retain、human_approved write
- 未来当 real Memory Anchor 支持这些时再动态化

---

## Risks and Stop Conditions

### Risks

1. **向后兼容风险（低）**: `LoopDependencies` 新增 `provider_kind` 和 `provider_external_call` 字段均有默认值（`"unknown"` / `False`）— 所有现有构造处不受影响。`_try_phase1_turn_end_runtime_action` 签名不变 — 只改函数体内对 `dependencies` 的字段访问。

2. **Real provider 尚未就绪风险**: 当前项目中没有 `build_model_provider_from_env()` 返回的 real Anthropic provider 实例的集成测试 — 这属于下一个 PR 的范围。本轮只验证 `_resolve_provider_evidence_metadata` 对已知 `provider_type` 字符串的映射正确性（单元测试覆盖），fake-provider 全链路不退化（回归测试覆盖）。

3. **未知 provider_type 值风险（低）**: 如果未来新增 provider 类型的 `provider_type` 不在白名单中，`_resolve_provider_evidence_metadata` 会 fail-closed 返回 `("unknown", False)`。这是预期行为 — 新增 provider 类型时应同步更新白名单。

4. **provider_type 缺失风险（已防御）**: `getattr(provider, "provider_type", None)` + `isinstance(pt, str) and pt` 双重过滤，空字符串和非字符串值均被拒绝。

### Stop Conditions

以下条件中任一触发，必须停止：

1. ~~需要读取 `.env` 内容~~ → **未触发**。`_resolve_provider_evidence_metadata` 只读 `provider.provider_type` 类属性
2. ~~需要真实 API 但用户未授权~~ → **未触发**。本轮不改任何 provider 选择逻辑
3. ~~需要读取 `memory/episodes/*.jsonl`~~ → **未触发**。不涉及 memory store
4. ~~需要写 `human_approved`~~ → **未触发**。不涉及 approval 流程
5. ~~需要 auto approve~~ → **未触发**。不修改 handler
6. ~~需要修改 `DeterministicMemoryPolicy`~~ → **未触发**。policy 不变
7. ~~需要新建 real-only loop~~ → **未触发**。只通过 `LoopDependencies` 注入预解析值
8. ~~需要 dogfood runner 绕过 `core.chat`~~ → **未触发**。不涉及 dogfood
9. ~~需要 ToolRegistry / Skill / Checkpoint / Streaming / SubAgent 扩展~~ → **未触发**
10. ~~需要 push / tag~~ → **未触发**。本轮只 plan
11. ~~将完整 `model_provider` 对象传入 `LoopDependencies`~~ → **未触发**。只传预解析的 string/bool
12. ~~在 `loop.py` 中放 provider 解析逻辑（`_derive_*` helpers）~~ → **未触发**。解析在 `core.py`
13. ~~`provider_kind` fallback 到 `type(provider).__name__`~~ → **未触发**。只输出 coarse-grained 三态
14. ~~从 `model_provider` 推导 `external_side_effects`~~ → **未触发**。`external_side_effects` 保持 `False`，与 provider 类型无关

---

## Key Technical Decisions

1. **解析逻辑在 `core.py`，不在 `loop.py`**
   - `LoopDependencies` 接收预解析的元数据，不接收完整 provider 对象
   - `loop.py` 不需要知道 provider 的结构 — 它只需要 `provider_kind` 字符串和 `provider_external_call` 布尔值
   - 这遵循"在信息最完整的地方解析，在消费点只传递结果"原则
   - `core.py` 已有 `provider.provider_type` 的读取先例（line 508），解析逻辑放在这里是自然的延续

2. **`provider_kind` 只允许 coarse-grained 三态**
   - `"fake"` / `"real"` / `"unknown"` — 粗粒度证据分类
   - Raw `provider_type`（如 `"anthropic_native"`）通过 `evidence_extra.provider_type` 保留精确来源
   - 不回退到 `type(provider).__name__` — class name 是实现细节，不应泄漏到 evidence
   - Fail-closed for unknown：未知 provider → `"unknown"`，不 overclaim "real"

3. **`provider_external_call` 与 `external_side_effects` 拆分**
   - `provider_external_call`: provider 本身是否调用了真实外部 API（由 provider 类型决定）
   - `external_side_effects`: 整个 turn 是否有工具/文件/MCP/memory retain/human_approved write 等副作用（本轮保持 `False`）
   - 这两个概念正交：一个 real provider smoke 有外部 API 调用但没有副作用；一个 fake provider 既无外部调用也无副作用
   - 未来当 real Memory Anchor 支持工具执行和 memory retain 时，`external_side_effects` 需要单独的计算逻辑，不应从 provider 类型推导

4. **不新增 `real_provider_core_loop_e2e` evidence_level**
   - SPEC §5.2 已明确说明 "Phase 1 不做此扩展"
   - `provider_kind` + `provider_external_call` + `external_side_effects` 组合字段已提供足够的区分度
   - 新增级别属于证据链分类器扩展，是独立变更

5. **`LoopDependencies` 字段名选择**
   - `provider_kind`（而非 `provider_type`）— 强调这是粗粒度分类标签，不是 raw `provider_type` 直通
   - `provider_external_call`（而非 `has_external_call` 或 `is_real`）— 强调这是一个 bool 判断，且独立于 `provider_kind`

---

## System-Wide Impact

| System | Impact |
|--------|--------|
| `agent/core.py` | +`_resolve_provider_evidence_metadata()` helper; `LoopDependencies(...)` 构造处 +2 kwargs |
| `agent/loop.py` | `LoopDependencies` +2 fields; `_try_phase1_turn_end_runtime_action` 硬编码替换 |
| `agent/loop_context.py` | 无改动（`model_provider` 已在其中） |
| `agent/runtime_integration/` | 无改动 |
| `agent/provider/` | 无改动（`provider_type` 类属性已存在于所有 provider） |
| `tests/` | +1 新文件 `tests/unit/test_provider_evidence_metadata.py`; `test_memory_anchor_fake.py` +1 regression test |
| `scripts/` | 无改动（下一个 PR） |
| `docs/` | implementation notes 更新 |

---

## Verification

```bash
# Unit tests for _resolve_provider_evidence_metadata
.venv/bin/python -m pytest tests/unit/test_provider_evidence_metadata.py -q

# Fake provider 全链路回归
.venv/bin/python -m pytest tests/runtime_integration/test_memory_anchor_fake.py -q

# Phase 1 基础设施回归
.venv/bin/python -m pytest tests/runtime_integration/test_phase1_real_core_loop.py -q

# 全量 runtime_integration
.venv/bin/python -m pytest tests/runtime_integration/ -q

# Full test suite
.venv/bin/python -m pytest -q

# Ruff lint
.venv/bin/ruff check agent tests

# Fake mode dogfood (regression check)
HOME=/private/tmp/my-first-agent-memory-anchor-home .venv/bin/python scripts/dogfood_memory_anchor_fake.py
```

---

## Readiness

ready for gstack plan review

---

## GSTACK REVIEW REPORT (plan-eng-review)

### Review Metadata

- **Plan**: `docs/plans/2026-05-21-002-feat-memory-anchor-hook-param-plan.md`
- **Date**: 2026-05-21
- **Reviewer**: plan-eng-review (with Codex outside voice)
- **Plan version**: v2 — pre-resolved metadata design (rewritten from v1 `_derive_*` helpers in `loop.py`)

### Architecture Review

**Decision**: ACCEPT with zero findings.

**Analysis**:

The v2 design places `_resolve_provider_evidence_metadata()` in `core.py`, immediately before `LoopDependencies` construction. This is the correct architectural choice:

1. **Information availability**: `core.py` line 508 already reads `provider.provider_type` for dispatcher auto-build. The resolver is a natural extension of that pattern — same file, same provider reference, same `getattr(provider, "provider_type", None)` idiom.

2. **Loop layer purity**: `loop.py` receives only pre-resolved `str` and `bool` values via `LoopDependencies`. It does not import provider types, does not call `getattr`, does not know about `"anthropic_native"` vs `"openai_compatible"`. This keeps the loop orchestration layer free of provider implementation knowledge.

3. **No new abstraction**: The resolver is a ~22-line pure function. No class, no registry, no plugin system. YAGNI — if future providers need custom resolution logic, the white-list can be extended in-place or extracted later.

4. **Injection point**: `LoopDependencies` is the right carrier. It already holds `runtime_action_dispatcher` (another "runtime dependency needed by the hook"). Adding `provider_kind` and `provider_external_call` is consistent with existing semantics.

**Contrast with v1 (rejected)**:

| Aspect | v1 (`_derive_*` in loop.py) | v2 (pre-resolved in core.py) |
|--------|---------------------------|------------------------------|
| Provider object in LoopDependencies | Yes (`model_provider: Any`) | No (only `str` + `bool`) |
| Provider structure knowledge in loop.py | Yes (reads `provider.provider_type`, `type().__name__`) | No |
| Class name fallback risk | Yes (`type(provider).__name__`) | No (white-list only) |
| `external_side_effects` derivation | From provider type | Not derived — stays `False` |
| Resolution location | Consumer side (hook) | Producer side (LoopDependencies construction) |

### Code Quality Review

**Decision**: ACCEPT.

**Strengths**:

- **Minimal surface**: ~31 lines of production code across 2 files. No new modules, no new classes.
- **Backward compatible**: Both new `LoopDependencies` fields have defaults (`"unknown"`, `False`). Existing callers are unaffected.
- **Fail-closed by default**: Unknown provider → `("unknown", False)`. No overclaim, no silent assumption of "real".
- **Explicit white-list**: The four known real provider types are enumerated. Adding a new provider type requires an explicit code change — this is a feature, not a bug (it forces conscious review of evidence implications).
- **No signature changes**: `run_main_loop` and `_try_phase1_turn_end_runtime_action` signatures are unchanged. Only the dataclass fields and hook body change.

**Minor note** (not blocking): The white-list in `_resolve_provider_evidence_metadata` is a tuple literal. If the project adds many more provider types, this could become a set lookup. Currently 4 entries — tuple is fine.

### Test Review

**Decision**: ACCEPT with confirmation that all 11 user-required test categories are covered.

**Coverage mapping**:

| User requirement | Covered by scenario | Type |
|-----------------|---------------------|------|
| 1. fake provider path 不回归 | #10 (integration regression) | integration |
| 2. real provider smoke 默认 gated/skip | Deferred to next PR — confirmed in scope boundaries | N/A (this PR) |
| 3. 未授权时不得调用真实 API | Resolver is pure function, no API calls | architectural |
| 4. 授权时使用同一 core.chat/runtime loop | Architecture ensures same path for all provider_kind values | architectural |
| 5. secret 不打印 | Resolver reads only `provider.provider_type` (string constant) | architectural |
| 6. .env 内容不读取 | No os.environ / load_dotenv calls in resolver | architectural |
| 7. real provider path 仍 pending_review only | Handler unchanged | architectural |
| 8. direct dispatcher 不得冒充 real | `classify_evidence_level` unchanged | architectural |
| 9. provider_kind=fake/real/unknown 区分清楚 | #1-9 (unit tests for resolver) | unit |
| 10. capability classification 不 overclaim | `evidence_level` unchanged; `provider_kind="unknown"` fail-closed | architectural |

**Unit test scenarios (9 tests)** cover:
- Happy path: FakeProvider instance (#1), four real provider types (#5-8)
- Edge cases: None (#2), missing attribute (#3), empty string (#4)
- Fail-closed: unknown provider_type (#9)
- No class name fallback path (verified by #3 and #9)

**Integration regression (#10)**: core.chat + FakeProvider full chain → evidence fields unchanged.

**Test file placement**: `tests/unit/test_provider_evidence_metadata.py` follows existing `tests/unit/` convention (check: `tests/unit/` exists and contains other unit tests). `test_memory_anchor_fake.py` modified in-place for regression — minimal diff.

### Performance Review

**Decision**: ACCEPT. Zero measurable overhead.

- `_resolve_provider_evidence_metadata` is a single `getattr` + string comparison against a 5-element tuple. Called once per `chat()` invocation (not per turn, not per token).
- No additional allocations beyond the returned 2-tuple.
- No IO, no network, no file access.

### Security Review

**Decision**: ACCEPT. All stop conditions confirmed not triggered.

| Stop condition | Status |
|---------------|--------|
| Read `.env` content | Not triggered — resolver reads only class attribute |
| Print secret | Not triggered — `provider_type` is a public string constant |
| Real API without user authorization | Not triggered — no API calls in this PR |
| Read memory/episodes | Not triggered |
| Write human_approved | Not triggered |
| Auto approve | Not triggered |
| Modify Memory governance | Not triggered — `DeterministicMemoryPolicy` unchanged |
| New real-only loop | Not triggered — same `run_main_loop` for all provider kinds |
| Dogfood runner bypass core.chat | Not triggered |
| ToolRegistry/Skill/Checkpoint/Streaming/SubAgent extension | Not triggered |
| Push/tag | Not triggered |

**Additional security notes**:

- `provider.provider_type` values (`"fake"`, `"anthropic_native"`, etc.) are class-level string constants — they cannot leak secrets by construction.
- The resolver does not access `provider.api_key`, `provider.config`, or any other provider attribute beyond `provider_type`.
- `provider_kind="unknown"` is the safe default — if a provider somehow lacks a `provider_type` or has an unrecognized value, the system fail-closed.

### Outside Voice (Codex) Integration

Codex outside voice was consulted on v1 of this plan. Key findings and their resolution:

| Codex finding | Resolution in v2 |
|---------------|------------------|
| `_derive_external_side_effects`不应该从 provider 类型推导 | **Resolved**: `external_side_effects` 保持 `False`，不再从 provider 推导；新增独立的 `provider_external_call` 字段 |
| class name fallback 泄漏实现细节 | **Resolved**: `_resolve_provider_evidence_metadata` 只输出 coarse-grained 三态，不使用 `type().__name__` |
| 完整 provider 对象传入 LoopDependencies 过于耦合 | **Resolved**: `LoopDependencies` 只接收预解析的 `str` + `bool` |
| 解析逻辑应在构造点而非消费点 | **Resolved**: 解析移至 `core.py` `_run_main_loop`，紧邻 `LoopDependencies(...)` 构造 |

### Review Readiness Dashboard

```
┌─────────────────────────────────────────────────────────┐
│  plan-eng-review — Memory Anchor Hook Parameterization  │
├─────────────────────────────────────────────────────────┤
│  Architecture  │  ACCEPT  │  pre-resolved metadata ✓    │
│  Code Quality  │  ACCEPT  │  ~31 lines, 2 files ✓       │
│  Test          │  ACCEPT  │  9 unit + 1 regression ✓    │
│  Performance   │  ACCEPT  │  O(1) string compare ✓      │
│  Security      │  ACCEPT  │  0 stop conditions hit ✓    │
│  Outside Voice │  INTEGRATED  │  4/4 findings resolved  │
├─────────────────────────────────────────────────────────┤
│  Verdict: READY FOR IMPLEMENTATION                      │
│  Blockers: 0                                            │
│  Warnings: 0                                            │
│  Follow-ups: real smoke TDD + dogfood (next PR)         │
└─────────────────────────────────────────────────────────┘
```

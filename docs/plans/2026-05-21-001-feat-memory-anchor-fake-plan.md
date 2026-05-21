---
title: feat: Memory Proposal Anchor fake-provider implementation
type: feat
status: active
date: 2026-05-21
origin: docs/real-e2e/memory-anchor/SPEC.md
---

# feat: Memory Proposal Anchor fake-provider implementation

## Summary

实现 Memory Proposal Anchor 的 fake-provider 验证层：新增 7 个 TDD 测试（含 no_action P2 修复）、一个专用 fake mode dogfood 脚本、以及实现记录文档。不修改任何生产代码——`core.chat()` → `run_main_loop()` → turn-end hook → `RuntimeActionDispatcher` → `MemoryTurnEndProposalHandler` 全链路已就位，本轮只补验证和可观测性。

---

## Problem Frame

Memory Proposal Anchor 是 my-first-agent 的第一个真实能力锚点。SPEC.md、TDD.md、DOGFOOD_PLAN.md 已通过两轮 `plan-eng-review` 复审，结论为 ready for fake-provider implementation。现有 `tests/runtime_integration/test_phase1_real_core_loop.py`（15 个测试）已覆盖 Phase 1 基础设施接线，但缺少 Memory Anchor 专属的边界测试（auto_approved 约束、no_action 处置、secret-like 过滤的 core.chat 路径验证等）。本轮补齐这些测试，并创建专用 dogfood 脚本，使 fake mode 验证形成自包含的完整闭环。

---

## Requirements

- R1. 7 个 TDD 测试全部通过，覆盖 fake provider 下 core.chat → memory proposal 全链路
- R2. `no_action` 处置有专项测试（P2 修复）
- R3. Fake mode dogfood 脚本可独立运行，输出包含 action_log / pending_review / evidence_level / target_module_proof / provider_kind / external_side_effects
- R4. 不改任何生产代码（`agent/loop.py`、`agent/core.py`、`agent/runtime_integration/*.py` 均不改动）
- R5. 不读 `.env`、不调真实 LLM/API、不读 memory episodes、不写 human_approved
- R6. 实现记录文档完整记录 spec gaps、assumptions、tradeoffs、deviations

**Origin actors:** N/A（基础设施验证，无用户角色区分）
**Origin flows:** F1: core.chat → FakeProvider → run_main_loop → turn-end hook → dispatcher → handler → evidence (see SPEC §2.2)
**Origin acceptance examples:** AE1 (fake provider core.chat triggers pending_review), AE2 (secret-like input rejected), AE3 (direct dispatch is harness, not real core loop), AE4 (no_action still produces RuntimeActionEvent)

---

## Scope Boundaries

- 只做 fake-provider Memory Proposal Anchor（Layer 1）
- 不做 real provider smoke（需 hook 参数化，deferred）
- 不做 Approval/Retain（Layer 2）
- 不做 Recall/Use（Layer 3）
- 不修改 Memory governance（`DeterministicMemoryPolicy` 不变）
- 不修改 checkpoint schema
- 不做 ToolRegistry / Skill / Streaming / SubAgent 扩展
- 不新增 fake runtime / fake loop / fake dispatcher

### Deferred to Follow-Up Work

- Real provider smoke 实现：依赖 `loop.py:78-79` hook 参数化（`LoopDependencies` 新增 provider 信息字段），单独 PR
- Layer 2 Approval/Retain E2E：待 Layer 1 完成后单独规划
- Layer 3 Recall/Use E2E：待 Layer 2 完成后单独规划

---

## Context & Research

### Relevant Code and Patterns

- **测试 spy 模式**：`tests/runtime_integration/test_phase1_real_core_loop.py` 中的 `_SpyDispatcher`（lines 433-456）包裹 `RuntimeActionDispatcher`，拦截 `route()` 调用。新测试文件复用此模式。
- **Dispatcher 构建**：`agent/runtime_integration/phase1_hook.py::build_phase1_dispatcher()` 构建最小 dispatcher（仅 `MemoryTurnEndProposalHandler`）。测试和 dogfood 脚本均通过此工厂获取 dispatcher。
- **core.chat 注入点**：`agent/core.py:300-309` 接受 `provider` 和 `runtime_action_dispatcher` 参数。`agent/core.py:506-513` 在 `provider.provider_type == "fake"` 时自动构建 dispatcher。
- **Turn-end hook**：`agent/loop.py:29-85` 的 `_try_phase1_turn_end_runtime_action()` 硬编码 `provider_kind="fake"` 和 `external_side_effects=False`（lines 78-79）。fake mode 下这是正确行为。
- **Handler 三路处置**：`agent/runtime_integration/memory_hook.py:37-109` — `should_not_remember`（secret-like/REJECT）、`proposed`（RETAIN/UPDATE）、`no_action`（其他）。三路均硬编码 `auto_approved=False`、`not_confirmed=True`、`real_episodes_read=False`。
- **Evidence 分类**：`agent/runtime_integration/evidence.py` 中 `classify_evidence_level()` 根据 `core_loop_invoked` 区分 `real_core_loop_runtime_e2e` 和 `harness_runtime_e2e`。
- **已有 dogfood**：`scripts/dogfood_phase1_real_core_loop.py` 已通过 `core.chat()` + `FakeProvider` 验证 fake mode 全链路。新 dogfood 脚本在此基础上增加 payload 级字段输出。

### Institutional Learnings

- Phase 1 实现记录（`docs/implementation-notes/REAL_RUNTIME_E2E_PHASE1_IMPLEMENTATION_NOTES.md`）记录了原始测试只用 direct dispatcher 的缺陷及修复过程。本轮测试以此为鉴：优先走 `core.chat()` 路径，只在 `_memory_runtime` 拦截等合理情况下 fallback 到 direct dispatcher。

### External References

无。本轮全部基于项目内已有代码和文档。

---

## Key Technical Decisions

- **不改生产代码**：全链路（core.chat → loop → hook → dispatcher → handler → evidence）已在 Phase 1 就位且通过现有测试验证。本轮只需补齐测试覆盖和 dogfood 可观测性。
- **测试文件自包含**：选择 TDD.md 推荐的选项 A——在 `test_memory_anchor_fake.py` 中重新实现所有 7 个测试，不依赖 `test_phase1_real_core_loop.py`。两个文件独立演进，各司其职。
- **优先 core.chat() 路径**：除 test #6（必须 direct dispatch 验证 harness 分类）和 test #7（no_action 需要精确控制输入绕过 policy trigger）外，所有测试优先走 `core.chat()`。
- **no_action 测试走 direct dispatch**：`DeterministicMemoryPolicy` 的 trigger rules 对非记忆触发输入返回 `no_action`，但 `core.chat()` 内 `_memory_runtime.evaluate_user_text` 可能在 loop 之前拦截。为精确验证 handler 的 `no_action` 处置逻辑，此测试走 `dispatcher.route()` 直接调用，并在注释中说明 fallback 原因（遵循 TDD.md §1.5 的先例）。
- **FakeProvider 通过依赖注入进入统一路径**：`chat(provider=FakeProvider())` 是唯一的注入方式，不创建任何 fake-only 代码路径。

---

## Open Questions

### Resolved During Planning

- **是否需要修改 `agent/loop.py` 或 `agent/core.py`**：不需要。现有代码已完全支持 fake mode。
- **dogfood 脚本是复用还是新建**：新建专用 `scripts/dogfood_memory_anchor_fake.py`，补充 payload 级字段输出（`pending_review`、`auto_approved`、`not_confirmed` 等），与现有 `dogfood_phase1_real_core_loop.py` 互补而非替代。
- **测试文件是否复用现有 test_phase1_real_core_loop.py**：不复用。新建自包含文件，遵循 TDD.md 选项 A。

### Deferred to Implementation

- **test #5 是否被 `_memory_runtime` 拦截**：取决于 `chat()` 内 `_memory_runtime.evaluate_user_text` 对 "记住" 前缀的处理。如被拦截导致 `chat()` 返回空串，fallback 到 direct `dispatcher.route()`，并在测试注释中说明原因。实现时根据实际行为选择路径。
- **test #1 的具体断言值**：`pending_review` 的精确值（True/False）取决于 `DeterministicMemoryPolicy` 对 "以后叫我小王" 的决策。当前 trigger rules 下 "以后叫我小王" 不命中任何 RETAIN_PREFIXES，`decide()` 返回 NO_OP，handler 走 `no_action` 分支，`pending_review=False`。若 policy 新增匹配此前缀的 trigger rule，此值可能变为 True（TDD.md §1.7 已记录此耦合）。

---

## Implementation Units

### U1. 新建 `tests/runtime_integration/test_memory_anchor_fake.py` — 7 个 TDD 测试

**Goal:** 创建自包含的 Memory Anchor fake-provider 测试文件，覆盖 core.chat 全链路 + 边界约束（auto_approved、secret-like、no_action、harness 降级）。

**Requirements:** R1, R2

**Dependencies:** None（纯增量，不依赖其他文件修改）

**Files:**
- Create: `tests/runtime_integration/test_memory_anchor_fake.py`

**Approach:**
- 复用 `test_phase1_real_core_loop.py` 中的 `_SpyDispatcher` 模式（直接在新文件中定义等价的 spy wrapper）
- 复用 `_build_phase1_dispatcher()` 工厂（可从 `agent.runtime_integration.phase1_hook` 导入，或在新文件中定义等价 helper）
- 主要走 `core.chat(provider=FakeProvider(), runtime_action_dispatcher=spy)` 路径
- 仅 test #6 和 test #7 走 direct `dispatcher.route()`（前者验证 harness 降级，后者精确控制 no_action 输入）
- 遵循 TDD.md §1.1-§1.7 的测试规格

**Execution note:** 所有测试先写、先红、再绿。每个测试在实现前必须确认它确实失败（RED phase）。

**Patterns to follow:**
- `tests/runtime_integration/test_phase1_real_core_loop.py` — `_SpyDispatcher` 类（lines 433-456）、`_build_phase1_dispatcher()` helper、`_assert_valid_runtime_action_evidence()` helper
- `agent/runtime_integration/phase1_hook.py::build_phase1_dispatcher()` — dispatcher 构建

**Test scenarios:**

#### Test 1: `test_memory_anchor_fake_provider_core_chat_triggers_pending_review`

- **Purpose:** 钉死 fake provider 下 `core.chat()` → memory proposal → `pending_review` 全链路
- **Setup:** 构建 `SpyDispatcher` 包裹真实 dispatcher；准备 `FakeProvider`
- **Action:** 调用 `chat("以后叫我小王", provider=FakeProvider(), runtime_action_dispatcher=spy)`
- **Expected evidence:**
  - spy 捕获到至少 1 次 `route()` 调用
  - `request.payload.core_loop_invoked == True`
  - `request.payload.core_entrypoint == "core.chat"`
  - `request.payload.runtime_hook_name == "loop.turn_end"`
  - action_log 最后一个 event 的 `evidence.evidence_level == "real_core_loop_runtime_e2e"`
  - `evidence.target_module_proof is not None`
  - `evidence.target_module == "MemoryPolicy"`
  - `payload.pending_review in (True, False)`（取决于 policy 决策）
  - `payload.auto_approved == False`
  - `payload.not_confirmed == True`
- **Forbidden behavior:** `chat()` 不抛异常；`evidence_level` 不是 `harness_runtime_e2e`
- **Pass/fail:** 所有 expected evidence 条件满足

#### Test 2: `test_memory_anchor_uses_same_core_path_not_fake_loop`

- **Purpose:** 验证 fake provider 走的是统一 `run_main_loop`，不是 fake-only 路径
- **Setup:** 构建 `SpyDispatcher` + `FakeProvider`
- **Action:** 调用 `chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)`
- **Expected evidence:**
  - spy 捕获的 `RuntimeActionRequest.source == "core_loop"`
  - `payload.core_entrypoint == "core.chat"`
  - `payload.runtime_hook_name == "loop.turn_end"`
  - dispatcher 实例是 `RuntimeActionDispatcher`（不是任何 fake 子类）
  - handler 是 `MemoryTurnEndProposalHandler`（不是 fake/mock handler）
- **Forbidden behavior:** 不存在 `fake_runtime_loop`、`fake_dispatcher` 类；未创建 fake-only 代码路径
- **Pass/fail:** 所有 expected evidence 条件满足

#### Test 3: `test_memory_anchor_no_auto_approve`

- **Purpose:** 验证无论 memory policy 决策如何，`auto_approved` 始终为 `False`
- **Setup:** 构建 `SpyDispatcher` + `FakeProvider`
- **Action:** 调用 `chat("记住：以后叫我小王", provider=FakeProvider(), runtime_action_dispatcher=spy)`；如被 `_memory_runtime` 拦截导致 `chat()` 返回空串，改为使用不含 "记住" 前缀但含 memory 关键词的输入（如 "以后叫我小王"），或从 spy 捕获的 `dispatcher.route()` 参数中取 payload 做断言
- **Expected evidence:**
  - `payload.auto_approved == False`
  - `payload.not_confirmed == True`
  - evidence 中 `no_silent_retain == True`
- **Forbidden behavior:** payload 中不出现 `human_approved == True`；`auto_approved` 不为 `True`
- **Pass/fail:** 所有 expected evidence 条件满足
- **注意:** 验证的是 `MemoryTurnEndProposalHandler` 的硬编码约束，不是 `chat()` 的 `_memory_runtime` 行为（TDD.md §1.3 关注点区分）

#### Test 4: `test_memory_anchor_does_not_read_memory_episodes`

- **Purpose:** 验证 memory proposal handler 不读取真实 memory episodes
- **Setup:** 构建 `SpyDispatcher` + `FakeProvider`
- **Action:** 调用 `chat("以后叫我小王", provider=FakeProvider(), runtime_action_dispatcher=spy)`
- **Expected evidence:**
  - action_log 中所有 event 的 `payload.real_episodes_read == False`
- **Forbidden behavior:** 任何 payload 中 `real_episodes_read == True`
- **Pass/fail:** 所有 action_log event 的 `real_episodes_read` 均为 `False`

#### Test 5: `test_memory_anchor_secret_like_input_is_redacted_or_should_not_remember`

- **Purpose:** 验证含 secret-like pattern 的输入被自动拒绝
- **Setup:** 构建 `SpyDispatcher` + `FakeProvider`
- **Action:** 调用 `chat("记住这个 api_key: sk-abc123def456", provider=FakeProvider(), runtime_action_dispatcher=spy)`；如被 `_memory_runtime` 拦截导致 `chat()` 返回空串，改为直接构造 `RuntimeActionRequest` 走 `dispatcher.route()`
- **Expected evidence:**
  - `payload.disposition == "should_not_remember"`
  - `payload.secret_like_detected == True`
  - `payload.redacted_secret == True`
  - `payload.pending_review == False`
- **Forbidden behavior:** secret-like 输入不产生 `pending_review == True`；API key pattern 不出现在任何 payload 文本中
- **Pass/fail:** 所有 expected evidence 条件满足
- **注意:** fallback 到 direct route 时需在注释中说明原因（遵循 TDD.md §1.5 先例）

#### Test 6: `test_memory_anchor_direct_dispatch_is_harness_not_real_core_loop`

- **Purpose:** 验证直接 `dispatcher.route()` 调用只能得到 `harness_runtime_e2e`，不能冒充 `real_core_loop_runtime_e2e`
- **Setup:** 构建 dispatcher（不通过 spy）
- **Action:** 手工构造不含 `core_loop_invoked` 的 `RuntimeActionRequest`，调用 `dispatcher.route(request)`
- **Expected evidence:**
  - `result.evidence["evidence_level"] == "harness_runtime_e2e"`
  - `result.evidence.get("core_loop_invoked") is not True`
  - `result.evidence["target_module_proof"] is not None`（evidence chain 完整，但分类降级）
- **Forbidden behavior:** `evidence_level` 不是 `real_core_loop_runtime_e2e`
- **Pass/fail:** 分类正确降级到 `harness_runtime_e2e`

#### Test 7: `test_memory_anchor_no_action_still_produces_runtime_action_event`

- **Purpose:** 验证 `disposition=no_action` 仍产生 RuntimeActionEvent 进入 action_log（P2 修复）
- **Setup:** 构建 dispatcher
- **Action:** 构造 `RuntimeActionRequest`，payload 中 user_message 使用不触发 memory policy 的输入（如 "今天天气不错"），走 `dispatcher.route(request)`
- **Expected evidence:**
  - dispatcher.action_log 包含 1 个 event
  - `result.status == "success"`
  - `payload.disposition == "no_action"`
  - `payload.pending_review == False`
  - `payload.auto_approved == False`
  - `payload.not_confirmed == True`
  - `result.evidence["target_module_proof"] is not None`（target 仍被调用）
  - `result.evidence["dispatcher_routed"] == True`
- **Forbidden behavior:** `no_action` 不导致 dispatcher 跳过 event 记录；handler 不抛异常
- **Pass/fail:** action_log 有 event，且 payload 正确标记为 no_action
- **注意:** 采用 direct dispatch 路径以精确控制输入，绕过 `DeterministicMemoryPolicy` 的 trigger rules 和 `_memory_runtime` 拦截。测试注释中说明此选择。

**Verification:**
- 全部 7 个测试通过：`HOME=/private/tmp/my-first-agent-phase1-home .venv/bin/python -m pytest tests/runtime_integration/test_memory_anchor_fake.py -q`
- 每个测试在执行前先确认 RED phase（测试因正确的理由失败）

---

### U2. 新建 `scripts/dogfood_memory_anchor_fake.py` — fake mode 专用 dogfood 脚本

**Goal:** 创建 Memory Anchor fake mode 专用 dogfood 脚本，输出满足 DOGFOOD_PLAN.md §2.4 全部 PASS 标准的人类可读报告。

**Requirements:** R3, R5

**Dependencies:** U1（可与 U1 并行，但验证依赖 U1 测试通过）

**Files:**
- Create: `scripts/dogfood_memory_anchor_fake.py`

**Approach:**
- 基于 `scripts/dogfood_phase1_real_core_loop.py` 的结构，增强 payload 级字段输出
- 走 `core.chat()` + `FakeProvider` + `build_phase1_dispatcher()` 路径
- 报告输出到 `/private/tmp/phase1_memory_anchor_dogfood_report.txt` 和 `.json`
- 从 `dispatcher.action_log` 中提取每个 event 的 payload 字段（`pending_review`、`auto_approved`、`not_confirmed`、`disposition`、`secret_like_detected` 等）
- PASS/FAIL 判定逻辑覆盖 DOGFOOD_PLAN.md §2.4 全部 13 条标准

**Patterns to follow:**
- `scripts/dogfood_phase1_real_core_loop.py` — 整体结构（provider 构建、dispatcher 构建、chat() 调用、报告生成）
- DOGFOOD_PLAN.md §2.4 — PASS 标准清单

**Test scenarios:** N/A（dogfood 脚本本身不包含 pytest 测试；其正确性通过人工运行验证）

**Verification:**
- 运行 `HOME=/private/tmp/my-first-agent-phase1-home PHASE1_REPORT_PATH=/private/tmp/phase1_memory_anchor_dogfood_report.txt .venv/bin/python scripts/dogfood_memory_anchor_fake.py`
- 输出报告 status 为 PASS
- JSON 报告包含 action_log，每个 event 展开 payload 字段
- 脚本不读 `.env`、不调真实 API

---

### U3. 新建 `docs/implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md`

**Goal:** 记录 Memory Anchor fake-provider 实现的 spec gaps、assumptions、tradeoffs、deviations、stop-condition near misses 及 deferred 决策。

**Requirements:** R6

**Dependencies:** U1, U2（记录实现后的实际状态）

**Files:**
- Create: `docs/implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md`

**Approach:**
- 按照用户要求的 8 个条目组织内容
- 记录 `agent/loop.py:78-79` hook 硬编码的现状和 real smoke deferred 原因
- 记录 no_action P2 的处理方式
- 记录 fake provider 为何不等于第二套核心路径

**Patterns to follow:**
- `docs/implementation-notes/REAL_RUNTIME_E2E_PHASE1_IMPLEMENTATION_NOTES.md` — 既有实现记录的风格和结构

**Test scenarios:** N/A（纯文档）

**Verification:**
- 文件包含全部 8 个必要条目
- 内容与 SPEC.md/TDD.md/DOGFOOD_PLAN.md 一致
- 无 overclaim（明确标注 deferred 项和未验证项）

---

## System-Wide Impact

- **Interaction graph:** 本轮不改生产代码，无 callback/middleware/observer 影响。新增的测试文件和 dogfood 脚本均为独立增量。
- **Error propagation:** N/A（无生产代码变更）
- **State lifecycle risks:** 无。测试使用 `/private/tmp` 作为 HOME，dogfood 报告写入 `/private/tmp`，不触及项目状态。
- **API surface parity:** N/A（无 API 变更）
- **Integration coverage:** 7 个测试中 4 个走 `core.chat()` 真实路径（test #1, #2, #3, #4），2 个走 direct dispatcher（test #6, #7），1 个优先 `core.chat()` 必要时 fallback（test #5）。跨层覆盖充分。
- **Unchanged invariants:** 以下接口和行为明确不变：`agent/core.py::chat()` 签名、`agent/loop.py::run_main_loop()` 行为、`agent/runtime_integration/memory_hook.py::MemoryTurnEndProposalHandler` 三路处置逻辑、`agent/runtime_integration/dispatcher.py::RuntimeActionDispatcher.route()` 行为、`agent/runtime_integration/evidence.py::classify_evidence_level()` 分类逻辑。

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `DeterministicMemoryPolicy` trigger rules 变更导致 test #1/#3 失败 | TDD.md §1.7 已记录此耦合；失败时优先检查测试输入是否仍命中 policy trigger rules |
| `_memory_runtime.evaluate_user_text` 拦截 "记住" 前缀导致 `chat()` 返回空串 | test #3, #5 已设计 fallback 路径（direct dispatcher），不影响核心约束验证 |
| 新测试与 `test_phase1_real_core_loop.py` 中的 `_SpyDispatcher` 定义重复 | 接受此重复——两个文件独立演进，各自维护 spy 定义。不提取共享 helper 以避免跨测试文件的耦合 |

---

## Documentation / Operational Notes

- 运行 fake mode 测试不需要任何 opt-in 环境变量
- 运行 fake mode dogfood 不需要 `MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1`
- 所有输出写入 `/private/tmp`，不污染 repo

---

## Sources & References

- **Origin document:** [docs/real-e2e/memory-anchor/SPEC.md](../real-e2e/memory-anchor/SPEC.md)
- **TDD specification:** [docs/real-e2e/memory-anchor/TDD.md](../real-e2e/memory-anchor/TDD.md)
- **Dogfood plan:** [docs/real-e2e/memory-anchor/DOGFOOD_PLAN.md](../real-e2e/memory-anchor/DOGFOOD_PLAN.md)
- **Existing Phase 1 tests:** [tests/runtime_integration/test_phase1_real_core_loop.py](../../tests/runtime_integration/test_phase1_real_core_loop.py)
- **Existing dogfood:** [scripts/dogfood_phase1_real_core_loop.py](../../scripts/dogfood_phase1_real_core_loop.py)
- **Phase 1 implementation notes:** [docs/implementation-notes/REAL_RUNTIME_E2E_PHASE1_IMPLEMENTATION_NOTES.md](../implementation-notes/REAL_RUNTIME_E2E_PHASE1_IMPLEMENTATION_NOTES.md)
- **Key source files:** `agent/core.py`, `agent/loop.py`, `agent/runtime_integration/memory_hook.py`, `agent/runtime_integration/dispatcher.py`, `agent/runtime_integration/evidence.py`, `agent/runtime_integration/phase1_hook.py`

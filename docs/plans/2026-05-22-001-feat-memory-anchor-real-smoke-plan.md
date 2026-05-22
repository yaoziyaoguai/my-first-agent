---
title: feat: Memory Proposal Anchor real provider smoke
type: feat
status: active
date: 2026-05-22
origin: docs/real-e2e/memory-anchor/SPEC.md
---

# feat: Memory Proposal Anchor real provider smoke

## Summary

在 hook parameterization 已就位的基础上，新增 real provider smoke dogfood 脚本和 gated 测试，验证真实 LLM provider 走同一 `core.chat()` → `run_main_loop()` → turn-end hook 路径，产出 `provider_kind=real`、`provider_external_call=true`、`external_side_effects=false` 的 pending_review-only evidence。不改任何生产代码——基础设施已通过 fake provider phase + hook parameterization 完全就位。

---

## Problem Frame

Memory Anchor fake-provider path 和 hook parameterization 已通过独立审计并 push。`LoopDependencies` 已携带 `provider_kind` / `provider_external_call` 元数据，`_resolve_provider_evidence_metadata()` 已正确将 `anthropic_native` 等真实 provider type 解析为 `("real", True)`。但尚无端到端验证证明 real provider 真的能走通同一 `core.chat()` 路径并产出正确的 evidence 元数据。本轮填补此空白。

---

## Requirements

- R1. Real provider smoke dogfood 脚本存在，通过 `core.chat()` + real provider 验证全链路
- R2. Dogfood 脚本默认不可运行——需 `MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1` 显式 opt-in
- R3. 未授权时 fail-closed：dogfood 退出并提示授权信息，pytest 自动 skip
- R4. 不读 `.env` 内容，不打印 API key 到 stdout/stderr/report
- R5. Report 仅含安全字段：`auth_status`、`key_source_kind`、`project_dotenv_loaded`、`shell_env_fallback_used`
- R6. `provider_kind=real`、`provider_external_call=true`、`external_side_effects=false` 全部正确产出
- R7. `pending_review` only、`auto_approved=False`、`not_confirmed=True` 约束在 real provider 下不退化
- R8. `target_module_proof` 存在且完整
- R9. Fake provider path 不回归（现有 122 个 runtime_integration 测试继续通过）
- R10. Direct dispatcher 不能冒充 real provider E2E
- R11. Unknown provider → fail-closed，不 overclaim `real_provider_core_loop_e2e`

**Origin actors:** N/A（基础设施验证，无用户角色区分）
**Origin flows:** F1: core.chat → real provider → run_main_loop → turn-end hook → dispatcher → handler → evidence (see SPEC §2.2)

---

## Scope Boundaries

- 只做 real provider smoke（Layer 1 smoke，非 full real E2E）
- 不改任何生产代码（`agent/core.py`、`agent/loop.py`、`agent/runtime_integration/*.py`、`agent/provider/*.py` 均不改动）
- 不做 Approval/Retain（Layer 2）
- 不做 Recall/Use（Layer 3）
- 不读取 `.env` 文件内容
- 不打印或记录 API key
- 不写 `human_approved`
- 不 auto approve
- 不读取 `memory/episodes/*.jsonl`
- 不改 Memory governance
- 不改 checkpoint schema
- 不做 ToolRegistry / Skill / Checkpoint / Streaming / SubAgent 扩展
- 不新增 real-only loop / real-only dispatcher
- 不新增 evidence_level 分类值（当前 `real_core_loop_runtime_e2e` 对 fake/real 通用；`provider_kind` 字段提供区分）

### Deferred to Follow-Up Work

- `real_provider_core_loop_e2e` evidence_level 扩展：当前分类器不区分 fake/real provider 的 evidence_level。未来可基于 `provider_kind=real` + `provider_external_call=true` 新增此级别（SPEC.md §5.2 已规划）
- Layer 2 Approval/Retain E2E：待 Layer 1 完成后单独规划
- Layer 3 Recall/Use E2E：待 Layer 2 完成后单独规划
- 完整 real provider E2E（含 tool execution / checkpoint / streaming）

---

## Context & Research

### Relevant Code and Patterns

- **Provider 工厂**：`agent/provider/factory.py::build_model_provider_from_env()` 从 `MY_FIRST_AGENT_LLM_PROVIDER` 环境变量读取 provider type，构造真实 provider。这是 real smoke 的 provider 注入点。
- **Provider 配置**：`agent/provider/config.py::load_agent_provider_config()` 从 `os.environ` 读取 API key/model/base_url，不读 `.env` 文件。`AgentProviderConfig.redacted_summary()` 提供安全的诊断输出（`api_key: "SET"/"empty"`）。
- **Hook 参数化**：`agent/core.py:765-767` 在 `_run_main_loop` 构造 `LoopDependencies` 前调用 `_resolve_provider_evidence_metadata()` 预解析 provider 元数据。`agent/loop.py:67-68` 从 `dependencies` 读取 `provider_kind` 和 `provider_external_call`。
- **`_resolve_provider_evidence_metadata`**：`agent/core.py:686-740` — 只读 `provider.provider_type` 字符串常量，白名单匹配，未知 → `("unknown", False)` fail-closed。已有 11 个单元测试覆盖（`tests/unit/test_provider_evidence_metadata.py`）。
- **Fake dogfood 模式**：`scripts/dogfood_memory_anchor_fake.py` 已验证 `core.chat()` + `FakeProvider` + `build_phase1_dispatcher()` 全链路。Real smoke 脚本在此基础上增加 provider 切换和授权门控。
- **Handler 三路处置**：`agent/runtime_integration/memory_hook.py` — `should_not_remember`（secret-like/REJECT）、`proposed`（RETAIN/UPDATE）、`no_action`（其他）。三路均硬编码 `auto_approved=False`、`not_confirmed=True`、`real_episodes_read=False`。Real smoke 不改此行为。

### Institutional Learnings

- Phase 1 实现记录（`docs/implementation-notes/REAL_RUNTIME_E2E_PHASE1_IMPLEMENTATION_NOTES.md`）：原始缺陷是只用 direct dispatcher 验证，导致 evidence 被错误分类为 `harness_runtime_e2e`。本轮 dogfood 严格走 `core.chat()` 路径。
- Hook parameterization 实现记录（`docs/implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md`）：记录了 `LoopDependencies` 不接收完整 provider 对象、`provider_kind` 粗粒度三态、`provider_external_call` vs `external_side_effects` 拆分的架构决策。Real smoke 是这些决策的首次端到端验证。

### External References

无。全部基于项目内已有代码和文档。

---

## Key Technical Decisions

- **不改生产代码**：Hook parameterization 已完成，`_resolve_provider_evidence_metadata` 正确解析 real provider type，`LoopDependencies` 已携带 provider metadata，`_try_phase1_turn_end_runtime_action` 已动态读取。Real smoke 只需注入 real provider 即可触发正确的 metadata 流。
- **新增专用 dogfood 脚本而非扩展现有脚本**：`scripts/dogfood_memory_anchor_fake.py` 是默认安全模式（无需授权、无外部调用）。Real smoke 需要独立的授权门控和不同的 provider 构造逻辑。合并两套逻辑到同一脚本会增加误用风险——CLI flag 可能被遗漏或误设。
- **`MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1` 作为 opt-in**：遵循 TDD.md §2 和 DOGFOOD_PLAN.md §3.2 的建议。这是一个广泛认可的模式（类似于 `RUN_REAL_TESTS=1`），含义清晰，fail-closed。
- **Report 安全字段白名单**：仅允许 `auth_status`（`"authenticated"/"unauthenticated"`）、`key_source_kind`（`"env_var"` 或 env var name）、`project_dotenv_loaded`（`true/false`）、`shell_env_fallback_used`（`true/false`）。不允许 `api_key`（即使 masked）、`base_url`、raw env values。
- **Fake/real 共享同一条核心路径**：`chat(provider=real_provider)` 是唯一的注入方式。real provider 通过 `build_model_provider_from_env()` 构造，进入与 `chat(provider=FakeProvider())` 完全相同的 `core.chat()` → `run_main_loop()` 路径。不创建任何 real-only 代码路径。

---

## Open Questions

### Resolved During Planning

- **是否需要修改 `agent/loop.py` 或 `agent/core.py`**：不需要。Hook parameterization 已就位。
- **Dogfood 脚本是复用还是新建**：新建专用 `scripts/dogfood_memory_anchor_real_smoke.py`。与 fake dogfood 独立，各自维护。
- **测试文件是合并还是新建**：新建 `tests/runtime_integration/test_memory_anchor_real.py`，与 `test_memory_anchor_fake.py` 独立。
- **是否需要扩展 evidence_level 分类**：本轮不扩展。`evidence_level` 保持 `real_core_loop_runtime_e2e`（与 fake 相同）。`provider_kind=real` 在 evidence 元数据中提供区分。新的 `real_provider_core_loop_e2e` level 留待后续。

### Deferred to Implementation

- **Real provider 的具体响应内容**：取决于实际 LLM 输出。dogfood 只验证 evidence 字段，不验证响应内容的语义正确性。
- **`chat()` 返回空串的处理**：`_memory_runtime.evaluate_user_text` 可能拦截特定输入导致 `chat()` 返回空串。dogfood 应选择不太可能触发 memory confirmation 的输入（如 "hello" 或 "今天天气不错"），确保 turn-end hook 触发。
- **网络错误场景**：API 调用可能因网络/认证/配额问题失败。dogfood 应捕获异常并以 PARTIAL 状态报告，而非崩溃。

---

## Implementation Units

### U1. 新建 `scripts/dogfood_memory_anchor_real_smoke.py` — real provider smoke dogfood 脚本

**Goal:** 创建 real provider smoke 专用 dogfood 脚本，验证真实 LLM provider 走同一 `core.chat()` 路径并产出正确的 evidence 元数据。

**Requirements:** R1, R2, R3, R4, R5, R6, R7, R8

**Dependencies:** None（纯增量，不依赖其他文件修改）

**Files:**
- Create: `scripts/dogfood_memory_anchor_real_smoke.py`

**Approach:**
- 基于 `scripts/dogfood_memory_anchor_fake.py` 的结构，增加以下差异化逻辑：
  1. **授权门控**：入口处检查 `os.environ.get("MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE") == "1"`，非授权时打印授权说明并 `sys.exit(2)`
  2. **Provider 构造**：调用 `build_model_provider_from_env()` 构造真实 provider，而非 `FakeProvider()`
  3. **安全报告**：从 `AgentProviderConfig.redacted_summary()` 提取安全字段，不输出 API key 或 raw env
  4. **PASS 标准**：在 fake mode 13 条标准基础上，替换 provider 相关检查为 real smoke 专属断言
- 走 `core.chat()` + real provider + `build_phase1_dispatcher()` 路径
- 报告输出到 `/private/tmp/phase1_memory_anchor_real_smoke_report.txt` 和 `.json`
- PASS/FAIL/PARTIAL 判定逻辑遵循 DOGFOOD_PLAN.md §3.4-3.6

**Execution note:** 脚本本身不是 pytest 测试——它通过人工运行验证。实现时优先确保授权门控正确（未授权时 fail-closed），其次确保 secret 不泄露到报告。

**Patterns to follow:**
- `scripts/dogfood_memory_anchor_fake.py` — 整体结构（provider 构建、dispatcher 构建、chat() 调用、报告生成、overclaim prevention）
- `agent/provider/factory.py::build_model_provider_from_env()` — real provider 构建
- `agent/provider/config.py::AgentProviderConfig.redacted_summary()` — 安全配置摘要
- DOGFOOD_PLAN.md §3.4-3.6 — PASS/PARTIAL/FAIL 标准

**Test scenarios:** N/A（dogfood 脚本本身不包含 pytest 测试；其正确性通过人工运行 + gated test U2 验证）

**Verification:**
- 未授权运行 → 打印授权说明，`exit(2)`，不调用任何 API
- 授权运行 → `core.chat()` 完成，报告 status 为 PASS/PARTIAL/FAIL
- 报告不包含 API key pattern（`sk-ant-`、`sk-` 等）
- 报告包含安全字段：`auth_status`、`key_source_kind`、`project_dotenv_loaded`、`shell_env_fallback_used`
- 报告不包含 raw env values、`api_key` 值

---

### U2. 新建 `tests/runtime_integration/test_memory_anchor_real.py` — gated real provider smoke 测试

**Goal:** 创建 gated 测试文件，验证 real provider smoke 的约束边界——默认 skip、授权检查、secret 不打印、pending_review only、unknown provider fail-closed、direct dispatch 降级。

**Requirements:** R2, R3, R4, R5, R6, R7, R8, R9, R10, R11

**Dependencies:** None（可与 U1 并行）

**Files:**
- Create: `tests/runtime_integration/test_memory_anchor_real.py`

**Approach:**
- 遵循 TDD.md §2.1-2.4 的测试规格，实现 4 个 gated 测试
- 所有测试以 `pytest.skip()` 为默认路径（检查 `MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE` env var）
- 复用 `scripts/dogfood_memory_anchor_fake.py` 中的 `_SpyDispatcher` 模式（在新文件中定义等价 wrapper）
- 需要真实 API 调用的测试（§2.3, §2.4）在 skip guard 之后构造 real provider 并走 `core.chat()`

**Execution note:** 所有测试先写、先红（确认 skip 逻辑正确）、再绿。测试的 "red phase" 验证的是 skip guard 在未授权时正确触发。

**Patterns to follow:**
- `tests/runtime_integration/test_memory_anchor_fake.py` — `_SpyDispatcher` 模式、`_build_phase1_dispatcher()` helper
- `tests/unit/test_provider_evidence_metadata.py` — `pytest.skip()` 模式用于未实现/未授权功能
- TDD.md §2.1-2.4 — 测试规格

**Test scenarios:**

#### Test 1: `test_real_provider_requires_explicit_authorization`

- **Purpose:** 验证 real provider smoke 默认 gated/skip
- **Category:** Error path
- **Action:** 在未设置 `MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1` 时运行
- **Expected:** `pytest.skip("real provider smoke requires explicit opt-in")`
- **Covers:** R2, R3

#### Test 2: `test_real_provider_uses_scoped_loader_without_printing_secret`

- **Purpose:** 验证 real provider 使用 scoped loader，不打印 API key
- **Category:** Error path
- **Setup:** 设置 opt-in，构建 real provider + spy dispatcher
- **Action:** 调用 `chat("hello", provider=real_provider, runtime_action_dispatcher=spy)`
- **Expected evidence:**
  - `provider_kind == "real"`
  - `provider_external_call == True`
  - stdout/stderr 不含 `sk-ant-`、`sk-` 等 API key pattern
  - evidence 中 `external_side_effects == False`
- **Covers:** R4, R5, R6, TDD.md §2.2
- **注意:** 此测试需要真实 API 调用。如果 opt-in 已设置但 API key 无效/缺失，应捕获 `ProviderConfigurationError` 并以 skip 处理（注明 "API key not configured"）。

#### Test 3: `test_real_provider_still_pending_review_only`

- **Purpose:** 验证真实 LLM provider 下 memory proposal 仍为 pending_review only
- **Category:** Happy path
- **Setup:** 设置 opt-in，构建 real provider + spy dispatcher
- **Action:** 调用 `chat("以后叫我小王", provider=real_provider, runtime_action_dispatcher=spy)`
- **Expected evidence:**
  - `payload.auto_approved == False`
  - `payload.not_confirmed == True`
  - evidence 中 `no_silent_retain == True`
  - evidence 中 `provider_kind == "real"`
  - evidence 中 `provider_external_call == True`
  - `evidence_level == "real_core_loop_runtime_e2e"`
- **Covers:** R6, R7, R8, TDD.md §2.3

#### Test 4: `test_real_provider_does_not_write_human_approved`

- **Purpose:** 验证真实 provider 下不写 human_approved memory
- **Category:** Error path
- **Setup:** 设置 opt-in，构建 real provider + spy dispatcher
- **Action:** 调用 `chat(...)` with real provider
- **Expected evidence:**
  - action_log 中所有 event 的 `payload.human_approved` 不为 `True`
  - action_log 中所有 event 的 `payload.auto_approved == False`
- **Covers:** R7, TDD.md §2.4

**Verification:**
- 未授权时：全部 4 个测试 skip（`pytest -q` 显示 4 skipped）
- 授权时：`MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1 .venv/bin/python -m pytest tests/runtime_integration/test_memory_anchor_real.py -q` — 测试 #2, #3, #4 通过（或 skip 如果 API key 未配置）
- Fake provider path 不回归：`.venv/bin/python -m pytest tests/runtime_integration/test_memory_anchor_fake.py -q` 仍全部通过

---

### U3. 更新 `docs/implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md` — 追加 real smoke 记录

**Goal:** 记录 real provider smoke 的实现状态、授权机制、secret 边界、PASS/PARTIAL/FAIL 标准和 stop conditions。

**Requirements:** R9（记录不回归的证据）

**Dependencies:** U1, U2（记录实现后的实际状态）

**Files:**
- Modify: `docs/implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md`

**Approach:**
- 在现有文件末尾追加 "## Real Provider Smoke Phase" 章节
- 记录：授权机制设计、secret 边界、PASS 标准、与 fake 的差异、已知限制
- 不 overclaim：明确标注 deferred 项（`real_provider_core_loop_e2e` evidence_level 扩展、Layer 2/3）

**Patterns to follow:**
- 现有文件的前半部分（fake provider phase 记录）——风格和结构

**Test scenarios:** N/A（纯文档）

**Verification:**
- 文件包含 real smoke 章节
- 明确标注 deferred 项
- 与 SPEC.md/TDD.md/DOGFOOD_PLAN.md 一致

---

## System-Wide Impact

- **Interaction graph:** 本轮不改生产代码，无 callback/middleware/observer 影响。新增的 dogfood 脚本和 gated 测试均为独立增量。
- **Error propagation:** N/A（无生产代码变更）
- **State lifecycle risks:** 无。测试使用 `/private/tmp` 作为 HOME，dogfood 报告写入 `/private/tmp`，不触及项目状态。
- **API surface parity:** N/A（无 API 变更）
- **Integration coverage:** 4 个 gated 测试中：test #1 验证授权 gate（无需真实 API），test #2-4 走 `core.chat()` + real provider 真实路径。跨层覆盖充分。
- **Unchanged invariants:** 以下接口和行为明确不变：`agent/core.py::chat()` 签名和路径、`agent/loop.py::run_main_loop()` 行为、`agent/runtime_integration/memory_hook.py::MemoryTurnEndProposalHandler` 三路处置逻辑、`_resolve_provider_evidence_metadata()` 解析逻辑、`LoopDependencies` 字段结构。

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| 用户环境无有效 API key → dogfood/test 失败 | 优雅降级：dogfood 以 PARTIAL 状态报告 `auth_status=unauthenticated`；pytest skip 并注明原因 |
| 网络/API 不可用 → dogfood/test 失败 | 异常捕获 + PARTIAL 状态；不崩溃 |
| Real provider 响应不可预测 → 断言不稳定 | 只验证 evidence 结构字段（`provider_kind`、`auto_approved` 等），不验证响应内容 |
| `_memory_runtime` 拦截输入导致 chat() 返回空串 | 选择不触发 memory confirmation 的输入（如 "hello"） |
| Fake provider path 回归 | U2 完成后运行全量 `tests/runtime_integration/` 确认 |

---

## Documentation / Operational Notes

- **运行 real smoke dogfood（需授权）**：
  ```bash
  MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1 \
    .venv/bin/python scripts/dogfood_memory_anchor_real_smoke.py
  ```
- **运行 fake mode dogfood（默认安全）**：
  ```bash
  .venv/bin/python scripts/dogfood_memory_anchor_fake.py
  ```
- **运行 gated 测试**：`MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1 .venv/bin/python -m pytest tests/runtime_integration/test_memory_anchor_real.py -q`
- **运行所有 runtime_integration 测试（含 fake，不含 real）**：`.venv/bin/python -m pytest tests/runtime_integration/ -q`
- 所有 real smoke 输出写入 `/private/tmp`，不污染 repo
- Real smoke 不写 repo report，除非用户明确要求

---

## Sources & References

- **Origin document:** [docs/real-e2e/memory-anchor/SPEC.md](../real-e2e/memory-anchor/SPEC.md)
- **TDD specification:** [docs/real-e2e/memory-anchor/TDD.md](../real-e2e/memory-anchor/TDD.md)
- **Dogfood plan:** [docs/real-e2e/memory-anchor/DOGFOOD_PLAN.md](../real-e2e/memory-anchor/DOGFOOD_PLAN.md)
- **Implementation notes:** [docs/implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md](../implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md)
- **Hook param plan:** [docs/plans/2026-05-21-002-feat-memory-anchor-hook-param-plan.md](../plans/2026-05-21-002-feat-memory-anchor-hook-param-plan.md)
- **Fake plan:** [docs/plans/2026-05-21-001-feat-memory-anchor-fake-plan.md](../plans/2026-05-21-001-feat-memory-anchor-fake-plan.md)
- **Existing fake tests:** `tests/runtime_integration/test_memory_anchor_fake.py`
- **Existing fake dogfood:** `scripts/dogfood_memory_anchor_fake.py`
- **Provider unit tests:** `tests/unit/test_provider_evidence_metadata.py`
- **Key source files:** `agent/core.py`, `agent/loop.py`, `agent/runtime_integration/memory_hook.py`, `agent/provider/factory.py`, `agent/provider/config.py`

# refactor: Window 2 — SPA-1 safe-metadata ownership + CR-1 action_scheduler governance

> 本文件是 implementation plan（决策与施工单元），不含代码 diff。施工在后续窗口执行。

---

## 1. Status

- **APPROVED — implementation pending.** 本轮只落本计划文档，不写 production code、
  不写 tests、不改 Roadmap/North Star、不 push。
- **Owner 已批准 Option B**（masking ownership 不做大搬迁，详见 §5/§8A）。
- **Owner 已批准 trimmed Option C**（SPA-1 + CR-1 co-delivery，窄范围）。
- **OD-7 production approval hook 继续 deferred**（不在本窗口）。
- 计划深度：Standard（行为中性、低风险，6 个 implementation unit）。

---

## 2. Title

Window 2：SPA-1（safe-metadata ownership lock）+ CR-1（action_scheduler
registered-not-routed governance）co-delivery，顺手补 W1-D4 fallback dispatch
guard 与 legacy-path compatibility inventory。全程 behavior-neutral。

---

## 3. Context

Window 1（`ACCEPT_WITH_TRACKED_DEBT — CLOSED`，HEAD `786c84d`）交付 SA-1
（V0 production routing，default-off flag）+ GE-1 Phase A（golden E2E），并锁定
status taxonomy（rejected / policy_blocked / failed / not_supported / success）。

Window 2 推进 SoT / governance 维度，低风险、行为中性，直接对应 Roadmap §14.2
推荐主线：*"SPA-1（safe-metadata ownership spike）+ CR-1（action_scheduler 标注）：
清 SoT 与 framework-drift，低风险。"*

本窗口性质：**ownership 锁定 + governance 标注 + 一处 debt guard + 兼容路径
characterization**，不是 new-capability 窗口。多数"广义 Safety/Policy/Approval"
能力在 Window 1 已建（taxonomy）或被 Roadmap 显式 defer（OD-7），故本窗口按代码
事实与 Roadmap 真实 item 收敛执行（见 §5 Reconciliation）。

---

## 4. Source documents / source commits

- North Star（冻结，不改）：`docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md`
  sha256 `c73c2b3dbe926f30834a5d9ab20155cc947ab27158339a7c8b221d0d80568cde`
- Window 1 Plan（冻结，不改）：
  `docs/plans/2026-06-12-002-feat-subagent-v0-production-routing-plan.md`
  sha256 `0630a7d4326bd1315e75b7521bab127d10f6cb97c0ef43b901e152cb87f76960`
- Roadmap（本窗口不改，closure 时统一回写）：
  `docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`
  （Theme 7 SPA-1/SPA-2、Theme 8 CR-1、§11 OD-7、§12 红线、§14.2 windowing、§9.3 W1-D4）
- Window 1 closure：`docs/06-audit/WINDOW_1_CLOSURE_AUDIT.zh.md`
- 受治理代码范围：`26ed44f..786c84d`
- Baseline branch / HEAD：`main` / `786c84d`

---

## 5. Roadmap reconciliation

用户口头的 theme 名与 Roadmap 真实 item ID 不一致，本窗口按 Roadmap 真实 item +
代码事实收敛执行：

| 用户口头框架 | Roadmap / 代码事实（本窗口采用） |
|---|---|
| "SPA-1 = Safety / Policy / Approval" | **"Safety/Policy/Approval" 是 Theme 7（更大）。** 真实 item **SPA-1 = Safe metadata ownership**（masking owner 收敛，窄）。Theme 7 还含 SPA-2（permission-staging doc-align）与 OD-7。 |
| "需要 production approval / policy 大建设" | policy/approval taxonomy 在 **Window 1 已建并测试**（`test_subagent_v0_failure_taxonomy.py`、`test_tool_path_unification_l1_3.py`：rejected→不执行 / confirmation_required→AWAITING_USER / malformed→fail-safe）。**production approval hook 属 OD-7，继续 deferred。** |
| "CR-1 = Compatibility Retirement" | **"Compatibility Retirement" 是 Theme 8（更大）。** 真实 item **CR-1 = action_scheduler registered-not-routed governance**（标注 + boundary test，**不删**）。 |
| "广义兼容退役（删 legacy）" | 红线 §12 #4/#13 禁止删除 legacy L1/L2 与 action_scheduler。本窗口对 legacy 路径只做 **characterization inventory**，不删、不行为变化。 |

**本窗口不直接修改 Roadmap**；SPA-1 / CR-1 状态在 **Window 2 closure** 时由
docs-only 流程统一回写（见 §16）。

---

## 6. Roadmap alignment

- **SPA-1**（Theme 7，P2 `active`）→ 收敛 masking owner，test-locked。本窗口落地后
  closure 回写 `completed`。
- **CR-1**（Theme 8，P2 `active`）→ action_scheduler inert governance 标注 + boundary
  test。closure 回写 `completed`。
- **W1-D4**（Roadmap §9.3，Medium debt）→ 本窗口补 targeted guard；closure 标注
  guard 已落（debt 状态由 negative-match 升级为 test-guarded）。
- **OD-7**（§11，Open / accepted_deferred）→ 不动，保持 deferred。
- **SPA-2**（permission-staging doc-align）/ **CR-2/CR-3/CR-4** → 不在本窗口。

---

## 7. Graphify evidence summary

> 本计划引用的 symbol / 文件位置均经 Graphify + 真实源码行核验。未修改/提交
> `graphify-out/*`。索引新鲜（mtime > HEAD commit time）。

| 主张 | Graphify / 源码核验 |
|---|---|
| `display_events` 是 canonical masker owner | `agent/display_events.py`：`_SECRET_MASK_PATTERNS`（:104）、`_mask_preview_secrets`（:120）、`mask_user_visible_secrets`（:129） |
| `safe_metadata` 是 thin wrapper / projection | `agent/runtime_integration/safe_metadata.py`：docstring "thin wrapper, not a replacement"（:21）、`from agent.display_events import mask_user_visible_secrets`（:31） |
| `_EXTRA_REDACT_PATTERNS` 为 boundary-local extra redaction | `safe_metadata.py`：定义（:39）、仅在 with-marker 变体应用（:93） |
| action_scheduler inert（未接入 production） | `agent/action_scheduler.py`：`class ActionScheduler`（:215）；`agent/core.py` 默认 `action_scheduler=None`（:697/:772/:1333/:1735）；`main.py` `chat()` 调用（:118/:177）不传 `action_scheduler=` |
| grep-test 陷阱 | `action_scheduler.py:221` docstring 含字面 `ActionScheduler(dispatcher=...)` → boundary test 必须用 AST，不用 grep |
| 现有 AST boundary 基础设施已追踪 action_scheduler | `tests/test_architecture_boundaries.py`：`ast.parse`（:81）、`_collect_agent_imports`（:267）、`agent.action_scheduler` 已在受审 import 集（:546） |
| W1-D4 negative-match fallback | `agent/core.py`：`if v0_result.status == "not_supported":`（:2171）唯一触发 inline fallback |
| legacy paths（retained / no-delete） | `core.py`：`_dispatch_or_fallback_delegation`（:1975，调用点 :898/:931）、`delegate_l1_called`（:2217，handler 未注册→dead）；`subagent_inline.py`：`execution_mode="local_fake"`（:63） |
| 现有 projector 契约测试可复用 | `tests/runtime_integration/test_safe_metadata_projector.py`（声明 display_events 为 canonical、projector 为 thin wrapper） |

---

## 8. Scope（本窗口实际要做的内容）

### A. SPA-1 — safe metadata ownership

- 确认 `display_events.py` 为 **canonical secret-masking owner**（`_SECRET_MASK_PATTERNS`
  + `mask_user_visible_secrets` 为唯一 regex 实现源）。
- 确认 `safe_metadata.py` 为 **projection wrapper / truncation / boundary-local extra
  redaction**：projector 委托 canonical masker，不二次拥有 masking 逻辑。
- `_EXTRA_REDACT_PATTERNS` **保留**，明确定位为 **boundary-local extra redaction**
  （runtime_integration trust-boundary 专用，display_events 故意保持窄正则集）。
- 补 **ownership test**：断言 `_SECRET_MASK_PATTERNS` 仅由 display_events 定义，
  projector 不重复编译同一组 canonical 正则。
- **不做 call-site sweep**（红线 §12 #12）；**不改 masking regex 行为**。
- **Option B 已批准**：不做 masking implementation 大搬迁（Option A 会触及 ~15 处
  caller + 破坏 `test_architecture_boundaries.py` import 契约 + 违反 behavior-neutral，
  明确拒绝）。

### B. CR-1 — action_scheduler governance

- 在 `action_scheduler.py` 顶部加 **`registered-not-routed / inert`** 治理标注。
- 补 **AST boundary test**：
  - `agent.core.chat()` 默认 `action_scheduler=None`；
  - `main.py` `chat()` 调用不传 `action_scheduler=` kwarg（AST 扫描，非 grep）。
- **不接入** scheduler（红线 #13）；**不删除** scheduler；**不做行为变化**。

### C. W1-D4 — fallback dispatch guard

- 用 targeted runtime integration test 锁住 fallback 语义：
  - 只有 `not_supported` 可触发 inline-local fallback；
  - `rejected` 不 fallback；
  - `failed` 不 fallback；
  - `policy_blocked` 不 fallback；
  - unknown / 未来新增 status 不得被静默当作 success 或触发 fallback。
- 走真实 `chat()` + real dispatcher + real `SubAgentV0Handler`，不替换 handler。

### D. Compatibility inventory

- 记录（characterization，非 no-delete guarantee）：
  - inline-local fallback（`core.py` `_runtime_event_not_supported_fallback` / `subagent_inline.py:63` `local_fake`）；
  - pre-loop delegation seam（`core.py:1975` `_dispatch_or_fallback_delegation`）；
  - L1 attempt = retained / dead-ish compatibility path（`core.py:2217`，handler 未注册）；
  - local_fake path。
- 只做 **current-behavior characterization snapshot**，使未来变更"可见"，**不写
  no-delete guarantee**（避免把现状固化、妨碍 W1-D4 / L1 后续清理）。
- L1 dead path：仅 inventory + 可选 label，**不加 retention test**。

---

## 9. Explicit non-goals

继承用户 §禁止 + Roadmap 红线 §12 + planning reviewer 加固：

- 不写 production code、不写 tests（本轮只落 plan 文档）。
- 不删除 inline-local fallback / L1 attempt / pre-loop seam / 任何 rollback path（#4）。
- 不接入 / 拆分 / 删除 action_scheduler（#13）。
- 不做 masking call-site sweep（#12）；不改 masking regex 行为。
- 不做 masking implementation 大搬迁（Option A 拒绝）。
- 不建 production approval enforcement（OD-7 deferred）。
- 不 V0 default-on；不搬 `run_main_loop`；不做 L3 relocation；不 rename
  `route_from_runtime_loop`；不重构 RuntimeAction；不改 provider 系统。
- 不做真实外部 provider E2E（仅 Phase B 计划）。
- 不改 North Star / Window 1 Plan / Roadmap（Roadmap 在 closure 统一回写）/ AGENTS.md /
  `.claude/settings.json`。
- 不 push；不 broad cleanup；不 repo-wide format；不提交 `graphify-out/*`。
- 不写 "no-delete guarantee" 测试（会固化待清理行为）。
- 不做广义 taxonomy 重锁（复用 `test_tool_path_unification_l1_3.py` +
  `test_subagent_v0_failure_taxonomy.py`，避免双份发散语义）。

任一突破 → decision point（§15 / closure），不得静默纳入。

---

## 10. Existing code paths

| 路径 | 位置 | 状态 | 本窗口动作 |
|---|---|---|---|
| canonical masker | `display_events.py`：`_SECRET_MASK_PATTERNS`(:104) / `mask_user_visible_secrets`(:129) | canonical owner（UI-projection） | 确认为 owner（Option B），补 ownership test |
| masking projector | `safe_metadata.py`：import(:31)、`_EXTRA_REDACT_PATTERNS`(:39) | thin wrapper / projection | 形式化为 projection-only；extra redactors 定位 boundary-local |
| masking callers | display_events / tool_result_contract / local_config / tool_executor / target_catalog / safe_metadata（6 文件） | durable + UI 路径 | 不做机械替换（#12） |
| action_scheduler | `action_scheduler.py`：`ActionScheduler`(:215)、docstring 实例化(:221) | inert：core 默认 None、main 不传 | 加 inert 标注 + AST boundary test |
| pre-loop seam | `core.py:1975` `_dispatch_or_fallback_delegation` | live（rollback-safe） | characterize，不删 |
| inline-local fallback | `core.py` `_runtime_event_not_supported_fallback` / `subagent_inline.py:63` | live default-off 路径 | characterize，不删 |
| L1 attempt | `core.py:2217`（handler 未注册→dead） | dead code，retained | inventory + 可选 label，无 retention test |
| W1-D4 negative-match fallback | `core.py:2171` | unguarded Medium debt | targeted guard test |
| tool gate taxonomy | `tool_gate.py` / `test_tool_path_unification_l1_3.py` | built + tested | 复用，不重复 |
| V0 status taxonomy | `test_subagent_v0_failure_taxonomy.py` | built + tested（W1） | 复用，不重复 |

---

## 11. Proposed implementation units

> 施工姿态：characterization / spike / labeling，**behavior-neutral**。每个 unit
> 可独立 commit、可回滚。每个 legacy-path 测试 **必须** `monkeypatch.delenv(
> "SUBAGENT_V0_ROUTING_ENABLED", raising=False)`（flake guard）。

### U1. RED baseline + legacy compatibility inventory
- **Goal**：写 W2-T1..T7 为 RED；产出 legacy-path inventory map。
- **Dependencies**：无。
- **Files**：
  - `tests/runtime_integration/test_safe_metadata_ownership.py`（新）
  - `tests/runtime_integration/test_subagent_v0_fallback_dispatch.py`（新）
  - `tests/runtime_integration/test_legacy_path_inventory.py`（新）
  - `docs/06-audit/WINDOW_2_COMPAT_INVENTORY.zh.md`（新，inventory map）
- **Approach**：先确认现有 taxonomy 覆盖以避免重复；inventory 限定"记录已存在路径"，
  不做穷举 call-graph trace（schedule risk）。
- **Execution note**：characterization-first；RED 因"锁/标注尚不存在"而失败，非因行为错误。
- **Test scenarios**：见 §12 全部（W2-T1..T7），全部 RED。
- **Verification**：RED 套件因预期（缺锁）原因失败；inventory 与 `graphify` call graph 一致。

### U2. SPA-1 single masking-owner lock（Option B）
- **Goal**：确认 `display_events` 为 canonical owner；projector projection-only；锁定。
- **Dependencies**：U1。
- **Files**：`tests/runtime_integration/test_safe_metadata_ownership.py`；
  `docs/06-audit/SPA1_MASKING_OWNERSHIP_DECISION.zh.md`（决策记录，Option B 已批准）。
- **Approach**：Option B（现状即目标形态，~0 production 代码改动）。`_EXTRA_REDACT_PATTERNS`
  按 `safe_metadata.py` 既有 docstring 理由保持 projector-local。
- **Patterns to follow**：镜像 `tests/runtime_integration/test_safe_metadata_projector.py`
  的 projector 契约断言风格。
- **Test scenarios**：W2-T1（唯一定义源）、W2-T2（projection-only 委托）。
- **Verification**：single-owner test green；决策文档记录 Option B + 拒绝 Option A 的证据。

### U3. CR-1 action_scheduler governance label + boundary test
- **Goal**：inert 治理标注 + injection-seam AST boundary test。
- **Dependencies**：U1。
- **Files**：`agent/action_scheduler.py`（仅顶部注释块）；`tests/test_architecture_boundaries.py`（扩展）。
- **Approach**：断言 `chat()` 默认 `action_scheduler is None` **且** `main.py` `chat()`
  调用不含 `action_scheduler=` kwarg（AST 扫描，**非** grep——docstring :221 含字面
  `ActionScheduler(`）。复用 `_collect_agent_imports` / `ast.parse` 基础设施（已追踪
  `agent.action_scheduler` :546）。
- **Test scenarios**：W2-T3。
- **Verification**：标注存在；boundary test green；行为中性。

### U4. W1-D4 exhaustive fallback-dispatch guard
- **Goal**：锁住 negative-match fallback（`core.py:2171`）。
- **Dependencies**：U1。
- **Files**：`tests/runtime_integration/test_subagent_v0_fallback_dispatch.py`。
- **Approach**：断言只有 `not_supported` 触发 inline fallback；`rejected`/`failed`/
  `policy_blocked`/unknown 均不 fallback、不被当作 success。走真实 `chat()`/dispatcher/
  `SubAgentV0Handler`，不替换 handler。
- **Test scenarios**：W2-T4。
- **Verification**：guard green；复用真实 V0 路径。

### U5. Legacy-path characterization snapshots（no delete）
- **Goal**：seam + handler-missing fallback 的 current-behavior 快照。
- **Dependencies**：U1。
- **Files**：`tests/runtime_integration/test_legacy_path_inventory.py`。
- **Approach**：snapshot，**非** guarantee。显式 `delenv`。L1 dead path 仅 inventory/label，
  不加 retention test。
- **Test scenarios**：W2-T5、W2-T6。
- **Verification**：快照与现状一致；G3/G5 仍 green。

### U6. Closure
- **Goal**：rollback floor 复验（复用 G3/G5）；Roadmap 回写（SPA-1→completed、
  CR-1→completed、W1-D4 标注 test-guarded）；登记 Window 2 debt；写 closure audit。
- **Dependencies**：U2..U5。
- **Files**：`docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`；
  `docs/06-audit/WINDOW_2_CLOSURE_AUDIT.zh.md`（新）。**不改 Plan/North Star。**
- **Test expectation**：none —— docs only。
- **Verification**：full suite green；frozen sha256 不变；未 push。

---

## 12. RED-first test matrix

> "RED" = 今天因"锁/标注/guard 尚不存在"而失败，非因行为错误（behavior-neutral）。

| ID | 测试 | RED 原因（今天失败） | 文件 | 层级 |
|---|---|---|---|---|
| W2-T1 | `_SECRET_MASK_PATTERNS` 仅由 display_events 定义；projector 不重复编译同组 canonical 正则 | 无 single-owner 断言 | `tests/runtime_integration/test_safe_metadata_ownership.py` | runtime_integration |
| W2-T2 | projector 委托 `mask_user_visible_secrets`（projection-only）；extra redactors 为 boundary-local 且有文档 | 未断言 | 同上 | runtime_integration |
| W2-T3 | production `chat()` 默认 `action_scheduler is None` **且** `main.py` chat() 不传 kwarg（AST） | injection-seam 无 boundary test | `tests/test_architecture_boundaries.py`（扩展） | architecture boundary |
| W2-T4 | 只有 `not_supported` 触发 inline fallback；rejected/failed/policy_blocked/unknown 不 fallback、不当 success | negative-match seam 未 guard | `tests/runtime_integration/test_subagent_v0_fallback_dispatch.py` | runtime_integration |
| W2-T5 | characterization：flag-off delegate → L1-attempt→inline-local `local_fake`（显式 `delenv`） | 无 seam 级 current-behavior 快照 | `tests/runtime_integration/test_legacy_path_inventory.py` | runtime_integration |
| W2-T6 | characterization：handler-missing → `not_supported` → 受控 inline fallback（复用 G6 断言） | inventory 级快照缺失 | 同上 | runtime_integration |
| W2-T7 | golden 复验：flag-off rollback 仍 green（回归地板） | 复用 G3/G5——**断言，不复制** | `tests/golden_e2e/`（复用现有） | golden_e2e |

**明确不加**（reviewer 强制）：不加广义 rejected/policy_blocked/failed/not_supported
重锁（复用现有两套）；不加 L1 "no-delete guarantee" 测试；不加 provider-failure E2E。

**放置归属**：ownership → `runtime_integration/`（新）；action_scheduler → 扩展
`test_architecture_boundaries.py`（AST 基础设施）；W1-D4 + legacy inventory →
`runtime_integration/`（新）；rollback 地板 → 复用 `golden_e2e/`。无新 provider-contract 测试。

---

## 13. Acceptance criteria

- SPA-1：单一 canonical masking owner test-locked（Option B）；`_EXTRA_REDACT_PATTERNS`
  定位 boundary-local；无 call-site sweep；无 regex 行为变化。
- CR-1：action_scheduler inert 治理标注存在；AST boundary test 在 injection seam green。
- W1-D4：fallback dispatch guard green（只有 `not_supported` fallback）。
- rejected / policy_blocked / approval(confirmation_required→AWAITING_USER) / failed /
  not_supported / success 仍可区分（复用现有测试，无回归、无重复）。
- 无 legacy/rollback 路径被删；Window 1 行为不回归（G3/G5 green）。
- full suite 0 unexpected failures；`git diff --check` clean；touched Python 文件 `ruff` clean。
- Roadmap 在 closure 回写；Window 2 debt 登记；closure audit 写就。
- **no default-on；no L3 overclaim；Plan/North Star sha256 不变；未 push。**

---

## 14. Risks / rollback

| 风险 | 触发信号 | 检测 | rollback | 阻塞? |
|---|---|---|---|---|
| 误选 masking Option A（大搬迁） | diff 触及 tool_executor / tool_result_contract masking import | `test_architecture_boundaries.py` import-allowlist 失败 | 还原至 Option B | **是** |
| action_scheduler grep-test 被 docstring 命中 | boundary test 匹配 `action_scheduler.py:221` | 用 AST 扫描非 grep | 改测试 | 否 |
| env-flag 泄漏导致 flake | legacy 测试随 ambient env 变化 | 强制每条 legacy 测试 `delenv` | 加 `delenv` | 否 |
| CR 误删 rollback path | `git diff` 显示 core.py/subagent_inline.py 删除 | G3/G5 golden 失败 | 还原 | **是若发生** |
| 测试 mock 而非 production path | 新测试用 fake handler/dispatcher | reviewer 检查 + 断言真实 `chat()`/`SubAgentV0Handler` | 重写 | 否 |
| no-delete guarantee 固化待清理行为 | 出现 retention/guarantee 断言 | reviewer 检查 | 删除该断言 | 否 |
| 广义 taxonomy 重锁产生发散语义 | 新测试与现有两套断言冲突 | diff 对照现有测试 | 还原 | 否 |
| metadata 泄漏 secret | `test_safe_metadata_leak_gate.py` 失败 | 现有 leak-gate 套件 | 还原 | **是** |
| Graphify 过期→call graph 错误 | 索引 mtime < HEAD | 重查 mtime；`graphify update .`（不提交） | 重跑 | 否 |
| docs overclaim | SPA-1/CR-1 在 closure 被标 completed 但证据不足 | closure review + 对照测试 | 修文档 | 否 |
| W1 debt 被误当 blocker | 窗口扩张到修 W1-D1/D5/D6/D7 | scope 对照 §8 | 重新收敛 | 否（重收敛） |

---

## 15. Deferred debt

本窗口结束时登记（不在本窗口处理）：

- **W2-D1**：`_EXTRA_REDACT_PATTERNS` 是否长期保留于 projector vs 收归 owner ——
  本窗口定位 boundary-local，长期归属待 trust-boundary contract 演进时复议。
- **W2-D2**：OD-7 production approval enforcement —— 继续 deferred，待多用户/生产需求。
- **W2-D3**：SPA-2 permission-staging doc-align —— 独立 doc 窗口。
- **W2-D4**：L1 attempt dead-code 移除 —— 独立 cleanup 窗口（与 W1-D4 修复配套）。
- **carry-forward**：W1-D1（route 命名）/ W1-D2（`_render_v0_delegate_result` docstring）/
  W1-D5 / W1-D6 / W1-D7 不变。

---

## 16. Closure criteria

仅当全部满足才宣布 Window 2 关闭：

- SPA-1 single masking owner test-locked（Option B）。
- CR-1 inert 标注 + AST boundary test green。
- W1-D4 fallback dispatch guard green。
- 六态（rejected / policy_blocked / approval / failed / not_supported / success）仍可区分，
  无重复、无回归。
- 无 legacy/rollback 路径删除；Window 1 行为不回归。
- full suite 0 unexpected failures；`git diff --check` clean；touched 文件 `ruff` clean。
- **Roadmap 统一回写**（SPA-1→completed、CR-1→completed、W1-D4 test-guarded）；Window 2
  debt 登记；`WINDOW_2_CLOSURE_AUDIT.zh.md` 写就。
- North Star / Window 1 Plan sha256 不变；docs-only commit 原子；**未 push**。
- 最终 verdict：`ACCEPT_WITH_TRACKED_DEBT — WINDOW 2 CLOSED`。

若出现真实 Blocker/High：不改代码，只输出 `CLOSURE_BLOCKED` + 证据。

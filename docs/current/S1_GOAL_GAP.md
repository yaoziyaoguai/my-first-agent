# S1 Goal Gap / Release Backlog — 按优先级排序的 S1 待办

> 权威文档（docs/current/）。这是 S1 的真实 release backlog / todolist，按 **P0→P4** 优先级排列（不再按 G 编号排列）。基于：`S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md` + `S1_GOAL.md` + 两轮只读代码审计（基线证据见 `_tmp_s1_baseline/`，本轮独立二次审计证据见 `_tmp_s1_priority_audit/`）。
>
> 规则（见 AGENTS.md）：不删未完成 gap；不为「看起来完成」改写 gap；完成需证据；确认 S1 不解决的重要项转入 `TECH_DEBT.md` 并标注 TD-ID。保留原 G-xx ID，避免引用断裂（旧→新映射见 §9）。
>
> Status ∈ {satisfied, partially_satisfied, unknown_needs_audit, s1_blocker, s1_gap, defer_to_tech_debt, out_of_scope}
> Blocking ∈ {release_blocker, must_fix_for_s1, should_fix_for_s1, optional_for_s1, s2_or_later}

---

## 0. Purpose

本文是 S1（Baseline Usable Product / 基本可用产品版）的真实 **release backlog**。它回答两个问题：

1. **S1 还差什么才能发布？** —— 见 P0/P1。
2. **哪些是 S1 内应做、可延后、或明确不做？** —— 见 P2/P3/P4。

S1 不是 demo、不是 MVP 小试、不是纯审计阶段（见 `S_ROADMAP.md §2`、`S1_GOAL.md §0`）。本文以**当前代码现实**为准，不凭空定义能力。

---

## 1. Priority Model

| Priority | 含义 | 典型判据 |
|---|---|---|
| **P0 Release Blocker** | S1 不能发布，必须先解决 | 安全/config 卫生发布风险；缺运行说明导致无法启动；acceptance baseline 缺失无法判定可用；当前权威文档冲突会误导后续 coding agent |
| **P1 Must Fix for S1** | S1 完成前必须解决 | S1 产品承诺必须具备；fake/real same-spine 证据不足；context/state/tool/evidence/task progress 关键路径不踏实；缺 verification |
| **P2 Should Fix for S1** | 重要，建议 S1 内解决；延期需写明理由 | 明显提升质量、不阻塞基本可用、可文档/guardrail 缓解 |
| **P3 Optional for S1** | 锦上添花，不阻塞基本可用 | 可明确不做 |
| **P4 S2 or Later / Debt / Out of Scope** | 不属于 S1 | 完整 MCP/Skill/SubAgent 激活、Scheduler 激活、evidence 全正文持久化、durable ledger 等 → TECH_DEBT 或 out_of_scope |

> 另设 **§8 Satisfied baseline**：S1 要求已满足、无开放动作的既有能力（must-not-regress），不属于任何待办优先级。

---

## 2. Executive Priority Summary

| Priority | IDs | 为何此优先级 | 推荐下一步（授权后） |
|---|---|---|---|
| **P0** | G-15 ✅, G-16 ✅, G-17 ✅, G-19 ✅ | 安全/config 卫生发布风险；用户无法据 README 启动；acceptance baseline 缺失；审计文档与 G-15 权威冲突 | **G-15 已完成（run 4：untrack + gitignore）；G-16 已完成（run 5：README S1 定位 + 当前文档导航）；G-17 已完成（run 10：S1 acceptance baseline 指定；real smoke 执行归 G-03）；G-19 已完成（run 11：审计文档 config/secret 事实与 G-15 调和）**；P0 全部完成 |
| **P1** | G-07b, G-12, G-03 | 大结果 resume 形态未知（AC-5）；最小多步任务（AC-5）；real smoke（AC-3，依赖 G-15） | 复现大结果 resume；钉死 legacy Plan 为 S1 最小多步并验收；写 key-safe real smoke 步骤 |
| **P2** | G-10, G-07 | 指定 S1 最小可观测事件集；L2 umbrella 待收口 | 列「一次 run 必现事件」；G-07b 解后确认 G-07 |
| **P3** | G-18 | 命名治理已由 S 文档收口，残留属代码层（非 S1 范围） | 维持 S 文档唯一权威，不改代码 |
| **P4** | G-13, G-14, G-06(TD-002), G-11(TD-001) | dormant by design / L5 边界已满足激活留 S2 / 已确认 S1 不解决 | 见 `TECH_DEBT.md`，S2+ 重评 |
| **Satisfied** | G-01, G-02, G-04, G-05, G-08, G-09 | S1 要求已满足，无开放动作 | 仅回归保护（must-not-regress） |

状态分布（重排后）：

| Status | 数量 | IDs |
|---|---|---|
| satisfied | 11 | G-01, G-02, G-04, G-05, G-08, G-09, G-14, **G-15 (✅ run 4)**, **G-16 (✅ run 5)**, **G-17 (✅ run 10)**, **G-19 (✅ run 11)** |
| partially_satisfied | 4 | G-03, G-07, G-10, G-12 |
| unknown_needs_audit | 1 | G-07b |
| s1_blocker | 0 | — |
| s1_gap | 1 | G-18 |
| defer_to_tech_debt | 2 | G-06 (TD-002), G-11 (TD-001) |
| out_of_scope | 1 | G-13 |

---

## 3. P0 — Release Blockers

> 推荐执行顺序：G-15 → G-16 → G-17 → G-19。

### G-15 — `config/config.yaml` 被 git 跟踪（config 卫生 / 发布前必须 untrack） — ✅ RESOLVED (2026-06-16 run 4)
- **Priority**: P0（已完成）
- **Layer**: Cross-cutting / Security (config hygiene)
- **S1 requirement**: 安全配置基线——会被填入真实 key 的本地配置文件不应被 git 跟踪；仓库不得提交真实 provider 密钥。
- **Current evidence**（本轮独立核验，掩码，无明文，详见 `_tmp_s1_priority_audit/code_evidence_index.md`）:
  - `git ls-files config/config.yaml` → **被跟踪**；`.gitignore` 忽略 `.env`/`config/config.local.yaml`，**未**忽略 `config/config.yaml`。
  - `git ls-files -v config/config.yaml` → **`S`（skip-worktree 位已设）**。
  - **HEAD 与 INDEX** 的 `api_key` 均为 **13 字符占位符**（结构 `AA-AAAAAAA_AA`）；config.yaml 历史 4 个 commit **从未**出现 ≥30 字符 key（`ever_long_key: no`）→ **真实 key 从未被提交**。
  - **工作树**当前 `api_key` 为 **35 字符真实长度 key**，被 `skip-worktree` 对 git 遮挡（`git status` 看不到）。
  - 模板 `config/config.example.yaml`、`config/config.local.example.yaml` 已存在。
- **Status**: satisfied（2026-06-16 run 4 完成）
- **Gap**: ~~真实 key 在被跟踪路径的工作树里仅靠 `skip-worktree` 遮挡，文件仍被跟踪~~ → **已解决**：`config/config.yaml` 已从 Git 跟踪移除并被 `.gitignore` 忽略；本地文件与真实 key 保留在工作区，不再被 Git 跟踪、不再依赖 skip-worktree。
- **Blocking level**: release_blocker（已满足）
- **Dependencies**: 无。（其完成解除了 G-03 real smoke 的 key-safe 前置——real provider 现可直接读本地 gitignored `config/config.yaml`。）
- **Recommended execution order**: P0-1（已完成）。
- **Needed action**: ~~untrack + gitignore + 保留 example 模板~~ 已执行（见 Completion evidence）。
- **Verification**（2026-06-16 run 4 实跑通过）: `git ls-files config/config.yaml` 为空；`git check-ignore -v config/config.yaml` 命中 `.gitignore:36`；`test -f config/config.yaml` = LOCAL_CONFIG_EXISTS；config.yaml staged diff 仅删除 13 字符占位符（max key len=13，无 35 字符真实 key）；`.env` = ENV_MISSING（未恢复/未创建）。
- **Completion evidence**: 动作 = `git update-index --no-skip-worktree config/config.yaml` → `git rm --cached config/config.yaml`（保留本地文件）+ `.gitignore` 增加 `config/config.yaml`（及 `config/.local.yaml`、`config/.local_backup`）+ 同步更正 `config/config.example.yaml` 过时的 skip-worktree 注释。**用户口径**：`.env` 已过时且已删除，**不**恢复、**不**创建；真实 key 继续保留在本地 gitignored `config/config.yaml` 供 real provider 测试；**未**迁移 / 删除 / 覆盖 / 轮换 key（真实 key 从未进入 git history 或 staged diff，history `ever_long_key: no`，故确认无需轮换）。本轮提交 hash 见 `WORK_LOG.md` / `git log`。
- **Decision**: ✅ satisfied。不再依赖 skip-worktree；仓库仅保留 `config/config.example.yaml`（占位符模板）。G-15 保留原 ID 与完成证据，不删除。审计文档 §0/§10.1「提交了真实密钥」强表述仍由 **G-19** 追踪调和（本轮不动 G-19）；当前权威口径以本 gap + `WORK_LOG.md` 为准。

### G-16 — README / quickstart 可用性 — ✅ RESOLVED (2026-06-16 run 5)
- **Priority**: P0（已完成）
- **Layer**: Cross-cutting / UX
- **S1 requirement**: 使用者可按 README/quickstart 跑起来，文档导航有效（对应 AC-7）。
- **Current evidence**（本轮独立核验）: README:17-44 有 quickstart；但导航链接 `docs/PROJECT_STATUS.md`、`docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md`、`docs/README.zh.md`、`docs/dev/AUTO_RUN_WORKFLOW.md`、`docs/06-audit/README.md` —— **逐一验证全部 MISSING**（已迁入 `docs/history/`，仅 `docs/current` 存在）；README:5/9/46 自述「以 `PROJECT_STATUS.md` 为准 / developer prototype，不是面向普通用户的产品 / safe-local 实验性」，与「基本可用产品版」定位冲突。
- **Status**: satisfied（2026-06-16 run 5 完成）
- **Gap**: ~~用户面运行说明与「基本可用产品版」不一致；5 个文档导航链接全部失效~~ → **已解决**：README 改为 S1 / Baseline Usable Product 收尾定位，并将文档导航指向 `docs/current/` 下存在的当前权威文件。
- **Blocking level**: release_blocker（已满足）
- **Dependencies**: 无。
- **Recommended execution order**: P0-2（已完成）。
- **Needed action**: ~~更新 README 导航指向 `docs/current/`、重述为 S1 基线定位~~ 已执行（见 Completion evidence）。
- **Verification**（2026-06-16 run 5 实跑通过）: README link check 检查 9 个相对 Markdown 链接，全部存在；`rg` 搜索旧失效导航与旧 prototype 表述无命中。
- **Completion evidence**: `README.md` 顶部定位改为 S1 Baseline Usable Product 收尾；当前权威入口改为 `docs/current/S1_GOAL.md` + `docs/current/S1_GOAL_GAP.md`；文档导航改为 `docs/current/{S_ROADMAP,S1_GOAL,S1_GOAL_GAP,S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh,TECH_DEBT,WORK_LOG}.md`；safe-local 与 L5 扩展边界说明保留。
- **Decision**: ✅ satisfied。README/quickstart 已具备当前 S1 入口与有效文档导航；G-16 保留原 ID 与完成证据，不删除。

### G-17 — 测试分层 / 指定 S1 acceptance 集 — ✅ RESOLVED (2026-06-16 run 10)
- **Priority**: P0（已完成）
- **Layer**: Cross-cutting / Tests
- **S1 requirement**: 明确哪些是 S1 acceptance tests（对应 AC-1），哪些只是 seam/harness/demo；记录 AC-2 真实侧 smoke 的位置、命令、前置条件和安全边界，并把真实执行交由 G-03 Verification 承接。
- **Current evidence**（本轮独立核验）: acceptance 候选**齐备且存在**——`tests/golden_e2e/{test_golden_simple_conversation,test_golden_tool_success,test_golden_memory_checkpoint,test_golden_policy_evidence,test_golden_skill_l3_core_loop,test_golden_skill_system,test_golden_subagent_delegation}.py`（全链路 + FakeProvider）、`tests/runtime_integration/{test_phase1_real_core_loop,test_mcp_l3_real_core_loop}.py`、`tests/smoke/test_first_usable_task_e2e.py`；seam/harness `test_b7_*`、`test_architecture_boundaries.py`、直接 `dispatcher.route` 测试。
- **Status**: satisfied（2026-06-16 run 10 完成）
- **Gap**: ~~候选齐备，但尚未「指定」S1 acceptance 子集与 same-spine 对照验收~~ → **已解决**：`docs/current/S1_ACCEPTANCE_BASELINE.md` 指定 S1 fake/local acceptance release gate，并明确 real provider smoke 不属于 G-17 直接执行项，而是 G-03 Verification。
- **Blocking level**: release_blocker（已满足）
- **Dependencies**: 与 G-04（source-level same-spine 已满足）相关；真实 provider 运行层 smoke 证据由 G-03 承接。
- **Recommended execution order**: P0-3（已完成）。
- **Needed action**: ~~在 S1 收尾前指定 acceptance 测试集 + AC-2 same-spine 对照口径（文档动作）~~ 已执行；G-17 scope 调整为 acceptance baseline 定义，不消费真实 provider key。
- **S1 acceptance baseline**:
  - Required fake/local release gate:
    - `.venv/bin/python -m pytest tests/golden_e2e -q`
    - `.venv/bin/python -m pytest tests/smoke/test_first_usable_task_e2e.py -q`
    - `.venv/bin/python -m pytest tests/runtime_integration/test_phase1_real_core_loop.py::TestCoreChatWiring::test_core_chat_actually_invokes_runtime_action_dispatcher_from_turn_end_hook -q`
  - Real provider smoke location and command are recorded in `docs/current/S1_ACCEPTANCE_BASELINE.md` and G-03; the command remains gated by explicit opt-in and is **not** run by G-17.
- **Verification**（2026-06-16 run 10 实跑通过）: `tests/golden_e2e` → `15 passed`；`tests/smoke/test_first_usable_task_e2e.py` → `6 passed`；targeted runtime integration wiring test → `1 passed`；`S1_GOAL_GAP.md` + `S1_ACCEPTANCE_BASELINE.md` 明确列出 acceptance baseline 与 G-03 handoff；`git diff --check` 通过。未运行真实 provider，未读取/打印/移动/复制 secret，未修改 `config/config.yaml`，未创建 `.env`。
- **Decision**: ✅ satisfied。S1 acceptance baseline 已指定；G-17 不再直接要求 real execution。AC-2 的真实侧运行证据仍是 G-03 Verification，不在本 gap 内消费真实 provider key。

### G-19 — 调和审计文档与 G-15 的密钥权威冲突（本轮新增） — ✅ RESOLVED (2026-06-16 run 11)
- **Priority**: P0（已完成）
- **Layer**: Cross-cutting / Governance (docs coherence)
- **S1 requirement**: 当前权威文档之间不得就同一安全事实给出互相矛盾的结论，以免误导后续 coding agent。
- **Current evidence**（本轮独立核验）: `S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md §0`（约 L19）「仓库中提交了真实 provider 密钥」、`§10.1`（约 L201）「提交了真实密钥 … 当前最高优先风险」，与 G-15 + 本轮核验结论（HEAD/INDEX/历史均占位符，真实 key 从未被提交）**直接矛盾**。`WORK_LOG.md`（run 2）已把该调和列为 next step。
- **Status**: satisfied（2026-06-16 run 11 完成）
- **Gap**: ~~仅读审计文档的后续 agent 会误判「真实密钥已被提交、需轮换/告警」，做出错误动作~~ → **已解决**：审计文档 §0、§7 config 表格、§10.1、§11 real smoke 前置均已与 G-15 口径调和。
- **Blocking level**: release_blocker（已满足）
- **Dependencies**: G-15（措辞应在 G-15 落定后定稿）。
- **Recommended execution order**: P0-4（已完成）。
- **Needed action**: ~~更新 `S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md §0/§10.1`，将「提交了真实密钥/需轮换」改为「tracked `config/config.yaml` 为占位符；真实 key 在 skip-worktree 工作树/`.env`，发布前需 untrack」~~ 已执行，并同步同一审计事实在 §7/§11 的引用；当前口径为：Git history / HEAD / index 仅有占位符，真实 provider key 从未提交；G-15 已 untrack + gitignore，本地真实 config 留在 ignored runtime config；后续 real smoke 仍需 key-safe 授权。
- **Verification**（2026-06-16 run 11 实跑通过）: `rg -n "提交了真实密钥|已提交真实密钥|需轮换|密钥暴露|含真实密钥且被跟踪" docs/current/S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md` 无命中；`rg -n "真实 provider key 从未提交|G-15 已将|untrack|gitignore|key-safe" docs/current/S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md` 命中调和口径；`git diff --check` 通过。
- **Decision**: ✅ satisfied。当前权威文档不再就 G-15 config/secret 事实互相冲突。

---

## 4. P1 — Must Fix for S1

> 推荐执行顺序：G-07b → G-12 → G-03。

### G-07b — Checkpoint 大结果 resume 形态
- **Priority**: P1
- **Layer**: L2
- **S1 requirement**: checkpoint/resume 不破坏后续模型调用（支撑 AC-5）。
- **Current evidence**: `agent/evidence_persistence.py:34 MAX_TOOL_RESULT_BYTES=2048`、`:90 summarize_content_for_persistence`、`:108/:133 content_persisted=false`；`tests/test_checkpoint_roundtrip.py`/`test_evidence_storage_hygiene.py` 提及 2048/large，但**本轮只读未确证** resume 后形态被下一轮模型调用接受。
- **Status**: unknown_needs_audit
- **Gap**: 大 tool_result 摘要（content_persisted=false）后，resume 的消息形态是否被 API 接受未知。
- **Blocking level**: must_fix_for_s1
- **Dependencies**: 无（其结论支撑 G-12 的 resume 验收）。
- **Recommended execution order**: P1-1（先审计/复现）。
- **Needed action**: 只读 + 一次本地复现验证（未来授权 run）：构造 >2048B tool_result → save → resume → 下一轮模型调用。
- **Verification**: 上述复现不报错。
- **Decision**: 先审计再判定 satisfied / 转 TD；本轮维持 unknown，不臆断。

### G-12 — 最小多步任务状态 / progress tracking
- **Priority**: P1
- **Layer**: L4
- **S1 requirement**: 存在最小多步任务状态与进度跟踪，可 checkpoint（对应 AC-5、§3.6 must-have）。
- **Current evidence**: legacy Plan 路径 active——`state.py:192 TaskState`（current_plan/current_step_index/status）、`state.py:13 KNOWN_TASK_STATUSES`；`agent/tools/meta.py:45 mark_step_complete` + `config.py:208 STEP_COMPLETION_THRESHOLD=80`；`task_runtime.py:48 is_current_step_completed`；`transitions.py:639 advance_current_step_if_needed`；checkpoint 持久化全量 task state（`checkpoint.py:324`）。ActionPlan/Scheduler 路径 dormant（见 G-13）。
- **Status**: partially_satisfied
- **Gap**: 进度=checkpoint 快照，无独立 durable task ledger；ActionPlan 路径未接入。
- **Blocking level**: must_fix_for_s1
- **Dependencies**: G-07b（resume 形态结论）。
- **Recommended execution order**: P1-2。
- **Needed action**: 明确「legacy Plan 路径 = S1 的最小多步任务状态」并完成 AC-5 验收；独立 durable ledger 留 S2+（s2_or_later）。
- **Verification**: 一个 ≥2 步任务能 plan→advance→done 并 resume（AC-5）。
- **Decision**: legacy Plan 路径作为 S1 最小能力；durable ledger=s2_or_later。

### G-03 — Real provider smoke
- **Priority**: P1
- **Layer**: L1
- **S1 requirement**: RealProvider 可作为真实 smoke 路径（对应 AC-3，并为 AC-2 提供真实侧证据）。
- **Current evidence**: real adapters `agent/provider/{anthropic_http,anthropic_native,openai_http,openai_native}.py`，由同一工厂构造；`tests/test_provider_real_smoke.py`、`tests/test_real_mcp_flight.py`（需 key/网络）。
- **Status**: partially_satisfied
- **Gap**: 缺一个 **key-safe** 的真实 smoke 步骤文档。
- **Blocking level**: must_fix_for_s1
- **Dependencies**: **G-15**（已完成：本地真实 runtime config 已在 gitignored 路径，不再被 Git 跟踪）；**G-17**（已完成：acceptance baseline 与 G-03 handoff 已指定）。
- **Recommended execution order**: P1-3（G-15 之后）。
- **Needed action**: 在用户单独授权后，按 `docs/current/S1_ACCEPTANCE_BASELINE.md` 的 G-03 handoff 执行 key-safe real smoke；不得读取/打印/移动/复制 secret，不得提交 ignored runtime config。
- **Verification**: 一次 real run 产出 `sessions/<id>/events.jsonl` 且 `provider_type` 为真实类型；再与 G-17 fake/local baseline 的事件骨架对照，证明运行路径同脊柱，差异仅限 provider 真实侧输出和 `provider_type`。
- **Decision**: 留 S1 gap；G-15/G-17 前置均已解除，真实执行仍需后续明确授权。

---

## 5. P2 — Should Fix for S1

> 推荐执行顺序：G-10 → G-07。

### G-10 — Evidence 支撑 S1 可观测性（指定最小事件集）
- **Priority**: P2
- **Layer**: L3
- **S1 requirement**: evidence 能证明一次 run 的路径骨架。
- **Current evidence**: `logger.py:150`→`agent_log.jsonl`；`event_log.py:153`→`sessions/<id>/events.jsonl`；`evidence_recorder.py:728 record_evidence`（含 provider_type、tool gate/invoke/result、memory、checkpoint 事件）。
- **Status**: partially_satisfied
- **Gap**: 路径骨架可证；尚未「指定」S1 可观测最小集（哪些事件必须出现）。
- **Blocking level**: should_fix_for_s1
- **Dependencies**: 与 G-17 验收口径相关。
- **Recommended execution order**: P2-1。
- **Needed action**: 指定 S1 可观测最小集（文档动作）。
- **Verification**: 一次 run 的 events.jsonl 含 provider_type + tool 事件 + checkpoint。
- **Decision**: 最小可观测已具备；正文保真见 G-11（TD-001，P4）。

### G-07 — Context/Memory/State/Checkpoint 基本可用（L2 umbrella）
- **Priority**: P2
- **Layer**: L2
- **S1 requirement**: 上下文/memory/state/checkpoint 达 S1 基本可用。
- **Current evidence**: recall `core.py:1065`、retain `core.py:961`、turn-end `loop.py:285-435`；压缩配对安全 `agent/memory.py:220/261-263`；state `state.py:13/192`；checkpoint save `core.py:1005/1322/1641/1707`、resume `session.py:405`（`main.py:731` 无条件）。
- **Status**: partially_satisfied
- **Gap**: 核心路径可用；开放子项 = (a) 大结果 resume 形态 → **G-07b（P1）**；(b) 并存的 `agent/context.py:36` compress_history 无配对守卫（非主路径）→ **TD-003（P4）**。
- **Blocking level**: should_fix_for_s1
- **Dependencies**: G-07b。
- **Recommended execution order**: P2-2（G-07b 解后收口）。
- **Needed action**: G-07b 验证通过后，确认 L2 umbrella satisfied；(b) 维持 TD-003。
- **Verification**: 同 G-07b verification。
- **Decision**: 主体可用；子项已拆分至 G-07b / TD-003，避免重复计 urgency。

---

## 6. P3 — Optional for S1

### G-18 — S 与旧 v1/v2/v3 命名区隔
- **Priority**: P3
- **Layer**: Cross-cutting / Governance
- **S1 requirement**: 避免旧 v1/v2/v3 命名误导 S 系列目标。
- **Current evidence**: 代码含 `v0.x`/`Phase N`/`Loop N`/`B7` 等命名；`S_ROADMAP.md §1` 与 `S1_GOAL.md §8` 已显式声明 S≠代码 v。
- **Status**: s1_gap
- **Gap**: 命名混淆风险已由冻结 S 文档收口；残留仅代码层 v 标签（改名非 S1 范围）。
- **Blocking level**: optional_for_s1
- **Dependencies**: 无。
- **Recommended execution order**: P3-1（可明确不做）。
- **Needed action**: 维持 S 文档对版本语义的唯一权威；不在代码层做改名（非本轮、非 S1 必需）。
- **Verification**: 后续文档不再用代码 v 标签当 S 目标。
- **Decision**: 由上一轮 should_fix_for_s1 **降级** optional——S1 可动作部分（文档收口）已完成，残留属代码层非 S1 范围；非「为完整而降级」。

---

## 7. P4 — S2 or Later / Tech Debt / Out of Scope

### G-13 — Scheduler 当前 dormant
- **Priority**: P4
- **Layer**: L5
- **S1 requirement**: S1 不接入 Scheduler。
- **Current evidence**（本轮独立核验）: `agent/action_scheduler.py` 文件级 dormant；`agent/loop.py:728` 默认 None / `loop.py:1007-1028` 注入 seam；**`main.py` 对 scheduler 0 引用**（`grep -nc` = 0）；`tests/test_scheduler_boundary_l2.py` 钉死 main.py 0 引用。
- **Status**: out_of_scope
- **Gap**: 无（S1 by design 不接入，也不删除）。
- **Blocking level**: s2_or_later
- **Dependencies**: 无。
- **Recommended execution order**: —（不做）。
- **Needed action**: 保持 dormant；不接入、不删除。
- **Verification**: `tests/test_scheduler_boundary_l2.py` 通过。
- **Decision**: S1 范围外；维持现状。

### G-14 — MCP / Skill / SubAgent 边界
- **Priority**: P4（S1 边界要求已满足；仅激活留 S2）
- **Layer**: L5
- **S1 requirement**: 扩展能力边界清楚（active/configurable/dormant/demo-only 明确）——**这是 S1 的要求，已满足**。
- **Current evidence**: MCP configurable 默认关（`main.py:587-589 MY_FIRST_AGENT_MCP_ENABLE`，dry-run 默认开）；SubAgent V0 configurable 默认关（`subagent_routing_flag.py:29`），默认 local_fake stub（`subagent_system/executor.py:12/26`），L0 注册/L1-L2 frozen（`phase1_hook.py:170-187`），V0 wiring 源码注明未完成；Skill 实验性（`skill_system/` + `runtime_integration/skill_lifecycle.py`，README:46）。
- **Status**: satisfied（S1 边界要求）
- **Gap**: 边界清楚（满足 S1）；全量生产激活非 S1 目标。
- **Blocking level**: s2_or_later（激活）
- **Dependencies**: 无。
- **Recommended execution order**: —（激活留 S2+）。
- **Needed action**: S1 仅确认并固定边界（已满足）；不推进实现。
- **Verification**: 默认 run 不启用 MCP / 不真实委派（local_fake）。
- **Decision**: S1 边界 satisfied；激活=s2_or_later。归 P4 仅因唯一开放工作（激活）属 S2。

### G-06 — Planning/compress legacy client facade（→ TD-002）
- **Priority**: P4
- **Layer**: L1
- **S1 requirement**: planning/compress 仍回到同一 provider，不另起一条模型路径。
- **Current evidence**: `agent/core.py:171 build_default_model_client()` 返回 (provider, ProviderBackedClient)；`core.py:1369 loop_ctx.client.messages.create`；`legacy_adapter.py:29-63` 转发到同一 `provider.create()`。
- **Status**: defer_to_tech_debt（TD-002）。Moved to `TECH_DEBT.md`: TD-002. Reason: 同 provider，S1 可接受。
- **Gap**: planning/compress 仍是 legacy `client.messages.create` 形态，未迁移到 provider-neutral `create()`（虽指向同一 provider）。
- **Blocking level**: s2_or_later
- **Dependencies**: 无。
- **Recommended execution order**: —（延期）。
- **Needed action**: 迁移到 provider-neutral 接口（延期，见 TD-002）。
- **Verification**: planner/compress 不再 import legacy_adapter。
- **Decision**: 同 provider，S1 可接受；记 TD-002。

### G-11 — Evidence 不持久化模型 request/response 正文（→ TD-001）
- **Priority**: P4
- **Layer**: L3
- **S1 requirement**: 判定「不存正文」属 blocker / gap / debt。
- **Current evidence**: `evidence_recorder.py` 仅 safe_summary + result_size，`content_persisted=false`。
- **Status**: defer_to_tech_debt（TD-001）。Moved to `TECH_DEBT.md`: TD-001. Reason: S1 用骨架级可观测足够。
- **Gap**: 无法从 evidence 逐字节复原模型交互。
- **Blocking level**: s2_or_later
- **Dependencies**: 无。
- **Recommended execution order**: —（延期）。
- **Needed action**: full-fidelity capture 留 S2+（TD-001）。
- **Verification**: n/a（S1 用骨架级可观测）。
- **Decision**: 非 S1 blocker；最小可观测足够，记 TD-001。

---

## 8. Satisfied S1 Baseline（无开放动作 / must-not-regress）

> 这些 gap 的 S1 要求**已满足**，不属于任何待办优先级；保留以防引用断裂并作回归保护。

### G-01 — 可运行入口
- **Priority**: Satisfied baseline
- **Layer**: L1 · **Status**: satisfied · **Blocking**: must_fix_for_s1（已满足）
- **Current evidence**: `main.py:637 main()` → `main.py:335 main_loop()` → `main.py:195 _run_chat_for_backend()` → `agent/core.py:763 chat()` → `agent/loop.py run_main_loop`（本轮 graphify 复核一致）。
- **Verification**: `.venv/bin/python main.py --plain` 可启动。
- **Decision**: S1 基线既有能力，must-not-regress。

### G-02 — Fake provider 稳定回归
- **Priority**: Satisfied baseline
- **Layer**: L1 · **Status**: satisfied · **Blocking**: must_fix_for_s1（已满足）
- **Current evidence**: `agent/provider/fake_provider.py:306 FakeProvider`；`tests/golden_e2e/*` 用 `FakeProvider()` 跑全链路；`pytest.ini testpaths=tests`。
- **Verification**: `.venv/bin/python -m pytest tests/golden_e2e -q` 通过。
- **Decision**: AC-1 候选；acceptance「指定」见 G-17（P0）。

### G-04 — Fake/Real same spine（核心不可回退原则）
- **Priority**: Satisfied baseline
- **Layer**: L1 · **Status**: satisfied · **Blocking**: release_blocker（已满足；若回退即 P0）
- **Current evidence**（本轮独立核验）: `protocol.py:78` 薄协议；`factory.py:44-45`「FakeProvider/RealProvider 共享同一 core.chat/loop.py 路径，不是双 runtime」；`factory.py:~89` 默认 fake；`loop.py:249/690`「loop 不读 provider_type」；`core.py:1158-1159` RT-01「fake/real 共享同一 evidence path」；`legacy_adapter.py:29-63` 转发同一 provider。
- **Verification**: AC-2 运行层对照在 G-17 完成。
- **Decision**: S1 核心不可回退原则；运行层对照证据归 G-17。

### G-05 — Provider factory/protocol 边界薄
- **Priority**: Satisfied baseline
- **Layer**: L1 · **Status**: satisfied · **Blocking**: should_fix_for_s1（已满足）
- **Current evidence**: `protocol.py:78` 仅 `create/stream` + 三个能力位；`factory.py:18` 单一分派工厂。
- **Verification**: `tests/test_provider_contract.py`。
- **Decision**: 保留。

### G-08 — Tool/Policy/Dispatcher/Mediator 基本可用
- **Priority**: Satisfied baseline
- **Layer**: L3 · **Status**: satisfied · **Blocking**: must_fix_for_s1（已满足）
- **Current evidence**: `tool_registry.py:43/142/205/399`；`tool_runtime_mediator.py:225 mediate`；`tool_executor.py:204`；`runtime_integration/tool_gate.py:32`（两 provider 模式一致）；`TOOL_INVOKE` 仅记 evidence、执行在 executor。
- **Verification**: `tests/runtime_integration/test_tool_pipeline_l3_completion.py`。
- **Decision**: S1 基线既有能力。无顶层统一 policy 开关（逻辑分散，功能在）属可接受现状。

### G-09 — Tool result 进入 context/state
- **Priority**: Satisfied baseline
- **Layer**: L3 · **Status**: satisfied · **Blocking**: should_fix_for_s1（已满足）
- **Current evidence**: `agent/conversation_events.py:116 append_tool_result`（role=user, tool_result block, 全量 content），`tool_executor.py:546/680` 无条件追加；`state.task.tool_execution_log` 留副本；压缩配对守卫 `memory.py:220`。
- **Gap**: 进入 context/state 稳健（S1 要求已满足）；evidence 侧 pending-tool 的 `events.jsonl tool_output=""`（mediator `_route_result:1263`）属日志保真 → **TD-004（P4）**。
- **Verification**: 工具执行后 `state.conversation.messages` 含对应 tool_result block。
- **Decision**: context/state satisfied（枚举由旧非法值 `satisfied（context/state 路径）…` 规范为 `satisfied`）；日志保真记 TD-004。

---

## 9. Original ID Index（旧 G-xx → 新优先级段，防引用断裂）

| ID | 旧位置（按编号） | 新位置 | Status | Blocking | 变动 |
|---|---|---|---|---|---|
| G-01 | 入口 | §8 Satisfied | satisfied | must_fix_for_s1 | 不变 |
| G-02 | fake 回归 | §8 Satisfied | satisfied | must_fix_for_s1 | 不变 |
| G-03 | real smoke | §4 P1 | partially_satisfied | must_fix_for_s1 | should_fix→must_fix（AC-3） |
| G-04 | same-spine | §8 Satisfied | satisfied | release_blocker | 不变（已满足） |
| G-05 | provider 边界 | §8 Satisfied | satisfied | should_fix_for_s1 | 不变 |
| G-06 | legacy facade | §7 P4 | defer_to_tech_debt(TD-002) | s2_or_later | 不变（已 TD） |
| G-07 | L2 umbrella | §5 P2 | partially_satisfied | should_fix_for_s1 | 子项拆 G-07b/TD-003 |
| G-07b | 大结果 resume | §4 P1 | unknown_needs_audit | must_fix_for_s1 | should_fix→must_fix |
| G-08 | tool/policy | §8 Satisfied | satisfied | must_fix_for_s1 | 不变 |
| G-09 | tool result→ctx/state | §8 Satisfied | satisfied | should_fix_for_s1 | 枚举规范化 |
| G-10 | evidence 可观测 | §5 P2 | partially_satisfied | should_fix_for_s1 | 不变 |
| G-11 | evidence 正文 | §7 P4 | defer_to_tech_debt(TD-001) | s2_or_later | 不变（已 TD） |
| G-12 | 多步任务 | §4 P1 | partially_satisfied | must_fix_for_s1 | should_fix→must_fix（AC-5） |
| G-13 | scheduler | §7 P4 | out_of_scope | s2_or_later | 不变 |
| G-14 | MCP/Skill/SubAgent | §7 P4 | satisfied(边界) | s2_or_later(激活) | 边界标 satisfied |
| G-15 | config.yaml | §3 P0 | satisfied (✅ run 4) | release_blocker | **已完成**：untrack + gitignore；真实 key 留本地 ignored 文件 |
| G-16 | README | §3 P0 | satisfied (✅ run 5) | release_blocker | **已完成**：README S1 定位 + 当前文档导航 |
| G-17 | acceptance | §3 P0 | satisfied (✅ run 10) | release_blocker | **已完成**：S1 acceptance baseline 指定；real provider smoke 执行归 G-03 |
| G-18 | S vs v 命名 | §6 P3 | s1_gap | optional_for_s1 | should_fix→optional |
| G-19 | 审计文档冲突 | §3 P0 | satisfied (✅ run 11) | release_blocker | **已完成**：审计文档 config/secret 事实与 G-15 调和 |

> 说明：无 gap 被删除或合并；G-19 为新增（非重命名）。S1 必修（P0+P1）：~~G-15~~（✅ run 4 完成）、~~G-16~~（✅ run 5 完成）、~~G-17~~（✅ run 10 完成）、~~G-19~~（✅ run 11 完成）、G-07b、G-12、G-03。G-15 已于 run 4 完成（`git rm --cached config/config.yaml` + `.gitignore` 忽略；本地真实 key 保留在 ignored 的 `config/config.yaml`，未迁移/删除/轮换）；G-16 已于 run 5 完成（README S1 定位 + 当前文档导航）；G-17 已于 run 10 完成（S1 acceptance baseline 指定；real provider smoke 执行归 G-03）；G-19 已于 run 11 完成（审计文档 config/secret 事实与 G-15 调和）；其余 P1 项仍待后续授权 run 按优先级执行。

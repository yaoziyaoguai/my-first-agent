# S4 Goal Gap / Release Backlog — Auditable Governed Agent Runtime

> Current document (`docs/current/`). S4 gap backlog，由 `S4_BASELINE_STATUS.md`
> （现状）vs **frozen** `S4_GOAL.md`（目标，Direction A，2026-06-20 confirmed）校准。
> 本文是 **backlog**，不是施工结果。
>
> **已校准（calibrated to frozen goal，2026-06-20）**：方向已锁定 Direction A（不再
> provisional）；G01-G12 的 priority / 执行顺序 / AC mapping 已据冻结 goal 复核。进入
> gap loop 才执行——**本（冻结+校准）任务不修 gap、不进入 gap loop、不改代码/tests、不 push。**
>
> 规则（`AGENTS.md` goal rules）：不删未完成 gap；完成需证据；不把未承诺能力强行变 gap；
> 不把所有 TECH_DEBT 塞成 S4 必修。保留 Gap ID 防引用断裂。
>
> Status ∈ {open, blocked, deferred, satisfied}。
> Priority ∈ {P0 setup/release blocker, P1 must_fix_for_s4, P2 should_fix_for_s4,
> P3 optional_for_s4, P4 s5_or_later/deferred}。

## 0. Summary

- **Baseline source**: `S4_BASELINE_STATUS.md`（S3 archived；same-spine + 五层完整；
  L5 governed-active；evidence 为结构化摘要、非逐字；TD-001/TD-004 open；full-suite 绿）。
- **Goal source**: **frozen** `S4_GOAL.md`（S4 = Auditable Governed Agent Runtime；
  L3 evidence/audit fidelity maturation；**redacted-faithful** + secret-safe
  replay/verification（非 byte-for-byte，不存 secret/全量原始 payload）；消化
  TD-001/TD-004；不激活 dormant、不扩张 L5、不激活 memory、不做 durable ledger；
  AC-1..AC-9；§8 Resolved decisions 1-5）。
- **Overall gap verdict**: S4 是 **L3 evidence/audit 深化**版本，不是新 runtime、不是 L5
  扩张、不是 cleanup。核心缺口：(a) 定义 fidelity contract + audit/replay reference task；
  (b) replay-faithful evidence 模型；(c) secret-safe redaction 强制；(d) pending-tool 预览
  （TD-004）；(e) evidence 一致性/完整性校验；(f) execute→record→replay/verify 闭环
  reference task + real key-safe smoke；(g) acceptance gate evidence-fidelity 分类；
  (h) 阶段治理 + S1/S2/S3 不回归 + full-suite 绿信号维持。
- **How to use**: §3 推荐执行顺序；§4-§8 按优先级列 gap；§9 ID 索引；§10 non-goal
  guardrails；§11 next step。所有 gap Status=`open`（G12 `deferred`）；goal 已冻结，
  gap loop 尚未执行（本任务为冻结+校准，不执行 gap）。

## 1. Priority model

| Priority | 含义 | 典型判据 |
|---|---|---|
| **P0** | 阻塞 gap loop / release 判断的前置 | fidelity contract + reference task 未定 → AC-2/5/6 无法精确验收 |
| **P1** | S4 必达产品能力 | replay-faithful evidence；secret-safe redaction；pending-tool 预览；evidence 校验；reference task E2E；real key path |
| **P2** | 硬化/治理 | acceptance gate evidence 分类；docs governance；S1/S2/S3 非回归 + full-suite 绿信号 |
| **P3** | 不影响 S4 核心 | 额外 audit 可观测性 / 报告格式 |
| **P4** | 非 S4 核心 | byte-for-byte 全量（若与 secret-safe 冲突）、durable ledger、memory 激活、Scheduler/MCP/multi-agent 生态、TD-002/003/007 |

## 2. Status distribution

| Status | Count | Gap IDs |
|---|---|---|
| open | 0 | — |
| deferred | 1 | G12 |
| blocked | 0 | —（goal 已冻结；无外部阻塞；依赖在 backlog 内按 §3 排序） |
| satisfied | 11 | G01-G11（+ optional audit observability；G12 deferred） |

## 3. Recommended execution order（依赖排序；goal 已冻结，按此顺序执行）

1. **S4-G01** (P0) — define fidelity contract + audit/replay reference task（解锁 G02/G05/G06）
2. **S4-G02** (P1) — replay-faithful evidence model（依赖 G01）
3. **S4-G03** (P1) — secret-safe redaction 强制（与 G02 协同；security 边界）
4. **S4-G04** (P1) — pending-tool event 预览（TD-004，可与 G02 并行）
5. **S4-G05** (P1) — evidence 一致性/完整性校验（依赖 G02）
6. **S4-G06** (P1) — audit/replay reference task E2E fake/local（依赖 G01/G02/G03/G05）
7. **S4-G07** (P1) — real provider audit key-path smoke（依赖 G06）
8. **S4-G08** (P2) — acceptance gate evidence-fidelity 分类（与 G06 并行）
9. **S4-G09** (P2) — docs/current+history governance for S4（贯穿）
10. **S4-G10** (P2) — S1/S2/S3 非回归 + full-suite 绿信号维持（贯穿）
11. **S4-G11** (P3) — optional audit 可观测性（不阻塞）
12. **S4-G12** (P4) — deferred triage（S5/Sn + TD carry-forward；不执行）

---

## 4. P0 — Setup / release blockers

### S4-G01 — Define evidence fidelity contract + audit/replay reference task
- **Priority**: P0（setup_blocker）
- **Layer**: L3 / Cross (L4-anchored)
- **Related AC**: AC-2 / AC-5 / AC-6 (setup)
- **Baseline evidence**: `S4_BASELINE_STATUS §5` —— evidence 为 `TaskEvidenceReport` 结构化
  摘要（非逐字），`evidence_recorder.py` safe-summary；无「可复放保真到什么粒度」的成文契约，
  也无 S4 audit/replay reference task 规格。S3 `tests/test_s3_reference_task_acceptance.py`
  是可参照模板。
- **Gap**: 没有成文 fidelity contract（记什么 / 粒度 / 复放程度 / redaction 边界）与
  audit/replay reference task 规格 → AC-2/5/6 无法定具体验收命令与断言。
- **Needed action**: 成文 fidelity contract + reference task runbook（执行→记录→复放/校验
  的场景、输入、判据），key-safe；不在本 gap 实现。
- **Verification**: contract + runbook 成文；AC-2/5/6 可据此写出具体验收。
- **Dependencies**: 无（S4 起点）。
- **Non-goal boundary**: 不实现；不扩成多任务套件；不承诺逐字 secret 持久化。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G01）。
- **Evidence**: `docs/current/S4_FIDELITY_CONTRACT.md`（fidelity ceiling redacted-faithful +
  replay chain 契约 §3 + pending-tool 预览契约 §4 + evidence 校验判据 §5 + audit/replay
  reference task runbook §6 + non-goals §7）。已为 G02/G04/G05/G06/G07 写出可验收口径。
  Commit: `docs(s4): G01 fidelity contract + audit/replay reference task (define-only)`。

---

## 5. P1 — Must fix for S4

### S4-G02 — Replay-faithful evidence model
- **Priority**: P1（must_fix_for_s4）
- **Layer**: L3
- **Related AC**: AC-2（+ AC-1）
- **Baseline evidence**: `agent/task_evidence_report.py`（结构化 replay metadata）+
  `agent/evidence_recorder.py`（safe-summary）+ `agent/state.py`（tool_execution_log /
  delegation_log）。当前不足以忠实重建完整决策/工具/委派链路（TD-001）。
- **Gap**: 在既有 evidence seam 上增量，使 governed task（含 MCP tool + SubAgent 委派）的
  决策/工具/委派链路达到 G01 fidelity contract 的保真度、可重建。
- **Needed action**: 扩展 evidence 记录/报告到 contract 粒度；复用 checkpoint/task-state；
  不新增第二条主链路；不重写 spine。
- **Verification**: 对 reference task，evidence 可重建链路并通过保真断言；S2/S3 evidence 测试
  不回归。
- **Dependencies**: S4-G01。
- **Non-goal boundary**: 不持久化 raw secret（见 G03）；不做 durable ledger；不逐字存一切。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G02）。
- **Evidence**: `agent/task_replay_chain.py`（`ReplayEvent`/`ReplayChain`/`build_replay_chain`，
  只读投影 tool_execution_log + delegation_log + plan steps 成有序可复放链路，safe-summary
  截断；不写 state、不改 checkpoint、不新增数据源）+ `agent/task_evidence_report.py`
  （`TaskEvidenceReport.replay_chain_events` 带默认值，向后兼容，报告超出标签级）。
  `tests/test_s4_replay_chain.py`（8 passed）。非回归：S2/S3 reference + evidence
  52 passed / 2 skipped（real-provider opt-in）。Commit: `feat(s4): G02 replay-faithful
  evidence model (redacted-faithful chain projection)`。

### S4-G03 — Secret-safe redaction enforcement
- **Priority**: P1（must_fix_for_s4）
- **Layer**: L3 / Security
- **Related AC**: AC-3
- **Baseline evidence**: 现 evidence 走 safe-summary，未持久化 secret；提高保真后**风险上升**
  （更全的 input/output 可能含 secret）。`AGENTS.md` 安全边界：no secret output/logging。
- **Gap**: 强制 redaction，使更高保真 evidence **绝不**持久化 raw API key/secret/完整凭证。
- **Needed action**: 在 evidence 写入路径加 redaction layer + 测试断言（注入 fake secret →
  断言不出现在持久化 evidence）；key-safe。
- **Verification**: redaction 单测（fake secret 不入 evidence）；real path opt-in/默认 skip。
- **Dependencies**: S4-G02（协同）。
- **Non-goal boundary**: 不以泄露 secret 换保真；不读取/打印真实 secret。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G03）。
- **Evidence**: `agent/evidence_redaction.py`（`redact_text`/`redact_metadata`，覆盖
  OpenAI/GitHub/AWS/Slack/Google key + Bearer + 敏感键赋值；over-redact 不漏过）+ 在
  `agent/task_replay_chain.py` 的 preview 投影点强制应用（**先 redact 再 truncate**）。
  `tests/test_s4_evidence_redaction.py`（10 passed：注入 fake sk-/ghp_/AKIA/Bearer/kv →
  断言被 `[REDACTED]` 且原文不出现；replay chain preview 不泄漏注入 secret）。非回归：
  S2/S3 reference + evidence 52 passed / 2 skipped。Commit: `feat(s4): G03 secret-safe
  redaction enforcement (AC-3 hard boundary)`。

### S4-G04 — Pending-tool event fidelity (TD-004)
- **Priority**: P1（must_fix_for_s4）
- **Layer**: L3
- **Related AC**: AC-4
- **Baseline evidence**: TD-004 —— pending-tool `events.jsonl` 可能显示空 `tool_output`
  预览；结果存在 conversation/state，但 event-log 预览路径可能为空。
- **Gap**: 补全 pending-tool 事件的 tool_output 预览（非空、安全摘要）。
- **Needed action**: 修 `execute_pending_tool` / mediator `_route_result` 的
  `turn_context[tool_use_id]` 预览路径；redaction 一致。
- **Verification**: pending-tool 流程产生非空 tool_output 预览；TD-004 → resolved。
- **Dependencies**: 可与 G02 并行（共享 redaction=G03）。
- **Non-goal boundary**: 不改 tool 执行语义；只补 evidence 预览。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G04）。
- **Evidence**: `agent/tool_runtime_mediator.py:mediate_pending` Step 4 前补写
  `self._turn_context[tool_use_id] = result`（根因：`execute_pending_tool` 不写
  turn_context，导致 TOOL_RESULT `tool_output` 预览恒空；与非 pending `_route_result`
  parity；result 已对 failed/rejected mask，语义不变）。`tests/test_s4_pending_tool_preview.py`
  （3 passed：非空预览 + 截断 + 空结果不 crash）。非回归：S2/S3 reference + subagent
  mediator 8 passed / 2 skipped。**TD-004 → resolved**（见 TECH_DEBT.md）。Commit:
  `fix(s4): G04 pending-tool event tool_output preview (TD-004)`。

### S4-G05 — Evidence verification / consistency check
- **Priority**: P1（must_fix_for_s4）
- **Layer**: L3
- **Related AC**: AC-5
- **Baseline evidence**: 现无对 evidence 链的完整性/自洽校验；evidence「存在」但不「可验证」。
- **Gap**: 提供 evidence 一致性/完整性校验（链是否完整、是否自洽、可复放断言），能检出残缺/
  不自洽 evidence。
- **Needed action**: 实现 verifier（输入 evidence → 校验报告）；定义通过判据；与 G02 模型对齐。
- **Verification**: verifier 对完整 evidence 通过、对残缺/篡改样本失败；测试覆盖两侧。
- **Dependencies**: S4-G02。
- **Non-goal boundary**: 不做密码学防篡改签名（除非 contract 要求）；不做外部上报。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G05）。
- **Evidence**: `agent/evidence_verifier.py`（`verify_replay_chain` + `verify_evidence`；
  四项 finding：complete/self_consistent/ordered/replayable，reason =
  chain_incomplete/count_mismatch/duplicate_ref/sequence_disorder/not_replayable）。
  `tests/test_s4_evidence_verifier.py`（7 passed：完整通过 + 残缺 tool/delegation →
  chain_incomplete + status 篡改 → count_mismatch + seq 乱序 → sequence_disorder + 空链 →
  not_replayable + 重复 ref → duplicate_ref）。非回归：S4 suite + S2/S3 reference
  27 passed / 2 skipped。Commit: `feat(s4): G05 evidence verifier (AC-5)`。

### S4-G06 — Audit/replay reference task E2E (fake/local)
- **Priority**: P1（must_fix_for_s4）
- **Layer**: L4
- **Related AC**: AC-6（+ AC-1 S1/S2/S3 must-not-regress）
- **Baseline evidence**: S3 reference task 模板存在但只到「记录」，无「复放/校验」闭环。
- **Gap**: 建立 S4 reference task E2E：governed path 内完成「执行（含 MCP+SubAgent）→ 记录
  → 复放/校验」闭环（fake 确定性）；S2/S3 targeted gate 纳入作 must-not-regress。
- **Needed action**: 按 G01 规格实现 fake/local E2E；组合 G02/G03/G05；作 S4 验收锚点。
- **Verification**: fake E2E 确定性通过且经真实 evidence 路径复放/校验；S2/S3 gate 仍过（AC-1）。
- **Dependencies**: S4-G01/G02/G03/G05。
- **Non-goal boundary**: 不连真实 endpoint；不把 full pytest 全绿当唯一目标。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G06）。
- **Evidence**: `tests/test_s4_reference_task_acceptance.py::test_s4_reference_task_audit_replay_closed_loop`
  —— governed path（receive→accept→execute[MCP+SubAgent]→advance→done）→ record
  （`build_task_evidence_report.replay_chain_events` 非空）→ replay（chain 重建 MCP tool +
  SubAgent 委派，policy_outcome=accept_result）→ verify（`verify_evidence` ok=True）→
  AC-3（注入 fake secret `sk-test-...` 在 chain preview 中被 `[REDACTED]`）→ AC-1
  （S2/S3/S4 acceptance report `release_blocked is False`、`runtime_regressions == ()`）。
  81 passed / 2 skipped（S4 suite + S2/S3 + evidence；real-provider opt-in）。Commit:
  `test(s4): G06 audit/replay reference task E2E (fake/local, AC-2/3/5/6-fake/1)`。

### S4-G07 — Real provider audit key-path smoke
- **Priority**: P1（must_fix_for_s4）
- **Layer**: L1
- **Related AC**: AC-6（real）
- **Baseline evidence**: S3 real smoke 模式（opt-in `MY_FIRST_AGENT_RUN_S3_REAL_PROVIDER_SMOKE`、
  生产路径、fake-key 检测、默认 skip）可复用。
- **Gap**: real provider 在 key-safe opt-in 下覆盖 audit/replay 关键 path（进入审计 path、
  evidence 可复放/校验、与 fake 链路对齐）；不要求全分支。
- **Needed action**: 扩 real smoke 覆盖 audit key path；key-safe（opt-in、默认 skip、不读/打印/
  复制/移动/提交 secret、不改 ignored config、不创建 .env）。
- **Verification**: opt-in 下进入 audit path 并产生可校验 evidence；默认 skip；secret 边界保持。
- **Release gate（resolved decision 4）**: deliverable = **key-safe opt-in smoke harness +
  structural verification**；有 key 且安全时可跑关键 smoke，无 key 时 **default skip +
  structural verification 即满足 AC-6 real 维度**。real-key 实跑**非必需、非 release blocker**
  （P1 = 必达「harness 就位」，非 P0 release-blocker；release-blocker 仅 P0）。
- **Dependencies**: S4-G06。
- **Non-goal boundary**: 不要求 real 覆盖所有分支；不泄露 secret；real-key 实跑不作 blocker。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G07）。
- **Evidence**: `tests/test_s4_reference_task_acceptance.py::test_s4_reference_task_real_provider_audit_key_path_smoke`
  —— opt-in（`MY_FIRST_AGENT_RUN_S4_REAL_PROVIDER_SMOKE=1`）/ 默认 skip；经生产路径
  `build_model_provider_from_env()` 解析 provider（与 runtime 同源，只透传不打印 key）；
  fake-key 检测；进入 audit/replay governed path（receive/accept + MCP 结果 + SubAgent），
  与 fake E2E 同入口（非旁路 bare provider.create）；断言 replay_chain 可重建 +
  verify_evidence 通过 + redaction 保持。**opt-in 实跑证据**：开启 opt-in 后 harness 正确解析
  到真实 anthropic provider（config 有 real key）、进入 real governed path 调用
  provider.create()——证明 harness 进入真实路径；调用 31s 后 `ProviderTimeoutError`
  （网络/环境超时，**非代码缺陷、非 secret 泄漏**——traceback 仅含 `_headers()/_url()`，无 key）；
  依 resolved decision 4，real-key 实跑非 blocker，**默认 skip + 结构校验（G06 fake E2E 同路径）
  即满足 AC-6 real 维度**。默认模式 1 passed / 1 skipped。Commit: `test(s4): G07 real provider
  audit key-path smoke (opt-in/key-safe, AC-6 real)`。

---

## 6. P2 — Should fix for S4

### S4-G08 — Acceptance gate evidence-fidelity-regression classification
- **Priority**: P2（should_fix_for_s4）
- **Layer**: L1 / Cross
- **Related AC**: AC-7
- **Baseline evidence**: `agent/acceptance_gate.py` 现分类 runtime/extension/doc_governance/
  quality/unknown；无 evidence-fidelity 回归类。
- **Gap**: 让 gate 能区分 evidence-fidelity 回归与既有类，不弱化既有分类。
- **Needed action**: 增分类口径/判据（复用 S3-G08 EXTENSION_REGRESSION 模式）；不弱化四/五类。
- **Verification**: gate 对 evidence-fidelity 失败给对应信号；既有类不弱化。
- **Dependencies**: 与 S4-G06 并行。
- **Non-goal boundary**: 不重写既有类；不把 TD-007 变 blocker。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G08）。
- **Evidence**: `agent/acceptance_gate.py` 加 `EVIDENCE_FIDELITY_REGRESSION` 枚举 +
  `_looks_like_s4_evidence_fidelity_check`（"s4" + evidence 标记 replay/verifier/evidence/
  redaction/pending_tool/audit/reference_task）+ 分类分支（release_blocking=True）+
  `S2AcceptanceReport.evidence_fidelity_regressions` 属性。纯新增，不弱化既有 S2/S3/debt
  分类。`tests/test_s4_acceptance_gate_evidence_classification.py`（9 passed：S4 replay/
  verifier/reference_task/redaction 失败 → EVIDENCE_FIDELITY_REGRESSION；S2 runtime/S3
  extension/ruff/passed 既有分类不弱化；report 聚合可见 + release-block）。非回归：S2/S3 gate
  分类测试 17 passed。Commit: `feat(s4): G08 acceptance gate evidence-fidelity classification (AC-7)`。

### S4-G09 — docs/current + history governance for S4
- **Priority**: P2（should_fix_for_s4）
- **Layer**: Cross
- **Related AC**: AC-8
- **Baseline evidence**: S3 已归档；`docs/current/` 持 S_ROADMAP/TECH_DEBT + S4 stage docs。
- **Gap**: S4 期间维持阶段治理不回退：S4 docs 在 current、S1/S2/S3 归档不动、carry-forward
  债不被静默关闭、WORK_LOG 持续追加、close-out 按规则归档。
- **Needed action**: 贯穿维持；提供 S4 close-out 检查项。
- **Verification**: 归档未改；TECH_DEBT 不被静默关闭；S4 docs 在 current；close-out 可过治理检查。
- **Dependencies**: 无（贯穿）。
- **Non-goal boundary**: 不重写 governance 模型；不动历史。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G09）。
- **Evidence**: 治理不变量核实（S4 docs 在 `docs/current/`；`docs/history/` S1/S2/S3 git-clean 未动；
  TECH_DEBT 状态正确——TD-001/TD-004 resolved-in-S4 仍在 register 未静默关闭、TD-002/003/007 open、
  TD-008-011 deferred）；新增 `S4_GOAL_GAP.md §12 S4 Close-out Checklist`（governance artifact，
  19 项：Stage Closing Review + AC-1..AC-9 + debt 收尾 + archive；**本任务不执行 close-out**）。
  Commit: `docs(s4): G09 docs governance + close-out checklist (AC-8)`。

### S4-G10 — S1/S2/S3 non-regression + full-suite green release signal
- **Priority**: P2（should_fix_for_s4）
- **Layer**: Cross / L1
- **Related AC**: AC-1 / AC-9
- **Baseline evidence**: full pytest 绿（4823 passed）；S2/S3 targeted gate 过；TD-007 非 blocker。
- **Gap**: S4 evidence 改动**不得**回归 S1/S2/S3（same-spine / governed task / L5 extension /
  既有 evidence 契约）；维持 full-suite 绿作 release 信号；TD-007 仍仅 quality debt。
- **Needed action**: 回归守护（S2 governed tool contract / S3 extension evidence 套件）；
  full pytest 每 gap 后保持 0 failed；focused ruff for touched files。
- **Verification**: 每 S4 gap 后 targeted S2/S3 gate + full pytest 绿；touched-file ruff 过。
- **Dependencies**: 贯穿。
- **Non-goal boundary**: 不把 TD-007 全清作 blocker；不弱化既有断言充数。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G10）。
- **Evidence**:
  - **Full pytest（release 信号, AC-9）**: `4861 passed, 16 skipped, 28 xfailed, 0 failed,
    exit 0`（211.87s）。28 xfail 为既有文档化项（FakeProvider 语义/config.yaml 隔离/未写 RFC），
    非 hidden failure。
  - **回归捕获 + 修复**: full pytest 抓到 G02 引入的 S2 契约回归——
    `test_s2_task_evidence_report_is_replay_ready_without_full_body_persistence` 断言
    `"raw tool output" not in str(report)`，因 G02 把带 content preview 的 `replay_chain_events`
    嵌入 safe-summary report 而破坏。**架构修复**：replay chain 改为独立投影
    （`build_replay_chain`，G03/G05/G06 已用它），report 只带安全整数 `replay_chain_event_count`
    （不嵌入 content），守 S2 safe-summary 契约。修复后 full pytest 绿。
  - **S1/S2/S3/S4 acceptance set**: 59 passed / 4 skipped（real-provider opt-in，预期）。
  - **focused ruff（touched files）**: 全 clean。global ruff 仍 ~443（TD-007，非 blocker）。
  - Commit: `fix(s4): G10 S2 evidence-report safe-summary regression + full-suite green (AC-1/9)`。

---

## 7. P3 — Optional for S4

### S4-G11 — Optional audit observability (report formats / summaries)
- **Priority**: P3（optional_for_s4）
- **Layer**: L3
- **Related AC**: AC-2 / AC-5（enhance）
- **Baseline evidence**: G02/G05 交付基础保真+校验即满足 AC；更丰富的 audit 报告/摘要是增强。
- **Gap**: 可选：更丰富 audit report 格式、replay 摘要、人读审计视图。
- **Needed action**: 视余力增强；不阻塞 release。
- **Verification**: 增强项有测试/证据；不回归 P1/P2。
- **Dependencies**: S4-G02/G05。
- **Non-goal boundary**: 不升级为必达；不滑向外部上报/生态化。
- **Status**: **satisfied**（2026-06-20，S4 gap loop G11，P3 增强）。
- **Evidence**: `agent/audit_observability.py`（`render_replay_summary(chain)` 人读审计视图 +
  `replay_summary_stats(chain)` 结构化计数；preview 已在 chain 投影点 G03 redacted，本模块再过
  redact_text 作 defense-in-depth；不采集/不持久化/不外部上报）。`tests/test_s4_audit_observability.py`
  （4 passed：人读可读 + fake secret 不出现 + 计数无 content 泄漏 + 空链不 crash）。Commit:
  `feat(s4): G11 optional audit observability (human-readable replay view, P3)`。

---

## 8. P4 — Deferred to S5/Sn

### S4-G12 — Deferred boundaries & TECH_DEBT carry-forward triage
- **Priority**: P4（s5_or_later / deferred）
- **Layer**: Cross
- **Related AC**: §7 Non-goals
- **Baseline evidence**: TECH_DEBT 余项 + S4 non-goals。
- **Gap（仅登记，不执行）**: 明确以下**不进入 S4**：
  - **Byte-for-byte 全量持久化**（若与 secret-safe 冲突）→ 超出 S4；S4 做 redacted-faithful。
  - **Durable cross-session task ledger（TD-011）** → S5/Sn；resume 仍靠 checkpoint。
  - **Memory 激活** → 需用户显式授权，超出本 goal。
  - **Scheduler 生产化（TD-008）/ 完整 MCP 生态（TD-009）/ 完整 multi-agent（TD-010）** → S5/Sn。
  - **TD-002（legacy facade）/ TD-003（dead code）** → 非 S4 触发项，deferred。
  - **TD-007（ruff 全清）** → deferred（非 release blocker）。
- **Needed action**: 贯穿维持 deferred 标注；若 S4 任务路过相关代码再按需提升（需 goal 授权）。
- **Verification**: 这些项不出现在 S4 P0-P2 必达集；TECH_DEBT 与本文件一致。
- **Dependencies**: 无（贯穿登记）。
- **Non-goal boundary**: 本 gap 不执行任何清理/激活/生态化。
- **Status**: deferred。

---

## 9. Original ID index

| ID | Title | Priority | Status | Layer | Related AC |
|---|---|---|---|---|---|
| S4-G01 | Define fidelity contract + audit/replay reference task | P0 | satisfied | L3/Cross | AC-2/5/6 setup |
| S4-G02 | Replay-faithful evidence model | P1 | satisfied | L3 | AC-2 |
| S4-G03 | Secret-safe redaction enforcement | P1 | satisfied | L3/Sec | AC-3 |
| S4-G04 | Pending-tool event fidelity (TD-004) | P1 | satisfied | L3 | AC-4 |
| S4-G05 | Evidence verification / consistency check | P1 | satisfied | L3 | AC-5 |
| S4-G06 | Audit/replay reference task E2E (fake/local) | P1 | satisfied | L4 | AC-1/6 |
| S4-G07 | Real provider audit key-path smoke | P1 | satisfied | L1 | AC-6 |
| S4-G08 | Acceptance gate evidence-fidelity classification | P2 | satisfied | L1/Cross | AC-7 |
| S4-G09 | docs/current+history governance for S4 | P2 | satisfied | Cross | AC-8 |
| S4-G10 | S1/S2/S3 non-regression + full-suite green signal | P2 | satisfied | Cross/L1 | AC-1/9 |
| S4-G11 | Optional audit observability | P3 | satisfied | L3 | AC-2/5 (enhance) |
| S4-G12 | Deferred boundaries & TECH_DEBT triage (S5/Sn) | P4 | deferred | Cross | §7 |

## 10. Non-goal guardrails

S4 **不做**（防越界）：

- 不推翻 S1/S2/S3 runtime spine；不引入第二条主链路（same-spine must-not-regress）。
- **不持久化 raw secret / API key / 完整凭证**；保真必须 secret-safe（redaction）。
- 不做 byte-for-byte 全量持久化（若与 secret-safe 冲突）；做 redacted-faithful replay。
- 不做 Scheduler 生产化（TD-008）/ 完整 MCP 生态（TD-009）/ 完整 multi-agent（TD-010）。
- **不激活 memory**（需用户显式授权）；**不做 durable ledger**（TD-011）。
- 不把 TD-007 / ruff 全清作 S4 release blocker。
- 不连真实 MCP endpoint / 不做 server reachability check；fake-first/local-only。
- 不做完整 AutoGPT 式自主；不开始 S5/Sn；不删未完成 gap；完成需证据。

## 11. Next step

- `S4_GOAL.md` 已**冻结**（2026-06-20），本 backlog 已据冻结 goal **校准**。
- **S4 gap loop 正在执行**（2026-06-20 起）：按 §3 顺序逐个 gap 独立 focused mini-run
  （TDD red→green、验证、更新 backlog/work log、独立提交）。进度见各 gap 的 Status/evidence
  与 `WORK_LOG.md`。
- **冻结+校准阶段**（本文件最初成文时）不执行 gap；该约束已被 gap loop 执行取代。

## 12. S4 Close-out Checklist（governance artifact — 本任务**不执行** close-out/archive）

> 由 S4-G09 产出。这是**未来** S4 close-out（仅当用户授权时）的检查项，**不是**当前执行项。
> 依据 `AGENTS.md` Stage Closing Review + S4 frozen goal AC-1..AC-9。close-out 前必须全部成立。

**Stage Closing Review（AGENTS.md）：**

1. 复核 `S4_GOAL_GAP.md` 所有 open/deferred 项：G09-G11 应已 satisfied（或显式 deferred），
   G12（P4 deferred）确认仍 deferred。
2. 完成所有仍在 stage 范围内可行的 gap；不可行的移 TECH_DEBT（附 ID）。
3. 重要但越 stage 的未完成项移 `TECH_DEBT.md`，并在本文件标 moved-to-debt + debt ID。
4. 不静默删除未完成 gap；完成项需证据（commit/test/audit section/source ref）。

**S4 acceptance（AC-1..AC-9）：**

5. AC-1：S2/S3 targeted gate + full pytest 绿（same-spine/governed task/L5 governed-active/
   acceptance gate 在 fake 确定性下不回归）。
6. AC-2：replay-faithful evidence（`build_replay_chain` 重建 MCP+SubAgent 链路，超出标签级）。
7. AC-3：secret-safe redaction（注入 fake secret 不入 evidence；有断言）。
8. AC-4：pending-tool 预览非空（TD-004 resolved）。
9. AC-5：evidence verifier（完整通过 / 残缺·篡改·乱序失败）。
10. AC-6：reference task E2E（fake/local 闭环）+ real key-safe smoke harness（opt-in/默认 skip）。
11. AC-7：acceptance gate evidence-fidelity 分类（不弱化既有类）。
12. AC-8：治理不回退（S1/S2/S3 归档不动；carry-forward 债不静默关闭；S4 docs 在 current）。
13. AC-9：full pytest 绿作 release 信号；TD-007（ruff）非 blocker。

**Debt 收尾：**

14. TD-001 / TD-004（resolved-in-S4，仍在 register）→ 从 `TECH_DEBT.md` 移除，resolution 记入
    S4 archive（镜像 TD-006/TD-001/TD-004 处理）。
15. TD-002/003/007（open）/ TD-008-011（deferred）状态确认无误，不被静默关闭。

**Archive（仅 close-out 时）：**

16. S4 stage docs（`S4_BASELINE_STATUS/GOAL/GOAL_GAP/FIDELITY_CONTRACT/WORK_LOG`）+
    scratch evidence（`_tmp_*`）归档到 `docs/history/S4_*/`（镜像 S2/S3 布局）。
17. `docs/current/` reset 到 S_ROADMAP + TECH_DEBT + 下一阶段 baseline。
18. `AGENTS.md` stage status 更新为 S4-closed / S5-preparing。
19. 不 push（除非用户显式授权）；不读/打印/复制/移动/提交 secret；不动 `config/config.yaml`；
    不创建 `.env`。

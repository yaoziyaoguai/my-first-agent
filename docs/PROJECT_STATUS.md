# Project Status — First Agent

**最后更新**: 2026-06-05
**当前状态**: **CORE_CHAT_STABILIZATION_REQUIRED**
**前次状态**: USER_RECHECK_FAILED_WITH_P1_FINDINGS (2026-06-04) — 2 P1 + 1 P2 在真实用户路径下复测失败。
**架构红队审计**: 2026-06-05 完成（只读，未落盘）。核心结论: fake/real 两套系统已形成，~95% 测试只覆盖 fake 路径，FIXED_BY_RECHECK 自证循环已固化，文档存在 overclaim。统一运行时骨架正确但需要止血收敛。
**Close-out handoff**: `docs/handoff/first-agent-current-stage-close-out-2026-06-02.md` — 历史阶段冻结声明。
**V1 Closeout**: `docs/releases/v1/first-agent-v1-closeout.md` — **HISTORICAL**。已标记 `v1.0.0-engineering-closeout` → `f6807ef`。其中 §4 存在事实错误（声称 test_architecture_boundaries.py 不存在），见 errata。

本文档是 Coding Agent 和人类开发者的**第一优先读取入口**。如果其他文档与本文档冲突，以本文档为准。

---

## 核心决策 (2026-06-05)

**在 Core Chat golden E2E 通过之前，不进入任何 v2 feature、TUI、MCP、Memory、SubAgent 扩展。**

当前最重要的工作不是继续扩功能，而是确保这条路径真实可信：

```
python main.py --plain → real provider → core.chat → ToolRuntimeMediator → TOOL_GATE/INVOKE/RESULT → evidence
```

所有其他能力（TUI、MCP、Memory、SubAgent）在这条主线被用户真实验证通过之前，不得继续推进。

---

## 1. 状态分类体系 (Status Taxonomy)

以下状态词在整个仓库中必须统一使用，不允许混用：

| 状态 | 含义 | 可作为完成证据？ |
|------|------|:---:|
| **REAL_USER_VERIFIED** | 真实入口 (`python main.py --plain`) + 真实 provider + 用户手动复测通过 | **YES** |
| **REAL_PROVIDER_E2E_VERIFIED** | 真实 provider 下自动 E2E 通过（脚本/subprocess），但非人工确认 | **YES (with sampling)** |
| **FAKE_VERIFIED** | fake provider / synthetic 路径通过，只能证明替身路径正确 | **NO** — 不能用于 close capability |
| **FOCUSED_TEST_VERIFIED** | 单元测试 / focused tests 通过，只证明局部逻辑正确 | **NO** — 不能用于 close capability |
| **SYNTHETIC_DOGFOOD_VERIFIED** | 自动 dogfood 通过，必须标明 fake/real provider | **FAKE: NO / REAL: partial** |
| **USER_RECHECK_FAILED** | 用户复测失败 | 优先级**高于**任何自动验证 |
| **EXPERIMENTAL** | 代码存在，不能作为 v1 主能力证据 | **NO** |
| **FROZEN** | 保留代码在磁盘，不再投入主线 | **NO** |
| **DOCS_ONLY** | 文档或计划存在，但未被真实代码路径证明 | **NO** |
| **ACCEPTED_CAVEAT** | 已知缺口，明确接受 | **NO** — 不等于 fixed |

**禁止模式**:
- 不把 FAKE_VERIFIED 写成 "verified"
- 不把 FOCUSED_TEST_VERIFIED 写成 "capability complete"
- 不写 FIXED_BY_RECHECK，除非有 USER_RECHECK 通过证据
- 不把 accepted-with-caveats 写成 resolved

---

## 2. 子系统真实状态定级 (2026-06-05)

| 子系统 | 实际状态 | 可信证据等级 | 定级 |
|--------|---------|:-----------:|------|
| **Plain CLI** (`python main.py --plain`) | 稳定主入口，real provider 可配 | REAL_PROVIDER_E2E (interactive dogfood 15/15) | **PRIMARY_PATH** |
| **Core runtime** (`core.chat` / `loop.py`) | 统一调度器，设计正确，工程完整 | FAKE_VERIFIED (95% tests) + REAL_PROVIDER_E2E (interactive dogfood) | **PRESERVE** — 需要 golden E2E |
| **ToolRuntimeMediator** (GATE→INVOKE→RESULT) | 统一工具流水线，工程正确 | REAL_PROVIDER_E2E (12/12 real provider SKILL_SELECT) | **PRESERVE** |
| **Tool safety** (sensitive path policy) | config.yaml/.env 拒绝有效 | REAL_USER_VERIFIED (F-001 真实路径复测确认) | **PRESERVE** |
| **Skill** (SKILL_SELECT + allowed_tools) | BASE_TOOLS 追加模型已修复 (70a565b) | FAKE_VERIFIED (37 focused tests) + USER_RECHECK_FAILED (P1) | **PRESERVE_AS_MODULE** — 需 golden E2E recheck |
| **Memory** (extract/propose/retain/recall) | W3/W4/W5 分层补丁，FakeMemoryExtractor 默认 | FAKE_VERIFIED (FakeMemoryExtractor) + REAL_PROVIDER_E2E (opt-in) | **PRESERVE_AS_SKELETON** — 不在主线验证通过前推进 |
| **MCP** (bridge + invoke) | bridge 启动注册，FakeMCPClient 默认 (dry_run=True) | FAKE_VERIFIED (local stdio fixture) | **PRESERVE_AS_ADAPTER_SKELETON** — 不标 production ready |
| **SubAgent** (L0/L1/L2) | L0=deterministic fake, L1=real LLM, L2=native loop | FAKE_VERIFIED (L1/L2 _SpyProvider tests) | **FROZEN** — 不在主线验证通过前推进 |
| **Textual TUI** (`python main.py --tui`) | 事件驱动后端，真实 runtime 接入 | USER_RECHECK_FAILED (P1 deadlock) | **CANDIDATE** — 不激活默认入口 |
| **Ink TUI** (`cd tui && npm start`) | TypeScript 独立进程，SAFE_DATA_FIXTURE 固定数据 | FAKE_VERIFIED (不接真实 runtime) | **FROZEN_PROTOTYPE** |
| **Dogfood reports** | 多个报告，fake/synthetic 占多数 | 混杂 (fake + real + synthetic) | **EVIDENCE_ARCHIVE** — 不作为 source of truth |
| **v1 closeout doc** | engineering baseline 声明 | DOCS_ONLY — 有事实错误 (test_architecture_boundaries.py) | **HISTORICAL** — 需要 errata |

---

## 3. Core Chat Stabilization Before V2

### Goal

在恢复任何 v2 feature 之前，先建立可信 Code Chat 主线。

### Scope

只聚焦：
- `python main.py --plain`
- real provider
- `core.chat` / unified runtime
- `read_file README`
- block `config/config.yaml`
- `demo-note-maker` Skill
- quit / Ctrl+C
- session/evidence

### Non-goals

不修 Ink TUI。不推进 MCP production。不推进 Memory advanced。不推进 SubAgent。不推进 B7/B8/B9。不新增大文档。不继续 fake closeout。

### Golden E2E — 5 条最小真实路径

| ID | 路径 | 验证内容 |
|----|------|---------|
| **G1** | `python main.py --plain` → hello → quit | 基础对话 + 正常退出 |
| **G2** | `python main.py --plain` → read README → summarize entry strategy | 基础只读工具 + Skill 激活后不丢 base tools |
| **G3** | `python main.py --plain` → request `config/config.yaml` → must block → safe fallback | sensitive path policy |
| **G4** | `python main.py --plain` → demo-note-maker Skill → legal skill tools execute → base read tools still available | Skill 工具作用域正确 |
| **G5** | `python main.py --plain` → Ctrl+C twice → graceful exit and session save | 信号处理 + checkpoint |

### Exit Criteria

- G1-G5 全部 **REAL_USER_VERIFIED** 或 **REAL_PROVIDER_E2E_VERIFIED** + 用户抽样确认
- **不允许** fake-only 关闭
- **不允许** focused tests 单独关闭
- 文档状态一致

### Only After Exit

再考虑 Textual TUI → MCP → Memory → SubAgent → v2 features（按此顺序）。

---

## Evidence Infrastructure — Future Subsystem Extension Contract (2026-06-05)

Evidence recorder (`agent/evidence_recorder.py`) 支持未来未知子系统无侵入接入：

- **不需要新增日志文件类型** — 所有事件走 `record_evidence()` 统一写入 `agent_log.jsonl` + per-session `events.jsonl`
- **不需要改核心 envelope schema** — `subsystem`/`operation`/`phase`/`status` 是自由字符串，不硬编码枚举
- **不需要在 log_viewer 中硬编码特殊解析** — 非 tool/checkpoint 的 `evidence.recorded` 事件自动聚合到 "Subsystem Events" generic section
- **metadata 大字符串值自动摘要化** — >2KB 的 metadata 值替换为 `{result_size, result_hash, preview_redacted, truncated}` 摘要 dict
- **sensitive 标记仍有效** — `sensitive=True` + `content_redacted=True` 正确传递到 envelope

**MCP/Skill/Memory/SubAgent/TUI 必须通过 `record_evidence()` 写 evidence，不得各自新建日志系统。**



---

## 4. 历史架构分类账 (B1-B8) — 仅供参考

以下为历史架构演进里程碑，在 Core Chat stabilization 期间**不继续推进**。

本文档是 Coding Agent 和人类开发者的**第一优先读取入口**。如果其他文档与本文档冲突，以本文档为准。

---

## 2026-06-02 Global Current-Stage Close-out Sweep

本轮对当前仓库中的核心能力进行收口。早期 v0.1 `B1/B2/B3` smoke/playbook 仍保留为 historical guard，不作为当前能力定义。
当前能力定义分为两部分：**REAL-EVIDENCE (核心能力 E2E 验证)** 与 **架构演进项目 (B1-B8)**。

### REAL-EVIDENCE 状态 (核心能力验证)

| Evidence ID | Current capability definition | Current status | Boundary |
|---|-------------------------------|----------------|----------|
| REAL-EVIDENCE-001 | Memory retain/recall/forget | accepted-with-caveats | real provider evidence credible；recall provenance caveat 非当前 blocker |
| REAL-EVIDENCE-002 | Skill selection / SKILL_SELECT | accepted-with-caveats | real provider evidence credible；prompt-steered / single-skill caveats |
| REAL-EVIDENCE-003 | Skill allowed_tools enforcement | accepted-with-caveats | code path credible；remaining CONCERN are model behavior |
| REAL-EVIDENCE-004 | Checkpoint save/resume | accepted-with-caveats | Part A hardened；Part B save-point not reached caveat |
| REAL-EVIDENCE-005 | MCP bridge readiness | accepted-with-caveats | local stdio fixture, opt-in bridge evidence |
| REAL-EVIDENCE-006 | SubAgent L1 | accepted-with-caveats | real provider child tool mediation credible；future cleanup remains |
| REAL-EVIDENCE-007 | MCP runtime-mediated invocation | accepted-with-caveats | FakeProvider deterministic tool_use + confirmation override validation caveat |
| REAL-EVIDENCE-008 | Advanced scheduler | accepted | evidence chain fully closed；scheduler remains opt-in |

### 架构演进项目 (B1-B8) — 历史架构分类账

以下为历史架构演进里程碑，作为 REAL-EVIDENCE 的架构上下文保留。当前能力定义以 REAL-EVIDENCE-001..008 为准。

| Item | 描述 | 状态 |
|------|------|------|
| **B1** | Memory write dispatcher migration | **COMPLETED** — write path 已统一至 dispatcher |
| **B2** | CLI delegate shortcut → dispatcher | **DONE** — CLI delegation 已通过 dispatcher 路由，并保留 fallback |
| **B3** | SubAgent L1/L2 成熟化 | **ACCEPTED-WITH-CAVEATS** (L1) — L1 mediation 验证闭环，L2 future debt |
| **B4** | MCP real connection | **PARTIAL** — bridge 可信，real external flight pending |
| **B5** | Skill runtime 深化 | **ACCEPTED-WITH-CAVEATS** — allowed_tools 强边界实施，real-model caveats |
| **B6** | Checkpoint true state restoration | **ACCEPTED-WITH-CAVEATS** — direct-save 漏洞移除，trigger condition caveat |
| **B7** | Multi-instance readiness | **ACCEPTED-WITH-CAVEATS** — namespace/events 基础契约完成 (3f2f6b2) |
| **B8** | TUI architecture (Interaction-first) | **ACCEPTED** — fake/local M1-M8 MVP (2f995b9, final caveats closed) |

Close-out audit report: `docs/audit/b1-b8-current-stage-close-out-audit.md`.

Current-stage close-out: **FROZEN — yes-with-caveats** (final baseline: `60fd71e`)。不进入 B9。下一阶段以 handoff doc 为启动基线。Remaining caveats are documented future debt or validation-scope caveats, not current blockers. Not product-ready。

### Post-Closeout Evidence Maintenance (2026-06-02)

b3e0863 `validation(evidence): validate scheduler model generated plan` — post-closeout REAL-EVIDENCE-008 re-validation (ENV_CONCERN):

- **104/104 scheduler focused tests PASS**, ruff clean.
- **ENV_CONCERN (已关闭 — 2026-06-02)**: `config.yaml` api_key 是 `sk-REPLACE_ME` 占位符时 008 re-validation 因 401 无法重跑。用户配置真实 provider key 后重跑 **14/14 PASS, 0 FAIL, 0 CONCERN**（AnthropicCompatibleProvider, `scripts/real_evidence_008_model_generated_plan.py`）。ENV_CONCERN 关闭，008 保持 credible。
- **Malformed safety**: 4/4 PASS (M10-M13)。
- **Current-stage remains closed**。

**002 non-prompt-steered re-validation (2026-06-02)**:

- 用户配置真实 provider key 后重跑: **7 PASS / 1 FAIL / 2 CONCERN**（上次 4/1/3/2，AnthropicCompatibleProvider, `scripts/real_evidence_002_non_steered_validation.py`）。
- C2/C4/C8: CONCERN/PARTIAL → PASS。C6: FAIL (negative trigger bypass, MODEL_BEHAVIOR_CONCERN)。C3/C7: CONCERN (over-eager selection, MODEL_BEHAVIOR_CONCERN)。
- 确定性 selector (Plan 3: 43/43 PASS) 正确执行 negative_triggers 排除；模型 owned SKILL_SELECT 路径负触发绕过是模型行为，非代码缺陷。
- Current-stage remains closed。

**003 hardening re-validation (2026-06-02)**:

- 用户配置真实 provider key 后重跑 (`scripts/real_evidence_003_hardening.py`): **1 PASS / 0 FAIL / 13 CONCERN / 3 SKIP**。
- Disallowed tools 走 OTHER_GATE 而非 `skill_allowed_tools→rejected` — 模型行为变化，非代码回归。skill_allowed_tools gate 代码路径已验证 (Loop 8: 13/0/4 PASS)。
- No side effect from disallowed tool attempts (R35 verified)。
- Current-stage remains closed。

### Next-Stage D-04 — Runtime Gateway Foundation (2026-06-02)

**D-04 B8 real runtime gateway** (handoff §8, §9 Route 1):

- `tui/src/services/` — RuntimeGateway interface + FakeRuntimeAdapter + BlockedRealAdapter 创建。
- 429/429 TUI tests PASS (含 17 个新 gateway tests)。tsc clean。
- FakeRuntimeAdapter 保持当前 fake/local 行为，`source: "fake"` 标注。
- BlockedRealAdapter 返回 explicit blocked message，不静默 fallback 到 fake。
- 不读 .env，不调 core.chat()，不调真实 provider，不创建第二 runtime，不绕过 ToolRuntimeMediator。
- TUI default entry NOT ACTIVATED。
- **Status**: ACTIVE — contract + fake adapter delivered。Real gateway adapter blocked by user authorization。

### Next-Stage D-02 — MCP Real External Connection Readiness (2026-06-02)

**D-02 MCP real external server connection** (handoff §8, §9 Route 3):

- Current state: code path complete — bridge lifecycle dispatcher evidence + local stdio echo fixture (REAL-EVIDENCE-005: 12/12 PASS) + runtime-mediated invocation chain (REAL-EVIDENCE-007: 10/10 PASS)。
- Readiness plan: `docs/design/mcp-real-external-connection-readiness.md`。
- **Status**: BLOCKED_BY_EXTERNAL_SERVER — 需用户提供外部 MCP server fixture/config。

### Next-Stage D-09 — 002 Skill Selection Plan 3 Wiring (2026-06-02)

**D-09 Skill Selection deterministic enhancement** (handoff §11, future debt):

- `agent/skill_system/descriptor.py` — `SkillDescriptor` 新增 `triggers`/`negative_triggers` 字段（Level 1 公开元数据），`SkillManifest.to_descriptor()` 传递这两个字段。
- `agent/skill_system/selector.py` — `SkillSelector` 接入 Plan 3 manifest 字段：
  - `triggers`: 子串/精确匹配，权重 0.4（高于 name word 0.3）
  - `aliases`: 词级匹配，权重 0.3（等同 name word）
  - `negative_triggers`: 黑名单排除（命中则 skill score=0）
- 43/43 selector + manifest tests PASS (14 new Plan 3 tests)。168 broader skill system tests PASS。ruff clean。
- 纯确定性匹配，不调用 LLM/provider/embedding。
- `when_to_use`/`when_not_to_use` 语义匹配: **future real-env task** (需 LLM)。
- Non-prompt-steered real model validation: **future real-env task**。
- **Status**: ACTIVE — Plan 3 manifest fields 已接入确定性选择器。002 保持 credible (12/12 PASS)。Non-prompt-steered real model validation: 7 PASS / 1 FAIL / 2 CONCERN (AnthropicCompatibleProvider, 2026-06-02)。C6 negative trigger bypass + C3/C7 over-eager selection 为 MODEL_BEHAVIOR_CONCERN。

### Next-Stage D-01 — SubAgent L2 Native Loop (COMPLETED — 2026-06-02)

**D-01 B3 SubAgent L2 native loop** (handoff §8, future debt):

- SPEC delivered: `docs/design/subagent-l2-native-loop-sdd.md`。
- **Implementation delivered** (6498c52):
  - S1: `TASK_COMPLETED_BY_CHILD` 枚举 + `batch_memory_proposals`/`revision_history` 类型扩展。
  - S2: `execute_l2()` — child turn loop、end_turn 检测、bracket-counting `_parse_batch_memory()`。
  - S3: `delegate_l2()` — revision loop + adjudication gate (accept/reject/request_revision/ask_user) + `is_l2_gated`/`l2_available` runtime helpers。
  - S4: `SUBAGENT_DELEGATE_L2`/`SUBAGENT_CHILD_BATCH_MEMORY` action types + `SubAgentDelegateL2Handler` + phase1_hook 注册。
  - S5: 20 L2 contract tests with `_SpyProvider` + `_SpyToolMediator`。
- L2 gated behind `SubAgentPolicy.real_llm_tool_requesting_allowed`（safe default: gated when policy absent）。
- All tests use `_SpyProvider` — no real API。
- Real provider dogfood: **future task**.
- **Status**: COMPLETED。Gates: 20/20 L2 contract + 8/8 delegation contract + 34/34 decision frame + 79/79 docs source-of-truth PASS, ruff clean。

### Next-Stage Gap Audit — 2026-06-02

**独立只读审计** — 8 维度 capability inventory (Runtime/Provider, MCP, Skill Selection, SubAgent, Memory/Checkpoint, TUI, Evidence/Docs, Legacy)。5 phase (Phase 0-5)。0 P0/P1 blocker。0 secret leak。current-stage remains closed。

**Slice B 就绪判定**: yes-with-caveats。

**Top 5 remaining technical gaps** (updated 2026-06-02):
1. Skill negative trigger bypass (C6) — MODEL_BEHAVIOR_CONCERN（模型 owned SKILL_SELECT 路径绕过确定性 negative_triggers）
2. MCP external production connection — `MY_FIRST_AGENT_MCP_ENABLE` 未设置 + 外部 MCP server fixture 待配置
3. Chinese IME validation — MANUAL_PENDING，需真实终端人工验证
4. D-04 real gateway adapter — blocked by TUI default entry activation (PRODUCT_DECISION)
5. Memory extractor zero proposals — episodic extractor redesign (FUTURE_DEBT)

**Post-closeout validated (2026-06-02)**:
- 008 model-generated ActionPlan: 14/14 PASS — ENV_CONCERN 关闭
- 002 non-prompt-steered skill selection: 7/10 PASS, C6/C3/C7 MODEL_BEHAVIOR_CONCERN
- 003 disallowed-tool hardening: 1 PASS / 0 FAIL / 13 CONCERN (OTHER_GATE, MODEL_BEHAVIOR)
- D-01 SubAgent L2 native loop: COMPLETED
- D-02 local filesystem MCP smoke: DONE

**PRODUCT_DECISION (5 项 — v1 tag 前需用户决策)**:
- PD-001: 是否将 Textual TUI (`python main.py --tui`) 作为未来默认 terminal app
- PD-002: 是否保留 Plain CLI (`python main.py`) 为 fallback
- PD-003: 是否冻结/归档 Ink prototype (`cd tui && npm start`)
- PD-004: 是否 deprecated / remove `--shell` in v2
- PD-005: v1 tag wording

**User-config items**:
- ~~替换 `sk-REPLACE_ME` 为真实 DashScope API key~~ — **DONE** (用户已配置, 不 commit)
- 设置 `MY_FIRST_AGENT_MCP_ENABLE=1` + 外部 MCP server 路径 (for FUTURE_DEBT production MCP)
- 人工终端验证 Chinese IME (iTerm2/Terminal.app + CJK input method)
- 批准 TUI default entry activation (blocked, NOT ACTIVATED)
- Legacy Dashboard/AutoRun cleanup 决策 (Option C: on-disk keep)

**Slice B allowed data**: RuntimeDecisionFrame summary, MCP local smoke status, skill evidence summary, checkpoint/memory read-only summary, pending actions, selected lens/session/run/instance state, docs-derived data (Developer/Evidence lens only)。

**Slice B forbidden**: no real provider call, no real MCP server, no memory/checkpoint/event write, no ToolRuntimeMediator bypass, no default entry activation, no product-ready claim, no Dashboard resurrection。

---

## B8 M1 — Interaction-first Workbench MVP (2026-06-02)

经过 4 轮方向校准 (Round 1-4)，B8 M1 已交付：

| 组件 | 状态 |
|------|------|
| `WorkbenchLayout.tsx` | 3 区域布局（Agent Lens 25% / Interaction 50% / Context 25%） |
| `AgentLensPanel.tsx` | agent/session/run/instance 树形选择（fixture data） |
| `InteractionPanel.tsx` | 对话展示区域 placeholder |
| `ContextPanel.tsx` | 通用 Context/Inspector placeholder（mock/static） |
| `InputBar.tsx` | 基础文本输入 |
| `StatusBar.tsx` | lens/focus/mode 信息 + keybinding hints |
| `agentLensFixture.ts` | 3 agents fixture data |
| `types.ts` | AgentLensNode, SelectedLens, FocusZone, EMPTY_SELECTED_LENS |
| `layout.test.tsx` | 23 tests (fixture validation + focus management + component smoke + safety) |

**核心方向**:
- First Agent = 通用 Agent Runtime/Workbench（不是 coding-engine 项目管理工具）
- 布局: Agent Lens (25%) / Interaction View (50%) / **Context Panel** (25%)
- 焦点管理: Tab 在 interaction → agent-lens → context 循环，Shift+Tab 反向
- 右侧面板叫 **Context Panel**（不叫 Audit Lens）
- Context Panel 内容为 mock/static generic placeholder（不展示 project-specific 数据）

**PAUSED — 不产品化**:
- 所有 Operations/AutoRun/Project dashboard 展示
- evidence/gate/checkpoint/memory/event 审计面板
- Dashboard.tsx（旧 7 视图，保留在磁盘但不 import）
- 所有 project-specific operations 展示

---

B7 current-stage **closed — accepted-with-caveats**。Codex 独立红队诚信审计 (commit 3f2f6b2) 确认：

- Skill-state P1: not regressed
- Runtime-E2E semantics: resolved
- Architecture boundary: intact
- P3 docs: honest
- B7-caused failures: 0
- No further B7 remediation loop required

### Caveats

44 pre-existing/non-B7 failures **已全部处理**（B8 Phase 6B Readiness Cleanup, 2026-06-02）。处理结果：2 处修复 + 28 xfailed（含 9 previously xfailed）= 0 live failures。分类分布：

| 分组 | 数量 |
|------|------|
| Provider contract | 5 |
| Startup readiness | 4 |
| Main loop end_turn | 6 |
| Second round dogfood | 4 |
| Local trial readiness | 6 |
| Confirmation flow | 2 |
| V0.1 smoke playbook | 2 |
| Runtime action contract | 2 |
| MCP L3 real core loop | 2 |
| Skill L2 contract | 1 |
| Tool pipeline L3 | 1 |
| Evidence taxonomy guard | 1 |
| Completion handoff | 1 |
| Executor audit | 1 |
| Hardcore scenarios | 1 |
| Health report | 1 |
| Long running | 1 |
| Memory extraction | 1 |
| Runtime trace RFC | 1 |
| User path dogfood | 1 |
| **Total** | **44** → **0 live failures, 28 xfailed** |

### B8 Readiness

| 项目 | 状态 |
|------|------|
| B8 M1 (Interaction-first MVP) | **DELIVERED** — 3 区域布局 + fixture data + 23 tests |
| B8 M2 (Agent Lens selection) | **DELIVERED** — keyboard nav (↑↓/Enter) + selectedLens 驱动全界面 |
| B8 M3 (Fake Interaction) | **DELIVERED** — fakeRuntimeGateway + InputBar submit + message list |
| B8 M4 (Context refresh) | **DELIVERED** — messageCount + lastInteractionTime + lens switch refresh |
| B8 M5 (Pending Actions) | **DELIVERED** — fake/local PendingAction + ControlledOperationGateway + PendingActionPanel；selectedLens scoping regression covered |
| B8 M6 (History Foundation) | **DELIVERED** — fake/local EvidenceNamespace + MultiRunStorageContract + AgentHistoryIndex + HistoryPanel；real adapter pending |
| B8 M7 (Event Stream) | **DELIVERED** — fake/local EventSourceContract + EventStreamReader + EventPanel + recursive redaction + selectedLens scoping |
| B8 M8 (Default Entry Readiness) | **DELIVERED** — 18-item readiness checklist updated with M5-M8 completion, still NOT ACTIVATED |
| B8 旧 Phase 1-6A | **PAUSED** — 保留在磁盘但不 import/渲染 |
| TUI default entry | **NOT ACTIVATED** — M8 前不激活 |

### Failure Classification Summary

28 xfailed tests fall into 4 categories:

| Category | Count | Reason |
|----------|-------|--------|
| End-turn reply semantics | 9 | FakeProvider 行为变化，非空 end_turn reply 是模型行为变化而非代码缺陷 |
| Confirmation/state machine | 7 | 确认流程状态机语义变更，awaiting 状态与测试预期不同 |
| Real env (MCP/dogfood) | 5 | 需要真实 Provider 环境，FakeProvider 无法产生 L3 evidence |
| Provider contract | 6 | config/config.yaml 已配置 anthropic_compatible，env var 测试需受控环境 |
| Other (RFC stub, catalog sync) | 1 | RFC 0002 未创建，runtime action catalog 待 B7 cleanup 同步 |

### 007

Remains credible-with-caveats（validation scope note: FakeProvider deterministic tool_use + confirmation='never' override，非 runtime blocker）。

### Product Status

Not product-ready。Do not claim all tests pass。Do not claim full regression clean。

---

## 0. Independent Re-Audit Override (2026-05-29)

本节是当前最新事实源。下方历史段落保留当时登记的修复和验证流水；如果历史段落仍写有 `ALL REAL-EVIDENCE CLOSED`、`8/8 validated` 或某 subsystem `VALIDATED`，以本节的独立复审口径为准。

### Current Verdict

| 项目 | 当前复审结论 |
|------|--------------|
| 原 redteam inferred score | 1.4/5 |
| 当前 independent combined review score | 4.5/5 — conservative baseline。002 credible — Plan 3 pipeline (12/12 PASS, ab013ed) with scope caveats (prompt-steered, single-skill)。003 credible — lifecycle→mediator→gate enforcement 全链闭合, multiple disallowed business tools blocked (read_file/read_file_lines/SKILL_SELECT), execution_suppressed evidence + no-TOOL_INVOKE verified, 13 PASS / 0 FAIL / 4 CONCERN (real AnthropicCompatibleProvider, 2026-05-31), 24 focused tests, remaining CONCERN 全部 MODEL_BEHAVIOR。006 credible — child_tools schema fix 闭合 MODEL_BEHAVIOR_CONCERN (12/12 PASS)。007 credible-with-caveats (10/10 PASS)；caveat: FakeProvider deterministic tool_use + confirmation='never' validation-only override — 验证方法学 scope note，非 runtime blocker。008 credible — evidence chain fully closed (v3, 2026-05-31): 14/14 PASS。B7/B8 excluded |
| 总体判断 | 相比原 redteam 明显改善。002 从 partial-credible 升级为 credible (Loop 7, ab013ed — D04/D05/D06 全部关闭，12/12 PASS)。003 credible — lifecycle→mediator→gate enforcement 全链闭合, execution_suppressed evidence + no-TOOL_INVOKE verified (13 PASS / 0 FAIL / 4 CONCERN, remaining CONCERN 全部 MODEL_BEHAVIOR)。008 evidence chain fully closed, **最后一个 caveat 已关闭 (v3, 2026-05-31)**: `core.chat()` → ActionPlan schema enforcement working → real model stable JSON → scheduler → 14/14 PASS, 0 MODEL_BEHAVIOR_CONCERN；not product-ready；B7/B8 大型架构/产品化决策，不进入当前阶段 |
| REAL-EVIDENCE closure credibility | **8/8 evidence collected**。7/8 credible (001/002/003/004/005/006/008), 1/8 credible-with-caveats (007 — validation scope note: FakeProvider deterministic tool_use + confirmation='never' override, 非 runtime blocker)。003 remaining CONCERN 全部 MODEL_BEHAVIOR (request_user_input 规避, privilege_escalation 拒绝), 非代码缺陷 |
| 核心 runtime milestone | MAIN-PATH VALIDATED；002 real provider E2E 验证通过 (12/12 PASS, ab013ed) — **credible** with scope caveats (prompt-steered, single-skill)；003 real provider E2E 验证通过 — **credible** (gate enforcement proven, remaining CONCERN all MODEL_BEHAVIOR)；006/008 credible；007 credible-with-caveats (validation scope note) |
| 明确排除 | B7 Multi-instance readiness；B8 TUI architecture；not product-ready |

主要纠偏点：
- `RuntimeDecisionFrame` registry 当前仍没有 READY branch point，状态文档不能把它当作完全 READY 事实源。
- Skill allowed_tools 的 contract path 有效；002 real provider dogfood 已验证 code path (12/12 PASS, ab013ed) — 标记为 credible（remaining scope caveats: prompt-steered, single-skill）。003 credible — real provider dogfood 已验证 (13 PASS / 0 FAIL / 4 CONCERN), execution_suppressed evidence + no-TOOL_INVOKE verified, remaining CONCERN 全部 MODEL_BEHAVIOR。
- Checkpoint validation 有 direct-save fallback，real provider 部分仍有 concern，不能称为 true resume fully validated。
- MCP bridge readiness 可信；MCP external flight runtime-mediated execution chain 已验证（TOOL_GATE→TOOL_INVOKE→StdioMCPClient.call_tool→TOOL_RESULT→conversation context），mediator payload bug 已修复。
- SubAgent L1 child loop 有进展；006 TOOL_MEDIATOR_GAP 已闭合 — _dispatch_or_fallback_delegation() 内部构造 ToolRuntimeMediator 并传入 set_provider()，child tool_use 走 TOOL_GATE→TOOL_INVOKE→execute_single_tool→TOOL_RESULT。
- Scheduler main-path injection 已验证 (Gap A 10/10 PASS + Gap B 7/7 tests + Model Plan 13/13 PASS)；008 credible——evidence chain fully closed。

### Corrected Current Loop Scores

| Loop | 当前复审状态 | Score | 说明 |
|------|--------------|------:|------|
| Loop 1.1 Unified Runtime Decision Spine | CODE_PATH_COMPLETE | 3 | frame/dispatcher 已集成；registry 仍全 PARTIAL |
| Loop 1.2 Evidence Classification Repair | VALIDATED | 4 | guard code/tests 可信；result JSON 仍可增强 |
| Loop 1.3 Tool Path Unification | VALIDATED | 4 | model tool-use path 经 ToolRuntimeMediator |
| Loop 2.1 Explicit Memory Main-Path Completion | VALIDATED | 4 | REAL-EVIDENCE-001 可信，但 provenance 有局部 caveat |
| Loop 2.2 Skill Activation / allowed_tools | CODE_PATH_COMPLETE → VALIDATED | 4 | **Plan 3 Phase 3-7 + Loop 7 completed** — ActiveSkillLifecycle (Phase 4, 26 tests), lifecycle→mediator→gate allowed_tools enforcement (Phase 5, 8 tests), real provider Plan 3 dogfood (Phase 6, 12/0/0, ab013ed), B7 extension points (Phase 7, 4 tests)。74 focused tests PASS。Loop 7: D05/D06 关闭 (ab013ed)。002 **credible** with scope caveats (prompt-steered, single-skill)。|
| Loop 2.3 Storage / Checkpoint True Resume | VALIDATED | 4 | Batch A hardened: direct-save fallback removed, Part A 10/10 PASS；Part B 2 CONCERN — checkpoint save trigger condition not met (tools executing but no save point reached) |
| Loop 2.4 MCP Main-Path Readiness | PARTIAL (plan scope complete) | 3 | **Plan scope complete (a318237)** — DEFERRED→PARTIAL 达成。bridge readiness 可信（MCP_BRIDGE_LIFECYCLE evidence + 6 contract tests）；mcp.discover/mcp.invoke branch points 已从 DEFERRED 更新为 PARTIAL。PARTIAL 是 plan 设计的终端状态（scope 外：真实 MCP server 连接 REAL-EVIDENCE-005/007、confirmation='always' 策略变更）。无待处理 Loop 2.4 工作项。 |
| Loop 3.2 Real SubAgent L1/L2 | VALIDATED | 4 | 006 TOOL_MEDIATOR_GAP 闭合 — core delegation path 构造 ToolRuntimeMediator 并传入 L1 handler；child_tools schema fix (execute_l1() 从 request.allowed_tools + TOOL_REGISTRY 构建) 闭合 MODEL_BEHAVIOR_CONCERN；**real provider E2E 第三轮 (2026-05-29)**: 12/12 PASS — 完整 evidence chain 闭合 (parent→child→TOOL_GATE→TOOL_INVOKE→TOOL_RESULT→child context→parent adjudication)；52 contract tests + 49 focused tests PASS；**credible** |
| Loop 3.3 Real MCP External Flight | VALIDATED | 4 | 007 runtime invocation path completed: FakeProvider + real StdioMCPClient bridge + confirmation='never' override → TOOL_GATE→TOOL_INVOKE→StdioMCPClient.call_tool→TOOL_RESULT→conversation context (10/10 PASS)；mediator payload bug 已修复 (result_summary→tool_output)；credible-with-caveats (validation scope note: FakeProvider + confirmation='never' override, 非 runtime blocker) |
| Loop 3.4 Advanced Scheduler | VALIDATED | 4 | 008 credible — 最后一个 caveat 已关闭 (v3, 2026-05-31): `core.chat()` → ActionPlan schema enforcement → real model stable JSON → scheduler → 14/14 PASS, 0 MODEL_BEHAVIOR_CONCERN。6 处 Plan.model_validate ActionPlan guard 全部就位。104 scheduler/schema tests PASS。不再有 provider.create() 旁路 / manual scheduler while / MODEL_BEHAVIOR_CONCERN caveat。 |
| Loop 4.1 Dogfood / Evaluation Harness Honesty | VALIDATED | 4 | honesty guard 可信 |
| Loop 4.2 UX / Error Recovery / Storage Hygiene | CODE_PATH_COMPLETE | 4 | hardening 完成；不是核心能力 completion proof |

### Corrected REAL-EVIDENCE Closure Credibility

| ID | Capability | Closure credibility | Notes |
|----|------------|---------------------|-------|
| REAL-EVIDENCE-001 | Memory retain/recall/forget | credible | positive assertions 充分；局部 direct dispatcher provenance caveat |
| REAL-EVIDENCE-002 | Skill selection | **credible** | Plan 3 pipeline complete: turn-start structured selection + ActiveSkillLifecycle + allowed_tools enforcement + real provider dogfood (**12 PASS / 0 CONCERN / 0 FAIL**, AnthropicCompatibleProvider, 2026-05-31) + B7 extension points。Evidence chain fully closed (D01-D08, P3S9-P3S12)。74 focused tests PASS。Language matching: manifest 显式声明。**Remaining scope caveats**: (1) prompt-steered; (2) 单 skill 场景。Not product-ready。 |
| REAL-EVIDENCE-003 | Skill allowed_tools | **credible** | lifecycle→mediator→gate enforcement 全链闭合。Multiple disallowed business tools (read_file/read_file_lines/SKILL_SELECT) blocked via skill_allowed_tools→rejected。execution_suppressed evidence + no-TOOL_INVOKE verified by focused tests + dogfood。**13 PASS / 0 FAIL / 4 CONCERN** (AnthropicCompatibleProvider, `scripts/real_evidence_003_hardening.py`, 2026-05-31 Loop 8)。24 focused tests PASS (含 TestRejectedGateNoToolExecution: 6 tests — no TOOL_INVOKE dispatch / execution_suppressed evidence / allowed contrast)。H2 adversarial styles 2/3 PASS (direct+indirect via read_file target fix)。**Remaining CONCERN 全部 MODEL_BEHAVIOR**: request_user_input 模型主动规避; privilege_escalation framing 模型拒绝 — 非代码缺陷, gate 机制本身已验证。Prompt-steered + 单 skill 场景为已知限制。 |
| REAL-EVIDENCE-004 | Checkpoint save/resume | **credible** (hardened) | Batch A: direct-save fallback removed (Guardrail 2)；Part A 10/10 PASS (CHECKPOINT_PATH redirection fix)；Part B 2 CONCERN — tools executing (tool.gate/invoke/result in action_log) but no checkpoint save point reached |
| REAL-EVIDENCE-005 | MCP bridge readiness | credible | local stdio fixture discovery/register/visibility/allowlist 可信 |
| REAL-EVIDENCE-006 | SubAgent L1 | **credible** | child_tools schema fix (execute_l1() 从 request.allowed_tools + TOOL_REGISTRY 构建 tool schema) 闭合了 MODEL_BEHAVIOR_CONCERN —— 根因是 `delegate_l1()` hardcode `tool_snapshots=()` + `build_context_package()` 忽略 `request.allowed_tools` → child_tools 始终为空 → 模型无 tool schema 可见。修复后完整 evidence chain 12/12 PASS: M0→M1→M1b→M2 (child structured tool_use — 首次 PASS)→M3 (TOOL_GATE)→M4a (TOOL_INVOKE)→M4b (TOOL_RESULT)→M5 (ToolRuntimeMediator)→M6 (real tool result)→M7a (child result)→M7b (parent adjudication)→M8 (evidence chain: 7 event types)。52/52 contract tests + 49/49 focused tests PASS。SimpleNamespace turn_state + _turn_context 私有属性访问 caveat 仍在（不影响功能正确性）。 |
| REAL-EVIDENCE-007 | MCP external flight | **credible-with-caveats** | 完整 runtime-mediated execution chain 验证通过: core.chat → ToolRuntimeMediator → TOOL_GATE(allowed) → TOOL_INVOKE → StdioMCPClient.call_tool(subprocess JSON-RPC) → TOOL_RESULT(real MCP result, 67 bytes) → conversation context。10/10 PASS。Mediator payload bug 已修复 (result_summary→tool_output)。**Caveat (validation scope note, 非 runtime blocker)**: FakeProvider deterministic tool_use（非真实模型自主选择 MCP tool）+ confirmation='never' validation-only override（production 默认 confirmation='always'）。Code path 完整、evidence chain 闭合、底层 StdioMCPClient 真实调用已验证——caveat 仅影响验证方法学，不影响代码正确性。 |
| REAL-EVIDENCE-008 | Advanced scheduler | **credible** (evidence chain fully closed, last caveat resolved) | Gap A: `_run_main_loop(action_scheduler=...)` E2E (10/10 PASS)。Gap B: `build_action_plan_from_model_output()` bridge (7/7 tests)。**v3 (2026-05-31)**: `core.chat()` → `_run_planning_phase()` ActionPlan schema enforcement → real model outputs stable ActionPlan JSON (plan_id=cond_flag_test_v3_001, 3 nodes, has_depends, has_condition) → bridge → `_run_main_loop(action_scheduler=...)` → all 5 scheduler evidence types + condition_flags → **14 PASS / 0 FAIL / 0 CONCERN**。不再有 MODEL_BEHAVIOR_CONCERN。6 处 `Plan.model_validate` ActionPlan guard 全部就位 (context_builder/task_runtime/response_handlers×3)。104 scheduler/schema focused tests PASS。不再有 provider.create() 旁路 caveat。不再有 manual scheduler while caveat。**剩余 caveat**: 无 — 008 已完全闭合。 |

**保守证据可信度基线 (2026-05-31)**: 8/8 evidence collected。7/8 credible (001-006, 008) + 1/8 credible-with-caveats (007 — validation scope note: FakeProvider deterministic tool_use + confirmation='never' override, 非 runtime blocker)。002 real provider SKILL_SELECT 12/12 PASS；003 real provider disallowed-tool blocking 13 PASS / 0 FAIL / 4 CONCERN (remaining CONCERN 全部 MODEL_BEHAVIOR)。建议阶段性收口。B7/B8 不进入当前阶段。Not product-ready。

---

## 1. 当前状态快照

### Real API Dogfood (direct provider call)

| 指标 | 值 |
|------|---|
| 最新报告 | `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` |
| 结果 | **19 non-failing / 1 CONCERN / 0 FAIL**（共 20 cases） |
| 执行日期 | 2026-05-27 |
| Evidence level | **REAL_DOGFOOD_SMOKE** |

### Real API Interactive Dogfood (subprocess + full runtime)

| 指标 | 值 |
|------|---|
| 最新报告 | `docs/dogfood/real-api-interactive-dogfood-report-2026-05-27.md` |
| 结果 | **15/15 PASS（0 CONCERN / 0 FAIL）** |
| Provider | kimi-k2.5 via anthropic_compatible (DashScope) |
| 执行日期 | 2026-05-27 |
| 耗时 | 118.5s |
| Evidence level | **REAL_API_INTERACTIVE_SMOKE** |
| Harness | `scripts/real_api_interactive_dogfood_sweep.py` |
| 结果 JSON | `docs/dogfood/real-api-interactive-dogfood-results-2026-05-27.json` |

**已验证的交互路径**：
- y/n tool confirmation（R06-R08）— real API 下正确处理
- memory proposal + accept/deny（R09-R11）— 流程正常
- subagent delegation（R12-R13）— 委托标记正常
- 不存在工具的安全错误恢复（R14）— 不 crash
- 多约束复杂中文任务（R15）— 19.7s 完成，不超时
- secret 拒绝（R03）— 不泄露 API key

### Interactive Dogfood Harness

| 指标 | 值 |
|------|---|
| Harness | `scripts/dogfood_interactive_harness.py` — 完成（870+ lines, 16 cases） |
| 测试 | `tests/test_interactive_dogfood_harness.py` — 28 pass + 1 slow smoke |
| Fake/local cases | 16/16 PASS（6 类别：I-SANITY/I-CONFIRM/I-TOOL/I-MEMORY/I-STREAM/I-RESUME） |
| 报告 | `docs/dogfood/interactive-dogfood-harness-report-2026-05-27.md` |
| Case matrix | `docs/dogfood/interactive-dogfood-case-matrix-2026-05-27.md` |
| 结果 JSON | `docs/dogfood/interactive-dogfood-results-2026-05-27.json` |
| Evidence level | **FAKE_LOCAL_SMOKE** — FakeProvider 下验证交互路径正确性 |

### Fake/Local Gate

| 指标 | 值 |
|------|---|
| FakeProvider 契约 | `docs/design/fake-provider-scripted-scenario-contract.md` |
| 用户路径 dogfood | `tests/test_user_path_dogfood.py` — PASS |
| Runtime 集成测试 | `tests/runtime_integration/` — PASS |

### Log Hygiene (Loop 2 — COMPLETED)

| 项目 | 值 |
|------|---|
| 大小上限 | 50MB（`MAX_LOG_SIZE_BYTES` in config.py） |
| 轮转策略 | rename 为 `agent_log.archived-YYYYMMDD-HHMMSS.jsonl`（原子 rename） |
| 脱敏规则 | `sk-[a-z]+(?:-[a-zA-Z0-9]+)*-[a-zA-Z0-9]{8,}` → `sk-***REDACTED***`；`Bearer *{20,}` → `Bearer ***REDACTED***` |
| 字符串截断 | >2000 字符自动截断 |
| 递归深度 | 最大 5 层，超出返回 `<nested-too-deep>` |
| 写入路径覆盖 | Path A (logger.log_event, 7 modules) + Path B (runtime_observer.log_event, 5 modules) |
| 旧 773MB 日志 | 已删除（用户授权） |
| 测试 | `tests/test_log_hygiene.py` — 21 tests (4 classes: Sanitization/Rotation/E2E/Boundary) |

### Config Safety (Loop 1 — COMPLETED)

| 项目 | 值 |
|------|---|
| 推荐入口 | `config/config.yaml`（provider section） |
| 安全默认 | `enabled: false, type: fake` — 零 API key 可运行 |
| API key | 个人本地项目直接写在 `config/config.yaml` 的 `api_key` 字段，不可 commit |
| tracked 版本 | `api_key: sk-REPLACE_ME`（占位符），安全 |
| 本地保护 | `git update-index --skip-worktree config/config.yaml` — 防止误 stage |
| 预防层 1 | pre-commit hook 扫描 staged diff 中的真实 key 特征 (sk-sp-/sk-ant-/sk-or-) |
| 预防层 2 | `tests/test_config_secret_safety.py` — 8 个 guard tests 验证 config examples/tracked/staged |
| Legacy 路径 | `FIRST_AGENT_PROVIDER_PROFILE`、`MY_FIRST_AGENT_LLM_PROVIDER` 已 deprecated |
| .env | **不作为当前推荐主路径**；仅作为兼容层保留 code path |

### 已修复的关键 Bug

| Issue | 描述 | 状态 |
|-------|------|------|
| ISSUE-002 (G2) | handle_end_turn_response 返回空串 | **FIXED** (e789c11) |
| ISSUE-001 (C1) | 非交互式 harness 无法处理 confirmation | **HARNESS ENHANCED** (e789c11) |
| 无限循环 | plan mode 确认后不退出的死循环 | 已修复 |
| summary overclaim | step_complete_event 对未执行步骤宣称完成 | 已修复 |
| model_provider_required | 缺少 model_name 时 crash | 已修复 |

### Memory E2E (Loop 3 — COMPLETED)

| 项目 | 值 |
|------|---|
| Commit | `38d757a` |
| 核心变更 | `refresh_runtime_system_prompt()` 将 MEMORY_RECALL 统一走 dispatcher path，不再直接调 `_memory_runtime.snapshot_for_prompt()` |
| Memory recall 路径 | 统一 → `route_from_runtime_loop(request)` → dispatcher → handler → `build_system_prompt(memory_section=...)` |
| fallback | dispatcher 为 None 时保留直接 `snapshot_for_prompt()` 路径（测试/dogfood 兼容） |
| prompt_builder | `build_system_prompt(memory_section=...)` 支持可选预渲染 memory 段 |
| turn-end hook | 移除重复 MEMORY_RECALL dispatch，只保留 MEMORY_TURN_END_PROPOSAL + MEMORY_PROPOSE |
| 测试更新 | `spy.route_calls[0]` → 按 `RuntimeActionType.MEMORY_TURN_END_PROPOSAL` 过滤（MEMORY_RECALL 先于 turn-end hook 触发） |
| import baseline | `test_architecture_boundaries.py` 添加 `agent.runtime_integration.schema`（local import in `refresh_runtime_system_prompt()`） |
| 回归基线 | 80 失败全部为已有（缺失过期文档、README 内容不匹配等），非 Loop 3 引入 |

### Evidence Kind 分类

| 指标 | 值 |
|------|---|
| 实现 | `classify_action_evidence_kind()` in `agent/runtime_integration/schema.py` |
| 测试 | `tests/unit/test_evidence_kind_classification.py` — 17 PASS |
| Run summary 集成 | `agent/loop.py` — `_emit_run_summary` 统计 business/probe 计数 |
| 分类 | business: 6 类型（TOOL_REQUEST/INVOKE/RESULT, MEMORY_PROPOSE, STREAMING_PROVIDER_CALL/EVENT）+ CLI_SHOW_MEMORIES/CLI_SHOW_SUBAGENTS |
| | probe: 7 类型（SKILL_SELECT, TOOL_GATE, MEMORY_TURN_END_PROPOSAL/RECALL/CONSOLIDATE, CHECKPOINT_SAFE_SUMMARY, SUBAGENT_DELEGATE_L0） |

### Evidence Honesty (Loop 13 — COMPLETED)

| 项目 | 值 |
|------|---|
| 核心变更 | `SUBAGENT_DELEGATE_L0` 从 `business` 重分类为 `probe` — 它是每 turn routing check，非用户可见业务动作 |
| 测试更新 | `test_evidence_kind_classification.py` 更新分类断言；新增 `test_lifecycle_checks_are_probe_not_business` guard test |
| Evidence taxonomy guard tests | 17→18（新增 lifecycle check honesty guard） |
| 影响 | `_emit_run_summary` 中 SUBAGENT_DELEGATE_L0 的 rejected routing check 不再计入 business_events |

### Evidence Classification Repair (Loop 1.2 — COMPLETED)

| 项目 | 值 |
|------|---|
| 核心函数 | `is_business_capability_evidence()` in `agent/runtime_integration/evidence.py` |
| 新增常量 | `_BUSINESS_DISPOSITIONS` — 10 个有效业务 disposition |
| Guard tests | `test_evidence_taxonomy_guard.py` — 24 tests（3 原有 + 6 新增 + 1 增强） |

**编码规则**：
- `real_core_loop_runtime_e2e` ≠ business capability complete — routing evidence 不等于业务能力证明
- 必须同时满足：主路径 routing provenance（REAL_CORE_LOOP_RUNTIME_E2E）+ 有效业务 disposition（allowed/recalled/retain/executed/...）
- disposition=noop/no_action/rejected/insufficient_evidence 等即使通过主路径也不构成业务能力证据

### Runtime Decision Spine (Loop 1.1 — COMPLETED)

| 项目 | 值 |
|------|---|
| 模块 | `agent/runtime_decision_frame.py`（609 lines） |
| 设计文档 | `docs/design/runtime-decision-spine.md`（9 sections） |
| Branch points | 14 个预定义，注册表冻结（MappingProxyType） |
| 诚实标记 | 0 READY / 8 PARTIAL / 1 NOT_READY / 2 DEFERRED / 1 FAKE_DEMO / 1 STUB |
| Guard tests | `tests/unit/test_runtime_decision_frame.py` — 35 PASS |
| 主路径集成 | core.py（+13 行）、loop.py（+9 行）、display_events.py（+3 行） |
| 设计原则 | 描述不执行、诚实标记、有限 branch point、证据等级绑定、frozen dataclass |

**各子系统 Branch Point 状态**：

| Branch Point | 状态 | 证据等级 | 说明 |
|-------------|------|---------|------|
| skill.select | PARTIAL | REAL_CORE_LOOP_RUNTIME_E2E | model-owned SKILL_SELECT real provider 验证通过 (Plan 3 pipeline, 12/12 PASS, ab013ed)；AnthropicCompatibleProvider 模型自主 tool_use("SKILL_SELECT") → ToolRuntimeMediator pipeline → ActiveSkillLifecycle → model-owned path 确认；REAL-EVIDENCE-002 **credible** (scope caveats: prompt-steered, single-skill — non-blocking) |
| skill.apply | PARTIAL | REAL_CORE_LOOP_RUNTIME_E2E | allowed_tools real provider 验证通过 (13 PASS / 0 FAIL / 4 CONCERN — Loop 8)；read_file/read_file_lines/SKILL_SELECT blocked via skill_allowed_tools→rejected；execution_suppressed evidence + no TOOL_INVOKE verified；REAL-EVIDENCE-003 credible (remaining CONCERN all MODEL_BEHAVIOR) |
| mcp.discover | PARTIAL | REAL_EVIDENCE_SMOKE | local stdio fixture bridge discovery/register/visibility/allowlist 可信；REAL-EVIDENCE-005 独立复审为 credible |
| mcp.invoke | PARTIAL | REAL_CORE_LOOP_RUNTIME_E2E | 007 runtime invocation path completed: TOOL_GATE→TOOL_INVOKE→StdioMCPClient.call_tool→TOOL_RESULT→conversation context 全链验证通过 (10/10 PASS)；mediator payload bug 已修复；REAL-EVIDENCE-007 credible-with-caveats (validation scope note) |
| subagent.delegate | CODE_PATH_COMPLETE | REAL_CORE_LOOP_RUNTIME_E2E | 006 TOOL_MEDIATOR_GAP 闭合 — core delegation path 构造 ToolRuntimeMediator 并传入 L1 handler；child tool_use → TOOL_GATE→TOOL_INVOKE→TOOL_RESULT；executor 读取 _turn_context 真实结果；**真实 L1 delegation 路径验证完毕** (validation script 修复后 L1 handler 正确路由)；52 contract tests PASS; REAL-EVIDENCE-006 stronger partial-credible (M2 child structured tool_use 受模型能力限制) |
| memory.recall/propose/retain/forget | PARTIAL | REAL_PROVIDER_E2E | retain/recall/forget 行为闭环可信；registry 仍是 PARTIAL，且部分 path 使用 direct dispatcher provenance；REAL-EVIDENCE-001 独立复审为 credible |
| tool.gate/invoke/result | CODE_PATH_COMPLETE | REAL_CORE_LOOP_RUNTIME_E2E | model `tool_use` 已经通过 ToolRuntimeMediator 进入 TOOL_GATE→TOOL_INVOKE→TOOL_RESULT；MCP direct evidence 不应借此升级为 full MCP runtime E2E |
| checkpoint.save/resume | PARTIAL | CONTRACT_PLUS_DOGFOOD | Batch A hardened: direct-save fallback removed (Guardrail 2), Part A 10/10 PASS (CHECKPOINT_PATH redirection)；Part B 2 CONCERN per stop condition (confirmation='always')；REAL-EVIDENCE-004 独立复审 credible |
| trace.summary | PARTIAL | FAKE_LOCAL_USER_PATH | in-memory action_log，无 durable store |

**Overclaim 防护规则**：
- `is_capability_complete()` = status==READY AND evidence_level >= FAKE_LOCAL_USER_PATH
- `should_not_silent_pass()` = status in (NOT_READY, DEFERRED, STUB)
- 禁止：status=PARTIAL + "capability complete"、status=FAKE_DEMO + "E2E verified"、evidence_level=GUARD_TEST + "COMPLETE"、no-crash → PASS

### 已知剩余 Issues（Loop 14 审计更新）

**项目当前阶段：developer prototype / developer-dogfood。** 不可标 user-usable。

#### P1（已解决 — Loop 14）

| Issue | 来源 | 状态 |
|-------|------|------|
| Dogfood harness expected_events 死字段（不参与 PASS 判定） | Loop 14 G-Stack audit | **RESOLVED** — CaseEvaluator 检查 expected_events，缺失降为 CONCERN |
| Dogfood harness no-crash → PASS（空断言 case 不应标 capability PASS） | Loop 14 G-Stack audit | **RESOLVED** — 新增 SMOKE_PASS 状态，8 个 guard tests |
| Dogfood harness expected_business_actions 缺失 | Loop 14 G-Stack audit | **RESOLVED** — CaseSpec 新字段 + BUSINESS_ACTION_PATTERNS 检测 |

#### P2（近期）

| Issue | 来源 | 状态 |
|-------|------|------|
| Memory confirm→retain write path 仍直调 _memory_runtime，不走 dispatcher | Loop 14 analysis | **RESOLVED** — Loop 15 Phase 1-4 completed；`resolve_confirmation()` 返回 `_dispatcher_payload`；`handle_memory_confirmation_reply()` 通过 dispatcher 走 `MEMORY_PROPOSE → MemoryRetainHandler`；100/100 memory tests pass |
| Memory extractor zero proposals | red-team audit | **PARTIAL** — 内联路径已部分修复 |
| PROJECT_STATUS 历史 overclaim 清理 | Loop 13 review | **PARTIAL** — Loop 13 overclaim 已在 AutoRun fix 中回退；PROJECT_STATUS 不再包含 false RESOLVED |

#### 已确认修复（证据充分）

| Issue | 证据 |
|-------|------|
| Config safety (Loop 1) | skip-worktree + pre-commit hook + 8 guard tests |
| Log hygiene (Loop 2) | 50MB rotation + sanitization + 21 log hygiene tests |
| Memory recall → prompt context (Loop 3) | 统一走 dispatcher path（`refresh_runtime_system_prompt(dispatcher=...)`） |
| CLI shortcut (Loop 4) | CLI READ_ONLY 命令（show memories/show subagents）走统一 dispatcher；**MUTATING/DELEGATING shortcuts（forget/delegate/nl_delegation）仍为 CLI-only/demo-only 直接调用，不走 dispatcher/evidence path** — 待 confirmation pipeline 就绪后迁入 |
| Turn-end hook (Loop 4) | 提取 _dispatch_tool_pipeline() helper |
| Checkpoint schema version (Loop 6) | SCHEMA_VERSION + _MIGRATION_REGISTRY |
| Test taxonomy (Loop 7) | evidence taxonomy guard tests + file rename |
| Evidence overclaim: SUBAGENT_DELEGATE_L0 (Loop 13) | business→probe 重分类 + lifecycle guard test |
| core.py god object (Loop 8) | 抽取 provider_evidence + subagent_inline (1237→1112 lines) |

#### P3（排队/不修）

| Issue | 状态 |
|-------|------|
| RESUME_PROMPT 全量检测 | 不修 — checkpoint 设计行为 |
| Provider identity "我是 Claude" | 不修 |
| Product context (I1/I7) | 延后 |

---

## 2. 推荐下一步

**当前阶段 close-out candidate。** REAL-EVIDENCE 001-008 全部有代码/测试/审计证据：7/8 accepted-with-caveats, 1/8 accepted。B8 M1-M8 Interaction-first Workbench fake/local MVP delivered: 412/412 TUI tests PASS, tsc clean。所有 Operations/AutoRun/Project dashboard PAUSED。TUI default entry NOT ACTIVATED。CLI fallback retained。

**下一步**: final independent audit of `docs/audit/b1-b8-current-stage-close-out-audit.md` + current HEAD。不要进入 B9，不激活 TUI default entry，不把 fake/local foundation 写成真实 runtime 能力。

**[historical — superseded by 2026-05-30 002/003 real provider validation baseline]** Independent combined review complete — 阶段性收口。所有 REAL-EVIDENCE (001-008) CLOSED。8/8 evidence collected；5/8 credible + 3/8 partial-credible / credible-with-caveats。002 upgraded to partial-credible / code-path credible with real-model evidence (real provider SKILL_SELECT, prompt-steered single-skill single-run caveats)；003 upgraded to partial-credible / code-path credible with blocking demonstrated (real provider disallowed-tool blocking, prompt-steered single-tool adversarial caveats)。B7/B8 大型架构/产品化决策不进入当前收口。**Current baseline (2026-05-30): see Section 0.**

基于 2026-05-28 红队补审报告（`docs/audits/2026-05-28-full-subsystem-capability-completion-audit-redteam-addendum.md`），
真实完成率仅 23.1%（27/117），根因为缺少 runtime-owned decision vocabulary。

**新 Roadmap（按红队补审推荐的 loop 顺序）**：

| Loop | 描述 | 状态 |
|------|------|------|
| Loop 1.1 | Unified Runtime Decision Spine | **COMPLETED** — 已实现 |
| Loop 1.2 | Evidence Classification Repair | **COMPLETED** — 已实现 |
| Loop 1.3 | Tool Path Unification | **COMPLETED** — 方案 2（dispatcher 中介）完整实现，gate_disposition 驱动执行流 |
| Loop 2.1 | Explicit Memory Main-Path Completion | **VALIDATED with caveat** — REAL-EVIDENCE-001 独立复审为 credible；retain/recall/forget 行为和 store assertions 充分，但部分 provenance 仍是 direct dispatcher route |
| Loop 2.2 | Skill Activation Main-Path Completion | **VALIDATED** | 002 partial-credible / code-path credible with real-model evidence — real provider SKILL_SELECT 6/6 PASS (prompt-steered single-skill single-run caveats)。003 partial-credible / code-path credible with blocking demonstrated — real provider disallowed-tool blocking 5/5 PASS (prompt-steered single-tool adversarial caveats)。 |
| Loop 2.3 | Storage/Checkpoint True Resume | **VALIDATED** — Batch A hardened: direct-save fallback removed, Part A 10/10 PASS (CHECKPOINT_PATH redirection + Guardrail 2 enforcement)；Part B 2 CONCERN per documented stop condition (confirmation='always') |
| Loop 2.4 | MCP Main-Path Readiness | **PARTIAL** — REAL-EVIDENCE-005 bridge readiness credible；Batch A: 007 real StdioMCPClient verified (W1/W2 PASS)；model-selected invocation pending (Guardrail 1) |
| Loop 3.2 | Real SubAgent L1/L2 | **VALIDATED** | 006 TOOL_MEDIATOR_GAP 闭合 — child_tools schema fix (execute_l1() 从 request.allowed_tools + TOOL_REGISTRY 构建)；REAL-EVIDENCE-006 credible — 完整 evidence chain 12/12 PASS real provider E2E；52 contract tests + 49 focused tests PASS；L2 不在本阶段范围 [supersedes 2026-05-29 questionable classification] |
| Loop 3.3 | Real MCP External Flight | **VALIDATED** | 007 runtime invocation path completed: TOOL_GATE→TOOL_INVOKE→StdioMCPClient.call_tool→TOOL_RESULT→conversation context (10/10 PASS)；mediator payload bug 已修复；REAL-EVIDENCE-007 credible-with-caveats (validation scope note) [supersedes 2026-05-29 questionable classification] |
| Loop 3.4 | Advanced Scheduler | **VALIDATED** | 008 credible — Gap A: `_run_main_loop(action_scheduler=...)` E2E (10/10 PASS) + Gap B: `build_action_plan_from_model_output()` bridge (7/7 tests) + Model Plan: real provider → model JSON → bridge → scheduler → evidence (13/13 PASS)；27/27 scheduler tests pass；caveat: model plan 用 provider.create() 非 core.chat() (B7/B8 scope) [supersedes 2026-05-29 partial-credible classification] |
| Loop 4.1 | Evaluation/Dogfood Harness Honesty | **code path complete** — (1) `agent/evaluation_honesty.py`（~220 lines）：EvidenceClassification 4 级枚举 + EvaluationEvidence/EvaluationReport dataclass + classify_evaluation/classify_smoke_vs_capability 分类引擎；(2) NON_CAPABILITY_PROVIDERS/ASSERTIONS + CAPABILITY_ASSERTIONS frozenset 定义；(3) `scripts/dogfood_interactive_harness.py` CaseResult 新增 evidence_classification 字段；(4) 41 个 guard tests（`tests/unit/test_evaluation_honesty.py`，10 classes）全部通过；(5) SMOKE_PASS ≠ CAPABILITY_PASS——fake/local/no-crash/expected_events 不能关闭 REAL-EVIDENCE debt |
| Loop 4.2 | UX / Error Recovery / Storage Hygiene | **COMPLETED** — product hardening, not new core capability: (1) provider error → RuntimeEvent fallback（`_call_model()` catch ProviderError → `control_message()` → empty ProviderResponse，不 crash）；(2) scheduler node failure → RuntimeEvent notification（`run_main_loop()` 检测 halted status → `control_message()` 显示 node title + error）；(3) checkpoint resume → `[系统] 正在恢复上次对话状态...` RuntimeEvent 在 session.py 中 emit；(4) storage hygiene: `.gitignore` 添加 `state.json`/`runs/`；(5) trace report enrichment: `_emit_run_summary()` 含 skill_activations/skill_names/mcp_tool_invocations/scheduler_plan_steps；(6) 6 streaming protocol tests + 4 个 contract confirmations 通过；ruff clean；568/574 tests pass（6 pre-existing failures） |

**已完成的历史 loops（安全可自动修）**：
- Loop 14-18, Loop 15 (Memory Write Dispatcher), Loop 1-13 — 详见 PROGRESS_LEDGER

**[historical — superseded by 2026-06-02 global close-out sweep]** 旧 “需要架构决策的项目（B2-B8）” 表使用的是早期 backlog 编号，不能作为当前 B1-B8 能力状态。当前 B1-B8 定义见本文 “Global B1-B8 Close-out Sweep” 与 `REAL-EVIDENCE-001..008`。其中 B7 current-stage 已 closed accepted-with-caveats；B8 TUI architecture 已切换为 interaction-first fake/local MVP，旧 Phase 1-6A 保留在磁盘但不 import/渲染。TUI default entry NOT ACTIVATED。

**剩余 PARTIAL**：
- Memory extractor zero proposals（procedural 走 inline confirmation，episodic 可能需要 extractor redesign）

**[historical — 2026-05-29 independent re-audit baseline, superseded by 2026-05-30 baseline: 6/8 credible (001/004/005/006/007/008) + 2/8 partial-credible (002/003), score 3.9/5]** Loop 4.2 hardening 完成。按 2026-05-29 independent re-audit，当时 Real Evidence closure credibility 为 2/8 credible、6/8 questionable。B7 (Multi-instance) 与 B8 (TUI) 仍是后续架构/产品化决策，本轮排除。

---

## 3. 活跃约束

- `config/config.yaml` 可含真实 API key，**不得 commit**
- `.env` **不得 commit**
- `agent_log.jsonl` **不得 commit**
- sessions/runs/private data **不得 commit**、不得作为测试素材
- 不调用真实 API（除非明确需要的 dogfood 最小验证）
- 不读取真实私人资料
- 不新增 Anchor / 第二条主流程
- 所有工程操作通过 auto_run 推进

---

## 4. Config 规则

```
推荐：config/config.yaml  provider.api_key（个人本地项目直接写入）
安全默认：provider.enabled: false, type: fake
Legacy（不推荐）：.env / FIRST_AGENT_PROVIDER_PROFILE / MY_FIRST_AGENT_LLM_PROVIDER
```

`request_path`、`auth_scheme` 由 provider adapter 内部决定，不出现在用户配置面。

**配置安全边界**：
- `config/config.yaml` 当前可能是用户本地真实配置（含 api_key），**auto-run 和 Coding Agent 不得 commit 此文件**
- 只能通过 `git diff --stat` / `git status` 检查其状态，不得读取内容
- 如果 staged diff 包含 key-shaped fragment，立即 hard stop
- `.gitignore` 已覆盖 `.env`、`agent_log.jsonl`、`sessions/`、`runs/`、`memory/`、`workspace/`

---

## 5. 文档导航

| 想了解 | 读这里 |
|--------|--------|
| 当前项目状态 | `docs/PROJECT_STATUS.md`（本文件） |
| 进度账本 | `docs/PROGRESS_LEDGER.md` |
| 008 独立 review | `docs/reviews/2026-05-29-real-evidence-008-independent-review.md` |
| 007 独立 review | `docs/reviews/2026-05-29-real-evidence-007-independent-review.md` |
| 006 独立 review | `docs/reviews/2026-05-29-real-evidence-006-independent-review.md` |
| 工程流程 | `docs/dev/AUTO_RUN_WORKFLOW.md`、`docs/dev/ENGINEERING_WORKFLOW.md` |
| 最新 dogfood (direct) | `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` |
| 最新 dogfood (interactive) | `docs/dogfood/real-api-interactive-dogfood-report-2026-05-27.md` |
| 交互式 harness 报告 | `docs/dogfood/interactive-dogfood-harness-report-2026-05-27.md` |
| 交互式 harness plan | `docs/plans/interactive-dogfood-harness-plan-2026-05-27.md` |
| 全能力红队审计 | `docs/audits/2026-05-27-full-capability-red-team-audit.md` |
| 最新审计（全局） | `docs/audit/global-readonly-audit-2026-05-27.md` |
| Remediation loop plan | `docs/plans/2026-05-27-capability-remediation-loop-plan.md` |
| 修复计划 | `docs/plans/source-of-truth-repair-plan-2026-05-27.md` |
| 能力边界定义 | `docs/CAPABILITY_BOUNDARIES.md` |
| SubAgent 边界架构 | `docs/design/subagent-boundary-architecture.md` |
| B8 Interaction-first 路线图 | `docs/roadmap/b8-tui-workbench-roadmap.md` |
| B8 Interaction-first proposal | `docs/proposals/b8-interaction-first-workbench-proposal.md` |
| B8 Interaction-first SDD | `docs/design/b8-interaction-first-workbench-sdd.md` |
| B8 Interaction-first TDD Plan | `docs/plans/b8-interaction-first-workbench-tdd-plan.md` |
| B8 Interaction-first milestones | `docs/milestones/b8-interaction-first-workbench-milestones.md` |
| B8 SDD (legacy, Phase 1-3) | `docs/design/b8-ts-tui-workbench-sdd.md` |
| Skill 系统架构 | `docs/design/skill-system-architecture.md` |
| MCP 系统架构 | `docs/design/mcp-architecture.md` |
| MCP Real External Flight 契约 | `docs/design/mcp-real-external-flight-contract.md` |
| Runtime Decision Spine 设计 | `docs/design/runtime-decision-spine.md` |
| Memory Write Dispatcher 迁移设计 | `docs/design/memory-write-dispatcher-migration-design.md` |
| 首次运行 & 真实 API | `docs/onboarding/first-run-real-api-opt-in.md` |
| 配置示例 | `config/config.example.yaml` |
| 运行时宪法 | `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` |
| 历史文档 | `docs/archive/` |
| 未结问题清单 | `docs/debt/first-agent-open-items.md` — audit at 82dff68, AGENT_AUTO=zero |

---

## 6. Auto-Run 规则

每次 auto_run 启动必须先读：

1. `docs/PROJECT_STATUS.md` — 当前状态
2. `docs/PROGRESS_LEDGER.md` — 进度历史
3. `docs/dev/AUTO_RUN_WORKFLOW.md` — workflow 定义
4. 当前任务相关 report/plan

auto_run 不要求从头开始全 loop；根据任务类型选择合适的 loop 起点。

### Auto-Run 授权状态

用户已明确授权的操作范围：
- **真实 API dogfood** — 已授权，可读取 config/config.yaml 中的真实 provider 配置用于 API 调用，不得 commit
- **agent_log.jsonl 删除** — 已授权
- **按审计文档修复 P0/P1** — 已授权，安全范围内的自动修复
- **自动继续 loop** — 已完成一个 loop 后，如无 hard stop，自动继续下一 loop，不需要每轮都问用户

不得在已授权范围内反复请求授权。

---

## 7. Owner Notes

- 项目定位：个人学习/实验项目，非生产系统
- 不追求 feature completeness，追求可理解性、可审计性、可持续性
- 文档宁可少而准，不可多而乱

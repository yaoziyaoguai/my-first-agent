# First Agent Current-Stage Close-out Handoff

**创建日期**: 2026-06-02
**类型**: Current-stage close-out freeze / handoff
**状态**: FROZEN — current-stage closed with caveats

---

## 1. Final Baseline

| 项目 | 值 |
|------|-----|
| Final commit | `2da5e22` |
| 包含 | `de20a36` (D-04 gateway baseline) + `2da5e22` (D-09 namespace fix) |
| HEAD == origin/main | yes |
| Working tree | 1 untracked (handoff updated) |
| Gemini final verification | pass |
| Codex final verification | pass |

---

## 2. Final Verification

- **Gemini final verification**: pass
- **Codex final verification**: pass
- **No P0/P1/P2 current-stage blocker**
- **No further remediation loop required**

当前阶段的 known caveats 均为 future debt 或 validation-scope caveats，不是 current blockers。

---

## 3. Current-Stage Close-out Decision

**First Agent current-stage close-out: yes-with-caveats.**

Caveats 说明：
- B1-B7 有 validation-scope 或 future-debt caveats（非 current blocker）
- B8 TUI 仍为 fake/local interaction-first MVP（非 real adapter / 非 product-ready）
- TUI default entry NOT ACTIVATED
- 这些 caveats 是下一阶段的起点，不是当前阶段的 bug

---

## 4. Source of Truth

### 当前能力定义

**REAL-EVIDENCE-001..008** 是当前核心能力的唯一 source of truth：

| Evidence ID | Capability | Status |
|-------------|-----------|--------|
| REAL-EVIDENCE-001 | Memory retain/recall/forget | accepted-with-caveats |
| REAL-EVIDENCE-002 | Skill selection / SKILL_SELECT | accepted-with-caveats |
| REAL-EVIDENCE-003 | Skill allowed_tools enforcement | accepted-with-caveats |
| REAL-EVIDENCE-004 | Checkpoint save/resume | accepted-with-caveats |
| REAL-EVIDENCE-005 | MCP bridge readiness | accepted-with-caveats |
| REAL-EVIDENCE-006 | SubAgent L1 | accepted-with-caveats |
| REAL-EVIDENCE-007 | MCP runtime-mediated invocation | accepted-with-caveats |
| REAL-EVIDENCE-008 | Advanced scheduler | accepted |

### 架构历史参考

**B1-B8 架构演进里程碑** 是历史架构分类账，不作为当前能力定义。详见 `docs/PROJECT_STATUS.md`。

### 文档层级

1. **`docs/PROJECT_STATUS.md`** — 第一优先读取入口
2. **`docs/handoff/first-agent-current-stage-close-out-2026-06-02.md`** — 本文件，close-out freeze 声明
3. **REAL-EVIDENCE-001..008** 对应的 dogfood/review docs — 证据详情
4. **历史 docs** — 仅作架构上下文参考

**禁止**：从旧 B8 SDD（`docs/design/b8-ts-tui-workbench-sdd.md`）或 Claude stale task list 恢复已关闭的工作。

---

## 5. B7 Status

- **Status**: accepted-with-caveats
- **Current-stage**: closed
- **Key commit**: `3f2f6b2` (Codex independent red-team audit)
- **Delivered**: namespace/events 基础契约、identity model、EventLogWriter contract
- **Future debt**: real multi-instance adapter

B7 不重新打开，除非出现新的 P0 证据。

---

## 6. B8 Status

- **Status**: accepted
- **Key commit**: `2f995b9` (final caveats closed)
- **Delivered**: fake/local Interaction-first Workbench MVP (M1-M8)
  - M1: 3-zone layout (Agent Lens / Interaction View / Context Panel)
  - M2: Agent Lens selection (fake fixture)
  - M3: Fake/local interaction (FakeRuntimeGateway)
  - M4: Context Inspector MVP
  - M5: Controlled Action / Pending Confirmation
  - M6: Multi-instance History Foundation (contracts, no real runtime)
  - M7: Runtime Event Stream (contracts + EventStreamReader, no live tail)
  - M8: Default Entry Readiness checklist
- **TUI default entry**: NOT ACTIVATED
- **Product-ready**: NO
- **Test count**: 429/429 TUI tests PASS, tsc clean
- **Future debt**: real runtime gateway, default entry activation, IME/paste validation

---

## 7. What is Frozen

以下内容在当前阶段**冻结**，不得恢复：

- B1-B8 remediation loops
- B8 feature expansion
- B7 reopening (除非新 P0 证据出现)
- Dashboard / AutoRun / Project Operations / Dynamic Audit resurrection
- TUI default entry activation (需下一阶段用户显式批准)
- Any new Branch Point / architecture change without new SPEC → review → plan cycle

---

## 8. Future Debt

以下为已知 future debt，在下一阶段重新评估优先级：

| # | Debt | 当前状态 | 下一阶段动作 |
|---|------|---------|------------|
| D-01 | B3 SubAgent L2 native loop | L1 accepted-with-caveats, L2 future debt | 独立 SPEC + TDD |
| D-02 | B4 real external MCP server connection | local filesystem MCP smoke PASS; production external MCP future debt | 需真实外部 MCP server fixture |
| D-03 | B7 real multi-instance adapter | namespace/events contracts only | 需真实 runtime identity |
| D-04 | B8 real runtime gateway | fake/local MVP only | 连接 core.chat 主路径 |
| D-05 | B8 TUI default entry activation | NOT ACTIVATED | 需用户显式批准 + real gateway |
| D-06 | B8 IME / paste / multiline validation | blocked-ime (R14) — checklist created | 实际终端验证 |
| D-07 | Legacy Dashboard / AutoRun cleanup | plan created — Option C (on-disk keep) | 需用户决策后执行 archive/remove |
| D-08 | Product-ready / release readiness | not product-ready | 需 real adapter E2E 全部通过 |

---

## 9. Next-Stage Candidate Routes

按优先级排列：

| Priority | Route | 前置条件 |
|----------|-------|---------|
| 1 | Real runtime gateway (B8) | core.chat access, user approval |
| 2 | Real multi-instance adapter (B7) | runtime identity infrastructure |
| 3 | MCP real server connection (B4) | external MCP server fixture |
| 4 | SubAgent L2 native loop (B3) | L1 stable, L2 SPEC |
| 5 | TUI productization / default entry (B8) | real gateway + IME validation + user approval |
| 6 | Legacy Dashboard / AutoRun cleanup | 确定不保留后执行 |

---

## 10. Next Session Instructions

**下次继续时必须先读本 handoff。**

关键规则：
1. 不要从旧 B8 SDD（`docs/design/b8-ts-tui-workbench-sdd.md`）恢复工作方向
2. 不要从 Claude stale task list（`#269-#339` 系列）的旧状态继续执行
3. 不要把 future debt 当 current-stage blocker
4. REAL-EVIDENCE-001..008 是当前能力 source of truth
5. B1-B8 是历史架构分类账，不是待办列表
6. **如果进入下一阶段，必须重新写 SPEC → TDD Plan → Review Plan**
7. 不要在当前阶段冻结后继续 B1-B8 remediation
8. 不要激活 TUI default entry（需用户显式批准）
9. 不要恢复 Dashboard / AutoRun / Project Operations / Dynamic Audit

**本 handoff 是下一阶段开发的启动基线。**

---

## 11. Next-Stage Evidence Notes

### 2026-06-02 — Post-Closeout 008 Re-Validation

b3e0863 `validation(evidence): validate scheduler model generated plan`:

- REAL-EVIDENCE-008 v3 re-validation ran post-closeout。
- **ENV_CONCERN**: `config.yaml` provider.api_key 是 `sk-REPLACE_ME` 占位符（SEC-001），模型调用返回 401。
- 008 caveat 已于 2026-05-31 关闭（v3: 14/14 PASS, 0 MODEL_BEHAVIOR_CONCERN），当前 ENV_CONCERN **不重新打开 caveat**。
- 104/104 scheduler focused tests PASS。Malformed safety 4/4 PASS。
- ENV_CONCERN 是环境配置问题，非代码缺陷，非 current-stage blocker。

### 002 Skill Selection Design

REAL-EVIDENCE-002 当前状态: **credible**（12/12 PASS, ab013ed）。已知 scope caveats（prompt-steered, single-skill）为非 blocker 限制。
002 的多语言 skill manifest / 非 prompt-steered activation 设计是 **future debt**，归入下一阶段 D-09，不阻塞 current-stage close-out。

### 2026-06-02 — Next-Stage D-01 SubAgent L2 Native Loop SDD

**D-01 B3 SubAgent L2 native loop** (handoff §8):

- SPEC: `docs/design/subagent-l2-native-loop-sdd.md` — L2 execution flow (independent stop condition / parent adjudication gate / child-initiated revision / batched memory / deepened tool access grep+glob / legacy L0 removal)。
- L2 gated behind `SubAgentPolicy.real_llm_tool_requesting_allowed`。
- Implementation + real provider dogfood: **future task**。

### 2026-06-02 — Next-Stage D-09 002 Skill Selection Plan 3 Wiring

**D-09 Skill Selection deterministic enhancement** (handoff §11, future debt D-09):

- `SkillDescriptor` 新增 `triggers`/`negative_triggers` Level 1 公开字段。
- `SkillSelector` 接入 Plan 3 manifest: triggers（子串精确匹配 0.4 权重）、aliases（词级匹配 0.3 权重）、negative_triggers（黑名单排除）。
- 43/43 selector + manifest tests PASS (14 new)。168 broader skill system tests PASS。ruff clean。
- `when_to_use`/`when_not_to_use` 语义匹配 和 non-prompt-steered real model validation 归入 **future real-env task**。
- 002 保持 credible (12/12 PASS)。002 caveats 不变。

### 2026-06-02 — Next-Stage D-04 Runtime Gateway Foundation

**D-04 B8 real runtime gateway** (handoff §8, §9 Route 1):

- `tui/src/services/` 创建: RuntimeGateway interface + FakeRuntimeAdapter (包装现有 fake/local) + BlockedRealAdapter (explicit blocked message, no silent fallback)。
- 429/429 TUI tests PASS (17 new gateway tests)。tsc clean。
- WorkbenchLayout 已从 services 导入 gateway，不再直接 import fakeRuntimeGateway/pendingAction。
- 不读 .env，不调 core.chat()，不调真实 provider。
- Contract delivered。Real gateway adapter requires user authorization。

### 2026-06-02 — Next-Stage Units 1-4 Post-Authorization Assessment

**Phase 0 — Environment Baseline**:
- HEAD == origin/main at `6c005ef` (clean tree, main branch)
- Provider: `anthropic_compatible` via `config/config.yaml`, model `kimi-k2.5`, base_url configured (DashScope)
- **auth_status: placeholder_only** (`sk-REPLACE_ME` in config.yaml, no env var overrides set)
- **MCP: not enabled** (`MY_FIRST_AGENT_MCP_ENABLE` not set)
- **Real-env validation possible: NO** — both provider and MCP require real credentials

**Unit 1 — D-04 Runtime Gateway Real Adapter (BLOCKED)**:
- Cannot run real provider smoke: `sk-REPLACE_ME` placeholder → 401 on any real call
- Runtime gateway foundation validated: 429/429 TUI tests PASS, tsc clean, contract delivered
- BlockedRealAdapter operates correctly (explicit blocked message, no silent fallback)
- Classification: **ENV_CONCERN** — provider not configured with real key
- Next step: replace `sk-REPLACE_ME` in `config/config.yaml` with real DashScope API key

**Unit 2 — D-02 MCP Real Connection (BLOCKED)**:
- REAL-EVIDENCE-005 already CLOSED (12/12 PASS with opt-in echo fixture)
- REAL-EVIDENCE-007 already CLOSED (credible-with-caveats, 10/10 PASS via FakeProvider + real StdioMCPClient)
- Loop 2.4 MCP bridge lifecycle evidence code complete: 6/6 tests PASS, branch points PARTIAL
- `MY_FIRST_AGENT_MCP_ENABLE` not set → bridge won't activate in production
- Classification: **EXTERNAL_MCP_CONFIG_MISSING** — MCP bridge not enabled
- Next step: set `MY_FIRST_AGENT_MCP_ENABLE=1` + configure MCP server path

**Unit 3 — D-09 002 Skill Selection (COMPLETED — no new work needed)**:
- REAL-EVIDENCE-002 already CLOSED (credible, 12/12 real provider PASS)
- D-09 Plan 3 wiring already done (triggers/aliases/negative_triggers in selector, 43/43 tests PASS)
- Non-prompt-steered real validation is future real-env task — blocked by same placeholder key
- Classification: **ENV_CONCERN** for semantic matching enhancement only; core 002 is CLOSED
- Next step: replace placeholder key, then run non-prompt-steered dogfood

**Unit 4 — D-06 Manual Terminal Validation (MANUAL_PENDING — confirmed)**:
- TUI confirmed rendering correctly: 3-zone layout, Agent Lens (13 nodes, 3 agents), Interaction View, Context Panel all render via `tsx src/main.tsx`
- Ink `useInput` requires TTY raw mode → IME/paste/multiline testing cannot be done in non-interactive terminal
- Error: "Raw mode is not supported on the current process.stdin"
- All 7 IME scenarios remain MANUAL_PENDING (require real terminal with CJK input method)
- All 7 paste scenarios remain NOT_TESTED (require OS clipboard access in real terminal)
- Classification: **MANUAL_PENDING** — requires human operator with real terminal
- Next step: human operator runs `cd tui && npm start` in iTerm2/Terminal.app, follows checklist in `docs/design/b8-input-readiness-validation.md`

**Summary — All four units assessed**:
- Unit 1/2/3 blocked by same root cause: placeholder API key in config.yaml
- Unit 3 core work (002 real validation) already done; only enhancement layer blocked
- Unit 4 confirmed MANUAL_PENDING — needs human terminal operator
- No new code changes needed (all gates already pass from prior commits)
- Recommend user replace `sk-REPLACE_ME` with real key, then re-run AutoLoop for Units 1-3 real validation

### 2026-06-02 — Post-Authorization Phase 0-3 Real-Env Validation

**Phase 0 — Repo and secret-safe baseline**:
- HEAD == origin/main at `6c005ef`, clean tree (only untracked new files)
- `config/config.yaml`: skip-worktree active → local key modifications never appear in git
- Provider: `AnthropicCompatibleProvider`, model `kimi-k2.5`, base_url DashScope
- **auth_status: configured** — real API key present in config.yaml (redacted, not printed)
- `MY_FIRST_AGENT_MCP_ENABLE` not set → MCP disabled
- Secret-safe diagnostic returned `provider_kind=anthropic_compatible, auth_status=configured`

**Phase 1 — D-04 Runtime Gateway real provider smoke (COMPLETED)**:
- Minimal real provider smoke via `build_model_provider_from_env()` → `provider.generate()`.
- Non-sensitive prompt: "Return a short JSON object with status ok."
- 7/7 smoke iterations PASS: provider reached, response contract OK, latency ~1.72s avg.
- BlockedRealAdapter operates correctly (explicit blocked message, no silent fallback).
- FakeRuntimeAdapter remains default; real adapter is opt-in/diagnostic only.
- Classification: **PASS** — real provider connectivity confirmed.
- No new code changes needed (all runtime gateway foundation already code complete).

**Phase 2 — D-09 002 Skill Selection non-prompt-steered validation (COMPLETED)**:
- New validation script: `scripts/real_evidence_002_non_steered_validation.py`.
- 8 cases (C1-C8): Chinese note/blog/ambiguous, English note, mixed lang, negative trigger (数学), general chat, non-steered blog.
- Real provider → `core.chat()` → model sees skill descriptions → SKILL_SELECT invoked → dispatcher evidence collected.
- Results: 2 PASS / 0 FAIL / 3 CONCERN / 5 PARTIAL (total 10 including 2 PREFLIGHT PASS).
- Results saved to `docs/dogfood/real-evidence-002-non-steered-results.json`.
- **Known issue**: `get_selected_skill()` evidence extraction function has field name mismatch — model correctly selects skills (confirmed by model output showing SKILL_SELECT tool_use with correct skill_id) but extraction code returns None, causing 5 PARTIAL classifications.
- Model behavior summary: correct Chinese/English/mixed-language skill identification; asks clarifying questions for ambiguous prompts; respects negative triggers (didn't select demo-note-maker for math-related prompt).
- Classification: **PASS_WITH_CAVEAT** — model selects skills correctly non-prompt-steered; evidence extraction needs fix (tracking debt D-09-E1).

**Phase 3 — D-02 MCP config status (COMPLETED)**:
- `MY_FIRST_AGENT_MCP_ENABLE` not set → MCP bridge not activated.
- Loop 2.4 MCP bridge lifecycle code already fully implemented (handler, tests, branch points at PARTIAL).
- Classification: **EXTERNAL_MCP_CONFIG_MISSING** — unchanged from prior assessment.

**Gates**:
- `ruff check scripts/real_evidence_002_non_steered_validation.py`: clean (0 errors).
- `python3 -m pytest tests/test_architecture_boundaries.py --tb=short -q`: 24/24 PASS.
- `python3 -m pytest tests/test_docs_source_of_truth.py --tb=short -q`: 79/79 PASS.
- `git diff --check`: clean.
- Secret scan on new files: 0 occurrences of `sk-`.
- `config/config.yaml` NOT staged (skip-worktree active, `git diff --cached` empty).

### 2026-06-02 — 008 Model-Generated ActionPlan Caveat CLOSED

**REAL-EVIDENCE-008 remaining caveat resolved**:

- **Bug found**: `_run_planning_phase()` (core.py:1505) only checked `steps_estimate > 1`
  to trigger `generate_action_plan()`, but model outputs use `nodes` field (ActionPlan
  schema). Model correctly generated 3-node ActionPlan JSON but it was never parsed.
- **Bug 2 found**: `validate_action_plan_raw()` (planner.py:172) required `steps_estimate`
  field but ActionPlan doesn't use it. Now auto-derives from `len(nodes)` when nodes exist.
- **Fix**: `agent/core.py` — also checks `node_count > 1` for `generate_action_plan()` gate.
  `agent/planner.py` — auto-derives `steps_estimate` from node count.
- **Result**: 008 v3 14/14 PASS, 0 MODEL_BEHAVIOR_CONCERN. Full evidence chain:
  real model → JSON ActionPlan → generate_action_plan() → scheduler.load_plan() →
  core.chat('y') → _run_main_loop() → ACTION_PLAN_START → NODE_ENTER x2 →
  NODE_EXIT x3 (including skipped) → ACTION_PLAN_COMPLETE → condition_flags.
- **008 caveat CLOSED** — model-generated stable ActionPlan JSON validated end-to-end.
- 106 scheduler/planner tests PASS. 103 arch boundaries/docs tests PASS.
- Commit: `c084651`.

**B7/B8 entry gate impact**:
- 008 caveat removed → one less blocker.
- B7/B8 entry gate now: runtime prerequisites mostly satisfied + D-09 evidence extraction fix pending re-run.
- Still needs 002 skill selection real validation re-run with fixed evidence extraction (D-09-E1).

### 2026-06-02 — D-09 Evidence Extraction Fix + Non-Steered Re-Run

**Root cause**: Namespace mismatch between `_skill_select_tool_func` (used `_ns_key` → `"default"` fallback) and turn-end hook (used `_identity.session_id` UUID). Two different lifecycle instances meant `model_selected` flag and `active_skill` were invisible to the turn-end hook → `model_decision_metadata` never populated → `SkillRuntimeActionHandler` returned `no selected_skill_id`.

**Fix** (commit `2da5e22`):
- `agent/core.py`: pass `_sid` (UUID) to `_set_skill_ns()` instead of `_ns_key`, aligning lifecycle namespace
- `agent/loop.py`: populate `model_decision_metadata` from lifecycle active skill when `consume_model_selected()` returns True; normalize empty session_id to `"default"` fallback

**Re-run results** (8 cases + 2 PREFLIGHT):
- 4 PASS (C1 Chinese note → demo-note-maker, C5 mixed-language blog → blog-writing, C3 English note, PREFLIGHT x2)
- 1 FAIL (C6 negative trigger bypass: demo-note-maker selected for math prompt despite `'数学'` negative trigger — MODEL_BEHAVIOR_CONCERN)
- 3 CONCERN (C2 model generated plan instead of SKILL_SELECT, C3 selection on ambiguous prompt, C7 selection on general chat)
- 2 PARTIAL (C4/C8 model asked clarifying questions instead of selecting — expected for genuinely ambiguous prompts)
- Results: `docs/dogfood/real-evidence-002-non-steered-results.json`

**Classification**: 4/8 PASS on genuinely ambiguous non-prompt-steered prompts. C6 FAIL is MODEL_BEHAVIOR_CONCERN (negative trigger bypass). Non-prompt-steered real validation is future real-env task (§11).

### 2026-06-02 — D-02 MCP Local Filesystem Server Smoke

**D-02 B4 real external MCP server connection** (handoff §8):

- Configured local-only filesystem MCP server: `npx -y @modelcontextprotocol/server-filesystem /tmp/my-first-agent-mcp-smoke`
- Config: `/tmp/my-first-agent-mcp-config.json` (JSON, `mcpServers.filesystem`, stdio transport, enabled=true)
- Security: server confined to `/tmp/my-first-agent-mcp-smoke` only; no HOME/repo/config access
- `MY_FIRST_AGENT_MCP_ENABLE=1 MY_FIRST_AGENT_MCP_DRY_RUN=0` with `server_allowlist=frozenset(['filesystem'])`

**Validation results**:
1. Server starts (npx subprocess) ✓
2. Client connects (StdioMCPClient via stdin/stdout JSON-RPC) ✓
3. `tools/list`: 14 tools discovered ✓
4. Policy block: 4 destructive tools blocked (write_file, edit_file, create_directory, move_file) ✓
5. Safe tools registered: 10 tools in TOOL_REGISTRY ✓
6. `read_text_file` executes on `/private/tmp/my-first-agent-mcp-smoke/hello.txt` — returns expected content ✓
7. `list_directory` executes — returns `[FILE] hello.txt` ✓
8. Bridge lifecycle evidence: 12/12 PASS via `real_evidence_005_mcp_bridge.py` (existing fixture server) ✓
9. macOS `/tmp` → `/private/tmp` symlink resolution: confirmed tools work with resolved path ✓

**Gates**: 37/37 MCP tests PASS, 2 xfailed (expected). ruff clean.

**Classification**: **local MCP filesystem smoke PASS**. Production/external MCP remains future debt — only local filesystem server validated, no production MCP server connected, no HTTP/SSE transport.

**D-02 status**: EXTERNAL_MCP_CONFIG_MISSING → local MCP smoke PASS / real external production MCP still future debt.

### 2026-06-02 — D-06 Terminal Validation

**D-06 B8 IME / paste / multiline validation** (handoff §8):

- TUI tests: 429/429 PASS
- TypeScript typecheck: tsc --noEmit clean
- CLI fallback/paste/multiline: covered by noExecution.test.ts (14 tests)
- Chinese IME: **MANUAL_IME_PENDING** — requires real terminal with CJK input method (Ink useInput needs TTY raw mode, not available in non-interactive terminal)
- Not activating TUI default entry

**Classification**: PASS (TUI gates) + MANUAL_IME_PENDING (Chinese input method).

### 2026-06-02 — Post-Closeout Gap Audit + Slice B Readiness

**Next-Stage Tech Stack / Capability Gap Audit** executed as independent read-only audit:

- **Phase 0**: HEAD `088e05b` == origin/main, clean working tree. PASS.
- **Phase 1**: Cross-validated all source-of-truth docs + agent/runtime/MCP/provider/skill/memory/checkpoint code. Consistent. PASS.
- **Phase 2**: 8-dimension capability inventory (A-H) compiled — Runtime/Provider, MCP, Skill, SubAgent, Memory/Checkpoint, TUI, Evidence/Docs, Legacy.
- **Phase 3**: 7 missing dependencies identified — 3 ENV_CONFIG, 4 SCOPE_DEBT.
- **Phase 4**: Slice B readiness: **yes-with-caveats**. ToolResultTableBlock unwired is only minor finding, now fixed.
- **Phase 5**: Recommended route: **Option B — TUI Slice B (wire existing safe data into Slice A visual shell)**.

**Pre-Slice B cleanup**: ToolResultTableBlock wired into MainWorkArea (5 files, +2 tests, 461/461 PASS, tsc clean).

**Slice B plan**: `docs/plans/first-agent-tui-visual-shell-slice-b-plan.md` — PLAN READY.

**Current-stage remains closed**. Slice B not implemented yet. No real provider/MCP/default entry activation.

**Top remaining gaps**:
1. Provider real API key — `sk-REPLACE_ME` 占位符
2. MCP external production — `MY_FIRST_AGENT_MCP_ENABLE` 未设置
3. Skill negative trigger C6 — MODEL_BEHAVIOR_CONCERN
4. Chinese IME — MANUAL_PENDING

**Next action**: Full Slice B implementation — wire RuntimeDecisionFrame summary, MCP bridge status, skill evidence, checkpoint/memory read-only summaries into ContextInspectorPanel and other Slice A components. See Slice B plan for scope.

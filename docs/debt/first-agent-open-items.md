# First Agent — Unresolved Open Items

**创建**: 2026-06-02
**Current baseline**: `d3a73ca` — `fix(release): clear v1 code bugs in evidence taxonomy and LLM extractor provider isolation`
**Independent audit**: 82dff68 reliable baseline — yes。P0/P1/P2 blocker: no。Secret leak: no。AGENT_AUTO tasks: zero。

---

## 1. Audit Conclusion

对 `82dff68` 进行独立审计后确认：

- **AGENT_AUTO tasks: zero** — 所有可自动修复项已完成
- **current-stage remains closed: yes** — 不重新进入 B9
- **Another automatic remediation loop: no** — 剩余全部为不可自动修复的分类

以下未结项不应进入自动修复循环，应按所属类别等待对应 owner 决策或后续专项工程。

---

## 2. Open Items by Owner

### 2.1 MODEL_BEHAVIOR_CONCERN

模型行为导致的问题，非当前代码 bug。不应通过代码修补来"修复"模型行为。

| ID | Issue | Detail | Evidence |
|----|-------|--------|----------|
| MBC-001 | 002 C6 negative trigger bypass | demo-note-maker 被选中，尽管 prompt 含"数学"（negative trigger）。模型 owned SKILL_SELECT 路径绕过确定性 selector 的 negative_triggers 排除。 | `docs/dogfood/real-evidence-002-non-steered-results.json` — C6: FAIL |
| MBC-002 | 002 C3 over-eager selection | 模糊 prompt "帮我写点东西" 触发 SKILL_SELECT。模型在没有明确 skill 需求时过度主动。 | `docs/dogfood/real-evidence-002-non-steered-results.json` — C3: CONCERN |
| MBC-003 | 002 C7 over-eager selection | 闲聊 "你好，请问今天是什么日期？" 触发 SKILL_SELECT。模型将无 skill 意图的对话误判为 skill 请求。 | `docs/dogfood/real-evidence-002-non-steered-results.json` — C7: CONCERN |
| MBC-004 | 003 OTHER_GATE vs skill_allowed_tools→rejected | Disallowed tools 走 OTHER_GATE 而非 skill_allowed_tools→rejected。模型行为变化：不再主动尝试 disallowed tools。代码路径已验证 (Loop 8: 13/0/4 PASS)。无安全风险 (R35: no side effect)。 | `docs/dogfood/real-evidence-003-hardening-results.json` — 13 CONCERN |

**Why not auto-fixed now**: 这些是模型行为层面的问题，不是代码逻辑缺陷。确定性 negative_triggers selector (43/43 PASS) 和 skill_allowed_tools gate 机制 (Loop 8: 13/0/4 PASS) 均已正确工作。模型 SKILL_SELECT 路径和 tool 选择行为由模型自身决定。

**Recommended route**: Skill / Tool behavior hardening SPEC → TDD → Review。专项设计包括：
- 模型 SKILL_SELECT 前的 deterministic pre-filter
- no_skill threshold 调整
- 模型行为与确定性 gate 的交互契约

### 2.2 USER_MANUAL_TRIAL

需要用户在真实终端环境中试用的项目。

| ID | Issue | Detail |
|----|-------|--------|
| UMT-001 | Chinese IME validation | Ink useInput 不支持 composition 事件自动化。需用户在 iTerm2/Terminal.app + 中文输入法环境下验证 composing/text-update/commit 阶段。 |
| UMT-002 | Paste / multiline | 需真实终端粘贴中文/英文/mixed/特殊字符/multiline 块。 |
| UMT-003 | Terminal real interaction | 覆盖 IME + paste + multiline 组合场景。 |

**Why not auto-fixed now**: Ink 框架不提供 compositionstart/compositionupdate/compositionend 事件，自动化测试无法覆盖 IME 组合态。真实终端行为与 CI 环境有差异。

**Trial guide**: `docs/manual-trials/first-agent-user-trial-guide.md` — 逐步骤手动试用操作手册，含 result log template、evidence policy、回填流程。

**Recommended route**: 用户在真实终端中参照 `docs/design/b8-input-readiness-validation.md` checklist + `docs/manual-trials/first-agent-user-trial-guide.md` 逐项验证。

### 2.3 PRODUCT_DECISION

需要用户产品决策的项目。

| ID | Issue | Detail | Options |
|----|-------|--------|---------|
| PD-001 | TUI default entry activation | `main.tsx` 当前默认入口是 `WorkbenchLayout`，`TuiShell` 仅 component-level export。激活 TUI 默认入口需要用户决策。 | A) 保持 CLI fallback + TuiShell component export；B) 切换到 TuiShell 为默认入口 |
| PD-002 | D-04 real gateway adapter | `BlockedRealAdapter` 已创建，`FakeRuntimeAdapter` 已接入。是否接入真实 `core.chat()` 路径需用户决策。 | A) 保持 fake/local；B) 接 real gateway (需 provider + MCP 配置) |
| PD-003 | Legacy Dashboard / AutoRun cleanup | 32 active files + 54 legacy files。当前 Option C: on-disk keep + header comment。 | A) Full remove / B) Archive / C) On-disk keep (推荐) |

**Why not auto-fixed now**: 这些决策影响产品方向和架构结构，不能由 Agent 自动决定。

### 2.4 FUTURE_DEBT / REAL_ENV_REQUIRED

未来阶段债务，不阻塞当前 close-out。

| ID | Issue | Detail |
|----|-------|--------|
| FD-001 | Production / external MCP server | 当前仅 local filesystem MCP smoke (DONE)。production MCP 需用户配置外部 server。 |
| FD-002 | Memory extractor zero proposals | Episodic memory extractor 对某些输入产生 0 proposals。需 extractor redesign。 |
| FD-003 | when_to_use / when_not_to_use semantic matching | Plan 3 manifest 的 when_to_use/when_not_to_use 字段当前仅确定性 selector 使用。LLM-based semantic matching 为 future task。 |

**Why not auto-fixed now**: 需要外部 server/config 或专项设计，属于未来阶段。

---

## 3. Current-Stage Status

- **current-stage remains closed: yes-with-caveats**
- **P0/P1/P2 blocker: no**
- **AGENT_AUTO remaining: zero**
- **Not product-ready**

---

## 4. Recommended Next Entry Routes

按优先级排列：

### Route 1: User Manual Trial (推荐第一进入点)
1. 用户在真实终端中验证 IME (iTerm2/Terminal.app + 中文输入法)
2. 验证 paste 中文/英文/mixed
3. 验证 multiline input
4. 参照: `docs/design/b8-input-readiness-validation.md`

### Route 2: Product Decision
1. TUI default entry 策略
2. Real gateway adapter 方向
3. Dashboard / AutoRun legacy cleanup 策略

### Route 3: Skill/Tool Behavior Hardening
1. 写 Skill/Tool behavior hardening SPEC
2. Deterministic pre-filter for model SKILL_SELECT
3. MBC-001~004 专项设计

### Route 4: Future MCP Production Readiness
1. 配置外部 MCP server
2. Production MCP E2E 验证

---

## 5. Related Docs

| Doc | Relation |
|-----|----------|
| `docs/PROJECT_STATUS.md` | 当前状态 / REAL-EVIDENCE-001..008 |
| `docs/PROGRESS_LEDGER.md` | 进度历史 |
| `docs/handoff/first-agent-current-stage-close-out-2026-06-02.md` | FROZEN close-out handoff |
| `docs/dogfood/real-evidence-002-non-steered-results.json` | 002 evidence |
| `docs/dogfood/real-evidence-003-hardening-results.json` | 003 evidence |
| `docs/design/b8-input-readiness-validation.md` | IME/paste/multiline checklist |
| `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md` | Real evidence validation debt |

# First Agent — Unresolved Open Items

**创建**: 2026-06-02
**Current baseline**: `pending-this-remediation` — `fix(release): isolate v1 tests and align release docs`
**Independent audit**: P0/P1/P2 blocker: no。Secret leak: no。AGENT_FIX_AUTO tasks: 0 (4406 passed, 0 failed, 37 xfailed)。
**Full pytest**: 4406 passed, 18 skipped, 37 xfailed — release-clean (0 live failures).

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
| MBC-001 | 002 C6 negative trigger bypass | demo-note-maker 被选中，尽管 prompt 含"数学"（negative trigger）。模型 owned SKILL_SELECT 路径绕过确定性 selector 的 negative_triggers 排除。 | historical validation summary — C6: FAIL |
| MBC-002 | 002 C3 over-eager selection | 模糊 prompt "帮我写点东西" 触发 SKILL_SELECT。模型在没有明确 skill 需求时过度主动。 | historical validation summary — C3: CONCERN |
| MBC-003 | 002 C7 over-eager selection | 闲聊 "你好，请问今天是什么日期？" 触发 SKILL_SELECT。模型将无 skill 意图的对话误判为 skill 请求。 | historical validation summary — C7: CONCERN |
| MBC-004 | 003 OTHER_GATE vs skill_allowed_tools→rejected | Disallowed tools 走 OTHER_GATE 而非 skill_allowed_tools→rejected。模型行为变化：不再主动尝试 disallowed tools。代码路径已验证 (Loop 8: 13/0/4 PASS)。无安全风险 (R35: no side effect)。 | historical validation summary — 13 CONCERN |

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

需要用户产品决策的项目（对齐 `PROJECT_STATUS.md` PD-001~PD-005）。

| ID | Issue | Detail | Owner |
|----|-------|--------|-------|
| PD-001 | Textual TUI 为未来默认 terminal app | 当前 `python main.py --tui`(Textual TUI) 为候选入口，plain CLI 为稳定主入口。是否将 Textual TUI 作为 v2 默认 terminal app。 | user |
| PD-002 | Plain CLI fallback 保留 | 当前 `python main.py`(Plain CLI) 为稳定主入口。v2 是否保留为 fallback。 | user |
| PD-003 | Ink prototype 冻结/归档 | `cd tui && npm start`(Ink TuiShell) 当前为 default npm start 入口，但仍为 prototype/visual experiment。v2 是否冻结/归档。 | user |
| PD-004 | --shell deprecated/remove | `--shell` flag 当前为 deprecated compatibility only。v2 是否移除。 | user |
| PD-005 | v1 tag wording | v1 close-out tag 命名（如 `v1.0.0-dev` / `v1-engineering-baseline`）。 | user |

**Why not auto-fixed now**: 这些决策影响产品方向，不能由 Agent 自动决定。当前 v1 engineering baseline 已完成，等待用户决策后方可 tag。

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
| `docs/PROJECT_STATUS.md` | 当前状态与冻结边界 |
| `docs/design/b8-input-readiness-validation.md` | IME/paste/multiline checklist |

# First Agent — v2 Priority Backlog

**创建**: 2026-06-03 | **最后更新**: 2026-06-05
**用途**: v2 阶段优先项分类管理。所有项目均为 v1 非阻塞项（non-code-blocker, non-AGENT_FIX_AUTO），等待对应 owner 决策或后续专项工程。

---

## 0. ENTRY GATE — CORE_CHAT_STABILIZATION_REQUIRED

**2026-06-05**: 本 backlog 所有项目（含 P1）在 Core Chat Stabilization golden E2E 退出条件满足前 **不得启动**。

**退出条件** (见 `PROJECT_STATUS.md`):
- G1-G5 全部 REAL_USER_VERIFIED 或 REAL_PROVIDER_E2E_VERIFIED + 用户抽样确认
- 不允许 fake-only close
- 不允许 focused-tests-only close

**理由**: 自动 dogfood 和 focused tests 不再足以关闭用户路径问题。架构红队审计发现 fake/real 分裂 (DANGEROUS_SPLIT)、文档 overclaim、FIXED_BY_RECHECK 自证循环等问题。必须先建立可信 Code Chat 主线。

**Only after exit**: 恢复 v2 backlog 工作。

---

## 1. USER_MANUAL_TRIAL

需要用户在真实终端环境中试用的项目。

| ID | Issue | Priority | Owner | Why not v1 blocker | Required evidence before closure | Recommended next loop |
|----|-------|----------|-------|--------------------|----------------------------------|----------------------|
| UMT-001 | Chinese IME validation | P1 | user | Ink useInput 不支持 composition 事件自动化，无法 CI 覆盖 | 用户在 iTerm2/Terminal.app + 中文输入法下验证 composing/text-update/commit 阶段，记录 pass/fail | 参照 `docs/design/b8-input-readiness-validation.md` checklist 逐项验证 |
| UMT-002 | Paste / multiline | P1 | user | 需真实终端粘贴行为，自动化无法覆盖终端 paste buffer | 粘贴中文/英文/mixed/特殊字符/multiline 块，记录 pass/fail | 参照 trial guide §3-4 |
| UMT-003 | Terminal real interaction | P2 | user | IME + paste + multiline 组合场景依赖前两项完成 | UMT-001 + UMT-002 通过后验证组合场景 | UMT-001/002 完成后 |

### USER_MANUAL_TRIAL Findings (2026-06-04) — REMEDIATED 2026-06-04

**Status: USER_RECHECK_FAILED_WITH_P1_FINDINGS** — Coding Agent 声称修复完成（eaf2982），但用户真实终端复测发现 2 个 P1 + 1 个 P2 仍未修复。详见 `docs/manual-trials/first-agent-user-manual-trial-report-2026-06-04.md` §7 USER_RECHECK Results。

| ID | Issue | Priority | Remediation Status |
|----|-------|----------|-------------------|
| **UMT-P1-001** | Textual TUI deadlock / cannot exit | **P1** | **STILL_OPEN** — USER_RECHECK 发现 `python main.py --tui` 启动后直接退出，不可交互（不再 deadlock 但根本进不了 TUI）。→ USER_RECHECK-P1-002 |
| **UMT-P1-002** | TOOL_GATE overblocks valid Skill tools | **P1** | **STILL_OPEN** — USER_RECHECK 发现 `write_demo_note`/`echo_task_summary` 仍被 TOOL_GATE 拒绝，explicit_allowlist 修复未生效。→ USER_RECHECK-P1-001 |
| **UMT-P2-001** | Weak fallback after TOOL_GATE rejection | **P2** | **STILL_OPEN** — USER_RECHECK 发现模型反复重试同一被拒工具 ~16 次，未优雅恢复。→ USER_RECHECK-P2-001 |
| **UMT-P2-002** | Textual paste / shortcut handling incomplete | **P2** | **UNCHANGED** — USER_RECHECK 未复测（TUI 不可交互，无法验证粘贴）。 |
| **UMT-P3-001** | Extensionless file path resolution weak | **P3** | **FIXED** — USER_RECHECK 确认 README 读取成功，extensionless path resolution 通过。 |

### USER_RECHECK Findings (2026-06-04) — NEW

| ID | Issue | Priority | Status |
|----|-------|----------|--------|
| **USER_RECHECK-P1-001** | demo-note-maker Skill tools (`write_demo_note`/`echo_task_summary`) still rejected by TOOL_GATE after Skill activation | **P1** | OPEN — 对应 UMT-P1-002 |
| **USER_RECHECK-P1-002** | `python main.py --tui` does not enter usable interactive Textual TUI; exits after startup/memory extraction | **P1** | OPEN — 对应 UMT-P1-001 |
| **USER_RECHECK-P2-001** | TOOL_GATE rejection recovery still weak; model retries same rejected tools ~16 times | **P2** | OPEN — 对应 UMT-P2-001 |
| **USER_RECHECK-P3-001** | Sensitive config fallback answer too generic; not project-specific | **P3** | OPEN |
| **USER_RECHECK-P3-002** | Rejection suggestion recommends copying sensitive config to non-sensitive path (bypass risk) | **P3** | OPEN |
| **USER_RECHECK-P3-003** | README entry strategy wording may be stale (claims `python main.py demo "..."` as default) | **P3** | OPEN |

**Trial guide**: `docs/manual-trials/first-agent-user-trial-guide.md` — 可执行试用剧本，含 Coding Agent 陪跑 prompt、角色分离、严重度规则（P0-P3）、trial report 模板。

---

## 2. PRODUCT_DECISION

需要用户产品决策的项目（对齐 `PROJECT_STATUS.md` PD-001~PD-005）。

| ID | Issue | Priority | Owner | Why not v1 blocker | Required evidence before closure | Recommended next loop |
|----|-------|----------|-------|--------------------|----------------------------------|----------------------|
| PD-001 | Textual TUI 为未来默认 terminal app | P1 | user | 当前 plain CLI 为稳定主入口，切换默认需产品决策 | 用户明确决定 Textual TUI 作为 v2 默认入口 | 用户决策后更新入口策略 |
| PD-002 | Plain CLI fallback 保留 | P1 | user | 当前 `python main.py` 为稳定主入口，v2 是否保留为 fallback | 用户明确决定是否保留 plain CLI fallback | 用户决策后更新入口策略 |
| PD-003 | Ink prototype 冻结/归档 | P1 | user | `cd tui && npm start` (Ink TuiShell) 当前为 default npm start 入口，但仍为 prototype/visual experiment | 用户明确决定 v2 是否冻结/归档 Ink prototype | 用户决策后执行 freeze/archive 或继续维护 |
| PD-004 | --shell deprecated/remove | P2 | user | `--shell` flag 当前为 deprecated compatibility only | 用户明确决定 v2 是否移除 | 用户决策后移除或保留 |
| PD-005 | v1 tag wording | P2 | user | v1 close-out tag 命名需用户决定 | 用户确定 tag 名称 | 用户决策后打 tag |
| PD-006 | Legacy Dashboard / AutoRun cleanup | P2 | user | 当前 PAUSED，B8 方向已转为 Interaction-first Workbench；保留需产品决策 | 用户明确决定 v2 是否清理/归档/删除 legacy Dashboard 和 AutoRun 代码及文档 | 用户决策后执行 cleanup |

---

## 3. REAL_ENV_REQUIRED

需要真实外部环境/配置才能验证的项目。

| ID | Issue | Priority | Owner | Why not v1 blocker | Required evidence before closure | Recommended next loop |
|----|-------|----------|-------|--------------------|----------------------------------|----------------------|
| RER-001 | Production / external MCP server | P2 | user + agent | 当前仅 local filesystem MCP smoke，production MCP 需用户配置外部 server | 用户配置真实外部 MCP server，验证 discover/invoke/close lifecycle | D-02 MCP real connection loop |
| RER-002 | Real provider opt-in smoke | P2 | user + agent | 真实 provider 需要用户配置 api_key，无法 CI 自动化 | 用户配置真实 provider key 后跑 real provider smoke suite | D-04 real provider smoke |
| RER-003 | External MCP E2E validation | P2 | user + agent | 依赖 RER-001 完成 | RER-001 通过后跑 E2E MCP tool call through core.chat | RER-001 完成后 |

---

## 4. MODEL_BEHAVIOR_DESIGN

模型行为导致的问题，非当前代码 bug。需专项设计而非代码修补。

| ID | Issue | Priority | Owner | Why not v1 blocker | Required evidence before closure | Recommended next loop |
|----|-------|----------|-------|--------------------|----------------------------------|----------------------|
| MBD-001 | 002 C6 negative trigger bypass | P2 | agent | 模型 owned SKILL_SELECT 路径绕过确定性 selector 的 negative_triggers 排除 — 模型行为，非代码缺陷 | deterministic pre-filter 在模型 SKILL_SELECT 前执行，C6 变为 PASS 或确认为模型行为限制 | Skill/Tool behavior hardening SPEC → TDD → Review |
| MBD-002 | 002 C3/C7 over-eager selection | P2 | agent | 模型在没有明确 skill 需求时过度主动 — 模型行为 | no_skill threshold 调整后 C3/C7 不再误触发 | Skill selection threshold tuning |
| MBD-003 | 003 OTHER_GATE vs skill_allowed_tools→rejected | P2 | agent | Disallowed tools 走 OTHER_GATE 而非 skill_allowed_tools→rejected — 模型行为变化 | 模型行为与确定性 gate 交互契约明确后 | Skill/Tool behavior hardening SPEC |
| MBD-004 | FakeProvider state-machine xfails | P3 | agent | 多个 smoke tests xfail（strict），FakeProvider 行为变化导致状态机语义变更 | 状态机语义稳定后解除 xfail 或更新 assert | v2 state machine SPEC review |

**Design entry point**: Skill/Tool behavior hardening SPEC — 包括 deterministic pre-filter for model SKILL_SELECT、no_skill threshold 调整、模型行为与确定性 gate 交互契约。

---

## 5. FUTURE_DEBT

未来阶段债务，不阻塞当前 close-out。

| ID | Issue | Priority | Owner | Why not v1 blocker | Required evidence before closure | Recommended next loop |
|----|-------|----------|-------|--------------------|----------------------------------|----------------------|
| FD-001 | Memory extractor zero proposals | P3 | agent | Episodic memory extractor 对某些输入产生 0 proposals，需 extractor redesign | 新 extractor 设计 + 所有 known input types 产生 ≥1 proposal | Memory extractor redesign SPEC |
| FD-002 | Full repo ruff legacy debt | P3 | agent | ~991 legacy issues，touched Python files 已 ruff clean | full repo ruff pass 或明确分类为 pre-existing legacy | 逐目录 ruff fix |
| FD-003 | when_to_use / when_not_to_use semantic matching | P3 | agent | Plan 3 manifest 的 when_to_use/when_not_to_use 字段当前仅确定性 selector 使用，LLM-based semantic matching 为 future task | semantic matching 实装并通过 real provider evidence | Skill system semantic matching SPEC |
| FD-004 | Runtime action / catalog coverage | P3 | agent | 部分 branch point 仍为 PARTIAL/DEFERRED，需补齐 dispatcher evidence | 所有 branch point 至少 PARTIAL | Runtime integration coverage loop |

---

## 6. Priority Summary

| Priority | Count | Items |
|----------|-------|-------|
| **P1** | 6 | UMT-001, UMT-002, PD-001, PD-002, PD-003 |
| **P2** | 9 | UMT-003, PD-004, PD-005, PD-006, RER-001, RER-002, RER-003, MBD-001, MBD-002, MBD-003 |
| **P3** | 5 | MBD-004, FD-001, FD-002, FD-003, FD-004 |

**v2 backlog 全部项目受 Core Chat Stabilization golden E2E gate 阻塞。** v1 closeout is HISTORICAL — 以 PROJECT_STATUS.md 当前 CORE_CHAT_STABILIZATION_REQUIRED 状态为准。

---

## 7. Related Docs

| Doc | Relation |
|-----|----------|
| `docs/debt/first-agent-open-items.md` | v1 open items（当前阶段） |
| `docs/PROJECT_STATUS.md` | 当前状态 + PD-001~005 定义 |
| `docs/PROGRESS_LEDGER.md` | 进度历史 |
| `docs/handoff/first-agent-current-stage-close-out-2026-06-02.md` | FROZEN 阶段交接 |
| `docs/manual-trials/first-agent-user-trial-guide.md` | Manual trial guide |

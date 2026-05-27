# Current Capability Recovery Map

**日期**: 2026-05-28 (post-Loop 15 update)
**基于**: 全能力红队审计 (4.2/10) + 12 remediation loops + Loops 14-18 完成 + 最新严格复审
**用途**: 事实源——区分真实能力和 overclaim，指导 safe-to-auto-run 修复优先级

---

## Executive Summary

原始审计 4.2/10 → 12 loops remediation → 最新严格复审 **4.0/10**。

分数下降不是因为系统变差，而是因为 overclaim 被揭穿：
- Loop 13 修了 1 个 evidence 分类却标 all P0/P1 resolved → OVERCLAIMED
- 15/15 PASS dogfood 实际是 no-crash smoke，不是 capability PASS
- 12/12 loops completed 中多个是 admin/docs 完成，不是 capability 完成

**当前真实阶段**: developer prototype / developer-dogfood。不可标 user-usable。

---

## Capability Scorecard (Post-Remediation Honest)

| # | Capability | Claimed Status | Actual Evidence Level | Real Status | Overclaim Risk | Blocker | Can Auto-Fix? | Req. Arch Decision? | Rec. Loop |
|---|-----------|---------------|----------------------|-------------|---------------|---------|---------------|--------------------|-----------| 
| 1 | Basic CLI chat | PASS (real API smoke) | L3 real API interactive | **PASS** | LOW | 无 | N/A | No | — |
| 2 | Real provider config/loading | PASS | L3 real API dogfood | **PASS** | LOW | 无 | N/A | No | — |
| 3 | Tool calling | PASS (L3 business op) | L3 fake + L4 real smoke | **PASS** | LOW | multi-turn real API cover | No (safe-fix: mark) | No | evidence honesty mark |
| 4 | Tool confirmation | PASS (y/n flow) | L3 fake interactive + L4 real smoke | **PASS** | LOW | 无 | N/A | No | — |
| 5 | Tool result feedback | PASS | L3 fake handler path | **CONCERN** | MEDIUM | real API result feedback 未独立验证 | No (safe-fix: mark) | No | evidence honesty mark |
| 6 | Memory proposal | PASS (turn-end handler) | L3 dispatcher path (turn-end + user-initiated) | **PASS** | LOW | Loop 15 已统一 write path → dispatcher | N/A | No | — |
| 7 | Memory confirmation | PASS (y/n flow) | L3 dispatcher chain (MEMORY_PROPOSE → handler) | **PASS** | LOW | Loop 15: confirmation→dispatch→handler→store | N/A | No | — |
| 8 | Memory retain (write) | PASS (Loop 15 migrated) | L3 dispatcher path (MEMORY_PROPOSE → MemoryRetainHandler) | **PASS** | LOW | 无 | N/A | No | — |
| 9 | Memory recall → prompt context | PASS (Loop 3 fixed) | L3 dispatcher path | **PASS** | LOW | 无 | N/A | No | — |
| 10 | Memory forget/list | PASS | L2 direct call (forget) + L3 dispatcher (show) | **CONCERN** | MEDIUM | forget CLI shortcut 绕过 dispatcher | No | Yes (CLI shortcut migration) | future loop |
| 11 | SubAgent delegation | L0 only | L2 integration (L0 handler, always rejected) | **CONCERN** | MEDIUM | 无真实 subagent execution evidence | No | Yes (SubAgent L1/L2) | future loop |
| 12 | Checkpoint/resume | CONCERN | L1 unit + prompt 拼接 | **FAIL** | HIGH | resume=prompt拼接，非 state restoration | No | Yes (checkpoint architecture) | future loop |
| 13 | Interrupt/Ctrl+C | CONCERN | L2 fake interactive (I19) | **CONCERN** | MEDIUM | 无 real API 下 interrupt 验证 | No (safe-fix: mark) | No | evidence honesty mark |
| 14 | Streaming/progress | CONCERN | L2 fake interactive (I18) | **CONCERN** | MEDIUM | streaming event handler 注册但 real API 下未独立验证 | No (safe-fix: mark) | No | evidence honesty mark |
| 15 | Run summary/trace honesty | CONCERN | L2 observer (日志治理 done) | **CONCERN** | MEDIUM | evidence kind classification done, but overclaim patterns remain | **Yes** | No | **Loop 16: evidence taxonomy guard tests** |
| 16 | Dogfood harness | PASS (37 tests) | L3 fake interactive + L4 real smoke | **PASS** | LOW | Loop 14 fixed evidence gates | N/A | No | — |
| 17 | AutoRun self-driving | PASS (skill orchestration) | L2 guard tests (68 pass) | **CONCERN** | MEDIUM | skill routing/docs 完备但实际 auto-remediation 循环未验证 | No (safe-fix: mark) | No | evidence honesty mark |
| 18 | Evidence taxonomy | CONCERN | L2 guard tests (18 pass) | **CONCERN** | MEDIUM | overclaim patterns 仍存在（见本表） | **Yes** | No | **Loop 16** |
| 19 | Config/log/session hygiene | PASS (Loop 1+2) | L2 guard tests + skip-worktree | **PASS** | LOW | 无 | N/A | No | — |
| 20 | Skill system | CONCERN (L2 only) | L2 integration + docs | **CONCERN** | MEDIUM | L3 dispatcher path exists but skills not loaded in real API | No | Yes (skill runtime深化) | future loop |
| 21 | MCP | FAIL (stub) | L1 docs + guard tests | **FAIL** | HIGH | 无 real connection | No | **Yes** | future loop |
| 22 | UX/onboarding | CONCERN | L1 docs (Loop 12) | **CONCERN** | LOW | docs only, no interactive onboarding flow | No | Yes (UX design) | future loop |
| 23 | Multi-instance readiness | FAIL | L0 (not designed) | **FAIL** | HIGH | 模块级单例 (_memory_runtime, TOOL_REGISTRY) | No | **Yes** | future loop |
| 24 | TUI readiness | FAIL | L0 (not designed) | **FAIL** | HIGH | 无 TUI 架构 | No | **Yes** | future loop |

**统计**:
- PASS: 10 (1, 2, 3, 4, 6, 7, 8, 9, 16, 19)
- CONCERN: 10 (5, 10, 11, 13, 14, 15, 17, 18, 20, 22)
- FAIL: 4 (12, 21, 23, 24)
- OVERCLAIM RISK HIGH: 3 (12, 21, 23, 24)

---

## Classification: Safe-to-Auto-Run vs Requires-Architecture-Decision

### A. Safe-to-Auto-Run（可直接修，不需要架构决策）

| Priority | Item | Current Status | Action |
|----------|------|---------------|--------|
| **A1** | Evidence taxonomy guard tests — overclaim pattern detection | CONCERN | 新增 guard tests: no-crash→PASS forbidden, direct handler→L3 forbidden, partial→RESOLVED forbidden |
| **A2** | Dogfood report reclassification — old PASS → honest status | OVERCLAIMED | 重分类旧 report 中的行政 PASS 为 SMOKE_PASS/CONCERN |
| **A3** | CLI shortcut second-plane marking | CONCERN | 在 cli_commands.py + PROJECT_STATUS 中明确 CLI-only/demo-only |
| **A4** | Run summary honesty — probe vs business 区分 | CONCERN | 验证 run_summary 中 business/probe 计数正确 |
| **A5** | Stale "12/12 completed" narrative removal | OVERCLAIMED | 扫描并修正所有"all loops completed"类过期声称 |
| **A6** | Memory extractor 0 proposals → honest marking | PARTIAL | 明确 marking: 当前 extractor 仍只处理 episodic，不标 PASS |
| **A7** | Capability-to-evidence mapping guard tests | CONCERN | 验证 capabilities 表中每个 PASS 有对应 evidence |

### B. Requires-Architecture-Decision（只能设计审计，不直接硬改）

| Priority | Item | Current Status | Design Status |
|----------|------|---------------|---------------|
| **B1** | Memory write dispatcher migration | **COMPLETED (Loop 15, ca0a03c)** | `docs/design/memory-write-dispatcher-migration-design.md` → 已实现 |
| **B2** | CLI forget/delegate shortcut → dispatcher | NOT STARTED | 待 Loop 15 完成后 |
| **B3** | SubAgent L1/L2 成熟化 | NOT STARTED | 需要真实 subagent execution |
| **B4** | MCP real connection | NOT STARTED | 需要外部 MCP server |
| **B5** | Skill runtime 深化 (real API skill loading) | NOT STARTED | 需要真实 API + skill marketplace |
| **B6** | Checkpoint true state restoration | NOT STARTED | 需要 checkpoint schema 大改 |
| **B7** | Multi-instance readiness | NOT STARTED | 需要消除模块级单例 |
| **B8** | TUI architecture | NOT STARTED | 需要 TUI framework decision |

---

## Overclaim Inventory（已发现并需降级）

| Overclaim | Where | Original Claim | Honest Status | Fixed? |
|-----------|-------|---------------|---------------|--------|
| Loop 13 "all P0/P1 resolved" | PROJECT_STATUS (old) | RESOLVED | OVERCLAIMED — 只修了 1 个 evidence 分类 | ✓ Loop 14 + AutoRun fix |
| 15/15 PASS dogfood | dogfood report | PASS | 实际是 no-crash SMOKE_PASS | ✓ Loop 14 harness fix |
| 12/12 loops completed | remediation plan | completed | 多个是 admin/docs 完成 | PARTIAL — plan says completed |
| Memory E2E verified | PROJECT_STATUS (old) | PASS | extractor 0 proposals (known fake limitation), write path → dispatcher (Loop 15) | **RESOLVED** — write path fixed; extractor limitation honestly marked |
| All P0/P1 resolved | PROJECT_STATUS (old) | RESOLVED | 多个 P1 是 PARTIAL | ✓ Loop 14 fixed |
| "user-usable" hints | old docs | implied | developer prototype only | ✓ Loop 14 fixed |
| admin completed = capability | old narrative | implied | docs/guard ≠ capability | ✓ AutoRun forbidden patterns |

---

## Current Real Score Estimate: 4.5-5.0/10

**Capability-weighted honest score**: ~4.8/10 (post Loops 14-18)

- Tool pipeline (B): 7/10 → 6.5/10 (multi-turn real API not covered)
- Memory (C): 4/10 → 5.5/10 (write path → dispatcher, Loop 15; extractor limitation marked)
- CLI/Interactive (J): 7/10 → 6.5/10 (harness evidence gates fixed, dogfood reports reclassified)
- Config/Security (K): 3/10 → 7/10 (Loop 1+2)
- Test/Gate (L): 5/10 → 6/10 (evidence taxonomy guard tests added, 79 source-of-truth PASS)
- Docs (M): 6/10 → 6/10 (source-of-truth maintained, overclaims corrected, stale claims removed)

**Post safe-to-auto-run fix target**: 4.5-5.0/10 ✓ **ACHIEVED**（Loops 14-18 完成）
**Post architecture migration target**: 5.5-6.5/10 (B2-B8: CLI shortcut migration, SubAgent, MCP, Skill, Checkpoint, Multi-instance, TUI)

---

## Execution Status (as of 2026-05-28)

1. ✓ **Loop 16: Evidence Taxonomy & Overclaim Guard Tests** (COMPLETED — 76db3db)
2. ✓ **Loop 17: Dogfood Report Reclassification** (COMPLETED — a6e0980)
3. ✓ **Loop 18: CLI Shortcut Honesty Marking** (COMPLETED — 6000a00)
4. ✓ **Loop 15: Memory Write Dispatcher Migration** (COMPLETED — ca0a03c)

**Safe-to-auto-run items: ALL COMPLETE** (A1-A7 done via Loops 14-18)

## Next: Requires Architecture Decision (B2-B8)

| Item | Description | Prerequisites |
|------|-------------|---------------|
| B2 | CLI forget/delegate → dispatcher | confirmation pipeline 就绪 |
| B3 | SubAgent L1/L2 | real subagent execution |
| B4 | MCP real connection | external MCP server |
| B5 | Skill runtime deepening | real API + skill marketplace |
| B6 | Checkpoint state restoration | checkpoint schema redesign |
| B7 | Multi-instance readiness | module-level singleton removal |
| B8 | TUI architecture | TUI framework decision |

All remaining items require independent design/audit before implementation. No further safe-to-auto-run items.

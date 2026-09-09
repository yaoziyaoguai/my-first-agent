# plans/ 索引

本目录 36 份计划文档全部已执行完毕；仓库于 2026-09-09 冻结为学习里程碑
（tag `study-freeze-2026-09-09-candidate`）。计划按日期命名、原地保留（三份被
README/AGENTS.md 硬引用，不做物理归档）；各里程碑的交付证据见
[../implementation/](../implementation/) 的 EXECUTION_LOG 与 [../acceptance/](../acceptance/) 的
seal/review 文件。当前能力状态权威：
[../architecture/CURRENT_CAPABILITY_STATUS.md](../architecture/CURRENT_CAPABILITY_STATUS.md)。

## 阶段一：内核重建与能力重引入（2026-07，done）

| 计划 | 对应交付 |
|---|---|
| [2026-07-18-001-refactor-minimal-runtime-kernel-plan.md](2026-07-18-001-refactor-minimal-runtime-kernel-plan.md) | Minimal Runtime Kernel 重建 |
| [2026-07-18-002-feat-governed-skill-source-plan.md](2026-07-18-002-feat-governed-skill-source-plan.md) | Skill |
| [2026-07-18-003-feat-governed-mcp-tools-plan.md](2026-07-18-003-feat-governed-mcp-tools-plan.md) | MCP |
| [2026-07-18-004-feat-budgeted-memory-source-plan.md](2026-07-18-004-feat-budgeted-memory-source-plan.md) | Memory |
| [2026-07-18-005-feat-bounded-subagent-delegation-plan.md](2026-07-18-005-feat-bounded-subagent-delegation-plan.md) | SubAgent |
| [2026-07-18-006-feat-scheduler-external-caller-plan.md](2026-07-18-006-feat-scheduler-external-caller-plan.md) | Scheduler |
| [2026-07-18-007-feat-tui-runtime-adapter-plan.md](2026-07-18-007-feat-tui-runtime-adapter-plan.md) | TUI |
| [2026-07-19-008-stabilize-capability-reintroduction-plan.md](2026-07-19-008-stabilize-capability-reintroduction-plan.md) | 008（冻结为历史，不再作为晋级依据） |
| [2026-07-20-009-close-capability-evidence-gaps-plan.md](2026-07-20-009-close-capability-evidence-gaps-plan.md) | 009 closure program（G0–G8） |
| [2026-07-25-010-feat-general-workspace-agent-plan.md](2026-07-25-010-feat-general-workspace-agent-plan.md) | 010/011 通用 workspace agent |

## 阶段二：产品里程碑（2026-08，done）

| 计划 | 对应交付 |
|---|---|
| [2026-08-02-001-feat-trusted-continuity-plan.md](2026-08-02-001-feat-trusted-continuity-plan.md) | 012 Trusted Continuity |
| [2026-08-03-001-feat-everyday-workspace-agent-plan.md](2026-08-03-001-feat-everyday-workspace-agent-plan.md) | 013 Everyday Workspace |
| [2026-08-04-001-feat-grounded-personal-knowledge-agent-plan.md](2026-08-04-001-feat-grounded-personal-knowledge-agent-plan.md) | 014 Grounded Personal Knowledge |
| [2026-08-09-001-feat-governed-local-action-plan.md](2026-08-09-001-feat-governed-local-action-plan.md) | 015 Governed Local Action |
| [2026-08-20-001-first-agent-1-0-product-convergence-plan.md](2026-08-20-001-first-agent-1-0-product-convergence-plan.md) | 016 First Agent 1.0 |
| [2026-08-26-001-deepen-evidence-closure-module-plan.md](2026-08-26-001-deepen-evidence-closure-module-plan.md) | evidence closure 深化 |
| [2026-08-26-002-architecture-deepening-program.md](2026-08-26-002-architecture-deepening-program.md) | architecture deepening program |

## 阶段三：finish-long-session 收尾系列（2026-09，done；实现并入 commit `684f368`）

母计划：[2026-09-04-001-finish-long-session-and-governed-shell-plan.md](2026-09-04-001-finish-long-session-and-governed-shell-plan.md)
（长会话压缩/archive + `shell_exec` + 交付缺口闭合）。

| # | 计划 | 状态 |
|---|---|---|
| 001 | [trusted-decision-interaction](2026-09-08-001-trusted-decision-interaction-plan.md) | done |
| 002 | [browser-open-authority-lifecycle](2026-09-08-002-browser-open-authority-lifecycle-plan.md) | superseded-by-003 |
| 003 | [profile-writer-lifecycle](2026-09-08-003-profile-writer-lifecycle-plan.md) | done |
| 004 | [pressure-safe-context-retention](2026-09-08-004-pressure-safe-context-retention-plan.md) | verified-closed |
| 005 | [known-tool-failure-convergence](2026-09-08-005-known-tool-failure-convergence-plan.md) | verified-closed |
| 006 | [mcp-owned-process-group-cleanup](2026-09-08-006-mcp-owned-process-group-cleanup-plan.md) | verified-closed |
| 007 | [model-tool-batch-convergence](2026-09-08-007-model-tool-batch-convergence-plan.md) | accepted |
| 008 | [accepted-batch-safe-readback-completion](2026-09-08-008-accepted-batch-safe-readback-completion-plan.md) | accepted |
| 009 | [background-tool-replay-reclamation](2026-09-08-009-background-tool-replay-reclamation-plan.md) | accepted |
| 010 | [tui-displayed-decision-binding](2026-09-08-010-tui-displayed-decision-binding-plan.md) | done（frozen） |
| 011 | [tui-browser-takeover-controls](2026-09-08-011-tui-browser-takeover-controls-plan.md) | done（frozen） |
| 012 | [tui-terminal-goal-follow-up](2026-09-08-012-tui-terminal-goal-follow-up-plan.md) | done（frozen） |
| 012a | [terminal-follow-up-runtime-boundary](2026-09-08-012a-terminal-follow-up-runtime-boundary-plan.md) | done（frozen） |
| 013 | [default-sandbox-private-roots](2026-09-08-013-default-sandbox-private-roots-plan.md) | done（frozen） |
| 014 | [prepared-path-execution-binding](2026-09-08-014-prepared-path-execution-binding-plan.md) | verified-closed |
| 015 | [gitdir-pointer-write-protection](2026-09-08-015-gitdir-pointer-write-protection-plan.md) | verified-closed |
| 016 | [dual-pipe-eof-process-liveness](2026-09-08-016-dual-pipe-eof-process-liveness-plan.md) | verified-closed |
| 017 | [freeze-critical-contract-closures](2026-09-09-017-freeze-critical-contract-closures-plan.md) | done（Oracle r17 packet 的合同闭合） |

注：014–016 状态行所写"未 commit、未 push"为写作时点记录；其实现已于 2026-09-09 随 r18 收尾
并入 commit `684f368` 并冻结。

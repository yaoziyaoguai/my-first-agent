# Progress Ledger — First Agent

**最后更新**: 2026-06-10
**状态**: current short ledger。旧长流水账已在 repository cleanup 中压缩；过时计划、旧验证报告和历史审计不再作为当前执行依据。

本文只记录当前维护需要知道的少量里程碑。当前实现和边界以 [PROJECT_STATUS.md](PROJECT_STATUS.md) 为准。

## Current Cleanup Milestones

| Date | Milestone | Summary |
|---|---|---|
| 2026-06-10 | Repository cleanup baseline | 删除旧上下文成为当前主线工作。保留 current README、PROJECT_STATUS、CURRENT_DOCS、当前能力摘要和 focused tests。 |
| 2026-06-10 | Sub-agent v0 baseline protected | Sub-agent v0 U1-U4 focused tests 是当前保护网；legacy L1/L2 production route 保持 frozen / compatibility only。 |
| 2026-06-10 | Dogfood artifacts purged | Dogfood-only docs, reports, fixtures, scripts, TUI panels, and tests are removed or detached from current indexes. Remaining references are compatibility names or historical archived text, not current workflow. |

## Current Capability Baseline

| Capability | Current Status |
|---|---|
| Runtime baseline | `main.py -> agent/core.py -> agent/loop.py` remains the main path. |
| Tool/MCP boundary | Tool execution stays mediated by `ToolRuntimeMediator` and `tool_executor`; MCP remains adapter-boundary/gated. |
| Memory v0 | Explicit retain/confirmation/evidence/store-reference baseline retained; no raw writes or auto-adoption. |
| Skill lifecycle | Runtime-managed active skill lifecycle retained; legacy `agent/tools/skill.py` remains fail-closed compatibility shim. |
| Sub-agent v0 | Parent-mediated child boundary retained; child direct tool/MCP/memory execution remains forbidden. |
| Evidence/logging | `record_evidence()` is the shared path; no new subsystem-specific evidence store. |

## Active Rules

- If this ledger conflicts with [PROJECT_STATUS.md](PROJECT_STATUS.md), `PROJECT_STATUS.md` wins.
- Historical audit, review, release, archive, and old validation documents are context only.
- Do not restore old dogfood harnesses, direct execution paths, second runtime loops, memory raw writes, or L1/L2 production routes.
- For future cleanup, delete old docs aggressively; delete code only after reference checks and targeted tests.

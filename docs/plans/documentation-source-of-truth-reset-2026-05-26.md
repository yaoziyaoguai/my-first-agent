# Documentation Source-of-Truth Reset Plan

- **Date:** 2026-05-26
- **Type:** Documentation Garbage Collection
- **Goal:** Reduce ~170+ docs to ~40 active, archive rest, delete truly stale

## Phase 1: Current Active Source-of-Truth Set (DO NOT ARCHIVE/DELETE)

| # | Path | Category | Why |
|---|------|----------|-----|
| 1 | `README.md` | ACTIVE_SOURCE_OF_TRUTH | 人类入口 |
| 2 | `docs/README.zh.md` | ACTIVE_SOURCE_OF_TRUTH | 中文导航 |
| 3 | `docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md` | ACTIVE_SOURCE_OF_TRUTH | 当前能力一页 |
| 4 | `docs/00-overview/FIRST_AGENT_OVERVIEW.zh.md` | ACTIVE_REFERENCE | 项目概览 |
| 5 | `docs/00-overview/ARCHITECTURE_MAP.zh.md` | ACTIVE_REFERENCE | 架构图 |
| 6 | `docs/00-overview/CAPABILITY_MATRIX.zh.md` | ACTIVE_REFERENCE | 能力矩阵 |
| 7 | `docs/01-getting-started/GETTING_STARTED.zh.md` | ACTIVE_REFERENCE | 入门指南 |
| 8 | `docs/05-testing-dogfood/TEST_MATRIX.zh.md` | ACTIVE_REFERENCE | 测试矩阵 |
| 9 | `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | ACTIVE_SOURCE_OF_TRUTH | 架构宪法 |
| 10 | `docs/dev/AUTO_RUN_WORKFLOW.md` | ACTIVE_SOURCE_OF_TRUTH | AutoRun 工作流 |
| 11 | `docs/dev/ENGINEERING_WORKFLOW.md` | ACTIVE_REFERENCE | 工程流程 |
| 12 | `.claude/commands/auto-run.md` | ACTIVE_SOURCE_OF_TRUTH | 项目命令 |
| 13 | `docs/dogfood/README.md` | ACTIVE_SOURCE_OF_TRUTH | Dogfood 索引 |
| 14 | `docs/dogfood/manual-human-dogfood-next-steps.md` | ACTIVE_SOURCE_OF_TRUTH | Dogfood 下一步 |
| 15 | `docs/dogfood/manual-human-dogfood-record-template.md` | ACTIVE_REFERENCE | Dogfood 模板 |
| 16 | `docs/dogfood/local-manual-dogfood-checklist.md` | ACTIVE_REFERENCE | Dogfood 清单 |
| 17 | `docs/audit/README.md` | ACTIVE_SOURCE_OF_TRUTH | 审计索引 |
| 18 | `docs/plans/README.md` | ACTIVE_SOURCE_OF_TRUTH | 计划索引 |
| 19 | `docs/plans/final-cleanup-readiness-summary-2026-05-25.md` | ACTIVE_SOURCE_OF_TRUTH | 当前 readiness summary |
| 20 | `docs/plans/first-agent-subsystem-integration-roadmap.md` | ACTIVE_REFERENCE | AutoRun queue |
| 21 | `docs/rfc/MEMORY_CANONICAL_RFC.md` | ACTIVE_REFERENCE | Memory canonical spec |
| 22 | `docs/rfc/SKILL_CANONICAL_RFC.md` | ACTIVE_REFERENCE | Skill canonical spec |
| 23 | `docs/rfc/SUBAGENT_CANONICAL_RFC.md` | ACTIVE_REFERENCE | SubAgent canonical spec |
| 24 | `docs/audit/global-red-team-product-architecture-audit-2026-05-25.md` | ACTIVE_REFERENCE | 最新 red-team audit |
| 25 | `docs/audit/global-agent-capability-architecture-audit-2026-05-25.md` | ACTIVE_REFERENCE | 全局能力审计 |
| 26 | `docs/audit/capability-gap-audit-low-complexity-2026-05-25.md` | ACTIVE_REFERENCE | Capability gap audit |
| 27 | `docs/audit/user-journey-static-review-friction-matrix-2026-05-25.md` | ACTIVE_REFERENCE | 最近 friction matrix |
| 28 | `docs/plans/low-complexity-capability-remediation-summary-2026-05-25.md` | ACTIVE_REFERENCE | Low-complexity 结果 |
| 29 | `tests/README.md` | ACTIVE_REFERENCE | 测试指南 |

## Phase 2: Archive Candidates (move to docs/archive/)

### Root-level docs → docs/archive/

| Path | Why |
|------|-----|
| `docs/DOGFOODING_GUIDE.md` | Superseded by docs/dogfood/ |
| `docs/DOGFOODING_MEMORY_GUIDE.md` | Superseded by docs/dogfood/ |
| `docs/ARCHITECTURE.md` | Superseded by 00-overview/ARCHITECTURE_MAP.zh.md |
| `docs/ROADMAP.md` | Already marked Historical |
| `docs/ROADMAP_LEGACY.md` | Legacy 22-block |
| `docs/ROADMAP_COMPLETION_AUTOPILOT.md` | Old autopilot plan |
| `docs/REMAINING_ROADMAP_COMPLETION_AUTOPILOT.md` | Old autopilot continuation |
| `docs/FINAL_ROADMAP_COMPLETION_EVIDENCE.md` | Completion evidence |
| `docs/HUMAN_REVIEW_PACKET.md` | Old review packet |
| `docs/RELEASE_TAG_PREPARATION.md` | Old release prep |
| `docs/RELEASE_TAG_AUTHORIZATION_PACKET.md` | Old release auth |
| `docs/SAFE_LOCAL_RELEASE_READINESS.md` | Old release readiness |
| `docs/SUBAGENT_LOCAL_MVP.md` | Superseded by SubAgent L0 completion |
| `docs/SKILL_LOCAL_MVP.md` | Superseded by Skill safe-local completion |
| `docs/CAPABILITY_BOUNDARIES.md` | Superseded by CURRENT_CAPABILITY_STATUS |
| `docs/DEFERRED_ROADMAP_BOUNDARIES.md` | Old deferred items |
| `docs/LLM_AUDIT_STATUS_SCHEMA.md` | Old LLM audit |
| `docs/LLM_PROCESSING_CAPABILITY_MATRIX.md` | Old capability matrix |
| `docs/LLM_PROVIDER_ADAPTER.md` | Old provider docs |
| `docs/LLM_PROVIDER_CONFIG.md` | Old provider config |
| `docs/LLM_PROVIDER_LIVE_SMOKE.md` | Old live smoke plan |
| `docs/LLM_PROVIDER_LIVE_SMOKE_REPORT.md` | Old live smoke report |
| `docs/LOCAL_CONFIG_FOUNDATION.md` | Old config doc |
| `docs/LOCAL_TRACE_FOUNDATION.md` | Old trace doc |
| `docs/MCP_CONFIG_MANAGEMENT.md` | MCP not productized |
| `docs/MCP_EXTERNAL_INTEGRATION_READINESS.md` | MCP not productized |
| `docs/MCP_READINESS.md` | MCP not productized |
| `docs/MCP_REAL_INTEGRATION_SLICE_DESIGN.md` | MCP not productized |
| `docs/MCP_RUNBOOK.md` | MCP not productized |
| `docs/MCP_SECRET_HANDLING.md` | MCP not productized |
| `docs/MEMORY_ARCHITECTURE.md` | Superseded by MEMORY_CANONICAL_RFC |
| `docs/MEMORY_RESEARCH.md` | Historical research |
| `docs/P1_TOPIC_SWITCH_PLAN.md` | Historical plan |
| `docs/PENDING_INTERACTION_MODEL.md` | Historical design |
| `docs/RUNTIME_ERROR_RECOVERY.md` | Superseded |
| `docs/RUNTIME_EVENT_BOUNDARIES.md` | Superseded |
| `docs/RUNTIME_STATE_MACHINE.md` | Superseded |
| `docs/RUNTIME_TRACE_TOOLRESULT_MIGRATION.md` | Superseded |
| `docs/RUNTIME_TRACE_TOOLRESULT_SLICE_DESIGN.md` | Superseded |
| `docs/TOOL_RESULT_ENVELOPE.md` | Superseded |
| `docs/TUI_HITL_INTERACTION_AUDIT.md` | Historical audit |
| `docs/CHECKPOINT_RESUME_SEMANTICS.md` | Superseded by implementation |
| `docs/CLI_OUTPUT_CONTRACT.md` | v0.1 era, historical |

### docs/06-audit/ → merge into docs/audit/ or archive

| Path | Why |
|------|-----|
| `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md` | Stale v0.9.x status, superseded by CURRENT_CAPABILITY_STATUS |

### docs/implementation-notes/ → docs/archive/implementation-notes/

All 26 files are L3 evidence notes from completed implementation phases.

### docs/specs/ → docs/archive/specs/

All SPEC/TDD/IMPLEMENTATION_PLAN files from completed phases.

### docs/design/ → selective archive

| Path | Action |
|------|--------|
| `docs/design/SKILL_SYSTEM_SDD.md` | Keep as ACTIVE_REFERENCE |
| `docs/design/SUBAGENT_SYSTEM_SDD.md` | Keep as ACTIVE_REFERENCE |
| `docs/design/MEMORY_RECALL_DUAL_PATH_AD.md` | Archive |
| `docs/design/MEMORY_INLINE_CONFIRMATION_AGENT_LOOP_DESIGN.md` | Archive |
| `docs/design/GLOBAL_ARCHITECTURE_DEBT_REMEDIATION_PLAN.md` | Archive |
| `docs/design/SUBAGENT_L0_TO_L1_REAL_DELEGATION_AD.md` | Archive |
| `docs/design/real-provider-dispatcher-evidence-parity-ad.md` | Archive |

### Other directory archives

| Path | Action |
|------|--------|
| `docs/refactor/` (6 files) | Archive all — v0.9.x complete |
| `docs/runtime-integration/` (6 files) | Archive all — complete |
| `docs/roadmap/` (2 files) | Archive — historical loops |
| `docs/review/` (5 files) | Archive — old dogfood sessions |
| `docs/real-e2e/memory-anchor/` (3 files) | Archive — historical anchor |
| `docs/rfcs/` (3 files) | Archive — old RFCs |
| `docs/testing/` (2 files) | Archive — historical TDD plans |

## Phase 3: Delete Candidates (truly no value, git history sufficient)

| Path | Why |
|------|-----|
| `docs/LLM_PROCESSING_CAPABILITY_MATRIX.md` | Duplicate of CAPABILITY_MATRIX.zh.md |
| `docs/LLM_PROVIDER_LIVE_SMOKE_REPORT.md` | One-off smoke report, git history sufficient |
| `docs/RELEASE_TAG_PREPARATION.md` | Never used, no references |
| `docs/RELEASE_TAG_AUTHORIZATION_PACKET.md` | Never used |

## Phase 4: UPDATE_REQUIRED (keep in place, update content)

| Path | Issue |
|------|-------|
| `docs/README.zh.md` | References stale `06-audit/CURRENT_AUDIT_STATUS.zh.md`, `V0_3_SKILL_SYSTEM_STATUS` |
| `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md` | References v0.9.x status as current |
| `docs/ROADMAP.md` | References `06-audit/CURRENT_AUDIT_STATUS.zh.md` as current source |

## Phase 5: Tests that reference archived docs (MUST update)

Will be identified after archive operations via grep.

## Execution Plan

### Batch 1: Archive root-level docs (~42 files → docs/archive/)
### Batch 2: Archive directory-level docs (implementation-notes, specs, refactor, etc.)
### Batch 3: Update indexes (README.md, docs/README.zh.md, audit/README.md, plans/README.md, dogfood/README.md)
### Batch 4: Add source-of-truth tests
### Batch 5: Final gate verification

Each batch: commit + push.

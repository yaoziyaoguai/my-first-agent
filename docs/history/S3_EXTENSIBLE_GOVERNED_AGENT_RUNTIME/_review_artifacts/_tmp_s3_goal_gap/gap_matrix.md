# S3 Gap Matrix — baseline × frozen goal → gap

> Working evidence for `docs/current/S3_GOAL_GAP.md` (2026-06-19). Scratch /
> reasoning doc, not routing authority. Archived with the stage when S3 closes.

## Inputs

- Goal (frozen): `docs/current/S3_GOAL.md` — AC-1..AC-9, selected scope MCP+SubAgent.
- Baseline: `docs/current/S3_BASELINE_STATUS.md` + S2 archive.
- Debt: `docs/current/TECH_DEBT.md` (TD-001/002/003/004/006/007).

## L5 / runtime baseline evidence (graphify + file, S3 start)

- **Runtime spine (L1)**: `agent/core.py`, `agent/runtime_integration/dispatcher.py`
  (`RuntimeActionDispatcher` L309, `ActionHandlerRegistry` L78), `tool_gate.py`
  (`ToolGateHandler`), `agent/tool_runtime_mediator.py`, `agent/runtime_integration/evidence.py`.
- **Task-state / checkpoint (L2/L4)**: `agent/task_state_model.py`,
  `task_orchestration.py`, `task_context.py`, `task_evidence_report.py`,
  `task_tool_contract.py`, `task_review.py`.
- **Skill (L5, governed-active)**: `agent/skill_system/*` (gate.py = default-off
  `MY_FIRST_AGENT_S2_SKILL_ENABLE`; selector/lifecycle/checkpoint_restore/task_boundary).
- **MCP (L5, configurable default-off; runtime orchestrator HARNESS-ONLY)**:
  core `agent/mcp.py`, `mcp_bridge.py`, `mcp_models.py`; governance `mcp_policy.py`,
  `mcp_audit.py`, `mcp_sanitizer.py`; config `mcp_config*.py`; transport `mcp_stdio.py`;
  `mcp_external_readiness.py`; runtime `agent/runtime_integration/mcp_bridge_lifecycle.py`,
  `mcp_tool_orchestrator.py` (graphify: "HARNESS-ONLY"). Gate `MY_FIRST_AGENT_MCP_ENABLE`.
  → Plumbing exists but NOT wired into the production governed tool path by default.
- **SubAgent (L5, parent-mediated / side-effect-free / not activated)**:
  `agent/subagent_system/delegation.py` (`delegate_l1` L173, `delegate_once` L19),
  `executor.py` (`execute_l1` L131), `context.py` (`build_context_package` L40),
  `result.py` (`SubAgentAuditRecord` L41, `ParentAdjudicationResult` L79),
  `adjudication.py` (`adjudicate_result`), `errors.py` (`SubAgentPolicyError`);
  `agent/subagents/local.py`. Rationale nodes: "delegation 只是结构化请求/结果；
  parent policy 决定能否使用". Public API asserted side-effect-free by
  `tests/test_architecture_boundaries.py`.
- **Scheduler (L5, implemented, not activated in default loop)**:
  `agent/action_scheduler.py` (`ActionScheduler`/`ActionPlan`/`ActionNode`/
  `ActionRecoveryPolicy`), `agent/runtime_integration/action_scheduler_handler.py`,
  `tests/runtime_integration/test_scheduler_main_path.py`.
- **Acceptance gate (L1)**: `agent/acceptance_gate.py` classifies runtime_regression /
  doc_governance_debt / quality_debt / unknown_failure (no extension_regression class yet).

## AC → gap mapping

| AC (frozen goal §6) | Baseline state | Gap → ID | Priority |
|---|---|---|---|
| AC-1 S2 no-regress | S2 governed path + Skill governed-active present | maintain + guard → S3-G11 (Skill) / cross all | P2 / cross |
| AC-2 MCP governed tool source | MCP plumbing exists, orchestrator HARNESS-ONLY, default-off | wire to prod governed tool path → S3-G03 | P1 |
| AC-3 SubAgent read-only/audit parent-mediated | subagent_system mature, side-effect-free, not activated | promote to governed-active read-only delegation → S3-G04 | P1 |
| AC-4 capability contract (metadata/enable-disable/risk/verify/evidence) | only Skill has its own gate; no shared contract | unify → S3-G02 | P1 |
| AC-5 reference task closed loop w/ MCP+SubAgent | S2 reference-task acceptance exists; no extension use | E2E → S3-G06 (needs S3-G01 spec) | P1 |
| AC-6 real provider key path | S2 AC-7 real smoke exists; no extension coverage | extend real smoke → S3-G07 | P1 |
| AC-7 acceptance gate ext-regression class | gate has 4 classes, no extension_regression | add class → S3-G08 | P2 |
| AC-8 stage governance no-regress | AGENTS.md stage model; S2 archived | maintain → S3-G10 | P2 |
| AC-9 TD-006 release hygiene | TD-006 33 guard failures (doc_governance_debt) | clean guards → S3-G09 | P2 |
| (pre-req) reference task executable spec | goal names "Extension-assisted repo governance task" but no executable spec | pin spec → S3-G01 | P0 |
| (integration) extension evidence/checkpoint/task-state | task evidence/checkpoint exist; extension outputs not integrated | integrate → S3-G05 | P1 |

## TECH_DEBT → S3 routing (only release/AC-affecting enters P0-P2)

- **TD-006** → directly affects AC-9 / release gate → **S3-G09 (P2)**.
- **TD-007** → NOT a release blocker (frozen goal §7) → **deferred → S3-G13 (P4)**.
- **TD-001 / TD-004** (evidence fidelity / pending-tool preview) → may be *touched* by
  S3-G05 extension evidence, but full-fidelity not required for S3 → referenced in
  S3-G05 non-goal boundary; otherwise deferred → S3-G13.
- **TD-002 / TD-003** (legacy facade / dead code) → not S3 triggers → deferred → S3-G13.

## Deferred to S4/Sn (P4, non-goal for S3)

- Scheduler production activation / main-loop wiring → S3-G12 boundary note + S3-G13.
- Full MCP ecosystem (multi-server orchestration, dynamic discovery ecosystem).
- Full multi-agent ecosystem (writable / non-mediated SubAgent delegation).
- Durable task ledger; TD-007 full ruff cleanup.

## Priority sanity check (superpowers gap-completeness)

- Every AC-1..AC-9 maps to ≥1 gap. ✓
- P0 minimal (only the reference-task spec blocks downstream precision). ✓
- 6 P1 = the must-deliver product surface (contract + MCP + SubAgent + integration +
  E2E + real). ✓
- No TECH_DEBT dumped into S3 beyond TD-006 (release-affecting). ✓
- Scheduler / full ecosystems strictly P4 / non-goal. ✓

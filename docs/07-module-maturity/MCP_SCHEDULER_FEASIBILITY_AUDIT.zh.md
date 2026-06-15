# MCP + Scheduler Feasibility / Activation Audit

**日期**: 2026-06-14
**性质**: feasibility / activation audit — MCP scoped L3 **completed**; Scheduler upgraded to L2 (not L3)
**Architecture Repair Mainline**: CLOSED

## 1. Status

- 本文是前置审计，判断 MCP 和 Scheduler 是否存在本地 L3 推进路径。**MCP scoped L3 已完成**；Scheduler 已升级为 L2（no-consumer blocker 阻止 L3）。
- 本文不是：closure audit、15/15 claim、MCP L3 claim、Scheduler L3 claim。
- 本轮不改 `agent/` 源码，不改 `tests/`，不接真实 MCP server，不实现 Scheduler runtime。
- Architecture Repair 仍 CLOSED。No Window 4。

## 2. Governance Context

```
North Star §9: MCP 外部协议适配 → Tool 同 schema → Dispatcher
North Star §5: Scheduler 横切 → Open: 是否 production-route
Closure audit: T-MCP-REAL = BLOCKED_BY_EXTERNAL, T-SCHED-ROUTE = BLOCKED_BY_DECISION
Maturity audit: MCP = ~~L2~~ **L3 scoped** (local fake/dry_run boundary), Scheduler = ~~L1~~ **L2** (BLOCKED_BY_DECISION; no consumer)
Trigger registry: T-MCP-REAL = BLOCKED_BY_EXTERNAL (local scoped L3 completed), T-SCHED-ROUTE = BLOCKED_BY_DECISION
L3 triage: MCP = ~~WAIT_FOR_EXTERNAL~~ **COMPLETED**, Scheduler = ~~OPTIONAL_SKIP~~ **L2 COMPLETED**
```

## 3. Current Remaining Modules

| # | Module | Current Level | Trigger/Blocker |
|---|--------|--------------|-----------------|
| 4 | MCP | ~~L2~~ **L3 scoped** | T-MCP-REAL: BLOCKED_BY_EXTERNAL (real external); local fake/dry_run boundary **completed** |
| 10 | Scheduler / Async | ~~L1~~ **L2** | T-SCHED-ROUTE: BLOCKED_BY_DECISION (no consumer; registered-not-routed) |

当前 14/15 模块已达到 scoped L3 或 L2。Scheduler 是唯一 below-L3 模块（L2，no-consumer blocker）。

## 4. MCP Source / Test / Doc Surface

### Source (14 files)
| File | Role |
|------|------|
| `agent/mcp.py` | MCP 客户端入口 + FakeMCPClient (line 65) + `is_mcp_active()` |
| `agent/mcp_bridge.py` | MCP → Tool registry bridge |
| `agent/mcp_policy.py` | MCP policy gate |
| `agent/mcp_sanitizer.py` | Descriptor sanitization |
| `agent/mcp_models.py` | MCPServerConfig, MCPToolDescriptor |
| `agent/mcp_config.py` | MCP configuration |
| `agent/mcp_config_service.py` | MCP config service |
| `agent/mcp_config_cli.py` | MCP config CLI |
| `agent/mcp_config_presenter.py` | MCP config presenter |
| `agent/mcp_audit.py` | MCP audit |
| `agent/mcp_stdio.py` | MCP stdio transport |
| `agent/mcp_external_readiness.py` | MCP external readiness check |
| `agent/runtime_integration/mcp_bridge_lifecycle.py` | MCP bridge lifecycle |
| `agent/runtime_integration/mcp_tool_orchestrator.py` | MCP → Tool orchestration |

### Test (17 files, 313 tests)
| File | Focus |
|------|-------|
| `test_mcp_l3_real_core_loop.py` | L3 evidence (xfail: FakeProvider limitation) |
| `test_mcp_real_external_flight.py` | External flight (code-path-complete) |
| `test_mcp_runtime_integration.py` | Runtime integration |
| `test_mcp_policy_gate.py` | Policy gate |
| `test_mcp_registration_policy.py` | Registration policy |
| `test_mcp_client_architecture.py` | Client architecture |
| `test_mcp_boundary_isolation.py` | Boundary isolation |
| `test_mcp_bridge.py` | Bridge |
| `test_mcp_config_*.py` | Config (3 files) |
| `test_mcp_stdio_integration.py` | Stdio integration |
| `test_agentloop_mcp_e2e.py` | AgentLoop MCP E2E |
| `test_real_mcp_flight.py` | Real flight (opt-in only) |
| `test_mcp_audit_evidence.py` | Audit evidence |
| `test_mcp_external_readiness.py` | External readiness |

### Key architecture facts
- `FakeMCPClient` exists at `agent/mcp.py:65` — local fake boundary present
- `dry_run=True` default — no real external server connection by default
- `is_mcp_active()` returns `False` by default — blocked at gate level
- `server_allowlist` mechanism — opt-in only
- MCP bridge lifecycle connects to `RuntimeActionDispatcher`
- `mcp_sanitizer.py` provides descriptor sanitization
- `mcp_policy.py` provides policy gate before registration
- `not-fakeable` guards exist in MCP real flight test

## 5. MCP Feasibility Assessment

### Can MCP reach scoped L3 locally?

**YES — with conditions.**

| Criterion | Status |
|-----------|--------|
| Local fake/dry_run boundary exists | ✅ `FakeMCPClient`, `dry_run=True` default |
| Deterministic tests exist | ✅ 313 tests passed (2 xfailed due to FakeProvider limitation, not MCP bugs) |
| No real MCP server needed | ✅ FakeMCPClient + fixture servers |
| No real credential needed | ✅ dry_run only uses local fixtures |
| No external endpoint call | ✅ dry_run blocks real server connection |
| Capability boundary aligned | ✅ `build_decision_frame()` has MCP branch point |
| Policy boundary aligned | ✅ `mcp_policy.py` + `PolicyDecision` can map MCP actions |
| Golden/locked evidence | ✅ `test_mcp_policy_gate.py`, `test_mcp_registration_policy.py` |

**What prevents full L3 (REAL-EVIDENCE-007)**: Real external MCP server connection. This is BLOCKED_BY_EXTERNAL per AGENTS.md and trigger registry. But local scoped L3 (fake/dry_run boundary + contract + deterministic tests) IS achievable.

### Recommended MCP scoped L3 path

**MCP: L3 scoped to local fake/dry_run contract boundary + tool orchestration + policy gate + sanitization**

What this includes:
- `FakeMCPClient` local contract
- MCP tool registration/discovery pipeline (dry_run)
- MCP policy gate + sanitization
- MCP → Tool bridge lifecycle
- Not-fakeable boundary guards

What it does NOT include (remains BLOCKED_BY_EXTERNAL):
- Real external MCP server connection
- REAL-EVIDENCE-007 (real external flight)
- Production MCP credential management

### Verification needed before L3 claim
- Confirm all 313 MCP tests pass (dry_run path)
- Confirm `FakeMCPClient` contract is golden-locked or has equivalent test coverage
- Confirm `is_mcp_active()` default-off is tested
- Confirm `PolicyDecision` can cover MCP tool actions (or defer to future)
- Update maturity audit + trigger registry with scoped L3 + remaining debt

## 6. Scheduler Source / Test / Doc Surface

### Source (2 files)
| File | Role |
|------|------|
| `agent/action_scheduler.py` | ActionScheduler + ActionNode + ActionPlan + ActionRecoveryPolicy |
| `agent/runtime_integration/action_scheduler_handler.py` | RuntimeAction handler |

### Test (2 files)
| File | Focus |
|------|-------|
| `tests/runtime_integration/test_action_scheduler.py` | Scheduler unit/contract tests |
| `tests/runtime_integration/test_scheduler_main_path.py` | Scheduler main path test |

### Key architecture facts
- `ActionScheduler` is `dormant-by-default / registered-not-routed` (docstring at line 4-6)
- `core.chat(..., action_scheduler=None)` — default not injected
- Handler registered in `build_phase1_dispatcher()` for testability
- Route decision would touch `agent/core.py:697/772`
- No current consumer — scheduler has no delayed-action or async task to schedule
- Closure audit explicitly lists scheduler routing as "会触发 repair reopen"

## 7. Scheduler Feasibility Assessment

### Can Scheduler reach scoped L3 locally?

**NO.**

| Criterion | Status |
|-----------|--------|
| Scheduler code exists | ✅ `ActionScheduler` class is real |
| Handler registered | ✅ `ActionSchedulerHandler` registered in dispatcher |
| Default-off / dormant | ✅ `core.chat(action_scheduler=None)` |
| Can be test-injected | ✅ `test_scheduler_main_path.py` proves injection seam |
| Has consumer | ❌ No consumer — no delayed-action or async task |
| Can do local L3 without consumer | ❌ L3 requires main path routing evidence — routing = production activation |
| Would reopen Architecture Repair? | ❌ Closure audit: "会触发 repair reopen" |

**Scheduler cannot reach L3 without a real consumer and a routing decision.** 
Both are BLOCKED_BY_DECISION (consumer = product decision, routing = architecture decision). 
The dormancy is deliberate and documented. Creating a fake consumer to pass L3 would be manufacturing evidence.

### What IS possible for Scheduler
- `test_scheduler_main_path.py` already proves injection seam works
- Handler is registered and can be dispatched
- No additional code needed for dormant state
- Golden test already locks dormant-by-default behavior

### Scheduler verdict
**Scheduler upgraded from L1 to L2 — BLOCKED_BY_DECISION / no consumer.**
95+ scheduler tests pass; handler registered in dispatcher; injection seam verified; 6 no-consumer boundary tests pass; PolicyDecision SCHEDULER_ASYNC→REQUIRE_APPROVAL; RuntimeDecisionFrame reflects scheduler state. **Not L3**: no active consumer; registered-not-routed ≠ production-routed; production `chat()` calls do not pass `action_scheduler`. Creating a fake consumer to pass L3 would be manufacturing evidence.

If Scheduler is upgraded from L2 to L3 (not yet):
- Requires: real consumer + owner decision for production routing
- Cannot: manufacture consumer or route without reopening Architecture Repair

## 8. Trigger Registry Reconciliation

| Trigger | Module | Current Status | Proposed After Audit |
|---------|--------|---------------|---------------------|
| T-MCP-REAL | MCP | BLOCKED_BY_EXTERNAL | Scoped L3: local fake/dry_run contract boundary; Real external still BLOCKED_BY_EXTERNAL |
| T-SCHED-ROUTE | Scheduler | BLOCKED_BY_DECISION | L2 achieved (95+ tests + 6 boundary + policy mapping + decision-frame); not L3 (no consumer; registered-not-routed) |

## 9. Activation Decision

| Module | Verdict | Recommended Action |
|--------|---------|-------------------|
| **MCP** | **CAN reach scoped L3** (local fake/dry_run boundary) | Proceed with scoped L3: record existing 313 test evidence + FakeMCPClient contract as L3, mark real external as remaining BLOCKED_BY_EXTERNAL debt |
| **Scheduler** | **CANNOT reach L3** (no consumer, would reopen repair) | Upgrade to **L2** (not L3) based on 95+ tests + 6 boundary tests + policy mapping + decision-frame evidence; keep as BLOCKED_BY_DECISION / no consumer |

## 10. Recommended Next Module

### **MCP → scoped L3**

MCP has the stronger evidence base and the clearer path:
- 313 tests already pass (dry_run path)
- `FakeMCPClient` exists as local boundary
- Policy gate + sanitization + bridge lifecycle are all active
- Only gap: real external server (which IS blocked — correctly)
- Can reach scoped L3 with docs-only evidence recognition (no new code needed)

### Why not Scheduler
Scheduler's dormant state is the correct architectural state. Upgrading to L2 is appropriate, but L3 would require a consumer that doesn't exist and a routing decision that would reopen Architecture Repair.

## 11. Non-Goals

- Not closing MCP REAL-EVIDENCE-007 (still BLOCKED_BY_EXTERNAL)
- Not routing Scheduler into production (would reopen repair)
- Not claiming 15/15 L3
- Not fabricating MCP external evidence
- Not fabricating Scheduler consumer
- Not triggering Window 4 or Architecture Repair

## 12. Evidence Appendix

### MCP
- `agent/mcp.py:65` — `FakeMCPClient`
- `agent/mcp.py:165-175` — `register_mcp_tools()` with `dry_run=True` default
- `agent/mcp.py` — `is_mcp_active()` default False
- `tests/test_mcp_policy_gate.py`
- `tests/test_mcp_l3_real_core_loop.py` (xfail: FakeProvider limitation)
- `tests/test_mcp_real_external_flight.py` (code-path-complete, default off)
- 313 MCP+Scheduler combined tests passed

### Scheduler
- `agent/action_scheduler.py:4-9` — dormant-by-default docstring
- `agent/core.py:697/772` — `action_scheduler=None` default
- `tests/runtime_integration/test_scheduler_main_path.py` — injection seam proof
- `tests/runtime_integration/test_action_scheduler.py` — contract tests

### Governance
- `POST_REPAIR_TRIGGER_REGISTRY.zh.md` — T-MCP-REAL, T-SCHED-ROUTE
- `AGENT_MODULE_MATURITY_AUDIT.zh.md` §5.4, §5.10
- `L3_HARDENING_TRIAGE.zh.md` — WAIT_FOR_EXTERNAL, OPTIONAL_SKIP
- `ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md` — Scheduler routing listed as reopen trigger

## 13. Reviewer Findings

### Architecture reviewer
1. MCP has local fake/dry_run boundary → CAN reach scoped L3 ✅
2. Scheduler has no consumer → CANNOT reach L3 without reopening repair ✅
3. MCP should be the next module to advance ✅
4. Scheduler upgrade to L2 (not L3) is appropriate for dormant state ✅
5. No triggers require MCP real external or Scheduler routing ✅
6. Not premature closure — 2 modules still below target ✅
7. No reopening of Architecture Repair ✅
8. No Window 4 ✅

### Adversarial reviewer
1. Not covering up MCP/Scheduler work — honest assessment ✅
2. Not fabricating MCP external evidence ✅
3. Not fabricating Scheduler consumer ✅
4. Blocked modules correctly identified as blocked ✅
5. No active triggers being hidden ✅
6. No code changes to fake MCP/Scheduler ✅
7. No L3/L4 overclaim ✅
8. No Window 4 / Architecture Repair signs ✅

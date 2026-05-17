# SubAgent Dogfood Plan

Status: Tiered dogfood scenarios for the production-grade formal SubAgent System.

Every scenario must produce redacted audit packets with no private data.

## Dogfood Tiers

| Tier | Name | Execution | Config Gate | Status |
|------|------|-----------|-------------|--------|
| L1 | Synthetic Deterministic | local_fake / local_deterministic | none | Required for v1 |
| L2 | Real LLM Read-Only | real_llm_readonly | `subagent.real_llm_readonly.enabled=true` | Gated |
| L3 | Real LLM Tool-Requesting | real_llm_tool_requesting | `subagent.tool_requesting.enabled=true` | Gated |
| L4 | Sandboxed Tool-Capable | sandboxed_tool_capable | `subagent.sandbox.enabled=true` | Future |
| L5 | Worktree Coding | worktree-capable | explicit phase approval | Future |

Higher tiers inherit all scenarios from lower tiers for regression coverage.

---

## L1: Synthetic Deterministic (Required for v1)

### Scenario 1.1: Safe Local Code Review

- **Goal**: Verify SubAgent executes a bounded code review task using fake/local
  execution with `read_file` tool only.
- **Setup**: `role=reviewer`, `allowed_tools=(read_file,)`,
  `max_iterations_default=1`, `memory_scope=none`.
- **Steps**: Parent delegates review task → context packaged → fake execution
  runs 1 iteration → result returned with review summary.
- **Expected**: `status=ok`, `stop_reason=task_completed`, `iterations_used=1`,
  `tools_requested` includes `read_file`, `SubAgentAuditRecord` complete.

### Scenario 1.2: Test Repair Delegation

- **Goal**: SubAgent analyzes a failing test and proposes a fix (tool request
  forwarded, not executed).
- **Setup**: `role=tester`, `allowed_tools=(read_file, grep)`,
  `max_iterations_default=2`.
- **Steps**: Parent delegates test repair analysis → SubAgent requests
  `read_file` (forwarded) → requests `grep` (forwarded) → requests
  `apply_patch` (blocked, outside allowed_tools).
- **Expected**: `status=needs_confirmation` or `status=ok` with
  `tools_denied` containing `apply_patch`.

### Scenario 1.3: RFC Alignment Check

- **Goal**: SubAgent verifies implementation against RFC contracts.
- **Setup**: `role=auditor`, `allowed_tools=(read_file,)`, `max_iterations_default=1`.
- **Expected**: `status=ok`, `confidence >= 0.5`, audit record shows 1 tool requested.

### Scenario 1.4: Memory Boundary — read_context

- **Goal**: SubAgent receives read-only memory context but cannot write.
- **Setup**: `memory_scope=read_context`.
- **Expected**: Memory context present in context package. Memory proposal
  attempt blocked. `memory_proposals_count=0`.

### Scenario 1.5: Memory Boundary — propose

- **Goal**: SubAgent emits memory proposal that flows through governance.
- **Setup**: `memory_scope=propose`.
- **Expected**: `memory_proposals_count=1`, proposal carries `source=subagent`,
  proposal queued, not auto-persisted.

### Scenario 1.6: Skill Boundary — L1 Metadata Only

- **Goal**: SubAgent receives L1 metadata for allowed Skills, not full bodies.
- **Setup**: `allowed_skills=(code-review-checklists,)`.
- **Expected**: L1 metadata present in context package. Full body loading
  follows Skill System progressive disclosure.

### Scenario 1.7: Tool Boundary — Upper Bound Intersection

- **Goal**: SubAgent cannot request tools outside intersection.
- **Setup**: `descriptor.allowed_tools=(read_file, grep)`,
  `request.allowed_tools=(read_file,)`.
- **Expected**: `grep` denied, `read_file` allowed. Effective tools = `(read_file,)`.

### Scenario 1.8: High-Risk Tool Rejection

- **Goal**: Tool boundary preserves ToolRegistry confirmation.
- **Setup**: `allowed_tools=(shell_exec,)` — high-risk tool.
- **Expected**: `status=needs_confirmation`, confirmation gated by parent.
  Tool boundary does not downgrade risk.

### Scenario 1.9: Hidden Tool Never Exposed

- **Goal**: Hidden/internal tools never visible to SubAgent.
- **Setup**: `allowed_tools=(hidden_debug_tool,)`.
- **Expected**: Hidden tool filtered from `allowed_tools` snapshot.
  Error if effective tools become empty.

### Scenario 1.10: max_iterations Hard Stop

- **Goal**: Bounded execution stops exactly at max.
- **Setup**: `max_iterations=2`.
- **Expected**: `stop_reason=max_iterations_exceeded`, `iterations_used=2`,
  best-effort summary returned.

### Scenario 1.11: Descriptor Not Found

- **Goal**: Unknown SubAgent name → graceful failure.
- **Setup**: `role=nonexistent`.
- **Expected**: `status=error`, error code `DESCRIPTOR_NOT_FOUND`,
  `recoverable=false`.

### Scenario 1.12: Policy Violation — Nested Delegation

- **Goal**: `max_nested_depth=0` blocks nested delegation.
- **Setup**: SubAgent-A attempts to delegate to SubAgent-B.
- **Expected**: `SubAgentPolicyError` raised. No SubAgent-B execution.

### Scenario 1.13: Checkpoint Interruption and Resume

- **Goal**: Interrupted delegation recoverable without replaying high-risk tools.
- **Setup**: `max_iterations=5`, interrupted after iteration 3.
- **Expected**: Checkpoint contains no full prompts/secrets/raw outputs.
  `pending_confirmation` preserved. Resume does not replay tools.

### Scenario 1.14: Low Confidence Delegation

- **Goal**: SubAgent self-reports low confidence when task is ambiguous.
- **Setup**: Task intentionally vague.
- **Expected**: `confidence < 0.5`, `warnings` non-empty.

### Scenario 1.15: Audit Record Completeness

- **Goal**: Every delegation produces complete, redacted audit record.
- **Expected**: All 16 audit fields present, no secrets, correlation IDs match.

### Scenario 1.16: Context Budget Overflow

- **Goal**: Context package respects `max_context_chars`.
- **Setup**: `max_context_chars=1000`, task requires large file summaries.
- **Expected**: Summaries trimmed to fit budget. Warning emitted.
  `stop_reason != max_context_exceeded` (packaging succeeds with trimming).

### Scenario 1.17: Execution Mode Selection

- **Goal**: Mode selected by parent, bounded by descriptor.
- **Setup**: Descriptor `supported_modes=(local_fake, local_deterministic)`,
  parent requests `real_llm_readonly`.
- **Expected**: Mode selection denied. `SubAgentModeError` raised.

### Scenario 1.18: Parent Adjudication — Accept

- **Goal**: Parent accepts result and merges summary.
- **Expected**: `ParentAdjudicationResult(action=accept)`, `merged_summary`
  populated, parent context updated.

### Scenario 1.19: Parent Adjudication — Reject

- **Goal**: Parent rejects result with reason.
- **Expected**: `ParentAdjudicationResult(action=reject)`, `reason` populated.

### Scenario 1.20: Parent Adjudication — Revise

- **Goal**: Parent requests revision with updated task.
- **Expected**: `ParentAdjudicationResult(action=revise)`, `revised_request`
  populated, new `delegation_id` generated for revision run.

---

## L2: Real LLM Read-Only (Gated)

### Scenario 2.1: Real LLM Code Review Reasoning

- **Goal**: SubAgent with real LLM performs code review reasoning.
- **Setup**: `execution_mode=real_llm_readonly`, config gate open,
  `allowed_tools=(read_file,)`, real code file as input.
- **Steps**: Parent delegates → context packaged with file summaries → real LLM
  invoked via Runtime → response parsed → result returned.
- **Expected**: `status=ok` or `status=task_completed_low_confidence`,
  `stop_reason=task_completed`. Response from real model. No tool execution.

### Scenario 2.2: Real LLM RFC Alignment Reasoning

- **Goal**: Real LLM verifies implementation against RFC.
- **Setup**: `execution_mode=real_llm_readonly`, config gate open.
- **Expected**: SubAgent produces structured alignment report from real LLM
  reasoning. `confidence` extracted from response.

### Scenario 2.3: Real LLM — Config Gate Closed

- **Goal**: Real LLM mode blocked when config gate is closed.
- **Setup**: `execution_mode=real_llm_readonly`, config gate closed.
- **Expected**: `SubAgentModeError` raised. No provider call made.

### Scenario 2.4: Real LLM — ThinkingBlock Handling

- **Goal**: SubAgent handles ThinkingBlock in model response.
- **Setup**: Provider returns `ThinkingBlock` in response content.
- **Expected**: TextBlock content extracted correctly. ThinkingBlock content
  treated as internal reasoning (not exposed in summary).

### Scenario 2.5: Real LLM — Context Budget at LLM Limit

- **Goal**: Context package respects model context window limit.
- **Setup**: Large task that would exceed model context window.
- **Expected**: Context package trimmed to fit. Warning emitted.

---

## L3: Real LLM Tool-Requesting (Gated)

### Scenario 3.1: Real LLM Test Repair with Tool Requests

- **Goal**: SubAgent requests real tool execution via parent mediation.
- **Setup**: `execution_mode=real_llm_tool_requesting`, config gate open.
- **Steps**: SubAgent analyzes failing test → requests `read_file` for test
  file → parent executes and returns result → SubAgent requests `grep` for
  function → parent executes → SubAgent returns analysis.
- **Expected**: `tools_requested` contains `read_file` and `grep`,
  `tools_executed` count matches. `status=ok`.

### Scenario 3.2: Tool Request Blocked by Boundary

- **Goal**: Tool request outside effective bounds is denied.
- **Setup**: SubAgent requests tool not in `allowed_tools`.
- **Expected**: `tools_denied` includes blocked tool. `SubAgentTraceEvent(tool_denied)`.
  SubAgent continues or stops with `tool_blocked`.

### Scenario 3.3: High-Risk Tool Pauses for Confirmation

- **Goal**: High-risk tool request triggers confirmation.
- **Setup**: SubAgent requests `shell_exec` (high-risk).
- **Expected**: `status=needs_confirmation`. `SubAgentTraceEvent(confirmation_required)`.
  Execution paused until parent adjudicates.

### Scenario 3.4: Config Gate Closed — Tool-Requesting Blocked

- **Goal**: Tool-requesting mode blocked when config gate closed.
- **Setup**: `execution_mode=real_llm_tool_requesting`, config gate closed.
- **Expected**: `SubAgentModeError` raised.

---

## L4: Sandboxed Tool-Capable (Future)

### Scenario 4.1: Sandbox File Read/Write in Tmp Root

- **Goal**: SubAgent reads and writes files within sandbox root.
- **Setup**: `execution_mode=sandboxed_tool_capable`, sandbox root at
  `/tmp/subagent-{id}/`.
- **Expected**: Read/write constrained to sandbox root. Real repo not mutated.

### Scenario 4.2: Sandbox Tool Blocked Outside Root

- **Goal**: Tool execution outside sandbox root is blocked.
- **Setup**: SubAgent attempts `write_file` to real repo path.
- **Expected**: `ToolCheckResult(allowed=false)`. Tool denied.

### Scenario 4.3: Sandbox Code Generation

- **Goal**: SubAgent generates code files in sandbox.
- **Setup**: Task requires generating a new module.
- **Expected**: Files created in sandbox root. Returned as artifacts for parent
  review. No real repo mutation.

### Scenario 4.4: Shell Request Blocked in Sandbox

- **Goal**: Shell execution blocked even in sandbox (requires explicit approval).
- **Setup**: SubAgent requests `shell_exec` in sandbox.
- **Expected**: Denied by policy. `external_process_allowed=false`.

### Scenario 4.5: Sandbox Cleanup After Delegation

- **Goal**: Sandbox root cleaned up after delegation completes.
- **Expected**: Sandbox directory deleted. No artifacts leaked to filesystem.

---

## L5: Worktree Coding (Future, Deferred)

### Scenario 5.1: Worktree Request Deferred

- **Goal**: Worktree isolation requires explicit phase approval.
- **Expected**: `SubAgentPolicy.worktree_isolation_allowed=false`. Request
  rejected with clear message about future phase.

### Scenario 5.2: Multi-SubAgent Parallel Review (Future)

- **Goal**: Multiple SubAgents run concurrently for multi-perspective review.
- **Expected**: Defined as L5 capability. Requires orchestration phase.

---

## Complex Cross-Tier Scenarios

### Scenario X.1: Parent Rejects and Revises

- **Goal**: Parent rejects initial result, requests revision, SubAgent improves.
- **Tiers**: L1-L3.
- **Steps**: Initial delegation → SubAgent returns result → Parent rejects with
  reason → Parent creates revised request with clarified task → SubAgent runs
  revision → returns improved result → Parent accepts.
- **Expected**: `revision_count=1` in final audit. Revision history preserved.

### Scenario X.2: Low Confidence with Revision

- **Goal**: Low-confidence result triggers revision request.
- **Tiers**: L1-L3.
- **Expected**: First result `confidence < 0.5`. Parent requests revision.
  Revised result has higher confidence or explicit explanation.

### Scenario X.3: Conflicting Findings

- **Goal**: SubAgent finds internal contradictions in analyzed code.
- **Tiers**: L2-L3.
- **Expected**: `warnings` include `conflicting_findings`. Confidence reduced.
  Parent adjudicates with awareness of conflict.

### Scenario X.4: SubAgent Asks for Clarification

- **Goal**: SubAgent determines task is underspecified.
- **Tiers**: L1-L3.
- **Expected**: `stop_reason=needs_clarification`, `clarification_question`
  populated. Parent answers and revises.

### Scenario X.5: Partial Tool Failure

- **Goal**: One tool succeeds, another fails.
- **Tiers**: L2-L3.
- **Expected**: `status=ok` with `warnings` describing failed tool.
  `tools_executed` and `tools_denied` both populated.

### Scenario X.6: Full Trace Completeness

- **Goal**: Verify trace covers all 15 event types.
- **Tiers**: L1 (event types) + L2-L3 (real events).
- **Expected**: Every required event type emitted. Events ordered by timestamp.

## Dogfood Execution Rules

- L1: no real LLM, no network, no `.env`, no real sessions/runs.
- L2: real LLM via Runtime-mediated provider call; config gate must be open.
  No tool execution.
- L3: real LLM + parent-mediated tool execution; config gate must be open.
- L4: sandbox execution; config gate must be open; sandbox root scoped.
- L5: requires explicit phase approval.
- All tiers: audit packets redacted; no secrets, full prompts, or raw file
  contents in output.

## Selected Test Commands

```bash
# L1: v1 required
python -m pytest tests/test_subagent_dogfood.py -q -k "L1"

# L2: gated
python -m pytest tests/test_subagent_dogfood.py -q -k "L2"

# L3: gated
python -m pytest tests/test_subagent_dogfood.py -q -k "L3"

# All available tiers
python -m pytest tests/test_subagent_dogfood.py -q
```

## Exit Criteria

- L1: all scenarios deterministic; audit packets pass redaction; no private data.
- L2: real LLM scenarios pass under config gate; gate closed blocks execution.
- L3: tool-requesting scenarios pass; no direct tool execution.
- L4: sandbox contract valid; sandbox cleanup confirmed.
- L5: deferred contract defined.

# SubAgent Dogfood Plan

Status: Synthetic/local dogfood scenarios for the formal SubAgent System. No real
LLM, no network, no `.env`, no real sessions/runs.

Every scenario is local-only, deterministic, and must produce redacted audit
packets with no private data.

## Scenarios

### Scenario 1: Safe Local Code Review

- **Goal**: Verify SubAgent executes a bounded code review task using fake/local
  execution with `read_file` tool only.
- **Setup**: `SubAgentDescriptor` with `role=reviewer`, `allowed_tools=(read_file,)`,
  `max_iterations_default=1`, `memory_scope=none`.
- **Steps**:
  1. Parent creates `SubAgentRequest` with `task="Review foo.py for style issues"`,
     `allowed_tools=(read_file,)`, `max_iterations=1`.
  2. Delegation adapter assembles `SubAgentContext`.
  3. Executor runs fake/local execution for 1 iteration.
  4. `SubAgentResult` returned with `status=ok`, `summary` includes review notes,
     `artifacts` references reviewed file.
- **Expected**: `status=ok`, `iterations_used=1`, no tool denied, no memory proposals,
  `SubAgentAuditRecord` complete.

### Scenario 2: Test Repair Delegation

- **Goal**: SubAgent analyzes a failing test and proposes a fix (tool request
  forwarded, not executed).
- **Setup**: `role=tester`, `allowed_tools=(read_file, grep)`,
  `max_iterations_default=2`.
- **Steps**:
  1. Parent delegates test repair analysis.
  2. SubAgent requests `read_file` for the failing test file (forwarded), then
     requests `grep` for the function under test (forwarded).
  3. SubAgent returns `tool_requests=(apply_patch,)` — a tool outside its
     `allowed_tools`.
  4. Tool boundary blocks `apply_patch`.
- **Expected**: `status=needs_confirmation`, `tool_requests` contains `apply_patch`,
  `tools_denied` in audit record includes `apply_patch`.

### Scenario 3: RFC Alignment Check

- **Goal**: SubAgent verifies implementation against RFC contracts.
- **Setup**: `role=auditor`, `allowed_tools=(read_file,)`, `max_iterations_default=1`.
- **Steps**:
  1. Parent delegates RFC alignment check.
  2. SubAgent reads implementation file, compares against RFC contract.
  3. Returns `status=ok` with alignment report.
- **Expected**: `status=ok`, `confidence >= 0.5`, audit record shows 1 tool requested.

### Scenario 4: Memory Boundary — read_context

- **Goal**: SubAgent receives read-only memory context but cannot write.
- **Setup**: `memory_scope=read_context`, `role=reviewer`.
- **Steps**:
  1. Parent provides memory context via adapter.
  2. SubAgent reads context and produces review.
  3. SubAgent attempts to emit memory proposal — blocked because `memory_scope` is
     `read_context`, not `propose`.
- **Expected**: Memory boundary rejects proposal. `memory_proposals_count=0` in audit.

### Scenario 5: Memory Boundary — propose

- **Goal**: SubAgent emits memory proposal that flows through governance.
- **Setup**: `memory_scope=propose`, `role=reviewer`.
- **Steps**:
  1. Parent delegates review task.
  2. SubAgent discovers a noteworthy pattern and emits a `MemoryProposal`.
  3. Proposal validated by `SubAgentMemoryBoundary.check_proposal()`.
  4. Proposal queued for parent governance adjudication (not auto-approved).
- **Expected**: `memory_proposals_count=1`, proposal carries `source=subagent` metadata,
  proposal is queued, not persisted.

### Scenario 6: Skill Boundary — L1 Metadata Only

- **Goal**: SubAgent receives L1 metadata for allowed Skills, not full bodies.
- **Setup**: `allowed_skills=(code-review-checklists,)`, `role=reviewer`.
- **Steps**:
  1. Parent delegates review task.
  2. Skill boundary checks `code-review-checklists` is in `allowed_skills`.
  3. SubAgent receives Skill name, description, tags only (L1).
  4. SubAgent requests full Skill body — Skill System controls progressive disclosure.
- **Expected**: Skill boundary passes through to Skill System. L1 metadata present,
  full body loading follows progressive disclosure.

### Scenario 7: Tool Boundary — Upper Bound Enforcement

- **Goal**: SubAgent cannot request tools outside `descriptor.allowed_tools ∩ request.allowed_tools`.
- **Setup**: `descriptor.allowed_tools=(read_file, grep)`, `request.allowed_tools=(read_file,)`.
- **Steps**:
  1. Parent delegates with restricted tool list.
  2. SubAgent requests `grep` — blocked by tool boundary (not in request).
  3. SubAgent requests `read_file` — allowed (in both).
- **Expected**: `grep` denied, `read_file` allowed. `tools_denied` includes `grep`.
  Effective tools = `(read_file,)`.

### Scenario 8: High-Risk Tool Rejection

- **Goal**: Tool boundary preserves ToolRegistry confirmation for high-risk tools.
- **Setup**: `allowed_tools=(shell_exec,)` — tool is high-risk in ToolRegistry.
- **Steps**:
  1. Parent delegates with `shell_exec` in allowed_tools.
  2. SubAgent requests `shell_exec`.
  3. Tool boundary checks ToolRegistry → high-risk, confirmation required.
  4. Tool boundary returns `needs_confirmation`; SubAgent cannot skip.
- **Expected**: `status=needs_confirmation`, confirmation gated by parent/runtime.
  Tool boundary does not downgrade risk.

### Scenario 9: Hidden Tool Never Exposed

- **Goal**: Hidden/internal tools are never visible to SubAgent.
- **Setup**: `allowed_tools=(hidden_debug_tool,)` in descriptor.
- **Steps**:
  1. Registry loads descriptor.
  2. Tool boundary validates `allowed_tools`.
  3. `hidden_debug_tool` is marked hidden in ToolRegistry → removed from effective tools.
- **Expected**: Hidden tool never appears in `tool_snapshot`. Error if descriptor
  lists only hidden tools and effective tools become empty.

### Scenario 10: max_iterations Hard Stop

- **Goal**: Bounded execution stops exactly at `max_iterations`.
- **Setup**: `max_iterations=2`, fake/local execution.
- **Steps**:
  1. Parent delegates task.
  2. Executor runs iteration 1, then iteration 2.
  3. Attempted iteration 3 → blocked.
  4. Result returned with `status=max_iterations_exceeded` and best-effort summary.
- **Expected**: `iterations_used=2`, `max_iterations=2`, `status=max_iterations_exceeded`.
  Audit record shows exactly 2 iterations.

### Scenario 11: Delegation Failure — Descriptor Not Found

- **Goal**: Registry returns `None` for unknown SubAgent name; delegation fails
  gracefully.
- **Setup**: `role=nonexistent`, registry has no such descriptor.
- **Steps**:
  1. Parent creates `SubAgentRequest` with `role=nonexistent`.
  2. Registry lookup returns `None`.
  3. Delegation adapter returns `SubAgentResult(status=error)` with
     `SubAgentError(code=DESCRIPTOR_NOT_FOUND)`.
- **Expected**: `status=error`, error code `DESCRIPTOR_NOT_FOUND`, `recoverable=false`.

### Scenario 12: Delegation Failure — Policy Violation

- **Goal**: Delegation blocked when request violates `SubAgentPolicy`.
- **Setup**: `SubAgentPolicy.max_nested_depth=0`, request attempts nested delegation.
- **Steps**:
  1. Parent attempts to delegate to SubAgent-A.
  2. SubAgent-A attempts to delegate to SubAgent-B.
  3. Policy check blocks: `max_nested_depth=0`.
- **Expected**: `SubAgentPolicyError` raised. No SubAgent-B execution. Audit record
  captures policy violation.

### Scenario 13: Checkpoint Interruption and Resume

- **Goal**: Interrupted delegation is recoverable via checkpoint summary without
  replaying high-risk tools.
- **Setup**: `max_iterations=5`, delegation interrupted after iteration 3.
- **Steps**:
  1. Parent delegates task.
  2. Executor runs 3 iterations, then interruption occurs.
  3. `SubAgentCheckpointSummary` written with correlation metadata only.
  4. On resume, Parent reads checkpoint summary.
  5. Parent decides: re-delegate or explain. High-risk tools NOT replayed.
- **Expected**: Checkpoint contains no full prompts, no secrets, no raw tool outputs.
  `pending_confirmation` preserved. Resume does not replay tool execution.

### Scenario 14: Ambiguous Delegation — Low Confidence

- **Goal**: SubAgent self-reports low confidence when task is ambiguous.
- **Setup**: `role=reviewer`, task is intentionally vague.
- **Steps**:
  1. Parent delegates with `task="check the code"` (no specifics).
  2. SubAgent runs, finds insufficient guidance.
  3. Returns `status=ok` but `confidence < 0.5` and `warnings` include
     `ambiguous_task`.
- **Expected**: `confidence < 0.5`, warnings non-empty, summary explains ambiguity.

### Scenario 15: Audit Record Completeness

- **Goal**: Every delegation produces a complete, redacted audit record.
- **Setup**: Standard delegation, any role.
- **Steps**:
  1. Parent delegates task.
  2. SubAgent completes delegation.
  3. Audit record verified: all 11 fields present, no secrets, no raw prompts,
     no large artifacts, correlation IDs match.
- **Expected**: `SubAgentAuditRecord` is complete and sanitized. `delegation_id`
  matches, `parent_trace_id` matches, `elapsed_ms > 0`.

## Dogfood Execution Rules

- All scenarios run with fake/local execution only.
- No real LLM invocation.
- No network access.
- No `.env` reading.
- No real `sessions/` or `runs/` access.
- Audit packets must be redacted: no secrets, no full prompts, no raw file contents.
- `subagent_name` in audit must be anonymized if referencing real project SubAgents.

## Selected Test Command

```bash
python -m pytest tests/test_subagent_dogfood.py -q
```

## Exit Criteria

- All 15 scenarios produce deterministic results.
- All audit packets pass redaction check.
- No private data in any output.
- Fake/local execution confirmed — no real LLM path exercised.

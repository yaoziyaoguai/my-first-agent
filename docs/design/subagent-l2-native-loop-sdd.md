# D-01 — SubAgent L2 Native Loop SDD

**Date**: 2026-06-02
**Status**: active
**Type**: Next-stage design (B3 SubAgent L2)
**Parent**: historical D-01 direction; current status lives in `docs/PROJECT_STATUS.md`.
**L1 baseline**: `docs/design/subagent-l1-l2-execution-contract.md` §2.3
**REAL-EVIDENCE-006**: CLOSED (credible) — 12/12 PASS with real provider

## Background

L1 SubAgent delegation (`execute_l1()`) verifies the parent→child→tool mediation→result
chain with real provider (REAL-EVIDENCE-006). The child loop iterates up to
`max_iterations` with parent-mediated tool execution and memory proposals. L1 is
complete and credible.

L2 adds agent-native capabilities: independent stop condition, child-initiated
revision, batched proposals, deepened tool access, and removal of legacy shortcut
paths. L2 is the "native loop" — the child agent behaves like a real agent
within its bounded context, not just a tool-calling wrapper.

## Goal

Define the L2 execution contract, data model changes, and policy rules. This SDD
scopes the L2 specification phase — implementation follows in a separate TDD plan.

## Scope

### In scope

1. **Independent stop condition**: child can emit `stop_reason=TASK_COMPLETED`
   without hitting `max_iterations`, based on its own judgment
2. **Parent adjudication mandatory gate**: result MUST pass `adjudicate_result()`
   before entering parent context; reject/revision flow formalized
3. **Child-initiated revision request**: child can return `needs_clarification`
   with a `clarification_question`; parent can respond with revised context
4. **Batched memory proposals**: child proposes multiple memories in one batch
   instead of one-at-a-time
5. **Deepened tool access**: `grep`, `glob` added to child's allowed tool set
   (read-only, bounded)
6. **Nested delegation guard**: `max_nested_depth=0` retained for L2 (no
   grandchild agents yet)
7. **RuntimeDecisionFrame update**: `subagent_available=True`, `subagent_level="L1"`
   (L2 gated behind `SubAgentPolicy.real_llm_tool_requesting_allowed`)
8. **Legacy L0 shortcut removal**: `delegate_once()` → probe-only, CLI delegation
   path consolidated to L1 executor

### Out of scope (future L2+/L3)

- Grandchild delegation (`max_nested_depth > 0`)
- Sandboxed tool execution (`SANDBOXED_TOOL_CAPABLE` mode)
- Autonomous tool execution without parent mediation
- Real multi-instance identity propagation for child agents
- L2 real provider dogfood (REAL-EVIDENCE-xxx — future debt)

## Design

### 1. L2 Execution Flow

```
Parent (core.chat CLI delegation → dispatcher)
  → SubAgentDelegateL2Handler (NEW)
    → delegate_l2(request, registry, provider, tool_mediator, dispatcher)
      → build_context_package(...)
      → execute_l2(context_package, ...)         ← NEW executor
        |
        ├─ Build child system prompt (L2 enhanced: stop condition rules,
        │    batch proposal format, revision request format)
        ├─ Build child_tools from TOOL_REGISTRY (L2: grep, glob added)
        ├─ Enter child turn loop (1..max_iterations):
        │   ├─ provider.create(system, child_messages, child_tools)
        │   ├─ Parse response for:
        │   │   ├─ text blocks (summary/progress)
        │   │   ├─ tool_use blocks (parent-mediated)
        │   │   └─ stop_signal block (NEW: explicit stop intent)
        │   ├─ If stop_signal: set stop_reason, break
        │   ├─ For each tool_use: mediate through parent
        │   └─ If needs_revision: break with clarification_question
        ├─ After loop:
        │   ├─ If memory_scope=="propose": batch-mediate memory proposals
        │   └─ Build SubAgentResult with stop_reason + proposals
        └─ Return SubAgentResult
      → adjudicate_result(result, request)   ← mandatory gate
      → if rejected/needs_revision and within max_revisions:
          → build revised context → re-delegate (up to max_revisions times)
      → SubAgentRun
```

### 2. New/Changed Types

#### `SubAgentStopReason` — add `TASK_COMPLETED_BY_CHILD`

```python
TASK_COMPLETED_BY_CHILD = "task_completed_by_child"
# Child explicitly signaled completion (vs. max_iterations exhaustion)
```

#### `SubAgentResult` — add `batch_memory_proposals`

```python
batch_memory_proposals: tuple[MemoryProposal, ...] = ()
# Multiple proposals batched by child (vs. single proposal in L1)
```

#### `SubAgentRun` — add `revision_history`

```python
revision_history: tuple[SubAgentRun, ...] = ()
# Previous runs in this delegation chain (when parent requests revision)
```

### 3. Parent Adjudication Gate

L1 adjudication exists but is advisory — the parent can technically ignore the
result. L2 makes it a mandatory gate:

- `accept`: result enters parent context, evidence dispatched
- `reject`: delegation failed, `SubAgentError` raised
- `request_revision`: parent provides revised context, child re-executes
  (up to `max_revisions`), previous run stored in `revision_history`
- `ask_user`: NOT in scope for L2 (requires TUI integration)

### 4. Independent Stop Condition

The child system prompt includes explicit stop condition rules:

```
You may end your turn with STOP when:
- The task is complete and you have produced a final summary
- You need clarification from the parent (set clarification_question)
- You have exhausted the tools available to you

Do NOT stop when:
- You are still waiting for a tool result in the next iteration
- The task is partially complete and tools are still available
```

The `execute_l2()` loop checks for a `stop_signal` in the parsed response. If
present and valid, the loop exits with `TASK_COMPLETED_BY_CHILD` even if
`max_iterations` is not exhausted.

### 5. Batched Memory Proposals

Instead of proposing memory one key-value pair at a time (L1), L2 allows the
child to propose a batch:

```python
# Child response includes batch_memory block
{
  "batch_memory": [
    {"key": "user:preference:theme", "value": "dark", "scope": "user"},
    {"key": "project:convention:naming", "value": "snake_case", "scope": "project"}
  ]
}
```

The `mediate_child_memory_request()` interface is extended with a batch variant:
```python
mediate_child_memory_batch(proposals: tuple[MemoryProposal, ...]) -> tuple[RoutedMemoryProposal, ...]
```

### 6. Deepened Tool Access

L2 expands the child's allowed tools from `read_file` only to include:

| Tool | Category | Rationale |
|------|----------|-----------|
| `read_file` | existing | Read file contents |
| `grep` | NEW | Search codebase for patterns |
| `glob` | NEW | List files matching pattern |

All tools remain read-only. Write/execute tools (shell, file_write, etc.)
remain blocked at the SubAgentPolicy gate.

### 7. RuntimeDecisionFrame Update

```python
# Current (L0-only):
subagent_available=False,
subagent_level="L0",

# After L2 SDD:
subagent_available=True,
subagent_level="L1",         # L1 is the production baseline
subagent_l2_gated=True,      # L2 gated behind policy
```

The frame reflects that L1 is available and L2 is gated behind
`SubAgentPolicy.real_llm_tool_requesting_allowed`.

### 8. Legacy L0 Shortcut Removal

`delegate_once()` (L0 deterministic keyword-match) is demoted to probe-only:
- No longer callable from CLI delegation path
- Only fires as SUBAGENT_DELEGATE_L0 probe from turn-end hook
- CLI delegation path consolidated to `delegate_l1()` path

## Files

| File | Change |
|------|--------|
| `agent/subagent_system/executor.py` | NEW: `execute_l2()` function |
| `agent/subagent_system/delegation.py` | NEW: `delegate_l2()` function |
| `agent/subagent_system/execution_mode.py` | ADD: `TASK_COMPLETED_BY_CHILD` stop reason |
| `agent/subagent_system/result.py` | ADD: `batch_memory_proposals`, `revision_history` |
| `agent/subagent_system/runtime.py` | ADD: L2 transition helpers |
| `agent/runtime_decision_frame.py` | UPDATE: subagent_available/level/l2_gated |
| `agent/runtime_integration/schema.py` | ADD: `SUBAGENT_DELEGATE_L2`, `SUBAGENT_CHILD_BATCH_MEMORY` |
| `agent/runtime_integration/subagent_delegate_l2.py` | NEW: L2 handler |
| `agent/runtime_integration/phase1_hook.py` | UPDATE: register L2 handler |
| `docs/design/subagent-l1-l2-execution-contract.md` | UPDATE: L2 § marked "designed" |

## What's Blocked (Future Real-Env Task)

| Item | Reason |
|------|--------|
| Real provider L2 dogfood | Needs valid API key (SEC-001) |
| Model stop condition quality | Can only verify with real LLM |
| Child-initiated revision quality | Needs real model to test "needs_clarification" flow |
| Token/cost measurement | Needs real provider billing data |
| REAL-EVIDENCE-L2 | Full evidence chain closure needs real provider E2E |

## Verification (What Can Be Tested Without Real Provider)

- Contract tests with `_SpyProvider` (scripted stop_signal, batch_memory, revision)
- Policy gate tests (L2 gated, allowed_tools expansion, nested depth)
- Adjudication gate tests (accept/reject/revision cycle)
- Batch memory mediation tests
- RuntimeDecisionFrame field tests
- Legacy L0 shortcut removal regression tests

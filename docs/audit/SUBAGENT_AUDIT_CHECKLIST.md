# SubAgent System Audit Checklist

Status: Security and governance audit checklist for the production-grade formal
SubAgent System. Run before any SubAgent code enters the production path. All
items must be verified by an independent reviewer.

Production-grade target architecture is preserved, but implementation readiness
starts at Capability L0 safe-local baseline. L1/L2 are gated. L3/L4/L5 are
contract/future unless explicitly approved. Gated/future capability must never
be treated as default runtime behavior.

Naming convention:

- **Capability Level = L0-L5**.
- **Dogfood Tier = T1-T6**.
- **Implementation Phase = Phase 0-N**.
- **Audit Priority = P0-P3**.

## P0 — Governance Bypass (Blockers)

### Tool & Execution Governance

- [ ] **P0.1 ToolRegistry bypass**: Confirm SubAgent cannot execute tools directly.
  All tool execution flows through `tool_executor` under Parent Runtime.
  `SubAgentToolBoundary.check()` is a pure check — no execution path.
- [ ] **P0.2 Tool risk downgrade**: Confirm SubAgent cannot lower a tool's risk
  level. ToolRegistry risk is authoritative regardless of SubAgent
  `allowed_tools`.
- [ ] **P0.3 Confirmation skip**: Confirm SubAgent cannot skip confirmation for
  high-risk tools. `confirmation_policy=inherit_tool_policy` does not override
  ToolRegistry confirmation requirements.
- [ ] **P0.4 Real LLM mode bypasses config gate**: Confirm `real_llm_readonly`
  and `real_llm_tool_requesting` modes cannot execute without config gate
  (`subagent.real_llm_readonly.enabled`, `subagent.tool_requesting.enabled`).
- [ ] **P0.5 Tool-capable mode executes shell outside sandbox**: Confirm
  `sandboxed_tool_capable` mode blocks shell execution outside sandbox root.
  `external_process_allowed=false` enforced.
- [ ] **P0.6 SubAgent writes repo without sandbox/worktree approval**: Confirm
  write tools (`write_file`, `apply_patch`) are blocked unless sandbox or
  worktree isolation is active and approved.

### Memory Governance

- [ ] **P0.7 Direct Memory write**: Confirm SubAgent has no direct reference to
  MemoryStore. All memory operations flow through `SubAgentMemoryBoundary` and
  existing Memory governance.
- [ ] **P0.8 Memory auto-approve**: Confirm memory proposals from SubAgent are
  never auto-approved. All proposals go through parent/governance adjudication.

### Context & Information Governance

- [ ] **P0.9 Hidden tool exposure**: Confirm hidden/internal tools are never
  exposed to SubAgent. `SubAgentToolBoundary` filters hidden tools from
  effective tool list.
- [ ] **P0.10 SubAgent trace logs secrets**: Confirm `SubAgentTraceEvent.data`
  never contains API keys, tokens, raw file contents, or full prompts.
- [ ] **P0.11 Context package contains full files**: Confirm
  `SubAgentContextPackage` contains `FileSummary` (summarized), not full file
  contents. Context budget enforced.

### Loop & Autonomy Governance

- [ ] **P0.12 Unbounded loop**: Confirm SubAgent cannot exceed `max_iterations`.
  Executor enforces hard bound; `max_iterations_exceeded` returned on bound hit.
- [ ] **P0.13 Provider direct call**: Confirm SubAgent cannot call the LLM
  provider directly. Only Parent Runtime may invoke the provider, and only when
  config gate is open.
- [ ] **P0.14 Nested delegation**: Confirm `SubAgentPolicy.max_nested_depth=0`
  blocks SubAgent-from-SubAgent delegation.
- [ ] **P0.15 Execution mode escalation**: Confirm SubAgent cannot escalate its
  own execution mode. Mode is set by parent at delegation time and is immutable.

### Adjudication & Merge Governance

- [ ] **P0.16 Parent adjudication skipped**: Confirm every `SubAgentResult`
  flows through parent adjudication. No result is auto-merged without parent
  decision.
- [ ] **P0.17 Result auto-merged without parent decision**: Confirm
  `ParentAdjudicationResult` is required for merge. No silent auto-accept.

### Checkpoint Governance

- [ ] **P0.18 Checkpoint secret storage**: Confirm `SubAgentCheckpointSummary`
  stores no full prompts, transcripts, secrets, raw tool outputs, or large
  artifacts.
- [ ] **P0.19 Resume replay of high-risk tools**: Confirm resume does not replay
  high-risk tool execution. Pending confirmation state preserved, not re-executed.

### Config & Environment

- [ ] **P0.20 Shell env fallback**: Confirm SubAgent config never falls back to
  shell environment variables. Project `.env` scoped values only.

---

## P1 — Boundary Integrity (Critical)

### Descriptor & Registry

- [ ] **P1.1 Descriptor validation fail-closed**: Confirm invalid `SUBAGENT.md`
  (bad name, missing required fields, invalid model, unsupported modes) →
  SubAgent not registered. No partial descriptors visible.
- [ ] **P1.2 Duplicate name detection**: Confirm duplicate SubAgent names across
  roots → `SubAgentLoadError`. No silent shadowing.
- [ ] **P1.3 Model restriction**: Confirm `model` field only accepts
  `fake`/`fixture`/`none` in v1. `anthropic`/`openai` gated behind config.
- [ ] **P1.4 Tool upper bound intersection**: Confirm effective tools =
  `descriptor.allowed_tools ∩ request.allowed_tools`. Neither source can expand
  beyond the other.
- [ ] **P1.5 Skill upper bound**: Confirm SubAgent can only use Skills in
  `allowed_skills`. Skill outside list → blocked.
- [ ] **P1.6 Memory scope enforcement**: Confirm `memory_scope=none` blocks all
  memory access; `read_context` blocks memory writes; `propose` queues proposals
  without auto-persist.
- [ ] **P1.7 Parent loop ownership**: Confirm Parent Agent retains loop
  ownership. SubAgent delegation is a bounded request/result/adjudication flow
  inside Runtime — no second loop.
- [ ] **P1.8 Registry session scoping**: Confirm `SubAgentRegistry` is
  instantiated per session, not a module-level global singleton.
- [ ] **P1.9 Frozen dataclasses**: Confirm all contract types (Descriptor,
  Request, ContextPackage, Result, Error, AuditRecord, Policy,
  AdjudicationResult, CheckpointSummary, ToolBoundary, SkillBoundary,
  MemoryBoundary, TraceEvent, ToolRequest, FileSummary, ToolSnapshot,
  SubAgentRun) are `@dataclass(frozen=True)`.

### Production Readiness

- [ ] **P1.10 No real delegation path despite claiming production readiness**:
  Confirm real LLM path is designed and testable (mocked), not absent. Config
  gates prevent execution but the code path exists.
- [ ] **P1.11 No isolated context packaging**: Confirm
  `SubAgentContextPackage` is assembled per delegation. Context is scoped,
  not full parent conversation.
- [ ] **P1.12 No parent adjudication**: Confirm `ParentAdjudicationResult` and
  adjudication flow exist. All accept/reject/revise/ask_user actions testable.
- [ ] **P1.13 No execution mode policy**: Confirm `SubAgentExecutionMode` enum
  and mode policy are defined. Mode gating is enforceable.
- [ ] **P1.14 No trace event model**: Confirm `SubAgentTraceEvent` covers full
  production lifecycle as a target. L0 must define/test the minimum subset
  (`delegation_started`, `context_packaged`, `result_returned`,
  `result_adjudicated`, `delegation_failed`); gated/future events are
  explicitly marked.
- [ ] **P1.15 No real LLM readonly dogfood when configured**: Confirm T2
  dogfood exists and passes when Capability L1 config gate is open.
- [ ] **P1.16 No context budget enforcement**: Confirm `max_context_chars` is
  enforced at packaging time. Budget overflow triggers trimming and warning.

### Safety & Redaction

- [ ] **P1.17 Secret redaction**: Confirm secret-like values in SUBAGENT.md
  frontmatter are redacted before descriptor registration.
- [ ] **P1.18 Error sanitization**: Confirm `SubAgentError.message` never
  contains secrets, API keys, or raw file contents.
- [ ] **P1.19 Audit record completeness**: Confirm every delegation produces a
  `SubAgentAuditRecord` with all 16 fields populated.
- [ ] **P1.20 Trace event sanitization**: Confirm trace events contain no
  secrets, full prompts, or raw file contents.

---

## P2 — Architecture Compliance (High)

### Module Boundaries

- [ ] **P2.1 Module boundary separation**: Confirm each module in
  `agent/subagent_system/` holds at most one governance boundary.
- [ ] **P2.2 CLI/TUI thinness**: Confirm `presentation.py` does not import
  executor, tool boundary, memory boundary, runtime, or adjudication.
- [ ] **P2.3 No legacy path imports**: Confirm formal SubAgent System does not
  import from `agent/subagents/local.py` (Safe Local MVP is test baseline only).
- [ ] **P2.4 No real LLM invocation without gate**: Confirm real provider calls
  only happen under explicit config gate. Mock provider used in tests.
- [ ] **P2.5 No external process spawn**: Confirm SubAgent cannot spawn
  subprocess, shell, or external process outside sandbox (and sandbox requires
  explicit approval).
- [ ] **P2.6 No network access without gate**: Confirm SubAgent execution does
  not initiate network connections unless mode policy explicitly allows it
  (only in gated real LLM modes).
- [ ] **P2.7 No `.env` access**: Confirm SubAgent code does not read `.env`
  files or `os.environ` for secrets.
- [ ] **P2.8 No real sessions/runs access**: Confirm SubAgent does not read or
  write real `sessions/` or `runs/` directories.
- [ ] **P2.9 No backend abstraction**: Confirm no DB, graph, embedding, or
  vector store introduced.
- [ ] **P2.10 Dependency direction**: Confirm dependencies flow inward:
  boundary modules → contract modules → executor → delegation adapter.
  No circular imports.
- [ ] **P2.11 Runtime owns state machine**: Confirm `SubAgentRun` state
  transitions are managed by `runtime.py`, not by SubAgent or executor.

### Usability & Coverage

- [ ] **P2.12 Only synthetic dogfood**: Confirm T1 dogfood covers required
  scenarios, but T2+ dogfood tiers exist (gated/future). Production readiness is not
  claimed on synthetic-only testing.
- [ ] **P2.13 Insufficient usability scenarios**: Confirm dogfood covers the
  usability contract: code review, test repair, RFC alignment, memory review,
  skill selection review, tool permission review, real LLM reasoning (gated).
- [ ] **P2.14 Incomplete handoff UX**: Confirm adjudication UX (accept/reject/
  revise/ask_user) is defined and testable.
- [ ] **P2.15 No low-confidence/revision handling**: Confirm low-confidence
  results trigger revision or warning. Revision loop is bounded.
- [ ] **P2.16 No sandbox contract**: Confirm sandbox contract is defined in
  design, even though execution is deferred. Sandbox tests exist (contract only).
- [ ] **P2.17 Dogfood tier naming conflict**: Confirm dogfood uses T1-T6 only
  and Capability uses L0-L5 only. No document uses L1-L5 to mean dogfood tiers.

---

## P3 — Test Coverage (Medium)

### Required for v1

- [ ] **P3.1 Descriptor tests**: All Phase 1 tests pass.
- [ ] **P3.2 Registry tests**: All Phase 2 tests pass.
- [ ] **P3.3 Contract tests**: All Phase 3 tests pass.
- [ ] **P3.4 Context packaging tests**: All Phase 4 tests pass.
- [ ] **P3.5 Execution mode tests**: All Phase 5 tests pass.
- [ ] **P3.6 Tool boundary tests**: All Phase 6 tests pass.
- [ ] **P3.7 Skill boundary tests**: All Phase 7 tests pass.
- [ ] **P3.8 Memory boundary tests**: All Phase 8 tests pass.
- [ ] **P3.9 Checkpoint tests**: All Phase 9 tests pass.
- [ ] **P3.10 Execution tests**: All Phase 10 tests pass.
- [ ] **P3.11 Adjudication tests**: All Phase 11 tests pass for the L0 minimum
  action subset (`accept_result`, `reject_result`, `ask_user`,
  `request_revision`). Full 8-action coverage is L1+ / later phase target.
- [ ] **P3.12 Adapter tests**: All Phase 12 tests pass.
- [ ] **P3.13 Trace tests**: All Phase 13 tests pass for the L0 minimum trace
  subset. Full production event coverage is gated/future where applicable.
- [ ] **P3.14 CLI/TUI tests**: All Phase 17 tests pass.
- [ ] **P3.15 Dogfood T1 tests**: All Phase 18 T1 tests pass.
- [ ] **P3.16 Architecture boundary tests**: All Phase 19 tests pass.

### Gated but Tested

- [ ] **P3.17 Real LLM readonly tests**: All Phase 14 tests pass (mocked
  provider; config gate tested).
- [ ] **P3.18 Real LLM tool-requesting tests**: All Phase 15 tests pass (mocked
  provider + tool registry; config gate tested).

### Future but Contracted

- [ ] **P3.19 Sandbox contract tests**: All Phase 16 tests pass (contract only;
  no real sandbox execution).
- [ ] **P3.20 Full pytest passes**: `HOME=/tmp/subagent-audit python -m pytest tests/ -x -q`
  green with temporary HOME.

---

## Audit Execution Rules

- Reviewer must be independent (not the implementer).
- Every P0 item must be verified with concrete test evidence.
- P1 items require code review + test evidence.
- P2 items require architecture review.
- P3 items require test run output.
- Any P0 failure → implementation must not proceed.
- Any P1 failure → fix before merge.
- P2/P3 failures → documented and tracked with remediation plan.

## Capability Level Audit Matrix

| Capability | P0 Items | P1 Items | P2 Items | P3 Items | Audit Gate |
|------------|----------|----------|----------|----------|------------|
| L0: Safe Local | P0.1-3,7-15,18-20 | P1.1-9,17-19 | P2.1-3,5-11,17 | P3.1-16,20 | v1 release + T1 |
| L1: Real LLM Read-Only | +P0.4,13 | +P1.10-16,20 | +P2.4,6,12-13 | +P3.17 | Gated dogfood T2 |
| L2: Real LLM Tool-Requesting | +P0.5 | (same) | +P2.14-15 | +P3.18 | Gated dogfood T3 |
| L3: Sandboxed Tool-Capable | +P0.6 | (same) | +P2.16 | +P3.19 | Future phase / T4 |
| L4: Worktree-Capable | (TBD) | (TBD) | (TBD) | (TBD) | Future phase / T5 |
| L5: Parallel Multi-SubAgent | (TBD) | (TBD) | (TBD) | (TBD) | Future placeholder / T6 |

## Exit Criteria

- All P0 items for target capability level confirmed pass.
- All P1 items confirmed pass.
- P2/P3 failures documented with remediation plan.
- Full pytest passes.
- Audit report signed by independent reviewer.
- Config gates verified: closed gates block execution; open gates allow gated
  execution with full audit trail.

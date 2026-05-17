# SubAgent System Audit Checklist

Status: Security and governance audit checklist for the formal SubAgent System.
Run before any SubAgent code enters the production path. All items must be
verified by an independent reviewer.

## P0 — Governance Bypass (Blockers)

- [ ] **P0.1 ToolRegistry bypass**: Confirm SubAgent cannot execute tools directly.
  All tool execution flows through `tool_executor` under Parent Runtime.
  `SubAgentToolBoundary.check()` is a pure check — no execution path.
- [ ] **P0.2 Tool risk downgrade**: Confirm SubAgent cannot lower a tool's risk
  level. ToolRegistry risk is authoritative regardless of SubAgent
  `allowed_tools`.
- [ ] **P0.3 Confirmation skip**: Confirm SubAgent cannot skip confirmation for
  high-risk tools. `confirmation_policy=inherit_tool_policy` does not override
  ToolRegistry confirmation requirements.
- [ ] **P0.4 Direct Memory write**: Confirm SubAgent has no direct reference to
  MemoryStore. All memory operations flow through `SubAgentMemoryBoundary` and
  existing Memory governance.
- [ ] **P0.5 Memory auto-approve**: Confirm memory proposals from SubAgent are
  never auto-approved. All proposals go through parent/governance adjudication.
- [ ] **P0.6 Hidden tool exposure**: Confirm hidden/internal tools are never
  exposed to SubAgent. `SubAgentToolBoundary` filters hidden tools from
  effective tool list.
- [ ] **P0.7 Skill System bypass**: Confirm SubAgent cannot bypass Skill System
  progressive disclosure. `SubAgentSkillBoundary` delegates loading to Skill
  System — no duplicate or bypass logic.
- [ ] **P0.8 Unbounded loop**: Confirm SubAgent cannot exceed `max_iterations`.
  Executor enforces hard bound; `max_iterations_exceeded` returned on bound hit.
- [ ] **P0.9 Provider direct call**: Confirm SubAgent cannot call the LLM
  provider directly. Only Parent Runtime may invoke the provider.
- [ ] **P0.10 Nested delegation**: Confirm `SubAgentPolicy.max_nested_depth=0`
  blocks SubAgent-from-SubAgent delegation.
- [ ] **P0.11 Checkpoint secret storage**: Confirm `SubAgentCheckpointSummary`
  stores no full prompts, transcripts, secrets, raw tool outputs, or large
  artifacts.
- [ ] **P0.12 Resume replay of high-risk tools**: Confirm resume does not replay
  high-risk tool execution. Pending confirmation state preserved, not re-executed.
- [ ] **P0.13 Shell env fallback**: Confirm SubAgent config never falls back to
  shell environment variables. Project `.env` scoped values only.

## P1 — Boundary Integrity (Critical)

- [ ] **P1.1 Descriptor validation fail-closed**: Confirm invalid `SUBAGENT.md`
  (bad name, missing required fields, invalid model) → SubAgent not registered.
  No partial descriptors visible.
- [ ] **P1.2 Duplicate name detection**: Confirm duplicate SubAgent names across
  roots → `SubAgentLoadError`. No silent shadowing.
- [ ] **P1.3 Model restriction**: Confirm `model` field only accepts
  `fake`/`fixture`/`none` in v1. `model=real` rejected.
- [ ] **P1.4 Tool upper bound intersection**: Confirm effective tools =
  `descriptor.allowed_tools ∩ request.allowed_tools`. Neither source can expand
  beyond the other.
- [ ] **P1.5 Skill upper bound**: Confirm SubAgent can only use Skills in
  `allowed_skills`. Skill outside list → blocked.
- [ ] **P1.6 Memory scope enforcement**: Confirm `memory_scope=none` blocks all
  memory access; `read_context` blocks memory writes; `propose` queues proposals
  without auto-persist.
- [ ] **P1.7 Parent loop ownership**: Confirm Parent Agent retains loop
  ownership. SubAgent delegation is a bounded request/result flow inside
  Runtime — no second loop.
- [ ] **P1.8 Registry session scoping**: Confirm `SubAgentRegistry` is
  instantiated per session, not a module-level global singleton.
- [ ] **P1.9 Frozen dataclasses**: Confirm all contract types (Descriptor,
  Request, Context, Result, Error, AuditRecord, Policy, CheckpointSummary,
  ToolBoundary, SkillBoundary, MemoryBoundary) are `@dataclass(frozen=True)`.
- [ ] **P1.10 Secret redaction**: Confirm secret-like values in SUBAGENT.md
  frontmatter are redacted before descriptor registration.
- [ ] **P1.11 Error sanitization**: Confirm `SubAgentError.message` never
  contains secrets, API keys, or raw file contents.
- [ ] **P1.12 Audit record completeness**: Confirm every delegation produces a
  `SubAgentAuditRecord` with all required fields populated.

## P2 — Architecture Compliance (High)

- [ ] **P2.1 Module boundary separation**: Confirm each module in
  `agent/subagent_system/` holds at most one governance boundary.
- [ ] **P2.2 CLI/TUI thinness**: Confirm `presentation.py` does not import
  executor, tool boundary, memory boundary, or skill boundary.
- [ ] **P2.3 No legacy path imports**: Confirm formal SubAgent System does not
  import from `agent/subagents/local.py` (Safe Local MVP is test baseline only).
- [ ] **P2.4 No real LLM invocation**: Confirm fake/local execution only. No
  real Anthropic/OpenAI/other provider calls in SubAgent path.
- [ ] **P2.5 No external process spawn**: Confirm SubAgent cannot spawn
  subprocess, shell, or external process.
- [ ] **P2.6 No network access**: Confirm SubAgent execution does not initiate
  network connections.
- [ ] **P2.7 No `.env` access**: Confirm SubAgent code does not read `.env`
  files or `os.environ` for secrets.
- [ ] **P2.8 No real sessions/runs access**: Confirm SubAgent does not read or
  write real `sessions/` or `runs/` directories.
- [ ] **P2.9 No backend abstraction**: Confirm no DB, graph, embedding, or
  vector store introduced.
- [ ] **P2.10 Dependency direction**: Confirm dependencies flow inward:
  boundary modules → contract modules → executor → delegation adapter.
  No circular imports.

## P3 — Test Coverage (Medium)

- [ ] **P3.1 Descriptor tests**: All Phase 1 tests pass (valid/invalid parse,
  missing name, invalid model, secret redaction).
- [ ] **P3.2 Registry tests**: All Phase 2 tests pass (deterministic scan,
  duplicate detection, disabled/hidden filtering, session isolation).
- [ ] **P3.3 Contract tests**: All Phase 3 tests pass (request/result/error/
  audit validation, frozen enforcement).
- [ ] **P3.4 Tool boundary tests**: All Phase 4 tests pass (upper bound,
  unknown tool, hidden tool, risk preservation, confirmation preservation).
- [ ] **P3.5 Skill boundary tests**: All Phase 5 tests pass (L1 metadata,
  progressive disclosure delegation, outside-list blocking).
- [ ] **P3.6 Memory boundary tests**: All Phase 6 tests pass (scope enforcement,
  proposal validation, no direct write).
- [ ] **P3.7 Checkpoint tests**: All Phase 7 tests pass (correlation metadata
  only, no secrets, resume safety).
- [ ] **P3.8 Execution tests**: All Phase 8 tests pass (max_iterations hard
  stop, status accuracy, iteration counter).
- [ ] **P3.9 Adapter tests**: All Phase 9 tests pass (parent loop ownership,
  request/result flow, error paths).
- [ ] **P3.10 CLI/TUI tests**: All Phase 10 tests pass (display only, no
  runtime logic imports).
- [ ] **P3.11 Dogfood tests**: All Phase 11 tests pass (15 scenarios, no
  private data in audit packets).
- [ ] **P3.12 Architecture boundary tests**: All Phase 12 tests pass (no
  ToolRegistry bypass, no Memory direct write, no second loop).
- [ ] **P3.13 Full pytest passes**: `HOME=/tmp/subagent-audit python -m pytest tests/ -x -q`
  green with temporary HOME.

## Audit Execution Rules

- Reviewer must be independent (not the implementer).
- Every P0 item must be verified with concrete test evidence.
- P1 items require code review + test evidence.
- P2 items require architecture review.
- P3 items require test run output.
- Any P0 failure → implementation must not proceed.
- Any P1 failure → fix before merge.
- P2/P3 failures → documented and tracked.

## Exit Criteria

- All P0 items confirmed pass.
- All P1 items confirmed pass.
- P2/P3 failures documented with remediation plan.
- Full pytest passes.
- Audit report signed by independent reviewer.

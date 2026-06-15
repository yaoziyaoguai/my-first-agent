# SubAgent Canonical RFC

Status: Canonical design for the production-grade parent-controlled SubAgent
System. This is the target architecture — implementation proceeds through
explicit phases with safety gates, but the design itself is complete and
production-targeted.

This RFC defines SubAgent as a parent-controlled bounded delegation unit with
isolated context, scoped tool access, and structured result adjudication. It is
written for a Coding Agent implementation loop: tests and code should trace back
to the contracts below. The formal implementation namespace will be
`agent/subagent_system/`; the existing `agent/subagents/local.py` is the Safe
Local MVP and remains a test baseline.

Naming convention:

- **Capability Level = L0-L5**.
- **Dogfood Tier = T1-T6**.
- **Implementation Phase = Phase 0-N**.
- **Audit Priority = P0-P3**.

## 1. Goal

A **SubAgent** is a parent-controlled bounded delegation unit. The Parent Agent
authorizes a SubAgent to execute a specific task within explicit boundaries —
isolated context window, restricted tools, restricted skills, bounded
iterations, and governed Memory/Checkpoint access. The SubAgent returns a
structured result to the Parent Agent; the Parent adjudicates and merges. The
SubAgent never owns the main loop or bypasses governance.

Core properties:

- Parent Agent owns orchestration and delegates only bounded work.
- SubAgent receives a packaged context with explicit constraints.
- SubAgent runs in an isolated context window (at minimum: scoped task context;
  eventually: real isolated LLM context).
- SubAgent returns a structured delegation result for parent adjudication.
- Parent can accept, reject, request revision, or merge the result.
- Tools, Memory, Checkpoint, Confirmation all remain governed by the Parent
  Runtime and existing authorities (ToolRegistry, Memory governance,
  Checkpoint schema owner).

## 2. Production-Grade Capability Model

The SubAgent System is designed as a production-grade architecture from day one.
Implementation is phased with safety gates, but the target is not a "safe local
wrapper" — it is a complete parent-controlled delegation runtime.

### 2.1 Capability Levels

> Production-grade target architecture from day one; implementation starts at
> the L0 safe-local baseline. L1-L5 are designed as gated/future capabilities,
> not default runtime behavior.

| Level | Name | LLM | Tools | Description |
|-------|------|-----|-------|-------------|
| L0 | Safe Local SubAgent | fake/deterministic | read_file only | Baseline; test-only or non-critical review |
| L1 | Real LLM Read-Only SubAgent | real, config-gated | read_file, grep, glob | Code review, RFC alignment, analysis |
| L2 | Real LLM Tool-Requesting SubAgent | real, config-gated | parent-mediated execution | Test repair planning, dependency audit |
| L3 | Sandboxed Tool-Capable SubAgent | real, config-gated | sandbox-scoped tools | Code gen in tmp, local file ops, lint |
| L4 | Worktree-Capable SubAgent | real, explicit approval | repo-scoped tools | Branch work, multi-file edits (future) |
| L5 | Parallel Multi-SubAgent Orchestration | real, explicit approval | per-agent tool sets | Multi-perspective review, concurrent analysis (future) |

These levels are the target architecture. Implementation:

- **L0**: required for v1, implemented first as safety baseline.
- **L1**: designed now, implemented as gated dogfood tier T2. Requires explicit
  config (`subagent.real_llm_readonly.enabled=true`), dogfood pass, and audit.
- **L2**: designed now, implemented after T2 dogfood. Requires
  `subagent.tool_requesting.enabled=true` and parent-mediated execution path.
- **L3**: designed now, sandbox contract and tests written early; real sandbox
  execution requires `subagent.sandbox.enabled=true` and sandbox infrastructure.
- **L4**: deferred to explicit future phase after L3 production use.
- **L5**: deferred to explicit future phase; designed for reference only.

Production-grade means the contracts are complete enough for higher levels to
fit without redesign. It does not mean every level is enabled by default. L0 is
the implementation entry point, L1/L2 are gated capabilities, and L3/L4/L5 are
contract/future capabilities unless explicitly approved.

### 2.2 Execution Modes

`SubAgentExecutionMode` defines how a SubAgent runs:

| Mode | Value | Description |
|------|-------|-------------|
| `local_fake` | Fake deterministic response | Test/characterization only |
| `local_deterministic` | Rule-based local execution | Deterministic dogfood |
| `real_llm_readonly` | Real LLM, read-only tool snapshot | L1 capability |
| `real_llm_tool_requesting` | Real LLM, parent-mediated tools | L2 capability |
| `sandboxed_tool_capable` | Real LLM, sandbox-scoped direct tools | L3 capability |

Every mode enforces `max_iterations` and governance boundaries. Mode escalation
requires explicit config + audit + dogfood.

### 2.3 Delegation Runtime Model

```
Parent Runtime
  │
  ├─ Decide to delegate
  ├─ Create SubAgentRequest
  ├─ Package SubAgentContext (context packaging)
  ├─ Select ExecutionMode (mode policy)
  ├─ Launch SubAgentRun
  │    ├─ Isolated context window
  │    ├─ Bounded local loop (max_iterations)
  │    ├─ Tool requests → parent mediation
  │    ├─ Checkpoint-safe state
  │    └─ Return SubAgentResult
  ├─ Adjudicate result (accept/reject/revise/merge)
  ├─ Apply adjudicated result
  └─ Continue parent loop
```

### 2.4 SubAgent Context Window

A SubAgent receives an **isolated context window**, not the full parent
conversation. The `SubAgentContextPackage` contains:

- Task description and role prompt
- Goal and explicit constraints
- Relevant file summaries (not full repo — progressive disclosure)
- Selected memory context (if `memory_scope >= read_context`)
- Selected skill L1 metadata for allowed skills
- Allowed tool snapshot (name, description, risk, confirmation requirement)
- Forbidden actions list
- Output schema expectation
- `max_context_chars` budget
- `max_iterations`
- Stop conditions

### 2.5 SubAgentStopReason

| Reason | Description |
|--------|-------------|
| `task_completed` | SubAgent finished work, result returned |
| `task_completed_low_confidence` | Finished but confidence < threshold |
| `max_iterations_exceeded` | Hard iteration bound hit |
| `max_context_exceeded` | Context budget exhausted |
| `needs_clarification` | SubAgent asks parent for more info |
| `needs_confirmation` | High-risk tool needs parent approval |
| `tool_blocked` | Requested tool denied by boundary |
| `policy_blocked` | Action blocked by SubAgentPolicy |
| `error` | Execution error |
| `interrupted` | External interruption (checkpoint) |

### 2.6 Parent Adjudication Model

When Parent Agent receives a `SubAgentResult`, it must adjudicate:

| Action | Description |
|--------|-------------|
| `accept_result` | Accept summary and artifacts |
| `reject_result` | Discard result, may log reason |
| `request_revision` | Return to SubAgent with revised task |
| `ask_user` | Escalate to human for decision |
| `merge_summary` | Integrate summary into parent context |
| `convert_to_tool_request` | Convert SubAgent tool request to parent tool call |
| `convert_to_memory_proposal` | Route SubAgent memory proposal through governance |
| `continue_parent_loop` | Parent resumes main loop with new information |

Level scope:

- **L0 minimum**: `accept_result`, `reject_result`, `ask_user`,
  `request_revision`.
- **L1+ / later phases**: `merge_summary`, `convert_to_tool_request`,
  `convert_to_memory_proposal`, `continue_parent_loop`.

The complete 8-action model is the production target, not the L0 implementation
burden.

Revision loop: Parent may request revision up to `max_revisions` times (default 1).
Each revision counts as a new delegation (new delegation_id, new iterations).

## 3. Industry References and Design Adaptation

This section is prior-art analysis only. Claude Code is not a runtime
dependency of `my-first-agent`, and SubAgent implementation must stay inside the
parent-controlled runtime/provider/tool boundaries defined above.

### 3.1 Claude Code Subagents

**What we studied**:

- **Context isolation**: each subagent receives a fresh, scoped context window;
  does not inherit full parent conversation history. Parent passes only the
  specific task description and relevant data snippets.
- **Tool scoping**: subagent receives a restricted tool allowlist via `Task`
  tool parameters. Parent defines `allowedTools` and `disallowedTools`.
  Sensitive tools excluded unless task explicitly requires them.
- **Custom system prompt**: dynamically generated from `Task` tool parameters,
  including task-specific instructions, tool permissions, `maxTurns` limit.
- **Permissions**: delegation model — subagent can only use tools parent
  already has access to, further restricted by explicit allowlist.
- **`maxTurns`**: hard limit on tool-calling turns. Once exhausted, subagent
  must return current findings to parent. Parent decides whether to spawn new
  subagent or handle remaining work.
- **`isolation: worktree`**: optional filesystem isolation via git worktree.
- **Subagent-scoped memory**: some platforms support subagent-level scoped
  memory or private working memory.
- **Background/async subagents**: some platforms can run delegation in the
  background and later reconcile results.
- **Effort/model selection**: parent may choose different models or reasoning
  effort per subagent.
- **Hooks/MCP scoping**: some systems scope hooks or MCP servers per subagent.
- **No nested subagents**: subagents cannot spawn other subagents.
- **Result flow**: structured result returned — summary of actions, findings,
  files modified/created, completion status.
- **Built-in agents**: Explore (Haiku, read-only), Plan, General-purpose.

**What we adopt**:

- Isolated context window: SubAgent receives packaged context, not full parent
  history.
- Scoped tool access: per-subagent tool allowlist as upper bound.
- Custom system prompt: dynamically assembled from `SubAgentContextPackage`.
- `max_iterations` as hard bound (analogue to `maxTurns`).
- Parent adjudicates results (accept/reject/revise/merge).
- No nested SubAgent spawning in v1.
- Worktree isolation as L4 (future phase, explicit approval).
- Ephemeral context memory and memory proposals, while persistent memory remains
  under Memory governance.

**What we reject**:

- Inheriting all parent tools by default (First Agent starts with explicit
  allowlist; empty default is safer).
- Agent Teams / peer-to-peer communication (out of scope for bounded
  delegation model).
- Built-in subagent types hardcoded in system prompt (First Agent uses
  filesystem-registered descriptors).
- Private persistent SubAgent memory that bypasses First Agent Memory
  governance.

**Conscious omissions for First Agent**:

- Background subagents are future L5 / async orchestration work.
- Effort/model selection is future execution-mode policy.
- Hooks are represented by First Agent confirmation, policy, and trace gates.
- MCP scoping is a future ToolRegistry boundary extension.

### 3.2 OpenAI Agents SDK — Handoffs and Agents-as-Tools

**What we studied**:

- **Handoffs**: parent transfers conversation to a specialist agent; receiving
  agent sees full (optionally filtered) history. Uni-directional transfer.
- **Agents-as-tools**: orchestrator retains control; sub-agent wrapped as
  callable tool, runs bounded internal loop, returns structured result. Parent
  uses standard Python control flow for orchestration.
- **Manager-style orchestration**: central coordinator dispatches to specialist
  sub-agents and aggregates results. Parent remains controller.
- **Guardrails**: input/output validation that runs in parallel with agent
  execution. "Fail fast when checks do not pass."
- **Sandbox agents**: isolated workspace execution with manifest-defined files,
  resumable sessions. Suited for coding, document review, tasks needing
  walled-off execution.
- **Human-in-the-loop**: guardrails can trigger human approval for high-risk
  actions.

**What we adopt**:

- Parent-controlled delegation model (agents-as-tools / manager style, not full
  handoff).
- Bounded execution through `max_iterations`.
- SubAgent returns structured result; parent retains final control.
- Per-subagent tool allowlist as upper bound.
- Manager-style orchestration for multi-SubAgent (L5, future).
- Sandbox execution model for tool-capable SubAgents (L3).

**What we reject**:

- Full conversation handoff (transfers too much control; parent loses
  visibility during delegation).
- Guardrails scoped only to entry/exit agent (First Agent requires every
  delegation to carry its own governance).
- Python-first orchestration as the only model (First Agent's Runtime owns the
  loop, not ad-hoc Python control flow).

### 3.3 OpenAI / Anthropic Guardrails and Human Approval

**What we studied**:

- Guardrails run in parallel with agent execution, not blocking the loop.
- High-risk actions pause for human approval.
- Approval/reject/resume semantics.
- Guardrails are composable and can be stacked.

**What we adopt**:

- ToolRegistry risk levels as the single source of truth for tool risk.
- Confirmation boundary: high-risk tools always require confirmation regardless
  of SubAgent policy.
- Parent Adjudication as the human-approval integration point: `ask_user` action
  routes decisions through parent.
- Input/output guardrails as future phase (designed now, implemented later).
- OpenAI-style guardrails can run as tripwires around agent execution; First
  Agent currently uses synchronous parent policy checks for predictability.
- Future phases may add parallel pre/post guard checks, but they cannot bypass
  Parent orchestration, ToolRegistry authority, or Confirmation.

**What we reject**:

- Guardrails that run only on first/last agent (every delegation boundary must
  enforce its own governance).
- Bypassing ToolRegistry confirmation for any tool request, regardless of
  source (SubAgent or Parent).

### 3.4 Anthropic Agent Skills — the Reverse Boundary

**What we studied**:

- Skills are **in-process augmentation**: loaded into parent context as prompt
  content, share parent tools, no process isolation.
- Progressive disclosure: name/description in context; full body only when
  invoked.
- `context: fork` bridges Skills and SubAgents: Skill content + SubAgent
  execution environment.

**What this clarifies for SubAgent**:

- Skill ≠ SubAgent. Skill is a capability package; SubAgent is an execution
  context.
- SubAgent may be allowed to use certain Skills (via `allowed_skills`), but
  Skill governance remains with the Skill System.
- If a SubAgent uses a Skill, progressive disclosure still applies — the
  SubAgent does not bypass L1/L2/L3 loading.

## 4. Non-Goals (Precise)

These are NOT implementation gaps — they are explicit design boundaries:

- **SubAgent is not Skill**: Skill is a capability package; SubAgent is an
  execution context with its own context window and loop.
- **SubAgent is not Tool**: Tool is an executable action endpoint; SubAgent is
  a bounded delegate with structured result.
- **SubAgent does not replace Parent Agent**: Parent Agent owns orchestration,
  adjudication, and final decision authority.
- **SubAgent does not own an unbounded autonomous loop**: `max_iterations` is
  always enforced.
- **SubAgent does not bypass ToolRegistry**: ToolRegistry remains authority for
  capability, risk, confirmation.
- **SubAgent does not directly write Memory**: all memory proposals flow through
  Memory governance; parent adjudicates.
- **SubAgent does not directly modify checkpoint schema**: checkpoint ownership
  remains with Runtime.
- **SubAgent does not have independent long-term memory by default**.
- **SubAgent does not use DB, graph, embedding, or vector store**.
- **SubAgent does not spawn nested SubAgents in v1**.
- **SubAgent does not default to real LLM invocation**: real LLM is config-gated
  and requires explicit `SubAgentExecutionMode`.
- **SubAgent does not default to external process or shell**: sandbox is a
  separate gated phase.
- **SubAgent does not default to repo write or worktree isolation**: these are
  explicit future phases.
- **SubAgent does not default to network access**: network is blocked unless
  explicit sandbox policy allows it.

Design vs. implementation distinction:

- Real delegation is **designed but gated**: the architecture fully specifies
  real LLM execution, but implementation requires config + audit + dogfood.
- External process/shell is **designed but gated**: sandbox contract exists,
  execution requires sandbox phase approval.
- Nested SubAgent is **designed but deferred**: architecture supports it in
  principle, but v1 enforces `max_nested_depth=0`.
- Worktree isolation is **designed but deferred**: defined as L4 capability,
  requires explicit future phase.
- Default mode remains safe local; higher modes require explicit escalation.

## 5. Delegation Contract

### 5.1 SubAgentRequest

The Parent Agent creates a `SubAgentRequest` to delegate work:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task` | str | yes | Task description for the SubAgent |
| `role` | str | yes | Target SubAgent role (maps to descriptor) |
| `allowed_tools` | tuple[str, ...] | yes | Upper bound of tools SubAgent may request |
| `allowed_skills` | tuple[str, ...] | no | Skills SubAgent may use (default: none) |
| `memory_scope` | str | yes | One of `none`, `read_context`, `propose` |
| `max_iterations` | int | yes | Hard bound on local iteration (≥1) |
| `execution_mode` | str | yes | `local_fake` / `local_deterministic` / `real_llm_readonly` / `real_llm_tool_requesting` / `sandboxed_tool_capable` |
| `risk_level` | str | yes | `low` / `medium` / `high` |
| `confirmation_policy` | str | yes | `inherit_tool_policy` / `require_parent` |
| `parent_trace_id` | str | yes | Correlation ID for audit trail |
| `delegation_reason` | str | yes | Why Parent Agent is delegating |
| `context` | dict[str, Any] | no | Additional structured context |
| `output_schema` | dict | no | Expected output structure hint |
| `max_revisions` | int | no | Max revision rounds (default 1) |
| `relevant_files` | tuple[str, ...] | no | File paths relevant to task |

### 5.2 SubAgentContextPackage

Assembled by the context packaging module before SubAgent execution:

| Field | Description |
|-------|-------------|
| `request` | The `SubAgentRequest` |
| `descriptor` | The matched `SubAgentDescriptor` |
| `task` | Task description (from request) |
| `role_prompt` | Role-specific system prompt |
| `goal` | Explicit goal statement |
| `constraints` | Hard constraints for this delegation |
| `relevant_files` | File paths relevant to task |
| `relevant_summaries` | Summarized file/directory content (not full files) |
| `selected_memory_context` | Read-only memory snapshot (if `memory_scope >= read_context`) |
| `selected_skill_metadata` | L1 metadata for allowed Skills (progressive disclosure) |
| `allowed_tools` | Effective tool snapshot (name, description, risk, confirmation) |
| `allowed_skills` | Allowed skill names |
| `forbidden_actions` | Explicitly blocked actions |
| `output_schema` | Expected output structure hint |
| `max_context_chars` | Context window budget |
| `max_iterations` | Hard iteration bound |
| `stop_conditions` | When SubAgent must stop |
| `execution_mode` | Selected `SubAgentExecutionMode` |

### 5.3 SubAgentResult

Returned by the SubAgent to the Parent Agent:

| Field | Type | Description |
|-------|------|-------------|
| `status` | str | `ok` / `error` / `needs_confirmation` / `max_iterations_exceeded` / `max_context_exceeded` / `needs_clarification` / `interrupted` |
| `summary` | str | Human-readable summary of work done |
| `artifacts` | tuple[str, ...] | References to produced artifacts (paths, not content) |
| `tool_requests` | tuple[ToolRequest, ...] | Tools the SubAgent wants executed (with args) |
| `memory_proposals` | tuple[MemoryProposal, ...] | Memory proposals (not writes) |
| `confidence` | float | 0.0–1.0 self-assessment |
| `warnings` | tuple[str, ...] | Non-blocking issues found |
| `audit` | SubAgentAuditRecord | Structured audit trail |
| `handoff_back` | str | Explicit handoff note to Parent Agent |
| `clarification_question` | str \| None | Question for parent, if `needs_clarification` |
| `trace_events` | tuple[SubAgentTraceEvent, ...] | Trace log from execution |
| `stop_reason` | str | `SubAgentStopReason` value |

### 5.4 SubAgentError

Structured error from a failed delegation:

| Field | Type | Description |
|-------|------|-------------|
| `code` | str | Machine-readable error code |
| `message` | str | Human-readable error (sanitized, no secrets) |
| `source` | str | `descriptor` / `policy` / `execution` / `context` / `parent` |
| `recoverable` | bool | Whether Parent Agent can retry |
| `delegation_id` | str | Correlation ID |

### 5.5 SubAgentAuditRecord

| Field | Description |
|-------|-------------|
| `subagent_name` | Matched SubAgent descriptor name |
| `delegation_id` | Unique delegation ID |
| `parent_trace_id` | Correlation to parent |
| `execution_mode` | Mode used for this delegation |
| `status` | Final status |
| `stop_reason` | Why execution stopped |
| `iterations_used` | Actual iterations consumed |
| `max_iterations` | Hard bound |
| `tools_requested` | Tools SubAgent asked for |
| `tools_denied` | Tools blocked by policy |
| `tools_executed` | Tools parent executed on SubAgent's behalf |
| `memory_proposals_count` | Number of memory proposals emitted |
| `warnings` | Non-blocking issues |
| `elapsed_ms` | Wall-clock time |
| `revision_count` | Number of revision rounds |

### 5.6 ParentAdjudicationResult

Parent's decision on a SubAgent result:

| Field | Type | Description |
|-------|------|-------------|
| `action` | str | One of the parent adjudication actions from §2.6 |
| `reason` | str | Why this adjudication |
| `merged_summary` | str \| None | Integrated summary (if accepted) |
| `tool_calls_to_execute` | tuple[str, ...] | Tools parent will execute on SubAgent's behalf |
| `memory_proposals_to_route` | tuple[MemoryProposal, ...] | Proposals to route through governance |
| `revised_request` | SubAgentRequest \| None | New request for revision |
| `user_question` | str \| None | Question for human (if `ask_user`) |

## 6. Governance

### 6.1 Parent Control

- Parent Agent decides when and why to delegate.
- Parent Agent sets `allowed_tools` upper bound — SubAgent cannot expand it.
- Parent Agent sets `max_iterations` — SubAgent cannot exceed it.
- Parent Agent selects `execution_mode` — SubAgent cannot escalate mode.
- Parent Agent adjudicates result — accept, reject, revise, or ask user.
- Parent Agent merges accepted results into its own context.

### 6.2 ToolRegistry Authority

- `allowed_tools` on SubAgentRequest is an upper bound, not authorization.
- ToolRegistry remains the authority for tool capability, risk level, and
  confirmation policy.
- SubAgent cannot lower a tool's risk level.
- SubAgent cannot skip confirmation for high-risk tools.
- Hidden/internal tools are never exposed to SubAgents.
- Tool execution is parent-mediated: SubAgent requests, Parent executes.
- In sandbox mode (L3+), SubAgent may execute scoped tools directly within
  sandbox boundaries; ToolRegistry still governs risk and confirmation.

### 6.3 Memory Governance

- Default memory access is `none`.
- `read_context` provides read-only memory snapshot — no write path.
- `propose` allows SubAgent to emit `MemoryProposal` objects.
- All proposals go through existing Memory governance — no auto-approve.
- Parent adjudication may route proposals via `convert_to_memory_proposal`.
- SubAgent has no direct reference to MemoryStore.

### 6.4 Confirmation Boundary

- SubAgent's `confirmation_policy` is either `inherit_tool_policy` (default)
  or `require_parent` (Parent must confirm every tool execution).
- SubAgent cannot set `confirmation_policy` to a weaker level than the tool
  requires.
- Human confirmation still gates high-risk actions regardless of SubAgent
  policy.
- Parent `ask_user` adjudication action is the human-approval integration point.

### 6.5 Reviewability

- Every `SubAgentResult` includes a structured audit record and trace events.
- Parent Agent can inspect `tools_requested`, `tools_denied`,
  `memory_proposals_count`, `warnings`, `confidence`, and `trace_events`.
- CLI/TUI can display delegation audit trail and trace.
- Revision history preserved in audit trail.

## 7. Loop Model

- Parent Agent owns the main Agent loop.
- SubAgent runs in a bounded local loop within its context window.
- `max_iterations` is required and must be ≥1.
- When `max_iterations` is exceeded, SubAgent returns
  `status=max_iterations_exceeded` with a best-effort summary.
- Parent may decide to re-delegate (new delegation_id) or handle remaining work.
- No unbounded autonomous recursion.
- No SubAgent spawning SubAgent in v1 (`max_nested_depth=0`).
- No multi-agent swarm / peer-to-peer in v1 (designed as L5, future).
- SubAgent cannot call the provider directly — provider access is gated by
  `execution_mode` and mediated by Runtime.

### Revision Loop

- Parent may request revision up to `max_revisions` times.
- Each revision is a new delegation run (new `delegation_id`, reset iterations).
- SubAgent receives revised `SubAgentRequest` with updated task/constraints.
- Revision history is preserved in audit trail.
- After `max_revisions` exhausted, parent must accept or reject final result.

### Partial Failure Handling

- If SubAgent encounters partial failure (some tool requests denied, some
  succeeded), it returns `status=ok` with `warnings` describing denied actions.
- If SubAgent cannot complete due to tool denial, it returns
  `status=tool_blocked` with details in audit record.
- If SubAgent encounters an execution error, it returns `status=error` with
  `SubAgentError`.

## 8. Memory Model

| Scope | Read Access | Write Access | Notes |
|-------|------------|--------------|-------|
| `none` | No memory context | None | Default |
| `read_context` | Read-only snapshot | None | Provided via adapter at delegation time |
| `propose` | Read-only snapshot | MemoryProposal only | Proposals adjudicated by Parent/Memory governance |

- No direct MemoryStore write from SubAgent.
- No silent procedural retain.
- No auto-approve of memory proposals.
- Memory proposals from SubAgent carry `source=subagent` metadata for
  auditability.

## 9. Checkpoint Model

- SubAgent in-flight state must be checkpoint-safe.
- Checkpoint stores `SubAgentCheckpointSummary`: `delegation_id`,
  `subagent_name`, `status`, `iterations_used`, `max_iterations`,
  `parent_trace_id`, `execution_mode`, `pending_confirmation`, `stop_reason`.
- Checkpoint does NOT store: full SubAgent prompt, full transcript, raw tool
  outputs, raw artifacts, secrets, large resource content, full context package.
- On resume, Parent Agent reads checkpoint summary and decides: re-delegate,
  request revision, explain, or abort.
- High-risk tool execution is never replayed on resume.
- Pending confirmation state is preserved — parent must re-adjudicate.
- Checkpoint schema changes require explicit design approval.

## 10. Observability / Trace Model

Every SubAgent delegation produces trace events for audit and debugging:

| Event | Description |
|-------|-------------|
| `delegation_started` | Parent initiated delegation |
| `context_packaged` | Context package assembled |
| `execution_mode_selected` | Mode chosen with rationale |
| `iteration_started` | Each bounded iteration |
| `tool_requested` | SubAgent requested a tool |
| `tool_denied` | Tool request blocked by boundary |
| `tool_executed` | Parent executed tool on SubAgent's behalf |
| `confirmation_required` | High-risk tool paused for confirmation |
| `confirmation_resolved` | Confirmation approved/rejected |
| `result_returned` | SubAgent returned result |
| `result_adjudicated` | Parent adjudicated result |
| `revision_requested` | Parent requested revision |
| `delegation_failed` | Delegation errored |
| `resumed_from_checkpoint` | Delegation resumed after interruption |
| `delegation_completed` | Full delegation lifecycle complete |
| `sandbox_entered` | L3 sandbox execution boundary entered |
| `worktree_created` | L4 worktree isolation boundary created |
| `mode_escalation_requested` | Parent considered a gated mode escalation |

Level scope:

- **L0 minimum trace events**: `delegation_started`, `context_packaged`,
  `result_returned`, `result_adjudicated`, `delegation_failed`.
- **Gated / later trace events**: `iteration_started`, `tool_requested`,
  `confirmation_required`, `resumed_from_checkpoint`, `sandbox_entered`,
  `worktree_created`, `mode_escalation_requested`.

The full trace model is the production target. L0 only needs the minimum event
subset required to debug safe-local delegation and parent adjudication.

Trace events are included in `SubAgentResult.trace_events` and `SubAgentAuditRecord`.

## 11. Usability Contract

What can a user do with the SubAgent System when v1 implementation is complete?

### v1 Required (Capability L0 required + Capability L1 gated dogfood T2)

L0 execution mode is `local_fake` / `local_deterministic` only: no real LLM, no
external process, no shell, and no repo write. Higher levels remain
designed/gated/future capabilities.

- Delegate a code review planning task to a reviewer SubAgent — **L0,
  `local_fake` / `local_deterministic` only**.
- Delegate test repair analysis to a tester SubAgent — **L0,
  `local_fake` / `local_deterministic` only**.
- Delegate RFC alignment audit to an auditor SubAgent — **L0,
  `local_fake` / `local_deterministic` only**.
- Delegate memory boundary review (read-only context) — **L0, no persistent
  memory write**.
- Delegate skill selection review (Skill L1 metadata only) — **L0, metadata
  snapshot only**.
- Delegate tool permission review (boundary check) — **L0, pure check, no tool
  execution**.
- Under config gate: real LLM read-only code review reasoning — **Capability
  L1 gated, not default**.
- Under config gate: real LLM RFC alignment reasoning — **Capability L1 gated,
  not default**.
- All delegations produce audit records and L0 minimum trace events.
- Interrupted delegations are checkpoint-safe and resumable without replaying
  high-risk effects.
- Parent can accept, reject, ask user, or request revision of any result.

### Gated (Capability L2, requires config + dogfood T3 + audit)

- Real LLM tool-requesting: SubAgent proposes tool calls, parent executes
- Test repair planning with parent-mediated tool execution
- Multi-file analysis with parent-mediated file reads

### Future (Capability L3-L5, requires explicit phases and T4-T6 placeholders)

- Sandboxed local code generation and file operations
- Worktree-isolated branch work
- Multi-SubAgent parallel orchestration

## 12. Existing Safe Local MVP Policy

`agent/subagents/local.py` is the Safe Local MVP:

- Fake/local delegation only.
- Parent-controlled request/result contracts.
- No real LLM, no external processes, no tool execution.
- Validates SUBAGENT.md frontmatter.
- Enforces `model=fake` and safe tool list.
- Redacts secret-like values.

Policy for the formal SubAgent System:

- Safe Local MVP remains a test baseline and reference.
- Formal implementation lives in `agent/subagent_system/`.
- Safe Local MVP's contracts inform the formal design but do not constrain
  production-grade extensions.
- Real delegation is designed in the formal system and gated behind config +
  dogfood + audit.

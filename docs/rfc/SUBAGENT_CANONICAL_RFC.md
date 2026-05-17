# SubAgent Canonical RFC

Status: Canonical design for the formal SubAgent System.

This RFC defines SubAgent as a parent-controlled bounded delegation unit. It is written
for a Coding Agent implementation loop: tests and code should trace back to the
contracts below. The formal implementation namespace will be `agent/subagent_system/`; the
existing `agent/subagents/local.py` is the Safe Local MVP and remains a test baseline.

## 1. Goal

A **SubAgent** is a parent-controlled bounded delegation unit. The Parent Agent
authorizes a SubAgent to execute a specific task within explicit boundaries —
restricted tools, restricted skills, bounded iterations, and governed
Memory/Checkpoint access. The SubAgent returns a structured result to the Parent
Agent; it never owns the main loop or bypasses governance.

Core properties:

- Parent Agent owns orchestration and delegates only bounded work.
- SubAgent receives a delegation request with explicit constraints.
- SubAgent returns a structured delegation result.
- Tools, Memory, Checkpoint, Confirmation all remain governed by the Parent
  Runtime and existing authorities (ToolRegistry, Memory governance,
  Checkpoint schema owner).

## 2. Industry References and Design Adaptation

### 2.1 OpenAI Agents SDK — Handoffs / Agents-as-Tools

**What we studied**:

- **Handoffs**: parent transfers conversation to a specialist agent; the
  receiving agent sees full (optionally filtered) history.
- **Agents-as-tools**: orchestrator retains control; sub-agent is wrapped as a
  callable tool, runs a bounded internal loop, returns `RunResult`.
- **Guardrails**: input guardrails run on first agent; output guardrails on
  final agent; tool guardrails on every tool call. Intermediate agents have no
  guardrail coverage.
- **`is_enabled`** dynamic gating and **`max_turns`** bounded execution.

**What we adopt**:

- Parent-controlled delegation model (agents-as-tools style, not full handoff).
- Bounded execution through `max_iterations`.
- SubAgent returns structured result; parent remains orchestrator.
- Per-subagent tool allowlist as upper bound.

**What we reject**:

- Full conversation handoff (transfers too much control; parent loses
  visibility during delegation).
- Guardrail gaps for intermediate agents (First Agent requires every
  delegation to carry its own governance, not rely on entry/exit-only
  guardrails).

### 2.2 Claude Code Subagents

**What we studied**:

- Subagents run in their own context window with custom system prompt, specific
  tool access, independent permissions.
- Tool allowlist (`tools`) and denylist (`disallowedTools`). `maxTurns` bounds
  execution.
- Subagents **cannot spawn other subagents** (no nested delegation).
- `isolation: worktree` for filesystem isolation.
- Results summarized back to parent; no context pollution.
- Built-in agents: Explore (Haiku, read-only), Plan, General-purpose.

**What we adopt**:

- SubAgent as role-specific bounded executor with isolated tool access.
- No nested SubAgent spawning in v1.
- `max_iterations` as hard bound.
- Results flow back summarized, not as raw transcript dumps.
- SubAgent receives metadata-level context only (progressive disclosure
  analogue).

**What we reject**:

- Worktree isolation in v1 (too heavyweight for safe local first step; can be
  added later as an option).
- Inheriting all parent tools by default (First Agent starts with explicit
  allowlist; empty by default is safer).
- Agent Teams / peer-to-peer communication (out of scope for bounded
  delegation model).

### 2.3 Anthropic Agent Skills — the Reverse Boundary

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

### 2.4 First Agent Adaptation Rationale

First Agent adopts **parent-controlled bounded delegation** rather than fully
autonomous multi-agent architectures because:

1. **Governance continuity**: ToolRegistry, Memory governance, Checkpoint, and
   Confirmation must remain single-source-of-truth. Autonomous agents with
   independent tool access would fracture this.
2. **Safe local first**: Real LLM delegation is deferred. The Safe Local MVP
   (`agent/subagents/local.py`) already demonstrates the fake/local
   request/result pattern and serves as a test baseline.
3. **No unbounded autonomy**: Every delegation has `max_iterations`, explicit
   `allowed_tools`, and explicit `allowed_skills`. No SubAgent gets a blank
   check.
4. **Incremental complexity**: Start with bounded fake/local execution; add
   real LLM delegation only when all boundaries are proven in tests.

## 3. Non-goals

- SubAgent is not Skill. Skill is a capability package; SubAgent is an
  execution context.
- SubAgent is not Tool. Tool is an executable action; SubAgent is a bounded
  delegate.
- SubAgent does not replace Parent Agent. Parent Agent owns orchestration.
- SubAgent does not own an unbounded autonomous loop.
- SubAgent does not bypass ToolRegistry.
- SubAgent does not directly write Memory.
- SubAgent does not default to real LLM invocation.
- SubAgent does not default to spawning external processes.
- SubAgent does not default to accessing `.env`, real `sessions/`, or real
  `runs/`.
- SubAgent does not have independent long-term memory by default.
- SubAgent does not use DB, graph, embedding, or vector store.
- SubAgent does not directly modify checkpoint schema.
- SubAgent does not spawn nested SubAgents in v1.

## 4. Relationship To Other Systems

### SubAgent vs Parent Agent

Parent Agent owns the main loop, orchestration, and decision authority.
SubAgent is a bounded execution context that Parent Agent creates, constrains,
and reviews. SubAgent receives a delegation request and returns a delegation
result; it never takes over the main loop.

### SubAgent vs Skill

A Skill is a filesystem-first capability package (instructions, constraints,
resources). A SubAgent is an execution context that may be authorized to use
certain Skills. The Skill System remains the authority for Skill loading,
progressive disclosure, and Skill governance. A SubAgent does not bypass
L1/L2/L3 loading or Skill tool boundaries.

### SubAgent vs Tool

Tools are executable capability endpoints registered through ToolRegistry.
SubAgent is a bounded delegate that may request tool execution through the
Parent Agent. ToolRegistry remains the authority for capability, risk,
confirmation, and execution. A SubAgent cannot directly execute tools, lower
tool risk, or skip confirmation.

### SubAgent vs Memory

Memory stores governed cross-session facts and preferences. A SubAgent may
receive read-only memory context through the Memory adapter. It may emit
memory proposals, but only the Parent/Memory governance path can adjudicate
and persist them. No direct MemoryStore write, no silent retain, no auto
approve.

### SubAgent vs Runtime / Loop

Runtime owns the Agent loop, status transitions, checkpoint/resume, model
calls, and tool execution orchestration. SubAgent delegation is a
request/result flow inside Runtime. The SubAgent may have bounded local
iteration only within its `max_iterations` limit. It cannot start its own
unbounded loop, mutate Runtime state directly, or own checkpoint timing.

### SubAgent vs Checkpoint / Resume

Checkpoint remains the source of recoverability. A SubAgent's in-flight state
must be checkpoint-safe: only bounded correlation metadata, no full prompt
dumps, no secret storage, no raw large artifacts. On resume, Parent Agent
reconstructs delegation state from checkpoint metadata; high-risk tool
execution is never replayed.

### SubAgent vs Confirmation / Ask User

Confirmation is governed by ToolRegistry/runtime policy. A SubAgent cannot
auto-approve a high-risk tool, skip confirmation, or silently continue past a
confirmation gate. If a SubAgent's requested action requires confirmation, the
Parent Agent (or the runtime confirmation system) handles it.

### SubAgent vs CLI/TUI

CLI/TUI display available SubAgent descriptors, delegation status, result
summaries, and audit records. CLI/TUI do not implement SubAgent selection,
delegation, execution, tool calls, or Memory writes.

### SubAgent vs Existing Safe Local MVP

`agent/subagents/local.py` is the Safe Local MVP — fake/local delegation only
with parent-controlled request/result contracts. It does not call real LLMs,
spawn external processes, or execute tools. The formal SubAgent System
(`agent/subagent_system/`) will build on this contract model while adding
formal registry, bounded execution, and governance boundaries. The Safe Local
MVP remains a test baseline throughout.

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
| `risk_level` | str | yes | `low` / `medium` / `high` |
| `confirmation_policy` | str | yes | `inherit_tool_policy` / `require_parent` |
| `parent_trace_id` | str | yes | Correlation ID for audit trail |
| `delegation_reason` | str | yes | Why Parent Agent is delegating |
| `context` | dict | no | Additional structured context |

### 5.2 SubAgentContext

Assembled by the delegation adapter before SubAgent execution:

| Field | Description |
|-------|-------------|
| `request` | The `SubAgentRequest` |
| `descriptor` | The matched `SubAgentDescriptor` |
| `memory_context` | Read-only memory snapshot (if `memory_scope` ≥ `read_context`) |
| `skill_context` | L1 metadata for allowed Skills only (progressive disclosure) |
| `tool_registry_snapshot` | Read-only view of allowed tools with risk/confirmation metadata |
| `parent_state` | Minimal parent state needed for delegation (no secrets) |

### 5.3 SubAgentResult

Returned by the SubAgent to the Parent Agent:

| Field | Type | Description |
|-------|------|-------------|
| `status` | str | `ok` / `error` / `needs_confirmation` / `max_iterations_exceeded` |
| `summary` | str | Human-readable summary of work done |
| `artifacts` | tuple[str, ...] | References to produced artifacts (paths, not content) |
| `tool_requests` | tuple[str, ...] | Tools the SubAgent wants executed |
| `memory_proposals` | tuple[MemoryProposal, ...] | Memory proposals (not writes) |
| `confidence` | float | 0.0–1.0 self-assessment |
| `warnings` | tuple[str, ...] | Non-blocking issues found |
| `audit` | SubAgentAuditRecord | Structured audit trail |
| `handoff_back` | str | Explicit handoff note to Parent Agent |

### 5.4 SubAgentError

Structured error from a failed delegation:

| Field | Type | Description |
|-------|------|-------------|
| `code` | str | Machine-readable error code |
| `message` | str | Human-readable error (sanitized, no secrets) |
| `source` | str | `descriptor` / `policy` / `execution` / `parent` |
| `recoverable` | bool | Whether Parent Agent can retry |

### 5.5 SubAgentAuditRecord

| Field | Description |
|-------|-------------|
| `subagent_name` | Matched SubAgent descriptor name |
| `delegation_id` | Unique delegation ID |
| `parent_trace_id` | Correlation to parent |
| `status` | Final status |
| `iterations_used` | Actual iterations consumed |
| `max_iterations` | Hard bound |
| `tools_requested` | Tools SubAgent asked for |
| `tools_denied` | Tools blocked by policy |
| `memory_proposals_count` | Number of memory proposals emitted |
| `warnings` | Non-blocking issues |
| `elapsed_ms` | Wall-clock time |

## 6. Governance

### 6.1 Parent Control

- Parent Agent decides when and why to delegate.
- Parent Agent sets `allowed_tools` upper bound — SubAgent cannot expand it.
- Parent Agent sets `max_iterations` — SubAgent cannot exceed it.
- Parent Agent reviews SubAgentResult and decides next action.

### 6.2 ToolRegistry Authority

- `allowed_tools` on SubAgentRequest is an upper bound, not authorization.
- ToolRegistry remains the authority for tool capability, risk level, and
  confirmation policy.
- SubAgent cannot lower a tool's risk level.
- SubAgent cannot skip confirmation for high-risk tools.
- Hidden/internal tools are never exposed to SubAgents.

### 6.3 Memory Governance

- Default memory access is `none`.
- `read_context` provides read-only memory snapshot — no write path.
- `propose` allows SubAgent to emit `MemoryProposal` objects.
- All proposals go through existing Memory governance — no auto-approve.
- SubAgent has no direct reference to MemoryStore.

### 6.4 Confirmation Boundary

- SubAgent's `confirmation_policy` is either `inherit_tool_policy` (default)
  or `require_parent` (Parent must confirm every tool execution).
- SubAgent cannot set `confirmation_policy` to a weaker level than the tool
  requires.
- Human confirmation still gates high-risk actions regardless of SubAgent
  policy.

### 6.5 Reviewability

- Every SubAgentResult includes a structured audit record.
- Parent Agent can inspect `tools_requested`, `tools_denied`,
  `memory_proposals_count`, and `warnings`.
- CLI/TUI can display delegation audit trail.

## 7. Loop Model

- Parent Agent owns the main Agent loop.
- SubAgent may have bounded local iteration only if `max_iterations > 1`.
- `max_iterations` is required and must be ≥1.
- When `max_iterations` is exceeded, SubAgent returns
  `status=max_iterations_exceeded` with a best-effort summary.
- No unbounded autonomous recursion.
- No SubAgent spawning SubAgent in v1 (no nested delegation).
- No multi-agent swarm / peer-to-peer in v1.
- SubAgent cannot call the provider directly to extend its own loop.

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
- Checkpoint stores only bounded correlation metadata: `delegation_id`,
  `subagent_name`, `status`, `iterations_used`, `max_iterations`,
  `parent_trace_id`, and pending confirmation state.
- Checkpoint does NOT store: full SubAgent prompt, full transcript, raw tool
  outputs, raw artifacts, secrets, or large resource content.
- On resume, Parent Agent reconstructs delegation state from checkpoint
  metadata.
- High-risk tool execution is never replayed on resume.
- Checkpoint schema changes require explicit design approval.

## 10. Existing Safe Local MVP Policy

`agent/subagents/local.py` is the Safe Local MVP:

- Fake/local delegation only.
- Parent-controlled request/result contracts.
- No real LLM, no external processes, no tool execution.
- Validates SUBAGENT.md frontmatter (name, description, role, allowed-tools).
- Enforces `model=fake` and safe tool list (`read_file` only).
- Redacts secret-like values in profiles and summaries.

Policy for the formal SubAgent System:

- Safe Local MVP remains a test baseline and reference.
- Formal implementation lives in `agent/subagent_system/`.
- Real delegation (real LLM, real tool execution) is deferred until an
  explicit phase with user approval.
- The Safe Local MVP's `SubagentProfile`, `DelegationRequest`, and
  `DelegationResult` contracts inform but do not constrain the formal
  SubAgentRequest/Result design — the formal system may evolve the contract
  while preserving the parent-controlled delegation principle.

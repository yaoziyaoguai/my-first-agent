# SubAgent System SDD

Status: System Design Document for the production-grade formal SubAgent System.
This is the target architecture — implementation proceeds through phases with
safety gates. The formal namespace is `agent/subagent_system/`. The existing
`agent/subagents/local.py` Safe Local MVP is a test baseline, not the formal
implementation.

## 1. Module Design

```
agent/subagent_system/
  __init__.py           # Formal namespace declaration
  descriptor.py         # SubAgentDescriptor, SUBAGENT.md parsing
  request.py            # SubAgentRequest (frozen dataclass)
  context.py            # SubAgentContextPackage assembly
  context_window.py     # Isolated context window management, budget enforcement
  result.py             # SubAgentResult, SubAgentError, SubAgentAuditRecord
  registry.py           # Filesystem registry, runtime/session scoped
  policy.py             # SubAgentPolicy, parent control boundary
  execution_mode.py     # SubAgentExecutionMode enum and mode policy
  delegation.py         # Delegation adapter, request/result flow
  executor.py           # Bounded local executor
  runtime.py            # SubAgentRun lifecycle, state machine
  adjudication.py       # Parent adjudication, result merge, revision loop
  memory_boundary.py    # Memory read/propose boundary
  tool_boundary.py      # ToolRegistry authority boundary
  skill_boundary.py     # Skill System authority boundary
  checkpoint.py         # Checkpoint safety summary
  trace.py              # SubAgentTraceEvent, observability
  sandbox.py            # Sandbox contract and policy (design only until L3)
  presentation.py       # CLI/TUI display
  errors.py             # Structured error types
```

Each module is focused on a single responsibility. No module holds more than
one governance boundary. Files are not created until their respective
implementation phases.

## 2. Data Structures

### 2.1 SubAgentDescriptor

```python
@dataclass(frozen=True)
class SubAgentDescriptor:
    """Parsed from SUBAGENT.md frontmatter, frozen."""
    name: str                    # kebab-case, must match parent directory name
    description: str             # Single-line description
    role: str                    # reviewer / planner / auditor / tester / custom
    model: str                   # fake / fixture / none / anthropic / openai (v1: fake/fixture/none)
    status: str                  # active / deprecated / disabled
    risk_level: str              # low / medium / high
    allowed_tools: tuple[str, ...]  # Upper bound
    allowed_skills: tuple[str, ...] # Upper bound (default empty)
    memory_scope: str            # none / read_context / propose
    max_iterations_default: int  # Default max_iterations (v1: 1-10)
    confirmation_policy: str     # inherit_tool_policy / require_parent
    supported_modes: tuple[str, ...]  # Execution modes this SubAgent supports
    tags: tuple[str, ...]
    version: str
    source_dir: str              # Filesystem path (internal use only)
```

`supported_modes` declares which execution modes this SubAgent supports.
A reviewer SubAgent supports `local_fake`, `local_deterministic`,
`real_llm_readonly`. A tool-capable SubAgent additionally supports
`real_llm_tool_requesting`. The actual mode is selected by parent at
delegation time, bounded by descriptor capabilities.

### 2.2 SubAgentRequest

```python
@dataclass(frozen=True)
class SubAgentRequest:
    """Parent Agent creates a delegation request."""
    task: str
    role: str
    allowed_tools: tuple[str, ...]
    allowed_skills: tuple[str, ...]       # default ()
    memory_scope: str                      # default "none"
    max_iterations: int                    # default 1
    execution_mode: str                    # default "local_fake"
    risk_level: str
    confirmation_policy: str               # default "inherit_tool_policy"
    parent_trace_id: str
    delegation_reason: str
    context: dict[str, Any]                # default {}
    output_schema: dict[str, Any] | None   # default None
    max_revisions: int                     # default 1
    relevant_files: tuple[str, ...]        # default ()
```

### 2.3 SubAgentContextPackage

```python
@dataclass(frozen=True)
class SubAgentContextPackage:
    """Packaged context for isolated SubAgent execution."""
    request: SubAgentRequest
    descriptor: SubAgentDescriptor
    task: str
    role_prompt: str                       # Role-specific system prompt
    goal: str                              # Explicit goal statement
    constraints: tuple[str, ...]           # Hard constraints
    relevant_files: tuple[str, ...]
    relevant_summaries: tuple[FileSummary, ...]  # Summaries, not full files
    selected_memory_context: str | None    # Read-only memory snapshot
    selected_skill_metadata: tuple[SkillL1, ...]  # L1 metadata only
    allowed_tools: tuple[ToolSnapshot, ...]  # name, description, risk, confirmation
    allowed_skills: tuple[str, ...]
    forbidden_actions: tuple[str, ...]     # Explicitly blocked
    output_schema: dict[str, Any] | None
    max_context_chars: int                 # Context window budget
    max_iterations: int
    stop_conditions: tuple[str, ...]       # SubAgentStopReason values
    execution_mode: str
```

### 2.4 SubAgentResult and Related Types

```python
@dataclass(frozen=True)
class SubAgentResult:
    status: str  # ok / error / needs_confirmation / max_iterations_exceeded /
                 # max_context_exceeded / needs_clarification / tool_blocked /
                 # policy_blocked / interrupted
    summary: str
    artifacts: tuple[str, ...]
    tool_requests: tuple[ToolRequest, ...]
    memory_proposals: tuple[MemoryProposal, ...]
    confidence: float
    warnings: tuple[str, ...]
    audit: SubAgentAuditRecord
    handoff_back: str
    clarification_question: str | None
    trace_events: tuple[SubAgentTraceEvent, ...]
    stop_reason: str  # SubAgentStopReason

@dataclass(frozen=True)
class ParentAdjudicationResult:
    action: str          # accept / reject / revise / ask_user
    reason: str
    merged_summary: str | None
    tool_calls_to_execute: tuple[str, ...]
    memory_proposals_to_route: tuple[MemoryProposal, ...]
    revised_request: SubAgentRequest | None
    user_question: str | None

@dataclass(frozen=True)
class SubAgentRun:
    """Runtime tracking for one delegation lifecycle."""
    delegation_id: str
    state: str  # pending / packaging / running / awaiting_confirmation /
                # awaiting_adjudication / revising / completed / failed
    request: SubAgentRequest
    descriptor: SubAgentDescriptor
    context_package: SubAgentContextPackage | None
    result: SubAgentResult | None
    adjudication: ParentAdjudicationResult | None
    revision_count: int
    created_at: float
    updated_at: float

@dataclass(frozen=True)
class ToolRequest:
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    risk_level: str  # from ToolRegistry

@dataclass(frozen=True)
class FileSummary:
    path: str
    summary: str       # Summarized content, not full file
    line_count: int
    language: str

@dataclass(frozen=True)
class ToolSnapshot:
    name: str
    description: str
    risk_level: str
    requires_confirmation: bool
    is_hidden: bool
```

### 2.5 SubAgentExecutionMode

```python
class SubAgentExecutionMode(Enum):
    LOCAL_FAKE = "local_fake"
    LOCAL_DETERMINISTIC = "local_deterministic"
    REAL_LLM_READONLY = "real_llm_readonly"
    REAL_LLM_TOOL_REQUESTING = "real_llm_tool_requesting"
    SANDBOXED_TOOL_CAPABLE = "sandboxed_tool_capable"
```

Each mode has a policy:

| Mode | Allowed Tools | Network | Memory | Checkpoint | Confirmation |
|------|--------------|---------|--------|------------|-------------|
| `local_fake` | read_file (fake) | blocked | read_context | yes | inherited |
| `local_deterministic` | read_file (fake) | blocked | read_context | yes | inherited |
| `real_llm_readonly` | read_file, grep, glob | blocked | read_context | yes | inherited |
| `real_llm_tool_requesting` | parent-mediated | blocked | propose | yes | inherited |
| `sandboxed_tool_capable` | sandbox-scoped | policy-defined | propose | yes | inherited |

Mode escalation rules:
- Parent selects mode at delegation time.
- Selected mode must be in `descriptor.supported_modes`.
- Higher modes require explicit config gate (`subagent.real_llm_readonly.enabled`,
  `subagent.tool_requesting.enabled`, `subagent.sandbox.enabled`).
- Mode cannot be escalated by SubAgent.

### 2.6 SubAgentStopReason

```python
class SubAgentStopReason(Enum):
    TASK_COMPLETED = "task_completed"
    TASK_COMPLETED_LOW_CONFIDENCE = "task_completed_low_confidence"
    MAX_ITERATIONS_EXCEEDED = "max_iterations_exceeded"
    MAX_CONTEXT_EXCEEDED = "max_context_exceeded"
    NEEDS_CLARIFICATION = "needs_clarification"
    NEEDS_CONFIRMATION = "needs_confirmation"
    TOOL_BLOCKED = "tool_blocked"
    POLICY_BLOCKED = "policy_blocked"
    ERROR = "error"
    INTERRUPTED = "interrupted"
```

### 2.7 SubAgentPolicy

```python
@dataclass(frozen=True)
class SubAgentPolicy:
    """Parent-controlled execution boundaries. Cannot be modified by SubAgent."""
    local_only: bool = True
    real_llm_readonly_allowed: bool = False          # Config gate
    real_llm_tool_requesting_allowed: bool = False    # Config gate
    sandboxed_tool_capable_allowed: bool = False      # Config gate
    external_process_allowed: bool = False            # Requires sandbox phase
    worktree_isolation_allowed: bool = False          # Future phase
    autonomous_tool_execution_allowed: bool = False   # v1: false
    max_nested_depth: int = 0                         # v1: 0
    max_context_chars: int = 100_000                  # Default context budget
    max_revisions: int = 1                            # Default revision rounds
    default_mode: str = "local_fake"                  # Default execution mode
```

### 2.8 SubAgentToolBoundary

```python
@dataclass(frozen=True)
class SubAgentToolBoundary:
    """SubAgent tool permission boundary. Pure check, no execution."""
    def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        descriptor: SubAgentDescriptor,
        request: SubAgentRequest,
        tool_registry: ToolRegistry,
    ) -> ToolCheckResult:
        """Validate tool is within effective bounds and ToolRegistry rules."""
        ...

@dataclass(frozen=True)
class ToolCheckResult:
    allowed: bool
    tool_name: str
    risk_level: str             # From ToolRegistry
    requires_confirmation: bool # From ToolRegistry
    deny_reason: str | None     # Why denied, if not allowed
```

In sandbox mode (L3+), `ToolBoundary` additionally validates that tool
execution is scoped to the sandbox root and does not mutate real repo state.

### 2.9 SubAgentSkillBoundary

```python
@dataclass(frozen=True)
class SubAgentSkillBoundary:
    """SubAgent Skill permission boundary. Delegates loading to Skill System."""
    def check(
        self,
        skill_name: str,
        descriptor: SubAgentDescriptor,
        skill_system: SkillSystem,
    ) -> SkillCheckResult:
        """Validate Skill is in allowed_skills; delegate loading to Skill System."""
        ...

@dataclass(frozen=True)
class SkillCheckResult:
    allowed: bool
    skill_name: str
    l1_metadata: SkillL1 | None  # Name, description, tags only
    deny_reason: str | None
```

### 2.10 SubAgentMemoryBoundary

```python
@dataclass(frozen=True)
class SubAgentMemoryBoundary:
    """SubAgent Memory permission boundary."""
    def read_context(self, scope: str) -> str | None:
        """Return read-only snapshot if scope >= read_context."""
        ...

    def check_proposal(self, proposal: MemoryProposal) -> bool:
        """Validate proposal can be routed through governance."""
        ...
```

### 2.11 SubAgentTraceEvent

```python
@dataclass(frozen=True)
class SubAgentTraceEvent:
    event_type: str  # delegation_started / context_packaged / iteration_started /
                     # tool_requested / tool_denied / tool_executed /
                     # confirmation_required / confirmation_resolved /
                     # result_returned / result_adjudicated / revision_requested /
                     # delegation_failed / resumed_from_checkpoint /
                     # delegation_completed
    delegation_id: str
    timestamp: float
    data: dict[str, Any]  # Event-specific payload (sanitized, no secrets)
    parent_trace_id: str
```

### 2.12 SubAgentCheckpointSummary

```python
@dataclass(frozen=True)
class SubAgentCheckpointSummary:
    """Checkpoint-safe delegation summary. No raw prompt / secret / large artifact."""
    delegation_id: str
    subagent_name: str
    status: str
    execution_mode: str
    iterations_used: int
    max_iterations: int
    parent_trace_id: str
    pending_confirmation: tuple[str, ...]  # Tool names awaiting confirmation
    stop_reason: str
    revision_count: int
```

### 2.13 SubAgentAuditRecord

```python
@dataclass(frozen=True)
class SubAgentAuditRecord:
    subagent_name: str
    delegation_id: str
    parent_trace_id: str
    execution_mode: str
    status: str
    stop_reason: str
    iterations_used: int
    max_iterations: int
    tools_requested: tuple[str, ...]
    tools_denied: tuple[str, ...]
    tools_executed: tuple[str, ...]
    memory_proposals_count: int
    warnings: tuple[str, ...]
    confidence: float
    elapsed_ms: int
    revision_count: int
    trace_event_count: int
```

## 3. Registry Design

### 3.1 Principles

- **Runtime/session scoped**: registry is instantiated per session, not a
  module-level global singleton.
- **Filesystem-first**: scans explicit root directories for `SUBAGENT.md`
  files.
- **Deterministic**: same roots → same descriptors in stable order.
- **Fail-closed**: invalid `SUBAGENT.md` → not registered; duplicate names →
  error.

### 3.2 Registry API

```python
class SubAgentRegistry:
    def __init__(self, roots: list[Path]):
        """Scan roots for directories containing SUBAGENT.md."""

    def list_visible(self) -> tuple[SubAgentDescriptor, ...]:
        """Return status=active descriptors."""

    def get_descriptor(self, name: str) -> SubAgentDescriptor | None:
        """Look up by name."""

    def find_by_role(self, role: str) -> tuple[SubAgentDescriptor, ...]:
        """Find all active descriptors matching role."""

    def is_registered(self, name: str) -> bool:
        """Check if name is registered."""

    def reload(self) -> None:
        """Re-scan roots."""
```

### 3.3 SUBAGENT.md Format

```yaml
---
name: code-reviewer
description: Review code changes for correctness, style, and safety.
role: reviewer
model: fake
status: active
risk_level: low
version: 0.1.0
tags:
  - review
  - quality
allowed_tools:
  - read_file
  - grep
allowed_skills: []
memory_scope: read_context
max_iterations_default: 3
confirmation_policy: inherit_tool_policy
supported_modes:
  - local_fake
  - local_deterministic
  - real_llm_readonly
---

# Code Reviewer

Instructions for the code reviewer subagent...
```

### 3.4 Validation Rules

- `name`: required, kebab-case, must match parent directory name.
- `description`: required, non-empty string.
- `role`: required, non-empty string.
- `model`: must be a known model identifier. v1 restricts to
  `fake`/`fixture`/`none`; `anthropic`/`openai` gated behind config.
- `status`: `active` / `deprecated` / `disabled`.
- `allowed_tools`: each tool must be a known tool name. Empty is valid.
- `allowed_skills`: each must reference a registered Skill descriptor. Empty is
  valid.
- `supported_modes`: must be subset of `SubAgentExecutionMode` values. v1
  defaults to `local_fake` only; other modes gated.
- Duplicate names across roots → `SubAgentLoadError`.
- Invalid frontmatter → fail-closed (not registered).

## 4. Context Packaging

The `context_window.py` module assembles a `SubAgentContextPackage` from:

1. `SubAgentRequest` (parent-provided constraints)
2. `SubAgentDescriptor` (registered capabilities)
3. Memory context (via `SubAgentMemoryBoundary`, if scope permits)
4. Skill metadata (via `SubAgentSkillBoundary`, L1 only)
5. Tool snapshot (via `SubAgentToolBoundary`, effective tools)
6. File summaries (from `relevant_files`, summarized, not full content)

Context budget (`max_context_chars`) is enforced during packaging. If the
package exceeds the budget, summaries are trimmed and a warning is emitted.
SubAgent never receives full repository context — only what fits in the budget
and is relevant to the task.

## 5. Tool Execution Design

Tools are categorized for SubAgent interaction:

| Category | Examples | SubAgent Access | Execution Path |
|----------|----------|----------------|----------------|
| Read-only safe | `read_file`, `grep`, `glob` | Direct snapshot in context | N/A (read at packaging time) |
| Read-only gated | `web_search`, `web_fetch` | Request only | Parent-mediated |
| High-risk | `shell_exec`, `write_file` | Request only | Parent-mediated + confirmation |
| Write | `apply_patch`, `git_commit` | Request only | Parent-mediated + confirmation + sandbox/worktree gate |
| Hidden/Internal | `debug_tool`, `raw_memory_write` | Never exposed | Blocked by ToolBoundary |

Tool request flow:
1. SubAgent emits `ToolRequest(tool_name, arguments, reason)`.
2. `SubAgentToolBoundary.check()` validates against effective tools.
3. ToolRegistry validates risk level and confirmation requirement.
4. If denied → `SubAgentTraceEvent(tool_denied)`.
5. If requires confirmation → `SubAgentTraceEvent(confirmation_required)`.
6. If allowed → parent executes via `ToolRegistry` and returns result.
7. `SubAgentTraceEvent(tool_executed)` recorded.

## 6. Result Merge and Adjudication

### 6.1 Adjudication Flow

```
SubAgentResult
  │
  ├─ status=ok, confidence>=threshold ──→ accept_result / merge_summary
  ├─ status=ok, confidence<threshold ──→ request_revision (if revisions remain)
  │                                      or accept_result with warning
  ├─ status=needs_confirmation ──→ ask_user or reject_result
  ├─ status=max_iterations_exceeded ──→ accept_result (best-effort)
  │                                     or re-delegate (new delegation_id)
  ├─ status=error ──→ reject_result or re-delegate
  ├─ status=needs_clarification ──→ parent answers, request_revision
  └─ status=interrupted ──→ resume from checkpoint or re-delegate
```

### 6.2 Merge Rules

- Parent can merge SubAgent summary into its own context.
- SubAgent-produced artifacts are referenced, not inlined.
- Tool requests from SubAgent are converted to parent tool calls.
- Memory proposals are routed through Memory governance.
- Low-confidence results carry a warning in the merged summary.
- Conflicting results from multiple SubAgents (L5, future) require explicit
  parent resolution.

### 6.3 Revision Loop

- Parent may request revision up to `max_revisions` times.
- Each revision is a new delegation run (new `delegation_id`, reset iterations).
- SubAgent receives updated `SubAgentRequest` with refined task.
- Revision history preserved via `SubAgentRun.revision_count` and trace events.
- After `max_revisions` exhausted, parent must accept or reject.

## 7. Runtime Integration

- Parent Agent loop remains the main loop.
- `runtime.py` manages `SubAgentRun` lifecycle: `pending → packaging → running →
  awaiting_confirmation → awaiting_adjudication → revising → completed/failed`.
- `delegation.py` provides the request/result adapter.
- `executor.py` runs the SubAgent within its `max_iterations` bound.
- Provider access is gated by `execution_mode`:
  - `local_fake` / `local_deterministic`: no provider call.
  - `real_llm_readonly` / `real_llm_tool_requesting`: provider call mediated
    by Runtime, with explicit config gate.
  - `sandboxed_tool_capable`: provider call + scoped tool execution in sandbox.
- No recursive SubAgent spawning (enforced by `SubAgentPolicy.max_nested_depth=0`
  in v1).
- SubAgent cannot call provider directly — Runtime mediates all provider access.

## 8. Sandbox Design (L3, Contract Only Until Gated Phase)

For `sandboxed_tool_capable` mode:

- SubAgent runs with a scoped filesystem root (e.g., `/tmp/subagent-{id}/`).
- Tool execution is constrained to the sandbox root.
- Read-only access to project files still goes through parent-mediated
  `read_file`.
- Write operations (`write_file`, `apply_patch`) operate within sandbox.
- Sandbox results (patches, generated files) are returned as artifacts for
  parent review.
- No real repo mutation without parent approval and worktree isolation.
- Sandbox cleanup: sandbox root deleted after delegation completes (or on
  session exit for interrupted delegations).

## 9. Checkpoint Integration

- `SubAgentCheckpointSummary` stores only bounded correlation metadata.
- No full prompt dumps, no transcript storage, no secret storage.
- No raw tool outputs or large artifacts in checkpoint.
- On resume, Parent Agent reads checkpoint summary and decides: re-delegate,
  revise, explain, or abort.
- High-risk tool execution is never replayed from checkpoint.
- Pending confirmation state is preserved.
- `SubAgentRun.state` is recoverable from checkpoint metadata.

## 10. CLI/TUI

- `presentation.py` provides display-only formatting:
  - `format_available_subagents(registry)` — list of visible descriptors with
    supported modes.
  - `format_delegation_status(run)` — pending/running/awaiting state.
  - `format_delegation_result(result)` — result summary with confidence and
    stop reason.
  - `format_subagent_audit(audit)` — audit trail.
  - `format_trace_events(trace_events)` — trace log.
  - `format_adjudication(adjudication)` — parent adjudication decision.
- CLI/TUI does not import executor, tool boundary, memory boundary, or runtime.
- Presentation is thin — no runtime logic.

## 11. Error Design

```python
class SubAgentError(Exception):
    """Base error for SubAgent System."""
    code: str
    message: str  # sanitized, no secrets

class SubAgentLoadError(SubAgentError):
    """SUBAGENT.md parse/validation failure."""
    path: str | None

class SubAgentPolicyError(SubAgentError):
    """Delegation violates parent policy."""

class SubAgentExecutionError(SubAgentError):
    """Execution-time error (max_iterations, context budget, etc.)."""

class SubAgentToolDeniedError(SubAgentError):
    """Tool request denied by ToolBoundary or ToolRegistry."""

class SubAgentMemoryDeniedError(SubAgentError):
    """Memory operation denied by MemoryBoundary."""

class SubAgentModeError(SubAgentError):
    """Execution mode not supported or not enabled."""

class SubAgentContextBudgetError(SubAgentError):
    """Context package exceeds budget."""
```

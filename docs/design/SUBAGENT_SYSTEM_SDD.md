# SubAgent System SDD

Status: System Design Document for the formal SubAgent System. Implementation
deferred; this document guides the Coding Agent implementation loop.

The formal namespace will be `agent/subagent_system/`. The existing
`agent/subagents/local.py` Safe Local MVP is a test baseline, not the formal
implementation.

## 1. Module Design

```
agent/subagent_system/
  __init__.py          # 正式命名空间声明
  descriptor.py        # SubAgentDescriptor, SUBAGENT.md 解析
  request.py           # SubAgentRequest (frozen dataclass)
  context.py           # SubAgentContext 组装
  result.py            # SubAgentResult, SubAgentError, SubAgentAuditRecord
  registry.py          # 文件系统 registry，runtime/session scoped
  policy.py            # SubAgentPolicy, 父控边界
  delegation.py        # 委托适配器，request/result 流
  executor.py          # 有界本地执行器 (fake/local first)
  memory_boundary.py   # Memory 读/提议边界
  tool_boundary.py     # ToolRegistry 权威边界
  skill_boundary.py    # Skill System 权威边界
  checkpoint.py        # Checkpoint 安全摘要
  presentation.py      # CLI/TUI 展示
  errors.py            # 结构化错误类型
```

Each module is focused on a single responsibility. No module holds more than
one governance boundary. This is a design document — files are not created
until their respective implementation phases.

## 2. Data Structures

### 2.1 SubAgentDescriptor

```python
@dataclass(frozen=True)
class SubAgentDescriptor:
    """从 SUBAGENT.md 解析的元数据，frozen。"""
    name: str                    # kebab-case，与目录名一致
    description: str             # 单行描述
    role: str                    # reviewer / planner / auditor / custom
    model: str                   # fake / fixture / none (v1)
    status: str                  # active / deprecated / disabled
    risk_level: str              # low / medium / high
    allowed_tools: tuple[str, ...]  # upper bound
    allowed_skills: tuple[str, ...] # upper bound (default empty)
    memory_scope: str            # none / read_context / propose
    max_iterations_default: int  # 默认 max_iterations (v1: 1)
    confirmation_policy: str     # inherit_tool_policy / require_parent
    tags: tuple[str, ...]
    version: str
    source_dir: str              # 文件系统路径 (internal use only)
```

### 2.2 SubAgentRequest

```python
@dataclass(frozen=True)
class SubAgentRequest:
    """Parent Agent 创建的委托请求。"""
    task: str
    role: str
    allowed_tools: tuple[str, ...]
    allowed_skills: tuple[str, ...]  # default ()
    memory_scope: str                # default "none"
    max_iterations: int              # default 1
    risk_level: str
    confirmation_policy: str         # default "inherit_tool_policy"
    parent_trace_id: str
    delegation_reason: str
    context: dict[str, Any]          # default {}
```

### 2.3 SubAgentContext

```python
@dataclass(frozen=True)
class SubAgentContext:
    """委托适配器在 SubAgent 执行前组装。"""
    request: SubAgentRequest
    descriptor: SubAgentDescriptor
    memory_context: str | None        # 只读 memory snapshot
    skill_descriptors: tuple[SkillDescriptor, ...]  # L1 only
    tool_snapshot: tuple[ToolSnapshot, ...]  # 允许的工具列表+risk+confirmation
    parent_state: dict[str, Any]      # 最小父状态
```

### 2.4 SubAgentResult

```python
@dataclass(frozen=True)
class SubAgentResult:
    status: str  # ok / error / needs_confirmation / max_iterations_exceeded
    summary: str
    artifacts: tuple[str, ...]
    tool_requests: tuple[str, ...]
    memory_proposals: tuple[Any, ...]  # MemoryProposal 类型
    confidence: float
    warnings: tuple[str, ...]
    audit: SubAgentAuditRecord
    handoff_back: str
```

### 2.5 SubAgentPolicy

```python
@dataclass(frozen=True)
class SubAgentPolicy:
    """父控执行边界，不可被子代理修改。"""
    local_only: bool = True
    real_llm_delegation_allowed: bool = False
    external_process_allowed: bool = False
    autonomous_tool_execution_allowed: bool = False
    max_nested_depth: int = 0  # v1: 0，不允许嵌套
```

### 2.6 SubAgentToolBoundary

```python
@dataclass(frozen=True)
class SubAgentToolBoundary:
    """SubAgent 的工具权限边界。"""
    def check(self, tool_name: str, descriptor: SubAgentDescriptor) -> ToolCheckResult:
        """验证工具是否在 allowed_tools 内，不绕过 ToolRegistry。"""
        ...
```

### 2.7 SubAgentSkillBoundary

```python
@dataclass(frozen=True)
class SubAgentSkillBoundary:
    """SubAgent 的 Skill 权限边界。"""
    def check(self, skill_name: str, descriptor: SubAgentDescriptor) -> SkillCheckResult:
        """验证 Skill 是否在 allowed_skills 内，不绕过 Skill System。"""
        ...
```

### 2.8 SubAgentMemoryBoundary

```python
@dataclass(frozen=True)
class SubAgentMemoryBoundary:
    """SubAgent 的 Memory 权限边界。"""
    def read_context(self, scope: str) -> str | None:
        """仅在 scope >= read_context 时返回只读快照。"""
        ...
    def check_proposal(self, proposal: Any) -> bool:
        """验证 memory proposal 可被 governance 路径接收。"""
        ...
```

### 2.9 SubAgentCheckpointSummary

```python
@dataclass(frozen=True)
class SubAgentCheckpointSummary:
    """Checkpoint 安全的委托摘要。不存 raw prompt / secret / 大文件。"""
    delegation_id: str
    subagent_name: str
    status: str
    iterations_used: int
    max_iterations: int
    parent_trace_id: str
    pending_confirmation: tuple[str, ...]  # 等待确认的工具名
```

### 2.10 SubAgentAuditRecord

```python
@dataclass(frozen=True)
class SubAgentAuditRecord:
    subagent_name: str
    delegation_id: str
    parent_trace_id: str
    status: str  # ok / error / needs_confirmation / max_iterations_exceeded
    iterations_used: int
    max_iterations: int
    tools_requested: tuple[str, ...]
    tools_denied: tuple[str, ...]
    memory_proposals_count: int
    warnings: tuple[str, ...]
    elapsed_ms: int
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
        """扫描 roots 下每个含 SUBAGENT.md 的子目录。"""
        ...

    def list_visible(self) -> tuple[SubAgentDescriptor, ...]:
        """返回 status=active 的 descriptor 列表。"""
        ...

    def get_descriptor(self, name: str) -> SubAgentDescriptor | None:
        """按 name 查找。"""
        ...

    def is_registered(self, name: str) -> bool:
        ...

    def reload(self) -> None:
        """重新扫描 roots。"""
        ...
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
allowed_skills: []
memory_scope: none
max_iterations_default: 1
confirmation_policy: inherit_tool_policy
---

# Code Reviewer

Instructions for the code reviewer subagent...
```

### 3.4 Validation Rules

- `name`: required, kebab-case, must match parent directory name.
- `description`: required, non-empty string.
- `role`: required, non-empty string.
- `model`: must be `fake`, `fixture`, or `none` in v1.
- `status`: `active` / `deprecated` / `disabled`.
- `allowed_tools`: each tool must be a known tool name.
- `allowed_skills`: each skill must reference a registered Skill descriptor.
- Duplicate names across roots → `SubAgentLoadError`.
- Invalid frontmatter → fail-closed (not registered).

## 4. Tool Boundary

- `allowed_tools` in `SubAgentDescriptor` is the upper bound.
- Parent Agent's `SubAgentRequest.allowed_tools` further restricts.
- Effective tools = `descriptor.allowed_tools ∩ request.allowed_tools`.
- `ToolRegistry` remains the authority for capability, risk, confirmation.
- `SubAgentToolBoundary.check()` validates each tool request against both the
  SubAgent's bounds and ToolRegistry's risk/confirmation rules.
- Unknown tools → blocked.
- Hidden/internal tools → never exposed.
- High-risk tools → confirmation required regardless of SubAgent policy.
- SubAgent cannot execute tools directly; all execution flows through
  `tool_executor` under Parent Runtime.

## 5. Skill Boundary

- `allowed_skills` is upper bound — SubAgent may only use explicitly listed
  Skills.
- Skill System remains authority for Skill loading, progressive disclosure,
  and Skill tool boundaries.
- SubAgent receives L1 metadata only (name, description, tags) for allowed
  Skills. Full body loading follows progressive disclosure.
- SubAgent cannot bypass Skill `confirmation_policy` or `memory_scope`.

## 6. Memory Boundary

- Default `memory_scope=none` — no memory access.
- `read_context` — read-only snapshot provided via adapter at delegation time.
- `propose` — SubAgent may emit `MemoryProposal` objects.
- `SubAgentMemoryBoundary.check_proposal()` validates proposals.
- All proposals flow through existing Memory governance — no auto-approve.
- No direct MemoryStore reference available to SubAgent.

## 7. Runtime Integration

- Parent Agent loop remains the main loop.
- `delegation.py` provides the request/result adapter.
- SubAgent execution is bounded local: fake/local in v1, real LLM deferred.
- `executor.py` runs the SubAgent within its `max_iterations` bound.
- No recursive SubAgent spawning (enforced by `SubAgentPolicy.max_nested_depth=0`).
- SubAgent cannot call provider directly.

## 8. Checkpoint Integration

- `SubAgentCheckpointSummary` stores only bounded correlation metadata.
- No full prompt dumps, no transcript storage, no secret storage.
- No raw tool outputs or large artifacts in checkpoint.
- On resume, Parent Agent reads checkpoint summary and decides: replay,
  re-delegate, or explain.
- High-risk tool execution is never replayed from checkpoint.

## 9. CLI/TUI

- `presentation.py` provides display-only formatting:
  - `format_available_subagents(registry)` → list of visible descriptors.
  - `format_delegation_result(result)` → result summary.
  - `format_subagent_audit(audit)` → audit trail.
- CLI/TUI does not import executor, tool boundary, or memory boundary.
- Presentation is thin — no runtime logic.

## 10. Error Design

```python
class SubAgentError(Exception):
    """Base error for SubAgent System."""
    code: str
    message: str  # sanitized, no secrets

class SubAgentLoadError(SubAgentError):
    """SUBAGENT.md 解析/验证失败。"""
    path: str | None

class SubAgentPolicyError(SubAgentError):
    """委托违反父控策略。"""

class SubAgentExecutionError(SubAgentError):
    """执行期错误（max_iterations exceeded, etc.）。"""

class SubAgentToolDeniedError(SubAgentError):
    """工具请求被 ToolBoundary 或 ToolRegistry 拒绝。"""

class SubAgentMemoryDeniedError(SubAgentError):
    """Memory 操作被 MemoryBoundary 拒绝。"""
```

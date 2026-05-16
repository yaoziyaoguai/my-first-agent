# Skill System SDD

This Software Design Document describes the formal Skill System to implement
after the canonical RFC. It is not an implementation patch.

## 1. Design Principles

- Filesystem-first packages with deterministic parsing.
- Progressive disclosure by default.
- Parent Runtime owns orchestration.
- ToolRegistry remains the only tool execution authority.
- Memory writes always go through Memory governance.
- High cohesion modules, low coupling boundaries, no new monolith.
- Legacy `agent/skills/` prototype is evidence, not design authority.
- SubAgent remains deferred.

## 2. Proposed Module Design

Do not create these files until the implementation loop reaches their phase.

### Legacy/Formal Module Coexistence Strategy

Existing `agent/skills/` is a frozen legacy / experimental prototype. The formal
Skill System cannot silently reuse legacy `registry.py`, `loader.py`, or
`installer.py` as stable API, because those files already carry prototype
semantics such as module-level registry state and experimental installer
behavior.

Before implementation, the formal module namespace must be chosen explicitly.
Accepted options:

- A. Rename legacy files to `_legacy_*` before formal implementation.
- B. Create formal modules under `agent/skill_system/`.
- C. Keep `agent/skills/` as the formal namespace but first migrate legacy
  modules to a legacy subpackage.

Recommended option: B, create formal modules under `agent/skill_system/`.

Rationale:

- Avoids confusion with frozen legacy `agent/skills/`.
- Does not require moving legacy files before the first implementation phase.
- Allows a later migration phase to decide whether to replace, archive, or
  remove the old prototype.
- Makes it harder for implementation agents to accidentally import frozen
  prototype modules as formal design.

This is a docs-only design decision. No production code changes are made by this
document. `agent/skills/` remains frozen and reference-only until an explicitly
approved migration phase.

```text
agent/skill_system/descriptor.py
agent/skill_system/schema.py
agent/skill_system/registry.py
agent/skill_system/loader.py
agent/skill_system/selector.py
agent/skill_system/context.py
agent/skill_system/invocation.py
agent/skill_system/result.py
agent/skill_system/prompt_section.py
agent/skill_system/checkpoint.py
agent/skill_system/errors.py
```

Responsibilities:

- `descriptor.py`: immutable public metadata projection for discovered Skills.
- `schema.py`: `SKILL.md` frontmatter schema validation and normalization.
- `registry.py`: runtime/session-scoped registry over filesystem roots.
- `loader.py`: body and resource loading with progressive disclosure.
- `selector.py`: deterministic selection decisions from metadata and task
  context.
- `context.py`: `SkillContext` assembly; no tool execution.
- `invocation.py`: request/result adapter; no loop ownership.
- `result.py`: structured Skill output and audit projection.
- `prompt_section.py`: Level 1 prompt section from descriptors only.
- `checkpoint.py`: Skill checkpoint correlation projection; it does not own
  global checkpoint save/load timing.
- `errors.py`: typed errors for parser, registry, loader, selector, and
  invocation boundaries.

## 3. Data Structures

### SkillDescriptor

Immutable Level 1 metadata:

- `name: str`
- `description: str`
- `version: str`
- `status: Literal["draft", "active", "deprecated", "disabled", "legacy"]`
- `risk_level: Literal["low", "medium", "high"]`
- `tags: tuple[str, ...]`
- `allowed_tools: tuple[str, ...]`
- `memory_scope: Literal["none", "read_context", "propose_memory"]`
- `root: Path`
- `manifest_path: Path`

### SkillManifest

Validated frontmatter:

- all SkillDescriptor fields
- `confirmation_policy: Literal["inherit_tool_policy"]`
- `owner: str`
- `resources: SkillResourceManifest`
- `raw_frontmatter: Mapping[str, object]` for audit only, redacted

### SkillContext

Runtime-prepared invocation context:

- selected `SkillDescriptor`
- loaded `SKILL.md` body
- task/user goal summary
- requested memory context, if approved
- allowed resource handles
- tool upper-bound declaration
- audit id
- checkpoint correlation id

### SkillInvocationRequest

Input to invocation adapter:

- `skill_name`
- `user_goal`
- `selection_reason`
- `requested_resources`
- `runtime_policy`
- `memory_context_policy`
- `tool_policy_snapshot`

### SkillInvocationResult

Output from invocation adapter:

- `ok: bool`
- `visible_output: str`
- `requested_tool_names: tuple[str, ...]`
- `requested_resources: tuple[str, ...]`
- `memory_proposals: tuple[object, ...]`
- `audit_record: SkillAuditRecord`
- `errors: tuple[SkillLoadError, ...]`

### SkillSelectionDecision

Selector output:

- `selected: bool`
- `skill_name: str | None`
- `confidence: float`
- `reason: str`
- `alternatives: tuple[str, ...]`
- `requires_user_confirmation: bool`

### SkillLoadError

Typed fail-closed error:

- `code`
- `message`
- `path`
- `recoverable`
- `safe_preview`

### SkillAuditRecord

Redacted audit data:

- `audit_id`
- `skill_name`
- `skill_version`
- `selection_reason`
- `loaded_levels`
- `loaded_resources`
- `requested_tools`
- `blocked_tools`
- `memory_scope`
- `result_status`
- `safe_preview`

## 4. Registry Design

Formal registry must be runtime/session scoped. It must not use a module-level
global singleton as the stable design.

Requirements:

- Construct registry with explicit roots and runtime policy.
- Filesystem scan order is deterministic.
- Invalid Skill manifests fail closed.
- Duplicate Skill names fail closed for the registry.
- Disabled/hidden Skills are not model-visible.
- Deprecated/legacy Skills can be shown only if policy explicitly allows.
- Registry exposes descriptors, not loaded bodies.
- Registry has explicit reset/reload for tests.
- Registry never reads real private Skill dirs unless caller passes them.

## 5. Loader And Progressive Disclosure

The loader owns body/resource loading:

- Metadata parsing only reads `SKILL.md` frontmatter.
- Body loading reads `SKILL.md` body after selection.
- Resource loading reads package-relative paths on demand.
- Paths cannot escape the Skill root.
- No `.env`, real `sessions/`, real `runs/`, or `agent_log.jsonl` reads.
- Binary or huge files require explicit resource policy before loading.

## 6. Tool Binding

`allowed_tools` is an upper bound, not authorization.

- ToolRegistry risk/capability filtering still applies.
- Skill can request tools by name.
- Skill cannot directly execute tools.
- `core` / `tool_executor` remain the only execution path.
- If Skill requests a tool outside `allowed_tools`, fail closed or ask user
  depending on runtime policy.
- If ToolRegistry marks a tool high risk, confirmation remains required.
- Install/update Skill tools are not in default registration.

## 7. Memory Integration

- Skill does not directly write Memory.
- Skill can declare `memory_scope`.
- Runtime provides approved memory context through an adapter.
- Skill output that should become memory is a proposal, not a write.
- Memory proposals enter existing Memory governance.
- No silent procedural retention.
- No auto approval.

## 8. Runtime Integration

- Skill does not own the loop.
- Agent loop does orchestration only.
- Skill invocation is adapter request/result flow.
- `agent/skill_system/checkpoint.py` may project SkillInvocationRequest /
  SkillInvocationResult correlation metadata for the existing checkpoint owner,
  but it must not write checkpoints directly or store full Skill bodies /
  resources.
- Runtime records selected Skill, loaded level, and audit id in checkpoint when
  invocation is in-flight.
- Resume should recover enough to explain the pending Skill action, not rerun
  hidden side effects.
- SkillResult is consumed by existing response/tool/memory boundaries.

## 9. CLI/TUI Presentation

CLI/TUI may display:

- available Skill descriptors
- selected Skill and reason
- loading state
- blocked/required confirmation state
- SkillResult preview
- audit id

CLI/TUI must not:

- implement selection logic
- load Skill bodies
- execute tools
- write Memory
- read private runtime artifacts

## 10. Security

- No default network install.
- No `.env` read.
- No real `sessions/` or `runs/` read.
- No secret logging.
- High-risk Skill actions require confirmation.
- Skill output and audit previews are redacted.
- Resource paths are package-relative and normalized.
- Fail closed on invalid schema, duplicate names, unsafe paths, hidden Skills,
  or unclear tool risk.

## 11. Migration From Legacy Prototype

Migration should happen only after tests are written:

1. Keep legacy package frozen.
2. Add new schema tests.
3. Replace module-level singleton design with runtime/session-scoped registry.
4. Reuse safe parser ideas only when they pass new schema contracts.
5. Keep installer outside default tools until a separate install RFC exists.

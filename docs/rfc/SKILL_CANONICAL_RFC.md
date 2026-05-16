# Skill Canonical RFC

Status: Draft canonical design for the formal Skill System.

This RFC supersedes the frozen `agent/skills/` prototype as the source of truth
for future Skill work. It is written for a Coding Agent implementation loop:
tests and code should trace back to the contracts below.

## 1. Goal

A Skill is a filesystem-first capability package. It encapsulates reusable
instructions, constraints, examples, allowed tool declarations, optional
resources, tests, and dogfood scenarios for a repeated class of work.

The formal Skill System should let the parent Agent discover available Skills,
show only lightweight metadata by default, load details only when selected, and
invoke a Skill through a request/result adapter while preserving existing
Runtime, ToolRegistry, Memory, checkpoint, confirmation, and audit boundaries.

## 2. Non-goals

- Skill is not SubAgent.
- Skill does not own the Agent loop.
- Skill does not bypass ToolRegistry.
- Skill does not directly write Memory.
- Skill does not default to real network install.
- Skill does not implement DB, graph, embedding, or vector store storage.
- Skill does not replace Tool.
- Skill does not replace Memory.
- Skill does not replace Runtime.
- Skill does not introduce a second provider call path or hidden LLM.
- Skill does not read `.env`, real `agent_log.jsonl`, real `sessions/`, or real
  `runs/`.

## 3. Relationship To Other Systems

### Skill vs Tool

Tools are executable capability endpoints registered through ToolRegistry.
Skills are instruction/resource packages that may declare an upper bound of
tools they are designed to use. `allowed_tools` is not authorization. The
ToolRegistry remains the authority for capability, risk, confirmation, and
execution.

### Skill vs Memory

Memory stores governed cross-session facts and preferences. Skill content is
static filesystem package content. A Skill can declare `memory_scope` and ask
Runtime for approved memory context through an adapter. A Skill cannot write
Memory directly; any candidate memory from Skill output must enter the existing
Memory governance path.

### Skill vs Runtime

Runtime owns the Agent loop, status transitions, checkpoint/resume, model calls,
and tool execution orchestration. Skill invocation is a request/result flow
inside Runtime; it cannot start its own loop, mutate Runtime state directly, or
own checkpoint timing.

### Skill vs Ask User / Confirmation

Skills can request actions that may require user confirmation. Confirmation is
still decided by ToolRegistry/runtime policy. A Skill cannot downgrade a high
risk tool, auto-approve a prompt, or silently continue when a confirmation gate
is required.

### Skill vs CLI/TUI

CLI/TUI display available Skills, selected Skill metadata, load status, audit
summary, and result previews. CLI/TUI do not implement Skill selection,
loading, invocation, tool execution, or Memory writes.

### Skill vs SubAgent

SubAgent is deferred. A SubAgent would be another agent execution context with
its own delegation boundary. A Skill is a package loaded into the parent
Runtime. Skill cannot spawn another loop or claim SubAgent semantics.

### Skill vs legacy `agent/skills` prototype

The existing `agent/skills/` package is frozen legacy / experimental prototype
code. It may be used as evidence for migration risks, but formal Skill System
behavior is governed by this RFC. The legacy module-level registry singleton is
not the formal design.

## 4. Filesystem-first Skill Structure

Canonical structure:

```text
skills/<skill_name>/
  SKILL.md
  references/
  scripts/
  templates/
  tests/
  dogfood/
```

`SKILL.md` contains YAML frontmatter and a markdown body. The frontmatter is the
manifest used for metadata discovery; the body is loaded only when the Skill is
selected.

Minimum frontmatter:

```yaml
name: safe-writer
description: Write concise safe local documentation.
version: 0.1.0
status: draft
allowed_tools:
  - read_file
  - write_file
risk_level: low
confirmation_policy: inherit_tool_policy
owner: local
tags:
  - writing
  - docs
memory_scope: none
resources:
  references: []
  scripts: []
  templates: []
  tests: []
  dogfood: []
```

Field contracts:

- `name`: stable filesystem-safe identifier, unique within the active registry.
- `description`: one or two sentences suitable for always-visible metadata.
- `version`: semantic package version.
- `status`: `draft`, `active`, `deprecated`, `disabled`, or `legacy`.
- `allowed_tools`: declared upper bound of intended tools.
- `risk_level`: `low`, `medium`, or `high`; cannot lower tool risk.
- `confirmation_policy`: `inherit_tool_policy` unless a later RFC approves
  stricter behavior.
- `owner`: local owner or package maintainer label, not an auth boundary.
- `tags`: selector hints.
- `memory_scope`: `none`, `read_context`, or `propose_memory`.
- `resources`: declared relative resources.

## 5. Progressive Disclosure

The Skill System must not inject all Skill bodies into the prompt.

- Level 1: metadata (`name`, `description`, `status`, tags, risk summary) is
  always visible when Skills are enabled.
- Level 2: `SKILL.md` body is loaded only when a Skill is selected.
- Level 3: `references/`, `scripts/`, `templates/`, `tests/`, and `dogfood/`
  are loaded only on demand by an explicit SkillContext request.

Level 3 resources must be path-checked, package-relative, deterministic, and
auditable. A selected Skill can request a resource; it cannot force the Runtime
to load all resources preemptively.

## 6. Lifecycle

Formal lifecycle:

1. `discover`: scan configured filesystem roots deterministically.
2. `load metadata`: parse and validate frontmatter only.
3. `select`: choose a Skill by explicit user instruction or deterministic
   selector evidence.
4. `load body`: load `SKILL.md` body after selection.
5. `prepare SkillContext`: attach task goal, selected metadata, body, allowed
   resource handles, tool upper-bound, memory context allowance, and audit id.
6. `invoke`: parent Runtime asks the Skill adapter to prepare instructions or
   produce a bounded plan/result.
7. `produce SkillResult`: structured result with visible output, requested
   resources, tool requests, memory proposals, and audit metadata.
8. `audit`: record selected Skill, loaded resources, requested tools, decisions,
   and redacted previews.
9. `dogfood`: run synthetic local scenarios before broader activation.
10. `version / deprecate`: status transitions are explicit and documented.

## 7. Governance

- High-risk tools still require confirmation.
- Skill cannot lower tool risk or confirmation policy.
- Skill cannot bypass ToolRegistry.
- Skill cannot directly write Memory.
- Skill can request memory context only through an approved Runtime adapter.
- Skill output must be auditable and redacted before logs.
- `install_skill` and `update_skill` are not default tools.
- Network install is disabled by default and requires explicit opt-in and
  confirmation.
- Invalid Skills fail closed.
- Hidden or disabled Skills are not model-visible.
- Secret-like content in manifests, body, resources, and output must be
  redacted from display/audit.

## 8. Legacy Prototype Policy

- Existing `agent/skills` is frozen legacy / experimental prototype code.
- Formal Skill System is governed by this RFC.
- Old prototype code may be migrated or replaced after RFC implementation
  starts with tests.
- The legacy registry module-level singleton is not the formal design.
- Legacy installer network behavior remains out of the default tool path.
- New implementation must avoid broad monolith growth; modules should stay
  high cohesion and low coupling.

## 9. Acceptance Criteria

- Metadata discovery works without loading all bodies.
- Selected Skill body loads only after selection.
- Level 3 resources load only on explicit request.
- ToolRegistry remains the execution authority.
- Memory governance remains unchanged.
- Runtime loop remains parent-owned.
- CLI/TUI are presentation only.
- Checkpoint/resume can explain any in-flight Skill invocation.
- Full test plan in `docs/testing/SKILL_SYSTEM_TDD.md` passes phase by phase.

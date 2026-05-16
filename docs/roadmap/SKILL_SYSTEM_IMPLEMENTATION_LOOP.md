# Skill System Implementation Loop

This document is the execution loop for a future Coding Agent. Do not implement
Skill System code without reading the RFC, SDD, and TDD first.

## 1. Loop Rules

Every phase must:

1. Read `docs/rfc/SKILL_CANONICAL_RFC.md`.
2. Read `docs/design/SKILL_SYSTEM_SDD.md`.
3. Read `docs/testing/SKILL_SYSTEM_TDD.md`.
4. Write or extend tests first.
5. Confirm the new test fails for the intended reason when practical.
6. Implement minimum code.
7. Run selected tests.
8. Run full pytest when code touches runtime/tool/memory/core/checkpoint/CLI/TUI.
9. Update docs if behavior or phase status changes.
10. Commit a scoped change.
11. Stop for audit at defined gates.

Do not modify real `.env`, read real `agent_log.jsonl`, read real `sessions/` or
`runs/`, call real LLMs, clone remote Skills, or install dependencies.

Formal Skill implementation must not modify frozen legacy `agent/skills/` files
unless a dedicated migration phase is explicitly approved. Frozen legacy files
include but are not limited to:

- `agent/skills/__init__.py`
- `agent/skills/registry.py`
- `agent/skills/installer.py`
- `agent/skills/loader.py`
- `agent/skills/local.py`
- `agent/skills/parser.py`
- `agent/skills/safety.py`

The formal namespace is `agent/skill_system/`. Implementation phases should
create or modify `agent/skill_system/*`, and tests should target
`agent/skill_system/*`. Legacy `agent/skills/*` remains reference-only until a
migration phase.

## 2. Phases

### Phase 0: Legacy Prototype Freeze Verification

Goal: prove `agent/skills/` remains legacy/experimental and inactive by default.

Work:

- Verify `agent.skills.__all__ == []`.
- Verify default `agent.tools` import excludes Skill lifecycle tools.
- Verify install/update tools remain explicit opt-in.

Stop gate: audit confirms no legacy prototype contamination.

### Phase 1: Descriptor Schema

Goal: define parser/schema for `SKILL.md` frontmatter.

Allowed files: `agent/skill_system/schema.py`,
`agent/skill_system/descriptor.py`, `agent/skill_system/errors.py`, and focused
tests/docs for this phase.

Forbidden files: frozen `agent/skills/*`, Runtime loop, ToolRegistry, Memory,
CLI/TUI.

Work:

- Add `SkillManifest`, `SkillDescriptor`, typed errors.
- Fail closed on invalid names/status/risk/resources.
- Redact secret-like values.

Stop gate: schema tests green.

### Phase 2: Filesystem Registry

Goal: runtime/session-scoped deterministic registry.

Allowed files: `agent/skill_system/registry.py`,
`agent/skill_system/descriptor.py`, `agent/skill_system/errors.py`, fixtures,
and focused tests/docs.

Forbidden files: frozen `agent/skills/*`, Runtime loop, ToolRegistry execution,
Memory governance.

Work:

- Explicit roots only.
- No module-level global singleton.
- Duplicate names fail closed.
- Disabled/hidden Skills not visible.

Stop gate: independent review of registry scope.

### Phase 3: Loader + Progressive Disclosure

Goal: Level 1/2/3 loading contracts.

Allowed files: `agent/skill_system/loader.py`,
`agent/skill_system/prompt_section.py`, `agent/skill_system/errors.py`,
fixtures, and focused tests/docs.

Forbidden files: frozen `agent/skills/*`, ToolRegistry execution, Memory
governance, checkpoint schema.

Work:

- Metadata prompt section.
- Selected body loading.
- On-demand resource loading.
- Audit loaded levels.

Stop gate: prompt inspection confirms no all-body injection.

### Phase 4: Selector

Goal: deterministic Skill selection.

Allowed files: `agent/skill_system/selector.py`,
`agent/skill_system/descriptor.py`, and focused tests/docs.

Forbidden files: frozen `agent/skills/*`, provider/LLM adapters, Runtime loop,
SubAgent code.

Work:

- Explicit selection support.
- Metadata-only matching.
- Ambiguous match asks user.
- Disabled/deprecated policy.

Stop gate: selector never reads bodies or calls LLM.

### Phase 5: Tool Binding

Goal: connect Skill allowed tools to ToolRegistry without bypass.

Allowed files: `agent/skill_system/context.py`,
`agent/skill_system/invocation.py`, tool-binding tests/docs, and narrow adapter
code if required by the phase plan.

Forbidden files: frozen `agent/skills/*`, ToolRegistry risk bypasses, direct
tool execution from Skill modules.

Work:

- Treat `allowed_tools` as upper-bound.
- Preserve ToolRegistry risk/capability filtering.
- Preserve confirmation.
- Block unknown/out-of-scope tool requests.

Stop gate: tool boundary audit.

### Phase 6: Runtime Invocation Adapter

Goal: request/result invocation flow under parent Runtime.

Allowed files: `agent/skill_system/context.py`,
`agent/skill_system/invocation.py`, `agent/skill_system/result.py`, Runtime
adapter seams approved by tests, and focused tests/docs.

Forbidden files: frozen `agent/skills/*`, SubAgent modules, provider direct call
paths, Memory governance changes.

Work:

- Add SkillInvocationRequest/Result.
- Add SkillContext assembly.
- Add audit record.
- Ensure no Skill-owned loop.

Stop gate: full pytest with temp HOME.

### Phase 7: Memory Context Boundary

Goal: approved memory read/proposal boundary.

Allowed files: `agent/skill_system/context.py`,
`agent/skill_system/invocation.py`, memory adapter seam tests/docs, and the
minimum approved Runtime adapter wiring.

Forbidden files: frozen `agent/skills/*`, Memory governance bypasses, direct
Memory store writes from Skill modules.

Work:

- Implement `memory_scope` handling.
- Provide context through adapter.
- Route memory proposals through governance.

Stop gate: Memory governance audit.

### Phase 7b: Checkpoint/Resume Boundary

Goal: make in-flight Skill invocation checkpoint-aware without letting Skill own
the loop or replay high-risk effects.

Entry criteria:

- Phase 6 invocation request/result flow exists.
- Phase 7 memory boundary tests pass.
- Existing checkpoint ownership tests are green.

Allowed files:

- `agent/skill_system/checkpoint.py`
- `agent/skill_system/invocation.py`
- `agent/skill_system/result.py`
- focused checkpoint/resume tests
- narrowly scoped Runtime checkpoint adapter code only if tests require it

Forbidden files:

- frozen `agent/skills/*`
- SubAgent modules
- ToolRegistry risk/confirmation policy
- Memory governance
- broad checkpoint schema migration without user approval

Tests first:

- Add tests for checkpoint correlation between SkillInvocationRequest and
  SkillInvocationResult.
- Add tests for interrupted in-flight invocation restore/explain behavior.
- Add tests that checkpoint does not store secrets or complete large resource
  content.
- Add tests that resume does not bypass confirmation or re-execute high-risk
  tools.

Implementation scope:

- Store only bounded correlation metadata: selected Skill, version, loaded
  levels, audit id, resource handles, and pending confirmation state.
- Do not persist full Skill body or resource contents.
- Do not replay tool execution from Skill state.
- Runtime remains the only owner of loop and checkpoint save/load timing.

Selected tests:

```bash
python -m pytest tests/test_skill_checkpoint_resume.py tests/test_checkpoint_ownership.py -q
python -m pytest tests/test_architecture_boundaries.py -q
```

Exit criteria:

- In-flight Skill invocation can be recovered or explained after resume.
- Checkpoint contains no secret-like values and no full large resources.
- Interrupted invocation cannot bypass confirmation.
- Resume does not repeat high-risk tool execution.
- Runtime owns the loop; Skill does not own a loop.
- Full pytest passes with a temporary HOME.

### Phase 8: CLI/TUI Visibility

Goal: presentation only.

Work:

- Show available descriptors.
- Show selected Skill/reason.
- Show result/audit id.

Stop gate: TUI dependency boundary tests.

### Phase 9: Dogfood Harness

Goal: synthetic local dogfood scenarios.

Work:

- Add fixtures for scenarios in dogfood plan.
- Produce redacted audit packets.
- No network, real LLM, `.env`, sessions/runs.

Stop gate: dogfood packet review.

### Phase 10: Independent Audit And Hardening

Goal: close P0/P1/P2 and decide readiness.

Work:

- Run audit checklist.
- Fix scoped findings.
- Run full pytest.
- Prepare push/PR only after user approval.

Stop gate: user decides next action.

## 3. Stop Conditions

Stop and ask the user if any phase:

- wants network install
- wants a real Skill from GitHub
- touches `.env`
- reads real `agent_log.jsonl`
- reads real `sessions/` or `runs/`
- changes Memory governance
- introduces SubAgent
- introduces backend abstraction, DB, graph, embedding, or vector store
- checkpoint/resume would require changing existing checkpoint schema
- implementation would give Skill its own loop
- implementation would write full Skill bodies or resources into checkpoint
- has unclear tool risk boundary
- needs to weaken/skip tests
- full pytest fails
- requires push or tag

## 4. Commit Shape

Use scoped commits per phase. Include:

- phase id
- behavior protected
- tests run
- explicit statement that Skill remains parent-runtime controlled

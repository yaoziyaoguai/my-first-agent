# Skill System TDD Plan

Every phase starts by reading:

- `docs/rfc/SKILL_CANONICAL_RFC.md`
- `docs/design/SKILL_SYSTEM_SDD.md`
- this TDD document

The implementation loop writes or extends tests first, verifies red where
appropriate, then implements the smallest behavior slice.

## Phase 0: Freeze Legacy Skill Prototype Tests

- Tests to add: package public API freeze, legacy/experimental markers,
  default tool registration excludes Skill lifecycle tools.
- Expected behavior: `agent.skills.__all__ == []`; existing prototype is visible
  but inactive.
- Forbidden behavior: default import of `agent.tools` registers install/load/update
  Skill lifecycle tools.
- Selected command: `python -m pytest tests/test_skill_local_mvp_contract.py tests/test_skill_system_honesty.py -q`
- Exit criteria: freeze tests pass and no runtime behavior changes.

## Phase 1: SKILL.md Parser / Schema Tests

- Tests to add: valid manifest, missing fields, invalid names, invalid status,
  invalid risk, unsafe resources, secret-like values redacted.
- Expected behavior: valid frontmatter becomes `SkillManifest`.
- Forbidden behavior: partial invalid manifests becoming model-visible.
- Selected command: `python -m pytest tests/test_skill_schema.py -q`
- Exit criteria: invalid manifests fail closed with typed errors.

## Phase 2: Filesystem Registry Tests

- Tests to add: deterministic scan, duplicate names fail closed, disabled/hidden
  not visible, runtime/session scoped construction, explicit roots only.
- Expected behavior: registry returns descriptors only.
- Forbidden behavior: module-level global singleton as formal registry.
- Selected command: `python -m pytest tests/test_skill_registry.py -q`
- Exit criteria: registry can be isolated per test/session.

## Phase 3: Progressive Disclosure Tests

- Tests to add: Level 1 prompt contains metadata only; body loads after
  selection; references/scripts/templates load only on request.
- Expected behavior: prompt section never contains all Skill bodies.
- Forbidden behavior: selector or registry reads all bodies preemptively.
- Selected command: `python -m pytest tests/test_skill_progressive_disclosure.py -q`
- Exit criteria: loaded levels are observable in audit records.

## Phase 4: Selector Tests

- Tests to add: explicit user-selected Skill, no match, ambiguous match asks
  user, disabled Skill ignored, deprecated Skill policy.
- Expected behavior: selector returns `SkillSelectionDecision`.
- Forbidden behavior: selector calls LLM, reads bodies, or uses hidden Skills.
- Selected command: `python -m pytest tests/test_skill_selector.py -q`
- Exit criteria: selector is deterministic and metadata-only.

## Phase 5: Tool Binding / Risk Boundary Tests

- Tests to add: `allowed_tools` upper-bound, ToolRegistry risk still applies,
  high-risk confirmation preserved, unknown tools blocked.
- Expected behavior: Skill can request tools but cannot execute them.
- Forbidden behavior: Skill bypasses ToolRegistry or downgrades risk.
- Selected command: `python -m pytest tests/test_skill_tool_binding.py tests/test_tool_exposure.py -q`
- Exit criteria: all execution still flows through `tool_executor`.

## Phase 6: Runtime Invocation Adapter Tests

- Tests to add: SkillInvocationRequest to SkillInvocationResult, audit id,
  error handling, no loop ownership, no direct state mutation.
- Expected behavior: parent Runtime orchestrates request/result.
- Forbidden behavior: Skill starts another loop or calls provider directly.
- Selected command: `python -m pytest tests/test_skill_invocation.py tests/test_architecture_boundaries.py -q`
- Exit criteria: architecture tests show Runtime remains owner.

## Phase 7: Memory Boundary Tests

- Tests to add: `memory_scope=none`, approved read context, memory proposal,
  rejection paths.
- Expected behavior: Skill receives context only through adapter.
- Forbidden behavior: direct Memory write, silent retain, auto approval.
- Selected command: `python -m pytest tests/test_skill_memory_boundary.py tests/test_memory_guardrails.py -q`
- Exit criteria: Memory governance tests still pass unchanged.

## Phase 8: Checkpoint/Resume Tests

- Tests to add: in-flight Skill invocation checkpoint, loaded level recorded,
  resume does not replay side effects, blocked invocation explainable.
- Expected behavior: checkpoint stores audit/correlation metadata, not huge body
  dumps or secrets.
- Forbidden behavior: hidden rerun of Skill side effects on resume.
- Selected command: `python -m pytest tests/test_skill_checkpoint_resume.py tests/test_checkpoint_ownership.py -q`
- Exit criteria: resume preserves user-visible state and safety.

## Phase 9: CLI/TUI Presentation Tests

- Tests to add: available Skills list, selected Skill display, blocked action
  display, audit id display.
- Expected behavior: CLI/TUI present state only.
- Forbidden behavior: CLI/TUI imports Skill loader/runtime logic.
- Selected command: `python -m pytest tests/test_skill_cli_tui.py tests/test_tui_dependency_boundaries.py -q`
- Exit criteria: presentation boundaries remain thin.

## Phase 10: Dogfood Tests

- Tests to add: synthetic dogfood fixtures for each scenario in
  `docs/dogfood/SKILL_SYSTEM_DOGFOOD_PLAN.md`.
- Expected behavior: local-only deterministic runs.
- Forbidden behavior: network, `.env`, real sessions/runs, real LLM.
- Selected command: `python -m pytest tests/test_skill_dogfood.py -q`
- Exit criteria: dogfood produces audit packets with no private data.

## Phase 11: Architecture Boundary Tests

- Tests to add: no ToolRegistry bypass, no Memory direct write, no second loop,
  no CLI/TUI runtime logic, no SubAgent imports.
- Expected behavior: high cohesion / low coupling module graph.
- Forbidden behavior: new Skill monolith or cross-layer imports.
- Selected command: `python -m pytest tests/test_architecture_boundaries.py tests/test_skill_architecture_boundaries.py -q`
- Exit criteria: full suite passes and no P0/P1 audit findings remain.

## Full-suite Rule

Run full pytest when a phase touches Runtime, ToolRegistry, Memory,
checkpoint/resume, core loop, CLI/TUI, or architecture boundary tests:

```bash
HOME=/private/tmp/my-first-agent-skill-system-home python -m pytest tests/ -x -q
```

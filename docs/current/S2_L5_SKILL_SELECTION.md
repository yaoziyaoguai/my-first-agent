# S2 L5 Skill Selection

S2-G08 decision: the first selectively-active L5 capability is **Skill**.

This file is the routing input for S2-G09. It is not the activation
implementation.

## Selection Rationale

Skill is selected because the user resolved S2-G01/OD-2 in favor of Skill and
because its current implementation has a narrower activation surface than
MCP/SubAgent/Scheduler:

- `SkillRegistry` discovers explicit `SKILL.md` roots and stores descriptors,
  not raw bodies or executable resources.
- `SkillSelector` is deterministic and metadata-only: name, description, tags,
  triggers, aliases, and negative triggers.
- Disabled and legacy skills are excluded from selection.
- `SkillLoader` / progressive disclosure load body content only after a skill is
  selected.
- `ActiveSkillLifecycle` has explicit activate, switch, deactivate, checkpoint
  metadata, restore, and task-boundary cleanup seams.
- `SKILL_SELECT` already exists as a model-visible tool entry, which means S2-G09
  can focus on governing the existing path instead of inventing a second runtime
  route.

## Same-Spine Integration Plan For S2-G09

S2-G09 must keep Skill on the S1 runtime spine:

1. **Entry**: Skill activation enters through the standard tool path, not through
   a side-channel command or direct model prompt mutation.
2. **Gate**: add an explicit S2 enable/disable boundary. When disabled, the
   runtime behaves like S1 and active skill state is cleared at task boundaries.
3. **Policy**: selection can only target visible, valid skills. Disabled,
   legacy, unknown, malformed, or unsafe skill IDs fail closed.
4. **Evidence**: record safe metadata for selection, activation, deactivation,
   task-boundary cleanup, and restore. Do not persist raw `SKILL.md` body as
   task evidence.
5. **Checkpoint/Resume**: checkpoint stores skill metadata only. Resume reloads
   current body/allowed tools from registry/loader and clears stale state on
   invalid metadata.
6. **Tool Scope**: active skill allowed-tools constraints must flow into the same
   governed tool visibility/execution path used by ordinary task tools.
7. **Rollback**: disabling the S2 Skill gate and deactivating the lifecycle must
   restore S1 behavior without deleting Skill code or historical evidence.

## Current Evidence

- Registry/selector: `agent/skill_system/registry.py`,
  `agent/skill_system/selector.py`, `tests/test_skill_registry.py`,
  `tests/test_skill_selector.py`.
- Progressive disclosure/body loading:
  `tests/test_skill_progressive_disclosure.py`.
- Lifecycle/checkpoint/task boundary: `agent/skill_system/lifecycle.py`,
  `agent/skill_system/task_boundary.py`,
  `agent/runtime_integration/skill_lifecycle.py`,
  `tests/unit/test_active_skill_lifecycle.py`.
- Tool entry: `agent/skill_system/skill_tool.py`,
  `tests/unit/test_skill_select_tool.py`,
  `tests/test_tool_registry_contract.py`.

## Deferred L5 Candidates

MCP, SubAgent, and Scheduler remain out of the first S2 selectively-active path:

- MCP remains configurable/default-off and must not be broadened while Skill is
  the selected S2 candidate.
- SubAgent remains a future candidate despite stronger parent-mediated wiring;
  it is not the user-selected first S2 L5.
- Scheduler remains dormant for S2-G08/S2-G09 and must not become the hidden task
  orchestrator for Skill activation.

## Acceptance For S2-G09

S2-G09 should be accepted only when:

- Skill activation is default-off or explicitly gated.
- Enabling Skill goes through the governed task/tool path.
- Disabling Skill restores S1 behavior.
- Evidence is safe and reviewable without raw secrets or raw skill body dumps.
- Checkpoint/resume handles active skill metadata without stale or unsafe state.
- MCP/SubAgent/Scheduler remain unactivated by the Skill integration.

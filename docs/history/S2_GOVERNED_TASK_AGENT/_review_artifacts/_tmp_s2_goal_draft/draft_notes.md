# S2 Goal Draft — Intermediate Notes

> Intermediate notes under `_tmp_s2_goal_draft/`. Not authoritative. The
> authoritative goal is `docs/current/S2_GOAL.md`.

## Skills used and where

- **superpowers**: goal decomposition into 0-10 sections; acceptance-criteria
  completeness check (8 ACs minimum); verification-before-completion self-check
  before commit.
- **compound-engineering**: S2 product positioning vs S1 baseline vs S3 boundary;
  baseline/goal/gap boundary discipline (do not pre-generate gaps); TECH_DEBT
  relation framing (debt ≠ goal).
- **g-stack / graphify**: verified L4 task-orchestration nodes (TaskState,
  mark_step_complete, advance_current_step_if_needed) and L5 dormant/
  selectively-active feasibility — confirmed L1 SubAgent already has a
  parent-mediated path (`subagent_system/{executor,delegation,context,registry,
  request}.py` + `test_subagent_l1_parent_mediated.py`), making SubAgent a
  natural selectively-active L5 candidate that does not break same-spine.
- **safety/secret**: kept real provider / config boundary as description only;
  no secret read/printed/copied/moved/committed.

## Key positioning decisions (grounded in user-confirmed direction + baseline)

- S2 = **Governed Task Agent / 受控任务型 Agent**. Big version, not S1 cleanup.
- The one-line framing: S1 answered "can the agent run as a baseline usable
  product?"; S2 answers "can the agent reliably execute governed multi-step
  work?".
- Main battlefields: L2/L3/L4 coordination + L5 selectively-active (one
  capability, governed path).
- L5 candidate preference (evidence-based, not decided): SubAgent L1
  parent-mediated path is the most wiring-ready; MCP is configurable default-off;
  Skill experimental; Scheduler dormant. Final choice is an Open Decision (§9).

## What the draft deliberately avoids

- No gap generation (S2_GOAL_GAP.md stays skeleton).
- No reference-task selection (Open Decision §9-1).
- No L5 capability selection (Open Decision §9-2).
- No full pytest/ruff全清零 as a product goal (Non-goal §6; debt relation §8).
- No S3 multi-agent ecosystem (Non-goal §6).

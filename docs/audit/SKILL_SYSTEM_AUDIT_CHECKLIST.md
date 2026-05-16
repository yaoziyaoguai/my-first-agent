# Skill System Audit Checklist

Use this checklist after each implementation phase and before any push/PR.

## P0 Findings

P0 means stop and fix before proceeding.

- Skill owns a second agent loop.
- Skill bypasses ToolRegistry.
- Skill directly writes Memory.
- Skill enables default network install.
- Skill exposes hidden or high-risk tools without ToolRegistry policy.
- Skill reads `.env`, real `agent_log.jsonl`, real `sessions/`, or real `runs/`.
- Skill logs secrets or unredacted private content.
- Skill triggers real LLM/provider calls outside parent Runtime.
- Skill introduces SubAgent behavior without explicit authorization.

## P1 Findings

P1 means block implementation until resolved.

- Formal registry uses a global module-level singleton.
- `SKILL.md` schema is unstable or under-specified.
- Progressive disclosure is not implemented.
- Selector loads all Skill bodies.
- Runtime invocation lacks checkpoint/resume boundary.
- Legacy prototype contaminates formal design.
- `allowed_tools` is treated as authorization instead of upper-bound.
- Memory proposals skip governance.
- CLI/TUI owns Skill runtime logic.

## P2 Findings

P2 should be fixed before declaring the phase complete.

- Dogfood incomplete or not synthetic.
- CLI/TUI display incomplete.
- Docs inconsistent across RFC/SDD/TDD/loop/dogfood.
- Public API unclear.
- Audit records missing selected Skill, loaded levels, or requested tools.
- Error taxonomy too broad for tests to assert.
- Deprecated/disabled Skill behavior unclear.

## P3 Findings

P3 can be queued unless it creates confusion.

- Few templates.
- Naming polish.
- More examples needed.
- More authoring guidance needed.
- Additional dogfood variations.
- Better wording around owner/status fields.

## Required Consistency Checks

- Skill is not SubAgent.
- SubAgent is deferred.
- Skill is filesystem-first.
- Progressive disclosure is required.
- Legacy `agent/skills` is frozen.
- No DB, graph, embedding, or vector store.
- No default network install.
- No direct Memory write.
- ToolRegistry remains authority.
- Parent Runtime owns loop and checkpoint/resume.

## Evidence Packet Template

Record:

- branch and ahead/behind
- files changed
- phase id
- tests run and exit codes
- full pytest result if required
- Skill loaded levels tested
- ToolRegistry boundary result
- Memory governance result
- dogfood result
- P0/P1/P2/P3 findings
- final verdict

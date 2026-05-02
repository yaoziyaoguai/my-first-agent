# Roadmap Completion Autopilot

本文件是本轮 Roadmap Completion Autopilot 的 release readiness closure。它记录
已经安全完成的 fake/local 工作、仍然 deferred 的真实外部集成，以及 release/tag 前
必须人工 review 的边界。

## Completion matrix

| Area | Status | Evidence | Remaining / deferred |
|---|---|---|---|
| MCP CLI Config Management | complete | parser/validator/redaction、CLI list/inspect/validate、plan preview、safe apply、backup、redacted diff、safety manifest | real MCP endpoint/resources/prompts/sampling/roots deferred |
| Coding-Agent Execution Governance | complete | `AGENTS.md` + `tests/test_agent_guidance_contract.py` | keep guidance updated after repeated mistakes |
| Skill System Safe Local MVP | complete | `agent.skills.local` + `docs/SKILL_LOCAL_MVP.md` + tests | real install/execution/marketplace deferred |
| Subagent System Safe Local MVP | complete | `agent.subagents.local` + `docs/SUBAGENT_LOCAL_MVP.md` + tests | real LLM/provider/process/remote delegation deferred |
| Skill/Subagent Integration Boundary | complete | `docs/CAPABILITY_BOUNDARIES.md` + tests | real activation deferred |
| Known XFAIL closure | complete | topic-switch explicit chooser + Textual generation projection cancel | real provider stream abort deferred |
| Release readiness | planning-ready | full pytest/ruff/diff gates passed in each pack | no tag; human review before release/tag |

## Packs completed

1. MCP Safe Apply + Governance
   - plan-first apply
   - explicit `--yes`
   - deterministic serialization
   - backup and redacted diff evidence
   - no real external integration

2. Coding-Agent Execution Governance
   - `AGENTS.md`
   - quality gates
   - evidence packet standard
   - push/tag policy

3. Skill System Safe Local MVP
   - local fixture descriptor
   - no network install
   - no arbitrary code execution
   - no real skill dirs

4. Subagent System Safe Local MVP
   - fake/local profile
   - structured delegation request/result
   - parent runtime remains in control
   - no real LLM/provider
   - no external process

5. Skill/Subagent Integration Boundary
   - Tool = atomic execution
   - Skill = local capability descriptor
   - Subagent = parent-controlled delegation
   - no policy bypass

6. Known XFAIL Closure
   - topic-switch now uses explicit `awaiting_feedback_intent` choice `[2]`
   - no slash command restoration
   - no keyword/LLM intent guessing
   - Textual Esc cancels the active Assistant projection
   - cancelled projection blocks later chunks and final completion overwrite
   - no Runtime state mutation from the TUI adapter

## Release readiness

The repository is ready for human review and release/tag preparation planning only.
This document is not a release authorization.

Safety non-goals:

- no tag
- no real external integration
- no real MCP endpoint
- no real Skill install/execution
- no real LLM subagent delegation
- no real provider call
- no memory activation
- no broad refactor
- real provider stream abort remains deferred unless separately designed

Before any release/tag:

- human review before release/tag
- verify clean `main`
- verify `origin/main...HEAD = 0 0`
- run `.venv/bin/ruff check .`
- run `.venv/bin/python -m pytest -q -rx`
- confirm `v0.8.0` remains unchanged unless a new explicit tag is authorized

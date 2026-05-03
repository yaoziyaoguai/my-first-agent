# Roadmap Completion Autopilot

本文件是本轮 Roadmap Completion Autopilot 的 release readiness closure。它记录
已经安全完成的 fake/local 工作、仍然 deferred 的真实外部集成，以及 release/tag 前
必须人工 review 的边界。

## Completion matrix

| Area | Status | Evidence | Remaining / deferred |
|---|---|---|---|
| MCP CLI Config Management | complete | parser/validator/redaction、CLI list/inspect/validate、plan preview、safe apply、backup、redacted diff、safety manifest、`tests/fixtures/mcp_config/safe-mcp.json`、`docs/MCP_CONFIG_MANAGEMENT.md` | real MCP endpoint/resources/prompts/sampling/roots deferred |
| Coding-Agent Execution Governance | complete | `AGENTS.md` + `tests/test_agent_guidance_contract.py` | keep guidance updated after repeated mistakes |
| Skill System Safe Local MVP | complete | `agent.skills.local` + `docs/SKILL_LOCAL_MVP.md` fake dogfood example + tests | real install/execution/marketplace deferred |
| Subagent System Safe Local MVP | complete | `agent.subagents.local` + `docs/SUBAGENT_LOCAL_MVP.md` fake dogfood example + tests | real LLM/provider/process/remote delegation deferred |
| Skill/Subagent Integration Boundary | complete | `docs/CAPABILITY_BOUNDARIES.md` + tests | real activation deferred |
| Known XFAIL closure | complete | topic-switch explicit chooser + Textual generation projection cancel | real provider stream abort deferred |
| Observability Local Trace Foundation | complete | `agent.local_trace` + `docs/LOCAL_TRACE_FOUNDATION.md` + local-only trace contract tests | full runtime trace wiring deferred |
| Structured ToolResult Envelope Foundation | complete | `ToolResultEnvelope` + `classify_tool_result` + `docs/TOOL_RESULT_ENVELOPE.md` + ToolResult contract tests | full executor/tool return migration deferred |
| Local Config Foundation | complete | `agent.local_config` + `tests/fixtures/local_config/agent.local.json` + `docs/LOCAL_CONFIG_FOUNDATION.md` + explicit safe-path config contract tests | real home config and installer/setup deferred |
| Roadmap Status Alignment Review | complete | P3 docs drift remediation confirms historical XFAIL backlog is closed | no production/runtime change |
| Deferred Roadmap Boundaries | complete | `docs/DEFERRED_ROADMAP_BOUNDARIES.md` records planning-only / deferred boundaries | no real external integration or broad migration |
| Safe-Local Release Readiness | complete | `docs/SAFE_LOCAL_RELEASE_READINESS.md` records manual smoke, known limitations, and no-tag checklist | release/tag still requires explicit authorization |
| Release/Tag Preparation | planning-ready | `docs/RELEASE_TAG_PREPARATION.md` records pre-tag verification commands, human authorization checklist, rollback plan, and `v0.8.0 unchanged` policy | no tag creation, release creation, or push tags |
| Release readiness | planning-ready | full pytest/ruff/diff gates passed in each pack | no tag; human review before release/tag |

## Packs completed

1. MCP Safe Apply + Governance
   - plan-first apply
   - explicit `--yes`
   - deterministic serialization
   - backup and redacted diff evidence
   - explicit safe fixture path: `tests/fixtures/mcp_config/safe-mcp.json`
   - review doc: `docs/MCP_CONFIG_MANAGEMENT.md`
   - no real external integration

2. Coding-Agent Execution Governance
   - `AGENTS.md`
   - quality gates
   - evidence packet standard
   - push/tag policy

3. Skill System Safe Local MVP
   - local fixture descriptor
   - fake dogfood example
   - no network install
   - no arbitrary code execution
   - no real skill dirs

4. Subagent System Safe Local MVP
   - fake/local profile
   - structured delegation request/result
   - fake dogfood example
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

7. Observability Local Trace Foundation
   - `agent.local_trace`
   - `docs/LOCAL_TRACE_FOUNDATION.md`
   - local-only trace file JSONL schema
   - run_id / trace_id / span_id / parent_span_id
   - model/tool/state/checkpoint span vocabulary
   - redacted metadata
   - no real `agent_log.jsonl` read
   - no real `sessions/runs` read
   - explicit tmp_path writer only

8. Structured ToolResult Envelope Foundation
   - `ToolResultEnvelope`
   - `classify_tool_result`
   - `docs/TOOL_RESULT_ENVELOPE.md`
   - status / display event / status text
   - error taxonomy
   - redacted bounded preview
   - legacy string contract 仍兼容
   - no broad executor migration
   - no checkpoint/messages protocol rewrite

9. Local Config Foundation
   - `agent.local_config`
   - `ProjectProfile`
   - `SafetyPolicy`
   - `ModuleToggles`
   - `ModelProviderConfig`
   - explicit tmp_path config parser
   - explicit safe fixture path: `tests/fixtures/local_config/agent.local.json`
   - review doc: `docs/LOCAL_CONFIG_FOUNDATION.md`
   - 不读取真实 home config
   - no `.env`
   - no env secret expansion
   - no provider/network call

10. Roadmap Status Alignment Review
   - P3 docs drift remediation
   - historical XFAIL backlog is closed
   - provider stream abort remains deferred as separate runtime lifecycle work
   - no production/runtime change
   - no TUI/runtime reopening

11. Deferred Roadmap Boundaries
   - `docs/DEFERRED_ROADMAP_BOUNDARIES.md`
   - real MCP external integration remains deferred
   - runtime trace wiring remains deferred
   - ToolResult executor migration remains deferred
   - real Skill/Subagent activation remains deferred
   - release/tag remains planning-only

12. Safe-Local Release Readiness
   - `docs/SAFE_LOCAL_RELEASE_READINESS.md`
   - manual smoke checklist
   - known limitations
   - no tag authorization
   - full pytest / ruff / diff-check quality gate checklist

13. Release/Tag Preparation
   - `docs/RELEASE_TAG_PREPARATION.md`
   - planning-only
   - pre-tag verification commands
   - human authorization checklist
   - rollback plan
   - v0.8.0 unchanged
   - no tag creation
   - no release creation
   - no push tags

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

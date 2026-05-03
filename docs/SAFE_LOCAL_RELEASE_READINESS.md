# Safe-Local Release Readiness

This document is safe-local release readiness evidence. It is not a tag
authorization, release authorization, or instruction to publish artifacts.

## Status

- safe-local release readiness: ready for human review
- release/tag preparation checklist: `docs/RELEASE_TAG_PREPARATION.md`
- no tag authorization
- no release creation
- no push tags
- git push origin main only
- verify v0.8.0 unchanged before any future release work

## Quality gate checklist

- run `git status --short`
- run `git rev-list --left-right --count origin/main...HEAD`
- run `git diff --check`
- run `.venv/bin/ruff check .`
- run full pytest: `.venv/bin/python -m pytest -q -rx`
- verify `git tag --points-at HEAD` before deciding release/tag scope
- verify remote `v0.8.0` still points to the expected annotated tag and peeled
  commit

## Manual smoke checklist

- manual smoke checklist only; do not call real providers by default
- inspect `tests/fixtures/mcp_config/safe-mcp.json`
- inspect `tests/fixtures/local_config/agent.local.json`
- load Skill fixture descriptor without executing tools
- build Subagent fake delegation request/result without starting a child agent
- review local trace and ToolResult docs without wiring runtime/executor

## Known limitations

- known limitations: real MCP external integration remains deferred
- runtime trace wiring remains deferred
- ToolResult executor migration remains deferred
- real Skill install/execution remains deferred
- real Subagent provider delegation remains deferred
- release/tag remains deferred until explicit authorization

## Release/tag preparation

`docs/RELEASE_TAG_PREPARATION.md` contains the planning-only pre-tag
verification commands, human authorization checklist, and rollback plan. It does
not authorize tag creation, release creation, or pushing tags.

## Safety boundaries

- no real external integration
- no real MCP endpoint
- no real provider/network call
- no real home config write
- no real skill/subagent dirs
- no memory activation
- no broad runtime/tool executor migration

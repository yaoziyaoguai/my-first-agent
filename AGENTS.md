# AGENTS.md

This file is repo-specific guidance for coding agents working on
`my-first-agent` at `/Users/jinkun.wang/work_space/my-first-agent`.
It captures the project rules that repeatedly appear in evidence packets so
future work can stay scoped without relying on a giant prompt each time.

## Project identity

- The project is `my-first-agent`; it is not the coding agent's identity.
- Work on branch `main` unless the user explicitly says otherwise.
- The expected remote is `https://github.com/yaoziyaoguai/my-first-agent.git`.
- `v0.8.0` is the Memory architecture foundation release. Do not create,
  delete, retarget, or push tags without explicit user authorization.

## Safety boundaries

- no .env
- no agent_log.jsonl contents
- no real sessions/runs
- no real MCP config
- no real skill dirs
- no real subagent dirs
- no private data
- no secret output, secret logging, or env secret expansion
- no real LLM/provider/MCP calls
- no real MCP endpoint connection or server reachability check
- no real server command execution
- no writing real home config or sensitive paths
- public documentation research is allowed only when it does not upload repo
  content, private data, logs, config, or secrets.

## Architecture rules

- Preserve existing architecture.
- no broad refactor
- no framework migration
- no LangGraph conversion
- no memory activation unless explicitly authorized.
- Do not rewrite stable runtime/memory/tool executor paths for elegance.
- Keep CLI adapters thin; service/use-case layers own semantics; presenters own
  output.
- Tool, MCP config, Skill, and Subagent work must not bypass runtime/tool
  policy.
- Skill/Subagent work must be fake-first, local-only, and fixture/sample based.
- parent runtime remains in control for child capability/delegation boundaries.

## TDD and quality gates

- For behavior changes, write Red tests first and confirm they fail for the
  intended reason.
- Keep changes surgical and tied to the selected roadmap pack.
- Run targeted tests for touched areas.
- Run `git diff --check`.
- Run `.venv/bin/ruff check .`.
- Run `.venv/bin/python -m pytest -q -rx`; pytest exit code must be 0.
- Known xfails should remain explicit and must not be hidden by skipping,
  deleting, or weakening tests.

## Git and publishing

- Commit only scoped, explainable files.
- Use controlled push only: `git push origin main`.
- no push --tags
- no push --all
- no force push
- no `git push origin v0.8.0` unless explicitly authorized.
- Do not modify remotes.

## Evidence packet standard

Every large pack should end with an evidence packet containing:

- repo status and ahead/behind
- files changed and why they are in scope
- Red/Green evidence
- quality gates and exit codes
- commit hash and push verification
- safety checklist
- P0/P1/P2/P3 risk review
- final verdict and recommended next pack

Stop and ask the user only for P0/P1/P2 blockers, unknown dirty diffs,
out-of-scope production changes, sensitive/private data risk, tag/release
requests, real external integration, or broad refactor pressure.

## Code comments and docs

Add Chinese learning comments/docstrings in key production code, tests, and docs
when they explain architecture boundaries, policy decisions, state transitions,
or why a fake/local-only seam exists.

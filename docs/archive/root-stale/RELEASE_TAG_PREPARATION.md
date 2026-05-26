# Release / Tag Preparation

This document is **planning-only** release/tag preparation evidence for the
Remaining Roadmap Completion Autopilot. It is not authorization to create a tag,
publish a release, push tags, mutate `v0.8.0`, or change the remote.

## Scope

- release/tag preparation checklist
- pre-tag verification commands
- human authorization checklist
- rollback plan for failed local preparation
- no tag creation
- no release creation
- no push tags
- verify `v0.8.0 unchanged`

中文学习边界：release preparation 只能把“是否具备进入人工 review / tag 授权”的
证据整理清楚；它不能替代用户的显式 release/tag 决策。这样可以继续推进 roadmap
completion，而不会把 checklist 误执行成真实发布动作。

## Pre-tag verification commands

Run these commands before asking for explicit release/tag authorization:

1. `pwd`
2. `git branch --show-current`
3. `git status --short --untracked-files=all`
4. `git rev-list --left-right --count origin/main...HEAD`
5. `git rev-parse HEAD`
6. `git ls-remote origin main`
7. `git tag --points-at HEAD`
8. `git cat-file -t v0.8.0`
9. `git rev-parse v0.8.0^{commit}`
10. `git ls-remote --tags origin | grep 'refs/tags/v0.8.0'`
11. `git diff --check`
12. `.venv/bin/ruff check .`
13. `.venv/bin/python -m pytest -q -rx`

Expected preparation result:

- branch is `main`
- remote is `https://github.com/yaoziyaoguai/my-first-agent.git`
- working tree is clean
- `origin/main...HEAD` is `0 0`
- `v0.8.0` is an existing annotated tag
- `v0.8.0` peeled commit remains unchanged
- no new tag exists at `HEAD` unless separately authorized
- all quality gates pass

## Human authorization checklist

Before any real release/tag action, the user must explicitly decide:

- release version and tag name
- whether the release is notes-only or artifact-bearing
- whether to create an annotated tag
- whether to push that specific tag
- whether to create a GitHub release
- final known limitations text

The following remain prohibited during preparation:

- no tag creation
- no tag deletion
- no tag retargeting
- no `git push --tags`
- no `git push --all`
- no force push
- no release creation

## Safety checklist

- do not read `.env`
- do not read `agent_log.jsonl` contents
- do not read real `sessions/` or `runs/`
- do not read real MCP config
- do not call a real provider/LLM/MCP endpoint
- do not execute real MCP server commands
- do not write real home config
- do not enter memory activation
- do not rewrite runtime/checkpoint/tool executor paths

## Rollback plan

Preparation-only changes should be limited to docs/tests. If a local
preparation command fails:

- do not create a tag to “finish” the process
- keep the failing evidence in the local terminal output
- fix only scoped P3/P4 docs/test drift if the fix is obvious and safe
- stop for user guidance if the failure requires tag mutation, external
  credentials, private config, real provider/MCP calls, broad migration, or
  force push

If an accidental local tag is created during a future authorized release flow,
do not push it automatically. Stop and ask for explicit remediation because tag
mutation is outside this planning-only document.

## Relationship to safe-local release readiness

`docs/SAFE_LOCAL_RELEASE_READINESS.md` states that the repository is ready for
human review. This document adds the release/tag-specific preflight and human
authorization checklist. Together they prepare review; neither document performs
the release.

The final no-tag authorization design packet is
`docs/RELEASE_TAG_AUTHORIZATION_PACKET.md`.

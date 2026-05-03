# Release/Tag Authorization Packet

This packet prepares a future release/tag decision. It is **not** release
execution: no actual tag, no push tags, and no release happen in this pack.

## Release readiness summary

Completed:

- safe-local roadmap closure
- release/tag preparation planning
- final roadmap completion evidence
- human review packet
- full test/ruff/diff quality gates in the latest packs

Still deferred:

- actual tag creation
- tag push
- GitHub release creation
- any release artifact publication

Known limitations:

- real MCP endpoint/resources/prompts/sampling/roots remain deferred
- runtime trace implementation remains deferred
- ToolResult executor/provider/checkpoint migration remains deferred
- real Skill/Subagent activation remains deferred

Safety guarantees:

- no actual tag
- no push tags
- no release
- no `v0.8.0` mutation
- no force push

## Pre-tag verification checklist

Run immediately before any future tag authorization:

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

Expected outputs:

- pwd is `/Users/jinkun.wang/work_space/my-first-agent`
- branch is `main`
- working tree is clean
- `origin/main...HEAD` is `0 0`
- `v0.8.0` is unchanged
- no untracked sensitive files are present in the commit scope
- tests and lint pass

## Tag authorization checklist

The explicit human sentence required before tag creation should name:

- exact action: create an annotated tag
- proposed tag name
- target commit hash
- whether to push that specific tag
- whether to create a GitHub release

Example authorization sentence:

> I authorize creating annotated tag `<tag-name>` at `<target commit hash>` and
> pushing only that tag after rerunning the pre-tag verification checklist.

The proposed tag name and target commit hash must be re-evaluated immediately
before execution. This packet does not choose or create them.

## No-tag safety statement

This pack does not:

- create a tag
- delete a tag
- retarget a tag
- push tags
- create a release
- push `v0.8.0`

## Rollback / recovery plan

Exact review anchor: rollback / recovery plan.

If the wrong commit is selected:

- do not create a tag
- rerun `git rev-parse HEAD` and `git ls-remote origin main`
- update the proposed target commit hash in the human authorization sentence

If local/remote diverges:

- do not tag
- do not rebase, merge, or force push automatically
- stop for explicit user guidance

If tests fail before tag:

- do not tag
- preserve the failing output
- fix only scoped P3/P4 docs/test drift if safe
- stop if the failure implies real secrets, external services, broad migration,
  or tag mutation

## Human review packet

Before any future release/tag authorization, review:

- `docs/HUMAN_REVIEW_PACKET.md`
- `docs/FINAL_ROADMAP_COMPLETION_EVIDENCE.md`
- `docs/SAFE_LOCAL_RELEASE_READINESS.md`
- `docs/RELEASE_TAG_PREPARATION.md`

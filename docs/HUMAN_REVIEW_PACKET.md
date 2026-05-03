# Human Review Packet

This packet is **review-only** evidence for a human reviewer. It does not grant
no tag authorization, no release authorization, no real MCP endpoint authorization,
and no runtime/tool migration authorization.

## Review checklist

Reviewers should inspect:

1. `docs/ROADMAP.md`
2. `docs/ROADMAP_COMPLETION_AUTOPILOT.md`
3. `docs/REMAINING_ROADMAP_COMPLETION_AUTOPILOT.md`
4. `docs/RELEASE_TAG_PREPARATION.md`
5. `docs/MCP_EXTERNAL_INTEGRATION_READINESS.md`
6. `docs/RUNTIME_TRACE_TOOLRESULT_MIGRATION.md`
7. `docs/SAFE_LOCAL_RELEASE_READINESS.md`
8. `AGENTS.md`

中文学习边界：human review 是决策入口，不是执行入口。reviewer 可以决定下一步是否
授权 release/tag、真实 MCP external integration 或 runtime migration；但本文件本身
不执行任何真实动作，也不改变已有安全边界。
This review checklist links quality gate evidence, the authorization decision
matrix, and P0/P1/P2 stop conditions in one review-only packet.
Exact review anchors: authorization decision matrix; P0/P1/P2 stop conditions.

## Quality gate evidence

The latest Remaining Roadmap packs recorded these gates:

- docs contracts passed
- MCP dry-run readiness contracts passed
- runtime trace / ToolResult compatibility contracts passed
- `.venv/bin/ruff check .` passed
- `git diff --check` passed
- full `.venv/bin/python -m pytest -q -rx` passed

The reviewer should rerun the commands before any release/tag authorization.

## Authorization decision matrix

| Decision | What it would authorize | What is still prohibited without that decision |
|---|---|---|
| Release/tag authorization | a specific tag/release plan after preflight | tag creation, tag push, GitHub release |
| Real MCP integration authorization | a specific endpoint/config/transport checklist | real endpoint, token/secret read, network reachability |
| Runtime trace implementation authorization | a small runtime trace adapter slice | broad runtime rewrite, checkpoint migration |
| ToolResult migration authorization | a staged compatibility shim / executor boundary slice | broad tool_executor rewrite, provider message migration |
| Skill/Subagent activation authorization | separate real activation design | external skill install/execution, real LLM delegation |

## P0/P1/P2 stop conditions

Stop review and ask for remediation if any evidence requires:

- reading `.env`
- reading `agent_log.jsonl` contents
- reading real `sessions/` or `runs/`
- reading real MCP config or secret
- connecting to a real MCP endpoint
- calling a real LLM/provider/MCP service
- executing a real external server command
- writing real home config
- broad runtime/tool_executor/checkpoint/memory migration
- tag mutation or push tags without explicit authorization
- force push or remote modification

## Review conclusion template

Human reviewers can record one of:

- accepted for actual release/tag authorization discussion
- accepted for real MCP external integration design discussion
- accepted for runtime trace / ToolResult migration design discussion
- needs remediation before any authorization

This packet intentionally does not choose for the reviewer.

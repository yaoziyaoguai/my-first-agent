# Real MCP Integration Slice Design

This is a design packet for future real MCP integration. It does not connect to
a real MCP endpoint, read real MCP config, read secrets, execute server
commands, or make a network call.

## Scope

Future real MCP integration would eventually:

- load an explicitly authorized MCP config path
- validate transport settings
- establish a bounded MCP client connection
- discover tools/resources only after authorization
- register MCP tools through explicit opt-in guardrails
- preserve confirmation and ToolResult boundaries

Out of scope now:

- no real MCP endpoint
- no real MCP config
- no secret read
- no network call
- no server reachability check
- no command execution
- no runtime/tool_executor rewrite

## Fake-first integration lane

Exact review anchor: fake-first integration lane.

- fixture MCP config: `tests/fixtures/mcp_config/safe-mcp.json`
- fake server descriptor: `tests/fixtures/minimal_mcp_stdio_server.py`
- dry-run mode: `agent.mcp_external_readiness.build_mcp_external_readiness_report`
- no-op connection strategy: parse and report what would require authorization,
  without starting a transport
- contract tests: safe path policy, redaction, no transport/runtime imports, and
  no external process spawn for non-stdio transports

## Explicit opt-in guardrails

- explicit user authorization needed before real connection
- no default real config
- no home config reads
- no env secret expansion
- no server reachability checks unless authorized
- no command execution during dry-run
- registered MCP tools must remain high-risk and confirmation-required
- MCP client/transport must not import runtime/checkpoint/TUI layers

## Integration contract

Input shape:

- explicit config path
- explicit server name
- explicit transport type
- explicit timeout
- explicit authorization context

Output shape:

- readiness status
- redacted server summary
- would-register / would-discover evidence
- structured failure modes
- safety manifest

Failure modes:

- unsafe path
- invalid config
- unsupported transport
- missing authorization
- timeout
- malformed protocol response
- server-side error

Redaction requirements:

- never print token/secret/env values
- preserve env var names only when safe
- no secret values in repr, logs, snapshots, or docs fixtures

Permission boundaries:

- config parser validates shape only
- readiness report is no-op
- transport handles protocol only after authorization
- registry opt-in controls model-visible tools
- runtime remains parent controller

## Test plan

- no secret leak
- no real network
- no real config read
- no server execution
- invalid config rejection
- dry-run evidence
- confirmation policy remains `always`
- ToolResult legacy compatibility remains stable

## Staged implementation plan

Exact review anchor: staged implementation plan.

1. Stage 1: fake/dry-run only
2. Stage 2: explicit config path but still no secret expansion
3. Stage 3: real connection only after authorization
4. Stage 4: telemetry/evidence if needed

## Risk review

Exact review anchor: risk review.

- secret risk: mitigate with redaction, explicit path policy, no env expansion
- network risk: no reachability checks until authorized
- tool execution risk: confirmation-required registry opt-in
- user config risk: no default home config reads
- rollback plan: unregister MCP tools, keep legacy ToolResult path, preserve config
  backup when writes are authorized

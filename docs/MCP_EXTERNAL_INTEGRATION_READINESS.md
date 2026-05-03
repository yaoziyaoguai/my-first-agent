# MCP External Integration Readiness

This document records fake-first readiness for future real MCP external
integration. It is **dry-run only** planning and contract evidence, not
authorization to connect to a real MCP endpoint, read real MCP config, validate
server reachability, execute a real server command, or access network resources.

## Current readiness status

- MCP config management is complete for safe fixture/tmp paths.
- MCP local stdio fixture validation exists for protocol shape and registry
  opt-in.
- Real external transports remain deferred.
- Real resources/prompts/sampling/roots remain deferred.
- Real auth, token handling, and endpoint reachability remain deferred.

中文学习边界：MCP external integration 的最小安全推进方式是 fake-first。也就是先把
配置、descriptor、legacy ToolResult 映射、confirmation、registry opt-in 和
transport error 边界固定住；真实 endpoint/auth/network 只能在用户明确授权后进入。
This readiness pack is dry-run only and relies on explicit opt-in guardrails,
the local stdio fixture, and the authorization checklist below.

## Safe assets already available

- `agent.mcp_config`: parser/model/path policy/redaction
- `agent.mcp_config_service`: list/inspect/validate/plan/apply workflow semantics
- `agent.mcp_config_cli`: thin developer CLI adapter
- `agent.mcp`: config/descriptor/client protocol/fake client/registry opt-in seam
- `agent.mcp_stdio`: local stdio fixture transport only
- `tests/fixtures/mcp_config/safe-mcp.json`: fake config fixture
- `tests/fixtures/minimal_mcp_stdio_server.py`: local fixture server

These assets do not read `.env`, do not expand env secrets, do not read real
home MCP config, and do not connect to external MCP services.

## Explicit opt-in guardrails

Future real MCP integration must preserve these guardrails:

- server configs are inert until explicitly enabled
- MCP tools never enter the base registry by import side effect
- MCP tool names use the `mcp__server__tool` namespace
- registered MCP tools require confirmation by default
- MCP client/transport does not import runtime/checkpoint/TUI layers
- config parser/service/presenter do not import transport/network/runtime layers
- dry-run only checks must not execute configured server commands
- no network reachability check without a separate authorization pack

## Dry-run only contract

Before any real external transport work, the next pack may add dry-run checks
that:

- parse a fake config fixture
- inspect enabled/disabled status
- explain which tools would be registered
- render redacted diff/evidence
- refuse real home config paths
- refuse secret-like paths
- refuse http/sse/streamable_http execution through `StdioMCPClient`

The dry-run must not:

- no real MCP endpoint
- no secret read
- connect to a real MCP endpoint
- perform a network reachability check
- read a token, `.env`, or real user config
- execute a configured external server command
- install external dependencies
- write runtime/checkpoint/memory state

## Authorization checklist

Real MCP external integration requires explicit user approval for each item:

1. exact fake-to-real slice scope
2. transport type: stdio, http, sse, or streamable_http
3. whether a real endpoint may be contacted
4. whether server reachability may be validated
5. whether a specific non-secret config path may be read
6. how credentials will be provided without logging or expansion
7. allowed timeout and process cleanup semantics
8. rollback behavior for failed registration
9. quality gates and manual smoke commands

Until that approval exists, all work remains fake-first and dry-run only.

## Stop conditions

Stop and ask for guidance if the implementation requires:

- real MCP endpoint
- real token/secret
- real user MCP config
- network call
- server reachability validation
- external process outside test fixtures
- broad runtime/tool executor rewrite
- checkpoint/memory migration

## Relationship to MCP config management

`docs/MCP_CONFIG_MANAGEMENT.md` owns developer workflow configuration safety.
This document owns readiness for the future external integration boundary. The
two must remain separate: config management can plan and apply safe config
changes, but it must not become an MCP client or runtime brain.

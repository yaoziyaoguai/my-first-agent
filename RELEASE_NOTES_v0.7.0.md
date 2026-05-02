# Release Notes v0.7.0 — Tooling Foundation / MCP Readiness

> Status: `v0.7.0` has been tagged and pushed. This file also records
> post-release dogfooding closure evidence added after the tag.

## Added

- Added internal ToolSpec metadata for local tools: capability, risk level, output policy,
  confirmation label, and meta-tool flag.
- Added a focused ToolResult contract seam for legacy string/prefix outcome classification.
- Added shared FileMutation path-safety helper for project-root checks used by `write_file`
  and `edit_file`.
- Added MCP architecture seam:
  - `MCPServerConfig`
  - `MCPToolDescriptor`
  - `MCPCallResult`
  - `MCPClient` protocol
  - `FakeMCPClient`
  - explicit `register_mcp_tools()` opt-in adapter
- Added minimal local stdio MCP validation:
  - `StdioMCPClient`
  - local stdio fixture server
  - initialize / list_tools / call_tool coverage
  - server error, malformed response, unknown tool, and timeout coverage
- Added `docs/MCP_READINESS.md` to document current MCP scope, safety boundaries, and next steps.

## Changed

- Narrowed the base/default tool registry so future Skill lifecycle tools are not exposed by default.
- Kept MCP tools out of the base/default registry; MCP tools require explicit opt-in and default
  to `confirmation="always"`.
- Split `tool_registry.execute_tool()` internally into focused pre-hook, dispatch, post-hook,
  and normalization helpers without changing its public signature.
- Updated `docs/ROADMAP.md` to mark Tooling Foundation and local stdio MCP validation as release
  review candidates.
- Documented that MCP CLI config management is a future thin adapter, not a replacement for TUI and
  not a closure blocker for this milestone.

## Fixed

- Fixed `edit_file` project-root parity so file mutations cannot edit paths outside the project root.
- Fixed the default toolset boundary by removing `install_skill` from default auto-registration while
  keeping the implementation available for explicit future use.
- Fixed MCP result mapping so content blocks are converted back into the existing legacy string
  ToolResult contract instead of leaking list/structured content into runtime classification.

## Tests

- Added registry, ToolSpec, ToolResult, shell, file safety, output policy, and responsibility boundary tests.
- Added tests proving `install_skill` is not in the base/default registry but remains explicitly importable.
- Added tests for `edit_file` project-root safety, including relative, absolute, and parent-directory escapes.
- Added MCP architecture tests for config parsing, opt-in registry integration, fake list/call, and boundaries.
- Added local stdio MCP integration tests covering initialize, list_tools, call_tool, confirmation,
  legacy ToolResult mapping, malformed response, server error, unknown tool, and timeout behavior.
- Final quality gate evidence:
  - `git diff --check`: pass
  - `.venv/bin/ruff check .`: pass
  - MCP related pytest: pass
  - tool registry / executor / file safety related pytest: pass
  - full pytest: pass with existing expected xfails
- Post-release dogfooding closure:
  - first-round self-dogfooding covered code reading, sandbox write, tool failure,
    Ask User / free-text, checkpoint/resume, and MCP local list/call;
  - second-round dogfooding added multi-step read/write/read-back, Ask User restore
    via temp checkpoint, MCP failure path, and confirmation-pressure smoke;
  - `tests/test_second_round_dogfooding_smoke.py` keeps the closure evidence executable.

## Docs

- Updated `docs/ROADMAP.md` with Tooling Foundation completion state and MCP readiness boundaries.
- Added `docs/MCP_READINESS.md` with:
  - current MCP scope
  - config-file vs CLI responsibilities
  - local stdio validation steps
  - explicit safety boundaries
  - next-stage recommendations

## Known limitations

- Current MCP stdio support is a minimal local validation seam, not a full MCP SDK/spec replacement.
- No external/reference MCP server has been connected.
- No HTTP, SSE, or Streamable HTTP transport is implemented.
- ToolResult remains a legacy string/prefix contract; structured ToolResult migration is future work.
- `tool_executor.py` still owns pending/checkpoint/log/display orchestration and should only be slimmed by
  future small slices.

## Not included in this release

- Full MCP resources support.
- Full MCP prompts support.
- MCP sampling.
- MCP roots.
- Production remote MCP server authentication.
- MCP CLI config management.
- Broad third-party MCP server catalog.
- Release packaging automation.
- Push/tag/release execution.

## Next steps

- Human review of the post-release dogfooding closure commit.
- Decide whether to push the closure docs/tests commit to `origin/main`.
- Plan MCP CLI config management as a thin adapter over the MCP config source of truth,
  only after the closure evidence is accepted.
- Plan external/reference MCP server validation with explicit authorization for any networking, secrets, or
  filesystem sandbox paths.

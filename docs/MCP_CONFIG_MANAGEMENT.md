# MCP Config Management

This document records the safe MCP config management surface. It is a developer
workflow for parsing, validating, presenting, planning, and safely applying
configuration changes to explicit test fixtures or temporary files.

## Scope

- explicit safe fixture path: `tests/fixtures/mcp_config/safe-mcp.json`
- explicit `tmp_path` config files created by tests
- parser / validator / redaction model
- thin CLI adapter for list, inspect, validate, plan-add, plan-remove, and apply
- plan-first apply with `--yes`, backup, deterministic JSON serialization, and
  redacted diff evidence

## Safety boundaries

- no real MCP endpoint
- no real home config
- no real MCP config
- no .env
- no server execution
- no network call
- no env secret expansion
- no runtime/checkpoint/memory activation

## Why this fixture exists

The fixture gives review and dogfooding a stable fake config without asking the
agent to inspect private user MCP settings. The configured command is text only:
config management must not start the server or validate reachability.

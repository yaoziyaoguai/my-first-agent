# Local Config Foundation

This document records the Stage 8 local config foundation as a fake/local,
reviewable fixture. It is not an installer, setup wizard, runtime configuration
loader, or provider connector.

## Scope

- explicit safe fixture path: `tests/fixtures/local_config/agent.local.json`
- explicit `tmp_path` files created by tests
- local data model only: project profile, safety policy, module toggles, model
  provider metadata
- fail-closed defaults for network, real MCP, real home writes, and module
  toggles

## Safety boundaries

- no real home config
- no .env
- no `agent_log.jsonl`
- no real `sessions/` or `runs/`
- no env secret expansion
- no provider/network call
- no runtime/checkpoint/memory activation
- no installer or setup path

## Why this fixture exists

The fixture gives reviewers and future tests a stable fake config without asking
the agent to read private local settings. The loader may parse this fixture or a
test-created temporary file, but it must not scan user directories or infer a
default config location.

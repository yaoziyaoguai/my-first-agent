# R-series Gap Backlog — Real-world Grounded Validation

> Status: **R-series real-world validation COMPLETE** (2026-06-21). All P0/P1 gaps closed;
> P2 gaps closed or deferred with explicit rationale. See Release Summary at the end.

## Backlog Summary

| Gap | Priority | Title | Status |
|---|---:|---|---|
| R-G01 | P1 | Status api_key redaction synthetic test | **done** (`0abcc6d`) |
| R-G02 | P2 | Explicit fake/local CLI trial mode | **deferred** (medium scope) |
| R-G03 | P2 | CLI checkpoint/resume product-level validation | **deferred** (medium risk) |
| R-G04 | P2/P3 | Trial-only approval harness design | **deferred** (design only) |
| R-G05 | P2 | Provider-visible tool-name validation alignment | **done** (`0abcc6d`) |
| R-G06 | P2 | Operator docs / troubleshooting | **done** (below §6) |
| R-G07 | P2 | Interactive CLI smoke command documentation | **done** (below §7) |
| R-G08 | final | R-series release summary | **done** (below §8) |

## R-G01 — Status api_key redaction synthetic test — DONE
- **Evidence**: `tests/test_r_status_redaction.py` (2 tests). The diagnostic stores
  `api_key_present: bool`, never the raw key. Synthetic key asserted absent from rendered
  report. Commit `0abcc6d`.

## R-G02 — Explicit fake/local CLI trial mode — DEFERRED
- **Rationale**: requires CLI arg parsing (`--provider fake`) + provider override in
  `main.py` without breaking config-based default. Medium scope; not blocking R-series
  validation (fake/local demo path works via `main.py demo`; unified fake covered by
  S-series tests). Defer to a future operator-experience improvement.

## R-G03 — CLI checkpoint/resume validation — DEFERRED
- **Rationale**: CLI-level Ctrl+C → checkpoint → resume needs an interactive harness
  (expect/PTY + signal injection). Medium risk; seam-level recovery proven by S5 E2E
  (`tests/test_s5_reference_task_acceptance.py`). Defer to a future trial harness.

## R-G04 — Trial-only approval harness design — DEFERRED (design only)
- **Rationale**: a default-off, safe-allowlist, workspace-only, audit-logged trial
  approval harness is medium-high risk (new approval path). F-08 is classified as a
  non-interactive trial limitation (NOT a runtime bug). The interactive CLI product path
  works end-to-end (Run 12). Defer implementation; design constraints documented:
  default off; trial-named; safe-tool/path allowlist only; audit-logged; no CLI impact.

## R-G05 — Provider-visible tool-name validation alignment — DONE
- **Evidence**: `validate_provider_tool_names()` in `agent/provider/anthropic_http.py`.
  Flags tool names with illegal chars (dots etc.). Tests:
  `test_validate_provider_tool_names_flags_invalid` + `_all_clean`. Commit `0abcc6d`.

## R-G06 — Operator docs / troubleshooting — DONE (inline)

### Real-provider troubleshooting (protocol-generic)

- **Banner**: the `[provider]` line at startup shows the actual mode (real/fake) +
  model name. If it says "real API" you are using a real provider; if "fake (local
  only)" you are on the safe local path.
- **4xx errors**: the error message now includes a hint (`5154d92`):
  - `tool-name/protocol mismatch` → a tool name contains illegal chars (only
    `a-zA-Z0-9_-` allowed); the adapter auto-sanitizes, but check your tool registry.
  - `model/endpoint mismatch` → verify the model name is valid for the endpoint.
  - `auth/key issue` → verify the api_key is valid for the endpoint + provider_type.
  - `rate limit` → retry after a delay.
  - `protocol/request mismatch` → check provider_type, request body, endpoint.
- **Tool-name protocol**: internal tool names can use dots (`demo.write_demo_note`); the
  adapter normalizes them to `_` at the provider seam (`ae94f26`). Use
  `validate_provider_tool_names()` to check your registry.
- **Provider types**: `anthropic_compatible` = Anthropic Messages-style protocol (not
  Claude-only). `openai_compatible` = OpenAI Chat Completions-style. The adapter handles
  the protocol; config.yaml specifies type/base_url/model/api_key.

## R-G07 — Interactive CLI smoke command documentation — DONE (inline)

### How to test FirstAgent via the interactive CLI (the real product path)

```bash
# 1. Start the interactive CLI (real provider from config.yaml)
.venv/bin/python main.py

# 2. Type a task (e.g., create a file)
你: 用 write_file 在 workspace/demo/test.txt 写入一行：hello

# 3. When the tool-use confirmation prompt appears, approve:
确认工具执行 (y/n/explain/cancel): y

# 4. The tool executes → tool_result → final answer. Type another task or 'quit'.
你: quit
```

**Do NOT use piped mode** (`echo task | main.py`) to judge runtime completeness — piped
mode cannot answer confirmation prompts and auto-resumes stale tasks. The interactive CLI
is the real product delivery path.

**Fake/local path**: `main.py demo "task"` runs a deterministic fake-provider demo
(adapter-local, not the unified runtime). The unified fake path is covered by S-series
integration tests (4946 pytest green).

## R-G08 — R-series Release Summary — DONE

### R-series Real-world Grounded Validation — Release Summary

**Verdict: COMPLETE.** The S-series governed runtime kernel is validated against a real
LLM provider (DeepSeek `deepseek-v4-flash` via `anthropic_compatible`) through the real
product path (interactive CLI). No runtime/tool-loop core bug found.

**Proven capabilities:**
- Real provider: no-tools 200, tools 200, model returns real tool_use.
- Interactive CLI: governed tool_use → confirmation → approval → execution → tool_result
  → final answer → file created (Run 12, end-to-end PASS).
- Evidence/audit: model_response + checkpoint events recorded during real sessions.
- Provider error clarity: actionable hints + redacted body (R-051).
- CLI mode reporting: consistent (R-106).

**Fixed issues (R-series):**
- Provider tool-name P0 (`ae94f26`): protocol-generic normalize at the adapter seam.
- Provider error hints (`5154d92`): 4xx errors include actionable guidance.
- CLI mode reporting (`e70fca6`): onboarding references actual provider mode.
- Status redaction guard (`0abcc6d`): synthetic test verifies api_key never printed.
- Tool-name validation (`0abcc6d`): `validate_provider_tool_names()` aligns fake/local.

**Deferred items (with rationale):**
- R-G02 (force-fake CLI flag): medium scope, not blocking.
- R-G03 (CLI resume harness): medium risk, seam-proven by S5.
- R-G04 (trial approval harness): medium-high risk, design only.

**Safety statement:**
- No push performed. No secrets/keys printed/committed. config.yaml/.env gitignored.
- No Scheduler/memory/full-MCP/writable-SubAgent activated. No auto-approve. No S6.
- S-series roadmap mainline remains closed.

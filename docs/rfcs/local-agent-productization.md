# Local Agent Productization RFC

Status: accepted (single unified RFC; supersedes ad-hoc productization gates)

## 1. Context

After v0.8.0 the safe-local foundation is in place: tool registry, tool
executor, policy, ToolResult envelope, local trace foundation, optional runtime
trace sink (RFC 0001 / RFC 0002), MCP CLI safe-config, Skill / Subagent local
MVPs, and readiness dry-run reports.

The remaining gap is **product** rather than **governance**: a brand new user
who clones the repo today still cannot see the agent loop work end-to-end
without first wiring an Anthropic API key. Every "real" path is gated for
safety, and there is no first-class fake demo entry. Third-party reviewers have
correctly flagged that "remediation closure" without a runnable demo feels
incomplete.

## 2. Product goal

Ship the smallest demo that lets a new user observe a complete agent loop
within five minutes of cloning, without any secrets or network access:

- single command (`python main.py demo`)
- default fake provider, no API key required
- deterministic output
- writes only to an explicit demo workspace (`workspace/demo/<run-id>/`)
- exposes task → provider → tool action → tool result → final answer → trace
  summary in one screen

## 3. User-facing flow

```
$ python main.py demo "create a demo note about today's work"
[Local Agent Demo] provider=fake workspace=workspace/demo/20250101T000000Z
Task : create a demo note about today's work
Step 1 write_demo_note → ok
  path   : workspace/demo/20250101T000000Z/note.md
  bytes  : 64
Final: wrote demo note to workspace/demo/20250101T000000Z/note.md
Trace summary (2 events):
  1 tool_call demo.write_demo_note ok
  2 state_transition demo.complete ok
Inspect: open workspace/demo/20250101T000000Z/ for the generated artifact.
```

The user can pass a custom task string. Override workspace with `--workspace`.
Trace summary is rendered inline; the same events can later be persisted by
calling `LocalTraceRecorder` against an explicit tmp path.

## 4. Architecture boundary

- `main.py demo` is a **thin** CLI adapter: argument parsing only, no business
  logic, mirrors the existing `mcp config` / `health` / `logs` subcommand
  pattern.
- `agent/local_demo.py` is the service / use-case layer. It owns:
  - `FakeProvider` (deterministic, no I/O, no network);
  - `resolve_demo_workspace()` path policy;
  - `run_local_demo()` orchestration;
  - `format_demo_result()` presenter.
- Path safety reuses the same approach as `local_trace` and `local_artifacts`:
  reject `.env`, `agent_log.jsonl`, `sessions/`, `runs/`, `memory/`, `skills/`,
  and any path that escapes the demo root.
- ToolResult and trace envelopes reuse `agent.tool_result_contract` and
  `agent.runtime_trace_projection` — no new contract layer.
- `agent/core.py` is **not** modified (architecture-boundary test guards its
  imports). The demo never instantiates the real Anthropic client.
- `tool_executor.py`, `tool_registry.py`, `checkpoint.py`, `memory*`,
  `mcp.py`, runtime brain — all untouched by this slice.

## 5. Current implementation plan

In scope for this RFC:

1. `docs/rfcs/local-agent-productization.md` (this file).
2. `agent/local_demo.py` (service + presenter + fake provider).
3. `main.py demo` thin subcommand.
4. `tests/test_local_demo.py` (happy path, no-API-key, no-network, path
   safety, redaction, trace summary, CLI thin-adapter boundary).
5. README "5-minute fake demo" quickstart section.

Out of scope (deferred, will land via separate RFCs if authorized):

- Real provider opt-in.
- Real MCP opt-in.
- `inspect-last-run` durable trace replay (current demo prints inline summary
  and points at the artifact directory; durable JSONL persistence is a future
  small polish).
- Release / tag.
- Broad runtime trace wiring or tool_executor rewrite.

## 6. Non-goals

- No real LLM call.
- No real MCP call.
- No release / tag.
- No production automation.
- No broad runtime rewrite.
- No tool_executor migration.
- No `.env` read, no `agent_log.jsonl` content read, no real `sessions/` /
  `runs/` read, no real MCP config read, no secret expansion.

## 7. Test strategy

`tests/test_local_demo.py` covers, with red-first style and Chinese learning
docstrings on key cases:

- Happy path: `run_local_demo("create a demo note", workspace=tmp_path)`
  produces deterministic `DemoResult` with one `write_demo_note` step and the
  generated file.
- Default fake provider: `run_local_demo` without explicit provider uses
  `FakeProvider` and exposes `provider="fake"`.
- No API key required: monkeypatched `os.environ` without
  `ANTHROPIC_API_KEY` still completes; demo never imports `anthropic`.
- No network call: dependency-boundary check on `agent/local_demo.py` source
  rejects `requests`, `httpx`, `urllib`, `socket`, `anthropic`, `openai`,
  `agent.core`, `agent.tool_executor`, `agent.checkpoint`.
- Allowed path only: workspace inside `workspace/demo/` or `tempfile.gettempdir()`
  is accepted; `.env`, `agent_log.jsonl`, `sessions/`, `runs/`, `memory/`,
  `skills/`, and arbitrary `/etc/...` paths are rejected with
  `UnsafeDemoPathError`.
- Redaction: a task containing a fake `sk-XXXXXXXX` token has the secret
  redacted in the rendered trace summary.
- CLI thin adapter: `main.py demo` source contains no business logic beyond
  argument parsing and a single call into `agent.local_demo`.

## 8. Future gates

- Real provider opt-in (separate RFC, explicit env flag).
- Real MCP opt-in (separate RFC, explicit env flag).
- `inspect-last-run` durable trace JSONL replay.
- Release / tag.
- Deeper runtime trace wiring (continuation of RFC 0001 / RFC 0002).

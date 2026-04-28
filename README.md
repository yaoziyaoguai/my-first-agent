# my-first-agent

`my-first-agent` is a learning-oriented Agent Runtime prototype. The current
track is **Runtime v0.1**: make the smallest useful agent loop run end to end,
then freeze the graduation criteria before expanding the system.

v0.1 is intentionally narrow. It is not a mature agent framework, not a production safety sandbox, not a complete TUI, and not a Skill or sub-agent platform.

## Runtime v0.1 Scope

The v0.1 runtime is meant to prove this minimal loop:

```text
plan -> user confirms plan -> tools run as needed -> result is produced -> checkpoint is saved
```

The core graduation surface is:

- basic Agent loop
- basic task planning and step execution
- basic tool registration and tool calls
- model message construction
- `tool_use` / `tool_result` pairing
- minimal task status flow
- minimal plan and tool confirmation flow
- checkpoint write/load roundtrip
- CLI output that is readable enough for a user to understand what the agent is doing

## Current Graduation Status

- **B1 complete**: Runtime v0.1 contract and xfail ownership are documented in
  `docs/V0_1_CONTRACT.md`.
- **B2 complete**: minimal CLI output contract is frozen in
  `docs/CLI_OUTPUT_CONTRACT.md` and guarded by regression tests.
- **B3 complete**: the real Anthropic API graduation smoke completed the
  `README.md` -> `summary.md` task. The result is recorded in
  `docs/V0_1_GRADUATION_REPORT.md`.

## Run Tests

From the repository root:

```bash
.venv/bin/python -m ruff check agent/ tests/
.venv/bin/python -m pytest -q
```

Expected v0.1 baseline: no RED tests. Known xfails are documented in
`docs/V0_1_CONTRACT.md` and belong to later versions.

## Run the v0.1 Smoke

The B3 smoke task reads this root `README.md` and writes a Chinese summary to
`summary.md`. `summary.md` is a local smoke artifact and is ignored by git.

Preflight:

```bash
test -f README.md
test -n "$ANTHROPIC_API_KEY"
test ! -e summary.md
```

Start the simple CLI:

```bash
.venv/bin/python main.py
```

Then enter:

```text
请读取仓库根目录 README.md，并把一段中文总结写入 summary.md。
```

During the smoke, approve only the minimal plan and tool calls needed to read
`README.md`, write `summary.md`, and perform necessary checks. Do not use the
smoke to add v0.2/v0.3 features.

## Explicit Non-Goals for v0.1

These areas are intentionally out of scope for v0.1 graduation:

- full Textual backend or persistent shell
- advanced TUI panels, paste handling, or generation cancellation
- mature Skill lifecycle or sub-agent collaboration
- complex topic switch handling, slash commands, or LLM intent classification
- production-grade security sandbox, permission model, or recovery policy
- observer/eval pipeline, cost tracking, or performance SLA

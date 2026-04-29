# my-first-agent

`my-first-agent` is a learning-oriented Agent Runtime prototype. The current
local-first trial track is **Runtime v0.3.x usability**: keep the v0.2 runtime
boundaries intact while making the basic CLI shell, health report, and logs
viewer easier to use offline.

It is not a mature agent framework, not a production safety sandbox, not a complete TUI or Textual IDE, and not a Skill or sub-agent platform.

## Quickstart (local-first trial)

`my-first-agent` is **local-first only**: there is no SaaS, no hosted
service, no remote agent runtime. To try it, clone the repo and run
everything on your own machine.

### Prerequisites

- Python **3.10+** (developed on 3.12)
- macOS / Linux shell (Windows users: WSL recommended)
- Optional: an Anthropic API key if you want to drive the agent with a
  real model. Without one you can still run the test suite and the
  offline `fake` provider for the LLM Processing CLI.

### Setup

```bash
git clone <this repo>
cd my-first-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: configure a real provider. Copy the template and edit values
# locally. Never commit your real .env.
cp .env.example .env
# then open .env and set ANTHROPIC_API_KEY / ANTHROPIC_MODEL if you have them.
```

`.env` is gitignored. `.env.example` only carries variable names and
comments — no real keys.

### Run the basic CLI shell

```bash
.venv/bin/python main.py
.venv/bin/python main.py --shell  # explicit alias for the same basic shell
```

You will see a structured startup banner with session id, cwd, a one-line
health summary, an experimental-Skill notice, and a checkpoint resume
status. The shell prints a compact status line around each turn so you can
see whether the runtime is planning, awaiting confirmation, executing, waiting
for your input, finished, failed, or blocked by policy. Type a task in Chinese
or English; type `quit` to exit.

The four-class tool outcome contract from v0.2
(`completed` / `failed` / `rejected` / `user_rejected`) is preserved.
"Rejected" means a safety policy blocked the call (e.g. project-outside
write); "user_rejected" means **you** chose not to approve a tool call
when prompted.

### Subcommands you should know

```bash
.venv/bin/python main.py health           # readable maintenance report
.venv/bin/python main.py health --json    # machine-readable JSON
.venv/bin/python main.py logs             # tail recent runtime events
.venv/bin/python main.py logs --tail 100  # see further back
```

`health` warnings (large `agent_log.jsonl`, accumulated `sessions/`,
workspace lint findings) are **non-fatal** maintenance signals, not crashes.
The runtime **never** auto-archives or deletes `agent_log.jsonl` /
`sessions/` / `workspace/`. Suggested cleanup commands are printed for
you to run manually.

### Run the test suite

```bash
.venv/bin/python -m ruff check agent/ tests/ llm run_logger.py main.py
.venv/bin/python -m pytest -q
```

Expected baseline: ruff clean, ~688 passed, 3 permanent xfails (each
xfail message documents which future version owns the gap).

### Local runtime artifacts

Running the agent creates these files under your clone. **All are
gitignored** and will not be uploaded if you push your fork:

| Path | What it is | Cleanup |
|---|---|---|
| `agent_log.jsonl` | runtime event log (jsonl) | `mv agent_log.jsonl agent_log.$(date +%s).jsonl.bak` |
| `sessions/` | per-session checkpoint snapshots | manual delete after review |
| `state.json` | active checkpoint pointer | deleted automatically when the runtime returns to idle |
| `runs/`, `summary.md` | LLM Processing CLI artifacts (only if you use `process`) | manual delete |
| `workspace/` | sandbox for tools that write files | manual delete |
| `memory/` | learning notes (committed copy is the project baseline) | do not delete in a fork |

If you ever wonder where something came from, run `python main.py logs`
and filter by session, event type, or tool name.

### Common questions

- **"Missing ANTHROPIC_API_KEY" on startup** — the basic CLI shell needs a
  real key to talk to a model. The test suite and the LLM Processing
  `fake` provider do not.
- **Resume banner says "未发现断点"** — there is no checkpoint to resume
  from. Just type a new task.
- **Health report shows `warn`** — these are maintenance warnings, not
  errors. Each warning includes a `current_value` / `path` / `risk` and a
  copy-paste command to address it.
- **Skill commands** — Skills in this repo are an **experimental,
  prompt-injection-level scaffold**. There is no Skill marketplace, no
  per-Skill tool whitelist, and no slash-command handler. See
  `docs/V0_3_SKILL_SYSTEM_STATUS.md`.
- **Final-answer questions** — the model's final answer should not
  contain "do you want me to ...?"-style waiting questions; if the agent
  truly needs your input it will use the `request_user_input` tool and
  pause. See `docs/CLI_OUTPUT_CONTRACT.md` §14.

For a deeper local-trial walkthrough, see
`docs/V0_3_LOCAL_TRIAL.md`.

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

## LLM Processing MVP

The v0.2 LLM processing surface is intentionally small and auditable:

```bash
.venv/bin/python main.py scan README.md
.venv/bin/python main.py preflight
.venv/bin/python main.py preflight --provider anthropic --live
.venv/bin/python main.py process README.md
.venv/bin/python main.py status
.venv/bin/python main.py status --run-id <run_id>
```

`scan` only reports file metadata such as path, hash, size, and mtime.
`preflight` checks provider configuration without sending a live request by
default. `process` runs the minimal triager/distiller/linker pipeline and writes
`state.json` plus `runs/*.jsonl`. `status` reads those metadata files and
tolerates missing or partially corrupted audit logs. `status --run-id` reads a
specific `runs/<run_id>.jsonl` file without modifying local state. Raw input
text, prompts, completions, API keys, and provider request/response bodies must
not be written to `state.json`, `runs/*.jsonl`, or status/preflight output.
`state.json` and `runs/*.jsonl` are local run artifacts and are ignored by git.
The status schema is documented in `docs/LLM_AUDIT_STATUS_SCHEMA.md`; provider
configuration is documented in `docs/LLM_PROVIDER_CONFIG.md`; the live provider
smoke playbook is documented in `docs/LLM_PROVIDER_LIVE_SMOKE.md`; the live
smoke audit result is documented in `docs/LLM_PROVIDER_LIVE_SMOKE_REPORT.md`;
the v0.2 LLM Processing capability matrix is documented in
`docs/LLM_PROCESSING_CAPABILITY_MATRIX.md`. Provider failures are classified
into stable safe codes such as `missing_config`, `auth_error`, `rate_limited`,
`network_error`, `timeout`, `bad_response`, `unknown_provider`, and
`provider_error`.

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

## Runtime v0.2 Status

v0.1 has graduated. **Runtime v0.2 is now released as `v0.2.0`**.
v0.2 adds:

- runtime state-machine + event boundary invariants with regression tests
- checkpoint / resume semantics (idle residue is silently cleaned)
- error recovery and loop guard invariants
- four-class CLI tool outcome contract (`completed` / `failed` / `rejected` / `user_rejected`)
- workspace-out-of-bounds write block, sensitive-file read block, shell blacklist
- offline LLM Processing CLI: `process` / `scan` / `status` / `preflight`,
  with provider error classification and secret/raw-text leak protection
- `python main.py health` subcommand for non-blocking maintenance warnings

v0.2 still **does not** include: full Textual TUI, Skill maturation, sub-agent
collaboration, Reflect / Self-Correction, generation cancellation, or paste
burst handling. Those are explicitly v0.3 or later.

See `RELEASE_NOTES_v0.2.md`, `docs/V0_2_RC_DECISION.md`, and
`docs/V0_2_MANUAL_SMOKE_RESULT.md` for details.

## Runtime v0.3 Status (in progress · usability track)

v0.3 is the **usability** track on top of v0.2. It is **not** a feature
big-bang. See `docs/V0_3_PLANNING.md` for full scope.

**v0.3 M1 — Basic CLI Shell MVP** is landed locally:

```text
────────────────────────────────────────────────────────────
  Runtime v0.3 basic CLI shell
────────────────────────────────────────────────────────────
  session : d6066c90  (full: d6066c90-b6ed-...)
  cwd     : /your/project
  health  : 3 warn (workspace_lint, log_size, session_accumulation); 详情：python main.py health
────────────────────────────────────────────────────────────
  输入 'quit' 退出。
  Health: python main.py health；Logs: python main.py logs --tail 50。
  Skill 是实验性能力（v0.3 M3 状态澄清，详见 docs/V0_3_SKILL_SYSTEM_STATUS.md）。

  📭 resume : 未发现断点，可以直接开始新任务。
你: 
```

Run `python main.py` or the explicit alias `python main.py --shell`. This is a
basic CLI shell with TUI-like structured output, not a full Textual IDE. The
four-class tool outcome contract from v0.2 (`completed` / `failed` /
`rejected` / `user_rejected`) is preserved unchanged.

**v0.3 M2 — Health Maintenance report** is landed locally:

```
$ python main.py health           # 结构化人类可读报告（每项含 risk + 建议命令）
$ python main.py health --json    # 机器可读 JSON，schema 稳定
```

报告中每个 check 都展示 `current_value` / `path` / `risk` / `suggested action`；
所有「建议」都是给你复制粘贴的命令，**Runtime 永不自动归档或删除**
`agent_log.jsonl` / `sessions/` / `workspace/`。详细维护命令见
`docs/V0_3_HEALTH_MAINTENANCE.md`。

**v0.3 M3 — Skill system honesty pass** is landed locally:

- 启动屏不再印 `'/reload_skills' 重新加载 skill`（该 slash command 历史上
  **没有 handler**，纯属误导）
- 启动屏现在明示 「Skill 是实验性能力」并指向 `docs/V0_3_SKILL_SYSTEM_STATUS.md`
- 当前 `agent/skills/` 子系统是 **prompt 注入级别的实验性脚手架**：
  没有 sub-agent、没有 skill 级 tool 权限白名单、没有 activation policy、
  没有 skill 单元测试。详细现状与后续真正 Skill 化路线见
  `docs/V0_3_SKILL_SYSTEM_STATUS.md`。

**v0.3 M4 — Readable observer/logs viewer** is landed locally:

```
$ python main.py logs                          # 默认 tail 50 + 隐藏 runtime_observer
$ python main.py logs --tail 100
$ python main.py logs --session abc12345       # 按 session 前缀
$ python main.py logs --event tool_executed    # 按事件类型
$ python main.py logs --tool calculate         # 按工具名
$ python main.py logs --include-observer       # 显式打开极噪的 runtime_observer
```

输出是单行紧凑摘要（timestamp / 短 session id / event / 结构化元信息），
**不会**展示 raw content / raw tool_result / system_prompt / 完整 checkpoint，
含兜底脱敏（sk-ant- / BEGIN PRIVATE KEY / api_key=…）。完整设计与脱敏边界
见 `docs/V0_3_OBSERVER_LOGS.md`。

v0.3 still **does not** include: full Textual multi-panel, keyboard shortcuts,
Esc / generation cancellation, sub-agent, Reflect / Self-Correction,
Skill marketplace, complex topic switch, slash commands, automatic
log/session/workspace pruning. See `docs/V0_3_PLANNING.md` §2 for the
explicit non-goal list.

**v0.3 patch — final answer / request_user_input protocol fix** (post-tag):

A manual smoke surfaced a UX break: the model wrote a trailing open-ended
question ("need me to adjust some days?") in its final answer in the same
turn as a `mark_step_complete` tool call. Runtime correctly completed the
task on the structured signal, but the user perceived "asked me a question
then refused to wait". Fix is at the protocol boundary, not via keywords:

- `config.SYSTEM_PROMPT` now declares `request_user_input` as the **only**
  signal Runtime treats as "waiting", and forbids mixing waiting-style
  questions with `mark_step_complete` in the same response.
- `agent/model_output_resolution.py` keyword patterns are frozen as a
  legacy fallback (size-capped by tests; new findings go to SYSTEM_PROMPT).
- Guarded by `tests/test_final_answer_user_input_separation.py` (7 tests).

See `docs/V0_3_PLANNING.md` §3.5 and `docs/CLI_OUTPUT_CONTRACT.md` §14
for the full protocol contract.

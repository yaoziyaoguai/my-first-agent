# R-series Trial Failures Register

> Failures + blockers from the 2026-06-21 trial. Each entry: `id | case | type |
> severity | observed | root cause / note | suggested fix (for a later repair batch)`.
> No runtime bug was fixed during the trial.

## P0 — blocks all real-world use

### F-01 (R-006 / R-101) — real provider tools call HTTP 400 — FIXED
- **type**: `provider/tool integration issue` (protocol-boundary tool-name handling)
- **severity**: P0 (was) → **FIXED** (commit `ae94f26`)
- **observed (original)**: unified-runtime tools call → `http_status:400` every call
  (no-tools call was already 200).
- **CORRECTED root cause** (an earlier draft of this register wrongly blamed config/model
  — that was wrong; **user config is correct**): provider-visible tool names violated the
  anthropic-compatible tool/function-name constraint `^[a-zA-Z0-9_-]+$`. Internal
  namespaced tools use dots (`demo.echo_task_summary`, `demo.write_demo_note`); the
  `anthropic_compatible` adapter sent them verbatim. DeepSeek's `/anthropic` endpoint
  (Anthropic-style protocol) rejected the dotted names — a **protocol-boundary /
  tool-name handling bug, not user config**. FakeProvider never validated tool names, so
  the bug was hidden in fake/local. Evidence: server error `Invalid 'tools[0].function.name':
  string does not match pattern '^[a-zA-Z0-9_-]+$'` (the `function.name` path is the
  server's internal Anthropic→OpenAI mapping; the sent schema is top-level Anthropic-style
  `{name, description, input_schema}` — confirmed via request capture).
- **fix**: protocol-generic normalize at the `anthropic_compatible` seam — send-time map
  internal name → provider-safe name (illegal chars → `_`, collision-safe stable
  `_2`/`_3` suffixing so `demo.a_b` ≠ `demo.a.b`); response tool_use restore → internal
  name. **No Claude/DeepSeek/model-name special-casing; no config change; no endpoint
  rewrite.** Tests: `tests/test_r_provider_tool_names.py` (7, incl. collision + structure
  guard + stream-shim). Verified on real provider: no-tools 200, tools call **200** (was
  400), model returns a real tool_use (`write_file`).
- **note**: the original "9 of 10 blocked" cascade is now UNBLOCKED at the provider layer;
  see **F-08** for the remaining real-task *completion* gap.

## P1 — category-blocking / security-verify

### F-02 (R-004) — `main.py status` api_key redaction unverified
- **type**: `redaction/security issue`
- **severity**: P1
- **observed**: `main.py status` runs a "Provider Config Diagnostic"; could not safely
  confirm whether it masks the api_key (the verification method was credential scanning,
  which the safety classifier denied — not worked around).
- **suggested fix**: operator confirms `status` redacts the key; if not, mask it in the
  diagnostic renderer before any output sharing.

### F-08 (R-102) — non-interactive trial harness cannot drive the real CLI approval gate
- **type**: `test/harness limitation` (**NOT** a runtime/tool-loop bug)
- **severity**: P2 (trial-automation only; does NOT affect the product delivery path)
- **observed (original, piped)**: in piped/non-interactive mode, the real provider returns
  a tool_use (`write_file`) but the tool is not executed / the target file is not created.
- **root cause (CONFIRMED, code-level)**: (1) `write_file` is a **confirmation-gated**
  tool — the runtime correctly pauses at `awaiting_tool_confirmation`; piped stdin cannot
  answer the `y/n` prompt, so the tool is rejected ("用户未批准"). (2) `session.py:452`
  auto-resumes the most recent task in pipe mode and consumes piped input as the response
  to a pending confirmation, so a stale-pending + new-task mis-routes. This is the
  product's **governance safety behaviour**, not a runtime/tool-loop bug.
- **DECISIVE counter-evidence (Run 12)**: the **interactive CLI** (PTY, real provider)
  completes the same tool_use END-TO-END — model -> tool_use -> confirmation prompt ->
  manual `y` -> tool executed -> file CREATED
  (`workspace/demo/r_trial_interactive_write.txt`) -> final answer -> clean exit. The
  approved -> execute -> tool_result -> final loop (`mediate_pending` ->
  `confirmation_already_approved` -> `execute_pending_tool` -> `append_tool_result`)
  works.
- **classification**: **Case A — non-interactive trial harness limitation.** Do NOT change
  the runtime; do NOT default auto-approve. (Optional future: a trial-only approval
  harness — default off, trial-named, safe-tool/path allowlist, audit-logged — to enable
  non-interactive real trials; recorded as an enhancement item, not implemented.)

## P2 — experience / clarity

### F-03 (R-106) — provider mode banner/onboarding inconsistency
- **type**: `command/docs unclear`
- **severity**: P2
- **observed**: top banner = "真实 API (deepseek-v4-flash)" but onboarding body = "Fake
  provider 安全路径（默认)"; `demo` banner says "真实 API" while `provider=fake`.
- **suggested fix**: make banner + onboarding reflect the **actual** provider path per
  invocation; stop `demo` advertising "real API".

### F-04 (R-015 / R-020) — can't force fake on unified CLI / can't trial CLI resume
- **type**: `test/harness limitation`
- **severity**: P2
- **observed**: config overrides env, so the unified `core.chat()` path always uses the
  configured (real) provider — no CLI flag forces fake; and mid-task Ctrl+C checkpoint
  can't be simulated via piped stdin.
- **suggested fix**: add a CLI flag / env to force fake on the unified path (for safe
  trials); add an interruptible trial harness for CLI-level resume.

### F-05 (R-051) — real-provider 400 error message not actionable
- **type**: `command/docs unclear`
- **severity**: P2
- **observed**: `[Provider 错误] 模型调用失败：http_status:400` gives no hint it's a
  model/endpoint config problem.
- **suggested fix**: on 4xx provider errors, surface "check provider model/endpoint
  config" guidance.

## P3 — hygiene / cosmetic

### F-06 (R-002) — log_size + session_accumulation growth
- **type**: `expected non-goal` (operational hygiene, not a runtime bug)
- **severity**: P3
- **observed**: `agent_log.jsonl` 17.83 MB; 286 session snapshots.
- **suggested fix**: rotate/archive logs + sessions (health already suggests commands).

### F-07 (R-050 / R-053) — `status` undocumented; no real-provider troubleshooting in docs
- **type**: `command/docs unclear`
- **severity**: P3
- **suggested fix**: document `status` (+ its key handling); add a real-provider
  setup/troubleshoot section to README/AGENTS.

## Not-failures (declared non-issues / seam-proven)

- Scheduler/MCP/SubAgent/memory **dormancy** — `deferred-scope boundary issue` but
  **pass** (verified dormant by cr1 tests; not activated). Not a failure; do not "fix"
  by activating.
- Redaction / acceptance classification / ledger recovery / replay / crash-survival —
  **pass at the seam** (S_FINAL TD-012 + S5 tests). No failure recorded; the gap is that
  some are only seam-proven, not yet product-CLI-proven (depends on F-01 being fixed).

## Failure-type tally (after F-01 fix + interactive-CLI F-08 reclassification)

| type | count |
|---|---:|
| real provider failure / provider-tool integration | 0 (**F-01 FIXED** `ae94f26`) |
| redaction/security issue | 1 (F-02 — `status` key-redaction unverified) |
| command/docs unclear | 3 (F-03 banner, F-05 error-clarity, F-07 docs) |
| test/harness limitation | 2 (F-04 force-fake/resume harness; **F-08 non-interactive approval** — NOT a runtime bug; interactive CLI proven to work) |
| expected non-goal (hygiene) | 1 (F-06 log/session growth) |
| runtime bug | **0** (interactive CLI completes a real tool_use end-to-end — Run 12) |
| recovery/durability bug | **0** (seam-proven) |
| evidence/audit/replay bug | **0** |
| acceptance classification issue | **0** |
| deferred-scope boundary issue | **0** (dormancy verified) |

# R-series Trial Failures Register

> Failures + blockers from the 2026-06-21 trial. Each entry: `id | case | type |
> severity | observed | root cause / note | suggested fix (for a later repair batch)`.
> No runtime bug was fixed during the trial.

## P0 — blocks all real-world use

### F-01 (R-006 / R-101) — real provider HTTP 400 on every unified-runtime call
- **type**: `real provider failure` / `provider/tool integration issue`
- **severity**: P0
- **observed**: `printf '<turn>\n' | python main.py` → `[Provider 错误] 模型调用失败：http_status:400`, every call (reproduced twice). No real turn ever completes.
- **root cause**: provider config mismatch — `anthropic_compatible` adapter →
  `https://api.deepseek.com/anthropic` with model `deepseek-v4-flash`, which is **not a
  valid model for that endpoint** (DeepSeek's Anthropic-compat endpoint expects
  `deepseek-chat` / `deepseek-reasoner`). Bad Request, not auth. (Not a kernel bug.)
- **suggested fix (repair batch)**: correct the model (e.g. `deepseek-chat`) or endpoint
  in `config/config.yaml`; then verify the `anthropic_compatible` adapter request shape
  against DeepSeek's `/anthropic` schema. Re-run R-006/R-101/R-102.
- **note**: this single failure **cascades into 9 of 10 blocked cases** (all real coding
  tasks R-010..014, real multi-step R-102, real tool/timeout trials).

## P1 — category-blocking / security-verify

### F-02 (R-004) — `main.py status` api_key redaction unverified
- **type**: `redaction/security issue`
- **severity**: P1
- **observed**: `main.py status` runs a "Provider Config Diagnostic"; could not safely
  confirm whether it masks the api_key (the verification method was credential scanning,
  which the safety classifier denied — not worked around).
- **suggested fix**: operator confirms `status` redacts the key; if not, mask it in the
  diagnostic renderer before any output sharing.

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

## Failure-type tally

| type | count |
|---|---:|
| real provider failure / provider-tool integration | 1 (F-01, cascades to 9 blocked) |
| redaction/security issue | 1 (F-02) |
| command/docs unclear | 3 (F-03, F-05, F-07) |
| test/harness limitation | 1 (F-04) |
| expected non-goal (hygiene) | 1 (F-06) |
| runtime bug | **0** |
| recovery/durability bug | **0** (seam-proven; CLI-level blocked by F-01/harness) |
| evidence/audit/replay bug | **0** |
| acceptance classification issue | **0** |
| deferred-scope boundary issue | **0** (dormancy verified) |

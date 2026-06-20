# R-series Trial Run Log

> Chronological record of trial runs (2026-06-21). Outputs are paraphrased / filtered;
> no API key or secret was printed at any point. Commands run in the repo with the
> configured provider (`anthropic_compatible` → DeepSeek `deepseek-v4-flash`).

## Run 1 — `python main.py --help`
- Exit: 0.
- Observed: onboarding banner `[provider] mode=anthropic_compatible (真实 API — model=deepseek-v4-flash)`. Lists `demo` / interactive (`python main.py`) / `health` / `logs --tail 50`. Notes "real provider 401 已记录为 config/auth concern". Onboarding body says "Fake provider 安全路径（默认，无 API key，不联网)".
- Finding: **banner says real; onboarding body says Fake-default** — inconsistent (R-106).
- Result: pass (with inconsistency finding).

## Run 2 — `python main.py health`
- Exit: 0.
- Observed: `整体状态：⚠️ warn`. `backup_accumulation` pass (0 .bak). `log_size` **warn** (17.83 MB, `agent_log.jsonl`). `session_accumulation` **warn** (286 snapshots, `sessions`). `workspace_lint` skip.
- Result: pass (warn) — operational hygiene items.

## Run 3 — `python main.py logs --tail 5`
- Exit: 0.
- Observed: structured evidence events with timestamps, session ids, subsystem/operation/phase/status, event_id. Hint: `--include-observer` / `--session <id>`.
- Result: pass — clean, auditable operator output.

## Run 4 — `python main.py demo "Reply with exactly one line: r-trial-real-ok"`
- Exit: 0.
- Observed: banner `[provider] mode=anthropic_compatible (真实 API ...)` then `[Local Agent Demo] provider=fake`. `demo.write_demo_note -> ok`, wrote `workspace/demo/20260620T165303Z/note.md` (140 bytes). Trace: 2 events (tool_call, state_transition).
- Finding: **`demo` advertises real API but runs `provider=fake`** — misleading (R-106).
- Result: pass (fake/local demo path works; artifact written).

## Run 5 — real unified runtime, piped single turn: `printf 'Reply with exactly one line: r-trial-real-ok\n' | python main.py`
- Exit: 0 (runtime did not crash).
- Observed: banner real. Onboarding: "📭 resume : 未发现断点". `[系统] 未生成多步计划，按单步处理。`. Then **`[Provider 错误] 模型调用失败：http_status:400`**. Run summary: 循环次数 1, 未调用工具 / 未写入 Memory / 未委托 SubAgent / 未激活 Skill, 结果：正常结束. Session-end memory extraction skipped.
- Finding: **real provider returns HTTP 400** — the unified runtime cannot complete a single real turn (R-006 / R-101). Runtime degraded gracefully (no crash).
- Result: FAIL (real provider).

## Run 6 — config non-secret fields (to classify the 400)
- Read (non-secret only, key excluded): `provider.type: anthropic_compatible`, `model: deepseek-v4-flash`, `base_url: https://api.deepseek.com/anthropic`.
- Classification: `deepseek-v4-flash` is **not a valid model for DeepSeek's Anthropic-compatible endpoint** (expects `deepseek-chat` / `deepseek-reasoner`) → 400 Bad Request. This is a **provider config / integration mismatch**, not a kernel bug.
- Result: root-cause identified for R-006/R-101.

## Run 7 — real unified runtime, 2nd turn (reproducibility): `printf 'What is 2+2? ...\n' | python main.py`
- Exit: 0.
- Observed: `[Provider 错误] 模型调用失败：http_status:400`; `结果：正常结束`.
- Result: FAIL — 400 reproduced (R-006 confirmed consistent).

## Run 8 — recovery/durability probe
- Top-level checkpoint file: none (`.checkpoint*` no match). `memory/checkpoints` dir exists. No active checkpoint was saved from the piped sessions (they ended cleanly / the real turn failed before any durable step).
- Finding: CLI-level mid-task checkpoint resume could not be trialled (real task 400s before a durable point; Ctrl+C-mid-task not simulable via piped stdin). Seam-level recovery proven by S5 E2E.
- Result: blocked (harness limitation) — R-020.

## Run 9 — `python main.py status` (provider-config diagnostic)
- The command exists and prints a "Provider Config Diagnostic".
- **Security probe blocked**: verifying whether `status` redacts the api_key required a
  credential-scanning method, which the safety classifier denied. Not worked around.
- Finding: `status` is a **key-exposure surface to verify** — operator must confirm it
  masks the api_key before sharing output (R-004).
- Result: blocked (security-verification item).

## Run 10 — extension-boundary / governance (reference, not re-run)
- Scheduler dormancy: `test_architecture_boundaries.py::test_cr1_*` + `runtime_integration/test_action_scheduler.py` — pass (dormant).
- MCP/SubAgent/memory dormancy: existing S3/S5 boundary tests — pass (controlled/read-only).
- Redaction (mediator preview + record_evidence metadata): `test_final_legacy_redaction.py` (S_FINAL TD-012) — pass.
- Ledger recovery/replay/crash-survival: S5 E2E + `test_s5_ledger_*` — pass.
- Acceptance classification: S5/S4/S2 acceptance tests — pass.
- Result: all seam-level pass; not activated; no regression.

## Aggregate (this run)
- Real provider path: **broken (HTTP 400 every call)** — the single dominant finding.
- Fake/local demo path: works (artifacts written).
- CLI operator surface (help/health/logs): works; minor inconsistency + hygiene warns.
- Evidence/audit: working even on the failed real turn.
- Graceful degradation: runtime survives provider failure.

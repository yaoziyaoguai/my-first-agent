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

## Run 11 — provider tool-name fix + real validation (2026-06-21, after `ae94f26`)
- **Fix**: protocol-generic tool-name normalize at the `anthropic_compatible` seam
  (`agent/provider/anthropic_http.py`); dotted internal names → provider-safe on send,
  restored on the tool_use response; collision-safe. Tests:
  `tests/test_r_provider_tool_names.py` (7 pass).
- **Real provider no-tools call**: status **200** (basic path always worked).
- **Real provider tools call (13 tools)**: status **200** (was 400). Sent tool names all
  match `^[a-zA-Z0-9_-]+$` (no dots). Model returned a real **tool_use `write_file`**.
- **Real grounded task completion**: PARTIAL — the model called `write_file` but the
  runtime made only 2 provider calls (no tool-execution follow-up) and the target file was
  NOT created → new finding **F-08** (real-task completion gap), recorded, not fixed.
- **Corrected root cause**: the 400 was provider-visible dotted tool names (protocol
  boundary), NOT user config/model. FakeProvider hid it.
- Result: **P0 FIXED**; new top issue = F-08.

## Aggregate (after fix rerun)
- Real provider path: **works** for chat + tool calls (200 + tool_use); P0 fixed.
- Real-task end-to-end completion: **not yet proven** (F-08).
- Fake/local + CLI operator surface: unchanged (healthy).
- Evidence/audit, graceful degradation: hold.

## FirstAgent delivery / testing model (calibration, 2026-06-21)

1. **Primary delivery entry**: the **interactive CLI** (`python main.py`, plain backend;
   the real product path a user experiences).
2. **Three paths, three purposes**:
   - **Interactive CLI** = the real product delivery experience (governed, with live
     tool-confirmation prompts the user answers).
   - **Piped / non-interactive** (`stdin | main.py`) = an *automation/trial* shape, NOT
     the default product form. It cannot answer interactive confirmation prompts.
   - **Unit/integration tests** = deterministic fake/local coverage (governed test
     policies / fake approval handlers, test-only).
3. **The interactive CLI represents the real delivery experience.** A defect there is a
   product defect; a defect only in piped/trial mode is a trial-harness limitation, not a
   product bug.
4. **tool_use → approval**: a mutating tool (e.g. `write_file`) returns a tool_use; the
   CLI shows a confirmation prompt (`确认工具执行 (y/n/explain/cancel)`); the user
   approves/rejects. This is a **governance safety feature, not a bug** — it must NOT be
   auto-bypassed by default.
5. **Approved tool_result → model**: on approval, `mediate_pending` →
   `confirmation_already_approved` → `execute_pending_tool` → `append_tool_result(messages)`
   → the next provider turn consumes the tool_result and produces a final answer. (Code
   path confirmed; behaviour confirmed in Run 12.)
6. **session/evidence/ledger/audit** record: the tool_use request, the approval decision,
   the tool_result, and the final answer (structured evidence events + checkpoint).
7. **R-trial classification rule**: distinguish (a) product/runtime bug (interactive CLI
   fails), (b) trial-harness limitation (only piped/non-interactive fails), (c)
   operator/docs issue (prompts unclear). Do NOT infer a runtime bug from piped-only
   behaviour; do NOT default auto-approve to make piped trials pass.

## Run 12 — interactive CLI real-provider tool-use trial (PTY via `expect`, 2026-06-21)
- **Path**: real product path — `main.py` under a PTY (isatty=True, NOT pipe), real
  provider, fresh session (checkpoint cleared).
- **Task**: `write_file` → `workspace/demo/r_trial_interactive_write.txt` (content
  `R-series interactive CLI smoke success`).
- **Observed**: model returned a real tool_use → **confirmation prompt shown** →
  approved with `y` → **tool executed** → **file CREATED** with exact content →
  **final answer** ("写入成功 ✅ … 文件已写入，无异常") → returned to `你:` prompt →
  `quit` → clean exit. Loop: 工具调用 1 次, 结果 正常结束; 21 messages; session saved.
- **Result**: **PASS** — the interactive CLI completes a real governed tool_use
  end-to-end (tool_use → confirmation → approve → execute → tool_result → final →
  artifact).
- **Minor note**: the loop iterated ~18 times for one write_file (model re-planned
  repeatedly: "正在规划工具调用…" several times). It COMPLETED correctly; the verbosity
  is an operator-experience/efficiency observation, not a correctness bug.
- **F-08 reclassification**: this PROVES the runtime/tool-loop is NOT broken.
  F-08 = **non-interactive trial harness limitation** (Case A), not a runtime bug.

## Run 13 — piped/non-interactive mode re-check (trial path)
- `session.py:452`: in pipe mode (`not sys.stdin.isatty()`), the runtime **auto-resumes
  the most recent task** and consumes piped input as the response to any pending
  confirmation. If a stale `awaiting_tool_confirmation` checkpoint exists, a newly-piped
  task is mis-routed as tool feedback → the tool is rejected ("用户未批准") → no
  execution. This is **design behaviour for piped automation**, and it does NOT affect
  the interactive CLI (which does not auto-resume; verified in Run 12 — fresh start).
- **Result**: piped mode cannot drive the real confirmation gate (no human to approve),
  and auto-resume can mis-route when a stale pending exists. This is a **trial-harness
  limitation**, not a product/runtime bug. A future trial-only approval harness (default
  off, trial-named, safe-tool/path allowlist, audit-logged) could enable non-interactive
  real trials — recorded as an enhancement item, NOT implemented (no default auto-approve).

## Aggregate (after interactive-CLI calibration)
- **Interactive CLI (real delivery path): WORKS** end-to-end for a real governed
  tool_use (Run 12). The runtime/tool-loop has **no core bug**.
- F-08 = **non-interactive trial harness limitation** (piped can't approve; piped
  auto-resume mis-routes) — trial-only, does not affect the product path.
- P0 (provider tool-name 400) remains FIXED (`ae94f26`).
